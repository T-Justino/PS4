# Limitações: por que o catálogo atual NÃO oferece variedade real de jogos de PS4

O MVP prova o **mecanismo** (descobrir → verificar → publicar → importar → instalar → abrir), com **um app próprio**. Hoje o catálogo instalável tem **1 título** (`PS4 Store BR Test`). Os motivos, separados:

## A. Autorização e legalidade (a maior barreira)
1. **Jogos comerciais estão fora do escopo do projeto:** só entram pacotes com autorização de distribuição. Não existe fonte legítima de jogos comerciais de PS4 por link direto (os oficiais exigem conta/licença PSN).
2. **PKG-Zone:** 191 releases descobertas, **0 publicáveis**. Os Termos não dão permissão a terceiros para listar; o catálogo não traz licença por app; os 19 itens com ID `CUSA` são, pelos Content IDs, repackagens de apps/jogos comerciais (Netflix, YouTube, Hulu, ESPN, Plex…). Pedido de permissão só em rascunho (`PKGZONE_PEDIDO.md`, não enviado).
3. **Autorização é por item**, e hoje só existe para o app próprio. Cada novo pacote exige licença/permissão do autor registrada.

## B. Compatibilidade com o importador do SSPI
4. **O SSPI 5.11.7 só aceita IDs `CUSA`** na importação (comprovado: `NPXS`, `APOL` recusados; outros prefixos não comprovados). Dos 180 PKGs lidos no PKG-Zone, 153 têm prefixo não comprovado e 2 foram recusados (`APOL00004`, `NPXS29129`). **A maior parte do homebrew fica de fora por isso.**
5. **Chaves sintéticas não resolvem:** o SSPI confere a chave com o ID interno na instalação (T7). Não dá para "traduzir" `NPXS`/`APOL` para `CUSA`.
6. **Um ID `CUSA` num homebrew pode colidir com um jogo oficial** (o PKG-Zone já tem 10 IDs diferentes do declarado). O ID do nosso app (`CUSA95417`) é experimental; não é oficial.
7. **Só pacotes "base"** (`gd`/`gde`). **Atualizações e DLC não foram testados**; pelo código público do SSPI dependem do jogo base instalado e do `param.sfo` sob o ID `CUSA`. Um app `CUSA` não é substituído automaticamente (precisa de *Reinstall* ou excluir antes).

## C. Hospedagem e tamanho
8. **O catálogo só aponta links:** alguém precisa hospedar os PKGs em HTTPS direto, sem login/CAPTCHA. Hosts comprovados no seu console: `raw.githubusercontent.com` (PKG de 6,6 MB) e `pkg-zone.com` (Store). **`github.com` falha com TLS.** O redirect assinado do PKG-Zone (`api.pkg-zone.com`) **foi comprovado** com o OpenTyrian (download direto, 19,8 MB); arquivos grandes e retomada ainda não.
9. **Jogos reais têm de 1 a 100 GB**, e hospedar no GitHub não é viável (limite de 100 MB por arquivo no repositório; uso como CDN de jogos viola os termos). **RAR/partes múltiplas não estão implementados** (Gate 5).
10. **Sem VPS e sem PC** (requisito) significa depender de hosts gratuitos de terceiros com limite de banda/arquivo.

## C2. Retomada de downloads grandes (achado do Teste 3, 22/11/2026)
- Um download de ≈949 MB **falhou por certificado TLS em 915,3 MB depois de uma interrupção**; a nova tentativa manual concluiu. **A retomada não está resolvida**: não se sabe se a 2ª tentativa retomou ou recomeçou, nem a causa do erro (hipótese: cadeia de certificado do host de download, `api.pkg-zone.com`/Cloudflare, não aceita pelo PS4 em uma reconexão). Do lado do robô não há correção; o servidor oferece o que o SSPI precisa (`Range`, tamanho e ETag estáveis). Para o usuário: após uma interrupção, **refazer o download**.

## D. Verificação e operação
11. **A verificação lê só os primeiros 64 KiB:** identidade e tamanho, **não** o conteúdo inteiro nem `sha256` (não inventamos). Não prova que o PKG instala/abre (só o T8b provou, para um pacote). 4 PKGs do PKG-Zone têm `param.sfo` além da janela e não foram lidos.
12. **O firmware exigido pelo pacote** (`pv` do PKG-Zone, ex. "9.00", "5.05+") **não é verificado** contra o console.
13. **A fonte não se atualiza sozinha no PS4:** é preciso colar o link de novo (espera de ≈5 min pelo cache do GitHub). O refresh automático do SSPI (`embedded-catalog-refresh-v1`) não foi usado nem provado.
14. **Conector do GitHub para terceiros funciona** (achou 5 releases do Apollo no Actions), mas projetos homebrew com release e ID `CUSA` são raros; o Apollo é `APOL` (rejeitado).
15. Sem metadados ricos (capas, gêneros, idiomas); PT-BR só por nome/alias (e filtro fora do escopo).

## O que seria preciso para ter variedade (em ordem de impacto)
1. **Autorizações reais:** permissão do PKG-Zone e licença por app dos autores; ou parceria com autores de homebrew/jogos independentes que queiram distribuir em PS4.
2. **Resolver a barreira do ID:** descobrir se o SSPI aceita outros prefixos além de `CUSA` em versões novas, ou se os autores podem publicar com ID `CUSA` próprio e livre de colisão.
3. **Hospedagem aprovada para pacotes grandes** (host que o SSPI baixa, com limite adequado) e, só depois, suporte a RAR/partes.
4. Testes de **atualização e DLC** no console antes de qualquer promessa.

**Nenhuma afirmação de que "qualquer jogo" pode ser encontrado ou instalado é feita ou suportada por esta evidência.**
