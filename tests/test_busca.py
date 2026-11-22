"""Busca por nome: índice JSON local, sem filtros obrigatórios. Dados de teste são fictícios (.invalid)."""
import json
from pathlib import Path

import pytest

from ps4store.busca import FONTES_PADRAO, buscar, carregar_fontes, carregar_indice, fonte_autorizada, importar, indice_vazio, ler_itens, main, norm

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "fixtures" / "busca-teste.json"
FONTES = {"teste": {"id": "teste", "authorization": {"basis": "test-fixture", "evidence": "dados fictícios"}},
          "teste-b": {"id": "teste-b", "authorization": {"basis": "test-fixture", "evidence": "idem"}},
          "sem-auth": {"id": "sem-auth", "authorization": None}}


def U(n):
    return f"https://exemplo.invalid/{n}"


def doc_com(*itens, fonte="teste"):
    d = indice_vazio()
    importar(d, FONTES, fonte, [{"nome": n, "url": U(i)} for i, n in enumerate(itens)])
    return d


def nomes(res):
    return [r["nome"] for r in res]


def test_batman_acha_varios_jogos_sem_nenhum_filtro():
    d = doc_com("Batman: Arkham Knight", "Batman: Arkham VR", "LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame", "Spider-Man")
    res = buscar(d, "Batman")
    assert nomes(res) == ["Batman: Arkham Knight", "Batman: Arkham VR", "LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame"]
    assert all(r["url"].startswith("https://") for r in res)


def test_lego_batman_filtra_e_ignora_caixa_acentos_e_pontuacao():
    d = doc_com("Batman: Arkham Knight", "LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame", "LEGO Marvel", "Pokémon Café Mix")
    assert nomes(buscar(d, "lego batman")) == ["LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame"]
    assert nomes(buscar(d, "BATMAN LEGO")) == nomes(buscar(d, "lego batman"))                     # ordem dos termos não importa
    assert nomes(buscar(d, "pokemon cafe")) == ["Pokémon Café Mix"] == nomes(buscar(d, "POKÉMON CAFÉ"))
    assert nomes(buscar(d, "batman: arkham")) == ["Batman: Arkham Knight"]
    assert nomes(buscar(d, "bat")) and "LEGO Marvel" not in nomes(buscar(d, "bat"))             # parcial


def test_resultado_vazio_e_termo_vazio():
    d = doc_com("Batman: Arkham Knight")
    assert buscar(d, "zelda") == [] and buscar(d, "") == [] and buscar(d, "   ::: ") == []
    assert buscar(indice_vazio(), "batman") == []


def test_ranking_igual_depois_comeca_com_depois_palavra_depois_contem():
    d = doc_com("Super Batman Returns", "Batman", "Batmanía Total", "The Batman Collection", "Batman Begins")
    r = [(x["nome"], x["rank"]) for x in buscar(d, "batman")]
    assert r[0] == ("Batman", 0) and r[1][1] == 1 and r[2][1] == 1 and {x[1] for x in r[3:]} == {2}


def test_nomes_repetidos_em_fontes_ou_urls_diferentes_sao_todos_mantidos():
    d = indice_vazio()
    importar(d, FONTES, "teste", [{"nome": "Batman Arkham Knight", "url": U("a")}, {"nome": "Batman Arkham Knight", "url": U("a2")},
                                  {"nome": "Batman Arkham Knight", "url": U("a")}])           # a terceira é cópia exata da primeira
    importar(d, FONTES, "teste-b", [{"nome": "BATMAN: Arkham Knight", "url": U("b")}])
    res = buscar(d, "arkham knight")
    assert sorted((r["fonte"], r["url"]) for r in res) == [("teste", U("a")), ("teste", U("a2")), ("teste-b", U("b"))]
    assert [r["url"] for r in buscar(d, "arkham knight", fonte="teste-b")] == [U("b")]


def test_limite_de_resultados():
    d = doc_com(*[f"Batman {n}" for n in range(30)])
    assert len(buscar(d, "batman")) == 30 and len(buscar(d, "batman", limite=5)) == 5


def test_importar_exige_fonte_registrada_e_autorizada():
    d = indice_vazio()
    with pytest.raises(ValueError, match="não está registrada"):
        importar(d, FONTES, "desconhecida", [{"nome": "X", "url": U(1)}])
    with pytest.raises(ValueError, match="authorization"):
        importar(d, FONTES, "sem-auth", [{"nome": "X", "url": U(1)}])
    assert d["titulos"] == [] and not fonte_autorizada(FONTES["sem-auth"])
    assert not fonte_autorizada({"authorization": {"basis": "qualquer-coisa", "evidence": "x"}})
    assert not fonte_autorizada({"authorization": {"basis": "license", "evidence": ""}})


def test_registro_de_fontes_do_repositorio_tem_so_teste_e_wikidata_cc0_autorizadas():
    f = carregar_fontes(str(ROOT / FONTES_PADRAO))
    assert set(f) == {"teste", "teste-b", "wikidata"} and all(fonte_autorizada(x) for x in f.values())
    assert f["wikidata"]["licenca"] == "CC0-1.0" and f["wikidata"]["authorization"]["basis"] == "license"
    assert all(f[k]["authorization"]["basis"] == "test-fixture" for k in ("teste", "teste-b"))


def test_importar_valida_itens_e_atualizacao_substitui_a_fonte():
    d = indice_vazio()
    rep = importar(d, FONTES, "teste", [{"nome": "Bom", "url": U(1)}, {"nome": "", "url": U(2)}, {"nome": "Sem https", "url": "http://x.invalid/a"},
                                        {"nome": "Com espaço", "url": "https://x.invalid/a b"}, {"nome": "Cred", "url": "https://u:p@x.invalid/a"},
                                        {"nome": "Ctl\x07", "url": U(3)}, {"nome": "Opcionais", "url": U(4), "titleId": "CUSA00001", "regiao": "US",
                                                                          "idiomas": ["pt-BR"]}])
    assert rep["importados"] == 2 and len(rep["rejeitados"]) == 5
    opc = next(t for t in d["titulos"] if t["nome"] == "Opcionais")
    assert opc["titleId"] == "CUSA00001" and opc["regiao"] == "US" and opc["idiomas"] == ["pt-BR"]       # base para filtros futuros
    importar(d, FONTES, "teste-b", [{"nome": "Outra", "url": U(9)}])
    rep2 = importar(d, FONTES, "teste", [{"nome": "Novo", "url": U(5)}])                                  # atualização: troca só a fonte 'teste'
    assert rep2["substituidos"] == 2 and nomes(d["titulos"]) == ["Outra", "Novo"]


def test_ler_itens_json_e_texto_tab(tmp_path):
    j = tmp_path / "a.json"
    j.write_text(json.dumps({"titulos": [{"nome": "A", "url": U(1)}]}), encoding="utf-8")
    t = tmp_path / "b.txt"
    t.write_text("# comentário\n\nBatman\thttps://exemplo.invalid/b\nsem tab\n", encoding="utf-8")
    assert ler_itens(str(j)) == [{"nome": "A", "url": U(1)}]
    assert ler_itens(str(t)) == [{"nome": "Batman", "url": "https://exemplo.invalid/b"}, {"nome": "sem tab", "url": ""}]


def test_indice_invalido_e_arquivo_ausente(tmp_path):
    assert carregar_indice(str(tmp_path / "nao.json"))["titulos"] == []
    (tmp_path / "x.json").write_text('{"schema": "outro"}', encoding="utf-8")
    with pytest.raises(ValueError):
        carregar_indice(str(tmp_path / "x.json"))


def test_norm_basico():
    assert norm("Pokémon: Café-Mix  2!") == "pokemon cafe mix 2" and norm(None) == ""


# ---------- CLI (o que o usuário digita) ----------
def cli(args, capsys):
    rc = main(args)
    c = capsys.readouterr()
    return rc, c.out, c.err


def test_cli_importa_a_fixture_e_batman_lista_nome_e_url(tmp_path, capsys):
    idx = str(tmp_path / "idx.json")
    fontes = str(ROOT / FONTES_PADRAO)
    rc, out, _ = cli(["--indice", idx, "--fontes", fontes, "--importar", str(FIXTURE), "--fonte", "teste"], capsys)
    assert rc == 0 and "Importados 7" in out
    rc, out, _ = cli(["--indice", idx, "Batman"], capsys)                   # só o nome, nenhum filtro
    assert rc == 0 and "5 resultado(s)" in out and "Batman: Arkham Knight" in out and "LEGO Batman: The Videogame" in out
    assert "https://exemplo.invalid/teste/batman-arkham-vr" in out and "[TESTE]" in out
    rc, out, _ = cli(["--indice", idx, "LEGO", "Batman"], capsys)
    assert rc == 0 and "2 resultado(s)" in out
    rc, out, _ = cli(["--indice", idx, "Zelda"], capsys)
    assert rc == 1 and "Nenhum título encontrado" in out
    rc, out, _ = cli(["--indice", idx, "batman", "--json"], capsys)
    assert rc == 0 and len(json.loads(out)) == 5


def test_cli_erros_claros(tmp_path, capsys):
    idx = str(tmp_path / "idx.json")
    assert cli(["--indice", idx, "Batman"], capsys)[0] == 3                                       # índice inexistente
    rc, _, err = cli(["--indice", idx], capsys)
    assert rc == 2 and "informe parte do nome" in err
    rc, _, err = cli(["--indice", idx, "--importar", str(FIXTURE)], capsys)
    assert rc == 2 and "--fonte" in err
    rc, _, err = cli(["--indice", idx, "--fontes", str(ROOT / FONTES_PADRAO), "--importar", str(FIXTURE), "--fonte", "nao-registrada"], capsys)
    assert rc == 2 and "não está registrada" in err and not Path(idx).exists()


def test_fixture_do_repositorio_e_ficticia():
    dados = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert all(".invalid/" in t["url"] for t in dados["titulos"]) and "FICTÍCIOS" in dados["_nota"]
