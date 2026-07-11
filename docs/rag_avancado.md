# RAG avancado

O RAG da Aya combina busca lexical SQLite FTS5, memoria persistente e, quando
ativado, embeddings locais do Ollama. Nenhuma API paga ou servico em nuvem e
necessario.

## Comportamento padrao

Embeddings ficam desligados por padrao. Mesmo assim, a busca local oferece:

- ranking por titulo, conteudo, tags e caminho da fonte;
- normalizacao de acentos, singular e plural em portugues;
- limite de dois trechos por arquivo para aumentar diversidade;
- remocao de trechos quase duplicados;
- limite total de caracteres enviados ao modelo;
- citacoes estaveis no formato `K:id` para conhecimento e `M:id` para memoria;
- descarte de memorias sem relacao lexical com a pergunta;
- troca atomica de trechos durante reingestao.

Trechos de documentos sao delimitados como dados nao confiaveis. Instrucoes
encontradas dentro de um arquivo nao devem ser obedecidas pelo modelo.

## Ativar busca semantica local

No PowerShell, baixe o modelo recomendado:

```powershell
ollama pull embeddinggemma
```

No arquivo `.env` real, altere somente:

```text
AYA_EMBEDDING_ENABLED=true
AYA_EMBEDDING_MODEL=embeddinggemma
```

Reinicie a Aya e gere o cache pelo Gradio local, em
`Conhecimento > Ingestao de arquivos > Reindexar`, ou use:

```text
/reindexar rag
```

O cache fica na tabela SQLite `conhecimento_embeddings`. Um documento so e
processado novamente quando seu conteudo muda. Se o Ollama ou o modelo falhar,
a busca vetorial e desativada naquela execucao e o ranking lexical continua
funcionando.

Documentacao oficial usada pela implementacao:

- https://docs.ollama.com/capabilities/embeddings
- https://docs.ollama.com/api/openai-compatibility

## Inspecao

Use `/ragstatus` para ver o modo atual e `/fontes consulta` para inspecionar
score, origem e motivo do ranking antes de confiar em uma resposta.

## Limite atual

A similaridade vetorial e calculada em Python sobre no maximo 5.000 vetores.
Isso e adequado para um banco pessoal. Se o projeto crescer para dezenas de
milhares de trechos, o proximo passo sera adotar um indice vetorial dedicado.
