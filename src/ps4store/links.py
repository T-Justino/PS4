"""Classificação de links e arquivos (sem rede): o que o SSPI consegue (ou não) usar, e por quê.

Regras baseadas no baixador nativo do SSPI (código público `transfer/gs_http.c`, `gs_xfer.c`): segue redirects sozinho
(só HTTPS→HTTPS), baixa em faixas `Range` paralelas quando recebe 206 com `Content-Range` e tamanho total, cai para uma
conexão só se o servidor ignora `Range`, exige `Content-Encoding` identity e, se a URL assinada expirar (401/403/404/410/5xx),
refaz o redirect pela URL ORIGINAL (por isso o catálogo guarda sempre a URL estável, nunca a assinada).
"""
from __future__ import annotations

import re

# Prefixos de serviço de Content ID de aparência comercial (Sony). Homebrew costuma usar IV0000, TX0000 etc.
RETAIL_RE = re.compile(r"^(UP|EP|HP|JP|KP|IP|UT|ET|AP|CP|HT|JT)\d{4}-")
# Categorias do PKG-Zone que misturam homebrew com portes/mods/apps de terceiros comerciais (media = streaming; game/mod/dev menu = jogos
# comerciais portados ou modificados). Conservador: ficam só na pesquisa. "hb game", "utility", "emulator" seguem para a lista pessoal.
RETAIL_CATEGORIES = {"media", "game", "games", "mod", "dev menu"}
_NEW = re.compile(r"^(.*)\.part(\d+)\.rar$", re.I)
_OLD = re.compile(r"^(.*)\.(rar|r\d{2,3}|[s-z]\d{2})$", re.I)


def is_retail_style(content_id: str | None, category: str | None = None) -> bool:
    return bool(content_id and RETAIL_RE.match(content_id)) or (category or "").lower() in RETAIL_CATEGORIES


def multipart_info(name: str) -> dict | None:
    """RAR dividido, como o SSPI reconhece (`x.part1.rar`/`x.part01.rar` ou `x.rar` + `x.r00`...)."""
    m = _NEW.match(name or "")
    if m:
        return {"style": "part-rar", "set": m.group(1) + ".part*.rar", "index": int(m.group(2))}
    m = _OLD.match(name or "")
    if m and m.group(2).lower() != "rar":
        return {"style": "old-rar", "set": m.group(1) + ".rar", "index": None}
    return None


def file_type(name: str) -> str:
    n = (name or "").lower()
    if n.endswith(".pkg"):
        return "pkg"
    if multipart_info(name):
        return "rar-multiparte"
    for ext, t in ((".rar", "rar"), (".7z", "7z"), (".zip", "zip")):
        if n.endswith(ext):
            return t
    return "desconhecido"


def classify_link(pr) -> dict:
    """Descreve o link a partir da sondagem (Probe). `sspiUsable` = o baixador do SSPI deve conseguir usá-lo (hipótese
    pelo código público; só o teste no console prova)."""
    notes: list[str] = []
    if not pr.ok:
        st = pr.status
        if st == 401:
            kind = "exige-autenticacao"
        elif st == 403:
            kind = "expirado" if pr.signed else "acesso-negado"      # o servidor recusa (versão desativada, bloqueio...): não presumimos o motivo
        elif st in (404, 410):
            kind = "removido"
        elif st is None:
            kind = "erro-de-rede"
        else:
            kind = "erro-http"
        return {"kind": kind, "status": st, "redirects": pr.redirects, "chain": pr.chain, "temporaryFinalUrl": pr.signed,
                "rangeOk": False, "sspiUsable": False, "notes": [pr.error or f"HTTP {st}"]}
    if (pr.content_type or "").startswith("text/"):
        return {"kind": "pagina-intermediaria", "status": pr.status, "redirects": pr.redirects, "chain": pr.chain,
                "temporaryFinalUrl": pr.signed, "rangeOk": False, "sspiUsable": False,
                "notes": ["a URL devolve HTML, não o arquivo: precisa de uma etapa intermediária que o robô não automatiza"]}
    enc_ok = (pr.content_encoding or "identity").lower() == "identity"
    single = not pr.range_ok
    usable = enc_ok and (pr.range_ok or (pr.status == 200 and pr.total_size is not None))
    if not enc_ok:
        notes.append(f"Content-Encoding {pr.content_encoding}: o SSPI exige identity")
    if single and usable:
        notes.append("servidor ignora Range: o SSPI baixa em uma conexão só, sem faixas paralelas")
    if pr.redirects and pr.signed:
        notes.append("redireciona para URL assinada que expira: o SSPI refaz o redirect pela URL estável se ela expirar")
    if pr.expires_in is not None:
        notes.append(f"URL assinada expira em ≈{max(pr.expires_in, 0) // 60} min (a estável gera outra)")
    if pr.total_size is None:
        notes.append("tamanho total desconhecido")
    return {"kind": "redirect" if pr.redirects else "direto", "status": pr.status, "redirects": pr.redirects,
            "chain": pr.chain, "temporaryFinalUrl": pr.signed, "rangeOk": pr.range_ok, "singleLane": single,
            "etag": bool(pr.etag), "etagStrong": bool(pr.etag) and not pr.etag.startswith("W/"),
            "lastModified": bool(pr.last_modified), "ttlSeconds": pr.expires_in, "sspiUsable": usable, "notes": notes}
