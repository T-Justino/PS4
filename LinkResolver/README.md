# Link Resolver (MVP)

App Android nativo (Kotlin + WebView + AndroidX, minSdk 29 / Android 10+) que recebe a URL de uma página e
acompanha o fluxo de navegação até identificar a URL de um **download de arquivo autorizado**.
O app **nunca baixa o arquivo**: o `DownloadListener` apenas entrega URL e metadados. Sem integração com PS4/VPS nesta fase.

## Instalação
1. Android Studio Ladybug (2024.2) ou mais novo, JDK 17 (embutido no Studio).
2. `File ▸ Open…` e escolha a pasta `LinkResolver/` (esta). O Studio baixa o Gradle 8.9 (wrapper) e o SDK 35 se faltar.
3. Execute em um emulador/aparelho com Android 10+ (API 29+) que tenha o **Android System WebView / Chrome atualizado** (Safe Browsing depende dele).
4. Linha de comando: `./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`; `./gradlew testDebugUnitTest` roda os testes de unidade.

## Versão
A versão e o commit aparecem no rodapé do app (`BuildConfig.VERSION_NAME` / `GIT_COMMIT`, preenchidos pelo CI via `GITHUB_SHA`).

## Como usar
1. Digite uma URL `https://…` e toque em **Analisar** (compartilhar uma URL de outro app para o Link Resolver também preenche o campo).
2. Abas inferiores: **Navegador** (WebView + abas), **Candidatos** (links/botões detectados com pontuação e motivos; botão *Seguir*/*Clicar* para ação manual), **Histórico** (etapas), **Resultado**.
3. A automação só segue candidatos com pontuação ≥ 40 em domínios já confiáveis. Domínio novo ⇒ diálogo *Permitir domínio / Só desta vez / Negar*.
4. CAPTCHA, verificação anti-robô ou login ⇒ a automação **pausa**; resolva na própria página. Ela retoma sozinha quando o desafio deixa de ser detectado (ou toque em *Já resolvi — verificar*).
5. Resultado: URL (valores sensíveis mascarados), host, MIME, nome estimado, tamanho, pontuação, evidências, diagnóstico de erro, candidatos, histórico e estado: **Arquivo confirmado**, **Candidato não verificado**, **Link intermediário**, **Exige sessão**, **Erro de rede**, **Nenhum candidato encontrado**, **Bloqueado**.
   URLs com cara de arquivo são validadas (cliente **OkHttp**) por **HEAD** (ou **GET com `Range: bytes=0-0`**) antes de navegar — só cabeçalhos, sem baixar o corpo, sem cookies, com checagem de IP interno a cada salto. O `DownloadListener` é evidência adicional. Páginas de erro do navegador (`chrome-error://`) nunca são analisadas. *Copiar URL* copia a URL completa (se tiver token/assinatura, o app avisa e marca a área de transferência como sensível no Android 13+).

## Como testar
**Unitários (JVM, sem emulador):** `./gradlew testDebugUnitTest` — 140 testes (+1 teste real de rede, opcional) (segurança de URL, heurísticas, scanner, motor: loops, limites, domínios, CAPTCHA, sessão). Estes testes também foram executados na JVM durante o desenvolvimento.

**Manuais no aparelho** (o app só aceita HTTPS público; `localhost`/IPs privados são bloqueados de propósito, então hospede `testpages/` em HTTPS — p.ex. GitHub Pages — ou use um túnel HTTPS):
| Página | Esperado |
|---|---|
| `testpages/index.html` | ignora o "anúncio", segue "Baixar agora" → etapa 2 → captura `exemplo.zip` ⇒ *Arquivo verificado* |
| `testpages/captcha.html` | pausa ao detectar o bloco de desafio; após "Simular resolução humana" retoma sozinha |
| `testpages/popup.html` | popup sem gesto bloqueado; link com gesto abre aba (chip com ✕ para fechar) |
| página de *Releases* do GitHub | redirecionamento para domínio de CDN desconhecido ⇒ diálogo de confirmação |
| `http://…`, `https://192.168.0.1`, `https://localhost` | ⇒ *Bloqueado* na URL inicial |
| `https://testsafebrowsing.appspot.com/s/malware.html` | Safe Browsing bloqueia ⇒ *Bloqueado* |

## Arquitetura
```
core/  (Kotlin puro, testado na JVM)
  UrlSafety        esquemas perigosos, HTTPS-only, IP/host local ou interno, redação de tokens
  DomainPolicy     domínios confiáveis da sessão (eTLD+1 heurístico)
  DownloadHeuristics  pontuação de candidatos, redes de anúncios, MIME, nome estimado
  PageScanner      JS somente-leitura (evaluateJavascript) + parser; detecta CAPTCHA/anti-robô/login
  ResolverEngine   máquina de estados: limites (profundidade 6, 180 s total, 45 s/etapa, 4 domínios,
                   10 redirecionamentos/etapa, 3 visitas/URL), loops, confirmação, pausa humana
TabManager         WebViews endurecidos, onCreateWindow (popup só com gesto + origem confiável), clients
MainActivity       cola WebView ↔ motor, UI em 4 painéis
```
Limites ajustáveis em `core/Models.kt` (`Limits`).

## Segurança (resumo)
- Safe Browsing: `meta-data EnableSafeBrowsing`, `settings.safeBrowsingEnabled`, `onSafeBrowsingHit` ⇒ sempre *voltar à segurança*.
- Só HTTPS (`usesCleartextTraffic=false` + validação); `intent:`, `javascript:`, `file:`, `content:`, `data:`, `blob:`… bloqueados; sub-recursos para rede interna recebem 403 em `shouldInterceptRequest`.
- Sem `addJavascriptInterface`; acesso a arquivos desligado; mixed content bloqueado; erros SSL nunca são ignorados; `alert/confirm/prompt` de página cancelados; permissões de câmera/microfone/GPS negadas.
- Cookies só em memória da sessão (limpos ao abrir/fechar o app e por *Limpar sessão*); cookies de terceiros desativados. Logs e a tela de resultado mascaram `token`, `sig`, `X-Amz-*`, credenciais na URL e fragmentos; cookies e cabeçalhos nunca são lidos nem registrados.
- O app **não contorna** CAPTCHA, DRM, paywalls ou autenticação: apenas detecta, pausa e espera a pessoa.

## Limitações conhecidas do MVP
- Verificação de IP interno é por texto do host; **DNS rebinding** (nome público → IP privado) não é detectado sem resolver DNS.
- Download via `http://`, `blob:` ou `data:` é recusado (política HTTPS-only).
- Detecção de CAPTCHA/login é heurística (seletores e frases); sites com desafios incomuns podem passar despercebidos — use *Parar* a qualquer momento.
- Botões que só funcionam por JavaScript (sem URL) não são clicados automaticamente; aparecem em *Candidatos* com *Clicar* manual.
- O código Android (`TabManager`, `MainActivity`, layouts) foi escrito sem acesso ao SDK no ambiente de desenvolvimento: o `TabManager` foi compilado contra o framework Android 15 e o núcleo foi testado na JVM, mas **a primeira compilação completa no Android Studio ainda não foi feita**. Se aparecer algum erro de build, é simples de corrigir; abra uma issue/mensagem com o log.

## Validação HTTP (v0.2.0)
- Cliente OkHttp 4.12 (HTTP/2 + HTTP/1.1, TLS do sistema) com perfis de tentativa: UA estilo Chrome (sem `; wv`/`Version/4.0`) em h2+http/1.1, depois só http/1.1, depois o UA do WebView. Hipótese para o `unexpected end of stream`/`ERR_EMPTY_RESPONSE` do Hetzner: o servidor fecha a conexão sem responder ao UA de WebView. Não foi possível reproduzir no ambiente de desenvolvimento (host bloqueado); o diagnóstico por tentativa mostra no aparelho qual perfil funcionou.
- Validação inconclusiva **não** navega até o binário: o resultado vira *Candidato não verificado* (ou *Exige sessão*, em 401/403), com o link preservado e botão **Copiar** (aba Candidatos e aba Resultado).
- Redirecionamento do arquivo para domínio novo pede a mesma confirmação de domínio e revalida.
- Diagnóstico (aba Resultado/Histórico): DNS, TCP, TLS (versão/cifra), protocolo, HTTP, timeout, redirecionamentos — sem IPs, cookies, cabeçalhos nem valores de query.

## v0.3.0 — resolvedor de redirecionamentos em múltiplas etapas
- **Caminho percorrido** (aba Resultado): cada página/salto/arquivo, *como* se chegou lá (URL inicial, redirecionamento HTTP, meta refresh, JavaScript, decisão automática, escolha manual) e o **motivo da decisão** (pontuação + sinais). Classes: *página intermediária*, *candidato de download*, *arquivo confirmado*.
- **Redirecionamentos HTTP 301/302/303/307/308:** todo candidato seguido é verificado antes por OkHttp (HEAD/Range 0-0), que registra o **código real** de cada salto; o WebView só informa que houve redirect (não expõe o código). Redirecionamento para domínio novo pede confirmação humana. Se a verificação encontra um arquivo, confirma sem navegar.
- **Meta refresh e JavaScript:** o scanner lê `<meta http-equiv=refresh>` e `location.href=/replace/assign` de scripts inline (somente leitura) e os trata como candidatos de alta pontuação.
- **Páginas intermediárias:** páginas com poucos links ou texto de espera ("aguarde", contagem) seguem o link de etapa (Continuar/Próximo/Download), esperando mais tempo quando indicam contagem regressiva. Domínio desconhecido continua passando pela confirmação humana.
- **Loops e limites:** 3ª visita à mesma URL, caminho que só leva a páginas já visitadas, 2 páginas sem nenhuma URL nova, 15 páginas, profundidade 6, tempos e domínios — todos interrompem e preservam os candidatos.
- Em qualquer falha os links encontrados (todas as páginas) ficam na aba **Candidatos**, com botão **Copiar** e status "não verificado".

### Páginas de teste (HTTPS, sem configurar nada)
O workflow *LinkResolver test pages* publica `LinkResolver/testpages` na branch `gh-pages`. As páginas são servidas por **raw.githack.com** (HTML), o arquivo de teste (200 KB, `v3/files/teste.bin`) por **cdn.jsdelivr.net** e os redirecionamentos HTTP reais por **httpbin.dev** (`/redirect-to?url=…&status_code=…`) e **github.com** (302 para raw.githubusercontent.com). Como cada serviço é um domínio diferente, o app pede **confirmação de domínio** durante os testes (toque em *Permitir domínio*). Menu: `https://raw.githack.com/T-Justino/PS4/gh-pages/v3/index.html`.

Base: `https://raw.githack.com/T-Justino/PS4/gh-pages/v3/`

| Teste | URL inicial | Esperado |
|---|---|---|
| A→B→C→arquivo | `…/v3/abc/a.html` | Arquivo confirmado após 3 páginas; confirma `cdn.jsdelivr.net`; não navega até o `.bin` |
| Meta refresh | `…/v3/meta/start.html` | segue o destino do meta refresh |
| Redirecionamento JS | `…/v3/js/start.html` | segue o destino do `location.href` |
| HTTP 301/302/303/307/308 | `…/v3/http/301.html` (idem `302`, `303`, `307`, `308`) | pede confirmação para `httpbin.dev`; registra o código HTTP; confirma o arquivo |
| 302 direto ao arquivo | `…/v3/http/raw302.html` | pede confirmação de `github.com` e de `raw.githubusercontent.com`; confirma o arquivo por HEAD/Range |
| Loop | `…/v3/loop/a.html` | Bloqueado: loop detectado |
| Sem link válido | `…/v3/dead/start.html` | Nenhum candidato; "política de privacidade" preservada para cópia |
| 4 etapas | `…/v3/long/1.html` | Arquivo confirmado após 4 páginas |
| Anúncios | `…/v3/ads/start.html` | ignora anúncios e segue "Continuar" |

(`…` = `https://raw.githack.com/T-Justino/PS4/gh-pages`.) Observação: `raw.githack.com` recusa HEAD (403) em alguns arquivos; a verificação cai para GET `Range: bytes=0-0`, e páginas continuam sendo navegadas normalmente. `httpbin.org` e `httpbingo.org` bloqueiam IPs de datacenter, por isso foram trocados.


## v0.4.0 — navegação assistida em múltiplas guias
- **Guias:** `window.open`/`target=_blank` só abrem com **gesto humano**, em **origem confiável**, sem popup dentro de popup, com limite por página (3) e por análise (6) e no máximo 4 guias. Cada guia nova entra no caminho com a página que a originou. Depois de carregar, a guia é **classificada**: tem continuação (link/botão de download-etapa) ⇒ vira a *guia de trabalho* (★ no chip); propaganda (cassino/prêmio/VPN…) ou sem continuação ⇒ **fechada**. Abrir guia nunca confirma arquivo. Você pode alternar/fechar guias e tocar em **Usar esta guia** para continuar manualmente em qualquer uma (inclusive depois do fim). Domínio desconhecido em qualquer guia continua pedindo confirmação.
- **Botões dinâmicos:** o scanner instala um `MutationObserver` (somente leitura) que conta mudanças relevantes (links/botões criados, habilitados, mostrados). O app lê o contador a cada 1 s e reescaneia com limite de frequência (≥ 1,5 s, ≤ 20 varreduras por página). Elementos criados/liberados depois do carregamento ganham bônus; desabilitados perdem pontos e nunca são clicados.
- **Cliques:** botão sem URL só é clicado automaticamente se a intenção for **inequívoca** (único botão visível, habilitado, com texto de ação como *Continuar/Próximo/Baixar*, sem texto suspeito nem contexto de anúncio; no máx. 6 por análise). Como o clique programático não vale como gesto humano, se nada acontecer em 4 s o app **destaca o botão** (contorno vermelho + rolagem) e espera **você tocar nele**. Com 2+ botões possíveis (ambíguo), nada é clicado: use *Destacar* na aba Candidatos.
- **Temporizadores:** contagens regressivas ("aguarde 6 segundos", "seu download começa em…") e botões desabilitados fazem o app **esperar** (até 40 s por página) e reescanear quando o botão for liberado. O app **não altera relógios, scripts nem atributos do site**; redirecionamentos JS dentro de *handlers* de clique não são seguidos adiantadamente (isso burlaria a espera).
- **Verificação humana:** CAPTCHA/anti-robô/login pausam a automação; a página fica aberta com sua sessão e cookies. Retoma sozinho quando a página libera, ou quando você toca em **Já resolvi** (que também ignora a detecção nessa página, caso ela persista). Nada é resolvido, contornado ou falsificado.
- **Motor:** novo estado **Loop detectado**; candidato pode ser **retomado manualmente após o fim** (*Seguir* na aba Candidatos inicia nova etapa controlada, até 5 vezes, com novo orçamento de tempo e histórico preservado); candidatos nunca ficam "verificando metadados" depois de concluir.

### Páginas de teste v0.4.0 (HTTPS)
Publicadas na branch `gh-pages` pelo workflow *LinkResolver test pages*; as páginas usam links relativos e funcionam em qualquer host. **GitHub Pages** (preferido): ative uma única vez em *Settings → Pages → Deploy from a branch → `gh-pages` / `(root)`* (o token do CI não consegue ativar — HTTP 403) e use `https://t-justino.github.io/PS4/v4/…`. **Já funciona sem configurar:** `https://raw.githack.com/T-Justino/PS4/gh-pages/v4/…`. O arquivo (200 KB) fica em `cdn.jsdelivr.net` (o app pede confirmação desse domínio).

| Teste | Caminho (depois da base) | Esperado |
|---|---|---|
| Botão que abre nova guia | `v4/tabs/start.html` | tenta clicar; sem efeito ⇒ destaca "Continuar"; ao tocar, abre guia que vira a de trabalho ⇒ arquivo confirmado |
| Popup de anúncio × guia legítima | `v4/popup-ad/start.html` | "Receber prêmio" abre propaganda ⇒ fechada sozinha; "Continuar" abre a guia legítima |
| Botão após contagem | `v4/timer/start.html` | espera ~6 s; clica só quando o botão é liberado |
| Botão dinâmico | `v4/dynamic/start.html` | botão aparece após ~2,5 s ⇒ clique ⇒ arquivo |
| Link dinâmico | `v4/dynamic/link.html` | link aparece após ~2,5 s ⇒ verificação ⇒ arquivo |
| Pausa humana simulada | `v4/human/start.html` | pausa; toque "Sou humano" (ou "Já resolvi") ⇒ retoma |
| Combinado | `v4/combo/start.html` | botão ⇒ nova guia ⇒ temporizador ⇒ pausa humana ⇒ arquivo |
| Popup repetitivo | `v4/popup-flood/start.html` | popups sem gesto bloqueados; se você tocar na página, no máx. 3 abrem e são fechados; segue o link legítimo |


## v0.4.1 — correção: resultado confirmado preservado ao alternar guias
Bug do teste real (`v4/tabs/start.html`): depois de **Arquivo confirmado**, alternar/usar guias reiniciava a análise (`setWorkTab` religava uma análise concluída), a página já visitada contava como loop e o resultado virava **Loop detectado**.
- **Resultado confirmado é imutável:** nenhum evento posterior (navegação, guia aberta/fechada, mudança no DOM, seleção de guia) o substitui.
- **Selecionar ≠ retomar:** tocar nos chips só muda a guia visível. Depois do fim, "Usar esta guia" virou **Retomar nesta guia**, uma ação explícita com confirmação; durante a análise ativa continua sendo "Usar esta guia".
- **Retomada explícita:** inicia uma nova etapa; se já havia arquivo confirmado, o novo resultado aparece **separado** ("Retomada #n") e o confirmado é mantido. Se o resultado anterior era só um candidato, o novo o substitui.
- **URL já confirmada não é loop:** voltar a ela (inclusive numa retomada) conta como sucesso ("já confirmado"), nunca como loop.
- **`window.open` exige gesto humano:** páginas cujos scripts chamam `window.open` (ou botões/links que abrem guia) **nunca recebem clique automático**; o app destaca o botão direto e espera o toque.
- **DOM ≠ nova guia:** uma alteração do DOM não retoma a espera nem conta como "guia aberta"; só a guia criada (ou uma navegação) prova o efeito.
- Guias abertas/fechadas depois do fim não alteram resultado, caminho nem estado.


## v0.4.2 — repositórios GitHub e ROMs
Problema real (`https://github.com/retrobrews/snes-games`): 150 candidatos (`astrohawk.smc`, `blt.sfc`, `bucket.smc`…) todos com pontuação 10 e resultado "Nenhum candidato". Causas: `.smc`/`.sfc`… não eram extensões de arquivo, as URLs `/blob/` são páginas HTML de visualização, e o scanner cortava a lista nos primeiros 150 elementos do DOM.
- **Extensões de ROM:** `smc sfc fig swc nes unf fds gba gb gbc sgb n64 z64 v64 nds dsi 3ds cia sms gg gen smd 32x pce sgx a26 a78 j64 ngp ngc ws wsc vb col rom chd cso pbp wad nsp xci` (`.md` fica de fora: é Markdown).
- **`/blob/` ≠ arquivo:** `GithubUrls` reconhece `github.com/<dono>/<repo>/blob/<ref>/<caminho>` como **página de visualização** (classe *página de visualização de arquivo*), mesmo terminando em `.smc`; nunca vira "candidato de download" nem "arquivo confirmado". Pontuação: +45 pela extensão conhecida, +10 se o texto do link é um nome de arquivo, +5 por contexto de listagem; `README.md`, pastas (`/tree/`) etc. continuam baixos.
- **Link Raw:** na página de visualização o app usa o link **que o próprio GitHub mostra** (`Raw file content`, `Download raw file`, `View raw` → `/raw/…`). Se, depois da 1ª varredura, o GitHub não expôs nenhum, o app **deriva** `…/blob/…` → `…/raw/…` (o GitHub responde 302 para `raw.githubusercontent.com`). Links para outros arquivos da árvore lateral não competem enquanto o Raw não aparece.
- **Confirmação:** a URL Raw é verificada por **HEAD/Range** (OkHttp); o 302 para `raw.githubusercontent.com` (domínio novo) **pede confirmação humana**; só `application/octet-stream` etc. confirma — HTML (`text/html`) não. Extensão sozinha nunca confirma.
- **Prioridade antes do corte:** o scanner agora coleta até 1500 elementos, ordena por relevância (extensão, Raw/download, `download`, redirecionamentos) e mantém **todos os candidatos de arquivo** (até 500) + os 150 demais mais relevantes: nada relevante no fim da página se perde. Nomes de ROM como "Super Bet Win.smc" não são tratados como propaganda; anúncios continuam ignorados.
- **Teste real:** o workflow *LinkResolver live GitHub check* varre `retrobrews/snes-games` de verdade (Chromium) e roda o motor completo com HEAD/Range reais até a URL Raw (`LiveGithubTest`); o relatório fica no resumo do job e no artifact `live-github-scans`.
