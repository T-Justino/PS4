# Auditoria de CUSAs e painel (Etapa 5F)

## Auditoria dos conflitos (`python -m ps4store.auditoria`)
Lê **só os dados já importados** (`local/cusas-wikidata.json`, o índice e os registros curados). **Sem rede, sem baixar de novo os 6.250 jogos.** Não apaga, troca nem associa nada: grava apenas o relatório `local/auditoria-cusas.json`, com o hash (sha256) de cada arquivo de entrada.

Para cada conflito mostra: o **CUSA**, os **Q-ids e nomes** dos jogos, o **ano** (do índice), os **Content IDs** que existirem (do valor do Wikidata ou do registro curado), e as **propriedades Wikidata** (com rótulo, valor bruto e data da consulta) que originaram a associação.

Classes (todas continuam **pendentes de revisão**; nada é resolvido automaticamente):
| Classe | Evidência usada |
|---|---|
| **Possível produto relacionado** | (forte) Content IDs **diferentes** com o mesmo CUSA nos jogos em conflito: um título pode cobrir mais de um produto; ou (fraca, só pelos nomes) um nome é o outro mais um marcador de edição/pacote (edition, bundle, season pass…) |
| **Associação contraditória** | o registro curado (fonte oficial citada) pertence a outro jogo e os nomes não têm relação; ou os nomes dos jogos não têm nenhuma palavra significativa em comum |
| **Indeterminado** | o resto: mesma série (jogos diferentes), mesmo nome (possível item duplicado), mesmo Content ID em dois Q-ids, nomes parcialmente parecidos |

**Tipo do produto (jogo-base, edição, DLC) fica "desconhecido".** Só aparecem *indícios* marcados "NÃO confirmado" (ex.: sufixo `DLC…` no Content ID). A classificação por nome é fraca e está rotulada como tal.

### Comandos (Termux)
```sh
cd ~/PS4 && git pull
PYTHONPATH=src python -m ps4store.auditoria                       # resumo + relatório JSON
PYTHONPATH=src python -m ps4store.auditoria --classe relacionado   # só uma classe (relacionado | contraditoria | indeterminado)
PYTHONPATH=src python -m ps4store.auditoria --cusa CUSA00053       # um conflito
PYTHONPATH=src python -m ps4store.auditoria --todos                # sem o limite de 6 por classe
```

## Painel
- **Cabeçalho com contadores separados:** Jogos pesquisáveis · Jogos com CUSA · CUSAs distintos · Registros manuais · Conflitos pendentes (números formatados em pt-BR).
- **Conflitos na página do jogo:** um aviso curto ("N CUSA(s) em conflito no Wikidata, NÃO associados a este jogo: A, B, C, D (+n)") e uma lista **recolhível** com uma linha por CUSA (motivo curto, outros jogos, classificação da auditoria ou "não auditado"). Sem mensagens repetidas e sem afirmar edição/DLC/jogo-base.
- O painel lê o relatório automaticamente (`--auditoria`, padrão `local/auditoria-cusas.json`); sem relatório, os conflitos aparecem como "não auditado". Filtros, pesquisa unificada e cobertura inalterados.
```sh
PYTHONPATH=src python -m ps4store.painel     # http://127.0.0.1:8765
```
