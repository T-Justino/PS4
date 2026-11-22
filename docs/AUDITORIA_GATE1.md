# Auditoria do Gate 1 — 22/11/2026

Escopo: assumir o projeto existente, sem reescrever. Nada do Gate 3+ foi implementado.

## Resultado

| Item | Resultado |
|---|---|
| Documentos (README, REVIEW, SDD 1.1, TESTE_PS4) | Lidos; consistentes entre si. |
| Testes | 50/50 originais passam (Python 3.11, 3.12 e 3.13). Com o teste novo: 51/51. |
| `check` nos `.gssource` de `dist/` | T2 e T3: **OK** (só aviso de prefixo não comprovado no binário, esperado). |
| `check` no fixture original | Falha de propósito: `CUSA99999` é placeholder bloqueado. Com `--allow-placeholder` passa. |
| Build reproduzível | **Sim, dentro de um mesmo ambiente** (3 versões de Python deram o mesmo hash aqui). |
| Bug crítico para o teste no PS4 | **Nenhum comprovado.** Nenhum código de geração foi alterado. |

## Diferença de hash do ZIP: causa e tratamento

**Fato verificado.** Rebuild do T2 deste ambiente: ZIP de 1438 B, sha256 `7d131922…`. O ZIP entregue no
pacote: 1448 B, sha256 `bc4376a2…`. Comparação:

- nomes e ordem das entradas: iguais;
- bytes **descomprimidos** dos 4 arquivos: iguais;
- cabeçalhos (data, flags, atributos): iguais;
- **só o fluxo deflate difere** (ex.: `source.json` comprimido = 501 B vs 494 B).

**Causa.** O fluxo deflate não é padronizado: depende da implementação do zlib (zlib, zlib-ng, zlib-cloudflare etc.)
e de sua versão. O mesmo nível de compressão gera bytes diferentes entre builds de zlib. Não é bug do projeto
nem do Python. Ambos os ZIPs são válidos e idênticos em conteúdo.

**Tratamento (mínimo).**
1. Manter Deflate: é o formato do fixture aceito pelo console. Trocar para STORED seria mudança não testada.
2. O `build` e o `check` agora imprimem e gravam `contentSha256` = sha256 do `source.json` descomprimido.
   Esse arquivo lista `size` e `sha256` de todos os demais, então o valor identifica o conteúdo inteiro
   e **é estável entre ambientes**.
3. Regra: compare artefatos pelo `contentSha256`, nunca pelo hash do ZIP.
4. Teste novo: `test_content_sha256_ignores_zip_compressor`.

Hashes de conteúdo de referência:

| Arquivo | contentSha256 |
|---|---|
| `ps4storebr-t2-npxs39041.gssource` | `e574eddbc96627d1f9219487cc851bebaaae8e9a8c9f79a880d7a567521512d1` |
| `ps4storebr-t3-apol00004.gssource` | `e3537c5cd6c54a71afddac451e777ce235b23c94eacdf2e3a8d1e17860222845` |

Se você já copiou para o pendrive os ZIPs do pacote original (`bc4376a2…` / `75a4b3c7…`), **pode usá-los**:
o conteúdo é o mesmo.

## Riscos residuais (não são bugs comprovados)

1. T2/T3 não têm `version` nas linhas de pacote; o fixture aceito tinha (`"version":"2.4.0"`). O código público
   trata como opcional, mas o binário não foi testado sem ele. Cobertura no Gate 2: se der erro que não seja de ID,
   a primeira variante a gerar é com `version` preenchida.
2. Aceitação de `NPXS` e `APOL` pelo binário: é justamente o que o Gate 2 mede.
3. `dist/*.report.json` marca compatibilidade como `NAO_TESTADO`. Correto até o relato do Gate 2.

## Atualização — resultado do Gate 2 (22/11/2026)

O console recusou T2 (NPXS) e T3 (APOL) na importação: `Unsupported catalog title identifier`. O rodapé
`BETA 5.11 / 0eb783eca1f3` é o rodapé do pacote público **5.11.7 Final** (correção do usuário). O commit `0eb783eca1f3` não está acessível
no GitHub (404) e o `main` público pode divergir do binário; por isso a regra real não pôde ser lida no código.
Mudanças: `NPXS`/`APOL` viram **erro** no `check`; fixtures movidas para `data/fixtures/rejected/`; novo campo
opcional `catalogKey: true` permite a chave fictícia `CUSA99999` (comprovada) como chave de catálogo; T4 gerado.
Os hashes de conteúdo de T2/T3 acima valem só como histórico.

## Gate 2b: T4 instalado (22/11/2026)

Relato do usuário: T4 foi "instalado". **Correção:** era a instalação da *fonte* (botão Install da lista USB). Comprovado: importação aceita com chave `CUSA`. Instalação do PKG: não provada.

## T7 (22/11/2026)

Instalação recusada: `Base game package · expected CUSA90004 got NPXS39041` (fonte, pesquisa e download OK). Chaves sintéticas abandonadas;
detalhes e regras vigentes em `docs/CHAVES_SINTETICAS.md` e `docs/SDD_REVISADO.md` §12.
