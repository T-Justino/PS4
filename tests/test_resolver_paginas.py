"""Resolvedor 4B: páginas intermediárias controladas (servidor local, arquivos próprios, nenhum download completo)."""
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ps4store.resolver import ARQUIVOS, INTERACAO, SEM_ARQUIVOS, ResolverNet, crawl, group_sets, main

PKG = b"\x7fCNT" + b"\0" * 50_000
RAR = b"Rar!\x1a\x07\x01\x00" + b"\0" * 50_000
HITS: Counter = Counter()


def page(*body):
    return "<html><body>" + "".join(body) + "</body></html>"


PAGES = {
    "/site/start": page(
        '<a href="/site/get/1">Baixar jogo (PKG)</a>',
        '<a href="/site/mirrors">Mirrors de download</a>',
        '<a href="/sobre">Sobre o site</a>',
        '<a href="https://externo.invalid/x.pkg">Download externo</a>',
        '<a href="javascript:void(0)" onclick="go()">Baixar agora</a>',
        '<a href="mailto:a@b.c">contato</a>',
        '<a href="/site/protegido">Download protegido</a>'),
    "/site/mirrors": page(
        '<a href="/r/x.part03.rar">part03</a>', '<a href="/r/x.part01.rar">part01</a>', '<a href="/r/x.part02.rar">part02</a>',
        '<a href="/site/start">Voltar ao download inicial</a>', '<a href="/r/x.part01.rar#dup">part01 de novo</a>'),
    "/site/protegido": page('<div class="g-recaptcha"></div>', '<a href="/a.pkg">baixar</a>'),
    "/site/botao": page('<form method="post" action="/x"><button>Gerar link</button></form>'),
    "/site/so-js": page('<a href="javascript:baixar()">Baixar</a>'),
    "/site/meta": '<html><head><meta http-equiv="refresh" content="0; url=/a.pkg"></head></html>',
    "/site/dir/rel": page('<a href="../../r/x.part02.rar">part02</a>', '<a href="./sub/download">Download sub</a>'),
    "/site/dir/sub/download": page('<a href="/a.pkg">PKG</a>'),
    "/site/p1": page('<a href="/site/p2">Download etapa 2</a>'),
    "/site/p2": page('<a href="/site/p3">Download etapa 3</a>'),
    "/site/p3": page('<a href="/a.pkg">PKG</a>'),
    "/site/flags": '<html><script>window.flags={"octocaptcha_origin_optimization":true}</script><body><a href="/a.pkg">Download PKG</a></body></html>',
    "/site/widget": '<html><script src="https://www.google.com/recaptcha/api.js"></script><body><a href="/a.pkg">Download</a></body></html>',
    "/site/so-login": page('<a href="/login?return_to=%2Fr%2Fx.part01.rar">Entrar para baixar</a>'),
    "/site/mista": page('<a href="/login?return_to=%2Fr%2Fx.part01.rar">Entrar</a>', '<a href="/a.pkg">PKG livre</a>'),
    "/site/spa": '<!doctype html><html><head><script type="module" src="/_app/index.js"></script></head><body></body></html>',
    "/site/vazia": page("<p>Nada para baixar</p>"),
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        HITS[p] += 1
        if p in PAGES:
            data, ctype = PAGES[p].encode(), "text/html"
        elif p == "/notas.txt":
            data, ctype = b"links: /a.pkg part01", "text/plain"
        elif p == "/a.pkg":
            data, ctype = PKG, "application/octet-stream"
        elif p.startswith("/r/") and p.endswith(".rar"):
            data, ctype = RAR, "application/octet-stream"
        elif p == "/go-localhost":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/a.pkg")
            self.end_headers()
            return
        elif p == "/site/get/1":
            self.send_response(302)
            self.send_header("Location", "/a.pkg")
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng and ctype != "text/html":
            a, b = rng[6:].split("-")
            a, b = int(a), min(int(b), len(data) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
            data = data[a:b + 1]
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def srv():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


NET = ResolverNet(allow_insecure=True, timeout=5)
HOSTS = {"127.0.0.1"}


@pytest.fixture(autouse=True)
def _reset():
    HITS.clear()


def test_pagina_com_varios_links_acha_pkg_e_volumes_rar_ordenados(srv):
    c = crawl(srv + "/site/start", NET, HOSTS)
    assert c.status == ARQUIVOS
    names = [f.filename for f in c.files]
    assert "a.pkg" in names and sorted(n for n in names if n.endswith(".rar")) == [f"x.part0{i}.rar" for i in (1, 2, 3)]
    g = group_sets(c.files)[0]
    assert g["complete"] and g["sspiOrder"] == [f"{srv}/r/x.part0{i}.rar" for i in (1, 2, 3)]


def test_redirect_do_link_e_resolvido_e_a_url_estavel_e_a_do_link(srv):
    c = crawl(srv + "/site/start", NET, HOSTS)
    f = next(f for f in c.files if f.sspiUrl.endswith("/site/get/1"))
    assert f.linkKind == "redirect" and f.finalUrl.endswith("/a.pkg") and f.format == "pkg"


def test_loop_nao_e_revisitado_e_link_repetido_com_fragmento_conta_uma_vez(srv):
    crawl(srv + "/site/start", NET, HOSTS)
    assert HITS["/site/start"] == 1 and HITS["/site/mirrors"] == 1 and HITS["/r/x.part01.rar"] == 1


def test_host_nao_permitido_nao_recebe_requisicao_e_e_listado(srv):
    c = crawl(srv + "/site/start", NET, HOSTS)
    assert any("externo.invalid" in s["url"] and "fora da lista" in s["reason"] for s in c.skipped)


def test_link_irrelevante_nao_e_seguido(srv):
    crawl(srv + "/site/start", NET, HOSTS)
    assert HITS["/sobre"] == 0


def test_captcha_em_um_ramo_vira_interacao_mas_nao_esconde_os_arquivos_dos_outros(srv):
    c = crawl(srv + "/site/start", NET, HOSTS)
    assert c.status == ARQUIVOS and len(c.interactions) == 1
    assert c.interactions[0]["url"].endswith("/site/protegido") and "CAPTCHA" in c.interactions[0]["reason"]
    assert HITS["/a.pkg"] >= 1 and "g-recaptcha" not in "".join(f.sspiUrl for f in c.files)


def test_botao_ou_formulario_sem_link_estatico_exige_navegador(srv):
    c = crawl(srv + "/site/botao", NET, HOSTS)
    assert c.status == INTERACAO and "formulário POST" in c.explanation and not c.files


def test_link_so_javascript_exige_navegador(srv):
    c = crawl(srv + "/site/so-js", NET, HOSTS)
    assert c.status == INTERACAO and "JavaScript" in c.explanation


def test_meta_refresh_estatico_e_seguido(srv):
    c = crawl(srv + "/site/meta", NET, HOSTS)
    assert c.status == ARQUIVOS and c.files[0].filename == "a.pkg"


def test_links_relativos_sao_resolvidos_contra_a_pagina(srv):
    c = crawl(srv + "/site/dir/rel", NET, HOSTS)
    assert {f.filename for f in c.files} == {"x.part02.rar", "a.pkg"}


def test_limite_de_profundidade_para_e_explica(srv):
    c = crawl(srv + "/site/p1", NET, HOSTS, max_depth=1)
    assert c.status != ARQUIVOS and any("profundidade" in s["reason"] for s in c.skipped) and HITS["/a.pkg"] == 0
    assert crawl(srv + "/site/p1", NET, HOSTS, max_depth=3).status == ARQUIVOS


def test_teto_de_requisicoes(srv):
    c = crawl(srv + "/site/start", NET, HOSTS, max_requests=3)
    assert c.requests == 3 and any("requisições" in s["reason"] for s in c.skipped)


def test_pagina_sem_nada_explica(srv):
    c = crawl(srv + "/site/vazia", NET, HOSTS)
    assert c.status == INTERACAO and not c.files          # sem link nem ação: depende do navegador


def test_url_de_arquivo_direto_continua_funcionando(srv):
    c = crawl(srv + "/a.pkg", NET, HOSTS)
    assert c.status == ARQUIVOS and len(c.files) == 1 and c.requests == 1


def test_404_na_entrada_informa_a_falha(srv):
    c = crawl(srv + "/nao-existe", NET, HOSTS)
    assert c.status == "INACESSIVEL" and not c.files


def test_cli_lista_organizada_e_json(srv, capsys):
    assert main(["--permitir", "127.0.0.1", "--hosts", "/x", srv + "/site/start"], net=NET) == 0
    out = capsys.readouterr().out
    assert "ARQUIVOS_ENCONTRADOS" in out and "completo" in out and "colar no SSPI:" in out and "INTERACAO_NECESSARIA" in out
    assert main(["--permitir", "127.0.0.1", "--hosts", "/x", "--json", srv + "/site/start"], net=NET) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["crawls"][0]["status"] == ARQUIVOS and d["sets"][0]["complete"] is True and d["crawls"][0]["skipped"]


def test_profundidade_zero_nao_segue(srv):
    c = crawl(srv + "/site/start", NET, HOSTS, max_depth=0)
    assert not c.files and HITS["/a.pkg"] == 0 and HITS["/site/mirrors"] == 0


def test_palavra_captcha_dentro_de_script_nao_e_captcha_mas_widget_real_e(srv):
    ok = crawl(srv + "/site/flags", NET, HOSTS)
    assert ok.status == ARQUIVOS and not ok.interactions               # falso positivo real visto na página do GitHub
    bad = crawl(srv + "/site/widget", NET, HOSTS)
    assert bad.status == INTERACAO and "CAPTCHA" in bad.explanation and not bad.files


def test_link_de_login_nunca_e_seguido_mesmo_com_extensao_na_query(srv):
    c = crawl(srv + "/site/so-login", NET, HOSTS)
    assert c.status == INTERACAO and "login" in c.explanation and HITS["/login"] == 0 and not c.files
    m = crawl(srv + "/site/mista", NET, HOSTS)
    assert m.status == ARQUIVOS and HITS["/login"] == 0 and any("login" in s["reason"] for s in m.skipped)


def test_pagina_montada_por_javascript_e_texto_puro(srv):
    c = crawl(srv + "/site/spa", NET, HOSTS)
    assert c.status == INTERACAO and "montado por JavaScript" in c.explanation        # caso real: pkg-zone.com (SvelteKit)
    t = crawl(srv + "/notas.txt", NET, HOSTS)
    assert t.status == "NAO_E_ARQUIVO" and not t.files                                # texto puro não é página nem arquivo


def test_busca_truncada_nunca_declara_conjunto_rar_completo(srv):
    c = crawl(srv + "/site/mirrors", NET, HOSTS, max_requests=3)      # só 2 dos 3 volumes cabem
    assert c.truncated
    g = group_sets(c.files, c.truncated)[0]
    assert g["complete"] is False and any("truncada" in p for p in g["problems"])
    full = crawl(srv + "/site/mirrors", NET, HOSTS)
    assert not full.truncated and group_sets(full.files, full.truncated)[0]["complete"] is True


def test_host_com_falha_de_tls_conhecida_no_sspi_usa_a_url_final_estavel(srv, monkeypatch):
    import ps4store.resolver as R
    monkeypatch.setattr(R, "load_tls_bad", lambda: {"127.0.0.1": "falhou com TLS no SSPI (teste)"})
    c = crawl(srv + "/go-localhost", NET, HOSTS | {"localhost"})
    f = c.files[0]
    assert f.sspiUrl.startswith("http://localhost:") and f.sspiUrl.endswith("/a.pkg") and any("já falhou com TLS" in n for n in f.notes)
    c2 = crawl(srv + "/a.pkg", NET, HOSTS)                     # sem URL final em outro host: só avisa
    assert c2.files[0].sspiUrl.endswith("/a.pkg") and any("ATENÇÃO" in n for n in c2.files[0].notes)
