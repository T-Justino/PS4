#!/usr/bin/env python3
"""Compara a cadeia de certificados que um host serve com as âncoras que o SSPI carrega (somente leitura; nada é desativado).

Usa `openssl s_client` (conexão normal, verificação completa contra o pacote de CAs do sistema). Para cada host: cadeia servida,
raiz alcançada, e se essa raiz (ou um intermediário) está entre as ÂNCORAS DO SSPI (lista curada de raízes + intermediários fixados,
lidos do código público `app/NativeHttp.cs`). Também compara a cadeia entre os IPs do host (bordas diferentes) e entre um cliente
moderno e um cliente RSA/TLS1.2 (aproximação de uma pilha antiga). O firmware 9.00 pode ter raízes próprias além da lista do SSPI:
"RISCO" significa só que o SSPI não a carrega; não prova falha.
Uso: tls_chain.py [host ...]   (sem argumentos: lista padrão de candidatos)
"""
import re
import socket
import subprocess
import sys
import tempfile

BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
ROOT_MARKERS = ["CN=ISRG Root X1,", "CN=ISRG Root X2,", "CN=DigiCert Global Root G2,", "OU=GlobalSign Root CA - R3", "OU=GlobalSign Root CA - R6",
                "CN=GlobalSign Root R46,", "CN=USERTrust RSA Certification Authority,", "CN=COMODO RSA Certification Authority,",
                "CN=Sectigo Public Server Authentication Root R46,", "CN=Sectigo Public Server Authentication Root E46,",
                "CN=USERTrust ECC Certification Authority,", "CN=Amazon Root CA 1,", "CN=GTS Root R1,", "CN=GTS Root R2,", "CN=GTS Root R3,",
                "CN=GTS Root R4,", "CN=Go Daddy Root Certificate Authority - G2,", "CN=Microsoft RSA Root Certificate Authority 2017,",
                "CN=DigiCert Trusted Root G4,"]
PINS = {"873F0BA80E3AC222656DFD04158CC15C2927D42D5D05F01DEE4A47EB43A916DF": "GitHub Sectigo DV (pin)",
        "8C54C334B66BA4E426772AF4A3F9136C19A1AEC729FDB28C535C07A5A4EF22E0": "GitHub Sectigo DV (pin)",
        "13949634D99CD6FD6AA80BC034FEFACCEB1969FEEF986586713ECDBB05758D3F": "Let's Encrypt Gen Y intermediário (pin)",
        "238B85A0099C65B970477D5724F1A1D475CE5058CFFE4EFA8733899BDB863C47": "Let's Encrypt Gen Y intermediário (pin)",
        "A2372D06431E9716365EEED47EC020351497D182FCC038E457E58168A03CAC07": "Let's Encrypt Gen Y intermediário (pin)",
        "97658DE8C68DFA98ACE1E5028A63D54A1AAE911B3E21471076C6850CD08CBAB4": "Let's Encrypt Gen Y intermediário (pin)",
        "E57B7E6F150C419102E8D5C055729FF967B9D1A829BF00CEC89CA604EBF4A86F": "ISRG Root YR (pin)",
        "E14FFCAD5B0025731006CAA43A121A22D8E9700F4FB9CF852F02A708AA5D5666": "ISRG Root YE (pin)",
        "A287FFAB762CC69A26D482037EDF701F653CE899025C62A7E5CB88BB9B419CBB": "Google WE1 cross-sign (pin)",
        "973A41276FFD01E027A2AAD49E34C37846D3E976FF6A620B6712E33832041AA6": "GoDaddy Secure G2 intermediário (pin)",
        "C06E307F7CFC1D32FA72A4C033C87B90019AF216F0775D64978A2ECA6C8A230E": "GeoTrust TLS RSA CA G1 (pin)"}
DEFAULT_HOSTS = ["raw.githubusercontent.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
                 "t-justino.github.io", "cdn.jsdelivr.net", "fastly.jsdelivr.net", "gcore.jsdelivr.net", "pkg-zone.com", "api.pkg-zone.com",
                 "storage.googleapis.com", "s3.amazonaws.com", "gitlab.com", "codeberg.org", "huggingface.co", "archive.org"]
PEM = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)


def run(args, data=None, timeout=20):
    return subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout).stdout


def served_chain(host, ip=None, rsa_only=False):
    args = ["openssl", "s_client", "-connect", f"{ip or host}:443", "-servername", host, "-showcerts"]
    if rsa_only:
        args += ["-tls1_2", "-cipher", "ECDHE-RSA-AES128-GCM-SHA256:AES128-GCM-SHA256", "-sigalgs", "RSA+SHA256"]
    try:
        return PEM.findall(run(args, data="", timeout=25))
    except Exception:
        return []


def info(pem):
    out = run(["openssl", "x509", "-noout", "-subject", "-issuer", "-enddate", "-fingerprint", "-sha256", "-nameopt", "RFC2253"], data=pem)
    g = lambda k: (re.search(rf"^{k}=?\s*(.*)$", out, re.M) or [None, ""])[1].strip()
    fp = (re.search(r"Fingerprint=([0-9A-F:]+)", out) or [None, ""])[1].replace(":", "")
    return {"subject": g("subject"), "issuer": g("issuer"), "notAfter": g("notAfter"), "sha256": fp}


def reach_root(chain):
    """Raiz alcançada contra o pacote de CAs do sistema (openssl verify -show_chain)."""
    if not chain:
        return None, "sem certificado"
    with tempfile.NamedTemporaryFile("w", suffix=".pem") as leaf, tempfile.NamedTemporaryFile("w", suffix=".pem") as rest:
        leaf.write(chain[0]); leaf.flush(); rest.write("\n".join(chain[1:])); rest.flush()
        out = run(["openssl", "verify", "-show_chain", "-nameopt", "RFC2253", "-CAfile", BUNDLE, "-untrusted", rest.name, leaf.name])
    ok = "OK" in out.splitlines()[0:1] or ": OK" in out
    depths = re.findall(r"depth=\d+:\s*(.*)", out)
    return (depths[-1] if depths else None), ("ok" if ok else (out.strip().splitlines() or ["falha"])[-1])


def verdict(chain):
    infos = [info(c) for c in chain]
    root, status = reach_root(chain)
    pinned = [PINS[i["sha256"]] for i in infos if i["sha256"] in PINS]
    root_ok = bool(root) and any(m.lower() in root.lower() for m in ROOT_MARKERS)
    if status != "ok":
        v = f"NÃO VERIFICA ({status[:60]})"
    elif root_ok:
        v = "ANCORADO (raiz na lista do SSPI)"
    elif pinned:
        v = "ANCORADO (intermediário fixado: " + pinned[0] + ")"
    else:
        v = "RISCO (raiz fora da lista do SSPI: depende do store do firmware)"
    return v, root, infos, pinned


def ips(host):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except OSError:
        return []


def main(hosts):
    print("| Host | Cliente | Veredito | Raiz alcançada | Emissor do servidor | Certs na cadeia | IPs / cadeias distintas |")
    print("|---|---|---|---|---|---|---|")
    for host in hosts:
        addrs = ips(host)
        fps = {}
        for ip in addrs[:6]:
            ch = served_chain(host, ip)
            fps.setdefault(tuple(info(c)["sha256"] for c in ch), []).append(ip)
        for label, rsa in (("moderno", False), ("RSA/TLS1.2", True)):
            ch = served_chain(host, None, rsa)
            if not ch:
                print(f"| `{host}` | {label} | sem resposta | | | | {len(addrs)} IPs |")
                continue
            v, root, infos, _ = verdict(ch)
            iss = infos[1]["subject"] if len(infos) > 1 else infos[0]["issuer"]
            leaf_iss = infos[0]["issuer"]
            print(f"| `{host}` | {label} | {v} | `{(root or '?')[:60]}` | `{leaf_iss[:70]}` | {len(ch)} | {len(addrs)} IPs / {len(fps)} cadeia(s) distinta(s) |")
        if len(fps) > 1:
            for k, v in fps.items():
                print(f"|  ↳ variante | | | | | {len(k)} | {', '.join(v)} |")
    print("\n### Detalhe: cada certificado servido (cliente moderno, 1º IP) e se é fixado (pin) pelo SSPI\n")
    for host in hosts:
        ch = served_chain(host)
        if not ch:
            continue
        print(f"**{host}**\n")
        for n, c in enumerate(ch):
            i = info(c)
            print(f"- [{n}] `{i['subject'][:70]}` · sha256 `{i['sha256'][:16]}…` · expira {i['notAfter']} · "
                  f"**{PINS.get(i['sha256'], 'não fixado pelo SSPI')}**")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_HOSTS)
