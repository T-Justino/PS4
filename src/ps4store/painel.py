"""PAINEL: interface web LOCAL e somente leitura para pesquisar jogos (busca.py) e consultar versões CUSA (versoes.py). Servidor http.server da stdlib.

Segurança: escuta SÓ em 127.0.0.1 (não há opção de outro endereço); só GET/HEAD; rotas fixas (nenhum acesso a arquivos pelo caminho da URL);
parâmetros validados por lista fechada; Host header conferido (contra DNS rebinding); CSP restritiva; a página não carrega nada externo.
Não resolve links, não baixa nada, não escreve em disco. Dados vêm de local/busca-indice.json e data/versoes-cusa.json (recarregados se o arquivo mudar).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import busca, versoes

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

    def __init__(self, indice: str, arq_versoes: str):
        self.indice_path, self.versoes_path = indice, arq_versoes
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}

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


def listar_jogos(dados: Dados, q: str, com_versoes: bool, limite: int) -> dict:
    idx, vdoc = dados.indice(), dados.versoes()
    por_qid = _agrupar(vdoc)
    fontes = idx.get("fontes", {})
    itens: list[dict] = []
    aviso = ""
    if idx.get("titulos"):
        base = busca.buscar(idx, q) if q else [t for t in idx["titulos"] if _qid_de(t) in por_qid]
        for t in base:
            qid = _qid_de(t)
            rs = por_qid.get(qid, []) if qid else []
            if com_versoes and not rs:
                continue
            itens.append({"nome": t["nome"], "ano": t.get("lancamento"), "fonte": t.get("fonte"), "fonteNome": fontes.get(t.get("fonte"), {}).get("nome"),
                          "qid": qid, "nRegistros": len(rs), "nCusas": len({r["cusa"] for r in rs})})
    else:
        aviso = "índice de busca vazio ou ausente: só jogos com versões cadastradas"
        nq = busca.norm(q)
        for qid, rs in por_qid.items():
            if (not nq or all(w in busca.norm(rs[0].get("jogo")) for w in nq.split())):
                itens.append({"nome": rs[0]["jogo"], "ano": None, "fonte": "versoes", "fonteNome": "registros de versão", "qid": qid,
                              "nRegistros": len(rs), "nCusas": len({r["cusa"] for r in rs})})
    total = len(itens)
    return {"total": total, "mostrando": min(total, limite), "itens": itens[:limite], "aviso": aviso}


def detalhar_jogo(dados: Dados, qid: str, cusa: str, regiao: str, idioma: str) -> dict | None:
    idx, vdoc = dados.indice(), dados.versoes()
    rs = _agrupar(vdoc).get(qid, [])
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
        if t is not None and busca.norm(r.get("jogo")) != busca.norm(t["nome"]):
            avisos.append(f"O registro {r['cusa']} foi cadastrado como \"{r['jogo']}\" para este Q-id: confira o vínculo.")
            break
    visiveis, omitidos = versoes.consultar({"versoes": rs}, cusa=cusa or None, regiao=regiao or None, idioma=idioma or None)
    return {"jogo": {"nome": nome, "qid": qid, "ano": (t or {}).get("lancamento"), "url": (t or {}).get("url") or ""},
            "total": len(rs), "cusasDistintos": len({r["cusa"] for r in rs}), "registros": visiveis, "omitidos": omitidos,
            "filtros": {"cusa": cusa, "regiao": regiao, "idioma": idioma}, "avisos": avisos,
            "temJogoBase": any(r.get("escopo") == "jogo-base" for r in rs)}


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
            if rota == "/api/estado":
                _qs(u.query, set())
                return self._json(200, {"jogosNoIndice": len(dados.indice().get("titulos", [])), "registrosDeVersao": len(dados.versoes().get("versoes", [])),
                                        "somenteLeitura": True}, head)
            if rota == "/api/jogos":
                p = _qs(u.query, {"q", "com_versoes", "limite"})
                q = _texto(p.get("q", ""), "q", 100)
                cv = p.get("com_versoes", "")
                if cv not in ("", "0", "1"):
                    raise ParametroInvalido("com_versoes deve ser 1 ou vazio")
                lim = p.get("limite", "50")
                if not lim.isdigit() or not 1 <= int(lim) <= LIMITE_MAX:
                    raise ParametroInvalido(f"limite deve ser de 1 a {LIMITE_MAX}")
                if not q and cv != "1":
                    raise ParametroInvalido("informe parte do nome ou use com_versoes=1")
                return self._json(200, listar_jogos(dados, q, cv == "1", int(lim)), head)
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


def criar_servidor(porta: int = PORTA_PADRAO, indice: str = busca.INDICE_PADRAO, arq_versoes: str = versoes.VERSOES_PADRAO, host: str = HOST) -> ThreadingHTTPServer:
    if host != HOST:
        raise ValueError("o painel só pode escutar em 127.0.0.1")
    if not (porta == 0 or 1024 <= porta <= 65535):
        raise ValueError("porta deve ser 0 (qualquer) ou de 1024 a 65535")
    dados = Dados(indice, arq_versoes)
    erros = versoes.validar_doc(dados.versoes())
    if erros:
        raise ValueError(f"o arquivo de versões tem {len(erros)} problema(s); rode: python -m ps4store.versoes --validar")
    dados.indice()                                              # falha cedo se o índice estiver corrompido (ausente é aceito)
    srv = ThreadingHTTPServer((HOST, porta), Handler)
    srv.daemon_threads = True
    srv.dados = dados
    return srv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.painel", description="interface web local (somente leitura) para jogos e versões CUSA")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    a = ap.parse_args(argv)
    try:
        srv = criar_servidor(a.porta, a.indice, a.versoes)
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
