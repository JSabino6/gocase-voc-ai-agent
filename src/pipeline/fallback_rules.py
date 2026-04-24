from __future__ import annotations

import re
from typing import Any

NEGATIVE_WORDS = {
    "atraso",
    "demora",
    "demorou",
    "defeito",
    "problema",
    "quebrou",
    "rasg",
    "ferrug",
    "ruim",
    "pessim",
    "caro",
    "juros",
    "nao recebi",
}

POSITIVE_WORDS = {
    "adorei",
    "amei",
    "excelente",
    "otima",
    "otimo",
    "qualidade",
    "recomendo",
    "satisfeita",
    "satisfeito",
    "lindo",
}

THEME_KEYWORDS = {
    "entrega": {"atraso", "entrega", "prazo", "transportadora", "nao recebi"},
    "qualidade_produto": {"qualidade", "defeito", "descasc", "ferrug", "rasg", "quebrou"},
    "preco_frete": {"preco", "caro", "frete", "juros", "parcel"},
    "atendimento": {"atendimento", "chamado", "resposta", "suporte"},
    "portfolio_personalizacao": {"modelo", "personalizado", "opcao", "variedade"},
}


def _find_theme(text: str) -> str:
    lower = text.lower()
    best_theme = "outros"
    best_score = 0

    for theme, keywords in THEME_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in lower)
        if score > best_score:
            best_theme = theme
            best_score = score

    return best_theme


def _sentiment(text: str) -> tuple[str, float]:
    lower = text.lower()
    negative_hits = sum(1 for word in NEGATIVE_WORDS if word in lower)
    positive_hits = sum(1 for word in POSITIVE_WORDS if word in lower)

    if negative_hits > positive_hits:
        return "negativo", max(-1.0, -0.35 - (0.1 * negative_hits))
    if positive_hits > negative_hits:
        return "positivo", min(1.0, 0.35 + (0.1 * positive_hits))
    return "neutro", 0.0


def _urgency(text: str, sentiment_label: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ["urgente", "nao recebi", "ferrug", "defeito", "rasgou"]):
        return "alta"
    if sentiment_label == "negativo":
        return "media"
    return "baixa"


def _recommendation(theme: str, sentiment_label: str) -> str:
    recommendations = {
        "entrega": "Revisar SLA de entrega e comunicar rastreio proativo para pedidos atrasados.",
        "qualidade_produto": "Priorizar investigacao de qualidade e abrir acao corretiva com fornecedor/fabrica.",
        "preco_frete": "Revisar politica de frete e comunicacao comercial para reduzir friccao na compra.",
        "atendimento": "Reforcar fila de suporte e reduzir tempo de primeira resposta em casos sensiveis.",
        "portfolio_personalizacao": "Mapear recorrencia de pedidos de personalizacao para alimentar backlog de portfolio.",
        "outros": "Realizar triagem manual para identificar causa raiz e proxima acao.",
    }
    if sentiment_label == "positivo":
        return "Registrar elogio como boa pratica e compartilhar aprendizados com a operacao."
    return recommendations.get(theme, recommendations["outros"])


def _extract_case_reference(text: str) -> str:
    match = re.search(
        r"\b(protocolo|pedido|id)\b\s*(?:numero|n[º°o\.]|#)?\s*[:#-]?\s*([A-Za-z0-9*._\-/]{3,})",
        text,
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


def _issue_summary(theme: str, text: str) -> str:
    lower = text.lower()
    if "cupom" in lower:
        return "dificuldade para aplicar cupom e concluir compra"
    if "nao recebi" in lower or "não recebi" in lower:
        return "divergencia de entrega e nao recebimento"
    if "reembolso" in lower or "estorno" in lower:
        return "solicitacao de reembolso"
    if "troca" in lower and "recus" in lower:
        return "recusa de troca relatada"

    by_theme = {
        "entrega": "atraso ou problema na entrega",
        "qualidade_produto": "defeito/avaria no produto",
        "preco_frete": "divergencia de preco, frete ou promocao",
        "atendimento": "experiencia de atendimento e retorno",
        "portfolio_personalizacao": "expectativa sobre personalizacao/modelo",
        "outros": "transtorno relatado no atendimento",
    }
    return by_theme.get(theme, by_theme["outros"])


def _next_step(theme: str, text: str) -> str:
    lower = text.lower()
    if "cupom" in lower:
        return "validar regra promocional e ajustar oferta quando aplicavel"
    if "reembolso" in lower or "estorno" in lower:
        return "confirmar tratativa financeira na mesma forma de pagamento"
    if "troca" in lower or "devolu" in lower or "cancel" in lower or "arrependimento" in lower:
        return "revisar elegibilidade e retornar opcao de troca/devolucao/reembolso conforme politica"

    by_theme = {
        "entrega": "fazer acareacao com transportadora e definir novo prazo ou reenvio",
        "qualidade_produto": "abrir tratativa de qualidade para troca, reembolso ou suporte",
        "preco_frete": "revisar condicoes aplicadas ao pedido e propor alternativa adequada",
        "atendimento": "priorizar retorno humano com explicacao clara dos proximos passos",
        "portfolio_personalizacao": "revisar fluxo de personalizacao e avaliar ajuste/troca",
        "outros": "fazer triagem com o time responsavel e registrar plano de resolucao",
    }
    return by_theme.get(theme, by_theme["outros"])


def _build_customer_text_base(theme: str, sentiment_label: str, urgency: str, text: str) -> str:
    if sentiment_label == "positivo":
        return (
            "Ola! Obrigado por compartilhar sua experiencia positiva com a Gocase. "
            "Seu feedback foi registrado para reforcarmos os pontos fortes da operacao."
        )

    issue = _issue_summary(theme, text)
    case_reference = _extract_case_reference(text)
    case_next_step = _next_step(theme, text)
    priority_text = "com prioridade maxima" if urgency in {"alta", "critica"} else "com prioridade"

    return (
        f"Ola! Sinto muito pelo ocorrido e entendo sua insatisfacao com {issue}. "
        f"Referente ao {case_reference}, sua tratativa foi registrada {priority_text}. "
        f"Nosso proximo passo e {case_next_step}. "
        "Retornaremos por este canal com atualizacoes objetivas."
    )


def _customer_response(theme: str, sentiment_label: str, urgency: str, text: str) -> str:
    issue = _issue_summary(theme, text)
    case_reference = _extract_case_reference(text)
    case_next_step = _next_step(theme, text)
    sla = "ate 4 horas" if urgency in {"alta", "critica"} else "ate 1 dia util"
    text_base = _build_customer_text_base(theme, sentiment_label, urgency, text)

    return (
        "Guia para atendente (uso interno):\n"
        f"- Dor principal a reconhecer: {issue}.\n"
        f"- Caso para conferir no CRM: {case_reference}.\n"
        f"- Proximo passo que precisa constar na resposta: {case_next_step}.\n\n"
        "Checklist do atendimento:\n"
        "1. Validar status do caso no CRM/ticket.\n"
        "2. Confirmar politica aplicavel (troca, reembolso, garantia, logistica).\n"
        f"3. Informar prazo de retorno ao cliente: {sla}.\n"
        "4. Registrar historico da tratativa para auditoria.\n\n"
        "Texto-base editavel (personalizar antes de enviar):\n"
        f"\"{text_base}\""
    )


def analyze_feedback_with_rules(text: str) -> dict[str, Any]:
    sentiment_label, sentiment_score = _sentiment(text)
    primary_theme = _find_theme(text)
    urgency = _urgency(text, sentiment_label)

    priority = 1
    if sentiment_label == "negativo":
        priority += 2
    if urgency == "media":
        priority += 1
    if urgency == "alta":
        priority += 2
    if primary_theme in {"entrega", "qualidade_produto"}:
        priority += 1

    priority = max(1, min(priority, 5))
    escalation_required = bool(priority >= 4 or urgency == "alta")

    response_guide = _customer_response(primary_theme, sentiment_label, urgency, text)

    return {
        "sentiment_label": sentiment_label,
        "sentiment_score": round(sentiment_score, 2),
        "primary_theme": primary_theme,
        "urgency": urgency,
        "priority": priority,
        "actionable_recommendation": _recommendation(primary_theme, sentiment_label),
        "recomendacao_interna_gocase": _recommendation(primary_theme, sentiment_label),
        "resposta_sugerida_cliente": response_guide,
        "guia_resposta_atendente": response_guide,
        "escalation_required": escalation_required,
        "ai_provider": "rules",
        "model_used": "deterministic_rules_v2",
        "confidence": 0.62,
    }
