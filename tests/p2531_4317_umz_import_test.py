#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.531.0 (#4317): the account import names what it cannot take over and never adds a row twice. Invented names only
(example.com). A crafted account export (old account id 1000) into a person without an organisation (freelancer_fixture):
 - F5: a part the import never reads (data/activity.json, larger than the 32 MiB of one part) no longer makes the file
   unimportable: the preview comes, it names the history with the row count of the manifest
 - F4: 60 different warnings (subtasks in another project): "These areas stay on the old server" still comes, first, and
   the result names more than 50 warnings
 - F6: approver and who set "waiting" (the person of the file = me) come along, a reviewer who is not here and a group of
   the old server stay empty with a warning naming the role
 - F7: a journal day written here already keeps its text, the file's entry is added below it and counted; the undo cuts it
   off again, the day the import created goes
 - F11: a row the database refuses (the same dependency twice in the file) is named with its area and number
 - F16: the same file a second time (confirmed): no second check-in, tag, follow or journal text and no refusal
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P4317_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2531_4317_umz_import_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
TS = "2026-10-20T06:00:00Z"
ME = 1000
DAY_OLD, DAY_NEW = "2026-10-10", "2026-10-11"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def mkzip(tables, counts):
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": TS,
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": ME, "name": "Test Person", "email": "test@example.com"},
         "tables": counts, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    mb = json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs.encode())
        for p, b in entries.items():
            z.writestr(p, b)
    return bio.getvalue()


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 300) or {}


def run(s, iid, again=False):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}, **({"again": True} if again else {})})
    check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
    return until(lambda: state_of(s, iid), 300) or {}


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def journal(s, day):
    j = s.get(B + "/api/life/journal", params={"from": day, "to": day}).json()
    return "\n".join(e.get("text") or "" for e in j.get("entries") or [] if e.get("day") == day)


# F4 + F5: one part the import never reads, larger than UMZ_JSON_MAX (32 MiB) on its own, and 60 different warnings
ACT = [{"id": i, "task_id": 11, "kind": "edit", "detail": "x" * 200, "created_at": TS} for i in range(160000)]
SUBS = [{"id": 100 + i, "list_id": 2, "parent_id": 11, "title": f"Unteraufgabe {i:02d}", "created_at": TS, "updated_at": TS} for i in range(60)]
BIG_T = {
    "lists": [{"id": 1, "name": "Umzug Eins", "created_at": TS}, {"id": 2, "name": "Umzug Zwei", "created_at": TS}],
    "tasks": [{"id": 11, "list_id": 1, "title": "Eltern", "created_at": TS, "updated_at": TS}] + SUBS,
    "activity": ACT,
}
BIG = mkzip(BIG_T, {t: len(r) for t, r in BIG_T.items()})
check(len(json.dumps(ACT)) > 32 * 1024 * 1024, "the history part is larger than one part may be")
TABLES = {
    "lists": [{"id": 1, "name": "Umzug Eins", "created_at": TS}],
    "tasks": [{"id": 11, "list_id": 1, "title": "Eltern", "created_at": TS, "updated_at": TS},
              {"id": 12, "list_id": 1, "title": "Rollen", "approver_id": ME, "approval": "pending", "reviewer_id": 2000,
               "assignee_group_id": 7, "wait_by": ME, "waiting_at": TS, "created_at": TS, "updated_at": TS}],
    "task_deps": [{"task_id": 12, "blocker_id": 11}, {"task_id": 12, "blocker_id": 11}],  # F11: the second one is refused
    "task_tags": [{"task_id": 12, "user_id": ME, "tag": "umzugtag"}],
    "task_watchers": [{"task_id": 12, "created_at": TS}],
    "habits": [{"id": 31, "name": "Umzug Laufen", "goal": 1, "created_at": TS}],
    "habit_logs": [{"habit_id": 31, "day": "2026-10-01", "count": 1}, {"habit_id": 31, "day": "2026-10-02", "count": 1}],
    "journal": [{"day": DAY_OLD, "text": "Alter Text aus der Datei", "updated_at": "2026-10-10T20:00:00Z"},
                {"day": DAY_NEW, "text": "Nur in der Datei", "updated_at": "2026-10-11T20:00:00Z"}],
}
FILE = mkzip(TABLES, {t: len(r) for t, r in TABLES.items()})

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P4317")
A = kt.setup()
HID_, Ha = freelancer(B, A, "hanna")  # F4 + F5, without an organisation
iid, j = upload(Ha, BIG)
check(j.get("state") == "preview", f"F5 a part the import never reads does not stop the file {j.get('state')} {j.get('error')}")
nt = {x.get("what"): x.get("count") for x in (j.get("preview") or {}).get("not_taken") or []}
check(nt.get("History") == len(ACT), f"F5 ... the preview names the history with the rows of the manifest {nt}")
j = run(Ha, iid)
check(j.get("state") == "done", f"the large import is done {j.get('state')} {j.get('error')}")
TXT = [w.get("text", "") for w in (j.get("result") or {}).get("warnings") or []]
check(TXT and TXT[0].startswith("These areas stay on the old server") and "History" in TXT[0], f"F4 the areas that stay come first {TXT[:1]}")
check(len(TXT) == 51 and sum(1 for t in TXT if t.startswith("Subtask in another project")) == 50,
      f"F4 ... on top of the 50 others {len(TXT)}")

GID, Gi = freelancer(B, A, "gina")  # the target account, without an organisation
r = Gi.put(B + f"/api/life/journal/{DAY_OLD}", json={"text": "Mein Tag hier"})
check(r.ok, f"a journal day written here before {r.status_code} {r.text[:120]}")

iid, j = upload(Gi, FILE)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
j = run(Gi, iid)
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
RES = j.get("result") or {}
IMP = RES.get("import_id")
W = RES.get("warnings") or []
TXT = [w.get("text", "") for w in W]

# F6: the roles
row = kt.dbx("SELECT approver_id, wait_by, reviewer_id, assignee_group_id FROM tasks WHERE title='Rollen' AND created_by=?", (GID,))
check(row and row[0][0] == GID and row[0][1] == GID, f"F6 approver and who set waiting come along {row}")
check(row and row[0][2] is None and row[0][3] is None, f"F6 a reviewer not here and a group of the old server stay empty {row}")
roles = {t for t in TXT if t.startswith("Role on tasks not imported")}
check(any(t.endswith(": Reviewer") for t in roles) and any(t.endswith(": Group") for t in roles), f"F6 ... with a warning naming the role {roles}")

# F11: the refused row
check(any(t.startswith("1 entries in Dependencies were refused") for t in TXT), f"F11 the refused dependency is named {TXT[-6:]}")

# F7: the journal
day = journal(Gi, DAY_OLD)
check(day.startswith("Mein Tag hier") and "Alter Text aus der Datei" in day and "From the import (entry of" in day,
      f"F7 the day here keeps its text, the file's entry below it {day!r}")
check((RES.get("created") or {}).get("journal_added") == 1 and any(t.startswith("Journal: the entry of the file was added") for t in TXT),
      f"F7 ... counted and named {RES.get('created')}")
check(journal(Gi, DAY_NEW) == "Nur in der Datei", "F7 a day only in the file is created as before")

# F16: the same file again
TID = one("SELECT id FROM tasks WHERE title='Rollen' AND created_by=?", (GID,))
HID = one("SELECT id FROM habits WHERE user_id=? AND name='Umzug Laufen'", (GID,))


def kids():
    return (one("SELECT COUNT(*) FROM habit_logs WHERE habit_id=?", (HID or 0,)), one("SELECT COUNT(*) FROM (SELECT k.obj_id AS task_id, CAST(ot.scope_id AS BIGINT) AS user_id, ot.name AS tag FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='user' WHERE k.kind='task') task_tags WHERE task_id=?", (TID or 0,)),  # 2.955.0 (#5276): personal tags are rows of the core (obj_tags scope user), read as the old task_tags
            one("SELECT COUNT(*) FROM task_watchers WHERE task_id=?", (TID or 0,)), one("SELECT COUNT(*) FROM task_deps WHERE task_id=?", (TID or 0,)))


before = kids()
check(before == (2, 1, 1, 1), f"the children of the first run {before}")
iid, j = upload(Gi, FILE)
check(j.get("state") == "preview" and (j.get("preview") or {}).get("again") is True, f"the same file again {j.get('state')}")
j = run(Gi, iid, again=True)
check(j.get("state") == "done", f"the second import is done {j.get('state')} {j.get('error')}")
T2 = [w.get("text", "") for w in (j.get("result") or {}).get("warnings") or []]
check(kids() == before, f"F16 nothing hangs twice on the rows of the earlier import {kids()} {before}")
check(not any("were refused" in t for t in T2), f"F16 ... and no refusal for them {T2}")
day = journal(Gi, DAY_OLD)
check(day.count("Alter Text aus der Datei") == 1, f"F16 the journal entry is not added a second time {day!r}")

# F7: the undo
check(IMP and Gi.post(B + f"/api/imports/{IMP}/undo", json={}).ok, "the undo of the first import")
check(journal(Gi, DAY_OLD) == "Mein Tag hier", f"F7 the undo cuts the added entry off again {journal(Gi, DAY_OLD)!r}")
check(journal(Gi, DAY_NEW) == "", "F7 ... and the day the import created goes")

sys.exit(kt.done("p2531_4317_umz_import"))
