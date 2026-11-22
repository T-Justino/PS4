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
    """fetch falso (modo DISTINCT): devolve `total` jogos distintos fatiados pelo OFFSET pedido (1 linha por jogo)."""
    def f(url):
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
        off = int(q.split("OFFSET ")[1].split(")")[0].split()[0])
        lim = int(q.split("LIMIT ")[1].split()[0])
        rows = [row(990100000 + n, f"Jogo {n}") for n in range(off, min(off + lim, total))]
        return json.dumps({"results": {"bindings": rows}}).encode()
    return f


def test_paginacao_termina_em_pagina_vazia_sem_contagem_e_pausa_entre_paginas():
    esperas, prog = [], []
    c = baixar_tudo(paginas(2500, 1000), 1000, 40, 1.5, dormir=esperas.append, progresso=lambda p, n: prog.append((p, n)))
    assert len(c.linhas) == 2500 and len(c.qids) == 2500 and esperas == [1.5, 1.5, 1.5] and prog == [(1, 1000), (2, 2000), (3, 2500), (4, 2500)]
    assert c.completa and not c.validada and any("NÃO pôde ser conferida" in a for a in c.avisos)
    itens, _ = para_itens(c.linhas)
    assert len(itens) == 2500


def test_com_contagem_para_ao_atingi_la_sem_pedir_pagina_extra_e_valida():
    pedidos = []

    def f(url):
        pedidos.append(url)
        return paginas(2500, 1000)(url)

    c = baixar_tudo(f, 1000, 40, 0, dormir=lambda s: None, esperado=2500)
    assert len(pedidos) == 3 and c.completa and c.validada and c.motivo == "" and c.avisos == []


def test_teto_de_paginas_marca_incompleta():
    c = baixar_tudo(paginas(10_000, 1000), 1000, 3, 0, dormir=lambda s: None)
    assert len(c.qids) == 3000 and any("teto de 3" in a for a in c.avisos) and not c.completa
    c2 = baixar_tudo(paginas(10_000, 1000), 1000, 3, 0, dormir=lambda s: None, esperado=10_000)
    assert not c2.completa and "3000 de 10000" in c2.motivo and "30.0%" in c2.motivo


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
    q = urllib.parse.unquote(url)
    if "COUNT(DISTINCT" in q:
        return json.dumps({"results": {"bindings": [{"n": {"type": "literal", "value": "6"}}]}}).encode()
    return json.dumps({"results": {"bindings": SIM if "OFFSET 0" in q else []}}).encode()


def test_atualizar_gera_cache_e_indice_e_a_busca_acha_batman_e_lego_batman(tmp_path, capsys):
    idx, cache = str(tmp_path / "idx.json"), str(tmp_path / "cache.json")
    rc = main(["--atualizar", "--cache", cache, "--indice", idx, "--fontes", FONTES, "--pausa", "0", "--user-agent", "T/1 (x)"], fetch=fetch_sim)
    out = capsys.readouterr().out
    assert rc == 0 and "5 importado(s)" in out and "6 jogo(s) de PS4" in out and "1 sem rótulo" in out and "não indicam que exista PKG" in out
    assert "conferido: 6 de 6 da contagem do serviço" in out and "PARCIAL" not in out
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


# ---------- teste rápido (--testar): não grava nada ----------
def fetch_testar(url):
    q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
    if "COUNT(DISTINCT" in q:
        return json.dumps({"results": {"bindings": [{"n": {"type": "literal", "value": "1234"}}]}}).encode()
    assert 'CONTAINS(LCASE(?l), "batman")' in q
    return json.dumps({"results": {"bindings": [x for x in SIM if "Batman" in json.dumps(x)]}}).encode()


def test_testar_lista_do_servico_sem_gravar_nada(tmp_path, capsys):
    idx, cache = tmp_path / "idx.json", tmp_path / "cache.json"
    rc = main(["--testar", "--cache", str(cache), "--indice", str(idx)], fetch=fetch_testar)
    out = capsys.readouterr().out
    assert rc == 0 and "(contagem do serviço): 1234" in out and "Batman: Arkham Knight" in out and "LEGO Batman: The Videogame" in out
    assert "Nada foi gravado" in out and "não indicam PKG" in out and not idx.exists() and not cache.exists()


def test_testar_com_termo_e_contagem_ausente_nao_inventa_numero(capsys):
    def f(url):
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
        assert 'CONTAINS(LCASE(?l), "spider-man")' in q or "COUNT(DISTINCT" in q
        return json.dumps({"results": {"bindings": []}}).encode()

    assert main(["--testar", "Spider-Man"], fetch=f) == 0
    out = capsys.readouterr().out
    assert "não obtida" in out and 'Com "Spider-Man" no nome: 0' in out


def test_termo_do_teste_nao_injeta_sparql():
    q = wikidata.consulta_nome('x") } DELETE { ?s ?p ?o } #\\ "y')
    lit = q.split('CONTAINS(LCASE(?l), "')[1].split('")')[0]                 # o que vai dentro do literal
    assert not any(c in lit for c in '"\\{}#()?') and lit == "x delete s p o y"
    assert q.count("{") == q.count("}")                                      # estrutura da consulta intacta
    assert wikidata._literal("Pokémon: Café-Mix!") == "pokémon: café-mix!"


def test_testar_nao_combina_com_atualizar(capsys):
    assert main(["--testar", "--atualizar"]) == 2


def test_testar_erro_de_rede_e_claro(capsys):
    def quebra(url):
        raise urllib.error.URLError("sem rede")

    assert main(["--testar"], fetch=quebra) == 1 and "URLError" in capsys.readouterr().err


# ---------- REGRESSÃO (relato real no Termux): total 6.628, 1ª página com 988 linhas / 947 jogos e coleta encerrada cedo ----------
TOTAL = 6628
LEGO3 = 5200                                   # o LEGO Batman 3 só aparece bem depois da 1ª página
NOMES = {10: "Batman: Arkham Knight", 2000: "Batman: Arkham VR", 3500: "Batman: The Telltale Series", LEGO3: "LEGO Batman 3: Beyond Gotham",
         6000: "LEGO Batman: The Videogame"}


def _bag():
    out = []
    for i in range(TOTAL):
        out.append(i)
        if i % 18 == 0:
            out.append(i)                      # o mesmo jogo por 2 caminhos de classe: duplicata que o antigo `SELECT ?g` contava no LIMIT
    return out


def _rows(ids):
    linhas = []
    for i in ids:
        linhas.append(row(990200000 + i, NOMES.get(i, f"Jogo {i}")))
        if i % 23 == 5:                                                  # 2ª linha do mesmo jogo (outra Wikipedia)
            linhas.append(row(990200000 + i, NOMES.get(i, f"Jogo {i}"), None, None, f"https://pt.wikipedia.org/wiki/J{i}"))
    return linhas


def servidor(modo="distinct", conta=TOTAL, corta_em=None, perde=0, log=None):
    """Simula o serviço. modo 'bag' = o comportamento do `SELECT ?g` sem DISTINCT (LIMIT conta linhas repetidas)."""
    bag = _bag()

    def f(url):
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
        if log is not None:
            log.append(q)
        if "COUNT(DISTINCT" in q:
            if conta is None:
                raise urllib.error.URLError("sem contagem")
            return json.dumps({"results": {"bindings": [{"n": {"type": "literal", "value": str(conta)}}]}}).encode()
        off = int(q.split("OFFSET ")[1].split(")")[0].split()[0])
        lim = int(q.split("LIMIT ")[1].split()[0])
        if corta_em is not None and off >= corta_em:
            return json.dumps({"results": {"bindings": []}}).encode()
        if modo == "bag":
            ids = sorted(set(bag[off:off + lim]))
        else:
            ids = list(range(off, min(off + lim, TOTAL)))
        ids = [i for i in ids if i >= perde] if perde else ids
        return json.dumps({"results": {"bindings": _rows(ids)}}).encode()
    return f


def test_cenario_do_relato_primeira_pagina_988_linhas_947_jogos():
    p1 = json.loads(servidor("bag")(url_pagina(1000, 0)))["results"]["bindings"]
    assert len(p1) == 988 and len({b["g"]["value"] for b in p1}) == 947          # exatamente o que o Termux mostrou
    assert 947 < 1000                                                               # a regra antiga ("página curta = fim") encerraria aqui


def test_consulta_de_pagina_usa_subconsulta_distinct():
    assert "SELECT DISTINCT ?g WHERE" in consulta(1000, 0)


def test_pagina_curta_nao_encerra_e_coleta_os_6628_jogos(tmp_path, capsys):
    log = []
    c = baixar_tudo(servidor("bag", log=log), 1000, 40, 0, dormir=lambda s: None, esperado=TOTAL)
    assert len(c.qids) == TOTAL and c.completa and c.validada and c.paginas > 1
    idx, cache = str(tmp_path / "i.json"), str(tmp_path / "c.json")
    assert main(["--atualizar", "--cache", cache, "--indice", idx, "--fontes", FONTES, "--pausa", "0", "--user-agent", "T/1 (x)"], fetch=servidor("bag")) == 0
    out = capsys.readouterr().out
    assert f"conferido: {TOTAL} de {TOTAL} da contagem do serviço" in out and f"{TOTAL} importado(s)" in out
    doc = busca.carregar_indice(idx)
    assert len(doc["titulos"]) == TOTAL
    assert "LEGO Batman 3: Beyond Gotham" in [r["nome"] for r in busca.buscar(doc, "lego batman")]                   # só existe depois da 1ª página
    assert {r["nome"] for r in busca.buscar(doc, "Batman")} == set(NOMES.values())                                     # os 5 Batman, não 4


def test_modo_distinct_pagina_exata_e_para_ao_atingir_a_contagem():
    log = []
    c = baixar_tudo(servidor("distinct", log=log), 1000, 40, 0, dormir=lambda s: None, esperado=TOTAL)
    assert c.paginas == 7 and len(c.qids) == TOTAL and c.completa and sum("OFFSET" in q for q in log) == 7


def test_coleta_encerrada_cedo_e_incompleta_nao_substitui_o_indice_valido(tmp_path, capsys):
    idx, cache = tmp_path / "i.json", tmp_path / "c.json"
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", [{"nome": "Antigo Válido", "url": "https://www.wikidata.org/wiki/Q1", "idFonte": "wikidata:Q1"}])
    busca.salvar_indice(d, str(idx))
    wikidata.salvar_cache(SIM, str(cache))
    antes_i, antes_c = idx.read_bytes(), cache.read_bytes()
    rc = main(["--atualizar", "--cache", str(cache), "--indice", str(idx), "--fontes", FONTES, "--pausa", "0"], fetch=servidor("bag", corta_em=1000))
    err = capsys.readouterr().err
    assert rc == 1 and "INCOMPLETA" in err and "coletados 947 de 6628" in err and "14.3%" in err
    assert idx.read_bytes() == antes_i and cache.read_bytes() == antes_c                                 # nada foi substituído
    parcial = json.loads((tmp_path / "c.parcial.json").read_text(encoding="utf-8"))
    assert parcial["completa"] is False and parcial["coletados"] == 947 and parcial["esperados"] == TOTAL


def test_aceitar_parcial_importa_mas_marca_o_indice_e_a_busca_avisa(tmp_path, capsys):
    idx, cache = str(tmp_path / "i.json"), str(tmp_path / "c.json")
    rc = main(["--atualizar", "--aceitar-parcial", "--cache", cache, "--indice", idx, "--fontes", FONTES, "--pausa", "0"], fetch=servidor("bag", corta_em=1000))
    out = capsys.readouterr().out
    assert rc == 0 and "PARCIAL" in out and "947 de 6628" in out
    f = busca.carregar_indice(idx)["fontes"]["wikidata"]
    assert f["parcial"] is True and f["coletados"] == 947 and f["esperados"] == TOTAL
    assert busca.main(["--indice", idx, "Jogo 10"]) == 0
    assert "é PARCIAL (947 de 6628 jogos)" in capsys.readouterr().out


def test_sem_contagem_termina_em_pagina_vazia_mas_avisa_que_nao_foi_conferida(tmp_path, capsys):
    idx, cache = str(tmp_path / "i.json"), str(tmp_path / "c.json")
    rc = main(["--atualizar", "--cache", cache, "--indice", idx, "--fontes", FONTES, "--pausa", "0"], fetch=servidor("distinct", conta=None))
    cap = capsys.readouterr()
    assert rc == 0 and "NÃO conferido contra a contagem" in cap.out and "indisponível" in cap.err and len(busca.carregar_indice(idx)["titulos"]) == TOTAL


def test_sem_contagem_e_teto_atingido_e_incompleto():
    c = baixar_tudo(servidor("distinct", conta=None), 1000, 3, 0, dormir=lambda s: None, esperado=None)
    assert not c.completa and not c.validada and "sem contagem" in c.motivo


def test_pagina_repetida_nao_prende_o_importador():
    pg = json.dumps({"results": {"bindings": [row(990300001, "A"), row(990300002, "B")]}}).encode()
    n = {"c": 0}

    def f(url):
        n["c"] += 1
        return pg

    c = baixar_tudo(f, 1000, 40, 0, dormir=lambda s: None, esperado=5000)
    assert n["c"] == 2 and not c.completa and any("nenhum jogo novo" in a for a in c.avisos)


def test_tolerancia_pequena_aceita_e_grande_rejeita():
    ok = baixar_tudo(servidor("distinct", perde=28), 1000, 40, 0, dormir=lambda s: None, esperado=TOTAL)       # 6600 de 6628 (99,6%)
    assert ok.completa and ok.validada and len(ok.qids) == TOTAL - 28 and any("28 jogo(s) a menos" in a for a in ok.avisos)
    ruim = baixar_tudo(servidor("distinct", perde=200), 1000, 40, 0, dormir=lambda s: None, esperado=TOTAL)   # 6428 de 6628 (97%)
    assert not ruim.completa and "coletados 6428 de 6628" in ruim.motivo


def test_offline_recusa_cache_incompleto_sem_aceitar_parcial(tmp_path, capsys):
    cache = str(tmp_path / "c.json")
    col = baixar_tudo(servidor("bag", corta_em=1000), 1000, 40, 0, dormir=lambda s: None, esperado=TOTAL)
    wikidata.salvar_cache(col.linhas, cache, col)
    idx = str(tmp_path / "i.json")
    assert main(["--offline", "--cache", cache, "--indice", idx, "--fontes", FONTES]) == 1 and not Path(idx).exists()
    assert "INCOMPLETO" in capsys.readouterr().err
    assert main(["--offline", "--aceitar-parcial", "--cache", cache, "--indice", idx, "--fontes", FONTES]) == 0
    assert busca.carregar_indice(idx)["fontes"]["wikidata"]["parcial"] is True


def test_cache_antigo_sem_informacao_de_completude_gera_aviso(tmp_path, capsys):
    cache = str(tmp_path / "c.json")
    wikidata.salvar_cache(SIM, cache)                                     # sem Coleta: como o cache da versão anterior
    assert main(["--offline", "--cache", cache, "--indice", str(tmp_path / "i.json"), "--fontes", FONTES]) == 0
    assert "versão antiga" in capsys.readouterr().err
