#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.662.0 B (#4939): the encryption passes' way back and the private documents' previews. Own container with a server key
(the start pass waits, KALMIDO_ORGCRYPT_DELAY=600); a helper process inside the container runs the passes with a fixed order
of events (no timing). Invented names only.
freelancer-matrix: docs
 - (1) decrypt-private: a budget row and a private knowledge text that change between the pass's read and its write stay
   sealed -- counted as failed (budget_failed / wiki_failed, and in failed) instead of left silently (were 0)
 - (2) docs_thumbs_open (decrypt-all's part for the previews of header 0) runs in portions over node_id and leaves a preview
   that was replaced between its read and its write as it is (was: overwritten with the old picture)
 - (3) a private preview made while private_encrypt is off is stored plain (was: sealed with header 0); on again: sealed
usage: p2662_b_crypt_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import FAILS, OKS, check, sess, until  # noqa: E402
from kt import docker_logs_on_first_fail  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

docker_logs_on_first_fail()
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
JPEG = b"\xff\xd8"


def in_ct(code):
    """Python inside the app container; the last stdout line is JSON."""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def text_pdf(line):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 60 740 Td ({line}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


# ---------------------------------------------------------------- setup: a server key, encryption on
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=600 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr


def healthy():
    try:
        return requests.get(B + "/api/health", timeout=2).ok
    except requests.RequestException:
        return False


check(until(healthy, 30), "setup: the server answers")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,files,docs", "tour": "done"})
FID, Fr = freelancer(B, A)
r = A.post(B + "/api/users", json={"orgs": [], "username": "paula", "display_name": "Paula Example", "password": "password123"})
assert r.ok, r.text
PID = r.json()["id"]

BASE = """import io, json, os
from kalmido.core.db import connect, gset
from kalmido.core.pg import system_ctx
from kalmido.core.config import ATT_DIR
from kalmido.core import orgcrypt as oc
from kalmido.admin import orgcrypt_cli as cli
c, c2 = connect(), connect()
def setting(k, v):
    with system_ctx(c):
        gset(c, k, v)
    c.commit()
"""
in_ct(BASE + "setting('org_encrypt', '1')\nsetting('private_encrypt', '1')\nsetting('wiki_encrypt', '1')\nprint(json.dumps({}))")


def upload(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(name), "application/pdf"))])
    check(r.status_code == 201 and r.json().get("ids"), f"setup: upload {name} ({r.status_code} {r.text[:150]})")
    return r.json()["ids"][0]


DOCS = {"f1": upload(Fr, "private", "Frida Rechnung"), "f2": upload(Fr, "private", "Frida Beleg")}
for k, nid in DOCS.items():  # the recognition first (it may write a preview of its own)
    st = until(lambda: (lambda r: r.ok and r.json()["state"] in ("done", "failed"))(Fr.get(B + f"/api/docs/{nid}")), 120)
    check(st, f"setup: {k} recognised")

DOC = BASE + f"""from kalmido.docs import store as S
from PIL import Image
DOCS = {json.dumps(DOCS)}
def png():
    b = io.BytesIO()
    Image.new("RGB", (900, 600), (30, 30, 200)).save(b, "PNG")
    return b.getvalue()
def make(k):  # the preview of the document as the recognition writes it (docs/store.py thumb_store)
    with system_ctx(c):
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (DOCS[k],)).fetchone()
        S.thumb_store(c, S.meta_row(c, DOCS[k]), node, png(), "image")
    c.commit()
def rel(k):
    with system_ctx(c):
        m = c.execute("SELECT thumb FROM doc_meta WHERE node_id=?", (DOCS[k],)).fetchone()
    c.commit()
    return os.path.join(ATT_DIR, m["thumb"])
def head(k):
    h = cli._head(rel(k)) or b""
    return oc.oc_file_org(h) if h[:len(oc.MAGIC)] == oc.MAGIC else "plain"
"""


def route_ok(k):
    r = Fr.get(B + f"/api/docs/{DOCS[k]}/thumb")
    return r.status_code == 200 and r.content[:2] == JPEG


# ---------------------------------------------------------------- (2) docs_thumbs_open: portions, a replaced preview stays
r = in_ct(DOC + """make('f1')
make('f2')
before = {k: head(k) for k in DOCS}
cli.BATCH = 1  # one row per portion: both previews still opened (the paging over node_id)
p1, orig, done = rel('f1'), S.thumb_read, []
def replace_between(k, ws, path):  # the pass read the preview: a new one replaces it (another file at the same path)
    data = orig(k, ws, path)
    if path == p1 and not done:
        done.append(1)
        with open(p1 + ".new", "wb") as f:
            f.write(b"replacement")
        os.replace(p1 + ".new", p1)
    return data
S.thumb_read = replace_between
n, bad = cli.docs_thumbs_open(c)
with open(p1, "rb") as f:
    kept = f.read() == b"replacement"
print(json.dumps({"before": before, "hooked": bool(done), "n": n, "bad": bad, "kept": kept, "f2": head('f2')}))""")
check(r["before"] == {"f1": 0, "f2": 0}, f"setup: two private previews of header 0 {r}")
check(r["hooked"], f"setup: the preview was replaced while the pass ran {r}")
check(r["kept"], f"#4939 (2): the replaced preview stays as it is (was overwritten with the old picture) {r}")
check(r["f2"] == "plain" and r["n"] == 1 and r["bad"] == 0, f"#4939 (2): the next portion's preview is opened (paging over node_id) {r}")
check(route_ok("f2"), "#4939 (2): the opened preview still answers with the picture")

# ---------------------------------------------------------------- (1) the way back counts rows it could not write
Pa = sess("paula")
Pa.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,budget,wiki", "tour": "done"})
PL = Pa.post(B + "/api/budget/lists", json={}).json().get("list_id")
e = Pa.post(B + f"/api/budget/{PL}/entries", json={"day": "2026-09-04", "amount": 12, "kind": "out", "title": "Brushes"})
check(e.ok, f"setup: paula's budget entry {e.status_code} {e.text[:150]}")
r = Pa.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notiz", "body": "Plain text"})
check(r.status_code == 201, f"setup: paula's private page {r.status_code} {r.text[:150]}")
PG = r.json().get("id")

BUD = BASE + f"""from kalmido.life import budget as bud
from kalmido.wiki import wkhist
PL, PID, PG = {PL}, {PID}, {PG}
def sealed():
    with system_ctx(c):
        e = c.execute("SELECT sid FROM budget_entries WHERE list_id=?", (PL,)).fetchone()
        p = c.execute("SELECT body FROM wiki_pages WHERE id=?", (PG,)).fetchone()
    c.commit()
    return {{"entry": int(e["sid"] or 0), "page": oc.oc_is_enc(p["body"])}}
"""
r = in_ct(BUD + "wkhist.wkh_settle(c)\nprint(json.dumps(sealed()))")
check(r == {"entry": -PID, "page": True}, f"setup: paula's entry and page sealed for her account {r}")

r = in_ct(BUD + """bo, wo, done = bud.bud_dec, wkhist.oc_dec_k, []
def edit_entry(k, table, row):  # right after the pass read the row: an edit commits (still sealed, another day)
    if table == "budget_entries" and "b" not in done:
        done.append("b")
        with system_ctx(c2):
            c2.execute("UPDATE budget_entries SET day='2026-09-05' WHERE list_id=?", (PL,))
        c2.commit()
    return bo(k, table, row)
def edit_page(key, sid, ctx, v):  # the pass read the text: a save commits a new sealed text
    if "w" not in done and ctx == wkhist.WKH_CTX:
        done.append("w")
        with system_ctx(c2):
            c2.execute("UPDATE wiki_pages SET body=? WHERE id=?", (wkhist._seal(key, sid, ctx, "Changed text"), PG))
        c2.commit()
    return wo(key, sid, ctx, v)
bud.bud_dec, wkhist.oc_dec_k = edit_entry, edit_page
d = cli.decrypt_private(c)
bud.bud_dec, wkhist.oc_dec_k = bo, wo
print(json.dumps({"done": sorted(done), "d": d, **sealed()}))""")
check(r["done"] == ["b", "w"], f"setup: the entry and the page changed while the way back ran {r}")
check(r["entry"] == -PID and r["page"], f"setup: both stay sealed (compare and set) {r}")
check(r["d"].get("budget_failed") == 1, f"#4939 (1): the budget row left sealed is counted (was silent) {r['d']}")
check(r["d"].get("wiki_failed") == 1, f"#4939 (1): the knowledge text left sealed is counted like a text that does not open {r['d']}")
check(r["d"]["failed"] >= 2, f"#4939 (1): decrypt-private fails the run (exit 1) {r['d']}")
r = in_ct(BUD + "d = cli.decrypt_private(c)\nprint(json.dumps({'d': d, **sealed()}))")
check(r["entry"] == 0 and not r["page"] and not r["d"]["failed"], f"#4939 (1): a second run opens both, nothing failed {r}")

# ---------------------------------------------------------------- (3) private_encrypt off: new private previews plain
r = in_ct(DOC + "make('f1')\noff = head('f1')\nsetting('private_encrypt', '1')\nmake('f2')\nprint(json.dumps({'off': off, 'on': head('f2')}))")
check(r["off"] == "plain", f"#4939 (3): a preview made while private_encrypt is off is stored plain (was header 0) {r}")
check(r["on"] == 0, f"#4939 (3): private_encrypt on again: sealed with the space's derived key {r}")
check(route_ok("f1") and route_ok("f2"), "#4939 (3): both previews answer with the picture")

print(f"p2662_b: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
