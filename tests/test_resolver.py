"""Resolvedor: servidor HTTP local com arquivos próprios (nada de rede externa, nada baixado por inteiro)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ps4store.resolver import (FORMATO, NAO_E_ARQUIVO, HOST_NAO_PERMITIDO, INACESSIVEL, INTERACAO, OK, PAGINA_SEM_ARQUIVO, ResolverNet, group_sets,
                               main, resolve)

PKG = b"\x7fCNT" + b"\0" * 200_000
RAR = b"Rar!\x1a\x07\x01\x00" + b"\0" * 100_000
HTML_CAPTCHA = b"<html><body><div class='g-recaptcha'></div><a href='/x.pkg'>baixar</a></body></html>"
HTML_JS = b"<html><noscript>Please enable JavaScript to continue to the download page.</noscript></html>"
HTML_LIST = b"<html><a href='/a.pkg'>a</a> <a href='/r/x.part01.rar'>1</a> <a href='/r/x.part01.rar'>dup</a> <a href='/sobre'>s</a></html>"
HTML_PLAIN = b"<html><body>Nada para baixar aqui.</body></html>"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _body(self, data, ctype="application/octet-stream", extra=None, honor_range=True):
        rng = self.headers.get("Range")
        if honor_range and rng and rng.startswith("bytes="):
            a, b = rng[6:].split("-")
            a, b = int(a), min(int(b), len(data) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
            chunk = data[a:b + 1]
        else:
            self.send_response(200)
            chunk = data
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(chunk)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(chunk)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/a.pkg":
            return self._body(PKG)
        if p == "/go":
            self.send_response(302)
            self.send_header("Location", "/a.pkg")
            self.end_headers()
            return
        if p == "/cd":
            return self._body(PKG, extra={"Content-Disposition": 'attachment; filename="Jogo_v1.02.pkg"'})
        if p.startswith("/r/") and p.endswith(".rar"):
            return self._body(RAR)
        if p == "/captcha":
            return self._body(HTML_CAPTCHA, "text/html", honor_range=False)
        if p == "/js":
            return self._body(HTML_JS, "text/html", honor_range=False)
        if p == "/list":
            return self._body(HTML_LIST, "text/html", honor_range=False)
        if p == "/plain":
            return self._body(HTML_PLAIN, "text/html", honor_range=False)
        if p == "/norange.pkg":
            return self._body(PKG, honor_range=False)
        if p == "/disfarce.rar":
            return self._body(PKG)
        if p == "/erro-json":                       # como o pkg-zone: 200 com JSON de erro, sem extensão
            return self._body(b'{"error":"Package not found."}', "application/json", honor_range=False)
        if p == "/z.zip":
            return self._body(b"PK\x03\x04" + b"\0" * 100)
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def srv():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


NET = ResolverNet(allow_insecure=True, timeout=5)
HOSTS = {"127.0.0.1"}


def R(url):
    return resolve(url, NET, HOSTS)


def test_link_direto_pkg_identifica_nome_tamanho_formato_por_bytes(srv):
    r = R(srv + "/a.pkg")
    assert (r.status, r.filename, r.format, r.sizeBytes, r.formatConfirmedByBytes) == (OK, "a.pkg", "pkg", len(PKG), True)
    assert r.rangeOk and r.sspiSendable and r.linkKind == "direto" and r.sspiUrl == srv + "/a.pkg"


def test_redirect_comum_segue_e_guarda_a_url_estavel_para_o_sspi(srv):
    r = R(srv + "/go")
    assert r.status == OK and r.linkKind == "redirect" and r.finalUrl.endswith("/a.pkg") and r.sspiUrl.endswith("/go")


def test_nome_vem_do_content_disposition_quando_a_url_nao_tem_extensao(srv):
    r = R(srv + "/cd")
    assert r.filename == "Jogo_v1.02.pkg" and r.format == "pkg"


def test_servidor_sem_range_e_avisado(srv):
    r = R(srv + "/norange.pkg")
    assert r.status == OK and not r.rangeOk and any("Range" in n for n in r.notes)


def test_assinatura_dos_bytes_vence_o_nome_e_avisa(srv):
    r = R(srv + "/disfarce.rar")
    assert r.format == "pkg" and any("o nome sugere" in n for n in r.notes)


def test_zip_nao_e_enviado_ao_sspi(srv):
    r = R(srv + "/z.zip")
    assert r.status == FORMATO and not r.sspiSendable


def test_captcha_e_javascript_viram_interacao_necessaria_sem_contornar(srv):
    for path, why in (("/captcha", "CAPTCHA"), ("/js", "JavaScript")):
        r = R(srv + path)
        assert r.status == INTERACAO and why in r.detail and not r.sspiUrl and not r.sspiSendable


def test_pagina_com_links_estaticos_lista_candidatos_sem_seguir(srv):
    r = R(srv + "/list")
    assert r.status == PAGINA_SEM_ARQUIVO and r.candidates == ["/a.pkg", "/r/x.part01.rar"]
    assert R(srv + "/plain").status == INTERACAO              # sem link direto: depende de ação humana


def test_404_e_host_fora_da_lista(srv):
    r = R(srv + "/nao-existe")
    assert r.status == INACESSIVEL and r.linkKind == "removido"
    assert resolve("https://exemplo.invalid/a.pkg", NET, HOSTS).status == HOST_NAO_PERMITIDO
    assert resolve(srv + "/a.pkg", NET, set()).status == HOST_NAO_PERMITIDO


def test_volumes_rar_ordenados_mesmo_embaralhados_e_completos(srv):
    urls = [f"{srv}/r/x.part{n:02d}.rar" for n in (3, 1, 2)]
    res = [R(u) for u in urls]
    assert all(r.format == "rar-multiparte" and r.volume["index"] == i for r, i in zip(res, (3, 1, 2)))
    g = group_sets(res)[0]
    assert g["complete"] and g["volumes"] == 3 and g["sspiOrder"] == [f"{srv}/r/x.part{n:02d}.rar" for n in (1, 2, 3)]
    assert g["problems"] == [] and g["markMultipartInSspi"] is False


def test_volume_faltando_e_repetido_sao_apontados(srv):
    g = group_sets([R(f"{srv}/r/x.part{n:02d}.rar") for n in (1, 3, 3)])[0]
    assert not g["complete"] and any("[2]" in p for p in g["problems"]) and any("repetido" in p for p in g["problems"])
    g2 = group_sets([R(f"{srv}/r/x.part{n:02d}.rar") for n in (2, 3)])[0]
    assert not g2["complete"] and any("começa em 2" in p for p in g2["problems"])


def test_cli_json_nao_inclui_nada_alem_do_resultado(srv, capsys):
    assert main(["--permitir", "127.0.0.1", "--hosts", "/nao/existe", "--json", srv + "/go"], net=NET) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["results"][0]["status"] == OK and d["sets"] == []


def test_cli_texto_mostra_status_e_motivo(srv, capsys):
    assert main(["--permitir", "127.0.0.1", "--hosts", "/nao/existe", srv + "/captcha", srv + "/a.pkg"], net=NET) == 0
    out = capsys.readouterr().out
    assert "INTERACAO_NECESSARIA" in out and "OK  a.pkg" in out


def test_resposta_200_que_nao_e_arquivo_vira_nao_e_arquivo_com_a_mensagem_do_servidor(srv):
    r = R(srv + "/erro-json")
    assert r.status == NAO_E_ARQUIVO and "Package not found" in r.detail and not r.sspiUrl and not r.sspiSendable
