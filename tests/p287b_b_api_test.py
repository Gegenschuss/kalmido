#!/usr/bin/env python3
"""2.87.9 API tests, part B: the target of an import (#1940) and the progress of a Paperless-ngx import (#1938), against the
fake Paperless-ngx inside the test container (fake_paperless.py, 127.0.0.1:8098). Invented names only, generated files.
 - #1940 Paperless (connection + export ZIP way share pl_run_target): an organisation's admin imports from the
   organisation's connection into the organisation (as before) or with target "private" into their OWN private space
   (the run says target private + mine); a member cannot start either; any other target is refused (400); a person
   without an organisation imports into their own space (target private = the same)
 - #1940 task import (ICS): space=private / org:<id> puts the new lists there, a foreign organisation is refused (400),
   without space the default of a new list stays (the first organisation); the preview (dry run) names nothing new
 - #1938 the run writes its progress after every document (a poll sees 0 < done < total while it runs) and ends idle with
   done = total
usage: p287b_b_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests
from freelancer_fixture import org_join  # 2.148.1 (#2480): an invited member accepts

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
PL = "http://127.0.0.1:8098"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.3)
    return fn()


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out.decode("latin-1")


def doc(i, title):
    return {"id": i, "title": title, "content": title + " text", "created": "2025-03-01", "correspondent": None, "document_type": None,
            "tags": [], "archive_serial_number": None, "original_file_name": f"doc{i}.pdf", "custom_fields": [], "notes": [],
            "file": tiny_pdf(title + " body")}


PLDATA = {"tags": [], "correspondents": [], "document_types": [], "custom_fields": [],
          "documents": [doc(21, "Rent contract"), doc(22, "Insurance letter"), doc(23, "Water bill")]}


def pl_write(**kw):
    with open(os.path.join(DATA, "pl.json"), "w") as f:
        json.dump({**PLDATA, **kw}, f)


def run_of(s, ws):
    return ((s.get(B + f"/api/paperless?ws={ws}").json().get("conn") or {}).get("run") or {})


def run_idle(s, ws):
    return until(lambda: run_of(s, ws) if run_of(s, ws).get("state") == "idle" else None)


def docs(s, ws):
    return s.get(B + f"/api/docs?ws={ws}").json().get("docs") or []


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098"
           " -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_paperless.py"), DATA)
pl_write()
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_paperless.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG)), "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, ids["bob"], ids["carol"]), write=True)
dbx("DELETE FROM org_members WHERE org_id=? AND user_id<>?", (ORG2, ids["carol"]), write=True)
dbx("DELETE FROM org_members WHERE user_id=?", (ids["erin"],), write=True)  # erin: self-employed, no organisation (P4)
A, Bo, Ca, Er = sess("alice"), sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    f = s.get(B + "/api/state").json()["settings"].get("features") or ""
    if "docs" not in f.split(","):
        s.patch(B + "/api/settings", json={"features": f + ",docs"})
OWS = f"org:{ORG}"

# ---- schema: two additive columns, nothing else
cols = {(r[0], r[1]) for r in dbx("SELECT table_name, column_name FROM information_schema.columns WHERE column_name='run_ws'")}
check(cols == {("pl_sources", "run_ws"), ("pl_uploads", "run_ws")}, f"#1940: run_ws on pl_sources + pl_uploads ({sorted(cols)})")

# ---- #1940 Paperless: from the organisation's connection into the own private space
r = Bo.put(B + "/api/paperless", json={"ws": OWS, "url": PL, "token": "pl-secret"})
check(r.ok, f"the organisation's admin connects ({r.status_code} {r.text[:200]})")
for bad in ("org:999999", f"org:{ORG2}", "u1", "everyone", 5):
    r = Bo.post(B + "/api/paperless/import", json={"ws": OWS, "target": bad})
    check(r.status_code == 400, f"#1940: target {bad!r} refused ({r.status_code} {r.text[:120]})")
check(run_of(Bo, OWS).get("state") == "idle", "#1940: a refused start leaves the run idle")
r = Ca.post(B + "/api/paperless/import", json={"ws": OWS, "target": "private"})
check(r.status_code == 403, f"#1940: a member cannot start an import into their private space from the organisation's connection ({r.status_code})")
r = Bo.post(B + "/api/paperless/import", json={"ws": OWS, "target": "private"})
check(r.ok, f"#1940: the admin starts the import into private ({r.status_code} {r.text[:200]})")
run = r.json()["conn"]["run"]
check(run.get("target") == "private" and run.get("mine") is True, f"#1940: the run names its target: private, mine ({run})")
run = run_idle(Bo, OWS)
check(run and run.get("new") == 3, f"#1940: three documents came in ({run})")
pd = docs(Bo, "private")
check(len(pd) == 3 and all(not d.get("org_id") for d in pd), f"#1940: they are in bob's private documents ({[(d['name'], d.get('org_id')) for d in pd]})")
check(not docs(Bo, OWS), "#1940: nothing in the organisation's documents")
check(not docs(Ca, OWS) and not docs(Ca, "private"), "#1940: carol (member) sees none of them")
ws_rows = {r[0] for r in dbx("SELECT ws FROM pl_imported")}
check(ws_rows == {f"u{ids['bob']}"}, f"#1940: remembered for bob's private space ({ws_rows})")
j = Ca.get(B + f"/api/paperless?ws={OWS}").json()
check(j["conn"]["run"].get("target") == "private" and j["conn"]["run"].get("mine") is False, "#1940: another member sees 'private of the starter', not 'mine'")
# the same connection into the organisation (as before): the documents come in there too (another space = not twice)
r = Bo.post(B + "/api/paperless/import", json={"ws": OWS})
check(r.ok and r.json()["conn"]["run"].get("target") == "ws", f"#1940: without target = the workspace itself ({r.text[:200]})")
run = run_idle(Bo, OWS)
od = docs(Bo, OWS)
check(len(od) == 3 and all(d.get("org_id") == ORG for d in od), f"#1940: organisation import as before ({len(od)})")
check(len(docs(Bo, "private")) == 3, "#1940: the private ones stay")
# a run must never file into a foreign space even with a forged row (pl_target): run_ws of another person -> the run refuses
dbx("UPDATE pl_sources SET run_state='queued', run_kind='all', run_by=?, run_ws=?, run_beat='0' WHERE ws=?", (ids["bob"], f"u{ids['carol']}", f"o{ORG}"), write=True)
Bo.put(B + "/api/paperless", json={"ws": OWS, "follow": False})  # wakes the worker
run = run_idle(Bo, OWS)
check(run and run.get("error") == "owner" and not docs(Ca, "private"), f"#1940: a run into someone else's space is refused ({run})")

# ---- #1940 P4: a person without an organisation
r = Er.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.ok, f"P4: erin connects their own space ({r.status_code})")
r = Er.post(B + "/api/paperless/import", json={"ws": "private", "target": "private"})
check(r.ok and r.json()["conn"]["run"].get("target") == "ws", f"P4: target private = their own space ({r.status_code} {r.text[:200]})")
run_idle(Er, "private")
check(len(docs(Er, "private")) == 3, "P4: erin's documents are in their private space")
r = Er.post(B + "/api/paperless/import", json={"ws": "private", "target": OWS})
check(r.status_code == 400, f"P4: a foreign organisation as target refused ({r.status_code})")
check(Er.post(B + "/api/paperless/import", json={"ws": OWS, "target": "private"}).status_code == 404, "P4: not across workspaces (404)")

# ---- #1940 the export ZIP route takes the same target check
r = Ca.post(B + "/api/paperless/zip/import", json={"ws": OWS, "target": "private"})
check(r.status_code in (403, 404), f"#1940: ZIP: a member cannot start ({r.status_code})")

# ---- #1938: progress after every document (a slow Paperless: every download waits)
pl_write(documents=[doc(31, "Slow one"), doc(32, "Slow two"), doc(33, "Slow three"), doc(34, "Slow four")], delay=1.2)
r = Er.post(B + "/api/paperless/import", json={"ws": "private"})
check(r.ok, f"#1938: a slow import starts ({r.status_code})")
seen = set()
t0 = time.time()
while time.time() - t0 < 60:
    x = run_of(Er, "private")
    if x.get("state") == "busy" and x.get("total"):
        seen.add(x.get("done"))
    if x.get("state") == "idle":
        break
    time.sleep(0.3)
x = run_of(Er, "private")
check(any(0 < n < 4 for n in seen if n is not None), f"#1938: a poll sees the count grow while it runs ({sorted(n for n in seen if n is not None)})")
check(x.get("state") == "idle" and x.get("done") == x.get("total") == 4 and x.get("new") == 4, f"#1938: it ends idle with all documents done ({x})")
pl_write()

# ---- #1940 task import: the workspace of the new lists
ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:{name}\r\nBEGIN:VTODO\r\nUID:{uid}@example.com\r\nSUMMARY:{title}\r\n"
       "END:VTODO\r\nEND:VCALENDAR\r\n")


def imp(s, name, title, **opts):
    r = s.post(B + "/api/import/ics", files={"file": ("tasks.ics", ICS.format(name=name, uid=title.replace(" ", ""), title=title).encode())},
               data={k: str(v) for k, v in opts.items()})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


def list_org(name, owner):
    rows = dbx("SELECT org_id FROM lists WHERE name=? AND owner_id=?", (name, owner))
    return rows[0][0] if rows else "missing"


st, j = imp(Bo, "Imported private", "Task one", space="private")
check(st == 200 and list_org("Imported private", ids["bob"]) is None, f"#1940: space=private -> a private list ({st} {list_org('Imported private', ids['bob'])})")
st, j = imp(Bo, "Imported org", "Task two", space=OWS)
check(st == 200 and list_org("Imported org", ids["bob"]) == ORG, f"#1940: space=org -> the organisation's list ({st})")
st, j = imp(Bo, "Imported default", "Task three")
check(st == 200 and list_org("Imported default", ids["bob"]) == ORG, "#1940: without space the default of a new list stays (first organisation)")
st, j = imp(Bo, "Imported foreign", "Task four", space=f"org:{ORG2}")
check(st == 400 and list_org("Imported foreign", ids["bob"]) == "missing", f"#1940: a foreign organisation refused ({st})")
st, j = imp(Bo, "Imported bad", "Task five", space="org:x")
check(st == 400, f"#1940: a bad space refused ({st})")
# a list of the same name is reused only inside the chosen space
st, j = imp(Bo, "Imported org", "Task six", space="private", dry_run=1)
check(st == 200 and j["lists"] and j["lists"][0].get("existing") is False, f"#1940: same name in another space = a new list ({j.get('lists')})")
st, j = imp(Bo, "Imported org", "Task six", space=OWS, dry_run=1)
check(st == 200 and j["lists"] and j["lists"][0].get("existing") is True, f"#1940: same name in the same space = reused ({j.get('lists')})")
st, j = imp(Er, "Erin list", "Task seven", space="private")
check(st == 200 and list_org("Erin list", ids["erin"]) is None, "P4: a person without an organisation imports privately")
st, j = imp(Er, "Erin org", "Task eight", space=OWS)
check(st == 400, f"P4: … and never into an organisation ({st})")
r = Bo.get(B + "/api/v1/openapi.json")
if r.ok:
    props = json.dumps(r.json())
    check('"space"' in props, "#1940: the API documents the option space")

print(f"p287b_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
