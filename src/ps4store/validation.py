"""2. LINK_VALIDATION: o link funciona? é o arquivo certo? qual a identidade real? Sem política de publicação.

Uma requisição `Range` de 64 KiB por link (mais, no máximo, uma faixa pequena para o `param.sfo` de PKGs grandes); nunca o arquivo inteiro.
Registra redirects, URL assinada/temporária, suporte a Range, tipo de arquivo, tamanho do servidor e a identidade (Content ID/TITLE_ID) do PKG.
O resultado é um Entry com `link`, `title_id`, `content_id`, `kind`... Falhas técnicas (404, HTML, tamanho divergente, ID divergente) ficam
registradas, não somem. Nada aqui consulta autorização, licença, categoria ou prefixo de ID: isso é PUBLICATION.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .links import classify_link, file_type, is_retail_style, multipart_info
from .model import EXTRA_MAX, HEAD_BYTES, RAR_MAGIC, Entry, Found
from .pkginfo import PkgError, parse_head

ARCHIVE_MAGIC = {"rar": RAR_MAGIC, "rar-multiparte": RAR_MAGIC, "zip": (b"PK\x03\x04", b"PK\x05\x06"), "7z": (b"7z\xbc\xaf\x27\x1c",)}


def _read_head(found: Found, pr, net):
    """parse_head sobre os 64 KiB; se a tabela/param.sfo estiverem além, lê UMA faixa pequena extra (nunca o arquivo)."""
    data = pr.head
    for _ in range(2):
        try:
            return parse_head(data)
        except PkgError as ex:
            if ex.code != "SFO_OUTSIDE_WINDOW" or not ex.need or ex.need[1] > EXTRA_MAX:
                raise
            a, b = ex.need
            p2 = net.probe(found.url, b - a, a)
            if not p2.ok or len(p2.head) < b - a:
                raise PkgError("SFO_OUTSIDE_WINDOW", "param.sfo além da janela e a 2ª faixa não veio")
            buf = bytearray(max(len(data), b))
            buf[:len(data)] = data
            buf[a:b] = p2.head[:b - a]
            data = bytes(buf)
    return parse_head(data)




def validate_link(found: Found, net) -> Entry:
    e = Entry(found)
    ftype = file_type(found.asset_name)
    mp = multipart_info(found.asset_name)
    if mp:
        found.meta["multipart"] = mp
    if found.skip_reason and found.skip_reason != "ARCHIVE_MULTIPART":
        return e.reject(found.skip_reason, f"{found.meta.get('console')}: fora do alvo (PS4); não sondado")
    archive = ftype != "pkg"
    # 1) acessível? (uma requisição Range de 64 KiB; nunca o pacote inteiro)
    pr = net.probe(found.url, HEAD_BYTES)
    e.link = classify_link(pr)
    if archive and pr.ok:
        magic = ARCHIVE_MAGIC.get(ftype)
        if magic and not pr.head.startswith(magic):
            return e.reject("NOT_RAR" if "rar" in ftype else "NOT_ARCHIVE", f"{found.asset_name}: sem a assinatura esperada de {ftype}")
        e.total_size = pr.total_size if pr.total_size is not None else found.size
        e.stage = "acessivel"
        if mp:
            return e.reject("ARCHIVE_MULTIPART", f"RAR dividido ({mp['set']}, volume {mp['index']}): o SSPI suporta (volumes em ordem), "
                            "mas a publicação multiparte em catálogo é o Gate 5; usar o caminho de download direto")
        return e.reject("ARCHIVE_NOT_INSPECTED", f"{ftype.upper()} único: assinatura ok; a identidade interna só aparece depois de extrair "
                        "(o SSPI instala ZIP/7z/RAR únicos pelo caminho de download direto)")
    if not pr.ok:
        return e.reject("UNREACHABLE", pr.error or f"HTTP {pr.status}")
    e.final_host = urlsplit(pr.final_url).hostname
    if e.final_host != urlsplit(found.url).hostname:
        e.warnings.append(f"o link redireciona para {e.final_host} (URL assinada que expira): comportamento do SSPI nesse redirect não testado")
    if pr.content_type and pr.content_type.startswith("text/"):
        return e.reject("NOT_FILE", f"content-type {pr.content_type}")
    if pr.total_size is not None and found.size is not None and pr.total_size != found.size:
        return e.reject("SIZE_MISMATCH", f"feed {found.size} B, servidor {pr.total_size} B")
    e.total_size = pr.total_size if pr.total_size is not None else found.size
    e.stage = "acessivel"
    # 2) identidade lida do próprio PKG
    try:
        head = _read_head(found, pr, net)
    except PkgError as ex:
        return e.reject(ex.code, str(ex))
    e.content_id, e.name, e.kind = head.content_id, found.name_hint or (head.sfo.get("TITLE") or "").strip() or None, head.kind
    e.version = head.sfo.get("APP_VER") or head.sfo.get("VERSION")
    e.category_sfo = head.sfo.get("CATEGORY")
    if head.sfo.get("TITLE_ID") != head.title_id:
        return e.reject("IDENTITY_MISMATCH", f"param.sfo TITLE_ID={head.sfo.get('TITLE_ID')} ≠ Content ID ({head.title_id})")
    if head.sfo.get("CONTENT_ID") not in (None, head.content_id):
        return e.reject("IDENTITY_MISMATCH", "CONTENT_ID do param.sfo ≠ cabeçalho do PKG")
    e.title_id = head.title_id
    e.restricted = is_retail_style(head.content_id, found.meta.get("category"))     # marca (sem descartar), para a etapa PUBLICATION
    cat_id = found.meta.get("catalogTitleId")
    if cat_id and cat_id != head.title_id:
        e.warnings.append(f"o catálogo da fonte declara {cat_id}, mas o PKG é {head.title_id}: vale o ID lido do PKG")
    e.stage = "pkg_verificado"
    return e


def mark_duplicates(entries: list[Entry]) -> None:
    """Mesmo arquivo em mais de um lugar (mesmo Content ID, versão e tamanho): o primeiro vale, os demais viram `duplicateOf`."""
    seen: dict[tuple, str] = {}
    for e in entries:
        if e.content_id and e.total_size:
            k = (e.content_id, e.version, e.total_size)
            if k in seen:
                e.duplicate_of = seen[k]
            else:
                seen[k] = e.found.key
