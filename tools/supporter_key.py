#!/usr/bin/env python3
"""2.74.0 (#338): supporter licence keys (they unlock nothing, they only show a badge on a self-hosted server).

A key is  KSUP1.<base64url JSON>.<base64url Ed25519 signature>  with the JSON {"t": "server"|"person", "d": "YYYY-MM-DD",
"id": "<label>"}; the signature covers the text "KSUP1.<base64url JSON>". The server checks it offline against the public
key in kalmido/admin/supporter.py (SUP_PUBKEYS).

  supporter_key.py genkey --out FILE     new key pair: the private key goes into FILE (mode 600, outside this repository,
                                         never overwritten); prints ONLY the public key (base64, 32 bytes)
  supporter_key.py pubkey --key FILE     prints the public key of an existing private key file
  supporter_key.py sign --key FILE --type server|person [--id X] [--date YYYY-MM-DD]
                                         prints a licence key
  supporter_key.py verify --pub BASE64 KEY
                                         checks a licence key against a public key (exit 0 = valid, prints the content)
"""
import argparse
import base64
import json
import os
import re
import secrets
import sys
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PREFIX = "KSUP1"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def load_priv(path):
    with open(path, "rb") as f:
        k = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(k, Ed25519PrivateKey):
        sys.exit("not an Ed25519 private key")
    return k


def pub_b64(priv):
    return base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def inside_repo(path):
    p = os.path.realpath(path)
    return p == REPO or p.startswith(REPO + os.sep)


def genkey(out):
    out = os.path.abspath(os.path.expanduser(out))
    if inside_repo(out):
        sys.exit("refused: the private key must live outside the repository")
    if os.path.lexists(out):
        sys.exit("refused: the file exists (never overwritten); use: pubkey --key FILE")
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    os.chmod(out, 0o600)
    return pub_b64(priv)


def sign(priv, kind, ident=None, day=None):
    if kind not in ("server", "person"):
        raise ValueError("type: server or person")
    ident = ident or secrets.token_hex(6)
    if not ID_RE.fullmatch(ident):
        raise ValueError("id: 1-64 characters A-Z a-z 0-9 . _ -")
    day = day or date.today().isoformat()
    date.fromisoformat(day)
    body = PREFIX + "." + b64u(json.dumps({"t": kind, "d": day, "id": ident}, separators=(",", ":")).encode())
    return body + "." + b64u(priv.sign(body.encode()))


def verify(pub, key):
    """-> the content dict; ValueError if the key is not valid for this public key."""
    parts = "".join(key.split()).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise ValueError("not a supporter key")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(unb64u(parts[2]), (parts[0] + "." + parts[1]).encode())
    except (InvalidSignature, ValueError) as e:
        raise ValueError("signature does not match") from e
    return json.loads(unb64u(parts[1]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kalmido supporter licence keys")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("genkey")
    g.add_argument("--out", required=True)
    p = sub.add_parser("pubkey")
    p.add_argument("--key", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--key", required=True)
    s.add_argument("--type", required=True, choices=("server", "person"))
    s.add_argument("--id")
    s.add_argument("--date")
    v = sub.add_parser("verify")
    v.add_argument("--pub", required=True)
    v.add_argument("licence")
    a = ap.parse_args(argv)
    if a.cmd == "genkey":
        print(genkey(a.out))
    elif a.cmd == "pubkey":
        print(pub_b64(load_priv(a.key)))
    elif a.cmd == "sign":
        try:
            print(sign(load_priv(a.key), a.type, a.id, a.date))
        except ValueError as e:
            sys.exit(str(e))
    else:
        try:
            print(json.dumps(verify(a.pub, a.licence)))
        except ValueError as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main()
