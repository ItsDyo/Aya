# Aya

Aya e uma assistente local de estudos, codigo e produtividade usando Ollama, SQLite, Gradio e Rich.

## Estrutura

```text
aya/
  core/        Orquestracao da assistente, LLM, RAG e ferramentas de projeto
  data/        Banco SQLite, memoria e sessao de estudo
  utils/       Funcoes auxiliares
docs/          Planos tecnicos e fine-tuning
scripts/       Testes manuais e utilitarios
tests/         Testes automatizados
data_local/    Banco, historico e arquivos locais persistentes
exports/       Datasets exportados
logs/          Logs da Aya
backups/       Backups locais versionados
app.py         Interface Gradio
main.py        Interface de terminal
```

## Rodar

```powershell
python app.py
```

Ou pelo terminal:

```powershell
python main.py
```

Para acessar de outro dispositivo na sua rede ou por VPN privada:

```powershell
Copy-Item .env.example .env
notepad .env
.\scripts\diagnose_remote.ps1
.\scripts\start_remote.ps1
```

No modo recomendado, mantenha `AYA_HOST=127.0.0.1` e use `tailscale serve 7860` em outro terminal. Veja o guia: `docs/acesso_remoto_seguro.md`.

O acesso remoto usa permissoes reduzidas: conversa, estudo, memoria e RAG
continuam disponiveis, mas arquivos, backups, diagnosticos e exports ficam
bloqueados. Veja `docs/permissoes_por_canal.md`.

## Testar

```powershell
python -m unittest discover -v
python -m compileall -q .
python scripts/smoke_test.py
```

## Backups

Crie um backup dos dados persistentes:

```powershell
python main.py
# dentro da Aya:
/backup criar
```

Ou pela interface web, na aba `Sistema` > `Backups`.

Comandos disponiveis:

```text
/backup criar
/backup listar
/backup verificar nome_do_backup.zip
/backup extrair nome_do_backup.zip
```

Os backups ficam em `backups/` e incluem o banco SQLite, historico local, exports e logs. A extracao cria uma pasta separada e nao sobrescreve a Aya atual.

## Modelos esperados no Ollama

```powershell
ollama pull llama3.2
ollama pull gemma2:2b
```

## Configuracao

A Aya centraliza configuracoes em `aya/config.py`. Voce pode mudar alguns valores por variaveis de ambiente sem editar codigo:

```powershell
$env:AYA_MODEL_PRIMARY="llama3.2"
$env:AYA_MODEL_REVIEWER="gemma2:2b"
$env:AYA_OLLAMA_BASE_URL="http://localhost:11434/v1"
$env:AYA_AUTO_REFLECTION_INTERVAL="6"
$env:AYA_PIPER_VOICE="pt_BR-faber-medium"
$env:AYA_PIPER_MAX_CHARS="3500"
$env:AYA_REMOTE_MODE="false"
$env:AYA_HOST="127.0.0.1"
$env:AYA_PORT="7860"
$env:AYA_AUTH_ENABLED="false"
```

Os defaults continuam prontos para uso local com Ollama e Piper.

## Comandos da Aya

Voce nao precisa decorar comandos para o uso comum. A Aya entende frases naturais como:

```text
vou estudar matematica por 25 minutos
terminei de estudar, revisei fracoes
lembre que eu prefiro exemplos curtos
tenho dificuldade com classes em Python
crie uma meta semanal estudar Python
busque Python na memoria
ingira README.md
mostre fontes sobre Python
crie um exercicio sobre listas em Python
responder exercicio 1 | listas guardam valores em ordem
o que revisar
preciso conversar
estou frustrado hoje
me da um conselho
onde paramos
roadmap da Aya
conselho tecnico da Aya
release da Aya
audite o projeto
analise o projeto
leia aya/core/assistant.py
revise o arquivo aya/core/assistant.py
crie um plano para alterar aya/core/assistant.py para separar responsabilidades
me ajude com codigo: cole aqui o erro, traceback ou trecho quebrado
```

Se a mensagem for curta ou ambigua, a Aya decide sozinha:

- assunto de estudo curto vira memoria de assunto atual;
- frase com cara de definicao vira conhecimento;
- mensagem casual ou pergunta clara segue a conversa normal.

Os comandos abaixo continuam disponiveis para controle manual:

```text
/ajuda
/painel
/roadmap
/release
/release executar
/release listar
/release ultimo
/release comparar
/salvar topico | conteudo | tags
/buscar termo
/estudar materia | minutos
/encerrar notas
/meta tipo | descricao
/metas
/dificuldade materia | topico | descricao
/perfil chave | valor
/codigo descreva o problema, erro, traceback ou cole o codigo
/memoria
/rag consulta
/ragstatus
/reindexar rag
/ingerir caminho
/fontes termo
/lembrar tipo | chave | valor
/refletir
/autonomia
/backup criar
/backup listar
/backup verificar nome_do_backup.zip
/backup extrair nome_do_backup.zip
/aprendizados
/aprovar id
/rejeitar id
/curadoria
/conflitos
/resolver conflito id | aceitar ou rejeitar
/fundir memoria id_principal | id_duplicada
/historico memoria id
/confirmar memoria id
/esquecer memoria id
/exercicio topico | nivel
/responder id | sua resposta
/revisoes
/companhia mensagem opcional
/desabafo mensagem opcional
/incentivo mensagem opcional
/diario
/continuidade
/conselho
/projeto
/auditar
/arquivo aya/core/assistant.py
/revisar aya/core/assistant.py
/plano aya/core/assistant.py | objetivo da mudanca
/diagnostico
/finetune
```

## Caminho de evolucao

1. Use `/roadmap` para ver a rota da Aya 1.0 e os criterios de estabilidade.
2. Use `/painel` para ver status, pendencias, curadoria e proximos passos em uma tela.
3. Use `/conselho` para receber uma recomendacao tecnica do proximo ciclo.
4. Use `/release` para gerar um relatorio tecnico honesto de estabilidade.
5. Use `/release executar` para rodar validacoes reais e salvar um relatorio completo.
6. Use `/release listar`, `/release ultimo` e `/release comparar` para navegar no historico tecnico.
7. Use `/lembrar` para salvar fatos permanentes, objetivos e preferencias.
8. Use `/salvar` para registrar conhecimento estudado.
9. Use `/rag` para ver o contexto local que a Aya recupera antes de responder.
10. Use `/ingerir caminho` para indexar arquivos locais no RAG.
11. Use `/fontes termo` para ver de onde uma resposta pode buscar contexto.
12. Use `/codigo` para pedir ajuda de programacao com contexto local do RAG.
13. Use `/revisar arquivo.py` para pedir uma revisao guiada antes de mudar codigo.
14. Use `/plano arquivo.py | objetivo` para a Aya propor mudancas, riscos e testes sem editar nada.
15. Use `/autonomia` para ver, ligar, desligar ou forcar a manutencao autonoma.
16. Use `/aprendizados` para revisar o que a Aya capturou com menor confianca.
17. Use `/aprovar id` ou `/rejeitar id` para curar a memoria permanente.
18. Use `/curadoria` para revisar memorias fracas e aprendizados pendentes.
19. Use `/confirmar memoria id` para fortalecer uma memoria correta.
20. Use `/esquecer memoria id` para arquivar uma memoria ruim ou antiga.
21. Use `/conflitos` para revisar mudancas que a Aya se recusou a sobrescrever.
22. Use `/resolver conflito id aceitar|rejeitar` para escolher o valor canonico.
23. Use `/fundir memoria principal duplicada` para unir duplicatas identicas sem apagar historico.
24. Use `/exercicio tema | nivel` para a Aya testar se voce aprendeu.
25. Use `/responder id | resposta` para receber correcao e gerar revisao futura.
26. Use `/revisoes` para ver exercicios que precisam voltar.
27. Use `/companhia` quando quiser conversar sobre o dia, desabafar ou pedir incentivo.
28. Use `/diario` para ver registros leves das conversas de companhia.
29. Use `/continuidade` para ver onde voces pararam e quais proximos passos fazem sentido.
30. Use `/diagnostico` para checar banco, dependencias, voz, Gradio e Tailscale.
31. Use `/backup criar` para proteger memoria, conhecimento, historico, exports e logs.
32. Use `/finetune` para exportar um dataset JSONL inicial.

Detalhes do comportamento de conflitos, fusoes e envelhecimento estao em
`docs/memoria_avancada.md`.

O RAG usa ranking lexical local por padrao e aceita embeddings opcionais do
Ollama. Instalacao, seguranca e configuracao: `docs/rag_avancado.md`.

## Voz local com Piper

A Aya usa Piper TTS para fala local, gratuita e sem nuvem.

Instale as dependencias:

```bash
pip install piper-tts
```

Baixe a voz pt-BR padrao no PowerShell:

```powershell
New-Item -ItemType Directory -Force voices
Invoke-WebRequest "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx" -OutFile "voices/pt_BR-faber-medium.onnx"
Invoke-WebRequest "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json" -OutFile "voices/pt_BR-faber-medium.onnx.json"
```

Teste a voz:

```bash
python voz.py
```

Use em codigo:

```python
from voz import falar

falar("Oi, eu sou a Aya.")
```

Para transcricao local por microfone na aba Voz, instale tambem:

```bash
pip install SpeechRecognition pocketsphinx
```

## Fine-tuning futuro

Comece com LoRA/QLoRA em um modelo pequeno compativel com sua maquina. Antes de treinar, revise o dataset exportado: remova respostas ruins, duplicatas, erros factuais e dados sensiveis.

Fine-tuning deve ensinar estilo e padroes de resposta. Memoria e conhecimento factual mutavel devem continuar no SQLite/RAG.

Veja tambem: `docs/fine_tuning_plan.md`.
