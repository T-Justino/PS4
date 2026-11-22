# Viabilidade: Android (Termux) como resolvedor local (22/11/2026)

Só investigação: nada foi instalado ou implementado; código do projeto, SSPI e PS4 intocados.
Fluxo alvo: **Android → resolução → URLs finais validadas → painel Phone Companion do SSPI → download/instalação no PS4.** O SSPI continua baixando e instalando; o Android não baixa PKG.

Legenda: **VERIFICADO** = conferi no código deste projeto ou do SSPI; **FONTE** = relato público (link); **NÃO TESTADO** = hipótese.

## Recomendação (objetiva)
1. **MVP: Termux + Python puro + `resolver.py` (sem Playwright).** `resolver.py`, `net.py` e `links.py` usam só a biblioteca padrão (**VERIFICADO**; `pyproject`: `dependencies = []`, Python ≥ 3.11). Rodam em Termux sem adaptar. A suíte sem Playwright (193 testes) é a que importa aqui.
2. **Páginas dinâmicas: modo assistido pelo navegador do próprio Android**, não Playwright. Você abre a página no Chrome/Firefox, faz a ação (botão, CAPTCHA), e **compartilha** a URL para o Termux; o resolvedor valida, segue redirects HTTP e organiza volumes RAR.
3. **Não apostar em Playwright no Android** (limitações abaixo). Se ainda assim quiser tentar, fica como experimento secundário, depois do MVP.
4. Integração com o SSPI: **somente copiar e colar** no Phone Companion (sem presumir API de envio).

## Arquitetura mínima
```
Navegador do Android ──(Compartilhar)──► Termux: ~/bin/termux-url-opener
                                              │  python -m ps4store resolve <URL> [--profundidade 2]
                                              ▼
                              resolver.py (crawl + group_sets, já existente)
                                              │  saída "para colar": 1 URL por linha, RAR em ordem
                                              ▼
                       termux-clipboard-set (Termux:API)  ──►  área de transferência do Android
                                              │
                                              ▼
              Navegador do Android → página do Phone Companion (QR do SSPI) → Downloads → colar → enviar
```
Também funciona sem compartilhar: `python -m ps4store resolve URL` no próprio Termux. Código novo previsto (não implementado agora): um formatador "para colar" (~40 linhas) e o script `termux-url-opener` (~5 linhas). Nada no PS4 e nenhum VPS/PC.

## Como apresentar as URLs ao SSPI (VERIFICADO no código do SSPI)
- O painel recebe **um link por linha** num campo de texto; **no máximo 50 links por envio** e, se passar, **nada é enfileirado** (`PairServer.cs:107`).
- Volumes `.partNN.rar` são agrupados sozinhos pelo nome; para outros estilos (`.rar` + `.r00`) é preciso marcar "parts of one RAR archive, in volume order" (já exposto por `markMultipartInSspi` no resolvedor).
- **URL individual:** a URL estável de entrada do resolvedor (`sspiUrl`), nunca a URL assinada final (expira em ≈ 6 h; o SSPI refaz o redirect pela estável). Se o host de entrada é `github.com` (TLS já falhou no SSPI), o resolvedor já troca pela URL final de `raw.githubusercontent.com`.
- **Lista RAR:** bloco único, na ordem 01…N, **sem misturar com PKG avulso** no mesmo envio quando houver dúvida; avisar se o conjunto tem mais de 50 volumes (o painel não envia em lotes de um mesmo conjunto) ou se está INCOMPLETO.
- Resultado e status ficam no texto; só o que for `OK` e "enviável ao SSPI" entra no bloco copiável.

## Playwright no Android: o que se sabe
- **Nenhum pacote "playwright-termux" encontrado** na minha busca; não encontrei fonte mantida para recomendar (não posso afirmar que não exista). **Não escolheria uma dependência assim sem manutenção verificável.**
- **FONTE:** Playwright já recusou instalar no Termux com "Unsupported platform: android" ([issue #6105](https://github.com/microsoft/playwright/issues/6105), versão antiga) e um projeto de controle por ChromeDriver afirma que Playwright e Selenium não funcionam em Android aarch64 ([cdriv](https://draken119.github.io/cdriv/)); guias de comunidade mostram Selenium + Chromium do Termux User Repository funcionando com ressalvas de versão ([guia 1](https://gist.github.com/HunterXProgrammer/beb06a5387bee78ee321fbe3c724d95e), [TUR](https://github.com/termux-user-repository/tur)). Fontes divergentes: **tratar como NÃO TESTADO**.
- **Expectativa técnica (NÃO TESTADO):** as rodas do `playwright` para Linux aarch64 são glibc (manylinux) e trazem um driver Node glibc; o Termux usa a libc do Android (bionic). O `pip` tende a rejeitar a roda e o driver não executaria. Contornar com Node do Termux (`PLAYWRIGHT_NODEJS_PATH`) e `executable_path` para o Chromium do TUR é uma gambiarra teórica que **não verifiquei**.
- **Chromium no Termux:** vem do TUR (repositório da comunidade, binários pré-compilados), não do repositório oficial; versão e confiança dependem do mantenedor do TUR.

## Alternativas mais simples para JavaScript (da mais simples à mais pesada)
1. **Assistido no navegador do Android + Compartilhar → Termux** (recomendado; zero dependência nova; já alinhado ao `INTERACAO_NECESSARIA` do resolvedor).
2. **Resolução pré-computada na nuvem** (GitHub Actions + `browser.py`) para fontes conhecidas; o Android só busca no catálogo web.
3. Selenium/ChromeDriver do TUR (anedótico, versões presas, frágil).
4. Cliente CDP mínimo falando com o Chromium do TUR (mais código, mais manutenção).
5. Script de usuário num navegador Android com extensões (Firefox + gerenciador de scripts): **NÃO TESTADO**; fora do escopo.

## Dependências (mínimas)
| Item | Para quê | Observação de segurança/manutenção |
|---|---|---|
| Termux (**F-Droid ou GitHub**, não a versão da Play Store) | shell + Python | a versão da Play é um fork não oficial; não misturar origens entre Termux e seus plugins ([anúncio](https://github.com/termux/termux-app/discussions/4000)) |
| `pkg install python` | rodar `ps4store` | repositório oficial do Termux; Python ≥ 3.11 |
| Termux:API (opcional) + `pkg install termux-api` | copiar para a área de transferência | do mesmo canal do Termux; permissões mínimas |
| `~/bin/termux-url-opener` | receber URL do botão Compartilhar | nativo do Termux ([exemplos](https://gist.github.com/amygrinn/4b4f4d37e630988eff4d881e4e26360d)); o script precisa de `chmod +x` |
| Código do projeto (`git clone`) | `resolver.py` etc. | sem `pip install` de terceiros no MVP |

Cuidados: o Android 12+ pode matar processos de fundo (*phantom process killer*, [guia](https://raw.githubusercontent.com/AidanPark/openclaw-android/main/docs/disable-phantom-process-killer.md), não oficial); o MVP roda comandos curtos em primeiro plano, então não precisa de serviço de fundo nem desse ajuste. Não abrir servidor local nesta fase; se um dia houver, só em `127.0.0.1`.

## Prova de conceito mínima (fontes e arquivos próprios)
Sem Playwright. Usa o que já existe: PKG e os 11 volumes RAR próprios no repositório e a página `rartest` no GitHub.

Roteiro no Android (marque ✔/✘ e anote o que ocorrer):
1. **Instalar Termux** (F-Droid/GitHub) e `pkg update && pkg install python git`. ✔ abre e `python --version` ≥ 3.11.
2. **Clonar** o repositório (`git clone … && cd PS4`, branch `ccr-8aace08a-bzwy8i`) e rodar a suíte sem Playwright: `PYTHONPATH=src python -m pytest -q` (se `pytest` faltar: `pip install pytest`). ✔ **193 passam, 1 pulado**.
3. **URL direta:** `PYTHONPATH=src python -m ps4store resolve https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/pkgs/PS4StoreBRTest_CUSA95417_v1.02.pkg`. ✔ `OK … 6,6 MB … enviável ao SSPI`.
4. **Página com vários links e volumes RAR:** `… resolve https://github.com/T-Justino/PS4/tree/ccr-8aace08a-bzwy8i/rartest --max-paginas 30 --max-requisicoes 80`. ✔ **11 volumes, completo, 6,6 MB**, URLs `raw.githubusercontent.com` em ordem.
5. **Redirecionamento real:** `… resolve https://pkg-zone.com/download/ps4/OPEN00001/1.01`. ✔ `OK 19,8 MB` (redirect para `api.pkg-zone.com`).
6. **Página dinâmica (assistida):** abrir `https://pkg-zone.com/` no Chrome do Android, tocar num item, **Compartilhar** a URL do download → Termux (com o `termux-url-opener` configurado, ou colar no comando). ✔ o resolvedor classifica o link.
7. **Entrega ao SSPI:** copiar o bloco de URLs; no PS4 abrir o SSPI → QR do Phone Companion → Downloads → colar → enviar. ✔ OpenTyrian (1 link) entra na fila e baixa; ✔ o conjunto RAR (11 linhas coladas, ordem 01…11) é reconhecido como um RAR.
8. **Registrar:** versão do Android, origem do Termux, versão do Python, tempo de cada comando, falhas.

Critério de decisão: se 1 a 5 passarem, o Android já resolve tudo que **não** depende de JavaScript, sem PC/VPS. Se o passo 6 for tolerável, o modo assistido basta; só então vale considerar Playwright/Selenium (experimento à parte).
