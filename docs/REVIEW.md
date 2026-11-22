# REVIEW — PS4 Store BR (Gate 0)

**Data:** 21/11/2026 · **Base:** `SDD_PS4_Store_BR_v1.md` v1.0 · **Resultado:** `docs/SDD_REVISADO.md` v1.1

Legenda: **[F]** fato verificado (com fonte) · **[H]** hipótese a testar · **[D]** decisão tomada.

---

## 1. Fontes examinadas

| Fonte | O que foi extraído |
|---|---|
| `SSPI_Teste_Homebrew_Compat_5117.gssource` (fornecido; importado e pesquisado com sucesso no PS4 9.00 / SSPI 5.11.7) | Schema real e mínimo aceito pelo binário: 4 arquivos, nomes, ordem de chaves, campos e serialização JSON compacta. **Referência primária.** |
| `app/PackageSourceEngineStatic.cs` (GitHub, `main`) | Limites, regex de ID, campos opcionais, regras de consistência e mensagens de erro. **Referência secundária**: pode diferir do binário. |
| Guia `xyhlo.github.io/SSPI` | `.gssource` = ZIP ≤ 4 MiB, só declarativo; 3 engines; RAR/7z; sem documentação do `catalog.json`. |

## 2. Contrato `.gssource` confirmado

**[F] Pelo fixture real** (4 entradas Deflate, nesta ordem):

```text
source.json          {"schema":"gamesearch.source/v1","id","name","description","version",
                      "engine":{"type":"embedded-catalog-v1","entryFile":"catalog.json"},
                      "capabilities":["titles.search","titles.catalog","packages.resolve"],
                      "files":[{"path","size","sha256"}...]}   # não lista a si mesmo
catalog.json         {"format":"embedded-catalog-v1","formatVersion":1,
                      "searchNormalization":"nfkd-lower-alnum-spaces-v1",
                      "indexFiles":[...],"packageFiles":[...],
                      "counts":{"titles","readyTitles","releases","multipartGroups","unresolved"}}
index/titles.json    {"titles":[{"titleId","name","packagesFile","releaseCount","kinds","searchText"}]}
packages/items.json  {"titles":{"<ID>":[{"id","titleId","kind","accessType","url","hoster",
                      "label","sourcePageUrl","version"}]}}
```

`size`/`sha256` em `source.json` são calculados sobre os bytes **descomprimidos**. Os hashes do fixture conferem.

**[F] Pelo código público** (não validado no binário): título `^[A-Z]{4}\d{5}$` sem prefixo `PPSA`; `kind` ∈ {base, update, dlc, unknown, backport}; `accessType` ∈ {Direct, HosterLanding}; ≤ 30.000 títulos; ≤ 500 títulos por página de índice; shard ≤ 1.500.000 B; JSON ≤ 2 MiB; índice total ≤ 8 MiB; `source.json` ≤ 256 KiB e ≤ 63 arquivos; ≤ 62 arquivos de índice e ≤ 62 shards; versão com 2–4 componentes numéricos; engine estático não pode declarar origem de rede; `releaseCount` igual ao número de linhas do shard; todo título indexado precisa de ≥ 1 pacote; contagens precisam bater; ≥ 1 título pronto.

## 3. Problemas encontrados (em ordem de prioridade)

1. **[F] Divergência de ID entre código público e binário.** `APOL00004` casa com o regex público, mas o console o rejeitou com `Unsupported catalog title identifier`. Ou o binário 5.11.7 é mais restrito (ex.: lista de prefixos), ou a rejeição teve outra causa no catálogo antigo. **[H]** O binário aceita apenas certos prefixos. *Impacto:* é o maior risco do projeto, porque homebrew usa IDs fora de `CUSA`. *Ação:* Gate 2 testa `NPXS39041` e `APOL00004` em fontes separadas.
2. **[F] O SSPI não exibe título sem pacote.** Todo título indexado precisa de ≥ 1 linha de pacote. *Consequência para a decisão 3:* metadados de jogos comerciais **sem link autorizado não entram no `.gssource`**. Ficam no JSON canônico e no relatório. O SDD v1 não previa isso.
3. **[F] O schema não tem campo de idioma.** PT-BR só pode aparecer via `name`, `label` ou `searchText`. *[D]* Só termos de busca (`ptbr`, `dublado`, `legendado`) e só com evidência. O filtro nativo PT-BR fica fora do MVP.
4. **[F] O link do fixture original (GitHub) falha TLS no SSPI.** Por isso o Apollo serve só como **teste de ID**, não de download.
5. **[H] Refresh (`embedded-catalog-refresh-v1`) não comprovado.** O engine estático proíbe origem de rede. *[D]* MVP = reimportar a fonte com `version` maior. Refresh vira spike pós-Gate 4.
6. **[F] Versão.** O README atual menciona a 5.11.7 Final (correção do usuário aceita). Um resumo anterior citava 5.10 beta. Isso não muda a premissa de que o código público não é necessariamente o binário.
7. **[H] Fonte pkg-zone.** O link `Store-R2.pkg` é a distribuição pública do próprio PKG-Zone e foi observado funcionando no console. **Os termos de uso para listagem por terceiros ainda não foram revisados.** Para fixture de teste pessoal o risco é baixo; para publicação, confirmar antes do Gate 3.
8. **[F] Sem fixture para RAR, refresh, múltiplos shards ou nomes acentuados.** Tudo isso ainda depende de teste no console.

## 4. Ambiguidades do SDD v1 e resoluções

| Item | Resolução |
|---|---|
| "Gerador compatível com o binário" sem schema | **[D]** O fixture real é o contrato. O código público fornece só limites e regras. Divergências vão para a seção 3. |
| Status `SSPI_TESTED` em validação de link | **[D]** Só é marcado manualmente, com relato do usuário. Nunca é automático. |
| `httpx` vs `requests`, `pydantic` | **[D]** Gate 1 sem dependências de runtime (stdlib). Cliente HTTP só no Gate 3. |
| YAML vs JSON | **[D]** Só JSON (stdlib, diff legível). |
| 5 comandos de CLI | **[D]** Gate 1 tem 2: `build` (que valida internamente) e `check`. `discover` e `report` entram no Gate 3. |
| Título comercial sem link | **[D]** Fica no canônico com `packages: []` ou pacotes sem autorização. É excluído do `.gssource` com motivo no relatório de build. |
| "Qualquer jogo" | **[D]** Fora de promessa. A cobertura de instalação depende de fontes autorizadas reais. A infraestrutura é agnóstica ao tipo de jogo. |

## 5. Decisões do usuário registradas (21/11/2026)

1. Manter o PS4 Store BR com arquitetura agnóstica ao tipo de jogo.
2. Usar homebrews autorizados como fixtures de importação, busca, download e instalação.
3. Aceitar metadados de jogos comerciais, mas sem publicar links sem autorização ou acesso legítimo.
4. Conectores independentes, começando por fontes verificadas.
5. Descoberta e validação automatizadas, sem IA obrigatória e sem VPS com jogos.
6. Python + GitHub Actions + hospedagem estática, condicionados a prova.
7. MVP simplificado.

## 6. Arquitetura mínima viável

```text
data/*.json (canônico, revisado no Git)
   └─ ps4store build ─► valida canônico ─► serializa ─► check (regras SSPI) ─► dist/*.gssource
                                                     └─► relatório (excluídos + motivo)
USB ─► SSPI no PS4 ─► download direto na origem
```

Gate 3 acrescenta `adapters/` + verificação HEAD/Range. Gate 4 acrescenta Actions + Pages, e só depois de provar o HTTPS do domínio no SSPI.

## 7. Fontes legítimas, links e PT-BR (Gate 3+)

- **Allowlist** `config/sources.json` com `permission_evidence` (licença, termo ou e-mail de autorização) e `allowed_hosts`.
- **Candidatas:** GitHub Releases de homebrew com licença livre (bloqueadas por TLS no SSPI; requerem mirror autorizado pelo autor), PKG-Zone (após revisão dos termos), demos e conteúdo gratuito somente se houver URL pública legítima, o que é raro para PS4.
- **Link:** HEAD → `Range: bytes=0-31` com teto, timeout, ≤ 5 redirects, só HTTPS, bloqueio de IP privado. Confere o magic PKG `7F 43 4E 54` (`\x7FCNT`). HTML → `NOT_FILE`. Status: `HTTP_REACHABLE` / `FILE_CANDIDATE` / `AUTH_REQUIRED` / `UNAVAILABLE` / `TLS_ERROR` / `UNKNOWN`. `SSPI_TESTED` é manual.
- **PT-BR:** `audioPtBr` / `subtitlesPtBr` ∈ {yes, no, unknown}. `yes` exige `evidence` (URL ou referência). Sem evidência, o build falha.

## 8. Plano incremental

| Gate | Entrega | Aceite |
|---|---|---|
| **1** (este) | Gerador, validador, CLI, testes, 2 fixtures reais | `pytest` verde; build reproduzível byte a byte; `check` aceita o fixture original e os gerados |
| **2** | Teste manual no PS4 | Usuário importa T2/T3, busca pelo nome e pelo ID e abre os detalhes; **sem instalar**; relato com foto |
| **3** | 1 adaptador autorizado + verificação de links + relatório | Entradas novas sem mudar código; link inválido não fica instalável |
| **4** | Actions + Pages + rollback | HTTPS do catálogo comprovado no SSPI; caso contrário, USB oficial |
| **5** | Spike de RAR multipartes | Ciclo comprovado com fixture pequena |
| **6** | UI própria | Fora do MVP |

## 9. Perguntas bloqueantes

Nenhuma para o Gate 1. Para o Gate 2 basta o resultado do teste.

## 10. Limitações desta revisão

- O código C# foi lido via resumo da página, não compilado nem executado. Os limites numéricos exigem conferência linha a linha antes de qualquer catálogo grande.
- Nenhum link foi verificado pela rede neste ambiente.
- **Nada aqui afirma compatibilidade com o console.**
