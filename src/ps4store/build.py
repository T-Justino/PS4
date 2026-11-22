"""Compilador determinístico: Catalog canônico → .gssource (embedded-catalog-v1)."""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import sspi
from .catalog import Catalog, Title, normalize_search

ZIP_DATE = (2026, 1, 1, 0, 0, 0)     # timestamp fixo → ZIP reproduzível
SHARD_BUDGET = 1_000_000              # margem sob MAX_SHARD_BYTES (1.500.000)
SEARCH_TEXT_MAX = 2048


@dataclass
class BuildReport:
    source_id: str
    version: str
    published_titles: list[str] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    files: dict[str, dict] = field(default_factory=dict)
    artifact_sha256: str = ""
    content_sha256: str = ""
    warnings: list[str] = field(default_factory=list)
    identity_map: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sourceId": self.source_id, "version": self.version,
                "publishedTitles": self.published_titles, "excluded": self.excluded,
                "files": self.files, "artifactSha256": self.artifact_sha256,
                "contentSha256": self.content_sha256,
                "warnings": self.warnings,
                "identityMap": self.identity_map,
                "consoleCompatibility": "NAO_TESTADO — requer teste manual no PS4 (Gate 2)"}


def search_text(t: Title) -> str:
    parts = [t.name, *t.aliases]
    if t.audio_pt_br == "yes":
        parts.append("ptbr dublado portugues")
    if t.subtitles_pt_br == "yes":
        parts.append("ptbr legendado portugues")
    tokens: list[str] = []
    for tok in normalize_search(" ".join(parts)).split() + [t.title_id]:
        if tok not in tokens:
            tokens.append(tok)
    out = ""
    for tok in tokens:
        cand = f"{out} {tok}" if out else tok
        if len(cand) > SEARCH_TEXT_MAX:
            break
        out = cand
    return out


def _row(t: Title, p) -> dict:
    row = {"id": p.id, "titleId": t.title_id, "kind": p.kind, "accessType": p.access_type,
           "url": p.url}
    if p.hoster:
        row["hoster"] = p.hoster
    if p.label:
        row["label"] = p.label
    if p.source_page_url:
        row["sourcePageUrl"] = p.source_page_url
    if p.version:
        row["version"] = p.version
    if t.region:
        row["region"] = t.region
    for k in ("size", "sha256", "contentId", "requiredFirmware"):
        if k in p.extra:
            row[k] = p.extra[k]
    return row


def _names(prefix: str, base: str, n: int) -> list[str]:
    if n == 1:
        return [f"{prefix}{base}.json"]       # nome idêntico ao fixture aceito
    return [f"{prefix}{base}-{i:03d}.json" for i in range(1, n + 1)]


def compile_catalog(cat: Catalog) -> tuple[dict[str, bytes], BuildReport]:
    rep = BuildReport(cat.source_id, cat.source_version)
    rep.identity_map = [{"catalogKey": t.title_id, "realTitleId": t.real_title_id,
                         "realContentId": t.real_content_id, "probe": t.probe}
                        for t in cat.titles if t.catalog_key]
    ready: list[tuple[Title, list[dict]]] = []
    for t in sorted(cat.titles, key=lambda x: x.title_id):
        rows = []
        for p in t.packages:
            if not p.authorized:
                rep.excluded.append({"titleId": t.title_id, "packageId": p.id,
                                     "reason": "SEM_AUTORIZACAO_DE_DISTRIBUICAO"})
            else:
                rows.append(_row(t, p))
        if not rows:
            rep.excluded.append({"titleId": t.title_id, "packageId": None,
                                 "reason": "SEM_PACOTE_PUBLICAVEL (SSPI exige >=1)"})
            continue
        if len(rows) > sspi.MAX_ROWS_PER_TITLE:
            raise ValueError(f"{t.title_id}: mais de {sspi.MAX_ROWS_PER_TITLE} pacotes")
        ready.append((t, rows))
    if not ready:
        raise ValueError("nenhum título publicável: o SSPI rejeita catálogo sem títulos prontos")

    # shards de pacotes (guloso por bytes, ordem estável)
    groups: list[list[tuple[Title, list[dict]]]] = [[]]
    size = 0
    for item in ready:
        s = len(sspi.dumps({item[0].title_id: item[1]}))
        if groups[-1] and size + s > SHARD_BUDGET:
            groups.append([])
            size = 0
        groups[-1].append(item)
        size += s
    shard_names = _names("packages/", "items", len(groups))
    shard_of: dict[str, str] = {}
    files: dict[str, bytes] = {}
    for name, grp in zip(shard_names, groups):
        files[name] = sspi.dumps({"titles": {t.title_id: rows for t, rows in grp}})
        for t, _ in grp:
            shard_of[t.title_id] = name

    pages = [ready[i:i + sspi.MAX_TITLES_PER_INDEX]
             for i in range(0, len(ready), sspi.MAX_TITLES_PER_INDEX)]
    index_names = _names("index/", "titles", len(pages))
    for name, page in zip(index_names, pages):
        entries = []
        for t, rows in page:
            e = {"titleId": t.title_id, "name": t.name}
            if t.region:
                e["region"] = t.region
            kinds = [k for k in sspi.KINDS if any(r["kind"] == k for r in rows)]
            e.update({"packagesFile": shard_of[t.title_id], "releaseCount": len(rows),
                      "kinds": kinds, "searchText": search_text(t)})
            entries.append(e)
        files[name] = sspi.dumps({"titles": entries})
    if len(pages) > 1 or len(groups) > 1:
        rep.warnings.append("múltiplos índices/shards: formato não comprovado no console")

    releases = sum(len(r) for _, r in ready)
    catalog = {"format": sspi.CATALOG_FORMAT, "formatVersion": sspi.FORMAT_VERSION,
               "searchNormalization": sspi.SEARCH_NORMALIZATION,
               "indexFiles": index_names, "packageFiles": shard_names,
               "counts": {"titles": len(ready), "readyTitles": len(ready), "releases": releases,
                          "multipartGroups": 0, "unresolved": 0}}
    ordered = {"catalog.json": sspi.dumps(catalog)}
    ordered.update({n: files[n] for n in index_names})
    ordered.update({n: files[n] for n in shard_names})

    source = {"schema": sspi.SOURCE_SCHEMA, "id": cat.source_id, "name": cat.source_name,
              "description": cat.source_description, "version": cat.source_version,
              "engine": {"type": sspi.ENGINE_TYPE, "entryFile": sspi.ENTRY_FILE},
              "capabilities": list(sspi.CAPABILITIES),
              "files": [{"path": p, "size": len(b), "sha256": sspi.sha256(b)}
                        for p, b in ordered.items()]}
    out = {"source.json": sspi.dumps(source), **ordered}
    rep.published_titles = [t.title_id for t, _ in ready]
    rep.files = {p: {"size": len(b), "sha256": sspi.sha256(b)} for p, b in out.items()}
    return out, rep


def zip_files(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in files.items():          # ordem de inserção preservada
            info = zipfile.ZipInfo(path, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, data, compresslevel=6)
    return buf.getvalue()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
