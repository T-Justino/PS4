"""Auditoria dos conflitos de CUSA: classificação só com evidência local; somente leitura dos dados. Dados simulados (Q-ids 99100xxxx, CUSA 900xx)."""
import hashlib
import json
from pathlib import Path

import pytest

from ps4store import auditoria, busca, cusas, versoes
from ps4store.auditoria import RELACIONADO, CONTRADITORIA, INDETERMINADO, auditar, main, relacao_nomes

ROOT = Path(__file__).resolve().parents[1]
SEMENTE = str(ROOT / "data" / "versoes-cusa.json")
FONTES = str(ROOT / "config" / "busca-fontes.json")
BAK = "Q15891648"

JOGOS = [(BAK, "Batman: Arkham Knight", "2015"),
         ("Q99100001", "Middle-earth: Shadow of Mordor", "2014"), ("Q99100002", "Middle-earth: Shadow of Mordor - Game of the Year Edition", "2015"),
         ("Q99100003", "Jogo Base Alfa", None), ("Q99100004", "Jogo Base Alfa Pacote Extra", None),
         ("Q99100005", "Racing Thunder", "2010"), ("Q99100006", "Cooking Quest", "2019"),
         ("Q99100007", "Batman Arkham Origins Sim", None), ("Q99100008", "Batman Arkham City Sim", None),
         ("Q99100009", "Duplicado", None), ("Q99100010", "Duplicado", None),
         ("Q99100011", "Outro Jogo Qualquer", None), ("Q99100012", "Batman: Arkham Knight Premium Edition", None),
         ("Q99100013", "Alpha One", None), ("Q99100014", "Alpha One Deluxe Edition", None), ("Q99100015", "Zeta Totally Different", None),
         ("Q99100016", "Gemeo Jogo Um", None), ("Q99100017", "Gemeo Jogo Dois", None)]
LINHAS = [
    ["Q99100001", "CUSA90001"], ["Q99100002", "CUSA90001"],                                                              # A: nome contido + marcador (edition)
    ["Q99100003", "EP0000-CUSA90002_00-BASEALFAAAAAAAAA"], ["Q99100004", "EP0000-CUSA90002_00-DLCEXTRAAAAAAAAA"],         # B: Content IDs diferentes
    ["Q99100005", "CUSA90003"], ["Q99100006", "CUSA90003"],                                                              # C: nomes sem relação
    ["Q99100007", "CUSA90004"], ["Q99100008", "CUSA90004"],                                                              # D: mesma série
    ["Q99100009", "CUSA90005"], ["Q99100010", "CUSA90005"],                                                              # E: mesmo nome
    ["Q99100011", "CUSA00133"],                                                                                          # F: contradiz o curado (nomes sem relação)
    ["Q99100012", "CUSA00135"],                                                                                          # G: contradiz o curado, mas nome contido + marcador
    ["Q99100013", "CUSA90006"], ["Q99100014", "CUSA90006"], ["Q99100015", "CUSA90006"],                                  # H: três jogos
    ["Q99100016", "EP0000-CUSA90007_00-SAMEPRODUCTAAAAA"], ["Q99100017", "EP0000-CUSA90007_00-SAMEPRODUCTAAAAA"],        # I: mesmo Content ID
]


@pytest.fixture(scope="module")
def cenario(tmp_path_factory):
    t = tmp_path_factory.mktemp("aud")
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", [{"nome": n, "url": f"https://www.wikidata.org/wiki/{q}", "idFonte": f"wikidata:{q}", **({"lancamento": a} if a else {})}
                                                                for q, n, a in JOGOS])
    ip = t / "idx.json"
    busca.salvar_indice(d, str(ip))
    cur = versoes.carregar(SEMENTE)
    doc = cusas.construir({"P5971": {"rotulo": "Europe PlayStation Store ID", "consultadoEm": "2026-11-23", "linhas": LINHAS}}, busca.carregar_indice(str(ip)), cur, "2026-11-23")
    dp = t / "dados.json"
    dp.write_text(json.dumps(doc), encoding="utf-8")
    return {"dir": t, "indice": str(ip), "dados": str(dp), "doc": doc, "cur": cur}


def rel(cenario):
    return auditar(cenario["doc"], busca.carregar_indice(cenario["indice"]), cenario["cur"])


def por_cusa(r):
    return {c["cusa"]: c for c in r["conflitos"]}


def test_o_cenario_produz_os_conflitos_esperados(cenario):
    assert {c["cusa"] for c in cenario["doc"]["conflitos"]} == {"CUSA90001", "CUSA90002", "CUSA90003", "CUSA90004", "CUSA90005", "CUSA00133", "CUSA00135", "CUSA90006", "CUSA90007"}


@pytest.mark.parametrize("cusa,classe,nivel,trecho", [
    ("CUSA90001", RELACIONADO, "nomes", "marcador de edição/pacote (edition)"),
    ("CUSA90002", RELACIONADO, "content-id", "Content IDs DIFERENTES"),
    ("CUSA90003", CONTRADITORIA, "nomes-sem-relacao", "nenhuma palavra significativa em comum"),
    ("CUSA90004", INDETERMINADO, "nenhuma", "mesma série"),
    ("CUSA90005", INDETERMINADO, "nenhuma", "mesmo nome"),
    ("CUSA00133", CONTRADITORIA, "fonte-oficial-curada", "registro curado deste CUSA tem fonte oficial citada: Batman: Arkham Knight [Q15891648]"),
    ("CUSA00135", RELACIONADO, "nomes", "Premium Edition" if False else "marcador de edição/pacote (premium, edition)"),
    ("CUSA90006", CONTRADITORIA, "nomes-sem-relacao", "Alpha One × Zeta Totally Different"),
    ("CUSA90007", INDETERMINADO, "nenhuma", "MESMO Content ID")])
def test_classificacao_so_com_evidencia_local(cenario, cusa, classe, nivel, trecho):
    c = por_cusa(rel(cenario))[cusa]
    assert c["classificacao"] == classe and c["nivelEvidencia"] == nivel and any(trecho in j for j in c["justificativas"]), c["justificativas"]
    assert c["revisaoPendente"] is True                                                    # nada é resolvido automaticamente


def test_cada_conflito_mostra_qids_nomes_content_ids_e_propriedades_de_origem(cenario):
    c = por_cusa(rel(cenario))["CUSA90002"]
    a, b = c["jogos"]
    assert (a["qid"], a["nome"], a["contentIds"]) == ("Q99100003", "Jogo Base Alfa", ["EP0000-CUSA90002_00-BASEALFAAAAAAAAA"])
    assert (b["qid"], b["nome"], b["contentIds"]) == ("Q99100004", "Jogo Base Alfa Pacote Extra", ["EP0000-CUSA90002_00-DLCEXTRAAAAAAAAA"])
    assert a["propriedades"] == [{"propriedade": "P5971", "rotulo": "Europe PlayStation Store ID", "valor": "EP0000-CUSA90002_00-BASEALFAAAAAAAAA", "consultadoEm": "2026-11-23"}]
    m = por_cusa(rel(cenario))["CUSA90001"]["jogos"]
    assert m[0]["ano"] == "2014" and m[1]["ano"] == "2015" and m[0]["contentIds"] == [] and m[0]["propriedades"][0]["valor"] == "CUSA90001"
    f = por_cusa(rel(cenario))["CUSA00133"]
    assert {j["qid"]: j["curado"] for j in f["jogos"]} == {"Q99100011": False, BAK: True}
    assert next(j for j in f["jogos"] if j["qid"] == BAK)["contentIds"] == ["UP1018-CUSA00133_00-B000000000001563", "UP1018-CUSA00133_00-ASIA000000000003"]


def test_tipo_de_produto_fica_desconhecido_e_so_ha_indicios_nao_confirmados(cenario):
    r = rel(cenario)
    for c in r["conflitos"]:
        assert all(j["tipoProduto"] == "desconhecido" for j in c["jogos"])                  # nunca afirma jogo-base/edição/DLC
    dlc = next(j for j in por_cusa(r)["CUSA90002"]["jogos"] if j["qid"] == "Q99100004")
    assert dlc["indicios"] == ["sufixo \"DLCEXTRAAAAAAAAA\" no Content ID EP0000-CUSA90002_00-DLCEXTRAAAAAAAAA: indício de DLC (NÃO confirmado)"] and dlc["tipoProduto"] == "desconhecido"
    base = next(j for j in por_cusa(r)["CUSA90002"]["jogos"] if j["qid"] == "Q99100003")
    assert base["indicios"] == []
    assert "NÃO confirmado" in json.dumps(r, ensure_ascii=False) and "jogo-base" not in json.dumps([j["tipoProduto"] for c in r["conflitos"] for j in c["jogos"]])


def test_resumo_e_aviso_de_nao_verificado(cenario):
    r = rel(cenario)
    assert r["resumo"]["conflitos"] == 9 and r["resumo"]["possivel_produto_relacionado"] == 3 and r["resumo"]["associacao_contraditoria"] == 3 and r["resumo"]["indeterminado"] == 3
    assert sum(r["resumo"]["porMotivo"].values()) == 9 and "contradiz o registro curado: o CUSA já está cadastrado para outro Q-id" in r["resumo"]["porMotivo"]
    assert "Nada foi associado, apagado ou substituído" in r["aviso"] and r["schema"] == auditoria.SCHEMA


@pytest.mark.parametrize("a,b,esperado", [
    ("Middle-earth: Shadow of Mordor", "Middle-earth: Shadow of Mordor - Game of the Year Edition", "contido-com-marcador"),
    ("Batman", "Batman: Arkham Knight", "contido-sem-marcador"), ("The Witcher 3", "Witcher 3", "mesmo-nome"),
    ("Racing Thunder", "Cooking Quest", "sem-relacao"), ("Batman Arkham City", "Batman Arkham Origins", "parcial"), ("", "x", "parcial")])
def test_relacao_entre_nomes(a, b, esperado):
    assert relacao_nomes(a, b)[0] == esperado


# ---------- somente leitura; relatório; terminal ----------
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_auditoria_nao_modifica_dados_originais_e_grava_so_o_relatorio(cenario, tmp_path, capsys):
    arqs = [cenario["dados"], cenario["indice"], SEMENTE]
    antes = [(sha(p), Path(p).stat().st_mtime_ns) for p in arqs]
    ls_antes = sorted(p.name for p in cenario["dir"].iterdir())
    saida = tmp_path / "rel" / "aud.json"
    rc = main(["--dados", cenario["dados"], "--indice", cenario["indice"], "--versoes", SEMENTE, "--saida", str(saida)])
    out = capsys.readouterr().out
    assert rc == 0 and [(sha(p), Path(p).stat().st_mtime_ns) for p in arqs] == antes and sorted(p.name for p in cenario["dir"].iterdir()) == ls_antes
    rel_ = json.loads(saida.read_text(encoding="utf-8"))
    assert rel_["entradas"]["dados"]["sha256"] == antes[0][0] and rel_["entradas"]["versoes"]["sha256"] == antes[2][0] and len(rel_["conflitos"]) == 9
    d = cusas.carregar_dados(cenario["dados"])
    assert not [r for r in d["registros"] if r["cusa"] in {c["cusa"] for c in d["conflitos"]}]                   # conflitos continuam sem associação
    assert "9 conflito(s)" in out and "possível produto relacionado: 3 · associação contraditória: 3 · indeterminado: 3" in out
    assert "nada foi associado automaticamente" in out and "Os dados originais não foram alterados" in out and "não verificados oficialmente" in out


def test_resumo_no_terminal_filtros_limite_e_detalhe(cenario, tmp_path, capsys):
    base = ["--dados", cenario["dados"], "--indice", cenario["indice"], "--versoes", SEMENTE, "--saida", str(tmp_path / "a.json")]
    assert main(base + ["--classe", "contraditoria"]) == 0
    out = capsys.readouterr().out
    assert "== associação contraditória (3)" in out and "== possível produto" not in out and "indeterminado (" not in out.split("==")[-1][:5]
    assert "Q99100005 Racing Thunder (2010) · P5971=CUSA90003" in out and "→ Racing Thunder × Cooking Quest: os nomes não têm nenhuma palavra significativa em comum" in out
    assert main(base + ["--cusa", "cusa90002"]) == 0
    out = capsys.readouterr().out
    assert out.count("CUSA90002 ·") == 1 and "indício: sufixo \"DLCEXTRAAAAAAAAA\"" in out and "CUSA90001 ·" not in out
    assert main(base + ["--limite", "1"]) == 0
    out = capsys.readouterr().out
    assert "… e mais 2 (use --todos ou --classe)" in out
    assert main(base + ["--todos"]) == 0 and "… e mais" not in capsys.readouterr().out


def test_erros_claros_sem_dados_ou_arquivo_invalido(tmp_path, capsys):
    assert main(["--dados", str(tmp_path / "nada.json"), "--indice", str(tmp_path / "i.json"), "--versoes", SEMENTE, "--saida", str(tmp_path / "s.json")]) == 2
    assert "sem dados de CUSAs" in capsys.readouterr().err and not (tmp_path / "s.json").exists()
    (tmp_path / "ruim.json").write_text("{}", encoding="utf-8")
    assert main(["--dados", str(tmp_path / "ruim.json"), "--saida", str(tmp_path / "s.json")]) == 2


def test_carregar_auditoria_tolera_ausente_ou_invalido(tmp_path):
    assert auditoria.carregar_auditoria(str(tmp_path / "nao.json")) == {"schema": auditoria.SCHEMA, "conflitos": []}
    (tmp_path / "x.json").write_text("lixo", encoding="utf-8")
    assert auditoria.carregar_auditoria(str(tmp_path / "x.json"))["conflitos"] == []


def test_modulo_nao_usa_rede_nem_modulos_proibidos():
    f = (ROOT / "src" / "ps4store" / "auditoria.py").read_text(encoding="utf-8")
    for proibido in ("urllib", "socket", "http.", "resolver", "colar", "browser", "subprocess"):
        assert proibido not in f.replace("não usa o resolvedor", ""), proibido
