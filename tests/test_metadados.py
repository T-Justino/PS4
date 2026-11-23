"""5H: metadados (atualização oficial, idiomas PT-BR), filtro PT-BR no painel e análise de link -> SSPI.
TUDO com respostas simuladas (sem rede externa): os valores de teste NÃO são dados reais de jogos."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from ps4store import analise_link, metadados, painel
from ps4store.resolver import ResolverNet
from test_painel import ROOT, SEMENTE, SEM_WD, Cli, faz_indice

PKG_T8 = (ROOT / "dist/t8/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg").read_bytes()

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<titlepatch titleid="CUSA00133"><tag name="X" mandatory="true">
<package version="01.14" size="1234567890" digest="d" manifest_url="https://exemplo.invalid/m.json" content_id="UP1018-CUSA00133_00-B000000000001563"
 system_ver="0x05050000" type="cumulative"><paramsfo><title>Batman: Arkham Knight</title></paramsfo></package></tag></titlepatch>"""


def fake(respostas: dict):
    """respostas: trecho da URL -> (status, bytes). Registra as URLs pedidas."""
    pedidas = []

    def f(url, maximo):
        pedidas.append(url)
        for k, v in respostas.items():
            if k in url:
                return v
        return 404, b""
    f.pedidas = pedidas
    return f


def wd_linhas(qid, itens):
    b = [{"g": {"value": f"http://www.wikidata.org/entity/{qid}"}, "tag": {"value": t}, **({"parteLab": {"value": p}} if p else {})} for t, p in itens]
    return 200, json.dumps({"results": {"bindings": b}}).encode()


# ---------- Sony ----------
def test_xml_oficial_versao_tamanho_firmware_e_url_derivada_do_cusa():
    u = metadados.url_xml_sony("CUSA00133")
    assert u.startswith("https://gs-sec.ww.np.dl.playstation.net/plo/np/CUSA00133/") and u.endswith("/CUSA00133-ver.xml") and len(u.split("/")[-2]) == 64
    r = metadados.consultar_sony("CUSA00133", fake({"CUSA00133-ver.xml": (200, XML)}))
    assert r["status"] == "ok" and r["versao"] == "01.14" and r["tamanhoBytes"] == 1234567890 and r["firmwareMinimo"] == "5.05" and r["firmwareAcimaDe900"] is False
    assert r["grau"] == "oficial" and r["consultadoEm"] and r["fonte"].startswith("Sony")
    alto = metadados.consultar_sony("CUSA00133", fake({"ver.xml": (200, XML.replace(b"0x05050000", b"0x10010000"))}))
    assert alto["firmwareMinimo"] == "10.01" and alto["firmwareAcimaDe900"] is True
    assert metadados.consultar_sony("CUSA00133", fake({}))["status"] == "sem-atualizacao"                      # 404: nenhum patch (não é erro, não é 'não existe jogo')
    outro = metadados.consultar_sony("CUSA00133", fake({"ver.xml": (200, XML.replace(b"CUSA00133_00", b"CUSA99999_00"))}))
    assert outro["status"] == "erro" and "outro CUSA" in outro["erro"]                                          # nunca liga dado de outro CUSA
    assert metadados.consultar_sony("CUSA00133", fake({"ver.xml": (200, b"<!DOCTYPE x [<!ENTITY a 'b'>]><x/>")}))["status"] == "erro"
    hist = metadados.consultar_sony("CUSA00133", fake({"ver.xml": (200, XML)}), anterior={"versao": "01.10", "consultadoEm": "2026-01-01"})
    assert hist["historico"] == [{"versao": "01.10", "vistoEm": "2026-01-01"}]


def test_rede_restrita_a_hosts_fixos_e_http_so_com_opcao_para_a_sony():
    ok = metadados.url_permitida
    assert ok("https://query.wikidata.org/sparql?q=1") and ok("https://store.playstation.com/pt-br/product/X") and ok(metadados.url_xml_sony("CUSA00001"))
    assert not ok("http://gs-sec.ww.np.dl.playstation.net/x") and ok("http://gs-sec.ww.np.dl.playstation.net/x", permitir_http=True)
    assert not ok("http://store.playstation.com/x", permitir_http=True) and not ok("https://evil.example/x") and not ok("https://u:p@store.playstation.com/x")
    with pytest.raises(ValueError):
        metadados.http_get("https://127.0.0.1/x", "ua", 10)


# ---------- PT-BR ----------
def test_ptbr_distingue_audio_texto_legendas_ptpt_e_sem_variante_sem_usar_regiao():
    v = metadados.variante
    assert [v("pt-BR"), v("pt_BR"), v("Português (Brasil)"), v("Brazilian Portuguese"), v("pt-PT"), v("Portuguese (Portugal)"), v("pt"), v("Português"), v("en")] == \
        ["pt-BR", "pt-BR", "pt-BR", "pt-BR", "pt-PT", "pt-PT", "pt", "pt", None]
    regs = [{"origem": "curado", "cusa": "CUSA00133", "contentId": "UP1018-CUSA00133_00-B000000000001563", "regiao": {"codigo": "US"}, "idiomas": None}]
    vazio = metadados.vazio()
    loc = metadados.localizacao("Q1", regs, vazio)
    assert loc["confirmadas"] == [] and loc["resumo"].startswith("desconhecido") and all(p["status"] == "desconhecido" for p in loc["partes"].values())
    doc = metadados.vazio()
    doc["idiomas"]["Q1"] = {"fonte": "Wikidata", "grau": "alegado", "consultadoEm": "x", "url": "u", "itens": [{"tag": "pt-BR", "parte": "audio"}, {"tag": "pt", "parte": "texto"}]}
    loc = metadados.localizacao("Q1", regs, doc)
    assert loc["confirmadas"] == [] and loc["informadas"] == ["audio"] and loc["partes"]["audio"]["status"] == "informado" and loc["ptSemVariante"]   # Wikidata ≠ confirmado; 'pt' ≠ PT-BR
    assert "só no Wikidata" in loc["resumo"] and metadados.filtro_ptbr(loc, "qualquer") and not metadados.filtro_ptbr(loc, "audio") and not metadados.filtro_ptbr(loc, "oficial")
    assert metadados.selos_ptbr(loc) == ["wikidata"]
    doc2 = metadados.vazio()
    doc2["loja"]["UP1018-CUSA00133_00-B000000000001563"] = {"status": "ok", "fonte": "PlayStation Store (pt-br)", "grau": "oficial", "audio": ["en", "es"], "tela": ["pt-BR", "en"]}
    loc2 = metadados.localizacao("Q1", regs, doc2)
    assert loc2["confirmadas"] == ["tela"] and loc2["partes"]["audio"]["status"] == "nao-consta" and metadados.filtro_ptbr(loc2, "texto") and metadados.selos_ptbr(loc2) == ["oficial"]
    doc3 = metadados.vazio()
    doc3["idiomas"]["Q1"] = {"fonte": "Wikidata", "grau": "alegado", "itens": [{"tag": "pt-PT", "parte": "audio"}]}
    assert metadados.localizacao("Q1", regs, doc3)["resumo"].startswith("só português europeu") and not metadados.filtro_ptbr(metadados.localizacao("Q1", regs, doc3), "qualquer")


def test_pagina_da_loja_e_wikidata_viram_listas_com_fonte_e_robots_e_respeitado():
    html = '<script>{"spokenLanguages":["en","pt-BR"],"screenLanguages":["en","pt-BR","fr"]}</script>'
    assert metadados.ler_pagina_loja(html) == {"audio": ["en", "pt-BR"], "tela": ["en", "pt-BR", "fr"]}
    f = fake({"/pt-br/product/": (200, html.encode())})
    r = metadados.consultar_loja("UP1018-CUSA00133_00-B000000000001563", f, lambda u: True)
    assert r["status"] == "ok" and r["url"].endswith("/pt-br/product/UP1018-CUSA00133_00-B000000000001563") and r["grau"] == "oficial"
    assert metadados.consultar_loja("UP1018-CUSA00133_00-B000000000001563", f, lambda u: False)["status"] == "nao-autorizado"
    rb = metadados.robots_da_loja(fake({"robots.txt": (200, b"User-agent: *\nDisallow: /pt-br/product/\n")}))
    assert not rb("https://store.playstation.com/pt-br/product/X") and rb("https://store.playstation.com/en-us/product/X")
    assert metadados.robots_da_loja(lambda u, m: (_ for _ in ()).throw(metadados.capas.ErroHttp(0, "rede:x")))("https://store.playstation.com/x") is False
    idi = metadados.consultar_idiomas_wikidata(["Q1", "Q2"], fake({"query.wikidata.org": wd_linhas("Q1", [("pt-BR", "voice acting"), ("pt-BR", "subtitle"), ("en", "")])}))
    assert [(i["tag"], i["parte"]) for i in idi["Q1"]["itens"]] == [("pt-BR", "audio"), ("pt-BR", "legendas"), ("en", "nao-especificada")] and idi["Q2"]["itens"] == []


def test_importacao_incremental_e_preserva_curados(tmp_path):
    cur = json.loads(Path(SEMENTE).read_text())
    antes = json.dumps(cur, sort_keys=True)
    wd = {"registros": [], "conflitos": []}
    doc = metadados.vazio()
    f = fake({"CUSA00133-ver.xml": (200, XML), "query.wikidata.org": wd_linhas("Q15891648", [("pt-BR", "user interface")]),
              "store.playstation.com": (200, b'"spokenLanguages":["en"],"screenLanguages":["pt-BR"]')})
    est = metadados.importar([("Q15891648", "Batman: Arkham Knight")], cur, wd, doc, f, pausa=0)
    assert est["sony"] and doc["atualizacoes"]["CUSA00133"]["versao"] == "01.14" and doc["idiomas"]["Q15891648"]["itens"][0]["parte"] == "texto"
    n = len(f.pedidas)
    metadados.importar([("Q15891648", "Batman: Arkham Knight")], cur, wd, doc, f, pausa=0)
    assert len(f.pedidas) == n                                                                                  # cache: nada consultado de novo
    assert json.dumps(cur, sort_keys=True) == antes                                                             # registros curados intactos
    p = tmp_path / "m.json"
    metadados.salvar(doc, str(p))
    assert metadados.carregar(str(p))["atualizacoes"]["CUSA00133"]["status"] == "ok"


# ---------- painel ----------
@pytest.fixture
def srv_meta(tmp_path):
    doc = metadados.vazio()
    doc["atualizacoes"]["CUSA00133"] = metadados.consultar_sony("CUSA00133", fake({"ver.xml": (200, XML)}))
    doc["idiomas"]["Q990700002"] = {"fonte": "Wikidata (P407 + P518)", "grau": "alegado", "consultadoEm": "2026-11-23T00:00:00+00:00", "url": "u",
                                    "itens": [{"tag": "pt-BR", "parte": "audio"}]}
    arq = tmp_path / "meta.json"
    metadados.salvar(doc, str(arq))
    ofi = tmp_path / "of.json"
    ofi.write_text(json.dumps({"schema": "ps4store.oficiais/v1", "produtos": [
        {"cusa": "CUSA00133", "escopo": "teste", "idiomas": {"audio": ["pt-BR"]}, "listaCompleta": False, "fonte": "Desenvolvedor X (simulado)", "tipo": "desenvolvedor",
         "url": "https://exemplo.invalid/idiomas", "obtidoEm": "2026-11-23", "verificacao": "teste"}]}))
    s = painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE, arq_cusas=SEM_WD, dir_capas=str(tmp_path / "c"), arq_apelidos=str(ROOT / "data" / "apelidos.json"),
                              arq_metadados=str(arq), arq_oficiais=str(ofi))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield Cli(s)
    s.shutdown()
    s.server_close()


def test_painel_filtro_ptbr_e_detalhe_com_patch_e_localizacao(srv_meta):
    j = srv_meta.get("/api/jogos?q=batman")[2]
    assert j["total"] == 3 and next(i for i in j["itens"] if i["qid"] == "Q15891648")["ptbr"] == ["oficial", "audio"]   # desconhecidos seguem na busca geral
    assert next(i for i in j["itens"] if i["qid"] == "Q990700002")["ptbr"] == ["wikidata"]
    assert [i["qid"] for i in srv_meta.get("/api/jogos?q=batman&ptbr=audio")[2]["itens"]] == ["Q15891648"]            # oficial: só o CUSA com fonte do desenvolvedor
    assert srv_meta.get("/api/jogos?q=batman&ptbr=texto")[2]["total"] == 0 and srv_meta.get("/api/jogos?q=batman&ptbr=qualquer")[2]["total"] == 2
    assert srv_meta.get("/api/jogos?ptbr=oficial")[2]["total"] == 1 and srv_meta.get("/api/jogos?ptbr=x")[0] == 400
    d = srv_meta.get("/api/jogo?qid=Q15891648")[2]
    assert d["localizacao"]["confirmadas"] == ["audio"] and d["localizacao"]["partes"]["texto"]["status"] == "desconhecido" and "CUSA00133" in d["localizacao"]["resumo"]
    assert d["localizacao"]["partes"]["audio"]["fontes"][0]["grau"] == "desenvolvedor"
    reg = next(r for r in d["registros"] if r["cusa"] == "CUSA00133")
    assert reg["oficial"][0]["escopo"] == "teste" and not next(r for r in d["registros"] if r["cusa"] == "CUSA00135")["oficial"]
    assert reg["atualizacao"]["versao"] == "01.14" and reg["atualizacao"]["firmwareMinimo"] == "5.05" and reg["versao"] is None   # patch ≠ versão do registro
    assert d["total"] == 3                                                                                       # registros (e conflitos) preservados


def test_rota_de_link_exige_cabecalho_do_painel_e_valida(srv_meta):
    assert srv_meta.get("/api/link?url=https://pkg-zone.com/x")[0] == 403                                        # sem X-PS4Store (pedido de outra página)
    assert srv_meta.req("POST", "/api/link?url=https://pkg-zone.com/x")[0] == 405 and srv_meta.req("OPTIONS", "/api/link")[0] == 405
    c = srv_meta

    def h(path):
        import http.client
        cx = http.client.HTTPConnection("127.0.0.1", c.port, timeout=10)
        cx.request("GET", path, headers={"X-PS4Store": "1", "Host": f"127.0.0.1:{c.port}"})
        r = cx.getresponse()
        return r.status, json.loads(r.read())
    assert h("/api/link")[0] == 400 and h("/api/link?url=https://a.com/x&qid=zz")[0] == 400
    st, d = h("/api/link?url=" + "https%3A%2F%2Fstore.playstation.com%2Fpt-br%2Fproduct%2FUP1018-CUSA00133_00-B000000000001563&qid=Q15891648")
    assert st == 200 and d["tipo"] == "pagina-loja" and d["sspi"] is None and d["arquivos"][0]["comparacao"]["resultado"] == "corresponde"
    st, d = h("/api/link?url=javascript:alert(1)")
    assert st == 200 and d["tipo"] == "invalida"
    st, d = h("/api/link?url=https%3A%2F%2F127.0.0.1%2Fx.pkg")
    assert st == 200 and not d["arquivos"] and d["naoArquivos"][0]["status"] == "HOST_NAO_PERMITIDO"            # host fora da lista: nenhuma requisição


# ---------- análise de link com servidor local (fluxo do OpenTyrian simulado: página -> PKG) ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/pagina":
            corpo, ct = b"<html><a href='/download/ps4/OPEN00001/1.01/app.pkg'>Download</a></html>", "text/html"
        elif p.endswith(".pkg"):
            rng = self.headers.get("Range", "bytes=0-65535")[6:].split("-")
            a, b = int(rng[0]), min(int(rng[1]), len(PKG_T8) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(PKG_T8)}")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(b - a + 1))
            self.end_headers()
            self.wfile.write(PKG_T8[a:b + 1])
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


@pytest.fixture(scope="module")
def local():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_link_de_pagina_ate_pkg_identifica_pelos_bytes_compara_e_prepara_sspi(local):
    net = ResolverNet(allow_insecure=True, timeout=5)
    cur = {"versoes": [{"qid": "Q1", "cusa": "CUSA95417", "jogo": "Teste"}, {"qid": "Q2", "cusa": "CUSA00001", "jogo": "Outro"}]}
    wd = {"registros": [], "conflitos": []}
    r = analise_link.analisar(local + "/pagina", "Q1", cur, wd, net, {"127.0.0.1"})
    a = r["arquivos"][0]
    assert r["tipo"] == "arquivos" and a["formato"] == "pkg" and a["identificacao"]["cusa"] == "CUSA95417" and a["identificacao"]["contentId"] == "IV0000-CUSA95417_00-PS4STOREBRTEST00"
    assert a["identificacao"]["base"].startswith("cabeçalho") and a["comparacao"]["resultado"] == "corresponde"
    assert r["sspi"]["blocos"] and r["sspi"]["blocos"][0]["pronto"] and r["sspi"]["blocos"][0]["urls"] == [local + "/download/ps4/OPEN00001/1.01/app.pkg"]
    r2 = analise_link.analisar(local + "/pagina", "Q2", cur, wd, net, {"127.0.0.1"})
    assert r2["arquivos"][0]["comparacao"]["resultado"] == "diferente" and not r2["sspi"]["blocos"][0]["pronto"]   # incompatível: não vai pronto
    wd_conf = {"registros": [], "conflitos": [{"cusa": "CUSA95417", "qids": ["Q1", "Q9"], "jogos": ["a", "b"]}]}
    r3 = analise_link.analisar(local + "/pagina", "Q1", cur, wd_conf, net, {"127.0.0.1"})
    assert r3["arquivos"][0]["comparacao"]["resultado"] == "conflito" and not r3["sspi"]["blocos"][0]["pronto"]  # conflito auditado não é resolvido


def test_identificacao_pelo_nome_do_arquivo_e_marcada_como_nao_verificada():
    i = analise_link._identificar_nome("https://h/EP0001-CUSA01234_00-ABCDEFGHIJ123456-A0114-V0100.pkg")
    assert i["cusa"] == "CUSA01234" and i["contentId"] == "EP0001-CUSA01234_00-ABCDEFGHIJ123456" and "não verificado" in i["base"]
    assert analise_link._identificar_nome("https://h/jogo.rar")["cusa"] is None


def test_interface_390px_mostra_ptbr_patch_e_secao_de_link(srv_meta):
    pw = pytest.importorskip("playwright.sync_api")
    ctx = pw.sync_playwright().start()
    try:
        b = ctx.chromium.launch()
    except Exception as e:
        ctx.stop()
        pytest.skip(f"Chromium indisponível: {str(e)[:60]}")
    try:
        pg = b.new_page(viewport={"width": 390, "height": 844})
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.goto(f"http://127.0.0.1:{srv_meta.port}/")
        pg.select_option("#f-ptbr", "audio")
        pg.wait_for_selector("#lista li")
        assert pg.locator("#lista li").count() == 1 and "PT-BR · áudio" in pg.locator("#lista li").first.inner_text()
        assert "Idiomas oficiais" not in pg.locator("#lista").inner_text()                                       # card sem excesso de metadados
        pg.locator("#lista li").first.click()
        pg.locator("#jogo .ptbr-box").wait_for(timeout=8000)
        txt = pg.locator("#jogo").inner_text()
        assert "Português do Brasil" in txt and "PT-BR confirmado por fonte oficial: áudio" in txt and "Idiomas oficiais deste CUSA" in txt and "01.14" in txt and "5.05" in txt and "NÃO garante compatibilidade" in txt
        assert txt.index("Português do Brasil") < txt.index("CUSA00133") < txt.index("Analisar link")                  # ordem pedida na SDD
        pg.fill("#link-url", "https://store.playstation.com/pt-br/product/UP1018-CUSA00133_00-B000000000001563")
        pg.click("#link-analisar")
        pg.locator("#link-resultado").filter(has_text="NÃO é link de arquivo PKG").wait_for(timeout=8000)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth") and not erros, erros
        pg.screenshot(path="/tmp/claude-0/-home-user-PS4/b867e52c-c743-5e36-9ba7-9256e64f3d0c/scratchpad/detalhe5h.png", full_page=True)
    finally:
        b.close()
        ctx.stop()



# ---------- correções após o teste real ----------
def _indice(nomes):
    return {"titulos": [{"nome": n, "idFonte": f"wikidata:Q99{i:05d}", "url": ""} for i, n in enumerate(nomes, 1)]}


def test_jogos_por_nome_exato_sem_encher_a_amostra_com_parecidos():
    idx = _indice(["Grand Theft Auto V", "Grand Theft Auto: Vice City", "Grand Theft Auto IV", "Cyberpunk 2077", "Batman: Arkham Knight", "Batman: Arkham City", "Doom", "Doom"])
    ap = json.loads((ROOT / "data" / "apelidos.json").read_text())["apelidos"]
    jogos, avisos = metadados.escolher_jogos(idx, {"versoes": []}, {"registros": []}, ["grand theft auto v", "cyberpunk 2077", "batman arkham knight"], 10, apelidos=ap)
    assert [j[1] for j in jogos] == ["Grand Theft Auto V", "Cyberpunk 2077", "Batman: Arkham Knight"] and not avisos
    jogos, _ = metadados.escolher_jogos(idx, {"versoes": []}, {"registros": []}, ["gta v"], 10, apelidos=ap)
    assert [j[1] for j in jogos] == ["Grand Theft Auto V"]                                                     # apelido com vínculo explícito
    jogos, avisos = metadados.escolher_jogos(idx, {"versoes": []}, {"registros": []}, ["grand theft auto", "doom"], 10, apelidos=ap)
    assert jogos == [] and "sem nome exato" in avisos[0] and "2 jogos com esse nome exato" in avisos[1]          # parecido/ambíguo: nada entra


def test_erro_de_rede_ou_tls_nao_bloqueia_nova_tentativa():
    cur = {"versoes": [{"qid": "Q1", "cusa": "CUSA00133", "jogo": "x"}]}
    wd = {"registros": [], "conflitos": []}
    doc = metadados.vazio()

    def tls(url, m):
        raise metadados.capas.ErroHttp(0, "tls:certificado-nao-verificado (unable to get local issuer certificate)")
    metadados.importar([("Q1", "x")], cur, wd, doc, tls, fontes=("sony",), pausa=0)
    a = doc["atualizacoes"]["CUSA00133"]
    assert a["status"] == "erro" and "local issuer" in a["erro"]
    f = fake({"ver.xml": (200, XML)})
    metadados.importar([("Q1", "x")], cur, wd, doc, f, fontes=("sony",), pausa=0)
    assert doc["atualizacoes"]["CUSA00133"]["status"] == "ok" and f.pedidas                                      # tentou de novo no mesmo dia
    def http_ok(url, m):
        if url.startswith("https"):
            raise metadados.capas.ErroHttp(0, "tls:certificado-nao-verificado")
        return 200, XML
    r = metadados.consultar_sony("CUSA00133", http_ok, permitir_http=True)
    assert r["status"] == "ok" and r["grau"] == "oficial-via-http" and r["url"].startswith("http://") and "integridade" in r["nota"]
    assert metadados.consultar_sony("CUSA00133", http_ok)["status"] == "erro"                                    # sem a opção, HTTP não é usado
    assert metadados.FONTES == ("sony", "wikidata") and "loja" in metadados.FONTES_VALIDAS                     # loja fora do padrão


def test_metadados_oficiais_por_cusa_do_repositorio_e_escopo():
    ofi = metadados.carregar_oficiais(str(ROOT / "data" / "metadados-oficiais.json"))
    assert not metadados.validar_oficiais(ofi)
    cur = json.loads(Path(SEMENTE).read_text())
    regs = [dict(r, origem="curado") for r in cur["versoes"] if r["qid"] == "Q3182559"]
    assert {r["cusa"] for r in regs} == {"CUSA16596", "CUSA16597", "CUSA16496", "CUSA20476"}
    assert all(r["evidencias"][0]["url"].startswith("https://support.cdprojektred.com/") for r in regs)
    loc = metadados.localizacao("Q3182559", regs, metadados.vazio(), ofi)
    assert loc["confirmadas"] == ["audio", "texto"] and "CUSA16596" in loc["resumo"] and loc["partes"]["legendas"]["status"] == "nao-consta"
    so_jp = [r for r in regs if r["cusa"] in ("CUSA16496", "CUSA20476")]
    loc_jp = metadados.localizacao("Q3182559", so_jp, metadados.vazio(), ofi)
    assert loc_jp["confirmadas"] == [] and loc_jp["partes"]["audio"]["status"] == "nao-consta" and "não consta" in loc_jp["resumo"]
    assert metadados.localizacao("Q3182559", [], metadados.vazio(), ofi)["resumo"].startswith("desconhecido")     # sem CUSA do jogo: nada é atribuído
    ruim = {"schema": "ps4store.oficiais/v1", "produtos": [{"cusa": "CUSA1", "escopo": "", "idiomas": {"voz": ["pt-BR"]}, "fonte": "x", "url": "http://a", "obtidoEm": "ontem"}]}
    assert len(metadados.validar_oficiais(ruim)) >= 5
