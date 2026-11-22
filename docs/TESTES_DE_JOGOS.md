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
**Teste 3 (grande + retomada + espaço):** cole o link do Live Die Repeat. Anote espaço livre no início, **com ~50 %**, no fim do download e após instalar. Retomada, em ordem:
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

## Prontidão para retomada, medida pelo robô antes do teste (22/11/2026)

Novo comando: `ps4store resume-check [--title ID ...] [--source ID]`. Para cada arquivo faz **3 requisições `Range` de 64 KiB** (25 %, 50 %, 90 %): confere se o servidor honra `Range` em offsets arbitrários, se o **tamanho total** e o **ETag** ficam estáveis mesmo passando por um novo redirect a cada requisição (o SSPI desconfia de réplicas que etiquetam os mesmos bytes de forma diferente) e mede quanto tempo vive a URL assinada. Nunca baixa o arquivo.

| Candidato | Tamanho | `Range` em offsets | Tamanho | Validador | Veredito |
|---|---|---|---|---|---|
| Kill'em All. (`BBFF12362/1.00`) | 1.423,5 MB | ok | estável | ETag | **PRONTO** |
| Live Die Repeat (`LAPY10024/1.01`) | 948,8 MB | ok | estável | ETag | **PRONTO** |
| PS Scene The Quiz Game (`LAPY10010/1.01`) | 261,7 MB | ok | estável | ETag | **PRONTO** |
| RAR dividido próprio (volumes 01–10 de 11; o 11 fica fora do teto de 10 por comando) | 0,6 MB cada | ok | estável | ETag | **PRONTO** |

Releases **inativas** (versões antigas, p.ex. `Live Die Repeat` 947,9 MB) respondem 403 no link estável e **não são candidatas**; o comando as ignora.
"PRONTO" significa que o servidor oferece o que o SSPI precisa para retomar e baixar em faixas; **só o teste no console prova** que a retomada funciona (Teste 3).
Como o link estável gera uma URL assinada nova a cada requisição, o robô confirma que isso **não troca o ETag nem o tamanho**: é a condição para a retomada do SSPI aceitar a renovação.
