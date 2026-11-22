"""3. PUBLICATION: o que pode ser OFERECIDO. Separado da descoberta e da validação do link.

Duas perguntas independentes, ambas sobre entradas já identificadas:
  - COMPATIBILIDADE com o SSPI (técnica): prefixo de ID aceito pelo importador, tipo base, placeholder, HTTPS. Lista TODOS os motivos.
  - DISPONIBILIDADE: (a) CATÁLOGO público/compartilhado: compatível + autorização registrada + host com TLS ok + sem aparência comercial;
    (b) INSTALAÇÃO por link direto (lista pessoal, local): link utilizável + identidade verificada + sem aparência comercial + host ok.
Descobrir uma URL ou ela estar acessível NÃO é autorização de uso ou distribuição. Licença desconhecida (LICENSE_UNKNOWN) não elimina nada da
pesquisa; apenas não autoriza. Autorização vem da configuração (fonte ou item), nunca é presumida.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import sspi
from .model import Config, Entry


def _compat_detail(e: Entry, code: str) -> str:
    t = e.title_id or ""
    return {"ID_FORMAT": f"{t} fora do padrão aceito pelo SSPI",
            "PREFIX_REJECTED_BY_SSPI": f"prefixo {t[:4]} recusado na importação (Gate 2)",
            "PREFIX_UNPROVEN": f"prefixo {t[:4]} não comprovado no console",
            "PLACEHOLDER_ID": f"{t} é ID fictício",
            "KIND_UNTESTED": f"tipo '{e.kind}': só 'base' é publicado; update/DLC não testados",
            "NOT_HTTPS": "URL não é HTTPS"}[code]


def assess_compat(e: Entry) -> list[str]:
    """Motivos técnicos de incompatibilidade com o importador/instalador do SSPI (todos, na ordem de gravidade)."""
    t = e.title_id or ""
    out: list[str] = []
    if not sspi.TITLE_ID_RE.match(t):
        out.append("ID_FORMAT")
    elif t.startswith(sspi.CONSOLE_REJECTED_PREFIXES):
        out.append("PREFIX_REJECTED_BY_SSPI")
    elif not t.startswith(sspi.CONSOLE_PROVEN_PREFIXES):
        out.append("PREFIX_UNPROVEN")
    if sspi.is_placeholder_id(t):
        out.append("PLACEHOLDER_ID")
    if e.kind != "base":
        out.append("KIND_UNTESTED")
    if not e.found.url.startswith("https://"):
        out.append("NOT_HTTPS")
    return out


def assess(e: Entry, cfg: Config) -> Entry:
    """Reavalia COMPATIBILIDADE e POLÍTICA de publicação sobre uma entrada com identidade verificada. Idempotente (serve ao cache)."""
    e.stage, e.reason, e.detail = "pkg_verificado", None, ""
    e.compat = assess_compat(e)
    src = e.found.source
    host = urlsplit(e.found.url).hostname or ""
    bl: list[str] = []
    if e.restricted and src.authorized_titles.get(e.title_id) is None:
        bl.append("RETAIL_STYLE_ID")
    if cfg.tls_enforce and host in cfg.tls_known_bad:
        bl.append("TLS_HOST_BLOCKED")
    if src.auth_for(e.title_id) is None:
        bl.append("NO_AUTHORIZATION")
    e.blockers = bl
    if e.compat:                                              # motivo "principal" = o mais grave (compatibilidade vem primeiro)
        return e.reject(e.compat[0], _compat_detail(e, e.compat[0]))
    e.stage = "compativel_sspi"
    if "RETAIL_STYLE_ID" in bl:
        cat = e.found.meta.get("category")
        return e.reject("RETAIL_STYLE_ID", f"Content ID {e.content_id}" + (f" / categoria '{cat}'" if cat else "")
                        + " tem aparência de conteúdo comercial: fica só na pesquisa; só entra em catálogo com autorização POR ITEM")
    if "TLS_HOST_BLOCKED" in bl:
        return e.reject("TLS_HOST_BLOCKED", f"{host}: {cfg.tls_known_bad[host]}")
    if host in cfg.tls_untested and "TLS não confirmado no SSPI" not in " ".join(e.warnings):
        e.warnings.append(f"{host}: TLS não confirmado no SSPI ({cfg.tls_untested[host]})")
    if "NO_AUTHORIZATION" in bl:
        return e.reject("NO_AUTHORIZATION", f"nem a fonte '{src.id}' nem o título {e.title_id} têm autorização de listagem registrada (config/sources.json)")
    e.stage = "publicado"
    return e


def assess_install(e: Entry, cfg: Config) -> list[str]:
    """Impeditivos para oferecer o item por DOWNLOAD DIRETO (lista pessoal). Independe do prefixo do ID e da autorização de catálogo."""
    bl: list[str] = []
    if not e.title_id:
        bl.append("NOT_IDENTIFIED")
    elif e.kind != "base":
        bl.append("KIND_NOT_BASE")
    if not e.link.get("sspiUsable"):
        bl.append("LINK_NOT_USABLE")
    if e.restricted:
        bl.append("RETAIL_STYLE_ID")
    host = urlsplit(e.found.url).hostname or ""
    if cfg.tls_enforce and host in cfg.tls_known_bad:
        bl.append("TLS_HOST_BLOCKED")
    if e.reason == "SUPERSEDED":
        bl.append("SUPERSEDED")
    if e.duplicate_of:
        bl.append("DUPLICATE")
    return bl


def personal_links(entries: list[Entry], cfg: Config | None = None) -> list[Entry]:
    """Lista PESSOAL para colar no SSPI (Downloads → colar link). Nunca é commitada nem hospedada."""
    out = []
    for e in entries:
        if cfg is not None:
            e.install_blockers = assess_install(e, cfg)
            e.install_ok = not e.install_blockers
        if e.install_ok:
            out.append(e)
    return out


def _vkey(v: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)




def dedupe_latest(published: list[Entry]) -> list[Entry]:
    """Um pacote por (título, tipo): vence a maior versão (empate: o mais novo; depois a chave). Os demais ficam VERIFICADOS
    com motivo SUPERSEDED, evitando duplicar o mesmo identificador no catálogo instalável."""
    best: dict[tuple, Entry] = {}
    for e in published:
        k = (e.title_id, e.kind)
        cur = best.get(k)
        rank = lambda x: (_vkey(x.version), x.found.published_at, x.found.key)
        if cur is None or rank(e) > rank(cur):
            best[k] = e
    keep = set(id(e) for e in best.values())
    for e in published:
        if id(e) not in keep:
            w = best[(e.title_id, e.kind)]
            e.stage = "compativel_sspi"
            e.blockers = [b for b in e.blockers if b != "SUPERSEDED"] + ["SUPERSEDED"]
            e.reject("SUPERSEDED", f"{e.title_id}: versão {w.version} ({w.found.asset_name}) é mais nova; só uma versão por ID entra no catálogo")
    return [e for e in published if id(e) in keep]




def _row_id(e: Entry) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", f"{e.found.source.id}-{e.found.tag}-{e.found.asset_name}")[:200]




def build_canonical(cfg: Config, published: list[Entry], version: str) -> dict:
    titles: dict[str, dict] = {}
    for e in sorted(published, key=lambda x: (x.title_id, x.found.published_at, x.found.key)):
        f = e.found
        t = titles.setdefault(e.title_id, {
            "titleId": e.title_id,
            "identityEvidence": f"Lido do proprio PKG ({f.url}): Content ID {e.content_id}, param.sfo TITLE_ID {e.title_id}.",
            "name": (e.name or e.title_id)[:200], "region": None,
            "aliases": [], "languages": {"audioPtBr": "unknown", "subtitlesPtBr": "unknown", "evidence": None},
            "packages": []})
        t["name"] = (e.name or t["name"])[:200]           # o mais recente (ordenação crescente por data)
        stem = re.sub(r"\.pkg$", "", f.asset_name, flags=re.I)
        if stem not in t["aliases"]:
            t["aliases"].append(stem)
        ver = e.version if e.version and sspi.VERSION_RE.match(e.version) else None
        t["packages"].append({
            "id": _row_id(e), "kind": "base", "accessType": "Direct", "url": f.url,
            "hoster": (urlsplit(f.url).hostname or "")[:200], "label": f"{f.source.id} {f.tag}".strip()[:200],
            "sourcePageUrl": f.release_url or None, "version": ver, "contentId": e.content_id, "size": e.total_size,
            "authorization": dict(zip(("basis", "evidence"), f.source.auth_for(e.title_id)))})
    return {"schema": "ps4storebr.catalog/v1",
            "source": {"id": cfg.catalog_id, "name": cfg.catalog_name, "description": cfg.catalog_description[:500],
                       "version": version},
            "titles": list(titles.values())}

