# Configuracao da Aya

A configuracao local da Aya fica no arquivo `.env`. Esse arquivo nao deve ser
enviado ao GitHub.

## Criar o arquivo local

```powershell
Copy-Item .env.example .env
notepad .env
```

Nunca copie valores reais para `.env.example`.

## Configuracao local recomendada

Use esta configuracao para rodar somente no proprio computador:

```text
AYA_REMOTE_MODE=false
AYA_HOST=127.0.0.1
AYA_PORT=7860
AYA_AUTH_ENABLED=false
AYA_GRADIO_SHARE=false
```

## Configuracao remota privada

Use somente com Tailscale Serve:

```text
AYA_REMOTE_MODE=true
AYA_HOST=127.0.0.1
AYA_PORT=7860
AYA_AUTH_ENABLED=true
AYA_AUTH_USERNAME=
AYA_AUTH_PASSWORD=
AYA_GRADIO_SHARE=false
```

Preencha `AYA_AUTH_USERNAME` e `AYA_AUTH_PASSWORD` apenas no `.env` local.

## Modelos

```text
AYA_MODEL_PRIMARY=llama3.2
AYA_MODEL_REVIEWER=gemma2:2b
AYA_OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
AYA_OLLAMA_API_KEY=ollama
```

`AYA_OLLAMA_API_KEY=ollama` e apenas o valor local usado pelo cliente
compativel com OpenAI do Ollama. Nao e uma chave real de nuvem.

## Memoria e RAG

```text
AYA_MEMORY_TEMPORARY_TTL_DAYS=45
AYA_EMBEDDING_ENABLED=false
AYA_EMBEDDING_MODEL=embeddinggemma
AYA_EMBEDDING_TIMEOUT_SECONDS=90
AYA_EMBEDDING_SCAN_LIMIT=5000
AYA_RAG_CONTEXT_MAX_CHARS=6500
```

Se `AYA_EMBEDDING_ENABLED=true`, confirme antes:

```powershell
ollama pull embeddinggemma
```

## Voz

```text
AYA_PIPER_VOICE=pt_BR-faber-medium
AYA_PIPER_MAX_CHARS=3500
```

Baixe a voz:

```powershell
.\scripts\download_voice.ps1
```

## Verificacao

Depois de configurar:

```powershell
.\scripts\check_install.ps1
```

O script nao mostra valores do `.env`.
