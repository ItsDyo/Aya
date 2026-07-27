# Modelos usados pela Aya

Este arquivo documenta os modelos esperados para reconstruir a Aya em outro
computador. Os modelos nao ficam no GitHub.

## Ollama

Instale o Ollama e baixe:

```powershell
ollama pull llama3.2
ollama pull gemma2:2b
ollama pull embeddinggemma
ollama list
```

## Funcao de cada modelo

- `llama3.2`: modelo principal da Aya.
- `gemma2:2b`: modelo auxiliar/revisor usado em fluxos tecnicos.
- `embeddinggemma`: modelo opcional para embeddings locais e RAG semantico.

## Variaveis relacionadas

```text
AYA_MODEL_PRIMARY=llama3.2
AYA_MODEL_REVIEWER=gemma2:2b
AYA_EMBEDDING_ENABLED=false
AYA_EMBEDDING_MODEL=embeddinggemma
```

Ative embeddings somente quando o modelo `embeddinggemma` estiver instalado:

```text
AYA_EMBEDDING_ENABLED=true
```

## Voz Piper

A voz esperada e:

```text
pt_BR-faber-medium
```

Arquivos esperados:

```text
voices/pt_BR-faber-medium.onnx
voices/pt_BR-faber-medium.onnx.json
```

Baixe automaticamente:

```powershell
.\scripts\download_voice.ps1
```

URLs publicas usadas pelo script:

```text
https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json
```

## O que nao deve ir para o GitHub

- arquivos `.onnx`;
- modelos `.gguf`;
- modelos `.safetensors`;
- bancos locais;
- memorias reais;
- logs e backups.

Use o GitHub para guardar codigo, testes, scripts e documentacao. Use scripts e
guias para reconstruir arquivos externos.
