"""RESOLVER: de uma URL (ou de várias) até o arquivo final, sem baixar nada além dos primeiros 64 KiB.

Segue redirects HTTP comuns (mesmas regras de segurança do robô), identifica host final, nome, tamanho informado e formato
(PKG/RAR, confirmado pela assinatura dos bytes), e agrupa volumes `.partNN.rar` preservando a ordem. Páginas HTML que exigem
JavaScript, CAPTCHA, login ou espera NÃO são contornadas: viram INTERACAO_NECESSARIA. Não executa nada, não grava arquivos,
não altera o catálogo; só LÊ (reaproveita net.py e links.py).
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
from collections import deque
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from .links import classify_link, file_type, multipart_info
from .net import SIGNED_RE, UA, NetError, Probe, UrllibNet, _expires_in, _Redirects

MAX_HTML = 256 * 1024
MAGIC = ((b"\x7fCNT", "pkg"), (b"Rar!\x1a\x07\x00", "rar"), (b"Rar!\x1a\x07\x01\x00", "rar"), (b"7z\xbc\xaf\x27\x1c", "7z"), (b"PK\x03\x04", "zip"))
INTERACTION = [
    (re.compile(r"captcha|hcaptcha|recaptcha|turnstile|cf-challenge|g-recaptcha", re.I), "CAPTCHA"),   # sobre marcação visível (ver _visible_markup)
    (re.compile(r"enable javascript|requires javascript|please turn on javascript|<noscript[^>]*>[^<]{10,}", re.I), "exige JavaScript"),
    (re.compile(r"just a moment|checking your browser|verify you are human|are you a robot", re.I), "verificação anti-robô"),
    (re.compile(r"type=[\"']?password|log ?in to download|sign ?in to download|faça login", re.I), "exige login"),
    (re.compile(r"please wait \d+ ?(?:s|sec|seconds)|wait \d+ seconds|countdown", re.I), "espera/contagem obrigatória"),
]
_HREF = re.compile(r"""<a\s[^>]*href=["']([^"']+)["']""", re.I)
_ANCHOR = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']*)["'][^>]*>(.*?)</a>""", re.I | re.S)
_META = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']\s*\d+\s*;\s*url=([^"'>\s]+)""", re.I)
_FILE_HREF = re.compile(r"\.(pkg|rar|r\d{2,3})$", re.I)          # aplicada ao CAMINHO da URL, nunca à query (ex.: login?return_to=...x.rar)
_LOGIN_PATH = re.compile(r"/(log-?in|sign-?in|sign-?up|register|session|account/login)(/|$)", re.I)
_DL_HINT = re.compile(r"download|baix|descarg|mirror|espelho|\bdl\b|get[ _-]?file|arquivo", re.I)
_SOFT = [(re.compile(r"<form[^>]+method=[\"']?post", re.I), "formulário POST"), (re.compile(r"<button\b", re.I), "botão que exige ação no navegador"),
         (re.compile(r"onclick=[\"'][^\"']*(location|window\.open)", re.I), "botão com redirecionamento por JavaScript")]
OK, INTERACAO, INACESSIVEL, HOST_NAO_PERMITIDO, PAGINA_SEM_ARQUIVO, FORMATO, NAO_E_ARQUIVO = (
    "OK", "INTERACAO_NECESSARIA", "INACESSIVEL", "HOST_NAO_PERMITIDO", "PAGINA_SEM_ARQUIVO", "FORMATO_NAO_SUPORTADO", "NAO_E_ARQUIVO")


@dataclass
class Resolved:
    inputUrl: str
    status: str
    detail: str = ""
    finalUrl: str = ""                 # só informativa: pode ser assinada e expirar
    finalHost: str = ""
    sspiUrl: str = ""                  # a URL estável que se cola no SSPI (ele refaz o redirect por ela)
    filename: str = ""
    sizeBytes: int | None = None
    format: str = ""                   # pkg | rar | rar-multiparte | 7z | zip | desconhecido
    formatConfirmedByBytes: bool = False
    chain: list = field(default_factory=list)
    rangeOk: bool = False
    linkKind: str = ""
    sspiSendable: bool = False         # PKG ou RAR com link utilizável pelo baixador do SSPI (hipótese pelo código; só o console prova)
    volume: dict | None = None         # {set, index, style} para volumes RAR
    candidates: list = field(default_factory=list)   # PKG/RAR ligados por <a href> estático na página (não seguidos)
    links: list = field(default_factory=list)        # links relevantes da página (absolutos): {url, text, kind}
    notes: list = field(default_factory=list)


class ResolverNet(UrllibNet):
    """Mesma segurança do robô (HTTPS, ≤5 redirects, sem IP privado), mas devolve também os cabeçalhos úteis."""

    def fetch(self, url: str, nbytes: int = 65536):
        try:
            self._check_url(url)
        except NetError as e:
            return Probe(False, error=str(e)), {}, b""
        red = _Redirects(self)
        red.hosts.append(urlsplit(url).hostname or "")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes=0-{nbytes - 1}", "Accept-Encoding": "identity",
                                                   "Accept": "*/*"})
        try:
            with urllib.request.build_opener(red).open(req, timeout=self.timeout) as r:
                hdr = {k.lower(): v for k, v in r.headers.items()}
                ctype = r.headers.get_content_type()
                body = r.read(MAX_HTML if ctype.startswith("text/") else nbytes)
                m = re.match(r"bytes (\d+)-(\d+)/(\d+)$", hdr.get("content-range", ""))
                total = int(m.group(3)) if m else (int(hdr["content-length"]) if r.status == 200 and hdr.get("content-length", "").isdigit() else None)
                pr = Probe(r.status in (200, 206), r.status, None, total, body[:nbytes], r.geturl(), ctype, red.count,
                           range_ok=r.status == 206 and bool(m), content_encoding=hdr.get("content-encoding"), etag=hdr.get("etag"),
                           last_modified=hdr.get("last-modified"), chain=list(red.hosts), signed=bool(SIGNED_RE.search(r.geturl())),
                           expires_in=_expires_in(r.geturl()))
                return pr, hdr, body
        except urllib.error.HTTPError as e:
            return Probe(False, e.code, f"HTTP {e.code}", redirects=red.count, chain=list(red.hosts), final_url=getattr(e, "url", "") or "",
                         signed=bool(SIGNED_RE.search(getattr(e, "url", "") or ""))), {}, b""
        except NetError as e:
            return Probe(False, error=str(e), redirects=red.count), {}, b""
        except (urllib.error.URLError, OSError) as e:
            return Probe(False, error=f"falha de rede: {getattr(e, 'reason', e)}", redirects=red.count), {}, b""


def load_hosts(path: Path | None = Path("config/resolver-hosts.json")) -> set[str]:
    try:
        return {h.lower() for h in json.loads(Path(path).read_text(encoding="utf-8")).get("hosts", [])}
    except (OSError, ValueError, TypeError):
        return set()


def load_tls_bad(path: Path = Path("config/sources.json")) -> dict:
    """Hosts com falha de TLS já observada no SSPI do usuário (a mesma lista que o robô usa para bloquear publicação)."""
    try:
        return dict(json.loads(Path(path).read_text(encoding="utf-8")).get("tls", {}).get("known_bad_hosts", {}))
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _filename(hdr: dict, final_url: str, input_url: str) -> str:
    cd = hdr.get("content-disposition", "")
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd, re.I) or re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if m:
        return unquote(m.group(1)).strip().rsplit("/", 1)[-1]
    for u in (final_url, input_url):
        base = unquote(urlsplit(u).path.rsplit("/", 1)[-1])
        if re.search(r"\.(pkg|rar|r\d{2,3}|7z|zip)$", base, re.I):
            return base
    return unquote(urlsplit(final_url or input_url).path.rsplit("/", 1)[-1])


_SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)</script>", re.I | re.S)
_WIDGET = re.compile(r"recaptcha|hcaptcha|turnstile|challenges\.cloudflare\.com|data-sitekey|g-recaptcha|h-captcha|cf-turnstile", re.I)


def _visible_markup(text: str) -> str:
    """Tira corpos de <script>/<style> e comentários (flags de configuração como 'octocaptcha_*' não são um CAPTCHA); mantém as tags
    <script src=...> e os atributos, onde widgets reais (recaptcha, hcaptcha, turnstile) aparecem."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = _SCRIPT.sub(lambda m: m.group(1) + "</script>", text)
    return re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)


def _interaction(html: bytes) -> list[str]:
    text = _visible_markup(html.decode("utf-8", "replace"))
    return [why for rx, why in INTERACTION if rx.search(text)]


def _page_links(html: str, base: str) -> list[dict]:
    """Links estáticos relevantes de uma página: arquivo (.pkg/.rar), 'pagina' (texto/URL de download) e meta refresh. `javascript:` vira kind 'js'."""
    out, seen = [], set()

    def add(href: str, text: str, kind: str):
        href = htmllib.unescape(href).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "data:")):
            return
        if href.lower().startswith("javascript:"):
            out.append({"url": "", "text": text[:60], "kind": "js"})
            return
        u = urldefrag(urljoin(base, href))[0]
        if urlsplit(u).scheme not in ("http", "https") or u in seen:
            return
        seen.add(u)
        out.append({"url": u, "text": text[:60], "kind": kind})

    for m in _META.finditer(html):
        add(m.group(1), "(meta refresh)", "meta-refresh")
    for href, inner in _ANCHOR.findall(html):
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if _LOGIN_PATH.search(urlsplit(href).path):
            add(href, text, "login")
        elif _FILE_HREF.search(urlsplit(href).path):
            add(href, text, "arquivo")
        elif _DL_HINT.search(href) or _DL_HINT.search(text):
            add(href, text, "pagina")
    return out


def resolve(url: str, net: ResolverNet | None = None, hosts: set[str] | None = None) -> Resolved:
    return _resolve(url, net, hosts)[0]


def _resolve(url: str, net: ResolverNet | None = None, hosts: set[str] | None = None) -> tuple[Resolved, bytes]:
    net = net or ResolverNet()
    hosts = load_hosts() if hosts is None else hosts
    host = (urlsplit(url).hostname or "").lower()
    if host not in hosts:
        return Resolved(url, HOST_NAO_PERMITIDO, f"{host or '?'} não está na lista de fontes permitidas (config/resolver-hosts.json ou --permitir)"), b""
    pr, hdr, body = net.fetch(url)
    r = Resolved(url, OK, finalUrl=pr.final_url, finalHost=(urlsplit(pr.final_url).hostname or "") if pr.final_url else "", chain=pr.chain)
    if not pr.ok:
        info = classify_link(pr)
        r.status, r.linkKind, r.detail = INACESSIVEL, info["kind"], "; ".join(info["notes"])
        return r, b""
    if (pr.content_type or "") in ("text/html", "application/xhtml+xml") and not any(body.startswith(m) for m, _ in MAGIC):
        html = body.decode("utf-8", "replace")
        why = _interaction(body)
        links = []
        for h in _HREF.findall(html):
            if _FILE_HREF.search(urlsplit(h).path) and h not in links:
                links.append(h)
        r.candidates = links[:50]
        r.links = _page_links(html, pr.final_url or url)
        static = [l for l in r.links if l["kind"] not in ("js", "login")]
        if why:
            r.status, r.detail = INTERACAO, "página exige " + ", ".join(why) + ": o resolvedor não tenta contornar; abra no navegador e cole o link final"
        elif links or static:
            r.status, r.detail = PAGINA_SEM_ARQUIVO, f"página HTML com {len(static)} link(s) estático(s) relevante(s)"
        else:
            soft = [w for rx, w in _SOFT if rx.search(html)]
            if any(l["kind"] == "js" for l in r.links):
                soft.append("link JavaScript (javascript:)")
            if any(l["kind"] == "login" for l in r.links):
                soft.append("link de login (o caminho para o arquivo passa por conta)")
            r.status = INTERACAO
            if not soft and re.search(r"<script\b[^>]+src=", html):
                soft.append("conteúdo montado por JavaScript (a página carrega scripts e não traz links no HTML)")
            r.detail = ("página sem link estático para PKG/RAR; há " + ", ".join(soft) + ": a continuação depende do navegador" if soft else
                        "página HTML sem link direto para PKG/RAR (pode depender de JavaScript ou de ação humana)")
        return r, body
    info = classify_link(pr)
    r.linkKind, r.rangeOk, r.sizeBytes, r.notes = info["kind"], pr.range_ok, pr.total_size, list(info["notes"])
    r.filename = _filename(hdr, pr.final_url, url)
    r.sspiUrl = url
    bad = load_tls_bad()
    in_host = (urlsplit(url).hostname or "").lower()
    if in_host in bad:
        fin = urlsplit(pr.final_url)
        if pr.final_url and (fin.hostname or "").lower() not in bad and not pr.signed:
            r.notes.append(f"{in_host} já falhou com TLS no SSPI; use a URL final estável de {fin.hostname}")
            r.sspiUrl = pr.final_url
        else:
            r.notes.append(f"ATENÇÃO: {in_host} já falhou com TLS no SSPI e não há URL final estável em outro host")
    by_name = file_type(r.filename)
    by_bytes = next((t for m, t in MAGIC if pr.head.startswith(m)), "")
    r.formatConfirmedByBytes = bool(by_bytes)
    if by_bytes and by_name not in ("desconhecido", by_bytes) and not (by_bytes == "rar" and by_name == "rar-multiparte"):
        r.notes.append(f"o nome sugere {by_name}, mas os bytes são {by_bytes}: vale a assinatura")
    fmt = by_bytes or by_name
    if fmt == "rar" and multipart_info(r.filename):
        fmt = "rar-multiparte"
    r.format = fmt or "desconhecido"
    if r.format == "desconhecido":                     # 200 sem assinatura de arquivo e sem extensão: ex.: JSON de erro do servidor
        snippet = re.sub(r"\s+", " ", pr.head[:200].decode("utf-8", "replace")).strip()
        r.status = NAO_E_ARQUIVO
        r.detail = f"a URL devolve {pr.content_type or 'conteúdo'} ({pr.total_size or len(pr.head)} bytes) e não um PKG/RAR: {snippet[:120]!r}"
        r.sspiUrl = ""
        return r, b""
    r.volume = multipart_info(r.filename) if r.format == "rar-multiparte" else None
    if r.format not in ("pkg", "rar", "rar-multiparte"):
        r.status = FORMATO
        r.detail = f"formato {r.format}: só PKG e RAR são enviados ao SSPI nesta etapa"
        return r, b""
    r.sspiSendable = bool(info["sspiUsable"])
    if not r.sspiSendable:
        r.detail = "; ".join(info["notes"]) or "link não utilizável pelo baixador do SSPI"
    return r, b""


ARQUIVOS, SEM_ARQUIVOS = "ARQUIVOS_ENCONTRADOS", "SEM_ARQUIVOS"


@dataclass
class Crawl:
    inputUrl: str
    status: str = SEM_ARQUIVOS
    explanation: str = ""
    files: list = field(default_factory=list)         # Resolved OK (PKG/RAR) na ordem em que apareceram
    terminal: list = field(default_factory=list)      # todo desfecho final (arquivos, interação, falhas, páginas não expandidas)
    interactions: list = field(default_factory=list)  # [{url, reason}] o que precisa continuar no navegador
    pages: list = field(default_factory=list)         # [{url, depth, links}] páginas intermediárias seguidas
    skipped: list = field(default_factory=list)       # [{url, reason}] o que NÃO foi seguido e por quê
    requests: int = 0

    @property
    def truncated(self) -> bool:
        """A busca parou por limite de páginas/requisições/links: pode haver mais arquivos (ex.: volumes RAR) fora do resultado."""
        return any(re.match(r"limite de \d+ (páginas|requisições)|\d+ link\(s\) além do limite", sk["reason"]) for sk in self.skipped)


def crawl(url: str, net: ResolverNet | None = None, hosts: set[str] | None = None, *, max_depth: int = 2, max_pages: int = 10,
          max_requests: int = 40, max_links: int = 30) -> Crawl:
    """Segue links ESTÁTICOS de uma página (largura primeiro) até achar PKG/RAR. Profundidade, páginas, links e requisições têm teto;
    URLs repetidas (inclusive depois de redirects) não são visitadas de novo; host fora da lista não recebe requisição.
    CAPTCHA/JavaScript/login/botão não são contornados: viram INTERACAO_NECESSARIA com o motivo."""
    net = net or ResolverNet()
    hosts = load_hosts() if hosts is None else hosts
    out = Crawl(url)
    seen = {urldefrag(url)[0]}
    queue = deque([(url, 0, "")])
    js_pages: list[str] = []
    login_pages: list[str] = []
    while queue:
        cur, depth, parent = queue.popleft()
        host = (urlsplit(cur).hostname or "").lower()
        if host not in hosts:
            r = Resolved(cur, HOST_NAO_PERMITIDO, f"{host or '?'} não permitido")
            out.skipped.append({"url": cur, "reason": f"host {host or '?'} fora da lista de fontes permitidas"})
            if depth == 0:
                out.terminal.append(r)
            continue
        if out.requests >= max_requests:
            out.skipped.append({"url": cur, "reason": f"limite de {max_requests} requisições"})
            continue
        out.requests += 1
        r, _ = _resolve(cur, net, hosts)
        if r.finalUrl:
            seen.add(urldefrag(r.finalUrl)[0])
        if r.status == PAGINA_SEM_ARQUIVO:
            if depth >= max_depth:
                out.skipped.append({"url": cur, "reason": f"página não expandida: limite de profundidade {max_depth}"})
                out.terminal.append(r)
                continue
            if len(out.pages) >= max_pages:
                out.skipped.append({"url": cur, "reason": f"limite de {max_pages} páginas"})
                continue
            follow = [l for l in r.links if l["kind"] not in ("js", "login")]
            out.pages.append({"url": cur, "depth": depth, "links": len(follow)})
            if any(l["kind"] == "js" for l in r.links):
                js_pages.append(cur)
            for l in [l for l in r.links if l["kind"] == "login"]:
                if not any(sk["reason"].startswith("link de login") for sk in out.skipped):       # um aviso basta (páginas repetem o cabeçalho)
                    out.skipped.append({"url": l["url"], "reason": "link de login (exige conta): não seguido; há outros iguais"})
                login_pages.append(cur)
            for l in follow[:max_links]:
                u = urldefrag(l["url"])[0]
                if u in seen:
                    out.skipped.append({"url": u, "reason": "já visitado (loop ou link repetido)"})
                    continue
                seen.add(u)
                queue.append((u, depth + 1, cur))
            extra = len(follow) - max_links
            if extra > 0:
                out.skipped.append({"url": cur, "reason": f"{extra} link(s) além do limite de {max_links} por página"})
            continue
        out.terminal.append(r)
        if r.status == OK:
            if all(f.sspiUrl != r.sspiUrl for f in out.files):
                out.files.append(r)
        elif r.status == INTERACAO:
            out.interactions.append({"url": cur, "reason": r.detail})
    if not out.interactions and js_pages and not out.files:
        out.interactions.append({"url": js_pages[0], "reason": "a página só oferece links/botões JavaScript (sem URL estática)"})
    if login_pages and not out.files and not out.interactions:
        out.interactions.append({"url": login_pages[0], "reason": "o caminho para o arquivo passa por login: o resolvedor não autentica"})
    if out.files:
        out.status = ARQUIVOS
        n = len(out.files)
        out.explanation = f"{n} arquivo(s) encontrado(s)" + (f"; {len(out.interactions)} ponto(s) exigem o navegador" if out.interactions else "")
    elif out.interactions:
        out.status = INTERACAO
        out.explanation = "; ".join(i["reason"] for i in out.interactions)
    elif len(out.terminal) == 1 and out.terminal[0].status != PAGINA_SEM_ARQUIVO:
        out.status, out.explanation = out.terminal[0].status, out.terminal[0].detail
    else:
        out.status = SEM_ARQUIVOS
        out.explanation = "nenhum PKG/RAR alcançado: " + ("; ".join(sorted({s_["reason"] for s_ in out.skipped})) or "as páginas não têm links estáticos")
    return out


def group_sets(items: list[Resolved], truncated: bool = False) -> list[dict]:
    """Agrupa volumes RAR por conjunto, em ordem; informa o que falta/duplica. Preserva a ordem de entrada dos PKG avulsos."""
    sets: dict[str, list[Resolved]] = {}
    for it in items:
        if it.format == "rar-multiparte" and it.volume and it.status == OK:
            sets.setdefault(it.volume["set"], []).append(it)
    out = []
    for name, vols in sets.items():
        style = vols[0].volume["style"]
        if style == "part-rar":
            vols = sorted(vols, key=lambda v: v.volume["index"])
            idx = [v.volume["index"] for v in vols]
            lo = min(idx)
            missing = [i for i in range(lo, max(idx) + 1) if i not in idx]
            dup = sorted({i for i in idx if idx.count(i) > 1})
            starts = lo in (0, 1)
            problems = ([f"falta(m) o(s) volume(s) {missing}"] if missing else []) + ([f"volume(s) repetido(s) {dup}"] if dup else []) + \
                       ([] if starts else [f"o conjunto começa em {lo}, não em 1"])
        else:
            vols = sorted(vols, key=lambda v: (v.filename.lower().endswith(".rar") is False, v.filename.lower()))
            problems = [] if vols[0].filename.lower().endswith(".rar") else ["falta o volume principal (.rar)"]
            problems.append("estilo antigo (.rar + .r00…): a contagem de volumes não é verificável; confira no SSPI")
        if truncated:
            problems.append("a busca foi truncada por limite (páginas/requisições): podem existir mais volumes; aumente --max-paginas/--max-requisicoes")
        out.append({"set": name, "style": style, "volumes": len(vols), "complete": not [p for p in problems if "não é verificável" not in p],
                    "problems": problems, "totalBytes": sum(v.sizeBytes or 0 for v in vols),
                    "sspiOrder": [v.sspiUrl for v in vols], "markMultipartInSspi": style != "part-rar"})
    return out


def _line(r: Resolved) -> None:
    if r.status == OK:
        mb = f"{r.sizeBytes / 1e6:.1f} MB" if r.sizeBytes else "tamanho ?"
        vol = f" · volume {r.volume['index']}" if r.volume and r.volume["index"] is not None else ""
        print(f"OK  {r.filename} · {r.format}{vol} · {mb} · host final {r.finalHost} · {r.linkKind} · "
              f"{'enviável ao SSPI' if r.sspiSendable else 'NÃO utilizável pelo SSPI'}\n    colar no SSPI: {r.sspiUrl}")
    else:
        print(f"{r.status}  {r.inputUrl}\n    {r.detail}")
    for n in r.notes:
        print(f"    - {n}")


def main(argv=None, net: ResolverNet | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ps4store resolve", description="resolve URLs (arquivo direto, redirect ou página com links estáticos) até PKG/RAR, sem baixar")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--arquivo", help="arquivo com uma URL por linha")
    ap.add_argument("--permitir", action="append", default=[], metavar="HOST", help="host de entrada extra permitido (repetível)")
    ap.add_argument("--hosts", default="config/resolver-hosts.json")
    ap.add_argument("--profundidade", type=int, default=2, help="níveis de páginas a seguir a partir da URL (padrão 2; 0 = não seguir)")
    ap.add_argument("--max-paginas", type=int, default=10)
    ap.add_argument("--max-requisicoes", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    urls = list(a.urls)
    if a.arquivo:
        urls += [ln.strip() for ln in Path(a.arquivo).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    if not urls:
        ap.error("informe URLs ou --arquivo")
    hosts = load_hosts(Path(a.hosts)) | {h.lower() for h in a.permitir}
    net = net or ResolverNet()
    crawls = [crawl(u, net, hosts, max_depth=max(0, a.profundidade), max_pages=a.max_paginas, max_requests=a.max_requisicoes) for u in urls]
    terminal = [r for c in crawls for r in c.terminal]
    groups = group_sets([f for c in crawls for f in c.files], any(c.truncated for c in crawls))
    if a.json:
        print(json.dumps({"results": [asdict(r) for r in terminal], "sets": groups,
                          "crawls": [{"inputUrl": c.inputUrl, "status": c.status, "truncated": c.truncated, "explanation": c.explanation, "requests": c.requests,
                                      "pages": c.pages, "skipped": c.skipped, "interactions": c.interactions} for c in crawls]},
                         ensure_ascii=False, indent=1))
        return 0
    for c in crawls:
        multi = len(c.terminal) > 1 or c.pages
        if multi:
            print(f"== {c.inputUrl}: {c.status} · {c.explanation} · {len(c.pages)} página(s), {c.requests} requisição(ões)")
        for r in c.terminal:
            _line(r)
        for sk in c.skipped[:6]:
            print(f"    ignorado: {sk['url'][:110]} ({sk['reason']})")
        if len(c.skipped) > 6:
            print(f"    ... e mais {len(c.skipped) - 6} ignorado(s) (use --json para a lista completa)")
    for g in groups:
        print(f"RAR {g['set']}: {g['volumes']} volume(s), {g['totalBytes'] / 1e6:.1f} MB, " + ("completo" if g["complete"] else "INCOMPLETO"))
        for p in g["problems"]:
            print(f"    - {p}")
        print("    ordem para colar no SSPI" + (" (marque 'parts of one RAR archive')" if g["markMultipartInSspi"] else "") + ":")
        for u in g["sspiOrder"]:
            print(f"      {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
