"""CLI: `build` (canônico → .gssource validado) e `check` (valida .gssource)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import sspi
from .build import compile_catalog, write_atomic, zip_files
from .catalog import CatalogError, load


def _print(res: sspi.CheckResult) -> None:
    for e in res.errors:
        print(f"ERRO  {e}", file=sys.stderr)
    for w in res.warnings:
        print(f"AVISO {w}", file=sys.stderr)


def cmd_build(a) -> int:
    try:
        cat = load(a.input, allow_synthetic=a.allow_synthetic_probe)
        files, rep = compile_catalog(cat)
    except CatalogError as e:
        for msg in e.errors:
            print(f"ERRO  {msg}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 1
    data = zip_files(files)
    res = sspi.check_archive(data, allow_placeholder_ids=any(t.probe for t in cat.titles))
    _print(res)
    if not res.ok:
        print("build abortado: artefato não passou no check; nada foi escrito", file=sys.stderr)
        return 1
    rep.artifact_sha256 = sspi.sha256(data)
    rep.content_sha256 = sspi.content_sha256(data)
    rep.warnings.extend(res.warnings)
    out = Path(a.output)
    write_atomic(out, data)
    if a.report:
        write_atomic(Path(a.report),
                     (json.dumps(rep.to_dict(), ensure_ascii=False, indent=2) + "\n").encode())
    print(f"OK {out} ({len(data)} bytes) sha256={rep.artifact_sha256}")
    print(f"   conteúdo sha256={rep.content_sha256}  (estável entre ambientes)")
    print(f"   títulos publicados: {', '.join(rep.published_titles)}")
    for ex in rep.excluded:
        print(f"   excluído: {ex['titleId']} {ex['packageId'] or ''} → {ex['reason']}")
    for m in rep.identity_map:
        print(f"   chave {m['catalogKey']} → identidade real {m['realTitleId']}" + (" [PROBE]" if m["probe"] else ""))
    print("   compatibilidade com o console: NÃO TESTADA (Gate 2)")
    return 0


def cmd_check(a) -> int:
    try:
        data = Path(a.file).read_bytes()
    except OSError as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 1
    res = sspi.check_archive(data, allow_placeholder_ids=a.allow_placeholder)
    _print(res)
    line = ("OK" if res.ok else "FALHOU") + f" {a.file} sha256={sspi.sha256(data)}"
    if res.ok:
        line += f"\n   conteúdo sha256={sspi.content_sha256(data)}  (estável entre ambientes)"
    print(line)
    return 0 if res.ok else 1


def cmd_run(a, net=None) -> int:
    """Descoberta → verificação → catálogo → .gssource, em um comando."""
    import os
    from .discover import ConfigError, load_config, run
    from .net import UrllibNet
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        for msg in str(e).splitlines():
            print(f"ERRO  {msg}", file=sys.stderr)
        return 1
    net = net or UrllibNet(token=os.environ.get("GITHUB_TOKEN"))
    out_dir = Path(a.out_dir)
    res = run(cfg, net, out_gssource=out_dir / "ps4storebr-auto.gssource",
              out_canonical=Path(a.canonical), out_report=out_dir / "discovery.report.json",
              state_path=Path(a.state), dry_run=a.dry_run, recheck=a.recheck,
              refresh_links=a.refresh_links, force_titles=frozenset(t.upper() for t in a.probe_title), out_research=Path(a.research_dir) / "research.json")
    c = res.report["counts"]
    for s in res.report["sources"]:
        print(f"fonte {s['source']} ({s['repo']}): {s['status']}" + (f" — {s['error']}" if s.get("error") else ""))
    print(f"descobertos={c['descobertos']} acessíveis={c['acessiveis']} pkg_verificados={c['pkgVerificados']} "
          f"compatíveis={c['compativeisSspi']} publicados={c['publicados']} novos={c['novos']} rejeitados={c['rejeitados']}")
    m = c["matriz"]
    print("matriz (sim/não/não avaliado): "
          f"encontrados={m['encontrados']} | link acessível {m['linkAcessivel'].get('True', 0)}/{m['linkAcessivel'].get('False', 0)}/{m['linkAcessivel'].get('None', 0)}"
          f" | arquivo identificado {m['arquivoIdentificado'].get('True', 0)}/{m['arquivoIdentificado'].get('False', 0)}/{m['arquivoIdentificado'].get('None', 0)}"
          f" | SSPI compatível {m['compatibilidadeSspi'].get('compatible', 0)}/{m['compatibilidadeSspi'].get('incompatible', 0)}/{m['compatibilidadeSspi'].get('not-evaluated', 0)}"
          f" | catálogo {m['publicacaoEmCatalogo'].get('available', 0)}/{m['publicacaoEmCatalogo'].get('blocked', 0)}/{m['publicacaoEmCatalogo'].get('not-evaluated', 0)}"
          f" | link direto {m['instalacaoPorLinkDireto'].get('available', 0)}/{m['instalacaoPorLinkDireto'].get('blocked', 0)}/{m['instalacaoPorLinkDireto'].get('not-evaluated', 0)}"
          f" | licença desconhecida={m['licencaDesconhecida']} conhecida={m['licencaConhecida']}")
    L = c["links"]
    print(f"links: sspi_baixáveis={L['sspiBaixaveis']} redirect_temporário={L['redirectTemporario']} restritos={c['restritos']} "
          f"duplicados={c['duplicados']} lista_pessoal={c['listaPessoal']}")
    print("fases: " + " · ".join(f"{k}={v}" for k, v in c["fases"].items()))
    for e in res.report["entries"]:
        print(f"  {'NOVO ' if e['isNew'] else '     '}{e['fase']:<10} {e['stage']:<16} {e['asset']} ({e['release']})"
              + (f" → rejeitado {e['reason']}: {e['detail']}" if e["rejected"] else f" → {e['titleId']}"))
    if res.wrote_catalog:
        print(f"catálogo atualizado: {res.report['artifact']['path']} v{res.report['artifact']['version']}" + (" [dry-run: nada foi gravado]" if a.dry_run else ""))
    else:
        print("catálogo NÃO atualizado" + (f": {res.report['catalogError']}" if res.report["catalogError"] else ": nenhuma entrada publicável (artefato anterior mantido)"))
    return 3 if res.critical_down else 0     # 3 = fonte crítica fora do ar (o workflow fica vermelho, o catálogo anterior fica)


def search_rows(rows: list[dict], terms: list[str], *, ftype: str | None = None, source: str | None = None,
                only: str | None = None, known_license: bool | None = None) -> list[dict]:
    """Busca no catálogo interno de pesquisa por nome, ID (CUSA ou outro), Content ID, URL, fonte, autor, descrição e tipo de arquivo."""
    out = []
    for r in rows:
        hay = " ".join(str(r.get(k) or "") for k in ("name", "titleId", "contentId", "url", "source", "author", "description", "repo")).casefold()
        if not all(t.casefold() in hay for t in terms):
            continue
        if ftype and r.get("fileType") != ftype:
            continue
        if source and r.get("source") != source:
            continue
        if known_license is not None and (r.get("license") == "KNOWN") != known_license:
            continue
        flt = {"compatible": r.get("sspiCompat") == "compatible", "incompatible": r.get("sspiCompat") == "incompatible",
               "available": bool(r.get("publicationAvailable")), "blocked": r.get("status", {}).get("publication") == "blocked",
               "installable": bool(r.get("directInstallAvailable")), "accessible": bool(r.get("status", {}).get("linkAccessible")),
               "identified": bool(r.get("identityRead"))}
        if only and not flt.get(only, False):
            continue
        out.append(r)
    return out


def cmd_resume_check(a, net=None) -> int:
    """Checagem leve de prontidão para retomada/arquivos grandes (até 3 requisições de 64 KiB por título; limite de títulos)."""
    from .net import UrllibNet
    from .validation import resume_check
    try:
        doc = json.loads(Path(a.research).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"ERRO  catálogo de pesquisa não encontrado em {a.research}: rode `ps4store run` primeiro", file=sys.stderr)
        return 1
    want = {t.upper() for t in a.title}

    def eligible(r) -> bool:
        if r["fileType"] not in ("pkg", "rar-multiparte") or not r.get("sizeBytes") or r.get("sourceActive") is False:
            return False                      # releases inativas: o servidor as recusa (403), não são candidatas
        if a.source and r.get("source") != a.source:
            return False
        if a.source and not want:
            return True
        if want:
            return (r["titleId"] or "").upper() in want
        return bool(r.get("directInstallAvailable")) and r["sizeBytes"] >= a.min_mb * 1e6

    rows = [r for r in doc["entries"] if eligible(r)]
    rows.sort(key=lambda r: -r["sizeBytes"])
    rows = rows[:max(1, min(a.limit, 20))]
    net = net or UrllibNet()
    for r in rows:
        res = resume_check(r["url"], r["sizeBytes"], net)
        print(f"{(r['name'] or r['url'].rsplit('/', 1)[-1])[:34]:34} v{str(r.get('version'))[:6]:6} {r['sizeBytes'] / 1e6:8.1f}MB  range={'ok' if res['rangeHonored'] else 'NAO'} "
              f"tamanho={'estável' if res['totalStable'] else 'INSTÁVEL'} validador={res['validators']}{'' if res['etagStable'] else ' (ETag MUDA)'} "
              f"=> {'PRONTO' if res['ready'] else 'ATENÇÃO'}")
        for n in res["notes"]:
            print(f"    - {n}")
    if not rows:
        print("nenhum título elegível (use --title ID ou diminua --min-mb)")
    return 0


def cmd_search(a) -> int:
    try:
        doc = json.loads(Path(a.research).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"ERRO  catálogo de pesquisa não encontrado em {a.research}: rode `ps4store run` primeiro", file=sys.stderr)
        return 1
    rows = search_rows(doc["entries"], a.terms, ftype=a.type, source=a.source, only=a.only,
                       known_license=None if a.license is None else a.license == "known")
    rows = [r for r in rows if (a.min_mb is None or (r.get("sizeBytes") or 0) >= a.min_mb * 1e6)
            and (a.max_mb is None or (r.get("sizeBytes") or 0) <= a.max_mb * 1e6)]
    if a.sort == "size":
        rows.sort(key=lambda r: -(r.get("sizeBytes") or 0))
    for r in rows[:a.limit]:
        mb = f"{(r['sizeBytes'] or 0) / 1e6:.1f}MB"
        st = r["status"]
        print(f"{(r['name'] or '?')[:34]:34} {(r['titleId'] or '?'):10} v{str(r['version'] or '?')[:8]:8} {mb:>9} {r['fileType']:14} "
              f"link={_s(st['linkAccessible'])} id={_s(st['fileIdentified'])} sspi={st['sspiCompat'][:4]} cat={st['publication'][:5]} "
              f"direto={st['directInstall'][:5]} {r['license']}  [{r['source']}]")
        if a.urls:
            print(f"    {r['url']}")
    print(f"-- {len(rows)} resultado(s)" + (f" (mostrando {a.limit})" if len(rows) > a.limit else ""))
    return 0


def _s(v) -> str:
    return {True: "ok", False: "NAO", None: "--"}[v]


def main(argv: list[str] | None = None, *, net=None) -> int:
    ap = argparse.ArgumentParser(prog="ps4store", description="PS4 Store BR — gerador .gssource")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="gera .gssource a partir de catálogo canônico JSON")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--report", help="grava relatório JSON do build")
    b.add_argument("--allow-synthetic-probe", action="store_true",
                   help="só para reproduzir sondas históricas T4–T7; chaves sintéticas não são produção")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="valida um .gssource contra as regras conhecidas do SSPI")
    c.add_argument("file")
    c.add_argument("--allow-placeholder", action="store_true",
                   help="aceita IDs fictícios (só para inspecionar fixtures antigos)")
    c.set_defaults(func=cmd_check)
    r = sub.add_parser("run", help="Gate 3: descobre, verifica links e gera o .gssource (um comando)")
    r.add_argument("--config", default="config/sources.json")
    r.add_argument("--out-dir", default="dist/auto")
    r.add_argument("--canonical", default="data/generated/auto-catalog.json")
    r.add_argument("--state", default="data/state/discovery-state.json")
    r.add_argument("--refresh-links", type=int, default=0, metavar="N",
                   help="re-sonda até N itens em cache sem dados de link (enriquecimento incremental)")
    r.add_argument("--probe-title", action="append", default=[], metavar="ID",
                   help="re-sonda só este título (repetível), ignorando o cache; para validar candidatos sem sondagem em massa")
    r.add_argument("--research-dir", default="local", help="catálogo de pesquisa e lista pessoal (NUNCA commitar; padrão local/)")
    r.add_argument("--recheck", action="store_true", help="ignora o cache de verificação e sonda tudo de novo")
    r.add_argument("--dry-run", action="store_true", help="não grava nada (estado, catálogo, relatório)")
    r.set_defaults(func=lambda a: cmd_run(a, net))
    q = sub.add_parser("search", help="busca no catálogo interno de pesquisa (local/research.json): nome, ID, tipo de arquivo, status")
    q.add_argument("terms", nargs="*", help="termos (todos devem aparecer em nome/ID/Content ID/URL/fonte/autor/descrição)")
    q.add_argument("--type", choices=["pkg", "rar", "rar-multiparte", "zip", "7z"], help="tipo de arquivo")
    q.add_argument("--source", help="id da fonte")
    q.add_argument("--only", choices=["accessible", "identified", "compatible", "incompatible", "available", "blocked", "installable"])
    q.add_argument("--license", choices=["known", "unknown"])
    q.add_argument("--research", default="local/research.json")
    q.add_argument("--limit", type=int, default=40)
    q.add_argument("--min-mb", type=float)
    q.add_argument("--max-mb", type=float)
    q.add_argument("--sort", choices=["size"], help="ordena do maior para o menor")
    q.add_argument("--urls", action="store_true", help="mostra também a URL")
    q.set_defaults(func=cmd_search)
    rc = sub.add_parser("resume-check", help="prontidão para retomada/arquivos grandes: Range em offsets, tamanho e ETag estáveis (≤3 requisições de 64 KiB por título)")
    rc.add_argument("--title", action="append", default=[], metavar="ID", help="título (repetível); sem isto, os maiores instaláveis")
    rc.add_argument("--source", help="só esta fonte (ex.: own-rar para checar todos os volumes de um RAR dividido)")
    rc.add_argument("--min-mb", type=float, default=100)
    rc.add_argument("--limit", type=int, default=5, help="máximo de títulos (teto 20)")
    rc.add_argument("--research", default="local/research.json")
    rc.set_defaults(func=lambda a: cmd_resume_check(a, net))
    a = ap.parse_args(argv)
    return a.func(a)
