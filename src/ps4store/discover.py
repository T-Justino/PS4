"""Gate 3 (MVP): descobre pacotes em fontes AUTORIZADAS, verifica os links com requisições leves e gera o catálogo.

Fluxo (um comando: `python -m ps4store run`):
  fonte (allowlist) → feed/API de releases → [descoberto] → Range nos primeiros 64 KiB → [acessível]
  → cabeçalho + param.sfo do PKG → [pkg verificado] → regras do SSPI → [compatível] → autorização + TLS → [publicado]
Só entram no catálogo instalável as entradas que chegam ao fim. As demais ficam no relatório, com o motivo.
Sem banco de dados: estado em um JSON versionável. Não baixa pacotes completos e não faz crawl genérico.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import sspi
from .build import compile_catalog, write_atomic, zip_files
from .catalog import AUTH_BASES, CatalogError, parse
from .links import classify_link, file_type, is_retail_style, multipart_info
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
    base_url: str = ""             # pkg-zone-catalog
    delay_seconds: float = 0.0     # pausa entre sondagens (educação com a fonte)
    max_probes: int = 250          # teto de sondagens por execução (o resto fica para a próxima)
    recheck_hours: float = 0.0     # 0 = sem cache; reaproveita a verificação por este tempo (evita repetir downloads parciais)

    critical: bool = True          # fonte com erro bloqueia a atualização do .gssource (mantém o último válido)
    authorized_titles: dict = field(default_factory=dict)   # titleId -> {basis, evidence}: autorização POR ITEM
    path: str = ""                 # github-contents: pasta do repositório com os .pkg
    ref: str = ""                  # github-contents: branch/tag (vazio = padrão do repositório)

    def auth_for(self, title_id: str | None) -> tuple[str, str] | None:
        """Autorização que vale para este título: a do item (se houver) ou a da fonte inteira. Nunca presumida."""
        a = self.authorized_titles.get(title_id or "")
        if a:
            return a["basis"], a["evidence"]
        if self.auth_basis in AUTH_BASES and self.auth_evidence:
            return self.auth_basis, self.auth_evidence
        return None

    @property
    def authorized(self) -> bool:
        return self.auth_for(None) is not None


@dataclass
class Config:
    catalog_id: str
    catalog_name: str
    catalog_description: str
    tls_enforce: bool
    tls_known_bad: dict
    sources: list[Source]
    tls_untested: dict = field(default_factory=dict)   # host -> nota; só gera aviso (não bloqueia)


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
        typ = s.get("type")
        if typ not in ("github-releases", "github-contents", "pkg-zone-catalog"):
            errs.append(f"{w}: type deve ser github-releases, github-contents ou pkg-zone-catalog")
        if typ == "github-contents" and not re.match(r"^[A-Za-z0-9_./-]{1,200}$", s.get("path") or "") :
            errs.append(f"{w}: github-contents exige path (pasta do repositório)")
        if typ in ("github-releases", "github-contents") and not REPO_RE.match(s.get("repo") or ""):
            errs.append(f"{w}: repo deve ser dono/nome")
        base = s.get("base_url") or ""
        if typ == "pkg-zone-catalog" and not re.match(r"^https://[a-z0-9.-]+$", base):
            errs.append(f"{w}: base_url deve ser https://host")
        a = s.get("authorization")
        if a is None:
            a = {}                                   # sem autorização: descobre e verifica, mas NUNCA publica
        elif a.get("basis") not in AUTH_BASES or not a.get("evidence"):
            errs.append(f"{w}: authorization (se presente) exige basis ∈ {AUTH_BASES} e evidence; use null se não houver")
        at: dict = {}
        for tid, aa in (s.get("authorized_titles") or {}).items():
            if not sspi.TITLE_ID_RE.match(tid) or not isinstance(aa, dict) or aa.get("basis") not in AUTH_BASES or not aa.get("evidence"):
                errs.append(f"{w}: authorized_titles[{tid}] exige ID válido, basis ∈ {AUTH_BASES} e evidence")
            else:
                at[tid] = {"basis": aa["basis"], "evidence": aa["evidence"]}
        srcs.append(Source(sid, typ or "", s.get("repo", ""), s.get("enabled", True) is True,
                           s.get("include_prereleases") is True, int(s.get("max_releases", 20)),
                           a.get("basis", ""), a.get("evidence", ""), s.get("api_base", "https://api.github.com"),
                           base, float(s.get("delay_seconds", 0)), int(s.get("max_probes", 250)),
                           float(s.get("recheck_hours", 0)), s.get("critical", True) is True, at, s.get("path", ""), s.get("ref", "")))
    if not srcs:
        errs.append("nenhuma fonte configurada")
    if errs:
        raise ConfigError("\n".join(errs))
    return Config(cat["id"], cat["name"], cat.get("description", ""), tls.get("enforce", True) is True,
                  dict(tls.get("known_bad_hosts") or {}), srcs, dict(tls.get("untested_hosts") or {}))


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
    name_hint: str | None = None      # nome do catálogo da fonte (mais legível que o TITLE do PKG)
    skip_reason: str | None = None    # descoberto, mas não vale sondar (ex.: PS5)
    meta: dict = field(default_factory=dict)


def discover_pkgzone(src: Source, net) -> list[Found]:
    """Lê o catálogo JSON público do PKG-Zone (o mesmo que o site carrega ao abrir): 1 requisição por execução.

    Só releases ativas. A URL guardada é o link ESTÁVEL `/download/{console}/{titleId}/{versão}`; o redirect para a URL
    assinada (que expira) nunca é gravado.
    """
    doc = net.get_json(f"{src.base_url}/api/v1/catalog")
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise ValueError("catálogo do PKG-Zone sem 'items'")
    found: list[Found] = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("titleId"), str):
            continue
        for r in it.get("releases") or []:
            if not isinstance(r, dict) or r.get("active") is not True:
                continue
            console, ver = str(r.get("console") or ""), str(r.get("version") or "")
            if not console or not ver:
                continue
            tid = it["titleId"].upper()
            url = f"{src.base_url}/download/{quote(console)}/{quote(tid)}/{quote(ver, safe='')}"
            size = r.get("size")
            found.append(Found(
                f"{src.id}#{tid}#{console}#{ver}#{r.get('date') or ''}", src, ver, f"{src.base_url}/",
                str(r.get("date") or ""), f"{tid}_{console}_v{ver}.pkg", url,
                size if isinstance(size, int) and not isinstance(size, bool) else None,
                name_hint=str(it.get("name") or "")[:200] or None,
                skip_reason=None if console == "ps4" else "NOT_PS4",
                meta={"catalogTitleId": tid, "console": console, "author": it.get("author"),
                      "category": it.get("category"), "firmware": r.get("pv")}))
    return found


def discover_contents(src: Source, net) -> list[Found]:
    """Lista os .pkg de uma PASTA de um repositório autorizado (API Contents do GitHub) e usa o link `download_url` (raw).

    "Release nova" = arquivo novo ou alterado na pasta: a chave inclui o sha do blob, então qualquer mudança é detectada.
    Útil quando o host de Releases (github.com) não é baixável pelo console; o raw.githubusercontent.com é outro host.
    """
    q = f"?ref={quote(src.ref, safe='')}" if src.ref else ""
    items = net.get_json(f"{src.api_base}/repos/{src.repo}/contents/{quote(src.path.strip('/'))}{q}")
    if not isinstance(items, list):
        raise ValueError("resposta inesperada da API de contents (a pasta existe e é um diretório?)")
    found: list[Found] = []
    for it in items:
        if not isinstance(it, dict) or it.get("type") != "file":
            continue
        name, url, sha = it.get("name"), it.get("download_url"), it.get("sha")
        if not (isinstance(name, str) and (name.lower().endswith(".pkg") or multipart_info(name))
                and isinstance(url, str) and isinstance(sha, str)):
            continue
        size = it.get("size")
        found.append(Found(f"{src.id}#{sha}", src, sha[:7], str(it.get("html_url") or ""), "", name, url,
                           size if isinstance(size, int) and not isinstance(size, bool) else None))
        if len(found) >= MAX_ASSETS_PER_SOURCE:
            break
    return found


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
            if not (isinstance(name, str) and isinstance(url, str) and (name.lower().endswith(".pkg") or multipart_info(name))):
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
    link: dict = field(default_factory=dict)      # classificação do link (links.classify_link)
    restricted: bool = False                      # ID/categoria de aparência comercial: nunca vai a catálogo nem à lista pessoal
    duplicate_of: str | None = None

    @property
    def phase(self) -> str:
        """DESCOBERTO (achado na fonte) → VERIFICADO (URL e metadados examinados) → PUBLICAVEL (autorizado e compatível)."""
        if self.stage == "publicado":
            return "PUBLICAVEL"
        return "VERIFICADO" if self.stage in ("pkg_verificado", "compativel_sspi") else "DESCOBERTO"

    def to_cache(self, now: str) -> dict:
        return {"checkedAt": now, "stage": self.stage, "reason": self.reason, "detail": self.detail,
                "titleId": self.title_id, "contentId": self.content_id, "name": self.name, "kind": self.kind,
                "version": self.version, "totalSize": self.total_size, "finalHost": self.final_host,
                "warnings": self.warnings, "link": self.link, "restricted": self.restricted}

    def load_cache(self, c: dict) -> "Entry":
        self.stage, self.reason, self.detail = c["stage"], c["reason"], c["detail"]
        self.title_id, self.content_id, self.name, self.kind = c["titleId"], c["contentId"], c["name"], c["kind"]
        self.version, self.total_size, self.final_host = c["version"], c["totalSize"], c["finalHost"]
        self.link, self.restricted = c.get("link") or {}, bool(c.get("restricted"))
        self.warnings = list(c["warnings"]) + ["resultado reaproveitado do cache (não sondado nesta execução)"]
        return self

    def reject(self, reason: str, detail: str = "") -> "Entry":
        self.reason, self.detail = reason, detail
        return self

    def to_dict(self) -> dict:
        f = self.found
        return {"key": f.key, "fase": self.phase, "source": f.source.id, "release": f.tag, "asset": f.asset_name, "url": f.url,
                "sizeFeed": f.size, "stage": self.stage, "rejected": self.reason is not None,
                "reason": self.reason, "detail": self.detail, "titleId": self.title_id, "contentId": self.content_id,
                "name": self.name, "kind": self.kind, "version": self.version, "sizeVerified": self.total_size,
                "downloadHost": urlsplit(f.url).hostname, "finalHost": self.final_host, "fileType": file_type(f.asset_name),
                "link": self.link, "restricted": self.restricted, "duplicateOf": self.duplicate_of,
                "isNew": self.is_new, "meta": f.meta, "warnings": self.warnings}


def mark_duplicates(entries: list[Entry]) -> None:
    """Mesmo arquivo em mais de um lugar (mesmo Content ID, versão e tamanho): o primeiro vale, os demais viram `duplicateOf`."""
    seen: dict[tuple, str] = {}
    for e in entries:
        if e.content_id and e.total_size:
            k = (e.content_id, e.version, e.total_size)
            if k in seen:
                e.duplicate_of = seen[k]
            else:
                seen[k] = e.found.key


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
            e.reject("SUPERSEDED", f"{e.title_id}: versão {w.version} ({w.found.asset_name}) é mais nova; só uma versão por ID entra no catálogo")
    return [e for e in published if id(e) in keep]


def _policy(e: Entry, cfg: Config) -> Entry:
    """Reavalia TLS e autorização sobre um resultado já verificado (cache), pois a política muda sem nova sondagem."""
    if e.stage not in ("compativel_sspi", "publicado"):
        return e
    e.stage, e.reason, e.detail = "compativel_sspi", None, ""
    if e.restricted and e.found.source.authorized_titles.get(e.title_id) is None:
        return e.reject("RETAIL_STYLE_ID", "aparência de conteúdo comercial: só na pesquisa; catálogo exige autorização POR ITEM")
    host = urlsplit(e.found.url).hostname or ""
    if cfg.tls_enforce and host in cfg.tls_known_bad:
        return e.reject("TLS_HOST_BLOCKED", f"{host}: {cfg.tls_known_bad[host]}")
    if e.found.source.auth_for(e.title_id) is None:
        return e.reject("NO_AUTHORIZATION", f"nem a fonte '{e.found.source.id}' nem o título {e.title_id} têm autorização de listagem registrada (config/sources.json)")
    e.stage = "publicado"
    return e


def verify(found: Found, net, cfg: Config) -> Entry:
    e = Entry(found)
    mp = multipart_info(found.asset_name)
    if mp and not found.skip_reason:
        found.skip_reason = "ARCHIVE_MULTIPART"
        found.meta["multipart"] = mp
    if found.skip_reason == "ARCHIVE_MULTIPART":
        return e.reject("ARCHIVE_MULTIPART", f"RAR dividido ({found.meta['multipart']['set']}, parte {found.meta['multipart']['index']}): "
                        "o SSPI suporta (volumes declarados), mas a publicação multiparte é o Gate 5; descoberto, não sondado")
    if found.skip_reason:
        return e.reject(found.skip_reason, f"{found.meta.get('console')}: fora do alvo (PS4); não sondado")
    # 1) acessível? (uma requisição Range de 64 KiB; nunca o pacote inteiro)
    pr = net.probe(found.url, HEAD_BYTES)
    e.link = classify_link(pr)
    if not pr.ok:
        return e.reject("UNREACHABLE", pr.error or f"HTTP {pr.status}")
    e.final_host = urlsplit(pr.final_url).hostname
    if e.final_host != urlsplit(found.url).hostname:
        e.warnings.append(f"o link redireciona para {e.final_host} (URL assinada que expira): comportamento do SSPI nesse redirect não testado")
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
    e.content_id, e.name, e.kind = head.content_id, found.name_hint or (head.sfo.get("TITLE") or "").strip() or None, head.kind
    e.version = head.sfo.get("APP_VER") or head.sfo.get("VERSION")
    if head.sfo.get("TITLE_ID") != head.title_id:
        return e.reject("IDENTITY_MISMATCH", f"param.sfo TITLE_ID={head.sfo.get('TITLE_ID')} ≠ Content ID ({head.title_id})")
    if head.sfo.get("CONTENT_ID") not in (None, head.content_id):
        return e.reject("IDENTITY_MISMATCH", "CONTENT_ID do param.sfo ≠ cabeçalho do PKG")
    e.title_id = head.title_id
    cat_id = found.meta.get("catalogTitleId")
    if cat_id and cat_id != head.title_id:
        e.warnings.append(f"o catálogo da fonte declara {cat_id}, mas o PKG é {head.title_id}: vale o ID lido do PKG")
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
    e.restricted = is_retail_style(head.content_id, found.meta.get("category"))
    if e.restricted and found.source.authorized_titles.get(e.title_id) is None:
        return e.reject("RETAIL_STYLE_ID", f"Content ID {head.content_id}"
                        + (f" / categoria '{found.meta.get('category')}'" if found.meta.get("category") else "")
                        + " tem aparência de conteúdo comercial: fica só na pesquisa; só entra em catálogo com autorização POR ITEM")
    # 4) política de TLS do console (dados em config/sources.json; atualizar conforme os testes)
    host = urlsplit(found.url).hostname or ""
    if cfg.tls_enforce and host in cfg.tls_known_bad:
        return e.reject("TLS_HOST_BLOCKED", f"{host}: {cfg.tls_known_bad[host]}")
    if host in cfg.tls_untested:
        e.warnings.append(f"{host}: TLS não confirmado no SSPI ({cfg.tls_untested[host]})")
    # 5) autorização: só a da fonte (allowlist); sem ela o item fica VERIFICADO, nunca PUBLICAVEL
    if found.source.auth_for(e.title_id) is None:
        return e.reject("NO_AUTHORIZATION", f"nem a fonte '{found.source.id}' nem o título {e.title_id} têm autorização de listagem registrada (config/sources.json)")
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
            "authorization": dict(zip(("basis", "evidence"), f.source.auth_for(e.title_id)))})
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
    critical_down: list = field(default_factory=list)


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


def _age_hours(a: str, b: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds() / 3600


CONNECTORS = {"github-releases": discover_github, "github-contents": discover_contents, "pkg-zone-catalog": discover_pkgzone}


def run(cfg: Config, net, *, out_gssource: Path, out_canonical: Path, out_report: Path, state_path: Path,
        dry_run: bool = False, now: str | None = None, recheck: bool = False, sleep=time.sleep,
        refresh_links: int = 0, out_research: Path | None = None) -> RunResult:
    now = now or _now()
    state = _load_state(state_path)
    entries: list[Entry] = []
    source_status: list[dict] = []
    for src in cfg.sources:
        if not src.enabled:
            source_status.append({"source": src.id, "repo": src.repo, "status": "desativada"})
            continue
        try:
            found = CONNECTORS[src.type](src, net)
        except Exception as ex:                      # uma fonte fora do ar não derruba as demais
            source_status.append({"source": src.id, "repo": src.repo, "status": "erro", "error": str(ex), "critical": src.critical})
            continue
        source_status.append({"source": src.id, "repo": src.repo, "status": "ok", "discovered": len(found)})
        probes = 0
        refresh_left = refresh_links          # enriquecimento incremental: re-sonda N itens em cache sem dados de link
        for f in found:
            seen = state["seen"].get(f.key) or {}
            cached = seen.get("check")
            needs_link = cached and not cached.get("link") and not f.skip_reason and cached["stage"] != "descoberto"
            if needs_link and refresh_left > 0 and probes < src.max_probes:
                refresh_left -= 1
                cached = None
            if (cached and not recheck and cached["reason"] != "UNREACHABLE"
                    and _age_hours(cached["checkedAt"], now) < src.recheck_hours):
                e = Entry(f).load_cache(cached)
                e.restricted = is_retail_style(e.content_id, f.meta.get("category"))
                # a política (TLS/autorização) é reavaliada a cada execução, mesmo com cache
                if e.reason in ("TLS_HOST_BLOCKED", "NO_AUTHORIZATION", "RETAIL_STYLE_ID") or e.stage == "publicado":
                    e = _policy(e, cfg)
            elif f.skip_reason:
                e = verify(f, net, cfg)                       # sem rede
            elif probes >= src.max_probes:
                e = Entry(f).reject("PROBE_BUDGET", f"teto de {src.max_probes} sondagens por execução; fica para a próxima")
            else:
                if probes and src.delay_seconds:
                    sleep(src.delay_seconds)
                probes += 1
                e = verify(f, net, cfg)
            e.is_new = f.key not in state["seen"]
            entries.append(e)

    mark_duplicates(entries)
    published = dedupe_latest([e for e in entries if e.stage == "publicado"])
    canonical = None
    wrote = False
    compile_error = None
    critical_down = [x["source"] for x in source_status if x["status"] == "erro" and x.get("critical")]
    if published and critical_down:
        compile_error = f"fonte crítica com erro ({', '.join(critical_down)}): .gssource anterior mantido para não perder entradas"
    if published and not critical_down:
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
    if out_research is not None and not dry_run:
        write_research(out_research, entries, now)
    if wrote:
        report["artifact"] = artifact
    if not dry_run:
        for e in entries:
            rec = state["seen"].setdefault(e.found.key, {"firstSeen": now})
            rec["lastStage"] = e.stage
            if e.reason not in ("PROBE_BUDGET",) and not any("cache" in w for w in e.warnings):
                rec["check"] = e.to_cache(now)
        write_atomic(state_path, (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
        write_atomic(out_report, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
        write_atomic(out_report.with_suffix(".md"), render_markdown(report).encode())
    res = RunResult(report, len(published), wrote)
    res.critical_down = critical_down
    return res


def research_row(e: Entry) -> dict:
    f = e.found
    return {"name": e.name, "titleId": e.title_id, "contentId": e.content_id, "version": e.version, "sizeBytes": e.total_size,
            "source": f.source.id, "url": f.url, "fileType": file_type(f.asset_name), "kind": e.kind,
            "linkStatus": e.link.get("kind"), "rangeOk": e.link.get("rangeOk"), "temporaryRedirect": e.link.get("temporaryFinalUrl"),
            "sspiDownloadable": bool(e.link.get("sspiUsable")),
            "sspiCatalogCompat": e.stage in ("compativel_sspi", "publicado") or (e.reason in ("RETAIL_STYLE_ID", "NO_AUTHORIZATION", "TLS_HOST_BLOCKED")),
            "phase": e.phase, "rejectionReason": e.reason, "detail": e.detail, "restricted": e.restricted,
            "duplicateOf": e.duplicate_of, "category": f.meta.get("category"), "author": f.meta.get("author"),
            "firmware": f.meta.get("firmware"), "linkNotes": e.link.get("notes") or []}


def personal_links(entries: list[Entry]) -> list[Entry]:
    """Lista PESSOAL para colar no SSPI (Downloads → colar link): identidade verificada, link utilizável, tipo base,
    sem aparência comercial, host sem falha de TLS conhecida. Independe do prefixo do ID (o SSPI instala pelo ID do próprio PKG)
    e da autorização de publicação; **nunca** é commitada nem hospedada."""
    out = []
    for e in entries:
        if (e.phase in ("VERIFICADO", "PUBLICAVEL") and e.kind == "base" and e.link.get("sspiUsable") and not e.restricted
                and e.reason not in ("TLS_HOST_BLOCKED", "SUPERSEDED") and not e.duplicate_of):
            out.append(e)
    return out


def write_research(path: Path, entries: list[Entry], now: str) -> None:
    rows = [research_row(e) for e in entries]
    doc = {"generatedAt": now, "aviso": "USO PESSOAL. Pesquisa de metadados e disponibilidade; não é publicação. Não commitar nem hospedar este arquivo.",
           "total": len(rows), "entries": rows}
    write_atomic(path, (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode())
    pl = personal_links(entries)
    lines = ["# USO PESSOAL: cole estes links no SSPI (Downloads → tocar no touchpad → colar link, ou a página do celular).",
             "# Cada link vai direto à origem; nada é hospedado aqui. Excluídos: IDs/categorias de aparência comercial, links sem Range/identidade.",
             "# Não redistribua esta lista."]
    for e in sorted(pl, key=lambda x: (x.name or "", x.version or "")):
        lines.append(f"# {e.name} {e.version or ''} [{e.title_id}] {e.total_size or '?'} B")
        lines.append(e.found.url)
    write_atomic(path.with_name("links-sspi.txt"), ("\n".join(lines) + "\n").encode())


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
                       "publicados": reached("publicado"),
                       "fases": {ph: sum(1 for e in entries if e.phase == ph) for ph in ("DESCOBERTO", "VERIFICADO", "PUBLICAVEL")},
                       "novos": sum(1 for e in entries if e.is_new),
                       "links": {"classificados": sum(1 for e in entries if e.link),
                                 "sspiBaixaveis": sum(1 for e in entries if e.link.get("sspiUsable")),
                                 "redirectTemporario": sum(1 for e in entries if e.link.get("temporaryFinalUrl")),
                                 "semRange": sum(1 for e in entries if e.link and e.link.get("rangeOk") is False and e.link.get("sspiUsable")),
                                 "tipos": dict(collections.Counter(e.link.get("kind") for e in entries if e.link))},
                       "restritos": sum(1 for e in entries if e.restricted),
                       "duplicados": sum(1 for e in entries if e.duplicate_of),
                       "listaPessoal": len(personal_links(entries)),
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
    L += ["", "## Entradas", "", "| Novo | Fase | Estágio | Resultado | Título | Arquivo | Detalhe |", "|---|---|---|---|---|---|---|"]
    for e in r["entries"]:
        res = "**publicado**" if not e["rejected"] else f"rejeitado: `{e['reason']}`"
        L.append(f"| {'sim' if e['isNew'] else ''} | {e['fase']} | {e['stage']} | {res} | {e['titleId'] or ''} | {e['asset']} ({e['release']}) | {e['detail']} |")
    return "\n".join(L) + "\n"
