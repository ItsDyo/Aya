# Memoria avancada

A memoria persistente da Aya usa um registro canonico para cada par
`(tipo, chave)` e preserva todas as mudancas em `memoria_historico`.

## Decisoes de escrita

- Fato novo: cria uma memoria ativa.
- Mesmo fato novamente: reforca a confianca e incrementa `reforco_count`.
- Valor diferente para a mesma memoria: mantem o valor atual e cria um conflito.
- `assunto_atual` e `reflexao`: podem ser atualizados porque sao estados temporarios.
- Atualizacao explicita de perfil: aplica o novo valor e registra a versao anterior.

Conflitos nunca entram no contexto do modelo antes da decisao do usuario. A
Aya continua usando somente o valor canonico.

## Curadoria

Na aba Sistema, abra `Conflitos e fusoes` para:

- listar propostas conflitantes;
- aceitar o novo valor ou manter o atual;
- fundir duas memorias com valores equivalentes;
- consultar o historico de uma memoria.

Os atalhos equivalentes sao:

```text
/conflitos
/resolver conflito 3 aceitar
/resolver conflito 3 rejeitar
/fundir memoria 2 5
/historico memoria 2
```

Uma fusao arquiva a duplicata com estado `fundida` e aponta para a memoria
principal. Nenhum registro e apagado.

## Envelhecimento seguro

A manutencao autonoma pode arquivar somente memorias dos tipos
`assunto_atual` e `reflexao` quando todas estas condicoes forem verdadeiras:

- confianca abaixo de 0.85;
- sem atualizacao ou uso recente;
- idade superior ao TTL configurado;
- nenhum conflito pendente.

O padrao e 45 dias e pode ser alterado por
`AYA_MEMORY_TEMPORARY_TTL_DAYS`. Perfil, preferencias, trabalho, estudo e
outras memorias permanentes nunca sao arquivados por essa rotina.
