"""DESCOBERTA DE LINKS (por jogo): consulta as fontes de config/fontes-links.json pelo CUSA, Content ID e nome EXATO do jogo e devolve candidatos
(página de download, PKG direto, RAR...). Reaproveita os conectores de discover.py (catálogo público do PKG-Zone, API de releases/contents do GitHub).

Regras: só fontes cadastradas (sem buscador genérico nem raspagem); não inventa URL (só o que a fonte publica); não baixa nada (a análise dos bytes e o
bloco para o SSPI ficam com analise_link.py, quando o usuário toca em "Analisar e preparar"); fonte sem autorização registrada aparece como
"link externo não verificado". Correspondência: CUSA/Content ID = forte; nome exato = só pelo nome (não verificado até ler o PKG).
Cache: catálogos em local/links-cache.json (gravado só pelo comando --atualizar) ou em memória no painel; validade de 24 h.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

from . import busca, cusas, unificada, versoes
from .discover import discover_contents, discover_github, discover_pkgzone
from .links import file_type
from .model import Source
from .net import NetError, UrllibNet

FONTES_PADRAO = "config/fontes-links.json"
CACHE_PADRAO = "local/links-cache.json"
SCHEMA = "ps4store.fontes-links/v1"
VALIDADE_H = 24
CONECTORES = {"pkg-zone-catalog": discover_pkgzone, "github-releases": discover_github, "github-contents": discover_contents}
CUSA_TXT = re.compile(r"CUSA\d{5}", re.I)
CID_TXT = re.compile(r"[A-Z]{2}\d{4}-[A-Z]{4}\d{5}_\d{2}-[A-Z0-9]{16}", re.I)


def carregar_fontes(caminho: str = FONTES_PADRAO) -> list[dict]:
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"{caminho}: não é {SCHEMA}")
    out = []
    for f in d.get("fontes", []):
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", str(f.get("id", ""))) or f.get("tipo") not in CONECTORES:
            raise ValueError(f"{caminho}: fonte inválida {f.get('id')!r} (tipos: {', '.join(CONECTORES)})")
        if f["tipo"] == "pkg-zone-catalog" and not re.match(r"^https://[a-z0-9.-]+$", f.get("base_url", "")):
            raise ValueError(f"{caminho}: {f['id']}: base_url https obrigatória")
        if f["tipo"] != "pkg-zone-catalog" and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", f.get("repo", "")):
            raise ValueError(f"{caminho}: {f['id']}: repo dono/nome obrigatório")
        out.append(f)
    return out


def _source(f: dict) -> Source:
    nomes = {x.name for x in fields(Source)}
    kw = dict(id=f["id"], type=f["tipo"], repo=f.get("repo", ""), enabled=True, include_prereleases=False, max_releases=int(f.get("max_releases", 5)),
              auth_basis="", auth_evidence="", base_url=f.get("base_url", ""), path=f.get("path", ""), all_types=True, include_inactive=False)
    return Source(**{k: v for k, v in kw.items() if k in nomes})


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def catalogo(f: dict, net, cache: dict, forcar: bool = False) -> tuple[list[dict], str]:
    """Itens da fonte (do cache se tiver < 24 h). Devolve (itens, origem: 'cache' | 'rede' | 'erro: ...')."""
    c = cache.get(f["id"])
    if c and not forcar:
        try:
            if (_agora() - datetime.fromisoformat(c["em"])).total_seconds() < VALIDADE_H * 3600:
                return c["itens"], "cache"
        except (KeyError, ValueError):
            pass
    try:
        achados = CONECTORES[f["tipo"]](_source(f), net)
    except (NetError, ValueError, OSError, KeyError, TypeError) as e:
        if c:
            return c["itens"], f"cache antigo (rede falhou: {str(e)[:80]})"
        return [], f"erro: {str(e)[:120]}"
    itens = [{"url": x.url, "arquivo": x.asset_name, "nome": x.name_hint or "", "titleId": (x.meta or {}).get("catalogTitleId") or "",
              "versao": x.tag, "tamanho": x.size, "pagina": x.release_url, "data": x.published_at, "ignorar": x.skip_reason} for x in achados]
    cache[f["id"]] = {"em": _agora().isoformat(timespec="seconds"), "itens": itens}
    return itens, "rede"


def _tipo(nome: str) -> str:
    n = (nome or "").lower()
    if re.search(r"patch|update|\bupd\b|-a0[1-9]\d\d-v0\d00", n):
        return "atualização (pelo nome)"
    if re.search(r"\bdlc\b|addon|add-on", n):
        return "DLC (pelo nome)"
    return "desconhecido até ler o PKG"


def casar(item: dict, jogo: dict, f: dict) -> dict | None:
    """Como o item corresponde ao jogo (ou None). Nunca por semelhança: CUSA/Content ID iguais ou nome normalizado IDÊNTICO."""
    campos = f.get("campos", [])
    texto = f"{item['arquivo']} {item['url']}"
    cids = {c.upper() for c in jogo.get("contentIds", [])}
    cusas_j = {c.upper() for c in jogo.get("cusas", [])}
    if "arquivo" in campos or "titleId" in campos:
        cid = CID_TXT.search(texto)
        if cid and cid.group(0).upper() in cids:
            return {"como": "contentId", "texto": f"Content ID {cid.group(0).upper()} no nome do arquivo", "forte": True}
        if item.get("titleId", "").upper() in cusas_j:
            return {"como": "cusa", "texto": f"ID do catálogo = {item['titleId']} (CUSA do jogo)", "forte": True}
        c = CUSA_TXT.search(texto)
        if c and c.group(0).upper() in cusas_j:
            return {"como": "cusa", "texto": f"{c.group(0).upper()} no nome do arquivo", "forte": True}
    if "nome" in campos:
        alvo = busca.norm(jogo["nome"])
        nome_item = item.get("nome") or f.get("nomeApp", "")
        if alvo and busca.norm(nome_item) == alvo:
            return {"como": "nome", "texto": f"nome exato no catálogo (\"{nome_item}\"); CUSA ainda não conferido", "forte": False}
    return None


def descobrir(jogo: dict, fontes: list[dict], net, cache: dict, forcar: bool = False) -> dict:
    """jogo = {qid, nome, cusas, contentIds}. Resultado para o painel/CLI."""
    res, est = [], []
    for f in fontes:
        itens, origem = catalogo(f, net, cache, forcar)
        n = 0
        for it in itens:
            if it.get("ignorar"):
                continue
            m = casar(it, jogo, f)
            if not m:
                continue
            n += 1
            fmt = file_type(it["arquivo"])
            res.append({"url": it["url"], "arquivo": it["arquivo"], "origem": f["nome"], "fonteId": f["id"], "pagina": it.get("pagina", ""),
                        "formato": {"pkg": "PKG", "rar": "RAR", "rar-multiparte": "RAR (volume)", "zip": "ZIP", "7z": "7z"}.get(fmt, "página/desconhecido"),
                        "linkDireto": f["tipo"] != "pkg-zone-catalog" and fmt != "desconhecido",
                        "tipo": _tipo(it["arquivo"]), "versao": it.get("versao"), "tamanho": it.get("tamanho"),
                        "autorizado": bool(f.get("autorizacao")), "autorizacao": f.get("autorizacao") or ("não verificada" + (f": {f['nota']}" if f.get("nota") else "")),
                        "correspondencia": m, "verificacao": "não analisado (toque em Analisar para ler o CUSA dos bytes)"})
        est.append({"fonte": f["nome"], "origem": origem, "itens": len(itens), "achados": n})
    res.sort(key=lambda r: (not r["correspondencia"]["forte"], not r["autorizado"], r["arquivo"]))
    return {"jogo": {k: jogo[k] for k in ("qid", "nome")}, "resultados": res[:40], "fontes": est,
            "texto": f"{len(res)} link(s) encontrado(s)" if res else "Nenhum link encontrado nas fontes consultadas"}


def jogo_do_indice(qid: str, indice: dict, curados: dict, wd: dict) -> dict | None:
    t = next((x for x in indice.get("titulos", []) if x.get("idFonte") == f"wikidata:{qid}"), None)
    regs = unificada.registros_do_jogo(qid, curados, wd)
    if not t and not regs:
        return None
    cids = [c for r in regs for c in ([r.get("contentId")] + list(r.get("contentIds") or [])) if c]
    return {"qid": qid, "nome": t["nome"] if t else regs[0]["jogo"], "cusas": sorted({r["cusa"] for r in regs}), "contentIds": sorted(set(cids))}


def carregar_cache(caminho: str = CACHE_PADRAO) -> dict:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar_cache(cache: dict, caminho: str = CACHE_PADRAO) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def main(argv=None, net=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.descoberta_links", description="procura links (PKG/RAR) de um jogo nas fontes cadastradas")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--jogo", metavar="NOME", help="nome do jogo (índice) ou de um app de homebrew (busca direta nas fontes pelo nome exato)")
    g.add_argument("--atualizar", action="store_true", help="baixa os catálogos das fontes para o cache local (1 requisição por fonte)")
    ap.add_argument("--analisar", action="store_true", help="analisa o 1º resultado compatível (lê os bytes) e mostra o bloco para o SSPI")
    ap.add_argument("--fontes", default=FONTES_PADRAO)
    ap.add_argument("--cache", default=CACHE_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--versoes", default=versoes.VERSOES_PADRAO)
    ap.add_argument("--cusas", default=cusas.DADOS_PADRAO)
    a = ap.parse_args(argv)
    try:
        fontes = carregar_fontes(a.fontes)
        indice, cur, wd = busca.carregar_indice(a.indice), versoes.carregar(a.versoes), cusas.carregar_dados(a.cusas)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    net = net or UrllibNet(timeout=30)
    cache = carregar_cache(a.cache)
    if a.atualizar:
        for f in fontes:
            itens, origem = catalogo(f, net, cache, forcar=True)
            print(f"  {f['nome']}: {len(itens)} item(ns) · {origem}")
        salvar_cache(cache, a.cache)
        return 0
    alvo = busca.norm(a.jogo)
    t = next((x for x in indice.get("titulos", []) if busca.norm(x["nome"]) == alvo and str(x.get("idFonte", "")).startswith("wikidata:")), None)
    jogo = jogo_do_indice(t["idFonte"].split(":", 1)[1], indice, cur, wd) if t else {"qid": "", "nome": a.jogo, "cusas": [], "contentIds": []}
    print(f"{jogo['nome']}" + (f" ({jogo['qid']}) · CUSAs conhecidos: {', '.join(jogo['cusas']) or 'nenhum'}" if jogo["qid"] else " (fora do índice: busca pelo nome exato nas fontes)"))
    r = descobrir(jogo, fontes, net, cache)
    salvar_cache(cache, a.cache)
    for e in r["fontes"]:
        print(f"  fonte {e['fonte']}: {e['achados']} de {e['itens']} item(ns) · {e['origem']}")
    print(r["texto"])
    for x in r["resultados"]:
        print(f"  [{x['formato']}] {x['arquivo']} · v{x['versao']} · {x['origem']} · {'AUTORIZADO: ' + x['autorizacao'] if x['autorizado'] else 'link externo, autorização ' + x['autorizacao']}")
        print(f"      {x['url']}\n      correspondência: {x['correspondencia']['texto']}")
    if a.analisar and r["resultados"]:
        from . import analise_link
        x = r["resultados"][0]
        an = analise_link.analisar(x["url"], jogo["qid"], cur, wd)
        print(f"Análise: {an['texto']}")
        for arq in an["arquivos"]:
            i = arq["identificacao"]
            print(f"  {arq.get('arquivo')}: CUSA/ID {i.get('cusa') or i.get('titleId') or '?'} · {i.get('tipo', '?')} · app {i.get('versaoApp') or '?'} · {arq['comparacao']['texto']}")
        for b in (an.get("sspi") or {}).get("blocos", []):
            print(("PRONTO para o SSPI: " if b["pronto"] else "NÃO pronto: ") + b["titulo"] + ("" if b["pronto"] else " · " + "; ".join(b["bloqueio"])))
            if b["pronto"]:
                print("\n".join(b["urls"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
