# Versões CUSA por jogo (Etapa 5B)

Módulo independente `src/ps4store/versoes.py` + dados em `data/versoes-cusa.json` (JSON local, stdlib, Termux). **Só metadados de versão**: não resolve links, não baixa nada, e um CUSA **não indica** que exista PKG ou download.

## Modelo
Cada registro liga um **Q-id do Wikidata** (o mesmo `idFonte` do índice de busca) a **um CUSA**. O mesmo jogo pode ter vários registros (vários CUSA, vários Content IDs/edições).
Campos: `qid`, `jogo` (só rótulo de exibição), `cusa`, `contentId`, `edicao`, `versao`, `regiao {codigo, prefixo, base}`, `idiomas` + `idiomasBase`, `lojas`, `status` (`citado`|`confirmado`), `evidencias [{fonte, tipo, url, obtidoEm, afirma[], trecho?}]`, `nota`.
Regras (validadas em teste):
- O vínculo jogo↔CUSA é **sempre o Q-id explícito**, nunca semelhança de nomes (nomes iguais com outro Q-id não herdam nada).
- **Cada campo não nulo precisa de uma evidência que o afirme** (`afirma`). O que não é sustentado fica `null` = **desconhecido** e é mostrado como "desconhecido".
- **Região não determina idioma**: `idiomas` só entra com evidência própria e `idiomasBase` dizendo o que ela diz e o que não diz. Um registro de região US sem evidência de idioma continua com idiomas desconhecidos.
- `regiao.codigo` precisa bater com o prefixo do Content ID (UP→US, EP→EU, JP, HP→ASIA, KP→KR; convenção da Sony, só vale com o Content ID evidenciado).
- Filtro por campo desconhecido **não casa** (o valor não é presumido) e o comando informa quantos registros ficaram de fora.

## Dados reais incluídos: Batman: Arkham Knight (3 registros)
| CUSA | Content ID | Edição | Região | Idiomas | Fonte |
|---|---|---|---|---|---|
| CUSA00133 | `UP1018-CUSA00133_00-B000000000001563` | Premium Edition | US (prefixo UP; lojas en-us/en-ca) | desconhecidos | páginas da PlayStation Store |
| CUSA00135 | `EP1018-CUSA00135_00-BAKPREMIUMED0000` | Premium Edition | EU (prefixo EP; loja en-ie) | desconhecidos | página da PlayStation Store |
| CUSA00133 | `UP1018-CUSA00133_00-ASIA000000000003` | Premium Edition | **desconhecida** (lojas en-id/en-hk, mas prefixo UP) | English, Korean (título da listagem; não diz se áudio/texto) | páginas da PlayStation Store |

**Limites honestos:**
- `status = citado`: as URLs oficiais da loja apareceram em resultado de busca em 22/11/2026 e **eu não consegui abrir as páginas** (a loja não é alcançável do ambiente de desenvolvimento). O Content ID está na própria URL; título/edição vêm do título da página nos resultados. **Abra os links no navegador do Android e use `--confirmar`** para marcar como `confirmado`.
- **Não há registro do jogo-base**: nenhuma fonte verificável do CUSA do disco/jogo-base foi encontrada. Uma planilha de usuário (Scribd) associa CUSA00135 ao jogo-base e **não foi usada** (não verificável). Os registros acima são da *Premium Edition* (base + Season Pass); o Season Pass dos EUA usa o mesmo CUSA00133 no Content ID.
- **O Q-id `Q15891648` NÃO foi verificado no Wikidata**: veio de um agregador de terceiros (golden.com) em resultado de busca. Por isso o comando compara com o **seu índice local**: confirma ("vínculo confirmado no índice: Q… = "Batman: Arkham Knight"") ou alerta (Q-id ausente / nome diferente). **Se alertar, não confie nos CUSAs** e me envie a saída: o Q-id deve ser corrigido.
- Versão do pacote: desconhecida em todos.

## Comandos (Termux)
```sh
cd ~/PS4 && git pull
# 0) conferir o Q-id contra o SEU índice do Wikidata e validar o arquivo
PYTHONPATH=src python -m ps4store.versoes --validar
# 1) critério de aceite: pesquisar o jogo e listar os CUSAs
PYTHONPATH=src python -m ps4store.versoes "Batman: Arkham Knight"
PYTHONPATH=src python -m ps4store.versoes "Batman: Arkham Knight" --evidencias        # todas as fontes
# 2) sem filtros = todas as versões registradas; filtros opcionais
PYTHONPATH=src python -m ps4store.versoes
PYTHONPATH=src python -m ps4store.versoes "Batman: Arkham Knight" --regiao EU
PYTHONPATH=src python -m ps4store.versoes --cusa CUSA00133
PYTHONPATH=src python -m ps4store.versoes --idioma Korean
# 3) depois de abrir a página da loja no navegador e conferir
PYTHONPATH=src python -m ps4store.versoes --confirmar UP1018-CUSA00133_00-B000000000001563 --por "eu"
# 4) acrescentar um registro (exige a fonte; campos não informados ficam desconhecidos)
PYTHONPATH=src python -m ps4store.versoes --adicionar --qid Q123 --jogo "Nome" --cusa CUSA00001 --evidencia-fonte "Loja" --evidencia-url https://...
```
A busca por nome usa o seu índice (`local/busca-indice.json`) só para **localizar** o jogo; as versões vêm do Q-id.
