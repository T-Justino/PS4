# Busca por nome (Etapa 5A)

Módulo independente `src/ps4store/busca.py` (stdlib, Python ≥ 3.11, serve no Termux). Índice JSON local, sem banco de dados, sem servidor.
Não resolve links, não baixa nada e não coleta sites: **importa um arquivo local** de uma fonte registrada e autorizada e **pesquisa por parte do nome**.

## Uso
```sh
# 1) importar o índice de TESTE (fictício) uma vez
PYTHONPATH=src python -m ps4store.busca --importar data/fixtures/busca-teste.json --fonte teste
# 2) pesquisar: só o nome, nenhum filtro
PYTHONPATH=src python -m ps4store.busca Batman
PYTHONPATH=src python -m ps4store.busca lego batman
PYTHONPATH=src python -m ps4store.busca pokemon --json
```
Saída: número de resultados e, para cada um, **nome + URL da página de origem + fonte**. O índice fica em `local/busca-indice.json` (`--indice` muda o caminho).
Atualizar uma fonte = importar de novo: troca **todos** os títulos daquela fonte e mantém os das outras.

## O que a busca faz
- Parte do nome, sem diferença de maiúsculas, acentos ou pontuação; todos os termos precisam aparecer, em qualquer ordem.
- Vários resultados; ordem: nome igual → começa com → palavra do nome → contém. Nomes repetidos em fontes/URLs diferentes são **todos mantidos** (só cópia exata de nome+URL é descartada).
- Nenhum CUSA, região, idioma ou outro filtro é exigido. Os campos opcionais `titleId`, `regiao` e `idiomas` já são aceitos e preservados no índice, para os filtros futuros.

## Fontes: regra e decisão
- Uma fonte só pode ser importada se estiver em `config/busca-fontes.json` com `authorization` (`basis` + `evidence`), a mesma regra de `config/sources.json`. Sem isso nada é importado. Hoje só existem fontes de **teste**, com dados inventados (`data/fixtures/busca-teste.json`, URLs `.invalid`).
- **`dlpsgame.com` e `dlpsgames.net` não foram acessados nem indexados.** São sites de páginas de download de jogos comerciais do PS4 sem autorização dos detentores (conhecimento geral; não verifiquei os sites). Construir um índice deles seria montar um localizador de cópias não autorizadas, e este projeto só trabalha com fontes autorizadas (homebrew, software próprio, fontes com permissão registrada). Por isso a verificação de acessibilidade, estrutura e termos de uso deles não foi feita, e o módulo não traz coletor para eles.
- Para uma fonte legítima futura: registrar em `config/busca-fontes.json` com a evidência da autorização e gerar o arquivo `.json`/`.txt` (`nome<TAB>url`) a importar.

## Limites desta entrega
Sem coleta/atualização remota (só arquivo local), sem filtros opcionais implementados, sem resolução de links (isso continua em `resolver.py`/`colar.py`).
