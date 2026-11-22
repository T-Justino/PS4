#!/usr/bin/env python3
"""Verifica os metadados de um PKG do PS4 ANTES de testar no console (somente leitura, stdlib).

Confere: magic PKG, Content ID do cabeçalho, param.sfo embutido (TITLE_ID, CONTENT_ID, CATEGORY) e a
consistência entre eles e os valores esperados. Uso: verify_pkg.py arquivo.pkg [--title-id CUSA95417] [--content-id ...]
Sai com código 1 se algo não bater. Não faz parte do Gate 3; é só a verificação do T8.
"""
import argparse
import hashlib
import re
import struct
import sys

MAGIC = b"\x7fCNT"
SFO_ID = 0x1000
CONTENT_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{4}-([A-Z]{4}[0-9]{5})_[0-9]{2}-[A-Z0-9_-]{16}$")


def parse_sfo(b: bytes) -> dict:
    if b[:4] != b"\x00PSF":
        raise ValueError("param.sfo sem magic PSF")
    key_off, data_off, count = struct.unpack_from("<III", b, 8)
    out = {}
    for i in range(count):
        koff, fmt, length, maxlen, doff = struct.unpack_from("<HHIII", b, 20 + i * 16)
        end = b.index(b"\x00", key_off + koff)
        key = b[key_off + koff:end].decode()
        raw = b[data_off + doff:data_off + doff + length]
        out[key] = int.from_bytes(raw[:4], "little") if fmt == 0x0404 else raw.split(b"\x00")[0].decode("utf-8")
    return out


def read_pkg(path: str) -> dict:
    d = open(path, "rb").read()
    if d[:4] != MAGIC:
        raise ValueError("magic PKG ausente (esperado 7F 43 4E 54)")
    content_id = d[0x40:0x40 + 36].decode("ascii")
    count = struct.unpack_from(">I", d, 0x10)[0]
    table = struct.unpack_from(">I", d, 0x18)[0]
    sfo = None
    for i in range(count):
        eid, _fn, _f1, _f2, off, size = struct.unpack_from(">IIIIII", d, table + i * 32)
        if eid == SFO_ID:
            sfo = parse_sfo(d[off:off + size])
    if sfo is None:
        raise ValueError("param.sfo não encontrado na tabela de entradas")
    return {"size": len(d), "sha256": hashlib.sha256(d).hexdigest(), "headerContentId": content_id, "sfo": sfo}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--title-id")
    ap.add_argument("--content-id")
    a = ap.parse_args()
    info = read_pkg(a.pkg)
    sfo, cid = info["sfo"], info["headerContentId"]
    print(f"arquivo         {a.pkg}\ntamanho         {info['size']} bytes\nsha256          {info['sha256']}")
    print(f"content ID (cabeçalho) {cid}")
    for k in ("TITLE", "TITLE_ID", "CONTENT_ID", "CATEGORY", "APP_TYPE", "VERSION", "APP_VER"):
        print(f"param.sfo {k:<10} {sfo.get(k)}")
    errs = []
    m = CONTENT_ID_RE.match(cid)
    if not m:
        errs.append("Content ID do cabeçalho fora do formato XX0000-AAAA00000_00-LABEL16")
    if sfo.get("CONTENT_ID") != cid:
        errs.append(f"CONTENT_ID do param.sfo ({sfo.get('CONTENT_ID')}) != cabeçalho ({cid})")
    if m and sfo.get("TITLE_ID") != m.group(1):
        errs.append(f"TITLE_ID do param.sfo ({sfo.get('TITLE_ID')}) != ID embutido no Content ID ({m.group(1)})")
    if a.title_id and sfo.get("TITLE_ID") != a.title_id:
        errs.append(f"TITLE_ID esperado {a.title_id}, encontrado {sfo.get('TITLE_ID')}")
    if a.content_id and cid != a.content_id:
        errs.append(f"Content ID esperado {a.content_id}, encontrado {cid}")
    for e in errs:
        print("ERRO", e, file=sys.stderr)
    print("OK: titleId, param.sfo e Content ID consistentes" if not errs else "FALHOU")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
