"""Modelo e configuração do robô: tipos compartilhados pelas três etapas independentes.

  1. DISCOVERY        (discover.py)    conectores: fonte → Found (título, arquivo, URL, metadados). Nunca descarta por licença/categoria/prefixo.
  2. LINK_VALIDATION  (validation.py)  sondagem leve, redirects, Range, tipo de arquivo, identidade lida do PKG. Não aplica política.
  3. PUBLICATION      (publication.py) compatibilidade SSPI + política (autorização, TLS, aparência comercial) → o que pode ir a catálogo
                                       ou ser oferecido por link direto. Descobrir uma URL NÃO é autorização de uso ou distribuição.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import sspi
from .catalog import AUTH_BASES
from .links import file_type

SOURCES_SCHEMA = "ps4storebr.sources/v1"
STATE_SCHEMA = "ps4storebr.discovery-state/v1"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
STAGES = ("descoberto", "acessivel", "pkg_verificado", "compativel_sspi", "publicado")
MAX_ASSETS_PER_SOURCE = 100
HEAD_BYTES = 65536
EXTRA_MAX = 8 * 1024 * 1024        # só lemos uma 2ª faixa pequena se tabela/param.sfo estiverem antes de 8 MiB
RAR_MAGIC = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")


class ConfigError(ValueError):
    pass




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
    all_types: bool = False        # DISCOVERY: registra também .rar/.zip/.7z únicos (config: padrão True)
    include_inactive: bool = False # DISCOVERY: registra releases inativas/antigas da fonte (config: padrão True)
    inactive_probe_budget: int = 15  # LINK_VALIDATION: quantas releases inativas validar por execução (incremental)
    queries: list = field(default_factory=list)   # github-search: consultas à API pública de busca de repositórios
    max_repos: int = 10            # github-search: repositórios por consulta

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
        if typ not in ("github-releases", "github-contents", "pkg-zone-catalog", "github-search"):
            errs.append(f"{w}: type deve ser github-releases, github-contents, pkg-zone-catalog ou github-search")
        if typ == "github-search" and not (isinstance(s.get("queries"), list) and s["queries"] and all(isinstance(q, str) and q for q in s["queries"])):
            errs.append(f"{w}: github-search exige queries (lista de consultas de repositórios)")
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
                           float(s.get("recheck_hours", 0)), s.get("critical", True) is True, at, s.get("path", ""), s.get("ref", ""),
                           all_types=s.get("all_types", True) is True, include_inactive=s.get("include_inactive", True) is True,
                           inactive_probe_budget=int(s.get("inactive_probe_budget", 15)),
                           queries=list(s.get("queries") or []), max_repos=int(s.get("max_repos", 10))))
    if not srcs:
        errs.append("nenhuma fonte configurada")
    if errs:
        raise ConfigError("\n".join(errs))
    return Config(cat["id"], cat["name"], cat.get("description", ""), tls.get("enforce", True) is True,
                  dict(tls.get("known_bad_hosts") or {}), srcs, dict(tls.get("untested_hosts") or {}))




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
    category_sfo: str | None = None
    compat: list[str] = field(default_factory=list)      # TODOS os motivos técnicos de incompatibilidade com o SSPI
    blockers: list[str] = field(default_factory=list)    # TODOS os impeditivos de PUBLICAÇÃO em catálogo (política)
    install_blockers: list[str] = field(default_factory=list)   # impeditivos da oferta por download direto (lista pessoal)
    install_ok: bool = False

    @property
    def license(self) -> dict:
        """Licença CONHECIDA (declarada pela fonte/repositório) ou LICENSE_UNKNOWN. Informativo: não autoriza nem elimina nada."""
        spdx = self.found.meta.get("license")
        known = bool(spdx) and str(spdx).upper() not in ("NOASSERTION", "OTHER", "NONE")
        return {"status": "KNOWN" if known else "LICENSE_UNKNOWN", "spdx": spdx if known else None,
                "hint": self.found.meta.get("licenseHint")}

    def status(self) -> dict:
        """As cinco perguntas do relatório, separadas: encontrado / link acessível / arquivo identificado / compatível / disponível."""
        lk = self.link.get("kind") if self.link else None
        accessible = None if not lk else lk in ("direto", "redirect")
        validated = bool(self.link)
        identified = True if self.title_id else (False if validated and accessible and file_type(self.found.asset_name) == "pkg" else None)
        compat = "not-evaluated" if not self.title_id else ("incompatible" if self.compat else "compatible")
        pub = "not-evaluated" if not self.title_id else ("available" if self.stage == "publicado" else "blocked")
        inst = "not-evaluated" if not self.title_id else ("available" if self.install_ok else "blocked")
        return {"found": True, "linkAccessible": accessible, "fileIdentified": identified, "sspiCompat": compat,
                "publication": pub, "directInstall": inst}

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
                "isNew": self.is_new, "meta": f.meta, "warnings": self.warnings,
                "license": self.license, "status": self.status(), "compatReasons": self.compat,
                "publicationBlockers": self.blockers, "directInstallBlockers": self.install_blockers}


