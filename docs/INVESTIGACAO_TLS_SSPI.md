# Investigação: erro TLS `0x8095F00C` no SSPI (RAR dividido e Live Die Repeat)

**Escopo:** transporte do SSPI. O robô de descoberta/validação **não foi alterado**. Nenhuma verificação TLS foi desativada; nenhuma mudança de firmware é proposta.
**Fonte do código:** `xyhlo/SSPI` público (`main`, commit `1295abb`, 23/10/2026), que **difere do binário instalado** (`package=20261003155605`, build `0eb783eca1f3`; ver §8); os `.pem` não estão no repositório.

> **ESTADO ATUAL (seções 8 e 9):** com os logs reais do PS4, a hipótese de cadeia de certificados (H1 abaixo) **deixou de ser a principal**. A mesma cadeia do `raw` foi aceita 6 vezes e depois recusada no mesmo processo; reiniciar o SSPI destravou o download. A causa mais provável é **estado/esgotamento do TLS no processo**, ainda **não provada**. As seções 0 a 7 ficam como histórico.

## 0. Correção da hipótese anterior (retirada)
A versão anterior deste documento dizia que o RAR era baixado pelo **worker residente** (que não fixa o certificado do GitHub). **A foto do 5A mostrava "In-app · keep SSPI open · Downloading" e isso refuta aquela explicação.** Reli o código:
- O rótulo vem de `app/SearchWindow.cs:3739` (`ActiveTransferOwnerText`): só aparece se o job **não** for do residente (`item.Background && item.BgftResident` mostraria "Resident owns this job").
- No modo In-app, `TryHandoffArchive` não é usado (exige `UseBgftDirect`); o RAR vai por `DownloadArchiveVolumes` (`app/DownloadManager.Archive.cs:406-520`), com o status `RAR volume i/N · Keep SSPI open`.
- Além disso, a cadeia real de `raw.githubusercontent.com` **já está fixada** (seção 2). Logo "falta pin no worker" não explica o 5A.

## 1. Pilha de rede e rotina de sondagem, RAR em modo In-app (código)
1. **Loop por volume:** `DownloadArchiveVolumes` baixa os volumes **um a um**; para cada um chama `NetHttp.DownloadFileResumable` (`DownloadManager.Archive.cs:~480`) dentro de `DownloadLinkRecovery.Run` (renovação de link, só útil com provedores).
2. **Motor:** `NetHttp.cs:351` → `TransferClient.Download` (`app/TransferClient.cs:118-190`) → módulo nativo **`libSspiTransfer.prx`** (`sspi_xfer_start/poll`), o **mesmo `transfer/gs_xfer.c`** do worker (por isso a mensagem é a do motor nativo, `gs_xfer.c:1217/1427`).
3. **Contexto TLS:** `sspi_xfer_init(NativeHttp.TransferContext)` (`TransferClient.cs:58-67`): o contexto `sceHttp` do **app** (`NativeHttp._httpCtx`, `NativeHttp.cs:154`), cuja confiança é montada em `TryLoadBundledRoots` (`NativeHttp.cs:305-372`): **subconjunto curado de raízes** (`NativeRootSubjectMarkers`, `:75-92`: ISRG X1/X2, DigiCert Global G2/Trusted G4, GlobalSign R3/R6/R46, USERTrust RSA/ECC, COMODO RSA, Sectigo R46/E46, Amazon Root CA 1, GTS R1–R4, GoDaddy G2, Microsoft RSA 2017) **+ pins** (Let's Encrypt Gen Y, GitHub Sectigo, GoDaddy G2, Google WE1 cross-sign, GeoTrust).
4. **Sondagem:** cada transferência (cada volume) faz uma **sondagem nova** (`gs_xfer.c:1330-1394`): `gs_http_open` com `Range 0-0xFFF`, **sessão nova**, fechada ao fim (`gs_http_close`), com redirects manuais (`gs_http.c:268-300`, até 8 saltos, só HTTPS→HTTPS). Em `0x8095F00C` repete com espera e só desiste (`tls_episode_terminal`, `:692-701`) após **≥ 8 falhas, ≥ 120 s, todas as lanes testadas e nenhum byte útil**: é a mensagem "…two minutes with no useful progress".
5. **Pacote único vs RAR:** um PKG faz **1 sondagem + lanes** (poucas sessões novas). Um RAR de 11 volumes faz **11 sondagens independentes + 11 conexões de dados** (≈ 22+ handshakes novos), e **um** volume cuja sondagem falhe por 2 min derruba o conjunto (`Retry` recomeça no volume 7, `.part` durável).
6. **Validadores:** o motor só paraleliza/retoma com ETag **forte** ou `Last-Modified` válido; senão usa **uma conexão** por arquivo (`gs_xfer.c`, `fallback_reason`).

## 2. O que as cadeias reais mostram (GitHub Actions, sem interceptação; `docs/evidencia/tls-cadeias-22-11-2026.md`)

| Host | Cadeia servida | Âncoras do SSPI |
|---|---|---|
| **`raw.githubusercontent.com`** (e `release-assets`/`objects`/`github.io`) | folha `*.github.io` ← **LE `YR1`** ← **`Root YR` (versão cruzada por ISRG X1)** | `YR1` **fixado**; raiz `Root YR` fixada é a **autoassinada** (outro certificado); a servida é a cruzada (`072639D0…`, não fixada) |
| `github.com` | Sectigo `DV E36` (ou `R36`) ← Root E46/R46 | intermediário **fixado** + raízes na lista |
| **`api.pkg-zone.com`** (Cloudflare) | folha ← **GTS `WE1`** (comum) ← GTS Root R4 | raiz na lista; o pin do SSPI é o **WE1 *cross-sign***, **não** este `WE1` |
| `pkg-zone.com` | LE `YE1` ← Root YE ← ISRG Root X2 | `YE1` fixado |
| **`cdn.jsdelivr.net`** | `*.jsdelivr.net` ← Sectigo **`DV R36`** ← Root R46 | **fixado** (o mesmo `R36` do GitHub) + raiz na lista |
| `archive.org` | GoDaddy G2 (intermediário) ← Go Daddy Root G2 | **fixado** + raiz na lista |
| `gitlab.com` / `codeberg.org` | Sectigo R36 / LE `YE1` | fixados |
| `storage.googleapis.com` | GTS `WE2`/`WR2` ← GTS R4/R1 | raiz ok; `WE2` **não** fixado |
| `s3.amazonaws.com`, `huggingface.co` | Amazon RSA 2048 M01 ← Amazon Root CA 1 | raiz ok; intermediário não fixado |

**Leitura:** (a) para o `raw`, o intermediário **está fixado**; o que pode atrapalhar é o servidor enviar também a `Root YR` **cruzada**, que o firmware antigo pode tentar seguir ("Older NanoSSL firmware may not build even the shortened chain", `NativeHttp.cs:~120`). (b) `api.pkg-zone.com` usa o `WE1` **comum**, que o SSPI **não** fixa: é o cenário que o autor descreve como "firmware chain discovery". (c) O primeiro erro TLS da sessão (download em `github.com/.../releases/...`) acabou no **mesmo conjunto de certificados Gen Y** (`release-assets.githubusercontent.com`), não em `github.com`.

## 3. Hipóteses revistas (da mais para a menos provável)
**H1 (principal): construção de cadeia pelo firmware antigo em hierarquias novas (LE Gen Y no `raw`; GTS WE1 no `api.pkg-zone.com`), de forma intermitente.** É o modo de falha que o próprio autor documenta ("unknown CA intermittently with both roots loaded"). Explica hosts/CAs diferentes com o mesmo `0x8095F00C`, os 6 volumes que passaram e o 7º que falhou, e o Retry que repetiu (a borda/IP escolhido pode persistir por alguns minutos). *Não confirmada.*
**H2: data/hora do console** (`verify` 0x08/0x10): o certificado folha do `raw` é recente (`*.github.io`, expira 29/12/2026). Se o relógio do PS4 estiver atrasado, folhas novas parecem "ainda não válidas"; intermitente se as bordas alternarem folhas.
**H3: borda específica** com variante de certificado/cadeia (`verify` 0x20 ou 0x04).
**Descartada:** "worker residente sem pin do GitHub" (pilha In-app confirmada; `YR1` fixado).

## 4. Registros que confirmam host, `verify` e rota
Local: `/data/SSPI/logs/` (`SspiLog.cs:17-25`): `download.log`, `network.log`, `resident.log`, `combined.log` (`startup.log` também). URLs são trocadas por `[url]` (`SspiLog.Clean`), mas `host=` aparece.

| Procure em | O que confirma |
|---|---|
| `download.log`/`combined.log`: **`event=preparation-probe-failed … hex=0x8095F00C … ssl=0x… verify=0x… errno=0x… host=…`** (`gs_xfer.c:1385-1390`) | **host real** que falhou; **`verify`**: `0x20` emissor desconhecido (H1/H3) · `0x08/0x10` datas (H2) · `0x04` nome do host/DNS; **estágio** (`phase=`/`stage=`) |
| mesma linha, **`attempt=`** e o campo de tempo `ms=` | quantas tentativas e em quanto tempo (confirma ≥ 8 falhas em ≥ 120 s) |
| `download.log`: `event=retry … raw=… hex=0x8095F00C … scope=tls-quarantine … reused=` | se houve reaproveitamento de conexão |
| `network.log`: `native_http ready=true … native_gen_y=N; native_gen_y_intermediates=N; native_github_intermediates=N; sceHttpsLoadCert=0` (`NativeHttp.cs:~315-345`) | **quais pins o app carregou nesta execução** (se `native_gen_y*` = 0, os pins Gen Y não foram carregados) |
| `network.log`: `sceHttp send 0x8095F00C host=… ssl=0x… verify=0x…` (`NativeHttp`) | mesmo dado vindo do HTTP do app |
| **Rota:** status do cartão `RAR volume 7/11 · Keep SSPI open` + **ausência** de `Handing RAR volumes to resident downloader`/`Checking RAR part` e de `Resident owns this job` | confirma **In-app** (motor `libSspiTransfer.prx`) |

## 5. Como coletar sem mexer no PS4
A **página do celular do SSPI tem uma aba *Logs*** (`app/PhoneCompanion.html:422-440`): lista "Log files" (grupo SSPI: `combined.log`, `download.log`…), "Kernel log" e **"Save a report"**. A página **guarda no próprio celular o `combined.log` enquanto está conectada** (`:1732`), então, se ela estava aberta durante o teste, o log do 5A pode já estar lá.
1. Abra a aba **Logs**, toque em `combined.log` (e `download.log`, `network.log`) e **copie as linhas** com `preparation-probe-failed`, `tls-quarantine`, `sceHttp send 0x8095F00C` e `native_http ready`.
2. (Alternativa) *Save a report* e me envie o arquivo/trecho.
Sem FTP, sem PC e sem alterar o PS4. **Verifique também a data/hora do console** (Settings → System → Date and Time).

## 6. Hospedagem HTTPS alternativa para os 11 volumes
Critério: a cadeia termina em raiz **carregada** pelo SSPI e o **intermediário é fixado** (sem depender de "descoberta de cadeia"), com `Range` e sem conta nova.

| Opção | Cadeia (medida) | Setup | Observações |
|---|---|---|---|
| **`cdn.jsdelivr.net` (recomendada para o teste)** | Sectigo **R36 fixado** ← Root R46 listada; **evita a Gen Y** | **nenhum** (usa o repositório atual) | 11/11 volumes **idênticos byte a byte** e `Range` 206 em offset arbitrário, conferidos no Actions. ETag **fraco** e sem `Last-Modified` ⇒ o SSPI baixa **1 conexão por volume** (600 KB: sem custo). URL por **commit** é imutável. Só para **nossos** arquivos (open source): a política do jsDelivr não permite outros usos |
| `archive.org` | GoDaddy G2 **fixado** ← GoDaddy Root G2; o motor do SSPI tem tratamento explícito de espelhos do Internet Archive (`gs_xfer.c`) | conta e upload manuais | alternativa mais "provada" pelo autor; só conteúdo próprio |
| `gitlab.com` raw / `codeberg.org` raw | Sectigo R36 / LE `YE1`, ambos fixados | conta + repositório | viável, com setup |
| GitHub Pages / `raw` / Releases | LE Gen Y (`YR1` + `Root YR` cruzada) | — | **a cadeia sob suspeita**; sem ganho |
| Google Cloud Storage, S3, Hugging Face | raiz listada, intermediário **não** fixado | conta (cobrança/termos) | sem vantagem sobre os acima |

**Teste mínimo para decidir (sem desenvolvimento):** repetir o **5A com os links do jsDelivr**: `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/rartest/links-jsdelivr-ordem.txt` (copiar o texto e colar na caixa Downloads; **o mesmo modo In-app**, para só mudar o host).

| Resultado | Conclusão |
|---|---|
| **conclui** 11/11, extrai, instala, abre | a cadeia Gen Y/borda do `raw` era o problema prático; hospedar os RAR (nossos) no jsDelivr |
| falha **também**, com `verify=0x20` em `cdn.jsdelivr.net` | o firmware falha com qualquer cadeia nova/fresca; precisaria de pin no SSPI (autor) |
| falha com `verify=0x08/0x10` | **relógio do console** (H2): ajustar data/hora |
| falha com outro erro (reset, timeout) | deixa de ser TLS: investigar por log |

## 7. Limites
Não vi a cadeia que o **seu** console recebe (outra região/borda pode diferir); o repositório público pode não ser o build instalado; o firmware pode ter raízes próprias. `0x8095F00C` pelo SSPI: a recusa vem da `libSceSsl`. Nada aqui altera o robô nem desativa TLS.

## 8. Evidência real do PS4 (logs `combined/network/download.log`, 22/11/2026; **confirmado** = está no log)

**Confirmado**
- Build: `0eb783eca1f3`, `package=20261003155605` (3/10/2026). `pid=120`, iniciado 14:07:18 BRT, **sem reinício** entre os testes raw (14:13) e jsDelivr (14:40).
- `native_http ready=True … sceHttpsLoadCert=0 PEM_roots=25; native_gen_y=2; native_gen_y_intermediates=4; native_torbox_intermediate=1; native_godaddy_intermediate=1`; **não há** `native_github_intermediates`. Conta: 25 − 2 − 4 − 1 − 1 = 17 raízes do bundle (o código público de 23/10 tem 19 marcadores): este build é anterior aos pins/raízes da GitHub (**inferência aritmética**, não vi os `.pem`).
- **Raw, pid 120:** handles 1 a 6 completaram (614.400 B cada, `complete-structure-verified`, ≈ 0,5 s cada, `host=raw.githubusercontent.com`); o handle 7 falhou na 1ª sondagem com `hex=0x8095F00C ssl=0x8095F00A verify=0x20`. **A mesma cadeia foi aceita 6 vezes e depois recusada no mesmo processo.** Isso refuta "âncora/intermediária ausente" para o `raw`.
- **Depois da 1ª falha, nenhum host funcionou no pid 120** (263 eventos TLS, todos com falha: raw, cdn.jsdelivr.net, orbispatches.com, amptis.com). O teste do jsDelivr foi feito em processo já comprometido e **não diz nada sobre o certificado do jsDelivr** (experimento confundido). Os "3,7 MB" do 2º teste eram da tarefa antiga; o jsDelivr teve `done=0`.
- **`ssl-out-of-memory` real:** `0x809517D5` (tratado pelo SSPI como falta de memória do `libSceSsl`, `NativeHttp.cs:699-720`) aparece 24 vezes nos logs e no mesmo segundo/host em que aparece `0x8095F00C … verify=0x20` (pid 93, `api.pkg-zone.com`, 5603–5604 s). Também há OOM em `orbispatches.com` aos 342 s do pid 120, **antes** do download.
- **Reiniciar o SSPI destravou o download:** após fechar e abrir de novo, o **Retry** na tarefa original do raw foi até o fim (relato do usuário, 22/11/2026).
- Os "sucessos" `ssl=0x0 verify=0x0` nos logs de `stream-retry` são, na verdade, `hex=0x809517D5` (OOM), não handshakes bem-sucedidos.
- Relógio do console: no pid 72 (sessão anterior) o `unix` recuou ≈ 5.049 s sem reinício do processo (`mono_ms` contínuo). Não afeta o pid 120 (inicia coerente com o relato).
- `github.com` falha em todos os pids (esperado neste build: sem âncora E46/USERTrust ECC). Não é a causa do multipart.

## 9. Hipóteses revistas (após os logs; **não provadas**)
| | Hipótese | Evidência a favor | Contra / lacuna |
|---|---|---|---|
| **H-A (principal)** | Esgotamento ou estado comprometido do TLS do processo (pool `sceSslInit` de 16 MiB compartilhado com `sceHttpInit` de 32 MiB, 25 lanes, polling periódico); `verify=0x20` é sintoma de falha de alocação na montagem da cadeia | 6 OK, depois falha persistente em todos os hosts; OOM e `0x20` no mesmo instante; reinício restaura | Não provei vazamento; não há contador de pool no log |
| H-B | Cadeia ausente/instável por host | `github.com` (build sem âncoras); jsDelivr indeterminado (R46/DV R36 podem faltar neste build) | O `raw` foi aceito 6 vezes na mesma cadeia |
| H-C | Relógio do console | pid 72 mostra salto do `unix` | `verify` seria 0x08/0x10, não 0x20 |
| H-D | `orbispatches.com` com problema próprio de cadeia | falha logo após o início no pid 99, enquanto `api.pkg-zone.com` funcionou | não separável nos logs |

**Retirado:** a recomendação do §6 (jsDelivr como solução). O jsDelivr não foi testado em processo saudável; não há evidência de que ajude ou prejudique.

**Menor estabilização (proposta; hipótese):** (1) operacional: reiniciar o SSPI antes de cada multipart; (2) ao mantenedor: reutilizar a conexão TLS entre volumes da mesma origem, e recriar o contexto SSL/HTTP depois de `0x809517D5`/`0x20` seguidos quando não houver handle aberto; (3) registrar o uso do pool SSL a cada falha. Nenhuma verificação TLS é enfraquecida.
