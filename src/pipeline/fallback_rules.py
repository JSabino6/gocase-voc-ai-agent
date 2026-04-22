from __future__ import annotations

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
        "entrega": "Revisar SLA de entrega e comunicacao proativa de rastreio para pedidos atrasados.",
        "qualidade_produto": "Priorizar investigacao de qualidade do produto e abrir acao corretiva com fornecedor.",
        "preco_frete": "Testar campanha de frete reduzido e simular parcelamento sem juros em tickets selecionados.",
        "atendimento": "Reforcar fila de suporte e tempo de primeira resposta nos chamados mais sensiveis.",
        "portfolio_personalizacao": "Mapear pedidos de novos modelos para alimentar backlog de portfolio.",
        "outros": "Realizar triagem manual para identificar causa raiz e proxima acao.",
    }
    base = recommendations.get(theme, recommendations["outros"])
    if sentiment_label == "positivo":
        return "Mapear este feedback como ponto forte e replicar boas praticas no restante da operacao."
    return base


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

    return {
        "sentiment_label": sentiment_label,
        "sentiment_score": round(sentiment_score, 2),
        "primary_theme": primary_theme,
        "urgency": urgency,
        "priority": priority,
        "actionable_recommendation": _recommendation(primary_theme, sentiment_label),
        "escalation_required": escalation_required,
        "ai_provider": "rules",
        "model_used": "deterministic_rules_v1",
        "confidence": 0.55,
    }
