# Catálogo web (MVP): pesquisar no celular e enviar o link ao SSPI

Página estática única (`site/index.html`, sem backend, banco ou usuários), gerada por `ps4store web` a partir dos registros que o robô já valida (`local/research.json`). O workflow `catalogo` gera e publica no GitHub Pages. `.gssource` e CLI seguem funcionando.

## O que a página mostra
- Busca por nome ou ID, sem acentos/maiúsculas; ordem: exato → começa com → palavra do nome → contém.
- Título, versão, tipo, tamanho, ID, Content ID, **de onde veio a identidade** ("lida do PKG" ou "informada pela fonte") e o estado:
  - **Link validado automaticamente** (verde): o robô testou o link (responde, Range) **e** leu a identidade do PKG. Não garante instalação.
  - **Instalação comprovada no PS4** (azul): só o que **você relatou** ter instalado e aberto, pela URL exata (`config/ps4-proven.json`: OpenTyrian e Live Die Repeat).
  - Não testado / inacessível / indisponível (com o motivo): sem botão e sem URL.
- **Copiar link**: só em item validado.
- Não entram na página: ID com aparência comercial, versões antigas, duplicados e RAR (só PKG por enquanto).

## Duas decisões suas (a página do Pages é pública)
| Modo | URL copiável embutida | Hoje |
|---|---|---|
| `publico` (padrão) | só item com autorização de listagem registrada | 1 (app de teste próprio) |
| `pessoal` | também os de **link direto validado** (pkg-zone etc.) | 67 |

O pkg-zone **não concede permissão de listagem a terceiros** (GATE3.md). Escolher `pessoal` publica essas URLs numa página pública: é decisão sua (workflow → Run workflow → `web_links = pessoal`).

## Ativar o Pages (uma vez)
1. Repositório → Settings → Pages → **Source: GitHub Actions**.
2. Settings → Environments → `github-pages` → permitir a branch `ccr-8aace08a-bzwy8i` (ou faça merge na principal). Sem isso o job `publicar-site` falha; o catálogo `.gssource` não é afetado.
3. Actions → catalogo → Run workflow. O endereço aparece no job `publicar-site`.

## Procedimento no Android + PS4
1. PS4: SSPI → mostrar o **QR do Phone Companion**; escanear no celular (mesma Wi-Fi).
2. Em outra aba, abrir o catálogo, buscar (ex.: `opentyrian`), tocar **Copiar link**.
3. Voltar à aba do SSPI → **Downloads** → colar em *Paste a download link* → enviar.
4. No PS4, o item entra na fila do SSPI. Anote se funcionou.

## Integração direta com a fila do SSPI (avaliação; NÃO implementada)
Lido em `app/PairServer.cs` (SSPI, commit 1295abb):
- A fila é alimentada por `POST http://IP-DO-PS4:8741/pair/<token>/downloads` com `links=<URLs>&multipart=0|1`. O token é de uso único, vem no QR e expira por inatividade.
- **Sem CORS** (nenhum `Access-Control-Allow-*`, sem tratar `OPTIONS`), só rede local, HTTP puro.
- Da página HTTPS do Pages, `fetch` para esse HTTP é **bloqueado** (conteúdo misto; no Chrome também a política de rede privada). Não dá para chamar direto sem mudar o SSPI.
- Alternativa possível (não testada): o usuário cola o endereço do QR na página e o botão envia um **formulário (navegação de topo)** ao PS4. O Chrome costuma avisar sobre envio inseguro; a resposta é texto simples. Guardar o token no navegador é risco pequeno (uso único, rede local), mas é segredo.
- **Recomendação:** manter "copiar e colar" para o MVP. Só implementar o formulário se você confirmar, e testando antes no seu Android/PS4.
