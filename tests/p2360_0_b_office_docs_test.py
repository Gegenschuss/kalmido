#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.0 B (#2496): hardening of the office and the documents (audit #1461, low findings), own container (start.sh) with a
virus scanner that is off at first (tests/fake_clamd.py, started later). Invented people, firms and texts only (example.com).
tenant-matrix: office, docs
freelancer-matrix: office, docs
 - letterhead and terms uploads while the scanner cannot check them: 503 with a plain sentence (no later scan for them);
   once the scanner answers they are taken again
 - a document found infected by the later scan: no recognised text (GET, agent API), out of the word and phrase search
 - office move undo: two undos at once = one 200 and one 409, one undo row
 - progress invoices: two at once over the cap = one 201 and one 400 (organisation and personal office)
 - contracts of an organisation: the deadline task never goes into another person's private list (shared with the admin);
   the task's list name only for whoever sees that list; the personal office keeps its own private list
 - accepting a suggested folder moves the document into that folder (no new folder named like its id)
 - learned sorting in an organisation's documents folder: a member gets only labels that are on a document they see
 - the document queue takes the workspaces in turn
 - an MP4 / MOV loses its recorded place on upload (synthetic file), same length, the rest byte for byte
usage: p2360_0_b_office_docs_test.py <datadir>      (P2360B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import struct
import subprocess
import sys
import threading
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # noqa: E402,F401  shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
D = O + "/docs"
TODAY = testclock.today()
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
# the EICAR test string, assembled here so this file itself never carries it (as tests/fake_clamd.py)
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_ct(code, timeout=120):
    """Python code inside the server container (the app loaded) -> stdout + stderr."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + code],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def scanner_on():
    subprocess.run(["cp", os.path.join(N, "fake_clamd.py"), DATA], check=True)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_clamd.py"], check=True)


def pdf(text):
    """A tiny valid PDF made here (no real document)."""
    body = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def at_once(*calls):
    """Run the calls in parallel threads -> their responses in order."""
    out = [None] * len(calls)

    def go(i, f):
        out[i] = f()
    ts = [threading.Thread(target=go, args=(i, f)) for i, f in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


if not (os.environ.get("P2360B_NOSTART") or os.environ.get("KMT_NOSTART")):
    # the scanner is configured but not running yet: uploads are "unchecked"; not strict, so they stay readable until a find
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_CLAMD=127.0.0.1:3310"
               " -e KALMIDO_CLAMD_STRICT=0 -e KALMIDO_CLAMD_TICK_S=1 -e KALMIDO_CLAMD_DOWN_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert until(lambda: s0.get(B + "/api/state").status_code in (200, 401, 403), 30), "server up"
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
UID = {}
for u, rl in (("bob", "member"), ("carol", "admin")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rl}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    UID[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": SP})
sql("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, UID["carol"]), write=True)
FID, Fr = freelancer(B, A, features=FEAT)  # freelancer-matrix: office, docs (the personal office and private documents)
for s, name in ((A, "Beispiel Film GmbH"), (Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "en", "company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text

# ---------------------------------------------------------------- letterhead / terms while the scanner is down
for who, s in (("organisation", A), ("personal office", Fr)):
    r = s.post(B + O + "/letterhead", files={"file": ("head.pdf", pdf("Briefkopf"), "application/pdf")})
    check(r.status_code == 503 and "virus scanner" in r.json().get("error", ""), f"{who}: letterhead refused while the scanner is down ({r.status_code} {r.text[:160]})")
    r = s.post(B + O + "/terms/de", files={"file": ("agb.pdf", pdf("AGB Test"), "application/pdf")})
    check(r.status_code == 503, f"{who}: terms refused while the scanner is down ({r.status_code} {r.text[:160]})")
check(not (A.get(B + O + "/terms").json().get("terms") or {}).get("de"), "no terms stored while the scanner was down")

# ---------------------------------------------------------------- documents uploaded while the scanner is down
WORD = "Kobaltblau"


def doc_up(s, ws, name, data, mime="text/plain"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, data, mime)})
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def hits(s, q, ws):
    r = s.get(B + "/api/docs", params={"ws": ws, "q": q, "facets": "0"})
    return [d["id"] for d in r.json().get("docs", r.json().get("items", []))] if r.ok else ["status", r.status_code]


BAD = {}
for who, s, ws in (("organisation member", Bo, SP), ("personal", Fr, "private")):
    nid = doc_up(s, ws, "notiz.txt", f"Zauberwort {WORD} Testnotiz\n".encode() + EICAR + b"\n")
    d = done(s, nid)
    check(d and WORD in (d.get("text") or ""), f"{who}: the document's text is recognised ({(d or {}).get('state')})")
    check(nid in hits(s, WORD, ws), f"{who}: the search finds it before the scan")
    BAD[who] = (s, ws, nid)
scanner_on()
for who, (s, ws, nid) in BAD.items():
    got = until(lambda: sql("SELECT state FROM upload_scan WHERE kind='fs' AND ref_id=?", (nid,)) == [("infected",)], 60)
    check(got, f"{who}: the later scan finds the test string")
    d = s.get(B + f"/api/docs/{nid}").json()
    check(WORD not in json.dumps(d), f"{who}: no recognised text of a file found infected ({str(d.get('text'))[:60]})")
    check(nid not in hits(s, WORD, ws), f"{who}: a file found infected leaves the word search")
    check(nid not in hits(s, f'"Zauberwort {WORD}"', ws), f"{who}: and the phrase search")
    check(s.get(B + f"/api/docs/{nid}/file").status_code == 403, f"{who}: the file itself stays locked")
check(not sql("SELECT 1 FROM doc_words WHERE node_id IN (?, ?)", tuple(x[2] for x in BAD.values())), "the index words of the locked files are gone")

# the scanner answers again: letterhead / terms are taken
for who, s in (("organisation", A), ("personal office", Fr)):
    r = until(lambda: (lambda x: x if x.status_code != 503 else None)(s.post(B + O + "/terms/de", files={"file": ("agb.pdf", pdf("AGB Test"), "application/pdf")})), 30)
    check(r and r.ok, f"{who}: terms uploaded once the scanner answers ({r.status_code if r else '-'} {r.text[:160] if r else ''})")
    r = s.post(B + O + "/letterhead", files={"file": ("head.pdf", pdf("Briefkopf"), "application/pdf")})
    check(r.status_code != 503, f"{who}: the letterhead is no longer held back by the scanner ({r.status_code})")

# ---------------------------------------------------------------- office move undo: two at once
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + O + "/trips", json={"date_from": "2025-09-01", "dest": "Rostock", "purpose": "Dreh"})
assert r.status_code == 201, r.text
TRIP = r.json()["id"]
r = A.post(B + O + "/move-space", json={"what": "travel", "ids": [TRIP], "to": SP})
check(r.ok and r.json().get("move_id"), "the trip moves into the organisation " + r.text[:200])
MID = r.json().get("move_id")
rs = at_once(*[lambda: A.post(B + O + "/move-space", json={"undo": MID})] * 2)
codes = sorted(x.status_code for x in rs)
check(codes == [200, 409], f"two undos at once: one goes through, one is refused {codes}")
n = len([1 for (d,) in sql("SELECT detail FROM space_moves") if json.loads(d or "{}").get("undo_of") == MID])
check(n == 1, f"exactly one undo row ({n})")
A.patch(B + "/api/settings", json={"workspace": SP})

# ---------------------------------------------------------------- progress invoices: the cap with two at once
for who, s in (("organisation", A), ("personal office", Fr)):
    cl = s.post(B + "/api/clients", json={"name": f"Kunde {who}", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
    r = s.post(B + D, json={"project_title": "Imagefilm", "client_id": cl, "service_from": TODAY.replace(day=1).isoformat(), "service_to": TODAY.isoformat()})
    assert r.status_code == 201, r.text
    off = r.json()["id"]
    assert s.put(B + f"{D}/{off}/items", json={"items": [{"title": "Dreh", "qty": 2, "unit": "day", "rate": 4000, "tax": "standard"}]}).ok
    rs = at_once(*[lambda: s.post(B + f"{D}/{off}/invoice", json={"inv_type": "progress", "pct": 60})] * 2)
    codes = sorted(x.status_code for x in rs)
    check(codes == [201, 400], f"{who}: two progress invoices of 60 % at once: one is drafted, one would exceed the cap {codes}")
    p = s.get(B + f"{D}/{off}/progress").json()
    check(len(p["progress"]) == 1 and float(p["remaining"]) >= 0, f"{who}: the quotation is not over-billed ({p.get('remaining')})")

# ---------------------------------------------------------------- contracts: the deadline task's list
ENDS = (TODAY + timedelta(days=200)).isoformat()


def own_list(s, name):
    s.patch(B + "/api/settings", json={"workspace": "private"})
    r = s.post(B + "/api/lists", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


LC = own_list(Ca, "Carol privat")
LA = own_list(A, "Alice privat")
assert Ca.put(B + f"/api/lists/{LC}/members", json={"user_id": ALICE, "role": "edit"}).ok
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"workspace": SP})
AG = {"kind": "insurance", "name": "Haftpflicht", "ends": ENDS, "notice": 1, "notice_unit": "m", "task": 1}
r = A.post(B + O + "/agreements", json=dict(AG, list_id=LC))
check(r.status_code == 400, f"an organisation contract's task never goes into another person's private list ({r.status_code} {r.text[:160]})")
lists = [x["id"] for x in A.get(B + O + "/agreements").json().get("lists", [])]
check(LA in lists and LC not in lists, f"the list choice offers the own private list, not the shared one of another person {lists}")
r = A.post(B + O + "/agreements", json=dict(AG, list_id=LA))
check(r.status_code == 201 and (r.json().get("task") or {}).get("list") == "Alice privat", "into the admin's own private list " + r.text[:200])
AID = r.json().get("id")
t = Ca.get(B + O + f"/agreements/{AID}").json().get("task") or {}
check(t.get("id") and t.get("list") == "", f"another admin sees the task but not the name of the private list ({t})")
LF = own_list(Fr, "Frida privat")
r = Fr.post(B + O + "/agreements", json=dict(AG, list_id=LF))
check(r.status_code == 201 and (r.json().get("task") or {}).get("list") == "Frida privat", "personal office: its own private list " + r.text[:200])

# ---------------------------------------------------------------- accepting a suggested folder
d1 = doc_up(Fr, "private", "rechnung-eins.pdf", pdf("Rechnung Eins"), "application/pdf")
d2 = doc_up(Fr, "private", "rechnung-zwei.pdf", pdf("Rechnung Zwei"), "application/pdf")
done(Fr, d1)
done(Fr, d2)
r = Fr.patch(B + f"/api/docs/{d1}", json={"folder": "Belege"})
FB = ((r.json() if r.ok else {}).get("folder") or {}).get("id")
check(FB, "a folder by name " + r.text[:200])
sql("UPDATE doc_meta SET suggest=?, review=1 WHERE node_id=?", (json.dumps({"folder": {"value": str(FB), "conf": 0.6, "by": "learn"}}), d2), write=True)
r = Fr.post(B + f"/api/docs/{d2}/accept", json={"features": ["folder"]})
f = ((r.json() if r.ok else {}).get("folder") or {})
check(f.get("id") == FB and f.get("name") == "Belege", f"accepting the suggested folder files the document there ({r.status_code} {f})")
check(not sql("SELECT 1 FROM fs_nodes WHERE kind='folder' AND name=? AND deleted_at IS NULL", (str(FB),)), "no folder named like the id")

# ---------------------------------------------------------------- learned sorting: labels of other members' documents
da = doc_up(A, SP, "praxis.pdf", pdf("Praxis Beispiel"), "application/pdf")
db_ = doc_up(Bo, SP, "brief.pdf", pdf("Brief Bob"), "application/pdf")
db2 = doc_up(Bo, SP, "brief2.pdf", pdf("Brief Bob zwei"), "application/pdf")
for nid, s in ((da, A), (db_, Bo), (db2, Bo)):
    done(s, nid)
check(A.patch(B + f"/api/docs/{da}", json={"sender": "Praxis Doktor Beispiel"}).ok, "the admin's document gets a sender")
SID = sql("SELECT sender_id FROM doc_meta WHERE node_id=?", (da,))[0][0]
PROBE = ("from kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.docs import store as S\nc = connect()\n"
         "with system_ctx(c):\n    m = S.meta_row(c, {nid})\n"
         "    print('seen', S._learn_seen(c, m, {bob}, 'sender', {sid}), S._learn_seen(c, m, {alice}, 'sender', {sid}))\nc.close()")
out = in_ct(PROBE.format(nid=db_, bob=UID["bob"], alice=ALICE, sid=SID))
check("seen False True" in out, "a member is not offered a sender of documents they do not see; the admin is " + out[-300:])
check(Bo.patch(B + f"/api/docs/{db2}", json={"sender": "Praxis Doktor Beispiel"}).ok, "the member's own document gets that sender")
out = in_ct(PROBE.format(nid=db_, bob=UID["bob"], alice=ALICE, sid=SID))
check("seen True True" in out, "once it is on a document the member sees, it may be offered " + out[-300:])

# ---------------------------------------------------------------- the document queue: workspaces in turn
fr_docs = [doc_up(Fr, "private", f"stapel-{i}.pdf", pdf(f"Stapel {i}"), "application/pdf") for i in range(3)]
dq = doc_up(Bo, SP, "brief3.pdf", pdf("Brief Bob drei"), "application/pdf")  # after the pile
for nid, s in [(x, Fr) for x in fr_docs] + [(dq, Bo)]:
    done(s, nid)
QUEUE = ("from kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.docs.ingest import DOCS_NEXT\nc = connect()\n"
         "with system_ctx(c):\n"
         "    c.execute(\"UPDATE doc_meta SET state='wait' WHERE node_id IN ({ids})\")\n"
         "    a = c.execute(DOCS_NEXT, ('{{}}',)).fetchone()[0]\n"
         "    b = c.execute(DOCS_NEXT, ('{{u{fid}}}',)).fetchone()[0]\n"
         "    d = c.execute(DOCS_NEXT, ('{{u{fid},o{org}}}',)).fetchone()[0]\n"
         "    print('next', a, b, d)\n"
         "c.rollback()\nc.close()")
out = in_ct(QUEUE.format(ids=",".join(str(x) for x in fr_docs + [dq]), fid=FID, org=ORG))
check(f"next {fr_docs[0]} {dq} {fr_docs[0]}" in out, f"the queue takes the oldest first, then another workspace's document before the pile goes on ({fr_docs}, {dq}) " + out[-300:])

# ---------------------------------------------------------------- MP4 / MOV: the recorded place goes
def box(t, p):
    return struct.pack(">I", 8 + len(p)) + t + p


GPS = b"+52.5200+013.4050/"
data_box = lambda v: box(b"data", b"\0\0\0\1\0\0\0\0" + v)  # noqa: E731
keys = box(b"keys", b"\0\0\0\0" + struct.pack(">I", 2) + box(b"mdta", b"com.apple.quicktime.make") + box(b"mdta", b"com.apple.quicktime.location.ISO6709"))
ilst = box(b"ilst", box(struct.pack(">I", 1), data_box(b"ExampleCam")) + box(struct.pack(">I", 2), data_box(GPS)))
moov = box(b"moov", box(b"mvhd", b"\0" * 100) + box(b"udta", box(b"\xa9xyz", struct.pack(">HH", len(GPS), 0x15c7) + GPS)
                                                        + box(b"loci", b"\0" * 6 + b"Ort\0" + b"\0" * 13 + GPS))
           + box(b"meta", box(b"hdlr", b"\0" * 8 + b"mdta" + b"\0" * 13) + keys + ilst))
MOV = box(b"ftyp", b"qt  \0\0\0\0qt  ") + box(b"mdat", b"\x11" * 256) + moov
for who, s, space in (("organisation", A, SP), ("personal", Fr, "private")):
    r = s.post(B + "/api/files/upload", data={"space": space, "replace": "0"}, files={"file": ("clip.mov", MOV, "video/quicktime")})
    check(r.status_code == 201, f"{who}: video upload {r.status_code} {r.text[:160]}")
    got = s.get(B + f"/api/files/nodes/{r.json()['items'][0]['id']}/content").content if r.ok else b""
    check(len(got) == len(MOV) and GPS not in got, f"{who}: the video keeps its size and loses the place ({len(got)}, {GPS in got})")
    check(b"\x11" * 256 in got and b"ExampleCam" in got and b"mvhd" in got, f"{who}: the rest of the video stays as it was")

print(f"p2360_0_b_office_docs: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
