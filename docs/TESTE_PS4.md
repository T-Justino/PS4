# Gate 2b — Teste manual no PS4 Pro 9.00 / GoldHEN / SSPI

## Resultado do Gate 2 (22/11/2026, foto do usuário)

T2 (`NPXS39041`) e T3 (`APOL00004`): **ambos recusados na importação** com
`Source couldn't be added — Static catalog: Unsupported catalog title identifier`.
Versão exibida na tela: **BETA 5.11 / 0eb783eca1f3** (não é a 5.11.7 Final).
Conclusão: o binário é mais restrito que o código público (que aceitaria os dois). Só `CUSA` está comprovado
(fixture original `CUSA99999`). Os arquivos T2/T3 foram movidos para `dist/rejected/` e o `build` agora os bloqueia.

## Resultado do Gate 2b (22/11/2026, relato do usuário)

**T4 foi instalado** pelo SSPI (BETA 5.11 / 0eb783eca1f3). Logo, no console: importação aceita, e a instalação de um PKG
com ID real `NPXS39041` sob a chave de catálogo `CUSA99999` funciona. O SSPI **não** exige que a chave bata com o ID do PKG.
Não foram relatados separadamente busca por nome/ID e detalhes (implícitos, pois a instalação parte deles).

**Regra comprovada:** chave de catálogo com prefixo `CUSA` + URL de download real = fluxo completo funcional.
`NPXS` e `APOL` como chave: recusados.

## Hipótese e teste (histórico)

O `titleId` do catálogo é só uma chave de busca; o fixture que funcionou usava `CUSA99999` (fictício) com o PKG do Apollo.
Teste T4 = o mesmo PKG do Store (download comprovado, 24,8 MB) sob a chave `CUSA99999`.

| Arquivo | Chave | contentSha256 (início) |
|---|---|---|
| `dist/ps4storebr-t4-cusa99999.gssource` | `CUSA99999` (fictícia, marcada `catalogKey`) | `24b41a5d…` |

## Passos

1. Baixe `dist/ps4storebr-t4-cusa99999.gssource` e copie para a raiz do pendrive (FAT32/exFAT).
2. SSPI → adicionar fonte → arquivo USB → selecione o arquivo.
3. Busque `store`, depois `CUSA99999`. Abra os detalhes (confira nome, tipo `base`, hoster PKG-Zone).
4. **Parte A (obrigatória): não instale.** Pare aqui.
5. **Parte B (opcional, só se A deu certo):** toque em Instalar. O Store já está instalado; reinstalar o mesmo PKG
   é o procedimento normal de atualização. Anote se o download inicia e se o SSPI reclama de ID incompatível.

## O que me enviar

```text
T4: importou [sim/não + erro] | busca nome [ok/vazio] | busca CUSA99999 [ok/vazio] | detalhes [ok/erro]
Parte B: instalar [não testei / baixou e instalou / erro: ____]
```

## Interpretação

| Resultado | Conclusão | Próximo passo |
|---|---|---|
| Importa e busca ok | Chave `CUSA` funciona como chave de catálogo | Adotar chave sintética `CUSA` + `contentId` real; seguir ao Gate 3 |
| Importa, mas busca vazia | Problema de normalização/`searchText` | Enviar o termo exato digitado |
| Erro de ID de novo | `CUSA99999` específico ou regra mais estrita | Testar `CUSA` com dígitos não-placeholder |
| Erro de outro tipo (formato) | Falta de `version` na linha do pacote | Gerar variante com `version` preenchida |
| B: erro de ID/conteúdo incompatível | O SSPI confere o ID do PKG com a chave | Só `CUSA` reais servem; rever o escopo |
