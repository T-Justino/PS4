# Operação: automação e cadastro de fontes autorizadas

## 1. Como o catálogo é atualizado

```text
config/sources.json ──► ps4store run ──► descobre → verifica (Range 64 KiB) → fases → dedupe → build → check
                                          └► dist/auto/ps4storebr-auto.gssource  (só se mudou)
                                          └► data/generated/auto-catalog.json, data/state/discovery-state.json
```
- **Automático:** `.github/workflows/catalogo.yml` a cada 6 h (UTC `23 */6 * * *`) e sob demanda (*Actions → catalogo → Run workflow*). Roda os testes primeiro; se falharem, nada é publicado.
  Só commita se `.gssource`, catálogo ou estado mudaram. Relatório completo no *Summary* do job.
- **Manual local:** `PYTHONPATH=src python3 -m ps4store run` (`--refresh-links N` enriquece N links em cache por execução; `--dry-run` não grava nada; `--recheck` ignora o cache e sonda tudo, use com moderação).
- **Link que o PS4 importa:** `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/auto/ps4storebr-auto.gssource` (cache de 5 min do GitHub).

### Regras de segurança do pipeline
| Situação | Comportamento |
|---|---|
| Nenhuma entrada publicável, ou erro de compilação/validação | mantém o `.gssource` anterior |
| Fonte **crítica** (`critical`, padrão `true`) fora do ar | mantém o anterior (para não perder entradas), código de saída **3**, job vermelho |
| Fonte não crítica fora do ar | segue sem ela e registra o erro |
| Testes falham no workflow | nada é publicado |
| Mesmo conteúdo | artefato idêntico, versão da fonte **não** sobe |
| Conteúdo muda | `source.version` = `1.0.N+1` (o SSPI só aceita revisão com versão maior) |
| Várias versões do mesmo `titleId` | só a maior entra (`SUPERSEDED` nas demais) |

### Quando algo dá errado
- **Job vermelho:** abra o *Summary*; veja a fonte com `erro`. Corrija a fonte ou marque `critical: false` se ela for só descoberta.
- **Catálogo ruim publicado:** `git revert <commit "catalogo: atualizacao automatica">` e rode o workflow; ou restaure uma fonte de `dist/t8b/` ou do histórico do Git. Reimporte no PS4 só se a versão da fonte for **maior** (reverter exige nova versão; rode o robô de novo).
- **Workflow parou de rodar:** o GitHub desativa agendamentos de repositórios sem atividade por ~60 dias. Reative em *Actions*. (O disparo por `cron` ainda não foi observado; os dois runs validados foram manuais.)
- **Limite da API do GitHub:** o job usa o `GITHUB_TOKEN` automático (maior limite); localmente defina `GITHUB_TOKEN` se vir `HTTP 403`.

## 2. Cadastrar uma nova fonte autorizada

**Você cadastra a FONTE e a AUTORIZAÇÃO. Nunca a URL do arquivo:** os arquivos são descobertos sozinhos.

### Checklist (todos obrigatórios antes de habilitar)
1. **Autorização por escrito** para listar os pacotes: licença que permita distribuição, release oficial do autor, ou permissão escrita (guarde o texto/URL em `evidence`). `robots.txt` e acesso público **não** são autorização.
2. **Acesso automatizado permitido:** API/feed documentado ou termos que não proíbam. Sem CAPTCHA, login ou desafio anti-bot.
3. **Download direto por HTTPS** sem login, em host que o SSPI baixa (comprovados: `raw.githubusercontent.com`; `github.com` **falha** com TLS). Teste um arquivo pequeno no console antes (modelo: `docs/TESTE_T8B.md`).
4. **IDs `CUSA`** (únicos aceitos pelo importador), com `Content ID` = `TITLE_ID` (use `python3 app/verify_pkg.py arquivo.pkg`) e, para apps OpenOrbis, `sce_module/libc.prx` e `libSceFios2.prx`.
5. **Não publicar** jogos/apps comerciais nem pacotes de terceiros sem a autorização do item.

### Tipos de fonte (`config/sources.json`)
| `type` | Descobre | Campos |
|---|---|---|
| `github-releases` | `.pkg` das releases do repositório (API do GitHub) | `repo` (`dono/nome`), `include_prereleases`, `max_releases` |
| `github-contents` | `.pkg` de uma pasta do repositório; link `raw` (host comprovado) | `repo`, `path`, `ref` (opcional) |
| `pkg-zone-catalog` | releases PS4 ativas do catálogo público do PKG-Zone | `base_url`, `delay_seconds`, `max_probes`, `recheck_hours` |

Campos comuns: `id` (minúsculas e hífens), `enabled`, `critical` (padrão `true`), `authorization` (`{"basis": "license|official-developer-release|written-permission", "evidence": "..."}` **ou `null`** = só descobre e relata, **nunca publica**),
`authorized_titles` (autorização **por item**: `{"CUSA12345": {"basis": "...", "evidence": "..."}}`; vale mesmo com `authorization: null`).
Política de TLS: `tls.known_bad_hosts` (bloqueia a publicação, ex. `github.com`), `tls.untested_hosts` (só avisa), `tls.enforce`.

### Passo a passo
1. Edite `config/sources.json`: copie um bloco existente e ajuste (exemplo `github-releases`):
   ```json
   {"id": "autor-app", "type": "github-releases", "repo": "autor/app", "critical": false,
    "authorization": {"basis": "license", "evidence": "GPL-3.0 em https://github.com/autor/app/blob/main/LICENSE"}}
   ```
   Comece com `critical: false` até a fonte provar-se estável.
2. `PYTHONPATH=src python3 -m ps4store run --dry-run` e leia a saída/relatório: o item deve aparecer, e a fase final (`PUBLICAVEL`) só ocorre se ID `CUSA`, identidade ok, TLS ok e autorização.
3. Publique: commite a config e rode o workflow. O PS4 recebe ao reimportar o link (docs/USO_NO_PS4.md).
4. **Pacote próprio:** coloque o `.pkg` em `pkgs/` (fonte `own-contents`); sem mexer na config. Gere com `bash app/build.sh` (`APP_VERSION=1.03 bash app/build.sh`).
5. **Autorizar um item de uma fonte sem autorização geral** (ex.: um app do PKG-Zone, depois de licença/permissão do autor): `authorized_titles` na fonte. Continua exigindo ID `CUSA`.
6. **Desativar/remover:** `"enabled": false` (o item some do catálogo na próxima execução; o relatório mantém o histórico no estado).

## 3. Testes
`PYTHONPATH=src python3 -m pytest -q` → **131 testes**, sem rede (Python 3.11, 3.12 no Actions e 3.13). Cobrem: formato `.gssource` e validador, regras do canônico, leitura de PKG, conectores
(Releases, Contents, PKG-Zone), fases e rejeições, autorização por item, cache e teto de sondagens, uma versão por ID, fonte crítica, rede segura (servidor local com Range/redirect) e os artefatos do T8.
**Não substituem o teste no console**: o que foi comprovado no PS4 está em `docs/TESTE_*.md`.

## 4. Mapa do que está comprovado
| | Código/testes | Rede real | PS4 real |
|---|---|---|---|
| Descobrir, verificar, publicar sem cadastrar URL | sim | sim (GitHub Contents/Releases, PKG-Zone) | — |
| Fonte importada por URL e atualizada (1.0.3→1.0.4) | sim | sim (workflow) | **sim (T9)** |
| Baixar, instalar e abrir um app do catálogo | — | — | **sim (T8b, v1.00, app próprio)** |
| Instalar a v1.02 (atualização do app) | — | — | **não testado** |
| Agendamento por `cron` | — | **não observado** | — |
