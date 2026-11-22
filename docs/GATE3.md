# Gate 3 — descoberta automática de links (MVP) — fonte real: PKG-Zone

**Um comando:** `PYTHONPATH=src python3 -m ps4store run`. Descobre → verifica → classifica em fases → gera o `.gssource` só com o que é PUBLICÁVEL.

## Estado do critério do MVP (honesto)

| Critério | Estado |
|---|---|
| Descobrir links **reais** de fonte **externa**, sem cadastrar arquivos | **Atendido** (PKG-Zone: 191 releases ativas descobertas e verificadas sem cadastro de URL) |
| Verificar links com requisições leves, ler a identidade do PKG | **Atendido** (184 acessíveis, 180 PKGs lidos; 1 requisição `Range` de 64 KiB cada) |
| Detectar release/upload novo sem mexer em código ou cadastro | **Atendido na lógica** (testes + execução real com estado); **ainda não vi o PKG-Zone publicar algo novo durante esta sessão** (ver evidência) |
| Alimentar o SSPI com pacotes compatíveis | **NÃO atendido: 0 publicáveis.** Bloqueio de **autorização**, não técnico (abaixo) |

## Investigação do PKG-Zone (feita nesta sessão, host liberado por você)

- **`robots.txt`:** `User-agent: *` / `Disallow:` (nada proibido).
- **API:** o site é uma SPA que carrega **`https://pkg-zone.com/api/v1/catalog`** (JSON público, ~140 KB, 187 apps) e `/api/v1/counts`. Não há documentação de API nem OpenAPI
  (`/api`, `/docs`, `/openapi.json` dão 404). **`api.pkg-zone.com`** é o host de armazenamento/download; a raiz devolve um **desafio anti-bot do Cloudflare** ("Just a moment…").
  **Não tentei contornar o desafio**; os caminhos `/dl/…` abrem normalmente quando chegam via o redirect do link de download.
- **Download:** o catálogo não traz URLs. O link estável é `https://pkg-zone.com/download/{console}/{titleId}/{versão}`, que responde **302 para uma URL assinada e com expiração
  (`exp`, `sig`; ≈6 h) em `api.pkg-zone.com`**. Guardamos **só o link estável**; a URL assinada nunca é gravada (testado).
- **Termos de uso** (texto lido no próprio site, atualizado em 18/11/2026): proíbem *scraping abusivo/não autorizado*, uso de ferramentas automatizadas que **sobrecarreguem** o serviço e **contornar controles de acesso**.
  Não proíbem leitura automatizada moderada do catálogo público (o §7 até descreve o cache do catálogo para "reduzir requisições"), mas **não concedem permissão a terceiros para listar/redistribuir os apps**:
  cada app é de responsabilidade de quem enviou; o PKG-Zone "não verifica nem endossa"; sem licença informada, **nenhuma licença é implícita**.
- **Conclusão:** *consumir* o catálogo de forma leve e documentada é compatível com os termos (e com o `robots.txt`). **Publicar os apps no nosso catálogo não está autorizado por ela** e o catálogo não traz campo de licença.
  O robô se limita: 1 requisição de catálogo por execução, 1 sondagem de 64 KiB por release, pausa de 0,5 s, cache de 7 dias, teto de 250 sondagens/execução, sem enviar credenciais.
  **Aviso:** sondagens podem contar como downloads nas estatísticas do site (pergunta no rascunho de pedido, `docs/PKGZONE_PEDIDO.md`). Foram ~190 na primeira execução.

## Resultado da descoberta REAL (22/11/2026) — `docs/evidencia/pkgzone-descoberta-real.report.md`

| Descobertos | Acessíveis | PKG lido | Compatíveis (regras) | **Publicáveis** |
|---|---|---|---|---|
| 191 | 184 | 180 | 19 | **0** |

Motivos (191 rejeições): `PREFIX_UNPROVEN` 153 · `NO_AUTHORIZATION` 19 · `NOT_PS4` 7 (PS5, não sondados) · `SFO_OUTSIDE_WINDOW` 4 · `KIND_UNTESTED` 4 ·
`PREFIX_REJECTED_BY_SSPI` 2 (**`APOL00004` Apollo Save Tool; `NPXS29129` GameMaker app**: ficam no relatório, nunca no `.gssource`) · `PLACEHOLDER_ID` 2.

**Os 19 "compatíveis" (prefixo `CUSA`, base) estão sem autorização, e deveriam estar.** Pelos Content IDs, são repackagens de **apps/jogos comerciais** (Netflix `EP4350-CUSA00127_00-NETFLIXPOLLUX001`,
YouTube, Hulu, Paramount+, ESPN, Twitch, Crunchyroll, Plex, Apple TV, Pluto TV, ADN; mods de jogos). Não verifiquei o conteúdo dos arquivos. Listá-los contrariaria a regra do projeto
(nada de links sem autorização). Os poucos que parecem homebrew próprio (ex.: `CUSA02012` PS4 Media Player) não têm licença legível na fonte.

**Dez PKGs têm ID diferente do declarado no catálogo da fonte** (ex.: catálogo `CUSA01116` "Youtube" → PKG `CUSA01015`; `CUSA00002` "Half-Life Blue Shift" → PKG `CUSA00000`, placeholder).
Por isso a identidade vem do PKG, nunca do catálogo da fonte (o robô agora avisa essas divergências).

## Fases (relatório e `ps4store run`)

| Fase | Significa | Quantos (real) |
|---|---|---|
| **DESCOBERTO** | achado na fonte (inclui PS5, e PKGs cujo `param.sfo` fica além dos 64 KiB) | 11 |
| **VERIFICADO** | URL acessível **e** metadados do PKG lidos e consistentes (inclui `NPXS`/`APOL`/outros prefixos, com o motivo de não serem publicáveis) | 180 |
| **PUBLICÁVEL** | verificado + compatível com o SSPI + TLS ok + **autorização** → entra no `.gssource` | 0 |

Nada é descartado na descoberta; só PUBLICÁVEL entra no catálogo instalável.

## Autorização (decisão de design)

`config/sources.json`: cada fonte tem `authorization` (da fonte inteira) **ou `null`**, e `authorized_titles` (por item: `basis` + `evidence`). **Nunca presumida.**
O PKG-Zone está com `authorization: null`: o robô descobre e verifica, mas não publica nada.
Para publicar um app: registrar a licença/permissão **daquele app** em `authorized_titles`. A URL continua descoberta sozinha; só a autorização é uma decisão humana.

## Fonte GitHub (conector existente)

- **Nesta sessão** só a API do repositório do projeto responde; repositórios de terceiros dão **403 por política do ambiente** (ex.: `bucanero/apollo-ps4`), então **não consegui avaliar releases de projetos homebrew de terceiros aqui**.
  O conector está pronto e testado; no seu computador (ou num Actions) com acesso à API ele funciona sem mudança de código.
- **Expectativa (não verificada):** a maior parte dos homebrew usa IDs `NPXS`/`APOL`/`BREW` → `PREFIX_*`; os downloads do GitHub usam `github.com` (TLS falhou no SSPI) → `TLS_HOST_BLOCKED`.
  Ou seja, **mesmo com acesso, o GitHub tende a render 0 publicáveis hoje.**

## Bloqueio concreto e opções

O gargalo **não é a descoberta**; é a interseção **(ID aceito pelo importador = `CUSA`) ∩ (distribuição autorizada) ∩ (host que o SSPI baixa)**, hoje praticamente vazia:

| Opção | Efeito | Esforço |
|---|---|---|
| **A. Pedir permissão ao PKG-Zone e licença por app aos autores** (rascunho em `docs/PKGZONE_PEDIDO.md`) | destrava itens individuais; os 19 `CUSA` atuais são comerciais e **não** devem ser autorizados | e-mail seu; depois 1 linha por app em `authorized_titles` |
| **B. Resultado do T8** | diz se um host/ID próprio instala; decide `tls.known_bad_hosts` | seu teste |
| **C. Rodar o conector GitHub onde a API é acessível** | avalia homebrew com release real e licença livre | rodar o comando na sua máquina |
| **D. Fonte própria** (releases dos nossos apps, como o T8) | única fonte 100% autorizada hoje; depende do TLS/host (B) | baixo |
| **E. Reavaliar a restrição `CUSA`-only** | `NPXS`/`APOL` cobrem a maioria dos homebrew, mas o importador os recusa; só novos testes dizem se há saída (fora do escopo pedido) | — |

## Evidência de detecção de entrada nova

- **Execução real 1:** estado vazio → 191 novos, todos descobertos sem cadastro de URL (a config só tem `base_url`).
- **Execução real 2 (minutos depois):** `novos=0`, **0 sondagens** (cache); catálogo idêntico.
- **Execução real 3:** removi **uma** chave do estado (`MOZI00001`, o upload mais recente, 21/11/2026) para simular "ainda não visto" → `novos=1`, **1 sondagem**, fase VERIFICADO.
  *Isso simula a chegada de um item; não é o PKG-Zone publicando algo novo durante a sessão.*
- **Testes** (`tests/test_pkgzone.py`, 8; `tests/test_gate3.py`, 16): um upload novo no catálogo é detectado sem mudar código/config, com **uma** sondagem (o resto vem do cache); a autorização nova vale sem sondar de novo;
  a URL assinada nunca é gravada; `NPXS`/`APOL` ficam VERIFICADOS e fora do `.gssource`; PS5 não é sondado; teto de sondagens e pausa funcionam.
  **Total: 107 testes passam** (99 anteriores + 8 novos).
- Para observar o caso real: agende `ps4store run` (ex.: diário) e leia `dist/auto/discovery.report.md`: novos aparecem com "Novo = sim".

## Limites conhecidos

`SFO_OUTSIDE_WINDOW` (4 PKGs com `param.sfo` além de 64 KiB: não verificados; todos com prefixo não comprovado de qualquer forma). `gde` é tratado como app base (visto em PKGs reais; sem teste no console).
O redirect para a URL assinada em `api.pkg-zone.com` **não foi testado no SSPI** (o T8 usa outro host). "Compatível" = regras conhecidas; a instalação sob essas regras segue sem prova (T8).
