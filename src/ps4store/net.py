"""Rede mínima e segura para o Gate 3 (stdlib): JSON da API e sondagem leve de links com Range.

Nunca baixa o pacote inteiro: lê no máximo `nbytes` do corpo e fecha a conexão. Só HTTPS (salvo `allow_insecure`, uso em teste),
≤ 5 redirects, sem enviar o token da API a outros hosts, e sem IP literal privado/loopback.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

UA = "ps4store-discovery/0.1"
_EXP_RE = re.compile(r"[?&](?:exp|expires)=(\d{9,11})(?:&|$)", re.I)
SIGNED_RE = re.compile(r"[?&](exp|expires|expiry|sig|signature|token|x-amz-signature|x-goog-signature|se)=", re.I)
MAX_JSON = 2 * 1024 * 1024
MAX_REDIRECTS = 5


def _expires_in(url: str) -> int | None:
    m = _EXP_RE.search(url)
    return int(m.group(1)) - int(time.time()) if m else None


class NetError(Exception):
    pass


@dataclass
class Probe:
    ok: bool
    status: int | None = None
    error: str | None = None
    total_size: int | None = None
    head: bytes = b""
    final_url: str = ""
    content_type: str | None = None
    redirects: int = 0
    range_ok: bool = False              # 206 com Content-Range (o SSPI baixa em faixas paralelas)
    content_encoding: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    chain: list = field(default_factory=list)   # hosts percorridos (origem → ... → final)
    signed: bool = False                # URL final com assinatura/expiração (temporária)
    range_start: int | None = None      # Content-Range: início devolvido (conferir se o servidor honrou o offset pedido)
    range_end: int | None = None
    expires_in: int | None = None       # segundos até a URL assinada expirar (parâmetro exp/expires numérico), se houver


def _host_blocked(host: str) -> str | None:
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)]
        except OSError:
            return None          # sem DNS local (ex.: via proxy): deixa a requisição decidir
    for ip in ips:
        if not ip.is_global:
            return f"host {host} resolve para endereço não público ({ip})"
    return None


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self, net: "UrllibNet"):
        self.net = net
        self.count = 0
        self.hosts: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > MAX_REDIRECTS:
            raise NetError("redirects demais")
        self.net._check_url(newurl)
        self.hosts.append(urlsplit(newurl).hostname or "")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibNet:
    def __init__(self, *, timeout: float = 15, allow_insecure: bool = False, token: str | None = None):
        self.timeout, self.allow_insecure, self.token = timeout, allow_insecure, token

    def _check_url(self, url: str) -> None:
        p = urlsplit(url)
        if p.scheme != "https" and not (self.allow_insecure and p.scheme == "http"):
            raise NetError(f"esquema não permitido: {p.scheme or '?'}")
        if not p.hostname or p.username or p.password:
            raise NetError("URL inválida ou com credenciais")
        if not self.allow_insecure:
            why = _host_blocked(p.hostname)
            if why:
                raise NetError(why)

    def get_json(self, url: str):
        self._check_url(url)
        h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
        if self.token and urlsplit(url).hostname == "api.github.com":
            h["Authorization"] = f"Bearer {self.token}"       # token só para a API, nunca para redirects/downloads
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=self.timeout) as r:
                body = r.read(MAX_JSON + 1)
        except urllib.error.HTTPError as e:
            raise NetError(f"HTTP {e.code} em {urlsplit(url).netloc}")
        except (urllib.error.URLError, OSError) as e:
            raise NetError(f"falha de rede: {getattr(e, 'reason', e)}")
        if len(body) > MAX_JSON:
            raise NetError("resposta JSON maior que 2 MiB")
        try:
            return json.loads(body)
        except ValueError:
            raise NetError("resposta não é JSON")

    def probe(self, url: str, nbytes: int = 65536, start: int = 0) -> Probe:
        try:
            self._check_url(url)
        except NetError as e:
            return Probe(False, error=str(e))
        redirects = _Redirects(self)
        opener = urllib.request.build_opener(redirects)
        redirects.hosts.append(urlsplit(url).hostname or "")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={start}-{start + nbytes - 1}",
                                                   "Accept-Encoding": "identity"})
        try:
            with opener.open(req, timeout=self.timeout) as r:
                status = r.status
                head = r.read(nbytes)                        # no máximo nbytes; o resto nunca é lido
                total = None
                cr = r.headers.get("Content-Range")
                m = re.match(r"bytes (\d+)-(\d+)/(\d+)$", cr or "")
                rs = re_ = None
                if m:
                    rs, re_, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif status == 200 and (r.headers.get("Content-Length") or "").isdigit():
                    total = int(r.headers["Content-Length"])
                return Probe(status in (200, 206), status, None if status in (200, 206) else f"HTTP {status}",
                             total, head, r.geturl(), r.headers.get_content_type(), redirects.count,
                             range_ok=status == 206 and bool(m), content_encoding=r.headers.get("Content-Encoding"),
                             etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"),
                             chain=list(redirects.hosts), signed=bool(SIGNED_RE.search(r.geturl())),
                             range_start=rs, range_end=re_, expires_in=_expires_in(r.geturl()))
        except urllib.error.HTTPError as e:
            return Probe(False, e.code, f"HTTP {e.code}", redirects=redirects.count, chain=list(redirects.hosts),
                         final_url=getattr(e, "url", "") or "", signed=bool(SIGNED_RE.search(getattr(e, "url", "") or "")))
        except NetError as e:
            return Probe(False, error=str(e), redirects=redirects.count)
        except (urllib.error.URLError, OSError) as e:
            return Probe(False, error=f"falha de rede: {getattr(e, 'reason', e)}", redirects=redirects.count)
