"""METADADOS (5H): enriquecimento incremental por CUSA / Content ID / Q-id, com cache local e grau de confirmação por campo.

Fontes (só leitura, sem chave, sem pagamento):
  sony      servidor OFICIAL de atualizações do PS4 (XML `<CUSA>-ver.xml`): versão da atualização (patch) mais recente, tamanho, firmware exigido,
            Content ID e título. O endereço do XML é derivado do CUSA (HMAC-SHA256, como o console faz); é metadado público, não há download de pacote.
  wikidata  P407 (idioma da obra) com o qualificador P518 (parte: dublagem/legendas/interface) e a etiqueta IETF do idioma (P305): pt-BR ≠ pt-PT ≠ pt.
  loja      página do produto na PlayStation Store (por Content ID), só se o robots.txt da loja permitir: listas de idiomas de áudio e de tela.
Regras: não inventa (ausente = desconhecido); idioma NUNCA vem da região; 'português' sem variante fica como está; versão do patch ≠ versão do jogo-base
≠ versão do PKG; firmware só o que a fonte declara (compatibilidade com 9.00 não é presumida). Os registros curados (data/versoes-cusa.json) não são
alterados: estes metadados ficam em local/metadados.json, ao lado, com fonte, URL, data e grau. Nada de conflito auditado é resolvido aqui.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from . import busca, capas, cusas, unificada, versoes, wikidata

SCHEMA = "ps4store.metadados/v1"
ARQ_PADRAO = "local/metadados.json"
FONTES = ("sony", "wikidata")                                       # padrão
FONTES_VALIDAS = ("sony", "wikidata", "loja")                       # loja: experimental (no teste real só deu "sem-idiomas": idiomas montados dinamicamente)
OFICIAIS_PADRAO = "data/metadados-oficiais.json"
SCHEMA_OFICIAIS = "ps4store.oficiais/v1"
PARTES_OFICIAIS = ("audio", "texto", "legendas", "geral")
MAX_JOGOS = 30
RECONSULTAR_DIAS = 7
SONY_HOST = "gs-sec.ww.np.dl.playstation.net"
# Chave HMAC pública usada pelos consoles/ferramentas para derivar o caminho do XML de atualização (não é credencial nem autenticação).
SONY_HMAC = bytes.fromhex("AD62E37F905E06BC19593142281C112CEC0E7EC3E97EFDCAEFCDBAAFA6378D84")
HOSTS = {"query.wikidata.org", "store.playstation.com", SONY_HOST}
CUSA_RE = versoes.CUSA_RE
CID_RE = versoes.CONTENT_ID_RE
LOJAS_POR_PREFIXO = {"UP": ("pt-br", "en-us"), "EP": ("pt-pt", "en-gb"), "JP": ("ja-jp",), "HP": ("en-hk",), "KP": ("ko-kr",)}


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def vazio() -> dict:
    return {"schema": SCHEMA, "atualizacoes": {}, "idiomas": {}, "loja": {}}


def carregar(caminho: str = ARQ_PADRAO) -> dict:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vazio()
    if d.get("schema") != SCHEMA:
        return vazio()
    for k in ("atualizacoes", "idiomas", "loja"):
        d.setdefault(k, {})
    return d


def salvar(doc: dict, caminho: str = ARQ_PADRAO) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _recente(reg: dict | None, dias: int = RECONSULTAR_DIAS) -> bool:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(reg["consultadoEm"])).days < dias
    except (TypeError, KeyError, ValueError):
        return False


# ---------- rede (lista fechada de hosts, HTTPS; HTTP só para o servidor da Sony e só com opção explícita) ----------
class _Redir(urllib.request.HTTPRedirectHandler):
    def __init__(self, permitir_http: bool):
        self.permitir_http = permitir_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destino = urllib.parse.urljoin(req.full_url, newurl)
        if not url_permitida(destino, self.permitir_http):
            raise ValueError(f"redirecionamento para destino não permitido: {urllib.parse.urlsplit(destino).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, destino)


def url_permitida(url: str, permitir_http: bool = False) -> bool:
    p = urllib.parse.urlsplit(url)
    if p.hostname not in HOSTS or p.username or p.password:
        return False
    return p.scheme == "https" or (permitir_http and p.scheme == "http" and p.hostname == SONY_HOST)


def http_get(url: str, ua: str, maximo: int, permitir_http: bool = False, timeout: int = 30) -> tuple[int, bytes]:
    """(status, corpo). 404 volta como (404, b''); outros erros viram capas.ErroHttp com causa legível."""
    if not url_permitida(url, permitir_http):
        raise ValueError(f"destino não permitido: {urllib.parse.urlsplit(url).hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.build_opener(_Redir(permitir_http)).open(req, timeout=timeout) as r:
            corpo = r.read(maximo + 1)
            st = r.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, b""
        raise capas.ErroHttp(e.code, str(e.reason)[:40]) from None
    except urllib.error.URLError as e:
        motivo = e.reason
        nome = type(motivo).__name__
        if "Certificate" in nome or "SSL" in nome:                  # validação continua LIGADA; só registramos o porquê (ex.: emissor não confiável)
            det = getattr(motivo, "verify_message", "") or getattr(motivo, "reason", "") or ""
            raise capas.ErroHttp(0, "tls:certificado-nao-verificado" + (f" ({str(det)[:60]})" if det else "")) from None
        raise capas.ErroHttp(0, f"rede:{nome if not isinstance(motivo, str) else motivo[:40]}") from None
    except TimeoutError:
        raise capas.ErroHttp(0, "rede:timeout") from None
    if len(corpo) > maximo:
        raise ValueError("resposta maior que o limite")
    return st, corpo


# ---------- Sony: XML de atualização ----------
def url_xml_sony(cusa: str, esquema: str = "https") -> str:
    if not CUSA_RE.match(cusa):
        raise ValueError("CUSA inválido")
    h = hmac.new(SONY_HMAC, ("np_" + cusa).encode(), hashlib.sha256).hexdigest()
    return f"{esquema}://{SONY_HOST}/plo/np/{cusa}/{h}/{cusa}-ver.xml"


def firmware(bruto: str | None) -> str | None:
    """system_ver (ex.: 0x05050000 ou o mesmo número em decimal) -> '5.05'. None se ausente/ilegível."""
    try:
        v = int(str(bruto), 0)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return f"{(v >> 24) & 0xFF:x}.{(v >> 16) & 0xFF:02x}"


def acima_de(fw: str | None, ref: str = "9.00") -> bool | None:
    if not fw:
        return None
    a, b = (tuple(int(x) for x in s.split(".")) for s in (fw, ref))
    return a > b


def ler_xml_sony(corpo: bytes) -> dict:
    """Lê o XML oficial; recusa DTD/entidades. Devolve campos do pacote mais recente (o servidor lista só a atualização atual)."""
    if b"<!DOCTYPE" in corpo or b"<!ENTITY" in corpo:
        raise ValueError("XML com DTD/entidades recusado")
    raiz = ET.fromstring(corpo)
    pkg = raiz.find(".//package")
    if pkg is None:
        return {}
    titulo = pkg.findtext("./paramsfo/title") or ""
    fw = firmware(pkg.get("system_ver"))
    tam = pkg.get("size")
    return {"versao": pkg.get("version"), "tamanhoBytes": int(tam) if (tam or "").isdigit() else None, "firmwareMinimo": fw,
            "firmwareBruto": pkg.get("system_ver"), "firmwareAcimaDe900": acima_de(fw), "contentId": pkg.get("content_id"),
            "titulo": titulo.strip()[:200], "tipo": pkg.get("type") or None, "obrigatoria": (raiz.find(".//tag") is not None and raiz.find(".//tag").get("mandatory") == "true")}


def consultar_sony(cusa: str, get, permitir_http: bool = False, anterior: dict | None = None) -> dict:
    base = {"fonte": "Sony (servidor oficial de atualizações do PS4)", "grau": "oficial", "consultadoEm": agora(), "url": url_xml_sony(cusa)}
    try:
        st, corpo = get(url_xml_sony(cusa), 1_000_000)
    except capas.ErroHttp as e:
        if permitir_http and e.motivo.startswith("tls"):
            st, corpo = get(url_xml_sony(cusa, "http"), 1_000_000)
            base.update(url=url_xml_sony(cusa, "http"), grau="oficial-via-http", nota="obtido por HTTP (sem TLS): integridade não verificada")
        else:
            return dict(base, status="erro", erro=e.descricao())
    if st == 404 or not corpo.strip():
        return dict(base, status="sem-atualizacao", nota="o servidor não lista atualização para este CUSA (nenhum patch publicado, ou título desconhecido)")
    try:
        dados = ler_xml_sony(corpo)
    except (ET.ParseError, ValueError) as e:
        return dict(base, status="erro", erro=f"XML ilegível ({type(e).__name__})")
    if not dados.get("versao"):
        return dict(base, status="sem-atualizacao", nota="XML sem pacote")
    if dados.get("contentId") and CID_RE.match(dados["contentId"]) and CID_RE.match(dados["contentId"]).group(2) != cusa:
        return dict(base, status="erro", erro=f"o XML descreve outro CUSA ({dados['contentId']}): descartado")
    hist = list((anterior or {}).get("historico", []))
    if anterior and anterior.get("versao") and anterior["versao"] != dados["versao"]:
        hist.append({"versao": anterior["versao"], "vistoEm": anterior.get("consultadoEm")})
    return dict(base, status="ok", historico=hist[-20:], **dados)


# ---------- Wikidata: idiomas com parte (áudio/legendas/interface) ----------
def _parte(rotulo: str) -> str:
    r = (rotulo or "").lower()
    if re.search(r"voice|dubb|audio|spoken|narration", r):
        return "audio"
    if re.search(r"subtit|caption", r):
        return "legendas"
    if re.search(r"interface|text|menu|screen", r):
        return "texto"
    return "nao-especificada"


def variante(tag_ou_nome: str) -> str | None:
    """'pt-BR' | 'pt-PT' | 'pt' (sem variante) | None (não é português). Aceita etiqueta IETF ou nome (pt/en)."""
    t = (tag_ou_nome or "").strip().lower().replace("_", "-")
    n = busca.norm(t)
    if t in ("pt-br",) or re.search(r"\bbrazil|brasil|brasileiro", n):
        return "pt-BR"
    if t in ("pt-pt",) or re.search(r"portugal|europeu|european portuguese", n):
        return "pt-PT"
    if t == "pt" or n in ("portugues", "portuguese"):
        return "pt"
    return None


def consultar_idiomas_wikidata(qids: list[str], fetch) -> dict[str, dict]:
    vals = " ".join(f"wd:{q}" for q in qids)
    q = ("SELECT ?g ?tag ?parteLab WHERE { VALUES ?g { " + vals + " } ?g p:P407 ?st . ?st ps:P407 ?l . ?l wdt:P305 ?tag . "
         'OPTIONAL { ?st pq:P518 ?pt . ?pt rdfs:label ?parteLab . FILTER(LANG(?parteLab) = "en") } }')
    linhas = json.loads(fetch(wikidata.url_consulta(q), 5_000_000)[1])["results"]["bindings"]
    out = {g: {"fonte": "Wikidata (P407 + P518)", "grau": "alegado", "consultadoEm": agora(), "url": f"https://www.wikidata.org/wiki/{g}", "itens": []} for g in qids}
    for b in linhas:
        m = re.search(r"/(Q[0-9]+)$", b["g"]["value"])
        if not m or m.group(1) not in out:
            continue
        it = {"tag": b["tag"]["value"][:20], "parte": _parte(b.get("parteLab", {}).get("value", "")), "parteRotulo": b.get("parteLab", {}).get("value", "")[:40]}
        if it not in out[m.group(1)]["itens"]:
            out[m.group(1)]["itens"].append(it)
    return out


# ---------- PlayStation Store: idiomas do produto ----------
_LISTA = r'"%s"\s*:\s*\[([^\]]{0,4000})\]'


def ler_pagina_loja(html: str) -> dict:
    """Listas 'spokenLanguages' (áudio) e 'screenLanguages' (tela: texto e/ou legendas, a loja não separa) do JSON embutido. Ausente = desconhecido."""
    out = {}
    for campo, chave in (("audio", "spokenLanguages"), ("tela", "screenLanguages")):
        m = re.search(_LISTA % chave, html)
        if m:
            out[campo] = [x[:30] for x in re.findall(r'"([^"]{1,40})"', m.group(1))][:80]
    return out


def consultar_loja(cid: str, get, robots) -> dict:
    m = CID_RE.match(cid)
    if not m:
        return {"status": "erro", "erro": "Content ID inválido", "consultadoEm": agora()}
    ultimo = None
    for loja in LOJAS_POR_PREFIXO.get(m.group(1), ("en-us",)):
        url = f"https://store.playstation.com/{loja}/product/{cid}"
        base = {"fonte": f"PlayStation Store ({loja})", "grau": "oficial", "consultadoEm": agora(), "url": url}
        if not robots(url):
            return dict(base, status="nao-autorizado", nota="o robots.txt da loja não permite este caminho: não consultado")
        try:
            st, corpo = get(url, 3_000_000)
        except capas.ErroHttp as e:
            ultimo = dict(base, status="erro", erro=e.descricao())
            continue
        if st == 404:
            ultimo = dict(base, status="nao-encontrado")
            continue
        dados = ler_pagina_loja(corpo.decode("utf-8", "replace"))
        if not dados:
            return dict(base, status="sem-idiomas", nota="a página não trouxe as listas de idiomas (formato desconhecido ou conteúdo montado por JavaScript)")
        return dict(base, status="ok", **dados)
    return ultimo or {"status": "erro", "erro": "nenhuma loja consultada", "consultadoEm": agora()}


# ---------- metadados oficiais por CUSA (curados, versionados em data/) ----------
def validar_oficiais(doc: dict) -> list[str]:
    e = []
    if doc.get("schema") != SCHEMA_OFICIAIS or not isinstance(doc.get("produtos"), list):
        return [f"não é um arquivo {SCHEMA_OFICIAIS}"]
    for i, p in enumerate(doc["produtos"], 1):
        if not CUSA_RE.match(str(p.get("cusa", ""))):
            e.append(f"produto {i}: cusa inválido")
        if not str(p.get("escopo", "")).strip():
            e.append(f"produto {i}: escopo obrigatório (ex.: edição física das Américas)")
        u = urllib.parse.urlsplit(str(p.get("url", "")))
        if u.scheme != "https" or not u.hostname or not str(p.get("fonte", "")).strip():
            e.append(f"produto {i}: fonte e url https obrigatórias")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(p.get("obtidoEm", ""))):
            e.append(f"produto {i}: obtidoEm AAAA-MM-DD")
        idi = p.get("idiomas")
        if not isinstance(idi, dict) or not idi or any(k not in PARTES_OFICIAIS or not isinstance(v, list) or not v for k, v in idi.items()):
            e.append(f"produto {i}: idiomas = {{audio|texto|legendas|geral: [etiquetas]}}")
        if not isinstance(p.get("listaCompleta"), bool):
            e.append(f"produto {i}: listaCompleta deve ser true ou false")
    return e


def carregar_oficiais(caminho: str = OFICIAIS_PADRAO) -> dict:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA_OFICIAIS, "produtos": []}
    if validar_oficiais(d):
        raise ValueError(f"{caminho}: " + "; ".join(validar_oficiais(d)[:3]))
    return d


# ---------- classificação PT-BR (sem dedução por região; força da evidência explícita) ----------
PARTES = ("audio", "texto", "legendas", "tela")
GRAUS = {"desenvolvedor": "oficial do desenvolvedor, por CUSA", "loja": "página do produto na loja", "wikidata": "Wikidata (geral, não verificado)", "curado": "registro curado"}


def localizacao(qid: str, registros: list[dict], meta: dict, oficiais: dict | None = None) -> dict:
    """Por parte (audio|texto|legendas|tela): status confirmado (fonte oficial: desenvolvedor por CUSA ou loja por produto) | informado (só Wikidata,
    geral e não verificado) | nao-consta (fonte oficial com lista COMPLETA sem pt-BR) | desconhecido. Ausência nunca vira 'não'."""
    partes = {p: {"status": "desconhecido", "fontes": []} for p in PARTES}
    sem_parte, pt_pt, pt_sem = [], [], []
    ORD = {"confirmado": 3, "informado": 2, "nao-consta": 1, "desconhecido": 0}

    def marca(p, status, f):
        if ORD[status] > ORD[partes[p]["status"]]:
            partes[p]["status"] = status
        partes[p]["fontes"].append(dict(f, statusDaFonte=status))

    def fonte(reg, grau, extra="", cusa=None):
        return {"fonte": reg.get("fonte", "?") + extra, "grau": grau, "cusa": cusa, "rotuloGrau": GRAUS[grau], "url": reg.get("url", ""), "consultadoEm": reg.get("consultadoEm") or reg.get("obtidoEm", "")}

    cusas_jogo = list(dict.fromkeys(r["cusa"] for r in registros))
    for prod in (oficiais or {}).get("produtos", []):
        if prod["cusa"] not in cusas_jogo:
            continue
        f = fonte(prod, "desenvolvedor", f" · {prod['cusa']} ({prod['escopo']})", prod["cusa"])
        tem_pt = False
        for parte, lista in prod["idiomas"].items():
            vs = {variante(x) for x in lista}
            if "pt-BR" in vs:
                tem_pt = True
                if parte == "geral":
                    sem_parte.append(f)
                else:
                    marca(parte, "confirmado", f)
            if "pt-PT" in vs:
                pt_pt.append(f)
            if "pt" in vs:
                pt_sem.append(f)
        if prod.get("listaCompleta") and not tem_pt:
            for p in ("audio", "texto", "legendas"):
                marca(p, "nao-consta", f)
    wd = meta.get("idiomas", {}).get(qid)
    if wd:
        for it in wd.get("itens", []):
            v = variante(it["tag"])
            f = fonte(wd, "wikidata")
            if v == "pt-BR":
                (sem_parte.append(f) if it["parte"] == "nao-especificada" else marca(it["parte"], "informado", f))
            elif v == "pt-PT":
                pt_pt.append(fonte(wd, "wikidata", f" ({it['parte']})"))
            elif v == "pt":
                pt_sem.append(fonte(wd, "wikidata", f" ({it['parte']})"))
    for r in registros:
        cids = [c for c in ([r.get("contentId")] + list(r.get("contentIds") or [])) if c]
        for cid in dict.fromkeys(cids):
            lj = meta.get("loja", {}).get(cid)
            if not lj or lj.get("status") != "ok":
                continue
            for campo in ("audio", "tela"):
                lista = lj.get(campo)
                if lista is None:
                    continue
                vs = {variante(x) for x in lista}
                f = fonte(lj, "loja", f" · {cid}", CID_RE.match(cid).group(2) if CID_RE.match(cid) else None)
                if "pt-BR" in vs:
                    marca(campo, "confirmado", f)
                elif lista:
                    marca(campo, "nao-consta", f)
                if "pt-PT" in vs:
                    pt_pt.append(f)
                if "pt" in vs:
                    pt_sem.append(f)
    conf = [p for p in PARTES if partes[p]["status"] == "confirmado"]
    inf = [p for p in PARTES if partes[p]["status"] == "informado"]
    nomes = {"audio": "áudio", "texto": "texto", "legendas": "legendas", "tela": "texto/legendas (tela)"}
    oficial_sem_parte = any(f["grau"] in ("desenvolvedor", "loja") for f in sem_parte)
    if conf:
        cus = sorted({f["cusa"] for p in conf for f in partes[p]["fontes"] if f["statusDaFonte"] == "confirmado" and f.get("cusa")})
        resumo = "PT-BR confirmado por fonte oficial: " + ", ".join(nomes[p] for p in conf) + (f" (só em {', '.join(cus)})" if cus else "")
    elif oficial_sem_parte:
        resumo = "PT-BR informado por fonte oficial, sem dizer se é áudio, texto ou legendas"
    elif inf:
        resumo = "PT-BR só no Wikidata (geral, não verificado): " + ", ".join(nomes[p] for p in inf)
    elif sem_parte:
        resumo = "PT-BR mencionado sem parte (Wikidata/registro), não verificado"
    elif pt_sem:
        resumo = "português informado SEM variante (não classificado como PT-BR)"
    elif pt_pt:
        resumo = "só português europeu (pt-PT) informado"
    elif any(partes[p]["status"] == "nao-consta" for p in PARTES):
        resumo = "fonte oficial lista os idiomas e PT-BR não consta (vale para o produto/CUSA citado)"
    else:
        resumo = "desconhecido (nenhuma fonte consultada informa)"
    return {"partes": partes, "semParte": sem_parte, "ptPT": pt_pt, "ptSemVariante": pt_sem, "confirmadas": conf, "informadas": inf,
            "oficialSemParte": oficial_sem_parte, "resumo": resumo}


MODOS_PTBR = ("qualquer", "oficial", "audio", "texto")


def filtro_ptbr(loc: dict, modo: str) -> bool:
    """qualquer = qualquer menção a PT-BR (inclui Wikidata); oficial = fonte oficial (qualquer parte); audio/texto = parte confirmada por fonte oficial."""
    c = set(loc["confirmadas"])
    if modo == "audio":
        return "audio" in c
    if modo == "texto":
        return bool(c & {"texto", "legendas", "tela"})
    if modo == "oficial":
        return bool(c) or loc["oficialSemParte"]
    return bool(c) or bool(loc["informadas"]) or bool(loc["semParte"])


def selos_ptbr(loc: dict) -> list[str]:
    """Rótulos curtos para o card: 'oficial', 'audio' (oficial) ou 'wikidata' (só geral)."""
    if loc["confirmadas"] or loc["oficialSemParte"]:
        return ["oficial"] + (["audio"] if "audio" in loc["confirmadas"] else [])
    if loc["informadas"] or loc["semParte"]:
        return ["wikidata"]
    return []


# ---------- seleção de jogos: nome EXATO primeiro (sem encher a amostra com parecidos) ----------
def escolher_jogos(indice: dict, curados: dict, wd: dict, nomes: list[str], n: int, ignorar: set[str] | None = None, prioridade: list[str] | None = None,
                   apelidos: list[dict] | None = None) -> tuple[list[tuple], list[str]]:
    """Com --jogos: SÓ os jogos de nome exato (ou apelido com vínculo explícito), um por nome; nada parecido entra. Sem --jogos: interesse do painel,
    depois jogos com CUSA. Devolve (jogos, avisos)."""
    from . import busca_inteligente
    n = max(1, min(n, MAX_JOGOS))
    por_qid = unificada.agrupar(curados, wd)
    titulos = [t for t in indice.get("titulos", []) if str(t.get("idFonte", "")).startswith("wikidata:")]
    q_de = lambda t: t["idFonte"].split(":", 1)[1]
    out, avisos, vistos = [], [], set()

    def add(t):
        q = q_de(t)
        if q not in vistos and len(out) < n:
            vistos.add(q)
            out.append((q, t["nome"], t.get("lancamento"), t.get("url", "")))

    if nomes:
        motor = busca_inteligente.Motor(indice, apelidos or [])
        for nome in nomes:
            r = motor.buscar(nome, limite=50)
            alvo = busca.norm(nome)
            exatos = [t for t in r["itens"] if r["via"].get(id(t)) == "apelido" or busca.norm(t["nome"]) == alvo]
            exatos = [t for t in exatos if str(t.get("idFonte", "")).startswith("wikidata:")]
            if len(exatos) > 1:
                com_cusa = [t for t in exatos if q_de(t) in por_qid]
                exatos = com_cusa if len(com_cusa) == 1 else exatos
            if len(exatos) == 1:
                add(exatos[0])
            elif exatos:
                avisos.append(f'"{nome}": {len(exatos)} jogos com esse nome exato ({", ".join(q_de(t) for t in exatos[:4])}); nenhum escolhido. Use o nome completo ou o Q-id.')
            else:
                sug = [t["nome"] for t in r["itens"][:3]] or [t["nome"] for t in r["sugestoes"][:3]]
                avisos.append(f'"{nome}": sem nome exato no índice' + (f' (parecidos: {"; ".join(sug)})' if sug else "") + "; nada parecido foi incluído.")
        return out, avisos
    ignorar = ignorar or set()
    por_id = {q_de(t): t for t in titulos}
    for q in prioridade or []:
        if q in por_id and q not in ignorar:
            add(por_id[q])
    for q, t in por_id.items():
        if q in por_qid and q not in ignorar:
            add(t)
    return out, avisos


# ---------- importação incremental ----------
def importar(jogos: list[tuple], curados: dict, wd: dict, doc: dict, fetch, fontes=FONTES, robots=None, pausa: float = 1.0, dormir=time.sleep,
             max_req: int = 80, permitir_http: bool = False, forcar: bool = False) -> dict:
    """`jogos` = [(qid, nome, ...)]. `fetch(url, maximo) -> (status, bytes)`. Atualiza `doc` (não grava). Estatísticas por fonte."""
    usadas = [0]
    est = {"requisicoes": 0, "sony": {}, "wikidata": {}, "loja": {}}

    def get(url, maximo):
        if usadas[0] >= max_req:
            raise RuntimeError(f"teto de {max_req} requisições")
        if usadas[0]:
            dormir(pausa)
        usadas[0] += 1
        return fetch(url, maximo)

    def conta(f, k):
        est[f][k] = est[f].get(k, 0) + 1

    qids = [j[0] for j in jogos]
    try:
        if "wikidata" in fontes:
            pend = [q for q in qids if forcar or not _recente(doc["idiomas"].get(q), 30)]
            for i in range(0, len(pend), 200):
                try:
                    for q, reg in consultar_idiomas_wikidata(pend[i:i + 200], get).items():
                        doc["idiomas"][q] = reg
                        conta("wikidata", "com-portugues" if any(variante(x["tag"]) for x in reg["itens"]) else ("com-idiomas" if reg["itens"] else "sem-idiomas"))
                except (capas.ErroHttp, ValueError, KeyError) as e:
                    conta("wikidata", f"erro: {getattr(e, 'descricao', lambda: type(e).__name__)()}")
        for q in qids:
            regs = unificada.registros_do_jogo(q, curados, wd)
            if "sony" in fontes:
                for cusa in dict.fromkeys(r["cusa"] for r in regs):
                    ant = doc["atualizacoes"].get(cusa)
                    if not forcar and _recente(ant) and ant.get("status") != "erro":      # erro de rede/TLS: tenta de novo na próxima execução
                        continue
                    reg = consultar_sony(cusa, get, permitir_http, ant)
                    doc["atualizacoes"][cusa] = reg
                    conta("sony", reg["status"] if reg["status"] != "erro" else f"erro: {reg.get('erro')}")
            if "loja" in fontes:
                cids = [c for r in regs for c in ([r.get("contentId")] + list(r.get("contentIds") or [])) if c and CID_RE.match(c)]
                for cid in list(dict.fromkeys(cids))[:3]:
                    ant = doc["loja"].get(cid)
                    if not forcar and _recente(ant, 30) and ant.get("status") != "erro":
                        continue
                    reg = consultar_loja(cid, get, robots or (lambda u: True))
                    doc["loja"][cid] = reg
                    conta("loja", reg["status"] if reg["status"] != "erro" else f"erro: {reg.get('erro')}")
    except RuntimeError as e:
        est["parada"] = str(e)
    est["requisicoes"] = usadas[0]
    return est


def robots_da_loja(fetch) -> callable:
    """Lê store.playstation.com/robots.txt UMA vez; sem robots legível = não consulta a loja (na dúvida, não acessa)."""
    rp = urllib.robotparser.RobotFileParser()
    try:
        st, corpo = fetch("https://store.playstation.com/robots.txt", 500_000)
    except (capas.ErroHttp, ValueError, OSError):
        return lambda u: False
    if st == 404:
        return lambda u: True
    rp.parse(corpo.decode("utf-8", "replace").splitlines())
    return lambda u: rp.can_fetch("*", u)


def resumo_jogo(qid: str, nome: str, curados: dict, wd: dict, doc: dict, oficiais: dict | None = None) -> list[str]:
    regs = unificada.registros_do_jogo(qid, curados, wd)
    loc = localizacao(qid, regs, doc, oficiais)
    out = [f"{nome} ({qid}) · PT-BR: {loc['resumo']}"]
    conf = unificada.conflitos_do_jogo(qid, wd)
    if not regs:
        out.append("  nenhum CUSA conhecido para este jogo: nem registro curado (data/versoes-cusa.json) nem CUSA alegado no Wikidata (local/cusas-wikidata.json)"
                   + (f"; {len(conf)} CUSA(s) em CONFLITO no Wikidata citam este jogo e ficaram sem associação: {', '.join(c['cusa'] for c in conf[:5])}" if conf else ""))
    elif conf:
        out.append(f"  {len(conf)} CUSA(s) em conflito no Wikidata NÃO associados: {', '.join(c['cusa'] for c in conf[:5])}")
    for c in dict.fromkeys(r["cusa"] for r in regs):
        a = doc["atualizacoes"].get(c)
        if not a:
            out.append(f"  {c}: atualização não consultada")
        elif a["status"] == "ok":
            fw = a.get("firmwareMinimo") or "?"
            out.append(f"  {c}: atualização (patch) {a['versao']} · {(a.get('tamanhoBytes') or 0) / 1e9:.2f} GB · firmware exigido {fw}"
                       + (" (ACIMA de 9.00)" if a.get("firmwareAcimaDe900") else "") + f" · {a['grau']} · {a['consultadoEm'][:10]}")
        else:
            out.append(f"  {c}: {a['status']} {a.get('erro') or a.get('nota') or ''}".rstrip())
    return out


def main(argv=None, fetch=None, dormir=time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.metadados", description="metadados por CUSA/Q-id: atualizações oficiais (Sony), idiomas (Wikidata, PlayStation Store)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fila", type=int, nargs="?", const=10, metavar="N", help=f"consulta até N jogos (máx. {MAX_JOGOS}); rode de novo para avançar")
    g.add_argument("--status", action="store_true", help="resumo do cache local (sem rede)")
    g.add_argument("--jogo", metavar="NOME", help="mostra o que se sabe de um jogo (sem rede)")
    g.add_argument("--validar-oficiais", action="store_true", help="confere data/metadados-oficiais.json (sem rede)")
    g.add_argument("--sony", metavar="CUSA", help="diagnóstico: mostra a URL do XML e o que o servidor da Sony responde (TLS, HTTP), sem gravar")
    ap.add_argument("--jogos", default="", help='nomes EXATOS separados por vírgula (ou apelido conhecido, ex.: "gta v"); só esses entram')
    ap.add_argument("--oficiais", default=OFICIAIS_PADRAO)
    ap.add_argument("--painel-porta", type=int, default=0)
    ap.add_argument("--fontes", default=",".join(FONTES), help=f"padrão: {','.join(FONTES)}; 'loja' é experimental (não trouxe idiomas no teste real)")
    ap.add_argument("--permitir-http", action="store_true", help="se o TLS do servidor de atualizações da Sony não puder ser verificado, lê o XML por HTTP (marcado como não verificado)")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--arquivo", default=ARQ_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusas", default=cusas.DADOS_PADRAO)
    ap.add_argument("--user-agent", default=os.environ.get("WIKIDATA_USER_AGENT", wikidata.UA_PADRAO))
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--max-requisicoes", type=int, default=80)
    a = ap.parse_args(argv)
    try:
        indice, cur, wd = busca.carregar_indice(a.indice), versoes.carregar(a.versoes), cusas.carregar_dados(a.cusas)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    doc = carregar(a.arquivo)
    try:
        ofi = carregar_oficiais(a.oficiais)
    except ValueError as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if a.validar_oficiais:
        print(f"{len(ofi['produtos'])} produto(s) oficial(is); 0 problema(s)")
        return 0
    if a.sony:
        if not CUSA_RE.match(a.sony.upper()):
            print("ERRO  informe um CUSA (CUSA + 5 dígitos)", file=sys.stderr)
            return 2
        c = a.sony.upper()
        f = fetch or (lambda u, m: http_get(u, a.user_agent, m, a.permitir_http))
        print(f"URL (HTTPS): {url_xml_sony(c)}")
        for esq in (("https", "http") if a.permitir_http else ("https",)):
            try:
                st, corpo = f(url_xml_sony(c, esq), 1_000_000)
                print(f"  {esq}: HTTP {st}, {len(corpo)} bytes" + (f" · versão {ler_xml_sony(corpo).get('versao')}" if st == 200 and corpo.strip() else ""))
            except capas.ErroHttp as e:
                print(f"  {esq}: {e.descricao()}")
            except (ValueError, ET.ParseError) as e:
                print(f"  {esq}: {type(e).__name__}: {str(e)[:80]}")
        if not a.permitir_http:
            print("  (HTTP não testado: use --permitir-http para testar o mesmo XML sem TLS; o resultado fica marcado como não verificado)")
        return 0
    if a.status:
        at = doc["atualizacoes"].values()
        st = {}
        for x in at:
            st[x["status"]] = st.get(x["status"], 0) + 1
        com_pt = sum(1 for v in doc["idiomas"].values() if any(variante(i["tag"]) == "pt-BR" for i in v.get("itens", [])))
        print(f"Atualizações consultadas: {len(doc['atualizacoes'])} {st or ''} · idiomas (Wikidata): {len(doc['idiomas'])} jogos, {com_pt} com pt-BR · loja: {len(doc['loja'])} produtos")
        return 0
    if a.jogo:
        rs = [r for r in busca.buscar(indice, a.jogo, limite=5) if str(r.get("idFonte", "")).startswith("wikidata:")]
        if not rs:
            print("nenhum jogo encontrado no índice")
            return 1
        for r in rs[:3]:
            print("\n".join(resumo_jogo(r["idFonte"].split(":", 1)[1], r["nome"], cur, wd, doc, ofi)))
        return 0
    fontes = tuple(x.strip() for x in a.fontes.split(",") if x.strip())
    if not fontes or any(x not in FONTES_VALIDAS for x in fontes):
        print(f"ERRO  fontes válidas: {', '.join(FONTES_VALIDAS)}", file=sys.stderr)
        return 2
    n = max(1, min(a.fila, MAX_JOGOS))
    feitos = set() if a.forcar else {q for q, v in doc["idiomas"].items() if _recente(v, 30)}
    prio = capas.interesse_do_painel(a.painel_porta) if a.painel_porta else []
    from . import busca_inteligente
    jogos, avisos = escolher_jogos(indice, cur, wd, [x.strip() for x in a.jogos.split(",") if x.strip()], n, feitos, prio,
                                   busca_inteligente.carregar_apelidos())
    for av in avisos:
        print(f"AVISO  {av}", file=sys.stderr)
    if not jogos:
        print("Nada a fazer: nenhum jogo selecionado (veja os avisos) ou os candidatos já foram consultados recentemente.")
        return 0 if not avisos else 1
    if a.user_agent == wikidata.UA_PADRAO:
        print("AVISO  User-Agent genérico: defina WIKIDATA_USER_AGENT com um contato.", file=sys.stderr)
    f = fetch or (lambda u, m: http_get(u, a.user_agent, m, a.permitir_http))
    robots = robots_da_loja(f) if "loja" in fontes else None
    est = importar(jogos, cur, wd, doc, f, fontes, robots, a.pausa, dormir, max(1, a.max_requisicoes), a.permitir_http, a.forcar)
    salvar(doc, a.arquivo)
    print(f"Lote: {len(jogos)} jogo(s) · {est['requisicoes']} requisição(ões)" + (f" · PAROU: {est['parada']}" if est.get("parada") else ""))
    for k in ("sony", "wikidata", "loja"):
        if k in fontes:
            print(f"  {k}: {est[k] or 'nada novo'}")
    for q, nome, *_ in jogos[:10]:
        print("\n".join(resumo_jogo(q, nome, cur, wd, doc, ofi)))
    print("Dados da rede ficam em local/metadados.json (fonte, URL, data e grau). Nada foi inventado: ausente = desconhecido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
