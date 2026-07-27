# Seguranca da Aya

A Aya e uma assistente local com memoria, conversas e dados pessoais. A regra
principal e simples: codigo pode ir para o GitHub privado; dados reais ficam no
seu computador.

## Nunca envie

- `.env`;
- bancos `.db`, `.sqlite` ou `.sqlite3`;
- memorias reais;
- conversas pessoais;
- logs;
- backups;
- senhas;
- tokens;
- chaves `.key`, `.pem` ou `.token`;
- modelos grandes;
- arquivos de voz `.onnx`.

## Acesso remoto

Use Tailscale Serve privado.

Nao use:

- porta aberta no roteador;
- Tailscale Funnel;
- `share=True` do Gradio;
- repositorio publico para dados pessoais.

## Antes de commitar

Execute:

```powershell
git status --short
git status --ignored --short
git ls-files | Select-String -Pattern '\.env$|\.db$|\.sqlite|\.pem$|\.key$|\.token$|data_local|\.onnx$'
```

Se algum arquivo privado ja estiver rastreado, nao apague do computador. Remova
apenas do rastreamento:

```powershell
git rm --cached caminho\do\arquivo
```

Depois confirme que o `.gitignore` esta protegendo o arquivo.

## Antes de publicar no GitHub

Confira:

```powershell
git remote -v
git status
git log -1 --oneline
```

Nao cole senha ou token em terminal, arquivo `.env`, README ou issue.

## Sinais de risco

Pare e revise se aparecer:

- arquivo `.env` em `git status`;
- banco de dados em `git status`;
- logs rastreados;
- backup rastreado;
- URL publica do Gradio;
- credencial em diff;
- arquivo grande de modelo ou voz entrando no Git.

## Boa pratica

Mantenha o GitHub como a copia do projeto, nao como a copia da sua vida privada.
Para recuperar dados reais, use backups locais controlados.
