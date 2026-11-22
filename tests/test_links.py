"""Classificação de links, restrições, multipartes, duplicados, cache incremental e saídas de pesquisa (uso pessoal)."""
import json
from pathlib import Path

import pytest

from ps4store.discover import load_config, run
from ps4store.links import classify_link, file_type, is_retail_style, multipart_info
from ps4store.net import Probe, UrllibNet
from test_gate3 import BASE_PKG, NOW, FakeNet, make_pkg
from test_contents import Repo, cfg as contents_cfg
from test_pkgzone import BASE, Zone, cfg_file as zone_cfg
import test_gate3 as g3
import test_pkgzone as pz


def P(**kw):
    d = dict(ok=True, status=206, total_size=100, head=b"", final_url="https://x/f", content_type="application/octet-stream",
             redirects=0, range_ok=True, chain=["x"])
    d.update(kw)
    return Probe(**d)


# ---------------------------------------------------------------- classificação (regras do baixador do SSPI)
def test_classify_direct_redirect_signed_and_range():
    assert classify_link(P())["kind"] == "direto" and classify_link(P())["sspiUsable"]
    r = classify_link(P(redirects=1, signed=True, chain=["a", "b"]))
    assert (r["kind"], r["temporaryFinalUrl"], r["sspiUsable"]) == ("redirect", True, True)
    assert any("URL estável" in n for n in r["notes"])
    one = classify_link(P(status=200, range_ok=False))
    assert one["sspiUsable"] and one["singleLane"] and any("uma conexão" in n for n in one["notes"])
    assert not classify_link(P(content_encoding="gzip"))["sspiUsable"]               # o SSPI exige identity
    assert not classify_link(P(status=200, range_ok=False, total_size=None))["sspiUsable"]


@pytest.mark.parametrize("pr,kind", [
    (Probe(False, 404, "HTTP 404"), "removido"), (Probe(False, 410, "HTTP 410"), "removido"),
    (Probe(False, 401, "HTTP 401"), "exige-autenticacao"), (Probe(False, 403, "HTTP 403"), "exige-autenticacao"),
    (Probe(False, 403, "HTTP 403", signed=True), "expirado"), (Probe(False, None, "falha de rede"), "erro-de-rede"),
    (Probe(False, 500, "HTTP 500"), "erro-http"), (P(content_type="text/html"), "pagina-intermediaria")])
def test_classify_failures(pr, kind):
    c = classify_link(pr)
    assert c["kind"] == kind and not c["sspiUsable"]


def test_multipart_and_file_types():
    assert multipart_info("Game-CUSA12345.part1.rar") == {"style": "part-rar", "set": "Game-CUSA12345.part*.rar", "index": 1}
    assert multipart_info("g.part02.rar")["index"] == 2 and multipart_info("g.r00")["style"] == "old-rar"
    assert multipart_info("g.pkg") is None and multipart_info("g.rar") is None
    assert [file_type(n) for n in ("a.pkg", "a.part1.rar", "a.rar", "a.7z", "a.zip", "a.bin")] == \
        ["pkg", "rar-multiparte", "rar", "7z", "zip", "desconhecido"]


def test_retail_style():
    assert is_retail_style("UP4381-CUSA18680_00-YOUTUBETVSCEA000") and is_retail_style("EP4350-CUSA00127_00-NETFLIXPOLLUX001")
    assert not is_retail_style("IV0000-CUSA95417_00-PS4STOREBRTEST00") and not is_retail_style("TX0000-BREW69420_00-BREWSTORE0000000")
    assert is_retail_style("IV0000-X", "media") and not is_retail_style(None)


# ---------------------------------------------------------------- rede real local: cabeçalhos e cadeia
def test_urllib_probe_reports_range_encoding_etag_chain_and_signed(server=None):
    import http.server, threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == "/go":
                self.send_response(302); self.send_header("Location", "/file?exp=123&sig=abc"); self.end_headers(); return
            body = b"x" * 5000
            self.send_response(206); self.send_header("Content-Range", f"bytes 0-1023/{len(body)}")
            self.send_header("Content-Length", "1024"); self.send_header("ETag", '"e"'); self.send_header("Content-Type", "application/octet-stream")
            self.end_headers(); self.wfile.write(body[:1024])

    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        p = UrllibNet(allow_insecure=True, timeout=5).probe(f"http://127.0.0.1:{s.server_port}/go", 1024)
        assert p.ok and p.range_ok and p.signed and p.redirects == 1 and len(p.chain) == 2 and p.etag == '"e"' and p.total_size == 5000
        c = classify_link(p)
        assert c["kind"] == "redirect" and c["temporaryFinalUrl"] and c["sspiUsable"]
    finally:
        s.shutdown()


# ---------------------------------------------------------------- pipeline: restrito, multiparte, duplicados, pesquisa
def go(tmp_path, net, cfgp, **kw):
    return run(load_config(cfgp), net, out_gssource=tmp_path / "o/a.gssource", out_canonical=tmp_path / "o/c.json",
               out_report=tmp_path / "o/r.json", state_path=tmp_path / "st.json", now=kw.pop("now", NOW),
               sleep=lambda s: None, out_research=tmp_path / "loc/research.json", **kw)


def retail_pkg(title="CUSA95601", pub="UP4381"):
    d = bytearray(make_pkg(title))
    i = d.index(b"IV0000-" + title.encode())
    d[i:i + 6] = pub.encode()
    j = d.find(b"IV0000-", i + 1)
    while j != -1 and j < 65536:
        d[j:j + 6] = pub.encode(); j = d.find(b"IV0000-", j + 1)
    return bytes(d)


def test_retail_style_never_published_even_with_source_authorization_but_item_authorization_can(tmp_path):
    z = Zone()
    data = retail_pkg()
    z.items.append(pz.item("CUSA95601", "App de streaming", size=len(data), extra={"category": "media"}))
    z.files[f"{BASE}/download/ps4/CUSA95601/1.0.0"] = data
    ok = {"basis": "license", "evidence": "e"}
    r = go(tmp_path, z, zone_cfg(tmp_path, authorization=ok))                     # autorização da FONTE inteira
    e = r.report["entries"][0]
    assert (e["reason"], e["restricted"], e["fase"]) == ("RETAIL_STYLE_ID", True, "VERIFICADO") and not r.wrote_catalog
    r = go(tmp_path, z, zone_cfg(tmp_path, authorized_titles={"CUSA95601": ok}), now="2026-11-23T00:00:00Z")   # por ITEM
    assert r.published == 1


def test_personal_list_has_non_cusa_homebrew_but_not_restricted_and_never_the_public_catalog(tmp_path):
    z = Zone()
    z.add("MOZI00001", "Homebrew com ID não-CUSA")                                # o catálogo recusaria; o SSPI baixa por link
    z.add("NPXS39041", "Outro homebrew")
    z.add("CUSA95602", "CUSA sem autorização")
    data = retail_pkg("CUSA95603")
    z.items.append(pz.item("CUSA95603", "Streaming", size=len(data), extra={"category": "media"}))
    z.files[f"{BASE}/download/ps4/CUSA95603/1.0.0"] = data
    r = go(tmp_path, z, zone_cfg(tmp_path))
    assert not r.wrote_catalog and not (tmp_path / "o/a.gssource").exists()      # catálogo público: nada publicável
    txt = (tmp_path / "loc/links-sspi.txt").read_text()
    assert f"{BASE}/download/ps4/MOZI00001/1.0.0" in txt and f"{BASE}/download/ps4/NPXS39041/1.0.0" in txt
    assert f"{BASE}/download/ps4/CUSA95602/1.0.0" in txt
    assert "CUSA95603" not in txt and "USO PESSOAL" in txt and "sig=" not in txt  # restrito fora; URL assinada nunca
    rows = {x["titleId"]: x for x in json.loads((tmp_path / "loc/research.json").read_text())["entries"]}
    assert set(rows) == {"MOZI00001", "NPXS39041", "CUSA95602", "CUSA95603"}   # nada é descartado na pesquisa
    m = rows["MOZI00001"]
    assert (m["fileType"], m["linkStatus"], m["sspiDownloadable"], m["rejectionReason"], m["temporaryRedirect"]) == \
        ("pkg", "redirect", True, "PREFIX_UNPROVEN", True)
    assert rows["CUSA95603"]["restricted"] and rows["CUSA95603"]["sspiDownloadable"]      # baixável tecnicamente, mas fora de qualquer lista


def test_multipart_rar_is_discovered_and_reported_not_probed(tmp_path):
    net = Repo()
    net.put("jogo.part1.rar", b"Rar!", "a" * 40)
    net.put("jogo.part2.rar", b"Rar!", "b" * 40)
    net.put("app.pkg", make_pkg("CUSA95701"), "c" * 40)
    r = go(tmp_path, net, contents_cfg(tmp_path))
    by = {e["asset"]: e for e in r.report["entries"]}
    assert by["jogo.part1.rar"]["reason"] == "ARCHIVE_MULTIPART" and by["jogo.part1.rar"]["fileType"] == "rar-multiparte"
    assert by["jogo.part1.rar"]["fase"] == "DESCOBERTO" and "Gate 5" in by["jogo.part1.rar"]["detail"]
    assert by["app.pkg"]["fase"] == "PUBLICAVEL" and net.probes == 1               # só o .pkg foi sondado


def test_duplicate_same_file_in_two_places_is_marked(tmp_path):
    net = Repo()
    d = make_pkg("CUSA95801")
    net.put("a.pkg", d, "a" * 40)
    net.put("copia.pkg", d, "b" * 40)
    r = go(tmp_path, net, contents_cfg(tmp_path))
    dup = [e for e in r.report["entries"] if e["duplicateOf"]]
    assert len(dup) == 1 and r.report["counts"]["duplicados"] == 1 and r.published == 1


def test_refresh_links_enriches_cached_entries_incrementally_without_mass_probe(tmp_path):
    z = Zone()
    for i in range(6):
        z.add(f"MOZI0000{i}", f"HB {i}")
    cfgp = zone_cfg(tmp_path, recheck_hours=720)
    go(tmp_path, z, cfgp)
    st = json.loads((tmp_path / "st.json").read_text())
    for rec in st["seen"].values():                         # simula cache antigo, sem dados de link
        rec["check"].pop("link", None)
    (tmp_path / "st.json").write_text(json.dumps(st))
    p0 = z.probes
    r = go(tmp_path, z, cfgp, now="2026-11-22T13:00:00Z", refresh_links=2)
    assert z.probes - p0 == 2 and r.report["counts"]["links"]["classificados"] == 2
    r = go(tmp_path, z, cfgp, now="2026-11-22T14:00:00Z", refresh_links=2)
    assert z.probes - p0 == 4 and r.report["counts"]["links"]["classificados"] == 4   # avança de 2 em 2


def test_personal_list_excludes_hosts_with_known_tls_failure_even_if_rejected_earlier(tmp_path):
    net = Repo()
    net.put("a.pkg", make_pkg("NPXS39041"), "a" * 40)               # ID recusado pelo catálogo → rejeitado antes da checagem de TLS
    net.files["https://github.com/acme/app/releases/download/v1/b.pkg"] = make_pkg("APOL00004")
    net.dir.append({"name": "b.pkg", "path": "pkgs/b.pkg", "sha": "b" * 40, "size": len(BASE_PKG), "type": "file",
                    "html_url": "x", "download_url": "https://github.com/acme/app/releases/download/v1/b.pkg"})
    cfgp = contents_cfg(tmp_path)
    cfgd = json.loads(cfgp.read_text()); cfgd["tls"]["known_bad_hosts"] = {"github.com": "TLS 0x8095F00C"}
    cfgp.write_text(json.dumps(cfgd))
    go(tmp_path, net, cfgp)
    txt = (tmp_path / "loc/links-sspi.txt").read_text()
    assert "raw.githubusercontent.com" in txt and "github.com/acme/app/releases" not in txt
