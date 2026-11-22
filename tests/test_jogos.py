"""Fluxo interativo busca -> escolha -> versões CUSA. Entrada/saída injetadas; Q-ids simulados 99050xxxx (a semente real usa o Q-id do Batman: Arkham Knight)."""
import json
from pathlib import Path

import pytest

from ps4store import busca, jogos, versoes

ROOT = Path(__file__).resolve().parents[1]
SEMENTE = str(ROOT / "data" / "versoes-cusa.json")
FONTES = str(ROOT / "config" / "busca-fontes.json")
QID_BAK = "Q15891648"


def indice(tmp_path, itens=None):
    d = busca.indice_vazio()
    itens = itens if itens is not None else [
        {"nome": "Batman: Arkham Knight", "url": "https://en.wikipedia.org/wiki/Batman:_Arkham_Knight", "idFonte": f"wikidata:{QID_BAK}", "lancamento": "2015"},
        {"nome": "Batman: Arkham VR", "url": "https://www.wikidata.org/wiki/Q990500002", "idFonte": "wikidata:Q990500002"},
        {"nome": "LEGO Batman 3: Beyond Gotham", "url": "https://www.wikidata.org/wiki/Q990500003", "idFonte": "wikidata:Q990500003"},
        {"nome": "Pokémon Café Mix", "url": "https://www.wikidata.org/wiki/Q990500004", "idFonte": "wikidata:Q990500004"}]
    busca.importar(d, busca.carregar_fontes(FONTES), "wikidata", itens)
    p = tmp_path / "idx.json"
    busca.salvar_indice(d, str(p))
    return str(p)


def rodar(args, respostas, tmp_path=None, **kw):
    it = iter(respostas)
    saida = []

    def entrada(prompt=""):
        saida.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    rc = jogos.executar(args, entrada=entrada, saida=saida.append)
    return rc, "\n".join(str(x) for x in saida)


def base(tmp_path, **kw):
    return ["--indice", indice(tmp_path, kw.get("itens")), "--versoes", kw.get("versoes", SEMENTE)]


# ---------- fluxo completo ----------
def test_fluxo_busca_lista_numerada_escolha_e_versoes(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "1", "q"])
    assert rc == 0
    assert "3 jogo(s) para \"batman\"" in out
    assert " 1. Batman: Arkham Knight (2015)  [wikidata:Q15891648]  · 3 registro(s), 2 CUSA(s) distinto(s)" in out        # numerada, com contagem
    assert " 2. Batman: Arkham VR  [wikidata:Q990500002]  · sem versões cadastradas" in out and " 3. LEGO Batman 3" in out
    assert "== Batman: Arkham Knight (2015)  [wikidata:Q15891648]" in out and "3 registro(s) de versão, 2 CUSA(s) distinto(s)" in out
    assert out.count("(CUSA: identificador do título)") == 3 and "CUSA00133" in out and "CUSA00135" in out


def test_termo_na_linha_de_comando_ou_perguntado_e_busca_livre_sem_acentos_e_parcial(tmp_path):
    rc, out = rodar(base(tmp_path), ["POKEMON", "q"])
    assert "Pokémon Café Mix" in out and "sem versões cadastradas" in out
    rc, out = rodar(base(tmp_path) + ["arkham"], ["2", "q"])                                  # termo já na linha de comando
    assert "2 jogo(s) para \"arkham\"" in out and "Nenhuma versão CUSA cadastrada para Q990500002" in out


def test_escolher_n_nao_interativo(tmp_path):
    rc, out = rodar(base(tmp_path) + ["batman", "--escolher", "1"], [])
    assert rc == 0 and "CUSA00135" in out and "Nome do jogo" not in out
    assert rodar(base(tmp_path) + ["batman", "--escolher", "9"], [])[0] == 2
    assert rodar(base(tmp_path) + ["zelda", "--escolher", "1"], [])[0] == 1


# ---------- sem versões: dizer claramente, sem inventar ----------
def test_jogo_sem_versoes_diz_claramente_e_nao_inventa(tmp_path):
    rc, out = rodar(base(tmp_path), ["lego batman", "1", "q"])
    assert "Nenhuma versão CUSA cadastrada para Q990500003" in out and "NÃO quer dizer que o jogo não tenha CUSA" in out and "Nada foi inventado" in out
    assert "CUSA0" not in out.split("Nenhuma versão CUSA cadastrada")[1]


def test_resultado_sem_qid_nao_vincula_versoes_nem_por_nome(tmp_path):
    itens = [{"nome": "Batman: Arkham Knight", "url": "https://exemplo.invalid/x", "idFonte": ""}]
    rc, out = rodar(base(tmp_path, itens=itens), ["batman arkham knight", "1", "q"])
    assert "sem Q-id do Wikidata: não dá para vincular versões" in out and "não há como vincular versões CUSA (nunca por semelhança de nome)" in out
    assert "CUSA00133" not in out                                                              # mesmo com o nome idêntico ao da semente


def test_nome_igual_com_outro_qid_nao_herda_versoes(tmp_path):
    itens = [{"nome": "Batman: Arkham Knight", "url": "https://x.invalid/a", "idFonte": "wikidata:Q990500099"}]
    rc, out = rodar(base(tmp_path, itens=itens), ["arkham knight", "1", "q"])
    assert "sem versões cadastradas" in out and "CUSA00133" not in out and "ATENÇÃO" not in out


def test_sem_resultados_e_indice_ausente(tmp_path):
    rc, out = rodar(base(tmp_path), ["zelda", "q"])
    assert 'Nenhum jogo encontrado para "zelda"' in out
    vazio = ["--indice", str(tmp_path / "nao-existe.json"), "--versoes", SEMENTE]
    rc, out = rodar(vazio, ["batman arkham", "1", "q"])
    assert "AVISO  índice de busca vazio ou ausente" in out and "lista só com jogos que têm versões cadastradas" in out and "CUSA00133" in out


# ---------- filtros opcionais ----------
def depois(out, marcador):
    """Texto entre `marcador` e o próximo prompt de comando."""
    return out.split(marcador, 1)[1].split("[jogo] comando", 1)[0]


def test_sem_filtros_mostra_todos_e_filtros_sao_opcionais_e_removiveis(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "1", "f regiao EU", "f idioma Korean", "f limpar", "q"])
    inicial = out.split("[jogo] comando", 1)[0]                                               # logo após escolher: sem filtros
    assert "filtros: nenhum (todos os registros)" in inicial and inicial.count("(CUSA: identificador do título)") == 3
    eu = depois(out, "filtro regiao = EU")
    assert "filtros: regiao=EU" in eu and eu.count("(CUSA: identificador do título)") == 1 and "CUSA00135   (CUSA" in eu and "CUSA00133   (CUSA" not in eu
    assert "2 registro(s) sem o campo filtrado ficaram de fora" in eu or "1 registro(s) sem o campo filtrado ficaram de fora" in eu
    kor = depois(out, "filtro idioma = Korean")
    assert "filtros: regiao=EU, idioma=Korean" in kor and "Nenhum registro passa nos filtros" in kor and "valor desconhecido não é presumido" in kor
    limpo = depois(out, "filtros removidos: todos os registros")
    assert "filtros: nenhum (todos os registros)" in limpo and limpo.count("(CUSA: identificador do título)") == 3


def test_filtros_iniciais_pela_linha_de_comando_cusa_regiao_idioma(tmp_path):
    rc, out = rodar(base(tmp_path) + ["batman", "--escolher", "1", "--cusa", "cusa00133"], [])
    assert out.count("(CUSA: identificador do título)") == 2 and "CUSA00135" not in out.split("== Batman")[1].replace("Content ID: EP1018-CUSA00135", "")
    rc, out = rodar(base(tmp_path) + ["batman", "--escolher", "1", "--idioma", "korean"], [])
    assert "ASIA000000000003" in out and out.count("(CUSA: identificador do título)") == 1
    rc, out = rodar(base(tmp_path) + ["batman", "--escolher", "1", "--regiao", "US", "--idioma", "English"], [])
    assert "Nenhum registro passa nos filtros" in out                                           # região US conhecida não implica idioma English


def test_filtro_cusa_invalido_e_content_id_nao_e_aceito_como_cusa(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "1", "f cusa UP1018-CUSA00133_00-B000000000001563", "f cusa 123", "f foo bar", "f", "q"])
    assert out.count("CUSA inválido") == 2 and "Não confunda com o Content ID" in out and "uso: f cusa" in out and "filtros: nenhum" in out


# ---------- citado × confirmado × desconhecido; Content ID × CUSA; edição × jogo-base ----------
def semente_com_confirmacao(tmp_path):
    d = json.loads(Path(SEMENTE).read_text(encoding="utf-8"))
    d["versoes"][0]["status"] = "confirmado"
    d["versoes"][0]["confirmacao"] = {"por": "tester", "em": "2026-11-23", "como": "página aberta"}
    p = tmp_path / "v.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def test_distingue_citado_confirmado_e_desconhecido(tmp_path):
    rc, out = rodar(base(tmp_path, versoes=semente_com_confirmacao(tmp_path)), ["batman", "1", "q"])
    assert "Status: CONFIRMADO por tester em 2026-11-23" in out and out.count("Status: CITADO: a fonte foi vista, mas a página não foi aberta nem conferida") == 2
    assert out.count("Idiomas: desconhecidos   (a região não define o idioma)") == 2 and "Região: desconhecida" in out and out.count("Versão do pacote: desconhecida") == 3
    assert "Idiomas: English, Korean   (base: título da listagem da loja" in out


def test_content_id_e_cusa_sao_rotulados_separadamente_e_edicao_nao_e_jogo_base(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "1", "q"])
    assert out.count("(identifica este produto/edição; NÃO é o CUSA)") == 3 and out.count("(CUSA: identificador do título)") == 3
    assert out.count("(registro de edição/produto da loja, não de jogo-base)") == 3
    assert "Nenhum registro está marcado como jogo-base: o que aparece são produtos/edições da loja." in out
    d = json.loads(Path(SEMENTE).read_text(encoding="utf-8"))
    d["versoes"][0]["escopo"] = "jogo-base"
    p = tmp_path / "vb.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    rc, out = rodar(base(tmp_path, versoes=str(p)), ["batman", "1", "q"])
    assert "Nenhum registro está marcado como jogo-base" not in out


def test_digitar_content_id_ou_cusa_explica_a_diferenca(tmp_path):
    rc, out = rodar(base(tmp_path), ["UP1018-CUSA00133_00-B000000000001563", "1", "q"])
    assert "é um Content ID (identifica um produto/edição), não um CUSA. O CUSA contido nele é CUSA00133." in out and "Batman: Arkham Knight" in out
    rc, out = rodar(base(tmp_path), ["CUSA00135", "1", "q"])
    assert "CUSA00135 é um CUSA (identificador do título)" in out and "Batman: Arkham Knight" in out
    rc, out = rodar(base(tmp_path), ["CUSA00001", "q"])
    assert "Nenhum registro cadastrado com ele" in out and "Nenhum jogo encontrado" in out
    rc, out = rodar(base(tmp_path), ["UP1018-CUSA00999_00-ABCDEFGHIJKLMNOP", "q"])
    assert "Nenhum registro cadastrado com este Content ID" in out


def test_avisa_quando_o_rotulo_do_registro_difere_do_nome_do_indice(tmp_path):
    itens = [{"nome": "Outro Nome Para O Mesmo Q-id", "url": "https://x.invalid/a", "idFonte": f"wikidata:{QID_BAK}"}]
    rc, out = rodar(base(tmp_path, itens=itens), ["outro nome", "1", "q"])
    assert "ATENÇÃO: o registro CUSA00133 foi cadastrado como \"Batman: Arkham Knight\" para este Q-id; confira o vínculo." in out


# ---------- navegação e robustez ----------
def test_navegacao_entre_resultados_lista_nova_busca_e_fontes(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "1", "e", "2", "b", "1", "n", "pokemon", "1", "q"])
    assert "mostrando todas as fontes e notas" in out and "Nota: Premium Edition (base + Season Pass)" in out
    assert "Nenhuma versão CUSA cadastrada para Q990500002" in out                                # '2' dentro do jogo = outro resultado
    assert out.count("3 jogo(s) para \"batman\"") == 2                                              # 'b' volta à lista
    assert "== Pokémon Café Mix" in out


def test_entradas_invalidas_e_fim_de_entrada_nao_quebram(tmp_path):
    rc, out = rodar(base(tmp_path), ["batman", "99", "abc", "n", "", ])
    assert rc == 0 and out.count("Digite um número de 1 a 3") == 2
    rc, out = rodar(base(tmp_path), ["batman", "1", "xyz", "?", "q"])
    assert "comando não reconhecido" in out and "Comandos: número = outro resultado" in out
    assert rodar(base(tmp_path), [])[0] == 0                                                     # EOF imediato


def test_limite_de_lista_e_arquivos_invalidos(tmp_path):
    itens = [{"nome": f"Batman {n}", "url": f"https://x.invalid/{n}", "idFonte": f"wikidata:Q99060{n:04d}"} for n in range(40)]
    rc, out = rodar(base(tmp_path, itens=itens) + ["--limite", "5"], ["batman", "q"])
    assert "40 jogo(s) para \"batman\" (mostrando 5)" in out and " 5. Batman" in out and " 6. Batman" not in out
    ruim = tmp_path / "ruim.json"
    ruim.write_text(json.dumps({"schema": versoes.SCHEMA, "versoes": [{"qid": "x", "cusa": "CUSA1"}]}), encoding="utf-8")
    assert jogos.executar(["--indice", indice(tmp_path), "--versoes", str(ruim)], entrada=lambda p="": "q", saida=lambda *a: None) == 2
    (tmp_path / "lixo.json").write_text("{}", encoding="utf-8")
    assert jogos.executar(["--indice", str(tmp_path / "lixo.json")], entrada=lambda p="": "q", saida=lambda *a: None) == 2


def test_modulo_usa_so_busca_e_versoes_e_nao_importa_resolvedor_nem_colar():
    fonte = (ROOT / "src" / "ps4store" / "jogos.py").read_text(encoding="utf-8")
    assert "from . import busca, versoes" in fonte and "resolver" not in fonte.replace("resolvedor", "") and "colar" not in fonte and "browser" not in fonte
