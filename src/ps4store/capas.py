"""CAPAS: importador independente de imagens (miniaturas locais) a partir do Wikidata (P18) + Wikimedia Commons, com licença conferida.

Fluxo por jogo (Q-id real do índice): P18 no Wikidata -> metadados do arquivo no Commons (licença, autor, categorias) -> aceita SÓ licença livre e clara
(CC0, domínio público, CC BY, CC BY-SA; NC/ND/GFDL isolada/uso justo/desconhecida = rejeitada; atribuição obrigatória sem autor = rejeitada) -> baixa a
MINIATURA (<= 400 KB, JPEG/PNG/WebP por assinatura dos bytes) -> grava em local/capas/<Qid>.<ext> + índice JSON com fonte, licença, autoria e atribuição.
Imagem do Wikidata NÃO é presumida capa: tipo 'capa' só se uma categoria do Commons indicar capa; senão 'ilustrativa'. Sem imagem = placeholder (na interface).
Rede só neste comando (hosts fixos: query.wikidata.org, commons.wikimedia.org, upload.wikimedia.org). Amostra limitada (máx. 30 jogos por execução).
Nada em local/capas/ é versionado. Stdlib, Termux.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import busca, unificada, versoes, cusas, wikidata

DIR_PADRAO = "local/capas"
SCHEMA = "ps4store.capas/v1"
HOSTS = {"query.wikidata.org", "commons.wikimedia.org", "upload.wikimedia.org"}
MAX_AMOSTRA = 30
MAX_BYTES = 400 * 1024
LARGURA = 360
ARQ_RE = re.compile(r"^(Q[0-9]{1,12})\.(jpg|png|webp)$")
QID_RE = re.compile(r"^Q[0-9]{1,12}$")
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_NEG = re.compile(r"(^|[\s\-_/(])(nc|nd)([\s\-_/)\d.]|$)|non-?commercial|no[- ]?deriv|fair use|non-?free|gfdl|copyrighted|all rights reserved|unknown|unspecified", re.I)
_OK = re.compile(r"^(cc0|cc[ -]by(?:[ -]sa)?(?:[ -]\d(?:\.\d)?)?(?: .*)?|public domain.*|pd[ -].*|pdm.*|attribution.*)$", re.I)


def licenca_aceita(rotulo: str) -> tuple[bool, str]:
    """(aceita, motivo). Lista de permissão estrita: CC0, domínio público, CC BY, CC BY-SA. Qualquer dúvida = rejeita."""
    r = (rotulo or "").strip()
    if not r:
        return False, "licenca-desconhecida"
    if _NEG.search(r):
        return False, f"licenca-nao-permitida:{r[:40]}"
    if _OK.match(r):
        return True, ""
    return False, f"licenca-nao-permitida:{r[:40]}"


def _texto(v: str, n: int = 200) -> str:
    t = re.sub(r"<[^>]+>", " ", htmllib.unescape(v or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]


def _meta(ext: dict, k: str) -> str:
    x = ext.get(k)
    return x.get("value", "") if isinstance(x, dict) else ""


def avaliar_arquivo(pagina: dict) -> dict:
    """Metadados de UMA página `File:` do Commons -> {'aceita': bool, 'motivo', 'registro'}. Só lê; não baixa."""
    info = (pagina.get("imageinfo") or [{}])[0]
    ext = info.get("extmetadata") or {}
    lic = _meta(ext, "LicenseShortName") or _meta(ext, "UsageTerms")
    ok, motivo = licenca_aceita(lic)
    if not ok:
        return {"aceita": False, "motivo": motivo}
    mime = info.get("mime", "")
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        return {"aceita": False, "motivo": f"formato-nao-permitido:{mime or '?'}"}
    autor = _texto(_meta(ext, "Artist"), 120)
    exige = _meta(ext, "AttributionRequired").lower() == "true" or lic.lower().startswith("cc by")
    if exige and not autor:
        return {"aceita": False, "motivo": "atribuicao-incompleta (autor ausente)"}
    cats = [c.get("title", "") for c in pagina.get("categories", [])]
    tipo = "capa" if any(re.search(r"\bcovers?\b", c, re.I) for c in cats) else "ilustrativa"
    titulo = pagina.get("title", "")
    lic_url = _meta(ext, "LicenseUrl")
    reg = {"tipo": tipo, "fonte": "Wikimedia Commons", "propriedade": "P18", "arquivoCommons": titulo,
           "paginaUrl": info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(titulo.replace(' ', '_'))}",
           "licenca": lic, "licencaUrl": lic_url, "autor": autor or "autor não informado", "atribuicaoObrigatoria": exige,
           "atribuicao": f"{titulo.removeprefix('File:')} · {autor or 'autor não informado'} · {lic}" + (f" ({lic_url})" if lic_url else "") + " · via Wikimedia Commons",
           "thumbUrl": info.get("thumburl") or "", "largura": info.get("thumbwidth"), "altura": info.get("thumbheight"), "categorias": cats[:6]}
    return {"aceita": True, "motivo": "", "registro": reg}


def _http(url: str, ua: str, maximo: int, timeout: int = 60) -> bytes:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in HOSTS:
        raise ValueError(f"host não permitido: {p.hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        corpo = r.read(maximo + 1)
    if len(corpo) > maximo:
        raise ValueError("resposta maior que o limite")
    return corpo


def tipo_da_imagem(b: bytes) -> str | None:
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


# ---------- índice local ----------
def indice_vazio() -> dict:
    return {"schema": SCHEMA, "capas": {}, "semImagem": {}}


def carregar_indice(diretorio: str = DIR_PADRAO) -> dict:
    try:
        d = json.loads((Path(diretorio) / "indice.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return indice_vazio()
    return d if d.get("schema") == SCHEMA and isinstance(d.get("capas"), dict) else indice_vazio()


def salvar_indice(doc: dict, diretorio: str = DIR_PADRAO) -> None:
    p = Path(diretorio)
    p.mkdir(parents=True, exist_ok=True)
    tmp = p / "indice.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p / "indice.json")


def caminho_da_capa(diretorio: str, idx: dict, qid: str) -> tuple[Path, str] | None:
    """Arquivo da capa de um Q-id (validado: nome Q123.ext dentro de `diretorio`, sem subpastas). None se não houver."""
    if not QID_RE.match(qid or ""):
        return None
    c = idx.get("capas", {}).get(qid)
    if not c or not ARQ_RE.match(str(c.get("arquivo", ""))) or not c["arquivo"].startswith(qid + "."):
        return None
    base = Path(diretorio).resolve()
    p = (base / c["arquivo"]).resolve()
    if p.parent != base or not p.is_file():
        return None
    return p, MIME[c["arquivo"].rsplit(".", 1)[1]]


def info_publica(idx: dict, qid: str) -> dict | None:
    """O que a interface pode mostrar (sem caminhos de arquivo)."""
    c = idx.get("capas", {}).get(qid)
    if not c:
        return None
    return {"url": f"/capa/{qid}", **{k: c.get(k) for k in ("tipo", "fonte", "licenca", "licencaUrl", "autor", "atribuicao", "paginaUrl", "arquivoCommons", "obtidoEm")}}


# ---------- importação ----------
def _arquivo_de_p18(uri: str) -> str | None:
    m = re.search(r"Special:FilePath/(.+)$", uri or "")
    return urllib.parse.unquote(m.group(1)).replace("_", " ") if m else None


def importar(qids: list[tuple[str, str]], fetch, diretorio: str, pausa: float = 1.0, dormir=time.sleep, max_req: int = 40, forcar: bool = False) -> dict:
    """`qids` = [(qid, nome)] do ÍNDICE. `fetch(url, maximo) -> bytes` injetável. Devolve estatísticas; grava arquivos só em `diretorio`."""
    idx = carregar_indice(diretorio)
    pend = [(q, n) for q, n in qids if forcar or (q not in idx["capas"] and q not in idx["semImagem"])]
    est = {"consultados": len(qids), "jaTinham": len(qids) - len(pend), "comImagem": 0, "capa": 0, "ilustrativa": 0, "rejeitadas": {}, "semP18": 0, "requisicoes": 0}
    usadas = [0]

    def req(url, maximo):
        if usadas[0] >= max_req:
            raise RuntimeError(f"teto de {max_req} requisições")
        if usadas[0]:
            dormir(pausa)
        usadas[0] += 1
        return fetch(url, maximo)

    def rej(q, motivo):
        k = motivo.split(":")[0].split(" (")[0]
        est["rejeitadas"][k] = est["rejeitadas"].get(k, 0) + 1
        idx["semImagem"][q] = {"motivo": motivo, "consultadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    if not pend:
        est["requisicoes"] = 0
        return est
    gs = " ".join(f"wd:{q}" for q, _ in pend)
    q_p18 = f"SELECT ?g ?img WHERE {{ VALUES ?g {{ {gs} }} ?g wdt:P18 ?img . }} ORDER BY ?g ?img"
    linhas = json.loads(req(wikidata.url_consulta(q_p18), 2_000_000))["results"]["bindings"]
    arq: dict[str, str] = {}
    for b in linhas:
        m = re.search(r"/(Q[0-9]+)$", b["g"]["value"])
        f = _arquivo_de_p18(b["img"]["value"])
        if m and f and m.group(1) not in arq:
            arq[m.group(1)] = f                                     # primeira imagem (ordem estável); as outras são ignoradas
    for q, _ in pend:
        if q not in arq:
            est["semP18"] += 1
            idx["semImagem"][q] = {"motivo": "sem-P18", "consultadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    com = [(q, arq[q]) for q, _ in pend if q in arq]
    for i in range(0, len(com), 10):
        lote = com[i:i + 10]
        titulos = "|".join("File:" + f for _, f in lote)
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo%7Ccategories&iiprop=url%7Csize%7Cmime%7Cextmetadata"
               f"&iiurlwidth={LARGURA}&cllimit=50&redirects=1&titles=" + urllib.parse.quote(titulos))
        d = json.loads(req(url, 2_000_000)).get("query", {})
        norm_ = {n["from"]: n["to"] for n in d.get("normalized", []) + d.get("redirects", [])}
        paginas = {p.get("title"): p for p in d.get("pages", {}).values()}
        for q, f in lote:
            t = "File:" + f
            t = norm_.get(norm_.get(t, t), norm_.get(t, t))
            p = paginas.get(t) or paginas.get("File:" + f)
            if not p or "missing" in p or not p.get("imageinfo"):
                rej(q, "arquivo-ausente-no-commons")
                continue
            av = avaliar_arquivo(p)
            if not av["aceita"]:
                rej(q, av["motivo"])
                continue
            reg = av["registro"]
            if not reg["thumbUrl"]:
                rej(q, "sem-miniatura")
                continue
            try:
                dados = req(reg["thumbUrl"], MAX_BYTES)
            except (OSError, ValueError, RuntimeError) as e:
                if isinstance(e, RuntimeError):
                    raise
                rej(q, f"download-falhou:{type(e).__name__}")
                continue
            ext = tipo_da_imagem(dados)
            if not ext:
                rej(q, "formato-invalido (assinatura dos bytes)")
                continue
            nome_arq = f"{q}.{ext}"
            Path(diretorio).mkdir(parents=True, exist_ok=True)
            (Path(diretorio) / nome_arq).write_bytes(dados)
            reg.pop("thumbUrl", None)
            reg.update({"arquivo": nome_arq, "bytes": len(dados), "sha256": hashlib.sha256(dados).hexdigest(), "obtidoEm": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            idx["capas"][q] = reg
            idx["semImagem"].pop(q, None)
            est["comImagem"] += 1
            est[reg["tipo"]] += 1
    est["requisicoes"] = usadas[0]
    salvar_indice(idx, diretorio)
    return est


def escolher_amostra(indice: dict, curados: dict, wd: dict, nomes: list[str], n: int) -> list[tuple[str, str]]:
    n = max(1, min(n, MAX_AMOSTRA))
    por_qid = unificada.agrupar(curados, wd)
    out: list[tuple[str, str]] = []
    vistos: set[str] = set()

    def add(q, nome):
        if q and q not in vistos and len(out) < n:
            vistos.add(q)
            out.append((q, nome))

    for t in nomes:
        for r in busca.buscar(indice, t, limite=n):
            i = str(r.get("idFonte", ""))
            if i.startswith("wikidata:"):
                add(i.split(":", 1)[1], r["nome"])
    for t in indice.get("titulos", []):                              # completa com jogos que já têm CUSA (mais úteis na interface)
        i = str(t.get("idFonte", ""))
        if i.startswith("wikidata:") and i.split(":", 1)[1] in por_qid:
            add(i.split(":", 1)[1], t["nome"])
    return out


def main(argv=None, fetch=None, dormir=time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.capas", description="importa miniaturas de jogos (Wikidata P18 + Commons, licença conferida); amostra de até 30 jogos")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--amostra", type=int, nargs="?", const=MAX_AMOSTRA, metavar="N", help=f"importa até N jogos (máx. {MAX_AMOSTRA})")
    g.add_argument("--status", action="store_true", help="resume o que já foi importado (sem rede)")
    ap.add_argument("--jogos", default="", help='nomes para priorizar, ex.: "batman,cyberpunk"')
    ap.add_argument("--dir", default=DIR_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusas", default=cusas.DADOS_PADRAO)
    ap.add_argument("--user-agent", default=os.environ.get("WIKIDATA_USER_AGENT", wikidata.UA_PADRAO))
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--max-requisicoes", type=int, default=40)
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        idx = carregar_indice(a.dir)
        tipos = {}
        for c in idx["capas"].values():
            tipos[c["tipo"]] = tipos.get(c["tipo"], 0) + 1
        mot = {}
        for s in idx["semImagem"].values():
            k = s["motivo"].split(":")[0].split(" (")[0]
            mot[k] = mot.get(k, 0) + 1
        print(f"Imagens locais: {len(idx['capas'])} {tipos or ''} · sem imagem: {len(idx['semImagem'])} {mot or ''}")
        return 0
    try:
        indice = busca.carregar_indice(a.indice)
        amostra = escolher_amostra(indice, versoes.carregar(a.versoes), cusas.carregar_dados(a.cusas), [x.strip() for x in a.jogos.split(",") if x.strip()], a.amostra)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if not amostra:
        print("ERRO  nenhum jogo para a amostra (índice vazio?)", file=sys.stderr)
        return 2
    if a.user_agent == wikidata.UA_PADRAO:
        print("AVISO  User-Agent genérico: defina WIKIDATA_USER_AGENT com um contato (Wikimedia pede).", file=sys.stderr)
    f = fetch or (lambda u, m: _http(u, a.user_agent, m))
    try:
        est = importar(amostra, f, a.dir, a.pausa, dormir, max(1, a.max_requisicoes), a.forcar)
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print(f"ERRO  {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1
    novos = est["consultados"] - est["jaTinham"]
    print(f"Amostra: {est['consultados']} jogo(s) ({est['jaTinham']} já tinham resultado) · {est['requisicoes']} requisição(ões)")
    print(f"  com imagem aceita: {est['comImagem']} (capa: {est['capa']}, ilustrativa: {est['ilustrativa']}) · sem P18 no Wikidata: {est['semP18']} · rejeitadas: {est['rejeitadas'] or 'nenhuma'}")
    if novos:
        print(f"  cobertura da amostra nova: {100 * est['comImagem'] / novos:.0f}% ({est['comImagem']}/{novos}); os demais usam placeholder")
    print("Imagens só de licença livre conferida (CC0, domínio público, CC BY, CC BY-SA); 'ilustrativa' NÃO é capa oficial. Nada em local/capas/ vai para o Git.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
