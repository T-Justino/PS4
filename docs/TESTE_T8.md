# T8 — App próprio "PS4 Store BR Test" (ID do catálogo == ID real do pacote)

**Objetivo:** provar a cadeia completa quando a identidade é compatível: fonte importada → item pesquisado → download → PKG aceito →
instalação concluída. **Nada disso foi testado no console.** Tudo abaixo é preparação e verificação offline.

## O que foi gerado

| Artefato | Arquivo | Identificação |
|---|---|---|
| PKG | `dist/t8/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg` | 6.619.136 B · sha256 `e7d3d14f04b13326244f2b2c003e1dc1706fa1befed96708647131a87fed69fc` |
| Fonte | `dist/t8/ps4storebr-t8-cusa95417.gssource` | contentSha256 `eea5b63b6dcc47806721082498540f4436517f0e93d2665c5375b108963403ae` |
| Código do app | `app/ps4storebr-test/` (`main.cpp`, `Makefile`, ícone) | licenças: ver abaixo |
| Build / verificação | `app/build.sh`, `app/verify_pkg.py` | |
| Canônico | `data/fixtures/t8/t8-cusa95417-ps4storebr-test.json` | **sem** chave sintética; `titleId` = ID real |

**Identificadores (consistentes, conferidos por `app/verify_pkg.py` lendo o PKG, independentemente do toolchain):**
`titleId` do catálogo = `CUSA95417` = `TITLE_ID` do `param.sfo` = ID embutido no Content ID `IV0000-CUSA95417_00-PS4STOREBRTEST00`
(= `CONTENT_ID` do `param.sfo` = Content ID do cabeçalho do PKG). `CATEGORY=gd`, `APP_TYPE=1`, versão `1.00`.

**O app:** tela estática "PS4 STORE BR TEST / INSTALACAO OK" com os IDs. Sem rede, sem arquivos, sem dados do usuário.
Para sair: botão PS. Não altera nenhum app instalado nem o firmware.

## Sobre o ID `CUSA95417` (experimental)

- **Não é um ID oficial** e **não será usado em produção.** É um ID de teste que identifica só este app próprio.
- Colisão: nenhuma ocorrência de `CUSA95417` na busca de código do GitHub nem na web; os IDs `CUSA` reais conhecidos estão muito abaixo de 9xxxx
  (ex.: `CUSA07473`, `CUSA15797`). **Isso reduz, mas não prova a ausência de colisão** (não há base oficial completa para consultar).
- Não reaproveita as chaves antigas (`CUSA99999`, `CUSA90001–90004`).
- Diferença para T4–T7: aqui o ID é o **verdadeiro** do pacote, escolhido na hora de compilar o **nosso** app. Nenhum PKG de terceiros foi alterado.

## Toolchain (investigação)

- **OpenOrbis PS4 Toolchain** (GPL-3.0, sem SDK da Sony). Usado o release **v0.5.2** (SHA-256 `92457ea5…1334`, conferido em `app/build.sh`);
  compila com `clang`/`lld` e empacota com `PkgTool.Core`, `create-gp4` e `create-fself` do próprio release. O `main` do repositório não traz binários.
- Licenças: o toolchain e os samples (`graphics.cpp`, `right.sprx` etc.) são GPL-3.0 e **não foram copiados** para este repositório
  (o `build.sh` os usa do cache). O código em `app/ps4storebr-test/` é nosso; o `Makefile` é adaptado de sample GPL-3.0 (indicado no cabeçalho);
  a licença do binário distribuído, que embute código do toolchain, deve ser tratada como GPL-3.0 se o PKG for redistribuído.
- Obstáculo de build (resolvido, só no ambiente de build): `PkgTool.Core` é .NET Core 3.0 e exige `libssl 1.1` (o Ubuntu 24 só tem OpenSSL 3) e
  `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` (sem ICU). Usei o `libssl1.1` do arquivo do Ubuntu num diretório temporário (`LD_LIBRARY_PATH`), sem instalar nada no sistema.

## Hospedagem do PKG por HTTPS (decisão necessária)

O `.gssource` usa: `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/t8/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg`
(repositório público; sem VPS; sem servidor próprio).

> **Risco conhecido:** no seu console o download pelo `github.com` (Releases) já falhou com TLS (`0x8095F00C`). **Não sei se `raw.githubusercontent.com` passa.**
> Daqui não dá para testar o TLS do PS4. O único host comprovado é `pkg-zone.com` (não é nosso).

| Plano | Quando | Esforço |
|---|---|---|
| **1. `raw.githubusercontent.com` (atual)** | primeiro | zero |
| 2. Outro host estático (ex.: GitHub Pages `github.io`, Cloudflare Pages/R2) | se o plano 1 falhar por TLS | gerar nova fonte com a nova URL (um comando); sem mudar o PKG |
| 3. **T8a (PKG por USB, sem rede)** | a qualquer momento, para isolar o PKG do transporte | nenhum |

Por isso o procedimento tem uma etapa 0 (T8a): se o PKG instala por USB, qualquer falha posterior é de **transporte**, não de identidade.

## Procedimento no PS4 Pro 9.00 (GoldHEN, SSPI 5.11.7)

**Não remova nem altere nenhum app instalado.** O único app novo é "PS4 Store BR Test".

### T8a — PKG por USB (opcional, recomendado primeiro)
1. Copie `IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg` para a raiz do pendrive.
2. No SSPI, instale o `.pkg` a partir do USB (o SSPI aceita arquivos `.pkg` de USB). Anote: **aceito/recusado** (mensagem exata) e **concluído**.
3. Abra "PS4 Store BR Test" na tela inicial: deve mostrar a tela de confirmação. Saia com o botão PS.

### T8 — catálogo + download HTTPS
Antes: se instalou o app no T8a, apague **só ele** (Opções → Excluir) para repetir o ciclo, ou anote e pule o item 5.
1. **Fonte:** copie `ps4storebr-t8-cusa95417.gssource` para o USB → *Install source from USB*. Remova antes fontes T4–T7.
2. **Pesquisa:** busque `ps4 store br test`, `teste t8` e `CUSA95417` → 1 item "PS4 Store BR Test". Abra os detalhes.
3. **Download:** toque em instalar/baixar; ≈ 6,6 MB. Anote se iniciou e se concluiu (6,6 / 6,6 MB).
4. **PKG:** anote **aceito/recusado** e a mensagem exata se recusar.
5. **Instalação:** o app aparece na tela inicial e abre mostrando "INSTALACAO OK" e `CUSA95417`.

### Como registrar
```text
T8a (opcional): PKG por USB: [aceito / recusado + msg] | instalou: [sim/não] | app abre: [sim/não]
T8:
1 fonte importada:        [sim / não + erro]
2 achado na pesquisa:     [sim / não]
3 download iniciado:      [sim / não + msg]   concluído: [sim / não + __%]
4 PKG aceito/recusado:    [aceito / recusado + msg EXATA]
5 instalação concluída:   [sim, abre / não + msg]
Foto das mensagens: [anexada]
```

### Interpretação
| Resultado | Conclusão | Próximo passo |
|---|---|---|
| T8 1–5 = sim | Cadeia completa comprovada com identidade compatível, para este app e esta versão do SSPI | Aceitar o pré-requisito do Gate 3; não generaliza |
| T8a ok, T8 falha no download (TLS/HTTP) | Problema de **hospedagem**, não do PKG nem da identidade | Plano 2 de hospedagem |
| T8a recusado | PKG não instalável (formato/assinatura/metadados) | Investigar o PKG antes de qualquer hospedagem |
| T8 recusado com `expected … got …` | Identidade incompatível (não esperado: IDs conferidos) | Reabrir a análise de identidade |
| T8 recusado por tipo/`param.sfo` | Metadado do PKG | Ajustar o app e repetir |
| Falha de importação da fonte | Schema/ID | Enviar a mensagem exata |

## Reprodução

```bash
bash app/build.sh                         # baixa/verifica o toolchain, compila e gera o PKG (precisa libssl1.1; ver acima)
python3 app/verify_pkg.py app/ps4storebr-test/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg --title-id CUSA95417
PYTHONPATH=src python3 -m ps4store build data/fixtures/t8/t8-cusa95417-ps4storebr-test.json -o dist/t8/ps4storebr-t8-cusa95417.gssource
```
O hash do PKG pode variar entre builds (assinatura/PFS do toolchain); o PKG entregue é o de `dist/t8/` (sha256 acima).

## Não comprovado

Instalação no PS4, aceitação do PKG pela instalação do SSPI, TLS de `raw.githubusercontent.com` no SSPI, execução do app no console,
atualizações, DLC. **Compatibilidade só será registrada depois do seu relato.**
