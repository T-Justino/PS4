# Investigação: erro TLS `0x8095F00C` no SSPI (RAR dividido e Live Die Repeat)

**Escopo:** só o transporte do SSPI. O robô de descoberta/validação **não foi alterado** (os links, tamanhos e `Range` estão corretos e foram conferidos). Nenhuma verificação TLS foi desativada e nenhuma mudança de firmware é proposta.
**Fonte:** código público do SSPI (`xyhlo/SSPI`, `main`, commit `1295abb`), lido localmente; **pode diferir do binário 5.11.7 instalado** (os arquivos `.pem` não estão no repositório). Não consegui ver a cadeia real de certificados de `raw.githubusercontent.com`: o ambiente de desenvolvimento intercepta TLS (a cadeia exibida é a do gateway) e o `crt.sh` é bloqueado.

## Sintoma (teste 5A, 22/11/2026)
O SSPI reconheceu os 11 volumes como **um** RAR e baixou os volumes 1–6 (≈ 3,69 MB = 6 × 614.400 B). No volume 7: `Provider TLS certificate not trusted on fresh probe sessions for two minutes with no useful progress (0x8095F00C)`.
O mesmo código apareceu no Live Die Repeat (PKG-Zone/Cloudflare, aos 915,3 MB, depois de uma interrupção). Hosts, CAs e tamanhos diferentes, mesmo erro.

## O que o código diz

**1. De onde vem a mensagem.** `transfer/gs_xfer.c:1427` (e `:1217` para lanes). A sondagem de identidade de cada transferência (`gs_http_open` com `Range 0-0xFFF`, `:1330-1394`) abre uma **sessão nova**, fecha-a (`gs_http_close`) e, ao receber `0x8095F00C`, registra o evento `preparation-probe-failed … ssl=0x… verify=0x… host=…` (`:1385-1390`), tenta de novo com espera (`retry_delay`) e só desiste (`tls_episode_terminal`, `:692-701`) quando há **≥ 8 falhas TLS, ≥ 120 s, todas as lanes testadas falharam e nenhum byte útil chegou depois da 1ª falha**. Ou seja: o painel só mostra "dois minutos" depois de ≥ 8 tentativas *frescas* seguidas falharem. Não é um erro isolado.

**2. O que o `0x8095F00C` significa.** É a recusa do certificado pela `libSceSsl` do console. O SSPI decodifica o campo `verify` (`app/DownloadManager.Resident.cs:335-355`): `0x04` nome do host, `0x08`/`0x10` datas de validade, **`0x20` emissor desconhecido**. O próprio autor documenta (`app/NativeHttp.cs:87-125`) que a `libSceSsl` de firmware antigo **falha de forma *intermitente* em montar a cadeia (intermediário servido) mesmo com a raiz carregada**: "The console still reported unknown CA intermittently with both roots loaded, so trust the exact issuing intermediates directly". A correção dele é **fixar (pin) o intermediário exato de cada host conhecido** (GitHub/Sectigo DV E36/R36, Let's Encrypt Gen Y, GoDaddy G2, Google WE1, GeoTrust).

**3. Há duas pilhas de rede, com conjuntos de confiança diferentes.**

| | Pacote único de **homebrew** (OpenTyrian, Live Die Repeat) | **RAR dividido** (e pacotes `CUSA`, em modo Background) |
|---|---|---|
| Quem baixa | transferência **no app** (`NetHttp`/`NativeHttp`, C#); homebrew não espera o worker (`DownloadManager.Resident.cs:359`) | **worker residente** em C (`gs_xfer.c`); arquivos `.rar` só são entregues a ele (`DownloadManager.Archive.cs:246-300`, exige `UseBgftDirect`, padrão `true` em `AppSettings.cs:103`) |
| Confiança | Mozilla + **pins** (GitHub Sectigo `github-sectigo-dv.pem`, Gen Y, GoDaddy, WE1, GeoTrust) (`NativeHttp.cs:305-372`) | Mozilla + Gen Y, WE1, GoDaddy G2, GeoTrust, **sem pin do GitHub** (`resident/plugin/gs_resident_worker.inc:775-784`) |
| Sessões TLS | 1 sondagem + lanes por arquivo | **por volume**: 1 sondagem no app (todos os 11 antes de começar, `NetHttp.ReadRangeDirect`, "Checking RAR part n/N") + **uma sondagem nova no worker para cada volume** + lanes |

Cada volume é uma transferência independente (caminho e tamanho próprios; "um conjunto multi-volume perde só o volume em andamento", doc do SSPI). Então um RAR de 11 volumes faz ≈ 20+ handshakes novos em poucos segundos, no stack **com menos pins**, e basta **uma** sondagem falhar por 2 min para derrubar o conjunto. Um PKG único faz poucos handshakes e usa o stack com mais pins.

## Causa mais provável
**O worker residente do SSPI não consegue, de forma intermitente, montar a cadeia de certificado de `raw.githubusercontent.com` em sessões novas** (emissor desconhecido, `verify=0x20`), porque o intermediário desse host não está entre os que o worker fixa. O mesmo mecanismo (cadeia não montada em handshake novo) explica o Live Die Repeat (`api.pkg-zone.com`, também em sessão nova após a interrupção), no stack do app. O RAR expõe o problema porque multiplica os handshakes novos e usa o stack residente.

**Evidências a favor:** (a) o autor descreve exatamente esse modo de falha, intermitente, no GitHub; (b) o worker não carrega o pin do GitHub e o app carrega; (c) os volumes 1–6 passaram e o 7 falhou: intermitência por handshake, não bloqueio do host; (d) as 11 sondagens do app (com pin) passaram antes do worker começar: a entrega só chega ao worker depois de todas (inferência, pois o download começou); (e) `T8b`/`T9` (poucos handshakes) funcionaram em `raw`.
**Contra/lacunas:** não vi a cadeia real de `raw.githubusercontent.com` (pode ser DigiCert, não Sectigo); o modo de download usado no 5A não foi registrado; não temos o `verify=` do log; o repositório público pode diferir do binário.
**Hipóteses alternativas** (testáveis): relógio do console (`verify` 0x08/0x10); DNS/filtro devolvendo borda com outro certificado (`verify` 0x04); limite de novas conexões do host ou do roteador.

## Teste mínimo para confirmar (2 passos, sem desenvolver nada)
**1) Ler o log do SSPI** (por FTP do GoldHEN, `/data/SSPI/logs/download.log`, `resident.log`, `network.log`; ou o que a página do celular/ajuda do SSPI oferecer para exportar logs). Procure, na hora da falha:
`event=preparation-probe-failed … ssl=0x… verify=0x… host=…` e a linha `Resident HTTPS ready with bundled PEM trust` / contagem de CAs. Copie 3–4 linhas (as URLs são filtradas pelo SSPI).
**2) Repetir o 5A com o modo de download no app:** *OPTIONS → Settings → General → Download mode = **In-app*** (o SSPI diz que ele roda os downloads dentro do app; a doc cita renovação de link de arquivos no modo In-app) e colar de novo `links-ordem.txt`. Anote em que volume termina ou se conclui; **registre antes qual era o modo** (padrão: Background).

| `verify` / host no log | 5A em **In-app** | Conclusão |
|---|---|---|
| `0x20`, host `raw.githubusercontent.com` | **conclui** 11/11 | o stack residente não confia no emissor do `raw` (falta o pin que o app tem) → causa confirmada |
| `0x20`, host `raw…` | **também falha** (qualquer volume) | intermitência da `libSceSsl` para esse host em qualquer stack → precisa fixar o intermediário exato no SSPI (autor) ou mudar de host |
| `0x08`/`0x10` | indiferente | data/hora do console |
| `0x04` | indiferente | DNS/borda com certificado de outro nome |
| host **diferente** de `raw…` (p.ex. um host de CDN) | indiferente | o `raw` redireciona para outro host que precisa de pin |
Também ajuda saber se uma nova tentativa falha **no mesmo volume 7** (determinístico: borda/IP fixo) ou em outro (aleatório por handshake).

## Se confirmado: opções (não implementadas; nenhuma desativa TLS)
1. **Usar o modo In-app** para RAR (sem mudança de código; o app tem mais pins).
2. **Hospedar em um host cuja cadeia o worker já fixa** (Let's Encrypt Gen Y, GoDaddy G2, Google WE1) ou que o app/worker consigam montar; precisa de teste no console (o único host provado em download é `raw`, em Background só com poucos handshakes, e `pkg-zone.com`).
3. **Pedir ao autor do SSPI** o pin do intermediário do `raw.githubusercontent.com` na lista do worker (mudança no SSPI, fora do nosso código).
4. Menos volumes (maiores) reduz os handshakes, mas não corrige a causa.
