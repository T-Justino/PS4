# Enriquecimento de CUSAs via Wikidata (Etapa 5E)

Módulo `src/ps4store/cusas.py` (importador incremental) + `src/ps4store/unificada.py` (visão unificada e pesquisa por nome/CUSA/Content ID), usados pelo painel web e pelo fluxo interativo. Só metadados; nada de PlayStation Store, downloads ou PKGs; nenhum módulo proibido alterado.

## O que NÃO foi possível verificar daqui (leia antes de rodar)
- **Cobertura real: desconhecida.** O Wikidata não é alcançável do ambiente de desenvolvimento; **nenhuma consulta real foi feita**. A quantidade de jogos com CUSA e os que ficam sem CUSA só aparecem quando você rodar os comandos abaixo no Termux. Todos os testes usam respostas **simuladas** (Q-ids `99080…`/`99090…` e CUSA `900xx` inventados, exceto os da semente de Batman: Arkham Knight da 5B).
- **Propriedades:** a busca pública só confirmou **P5971 = "Europe PlayStation Store ID"**. **Não consegui confirmar o que P5944 e P5999 são.** Por isso o importador **não presume o significado**: pergunta o rótulo ao serviço na hora e mostra no relatório, e só aceita valores que sejam **exatamente** um CUSA (`CUSA` + 5 dígitos) ou um **Content ID completo** (que embute o CUSA). Se os valores reais forem de outro formato (por exemplo IDs numéricos de loja), a cobertura será baixa e o relatório mostrará os formatos rejeitados.
- **"GTA V"**: o índice só tem os rótulos en/pt do Wikidata, não apelidos. Buscar `gta v` não acha "Grand Theft Auto V" (use o nome completo); suporte a apelidos (altLabel) exigiria reimportar o índice e não foi feito.

## Regras
- **Só Q-ids do índice local.** A importação lê as afirmações do Wikidata sobre os jogos de PS4 e descarta o que não é do índice (contado).
- **Só CUSA válido:** `CUSA\d{5}` exato ou Content ID completo. **PPSA (PS5), NPXS e qualquer outro formato são rejeitados e contados por motivo** (`ppsa-ps5`, `npxs`, `formato-desconhecido`, `formato-com-cusa-nao-reconhecido`); nada é corrigido, normalizado ou deduzido (`cusa00133` minúsculo é rejeitado).
- **Evidência de cada registro:** fonte "Wikidata", **propriedade**, rótulo da propriedade, **valor bruto**, **Q-id** (URL da entidade) e **data da consulta**. Vários valores para o mesmo CUSA viram um registro com várias evidências.
- **Nada inventado:** registros do Wikidata não têm região, idiomas, edição nem versão (aparecem como "desconhecido"); o Content ID só existe se o próprio valor era um Content ID completo.
- **Origem separada:** `origem: "wikidata"`, `verificadoEmFonteOficial: false`, status **WIKIDATA: alegado, NÃO verificado em fonte oficial**. Os registros curados da 5B (`data/versoes-cusa.json`) **nunca são alterados** (o resultado fica em `local/cusas-wikidata.json`); quando o mesmo CUSA aparece nos dois para o mesmo Q-id, o curado ganha "Também no Wikidata (Pxxxx)" e **nenhum registro duplicado é criado**.
- **Conflitos (nada é associado):** o mesmo CUSA atribuído a mais de um jogo no Wikidata, ou CUSA que contradiz um registro curado (já cadastrado para outro Q-id). Ficam em `conflitos` (para revisão), aparecem como aviso no jogo e a busca por esse CUSA diz "em CONFLITO". Listar: `python -m ps4store.cusas --conflitos`.

## Importação incremental e proteção
- **Cache por propriedade** (`local/cusas-wikidata-cache.json`): uma propriedade com cache completo e mais nova que `--max-idade-dias` (30) **não é consultada de novo**; `--forcar` ignora o cache.
- **Controle de requisições:** pausa entre consultas (`--pausa`, 1 s), teto (`--max-requisicoes`, 60), páginas de 1.000 jogos **distintos** (`SELECT DISTINCT` na subconsulta), User-Agent seu (`WIKIDATA_USER_AGENT`), repetição em 429/5xx.
- **Coleta incompleta nunca substitui nada:** cada propriedade é conferida contra a contagem do serviço (tolerância de 0,5%). Se algo ficar incompleto (ou estourar o teto), o cache e o resultado **válidos continuam como estavam**, a coleta parcial vai para `local/cusas-wikidata-cache.parcial.json` e o comando termina com erro; `--aceitar-parcial` importa mesmo assim e marca o resultado como parcial.

## Pesquisa unificada (mesmo campo)
No painel e no `python -m ps4store.jogos`: **nome** (livre, sem filtros), **CUSA** (`CUSA00133`, minúsculas aceitas) e **Content ID completo** (curado ou vindo do Wikidata). O programa diz o que reconheceu ("reconhecido como CUSA", "é um Content ID, não um CUSA; o CUSA contido nele é …"). `busca.py` continua sendo a busca por nome (biblioteca).
No painel, os novos CUSAs aparecem com o selo azul **WIKIDATA**, os desconhecidos como "desconhecido", e os curados mantêm CITADO/CONFIRMADO; layout e filtros iguais (filtro de região/idioma não casa com registro de valor desconhecido).

## Estratégia de execução no Termux (nesta ordem)
```sh
cd ~/PS4 && git pull
export WIKIDATA_USER_AGENT="MeuApp/1.0 (seu-contato@exemplo)"
# 1) quantos jogos têm valor? (rótulos reais das propriedades, contagens e formatos; poucas consultas; não grava)
PYTHONPATH=src python -m ps4store.cusas --sondar
# 2) teste com poucos jogos (não grava): Batman, GTA V (nome completo) e Cyberpunk 2077
PYTHONPATH=src python -m ps4store.cusas --amostra "batman,grand theft auto v,cyberpunk"
# 3) SÓ se 1 e 2 parecerem certos: importar tudo (incremental; imprime a cobertura real)
PYTHONPATH=src python -m ps4store.cusas --atualizar
# 4) ver conflitos e usar
PYTHONPATH=src python -m ps4store.cusas --conflitos
PYTHONPATH=src python -m ps4store.painel
```
O relatório do passo 3 informa: jogos no índice, com valor, **com CUSA válido (%)**, **sem CUSA**, registros, CUSAs distintos, conflitos, rejeitados por motivo e o detalhe por propriedade.
