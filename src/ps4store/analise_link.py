"""ANÁLISE DE LINK (5H): de uma URL até "o que é isto, de que jogo, e o que vai para o SSPI" — reaproveita resolver.py (crawl/resolve),
pkginfo.py (Content ID e param.sfo dos primeiros bytes do PKG) e colar.py (blocos prontos para o painel do SSPI).

Segurança herdada do resolvedor: só HTTPS, host de entrada na lista config/resolver-hosts.json, ≤5 redirecionamentos conferidos (sem IP privado),
lê no máximo 64 KiB por arquivo (1 MiB só se o param.sfo estiver além), não segue CAPTCHA/login/JavaScript, não baixa pacote.
Página da PlayStation Store NUNCA é tratada como link de PKG: é página de loja (só o Content ID da URL é lido, sem acesso à rede).
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from . import colar, pkginfo, unificada, versoes
from .resolver import OK, ResolverNet, crawl, load_hosts

CUSA_TXT = re.compile(r"CUSA\d{5}", re.I)
CID_TXT = re.compile(r"[A-Z]{2}\d{4}-CUSA\d{5}_\d{2}-[A-Z0-9]{16}", re.I)
VER_TXT = re.compile(r"(?:\b[vV]|[_\-. ]A)(\d{1,2})[._]?(\d{2})\b")
LOJA = re.compile(r"(^|\.)playstation\.com$", re.I)
MAX_ARQUIVOS = 10
TIPOS_SFO = {"gd": "jogo/aplicativo (base)", "gde": "aplicativo (base)", "gp": "atualização (patch)", "ac": "conteúdo adicional (DLC)"}


def _identificar_nome(texto: str) -> dict:
    t = unquote(texto or "")
    cid = CID_TXT.search(t)
    cusa = CUSA_TXT.search(t)
    ver = VER_TXT.search(t)
    return {"contentId": cid.group(0).upper() if cid else None, "cusa": (cid.group(0)[7:16] if cid else (cusa.group(0).upper() if cusa else None)),
            "versao": f"{int(ver.group(1)):02d}.{ver.group(2)}" if ver else None, "base": "nome do arquivo/URL (não verificado nos bytes)"}


def _identificar_pkg(url: str, net) -> dict:
    """Lê o cabeçalho do PKG (64 KiB; até 1 MiB se o param.sfo estiver além) e devolve o que os BYTES dizem."""
    nbytes = 65536
    for _ in range(2):
        pr, _hdr, body = net.fetch(url, nbytes)
        if not pr.ok:
            return {"erro": pr.error or f"HTTP {pr.status}"}
        try:
            h = pkginfo.parse_head(pr.head or body)
        except pkginfo.PkgError as e:
            if e.code == "SFO_OUTSIDE_WINDOW" and e.need and e.need[1] <= 1_048_576 and nbytes == 65536:
                nbytes = e.need[1]
                continue
            return {"erro": f"{e.code}: {e}"}
        sfo = h.sfo
        cat = str(sfo.get("CATEGORY") or "")
        return {"contentId": h.content_id, "cusa": h.title_id if versoes.CUSA_RE.match(h.title_id) else None, "titleId": h.title_id,
                "versaoApp": sfo.get("APP_VER"), "versaoPkg": sfo.get("VERSION"), "categoria": cat, "tipo": TIPOS_SFO.get(cat, "desconhecido"),
                "titulo": str(sfo.get("TITLE") or "")[:120], "firmwareSfo": None, "base": "cabeçalho e param.sfo do PKG (bytes lidos)"}
    return {"erro": "param.sfo fora da janela lida"}


def _cusas_do_jogo(qid: str, curados: dict, wd: dict) -> tuple[set[str], set[str]]:
    regs = unificada.registros_do_jogo(qid, curados, wd) if qid else []
    conf = {c["cusa"] for c in unificada.conflitos_do_jogo(qid, wd)} if qid else set()
    return {r["cusa"] for r in regs}, conf


def comparar(ident: dict, qid: str, curados: dict, wd: dict) -> dict:
    if not qid:
        return {"resultado": "sem-jogo", "texto": "nenhum jogo selecionado: sem comparação"}
    cusas, conflito = _cusas_do_jogo(qid, curados, wd)
    c = ident.get("cusa")
    if not c:
        tid = ident.get("titleId")
        return {"resultado": "sem-identificacao", "texto": f"o arquivo não traz CUSA verificável{f' (ID {tid}: homebrew ou app sem CUSA)' if tid else ''}: não dá para confirmar que é deste jogo"}
    if c in conflito:
        return {"resultado": "conflito", "texto": f"{c} está em CONFLITO auditado (atribuído a mais de um jogo no Wikidata): não confirmado para este jogo"}
    if c in cusas:
        return {"resultado": "corresponde", "texto": f"{c} é um CUSA conhecido deste jogo" + (" (pelo nome do arquivo, não pelos bytes)" if "nome" in ident.get("base", "") else "")}
    if not cusas:
        return {"resultado": "sem-referencia", "texto": f"o arquivo indica {c}, mas este jogo não tem CUSA cadastrado para comparar"}
    return {"resultado": "diferente", "texto": f"INCOMPATÍVEL: o arquivo indica {c}, e os CUSAs conhecidos deste jogo são {', '.join(sorted(cusas))}"}


def analisar(url: str, qid: str, curados: dict, wd: dict, net: ResolverNet | None = None, hosts: set[str] | None = None) -> dict:
    u = colar.validar_url(url)
    if not u:
        return {"url": url[:200], "tipo": "invalida", "texto": "URL inválida (só http/https, sem espaços nem credenciais)", "arquivos": [], "sspi": None}
    host = (urlsplit(u).hostname or "").lower()
    if LOJA.search(host):
        ident = _identificar_nome(urlsplit(u).path)
        return {"url": u, "tipo": "pagina-loja", "texto": "página da PlayStation Store: NÃO é link de arquivo PKG e não vai para o SSPI",
                "arquivos": [{"url": u, "formato": "página", "identificacao": ident, "comparacao": comparar(ident, qid, curados, wd)}], "sspi": None}
    net = net or ResolverNet()
    hosts = load_hosts() if hosts is None else hosts
    c = crawl(u, net, hosts, max_depth=1, max_pages=3, max_requests=12, max_links=20)
    arquivos = []
    incompat = set()
    for f in c.files[:MAX_ARQUIVOS]:
        ident = _identificar_pkg(f.sspiUrl or f.finalUrl, net) if f.format == "pkg" else {}
        if not ident or ident.get("erro"):
            nome = _identificar_nome(f.filename + " " + (f.sspiUrl or ""))
            nome["erroBytes"] = (ident or {}).get("erro")
            ident = nome
        if f.format in ("rar", "rar-multiparte"):
            ident.setdefault("tipo", "arquivo RAR (conteúdo não inspecionado)")
        cmp_ = comparar(ident, qid, curados, wd)
        if cmp_["resultado"] in ("diferente", "conflito"):
            incompat.add(f.sspiUrl)
        arquivos.append({"url": f.sspiUrl or f.finalUrl, "arquivo": f.filename, "formato": f.format, "tamanhoBytes": f.sizeBytes, "host": f.finalHost,
                         "temporaria": bool(colar._temporaria(f.sspiUrl or "")), "identificacao": ident, "comparacao": cmp_, "notas": f.notes[:4]})
    res = colar.montar_blocos([c])
    blocos = []
    for b in res["blocos"]:
        bl = {"titulo": b.titulo, "urls": b.urls, "pronto": b.pronto, "avisos": b.avisos, "bloqueio": list(b.bloqueio), "tipo": b.tipo}
        if incompat & set(b.urls):
            bl["pronto"] = False
            bl["bloqueio"].append("há arquivo cujo CUSA NÃO é deste jogo (ou está em conflito): confira antes de enviar")
        blocos.append(bl)
    sem_arquivo = [{"url": r.inputUrl, "status": r.status, "motivo": r.detail} for r in c.terminal if r.status != OK][:8]
    tipo = "arquivos" if c.files else ("interacao" if c.interactions else "sem-arquivo")
    texto = (f"{len(c.files)} arquivo(s) encontrado(s)" if c.files else
             ("a página exige ação no navegador (CAPTCHA, login ou JavaScript): não contornado" if c.interactions else "nenhum PKG/RAR encontrado"))
    return {"url": u, "tipo": tipo, "texto": texto, "requisicoes": c.requests, "arquivos": arquivos, "naoArquivos": sem_arquivo,
            "interacoes": c.interactions[:5], "sspi": {"blocos": blocos, "naoEnviar": res["naoEnviar"][:10], "avisos": res["avisos"]}}
