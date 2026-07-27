# Instalacao limpa da Aya v1

Este guia mostra como reconstruir a Aya em outro computador usando apenas o
repositorio GitHub e arquivos externos gratuitos. Ele nao inclui memorias,
conversas, bancos locais, logs, backups, senhas ou modelos privados.

## Requisitos

- Windows com PowerShell.
- Git.
- Python 3.13 ou superior.
- Ollama instalado.
- Tailscale instalado apenas se quiser usar a Aya pelo celular.

## 1. Baixar o projeto

```powershell
git clone https://github.com/ItsDyo/Aya.git
cd Aya
```

Se voce estiver usando outra pasta, execute os comandos sempre dentro da raiz do
projeto.

## 2. Criar o ambiente Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Configurar o ambiente local

Crie o arquivo `.env` a partir do exemplo:

```powershell
Copy-Item .env.example .env
```

Edite o `.env` somente no seu computador. Nao envie esse arquivo para o GitHub.
Para comecar localmente, mantenha:

```text
AYA_REMOTE_MODE=false
AYA_HOST=127.0.0.1
AYA_PORT=7860
AYA_GRADIO_SHARE=false
```

Se for usar acesso remoto privado com Tailscale, configure usuario e senha no
`.env` local antes de iniciar em modo remoto.

## 4. Baixar modelos do Ollama

Abra o Ollama e execute:

```powershell
ollama pull llama3.2
ollama pull gemma2:2b
ollama pull embeddinggemma
ollama list
```

Modelos usados:

- `llama3.2`: modelo principal.
- `gemma2:2b`: modelo revisor/auxiliar.
- `embeddinggemma`: embeddings locais para busca semantica, quando ativado.

## 5. Baixar a voz Piper

A voz nao deve ir para o GitHub porque e um arquivo grande. Para baixar no
computador novo:

```powershell
.\scripts\download_voice.ps1
```

Arquivos esperados em `voices/`:

- `pt_BR-faber-medium.onnx`
- `pt_BR-faber-medium.onnx.json`

## 6. Verificar a instalacao

```powershell
.\scripts\check_install.ps1
```

Esse script apenas consulta o ambiente. Ele nao inicia a Aya, nao encerra
processos, nao altera configuracoes e nao mostra conteudo do `.env`.

## 7. Iniciar e abrir

Para iniciar:

```powershell
.\scripts\start_v1.ps1
```

Para abrir no navegador, em outro terminal:

```powershell
.\scripts\open_v1.ps1
```

Tambem existem atalhos em `atalhos/`:

- `Iniciar Aya.cmd`
- `Abrir Aya.cmd`
- `Status Aya.cmd`

## 8. Uso no celular com Tailscale

Use somente Tailscale Serve privado. Nao use Funnel, nao abra porta no roteador
e nao use `share=True` do Gradio.

Com a Aya ligada, publique a porta local na sua tailnet:

```powershell
tailscale serve 7860
```

Depois acesse a URL privada `.ts.net` pelo celular conectado ao mesmo Tailscale.

## 9. Validacoes de desenvolvimento

Para validar o projeto apos instalar:

```powershell
python -m pytest
python -m ruff check .
python -m compileall .
python -m pip check
python scripts\smoke_test.py
```

## 10. O que fica fora do GitHub

Estes itens devem ser recriados, baixados ou restaurados localmente:

- `.env`
- bancos SQLite e memorias reais
- conversas pessoais
- logs
- backups
- arquivos de voz `.onnx`
- modelos locais grandes

Isso protege privacidade e evita que arquivos grandes sejam enviados ao GitHub.
