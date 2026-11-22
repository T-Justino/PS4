# Pesquisa de links e download direto (modo pessoal)

Objetivo: descobrir links de PKGs em fontes públicas, **validar, resolver e classificar**, e deixar o SSPI baixá-los. Dois caminhos, com regras diferentes:

| Caminho | O que é | Quem entra | Onde fica |
|---|---|---|---|
| **A. Catálogo `.gssource`** (publicável) | busca no SSPI + download | só ID `CUSA`, identidade verificada, host com TLS ok, tipo base, **autorização registrada**, sem aparência comercial | `dist/auto/` (Git, hospedado) |
| **B. Pesquisa + lista pessoal** (novo) | `local/research.json` (tudo o que foi achado, com status e motivo) e `local/links-sspi.txt` (links para **colar** no SSPI: Downloads → colar link) | identidade verificada, link utilizável pelo baixador, tipo base, **sem aparência comercial**, qualquer prefixo de ID | `local/` (**fora do Git**, nunca commitado nem hospedado) |

`local/` está no `.gitignore` e o workflow só commita caminhos explícitos. As proteções de publicação do caminho A **não mudaram**.
**Nada de jogos comerciais é conectado ou procurado:** não há conector para sites que distribuem jogos sem direitos, e itens com Content ID de aparência comercial (`UP/EP/IP/UT…`) ou categoria `media/game/mod/dev menu` do PKG-Zone ficam **restritos**: aparecem na pesquisa (metadados), mas em **nenhuma** lista de download, e só chegam a catálogo com autorização **por item**.

## Comando
```bash
PYTHONPATH=src python3 -m ps4store run --refresh-links 10   # descobre → valida → classifica links → catálogo + local/research.json + local/links-sspi.txt
```
`--refresh-links N` re-sonda até N itens em cache sem dados de link por execução (o workflow usa 10), então a cobertura cresce sem sondagem em massa. `--research-dir` muda a pasta local.

## O que cada link diz (`linkStatus` e `linkNotes`)
`direto` · `redirect` (+ `temporaryRedirect` se a URL final é assinada/expira) · `pagina-intermediaria` (HTML: não automatizamos) · `exige-autenticacao` (401/403: **não tentamos contornar**) ·
`expirado` (403 numa URL assinada) · `removido` (404/410) · `erro-de-rede`/`erro-http`. Também `rangeOk`, `fileType` (`pkg`, `rar-multiparte`), tamanho verificado, ID e Content ID lidos **do próprio PKG**, `duplicateOf` (mesmo Content ID+versão+tamanho em outro lugar) e `sspiDownloadable`.

## Como o SSPI usa uma URL (lido no código público `transfer/gs_http.c`, `gs_xfer.c`; **ainda sem prova no console para redirects**)
- Segue redirects sozinho (só HTTPS→HTTPS). Se a URL final **assinada expirar** (401/403/404/410/5xx), **refaz o redirect pela URL original**. Por isso guardamos sempre a URL **estável**, nunca a assinada.
- Baixa em **faixas `Range` paralelas** quando recebe 206 com `Content-Range` e total; sem `Range`, baixa numa conexão só. Exige `Content-Encoding` identity.
- **Colar link direto (PKG/RAR)** na aba Downloads **não passa pelo importador de catálogo**: o ID do pacote (`NPXS`, `APOL`, `BREW`…) não é barrado aqui. É a rota para o homebrew que o catálogo não carrega.
- RAR dividido: o SSPI suporta (`x.part1.rar` ou `x.rar`+`x.r00`, 2–512 volumes declarados em ordem). O robô **reconhece** esses nomes (`ARCHIVE_MULTIPART`, não sondados); **publicá-los é o Gate 5** (não feito).

## Resultado real (22/11/2026)

**Fontes consultadas:** (1) PKG-Zone, catálogo JSON público (191 releases ativas); (2) GitHub Contents do repositório do projeto (3 PKGs); (3) GitHub Releases: do projeto (0) e do Apollo (no Actions: 5 releases reais, `APOL00004`). `LightningMods/PS4-Store` foi adicionada só para pesquisa; **sem resultado ainda** (403 nesta sessão; roda no Actions).
**Não conectadas, de propósito:** qualquer fonte de jogos comerciais sem direitos.

| Métrica (PKG-Zone + pasta própria) | Valor |
|---|---|
| Links descobertos | **194** (191 + 3) |
| Acessíveis (o servidor entregou o arquivo) | **187** (7 são PS5: descobertos, não sondados) |
| Com identidade PKG verificável (Content ID = `TITLE_ID`) | **183** (4 PKGs têm o `param.sfo` além dos 64 KiB) |
| Links com classificação completa (sondados com a versão nova) | **15** (12 PKG-Zone + 3 próprios); sobem 10 por execução do workflow |
| Dessas 15: baixáveis pelo SSPI (hipótese pelo código) | **15/15**: 3 diretos; **12 redirects para URL assinada temporária**, todos com `Range` 206 e tamanho conferido |
| Compatíveis com o importador (ID `CUSA`, base) | 22, dos quais **1 publicável** (app próprio); 19 são `RETAIL_STYLE_ID` (aparência comercial, bloqueados) |
| IDs que o catálogo não importa (`PREFIX_UNPROVEN` 153, recusados 2) | 155: **fora do catálogo, mas na pesquisa**; os não restritos entram na lista pessoal para colar |
| Restritos (aparência comercial) | 102: só metadados |
| Lista pessoal gerada | 9 itens (homebrew/utilitários/emuladores; tamanhos de 7 a 63 MB) |

## Obstáculos que impedem os demais downloads
1. **Catálogo só aceita `CUSA`:** 155 itens não podem ir por catálogo. Solução tecnicamente viável: **colar o link** (caminho B), a testar no console (T10).
2. **Restritos (102):** excluídos por política; não vou listá-los para download.
3. **Redirect assinado do PKG-Zone:** previsto como compatível, **não testado no SSPI** (T10, parte B).
4. **11 sem verificação de identidade:** 7 PS5 (fora do alvo) e 4 com `param.sfo` fora da janela; solução simples: uma 2ª requisição `Range` só do `param.sfo` (não implementada, ganho pequeno).
5. **Cobertura de medição:** 15 de 191 links do PKG-Zone com dados completos; o resto sobe pelo `--refresh-links` (ou `--recheck`, que é sondagem em massa: evitei).
6. **Multipartes:** nenhuma fonte atual os usa; mecanismo de detecção pronto, publicação é o Gate 5.
7. **Sem autorização de listagem do PKG-Zone:** não afeta o caminho B (uso pessoal, link direto da própria origem), mas continua bloqueando o A.

## Teste no console (T10): colar link, sem catálogo
No celular (página do SSPI) ou no PS4 (*Downloads → touchpad → Paste a download link*), um link por linha:

| | Link | O que prova |
|---|---|---|
| A | `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/pkgs/PS4StoreBRTest_CUSA95417_v1.02.pkg` (app próprio; exclua o app antes se a v1.00 estiver instalada) | colar link **direto** funciona e instala sem catálogo |
| B | `https://pkg-zone.com/download/ps4/NUEX00001/3.0` (PS MTP Explorer, homebrew público de 7 MB, **ID `NUEX…`, que o catálogo recusaria**) | **redirect para URL assinada** + `Range` funcionam no SSPI, e o SSPI instala ID não-`CUSA` pelo link |

B instala um homebrew de terceiros no seu console: decisão sua (os Termos do PKG-Zone avisam sobre riscos). Se preferir só validar o download, cancele antes de instalar.
```text
T10
A: aceitou o link [sim/não+msg] | download [ok/erro] | instalou [sim/não+msg] | abre [sim/não]
B: aceitou o link [sim/não+msg] | tamanho mostrado [__] | download [ok/erro+msg] | PKG aceito [sim/não+msg] | instalou [sim/não]
```
