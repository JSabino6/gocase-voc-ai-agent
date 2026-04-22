from __future__ import annotations

import hashlib
from pathlib import Path
import unicodedata
from typing import Any

import pandas as pd

from src.config import DATA_RAW_DIR

DEFAULT_INPUT_PATH = DATA_RAW_DIR / "reclameaqui_manual_template.csv"
DEFAULT_OUTPUT_PATH = DATA_RAW_DIR / "reclameaqui_feedback.csv"

OUTPUT_COLUMNS = [
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

REQUIRED_COLUMNS = {
    "source_url",
    "title",
    "description",
    "date",
    "status",
    "initial_category",
}

RESOLVED_STATUS_HINTS = {
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

RA_BOILERPLATE_HINTS = {
    "pesquise reputacao de empresas antes de comprar",
    "toda empresa tem problema",
}


def _build_feedback_id(row: pd.Series) -> str:
    source_url = str(row.get("source_url", "")).strip().rstrip("/")
    if source_url:
        base = source_url
    else:
        base = f"{row.get('title', '')}|{row.get('date', '')}|{row.get('source_url', '')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _ensure_output_schema(df: pd.DataFrame) -> pd.DataFrame:
    local = df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in local.columns:
            local[column] = ""
    return local[OUTPUT_COLUMNS]


def _dedupe_by_source_url(local: pd.DataFrame) -> pd.DataFrame:
    frame = _ensure_output_schema(local).copy()

    url_key = frame["source_url"].fillna("").astype(str).str.strip().str.rstrip("/")
    id_key = frame["feedback_id"].fillna("").astype(str).str.strip()

    frame["_dedupe_key"] = "url::" + url_key
    missing_url = url_key == ""
    frame.loc[missing_url, "_dedupe_key"] = "id::" + id_key[missing_url]

    frame = frame.drop_duplicates(subset=["_dedupe_key"], keep="last")
    return frame.drop(columns=["_dedupe_key"])


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _has_ra_boilerplate(value: str) -> bool:
    normalized = _normalize_text(value)
    return any(hint in normalized for hint in RA_BOILERPLATE_HINTS)


def _drop_low_quality_auto_rows(local: pd.DataFrame) -> pd.DataFrame:
    frame = _ensure_output_schema(local).copy()
    auto_mask = frame["source"].fillna("").astype(str).str.strip() == "reclameaqui_auto"
    low_quality_mask = frame["raw_text"].fillna("").astype(str).map(_has_ra_boilerplate)
    cleaned = frame.loc[~(auto_mask & low_quality_mask)].copy()
    return _ensure_output_schema(cleaned)


def _is_resolved_status(value: str) -> bool:
    normalized = _normalize_text(value)
    return any(hint in normalized for hint in RESOLVED_STATUS_HINTS)


def _status_match(value: str, status_filter: str) -> bool:
    if status_filter == "Todas":
        return True

    resolved = _is_resolved_status(value)
    if status_filter == "Resolvidas":
        return resolved
    if status_filter in {"Não Resolvidas", "Nao Resolvidas"}:
        return not resolved
    return True


def load_reclameaqui_manual(
    input_path: Path | None = None,
    extraction_limit: int | None = None,
    status_filter: str = "Todas",
) -> pd.DataFrame:
    source_path = input_path or DEFAULT_INPUT_PATH
    if not source_path.exists():
        return _empty_output_frame()

    raw = pd.read_csv(source_path)
    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"Missing required columns in {source_path}: {sorted(missing)}")

    raw = raw.fillna("")
    raw = raw[raw["status"].astype(str).map(lambda value: _status_match(value, status_filter))]

    if extraction_limit is not None:
        extraction_limit = max(0, int(extraction_limit))
        raw = raw.head(extraction_limit)

    formatted: list[dict[str, Any]] = []

    for _, row in raw.iterrows():
        title = str(row["title"]).strip()
        description = str(row["description"]).strip()
        text = " ".join(part for part in [title, description] if part).strip()
        if len(text) < 10:
            continue

        formatted.append(
            {
                "feedback_id": _build_feedback_id(row),
                "source": "reclameaqui_manual",
                "source_url": str(row["source_url"]).strip(),
                "author": "Consumidor RA",
                "feedback_date": str(row["date"]).strip(),
                "raw_text": text,
                "initial_category": str(row["initial_category"]).strip() or "reclamacao",
                "channel": "complaint_site",
                "status": str(row["status"]).strip(),
            }
        )

    if not formatted:
        return _empty_output_frame()

    return _ensure_output_schema(pd.DataFrame(formatted))


def save_reclameaqui_feedback(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DEFAULT_OUTPUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_output_schema(df).to_csv(target, index=False, encoding="utf-8")
    return target


def upsert_reclameaqui_feedback(
    new_df: pd.DataFrame,
    output_path: Path | None = None,
) -> tuple[pd.DataFrame, int, Path]:
    target = output_path or DEFAULT_OUTPUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    incoming = _ensure_output_schema(new_df)

    if target.exists():
        existing = pd.read_csv(target).fillna("")
        existing = _ensure_output_schema(existing)
    else:
        existing = _empty_output_frame()

    existing = _drop_low_quality_auto_rows(_dedupe_by_source_url(existing))
    incoming = _drop_low_quality_auto_rows(_dedupe_by_source_url(incoming))
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = _drop_low_quality_auto_rows(_dedupe_by_source_url(merged))

    added_records = max(0, len(merged) - len(existing))
    merged.to_csv(target, index=False, encoding="utf-8")
    return merged, added_records, target


def load_and_save_reclameaqui_feedback(
    extraction_limit: int | None = None,
    status_filter: str = "Todas",
) -> pd.DataFrame:
    fresh_df = load_reclameaqui_manual(
        extraction_limit=extraction_limit,
        status_filter=status_filter,
    )
    merged_df, _, _ = upsert_reclameaqui_feedback(fresh_df)
    return merged_df


if __name__ == "__main__":
    dataframe = load_and_save_reclameaqui_feedback()
    print(f"Reclame Aqui rows loaded: {len(dataframe)}")
