"""5G: capas (importador com respostas simuladas, sem rede), rota /capa/<Qid>, busca inteligente no painel e um teste visual a ~390 px."""
import json
from datetime import datetime, timedelta, timezone
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
                           "thumbwidth": 330, "thumbheight": 440, "width": 800, "height": 1000, "extmetadata": ext}]}


def fetch_falso(imgs: dict, paginas: list[dict], png=None):
    """imgs: Q-id -> nome do arquivo no P18; paginas: páginas File: do Commons."""
    corpo_png = png or png_min()

    def f(url, maximo):
        if "query.wikidata.org" in url:
            b = [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "k": {"value": "p18"}, "v": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/" + n.replace(" ", "%20")}} for q, n in imgs.items()]
            return json.dumps({"results": {"bindings": b}}).encode()
        if "generator=" in url:
            return json.dumps({"query": {"pages": {}}}).encode()
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
    s = painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE, arq_cusas=SEM_WD, dir_capas=str(d), arq_apelidos=str(ROOT / "data" / "apelidos.json"), arq_metadados="/nao/existe/meta.json")
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
def fetch_multi(p18=None, wiki=None, busca=None, commons=None, sitelinks=None, cats=None, logos=None, categoria=None, falha_thumb=None):
    """p18/logos: {qid: arquivo}; sitelinks: {qid: titulo_en}; wiki: {titulo: [arquivos do artigo]}; cats: {qid: categoria}; categoria: {nome: [páginas]};
    busca: {termo: [páginas]}; commons: páginas File: por título; falha_thumb: exceção a levantar no download."""
    import urllib.parse as up
    commons = commons or {}

    def f(url, maximo):
        if "query.wikidata.org" in url:
            b = []
            for k, dic in (("p18", p18), ("logo", logos)):
                b += [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "k": {"value": k}, "v": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/" + n.replace(" ", "%20")}} for q, n in (dic or {}).items()]
            b += [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "k": {"value": "wen"}, "v": {"value": t}} for q, t in (sitelinks or {}).items()]
            b += [{"g": {"value": f"http://www.wikidata.org/entity/{q}"}, "k": {"value": "cat"}, "v": {"value": c}} for q, c in (cats or {}).items()]
            return json.dumps({"results": {"bindings": b}}).encode()
        if ".wikipedia.org/w/api.php" in url:
            tits = up.unquote(url.split("titles=")[1]).split("|")
            pgs = {str(i): {"title": t, "images": [{"title": "File:" + a} for a in (wiki or {}).get(t, [])]} for i, t in enumerate(tits)}
            return json.dumps({"query": {"pages": pgs}}).encode()
        if "generator=search" in url:
            termo = up.unquote(url.split("gsrsearch=")[1]).split('"')[1]
            return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate((busca or {}).get(termo, []))}}}).encode()
        if "generator=categorymembers" in url:
            cat = up.unquote(url.split("gcmtitle=")[1]).split("&")[0].removeprefix("Category:")
            return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate((categoria or {}).get(cat, []))}}}).encode()
        if "commons.wikimedia.org/w/api.php" in url:
            tits = up.unquote(url.split("titles=")[1]).split("|")
            return json.dumps({"query": {"pages": {str(i): commons[t] for i, t in enumerate(tits) if t in commons}}}).encode()
        if "upload.wikimedia.org" in url:
            if falha_thumb:
                raise falha_thumb
            return png_min()
        raise AssertionError(url)
    return f


def test_fallback_entre_provedores_por_id_sem_exigir_nome_no_arquivo(tmp_path):
    d = str(tmp_path / "c")
    jogos = [("Q990100001", "Jogo Um", "2015", ""),      # P18 com licença NC -> cai para o artigo da Wikipedia (Q-id -> sitelink), arquivo SEM o nome do jogo
             ("Q990100002", "Jogo Dois", "2016", ""),    # sem P18/logo; categoria do Commons (P373) do Q-id
             ("Q990100003", "Jogo Tres", "2017", ""),    # só logo (P154)
             ("Q990100004", "Jogo Quatro", None, ""),    # nada ligado por ID; só a busca por nome acha
             ("Q990100005", "Jogo Cinco", None, "")]     # nada em lugar nenhum -> placeholder
    commons = {"File:NC Um.png": pagina("File:NC Um.png", lic="CC BY-NC 4.0"), "File:Foto qualquer.png": pagina("File:Foto qualquer.png"), "File:Logo Tres.png": pagina("File:Logo Tres.png")}
    f = fetch_multi(p18={"Q990100001": "NC Um.png"}, sitelinks={"Q990100001": "Jogo Um"}, wiki={"Jogo Um": ["Foto qualquer.png", "Flag of Brazil.png", "Question icon.png"]},
                    cats={"Q990100002": "Jogo Dois (video game)"}, logos={"Q990100003": "Logo Tres.png"},
                    categoria={"Jogo Dois (video game)": [pagina("File:Screenshot de 2016.png"), pagina("File:Padlock.png")]},
                    busca={"Jogo Quatro": [pagina("File:Jogo Quatro cover.png", extra={"ImageDescription": {"value": "video game"}})]}, commons=commons)
    est = capas.importar(jogos, f, d, pausa=0, dormir=lambda s: None)
    assert est["comImagem"] == 4 and est["porProvedor"] == {"wikipedia": 1, "commons-categoria": 1, "wikidata-outras": 1, "commons-busca": 1} and est["semP18"] == 1
    idx = capas.carregar_indice(d)
    assert idx["capas"]["Q990100001"]["provedor"] == "wikipedia" and "Q-id" in idx["capas"]["Q990100001"]["correspondencia"]
    assert idx["capas"]["Q990100001"]["arquivoCommons"] == "File:Foto qualquer.png"               # sem o nome do jogo, mas ligado por ID
    assert idx["capas"]["Q990100002"]["provedor"] == "commons-categoria" and idx["capas"]["Q990100003"]["provedor"] == "wikidata-outras"
    assert idx["capas"]["Q990100004"]["provedor"] == "commons-busca" and idx["capas"]["Q990100004"]["jogo"]["qid"] == "Q990100004"
    assert idx["capas"]["Q990100001"]["consultadoEm"] and idx["capas"]["Q990100001"]["paginaUrl"].startswith("https://commons.wikimedia.org/")
    assert "thumbUrl" not in idx["capas"]["Q990100001"]
    neg = idx["semImagem"]["Q990100005"]
    assert neg["motivo"] == "sem-candidato" and neg["versao"] == capas.IMPORTADOR_VERSAO and any(t.startswith("wikipedia:") for t in neg["tentativas"])
    est2 = capas.importar([("Q990100009", "Outro", None, "")], fetch_multi(), d, pausa=0, provedores=("wikidata-p18",))
    assert est2["comImagem"] == 0


def test_download_falho_registra_causa_real_e_e_refeito_logo(tmp_path):
    d = str(tmp_path / "c")
    jogos = [("Q990400001", "Jogo", None, "")]
    f429 = fetch_multi(p18={"Q990400001": "A.png"}, commons={"File:A.png": pagina("File:A.png")}, falha_thumb=capas.ErroHttp(429, "Too Many Requests", "30"))
    est = capas.importar(jogos, f429, d, pausa=0)
    assert est["comImagem"] == 0 and est["falhasDownload"] == {"HTTP 429 Too Many Requests": 1}
    neg = capas.carregar_indice(d)["semImagem"]["Q990400001"]
    assert neg["motivo"].startswith("download-falhou:HTTP 429") and "Retry-After 30" in neg["motivo"]
    assert capas._recente(neg)                                                                       # recém-registrado: não consulta de novo no mesmo instante
    neg["consultadoEm"] = "2000-01-01T00:00:00+00:00"                                                # falha de download envelhece em 1 dia, não em 14
    assert not capas._recente(neg)
    meio = dict(neg, consultadoEm=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())
    assert not capas._recente(meio) and capas._recente(dict(meio, motivo="sem-candidato", versao=capas.IMPORTADOR_VERSAO))


def test_http_429_tenta_uma_vez_e_erros_tem_causa_legivel(monkeypatch):
    import io
    import urllib.error
    chamadas = []

    class Resp:
        def __init__(self, b): self.b = io.BytesIO(b)
        def read(self, n): return self.b.read(n)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def abre(req, timeout):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "2"}, None)
        return Resp(b"ok")
    monkeypatch.setattr(capas, "_ABRIR", abre)
    esperas = []
    assert capas._http("https://upload.wikimedia.org/x.png", "ua", 100, dormir=esperas.append) == b"ok" and esperas == [2] and len(chamadas) == 2

    def sempre403(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    monkeypatch.setattr(capas, "_ABRIR", sempre403)
    with pytest.raises(capas.ErroHttp) as e:
        capas._http("https://upload.wikimedia.org/x.png", "ua", 100)
    assert e.value.codigo == 403 and e.value.descricao() == "HTTP 403 Forbidden"

    def sem_rede(req, timeout):
        raise urllib.error.URLError(OSError("sem rota"))
    monkeypatch.setattr(capas, "_ABRIR", sem_rede)
    with pytest.raises(capas.ErroHttp) as e:
        capas._http("https://upload.wikimedia.org/x.png", "ua", 100)
    assert e.value.codigo == 0 and e.value.descricao().startswith("rede:")


def test_negativos_de_versao_antiga_sao_reavaliados_sem_tocar_nas_imagens_validas(tmp_path):
    d = str(tmp_path / "c")
    capas.importar([("Q990500001", "Bom", None, "")], fetch_multi(p18={"Q990500001": "B.png"}, commons={"File:B.png": pagina("File:B.png")}), d, pausa=0)
    antes = (Path(d) / "Q990500001.png").read_bytes()
    idx = capas.carregar_indice(d)
    idx["semImagem"]["Q990500002"] = {"motivo": "sem-P18", "consultadoEm": capas.agora()}          # formato antigo: sem 'versao'
    capas.salvar_indice(idx, d)
    lista = [("Q990500001", "Bom", None, ""), ("Q990500002", "Novo", None, "")]
    consultas = []
    base = fetch_multi(p18={"Q990500002": "N.png"}, commons={"File:N.png": pagina("File:N.png")})
    est = capas.importar(lista, lambda u, m: (consultas.append(u), base(u, m))[1], d, pausa=0)
    assert est["jaTinham"] == 1 and est["comImagem"] == 1 and capas.carregar_indice(d)["capas"]["Q990500002"]["provedor"] == "wikidata-p18"
    assert (Path(d) / "Q990500001.png").read_bytes() == antes and not any("Q990500001" in u for u in consultas)       # válida: intacta e não reconsultada
    # --reavaliar refaz negativos recentes (versão atual) sem tocar nas imagens
    idx = capas.carregar_indice(d)
    idx["semImagem"]["Q990500003"] = {"motivo": "sem-candidato", "consultadoEm": capas.agora(), "versao": capas.IMPORTADOR_VERSAO}
    capas.salvar_indice(idx, d)
    lista = [("Q990500003", "Tres", None, "")]
    assert capas.importar(lista, fetch_multi(), d, pausa=0)["jaTinham"] == 1
    assert capas.importar(lista, fetch_multi(), d, pausa=0, reavaliar=True)["jaTinham"] == 0


def test_diagnostico_mostra_causa_por_jogo_sem_gravar(tmp_path, capsys):
    idx = {"schema": "ps4store.indice/v1", "fontes": {}, "titulos": [{"nome": "Jogo Diag", "idFonte": "wikidata:Q990600001", "url": "", "fonte": "wikidata"}]}
    arq = tmp_path / "i.json"
    arq.write_text(json.dumps(idx))
    dados = str(tmp_path / "cx")
    f = fetch_multi(p18={"Q990600001": "D.png"}, commons={"File:D.png": pagina("File:D.png", lic="CC BY-NC 4.0")})
    rc = capas.main(["--diagnostico", "3", "--jogos", "jogo diag", "--indice", str(arq), "--versoes", SEMENTE, "--cusas", SEM_WD, "--dir", dados, "--pausa", "0"], fetch=f, dormir=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and "p18=1" in out and "rejeitada: licenca-nao-permitida" in out and "nada foi gravado" in out and not Path(dados).exists()


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


def test_thumb_wikimedia_permitido_e_hosts_continuam_restritos():
    ok = ["https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/330px-X.jpg", "https://upload.wikimedia.org/x.png", "https://en.wikipedia.org/w/api.php"]
    ruim = ["http://thumb.wikimedia.org/x.jpg", "https://thumb.wikimedia.org.evil.example/x.jpg", "https://evil.example/thumb.wikimedia.org", "https://wikimedia.org/x", "ftp://thumb.wikimedia.org/x"]
    assert all(capas._host_permitido(u) for u in ok) and not any(capas._host_permitido(u) for u in ruim)
    for u in ruim:
        with pytest.raises(ValueError):
            capas._http(u, "ua", 10)


def test_redirecionamento_so_dentro_dos_dominios_autorizados():
    import urllib.request
    h = capas._RedirecionamentoRestrito()
    req = urllib.request.Request("https://upload.wikimedia.org/a.png")
    assert h.redirect_request(req, None, 302, "Found", {}, "https://thumb.wikimedia.org/b.png").full_url == "https://thumb.wikimedia.org/b.png"
    assert h.redirect_request(req, None, 302, "Found", {}, "/c.png").full_url == "https://upload.wikimedia.org/c.png"
    for destino in ("https://evil.example/x.png", "http://upload.wikimedia.org/x.png", "https://upload.wikimedia.org.evil.example/x.png"):
        with pytest.raises(ValueError):
            h.redirect_request(req, None, 302, "Found", {}, destino)


def test_negativo_causado_pelo_bloqueio_de_host_e_reavaliado_na_hora_e_imagem_valida_fica(tmp_path):
    d = str(tmp_path / "c")
    capas.importar([("Q990700001", "Bom", None, "")], fetch_multi(p18={"Q990700001": "B.png"}, commons={"File:B.png": pagina("File:B.png")}), d, pausa=0)
    antes = (Path(d) / "Q990700001.png").read_bytes()
    idx = capas.carregar_indice(d)
    idx["semImagem"]["Q990700002"] = {"motivo": "download-falhou:ValueError: host não permitido: thumb.wikimedia.org", "consultadoEm": capas.agora(), "versao": capas.IMPORTADOR_VERSAO}
    capas.salvar_indice(idx, d)
    assert not capas._recente(idx["semImagem"]["Q990700002"])
    est = capas.importar([("Q990700001", "Bom", None, ""), ("Q990700002", "Outro", None, "")],
                         fetch_multi(p18={"Q990700002": "O.png"}, commons={"File:O.png": pagina("File:O.png")}), d, pausa=0)
    assert est["jaTinham"] == 1 and est["comImagem"] == 1 and (Path(d) / "Q990700001.png").read_bytes() == antes
