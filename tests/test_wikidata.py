"""Importador Wikidata -> índice de busca. IMPORTANTE: os dados abaixo são SIMULADOS no formato documentado da resposta SPARQL
(Q-ids inventados 99000xxxx); não são dados reais do Wikidata (a rede deste ambiente não alcança o serviço)."""
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from ps4store import busca, wikidata
from ps4store.wikidata import UA_PADRAO, baixar_tudo, consulta, fetch_http, main, para_itens, url_pagina

ROOT = Path(__file__).resolve().parents[1]
FONTES = str(ROOT / "config" / "busca-fontes.json")


def L(v, lang=None):
    d = {"type": "literal", "value": v}
    if lang:
        d["xml:lang"] = lang
    return d


def row(q, en=None, pt=None, enwiki=None, ptwiki=None, data=None):
    b = {"g": {"type": "uri", "value": f"http://www.wikidata.org/entity/Q{q}"}}
    if en:
        b["label_en"] = L(en, "en")
    if pt:
        b["label_pt"] = L(pt, "pt")
    if enwiki:
        b["enwiki"] = {"type": "uri", "value": enwiki}
    if ptwiki:
        b["ptwiki"] = {"type": "uri", "value": ptwiki}
    if data:
        b["data"] = {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#dateTime", "value": data}
    return b


SIM = [
    row(990000001, "Batman: Arkham Knight", "Batman: Arkham Knight", "https://en.wikipedia.org/wiki/Batman:_Arkham_Knight", None, "2015-06-23T00:00:00Z"),
    row(990000002, None, "Batman: Arkham VR", None, "https://pt.wikipedia.org/wiki/Batman:_Arkham_VR", "2016-01-01T00:00:00Z"),
    row(990000003, "LEGO Batman 3: Beyond Gotham", "LEGO Batman 3: Além de Gotham"),                 # sem Wikipedia e sem data
    row(990000004, "LEGO Batman: The Videogame", None, "https://en.wikipedia.org/wiki/Lego_Batman:_The_Videogame"),
    row(990000005),                                                                                  # sem rótulo en/pt
    row(990000006, "Spider-Man", None, "http://evil.example/wiki/Spider-Man"),                        # URL fora da Wikipedia https: ignorada
    row(990000001, "Batman: Arkham Knight", None, None, "https://pt.wikipedia.org/wiki/Batman:_Arkham_Knight", "2015-06-24T00:00:00Z"),   # 2ª linha do mesmo item
    {"g": {"type": "uri", "value": "http://exemplo.invalid/entity/Q1"}, "label_en": L("Fora do padrão", "en")},                          # não é entidade Wikidata
]


def por_nome(itens):
    return {i["nome"]: i for i in itens}


# ---------- mapeamento: nada inventado ----------
def test_para_itens_preserva_nomes_ids_e_urls_e_nao_inventa():
    itens, est = para_itens(SIM)
    m = por_nome(itens)
    k = m["Batman: Arkham Knight"]
    assert k["idFonte"] == "wikidata:Q990000001" and k["url"] == "https://en.wikipedia.org/wiki/Batman:_Arkham_Knight" and k["lancamento"] == "2015"
    assert k["referencias"] == {"wikidata": "https://www.wikidata.org/wiki/Q990000001", "wikipedia-en": "https://en.wikipedia.org/wiki/Batman:_Arkham_Knight",
                                "wikipedia-pt": "https://pt.wikipedia.org/wiki/Batman:_Arkham_Knight"} and "aliases" not in k       # linhas do mesmo item foram unidas
    vr = m["Batman: Arkham VR"]                                                                                                       # só rótulo pt
    assert vr["url"] == "https://pt.wikipedia.org/wiki/Batman:_Arkham_VR" and vr["lancamento"] == "2016"
    l3 = m["LEGO Batman 3: Beyond Gotham"]                                                                                           # sem Wikipedia: cai para o Wikidata
    assert l3["url"] == "https://www.wikidata.org/wiki/Q990000003" and "lancamento" not in l3 and l3["aliases"] == ["LEGO Batman 3: Além de Gotham"]
    assert "referencias" in m["Spider-Man"] and list(m["Spider-Man"]["referencias"]) == ["wikidata"]                                    # URL ruim ignorada, não inventada
    assert m["Spider-Man"]["url"] == "https://www.wikidata.org/wiki/Q990000006"
    assert est == {"itensWikidata": 6, "importaveis": 5, "semRotulo": 1, "comWikipedia": 3, "comAno": 2}
    assert all(k in ("nome", "url", "idFonte", "referencias", "aliases", "lancamento") for i in itens for k in i)                   # nenhum campo de download/CUSA


def test_ano_so_quando_a_data_existe_e_e_valida():
    itens, _ = para_itens([row(990000010, "X", data="não é data"), row(990000011, "Y", data="2019-11-05T00:00:00Z"), row(990000012, "Z")])
    m = por_nome(itens)
    assert "lancamento" not in m["X"] and m["Y"]["lancamento"] == "2019" and "lancamento" not in m["Z"]


# ---------- consulta e rede ----------
def test_consulta_usa_ps4_e_jogo_e_so_inteiros_no_limite():
    q = consulta(1000, 2000)
    assert "wdt:P400 wd:Q5014725" in q and "wd:Q7889" in q and "LIMIT 1000 OFFSET 2000" in q
    assert url_pagina(10, 0).startswith("https://query.wikidata.org/sparql?format=json&query=")
    assert "LIMIT 5 OFFSET 7" in consulta("5", "7") and "5; DROP" not in consulta(5, 7)
    with pytest.raises(ValueError):
        consulta("1; DELETE", 0)


def paginas(total, tamanho):
    """fetch falso: devolve `total` itens distintos fatiados pelo OFFSET pedido (1 linha por item)."""
    def f(url):
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
        off = int(q.split("OFFSET ")[1].split(")")[0].split()[0])
        lim = int(q.split("LIMIT ")[1].split()[0])
        rows = [row(990100000 + n, f"Jogo {n}") for n in range(off, min(off + lim, total))]
        return json.dumps({"results": {"bindings": rows}}).encode()
    return f


def test_paginacao_ate_pagina_incompleta_e_com_pausa_entre_paginas():
    esperas, prog = [], []
    bind, avisos = baixar_tudo(paginas(2500, 1000), 1000, 40, 1.5, dormir=esperas.append, progresso=lambda p, n: prog.append((p, n)))
    assert len(bind) == 2500 and avisos == [] and esperas == [1.5, 1.5] and prog == [(1, 1000), (2, 2000), (3, 2500)]
    itens, _ = para_itens(bind)
    assert len(itens) == 2500


def test_teto_de_paginas_avisa_que_pode_haver_mais():
    bind, avisos = baixar_tudo(paginas(10_000, 1000), 1000, 3, 0, dormir=lambda s: None)
    assert len(bind) == 3000 and avisos and "teto de 3" in avisos[0]


def test_fetch_http_so_fala_com_o_host_do_servico_e_usa_user_agent_do_usuario(monkeypatch):
    for ruim in ("http://query.wikidata.org/sparql", "https://example.com/sparql", "https://query.wikidata.org.evil.com/x"):
        with pytest.raises(ValueError):
            fetch_http(ruim, "UA")
    vistos = []

    class R:
        def __init__(self, b):
            self.b = b

        def read(self, n):
            return self.b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        vistos.append(req.get_header("User-agent"))
        return R(b"{}")

    monkeypatch.setattr(wikidata.urllib.request, "urlopen", urlopen)
    assert fetch_http("https://query.wikidata.org/sparql?x=1", "MeuApp/1.0 (contato)") == b"{}" and vistos == ["MeuApp/1.0 (contato)"]


def test_fetch_http_respeita_retry_after_em_429_e_desiste_depois(monkeypatch):
    n = {"c": 0}
    esperas = []

    def urlopen(req, timeout):
        n["c"] += 1
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "7"}, io.BytesIO(b""))

    monkeypatch.setattr(wikidata.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        fetch_http("https://query.wikidata.org/sparql", "UA", tentativas=3, dormir=esperas.append)
    assert n["c"] == 3 and esperas == [7, 7]


def test_user_agent_padrao_nao_expoe_dados_do_usuario_ou_do_projeto():
    assert "ps4store" not in UA_PADRAO.lower() and "justino" not in UA_PADRAO.lower() and "@" not in UA_PADRAO


# ---------- ponta a ponta: importar -> índice offline -> busca ----------
def fetch_sim(url):
    return json.dumps({"results": {"bindings": SIM if "OFFSET 0" in urllib.parse.unquote(url) else []}}).encode()


def test_atualizar_gera_cache_e_indice_e_a_busca_acha_batman_e_lego_batman(tmp_path, capsys):
    idx, cache = str(tmp_path / "idx.json"), str(tmp_path / "cache.json")
    rc = main(["--atualizar", "--cache", cache, "--indice", idx, "--fontes", FONTES, "--pausa", "0", "--user-agent", "T/1 (x)"], fetch=fetch_sim)
    out = capsys.readouterr().out
    assert rc == 0 and "5 importado(s)" in out and "6 jogo(s) de PS4" in out and "1 sem rótulo" in out and "não indicam que exista PKG" in out
    doc = busca.carregar_indice(idx)
    f = doc["fontes"]["wikidata"]
    assert f["licenca"] == "CC0-1.0" and f["origem"] == "https://www.wikidata.org/" and f["obtidoEm"] and f["itens"] == 5
    res = busca.buscar(doc, "Batman")
    assert [r["nome"] for r in res] == ["Batman: Arkham Knight", "Batman: Arkham VR", "LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame"]
    assert [r["nome"] for r in busca.buscar(doc, "lego batman")] == ["LEGO Batman 3: Beyond Gotham", "LEGO Batman: The Videogame"]
    assert [r["nome"] for r in busca.buscar(doc, "alem de gotham")] == ["LEGO Batman 3: Beyond Gotham"]          # alias pt, sem acento
    assert all(r["url"].startswith("https://") and "download" not in r["url"] for r in res)
    assert busca.main(["--indice", idx, "Batman"]) == 0
    saida = capsys.readouterr().out
    assert "Metadados de 'wikidata': licença CC0-1.0" in saida and "wikidata:Q990000001" in saida and "(2015)" in saida and "não indicam que exista PKG" in saida


def test_offline_reconstroi_sem_rede_e_mantem_outras_fontes(tmp_path, capsys):
    idx, cache = str(tmp_path / "idx.json"), str(tmp_path / "cache.json")
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(FONTES), "teste", [{"nome": "Batman Teste", "url": "https://exemplo.invalid/t"}])
    busca.salvar_indice(d, idx)
    wikidata.salvar_cache(SIM, cache)

    def sem_rede(url):
        raise AssertionError("não deve usar a rede")

    assert main(["--offline", "--cache", cache, "--indice", idx, "--fontes", FONTES], fetch=sem_rede) == 0
    capsys.readouterr()
    doc = busca.carregar_indice(idx)
    assert {t["fonte"] for t in doc["titulos"]} == {"teste", "wikidata"} and len(doc["titulos"]) == 6
    assert main(["--offline", "--cache", cache, "--indice", idx, "--fontes", FONTES]) == 0                  # reimportar substitui, não duplica
    assert len(busca.carregar_indice(idx)["titulos"]) == 6


def test_erros_claros(tmp_path, capsys):
    assert main([]) == 2 and main(["--atualizar", "--offline"]) == 2
    assert main(["--offline", "--cache", str(tmp_path / "nao.json"), "--indice", str(tmp_path / "i.json")]) == 2
    assert "cache não encontrado" in capsys.readouterr().err

    def quebra(url):
        raise urllib.error.URLError("sem rede")

    assert main(["--atualizar", "--cache", str(tmp_path / "c.json"), "--indice", str(tmp_path / "i.json"), "--pausa", "0"], fetch=quebra) == 1
    assert not (tmp_path / "i.json").exists()                                                               # falha de rede não cria índice vazio
