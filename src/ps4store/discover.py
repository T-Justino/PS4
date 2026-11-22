"""Gate 3 (MVP): descobre pacotes em fontes AUTORIZADAS, verifica os links com requisições leves e gera o catálogo.

Fluxo (um comando: `python -m ps4store run`):
  fonte (allowlist) → feed/API de releases → [descoberto] → Range nos primeiros 64 KiB → [acessível]
  → cabeçalho + param.sfo do PKG → [pkg verificado] → regras do SSPI → [compatível] → autorização + TLS → [publicado]
Só entram no catálogo instalável as entradas que chegam ao fim. As demais ficam no relatório, com o motivo.
Sem banco de dados: estado em um JSON versionável. Não baixa pacotes completos e não faz crawl genérico.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import sspi
from .build import compile_catalog, write_atomic, zip_files
from .catalog import AUTH_BASES, CatalogError, parse
from .pkginfo import PkgError, parse_head

SOURCES_SCHEMA = "ps4storebr.sources/v1"
STATE_SCHEMA = "ps4storebr.discovery-state/v1"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
STAGES = ("descoberto", "acessivel", "pkg_verificado", "compativel_sspi", "publicado")
MAX_ASSETS_PER_SOURCE = 100
HEAD_BYTES = 65536


class ConfigError(ValueError):
    pass


# --------------------------------------------------------------------------- configuração

@dataclass
class Source:
    id: str
    type: str
    repo: str
    enabled: bool
    include_prereleases: bool
    max_releases: int
    auth_basis: str
    auth_evidence: str
    api_base: str = "https://api.github.com"


@dataclass
class Config:
    catalog_id: str
    catalog_name: str
    catalog_description: str
    tls_enforce: bool
    tls_known_bad: dict
    sources: list[Source]


def load_config(path: str | Path) -> Config:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"config ilegível: {e}")
    errs: list[str] = []
    if doc.get("schema") != SOURCES_SCHEMA:
        errs.append(f"schema deve ser {SOURCES_SCHEMA}")
    cat = doc.get("catalog") or {}
    for k in ("id", "name"):
        if not cat.get(k):
            errs.append(f"catalog.{k} obrigatório")
    tls = doc.get("tls") or {}
    srcs: list[Source] = []
    seen: set[str] = set()
    for i, s in enumerate(doc.get("sources") or []):
        w = f"sources[{i}]"
        sid = s.get("id") or ""
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", sid) or sid in seen:
            errs.append(f"{w}: id inválido ou duplicado")
        seen.add(sid)
        if s.get("type") != "github-releases":
            errs.append(f"{w}: type deve ser github-releases")
        if not REPO_RE.match(s.get("repo") or ""):
            errs.append(f"{w}: repo deve ser dono/nome")
        a = s.get("authorization") or {}
        if a.get("basis") not in AUTH_BASES or not a.get("evidence"):
            errs.append(f"{w}: authorization.basis ∈ {AUTH_BASES} e evidence são obrigatórios (sem autorização, a fonte não entra)")
        srcs.append(Source(sid, s.get("type", ""), s.get("repo", ""), s.get("enabled", True) is True,
                           s.get("include_prereleases") is True, int(s.get("max_releases", 20)),
                           a.get("basis", ""), a.get("evidence", ""), s.get("api_base", "https://api.github.com")))
    if not srcs:
        errs.append("nenhuma fonte configurada")
    if errs:
        raise ConfigError("\n".join(errs))
    return Config(cat["id"], cat["name"], cat.get("description", ""), tls.get("enforce", True) is True,
                  dict(tls.get("known_bad_hosts") or {}), srcs)


# --------------------------------------------------------------------------- descoberta (conector)

@dataclass
class Found:
    key: str                 # estável: fonte + id da release + id do asset
    source: Source
    tag: str
    release_url: str
    published_at: str
    asset_name: str
    url: str
    size: int | None


def discover_github(src: Source, net) -> list[Found]:
    """Lista os assets .pkg das últimas releases da API pública de Releases do GitHub (nada é cadastrado URL a URL)."""
    releases = net.get_json(f"{src.api_base}/repos/{src.repo}/releases?per_page={min(max(src.max_releases, 1), 100)}")
    if not isinstance(releases, list):
        raise ValueError("resposta inesperada da API de releases")
    found: list[Found] = []
    for rel in releases[:src.max_releases]:
        if not isinstance(rel, dict) or rel.get("draft") or (rel.get("prerelease") and not src.include_prereleases):
            continue
        for a in rel.get("assets") or []:
            name, url = a.get("name"), a.get("browser_download_url")
            if not (isinstance(name, str) and isinstance(url, str) and name.lower().endswith(".pkg")):
                continue
            if a.get("state") not in (None, "uploaded"):
                continue
            size = a.get("size")
            found.append(Found(f"{src.id}#{rel.get('id')}#{a.get('id')}", src, str(rel.get("tag_name") or ""),
                               str(rel.get("html_url") or ""), str(rel.get("published_at") or ""), name, url,
                               size if isinstance(size, int) and not isinstance(size, bool) else None))
            if len(found) >= MAX_ASSETS_PER_SOURCE:
                return found
    return found


# --------------------------------------------------------------------------- verificação

@dataclass
class Entry:
    found: Found
    stage: str = "descoberto"
    reason: str | None = None
    detail: str = ""
    title_id: str | None = None
    content_id: str | None = None
    name: str | None = None
    kind: str | None = None
    version: str | None = None
    total_size: int | None = None
    final_host: str | None = None
    is_new: bool = False
    warnings: list[str] = field(default_factory=list)

    def reject(self, reason: str, detail: str = "") -> "Entry":
        self.reason, self.detail = reason, detail
        return self

    def to_dict(self) -> dict:
        f = self.found
        return {"key": f.key, "source": f.source.id, "release": f.tag, "asset": f.asset_name, "url": f.url,
                "sizeFeed": f.size, "stage": self.stage, "rejected": self.reason is not None,
                "reason": self.reason, "detail": self.detail, "titleId": self.title_id, "contentId": self.content_id,
                "name": self.name, "kind": self.kind, "version": self.version, "sizeVerified": self.total_size,
                "downloadHost": urlsplit(f.url).hostname, "isNew": self.is_new, "warnings": self.warnings}


def verify(found: Found, net, cfg: Config) -> Entry:
    e = Entry(found)
    # 1) acessível? (uma requisição Range de 64 KiB; nunca o pacote inteiro)
    pr = net.probe(found.url, HEAD_BYTES)
    if not pr.ok:
        return e.reject("UNREACHABLE", pr.error or f"HTTP {pr.status}")
    e.final_host = urlsplit(pr.final_url).hostname
    if pr.content_type and pr.content_type.startswith("text/"):
        return e.reject("NOT_FILE", f"content-type {pr.content_type}")
    if pr.total_size is not None and found.size is not None and pr.total_size != found.size:
        return e.reject("SIZE_MISMATCH", f"feed {found.size} B, servidor {pr.total_size} B")
    e.total_size = pr.total_size if pr.total_size is not None else found.size
    e.stage = "acessivel"
    # 2) identidade lida do próprio PKG
    try:
        head = parse_head(pr.head)
    except PkgError as ex:
        return e.reject(ex.code, str(ex))
    e.content_id, e.name, e.kind = head.content_id, head.sfo.get("TITLE"), head.kind
    e.version = head.sfo.get("APP_VER") or head.sfo.get("VERSION")
    if head.sfo.get("TITLE_ID") != head.title_id:
        return e.reject("IDENTITY_MISMATCH", f"param.sfo TITLE_ID={head.sfo.get('TITLE_ID')} ≠ Content ID ({head.title_id})")
    if head.sfo.get("CONTENT_ID") not in (None, head.content_id):
        return e.reject("IDENTITY_MISMATCH", "CONTENT_ID do param.sfo ≠ cabeçalho do PKG")
    e.title_id = head.title_id
    e.stage = "pkg_verificado"
    # 3) regras do SSPI (importação já comprovada só para CUSA; NPXS/APOL recusados; instalação ainda não comprovada)
    if not sspi.TITLE_ID_RE.match(head.title_id):
        return e.reject("ID_FORMAT", f"{head.title_id} fora do padrão aceito pelo SSPI")
    if head.title_id.startswith(sspi.CONSOLE_REJECTED_PREFIXES):
        return e.reject("PREFIX_REJECTED_BY_SSPI", f"prefixo {head.title_id[:4]} recusado na importação (Gate 2)")
    if not head.title_id.startswith(sspi.CONSOLE_PROVEN_PREFIXES):
        return e.reject("PREFIX_UNPROVEN", f"prefixo {head.title_id[:4]} não comprovado no console")
    if sspi.is_placeholder_id(head.title_id):
        return e.reject("PLACEHOLDER_ID", f"{head.title_id} é ID fictício")
    if head.kind != "base":
        return e.reject("KIND_UNTESTED", f"tipo '{head.kind}' (CATEGORY={head.sfo.get('CATEGORY')}): só 'base' é publicado; update/DLC não testados")
    if not found.url.startswith("https://"):
        return e.reject("NOT_HTTPS", "URL não é HTTPS")
    e.stage = "compativel_sspi"
    # 4) política de TLS do console (dados em config/sources.json; atualizar conforme os testes)
    host = urlsplit(found.url).hostname or ""
    if cfg.tls_enforce and host in cfg.tls_known_bad:
        return e.reject("TLS_HOST_BLOCKED", f"{host}: {cfg.tls_known_bad[host]}")
    # autorização vem da allowlist da fonte (validada no load_config)
    e.stage = "publicado"
    return e


# --------------------------------------------------------------------------- catálogo canônico

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
            "authorization": {"basis": f.source.auth_basis, "evidence": f.source.auth_evidence}})
    return {"schema": "ps4storebr.catalog/v1",
            "source": {"id": cfg.catalog_id, "name": cfg.catalog_name, "description": cfg.catalog_description[:500],
                       "version": version},
            "titles": list(titles.values())}


# --------------------------------------------------------------------------- execução

@dataclass
class RunResult:
    report: dict
    published: int
    wrote_catalog: bool


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state(path: Path) -> dict:
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        if st.get("schema") == STATE_SCHEMA:
            return st
    except (OSError, ValueError):
        pass
    return {"schema": STATE_SCHEMA, "versionCounter": 0, "catalogHash": "", "seen": {}}


def run(cfg: Config, net, *, out_gssource: Path, out_canonical: Path, out_report: Path, state_path: Path,
        dry_run: bool = False, now: str | None = None) -> RunResult:
    now = now or _now()
    state = _load_state(state_path)
    entries: list[Entry] = []
    source_status: list[dict] = []
    for src in cfg.sources:
        if not src.enabled:
            source_status.append({"source": src.id, "repo": src.repo, "status": "desativada"})
            continue
        try:
            found = discover_github(src, net)
        except Exception as ex:                      # uma fonte fora do ar não derruba as demais
            source_status.append({"source": src.id, "repo": src.repo, "status": "erro", "error": str(ex)})
            continue
        source_status.append({"source": src.id, "repo": src.repo, "status": "ok", "discovered": len(found)})
        for f in found:
            e = verify(f, net, cfg)
            e.is_new = f.key not in state["seen"]
            entries.append(e)

    published = [e for e in entries if e.stage == "publicado"]
    canonical = None
    wrote = False
    compile_error = None
    if published:
        cur = {"titles": build_canonical(cfg, published, "0.0.0")["titles"]}
        chash = hashlib.sha256(json.dumps(cur, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        counter = state["versionCounter"] + (0 if chash == state["catalogHash"] else 1)
        canonical = build_canonical(cfg, published, f"1.0.{counter}")
        try:
            files, rep = compile_catalog(parse(canonical))
            data = zip_files(files)
            res = sspi.check_archive(data)
            if not res.ok:
                raise ValueError("; ".join(res.errors))
        except (CatalogError, ValueError) as ex:
            compile_error = str(ex)
        else:
            if not dry_run:
                write_atomic(out_gssource, data)
                write_atomic(out_canonical, (json.dumps(canonical, ensure_ascii=False, indent=2) + "\n").encode())
                state["versionCounter"], state["catalogHash"] = counter, chash
            wrote = True
            artifact = {"path": str(out_gssource), "version": f"1.0.{counter}", "sha256": sspi.sha256(data),
                        "contentSha256": sspi.content_sha256(data), "titles": rep.published_titles}
    report = build_report(cfg, now, source_status, entries, wrote, compile_error, canonical, dry_run)
    if wrote:
        report["artifact"] = artifact
    if not dry_run:
        for e in entries:
            state["seen"].setdefault(e.found.key, {"firstSeen": now})["lastStage"] = e.stage
        write_atomic(state_path, (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
        write_atomic(out_report, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
        write_atomic(out_report.with_suffix(".md"), render_markdown(report).encode())
    return RunResult(report, len(published), wrote)


def build_report(cfg, now, source_status, entries, wrote, compile_error, canonical, dry_run) -> dict:
    reached = lambda stage: sum(1 for e in entries if STAGES.index(e.stage) >= STAGES.index(stage))
    reasons: dict[str, int] = {}
    for e in entries:
        if e.reason:
            reasons[e.reason] = reasons.get(e.reason, 0) + 1
    return {"generatedAt": now, "dryRun": dry_run,
            "note": "Compatibilidade de instalação NÃO comprovada no console (T8 pendente): 'compativel_sspi' = regras conhecidas.",
            "sources": source_status,
            "counts": {"descobertos": len(entries), "acessiveis": reached("acessivel"),
                       "pkgVerificados": reached("pkg_verificado"), "compativeisSspi": reached("compativel_sspi"),
                       "publicados": reached("publicado"), "novos": sum(1 for e in entries if e.is_new),
                       "rejeitados": sum(1 for e in entries if e.reason), "motivos": reasons},
            "catalogUpdated": wrote, "catalogError": compile_error,
            "entries": [e.to_dict() for e in entries]}


def render_markdown(r: dict) -> str:
    c = r["counts"]
    L = [f"# Relatório de descoberta — {r['generatedAt']}", "", f"> {r['note']}", "",
         "| Descobertos | Acessíveis | PKG verificado | Compatíveis (regras) | Publicados | Novos | Rejeitados |",
         "|---|---|---|---|---|---|---|",
         f"| {c['descobertos']} | {c['acessiveis']} | {c['pkgVerificados']} | {c['compativeisSspi']} | {c['publicados']} | {c['novos']} | {c['rejeitados']} |", ""]
    L.append("## Fontes")
    for s in r["sources"]:
        L.append(f"- `{s['source']}` ({s['repo']}): {s['status']}" + (f", {s['discovered']} .pkg" if 'discovered' in s else "") + (f" — {s['error']}" if s.get("error") else ""))
    L += ["", f"Catálogo atualizado: **{'sim' if r['catalogUpdated'] else 'não'}**" + (f" — {r['catalogError']}" if r.get("catalogError") else "")]
    if r.get("artifact"):
        a = r["artifact"]
        L.append(f"Artefato: `{a['path']}` v{a['version']} · títulos: {', '.join(a['titles'])} · contentSha256 `{a['contentSha256'][:16]}…`")
    L += ["", "## Entradas", "", "| Novo | Estágio | Resultado | Título | Arquivo | Detalhe |", "|---|---|---|---|---|---|"]
    for e in r["entries"]:
        res = "**publicado**" if not e["rejected"] else f"rejeitado: `{e['reason']}`"
        L.append(f"| {'sim' if e['isNew'] else ''} | {e['stage']} | {res} | {e['titleId'] or ''} | {e['asset']} ({e['release']}) | {e['detail']} |")
    return "\n".join(L) + "\n"
