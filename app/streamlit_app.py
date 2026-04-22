from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.ebit_collector import collect_and_save_ebit_reviews
from src.collectors.reclameaqui_collector import collect_reclameaqui_complaints
from src.collectors.ra_manual_loader import load_reclameaqui_manual, upsert_reclameaqui_feedback
from src.config import DATA_PROCESSED_DIR, ensure_project_dirs, get_settings
from src.pipeline.analyze_with_groq import enrich_feedback_dataframe, save_analyzed_feedback
from src.pipeline.normalize_feedback import normalize_feedback_frames, save_normalized_feedback
from src.reporting.build_report import build_reports

ANALYZED_PATH = DATA_PROCESSED_DIR / "analyzed_feedback.csv"
PDF_REPORT_PATH = DATA_PROCESSED_DIR / "executive_report.pdf"

SOURCE_LABELS = {
    "ebit": "Ebit (coleta automatica)",
    "ebit_seed": "Ebit (base de apoio)",
    "reclameaqui_auto": "Reclame Aqui (coleta automatica)",
    "reclameaqui_manual": "Reclame Aqui (coleta manual)",
}

SENTIMENT_LABELS = {
    "positivo": "Positivo",
    "neutro": "Neutro",
    "negativo": "Negativo",
}

THEME_LABELS = {
    "entrega": "Entrega e prazo",
    "qualidade_produto": "Qualidade do produto",
    "preco_frete": "Preco e frete",
    "atendimento": "Atendimento",
    "portfolio_personalizacao": "Portfolio e personalizacao",
    "outros": "Outros",
}

URGENCY_LABELS = {
    "baixa": "Baixa",
    "media": "Media",
    "alta": "Alta",
    "critica": "Critica",
}


def _to_label(value: Any, mapping: dict[str, str]) -> str:
    if pd.isna(value):
        return "-"
    return mapping.get(str(value), str(value))


def _build_filter_mapping(values: list[str], mapping: dict[str, str]) -> tuple[list[str], dict[str, list[str]]]:
    label_to_values: dict[str, list[str]] = {}
    for value in values:
        label = mapping.get(value, value)
        label_to_values.setdefault(label, []).append(value)
    labels = sorted(label_to_values.keys())
    return labels, label_to_values


def _prepare_display_data(df: pd.DataFrame) -> pd.DataFrame:
    local = df.copy()
    local["Data"] = pd.to_datetime(local.get("feedback_date"), errors="coerce").dt.strftime("%d/%m/%Y").fillna("-")
    local["Fonte"] = local.get("source", "").map(lambda item: _to_label(item, SOURCE_LABELS))
    local["Sentimento"] = local.get("sentiment_label", "").map(lambda item: _to_label(item, SENTIMENT_LABELS))
    local["Tema Principal"] = local.get("primary_theme", "").map(lambda item: _to_label(item, THEME_LABELS))
    local["Urgencia"] = local.get("urgency", "").map(lambda item: _to_label(item, URGENCY_LABELS))
    local["Escalacao Recomendada"] = local.get("escalation_required", False).map(lambda item: "Sim" if bool(item) else "Nao")
    local["Acao Recomendada"] = local.get("actionable_recommendation", "")
    local["Feedback Original"] = local.get("raw_text", "")
    local["Prioridade"] = pd.to_numeric(local.get("priority", 0), errors="coerce").fillna(0).astype(int)
    return local


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _build_runtime_email_settings() -> Any:
    base_settings = get_settings()

    dotenv_map = dotenv_values(PROJECT_ROOT / ".env")

    def _pick_value(attribute_name: str, env_key: str, default: str = "") -> str:
        current_value = getattr(base_settings, attribute_name, None)
        if current_value is not None and str(current_value).strip():
            return str(current_value).strip()

        env_value = str(os.getenv(env_key, "")).strip()
        if env_value:
            return env_value

        file_value = str(dotenv_map.get(env_key, "") or "").strip()
        if file_value:
            return file_value

        return default

    request_timeout_raw = _pick_value("request_timeout_seconds", "REQUEST_TIMEOUT_SECONDS", "30")
    smtp_port_raw = _pick_value("smtp_port", "SMTP_PORT", "587")

    return SimpleNamespace(
        request_timeout_seconds=int(request_timeout_raw),
        smtp_host=_pick_value("smtp_host", "SMTP_HOST", ""),
        smtp_port=int(smtp_port_raw or "587"),
        smtp_username=_pick_value("smtp_username", "SMTP_USERNAME", ""),
        smtp_password=_pick_value("smtp_password", "SMTP_PASSWORD", ""),
        smtp_sender_email=_pick_value("smtp_sender_email", "SMTP_SENDER_EMAIL", ""),
        smtp_use_tls=_as_bool(
            _pick_value("smtp_use_tls", "SMTP_USE_TLS", "true"),
            default=True,
        ),
    )


def _load_email_sender_runtime() -> tuple[Any, Any]:
    module = importlib.import_module("src.reporting.email_sender")
    module = importlib.reload(module)
    return module.parse_recipient_emails, module.send_pdf_report_via_email


def _extract_and_update_data(
    extraction_limit: int,
    status_filter: str,
    collection_mode: str,
    hours_window: int | None,
) -> tuple[int, int, int, int]:
    ensure_project_dirs()

    auto_df = pd.DataFrame()
    manual_df = pd.DataFrame()

    run_auto = collection_mode in {"Automatica (site)", "Automatica + Manual (fallback)"}
    run_manual = collection_mode == "Manual (CSV)"

    if run_auto:
        auto_df = collect_reclameaqui_complaints(
            extraction_limit=extraction_limit,
            status_filter=status_filter,
            hours_window=hours_window,
        )

    if run_manual or (collection_mode == "Automatica + Manual (fallback)" and auto_df.empty):
        manual_df = load_reclameaqui_manual(
            extraction_limit=extraction_limit,
            status_filter=status_filter,
        )

    frames = [frame for frame in [auto_df, manual_df] if not frame.empty]
    fresh_ra_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    merged_ra_df, added_records, _ = upsert_reclameaqui_feedback(fresh_ra_df)

    try:
        ebit_df = collect_and_save_ebit_reviews()
    except Exception:
        ebit_df = pd.DataFrame()

    normalized_df = normalize_feedback_frames([ebit_df, merged_ra_df])
    save_normalized_feedback(normalized_df)

    analyzed_df = enrich_feedback_dataframe(normalized_df)
    save_analyzed_feedback(analyzed_df)
    build_reports(analyzed_df)

    return added_records, len(fresh_ra_df), len(auto_df), len(manual_df)


@st.cache_data
def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except pd.errors.ParserError:
        # Some generated rows may have unescaped commas/newlines.
        # Fallback parser keeps the app usable by skipping malformed lines.
        df = pd.read_csv(path, engine="python", on_bad_lines="skip")
    if "feedback_date" in df.columns:
        df["feedback_date"] = pd.to_datetime(df["feedback_date"], errors="coerce")
    if "escalation_required" in df.columns:
        df["escalation_required"] = df["escalation_required"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df


def main() -> None:
    st.set_page_config(page_title="Gocase - Painel VoC", layout="wide")
    st.title("Gocase - Agente IA de Voz do Cliente")
    st.caption("Painel de inteligencia de feedback com classificacao por IA e foco em acao")

    settings = _build_runtime_email_settings()

    with st.sidebar:
        st.header("Atualizacao de dados")
        collection_mode = st.selectbox(
            "Modo de extracao Reclame Aqui",
            options=[
                "Automatica (site)",
                "Automatica + Manual (fallback)",
                "Manual (CSV)",
            ],
            index=1,
            help="Use o modo automatico para tentar capturar reclamacoes diretamente do site.",
        )
        extraction_limit = st.number_input(
            "Limite Maximo de Extracao",
            min_value=10,
            value=50,
            step=10,
            help="Define o numero maximo de reclamacoes consideradas na extracao manual.",
        )
        time_window_option = st.selectbox(
            "Periodo da extracao",
            options=["Sem limite", "Ultimas 24 horas", "Ultimos 7 dias", "Ultimas N horas"],
            index=0,
            help="Filtra reclamacoes recentes no modo automatico.",
        )
        custom_hours = None
        if time_window_option == "Ultimas N horas":
            custom_hours = st.number_input(
                "Quantidade de horas",
                min_value=1,
                max_value=720,
                value=24,
                step=1,
            )

        status_filter = st.radio(
            "Status das Reclamacoes",
            options=["Todas", "Resolvidas", "Não Resolvidas"],
            index=0,
            help="Filtre as reclamacoes pelo status antes de atualizar os dados.",
        )
        extract_clicked = st.button(
            "Extrair e Atualizar Dados",
            type="primary",
            use_container_width=True,
        )

    if extract_clicked:
        try:
            hours_window = None
            if time_window_option == "Ultimas 24 horas":
                hours_window = 24
            elif time_window_option == "Ultimos 7 dias":
                hours_window = 24 * 7
            elif time_window_option == "Ultimas N horas":
                hours_window = int(custom_hours) if custom_hours else 24

            added_records, extracted_count, auto_count, manual_count = _extract_and_update_data(
                extraction_limit=int(extraction_limit),
                status_filter=status_filter,
                collection_mode=collection_mode,
                hours_window=hours_window,
            )
            st.session_state["extraction_message"] = (
                "success",
                (
                    f"Extracao concluida com {extracted_count} registros lidos. "
                    f"{added_records} registros novos foram efetivamente adicionados. "
                    f"Auto: {auto_count} | Manual: {manual_count}."
                ),
            )
        except Exception as exc:
            st.session_state["extraction_message"] = (
                "error",
                f"Falha ao extrair e atualizar dados: {exc}",
            )

        load_data.clear()
        st.rerun()

    df = load_data(ANALYZED_PATH)
    if df.empty:
        st.warning("Nenhum dado analisado encontrado. Rode: python scripts/run_pipeline.py")
        return

    sources = sorted(df["source"].dropna().unique().tolist())
    sentiments = sorted(df["sentiment_label"].dropna().unique().tolist())
    themes = sorted(df["primary_theme"].dropna().unique().tolist())

    source_labels, source_map = _build_filter_mapping(sources, SOURCE_LABELS)
    sentiment_labels, sentiment_map = _build_filter_mapping(sentiments, SENTIMENT_LABELS)
    theme_labels, theme_map = _build_filter_mapping(themes, THEME_LABELS)

    with st.sidebar:
        extraction_message = st.session_state.pop("extraction_message", None)
        if extraction_message:
            message_type, message_text = extraction_message
            if message_type == "success":
                st.success(message_text)
            else:
                st.error(message_text)

        st.divider()
        st.header("Filtros")
        selected_source_labels = st.multiselect("Fonte de feedback", options=source_labels, default=source_labels)
        selected_sentiment_labels = st.multiselect(
            "Sentimento", options=sentiment_labels, default=sentiment_labels
        )
        selected_theme_labels = st.multiselect("Tema", options=theme_labels, default=theme_labels)

    selected_sources = [value for label in selected_source_labels for value in source_map.get(label, [])]
    selected_sentiments = [value for label in selected_sentiment_labels for value in sentiment_map.get(label, [])]
    selected_themes = [value for label in selected_theme_labels for value in theme_map.get(label, [])]

    filtered = df[
        df["source"].isin(selected_sources)
        & df["sentiment_label"].isin(selected_sentiments)
        & df["primary_theme"].isin(selected_themes)
    ].copy()

    if filtered.empty:
        st.warning("Nenhum feedback encontrado para os filtros atuais.")
        return

    display_df = _prepare_display_data(filtered)

    total = len(filtered)
    negative_rate = (
        round((len(filtered[filtered["sentiment_label"] == "negativo"]) / total) * 100, 1)
        if total
        else 0.0
    )
    escalation_count = int(filtered["escalation_required"].sum()) if total else 0
    avg_priority = round(filtered["priority"].mean(), 2) if total else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de feedbacks", total)
    col2.metric("Percentual negativo", f"{negative_rate}%")
    col3.metric("Casos para escalacao", escalation_count)
    col4.metric("Prioridade media", avg_priority)

    st.info(
        "Leitura rapida: percentual negativo alto + muitos casos com prioridade 4 ou 5 indicam dor critica para operacao."
    )

    chart_col_1, chart_col_2 = st.columns(2)
    with chart_col_1:
        sentiment_chart = display_df["Sentimento"].value_counts().reset_index()
        sentiment_chart.columns = ["Sentimento", "Quantidade"]
        fig_sentiment = px.pie(
            sentiment_chart,
            values="Quantidade",
            names="Sentimento",
            title="Distribuicao de Sentimento",
            color="Sentimento",
            color_discrete_map={
                "Positivo": "#0f766e",
                "Neutro": "#b45309",
                "Negativo": "#b91c1c",
            },
        )
        st.plotly_chart(fig_sentiment, use_container_width=True)

    with chart_col_2:
        theme_chart = display_df["Tema Principal"].value_counts().reset_index()
        theme_chart.columns = ["Tema", "Quantidade"]
        fig_themes = px.bar(
            theme_chart,
            x="Tema",
            y="Quantidade",
            title="Top Temas",
            color="Tema",
            color_discrete_sequence=["#0ea5e9", "#14b8a6", "#22c55e", "#f97316", "#ef4444", "#8b5cf6"],
        )
        st.plotly_chart(fig_themes, use_container_width=True)

    st.subheader("O que foi positivo?")
    positive_feedback = display_df[display_df["Sentimento"] == "Positivo"]["Feedback Original"].head(5).tolist()
    if positive_feedback:
        for item in positive_feedback:
            st.write(f"- {' '.join(str(item).split())[:180]}")
    else:
        st.write("Sem feedback positivo para os filtros atuais.")

    st.subheader("Criticas e acoes prioritarias")
    priority_table = display_df[display_df["Prioridade"] >= 4][
        [
            "Data",
            "Fonte",
            "Tema Principal",
            "Prioridade",
            "Urgencia",
            "Acao Recomendada",
            "Feedback Original",
        ]
    ].sort_values(by=["Prioridade", "Data"], ascending=[False, False])

    if priority_table.empty:
        st.info("Nenhum caso de prioridade alta (>=4) para os filtros atuais.")
    else:
        st.dataframe(priority_table, use_container_width=True)

    st.subheader("Visao completa")
    display_columns = [
        "Data",
        "Fonte",
        "Sentimento",
        "Tema Principal",
        "Prioridade",
        "Urgencia",
        "Escalacao Recomendada",
        "Acao Recomendada",
        "Feedback Original",
    ]
    st.dataframe(display_df[display_columns], use_container_width=True)

    st.subheader("Envio de insights por e-mail")
    st.caption("Envie o PDF executivo para um ou mais destinatarios (separados por virgula).")

    if not PDF_REPORT_PATH.exists():
        st.warning("Relatorio PDF nao encontrado. Rode o pipeline para gerar o arquivo antes do envio.")

    with st.expander("Configurar envio", expanded=False):
        recipients_input = st.text_input(
            "Destinatarios",
            placeholder="exemplo1@empresa.com, exemplo2@empresa.com",
        )
        email_subject = st.text_input(
            "Assunto",
            value="Relatorio de insights - Voz do Cliente",
        )
        email_body = st.text_area(
            "Mensagem",
            value=(
                "Ola,\n\nSegue em anexo o relatorio executivo de insights de Voz do Cliente.\n"
                "Este material inclui sentimento, principais temas e recomendacoes de acao.\n\n"
                "Atenciosamente,\nAgente IA VoC"
            ),
            height=140,
        )

        smtp_host = getattr(settings, "smtp_host", "")
        smtp_sender_email = getattr(settings, "smtp_sender_email", "")
        smtp_ready = bool(smtp_host and smtp_sender_email)
        if not smtp_ready:
            st.warning(
                "Configure SMTP_HOST, SMTP_PORT, SMTP_SENDER_EMAIL e (se necessario) SMTP_USERNAME/SMTP_PASSWORD no arquivo .env para habilitar o envio."
            )

        if st.button("Enviar Insights para EMAIL", type="primary"):
            try:
                parse_recipient_emails, send_pdf_report_via_email = _load_email_sender_runtime()
                recipients = parse_recipient_emails(recipients_input)
                send_pdf_report_via_email(
                    recipients=recipients,
                    subject=email_subject,
                    body=email_body,
                    pdf_path=PDF_REPORT_PATH,
                    settings=settings,
                )
                st.success(f"Envio realizado com sucesso para: {', '.join(recipients)}")
            except Exception as exc:
                st.error(f"Falha ao enviar e-mail: {exc}")


if __name__ == "__main__":
    main()
