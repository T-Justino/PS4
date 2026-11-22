# Busca e consulta unificadas (Etapa 5C)

`python -m ps4store.jogos`: um fluxo interativo (Termux) que junta `busca.py` e `versoes.py` (usados como bibliotecas): **digitar o nome → lista numerada → escolher o número → ver os CUSAs ligados ao Q-id**. Só metadados: não resolve links, não baixa nada, e um CUSA não indica PKG/download (isso continua com o resolvedor).

## Um comando para o Android
```sh
cd ~/PS4 && git pull && PYTHONPATH=src python -m ps4store.jogos
```
Digite, por exemplo, `batman` → escolha `1` (Batman: Arkham Knight).

## O que o fluxo faz
- **Busca livre** por parte do nome (sem acentos/maiúsculas), sem filtros obrigatórios; resultados numerados com ano, Q-id e a contagem de versões ("3 registro(s), 2 CUSA(s) distinto(s)") ou "sem versões cadastradas". Resultado sem Q-id: "não dá para vincular versões".
- **Ao escolher**, mostra os registros do **Q-id** escolhido (nunca por semelhança de nome). Sem filtros, **todos** aparecem.
- **Filtros opcionais** dentro do jogo: `f cusa CUSA00133`, `f regiao EU`, `f idioma Korean`, `f limpar` (também `--cusa/--regiao/--idioma` na linha de comando). Campo desconhecido não casa com filtro e o programa diz quantos ficaram de fora.
- **Rótulos que evitam confusão:** `CUSA00133 (CUSA: identificador do título)` e, separado, `Content ID … (identifica este produto/edição; NÃO é o CUSA)`; `Edição: … (registro de edição/produto da loja, não de jogo-base)`; e a linha "Nenhum registro está marcado como jogo-base" enquanto nenhum registro tiver `escopo: "jogo-base"`.
- **Status:** `CITADO: a fonte foi vista, mas a página não foi aberta nem conferida` × `CONFIRMADO por … em …`; campos sem evidência: "desconhecida(s)" (a região não define o idioma).
- **Sem versões:** "Nenhuma versão CUSA cadastrada para Q… Isso NÃO quer dizer que o jogo não tenha CUSA… Nada foi inventado."
- Digitar um **Content ID** ou um **CUSA** na busca: o programa explica a diferença e lista o(s) jogo(s) com esse registro.
- Comandos dentro do jogo: número (outro resultado) · `e` (todas as fontes e notas) · `b` (lista) · `n` (nova busca) · `?` · `q`.
- Sem índice de busca (`local/busca-indice.json`): avisa e só acha jogos que já têm versões cadastradas (gere o índice com `python -m ps4store.wikidata --atualizar`).
- Não interativo: `python -m ps4store.jogos batman --escolher 1 [--cusa X --regiao Y --idioma Z --evidencias]`.

## Limites
Os dados de versão continuam os da 5B (3 registros de Batman: Arkham Knight, todos "citado"). Não há registro de jogo-base. Links/arquivos de download não são tratados aqui.
