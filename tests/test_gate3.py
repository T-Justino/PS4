"""Gate 3: descoberta automática, verificação leve de links e geração do catálogo.

Os PKGs de teste derivam do PKG real do T8 (dist/t8) com IDs trocados SÓ nos bytes lidos pelo robô (primeiros 64 KiB);
servem para exercitar as regras e nunca são publicados.
"""
import http.server
import json
import threading
import zipfile
from pathlib import Path

import pytest

from ps4store import sspi
from ps4store.cli import main
from ps4store.discover import ConfigError, Source, discover_github, load_config, run
from ps4store.net import NetError, Probe, UrllibNet
from ps4store.pkginfo import PkgError, parse_head

ROOT = Path(__file__).parent.parent
BASE_PKG = (ROOT / "dist/t8/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg").read_bytes()
NOW = "2026-11-22T12:00:00Z"


def make_pkg(title_id="CUSA95417", *, category=None, title=None, header_only=False):
    """Cópia do PKG real com outro ID (só para teste). header_only=True deixa o param.sfo com o ID antigo."""
    head = bytearray(BASE_PKG[:65536])
    old = b"CUSA95417"
    new = title_id.encode()
    assert len(new) == 9
    if header_only:
        i = head.index(b"IV0000-CUSA95417_00-PS4STOREBRTEST00")
        head[i + 7:i + 16] = new
    else:
        head[:] = head.replace(old, new)
    if category:
        j = head.index(b"gd\x00")
        head[j:j + 2] = category.encode()
    if title:
        head[:] = head.replace(b"PS4 Store BR Test", title.encode().ljust(17, b" ")[:17])
    return bytes(head) + BASE_PKG[65536:]


class Html(bytes):
    pass


class FakeNet:
    """Rede simulada: uma 'API de releases' mutável + um 'servidor de arquivos' com semântica de Range."""

    def __init__(self):
        self.releases: dict[str, list] = {}
        self.files: dict[str, bytes] = {}
        self.errors: dict[str, str] = {}
        self.bytes_served = 0
        self.probes = 0

    def release(self, repo, rid, tag, assets, **kw):
        a = [{"id": rid * 100 + i, "name": n, "browser_download_url": u, "size": s, "state": "uploaded"}
             for i, (n, u, s) in enumerate(assets)]
        self.releases.setdefault(repo, []).insert(0, {"id": rid, "tag_name": tag, "draft": False, "prerelease": False,
                                                       "html_url": f"https://example.org/{repo}/releases/{tag}",
                                                       "published_at": f"2026-11-{10 + rid:02d}T00:00:00Z", "assets": a, **kw})

    def get_json(self, url):
        repo = url.split("/repos/")[1].split("/releases")[0]
        if repo in self.errors:
            raise NetError(self.errors[repo])
        return self.releases.get(repo, [])

    def probe(self, url, nbytes=65536, start=0):
        self.probes += 1
        if url not in self.files:
            return Probe(False, 404, "HTTP 404", final_url=url)
        d = self.files[url]
        self.bytes_served += min(len(d), nbytes)
        ct = "text/html" if isinstance(d, Html) else "application/octet-stream"
        return Probe(True, 206, None, len(d), bytes(d[start:start + nbytes]), url, ct, range_ok=True)


def write_cfg(tmp_path, *, sources=None, tls=None):
    cfg = {"schema": "ps4storebr.sources/v1",
           "catalog": {"id": "test.auto", "name": "Teste", "description": "d"},
           "tls": tls if tls is not None else {"enforce": True, "known_bad_hosts": {"github.com": "obs"}},
           "sources": sources or [{"id": "src-a", "type": "github-releases", "repo": "acme/app", "enabled": True,
                                   "authorization": {"basis": "license", "evidence": "licença livre do autor"}}]}
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(cfg))
    return p


def go(tmp_path, net, cfg_path, **kw):
    cfg = load_config(cfg_path)
    return run(cfg, net, out_gssource=tmp_path / "out/auto.gssource", out_canonical=tmp_path / "out/canon.json",
               out_report=tmp_path / "out/report.json", state_path=tmp_path / "state.json", now=NOW, **kw)


H = "https://dl.example.org/"   # host de download fictício (não está na lista de TLS ruim)


# ---------------------------------------------------------------- pkginfo

def test_parse_head_reads_identity_from_real_pkg():
    h = parse_head(BASE_PKG[:65536])
    assert (h.title_id, h.kind, h.sfo["TITLE"]) == ("CUSA95417", "base", "PS4 Store BR Test")


def test_parse_head_errors():
    with pytest.raises(PkgError) as e:
        parse_head(b"<html>" + b"0" * 5000)
    assert e.value.code == "NOT_PKG"
    with pytest.raises(PkgError) as e:
        parse_head(BASE_PKG[:0x2000])              # janela curta: tabela/param.sfo fora
    assert e.value.code == "SFO_OUTSIDE_WINDOW"


# ---------------------------------------------------------------- critério principal: descobrir entrada nova sozinho

def test_robot_discovers_new_release_and_updates_catalog_without_manual_url(tmp_path):
    cfgp = write_cfg(tmp_path)                       # a config só tem o REPO; nenhuma URL de arquivo
    net = FakeNet()
    u1 = H + "app-1.0.pkg"
    net.files[u1] = make_pkg("CUSA95417")
    net.release("acme/app", 1, "v1.0", [("app-1.0.pkg", u1, len(net.files[u1]))])

    r1 = go(tmp_path, net, cfgp)
    assert (r1.report["counts"]["novos"], r1.report["counts"]["publicados"]) == (1, 1)
    z1 = zipfile.ZipFile(tmp_path / "out/auto.gssource")
    assert [t["titleId"] for t in json.loads(z1.read("index/titles.json"))["titles"]] == ["CUSA95417"]
    assert json.loads((tmp_path / "out/canon.json").read_text())["source"]["version"] == "1.0.1"

    # o autor publica uma NOVA release (outro pacote, outra URL) — ninguém cadastra nada
    u2 = H + "outro-2.0.pkg"
    net.files[u2] = make_pkg("CUSA95418", title="Outro App Teste")
    net.release("acme/app", 2, "v2.0", [("outro-2.0.pkg", u2, len(net.files[u2]))])
    r2 = go(tmp_path, net, cfgp)
    c = r2.report["counts"]
    assert (c["descobertos"], c["novos"], c["publicados"]) == (2, 1, 2)
    new = [e for e in r2.report["entries"] if e["isNew"]]
    assert [(e["titleId"], e["release"]) for e in new] == [("CUSA95418", "v2.0")]
    data = (tmp_path / "out/auto.gssource").read_bytes()
    assert sspi.check_archive(data).ok
    z2 = zipfile.ZipFile(tmp_path / "out/auto.gssource")
    ids = [t["titleId"] for t in json.loads(z2.read("index/titles.json"))["titles"]]
    assert sorted(ids) == ["CUSA95417", "CUSA95418"]
    assert json.loads((tmp_path / "out/canon.json").read_text())["source"]["version"] == "1.0.2"   # versão sobe: reimportar atualiza

    # nada mudou: sem novos, versão estável, artefato idêntico
    r3 = go(tmp_path, net, cfgp)
    assert r3.report["counts"]["novos"] == 0
    assert (tmp_path / "out/auto.gssource").read_bytes() == data
    assert json.loads((tmp_path / "out/canon.json").read_text())["source"]["version"] == "1.0.2"


def test_published_rows_carry_verified_data_only(tmp_path):
    net = FakeNet()
    u = H + "app-1.0.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1.0", [("app-1.0.pkg", u, len(net.files[u]))])
    go(tmp_path, net, write_cfg(tmp_path))
    canon = json.loads((tmp_path / "out/canon.json").read_text())
    [t] = canon["titles"]
    [p] = t["packages"]
    assert t["name"] == "PS4 Store BR Test" and t["titleId"] == "CUSA95417"
    assert p["contentId"] == "IV0000-CUSA95417_00-PS4STOREBRTEST00" and p["size"] == len(BASE_PKG)
    assert p["version"] == "1.00" and p["url"] == u and "sha256" not in p      # não fabrica hash sem baixar o arquivo
    assert p["authorization"]["basis"] == "license"


# ---------------------------------------------------------------- descoberto ≠ acessível ≠ compatível ≠ publicado

def test_classification_ladder_and_reasons(tmp_path):
    net = FakeNet()
    spec = {}
    def add(name, data, size=None, host=H):
        u = host + name
        if data is not None:
            net.files[u] = data
        spec[name] = (name, u, len(data) if size is None and data is not None else (size or 1000))
    add("good.pkg", make_pkg("CUSA95417"))
    add("npxs.pkg", make_pkg("NPXS39041"))
    add("apol.pkg", make_pkg("APOL00004"))
    add("unproven.pkg", make_pkg("PCAS00001"))
    add("placeholder.pkg", make_pkg("CUSA99999"))
    add("update.pkg", make_pkg("CUSA95418", category="gp"))
    add("mismatch.pkg", make_pkg("CUSA95419", header_only=True))
    add("html.pkg", Html(b"<html>login</html>" + b"0" * 5000))
    add("garbage.pkg", b"\x00" * 70000)
    add("missing.pkg", None)
    add("sizebad.pkg", make_pkg("CUSA95420"), size=12345)
    add("github.pkg", make_pkg("CUSA95421"), host="https://github.com/acme/app/releases/download/v1/")
    net.release("acme/app", 1, "v1", list(spec.values()) + [("leia.txt", H + "leia.txt", 10)])
    net.release("acme/app", 2, "v2-pre", [("pre.pkg", H + "pre.pkg", 1)], prerelease=True)
    net.release("acme/app", 3, "v3-draft", [("draft.pkg", H + "draft.pkg", 1)], draft=True)

    r = go(tmp_path, net, write_cfg(tmp_path))
    by = {e["asset"]: e for e in r.report["entries"]}
    assert set(by) == set(spec)                                 # .txt, pré-release e rascunho ignorados
    exp = {"good.pkg": ("publicado", None),
           "npxs.pkg": ("pkg_verificado", "PREFIX_REJECTED_BY_SSPI"),
           "apol.pkg": ("pkg_verificado", "PREFIX_REJECTED_BY_SSPI"),
           "unproven.pkg": ("pkg_verificado", "PREFIX_UNPROVEN"),
           "placeholder.pkg": ("pkg_verificado", "PLACEHOLDER_ID"),
           "update.pkg": ("pkg_verificado", "KIND_UNTESTED"),
           "mismatch.pkg": ("acessivel", "IDENTITY_MISMATCH"),
           "html.pkg": ("descoberto", "NOT_FILE"),
           "garbage.pkg": ("acessivel", "NOT_PKG"),
           "missing.pkg": ("descoberto", "UNREACHABLE"),
           "sizebad.pkg": ("descoberto", "SIZE_MISMATCH"),
           "github.pkg": ("compativel_sspi", "TLS_HOST_BLOCKED")}
    for name, (stage, reason) in exp.items():
        assert (by[name]["stage"], by[name]["reason"]) == (stage, reason), name
    c = r.report["counts"]
    assert c["descobertos"] == 12 and c["publicados"] == 1 and c["rejeitados"] == 11
    assert c["acessiveis"] > c["pkgVerificados"] > c["compativeisSspi"] > c["publicados"]
    # o catálogo instalável só tem o que passou em tudo
    z = zipfile.ZipFile(tmp_path / "out/auto.gssource")
    assert [t["titleId"] for t in json.loads(z.read("index/titles.json"))["titles"]] == ["CUSA95417"]
    md = (tmp_path / "out/report.md").read_text()
    assert "PREFIX_REJECTED_BY_SSPI" in md and "TLS_HOST_BLOCKED" in md


def test_tls_policy_can_be_relaxed_by_config(tmp_path):
    net = FakeNet()
    u = "https://github.com/acme/app/releases/download/v1/a.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    assert go(tmp_path, net, write_cfg(tmp_path)).published == 0
    r = go(tmp_path, net, write_cfg(tmp_path, tls={"enforce": False}))
    assert r.published == 1


def test_robot_asks_for_the_head_window_only(tmp_path):
    net = FakeNet()
    u = H + "a.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    go(tmp_path, net, write_cfg(tmp_path))
    assert net.bytes_served <= 65536 * net.probes and len(BASE_PKG) > 6_000_000


# ---------------------------------------------------------------- autorização, falhas e artefato anterior

def test_source_without_authorization_is_rejected(tmp_path):
    bad = write_cfg(tmp_path, sources=[{"id": "x", "type": "github-releases", "repo": "a/b", "authorization": {"basis": "license"}}])
    with pytest.raises(ConfigError, match="authorization"):
        load_config(bad)
    bad2 = write_cfg(tmp_path, sources=[{"id": "x", "type": "crawler", "repo": "a/b", "authorization": {"basis": "license", "evidence": "e"}}])
    with pytest.raises(ConfigError, match="type"):
        load_config(bad2)


def test_failing_source_does_not_stop_the_others_and_is_reported(tmp_path):
    net = FakeNet()
    u = H + "a.pkg"
    net.files[u] = make_pkg()
    net.release("ok/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    net.errors["down/app"] = "HTTP 403 em api.github.com"
    auth = {"basis": "license", "evidence": "e"}
    cfgp = write_cfg(tmp_path, sources=[
        {"id": "down", "type": "github-releases", "repo": "down/app", "authorization": auth},
        {"id": "off", "type": "github-releases", "repo": "off/app", "enabled": False, "authorization": auth},
        {"id": "ok", "type": "github-releases", "repo": "ok/app", "authorization": auth}])
    r = go(tmp_path, net, cfgp)
    st = {s["source"]: s["status"] for s in r.report["sources"]}
    assert st == {"down": "erro", "off": "desativada", "ok": "ok"} and r.published == 1


def test_zero_publishable_keeps_previous_artifact(tmp_path):
    net = FakeNet()
    u = H + "a.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    cfgp = write_cfg(tmp_path)
    go(tmp_path, net, cfgp)
    before = (tmp_path / "out/auto.gssource").read_bytes()
    net.files[u] = make_pkg("NPXS39041")             # o pacote passa a ser recusado
    r = go(tmp_path, net, cfgp)
    assert not r.wrote_catalog and (tmp_path / "out/auto.gssource").read_bytes() == before


def test_dry_run_writes_nothing(tmp_path):
    net = FakeNet()
    u = H + "a.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    r = go(tmp_path, net, write_cfg(tmp_path), dry_run=True)
    assert r.wrote_catalog and not (tmp_path / "out").exists() and not (tmp_path / "state.json").exists()


def test_cli_run_single_command(tmp_path, capsys):
    net = FakeNet()
    u = H + "a.pkg"
    net.files[u] = make_pkg()
    net.release("acme/app", 1, "v1", [("a.pkg", u, len(BASE_PKG))])
    cfgp = write_cfg(tmp_path)
    argv = ["run", "--config", str(cfgp), "--out-dir", str(tmp_path / "o"), "--canonical", str(tmp_path / "c.json"),
            "--state", str(tmp_path / "s.json")]
    assert main(argv, net=net) == 0
    out = capsys.readouterr().out
    assert "publicados=1" in out and "NOVO" in out and "catálogo atualizado" in out
    assert main(["check", str(tmp_path / "o/ps4storebr-auto.gssource")]) == 0
    assert main(argv, net=net) == 0
    assert "novos=0" in capsys.readouterr().out


# ---------------------------------------------------------------- conector do GitHub (formato real da API)

def test_github_connector_filters_drafts_prereleases_and_non_pkg():
    net = FakeNet()
    net.release("a/b", 1, "v1", [("x.pkg", H + "x.pkg", 5), ("x.zip", H + "x.zip", 5)])
    net.release("a/b", 2, "v2", [("y.PKG", H + "y.pkg", 5)], prerelease=True)
    src = Source("s", "github-releases", "a/b", True, False, 10, "license", "e")
    assert [f.asset_name for f in discover_github(src, net)] == ["x.pkg"]
    src.include_prereleases = True
    assert sorted(f.asset_name for f in discover_github(src, net)) == ["x.pkg", "y.PKG"]


# ---------------------------------------------------------------- rede real (servidor HTTP local, com Range)

class _H(http.server.BaseHTTPRequestHandler):
    body = bytes(range(256)) * 4096                       # 1 MiB
    honor_range = True

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302); self.send_header("Location", "/file"); self.end_headers(); return
        if self.path == "/redir-http":
            self.send_response(302); self.send_header("Location", "http://example.com/x"); self.end_headers(); return
        if self.path == "/404":
            self.send_response(404); self.end_headers(); return
        if self.path == "/html":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b"<html>"); return
        if self.path == "/json":
            b = b'{"a":1}'; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.headers_seen = dict(self.headers)
        _H.last_auth = self.headers.get("Authorization")
        rng = self.headers.get("Range")
        if rng and _H.honor_range:
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), min(int(b), len(self.body) - 1)
            chunk = self.body[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(self.body)}")
        else:
            chunk = self.body
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        try:
            self.wfile.write(chunk)
        except OSError:
            pass


@pytest.fixture()
def server():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_urllib_probe_range_total_redirect_and_limits(server):
    net = UrllibNet(allow_insecure=True, timeout=5)
    p = net.probe(server + "/file", 65536)
    assert (p.ok, p.status, p.total_size, len(p.head)) == (True, 206, 1 << 20, 65536)
    r = net.probe(server + "/redir")
    assert r.ok and r.redirects == 1 and r.final_url.endswith("/file")
    _H.honor_range = False                                 # servidor ignora Range: ainda lemos só 64 KiB
    try:
        q = net.probe(server + "/file", 65536)
        assert (q.status, q.total_size, len(q.head)) == (200, 1 << 20, 65536)
    finally:
        _H.honor_range = True
    assert net.probe(server + "/404").status == 404
    assert net.probe(server + "/html").content_type == "text/html"
    assert net.get_json(server + "/json") == {"a": 1}


def test_urllib_security_rules(server):
    strict = UrllibNet()
    assert "esquema" in strict.probe(server + "/file").error                      # http recusado
    assert not strict.probe("https://127.0.0.1/x").ok                             # loopback recusado
    assert not strict.probe("https://192.168.0.10/x").ok
    assert "credenciais" in strict.probe("https://user:pw@example.com/x").error
    loose = UrllibNet(allow_insecure=True)
    assert loose.probe(server + "/file").ok                                        # modo de teste libera http local
    with pytest.raises(NetError):
        strict.get_json("ftp://example.com/x")


def test_token_is_not_sent_to_download_hosts(server):
    net = UrllibNet(allow_insecure=True, token="segredo")
    net.probe(server + "/file")
    assert _H.last_auth is None
