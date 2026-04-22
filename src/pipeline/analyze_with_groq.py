from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
from groq import Groq

from src.config import DATA_PROCESSED_DIR, get_settings
from src.pipeline.fallback_rules import analyze_feedback_with_rules

SYSTEM_PROMPT = (
    """Você é um Analista Sênior de Customer Experience (CX) e Engenharia de Qualidade trabalhando INTERNAMENTE na Gocase. Sua missão é ler as reclamações dos clientes e definir o plano de ação, seguindo ESTRITAMENTE as Políticas Oficiais, Termos de Uso e Manuais de Garantia da Gocase.

📋 POLÍTICAS GLOBAIS DE RESOLUÇÃO GOCASE (BASE DE CONHECIMENTO OFICIAL):

[1. ARREPENDIMENTO E CANCELAMENTO (CDC)]
- Regra de Personalizados: A Gocase produz itens sob demanda e exclusivos. Produtos em produção não podem ser cancelados, pois não retornam ao estoque.
- Regra de Produtos "Clear" (Sem estampa): Podem ser cancelados sem atrito se ainda não foram recebidos.
- Prazo de Arrependimento: 7 dias corridos após o recebimento.
- Ação Padrão: O reembolso ou vale-compras só deve ser liberado APÓS o cliente postar o produto na agência dos Correios com o código de logística reversa e enviar o comprovante.

[2. DEVOLUÇÃO FINANCEIRA (REGRAS DE REEMBOLSO)]
- Regra Base: O reembolso será feito na mesma forma de pagamento.
- Pix/Boleto: O estorno será via depósito bancário e, sob nenhuma hipótese, será feito em conta de terceiros (apenas na conta do titular da compra).
- Produtos em Promoção: O valor estornado será exatamente o valor pago no momento da compra promocional, e não o valor original "cheio" do produto.

[3. GARANTIAS E AVARIAS (PRODUTOS COM DEFEITO)]
- Regra Base: Exigir o retorno do produto na embalagem original, com todos os acessórios e tags, para análise e melhoria dos processos de fabricação na fábrica.
- Peças de Reposição Específicas: Se o problema for a perda da borracha de vedação da garrafa térmica, a ação NÃO é trocar a garrafa. A ação é orientar o cliente a abrir um protocolo no WhatsApp para o envio de uma nova borracha mediante o pagamento do frete de R$ 15,00.
- Garantia de Malas: Modelos Trip e Voyage (6 meses contra descascamento, 3 meses outros defeitos). Modelo Bold (3 meses geral).

[4. ATENDIMENTO E LOGÍSTICA]
- Regra Base: Se a transportadora falhar ou o sistema de atendimento demorar, a culpa nunca deve ser repassada ao cliente.
- Ação Padrão: Recomendar prioridade no contato, acareação com a transportadora e, se necessário, reenvio expresso do produto.

🚨 DIRETRIZES ESTRITAS DE COMPORTAMENTO:
1. Você trabalha para a Gocase. NUNCA concorde com ofensas à empresa ou diga que o serviço é ruim.
2. NUNCA escreva conselhos morais para o cliente (ex: "pesquise melhor", "leia as regras"). O seu texto é um memorando INTERNO para os gerentes da Gocase lerem e agirem.
3. Baseie sua decisão ESTRITAMENTE na política oficial que mais se adequa ao relato."""
)

USER_PROMPT_TEMPLATE = """
Analise o feedback abaixo em portugues e retorne APENAS um JSON valido.

Campos obrigatorios:
- sentimento: positivo | neutro | negativo
- tema_principal: entrega | qualidade_produto | preco_frete | atendimento | portfolio_personalizacao | outros
- prioridade: inteiro de 1 a 5
- recomendacao_interna_gocase: recomendacao objetiva e acionavel para os times internos da Gocase


Campos opcionais:
- urgencia: baixa | media | alta | critica
- score_sentimento: numero entre -1 e 1
- escalonamento_necessario: true ou false
- confianca: numero entre 0 e 1

Feedback:
{text}
""".strip()

ALLOWED_SENTIMENT = {"positivo", "neutro", "negativo"}
ALLOWED_THEME = {
    "entrega",
    "qualidade_produto",
    "preco_frete",
    "atendimento",
    "portfolio_personalizacao",
    "outros",
}
ALLOWED_URGENCY = {"baixa", "media", "alta", "critica"}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "t", "sim", "yes", "y"}


def _attach_corporate_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    recommendation = str(
        payload.get("recomendacao_interna_gocase")
        or payload.get("actionable_recommendation")
        or "Revisar caso manualmente."
    ).strip()
    if not recommendation:
        recommendation = "Revisar caso manualmente."

    payload["actionable_recommendation"] = recommendation
    payload["recomendacao_interna_gocase"] = recommendation

    sentiment = str(payload.get("sentiment_label", "neutro")).strip().lower()
    theme = str(payload.get("primary_theme", "outros")).strip().lower()
    priority_value = payload.get("priority", 3)

    try:
        priority = int(priority_value)
    except (TypeError, ValueError):
        priority = 3

    payload["sentimento"] = sentiment
    payload["tema_principal"] = theme
    payload["prioridade"] = max(1, min(5, priority))
    return payload


def _extract_json_block(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return json.loads(content)

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("No JSON payload found in model response")
    return json.loads(match.group(0))


def _sanitize_model_output(payload: dict[str, Any]) -> dict[str, Any]:
    sentiment_label = str(payload.get("sentiment_label", payload.get("sentimento", "neutro"))).strip().lower()
    primary_theme = str(payload.get("primary_theme", payload.get("tema_principal", "outros"))).strip().lower()

    priority = payload.get("priority", payload.get("prioridade", 3))
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        priority = 3

    urgency = str(payload.get("urgency", payload.get("urgencia", ""))).strip().lower()
    if not urgency:
        if priority >= 5:
            urgency = "critica"
        elif priority >= 4:
            urgency = "alta"
        elif priority <= 2:
            urgency = "baixa"
        else:
            urgency = "media"

    if sentiment_label not in ALLOWED_SENTIMENT:
        sentiment_label = "neutro"
    if primary_theme not in ALLOWED_THEME:
        primary_theme = "outros"
    if urgency not in ALLOWED_URGENCY:
        urgency = "media"

    sentiment_score = payload.get("sentiment_score", payload.get("score_sentimento", 0))
    try:
        sentiment_score = float(sentiment_score)
    except (TypeError, ValueError):
        sentiment_score = 0.0

    confidence = payload.get("confidence", payload.get("confianca", 0.7))
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.7

    recommendation = str(
        payload.get("recomendacao_interna_gocase")
        or payload.get("actionable_recommendation")
        or "Revisar caso manualmente."
    ).strip()
    if not recommendation:
        recommendation = "Revisar caso manualmente."

    escalation_required = _to_bool(
        payload.get("escalation_required", payload.get("escalonamento_necessario", False))
    )

    normalized = {
        "sentiment_label": sentiment_label,
        "sentiment_score": max(-1.0, min(1.0, sentiment_score)),
        "primary_theme": primary_theme,
        "urgency": urgency,
        "priority": max(1, min(5, priority)),
        "actionable_recommendation": recommendation,
        "escalation_required": escalation_required,
        "confidence": max(0.0, min(1.0, confidence)),
    }
    return _attach_corporate_aliases(normalized)


def analyze_feedback_with_groq(text: str, client: Groq | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.groq_api_key:
        fallback = analyze_feedback_with_rules(text)
        fallback = _attach_corporate_aliases(fallback)
        fallback["analysis_notes"] = "GROQ_API_KEY ausente. Fallback de regras aplicado."
        return fallback

    local_client = client or Groq(api_key=settings.groq_api_key)

    try:
        completion = local_client.chat.completions.create(
            model=settings.groq_model,
            temperature=0.2,
            max_tokens=350,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
            ],
        )

        content = completion.choices[0].message.content or "{}"
        payload = _extract_json_block(content)
        normalized = _sanitize_model_output(payload)
        normalized["ai_provider"] = "groq"
        normalized["model_used"] = settings.groq_model
        normalized["analysis_notes"] = "Analisado com Groq"
        return normalized
    except Exception as exc:
        fallback = analyze_feedback_with_rules(text)
        fallback = _attach_corporate_aliases(fallback)
        fallback["analysis_notes"] = f"Fallback aplicado por erro Groq: {exc}"
        return fallback


def enrich_feedback_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        expected = [
            "sentiment_label",
            "sentiment_score",
            "primary_theme",
            "urgency",
            "priority",
            "actionable_recommendation",
            "recomendacao_interna_gocase",
            "sentimento",
            "tema_principal",
            "prioridade",
            "escalation_required",
            "ai_provider",
            "model_used",
            "confidence",
            "analysis_notes",
        ]
        for col in expected:
            df[col] = []
        return df

    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key) if settings.groq_api_key else None

    enriched_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        result = analyze_feedback_with_groq(str(row.get("raw_text", "")), client=client)
        merged = row.to_dict()
        merged.update(result)
        enriched_rows.append(merged)

    enriched = pd.DataFrame(enriched_rows)
    return enriched


def save_analyzed_feedback(df: pd.DataFrame, output_path: str | None = None) -> str:
    target = output_path or str(DATA_PROCESSED_DIR / "analyzed_feedback.csv")
    pd.DataFrame(df).to_csv(target, index=False, encoding="utf-8")
    return target
