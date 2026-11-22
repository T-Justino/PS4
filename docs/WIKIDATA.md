# Catálogo real de jogos via Wikidata (Etapa 5A.1)

Importador independente `src/ps4store/wikidata.py` → índice local `local/busca-indice.json` (o mesmo de `busca.py`). **Só metadados** (nome, identificador Q, páginas de referência, ano). Nenhum link de download; encontrar um jogo **não** significa que exista PKG.

## O que foi verificado e o que não foi
- **NÃO verificado (sem rede):** o proxy deste ambiente bloqueia `query.wikidata.org` (falha 403 no shell; DNS no agente de leitura web). Você negou a liberação do host, então **nenhum dado real do Wikidata foi obtido aqui**. **A quantidade real de títulos importados não foi medida** (aqui: 0 reais). O número aparecerá quando você rodar o comando no Termux.
- **Verificado:** o importador, a paginação, o mapeamento, o cache offline e a busca funcionam, com respostas **simuladas** no formato documentado do SPARQL JSON (Q-ids inventados `99000xxxx`; os testes dizem isso). 11 testes novos.
- **Conhecimento geral, a conferir no 1º uso:** a consulta usa `wdt:P31/wdt:P279* wd:Q7889` (videogame) e `wdt:P400 wd:Q5014725` (plataforma PlayStation 4) e as propriedades `rdfs:label`, `schema:about` (páginas da Wikipedia) e `P577` (data de publicação). Se os Q-ids/propriedades estiverem errados, a contagem sai absurda (0 ou milhares fora de PS4) e o relatório mostra isso.
- Convenções do Wikimedia (User-Agent com contato, poucas requisições, `Retry-After`) estão implementadas, mas vêm de documentação pública que **não consegui reler daqui**.

## Dados e licença
Wikidata: dados estruturados em **CC0 1.0** (registrado em `config/busca-fontes.json`, fonte `wikidata`, `basis: license`). O índice grava `origem`, `licenca` e `obtidoEm`, e a busca imprime a linha "Metadados de 'wikidata': licença CC0-1.0 …".
- Nomes, Q-ids (`idFonte`) e URLs vêm da fonte sem alteração. URL do resultado = página da Wikipedia (en, senão pt) se existir; senão a página do próprio Wikidata. Todas ficam em `referencias`.
- **Campo ausente fica ausente:** item sem rótulo en/pt é descartado e contado; sem data não há ano; sem Wikipedia não há link da Wikipedia; sem rótulo pt não há alias. URL fora de `https://{en,pt}.wikipedia.org` é ignorada.

## Paginação e validação (correção 22/11/2026)
Relato real no Termux: o serviço contava **6.628** jogos de PS4, mas `--atualizar` parou na página 1 (988 linhas, **947 jogos distintos**) e só 947 foram importados (a busca por "lego batman" não achou nada e "Batman" só 4).
- **Causa:** a subconsulta de página era `SELECT ?g` sem `DISTINCT`: o mesmo jogo aparece por mais de um caminho de classe e o `LIMIT 1000` contava linhas repetidas, trazendo menos de 1000 jogos distintos; a regra antiga "página curta = fim" encerrava a coleta.
- **Correção:** `SELECT DISTINCT ?g … ORDER BY ?g LIMIT/OFFSET` (a página passa a contar jogos); página curta **não** encerra. A coleta só termina com página vazia, ao atingir a contagem do serviço, sem Q-ids novos (página repetida) ou no teto de páginas. Depois confere os Q-ids coletados contra a contagem do serviço (tolerância de 0,5%).
- **Incompleta:** o índice e o cache atuais **não são substituídos**; a coleta parcial fica em `local/wikidata-ps4.parcial.json` e o comando termina com erro. `--aceitar-parcial` importa mesmo assim e marca a fonte como PARCIAL (a busca avisa). `--offline` também recusa cache marcado incompleto. Sem a contagem (consulta falhou), a coleta só vale se terminar em página vazia e o relatório diz "NÃO conferido".
- Regressão testada com um serviço simulado: 6.628 jogos, 1ª página com 988 linhas/947 jogos (os números exatos do relato). **Não verificado contra o serviço real** daqui (rede bloqueada).

## Comandos (Termux)
**Passo 0, teste rápido (2 consultas pequenas, não grava nada):** confirma que a API responde e que os identificadores estão certos antes da importação completa.
```sh
export WIKIDATA_USER_AGENT="MeuApp/1.0 (seu-contato@exemplo)"
PYTHONPATH=src python -m ps4store.wikidata --testar batman
```
Mostra a contagem de jogos de PS4 do serviço e os jogos com "batman" no nome (nome, ano, URL, Q-id). Se a contagem for 0 ou absurda, os Q-ids/propriedades da consulta estão errados e **não** vale rodar `--atualizar`: me envie a saída.

```sh
cd ~/PS4 && git pull
# 1) atualizar o índice (completo; pode levar alguns minutos no celular) (precisa de internet; use o SEU contato no User-Agent, como o Wikimedia pede)
export WIKIDATA_USER_AGENT="MeuApp/1.0 (seu-contato@exemplo)"
PYTHONPATH=src python -m ps4store.wikidata --atualizar
# 2) pesquisar (offline, só o nome)
PYTHONPATH=src python -m ps4store.busca Batman
PYTHONPATH=src python -m ps4store.busca lego batman
# reconstruir o índice só do cache local, sem rede
PYTHONPATH=src python -m ps4store.wikidata --offline
```
A atualização faz 1 consulta por página de 1.000 jogos com pausa de 1 s (teto de 40 páginas) e grava a resposta bruta em `local/wikidata-ps4.json`. Falha de rede não apaga nem cria índice.
Depois do primeiro `--atualizar`, **anote o relatório** (jogos no Wikidata, importados, sem rótulo, com Wikipedia, com ano) e confira se Batman/LEGO Batman aparecem.

## Se o Wikidata for insuficiente
Cobertura de PS4 no Wikidata é incompleta e irregular (depende de voluntários; não medi). Alternativas de metadados com acesso permitido (conhecimento geral, **não verificado aqui**; confirmar termos antes de usar):
- **Wikipedia (listas de jogos de PS4, MediaWiki API):** texto sob CC BY-SA, exige atribuição; cobertura boa de títulos conhecidos.
- **IGDB (API da Twitch):** gratuita para uso não comercial com credenciais (Client ID/secret); termos próprios de uso e atribuição.
- **RAWG:** chave de API gratuita com limites e atribuição obrigatória.
Qualquer uma entraria como nova fonte em `config/busca-fontes.json` (com a autorização/licença registrada) e um importador próprio que produza o mesmo formato.

## Limites
Sem CUSA, região ou idioma (campos reservados, não preenchidos); sem filtros; sem links de download; 1 consulta paginada de "tudo de PS4" pode demorar ou o endpoint pode recusar (o importador tenta de novo em 429/5xx e para com erro claro).
