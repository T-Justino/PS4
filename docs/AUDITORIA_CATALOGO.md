# Auditoria do catálogo (22/11/2026): quanto dá para publicar no SSPI

Fonte dos números: `local/research.json` regenerado após o run `catalogo` #5 (lote de validação 60, Actions) e `ps4store run`. Nada foi removido dos bloqueios `NO_AUTHORIZATION` / `RETAIL_STYLE_ID`.

## Resultado

| | Antes | Depois do lote de 60 |
|---|---|---|
| Descobertos | 342 | 342 |
| Link acessível (testado e respondeu) | 52 | **112** |
| Link inacessível (403) | 15 | 15 |
| Link ainda não testado | 275 | 215 |
| Arquivo identificado (ID lido do PKG) | 185 | 187 |
| Disponíveis por link direto (lista pessoal) | 29 | **69** |
| **Títulos pesquisáveis no catálogo do SSPI (.gssource)** | **1** | **1** |

A busca dentro do SSPI continua com **1 título** (`CUSA95417`, app de teste próprio v1.02). Não houve bloqueio técnico: os critérios de publicação simplesmente não são atendidos pelos demais.

## Por que nenhum registro novo entra no .gssource (pkg-zone, 328 registros)

Para entrar é preciso, ao mesmo tempo: **autorização verificável + identidade lida do PKG + ID aceito pelo importador do SSPI (CUSA)**.

- **Autorização:** nenhum tem. A fonte `pkg-zone` não concede permissão de listagem a terceiros (`GATE3.md`). 65 descrições citam "open source/GPL/freeware/Apache": isso é só **pista** (`licenseHint`); a licença continua `LICENSE_UNKNOWN`. Não é ausência comprovada de autorização, é **ausência de autorização registrada**; só um registro por título em `config/sources.json` com evidência a muda.
- **ID aceito (CUSA):** 19 de 328. Os outros 163+ (`MOZI00001`, `LAPY…`, `NPXX…` etc.) o importador recusa; seguem só na rota de link direto.
- **Aparência comercial:** os 19 CUSA são todos `RETAIL_STYLE_ID` (Netflix, Hulu, Plex, DooM etc.). Nenhum "CUSA compatível e não comercial".
- Não usei CUSA fictício para disfarçar IDs incompatíveis.

## O que fica disponível, e onde

- **Catálogo SSPI (pesquisável no console):** 1 título.
- **Link direto (colar no SSPI, "Paste a download link"):** 69 itens com link testado e identidade lida, incluindo homebrew-jogos como OpenTyrian, Lapy Games Collection, Sonic SMS Remake 1 e 2, Relic Hunters Zero, Wild Gunman Remake. Rota tecnicamente suportada; `ps4store find <nome> --disponiveis --urls`.
- Itens "Descobertos, link NÃO testado" aparecem na busca como tal, sem URL.

## Como ampliar o catálogo do SSPI de forma legítima

1. Escolher homebrews com **ID CUSA genuíno** (poucos; a maioria usa IDs próprios).
2. Obter **evidência de licença/permissão do autor** (licença do repositório, release oficial) e registrar em `authorized_titles` com `basis` e `evidence`.
3. Só então rodar o workflow. Sem a evidência, o item permanece na busca/links diretos, fora do `.gssource`.
