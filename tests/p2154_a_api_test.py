#!/usr/bin/env python3
"""2.154.0 API tests, part A (#1111 #1356): documents -- a stack scan split by its archive number codes, a document linked
with an existing task, and who confirmed an agent's receipt suggestion. Own container (start.sh). Invented names only; every
PDF is drawn here (Pillow + segno in the test container: pages with QR codes, a blank page, a separator sheet).
freelancer-matrix: files  tenant-matrix: document
 - #1111 stack: a PDF with two archive number codes is marked "Stack - split?" (To review); the page scan finds the codes,
   the separator sheet, a blank page (only with text recognition); the proposed cuts: pages before the first code = own
   document, a page without a code joins the one before, the separator starts one and is dropped; previews of the pages;
   wrong parts 400; the split makes the documents (archive numbers from the codes, the first without one with its hint),
   the stack goes to the trash; undo brings it back (with its mark) and the parts go; split again works; "No stack" + undo;
   a PDF with one code is no stack; the separator sheet is a PDF
 - workspace boundary: another person / organisation 404 on the pages, previews, split, undo, dismiss
 - #1111 task link: a private document with a private task (the task shows it, the document the task's title), unlink;
   an organisation's document with a task of the organisation or a private one, a private document never with an
   organisation's task; a task I cannot see 404; a task's documents only those I see
 - #1356: the receipt of a document shows who confirmed the agent's suggestion until a person changes it
 - all of it as a person without organisation (freelancer-matrix)
usage: p2154_a_api_test.py <datadir>   (P2154A_NOSTART=1: the container runs already)"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,files"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


# pages: ["text", "qr:CONTENT\ntext", "" = blank]; drawn in the test container (segno + Pillow are in the image)
STACK_CODE = r"""
import base64, io, json, sys, segno
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=44)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    lines = spec.split('\n') if spec else []
    if lines and lines[0].startswith('qr:'):
        q = segno.make(lines.pop(0)[3:], micro=False)
        b = io.BytesIO()
        q.save(b, kind='png', scale=8, border=4)
        im.paste(Image.open(b).convert('L'), (1200, 100))
    for i, ln in enumerate(lines):
        d.text((150, 400 + i * 90), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
"""


def stack_pdf(pages):
    out = subprocess.run(["docker", "exec", CT, "python", "-c", STACK_CODE, json.dumps(pages)], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


def up(s, name, data, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid, secs=180):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def listed(s, ws="private"):
    r = s.get(B + "/api/docs", params={"ws": ws, "facets": "0", "limit": 200})
    return [d["id"] for d in r.json()["docs"]] if r.ok else []


def new_agent(admin, owner, org, name):
    r = admin.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title()})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    sql("DELETE FROM org_members WHERE user_id=?", (aid,), write=True)
    sql("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    return aid, tok(t)


if not os.environ.get("P2154A_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    key = base64.b64encode(os.urandom(32)).decode()
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={key}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
assert A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"}).ok
Ca = sess("carol")
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: files (her private documents)
OCR = "deu" in subprocess.run(["docker", "exec", CT, "tesseract", "--list-langs"], capture_output=True, text=True).stdout

# ================================================================ #1111 the stack (as the freelancer, private space)
PAGES = ["Deckblatt ohne Code\nBeispiel Sammlung", "qr:ASN00101\nRechnung Eins\nBeispiel Strom GmbH", "Seite zwei der Rechnung\nSumme 12,00 EUR",
         "", "qr:ASN00102\nVertrag Zwei\nBeispiel Versicherung AG", "qr:KALMIDO-SPLIT\nTrennblatt", "Brief Drei\nBeispiel Verein e.V."]
SID = up(Fr, "stapel.pdf", stack_pdf(PAGES))
d = done(Fr, SID)
check(d and d["state"] == "done" and d["pages"] == 7, f"stack recognised ({d and d['state']} {d and d['pages']})")
check(d and (d.get("split") or {}).get("stack") is True and d["review"], f"stack: marked 'Stack - split?' + To review ({d and d.get('split')})")
check(SID in [x["id"] for x in Fr.get(B + "/api/docs", params={"review": "1", "facets": "0"}).json()["docs"]], "stack: in To review")
card = [x for x in Fr.get(B + "/api/docs", params={"facets": "0"}).json()["docs"] if x["id"] == SID]
check(card and card[0].get("split", {}).get("stack") is True, "stack: the card in the list carries the mark")
j = Fr.get(B + f"/api/docs/{SID}/split").json()
scan = j.get("scan") or []
check(j.get("pages") == 7 and [p["asn"] for p in scan] == [None, 101, None, None, 102, None, None], f"page scan: codes ({[p.get('asn') for p in scan]})")
check([p["sep"] for p in scan] == [False, False, False, False, False, True, False], "page scan: the separator sheet")
check(j.get("starts") == [0, 1, 4, 6] and j.get("drop") == [5] and j.get("stack") is True and j.get("prefix") == "ASN",
      f"proposed cuts: cover page own, page 3 joins, separator dropped ({j.get('starts')} {j.get('drop')})")
if OCR:
    check([p["blank"] for p in scan] == [False, False, False, True, False, False, False], f"blank page found (ink + text) ({[p['blank'] for p in scan]})")
else:
    print("NOTE: no Tesseract in this image -- blank detection by ink only", flush=True)
    check(not any(p["blank"] for p in scan[:3]), "pages with text are never blank")
th = Fr.get(B + f"/api/docs/{SID}/split/thumbs?from=1").json().get("thumbs") or []
check(len(th) == 7 and all((t.get("src") or "").startswith("data:image/jpeg;base64,") for t in th), f"previews of all pages ({len(th)})")
sh = Fr.get(B + "/api/docs/split-sheet.pdf")
check(sh.ok and sh.content[:5] == b"%PDF-" and sh.headers.get("Content-Type", "").startswith("application/pdf"), "the separator sheet is a PDF")

# the boundary: another person / organisation sees nothing of it
for who, s in (("alice", A), ("carol", Ca)):
    check(s.get(B + f"/api/docs/{SID}/split").status_code == 404, f"{who}: the stack's pages 404")
    check(s.get(B + f"/api/docs/{SID}/split/thumbs").status_code == 404, f"{who}: previews 404")
    check(s.post(B + f"/api/docs/{SID}/split", json={"parts": [[1], [2]]}).status_code == 404, f"{who}: split 404")
    check(s.post(B + f"/api/docs/{SID}/split/dismiss", json={}).status_code == 404, f"{who}: dismiss 404")
    check(s.post(B + f"/api/docs/{SID}/unsplit").status_code == 404, f"{who}: undo 404")

# "No stack" and its undo
r = Fr.post(B + f"/api/docs/{SID}/split/dismiss", json={})
check(r.ok and not (doc(Fr, SID).get("split") or {}).get("stack"), "No stack: the mark goes")
r = Fr.post(B + f"/api/docs/{SID}/split/dismiss", json={"undo": True})
check(r.ok and (doc(Fr, SID).get("split") or {}).get("stack") is True and doc(Fr, SID)["review"], "No stack undone: the mark is back")

# wrong parts
for bad in ([[1, 2, 3, 4, 5, 6, 7]], [[2, 1], [3]], [[1], [1]], [[1], [99]], [[1], []], "x", [[1], ["2"]], [[3], [1]]):
    check(Fr.post(B + f"/api/docs/{SID}/split", json={"parts": bad}).status_code == 400, f"wrong parts refused: {bad}")

# split: cover page / 2+3 / 5 / 7 (blank page 4 and the separator 6 left out)
r = Fr.post(B + f"/api/docs/{SID}/split", json={"parts": [[1], [2, 3], [5], [7]]})
check(r.status_code == 201 and len(r.json().get("ids") or []) == 4, f"split: four documents ({r.status_code} {r.text[:160]})")
P = r.json().get("ids") or [] if r.status_code == 201 else []
ids = listed(Fr)
check(SID not in ids and all(p in ids for p in P), "split: the stack left the list, the parts are in it")
check(sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (SID,))[0][0] is not None, "split: the stack is in the trash")
check(Fr.post(B + f"/api/docs/{SID}/split", json={"parts": [[1], [2]]}).status_code == 404, "split twice: the stack is gone (404)")
if len(P) == 4:
    ds = [done(Fr, p) for p in P]
    check([x and x["pages"] for x in ds] == [1, 2, 1, 1], f"parts: pages {[x and x['pages'] for x in ds]}")
    check([x and x["asn"] for x in ds] == [None, 101, 102, None], f"parts: archive numbers from the codes {[x and x['asn'] for x in ds]}")
    check(ds[1] and ds[1]["auto"].get("asn") == "code", "parts: the number marked as read from the code")
    check(ds[0] and (ds[0].get("split") or {}).get("no_asn") is True and ds[0]["review"], f"the cover page: no archive number, with its hint ({ds[0] and ds[0].get('split')})")
    check(ds[3] and not (ds[3].get("split") or {}).get("no_asn"), "after the separator: no 'before the first code' hint")
    check(all(x and x["parent_id"] == d["parent_id"] for x in ds), "parts: in the stack's folder")
    check(all(x and not (x.get("split") or {}).get("stack") for x in ds), "parts: no stack mark")
    # undo
    r = Fr.post(B + f"/api/docs/{SID}/unsplit")
    check(r.ok, f"undo of the split ({r.status_code} {r.text[:120]})")
    ids = listed(Fr)
    check(SID in ids and not any(p in ids for p in P), "undo: the stack is back, the parts in the trash")
    check(all(x[0] is None for x in sql(f"SELECT asn FROM doc_meta WHERE node_id IN ({','.join('?' * len(P))})", tuple(P))), "undo: the parts gave their numbers up")
    check((doc(Fr, SID).get("split") or {}).get("stack") is True, "undo: the stack carries its mark again")
    check(Fr.post(B + f"/api/docs/{SID}/unsplit").status_code == 409, "undo twice: 409")
    # redo -- 2.154.0 E (#1111, A4): as a double click (two requests at once) it splits once
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(lambda _: Fr.post(B + f"/api/docs/{SID}/split", json={"parts": [[1], [2, 3], [5], [7]]}), range(2)))
    codes = sorted(x.status_code for x in rs)
    check(codes[0] == 201 and codes[1] in (404, 409), f"double split: once ({codes})")
    r = next((x for x in rs if x.status_code == 201), rs[0])
    check(r.status_code == 201, f"split again ({r.status_code} {r.text[:120]})")
    if r.status_code == 201:
        P2 = r.json()["ids"]
        ds = [done(Fr, p) for p in P2]
        check([x and x["asn"] for x in ds] == [None, 101, 102, None], f"split again: the numbers again {[x and x['asn'] for x in ds]}")

# one code only: no stack
OID = up(Fr, "einzeln.pdf", stack_pdf(["qr:ASN00300\nRechnung Einzeln", "Seite zwei Einzeln"]))
d1 = done(Fr, OID)
check(d1 and d1["asn"] == 300 and not (d1.get("split") or {}).get("stack"), f"one code: no stack mark ({d1 and d1.get('split')})")
j = Fr.get(B + f"/api/docs/{OID}/split").json()
check(j.get("stack") is False and j.get("starts") == [0], f"one code: split by hand possible, no cut proposed ({j.get('starts')})")
check(Ca.post(B + f"/api/docs/{OID}/split", json={"parts": [[1], [2]]}).status_code == 404, "carol: split of another's document 404")

# ================================================================ #1111 a document linked with an existing task
FIN = [x for x in Fr.get(B + "/api/state").json()["lists"] if x.get("is_inbox")][0]["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Strom bezahlen", "list_id": FIN}).json()["id"]
r = Fr.post(B + f"/api/docs/{OID}/task/link", json={"task_id": FT})
check(r.ok and r.json()["task"]["title"] == "Strom bezahlen" and r.json()["prev_task_id"] is None, f"freelancer: link with her task ({r.status_code} {r.text[:120]})")
check((doc(Fr, OID).get("task") or {}).get("id") == FT, "the document shows the task")
check([x["id"] for x in Fr.get(B + f"/api/tasks/{FT}/docs").json()["docs"]] == [OID], "the task shows the document")
check(Ca.get(B + f"/api/tasks/{FT}/docs").status_code == 404, "carol: nothing about another's task (2.161.0: 404)")
check(Fr.post(B + f"/api/docs/{OID}/task/link", json={"task_id": "x"}).status_code == 400, "link: a task id must be a number")
CL = Ca.post(B + "/api/lists", json={"name": "Beta Aufgaben", "org_id": ORG2}).json()["id"]
CT2 = Ca.post(B + "/api/tasks", json={"title": "Fremde Aufgabe", "list_id": CL}).json()["id"]
check(Fr.post(B + f"/api/docs/{OID}/task/link", json={"task_id": CT2}).status_code == 404, "link: a task I cannot see 404")
CD = up(Ca, "beta.pdf", stack_pdf(["Beta Brief"]), f"org:{ORG2}")
check(Ca.post(B + f"/api/docs/{CD}/task/link", json={"task_id": FT}).status_code == 404, "carol: her document with another's task 404")
check(Fr.post(B + f"/api/docs/{CD}/task/link", json={"task_id": FT}).status_code == 404, "freelancer: another organisation's document 404")
r = Fr.delete(B + f"/api/docs/{OID}/task")
check(r.ok and not doc(Fr, OID).get("task_id") and Fr.get(B + f"/api/tasks/{FT}/docs").json()["docs"] == [], "unlink: gone on both sides")
# the organisation: its own tasks and private ones, a private document never with an organisation's task
AL = A.post(B + "/api/lists", json={"name": "Alpha Aufgaben", "org_id": ORG}).json()["id"]
AT = A.post(B + "/api/tasks", json={"title": "Alpha Rechnung", "list_id": AL}).json()["id"]
AIN = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1 AND org_id IS NULL", (ALICE,))
APT = A.post(B + "/api/tasks", json={"title": "Privat merken", "list_id": AIN[0][0]}).json()["id"] if AIN else None
AD = up(A, "alpha.pdf", stack_pdf(["Alpha Brief"]), f"org:{ORG}")
APD = up(A, "privat.pdf", stack_pdf(["Privater Brief"]), "private")
check(A.post(B + f"/api/docs/{AD}/task/link", json={"task_id": AT}).ok, "an organisation's document with its task")
check(APT and A.post(B + f"/api/docs/{AD}/task/link", json={"task_id": APT}).ok, "an organisation's document with a private task")
check(A.post(B + f"/api/docs/{APD}/task/link", json={"task_id": AT}).status_code == 400, "a private document never with an organisation's task")
check(Ca.get(B + f"/api/tasks/{AT}/docs").status_code == 404, "carol: the documents of Alpha's task: nothing (2.161.0: 404)")

# ================================================================ #1356 who confirmed the agent's suggestion
FAG, FAGS = new_agent(A, FID, None, "fridabot")
check(Fr.post(B + f"/api/files/nodes/{OID}/shares", json={"agent_id": FAG, "role": "view"}).ok, "setup: shared with her agent")
r = FAGS.post(V + f"/documents/{OID}/receipt-suggestion", json={"category": "Strom"})
check(r.status_code == 201, f"her agent suggests a category ({r.status_code} {r.text[:120]})")
rc = Fr.get(B + f"/api/docs/{OID}/receipt").json()
check(rc.get("confirmed") is None and len(rc.get("suggestions") or []) == 1, "open suggestion: nobody confirmed yet")
SG = rc["suggestions"][0]["id"] if rc.get("suggestions") else 0
rc = Fr.post(B + f"/api/receipt-suggestions/{SG}/accept", json={}).json()
cf = rc.get("confirmed") or {}
check(rc["receipt"]["category"] == "Strom" and cf.get("agent", {}).get("name") == "Fridabot" and cf.get("by", {}).get("id") == FID,
      f"accepted: suggested by the agent, confirmed by her ({cf})")
time.sleep(1.1)
rc = Fr.put(B + f"/api/docs/{OID}/receipt", json={"project_id": None, "category": "Energie"}).json()
check(rc.get("confirmed") is None, "changed by her afterwards: no longer 'confirmed'")
check(FAGS.post(B + f"/api/docs/{OID}/split", json={"parts": [[1], [2]]}).status_code in (401, 403, 404), "the agent cannot split")
check(FAGS.post(B + f"/api/docs/{OID}/task/link", json={"task_id": FT}).status_code in (401, 403, 404), "the agent cannot link a task")

print(f"p2154_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
