# PS4 Store BR

Catálogo pesquisável para o SSPI (PS4), com prioridade para PT-BR. Gera arquivos `.gssource` a partir de um catálogo canônico versionado. **Não hospeda nem baixa jogos.**

**Status:** Gate 1 auditado (`docs/AUDITORIA_GATE1.md`). Gate 2 concluído no console (SSPI 5.11.7 Final): `NPXS`/`APOL` recusados como chave; chaves `CUSA` sintéticas (T4–T7): fonte importada, mas **instalação recusada** (T7) (`docs/TESTE_PS4.md`, `docs/CHAVES_SINTETICAS.md`). **T7: instalação recusada** (`expected CUSA90004 got NPXS39041`): chaves sintéticas abandonadas. Próximo: **T8**, app próprio `CUSA95417` com identidade compatível (`docs/TESTE_T8.md`; ainda não testado no console).

## Gate 3 (MVP): descoberta automática

```bash
PYTHONPATH=src python3 -m ps4store run     # descobre → verifica links (Range) → gera dist/auto/ps4storebr-auto.gssource + relatório
```
**Estado do MVP:** ciclo descoberta → catálogo → importação → download → instalação → execução **comprovado no PS4 Pro 9.00 para o app próprio** (T8b, 22/11/2026; o T8 original abria com erro por falta de `sce_module`, corrigido). Workflow do GitHub Actions executado com sucesso (descobriu a v1.02 sozinho e atualizou a fonte para 1.0.4); falta provar no console a importação por URL e a atualização (T9, `docs/USO_NO_PS4.md`). Não garante compatibilidade universal. Fontes reais: PKG-Zone (prova de descoberta; 0 publicáveis sem autorização) e pasta autorizada do próprio repositório (ciclo descoberta → catálogo gerado; instalação pendente do T8/T9). Ver `docs/GATE3.md`.

## Uso

Python ≥ 3.11, sem dependências de runtime.

```bash
pip install -e '.[test]'      # ou: export PYTHONPATH=src
pytest -q
python -m ps4store build data/fixtures/t2-npxs39041-store-r2.json \
       -o dist/ps4storebr-t2-npxs39041.gssource --report dist/ps4storebr-t2-npxs39041.report.json
python -m ps4store check dist/ps4storebr-t2-npxs39041.gssource
```

O `build` valida o canônico, compila, roda o `check` e só grava se tudo passar (escrita atômica). O exit code é 1 em qualquer erro.

## Regras do canônico (`data/*.json`, schema `ps4storebr.catalog/v1`)

- `titleId` = **ID real do pacote** (`AAAA00000`, sem `PPSA`), com `identityEvidence`. `NPXS`/`APOL` são bloqueados (o console recusa a importação). Chaves sintéticas e placeholders são bloqueados (T7: a instalação é recusada). Se o pacote declara `contentId`, ele deve embutir o mesmo `titleId`.
- Pacote sem `authorization.evidence` **não é publicado**. Título sem pacote publicável fica fora do `.gssource` e aparece no relatório.
- `languages.audioPtBr` / `subtitlesPtBr` ∈ `yes|no|unknown`. `yes` exige `evidence` e adiciona termos de busca `ptbr dublado/legendado`.
- URLs somente `https://`, sem credenciais, sem IP literal nem host local.
- RAR multipartes desativado até o Gate 5.

## Estrutura

```text
src/ps4store/sspi.py     regras do formato .gssource + validador (check)
src/ps4store/catalog.py  modelo canônico + políticas
src/ps4store/build.py    compilador determinístico + ZIP reproduzível
src/ps4store/cli.py      build / check
data/fixtures/           fontes de teste reais (T2, T3)
tests/fixtures/          .gssource aceito pelo console (contrato de formato; ID fictício, não reutilizar)
dist/probes/             sondas históricas T4–T7 (não são produção)
dist/t8/                 PKG e .gssource do T8 (app próprio)
app/                     app de teste (OpenOrbis), build.sh e verify_pkg.py
docs/                    REVIEW, SDD_REVISADO, AUDITORIA_GATE1, TESTE_PS4
```

## Reprodução

O conteúdo é reproduzível; o **hash do ZIP pode variar** entre ambientes (o fluxo deflate depende do zlib). Compare pelo `contentSha256` impresso por `build`/`check`.

## Troubleshooting

- **SSPI rejeita a fonte:** fotografe a mensagem e compare com a tabela de `docs/TESTE_PS4.md`.
- **Atualizar uma fonte:** aumente `source.version` e reimporte. O refresh automático não está comprovado.
- **Rollback:** reimporte o `.gssource` anterior (os artefatos são reproduzíveis a partir do Git).
