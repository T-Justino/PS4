# Uso no PS4 (sem PC e sem pendrive): instalar a fonte e receber atualizações

**Link da fonte (sempre a versão mais recente gerada pelo robô):**
`https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/auto/ps4storebr-auto.gssource`

É o próprio arquivo (HTTPS, sem redirect, 1,5 KB, `application/octet-stream`), como o SSPI exige. O PC e o servidor não precisam ficar ligados: o catálogo é atualizado no GitHub e o PS4 baixa direto de lá.

## 1) Instalar a fonte (uma vez)
1. No SSPI: *Settings → Connections → Connect your phone* (QR). No celular, na mesma rede, abra a página que aparece.
2. Aba **Sources**: cole o link acima → **Install source on PS4**. O PS4 baixa, verifica e instala.
3. Em *Search* busque o nome ou `CUSA95417` → detalhes → baixar → instalar.

## 2) Atualizar (quando o robô publicar versão nova)
1. O robô roda **a cada 6 h** (workflow agendado) ou na hora, em *Actions → catalogo → Run workflow*. Só muda o arquivo se algo mudou; a versão da fonte (`1.0.N`) sobe.
2. **Espere ~5 min** depois da execução: o GitHub guarda o arquivo em cache por 5 min (`cache-control: max-age=300`; medi ≈4 min).
3. Na página do celular (aba **Sources**) cole **o mesmo link** de novo → Install. O SSPI aceita a revisão **se a versão da fonte for maior**; a lista *Installed on your PS4* mostra a versão. Não é automático (limitação do SSPI para fontes por link).
4. Para instalar a nova versão de um app com ID `CUSA` sobre a antiga, use *Reinstall* ou exclua o app antes (o SSPI só substitui sozinho homebrew com ID não-`CUSA`).

Como saber que há versão nova: o commit `catalogo: atualizacao automatica` no repositório, ou o resumo do job em *Actions*.

## 3) T9 (APROVADO em 22/11/2026: etapas A e B; C não executada — ver `docs/TESTE_T9.md`)
Use dois links, para provar importação **por URL** e **atualização**:

| Etapa | Link | Esperado |
|---|---|---|
| A. Importar por URL | `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/t8b/ps4storebr-t8b-depois-v1.01.gssource` (fonte **1.0.3**, item v1.01, fixo) | fonte aceita; item v1.01 aparece na busca |
| B. Atualizar | link estável acima (agora **1.0.4**, item **v1.02**, gerado pelo workflow) | SSPI aceita como versão nova; o item passa a v1.02 |
| C. Instalar (opcional) | item v1.02 (*Reinstall*/exclua o app antes) | abre mostrando "VERSAO 1.02" |

```text
T9
A: importou por URL [sim/não+msg] | versão da fonte [__] | item achado v[__]
B: reimportou o link estável [sim/não+msg] | aceita como versão nova [sim/não] | versão da fonte [__] | item v[__]
C: instalou v1.02 [sim/não+msg] | abre mostrando 1.02 [sim/não]
```
Se A falhar, usar USB (`dist/t8b/…`) e me enviar a mensagem exata: o TLS do SSPI ao baixar **a fonte** por URL não foi provado (o do PKG foi, no T8b).

## 4) Como entra um pacote novo
- **Pacote próprio:** coloque o `.pkg` em `pkgs/` (o robô o descobre pela API do GitHub) e rode o workflow. Precisa de ID `CUSA`, `Content ID` = `TITLE_ID` e `sce_module` (use `app/build.sh`).
- **Pacote de terceiros:** só com autorização registrada **por item** em `config/sources.json` (`authorized_titles`) e ID `CUSA`. Hoje não há nenhum.
- Entram no catálogo instalável **somente** os pacotes que passam em: link acessível, identidade lida do PKG, ID compatível com o importador, host com TLS ok e autorização. O resto fica no relatório.

## Limites
Comprovado no console só para o app próprio (T8b). Não garante jogos comerciais, outros hosts, atualizações ou DLC. O PKG-Zone continua só como descoberta/relatório (sem autorização de listagem).
