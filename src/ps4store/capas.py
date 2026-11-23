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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import busca, unificada, versoes, cusas, wikidata

DIR_PADRAO = "local/capas"
SCHEMA = "ps4store.capas/v1"
HOSTS = {"query.wikidata.org", "commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"}   # thumb.wikimedia.org: domínio das miniaturas devolvidas pelo Commons
WIKIPEDIA_RE = re.compile(r"^[a-z]{2,3}\.wikipedia\.org$")          # Wikipedia em qualquer idioma (só leitura da API pública)
RETENTAR_DIAS = 14                                                  # jogo sem imagem não é consultado de novo antes disso
MAX_BUSCAS_COMMONS = 15                                             # buscas por nome (1 requisição cada) por execução
PROVEDORES = ("wikidata-p18", "wikidata-outras", "wikipedia", "commons-categoria", "commons-busca")
MAX_AMOSTRA = 30
MAX_BYTES = 400 * 1024
LARGURA = 330                                                       # tamanho de miniatura padrão do Wikimedia (larguras fora da lista oficial podem receber HTTP 429)
IMPORTADOR_VERSAO = 2                                               # registros negativos de versões anteriores são reavaliados automaticamente
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


class ErroHttp(OSError):
    """Falha de rede/HTTP com causa legível (código, motivo, Retry-After); sem URL, cabeçalhos ou dados do usuário."""

    def __init__(self, codigo: int, motivo: str, retry_after: str = ""):
        self.codigo, self.motivo, self.retry_after = codigo, motivo, retry_after
        super().__init__(self.descricao())

    def descricao(self) -> str:
        return (f"HTTP {self.codigo} {self.motivo}" if self.codigo else self.motivo) + (f" (Retry-After {self.retry_after})" if self.retry_after else "")


def _host_permitido(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and bool(p.hostname) and (p.hostname in HOSTS or bool(WIKIPEDIA_RE.match(p.hostname)))


class _RedirecionamentoRestrito(urllib.request.HTTPRedirectHandler):
    """Redirecionamento só para https e para a mesma lista de domínios; qualquer outro destino é recusado."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destino = urllib.parse.urljoin(req.full_url, newurl)
        if not _host_permitido(destino):
            raise ValueError(f"redirecionamento para host não permitido: {urllib.parse.urlsplit(destino).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, destino)


_ABRIR = urllib.request.build_opener(_RedirecionamentoRestrito).open


def _http(url: str, ua: str, maximo: int, timeout: int = 60, dormir=time.sleep) -> bytes:
    if not _host_permitido(url):
        raise ValueError(f"host não permitido: {urllib.parse.urlsplit(url).hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    for tentativa in (0, 1):
        try:
            with _ABRIR(req, timeout=timeout) as r:
                corpo = r.read(maximo + 1)
            break
        except urllib.error.HTTPError as e:
            ra = (e.headers.get("Retry-After") or "")[:10] if e.headers else ""
            if e.code in (429, 503) and tentativa == 0:                  # limite de taxa: espera e tenta UMA vez
                dormir(min(int(ra) if ra.isdigit() else 5, 20))
                continue
            raise ErroHttp(e.code, str(e.reason)[:40], ra) from None
        except urllib.error.URLError as e:
            raise ErroHttp(0, "rede:" + type(e.reason).__name__ if not isinstance(e.reason, str) else "rede:" + e.reason[:40]) from None
        except TimeoutError:
            raise ErroHttp(0, "rede:timeout") from None
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


def _buscar_commons(i: dict, req) -> tuple[list[dict], int]:
    """Busca no Commons pelo NOME e confere: nome do arquivo = nome do jogo (sem sobras) + indício de videogame + ano. Devolve páginas aprovadas."""
    url = (COMMONS_API + "&generator=search&gsrnamespace=6&gsrlimit=6&gsrsearch=" + urllib.parse.quote(f'"{i["nome"]}" game'))
    d = json.loads(req(url, 2_000_000)).get("query", {})
    ok = []
    todos = [p for p in d.get("pages", {}).values() if "imageinfo" in p]
    for p in todos:
        if confere_titulo_arquivo(i["nome"], i["ano"], p.get("title", "")) and _VG.search(_texto_pagina(p) + " " + p.get("title", "")):
            ok.append(p)
    return ok, len(todos)


RUIDO_ARTIGO = re.compile(r"flag|icon|symbol|esrb|pegi|cero|usk|acb|playstation|xbox|nintendo|steam|wiki|commons|question|portal|ambox|edit-|folder|stub|searchtool|disambig|padlock", re.I)
MIN_LADO = 200                                                      # imagens de artigo/categoria menores que isto são ícones, não imagens do jogo


def _ids_wikidata(pend: list[dict], req) -> dict[str, dict]:
    """UMA consulta ao Wikidata devolve, por Q-id (identificação inequívoca): P18 (imagem), P154 (logo), P2716 (colagem), P373 (categoria do Commons) e artigos en/pt da Wikipedia."""
    gs = " ".join(f"wd:{i['qid']}" for i in pend)
    q = ("SELECT ?g ?k ?v WHERE { VALUES ?g { " + gs + " } "
         '{ ?g wdt:P18 ?v . BIND("p18" AS ?k) } UNION { ?g wdt:P154 ?v . BIND("logo" AS ?k) } UNION { ?g wdt:P2716 ?v . BIND("colagem" AS ?k) } '
         'UNION { ?g wdt:P373 ?v . BIND("cat" AS ?k) } '
         'UNION { ?a schema:about ?g ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?v . BIND("wen" AS ?k) } '
         'UNION { ?a schema:about ?g ; schema:isPartOf <https://pt.wikipedia.org/> ; schema:name ?v . BIND("wpt" AS ?k) } } ORDER BY ?g ?k ?v')
    out: dict[str, dict] = {}
    for b in json.loads(req(wikidata.url_consulta(q), 3_000_000))["results"]["bindings"]:
        m = re.search(r"/(Q[0-9]+)$", b["g"]["value"])
        if not m:
            continue
        k, v = b["k"]["value"], b["v"]["value"]
        if k in ("p18", "logo", "colagem"):
            v = _arquivo_de_p18(v)
        if v:
            out.setdefault(m.group(1), {}).setdefault(k, []).append(v)
    return out


def _cand_imagens(ids: dict, chaves: tuple[str, ...], rotulo: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    return {q: [("File:" + f, rotulo[k]) for k in chaves for f in d.get(k, [])[:2]] for q, d in ids.items() if any(d.get(k) for k in chaves)}


def _cand_wikipedia(ids: dict, abertos: list[str], req) -> dict[str, list[tuple[str, str]]]:
    """Imagens do ARTIGO da Wikipedia ligado ao Q-id pelo Wikidata (sitelink; nada de busca por texto). Só entram arquivos que estejam no Commons (livres) e não pareçam ícones."""
    por_host: dict[str, list[tuple[str, str]]] = {}
    for q in abertos:
        for k, host in (("wen", "en.wikipedia.org"), ("wpt", "pt.wikipedia.org")):
            for t in ids.get(q, {}).get(k, [])[:1]:
                por_host.setdefault(host, []).append((q, t))
    out: dict[str, list] = {}
    for host, lista in por_host.items():
        for k in range(0, len(lista), 20):
            lote = lista[k:k + 20]
            url = (f"https://{host}/w/api.php?action=query&format=json&prop=pageimages%7Cimages&piprop=name&imlimit=30&redirects=1&titles=" + urllib.parse.quote("|".join(t for _, t in lote)))
            d = json.loads(req(url, 2_000_000)).get("query", {})
            mapa = {n["from"]: n["to"] for n in d.get("normalized", []) + d.get("redirects", [])}
            pgs = {p.get("title"): p for p in d.get("pages", {}).values()}
            for q, t in lote:
                p = pgs.get(mapa.get(mapa.get(t, t), mapa.get(t, t))) or {}
                arqs = ([p["pageimage"].replace("_", " ")] if p.get("pageimage") else []) + [i["title"].removeprefix("File:") for i in p.get("images", [])]
                vistos, cs = set(), []
                for a in arqs:
                    if a not in vistos and not RUIDO_ARTIGO.search(a) and re.search(r"\.(jpe?g|png|webp)$", a, re.I):
                        vistos.add(a)
                        cs.append(("File:" + a, f"imagem do artigo \"{t}\" ({host}), ligado ao Q-id pelo Wikidata"))
                if cs:
                    out.setdefault(q, []).extend(cs[:5])
    return out


def _cand_categoria(i: dict, cat: str, req) -> list[dict]:
    """Arquivos da categoria do Commons que o Wikidata (P373) associa ao Q-id."""
    url = COMMONS_API + "&generator=categorymembers&gcmtype=file&gcmlimit=8&gcmtitle=" + urllib.parse.quote("Category:" + cat.removeprefix("Category:"))
    d = json.loads(req(url, 2_000_000)).get("query", {})
    return [p for p in d.get("pages", {}).values() if "imageinfo" in p and not RUIDO_ARTIGO.search(p.get("title", ""))]


def _lado_ok(p: dict) -> bool:
    info = (p.get("imageinfo") or [{}])[0]
    return min(info.get("width") or 0, info.get("height") or 0) >= MIN_LADO


def _gravar(q: str, reg: dict, req, diretorio: str, idx: dict) -> str | None:
    """Baixa a miniatura do registro aprovado e grava. None = gravou; senão, o motivo REAL da falha (HTTP/rede)."""
    try:
        dados = req(reg["thumbUrl"], MAX_BYTES)
    except RuntimeError:
        raise
    except ErroHttp as e:
        return f"download-falhou:{e.descricao()}"
    except (OSError, ValueError) as e:
        return f"download-falhou:{type(e).__name__}: {str(e)[:60]}"
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
    """Negativo ainda vale? Não vale se foi gravado por versão antiga do importador; falha de download é refeita em 1 dia; o resto em RETENTAR_DIAS."""
    if (s.get("versao") or 1) < IMPORTADOR_VERSAO:
        return False
    try:
        t = datetime.fromisoformat(s.get("consultadoEm", ""))
    except ValueError:
        return False
    if "host não permitido" in str(s.get("motivo", "")) or any("host não permitido" in str(t) for t in s.get("tentativas", [])):
        return False                                                # bloqueio do próprio importador (já corrigido), não resposta da fonte
    dias = 1 if str(s.get("motivo", "")).startswith("download-falhou") else RETENTAR_DIAS
    return (datetime.now(timezone.utc) - t).days < dias


def pendentes(qids: list, idx: dict, forcar: bool = False, reavaliar: bool = False) -> list[dict]:
    """Quem precisa de consulta: sem imagem (imagens válidas nunca são apagadas nem refeitas) e sem negativo ainda válido."""
    out = []
    for x in qids:
        i = _item(x)
        if forcar or (i["qid"] not in idx["capas"] and (reavaliar or not (i["qid"] in idx["semImagem"] and _recente(idx["semImagem"][i["qid"]])))):
            out.append(i)
    return out


def importar(qids: list, fetch, diretorio: str, pausa: float = 1.0, dormir=time.sleep, max_req: int = 120, forcar: bool = False, provedores=PROVEDORES, reavaliar: bool = False) -> dict:
    """`qids` = [(qid, nome[, ano[, url do índice]])]. `fetch(url, maximo) -> bytes` injetável. Provedores em ordem; cada um só vê quem ainda está sem imagem.
    Identificação por Q-id (Wikidata) dispensa conferir o nome no arquivo; só a busca por texto (commons-busca) exige correspondência literal."""
    idx = carregar_indice(diretorio)
    pend = pendentes(qids, idx, forcar, reavaliar)
    est = {"consultados": len(qids), "jaTinham": len(qids) - len(pend), "comImagem": 0, "capa": 0, "ilustrativa": 0, "rejeitadas": {}, "semP18": 0, "requisicoes": 0,
           "porProvedor": {}, "falhasDownload": {}}
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

    def nota(q, prov, texto):
        motivos.setdefault(q, []).append(f"{prov}:{texto}")

    def tentar(q: str, prov: str, paginas: list[tuple[dict, str]]) -> bool:
        regs = []
        for p, corr in paginas:
            av = avaliar_arquivo(p)
            if not av["aceita"]:
                nota(q, prov, av["motivo"])
                continue
            r = av["registro"]
            if not r["thumbUrl"]:
                nota(q, prov, "sem-miniatura")
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
            nota(q, prov, falha)
            if falha.startswith("download-falhou"):
                k = falha.split(":", 1)[1].split(" (")[0]
                est["falhasDownload"][k] = est["falhasDownload"].get(k, 0) + 1
        return False

    def fechar(q):
        nonlocal aberto
        aberto = [x for x in aberto if x != q]

    def por_arquivos(prov: str, cand: dict[str, list[tuple[str, str]]], min_lado: bool = False) -> None:
        qs = [q for q in aberto if q in cand]
        todos = sorted({t for q in qs for t, _ in cand[q]})
        pgs: dict[str, dict] = {}
        for k in range(0, len(todos), 10):
            pgs.update(_paginas_commons(todos[k:k + 10], req))
        for q in qs:
            achados = [(pgs[t], c) for t, c in cand[q] if t in pgs]
            if min_lado:
                achados = [(p, c) for p, c in achados if _lado_ok(p)]
            if not achados:
                nota(q, prov, "arquivos-fora-do-commons-ou-pequenos (uso justo local não é reutilizável)" if min_lado else "arquivo-ausente-no-commons")
            elif tentar(q, prov, achados):
                fechar(q)

    def sem_candidato(prov, antes):
        for q in antes:
            if q in aberto and not any(m.startswith(prov + ":") for m in motivos.get(q, [])):
                nota(q, prov, "sem-candidato")

    ids: dict[str, dict] = {}
    try:
        if pend and any(p in provedores for p in ("wikidata-p18", "wikidata-outras", "wikipedia", "commons-categoria")):
            ids = _ids_wikidata(pend, req)
        if "wikidata-p18" in provedores and aberto:
            antes = list(aberto)
            por_arquivos("wikidata-p18", _cand_imagens(ids, ("p18",), {"p18": "imagem (P18) do Q-id no Wikidata"}))
            sem_candidato("wikidata-p18", antes)
        if "wikidata-outras" in provedores and aberto:
            antes = list(aberto)
            por_arquivos("wikidata-outras", _cand_imagens(ids, ("logo", "colagem"), {"logo": "logo (P154) do Q-id no Wikidata", "colagem": "colagem (P2716) do Q-id no Wikidata"}))
            sem_candidato("wikidata-outras", antes)
        if "wikipedia" in provedores and aberto:
            antes = list(aberto)
            por_arquivos("wikipedia", _cand_wikipedia(ids, aberto, req), min_lado=True)
            sem_candidato("wikipedia", antes)
        if "commons-categoria" in provedores and aberto:
            antes = list(aberto)
            for q in [x for x in aberto if ids.get(x, {}).get("cat")][:MAX_BUSCAS_COMMONS]:
                ps = [(p, f"arquivo da categoria \"{ids[q]['cat'][0]}\" (P373) do Q-id no Wikidata") for p in _cand_categoria(ctx[q], ids[q]["cat"][0], req) if _lado_ok(p)]
                if ps and tentar(q, "commons-categoria", ps):
                    fechar(q)
            sem_candidato("commons-categoria", antes)
        if "commons-busca" in provedores and aberto:
            antes = list(aberto)
            for q in list(aberto)[:MAX_BUSCAS_COMMONS]:
                ok, n = _buscar_commons(ctx[q], req)
                achados = [(p, "nome do arquivo = nome do jogo, indício de videogame, ano conferido") for p in ok]
                if n and not achados:
                    nota(q, "commons-busca", f"sem-correspondencia ({n} resultado(s) descartado(s) pela conferência do nome)")
                if achados and tentar(q, "commons-busca", achados):
                    fechar(q)
            sem_candidato("commons-busca", antes)
    finally:
        for q in aberto:
            ms = motivos.get(q) or []
            reais = [m for m in ms if not m.endswith(":sem-candidato")]
            if reais:
                k = reais[0].split(":", 1)[1].split(":")[0].split(" (")[0]
                est["rejeitadas"][k] = est["rejeitadas"].get(k, 0) + 1
                idx["semImagem"][q] = {"motivo": reais[0].split(":", 1)[1], "tentativas": ms[:10], "consultadoEm": agora(), "versao": IMPORTADOR_VERSAO}
            elif ms:                                               # todos os provedores consultados responderam "sem candidato"
                est["semP18"] += 1
                idx["semImagem"][q] = {"motivo": "sem-candidato", "tentativas": ms[:10], "consultadoEm": agora(), "versao": IMPORTADOR_VERSAO}
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


def diagnosticar(a, fetch=None, dormir=time.sleep) -> int:
    """Passo a passo para N jogos (sem gravar): o que o Wikidata devolve, o que o Commons diz da licença/tamanho e o resultado REAL do download (código HTTP)."""
    n = max(1, min(a.diagnostico, 8))
    try:
        amostra = escolher_amostra(busca.carregar_indice(a.indice), versoes.carregar(a.versoes), cusas.carregar_dados(a.cusas), [x.strip() for x in a.jogos.split(",") if x.strip()], n)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    f = fetch or (lambda u, m: _http(u, a.user_agent, m))
    usadas = [0]

    def req(url, maximo):
        if usadas[0]:
            dormir(a.pausa)
        usadas[0] += 1
        return f(url, maximo)

    pend = [_item(x) for x in amostra]
    try:
        ids = _ids_wikidata(pend, req)
    except (OSError, ValueError, KeyError) as e:
        print(f"ERRO no Wikidata: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr)
        return 1
    for i in pend:
        d = ids.get(i["qid"], {})
        print(f"{i['qid']} {i['nome']}: " + (", ".join(f"{k}={len(v)}" for k, v in d.items()) or "NENHUM dado de imagem/artigo/categoria no Wikidata"))
        titulo = next((("File:" + d[k][0]) for k in ("p18", "logo", "colagem") if d.get(k)), None)
        if not titulo:
            continue
        try:
            pg = _paginas_commons([titulo], req).get(titulo)
            if not pg:
                print(f"    {titulo}: não está no Commons")
                continue
            av = avaliar_arquivo(pg)
            info = pg["imageinfo"][0]
            print(f"    {titulo}: licença='{_meta(info.get('extmetadata') or {}, 'LicenseShortName')}' -> {'ACEITA' if av['aceita'] else 'rejeitada: ' + av['motivo']} · {info.get('width')}x{info.get('height')}")
            if av["aceita"]:
                dados = req(av["registro"]["thumbUrl"], MAX_BYTES)
                print(f"    download: OK, {len(dados)} bytes, formato {tipo_da_imagem(dados)}")
        except ErroHttp as e:
            print(f"    FALHA {e.descricao()}")
        except (OSError, ValueError) as e:
            print(f"    FALHA {type(e).__name__}: {str(e)[:100]}")
    print(f"({usadas[0]} requisições; nada foi gravado)")
    return 0


def main(argv=None, fetch=None, dormir=time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.capas", description="importa miniaturas (Wikidata P18, Wikipedia, Commons; licença e jogo conferidos); fila progressiva de até 30 jogos por execução")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--amostra", "--fila", type=int, nargs="?", const=MAX_AMOSTRA, metavar="N", dest="amostra", help=f"processa até N jogos sem imagem (máx. {MAX_AMOSTRA}); rode de novo para avançar")
    g.add_argument("--status", action="store_true", help="resume o que já foi importado (sem rede), com os motivos por jogo")
    g.add_argument("--diagnostico", type=int, nargs="?", const=5, metavar="N", help="mostra, passo a passo, o que cada fonte devolve para N jogos (máx. 8), sem gravar nada")
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
    ap.add_argument("--reavaliar", action="store_true", help="refaz a consulta dos jogos marcados 'sem imagem' (nunca apaga nem refaz imagens válidas); versões antigas já são reavaliadas sozinhas")
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
        antigos = sum(1 for s_ in idx["semImagem"].values() if (s_.get("versao") or 1) < IMPORTADOR_VERSAO)
        if antigos:
            print(f"  {antigos} registro(s) negativo(s) de versão antiga do importador: serão reavaliados na próxima fila (imagens válidas não são tocadas)")
        for q, s_ in list(idx["semImagem"].items())[:12]:
            print(f"  {q}: {s_['motivo']} | " + "; ".join(s_.get("tentativas", [])[:6]))
        return 0
    if a.diagnostico is not None:
        return diagnosticar(a, fetch, dormir)
    provs = [x.strip() for x in a.provedores.split(",") if x.strip()]
    if not provs or any(x not in PROVEDORES for x in provs):
        print(f"ERRO  provedores válidos: {', '.join(PROVEDORES)}", file=sys.stderr)
        return 2
    try:
        indice = busca.carregar_indice(a.indice)
        idx0 = carregar_indice(a.dir)
        feitos = set(idx0["capas"]) | (set() if a.reavaliar else {q for q, s_ in idx0["semImagem"].items() if _recente(s_)})
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
        est = importar(amostra, f, a.dir, a.pausa, dormir, max(1, a.max_requisicoes), a.forcar, tuple(provs), a.reavaliar)
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print(f"ERRO  {type(e).__name__}: {str(e)[:200]} (o que já foi gravado fica no cache; rode de novo)", file=sys.stderr)
        return 1
    novos = est["consultados"] - est["jaTinham"]
    print(f"Lote: {est['consultados']} jogo(s) · {est['requisicoes']} requisição(ões) · provedores: {', '.join(provs)}")
    print(f"  com imagem: {est['comImagem']} (capa: {est['capa']}, ilustrativa: {est['ilustrativa']}) por provedor {est['porProvedor'] or 'nenhum'} · sem candidato em nenhuma fonte: {est['semP18']} · rejeitadas: {est['rejeitadas'] or 'nenhuma'}")
    if est["falhasDownload"]:
        print(f"  falhas de download (causa real): {est['falhasDownload']}")
    if novos:
        print(f"  cobertura do lote: {100 * est['comImagem'] / novos:.0f}% ({est['comImagem']}/{novos}); os demais usam placeholder e só são reconsultados após {RETENTAR_DIAS} dias")
    print("Só licença livre conferida (CC0, domínio público, CC BY, CC BY-SA) e nome do jogo conferido; 'ilustrativa' NÃO é capa oficial. Cache local em local/capas/ (fora do Git).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
