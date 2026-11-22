# dist/: artefatos gerados

| Pasta | Conteúdo | Uso |
|---|---|---|
| `auto/ps4storebr-auto.gssource` | **catálogo de produção**, atualizado pelo workflow (`catalogo.yml`) | é o que o PS4 importa por URL (`docs/USO_NO_PS4.md`) |
| `t8b/` | fontes do T8b/T9 preservadas (v1.0.2 = PKG v1.00; v1.0.3 = v1.01; v1.0.4 = v1.02) | testes no console; fixas, não mudam |
| `t8/` | **T8 original**: PKG defeituoso + fonte, só diagnóstico (`LEIA-ME-DEFEITUOSO.md`) | não usar |
| `probes/` | sondas históricas T4–T7 (chaves sintéticas, abandonadas) | histórico; só reproduzíveis com `--allow-synthetic-probe` |
| `rejected/` | T2/T3 (`NPXS`/`APOL` como chave, recusados pelo console) | histórico |

`auto/discovery.report.*` é o último relatório gerado localmente (o workflow publica o relatório no *Summary* do job, não no Git). PKGs ficam em `pkgs/` (fonte monitorada), não aqui.
