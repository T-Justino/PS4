import copy
import json
from pathlib import Path

import pytest

from ps4store import sspi
from ps4store.build import compile_catalog, search_text, zip_files
from ps4store.catalog import CatalogError, normalize_search, parse
from ps4store.cli import main

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "tests/fixtures/sspi_compat_5117_original.gssource"
FIXTURES = sorted((ROOT / "data/fixtures/probes").glob("*.json"))   # sondas históricas T4–T7


def base_doc(**title_over):
    """Catálogo sintético SÓ para testes (ID não-placeholder, nunca publicado)."""
    t = {
        "titleId": "TEST12345", "identityEvidence": "teste unitário", "name": "Jogo Ação",
        "aliases": ["acao"], "languages": {"audioPtBr": "unknown", "subtitlesPtBr": "unknown"},
        "packages": [{
            "id": "p1", "kind": "base", "accessType": "Direct",
            "url": "https://example.org/a.pkg", "hoster": "Example", "label": "L",
            "authorization": {"basis": "license", "evidence": "MIT"}}],
    }
    t.update(title_over)
    return {"schema": "ps4storebr.catalog/v1",
            "source": {"id": "test.src", "name": "Teste", "description": "", "version": "1.0.0"},
            "titles": [t]}


def build_bytes(doc):
    files, rep = compile_catalog(parse(doc, allow_synthetic=True))
    return files, rep, zip_files(files)


# ---------- contrato com o fixture aceito pelo console

def test_original_fixture_passes_check():
    res = sspi.check_archive(ORIGINAL.read_bytes(), allow_placeholder_ids=True)
    assert res.ok, res.errors


def test_original_fixture_placeholder_rejected_by_default():
    res = sspi.check_archive(ORIGINAL.read_bytes())
    assert any("placeholder" in e for e in res.errors)


def test_serializer_reproduces_original_bytes():
    files = sspi.read_archive(ORIGINAL.read_bytes())
    for path, data in files.items():
        assert sspi.dumps(json.loads(data)) == data, path


def test_generated_structure_matches_original_keys():
    orig = {p: json.loads(b) for p, b in sspi.read_archive(ORIGINAL.read_bytes()).items()}
    gen = {p: json.loads(b) for p, b in compile_catalog(parse(base_doc()))[0].items()}
    assert list(gen) == list(orig)                                  # nomes e ordem dos arquivos
    assert list(gen["source.json"]) == list(orig["source.json"])
    assert gen["source.json"]["engine"] == orig["source.json"]["engine"]
    assert gen["source.json"]["capabilities"] == orig["source.json"]["capabilities"]
    assert list(gen["catalog.json"]) == list(orig["catalog.json"])
    assert list(gen["index/titles.json"]["titles"][0]) == list(orig["index/titles.json"]["titles"][0])
    o_row = next(iter(orig["packages/items.json"]["titles"].values()))[0]
    g_row = next(iter(gen["packages/items.json"]["titles"].values()))[0]
    assert list(g_row)[:5] == list(o_row)[:5]


# ---------- fixtures reais

@pytest.mark.parametrize("fx", FIXTURES, ids=lambda p: p.stem)
def test_real_fixtures_build_and_check(fx):
    doc = json.loads(fx.read_text(encoding="utf-8"))
    files, rep, data = build_bytes(doc)
    res = sspi.check_archive(data, allow_placeholder_ids=True)  # T4 usa chave fictícia CUSA99999
    assert res.ok, res.errors
    assert not rep.excluded
    for t in doc["titles"]:
        assert t["titleId"] in rep.published_titles


@pytest.mark.parametrize("fx", FIXTURES, ids=lambda p: p.stem)
def test_build_is_byte_reproducible(fx):
    doc = json.loads(fx.read_text(encoding="utf-8"))
    assert build_bytes(doc)[2] == build_bytes(copy.deepcopy(doc))[2]


def test_fixture_source_ids_are_distinct():
    ids = [json.loads(f.read_text())["source"]["id"] for f in FIXTURES]
    assert len(ids) == len(set(ids)) >= 1


# ---------- regras de política do canônico

@pytest.mark.parametrize("tid", ["CUSA99999", "APOL00000"])
def test_placeholder_ids_rejected(tid):
    with pytest.raises(CatalogError, match="placeholder"):
        parse(base_doc(titleId=tid))


@pytest.mark.parametrize("tid", ["PPSA01234", "CUSA1234", "cusa12345", "CUSA-12345", ""])
def test_invalid_ids_rejected(tid):
    with pytest.raises(CatalogError):
        parse(base_doc(titleId=tid))


def test_duplicate_title_rejected():
    doc = base_doc()
    doc["titles"].append(copy.deepcopy(doc["titles"][0]))
    with pytest.raises(CatalogError, match="duplicado"):
        parse(doc)


def test_ptbr_yes_without_evidence_rejected():
    with pytest.raises(CatalogError, match="evidence"):
        parse(base_doc(languages={"audioPtBr": "yes", "subtitlesPtBr": "unknown"}))


def test_ptbr_unknown_adds_no_ptbr_terms():
    t = parse(base_doc()).titles[0]
    assert "ptbr" not in search_text(t)


def test_ptbr_confirmed_adds_terms():
    doc = base_doc(languages={"audioPtBr": "yes", "subtitlesPtBr": "yes", "evidence": "https://ex.org"})
    st = search_text(parse(doc).titles[0])
    assert "dublado" in st and "legendado" in st


@pytest.mark.parametrize("url", ["http://example.org/a.pkg", "https://user:pw@example.org/a.pkg",
                                 "https://127.0.0.1/a.pkg", "https://localhost/a.pkg",
                                 "file:///etc/passwd", "javascript:alert(1)", "https:///a.pkg"])
def test_unsafe_urls_rejected(url):
    doc = base_doc()
    doc["titles"][0]["packages"][0]["url"] = url
    with pytest.raises(CatalogError):
        parse(doc)


def test_rar_volumes_disabled_until_gate5():
    doc = base_doc()
    doc["titles"][0]["packages"][0]["volumes"] = [{"url": "https://e.org/a.part1.rar"}]
    with pytest.raises(CatalogError, match="Gate 5"):
        parse(doc)


def test_unauthorized_package_excluded_and_title_without_link_excluded():
    doc = base_doc()
    meta_only = copy.deepcopy(doc["titles"][0])
    meta_only.update(titleId="META00001", packages=[])                 # só metadados
    no_auth = copy.deepcopy(doc["titles"][0])
    no_auth["titleId"] = "NOAU00001"
    del no_auth["packages"][0]["authorization"]
    doc["titles"] += [meta_only, no_auth]
    files, rep, data = build_bytes(doc)
    assert rep.published_titles == ["TEST12345"]
    reasons = {(e["titleId"], e["reason"].split()[0]) for e in rep.excluded}
    assert ("META00001", "SEM_PACOTE_PUBLICAVEL") in reasons
    assert ("NOAU00001", "SEM_AUTORIZACAO_DE_DISTRIBUICAO") in reasons
    assert b"META00001" not in data and b"NOAU00001" not in b"".join(files.values())
    assert sspi.check_archive(data).ok


def test_no_publishable_title_fails_build():
    with pytest.raises(ValueError, match="nenhum título"):
        compile_catalog(parse(base_doc(packages=[])))


def test_normalize_search_accents():
    assert normalize_search("Ação: São-Paulo! ÉPICO") == "acao sao paulo epico"


def test_utf8_names_preserved():
    files, _, data = build_bytes(base_doc(name="Coração Valente"))
    assert "Coração Valente".encode() in files["index/titles.json"]
    assert sspi.check_archive(data).ok


def test_many_titles_split_index_pages():
    doc = base_doc()
    t0 = doc["titles"][0]
    doc["titles"] = []
    for i in range(1, 1002):
        t = copy.deepcopy(t0)
        t["titleId"] = f"TEST{i:05d}"
        doc["titles"].append(t)
    files, rep, data = build_bytes(doc)
    cat = json.loads(files["catalog.json"])
    assert len(cat["indexFiles"]) == 3 and cat["counts"]["titles"] == 1001
    assert sspi.check_archive(data).ok
    assert any("não comprovado" in w for w in rep.warnings)


# ---------- o check detecta adulteração

def _tamper(mutator):
    files = dict(compile_catalog(parse(base_doc()))[0])
    mutator(files)
    return sspi.check_files(files)


def test_check_detects_hash_mismatch():
    def m(f):
        f["index/titles.json"] = f["index/titles.json"].replace(b"Jogo", b"Jogx")
    assert any("sha256" in e for e in _tamper(m).errors)


def _rewrite(files, path, fn):
    doc = json.loads(files[path])
    fn(doc)
    files[path] = sspi.dumps(doc)
    src = json.loads(files["source.json"])
    for e in src["files"]:
        e["size"], e["sha256"] = len(files[e["path"]]), sspi.sha256(files[e["path"]])
    files["source.json"] = sspi.dumps(src)


@pytest.mark.parametrize("path,fn,msg", [
    ("catalog.json", lambda d: d["counts"].update(releases=9), "counts"),
    ("index/titles.json", lambda d: d["titles"][0].update(releaseCount=2), "disagrees"),
    ("index/titles.json", lambda d: d["titles"][0].update(titleId="APOL0004"), "Unsupported catalog title"),
    ("packages/items.json", lambda d: d["titles"]["TEST12345"][0].update(kind="game"), "kind"),
    ("packages/items.json", lambda d: d["titles"]["TEST12345"][0].update(accessType="Torrent"), "access"),
    ("packages/items.json", lambda d: d["titles"]["TEST12345"][0].update(sha256="xyz"), "SHA-256"),
    ("catalog.json", lambda d: d.update(format="v2"), "newer SSPI"),
])
def test_check_detects_semantic_errors(path, fn, msg):
    def m(f):
        _rewrite(f, path, fn)
    assert any(msg in e for e in _tamper(m).errors)


@pytest.mark.parametrize("bad", ["../x.json", "/abs.json", "a\\b.json", "c:x.json", "a//b.json"])
def test_check_rejects_bad_paths(bad):
    def m(f):
        f[bad] = b"{}"
    assert any("caminho inválido" in e for e in _tamper(m).errors)


def test_check_rejects_oversized_archive():
    files = compile_catalog(parse(base_doc()))[0]
    assert not sspi.check_files(files, archive_size=sspi.MAX_ARCHIVE_BYTES + 1).ok


def test_check_rejects_garbage():
    assert not sspi.check_archive(b"not a zip").ok


# ---------- CLI

def test_cli_build_and_check(tmp_path):
    out = tmp_path / "x.gssource"
    rep = tmp_path / "x.report.json"
    assert main(["build", str(FIXTURES[0]), "-o", str(out), "--report", str(rep),
                 "--allow-synthetic-probe"]) == 0
    assert main(["check", str(out), "--allow-placeholder"]) == 0
    r = json.loads(rep.read_text())
    assert r["consoleCompatibility"].startswith("NAO_TESTADO")
    assert r["artifactSha256"] == sspi.sha256(out.read_bytes())


def test_cli_build_failure_writes_nothing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(base_doc(titleId="CUSA99999")))
    out = tmp_path / "x.gssource"
    assert main(["build", str(bad), "-o", str(out)]) == 1
    assert not out.exists()


def test_content_sha256_ignores_zip_compressor():
    """O hash do ZIP depende do zlib; o hash de conteúdo não."""
    files = build_bytes(json.loads(FIXTURES[0].read_text(encoding="utf-8")))[0]
    a = zip_files(files)
    # recompacta o mesmo conteúdo com outro nível de deflate → bytes do ZIP diferem
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, d in files.items():
            zi = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, d, compresslevel=1)
    b = buf.getvalue()
    assert sspi.content_sha256(a) == sspi.content_sha256(b)


REJECTED = sorted((Path(__file__).parent.parent / "data" / "fixtures" / "rejected").glob("*.json"))


@pytest.mark.parametrize("fx", REJECTED, ids=lambda p: p.stem)
def test_prefixes_rejected_by_console_fail_build(fx, tmp_path):
    """Gate 2 (22/11/2026): SSPI 5.11.7 recusou NPXS e APOL na importação."""
    out = tmp_path / "x.gssource"
    assert main(["build", str(fx), "-o", str(out)]) == 1
    assert not out.exists()


# ---------- Gate 2: chaves sintéticas T5/T6 (identidade real separada da chave)

import io as _io
import zipfile as _zf

DATA = Path(__file__).parent.parent / "data" / "fixtures" / "probes"


def _gss(name):
    doc = json.loads((DATA / name).read_text(encoding="utf-8"))
    files, rep, data = build_bytes(doc)
    return doc, {k: json.loads(v) for k, v in files.items()}, rep, data


def _key_doc(**over):
    t = {"titleId": "CUSA90001", "catalogKey": True,
         "realIdentity": {"titleId": "NPXS39041", "contentId": None, "evidence": "x"},
         "identityEvidence": "chave sintética", "name": "Loja",
         "packages": [{"id": "p", "kind": "base", "accessType": "Direct", "url": "https://example.com/a.pkg",
                       "authorization": {"basis": "license", "evidence": "x"}}]}
    t.update(over)
    return {"schema": "ps4storebr.catalog/v1",
            "source": {"id": "s.k", "name": "K", "description": "", "version": "1.0.0"}, "titles": [t]}


def test_t5_uses_distinct_non_probe_cusa_key():
    doc, f, rep, data = _gss("t5-cusa90001-store-r2.json")
    [row] = f["index/titles.json"]["titles"]
    assert row["titleId"] == "CUSA90001" and row["titleId"] != "CUSA99999"
    assert "CUSA90001" in row["searchText"] and "store" in row["searchText"]
    assert sspi.check_archive(data).ok          # sem --allow-placeholder


def test_t6_two_titles_distinct_keys_no_conflict():
    doc, f, rep, data = _gss("t6-two-titles.json")
    rows = f["index/titles.json"]["titles"]
    keys = [r["titleId"] for r in rows]
    assert sorted(keys) == ["CUSA90002", "CUSA90003"] and len(set(keys)) == 2
    assert f["catalog.json"]["counts"]["titles"] == 2
    shard = f["packages/items.json"]["titles"]
    assert set(shard) == set(keys)
    for k in keys:                              # cada chave tem sua linha e não cruza com a outra
        assert [r["titleId"] for r in shard[k]] == [k]
    assert sspi.check_archive(data).ok
    assert [m["realTitleId"] for m in rep.to_dict()["identityMap"]] == ["NPXS39041", "APOL00004"]


@pytest.mark.parametrize("fx", ["t5-cusa90001-store-r2.json", "t6-two-titles.json", "t7-cusa90004-store-r2.json"])
def test_real_identity_never_leaks_into_gssource(fx):
    _, f, _, data = _gss(fx)
    blob = b"".join(_zf.ZipFile(_io.BytesIO(data)).read(n) for n in _zf.ZipFile(_io.BytesIO(data)).namelist())
    for real in (b'"titleId":"NPXS', b'"titleId":"APOL'):
        assert real not in blob
    for rows in f["packages/items.json"]["titles"].values():
        assert all("contentId" not in r for r in rows)   # sem variável extra no teste de console


def test_production_fixtures_do_not_use_99999():
    for p in DATA.glob("t[567]*.json"):
        assert "CUSA99999" not in p.read_text(encoding="utf-8").replace("CUSA99999 não", "")


@pytest.mark.parametrize("over,msg", [
    ({"titleId": "CUSA12345"}, "CUSA90000"),                       # fora da faixa reservada
    ({"titleId": "CUSA99999"}, "placeholder"),                     # 99999 sem probe
    ({"realIdentity": {"titleId": "NPXS39041"}}, "evidence"),
    ({"realIdentity": {"titleId": "CUSA90001", "evidence": "x"}}, "igual à chave"),
    ({"realIdentity": {"titleId": "xx", "evidence": "x"}}, "realIdentity.titleId"),
])
def test_catalog_key_rules(over, msg):
    with pytest.raises(CatalogError, match=msg):
        parse(_key_doc(**over), allow_synthetic=True)


def test_real_identity_requires_catalog_key_and_is_unique():
    with pytest.raises(CatalogError, match="só é usado"):
        parse(_key_doc(catalogKey=False, titleId="TEST12345"), allow_synthetic=True)
    d = _key_doc()
    t2 = copy.deepcopy(d["titles"][0]); t2["titleId"] = "CUSA90002"
    d["titles"].append(t2)
    with pytest.raises(CatalogError, match="duplicaria"):
        parse(d, allow_synthetic=True)


def test_probe_allows_99999_only_for_probe():
    parse(_key_doc(titleId="CUSA99999", probe=True), allow_synthetic=True)


def test_t7_store_pkg_unmodified_under_distinct_synthetic_key():
    doc, f, rep, data = _gss("t7-cusa90004-store-r2.json")
    [row] = f["index/titles.json"]["titles"]
    assert row["titleId"] == "CUSA90004"
    used = {json.loads(p.read_text(encoding="utf-8"))["titles"][i]["titleId"]
            for p in DATA.glob("t[56]*.json") for i in range(len(json.loads(p.read_text(encoding="utf-8"))["titles"]))}
    assert "CUSA90004" not in used                      # chave inédita: sem confundir com T5/T6
    [pkg] = f["packages/items.json"]["titles"]["CUSA90004"]
    assert pkg["url"] == "https://pkg-zone.com/update/Store-R2.pkg"   # URL oficial, sem espelho/alteração
    assert pkg["kind"] == "base" and pkg["accessType"] == "Direct"
    assert doc["titles"][0]["realIdentity"]["titleId"] == "NPXS39041"
    assert rep.to_dict()["identityMap"][0] == {"catalogKey": "CUSA90004", "realTitleId": "NPXS39041",
                                               "realContentId": None, "probe": False}
    assert sspi.check_archive(data).ok


# ---------- T7 (22/11/2026): SSPI recusou a instalação: "expected CUSA90004 got NPXS39041"

@pytest.mark.parametrize("fx", FIXTURES, ids=lambda p: p.stem)
def test_synthetic_keys_blocked_by_default(fx, tmp_path):
    out = tmp_path / "x.gssource"
    assert main(["build", str(fx), "-o", str(out)]) == 1
    assert not out.exists()
    with pytest.raises(CatalogError, match="abandonad"):
        parse(json.loads(fx.read_text(encoding="utf-8")))


def test_content_id_must_match_title_id():
    ok = base_doc()
    ok["titles"][0]["titleId"] = "CUSA12345"
    ok["titles"][0]["packages"][0]["contentId"] = "UP0000-CUSA12345_00-ABCDEFGHIJKLMNOP"
    parse(ok)
    bad = copy.deepcopy(ok)
    bad["titles"][0]["packages"][0]["contentId"] = "UP0000-CUSA54321_00-ABCDEFGHIJKLMNOP"
    with pytest.raises(CatalogError, match="não a CUSA12345"):
        parse(bad)
    worse = copy.deepcopy(ok)
    worse["titles"][0]["packages"][0]["contentId"] = "lixo"
    with pytest.raises(CatalogError, match="fora do formato"):
        parse(worse)
