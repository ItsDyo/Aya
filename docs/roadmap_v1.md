# Roadmap Aya 1.0

Meta: chegar em uma Aya 1.0 estavel ate 1 de agosto de 2026, priorizando uso local, confiabilidade, memoria persistente e ajuda real no dia a dia.

## Principio da versao 1.0

Aya 1.0 nao precisa ser a versao mais poderosa possivel. Ela precisa ser a primeira versao confiavel para uso diario.

Critério central:

- iniciar sem erro;
- preservar memoria e conhecimento;
- recuperar contexto local com fontes;
- ajudar em estudos, codigo e rotina sem depender de API paga;
- funcionar no computador e no celular via acesso remoto seguro;
- ter testes e diagnosticos que mostrem quando algo quebrou.

## Ja pronto

- Estrutura modular em `aya/`.
- Interface Gradio local.
- Acesso remoto seguro com Tailscale Serve, login e senha.
- SQLite em `data_local/study_ai.db`.
- Memoria persistente com reforco, conflitos, fusao, curadoria e envelhecimento.
- Banco de conhecimento com ingestao de arquivos.
- RAG lexical e semantico com `embeddinggemma`.
- Citacoes de fontes no contexto local.
- Protecao contra instrucoes maliciosas vindas de documentos.
- Sistema de estudo com sessoes, metas, dificuldades, exercicios e revisoes.
- Modo companhia com diario.
- Voz com Piper e tratamento de erro quando modelo nao existe.
- Permissoes por canal: local, remoto e integracao limitada.
- Backups, diagnostico, smoke test e testes unitarios.
- Ajuda com codigo via `/codigo`.
- Revisao guiada de arquivo via `/revisar`.
- Plano de alteracao seguro via `/plano`, sem editar arquivos antes de confirmacao.
- Relatorio tecnico de release via `/release`.
- Historico tecnico via `/release listar`, `/release ultimo` e `/release comparar`.
- Diagnostico local/remoto com Gradio, Tailscale e avisos de seguranca.

## Prioridades para fechar Aya 1.0

1. Estabilidade de inicializacao
   - confirmar Ollama ativo;
   - confirmar modelos disponiveis;
   - confirmar Gradio local;
   - confirmar banco SQLite integro;
   - confirmar Piper sem travar interface.

2. Diagnostico de release
   - rodar `ruff`;
   - rodar `compileall`;
   - rodar `unittest`;
   - rodar `smoke_test.py`;
   - rodar `pip check`;
   - validar `PRAGMA quick_check`;
   - registrar resultado em relatorio tecnico.

3. Memoria e privacidade
   - evitar salvar dados sensiveis automaticamente;
   - separar dominios: pessoal, estudo, trabalho, programacao, Aya e geral;
   - mostrar conflitos e aprendizados pendentes com clareza;
   - manter backup antes de migracoes.

4. RAG local
   - manter `embeddinggemma` ativo;
   - mostrar aviso claro quando nenhuma fonte relevante for encontrada;
   - melhorar listagem de fontes por dominio e origem;
   - reindexar sem duplicar arquivos.

5. Interface
   - reduzir poluicao visual;
   - melhorar uso no celular;
   - esconder controles raros em areas expansíveis;
   - manter conversa como tela principal.

6. Programacao
   - evoluir `/codigo`;
   - evoluir `/revisar`;
   - usar `/plano` antes de editar arquivos;
   - nunca aplicar mudancas destrutivas sem confirmacao.

## Fora da Aya 1.0

- Telegram.
- Fine-tuning real com LoRA.
- Automacao agressiva sem confirmacao.
- Banco vetorial externo.
- Voz ultra natural.
- Edicao automatica irrestrita de arquivos.
- Expor porta no roteador.

Esses itens podem vir depois, mas nao devem atrasar a estabilidade.

## Critérios de pronto

Aya 1.0 pode ser considerada pronta quando:

- todos os testes automatizados passam;
- `pip check` nao mostra dependencias quebradas;
- o banco passa em `PRAGMA quick_check`;
- a interface abre localmente;
- o acesso remoto via Tailscale funciona sem abrir porta no roteador;
- o RAG responde com fontes quando houver contexto relevante;
- a Aya avisa quando nao houver fonte relevante;
- backup e restauracao basica estao documentados;
- o README explica instalacao, uso, diagnostico e recuperacao;
- nenhum log registra senha, token ou conteudo sensivel desnecessario.

## Relatorio tecnico de release

Disponivel via:

- `/release`
- `/release salvar`
- `/release executar`
- `/release listar`
- `/release ultimo`
- `/release comparar`

O relatorio registra fatos verificaveis no momento: banco, contadores, RAG, diagnostico e riscos. Ele nao inventa resultado de `ruff`, `unittest`, `smoke_test.py` ou `pip check` quando esses comandos nao foram executados dentro do ciclo.

`/release executar` roda as validacoes reais, mede duracao e salva o relatorio completo em `logs/releases/`.

## Historico tecnico

Disponivel via:

- `/release listar`
- `/release ultimo`
- `/release comparar`

Esse historico mostra validacoes anteriores, abre o ultimo relatorio e compara checks/dados entre os dois relatorios mais recentes.

## Diagnostico remoto/local

Disponivel via:

- `/diagnostico`

O diagnostico mostra banco, pastas, dependencias, voz, Gradio local, modo remoto, autenticacao, Tailscale, IP da tailnet quando disponivel e o comando `tailscale serve`. Ele nao imprime senha nem token.

## Proximo ciclo recomendado

Criar aplicacao assistida de mudancas pequenas:

- partir de um plano gerado por `/plano`;
- aplicar apenas patches pequenos e revisaveis;
- mostrar diff antes/depois quando possivel;
- rodar testes focados depois de cada mudanca;
- manter confirmacao obrigatoria para mudancas destrutivas.
