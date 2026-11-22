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
    s = painel.criar_servidor(0, faz_indice(tmp_path), SEMENTE)
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
    s = painel.criar_servidor(0, idx, SEMENTE)
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
    assert srv.get("/api/jogos?q=zelda")[2] == {"total": 0, "mostrando": 0, "itens": [], "aviso": ""}
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
    s = painel.criar_servidor(0, idx, SEMENTE)
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
    s = painel.criar_servidor(0, str(tmp_path / "nao-existe.json"), SEMENTE)
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
    s = painel.criar_servidor(0, idx, SEMENTE)
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
    pg.locator("#estado").filter(has_text="jogos no índice").wait_for(timeout=8000)
    assert "5 jogos no índice · 3 registro(s)" in pg.inner_text("#estado")
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
    s = painel.criar_servidor(0, faz_indice(tmp_path, itens), SEMENTE)
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
