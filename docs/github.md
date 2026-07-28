# GitHub da Aya

O repositorio GitHub deve permitir reconstruir e continuar desenvolvendo a Aya sem publicar dados pessoais.

## Pode ir para o GitHub

- `aya/`
- `tests/`
- `scripts/`
- `docs/`
- `atalhos/`
- `README.md`
- `requirements.txt`
- `pytest.ini`
- `.env.example`
- arquivos de configuracao sem segredo.

## Nao deve ir para o GitHub

- `.env` e `.env.*`, exceto `.env.example`;
- senhas, tokens, chaves e credenciais;
- bancos `.db`, `.sqlite`, `.sqlite3`;
- `data_local/`;
- logs;
- backups;
- modelos locais grandes;
- vozes `.onnx`;
- caches e arquivos temporarios;
- worktrees do Aya Dev;
- conversas, memorias e documentos pessoais.

## Conferir antes de commit

```powershell
git status --short
git diff --check
git diff --cached --name-only
```

Se ainda nao adicionou arquivos, confira o que esta fora do Git:

```powershell
git status --ignored --short
```

Para checar se um arquivo esta protegido pelo `.gitignore`:

```powershell
git check-ignore -v .env
git check-ignore -v data_local
```

## Se um arquivo privado aparecer staged

Nao apague o arquivo do computador. Remova apenas do stage:

```powershell
git restore --staged caminho\do\arquivo
```

Se ele ja estiver rastreado pelo Git e precisar sair do rastreamento:

```powershell
git rm --cached caminho\do\arquivo
```

Depois revise o `.gitignore` antes de commitar.

## Antes de push

1. Confirme que o repositorio e privado.
2. Rode `git status`.
3. Revise arquivos staged.
4. Confirme que `.env`, bancos, backups, logs e modelos locais nao aparecem.
5. So entao use `git push origin main`.

## Regra simples

Codigo e documentacao entram no Git. Dados pessoais, credenciais, bancos, logs, backups e modelos grandes ficam somente locais.
