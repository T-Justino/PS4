"""Regras do formato .gssource (engine embedded-catalog-v1).

Fontes:
  [FIXTURE] tests/fixtures/sspi_compat_5117_original.gssource — importado com sucesso no SSPI 5.11.7.
  [PUBLIC]  app/PackageSourceEngineStatic.cs (GitHub). Pode divergir do binário instalado.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# --- [FIXTURE] constantes observadas no arquivo aceito pelo console
SOURCE_SCHEMA = "gamesearch.source/v1"
ENGINE_TYPE = "embedded-catalog-v1"
ENTRY_FILE = "catalog.json"
CAPABILITIES = ["titles.search", "titles.catalog", "packages.resolve"]
CATALOG_FORMAT = "embedded-catalog-v1"
FORMAT_VERSION = 1
SEARCH_NORMALIZATION = "nfkd-lower-alnum-spaces-v1"

# --- [PUBLIC] limites e domínios
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024          # guia: ZIP até 4 MiB
MAX_SOURCE_JSON_BYTES = 256 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SHARD_BYTES = 1_500_000
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_TITLES = 30_000
MAX_TITLES_PER_INDEX = 500
MAX_MANIFEST_FILES = 63
MAX_INDEX_FILES = 62
MAX_PACKAGE_FILES = 62
MAX_ROWS_PER_TITLE = 512
TITLE_ID_RE = re.compile(r"^(?!PPSA)[A-Z]{4}[0-9]{5}$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
KINDS = ("base", "update", "dlc", "backport", "unknown")
ACCESS_TYPES = ("Direct", "HosterLanding")

# Prefixos com aceitação observada no SSPI 5.11.7 do usuário (atualizar após o Gate 2).
# CUSA: fixture aceito (CUSA99999, importação + busca). APOL: rejeitado em catálogo antigo.
CONSOLE_PROVEN_PREFIXES: tuple[str, ...] = ("CUSA",)
# Rejeitados pelo SSPI 5.11.7 Final (rodapé "BETA 5.11 / 0eb783eca1f3") na importação (Gate 2, 22/11/2026, foto do usuário):
# "Source couldn't be added — Static catalog: Unsupported catalog title identifier".
CONSOLE_REJECTED_PREFIXES: tuple[str, ...] = ("NPXS", "APOL")

# Faixa reservada do projeto para chaves SINTÉTICAS de catálogo (assumida livre de IDs oficiais; não verificável).
SYNTHETIC_KEY_RE = re.compile(r"^CUSA9[0-8][0-9]{3}$")
CONTENT_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{4}-([A-Z]{4}[0-9]{5})_[0-9]{2}-[A-Z0-9_-]{16}$")
REAL_ID_RE = re.compile(r"^[A-Z]{4}[0-9]{5}$")

_BAD_PATH_CHARS = re.compile(r"[\\:\x00-\x1f\x7f]")

STR_LIMITS_TITLE = {"titleId": 16, "region": 32, "packagesFile": 180, "name": 512,
                    "icon": 2048, "searchText": 2048}
STR_LIMITS_ROW = {"id": 256, "titleId": 16, "region": 32, "kind": 16, "url": 4096,
                  "label": 512, "hoster": 256, "version": 64, "requiredFirmware": 64,
                  "groupId": 256, "sourcePageUrl": 2048, "contentId": 128,
                  "accessType": 32, "name": 512}


def dumps(obj) -> bytes:
    """Serialização canônica idêntica à do fixture aceito (JSON compacto, UTF-8)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_sha256(archive: bytes) -> str:
    """Hash estável do CONTEÚDO: sha256 do source.json descomprimido.

    O source.json lista size+sha256 de todos os outros arquivos, então este hash identifica o
    conteúdo inteiro e independe do compressor deflate (o hash do ZIP varia entre builds de zlib).
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        return sha256(z.read("source.json"))


def is_placeholder_id(title_id: str) -> bool:
    return title_id[4:] in ("99999", "00000")


def path_ok(path: str) -> bool:
    if not path or path.startswith("/") or _BAD_PATH_CHARS.search(path):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def url_ok(url: str, *, https_only: bool) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    allowed = ("https",) if https_only else ("http", "https")
    return (parts.scheme in allowed and bool(parts.hostname)
            and parts.username is None and parts.password is None)


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_json(name: str, data: bytes, limit: int, res: CheckResult):
    if len(data) > limit:
        res.errors.append(f"{name}: {len(data)} bytes excede limite {limit}")
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        res.errors.append(f"{name}: não é UTF-8 válido")
    except json.JSONDecodeError as e:
        res.errors.append(f"{name}: JSON inválido ({e.msg})")
    return None


def _check_strs(obj: dict, limits: dict, where: str, res: CheckResult):
    for k, lim in limits.items():
        v = obj.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > lim):
            res.errors.append(f"{where}: campo '{k}' inválido ou maior que {lim}")


def check_files(files: dict[str, bytes], *, archive_size: int | None = None,
                allow_placeholder_ids: bool = False) -> CheckResult:
    """Valida o conteúdo de um .gssource (dicionário caminho → bytes)."""
    res = CheckResult()
    if archive_size is not None and archive_size > MAX_ARCHIVE_BYTES:
        res.errors.append(f"arquivo .gssource com {archive_size} bytes excede {MAX_ARCHIVE_BYTES}")
    for p in files:
        if not path_ok(p):
            res.errors.append(f"caminho inválido no ZIP: {p!r}")

    raw = files.get("source.json")
    if raw is None:
        res.errors.append("source.json ausente")
        return res
    src = _load_json("source.json", raw, MAX_SOURCE_JSON_BYTES, res)
    if not isinstance(src, dict):
        return res
    if src.get("schema") != SOURCE_SCHEMA:
        res.errors.append(f"source.json: schema deve ser {SOURCE_SCHEMA}")
    sid = src.get("id")
    if not isinstance(sid, str) or not sid or len(sid) > 128:
        res.errors.append("source.json: id ausente ou > 128")
    ver = src.get("version")
    if not isinstance(ver, str) or not VERSION_RE.match(ver) or len(ver) > 64:
        res.errors.append("source.json: version deve ter 2 a 4 componentes numéricos")
    if not isinstance(src.get("name"), str) or not src.get("name"):
        res.errors.append("source.json: name ausente")
    eng = src.get("engine") or {}
    if eng.get("type") != ENGINE_TYPE:
        res.errors.append(f"source.json: engine.type deve ser {ENGINE_TYPE}")
    if eng.get("entryFile") != ENTRY_FILE:
        res.errors.append("Static engine entry must be catalog.json")
    if set(eng) - {"type", "entryFile"}:
        res.errors.append("source.json: engine estático não pode declarar origens de rede/extras")
    if set(src) & {"update", "updateUrl", "origins"}:
        res.errors.append("Static catalogs cannot declare network origins")

    manifest = src.get("files")
    if not isinstance(manifest, list) or not manifest or len(manifest) > MAX_MANIFEST_FILES:
        res.errors.append(f"source.json: files deve ter 1 a {MAX_MANIFEST_FILES} entradas")
        return res
    declared: set[str] = set()
    for entry in manifest:
        p = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(p, str) or not path_ok(p) or len(p) > 180:
            res.errors.append(f"source.json: caminho de manifesto inválido {p!r}")
            continue
        if p in declared:
            res.errors.append(f"source.json: caminho duplicado {p}")
        declared.add(p)
        data = files.get(p)
        if data is None:
            res.errors.append(f"manifesto lista {p}, ausente no ZIP")
            continue
        if entry.get("size") != len(data):
            res.errors.append(f"{p}: tamanho declarado {entry.get('size')} ≠ real {len(data)}")
        h = entry.get("sha256")
        if not isinstance(h, str) or not SHA256_RE.match(h) or h.lower() != sha256(data):
            res.errors.append(f"{p}: sha256 não confere")
    for p in files:
        if p != "source.json" and p not in declared:
            res.warnings.append(f"{p} presente no ZIP mas fora do manifesto")
    if ENTRY_FILE not in declared:
        res.errors.append("catalog.json ausente do manifesto")
        return res

    cat = _load_json("catalog.json", files.get("catalog.json", b""), MAX_JSON_BYTES, res)
    if not isinstance(cat, dict):
        return res
    if cat.get("format") != CATALOG_FORMAT or cat.get("formatVersion") != FORMAT_VERSION:
        res.errors.append("Catalog format needs a newer SSPI release; install it and restart the PS4")
    if cat.get("searchNormalization") != SEARCH_NORMALIZATION:
        res.errors.append(f"catalog.json: searchNormalization deve ser {SEARCH_NORMALIZATION}")
    idx_files = cat.get("indexFiles") or []
    pkg_files = cat.get("packageFiles") or []
    for lst, prefix, lim, label in ((idx_files, "index/", MAX_INDEX_FILES, "indexFiles"),
                                    (pkg_files, "packages/", MAX_PACKAGE_FILES, "packageFiles")):
        if not isinstance(lst, list) or not lst or len(lst) > lim:
            res.errors.append(f"catalog.json: {label} deve ter 1 a {lim} entradas")
            continue
        for p in lst:
            if not (isinstance(p, str) and p.startswith(prefix) and p.endswith(".json")):
                res.errors.append(f"catalog.json: {label} contém caminho inválido {p!r}")
            elif p not in declared:
                res.errors.append(f"catalog.json: {p} não está no manifesto")
    if res.errors:
        return res

    # --- índice
    indexed: dict[str, dict] = {}
    index_bytes = 0
    for p in idx_files:
        data = files[p]
        index_bytes += len(data)
        doc = _load_json(p, data, MAX_JSON_BYTES, res)
        titles = doc.get("titles") if isinstance(doc, dict) else None
        if not isinstance(titles, list) or len(titles) > MAX_TITLES_PER_INDEX:
            res.errors.append(f"{p}: titles deve ser lista com até {MAX_TITLES_PER_INDEX}")
            continue
        for t in titles:
            if not isinstance(t, dict):
                res.errors.append(f"{p}: título não é objeto")
                continue
            tid = t.get("titleId")
            where = f"{p}[{tid}]"
            _check_strs(t, STR_LIMITS_TITLE, where, res)
            if not isinstance(tid, str) or not TITLE_ID_RE.match(tid):
                res.errors.append(f"{where}: Unsupported catalog title identifier")
                continue
            if tid.startswith(CONSOLE_REJECTED_PREFIXES):
                res.errors.append(f"{where}: Unsupported catalog title identifier "
                                  f"(prefixo {tid[:4]} rejeitado pelo SSPI 5.11.7 no console)")
            if is_placeholder_id(tid) and not allow_placeholder_ids:
                res.errors.append(f"{where}: ID fictício/placeholder proibido")
            if tid in indexed:
                res.errors.append(f"{where}: título duplicado no índice")
            if not t.get("name"):
                res.errors.append(f"{where}: name obrigatório")
            if t.get("packagesFile") not in pkg_files:
                res.errors.append(f"{where}: packagesFile não declarado")
            rc = t.get("releaseCount")
            if not isinstance(rc, int) or isinstance(rc, bool) or not 1 <= rc <= MAX_ROWS_PER_TITLE:
                res.errors.append(f"{where}: releaseCount fora de 1..512")
            kinds = t.get("kinds")
            if not isinstance(kinds, list) or len(kinds) > 8 or any(k not in KINDS for k in kinds):
                res.errors.append(f"{where}: kinds inválido")
            icon = t.get("icon")
            if icon is not None and not url_ok(icon, https_only=False):
                res.errors.append(f"{where}: icon deve ser URL http(s)")
            if not tid.startswith(CONSOLE_PROVEN_PREFIXES):
                res.warnings.append(f"{where}: prefixo {tid[:4]} aceito pelo parser público, "
                                    "não comprovado no console")
            indexed[tid] = t
    if index_bytes > MAX_INDEX_BYTES:
        res.errors.append("Catalog title index exceeds its memory budget; split the source")
    if len(indexed) > MAX_TITLES:
        res.errors.append("Catalog has too many indexed titles; split the source")

    # --- shards
    rows_by_title: dict[str, list] = {}
    shard_of: dict[str, str] = {}
    for p in pkg_files:
        data = files[p]
        if len(data) > MAX_SHARD_BYTES:
            res.errors.append(f"{p}: shard excede {MAX_SHARD_BYTES} bytes")
        doc = _load_json(p, data, MAX_JSON_BYTES, res)
        titles = doc.get("titles") if isinstance(doc, dict) else None
        if not isinstance(titles, dict):
            res.errors.append(f"{p}: raiz 'titles' deve ser objeto")
            continue
        for tid, rows in titles.items():
            if tid in rows_by_title:
                res.errors.append(f"{p}[{tid}]: título em mais de um shard")
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS_PER_TITLE:
                res.errors.append(f"{p}[{tid}]: Package choices must contain 1 to 512 records")
                continue
            rows_by_title[tid] = rows
            shard_of[tid] = p
            ids: set[str] = set()
            for row in rows:
                _check_row(row, tid, f"{p}[{tid}]", ids, res)

    releases = 0
    for tid, t in indexed.items():
        rows = rows_by_title.get(tid)
        if not rows:
            res.errors.append(f"{tid}: Selected title has no published package choices")
            continue
        if shard_of[tid] != t.get("packagesFile"):
            res.errors.append(f"{tid}: packagesFile aponta para shard errado")
        if t.get("releaseCount") != len(rows):
            res.errors.append(f"Indexed package count disagrees with its shard: {tid}")
        releases += len(rows)
    for tid in rows_by_title:
        if tid not in indexed:
            res.warnings.append(f"{tid}: pacotes sem título no índice")

    counts = cat.get("counts") or {}
    multipart = sum(1 for rs in rows_by_title.values() for r in rs if isinstance(r, dict) and r.get("volumes"))
    expected = {"titles": len(indexed), "readyTitles": len(indexed), "releases": releases,
                "multipartGroups": multipart, "unresolved": 0}
    if counts != expected:
        res.errors.append(f"Catalog counts do not match its ready titles and package choices "
                          f"(declarado {counts}, esperado {expected})")
    if not indexed:
        res.errors.append("Catalog has no ready titles")
    return res


def _check_row(row, tid: str, where: str, ids: set, res: CheckResult):
    if not isinstance(row, dict):
        res.errors.append(f"{where}: pacote não é objeto")
        return
    _check_strs(row, STR_LIMITS_ROW, where, res)
    rid = row.get("id")
    if not rid:
        res.errors.append(f"{where}: id do pacote obrigatório")
    elif rid in ids:
        res.errors.append(f"{where}: id de pacote duplicado {rid}")
    ids.add(rid)
    if row.get("titleId") not in (None, tid):
        res.errors.append(f"{where}: titleId do pacote difere da chave")
    if row.get("kind") not in KINDS:
        res.errors.append(f"{where}: Unsupported package kind")
    if row.get("accessType") not in ACCESS_TYPES:
        res.errors.append(f"{where}: Unsupported package access type")
    if not url_ok(row.get("url") or "", https_only=False):
        res.errors.append(f"{where}: url inválida (http/https, com host, sem credenciais)")
    spu = row.get("sourcePageUrl")
    if spu is not None and not url_ok(spu, https_only=False):
        res.errors.append(f"{where}: sourcePageUrl inválida")
    h = row.get("sha256")
    if h is not None and not (isinstance(h, str) and SHA256_RE.match(h)):
        res.errors.append(f"{where}: Invalid package SHA-256")
    size = row.get("size")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        res.errors.append(f"{where}: size inválido")
    vols = row.get("volumes")
    if vols is not None:
        res.warnings.append(f"{where}: volumes (RAR) não comprovados no console — Gate 5")
        if not isinstance(vols, list) or len(vols) < 2:
            res.errors.append(f"{where}: Multipart choice needs a complete declared sequence")
        elif vols[0].get("url") != row.get("url") or vols[0].get("accessType") != row.get("accessType"):
            res.errors.append(f"{where}: pacote pai deve referenciar a primeira parte")


def read_archive(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        out = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.filename in out:
                raise ValueError(f"entrada duplicada no ZIP: {info.filename}")
            out[info.filename] = zf.read(info)
        return out


def check_archive(data: bytes, *, allow_placeholder_ids: bool = False) -> CheckResult:
    try:
        files = read_archive(data)
    except (zipfile.BadZipFile, ValueError) as e:
        return CheckResult(errors=[f"ZIP inválido: {e}"])
    return check_files(files, archive_size=len(data), allow_placeholder_ids=allow_placeholder_ids)
