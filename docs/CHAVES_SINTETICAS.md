# Chaves sintéticas de catálogo — ABANDONADAS (decisão de 22/11/2026)

**Resultado que decidiu (T7).** Com a fonte importada, o item pesquisado e o download concluído (24,8 MB), a instalação foi
bloqueada: `Base game package · expected CUSA90004 got NPXS39041`. O SSPI 5.11.7 confere a chave do catálogo com o ID interno do PKG.

## Linha do tempo (o que cada teste provou)

| Teste | Chave → PKG | Provou | Não provou |
|---|---|---|---|
| T2/T3 | `NPXS39041` / `APOL00004` como chave | **Importação recusada** (`Unsupported catalog title identifier`) | — |
| T4/T5/T6 | `CUSA99999`, `CUSA90001`, `CUSA90002/3` | **Importação** de fontes com chave `CUSA` | Instalação (o "Install" visto era o da fonte) |
| T7 | `CUSA90004` → Store-R2 (`NPXS39041`) | Fonte, pesquisa e download OK; **instalação recusada por identidade** | — |

**Importar uma fonte com sucesso NÃO garante que o pacote seja instalável.** Aceitação do catálogo e aceitação do pacote são
verificações diferentes, feitas em momentos diferentes.

## Regras vigentes

1. O `titleId` do catálogo deve ser o **ID real do pacote**, com prefixo aceito pelo parser (comprovado: `CUSA`; recusados: `NPXS`, `APOL`).
2. Se o pacote declara `contentId`, o `build` exige que o ID embutido nele seja igual ao `titleId` (o SSPI faria a mesma conferência).
3. Chaves sintéticas (`catalogKey`, `probe`, `realIdentity`) são **bloqueadas** no `build`; só `--allow-synthetic-probe`
   reproduz as sondas históricas T4–T7 (`data/fixtures/probes/`, `dist/probes/`), que **não** são produção.
4. **Homebrews cujos IDs o parser recusa** (`NPXS`, `APOL`, …) **ficam fora do catálogo**. Alternativa: download direto
   (link na documentação, instalação pelo SSPI/gerenciador de downloads), como já foi feito com o Store-R2.
5. Não alterar o PKG nem seu ID interno.

## Hipóteses do código público que o T7 confirmou ou deixou abertas

- **Confirmado:** a conferência chave × ID do PKG existe na instalação (`TitleMismatch: expected … got …`).
- **Aberto (sem teste):** atualizações e DLC. O código público exige base instalada sob a chave e o `param.sfo` do jogo para DLC; com IDs reais
  de jogos oficiais isso é plausível, mas precisa de teste próprio.
- **Aberto:** botão Open/Install para itens já instalados com ID real; duplicação entre fontes.
