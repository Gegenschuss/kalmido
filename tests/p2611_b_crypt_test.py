#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.611.0 B (#4884, #4865): the encryption passes and the documents' preview images, the background passes next to edits.
Own container with a server key (the start pass waits, KALMIDO_ORGCRYPT_DELAY=600); a helper process inside the container runs
the passes with a fixed order of events (no timing). Invented names only.
freelancer-matrix: docs
 - #4884: an organisation without a key (encryption off) and a person without an organisation have documents with a preview
   (doc_meta.thumb, and thumb_l where this database has it): encrypt-org / the start pass seal the previews (were left plain),
   decrypt-private opens the person's, decrypt-all opens every one (also a private one of header 0, sealed with the space's
   derived key) and the preview route still answers with the picture. Counter-check in the same run: the passes without the
   preview entries leave them plain
 - #4865 budget: a list a running transaction holds is queued again (orgcrypt:settle, a bounded number of times) and that row
   finishes it; an entry edited between the pass's read and its write keeps the edit (was overwritten with the values read)
 - #4865 knowledge pages: a page moved to another space between the pass's read and its write (text unchanged) is not sealed
   with the old space's key (was: unreadable in the new one); the next pass seals it for the new space
 - #4865 files: a file deleted between the pass's read and its write does not come back on the disk
usage: p2611_b_crypt_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

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


# ---------------------------------------------------------------- setup: a server key, encryption off for now
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
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,files,docs", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)
ids = {}
for u, n in (("bob", "Bob Member"), ("paula", "Paula Example")):
    r = A.post(B + "/api/users", json={"orgs": [], "username": u, "display_name": n, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]

BASE = """import io, json, os, threading, time
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
in_ct(BASE + "setting('org_encrypt', '0')\nprint(json.dumps({}))")  # the organisation has no key yet (nothing sealed)


def upload(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(name), "application/pdf"))])
    check(r.status_code == 201 and r.json().get("ids"), f"setup: upload {name} ({r.status_code} {r.text[:150]})")
    return r.json()["ids"][0]


DOCS = {"org": upload(A, f"org:{ORG}", "Alpha Vertrag"), "f1": upload(Fr, "private", "Frida Rechnung"),
        "f2": upload(Fr, "private", "Frida Beleg")}
OWNER = {"org": A, "f1": Fr, "f2": Fr}
for k, nid in DOCS.items():  # the recognition first (it may write a preview of its own)
    st = until(lambda: (lambda r: r.ok and r.json()["state"] in ("done", "failed"))(OWNER[k].get(B + f"/api/docs/{nid}")), 120)
    check(st, f"setup: {k} recognised")

DOC = BASE + f"""from kalmido.docs import store as S
from PIL import Image
DOCS = {json.dumps(DOCS)}
def png():
    b = io.BytesIO()
    Image.new("RGB", (900, 600), (200, 30, 30)).save(b, "PNG")
    return b.getvalue()
def make(k):  # the preview(s) of the document as the recognition writes them (docs/store.py thumb_store)
    with system_ctx(c):
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (DOCS[k],)).fetchone()
        S.thumb_store(c, S.meta_row(c, DOCS[k]), node, png(), "image")
    c.commit()
def heads(cols=None):  # {{"org.thumb": header id | "plain"}}
    out = {{}}
    for k, nid in DOCS.items():
        with system_ctx(c):
            m = c.execute("SELECT * FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
        c.commit()
        for col in cols or cli._thumb_cols(c):
            if m[col]:
                h = cli._head(os.path.join(ATT_DIR, m[col])) or b""
                out[k + "." + col] = oc.oc_file_org(h) if h[:len(oc.MAGIC)] == oc.MAGIC else "plain"
    return out
"""


def of(h, k):
    """The header ids of document k's previews (thumb, thumb_l where present)."""
    return [v for x, v in h.items() if x.split(".")[0] == k]


def route_ok(k):
    r = OWNER[k].get(B + f"/api/docs/{DOCS[k]}/thumb")
    return r.status_code == 200 and r.content[:2] == JPEG


# ---------------------------------------------------------------- #4884: previews made while encryption is off
h = in_ct(DOC + "make('org')\nmake('f1')\nprint(json.dumps({'h': heads(), 'cols': cli._thumb_cols(c)}))")
COLS = h["cols"]
print("NOTE: preview columns of this database:", COLS, flush=True)
h = h["h"]
check("org.thumb" in h and "f1.thumb" in h and set(of(h, "org") + of(h, "f1")) == {"plain"}, f"setup: two plain previews {h}")
check(len(of(h, "org")) == len(COLS), f"setup: every preview column of the document filled {h} {COLS}")

# ---------------------------------------------------------------- #4884: encrypting seals them
r = in_ct(DOC + """setting('org_encrypt', '1')
keep_cols, keep_sql = cli._thumb_cols, cli.SPACE_SQL
cli._thumb_cols = lambda k: ()  # the counter-check: the passes as before 2.611 (no preview entries)
cli.SPACE_SQL = tuple(x for x in keep_sql if not x[0].startswith("doc_meta"))
cli.encrypt_org(c, %d)
cli.files_settle(c)
cli._thumb_cols, cli.SPACE_SQL = keep_cols, keep_sql
before = heads()
e = cli.encrypt_org(c, %d)
s = cli.files_settle(c)
after = heads()
make('f2')  # a private preview made while encryption is on: sealed with the space's derived key (header 0)
print(json.dumps({"before": before, "after": heads(), "e": e, "s": s}))""" % (ORG, ORG))
check(set(of(r["before"], "org") + of(r["before"], "f1")) == {"plain"}, f"#4884 counter-check: without the preview entries both stay plain {r['before']}")
check(set(of(r["after"], "org")) == {ORG}, f"#4884: encrypt-org seals the organisation's previews with its key {r}")
check(set(of(r["after"], "f1")) == {-FID}, f"#4884: the start pass seals the private previews with the person's account key (freelancer) {r}")
check(set(of(r["after"], "f2")) == {0}, f"setup: a private preview made now has header 0 {r['after']}")
for k in DOCS:
    check(route_ok(k), f"#4884: the preview route answers with the picture ({k}, sealed)")

# ---------------------------------------------------------------- #4884: the ways back
r = in_ct(DOC + "d = cli.decrypt_private(c)\nprint(json.dumps({'h': heads(), 'd': d}))")
check(set(of(r["h"], "f1")) == {"plain"}, f"#4884: decrypt-private opens the person's previews {r}")
check(set(of(r["h"], "org")) == {ORG} and set(of(r["h"], "f2")) == {0}, f"#4884: the organisation's stay sealed, header 0 keeps its own form {r}")
check(not r["d"]["failed"], f"#4884: no preview counted as failed (header 0 is skipped) {r['d']}")
check(route_ok("f1") and route_ok("f2"), "#4884: the person's previews still answer after decrypt-private")
r = in_ct(DOC + "setting('private_encrypt', '1')\ncli.files_settle(c)\nprint(json.dumps({'h': heads()}))")
check(set(of(r["h"], "f1")) == {-FID}, f"#4884: private encryption on again seals them again {r}")
r = in_ct(DOC + "d = cli.decrypt_all(c)\nprint(json.dumps({'h': heads(), 'd': d}))")
check(set(r["h"].values()) == {"plain"}, f"#4884: decrypt-all opens every preview, header 0 too (were left sealed) {r}")
check(not r["d"]["failed"], f"#4884: decrypt-all without failures {r['d']}")
for k in DOCS:
    check(route_ok(k), f"#4884: the preview route answers after decrypt-all ({k})")

# ---------------------------------------------------------------- #4865: paula's budget project and private page, sealed
in_ct(BASE + "setting('org_encrypt', '1')\nprint(json.dumps({}))")
Pa = sess("paula")
Pa.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,budget,wiki", "tour": "done"})
PL = Pa.post(B + "/api/budget/lists", json={}).json().get("list_id")
e = Pa.post(B + f"/api/budget/{PL}/entries", json={"day": "2026-09-04", "amount": 12, "kind": "out", "title": "Brushes"}).json()
check(Pa.post(B + f"/api/budget/entries/{e['id']}/files", files=[("file", ("receipt.txt", b"kept", "text/plain"))]).ok, "setup: paula's project receipt")
r = Pa.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notiz", "body": "Plain text"})
check(r.status_code == 201, f"setup: paula's private page {r.status_code} {r.text[:150]}")
PG = r.json().get("id")

BUD = BASE + f"""from kalmido.life import budget as bud
from kalmido.wiki import wkhist
PL, PID, BOB, PG = {PL}, {ids["paula"]}, {ids["bob"]}, {PG}
calls = []
cli.bgj_add = lambda kind, *a, **k: calls.append([kind, list(a), k.get("delay")])  # what would be queued
def rpath(k):
    with system_ctx(k):
        return os.path.join(ATT_DIR, k.execute("SELECT path FROM budget_files WHERE list_id=?", (PL,)).fetchone()[0])
def state(k):
    with system_ctx(k):
        rows = k.execute("SELECT * FROM budget_entries WHERE list_id=?", (PL,)).fetchall()
    path = rpath(k)
    k.commit()
    return {{"sids": [int(r["sid"] or 0) for r in rows], "titles": [bud.bud_dec(k, "budget_entries", r)["title"] for r in rows],
            "file": oc.oc_file_org(cli._head(path) or b"") if os.path.exists(path) else "gone", "path": path}}
def owner(k, to, commit=True):
    with system_ctx(k):
        k.execute("UPDATE lists SET owner_id=? WHERE id=?", (to, PL))
    if commit:
        k.commit()
"""
s = in_ct(BUD + "print(json.dumps(state(c)))")
check(s["sids"] == [-ids["paula"]] and s["file"] == -ids["paula"] and s["titles"] == ["Brushes"], f"setup: sealed for paula's account {s}")

# ---------------------------------------------------------------- #4865: a busy list is queued again, bounded
r = in_ct(BUD + """owner(c2, BOB, commit=False)  # a request hands the list to bob, not committed yet
n = cli.bud_settle_again(c, list_ids=[PL])
mid = state(c)
c2.commit()
first = list(calls)
if calls:
    cli.oc_settle_lists(*calls[0][1])  # what the queue's worker runs
end = state(c)
calls.clear()
owner(c2, PID, commit=False)  # busy again, but queued often enough already: no new row (no loop)
cli.bud_settle_again(c, list_ids=[PL], again=cli.OC_SETTLE_AGAIN)
c2.rollback()
print(json.dumps({"n": n, "mid": mid["sids"], "first": first, "bound": calls, **end}))""")
check(r["n"] == 0 and r["mid"] == [-ids["paula"]], f"#4865: the busy list is left to its transaction {r}")
check(len(r["first"]) == 1 and r["first"][0][0] == "orgcrypt:settle" and r["first"][0][1] == [[PL], 1] and r["first"][0][2] >= 30,
      f"#4865: and queued again (orgcrypt:settle, the first time again, not at once) {r['first']}")
check(r["sids"] == [-ids["bob"]] and r["titles"] == ["Brushes"] and r["file"] == -ids["bob"], f"#4865: that row reseals it for bob {r}")
check(r["bound"] == [], f"#4865: after OC_SETTLE_AGAIN times no further row {r['bound']}")

# ---------------------------------------------------------------- #4865: an edit between the read and the write stays
r = in_ct(BUD + """owner(c2, PID)  # handed back to paula (committed): the pass moves the rows
orig, done = bud.bud_dec, []
def edit_between(k, table, row):  # right after the pass read the row: an edit commits (same space, other content)
    if table == "budget_entries" and not done:
        done.append(1)
        enc, sid = bud.bud_enc(c2, "budget_entries", -BOB, {"title": "Edited"})
        with system_ctx(c2):
            c2.execute("UPDATE budget_entries SET title=? WHERE list_id=?", (enc["title"], PL))
        c2.commit()
    return orig(k, table, row)
bud.bud_dec = edit_between
n = cli.bud_settle_again(c, list_ids=[PL])
bud.bud_dec = orig
mid = state(c)
first = list(calls)
if calls:
    cli.oc_settle_lists(*calls[0][1])
print(json.dumps({"n": n, "mid": mid, "first": first, **state(c)}))""")
check(r["mid"]["titles"] == ["Edited"], f"#4865: the edit between the read and the write stays (was overwritten with 'Brushes') {r['mid']}")
check(len(r["first"]) == 1, f"#4865: the list is queued again for the row it could not write {r['first']}")
check(r["sids"] == [-ids["paula"]] and r["titles"] == ["Edited"], f"#4865: that row seals the edited entry for paula {r}")

# ---------------------------------------------------------------- #4865: a page moved between the read and the write
r = in_ct(BUD + """setting('wiki_encrypt', '1')
orig, done = wkhist.oc_key, []
def move_between(k, sid, create=True):  # the pass read the page and asks for paula's key: the page goes to bob (text unchanged)
    if sid == -PID and not done:
        done.append(1)
        with system_ctx(c2):
            c2.execute("UPDATE wiki_pages SET owner_id=? WHERE id=?", (BOB, PG))
        c2.commit()
    return orig(k, sid, create=create)
wkhist.oc_key = move_between
one = wkhist.wkh_settle(c)
wkhist.oc_key = orig
def page():
    with system_ctx(c):
        row = c.execute("SELECT id, org_id, owner_id, body FROM wiki_pages WHERE id=?", (PG,)).fetchone()
    c.commit()
    try:
        txt = wkhist.wkh_body(c, row)
    except Exception as e:
        txt = "unreadable: " + type(e).__name__
    return {"sealed": oc.oc_is_enc(row["body"]), "text": txt, "owner": row["owner_id"]}
mid = page()
two = wkhist.wkh_settle(c)
print(json.dumps({"hooked": bool(done), "mid": mid, "end": page()}))""")
check(r["hooked"] and r["mid"]["owner"] == ids["bob"], f"setup: the page moved to bob while the pass ran {r}")
check(r["mid"]["text"] == "Plain text", f"#4865: the moved page is not sealed with paula's key (was unreadable for bob) {r['mid']}")
check(r["end"]["sealed"] and r["end"]["text"] == "Plain text", f"#4865: the next pass seals it for bob {r['end']}")

# ---------------------------------------------------------------- #4865: a file deleted between the read and the write
r = in_ct(BUD + """owner(c2, BOB)  # the receipt has to be resealed for bob
path = rpath(c)
orig, done = oc.oc_seal_raw, []
def delete_between(*a, **k):  # the pass read the file: a deletion removes it now
    if not done:
        done.append(1)
        os.remove(path)
    return orig(*a, **k)
oc.oc_seal_raw = delete_between
out = cli.files_settle(c, list_ids=[PL])
oc.oc_seal_raw = orig
print(json.dumps({"hooked": bool(done), "out": out, "exists": os.path.exists(path)}))""")
check(r["hooked"], f"setup: the file went while the pass ran {r}")
check(not r["exists"] and r["out"]["resealed"] == 0, f"#4865: the deleted file does not come back on the disk {r}")

print(f"p2611_b: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
