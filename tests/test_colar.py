"""Formatador para o painel do SSPI + script termux-url-opener: regras de 'pronto', ordem, limite de 50, cópia e segurança dos argumentos."""
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ps4store.colar import LIMITE_PAINEL, copiar, extrair_urls, ler_lista, main, montar_blocos, ultimo_volume_aberto, validar_url
from ps4store.resolver import Crawl, Resolved, ResolverNet

ROOT = Path(__file__).resolve().parents[1]


def R(url, fmt="pkg", idx=None, set_="x.part*.rar", style="part-rar", ok=True, size=1_000_000):
    return Resolved(url, "OK", sspiUrl=url, filename=url.rsplit("/", 1)[-1], format=fmt, sspiSendable=ok, sizeBytes=size,
                    volume={"set": set_, "index": idx, "style": style} if idx is not None else None)


def C(files, terminal=None, skipped=None):
    c = Crawl("https://h/x")
    c.files = list(files)
    c.terminal = list(terminal if terminal is not None else files)
    c.skipped = skipped or []
    return c


def blocos(res):
    return {b.tipo + str(i): b for i, b in enumerate(res["blocos"])}


# ---------- entrada ----------
def test_validar_e_extrair_urls():
    assert validar_url("https://a.com/x.pkg") and validar_url("http://a.com/y")
    for ruim in ("ftp://a.com/x", "javascript:alert(1)", "https://a b.com/x", "https://u:p@a.com/x", "https:///x", "-rf", "$(id)", "https://a.com/x\nhttps://b.com", ""):
        assert validar_url(ruim) is None
    assert extrair_urls("Baixar jogo\nhttps://pkg-zone.com/download/ps4/OPEN00001/1.01).") == ["https://pkg-zone.com/download/ps4/OPEN00001/1.01"]
    assert extrair_urls("$(touch /tmp/x) `id` ; rm -rf / sem url") == []


# ---------- regras de 'pronto' ----------
def test_rar_embaralhado_sai_em_ordem_e_pronto():
    vols = [R(f"https://h/x.part{n:02d}.rar", "rar-multiparte", n) for n in (3, 1, 2)]
    b = montar_blocos([C(vols)])["blocos"][0]
    assert b.pronto and b.tipo == "rar" and [u[-6:] for u in b.urls] == ["01.rar", "02.rar", "03.rar"]


def test_conjunto_incompleto_nunca_e_pronto():
    b = montar_blocos([C([R(f"https://h/x.part{n:02d}.rar", "rar-multiparte", n) for n in (1, 3)])])["blocos"][0]
    assert not b.pronto and any("[2]" in p for p in b.bloqueio)
    b2 = montar_blocos([C([R(f"https://h/x.part{n:02d}.rar", "rar-multiparte", n) for n in (2, 3)])])["blocos"][0]
    assert not b2.pronto


def test_busca_truncada_bloqueia_o_conjunto_mesmo_contiguo():
    c = C([R(f"https://h/x.part{n:02d}.rar", "rar-multiparte", n) for n in (1, 2, 3)], skipped=[{"url": "u", "reason": "limite de 10 páginas"}])
    res = montar_blocos([c])
    assert not res["blocos"][0].pronto and any("truncada" in p for p in res["blocos"][0].bloqueio) and any("truncada" in a for a in res["avisos"])


def test_estilo_antigo_nao_e_marcado_pronto():
    vols = [R("https://h/y.rar", "rar-multiparte", None, "y.rar", "old-rar"), R("https://h/y.r00", "rar-multiparte", None, "y.rar", "old-rar")]
    for v in vols:
        v.filename = v.sspiUrl.rsplit("/", 1)[-1]
        v.volume = {"set": "y.rar", "index": None, "style": "old-rar"}          # como o resolvedor devolve estilo antigo
    assert not montar_blocos([C(vols)])["blocos"][0].pronto


def test_mais_de_50_avulsos_viram_lotes_de_50_com_alerta():
    files = [R(f"https://h/p{n}.pkg") for n in range(120)]
    res = montar_blocos([C(files)])
    assert [len(b.urls) for b in res["blocos"]] == [50, 50, 20] and all(b.pronto for b in res["blocos"])
    assert any("120" in a and "lotes" in a for a in res["avisos"]) and any("120 URLs no total" in a for a in res["avisos"])


def test_conjunto_com_mais_de_50_volumes_e_bloqueado_nao_dividido():
    vols = [R(f"https://h/x.part{n:02d}.rar", "rar-multiparte", n) for n in range(1, LIMITE_PAINEL + 2)]
    b = montar_blocos([C(vols)])["blocos"][0]
    assert not b.pronto and any("no máximo 50" in p for p in b.bloqueio) and len(b.urls) == 51


def test_link_temporario_fica_de_fora_a_menos_que_aceito():
    t = R("https://h/a.pkg?exp=9999999999&sig=abc")
    res = montar_blocos([C([t, R("https://h/b.pkg")])])
    assert [b.urls for b in res["blocos"]] == [["https://h/b.pkg"]] and any("temporário" in n["motivo"] for n in res["naoEnviar"])
    assert montar_blocos([C([t])], aceitar_temporarias=True)["blocos"][0].urls == [t.sspiUrl]


def test_nao_ok_e_nao_enviavel_vao_para_nao_enviar_com_motivo():
    inter = Resolved("https://h/p", "INTERACAO_NECESSARIA", "página exige CAPTCHA")
    ruim = R("https://h/c.pkg", ok=False)
    ruim.detail = "servidor ignora Range"
    res = montar_blocos([C([ruim], terminal=[ruim, inter])])
    assert not res["blocos"]
    motivos = " | ".join(n["motivo"] for n in res["naoEnviar"])
    assert "CAPTCHA" in motivos and "Range" in motivos


# ---------- cópia ----------
def test_copiar_usa_lista_de_argumentos_sem_shell_e_texto_por_stdin():
    chamadas = []

    def run(cmd, **kw):
        chamadas.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0)

    ok, _ = copiar("https://h/a.pkg\n", run, lambda n: "/x/termux-clipboard-set")
    assert ok and chamadas[0][0] == ["/x/termux-clipboard-set"] and chamadas[0][1]["input"] == "https://h/a.pkg\n" and not chamadas[0][1].get("shell")
    ok2, msg = copiar("x", run, lambda n: None)
    assert not ok2 and "manualmente" in msg


# ---------- ponta a ponta (servidor local, sem download completo) ----------
PKG = b"\x7fCNT" + b"\0" * 20_000
RAR = b"Rar!\x1a\x07\x01\x00" + b"\0" * 20_000
LAST = {"v": 11, "w": 51}        # diretório -> índice do último volume (os anteriores declaram "há mais volumes")


def volume_rar5(diretorio: str, n: int) -> bytes:
    aberto = n < LAST[diretorio]
    return b"Rar!\x1a\x07\x01\x00" + b"\0" * 20_000 + b"\x11\x22\x33\x44" + b"\x03\x05\x04" + (b"\x01" if aberto else b"\x00") + (b"\0" * 4 if aberto else b"")


PAGES = {
    "/pg": '<a href="/r/x.part03.rar">3</a><a href="/r/x.part01.rar">1</a><a href="/r/x.part02.rar">2</a><a href="/a.pkg">pkg</a>',
    "/pg-falta": '<a href="/r/x.part01.rar">1</a><a href="/r/x.part03.rar">3</a>',
    "/pg-temp": '<a href="/a.pkg?exp=9999999999&sig=zz">Download</a>',
    "/pg-captcha": '<div class="g-recaptcha"></div>',
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in PAGES:
            data, ct = ("<html><body>" + PAGES[p] + "</body></html>").encode(), "text/html"
        elif p == "/a.pkg":
            data, ct = PKG, "application/octet-stream"
        elif p.startswith("/r/") and p.endswith(".rar"):
            data, ct = RAR, "application/octet-stream"
        elif re.match(r"^/(v|w)/\w+\.part\d+\.rar$", p):
            data, ct = volume_rar5(p[1], int(re.search(r"part(\d+)", p).group(1))), "application/octet-stream"
        elif re.match(r"^/p/\d+\.pkg$", p):
            data, ct = PKG, "application/octet-stream"
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
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def srv():
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


NET = ResolverNet(allow_insecure=True, timeout=5)
BASE = ["--permitir", "127.0.0.1", "--hosts", "/nao/existe"]


def rodar(args, capsys, copias=None, termux=True):
    def run(cmd, **kw):
        if copias is not None:
            copias.append(kw["input"])
        return subprocess.CompletedProcess(cmd, 0)

    rc = main(BASE + args, net=NET, run=run, which=(lambda n: "/x/termux-clipboard-set") if termux else (lambda n: None))
    return rc, capsys.readouterr().out


def test_e2e_pagina_vira_dois_blocos_e_copia_o_primeiro_em_ordem(srv, capsys):
    copias = []
    rc, out = rodar([srv + "/pg"], capsys, copias)
    assert rc == 0 and "2 bloco(s) pronto(s)" in out and "BLOCO 1 · PRONTO · RAR" in out and "BLOCO 2 · PRONTO · 1 arquivo" in out
    assert copias == [f"{srv}/r/x.part01.rar\n{srv}/r/x.part02.rar\n{srv}/r/x.part03.rar\n"]
    rc, out = rodar([srv + "/pg", "--bloco", "2"], capsys, copias)
    assert copias[-1] == f"{srv}/a.pkg\n" and "Copiado: BLOCO 2" in out


def test_e2e_conjunto_incompleto_nao_e_copiado(srv, capsys):
    copias = []
    rc, out = rodar([srv + "/pg-falta"], capsys, copias)
    assert rc == 3 and copias == [] and "NÃO ENVIAR" in out and "Nada pronto" in out


def test_e2e_sem_termux_api_mostra_bloco_para_copia_manual(srv, capsys):
    rc, out = rodar([srv + "/a.pkg"], capsys, termux=False)
    assert rc == 0 and "copie manualmente" in out and f"----- copie daqui (BLOCO 1) -----\n{srv}/a.pkg\n----- até aqui -----" in out


def test_e2e_temporario_e_captcha_nao_sao_enviados(srv, capsys):
    rc, out = rodar([srv + "/pg-temp"], capsys, [])
    assert rc == 3 and "temporário" in out
    rc, out = rodar([srv + "/pg-captcha"], capsys, [])
    assert rc == 3 and "CAPTCHA" in out


def test_e2e_json_e_entrada_invalida(srv, capsys):
    rc, out = rodar([srv + "/pg", "--json"], capsys)
    d = json.loads(out)
    assert rc == 0 and d["blocos"][0]["pronto"] and d["blocos"][0]["urls"][0].endswith("part01.rar")
    assert main(["--extrair", "$(touch /tmp/x) ; rm -rf /"]) == 2


# ---------- script termux-url-opener: o texto recebido nunca vira comando ----------
def _opener(arg, tmp_path):
    env = dict(os.environ, PS4STORE_DIR=str(ROOT), PS4STORE_PYTHON=sys.executable, PS4STORE_SEM_PAUSA="1")
    return subprocess.run(["sh", str(ROOT / "android" / "termux-url-opener"), arg], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)


@pytest.mark.parametrize("malicioso", ["$(touch PWNED)", "`touch PWNED`", "; touch PWNED", "https://x.invalid/a.pkg; touch PWNED", "-h", "--arquivo /etc/passwd",
                                       "x\ntouch PWNED"])
def test_opener_nao_executa_nem_interpreta_conteudo_recebido(malicioso, tmp_path):
    r = _opener(malicioso, tmp_path)
    assert not (tmp_path / "PWNED").exists() and not (ROOT / "PWNED").exists()
    assert "usage" not in (r.stdout + r.stderr).lower()                       # '-h' não vira opção do programa
    if "http" not in malicioso:
        assert r.returncode == 2 and "nenhuma URL http(s) válida" in r.stderr


def test_opener_sem_projeto_avisa(tmp_path):
    env = dict(os.environ, PS4STORE_DIR=str(tmp_path), PS4STORE_SEM_PAUSA="1")
    r = subprocess.run(["sh", str(ROOT / "android" / "termux-url-opener"), "https://a.com/x.pkg"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 1 and "Projeto não encontrado" in r.stderr


# ---------- --arquivo (listas locais): regressão do caso real "rartest/links-ordem.txt" ----------
def lista(tmp_path, linhas, nome="lista.txt"):
    f = tmp_path / nome
    f.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return str(f)


def vols(srv, d, ns):
    return [f"{srv}/{d}/x.part{n:02d}.rar" for n in ns]


def test_ler_lista_ignora_vazias_e_comentarios_sem_limite_de_10(tmp_path):
    f = lista(tmp_path, ["# volumes", "", "  ", *[f"https://h/p{n}.pkg" for n in range(30)], "texto solto", "ftp://h/x", "# fim", "https://h/p0.pkg"])
    urls, avisos = ler_lista(f)
    assert len(urls) == 30 and urls[0] == "https://h/p0.pkg" and urls[-1] == "https://h/p29.pkg"
    assert len(avisos) == 2 and "linha" in avisos[0]


def test_arquivo_com_11_volumes_vira_um_unico_bloco_pronto_em_ordem(srv, tmp_path, capsys):
    embaralhado = [vols(srv, "v", [n])[0] for n in (4, 11, 1, 7, 2, 10, 3, 9, 5, 8, 6)]
    f = lista(tmp_path, ["# 11 volumes (embaralhados)", "", *embaralhado, ""])
    copias = []
    rc, out = rodar(["--arquivo", f], capsys, copias)
    assert rc == 0 and "1 bloco(s) pronto(s)" in out and out.count("== BLOCO") == 1 and "RAR x.part*.rar · 11 volume(s)" in out
    assert copias == ["\n".join(vols(srv, "v", range(1, 12))) + "\n"]
    assert "confirmado pelo cabeçalho RAR" in out


def test_arquivo_sem_o_ultimo_volume_e_bloqueado_pelo_cabecalho_final(srv, tmp_path, capsys):
    copias = []
    rc, out = rodar(["--arquivo", lista(tmp_path, vols(srv, "v", range(1, 11)))], capsys, copias)       # 1..10 de 11 (como rartest/links-sem-part11.txt)
    assert rc == 3 and copias == [] and "BLOQUEADO" in out and "há mais volumes depois" in out and "Nada pronto" in out


def test_arquivo_com_volume_do_meio_faltando_e_bloqueado(srv, tmp_path, capsys):
    rc, out = rodar(["--arquivo", lista(tmp_path, vols(srv, "v", [n for n in range(1, 12) if n != 5]))], capsys, [])
    assert rc == 3 and "[5]" in out and "NÃO ENVIAR" in out


def test_arquivo_com_mais_de_50_volumes_e_bloqueado_e_avulsos_viram_lotes(srv, tmp_path, capsys):
    rc, out = rodar(["--arquivo", lista(tmp_path, vols(srv, "w", range(1, 52)))], capsys, [])
    assert rc == 3 and "no máximo 50" in out
    copias = []
    rc, out = rodar(["--arquivo", lista(tmp_path, [f"{srv}/p/{n}.pkg" for n in range(1, 56)])], capsys, copias)
    assert rc == 0 and "lote 1 de 2" in out and "lote 2 de 2" in out and len(copias[0].splitlines()) == 50 and "55 URLs no total" in out


def test_limite_de_10_continua_so_para_argumentos_com_aviso_explicito(srv, capsys):
    rc, out = rodar([f"{srv}/p/{n}.pkg" for n in range(1, 13)] + ["--sem-copiar"], capsys)
    assert "só as 10 primeiras" in out and "10 arquivo(s) avulso(s)" in out


def test_arquivo_inexistente_ou_gigante_falha_claro(tmp_path, capsys):
    assert main(BASE + ["--arquivo", str(tmp_path / "nao-existe.txt")]) == 2
    assert main(BASE + ["--arquivo", lista(tmp_path, [f"https://h/p{n}.pkg" for n in range(501)])]) == 2
    assert main(BASE + ["--arquivo", lista(tmp_path, ["# só comentário", ""])]) == 2


def test_arquivo_junto_com_url_posicional_mantem_ordem_e_remove_repetidas(srv, tmp_path, capsys):
    copias = []
    f = lista(tmp_path, [f"{srv}/p/2.pkg", f"{srv}/p/1.pkg"])
    rc, out = rodar([f"{srv}/p/1.pkg", "--arquivo", f], capsys, copias)
    assert rc == 0 and copias == [f"{srv}/p/1.pkg\n{srv}/p/2.pkg\n"]


def test_ultimo_volume_aberto_cobre_casos_sem_confirmacao():
    class Net:
        def __init__(self, head, status=206, ini=None):
            self.head, self.status, self.ini = head, status, ini

        def probe(self, url, nbytes, start):
            from ps4store.net import Probe
            return Probe(True, self.status, head=self.head, range_start=start if self.ini is None else self.ini)

    fim_aberto = b"\0" * 50 + b"\x03\x05\x04\x01" + b"\0" * 10
    fim_ultimo = b"\0" * 60 + b"\x03\x05\x04\x00"
    assert ultimo_volume_aberto("u", 1000, Net(fim_aberto)) is True
    assert ultimo_volume_aberto("u", 1000, Net(fim_ultimo)) is False
    assert ultimo_volume_aberto("u", 1000, Net(b"\x03\x05\x04\x01" + b"\xff" * 60)) is None       # padrão no meio dos dados, não no fim
    assert ultimo_volume_aberto("u", 1000, Net(b"x" * 64)) is None                                   # sem cabeçalho (ex.: RAR4)
    assert ultimo_volume_aberto("u", 1000, Net(fim_aberto, status=200)) is None                      # servidor ignora Range
    assert ultimo_volume_aberto("u", 1000, Net(fim_aberto, ini=0)) is None                           # offset não honrado
    assert ultimo_volume_aberto("u", None, Net(fim_aberto)) is None
