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
FONTES = ("sony", "wikidata", "loja")
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
        raise capas.ErroHttp(0, "tls:certificado-nao-verificado" if "Certificate" in nome or "SSL" in nome else f"rede:{nome if not isinstance(motivo, str) else motivo[:40]}") from None
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


# ---------- classificação PT-BR (sem dedução por região) ----------
PARTES = ("audio", "texto", "legendas", "tela")


def localizacao(qid: str, registros: list[dict], meta: dict) -> dict:
    """{partes: {audio|texto|legendas|tela: {status, fontes}}, semParte, ptPT, ptSemVariante, resumo}. status: confirmado | nao-listado | desconhecido.
    'confirmado' = uma fonte AFIRMA pt-BR naquela parte (grau indicado: oficial, alegado no Wikidata, curado). Ausência nunca vira 'não'."""
    partes = {p: {"status": "desconhecido", "fontes": []} for p in PARTES}
    sem_parte, pt_pt, pt_sem = [], [], []

    def fonte(reg, extra=""):
        return {"fonte": reg.get("fonte", "?") + extra, "grau": reg.get("grau", "?"), "url": reg.get("url", ""), "consultadoEm": reg.get("consultadoEm", "")}

    wd = meta.get("idiomas", {}).get(qid)
    if wd:
        for it in wd.get("itens", []):
            v = variante(it["tag"])
            if v == "pt-BR":
                if it["parte"] == "nao-especificada":
                    sem_parte.append(fonte(wd))
                else:
                    partes[it["parte"]]["status"] = "confirmado"
                    partes[it["parte"]]["fontes"].append(fonte(wd))
            elif v == "pt-PT":
                pt_pt.append(fonte(wd, f" ({it['parte']})"))
            elif v == "pt":
                pt_sem.append(fonte(wd, f" ({it['parte']})"))
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
                if "pt-BR" in vs:
                    partes[campo]["status"] = "confirmado"
                    partes[campo]["fontes"].append(fonte(lj, f" · {cid}"))
                elif lista and partes[campo]["status"] == "desconhecido":
                    partes[campo]["status"] = "nao-listado"
                    partes[campo]["fontes"].append(fonte(lj, f" · {cid} (lista sem pt-BR)"))
                if "pt-PT" in vs:
                    pt_pt.append(fonte(lj, f" · {campo}"))
                if "pt" in vs:
                    pt_sem.append(fonte(lj, f" · {campo}"))
        if r.get("origem") == "curado" and r.get("idiomas"):
            for x in r["idiomas"]:
                v = variante(x)
                ev = {"fonte": f"registro curado {r['cusa']}", "grau": "curado", "url": (r.get("evidencias") or [{}])[0].get("url", ""), "consultadoEm": ""}
                if v == "pt-BR":
                    sem_parte.append(ev)
                elif v == "pt-PT":
                    pt_pt.append(ev)
                elif v == "pt":
                    pt_sem.append(ev)
    conf = [p for p in PARTES if partes[p]["status"] == "confirmado"]
    if conf:
        resumo = "PT-BR confirmado: " + ", ".join({"audio": "áudio", "texto": "texto", "legendas": "legendas", "tela": "texto/legendas (tela)"}[p] for p in conf)
    elif sem_parte:
        resumo = "PT-BR informado, sem dizer se é áudio, texto ou legendas"
    elif pt_sem:
        resumo = "português informado SEM variante (não classificado como PT-BR)"
    elif pt_pt:
        resumo = "só português europeu (pt-PT) informado"
    elif any(partes[p]["status"] == "nao-listado" for p in PARTES):
        resumo = "a loja lista idiomas e PT-BR não aparece (pode variar por produto/região)"
    else:
        resumo = "desconhecido (nenhuma fonte consultada informa)"
    return {"partes": partes, "semParte": sem_parte, "ptPT": pt_pt, "ptSemVariante": pt_sem, "confirmadas": conf, "resumo": resumo}


def filtro_ptbr(loc: dict, modo: str) -> bool:
    c = set(loc["confirmadas"])
    if modo == "audio":
        return "audio" in c
    if modo == "texto":
        return bool(c & {"texto", "legendas", "tela"})
    return bool(c) or bool(loc["semParte"])


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
                    if not forcar and _recente(ant):
                        continue
                    reg = consultar_sony(cusa, get, permitir_http, ant)
                    doc["atualizacoes"][cusa] = reg
                    conta("sony", reg["status"] if reg["status"] != "erro" else f"erro: {reg.get('erro')}")
            if "loja" in fontes:
                cids = [c for r in regs for c in ([r.get("contentId")] + list(r.get("contentIds") or [])) if c and CID_RE.match(c)]
                for cid in list(dict.fromkeys(cids))[:3]:
                    if not forcar and _recente(doc["loja"].get(cid), 30):
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


def resumo_jogo(qid: str, nome: str, curados: dict, wd: dict, doc: dict) -> list[str]:
    regs = unificada.registros_do_jogo(qid, curados, wd)
    loc = localizacao(qid, regs, doc)
    out = [f"{nome} ({qid}) · PT-BR: {loc['resumo']}"]
    if not regs:
        out.append("  nenhum CUSA conhecido para este jogo")
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
    ap.add_argument("--jogos", default="", help='nomes para priorizar, ex.: "batman,cyberpunk"')
    ap.add_argument("--painel-porta", type=int, default=0)
    ap.add_argument("--fontes", default=",".join(FONTES))
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
            print("\n".join(resumo_jogo(r["idFonte"].split(":", 1)[1], r["nome"], cur, wd, doc)))
        return 0
    fontes = tuple(x.strip() for x in a.fontes.split(",") if x.strip())
    if not fontes or any(x not in FONTES for x in fontes):
        print(f"ERRO  fontes válidas: {', '.join(FONTES)}", file=sys.stderr)
        return 2
    n = max(1, min(a.fila, MAX_JOGOS))
    feitos = set() if a.forcar else {q for q, v in doc["idiomas"].items() if _recente(v, 30)}
    prio = capas.interesse_do_painel(a.painel_porta) if a.painel_porta else []
    jogos = capas.escolher_amostra(indice, cur, wd, [x.strip() for x in a.jogos.split(",") if x.strip()], n, feitos, prio)
    if not jogos:
        print("Nada a fazer: os jogos candidatos já foram consultados recentemente.")
        return 0
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
        print("\n".join(resumo_jogo(q, nome, cur, wd, doc)))
    print("Dados da rede ficam em local/metadados.json (fonte, URL, data e grau). Nada foi inventado: ausente = desconhecido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
