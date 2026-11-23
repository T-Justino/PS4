# 5H · Metadados, PT-BR, versões e links

## Comandos
- `python -m ps4store.metadados --fila 10 --jogos "batman,cyberpunk,grand theft auto"`: consulta até 10 jogos (máx. 30) nas três fontes e grava `local/metadados.json` (fora do Git). Rode de novo para avançar; o que foi consultado há pouco não é repetido (patch: 7 dias; idiomas: 30 dias).
- `--status` (sem rede) e `--jogo "nome"` (sem rede: o que se sabe do jogo).
- `--painel-porta 8765` prioriza jogos abertos/pesquisados no painel. `--fontes sony,wikidata,loja` escolhe as fontes.
- `--permitir-http`: só se o TLS do servidor de atualizações da Sony falhar na verificação; os dados ficam marcados `oficial-via-http` (integridade não verificada). Não é usado por padrão.

## Fontes (todas sem chave/pagamento; nenhuma validada com rede na sandbox de desenvolvimento)
| Fonte | O que dá | Grau |
|---|---|---|
| Sony, XML de atualização (`gs-sec.ww.np.dl.playstation.net/plo/np/<CUSA>/<hmac>/<CUSA>-ver.xml`) | versão do patch mais recente, tamanho, firmware exigido, Content ID, título | oficial |
| Wikidata P407 + qualificador P518, etiqueta IETF (P305) | pt-BR / pt-PT / pt por parte (dublagem, legendas, interface) | alegado |
| PlayStation Store (página do produto, só se o robots.txt permitir) | listas de idiomas de áudio e de tela | oficial |
O servidor da Sony lista só a atualização atual: o "histórico" é o que este projeto viu mudar entre consultas. Versão do patch ≠ versão do jogo-base ≠ versão do PKG. Firmware: só o declarado; ≤ 9.00 não garante compatibilidade.

## PT-BR
Partes: áudio, texto/interface, legendas, e "tela" (a loja junta texto e legendas). Status: confirmado (uma fonte afirma), não consta na lista da fonte, desconhecido. "Português" sem variante e pt-PT ficam separados e não contam como PT-BR. Região nunca define idioma. Filtro no painel: qualquer / áudio / texto ou legendas; jogos sem dado continuam na busca geral.

## Links → SSPI (painel)
Na página do jogo, "Analisar link": `GET /api/link` (exige cabeçalho `X-PS4Store`, contra CSRF; uma análise por vez). Usa `resolver.crawl` (HTTPS, hosts de `config/resolver-hosts.json`, sem IP privado, ≤5 redirecionamentos, profundidade 1), lê o cabeçalho/param.sfo do PKG (`pkginfo`) e monta os blocos com `colar.montar_blocos`. CUSA diferente do jogo ou em conflito auditado: bloco NÃO pronto. Página da PlayStation Store: nunca é link de PKG. CAPTCHA/login/JavaScript não são contornados.

## Correções após o teste real (Termux)
- `--jogos`: só entra o jogo de **nome exato** (ou apelido com vínculo explícito, ex.: "gta v"), um por nome. Nome parecido ou ambíguo não entra: vira aviso com os parecidos. Sem `--jogos`, a fila usa o interesse do painel e jogos com CUSA.
- Sony: erro de rede/TLS não fica "valendo" por 7 dias; a próxima execução tenta de novo. O erro TLS agora traz o motivo do OpenSSL (ex.: emissor não confiável). Validação de certificado continua ligada. Diagnóstico: `python -m ps4store.metadados --sony CUSA00133 [--permitir-http]`. A URL segue o formato `https://gs-sec.ww.np.dl.playstation.net/plo/np/<CUSA>/<HMAC-SHA256("np_"+CUSA)>/<CUSA>-ver.xml` (de memória; não conferido em rede daqui). Se só o HTTP responder, `--permitir-http` grava com grau `oficial-via-http` (integridade não verificada).
- Força da evidência de PT-BR: **confirmado** = fonte oficial (desenvolvedor por CUSA, ou página do produto na loja); **informado** = só Wikidata (geral, não verificado); **não consta** = fonte oficial com lista completa sem PT-BR. Filtros: `oficial`, `audio` e `texto` (só fonte oficial) e `qualquer` (inclui Wikidata). Card: "PT-BR" (oficial) ou "PT-BR? (Wikidata)".
- Metadados oficiais por produto/CUSA: `data/metadados-oficiais.json` (genérico, validado por `--validar-oficiais`): CUSA, escopo (ex.: edição física das Américas), idiomas por parte, lista completa ou parcial, fonte, URL, data e como o conteúdo foi obtido. Primeiro uso: Cyberpunk 2077 (página de suporte da CD PROJEKT RED): CUSA16596/CUSA16597 (físicas Américas: dublagem e texto PT-BR) e CUSA16496/CUSA20476 (japonesas: inglês e japonês). Os CUSAs também entraram em `data/versoes-cusa.json` com a mesma evidência (status "citado"; conteúdo relatado pelo usuário, página não lida pela ferramenta). Vale só para esses CUSAs, não para edições digitais.
- Cyberpunk sem CUSA: o registro local só tinha CUSAs alegados no Wikidata; nenhum havia para Q3182559 (ou estavam em conflito). `--jogo "cyberpunk 2077"` agora diz qual dos dois casos é.
- PlayStation Store: saiu do padrão. As páginas não trazem as listas de idiomas no HTML (são montadas depois por JavaScript/API interna); não é feito scraping dessa API. `--fontes ...,loja` continua possível, como experimental.
