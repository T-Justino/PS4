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
