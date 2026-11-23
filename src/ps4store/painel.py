"""PAINEL: interface web LOCAL e somente leitura para pesquisar jogos (busca.py) e consultar versões CUSA (versoes.py). Servidor http.server da stdlib.

Segurança: escuta SÓ em 127.0.0.1 (não há opção de outro endereço); só GET/HEAD; rotas fixas (nenhum acesso a arquivos pelo caminho da URL);
parâmetros validados por lista fechada; Host header conferido (contra DNS rebinding); CSP restritiva; a página não carrega nada externo.
Não baixa nada e não escreve em disco. Única rota com rede: /api/link (análise de URL pedida pelo usuário, via resolver.py, com as mesmas travas: HTTPS,
lista de hosts, sem IP privado, ≤64 KiB por arquivo; exige o cabeçalho X-PS4Store contra CSRF). Dados vêm de local/ e data/ (recarregados se o arquivo mudar).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import analise_link, auditoria, busca, busca_inteligente, capas, cusas, metadados, unificada, versoes

HOST = "127.0.0.1"
PORTA_PADRAO = 8765
ASSETS = Path(__file__).with_name("painel_assets")
ROTAS_ESTATICAS = {"/": ("index.html", "text/html; charset=utf-8"), "/estilo.css": ("estilo.css", "text/css; charset=utf-8"),
                   "/app.js": ("app.js", "application/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
QID_RE = re.compile(r"^Q[0-9]{1,12}$")
CUSA_RE = versoes.CUSA_RE
REGIAO_RE = re.compile(r"^[A-Za-z]{2,5}$")
IDIOMA_RE = re.compile(r"^[^\W\d_][\w \-']{0,29}$", re.UNICODE)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
LIMITE_MAX = 200


class ParametroInvalido(ValueError):
    pass


class Dados:
    """Índice de busca + versões, recarregados quando o arquivo muda (mtime). Leitura apenas."""

    def __init__(self, indice: str, arq_versoes: str, arq_cusas: str = cusas.DADOS_PADRAO, arq_auditoria: str = auditoria.AUDITORIA_PADRAO,
                 dir_capas: str = capas.DIR_PADRAO, arq_apelidos: str = busca_inteligente.APELIDOS_PADRAO, arq_metadados: str = metadados.ARQ_PADRAO):
        self.indice_path, self.versoes_path, self.cusas_path, self.auditoria_path = indice, arq_versoes, arq_cusas, arq_auditoria
        self.dir_capas, self.apelidos_path, self.metadados_path = dir_capas, arq_apelidos, arq_metadados
        self.trava_link = threading.Lock()                          # uma análise de link por vez
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._interesse: deque[str] = deque(maxlen=200)             # só Q-ids, só em memória (nada é gravado): fila de prioridade para o importador de capas

    def _carregar(self, chave: str, caminho: str, loader):
        try:
            m = os.stat(caminho).st_mtime_ns
        except OSError:
            m = -1
        with self._lock:
            ant = self._cache.get(chave)
            if ant and ant[0] == m:
                return ant[1]
            doc = loader(caminho)
            self._cache[chave] = (m, doc)
            return doc

    def indice(self) -> dict:
        return self._carregar("i", self.indice_path, busca.carregar_indice)

    def versoes(self) -> dict:
        return self._carregar("v", self.versoes_path, versoes.carregar)

    def wikidata(self) -> dict:
        return self._carregar("w", self.cusas_path, cusas.carregar_dados)

    def auditoria(self) -> dict:
        return self._carregar("a", self.auditoria_path, auditoria.carregar_auditoria)

    def marcar(self, qids) -> None:
        with self._lock:
            for q in qids:
                if q and q not in self._interesse:
                    self._interesse.appendleft(q)

    def interesse(self) -> list[str]:
        with self._lock:
            return list(self._interesse)

    def metadados(self) -> dict:
        return self._carregar("md", self.metadados_path, metadados.carregar)

    def capas(self) -> dict:
        return self._carregar("c", str(Path(self.dir_capas) / "indice.json"), lambda _c: capas.carregar_indice(self.dir_capas))

    def motor(self) -> busca_inteligente.Motor:
        idx = self.indice()                                         # recria o motor só quando o índice (ou os apelidos) mudam
        return self._carregar("m", self.indice_path, lambda _c: busca_inteligente.Motor(idx, busca_inteligente.carregar_apelidos(self.apelidos_path)))


def _qs(query: str, permitidos: set[str]) -> dict[str, str]:
    try:
        bruto = parse_qs(query, keep_blank_values=True, max_num_fields=12, strict_parsing=False, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise ParametroInvalido("parâmetros ilegíveis")
    for k, v in bruto.items():
        if k not in permitidos:
            raise ParametroInvalido(f"parâmetro desconhecido: {k[:20]}")
        if len(v) != 1:
            raise ParametroInvalido(f"parâmetro repetido: {k}")
    return {k: v[0] for k, v in bruto.items()}


def _texto(valor: str, nome: str, maximo: int) -> str:
    valor = valor.strip()
    if len(valor) > maximo or _CTRL.search(valor):
        raise ParametroInvalido(f"{nome}: texto longo demais ou com caracteres de controle")
    return valor


def _agrupar(vdoc: dict) -> dict[str, list[dict]]:
    por: dict[str, list[dict]] = {}
    for r in vdoc.get("versoes", []):
        por.setdefault(r["qid"], []).append(r)
    return por


def _qid_de(t: dict) -> str | None:
    i = str(t.get("idFonte", ""))
    return i.split(":", 1)[1] if i.startswith("wikidata:") else None


def _contagem(rs: list[dict]) -> dict:
    return {"nRegistros": len(rs), "nCusas": len({r["cusa"] for r in rs}), "nWikidata": sum(1 for r in rs if r.get("origem") == "wikidata")}


def listar_jogos(dados: Dados, q: str, com_versoes: bool, limite: int, offset: int = 0, ptbr: str = "") -> dict:
    idx, vdoc, wd = dados.indice(), dados.versoes(), dados.wikidata()
    por_qid = unificada.agrupar(vdoc, wd)
    fontes = idx.get("fontes", {})
    nomes = {_qid_de(t): t for t in idx.get("titulos", []) if _qid_de(t)}
    itens: list[dict] = []
    aviso = ""
    sugestoes: list[str] = []
    via = ""
    cp = dados.capas()
    tipo = unificada.classificar_termo(q) if q else "nome"
    if tipo in ("cusa", "contentId"):                               # pesquisa por identificador no mesmo campo
        loc = unificada.localizar(q, vdoc, wd)
        aviso = loc["nota"]
        for qid in loc["qids"]:
            t = nomes.get(qid)
            rs = por_qid.get(qid, [])
            itens.append({"nome": t["nome"] if t else rs[0]["jogo"], "ano": (t or {}).get("lancamento"), "fonte": (t or {}).get("fonte", "versoes"),
                          "fonteNome": fontes.get((t or {}).get("fonte"), {}).get("nome") or "registros de versão", "qid": qid, **_contagem(rs)})
    elif idx.get("titulos"):
        if q:
            r = dados.motor().buscar(q, limite=100000)
            base = r["itens"]
            sugestoes = [{"nome": t["nome"], "qid": _qid_de(t)} for t in r["sugestoes"]]
            via = "apelido" if r["via"] else ""
        elif ptbr:
            base = list(idx["titulos"])
        else:
            base = [t for t in idx["titulos"] if _qid_de(t) in por_qid]
        for t in base:
            qid = _qid_de(t)
            rs = por_qid.get(qid, []) if qid else []
            if com_versoes and not rs:
                continue
            itens.append({"nome": t["nome"], "ano": t.get("lancamento"), "fonte": t.get("fonte"), "fonteNome": fontes.get(t.get("fonte"), {}).get("nome"),
                          "qid": qid, **_contagem(rs)})
    else:
        aviso = "índice de busca vazio ou ausente: só jogos com versões cadastradas"
        nq = busca.norm(q)
        for qid, rs in por_qid.items():
            if (not nq or all(w in busca.norm(rs[0].get("jogo")) for w in nq.split())):
                itens.append({"nome": rs[0]["jogo"], "ano": None, "fonte": "versoes", "fonteNome": "registros de versão", "qid": qid, **_contagem(rs)})
    md = dados.metadados()
    for it in itens:
        loc = metadados.localizacao(it["qid"], por_qid.get(it["qid"], []), md) if it.get("qid") else None
        it["ptbr"] = (loc["confirmadas"] + (["sem-parte"] if loc["semParte"] else [])) if loc else []
    if ptbr:
        itens = [it for it in itens if it.get("qid") and metadados.filtro_ptbr(metadados.localizacao(it["qid"], por_qid.get(it["qid"], []), md), ptbr)]
    for it in itens:
        it["capa"] = capas.info_publica(cp, it["qid"]) if it.get("qid") else None
        if it["capa"]:
            it["capa"] = {k: it["capa"][k] for k in ("url", "tipo")}
    total = len(itens)
    pagina = itens[offset:offset + limite]
    if q and offset == 0:
        dados.marcar([it.get("qid") for it in pagina[:8]])
    return {"total": total, "mostrando": len(pagina), "offset": offset, "temMais": offset + len(pagina) < total, "itens": pagina, "aviso": aviso,
            "tipoBusca": tipo, "sugestoes": sugestoes, "viaApelido": via == "apelido"}


MOTIVOS_CURTOS = {"o Wikidata atribui o mesmo CUSA a mais de um jogo": "mesmo CUSA em mais de um jogo",
                  "contradiz o registro curado: o CUSA já está cadastrado para outro Q-id": "contradiz o registro curado"}


def resumir_conflitos(qid: str, wd: dict, aud: dict, nome: str) -> list[dict]:
    """Conflitos do jogo, uma linha curta cada: CUSA, motivo curto, outros jogos (até 3) e a classificação da auditoria (se houver). Não afirma tipo de produto."""
    por_cusa = {c.get("cusa"): c for c in aud.get("conflitos", [])}
    out = []
    for c in unificada.conflitos_do_jogo(qid, wd):
        outros = [n for q, n in zip(c["qids"], c.get("jogos", [])) if q != qid]
        a = por_cusa.get(c["cusa"])
        out.append({"cusa": c["cusa"], "motivo": MOTIVOS_CURTOS.get(c["motivo"], c["motivo"]), "outrosJogos": outros[:3], "maisOutros": max(len(outros) - 3, 0),
                    "classificacao": a["classificacao"] if a else "nao-auditado", "rotulo": a["rotulo"] if a else auditoria.ROTULOS["nao-auditado"]})
    return out


def estatisticas(dados: Dados) -> dict:
    """Contadores do cabeçalho: cada um separado (não misturar jogos, CUSAs, registros manuais e conflitos)."""
    idx, vdoc, wd = dados.indice(), dados.versoes(), dados.wikidata()
    no_indice = {_qid_de(t) for t in idx.get("titulos", []) if _qid_de(t)}
    com = {r["qid"] for r in vdoc.get("versoes", [])} | {r["qid"] for r in wd.get("registros", [])}
    if no_indice:
        com &= no_indice
    cusas_ = {r["cusa"] for r in vdoc.get("versoes", [])} | {r["cusa"] for r in wd.get("registros", [])}
    return {"jogosPesquisaveis": len(idx.get("titulos", [])), "jogosComCusa": len(com), "cusasDistintos": len(cusas_),
            "registrosManuais": len(vdoc.get("versoes", [])), "registrosWikidata": len(wd.get("registros", [])), "conflitosPendentes": len(wd.get("conflitos", [])),
            "jogosNoIndice": len(idx.get("titulos", [])), "registrosDeVersao": len(vdoc.get("versoes", [])), "cusasWikidata": len(wd.get("registros", [])),
            "conflitosWikidata": len(wd.get("conflitos", [])), "somenteLeitura": True}


def detalhar_jogo(dados: Dados, qid: str, cusa: str, regiao: str, idioma: str) -> dict | None:
    idx, vdoc, wd = dados.indice(), dados.versoes(), dados.wikidata()
    rs = unificada.registros_do_jogo(qid, vdoc, wd)
    t = next((x for x in idx.get("titulos", []) if x.get("idFonte") == f"wikidata:{qid}"), None)
    if t is None and not rs:
        return None
    nome = t["nome"] if t else rs[0]["jogo"]
    avisos: list[str] = []
    if not idx.get("titulos"):
        avisos.append("Índice de busca ausente: o vínculo do Q-id não pôde ser conferido no índice local.")
    elif t is None:
        avisos.append(f"O Q-id {qid} NÃO existe no índice local: confira o vínculo antes de confiar nestes CUSAs.")
    for r in rs:
        if r.get("origem") == "curado" and t is not None and busca.norm(r.get("jogo")) != busca.norm(t["nome"]):
            avisos.append(f"O registro {r['cusa']} foi cadastrado como \"{r['jogo']}\" para este Q-id: confira o vínculo.")
            break
    conflitos = resumir_conflitos(qid, wd, dados.auditoria(), nome)
    if conflitos:                                                   # UM aviso curto; o detalhe vai na lista compacta `conflitos`
        lista = ", ".join(c["cusa"] for c in conflitos[:4]) + (f" (+{len(conflitos) - 4})" if len(conflitos) > 4 else "")
        avisos.append(f"{len(conflitos)} CUSA(s) em conflito no Wikidata, NÃO associados a este jogo: {lista}.")
    visiveis, omitidos = versoes.consultar({"versoes": rs}, cusa=cusa or None, regiao=regiao or None, idioma=idioma or None)
    md = dados.metadados()
    visiveis = [dict(r, atualizacao=md["atualizacoes"].get(r["cusa"])) for r in visiveis]
    return {"capa": capas.info_publica(dados.capas(), qid), "jogo": {"nome": nome, "qid": qid, "ano": (t or {}).get("lancamento"), "url": (t or {}).get("url") or ""},
            "total": len(rs), "cusasDistintos": len({r["cusa"] for r in rs}), "registros": visiveis, "omitidos": omitidos,
            "origens": {"curado": sum(1 for r in rs if r.get("origem") == "curado"), "wikidata": sum(1 for r in rs if r.get("origem") == "wikidata")},
            "filtros": {"cusa": cusa, "regiao": regiao, "idioma": idioma}, "avisos": avisos, "conflitos": conflitos,
            "localizacao": metadados.localizacao(qid, rs, md),
            "temJogoBase": any(r.get("escopo") == "jogo-base" for r in rs if r.get("origem") == "curado")}


class Handler(BaseHTTPRequestHandler):
    server_version = "ps4store-painel"
    sys_version = ""
    timeout = 10                                   # conexão ociosa é derrubada

    def log_message(self, *a):                     # sem log de URLs/consultas
        pass

    def _enviar(self, status: int, corpo: bytes, ctype: str, head: bool = False, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(corpo)

    def _json(self, status: int, obj, head: bool = False, extra=None) -> None:
        self._enviar(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", head, extra)

    def _host_ok(self) -> bool:
        porta = self.server.server_address[1]
        return (self.headers.get("Host") or "") in (f"127.0.0.1:{porta}", f"localhost:{porta}")

    def _tratar(self, head: bool) -> None:
        if not self._host_ok():
            return self._json(403, {"erro": "Host não permitido (só 127.0.0.1/localhost)"}, head)
        u = urlsplit(self.path)
        rota = u.path
        try:
            if rota in ROTAS_ESTATICAS:
                if u.query:
                    raise ParametroInvalido("esta rota não aceita parâmetros")
                nome, ctype = ROTAS_ESTATICAS[rota]
                return self._enviar(200, (ASSETS / nome).read_bytes(), ctype, head)
            dados: Dados = self.server.dados
            if rota.startswith("/capa/"):                               # só por Q-id validado; o arquivo vem do índice de capas, nunca do caminho da URL
                _qs(u.query, set())
                qid = rota[6:]
                ach = capas.caminho_da_capa(dados.dir_capas, dados.capas(), qid) if QID_RE.match(qid) else None
                if not ach:
                    return self._json(404, {"erro": "sem imagem local para este jogo"}, head)
                return self._enviar(200, ach[0].read_bytes(), ach[1], head, {"Cache-Control": "private, max-age=3600"})
            if rota == "/api/link":                                     # ÚNICA rota com rede: análise de link pedida pelo usuário (resolver.py)
                if self.headers.get("X-PS4Store") != "1":               # cabeçalho próprio: outra página não consegue pedir isto ao painel (CSRF)
                    return self._json(403, {"erro": "pedido sem o cabeçalho do painel"}, head)
                p = _qs(u.query, {"url", "qid"})
                url = p.get("url", "")
                if not url or len(url) > 2048 or _CTRL.search(url):
                    raise ParametroInvalido("url ausente ou inválida")
                qid = p.get("qid", "")
                if qid and not QID_RE.match(qid):
                    raise ParametroInvalido("qid inválido")
                if not dados.trava_link.acquire(blocking=False):
                    return self._json(429, {"erro": "já há uma análise em andamento"}, head)
                try:
                    r = analise_link.analisar(url, qid, dados.versoes(), dados.wikidata(), getattr(self.server, "rede_links", None), getattr(self.server, "hosts_links", None))
                finally:
                    dados.trava_link.release()
                return self._json(200, r, head)
            if rota == "/api/interesse":
                _qs(u.query, set())
                return self._json(200, {"qids": dados.interesse()}, head)
            if rota == "/api/estado":
                _qs(u.query, set())
                return self._json(200, estatisticas(dados), head)
            if rota == "/api/jogos":
                p = _qs(u.query, {"q", "com_versoes", "limite", "offset", "ptbr"})
                q = _texto(p.get("q", ""), "q", 100)
                cv = p.get("com_versoes", "")
                if cv not in ("", "0", "1"):
                    raise ParametroInvalido("com_versoes deve ser 1 ou vazio")
                lim = p.get("limite", "50")
                if not lim.isdigit() or not 1 <= int(lim) <= LIMITE_MAX:
                    raise ParametroInvalido(f"limite deve ser de 1 a {LIMITE_MAX}")
                off = p.get("offset", "0")
                if not off.isdigit() or int(off) > 100000:
                    raise ParametroInvalido("offset inválido")
                pb = p.get("ptbr", "")
                if pb not in ("", "qualquer", "audio", "texto"):
                    raise ParametroInvalido("ptbr deve ser qualquer, audio ou texto")
                if not q and cv != "1" and not pb:
                    raise ParametroInvalido("informe parte do nome ou use com_versoes=1")
                return self._json(200, listar_jogos(dados, q, cv == "1", int(lim), int(off), pb), head)
            if rota == "/api/jogo":
                p = _qs(u.query, {"qid", "cusa", "regiao", "idioma"})
                qid = p.get("qid", "")
                if not QID_RE.match(qid):
                    raise ParametroInvalido("qid inválido (esperado Q seguido de números)")
                cusa = _texto(p.get("cusa", ""), "cusa", 9).upper()
                if cusa and not CUSA_RE.match(cusa):
                    raise ParametroInvalido("cusa inválido (CUSA + 5 dígitos; não é o Content ID)")
                regiao = _texto(p.get("regiao", ""), "regiao", 5)
                if regiao and not REGIAO_RE.match(regiao):
                    raise ParametroInvalido("regiao inválida (US, EU, JP, ASIA, KR ou prefixo)")
                idioma = _texto(p.get("idioma", ""), "idioma", 30)
                if idioma and not IDIOMA_RE.match(idioma):
                    raise ParametroInvalido("idioma inválido")
                r = detalhar_jogo(dados, qid, cusa, regiao, idioma)
                if r:
                    dados.marcar([qid])
                return self._json(200, r, head) if r else self._json(404, {"erro": "jogo não encontrado no índice nem nos registros de versão"}, head)
            return self._json(404, {"erro": "rota inexistente"}, head)
        except ParametroInvalido as e:
            return self._json(400, {"erro": str(e)}, head)
        except (OSError, ValueError) as e:
            return self._json(500, {"erro": f"dados indisponíveis ({type(e).__name__})"}, head)

    def do_GET(self):
        self._tratar(False)

    def do_HEAD(self):
        self._tratar(True)

    def _nao_permitido(self):
        self._json(405, {"erro": "somente leitura: apenas GET"}, extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _nao_permitido


def criar_servidor(porta: int = PORTA_PADRAO, indice: str = busca.INDICE_PADRAO, arq_versoes: str = versoes.VERSOES_PADRAO, host: str = HOST,
                   arq_cusas: str = cusas.DADOS_PADRAO, arq_auditoria: str = auditoria.AUDITORIA_PADRAO,
                   dir_capas: str = capas.DIR_PADRAO, arq_apelidos: str = busca_inteligente.APELIDOS_PADRAO,
                   arq_metadados: str = metadados.ARQ_PADRAO) -> ThreadingHTTPServer:
    if host != HOST:
        raise ValueError("o painel só pode escutar em 127.0.0.1")
    if not (porta == 0 or 1024 <= porta <= 65535):
        raise ValueError("porta deve ser 0 (qualquer) ou de 1024 a 65535")
    dados = Dados(indice, arq_versoes, arq_cusas, arq_auditoria, dir_capas, arq_apelidos, arq_metadados)
    erros = versoes.validar_doc(dados.versoes())
    if erros:
        raise ValueError(f"o arquivo de versões tem {len(erros)} problema(s); rode: python -m ps4store.versoes --validar")
    dados.indice()                                              # falha cedo se o índice estiver corrompido (ausente é aceito)
    dados.wikidata()                                            # idem para os CUSAs do Wikidata (ausente é aceito)
    srv = ThreadingHTTPServer((HOST, porta), Handler)
    srv.daemon_threads = True
    srv.dados = dados
    return srv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.painel", description="interface web local (somente leitura) para jogos e versões CUSA")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusas", default=cusas.DADOS_PADRAO, help="CUSAs alegados no Wikidata (gerados por ps4store.cusas)")
    ap.add_argument("--auditoria", default=auditoria.AUDITORIA_PADRAO, help="relatório de conflitos (gerado por ps4store.auditoria; opcional)")
    ap.add_argument("--capas", default=capas.DIR_PADRAO, help="pasta das miniaturas (gerada por ps4store.capas; opcional)")
    ap.add_argument("--apelidos", default=busca_inteligente.APELIDOS_PADRAO)
    ap.add_argument("--metadados", default=metadados.ARQ_PADRAO, help="gerado por ps4store.metadados (opcional)")
    a = ap.parse_args(argv)
    try:
        srv = criar_servidor(a.porta, a.indice, a.versoes, arq_cusas=a.cusas, arq_auditoria=a.auditoria, dir_capas=a.capas, arq_apelidos=a.apelidos, arq_metadados=a.metadados)
    except OSError as e:
        print(f"ERRO  não foi possível abrir a porta {a.porta} em 127.0.0.1 ({e.strerror or type(e).__name__}). Já há um painel rodando? Use --porta OUTRA.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    porta = srv.server_address[1]
    print(f"PS4 Store BR · painel local (somente leitura) em http://127.0.0.1:{porta}")
    print("Abra esse endereço no navegador do Android. Para ENCERRAR: Ctrl+C aqui no Termux (ou, de outra sessão: pkill -f ps4store.painel).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
