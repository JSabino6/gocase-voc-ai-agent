from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as ReportImage
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.config import DATA_PROCESSED_DIR

THEME_LABELS = {
    "entrega": "Entrega",
    "qualidade_produto": "Qualidade",
    "preco_frete": "Preco/Frete",
    "atendimento": "Atendimento",
    "portfolio_personalizacao": "Portfolio",
    "outros": "Outros",
}


def _safe_percent(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((value / total) * 100, 1)


def _sample_text(text: str, max_len: int = 150) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3] + "..."


def _resolve_column(df: pd.DataFrame, options: list[str], fallback: str = "") -> str:
    for option in options:
        if option in df.columns:
            return option
    return fallback


def _format_theme_label(raw_theme: str) -> str:
    return THEME_LABELS.get(str(raw_theme), str(raw_theme).replace("_", " ").title())


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _paragraph_safe(text: str, preserve_line_breaks: bool = False) -> str:
    if preserve_line_breaks:
        normalized_lines = [escape(_clean_text(line)) for line in str(text or "").splitlines() if _clean_text(line)]
        if not normalized_lines:
            return "-"
        return "<br/>".join(normalized_lines)
    cleaned = _clean_text(text)
    return escape(cleaned) if cleaned else "-"


def _theme_counts_for_chart(frame: pd.DataFrame, theme_col: str, top_n: int = 5) -> pd.Series:
    if frame.empty or theme_col not in frame.columns:
        return pd.Series(dtype=int)

    counts = frame[theme_col].fillna("outros").astype(str).value_counts()
    if counts.empty:
        return counts

    if len(counts) <= top_n:
        return counts

    top_counts = counts.head(top_n).copy()
    remaining = int(counts.iloc[top_n:].sum())
    if remaining > 0:
        top_counts.loc["outros"] = int(top_counts.get("outros", 0)) + remaining
    return top_counts


def _build_automatic_insights(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return [
            "Sem dados suficientes para gerar tendencia de sentimento.",
            "Execute a extracao para atualizar a base com novas reclamacoes.",
            "Acompanhe diariamente o volume para identificar picos operacionais.",
        ]

    sentiment_col = _resolve_column(df, ["sentimento", "sentiment_label"], fallback="sentiment_label")
    priority_col = _resolve_column(df, ["prioridade", "priority"], fallback="priority")
    theme_col = _resolve_column(df, ["tema_principal", "primary_theme"], fallback="primary_theme")

    total = len(df)
    negative = int((df[sentiment_col] == "negativo").sum()) if sentiment_col in df.columns else 0
    negative_pct = _safe_percent(negative, total)
    high_priority = int((pd.to_numeric(df[priority_col], errors="coerce").fillna(0) >= 4).sum()) if priority_col in df.columns else 0
    high_priority_pct = _safe_percent(high_priority, total)

    theme_counts = df[theme_col].value_counts() if theme_col in df.columns else pd.Series(dtype=int)
    if theme_counts.empty:
        top_theme_label = "Outros"
        top_theme_count = 0
    else:
        top_theme = str(theme_counts.index[0])
        top_theme_label = THEME_LABELS.get(top_theme, top_theme)
        top_theme_count = int(theme_counts.iloc[0])

    provider_counts = df["ai_provider"].value_counts() if "ai_provider" in df.columns else pd.Series(dtype=int)
    groq_count = int(provider_counts.get("groq", 0))
    rules_count = int(provider_counts.get("rules", 0))

    insights: list[str] = []
    insights.append(
        f"{negative_pct}% dos feedbacks estao negativos; recomenda-se priorizar causas recorrentes de insatisfacao."
    )
    insights.append(
        f"Tema mais citado: {top_theme_label} ({top_theme_count} ocorrencias), indicando foco imediato para plano de acao."
    )
    insights.append(
        f"{high_priority_pct}% da base esta em prioridade alta (>=4), exigindo acompanhamento operacional diario."
    )
    insights.append(
        f"Cobertura da IA: Groq={groq_count} e regras={rules_count}; monitorar fallback para manter qualidade analitica."
    )
    return insights


def _build_theme_pie_chart_image(df: pd.DataFrame, critical_df: pd.DataFrame) -> ReportImage:
    theme_col = _resolve_column(df, ["tema_principal", "primary_theme"], fallback="primary_theme")
    colors_palette = ["#0EA5E9", "#14B8A6", "#F59E0B", "#F97316", "#EF4444", "#6366F1"]

    figure, axes = plt.subplots(2, 1, figsize=(8.4, 7.2), dpi=150)
    sections = [
        (df, "Temas - Base Completa"),
        (critical_df, "Temas - Casos Criticos (P5/P4)"),
    ]

    for axis, (frame, title) in zip(axes, sections):
        axis.set_title(title, fontsize=11, fontweight="bold", pad=8)
        axis.set_facecolor("#F8FAFC")

        counts = _theme_counts_for_chart(frame, theme_col, top_n=5)
        if counts.empty:
            axis.text(0.5, 0.5, "Sem dados", ha="center", va="center", fontsize=10)
            axis.axis("off")
            continue

        labels = [_format_theme_label(value) for value in counts.index.tolist()]
        wedges, _, autotexts = axis.pie(
            counts.tolist(),
            labels=None,
            startangle=90,
            autopct=lambda pct: f"{pct:.0f}%" if pct >= 8 else "",
            pctdistance=0.78,
            colors=colors_palette[: len(labels)],
            wedgeprops={"linewidth": 1.0, "edgecolor": "white", "width": 0.45},
            textprops={"fontsize": 8, "weight": "bold", "color": "#0F172A"},
        )
        axis.axis("equal")
        for auto_text in autotexts:
            auto_text.set_fontsize(8)
            auto_text.set_color("#0F172A")

        legend_labels = [
            f"{label}: {int(value)} ({_safe_percent(int(value), int(counts.sum()))}%)"
            for label, value in zip(labels, counts.tolist())
        ]
        axis.legend(
            wedges,
            legend_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.05),
            ncol=2,
            fontsize=8,
            frameon=False,
        )

    plt.tight_layout(h_pad=2.2)
    image_buffer = BytesIO()
    figure.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(figure)
    image_buffer.seek(0)

    return ReportImage(image_buffer, width=520, height=330)


def generate_markdown_report(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DATA_PROCESSED_DIR / "executive_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    sentiment_col = _resolve_column(df, ["sentimento", "sentiment_label"], fallback="sentiment_label")
    priority_col = _resolve_column(df, ["prioridade", "priority"], fallback="priority")
    theme_col = _resolve_column(df, ["tema_principal", "primary_theme"], fallback="primary_theme")

    total = len(df)
    sentiment_counts = df[sentiment_col].value_counts() if total and sentiment_col in df.columns else pd.Series(dtype=int)
    positive = int(sentiment_counts.get("positivo", 0))
    neutral = int(sentiment_counts.get("neutro", 0))
    negative = int(sentiment_counts.get("negativo", 0))

    theme_counts = df[theme_col].value_counts().head(5) if total and theme_col in df.columns else pd.Series(dtype=int)
    high_priority = (
        df[pd.to_numeric(df[priority_col], errors="coerce").fillna(0) >= 4]
        if total and priority_col in df.columns
        else pd.DataFrame()
    )
    escalation_count = int(df["escalation_required"].astype(bool).sum()) if total and "escalation_required" in df.columns else 0

    positive_samples = (
        df[df[sentiment_col] == "positivo"]["raw_text"].head(5).tolist()
        if total and sentiment_col in df.columns and "raw_text" in df.columns
        else []
    )
    negative_samples = (
        df[df[sentiment_col] == "negativo"]["raw_text"].head(5).tolist()
        if total and sentiment_col in df.columns and "raw_text" in df.columns
        else []
    )

    lines: list[str] = []
    lines.append("# Relatorio Executivo - Voz do Cliente (MVP)")
    lines.append("")
    lines.append("## Resumo Geral")
    lines.append(f"- Total de feedbacks analisados: {total}")
    lines.append(f"- Positivos: {positive} ({_safe_percent(positive, total)}%)")
    lines.append(f"- Neutros: {neutral} ({_safe_percent(neutral, total)}%)")
    lines.append(f"- Negativos: {negative} ({_safe_percent(negative, total)}%)")
    lines.append(f"- Escalacoes recomendadas: {escalation_count}")
    lines.append("")

    lines.append("## WHAT WAS POSITIVE?")
    if positive_samples:
        for sample in positive_samples:
            lines.append(f"- {_sample_text(sample)}")
    else:
        lines.append("- Nao foram identificados feedbacks positivos na amostra atual.")
    lines.append("")

    lines.append("## Criticas e Oportunidades")
    if negative_samples:
        for sample in negative_samples:
            lines.append(f"- {_sample_text(sample)}")
    else:
        lines.append("- Nao foram identificadas criticas relevantes na amostra atual.")
    lines.append("")

    lines.append("## Temas Mais Frequentes")
    if not theme_counts.empty:
        for theme, count in theme_counts.items():
            lines.append(f"- {theme}: {count}")
    else:
        lines.append("- Sem dados suficientes para ranking de temas.")
    lines.append("")

    lines.append("## Acoes Prioritarias Recomendadas")
    recommendation_col = _resolve_column(
        df,
        ["recomendacao_interna_gocase", "actionable_recommendation"],
        fallback="actionable_recommendation",
    )
    if not high_priority.empty and recommendation_col in high_priority.columns:
        prioritized = high_priority[[theme_col, priority_col, recommendation_col]].head(10)
        for _, row in prioritized.iterrows():
            lines.append(
                f"- Prioridade {int(row[priority_col])} | Tema: {row[theme_col]} | Acao: {row[recommendation_col]}"
            )
    else:
        lines.append("- Nenhuma acao urgente identificada (prioridade >= 4).")
    lines.append("")

    lines.append("## Guia de Resposta para Atendente (SAC)")
    response_col = _resolve_column(df, ["resposta_sugerida_cliente", "suggested_customer_response"], fallback="")
    if total and response_col and response_col in df.columns:
        reply_frame = (
            high_priority[[theme_col, response_col]]
            .dropna(subset=[response_col])
            .head(10)
        )
        if not reply_frame.empty:
            for _, row in reply_frame.iterrows():
                lines.append(
                    f"- Tema: {row[theme_col]} | Guia sugerido: {_sample_text(row[response_col], 240)}"
                )
        else:
            lines.append("- Sem guias de resposta de alta prioridade na amostra atual.")
    else:
        lines.append("- Campo de guia de resposta ainda nao disponivel para esta base.")
    lines.append("")

    lines.append("## Insights Automaticos")
    for insight in _build_automatic_insights(df):
        lines.append(f"- {insight}")
    lines.append("")

    lines.append("## Proximos Passos")
    lines.append("- Integrar fontes oficiais de feedback interno (NPS, tickets, CRM).")
    lines.append("- Evoluir taxonomia de temas por area de negocio.")
    lines.append("- Criar rotina semanal automatica com envio para liderancas.")

    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def generate_pdf_report(
    markdown_path: Path,
    output_path: Path | None = None,
    analyzed_df: pd.DataFrame | None = None,
) -> Path:
    target = output_path or DATA_PROCESSED_DIR / "executive_report.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    _ = markdown_path
    df_for_pdf = analyzed_df.copy() if analyzed_df is not None else pd.DataFrame()

    priority_col = _resolve_column(df_for_pdf, ["prioridade", "priority"], fallback="priority")
    sentiment_col = _resolve_column(df_for_pdf, ["sentimento", "sentiment_label"], fallback="sentiment_label")
    theme_col = _resolve_column(df_for_pdf, ["tema_principal", "primary_theme"], fallback="primary_theme")
    recommendation_col = _resolve_column(
        df_for_pdf,
        ["recomendacao_interna_gocase", "actionable_recommendation"],
        fallback="actionable_recommendation",
    )
    response_col = _resolve_column(
        df_for_pdf,
        ["resposta_sugerida_cliente", "suggested_customer_response"],
        fallback="resposta_sugerida_cliente",
    )
    complaint_col = _resolve_column(df_for_pdf, ["raw_text"], fallback="raw_text")

    if not df_for_pdf.empty and priority_col in df_for_pdf.columns:
        df_for_pdf[priority_col] = pd.to_numeric(df_for_pdf[priority_col], errors="coerce").fillna(0).astype(int)

    critical_df = (
        df_for_pdf[df_for_pdf[priority_col].isin([5, 4])].copy()
        if not df_for_pdf.empty and priority_col in df_for_pdf.columns
        else pd.DataFrame()
    )
    if not critical_df.empty:
        critical_df = critical_df.sort_values(by=[priority_col], ascending=False)

    total = len(df_for_pdf)
    negative = int((df_for_pdf[sentiment_col] == "negativo").sum()) if total and sentiment_col in df_for_pdf.columns else 0
    negative_pct = _safe_percent(negative, total)

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        topMargin=38,
        bottomMargin=28,
        leftMargin=34,
        rightMargin=34,
    )

    base_styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=base_styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "SectionTitle",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=8,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=base_styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.6,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
    )
    case_title_style = ParagraphStyle(
        "CaseTitleStyle",
        parent=base_styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
        spaceBefore=6,
    )
    insight_style = ParagraphStyle(
        "InsightStyle",
        parent=base_styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#0F172A"),
        leftIndent=8,
    )

    flow: list = []
    flow.append(Paragraph("Relatorio Executivo - Voz do Cliente", title_style))
    flow.append(Paragraph("Visao gerencial para apoio a decisao e resposta rapida aos gargalos.", subtitle_style))
    flow.append(Paragraph(f"Data de geracao: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
    flow.append(Spacer(1, 8))

    kpi_table = Table(
        [
            ["Total de Reclamacoes", "% de Negativos", "Casos Criticos (P5/P4)"],
            [str(total), f"{negative_pct}%", str(len(critical_df))],
        ],
        colWidths=[doc.width / 3.0] * 3,
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    flow.append(kpi_table)

    flow.append(Spacer(1, 14))
    flow.append(Paragraph("Distribuicao de Temas (Grafico de Pizza)", section_style))
    flow.append(_build_theme_pie_chart_image(df_for_pdf, critical_df))

    flow.append(Spacer(1, 10))
    flow.append(Paragraph("Insights Executivos", section_style))
    for insight in _build_automatic_insights(df_for_pdf):
        flow.append(Paragraph(f"- {escape(insight)}", insight_style))

    flow.append(Spacer(1, 10))
    flow.append(Paragraph("Casos Criticos - Prioridade 5 e 4", section_style))

    if critical_df.empty:
        flow.append(Paragraph("Nao foram encontrados casos criticos na base analisada.", body_style))
    else:
        for index, (_, row) in enumerate(critical_df.iterrows(), start=1):
            priority_value = int(row.get(priority_col, 0))
            theme_value = _format_theme_label(str(row.get(theme_col, "outros")))
            complaint_text = _paragraph_safe(str(row.get(complaint_col, "")))
            recommendation_text = _paragraph_safe(
                str(row.get(recommendation_col, "Sem recomendacao interna registrada.")),
            )
            response_text = _paragraph_safe(
                str(row.get(response_col, "Sem resposta sugerida registrada.")),
                preserve_line_breaks=True,
            )

            flow.append(Paragraph(f"Caso Critico {index} | Prioridade {priority_value} | Tema: {escape(theme_value)}", case_title_style))
            flow.append(Paragraph(f"<b>Reclamacao:</b> {complaint_text}", body_style))
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"<b>Acao Interna:</b> {recommendation_text}", body_style))
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"<b>Guia de Resposta (Atendente):</b><br/>{response_text}", body_style))
            flow.append(Spacer(1, 6))
            flow.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1")))
            flow.append(Spacer(1, 8))

    doc.build(flow)
    return target


def build_reports(df: pd.DataFrame) -> tuple[Path, Path]:
    markdown_path = generate_markdown_report(df)
    pdf_path = generate_pdf_report(markdown_path, analyzed_df=df)
    return markdown_path, pdf_path

