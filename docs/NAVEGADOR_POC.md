# Navegador automatizado (Etapa 4C, prova de conceito)

Página dinâmica → Chromium (Playwright) → URLs → `resolver.py` → arquivos e volumes RAR organizados. Módulo isolado `src/ps4store/browser.py`; o resolvedor HTTP, a descoberta, o catálogo web, o workflow e o SSPI **não foram alterados**. Não é servidor nem serviço: roda localmente, sob demanda.

## Como rodar (local)
```
pip install playwright && playwright install chromium     # uma vez; é extra opcional (pip install -e '.[browser]')
python -m ps4store.browser URL [--permitir host] [--assistido] [--max-cliques 3] [--json]
```
`--assistido` abre a janela visível; nas barreiras humanas (CAPTCHA, login, verificação) a automação **pausa** e espera você resolver e apertar Enter. Sem `--assistido` ela só para e explica.

## Regras do PoC
- Só entra em hosts de `config/resolver-hosts.json` (ou `--permitir`). Navegação e **nova aba** para outro host são abortadas e registradas.
- **Nunca** automatiza CAPTCHA/login/verificação: interrompe (`INTERACAO_NECESSARIA`) ou espera a pessoa (`--assistido`) e confere que a barreira sumiu.
- **Não baixa**: todo download é cancelado na hora; só a URL é registrada.
- Cliques: no máximo 3, só em botões/links visíveis cujo texto é de ação (baixar, download, gerar link, continuar…). Recusa o que parece anúncio (classe/id/`rel=sponsored`/ancestral `ad|sponsor|banner`), o invisível e o que aponta para host não permitido; links de anúncio também não entram no resultado.
- Acompanha redirecionamento por JavaScript, `meta refresh`, abas abertas por ação e downloads iniciados por clique.
- Cada passo é registrado como **AUTOMÁTICO** ou **INTERVENÇÃO**.

## Resultados reais (22/11/2026)
Testes: `tests/test_browser.py` (12, servidor local com páginas JavaScript próprias). Suíte completa **205 passam** com Playwright; **193 passam + 1 pulado** sem ele.

| Caso | Resultado |
|---|---|
| link criado por JS 300 ms depois do carregamento | achado, automático |
| botão "Gerar link" revela 3 volumes RAR fora de ordem | achados; resolvedor entrega o conjunto **completo e na ordem 01-02-03** |
| redirecionamento por JS / `meta refresh` | seguido / download interceptado |
| botão abre nova aba (permitida) | aba lida, link achado; outra aba para host não permitido fechada, sem requisição |
| botão que dispara download | URL registrada, download **cancelado** |
| banner e botão de anúncio ("Download now!") | **não clicados** (0 requisições ao destino); botão legítimo funciona |
| CAPTCHA / campo de senha | para; **INTERVENÇÃO**; nenhum link coletado |
| CAPTCHA + `--assistido` (a "pessoa" remove o desafio) | retoma e acha o link |
| host de entrada não permitido / página vazia | `HOST_NAO_PERMITIDO` / `SEM_URLS` |

**Página real:** `https://pkg-zone.com/` (SvelteKit), que o resolvedor HTTP classificava `INTERACAO_NECESSARIA`. Com o navegador: DOM renderizado, **3 links** (`/download/ps4/MOZI00001/latest`, `/update/Store-R2.pkg`, `/update/Store-R2-PS5.pkg`), todos classificados `OK` e enviáveis (13,9 / 24,8 / 43,5 MB), sem nenhuma intervenção.

## O que funcionou automaticamente × o que exige intervenção
- Automático: renderização JS, links no DOM, redirecionamento, nova aba, botão de ação de download, download interceptado, anúncios ignorados.
- Intervenção humana: CAPTCHA, login, verificação anti-robô, contagem/espera obrigatória só se a página a trouxer como barreira, qualquer botão sem texto de ação reconhecível.

## Limites e o que falta
- Não testado contra um hoster real com CAPTCHA/contagem: só contra páginas próprias (a detecção usa widgets/atributos conhecidos e texto; páginas desconhecidas podem escapar ou gerar falso alarme).
- Heurística de anúncio é por classe/atributos/host; um anúncio sem nenhum desses sinais e com texto "Baixar" poderia ser clicado (limite de 3 cliques e bloqueio de host reduzem o dano).
- Só Chromium, headless por padrão; `--assistido` exige tela (não testado aqui, só a lógica por callback).
- Cada execução abre um Chromium novo (≈ 2 s); para uso contínuo seria preciso reaproveitar o navegador.
- Não é integrado ao catálogo, ao site nem ao workflow (decisão para uma etapa seguinte).
