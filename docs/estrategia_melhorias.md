# Estrategia de Melhorias para Surpreender no Processo Seletivo

## 1. Diagnostico atual (MVP)
- Ponto forte: pipeline ponta a ponta (coleta, analise IA, dashboard e PDF executivo).
- Gap principal: respostas estavam no modo "SAC final", quando o ideal e "copiloto do atendente".
- Risco tecnico: dependencia de fonte externa (scraping) e variacao de qualidade dos dados.

## 2. Melhoria critica ja implementada
- A saida `resposta_sugerida_cliente` foi reposicionada para **guia interno do atendente**:
  - bloco `Guia para atendente`
  - bloco `Checklist do atendimento`
  - bloco `Texto-base editavel (personalizar antes de enviar)`
- Esse formato evita resposta automatica indevida e aumenta padrao operacional.

## 3. Melhorias de alto impacto (proximas)
1. Score de qualidade da resposta interna
- Medir se a sugestao contem protocolo, proximo passo e prazo.
- Exibir no dashboard `% de sugestoes completas`.

2. Triage por fila operacional
- Criar fila por `tema x prioridade x status` com dono sugerido:
  - Logistica
  - Qualidade
  - SAC
  - Financeiro

3. Alertas de crise
- Disparar alerta quando houver:
  - pico de prioridade 5
  - aumento de tema critico em 24h
  - queda abrupta de sentimento

4. Qualidade de classificacao (QA)
- Amostragem semanal de 30 casos.
- Comparar IA vs avaliacao humana.
- KPI: acuracia por tema, prioridade e urgencia.

5. Camada de auditoria para producao
- Registrar versao do prompt, modelo, timestamp, confianca e fallback.
- Facilita explicabilidade para lideranca e compliance.

## 4. Plano de execucao sugerido (15 dias)
1. Dias 1-3
- Consolidar taxonomia de temas com CX.
- Definir SLA por prioridade (P5, P4, P3...).

2. Dias 4-7
- Implementar score de qualidade da sugestao.
- Implementar fila operacional no dashboard.

3. Dias 8-11
- Implementar alertas (e-mail ou webhook).
- Validar casos de excecao (sem protocolo, texto curto, dados incompletos).

4. Dias 12-15
- QA com amostra real.
- Ajustar prompt/regras.
- Entregar mini-relatorio de impacto.

## 5. KPIs para apresentar ao avaliador
- Tempo medio de triagem antes vs depois.
- % de casos criticos tratados dentro do SLA.
- % de respostas com checklist completo.
- % de feedback classificado automaticamente sem retrabalho.
- Reducao de backlog de atendimento critico.

## 6. Possiveis falhas e mitigacoes
1. Classificacao incorreta de tema
- Mitigacao: fallback por regras + QA amostral.

2. Sugestao sem contexto suficiente
- Mitigacao: checklist obrigatorio com campos minimos.

3. Fonte externa indisponivel
- Mitigacao: modo manual + cache local + rotina de retentativa.

4. Adocao baixa pelo time
- Mitigacao: painel simples, treinamento rapido e feedback loop com SAC.

## 7. Narrativa para entrevista
- "Nao quis automatizar resposta ao cliente sem controle; transformei o agente em copiloto do atendente."
- "Assim, ganho velocidade sem perder qualidade, governanca e responsabilidade humana na etapa final."
