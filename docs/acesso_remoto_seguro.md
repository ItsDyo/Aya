# Acesso remoto seguro da Aya

Este guia prepara a Aya para uso no celular ou em outro computador sem expor seu projeto inteiro na internet publica.

## Regra principal

Nao abra porta do roteador para a internet publica. A Aya guarda memorias, historico e dados pessoais; o caminho mais seguro e usar uma VPN privada como Tailscale, ZeroTier ou WireGuard.

## Modo local

Use quando estiver no proprio computador:

```powershell
.\iniciar_app.bat
```

Endereco:

```text"
http://127.0.0.1:7860
```

## Modo remoto com Tailscale Serve

Use quando quiser acessar de outro dispositivo pela sua tailnet privada:

```powershell
Copy-Item .env.example .env
notepad .env
.\scripts\diagnose_remote.ps1
.\scripts\start_remote.ps1
```

No `.env`, configure:

```env
AYA_REMOTE_MODE=true
AYA_HOST=127.0.0.1
AYA_PORT=7860
AYA_AUTH_ENABLED=true
AYA_AUTH_USERNAME=seu_usuario
AYA_AUTH_PASSWORD=sua_senha_forte
```

Em outro terminal, publique a Aya apenas na tailnet:

```powershell""
tailscale serve 7860
```

O Tailscale Serve faz o proxy privado para o Gradio local em `127.0.0.1:7860`.

## Variaveis de ambiente

Voce tambem pode iniciar manualmente:

```powershell
$env:AYA_REMOTE_MODE="true"
$env:AYA_HOST="127.0.0.1"
$env:AYA_PORT="7860"
$env:AYA_AUTH_ENABLED="true"
$env:AYA_AUTH_USERNAME="seu_usuario"
$env:AYA_AUTH_PASSWORD="sua_senha_forte"
python app.py
```

Para voltar ao modo local:

```powershell
$env:AYA_REMOTE_MODE="false"
$env:AYA_HOST="127.0.0.1"
python app.py
```

## Protecoes implementadas

- O modo local continua sendo o padrao.
- Se a Aya for configurada para modo remoto sem usuario e senha, o app nao inicia.
- O `share=True` do Gradio fica desligado por padrao.
- `share=True` e bloqueado.
- O Gradio fica em `127.0.0.1` no modo remoto; o Tailscale Serve faz o acesso privado.
- Leitura de `.env`, bancos, logs, backups e caminhos fora da raiz fica bloqueada pelo chat.

## Melhor caminho para fora de casa

1. Instale o Tailscale no PC da Aya e no celular.
2. Entre na mesma tailnet nos dois dispositivos.
3. Configure `.env` com `AYA_REMOTE_MODE=true` e autenticacao.
4. Rode `.\scripts\diagnose_remote.ps1`.
5. Rode `.\scripts\start_remote.ps1`.
6. Em outro terminal, rode `tailscale serve 7860`.
7. Acesse pelo endereco mostrado pelo Tailscale Serve.

Esse caminho e melhor que abrir porta no roteador porque reduz muito a chance de alguem encontrar sua Aya pela internet.

Referencias oficiais usadas:

- https://tailscale.com/docs/features/tailscale-serve
- https://tailscale.com/docs/reference/tailscale-cli/serve
