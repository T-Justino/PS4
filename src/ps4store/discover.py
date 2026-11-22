"""1. DISCOVERY (+ orquestração do robô). Descoberta genérica de títulos, arquivos e URLs públicas em fontes consultáveis.

Fluxo (um comando: `python -m ps4store run`):
  DISCOVERY        fonte → Found (nome, ID da fonte, arquivo, URL, versão, tamanho, tipo, licença conhecida ou LICENSE_UNKNOWN)
  LINK_VALIDATION  (validation.py) Range 64 KiB, redirects, tipo, identidade lida do PKG
  PUBLICATION      (publication.py) compatibilidade SSPI + política → catálogo compartilhado e/ou lista pessoal de download direto
A descoberta NUNCA descarta por licença, autorização, categoria ou prefixo de ID: tudo o que a fonte expõe é registrado em `local/research.json`.
Só a etapa PUBLICATION decide o que pode ser oferecido. Sem banco de dados: estado em JSON. Sem crawler genérico: só APIs/índices públicos
de fontes configuradas (e consultas fixas à API pública de busca de repositórios do GitHub). Nunca baixa pacotes completos.
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
from .links import file_type, is_retail_style, multipart_info
from .model import *                                            # noqa: F401,F403  (Source, Config, Found, Entry, load_config, constantes)
from .model import (EXTRA_MAX, HEAD_BYTES, MAX_ASSETS_PER_SOURCE, RAR_MAGIC, REPO_RE, SOURCES_SCHEMA, STAGES, STATE_SCHEMA,
                    Config, ConfigError, Entry, Found, Source, load_config)
from .pkginfo import PkgError, parse_head                       # noqa: F401
from .publication import (assess, assess_compat, assess_install, build_canonical, dedupe_latest,   # noqa: F401
                          personal_links)
from .validation import _read_head, mark_duplicates, validate_link   # noqa: F401


# --------------------------------------------------------------------------- 1. DISCOVERY (conectores)

_LIC_HINT = re.compile(r"\b(open[- ]source|GPL(?:v?\d)?|MIT license|BSD|Apache|freeware|public domain|creative commons)\b", re.I)


def _license_hint(text) -> str | None:
    """Menção a licença na DESCRIÇÃO da fonte. É só pista: a licença continua LICENSE_UNKNOWN (não é declaração verificável)."""
    m = _LIC_HINT.search(str(text or ""))
    return f"a descrição menciona '{m.group(1)}'" if m else None


def _wanted_asset(src: Source, name: str) -> bool:
    """PKG e RAR dividido sempre; ZIP/7z/RAR únicos quando `all_types` (tipos de arquivo que o SSPI sabe usar)."""
    ft = file_type(name)
    return ft in ("pkg", "rar-multiparte") or (src.all_types and ft in ("rar", "zip", "7z"))


def discover_pkgzone(src: Source, net) -> list[Found]:
    """Lê o catálogo JSON público do PKG-Zone (o mesmo que o site carrega ao abrir): 1 requisição por execução.

    Registra TODAS as releases (ativas e, se `include_inactive`, antigas/inativas, marcadas em `sourceActive`). A URL guardada é o link ESTÁVEL `/download/{console}/{titleId}/{versão}`; o redirect para a URL
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
            if not isinstance(r, dict) or (r.get("active") is not True and not src.include_inactive):
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
                      "category": it.get("category"), "firmware": r.get("pv"), "sourceActive": r.get("active") is True,
                      "description": re.sub(r"\s+", " ", str(it.get("description") or ""))[:240],
                      "licenseHint": _license_hint(it.get("description"))}))
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
        if not (isinstance(name, str) and _wanted_asset(src, name) and isinstance(url, str) and isinstance(sha, str)):
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
            if not (isinstance(name, str) and isinstance(url, str) and _wanted_asset(src, name)):
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


def discover_search(src: Source, net) -> list[Found]:
    """Busca genérica por repositórios na API PÚBLICA de busca do GitHub (consultas fixas da configuração) e lista os arquivos das
    releases de cada repositório achado. É índice público oficial: sem login, sem raspagem, sem contornar nada. Descoberta apenas."""
    repos: dict[str, tuple[dict, str]] = {}
    for q in src.queries:
        data = net.get_json(f"{src.api_base}/search/repositories?q={quote(q)}&sort=stars&order=desc&per_page={min(max(src.max_repos, 1), 30)}")
        for it in (data.get("items") if isinstance(data, dict) else None) or []:
            fn = it.get("full_name") if isinstance(it, dict) else None
            if isinstance(fn, str) and REPO_RE.match(fn):
                repos.setdefault(fn, (it, q))
    found: list[Found] = []
    for fn, (it, q) in repos.items():
        try:
            releases = net.get_json(f"{src.api_base}/repos/{fn}/releases?per_page={min(max(src.max_releases, 1), 100)}")
        except Exception:
            continue                                  # repositório sem releases acessíveis: segue
        if not isinstance(releases, list):
            continue
        lic = (it.get("license") or {}).get("spdx_id") if isinstance(it.get("license"), dict) else None
        for rel in releases[:src.max_releases]:
            if not isinstance(rel, dict) or rel.get("draft") or (rel.get("prerelease") and not src.include_prereleases):
                continue
            for a in rel.get("assets") or []:
                name, url = a.get("name"), a.get("browser_download_url")
                if not (isinstance(name, str) and isinstance(url, str) and _wanted_asset(src, name)) or a.get("state") not in (None, "uploaded"):
                    continue
                size = a.get("size")
                found.append(Found(f"{src.id}#{fn}#{rel.get('id')}#{a.get('id')}", src, str(rel.get("tag_name") or ""),
                                   str(rel.get("html_url") or ""), str(rel.get("published_at") or ""), name, url,
                                   size if isinstance(size, int) and not isinstance(size, bool) else None,
                                   meta={"repo": fn, "license": lic, "stars": it.get("stargazers_count"), "archived": bool(it.get("archived")),
                                         "description": str(it.get("description") or "")[:240], "discoveredVia": q}))
                if len(found) >= MAX_ASSETS_PER_SOURCE * 3:
                    return found
    return found


def repo_license(src: Source, net) -> str | None:
    """Licença declarada do repositório (API pública). Qualquer falha ou ausência = desconhecida (LICENSE_UNKNOWN)."""
    try:
        d = net.get_json(f"{src.api_base}/repos/{src.repo}")
        lic = d.get("license") if isinstance(d, dict) else None
        return lic.get("spdx_id") if isinstance(lic, dict) else None
    except Exception:
        return None


# --------------------------------------------------------------------------- 1+2+3 juntas (compatibilidade com o código anterior)

def verify(found: Found, net, cfg: Config) -> Entry:
    """LINK_VALIDATION e depois PUBLICATION, cada uma na sua função/módulo."""
    e = validate_link(found, net)
    if e.title_id and e.stage == "pkg_verificado":
        assess(e, cfg)
    return e


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


CONNECTORS = {"github-releases": discover_github, "github-contents": discover_contents, "pkg-zone-catalog": discover_pkgzone,
              "github-search": discover_search}


def run(cfg: Config, net, *, out_gssource: Path, out_canonical: Path, out_report: Path, state_path: Path,
        dry_run: bool = False, now: str | None = None, recheck: bool = False, sleep=time.sleep,
        refresh_links: int = 0, out_research: Path | None = None, force_titles: frozenset = frozenset()) -> RunResult:
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
        if src.type in ("github-releases", "github-contents"):
            lic = repo_license(src, net)
            for f in found:
                f.meta.setdefault("license", lic)
        source_status.append({"source": src.id, "repo": src.repo, "status": "ok", "discovered": len(found), "type": src.type})
        found.sort(key=lambda f: f.meta.get("sourceActive") is False)      # ativas primeiro; inativas só com o orçamento incremental
        inactive_left = src.inactive_probe_budget
        probes = 0
        refresh_left = refresh_links          # enriquecimento incremental: re-sonda N itens em cache sem dados de link
        for f in found:
            seen = state["seen"].get(f.key) or {}
            cached = seen.get("check")
            if cached and (f.meta.get("catalogTitleId") in force_titles or cached.get("titleId") in force_titles):
                cached = None                      # re-sondagem pedida para este título (--probe-title)
            needs_link = cached and not cached.get("link") and not f.skip_reason and cached["stage"] != "descoberto"
            if needs_link and refresh_left > 0 and probes < src.max_probes:
                refresh_left -= 1
                cached = None
            if (cached and not recheck and cached["reason"] != "UNREACHABLE"
                    and _age_hours(cached["checkedAt"], now) < src.recheck_hours):
                e = Entry(f).load_cache(cached)
                e.restricted = is_retail_style(e.content_id, f.meta.get("category"))
                if e.title_id and e.stage in ("pkg_verificado", "compativel_sspi", "publicado"):
                    e = assess(e, cfg)               # PUBLICATION é reavaliada a cada execução, mesmo com o cache da validação
            elif f.skip_reason:
                e = verify(f, net, cfg)                       # sem rede
            elif probes >= src.max_probes:
                e = Entry(f).reject("PROBE_BUDGET", f"teto de {src.max_probes} sondagens por execução; fica para a próxima")
            elif f.meta.get("sourceActive") is False and inactive_left <= 0:
                e = Entry(f).reject("PROBE_BUDGET", "release inativa/antiga: registrada; o link é validado aos poucos (orçamento incremental)")
            else:
                if f.meta.get("sourceActive") is False:
                    inactive_left -= 1
                if probes and src.delay_seconds:
                    sleep(src.delay_seconds)
                probes += 1
                e = verify(f, net, cfg)
            e.is_new = f.key not in state["seen"]
            entries.append(e)

    mark_duplicates(entries)
    personal_links(entries, cfg)                         # PUBLICATION (instalação por link direto): marca install_ok/impeditivos
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
    report["rarSets"] = rar_sets(entries)
    if out_research is not None and not dry_run:
        write_research(out_research, entries, now, cfg)
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


def rar_sets(entries: list[Entry]) -> list[dict]:
    """Agrupa volumes `x.partN.rar` por fonte+conjunto: ordem, completude, tamanhos, acessibilidade e assinatura RAR."""
    groups: dict[tuple, list[Entry]] = {}
    for e in entries:
        mp = e.found.meta.get("multipart")
        if mp and mp.get("index") is not None:
            groups.setdefault((e.found.source.id, mp["set"]), []).append(e)
    out = []
    for (src, name), es in sorted(groups.items()):
        es.sort(key=lambda x: x.found.meta["multipart"]["index"])
        idx = [x.found.meta["multipart"]["index"] for x in es]
        top = max(idx)
        missing = sorted(set(range(1, top + 1)) - set(idx))
        dup = sorted({i for i in idx if idx.count(i) > 1})
        ok = all(x.stage == "acessivel" and x.reason == "ARCHIVE_MULTIPART" for x in es)
        total = sum(x.total_size or 0 for x in es)
        out.append({"source": src, "set": name, "volumes": len(es), "indexes": idx, "missing": missing, "duplicates": dup,
                    "allAccessible": ok, "complete": bool(not missing and not dup and len(es) >= 2 and ok), "totalBytes": total,
                    "parts": [{"index": x.found.meta["multipart"]["index"], "name": x.found.asset_name, "bytes": x.total_size,
                               "accessible": x.stage == "acessivel", "rangeOk": x.link.get("rangeOk"), "url": x.found.url} for x in es],
                    "note": "colar os links NA ORDEM (até 50 por vez); se os nomes forem reconhecidos o SSPI agrupa sozinho, senão marcar "
                            "'These links are parts of one RAR archive, in volume order'. Espaço de pico: arquivos + pacote extraído"})
    return out


def research_row(e: Entry) -> dict:
    """Uma linha do catálogo interno de pesquisa: tudo o que se sabe sobre o achado, sem filtro de licença/categoria/prefixo."""
    f = e.found
    st = e.status()
    auth = f.source.auth_for(e.title_id)
    return {"name": e.name or f.name_hint, "titleId": e.title_id or f.meta.get("catalogTitleId"), "contentId": e.content_id,
            "identityRead": bool(e.title_id), "version": e.version or f.tag, "sizeBytes": e.total_size or f.size,
            "source": f.source.id, "sourceType": f.source.type, "url": f.url, "fileType": file_type(f.asset_name), "kind": e.kind,
            "linkStatus": e.link.get("kind"), "rangeOk": e.link.get("rangeOk"), "temporaryRedirect": e.link.get("temporaryFinalUrl"),
            "redirects": e.link.get("redirects"), "redirectChain": e.link.get("chain"),
            "license": e.license["status"], "licenseSpdx": e.license["spdx"], "licenseHint": e.license["hint"],
            "authorization": (auth[0] if auth else None),
            "status": st, "sspiDownloadable": bool(e.link.get("sspiUsable")),
            "sspiCompat": st["sspiCompat"], "compatReasons": e.compat,
            "publicationAvailable": st["publication"] == "available", "publicationBlockers": e.blockers,
            "directInstallAvailable": st["directInstall"] == "available", "directInstallBlockers": e.install_blockers,
            "phase": e.phase, "rejectionReason": e.reason, "detail": e.detail, "restricted": e.restricted,
            "duplicateOf": e.duplicate_of, "category": f.meta.get("category"), "author": f.meta.get("author"),
            "firmware": f.meta.get("firmware"), "sourceActive": f.meta.get("sourceActive", True),
            "repo": f.meta.get("repo"), "stars": f.meta.get("stars"), "discoveredVia": f.meta.get("discoveredVia"),
            "description": f.meta.get("description"), "linkNotes": e.link.get("notes") or []}



def write_research(path: Path, entries: list[Entry], now: str, cfg: Config | None = None) -> None:
    rows = [research_row(e) for e in entries]
    sets = rar_sets(entries)
    doc = {"generatedAt": now, "aviso": "USO PESSOAL. Pesquisa de metadados e disponibilidade; não é publicação. Não commitar nem hospedar este arquivo.",
           "total": len(rows), "rarSets": sets, "entries": rows}
    write_atomic(path, (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode())
    pl = personal_links(entries, cfg)
    lines = ["# USO PESSOAL: cole estes links no SSPI (Downloads → tocar no touchpad → colar link, ou a página do celular).",
             "# Cada link vai direto à origem; nada é hospedado aqui. Excluídos: IDs/categorias de aparência comercial, links sem Range/identidade.",
             "# Não redistribua esta lista."]
    for e in sorted(pl, key=lambda x: (x.name or "", x.version or "")):
        lines.append(f"# {e.name} {e.version or ''} [{e.title_id}] {e.total_size or '?'} B")
        lines.append(e.found.url)
    for st in sets:
        if st["complete"]:
            lines.append(f"# RAR dividido {st['set']}: {st['volumes']} volumes, {st['totalBytes']} B. Cole TODOS, nesta ordem:")
            lines += [p["url"] for p in st["parts"]]
    write_atomic(path.with_name("links-sspi.txt"), ("\n".join(lines) + "\n").encode())


def status_matrix(entries: list[Entry]) -> dict:
    """As cinco perguntas, separadas (contagens): encontrado / link acessível / arquivo identificado / compatível / disponível."""
    sts = [e.status() for e in entries]
    n = len(sts)
    c = collections.Counter
    return {"encontrados": n,
            "linkAcessivel": dict(c(str(s["linkAccessible"]) for s in sts)),
            "arquivoIdentificado": dict(c(str(s["fileIdentified"]) for s in sts)),
            "compatibilidadeSspi": dict(c(s["sspiCompat"] for s in sts)),
            "publicacaoEmCatalogo": dict(c(s["publication"] for s in sts)),
            "instalacaoPorLinkDireto": dict(c(s["directInstall"] for s in sts)),
            "licencaDesconhecida": sum(1 for e in entries if e.license["status"] == "LICENSE_UNKNOWN"),
            "licencaConhecida": sum(1 for e in entries if e.license["status"] == "KNOWN"),
            "porFonte": {src: dict(c(("link-ok" if e.status()["linkAccessible"] else "sem-link-validado") for e in entries
                                     if e.found.source.id == src)) | {"encontrados": sum(1 for e in entries if e.found.source.id == src)}
                         for src in sorted({e.found.source.id for e in entries})}}


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
                       "matriz": status_matrix(entries),
                       "links": {"classificados": sum(1 for e in entries if e.link),
                                 "sspiBaixaveis": sum(1 for e in entries if e.link.get("sspiUsable")),
                                 "redirectTemporario": sum(1 for e in entries if e.link.get("temporaryFinalUrl")),
                                 "semRange": sum(1 for e in entries if e.link and e.link.get("rangeOk") is False and e.link.get("sspiUsable")),
                                 "tipos": dict(collections.Counter(e.link.get("kind") for e in entries if e.link))},
                       "restritos": sum(1 for e in entries if e.restricted),
                       "duplicados": sum(1 for e in entries if e.duplicate_of),
                       "listaPessoal": len(personal_links(entries, cfg)),
                       "rejeitados": sum(1 for e in entries if e.reason), "motivos": reasons},
            "catalogUpdated": wrote, "catalogError": compile_error,
            "entries": [e.to_dict() for e in entries]}


def _sym(v) -> str:
    return {True: "✓", False: "✗", None: "—", "compatible": "✓", "incompatible": "✗", "available": "✓", "blocked": "✗",
            "not-evaluated": "—"}.get(v, str(v))


def render_markdown(r: dict) -> str:
    c, m = r["counts"], r["counts"]["matriz"]
    la = m["linkAcessivel"]; fi = m["arquivoIdentificado"]; cs = m["compatibilidadeSspi"]
    pc = m["publicacaoEmCatalogo"]; ins = m["instalacaoPorLinkDireto"]
    L = [f"# Relatório de descoberta: {r['generatedAt']}", "", f"> {r['note']}", "",
         "A **descoberta registra tudo o que a fonte expõe** (sem filtrar por licença, autorização, categoria ou prefixo de ID). "
         "Só a etapa de **publicação** decide o que pode ser oferecido; descobrir uma URL não é autorização de uso ou distribuição.", "",
         "## Cinco perguntas, separadas", "",
         "| Pergunta | Sim | Não | Não avaliado |", "|---|---|---|---|",
         f"| **Encontrado** (descoberta) | {m['encontrados']} | 0 | — |",
         f"| **Link acessível** (validação) | {la.get('True', 0)} | {la.get('False', 0)} | {la.get('None', 0)} |",
         f"| **Arquivo identificado** (ID lido do PKG) | {fi.get('True', 0)} | {fi.get('False', 0)} | {fi.get('None', 0)} |",
         f"| **Compatível com o SSPI** (regras técnicas) | {cs.get('compatible', 0)} | {cs.get('incompatible', 0)} | {cs.get('not-evaluated', 0)} |",
         f"| **Disponível em catálogo publicável** (política) | {pc.get('available', 0)} | {pc.get('blocked', 0)} | {pc.get('not-evaluated', 0)} |",
         f"| **Disponível por link direto** (lista pessoal) | {ins.get('available', 0)} | {ins.get('blocked', 0)} | {ins.get('not-evaluated', 0)} |", "",
         f"Licença: **{m['licencaConhecida']} conhecida(s)**, **{m['licencaDesconhecida']} `LICENSE_UNKNOWN`** (informativo: não elimina o resultado; também não autoriza).", "",
         "| Descobertos | Acessíveis | PKG verificado | Compatíveis (regras) | Publicáveis | Novos | Com motivo de bloqueio |",
         "|---|---|---|---|---|---|---|",
         f"| {c['descobertos']} | {c['acessiveis']} | {c['pkgVerificados']} | {c['compativeisSspi']} | {c['publicados']} | {c['novos']} | {c['rejeitados']} |", ""]
    L.append("## Fontes")
    for s in r["sources"]:
        pf = m["porFonte"].get(s["source"], {})
        L.append(f"- `{s['source']}` ({s.get('type', '')} {s['repo']}): {s['status']}"
                 + (f", {s['discovered']} arquivos" if 'discovered' in s else "")
                 + (f" · link validado em {pf.get('link-ok', 0)}" if pf else "")
                 + (f" — {s['error']}" if s.get("error") else ""))
    L += ["", f"Catálogo atualizado: **{'sim' if r['catalogUpdated'] else 'não'}**" + (f" — {r['catalogError']}" if r.get("catalogError") else "")]
    if r.get("artifact"):
        a = r["artifact"]
        L.append(f"Artefato: `{a['path']}` v{a['version']} · títulos: {', '.join(a['titles'])} · contentSha256 `{a['contentSha256'][:16]}…`")
    L += ["", "## Entradas", "",
          "Legenda: ✓ sim · ✗ não · — não avaliado. Colunas: Link acessível · Arquivo identificado · Compatível SSPI · Catálogo · Link direto.", "",
          "| Novo | Link | ID | SSPI | Catálogo | Direto | Licença | Título | Arquivo | Motivo principal |", "|---|---|---|---|---|---|---|---|---|---|"]
    for e in r["entries"]:
        st = e["status"]
        lic = "conhecida" if e["license"]["status"] == "KNOWN" else "LICENSE_UNKNOWN"
        L.append(f"| {'sim' if e['isNew'] else ''} | {_sym(st['linkAccessible'])} | {_sym(st['fileIdentified'])} | {_sym(st['sspiCompat'])} | "
                 f"{_sym(st['publication'])} | {_sym(st['directInstall'])} | {lic} | {e['titleId'] or ''} | {e['asset']} ({e['release']}) | "
                 f"{('`' + e['reason'] + '` ') if e['reason'] else ''}{e['detail']} |")
    return "\n".join(L) + "\n"
