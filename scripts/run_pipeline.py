from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.ebit_collector import collect_and_save_ebit_reviews
from src.collectors.reclameaqui_collector import collect_reclameaqui_complaints
from src.collectors.ra_manual_loader import load_reclameaqui_manual, upsert_reclameaqui_feedback
from src.config import DATA_PROCESSED_DIR, ensure_project_dirs
from src.pipeline.analyze_with_groq import enrich_feedback_dataframe, save_analyzed_feedback
from src.pipeline.normalize_feedback import normalize_feedback_frames, save_normalized_feedback
from src.reporting.build_report import build_reports


def _safe_collect_ebit() -> pd.DataFrame:
    try:
        return collect_and_save_ebit_reviews()
    except Exception as exc:
        print(f"[WARN] Ebit collection failed: {exc}")
        return pd.DataFrame()


def _safe_collect_ra() -> pd.DataFrame:
    auto_df = pd.DataFrame()
    manual_df = pd.DataFrame()

    try:
        auto_df = collect_reclameaqui_complaints(
            extraction_limit=50,
            status_filter="Todas",
            hours_window=24 * 7,
        )
    except Exception as exc:
        print(f"[WARN] Reclame Aqui auto collection failed: {exc}")

    try:
        manual_df = load_reclameaqui_manual(
            extraction_limit=50,
            status_filter="Todas",
        )
    except Exception as exc:
        print(f"[WARN] Reclame Aqui manual load failed: {exc}")
        manual_df = pd.DataFrame()

    frames = [frame for frame in [auto_df, manual_df] if not frame.empty]
    fresh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    merged, added_records, _ = upsert_reclameaqui_feedback(fresh)

    print(
        "[INFO] Reclame Aqui sync "
        f"auto={len(auto_df)} manual={len(manual_df)} novos={added_records} total={len(merged)}"
    )
    return merged


def run_pipeline() -> dict[str, str]:
    ensure_project_dirs()

    ebit_df = _safe_collect_ebit()
    ra_df = _safe_collect_ra()

    normalized_df = normalize_feedback_frames([ebit_df, ra_df])
    normalized_path = save_normalized_feedback(normalized_df)

    analyzed_df = enrich_feedback_dataframe(normalized_df)
    analyzed_path = save_analyzed_feedback(analyzed_df)

    markdown_report, pdf_report = build_reports(analyzed_df)

    result = {
        "normalized_path": str(normalized_path),
        "analyzed_path": str(analyzed_path),
        "markdown_report": str(markdown_report),
        "pdf_report": str(pdf_report),
        "rows_collected": str(len(normalized_df)),
        "rows_ebit": str(len(ebit_df)),
        "rows_reclameaqui": str(len(ra_df)),
    }

    if not normalized_df.empty:
        source_breakdown = normalized_df["source"].value_counts().to_dict()
        result["source_breakdown"] = str(source_breakdown)

    return result


def main() -> None:
    result = run_pipeline()
    print("Pipeline finished successfully.")
    for key, value in result.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
