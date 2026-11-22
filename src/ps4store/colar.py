"""COLAR: resolve URLs (resolver.py) e monta blocos de URLs PRONTOS para colar no painel Phone Companion do SSPI (uma URL por linha).

Só usa o resolvedor como biblioteca; não baixa arquivos, não grava histórico, não executa nada do que recebe (URL só passa por regex e HTTP,
nunca por shell). Regras de segurança do que é 'pronto':
  - só arquivo OK e enviável ao SSPI; link assinado/temporário fica de fora (a menos que --aceitar-temporarias);
  - conjunto RAR só é pronto se `.partNN.rar`, completo, na ordem, sem truncamento e com <= 50 volumes;
  - o painel aceita no máximo 50 links por envio (PairServer.cs: acima disso NADA é enfileirado): listas maiores viram lotes de 50.
Uso: python -m ps4store.colar [--extrair] [--bloco N] [--sem-copiar] [--json] URL...    (no Termux: via termux-url-opener)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .net import SIGNED_RE
from .resolver import OK, PAGINA_SEM_ARQUIVO, Resolved, ResolverNet, crawl, group_sets, load_hosts

LIMITE_PAINEL = 50
MAX_URL = 2048
_URL = re.compile(r"https?://[^\s<>\"'`\\]+", re.I)
_CTRL = re.compile(r"[\x00-\x20\x7f]")


def validar_url(s: str) -> str | None:
    """Devolve a URL se for http(s) simples e segura de tratar; None caso contrário (sem espaços/controle, host presente, sem credenciais)."""
    if not isinstance(s, str) or not 8 <= len(s) <= MAX_URL or _CTRL.search(s):
        return None
    p = urlsplit(s)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    return s


def extrair_urls(texto: str, limite: int = 10) -> list[str]:
    """URLs http(s) dentro de um texto compartilhado (o Android costuma mandar 'título + URL'). Tira pontuação final e ignora o resto."""
    out = []
    for m in _URL.findall(texto or ""):
        u = validar_url(m.rstrip(".,;:!?)]}"))
        if u and u not in out:
            out.append(u)
    return out[:limite]


@dataclass
class Bloco:
    titulo: str
    urls: list = field(default_factory=list)
    pronto: bool = False
    avisos: list = field(default_factory=list)       # o que o usuário precisa saber ao colar
    bloqueio: list = field(default_factory=list)     # por que NÃO é pronto (vazio se pronto)
    tipo: str = "pkg"                                # pkg | rar


def _temporaria(u: str) -> bool:
    return bool(SIGNED_RE.search(u))


def montar_blocos(crawls: list, aceitar_temporarias: bool = False) -> dict:
    """Blocos prontos e a lista do que NÃO enviar. Entrada: resultados de resolver.crawl()."""
    files, terminal = [], []
    for c in crawls:
        for f in c.files:
            if all(f.sspiUrl != g.sspiUrl for g in files):
                files.append(f)
        terminal += c.terminal
    truncated = any(c.truncated for c in crawls)
    avisos: list[str] = []
    nao: list[dict] = []
    blocos: list[Bloco] = []

    def barrado(f: Resolved) -> str | None:
        if not f.sspiSendable:
            return f.detail or "link não utilizável pelo baixador do SSPI"
        if _temporaria(f.sspiUrl) and not aceitar_temporarias:
            return "link assinado/temporário (expira): use a URL estável da página de origem ou --aceitar-temporarias"
        return None

    singles = []
    sets_files = []
    for f in files:
        (sets_files if f.format == "rar-multiparte" else singles).append(f)

    for g in group_sets(sets_files, truncated):
        b = Bloco(f"RAR {g['set']} · {g['volumes']} volume(s) · {g['totalBytes'] / 1e6:.1f} MB", tipo="rar")
        vols = {u: f for f in sets_files for u in [f.sspiUrl]}
        b.urls = list(g["sspiOrder"])
        bad = [barrado(vols[u]) for u in b.urls if barrado(vols[u])]
        if g["style"] != "part-rar":
            b.bloqueio.append("estilo antigo (.rar + .rNN): a contagem de volumes não é verificável; não é marcado como pronto")
        if not g["complete"] or truncated:
            b.bloqueio += [p for p in g["problems"] if "não é verificável" not in p] or ["conjunto incompleto"]
        if len(b.urls) > LIMITE_PAINEL:
            b.bloqueio.append(f"{len(b.urls)} volumes: o painel do SSPI aceita no máximo {LIMITE_PAINEL} links por envio e o conjunto não pode ser dividido")
        b.bloqueio += sorted(set(bad))
        b.pronto = not b.bloqueio
        if b.pronto:
            b.avisos.append("cole tudo de uma vez; o SSPI agrupa os volumes pelos nomes .partNN.rar (ordem 01 → N)")
        blocos.append(b)

    prontos = [f for f in singles if not barrado(f)]
    for f in singles:
        why = barrado(f)
        if why:
            nao.append({"url": f.sspiUrl, "motivo": why})
    if len(prontos) > LIMITE_PAINEL:
        avisos.append(f"{len(prontos)} URLs avulsas: o painel aceita no máximo {LIMITE_PAINEL} por envio; divididas em lotes")
    for i in range(0, len(prontos), LIMITE_PAINEL):
        lote = prontos[i:i + LIMITE_PAINEL]
        n = i // LIMITE_PAINEL + 1
        tot = (len(prontos) + LIMITE_PAINEL - 1) // LIMITE_PAINEL
        b = Bloco(f"{len(lote)} arquivo(s) avulso(s)" + (f" · lote {n} de {tot}" if tot > 1 else "") + f" · {sum(x.sizeBytes or 0 for x in lote) / 1e6:.1f} MB",
                  [x.sspiUrl for x in lote], True)
        blocos.append(b)

    total = sum(len(b.urls) for b in blocos)
    if total > LIMITE_PAINEL:
        avisos.append(f"{total} URLs no total (> {LIMITE_PAINEL}): cole um bloco por vez")
    if truncated:
        avisos.append("a busca foi truncada por limite (páginas/requisições): podem existir mais arquivos; aumente --max-paginas/--max-requisicoes")

    for r in terminal:
        if r.status == OK:
            continue
        if r.status == PAGINA_SEM_ARQUIVO and files:
            continue                                                   # página não expandida: ruído quando já há arquivos
        dica = " Para permitir este host: PS4STORE_PERMITIR=host (ou --permitir host)." if r.status == "HOST_NAO_PERMITIDO" else ""
        nao.append({"url": r.inputUrl, "motivo": f"{r.status}: {r.detail}{dica}"})
    blocos.sort(key=lambda b: (not b.pronto,))                         # prontos primeiro (ordem estável)
    return {"blocos": blocos, "naoEnviar": nao, "avisos": avisos}


def copiar(texto: str, run=subprocess.run, which=shutil.which) -> tuple[bool, str]:
    """Copia com Termux:API se existir (`termux-clipboard-set`, sem shell, texto por stdin). Senão devolve False (cópia manual)."""
    exe = which("termux-clipboard-set")
    if not exe:
        return False, "termux-clipboard-set não encontrado (instale `pkg install termux-api` e o app Termux:API): copie manualmente"
    try:
        r = run([exe], input=texto, text=True, timeout=10, capture_output=True)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"falha ao copiar ({type(e).__name__}): copie manualmente"
    return (r.returncode == 0, "" if r.returncode == 0 else "termux-clipboard-set falhou: copie manualmente")


def main(argv=None, net: ResolverNet | None = None, run=subprocess.run, which=shutil.which) -> int:
    ap = argparse.ArgumentParser(prog="python -m ps4store.colar", description="resolve URLs e monta blocos para colar no painel do SSPI")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--extrair", action="store_true", help="extrai as URLs http(s) de um texto compartilhado (modo Termux)")
    ap.add_argument("--bloco", type=int, default=1, help="qual bloco PRONTO copiar (padrão 1)")
    ap.add_argument("--sem-copiar", action="store_true")
    ap.add_argument("--aceitar-temporarias", action="store_true", help="inclui links assinados/temporários (expiram)")
    ap.add_argument("--permitir", action="append", default=[], metavar="HOST")
    ap.add_argument("--hosts", default="config/resolver-hosts.json")
    ap.add_argument("--profundidade", type=int, default=2)
    ap.add_argument("--max-paginas", type=int, default=30)
    ap.add_argument("--max-requisicoes", type=int, default=80)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    bruto = list(a.urls)
    urls: list[str] = []
    for x in bruto:
        urls += extrair_urls(x) if a.extrair else ([x] if validar_url(x) else [])
    urls = list(dict.fromkeys(urls))[:10]
    if not urls:
        print("ERRO  nenhuma URL http(s) válida na entrada (nada foi executado nem acessado)", file=sys.stderr)
        return 2
    extra = [h.strip().lower() for h in os.environ.get("PS4STORE_PERMITIR", "").split(",") if h.strip()]
    hosts = load_hosts(Path(a.hosts)) | {h.lower() for h in a.permitir} | set(extra)
    net = net or ResolverNet()
    crawls = [crawl(u, net, hosts, max_depth=max(0, a.profundidade), max_pages=a.max_paginas, max_requests=a.max_requisicoes) for u in urls]
    res = montar_blocos(crawls, a.aceitar_temporarias)
    blocos: list[Bloco] = res["blocos"]
    prontos = [b for b in blocos if b.pronto]
    if a.json:
        print(json.dumps({"blocos": [asdict(b) for b in blocos], "naoEnviar": res["naoEnviar"], "avisos": res["avisos"]}, ensure_ascii=False, indent=1))
        return 0 if prontos else 3
    print(f"Resolvido: {sum(len(c.files) for c in crawls)} arquivo(s) · {len(prontos)} bloco(s) pronto(s) · {len(blocos) - len(prontos)} bloqueado(s)")
    for av in res["avisos"]:
        print(f"AVISO  {av}")
    for i, b in enumerate(blocos, 1):
        print(f"\n== BLOCO {i} · {'PRONTO' if b.pronto else 'NÃO ENVIAR'} · {b.titulo}")
        for av in b.avisos:
            print(f"   {av}")
        for p in b.bloqueio:
            print(f"   BLOQUEADO: {p}")
        if b.pronto:
            for u in b.urls:
                print(u)
    if res["naoEnviar"]:
        print("\n== NÃO ENVIAR")
        for n in res["naoEnviar"][:8]:
            print(f"   {n['url'][:100]}\n      {n['motivo']}")
        if len(res["naoEnviar"]) > 8:
            print(f"   ... e mais {len(res['naoEnviar']) - 8}")
    if not prontos:
        print("\nNada pronto para enviar ao SSPI.")
        return 3
    idx = [i for i, b in enumerate(blocos) if b.pronto]
    if not 1 <= a.bloco <= len(prontos):
        print(f"\nERRO  --bloco {a.bloco} não existe (há {len(prontos)} pronto(s))", file=sys.stderr)
        return 2
    alvo = prontos[a.bloco - 1]
    texto = "\n".join(alvo.urls) + "\n"
    if a.sem_copiar:
        return 0
    ok, msg = copiar(texto, run, which)
    if ok:
        print(f"\nCopiado: BLOCO {idx[a.bloco - 1] + 1} ({len(alvo.urls)} URL(s)) para a área de transferência. Cole no painel do SSPI → Downloads → Paste a download link.")
        if len(prontos) > 1:
            print(f"Há {len(prontos)} blocos prontos; para copiar outro: --bloco N")
    else:
        print(f"\n{msg}\n----- copie daqui (BLOCO {idx[a.bloco - 1] + 1}) -----\n{texto}----- até aqui -----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
