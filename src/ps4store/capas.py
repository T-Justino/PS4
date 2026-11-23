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
WIKIPEDIA_RE = re.compile(r"^[a-z]{2,3}\.wikipedia\.org$")          # Wikipedia em qualquer idioma (só leitura da API pública)
RETENTAR_DIAS = 14                                                  # jogo sem imagem não é consultado de novo antes disso
MAX_BUSCAS_COMMONS = 15                                             # buscas por nome (1 requisição cada) por execução
PROVEDORES = ("wikidata-p18", "wikipedia", "commons-busca")
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
    reg = {"tipo": tipo, "fonte": "Wikimedia Commons", "arquivoCommons": titulo,
           "paginaUrl": info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(titulo.replace(' ', '_'))}",
           "licenca": lic, "licencaUrl": lic_url, "autor": autor or "autor não informado", "atribuicaoObrigatoria": exige,
           "atribuicao": f"{titulo.removeprefix('File:')} · {autor or 'autor não informado'} · {lic}" + (f" ({lic_url})" if lic_url else "") + " · via Wikimedia Commons",
           "thumbUrl": info.get("thumburl") or "", "largura": info.get("thumbwidth"), "altura": info.get("thumbheight"), "categorias": cats[:6]}
    return {"aceita": True, "motivo": "", "registro": reg}


def _http(url: str, ua: str, maximo: int, timeout: int = 60) -> bytes:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not (p.hostname in HOSTS or WIKIPEDIA_RE.match(p.hostname or "")):
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
    return {"url": f"/capa/{qid}", **{k: c.get(k) for k in ("tipo", "fonte", "licenca", "licencaUrl", "autor", "atribuicao", "paginaUrl", "arquivoCommons", "obtidoEm", "provedor", "correspondencia")}}


# ---------- importação (múltiplos provedores, em ordem; o primeiro com imagem aceita e jogo conferido vence) ----------
RUIDO = {"screenshot", "cover", "covers", "logo", "box", "art", "boxart", "gameplay", "video", "game", "videogame", "playstation", "ps4", "jpg", "jpeg", "png", "webp", "file",
         "title", "screen", "pc", "xbox", "one", "switch", "the", "of", "and", "a", "wallpaper", "poster", "front", "us", "eu"}
_VG = re.compile(r"video ?game|playstation|\bps4\b", re.I)


def _arquivo_de_p18(uri: str) -> str | None:
    m = re.search(r"Special:FilePath/(.+)$", uri or "")
    return urllib.parse.unquote(m.group(1)).replace("_", " ") if m else None


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _item(x) -> dict:
    """(qid, nome[, ano[, url]]) -> dict. O 'url' é a página de referência do ÍNDICE (vínculo por Q-id), nunca texto livre."""
    return {"qid": x[0], "nome": x[1], "ano": (str(x[2])[:4] if len(x) > 2 and x[2] else None), "url": (x[3] if len(x) > 3 else "") or ""}


def _sem_parenteses(t: str) -> str:
    return busca.norm(re.sub(r"\([^)]*\)", " ", t or ""))


def confere_titulo_arquivo(nome: str, ano: str | None, titulo: str) -> bool:
    """O nome do arquivo só 'fala' do jogo certo se contém TODAS as palavras do nome e nada além de ruído (capa, logo, ano igual...). Sequências (2, III) reprovam."""
    n = _sem_parenteses(nome).split()
    t = busca.norm(re.sub(r"\.[A-Za-z0-9]{2,5}$", "", titulo.removeprefix("File:"))).split()
    if not n or any(w not in t for w in n):
        return False
    resto = [w for w in t if w not in n and w not in RUIDO]
    anos = [w for w in resto if re.fullmatch(r"(19|20)\d\d", w)]
    if ano and any(a != ano for a in anos):
        return False
    return not [w for w in resto if w not in anos]


def _texto_pagina(p: dict) -> str:
    ext = ((p.get("imageinfo") or [{}])[0].get("extmetadata")) or {}
    return " ".join([_meta(ext, "ImageDescription"), _meta(ext, "ObjectName"), _meta(ext, "Categories")] + [c.get("title", "") for c in p.get("categories", [])])


def _preferir(regs: list[dict]) -> list[dict]:
    """Vertical antes de horizontal (cards), 'capa' antes de 'ilustrativa'."""
    return sorted(regs, key=lambda r: (0 if (r.get("altura") or 0) >= (r.get("largura") or 0) else 1, 0 if r["tipo"] == "capa" else 1))


COMMONS_API = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo%7Ccategories&iiprop=url%7Csize%7Cmime%7Cextmetadata"
               f"&iiurlwidth={LARGURA}&cllimit=50&redirects=1")


def _paginas_commons(titulos: list[str], req) -> dict[str, dict]:
    d = json.loads(req(COMMONS_API + "&titles=" + urllib.parse.quote("|".join(titulos)), 2_000_000)).get("query", {})
    mapa = {n["from"]: n["to"] for n in d.get("normalized", []) + d.get("redirects", [])}
    pgs = {p.get("title"): p for p in d.get("pages", {}).values()}
    out = {}
    for t in titulos:
        t2 = mapa.get(mapa.get(t, t), mapa.get(t, t))
        p = pgs.get(t2) or pgs.get(t)
        if p and "missing" not in p and p.get("imageinfo"):
            out[t] = p
    return out


def _candidatos_p18(pend: list[dict], req) -> dict[str, list[tuple[str, str]]]:
    gs = " ".join(f"wd:{i['qid']}" for i in pend)
    q = f"SELECT ?g ?img WHERE {{ VALUES ?g {{ {gs} }} ?g wdt:P18 ?img . }} ORDER BY ?g ?img"
    out: dict[str, list] = {}
    for b in json.loads(req(wikidata.url_consulta(q), 2_000_000))["results"]["bindings"]:
        m = re.search(r"/(Q[0-9]+)$", b["g"]["value"])
        f = _arquivo_de_p18(b["img"]["value"])
        if m and f:
            out.setdefault(m.group(1), []).append(("File:" + f, "Q-id do jogo tem esta imagem (P18) no Wikidata"))
    return out


def _candidatos_wikipedia(pend: list[dict], req) -> dict[str, list[tuple[str, str]]]:
    """Imagem principal do artigo da Wikipedia que o ÍNDICE já associa ao Q-id (a página de referência); o título do artigo precisa bater com o nome."""
    por_host: dict[str, list[tuple[dict, str]]] = {}
    for i in pend:
        u = urllib.parse.urlsplit(i["url"])
        if u.scheme == "https" and WIKIPEDIA_RE.match(u.hostname or "") and u.path.startswith("/wiki/"):
            por_host.setdefault(u.hostname, []).append((i, urllib.parse.unquote(u.path[6:]).replace("_", " ")))
    out: dict[str, list] = {}
    for host, lista in por_host.items():
        for k in range(0, len(lista), 20):
            lote = lista[k:k + 20]
            url = f"https://{host}/w/api.php?action=query&format=json&prop=pageimages&piprop=name&redirects=1&titles=" + urllib.parse.quote("|".join(t for _, t in lote))
            d = json.loads(req(url, 1_000_000)).get("query", {})
            mapa = {n["from"]: n["to"] for n in d.get("normalized", []) + d.get("redirects", [])}
            pgs = {p.get("title"): p for p in d.get("pages", {}).values()}
            for i, t in lote:
                p = pgs.get(mapa.get(mapa.get(t, t), mapa.get(t, t)))
                if p and p.get("pageimage") and _sem_parenteses(p["title"]) == _sem_parenteses(i["nome"]):
                    out[i["qid"]] = [("File:" + p["pageimage"].replace("_", " "), f"imagem principal do artigo \"{p['title']}\" ({host}), página de referência do Q-id no índice")]
    return out


def _buscar_commons(i: dict, req) -> list[dict]:
    """Busca no Commons pelo NOME e confere: nome do arquivo = nome do jogo (sem sobras) + indício de videogame + ano. Devolve páginas aprovadas."""
    url = (COMMONS_API + "&generator=search&gsrnamespace=6&gsrlimit=6&gsrsearch=" + urllib.parse.quote(f'"{i["nome"]}" game'))
    d = json.loads(req(url, 2_000_000)).get("query", {})
    ok = []
    for p in d.get("pages", {}).values():
        if "imageinfo" in p and confere_titulo_arquivo(i["nome"], i["ano"], p.get("title", "")) and _VG.search(_texto_pagina(p) + " " + p.get("title", "")):
            ok.append(p)
    return ok


def _gravar(q: str, reg: dict, req, diretorio: str, idx: dict) -> str | None:
    """Baixa a miniatura do registro aprovado e grava. None = gravou; senão, o motivo da falha."""
    try:
        dados = req(reg["thumbUrl"], MAX_BYTES)
    except RuntimeError:
        raise
    except (OSError, ValueError) as e:
        return f"download-falhou:{type(e).__name__}"
    ext = tipo_da_imagem(dados)
    if not ext:
        return "formato-invalido (assinatura dos bytes)"
    nome_arq = f"{q}.{ext}"
    Path(diretorio).mkdir(parents=True, exist_ok=True)
    (Path(diretorio) / nome_arq).write_bytes(dados)
    reg = {k: v for k, v in reg.items() if k != "thumbUrl"}
    reg.update({"arquivo": nome_arq, "bytes": len(dados), "sha256": hashlib.sha256(dados).hexdigest(), "obtidoEm": agora()})
    idx["capas"][q] = reg
    idx["semImagem"].pop(q, None)
    return None


def _recente(s: dict) -> bool:
    try:
        t = datetime.fromisoformat(s.get("consultadoEm", ""))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - t).days < RETENTAR_DIAS


def pendentes(qids: list, idx: dict, forcar: bool = False) -> list[dict]:
    """Quem precisa de consulta: sem imagem e sem tentativa recente (jogo sem imagem não é reconsultado em intervalo curto)."""
    out = []
    for x in qids:
        i = _item(x)
        if forcar or (i["qid"] not in idx["capas"] and not (i["qid"] in idx["semImagem"] and _recente(idx["semImagem"][i["qid"]]))):
            out.append(i)
    return out


def importar(qids: list, fetch, diretorio: str, pausa: float = 1.0, dormir=time.sleep, max_req: int = 120, forcar: bool = False, provedores=PROVEDORES) -> dict:
    """`qids` = [(qid, nome[, ano[, url do índice]])]. `fetch(url, maximo) -> bytes` injetável. Provedores em ordem; cada um só vê quem ainda está sem imagem."""
    idx = carregar_indice(diretorio)
    pend = pendentes(qids, idx, forcar)
    est = {"consultados": len(qids), "jaTinham": len(qids) - len(pend), "comImagem": 0, "capa": 0, "ilustrativa": 0, "rejeitadas": {}, "semP18": 0, "requisicoes": 0, "porProvedor": {}}
    usadas = [0]

    def req(url, maximo):
        if usadas[0] >= max_req:
            raise RuntimeError(f"teto de {max_req} requisições")
        if usadas[0]:
            dormir(pausa)
        usadas[0] += 1
        return fetch(url, maximo)

    motivos: dict[str, list[str]] = {}
    ctx = {i["qid"]: i for i in pend}
    aberto = [i["qid"] for i in pend]

    def tentar(q: str, prov: str, paginas: list[tuple[dict, str]]) -> bool:
        regs = []
        for p, corr in paginas:
            av = avaliar_arquivo(p)
            if not av["aceita"]:
                motivos.setdefault(q, []).append(f"{prov}:{av['motivo']}")
                continue
            r = av["registro"]
            if not r["thumbUrl"]:
                motivos.setdefault(q, []).append(f"{prov}:sem-miniatura")
                continue
            r.update({"provedor": prov, "correspondencia": corr, "consultadoEm": agora(), "jogo": {"qid": q, "nome": ctx[q]["nome"], "ano": ctx[q]["ano"]}})
            regs.append(r)
        for r in _preferir(regs):
            falha = _gravar(q, r, req, diretorio, idx)
            if falha is None:
                est["comImagem"] += 1
                est[r["tipo"]] += 1
                est["porProvedor"][prov] = est["porProvedor"].get(prov, 0) + 1
                return True
            motivos.setdefault(q, []).append(f"{prov}:{falha}")
        return False

    def por_arquivos(prov: str, cand: dict[str, list[tuple[str, str]]]) -> None:
        nonlocal aberto
        qs = [q for q in aberto if q in cand]
        todos = sorted({t for q in qs for t, _ in cand[q]})
        pgs: dict[str, dict] = {}
        for k in range(0, len(todos), 10):
            pgs.update(_paginas_commons(todos[k:k + 10], req))
        for q in qs:
            achados = [(pgs[t], c) for t, c in cand[q] if t in pgs]
            if not achados:
                motivos.setdefault(q, []).append(f"{prov}:arquivo-ausente-no-commons")
            elif tentar(q, prov, achados):
                aberto = [x for x in aberto if x != q]

    try:
        if pend and "wikidata-p18" in provedores:
            por_arquivos("wikidata-p18", {q: v[:1] for q, v in _candidatos_p18(pend, req).items()})
        if aberto and "wikipedia" in provedores:
            por_arquivos("wikipedia", _candidatos_wikipedia([ctx[q] for q in aberto], req))
        if aberto and "commons-busca" in provedores:
            for q in list(aberto)[:MAX_BUSCAS_COMMONS]:
                achados = [(p, "nome do arquivo = nome do jogo, indício de videogame, ano conferido") for p in _buscar_commons(ctx[q], req)]
                if achados and tentar(q, "commons-busca", achados):
                    aberto = [x for x in aberto if x != q]
    finally:
        for q in aberto:                                           # (inclui o caso de parada por teto: só registra quem de fato teve motivo ou foi consultado)
            ms = motivos.get(q)
            if ms:
                k = ms[0].split(":", 1)[1].split(":")[0].split(" (")[0]
                est["rejeitadas"][k] = est["rejeitadas"].get(k, 0) + 1
                idx["semImagem"][q] = {"motivo": ms[0].split(":", 1)[1], "tentativas": ms[:6], "consultadoEm": agora()}
            elif usadas[0] < max_req:
                est["semP18"] += 1
                idx["semImagem"][q] = {"motivo": "sem-P18", "tentativas": [], "consultadoEm": agora()}
        est["requisicoes"] = usadas[0]
        if pend:
            salvar_indice(idx, diretorio)
    return est


def interesse_do_painel(porta: int) -> list[str]:
    """Q-ids vistos/pesquisados no painel local (memória do painel; nada é gravado por ele). Falha = lista vazia."""
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{int(porta)}/api/interesse", headers={"Accept": "application/json"}), timeout=3) as r:
            return [q for q in json.loads(r.read(100_000)).get("qids", []) if QID_RE.match(str(q))]
    except (OSError, ValueError):
        return []


def escolher_amostra(indice: dict, curados: dict, wd: dict, nomes: list[str], n: int, ignorar: set[str] | None = None, prioridade: list[str] | None = None) -> list[tuple]:
    """Fila de até n jogos (máx. 30) sem imagem: 1º visto/pesquisado no painel, 2º nomes pedidos, 3º jogos com CUSA. Quem já tem resultado recente fica de fora."""
    n = max(1, min(n, MAX_AMOSTRA))
    ignorar = ignorar or set()
    por_qid = unificada.agrupar(curados, wd)
    por_id = {str(t.get("idFonte", "")).split(":", 1)[1]: t for t in indice.get("titulos", []) if str(t.get("idFonte", "")).startswith("wikidata:")}
    out: list[tuple] = []
    vistos: set[str] = set(ignorar)

    def add(q, t):
        if q and q not in vistos and len(out) < n:
            vistos.add(q)
            out.append((q, t["nome"], t.get("lancamento"), t.get("url", "")))

    for q in prioridade or []:
        if q in por_id:
            add(q, por_id[q])
    for nome in nomes:
        for r in busca.buscar(indice, nome, limite=n):
            i = str(r.get("idFonte", ""))
            if i.startswith("wikidata:"):
                add(i.split(":", 1)[1], r)
    for q, t in por_id.items():
        if q in por_qid:
            add(q, t)
    return out


def main(argv=None, fetch=None, dormir=time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.capas", description="importa miniaturas (Wikidata P18, Wikipedia, Commons; licença e jogo conferidos); fila progressiva de até 30 jogos por execução")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--amostra", "--fila", type=int, nargs="?", const=MAX_AMOSTRA, metavar="N", dest="amostra", help=f"processa até N jogos sem imagem (máx. {MAX_AMOSTRA}); rode de novo para avançar")
    g.add_argument("--status", action="store_true", help="resume o que já foi importado (sem rede)")
    ap.add_argument("--jogos", default="", help='nomes para priorizar, ex.: "batman,cyberpunk"')
    ap.add_argument("--painel-porta", type=int, default=0, help="se o painel estiver rodando, prioriza os jogos que você pesquisou/abriu (ex.: 8765)")
    ap.add_argument("--provedores", default=",".join(PROVEDORES), help="ordem de tentativa (padrão: todos)")
    ap.add_argument("--dir", default=DIR_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusas", default=cusas.DADOS_PADRAO)
    ap.add_argument("--user-agent", default=os.environ.get("WIKIDATA_USER_AGENT", wikidata.UA_PADRAO))
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--max-requisicoes", type=int, default=120)
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        idx = carregar_indice(a.dir)
        tipos, provs, mot = {}, {}, {}
        for c in idx["capas"].values():
            tipos[c["tipo"]] = tipos.get(c["tipo"], 0) + 1
            provs[c.get("provedor", "wikidata-p18")] = provs.get(c.get("provedor", "wikidata-p18"), 0) + 1
        for s_ in idx["semImagem"].values():
            k = s_["motivo"].split(":")[0].split(" (")[0]
            mot[k] = mot.get(k, 0) + 1
        print(f"Imagens locais: {len(idx['capas'])} {tipos or ''} por provedor {provs or ''} · sem imagem: {len(idx['semImagem'])} {mot or ''}")
        return 0
    provs = [x.strip() for x in a.provedores.split(",") if x.strip()]
    if not provs or any(x not in PROVEDORES for x in provs):
        print(f"ERRO  provedores válidos: {', '.join(PROVEDORES)}", file=sys.stderr)
        return 2
    try:
        indice = busca.carregar_indice(a.indice)
        idx0 = carregar_indice(a.dir)
        feitos = set(idx0["capas"]) | {q for q, s_ in idx0["semImagem"].items() if _recente(s_)}
        prio = interesse_do_painel(a.painel_porta) if a.painel_porta else []
        amostra = escolher_amostra(indice, versoes.carregar(a.versoes), cusas.carregar_dados(a.cusas), [x.strip() for x in a.jogos.split(",") if x.strip()], a.amostra,
                                   None if a.forcar else feitos, prio)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if not amostra:
        print("Nada a fazer: todos os jogos candidatos já têm imagem ou foram consultados há menos de %d dias (ou o índice está vazio)." % RETENTAR_DIAS)
        return 0
    if a.user_agent == wikidata.UA_PADRAO:
        print("AVISO  User-Agent genérico: defina WIKIDATA_USER_AGENT com um contato (Wikimedia pede).", file=sys.stderr)
    f = fetch or (lambda u, m: _http(u, a.user_agent, m))
    try:
        est = importar(amostra, f, a.dir, a.pausa, dormir, max(1, a.max_requisicoes), a.forcar, tuple(provs))
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print(f"ERRO  {type(e).__name__}: {str(e)[:200]} (o que já foi gravado fica no cache; rode de novo)", file=sys.stderr)
        return 1
    novos = est["consultados"] - est["jaTinham"]
    print(f"Lote: {est['consultados']} jogo(s) · {est['requisicoes']} requisição(ões) · provedores: {', '.join(provs)}")
    print(f"  com imagem: {est['comImagem']} (capa: {est['capa']}, ilustrativa: {est['ilustrativa']}) por provedor {est['porProvedor'] or 'nenhum'} · sem candidato: {est['semP18']} · rejeitadas: {est['rejeitadas'] or 'nenhuma'}")
    if novos:
        print(f"  cobertura do lote: {100 * est['comImagem'] / novos:.0f}% ({est['comImagem']}/{novos}); os demais usam placeholder e só são reconsultados após {RETENTAR_DIAS} dias")
    print("Só licença livre conferida (CC0, domínio público, CC BY, CC BY-SA) e nome do jogo conferido; 'ilustrativa' NÃO é capa oficial. Cache local em local/capas/ (fora do Git).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
