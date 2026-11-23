"""Painel web local: servidor (segurança, validação, leitura) e interface (Chromium, se houver Playwright). Dados de busca simulados (Q-ids 99070xxxx)."""
import http.client
import json
import re
import threading
import urllib.parse
from pathlib import Path

import pytest

from ps4store import busca, painel, versoes

ROOT = Path(__file__).resolve().parents[1]
SEMENTE = str(ROOT / "data" / "versoes-cusa.json")
FONTES = str(ROOT / "config" / "busca-fontes.json")
SEM_WD = "/nao/existe/cusas-wikidata.json"        # os testes não podem depender de local/ do usuário


def faz_indice(tmp_path, itens=None):
    d = busca.indice_vazio()
    itens = itens if itens is not None else [
        {"nome": "Batman: Arkham Knight", "url": "https://en.wikipedia.org/wiki/Batman:_Arkham_Knight", "idFonte": "wikidata:Q15891648", "lancamento": "2015"},
        {"nome": "Batman: Arkham VR", "url": "https://www.wikidata.org/wiki/Q990700002", "idFonte": "wikidata:Q990700002"},
        {"nome": "LEGO Batman 3: Beyond Gotham", "url": "https://www.wikidata.org/wiki/Q990700003", "idFonte": "wikidata:Q990700003"},
        {"nome": "Pokémon Café Mix", "url": "https://www.wikidata.org/wiki/Q990700004", "idFonte": "wikidata:Q990700004"},
        {"nome": "Sem Qid Jogo", "url": "https://exemplo.invalid/x", "idFonte": ""}]
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", itens)
    p = tmp_path / "idx.json"
    busca.salvar_indice(d, str(p))
    return str(p)


class Cli:
    def __init__(self, srv):
        self.srv = srv
        self.port = srv.server_address[1]

    def req(self, metodo, caminho, host=None, corpo=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest(metodo, caminho, skip_host=True)
        c.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
        if corpo is not None:
            c.putheader("Content-Length", str(len(corpo)))
        c.endheaders(corpo)
        r = c.getresponse()
        dados = r.read()
        h = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, h, dados

    def get(self, caminho, **kw):
        s, h, d = self.req("GET", caminho, **kw)
        try:
            return s, h, json.loads(d)
        except ValueError:
            return s, h, d.decode("utf-8", "replace")


@pytest.fixture
def srv(tmp_path):
    s = painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE, arq_cusas=SEM_WD, dir_capas=str(tmp_path / "capas-vazio"), arq_apelidos=str(ROOT / "data" / "apelidos.json"), arq_metadados="/nao/existe/meta.json")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield Cli(s)
    s.shutdown()
    s.server_close()


# ---------- rede: só 127.0.0.1, só leitura ----------
def test_escuta_somente_em_127_0_0_1_e_recusa_outro_endereco(srv, tmp_path):
    assert srv.srv.server_address[0] == "127.0.0.1"
    for h in ("0.0.0.0", "::", "192.168.0.10", "localhost"):
        with pytest.raises(ValueError, match="127.0.0.1"):
            painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE, host=h)
    assert "--host" not in (ROOT / "src" / "ps4store" / "painel.py").read_text(encoding="utf-8").split("def main")[1].split("a = ap.parse_args")[0]
    with pytest.raises(ValueError, match="porta"):
        painel.criar_servidor(80, faz_indice(tmp_path), SEMENTE)


def test_host_header_estranho_e_rejeitado_contra_dns_rebinding(srv):
    for host in ("evil.example", "evil.example:%d" % srv.port, "192.168.0.10:%d" % srv.port, "127.0.0.1:1", ""):
        assert srv.req("GET", "/api/estado", host=host)[0] == 403
    assert srv.req("GET", "/api/estado", host=f"localhost:{srv.port}")[0] == 200


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_somente_leitura_metodos_de_escrita_sao_recusados(srv, metodo):
    s, h, _ = srv.req(metodo, "/api/jogos?q=batman", corpo=b"x=1")
    assert s == 405 and h["allow"] == "GET, HEAD"


def test_nao_escreve_em_disco_e_dados_nao_mudam(tmp_path):
    idx = faz_indice(tmp_path)
    antes = (Path(idx).read_bytes(), Path(SEMENTE).read_bytes())
    s = painel.criar_servidor(0, idx, SEMENTE, arq_cusas=SEM_WD)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    for p in ("/", "/api/estado", "/api/jogos?q=batman", "/api/jogo?qid=Q15891648"):
        c.get(p)
    s.shutdown()
    s.server_close()
    assert (Path(idx).read_bytes(), Path(SEMENTE).read_bytes()) == antes
    assert not list(tmp_path.glob("*.tmp"))


# ---------- sem navegar em arquivos / sem executar comandos ----------
@pytest.mark.parametrize("caminho", ["/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/app.js/../../../etc/passwd", "/index.html", "/src/ps4store/painel.py",
                                     "/painel_assets/app.js", "/config/busca-fontes.json", "//etc/passwd", "/api", "/api/", "/api/jogos/../../x", "/estilo.css/x"])
def test_caminhos_fora_das_rotas_fixas_dao_404_sem_vazar_arquivos(srv, caminho):
    s, h, corpo = srv.get(caminho)
    assert s == 404 and "root:" not in json.dumps(corpo) and "def " not in json.dumps(corpo)


def test_consulta_com_metacaracteres_de_shell_nao_executa_nada(srv, tmp_path):
    marcador = tmp_path / "PWNED"
    for q in ("$(touch %s)" % marcador, "`touch %s`" % marcador, "; touch %s" % marcador, "batman' OR '1'='1", "<script>alert(1)</script>"):
        s, h, j = srv.get("/api/jogos?q=" + urllib.parse.quote(q))
        assert s == 200 and j["total"] == 0 and h["content-type"].startswith("application/json")
    assert not marcador.exists()


# ---------- validação de parâmetros ----------
@pytest.mark.parametrize("caminho", [
    "/api/jogos", "/api/jogos?q=", "/api/jogos?q=" + "a" * 101, "/api/jogos?q=a%00b", "/api/jogos?q=a%0Ab", "/api/jogos?q=ba&limite=0", "/api/jogos?q=ba&limite=201",
    "/api/jogos?q=ba&limite=abc", "/api/jogos?q=ba&limite=-1", "/api/jogos?q=ba&com_versoes=2", "/api/jogos?q=ba&q=bat", "/api/jogos?q=ba&extra=1", "/api/jogos?q=%ff%fe",
    "/api/jogo", "/api/jogo?qid=15891648", "/api/jogo?qid=Q1;DROP", "/api/jogo?qid=q15891648", "/api/jogo?qid=Q" + "9" * 13,
    "/api/jogo?qid=Q15891648&cusa=123", "/api/jogo?qid=Q15891648&cusa=UP1018-CUSA00133_00-B000000000001563", "/api/jogo?qid=Q15891648&regiao=../x",
    "/api/jogo?qid=Q15891648&regiao=TOOLONGX", "/api/jogo?qid=Q15891648&idioma=" + "x" * 31, "/api/jogo?qid=Q15891648&idioma=%3Cb%3E", "/api/jogo?qid=Q15891648&x=1",
    "/api/estado?x=1", "/?x=1", "/app.js?x=1"])
def test_parametros_invalidos_dao_400_com_mensagem(srv, caminho):
    s, h, j = srv.get(caminho)
    assert s == 400 and "erro" in (j if isinstance(j, dict) else {"erro": ""})


def test_head_e_get_so_com_parametros_validos(srv):
    s, h, d = srv.req("HEAD", "/api/estado")
    assert s == 200 and d == b"" and int(h["content-length"]) > 0
    assert srv.get("/api/jogos?q=batman&limite=1")[0] == 200


# ---------- dados: busca e versões ----------
def test_busca_por_nome_sem_acentos_com_ano_fonte_e_contagem_de_versoes(srv):
    s, h, j = srv.get("/api/jogos?q=BATMAN")
    assert s == 200 and j["total"] == 3
    ak = next(i for i in j["itens"] if i["qid"] == "Q15891648")
    assert ak["nome"] == "Batman: Arkham Knight" and ak["ano"] == "2015" and ak["fonte"] == "wikidata" and ak["fonteNome"].startswith("Wikidata") and ak["nRegistros"] == 3 and ak["nCusas"] == 2
    vr = next(i for i in j["itens"] if i["qid"] == "Q990700002")
    assert vr["nRegistros"] == 0 and vr["ano"] is None
    assert srv.get("/api/jogos?q=pokemon")[2]["itens"][0]["nome"] == "Pokémon Café Mix"
    assert srv.get("/api/jogos?q=zelda")[2] == {"total": 0, "mostrando": 0, "offset": 0, "temMais": False, "itens": [], "aviso": "", "tipoBusca": "nome", "sugestoes": [], "viaApelido": False}
    j2 = srv.get("/api/jogos?q=sem+qid")[2]
    assert j2["itens"][0]["qid"] is None and j2["itens"][0]["nRegistros"] == 0                           # sem Q-id: sem vínculo


def test_limite_e_so_com_versoes(srv):
    assert srv.get("/api/jogos?q=batman&limite=2")[2]["mostrando"] == 2
    j = srv.get("/api/jogos?com_versoes=1")[2]
    assert [i["nome"] for i in j["itens"]] == ["Batman: Arkham Knight"]
    assert srv.get("/api/jogos?q=lego&com_versoes=1")[2]["total"] == 0


def test_versoes_do_qid_todos_os_registros_sem_filtros(srv):
    s, _, j = srv.get("/api/jogo?qid=Q15891648")
    assert s == 200 and j["total"] == 3 and j["cusasDistintos"] == 2 and len(j["registros"]) == 3 and j["omitidos"] == 0
    assert j["jogo"]["nome"] == "Batman: Arkham Knight" and j["jogo"]["ano"] == "2015" and j["jogo"]["url"].startswith("https://en.wikipedia.org/")
    assert j["temJogoBase"] is False and j["avisos"] == [] and j["filtros"] == {"cusa": "", "regiao": "", "idioma": ""}


def test_filtros_opcionais_cusa_regiao_idioma(srv):
    eu = srv.get("/api/jogo?qid=Q15891648&regiao=EU")[2]
    assert [r["cusa"] for r in eu["registros"]] == ["CUSA00135"] and eu["omitidos"] == 1 and eu["total"] == 3
    assert [r["contentId"] for r in srv.get("/api/jogo?qid=Q15891648&cusa=cusa00133")[2]["registros"]] == ["UP1018-CUSA00133_00-B000000000001563", "UP1018-CUSA00133_00-ASIA000000000003"]
    ko = srv.get("/api/jogo?qid=Q15891648&idioma=Korean")[2]
    assert len(ko["registros"]) == 1 and ko["registros"][0]["idiomas"] == ["English", "Korean"]
    vazio = srv.get("/api/jogo?qid=Q15891648&regiao=US&idioma=English")[2]                             # região conhecida não implica idioma
    assert vazio["registros"] == [] and vazio["omitidos"] >= 1


def test_desconhecido_continua_desconhecido_e_status_citado_nada_inventado(srv):
    regs = srv.get("/api/jogo?qid=Q15891648")[2]["registros"]
    for r in regs:
        assert r["status"] == "citado" and r["versao"] is None and r.get("escopo") is None
    asia = next(r for r in regs if "ASIA" in r["contentId"])
    us = next(r for r in regs if r["contentId"].startswith("UP1018-CUSA00133_00-B"))
    assert asia["regiao"] is None and us["idiomas"] is None and us["regiao"]["codigo"] == "US"


def test_jogo_sem_versoes_e_jogo_inexistente(srv):
    s, _, j = srv.get("/api/jogo?qid=Q990700003")
    assert s == 200 and j["total"] == 0 and j["registros"] == [] and j["jogo"]["nome"] == "LEGO Batman 3: Beyond Gotham"
    s, _, j = srv.get("/api/jogo?qid=Q999999999")
    assert s == 404 and "não encontrado" in j["erro"]


def test_nome_igual_com_outro_qid_nao_herda_versoes(tmp_path):
    idx = faz_indice(tmp_path, [{"nome": "Batman: Arkham Knight", "url": "https://x.invalid/a", "idFonte": "wikidata:Q990700099"}])
    s = painel.criar_servidor(0, idx, SEMENTE, arq_cusas=SEM_WD)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    j = c.get("/api/jogos?q=arkham")[2]
    assert j["itens"][0]["qid"] == "Q990700099" and j["itens"][0]["nRegistros"] == 0
    assert c.get("/api/jogo?qid=Q990700099")[2]["total"] == 0
    # e o Q-id da semente, ausente deste índice, é sinalizado em vez de aceito em silêncio
    assert any("NÃO existe no índice local" in a for a in c.get("/api/jogo?qid=Q15891648")[2]["avisos"])
    s.shutdown()
    s.server_close()


def test_indice_ausente_usa_so_rotulos_das_versoes_e_avisa(tmp_path):
    s = painel.criar_servidor(0, str(tmp_path / "nao-existe.json"), SEMENTE, arq_cusas=SEM_WD)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    j = c.get("/api/jogos?q=arkham")[2]
    assert j["total"] == 1 and j["aviso"].startswith("índice de busca vazio") and j["itens"][0]["qid"] == "Q15891648"
    assert any("Índice de busca ausente" in a for a in c.get("/api/jogo?qid=Q15891648")[2]["avisos"])
    assert c.get("/api/estado")[2]["jogosNoIndice"] == 0
    s.shutdown()
    s.server_close()


def test_dados_atualizados_no_disco_sao_vistos_sem_reiniciar(tmp_path):
    idx = faz_indice(tmp_path)
    s = painel.criar_servidor(0, idx, SEMENTE, arq_cusas=SEM_WD)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    assert c.get("/api/jogos?q=zelda")[2]["total"] == 0
    busca.salvar_indice(busca.indice_vazio(), idx)
    d = busca.carregar_indice(idx)
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", [{"nome": "Zelda Simulado", "url": "https://x.invalid/z", "idFonte": "wikidata:Q990700500"}])
    import os
    busca.salvar_indice(d, idx)
    os.utime(idx, (1, 1_900_000_000))                                                                  # garante mtime diferente
    assert c.get("/api/jogos?q=zelda")[2]["total"] == 1
    s.shutdown()
    s.server_close()


def test_nao_sobe_com_arquivo_de_versoes_invalido(tmp_path):
    ruim = tmp_path / "v.json"
    ruim.write_text(json.dumps({"schema": versoes.SCHEMA, "versoes": [{"qid": "x", "cusa": "CUSA1"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="problema"):
        painel.criar_servidor(0, faz_indice(tmp_path), str(ruim))
    assert painel.main(["--porta", "80"]) == 2


def test_porta_ocupada_da_erro_claro(srv, capsys):
    assert painel.main(["--porta", str(srv.port), "--indice", "/nao/existe.json"]) == 2
    assert "porta" in capsys.readouterr().err


# ---------- página e ativos: nada externo, sem inline, sem innerHTML ----------
def test_pagina_e_ativos_com_csp_e_sem_conteudo_externo(srv):
    s, h, html = srv.get("/")
    assert s == 200 and h["content-type"].startswith("text/html") and "viewport" in html and 'id="q"' in html and 'id="f-cusa"' in html and 'id="f-regiao"' in html and 'id="f-idioma"' in html
    csp = h["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store" and h["referrer-policy"] == "no-referrer"
    assert not re.search(r"""(src|href|action)=["']https?://""", html) and "<script>" not in html and "onclick=" not in html
    for rota, tipo in (("/estilo.css", "text/css"), ("/app.js", "application/javascript")):
        s, h, corpo = srv.get(rota)
        assert s == 200 and h["content-type"].startswith(tipo) and "@import" not in corpo and "url(http" not in corpo
    js = srv.get("/app.js")[2]
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js and "textContent" in js
    for texto in ("não é o CUSA", "NÃO é o CUSA", "desconhecid", "CITADO", "CONFIRMADO", "sem versões cadastradas", "jogo-base", "Nada foi inventado"):
        assert texto.lower() in js.lower(), texto


# ---------- interface no navegador (Chromium; pula se não houver) ----------
@pytest.fixture(scope="module")
def navegador():
    pw = pytest.importorskip("playwright.sync_api")
    ctx = pw.sync_playwright().start()
    try:
        b = ctx.chromium.launch()
    except Exception as e:
        ctx.stop()
        pytest.skip(f"Chromium indisponível: {str(e)[:60]}")
    yield b
    b.close()
    ctx.stop()


def test_interface_fluxo_completo_no_celular(navegador, srv, tmp_path):
    pg = navegador.new_page(viewport={"width": 390, "height": 844})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pedidos = []
    pg.on("request", lambda r: pedidos.append(r.url))
    pg.goto(f"http://127.0.0.1:{srv.port}/")
    pg.locator("#estado li b").first.wait_for(timeout=8000)
    cab = pg.locator("#estado li").all_inner_texts()
    assert [c.replace("\n", " ") for c in cab] == ["5 Jogos pesquisáveis", "1 Jogos com CUSA", "2 CUSAs distintos", "3 Registros manuais", "0 Conflitos pendentes"]
    pg.fill("#q", "BATMAN")
    pg.click("button.primario")
    pg.wait_for_selector("#lista li")
    cards = pg.locator("#lista li").all_inner_texts()
    assert len(cards) == 3 and "Batman: Arkham Knight (2015)" in cards[0] and "Wikidata" in cards[0] and "3 registro(s) · 2 CUSA(s)" in cards[0]
    assert any("sem versões cadastradas" in c for c in cards)
    pg.screenshot(path=str(tmp_path / "lista.png"))
    pg.locator("#lista li").first.click()
    pg.wait_for_selector("#jogo .card")
    texto = pg.inner_text("#jogo")
    assert texto.count("CUSA: identificador do título") == 3 and texto.count("identifica este produto/edição; NÃO é o CUSA") == 3
    assert "CUSA00133" in texto and "CUSA00135" in texto and texto.count("CITADO: fonte vista, página não conferida") == 3
    assert "desconhecido" in texto and "desconhecidos (a região não define o idioma)" in texto and "English, Korean" in texto
    assert "Nenhum registro está marcado como jogo-base" in texto and "Premium Edition" in texto
    pg.screenshot(path=str(tmp_path / "jogo.png"), full_page=True)
    pg.click("#filtros summary")                                                                       # os filtros ficam recolhidos até o usuário abrir
    pg.select_option("#f-regiao", "EU")
    pg.locator("#jogo").filter(has_text="filtros: regiao=EU").wait_for(timeout=8000)
    t2 = pg.inner_text("#jogo")
    assert t2.count("CUSA: identificador do título") == 1 and "CUSA00135" in t2 and "ficaram de fora" in t2
    pg.fill("#f-idioma", "Korean")
    pg.dispatch_event("#f-idioma", "change")
    pg.locator("#jogo").filter(has_text="Nenhum registro passa nos filtros").wait_for(timeout=8000)
    pg.select_option("#f-regiao", "")
    pg.fill("#f-idioma", "")
    pg.dispatch_event("#f-idioma", "change")
    pg.locator("#jogo").filter(has_text="filtros: nenhum").wait_for(timeout=8000)
    assert pg.inner_text("#jogo").count("CUSA: identificador do título") == 3
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")                  # sem rolagem lateral no celular
    pg.click("#voltar")
    pg.locator("#lista li").nth(1).click()
    pg.wait_for_selector("#jogo .card")
    assert "Nenhuma versão CUSA cadastrada para Q990700002" in pg.inner_text("#jogo") and "Nada foi inventado" in pg.inner_text("#jogo")
    assert erros == [] and all(u.startswith(f"http://127.0.0.1:{srv.port}/") for u in pedidos)         # nenhuma requisição externa
    pg.close()


def test_interface_nome_malicioso_e_exibido_como_texto_e_so_links_https(navegador, tmp_path):
    itens = [{"nome": "<img src=x onerror=window.__xss=1> Batman", "url": "https://exemplo.invalid/x", "idFonte": "wikidata:Q990700777"}]
    s = painel.criar_servidor(0, faz_indice(tmp_path, itens), SEMENTE, arq_cusas=SEM_WD)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    pg = navegador.new_page()
    pg.goto(f"http://127.0.0.1:{s.server_address[1]}/")
    pg.fill("#q", "batman")
    pg.click("button.primario")
    pg.wait_for_selector("#lista li")
    assert pg.evaluate("window.__xss") is None and "<img src=x" in pg.inner_text("#lista")
    pg.locator("#lista li").first.click()
    pg.wait_for_selector("#jogo h2")
    assert pg.locator("#jogo a[href^='javascript']").count() == 0 and "<img src=x" in pg.inner_text("#jogo")
    pg.close()
    s.shutdown()
    s.server_close()


# ---------- CUSAs do Wikidata no painel: pesquisa unificada (nome, CUSA, Content ID) ----------
def faz_wd(tmp_path):
    from ps4store import cusas
    idx = busca.indice_vazio()
    jogos = [("Q15891648", "Batman: Arkham Knight"), ("Q990900001", "Grand Theft Auto V"), ("Q990900002", "Cyberpunk 2077"), ("Q990900006", "Conflito A"),
             ("Q990900007", "Conflito B")]
    busca.importar(idx, busca.carregar_fontes(FONTES), "wikidata", [{"nome": n, "url": f"https://www.wikidata.org/wiki/{q}", "idFonte": f"wikidata:{q}"} for q, n in jogos])
    cache = {"P5971": {"rotulo": "Europe PlayStation Store ID", "consultadoEm": "2026-11-23", "linhas": [
        ["Q15891648", "EP1018-CUSA00135_00-BAKPREMIUMED0000"], ["Q990900001", "CUSA90001"], ["Q990900002", "EP0000-CUSA90003_00-ABCDEFGHIJKLMNOP"],
        ["Q990900006", "CUSA90099"], ["Q990900007", "CUSA90099"]]}}
    doc = cusas.construir(cache, idx, versoes.carregar(SEMENTE), "2026-11-23")
    p = tmp_path / "cusas-wd.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    ip = tmp_path / "idx-wd.json"
    busca.salvar_indice(idx, str(ip))
    return str(ip), str(p)


@pytest.fixture
def srv_wd(tmp_path):
    ip, wd = faz_wd(tmp_path)
    s = painel.criar_servidor(0, ip, SEMENTE, arq_cusas=wd)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield Cli(s)
    s.shutdown()
    s.server_close()


def test_pesquisa_por_cusa_no_mesmo_campo_acha_o_jogo_do_wikidata(srv_wd):
    s, _, j = srv_wd.get("/api/jogos?q=cusa90001")
    assert s == 200 and j["tipoBusca"] == "cusa" and [i["nome"] for i in j["itens"]] == ["Grand Theft Auto V"] and j["itens"][0]["nWikidata"] == 1
    assert "CUSA90001 reconhecido como CUSA" in j["aviso"]
    j = srv_wd.get("/api/jogos?q=CUSA00133")[2]                                           # CUSA curado continua achando
    assert [i["qid"] for i in j["itens"]] == ["Q15891648"] and j["itens"][0]["nWikidata"] == 0


def test_pesquisa_por_content_id_completo_curado_ou_do_wikidata(srv_wd):
    j = srv_wd.get("/api/jogos?q=UP1018-CUSA00133_00-B000000000001563")[2]
    assert j["tipoBusca"] == "contentId" and [i["qid"] for i in j["itens"]] == ["Q15891648"] and "Content ID" in j["aviso"] and "CUSA00133" in j["aviso"]
    j = srv_wd.get("/api/jogos?q=ep0000-cusa90003_00-abcdefghijklmnop")[2]
    assert [i["nome"] for i in j["itens"]] == ["Cyberpunk 2077"]
    assert srv_wd.get("/api/jogos?q=UP1018-CUSA09999_00-ABCDEFGHIJKLMNOP")[2]["total"] == 0


def test_cusa_em_conflito_nao_associa_a_nenhum_jogo_e_avisa(srv_wd):
    j = srv_wd.get("/api/jogos?q=CUSA90099")[2]
    assert j["total"] == 0 and "CONFLITO" in j["aviso"]
    d = srv_wd.get("/api/jogo?qid=Q990900006")[2]
    assert d["total"] == 0 and d["avisos"] == ["1 CUSA(s) em conflito no Wikidata, NÃO associados a este jogo: CUSA90099."]
    assert d["conflitos"] == [{"cusa": "CUSA90099", "motivo": "mesmo CUSA em mais de um jogo", "outrosJogos": ["Conflito B"], "maisOutros": 0,
                              "classificacao": "nao-auditado", "rotulo": "não auditado"}]


def test_busca_por_nome_continua_livre_e_mostra_contagem_do_wikidata(srv_wd):
    j = srv_wd.get("/api/jogos?q=cyberpunk")[2]
    assert j["tipoBusca"] == "nome" and j["itens"][0]["nRegistros"] == 1 and j["itens"][0]["nWikidata"] == 1
    assert srv_wd.get("/api/jogos?q=batman")[2]["itens"][0]["nRegistros"] == 3                 # CUSA00135 do Wikidata já era curado: sem duplicata


def test_detalhe_do_wikidata_origem_status_e_desconhecidos(srv_wd):
    d = srv_wd.get("/api/jogo?qid=Q990900001")[2]
    assert d["total"] == 1 and d["origens"] == {"curado": 0, "wikidata": 1}
    r = d["registros"][0]
    assert r["origem"] == "wikidata" and r["status"] == "wikidata" and r["verificadoEmFonteOficial"] is False
    assert r["regiao"] is None and r["idiomas"] is None and r["edicao"] is None and r["versao"] is None and r["contentIds"] == []
    assert r["evidencias"][0]["url"] == "https://www.wikidata.org/wiki/Q990900001" and "P5971" in r["evidencias"][0]["fonte"] and r["evidencias"][0]["obtidoEm"] == "2026-11-23"
    assert srv_wd.get("/api/jogo?qid=Q990900001&regiao=EU")[2]["registros"] == []                # região desconhecida não casa com filtro
    assert srv_wd.get("/api/jogo?qid=Q990900001&regiao=EU")[2]["omitidos"] == 1
    assert [x["cusa"] for x in srv_wd.get("/api/jogo?qid=Q990900001&cusa=CUSA90001")[2]["registros"]] == ["CUSA90001"]
    c = srv_wd.get("/api/jogo?qid=Q990900002")[2]["registros"][0]
    assert c["contentIds"] == ["EP0000-CUSA90003_00-ABCDEFGHIJKLMNOP"] and c["contentId"] == c["contentIds"][0] and c["cusa"] == "CUSA90003"


def test_registro_curado_ganha_corroboracao_sem_perder_origem_nem_status(srv_wd):
    d = srv_wd.get("/api/jogo?qid=Q15891648")[2]
    assert d["total"] == 3 and d["origens"] == {"curado": 3, "wikidata": 0}
    eu = next(r for r in d["registros"] if r["cusa"] == "CUSA00135")
    assert eu["origem"] == "curado" and eu["status"] == "citado" and eu["corroboradoPorWikidata"][0]["fonte"].startswith("Wikidata (P5971")
    assert srv_wd.get("/api/estado")[2]["cusasWikidata"] == 3 and srv_wd.get("/api/estado")[2]["conflitosWikidata"] == 1


def test_interface_pesquisa_por_cusa_e_exibe_origem_wikidata(navegador, srv_wd):
    pg = navegador.new_page(viewport={"width": 390, "height": 844})
    pg.goto(f"http://127.0.0.1:{srv_wd.port}/")
    assert "Nome do jogo, CUSA ou Content ID" in pg.inner_text("#vista-lista")
    pg.fill("#q", "CUSA90001")
    pg.click("button.primario")
    pg.wait_for_selector("#lista li")
    assert "Grand Theft Auto V" in pg.inner_text("#lista") and "1 alegado(s) no Wikidata" in pg.inner_text("#lista") and "CUSA90001 reconhecido como CUSA" in pg.inner_text("#msg-lista")
    pg.locator("#lista li").first.click()
    pg.wait_for_selector("#jogo .card")
    t = pg.inner_text("#jogo")
    assert "WIKIDATA: alegado, NÃO verificado em fonte oficial" in t and "(1 curado(s), 0" not in t and "0 curado(s), 1 alegado(s) no Wikidata" in t
    assert "Edição\ndesconhecido" in t and "Região\ndesconhecido" in t and "desconhecidos (a região não define o idioma)" in t and "Versão do pacote (registro)\ndesconhecido" in t
    pg.click("#voltar")
    pg.fill("#q", "batman")
    pg.click("button.primario")
    pg.wait_for_selector("#lista li")
    pg.locator("#lista li").first.click()
    pg.wait_for_selector("#jogo .card")
    assert "Também no Wikidata" in pg.inner_text("#jogo") and "CITADO: fonte vista, página não conferida" in pg.inner_text("#jogo")
    pg.close()


# ---------- cabeçalho com contadores separados e avisos de conflito compactos ----------
def test_estado_separa_jogos_com_cusa_cusas_distintos_registros_manuais_e_conflitos(srv_wd, srv):
    e = srv_wd.get("/api/estado")[2]
    assert (e["jogosPesquisaveis"], e["jogosComCusa"], e["cusasDistintos"], e["registrosManuais"], e["registrosWikidata"], e["conflitosPendentes"]) == (5, 3, 4, 3, 3, 1)
    sem = srv.get("/api/estado")[2]                                                                  # só curados: 5 jogos no índice, 1 com CUSA, 2 CUSAs, 3 manuais, 0 conflitos
    assert (sem["jogosPesquisaveis"], sem["jogosComCusa"], sem["cusasDistintos"], sem["registrosManuais"], sem["conflitosPendentes"]) == (5, 1, 2, 3, 0)
    assert e["jogosNoIndice"] == 5 and e["registrosDeVersao"] == 3 and e["somenteLeitura"] is True      # chaves antigas preservadas


def faz_wd_com_muitos_conflitos(tmp_path, n=12):
    from ps4store import cusas
    idx = busca.indice_vazio()
    jogos = [("Q990910000", "Middle Aqui Principal")] + [(f"Q99092{k:04d}", f"Outro Jogo {k}") for k in range(n)]
    busca.importar(idx, busca.carregar_fontes(FONTES), "wikidata", [{"nome": nm, "url": f"https://www.wikidata.org/wiki/{q}", "idFonte": f"wikidata:{q}"} for q, nm in jogos])
    linhas = [["Q990910000", f"CUSA9{k:04d}"] for k in range(n)] + [[f"Q99092{k:04d}", f"CUSA9{k:04d}"] for k in range(n)]
    doc = cusas.construir({"P5971": {"rotulo": "x", "consultadoEm": "2026-11-23", "linhas": linhas}}, idx, versoes.carregar(SEMENTE), "2026-11-23")
    (tmp_path / "wd2.json").write_text(json.dumps(doc), encoding="utf-8")
    busca.salvar_indice(idx, str(tmp_path / "idx2.json"))
    return str(tmp_path / "idx2.json"), str(tmp_path / "wd2.json"), doc


def test_muitos_conflitos_geram_um_aviso_curto_e_lista_compacta_com_classificacao(tmp_path):
    from ps4store import auditoria
    ip, wd, doc = faz_wd_com_muitos_conflitos(tmp_path)
    aud = auditoria.auditar(doc, busca.carregar_indice(ip), versoes.carregar(SEMENTE))
    ap = tmp_path / "aud.json"
    ap.write_text(json.dumps(aud), encoding="utf-8")
    s = painel.criar_servidor(0, ip, SEMENTE, arq_cusas=wd, arq_auditoria=str(ap))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    c = Cli(s)
    d = c.get("/api/jogo?qid=Q990910000")[2]
    assert len(d["avisos"]) == 1 and len(d["avisos"][0]) < 160 and d["avisos"][0].startswith("12 CUSA(s) em conflito no Wikidata, NÃO associados a este jogo: CUSA90000, CUSA90001, CUSA90002, CUSA90003 (+8).")
    assert len(d["conflitos"]) == 12 and all(x["classificacao"] == "associacao-contraditoria" and x["rotulo"] == "associação contraditória" for x in d["conflitos"])
    assert all(len(x["outrosJogos"]) == 1 and x["maisOutros"] == 0 for x in d["conflitos"]) and d["registros"] == []
    s.shutdown()
    s.server_close()


def test_interface_mostra_conflitos_em_lista_recolhivel_e_cabecalho_novo(navegador, tmp_path):
    ip, wd, doc = faz_wd_com_muitos_conflitos(tmp_path)
    s = painel.criar_servidor(0, ip, SEMENTE, arq_cusas=wd, arq_auditoria=str(tmp_path / "sem-auditoria.json"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    pg = navegador.new_page(viewport={"width": 390, "height": 844})
    pg.goto(f"http://127.0.0.1:{s.server_address[1]}/")
    pg.locator("#estado li b").first.wait_for(timeout=8000)
    cab = [c.replace("\n", " ") for c in pg.locator("#estado li").all_inner_texts()]
    assert cab[0] == "13 Jogos pesquisáveis" and cab[1].endswith("Jogos com CUSA") and cab[3] == "3 Registros manuais" and cab[4] == "12 Conflitos pendentes"
    pg.fill("#q", "middle aqui")
    pg.click("button.primario")
    pg.wait_for_selector("#lista li")
    pg.locator("#lista li").first.click()
    pg.wait_for_selector("#jogo details.conflitos")
    assert not pg.locator("#jogo details.conflitos").get_attribute("open") and pg.locator("#jogo .aviso-box").count() >= 1
    pg.click("#jogo details.conflitos summary")
    txt = pg.inner_text("#jogo details.conflitos")
    assert "12 CUSA(s) em conflito (não associados a este jogo)" in txt and "… e mais 4" in txt and "não auditado" in txt and txt.count("CUSA9") == 8
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    pg.screenshot(path=str(tmp_path / "conflitos.png"), full_page=True)
    pg.close()
    s.shutdown()
    s.server_close()
