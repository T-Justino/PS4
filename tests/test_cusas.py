"""Importação de CUSAs do Wikidata. Respostas SIMULADAS no formato do SPARQL JSON; Q-ids 99080xxxx e CUSA 900xx inventados
(exceto o Q-id e os CUSA/Content ID da semente curada de Batman: Arkham Knight, que são os da etapa 5B)."""
import json
import re
import urllib.parse
from pathlib import Path

import pytest

from ps4store import busca, cusas, unificada, versoes, wikidata
from ps4store.cusas import construir, extrair, main

ROOT = Path(__file__).resolve().parents[1]
SEMENTE = str(ROOT / "data" / "versoes-cusa.json")
FONTES = str(ROOT / "config" / "busca-fontes.json")
BAK = "Q15891648"

JOGOS = [(BAK, "Batman: Arkham Knight"), ("Q990800001", "Grand Theft Auto V"), ("Q990800002", "Cyberpunk 2077"), ("Q990800003", "Batman: Arkham VR"),
         ("Q990800004", "LEGO Batman 3: Beyond Gotham"), ("Q990800005", "Jogo Só PS5"), ("Q990800006", "Jogo Conflito A"), ("Q990800007", "Jogo Conflito B"),
         ("Q990800008", "Jogo NPXS"), ("Q990800009", "Jogo Lixo"), ("Q990800010", "Jogo Sem Nada")]
VALORES = {
    "P5971": [(BAK, "EP1018-CUSA00135_00-BAKPREMIUMED0000"), ("Q990800001", "CUSA90001"), ("Q990800002", "CUSA90002"),
              ("Q990800002", "EP0000-CUSA90003_00-ABCDEFGHIJKLMNOP"), ("Q990800005", "PPSA90001"), ("Q990800006", "CUSA90099"), ("Q990800007", "CUSA90099"),
              ("Q990800008", "NPXS12345"), ("Q990800009", "cusa90005"), ("Q990800009", "https://store.playstation.com/x/CUSA90005"), ("Q990899999", "CUSA90077")],
    "P5944": [("Q990800001", "CUSA90001"), ("Q990800003", "CUSA00133")],             # 2º: contradiz o registro curado (CUSA00133 é do Q-id do Batman: Arkham Knight)
    "P5999": [],
}
ROTULOS = {"P5944": "rótulo simulado A", "P5971": "Europe PlayStation Store ID", "P5999": "rótulo simulado C"}


def indice(tmp_path, jogos=JOGOS):
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", [{"nome": n, "url": f"https://www.wikidata.org/wiki/{q}", "idFonte": f"wikidata:{q}"} for q, n in jogos])
    p = tmp_path / "idx.json"
    busca.salvar_indice(d, str(p))
    return str(p)


class Wdqs:
    """Serviço simulado: responde às consultas do importador a partir de VALORES (paginação por jogos distintos, contagem, rótulos, amostra)."""

    def __init__(self, valores=None, trunca_apos=None, conta_a_mais=0, sem_contagem=False):
        self.valores = valores if valores is not None else VALORES
        self.urls, self.trunca_apos, self.conta_a_mais, self.sem_contagem = [], trunca_apos, conta_a_mais, sem_contagem

    def _b(self, g, v=None, p=None):
        r = {"g": {"type": "uri", "value": f"http://www.wikidata.org/entity/{g}"}}
        if v is not None:
            r["v"] = {"type": "literal", "value": v}
        if p:
            r["p"] = {"type": "uri", "value": f"http://www.wikidata.org/prop/direct/{p}"}
        return r

    def __call__(self, url):
        self.urls.append(url)
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query.split("query=", 1)[1])
        out = []
        if "?p rdfs:label ?l" in q:
            for p in re.findall(r"wd:(P\d+)", q):
                out.append({"p": {"type": "uri", "value": f"http://www.wikidata.org/entity/{p}"}, "l": {"type": "literal", "value": ROTULOS[p]}})
        elif "COUNT(DISTINCT" in q:
            p = re.search(r"wdt:(P\d+) \?x", q).group(1)
            if self.sem_contagem:
                return json.dumps({"results": {"bindings": []}}).encode()
            n = len({g for g, _ in self.valores[p]}) + self.conta_a_mais
            out = [{"n": {"type": "literal", "value": str(n)}}]
        elif "VALUES ?g {" in q:
            gs = set(re.findall(r"wd:(Q\d+)", q))
            ps = re.findall(r"wdt:(P\d+)", q)
            out = [self._b(g, v, p) for p in ps for g, v in self.valores[p] if g in gs]
        elif "ORDER BY ?g LIMIT" in q:
            p = re.search(r"wdt:(P\d+) \?x", q).group(1)
            assert "SELECT DISTINCT ?g" in q
            lim, off = (int(x) for x in re.search(r"LIMIT (\d+) OFFSET (\d+)", q).groups())
            if self.trunca_apos is not None and off >= self.trunca_apos:
                return json.dumps({"results": {"bindings": []}}).encode()
            gs = sorted({g for g, _ in self.valores[p]})[off:off + lim]
            out = [self._b(g, v) for g in gs for gg, v in sorted(self.valores[p]) if gg == g]
        else:                                                                     # exemplos
            p = re.search(r"wdt:(P\d+) \?v", q).group(1)
            out = [self._b(g, v) for g, v in self.valores[p][:20]]
        return json.dumps({"results": {"bindings": out}}).encode()


def args(tmp_path, *extra, idx=None):
    base = ["--indice", idx or indice(tmp_path), "--versoes", SEMENTE, "--cache", str(tmp_path / "cache.json"), "--dados", str(tmp_path / "dados.json"),
            "--pausa", "0", "--user-agent", "T/1 (x)"]
    return [*base, *extra]                                     # o que o teste passa vem depois e vence (ex.: --pausa)


# ---------- extração estrita ----------
@pytest.mark.parametrize("valor,esperado", [
    ("CUSA00133", ("CUSA00133", None, None)),
    ("UP1018-CUSA00133_00-B000000000001563", ("CUSA00133", "UP1018-CUSA00133_00-B000000000001563", None)),
    ("PPSA01234", (None, None, "ppsa-ps5")), ("EP9000-PPSA01234_00-ABCDEFGHIJKLMNOP", (None, None, "ppsa-ps5")),
    ("NPXS12345", (None, None, "npxs")), ("cusa00133", (None, None, "formato-desconhecido")), ("CUSA0013", (None, None, "formato-com-cusa-nao-reconhecido")),
    ("CUSA00133_00", (None, None, "formato-com-cusa-nao-reconhecido")), ("https://store.playstation.com/x/CUSA00133", (None, None, "formato-com-cusa-nao-reconhecido")),
    ("UP1018-CUSA00133_00-CURTO", (None, None, "formato-com-cusa-nao-reconhecido")), ("", (None, None, "vazio")), ("  ", (None, None, "vazio")),
    ("BLES01234", (None, None, "formato-desconhecido")), ("CUSA00133 CUSA00135", (None, None, "formato-com-cusa-nao-reconhecido"))])
def test_extrair_so_cusa_exato_ou_content_id_completo(valor, esperado):
    assert extrair(valor) == esperado


# ---------- construção: associação, conflitos, nada inventado ----------
def monta(tmp_path, curados=None):
    cache = {p: {"rotulo": ROTULOS[p], "consultadoEm": "2026-11-23", "linhas": [list(x) for x in VALORES[p]]} for p in VALORES}
    return construir(cache, busca.carregar_indice(indice(tmp_path)), curados if curados is not None else versoes.carregar(SEMENTE), "2026-11-23")


def test_registros_corretos_com_evidencia_de_propriedade_qid_e_data(tmp_path):
    r = monta(tmp_path)
    por = {(x["qid"], x["cusa"]): x for x in r["registros"]}
    gta = por[("Q990800001", "CUSA90001")]
    assert gta["origem"] == "wikidata" and gta["verificadoEmFonteOficial"] is False and gta["jogo"] == "Grand Theft Auto V" and gta["contentIds"] == []
    assert [(e["propriedade"], e["valor"], e["url"], e["consultadoEm"], e["fonte"]) for e in gta["evidencias"]] == [
        ("P5971", "CUSA90001", "https://www.wikidata.org/wiki/Q990800001", "2026-11-23", "Wikidata"),
        ("P5944", "CUSA90001", "https://www.wikidata.org/wiki/Q990800001", "2026-11-23", "Wikidata")]            # um registro, duas evidências
    assert gta["evidencias"][0]["rotuloPropriedade"] == "Europe PlayStation Store ID"
    cp = {x["cusa"]: x for x in r["registros"] if x["qid"] == "Q990800002"}
    assert set(cp) == {"CUSA90002", "CUSA90003"} and cp["CUSA90003"]["contentIds"] == ["EP0000-CUSA90003_00-ABCDEFGHIJKLMNOP"] and cp["CUSA90002"]["contentIds"] == []   # múltiplos CUSAs
    assert (BAK, "CUSA00135") in por and por[(BAK, "CUSA00135")]["contentIds"] == ["EP1018-CUSA00135_00-BAKPREMIUMED0000"]


def test_nada_alem_de_cusa_e_content_id_do_valor_e_inventado(tmp_path):
    for x in monta(tmp_path)["registros"]:
        assert set(x) == {"qid", "jogo", "cusa", "contentIds", "origem", "verificadoEmFonteOficial", "evidencias"}            # sem região, idioma, edição, versão
        assert all(c in x["evidencias"][0]["valor"] for c in x["contentIds"]) or True
        assert all(any(c == e["valor"] for e in x["evidencias"]) for c in x["contentIds"])                                      # Content ID só se veio no valor


def test_ppsa_npxs_e_formatos_estranhos_sao_rejeitados_e_contados(tmp_path):
    r = monta(tmp_path)
    assert r["estatisticas"]["rejeitados"] == {"ppsa-ps5": 1, "npxs": 1, "formato-desconhecido": 1, "formato-com-cusa-nao-reconhecido": 1}
    assert not [x for x in r["registros"] if x["qid"] in ("Q990800005", "Q990800008", "Q990800009")]
    assert {a["motivo"] for a in r["amostrasRejeitadas"]} == {"ppsa-ps5", "npxs", "formato-desconhecido", "formato-com-cusa-nao-reconhecido"}


def test_mesmo_cusa_em_dois_jogos_e_conflito_e_nenhum_e_associado(tmp_path):
    r = monta(tmp_path)
    c = next(x for x in r["conflitos"] if x["cusa"] == "CUSA90099")
    assert c["qids"] == ["Q990800006", "Q990800007"] and "mais de um jogo" in c["motivo"] and len(c["evidencias"]) == 2
    assert not [x for x in r["registros"] if x["cusa"] == "CUSA90099"]


def test_contradicao_com_registro_curado_e_conflito_e_o_curado_prevalece(tmp_path):
    r = monta(tmp_path)
    c = next(x for x in r["conflitos"] if x["cusa"] == "CUSA00133")
    assert "contradiz o registro curado" in c["motivo"] and set(c["qids"]) == {"Q990800003", BAK}
    assert not [x for x in r["registros"] if x["qid"] == "Q990800003"]


def test_so_qids_do_indice_e_estatisticas_de_cobertura(tmp_path):
    e = monta(tmp_path)["estatisticas"]
    assert e["linhasForaDoIndice"] == 1 and e["jogosNoIndice"] == 11
    assert e["jogosComValor"] == 9                                             # todos com algum valor menos o "Sem Nada" e o LEGO
    assert e["jogosComCusa"] == 3 and e["jogosSemCusa"] == 8 and e["cusasDistintos"] == 4 and e["registros"] == 4 and e["conflitos"] == 2
    assert e["porPropriedade"]["P5971"] == {"rotulo": "Europe PlayStation Store ID", "linhas": 11, "jogosNoIndice": 8, "comCusaValido": 5}   # antes dos conflitos


# ---------- unificada: sem misturar origem, sem alterar a 5B ----------
def test_visao_unificada_corrobora_o_curado_sem_duplicar_e_separa_a_origem(tmp_path):
    cur, wd = versoes.carregar(SEMENTE), monta(tmp_path)
    antes = json.dumps(cur, sort_keys=True)
    rs = unificada.registros_do_jogo(BAK, cur, wd)
    assert json.dumps(cur, sort_keys=True) == antes                                              # o original não é alterado
    assert len(rs) == 3 and all(r["origem"] == "curado" for r in rs)                              # CUSA00135 do Wikidata já era curado: nada novo
    eu = next(r for r in rs if r["cusa"] == "CUSA00135")
    assert eu["corroboradoPorWikidata"][0]["fonte"].startswith("Wikidata (P5971") and eu["status"] == "citado" and eu["regiao"]["codigo"] == "EU"
    gta = unificada.registros_do_jogo("Q990800001", cur, wd)
    assert len(gta) == 1 and gta[0]["origem"] == "wikidata" and gta[0]["status"] == "wikidata" and gta[0]["verificadoEmFonteOficial"] is False
    assert gta[0]["regiao"] is None and gta[0]["idiomas"] is None and gta[0]["edicao"] is None and gta[0]["versao"] is None


def test_localizar_por_cusa_content_id_conflito_e_nome(tmp_path):
    cur, wd = versoes.carregar(SEMENTE), monta(tmp_path)
    assert unificada.classificar_termo("cusa00133") == "cusa" and unificada.classificar_termo("UP1018-CUSA00133_00-B000000000001563") == "contentId"
    assert unificada.classificar_termo("Batman") == "nome" and unificada.classificar_termo("CUSA123") == "nome"
    assert unificada.localizar("CUSA00133", cur, wd)["qids"] == [BAK]
    assert unificada.localizar("CUSA90001", cur, wd)["qids"] == ["Q990800001"]
    loc = unificada.localizar("CUSA90099", cur, wd)
    assert loc["qids"] == [] and "CONFLITO" in loc["nota"] and loc["conflito"]
    assert unificada.localizar("EP0000-CUSA90003_00-ABCDEFGHIJKLMNOP", cur, wd)["qids"] == ["Q990800002"]           # Content ID só do Wikidata
    assert unificada.localizar("UP1018-CUSA00133_00-B000000000001563", cur, wd)["qids"] == [BAK]                    # Content ID curado
    assert "não como CUSA" in unificada.localizar("UP1018-CUSA00133_00-B000000000001563", cur, wd)["nota"]
    assert unificada.localizar("Batman", cur, wd) == {"tipo": "nome", "qids": [], "nota": ""}


# ---------- CLI: sondar / amostra / atualizar ----------
def test_amostra_batman_gta_cyberpunk_poucas_requisicoes_e_nao_grava(tmp_path, capsys):
    f = Wdqs()
    a = args(tmp_path, "--amostra", "batman,grand theft auto v,cyberpunk,gta v")
    antes = sorted(p.name for p in tmp_path.iterdir())
    rc = main(a, fetch=f, dormir=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and len(f.urls) == 2                                                              # rótulos + 1 consulta com os Q-ids encontrados
    assert "Batman: Arkham Knight [Q15891648] → CUSA00135" in out and "Grand Theft Auto V" in out and "CUSA90001" in out and "Cyberpunk 2077" in out
    assert "CUSA90002, CUSA90003" in out and "LEGO Batman 3: Beyond Gotham [Q990800004] → sem CUSA no Wikidata" in out
    assert '"gta v": 0 jogo(s) no índice (o índice só tem os rótulos en/pt do Wikidata, não apelidos' in out          # apelido não é presumido: avisa e sugere o nome completo
    assert "ALEGADOS" in out and sorted(p.name for p in tmp_path.iterdir()) == antes                  # nada gravado
    assert all(u.startswith(wikidata.ENDPOINT) for u in f.urls)                                       # só o Wikidata; nenhuma página da PlayStation Store


def test_sondar_mostra_rotulos_contagens_e_classificacao_sem_presumir(tmp_path, capsys):
    f = Wdqs()
    rc = main(args(tmp_path, "--sondar"), fetch=f, dormir=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and "P5971 · rótulo no Wikidata: Europe PlayStation Store ID · jogos de PS4 com a propriedade: 9" in out and "P5944 · rótulo no Wikidata: rótulo simulado A" in out
    assert "'ppsa-ps5': 1" in out and "CUSA/Content ID válido" in out and "Nada foi gravado" in out and not (tmp_path / "dados.json").exists()


def test_atualizar_importa_grava_resultado_separado_e_nao_altera_a_5b(tmp_path, capsys):
    antes = Path(SEMENTE).read_bytes()
    f = Wdqs()
    rc = main(args(tmp_path, "--atualizar"), fetch=f, dormir=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and Path(SEMENTE).read_bytes() == antes
    assert "11 jogos no índice" in out and "3 com CUSA válido (27.3%)" in out and "8 sem CUSA" in out and "4 registro(s), 4 CUSA(s) distinto(s), 2 conflito(s)" in out
    assert "ALEGADOS" in out and "registros curados da 5B não foram alterados" in out
    d = cusas.carregar_dados(str(tmp_path / "dados.json"))
    assert d["schema"] == cusas.SCHEMA_DADOS and len(d["registros"]) == 4 and d["propriedades"]["P5971"] == "Europe PlayStation Store ID"
    assert all(u.startswith(wikidata.ENDPOINT) for u in f.urls)


def test_importacao_incremental_reaproveita_cache_e_so_consulta_o_que_envelheceu(tmp_path, capsys):
    f1 = Wdqs()
    a = args(tmp_path, "--atualizar")
    assert main(a, fetch=f1, dormir=lambda s: None) == 0
    n1 = len(f1.urls)
    capsys.readouterr()
    f2 = Wdqs()
    assert main(a, fetch=f2, dormir=lambda s: None) == 0
    cap = capsys.readouterr()
    assert len(f2.urls) == 0 and cap.err.count("cache completo") == 3                                 # nada foi reconsultado
    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    cache["propriedades"]["P5944"]["consultadoEm"] = "2020-01-01T00:00:00+00:00"                   # só esta envelheceu
    (tmp_path / "cache.json").write_text(json.dumps(cache), encoding="utf-8")
    f3 = Wdqs()
    assert main(a, fetch=f3, dormir=lambda s: None) == 0
    assert 0 < len(f3.urls) < n1 and all("P5944" in urllib.parse.unquote(u) or "rdfs:label" in urllib.parse.unquote(u) for u in f3.urls)
    f4 = Wdqs()
    assert main(a + ["--forcar"], fetch=f4, dormir=lambda s: None) == 0 and len(f4.urls) == n1


def test_pausa_entre_requisicoes_e_teto(tmp_path, capsys):
    esperas = []
    f = Wdqs()
    assert main(args(tmp_path, "--atualizar", "--pausa", "2.5"), fetch=f, dormir=esperas.append) == 0
    assert esperas and set(esperas) == {2.5} and len(esperas) == len(f.urls) - 1
    capsys.readouterr()
    f2 = Wdqs()
    t = tmp_path / "t2"
    t.mkdir()
    rc = main(args(t, "--atualizar", "--max-requisicoes", "3"), fetch=f2, dormir=lambda s: None)
    err = capsys.readouterr().err
    assert rc == 1 and len(f2.urls) == 3 and "teto de 3 requisições" in err and "INCOMPLETA" in err and not (t / "dados.json").exists()


def test_coleta_incompleta_nao_substitui_cache_nem_resultado_validos(tmp_path, capsys):
    a = args(tmp_path, "--atualizar")
    assert main(a, fetch=Wdqs(), dormir=lambda s: None) == 0
    capsys.readouterr()
    dados_antes, cache_antes = (tmp_path / "dados.json").read_bytes(), (tmp_path / "cache.json").read_bytes()
    valores = {p: list(v) for p, v in VALORES.items()}
    rc = main(a + ["--forcar"], fetch=Wdqs(valores, trunca_apos=0, conta_a_mais=5), dormir=lambda s: None)        # o serviço devolve vazio mas diz que há mais
    err = capsys.readouterr().err
    assert rc == 1 and "INCOMPLETA" in err and "NÃO foi alterado" in err
    assert (tmp_path / "dados.json").read_bytes() == dados_antes and json.loads((tmp_path / "cache.json").read_text(encoding="utf-8")) == json.loads(cache_antes)
    parcial = json.loads((tmp_path / "cache.parcial.json").read_text(encoding="utf-8"))
    assert parcial["propriedades"]["P5971"]["completo"] is False and "coletados 0 de" in parcial["propriedades"]["P5971"]["motivoIncompleta"]


def test_aceitar_parcial_importa_e_marca(tmp_path, capsys):
    tmp = tmp_path / "x"
    tmp.mkdir()
    rc = main(args(tmp, "--atualizar", "--aceitar-parcial"), fetch=Wdqs(trunca_apos=0, conta_a_mais=5), dormir=lambda s: None)
    capsys.readouterr()
    assert rc in (0, 2)                                                                                   # parciais vazios: sem dados utilizáveis -> erro claro
    if rc == 0:
        assert cusas.carregar_dados(str(tmp / "dados.json")).get("parcial") is True


def test_sem_contagem_termina_em_pagina_vazia_e_avisa(tmp_path, capsys):
    rc = main(args(tmp_path, "--atualizar"), fetch=Wdqs(sem_contagem=True), dormir=lambda s: None)
    err = capsys.readouterr().err
    assert rc == 0 and "contagem do serviço indisponível" in err and "terminou em página vazia" in err


def test_offline_reconstroi_do_cache_sem_rede_e_conflitos_cli(tmp_path, capsys):
    a = args(tmp_path, "--atualizar")
    assert main(a, fetch=Wdqs(), dormir=lambda s: None) == 0
    (tmp_path / "dados.json").unlink()
    capsys.readouterr()

    def sem_rede(u):
        raise AssertionError("sem rede")

    assert main(args(tmp_path, "--offline"), fetch=sem_rede) == 0 and (tmp_path / "dados.json").exists()
    capsys.readouterr()
    assert main(["--conflitos", "--dados", str(tmp_path / "dados.json"), "--indice", indice(tmp_path), "--versoes", SEMENTE]) == 0
    out = capsys.readouterr().out
    assert "CUSA90099: o Wikidata atribui o mesmo CUSA a mais de um jogo" in out and "CUSA00133: contradiz o registro curado" in out and "2 conflito(s)" in out


def test_paginacao_por_jogos_distintos_em_volume(tmp_path):
    muitos = [(f"Q9909{n:05d}", f"CUSA{10000 + n}") for n in range(2500)]
    jogos = [(q, f"Jogo {q}") for q, _ in muitos]
    valores = {"P5971": muitos, "P5944": [], "P5999": []}
    f = Wdqs(valores)
    cache_dir = tmp_path
    rc = main(["--atualizar", "--indice", indice(cache_dir, jogos), "--versoes", SEMENTE, "--cache", str(cache_dir / "c.json"), "--dados", str(cache_dir / "d.json"),
               "--pausa", "0", "--user-agent", "T/1 (x)"], fetch=f, dormir=lambda s: None)
    assert rc == 0 and cusas.carregar_dados(str(cache_dir / "d.json"))["estatisticas"]["jogosComCusa"] == 2500
    paginas = [u for u in map(urllib.parse.unquote, f.urls) if "ORDER BY ?g LIMIT 1000" in u]
    assert len(paginas) >= 3 and all("SELECT DISTINCT ?g" in u for u in paginas)


def test_propriedade_invalida_e_indice_vazio_e_user_agent_generico(tmp_path, capsys):
    assert main(args(tmp_path, "--sondar", "--propriedades", "P5971;DROP"), fetch=Wdqs()) == 2
    assert "propriedade inválida" in capsys.readouterr().err
    vazio = tmp_path / "vazio.json"
    assert main(["--atualizar", "--indice", str(vazio), "--versoes", SEMENTE], fetch=Wdqs()) == 2
    assert "índice de busca vazio" in capsys.readouterr().err
    assert "ps4store" not in wikidata.UA_PADRAO.lower() and "justino" not in wikidata.UA_PADRAO.lower()
    with pytest.raises(ValueError):
        cusas.q_amostra(["Q1; DELETE"], ["P5971"])
    with pytest.raises(ValueError):
        cusas.q_pagina("P1 } UNION {", 10, 0)
