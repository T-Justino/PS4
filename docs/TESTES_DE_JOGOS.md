# Testes reais de jogos no PS4: candidatos, procedimento e evidências

Objetivo: provar **download → (extração) → instalação → execução** de um **jogo completo** pelo SSPI, e medir o que o SSPI faz com redirects, arquivos grandes, RAR dividido, retomada e espaço.
Todos os candidatos foram **descobertos e validados pelo robô** (`ps4store run --probe-title …`): link acessível, `Range` 206, tamanho e identidade lidos do próprio PKG. Isso **não prova** que instalam: só o console prova.

**Origem e legitimidade (sem maquiar):** nenhuma fonte publica licença por item. Escolhi projetos de código aberto ou originais do autor, distribuídos pelo próprio autor no PKG-Zone. A licença exata **não está verificada**; o uso é pessoal e a decisão final é sua.
Não incluí jogos comerciais, portes/mods de jogos comerciais nem repackagens (o robô mantém esses itens na pesquisa como metadados, fora das listas).

## RESULTADO: Teste 1 (OpenTyrian) APROVADO (22/11/2026, relato do usuário; PS4 Pro 9.00, GoldHEN, SSPI 5.11.7)

Link usado: `https://pkg-zone.com/download/ps4/OPEN00001/1.01` na função de **download direto** do SSPI (sem catálogo, sem PC, sem VPS).

| Etapa | Resultado |
|---|---|
| Download | **concluído**, 19,8 MB (= 19.791.872 B previstos pelo robô) |
| Pacote identificado | **`OPEN00001`** (= identidade lida pelo robô: `IV0001-OPEN00001_00-OPEN000010000000`) |
| Instalação | concluída, status **Installed** |
| Execução | o jogo **abriu** e exibiu o menu principal |

**O que isto comprova (e só isto):** um jogo homebrew completo obtido por **URL estável que redireciona para uma URL assinada temporária** (`pkg-zone.com` → `api.pkg-zone.com`), com `Range`, e com **ID que o importador de catálogo recusaria** (`OPEN00001` não é `CUSA`): o caminho de download direto do SSPI o baixa, identifica, instala e executa.
As hipóteses do robô sobre o baixador do SSPI (redirect, URL assinada, `Range`, identidade) **foram confirmadas para este item**. **Não comprova** arquivos grandes, retomada, RAR dividido, os demais itens do PKG-Zone, jogos comerciais nem outros hosts. Os Testes 2 a 5 continuam pendentes.

## RESULTADO: Teste 3 (Live Die Repeat, ≈949 MB): instalação e execução APROVADAS; **retomada NÃO resolvida** (22/11/2026, relato do usuário; PS4 Pro 9.00, GoldHEN, SSPI 5.11.7)

Link: `https://pkg-zone.com/download/ps4/LAPY10024/1.01` (estável → redirect assinado), download direto do SSPI, sem PC nem VPS.

| Etapa | Resultado |
|---|---|
| Download completo | **948,8 MB** (= 948.830.208 B previstos pelo robô) |
| Instalação | **concluída** |
| Execução | o jogo **abriu normalmente** |
| **Tentativa 1** | chegou a **915,3 MB (≈96,5 %)** e **falhou por certificado TLS** depois de uma **interrupção** |
| **Tentativa 2** | iniciada de novo pelo usuário; **concluiu** |

**Aprovado:** um jogo de ≈1 GB baixado, instalado e executado pelo link estável com redirect assinado. **Em aberto (não resolvido):**
- **A retomada após erro TLS.** Não sabemos se a tentativa 2 **retomou** os 915 MB já baixados ou **recomeçou do zero** (relato: "iniciada novamente"), nem a mensagem/código exatos do erro. Os cortes de rede planejados (30 s, 4 min) e o fechamento do SSPI **não foram executados**.
- **Causa do erro TLS: desconhecida.** Hipóteses (nenhuma verificada): (1) ao reconectar depois da interrupção, o SSPI fez um handshake novo com `api.pkg-zone.com` (Cloudflare) e a cadeia de certificado apresentada não é aceita pelo store de certificados do PS4 9.00 (o primeiro handshake passou, então não seria sistemático; a CA/cadeia entregue pode variar); (2) a interrupção de rede e a lógica de nova tentativa do SSPI terminaram em falha de TLS; (3) expiração da URL assinada está **descartada**: ela dura ≈6 h e o download levou bem menos.
- **O que coletar quando repetir:** texto/código exato do erro; se o erro aparece logo na reconexão após um corte **curto** (30 s) ou só em cortes longos; se o SSPI mostra % retomado ou recomeça; se existe arquivo parcial em *Stored files* depois da falha; horário da falha.
- Do lado do robô não há correção possível (é o certificado do servidor de download). Registrado como **limitação conhecida**: downloads grandes podem exigir **nova tentativa manual** após uma interrupção. O robô já garante o pré-requisito do servidor (`Range` honrado, tamanho e ETag estáveis entre redirects: `resume-check`).

## Lista curta de candidatos

| # | Candidato | Tamanho | Formato / caminho | Origem | O que demonstra |
|---|---|---|---|---|---|
| **1** | **OpenTyrian** (cpasjuste), jogo completo, `hb game`, `OPEN00001` | 19.791.872 B (≈19 MB) | PKG; **link estável → redirect para URL assinada**; ID não-`CUSA` ⇒ **colar link** | PKG-Zone `https://pkg-zone.com/download/ps4/OPEN00001/1.01` (porte GL de OpenTyrian, engine GPL) | **Critério principal com custo mínimo:** jogo completo + redirect temporário + ID que o catálogo recusa |
| **2** | **Friday Night Funkin'** (cuckydev), "Open Source, fan remake", `SCUS00000` | 179.961.856 B (≈172 MiB) | PKG; redirect; **colar link** | `https://pkg-zone.com/download/ps4/SCUS00000/1.00` | jogo completo médio; **o robô o marca `restricted` só pelo Content ID `UP9000-…`** (heurística conservadora): decisão individual sua |
| **3** | **Live Die Repeat** (Lapy, "tribute to Dragon's Lair"), `LAPY10024` | 948.830.208 B (≈905 MiB) | PKG; redirect; **colar link** | `https://pkg-zone.com/download/ps4/LAPY10024/1.01` | **arquivo grande (~1 GB)**: retomada de download e espaço de pico. (A fonte o classifica como `utility`; é homenagem de fã, **origem não verificada**) |
| 4 | **Kill'em All.** (RetroGamer), `hb game`, `BBFF12362` | 1.423.507.456 B (≈1,33 GiB) | PKG; redirect; **colar link** | `https://pkg-zone.com/download/ps4/BBFF12362/1.00` | o maior jogo "hb game" achado; **origem/licença não verificadas**: só se o 3 não bastar |
| **5** | **App próprio em RAR dividido**: 11 volumes de 600 KB (último 477.558 B), total 6.621.558 B | 6,3 MiB | **RAR5 multiparte** `…_rar.part01.rar … part11.rar`; **colar 11 links** (ou USB) | `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/rartest/PS4StoreBRTest_v1.02_rar.part01.rar` … `part11.rar` | identificação das partes, **ordem** (`part02` antes de `part10`), tamanho, extração e instalação. Extração local conferida: PKG extraído **idêntico** ao original |
| 6 | App próprio, PKG direto (baseline já comprovado no catálogo, T8b/T9) | 6.619.136 B | PKG; **direto** (`raw`, sem redirect); colar link | `…/pkgs/PS4StoreBRTest_CUSA95417_v1.02.pkg` | compara direto × redirect |

**Por que não há RAR de jogo grande:** não existe fonte legítima com RAR multiparte (o robô procurou nas fontes ativas e **só reconhece** o formato) e eu não posso hospedar RAR de jogos de terceiros. O conjunto 5 prova o mecanismo (ordem/extração/instalação); **não prova** o comportamento com dezenas de GB.
**Por que não há PKG direto grande:** o GitHub limita arquivos a 100 MB e não é CDN de jogos; o único PKG direto disponível é o próprio de 6,6 MB.

## O que o robô já mediu (22/11/2026)

| | Link | Redirect | Temporário | Range | Identidade (PKG) |
|---|---|---|---|---|---|
| 1 OpenTyrian | estável | → `api.pkg-zone.com` | sim (~6 h) | 206 | `IV0001-OPEN00001_00-OPEN000010000000` |
| 2 FNF | estável | idem | sim | 206 | `UP9000-SCUS00000_00-SCUS00000PSXFPKG` (⇒ restrito pela heurística) |
| 3 Live Die Repeat | estável | idem | sim | 206 | `ED1234-LAPY10024_00-0000000000000000` (`param.sfo` lido por 2ª faixa) |
| 4 Kill'em All | estável | idem | sim | 206 | `ED6433-BBFF12362_00-0000000000000000` (idem) |
| 5 RAR | direto (`raw`) | não | não | 206 | 11 volumes, assinatura RAR5 ok, **completo e em ordem**, nenhum faltando |

## O que o SSPI deve fazer (documentação e código públicos do SSPI; **a confirmar no console**)
- **Redirect temporário:** segue o redirect sozinho; se a URL assinada expirar, **refaz o redirect pela URL original**. Retomada: "resume após interrupções e mantém o progresso" (mapa de faixas; exige o mesmo tamanho total).
- **RAR:** "enfileire o conjunto completo"; partes com nomes reconhecidos são agrupadas sozinhas; senão marque *These links are parts of one RAR archive, in volume order*. Até **50 links por vez** na página do celular. O SSPI extrai no PS4 e confere o PKG antes de instalar. Parte faltando/danificada: precisa do conjunto completo.
- **Espaço de pico:** "durante a extração, o arquivo e o pacote extraído existem ao mesmo tempo". Staging na memória interna ou em **USB exFAT** (FAT32 não guarda arquivo > 4 GiB). Hipótese a **medir**: PKG direto ≈ 2× o tamanho (pacote em staging + jogo instalado); RAR ≈ 3× (partes + PKG extraído + instalado).
- **Renovação de link:** modo *In-app* pede link novo após 75 s sem resposta (3 min p/ arquivo), até 3 vezes sem progresso; o serviço em *Background* (precisa GoldHEN) continua sozinho.
- Itens que o próprio SSPI marca **"Needs a PS4 test"** e que estes testes cobrem: mensagem de FAT32 > 4 GiB, interrupção do serviço em segundo plano durante arquivo.

## Procedimento (cole links no celular: página do SSPI → *Downloads*; ou no PS4: *Downloads → touchpad → Paste a download link*)

**Antes de cada teste:** *Settings → Storage*: anote **espaço livre** (interno e USB) e o **Staging location**. Para o 3/4/5 prefira **USB exFAT** como staging. Mantenha o PS4 fora do modo repouso; ative *Stats for nerds* (velocidade/tamanho).

**Teste 1 (jogo completo, redirect): ✅ APROVADO, não repetir.** cole o link do OpenTyrian → baixar → instalar → **abrir e jogar 1 min**. Fotografe: tamanho exibido (esperado 19,8 MB), conclusão, "Installed", tela do jogo.
**Teste 2 (opcional):** idem com FNF (≈172 MiB).
**Teste 3 (grande + retomada + espaço): download/instalação/execução ✅ aprovados; retomada ⏳ NÃO resolvida (ver resultado acima).** cole o link do Live Die Repeat. Anote espaço livre no início, **com ~50 %**, no fim do download e após instalar. Retomada, em ordem:
 1. com ~30 %, **corte a rede 30–40 s** (cabo/Wi-Fi) e restaure → continua de onde parou? (anote % antes/depois e se a velocidade recomeça);
 2. com ~60 %, **corte 4 min** (passa dos 75 s de renovação) → renovou o link e continuou? ou falhou? (mensagem exata);
 3. com ~80 %, **feche o SSPI** (modo In-app) ou mude para *Background* e saia: o download segue?
 Depois instale e **abra o jogo**. Se a instalação for demorada, anote o tempo.
**Teste 5 (RAR dividido):** cole os **11 links na ordem** (`part01` … `part11`), tudo de uma vez. Anote: agrupou sozinho? precisou marcar a caixa? mostra 11 volumes e 6,3 MiB? extrai? instala? abre? **Variante de erro útil:** cole só 10 links (sem o `part11`) e anote a mensagem de "volume faltando".

## Registro (copie e preencha; fotos quando houver erro)
```text
Teste __ | candidato __ | caminho [colar link / USB]
link aceito [sim/não+msg] | tamanho mostrado [__] (esperado __ B) | download [ok/erro+msg] | tempo [__]
espaço livre: início [__] · meio [__] · fim do download [__] · após instalar [__] · staging [interno/USB]
extração [n/a ou ok/erro+msg] | PKG aceito [sim/não+msg] | instalado [sim/não] | ABRE e roda [sim/não+msg]
retomada: corte 30 s [retomou/reiniciou/falhou] · corte 4 min [retomou/renovou/falhou+msg] · fechar SSPI [segue/para]
```

## Critério de sucesso
**Um jogo completo baixado direto no PS4, instalado e executado, com evidência de cada etapa.** O mínimo é o **Teste 1**; os testes 3 e 5 respondem às perguntas de arquivo grande, retomada, espaço e RAR.
Nada aqui garante jogos comerciais nem outros hosts. Nenhum identificador interno de PKG, firmware ou proteção é alterado.


## RESULTADO: Teste 5A (RAR dividido, 11 volumes): reconhecimento OK; **download falhou por TLS no volume 7/11** (22/11/2026, relato do usuário)

- O SSPI **reconheceu os 11 volumes como um único RAR** (identificação e agrupamento ✅).
- O download começou e **chegou ao volume 7/11 (≈ 3,7–4 MB; 6 volumes × 614.400 B = 3,69 MB)** e **falhou**: `Provider TLS certificate not trusted on fresh probe sessions for two minutes with no useful progress (0x8095F00C)`, no painel do celular.
- Hospedagem: `raw.githubusercontent.com`. **Extração, instalação e execução não foram alcançadas.** 5B e 5C pendentes.
- **Modo confirmado: In-app** (foto: "In-app · keep SSPI open · Downloading"); **Retry repetiu o erro**. Mesmo código TLS do Live Die Repeat (PKG-Zone).
- **Investigação revista** (a hipótese do worker residente foi **retirada**): `docs/INVESTIGACAO_TLS_SSPI.md`. Causa mais provável, não confirmada: o firmware antigo falha de forma intermitente ao construir a cadeia de hierarquias novas (Let's Encrypt Gen Y no `raw`; GTS WE1 no PKG-Zone). **Próximo teste: 5A com os mesmos 11 volumes servidos pelo jsDelivr** (`rartest/links-jsdelivr-ordem.txt`; cadeia Sectigo R36 fixada pelo SSPI) + coleta dos logs. Teste 5 **reprovado por transporte, não por descoberta**.

## Teste 5 (RAR dividido): preparação (resultado do 5A acima)

**Conjunto de teste** (feito do PKG próprio v1.02; nada de terceiros): `PS4StoreBRTest_v1.02_rar.part01.rar … part11.rar`, RAR5, sem compressão.
Validado pelo robô e conferido ponta a ponta (22/11/2026):
- 11 volumes, **ordem 1–11 completa, nenhum faltando**, todos acessíveis com `Range` (`resume-check`: 11/11 PRONTO), assinatura RAR5 ok em todos;
- tamanhos: **10 × 614.400 B + 1 × 477.558 B = 6.621.558 B** (≈ 6,3 MiB);
- baixados pelas URLs públicas e comparados ao repositório: **idênticos**; extraídos localmente: o PKG resultante é **idêntico** ao original (6.619.136 B, `CUSA95417`, v1.02, Content ID `IV0000-CUSA95417_00-PS4STOREBRTEST00`).

**Para não digitar 11 links:** abra no navegador do celular o arquivo de links, **copie todo o texto** e cole na caixa *Downloads* da página do SSPI (até 50 links, um por linha):

| Arquivo (raw) | Conteúdo | Teste |
|---|---|---|
| `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/rartest/links-ordem.txt` | os 11 volumes em ordem | **5A** |
| `…/rartest/links-sem-part11.txt` | 10 volumes (falta o 11) | **5B** |
| `…/rartest/links-embaralhado.txt` | os 11 em ordem embaralhada (nomes reconhecíveis) | **5C** |

**Antes:** exclua o app "PS4 Store BR Test" se estiver instalado (o PKG interno é o mesmo `CUSA95417`; o SSPI não substitui sozinho um ID `CUSA`). Anote o espaço livre e o *Staging location* (interno ou USB exFAT).

**5A (caminho feliz):** cole `links-ordem.txt`. Esperado: o SSPI **agrupa sozinho** (nomes `.partNN.rar`), mostra **11 volumes / ≈ 6,3 MiB**, baixa, **extrai**, confere o PKG e instala. Abra o app: tela "INSTALACAO OK … VERSAO 1.02".
**5B (parte faltando):** cole `links-sem-part11.txt` (com 5A concluído e o app excluído de novo, ou só observe até a extração). Esperado, pela documentação do SSPI: erro de **volume faltando** ("missing-volume") pedindo o conjunto completo. Anote a **mensagem exata**.
**5C (ordem):** cole `links-embaralhado.txt` e **cancele antes de instalar**. Pergunta: o SSPI ordena pelos nomes ou segue a ordem colada? (a documentação diz que nomes reconhecíveis são agrupados; ordem colada com nomes que escondem o volume exige marcar *These links are parts of one RAR archive, in volume order*.) Anote se extraiu certo.
**Espaço:** anote livre antes, durante a extração (pico: partes + PKG extraído) e após instalar. Com 6,3 MiB o pico é pequeno; o valor serve só de **linha de base** para estimar a razão em conjuntos grandes (a documentação prevê "arquivo e pacote extraído ao mesmo tempo").

```text
Teste 5 | staging [interno/USB exFAT] | livre: início [__] pico [__] fim [__]
5A: aceitou [sim/não+msg] | agrupou sozinho [sim/não] | volumes/tamanho mostrados [__/__] | baixou [ok/erro] | extraiu [ok/erro+msg] | PKG aceito [sim/não] | instalou [sim/não] | abre [sim/não]
5B: mensagem exata de volume faltando: [__] | baixou os 10 [sim/não]
5C: agrupou [sim/não] | respeitou a ordem [pelos nomes / pela colagem / falhou+msg] | extraiu [ok/erro]
```
**Limite:** prova o mecanismo (identificar partes, ordem, extração, instalação) com **6,3 MiB**. Não prova RAR de dezenas de GB (não há fonte legítima de RAR de jogo para hospedar/validar).

## Prontidão para retomada, medida pelo robô antes do teste (22/11/2026)

Novo comando: `ps4store resume-check [--title ID ...] [--source ID]`. Para cada arquivo faz **3 requisições `Range` de 64 KiB** (25 %, 50 %, 90 %): confere se o servidor honra `Range` em offsets arbitrários, se o **tamanho total** e o **ETag** ficam estáveis mesmo passando por um novo redirect a cada requisição (o SSPI desconfia de réplicas que etiquetam os mesmos bytes de forma diferente) e mede quanto tempo vive a URL assinada. Nunca baixa o arquivo.

| Candidato | Tamanho | `Range` em offsets | Tamanho | Validador | Veredito |
|---|---|---|---|---|---|
| Kill'em All. (`BBFF12362/1.00`) | 1.423,5 MB | ok | estável | ETag | **PRONTO** |
| Live Die Repeat (`LAPY10024/1.01`) | 948,8 MB | ok | estável | ETag | **PRONTO** |
| PS Scene The Quiz Game (`LAPY10010/1.01`) | 261,7 MB | ok | estável | ETag | **PRONTO** |
| RAR dividido próprio (11 volumes) | 0,6 MB cada | ok | estável | ETag | **PRONTO** (11/11) |

Releases **inativas** (versões antigas, p.ex. `Live Die Repeat` 947,9 MB) respondem 403 no link estável e **não são candidatas**; o comando as ignora.
"PRONTO" significa que o servidor oferece o que o SSPI precisa para retomar e baixar em faixas; **só o teste no console prova** que a retomada funciona (Teste 3).
Como o link estável gera uma URL assinada nova a cada requisição, o robô confirma que isso **não troca o ETag nem o tamanho**: é a condição para a retomada do SSPI aceitar a renovação.
