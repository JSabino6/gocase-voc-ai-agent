from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.config import DATA_RAW_DIR, get_settings

EBIT_URL = "https://www.ebit.com.br/gocase"
EBIT_SEED_PATH = DATA_RAW_DIR / "ebit_manual_seed.csv"
DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
NEGATIVE_HINTS = (
    "atraso",
    "demor",
    "ruim",
    "pessim",
    "nunca",
    "defeito",
    "problema",
    "caro",
    "juros",
    "frete",
    "nao recebi",
)
STOP_WORDS = {
    "TODOS",
    "ELOGIOS",
    "RECLAMACOES",
    "AVALIACOES DOS CONSUMIDORES",
    "SOBRE",
    "ADDITIONAL LINKS",
}


def _empty_reviews_frame() -> pd.DataFrame:
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
        ]
    )


def _normalize_line(line: str) -> str:
    cleaned = line.replace("\xa0", " ").strip()
    return " ".join(cleaned.split())


def _is_stop_line(line: str) -> bool:
    upper = line.upper()
    return upper in STOP_WORDS


def _find_author(lines: list[str], date_index: int) -> str:
    for index in range(date_index - 1, max(-1, date_index - 8), -1):
        candidate = lines[index]
        if not candidate:
            continue
        if DATE_PATTERN.match(candidate):
            continue
        if _is_stop_line(candidate):
            continue
        if len(candidate) > 80:
            continue
        return candidate
    return "Anonimo"


def _clean_review_text(text: str) -> str:
    cleaned = text.strip().strip('"').strip("'")
    return " ".join(cleaned.split())


def _infer_initial_category(text: str) -> str:
    lower = text.lower()
    return "reclamacao" if any(hint in lower for hint in NEGATIVE_HINTS) else "elogio"


def fetch_ebit_html(url: str = EBIT_URL, timeout_seconds: int | None = None) -> str:
    settings = get_settings()
    timeout = timeout_seconds or settings.request_timeout_seconds
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_ebit_reviews(html: str, source_url: str = EBIT_URL) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    lines = [_normalize_line(line) for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]

    records: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(lines):
        current = lines[cursor]
        if DATE_PATTERN.match(current):
            feedback_date = current
            author = _find_author(lines, cursor)
            next_cursor = cursor + 1
            text_chunks: list[str] = []

            while next_cursor < len(lines):
                look_ahead = lines[next_cursor]
                if DATE_PATTERN.match(look_ahead):
                    break
                if _is_stop_line(look_ahead):
                    next_cursor += 1
                    continue
                text_chunks.append(look_ahead)
                next_cursor += 1

            raw_text = _clean_review_text(" ".join(text_chunks))
            if len(raw_text) >= 15:
                digest_base = f"{author}|{feedback_date}|{raw_text}|{source_url}"
                feedback_id = hashlib.sha1(digest_base.encode("utf-8")).hexdigest()[:12]
                records.append(
                    {
                        "feedback_id": feedback_id,
                        "source": "ebit",
                        "source_url": source_url,
                        "author": author,
                        "feedback_date": feedback_date,
                        "raw_text": raw_text,
                        "initial_category": _infer_initial_category(raw_text),
                        "channel": "review_site",
                    }
                )
            cursor = next_cursor
        else:
            cursor += 1

    if not records:
        return _empty_reviews_frame()

    frame = pd.DataFrame(records)
    frame = frame.drop_duplicates(subset=["feedback_id"], keep="first")
    return frame


def save_ebit_reviews(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DATA_RAW_DIR / "ebit_feedback.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False, encoding="utf-8")
    return target


def load_ebit_seed_reviews(seed_path: Path | None = None) -> pd.DataFrame:
    source_path = seed_path or EBIT_SEED_PATH
    if not source_path.exists():
        return _empty_reviews_frame()

    raw = pd.read_csv(source_path).fillna("")
    required = {"author", "feedback_date", "raw_text", "initial_category"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing required columns in {source_path}: {sorted(missing)}")

    records: list[dict[str, Any]] = []
    for _, row in raw.iterrows():
        text = _clean_review_text(str(row.get("raw_text", "")))
        if len(text) < 15:
            continue

        author = str(row.get("author", "Anonimo")).strip() or "Anonimo"
        feedback_date = str(row.get("feedback_date", "")).strip()
        source_url = str(row.get("source_url", EBIT_URL)).strip() or EBIT_URL
        initial_category = str(row.get("initial_category", "")).strip() or _infer_initial_category(text)

        digest_base = f"{author}|{feedback_date}|{text}|{source_url}"
        feedback_id = hashlib.sha1(digest_base.encode("utf-8")).hexdigest()[:12]
        records.append(
            {
                "feedback_id": feedback_id,
                "source": "ebit_seed",
                "source_url": source_url,
                "author": author,
                "feedback_date": feedback_date,
                "raw_text": text,
                "initial_category": initial_category,
                "channel": "review_site_seed",
            }
        )

    if not records:
        return _empty_reviews_frame()

    return pd.DataFrame(records).drop_duplicates(subset=["feedback_id"], keep="first")


def collect_and_save_ebit_reviews() -> pd.DataFrame:
    df = _empty_reviews_frame()

    try:
        html = fetch_ebit_html()
        df = parse_ebit_reviews(html)
    except Exception:
        df = _empty_reviews_frame()

    if df.empty:
        df = load_ebit_seed_reviews()

    save_ebit_reviews(df)
    return df


if __name__ == "__main__":
    dataframe = collect_and_save_ebit_reviews()
    print(f"Ebit rows collected: {len(dataframe)}")
