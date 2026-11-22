# SDD — PS4 Store BR: catálogo automatizado para SSPI

**Versão:** 1.2 — 22/11/2026 · **Status:** revisado após Gates 1–2 e T7 (ver `docs/REVIEW.md`, `docs/CHAVES_SINTETICAS.md`) · **Substitui:** v1.1
**Alvo:** PS4 Pro, FW 9.00, GoldHEN, SSPI 5.11.7 (`0eb783eca1f3`) · **Idioma:** PT-BR

## 1. Visão

Uma loja de PS4 pesquisável, com prioridade para conteúdo em PT-BR. O serviço descobre, valida e publica um **catálogo**, e o PS4 baixa direto da origem via SSPI. A arquitetura é **agnóstica ao tipo de jogo**: homebrew, demo, gratuito ou comercial são tratados da mesma forma. O que decide se um item é instalável é a **autorização de distribuição do link**, não o tipo do jogo.

**Premissa corrigida (v1.2):** importar uma fonte com sucesso **não** garante que o pacote seja instalável. O SSPI valida o catálogo na importação e valida a identidade do PKG na instalação (§12).

**Separação central:** *catálogo* (identidade, metadados, idiomas) ≠ *disponibilidade* (links autorizados). Um título pode existir no catálogo sem nenhum link publicável.

**Não prometido:** cobertura de qualquer jogo, links inventados, bypass de CAPTCHA/DRM/login, hospedagem de arquivos de jogo, refresh automático sem prova, filtro PT-BR nativo no SSPI.

## 2. Evidências do console (relatadas pelo usuário)

1. O SSPI 5.11.7 roda com GoldHEN 9.00.
2. O `.gssource` de teste (ID fictício `CUSA99999`) foi importado por USB, e a busca "Apollo" retornou 1 item. O arquivo está em `tests/fixtures/` como **contrato de formato**.
3. `APOL00004` foi rejeitado (`Unsupported catalog title identifier`) num catálogo anterior, embora passe no regex público.
4. O download pelo GitHub falhou com TLS (`0x8095F00C`).
5. `https://pkg-zone.com/update/Store-R2.pkg` baixou (24,8 MB) e foi instalado. O SSPI exibiu `NPXS39041`.
6. Requisito: download direto no console, sem PC ou VPS ligados em operação.

## 3. Escopo

**MVP (Gates 1–4):** modelo canônico JSON; gerador e validador `.gssource`; 1 adaptador de fonte autorizada; verificação leve de links; relatório; CI agendado; hospedagem estática **se** o HTTPS for comprovado no SSPI (senão, USB).

**Pós-MVP:** RAR multipartes (Gate 5), refresh de fonte, artes e gêneros, painel admin, UI própria (Gate 6).

**Proibido:** hospedar ou espelhar pacotes de terceiros sem autorização; publicar links assinados, tokens ou cookies; IDs inventados (`CUSA99999` e afins são bloqueados no build); scraping aberto; banco de dados, VPS, Docker ou LLM obrigatória.

## 4. Arquitetura

```text
config/sources.json (allowlist, Gate 3) ─► adapters ─► data/*.json (canônico)
data/*.json ─► ps4store build ─► [valida canônico] ─► [serializa] ─► [check regras SSPI] ─► dist/*.gssource
                                                                  └─► relatório de exclusões
dist/*.gssource ─► USB (MVP) | Pages (Gate 4, se HTTPS provado) ─► SSPI ─► origem do arquivo
```

Python ≥ 3.11, **somente stdlib** no Gate 1, `pytest` nos testes. O cliente HTTP é escolhido no Gate 3.

## 5. Modelo canônico (`ps4storebr.catalog/v1`)

```jsonc
{
  "schema": "ps4storebr.catalog/v1",
  "source": { "id": "ps4storebr.x", "name": "...", "description": "...", "version": "0.1.0" },
  "titles": [{
    "titleId": "NPXS39041",               // real, com evidência
    "identityEvidence": "texto/URL",      // obrigatório
    "name": "...", "region": null, "aliases": ["..."],
    "languages": { "audioPtBr": "unknown|yes|no", "subtitlesPtBr": "unknown|yes|no", "evidence": null },
    "packages": [{
      "id": "...", "kind": "base|update|dlc|backport|unknown",
      "accessType": "Direct|HosterLanding", "url": "https://...",
      "hoster": "...", "label": "...", "sourcePageUrl": "https://...",
      "version": null, "size": null, "sha256": null, "contentId": null, "requiredFirmware": null,
      "authorization": { "basis": "official-developer-release|license|written-permission", "evidence": "..." }
    }]
  }]
}
```

**Regras:**
- O ID segue o regex público, sem placeholder (`*99999`, `*00000`).
- `languages.*=yes` exige `evidence`.
- Pacote sem `authorization.evidence` é **excluído** do `.gssource`.
- Título sem pacote publicável é **excluído** do `.gssource` (o SSPI exige ≥ 1 pacote).
- Exclusões aparecem no relatório.
- URL só HTTPS, sem credenciais embutidas, sem IP literal.

## 6. Contrato `.gssource` (derivado do fixture real + código público)

Ver `docs/REVIEW.md` §2. O gerador reproduz exatamente:
- nomes de arquivo `source.json`, `catalog.json`, `index/titles.json`, `packages/items.json`;
- ordem de chaves e JSON compacto UTF-8;
- manifesto com `size`/`sha256` dos bytes descomprimidos;
- ZIP Deflate com timestamp fixo e ordem fixa.

**Mapeamento PT-BR:** `audioPtBr=yes` → `searchText` += `ptbr dublado`; `subtitlesPtBr=yes` → `ptbr legendado`. `unknown` não adiciona nada.

**Limites:** os públicos, com margem conservadora (ZIP ≤ 4 MiB). Múltiplos shards e índices são gerados acima de 500 títulos ou 1 MB por shard, **[H]** mas isso ainda não foi provado no console.

## 7. Validação de links (Gate 3)

HEAD, depois `Range: bytes=0-31`, com timeout de 10 s, ≤ 5 redirects, só HTTPS, bloqueio de redes privadas e de downgrade, concorrência ≤ 4. Magic PKG `\x7FCNT` → `FILE_CANDIDATE`. HTML → `NOT_FILE`. 401/403 ou página de login → `AUTH_REQUIRED`. Status possíveis: `HTTP_REACHABLE`, `FILE_CANDIDATE`, `NOT_FILE`, `AUTH_REQUIRED`, `UNAVAILABLE`, `TLS_ERROR`, `UNKNOWN`. `SSPI_TESTED` só é marcado manualmente. O pipeline não baixa o arquivo completo e não fabrica `sha256`.

## 8. CLI

```bash
python -m ps4store build data/fixtures/X.json -o dist/X.gssource [--report dist/X.report.json]
python -m ps4store check dist/X.gssource
```
`build` falha (exit 1) se o canônico ou o `check` falharem. A escrita é atômica (temp + rename). `discover` e `report` entram no Gate 3.

## 9. Qualidade e segurança

- **Testes:** reprodução byte a byte do fixture real; determinismo; hashes e contagens; regex de ID; placeholders; kinds; accessType; URL; PT-BR sem evidência; exclusões; limites; caminhos inválidos no ZIP; adulteração detectada.
- **CI (Gate 4):** publica só com testes verdes e mantém o artefato anterior.
- **Segurança:** URLs tratadas como dados não confiáveis; sem segredos; sem desativar TLS.

## 10. Gates

| Gate | Entrega | Aceite |
|---|---|---|
| 0 | REVIEW + SDD 1.1 | aprovado pelo usuário ✅ |
| 1 | gerador, validador, CLI, testes, fixtures T2/T3 | `pytest` verde; build reproduzível; `check` OK |
| 2 | teste no PS4 (`docs/TESTE_PS4.md`, T7) | importação e busca comprovadas; **instalação com identidade compatível ainda pendente** (`docs/VALIDACAO_E2E.md`) |
| 3 | 1 adaptador autorizado + links + relatório | **Descoberta real comprovada** (`docs/GATE3.md`): PKG-Zone, 191 releases descobertas/verificadas sem cadastro; fases DESCOBERTO/VERIFICADO/PUBLICÁVEL; **0 publicáveis** (autorização por app ausente; IDs CUSA da fonte são apps comerciais). Pendente: T8, autorizações, conector GitHub fora desta sessão |
| 4 | Actions + hospedagem + rollback | HTTPS comprovado no SSPI ou USB oficial |
| 5 | RAR multipartes | ciclo comprovado com fixture pequena |
| 6 | UI própria | fora do MVP |

**Decisão condicional pós-Gate 2:**
- Se `NPXS39041` **e** `APOL00004` forem rejeitados, o binário restringe prefixos. O próximo teste usa um homebrew com ID `CUSA` real e autorizado, e o regex do validador é ajustado ao observado.
- Se só um for rejeitado, a regra é registrada como lista de prefixos permitidos.

## 11. Riscos

| Risco | Mitigação |
|---|---|
| Binário mais restrito que o código | Fontes de teste separadas por ID; ajuste do validador ao observado |
| TLS do SSPI por domínio | Provar cada host; USB como fallback |
| Poucas fontes autorizadas de jogos comerciais | Catálogo existe sem link; nada de link não autorizado |
| PT-BR incorreto | Evidência obrigatória; `unknown` por padrão |
| Termos do pkg-zone | Revisar antes do Gate 3 |
| Artefato ruim publicado | `check` bloqueante e artefato anterior mantido |

## 12. Identidade e instalabilidade (v1.2, após o T7)

**Evidências no console (SSPI 5.11.7 Final; rodapé `BETA 5.11 / 0eb783eca1f3`; PS4 Pro 9.00):**

| Teste | Resultado |
|---|---|
| T1 (fixture original) | Fonte com `CUSA99999` importada e pesquisada |
| T2/T3 | `NPXS39041` e `APOL00004` como chave: **importação recusada** (`Unsupported catalog title identifier`) |
| T4/T5/T6 | Chaves `CUSA` sintéticas: **fonte importada** |
| T7 | `CUSA90004` → Store-R2 (`NPXS39041`): fonte, pesquisa e download OK; **instalação recusada** (`expected CUSA90004 got NPXS39041`) |

**Arquitetura corrigida:**

```text
catálogo (data/*.json) ─ titleId = ID REAL do pacote (CUSA…) ─ build ─ [contentId do PKG deve embutir o mesmo titleId] ─ .gssource
homebrew com ID que o parser recusa (NPXS, APOL…) ─► fora do catálogo ─► download direto (alternativa, comprovada para o Store-R2)
```

**Regras:**
1. O `titleId` do `.gssource` é sempre o ID real do pacote. Sem chaves sintéticas em produção (bloqueadas no `build`).
2. A identidade do PKG é verificada contra o catálogo antes de publicar (hoje: `contentId` declarado; Gate 3: leitura do cabeçalho do PKG).
3. Aceite de um item exige **as cinco etapas** no console: fonte importada → item encontrado → download concluído → PKG aceito → instalação concluída.
4. Cobertura é limitada a pacotes legalmente distribuídos cujo ID real é aceito pelo parser (`CUSA`). Homebrews `NPXS`/`APOL`: só download direto.
5. Updates e DLC: **não testados**; não prometer.

**Gate 2 (reaberto/encerrado):** importação e pesquisa comprovadas; instalação **só** comprovada para pacote com identidade compatível,
e esse caso ainda **não foi testado** (ver `docs/VALIDACAO_E2E.md`, pré-requisito do Gate 3).
