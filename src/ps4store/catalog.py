"""Modelo canônico ps4storebr.catalog/v1: carga e validação de política.

O canônico pode conter títulos sem link publicável (ex.: jogos comerciais sem
fonte autorizada). Esses ficam fora do .gssource e aparecem no relatório.
"""
from __future__ import annotations

import ipaddress
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import sspi

SCHEMA = "ps4storebr.catalog/v1"
LANG_VALUES = ("yes", "no", "unknown")
AUTH_BASES = ("official-developer-release", "license", "written-permission")
OPTIONAL_ROW_FIELDS = ("size", "sha256", "contentId", "requiredFirmware")


class CatalogError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class Package:
    id: str
    kind: str
    access_type: str
    url: str
    hoster: str
    label: str
    source_page_url: str | None
    version: str | None
    extra: dict
    authorized: bool


@dataclass
class Title:
    title_id: str
    name: str
    region: str | None
    aliases: list[str]
    audio_pt_br: str
    subtitles_pt_br: str
    catalog_key: bool = False   # titleId é chave sintética de catálogo (não é o ID real do pacote)
    probe: bool = False         # chave descartável de teste (única forma de usar CUSA99999)
    real_title_id: str | None = None    # identidade real do pacote, separada da chave
    real_content_id: str | None = None
    real_evidence: str | None = None
    packages: list[Package] = field(default_factory=list)


@dataclass
class Catalog:
    source_id: str
    source_name: str
    source_description: str
    source_version: str
    titles: list[Title]


def normalize_search(text: str) -> str:
    """Aproximação de nfkd-lower-alnum-spaces-v1 (o SSPI normaliza do seu lado)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join("".join(c if c.isalnum() else " " for c in stripped).split())


def _secure_url(url, field_name: str, where: str, errs: list[str]) -> None:
    if not isinstance(url, str) or not sspi.url_ok(url, https_only=True):
        errs.append(f"{where}: {field_name} deve ser https://, com host e sem credenciais")
        return
    host = urlsplit(url).hostname or ""
    try:
        ipaddress.ip_address(host)
        errs.append(f"{where}: {field_name} não pode usar IP literal")
    except ValueError:
        if host == "localhost" or host.endswith(".local"):
            errs.append(f"{where}: {field_name} aponta para host local")


def _req_str(obj: dict, key: str, where: str, errs: list[str]) -> str:
    v = obj.get(key)
    if not isinstance(v, str) or not v.strip():
        errs.append(f"{where}: '{key}' obrigatório")
        return ""
    return v


def parse(doc: dict) -> Catalog:
    errs: list[str] = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema deve ser {SCHEMA}")
    src = doc.get("source") or {}
    sid = _req_str(src, "id", "source", errs)
    name = _req_str(src, "name", "source", errs)
    version = _req_str(src, "version", "source", errs)
    if version and not sspi.VERSION_RE.match(version):
        errs.append("source.version deve ter 2 a 4 componentes numéricos")
    description = src.get("description") or ""

    titles: list[Title] = []
    seen: set[str] = set()
    raw_titles = doc.get("titles")
    if not isinstance(raw_titles, list):
        errs.append("titles deve ser lista")
        raw_titles = []
    for i, t in enumerate(raw_titles):
        where = f"titles[{i}]"
        tid = _req_str(t, "titleId", where, errs)
        where = f"titles[{i}]({tid})"
        if tid:
            if not sspi.TITLE_ID_RE.match(tid):
                errs.append(f"{where}: titleId fora do padrão AAAA00000 (PPSA não suportado)")
            elif sspi.is_placeholder_id(tid) and not (t.get("catalogKey") is True and t.get("probe") is True):
                errs.append(f"{where}: titleId fictício/placeholder proibido (só com catalogKey+probe, em teste)")
            if tid in seen:
                errs.append(f"{where}: titleId duplicado (edições/regiões distintas exigem decisão explícita)")
            seen.add(tid)
        _req_str(t, "identityEvidence", where, errs)
        real = t.get("realIdentity") if isinstance(t.get("realIdentity"), dict) else {}
        if t.get("catalogKey") is True:
            if tid and not (sspi.SYNTHETIC_KEY_RE.match(tid) or (t.get("probe") is True and tid == "CUSA99999")):
                errs.append(f"{where}: chave sintética deve estar em CUSA90000–CUSA98999 "
                            "(CUSA99999 só com probe=true)")
            rid = real.get("titleId")
            if not isinstance(rid, str) or not sspi.REAL_ID_RE.match(rid):
                errs.append(f"{where}: catalogKey exige realIdentity.titleId (AAAA00000)")
            elif rid == tid:
                errs.append(f"{where}: realIdentity.titleId não pode ser igual à chave")
            if not real.get("evidence"):
                errs.append(f"{where}: catalogKey exige realIdentity.evidence")
            if t.get("probe") is not True and tid == "CUSA99999":
                errs.append(f"{where}: CUSA99999 não é identidade de produção")
        elif real:
            errs.append(f"{where}: realIdentity só é usado com catalogKey=true")
        tname = _req_str(t, "name", where, errs)
        aliases = t.get("aliases") or []
        if not all(isinstance(a, str) for a in aliases):
            errs.append(f"{where}: aliases deve ser lista de strings")
            aliases = []
        lang = t.get("languages") or {}
        audio = lang.get("audioPtBr", "unknown")
        subs = lang.get("subtitlesPtBr", "unknown")
        for k, v in (("audioPtBr", audio), ("subtitlesPtBr", subs)):
            if v not in LANG_VALUES:
                errs.append(f"{where}: languages.{k} deve ser {LANG_VALUES}")
        if "yes" in (audio, subs) and not lang.get("evidence"):
            errs.append(f"{where}: PT-BR 'yes' exige languages.evidence")

        pkgs: list[Package] = []
        pids: set[str] = set()
        for j, p in enumerate(t.get("packages") or []):
            pw = f"{where}.packages[{j}]"
            pid = _req_str(p, "id", pw, errs)
            if pid in pids:
                errs.append(f"{pw}: id duplicado")
            pids.add(pid)
            kind = p.get("kind")
            if kind not in sspi.KINDS:
                errs.append(f"{pw}: kind deve ser {sspi.KINDS}")
            access = p.get("accessType")
            if access not in sspi.ACCESS_TYPES:
                errs.append(f"{pw}: accessType deve ser {sspi.ACCESS_TYPES}")
            _secure_url(p.get("url"), "url", pw, errs)
            spu = p.get("sourcePageUrl")
            if spu is not None:
                _secure_url(spu, "sourcePageUrl", pw, errs)
            if "volumes" in p:
                errs.append(f"{pw}: volumes (RAR multipartes) desativado até o Gate 5")
            auth = p.get("authorization") or {}
            authorized = auth.get("basis") in AUTH_BASES and bool(auth.get("evidence"))
            if auth and auth.get("basis") not in AUTH_BASES:
                errs.append(f"{pw}: authorization.basis deve ser {AUTH_BASES}")
            extra = {k: p[k] for k in OPTIONAL_ROW_FIELDS if p.get(k) is not None}
            if "sha256" in extra and not sspi.SHA256_RE.match(str(extra["sha256"])):
                errs.append(f"{pw}: sha256 inválido")
            if "size" in extra and (not isinstance(extra["size"], int) or extra["size"] < 0):
                errs.append(f"{pw}: size inválido")
            pkgs.append(Package(
                id=pid, kind=kind, access_type=access, url=p.get("url", ""),
                hoster=p.get("hoster") or "", label=p.get("label") or "",
                source_page_url=spu, version=p.get("version"), extra=extra,
                authorized=authorized))
        titles.append(Title(tid, tname, t.get("region"), aliases, audio, subs,
                            catalog_key=t.get("catalogKey") is True, probe=t.get("probe") is True,
                            real_title_id=real.get("titleId"), real_content_id=real.get("contentId"),
                            real_evidence=real.get("evidence"), packages=pkgs))

    reals = [t.real_title_id for t in titles if t.real_title_id]
    for r in {x for x in reals if reals.count(x) > 1}:
        errs.append(f"realIdentity {r} aparece em mais de uma chave: duplicaria o item na biblioteca")
    if errs:
        raise CatalogError(errs)
    return Catalog(sid, name, description, version, titles)


def load(path: str | Path) -> Catalog:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CatalogError([f"não foi possível ler {path}: {e}"]) from e
    if not isinstance(doc, dict):
        raise CatalogError(["raiz do catálogo deve ser objeto"])
    return parse(doc)
