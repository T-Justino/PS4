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
        cat = load(a.input)
        files, rep = compile_catalog(cat)
    except CatalogError as e:
        for msg in e.errors:
            print(f"ERRO  {msg}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 1
    data = zip_files(files)
    res = sspi.check_archive(data)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ps4store", description="PS4 Store BR — gerador .gssource")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="gera .gssource a partir de catálogo canônico JSON")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--report", help="grava relatório JSON do build")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="valida um .gssource contra as regras conhecidas do SSPI")
    c.add_argument("file")
    c.add_argument("--allow-placeholder", action="store_true",
                   help="aceita IDs fictícios (só para inspecionar fixtures antigos)")
    c.set_defaults(func=cmd_check)
    a = ap.parse_args(argv)
    return a.func(a)
