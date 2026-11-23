# Interface web local (Etapa 5D)

Painel visual para pesquisar jogos e consultar versões CUSA no **navegador do Android**, sem digitar comandos. Usa `busca.py` e `versoes.py` como bibliotecas e o servidor `http.server` da biblioteca padrão. Só leitura; sem login; nada externo.

## Iniciar (um comando no Termux)
```sh
cd ~/PS4 && git pull && PYTHONPATH=src python -m ps4store.painel
```
Depois abra **http://127.0.0.1:8765** no navegador do Android.

## Encerrar
- No Termux: **Ctrl+C** (volume-baixo + C no teclado do Termux).
- Ou, de outra sessão do Termux: `pkill -f ps4store.painel`.
- Porta ocupada (já há um painel rodando)? Use `--porta 8766` e abra o endereço novo.

## Como usar
1. Digite parte do nome (sem acentos/maiúsculas) e toque em **Buscar**; ou **Mostrar só jogos com versões cadastradas**.
2. A lista mostra nome, ano, fonte (ex.: Wikidata) e o Q-id, com "N registro(s) · M CUSA(s)" ou "sem versões cadastradas".
3. Toque num jogo para ver as versões ligadas ao **Q-id**: CUSA ("identificador do título"), Content ID ("NÃO é o CUSA"), edição ("registro de edição, não de jogo-base"), região, idiomas, versão do pacote, lojas, status (**CITADO** × **CONFIRMADO**) e fontes. O que não tem evidência aparece como **desconhecido**.
4. **Filtros opcionais** (CUSA, região, idioma) ficam em "Filtros das versões"; sem filtros, todos os registros aparecem. Campo desconhecido não casa com filtro e a tela diz quantos ficaram de fora.
5. Sem versões cadastradas: "Nenhuma versão CUSA cadastrada… Nada foi inventado."
Funciona offline com os dados já importados (`local/busca-indice.json` e `data/versoes-cusa.json`); se mudarem no disco, o painel os recarrega sozinho.

## Segurança
- Escuta **só em `127.0.0.1`** (sem opção de outro endereço) e confere o cabeçalho `Host` (contra DNS rebinding).
- **Somente GET/HEAD**; POST/PUT/DELETE/PATCH/OPTIONS retornam 405. Nada é gravado em disco.
- Rotas fixas (`/`, `/estilo.css`, `/app.js`, `/api/estado`, `/api/jogos`, `/api/jogo`): o caminho da URL nunca vira caminho de arquivo; o resto é 404.
- Parâmetros em lista fechada e validados (tamanho, caracteres de controle, `Q…`, `CUSA…`, limite 1–200); repetidos/desconhecidos → 400. Consultas nunca viram comandos.
- CSP restritiva (`default-src 'none'`, sem script inline nem externo), `nosniff`, `no-referrer`, `no-store`; a interface monta o conteúdo com `textContent` (nomes do índice não executam HTML) e só abre links `https://`.
- Não resolve links nem baixa nada; CUSA não indica PKG/download.

## Limites
Só busca e consulta de versões (os dados são os da 5B: 3 registros de Batman: Arkham Knight, todos "citado"). Não integra downloads, SSPI nem o resolvedor.

## 5G · Catálogo visual, capas e busca inteligente

- **Interface**: tema escuro, grade de cards (2 colunas em ~390 px), imagem com carregamento tardío (`loading=lazy`), placeholder com a inicial quando não há imagem, "Mostrar mais" (48 por vez, `offset`), contadores compactos, detalhe com imagem + origem/licença recolhível.
- **Imagens** (comando separado, é o único que usa rede): `python -m ps4store.capas --amostra 30 --jogos "batman,cyberpunk"` (`--status` resume, sem rede). Fonte: Wikidata P18 → metadados do Wikimedia Commons. Só entram CC0, domínio público, CC BY e CC BY-SA, com autor quando exigido; NC/ND/GFDL/uso justo/desconhecida são rejeitadas e registradas em `local/capas/indice.json` (`semImagem`). Miniatura ≤ 400 KB, validada pelos bytes. Rótulos: **capa** (categoria "cover" no Commons), **imagem ilustrativa** (não é capa oficial), **sem imagem** (placeholder). `local/capas/` não vai para o Git.
- **Rota** `GET /capa/<Qid>`: só Q-id válido; o arquivo vem do índice de capas (nome `Q123.ext` dentro da pasta), nunca do caminho da URL.
- **Busca**: exata primeiro; parcial, sem acento/pontuação; apelidos em `data/apelidos.json` (só com vínculo explícito a UM Q-id do índice; ambíguo ou ausente = não aplica); sem resultado → até 5 sugestões por similaridade (você escolhe; nada é trocado sozinho). Texto parecido nunca altera Q-id nem CUSA.
- API: `/api/jogos` ganhou `offset`, `temMais`, `sugestoes`, `viaApelido`, `capa` por item; `/api/jogo` ganhou `capa` (com atribuição).

### Imagens automáticas (complemento 5G/5H)
- `capas.py` agora tenta, **em ordem**, três provedores independentes; o primeiro que der imagem aceita (licença livre) **e** jogo conferido vence: `wikidata-p18` → `wikipedia` (imagem principal do artigo que o índice já liga ao Q-id; título do artigo tem de bater com o nome) → `commons-busca` (busca por nome no Commons; o nome do arquivo precisa conter o nome do jogo e nada além de ruído, sem número de sequência/ano diferente, e o texto precisa indicar videogame). Vertical vence horizontal; "capa" vence "ilustrativa". Registro: provedor, como o jogo foi conferido, Q-id/nome/ano, página do arquivo, licença, autor, data.
- Só miniatura **local** (sem hotlink; nenhuma URL externa é usada para exibir). Cache em `local/capas/`; jogo sem imagem só é reconsultado após 14 dias.
- Fila progressiva: `python -m ps4store.capas --fila 30 [--painel-porta 8765] [--jogos "a,b"]`. Prioridade: jogos que você abriu/pesquisou no painel (`/api/interesse`, só Q-ids em memória; o painel não grava nada) → nomes pedidos → jogos com CUSA. Cada execução processa ≤ 30 jogos; rode de novo para avançar. O painel nunca busca imagem.
- Investigadas e **não** integradas: bases que exigem chave (RAWG, IGDB, TheGamesDB, SteamGridDB) e CDNs de lojas/promo (sem permissão de reuso). Isso vem do meu conhecimento prévio; não foi possível verificar da sandbox (sem rede).
