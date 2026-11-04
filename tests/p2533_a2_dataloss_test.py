#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.533.0 A2 (#4318, audit #2425): small data loss spots, each kept or named instead of gone silently. Own container
(start.sh through kt.fresh, mode workspaces). Invented names only (example.com); the person without an organisation
(tests/freelancer_fixture.py) does every step that exists for her.
freelancer-matrix: office, wiki, tasks, files
 - B21 letterhead: the old letterhead file goes only after the commit (source order in the upload and the removal route);
   uploaded three times: the first file goes, the second stays as the undo step
 - B21 terms: a terms file named only by a draft copy in the office trash stays at the terms clean-up (restorable)
 - B20: the helper that an undo of a table's offer / an agent's proposal calls puts the draft into the office trash, and it
   comes back from there; both delete sites call it before their DELETE
 - B30: a received e-invoice (olk_fs_locked arrival) keeps its old versions at the version clean-up; a plain file loses them
 - A17: a rename relinks a linking page under that page's save lock and reads it again: a save of the page in between
   (committed while the rename waits) is kept together with the new link; a page without the link keeps its updated_at
 - A14: an app route's committed claim without an answer is answered as done (the change is not applied twice); a committed
   request that answered 5xx keeps its key as done on app routes, API v1 frees it as before
 - B8: "Delete all completed" writes a history line "delete" per task
usage: p2533_a2_dataloss_test.py <datadir>      (P2533A2_NOSTART=1 / KMT_NOSTART=1: a running server)"""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
import zlib
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import kt
from kt import B, CT, DATA, check, done
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
O = "/api/office"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


def box_cmd(code):
    body = "\n".join("    " + x for x in code.split("\n"))
    return ["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
            "c = connect()\nwith system_ctx(c):\n" + body + "\nc.commit()\nc.close()"]


def box(code):
    """python code inside the app container (system context, a fresh process) -> its output"""
    out = subprocess.run(box_cmd(code), capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def sh(cmd):
    return subprocess.run(["docker", "exec", CT, "sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def ago(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def src(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def order_in(rel, fn, first, then):
    """True when, in function fn of file rel, the last call named `first` comes before the first call named `then` after it"""
    tree = ast.parse(src(rel))
    f = next(x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == fn)
    calls = sorted((x.lineno, getattr(x.func, "attr", getattr(x.func, "id", ""))) for x in ast.walk(f) if isinstance(x, ast.Call))
    a = [ln for ln, n in calls if n == first]
    b = [ln for ln, n in calls if n == then]
    return bool(a and b) and max(a) < min(b)


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2533A2")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)

# ================================================================== B21 letterhead: the old file goes after the commit
for fn in ("bp_upload", "bp_delete"):
    check(order_in("kalmido/office/letterhead.py", fn, "commit", "bp_purge"), f"B21: {fn} deletes letterhead files only after c.commit()")
W_, H_ = 595.28, 841.89


def lh_pdf(rgb):
    content = b"%s rg 0 800 595.28 41.89 re f\n" % rgb
    z = zlib.compress(content)
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << >> /Contents 4 0 R >>" % (W_, H_),
            4: b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream"}
    out, offs = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"), {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % offs[n] for n in range(1, 5))
    out += b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % x
    return bytes(out)


lhs = []
for rgb in (b"0.1 0.2 0.3", b"0.4 0.5 0.6", b"0.7 0.8 0.9"):
    data = lh_pdf(rgb)
    r = Fr.post(B + O + "/letterhead", files={"file": ("Briefpapier.pdf", data, "application/pdf")})
    check(r.ok, f"B21: freelancer letterhead upload {r.status_code} {r.text[:160]}")
    lhs.append(f"letterhead-{hashlib.sha256(data).hexdigest()[:16]}.pdf")
have = sh("ls /data/office/*/ | grep letterhead- || true")
check(lhs[0] not in have and lhs[1] in have and lhs[2] in have, f"B21: after the third upload the first file is gone, the undo step stays: {have}")
r = Fr.delete(B + O + "/letterhead")
have = sh("ls /data/office/*/ | grep letterhead- || true")
check(r.ok and lhs[2] in have and lhs[1] not in have, f"B21: removing keeps the removed file as the undo step: {have}")

# ================================================================== B21 terms: a draft copy in the office trash names its terms file
COMPANY = {"name": "Studio Beispiel", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "post@example.com",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
check(Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14}).ok, "office settings")
CL = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln",
                                       "country": "DE", "email": "kunde@example.com"}).json()["id"]


def terms_up(tag):
    data = b"%PDF-1.4\n% invented terms " + tag.encode() + b"\n" + os.urandom(16).hex().encode() + b"\n%%EOF\n"
    r = Fr.post(B + O + "/terms/de", files={"file": ("AGB.pdf", data, "application/pdf")}, data={"date": "2026-09-01"})
    assert r.ok, r.text
    return f"terms-de-{hashlib.sha256(data).hexdigest()[:16]}.pdf", hashlib.sha256(data).hexdigest()


def terms_purge():
    code = ("import app\nfrom kalmido.office.terms import agb_purge_tick\nc = app.connect()\n"
            "try:\n    print('purged', agb_purge_tick(c))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_PURGE_FILES=1", CT, "python", "-c", code], capture_output=True, text=True)
    return out.stdout + out.stderr


t1, sha1 = terms_up("1")
DOC = Fr.post(B + O + "/docs", json={"client_id": CL, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
sql("UPDATE office_docs SET terms=? WHERE id=?", (json.dumps({"file": t1, "sha256": sha1, "lang": "de"}), DOC))
r = Fr.delete(B + O + f"/docs/{DOC}")
TR = r.json().get("trash_id") if r.ok else None
check(TR, f"B21: the draft with frozen terms went to the office trash {r.status_code} {r.text[:160]}")
t2, _ = terms_up("2")
t3, _ = terms_up("3")  # the current one
rows = [x for x in sql("SELECT org_id, data FROM office_settings") if t3 in str(x[1])]
OID = rows[0][0] if rows else None
check(OID is not None, "B21: the freelancer's office area found")
sql("DELETE FROM settings WHERE key='agb_grace_at'")
terms_purge()  # the grace round (file times = now)
d = json.loads(rows[0][1])
d["terms"]["de"]["uploaded_at"] = "2026-01-01T10:00:00+00:00"  # the current state was set long ago
sql("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(d), OID))
for n in (t1, t2):
    sh(f"touch -d '40 days ago' /data/office/{OID}/{n}")
out = terms_purge()
have = sh(f"ls /data/office/{OID}/")
check(t1 in have, f"B21: the terms file named only by the trash copy of a draft stays {out[-200:]}")
check(t2 not in have and t3 in have, f"B21: an old file nobody names goes, the current one stays: {have}")
r = Fr.post(B + O + f"/trash/{TR}/restore")
check(r.ok, f"B21: the draft comes back from the trash {r.status_code} {r.text[:160]}")

# ================================================================== B20: undo deletes of a draft go to the office trash
for rel in ("kalmido/sheets/step2.py", "kalmido/agents/propkinds2.py"):
    s = src(rel)
    i = s.find("dvb_otb_draft(")
    check(i > 0 and s.find("DELETE FROM office_docs", i) > i and s.rfind("DELETE FROM office_docs", 0, i) < 0,
          f"B20: {rel} stores the trash copy before its DELETE of the draft")
DOC2 = Fr.post(B + O + "/docs", json={"client_id": CL, "items": [{"title": "Ton", "qty": 2, "rate": 50}]}).json()["id"]
out = box(f"from kalmido.office.otrash import dvb_otb_draft\ntid = dvb_otb_draft(c, {OID}, {FID}, {DOC2})\n"
          f"c.execute('DELETE FROM office_docs WHERE id=?', ({DOC2},))\nprint('trash', tid)")
m = re.search(r"^trash (\d+)$", out, re.M)
tid = m.group(1) if m else ""
lst = Fr.get(B + O + "/trash").json()
check(tid.isdigit() and any(str(x.get("id")) == tid for x in (lst.get("items") or lst.get("trash") or [])),
      f"B20: the draft is in the office trash {out[-200:]} {str(lst)[:200]}")
r = Fr.post(B + O + f"/trash/{tid}/restore") if tid.isdigit() else None
check(r is not None and r.ok and sql("SELECT 1 FROM office_docs WHERE id=?", (DOC2,)), f"B20: ... and comes back from it {r.text[:160] if r is not None else out}")

# ================================================================== B30: a received e-invoice keeps its versions
P1 = Fr.post(B + "/api/files/upload", files={"file": ("Rechnung.xml", b"<invoice/>")}).json()["items"][0]["id"]
for no in range(100, 122):
    sql("INSERT INTO fs_versions(node_id, no, path, size, mime, sha256, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (P1, no, f"fs/p2533a2-{P1}-{no}", 1, "application/xml", "", FID, ago()))
out = box("import kalmido.receipts.suggest as S\nimport datetime\nS.olk_einv_until = lambda c, nid: datetime.date(2099, 12, 31)  # stands for: an e-invoice received into an office\n"
          f"from kalmido.admin.dataretention import orf_prune_versions\nprint('kept', orf_prune_versions(c, {P1}, False)[0])\n"
          "S.olk_einv_until = lambda c, nid: None\n"
          f"print('plain', orf_prune_versions(c, {P1}, False)[0])")
check("kept 0" in out, f"B30: the version clean-up keeps every version of a received e-invoice {out[-300:]}")
check("plain 0" not in out and "plain " in out, f"B30: a plain file still loses the versions beyond the limit {out[-300:]}")
sql("DELETE FROM fs_versions WHERE path LIKE 'fs/p2533a2-%'")

# ================================================================== A17: the rename relinks under the page's save lock
pa = Fr.post(B + "/api/wiki/pages", json={"path": "Projekt Alt", "body": "Ziel"}).json()["id"]
pb = Fr.post(B + "/api/wiki/pages", json={"path": "Notizen", "body": "Siehe [[Projekt Alt]]."}).json()["id"]
pc = Fr.post(B + "/api/wiki/pages", json={"path": "Fremd", "body": "Ohne Link."}).json()["id"]
before_c = Fr.get(B + f"/api/wiki/pages/{pc}").json()["updated_at"]
MARK = "Getippt waehrend des Umbenennens " + uuid.uuid4().hex[:8]
held = ("import time\nfrom kalmido.core.pg import write_lock\nfrom kalmido.wiki.wkhist import wkh_seal\n"
        f"r = c.execute('SELECT org_id, owner_id FROM wiki_pages WHERE id=?', ({pb},)).fetchone()\n"
        f"write_lock(c, 'wiki-{pb}')\n"
        f"c.execute('UPDATE wiki_pages SET body=? WHERE id=?', (wkh_seal(c, r['org_id'], r['owner_id'], 'Siehe [[Projekt Alt]]. {MARK}'), {pb}))\n"
        "print('held', flush=True)\nend = time.time() + 40\n"
        "while time.time() < end and not c.execute('SELECT COUNT(*) FROM pg_locks WHERE NOT granted').fetchone()[0]:\n"
        "    time.sleep(0.05)\n"
        "print('waiter', flush=True)")
p = subprocess.Popen(box_cmd(held), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
line = ""
while "held" not in line:  # the container's start notes (stderr) come first: wait for the real state
    line = p.stdout.readline()
    if not line:
        break
check("held" in line, f"A17: a save of the linking page holds its lock {line}")
res = {}
th = threading.Thread(target=lambda: res.update(r=Fr.patch(B + f"/api/wiki/pages/{pa}", json={"path": "Projekt Neu"})))
th.start()
rest = p.communicate(timeout=60)[0]
th.join(60)
r = res.get("r")
check("waiter" in rest, f"A17: the rename waited for the save {rest[-200:]}")
check(r is not None and r.ok, f"A17: rename {r.status_code if r is not None else '-'} {r.text[:160] if r is not None else ''}")
body = Fr.get(B + f"/api/wiki/pages/{pb}").json().get("body", "")
check(MARK in body, f"A17: the text saved while the rename waited is kept: {body[:200]}")
check("[[Projekt Neu" in body, f"A17: ... and the link is the new name: {body[:200]}")
check(Fr.get(B + f"/api/wiki/pages/{pc}").json()["updated_at"] == before_c, "A17: a page without the link keeps its updated_at")

# ================================================================== A14: idempotency keys of the app's routes
LID = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Band schneiden", "list_id": LID}).json()["id"]
k = uuid.uuid4().hex[:16]
sql("INSERT INTO idem_keys(user_id, k, method, path, created_at) VALUES(?,?,?,?,?)", (FID, k, "PATCH", f"/api/tasks/{T}", ago()))
r = Fr.patch(B + f"/api/tasks/{T}", json={"title": "Band schneiden zweimal"}, headers={"Idempotency-Key": k})
t = [x for x in Fr.get(B + "/api/state").json()["tasks"] if x["id"] == T]
check(r.ok and r.headers.get("Idempotent-Replayed") == "true" and t and t[0]["title"] == "Band schneiden",
      f"A14: a committed claim without an answer: the repeat is answered as done, not applied again {r.status_code} {r.text[:120]} {t and t[0]['title']}")
# review 2.533.0: a create with client_ref runs again: its duplicate check hands back the task WITH its id (the offline
# queue maps its temporary id with it; an {"ok": true} without id lost the mapping)
ref = "dvb-ref-" + uuid.uuid4().hex[:8]
T2 = Fr.post(B + "/api/tasks", json={"title": "Offline angelegt", "list_id": LID, "client_ref": ref}).json()["id"]
k3 = uuid.uuid4().hex[:16]
sql("INSERT INTO idem_keys(user_id, k, method, path, created_at) VALUES(?,?,?,?,?)", (FID, k3, "POST", "/api/tasks", ago()))
r = Fr.post(B + "/api/tasks", json={"title": "Offline angelegt", "list_id": LID, "client_ref": ref}, headers={"Idempotency-Key": k3})
n = [x for x in Fr.get(B + "/api/state").json()["tasks"] if x.get("title") == "Offline angelegt"]
check(r.ok and r.json().get("id") == T2 and len(n) == 1,
      f"A14: a repeated create with client_ref answers with the existing task's id, once {r.status_code} {r.text[:160]} {len(n)}")
k1, k2 = "dvb" + uuid.uuid4().hex[:12], "dvb" + uuid.uuid4().hex[:12]
for kk, path in ((k1, f"/api/tasks/{T}"), (k2, f"/api/v1/tasks/{T}")):
    sql("INSERT INTO idem_keys(user_id, k, method, path, created_at) VALUES(?,?,?,?,?)", (FID, kk, "PATCH", path, ago()))
out = box("from flask import Response, g\nfrom kalmido.core.config import app as F\nfrom kalmido.core.idem import idem_store\n"
          f"for path, kk in (('/api/tasks/{T}', '{k1}'), ('/api/v1/tasks/{T}', '{k2}')):\n"
          "    with F.test_request_context(path, method='PATCH'):\n"
          f"        g.user = {{'id': {FID}}}\n        g.idem_k = kk\n"
          "        idem_store(Response('{\"error\": \"x\"}', 500, mimetype='application/json'))\nprint('stored')")
r1 = sql("SELECT status FROM idem_keys WHERE user_id=? AND k=?", (FID, k1))
r2 = sql("SELECT status FROM idem_keys WHERE user_id=? AND k=?", (FID, k2))
check(r1 and r1[0][0] == 200, f"A14: committed, then 5xx on an app route: the key stays as done {r1} {out[-300:]}")
check(not r2, f"A14: API v1 frees the key as before {r2}")

# ================================================================== B8: "Delete all completed" writes the history
ids = [Fr.post(B + "/api/tasks", json={"title": f"Fertig {i}", "list_id": LID}).json()["id"] for i in range(3)]
check(Fr.post(B + "/api/tasks/batch", json={"ids": ids, "action": "complete", "data": {}}).ok, "B8: three tasks completed")
r = Fr.post(B + "/api/tasks/purge-done", json={})
check(r.ok and r.json().get("count", 0) >= 3, f"B8: purge-done {r.status_code} {r.text[:120]}")
logged = {x[0] for x in sql(f"SELECT task_id FROM activity WHERE kind='delete' AND task_id IN ({','.join('?' * len(ids))})", ids)}
check(logged == set(ids), f"B8: a history line 'delete' per task {sorted(logged)} of {ids}")

sys.exit(done("p2533_a2_dataloss"))
