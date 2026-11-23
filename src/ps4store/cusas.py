"""CUSAS: enriquece o catálogo com CUSAs ALEGADOS no Wikidata (propriedades P5944, P5971, P5999 por padrão), ligados aos Q-ids do índice local.

Só metadados. Os valores NÃO são presumidos: o rótulo de cada propriedade é pedido ao serviço na hora (não assumimos o que P5944/P5999 significam) e só
entram valores que sejam EXATAMENTE um CUSA (CUSA + 5 dígitos) ou um Content ID completo (que embute o CUSA). PPSA (PS5), NPXS e qualquer outro formato
são rejeitados e contados. Nada de região, idioma, edição, versão ou Content ID é inventado. Um CUSA que o Wikidata atribui a mais de um jogo (ou que
contradiz um registro curado) vira CONFLITO para revisão e não é associado. Os registros da 5B (data/versoes-cusa.json) nunca são alterados: o resultado
fica em local/cusas-wikidata.json e a visão unificada (unificada.py) os junta SEM misturar a origem ("wikidata" = alegado; nunca "verificado em fonte oficial").
Importação incremental: cache por propriedade (local/cusas-wikidata-cache.json), pausa entre consultas, teto de requisições, e uma coleta incompleta não
substitui nem o cache nem o resultado válidos. Independente, stdlib, Termux.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from . import busca, versoes, wikidata

PROPS_PADRAO = ("P5944", "P5971", "P5999")
CACHE_PADRAO = "local/cusas-wikidata-cache.json"
DADOS_PADRAO = "local/cusas-wikidata.json"
SCHEMA_CACHE = "ps4store.cusas-cache/v1"
SCHEMA_DADOS = "ps4store.cusas-wikidata/v1"
PROP_RE = re.compile(r"^P[0-9]{1,7}$")
CUSA_RE = versoes.CUSA_RE
CONTENT_ID_RE = versoes.CONTENT_ID_RE
TOLERANCIA = wikidata.TOLERANCIA
TAM_PAGINA = 1000
LOTE_QIDS = 50
MAX_REQ_PADRAO = 60


def _prop(p: str) -> str:
    if not PROP_RE.match(p):
        raise ValueError(f"propriedade inválida: {p!r}")
    return p


def _jogos_ps4() -> str:
    return f"?g wdt:P31/wdt:P279* wd:{wikidata.Q_VIDEO_GAME} ; wdt:P400 wd:{wikidata.Q_PLAYSTATION_4} ."


# ---------- consultas (identificadores validados; nunca texto livre) ----------
def q_rotulos(props) -> str:
    vals = " ".join(f"wd:{_prop(p)}" for p in props)
    return f'SELECT ?p ?l WHERE {{ VALUES ?p {{ {vals} }} ?p rdfs:label ?l . FILTER(LANG(?l) = "en") }}'


def q_contagem(prop: str) -> str:
    return f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ {_jogos_ps4()} ?g wdt:{_prop(prop)} ?x . }}"


def q_pagina(prop: str, limite: int, desloc: int) -> str:
    """Página de JOGOS DISTINTOS que têm a propriedade (DISTINCT na subconsulta: LIMIT/OFFSET contam jogos), com todos os valores de cada um."""
    p = _prop(prop)
    return (f"SELECT ?g ?v WHERE {{ {{ SELECT DISTINCT ?g WHERE {{ {_jogos_ps4()} ?g wdt:{p} ?x . }} ORDER BY ?g LIMIT {int(limite)} OFFSET {int(desloc)} }} "
            f"?g wdt:{p} ?v . }} ORDER BY ?g ?v")


def q_exemplos(prop: str, n: int = 20) -> str:
    return f"SELECT ?g ?v WHERE {{ {_jogos_ps4()} ?g wdt:{_prop(prop)} ?v . }} LIMIT {int(n)}"


def q_amostra(qids, props) -> str:
    for q in qids:
        if not wikidata_qid_ok(q):
            raise ValueError(f"Q-id inválido: {q!r}")
    gs = " ".join(f"wd:{q}" for q in qids)
    ps = " ".join(f"wdt:{_prop(p)}" for p in props)
    return f"SELECT ?g ?p ?v WHERE {{ VALUES ?g {{ {gs} }} VALUES ?p {{ {ps} }} ?g ?p ?v . }}"


def wikidata_qid_ok(q: str) -> bool:
    return bool(re.match(r"^Q[0-9]{1,12}$", q or ""))


def executar(fetch, q: str) -> list[dict]:
    return json.loads(fetch(wikidata.url_consulta(q)))["results"]["bindings"]


def _v(b: dict, k: str) -> str:
    return wikidata._val(b, k)


def _qid(uri: str) -> str | None:
    m = wikidata._ENT.match(uri or "")
    return m.group(1) if m else None


# ---------- extração: só CUSA exato ou Content ID completo ----------
def extrair(valor: str) -> tuple[str | None, str | None, str | None]:
    """(cusa, contentId, motivo_da_rejeição). Estrito: nada é corrigido, normalizado ou deduzido."""
    v = (valor or "").strip()
    if not v:
        return None, None, "vazio"
    if CUSA_RE.match(v):
        return v, None, None
    m = CONTENT_ID_RE.match(v)
    if m:
        return m.group(2), v, None
    if "PPSA" in v:
        return None, None, "ppsa-ps5"
    if "NPXS" in v:
        return None, None, "npxs"
    if "CUSA" in v:
        return None, None, "formato-com-cusa-nao-reconhecido"
    return None, None, "formato-desconhecido"


# ---------- construção do resultado ----------
def _qids_do_indice(indice: dict) -> dict[str, str]:
    return {str(t["idFonte"]).split(":", 1)[1]: t["nome"] for t in indice.get("titulos", []) if str(t.get("idFonte", "")).startswith("wikidata:")}


def construir(por_prop: dict[str, dict], indice: dict, curados: dict | None = None, consultado_em: str = "") -> dict:
    """`por_prop[P] = {"rotulo", "consultadoEm", "linhas": [[qid, valor], ...]}`. Só Q-ids do índice local; conflitos ficam de fora das associações."""
    nomes = _qids_do_indice(indice)
    cand: dict[tuple[str, str], dict] = {}
    rejeitados: dict[str, int] = {}
    amostras_rej: list[dict] = []
    fora = 0
    com_valor: set[str] = set()
    est_prop: dict[str, dict] = {}
    for prop, d in por_prop.items():
        e = est_prop.setdefault(prop, {"rotulo": d.get("rotulo", ""), "linhas": 0, "jogosNoIndice": set(), "comCusaValido": set()})
        for qid, valor in d.get("linhas", []):
            e["linhas"] += 1
            if qid not in nomes:
                fora += 1
                continue
            com_valor.add(qid)
            e["jogosNoIndice"].add(qid)
            cusa, cid, motivo = extrair(valor)
            if motivo:
                rejeitados[motivo] = rejeitados.get(motivo, 0) + 1
                if len(amostras_rej) < 20:
                    amostras_rej.append({"qid": qid, "propriedade": prop, "valor": valor[:60], "motivo": motivo})
                continue
            e["comCusaValido"].add(qid)
            r = cand.setdefault((qid, cusa), {"qid": qid, "jogo": nomes[qid], "cusa": cusa, "contentIds": [], "origem": "wikidata", "verificadoEmFonteOficial": False,
                                              "evidencias": []})
            if cid and cid not in r["contentIds"]:
                r["contentIds"].append(cid)
            ev = {"fonte": "Wikidata", "propriedade": prop, "rotuloPropriedade": d.get("rotulo", ""), "valor": valor,
                  "url": f"https://www.wikidata.org/wiki/{qid}", "consultadoEm": d.get("consultadoEm") or consultado_em}
            if ev not in r["evidencias"]:
                r["evidencias"].append(ev)
    # conflitos: mesmo CUSA em Q-ids diferentes (Wikidata) ou contradizendo um registro curado
    por_cusa: dict[str, set[str]] = {}
    for (qid, cusa) in cand:
        por_cusa.setdefault(cusa, set()).add(qid)
    cur_por_cusa: dict[str, set[str]] = {}
    for r in (curados or {}).get("versoes", []):
        cur_por_cusa.setdefault(r["cusa"], set()).add(r["qid"])
    conflitos, excluir = [], set()
    for cusa, qs in sorted(por_cusa.items()):
        if len(qs) > 1:
            conflitos.append({"cusa": cusa, "motivo": "o Wikidata atribui o mesmo CUSA a mais de um jogo", "qids": sorted(qs), "jogos": [nomes[q] for q in sorted(qs)],
                              "evidencias": [ev for q in sorted(qs) for ev in cand[(q, cusa)]["evidencias"]]})
            excluir |= {(q, cusa) for q in qs}
        cq = cur_por_cusa.get(cusa, set())
        for q in qs:
            if cq and q not in cq:
                conflitos.append({"cusa": cusa, "motivo": "contradiz o registro curado: o CUSA já está cadastrado para outro Q-id", "qids": sorted({q} | cq),
                                  "jogos": [nomes.get(x, x) for x in sorted({q} | cq)], "evidencias": cand[(q, cusa)]["evidencias"]})
                excluir.add((q, cusa))
    registros = [r for k, r in sorted(cand.items(), key=lambda kv: (int(kv[0][0][1:]), kv[0][1])) if k not in excluir]
    com_cusa = {r["qid"] for r in registros}
    por_propriedade = {p: {"rotulo": e["rotulo"], "linhas": e["linhas"], "jogosNoIndice": len(e["jogosNoIndice"]), "comCusaValido": len(e["comCusaValido"])}
                       for p, e in est_prop.items()}
    return {"schema": SCHEMA_DADOS, "fonte": "Wikidata (CC0-1.0)", "consultadoEm": consultado_em, "propriedades": {p: d.get("rotulo", "") for p, d in por_prop.items()},
            "registros": registros, "conflitos": conflitos,
            "estatisticas": {"jogosNoIndice": len(nomes), "jogosComValor": len(com_valor), "jogosComCusa": len(com_cusa), "jogosSemCusa": len(nomes) - len(com_cusa),
                             "cusasDistintos": len({r["cusa"] for r in registros}), "registros": len(registros), "conflitos": len(conflitos),
                             "linhasForaDoIndice": fora, "rejeitados": rejeitados, "porPropriedade": por_propriedade},
            "amostrasRejeitadas": amostras_rej}


# ---------- arquivos ----------
def _gravar(doc: dict, caminho: str) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def carregar_cache(caminho: str) -> dict:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": SCHEMA_CACHE, "propriedades": {}}
    if d.get("schema") != SCHEMA_CACHE or not isinstance(d.get("propriedades"), dict):
        raise ValueError(f"{caminho} não é um cache {SCHEMA_CACHE}")
    return d


def carregar_dados(caminho: str = DADOS_PADRAO) -> dict:
    """Resultado importado (ou vazio). Usado pela visão unificada, pelo painel e pelo CLI."""
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": SCHEMA_DADOS, "registros": [], "conflitos": []}
    if d.get("schema") != SCHEMA_DADOS or not isinstance(d.get("registros"), list):
        raise ValueError(f"{caminho} não é um arquivo {SCHEMA_DADOS}")
    return d


# ---------- coleta ----------
class Orcamento:
    """Teto de requisições da execução + pausa entre elas."""

    def __init__(self, fetch, maximo: int, pausa: float, dormir):
        self.fetch, self.maximo, self.pausa, self.dormir, self.usadas = fetch, maximo, pausa, dormir, 0

    def __call__(self, q: str) -> list[dict]:
        if self.usadas >= self.maximo:
            raise LimiteDeRequisicoes(f"teto de {self.maximo} requisições atingido")
        if self.usadas:
            self.dormir(self.pausa)
        self.usadas += 1
        return executar(self.fetch, q)


class LimiteDeRequisicoes(RuntimeError):
    pass


def rotulos(orc, props) -> dict[str, str]:
    out = {}
    for b in orc(q_rotulos(props)):
        m = re.search(r"/(P[0-9]+)$", _v(b, "p"))
        if m:
            out[m.group(1)] = _v(b, "l")
    return out


def coletar_propriedade(orc, prop: str, tamanho: int = TAM_PAGINA, max_paginas: int = 40, progresso=None) -> dict:
    """Todas as linhas (qid, valor) da propriedade nos jogos de PS4. `completo` = conferido contra a contagem do serviço (tolerância de 0,5%)."""
    esperado = None
    try:
        c = orc(q_contagem(prop))
        esperado = int(c[0]["n"]["value"]) if c else None
    except (KeyError, IndexError, ValueError, TypeError):
        esperado = None
    linhas, jogos, fim_natural, avisos = [], set(), False, []
    for pag in range(max_paginas):
        rows = orc(q_pagina(prop, tamanho, pag * tamanho))
        novos = 0
        for b in rows:
            q = _qid(_v(b, "g"))
            if q:
                if q not in jogos:
                    novos += 1
                jogos.add(q)
                linhas.append([q, _v(b, "v")])
        if progresso:
            progresso(prop, pag + 1, len(jogos))
        if not rows:
            fim_natural = True
            break
        if esperado is not None and len(jogos) >= esperado:
            fim_natural = True
            break
        if not novos:
            avisos.append(f"{prop}: a página {pag + 1} não trouxe jogo novo")
            break
    else:
        avisos.append(f"{prop}: teto de {max_paginas} páginas")
    if esperado is not None:
        completo = len(jogos) >= int(esperado * TOLERANCIA + 0.999999)
        motivo = "" if completo else f"coletados {len(jogos)} de {esperado} jogos ({100 * len(jogos) / max(esperado, 1):.1f}%)"
    else:
        completo = fim_natural
        motivo = "" if fim_natural else "coleta interrompida sem contagem para validar"
        avisos.append(f"{prop}: contagem do serviço indisponível; coleta {'terminou em página vazia' if fim_natural else 'NÃO validada'}")
    return {"esperado": esperado, "coletados": len(jogos), "completo": completo, "motivoIncompleta": motivo, "paginas": pag + 1, "linhas": linhas, "avisos": avisos}


def _idade_dias(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 86400
    except (ValueError, TypeError):
        return 1e9


def atualizar_cache(cache: dict, orc, props, max_idade_dias: float, forcar: bool, progresso=None) -> tuple[dict, list[str], dict[str, dict]]:
    """Incremental: só consulta propriedades sem cache completo ou mais velhas que max_idade_dias. Devolve (cache novo, avisos, parciais)."""
    novo = json.loads(json.dumps(cache))
    avisos, parciais = [], {}
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rot = None
    for p in props:
        ent = novo["propriedades"].get(p)
        if ent and ent.get("completo") and not forcar and _idade_dias(ent.get("consultadoEm", "")) < max_idade_dias:
            avisos.append(f"{p}: cache completo de {ent['consultadoEm'][:10]} reaproveitado (sem consulta)")
            continue
        try:
            if rot is None:
                rot = rotulos(orc, props)
            col = coletar_propriedade(orc, p, progresso=progresso)
        except LimiteDeRequisicoes as e:
            avisos.append(f"{p}: {e}; propriedade NÃO atualizada")
            parciais[p] = {"completo": False, "motivoIncompleta": str(e), "linhas": []}
            continue
        avisos += col["avisos"]
        entrada = {"rotulo": (rot or {}).get(p, ""), "consultadoEm": agora, **{k: col[k] for k in ("esperado", "coletados", "completo", "motivoIncompleta", "paginas", "linhas")}}
        if col["completo"]:
            novo["propriedades"][p] = entrada                          # só coleta completa substitui o cache
        else:
            parciais[p] = entrada
    return novo, avisos, parciais


def linhas_do_cache(cache: dict, props) -> dict[str, dict]:
    return {p: cache["propriedades"][p] for p in props if p in cache["propriedades"] and cache["propriedades"][p].get("completo")}


# ---------- amostra / sondagem (não gravam nada) ----------
def resolver_nomes(indice: dict, termos: list[str], por_termo: int = 30) -> dict[str, list[tuple[str, str]]]:
    """Nomes -> (qid, nome) do ÍNDICE. Só escolhe QUAIS Q-ids consultar; o CUSA vem das afirmações do Wikidata sobre esses Q-ids."""
    out: dict[str, list[tuple[str, str]]] = {}
    for t in termos:
        achados = []
        for r in busca.buscar(indice, t, limite=por_termo):
            i = str(r.get("idFonte", ""))
            if i.startswith("wikidata:"):
                achados.append((i.split(":", 1)[1], r["nome"]))
        out[t] = achados
    return out


def amostra(orc, indice: dict, termos: list[str], props) -> dict:
    por_termo = resolver_nomes(indice, termos)
    qids = list(dict.fromkeys(q for v in por_termo.values() for q, _ in v))
    rot = rotulos(orc, props)
    linhas: dict[str, dict] = {p: {"rotulo": rot.get(p, ""), "consultadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"), "linhas": []} for p in props}
    for i in range(0, len(qids), LOTE_QIDS):
        for b in orc(q_amostra(qids[i:i + LOTE_QIDS], props)):
            m = re.search(r"/(P[0-9]+)$", _v(b, "p"))
            q = _qid(_v(b, "g"))
            if m and q and m.group(1) in linhas:
                linhas[m.group(1)]["linhas"].append([q, _v(b, "v")])
    sub = {"titulos": [t for t in indice["titulos"] if str(t.get("idFonte", "")).startswith("wikidata:") and t["idFonte"].split(":", 1)[1] in qids]}
    return {"porTermo": por_termo, "resultado": construir(linhas, sub, None, linhas[props[0]]["consultadoEm"] if props else "")}


def sondar(orc, props, indice: dict) -> dict:
    rot = rotulos(orc, props)
    out = {}
    for p in props:
        n = None
        try:
            c = orc(q_contagem(p))
            n = int(c[0]["n"]["value"]) if c else None
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        ex = [(_qid(_v(b, "g")), _v(b, "v")) for b in orc(q_exemplos(p, 20))]
        classe: dict[str, int] = {}
        for _, v in ex:
            cusa, _, motivo = extrair(v)
            k = "CUSA/Content ID válido" if cusa else motivo
            classe[k] = classe.get(k, 0) + 1
        out[p] = {"rotulo": rot.get(p, ""), "jogosComAPropriedade": n, "exemplos": ex[:8], "classificacaoDosExemplos": classe}
    return out


def main(argv=None, fetch=None, dormir=None) -> int:
    import time
    dormir = dormir or time.sleep
    ap = argparse.ArgumentParser(prog="python -m ps4store.cusas", description="CUSAs alegados no Wikidata para os jogos do índice (importação incremental)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sondar", action="store_true", help="1º passo: rótulos das propriedades, contagens e exemplos de valores (poucas consultas; não grava)")
    g.add_argument("--amostra", metavar="NOMES", help="teste com poucos jogos, ex.: \"batman,gta v,cyberpunk\" (não grava)")
    g.add_argument("--atualizar", action="store_true", help="importa todas as propriedades (incremental, com cache) e grava o resultado")
    g.add_argument("--offline", action="store_true", help="reconstrói o resultado só do cache, sem rede")
    g.add_argument("--conflitos", action="store_true", help="lista os conflitos para revisão")
    ap.add_argument("--propriedades", default=",".join(PROPS_PADRAO))
    ap.add_argument("--cache", default=CACHE_PADRAO)
    ap.add_argument("--dados", default=DADOS_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--user-agent", default=os.environ.get("WIKIDATA_USER_AGENT", wikidata.UA_PADRAO))
    ap.add_argument("--max-requisicoes", type=int, default=MAX_REQ_PADRAO)
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--max-idade-dias", type=float, default=30.0)
    ap.add_argument("--forcar", action="store_true", help="ignora o cache e consulta de novo")
    ap.add_argument("--aceitar-parcial", action="store_true")
    a = ap.parse_args(argv)
    if not any((a.sondar, a.amostra, a.atualizar, a.offline, a.conflitos)):
        ap.error("use --sondar, --amostra, --atualizar, --offline ou --conflitos")
    try:
        props = tuple(dict.fromkeys(_prop(p.strip()) for p in a.propriedades.split(",") if p.strip()))
        indice = busca.carregar_indice(a.indice)
        curados = versoes.carregar(a.versoes)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if a.conflitos:
        d = carregar_dados(a.dados)
        for c in d.get("conflitos", []):
            print(f"{c['cusa']}: {c['motivo']} · Q-ids {', '.join(c['qids'])} · {'; '.join(c['jogos'])}")
        print(f"{len(d.get('conflitos', []))} conflito(s) para revisão (nenhum foi associado)")
        return 0
    if not indice.get("titulos") and not a.sondar:
        print("ERRO  índice de busca vazio: gere-o antes (python -m ps4store.wikidata --atualizar)", file=sys.stderr)
        return 2
    f = fetch or (lambda u: wikidata.fetch_http(u, a.user_agent))
    if (a.sondar or a.amostra or a.atualizar) and a.user_agent == wikidata.UA_PADRAO:
        print("AVISO  User-Agent genérico: defina WIKIDATA_USER_AGENT com um contato (o Wikimedia pede).", file=sys.stderr)
    orc = Orcamento(f, max(1, a.max_requisicoes), max(0.0, a.pausa), dormir)
    try:
        if a.sondar:
            for p, d in sondar(orc, props, indice).items():
                print(f"{p} · rótulo no Wikidata: {d['rotulo'] or '(não obtido)'} · jogos de PS4 com a propriedade: "
                      f"{d['jogosComAPropriedade'] if d['jogosComAPropriedade'] is not None else 'contagem indisponível'}")
                print(f"   classificação dos exemplos: {d['classificacaoDosExemplos']}")
                for q, v in d["exemplos"]:
                    print(f"   {q}: {v[:70]}")
            print("Nada foi gravado. Para ver a cobertura real nos seus jogos: --atualizar. Requisições usadas:", orc.usadas)
            return 0
        if a.amostra:
            termos = [t.strip() for t in a.amostra.split(",") if t.strip()]
            r = amostra(orc, indice, termos, props)
            res = r["resultado"]
            for t, achados in r["porTermo"].items():
                print(f'"{t}": {len(achados)} jogo(s) no índice' + ("" if achados else " (o índice só tem os rótulos en/pt do Wikidata, não apelidos como \"GTA\": tente o nome completo)"))
                for q, n in achados:
                    cs = sorted({x["cusa"] for x in res["registros"] if x["qid"] == q})
                    print(f"   {n} [{q}] → " + (", ".join(cs) if cs else "sem CUSA no Wikidata (propriedades consultadas)"))
            e = res["estatisticas"]
            print(f"{e['registros']} registro(s), {e['cusasDistintos']} CUSA(s) distinto(s), {e['conflitos']} conflito(s); rejeitados: {e['rejeitados'] or 'nenhum'}")
            print("Nada foi gravado. Valores do Wikidata são ALEGADOS, não verificados em fonte oficial. Requisições usadas:", orc.usadas)
            return 0
        if a.atualizar:
            cache = carregar_cache(a.cache)
            novo, avisos, parciais = atualizar_cache(cache, orc, props, a.max_idade_dias, a.forcar,
                                                    progresso=lambda p, pg, n: print(f"  {p}: página {pg}, {n} jogos distintos", file=sys.stderr))
            for av in avisos:
                print(f"AVISO  {av}", file=sys.stderr)
            if parciais and not a.aceitar_parcial:
                _gravar({"schema": SCHEMA_CACHE, "propriedades": parciais}, str(Path(a.cache).with_suffix(".parcial.json")))
                if novo != cache:
                    _gravar(novo, a.cache)                                # o que estava completo continua valendo; o parcial não substitui nada
                print("ERRO  importação INCOMPLETA: " + "; ".join(f"{p}: {d.get('motivoIncompleta')}" for p, d in parciais.items()) +
                      f".\n      O resultado atual ({a.dados}) NÃO foi alterado. Use --aceitar-parcial para importar mesmo assim.", file=sys.stderr)
                return 1
            if parciais:
                novo["propriedades"].update({p: d for p, d in parciais.items() if d.get("linhas")})
            _gravar(novo, a.cache)
            cache = novo
        else:
            cache = carregar_cache(a.cache)
    except LimiteDeRequisicoes as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
        print(f"ERRO  {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1
    dados_cache = {p: d for p, d in cache["propriedades"].items() if p in props}
    if not dados_cache:
        print(f"ERRO  cache vazio ({a.cache}): rode --atualizar com internet", file=sys.stderr)
        return 2
    incompletas = [p for p, d in dados_cache.items() if not d.get("completo")]
    if incompletas and not a.aceitar_parcial:
        print(f"ERRO  cache incompleto para {', '.join(incompletas)}: use --atualizar ou --aceitar-parcial", file=sys.stderr)
        return 1
    ref = max((d.get("consultadoEm", "") for d in dados_cache.values()), default="")
    res = construir(dados_cache, indice, curados, ref[:10] or "")
    if incompletas:
        res["parcial"] = True
    _gravar(res, a.dados)
    e = res["estatisticas"]
    print(f"Wikidata (CC0-1.0), consultado em {ref[:10] or '?'}: {e['jogosNoIndice']} jogos no índice · {e['jogosComValor']} com valor nas propriedades · "
          f"{e['jogosComCusa']} com CUSA válido ({100 * e['jogosComCusa'] / max(e['jogosNoIndice'], 1):.1f}%) · {e['jogosSemCusa']} sem CUSA")
    print(f"{e['registros']} registro(s), {e['cusasDistintos']} CUSA(s) distinto(s), {e['conflitos']} conflito(s) para revisão · rejeitados: {e['rejeitados'] or 'nenhum'}")
    for p, d in e["porPropriedade"].items():
        print(f"  {p} ({d['rotulo'] or 'rótulo não obtido'}): {d['linhas']} linha(s), {d['jogosNoIndice']} jogo(s) do índice, {d['comCusaValido']} com CUSA/Content ID válido")
    print("Valores do Wikidata são ALEGADOS (não verificados em fonte oficial). Os registros curados da 5B não foram alterados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
