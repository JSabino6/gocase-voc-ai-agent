from __future__ import annotations

from pathlib import Path

import pandas as pd
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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


def _build_automatic_insights(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return [
            "Sem dados suficientes para gerar tendencia de sentimento.",
            "Execute a extracao para atualizar a base com novas reclamacoes.",
            "Acompanhe diariamente o volume para identificar picos operacionais.",
        ]

    total = len(df)
    negative = int((df["sentiment_label"] == "negativo").sum())
    negative_pct = _safe_percent(negative, total)
    high_priority = int((pd.to_numeric(df["priority"], errors="coerce").fillna(0) >= 4).sum())
    high_priority_pct = _safe_percent(high_priority, total)

    theme_counts = df["primary_theme"].value_counts()
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


def _build_sentiment_pie_chart(df: pd.DataFrame) -> Drawing:
    drawing = Drawing(420, 220)
    pie = Pie()
    pie.x = 120
    pie.y = 20
    pie.width = 180
    pie.height = 180

    if df.empty:
        pie.data = [1]
        pie.labels = ["Sem dados"]
    else:
        counts = df["sentiment_label"].value_counts()
        pie.data = [
            int(counts.get("positivo", 0)),
            int(counts.get("neutro", 0)),
            int(counts.get("negativo", 0)),
        ]
        pie.labels = ["Positivo", "Neutro", "Negativo"]

    pie.slices.strokeWidth = 0.5
    pie.slices[0].fillColor = colors.HexColor("#0f766e")
    if len(pie.slices) > 1:
        pie.slices[1].fillColor = colors.HexColor("#b45309")
    if len(pie.slices) > 2:
        pie.slices[2].fillColor = colors.HexColor("#b91c1c")

    drawing.add(String(10, 200, "Distribuicao de Sentimento", fontSize=11))
    drawing.add(pie)
    return drawing


def _build_theme_bar_chart(df: pd.DataFrame) -> Drawing:
    drawing = Drawing(460, 240)
    chart = VerticalBarChart()
    chart.x = 50
    chart.y = 45
    chart.height = 150
    chart.width = 360

    if df.empty:
        labels = ["Sem dados"]
        values = [0]
    else:
        counts = df["primary_theme"].value_counts().head(5)
        labels = [THEME_LABELS.get(str(item), str(item)) for item in counts.index.tolist()]
        values = [int(value) for value in counts.tolist()]

    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -12
    chart.barLabels.nudge = 7
    chart.barLabels.fontSize = 7
    chart.barLabels.fillColor = colors.black
    chart.barLabelFormat = "%d"
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueStep = max(1, int((max(values) if values else 1) / 4) or 1)
    chart.bars[0].fillColor = colors.HexColor("#0ea5e9")

    drawing.add(String(10, 215, "Top Temas", fontSize=11))
    drawing.add(chart)
    return drawing


def generate_markdown_report(df: pd.DataFrame, output_path: Path | None = None) -> Path:
    target = output_path or DATA_PROCESSED_DIR / "executive_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    total = len(df)
    sentiment_counts = df["sentiment_label"].value_counts() if total else pd.Series(dtype=int)
    positive = int(sentiment_counts.get("positivo", 0))
    neutral = int(sentiment_counts.get("neutro", 0))
    negative = int(sentiment_counts.get("negativo", 0))

    theme_counts = df["primary_theme"].value_counts().head(5) if total else pd.Series(dtype=int)
    high_priority = df[df["priority"] >= 4] if total else pd.DataFrame()
    escalation_count = int(df["escalation_required"].astype(bool).sum()) if total else 0

    positive_samples = (
        df[df["sentiment_label"] == "positivo"]["raw_text"].head(5).tolist() if total else []
    )
    negative_samples = (
        df[df["sentiment_label"] == "negativo"]["raw_text"].head(5).tolist() if total else []
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
    if not high_priority.empty:
        prioritized = high_priority[["primary_theme", "priority", "actionable_recommendation"]].head(10)
        for _, row in prioritized.iterrows():
            lines.append(
                f"- Prioridade {int(row['priority'])} | Tema: {row['primary_theme']} | Acao: {row['actionable_recommendation']}"
            )
    else:
        lines.append("- Nenhuma acao urgente identificada (prioridade >= 4).")
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

    styles = getSampleStyleSheet()
    content = markdown_path.read_text(encoding="utf-8").splitlines()

    doc = SimpleDocTemplate(str(target), pagesize=A4)
    flow = []
    for line in content:
        if not line.strip():
            flow.append(Spacer(1, 8))
            continue
        style = styles["BodyText"]
        if line.startswith("# "):
            style = styles["Heading1"]
            line = line[2:]
        elif line.startswith("## "):
            style = styles["Heading2"]
            line = line[3:]
        elif line.startswith("- "):
            line = "• " + line[2:]
        flow.append(Paragraph(line, style))

    flow.append(Spacer(1, 16))
    flow.append(Paragraph("Graficos Executivos", styles["Heading2"]))

    df_for_chart = analyzed_df if analyzed_df is not None else pd.DataFrame()
    flow.append(_build_sentiment_pie_chart(df_for_chart))
    flow.append(Spacer(1, 12))
    flow.append(_build_theme_bar_chart(df_for_chart))

    flow.append(Spacer(1, 14))
    flow.append(Paragraph("Insights Automaticos (sempre retornados)", styles["Heading2"]))
    for insight in _build_automatic_insights(df_for_chart):
        flow.append(Paragraph(f"• {insight}", styles["BodyText"]))

    doc.build(flow)
    return target


def build_reports(df: pd.DataFrame) -> tuple[Path, Path]:
    markdown_path = generate_markdown_report(df)
    pdf_path = generate_pdf_report(markdown_path, analyzed_df=df)
    return markdown_path, pdf_path
