# Gate 3 — descoberta automática de links (MVP)

**Um comando:** `PYTHONPATH=src python3 -m ps4store run` (ou `ps4store run`). Descobre → verifica → gera o `.gssource`. Sem interface, sem banco, sem IA, sem VPS.

## Escolha da fonte

| Candidata | Resultado |
|---|---|
| **PKG-Zone** | **Não avaliável nesta sessão**: o proxy de rede bloqueou `pkg-zone.com` (HTTP 403 de política; não contornei). Não conheço índice oficial dele e os termos continuam sem revisão. **Não adotado.** Se você tiver um índice/feed oficial e permissão, o conector é um arquivo novo. |
| **API de Releases do GitHub** | **Adotada.** API pública e documentada (`GET /repos/{dono}/{repo}/releases`), feita para uso automatizado (limite de 60 req/h sem token; `GITHUB_TOKEN` opcional). Autorização = licença/release oficial do autor, registrada por fonte. |

**Limite desta sessão:** daqui só o repositório do projeto responde na API do GitHub (repositórios de terceiros dão 403 da política do ambiente). Portanto a fonte `apollo-releases` do `config/sources.json` **não foi executada com sucesso aqui** (aparece como erro no relatório e o robô segue). Na sua máquina ela deve listar o PKG do Apollo; o esperado, **não verificado**, é rejeição `PREFIX_REJECTED_BY_SSPI` (`APOL`).

## Como funciona

`config/sources.json` é uma **allowlist de fontes** (repositório + base de autorização + evidência); **não se cadastra nenhuma URL de arquivo**.

```text
fonte (repo) → API de releases → [descoberto]  cada .pkg de release publicada (sem rascunho/pré-release)
  → Range 0-64 KiB do link  → [acessível]       HTTPS, ≤5 redirects, sem IP privado, tamanho confere com o feed
  → cabeçalho + param.sfo   → [pkg verificado]  Content ID == TITLE_ID == CONTENT_ID; nome, versão, tipo lidos do PKG
  → regras do SSPI          → [compatível]      prefixo CUSA (único comprovado), não NPXS/APOL, não placeholder, tipo "base"
  → TLS + autorização       → [publicado]       host não listado como falho no console; autorização da fonte
publicado → catálogo canônico (data/generated/auto-catalog.json) → compile_catalog → check → dist/auto/ps4storebr-auto.gssource
```

- **Nunca baixa o pacote inteiro** (uma requisição `Range` de 64 KiB; o corpo lido é limitado). Não calcula nem inventa `sha256`.
- **Identidade vem do próprio PKG**, não do nome do arquivo nem do feed. O `size` publicado é o do servidor.
- **Novo** = chave `fonte#release#asset` ausente do estado (`data/state/discovery-state.json`, um JSON versionável; não é banco).
- **Versão do catálogo** (`1.0.N`) sobe só quando o conteúdo muda, para o SSPI aceitar a reimportação. Execução sem mudança gera artefato idêntico.
- **Sem entrada publicável**, o artefato anterior é mantido. Uma fonte fora do ar não derruba as outras.
- Motivos de rejeição: `UNREACHABLE`, `NOT_FILE`, `SIZE_MISMATCH`, `NOT_PKG`, `SFO_OUTSIDE_WINDOW`, `BAD_SFO`, `IDENTITY_MISMATCH`, `PREFIX_REJECTED_BY_SSPI`,
  `PREFIX_UNPROVEN`, `PLACEHOLDER_ID`, `KIND_UNTESTED` (update/DLC), `NOT_HTTPS`, `TLS_HOST_BLOCKED`.

Opções: `--config`, `--out-dir` (padrão `dist/auto`), `--canonical`, `--state`, `--dry-run` (não grava nada).

## Achados reais que mudam o resultado (decisão sua)

1. **TLS:** `config/sources.json` lista `github.com` como host que falhou no SSPI (`0x8095F00C`, seu relato). Como os downloads de Releases do GitHub usam `github.com`, **o robô descobre e verifica esses links, mas não os publica** (`TLS_HOST_BLOCKED`) enquanto essa política valer. Se o T8 mostrar que o host funciona, mude `tls.known_bad_hosts` (ou `tls.enforce`) e rode de novo. É dado, não código.
2. **IDs:** a maioria dos homebrews tem IDs que o importador recusa (`NPXS`, `APOL`…). Eles ficam no relatório como `PREFIX_REJECTED_BY_SSPI`. Só pacotes com ID `CUSA` real entram.
3. **"Compatível" = regras conhecidas.** A instalação sob essas regras ainda **não foi comprovada** no console (T8 pendente).

## Evidências

**Testes:** `tests/test_gate3.py` (16 testes) e `tests/test_gate1.py`/`test_t8.py`: **99 passam**. Cobrem: descoberta de release nova sem URL cadastrada e versão que sobe; a escada
descoberto → acessível → verificado → compatível → publicado com 12 casos de rejeição (HTML, binário não-PKG, 404, tamanho divergente, ID divergente, NPXS, APOL, prefixo não comprovado,
placeholder, update, host TLS bloqueado); autorização obrigatória; falha isolada por fonte; artefato anterior preservado; `--dry-run`; comando único;
e rede real em servidor HTTP local (Range 206, servidor que ignora Range, redirects, 404, limite de 64 KiB, bloqueio de http/loopback/IP privado, token da API nunca enviado a hosts de download).

**Execução ao vivo (rede real), nesta sessão:**
```text
fonte own-releases (T-Justino/PS4): ok          ← API real do GitHub respondeu; o repositório ainda não tem releases
fonte apollo-releases (bucanero/apollo-ps4): erro — HTTP 403 em api.github.com   ← bloqueio de política desta sessão (reportado, robô segue)
descobertos=0 ... catálogo NÃO atualizado: nenhuma entrada publicável (artefato anterior mantido)
```
(Relatório gravado em `dist/auto/discovery.report.md`.)

**Execução de ponta a ponta com um feed simulado** (mesmo formato JSON da API do GitHub, PKGs reais derivados do T8, config com **só o repositório**). *Não é uma fonte de terceiros ao vivo.*
O autor "publica" a release v2.0 entre as execuções 1 e 2:

```text
======== EXECUÇÃO 1 (feed com a release v1.0) ========
fonte src-a (acme/app): ok
descobertos=1 acessíveis=1 pkg_verificados=1 compatíveis=1 publicados=1 novos=1 rejeitados=0
  NOVO publicado        store-br-test-1.0.pkg (v1.0) → CUSA95417
catálogo atualizado: dist/auto/ps4storebr-auto.gssource v1.0.1

>>> O autor publica a release v2.0 (3 novos .pkg). Ninguém cadastra nada. <<<

======== EXECUÇÃO 2 ========
fonte src-a (acme/app): ok
descobertos=4 acessíveis=3 pkg_verificados=3 compatíveis=2 publicados=2 novos=3 rejeitados=2
  NOVO publicado        outro-app-2.0.pkg (v2.0) → CUSA95418
  NOVO pkg_verificado   intruso.pkg (v2.0) → rejeitado PREFIX_REJECTED_BY_SSPI: prefixo NPXS recusado na importação (Gate 2)
  NOVO descoberto       quebrado.pkg (v2.0) → rejeitado UNREACHABLE: HTTP 404
       publicado        store-br-test-1.0.pkg (v1.0) → CUSA95417
catálogo atualizado: dist/auto/ps4storebr-auto.gssource v1.0.2

======== EXECUÇÃO 3 (sem mudanças) ========
fonte src-a (acme/app): ok
descobertos=4 acessíveis=3 pkg_verificados=3 compatíveis=2 publicados=2 novos=0 rejeitados=2
       publicado        outro-app-2.0.pkg (v2.0) → CUSA95418
       pkg_verificado   intruso.pkg (v2.0) → rejeitado PREFIX_REJECTED_BY_SSPI: prefixo NPXS recusado na importação (Gate 2)
       descoberto       quebrado.pkg (v2.0) → rejeitado UNREACHABLE: HTTP 404
       publicado        store-br-test-1.0.pkg (v1.0) → CUSA95417
catálogo atualizado: dist/auto/ps4storebr-auto.gssource v1.0.2
```
O `.gssource` final passou no `check` (`conteúdo sha256 67dfd5af…`, títulos `CUSA95417` e `CUSA95418`; o `NPXS39041` e o link 404 ficaram só no relatório).

## Para ver o robô detectando algo novo ao vivo

Publique uma Release com um `.pkg` no seu repositório (ou me autorize a criar uma com o PKG do T8, o que é uma ação pública sua) e rode o comando. Com `github.com` na lista de TLS ruim, o robô vai reportar `TLS_HOST_BLOCKED` em vez de publicar: o objetivo é só provar a descoberta; ajuste `tls` para publicar.

## Fora do escopo (não feito)

Hospedagem/CI agendado, mais conectores, atualizações e DLC, PT-BR, interface.
