"""Conector github-contents: PKGs numa pasta de repositório autorizado (download pelo raw.githubusercontent.com)."""
import json
import zipfile

import pytest

from ps4store import sspi
from ps4store.discover import ConfigError, load_config, run
from test_gate3 import BASE_PKG, NOW, FakeNet, make_pkg

RAW = "https://raw.githubusercontent.com/acme/app/main/pkgs/"


class Repo(FakeNet):
    def __init__(self):
        super().__init__()
        self.dir = []                                   # entradas da API Contents

    def put(self, name, data, sha, type="file"):
        url = RAW + name
        self.files[url] = data
        self.dir = [d for d in self.dir if d["name"] != name]
        self.dir.append({"name": name, "path": "pkgs/" + name, "sha": sha, "size": len(data), "type": type,
                         "html_url": f"https://github.com/acme/app/blob/main/pkgs/{name}", "download_url": url})

    def get_json(self, url):
        assert "/repos/acme/app/contents/pkgs" in url
        return self.dir


def cfg(tmp_path, **kw):
    src = {"id": "own", "type": "github-contents", "repo": "acme/app", "path": "pkgs",
           "authorization": {"basis": "license", "evidence": "software do próprio autor"}}
    src.update(kw)
    tls = {"enforce": True, "known_bad_hosts": {"github.com": "x"}, "untested_hosts": {"raw.githubusercontent.com": "T8 pendente"}}
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": "ps4storebr.sources/v1", "catalog": {"id": "t", "name": "T"}, "tls": tls, "sources": [src]}))
    return p


def go(tmp_path, net, p):
    return run(load_config(p), net, out_gssource=tmp_path / "o/a.gssource", out_canonical=tmp_path / "o/c.json",
               out_report=tmp_path / "o/r.json", state_path=tmp_path / "st.json", now=NOW)


def test_new_file_in_authorized_folder_is_discovered_verified_and_published(tmp_path):
    net = Repo()
    net.put("app-a.pkg", make_pkg("CUSA95701"), "a" * 40)
    p = cfg(tmp_path)
    r1 = go(tmp_path, net, p)
    assert (r1.report["counts"]["novos"], r1.published) == (1, 1)
    e = r1.report["entries"][0]
    assert e["fase"] == "PUBLICAVEL" and e["titleId"] == "CUSA95701" and e["url"] == RAW + "app-a.pkg"
    assert any("raw.githubusercontent.com: TLS não confirmado" in w for w in e["warnings"])     # aviso, não bloqueio

    net.put("app-b.pkg", make_pkg("CUSA95702"), "b" * 40)           # arquivo novo na pasta, sem tocar na config
    net.put("LEIA.md", b"x", "c" * 40)
    net.put("subpasta", b"", "d" * 40, type="dir")
    r2 = go(tmp_path, net, p)
    assert [(x["titleId"], x["isNew"]) for x in r2.report["entries"]] == [("CUSA95701", False), ("CUSA95702", True)]
    z = zipfile.ZipFile(tmp_path / "o/a.gssource")
    assert sorted(t["titleId"] for t in json.loads(z.read("index/titles.json"))["titles"]) == ["CUSA95701", "CUSA95702"]
    assert sspi.check_archive((tmp_path / "o/a.gssource").read_bytes()).ok


def test_changed_content_same_name_is_a_new_discovery(tmp_path):
    net = Repo()
    net.put("app.pkg", make_pkg("CUSA95701"), "a" * 40)
    p = cfg(tmp_path)
    go(tmp_path, net, p)
    net.put("app.pkg", make_pkg("CUSA95701", title="App atualizado"), "f" * 40)   # nova versão do mesmo arquivo
    r = go(tmp_path, net, p)
    assert r.report["counts"]["novos"] == 1 and r.report["entries"][0]["name"] == "App atualizado"


def test_contents_source_needs_authorization_and_path(tmp_path):
    r = go(tmp_path, (lambda n: (n.put("x.pkg", make_pkg("CUSA95701"), "a" * 40), n)[1])(Repo()), cfg(tmp_path, authorization=None))
    assert r.published == 0 and r.report["entries"][0]["reason"] == "NO_AUTHORIZATION"
    with pytest.raises(ConfigError, match="path"):
        load_config(cfg(tmp_path, path=""))


def test_contents_pkg_with_rejected_id_stays_verified_not_published(tmp_path):
    net = Repo()
    net.put("store.pkg", make_pkg("NPXS39041"), "a" * 40)
    r = go(tmp_path, net, cfg(tmp_path))
    e = r.report["entries"][0]
    assert (e["fase"], e["reason"]) == ("VERIFICADO", "PREFIX_REJECTED_BY_SSPI") and not r.wrote_catalog


def test_one_version_per_id_latest_wins_and_catalog_updates_without_url_registration(tmp_path):
    """Alteração na pasta monitorada: o arquivo novo (versão maior) substitui o anterior; o ID não é duplicado."""
    net = Repo()
    old = make_pkg("CUSA95801", title="App Teste")
    net.put("app-v1.00.pkg", old, "a" * 40)
    p = cfg(tmp_path)
    r1 = go(tmp_path, net, p)
    assert r1.published == 1
    v1 = json.loads((tmp_path / "o/c.json").read_text())["source"]["version"]

    new = bytearray(make_pkg("CUSA95801", title="App Teste"))
    i = new.index(b"1.00\x00")                       # param.sfo: APP_VER/VERSION 1.00 -> 1.01 (só no teste)
    while i != -1 and i < 65536:
        new[i:i + 4] = b"1.01"
        i = new.find(b"1.00\x00", i + 1)
    net.put("app-v1.01.pkg", bytes(new), "b" * 40)   # arquivo novo na pasta: ninguém cadastra a URL
    r2 = go(tmp_path, net, p)
    by = {e["asset"]: e for e in r2.report["entries"]}
    assert by["app-v1.01.pkg"]["isNew"] and by["app-v1.01.pkg"]["fase"] == "PUBLICAVEL"
    assert (by["app-v1.00.pkg"]["fase"], by["app-v1.00.pkg"]["reason"]) == ("VERIFICADO", "SUPERSEDED")
    z = zipfile.ZipFile(tmp_path / "o/a.gssource")
    rows = json.loads(z.read("packages/items.json"))["titles"]["CUSA95801"]
    assert len(rows) == 1 and rows[0]["url"].endswith("app-v1.01.pkg") and rows[0]["version"] == "1.01"
    assert json.loads(z.read("index/titles.json"))["titles"][0]["releaseCount"] == 1
    assert json.loads((tmp_path / "o/c.json").read_text())["source"]["version"] != v1      # versão do catálogo sobe
