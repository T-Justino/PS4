# Proposta: validação ponta a ponta antes do Gate 3 (T8)

**Status:** proposta, nada implementado nem testado. Depende de **um PKG candidato** (abaixo).

## Objetivo

Provar, em 1 caso real, a cadeia completa com identidade **compatível** entre catálogo e pacote:
`fonte importada → item encontrado → download concluído → PKG aceito → instalação concluída`.
O T7 provou que a cadeia quebra na 4ª etapa quando a chave ≠ ID interno. Falta provar que ela **fecha** quando são iguais.

## Requisitos do PKG candidato (todos obrigatórios)

1. **Distribuição legal**: licença livre, ou permissão escrita do autor, ou release oficial do autor. Evidência guardada no canônico.
2. **ID real com prefixo `CUSA`** (única família comprovada no importador). `NPXS`/`APOL` ficam fora.
3. **Content ID visível e conferido**: `XX0000-CUSAnnnnn_00-…` com o mesmo `CUSAnnnnn` usado como `titleId`. O `build` já exige isso quando `contentId` é declarado.
4. **Download direto por HTTPS que o SSPI consiga abrir** (o GitHub Releases falhou por TLS; `pkg-zone.com` funcionou).
5. **Não instalado hoje no console**: assim "já instalado" não confunde o resultado (o T7 tinha essa ambiguidade).
6. **Tamanho pequeno** (idealmente < 100 MB) e **sem exigir remover nada**.

**Candidato:** não tenho um identificado e não vou inventar. Preciso de você: nome, URL, licença/permissão e o ID mostrado no SSPI.
Como a maioria dos homebrews usa IDs não-`CUSA` (`NPXS`, `APOL`, `ITEM`…), **pode não existir candidato** que cumpra o item 2.

## Caminhos, em ordem de preferência

| | Caminho | Prós | Contras |
|---|---|---|---|
| A | PKG existente de terceiros com `CUSA` real e licença/permissão | Nada fabricado; prova o caso real | Candidato difícil de achar; permissão pode demorar |
| B | **Software próprio seu** (você é o autor) compilado com um ID `CUSA`-formatado definido por você, hospedado em URL sua | Identidade compatível por construção; licença é sua | Cria um ID novo, com risco de colidir com título real; precisa de toolchain no PC; instalação na 9.00 não garantida. **Exige sua decisão explícita**, pois mexe em identificador (de um pacote novo, não de um existente) |
| C | Jogo comercial com `CUSA` real | Muitos IDs | Sem link autorizado: **fora de questão** |

Recomendação: A; se em ~1 semana não houver candidato, decidir B.

## Procedimento T8 (quando houver candidato)

1. **Eu**: gero `ps4storebr-t8-<cusa>.gssource` com `titleId` = ID real, `contentId` declarado, evidência de autorização; `check` + testes;
   relatório com a conferência. Sem chave sintética.
2. **Você, no PS4** (mesma ficha de 6 etapas do T7), sem remover nada:

```text
T8
1 fonte importada:       [sim / não + erro]
2 achado na pesquisa:    [sim / não]
3 download concluído:    [sim / não + __%]
4 PKG aceito/recusado:   [aceito / recusado + mensagem EXATA]
5 instalação concluída:  [sim, abre / não + mensagem]
6 botão após instalar:   [Open / Install]
```

3. **Aceite do Gate 3** (todos): etapas 1–5 = sim, e o botão da etapa 6 anotado.
   Se a 4ª falhar com `expected … got …`, o `contentId` ou o ID está errado: o item é removido do catálogo, sem exceção.

## O que o Gate 3 herda desta decisão

- Verificação **antes de publicar**: ler o content ID no cabeçalho do PKG (requisição `Range` dos primeiros bytes) e comparar com o `titleId`. Não baixar o arquivo inteiro.
- Item cujo ID não bate, ou cujo prefixo o parser recusa, **não entra** no `.gssource`.
- Atualizações e DLC continuam sem promessa até teste próprio.
