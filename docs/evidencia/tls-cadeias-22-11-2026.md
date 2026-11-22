# Cadeias de certificado dos hosts de download vs âncoras do SSPI (22/11/2026)

Gerado por `tools/tls_chain.py` no GitHub Actions (workflow `tlscheck`, conexão direta, sem interceptação). Âncoras do SSPI lidas de `app/NativeHttp.cs` (raízes curadas + pins). O firmware 9.00 pode ter raízes próprias: "RISCO" não prova falha. A visão é a do runner (outra região/borda pode servir outra cadeia).

| Host | Cliente | Veredito | Raiz alcançada | Emissor do servidor | Certs na cadeia | IPs / cadeias distintas |
|---|---|---|---|---|---|---|
| `raw.githubusercontent.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
| `raw.githubusercontent.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 185.199.108.133, 185.199.109.133, 185.199.110.133, 185.199.111.133 |
|  ↳ variante | | | | | 0 | 2606:50c0:8000::154, 2606:50c0:8001::154 |
| `github.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root E46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV E36,O=Sectigo Limited,C=` | 3 | 1 IPs / 1 cadeia(s) distinta(s) |
| `github.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 1 IPs / 1 cadeia(s) distinta(s) |
| `release-assets.githubusercontent.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 4 IPs / 1 cadeia(s) distinta(s) |
| `release-assets.githubusercontent.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 4 IPs / 1 cadeia(s) distinta(s) |
| `objects.githubusercontent.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 4 IPs / 1 cadeia(s) distinta(s) |
| `objects.githubusercontent.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 4 IPs / 1 cadeia(s) distinta(s) |
| `t-justino.github.io` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
| `t-justino.github.io` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X1,O=Internet Security Research Group,C=US` | `CN=YR1,O=Let's Encrypt,C=US` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153 |
|  ↳ variante | | | | | 0 | 2606:50c0:8000::153, 2606:50c0:8001::153 |
| `cdn.jsdelivr.net` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 6 IPs / 2 cadeia(s) distinta(s) |
| `cdn.jsdelivr.net` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 6 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 151.101.1.229, 151.101.129.229, 151.101.193.229, 151.101.65.229 |
|  ↳ variante | | | | | 0 | 2606:4700::6810:b370, 2606:4700::6810:b470 |
| `fastly.jsdelivr.net` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=GlobalSign Root R46,O=GlobalSign nv-sa,C=BE` | `CN=GlobalSign Atlas R46 DV TLS CA 2026 Q4,O=GlobalSign nv-sa,C=BE` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
| `fastly.jsdelivr.net` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=GlobalSign Root R46,O=GlobalSign nv-sa,C=BE` | `CN=GlobalSign Atlas R46 DV TLS CA 2026 Q4,O=GlobalSign nv-sa,C=BE` | 3 | 8 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 151.101.1.229, 151.101.129.229, 151.101.193.229, 151.101.65.229 |
|  ↳ variante | | | | | 0 | 2a04:4e42:200::485, 2a04:4e42:400::485 |
| `gcore.jsdelivr.net` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 4 IPs / 2 cadeia(s) distinta(s) |
| `gcore.jsdelivr.net` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 4 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 104.16.179.112, 104.16.180.112 |
|  ↳ variante | | | | | 0 | 2606:4700::6810:b370, 2606:4700::6810:b470 |
| `pkg-zone.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X2,O=Internet Security Research Group,C=US` | `CN=YE1,O=Let's Encrypt,C=US` | 4 | 1 IPs / 1 cadeia(s) distinta(s) |
| `pkg-zone.com` | RSA/TLS1.2 | sem resposta | | | | 1 IPs |
| `api.pkg-zone.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=GTS Root R4,O=Google Trust Services LLC,C=US` | `CN=WE1,O=Google Trust Services,C=US` | 3 | 4 IPs / 2 cadeia(s) distinta(s) |
| `api.pkg-zone.com` | RSA/TLS1.2 | sem resposta | | | | 4 IPs |
|  ↳ variante | | | | | 3 | 104.21.39.95, 172.67.144.8 |
|  ↳ variante | | | | | 0 | 2606:4700:3030::6815:275f, 2606:4700:3037::ac43:9008 |
| `storage.googleapis.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=GTS Root R4,O=Google Trust Services LLC,C=US` | `CN=WE2,O=Google Trust Services,C=US` | 3 | 16 IPs / 1 cadeia(s) distinta(s) |
| `storage.googleapis.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=GTS Root R1,O=Google Trust Services LLC,C=US` | `CN=WR2,O=Google Trust Services,C=US` | 3 | 16 IPs / 1 cadeia(s) distinta(s) |
| `s3.amazonaws.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Amazon Root CA 1,O=Amazon,C=US` | `CN=Amazon RSA 2048 M01,O=Amazon,C=US` | 3 | 8 IPs / 1 cadeia(s) distinta(s) |
| `s3.amazonaws.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Amazon Root CA 1,O=Amazon,C=US` | `CN=Amazon RSA 2048 M01,O=Amazon,C=US` | 3 | 8 IPs / 1 cadeia(s) distinta(s) |
| `gitlab.com` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 2 IPs / 2 cadeia(s) distinta(s) |
| `gitlab.com` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Sectigo Public Server Authentication Root R46,O=Sectigo L` | `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` | 3 | 2 IPs / 2 cadeia(s) distinta(s) |
|  ↳ variante | | | | | 3 | 172.65.251.78 |
|  ↳ variante | | | | | 0 | 2606:4700:90:0:f22e:fbec:5bed:a9b9 |
| `codeberg.org` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=ISRG Root X2,O=Internet Security Research Group,C=US` | `CN=YE1,O=Let's Encrypt,C=US` | 4 | 2 IPs / 2 cadeia(s) distinta(s) |
| `codeberg.org` | RSA/TLS1.2 | sem resposta | | | | 2 IPs |
|  ↳ variante | | | | | 4 | 217.197.84.140 |
|  ↳ variante | | | | | 0 | 2a0a:4580:103f:c0de::1 |
| `huggingface.co` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Amazon Root CA 1,O=Amazon,C=US` | `CN=Amazon RSA 2048 M01,O=Amazon,C=US` | 3 | 12 IPs / 1 cadeia(s) distinta(s) |
| `huggingface.co` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Amazon Root CA 1,O=Amazon,C=US` | `CN=Amazon RSA 2048 M01,O=Amazon,C=US` | 3 | 12 IPs / 1 cadeia(s) distinta(s) |
| `archive.org` | moderno | ANCORADO (raiz na lista do SSPI) | `CN=Go Daddy Root Certificate Authority - G2,O=GoDaddy.com\, ` | `CN=Go Daddy Secure Certificate Authority - G2,OU=http://certs.godaddy.` | 4 | 1 IPs / 1 cadeia(s) distinta(s) |
| `archive.org` | RSA/TLS1.2 | ANCORADO (raiz na lista do SSPI) | `CN=Go Daddy Root Certificate Authority - G2,O=GoDaddy.com\, ` | `CN=Go Daddy Secure Certificate Authority - G2,OU=http://certs.godaddy.` | 4 | 1 IPs / 1 cadeia(s) distinta(s) |

### Detalhe: cada certificado servido (cliente moderno, 1º IP) e se é fixado (pin) pelo SSPI

**raw.githubusercontent.com**

- [0] `CN=*.github.io` · sha256 `F2F9A159CE50A0A1…` · expira Dec 29 23:44:45 2026 GMT · **não fixado pelo SSPI**
- [1] `CN=YR1,O=Let's Encrypt,C=US` · sha256 `13949634D99CD6FD…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YR,O=ISRG,C=US` · sha256 `072639D0B140D5BF…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**github.com**

- [0] `CN=github.com` · sha256 `7DC4D85CF1E31097…` · expira Jan 27 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Sectigo Public Server Authentication CA DV E36,O=Sectigo Limited,C=` · sha256 `873F0BA80E3AC222…` · expira Mar 21 23:59:59 2036 GMT · **GitHub Sectigo DV (pin)**
- [2] `CN=Sectigo Public Server Authentication Root E46,O=Sectigo Limited,C=G` · sha256 `EA6B89ED6907A209…` · expira Jan 18 23:59:59 2038 GMT · **não fixado pelo SSPI**

**release-assets.githubusercontent.com**

- [0] `CN=*.github.io` · sha256 `F2F9A159CE50A0A1…` · expira Dec 29 23:44:45 2026 GMT · **não fixado pelo SSPI**
- [1] `CN=YR1,O=Let's Encrypt,C=US` · sha256 `13949634D99CD6FD…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YR,O=ISRG,C=US` · sha256 `072639D0B140D5BF…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**objects.githubusercontent.com**

- [0] `CN=*.github.io` · sha256 `F2F9A159CE50A0A1…` · expira Dec 29 23:44:45 2026 GMT · **não fixado pelo SSPI**
- [1] `CN=YR1,O=Let's Encrypt,C=US` · sha256 `13949634D99CD6FD…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YR,O=ISRG,C=US` · sha256 `072639D0B140D5BF…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**t-justino.github.io**

- [0] `CN=*.github.io` · sha256 `F2F9A159CE50A0A1…` · expira Dec 29 23:44:45 2026 GMT · **não fixado pelo SSPI**
- [1] `CN=YR1,O=Let's Encrypt,C=US` · sha256 `13949634D99CD6FD…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YR,O=ISRG,C=US` · sha256 `072639D0B140D5BF…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**cdn.jsdelivr.net**

- [0] `CN=*.jsdelivr.net` · sha256 `4191F8642ACE9FD8…` · expira May  2 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` · sha256 `8C54C334B66BA4E4…` · expira Mar 21 23:59:59 2036 GMT · **GitHub Sectigo DV (pin)**
- [2] `CN=Sectigo Public Server Authentication Root R46,O=Sectigo Limited,C=G` · sha256 `92F351BF3D54164D…` · expira Jan 18 23:59:59 2038 GMT · **não fixado pelo SSPI**

**fastly.jsdelivr.net**

- [0] `CN=jsdelivr.net` · sha256 `183C7E7CB4D2CA04…` · expira May  8 13:50:25 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=GlobalSign Atlas R46 DV TLS CA 2026 Q4,O=GlobalSign nv-sa,C=BE` · sha256 `AE6A9C50C942220C…` · expira Jul 21 12:00:00 2028 GMT · **não fixado pelo SSPI**
- [2] `CN=GlobalSign Root R46,O=GlobalSign nv-sa,C=BE` · sha256 `A63C1398B5F8DD2D…` · expira Mar 18 00:00:00 2029 GMT · **não fixado pelo SSPI**

**gcore.jsdelivr.net**

- [0] `CN=*.jsdelivr.net` · sha256 `4191F8642ACE9FD8…` · expira May  2 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` · sha256 `8C54C334B66BA4E4…` · expira Mar 21 23:59:59 2036 GMT · **GitHub Sectigo DV (pin)**
- [2] `CN=Sectigo Public Server Authentication Root R46,O=Sectigo Limited,C=G` · sha256 `92F351BF3D54164D…` · expira Jan 18 23:59:59 2038 GMT · **não fixado pelo SSPI**

**pkg-zone.com**

- [0] `CN=pkg-zone.com` · sha256 `1E7C5907F72BB4A7…` · expira Feb 11 18:00:12 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=YE1,O=Let's Encrypt,C=US` · sha256 `A2372D06431E9716…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YE,O=ISRG,C=US` · sha256 `0FC0901CCA2BAE9E…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**
- [3] `CN=ISRG Root X2,O=Internet Security Research Group,C=US` · sha256 `EE5F7ABD6981BB02…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**api.pkg-zone.com**

- [0] `CN=pkg-zone.com` · sha256 `E1B97E7A934AAB05…` · expira Jan  2 17:57:48 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=WE1,O=Google Trust Services,C=US` · sha256 `1DFC1605FBAD358D…` · expira Feb 20 14:00:00 2029 GMT · **não fixado pelo SSPI**
- [2] `CN=GTS Root R4,O=Google Trust Services LLC,C=US` · sha256 `76B27B80A58027DC…` · expira Jan 28 00:00:42 2028 GMT · **não fixado pelo SSPI**

**storage.googleapis.com**

- [0] `CN=storage.googleapis.com` · sha256 `42330480D5F33FB5…` · expira Jan 26 08:32:10 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=WE2,O=Google Trust Services,C=US` · sha256 `9C3F2FD11C57D7C6…` · expira Feb 20 14:00:00 2029 GMT · **não fixado pelo SSPI**
- [2] `CN=GTS Root R4,O=Google Trust Services LLC,C=US` · sha256 `76B27B80A58027DC…` · expira Jan 28 00:00:42 2028 GMT · **não fixado pelo SSPI**

**s3.amazonaws.com**

- [0] `CN=s3.amazonaws.com` · sha256 `E01CECBC6B4F96CF…` · expira Apr  5 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Amazon RSA 2048 M01,O=Amazon,C=US` · sha256 `5338EBEC8FB2AC60…` · expira Aug 23 22:21:28 2030 GMT · **não fixado pelo SSPI**
- [2] `CN=Amazon Root CA 1,O=Amazon,C=US` · sha256 `87DCD4DC74640A32…` · expira Dec 31 01:00:00 2037 GMT · **não fixado pelo SSPI**

**gitlab.com**

- [0] `CN=gitlab.com` · sha256 `8412F4407213BC94…` · expira May 12 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Sectigo Public Server Authentication CA DV R36,O=Sectigo Limited,C=` · sha256 `8C54C334B66BA4E4…` · expira Mar 21 23:59:59 2036 GMT · **GitHub Sectigo DV (pin)**
- [2] `CN=Sectigo Public Server Authentication Root R46,O=Sectigo Limited,C=G` · sha256 `92F351BF3D54164D…` · expira Jan 18 23:59:59 2038 GMT · **não fixado pelo SSPI**

**codeberg.org**

- [0] `CN=*.codeberg.org` · sha256 `B30C37338661CEBC…` · expira Feb 18 22:26:53 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=YE1,O=Let's Encrypt,C=US` · sha256 `A2372D06431E9716…` · expira Sep  2 23:59:59 2028 GMT · **Let's Encrypt Gen Y intermediário (pin)**
- [2] `CN=Root YE,O=ISRG,C=US` · sha256 `0FC0901CCA2BAE9E…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**
- [3] `CN=ISRG Root X2,O=Internet Security Research Group,C=US` · sha256 `EE5F7ABD6981BB02…` · expira Sep  2 23:59:59 2032 GMT · **não fixado pelo SSPI**

**huggingface.co**

- [0] `CN=huggingface.co` · sha256 `0ECA454B46A3617C…` · expira Feb 27 23:59:59 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Amazon RSA 2048 M01,O=Amazon,C=US` · sha256 `5338EBEC8FB2AC60…` · expira Aug 23 22:21:28 2030 GMT · **não fixado pelo SSPI**
- [2] `CN=Amazon Root CA 1,O=Amazon,C=US` · sha256 `87DCD4DC74640A32…` · expira Dec 31 01:00:00 2037 GMT · **não fixado pelo SSPI**

**archive.org**

- [0] `CN=*.archive.org` · sha256 `5186C5EC3D3E7B93…` · expira Feb  9 22:02:42 2027 GMT · **não fixado pelo SSPI**
- [1] `CN=Go Daddy Secure Certificate Authority - G2,OU=http://certs.godaddy.` · sha256 `973A41276FFD01E0…` · expira May  3 07:00:00 2031 GMT · **GoDaddy Secure G2 intermediário (pin)**
- [2] `CN=Go Daddy Root Certificate Authority - G2,O=GoDaddy.com\, Inc.,L=Sco` · sha256 `3A2FBE92891E57FE…` · expira May 30 07:00:00 2031 GMT · **não fixado pelo SSPI**
- [3] `OU=Go Daddy Class 2 Certification Authority,O=The Go Daddy Group\, Inc` · sha256 `C3846BF24B9E93CA…` · expira Jun 29 17:06:20 2034 GMT · **não fixado pelo SSPI**

