"""Leitura somente-leitura do início de um PKG do PS4 (cabeçalho + param.sfo), a partir de bytes já baixados via Range."""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

MAGIC = b"\x7fCNT"
SFO_ENTRY_ID = 0x1000
CONTENT_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{4}-([A-Z]{4}[0-9]{5})_[0-9]{2}-[A-Z0-9_-]{16}$")
KIND_BY_CATEGORY = {"gd": "base", "gp": "update", "ac": "dlc"}


class PkgError(ValueError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code


@dataclass
class PkgHead:
    content_id: str
    title_id: str            # ID embutido no Content ID (o que o SSPI compara)
    sfo: dict
    kind: str                # base | update | dlc | unknown (pela CATEGORY do param.sfo)


def parse_sfo(b: bytes) -> dict:
    if b[:4] != b"\x00PSF" or len(b) < 20:
        raise PkgError("BAD_SFO", "param.sfo sem magic PSF")
    key_off, data_off, count = struct.unpack_from("<III", b, 8)
    if count > 256:
        raise PkgError("BAD_SFO", "param.sfo com entradas demais")
    out: dict = {}
    try:
        for i in range(count):
            koff, fmt, length, _mx, doff = struct.unpack_from("<HHIII", b, 20 + i * 16)
            key = b[key_off + koff:b.index(b"\x00", key_off + koff)].decode("ascii")
            raw = b[data_off + doff:data_off + doff + length]
            out[key] = int.from_bytes(raw[:4], "little") if fmt == 0x0404 else raw.split(b"\x00")[0].decode("utf-8")
    except (struct.error, ValueError, UnicodeDecodeError) as e:
        raise PkgError("BAD_SFO", f"param.sfo ilegível ({e})")
    return out


def parse_head(data: bytes) -> PkgHead:
    if data[:4] != MAGIC:
        raise PkgError("NOT_PKG", "magic PKG ausente (7F 43 4E 54)")
    if len(data) < 0x64:
        raise PkgError("TRUNCATED", "cabeçalho incompleto")
    try:
        content_id = data[0x40:0x40 + 36].decode("ascii")
    except UnicodeDecodeError:
        raise PkgError("BAD_CONTENT_ID", "Content ID não ASCII")
    m = CONTENT_ID_RE.match(content_id)
    if not m:
        raise PkgError("BAD_CONTENT_ID", f"Content ID fora do formato: {content_id!r}")
    count, table = struct.unpack_from(">I", data, 0x10)[0], struct.unpack_from(">I", data, 0x18)[0]
    if count == 0 or count > 512 or table + count * 32 > len(data):
        raise PkgError("SFO_OUTSIDE_WINDOW", "tabela de entradas fora da janela baixada")
    sfo = None
    for i in range(count):
        eid, _fn, _f1, _f2, off, size = struct.unpack_from(">IIIIII", data, table + i * 32)
        if eid == SFO_ENTRY_ID:
            if off + size > len(data):
                raise PkgError("SFO_OUTSIDE_WINDOW", "param.sfo fora da janela baixada")
            sfo = parse_sfo(data[off:off + size])
    if sfo is None:
        raise PkgError("BAD_SFO", "param.sfo não encontrado")
    return PkgHead(content_id, m.group(1), sfo, KIND_BY_CATEGORY.get(str(sfo.get("CATEGORY")), "unknown"))
