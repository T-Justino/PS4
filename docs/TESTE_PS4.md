# Gate 2 — Testes manuais no PS4 Pro 9.00 / GoldHEN / SSPI 5.11.7

## Resultado do Gate 2 (22/11/2026, foto do usuário)

T2 (`NPXS39041`) e T3 (`APOL00004`): **ambos recusados na importação** com
`Source couldn't be added — Static catalog: Unsupported catalog title identifier`.
O rodapé `BETA 5.11 / 0eb783eca1f3` é o do pacote público **5.11.7 Final**.
Conclusão: o binário é mais restrito que o código público (que aceitaria os dois). Só `CUSA` está comprovado
(fixture original `CUSA99999`). Os arquivos T2/T3 foram movidos para `dist/rejected/` e o `build` agora os bloqueia.

## Resultado do Gate 2b (22/11/2026, relato do usuário)

**T4 foi instalado** pelo SSPI 5.11.7. O que isso comprova, e só isso: **aquele PKG** (PKG-Zone Store-R2, ID real `NPXS39041`),
listado sob a chave `CUSA99999`, foi importado e instalado **nesta versão do SSPI**. **Não** comprova o mesmo para outros
PKGs, jogos, atualizações, DLCs, nem para outras chaves.
Não foram relatados separadamente busca por nome/ID e detalhes (implícitos, pois a instalação parte deles).

**Observação:** o código público do SSPI (`main`) prevê rejeitar um PKG cujo content ID não bate com a chave
(`Package does not belong to …`). O T4 não foi rejeitado, então o binário se comporta diferente do código público
nesse ponto, ou aquele PKG segue outro caminho. **Causa desconhecida; não generalizar.** Detalhes: `docs/CHAVES_SINTETICAS.md`.

`NPXS` e `APOL` como chave: recusados na importação.

## Resultado de T5 e T6 (22/11/2026, relato do usuário)

O usuário relatou que **T5 e T6 funcionaram e foram instalados** (SSPI 5.11.7). Não foi detalhado: o botão do Store no T5
(`Install`/`Open`), qual item do T6 foi instalado (o download do Apollo falhava por TLS), nem o teste opcional de duplicação.
Comprovado, no relato: chaves `CUSA90001`, `CUSA90002` (e `CUSA90003`) importam e instalam. Continua valendo: vale só para
esses PKGs e essa versão do SSPI; updates, DLC, biblioteca e duplicação seguem **não testados**.

## Arquivos (pasta `dist/`)

| Teste | Arquivo | Chaves | contentSha256 (início) |
|---|---|---|---|
| T5 | `ps4storebr-t5-cusa90001.gssource` | `CUSA90001` → Store | `2cf0adc7…` |
| T6 | `ps4storebr-t6-two-titles.gssource` | `CUSA90002` → Store, `CUSA90003` → Apollo | `8598a27c…` |

As chaves são sintéticas (faixa `CUSA90000–98999` reservada pelo projeto) e o ID real de cada pacote fica só no
canônico/relatório (`identityMap`), nunca no `.gssource`. **Nesta rodada não instale nada.** (O download do Apollo falha por TLS.)

## Preparação

Copie os dois arquivos para a raiz do pendrive. Importe **um por vez**; antes de cada importação remova do SSPI
qualquer fonte de teste anterior (T4, T5), para não misturar resultados.

## T5 (chave diferente de CUSA99999)

1. Importe `T5`. Anote: importou? (erro exato/foto se não).
2. Busque `store`, depois `CUSA90001`.
3. Abra os detalhes: nome, tipo `base`, hoster PKG-Zone.
4. **Observe o botão do item:** `Install` ou `Open`? (o Store já está instalado no console). Não toque.
5. Remova a fonte T5.

## T6 (dois títulos)

1. Importe `T6`. Importou?
2. Busque `store` → deve aparecer só o Store. Busque `apollo` → só o Apollo. Busque `CUSA90002` e `CUSA90003` → um item cada.
3. Busque `teste t6` → devem aparecer **os dois**.
4. Abra os detalhes de cada um: o nome/hoster/link de um não pode aparecer no outro.
5. Opcional (duplicação): com T6 ainda importado, importe também T5. Busque `store`: **quantas entradas** de Store aparecem (esperado: 2)?

## O que me enviar

```text
T5: importou [sim/não + erro] | busca nome [ok/vazio] | busca CUSA90001 [ok/vazio] | detalhes [ok/erro] | botão: [Install/Open]
T6: importou [sim/não + erro] | store [só Store/outro] | apollo [só Apollo/outro] | CUSA90002 [ok] | CUSA90003 [ok] | "teste t6" [2 itens/outro] | detalhes sem cruzamento [sim/não]
Extra (opcional): store com T5+T6 → [N] entradas
```

## Interpretação

| Resultado | Conclusão | Próximo passo |
|---|---|---|
| T5 e T6 ok | Chaves `CUSA9xxxx` distintas importam e pesquisam sem conflito | Definir estratégia de identificação (docs/CHAVES_SINTETICAS.md) |
| T5 erro de ID | Só `CUSA99999` passa, ou há lista de chaves | Testar outra faixa (ex.: `CUSA0xxxx`) |
| T6 mistura/duplica itens | Conflito de chaves/shard | Investigar `packages/items.json` |
| Botão `Open` no T5 | SSPI associa o item ao instalado de algum modo | Registrar; impacta biblioteca/atualização |
| Botão `Install` no T5 | Chave sintética não associa ao NPXS instalado (esperado pelo código público) | Registrar; atualizações de homebrew não serão detectadas |
