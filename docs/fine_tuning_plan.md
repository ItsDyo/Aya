# Plano de evolução da Aya

## Regra principal

Use fine-tuning para ensinar estilo, formato de resposta, didática e comportamento. Use SQLite/RAG para fatos, preferências, conteúdos estudados e qualquer coisa que muda com o tempo.

## Fase 1 - Memória forte

- Salvar fatos estáveis com `/lembrar`.
- Salvar conteúdos estudados com `/salvar`.
- Usar `/rag consulta` para inspecionar o que a Aya recupera.
- Usar `/refletir` para transformar histórico em memórias de alto nível.

## Fase 2 - Dataset limpo

Gere o dataset:

```powershell
python -c "from aya.core.assistant import Assistant; a=Assistant(); print(a.exportar_fine_tuning()); a.encerrar()"
```

Antes de treinar:

- Remova respostas ruins.
- Remova erros factuais.
- Remova dados sensíveis.
- Remova duplicatas.
- Prefira exemplos curtos, claros e consistentes.

## Fase 3 - LoRA/QLoRA

Quando for treinar:

- Comece pequeno.
- Treine comportamento, não conhecimento factual mutável.
- Compare o modelo ajustado contra o modelo base.
- Mantenha uma suíte de perguntas fixas para regressão.

## Fase 4 - Agente local

Próximas ferramentas úteis:

- Leitura estruturada de PDFs/anotações.
- Agenda de estudos.
- Revisão espaçada.
- Quizzes automáticos.
- Análise de código do projeto.
- Planejamento semanal.
- Painel de progresso.
