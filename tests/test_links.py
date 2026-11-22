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


RAR5 = b"Rar!\x1a\x07\x01\x00" + b"\x00" * 600


def test_multipart_rar_parts_are_probed_ordered_and_summarized(tmp_path):
    net = Repo()
    for i in (1, 2, 10, 3):                                   # ordem de listagem embaralhada; 10 > 2 (ordem numérica)
        net.put(f"jogo.part{i:02d}.rar", RAR5, f"{i:040d}")
    net.put("app.pkg", make_pkg("CUSA95701"), "c" * 40)
    r = go(tmp_path, net, contents_cfg(tmp_path))
    by = {e["asset"]: e for e in r.report["entries"]}
    p1 = by["jogo.part01.rar"]
    assert (p1["reason"], p1["fileType"], p1["stage"], p1["fase"]) == ("ARCHIVE_MULTIPART", "rar-multiparte", "acessivel", "DESCOBERTO")
    assert "Gate 5" in p1["detail"] and p1["link"]["rangeOk"]
    st = r.report["rarSets"][0]
    assert st["indexes"] == [1, 2, 3, 10] and st["missing"] == [4, 5, 6, 7, 8, 9] and not st["complete"]      # faltam partes
    assert by["app.pkg"]["fase"] == "PUBLICAVEL" and net.probes == 5                                           # 4 partes + 1 pkg, 64 KiB cada


def test_complete_rar_set_goes_to_the_personal_list_in_order_and_bad_magic_is_flagged(tmp_path):
    net = Repo()
    for i in (3, 1, 2):
        net.put(f"g.part{i}.rar", RAR5, f"{i:040d}")
    net.put("h.part1.rar", b"<html>nope" + b"0" * 600, "f" * 40)
    r = go(tmp_path, net, contents_cfg(tmp_path))
    sets = {x["set"]: x for x in r.report["rarSets"]}
    g = sets["g.part*.rar"]
    assert g["complete"] and g["volumes"] == 3 and [p["index"] for p in g["parts"]] == [1, 2, 3]
    assert [e["reason"] for e in r.report["entries"] if e["asset"] == "h.part1.rar"] == ["NOT_RAR"]
    txt = (tmp_path / "loc/links-sspi.txt").read_text().splitlines()
    i = [n for n, l in enumerate(txt) if l.startswith("# RAR dividido g.part*.rar")][0]
    assert [u.rsplit("/", 1)[1] for u in txt[i + 1:i + 4]] == ["g.part1.rar", "g.part2.rar", "g.part3.rar"]
    assert not any("h.part1.rar" in l for l in txt)


def test_param_sfo_beyond_the_first_window_is_read_with_one_small_extra_range(tmp_path):
    base = bytearray(make_pkg("CUSA95902"))
    from ps4store.pkginfo import parse_head
    import struct
    # move param.sfo (e a tabela) para depois dos 64 KiB, como nos PKGs grandes reais
    tab = struct.unpack_from(">I", base, 0x18)[0]
    cnt = struct.unpack_from(">I", base, 0x10)[0]
    for i in range(cnt):
        eid, fn, f1, f2, off, size = struct.unpack_from(">IIIIII", base, tab + i * 32)
        if eid == 0x1000:
            sfo = bytes(base[off:off + size])
            new_off = 200_000
            base[new_off:new_off + size] = sfo
            struct.pack_into(">I", base, tab + i * 32 + 16, new_off)
    net = Repo()
    net.put("big.pkg", bytes(base), "a" * 40)
    with pytest.raises(Exception):
        parse_head(bytes(base[:65536]))                       # sem a 2ª faixa não dá
    r = go(tmp_path, net, contents_cfg(tmp_path))
    e = r.report["entries"][0]
    assert e["titleId"] == "CUSA95902" and e["fase"] == "PUBLICAVEL" and net.probes == 2     # 64 KiB + uma faixa pequena


def test_probe_title_forces_reprobe_of_just_that_title_ignoring_cache(tmp_path):
    z = Zone()
    for t in ("MOZI00001", "MOZI00002", "MOZI00003"):
        z.add(t, t)
    cfgp = zone_cfg(tmp_path, recheck_hours=720)
    go(tmp_path, z, cfgp)
    p0 = z.probes
    go(tmp_path, z, cfgp, now="2026-11-22T13:00:00Z", force_titles=frozenset({"MOZI00002"}))
    assert z.probes - p0 == 1


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


def test_restricted_is_flagged_even_when_the_item_is_rejected_earlier_by_prefix(tmp_path):
    z = Zone()
    data = retail_pkg("MOZI00009", pub="UP9000")             # ID não-CUSA (rejeitado por prefixo) com Content ID UP9000-
    z.items.append(pz.item("MOZI00009", "Port com Content ID de aparência comercial", size=len(data)))
    z.files[f"{BASE}/download/ps4/MOZI00009/1.0.0"] = data
    r = go(tmp_path, z, zone_cfg(tmp_path))
    e = r.report["entries"][0]
    assert e["reason"] == "PREFIX_UNPROVEN" and e["restricted"] is True
    assert "MOZI00009" not in (tmp_path / "loc/links-sspi.txt").read_text()          # fora da lista pessoal, presente na pesquisa
