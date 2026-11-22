"""DISCOVERY × LINK_VALIDATION × PUBLICATION: a descoberta não perde resultados por licença, autorização, categoria ou prefixo."""
import json
import zipfile
from pathlib import Path

import pytest

from ps4store import validation
from ps4store.cli import main, search_rows
from ps4store.discover import discover_search, load_config, run
from ps4store.model import Source
from ps4store.publication import assess_compat
from test_contents import Repo, cfg as contents_cfg
from test_gate3 import BASE_PKG, NOW, FakeNet, make_pkg
import test_links as tl
import test_pkgzone as pz
from test_pkgzone import BASE, Zone, cfg_file as zone_cfg

SRC = Path(__file__).parent.parent / "src" / "ps4store"


def go(tmp_path, net, cfgp, **kw):
    return run(load_config(cfgp), net, out_gssource=tmp_path / "o/a.gssource", out_canonical=tmp_path / "o/c.json",
               out_report=tmp_path / "o/r.json", state_path=tmp_path / "st.json", now=kw.pop("now", NOW),
               sleep=lambda s: None, out_research=tmp_path / "loc/research.json", **kw)


def rows(tmp_path):
    return json.loads((tmp_path / "loc/research.json").read_text())["entries"]


def mixed_zone():
    z = Zone()
    z.add("CUSA95601", "App livre CUSA")
    z.add("NPXS39041", "Homebrew NPXS")
    z.add("MOZI00001", "Prefixo desconhecido")
    data = tl.retail_pkg("CUSA95602")
    z.items.append(pz.item("CUSA95602", "Streaming", size=len(data), extra={"category": "media"}))
    z.files[f"{BASE}/download/ps4/CUSA95602/1.0.0"] = data
    z.add("PPSA01650", "PS5", console="ps5")
    return z


# ---------------------------------------------------------------- a descoberta não depende de licença/autorização/categoria/prefixo
def test_discovery_set_is_identical_with_or_without_authorization(tmp_path):
    ok = {"basis": "license", "evidence": "e"}
    a = go(tmp_path / "a", mixed_zone(), zone_cfg(tmp_path, authorization=None)) if (tmp_path / "a").mkdir() is None else None
    b_dir = tmp_path / "b"; b_dir.mkdir()
    b = go(b_dir, mixed_zone(), zone_cfg(tmp_path, authorization=ok, authorized_titles={"CUSA95601": ok}))
    key = lambda r: sorted(e["key"] for e in r.report["entries"])
    assert key(a) == key(b) and len(key(a)) == 5
    ra, rb = rows(tmp_path / "a"), rows(b_dir)
    assert sorted(x["url"] for x in ra) == sorted(x["url"] for x in rb)                     # mesmos links registrados
    assert {x["titleId"] for x in ra} == {"CUSA95601", "NPXS39041", "MOZI00001", "CUSA95602", "PPSA01650"}
    for x in ra:                                                                             # nenhum é eliminado: todos têm linha completa
        assert x["status"]["found"] is True and x["license"] == "LICENSE_UNKNOWN"


def test_license_unknown_is_recorded_not_a_reason_to_drop_and_known_license_is_captured(tmp_path):
    z = mixed_zone()
    z.items[0]["description"] = "Open Source remake"                                         # só pista; licença segue desconhecida
    r = go(tmp_path, z, zone_cfg(tmp_path))
    x = {e["titleId"]: e for e in rows(tmp_path)}["CUSA95601"]
    assert x["license"] == "LICENSE_UNKNOWN" and x["licenseSpdx"] is None and "Open Source" in x["licenseHint"]
    net = Repo()
    net.put("a.pkg", make_pkg("CUSA95701"), "a" * 40)
    orig = net.get_json
    net.get_json = lambda url: {"license": {"spdx_id": "GPL-3.0"}} if url.endswith("/repos/acme/app") else orig(url)
    go(tmp_path / "c" if (tmp_path / "c").mkdir() is None else tmp_path, net, contents_cfg(tmp_path))
    y = rows(tmp_path / "c")[0]
    assert (y["license"], y["licenseSpdx"]) == ("KNOWN", "GPL-3.0")


def test_five_statuses_are_reported_separately(tmp_path):
    ok = {"basis": "license", "evidence": "e"}
    z = mixed_zone()
    z.items.append(pz.item("CUSA95699", "Sem arquivo", size=10))                           # link quebrado (404)
    r = go(tmp_path, z, zone_cfg(tmp_path, authorized_titles={"CUSA95601": ok}))
    by = {e["titleId"] or e["asset"]: e["status"] for e in r.report["entries"]}
    assert by["CUSA95601"] == {"found": True, "linkAccessible": True, "fileIdentified": True, "sspiCompat": "compatible",
                               "publication": "available", "directInstall": "available"}
    assert by["NPXS39041"]["sspiCompat"] == "incompatible" and by["NPXS39041"]["publication"] == "blocked" \
        and by["NPXS39041"]["directInstall"] == "available"                                # incompatível com o catálogo, instalável por link
    assert by["CUSA95602"]["sspiCompat"] == "compatible" and by["CUSA95602"]["publication"] == "blocked" \
        and by["CUSA95602"]["directInstall"] == "blocked"                                  # restrito: compatível, mas fora de qualquer oferta
    assert by["PPSA01650_ps5_v1.0.0.pkg"] == {"found": True, "linkAccessible": None, "fileIdentified": None,
                                                "sspiCompat": "not-evaluated", "publication": "not-evaluated", "directInstall": "not-evaluated"}
    broken = next(e for e in r.report["entries"] if e["asset"].startswith("CUSA95699"))
    assert broken["status"]["linkAccessible"] is False and broken["status"]["fileIdentified"] is None
    m = r.report["counts"]["matriz"]
    assert m["encontrados"] == 6 and m["publicacaoEmCatalogo"]["available"] == 1
    md = (tmp_path / "o/r.md").read_text()
    assert "Cinco perguntas, separadas" in md and "LICENSE_UNKNOWN" in md and "Disponível por link direto" in md


def test_compat_lists_all_reasons_and_publication_is_independent(tmp_path):
    from ps4store.model import Entry, Found
    s = Source("s", "pkg-zone-catalog", "", True, False, 1, "license", "e")
    e = Entry(Found("k", s, "1", "", "", "x.pkg", "https://h/x.pkg", 1))
    e.title_id, e.kind = "UDAT99999", "update"
    assert assess_compat(e) == ["PREFIX_UNPROVEN", "PLACEHOLDER_ID", "KIND_UNTESTED"]
    e.title_id, e.kind = "CUSA12345", "base"
    assert assess_compat(e) == []


def test_validation_module_never_looks_at_authorization_tls_policy_or_licence():
    txt = (SRC / "validation.py").read_text(encoding="utf-8")
    for forbidden in ("authorized_titles", "auth_for", "tls_known_bad", "authorization", "RETAIL_STYLE_ID", "LICENSE"):
        assert forbidden not in txt, forbidden
    pub = (SRC / "publication.py").read_text(encoding="utf-8")
    assert "net.probe" not in pub and "classify_link" not in pub          # PUBLICATION não toca a rede nem classifica links


def test_validate_link_result_is_the_same_whatever_the_authorization():
    d = make_pkg("CUSA95801")
    outs = []
    for auth in ({}, {"basis": "license", "evidence": "x"}):
        s = Source("s", "github-contents", "a/b", True, False, 1, auth.get("basis", ""), auth.get("evidence", ""))
        net = FakeNet()
        net.files["https://h/x.pkg"] = d
        outs.append(validation.validate_link(__import__("ps4store.model", fromlist=["Found"]).Found("k", s, "1", "", "", "x.pkg", "https://h/x.pkg", len(d)), net))
    a, b = outs
    assert (a.title_id, a.content_id, a.stage, a.link["kind"], a.total_size) == (b.title_id, b.content_id, b.stage, b.link["kind"], b.total_size)


# ---------------------------------------------------------------- cobertura: releases inativas, tipos de arquivo, busca
def test_inactive_releases_are_discovered_and_validated_incrementally(tmp_path):
    z = Zone()
    z.add("CUSA95601", "Ativo")
    for i in range(5):
        data = make_pkg("MOZI0000%d" % i)
        z.items.append(pz.item("MOZI0000%d" % i, "Antiga %d" % i, size=len(data), active=False))
        z.files[f"{BASE}/download/ps4/MOZI0000{i}/1.0.0"] = data
    cfgp = zone_cfg(tmp_path, include_inactive=True, inactive_probe_budget=2, recheck_hours=720)
    r1 = go(tmp_path, z, cfgp)
    assert r1.report["counts"]["descobertos"] == 6 and z.probes == 3                       # 1 ativa + 2 inativas
    assert r1.report["counts"]["motivos"].get("PROBE_BUDGET") == 3
    assert sum(1 for x in rows(tmp_path) if x["sourceActive"] is False) == 5               # todas registradas na pesquisa
    go(tmp_path, z, cfgp, now="2026-11-22T13:00:00Z")
    assert z.probes == 5                                                                    # +2 por execução, sem repetir as validadas


def test_single_archives_are_recorded_with_signature_check_and_other_files_are_ignored(tmp_path):
    net = Repo()
    net.put("jogo.zip", b"PK\x03\x04" + b"0" * 600, "a" * 40)
    net.put("jogo.7z", b"7z\xbc\xaf\x27\x1c" + b"0" * 600, "b" * 40)
    net.put("jogo.rar", b"Rar!\x1a\x07\x01\x00" + b"0" * 600, "c" * 40)
    net.put("falso.zip", b"<html>nope" + b"0" * 600, "d" * 40)
    net.put("leia.txt", b"x", "e" * 40)
    r = go(tmp_path, net, contents_cfg(tmp_path))
    by = {e["asset"]: e for e in r.report["entries"]}
    assert set(by) == {"jogo.zip", "jogo.7z", "jogo.rar", "falso.zip"}
    assert [by[n]["reason"] for n in ("jogo.zip", "jogo.7z", "jogo.rar")] == ["ARCHIVE_NOT_INSPECTED"] * 3
    assert by["falso.zip"]["reason"] == "NOT_ARCHIVE" and by["jogo.zip"]["fileType"] == "zip"
    assert by["jogo.zip"]["status"]["linkAccessible"] is True and by["jogo.zip"]["status"]["fileIdentified"] is None


class Search(FakeNet):
    def __init__(self):
        super().__init__()
        self.search = {}

    def get_json(self, url):
        if "/search/repositories" in url:
            q = url.split("q=")[1].split("&")[0]
            return {"items": self.search.get(q, [])}
        return super().get_json(url)


def test_github_search_discovers_repos_and_their_release_files_with_license(tmp_path):
    net = Search()
    net.search["topic%3Aps4-homebrew"] = [{"full_name": "a/jogo", "license": {"spdx_id": "GPL-3.0"}, "stargazers_count": 9, "description": "um jogo"},
                                           {"full_name": "b/sem-releases", "license": None, "stargazers_count": 1}]
    net.search["ps4%20pkg"] = [{"full_name": "a/jogo", "license": {"spdx_id": "GPL-3.0"}}, {"full_name": "c/util", "license": None}]
    u1, u2 = "https://dl.example.org/jogo.pkg", "https://dl.example.org/util.pkg"
    net.files[u1], net.files[u2] = make_pkg("CUSA95901"), make_pkg("NPXS39041")
    net.release("a/jogo", 1, "v1", [("jogo.pkg", u1, len(net.files[u1])), ("notas.txt", "https://x/n", 1)])
    net.release("c/util", 2, "v2", [("util.pkg", u2, len(net.files[u2]))])
    src = Source("busca", "github-search", "", True, False, 3, "", "", queries=["topic:ps4-homebrew", "ps4 pkg"], max_repos=5)
    f = discover_search(src, net)
    assert sorted(x.asset_name for x in f) == ["jogo.pkg", "util.pkg"]                   # repo duplicado entre consultas = 1; sem releases = pula
    meta = {x.asset_name: x.meta for x in f}
    assert meta["jogo.pkg"]["license"] == "GPL-3.0" and meta["jogo.pkg"]["discoveredVia"] == "topic:ps4-homebrew"
    cfgp = tmp_path / "s.json"
    cfgp.write_text(json.dumps({"schema": "ps4storebr.sources/v1", "catalog": {"id": "t", "name": "T"}, "tls": {"enforce": True}, "sources": [
        {"id": "busca", "type": "github-search", "queries": ["topic:ps4-homebrew", "ps4 pkg"], "max_repos": 5, "authorization": None, "critical": False}]}))
    r = go(tmp_path, net, cfgp)
    by = {e["titleId"]: e for e in rows(tmp_path)}
    assert by["CUSA95901"]["license"] == "KNOWN" and by["NPXS39041"]["license"] == "LICENSE_UNKNOWN"
    assert by["CUSA95901"]["publicationBlockers"] == ["NO_AUTHORIZATION"] and not r.wrote_catalog   # descoberto; não publicado


def test_search_command_by_name_id_type_and_status(tmp_path, capsys):
    net = Repo()
    net.put("jogo.zip", b"PK\x03\x04" + b"0" * 600, "a" * 40)
    net.put("app.pkg", make_pkg("CUSA95417", title="PS4 Store BR Test"), "b" * 40)
    go(tmp_path, net, contents_cfg(tmp_path))
    rs = rows(tmp_path)
    assert [r["titleId"] for r in search_rows(rs, ["store", "br"])] == ["CUSA95417"]
    assert [r["titleId"] for r in search_rows(rs, ["cusa95417"])] == ["CUSA95417"]
    assert [r["fileType"] for r in search_rows(rs, [], ftype="zip")] == ["zip"]
    assert len(search_rows(rs, [], only="accessible")) == 2 and len(search_rows(rs, [], only="identified")) == 1
    assert main(["search", "store", "--research", str(tmp_path / "loc/research.json"), "--urls"]) == 0
    out = capsys.readouterr().out
    assert "CUSA95417" in out and "LICENSE_UNKNOWN" in out and "1 resultado" in out
    assert main(["search", "x", "--research", str(tmp_path / "nao-existe.json")]) == 1


# ---- find: busca por nome (normalização, ranking, disponibilidade em português) ----
def _row(name, tid, **kw):
    r = {"name": name, "titleId": tid, "contentId": None, "url": f"https://x/{tid}.pkg", "source": "s", "author": None,
         "description": None, "repo": None, "fileType": "pkg", "version": "1.0", "sizeBytes": 1000000, "identityRead": False,
         "linkStatus": None, "publicationAvailable": False, "directInstallAvailable": False,
         "status": {"linkAccessible": None}, "publicationBlockers": [], "directInstallBlockers": []}
    r.update(kw)
    return r


def test_find_normaliza_e_ordena_exato_inicio_parcial():
    from ps4store.cli import match_rank, search_rows
    rs = [_row("Super Ação Bros Deluxe", "AAAA00001"), _row("Ação", "AAAA00002"), _row("Ação Total", "AAAA00003"), _row("A Grande Acao", "AAAA00004")]
    got = search_rows(rs, ["acao"])                      # sem acento e minúsculas acham "Ação"
    assert len(got) == 4
    got.sort(key=lambda r: match_rank(r, ["ACAO"]))
    assert [r["titleId"] for r in got[:2]] == ["AAAA00002", "AAAA00003"]     # exato, depois início do nome
    assert {r["titleId"] for r in got[2:]} == {"AAAA00001", "AAAA00004"}    # depois palavra no meio do nome
    assert match_rank(rs[1], ["aaaa00002"]) == 0          # ID exato conta como exato


def test_find_disponibilidade_nao_inventa_validacao():
    from ps4store.cli import availability_pt
    assert availability_pt(_row("X", "AAAA00001")) == ("Descoberto, link NÃO testado", False)
    assert availability_pt(_row("X", "AAAA00001", status={"linkAccessible": False}, linkStatus="acesso-negado"))[1] is False
    # link responde mas identidade não lida => nunca 'validado'
    t, ok = availability_pt(_row("X", "AAAA00001", status={"linkAccessible": True}, directInstallAvailable=True))
    assert ok is False and "não identificado" in t
    t, ok = availability_pt(_row("X", "AAAA00001", status={"linkAccessible": True}, identityRead=True, directInstallAvailable=True))
    assert ok is True and "link direto" in t
    t, ok = availability_pt(_row("X", "AAAA00001", status={"linkAccessible": True}, identityRead=True, publicationBlockers=["NO_AUTHORIZATION"]))
    assert ok is False and "sem autorização" in t


def test_find_cli_nao_mostra_url_de_item_nao_validado(tmp_path, capsys):
    from ps4store.cli import main
    rs = [_row("Jogo Teste", "AAAA00001"), _row("Jogo Pronto", "AAAA00002", status={"linkAccessible": True}, identityRead=True, directInstallAvailable=True)]
    f = tmp_path / "research.json"
    f.write_text(json.dumps({"entries": rs}), encoding="utf-8")
    assert main(["find", "jogo", "--urls", "--research", str(f)]) == 0
    out = capsys.readouterr().out
    assert "https://x/AAAA00002.pkg" in out and "https://x/AAAA00001.pkg" not in out
    assert "região não informada" in out and "idioma não informado" in out
