# Troubleshooting da Aya

Use este guia quando a Aya nao iniciar, nao abrir no navegador ou nao responder como esperado.

## Aya nao abre no navegador

Verifique se a porta `7860` esta em uso:

```powershell
netstat -ano | findstr 7860
```

Se a Aya estiver rodando, abra:

```text
http://127.0.0.1:7860
```

Tambem pode usar:

```powershell
.\scripts\open_v1.ps1
```

## Aya nao parece ligada

Rode:

```powershell
.\scripts\status_v1.ps1
```

Se a porta `7860` nao estiver ativa, inicie:

```powershell
.\scripts\start_v1.ps1
```

## Ollama fora do ar

Verifique:

```powershell
ollama list
```

Se o Ollama nao responder, abra o Ollama ou rode:

```powershell
ollama serve
```

Depois tente iniciar a Aya novamente.

## Modelo ausente

Veja os modelos esperados em `docs/modelos_usados.md`.

Comandos uteis:

```powershell
ollama list
ollama pull llama3.2
ollama pull gemma2:2b
```

## Tailscale nao funciona no celular

Confira:

1. Tailscale ligado no computador.
2. Tailscale ligado no celular.
3. Ambos na mesma conta.
4. Aya rodando no computador.
5. Tailscale Serve ativo para a porta `7860`.

Use:

```powershell
.\scripts\diagnose_remote.ps1
```

Nao use Tailscale Funnel e nao abra porta no roteador.

## Dependencias quebradas

Ative o ambiente virtual e reinstale:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
```

Se nao houver `.venv`, consulte `docs/instalacao_limpa.md`.

## Testes falhando

Comece pequeno:

```powershell
python scripts\smoke_test.py
python -m ruff check .
python -m pytest -q
```

Se uma falha apareceu depois de uma mudanca especifica, revise primeiro os arquivos alterados:

```powershell
git status --short
git diff
```

## Voz Piper nao fala

Veja a documentacao de voz no README e `docs/modelos_usados.md`.

Verifique:

- modelo `.onnx` baixado em `voices/`;
- arquivo `.onnx.json` correspondente;
- dispositivo de audio do Windows funcionando;
- volume do sistema.

## Banco ou memoria com comportamento estranho

1. Pare a Aya com `Ctrl+C`.
2. Crie uma copia dos arquivos locais antes de mexer.
3. Verifique backups com `/backup listar`.
4. Consulte `docs/backup.md` e `docs/recuperacao.md`.

Nao exclua bancos, memorias ou backups para "testar". Primeiro preserve os arquivos.

## Aya Dev em estado estranho

Confira:

```powershell
git status --short
git worktree list
```

Depois use os comandos oficiais:

```text
/aya-dev status
/aya-dev propostas
```

Nao use `reset`, `rebase`, `force push` ou remocao manual de historico para corrigir Aya Dev sem revisar o estado.
