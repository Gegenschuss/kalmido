#!/usr/bin/env python3
"""2.73.0 part B (#1473): moving an account -- the account export (one ZIP) and its import on another server. Invented names only.
 - export: a person starts it, polls, downloads, deletes; the ZIP has manifest.json (format kalmido-account, v 1), data/*.json,
   files/ and checksum.sha256 (every SHA-256 and size right); the own lists with tasks, subtask, dependency, comments,
   attachments (also the sealed one of an organisation list, decrypted), calendar, contact, habit; a list another person shares
   with me only as a reference with my own comment there; no list of others, no secrets (column names); sealed on disk (0600);
   another person 404, an agent token 401/403; GET /api/export.json unchanged
 - import into another person (private): the upload in pieces (wrong offset 409, another person's upload 404), the preview
   (counts, people found by the hash of their address -- review M1: no address of others in the file or the preview, again-warning), target checks (an organisation without admin rights 403, a foreign one
   404), everything created anew with new ids, subtask + dependency mapped, the comment authors mapped (me -> me, a ticked
   person -> that person), a found person shared only with a tick, the attachment readable; the upload is gone afterwards;
   undo removes everything (also the files)
 - import into an organisation the person administers: the lists belong to it, the attachment is sealed on disk
 - a crafted file: ids / owner / org / author from the file are ignored, wrong types fall back, cycles and lists that are not
   in the file are dropped; a missing person is invited only by an instance admin
 - attacks: no ZIP, path traversal, duplicate part, encrypted ZIP, ZIP bomb, deep JSON, wrong checksum, missing file, wrong
   format, newer version, too large, too many rows in one table, storage quota before the upload and in the middle of the run (stops, undo possible)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY and the mode workspaces.
usage: p273_b_api_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
SECRET = {"password_hash", "password", "token", "token_hash", "secret", "hook_secret", "totp_secret", "p256dh", "auth", "endpoint",
          "api_key", "access_token", "refresh_token", "drop_token", "ical_token", "code_hash", "webauthn_handle", "oidc_subject", "token_enc"}


def EH(email):  # review M1: other people's addresses only as this hash
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)
        if len(FAILS) == 1:  # the server's side of the first failure (a traceback of the import thread)
            ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
            print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True).stdout[-6000:], flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def export_of(s, secs=120):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = s.get(B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def upload(s, data, piece=1 << 20, name="kalmido-account.zip"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + piece]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def run(s, iid, target="private", people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": people or {}})
    assert r.status_code == 202, r.text
    return wait(s, iid)


def mkzip(tables, files=None, man=None, tamper=None, drop=None, extra=(), dup=None, manifest_raw=None):
    """A crafted account export (invented data)."""
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    entries.update(files or {})
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": "2026-10-17T06:00:00Z",
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": 1000, "name": "Test Person", "email": "test@example.com"},
         "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    m.update(man or {})
    mb = manifest_raw if manifest_raw is not None else json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    if tamper:
        entries[tamper] = entries[tamper] + b" "
    if drop:
        del entries[drop]
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs)
        for p, b in entries.items():
            z.writestr(p, b)
        for p, b in extra:
            z.writestr(p, b)
        if dup:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                z.writestr(dup, b"[]")
    return bio.getvalue()


def bad(s, data, what, code=None):
    """The file is refused before the preview (state invalid with a message)."""
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "invalid" and j.get("error"), f"attack refused: {what} ({j.get('state')}: {j.get('error')})")
    s.delete(B + f"/api/account/import/{iid}")


# 2.73.0 (#1473) review M2: a small row limit per table, so the test can go just above it
MAX_ROWS = 5000
env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_ACCOUNT_IMPORT_MAX_ROWS={MAX_ROWS}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Umzug", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Mitglied"), ("carol", "Carol Fremd"), ("dave", "Dave Neu"), ("erin", "Erin Privat")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,contacts,habits,deps,events,fields,time,health", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Umzug", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
for u in ("bob", "dave"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta Fremd", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}

# ---------------------------------------------------------------- alice's data
LP = A.post(B + "/api/lists", json={"name": "Umzug Privatliste", "org_id": None, "kind": "project"}).json()["id"]
check(A.put(B + f"/api/lists/{LP}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "alice shares her private list with bob")
T1 = A.post(B + "/api/tasks", json={"title": "Umzugskartons packen", "list_id": LP, "priority": 3}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Kartons beschriften", "list_id": LP, "parent_id": T1}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Moebelwagen buchen", "list_id": LP}).json()["id"]
r = A.post(B + "/api/deps", json={"task_id": T1, "blocker_id": T3})
check(r.ok, "dependency T1 waits on T3 " + r.text[:120])
check(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Kommentar von Alice"}).ok, "alice comments")
check(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "Kommentar von Bob"}).ok, "bob comments")
ATT = b"Packliste " + os.urandom(16).hex().encode()
r = A.post(B + f"/api/tasks/{T1}/attachments", files=[("file", ("packliste.txt", ATT, "text/plain"))])
check(r.ok, "attachment " + r.text[:100])
for i in (1, 2):  # random (the server takes 1 MB per file in the tests): the ZIP gets > 1 MiB -> the upload takes two pieces
    r = A.post(B + f"/api/tasks/{T3}/attachments", files=[("file", (f"angebot{i}.bin", os.urandom(800_000), "application/octet-stream"))])
    check(r.ok, f"big attachment {i} {r.text[:120]}")
LO = A.post(B + "/api/lists", json={"name": "Alpha Orgliste", "org_id": ORG}).json()["id"]
TO = A.post(B + "/api/tasks", json={"title": "Orgaufgabe Uebergabe", "list_id": LO}).json()["id"]
OATT = b"Org-Datei " + os.urandom(8).hex().encode()
check(A.post(B + f"/api/tasks/{TO}/attachments", files=[("file", ("org.txt", OATT, "text/plain"))]).ok, "org attachment")
odir = os.path.join(DATA, "attachments", str(TO))
check(open(os.path.join(odir, os.listdir(odir)[0]), "rb").read(6) == b"KENC1\n", "the org attachment is sealed on disk")
r = A.post(B + "/api/life/health", json={"type": "appointment", "title": "Zahnarzt Umzug", "date": "2026-11-03"})
check(r.status_code == 201, "a health appointment (Home & life) " + r.text[:120])
LH = (dbx("SELECT id FROM lists WHERE owner_id=? AND life='health'", (ALICE,)) or [{"id": 0}])[0]["id"]
KA = A.post(B + "/api/evcals", json={"name": "Umzugskalender"}).json()["id"]
check(A.post(B + "/api/events", json={"title": "Schluesseluebergabe", "start": "2026-11-02T10:00", "end": "2026-11-02T11:00", "cal_id": KA}).ok, "event")
BK = A.post(B + "/api/books", json={"name": "Umzugshelfer"}).json()["id"]
check(A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Hanna Helferin", "emails": [{"value": "hanna@example.com"}]}).status_code == 201, "contact")
check(A.post(B + "/api/habits", json={"name": "Jeden Tag ein Karton"}).ok, "habit")
LC = Bo.post(B + "/api/lists", json={"name": "Bob Geheimliste", "org_id": None}).json()["id"]
TC = Bo.post(B + "/api/tasks", json={"title": "Bob Geheimaufgabe", "list_id": LC}).json()["id"]
r = Bo.put(B + f"/api/lists/{LC}/members", json={"user_id": ALICE, "role": "edit"})
check(r.ok, "bob shares a list with alice " + r.text[:120])
check(A.post(B + f"/api/tasks/{TC}/comments", json={"body": "Alice schreibt bei Bob"}).ok, "alice comments on bob's list")
LCC = Ca.post(B + "/api/lists", json={"name": "Carol Geheimliste", "org_id": None}).json()["id"]
LE = Er.post(B + "/api/lists", json={"name": "Erin Privatsache", "org_id": None}).json()["id"]

# ---------------------------------------------------------------- export: rights
P = "/api/account/export"
check(requests.post(B + P, headers=AGH).status_code in (401, 403) and requests.get(B + P, headers=AGH).status_code in (401, 403), "agent token refused")
check(requests.post(B + "/api/account/import", headers=AGH, json={"size": 100}).status_code in (401, 403), "agent token: no import")
check(requests.get(B + "/api/v1/account/export", headers=AGH).status_code in (403, 404, 405), "nothing of it in the agent API")
check(A.get(B + P).json().get("state") == "none", "no export yet")
# 2.73.0 (#1473) review N5: a webhook address and a server-only setting
WHU = "https://hooks.example.com/services/T000/Geheimpfad0815"
check(A.post(B + "/api/me/webhooks", json={"name": "Umzug Hook", "url": WHU, "events": ["task.created"]}).status_code == 201, "N5: webhook")
check(A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "umzugtopic4711"}).ok, "N5: ntfy topic (admin)")
EXP = export_of(A)
check(Bo.get(B + P + "/file").status_code == 404, "bob cannot download (he has none, alice's is not his)")
ad = os.path.join(DATA, "exports", "account", str(ALICE))
af = [f for f in os.listdir(ad) if f.endswith(".zip")]
check(len(af) == 1 and open(os.path.join(ad, af[0]), "rb").read(13) == b"KALMIDO-UMZ1\n", f"the export is sealed on disk {af}")
check(len(af) == 1 and (os.stat(os.path.join(ad, af[0])).st_mode & 0o777) == 0o600, "the export file is 0600")

# ---------------------------------------------------------------- export: content
z = zipfile.ZipFile(io.BytesIO(EXP))
names = set(z.namelist())
man = json.loads(z.read("manifest.json"))
check(man["format"] == "kalmido-account" and man["v"] == 1 and man["user"]["email"] == "alice@example.com" and man["export_id"], "manifest head")
sums = dict(reversed(line.split("  ", 1)) for line in z.read("checksum.sha256").decode().splitlines())
check(sums.get("manifest.json") == sha(z.read("manifest.json")), "checksum of manifest.json")
okf = all(sha(z.read(f["path"])) == f["sha256"] and len(z.read(f["path"])) == f["size"] and sums.get(f["path"]) == f["sha256"] for f in man["files"])
check(okf and len(man["files"]) >= 10, "every file: SHA-256 + size in manifest and checksum.sha256")
D = {n[5:-5]: json.loads(z.read(n)) for n in names if n.startswith("data/")}
titles = {t["title"] for t in D["tasks"]}
check({"Umzugskartons packen", "Kartons beschriften", "Moebelwagen buchen", "Orgaufgabe Uebergabe"} <= titles, "own tasks in it")
check("Bob Geheimaufgabe" not in titles and not any(L["name"] in ("Bob Geheimliste", "Carol Geheimliste", "Erin Privatsache") for L in D["lists"]),
      "no lists / tasks of other people")
# 2.73.0 (#1473) review M1: the owner's address only as a hash
check(any(x["name"] == "Bob Geheimliste" and x["owner_email_hash"] == EH("bob@example.com") and "owner_email" not in x for x in D["shared_lists"]),
      "bob's list as a reference")
check([x["body"] for x in D["shared_comments"]] == ["Alice schreibt bei Bob"], "my comment on bob's list (Art. 15)")
check({"Kommentar von Alice", "Kommentar von Bob"} <= {x["body"] for x in D["comments"]}, "comments of my lists")
check(any(p["email_hash"] == EH("Bob@Example.com ") and "email" not in p and str(LP) in p["lists"] for p in D["people"]), "bob among the people (mapping)")
check(not any(b"bob@example.com" in z.read(n) or b"carol@example.com" in z.read(n) for n in names if not n.startswith("files/")),
      "no address of another person anywhere in the file (review M1)")
check(D["event_calendars"] and D["events"] and D["contacts"] and D["habits"], "calendar, event, contact, habit")
att = {a["name"]: a for a in D["attachments"]}
check(z.read(att["packliste.txt"]["file"]) == ATT and z.read(att["org.txt"]["file"]) == OATT, "attachments in it (the org one decrypted)")
check(not any(z.read(n)[:6] == b"KENC1\n" for n in names if n.startswith("files/")), "no sealed file in the ZIP")
leak = sorted({k for rows in D.values() for row in rows if isinstance(row, dict) for k in row if k in SECRET})
check(not leak, f"no secret columns: {leak}")
check(ag["token"].encode() not in EXP, "the agent token is not in the file")
check(not any(x.get("key") in ("ntfy_topic", "onboard", "digest_sent") for x in D["settings"]) and b"umzugtopic4711" not in z.read("data/settings.json"),
      "N5: no server-only settings")
check(any(x.get("url_hint") == "https://hooks.example.com/…" and "url" not in x for x in D["webhooks"]) and
      not any(b"Geheimpfad0815" in z.read(n) for n in names if not n.startswith("files/")), "N5: the webhook only as url_hint")
EJ = A.get(B + "/api/export.json").json()
check({"lists", "tasks", "comments", "attachments", "settings", "events", "contacts", "user"} <= set(EJ) and
      len(EJ["tasks"]) == len(D["tasks"]) and "shared_lists" not in EJ and any(x.get("url") == WHU for x in EJ.get("webhooks", [])),
      "GET /api/export.json unchanged")
check(A.delete(B + P).ok and A.get(B + P).json()["state"] == "none" and not os.path.isdir(ad), "delete the export now")
EXP = export_of(A)  # again for the imports

# ---------------------------------------------------------------- import into dave (private)
r = Da.post(B + "/api/account/import", json={"size": len(EXP), "name": "alice.zip"})
iid = r.json()["id"]
check(Da.put(B + f"/api/account/import/{iid}?offset=5", data=EXP[:1 << 20], headers={"Content-Type": "application/octet-stream"}).status_code == 409,
      "wrong offset 409")
check(Da.put(B + f"/api/account/import/{iid}?offset=0", data=EXP[:1000], headers={"Content-Type": "application/octet-stream"}).status_code == 400,
      "a middle piece that is no whole block 400")
Da.delete(B + f"/api/account/import/{iid}")
check(len(EXP) > 1 << 20, f"the export is larger than one piece ({len(EXP)})")
iid = upload(Da, EXP)
for s, nm in ((Bo, "bob"), (A, "alice")):
    check(s.get(B + f"/api/account/import/{iid}").status_code == 404 and s.delete(B + f"/api/account/import/{iid}").status_code == 404 and
          s.post(B + f"/api/account/import/{iid}/run", json={}).status_code == 404, f"{nm}: dave's upload 404")
j = wait(Da, iid)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
pv = j.get("preview") or {}
check(pv.get("counts", {}).get("tasks") == len(D["tasks"]) and pv.get("user", {}).get("email") == "alice@example.com" and not pv.get("again"),
      f"preview counts + source {pv.get('counts')}")
pb = [p for p in pv.get("people", []) if p["key"] == EH("bob@example.com")]
check(pb and pb[0]["found"] and pb[0]["found_name"] and "email" not in pb[0], f"bob found by the hash, no address in the preview {pb}")
check(not pv.get("can_invite"), "dave may not invite")
check({t["id"] for t in pv.get("targets", [])} == {"private"}, f"dave: only private (member, not admin of Alpha) {pv.get('targets')}")
check(Da.post(B + f"/api/account/import/{iid}/run", json={"target": ORG}).status_code == 403, "target: organisation without admin rights 403")
check(Da.post(B + f"/api/account/import/{iid}/run", json={"target": ORG2}).status_code == 404, "target: foreign organisation 404")
DAVE = ids["dave"]
j = run(Da, iid, people={EH("bob@example.com"): {"share": True}})
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
res = j.get("result") or {}
check(res.get("import_id") and res.get("created", {}).get("tasks") == len([t for t in D["tasks"] if not t.get("deleted_at")]),
      f"result {res.get('created')}")
check(not os.path.exists(os.path.join(DATA, "exports", "account-import", str(DAVE), iid, "upload.bin")), "the upload is gone after the run")
dl = {r_["name"]: r_ for r_ in dbx("SELECT id, name, org_id FROM lists WHERE owner_id=? AND is_inbox=0", (DAVE,))}
check({"Umzug Privatliste", "Alpha Orgliste"} <= set(dl) and all(dl[n]["org_id"] is None for n in ("Umzug Privatliste", "Alpha Orgliste")),
      f"dave's new lists, private {list(dl)}")
check(dl["Umzug Privatliste"]["id"] != LP, "new ids")
dt = {r_["title"]: r_ for r_ in dbx("SELECT id, title, parent_id, created_by, list_id FROM tasks WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?)", (DAVE,))}
check(dt["Kartons beschriften"]["parent_id"] == dt["Umzugskartons packen"]["id"], "subtask mapped")
check(all(x["created_by"] == DAVE for x in dt.values()), "created_by = the importing person")
check(dbx("SELECT 1 FROM task_deps WHERE task_id=? AND blocker_id=?", (dt["Umzugskartons packen"]["id"], dt["Moebelwagen buchen"]["id"])),
      "dependency mapped")
cm = {r_["body"]: r_["user_id"] for r_ in dbx("SELECT body, user_id FROM comments WHERE task_id=?", (dt["Umzugskartons packen"]["id"],))}
check(cm.get("Kommentar von Alice") == DAVE and cm.get("Kommentar von Bob") == ids["bob"], f"comment authors mapped {cm}")
check(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (dl["Umzug Privatliste"]["id"], ids["bob"])), "bob (ticked) shared")
check(not dbx("SELECT 1 FROM list_members WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?) AND user_id=?", (DAVE, ids["erin"])), "nobody else")
ar = dbx("SELECT id, path FROM attachments WHERE task_id=? AND name='packliste.txt'", (dt["Umzugskartons packen"]["id"],))
check(ar and Da.get(B + f"/api/attachments/{ar[0]['id']}").content == ATT, "the attachment is readable")
APATH = os.path.join(DATA, "attachments", ar[0]["path"]) if ar else ""
check(dbx("SELECT 1 FROM events e JOIN ev_cals k ON k.id=e.cal_id WHERE k.owner_id=? AND e.title='Schluesseluebergabe'", (DAVE,)), "event over")
check(dbx("SELECT 1 FROM contacts c JOIN books b ON b.id=c.book_id WHERE b.owner_id=? AND c.fn='Hanna Helferin'", (DAVE,)), "contact over")
check(dbx("SELECT 1 FROM habits WHERE user_id=? AND name='Jeden Tag ein Karton'", (DAVE,)), "habit over")
imp = Da.get(B + "/api/imports").json()["imports"]
check(imp and imp[0]["source_name"] == "Kalmido" and imp[0]["can_undo"], "listed under recent imports with undo")
# the same file again: a warning in the preview
iid2 = upload(Da, EXP)
j = wait(Da, iid2)
check(j.get("state") == "preview" and j["preview"]["again"], "the same export again: warning")
check(Da.delete(B + f"/api/account/import/{iid2}").ok and not os.path.isdir(os.path.join(DATA, "exports", "account-import", str(DAVE), iid2)),
      "cancel removes the upload at once")
# undo
r = Da.post(B + f"/api/imports/{res.get('import_id')}/undo")
check(r.ok and r.json().get("lists") >= 2, f"undo {r.text[:200]}")
check(not dbx("SELECT 1 FROM lists WHERE owner_id=? AND name IN ('Umzug Privatliste', 'Alpha Orgliste')", (DAVE,)) and
      not dbx("SELECT 1 FROM ev_cals WHERE owner_id=? AND name='Umzugskalender'", (DAVE,)) and
      not dbx("SELECT 1 FROM habits WHERE user_id=?", (DAVE,)), "undo: lists, calendar, habit gone")
check(APATH and not os.path.exists(APATH), "undo: the attachment file is gone")

# ---------------------------------------------------------------- import into an organisation (alice is its admin)
iid = upload(A, EXP)
j = wait(A, iid)
check(j.get("state") == "preview" and ORG in [t["id"] for t in j["preview"]["targets"]] and j["preview"]["can_invite"], "alice: Alpha is a target")
j = run(A, iid, target=ORG)
check(j.get("state") == "done", f"import into the organisation {j.get('error')}")
ol = dbx("SELECT id, org_id FROM lists WHERE owner_id=? AND name='Umzug Privatliste' AND id!=?", (ALICE, LP))
check(ol and ol[0]["org_id"] == ORG, "the list belongs to the organisation")
hl = dbx("SELECT org_id FROM lists WHERE owner_id=? AND life='health' AND id!=?", (ALICE, LH))
check(hl and hl[0]["org_id"] is None, "a Home & life list stays private, also with an organisation as target")
oa = dbx("SELECT a.path FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.name='packliste.txt'", (ol[0]["id"] if ol else 0,))
check(oa and open(os.path.join(DATA, "attachments", oa[0]["path"]), "rb").read(6) == b"KENC1\n", "the attachment is sealed (organisation key)")

# ---------------------------------------------------------------- part 4: an organisation export into another organisation
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
for _ in range(480):
    if A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
OX = A.get(B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ALICE})
GAMMA = r.json()["id"]
iid = upload(A, OX, name="alpha.kalmido-export")
j = wait(A, iid)
check(j.get("state") == "key" and j["preview"]["org"] == "Alpha Umzug", f"an organisation export asks for the recovery key {j.get('state')}")
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": "nonsense"}).status_code == 400, "not a recovery key 400")
check(Bo.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 404, "bob: alice's upload 404")
wrong = "-".join(["ABCD"] * 13)
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": wrong}).status_code == 202, "a wrong key is taken")
j = wait(A, iid)
check(j.get("state") == "key" and "Attempts left: 9" in (j.get("error") or ""), f"wrong key: asked again {j.get('error')}")
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the right key")
j = wait(A, iid)
pv = j.get("preview") or {}
check(j.get("state") == "preview" and pv.get("kind") == "org", f"opened: preview {j.get('state')} {j.get('error')}")
# 2.96.0 (#1941): an organisation export may go into the private space too (p296_d_api_test.py runs it)
check("private" in [t["id"] for t in pv.get("targets", [])] and GAMMA in [t["id"] for t in pv.get("targets", [])], "targets: private + organisations")
check(any(x["key"] == EH("bob@example.com") and x["found"] for x in pv.get("people", [])) and
      not any(x["key"] == EH("alice@example.com") for x in pv.get("people", [])) and not any("email" in x for x in pv.get("people", [])),
      "the members: bob found, alice herself not listed, no address in the preview")
j = run(A, iid, target=GAMMA, people={"bob@example.com": {"share": True}})  # a plain address as key (older client) still works
check(j.get("state") == "done", f"organisation import done {j.get('error')}")
gl = dbx("SELECT id, owner_id FROM lists WHERE org_id=? AND name='Alpha Orgliste'", (GAMMA,))
check(gl and gl[0]["owner_id"] == ALICE, "the list is in the target organisation")
ga = dbx("SELECT a.id, a.path FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.name='org.txt'", (gl[0]["id"] if gl else 0,))
check(ga and open(os.path.join(DATA, "attachments", ga[0]["path"]), "rb").read(6) == b"KENC1\n" and
      A.get(B + f"/api/attachments/{ga[0]['id']}").content == OATT, "the file: sealed with the new organisation's key, readable")
check(dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (GAMMA, ids["bob"])), "bob (ticked) joined the organisation")
check(not dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (GAMMA, DAVE)), "dave (not ticked) did not")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a crafted file: nothing from it is trusted
CAROL = ids["carol"]
ts = "2026-10-01T08:00:00Z"
crafted = mkzip({
    "lists": [{"id": 5, "name": "Fremdliste Test", "owner_id": CAROL, "org_id": ORG2, "is_inbox": 0, "created_at": ts, "sort": "x"}],
    "tasks": [{"id": 9, "list_id": 5, "title": "Fremdaufgabe Test", "created_by": CAROL, "assignee_id": CAROL, "priority": "hoch",
               "status": "x", "created_at": ts, "updated_at": ts, "org_id": ORG2},
              {"id": 10, "list_id": 5, "parent_id": 10, "title": "Selbstzyklus Test", "created_at": ts, "updated_at": ts},
              {"id": 11, "list_id": 999, "title": "Ohne Liste Test", "created_at": ts, "updated_at": ts},
              {"id": 12, "list_id": 5, "title": "x" * 100000, "created_at": ts, "updated_at": ts}],
    "comments": [{"id": 1, "task_id": 9, "user_id": CAROL, "body": "Fremder Kommentar Test", "created_at": ts}],
    "people": [{"user_id": 77, "name": "Frank Neu", "email": "frank@example.com", "lists": {"5": "edit"}},  # an older file: plain address
               # review M1: only hashes -- the admin types the address; a wrong one invites nobody
               {"user_id": 78, "name": "Gina Neu", "email_hash": EH("gina@example.com"), "lists": {"5": "edit"}},
               {"user_id": 79, "name": "Hugo Neu", "email_hash": EH("hugo@example.com"), "lists": {"5": "view"}},
               {"user_id": 80, "name": "Bob im Hash", "email_hash": EH("bob@example.com"), "lists": {}}],
})
iid = upload(A, crafted)
j = wait(A, iid)
pp = {p["key"]: p for p in (j.get("preview") or {}).get("people", [])}
check(j.get("state") == "preview" and not pp.get(EH("frank@example.com"), {}).get("found", True) and pp[EH("frank@example.com")]["need_address"] is False,
      "frank: not here (address in the older file)")
check(pp.get(EH("gina@example.com"), {}).get("need_address") is True and pp.get(EH("bob@example.com"), {}).get("found"), "gina: address needed; bob found by hash")
j = run(A, iid, people={EH("frank@example.com"): {"invite": True}, EH("gina@example.com"): {"invite": True, "email": "Gina@Example.com"},
                        EH("hugo@example.com"): {"invite": True, "email": "nothugo@example.com"}})
st = {p.get("name"): p.get("state") for p in (j.get("result") or {}).get("people", [])}
check(st.get("Gina Neu") == "invited" and st.get("Hugo Neu") == "mismatch" and not any("email" in p for p in j["result"]["people"]), f"invite states {st}")
check(dbx("SELECT 1 FROM users WHERE lower(email)='gina@example.com'") and not dbx("SELECT 1 FROM users WHERE email IN ('nothugo@example.com', 'hugo@example.com')"),
      "gina invited with the typed address, a wrong one invites nobody")
check(j.get("state") == "done", f"crafted import done {j.get('error')}")
fl = dbx("SELECT id, owner_id, org_id FROM lists WHERE name='Fremdliste Test'")
check(len(fl) == 1 and fl[0]["owner_id"] == ALICE and fl[0]["org_id"] is None, f"owner / org from the file ignored {[dict(zip(x.keys(), x)) for x in fl]}")
ft = dbx("SELECT created_by, assignee_id, priority, status, parent_id FROM tasks WHERE title='Fremdaufgabe Test'")
check(ft and ft[0]["created_by"] == ALICE and ft[0]["assignee_id"] is None and ft[0]["priority"] == 0 and ft[0]["status"] == 0,
      "created_by / assignee / wrong types from the file ignored")
check(dbx("SELECT parent_id FROM tasks WHERE title='Selbstzyklus Test'")[0]["parent_id"] is None, "a cycle becomes a main task")
check(not dbx("SELECT 1 FROM tasks WHERE title='Ohne Liste Test'"), "a task of a list that is not in the file is dropped")
check(len(dbx("SELECT title FROM tasks WHERE list_id=? AND title LIKE 'xxx%'", (fl[0]["id"] if fl else 0,))[0]["title"]) <= 2000, "a huge title is cut")
fc = dbx("SELECT user_id, ext_name FROM comments WHERE body='Fremder Kommentar Test'")
check(fc and fc[0]["user_id"] is None and fc[0]["ext_name"], "a foreign author stays a name, never the account with that id")
fr = dbx("SELECT id FROM users WHERE email='frank@example.com'")
check(fr and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (fl[0]["id"], fr[0]["id"])), "frank invited (instance admin) and shared")
check(dbx("SELECT 1 FROM user_invites WHERE user_id=?", (fr[0]["id"] if fr else 0,)), "frank has an invitation link")

# ---------------------------------------------------------------- 2.73.0 (#1473) review N4: a piece that broke off half-written
r = Da.post(B + "/api/account/import", json={"size": len(EXP), "name": "alice.zip"})
iid = r.json()["id"]
check(Da.put(B + f"/api/account/import/{iid}?offset=0", data=EXP[:1 << 20], headers={"Content-Type": "application/octet-stream"}).ok, "N4: piece 1")
with open(os.path.join(DATA, "exports", "account-import", str(DAVE), iid, "upload.bin"), "ab") as f:
    f.write(os.urandom(70000))  # the rest of a write that stopped in the middle (the state still says 1 MiB)
off = 1 << 20
while off < len(EXP):
    r = Da.put(B + f"/api/account/import/{iid}?offset={off}", data=EXP[off:off + (1 << 20)], headers={"Content-Type": "application/octet-stream"})
    check(r.ok, f"N4: piece at {off} {r.status_code}")
    off += 1 << 20
j = wait(Da, iid)
check(j.get("state") == "preview", f"N4: the leftover bytes were cut, the file checks fine ({j.get('state')}: {j.get('error')})")
Da.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- 2.73.0 (#1473) review N6: values in a form the app never writes
n6 = mkzip({
    "lists": [{"id": 1, "name": "Formatpruefung Test", "color": "rot", "created_at": ts}],
    "tasks": [{"id": 1, "list_id": 1, "title": "Kaputte Wiederholung", "due": "2026-99-99", "due_time": "25:99", "repeat": "FREQ=DAILY",
               "priority": 999, "reminders": "abc", "duration": -5, "repeat_from": "irgendwann", "created_at": "gestern", "updated_at": ts},
              {"id": 2, "list_id": 1, "title": "Gute Wiederholung", "due": "2026-10-20", "due_time": "09:30", "repeat": "RRULE:FREQ=WEEKLY",
               "priority": 3, "reminders": "15,0", "created_at": ts, "updated_at": ts},
              {"id": 3, "list_id": 1, "title": "Kaputte Regel", "due": "2026-10-20", "repeat": "FREQ=SECONDLY;INTERVAL=1", "created_at": ts,
               "updated_at": ts}],
    "habits": [{"id": 1, "name": "Formatgewohnheit", "color": "#12345", "remind_at": "abends", "days": "89", "goal": 0, "created_at": ts}],
})
iid = upload(Da, n6)
j = wait(Da, iid)
j = run(Da, iid) if j.get("state") == "preview" else j
check(j.get("state") == "done", f"N6: import done {j.get('state')} {j.get('error')}")
n6l = dbx("SELECT id, color FROM lists WHERE owner_id=? AND name='Formatpruefung Test'", (DAVE,))
check(n6l and n6l[0]["color"] in ("", None), f"N6: a wrong colour is left out {n6l and n6l[0]['color']}")
n6t = {r_["title"]: r_ for r_ in dbx("SELECT id, title, due, due_time, repeat, priority, reminders, duration, repeat_from, created_at FROM tasks "
                                     "WHERE list_id=?", (n6l[0]["id"] if n6l else 0,))}
kb, gu = n6t.get("Kaputte Wiederholung"), n6t.get("Gute Wiederholung")
check(kb and kb["due"] is None and kb["due_time"] is None and kb["priority"] == 0 and kb["reminders"] in ("", None) and kb["duration"] is None
      and kb["repeat_from"] == "due" and kb["created_at"] != "gestern", f"N6: broken values left out {kb and dict(zip(kb.keys(), kb))}")
check(gu and gu["due"] == "2026-10-20" and gu["due_time"] == "09:30" and gu["repeat"] == "FREQ=WEEKLY" and gu["priority"] == 3 and gu["reminders"] == "15,0",
      f"N6: valid values kept {gu and dict(zip(gu.keys(), gu))}")
check(n6t.get("Kaputte Regel") and not n6t["Kaputte Regel"]["repeat"], "N6: a rule the app refuses is left out")
for t_ in (kb, gu):
    r = Da.post(B + f"/api/tasks/{t_['id'] if t_ else 0}/complete", json={})
    check(r.ok, f"N6: {t_ and t_['title']} can be ticked off ({r.status_code} {r.text[:200]})")
hb = dbx("SELECT color, remind_at, days, goal FROM habits WHERE user_id=? AND name='Formatgewohnheit'", (DAVE,))
check(hb and hb[0]["color"] in ("", None) and hb[0]["remind_at"] == "" and hb[0]["days"] == "1234567" and hb[0]["goal"] == 1,
      f"N6: habit defaults {hb and dict(zip(hb[0].keys(), hb[0]))}")

# ---------------------------------------------------------------- 2.73.0 (#1473) review N7: the CardDAV path never from the file
n7 = mkzip({"lists": [], "address_books": [{"id": 1, "name": "Pfadbuch Test", "created_at": ts}],
            "contacts": [{"id": 1, "book_id": 1, "uid": "../boese uid/x", "fn": "Kontakt Pfad", "updated_at": ts},
                         {"id": 2, "book_id": 1, "uid": "gute-uid_1@example.com", "fn": "Kontakt Gut", "updated_at": ts}]})
iid = upload(Da, n7)
j = wait(Da, iid)
j = run(Da, iid) if j.get("state") == "preview" else j
check(j.get("state") == "done", f"N7: import done {j.get('state')} {j.get('error')}")
n7c = {r_["fn"]: dict(zip(r_.keys(), r_)) for r_ in dbx("SELECT c.fn, c.uid, c.href FROM contacts c JOIN books b ON b.id=c.book_id WHERE b.owner_id=? AND b.name='Pfadbuch Test'",
                                  (DAVE,))}
check(len(n7c) == 2 and all(re.fullmatch(r"[0-9a-f]{32}\.vcf", x["href"]) for x in n7c.values()), f"N7: href always new {n7c}")
check(n7c.get("Kontakt Pfad", {}).get("uid") != "../boese uid/x" and re.fullmatch(r"[A-Za-z0-9@._-]+", n7c.get("Kontakt Pfad", {}).get("uid") or "")
      and n7c.get("Kontakt Gut", {}).get("uid") == "gute-uid_1@example.com", "N7: a bad uid is replaced, a good one kept")

# ---------------------------------------------------------------- attacks
bad(Da, b"this is not a zip" * 100, "no ZIP")
bad(Da, mkzip({"lists": []}, extra=[("../evil.txt", b"x")]), "path traversal")
bad(Da, mkzip({"lists": []}, extra=[("/abs/evil.txt", b"x")]), "absolute path")
bad(Da, mkzip({"lists": []}, dup="data/lists.json"), "a part twice")
enc = bytearray(mkzip({"lists": []}))
for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
    i = enc.find(sig)
    while i >= 0:
        enc[i + off] |= 1
        i = enc.find(sig, i + 4)
bad(Da, bytes(enc), "encrypted ZIP")
bad(Da, mkzip({"lists": []}, files={"files/bomb.bin": b"\0" * 60_000_000}), "ZIP bomb")
bad(Da, mkzip({"lists": []}, manifest_raw=b"[" * 100000 + b"]" * 100000), "deep JSON")
bad(Da, mkzip({"lists": [{"id": 1, "name": "x"}]}, tamper="data/lists.json"), "wrong checksum")
bad(Da, mkzip({"lists": []}, files={"files/a.txt": b"abc"}, drop="files/a.txt"), "a file of the manifest is missing")
bad(Da, mkzip({"lists": []}, man={"format": "kalmido-org-export"}), "wrong format")
bad(Da, mkzip({"lists": []}, man={"v": 99}), "newer version")
bad(Da, mkzip({"lists": {"not": "a list"}}), "broken JSON types")
bad(Da, mkzip({"lists": [], "habits": [{"id": i} for i in range(MAX_ROWS + 1)]}), "one row above the limit per table (review M2)")
check(Da.post(B + "/api/account/import", json={"size": 5 * 1024 ** 4}).status_code == 413, "too large 413")
check(Da.post(B + "/api/account/import", json={"size": "big"}).status_code == 400, "size must be a number")
# storage quota: before the upload, and in the middle of the run (stops, undo possible)
check(A.patch(B + f"/api/users/{DAVE}", json={"storage_quota_mb": 1}).ok, "dave: 1 MB")
r = Da.post(B + "/api/account/import", json={"size": 2 * 1024 * 1024})
check(r.status_code == 413 and r.json().get("code") == "quota_exceeded", f"quota before the upload {r.status_code}")
big = b"Q" * 600_000  # (below the 1 MB per file of the tests)  # compresses well: the file is small, its attachments are not
qz = mkzip({"lists": [{"id": 1, "name": "Kontingent Test", "created_at": ts}],
            "tasks": [{"id": i, "list_id": 1, "title": f"Quota {i}", "created_at": ts, "updated_at": ts, "assignee_id": 55} for i in (1, 2, 3)],
            "comments": [{"id": 1, "task_id": 1, "user_id": 55, "body": "Bob im Kontingent", "created_at": ts}],
            "people": [{"user_id": 55, "name": "Bob aus der Datei", "email": "bob@example.com", "lists": {"1": "edit"}}],
            "attachments": [{"id": i, "task_id": i, "name": f"q{i}.txt", "file": f"files/attachments/{i}-q{i}.txt", "created_at": ts} for i in (1, 2, 3)]},
           files={f"files/attachments/{i}-q{i}.txt": big for i in (1, 2, 3)})
iid = upload(Da, qz)
j = wait(Da, iid)
j = run(Da, iid, people={"bob@example.com": {"share": True}}) if j.get("state") == "preview" else j
check(j.get("state") == "stopped" and j["result"].get("stopped") and j["result"].get("import_id"), f"quota in the run: stopped {j.get('state')}")
na = dbx("SELECT COUNT(*) AS n FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND l.name='Kontingent Test'",
         (DAVE,))[0]["n"]
check(na == 1, f"one file fitted ({na})")
qa = dbx("SELECT t.assignee_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND l.name='Kontingent Test'", (DAVE,))
qc = dbx("SELECT c.user_id, c.ext_name FROM comments c WHERE c.body='Bob im Kontingent'")
check(qa and all(x["assignee_id"] is None for x in qa) and qc and qc[0]["user_id"] is None and qc[0]["ext_name"] == "Bob aus der Datei",
      "stopped before the sharing: bob is neither assignee nor author in a list he cannot see")
check(Da.post(B + f"/api/imports/{j['result'].get('import_id')}/undo").ok and not dbx("SELECT 1 FROM lists WHERE owner_id=? AND name='Kontingent Test'", (DAVE,)),
      "undo after the stop")
A.patch(B + f"/api/users/{DAVE}", json={"storage_quota_mb": None})

print(f"p273_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
