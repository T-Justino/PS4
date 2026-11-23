"""AUDITORIA: revisa os CONFLITOS de CUSA já importados (local/cusas-wikidata.json) e os classifica SÓ com a evidência que existe nos dados locais.
Somente leitura dos dados (nada é apagado, trocado ou associado); grava apenas o relatório (local/auditoria-cusas.json). Sem rede. Stdlib, Termux.

Classes (nenhuma resolve nada sozinha; todas ficam pendentes para revisão humana):
  possivel-produto-relacionado: o mesmo CUSA pode legitimamente cobrir produtos relacionados. Evidência: (forte) Content IDs DIFERENTES com o mesmo CUSA nos
      jogos em conflito, ou (fraca) nomes em que um contém o outro mais um marcador de edição/pacote (edition, bundle, season pass...).
  associacao-contraditoria: indício de que a atribuição não pode estar certa: o registro curado (fonte oficial citada) pertence a outro jogo e os nomes não têm
      relação; ou os nomes dos jogos não têm nenhuma relação entre si.
  indeterminado: o resto (mesma série, mesmo nome, mesmo Content ID, nomes parcialmente parecidos...).
Tipo do produto (jogo-base, edição, DLC) fica "desconhecido": só aparecem INDÍCIOS (ex.: sufixo DLC no Content ID), marcados como não confirmados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from . import busca, cusas, versoes

AUDITORIA_PADRAO = "local/auditoria-cusas.json"
SCHEMA = "ps4store.auditoria-cusas/v1"
RELACIONADO, CONTRADITORIA, INDETERMINADO = "possivel-produto-relacionado", "associacao-contraditoria", "indeterminado"
ROTULOS = {RELACIONADO: "possível produto relacionado (não confirmado)", CONTRADITORIA: "associação contraditória", INDETERMINADO: "indeterminado",
           "nao-auditado": "não auditado"}
STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "to", "de", "da", "do", "das", "dos", "e", "o", "os", "as", "no", "na", "em", "para", "com", "vs", "ps4"}
MARCADORES = {"edition", "edicao", "bundle", "collection", "colecao", "pack", "pacote", "season", "pass", "dlc", "addon", "expansion", "expansao", "goty",
              "deluxe", "ultimate", "complete", "premium", "standard", "digital", "gold", "platinum", "legendary", "anniversary", "limited", "special"}
CONTENT_ID_RE = versoes.CONTENT_ID_RE


def _tokens(nome: str) -> list[str]:
    return [w for w in busca.norm(nome).split() if w not in STOP]


def relacao_nomes(a: str, b: str) -> tuple[str, str]:
    """(relação, explicação) entre dois nomes: 'mesmo-nome' | 'contido-com-marcador' | 'contido-sem-marcador' | 'sem-relacao' | 'parcial'."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return "parcial", "nome sem palavras comparáveis"
    if ta == tb:
        return "mesmo-nome", "os dois Q-ids têm o mesmo nome"
    curto, longo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if longo[:len(curto)] == curto:
        extra = longo[len(curto):]
        if any(w in MARCADORES for w in extra):
            return "contido-com-marcador", f"um nome é o outro mais um marcador de edição/pacote ({', '.join(w for w in extra if w in MARCADORES)})"
        return "contido-sem-marcador", "um nome começa com o outro, mas sem marcador de edição/pacote (pode ser outro jogo da série)"
    if not set(ta) & set(tb):
        return "sem-relacao", "os nomes não têm nenhuma palavra significativa em comum"
    return "parcial", "os nomes têm palavras em comum, mas não indicam o mesmo produto (ex.: jogos da mesma série)"


def _content_ids(evidencias: list[dict]) -> list[str]:
    out = []
    for e in evidencias:
        v = (e.get("valor") or "").strip()
        if CONTENT_ID_RE.match(v) and v not in out:
            out.append(v)
    return out


def _indicios_cid(cids: list[str]) -> list[str]:
    out = []
    for c in cids:
        sufixo = c.split("-")[-1]
        if sufixo.startswith("DLC"):
            out.append(f"sufixo \"{sufixo}\" no Content ID {c}: indício de DLC (NÃO confirmado)")
    return out


def _qid_da_url(url: str) -> str | None:
    m = re.search(r"/wiki/(Q[0-9]+)$", url or "")
    return m.group(1) if m else None


def classificar(conf: dict, nomes: dict[str, str], anos: dict[str, str], curados: dict) -> dict:
    cusa, qids = conf["cusa"], list(conf["qids"])
    cur = [r for r in curados.get("versoes", []) if r.get("cusa") == cusa]
    cur_qids = {r["qid"] for r in cur}
    por_q: dict[str, dict] = {}
    for q in qids:
        evs = [e for e in conf.get("evidencias", []) if _qid_da_url(e.get("url", "")) == q]
        cids = _content_ids(evs)
        for r in cur:
            if r["qid"] == q and r.get("contentId") and r["contentId"] not in cids:
                cids.append(r["contentId"])
        por_q[q] = {"qid": q, "nome": nomes.get(q) or next((n for qq, n in zip(conf["qids"], conf.get("jogos", [])) if qq == q), q), "ano": anos.get(q),
                    "curado": q in cur_qids, "contentIds": cids,
                    "propriedades": [{"propriedade": e.get("propriedade"), "rotulo": e.get("rotuloPropriedade", ""), "valor": e.get("valor"), "consultadoEm": e.get("consultadoEm")}
                                     for e in evs],
                    "tipoProduto": "desconhecido", "indicios": _indicios_cid(cids)}
    just: list[str] = []
    pares = list(combinations(qids, 2))
    rels = {(a, b): relacao_nomes(por_q[a]["nome"], por_q[b]["nome"]) for a, b in pares}
    todos_cids = [c for q in qids for c in por_q[q]["contentIds"]]
    classe, nivel = INDETERMINADO, "nenhuma"
    cid_por_q = {q: set(por_q[q]["contentIds"]) for q in qids if por_q[q]["contentIds"]}
    cids_distintos = len(cid_por_q) >= 2 and len(set().union(*cid_por_q.values())) > max(len(v) for v in cid_por_q.values()) and not set.intersection(*cid_por_q.values())
    if cids_distintos:
        classe, nivel = RELACIONADO, "content-id"
        just.append("o mesmo CUSA aparece com Content IDs DIFERENTES (" + "; ".join(sorted(set(todos_cids))[:4]) + "): o título pode cobrir mais de um produto")
    elif cid_por_q and len(cid_por_q) >= 2 and set.intersection(*cid_por_q.values()):
        just.append("os dois Q-ids apontam para o MESMO Content ID: possível item duplicado no Wikidata")
    elif pares and all(r[0] == "contido-com-marcador" for r in rels.values()):
        classe, nivel = RELACIONADO, "nomes"
        just += [f"{por_q[a]['nome']} × {por_q[b]['nome']}: {r[1]}" for (a, b), r in rels.items()][:3]
        just.append("evidência fraca (só pelos nomes); não confirmado")
    elif any(r[0] == "sem-relacao" for r in rels.values()):
        classe = CONTRADITORIA
        nivel = "fonte-oficial-curada" if cur_qids else "nomes-sem-relacao"
        for (a, b), r in rels.items():
            if r[0] == "sem-relacao":
                just.append(f"{por_q[a]['nome']} × {por_q[b]['nome']}: {r[1]}")
        if cur_qids:
            just.append("o registro curado deste CUSA tem fonte oficial citada: " + ", ".join(sorted(f"{por_q[q]['nome']} [{q}]" for q in cur_qids if q in por_q)))
        just = just[:4]
    else:
        for (a, b), r in rels.items():
            just.append(f"{por_q[a]['nome']} × {por_q[b]['nome']}: {r[1]}")
        just = just[:3] or ["sem evidência suficiente"]
    return {"cusa": cusa, "motivo": conf["motivo"], "classificacao": classe, "rotulo": ROTULOS[classe], "nivelEvidencia": nivel, "justificativas": just,
            "jogos": [por_q[q] for q in qids], "revisaoPendente": True}


def _sha(caminho: str) -> str | None:
    try:
        return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()
    except OSError:
        return None


def auditar(dados: dict, indice: dict, curados: dict) -> dict:
    nomes, anos = {}, {}
    for t in indice.get("titulos", []):
        i = str(t.get("idFonte", ""))
        if i.startswith("wikidata:"):
            q = i.split(":", 1)[1]
            nomes[q], anos[q] = t["nome"], t.get("lancamento")
    for r in curados.get("versoes", []):
        nomes.setdefault(r["qid"], r.get("jogo", r["qid"]))
    itens = [classificar(c, nomes, anos, curados) for c in dados.get("conflitos", [])]
    cont = {k: sum(1 for i in itens if i["classificacao"] == k) for k in (RELACIONADO, CONTRADITORIA, INDETERMINADO)}
    motivos: dict[str, int] = {}
    for i in itens:
        motivos[i["motivo"]] = motivos.get(i["motivo"], 0) + 1
    return {"schema": SCHEMA, "geradoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dadosConsultadosEm": dados.get("consultadoEm", ""),
            "aviso": "Auditoria só com evidência local. Nada foi associado, apagado ou substituído; todos os conflitos continuam pendentes de revisão. "
                     "Dados do Wikidata não são verificados em fonte oficial.",
            "resumo": {"conflitos": len(itens), **{k.replace("-", "_"): v for k, v in cont.items()}, "porMotivo": motivos}, "conflitos": itens}


def carregar_auditoria(caminho: str = AUDITORIA_PADRAO) -> dict:
    """Relatório (ou vazio). Usado pelo painel para rotular conflitos; erro de leitura = sem auditoria."""
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "conflitos": []}
    return d if d.get("schema") == SCHEMA and isinstance(d.get("conflitos"), list) else {"schema": SCHEMA, "conflitos": []}


def _gravar(doc: dict, caminho: str) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _linhas(i: dict) -> list[str]:
    out = [f"{i['cusa']} · {i['rotulo']} · evidência: {i['nivelEvidencia']} · {i['motivo']}"]
    for j in i["jogos"]:
        props = ", ".join(f"{p['propriedade']}={p['valor']}" for p in j["propriedades"][:3]) or ("(registro curado)" if j["curado"] else "")
        out.append(f"    {j['qid']} {j['nome']}" + (f" ({j['ano']})" if j.get("ano") else "") + (f" · {props}" if props else "") + (" · CURADO" if j["curado"] else ""))
        for ind in j["indicios"]:
            out.append(f"        indício: {ind}")
    for t in i["justificativas"][:2]:
        out.append(f"    → {t}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.auditoria", description="audita os conflitos de CUSA já importados (somente leitura dos dados; sem rede)")
    ap.add_argument("--dados", default=cusas.DADOS_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--saida", default=AUDITORIA_PADRAO, help="relatório JSON (único arquivo gravado)")
    ap.add_argument("--classe", choices=["relacionado", "contraditoria", "indeterminado"], help="mostra só esta classe")
    ap.add_argument("--cusa", help="mostra só este CUSA")
    ap.add_argument("--limite", type=int, default=6, help="conflitos mostrados por classe (padrão 6)")
    ap.add_argument("--todos", action="store_true")
    a = ap.parse_args(argv)
    try:
        dados = cusas.carregar_dados(a.dados)
        indice = busca.carregar_indice(a.indice)
        curados = versoes.carregar(a.versoes)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if not dados.get("registros") and not dados.get("conflitos"):
        print(f"ERRO  sem dados de CUSAs em {a.dados}: rode python -m ps4store.cusas --atualizar", file=sys.stderr)
        return 2
    entradas = {k: _sha(v) for k, v in (("dados", a.dados), ("indice", a.indice), ("versoes", a.versoes))}
    rel = auditar(dados, indice, curados)
    rel["entradas"] = {k: {"arquivo": v, "sha256": entradas[k]} for k, v in (("dados", a.dados), ("indice", a.indice), ("versoes", a.versoes))}
    _gravar(rel, a.saida)
    r = rel["resumo"]
    print(f"Auditoria de CUSAs em conflito · {r['conflitos']} conflito(s) · dados consultados em {rel['dadosConsultadosEm'] or '?'} (Wikidata, não verificados oficialmente)")
    print(f"  possível produto relacionado: {r['possivel_produto_relacionado']} · associação contraditória: {r['associacao_contraditoria']} · indeterminado: {r['indeterminado']}")
    for m, n in r["porMotivo"].items():
        print(f"  {n}× {m}")
    ordem = [(RELACIONADO, "relacionado"), (CONTRADITORIA, "contraditoria"), (INDETERMINADO, "indeterminado")]
    for classe, chave in ordem:
        if a.classe and a.classe != chave:
            continue
        itens = [i for i in rel["conflitos"] if i["classificacao"] == classe and (not a.cusa or i["cusa"] == a.cusa.upper())]
        if not itens:
            continue
        print(f"\n== {ROTULOS[classe]} ({len(itens)}) · nada foi associado automaticamente")
        for i in (itens if a.todos else itens[:max(1, a.limite)]):
            print("\n".join(_linhas(i)))
        if not a.todos and len(itens) > a.limite:
            print(f"    … e mais {len(itens) - a.limite} (use --todos ou --classe)")
    print(f"\nRelatório completo: {a.saida}. Os dados originais não foram alterados; todos os conflitos continuam pendentes de revisão.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
