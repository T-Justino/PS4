"""Busca inteligente: exata, parcial, apelido (vínculo explícito) e sugestão por erro de digitação. Q-ids simulados (99110xxxx)."""
import json
from pathlib import Path

import pytest

from ps4store import busca, busca_inteligente as bi

ROOT = Path(__file__).resolve().parents[1]
FONTES = str(ROOT / "config" / "busca-fontes.json")
NOMES = ["Batman: Arkham Knight", "Batman: Arkham VR", "LEGO Batman 3: Beyond Gotham", "Cyberpunk 2077", "Grand Theft Auto V", "Grand Theft Auto IV",
         "Middle-earth: Shadow of Mordor", "Middle-earth: Shadow of War", "Pokémon Café Mix", "Red Dead Redemption 2", "God of War", "God of War III"]


def doc(nomes=NOMES, extra=()):
    d = busca.indice_vazio()
    itens = [{"nome": n, "url": f"https://www.wikidata.org/wiki/Q9911{i:04d}", "idFonte": f"wikidata:Q9911{i:04d}"} for i, n in enumerate(list(nomes) + list(extra))]
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", itens)
    return d


def nomes_de(r, k="itens"):
    return [t["nome"] for t in r[k]]


@pytest.fixture
def motor():
    return bi.Motor(doc(), bi.carregar_apelidos(str(ROOT / "data" / "apelidos.json")))


def test_busca_exata_e_parcial_continuam(motor):
    assert nomes_de(motor.buscar("Batman")) == ["Batman: Arkham Knight", "Batman: Arkham VR", "LEGO Batman 3: Beyond Gotham"]
    assert nomes_de(motor.buscar("Cyberpunk 2077")) == ["Cyberpunk 2077"]
    assert nomes_de(motor.buscar("cyber pun")) == ["Cyberpunk 2077"]                         # parcial, por palavras
    assert nomes_de(motor.buscar("pokemon cafe")) == ["Pokémon Café Mix"] and motor.buscar("pokemon cafe")["sugestoes"] == []   # sem acento


def test_apelidos_gta_v_e_gta_5_levam_ao_jogo_com_vinculo_explicito(motor):
    for t in ("GTA V", "gta 5", "GTAV", "Grand Theft Auto 5"):
        r = motor.buscar(t)
        assert nomes_de(r)[0] == "Grand Theft Auto V" and r["via"][id(r["itens"][0])] == "apelido", t
    assert nomes_de(motor.buscar("grand theft auto")) == ["Grand Theft Auto IV", "Grand Theft Auto V"]       # busca normal: ordem alfabética, sem apelido


def test_apelido_so_vale_com_nome_exato_e_unico_no_indice():
    m = bi.Motor(doc(extra=["Grand Theft Auto V"]), bi.carregar_apelidos(str(ROOT / "data" / "apelidos.json")))      # dois Q-ids com o mesmo nome
    assert "GTA V" not in " ".join(nomes_de(m.buscar("gta v"))) or not m.buscar("gta v")["via"]
    assert any("Grand Theft Auto V: nome ambíguo" in a for a in m.nao_aplicados)
    m2 = bi.Motor(doc(["Batman"]), [{"apelidos": ["Bats"], "alvo": "Grand Theft Auto V"}])                       # alvo ausente
    assert m2.apelidos == {} and any("ausente do índice" in a for a in m2.nao_aplicados)
    q = "wikidata:Q99110003"
    m3 = bi.Motor(doc(extra=["Grand Theft Auto V"]), [{"apelidos": ["GTA V"], "alvo": "Grand Theft Auto V", "qid": "Q99110012"}])   # qid explícito desfaz a ambiguidade
    assert nomes_de(m3.buscar("gta v")) == ["Grand Theft Auto V"] and m3.buscar("gta v")["itens"][0]["idFonte"] == "wikidata:Q99110012"


def test_erro_de_digitacao_gera_sugestao_relevante(motor):
    r = motor.buscar("shadow of morder")
    assert r["itens"] == [] and nomes_de(r, "sugestoes") == ["Middle-earth: Shadow of Mordor"]                 # "Shadow of War" não: "morder" ≠ "war"
    assert nomes_de(motor.buscar("cyberpnk 2077"), "sugestoes") == ["Cyberpunk 2077"]
    assert nomes_de(motor.buscar("batmna arkham"), "sugestoes") == ["Batman: Arkham Knight", "Batman: Arkham VR"]


def test_sugestoes_evitam_resultados_evidentemente_incorretos(motor):
    for ruim in ("zelda", "xyz", "qqqq wwww", "shadow of morder xyzzy", "gta", "bat", "ab"):
        r = motor.buscar(ruim)
        assert r["sugestoes"] == [] or all(ruim.split()[0][:3] in s["nome"].lower() for s in r["sugestoes"]), (ruim, nomes_de(r, "sugestoes"))
    assert motor.buscar("zelda")["sugestoes"] == [] and motor.buscar("qqqq wwww")["sugestoes"] == []
    assert motor.buscar("")["itens"] == [] and motor.buscar("   ::: ")["sugestoes"] == []


def test_sugestao_so_aparece_quando_nao_ha_resultado_e_e_limitada():
    muitos = [f"Batman Arkham Knigth Edição {n}" for n in range(40)]
    m = bi.Motor(doc(muitos), [])
    r = m.buscar("batman arkam")                                                         # typo em 'arkham'
    assert r["itens"] == [] and 0 < len(r["sugestoes"]) <= bi.MAX_SUGESTOES
    assert m.buscar("batman")["sugestoes"] == []                                         # com resultados, nenhuma sugestão


def test_nao_altera_o_indice_nem_os_qids(motor):
    antes = json.dumps(motor.indice, sort_keys=True)
    motor.buscar("shadow of morder")
    motor.buscar("gta v")
    assert json.dumps(motor.indice, sort_keys=True) == antes


def test_arquivo_de_apelidos_do_repositorio_e_valido():
    a = bi.carregar_apelidos(str(ROOT / "data" / "apelidos.json"))
    assert a and all(x["alvo"] and x["apelidos"] for x in a) and bi.carregar_apelidos("/nao/existe.json") == []
