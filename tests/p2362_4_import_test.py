#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.362.4 (#3100): the account import leaves no id of the old server behind and a full storage stops only the files.
Invented names only (example.com). A person without an organisation (freelancer, P4) exports a project with a mention, a saved
filter, a template, a person, a task and a formula field and a large attachment; other people import it:
 - a mention of a person who did not come along is plain text, my own mention and a ticked person's point at the new account
 - a saved filter carries the new project / section / field ids, a filter on what did not come along is left out, not widened
 - a template keeps only what a new template stores
 - person and task field values and formulas carry new ids
 - a full storage leaves out the file; time entries, habits, contacts and the journal after it still come, the state says stopped
 - a checksum that goes wrong while the run writes removes the files written so far
 - a run of imports never takes the undo of an import that is younger than the undo window
usage: p2362_4_import_test.py <datadir>"""
# freelancer-matrix: own
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from io import BytesIO

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}


def ok(r, what):
    check(r.status_code in (200, 201, 202, 204), f"{what}: {r.status_code} {r.text[:200]}")
    return r.json() if r.content else {}


def db():
    return dbxm.connect(DATA)


def rows(sql, args=()):
    return db().execute(sql, args).fetchall()


def export_of(s):
    assert s.post(B + "/api/account/export").status_code == 202
    j = {}
    for _ in range(480):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "frida.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid):
    j = {}
    for _ in range(960):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def run(s, iid, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": people or {}, "again": True})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def texts(j):
    return " | ".join(w["text"] for w in (j.get("result") or {}).get("warnings") or [])


def stored_files():
    out = set()
    for d, _s, fs in os.walk(os.path.join(DATA, "attachments")):
        out.update(os.path.join(d, f) for f in fs)
    return out


# ---------------------------------------------------------------- server, people
env = dict(os.environ)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
FRIDA, F = freelancer(B, A, "frida")
BOB, Bo = freelancer(B, A, "bob")
GINA, G = freelancer(B, A, "gina")
HENRY, He = freelancer(B, A, "henry")
ILSE, Il = freelancer(B, A, "ilse")
JUDY, Ju = freelancer(B, A, "judy")
BIG = os.urandom(700 << 10)  # two of these do not fit into 1 MB (and do not compress)

# ---------------------------------------------------------------- the project of frida
LP = ok(F.post(B + "/api/lists", json={"name": "Umzug Projekt", "kind": "project"}), "project")["id"]
check(F.put(B + f"/api/lists/{LP}/members", json={"user_id": BOB, "role": "edit"}).ok, "shared with bob")
LB = ok(Bo.post(B + "/api/lists", json={"name": "Bobs Liste"}), "a list of bob")["id"]
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": FRIDA, "role": "edit"}).ok, "bob shares with frida")
SEC = ok(F.post(B + "/api/sections", json={"list_id": LP, "name": "Abschnitt"}), "section")["id"]
FA = ok(F.post(B + f"/api/lists/{LP}/fields", json={"name": "Menge", "type": "number"}), "number field")["id"]
FB = ok(F.post(B + f"/api/lists/{LP}/fields", json={"name": "Preis", "type": "number"}), "number field 2")["id"]
FP = ok(F.post(B + f"/api/lists/{LP}/fields", json={"name": "Wer", "type": "person"}), "person field")["id"]
FT = ok(F.post(B + f"/api/lists/{LP}/fields", json={"name": "Bezug", "type": "task"}), "task field")["id"]
FX = ok(F.post(B + f"/api/lists/{LP}/fields", json={"name": "Summe", "type": "formula", "formula": "{Menge}*{Preis}"}), "formula field")["id"]
T1 = ok(F.post(B + "/api/tasks", json={"list_id": LP, "title": "Erste", "section_id": SEC}), "task")["id"]
T2 = ok(F.post(B + "/api/tasks", json={"list_id": LP, "title": "Zweite"}), "task 2")["id"]
ok(F.patch(B + f"/api/tasks/{T2}", json={"fields": {str(FP): BOB, str(FT): T1, str(FA): 3, str(FB): 4}}), "field values")
ok(F.post(B + f"/api/tasks/{T1}/comments", json={"body": f"Danke <@{FRIDA}> und <@{BOB}>"}), "comment with mentions")
check(f"<@{BOB}>" in rows("SELECT body FROM comments WHERE task_id=?", (T1,))[0]["body"], "the token is stored")
ok(F.post(B + "/api/filters", json={"name": "Passt", "rules": {"lists": [LP], "secs": [SEC, "none"], "who": [FRIDA, BOB, "none"],
                                                                "sprints": ["cur", 77], "cf": {str(FA): {"num": {"op": "set"}}}}}), "filter")
ok(F.post(B + "/api/filters", json={"name": "Nur Bob", "rules": {"lists": [LB]}}), "filter on a list that stays behind")
ok(F.post(B + "/api/templates", json={"list_id": LP, "name": "Vorlage"}), "template")
for nm in ("gross1.bin", "gross2.bin"):
    ok(F.post(B + f"/api/tasks/{T1}/attachments", files={"file": (nm, BIG, "application/octet-stream")}), "a large file")
now = datetime.now(timezone.utc).replace(microsecond=0)
ok(F.post(B + "/api/habits", json={"name": "Lesen"}), "habit")
db().execute("""INSERT INTO time_entries(user_id,task_id,start,"end",seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
             (FRIDA, T1, "2026-10-01T08:00:00Z", "2026-10-01T09:00:00Z", 3600, "2026-10-01T09:00:00Z", "2026-10-01T09:00:00Z"))
EXP = export_of(F)


man = json.loads(zipfile.ZipFile(BytesIO(EXP)).read("manifest.json"))
# 2.362.4 (#3107): sprints are in the account export since #3469, chat_saves is still left out
check(any("chat_saves" in x and "not yet" in x for x in man["not_included"]), f"#3107: the manifest names the tables left out: {man['not_included'][-1]}")
check(not any("sprints" in x for x in man["not_included"]), f"#3107: what is exported is not named as left out: {man['not_included']}")


def new_list(uid):
    return rows("SELECT id FROM lists WHERE owner_id=? AND name=?", (uid, "Umzug Projekt"))[0]["id"]


# ---------------------------------------------------------------- nobody ticked, the storage full
iid = upload(G, EXP)
j = wait(G, iid)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
db().execute("UPDATE users SET storage_quota_mb=1 WHERE id=?", (GINA,))  # after the upload: it counts against the storage too
j = run(G, iid)
check(j.get("state") == "stopped", f"a full storage: state stopped ({j.get('state')}: {j.get('error')})")
res = j.get("result") or {}
check("some files were left out" in (res.get("stopped") or ""), f"the text says what is missing: {res.get('stopped')}")
check("left out because your storage is full" in texts(j), f"the file is named in the warnings: {texts(j)}")
LG = new_list(GINA)
check(rows("SELECT COUNT(*) FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=?", (LG,))[0][0] == 1, "the file that no longer fits stayed out")
check(rows("SELECT COUNT(*) FROM time_entries WHERE user_id=?", (GINA,))[0][0] == 1, "#3100: the time entry after the file came along")
check(rows("SELECT COUNT(*) FROM habits WHERE user_id=?", (GINA,))[0][0] == 1, "#3100: the habit after the file came along")
check(rows("SELECT COUNT(*) FROM filters WHERE user_id=?", (GINA,))[0][0] == 1, "#3100: filters after the file came along")
check(rows("SELECT COUNT(*) FROM templates WHERE user_id=?", (GINA,))[0][0] == 1, "#3100: templates after the file came along")
body = rows("SELECT c.body FROM comments c JOIN tasks t ON t.id=c.task_id WHERE t.list_id=?", (LG,))[0]["body"]
check(f"<@{GINA}>" in body, f"my own mention points at my new account: {body}")
check("@Bob" in body and f"<@{BOB}>" not in body, f"a person not ticked is plain text: {body}")
t = {r["title"]: r["id"] for r in rows("SELECT id, title FROM tasks WHERE list_id=?", (LG,))}
f = {r["name"]: r for r in rows("SELECT id, name, options FROM list_fields WHERE list_id=?", (LG,))}
vals = {r["field_id"]: r["value"] for r in rows("SELECT field_id, value FROM task_field_values WHERE task_id=?", (t["Zweite"],))}
check(f["Wer"]["id"] not in vals, f"a person field of somebody not ticked stays empty: {vals}")
check(vals.get(f["Bezug"]["id"]) == str(t["Erste"]), f"the task field points at the new task: {vals}")
expr = json.loads(f["Summe"]["options"]).get("expr") or ""
check(f'#{f["Menge"]["id"]}' in expr and f"#{FA}" not in expr, f"the formula names the new fields: {expr}")
flt = rows("SELECT name, rules FROM filters WHERE user_id=?", (GINA,))
check([x["name"] for x in flt] == ["Passt"], f"a filter on what stayed behind is left out, not widened: {flt}")
check("saved filter" in texts(j) and "Nur Bob" in texts(j), f"and it is named: {texts(j)}")
ru = json.loads(flt[0]["rules"])
sec = rows("SELECT id FROM sections WHERE list_id=?", (LG,))[0]["id"]
check(ru["lists"] == [LG] and ru["secs"] == [sec, "none"], f"new project and section ids: {ru}")
check(ru["who"] == ["me", "none"], f"me stays me, a person not ticked goes: {ru}")
check(ru["sprints"] == ["cur"], f"never a sprint id: {ru}")
check(list(ru["cf"]) == [str(f["Menge"]["id"])], f"the field rule follows its field: {ru}")
tpl = json.loads(rows("SELECT data FROM templates WHERE user_id=?", (GINA,))[0]["data"])
check(tpl.get("fields") and "list_id" not in json.dumps(tpl), f"the template as a new one stores it: {sorted(tpl)}")

# ---------------------------------------------------------------- a ticked person
iid = upload(He, EXP)
j = wait(He, iid)
p = [x for x in j["preview"]["people"] if x["name"] == "Bob"]
check(p and p[0]["found"], f"bob is found: {j['preview']['people']}")
j = run(He, iid, {p[0]["key"]: {"share": True}})
check(j.get("state") == "done", f"import with a ticked person {j.get('state')} {j.get('error')}")
LH = new_list(HENRY)
body = rows("SELECT c.body FROM comments c JOIN tasks t ON t.id=c.task_id WHERE t.list_id=?", (LH,))[0]["body"]
check(f"<@{HENRY}>" in body and f"<@{BOB}>" in body, f"a ticked person stays a mention: {body}")
ru = json.loads(rows("SELECT rules FROM filters WHERE user_id=?", (HENRY,))[0]["rules"])
check(ru["who"] == ["me", BOB, "none"], f"a ticked person stays in the filter: {ru}")
check(rows("SELECT COUNT(*) FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=?", (LH,))[0][0] == 2, "without a limit both files come")

# ---------------------------------------------------------------- a checksum that goes wrong during the run
ok(F.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("zweite.bin", os.urandom(4096), "application/octet-stream")}), "a second file")
src = zipfile.ZipFile(BytesIO(export_of(F)))
buf = BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
    for zi in src.infolist():
        z.writestr(zipfile.ZipInfo(zi.filename), src.read(zi))
raw = bytearray(buf.getvalue())
names = [x for x in zipfile.ZipFile(BytesIO(bytes(raw))).namelist() if x.startswith("files/attachments/")]
last = next(x for x in names if x.endswith("zweite.bin"))
check(names.index(last) == len(names) - 1 or len(names) == 2, f"the broken file is not the only one: {names}")
iid = upload(Il, bytes(raw))
j = wait(Il, iid)
check(j.get("state") == "preview", f"preview of the stored file {j.get('state')} {j.get('error')}")
z = zipfile.ZipFile(BytesIO(bytes(raw)))
zi = z.getinfo(last)
fn, ex = struct.unpack("<HH", raw[zi.header_offset + 26:zi.header_offset + 30])
at = zi.header_offset + 30 + fn + ex
raw[at] ^= 0xff
crc = zlib.crc32(bytes(raw[at:at + zi.file_size]))
pos = z.start_dir
while True:  # the entry of the file in the central directory: zipfile checks the CRC from there
    n, m, k = struct.unpack("<HHH", raw[pos + 28:pos + 34])
    if bytes(raw[pos + 46:pos + 46 + n]) == last.encode():
        raw[pos + 16:pos + 20] = struct.pack("<I", crc)
        break
    pos += 46 + n + m + k
with open(os.path.join(DATA, "exports", "account-import", str(ILSE), iid, "upload.bin"), "r+b") as fh:
    fh.write(raw)
before = stored_files()
j = run(Il, iid)
check(j.get("state") == "invalid" and "Checksum" in (j.get("error") or ""), f"the run ends as invalid ({j.get('state')}: {j.get('error')})")
check(stored_files() == before, f"#3100: no file of the run stayed ({len(stored_files() - before)} left)")
check(not rows("SELECT 1 FROM lists WHERE owner_id=? AND name=?", (ILSE, "Umzug Projekt")), "nothing of the run stayed in the database")

# ---------------------------------------------------------------- a crafted file, a ticked person who never joins the project
def tampered(zdata, edit):
    """The export with its parts changed by edit({part: rows}), with a matching manifest and checksums."""
    zs = zipfile.ZipFile(BytesIO(zdata))
    parts = {n[5:-5]: json.loads(zs.read(n)) for n in zs.namelist() if n.startswith("data/") and n.endswith(".json")}
    edit(parts)
    files = {n: zs.read(n) for n in zs.namelist() if n not in ("manifest.json", "checksum.sha256")}
    files.update({f"data/{k}.json": json.dumps(v).encode() for k, v in parts.items()})
    m = json.loads(zs.read("manifest.json"))
    m["files"] = [{"path": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]
    mb = json.dumps(m).encode()
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", "\n".join(f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in [("manifest.json", mb), *files.items()]) + "\n")
    return out.getvalue()


def craft(p):
    for r in p["comments"]:
        r["body"] = 5
    for r in p["filters"]:
        r["rules"] = "[" * 100000
    for r in p["templates"]:
        r["data"] = "[" * 100000
    for r in p["list_fields"]:
        if r["type"] == "number":
            r["options"] = "x"
    for r in p["people"]:
        r["lists"] = {}


KE, Ke = freelancer(B, A, "kerstin")
iid = upload(Ke, tampered(EXP, craft))
j = wait(Ke, iid)
check(j.get("state") == "preview", f"preview of the crafted file {j.get('state')} {j.get('error')}")
j = run(Ke, iid)
check(j.get("state") == "done", f"review: broken JSON from a file never fails the run ({j.get('state')}: {j.get('error')})")
check(rows("SELECT body FROM comments c JOIN tasks t ON t.id=c.task_id WHERE t.list_id=?", (new_list(KE),))[0]["body"] == "5", "the body is coerced to text")


def nolists(p):
    for r in p["people"]:
        r["lists"] = {}


LO, Lo = freelancer(B, A, "lotte")
iid = upload(Lo, tampered(EXP, nolists))
j = wait(Lo, iid)
p = [x for x in j["preview"]["people"] if x["name"] == "Bob"]
j = run(Lo, iid, {p[0]["key"]: {"share": True}})
check(j.get("state") == "done", f"ticked without a project {j.get('state')} {j.get('error')}")
LL = new_list(LO)
body = rows("SELECT c.body FROM comments c JOIN tasks t ON t.id=c.task_id WHERE t.list_id=?", (LL,))[0]["body"]
check("@Bob" in body and "<@" + str(BOB) not in body, f"review: a person who did not join the project is plain text: {body}")
check(not rows("SELECT 1 FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE f.list_id=? AND f.type='person'", (LL,)),
      "review: and no person field keeps them")

# ---------------------------------------------------------------- the import records
old = (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
young = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
for i in range(26):  # the first three past the undo window, then more young ones than IMPORT_KEEP
    db().execute("INSERT INTO imports(user_id,source,file_name,created,report,created_at) VALUES(?,?,?,?,?,?)",
                 (JUDY, "csv", f"f{i}.csv", "{}", "{}", old if i < 3 else young))
r = Ju.post(B + "/api/import/csv", files={"file": ("a.csv", b"title\nEine Aufgabe\n", "text/csv")})
ok(r, "one more import")
left = rows("SELECT file_name FROM imports WHERE user_id=?", (JUDY,))
names = {x["file_name"] for x in left}
check(len(left) == 24, f"#3100: the 23 young records and the new one stay ({len(left)})")
check(not names & {"f0.csv", "f1.csv", "f2.csv"}, f"the old ones past the limit go: {sorted(names)[:4]}")
lst = Ju.get(B + "/api/imports").json()["imports"]
check(len(lst) == 24 and sum(1 for x in lst if x["can_undo"]) == 24, f"the list shows every one that can be undone ({len(lst)})")

print(f"p2362_4_import: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
