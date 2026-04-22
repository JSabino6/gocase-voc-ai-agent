# Documentacao Completa da Automacao

## 1. Resumo
Este projeto implementa um agente de IA para Voz do Cliente (VoC) com foco em gerar inteligencia de negocio a partir de avaliacoes e reclamacoes publicas.

Area escolhida: Customer Experience / Operacoes

Dor real: feedback de clientes esta disperso e demanda leitura manual, atrasando decisao e acao.

## 2. Objetivo
Automatizar o ciclo:
1. Captura de feedback
2. Classificacao de sentimento e tema
3. Priorizacao de risco
4. Recomendacao de acao
5. Entrega de relatorio executivo e dashboard

## 3. Fontes de dados no MVP
### 3.1 Ebit (automatico)
- Tipo: avaliacoes publicas
- Metodo: parser HTML
- Valor: massa de comentarios com elogios e criticas
- Observacao tecnica: quando o Ebit retorna apenas frontend SPA em HTML estatico, o sistema usa fallback para `data/raw/ebit_manual_seed.csv`.

### 3.2 Reclame Aqui (manual estruturado)
- Tipo: reclamacoes e status
- Metodo: template CSV preenchido manualmente
- Valor: contexto atual e mais critico para operacao

### 3.3 Reclame Aqui (automatico paginado)
- Tipo: reclamacoes publicas
- Metodo: crawler com navegacao por paginas (`?pagina=1..N`) para evitar limite de 5 itens da primeira pagina
- Valor: extracao recorrente com maior volume
- Filtros suportados: status (`Todas`, `Resolvidas`, `Não Resolvidas`) e janela temporal (`24h`, `7 dias`, `N horas`)

## 4. Arquitetura tecnica
### 4.1 Coleta
- src/collectors/ebit_collector.py
- src/collectors/ra_manual_loader.py

### 4.2 Normalizacao
- src/pipeline/normalize_feedback.py
- Esquema final padrao:
  - feedback_id
  - source
  - source_url
  - author
  - feedback_date
  - raw_text
  - initial_category
  - channel
  - status

### 4.3 Analise IA
- src/pipeline/analyze_with_groq.py
- src/pipeline/fallback_rules.py

Campos gerados:
- sentiment_label (positivo/neutro/negativo)
- sentiment_score (-1 a 1)
- primary_theme
- urgency
- priority (1-5)
- actionable_recommendation
- escalation_required
- ai_provider
- model_used
- confidence

### 4.4 Relatorio
- src/reporting/build_report.py
- Saidas:
  - Markdown executivo
  - PDF executivo

### 4.5 Dashboard
- app/streamlit_app.py
- Visoes:
  - KPIs
  - distribuicao de sentimento
  - top temas
  - bloco WHAT WAS POSITIVE?
  - tabela de casos prioritarios

## 5. Prompt da IA (Groq)
O prompt pede JSON estrito com taxonomia fixa para facilitar governanca e reduzir ruido.

## 6. Fallback sem IA
Se a Groq falhar ou a chave nao estiver disponivel, o sistema aplica regras deterministicas por palavras-chave.

Beneficio:
- O fluxo nao para
- O dashboard continua funcionando

## 7. Ganhos esperados
### Operacao
- Menos tempo de leitura manual
- Triagem automatica de urgencia

### Negocio
- Visao clara de dor por tema
- Priorizacao de backlog por impacto no cliente

### Gestao
- Relatorio padrao semanal com foco em acao

## 8. Limitacoes do MVP
- Ebit possui historico mais antigo
- Ebit pode exigir renderizacao JS para exibir reviews em tempo real
- Reclame Aqui esta em carga manual no MVP
- Taxonomia inicial simples (fase 1)

Nota tecnica: o Reclame Aqui pode responder com protecao anti-bot em alguns cenarios. O sistema usa fallback tecnico e modo `Automatica + Manual (fallback)` para manter continuidade da operacao.

## 9. Evolucao recomendada
1. Integrar NPS interno, tickets e CRM
2. Implementar ingestao oficial de parceiros de dados
3. Treinar taxonomia customizada da empresa
4. Criar fluxo de alertas em Slack/Email

## 10. Como operar
1. Atualizar arquivo data/raw/reclameaqui_manual_template.csv
2. Rodar python scripts/run_pipeline.py
3. Abrir streamlit run app/streamlit_app.py
4. Consultar relatorios em data/processed

## 11. Evidencia de uso de IA
A automacao usa API Groq para inferencia de sentimento, tema, prioridade e recomendacao por feedback, com fallback auditavel por regras.
