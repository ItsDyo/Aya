# Comandos da Aya

Os comandos sao atalhos. Para uso comum, voce tambem pode falar de forma natural.

## Conversa

| Comando | Uso |
| --- | --- |
| texto sem barra | Conversa normal com a Aya |
| `/companhia mensagem` | Conversa mais pessoal, para desabafo leve ou conselho |
| `/diario` | Mostra registros leves do modo companhia |
| `/continuidade` | Mostra contexto recente e proximos passos |

## Estudo

| Comando | Uso |
| --- | --- |
| `/estudar materia | minutos` | Inicia uma sessao de estudo |
| `/encerrar notas` | Encerra a sessao atual |
| `/meta descricao | categoria` | Cria uma meta |
| `/metas` | Lista metas ativas |
| `/dificuldade texto` | Registra dificuldade |
| `/exercicio topico | nivel` | Gera exercicio de estudo |
| `/responder id | resposta` | Corrige uma resposta |
| `/revisoes` | Lista revisoes pendentes |

## Conhecimento e RAG

| Comando | Uso |
| --- | --- |
| `/salvar topico | conteudo | tags` | Salva conhecimento local |
| `/buscar termo` | Busca no conhecimento local |
| `/ingerir caminho` | Ingere arquivo ou pasta no conhecimento |
| `/fontes` | Lista fontes ingeridas |
| `/rag termo` | Busca contexto local |
| `/ragstatus` | Mostra estado do RAG |
| `/reindexar` | Reindexa conhecimento local |

## Memoria

| Comando | Uso |
| --- | --- |
| `/memoria` | Mostra contexto de memoria atual |
| `/memorias dominio|fracas` | Lista memorias por visao de revisao |
| `/lembrar chave | valor | dominio` | Salva memoria persistente |
| `/confirmar memoria id` | Confirma uma memoria |
| `/esquecer memoria id` | Arquiva uma memoria |
| `/arquivar memoria id` | Arquiva memoria sem apagar historico |
| `/restaurar memoria id` | Restaura memoria arquivada |
| `/editar memoria id | novo valor` | Edita memoria existente |
| `/dominio memoria id | dominio` | Ajusta dominio da memoria |
| `/adiar memoria id` | Adia revisao com prazo padrao |
| `/adiar memoria id | 7 dias` | Adia revisao por prazo explicito |
| `/ignorar memoria id` | Ignora a mesma razao de curadoria |
| `/retomar memoria id` | Remove adiamento ou ignore |
| `/revisar memoria id` | Reabre revisao de memoria |
| `/curadoria` | Mostra itens pendentes |
| `/higiene` | Mostra resumo de higiene da memoria |
| `/conflitos` | Lista conflitos de memoria |
| `/resolver conflito id aceitar|rejeitar` | Resolve conflito |
| `/fundir memoria principal duplicada` | Une duplicatas preservando historico |

## Alertas

| Comando | Uso |
| --- | --- |
| `/alertas` | Mostra alertas resumidos |
| `/alertas detalhes` | Mostra alertas com IDs e dados seguros |
| `/alertas revisao` | Filtra revisoes |
| `/alertas memoria` | Filtra conflitos de memoria |
| `/alertas curadoria` | Filtra curadoria |
| `/alertas meta` | Filtra metas |
| `/alertas aya-dev` | Filtra propostas do Aya Dev |
| `/alertas critico` | Filtra problemas criticos |
| `/alertas detalhes revisao` | Mostra detalhes de uma categoria |

## Projeto e codigo

| Comando | Uso |
| --- | --- |
| `/codigo pedido ou erro` | Ajuda com codigo |
| `/auditar` | Audita o projeto |
| `/arquivo caminho_relativo` | Le arquivo seguro do projeto |
| `/revisar caminho_relativo` | Revisa arquivo |
| `/plano caminho_relativo | objetivo` | Gera plano de alteracao |

## Sistema

| Comando | Uso |
| --- | --- |
| `/ajuda` | Mostra ajuda geral |
| `/status` | Mostra estado resumido |
| `/diagnostico` | Roda diagnostico |
| `/modelos` | Mostra modelos configurados |
| `/roadmap` | Mostra plano do projeto |
| `/release` | Mostra validacao de release |
| `/conselho` | Recomenda proximo ciclo tecnico |
| `/backup criar` | Cria backup |
| `/backup listar` | Lista backups |
| `/backup verificar nome.zip` | Verifica backup |
| `/backup extrair nome.zip` | Extrai backup sem sobrescrever a Aya atual |
| `/finetune` | Exporta dataset inicial |

## Aya Dev

Use `/aya-dev status` para ver os comandos disponiveis no estado atual. O Aya Dev deve continuar supervisionado: nao aprove, integre ou reverta mudancas sem revisar evidencias.
