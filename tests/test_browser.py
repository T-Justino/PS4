"""PoC de navegador: páginas próprias com JavaScript num servidor local. Pula sozinho se o Playwright/Chromium não existir."""
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright.sync_api")

from ps4store.browser import ENCONTRADAS, INTERACAO, NAO_PERMITIDO, SEM_URLS, explore, pipeline  # noqa: E402
from ps4store.resolver import ResolverNet  # noqa: E402

PKG = b"\x7fCNT" + b"\0" * 300_000
RAR = b"Rar!\x1a\x07\x01\x00" + b"\0" * 50_000
HITS: Counter = Counter()

PAGES = {
    "/dyn/js": '<div id=o></div><script>setTimeout(()=>{o.innerHTML=\'<a href="/a.pkg">Download PKG</a>\'},300)</script>',
    "/dyn/button": '<button onclick="show()">Gerar link</button><div id=o></div><script>function show(){o.innerHTML=\'<a href="/r/x.part03.rar">p3</a>'
                   '<a href="/r/x.part01.rar">p1</a><a href="/r/x.part02.rar">p2</a>\'}</script>',
    "/dyn/redirect": "<script>setTimeout(()=>location.replace('/dyn/final'),200)</script>",
    "/dyn/final": '<a href="/a.pkg">Download</a>',
    "/dyn/meta": '<meta http-equiv="refresh" content="0; url=/a.pkg">',
    "/dyn/popup": '<button onclick="window.open(\'/dyn/popup-target\')">Download</button>'
                  '<button onclick="window.open(\'{alt}/ad\')">Baixar mirror alternativo</button>',
    "/dyn/popup-target": '<a href="/a.pkg">Download PKG</a>',
    "/dyn/dl": "<button onclick=\"location='/big.pkg'\">Baixar</button>",
    "/dyn/ads": '<a class="ad-banner" href="/ad-click" target="_blank">Download now! Baixar grátis</a>'
                '<div class="sponsored"><button onclick="location=\'/ad-click\'">Baixar agora</button></div>'
                '<a rel="sponsored" href="{alt}/ad">Download VIP</a>'
                '<button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<a href=&quot;/a.pkg&quot;>Download PKG</a>\')">Baixar jogo</button>',
    "/dyn/captcha": '<div class="g-recaptcha" data-sitekey="x"></div><a href="/a.pkg">Download</a>',
    "/dyn/login": '<form><input type="password" name="p"></form><a href="/a.pkg">Download</a>',
    "/dyn/vazia": "<p>nada</p>",
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        HITS[p] += 1
        port = self.server.server_port
        if p in PAGES:
            data, ct, extra = ("<html><body>" + PAGES[p].replace("{alt}", f"http://localhost:{port}") + "</body></html>").encode(), "text/html", {}
        elif p == "/a.pkg":
            data, ct, extra = PKG, "application/octet-stream", {}
        elif p == "/big.pkg":
            data, ct, extra = PKG, "application/octet-stream", {"Content-Disposition": 'attachment; filename="big.pkg"'}
        elif p.startswith("/r/") and p.endswith(".rar"):
            data, ct, extra = RAR, "application/octet-stream", {}
        else:
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng and ct != "text/html":
            a, b = rng[6:].split("-")
            a, b = int(a), min(int(b), len(data) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
            data = data[a:b + 1]
        else:
            self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def srv():
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


@pytest.fixture(scope="module", autouse=True)
def _chromium(srv):
    try:
        explore(srv + "/dyn/vazia", {"127.0.0.1"})
    except Exception as e:                                # navegador indisponível neste ambiente
        pytest.skip(f"Chromium indisponível: {str(e)[:80]}")


@pytest.fixture(autouse=True)
def _reset():
    HITS.clear()


HOSTS = {"127.0.0.1"}
NET = ResolverNet(allow_insecure=True, timeout=5)


def urls(r):
    return [f.url.rsplit("/", 1)[-1] for f in r.found]


def test_link_criado_por_javascript_depois_do_carregamento(srv):
    r = explore(srv + "/dyn/js", HOSTS)
    assert r.status == ENCONTRADAS and urls(r) == ["a.pkg"] and r.found[0].via == "dom"


def test_botao_revela_volumes_rar_e_o_resolvedor_organiza_em_ordem(srv):
    out = pipeline(srv + "/dyn/button", HOSTS, NET)
    assert out["browser"].status == ENCONTRADAS and any("clique" in s["step"] for s in out["browser"].steps)
    g = out["sets"][0]
    assert g["complete"] and g["volumes"] == 3 and [u.rsplit("part", 1)[1] for u in g["sspiOrder"]] == ["01.rar", "02.rar", "03.rar"]


def test_redirecionamento_por_javascript_e_acompanhado(srv):
    r = explore(srv + "/dyn/redirect", HOSTS)
    assert r.status == ENCONTRADAS and urls(r) == ["a.pkg"] and any("redirecionamento" in s["step"] for s in r.steps)


def test_meta_refresh_para_arquivo_vira_download_interceptado_sem_baixar(srv):
    r = explore(srv + "/dyn/meta", HOSTS)
    assert r.status == ENCONTRADAS and "a.pkg" in urls(r)


def test_nova_aba_permitida_e_lida_e_aba_de_outro_host_e_fechada(srv):
    r = explore(srv + "/dyn/popup", HOSTS)
    assert "a.pkg" in urls(r) and any("nova aba aberta" in s["step"] for s in r.steps)
    assert any("host não permitido" in b["reason"] for b in r.blocked) and HITS["/ad"] == 0


def test_download_por_clique_e_cancelado_so_a_url_e_registrada(srv):
    r = explore(srv + "/dyn/dl", HOSTS)
    assert r.status == ENCONTRADAS and r.found[0].via == "download" and r.found[0].url.endswith("/big.pkg")
    assert any("cancelado" in s["detail"] for s in r.steps)


def test_anuncios_nao_sao_clicados_e_a_acao_legitima_funciona(srv):
    r = explore(srv + "/dyn/ads", HOSTS)
    assert HITS["/ad-click"] == 0 and HITS["/ad"] == 0
    assert urls(r) == ["a.pkg"] and any("anúncio" in b["reason"] or "host não permitido" in b["reason"] for b in r.blocked)


def test_captcha_para_e_pede_intervencao_sem_tocar_na_pagina(srv):
    r = explore(srv + "/dyn/captcha", HOSTS)
    assert r.status == INTERACAO and "CAPTCHA" in r.explanation and not r.found
    assert any(s["outcome"] == "intervencao" for s in r.steps)


def test_login_para_e_pede_intervencao(srv):
    r = explore(srv + "/dyn/login", HOSTS)
    assert r.status == INTERACAO and "login" in r.explanation and not r.found


def test_modo_assistido_retoma_depois_que_a_pessoa_resolve(srv):
    def pessoa(page, why):                                  # simula a ação humana na janela (remove o desafio); a automação não o resolve
        page.evaluate("document.querySelector('.g-recaptcha').remove()")
        return True
    r = explore(srv + "/dyn/captcha", HOSTS, assistido=pessoa)
    assert r.status == ENCONTRADAS and urls(r) == ["a.pkg"] and any("resolvida pela pessoa" in s["step"] for s in r.steps)
    nao = explore(srv + "/dyn/captcha", HOSTS, assistido=lambda p, w: False)
    assert nao.status == INTERACAO and not nao.found


def test_host_de_entrada_nao_permitido_e_pagina_vazia(srv):
    assert explore(srv.replace("127.0.0.1", "localhost") + "/dyn/js", HOSTS).status == NAO_PERMITIDO
    assert explore(srv + "/dyn/vazia", HOSTS).status == SEM_URLS


def test_pipeline_completo_pagina_dinamica_navegador_resolvedor(srv):
    out = pipeline(srv + "/dyn/popup", HOSTS, NET)
    f = out["files"][0]
    assert f.filename == "a.pkg" and f.format == "pkg" and f.sspiSendable and f.sizeBytes == len(PKG)
