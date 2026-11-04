#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.523.0 (#4073): resource limits from the security audit, own container (start.sh). Invented data only.
 (a) the credit card reader (office/ccread.py): a line of a million digits in the text layer is read at once (the old amount
     pattern took hours on it), a line over 400 characters is cut before the patterns, text after 2 MB is not read;
     an ordinary statement is read as before
 (b) MT940 (core/mt940.py): 600,000 continuation lines of one field are joined in file order, at once (the old string
     concatenation copied the field per line)
 (c) the booking archive (office/bookarch.py): the files of one upload share one cap (413 when two files together pass it,
     each alone would fit); an archive run older than 24 hours cannot be undone (409), a younger one can
 (d) the file preview GET /api/files/nodes/<id>/thumb as a person WITHOUT an organisation: 60 per minute, the 61st is 429;
     another person's previews are not counted with hers
Each "at once" is a generous cap (minutes) on a real end state, no timing measurement: the old code does not end in it.
usage: p2523_b_limits_test.py <datadir>
freelancer-matrix: files"""
import json
import os
import struct
import subprocess
import sys
import time
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)


def pyrun(code, timeout):
    """Runs code in the app container (the app's own modules, a request context for the texts) -> the JSON it prints last,
    or {"timeout": True} when it does not end within `timeout` seconds."""
    head = "import json, io\nimport app as _app\nfrom kalmido.core.config import app as F\n"
    try:
        p = subprocess.run(["docker", "exec", "-i", CT, "python", "-"], input=head + code, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"timeout": True}
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"error": (p.stdout + p.stderr)[-1500:]}


# ---------------------------------------------------------------- (a) the credit card reader
STMT = ("Kreditkartenabrechnung Mastercard\nAbrechnungsdatum 31.10.2026\nKartennummer 5232 xxxx xxxx 4711\n"
        "02.10. 03.10. Example Bookshop Berlin 12,34\n{mid}"
        "Neuer Saldo 12,34\n{tail}")
r = pyrun(f"""
from kalmido.office.ccread import ccr_mastercard
with F.test_request_context():
    a = ccr_mastercard({STMT!r}.format(mid="1" * 1000000 + "\\n", tail=""))
    b = ccr_mastercard({STMT!r}.format(mid="05.10. 05.10. " + "Very long shop name " * 30 + "9,99\\n", tail=""))
    pad = "Seite 1 von 1 " * 100 + "\\n"
    c = ccr_mastercard({STMT!r}.format(mid="", tail=pad * (2 * 1024 * 1024 // len(pad) + 10) + "06.10. 06.10. After the cap 5,00\\n"))
    d = ccr_mastercard({STMT!r}.format(mid="07.10. 08.10. Example Hotel Lisbon 1.234,56\\nUSD 1.300,00\\n04.10. Example Cafe 4,50\\n", tail=""))
print(json.dumps({{k: {{"total": str(v["total"]), "last4": v["last4"], "lines": [[x["day"], x["merchant"], str(x["amount"]), str(x["orig_amount"]), x["orig_currency"]] for x in v["lines"]]}}
                  for k, v in (("a", a), ("b", b), ("c", c), ("d", d))}}))
""", 180)
check(not r.get("timeout") and "a" in r, "(a) the reader ends on a line of a million digits " + str(r)[:300])
if "a" in r:
    check(r["a"]["lines"] == [["2026-10-02", "Example Bookshop Berlin", "12.34", "None", None]] and r["a"]["total"] == "12.34"
          and r["a"]["last4"] == "4711", "(a) beside it the statement is read as before " + str(r["a"]))
    check(len(r["b"]["lines"]) == 1, "(a) a line over 400 characters is cut before the patterns (its amount at the end is not read) " + str(r["b"])[:300])
    check([x[1] for x in r["c"]["lines"]] == ["Example Bookshop Berlin"], "(a) a position after 2 MB of text is not read " + str(r["c"])[:300])
    check(r["d"]["lines"] == [["2026-10-02", "Example Bookshop Berlin", "12.34", "None", None],
                              ["2026-10-07", "Example Hotel Lisbon", "1234.56", "1300.00", "USD"],
                              ["2026-10-04", "Example Cafe", "4.50", "None", None]],
          "(a) thousands groups, a foreign amount under its position and a short amount read as before " + str(r["d"]))

# ---------------------------------------------------------------- (b) MT940 continuation lines
r = pyrun("""
from kalmido.core.mt940 import _fields, mt_parse
lines = ["Purpose line %06d, invented" % i for i in range(600000)]
text = ":20:STARTUMS\\n:25:DE02120300000000202051\\n:28C:1/1\\n:60F:C261001EUR100,00\\n:61:2610011001D12,34NTRFNONREF\\n:86:" + lines[0] + "\\n" + "\\n".join(lines[1:]) + "\\n:62F:C261001EUR87,66\\n-\\n"
with F.test_request_context():
    f = _fields(text)
    small = mt_parse(":20:X\\n:25:DE02120300000000202051\\n:28C:1/1\\n:60F:C261001EUR100,00\\n:61:2610011001D12,34NTRFNONREF\\n:86:Rent\\nOctober\\nflat 3\\n:62F:C261001EUR87,66\\n-\\n")
v = dict((t, x) for t, x in f if t != "-")
print(json.dumps({"tags": [t for t, _x in f], "ok86": v.get("86") == "\\n".join(lines), "n86": len(v.get("86", "")), "small": json.dumps(small, default=str)[:2000]}))
""", 180)
check(not r.get("timeout") and r.get("tags") == ["20", "25", "28C", "60F", "61", "86", "62F", "-"], "(b) MT940 with 600,000 continuation lines ends, fields in order " + str(r)[:300])
check(r.get("ok86") is True, "(b) the continuation lines are joined in file order with a newline " + str(r.get("n86")))
check("Rent" in r.get("small", "") and "October" in r.get("small", ""), "(b) a short purpose of three lines is read as before " + r.get("small", str(r))[:300])

# ---------------------------------------------------------------- (c) the booking archive
r = pyrun("""
from datetime import timedelta
import kalmido.office.bookarch as ba
from kalmido.core.access import Denied
from kalmido.core.db import connect, iso, now_utc
out = {}
def up(cap, n):
    ba.BA_UPLOAD_MAX = cap
    files = [(io.BytesIO(bytes([65 + i]) * 600), "batch%d.csv" % i) for i in range(n)]
    with F.test_request_context("/api/office/books/archive/check", method="POST", data={"file": files}, content_type="multipart/form-data"):
        try:
            return [len(x[1]) for x in ba._uploads(True)]
        except Denied as e:
            return [e.code, e.msg]
out["fits"] = up(2000, 2)
out["two"] = up(1000, 2)       # each file alone fits, both together do not
ba.BA_UPLOAD_SLACK = 0
out["one"] = up(100, 1)        # the request alone is longer than the cap
c = connect()
def undo(hours):
    with F.test_request_context():
        try:
            ba.ba_undo(c, 987654321, 0, {"undone_at": None, "id": 0, "created_at": iso(now_utc() - timedelta(hours=hours)), "detail": "{}"})
            return "undone"
        except Denied as e:
            return [e.code, e.msg]
out["old"] = undo(25)
out["young"] = undo(23)
c.rollback()
c.close()
print(json.dumps(out))
""", 120)
check(r.get("fits") == [600, 600], "(c) two files under the shared cap are read " + str(r)[:300])
check((r.get("two") or [None])[0] == 413 and "too large together" in str(r.get("two")), "(c) two files that pass the cap together: 413 " + str(r.get("two")))
check((r.get("one") or [None])[0] == 413, "(c) one file longer than the cap: 413 " + str(r.get("one")))
check(r.get("old") and r["old"][0] == 409 and "24 hours" in r["old"][1], "(c) an archive run older than 24 hours: undo 409 " + str(r.get("old")))
check(r.get("young") == "undone", "(c) a run younger than 24 hours can be undone " + str(r.get("young")))

# ---------------------------------------------------------------- (d) the file preview
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A, "frida")
_GID, Gr = freelancer(B, A, "greta")


def png(w, h):
    raw = b"".join(b"\x00" + bytes((x * 7 + y * 3) & 255 for x in range(w * 3)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pic(s):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "collab,files,docs", "tour": "done"})
    folder = s.post(B + "/api/files/folders", json={"space": "private", "name": "Pictures"}).json()["id"]
    r = s.post(B + "/api/files/upload", data={"parent_id": str(folder)}, files={"file": ("dot.png", png(24, 24), "image/png")})
    assert r.status_code == 201, (r.status_code, r.text)
    return r.json()["items"][0]["id"]


FP, GP = pic(Fr), pic(Gr)
codes = [Fr.get(B + f"/api/files/nodes/{FP}/thumb?v=1").status_code for _i in range(60)]
check(codes == [200] * 60, f"(d) without an organisation: 60 previews in a minute are made ({sorted(set(codes))})")
r = Fr.get(B + f"/api/files/nodes/{FP}/thumb?v=1")
check(r.status_code == 429, f"(d) the 61st preview of the minute: 429 ({r.status_code})")
check(Gr.get(B + f"/api/files/nodes/{GP}/thumb?v=1").status_code == 200, "(d) another person's previews are not counted with hers")

print(f"p2523_b_limits: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
