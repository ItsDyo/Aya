# Guia rapido da Aya

Este guia e para o uso diario da Aya v1.0 no computador e no celular.

## Iniciar

Pelo atalho:

1. Abra `atalhos/Iniciar Aya.cmd`.
2. Aguarde a janela informar que a Aya iniciou em `http://127.0.0.1:7860`.
3. Abra `atalhos/Abrir Aya.cmd`.

Pelo PowerShell:

```powershell
cd "E:\Aya\Teste de IA Principal"
.\scripts\start_v1.ps1
```

O Ollama precisa estar instalado e disponivel para a Aya responder com os modelos locais.

## Usar no celular

O caminho recomendado fora de casa e Tailscale privado.

1. Deixe o Tailscale ligado no computador.
2. Deixe o Tailscale ligado no celular, na mesma conta.
3. Inicie a Aya no computador.
4. Acesse a URL privada mostrada pelo Tailscale Serve.

Nao use `share=True`, nao use Tailscale Funnel e nao abra porta no roteador.

## Ver status

Pelo atalho:

```text
atalhos/Status Aya.cmd
```

Pelo PowerShell:

```powershell
.\scripts\status_v1.ps1
```

Esse script apenas consulta o estado da Aya. Ele nao inicia, encerra ou muda configuracoes.

## Abrir a interface

Pelo atalho:

```text
atalhos/Abrir Aya.cmd
```

Pelo PowerShell:

```powershell
.\scripts\open_v1.ps1
```

Se a porta `7860` nao estiver ativa, o script avisa que a Aya ainda nao parece ligada.

## Encerrar com seguranca

1. Feche a aba do navegador.
2. Volte para a janela onde a Aya esta rodando.
3. Pressione `Ctrl+C`.
4. Aguarde o terminal voltar ao prompt.

Nao encerre todos os processos Python do Windows. Isso pode fechar outras ferramentas.

## Comandos mais usados

```text
/alertas
/alertas detalhes
/alertas revisao
/status
/diagnostico
/continuidade
/estudar materia | minutos
/encerrar notas
/exercicio topico | nivel
/revisoes
/salvar topico | conteudo | tags
/buscar termo
/curadoria
/backup criar
```

## Quando algo der errado

1. Rode `atalhos/Status Aya.cmd`.
2. Teste `python scripts\smoke_test.py`.
3. Consulte `docs/troubleshooting.md`.
4. Se envolver dados importantes, crie um backup antes de tentar corrigir.
