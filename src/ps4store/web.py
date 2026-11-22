"""WEB: gera o catálogo estático pesquisável (HTML único, sem backend) a partir de local/research.json.

Só LÊ os registros que o robô já valida; não descobre, não sonda, não altera o .gssource. Duas decisões ficam explícitas aqui:
  - o que aparece: nada de ID com aparência comercial (restricted), versões antigas, duplicados nem RAR; só PKG;
  - quando a URL é embutida: só de item com link TESTADO + identidade LIDA do PKG, e (modo 'publico') só se a política de publicação
    o autoriza. No modo 'pessoal' entram também os de link direto validado (a página fica pública no GitHub Pages: decisão do dono do repositório).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ASSET = Path(__file__).with_name("web_assets") / "index.html"
KIND_PT = {"base": "Jogo/app base", "update": "Atualização", "dlc": "DLC"}
REASON_PT = {"NO_AUTHORIZATION": "sem autorização de listagem registrada", "KIND_NOT_BASE": "não é jogo base",
             "LINK_NOT_USABLE": "link não utilizável pelo SSPI", "NOT_IDENTIFIED": "arquivo ainda não identificado",
             "TLS_HOST_BLOCKED": "host com falha de TLS conhecida", "DUPLICATE": "duplicado"}


def load_proven(path: Path | None) -> dict[str, dict]:
    """url exata -> {date, note}. Só vale o que o usuário relatou ter instalado no PS4 (config/ps4-proven.json)."""
    if not path or not Path(path).exists():
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {p["url"]: {"date": p.get("date", ""), "note": p.get("note", "")} for p in doc.get("proven", []) if p.get("url")}


def _state(r: dict) -> tuple[str, str]:
    """(estado, texto). 'validado' exige link testado E identidade lida do PKG E item disponível por alguma rota."""
    st = r.get("status", {})
    if st.get("linkAccessible") is False:
        return "inacessivel", f"Link inacessível ({r.get('linkStatus') or 'falhou'})"
    if st.get("linkAccessible") is None:
        return "nao-testado", "Descoberto, link ainda NÃO testado"
    if not r.get("identityRead"):
        return "nao-testado", "Link responde, mas o arquivo ainda não foi identificado"
    if r.get("publicationAvailable") or r.get("directInstallAvailable"):
        return "validado", "Link validado automaticamente"
    blk = r.get("publicationBlockers") or r.get("directInstallBlockers") or []
    return "indisponivel", "Indisponível: " + (", ".join(REASON_PT.get(b, b) for b in blk) or "sem motivo registrado")


def select_items(entries: list[dict], mode: str = "publico", proven: dict | None = None) -> list[dict]:
    if mode not in ("publico", "pessoal"):
        raise ValueError("modo deve ser 'publico' ou 'pessoal'")
    proven = proven or {}
    out = []
    for r in entries:
        if r.get("fileType") != "pkg" or r.get("restricted") or r.get("duplicateOf") or r.get("rejectionReason") == "SUPERSEDED":
            continue
        if r.get("sourceActive") is False:
            continue
        state, text = _state(r)
        item = {
            "name": r.get("name") or r.get("titleId") or "?", "titleId": r.get("titleId") or "", "version": str(r.get("version") or ""),
            "kind": KIND_PT.get(r.get("kind") or "", "Tipo não identificado"), "fileType": "PKG",
            "contentId": r.get("contentId") or "", "identity": "lida do PKG" if r.get("identityRead") else "informada pela fonte (não lida do PKG)",
            "sizeMB": round((r.get("sizeBytes") or 0) / 1e6, 1), "source": r.get("source") or "",
            "state": state, "text": text, "catalog": bool(r.get("publicationAvailable")),
        }
        if state == "validado":
            if r.get("publicationAvailable") or mode == "pessoal":
                item["url"] = r["url"]
            else:
                item["text"] += " (link não listado publicamente: sem autorização de listagem)"
        p = proven.get(r.get("url"))
        if p:
            item["ps4"] = p
        out.append(item)
    out.sort(key=lambda i: (i["state"] != "validado", i["name"].casefold(), i["version"]))
    return out


def build_site(research: dict, out_dir: Path, mode: str = "publico", proven_path: Path | None = None) -> dict:
    items = select_items(research.get("entries", []), mode, load_proven(proven_path))
    doc = {"generatedAt": research.get("generatedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "mode": mode, "items": items}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, ensure_ascii=False).replace("</", "<\\/")          # nunca fecha o <script> por dentro dos dados
    html = ASSET.read_text(encoding="utf-8").replace("/*__DATA__*/null", data, 1)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "catalog.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"items": len(items), "validated": sum(1 for i in items if i["state"] == "validado"),
            "withUrl": sum(1 for i in items if i.get("url")), "ps4Proven": sum(1 for i in items if i.get("ps4"))}
