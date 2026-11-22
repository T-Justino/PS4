# Gate 3 — descoberta automática de links — fonte real: PKG-Zone

> **Registro:** a descoberta real no PKG-Zone (191 releases descobertas, 184 links acessíveis, 180 PKGs lidos) é **prova de descoberta automatizada**.
> **Não é o MVP concluído.** O critério do MVP é: *um pacote autorizado, descoberto automaticamente, publicado no catálogo e instalado no PS4, sem cadastrar o link*.
> Os resultados do PKG-Zone ficam preservados (`docs/evidencia/`, estado e cache em `data/state/`); nada foi publicado sem autorização.

## MVP: o que está comprovado, e onde

| Critério | Em código/testes | Em rede real | No PS4 real |
|---|---|---|---|
| Arquivo autorizado descoberto em fonte real, sem cadastrar a URL | sim (113 testes) | **sim**: API de Contents do GitHub achou `pkgs/*.pkg`; antes/depois abaixo | — |
| Link verificado, identidade do PKG validada | sim | **sim**: `Range` 64 KiB no `raw`; Content ID = `TITLE_ID` = `CUSA95417`; tamanho confere | — |
| `.gssource` gerado sem cadastrar a URL; sem duplicar o ID | sim | **sim**: v1.0.2 (só v1.00) e v1.0.3 (só v1.01; v1.00 `SUPERSEDED`) | — |
| Importar, achar, baixar | — | — | **T8 (22/11): sim** (importou, achou, 6,6/6,6 MB, "Installed") |
| **Abrir o app** | — | — | T8 original: não; **T8b: SIM** (v1.00 corrigida, tela "INSTALACAO OK", 22/11/2026) |
| Atualização da fonte | regras do SSPI lidas no código público | — | **pendente** (T8b, Parte 2) |
| Automação agendada | workflow escrito; mesmo comando testado | — | **não executado no GitHub ainda** |

**Ciclo de instalação e execução comprovado para o app próprio (T8b). O MVP ainda depende da atualização por URL e do workflow agendado.** Evidência antes/depois: `docs/evidencia/gate3-antes.report.md` e `gate3-depois.report.md`. Diagnóstico: `docs/DIAGNOSTICO_T8.md`.
Automação e atualização: `docs/AUTOMACAO_E_ATUALIZACAO.md`. Procedimento: `docs/TESTE_T8B.md`.

## Ciclo real anterior: descoberta → validação → catálogo (T8 original, defeituoso)

| Etapa | Estado |
|---|---|
| Descoberta sem cadastrar a URL | **Feito, ao vivo:** conector `github-contents` listou `dist/t8/` pela **API real do GitHub** e achou o PKG do T8 |
| Link e identidade validados | **Feito:** `Range` de 64 KiB no `raw.githubusercontent.com`; Content ID = `TITLE_ID` = `CUSA95417`; tamanho do servidor (6.619.136 B) = tamanho da API |
| Autorização | Fonte própria (`license`, software do autor do projeto) |
| Catálogo gerado do resultado real | **Feito:** `dist/auto/ps4storebr-auto.gssource` v1.0.1 (`check` OK); `data/generated/auto-catalog.json` |
| Instalação no PS4 | **Pendente:** T8 (você) e depois T9 (`docs/TESTE_T9.md`) |
| "Release nova" descoberta sozinha | **Provado em teste** (4 casos); **falta provar ao vivo** com um arquivo/versão novo real: precisa da sua aprovação (abaixo) |

**Por que `github-contents` e não Releases:** o seu SSPI falhou com TLS em `github.com`, que serve os downloads de Releases, então uma Release nunca fecharia o ciclo de instalação
(o robô a descobriria e a marcaria `TLS_HOST_BLOCKED`). O `raw.githubusercontent.com` é **outro host**, já em teste no T8. O conector de Releases continua pronto e testado.
Uma "release nova" aqui é um arquivo novo ou alterado na pasta autorizada (a chave inclui o `sha` do arquivo no Git).

**Alternativa de hospedagem se o T8 falhar por TLS** (sem contornar certificados): o que se sabe é que `pkg-zone.com` baixa e `github.com` não. Não sei qual CA o PS4 9.00 aceita
(hipótese: raízes antigas). O mais simples é repetir o T8 com o **mesmo PKG** em **um** host estático gratuito (Cloudflare Pages/R2 público; o PKG de 6,6 MB cabe) e adotar o primeiro que baixar;
o robô só precisa de um conector da API desse host ou de um índice JSON. Não implementei nada disso antes do resultado do T8.


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
