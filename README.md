# Gocase VoC AI Agent (MVP)

Projeto de automacao com IA para transformar feedback de clientes em relatorios acionaveis para negocio.

Video explicativo: https://youtu.be/bwer3-99_m4

## Problema de negocio
Times de CX, Produto e Operacoes perdem muito tempo lendo feedback manualmente em canais diferentes.

## Solucao
Um agente IA que:
1. Coleta reclamacoes do Reclame Aqui (automatico + fallback manual em CSV).
2. Normaliza os dados em um formato unico.
3. Analisa cada feedback com Groq (ou fallback por regras), gerando recomendacao interna e guia de resposta para o atendente.
4. Gera relatorio executivo com pontos positivos, criticas e acoes prioritarias.
5. Exibe dashboard para acompanhamento rapido.

## Campos gerados pela IA
No arquivo `data/processed/analyzed_feedback.csv`, cada feedback passa a ter dois campos de saida principais para operacao:
- `recomendacao_interna_gocase`: orientacao acionavel para o time interno (produto, logistica, CX, qualidade).
- `resposta_sugerida_cliente`: guia interno para o analista do SAC montar resposta profissional no Reclame Aqui (com checklist e texto-base editavel).

## Arquitetura (MVP)
- Coleta: src/collectors
- Processamento IA: src/pipeline
- Relatorio: src/reporting
- Dashboard: app/streamlit_app.py
- Orquestracao: scripts/run_pipeline.py

## Como executar
### 1) Instalar dependencias
```bash
pip install -r requirements.txt
```

Observacao: o `requirements.txt` foi ajustado para compatibilidade com Python 3.13.

### 2) Configurar variaveis de ambiente
```bash
copy .env.example .env
```
Preencha no `.env`:
- GROQ_API_KEY
- GROQ_MODEL llama-3.3-70b-versatile 
- REQUEST_TIMEOUT_SECONDS (opcional)

### 3) Rodar pipeline completo
```bash
python scripts/run_pipeline.py
```

### 4) Subir dashboard
```bash
streamlit run app/streamlit_app.py
```

## Extrair e atualizar dados (Sidebar)
No dashboard, na barra lateral, existe a secao de extracao com:
- `Modo de extracao Reclame Aqui` (`Automatica (site)`, `Automatica + Manual (fallback)`, `Manual (CSV)`)
- `Limite Maximo de Extracao` (number input)
- `Periodo da extracao` (`Sem limite`, `Ultimas 24 horas`, `Ultimos 7 dias`, `Ultimas N horas`)
- `Status das Reclamacoes` (`Todas`, `Resolvidas`, `Não Resolvidas`)
- botao `Extrair e Atualizar Dados`

Ao clicar no botao:
1. O app chama a carga manual do Reclame Aqui com os filtros escolhidos.
2. Faz merge com o arquivo existente `data/raw/reclameaqui_feedback.csv`.
3. Aplica `drop_duplicates(subset=['feedback_id'], keep='last')`.
4. Salva o CSV atualizado sem repeticoes.
5. Mostra quantos registros novos foram efetivamente adicionados.

### Como funciona a coleta automatica
- Reclame Aqui: tenta coletar diretamente de `https://www.reclameaqui.com.br/empresa/go-case/lista-reclamacoes/` e paginas de detalhe.
- Fallback recomendando: `Automatica + Manual (fallback)` para evitar tela sem dados quando houver bloqueio temporario de scraping.

## Enviar PDF por e-mail
O dashboard possui o botao `Enviar Insights para EMAIL` para envio do arquivo `data/processed/executive_report.pdf`.

Configure no `.env`:
- SMTP_HOST
- SMTP_PORT
- SMTP_USERNAME
- SMTP_PASSWORD
- SMTP_SENDER_EMAIL
- SMTP_USE_TLS

Depois, no painel, informe um ou mais destinatarios (separados por virgula) e clique no botao de envio.

## Entradas e saidas
### Entrada
- data/raw/reclameaqui_manual_template.csv (editavel)

### Saida
- data/raw/reclameaqui_feedback.csv
- data/processed/normalized_feedback.csv
- data/processed/analyzed_feedback.csv
- data/processed/executive_report.md
- data/processed/executive_report.pdf

## Compliance para MVP
- Uso de dados publicos para fins de demonstracao tecnica.
- Nao republicar dados pessoais sensiveis.
- Em producao, substituir coleta manual por integracoes oficiais.

## Estrutura
```text
Desafio 1/
  app/
  data/
    raw/
    processed/
  docs/
  scripts/
  src/
```
