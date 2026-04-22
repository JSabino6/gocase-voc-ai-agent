from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    cloudscraper = None

from src.config import DATA_RAW_DIR, get_settings

BASE_URL = "https://www.reclameaqui.com.br"
LIST_URL = "https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/"
DEFAULT_OUTPUT_PATH = DATA_RAW_DIR / "reclameaqui_feedback_auto.csv"
PAGE_SIZE_HINT = 5

COMPLAINT_PATH_RE = re.compile(r"^/go-case/[^?#]+_[A-Za-z0-9-]+/?$")
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
RELATIVE_RE = re.compile(r"ha\s*(\d+)\s*(hora|horas|dia|dias|minuto|minutos)", re.IGNORECASE)

NEXT_DATA_SCRIPT_ID = "__NEXT_DATA__"
MOJIBAKE_HINTS = ("Ã", "Â", "â")
COMPLAINT_KEY_HINTS = {
    "complaint",
    "description",
    "message",
    "content",
    "body",
    "text",
    "problem",
    "question",
    "consumer",
}
BOILERPLATE_HINTS = {
    "pesquise reputacao de empresas antes de comprar",
    "toda empresa tem problema",
    "reclamacoes parecidas",
    "termos de uso",
    "politica de privacidade",
    "central de ajuda",
    "para consumidor",
    "para empresas",
    "ra ads",
}

BOILERPLATE_CUT_PATTERNS = [
    re.compile(r"\s*-\s*gocase\s*-\s*reclame\s*aqui.*$", re.IGNORECASE),
    re.compile(r"\s*-\s*reclame\s*aqui.*$", re.IGNORECASE),
    re.compile(r"pesquise\s+reputa(?:cao|ção)\s+de\s+empresas\s+antes\s+de\s+comprar.*$", re.IGNORECASE),
    re.compile(r"toda\s+empresa\s+tem\s+problema.*$", re.IGNORECASE),
]

RESOLVED_HINTS = {
    "respondida",
    "respondido",
    "resolvida",
    "resolvido",
    "avaliada",
    "avaliado",
    "encerrada",
    "encerrado",
    "finalizada",
    "finalizado",
    "solucionada",
    "solucionado",
}

UNRESOLVED_HINTS = {
    "nao respondida",
    "nao respondido",
    "sem resposta",
    "pendente",
    "aberta",
    "em andamento",
}


def _empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "feedback_id",
            "source",
            "source_url",
            "author",
            "feedback_date",
            "raw_text",
            "initial_category",
            "channel",
            "status",
        ]
    )


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.split())


def _collapse_spaces(value: str) -> str:
    return " ".join(str(value or "").split())


def _extract_status(text: str) -> str:
    normalized = _normalize_text(text)

    if any(hint in normalized for hint in UNRESOLVED_HINTS):
        return "nao resolvida"
    if any(hint in normalized for hint in RESOLVED_HINTS):
        return "resolvida"

    if "respondida" in normalized:
        return "resolvida"
    if "nao respondida" in normalized:
        return "nao resolvida"

    return "nao informada"


def _status_matches(status_text: str, status_filter: str) -> bool:
    if status_filter == "Todas":
        return True

    status_normalized = _normalize_text(status_text)
    is_resolved = "resolvida" in status_normalized

    if status_filter == "Resolvidas":
        return is_resolved
    if status_filter in {"Não Resolvidas", "Nao Resolvidas"}:
        return not is_resolved
    return True


def _parse_relative_datetime(relative_text: str, now_utc: datetime) -> datetime | None:
    normalized = _normalize_text(relative_text)

    if "agora" in normalized or "hoje" in normalized:
        return now_utc
    if "ontem" in normalized:
        return now_utc - timedelta(days=1)

    match = RELATIVE_RE.search(normalized)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    if unit.startswith("hora"):
        return now_utc - timedelta(hours=amount)
    if unit.startswith("dia"):
        return now_utc - timedelta(days=amount)
    if unit.startswith("minuto"):
        return now_utc - timedelta(minutes=amount)
    return None


def _extract_relative_text(text: str) -> str:
    normalized = _normalize_text(text)
    match = RELATIVE_RE.search(normalized)
    if match:
        return f"ha {match.group(1)} {match.group(2)}"
    if "ontem" in normalized:
        return "ontem"
    if "hoje" in normalized:
        return "hoje"
    if "agora" in normalized:
        return "agora"
    return ""


def _extract_date(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    return match.group(1)


def _looks_like_mojibake(text: str) -> bool:
    if not text:
        return False
    hits = sum(text.count(token) for token in MOJIBAKE_HINTS)
    return hits >= 4


def _decode_html_bytes(raw_bytes: bytes) -> str:
    # Try utf-8 first, then fallback to legacy encodings used by the target site.
    try:
        utf8_text = raw_bytes.decode("utf-8")
        if not _looks_like_mojibake(utf8_text):
            return utf8_text
    except UnicodeDecodeError:
        pass

    for encoding in ("cp1252", "latin-1"):
        try:
            decoded = raw_bytes.decode(encoding)
            if decoded:
                return decoded
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def _is_boilerplate_text(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in BOILERPLATE_HINTS)


def _strip_boilerplate_segments(text: str) -> str:
    cleaned = _collapse_spaces(text)
    if not cleaned:
        return ""

    for pattern in BOILERPLATE_CUT_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    cleaned = _collapse_spaces(cleaned)
    if _is_boilerplate_text(cleaned):
        return ""
    return cleaned


def _looks_like_complaint_text(text: str) -> bool:
    collapsed = _collapse_spaces(text)
    if len(collapsed) < 40:
        return False
    if _is_boilerplate_text(collapsed):
        return False
    return True


def _extract_best_candidate(candidates: list[tuple[int, str]]) -> str:
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _extract_complaint_from_next_data(soup: BeautifulSoup) -> str:
    script = soup.find("script", id=NEXT_DATA_SCRIPT_ID, attrs={"type": "application/json"})
    if script is None:
        script = soup.find("script", id=NEXT_DATA_SCRIPT_ID)
    if script is None:
        return ""

    payload_raw = script.get_text(strip=True)
    if not payload_raw:
        return ""

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return ""

    candidates: list[tuple[int, str]] = []

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = f"{path}.{key}" if path else str(key)
                walk(value, next_path)
            return

        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
            return

        if not isinstance(node, str):
            return

        text = _collapse_spaces(node)
        if not _looks_like_complaint_text(text):
            return

        path_lower = path.lower()
        key_hint_score = sum(1 for hint in COMPLAINT_KEY_HINTS if hint in path_lower)
        score = len(text) + (key_hint_score * 60)
        candidates.append((score, text))

    walk(payload)
    return _extract_best_candidate(candidates)


def _extract_complaint_from_dom(soup: BeautifulSoup) -> str:
    selectors = [
        "#complaint-description",
        "[data-testid='complaint-description']",
        "[id*='complaint-description']",
        "div[class*='complaint-description']",
        "p[class*='complaint-description']",
    ]

    candidates: list[tuple[int, str]] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = _collapse_spaces(node.get_text(" ", strip=True))
            if not _looks_like_complaint_text(text):
                continue
            score = len(text) + 120
            if "complaint-description" in selector:
                score += 80
            candidates.append((score, text))

    return _extract_best_candidate(candidates)


def _extract_complaint_from_schema_ld(soup: BeautifulSoup) -> str:
    candidates: list[tuple[int, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            node_type = _normalize_text(str(node.get("@type", "")))

            for key in ("text", "description", "reviewBody", "articleBody"):
                value = node.get(key)
                if isinstance(value, str):
                    text = _collapse_spaces(value)
                    if not _looks_like_complaint_text(text):
                        continue
                    score = len(text)
                    if node_type in {"question", "review", "comment"}:
                        score += 100
                    candidates.append((score, text))

            for value in node.values():
                walk(value)
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload_raw = script.get_text(strip=True)
        if not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        walk(payload)

    return _extract_best_candidate(candidates)


def _extract_complaint_description(soup: BeautifulSoup, fallback_snippet: str) -> str:
    # Priority order: Next.js hydration JSON, rendered complaint block, then JSON-LD.
    description = _extract_complaint_from_next_data(soup)
    if not description:
        description = _extract_complaint_from_dom(soup)
    if not description:
        description = _extract_complaint_from_schema_ld(soup)
    if not description:
        description = fallback_snippet
    return _strip_boilerplate_segments(description)


def _http_get(url: str) -> str:
    settings = get_settings()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    response = requests.get(url, headers=headers, timeout=settings.request_timeout_seconds)
    if response.status_code < 400:
        return _decode_html_bytes(response.content)

    if response.status_code == 403 and cloudscraper is not None:
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        cloud_response = scraper.get(url, headers=headers, timeout=settings.request_timeout_seconds)
        cloud_response.raise_for_status()
        return _decode_html_bytes(cloud_response.content)

    response.raise_for_status()
    return _decode_html_bytes(response.content)


def _extract_list_entries(html: str, extraction_limit: int) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href:
            continue

        absolute_url = urljoin(BASE_URL, href)
        parsed_path = urlparse(absolute_url).path
        if not COMPLAINT_PATH_RE.match(parsed_path):
            continue

        if absolute_url in seen_urls:
            continue

        title = _strip_boilerplate_segments(anchor.get_text(" ", strip=True))
        if len(title) < 10:
            continue

        container = anchor.find_parent(["article", "li", "section", "div"])
        container_text = _collapse_spaces(container.get_text(" ", strip=True) if container else title)

        status = _extract_status(container_text)
        relative_text = _extract_relative_text(container_text)

        snippet = container_text
        if title in snippet:
            snippet = _collapse_spaces(snippet.replace(title, "", 1))
        snippet = _strip_boilerplate_segments(snippet)
        if len(snippet) < 20:
            snippet = title

        entries.append(
            {
                "source_url": absolute_url,
                "title": title,
                "status": status,
                "relative_text": relative_text,
                "snippet": snippet,
            }
        )
        seen_urls.add(absolute_url)

        if len(entries) >= extraction_limit:
            break

    return entries


def _build_list_page_url(page_number: int) -> str:
    if page_number <= 1:
        return LIST_URL
    return f"{LIST_URL}?pagina={page_number}"


def _collect_paginated_entries(extraction_limit: int, max_pages: int | None = None) -> list[dict[str, str]]:
    # Use a conservative cap derived from page size to avoid crawling too many pages.
    effective_max_pages = max_pages
    if effective_max_pages is None:
        effective_max_pages = max(2, int(extraction_limit / PAGE_SIZE_HINT) + 2)

    all_entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for page_number in range(1, effective_max_pages + 1):
        page_url = _build_list_page_url(page_number)

        try:
            html = _http_get(page_url)
        except Exception:
            break

        page_entries = _extract_list_entries(html, extraction_limit=max(extraction_limit, 50))
        if not page_entries:
            break

        new_count = 0
        for entry in page_entries:
            source_url = entry.get("source_url", "")
            if not source_url or source_url in seen_urls:
                continue
            all_entries.append(entry)
            seen_urls.add(source_url)
            new_count += 1

            if len(all_entries) >= extraction_limit:
                return all_entries[:extraction_limit]

        # If a page yields no new complaint URLs, pagination likely ended.
        if new_count == 0:
            break

    return all_entries[:extraction_limit]


def _extract_detail(entry: dict[str, str]) -> dict[str, str]:
    html = _http_get(entry["source_url"])
    soup = BeautifulSoup(html, "lxml")

    page_title = ""
    heading = soup.find("h1")
    if heading:
        page_title = _strip_boilerplate_segments(heading.get_text(" ", strip=True))

    if not page_title:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        page_title = _strip_boilerplate_segments(og_title.get("content", "") if og_title else "")

    if not page_title:
        page_title = _strip_boilerplate_segments(entry["title"])
    if not page_title:
        page_title = _collapse_spaces(entry["title"])

    description = _extract_complaint_description(soup, fallback_snippet=entry.get("snippet", ""))

    detail_context = _collapse_spaces(
        f"{page_title} {description} {soup.get_text(' ', strip=True)[:2400]}"
    )
    date_str = _extract_date(detail_context)

    status_from_detail = _extract_status(detail_context[:1800])
    status = status_from_detail if status_from_detail != "nao informada" else entry.get("status", "nao informada")

    if len(description) < 20:
        description = _strip_boilerplate_segments(entry.get("snippet", ""))

    return {
        "title": page_title or entry["title"],
        "description": description,
        "date_str": date_str,
        "status": status,
    }


def _as_iso_date(date_str: str) -> str:
    if not date_str:
        return ""
    parsed = pd.to_datetime(date_str, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def collect_reclameaqui_complaints(
    extraction_limit: int = 50,
    status_filter: str = "Todas",
    hours_window: int | None = None,
) -> pd.DataFrame:
    extraction_limit = max(1, int(extraction_limit))
    now_utc = datetime.now(UTC)
    cutoff = (now_utc - timedelta(hours=int(hours_window))) if hours_window else None

    list_entries = _collect_paginated_entries(extraction_limit=extraction_limit)
    if not list_entries:
        return _empty_output_frame()

    records: list[dict[str, str]] = []

    for entry in list_entries:
        try:
            detail = _extract_detail(entry)
        except Exception:
            detail = {
                "title": entry.get("title", ""),
                "description": entry.get("snippet", ""),
                "date_str": "",
                "status": entry.get("status", "nao informada"),
            }

        if not _status_matches(detail["status"], status_filter):
            continue

        feedback_date_iso = _as_iso_date(detail["date_str"])
        if not feedback_date_iso and entry.get("relative_text"):
            relative_dt = _parse_relative_datetime(entry["relative_text"], now_utc=now_utc)
            if relative_dt:
                feedback_date_iso = relative_dt.strftime("%Y-%m-%d")

        if cutoff is not None:
            if not feedback_date_iso:
                continue
            feedback_dt = pd.to_datetime(feedback_date_iso, errors="coerce", utc=True)
            if pd.isna(feedback_dt):
                continue
            if feedback_dt.to_pydatetime() < cutoff:
                continue

        raw_text = _collapse_spaces(f"{detail['title']} {detail['description']}")
        if len(raw_text) < 20:
            continue
        if _is_boilerplate_text(raw_text):
            continue

        stable_url = str(entry["source_url"]).strip().rstrip("/")
        digest = hashlib.sha1(stable_url.encode("utf-8")).hexdigest()[:12]

        records.append(
            {
                "feedback_id": digest,
                "source": "reclameaqui_auto",
                "source_url": entry["source_url"],
                "author": "Consumidor RA",
                "feedback_date": feedback_date_iso,
                "raw_text": raw_text,
                "initial_category": "reclamacao",
                "channel": "complaint_site_auto",
                "status": detail["status"],
            }
        )

    if not records:
        return _empty_output_frame()

    frame = pd.DataFrame(records)
    frame = frame.drop_duplicates(subset=["feedback_id"], keep="last")
    return frame


def save_reclameaqui_auto_feedback(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DEFAULT_OUTPUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        _empty_output_frame().to_csv(target, index=False, encoding="utf-8")
    else:
        df.to_csv(target, index=False, encoding="utf-8")
    return target


if __name__ == "__main__":
    dataframe = collect_reclameaqui_complaints(extraction_limit=20)
    save_reclameaqui_auto_feedback(dataframe)
    print(f"Reclame Aqui auto rows collected: {len(dataframe)}")
