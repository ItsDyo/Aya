# Permissoes por canal

A Aya aplica autorizacao no nucleo antes de executar uma acao. Ocultar um botao
na interface nao e considerado uma protecao suficiente.

## Perfis

| Canal | Uso | Capacidades |
| --- | --- | --- |
| `local_terminal` | Terminal no computador da Aya | Acesso completo |
| `local_gradio` | Gradio acessado apenas no computador | Acesso completo |
| `remote_gradio` | Celular/computador via Tailscale Serve e login | Conversa, companhia, estudo, status, consulta de memoria, consulta de conhecimento e RAG |
| `limited_integration` | Base para conectores futuros | Conversa sem memoria/historico global, estudo, status e conhecimento sem RAG |

No `remote_gradio`, ficam bloqueados:

- leitura e auditoria dos arquivos do projeto;
- ingestao de arquivos;
- escrita, edicao ou curadoria de memoria;
- escrita de conhecimento;
- criacao, verificacao ou extracao de backups;
- diagnosticos internos e alteracao da autonomia;
- exportacao de dataset de fine-tuning.

Essas operacoes devem ser feitas no terminal local ou no Gradio local. Os
controles correspondentes tambem ficam ocultos quando `AYA_REMOTE_MODE=true`.

## Regra para novas integracoes

Toda nova entrada deve chamar `Assistant.responder(..., channel=...)`. Nunca
chame diretamente banco, backup, ingestao ou ferramentas de projeto a partir de
um bot, webhook ou outro conector.

O perfil `limited_integration` e apenas uma fundacao de seguranca. Antes de
ativar Telegram ou outro mensageiro, ainda e necessario criar identidade do
usuario, historico isolado por canal, limite de requisicoes e confirmacao para
acoes persistentes.
