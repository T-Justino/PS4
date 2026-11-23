"""5G: capas (importador com respostas simuladas, sem rede), rota /capa/<Qid>, busca inteligente no painel e um teste visual a ~390 px."""
import json
import struct
import threading
import zlib
from pathlib import Path

import pytest

from ps4store import capas, painel
from test_painel import ROOT, SEMENTE, SEM_WD, Cli, faz_indice


def png_min() -> bytes:
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + ch(b"IEND", b"")


def pagina(titulo, lic="CC BY-SA 4.0", autor="Fulano", cats=(), mime="image/png", extra=None):
    ext = {"LicenseShortName": {"value": lic}, "Artist": {"value": autor}, "AttributionRequired": {"value": "true"}}
    ext.update(extra or {})
    return {"title": titulo, "categories": [{"title": c} for c in cats],
            "imageinfo": [{"mime": mime, "thumburl": "https://upload.wikimedia.org/x/" + titulo.replace(" ", "_"), "descriptionurl": "https://commons.wikimedia.org/wiki/" + titulo.replace(" ", "_"),
                           "thumbwidth": 360, "thumbheight": 480, "extmetadata": ext}]}


def fetch_falso(imgs: dict, paginas: list[dict], png=None):
    """imgs: Q-id -> nome do arquivo no P18; paginas: páginas File: do Commons."""
    corpo_png = png or png_min()

    def f(url, maximo):
        if "query.wikidata.org" in url:
            b = [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "img": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/" + n.replace(" ", "%20")}} for q, n in imgs.items()]
            return json.dumps({"results": {"bindings": b}}).encode()
        if "commons.wikimedia.org/w/api.php" in url:
            return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate(paginas)}}}).encode()
        if "upload.wikimedia.org" in url:
            return corpo_png
        raise AssertionError(url)
    return f


def test_licencas_so_livres_e_claras():
    for ok in ("CC BY-SA 4.0", "CC BY 3.0", "CC0", "Public domain", "CC BY-SA 2.5"):
        assert capas.licenca_aceita(ok)[0], ok
    for ruim in ("CC BY-NC 4.0", "CC BY-ND 2.0", "GFDL", "Fair use", "", "All rights reserved", "licença qualquer", "CC BY-NC-SA 3.0"):
        assert not capas.licenca_aceita(ruim)[0], ruim


def test_importacao_valida_grava_so_aceitas_e_distingue_capa_de_ilustrativa(tmp_path):
    d = str(tmp_path / "capas")
    pgs = [pagina("File:Capa A.png", cats=["Category:Video game covers"]), pagina("File:Foto B.png"), pagina("File:Nc C.png", lic="CC BY-NC 4.0"),
           pagina("File:SemAutor D.png", autor=""), pagina("File:Desc E.png", lic="")]
    imgs = {"Q990000001": "Capa A.png", "Q990000002": "Foto B.png", "Q990000003": "Nc C.png", "Q990000004": "SemAutor D.png", "Q990000005": "Desc E.png"}
    qs = [(q, q) for q in imgs] + [("Q990000006", "sem p18")]
    est = capas.importar(qs, fetch_falso(imgs, pgs), d, pausa=0, dormir=lambda s: None)
    assert est["comImagem"] == 2 and est["capa"] == 1 and est["ilustrativa"] == 1 and est["semP18"] == 1 and sum(est["rejeitadas"].values()) == 3
    idx = capas.carregar_indice(d)
    assert idx["capas"]["Q990000001"]["tipo"] == "capa" and idx["capas"]["Q990000002"]["tipo"] == "ilustrativa"
    assert "Fulano" in idx["capas"]["Q990000001"]["atribuicao"] and idx["capas"]["Q990000001"]["licenca"] == "CC BY-SA 4.0"
    assert {p.name for p in Path(d).iterdir()} == {"indice.json", "Q990000001.png", "Q990000002.png"}
    assert idx["semImagem"]["Q990000003"]["motivo"].startswith("licenca-nao-permitida") and "autor" in idx["semImagem"]["Q990000004"]["motivo"]
    assert idx["semImagem"]["Q990000005"]["motivo"] == "licenca-desconhecida"
    est2 = capas.importar(qs, lambda u, m: (_ for _ in ()).throw(AssertionError("não deve refazer rede")), d, pausa=0)     # incremental: nada pendente
    assert est2["jaTinham"] == 6 and est2["requisicoes"] == 0


def test_bytes_que_nao_sao_imagem_ou_grandes_demais_sao_rejeitados(tmp_path):
    d = str(tmp_path / "c")
    imgs = {"Q990000001": "A.png"}
    est = capas.importar([("Q990000001", "A")], fetch_falso(imgs, [pagina("File:A.png")], png=b"<html>nao sou imagem</html>"), d, pausa=0)
    assert est["comImagem"] == 0 and "formato-invalido" in capas.carregar_indice(d)["semImagem"]["Q990000001"]["motivo"]
    assert not list(Path(d).glob("Q*"))
    with pytest.raises(ValueError):
        capas._http("https://exemplo.invalid/x.png", "ua", 10)                          # host fora da lista
    with pytest.raises(ValueError):
        capas._http("http://upload.wikimedia.org/x.png", "ua", 10)                      # só https


def test_teto_de_requisicoes_e_amostra_maxima(tmp_path):
    assert capas.MAX_AMOSTRA == 30
    idx = {"titulos": [{"nome": f"Jogo {i}", "idFonte": f"wikidata:Q99{i:05d}"} for i in range(1, 80)]}
    assert len(capas.escolher_amostra(idx, {"versoes": []}, {"registros": []}, ["jogo"], 500)) == 30
    with pytest.raises(RuntimeError):
        capas.importar([("Q990000001", "A")], fetch_falso({"Q990000001": "A.png"}, [pagina("File:A.png")]), str(tmp_path / "c"), pausa=0, max_req=1)


# ---------- rota /capa e painel ----------
@pytest.fixture
def srv_capas(tmp_path):
    d = tmp_path / "capas"
    imgs = {"Q15891648": "Arkham.png"}
    capas.importar([("Q15891648", "Batman: Arkham Knight")], fetch_falso(imgs, [pagina("File:Arkham.png", cats=["Category:Video game covers"])]), str(d), pausa=0)
    (tmp_path / "segredo.txt").write_text("segredo")
    s = painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE, arq_cusas=SEM_WD, dir_capas=str(d), arq_apelidos=str(ROOT / "data" / "apelidos.json"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield Cli(s)
    s.shutdown()
    s.server_close()


def test_rota_capa_serve_so_por_qid_validado(srv_capas):
    st, h, corpo = srv_capas.req("GET", "/capa/Q15891648")
    assert st == 200 and h["content-type"] == "image/png" and corpo[:4] == b"\x89PNG" and h["x-content-type-options"] == "nosniff"
    assert srv_capas.req("HEAD", "/capa/Q15891648")[0] == 200
    for ruim in ("/capa/Q1", "/capa/Q15891648.png", "/capa/../segredo.txt", "/capa/%2e%2e%2fsegredo.txt", "/capa/Q15891648/../../x", "/capa/", "/capa/q15891648", "/capa/Q15891648?x=1",
                 "/capa/indice.json", "/capa/Q99999999999999"):
        assert srv_capas.req("GET", ruim)[0] in (400, 404), ruim
    assert srv_capas.req("POST", "/capa/Q15891648")[0] == 405


def test_api_traz_capa_com_tipo_e_atribuicao_e_jogo_sem_imagem_fica_sem(srv_capas):
    j = srv_capas.get("/api/jogos?q=batman")[2]
    com = next(i for i in j["itens"] if i["qid"] == "Q15891648")
    assert com["capa"] == {"url": "/capa/Q15891648", "tipo": "capa"}
    assert all(i["capa"] is None for i in j["itens"] if i["qid"] != "Q15891648")
    d = srv_capas.get("/api/jogo?qid=Q15891648")[2]
    assert d["capa"]["tipo"] == "capa" and "CC BY-SA" in d["capa"]["atribuicao"] and "arquivo" not in d["capa"] and "/" not in d["capa"].get("caminho", "")
    assert srv_capas.get("/api/jogo?qid=Q990700002")[2]["capa"] is None


def test_busca_exata_apelido_e_sugestao_no_painel(srv_capas):
    j = srv_capas.get("/api/jogos?q=batman")[2]
    assert j["total"] == 3 and j["sugestoes"] == [] and j["offset"] == 0 and not j["temMais"]
    j = srv_capas.get("/api/jogos?q=batmna+arkham")[2]
    assert j["total"] == 0 and {s["qid"] for s in j["sugestoes"]} >= {"Q15891648"}
    j = srv_capas.get("/api/jogos?q=batman&limite=1&offset=1")[2]
    assert j["mostrando"] == 1 and j["offset"] == 1 and j["temMais"]
    assert srv_capas.get("/api/jogos?q=batman&offset=-1")[0] == 400 and srv_capas.get("/api/jogos?q=batman&offset=x")[0] == 400
    assert srv_capas.get("/api/jogo?qid=Q15891648&cusa=")[2]["total"] == 3            # CUSAs preservados


def test_visual_390px_com_capa_placeholder_e_sugestao(srv_capas, tmp_path):
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
        pg.goto(f"http://127.0.0.1:{srv_capas.port}/")
        pg.fill("#q", "batman")
        pg.click("button.primario")
        pg.wait_for_selector("#lista li")
        assert pg.locator("#lista li").count() == 3
        assert pg.locator("#lista li img").count() == 1 and pg.locator("#lista li .selo.vazio").count() == 2 and pg.locator("#lista li .selo", has_text="capa").count() >= 1
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")                 # sem rolagem horizontal
        pg.screenshot(path="/tmp/claude-0/-home-user-PS4/b867e52c-c743-5e36-9ba7-9256e64f3d0c/scratchpad/grade390.png")
        pg.fill("#q", "batmna arkham")
        pg.click("button.primario")
        pg.locator("#sugestoes button").first.wait_for(timeout=8000)
        pg.locator("#sugestoes button").first.click()
        pg.wait_for_selector("#lista li")
        pg.locator("#lista li").first.click()
        pg.locator("#jogo .hero img").wait_for(timeout=8000)
        assert pg.locator("#jogo details.atribuicao").count() == 1 and "CC BY-SA" in pg.locator("#jogo details.atribuicao").text_content()
        assert not erros, erros
    finally:
        b.close()
        ctx.stop()


# ---------- 5H-complemento: múltiplos provedores, conferência do jogo, fila ----------
def fetch_multi(p18=None, wiki=None, busca=None, commons=None):
    """p18: {qid: arquivo}; wiki: {titulo_artigo: arquivo}; busca: {termo: [páginas]}; commons: páginas File: por título (resolução por nome)."""
    commons = commons or {}

    def f(url, maximo):
        if "query.wikidata.org" in url:
            b = [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "img": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/" + n.replace(" ", "%20")}} for q, n in (p18 or {}).items()]
            return json.dumps({"results": {"bindings": b}}).encode()
        if ".wikipedia.org/w/api.php" in url:
            import urllib.parse as up
            tits = up.unquote(url.split("titles=")[1]).split("|")
            pgs = {str(i): {"title": t, **({"pageimage": wiki[t].replace(" ", "_")} if t in (wiki or {}) else {})} for i, t in enumerate(tits)}
            return json.dumps({"query": {"pages": pgs}}).encode()
        if "generator=search" in url:
            import urllib.parse as up
            termo = up.unquote(url.split("gsrsearch=")[1]).split('"')[1]
            return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate((busca or {}).get(termo, []))}}}).encode()
        if "commons.wikimedia.org/w/api.php" in url:
            import urllib.parse as up
            tits = up.unquote(url.split("titles=")[1]).split("|")
            return json.dumps({"query": {"pages": {str(i): commons[t] for i, t in enumerate(tits) if t in commons}}}).encode()
        if "upload.wikimedia.org" in url:
            return png_min()
        raise AssertionError(url)
    return f


def test_fallback_entre_provedores_e_ordem(tmp_path):
    d = str(tmp_path / "c")
    jogos = [("Q990100001", "Jogo Um", "2015", "https://en.wikipedia.org/wiki/Jogo_Um"),            # P18 com licença NC -> cai para a Wikipedia (livre)
             ("Q990100002", "Jogo Dois", "2016", "https://en.wikipedia.org/wiki/Jogo_Dois_(video_game)"),   # sem P18; Wikipedia sem imagem -> busca no Commons
             ("Q990100003", "Jogo Tres", "2017", "https://en.wikipedia.org/wiki/Jogo_Tres"),          # nada em lugar nenhum -> placeholder
             ("Q990100004", "Jogo Quatro", None, "")]                                                  # sem página no índice: só P18
    commons = {"File:NC Um.png": pagina("File:NC Um.png", lic="CC BY-NC 4.0"), "File:Livre Um.png": pagina("File:Livre Um.png"),
               "File:P4.png": pagina("File:P4.png", mime="image/png")}
    busca = {"Jogo Dois": [pagina("File:Jogo Dois cover.png", cats=["Category:Video game covers"], extra={"ImageDescription": {"value": "Cover of the video game Jogo Dois"}})]}
    f = fetch_multi(p18={"Q990100001": "NC Um.png", "Q990100004": "P4.png"}, wiki={"Jogo Um": "Livre Um.png"}, busca=busca, commons=commons)
    est = capas.importar(jogos, f, d, pausa=0, dormir=lambda s: None)
    assert est["comImagem"] == 3 and est["porProvedor"] == {"wikidata-p18": 1, "wikipedia": 1, "commons-busca": 1} and est["semP18"] == 1
    idx = capas.carregar_indice(d)
    assert idx["capas"]["Q990100001"]["provedor"] == "wikipedia" and "Jogo Um" in idx["capas"]["Q990100001"]["correspondencia"]
    assert idx["capas"]["Q990100002"]["provedor"] == "commons-busca" and idx["capas"]["Q990100002"]["tipo"] == "capa"
    assert idx["capas"]["Q990100004"]["provedor"] == "wikidata-p18" and idx["capas"]["Q990100004"]["jogo"]["qid"] == "Q990100004"
    assert idx["capas"]["Q990100001"]["consultadoEm"] and idx["capas"]["Q990100001"]["paginaUrl"].startswith("https://commons.wikimedia.org/")
    assert "thumbUrl" not in idx["capas"]["Q990100001"] and "Q990100003" in idx["semImagem"]               # sem URL externa guardada para exibição (só cache local)
    # provedor escolhido pelo usuário limita a busca
    est2 = capas.importar([("Q990100009", "Outro", None, "")], fetch_multi(), d, pausa=0, provedores=("wikidata-p18",))
    assert est2["comImagem"] == 0


def test_correspondencia_imagem_jogo_rejeita_sequencia_filme_e_ano_errado():
    c = capas.confere_titulo_arquivo
    assert c("Batman: Arkham Knight", "2015", "File:Batman Arkham Knight cover.jpg")
    assert c("Batman: Arkham Knight", "2015", "File:Batman Arkham Knight 2015 screenshot.png")
    assert not c("Batman: Arkham Knight", "2015", "File:Batman Arkham Knight 2 cover.jpg")          # outra numeração
    assert not c("Batman: Arkham Knight", "2015", "File:Batman Arkham Knight 2019 Comic-Con.jpg")   # ano diferente
    assert not c("Batman", "1989", "File:Batman Arkham Knight cover.jpg")                            # nome do jogo é prefixo de outro título
    assert not c("Doom", None, "File:Doom Eternal cover.jpg")
    assert c("Doom", None, "File:Doom cover.png") and c("Cyberpunk 2077", "2020", "File:Cyberpunk 2077 logo.svg".replace("svg", "png"))


def test_busca_commons_rejeita_arquivo_sem_indicio_de_videogame_e_de_outro_jogo(tmp_path):
    d = str(tmp_path / "c")
    busca = {"Doom": [pagina("File:Doom Eternal cover.png", extra={"ImageDescription": {"value": "video game"}}),            # outro jogo
                      pagina("File:Doom poster.png", extra={"ImageDescription": {"value": "a film poster"}})]}                  # sem indício de videogame
    est = capas.importar([("Q990200001", "Doom", None, "")], fetch_multi(busca=busca), d, pausa=0)
    assert est["comImagem"] == 0 and not list(Path(d).glob("Q*"))


def test_prefere_imagem_vertical_a_horizontal(tmp_path):
    d = str(tmp_path / "c")
    h = pagina("File:Jogo H cover.png"); h["imageinfo"][0].update(thumbwidth=360, thumbheight=200)
    v = pagina("File:Jogo H box.png"); v["imageinfo"][0].update(thumbwidth=360, thumbheight=500)
    for p in (h, v):
        p["imageinfo"][0]["extmetadata"]["ImageDescription"] = {"value": "video game"}
    est = capas.importar([("Q990200002", "Jogo H", None, "")], fetch_multi(busca={"Jogo H": [h, v]}), d, pausa=0)
    assert est["comImagem"] == 1 and capas.carregar_indice(d)["capas"]["Q990200002"]["arquivoCommons"] == "File:Jogo H box.png"


def test_sem_imagem_nao_e_reconsultado_logo_e_fila_avanca(tmp_path):
    d = str(tmp_path / "c")
    jogos = [("Q990300001", "Nada Aqui", None, "")]
    capas.importar(jogos, fetch_multi(), d, pausa=0)
    assert "Q990300001" in capas.carregar_indice(d)["semImagem"]
    est = capas.importar(jogos, lambda u, m: (_ for _ in ()).throw(AssertionError("não deve consultar")), d, pausa=0)
    assert est["requisicoes"] == 0 and est["jaTinham"] == 1
    idx = {"titulos": [{"nome": f"Jogo {i}", "idFonte": f"wikidata:Q99{i:05d}", "url": ""} for i in range(1, 50)]}
    wd = {"registros": [{"cusa": f"CUSA{i:05d}", "jogo": f"Jogo {i}", "qid": f"Q99{i:05d}", "origem": "wikidata", "evidencias": []} for i in range(1, 50)]}
    a = capas.escolher_amostra(idx, {"versoes": []}, {"registros": []}, ["jogo 7"], 3, ignorar={"Q9900007"}, prioridade=["Q9900042", "Q9999999"])
    assert [x[0] for x in a][0] == "Q9900042" and "Q9900007" not in [x[0] for x in a] and len(a) == 3


def test_painel_expoe_interesse_so_em_memoria_e_importador_le(srv_capas, tmp_path):
    assert srv_capas.get("/api/interesse")[2] == {"qids": []}
    srv_capas.get("/api/jogo?qid=Q15891648")
    srv_capas.get("/api/jogos?q=batman")
    q = srv_capas.get("/api/interesse")[2]["qids"]
    assert q[0] in ("Q990700002", "Q990700003", "Q15891648") and "Q15891648" in q and all(capas.QID_RE.match(x) for x in q)
    assert capas.interesse_do_painel(srv_capas.port) == q
    assert capas.interesse_do_painel(1) == []                                                      # painel fora do ar: segue sem prioridade
    assert srv_capas.get("/api/interesse?x=1")[0] == 400 and srv_capas.req("POST", "/api/interesse")[0] == 405
    assert not (tmp_path / "interesse.json").exists()
