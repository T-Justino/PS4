# Chaves sintéticas de catálogo — investigação (Gate 2, antes do Gate 3)

**Escopo da evidência.** T4 (`CUSA99999` + Store-R2.pkg, real `NPXS39041`) importou e instalou no SSPI 5.11.7.
Isso vale **só para aquele PKG e aquela versão**. Nenhuma generalização para outros PKGs, jogos, updates ou DLCs.

**Fonte desta análise.** Código público `xyhlo/SSPI` (`main`): `PkgValidator.cs`, `PkgInstaller.cs`, `InstalledTitleScan.cs`.
O commit do binário (`0eb783eca1f3`) não está acessível, então o `main` pode divergir. É **leitura de código, não teste**.
O T4 já contradiz uma previsão do código (item 1), então tudo abaixo é hipótese a confirmar no console.

## Regra de projeto

- **Chave de catálogo** (`titleId` no `.gssource`, `CUSA90000–98999`) é só um índice de busca. É sintética.
- **Identidade real** (`realIdentity.titleId`/`contentId`) fica no canônico e no relatório (`identityMap`). Nunca vira `titleId`
  do `.gssource` (`NPXS`/`APOL` são recusados) e **não** é gravada nas linhas de pacote nesta fase.
- `CUSA99999` só existe como sonda (`probe: true`), nunca como identidade de produção.
- A faixa reservada é suposição (não dá para provar que nenhum jogo oficial a usa).

## Efeitos possíveis (hipóteses)

| Área | O que o código público indica | Risco | Como verificar |
|---|---|---|---|
| Instalação (base) | `CheckRequestedIdentity` compara a chave com o content ID do PKG (`Package does not belong to …`). T4 passou, contrariando isso | Outro PKG pode ser recusado | Só testando cada PKG; T4 não basta |
| Biblioteca / botão Open | Homebrew é identificado pelo próprio ID instalado (`IsHomebrew`: não-CUSA). Uma chave `CUSA` não casa com `NPXS39041` instalado | Item pode aparecer como `Install` mesmo instalado | T5, passo 4 |
| Atualizações | Update exige base instalada sob a chave (`sceAppInstUtilAppExists(titleId)`) e compara content ID com o `param.sfo` instalado | Update de homebrew sob chave sintética tende a falhar (`requires installed base game`) | Fora do escopo do T5/T6; testar antes de prometer updates |
| DLC | `GameAcceptsAddon` lê `appmeta/<CUSA>/param.sfo` do jogo instalado | Chave sintética nunca tem `param.sfo`: DLC não associa | Testar com DLC autorizado antes de suportar |
| Jogos instalados | Chave `CUSA` real colidiria com um jogo instalado | Falsa associação | Faixa `9xxxx` reservada + chave única por título |
| Duplicação | Mesmo pacote sob duas chaves = duas entradas | Lista duplicada | O build recusa a mesma `realIdentity` em duas chaves na mesma fonte; T6 passo 5 mede entre fontes |

## Decisão pendente (após T5/T6)

Escolher a estratégia definitiva de identificação (chave sintética estável por pacote x outra) com os resultados do console.
Não implementar descoberta automática até lá.
