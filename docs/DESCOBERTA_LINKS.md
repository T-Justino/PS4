# Descoberta de links por jogo

- Painel → página do jogo → **Buscar links** (`GET /api/links?qid=`, exige o cabeçalho do painel). Cada resultado mostra origem, formato (PKG/RAR/...), tipo (base/atualização/DLC só pelo nome até ler os bytes), versão, tamanho, como corresponde ao jogo e se a distribuição é **autorizada** ou **link externo não verificado**. **Analisar e preparar para SSPI** reaproveita `analise_link.py` (lê CUSA/Content ID/versão dos bytes do PKG, compara com o jogo, monta o bloco com `colar.py`). Colar URL manual continua.
- Sem resultado: "Nenhum link encontrado nas fontes consultadas".
- Linha de comando: `python -m ps4store.descoberta_links --jogo "OpenTyrian" --analisar` (nome exato; funciona também para homebrew fora do índice) e `--atualizar` (grava os catálogos em `local/links-cache.json`, validade 24 h).
- Fontes: `config/fontes-links.json`, só conectores estruturados de `discover.py` (catálogo JSON público do PKG-Zone, API de releases/contents do GitHub). Correspondência: CUSA/Content ID iguais (forte) ou nome normalizado idêntico (fraca, até ler o PKG). Nada por semelhança.
- Fora de escopo: sites que distribuem PKGs de jogos comerciais sem autorização. Não há conector de busca genérica nem raspagem.
