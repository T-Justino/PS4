"""Prontidão para retomada: Range em offsets arbitrários, tamanho/ETag estáveis, expiração da URL temporária."""
import http.server
import json
import threading
import time

import pytest

from ps4store.cli import main
from ps4store.links import classify_link
from ps4store.net import UrllibNet
from ps4store.validation import resume_check

BODY = bytes(range(256)) * 4096          # 1 MiB


def serve(handler):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_port}"


def make_handler(*, honor=True, etag="stable", total=None, redirect_exp=None):
    counter = {"n": 0}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            if self.path == "/go":
                loc = "/file" + (f"?exp={int(time.time()) + redirect_exp}&sig=abc" if redirect_exp else "")
                self.send_response(302); self.send_header("Location", loc); self.end_headers(); return
            counter["n"] += 1
            rng = self.headers.get("Range")
            if rng and honor:
                a, b = rng.split("=")[1].split("-")
                a, b = int(a), min(int(b), len(BODY) - 1)
                chunk = BODY[a:b + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {a}-{b}/{total or len(BODY)}")
            else:
                chunk = BODY
                self.send_response(200)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("ETag", f'"{counter["n"]}"' if etag == "changing" else '"abc"')
            self.end_headers()
            try:
                self.wfile.write(chunk)
            except OSError:
                pass
    return H


def net():
    return UrllibNet(allow_insecure=True, timeout=5)


def test_resume_ready_when_ranges_honored_total_and_etag_stable():
    s, u = serve(make_handler())
    try:
        r = resume_check(u + "/go", len(BODY), net())
        assert r["ready"] and r["rangeHonored"] and r["totalStable"] and r["etagStable"] and r["validators"] == "etag"
        assert [p["offset"] for p in r["points"]] == [262144, 524288, 942080]           # 25 %, 50 %, 90 % alinhados a 4 KiB
    finally:
        s.shutdown()


def test_resume_not_ready_when_server_ignores_range_or_etag_changes_or_total_differs():
    for kw, note in ((dict(honor=False), "não honrou Range"), (dict(etag="changing"), "ETag muda"), (dict(total=len(BODY) + 5), "tamanho total")):
        s, u = serve(make_handler(**kw))
        try:
            r = resume_check(u + "/go", len(BODY), net())
            assert not r["ready"] and any(note in n for n in r["notes"]), (kw, r["notes"])
        finally:
            s.shutdown()


def test_signed_url_ttl_is_measured_and_noted_without_storing_the_url():
    s, u = serve(make_handler(redirect_exp=3600))
    try:
        pr = net().probe(u + "/go", 1024)
        assert pr.signed and 3500 < pr.expires_in <= 3600
        c = classify_link(pr)
        assert c["ttlSeconds"] == pr.expires_in and c["etagStrong"] and any("expira em ≈60 min" in n for n in c["notes"])
        assert "sig=" not in json.dumps(c)
    finally:
        s.shutdown()


def test_cli_resume_check_reads_research_and_caps_titles(tmp_path, capsys):
    s, u = serve(make_handler())
    try:
        rows = [{"name": f"Jogo {i}", "titleId": f"ABCD0000{i}", "fileType": "pkg", "sizeBytes": len(BODY), "url": u + "/go",
                 "directInstallAvailable": True} for i in range(3)]
        (tmp_path / "r.json").write_text(json.dumps({"entries": rows}))
        assert main(["resume-check", "--research", str(tmp_path / "r.json"), "--min-mb", "0", "--limit", "2"], net=net()) == 0
        out = capsys.readouterr().out
        assert out.count("PRONTO") == 2 and "range=ok" in out
        assert main(["resume-check", "--title", "ZZZZ99999", "--research", str(tmp_path / "r.json")], net=net()) == 0
        assert "nenhum título elegível" in capsys.readouterr().out
    finally:
        s.shutdown()
