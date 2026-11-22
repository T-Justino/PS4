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
FIXTURES = sorted((ROOT / "data/fixtures").glob("*.json"))


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
    files, rep = compile_catalog(parse(doc))
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
    assert main(["build", str(FIXTURES[0]), "-o", str(out), "--report", str(rep)]) == 0
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
    """Gate 2 (22/11/2026): SSPI 5.11 beta recusou NPXS e APOL na importação."""
    out = tmp_path / "x.gssource"
    assert main(["build", str(fx), "-o", str(out)]) == 1
    assert not out.exists()
