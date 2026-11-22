"""WIKIDATA: importa METADADOS de jogos de PlayStation 4 (nome, identificador Q, páginas de referência) para o índice de busca (busca.py).

Só metadados CC0: nenhum link de download, nenhuma afirmação de que existe PKG. Independente (stdlib, Python >= 3.11, serve no Termux).
Atualização: consulta paginada ao Wikidata Query Service (https://query.wikidata.org/sparql, host fixo, HTTPS), guarda a resposta bruta em
local/wikidata-ps4.json (offline) e reconstrói a fonte 'wikidata' do índice. Sem rede, o índice e o cache continuam funcionando.
Campos ausentes ficam ausentes: item sem rótulo en/pt é descartado e contado; sem Wikipedia, a página de referência é a do próprio Wikidata.

Convenções do serviço (documentação pública do Wikimedia; NÃO verificadas daqui, sem acesso à rede): User-Agent identificável com contato,
poucas requisições, respeitar 429/Retry-After. Por isso o User-Agent é seu: --user-agent ou WIKIDATA_USER_AGENT ("App/1.0 (seu contato)").
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import busca

ENDPOINT = "https://query.wikidata.org/sparql"
Q_PLAYSTATION_4, Q_VIDEO_GAME = "Q5014725", "Q7889"          # entidades públicas do Wikidata (conferir no 1º uso: o relatório mostra a contagem)
CACHE_PADRAO = "local/wikidata-ps4.json"
UA_PADRAO = "game-metadata-importer/0.1 (python-urllib; defina WIKIDATA_USER_AGENT com seu contato)"
MAX_RESPOSTA = 30 * 1024 * 1024
_ENT = re.compile(r"^https?://www\.wikidata\.org/entity/(Q\d+)$")
_WIKI = re.compile(r"^https://(en|pt)\.wikipedia\.org/wiki/\S+$")


def consulta(limite: int, deslocamento: int) -> str:
    """Uma página de jogos de PS4: a subconsulta é DISTINCT e ordenada por ?g, então LIMIT/OFFSET contam JOGOS (Q-ids), não linhas repetidas.
    (Sem DISTINCT, o mesmo jogo aparece por mais de um caminho de classe e a página traz menos de LIMIT jogos distintos.)"""
    return f"""SELECT ?g ?label_en ?label_pt ?enwiki ?ptwiki (MIN(?d) AS ?data) WHERE {{
  {{ SELECT DISTINCT ?g WHERE {{ ?g wdt:P31/wdt:P279* wd:{Q_VIDEO_GAME} ; wdt:P400 wd:{Q_PLAYSTATION_4} . }} ORDER BY ?g LIMIT {int(limite)} OFFSET {int(deslocamento)} }}
  OPTIONAL {{ ?g rdfs:label ?label_en . FILTER(LANG(?label_en) = "en") }}
  OPTIONAL {{ ?g rdfs:label ?label_pt . FILTER(LANG(?label_pt) = "pt") }}
  OPTIONAL {{ ?enwiki schema:about ?g ; schema:isPartOf <https://en.wikipedia.org/> . }}
  OPTIONAL {{ ?ptwiki schema:about ?g ; schema:isPartOf <https://pt.wikipedia.org/> . }}
  OPTIONAL {{ ?g wdt:P577 ?d . }}
}} GROUP BY ?g ?label_en ?label_pt ?enwiki ?ptwiki ORDER BY ?g"""


def _literal(termo: str) -> str:
    """Termo livre -> texto seguro para literal SPARQL: só letras, dígitos, espaço e pontuação simples; sem aspas nem barra invertida."""
    t = re.sub(r"[^\w\s:'\-.&!]", " ", str(termo), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip().casefold()[:60]


def consulta_contagem() -> str:
    return f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ ?g wdt:P31/wdt:P279* wd:{Q_VIDEO_GAME} ; wdt:P400 wd:{Q_PLAYSTATION_4} . }}"


def consulta_nome(termo: str, limite: int = 100) -> str:
    """Jogos de PS4 cujo rótulo en/pt contém o termo (teste rápido: não serve para importar tudo). Mesmas colunas de consulta()."""
    t = _literal(termo)
    return f"""SELECT ?g ?label_en ?label_pt ?enwiki ?ptwiki (MIN(?d) AS ?data) WHERE {{
  {{ SELECT DISTINCT ?g WHERE {{ ?g wdt:P31/wdt:P279* wd:{Q_VIDEO_GAME} ; wdt:P400 wd:{Q_PLAYSTATION_4} ; rdfs:label ?l .
      FILTER(LANG(?l) IN ("en", "pt") && CONTAINS(LCASE(?l), "{t}")) }} LIMIT {int(limite)} }}
  OPTIONAL {{ ?g rdfs:label ?label_en . FILTER(LANG(?label_en) = "en") }}
  OPTIONAL {{ ?g rdfs:label ?label_pt . FILTER(LANG(?label_pt) = "pt") }}
  OPTIONAL {{ ?enwiki schema:about ?g ; schema:isPartOf <https://en.wikipedia.org/> . }}
  OPTIONAL {{ ?ptwiki schema:about ?g ; schema:isPartOf <https://pt.wikipedia.org/> . }}
  OPTIONAL {{ ?g wdt:P577 ?d . }}
}} GROUP BY ?g ?label_en ?label_pt ?enwiki ?ptwiki ORDER BY ?g"""


def url_consulta(q: str) -> str:
    return ENDPOINT + "?format=json&query=" + urllib.parse.quote(q)


def testar(fetch, termo: str = "batman") -> dict:
    """Teste de conexão SEM gravar nada: conta os jogos de PS4 e lista os que contêm o termo. Devolve só o que o serviço respondeu."""
    n = contar(fetch)
    bind = json.loads(fetch(url_consulta(consulta_nome(termo))))["results"]["bindings"]
    itens, est = para_itens(bind)
    return {"total": n, "termo": termo, "itens": itens, "estatisticas": est}


def url_pagina(limite: int, deslocamento: int) -> str:
    return ENDPOINT + "?format=json&query=" + urllib.parse.quote(consulta(limite, deslocamento))


def fetch_http(url: str, user_agent: str, timeout: int = 90, tentativas: int = 3, dormir=time.sleep) -> bytes:
    """GET HTTPS só no host do Wikidata Query Service; tenta de novo em 429/5xx respeitando Retry-After; resposta limitada a 30 MiB."""
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != "query.wikidata.org":
        raise ValueError("só https://query.wikidata.org é permitido")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/sparql-results+json"})
    for n in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                corpo = r.read(MAX_RESPOSTA + 1)
            if len(corpo) > MAX_RESPOSTA:
                raise ValueError("resposta maior que 30 MiB")
            return corpo
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and n < tentativas:
                espera = int(e.headers.get("Retry-After", "") or 0) if str(e.headers.get("Retry-After", "")).isdigit() else 5 * n
                dormir(min(max(espera, 1), 120))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if n < tentativas:
                dormir(5 * n)
                continue
            raise
    raise RuntimeError("inalcançável")


@dataclass
class Coleta:
    linhas: list = field(default_factory=list)
    qids: set = field(default_factory=set)
    paginas: int = 0
    esperado: int | None = None        # contagem de jogos de PS4 informada pelo serviço (None = não obtida)
    completa: bool = False
    validada: bool = False             # True = conferida contra a contagem do serviço
    avisos: list = field(default_factory=list)
    motivo: str = ""                   # por que NÃO é completa


TOLERANCIA = 0.995                     # diferença aceita entre a contagem e o coletado (edições do Wikidata entre as consultas)


def contar(fetch) -> int | None:
    """Contagem de jogos de PS4 segundo o serviço (None se a consulta falhar ou vier em formato inesperado)."""
    try:
        c = json.loads(fetch(url_consulta(consulta_contagem())))["results"]["bindings"]
        return int(c[0]["n"]["value"]) if c else None
    except (KeyError, IndexError, ValueError, TypeError, OSError, urllib.error.URLError):
        return None


def _qids(linhas: list[dict]) -> set[str]:
    out = set()
    for b in linhas:
        m = _ENT.match(_val(b, "g"))
        if m:
            out.add(m.group(1))
    return out


def baixar_tudo(fetch, tamanho: int = 1000, max_paginas: int = 40, pausa: float = 1.0, dormir=time.sleep, progresso=None,
                esperado: int | None = None) -> Coleta:
    """Coleta por páginas de JOGOS DISTINTOS. Uma página curta NÃO encerra a coleta: só terminam (a) página vazia, (b) Q-ids coletados >= contagem
    do serviço, (c) página sem nenhum Q-id novo (travada) ou (d) teto de páginas. Depois confere o total contra a contagem (`esperado`)."""
    c = Coleta(esperado=esperado)
    fim_natural = False
    for pag in range(max_paginas):
        linhas = json.loads(fetch(url_pagina(tamanho, pag * tamanho)))["results"]["bindings"]
        c.paginas += 1
        qs = _qids(linhas)
        novos = qs - c.qids
        c.linhas += linhas
        c.qids |= qs
        if progresso:
            progresso(c.paginas, len(c.qids))
        if not linhas:
            fim_natural = True
            break
        if esperado is not None and len(c.qids) >= esperado:
            fim_natural = True
            break
        if not novos:
            c.avisos.append(f"a página {c.paginas} não trouxe nenhum jogo novo: coleta interrompida")
            break
        dormir(pausa)
    else:
        c.avisos.append(f"parou no teto de {max_paginas} páginas: pode haver mais jogos; aumente --max-paginas")
    coletados = len(c.qids)
    if esperado is not None:
        minimo = int(esperado * TOLERANCIA + 0.999999)                       # teto de esperado*0,995
        c.validada = True
        c.completa = coletados >= minimo
        if not c.completa:
            c.motivo = f"coletados {coletados} de {esperado} jogos ({100 * coletados / max(esperado, 1):.1f}%)"
        elif coletados < esperado:
            c.avisos.append(f"{esperado - coletados} jogo(s) a menos que a contagem do serviço (dentro da tolerância de {100 * (1 - TOLERANCIA):.1f}%)")
    else:
        c.completa = fim_natural
        c.avisos.append("contagem do serviço indisponível: a coleta NÃO pôde ser conferida (só se sabe que terminou com página vazia)" if fim_natural
                        else "contagem do serviço indisponível e a coleta não terminou normalmente")
        if not fim_natural:
            c.motivo = "coleta interrompida sem contagem para validar"
    return c


def _val(b: dict, k: str) -> str:
    v = b.get(k)
    return v["value"].strip() if isinstance(v, dict) and isinstance(v.get("value"), str) else ""


def para_itens(bindings: list[dict]) -> tuple[list[dict], dict]:
    """Junta as linhas por item Q e monta registros para busca.importar. Nada é inventado: sem rótulo en/pt o item é descartado."""
    por_q: dict[str, dict] = {}
    for b in bindings:
        m = _ENT.match(_val(b, "g"))
        if not m:
            continue
        q = m.group(1)
        it = por_q.setdefault(q, {"q": q, "en": "", "pt": "", "enwiki": "", "ptwiki": "", "ano": ""})
        for k_in, k_out in (("label_en", "en"), ("label_pt", "pt")):
            if _val(b, k_in) and not it[k_out]:
                it[k_out] = _val(b, k_in)
        for k in ("enwiki", "ptwiki"):
            u = _val(b, k)
            if _WIKI.match(u) and not it[k]:
                it[k] = u
        ano = re.match(r"^(-?\d{4})-", _val(b, "data"))
        if ano and ano.group(1).isdigit() and not it["ano"]:
            it["ano"] = ano.group(1)
    itens, sem_rotulo = [], 0
    for q, it in sorted(por_q.items(), key=lambda kv: int(kv[0][1:])):
        nome = it["en"] or it["pt"]
        if not nome:
            sem_rotulo += 1
            continue
        refs = {"wikidata": f"https://www.wikidata.org/wiki/{q}"}
        if it["enwiki"]:
            refs["wikipedia-en"] = it["enwiki"]
        if it["ptwiki"]:
            refs["wikipedia-pt"] = it["ptwiki"]
        rec = {"nome": nome, "url": it["enwiki"] or it["ptwiki"] or refs["wikidata"], "idFonte": f"wikidata:{q}", "referencias": refs}
        outro = it["pt"] if it["en"] and it["pt"] and it["pt"].casefold() != it["en"].casefold() else ""
        if outro:
            rec["aliases"] = [outro]
        if it["ano"]:
            rec["lancamento"] = it["ano"]
        itens.append(rec)
    est = {"itensWikidata": len(por_q), "importaveis": len(itens), "semRotulo": sem_rotulo,
           "comWikipedia": sum(1 for r in itens if len(r["referencias"]) > 1), "comAno": sum(1 for r in itens if "lancamento" in r)}
    return itens, est


def salvar_cache(bindings: list[dict], caminho: str, coleta: Coleta | None = None) -> None:
    doc = {"origem": ENDPOINT, "licenca": "CC0-1.0", "obtidoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "plataforma": Q_PLAYSTATION_4, "classe": Q_VIDEO_GAME, "linhas": bindings}
    if coleta is not None:
        doc.update({"completa": coleta.completa, "validada": coleta.validada, "esperados": coleta.esperado, "coletados": len(coleta.qids),
                    "motivoIncompleta": coleta.motivo})
    _gravar(doc, caminho)


def _gravar(doc: dict, caminho: str) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def carregar_cache(caminho: str) -> dict:
    doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if not isinstance(doc.get("linhas"), list):
        raise ValueError(f"{caminho} não é um cache do importador")
    return doc


def montar_indice(cache: dict, indice_caminho: str, fontes_caminho: str = busca.FONTES_PADRAO) -> dict:
    itens, est = para_itens(cache["linhas"])
    doc = busca.carregar_indice(indice_caminho)
    meta = {"obtidoEm": cache.get("obtidoEm", ""), "consulta": f"P31/P279* {Q_VIDEO_GAME} + P400 {Q_PLAYSTATION_4}"}
    if cache.get("completa") is False:
        meta.update({"parcial": True, "coletados": cache.get("coletados"), "esperados": cache.get("esperados"), "motivoIncompleta": cache.get("motivoIncompleta", "")})
    rep = busca.importar(doc, busca.carregar_fontes(fontes_caminho), "wikidata", itens, meta=meta)
    busca.salvar_indice(doc, indice_caminho)
    return {**est, **rep}


def main(argv=None, fetch=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.wikidata", description="importa metadados CC0 de jogos de PS4 do Wikidata para o índice de busca")
    ap.add_argument("--atualizar", action="store_true", help="consulta o Wikidata (precisa de internet) e reconstrói o índice")
    ap.add_argument("--offline", action="store_true", help="reconstrói o índice só a partir do cache local (sem rede)")
    ap.add_argument("--testar", nargs="?", const="batman", metavar="TERMO", help="teste rápido de conexão (2 consultas pequenas, não grava nada): conta jogos de PS4 e lista os que contêm TERMO (padrão: batman)")
    ap.add_argument("--cache", default=CACHE_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--fontes", default=busca.FONTES_PADRAO)
    ap.add_argument("--user-agent", default=os.environ.get("WIKIDATA_USER_AGENT", UA_PADRAO))
    ap.add_argument("--tamanho", type=int, default=1000, help="itens por página (padrão 1000)")
    ap.add_argument("--max-paginas", type=int, default=40)
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre páginas")
    ap.add_argument("--aceitar-parcial", action="store_true", help="importa mesmo se a coleta estiver incompleta (o índice fica marcado como PARCIAL)")
    a = ap.parse_args(argv)
    if a.testar is not None:
        if a.atualizar or a.offline:
            print("ERRO  --testar não se combina com --atualizar/--offline", file=sys.stderr)
            return 2
        try:
            r = testar(fetch or (lambda u: fetch_http(u, a.user_agent)), a.testar)
        except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
            print(f"ERRO  {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return 1
        print(f"Wikidata respondeu. Jogos de PS4 no Wikidata (contagem do serviço): {r['total'] if r['total'] is not None else 'não obtida'}")
        print(f"Com \"{r['termo']}\" no nome: {len(r['itens'])} (sem rótulo en/pt: {r['estatisticas']['semRotulo']})")
        for it in r["itens"][:30]:
            print(f"  {it['nome']}" + (f" ({it['lancamento']})" if it.get("lancamento") else "") + f"\n    {it['url']}   [{it['idFonte']}]")
        print("Nada foi gravado. Se a lista parece certa, rode --atualizar. São metadados: não indicam PKG ou download.")
        return 0
    if a.atualizar == a.offline:
        print("ERRO  use --atualizar (rede), --offline (cache local) ou --testar (teste rápido)", file=sys.stderr)
        return 2
    try:
        if a.atualizar:
            if a.user_agent == UA_PADRAO:
                print("AVISO  User-Agent genérico: o Wikimedia pede um identificador com contato (--user-agent ou WIKIDATA_USER_AGENT).", file=sys.stderr)
            f = fetch or (lambda u: fetch_http(u, a.user_agent))
            esperado = contar(f)
            print(f"Contagem do serviço: {esperado if esperado is not None else 'indisponível'} jogos de PS4", file=sys.stderr)
            col = baixar_tudo(f, max(1, min(a.tamanho, 5000)), max(1, a.max_paginas), max(0.0, a.pausa),
                              progresso=lambda p, n: print(f"  página {p}: {n} jogos distintos até agora", file=sys.stderr), esperado=esperado)
            for av in col.avisos:
                print(f"AVISO  {av}", file=sys.stderr)
            if not col.completa and not a.aceitar_parcial:
                parcial = str(Path(a.cache).with_suffix(".parcial.json"))
                salvar_cache(col.linhas, parcial, col)
                print(f"ERRO  importação INCOMPLETA ({col.motivo}). O índice e o cache atuais NÃO foram alterados; a coleta parcial ficou em {parcial}.\n"
                      "      Tente de novo (--atualizar) ou use --aceitar-parcial para importar mesmo assim (o índice ficará marcado como PARCIAL).", file=sys.stderr)
                return 1
            salvar_cache(col.linhas, a.cache, col)
        cache = carregar_cache(a.cache)
        if cache.get("completa") is False and not a.aceitar_parcial:
            print(f"ERRO  o cache está marcado como INCOMPLETO ({cache.get('motivoIncompleta', '?')}); use --atualizar ou --aceitar-parcial.", file=sys.stderr)
            return 1
        if "completa" not in cache:
            print("AVISO  este cache é de uma versão antiga e não diz se a coleta foi completa; rode --atualizar para validar contra a contagem do serviço.", file=sys.stderr)
        rep = montar_indice(cache, a.indice, a.fontes)
    except FileNotFoundError:
        print(f"ERRO  cache não encontrado ({a.cache}): rode --atualizar com internet", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
        print(f"ERRO  {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1
    conf = (f" · conferido: {cache['coletados']} de {cache['esperados']} da contagem do serviço" if cache.get("validada") and cache.get("esperados") else
            " · NÃO conferido contra a contagem do serviço" if cache.get("validada") is False else "")
    if cache.get("completa") is False:
        conf += " · PARCIAL"
    print(f"Wikidata (CC0-1.0), obtido em {cache.get('obtidoEm', '?')}: {rep['itensWikidata']} jogo(s) de PS4 no Wikidata{conf} · "
          f"{rep['importados']} importado(s) no índice · {rep['semRotulo']} sem rótulo en/pt (descartados) · "
          f"{rep['comWikipedia']} com página da Wikipedia · {rep['comAno']} com ano de lançamento · {len(rep['rejeitados'])} rejeitado(s)")
    print("São metadados de jogos: não indicam que exista PKG ou download disponível.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
