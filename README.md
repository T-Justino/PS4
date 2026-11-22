# PS4 Store BR

Catálogo pesquisável para o SSPI (PS4), com prioridade para PT-BR. Gera arquivos `.gssource` a partir de um catálogo canônico versionado. **Não hospeda nem baixa jogos.**

**Status:** Gate 1 auditado (`docs/AUDITORIA_GATE1.md`). Gate 2 concluído no console (SSPI 5.11.7 Final): `NPXS`/`APOL` recusados como chave; `CUSA99999` + link real importa e instala (T4, só aquele PKG). T5/T6 (chaves `CUSA9xxxx` distintas) instalaram no console (relato); riscos das chaves sintéticas em `docs/CHAVES_SINTETICAS.md`.

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

- `titleId` no padrão `AAAA00000` (sem `PPSA`), com `identityEvidence`. Prefixos `NPXS` e `APOL` são bloqueados (recusados pelo console). Placeholders (`*99999`, `*00000`) só com `"catalogKey": true`; nesse caso use `check --allow-placeholder`.
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
dist/                    .gssource gerados (T2, T3) para o Gate 2
docs/                    REVIEW, SDD_REVISADO, AUDITORIA_GATE1, TESTE_PS4
```

## Reprodução

O conteúdo é reproduzível; o **hash do ZIP pode variar** entre ambientes (o fluxo deflate depende do zlib). Compare pelo `contentSha256` impresso por `build`/`check`.

## Troubleshooting

- **SSPI rejeita a fonte:** fotografe a mensagem e compare com a tabela de `docs/TESTE_PS4.md`.
- **Atualizar uma fonte:** aumente `source.version` e reimporte. O refresh automático não está comprovado.
- **Rollback:** reimporte o `.gssource` anterior (os artefatos são reproduzíveis a partir do Git).
