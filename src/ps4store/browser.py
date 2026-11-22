"""BROWSER (prova de conceito): páginas dinâmicas -> navegador (Playwright/Chromium) -> URLs de arquivo -> resolver.py -> resultado organizado.

Isolado: só LÊ constantes/funções do resolver.py (não o altera). Nunca automatiza CAPTCHA/login/verificação humana: interrompe e pede
intervenção (ou, com `assistido=True`, espera a pessoa resolver na janela visível e continua). Não baixa arquivos: todo download é
CANCELADO na hora e só a URL é registrada. Navegação (inclusive nova aba) para host fora da lista é abortada. Cliques: no máximo
`max_cliques`, só em ações de download visíveis, nunca em anúncios. Playwright é opcional: `pip install playwright` (ver docs/NAVEGADOR_POC.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

from .resolver import (_DL_HINT, _FILE_HREF, _LOGIN_PATH, ARQUIVOS, ResolverNet, crawl, group_sets, load_hosts)

ENCONTRADAS, INTERACAO, SEM_URLS, NAO_PERMITIDO = "URLS_ENCONTRADAS", "INTERACAO_NECESSARIA", "SEM_URLS", "HOST_NAO_PERMITIDO"
AUTO, HUMANO = "automatico", "intervencao"
_ACTION = re.compile(r"download|baixar|descarreg|descarg|gerar|generate|get link|create link|obter|continuar|continue|iniciar|start", re.I)
_AD = re.compile(r"(^|[\s_-])(ad|ads|advert\w*|sponsor\w*|banner|promo\w*|popup|affiliate|publicidade)([\s_-]|$)", re.I)
_BARRIER_SELECTORS = [
    (".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare.com']", "CAPTCHA"),
    ("input[type=password]", "login (campo de senha)"),
]
_BARRIER_TEXT = re.compile(r"verify you are human|are you a robot|checking your browser|just a moment|confirme que você é humano|não sou um robô", re.I)


@dataclass
class Found:
    url: str
    via: str          # dom | download | popup | redirect | click
    fromPage: str = ""


@dataclass
class BrowserResult:
    inputUrl: str
    status: str = SEM_URLS
    found: list = field(default_factory=list)          # [Found]
    steps: list = field(default_factory=list)          # [{step, outcome: automatico|intervencao, detail}]
    blocked: list = field(default_factory=list)        # [{url, reason}] navegações abortadas / cliques recusados
    explanation: str = ""

    def step(self, name: str, outcome: str, detail: str = "") -> None:
        self.steps.append({"step": name, "outcome": outcome, "detail": detail})

    def add(self, url: str, via: str, page: str = "") -> None:
        url = urldefrag(url)[0]
        if url and urlsplit(url).scheme in ("http", "https") and all(f.url != url for f in self.found):
            self.found.append(Found(url, via, page))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _relevant(href: str, text: str) -> str | None:
    path = urlsplit(href).path
    if _LOGIN_PATH.search(path):
        return None
    if _FILE_HREF.search(path):
        return "arquivo"
    if _DL_HINT.search(href) or _DL_HINT.search(text):
        return "pagina"
    return None


def _barrier(page) -> str | None:
    for sel, why in _BARRIER_SELECTORS:
        if page.locator(sel).count():
            return why
    try:
        if _BARRIER_TEXT.search(page.inner_text("body", timeout=1500)):
            return "verificação anti-robô"
    except Exception:
        pass
    return None


def _settle(page, ms: int = 4000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    page.wait_for_timeout(300)


def _scan_dom(page, res: BrowserResult, hosts: set[str], via: str = "dom") -> int:
    n = 0
    for a in page.locator("a[href]").all():
        try:
            href = a.get_attribute("href") or ""
            text = (a.inner_text(timeout=500) or "").strip()
            attrs = a.evaluate("e => (e.className && e.className.baseVal === undefined ? e.className : '') + ' ' + (e.id || '') + ' ' + (e.getAttribute('rel') || '')"
                               " + ' ' + (e.closest('[class*=ad],[id*=ad],[class*=sponsor],[class*=banner]') ? 'ad-ancestor' : '')")
        except Exception:
            continue
        if href.lower().startswith(("javascript:", "mailto:", "#")):
            continue
        absu = urljoin(page.url, href)
        kind = _relevant(absu, text)
        if kind and (_AD.search(attrs) or "ad-ancestor" in attrs or "sponsored" in attrs):
            res.blocked.append({"url": absu, "reason": "link ignorado: parece anúncio (classe/atributo)"})
            continue
        if kind and _host(absu) in hosts:
            before = len(res.found)
            res.add(absu, via, page.url)
            n += len(res.found) - before
    return n


def _click_candidates(page, hosts: set[str]) -> list[dict]:
    """Ações visíveis que parecem 'baixar/gerar link' e NÃO parecem anúncio. Devolve [{index, text, why_skip|None}]."""
    info = page.evaluate("""() => [...document.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]')].map((e, i) => {
        const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
        return {i, tag: e.tagName.toLowerCase(), text: (e.innerText || e.value || '').trim().slice(0, 80), href: e.getAttribute('href') || '',
                cls: (e.className && e.className.baseVal === undefined ? e.className : '') + ' ' + (e.id || '') + ' ' + (e.getAttribute('rel') || '') + ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.closest('[class*=ad],[id*=ad],[class*=sponsor],[class*=banner]') ? 'ad-ancestor' : ''),
                visible: r.width > 8 && r.height > 8 && cs.visibility !== 'hidden' && cs.display !== 'none', target: e.getAttribute('target') || '',
                inIframe: false}; })""")
    out = []
    for e in info:
        if not _ACTION.search(e["text"]):
            continue
        why = None
        absu = urljoin(page.url, e["href"]) if e["href"] else ""
        if not e["visible"]:
            why = "invisível"
        elif _AD.search(e["cls"]) or "ad-ancestor" in e["cls"] or "sponsored" in e["cls"]:
            why = "parece anúncio (classe/atributo)"
        elif absu and _host(absu) and _host(absu) not in hosts:
            why = f"aponta para host não permitido ({_host(absu)})"
        elif absu and (_relevant(absu, e["text"]) == "arquivo"):
            why = "já é um link estático (não precisa de clique)"
        out.append({"index": e["i"], "text": e["text"], "skip": why})
    return out


def explore(url: str, hosts: set[str] | None = None, *, headless: bool = True, max_cliques: int = 3, timeout_ms: int = 15000,
            assistido=None, chromium_path: str | None = None) -> BrowserResult:
    """`assistido`: função(page, motivo) chamada quando há barreira humana; deve devolver True quando a pessoa terminou (ex.: input())."""
    from playwright.sync_api import sync_playwright
    hosts = load_hosts() if hosts is None else {h.lower() for h in hosts}
    res = BrowserResult(url)
    if _host(url) not in hosts:
        res.status, res.explanation = NAO_PERMITIDO, f"{_host(url) or '?'} fora da lista de fontes permitidas"
        return res
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, **({"executable_path": chromium_path} if chromium_path else {}))
        ctx = browser.new_context(accept_downloads=True)
        popups: list = []

        def route(r):
            req = r.request
            if req.resource_type in ("image", "media", "font"):
                return r.abort()
            if req.resource_type == "document" and _host(req.url) not in hosts and not req.url.startswith(("about:", "data:", "blob:")):
                res.blocked.append({"url": req.url, "reason": "navegação para host não permitido (abortada)"})
                return r.abort()
            return r.continue_()

        ctx.route("**/*", route)
        ctx.on("page", lambda pg: popups.append(pg))
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)

        def on_download(d):                                               # nunca baixa: registra a URL e cancela
            res.add(d.url, "download", page.url)
            res.step("download interceptado", AUTO, f"{d.suggested_filename}: cancelado, só a URL foi registrada")
            d.cancel()

        page.on("download", on_download)
        ctx.on("page", lambda pg: pg.on("download", on_download))
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            if "ERR_ABORTED" not in str(e) and "Download is starting" not in str(e):
                res.status, res.explanation = SEM_URLS, f"falha ao abrir a página: {str(e).splitlines()[0][:120]}"
                browser.close()
                return res
        _settle(page)
        res.step("abrir e renderizar", AUTO, f"{page.url}")
        if page.url != url and _host(page.url) in hosts:
            if _FILE_HREF.search(urlsplit(page.url).path):
                res.add(page.url, "redirect", url)
            res.step("redirecionamento no navegador", AUTO, f"{url} → {page.url}")

        def barrier_check(pg) -> bool:
            why = _barrier(pg)
            if not why:
                return False
            res.step(f"barreira: {why}", HUMANO, "a automação não resolve nem contorna; intervenção humana necessária")
            if assistido is None:
                res.status, res.explanation = INTERACAO, f"a página exige {why}: resolva no navegador (use --assistido) ou cole o link final"
                return True
            if not assistido(pg, why):
                res.status, res.explanation = INTERACAO, f"a página exige {why} e a intervenção não foi concluída"
                return True
            _settle(pg)
            if _barrier(pg):
                res.status, res.explanation = INTERACAO, f"a barreira ({why}) ainda está presente após a intervenção"
                return True
            res.step(f"barreira {why} resolvida pela pessoa", HUMANO, "automação retomada")
            return False

        if barrier_check(page) and res.status == INTERACAO:
            browser.close()
            return res
        n = _scan_dom(page, res, hosts)
        res.step("ler links do DOM renderizado", AUTO, f"{n} link(s) relevante(s)")
        clicks = 0
        tried: set[str] = set()
        while clicks < max_cliques:
            cands = [c for c in _click_candidates(page, hosts) if c["text"] not in tried]
            for c in cands:
                if c["skip"]:
                    res.blocked.append({"url": c["text"], "reason": f"clique recusado: {c['skip']}"})
                    tried.add(c["text"])
            todo = [c for c in cands if not c["skip"]]
            if not todo:
                break
            c = todo[0]
            tried.add(c["text"])
            clicks += 1
            before_url, before_found, npop = page.url, len(res.found), len(popups)
            try:
                page.evaluate("(i) => document.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]')[i].click()", c["index"])
            except Exception as e:
                res.step(f"clique em “{c['text']}”", AUTO, f"falhou: {str(e).splitlines()[0][:80]}")
                continue
            page.wait_for_timeout(600)
            _settle(page, 3000)
            for pg in popups[npop:]:
                try:
                    pg.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass
                purl = pg.url
                if purl in ("", "about:blank") or _host(purl) not in hosts:
                    res.blocked.append({"url": purl or "(aba vazia)", "reason": "nova aba para host não permitido (provável anúncio): fechada"})
                    res.step("nova aba", AUTO, f"fechada: {purl or 'vazia'}")
                else:
                    res.step("nova aba aberta pela ação", AUTO, purl)
                    if _FILE_HREF.search(urlsplit(purl).path):
                        res.add(purl, "popup", page.url)
                    if barrier_check(pg) and res.status == INTERACAO:
                        pg.close()
                        continue
                    _scan_dom(pg, res, hosts, "popup")
                    if _relevant(purl, ""):
                        res.add(purl, "popup", page.url)
                pg.close()
            if page.url != before_url:
                res.step("redirecionamento após o clique", AUTO, f"{before_url} → {page.url}")
                if _host(page.url) in hosts:
                    if _FILE_HREF.search(urlsplit(page.url).path):
                        res.add(page.url, "redirect", before_url)
                    if barrier_check(page) and res.status == INTERACAO:
                        break
            added = _scan_dom(page, res, hosts, "click")
            res.step(f"clique em “{c['text']}”", AUTO, f"{added} novo(s) link(s)" if added or len(res.found) > before_found else "sem efeito visível")
        browser.close()
    if res.status != INTERACAO:
        res.status = ENCONTRADAS if res.found else SEM_URLS
        res.explanation = f"{len(res.found)} URL(s) de arquivo/página de download" if res.found else "nenhuma URL de arquivo encontrada no DOM renderizado"
    return res


def pipeline(url: str, hosts: set[str] | None = None, net: ResolverNet | None = None, **kw) -> dict:
    """Página dinâmica -> navegador -> URLs -> resolver (crawl, profundidade 1) -> arquivos e conjuntos RAR organizados."""
    hosts = load_hosts() if hosts is None else {h.lower() for h in hosts}
    br = explore(url, hosts, **kw)
    net = net or ResolverNet()
    crawls = [crawl(f.url, net, hosts, max_depth=1) for f in br.found]
    files = []
    for c in crawls:
        for f in c.files:
            if all(f.sspiUrl != g.sspiUrl for g in files):
                files.append(f)
    return {"browser": br, "crawls": crawls, "files": files, "sets": group_sets(files, any(c.truncated for c in crawls))}


def main(argv=None, net: ResolverNet | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.browser", description="página dinâmica -> Chromium -> URLs -> resolvedor (PoC)")
    ap.add_argument("url")
    ap.add_argument("--permitir", action="append", default=[], metavar="HOST")
    ap.add_argument("--hosts", default="config/resolver-hosts.json")
    ap.add_argument("--assistido", action="store_true", help="janela visível; pausa nas barreiras humanas até você resolver e apertar Enter")
    ap.add_argument("--max-cliques", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    hosts = load_hosts(Path(a.hosts)) | {h.lower() for h in a.permitir}

    def ask(page, why):
        input(f"[assistido] resolva '{why}' na janela do navegador e pressione Enter aqui... ")
        return True

    out = pipeline(a.url, hosts, net, headless=not a.assistido, max_cliques=a.max_cliques, assistido=ask if a.assistido else None)
    br = out["browser"]
    if a.json:
        print(json.dumps({"browser": asdict(br), "files": [asdict(f) for f in out["files"]], "sets": out["sets"]}, ensure_ascii=False, indent=1))
        return 0
    print(f"NAVEGADOR: {br.status} · {br.explanation}")
    for s in br.steps:
        print(f"  [{'AUTOMÁTICO' if s['outcome'] == AUTO else 'INTERVENÇÃO'}] {s['step']}" + (f": {s['detail']}" if s["detail"] else ""))
    for b in br.blocked:
        print(f"  [BLOQUEADO] {b['url'][:100]}: {b['reason']}")
    for f in br.found:
        print(f"  achou ({f.via}): {f.url}")
    from .resolver import _line
    for c in out["crawls"]:
        for r in c.terminal:
            _line(r)
    for g in out["sets"]:
        print(f"RAR {g['set']}: {g['volumes']} volume(s), {g['totalBytes'] / 1e6:.1f} MB, " + ("completo" if g["complete"] else "INCOMPLETO"))
        for p in g["problems"]:
            print(f"    - {p}")
        for u in g["sspiOrder"]:
            print(f"      {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
