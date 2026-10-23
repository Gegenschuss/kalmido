#!/usr/bin/env python3
"""2.45.0 (#1515, review): the server key file (KALMIDO_SECRET_FILE) without a server: created once with mode 0600 and
reused, a byte order mark tolerated, a file that is no text or a dangling symlink gives a clear problem instead of a
crash at start. Runs the key functions of kalmido/core/config.py on their own (no database needed)."""
import base64, os, secrets, stat, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "kalmido", "core", "config.py"), encoding="utf-8").read()
PART = SRC[SRC.index("def _secret_key_parse"):SRC.index("\nSECRET_KEY, SECRET_KEY_PROBLEM")]
sys.path.insert(0, HERE)
from kt import FAILS, check  # 2.206.0 (#2762): shared helpers (tests/kt.py)


def load(path, data):
    os.environ["KALMIDO_SECRET_FILE"] = path
    g = {"os": os, "sys": sys, "base64": base64, "secrets": secrets, "DB": os.path.join(data, "tasks.db")}
    exec(PART, g)
    k, p = g["sh_secret_file"]()
    return k, p, g["SECRET_KEY_SRC"]


with tempfile.TemporaryDirectory() as t:
    data = os.path.join(t, "data"); os.mkdir(data)
    new = os.path.join(t, "secret", "kalmido.key")
    k1, p, src = load(new, data)
    check(k1 is not None and len(k1) == 32 and p == "" and src == "file", "a missing key file is created")
    check(stat.S_IMODE(os.stat(new).st_mode) == 0o600, "the key file has mode 0600")
    k2, _, _ = load(new, data)
    check(k2 == k1, "the second start reuses the key")
    bom = os.path.join(t, "bom.key")
    with open(bom, "w", encoding="utf-8-sig") as f:
        f.write(base64.b64encode(os.urandom(32)).decode() + "\n")
    k, p, _ = load(bom, data)
    check(k is not None and p == "", "a byte order mark (editor) is tolerated")
    binf = os.path.join(t, "bin.key")
    with open(binf, "wb") as f:
        f.write(b"\xff\xfe\x00bad")
    k, p, _ = load(binf, data)
    check(k is None and p == "invalid", "a file that is no text: problem invalid, no crash")
    dang = os.path.join(t, "dang.key")
    os.symlink(os.path.join(t, "nowhere", "x"), dang)
    k, p, _ = load(dang, data)
    check(k is None and p == "file_error", "a dangling symlink: problem file_error, no endless retry")
    k, p, _ = load(os.path.join(data, "kalmido.key"), data)
    check(k is None and p == "file_in_data", "a key file inside the data folder is ignored")

print(f"{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
