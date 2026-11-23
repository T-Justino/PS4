"""UNIFICADA: visão única dos CUSAs por jogo (registros curados da 5B + CUSAs alegados no Wikidata) e reconhecimento do termo de busca
(nome, CUSA ou Content ID). Só leitura: não altera nenhum dos dois conjuntos e NÃO mistura a origem:
  origem "curado"   = registro de versões.py (evidência de fonte oficial citada/confirmada);
  origem "wikidata" = CUSA alegado no Wikidata (verificadoEmFonteOficial = False), sem região/idioma/edição/versão.
Se o mesmo CUSA aparece nos dois para o mesmo Q-id, o registro curado ganha `corroboradoPorWikidata` (nenhum duplicado é criado).
"""
from __future__ import annotations

from . import versoes

CUSA_RE = versoes.CUSA_RE
CONTENT_ID_RE = versoes.CONTENT_ID_RE


def classificar_termo(termo: str) -> str:
    """'contentId' | 'cusa' | 'nome'. Reconhece só o formato exato (maiúsculas/minúsculas tanto faz); o resto é nome."""
    t = (termo or "").strip().upper()
    if CONTENT_ID_RE.match(t):
        return "contentId"
    if CUSA_RE.match(t):
        return "cusa"
    return "nome"


def _evidencia_wd(ev: dict) -> dict:
    rot = f": {ev['rotuloPropriedade']}" if ev.get("rotuloPropriedade") else ""
    return {"fonte": f"Wikidata ({ev.get('propriedade', '?')}{rot})", "tipo": "wikidata", "url": ev.get("url", ""), "obtidoEm": ev.get("consultadoEm", ""),
            "trecho": f"valor no Wikidata: {ev.get('valor', '')}"}


def _normalizar_wd(r: dict) -> dict:
    cids = list(r.get("contentIds") or [])
    return {"origem": "wikidata", "qid": r["qid"], "jogo": r.get("jogo", ""), "cusa": r["cusa"], "contentId": cids[0] if len(cids) == 1 else None, "contentIds": cids,
            "edicao": None, "versao": None, "regiao": None, "idiomas": None, "idiomasBase": None, "lojas": [],
            "status": "wikidata", "verificadoEmFonteOficial": False, "evidencias": [_evidencia_wd(e) for e in r.get("evidencias", [])],
            "nota": "CUSA alegado no Wikidata; não verificado em fonte oficial. Região, idiomas, edição e versão: desconhecidos."}


def registros_do_jogo(qid: str, curados: dict, wd: dict) -> list[dict]:
    """Curados primeiro (inalterados, com origem 'curado'), depois os do Wikidata que NÃO repetem um CUSA já curado deste Q-id."""
    cur = [dict(r, origem="curado") for r in curados.get("versoes", []) if r.get("qid") == qid]
    wds = [r for r in wd.get("registros", []) if r.get("qid") == qid]
    por_cusa = {r["cusa"]: r for r in cur}
    extra = []
    for w in wds:
        n = _normalizar_wd(w)
        if w["cusa"] in por_cusa:
            for r in cur:
                if r["cusa"] == w["cusa"]:
                    r.setdefault("corroboradoPorWikidata", []).extend(n["evidencias"])
        else:
            extra.append(n)
    return cur + extra


def agrupar(curados: dict, wd: dict) -> dict[str, list[dict]]:
    qids = []
    for r in curados.get("versoes", []):
        if r["qid"] not in qids:
            qids.append(r["qid"])
    for r in wd.get("registros", []):
        if r["qid"] not in qids:
            qids.append(r["qid"])
    return {q: registros_do_jogo(q, curados, wd) for q in qids}


def conflitos_do_jogo(qid: str, wd: dict) -> list[dict]:
    return [c for c in wd.get("conflitos", []) if qid in c.get("qids", [])]


def localizar(termo: str, curados: dict, wd: dict) -> dict:
    """Para CUSA e Content ID: quais Q-ids têm esse identificador (curado ou Wikidata). Nome não é resolvido aqui (use busca.buscar).
    Devolve {tipo, qids, conflito?, nota}. Um CUSA em conflito não é associado a nenhum jogo."""
    tipo = classificar_termo(termo)
    t = (termo or "").strip().upper()
    qids: list[str] = []
    out: dict = {"tipo": tipo, "qids": qids, "nota": ""}
    if tipo == "nome":
        return out
    if tipo == "cusa":
        for r in curados.get("versoes", []):
            if r["cusa"] == t and r["qid"] not in qids:
                qids.append(r["qid"])
        for r in wd.get("registros", []):
            if r["cusa"] == t and r["qid"] not in qids:
                qids.append(r["qid"])
        conf = [c for c in wd.get("conflitos", []) if c.get("cusa") == t]
        if conf:
            out["conflito"] = conf
            out["nota"] = f"{t} é um CUSA em CONFLITO no Wikidata ({'; '.join(conf[0]['jogos'])}): não foi associado a jogo algum até revisão."
        else:
            out["nota"] = f"{t} reconhecido como CUSA (identificador do título)."
        return out
    m = CONTENT_ID_RE.match(t)
    for r in curados.get("versoes", []):
        if (r.get("contentId") or "").upper() == t and r["qid"] not in qids:
            qids.append(r["qid"])
    for r in wd.get("registros", []):
        if t in [c.upper() for c in r.get("contentIds", [])] and r["qid"] not in qids:
            qids.append(r["qid"])
    out["nota"] = f"{t} reconhecido como Content ID (identifica um produto/edição), não como CUSA. O CUSA contido nele é {m.group(2)}."
    return out
