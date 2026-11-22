"""Integração com a fonte externa PKG-Zone (catálogo JSON público) e as fases DESCOBERTO → VERIFICADO → PUBLICÁVEL.

A forma do catálogo e do redirect (302 para URL assinada em outro host) vem da fonte real, observada em 22/11/2026.
Os PKGs de teste derivam do PKG real do T8 (ver test_gate3.py).
"""
import json
import zipfile

from ps4store import sspi
from ps4store.discover import discover_pkgzone, load_config, run
from ps4store.net import Probe
from test_gate3 import BASE_PKG, NOW, FakeNet, make_pkg

BASE = "https://pkg-zone.com"
SIGNED = "https://api.pkg-zone.com/dl/releases/{t}/ps4/{v}/PS4_{t}_v{v}.pkg?exp=1795377935&sig=abc123"


def item(tid, name, version="1.0.0", size=None, console="ps4", active=True, extra=None):
    rel = {"console": console, "version": version, "size": size, "sizeLabel": "x", "pv": "5.05+", "active": active,
           "date": "2026-11-20T10:00:00.000Z"}
    return {"titleId": tid, "name": name, "description": "d", "category": "hb", "author": "autor", "releases": [rel], **(extra or {})}


class Zone(FakeNet):
    """Catálogo mutável + redirect para URL assinada; só devolve o PKG se a URL estável for conhecida."""

    def __init__(self):
        super().__init__()
        self.items = []
        self.catalog_calls = 0

    def add(self, tid, name, pkg_id=None, **kw):
        data = make_pkg(pkg_id or tid)
        self.items.append(item(tid, name, size=len(data), **kw))
        v = kw.get("version", "1.0.0")
        self.files[f"{BASE}/download/{kw.get('console', 'ps4')}/{tid}/{v}"] = data

    def get_json(self, url):
        assert url == BASE + "/api/v1/catalog"
        self.catalog_calls += 1
        return {"items": self.items, "categories": [], "site": {}}

    def probe(self, url, nbytes=65536):
        pr = super().probe(url, nbytes)
        if pr.ok:
            tid, v = url.split("/")[-2], url.split("/")[-1]
            pr.final_url = SIGNED.format(t=tid, v=v)       # o servidor real responde 302 → URL assinada
        return pr


def cfg_file(tmp_path, **src):
    base = {"id": "pkg-zone", "type": "pkg-zone-catalog", "base_url": BASE, "authorization": None}
    base.update(src)
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": "ps4storebr.sources/v1", "catalog": {"id": "t.auto", "name": "T"},
                             "tls": {"enforce": True, "known_bad_hosts": {"github.com": "x"}}, "sources": [base]}))
    return p


def go(tmp_path, net, cfgp, **kw):
    return run(load_config(cfgp), net, out_gssource=tmp_path / "o/a.gssource", out_canonical=tmp_path / "o/c.json",
               out_report=tmp_path / "o/r.json", state_path=tmp_path / "st.json", now=kw.pop("now", NOW),
               sleep=kw.pop("sleep", lambda s: None), **kw)


def zone():
    z = Zone()
    z.add("CUSA95501", "App Livre CUSA")                     # CUSA, compatível pelas regras
    z.add("CUSA95502", "Outro CUSA")
    z.add("NPXS39041", "Store (NPXS)")                      # ID recusado pelo SSPI
    z.add("APOL00004", "Apollo (APOL)")
    z.add("MOZI00001", "Prefixo não comprovado")
    z.add("PPSA01650", "App de PS5", console="ps5")
    z.items.append(item("CUSA95503", "Versão antiga", active=False))
    return z


def test_connector_builds_stable_urls_skips_inactive_and_marks_ps5():
    z = zone()
    from ps4store.discover import Source
    src = Source("pkg-zone", "pkg-zone-catalog", "", True, False, 20, "", "", base_url=BASE)
    f = {x.asset_name: x for x in discover_pkgzone(src, z)}
    assert len(f) == 6 and "CUSA95503_ps4_v1.0.0.pkg" not in f              # release inativa ignorada
    a = f["CUSA95501_ps4_v1.0.0.pkg"]
    assert a.url == f"{BASE}/download/ps4/CUSA95501/1.0.0" and a.size == len(BASE_PKG) and a.name_hint == "App Livre CUSA"
    assert f["PPSA01650_ps5_v1.0.0.pkg"].skip_reason == "NOT_PS4"


def test_phases_npxs_apol_stay_in_report_but_never_in_gssource(tmp_path):
    z = zone()
    r = go(tmp_path, z, cfg_file(tmp_path))                  # fonte sem autorização
    by = {e["titleId"] or e["asset"]: e for e in r.report["entries"]}
    assert by["NPXS39041"]["fase"] == "VERIFICADO" and by["NPXS39041"]["reason"] == "PREFIX_REJECTED_BY_SSPI"
    assert by["APOL00004"]["fase"] == "VERIFICADO" and by["APOL00004"]["reason"] == "PREFIX_REJECTED_BY_SSPI"
    assert by["MOZI00001"]["reason"] == "PREFIX_UNPROVEN"
    for t in ("CUSA95501", "CUSA95502"):                      # compatíveis, mas sem autorização: VERIFICADO, não publicável
        assert (by[t]["fase"], by[t]["stage"], by[t]["reason"]) == ("VERIFICADO", "compativel_sspi", "NO_AUTHORIZATION")
    assert by["PPSA01650_ps5_v1.0.0.pkg"]["fase"] == "DESCOBERTO"
    assert r.report["counts"]["fases"] == {"DESCOBERTO": 1, "VERIFICADO": 5, "PUBLICAVEL": 0}
    assert not r.wrote_catalog and not (tmp_path / "o/a.gssource").exists()
    assert z.probes == 5                                                       # PS5 não foi sondado (só os 5 PS4)


def test_authorization_is_per_title_and_only_publishable_enters_gssource(tmp_path):
    z = zone()
    ok = {"basis": "license", "evidence": "GPL-3.0 do autor, texto em repo X"}
    cfgp = cfg_file(tmp_path, authorized_titles={"CUSA95501": ok, "NPXS39041": ok})   # NPXS autorizado não entra mesmo assim
    r = go(tmp_path, z, cfgp)
    assert r.published == 1 and r.report["counts"]["fases"]["PUBLICAVEL"] == 1
    zf = zipfile.ZipFile(tmp_path / "o/a.gssource")
    idx = json.loads(zf.read("index/titles.json"))["titles"]
    assert [t["titleId"] for t in idx] == ["CUSA95501"] and idx[0]["name"] == "App Livre CUSA"
    row = json.loads(zf.read("packages/items.json"))["titles"]["CUSA95501"][0]
    assert row["url"] == f"{BASE}/download/ps4/CUSA95501/1.0.0" and row["size"] == len(BASE_PKG)
    blob = b"".join(zf.read(n) for n in zf.namelist()) + (tmp_path / "o/c.json").read_bytes() + (tmp_path / "o/r.json").read_bytes()
    assert b"sig=" not in blob and b"exp=" not in blob                          # URL assinada nunca é gravada
    assert sspi.check_archive((tmp_path / "o/a.gssource").read_bytes()).ok
    redirect = next(e for e in r.report["entries"] if e["titleId"] == "CUSA95501")
    assert redirect["finalHost"] == "api.pkg-zone.com" and any("redireciona" in w for w in redirect["warnings"])


def test_new_upload_detected_without_code_or_config_change_and_cache_limits_probes(tmp_path):
    z = zone()
    cfgp = cfg_file(tmp_path, recheck_hours=168)
    r1 = go(tmp_path, z, cfgp)
    assert r1.report["counts"]["novos"] == 6 and z.probes == 5
    z.add("CUSA95504", "Upload novo do autor")                # alguém publica um app novo no PKG-Zone
    p0 = z.probes
    r2 = go(tmp_path, z, cfgp, now="2026-11-22T13:00:00Z")
    new = [e for e in r2.report["entries"] if e["isNew"]]
    assert [(e["titleId"], e["fase"]) for e in new] == [("CUSA95504", "VERIFICADO")]
    assert z.probes - p0 == 1                                  # só o item novo foi sondado; o resto veio do cache
    assert any("cache" in w for e in r2.report["entries"] for w in e["warnings"])
    r3 = go(tmp_path, z, cfgp, now="2026-12-10T00:00:00Z")      # cache expirado (>168 h): sonda tudo de novo
    assert r3.report["counts"]["novos"] == 0 and z.probes - p0 > 1


def test_cached_result_is_reevaluated_against_new_authorization(tmp_path):
    z = zone()
    go(tmp_path, z, cfg_file(tmp_path, recheck_hours=168))
    p0 = z.probes
    ok = {"basis": "written-permission", "evidence": "e-mail do autor, 22/11/2026"}
    r = go(tmp_path, z, cfg_file(tmp_path, recheck_hours=168, authorized_titles={"CUSA95502": ok}), now="2026-11-22T13:00:00Z")
    assert r.published == 1 and z.probes == p0                 # autorização nova vale sem sondar de novo


def test_probe_budget_and_politeness_delay(tmp_path):
    z = zone()
    sleeps = []
    r = go(tmp_path, z, cfg_file(tmp_path, max_probes=2, delay_seconds=0.5), sleep=sleeps.append)
    assert z.probes == 2 and sleeps == [0.5]
    assert r.report["counts"]["motivos"].get("PROBE_BUDGET") == 3
    assert r.report["counts"]["fases"]["DESCOBERTO"] >= 3       # sem sondar = só descoberto


def test_config_null_authorization_ok_partial_rejected(tmp_path):
    import pytest
    from ps4store.discover import ConfigError
    load_config(cfg_file(tmp_path))                              # authorization null: permitido (não publica)
    with pytest.raises(ConfigError, match="authorization"):
        load_config(cfg_file(tmp_path, authorization={"basis": "license"}))
    with pytest.raises(ConfigError, match="authorized_titles"):
        load_config(cfg_file(tmp_path, authorized_titles={"CUSA95501": {"basis": "license"}}))
    with pytest.raises(ConfigError, match="base_url"):
        load_config(cfg_file(tmp_path, base_url="http://x"))


def test_identity_comes_from_pkg_not_from_source_catalog(tmp_path):
    z = Zone()
    z.add("CUSA95601", "Declarado no catálogo", pkg_id="CUSA95602")     # catálogo da fonte diz 95601, o PKG é 95602
    ok = {"basis": "license", "evidence": "e"}
    r = go(tmp_path, z, cfg_file(tmp_path, authorized_titles={"CUSA95602": ok}))
    [e] = r.report["entries"]
    assert e["titleId"] == "CUSA95602" and e["fase"] == "PUBLICAVEL"
    assert any("catálogo da fonte declara CUSA95601" in w for w in e["warnings"])
