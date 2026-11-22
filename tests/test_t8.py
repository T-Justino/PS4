"""T8: app próprio PS4 Store BR Test, com ID do catálogo == ID real do pacote (sem chave sintética)."""
import importlib.util
import json
from pathlib import Path

import pytest

from ps4store import sspi
from ps4store.catalog import CatalogError, load
from ps4store.cli import main

ROOT = Path(__file__).parent.parent
FIX = ROOT / "data/fixtures/t8/t8-cusa95417-ps4storebr-test.json"
PKG = ROOT / "dist/t8/IV0000-CUSA95417_00-PS4STOREBRTEST00.pkg"
GSS = ROOT / "dist/t8/ps4storebr-t8-cusa95417.gssource"

spec = importlib.util.spec_from_file_location("verify_pkg", ROOT / "app/verify_pkg.py")
verify_pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_pkg)

OLD_SYNTHETIC = {"CUSA99999", "CUSA90001", "CUSA90002", "CUSA90003", "CUSA90004"}


def test_t8_builds_without_synthetic_flag_and_passes_check(tmp_path):
    out = tmp_path / "x.gssource"
    assert main(["build", str(FIX), "-o", str(out)]) == 0          # sem --allow-synthetic-probe
    assert main(["check", str(out)]) == 0                          # sem --allow-placeholder


def test_t8_is_not_a_synthetic_key_and_does_not_reuse_old_ones():
    cat = load(FIX)                                                # allow_synthetic=False
    [t] = cat.titles
    assert not t.catalog_key and not t.probe and t.real_title_id is None
    assert t.title_id == "CUSA95417" and t.title_id not in OLD_SYNTHETIC
    assert not sspi.is_placeholder_id(t.title_id)


def test_catalog_id_equals_package_identity():
    info = verify_pkg.read_pkg(str(PKG))
    cid = info["headerContentId"]
    m = sspi.CONTENT_ID_RE.match(cid)
    assert m, cid
    cat = load(FIX)
    pkg = cat.titles[0].packages[0]
    assert pkg.extra["contentId"] == cid                           # catálogo == cabeçalho do PKG
    assert m.group(1) == cat.titles[0].title_id == info["sfo"]["TITLE_ID"]   # catálogo == Content ID == param.sfo
    assert info["sfo"]["CONTENT_ID"] == cid
    assert info["sfo"]["TITLE"] == "PS4 Store BR Test"
    assert info["sfo"]["CATEGORY"] == "gd"


def test_gssource_artifact_matches_fixture_and_published_pkg_path():
    from zipfile import ZipFile
    z = ZipFile(GSS)
    idx = json.loads(z.read("index/titles.json"))["titles"]
    rows = json.loads(z.read("packages/items.json"))["titles"]
    assert [t["titleId"] for t in idx] == ["CUSA95417"] and list(rows) == ["CUSA95417"]
    [row] = rows["CUSA95417"]
    assert "NPXS" not in z.read("index/titles.json").decode()
    assert row["url"].startswith("https://") and row["url"].endswith(PKG.name)
    assert (ROOT / "dist/t8" / row["url"].rsplit("/", 1)[1]).exists()   # o arquivo publicado existe no repo
    assert sspi.check_archive(GSS.read_bytes()).ok


def test_verify_pkg_cli_ok_and_detects_tampering(tmp_path, capsys):
    assert verify_pkg.main.__module__ == "verify_pkg"
    data = bytearray(PKG.read_bytes())
    data[0x40 + 10] ^= 0x01                                        # corrompe 1 byte do Content ID do cabeçalho
    bad = tmp_path / "bad.pkg"
    bad.write_bytes(bytes(data))
    import sys
    sys.argv = ["verify_pkg", str(bad)]
    assert verify_pkg.main() == 1
    sys.argv = ["verify_pkg", str(PKG), "--title-id", "CUSA95417"]
    assert verify_pkg.main() == 0
    sys.argv = ["verify_pkg", str(PKG), "--title-id", "CUSA90004"]
    assert verify_pkg.main() == 1


def test_verify_pkg_rejects_non_pkg(tmp_path):
    f = tmp_path / "x.pkg"
    f.write_bytes(b"\x00" * 2048)
    with pytest.raises(ValueError, match="magic"):
        verify_pkg.read_pkg(str(f))


def test_content_id_mismatch_blocks_t8_like_catalog():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    d["titles"][0]["packages"][0]["contentId"] = "IV0000-NPXS39041_00-PS4STOREBRTEST00"
    from ps4store.catalog import parse
    with pytest.raises(CatalogError, match="não a CUSA95417"):
        parse(d)
