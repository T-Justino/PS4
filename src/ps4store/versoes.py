"""VERSÕES: versões CUSA conhecidas de cada jogo do índice, ligadas pelo Q-id do Wikidata. JSON local, stdlib, Python >= 3.11 (serve no Termux).

Só metadados de versão (CUSA, Content ID, edição, versão, região, idiomas, lojas). Não resolve links, não baixa nada, não indica PKG disponível.
Regras: (1) o vínculo jogo<->CUSA é SEMPRE o Q-id explícito, nunca semelhança de nomes; (2) cada campo não nulo precisa de uma evidência que o afirme
(campo 'afirma'); o que não é sustentado fica desconhecido; (3) a região não determina o idioma: idiomas só entram com evidência própria.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from . import busca

SCHEMA = "ps4store.versoes/v1"
VERSOES_PADRAO = "data/versoes-cusa.json"
CUSA_RE = re.compile(r"^CUSA\d{5}$")
QID_RE = re.compile(r"^Q\d+$")
CONTENT_ID_RE = re.compile(r"^([A-Z]{2})\d{4}-(CUSA\d{5})_\d{2}-[A-Z0-9]{16}$")
CAMPOS = ("cusa", "contentId", "edicao", "versao", "regiao", "idiomas")
PREFIXO_REGIAO = {"UP": "US", "EP": "EU", "JP": "JP", "HP": "ASIA", "KP": "KR"}      # convenção dos prefixos de Content ID (só vale com o Content ID evidenciado)
STATUS = ("citado", "confirmado")


def _s(x) -> str:
    return x.strip() if isinstance(x, str) else ""


def validar_registro(r: dict) -> list[str]:
    """Lista de problemas (vazia = válido). Nada é completado ou inferido aqui."""
    e: list[str] = []
    if not QID_RE.match(_s(r.get("qid"))):
        e.append("qid inválido (esperado Q seguido de números)")
    if not CUSA_RE.match(_s(r.get("cusa"))):
        e.append("cusa inválido (esperado CUSA + 5 dígitos)")
    cid = r.get("contentId")
    m = CONTENT_ID_RE.match(cid) if isinstance(cid, str) else None
    if cid is not None and not m:
        e.append("contentId inválido")
    if m and m.group(2) != r.get("cusa"):
        e.append(f"contentId contém {m.group(2)}, diferente do cusa informado")
    if r.get("status", "citado") not in STATUS:
        e.append("status deve ser 'citado' ou 'confirmado'")
    if r.get("status") == "confirmado" and not (isinstance(r.get("confirmacao"), dict) and _s(r["confirmacao"].get("em"))):
        e.append("status 'confirmado' exige confirmacao {por, em, como}")
    ev = r.get("evidencias")
    if not isinstance(ev, list) or not ev:
        return e + ["precisa de ao menos uma evidência"]
    afirmado: set[str] = set()
    for i, x in enumerate(ev, 1):
        u = urlsplit(_s(x.get("url")) if isinstance(x, dict) else "")
        if not isinstance(x, dict) or not _s(x.get("fonte")) or u.scheme != "https" or not u.hostname:
            e.append(f"evidência {i}: exige fonte e url https")
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", _s(x.get("obtidoEm"))):
            e.append(f"evidência {i}: obtidoEm deve ser AAAA-MM-DD")
        af = x.get("afirma")
        if not isinstance(af, list) or not af or any(a not in CAMPOS for a in af):
            e.append(f"evidência {i}: 'afirma' deve listar campos entre {', '.join(CAMPOS)}")
            continue
        afirmado |= set(af)
    for campo in CAMPOS:
        valor = r.get(campo)
        if valor not in (None, "", [], {}) and campo not in afirmado:
            e.append(f"'{campo}' tem valor mas nenhuma evidência o afirma (deixe desconhecido ou cite a fonte)")
    reg = r.get("regiao")
    if reg is not None:
        if not isinstance(reg, dict) or not _s(reg.get("codigo")) or not _s(reg.get("base")):
            e.append("regiao exige {codigo, base}")
        else:
            pre = _s(reg.get("prefixo")).upper()
            if m and pre and pre != m.group(1):
                e.append("regiao.prefixo diferente do prefixo do contentId")
            if pre in PREFIXO_REGIAO and reg["codigo"].upper() != PREFIXO_REGIAO[pre]:
                e.append(f"regiao.codigo deveria ser {PREFIXO_REGIAO[pre]} para o prefixo {pre}")
    ids = r.get("idiomas")
    if ids is not None and (not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip() for i in ids)):
        e.append("idiomas deve ser uma lista de textos (ou null = desconhecido)")
    if ids and not _s(r.get("idiomasBase")):
        e.append("idiomas exige idiomasBase (o que a evidência diz, e o que não diz)")
    return e


def _chave(r: dict) -> tuple:
    return (r.get("qid"), r.get("cusa"), r.get("contentId"))


def validar_doc(doc: dict) -> list[str]:
    e: list[str] = []
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("versoes"), list):
        return [f"não é um arquivo {SCHEMA}"]
    vistos: set = set()
    for i, r in enumerate(doc["versoes"], 1):
        for p in validar_registro(r):
            e.append(f"registro {i} ({r.get('cusa')}): {p}")
        if _chave(r) in vistos:
            e.append(f"registro {i}: repetido (mesmo qid, cusa e contentId)")
        vistos.add(_chave(r))
    return e


def carregar(caminho: str = VERSOES_PADRAO) -> dict:
    try:
        doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": SCHEMA, "versoes": []}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("versoes"), list):
        raise ValueError(f"{caminho} não é um arquivo {SCHEMA}")
    return doc


def salvar(doc: dict, caminho: str = VERSOES_PADRAO) -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def adicionar(doc: dict, rec: dict) -> None:
    """Acrescenta um registro VÁLIDO (com evidência). Recusa repetido; nunca completa campos."""
    rec = {**rec, "status": rec.get("status", "citado")}
    prob = validar_registro(rec)
    if _chave(rec) in {_chave(r) for r in doc["versoes"]}:
        prob.append("já existe um registro com este qid, cusa e contentId")
    if prob:
        raise ValueError("; ".join(prob))
    doc["versoes"].append(rec)


def _norm_regiao(x: str) -> str:
    x = _s(x).upper()
    return PREFIXO_REGIAO.get(x, x)


def consultar(doc: dict, qid: str | None = None, cusa: str | None = None, regiao: str | None = None, idioma: str | None = None) -> tuple[list[dict], int]:
    """Registros que passam nos filtros (todos opcionais; sem filtros = todos). Devolve (registros, omitidos_por_campo_desconhecido).
    Campo desconhecido NÃO casa com filtro (não se presume): conta em 'omitidos'."""
    out, omitidos = [], 0
    for r in doc.get("versoes", []):
        if qid and r.get("qid") != qid:
            continue
        if cusa and r.get("cusa") != cusa.upper():
            continue
        if regiao:
            reg = r.get("regiao")
            if not reg:
                omitidos += 1
                continue
            if _norm_regiao(regiao) not in (_norm_regiao(reg.get("codigo")), _norm_regiao(reg.get("prefixo"))):
                continue
        if idioma:
            ids = r.get("idiomas")
            if not ids:
                omitidos += 1
                continue
            if busca.norm(idioma) not in [busca.norm(i) for i in ids]:
                continue
        out.append(r)
    return out, omitidos


def _vinculo(qid: str, indice: dict | None, jogo: str) -> str:
    if not indice or not indice.get("titulos"):
        return "vínculo Q-id NÃO verificado (sem índice local; rode ps4store.wikidata --atualizar)"
    achados = [t for t in indice["titulos"] if t.get("idFonte") == f"wikidata:{qid}"]
    if not achados:
        return f"ATENÇÃO: o Q-id {qid} NÃO existe no seu índice local: confira o vínculo antes de confiar nestes CUSAs"
    nome = achados[0]["nome"]
    if busca.norm(nome) == busca.norm(jogo):
        return f"vínculo confirmado no índice: {qid} = \"{nome}\""
    return f"ATENÇÃO: o índice diz que {qid} é \"{nome}\", não \"{jogo}\": confira o vínculo"


def linhas_registro(r: dict, evidencias: bool = False) -> list[str]:
    reg = r.get("regiao")
    regiao = f"região {reg['codigo']} (prefixo {reg.get('prefixo', '?')})" if reg else "região desconhecida"
    idiomas = "idiomas: " + (", ".join(r["idiomas"]) if r.get("idiomas") else "desconhecidos")
    out = [f"  {r['cusa']} · {r.get('edicao') or 'edição desconhecida'} · {regiao} · {idiomas} · versão: {r.get('versao') or 'desconhecida'} · status: {r.get('status', 'citado')}"]
    if r.get("contentId"):
        out.append(f"     Content ID {r['contentId']}")
    if r.get("idiomas") and r.get("idiomasBase"):
        out.append(f"     idiomas, base: {r['idiomasBase']}")
    ev = r.get("evidencias", [])
    for x in (ev if evidencias else ev[:1]):
        out.append(f"     fonte: {x['fonte']} {x['url']}")
    if r.get("nota") and evidencias:
        out.append(f"     nota: {r['nota']}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.versoes", description="lista as versões CUSA conhecidas de um jogo (metadados; sem downloads)")
    ap.add_argument("busca", nargs="*", help="nome do jogo, Q-id (Q123) ou CUSA; vazio = todas as versões registradas")
    ap.add_argument("--versoes", default=VERSOES_PADRAO)
    ap.add_argument("--indice", default=busca.INDICE_PADRAO)
    ap.add_argument("--cusa")
    ap.add_argument("--regiao", help="US, EU, JP, ASIA, KR ou o prefixo (UP, EP…)")
    ap.add_argument("--idioma")
    ap.add_argument("--evidencias", action="store_true", help="mostra todas as fontes e notas")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--validar", action="store_true", help="valida o arquivo de versões e confere os Q-ids no índice local")
    ap.add_argument("--confirmar", metavar="CONTENT_ID", help="marca o registro como confirmado (você abriu a página da fonte e conferiu)")
    ap.add_argument("--por", default="usuário", help="quem confirmou (com --confirmar)")
    ap.add_argument("--adicionar", action="store_true", help="acrescenta um registro (exige --qid --jogo --cusa --evidencia-fonte --evidencia-url)")
    for k in ("qid", "jogo", "content-id", "edicao", "versao", "evidencia-fonte", "evidencia-url", "idiomas-base"):
        ap.add_argument(f"--{k}")
    ap.add_argument("--idiomas", help="lista separada por vírgula (exige --idiomas-base)")
    ap.add_argument("--regiao-base", help="como a região foi sustentada (ex.: 'prefixo UP do Content ID')")
    a = ap.parse_args(argv)
    try:
        doc = carregar(a.versoes)
        indice = busca.carregar_indice(a.indice)
    except (OSError, ValueError) as e:
        print(f"ERRO  {e}", file=sys.stderr)
        return 2

    if a.validar:
        erros = validar_doc(doc)
        for e in erros:
            print(f"ERRO  {e}")
        for qid in sorted({r["qid"] for r in doc["versoes"] if r.get("qid")}):
            jogo = next(r["jogo"] for r in doc["versoes"] if r.get("qid") == qid)
            print(f"{qid}: {_vinculo(qid, indice, jogo)}")
        print(f"{len(doc['versoes'])} registro(s); {len(erros)} problema(s)")
        return 1 if erros else 0

    if a.confirmar:
        for r in doc["versoes"]:
            if r.get("contentId") == a.confirmar:
                r["status"] = "confirmado"
                r["confirmacao"] = {"por": a.por, "em": date.today().isoformat(), "como": "página da fonte aberta no navegador e conferida"}
                salvar(doc, a.versoes)
                print(f"{a.confirmar}: marcado como confirmado por {a.por}")
                return 0
        print(f"ERRO  Content ID {a.confirmar} não encontrado", file=sys.stderr)
        return 2

    if a.adicionar:
        falta = [k for k in ("qid", "jogo", "cusa", "evidencia_fonte", "evidencia_url") if not getattr(a, k)]
        if falta:
            print("ERRO  --adicionar exige: " + ", ".join("--" + k.replace("_", "-") for k in falta), file=sys.stderr)
            return 2
        afirma = ["cusa"] + [c for c, v in (("contentId", a.content_id), ("edicao", a.edicao), ("versao", a.versao), ("idiomas", a.idiomas), ("regiao", a.regiao_base)) if v]
        rec = {"qid": a.qid, "jogo": a.jogo, "cusa": a.cusa.upper(), "contentId": a.content_id, "edicao": a.edicao, "versao": a.versao, "regiao": None,
               "idiomas": [i.strip() for i in a.idiomas.split(",") if i.strip()] if a.idiomas else None, "idiomasBase": a.idiomas_base, "status": "citado",
               "evidencias": [{"fonte": a.evidencia_fonte, "url": a.evidencia_url, "obtidoEm": date.today().isoformat(), "afirma": afirma, "tipo": "informado-pelo-usuario"}]}
        if a.regiao_base and a.content_id and CONTENT_ID_RE.match(a.content_id):
            pre = a.content_id[:2]
            if pre in PREFIXO_REGIAO:
                rec["regiao"] = {"codigo": PREFIXO_REGIAO[pre], "prefixo": pre, "base": a.regiao_base}
        try:
            adicionar(doc, rec)
        except ValueError as e:
            print(f"ERRO  {e}", file=sys.stderr)
            return 2
        salvar(doc, a.versoes)
        print(f"Registro {a.cusa.upper()} de {a.qid} adicionado ({a.versoes}).")
        return 0

    termo = " ".join(a.busca).strip()
    qid_arg = termo.upper() if QID_RE.match(termo.upper()) else None
    cusa_arg = a.cusa or (termo.upper() if CUSA_RE.match(termo.upper()) else None)
    regs, omitidos = consultar(doc, qid_arg, cusa_arg, a.regiao, a.idioma)
    jogos: dict[str, str] = {}                                    # qid -> nome a exibir (só jogos que o usuário pediu)
    if termo and not qid_arg and not CUSA_RE.match(termo.upper()):
        for t in busca.buscar(indice, termo):                     # localiza candidatos no índice; as versões vêm do Q-id explícito
            if str(t.get("idFonte", "")).startswith("wikidata:"):
                jogos[t["idFonte"].split(":", 1)[1]] = t["nome"]
        qn = busca.norm(termo)
        for r in doc["versoes"]:                                  # e pelo rótulo do próprio registro (índice ausente)
            if qn and all(w in busca.norm(r.get("jogo")) for w in qn.split()):
                jogos.setdefault(r["qid"], r["jogo"])
        regs = [r for r in regs if r["qid"] in jogos]
    por_qid: dict[str, list[dict]] = {}
    for r in regs:
        por_qid.setdefault(r["qid"], []).append(r)
    if a.json:
        print(json.dumps(regs, ensure_ascii=False, indent=1))
        return 0 if regs else 1
    if not regs:
        extra = f" ({omitidos} registro(s) sem o campo filtrado ficaram de fora: o valor desconhecido não é presumido)" if omitidos else ""
        outros = [n for q, n in jogos.items() if q not in por_qid]
        print(f"Nenhuma versão CUSA registrada para esta consulta{extra}.")
        if outros:
            print(f"{len(outros)} jogo(s) do índice casam com o nome, mas sem versões registradas: " + "; ".join(outros[:8]) + (" …" if len(outros) > 8 else ""))
        return 1
    for qid, rs in por_qid.items():
        nome = jogos.get(qid) or rs[0]["jogo"]
        print(f"{nome}  [wikidata:{qid}]  {len(rs)} versão(ões)\n  {_vinculo(qid, indice, rs[0]['jogo'])}")
        for r in rs:
            print("\n".join(linhas_registro(r, a.evidencias)))
        print()
    if omitidos:
        print(f"{omitidos} registro(s) sem o campo filtrado ficaram de fora: o valor desconhecido não é presumido.")
    sem = [n for q, n in jogos.items() if q not in por_qid]
    if sem:
        print(f"{len(sem)} outro(s) jogo(s) casam com o nome, mas sem versões registradas: " + "; ".join(sem[:8]) + (" …" if len(sem) > 8 else ""))
    print("CUSA identifica o título; não é link nem indica que exista PKG/download disponível. 'citado' = fonte vista, página não aberta/conferida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
