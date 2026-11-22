# Descoberta × validação de link × publicação

**Princípio:** descobrir uma URL pública **não é** autorização de uso ou distribuição, e a falta de licença **não** é motivo para esconder um resultado. O robô tem três etapas independentes; só a terceira decide o que pode ser oferecido.

| Etapa | Módulo | Faz | Nunca faz |
|---|---|---|---|
| **1. DISCOVERY** | `discover.py` (conectores) | consulta APIs/índices públicos; registra título, arquivo, URL pública, versão, tamanho, tipo, fonte, licença declarada ou `LICENSE_UNKNOWN`; guarda releases inativas/antigas e arquivos compactados | filtra por licença, autorização, categoria ou prefixo de ID; baixa arquivos |
| **2. LINK_VALIDATION** | `validation.py` | 1 `Range` de 64 KiB: acessibilidade, redirects, URL temporária, suporte a Range, tipo/assinatura do arquivo, tamanho do servidor, **identidade lida do PKG** (Content ID, `TITLE_ID`, categoria); deduplicação | consulta autorização, TLS do console, licença ou prefixo de ID |
| **3. PUBLICATION** | `publication.py` | **compatibilidade SSPI** (prefixo aceito, tipo base, placeholder, HTTPS: lista *todos* os motivos) e **disponibilidade** (catálogo publicável; link direto pessoal) | acessa a rede; altera o que foi descoberto/validado |

Tipos e configuração compartilhados: `model.py`. Um teste (`test_separation.py`) impede que `validation.py` mencione autorização/TLS/licença e que `publication.py` toque a rede.

## O que fica no catálogo interno de pesquisa (`local/research.json`, fora do Git)
Nome · ID (CUSA ou outro) e Content ID · fonte e URL pública · versão, tamanho, formato · **status do link** (`direto`, `redirect`, `pagina-intermediaria`, `exige-autenticacao` 401, `acesso-negado` 403, `expirado`, `removido`, `erro-de-rede`) · redirects/cadeia, URL temporária, `Range` · **licença** (`KNOWN` + SPDX, ou `LICENSE_UNKNOWN`; a descrição da fonte pode dar só uma pista, `licenseHint`) · autorização configurada · **motivos de incompatibilidade** e **impeditivos de publicação/instalação** · descrição, autor, firmware, repositório/consulta de origem.
`LICENSE_UNKNOWN` é informativo: não elimina o resultado e **também não autoriza** nada.

## As cinco perguntas (relatório `dist/auto/discovery.report.md`, `ps4store run` e `research.json`)
| Pergunta | Valores | Quem responde |
|---|---|---|
| **Encontrado** | sempre sim (se está no relatório) | DISCOVERY |
| **Link acessível** | ✓ / ✗ / — (não validado ainda) | LINK_VALIDATION |
| **Arquivo identificado** | ✓ (ID lido do PKG) / ✗ / — (compactado ou não validado) | LINK_VALIDATION |
| **Compatível com o SSPI** | compatível / incompatível / não avaliado (+ motivos) | PUBLICATION |
| **Disponível** | em **catálogo publicável** (autorização + TLS + sem aparência comercial) e por **link direto** (lista pessoal): disponível / bloqueado (+ impeditivos) / não avaliado | PUBLICATION |

Os impeditivos de publicação são independentes dos de compatibilidade: p.ex. um homebrew `NPXS` é *incompatível com o catálogo* mas *disponível por link direto*; um app com Content ID `UP…` é *compatível* mas *bloqueado em ambos* (aparência comercial).

## Busca genérica
- **`github-search`** (novo conector): consultas fixas na **API pública de busca de repositórios do GitHub** (`config/sources.json`: `topic:ps4-homebrew`, `topic:openorbis`, `topic:goldhen`, `topic:ps4 topic:pkg`), depois as releases de cada repositório achado. Sem login, sem raspagem; só descoberta (sem autorização registrada, nada é publicado).
- **`ps4store search`** (novo comando): consulta o catálogo de pesquisa por nome, ID (CUSA ou outro), Content ID, URL, fonte, autor, **tipo de arquivo** e status:
  ```bash
  PYTHONPATH=src python3 -m ps4store search tyrian                         # por nome
  PYTHONPATH=src python3 -m ps4store search CUSA95417 --urls               # por identificador
  PYTHONPATH=src python3 -m ps4store search --type rar-multiparte          # por tipo de arquivo
  PYTHONPATH=src python3 -m ps4store search --only installable --license known
  ```
  (`--only`: accessible, identified, compatible, incompatible, available, blocked, installable.)
- Campos novos por fonte (`config/sources.json`): `all_types` (registra ZIP/7z/RAR únicos, padrão `true`), `include_inactive` (releases antigas, padrão `true`), `inactive_probe_budget` (quantas validar por execução, padrão 15), `queries`/`max_repos` (busca).

## O que antes se perdia e agora é registrado (execução real, 22/11/2026, GitHub Actions run `45041059933`)
| | Antes | Agora |
|---|---|---|
| **Releases inativas/antigas do PKG-Zone** | 0 (descartadas) | **137** registradas (versão, tamanho, URL estável); 30 já validadas; as validadas dão **403** no link estável (o site as recusa; classificadas `acesso-negado`, sem tentar contornar) |
| **ZIP/7z/RAR únicos** em releases do GitHub | 0 | **22** (assinatura conferida; identidade só após extrair) |
| **Repositórios fora da lista configurada** | 0 | **16 repositórios / 50 arquivos** achados pela busca (p.ex. EmuSuNi, Control4Free, NULL_store, PStream, o próprio SSPI), todos com PKG lido |
| **Licença** | não era registrada | **55 conhecidas** (SPDX do repositório), **346 `LICENSE_UNKNOWN`** |
| Itens "rejeitados por autorização" | contavam como rejeitados | seguem **encontrados, acessíveis e identificados**; só a coluna de catálogo diz "bloqueado: `NO_AUTHORIZATION`" |

## Resultado real (Actions, todas as fontes)
| Pergunta | Sim | Não | Não avaliado |
|---|---|---|---|
| Encontrados | **401** | | |
| Link acessível | 111 | 15 | 275 (validação incremental: inativas, PS5, orçamento) |
| Arquivo identificado | 222 | 0 | 179 (compactados e não validados) |
| Compatível com o SSPI | 22 | 200 | 179 |
| Disponível em catálogo publicável | **1** (app próprio) | 221 | 179 |
| Disponível por link direto (sem `github.com`, sem aparência comercial) | 29 | 193 | 179 |

Por fonte (registrados / links validados / identidade lida): PKG-Zone 328/53/182 · busca GitHub 50/50/29 · Apollo 5/5/5 · LightningMods 4/4/3 · pasta própria 4+11 RAR.
Saída completa: `docs/evidencia/descoberta-matriz-actions-22-11-2026.txt`. Entre os 401 achados, 111 links foram validados com `Range`; 97 são redirects para URL temporária.

## O que não mudou (publicação)
Catálogo compartilhado só com **autorização registrada** (fonte ou item), ID aceito pelo importador, host sem falha de TLS e sem aparência comercial; `authorized_titles` só atua na etapa PUBLICATION. Itens de aparência comercial ficam como metadados (nenhuma lista de download). Nada de contornar autenticação, CAPTCHA ou proteção.

## Limites
- Validação de links é **incremental** (por orçamento) para não sobrecarregar as fontes: 275 achados ainda sem link validado.
- GitHub Releases baixam via `github.com` (TLS falho no seu console): ficam fora da lista de download direto.
- A busca usa 4 consultas fixas × 10 repositórios; resultados de busca do GitHub são amostra, não inventário completo.
- Identidade só para PKG; ZIP/7z/RAR únicos têm a identidade interna desconhecida até extrair.
