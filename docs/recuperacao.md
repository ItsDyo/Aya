# Recuperacao da Aya

Este guia e para quando voce precisar mover a Aya para outro computador ou
recuperar o projeto depois de algum problema.

## Recuperar codigo

```powershell
git clone https://github.com/ItsDyo/Aya.git
cd Aya
```

Depois siga:

```text
docs/instalacao_limpa.md
```

## Recuperar ambiente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite o `.env` com seus valores locais.

## Recuperar modelos e voz

```powershell
ollama pull llama3.2
ollama pull gemma2:2b
ollama pull embeddinggemma
.\scripts\download_voice.ps1
```

## Verificar antes de usar

```powershell
.\scripts\check_install.ps1
```

## Recuperar dados pessoais

Dados pessoais nao estao no GitHub. Eles devem vir de backup local.

Itens comuns:

- `data_local/`;
- bancos SQLite;
- historico;
- exports;
- backups.

Use os comandos oficiais de backup quando possivel:

```text
/backup listar
/backup verificar nome_do_backup.zip
/backup extrair nome_do_backup.zip
```

A extracao deve criar uma pasta separada e nao sobrescrever a Aya atual.

## Se algo quebrar

1. Rode `.\scripts\check_install.ps1`.
2. Rode `.\scripts\status_v1.ps1`.
3. Confirme que o Ollama esta aberto.
4. Confirme que os modelos estao em `ollama list`.
5. Confirme que a voz esta em `voices/`.
6. Confirme que `.env` existe.
7. Leia o erro antes de apagar qualquer coisa.

Nao use `git reset --hard`, `git clean`, `taskkill /F` generico ou limpeza de
pastas sem backup.
