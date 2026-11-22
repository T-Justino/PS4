"""BUSCA: pesquisa por nome num índice JSON local de títulos -> URL da página de origem. Independente (stdlib, Python >= 3.11, serve no Termux).

Escopo mínimo: importar um índice de uma FONTE REGISTRADA E AUTORIZADA (config/busca-fontes.json), pesquisar por parte do nome (sem acentos,
sem diferença de maiúsculas, vários resultados) e mostrar nome + URL da página. Não resolve links, não baixa nada, não coleta sites:
a importação lê um arquivo local que você forneceu. Campos opcionais já previstos para filtros futuros: titleId, regiao, idiomas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "ps4store.indice/v1"
INDICE_PADRAO = "local/busca-indice.json"
FONTES_PADRAO = "config/busca-fontes.json"
AUTH_BASES = ("license", "official-developer-release", "written-permission", "test-fixture")
MAX_NOME, MAX_URL, MAX_ITENS = 200, 2048, 200_000
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def norm(texto) -> str:
    """Minúsculas, sem acentos, só letras/dígitos separados por um espaço."""
    t = unicodedata.normalize("NFKD", str(texto or "")).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# ---------- fontes ----------
def carregar_fontes(caminho: str = FONTES_PADRAO) -> dict[str, dict]:
    try:
        doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for f in doc.get("fontes", []):
        fid = f.get("id") or ""
        if re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", fid):
            out[fid] = f
    return out


def fonte_autorizada(fonte: dict | None) -> bool:
    a = (fonte or {}).get("authorization")
    return isinstance(a, dict) and a.get("basis") in AUTH_BASES and bool(a.get("evidence"))


# ---------- índice ----------
def indice_vazio() -> dict:
    return {"schema": SCHEMA, "geradoEm": "", "fontes": {}, "titulos": []}


def carregar_indice(caminho: str = INDICE_PADRAO) -> dict:
    try:
        doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return indice_vazio()
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("titulos"), list):
        raise ValueError(f"{caminho} não é um índice {SCHEMA}")
    return doc


def salvar_indice(doc: dict, caminho: str = INDICE_PADRAO) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ler_itens(caminho: str) -> list[dict]:
    """Itens de um arquivo local: JSON ({"titulos":[...]} ou lista) com nome/url, ou texto 'nome<TAB>url' por linha (vazias e # ignoradas)."""
    texto = Path(caminho).read_text(encoding="utf-8-sig")
    if caminho.lower().endswith(".json"):
        d = json.loads(texto)
        lista = d.get("titulos") if isinstance(d, dict) else d
        if not isinstance(lista, list):
            raise ValueError("JSON deve ser uma lista ou conter 'titulos'")
        return [x for x in lista if isinstance(x, dict)]
    itens = []
    for linha in texto.splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        nome, _, url = linha.partition("\t")
        itens.append({"nome": nome, "url": url})
    return itens


def _valido(item: dict) -> tuple[dict | None, str]:
    nome = re.sub(r"\s+", " ", str(item.get("nome") or item.get("name") or "")).strip()
    url = str(item.get("url") or "").strip()
    if not nome or len(nome) > MAX_NOME or _CTRL.search(nome) or not norm(nome):
        return None, "nome vazio, longo demais ou com caracteres de controle"
    p = urlsplit(url)
    if len(url) > MAX_URL or p.scheme != "https" or not p.hostname or p.username or p.password or re.search(r"\s", url):
        return None, "URL deve ser https simples (sem espaços nem credenciais)"
    rec = {"nome": nome, "url": url}
    if isinstance(item.get("aliases"), list):
        rec["aliases"] = [str(a)[:MAX_NOME] for a in item["aliases"] if str(a).strip()][:10]
    for k in ("titleId", "regiao", "idiomas"):          # opcionais: base para filtros futuros (nenhum é exigido)
        if item.get(k) not in (None, "", []):
            rec[k] = item[k]
    return rec, ""


def importar(doc: dict, fontes: dict[str, dict], fonte_id: str, itens: list[dict]) -> dict:
    """Troca TODOS os títulos da fonte pelos itens dados (atualização controlada). Recusa fonte desconhecida ou sem autorização registrada."""
    f = fontes.get(fonte_id)
    if f is None:
        raise ValueError(f"fonte '{fonte_id}' não está registrada em {FONTES_PADRAO}")
    if not fonte_autorizada(f):
        raise ValueError(f"fonte '{fonte_id}' não tem 'authorization' (basis + evidence) registrada: nada foi importado")
    if len(itens) > MAX_ITENS:
        raise ValueError(f"mais de {MAX_ITENS} itens")
    novos, rejeitados, vistos = [], [], set()
    for i, it in enumerate(itens, 1):
        rec, why = _valido(it)
        if rec is None:
            rejeitados.append({"item": i, "motivo": why})
            continue
        chave = (norm(rec["nome"]), rec["url"])
        if chave in vistos:
            rejeitados.append({"item": i, "motivo": "repetido (mesmo nome e URL)"})
            continue
        vistos.add(chave)
        rec["fonte"] = fonte_id
        novos.append(rec)
    antes = sum(1 for t in doc["titulos"] if t.get("fonte") == fonte_id)
    doc["titulos"] = [t for t in doc["titulos"] if t.get("fonte") != fonte_id] + novos
    doc["fontes"][fonte_id] = {"nome": f.get("nome", fonte_id), "itens": len(novos)}
    from datetime import datetime, timezone
    doc["geradoEm"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"importados": len(novos), "substituidos": antes, "rejeitados": rejeitados}


# ---------- busca ----------
def _rank(q: str, nomes: list[str]) -> int:
    """0 = nome igual · 1 = começa com · 2 = palavra do nome começa com · 3 = contém · 4 = termos soltos no nome."""
    best = 4
    for n in nomes:
        r = 0 if n == q else 1 if n.startswith(q) else 2 if (" " + q) in (" " + n) else 3 if q in n else 4
        best = min(best, r)
    return best


def buscar(doc: dict, termo: str, fonte: str | None = None, limite: int | None = None) -> list[dict]:
    """Todos os títulos cujo nome (ou alias) contém TODOS os termos, em qualquer ordem. Nomes repetidos em fontes/URLs diferentes são mantidos."""
    q = norm(termo)
    if not q:
        return []
    termos = q.split()
    out = []
    for t in doc.get("titulos", []):
        if fonte and t.get("fonte") != fonte:
            continue
        nomes = [norm(t.get("nome"))] + [norm(a) for a in t.get("aliases", [])]
        if any(all(w in n for w in termos) for n in nomes):
            out.append((_rank(q, nomes), norm(t.get("nome")), t.get("fonte", ""), t.get("url", ""), t))
    out.sort(key=lambda x: x[:4])
    res = [dict(x[4], rank=x[0]) for x in out]
    return res[:limite] if limite else res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.busca", description="pesquisa jogos por nome num índice local (nome + URL da página)")
    ap.add_argument("termo", nargs="*", help="parte do nome (sem filtros obrigatórios)")
    ap.add_argument("--indice", default=INDICE_PADRAO)
    ap.add_argument("--fontes", default=FONTES_PADRAO)
    ap.add_argument("--fonte", help="limita a pesquisa a uma fonte; com --importar, a fonte do arquivo")
    ap.add_argument("--importar", metavar="ARQUIVO", help="importa/atualiza o índice a partir de um arquivo local (.json ou texto 'nome<TAB>url')")
    ap.add_argument("--limite", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.importar:
            if not a.fonte:
                print("ERRO  --importar exige --fonte ID (fonte registrada e autorizada)", file=sys.stderr)
                return 2
            doc = carregar_indice(a.indice)
            rep = importar(doc, carregar_fontes(a.fontes), a.fonte, ler_itens(a.importar))
            salvar_indice(doc, a.indice)
            print(f"Importados {rep['importados']} título(s) da fonte '{a.fonte}' (substituiu {rep['substituidos']}); rejeitados: {len(rep['rejeitados'])}")
            for r in rep["rejeitados"][:10]:
                print(f"  item {r['item']}: {r['motivo']}")
            return 0
        if not " ".join(a.termo).strip():
            print("ERRO  informe parte do nome, ex.: python -m ps4store.busca Batman", file=sys.stderr)
            return 2
        doc = carregar_indice(a.indice)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2
    if not doc["titulos"]:
        print(f"Índice vazio ou inexistente ({a.indice}). Importe um: --importar ARQUIVO --fonte ID", file=sys.stderr)
        return 3
    termo = " ".join(a.termo)
    res = buscar(doc, termo, a.fonte, max(1, a.limite))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res else 1
    if not res:
        print(f'Nenhum título encontrado para "{termo}" ({len(doc["titulos"])} no índice).')
        return 1
    total = len(buscar(doc, termo, a.fonte))
    print(f'{total} resultado(s) para "{termo}"' + (f" (mostrando {len(res)})" if total > len(res) else "") + ":")
    for i, t in enumerate(res, 1):
        teste = " [TESTE]" if t.get("fonte", "").startswith("teste") else ""
        print(f"{i}. {t['nome']}{teste}\n   {t['url']}   [fonte: {t.get('fonte', '?')}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
