# Aya v1.0 - operacao congelada

Este documento congela a Aya v1.0 para uso diario estavel. A partir deste ponto, nao execute novas calibracoes do Aya Dev durante o fechamento da v1.0.

## Estado do congelamento

- Aya Dev e experimental e supervisionado.
- Autonomia do Aya Dev fica DESLIGADA por padrao.
- Nao existe autoaprovacao, commit automatico, integracao automatica ou push automatico.
- A primeira calibracao real nao foi concluida.
- `EXP-475CFA382FA0` falhou por timeout pos-patch dos testes relacionados.
- `EXP-B770FE0E98F1` falhou por timeout da suite completa na baseline.
- Os experimentos bloquearam antes de modificar a `main`.
- A correcao do timeout global da baseline fica para Aya v1.1.

## Inicializacao local

1. Abra o Ollama e confirme os modelos:

```powershell
ollama list
ollama pull llama3.2
ollama pull gemma2:2b
```

2. Inicie a Aya:

```powershell
python app.py
```

3. Abra `http://127.0.0.1:7860`.
4. Verifique o diagnostico:

```powershell
python scripts/smoke_test.py
```

Para encerrar, use `Ctrl+C` no terminal da Aya. Logs ficam em `logs/`.

## Inicializacao v1 no Windows

Use o launcher simples:

```powershell
.\scripts\start_v1.ps1
```

Ele verifica Ollama, evita segunda instancia, registra inicio/encerramento em `logs/aya_v1_start_*.log` e mantem `AYA_HOST=127.0.0.1`.

Para iniciar junto com o Windows sem instalar servico, crie manualmente um atalho na pasta `shell:startup` apontando para:

```text
powershell.exe -ExecutionPolicy Bypass -File "E:\Aya\Teste de IA Principal\scripts\start_v1.ps1"
```

## Modos principais

- Conversa: chat normal com a Aya.
- Estudos: sessoes, metas, dificuldades, exercicios e revisoes.
- Memoria: leitura local e curadoria somente em canal local.
- RAG: consulta ao conhecimento local indexado.
- Voz: Piper local, sem API paga.
- Acesso remoto: somente Tailscale, autenticado e com permissoes reduzidas.
- Aya Dev: supervisionado, local, sem execucao automatica.

## Acesso remoto seguro

Use somente Tailscale Serve. Nao use `share=True`, Tailscale Funnel, porta no roteador ou link publico.

Configuracao esperada no `.env`:

```text
AYA_REMOTE_MODE=true
AYA_HOST=127.0.0.1
AYA_PORT=7860
AYA_AUTH_ENABLED=true
AYA_AUTH_USERNAME=...
AYA_AUTH_PASSWORD=...
```

Nao registre nem compartilhe a senha. Para publicar na tailnet:

```powershell
.\scripts\start_v1.ps1
```

Em outro terminal:

```powershell
"C:\Program Files\Tailscale\tailscale.exe" serve 7860
```

Permissoes remotas permitidas:

- conversar;
- estudar;
- companhia;
- consultar status;
- consultar memoria permitida;
- consultar conhecimento/RAG permitido.

Bloqueado remotamente pelo backend:

- Aya Dev;
- executar candidato ou experimento;
- aprovar, aplicar, integrar, reverter ou descartar worktree;
- ingerir arquivos;
- acessar arquivos do projeto;
- backups;
- diagnosticos administrativos completos;
- alterar politicas;
- exportar dados;
- escrever/curar memoria ou conhecimento.

## Uso no celular

1. Instale Tailscale no celular.
2. Entre na mesma conta/tailnet do computador.
3. Confirme que o computador esta online no Tailscale.
4. Abra a URL privada exibida por `tailscale serve`.
5. Use o login/senha configurados, sem compartilhar.
6. No navegador, use "Adicionar a tela inicial" quando disponivel.

Se nao abrir, verifique se o computador esta ligado, se a Aya esta aberta e se o Tailscale esta conectado.

## Recuperacao

Verifique Git:

```powershell
git status --porcelain
git log -1 --oneline
git worktree list
```

Para remover somente worktrees oficiais abandonados, confira primeiro `git worktree list`; remova apenas pastas sob `E:\Aya\aya_dev_workspaces` quando tiver certeza de que nao ha experimento aguardando aprovacao.

Para falha remota, desative no `.env`:

```text
AYA_REMOTE_MODE=false
```

Depois inicie localmente com:

```powershell
python app.py
```

Logs de release ficam em `logs/releases/`.

## Backup v1

Crie um backup local:

```powershell
.\scripts\backup_v1.ps1
```

O backup preserva codigo, documentacao, scripts, testes, bancos locais principais e configuracoes nao secretas. Nao inclui `.env`, senhas, tokens, modelos Ollama, worktrees temporarios, caches ou logs excessivos.

## Testes de aceitacao

Antes de declarar a v1.0 operacional, valide:

- inicializacao local;
- encerramento com `Ctrl+C`;
- reinicializacao;
- chat basico;
- memoria em canal local;
- RAG;
- estudo;
- voz local;
- interface desktop;
- interface via Tailscale no celular;
- autenticacao invalida e valida;
- bloqueio remoto do Aya Dev;
- ausencia de `share=True`;
- ausencia de Funnel;
- ausencia de porta publica;
- funcionamento local com Tailscale desligado;
- logs sem credenciais;
- prevencao de segunda instancia;
- recuperacao apos encerramento inesperado.
