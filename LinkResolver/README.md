# Link Resolver (MVP)

App Android nativo (Kotlin + WebView + AndroidX, minSdk 29 / Android 10+) que recebe a URL de uma página e
acompanha o fluxo de navegação até identificar a URL de um **download de arquivo autorizado**.
O app **nunca baixa o arquivo**: o `DownloadListener` apenas entrega URL e metadados. Sem integração com PS4/VPS nesta fase.

## Instalação
1. Android Studio Ladybug (2024.2) ou mais novo, JDK 17 (embutido no Studio).
2. `File ▸ Open…` e escolha a pasta `LinkResolver/` (esta). O Studio baixa o Gradle 8.9 (wrapper) e o SDK 35 se faltar.
3. Execute em um emulador/aparelho com Android 10+ (API 29+) que tenha o **Android System WebView / Chrome atualizado** (Safe Browsing depende dele).
4. Linha de comando: `./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`; `./gradlew testDebugUnitTest` roda os testes de unidade.

## Como usar
1. Digite uma URL `https://…` e toque em **Analisar** (compartilhar uma URL de outro app para o Link Resolver também preenche o campo).
2. Abas inferiores: **Navegador** (WebView + abas), **Candidatos** (links/botões detectados com pontuação e motivos; botão *Seguir*/*Clicar* para ação manual), **Histórico** (etapas), **Resultado**.
3. A automação só segue candidatos com pontuação ≥ 40 em domínios já confiáveis. Domínio novo ⇒ diálogo *Permitir domínio / Só desta vez / Negar*.
4. CAPTCHA, verificação anti-robô ou login ⇒ a automação **pausa**; resolva na própria página. Ela retoma sozinha quando o desafio deixa de ser detectado (ou toque em *Já resolvi — verificar*).
5. Resultado: URL (valores sensíveis mascarados), host, MIME, nome estimado, tamanho, pontuação, evidências, diagnóstico de erro, candidatos, histórico e estado: **Arquivo confirmado**, **Candidato não verificado**, **Link intermediário**, **Exige sessão**, **Erro de rede**, **Nenhum candidato encontrado**, **Bloqueado**.
   URLs com cara de arquivo são validadas por **HEAD** (ou **GET com `Range: bytes=0-0`**) antes de navegar — só cabeçalhos, sem baixar o corpo, sem cookies, com checagem de IP interno a cada salto. O `DownloadListener` é evidência adicional. Páginas de erro do navegador (`chrome-error://`) nunca são analisadas. *Copiar URL* copia a URL completa (se tiver token/assinatura, o app avisa e marca a área de transferência como sensível no Android 13+).

## Como testar
**Unitários (JVM, sem emulador):** `./gradlew testDebugUnitTest` — 48 testes (segurança de URL, heurísticas, scanner, motor: loops, limites, domínios, CAPTCHA, sessão). Estes testes também foram executados na JVM durante o desenvolvimento.

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
