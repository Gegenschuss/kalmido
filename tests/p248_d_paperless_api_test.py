#!/usr/bin/env python3
"""2.48.0 API tests, part D (#1152): the Paperless-ngx connection of a workspace and the import into the documents, against
a fake Paperless-ngx inside the test container (fake_paperless.py, 127.0.0.1:8098, allowed as an internal host).
Invented names only, generated file contents.
 - connect: wrong token / bad address / redirect refused with a readable reason; the token never comes back
 - preview: count, tags / correspondents / types with their mapping
 - import in the background: file, Paperless' text, date, tags, correspondent -> sender, type, a tag as folder, a skipped
   tag, custom fields + notes + archive serial number in the text; the same file twice = once; again = nothing new
 - following: new documents come in by themselves; Kalmido only ever sends GET
 - 2.66.1 (#1944): an import with Paperless' text gets its preview (private: sealed with the space's key, an organisation:
   with its key); the one-time catch-up makes missing previews of earlier imports and changes nothing else
 - rights: organisation admins only (members see, cannot change), no agents, not across workspaces; a person without an
   organisation for their own space
 - a hosted server: 2.69.0 (#1846) the connection is there, public HTTPS only (more in p269_a_api_test.py)
 - 2.56.4 (#1859): the API version is negotiated (Paperless-ngx 3.x: only 9 / 10, 406 on 5; an old server: only up to 5;
   none in common: a readable reason), custom fields of API 7+ (select option ids, amounts, yes / no, document links) and of
   before (select option index) as text
usage: p248_d_paperless_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
PL = "http://127.0.0.1:8098"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
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


def doc(i, title, **kw):
    d = {"id": i, "title": title, "content": "", "created": "2025-01-01", "correspondent": None, "document_type": None, "tags": [],
         "archive_serial_number": None, "original_file_name": f"doc{i}.pdf", "custom_fields": [], "notes": [], "file": tiny_pdf(title)}
    d.update(kw)
    return d


# 2.56.4 (#1859): like Paperless-ngx 3.x -- API 9 / 10 only, tags with parent / children, select options with ids, notes
# with a user object, created a date
PLDATA = {
    "versions": ["9", "10"],
    "tags": [{"id": 1, "name": "Tax", "document_count": 2, "parent": None, "children": []},
             {"id": 2, "name": "Archive 2025", "document_count": 1, "parent": None, "children": []},
             {"id": 3, "name": "Ignore me", "document_count": 1, "parent": None, "children": []}],
    "correspondents": [{"id": 7, "name": "Example Utility", "document_count": 1}],
    "document_types": [{"id": 9, "name": "Invoice", "document_count": 2}],
    "custom_fields": [{"id": 4, "name": "Contract number", "data_type": "string", "extra_data": {}},
                      {"id": 5, "name": "Status", "data_type": "select",
                       "extra_data": {"select_options": [{"id": "aB3xY9", "label": "Open"}, {"id": "Qw7rT2", "label": "Paid"}]}},
                      {"id": 6, "name": "Amount", "data_type": "monetary", "extra_data": {"default_currency": None}},
                      {"id": 8, "name": "Signed", "data_type": "boolean", "extra_data": {}},
                      {"id": 10, "name": "Related", "data_type": "documentlink", "extra_data": {}}],
    "documents": [
        doc(11, "Power bill May", content="Power bill May total 42.00 EUR", created="2025-05-03", created_date="2025-05-03",
            correspondent=7, document_type=9, tags=[1, 2], archive_serial_number=17, original_file_name="power.pdf",
            custom_fields=[{"field": 4, "value": "C-123"}, {"field": 5, "value": "Qw7rT2"}, {"field": 6, "value": "EUR42.00"},
                           {"field": 8, "value": True}, {"field": 10, "value": [12]}],
            notes=[{"id": 1, "note": "Paid on 10 May", "created": "2025-05-10T09:00:00+02:00",
                    "user": {"id": 3, "username": "someone", "first_name": "", "last_name": ""}}]),
        doc(12, "Tax notice", content="Notice of assessment", created="2025-02-01T10:00:00+01:00", document_type=9, tags=[1, 3],
            notes=1),
        doc(13, "Copy", file=tiny_pdf("Power bill May"))],
    "notes": {"12": [{"id": 2, "note": "Check the objection period"}]}}


def pl_write():
    with open(os.path.join(DATA, "pl.json"), "w") as f:
        json.dump(PLDATA, f)


def pl_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "pl.log"), encoding="utf-8")]
    except OSError:
        return []


def run_idle(s, ws="private", secs=60):
    def done():
        j = s.get(B + f"/api/paperless?ws={ws}").json()
        r = (j.get("conn") or {}).get("run") or {}
        return j if r.get("state") == "idle" else None
    return until(done, secs)


def docs(s, ws="private"):
    return s.get(B + f"/api/docs?ws={ws}").json().get("docs") or []


BASE_EXTRA = os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098"
# 2.48.0 review (S2): the token is always sealed with a key derived from the server key -> the container has one
env = dict(os.environ, EXTRA=BASE_EXTRA + " -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
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
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, ids["bob"], ids["carol"]), write=True)
dbx("DELETE FROM org_members WHERE user_id=?", (ids["erin"],), write=True)  # erin: a freelancer without an organisation
r = A.post(B + "/api/admin/agents", json={"username": "plbot", "display_name": "Plbot"})
assert r.status_code == 201, r.text
AGT = r.json().get("token") or ""
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Er = sess("alice"), sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    f = s.get(B + "/api/state").json()["settings"].get("features") or ""
    if "docs" not in f.split(","):
        s.patch(B + "/api/settings", json={"features": f + ",docs"})

# ---- rollback: only new tables
cols = {r[0] for r in dbx("SELECT table_name FROM information_schema.columns WHERE table_name IN ('pl_sources', 'pl_imported')")}
check(cols == {"pl_sources", "pl_imported"}, f"two new tables ({sorted(cols)})")
check(all(x[0] for x in dbx("SELECT relrowsecurity FROM pg_class WHERE relname IN ('pl_sources', 'pl_imported')")), "row-level security on both")

# ---- connect
j = A.get(B + "/api/paperless?ws=private").json()
check(j.get("available") is True and j.get("conn") is None and j.get("can_manage") is True, f"not connected yet ({j})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "wrong"})
check(r.status_code == 400 and "refused the API token" in r.json().get("error", ""), f"wrong token: refused with the reason ({r.status_code} {r.text[:200]})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": "ftp://127.0.0.1:8098", "token": "pl-secret"})
check(r.status_code == 400, f"ftp:// refused ({r.status_code})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL + "/redirect", "token": "pl-secret"})
check(r.status_code == 400 and "redirect" in r.json().get("error", ""), f"a redirect is not followed ({r.status_code} {r.text[:200]})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": "http://10.255.255.1:8098", "token": "pl-secret"})
check(r.status_code == 400 and "private network" in r.json().get("error", ""), f"an internal host that is not allowed: blocked ({r.text[:200]})")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL + "/api/", "token": "pl-secret"})
check(r.ok and r.json()["conn"]["token_set"] is True and r.json()["conn"]["url"] == PL, f"connected, /api/ cut off ({r.status_code} {r.text[:200]})")
# 2.56.4 (#1859): Paperless-ngx 3.x allows only API 9 / 10 -> Kalmido asks for 10 (not 5 any more: that was the 406)
acc = [x.get("accept") or "" for x in pl_log() if x.get("auth")]
check(acc and acc[-1].endswith("version=10") and not any("version=5" in a for a in acc), f"Paperless-ngx 3.x: API version 10 ({acc[-3:]})")
check("pl-secret" not in r.text and "pl-secret" not in A.get(B + "/api/paperless?ws=private").text, "the token never comes back")
check(A.put(B + "/api/paperless", json={"ws": "private", "foo": 1}).status_code == 400, "unknown field refused")
check(A.put(B + "/api/paperless", json={"ws": "private", "every_min": 7}).status_code == 400, "only the offered intervals")
# 2.48.0 review (S2, L6): sealed in the database (also with the encryption of organisations off); a plain value from
# before is sealed on the next save; a null address is a 400
tv = lambda: dbx("SELECT token FROM pl_sources WHERE ws='u1'")[0][0]
check(tv().startswith("kenc1:") and "pl-secret" not in tv(), "the token is sealed in the database")
dbx("UPDATE pl_sources SET token='pl-secret' WHERE ws='u1'", write=True)
check(A.put(B + "/api/paperless", json={"ws": "private", "follow": False}).ok and tv().startswith("kenc1:"), "a plain token is sealed on the next save")
check(A.put(B + "/api/paperless", json={"ws": "private", "url": None}).status_code == 400, "url null: 400")
check(A.put(B + "/api/paperless", json={"ws": "private", "url": 5, "token": "pl-secret"}).status_code == 400, "url a number: 400")
check(A.put(B + "/api/paperless", json={"ws": "private", "url": "http://[::1", "token": "pl-secret"}).status_code == 400, "a broken address: 400")

# ---- preview
p = A.get(B + "/api/paperless/preview?ws=private").json()
check(p.get("count") == 3 and p.get("already") == 0, f"preview: 3 documents, none imported ({p.get('count')}, {p.get('already')})")
check([t["name"] for t in p.get("tags", [])] == ["Tax", "Archive 2025", "Ignore me"] and all(t["to"] == "tag" for t in p["tags"]),
      f"preview: tags become tags by default ({p.get('tags')})")
check(p.get("senders") and p["senders"][0]["target"] == "Example Utility" and p.get("types") and p["types"][0]["name"] == "Invoice",
      "preview: correspondents -> senders, document types -> types")

# ---- import
mapping = {"tags": {"2": {"to": "folder", "name": "Archive 2025"}, "3": {"to": "skip", "name": ""}, "1": {"to": "tag", "name": "Taxes"}},
           "senders": {}, "types": {"9": "Bill"}}
r = A.post(B + "/api/paperless/import", json={"ws": "private", "mapping": mapping})
check(r.ok and r.json()["conn"]["run"]["state"] in ("queued", "busy", "idle"), f"import started ({r.status_code} {r.text[:200]})")
j = run_idle(A)
run = (j or {}).get("conn", {}).get("run", {})
check(run.get("new") == 2 and run.get("skipped") == 1 and run.get("failed") == 0 and run.get("total") == 3,
      f"import: 2 new, the same file once more = skipped ({run})")
ds = until(lambda: (lambda x: x if len(x) == 2 and all(d["state"] in ("done", "failed") for d in x) else None)(docs(A)), 60) or docs(A)
by = {d["name"]: d for d in ds}
pb, tn = by.get("Power bill May.pdf"), by.get("Tax notice.pdf")
check(pb and tn, f"two documents, named after the title ({sorted(by)})")
if pb and tn:
    check(pb["source"] == "paperless" and pb["date"] == "2025-05-03" and tn["date"] == "2025-02-01", f"date taken ({pb['date']}, {tn['date']})")
    check((pb.get("sender") or {}).get("name") == "Example Utility" and (pb.get("type") or {}).get("name") == "Bill",
          f"correspondent -> sender, type renamed in the preview ({pb.get('sender')}, {pb.get('type')})")
    check([t["name"] for t in pb["tags"]] == ["Taxes"] and [t["name"] for t in tn["tags"]] == ["Taxes"],
          f"tag renamed, the skipped tag left out ({pb['tags']}, {tn['tags']})")
    check((pb.get("folder") or {}).get("name") == "Archive 2025" and not tn.get("folder"), f"a tag as folder ({pb.get('folder')})")
    full = A.get(B + f"/api/docs/{pb['id']}").json()
    t = full.get("text") or ""
    check("Power bill May total 42.00 EUR" in t and "Archive serial number: 17" in t and "Contract number: C-123" in t and "Paid on 10 May" in t,
          f"text + serial number + custom field + note ({t[:300]!r})")
    check("Status: Paid" in t and "Amount: 42.00 EUR" in t and "Signed: Yes" in t and "Related: Paperless #12" in t and "Qw7rT2" not in t,
          f"API 10 custom fields: the select option's label, amount, yes / no, document link ({t[:400]!r})")
    t2 = A.get(B + f"/api/docs/{tn['id']}").json().get("text") or ""
    check("Check the objection period" in t2, "notes fetched when the list only counts them")
    f = A.get(B + f"/api/docs/{pb['id']}/file")
    check(f.ok and f.content.startswith(b"%PDF"), "the original file is stored")
    # 2.66.1 (#1944): an import with Paperless' text gets its preview all the same; alice has no organisation -> her
    # private preview is sealed on disk with the space's key, the route opens it (P4)
    th = dbx("SELECT thumb FROM doc_meta WHERE node_id=?", (pb["id"],))[0][0]
    check(pb.get("thumb") and th, f"#1944: the imported document has a preview ({pb.get('thumb')}, {th!r})")
    if th:
        raw = open(os.path.join(DATA, "attachments", th), "rb").read()
        tr_ = A.get(B + f"/api/docs/{pb['id']}/thumb")
        check(raw.startswith(b"KENC1\n") and tr_.ok and tr_.content[:2] == b"\xff\xd8", "#1944: private preview sealed on disk, a JPEG from the route")
    # the catch-up for documents imported before: preview gone, the merker reset -> the queue makes it again, nothing else changes
    before = A.get(B + f"/api/docs/{pb['id']}").json()
    dbx("UPDATE doc_meta SET thumb='' WHERE node_id=?", (pb["id"],), write=True)
    dbx("DELETE FROM settings WHERE key='docs_thumb_fill'", write=True)
    th2 = until(lambda: dbx("SELECT thumb FROM doc_meta WHERE node_id=?", (pb["id"],))[0][0], 90)
    tr_ = A.get(B + f"/api/docs/{pb['id']}/thumb")
    check(th2 and tr_.ok and tr_.content[:2] == b"\xff\xd8", f"#1944: the catch-up made the preview again ({th2!r}, {tr_.status_code})")
    after = A.get(B + f"/api/docs/{pb['id']}").json()
    check(all(after.get(k) == before.get(k) for k in ("text", "sender", "type", "tags", "folder", "review", "asn", "date")),
          "#1944: the catch-up changes nothing but the preview")
    check(until(lambda: '"done"' in (dbx("SELECT value FROM settings WHERE key='docs_thumb_fill'") or [[""]])[0][0], 90),
          "#1944: the catch-up notes that it is done")
check(dbx("SELECT COUNT(*) FROM pl_imported WHERE dup=1")[0][0] == 1, "the duplicate is remembered")

# again: nothing new
r = A.post(B + "/api/paperless/import", json={"ws": "private"})
j = run_idle(A)
run = (j or {}).get("conn", {}).get("run", {})
check(run.get("new") == 0 and run.get("skipped") == 3 and len(docs(A)) == 2, f"a second import brings nothing twice ({run})")
check(A.get(B + "/api/paperless/preview?ws=private").json().get("already") == 3, "preview counts what came in")

# ---- 2.56.4 (#1859): a server without any version in common -> a readable reason, not "(406)"
PLDATA["versions"] = ["11"]
pl_write()
r = A.put(B + "/api/paperless", json={"ws": "private", "token": "pl-secret"})
check(r.status_code == 400 and "API version" in r.json().get("error", "") and "406" not in r.json().get("error", ""),
      f"no common API version: refused with a readable reason ({r.status_code} {r.text[:200]})")

# ---- an old server (API up to 5, select options as a plain list, the value its index): Kalmido falls back to 5
PLDATA["versions"] = ["1", "2", "3", "4", "5"]
PLDATA["custom_fields"][1]["extra_data"] = {"select_options": ["Open", "Paid", "Overdue"]}
PLDATA["documents"].append(doc(14, "New letter", content="A new letter", tags=[1], created="2025-06-02T23:30:00+02:00",
                               custom_fields=[{"field": 5, "value": 2}]))
pl_write()
open(os.path.join(DATA, "pl.log"), "w").close()
r = A.put(B + "/api/paperless", json={"ws": "private", "token": "pl-secret", "follow": True, "every_min": 15})
check(r.ok and r.json()["conn"]["follow"] is True, f"old server: connected again, following switched on ({r.status_code} {r.text[:200]})")
acc = [x.get("accept") or "" for x in pl_log() if x.get("auth")]
check(any(a.endswith("version=5") for a in acc), f"old server: falls back to API version 5 ({acc[:4]})")
dbx("UPDATE pl_sources SET synced_at='2000-01-01T00:00:00+00:00' WHERE ws LIKE 'u%'", write=True)
check(until(lambda: any(d["name"] == "New letter.pdf" and d["state"] in ("done", "failed") for d in docs(A)), 60),
      "following: the new document came in by itself")  # 2.80.3: and is recognised (an import makes its preview since 2.80.2)
nl = next((d for d in docs(A) if d["name"] == "New letter.pdf"), None)
if nl:
    t3 = A.get(B + f"/api/docs/{nl['id']}").json().get("text") or ""
    check("Status: Overdue" in t3 and nl["date"] == "2025-06-02", f"old server: select option by index, date of a timestamp ({nl['date']}, {t3[:200]!r})")
log = pl_log()
check(log and all(x["m"] == "GET" for x in log), f"Kalmido only reads in Paperless-ngx ({sorted({x['m'] for x in log})})")
check(any("version=" in (x.get("accept") or "") for x in log), "API version header sent")

# ---- stop
r = A.post(B + "/api/paperless/import", json={"ws": "private"})
r = A.post(B + "/api/paperless/stop", json={"ws": "private"})
check(r.ok and r.json()["conn"]["run"]["state"] in ("idle", "stop"), f"stop ({r.text[:200]})")
check(run_idle(A), "after Stop the run ends")

# ---- rights
j = Ca.get(B + f"/api/paperless?ws=org:{ORG}").json()
check(j.get("can_manage") is False, "an organisation member sees the section, cannot manage")
r = Ca.put(B + "/api/paperless", json={"ws": f"org:{ORG}", "url": PL, "token": "pl-secret"})
check(r.status_code == 403, f"a member cannot connect the organisation ({r.status_code})")
# tenant-matrix: paperless
check(Er.get(B + f"/api/paperless?ws=org:{ORG}").status_code == 404, "not across workspaces: outsiders 404")
r = Bo.put(B + "/api/paperless", json={"ws": f"org:{ORG}", "url": PL, "token": "pl-secret"})
check(r.ok, f"the organisation's admin connects ({r.status_code} {r.text[:200]})")
r = Bo.post(B + "/api/paperless/import", json={"ws": f"org:{ORG}"})
check(r.ok, "the admin imports into the organisation")
run_idle(Bo, f"org:{ORG}")
od = docs(Bo, f"org:{ORG}")
check(len(od) == 3 and all(d["org_id"] == ORG for d in od), f"organisation import: in the organisation's documents ({len(od)})")
od = until(lambda: (lambda x: x if len(x) == 3 and all(d["state"] in ("done", "failed") for d in x) else None)(docs(Bo, f"org:{ORG}")), 60) or od
check(all(d.get("thumb") for d in od) and Bo.get(B + f"/api/docs/{od[0]['id']}/thumb").content[:2] == b"\xff\xd8",
      "#1944: the organisation's imports have their previews (sealed with the organisation's key, the route opens them)")
check(not any(d["org_id"] == ORG for d in docs(A, "all")), "alice (no member) sees none of them")
check(len(docs(A)) == 3, "the private import is untouched")
r = Er.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.ok, f"a person without an organisation connects their own space ({r.status_code})")
ag = requests.Session()
ag.headers.update({**H, "Authorization": "Bearer " + AGT})
check(ag.get(B + "/api/paperless?ws=private").status_code in (401, 403, 404), "an agent has no connection")
check(Er.delete(B + "/api/paperless?ws=private").json().get("conn") is None, "disconnect")

# ---- a hosted server: 2.69.0 (#1846): the connection is there too, but only for public HTTPS addresses (p269_a_api_test.py)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**env, "KEEP": "1", "EXTRA": env["EXTRA"] + " -e KALMIDO_HOSTED=1 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="})
A = sess("alice")
check(A.get(B + "/api/paperless?ws=private").json().get("available") is True, "hosted: available (2.69.0)")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.status_code == 400 and "public HTTPS" in r.json().get("error", ""), f"hosted: an http:// address refused (2.69.0) ({r.status_code} {r.text[:200]})")

# ---- 2.48.0 review (S2): without a server key the token is not stored at all
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env={**env, "KEEP": "1", "EXTRA": BASE_EXTRA})
A = sess("alice")
r = A.put(B + "/api/paperless", json={"ws": "private", "url": PL, "token": "pl-secret"})
check(r.status_code == 409 and "server key" in r.json().get("error", ""), f"no server key: 409 ({r.status_code} {r.text[:120]})")

print(f"p248_d_paperless_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
