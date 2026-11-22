"""JOGOS: busca por nome + consulta de versões CUSA num só fluxo interativo (Termux). Usa busca.py e versoes.py como bibliotecas.

Fluxo: digitar um nome -> lista numerada -> escolher o número -> ver os CUSAs ligados ao Q-id escolhido (filtros opcionais por CUSA, região e idioma).
Só metadados: não resolve links, não baixa nada, e um CUSA não indica que exista PKG/download. Nada é inventado: sem registro de versão, diz que não há.
"""
from __future__ import annotations

import argparse
import re
import sys

from . import busca, versoes

CUSA_RE = versoes.CUSA_RE
LIMITE_LISTA = 30
AJUDA_JOGO = "Comandos: número = outro resultado · f cusa X / f regiao X / f idioma X · f limpar · e = fontes · b = lista · n = nova busca · q = sair"


def _qid(item: dict) -> str | None:
    i = str(item.get("idFonte", ""))
    return i.split(":", 1)[1] if i.startswith("wikidata:") else None


def indexar_versoes(vdoc: dict) -> dict[str, list[dict]]:
    por: dict[str, list[dict]] = {}
    for r in vdoc.get("versoes", []):
        por.setdefault(r["qid"], []).append(r)
    return por


def resultados_para(termo: str, indice: dict, vdoc: dict, limite: int = 200) -> tuple[list[dict], bool]:
    """Jogos que casam com o nome. Devolve (itens, usou_so_versoes). Com índice vazio, usa só os rótulos dos registros de versão (e avisa)."""
    if indice.get("titulos"):
        return busca.buscar(indice, termo, limite=limite), False
    q = busca.norm(termo)
    vistos, itens = set(), []
    for r in vdoc.get("versoes", []):
        if q and all(w in busca.norm(r.get("jogo")) for w in q.split()) and r["qid"] not in vistos:
            vistos.add(r["qid"])
            itens.append({"nome": r["jogo"], "idFonte": f"wikidata:{r['qid']}", "url": "", "fonte": "versoes"})
    return itens, True


def linha_resultado(n: int, item: dict, por_qid: dict[str, list[dict]]) -> str:
    q = _qid(item)
    ano = f" ({item['lancamento']})" if item.get("lancamento") else ""
    base = f"{n:>2}. {item['nome']}{ano}" + (f"  [wikidata:{q}]" if q else "")
    if not q:
        return base + "  · sem Q-id do Wikidata: não dá para vincular versões"
    rs = por_qid.get(q, [])
    if not rs:
        return base + "  · sem versões cadastradas"
    return base + f"  · {len(rs)} registro(s), {len({r['cusa'] for r in rs})} CUSA(s) distinto(s)"


def rotulo_status(r: dict) -> str:
    if r.get("status") == "confirmado":
        c = r.get("confirmacao") or {}
        return f"CONFIRMADO por {c.get('por', '?')} em {c.get('em', '?')}"
    return "CITADO: a fonte foi vista, mas a página não foi aberta nem conferida"


def blocos_versao(r: dict, todas_as_fontes: bool = False) -> list[str]:
    reg = r.get("regiao")
    out = [f"  {r['cusa']}   (CUSA: identificador do título)"]
    out.append(f"    Content ID: {r['contentId']}   (identifica este produto/edição; NÃO é o CUSA)" if r.get("contentId") else "    Content ID: desconhecido")
    out.append(f"    Edição: {r['edicao']}   (registro de edição/produto da loja, não de jogo-base)" if r.get("edicao") else "    Edição: desconhecida")
    out.append(f"    Região: {reg['codigo']}   (base: {reg['base']})" if reg else "    Região: desconhecida")
    if r.get("idiomas"):
        out.append(f"    Idiomas: {', '.join(r['idiomas'])}   (base: {r.get('idiomasBase', '?')})")
    else:
        out.append("    Idiomas: desconhecidos   (a região não define o idioma)")
    out.append(f"    Versão do pacote: {r['versao']}" if r.get("versao") else "    Versão do pacote: desconhecida")
    out.append(f"    Status: {rotulo_status(r)}")
    ev = r.get("evidencias", [])
    for x in (ev if todas_as_fontes else ev[:1]):
        out.append(f"    Fonte: {x['fonte']}  {x['url']}")
    if todas_as_fontes and r.get("nota"):
        out.append(f"    Nota: {r['nota']}")
    return out


def descrever_filtros(f: dict) -> str:
    ativos = [f"{k}={v}" for k, v in f.items() if v]
    return "filtros: " + (", ".join(ativos) if ativos else "nenhum (todos os registros)")


def mostrar_jogo(item: dict, indice: dict, por_qid: dict[str, list[dict]], filtros: dict, todas_as_fontes: bool, saida) -> None:
    q = _qid(item)
    ano = f" ({item['lancamento']})" if item.get("lancamento") else ""
    saida(f"\n== {item['nome']}{ano}" + (f"  [wikidata:{q}]" if q else ""))
    if item.get("url"):
        saida(f"   página de referência: {item['url']}")
    if not q:
        saida("   Este resultado não tem Q-id do Wikidata: não há como vincular versões CUSA (nunca por semelhança de nome).")
        return
    rs = por_qid.get(q, [])
    if not rs:
        saida(f"   Nenhuma versão CUSA cadastrada para {q}.")
        saida("   Isso NÃO quer dizer que o jogo não tenha CUSA: só que ainda não há registro com fonte. Nada foi inventado.")
        return
    for r in rs:                                                  # aviso se o rótulo do registro difere do nome do índice (confira o vínculo)
        if busca.norm(r.get("jogo")) != busca.norm(item["nome"]):
            saida(f"   ATENÇÃO: o registro {r['cusa']} foi cadastrado como \"{r['jogo']}\" para este Q-id; confira o vínculo.")
            break
    visiveis, omitidos = versoes.consultar({"versoes": rs}, cusa=filtros.get("cusa"), regiao=filtros.get("regiao"), idioma=filtros.get("idioma"))
    saida(f"   {len(rs)} registro(s) de versão, {len({r['cusa'] for r in rs})} CUSA(s) distinto(s) · {descrever_filtros(filtros)}")
    if not any(r.get("escopo") == "jogo-base" for r in rs):
        saida("   Nenhum registro está marcado como jogo-base: o que aparece são produtos/edições da loja.")
    if not visiveis:
        saida("   Nenhum registro passa nos filtros" + (f" ({omitidos} sem o campo conhecido ficaram de fora: o valor desconhecido não é presumido)" if omitidos else "") + ". Digite 'f limpar' para ver todos.")
        return
    for r in visiveis:
        saida("\n".join(blocos_versao(r, todas_as_fontes)))
    if omitidos:
        saida(f"   {omitidos} registro(s) sem o campo filtrado ficaram de fora: o valor desconhecido não é presumido.")
    saida("   (CUSA identifica o título; não é link e não indica que exista PKG/download. Para links, use o resolvedor.)")


def aplicar_filtro(cmd: str, filtros: dict) -> str:
    p = cmd.split(None, 2)
    if len(p) == 1:
        return descrever_filtros(filtros)
    if p[1].lower() in ("limpar", "limpa", "clear"):
        filtros.update({"cusa": None, "regiao": None, "idioma": None})
        return "filtros removidos: todos os registros"
    if len(p) < 3 or p[1].lower() not in ("cusa", "regiao", "região", "idioma"):
        return "uso: f cusa CUSA00133 · f regiao EU · f idioma Korean · f limpar"
    campo, valor = p[1].lower().replace("região", "regiao"), p[2].strip()
    if campo == "cusa":
        if not CUSA_RE.match(valor.upper()):
            return "CUSA inválido (esperado CUSA + 5 dígitos, ex.: CUSA00133). Não confunda com o Content ID."
        valor = valor.upper()
    filtros[campo] = valor
    return f"filtro {campo} = {valor}"


def _responder(entrada, texto: str):
    try:
        return entrada(texto).strip()
    except EOFError:
        return None


def executar(argv=None, entrada=input, saida=print) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.jogos", description="pesquisa um jogo por nome e consulta as versões CUSA (interativo)")
    ap.add_argument("termo", nargs="*", help="nome (opcional; sem ele o programa pergunta)")
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusa")
    ap.add_argument("--regiao")
    ap.add_argument("--idioma")
    ap.add_argument("--evidencias", action="store_true")
    ap.add_argument("--escolher", type=int, metavar="N", help="sem perguntar: mostra o resultado de número N e sai")
    ap.add_argument("--limite", type=int, default=LIMITE_LISTA)
    a = ap.parse_args(argv)
    try:
        indice = busca.carregar_indice(a.indice)
        vdoc = versoes.carregar(a.versoes)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    erros = versoes.validar_doc(vdoc)
    if erros:
        print(f"ERRO  o arquivo de versões tem {len(erros)} problema(s); rode: python -m ps4store.versoes --validar", file=sys.stderr)
        return 2
    por_qid = indexar_versoes(vdoc)
    filtros = {"cusa": a.cusa.upper() if a.cusa else None, "regiao": a.regiao, "idioma": a.idioma}
    fontes = a.evidencias
    if not indice.get("titulos"):
        saida(f"AVISO  índice de busca vazio ou ausente ({a.indice}): só dá para achar jogos que já têm versões cadastradas. Gere o índice: python -m ps4store.wikidata --atualizar")
    termo = " ".join(a.termo).strip()
    itens: list[dict] = []
    atual: dict | None = None
    saida("PS4 Store BR · busca de jogos e versões CUSA (metadados; sem downloads)")
    while True:
        if atual is not None:
            cmd = _responder(entrada, "\n[jogo] comando (? ajuda): ")
            if cmd is None or cmd.lower() in ("q", "sair"):
                return 0
            low = cmd.lower()
            if low == "?":
                saida(AJUDA_JOGO)
            elif low in ("b", "lista") and itens:
                atual = None
            elif low in ("n", "nova"):
                atual, itens, termo = None, [], ""
            elif low == "e":
                fontes = not fontes
                saida("mostrando " + ("todas as fontes e notas" if fontes else "só a primeira fonte"))
                mostrar_jogo(atual, indice, por_qid, filtros, fontes, saida)
            elif low.startswith("f"):
                saida(aplicar_filtro(cmd, filtros))
                mostrar_jogo(atual, indice, por_qid, filtros, fontes, saida)
            elif cmd.isdigit() and 1 <= int(cmd) <= len(itens):
                atual = itens[int(cmd) - 1]
                mostrar_jogo(atual, indice, por_qid, filtros, fontes, saida)
            else:
                saida("comando não reconhecido (? para ajuda)")
            continue
        if not termo:
            termo = _responder(entrada, "\nNome do jogo (parte do nome; Enter ou q para sair): ")
            if termo is None or termo.lower() in ("", "q", "sair"):
                return 0
        up = termo.upper()
        if versoes.CONTENT_ID_RE.match(up):                        # o usuário digitou um Content ID: explica e mostra, sem confundir com CUSA
            achados = [r for r in vdoc["versoes"] if (r.get("contentId") or "").upper() == up]
            m = versoes.CONTENT_ID_RE.match(up)
            saida(f"\"{termo}\" é um Content ID (identifica um produto/edição), não um CUSA. O CUSA contido nele é {m.group(2)}.")
            itens = [{"nome": r["jogo"], "idFonte": f"wikidata:{r['qid']}", "url": ""} for r in achados]
            if not achados:
                saida("Nenhum registro cadastrado com este Content ID.")
        elif CUSA_RE.match(up):                                    # o usuário digitou um CUSA: lista os jogos que têm registro com ele
            qs = []
            for r in vdoc["versoes"]:
                if r["cusa"] == up and r["qid"] not in qs:
                    qs.append(r["qid"])
            itens = [{"nome": next(x["jogo"] for x in vdoc["versoes"] if x["qid"] == q), "idFonte": f"wikidata:{q}", "url": ""} for q in qs]
            saida(f"\n{up} é um CUSA (identificador do título)." + ("" if itens else " Nenhum registro cadastrado com ele."))
        else:
            itens, so_versoes = resultados_para(termo, indice, vdoc)
            if so_versoes and itens:
                saida("(índice de busca ausente: lista só com jogos que têm versões cadastradas)")
        if not itens:
            saida(f'Nenhum jogo encontrado para "{termo}".')
            if a.escolher:
                return 1
            termo = ""
            if a.termo:
                return 1
            continue
        mostrados = itens[:max(1, a.limite)]
        saida(f'\n{len(itens)} jogo(s) para "{termo}"' + (f" (mostrando {len(mostrados)})" if len(itens) > len(mostrados) else "") + ":")
        for n, it in enumerate(mostrados, 1):
            saida(linha_resultado(n, it, por_qid))
        itens = mostrados
        if a.escolher:
            if not 1 <= a.escolher <= len(itens):
                saida(f"Número {a.escolher} fora da lista (1 a {len(itens)}).")
                return 2
            mostrar_jogo(itens[a.escolher - 1], indice, por_qid, filtros, fontes, saida)
            return 0
        while atual is None:
            r = _responder(entrada, "\nEscolha o número (n = nova busca, q = sair): ")
            if r is None or r.lower() in ("q", "sair"):
                return 0
            if r.lower() in ("n", "nova"):
                termo, itens = "", []
                break
            if r.isdigit() and 1 <= int(r) <= len(itens):
                atual = itens[int(r) - 1]
                mostrar_jogo(atual, indice, por_qid, filtros, fontes, saida)
                saida(AJUDA_JOGO)
            else:
                saida(f"Digite um número de 1 a {len(itens)}.")
        if atual is None:
            continue


def main(argv=None) -> int:
    try:
        return executar(argv)
    except KeyboardInterrupt:
        print("\nSaindo.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
