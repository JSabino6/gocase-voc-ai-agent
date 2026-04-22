from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.config import DATA_PROCESSED_DIR

BASE_COLUMNS = [
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


def _ensure_schema(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame.copy()
    for column in BASE_COLUMNS:
        if column not in local.columns:
            local[column] = ""
    return local[BASE_COLUMNS]


def _stable_feedback_id(source: str, feedback_date: str, raw_text: str) -> str:
    base = f"{source}|{feedback_date}|{raw_text}".encode("utf-8")
    return hashlib.sha1(base).hexdigest()[:12]


def normalize_feedback_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    normalized_frames: list[pd.DataFrame] = []

    for frame in frames:
        if frame is None or frame.empty:
            continue

        local = _ensure_schema(frame)
        local = local.fillna("")
        local["raw_text"] = local["raw_text"].astype(str).str.strip()
        local = local[local["raw_text"].str.len() >= 10]

        parsed_date = pd.to_datetime(local["feedback_date"], errors="coerce", dayfirst=True)
        local["feedback_date"] = parsed_date.dt.strftime("%Y-%m-%d").fillna("")

        local["feedback_id"] = local.apply(
            lambda row: row["feedback_id"]
            if str(row["feedback_id"]).strip()
            else _stable_feedback_id(row["source"], row["feedback_date"], row["raw_text"]),
            axis=1,
        )

        local["ingested_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        normalized_frames.append(local)

    if not normalized_frames:
        empty_columns = BASE_COLUMNS + ["ingested_at"]
        return pd.DataFrame(columns=empty_columns)

    result = pd.concat(normalized_frames, ignore_index=True)
    result = result.drop_duplicates(subset=["source", "feedback_date", "raw_text"], keep="first")
    result = result.sort_values(by=["feedback_date", "source"], ascending=[False, True])
    result = result.reset_index(drop=True)
    return result


def save_normalized_feedback(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DATA_PROCESSED_DIR / "normalized_feedback.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False, encoding="utf-8")
    return target
