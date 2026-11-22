"""RESOLVER: de uma URL (ou de várias) até o arquivo final, sem baixar nada além dos primeiros 64 KiB.

Segue redirects HTTP comuns (mesmas regras de segurança do robô), identifica host final, nome, tamanho informado e formato
(PKG/RAR, confirmado pela assinatura dos bytes), e agrupa volumes `.partNN.rar` preservando a ordem. Páginas HTML que exigem
JavaScript, CAPTCHA, login ou espera NÃO são contornadas: viram INTERACAO_NECESSARIA. Não executa nada, não grava arquivos,
não altera o catálogo; só LÊ (reaproveita net.py e links.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .links import classify_link, file_type, multipart_info
from .net import SIGNED_RE, UA, NetError, Probe, UrllibNet, _expires_in, _Redirects

MAX_HTML = 256 * 1024
MAGIC = ((b"\x7fCNT", "pkg"), (b"Rar!\x1a\x07\x00", "rar"), (b"Rar!\x1a\x07\x01\x00", "rar"), (b"7z\xbc\xaf\x27\x1c", "7z"), (b"PK\x03\x04", "zip"))
INTERACTION = [
    (re.compile(r"captcha|hcaptcha|recaptcha|turnstile|cf-challenge|g-recaptcha", re.I), "CAPTCHA"),
    (re.compile(r"enable javascript|requires javascript|please turn on javascript|<noscript[^>]*>[^<]{10,}", re.I), "exige JavaScript"),
    (re.compile(r"just a moment|checking your browser|verify you are human|are you a robot", re.I), "verificação anti-robô"),
    (re.compile(r"type=[\"']?password|log ?in to download|sign ?in to download|faça login", re.I), "exige login"),
    (re.compile(r"please wait \d+ ?(?:s|sec|seconds)|wait \d+ seconds|countdown", re.I), "espera/contagem obrigatória"),
]
_HREF = re.compile(r"""<a\s[^>]*href=["']([^"']+)["']""", re.I)
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


def _interaction(html: bytes) -> list[str]:
    text = html.decode("utf-8", "replace")
    return [why for rx, why in INTERACTION if rx.search(text)]


def resolve(url: str, net: ResolverNet | None = None, hosts: set[str] | None = None) -> Resolved:
    net = net or ResolverNet()
    hosts = load_hosts() if hosts is None else hosts
    host = (urlsplit(url).hostname or "").lower()
    if host not in hosts:
        return Resolved(url, HOST_NAO_PERMITIDO, f"{host or '?'} não está na lista de fontes permitidas (config/resolver-hosts.json ou --permitir)")
    pr, hdr, body = net.fetch(url)
    r = Resolved(url, OK, finalUrl=pr.final_url, finalHost=(urlsplit(pr.final_url).hostname or "") if pr.final_url else "", chain=pr.chain)
    if not pr.ok:
        info = classify_link(pr)
        r.status, r.linkKind, r.detail = INACESSIVEL, info["kind"], "; ".join(info["notes"])
        return r
    if (pr.content_type or "").startswith("text/") and not any(body.startswith(m) for m, _ in MAGIC):
        why = _interaction(body)
        links = []
        for h in _HREF.findall(body.decode("utf-8", "replace")):
            if re.search(r"\.(pkg|rar|r\d{2,3})(\?|$)", h, re.I) and h not in links:
                links.append(h)
        r.candidates = links[:50]
        if why:
            r.status, r.detail = INTERACAO, "página exige " + ", ".join(why) + ": o resolvedor não tenta contornar; abra no navegador e cole o link final"
        elif links:
            r.status, r.detail = PAGINA_SEM_ARQUIVO, f"página HTML com {len(links)} link(s) estático(s) para PKG/RAR (não seguidos nesta etapa)"
        else:
            r.status, r.detail = INTERACAO, "página HTML sem link direto para PKG/RAR (pode depender de JavaScript ou de ação humana)"
        return r
    info = classify_link(pr)
    r.linkKind, r.rangeOk, r.sizeBytes, r.notes = info["kind"], pr.range_ok, pr.total_size, list(info["notes"])
    r.filename = _filename(hdr, pr.final_url, url)
    r.sspiUrl = url
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
        return r
    r.volume = multipart_info(r.filename) if r.format == "rar-multiparte" else None
    if r.format not in ("pkg", "rar", "rar-multiparte"):
        r.status = FORMATO
        r.detail = f"formato {r.format}: só PKG e RAR são enviados ao SSPI nesta etapa"
        return r
    r.sspiSendable = bool(info["sspiUsable"])
    if not r.sspiSendable:
        r.detail = "; ".join(info["notes"]) or "link não utilizável pelo baixador do SSPI"
    return r


def group_sets(items: list[Resolved]) -> list[dict]:
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
        out.append({"set": name, "style": style, "volumes": len(vols), "complete": not [p for p in problems if "não é verificável" not in p],
                    "problems": problems, "totalBytes": sum(v.sizeBytes or 0 for v in vols),
                    "sspiOrder": [v.sspiUrl for v in vols], "markMultipartInSspi": style != "part-rar"})
    return out


def main(argv=None, net: ResolverNet | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ps4store resolve", description="resolve URLs até o arquivo final (sem baixar) e agrupa volumes RAR")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--arquivo", help="arquivo com uma URL por linha")
    ap.add_argument("--permitir", action="append", default=[], metavar="HOST", help="host de entrada extra permitido (repetível)")
    ap.add_argument("--hosts", default="config/resolver-hosts.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    urls = list(a.urls)
    if a.arquivo:
        urls += [ln.strip() for ln in Path(a.arquivo).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    if not urls:
        ap.error("informe URLs ou --arquivo")
    hosts = load_hosts(Path(a.hosts)) | {h.lower() for h in a.permitir}
    net = net or ResolverNet()
    res = [resolve(u, net, hosts) for u in urls]
    groups = group_sets(res)
    if a.json:
        print(json.dumps({"results": [asdict(r) for r in res], "sets": groups}, ensure_ascii=False, indent=1))
        return 0
    for r in res:
        if r.status == OK:
            mb = f"{r.sizeBytes / 1e6:.1f} MB" if r.sizeBytes else "tamanho ?"
            vol = f" · volume {r.volume['index']}" if r.volume and r.volume["index"] is not None else ""
            print(f"OK  {r.filename} · {r.format}{vol} · {mb} · host final {r.finalHost} · {r.linkKind} · "
                  f"{'enviável ao SSPI' if r.sspiSendable else 'NÃO utilizável pelo SSPI'}")
        else:
            print(f"{r.status}  {r.inputUrl}\n    {r.detail}")
        for n in r.notes:
            print(f"    - {n}")
    for g in groups:
        print(f"RAR {g['set']}: {g['volumes']} volume(s), {g['totalBytes'] / 1e6:.1f} MB, " + ("completo" if g["complete"] else "INCOMPLETO"))
        for p in g["problems"]:
            print(f"    - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
