# Backup da Aya

Backups protegem memoria, conhecimento, historico local, exports e logs. Eles nao substituem Git: Git guarda o codigo; backup guarda os dados locais.

## Criar backup

Dentro da Aya:

```text
/backup criar
```

Pelo PowerShell:

```powershell
cd "E:\Aya\Teste de IA Principal"
.\scripts\backup_v1.ps1
```

Os backups ficam em `backups/`.

## Listar backups

```text
/backup listar
```

## Verificar backup

```text
/backup verificar nome_do_backup.zip
```

Esse comando ajuda a confirmar se o arquivo parece valido antes de guardar ou extrair.

## Extrair backup

```text
/backup extrair nome_do_backup.zip
```

A extracao cria uma pasta separada. Ela nao deve sobrescrever a Aya atual automaticamente.

## O que normalmente entra

- banco SQLite local;
- historico local;
- exports;
- logs;
- dados necessarios para recuperar o estado pessoal da Aya.

## O que nao deve ir para GitHub

- backups `.zip`;
- bancos `.db`, `.sqlite` e `.sqlite3`;
- `.env`;
- logs privados;
- memorias e conversas reais;
- arquivos pessoais ingeridos no RAG.

## Rotina recomendada

1. Antes de grandes mudancas, rode `/backup criar`.
2. Depois de ciclos importantes, confira `/backup listar`.
3. Antes de formatar disco ou mudar de computador, copie `backups/` para um local seguro.
4. Nunca publique backups em repositorio, chat publico ou anexo sem revisar.

## Recuperacao

Para recuperacao completa, use tambem `docs/recuperacao.md`. Em caso de duvida, preserve todos os arquivos antes de tentar corrigir.
