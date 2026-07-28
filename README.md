# Aya

Aya e uma assistente pessoal local para estudos, codigo, memoria, conhecimento e companhia leve. Ela roda no seu computador com Ollama, Gradio, SQLite, Rich e Piper TTS, priorizando privacidade e controle local.

Este README e a porta de entrada do projeto. O uso detalhado fica em `docs/`.

## Comece Aqui

- [Guia rapido](docs/guia_rapido.md): iniciar, abrir, usar no celular, ver status e encerrar.
- [Instalacao limpa](docs/instalacao_limpa.md): preparar a Aya em outro computador.
- [Comandos](docs/comandos.md): lista organizada de comandos com exemplos.
- [Backup](docs/backup.md): criar, listar, verificar e extrair backups.
- [GitHub](docs/github.md): o que versionar e o que manter fora do repositorio.
- [Problemas comuns](docs/troubleshooting.md): primeiros diagnosticos e solucoes seguras.

## Rodar

Uso diario recomendado:

```powershell
.\scripts\start_v1.ps1
```

Abrir a interface:

```powershell
.\scripts\open_v1.ps1
```

Ver status sem iniciar ou encerrar nada:

```powershell
.\scripts\status_v1.ps1
```

Tambem e possivel iniciar diretamente:

```powershell
python app.py
```

A interface local fica em:

```text
http://127.0.0.1:7860
```

## Acesso Pelo Celular

O caminho recomendado e Tailscale privado com a Aya exposta somente dentro da sua tailnet.

Leia:

- [Acesso remoto seguro](docs/acesso_remoto_seguro.md)
- [Operacao da Aya v1.0](docs/aya_v1_operacao.md)
- [Permissoes por canal](docs/permissoes_por_canal.md)

Nao use `share=True`, Tailscale Funnel ou porta aberta no roteador.

## Arquitetura

| Caminho | Responsabilidade |
| --- | --- |
| `aya/core/assistant.py` | Orquestracao principal da Aya |
| `aya/core/alerts.py` | Alertas sob demanda |
| `aya/core/memory.py` | Memoria persistente |
| `aya/core/rag.py` | Busca local e conhecimento documentado |
| `aya/core/learning.py` | Sessoes de estudo, metas e revisoes |
| `aya/core/aya_dev.py` | Aya Dev supervisionado |
| `aya/data/` | Codigo de persistencia SQLite |
| `aya/ui/` | Interfaces Gradio |
| `scripts/` | Scripts operacionais e diagnosticos |
| `tests/` | Testes automatizados |
| `docs/` | Documentacao de uso, manutencao e evolucao |

## Tecnologias

- Python
- Ollama
- SQLite
- Gradio
- Rich
- Piper TTS
- Tailscale para acesso remoto privado

## Validar

```powershell
python -m pytest
python -m ruff check .
python -m compileall .
python -m pip check
python scripts\smoke_test.py
```

## Comandos Essenciais

```text
/alertas
/alertas detalhes
/alertas revisao|memoria|curadoria|meta|aya-dev|critico
/status
/diagnostico
/continuidade
/estudar materia | minutos
/encerrar notas
/exercicio topico | nivel
/revisoes
/salvar topico | conteudo | tags
/buscar termo
/curadoria
/backup criar
/conselho
```

Veja a lista completa em [docs/comandos.md](docs/comandos.md).

## Dados Locais e Privacidade

O repositorio deve conter codigo, testes, scripts, documentacao e configuracoes de exemplo.

Nao envie para o GitHub:

- `.env`;
- bancos locais;
- memorias e conversas reais;
- backups;
- logs privados;
- modelos e vozes grandes;
- credenciais, tokens ou chaves.

Leia [docs/github.md](docs/github.md) e [docs/seguranca.md](docs/seguranca.md) antes de publicar mudancas.

## Backup

Dentro da Aya:

```text
/backup criar
```

Pelo PowerShell:

```powershell
.\scripts\backup_v1.ps1
```

Mais detalhes em [docs/backup.md](docs/backup.md) e [docs/recuperacao.md](docs/recuperacao.md).

## Modelos, Voz e Fine-Tuning

- [Modelos usados](docs/modelos_usados.md)
- [RAG avancado](docs/rag_avancado.md)
- [Plano de fine-tuning](docs/fine_tuning_plan.md)

Fine-tuning deve ensinar estilo e padroes de resposta. Memoria e conhecimento factual mutavel devem continuar no SQLite/RAG.

## Roadmap

Use `/roadmap`, `/conselho` e `/release` dentro da Aya para acompanhar a evolucao tecnica.

Tambem veja [docs/roadmap_v1.md](docs/roadmap_v1.md).
