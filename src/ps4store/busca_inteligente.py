"""BUSCA INTELIGENTE: nome (parcial, sem acentos/pontuação) + apelidos com vínculo explícito + sugestões para pequenos erros de digitação.
Usa busca.py como biblioteca; stdlib (difflib); Termux. NUNCA altera Q-ids nem associações CUSA: só decide QUAIS jogos do índice mostrar.
  1. exatos/parciais (busca.buscar) ... ordenados: nome igual > começa com > palavra > contém;
  2. apelido (data/apelidos.json): o alvo é o nome EXATO de um único Q-id do índice (senão não é aplicado);
  3. se nada casou: SUGESTÕES aproximadas (cada palavra da busca precisa existir no nome, exata ou com similaridade >= 0,8; palavras curtas só exatas;
     no máximo 5 sugestões; rotuladas como aproximadas).
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path

from . import busca

APELIDOS_PADRAO = "data/apelidos.json"
STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "to", "de", "da", "do", "das", "dos", "e", "o", "os", "as", "no", "na", "em"}
SIM_MIN_TOKEN = 0.8        # similaridade mínima por palavra
SIM_MIN_MEDIA = 0.88       # média mínima das palavras da busca
MIN_TOKEN_APROX = 4        # palavras com menos letras só casam exatas
MAX_CANDIDATOS = 300
MAX_SUGESTOES = 5


def carregar_apelidos(caminho: str = APELIDOS_PADRAO) -> list[dict]:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a for a in d.get("apelidos", []) if isinstance(a, dict) and a.get("alvo") and a.get("apelidos")]


def _qid(t: dict) -> str | None:
    i = str(t.get("idFonte", ""))
    return i.split(":", 1)[1] if i.startswith("wikidata:") else None


class Motor:
    """Índices em memória construídos UMA vez por versão do arquivo de índice (6.250 jogos: milissegundos)."""

    def __init__(self, indice: dict, apelidos: list[dict] | None = None):
        self.indice = indice
        self.titulos = indice.get("titulos", [])
        self.nomes = [busca.norm(t.get("nome")) for t in self.titulos]
        self.inv: dict[str, list[int]] = {}
        for i, n in enumerate(self.nomes):
            for tok in set(n.split()):
                self.inv.setdefault(tok, []).append(i)
        self.vocab = sorted(self.inv)
        self.apelidos, self.nao_aplicados = self._resolver(apelidos or [])

    def _resolver(self, lista: list[dict]) -> tuple[dict[str, int], list[str]]:
        por_nome: dict[str, list[int]] = {}
        for i, n in enumerate(self.nomes):
            por_nome.setdefault(n, []).append(i)
        ok: dict[str, int] = {}
        nao: list[str] = []
        for a in lista:
            cand = por_nome.get(busca.norm(a["alvo"]), [])
            if a.get("qid"):
                cand = [i for i in cand if _qid(self.titulos[i]) == a["qid"]]
            qids = {_qid(self.titulos[i]) or f"#{i}" for i in cand}
            if len(qids) != 1:
                nao.append(f"{a['alvo']}: " + ("ausente do índice" if not qids else "nome ambíguo (mais de um Q-id); informe 'qid'"))
                continue
            for ap in a["apelidos"]:
                ok[busca.norm(ap)] = cand[0]
        return ok, nao

    def _sugerir(self, q: str, limite: int) -> list[tuple[float, int]]:
        toks = [t for t in q.split() if t not in STOP]
        if not toks or len(toks) > 8:
            return []
        conjuntos, sims = [], []
        for t in toks:
            cand = {t: 1.0} if t in self.inv else {}
            if len(t) >= MIN_TOKEN_APROX:
                for v in difflib.get_close_matches(t, self.vocab, n=4, cutoff=SIM_MIN_TOKEN):
                    cand.setdefault(v, difflib.SequenceMatcher(None, t, v).ratio())
            if not cand:
                return []                                             # uma palavra sem nenhum candidato próximo: nada evidente
            idxs = set()
            for v in cand:
                idxs.update(self.inv[v])
            conjuntos.append(idxs)
            sims.append(cand)
        comuns = set.intersection(*conjuntos)
        if len(comuns) > MAX_CANDIDATOS:
            comuns = set(sorted(comuns)[:MAX_CANDIDATOS])
        out = []
        for i in comuns:
            nt = set(self.nomes[i].split())
            melhores = [max((s for v, s in cand.items() if v in nt), default=0.0) for cand in sims]
            media = sum(melhores) / len(melhores)
            if min(melhores) >= SIM_MIN_TOKEN and media >= SIM_MIN_MEDIA:
                extra = len(nt) - len(toks)
                out.append((media - 0.01 * max(extra, 0), i))
        out.sort(key=lambda x: (-x[0], self.nomes[x[1]]))
        return out[:limite]

    def buscar(self, termo: str, limite: int = 200) -> dict:
        """{'itens': [título...], 'via': {id(título): 'apelido'}, 'sugestoes': [título...]}. Sugestões só se nada casou."""
        q = busca.norm(termo)
        res = {"itens": [], "via": {}, "sugestoes": [], "avisoApelidos": self.nao_aplicados}
        if not q:
            return res
        itens: list[dict] = []
        if q in self.apelidos:
            t = self.titulos[self.apelidos[q]]
            itens.append(t)
            res["via"][id(t)] = "apelido"
        for t in busca.buscar(self.indice, termo, limite=limite):
            if all(t is not x for x in itens):
                itens.append(t)
        res["itens"] = itens[:limite]
        if not itens:
            res["sugestoes"] = [self.titulos[i] for _, i in self._sugerir(q, MAX_SUGESTOES)]
        return res
