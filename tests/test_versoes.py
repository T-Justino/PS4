"""Versões CUSA por Q-id. Dados simulados usam Q-ids inventados (99040xxxx) e CUSA fictícios marcados nos testes; a semente real é validada à parte."""
import copy
import json
from pathlib import Path

import pytest

from ps4store import busca, versoes
from ps4store.versoes import adicionar, consultar, validar_doc, validar_registro

ROOT = Path(__file__).resolve().parents[1]
SEMENTE = ROOT / "data" / "versoes-cusa.json"
FONTES = str(ROOT / "config" / "busca-fontes.json")


def reg(**kw):
    r = {"qid": "Q990400001", "jogo": "Jogo Simulado", "cusa": "CUSA99001", "contentId": "UP0000-CUSA99001_00-ABCDEFGHIJKLMNOP", "edicao": "Standard",
         "versao": None, "regiao": {"codigo": "US", "prefixo": "UP", "base": "prefixo UP do Content ID"}, "idiomas": None, "status": "citado",
         "evidencias": [{"fonte": "Loja simulada", "url": "https://loja.exemplo.invalid/p/1", "obtidoEm": "2026-11-22", "afirma": ["cusa", "contentId", "edicao", "regiao"]}]}
    r.update(kw)
    return r


def doc(*rs):
    return {"schema": versoes.SCHEMA, "versoes": list(rs)}


# ---------- validação: nada inventado ----------
def test_registro_valido_e_campos_desconhecidos_ficam_nulos():
    r = reg()
    assert validar_registro(r) == [] and r["idiomas"] is None and r["versao"] is None


@pytest.mark.parametrize("mudanca,trecho", [
    ({"cusa": "CUSA123"}, "cusa inválido"),
    ({"cusa": "NPXS12345"}, "cusa inválido"),
    ({"qid": "15891648"}, "qid inválido"),
    ({"contentId": "UP0000-CUSA99002_00-ABCDEFGHIJKLMNOP"}, "diferente do cusa"),
    ({"contentId": "lixo"}, "contentId inválido"),
    ({"status": "talvez"}, "status"),
    ({"status": "confirmado"}, "confirmacao"),
    ({"evidencias": []}, "ao menos uma evidência"),
    ({"evidencias": [{"fonte": "x", "url": "http://inseguro.invalid/", "obtidoEm": "2026-11-22", "afirma": ["cusa"]}]}, "url https"),
    ({"evidencias": [{"fonte": "x", "url": "https://a.invalid/", "obtidoEm": "ontem", "afirma": ["cusa"]}]}, "obtidoEm"),
    ({"evidencias": [{"fonte": "x", "url": "https://a.invalid/", "obtidoEm": "2026-11-22", "afirma": ["telefone"]}]}, "'afirma'"),
])
def test_registros_invalidos(mudanca, trecho):
    assert any(trecho in p for p in validar_registro(reg(**mudanca)))


def test_campo_com_valor_sem_evidencia_que_o_afirme_e_recusado():
    ev = [{"fonte": "Loja", "url": "https://a.invalid/", "obtidoEm": "2026-11-22", "afirma": ["cusa"]}]
    assert any("'contentId' tem valor mas nenhuma evidência" in p for p in validar_registro(reg(evidencias=ev)))
    assert any("'regiao'" in p for p in validar_registro(reg(evidencias=ev, contentId=None, edicao=None)))
    assert any("'edicao'" in p for p in validar_registro(reg(evidencias=ev, contentId=None, regiao=None)))
    assert any("'idiomas'" in p for p in validar_registro(reg(idiomas=["Portuguese"], idiomasBase="x")))       # região/edição afirmadas não provam idioma
    assert any("'versao'" in p for p in validar_registro(reg(versao="01.09")))


def test_idiomas_exigem_base_e_evidencia_propria_e_regiao_nao_implica_idioma():
    ev = [{"fonte": "Loja", "url": "https://a.invalid/", "obtidoEm": "2026-11-22", "afirma": ["cusa", "contentId", "edicao", "regiao", "idiomas"]}]
    assert any("idiomasBase" in p for p in validar_registro(reg(evidencias=ev, idiomas=["English"])))
    assert validar_registro(reg(evidencias=ev, idiomas=["English"], idiomasBase="título da listagem: (English)")) == []
    assert reg()["idiomas"] is None                                            # região US presente, idiomas continua desconhecido


def test_regiao_precisa_ser_coerente_com_o_prefixo():
    assert any("deveria ser EU" in p for p in validar_registro(reg(regiao={"codigo": "US", "prefixo": "EP", "base": "x"}, contentId=None,
                                                                   evidencias=[{"fonte": "x", "url": "https://a.invalid/", "obtidoEm": "2026-11-22", "afirma": ["cusa", "edicao", "regiao"]}])))
    assert any("diferente do prefixo" in p for p in validar_registro(reg(regiao={"codigo": "EU", "prefixo": "EP", "base": "x"})))
    assert any("regiao exige" in p for p in validar_registro(reg(regiao={"codigo": "US"})))


def test_documento_rejeita_repetidos_e_aceita_varios_cusa_do_mesmo_jogo():
    a, b = reg(), reg(cusa="CUSA99002", contentId="EP0000-CUSA99002_00-ABCDEFGHIJKLMNOP", regiao={"codigo": "EU", "prefixo": "EP", "base": "x"})
    assert validar_doc(doc(a, b)) == []                                        # 2 CUSAs, mesmo Q-id
    assert any("repetido" in p for p in validar_doc(doc(a, copy.deepcopy(a))))
    assert validar_doc({"schema": "outro"}) != []


# ---------- consulta e filtros opcionais ----------
BASE = doc(reg(),
           reg(cusa="CUSA99002", contentId="EP0000-CUSA99002_00-ABCDEFGHIJKLMNOP", regiao={"codigo": "EU", "prefixo": "EP", "base": "x"}),
           reg(cusa="CUSA99001", contentId="UP0000-CUSA99001_00-ZZZZZZZZZZZZZZZZ", edicao="Deluxe", regiao=None, idiomas=["English", "Korean"], idiomasBase="título: (English, Korean)",
               evidencias=[{"fonte": "L", "url": "https://l.invalid/2", "obtidoEm": "2026-11-22", "afirma": ["cusa", "contentId", "edicao", "idiomas"]}]),
           reg(qid="Q990400002", jogo="Outro Jogo", cusa="CUSA99010", contentId=None, edicao=None, regiao=None))


def test_sem_filtros_lista_todos_os_registros():
    r, omit = consultar(BASE)
    assert len(r) == 4 and omit == 0
    assert [x["cusa"] for x in consultar(BASE, qid="Q990400001")[0]] == ["CUSA99001", "CUSA99002", "CUSA99001"]


def test_filtros_por_cusa_regiao_e_idioma_sao_opcionais_e_combinaveis():
    assert [x["cusa"] for x in consultar(BASE, cusa="cusa99002")[0]] == ["CUSA99002"]
    assert [x["cusa"] for x in consultar(BASE, regiao="EU")[0]] == ["CUSA99002"]
    assert [x["cusa"] for x in consultar(BASE, regiao="up")[0]] == ["CUSA99001"]                  # também pelo prefixo
    assert [x["edicao"] for x in consultar(BASE, idioma="KOREAN")[0]] == ["Deluxe"]
    assert consultar(BASE, regiao="US", idioma="English")[0] == []                                # US conhecida não implica English


def test_valor_desconhecido_nao_casa_com_filtro_e_e_contado():
    r, omit = consultar(BASE, regiao="US")
    assert [x["cusa"] for x in r] == ["CUSA99001"] and omit == 2                                  # o registro sem região e o de outro jogo
    r, omit = consultar(BASE, idioma="English")
    assert len(r) == 1 and omit == 3                                                              # só um registro tem idiomas confirmados


# ---------- vínculo por Q-id, nunca por nome ----------
def indice_com(*jogos):
    d = busca.indice_vazio()
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", [{"nome": n, "url": f"https://www.wikidata.org/wiki/{q}", "idFonte": f"wikidata:{q}"} for q, n in jogos])
    return d


def cli(args, capsys):
    rc = versoes.main(args)
    c = capsys.readouterr()
    return rc, c.out, c.err


def prepara(tmp_path, d, indice=None):
    v = tmp_path / "v.json"
    versoes.salvar(d, str(v))
    i = tmp_path / "i.json"
    if indice is not None:
        busca.salvar_indice(indice, str(i))
    return ["--versoes", str(v), "--indice", str(i)]


def test_nomes_iguais_ou_parecidos_nao_herdam_versoes_de_outro_qid(tmp_path, capsys):
    idx = indice_com(("Q990400001", "Jogo Simulado"), ("Q990400077", "Jogo Simulado"), ("Q990400078", "Jogo Simulado: Edição Especial"))
    rc, out, _ = cli(prepara(tmp_path, BASE, idx) + ["Jogo Simulado"], capsys)
    assert rc == 0 and out.count("[wikidata:Q990400001]") == 1 and "[wikidata:Q990400077]" not in out and "[wikidata:Q990400078]" not in out
    assert "2 outro(s) jogo(s) casam com o nome, mas sem versões registradas" in out                      # aparecem, mas SEM CUSA


def test_por_nome_pelo_indice_lista_os_cusas_e_confirma_o_vinculo(tmp_path, capsys):
    idx = indice_com(("Q990400001", "Jogo Simulado"))
    rc, out, _ = cli(prepara(tmp_path, BASE, idx) + ["jogo simulado"], capsys)
    assert rc == 0 and "3 versão(ões)" in out and "vínculo confirmado no índice: Q990400001" in out and out.count("\n  CUSA99001 ·") == 2 and "\n  CUSA99002 ·" in out
    assert "não é link nem indica que exista PKG" in out


def test_vinculo_com_alerta_quando_qid_ausente_ou_nome_diferente(tmp_path, capsys):
    rc, out, _ = cli(prepara(tmp_path, BASE, indice_com(("Q5", "Outro"))) + ["Q990400001"], capsys)
    assert "NÃO existe no seu índice local" in out
    rc, out, _ = cli(prepara(tmp_path, BASE, indice_com(("Q990400001", "Nome Totalmente Diferente"))) + ["--validar"], capsys)
    assert "o índice diz que Q990400001 é \"Nome Totalmente Diferente\"" in out
    sem = tmp_path / "sem"
    sem.mkdir()
    rc, out, _ = cli(prepara(sem, BASE) + ["--validar"], capsys)                                       # sem índice
    assert "NÃO verificado (sem índice local" in out and rc == 0


def test_cli_sem_argumentos_lista_tudo_e_filtros_sao_opcionais(tmp_path, capsys):
    a = prepara(tmp_path, BASE)
    rc, out, _ = cli(a, capsys)
    assert rc == 0 and "[wikidata:Q990400001]" in out and "[wikidata:Q990400002]" in out and "4 registro" not in out
    rc, out, _ = cli(a + ["--regiao", "EU"], capsys)
    assert "CUSA99002" in out and "CUSA99010" not in out and "ficaram de fora" in out
    rc, out, _ = cli(a + ["CUSA99010"], capsys)
    assert rc == 0 and "Outro Jogo" in out
    rc, out, _ = cli(a + ["--json"], capsys)
    assert len(json.loads(out)) == 4
    rc, out, _ = cli(a + ["--idioma", "Klingon"], capsys)
    assert rc == 1 and "Nenhuma versão CUSA registrada" in out


def test_consulta_so_pelo_rotulo_do_registro_quando_nao_ha_indice(tmp_path, capsys):
    rc, out, _ = cli(prepara(tmp_path, BASE) + ["simulado"], capsys)
    assert rc == 0 and "Jogo Simulado" in out and "Outro Jogo" not in out


# ---------- adicionar / confirmar ----------
def test_adicionar_exige_evidencia_e_nao_completa_campos(tmp_path, capsys):
    a = prepara(tmp_path, doc())
    base = ["--adicionar", "--qid", "Q990400050", "--jogo", "Jogo X", "--cusa", "cusa99050"]
    rc, _, err = cli(a + base, capsys)
    assert rc == 2 and "--evidencia-fonte" in err and "--evidencia-url" in err
    rc, out, _ = cli(a + base + ["--evidencia-fonte", "Loja", "--evidencia-url", "https://loja.exemplo.invalid/x"], capsys)
    assert rc == 0
    r = versoes.carregar(a[1])["versoes"][0]
    assert r["cusa"] == "CUSA99050" and r["contentId"] is None and r["edicao"] is None and r["regiao"] is None and r["idiomas"] is None and r["versao"] is None
    assert r["evidencias"][0]["afirma"] == ["cusa"] and r["status"] == "citado"
    rc, _, err = cli(a + base + ["--evidencia-fonte", "Loja", "--evidencia-url", "https://loja.exemplo.invalid/x"], capsys)
    assert rc == 2 and "já existe" in err
    rc, _, err = cli(a + ["--adicionar", "--qid", "Q9", "--jogo", "J", "--cusa", "CUSA1", "--evidencia-fonte", "L", "--evidencia-url", "https://a.invalid/"], capsys)
    assert rc == 2 and "cusa inválido" in err


def test_adicionar_com_content_id_e_idiomas_com_base(tmp_path, capsys):
    a = prepara(tmp_path, doc())
    rc, _, _ = cli(a + ["--adicionar", "--qid", "Q990400051", "--jogo", "Jogo Y", "--cusa", "CUSA99051", "--content-id", "EP0000-CUSA99051_00-ABCDEFGHIJKLMNOP",
                        "--edicao", "GOTY", "--regiao-base", "prefixo EP do Content ID", "--idiomas", "Portuguese, English", "--idiomas-base", "texto da loja",
                        "--evidencia-fonte", "Loja", "--evidencia-url", "https://loja.exemplo.invalid/y"], capsys)
    r = versoes.carregar(a[1])["versoes"][0]
    assert rc == 0 and r["regiao"] == {"codigo": "EU", "prefixo": "EP", "base": "prefixo EP do Content ID"} and r["idiomas"] == ["Portuguese", "English"]
    rc, _, err = cli(a + ["--adicionar", "--qid", "Q990400052", "--jogo", "Z", "--cusa", "CUSA99052", "--idiomas", "English", "--evidencia-fonte", "L",
                          "--evidencia-url", "https://a.invalid/"], capsys)
    assert rc == 2 and "idiomasBase" in err                                                             # idiomas sem base é recusado


def test_confirmar_marca_o_registro(tmp_path, capsys):
    a = prepara(tmp_path, BASE)
    rc, out, _ = cli(a + ["--confirmar", "UP0000-CUSA99001_00-ABCDEFGHIJKLMNOP", "--por", "teste"], capsys)
    d = versoes.carregar(a[1])
    r = next(x for x in d["versoes"] if x["contentId"] == "UP0000-CUSA99001_00-ABCDEFGHIJKLMNOP")
    assert rc == 0 and r["status"] == "confirmado" and r["confirmacao"]["por"] == "teste" and validar_doc(d) == []
    assert cli(a + ["--confirmar", "UP0000-CUSA99999_00-ABCDEFGHIJKLMNOP"], capsys)[0] == 2


# ---------- semente REAL (Batman: Arkham Knight) ----------
def semente():
    return json.loads(SEMENTE.read_text(encoding="utf-8"))


def test_semente_e_valida_e_so_afirma_o_que_a_evidencia_sustenta():
    d = semente()
    assert validar_doc(d) == []
    for r in d["versoes"]:
        assert r["status"] == "citado" and r["versao"] is None                              # nada foi aberto/confirmado; versão do pacote desconhecida
        if r["qid"] == "Q3182559":                                                           # Cyberpunk 2077: página oficial do desenvolvedor, sem Content ID
            assert r["contentId"] is None and all(e["tipo"] == "desenvolvedor" and e["url"].startswith("https://support.cdprojektred.com/") for e in r["evidencias"])
            continue
        assert all(e["url"].startswith("https://store.playstation.com/") and e["tipo"] == "loja-oficial" for e in r["evidencias"])
        assert any(r["contentId"] in e["url"] for e in r["evidencias"])                      # o Content ID está na própria URL da evidência (sem digitação solta)
        assert r["contentId"].split("-")[1].split("_")[0] == r["cusa"]


def test_semente_batman_arkham_knight_tem_mais_de_um_cusa_e_nao_inventa_idioma_nem_regiao():
    d = semente()
    d["versoes"] = [r for r in d["versoes"] if r["qid"] == "Q15891648"]
    assert {r["cusa"] for r in d["versoes"]} == {"CUSA00133", "CUSA00135"} and len([r for r in d["versoes"] if r["cusa"] == "CUSA00133"]) == 2
    por_cid = {r["contentId"]: r for r in d["versoes"]}
    us, eu, asia = (por_cid["UP1018-CUSA00133_00-B000000000001563"], por_cid["EP1018-CUSA00135_00-BAKPREMIUMED0000"], por_cid["UP1018-CUSA00133_00-ASIA000000000003"])
    assert us["regiao"]["codigo"] == "US" and eu["regiao"]["codigo"] == "EU" and asia["regiao"] is None
    assert us["idiomas"] is None and eu["idiomas"] is None and asia["idiomas"] == ["English", "Korean"]        # idioma só onde a listagem o diz
    assert all(r["qid"] == "Q15891648" for r in d["versoes"])
    assert "NÃO verificado" in d["versoes"][0]["qidEvidencia"]
    assert "CUSA00135" in d["versoes"][1]["nota"] and "NÃO foi usada" in d["versoes"][1]["nota"]            # a alegação não verificável ficou de fora


def test_criterio_de_aceite_pesquisar_batman_arkham_knight_lista_os_cusas(tmp_path, capsys):
    rc, out, _ = cli(["--versoes", str(SEMENTE), "--indice", str(tmp_path / "sem-indice.json"), "Batman: Arkham Knight"], capsys)
    assert rc == 0 and "3 versão(ões)" in out and out.count("\n  CUSA00133 ·") == 2 and out.count("\n  CUSA00135 ·") == 1 and "citado" in out
    assert "desconhecidos" in out and "desconhecida" in out
    rc, out, _ = cli(["--versoes", str(SEMENTE), "--indice", str(tmp_path / "x.json"), "Batman: Arkham Knight", "--regiao", "EU"], capsys)
    assert "CUSA00135" in out and "CUSA00133" not in out
    rc, out, _ = cli(["--versoes", str(SEMENTE), "--indice", str(tmp_path / "x.json"), "--idioma", "Korean"], capsys)
    assert "ASIA000000000003" in out and "CUSA00135" not in out
