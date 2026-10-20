#!/usr/bin/env python3
"""Opens a Kalmido organisation export (*.kalmido-export, 2.42.0, #833) with the organisation's recovery key.

usage: kalmido_export_decrypt.py ARCHIVE.kalmido-export -o org.zip [--key-file FILE]

The recovery key (Settings > Organisation > Encryption: "R2-" and 13 groups of 4 characters; exports of older versions
also open with the earlier format, 13 groups without "R2-") is read from --key-file or from stdin
(typed or piped) -- never from the command line, where other users of the machine could see it in the process list.
The tool checks every block (AES-256-GCM: a wrong key, a damaged, shortened or reordered file is refused), writes the ZIP
and then checks the SHA-256 of every entry against its manifest.json. Needs Python 3.8+ and the package "cryptography"
(pip install cryptography). Exit codes: 0 ok, 1 wrong key / damaged archive, 2 usage.

The format is described in kalmido/admin/orgexport.py."""
import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import struct
import sys
import zipfile

MAGIC = b"KALMIDO-ORGX\n"
FK_AAD = b"kalmido-orgx-fk|1|"
TAG = 16


class Bad(Exception):
    pass


def parse_key(text):
    """("secret" | "key", 32 bytes) of a recovery key (base32 without padding; spaces, dashes and case do not matter).
    "R2-..." = the recovery secret (it opens the header's recovery_wrapped), else the earlier format = the org key."""
    s = re.sub(r"[\s\-]", "", str(text or "")).upper()
    kind = "key"
    if len(s) == 54 and s.startswith("R2"):
        kind, s = "secret", s[2:]
    if not re.fullmatch(r"[A-Z2-7]{52}", s):
        raise Bad("this is not a recovery key (expected R2- and 52 characters A-Z and 2-7, in groups of 4)")
    return kind, base64.b32decode(s + "=" * (-len(s) % 8))


def org_key(h, parsed):
    """The organisation key: the earlier format is the key; a recovery secret opens the header's recovery_wrapped
    (AES-256-GCM under HKDF-SHA256(secret, info "kalmido-orgkey-recovery-v1"), AAD binds the organisation)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    kind, b = parsed
    if kind == "key":
        return b
    w = str(h.get("recovery_wrapped") or "")
    if not w.startswith("r1."):
        raise Bad("this archive was made before the recovery key was set up: use the recovery key of that time")
    try:
        raw = base64.urlsafe_b64decode(w[3:] + "=" * (-len(w[3:]) % 4))
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-orgkey-recovery-v1").derive(b)
        return AESGCM(k).decrypt(raw[:12], raw[12:], b"kalmido-orgkey-recovery|%d" % int(h["org_id"]))
    except (InvalidTag, ValueError, KeyError, TypeError):
        raise Bad("wrong recovery key (or the archive belongs to another organisation, or the key was renewed since)") from None


def read_header(f):
    if f.read(len(MAGIC)) != MAGIC:
        raise Bad("not a Kalmido organisation export")
    raw = f.read(4)
    if len(raw) != 4:
        raise Bad("the file is cut off")
    n = struct.unpack(">I", raw)[0]
    if n > 1 << 20:
        raise Bad("damaged header")
    head = f.read(n)
    if len(head) != n:
        raise Bad("the file is cut off")
    try:
        h = json.loads(head.decode("utf-8"))
    except ValueError:
        raise Bad("damaged header") from None
    if h.get("format") != "kalmido-org-export" or h.get("v") != 1 or h.get("alg") != "AES-256-GCM":
        raise Bad("unknown archive format or version (a newer Kalmido? update this tool)")
    return h, hashlib.sha256(MAGIC + raw + head).digest()


def decrypt(src, dst, key):
    """Writes the plain ZIP of src to dst; returns the header. Bad on a wrong key or a damaged file (dst is removed)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as f:
        h, hh = read_header(f)
        try:
            w = base64.b64decode(h["wrapped_fk"])
            prefix = base64.b64decode(h["nonce_prefix"])
            block = int(h["block"])
            fk = AESGCM(org_key(h, key) if isinstance(key, tuple) else key).decrypt(w[:12], w[12:], FK_AAD + str(int(h["org_id"])).encode())
        except InvalidTag:
            raise Bad("wrong recovery key (or the archive belongs to another organisation)") from None
        except (KeyError, ValueError, TypeError):
            raise Bad("damaged header") from None
        if len(prefix) != 8 or not 0 < block <= 1 << 26:
            raise Bad("damaged header")
        aes, i = AESGCM(fk), 0
        cur = f.read(block + TAG)
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        ok = False
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    if len(cur) < TAG:
                        raise Bad("the file is cut off")
                    nxt = f.read(block + TAG) if len(cur) == block + TAG else b""
                    last = not nxt
                    try:
                        out.write(aes.decrypt(prefix + struct.pack(">I", i), cur, hh + struct.pack(">QB", i, 1 if last else 0)))
                    except InvalidTag:
                        raise Bad(f"block {i} is damaged, missing or out of order (or the file is cut off)") from None
                    if last:
                        break
                    cur, i = nxt, i + 1
            ok = True
        finally:
            if not ok and os.path.exists(dst):
                os.remove(dst)
    return h


def verify(zpath):
    """Checks every entry of the ZIP against manifest.json; returns (manifest, number of checked entries)."""
    with zipfile.ZipFile(zpath) as z:
        try:
            man = json.loads(z.read("manifest.json"))
        except (KeyError, ValueError):
            raise Bad("manifest.json is missing or damaged") from None
        names = set(z.namelist()) - {"manifest.json"}
        listed = set(man.get("files", {})) - {"manifest.json"}
        if names != listed:
            raise Bad("the archive's entries do not match its manifest")
        for name in sorted(listed):
            h = hashlib.sha256()
            with z.open(name) as r:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != man["files"][name].get("sha256"):
                raise Bad(f"checksum of {name} does not match")
    return man, len(listed)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Open a Kalmido organisation export with the organisation's recovery key.")
    ap.add_argument("archive")
    ap.add_argument("-o", "--out", required=True, help="the ZIP to write")
    ap.add_argument("--key-file", help="file with the recovery key (default: stdin)")
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        print(f"{a.out} exists already: choose another name", file=sys.stderr)
        return 2
    try:
        if a.key_file:
            with open(a.key_file, encoding="utf-8") as f:
                text = f.read()
        elif sys.stdin.isatty():
            text = getpass.getpass("Recovery key of the organisation: ")
        else:
            text = sys.stdin.read()
        key = parse_key(text)
        h = decrypt(a.archive, a.out, key)
        try:
            man, n = verify(a.out)
        except (Bad, zipfile.BadZipFile) as e:
            os.remove(a.out)
            raise Bad(str(e)) from None
    except Bad as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e.strerror}: {e.filename}", file=sys.stderr)
        return 1
    print(f"ok: {h.get('org')!s} (organisation {h.get('org_id')}), created {h.get('created_at')} with Kalmido "
          f"{h.get('kalmido_version')}; {n} entries checked -> {a.out}")
    enc = man.get("client_encrypted") or {}
    if enc.get("attachments") or enc.get("task_notes"):
        print(f"note: {len(enc.get('attachments') or [])} attachments and {enc.get('task_notes') or 0} task notes were encrypted "
              "in the browser by their authors and stay ciphertext (see manifest.json)")
    if enc.get("locked_lists"):  # 2.64.1 B (#1817)
        print(f"note: {enc['locked_lists']} lists are encrypted in the browser: their texts (values starting with e2e1:) stay "
              "ciphertext and can only be read in Kalmido with a member's own passphrase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
