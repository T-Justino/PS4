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
              refresh_links=a.refresh_links, out_research=Path(a.research_dir) / "research.json")
    c = res.report["counts"]
    for s in res.report["sources"]:
        print(f"fonte {s['source']} ({s['repo']}): {s['status']}" + (f" — {s['error']}" if s.get("error") else ""))
    print(f"descobertos={c['descobertos']} acessíveis={c['acessiveis']} pkg_verificados={c['pkgVerificados']} "
          f"compatíveis={c['compativeisSspi']} publicados={c['publicados']} novos={c['novos']} rejeitados={c['rejeitados']}")
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
    r.add_argument("--research-dir", default="local", help="catálogo de pesquisa e lista pessoal (NUNCA commitar; padrão local/)")
    r.add_argument("--recheck", action="store_true", help="ignora o cache de verificação e sonda tudo de novo")
    r.add_argument("--dry-run", action="store_true", help="não grava nada (estado, catálogo, relatório)")
    r.set_defaults(func=lambda a: cmd_run(a, net))
    a = ap.parse_args(argv)
    return a.func(a)
