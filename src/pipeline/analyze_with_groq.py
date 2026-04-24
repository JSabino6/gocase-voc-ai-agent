from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
from groq import Groq

from src.config import DATA_PROCESSED_DIR, get_settings
from src.pipeline.fallback_rules import analyze_feedback_with_rules

SYSTEM_PROMPT = """
Voce e um Analista Senior de Customer Experience (CX) e Engenharia de Qualidade trabalhando internamente na Gocase.
Sua missao e classificar reclamacoes e orientar a equipe interna com plano de acao objetivo.

POLITICAS GLOBAIS (RESUMO):
1) Arrependimento e cancelamento:
- Produtos personalizados em producao nao podem ser cancelados.
- Produtos clear podem ser cancelados se nao recebidos.
- Arrependimento: 7 dias corridos apos recebimento.
- Reembolso/vale somente apos postagem e comprovante da logistica reversa.

2) Reembolso:
- Mesma forma de pagamento.
- Pix/boleto apenas para conta do titular da compra.
- Promocao: estorno sobre valor efetivamente pago.

3) Garantia e avarias:
- Solicitar retorno do produto com embalagem/acessorios para analise.
- Borracha de vedacao de garrafa termica: orientar protocolo no WhatsApp para reposicao com frete de R$ 15,00.
- Garantia malas: Trip/Voyage (6 meses descascamento, 3 meses demais); Bold (3 meses geral).

4) Atendimento e logistica:
- Nao culpar cliente por falha de transportadora ou demora de atendimento.
- Priorizar contato, acareacao com transportadora e reenvio expresso quando aplicavel.

DIRETRIZES:
- Nao responder com julgamento moral.
- Gerar duas saidas:
  recomendacao_interna_gocase: plano de acao interno.
  resposta_sugerida_cliente: GUIA INTERNO para o atendente (nao resposta final ao cliente).
- O campo resposta_sugerida_cliente deve conter 3 blocos:
  1) Guia para atendente
  2) Checklist do atendimento
  3) Texto-base editavel (personalizar antes de enviar)
""".strip()

USER_PROMPT_TEMPLATE = """
Analise o feedback abaixo em portugues e retorne APENAS um JSON valido.

Campos obrigatorios:
- sentimento: positivo | neutro | negativo
- tema_principal: entrega | qualidade_produto | preco_frete | atendimento | portfolio_personalizacao | outros
- prioridade: inteiro de 1 a 5
- recomendacao_interna_gocase: recomendacao objetiva e acionavel para os times internos da Gocase
- resposta_sugerida_cliente: guia interno para o atendente do SAC (nao escrever resposta final direta ao cliente)

Regras para resposta_sugerida_cliente:
- Nao iniciar com "Ola", "Prezado cliente", etc.
- Trazer os 3 blocos:
  1) Guia para atendente
  2) Checklist do atendimento
  3) Texto-base editavel (personalizar antes de enviar)
- Citar a dor especifica do caso e proximo passo concreto.
- Incluir referencia de protocolo/pedido quando houver no relato; se nao houver, usar [informar].

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
    return str(value).strip().lower() in {"1", "true", "t", "sim", "yes", "y"}


def _normalize_author_name(author: str) -> str:
    cleaned = str(author or "").strip()
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    generic_values = {
        "consumidor",
        "consumidor ra",
        "cliente",
        "anonimo",
        "anônimo",
        "nao informado",
        "não informado",
    }
    if lowered in generic_values or lowered.startswith("consumidor"):
        return ""
    return cleaned


def _extract_case_reference(feedback_text: str) -> str:
    match = re.search(
        r"\b(protocolo|pedido|id)\b\s*(?:numero|n[º°o\.]|#)?\s*[:#-]?\s*([A-Za-z0-9*._\-/]{3,})",
        feedback_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return "protocolo/pedido [informar]"

    label = match.group(1).lower()
    value = match.group(2).strip(".,;:)")
    if not re.search(r"[0-9*]", value):
        return "protocolo/pedido [informar]"
    if label == "id":
        return f"ID {value}"
    return f"{label} {value}"


def _issue_summary(theme: str, feedback_text: str) -> str:
    lower = feedback_text.lower()
    if "cupom" in lower:
        return "dificuldade com cupom e finalizacao da compra"
    if "nao recebi" in lower or "não recebi" in lower:
        return "divergencia de entrega e nao recebimento do pedido"
    if "reembolso" in lower or "estorno" in lower:
        return "solicitacao de reembolso"
    if "troca" in lower and "recus" in lower:
        return "recusa de troca no atendimento"

    by_theme = {
        "entrega": "atraso ou problema de entrega",
        "qualidade_produto": "defeito ou avaria de produto",
        "preco_frete": "divergencia de preco/frete/promocao",
        "atendimento": "dificuldade de atendimento e retorno",
        "portfolio_personalizacao": "expectativa sobre personalizacao/modelo",
        "outros": "transtorno relatado pelo cliente",
    }
    return by_theme.get(theme, by_theme["outros"])


def _next_step_summary(theme: str, feedback_text: str) -> str:
    lower = feedback_text.lower()
    if "cupom" in lower:
        return "validar regra promocional com time comercial e retornar alternativa aplicavel"
    if "reembolso" in lower or "estorno" in lower:
        return "confirmar tratativa financeira na mesma forma de pagamento"

    by_theme = {
        "entrega": "fazer acareacao com transportadora e definir novo prazo ou reenvio",
        "qualidade_produto": "abrir tratativa de qualidade para troca/reembolso conforme politica",
        "preco_frete": "revisar condicoes comerciais aplicadas ao pedido",
        "atendimento": "priorizar retorno humano com orientacao clara",
        "portfolio_personalizacao": "revisar fluxo de personalizacao e opcao de ajuste/troca",
        "outros": "fazer triagem com time responsavel e registrar plano de resolucao",
    }
    return by_theme.get(theme, by_theme["outros"])


def _is_generic_customer_response(customer_response: str) -> bool:
    normalized = " ".join(str(customer_response).lower().split())
    if not normalized or len(normalized) < 120:
        return True

    generic_markers = [
        "sentimos muito pelo transtorno",
        "seguimos a disposicao",
        "retornaremos por este canal",
    ]
    specific_markers = [
        "protocolo",
        "pedido",
        "reembolso",
        "troca",
        "transportadora",
        "garantia",
        "cupom",
        "prazo",
        "devolucao",
        "estorno",
        "checklist",
        "guia para atendente",
    ]

    generic_hits = sum(marker in normalized for marker in generic_markers)
    specific_hits = sum(marker in normalized for marker in specific_markers)
    return generic_hits >= 2 and specific_hits == 0


def _build_customer_text_base(
    sentiment_label: str,
    issue: str,
    case_reference: str,
    next_step: str,
    urgency: str,
    author: str,
) -> str:
    customer_name = _normalize_author_name(author)
    greeting = f"Ola, {customer_name}" if customer_name else "Ola"
    priority_phrase = "com prioridade maxima" if urgency in {"alta", "critica"} else "com prioridade"

    if sentiment_label == "positivo":
        return (
            f"{greeting}! Obrigado por compartilhar sua experiencia positiva com a Gocase. "
            "Seu feedback foi registrado internamente para reforcarmos os pontos fortes do atendimento e do produto. "
            "Se precisar de qualquer suporte adicional, seguimos a disposicao."
        )

    return (
        f"{greeting}! Sinto muito pelo ocorrido e entendo sua insatisfacao com {issue}. "
        f"Referente ao seu {case_reference}, sua tratativa foi registrada {priority_phrase}. "
        f"Nosso proximo passo e {next_step}. "
        "Assim que tivermos atualizacao, retornaremos por este canal com os proximos passos."
    )


def _default_customer_response(
    theme: str,
    sentiment_label: str,
    urgency: str = "media",
    feedback_text: str = "",
    author: str = "",
    recommendation: str = "",
) -> str:
    issue = _issue_summary(theme, feedback_text)
    next_step = _next_step_summary(theme, feedback_text)
    case_reference = _extract_case_reference(feedback_text)
    sla = "ate 4 horas" if urgency in {"alta", "critica"} else "ate 1 dia util"

    recommendation_line = recommendation.strip() if recommendation else "Validar tratamento com o time responsavel."
    text_base = _build_customer_text_base(
        sentiment_label=sentiment_label,
        issue=issue,
        case_reference=case_reference,
        next_step=next_step,
        urgency=urgency,
        author=author,
    )

    return (
        "Guia para atendente (uso interno):\n"
        f"- Dor principal a reconhecer: {issue}.\n"
        f"- Caso para conferir no CRM: {case_reference}.\n"
        f"- Acao interna obrigatoria: {recommendation_line}.\n"
        f"- Proximo passo para comunicar: {next_step}.\n\n"
        "Checklist do atendimento:\n"
        "1. Validar dados do pedido/protocolo e status atual da tratativa.\n"
        "2. Confirmar politica aplicavel ao caso (troca, reembolso, garantia, logistica).\n"
        f"3. Informar prazo de retorno ao cliente: {sla}.\n"
        "4. Registrar no historico o compromisso assumido na resposta.\n\n"
        "Texto-base editavel (personalizar antes de enviar):\n"
        f"\"{text_base}\""
    )


def _looks_customer_facing(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False

    direct_openers = [
        "ola",
        "olá",
        "prezado",
        "prezada",
        "sentimos",
        "sinto muito",
        "lamentamos",
    ]

    starts_direct = any(normalized.startswith(opener) for opener in direct_openers)
    has_internal_labels = all(
        marker in normalized
        for marker in ["guia para atendente", "checklist", "texto-base editavel"]
    )
    return starts_direct and not has_internal_labels


def _ensure_employee_guidance(
    response_text: str,
    theme: str,
    sentiment_label: str,
    urgency: str,
    feedback_text: str,
    author: str,
    recommendation: str,
) -> str:
    normalized = str(response_text or "").strip()
    if not normalized:
        return _default_customer_response(
            theme=theme,
            sentiment_label=sentiment_label,
            urgency=urgency,
            feedback_text=feedback_text,
            author=author,
            recommendation=recommendation,
        )

    lowered = normalized.lower()
    has_internal_shape = all(
        marker in lowered
        for marker in ["guia para atendente", "checklist", "texto-base"]
    )
    if has_internal_shape:
        return normalized

    if _looks_customer_facing(normalized) or _is_generic_customer_response(normalized):
        return _default_customer_response(
            theme=theme,
            sentiment_label=sentiment_label,
            urgency=urgency,
            feedback_text=feedback_text,
            author=author,
            recommendation=recommendation,
        )

    # Se nao estiver no formato padrao, encapsula o conteudo como guia interno.
    issue = _issue_summary(theme, feedback_text)
    case_reference = _extract_case_reference(feedback_text)
    next_step = _next_step_summary(theme, feedback_text)
    return (
        "Guia para atendente (uso interno):\n"
        f"- Dor principal a reconhecer: {issue}.\n"
        f"- Caso para conferir no CRM: {case_reference}.\n"
        f"- Proximo passo para comunicar: {next_step}.\n\n"
        "Checklist do atendimento:\n"
        "1. Validar numero do pedido/protocolo e status no sistema.\n"
        "2. Confirmar politica aplicavel antes de responder.\n"
        "3. Informar prazo e dono da tratativa.\n"
        "4. Registrar historico da acao.\n\n"
        "Texto-base editavel (personalizar antes de enviar):\n"
        f"\"{normalized}\""
    )


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

    customer_response = str(
        payload.get("resposta_sugerida_cliente")
        or payload.get("suggested_customer_response")
        or ""
    ).strip()

    theme = str(payload.get("primary_theme", "outros")).strip().lower()
    sentiment = str(payload.get("sentiment_label", "neutro")).strip().lower()
    urgency = str(payload.get("urgency", "media")).strip().lower()
    feedback_text = str(payload.get("raw_text", "") or "")
    author = str(payload.get("author", "") or "")

    customer_response = _ensure_employee_guidance(
        response_text=customer_response,
        theme=theme,
        sentiment_label=sentiment,
        urgency=urgency,
        feedback_text=feedback_text,
        author=author,
        recommendation=recommendation,
    )

    payload["resposta_sugerida_cliente"] = customer_response
    payload["suggested_customer_response"] = customer_response

    priority_value = payload.get("priority", 3)
    try:
        priority = int(priority_value)
    except (TypeError, ValueError):
        priority = 3

    payload["sentimento"] = sentiment
    payload["tema_principal"] = theme
    payload["prioridade"] = max(1, min(5, priority))
    payload["guia_resposta_atendente"] = customer_response
    return payload


def _extract_json_block(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return json.loads(content)

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("No JSON payload found in model response")
    return json.loads(match.group(0))


def _sanitize_model_output(
    payload: dict[str, Any],
    feedback_text: str = "",
    author: str = "",
) -> dict[str, Any]:
    sentiment_label = str(payload.get("sentiment_label", payload.get("sentimento", "neutro"))).strip().lower()
    primary_theme = str(payload.get("primary_theme", payload.get("tema_principal", "outros"))).strip().lower()

    priority_value = payload.get("priority", payload.get("prioridade", 3))
    try:
        priority = int(priority_value)
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

    sentiment_score_value = payload.get("sentiment_score", payload.get("score_sentimento", 0))
    try:
        sentiment_score = float(sentiment_score_value)
    except (TypeError, ValueError):
        sentiment_score = 0.0

    confidence_value = payload.get("confidence", payload.get("confianca", 0.7))
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError):
        confidence = 0.7

    recommendation = str(
        payload.get("recomendacao_interna_gocase")
        or payload.get("actionable_recommendation")
        or "Revisar caso manualmente."
    ).strip()
    if not recommendation:
        recommendation = "Revisar caso manualmente."

    customer_response = str(
        payload.get("resposta_sugerida_cliente")
        or payload.get("suggested_customer_response")
        or ""
    ).strip()

    customer_response = _ensure_employee_guidance(
        response_text=customer_response,
        theme=primary_theme,
        sentiment_label=sentiment_label,
        urgency=urgency,
        feedback_text=feedback_text,
        author=author,
        recommendation=recommendation,
    )

    escalation_required = _to_bool(payload.get("escalation_required", payload.get("escalonamento_necessario", False)))

    normalized = {
        "sentiment_label": sentiment_label,
        "sentiment_score": max(-1.0, min(1.0, sentiment_score)),
        "primary_theme": primary_theme,
        "urgency": urgency,
        "priority": max(1, min(5, priority)),
        "actionable_recommendation": recommendation,
        "resposta_sugerida_cliente": customer_response,
        "escalation_required": escalation_required,
        "confidence": max(0.0, min(1.0, confidence)),
        "raw_text": feedback_text,
        "author": author,
    }
    return _attach_corporate_aliases(normalized)


def analyze_feedback_with_groq(
    text: str,
    client: Groq | None = None,
    author: str = "",
) -> dict[str, Any]:
    settings = get_settings()

    if not settings.groq_api_key:
        fallback = analyze_feedback_with_rules(text)
        fallback["raw_text"] = text
        fallback["author"] = author
        fallback = _attach_corporate_aliases(fallback)
        fallback["resposta_sugerida_cliente"] = _ensure_employee_guidance(
            response_text=str(fallback.get("resposta_sugerida_cliente", "")),
            theme=str(fallback.get("primary_theme", "outros")),
            sentiment_label=str(fallback.get("sentiment_label", "neutro")),
            urgency=str(fallback.get("urgency", "media")),
            feedback_text=text,
            author=author,
            recommendation=str(fallback.get("actionable_recommendation", "")),
        )
        fallback["analysis_notes"] = "GROQ_API_KEY ausente. Fallback de regras aplicado."
        return fallback

    local_client = client or Groq(api_key=settings.groq_api_key)

    try:
        completion = local_client.chat.completions.create(
            model=settings.groq_model,
            temperature=0.2,
            max_tokens=700,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
            ],
        )

        content = completion.choices[0].message.content or "{}"
        payload = _extract_json_block(content)
        normalized = _sanitize_model_output(payload, feedback_text=text, author=author)
        normalized["ai_provider"] = "groq"
        normalized["model_used"] = settings.groq_model
        normalized["analysis_notes"] = "Analisado com Groq"
        return normalized
    except Exception as exc:
        fallback = analyze_feedback_with_rules(text)
        fallback["raw_text"] = text
        fallback["author"] = author
        fallback = _attach_corporate_aliases(fallback)
        fallback["resposta_sugerida_cliente"] = _ensure_employee_guidance(
            response_text=str(fallback.get("resposta_sugerida_cliente", "")),
            theme=str(fallback.get("primary_theme", "outros")),
            sentiment_label=str(fallback.get("sentiment_label", "neutro")),
            urgency=str(fallback.get("urgency", "media")),
            feedback_text=text,
            author=author,
            recommendation=str(fallback.get("actionable_recommendation", "")),
        )
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
            "resposta_sugerida_cliente",
            "guia_resposta_atendente",
            "sentimento",
            "tema_principal",
            "prioridade",
            "escalation_required",
            "ai_provider",
            "model_used",
            "confidence",
            "analysis_notes",
        ]
        for column in expected:
            df[column] = []
        return df

    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key) if settings.groq_api_key else None

    enriched_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        result = analyze_feedback_with_groq(
            str(row.get("raw_text", "")),
            client=client,
            author=str(row.get("author", "")),
        )
        merged = row.to_dict()
        merged.update(result)
        enriched_rows.append(merged)

    return pd.DataFrame(enriched_rows)


def save_analyzed_feedback(df: pd.DataFrame, output_path: str | None = None) -> str:
    target = output_path or str(DATA_PROCESSED_DIR / "analyzed_feedback.csv")
    pd.DataFrame(df).to_csv(target, index=False, encoding="utf-8")
    return target
