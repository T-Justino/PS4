import json

from ps4store.cli import main
from ps4store.web import build_site, select_items


def _r(name, tid, url, **kw):
    r = {"name": name, "titleId": tid, "contentId": f"IV0000-{tid}_00-AAAAAAAAAAAAAAAA", "url": url, "source": "s", "fileType": "pkg",
         "version": "1.0", "sizeBytes": 2_000_000, "kind": "base", "identityRead": True, "restricted": False, "duplicateOf": None,
         "rejectionReason": None, "sourceActive": True, "linkStatus": "direto", "publicationAvailable": False,
         "directInstallAvailable": True, "status": {"linkAccessible": True}, "publicationBlockers": ["NO_AUTHORIZATION"],
         "directInstallBlockers": []}
    r.update(kw)
    return r


ES = [
    _r("Jogo Livre", "AAAA00001", "https://x/a.pkg"),
    _r("Jogo Catalogado", "AAAA00002", "https://x/b.pkg", publicationAvailable=True),
    _r("Netflix", "CUSA00127", "https://x/n.pkg", restricted=True),
    _r("Velho", "AAAA00003", "https://x/v.pkg", rejectionReason="SUPERSEDED"),
    _r("Nao Testado", "AAAA00004", "https://x/t.pkg", status={"linkAccessible": None}, identityRead=False, directInstallAvailable=False),
    _r("Sem Identidade", "AAAA00005", "https://x/i.pkg", identityRead=False),
    _r("Fora", "AAAA00006", "https://x/f.pkg", status={"linkAccessible": False}, linkStatus="acesso-negado", directInstallAvailable=False),
    _r("Pacote RAR", "AAAA00007", "https://x/r.rar", fileType="rar-multiparte"),
]


def _by(items, name):
    return next(i for i in items if i["name"] == name)


def test_publico_so_embute_url_de_item_autorizado_e_exclui_restrito_rar_antigo():
    it = select_items(ES, "publico")
    assert {i["name"] for i in it} == {"Jogo Livre", "Jogo Catalogado", "Nao Testado", "Sem Identidade", "Fora"}
    assert "url" not in _by(it, "Jogo Livre") and "não listado publicamente" in _by(it, "Jogo Livre")["text"]
    assert _by(it, "Jogo Catalogado")["url"] == "https://x/b.pkg"


def test_pessoal_embute_url_validada_mas_nunca_de_item_nao_validado():
    it = select_items(ES, "pessoal")
    assert _by(it, "Jogo Livre")["url"] == "https://x/a.pkg"
    for n in ("Nao Testado", "Sem Identidade", "Fora"):
        assert "url" not in _by(it, n) and _by(it, n)["state"] != "validado"
    assert _by(it, "Sem Identidade")["state"] == "nao-testado"


def test_instalacao_comprovada_casa_pela_url_exata_e_nao_vem_da_validacao_automatica():
    it = select_items(ES, "pessoal", {"https://x/a.pkg": {"date": "2026-11-22", "note": "ok"}})
    assert _by(it, "Jogo Livre")["ps4"]["date"] == "2026-11-22"
    assert "ps4" not in _by(it, "Jogo Catalogado")


def test_site_gerado_nao_quebra_o_script_com_dados_maliciosos(tmp_path):
    bad = _r("</script><img src=x onerror=alert(1)>", "AAAA00009", "https://x/z.pkg")
    rep = build_site({"entries": [bad], "generatedAt": "2026-11-22T00:00:00Z"}, tmp_path, "pessoal")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert rep["items"] == 1 and "</script><img" not in html and "<\\/script>" in html
    assert json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))["items"][0]["url"] == "https://x/z.pkg"
    assert (tmp_path / ".nojekyll").exists()


def test_cli_web(tmp_path, capsys):
    f = tmp_path / "research.json"
    f.write_text(json.dumps({"entries": ES}), encoding="utf-8")
    assert main(["web", "--research", str(f), "--out", str(tmp_path / "site"), "--proven", ""]) == 0
    assert "1 com URL copiável" in capsys.readouterr().out
