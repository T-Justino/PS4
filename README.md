# PS4 Store BR

Robô que **descobre pacotes em fontes autorizadas, verifica os links e gera automaticamente um catálogo `.gssource`** para o SSPI (PS4). **Não hospeda nem baixa jogos**: o console baixa direto da origem.

## Estado do MVP técnico (22/11/2026)

| Etapa | Estado |
|---|---|
| Descoberta automática sem cadastrar URL (GitHub Contents/Releases, PKG-Zone) | **comprovada** em rede real |
| Verificação de link e identidade do PKG; fases DESCOBERTO → VERIFICADO → PUBLICÁVEL | **comprovada** |
| Catálogo gerado e atualizado sozinho (GitHub Actions, execuções manuais com sucesso) | **comprovada**; disparo por `cron` ainda não observado |
| SSPI importa e **atualiza a fonte por URL** (1.0.3 → 1.0.4), pesquisa e mostra o item | **comprovada no PS4 (T9)** |
| Baixar, instalar e **abrir** um app do catálogo | **comprovada no PS4 (T8b), só para o app próprio v1.00** |
| Variedade real de jogos | **não existe**: 1 título publicável. Ver `docs/LIMITACOES.md` |

**Ressalva:** os testes no console valem para o app próprio `PS4 Store BR Test` (`CUSA95417`, ID experimental), este PS4 Pro 9.00/GoldHEN e o SSPI 5.11.7. Não garantem jogos comerciais, outros hosts, atualizações ou DLC.

## Usar

```bash
PYTHONPATH=src python3 -m ps4store run              # descobre → verifica → gera dist/auto/ps4storebr-auto.gssource
PYTHONPATH=src python3 -m ps4store run --dry-run    # sem gravar nada
PYTHONPATH=src python3 -m pytest -q                 # 131 testes (Python ≥ 3.11, sem dependências de runtime)
```
No PS4 (sem PC): cole `https://raw.githubusercontent.com/T-Justino/PS4/ccr-8aace08a-bzwy8i/dist/auto/ps4storebr-auto.gssource` na página do celular do SSPI (aba *Sources*). Passo a passo: `docs/USO_NO_PS4.md`.

## Pesquisa de links e download direto (modo pessoal)
`ps4store run` também grava `local/research.json` (tudo o que foi achado, com status do link e motivo) e `local/links-sspi.txt` (links para **colar** no SSPI, sem passar pelo importador de IDs). `local/` **nunca** é commitado; itens de aparência comercial ficam só na pesquisa. Detalhes, números reais e obstáculos: `docs/PESQUISA_DE_LINKS.md`.

## Operar e cadastrar fontes
`docs/OPERACAO.md` (workflow, regras de segurança, como cadastrar uma fonte autorizada, checklist). **Cadastra-se a fonte e a autorização, nunca a URL do arquivo.**

## Estrutura
```text
src/ps4store/    sspi.py (formato+validador) · catalog.py (canônico) · build.py · pkginfo.py (PKG) · net.py (rede segura) · discover.py (conectores, fases, run) · cli.py
config/sources.json   fontes, autorizações e política de TLS
pkgs/                 PKGs próprios monitorados (v1.00, v1.01, v1.02)
app/                  app de teste OpenOrbis + build.sh + verify_pkg.py
data/                 canônico gerado, estado do robô, fixtures históricas
dist/                 artefatos (ver dist/README.md)
.github/workflows/    catalogo.yml (agendado a cada 6 h)
docs/                 índice em docs/README.md
tests/                131 testes
```

## Regras do catálogo instalável
- `titleId` = **ID real do pacote**, lido do próprio PKG; `Content ID` = `TITLE_ID`. Só IDs `CUSA` (único prefixo aceito pelo importador do SSPI: `NPXS`/`APOL` são recusados). Chaves sintéticas são bloqueadas.
- Só entra com **autorização registrada** (por fonte ou por item), link HTTPS acessível, host sem falha de TLS conhecida e tipo "base". O restante fica no relatório com o motivo.
- Uma versão por `titleId` (a maior). A versão da fonte (`1.0.N`) só sobe quando o conteúdo muda.
- URLs só `https://`, sem credenciais nem IP privado. Sem `sha256` inventado. Sem banco de dados, VPS ou IA.
