"""Descoberta de links por jogo: fontes cadastradas (respostas SIMULADAS), correspondência, cache e fluxo até o bloco do SSPI (OpenTyrian simulado)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ps4store import analise_link, busca, descoberta_links, painel
from ps4store.resolver import ResolverNet
from test_painel import ROOT, SEMENTE, SEM_WD, Cli
from test_metadados import PKG_T8

CATALOGO = {"items": [
    {"titleId": "OPEN00001", "name": "OpenTyrian", "author": "x", "category": "game", "description": "GPL port",
     "releases": [{"console": "ps4", "version": "1.01", "active": True, "size": 6_000_000, "date": "2024-01-01"}]},
    {"titleId": "OPEN00002", "name": "OpenTyrian 2000", "releases": [{"console": "ps4", "version": "1.0", "active": True}]},
    {"titleId": "CUSA95417", "name": "Outro nome", "releases": [{"console": "ps4", "version": "1.02", "active": True}]},
    {"titleId": "OPEN00009", "name": "OpenTyrian", "releases": [{"console": "ps5", "version": "1.0", "active": True}]}]}


class Net:
    def __init__(self, base):
        self.base, self.pedidos = base, []

    def get_json(self, url):
        self.pedidos.append(url)
        if url.endswith("/api/v1/catalog"):
            return CATALOGO
        if "/releases" in url:
            return [{"id": 1, "tag_name": "v1.0", "html_url": "https://github.com/a/b/releases/v1.0", "published_at": "2024", "assets": [
                {"id": 9, "name": "IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg", "browser_download_url": "https://github.com/a/b/releases/download/v1.0/x.pkg", "size": 7, "state": "uploaded"},
                {"id": 8, "name": "leia-me.txt", "browser_download_url": "https://github.com/a/b/x.txt", "size": 1}]}]
        return []


def fontes(base):
    return [{"id": "pkg-zone", "nome": "PKG-Zone (simulado)", "tipo": "pkg-zone-catalog", "base_url": base, "campos": ["titleId", "nome"], "autorizacao": None},
            {"id": "projeto", "nome": "Projeto (simulado)", "tipo": "github-releases", "repo": "a/b", "campos": ["arquivo"], "autorizacao": "software do autor"}]


def test_cadastro_do_repositorio_e_valido_e_so_tem_conectores_estruturados():
    fs = descoberta_links.carregar_fontes(str(ROOT / "config" / "fontes-links.json"))
    assert {f["tipo"] for f in fs} <= set(descoberta_links.CONECTORES) and any(f["id"] == "pkg-zone" for f in fs)
    assert all(f["autorizacao"] is None or f["autorizacao"] for f in fs)


def test_busca_por_nome_exato_cusa_e_content_id_sem_parecidos_e_com_cache():
    net = Net("https://pkg-zone.com")
    cache = {}
    j = {"qid": "", "nome": "OpenTyrian", "cusas": [], "contentIds": []}
    r = descoberta_links.descobrir(j, fontes("https://pkg-zone.com"), net, cache)
    assert [x["url"] for x in r["resultados"]] == ["https://pkg-zone.com/download/ps4/OPEN00001/1.01"]                 # nem "OpenTyrian 2000" nem PS5
    x = r["resultados"][0]
    assert x["formato"] == "PKG" and not x["autorizado"] and x["autorizacao"].startswith("não verificada") and x["correspondencia"]["como"] == "nome"
    n = len(net.pedidos)
    descoberta_links.descobrir(j, fontes("https://pkg-zone.com"), net, cache)
    assert len(net.pedidos) == n                                                                                     # cache: nada consultado de novo
    j2 = {"qid": "Q1", "nome": "Jogo Teste", "cusas": ["CUSA95417"], "contentIds": ["IV0000-CUSA95417_00-PS4STOREBRTEST00"]}
    r2 = descoberta_links.descobrir(j2, fontes("https://pkg-zone.com"), net, cache)
    como = {x["fonteId"]: x["correspondencia"]["como"] for x in r2["resultados"]}
    assert como == {"pkg-zone": "cusa", "projeto": "contentId"} and r2["resultados"][0]["autorizado"]                 # autorizado e forte primeiro
    vazio = descoberta_links.descobrir({"qid": "Q2", "nome": "Grand Theft Auto V", "cusas": ["CUSA00411"], "contentIds": []}, fontes("https://pkg-zone.com"), net, cache)
    assert vazio["resultados"] == [] and vazio["texto"] == "Nenhum link encontrado nas fontes consultadas"


def test_fonte_com_erro_nao_derruba_as_outras():
    class Ruim(Net):
        def get_json(self, url):
            if "catalog" in url:
                raise descoberta_links.NetError("HTTP 503")
            return super().get_json(url)
    r = descoberta_links.descobrir({"qid": "Q1", "nome": "x", "cusas": ["CUSA95417"], "contentIds": []}, fontes("https://pkg-zone.com"), Ruim("b"), {})
    assert r["fontes"][0]["origem"].startswith("erro") and len(r["resultados"]) == 1


# ---------- fluxo completo: descobrir -> analisar bytes -> bloco SSPI (servidor local no lugar do PKG-Zone) ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/download/ps4/OPEN00001/1.01"):
            self.send_response(302)
            self.send_header("Location", "/arquivos/OpenTyrian.pkg")
            self.end_headers()
            return
        if self.path.startswith("/arquivos/"):
            a, b = (int(x) for x in self.headers.get("Range", "bytes=0-65535")[6:].split("-"))
            b = min(b, len(PKG_T8) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(PKG_T8)}")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(b - a + 1))
            self.end_headers()
            self.wfile.write(PKG_T8[a:b + 1])
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def local():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_opentyrian_descoberto_analisado_e_pronto_para_sspi(local, tmp_path):
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(str(ROOT / "config" / "busca-fontes.json")), "wikidata",
                   [{"nome": "OpenTyrian", "url": "https://www.wikidata.org/wiki/Q990990001", "idFonte": "wikidata:Q990990001"}])
    idx = tmp_path / "idx.json"
    busca.salvar_indice(d, str(idx))
    fl = tmp_path / "fl.json"
    fl.write_text(json.dumps({"schema": descoberta_links.SCHEMA, "fontes": [fontes(local)[0] | {"base_url": "https://pkg-zone.invalid"}]}))
    s = painel.criar_servidor(0, str(idx), SEMENTE, arq_cusas=SEM_WD, dir_capas=str(tmp_path / "c"), arq_apelidos=str(ROOT / "data" / "apelidos.json"),
                              arq_metadados="/nao/existe/m.json")
    s.fontes_links, s.cache_links_arq = str(fl), "/nao/existe/cache.json"
    net = Net(local)

    def get_json(url):                                                    # o catálogo aponta para o servidor local (base_url da fonte simulada)
        cat = json.loads(json.dumps(CATALOGO))
        return cat
    net.get_json = get_json
    s.rede_descoberta = net
    s.rede_links, s.hosts_links = ResolverNet(allow_insecure=True, timeout=5), {"127.0.0.1"}
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    try:
        assert c.get("/api/links?qid=Q990990001")[0] == 403                                                         # sem cabeçalho do painel
        import http.client

        def h(path):
            cx = http.client.HTTPConnection("127.0.0.1", c.port, timeout=15)
            cx.request("GET", path, headers={"X-PS4Store": "1", "Host": f"127.0.0.1:{c.port}"})
            r = cx.getresponse()
            return r.status, json.loads(r.read())
        st, r = h("/api/links?qid=Q990990001")
        assert st == 200 and len(r["resultados"]) == 1 and r["resultados"][0]["url"] == "https://pkg-zone.invalid/download/ps4/OPEN00001/1.01"
        url_local = r["resultados"][0]["url"].replace("https://pkg-zone.invalid", local)                          # mesma rota servida localmente (sem rede externa)
        an = analise_link.analisar(url_local, "Q990990001", {"versoes": []}, {"registros": [], "conflitos": []}, s.rede_links, s.hosts_links)
        a = an["arquivos"][0]
        assert a["formato"] == "pkg" and a["identificacao"]["contentId"] == "IV0000-CUSA95417_00-PS4STOREBRTEST00"
        assert an["sspi"]["blocos"][0]["pronto"] and an["sspi"]["blocos"][0]["urls"] == [url_local]                # URL estável da fonte (não a final)
        assert h("/api/links?qid=Q1")[0] == 404 and h("/api/links?qid=x")[0] == 400
    finally:
        s.shutdown()
        s.server_close()
