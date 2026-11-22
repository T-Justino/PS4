# Etapa 4D: viabilidade de executar tudo no PS4 (22/11/2026)

Só investigação: nada foi implementado ou instalado; `browser.py`, `resolver.py`, SSPI, OrbisFox, catálogo e workflow não foram tocados. Base: código do OrbisFox (commit `e257fdf`, lido em clone somente-leitura), código público do SSPI (`1295abb`) e as evidências reais do seu PS4 Pro 9.00 neste projeto.

## Legenda
- **COMPROVADO** = já observado no **seu** PS4 (testes deste projeto).
- **CÓDIGO** = visto no código-fonte, nunca executado por nós.
- **AUTOR** = o que a documentação do projeto afirma (inclusive o que o autor diz ter visto no console dele).
- **NÃO TESTADO** = hipótese.

## O que já é comprovado no seu console
- App homebrew próprio (OpenOrbis) instala e abre no 9.00 + GoldHEN (T8b). **COMPROVADO**
- SSPI baixa por link colado, instala e executa (OpenTyrian, Live Die Repeat) e extrai RAR multipartes. **COMPROVADO**
- A pilha TLS do sistema (`libSceHttp`/`libSceSsl`, a que o SSPI usa) **falha em sessões longas** (`0x8095F00C`/`0x809517D5`) e reiniciar o processo restaura. **COMPROVADO** (logs 22/11)

## As três alternativas

| | 1. Homebrew nativo próprio | 2. OrbisFox (Gecko) | 3. Linux no PS4 |
|---|---|---|---|
| Roda JavaScript de página | **Não** sem motor + DOM (QuickJS não tem DOM; portar jsdom é inviável) | **Sim** (SpiderMonkey, só interpretador, sem JIT, sem WebAssembly) **AUTOR** | Sim (Firefox/Chromium de Linux) NÃO TESTADO |
| Roda no seu 9.00 | Cadeia de build **COMPROVADA** | **NÃO TESTADO**: o autor relata bring-up em **11.00** (`docs/HARDWARE.md`) | NÃO TESTADO |
| Controle por programa | Total (é seu código) | **Nenhum pronto**: sem Marionette/DevTools/CLI/socket de controle (busca no código) | Total (Playwright roda em Linux) |
| TLS | `libSceSsl` do sistema: mesmos problemas já **COMPROVADOS** | NSS próprio do Gecko (independe da `libSceSsl`); validação no console ainda "pendente" segundo o autor **AUTOR** | Do Linux |
| SSPI no mesmo ambiente | Sim, mas um app por vez | Sim, mas um app por vez | **Não**: substitui a sessão do OrbisOS |
| Esforço | Médio (C + sceHttp), mas sem JS dinâmico | Alto para automatizar (mexer no shell/rebuild) ou **zero** para uso manual | Alto e fora do objetivo |

## Respostas

**1. O Playwright pode ser portado?** Não. Ele precisa de Node/Python e de um protocolo de controle (CDP/Juggler/WebKit) falando com um navegador; nada disso existe no PS4. No OrbisFox o equivalente seria **JavaScript de chrome dentro do próprio navegador** (outro mecanismo, não Playwright).

**2. O OrbisFox permite controle programático, JavaScript e extração de links?**
- JavaScript de página: sim **AUTOR** (interpretador; lento; sem Wasm).
- Controle externo: **não encontrei** nenhum (sem Marionette, remote debugging, CLI ou socket). A entrada é só controle + teclado próprio (`README.md`).
- Extração: o shell é JavaScript de chrome com *system principal* (`gecko/orbisfox/fixtures/browser-shell-host.js`) e já acessa o documento da aba (`tab.nav.document`), então **em tese** um script de chrome poderia varrer `a[href]` e botões **CÓDIGO**. Isso exige alterar o shell e reempacotar; o build completo pede **100 GB+** de disco num Linux (`README.md`). Se dá para trocar só o JS de chrome sem refazer o motor, **eu não sei**.
- Não há ponte de saída: `nsIOrbisFoxHost` só tem entrada/tela/teclado/log, nada de arquivo, rede para outros apps ou área de transferência **CÓDIGO**.

**3. Dá para usar o WebKit nativo do PS4?** Em tese só como visualizador para uma pessoa (diálogo do navegador do sistema). Não conheço API que deixe um homebrew ler o DOM ou executar JS nele, e a política de mesma origem impede ler uma página de terceiros. **NÃO TESTADO**, probabilidade baixa.

**4. Reaproveitar a lógica do `resolver.py` sem portar o Python?** O que ele faz é regex, HTTP com Range, redirects e agrupamento de volumes RAR: cerca de 600 linhas, portáveis. Python no PS4 não é opção (**NÃO TESTADO**, sem porta conhecida). Opções: reescrever em C (app OpenOrbis + `sceHttp`) ou em C# dentro do SSPI (mexer no SSPI está fora do escopo). A parte dinâmica (JavaScript) continua sem solução fora do OrbisFox.

**5. Como o resultado chegaria ao SSPI?** (todas **CÓDIGO**, nada testado por nós)
- **Digitar no próprio SSPI:** Configurações → *My files* → "Paste a download link" tem teclado na tela (`SearchWindow.cs` 4130 e 1845, até 8192 caracteres, R2 enfileira). Funciona para link curto/estável, p.ex. `pkg-zone.com/download/ps4/OPEN00001/1.01` (42 caracteres). Não há colar entre apps.
- **Página do celular (QR):** exige o SSPI aberto, o celular e a mesma rede; um app nativo **não roda ao mesmo tempo** que o SSPI, e o *resident worker* não escuta em nenhuma porta (busca no código).
- **Pasta de entrada `/data/SSPI/pkg-rars`:** o SSPI e o worker residente processam **arquivos** PKG/RAR que aparecerem ali, mesmo com o SSPI fechado (`FtpInbox.cs`). Serve para quem **baixa o arquivo**, não para entregar uma URL.
- **Catálogo `.gssource` por URL:** já **COMPROVADO** (T9), mas só aceita IDs CUSA.
- Não há API de URL entre apps.

**6. O que exige menos desenvolvimento e tem mais chance?**
1. **Menos esforço e maior chance, hoje:** a resolução **pré-computada na nuvem** (GitHub Actions + `browser.py`) alimentando o catálogo web e o SSPI. Não roda no PS4, mas também não depende de PC/VPS seu durante o uso.
2. **Único caminho 100% no console com JavaScript real:** OrbisFox. Em **uso manual** o custo de desenvolvimento é **zero**; a automação seria trabalho alto e incerto.
3. App nativo próprio: só resolve HTTP estático (o que o resolvedor atual já faz); a lacuna que importa é o JavaScript.
4. Linux: descartar (veja o limite abaixo).

**7. Limites a considerar**
- **Memória:** o OrbisFox é limitado pela *flexible memory*, não pela RAM total (`docs/MESA_WEBRENDER.md`); o autor mediu 86 a 242 MB livres em amostras (`docs/HOMEBREW_SDK.md`), até 3 abas, **travamentos de vários segundos** e **quedas ainda sem causa** **AUTOR**.
- **TLS:** o SSPI e um app nativo próprio sofrem o esgotamento/falha da `libSceSsl` **COMPROVADO**; o Gecko usa NSS próprio (pode escapar do problema, **NÃO TESTADO** no 9.00).
- **Segurança:** o conteúdo roda no mesmo processo, sem sandbox; o próprio README manda evitar contas sensíveis e navegação não confiável. Sem bloqueador de anúncios e sem a lista de hosts permitidos do nosso resolvedor.
- **Estabilidade:** alfa inicial para desenvolvedores, sem suporte garantido por modelo/firmware (README). Um app por vez no console.
- **Linux:** o jailbreak do 9.00 não é persistente (reinício exige refazer tudo) ([wololo](https://wololo.net/2021/12/14/ps4-how-to-run-the-ps4-9-00-jailbreak-full-guide-with-goldhen-payload/)); iniciar Linux ocupa o console no lugar do OrbisOS, então o SSPI não roda junto. Não encontrei fonte confirmando os detalhes de um carregador Linux para 9.00; não verifiquei.

## Prova de conceito mínima proposta (uma só)
**"OrbisFox no 9.00 + link digitado no SSPI", sem escrever código.** Nada de PC ou VPS: só instalar o pacote publicado pelo autor (`OrbisFox SDK Test`, `ORHB00001`, **sem modificá-lo**), usando o instalador que você já usa.

Roteiro e critérios (anote exatamente o que aconteceu):
1. **Abre e não cai?** (aceite: abre; fica 10 min com 1 aba sem fechar sozinho).
2. **TLS:** abrir `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/README.md` e `https://pkg-zone.com/` (aceite: carrega sem erro de certificado).
3. **JavaScript real:** em `https://pkg-zone.com/` (que o resolvedor HTTP não vê, mas o Chromium viu 3 links) e em `https://t-justino.github.io/PS4/` (lista montada por JS). Aceite: a lista aparece renderizada e dá para ler o nome/link de OpenTyrian.
4. **Ver a URL:** a barra de endereço mostra o endereço final depois do clique/redirecionamento (aceite: legível).
5. **Encaminhar ao SSPI:** fechar o OrbisFox, abrir o SSPI → Configurações → *My files* → "Paste a download link" e digitar a URL curta do OpenTyrian; **R2** enfileira (aceite: o item entra na fila e baixa).
6. Registrar: modelo, firmware 9.00, versão do OrbisFox, tempo de estabilidade, se travou, e (se ligar diagnósticos nas configurações) a memória *flexible* livre.

**Decisão a partir do resultado:** se 1 a 4 passarem, vale estudar a extração por script de chrome (próxima etapa, com a pergunta aberta sobre trocar só o JS sem refazer o motor); se 1 falhar no 9.00, o caminho OrbisFox cai e a melhor opção continua sendo a resolução na nuvem + SSPI; se o 5 passar, o encaminhamento manual no console já existe e comprovamos que dá para trabalhar sem celular.
