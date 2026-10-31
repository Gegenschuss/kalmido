#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.363.3 A (#3133) API tests, own container (kt.fresh): the rest of "a move loses nothing silently".
 - org_leave: joining again within 24 hours brings back assignments and coming along, only for tasks that exist and can be seen
 - a folder of several lists into another workspace keeps its memo, the move back brings the opening and the client back
 - the way back of a files move restores the project of an agent's receipt suggestion
 - an "also in" request that waited offline during a move is kept for the way back
 - knowledge pages in the trash move along with their folder (someone else's page without a right stays)
 - files of tables and knowledge pages are sealed into a new stored file, the old one goes after the commit
 - My tasks: _prev protects a newer order, places of completed tasks stay
 - ICS: a changed occurrence is weighed by its own LAST-MODIFIED
 - the archive number lock around the write (preview catch-up; split, unsplit, files move)
freelancer-matrix: tasks (a person without an organisation: also-in wish, My tasks, ICS)
usage: p2363_3_a_test.py <datadir>"""
import json
import os
import subprocess
import sys

import kt
from kt import B, FAILS, OKS, check, sess, dbx  # noqa: F401
from freelancer_fixture import freelancer, org_join

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,family,files,wiki,sheets,office,clients,events,docs"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
FID, Fr = freelancer(B, A, "frida")
BID, Bo = freelancer(B, A, "bob")
CID, Ca = freelancer(B, A, "carol")
for u in ("bob", "carol"):
    check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG), f"setup: {u} joins Alpha")


def in_ct(code):
    """Python inside the app container (as system: writes the tests cannot do through the API)."""
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", kt.CT, "python", "-"], input=code, capture_output=True, text=True)
    return p.stdout.strip() + p.stderr[-400:]


def sql(q, *args):
    in_ct(f'''
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    c.execute({q!r}, {args!r})
c.commit()
''')


def one(q, *args):
    r = dbx(q, args)
    return r[0][0] if r else None


def task(s, tid):
    j = s.get(B + f"/api/tasks/{tid}").json()
    return j.get("task") or j


def new_list(s, name, org=None, **b):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org, **b})
    assert r.ok, r.text
    return r.json()["id"]


def new_task(s, lid, title, **b):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **b})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== 1. leaving and joining again
OPEN = new_list(A, "Open to all", ORG)
sql("UPDATE lists SET org_visibility='org', org_edit=1 WHERE id=?", OPEN)
SHUT = new_list(A, "Closed", ORG)
for lid in (OPEN, SHUT):  # the membership ends with leaving; the open list still shows its tasks afterwards
    assert A.put(B + f"/api/lists/{lid}/members", json={"email": "bob@example.com", "role": "edit"}).ok
T1, T2, T3, T4 = new_task(A, OPEN, "Mine again"), new_task(A, OPEN, "Taken over"), new_task(A, SHUT, "Closed list"), new_task(A, OPEN, "Deleted since")
for t in (T1, T2, T3, T4):
    check(A.patch(B + f"/api/tasks/{t}", json={"assignee_id": BID, "people": [BID]}).ok, f"setup: bob on task {t}")


def leave_and_back():
    check(A.delete(B + f"/api/orgs/{ORG}/members/{BID}").ok, "bob is removed from the organisation")
    check(one("SELECT assignee_id FROM tasks WHERE id=?", T1) is None and one("SELECT COUNT(*) FROM task_people WHERE user_id=?", BID) == 0,
          "assignments and coming along end")


leave_and_back()
check(A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": AID}).ok, "setup: alice takes one over")
check(A.delete(B + f"/api/tasks/{T4}").ok, "setup: one is deleted")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com"}).ok and org_join(B, "bob", ORG), "bob joins again")
check(one("SELECT assignee_id FROM tasks WHERE id=?", T1) == BID, "#3133: the assignment is back")
check(one("SELECT COUNT(*) FROM task_people WHERE task_id=? AND user_id=?", T1, BID) == 1, "#3133: coming along is back")
check(one("SELECT assignee_id FROM tasks WHERE id=?", T2) == AID, "#3133: a task somebody else took over stays theirs")
check(one("SELECT assignee_id FROM tasks WHERE id=?", T3) is None, "#3133: a task of a closed list (not visible) stays unassigned")
check(one("SELECT COUNT(*) FROM task_people WHERE task_id=? AND user_id=?", T3, BID) == 0, "#3133: nor does coming along return there")
check(one("SELECT assignee_id FROM tasks WHERE id=?", T4) is None, "#3133: a deleted task gets nothing back")
check(one("SELECT detail FROM space_moves WHERE kind='orgleave' ORDER BY id DESC LIMIT 1").find("restored") > 0, "#3133: the memo counts as used")
# older than 24 hours: nothing
leave_and_back()
sql("UPDATE space_moves SET at='2020-01-01T00:00:00Z' WHERE kind='orgleave'")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com"}).ok and org_join(B, "bob", ORG), "bob joins a third time")
check(one("SELECT assignee_id FROM tasks WHERE id=?", T1) is None, "#3133: after 24 hours nothing comes back")

# ================================================================== 2. a folder of several lists
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": CID, "role": "admin"}).ok
L1, L2 = new_list(A, "One", ORG, folder="Clients"), new_list(A, "Two", ORG, folder="Clients")
sql("UPDATE lists SET org_visibility='org', org_edit=0 WHERE id=?", L1)
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": 0}, "apply": "all"})
j = r.json()
check(r.ok and j.get("changed") == 2 and (j.get("move_ended") or {}).get("visibility") == 1, f"#3133: the folder's move names what ended {r.text[:200]}")
check(one("SELECT org_id FROM lists WHERE id=?", L1) is None and one("SELECT org_visibility FROM lists WHERE id=?", L1) == "", "#3133: both private, the opening ended")
check(one("SELECT COUNT(*) FROM space_moves WHERE kind='list' AND obj_id=?", L1) == 1, "#3133: the list has its memo")
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": ORG}, "apply": "all"})
check(r.ok and (r.json().get("move_restored") or {}).get("visibility") == 1, f"#3133: the move back names what returned {r.text[:200]}")
check(one("SELECT org_visibility FROM lists WHERE id=?", L1) == "org", "#3133: the opening is back")

# ================================================================== 3. an agent's suggestion: its project on the way back
P = new_list(A, "Project", ORG)
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("receipt.txt", b"Receipt 12.50 EUR", "text/plain"))])
assert r.ok, r.text
N = r.json()["ids"][0]
check(kt.until(lambda: A.get(B + f"/api/docs/{N}").json()["state"] == "done", 90), "setup: a document")
sql("INSERT INTO rc_suggest(node_id, ws, org_id, agent_id, state, list_id, created_at) VALUES(?,?,?,?,'accepted',?,'2026-10-01T00:00:00Z')", N, f"org:{ORG}", ORG, AID, P)
check(one("SELECT list_id FROM rc_suggest WHERE node_id=?", N) == P, "setup: the suggestion has its project")
r = A.post(B + "/api/files/move-space", json={"ids": [N], "to": "private"})
check(r.ok, f"the file goes private {r.text[:200]}")
check(one("SELECT list_id FROM rc_suggest WHERE node_id=?", N) is None, "the project stays behind")
r = A.post(B + "/api/files/move-space", json={"items": [{"id": N, "parent": None}], "to": f"org:{ORG}"})
check(r.ok and one("SELECT list_id FROM rc_suggest WHERE node_id=?", N) == P, f"#3133: the way back restores the suggestion's project {r.text[:200]}")

# ================================================================== 4. "also in" that waited offline (freelancer-matrix: tasks)
Fa, Fb, Fc = new_list(Fr, "Fa"), new_list(Fr, "Fb"), new_list(Fr, "Fc")
FT, FP = new_task(Fr, Fa, "Linked"), new_task(Fr, Fa, "Parent")
check(Fr.post(B + f"/api/tasks/{FT}/links", json={"list_id": Fb}).ok, "setup: shown also in Fb")
check(Fr.patch(B + f"/api/tasks/{FT}", json={"parent_id": FP}).ok and not task(Fr, FT).get("also"), "setup: indented, the trigger dropped the link")
r = Fr.post(B + f"/api/tasks/{FT}/links", json={"list_id": Fc})  # what the queue sends after the move
check(r.ok and r.json().get("link_waits"), f"#3133: the request that waited is kept, not refused {r.status_code} {r.text[:200]}")
check(Fr.patch(B + f"/api/tasks/{FT}", json={"parent_id": None}).ok, "outdented again")
also = sorted(x["list_id"] for x in task(Fr, FT).get("also") or [])
check(also == sorted([Fb, Fc]), f"#3133: the way back brings the old link and the waiting one {also}")
FU = new_task(Fr, Fa, "Never moved")
check(Fr.patch(B + f"/api/tasks/{FU}", json={"parent_id": FP}).ok, "setup: a task without links is indented")
check(Fr.post(B + f"/api/tasks/{FU}/links", json={"list_id": Fb}).status_code == 400, "#3133: without a memo of the move the refusal stands")
OT = new_task(A, P, "Across")
Q, PV = new_list(A, "Target", ORG), new_list(A, "Private")
check(A.post(B + f"/api/tasks/{OT}/links", json={"list_id": Q}).ok and A.patch(B + f"/api/tasks/{OT}", json={"list_id": PV}).ok, "setup: moved to the private space")
r = A.post(B + f"/api/tasks/{OT}/links", json={"list_id": PV + 999999})
check(r.status_code in (403, 404), f"#3133: a list the person has no right in stays refused {r.status_code}")

# ================================================================== 5. knowledge pages in the trash
def wpage(s, space, path, body):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


W1, W2 = wpage(A, "private", "Plans/Live", "see [[Plans/Binned]]"), wpage(A, "private", "Plans/Binned", "old text")
check(A.delete(B + f"/api/wiki/pages/{W2}").ok, "setup: one page in the trash")
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "folder": "Plans", "to": f"org:{ORG}", "dry": 1})
check(r.ok and r.json().get("trash") == 1 and any("goes along" in n for n in r.json().get("notes", [])), f"#3133: the dry run says it goes along {r.text[:300]}")
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "folder": "Plans", "to": f"org:{ORG}", "dest": "Moved"})
check(r.ok, f"the folder moves {r.text[:200]}")
check(one("SELECT org_id FROM wiki_pages WHERE id=?", W2) == ORG and one("SELECT path FROM wiki_pages WHERE id=?", W2) == "Moved/Plans/Binned",
      "#3133: the page in the trash moved along under the new path")
check(one("SELECT deleted_at FROM wiki_pages WHERE id=?", W2) is not None, "#3133: it is still in the trash")
r = A.post(B + "/api/wiki/move-space", json={"space": f"org:{ORG}", "folder": "Moved/Plans", "to": "private"})
check(r.ok and one("SELECT org_id FROM wiki_pages WHERE id=?", W2) is None and one("SELECT path FROM wiki_pages WHERE id=?", W2) == "Plans/Binned",
      f"#3133: the move back takes it along too {r.text[:200]}")
# a member's release covers their own page: alice's page in the trash stays in the organisation
M1, M2 = wpage(Bo, f"org:{ORG}", "Team/Bobs", "bob"), wpage(A, f"org:{ORG}", "Team/Alices", "alice")
check(A.delete(B + f"/api/wiki/pages/{M2}").ok, "setup: alice's page in the trash")
r = Bo.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": "wiki", "id": M1})
check(r.ok, f"setup: bob asks {r.text[:200]}")
check(A.post(B + f"/api/orgs/{ORG}/out-requests/{r.json().get('id')}", json={"decision": "approve"}).ok, "setup: alice releases it")
r = Bo.post(B + "/api/wiki/move-space", json={"space": f"org:{ORG}", "folder": "Team", "to": "private"})
check(r.ok and one("SELECT org_id FROM wiki_pages WHERE id=?", M1) is None, f"bob's page goes private {r.text[:200]}")
check(one("SELECT org_id FROM wiki_pages WHERE id=?", M2) == ORG, "#3133: someone else's page in the trash never leaves the organisation with it")

# ================================================================== 6. new stored file, the old one gone after the commit
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
S = A.post(B + "/api/sheets", json={"title": "Kit", "space": f"org:{ORG}"}).json()
SID, rid = S["id"], S["rows"][0]["id"]
cols = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Doc", "kind": "file"}).json()["column"]["id"]
r = A.post(B + f"/api/sheets/{SID}/files", data={"row_id": str(rid), "col_id": str(cols)}, files={"file": ("m.pdf", PDF, "application/pdf")})
check(r.status_code == 201, f"setup: a file in a cell {r.text[:200]}")
SF = r.json()["file"]["id"]
old = one("SELECT path FROM sheet_files WHERE id=?", SF)
r = A.post(B + f"/api/sheets/{SID}/move-space", json={"to": "private"})
check(r.ok, f"the table moves {r.text[:200]}")
new = one("SELECT path FROM sheet_files WHERE id=?", SF)
check(new != old and new.endswith("-m.pdf"), f"#3133: the table's file has a new stored file {old} -> {new}")
check(not os.path.exists(os.path.join(kt.DATA, "attachments", old)), "#3133: the old stored file is gone after the commit")
r = A.get(B + f"/api/sheets/{SID}/files/{SF}")
check(r.ok and r.content == PDF, "#3133: the file reads as before")
WF = wpage(A, "private", "Pics/One", "x")
r = A.post(B + f"/api/wiki/pages/{WF}/files", files={"file": ("n.pdf", PDF, "application/pdf")})
check(r.status_code in (200, 201), f"setup: a page's file {r.text[:200]}")
fid = r.json()["files"][0]["id"]
old = one("SELECT path FROM wiki_files WHERE id=?", fid)
check(A.post(B + "/api/wiki/move-space", json={"space": "private", "pages": [WF], "to": f"org:{ORG}"}).ok, "the page moves")
new = one("SELECT path FROM wiki_files WHERE id=?", fid)
check(new != old and not os.path.exists(os.path.join(kt.DATA, "attachments", old)), f"#3133: the page's file too {old} -> {new}")
check(A.get(B + f"/api/wiki/files/{fid}").content == PDF, "#3133: it reads as before")

# ================================================================== 7. My tasks (freelancer-matrix: tasks)
M = new_list(Fr, "Order")
a, b_, c_, d = (new_task(Fr, M, x) for x in "abcd")


def mine():
    o = Fr.get(B + "/api/state").json()["mine_order"]
    return [int(k) for k, _ in sorted(o.items(), key=lambda x: x[1])]


check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [a, b_, c_, d]}).json().get("count") == 4, "setup: an order")
r = Fr.put(B + "/api/tasks/mine-order", json={"ids": [d, c_, b_, a], "_prev": {"ids": [b_, a, c_, d]}}).json()
check(r.get("order_kept") and mine() == [a, b_, c_, d], f"#3133: an order built on an older one does not overwrite the newer {r}")
r = Fr.put(B + "/api/tasks/mine-order", json={"ids": [b_, a, c_, d], "_prev": {"ids": [a, b_, 999, c_, d]}}).json()
check(not r.get("order_kept") and mine() == [b_, a, c_, d], f"#3133: a task gone since is no conflict {r}")
check(Fr.post(B + f"/api/tasks/{c_}/complete", json={}).ok, "setup: one completed")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [d, b_, a]}).json().get("count") == 3, "the app sends the open tasks")
check(Fr.post(B + f"/api/tasks/{c_}/reopen", json={}).ok, "opened again")
check(mine() == [d, b_, a, c_], f"#3133: a completed task keeps its place behind the task it followed {mine()}")

# ================================================================== 8. ICS occurrences (freelancer-matrix: tasks)
CAL = Fr.post(B + "/api/evcals", json={"name": "Imports"}).json()["id"]


def ics(master_mod, occ_mod, occ_title, master_title="Series"):
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:series-1
DTSTAMP:20260101T000000Z
LAST-MODIFIED:{master_mod}
DTSTART:20260105T090000Z
DTEND:20260105T100000Z
RRULE:FREQ=WEEKLY;COUNT=4
SUMMARY:{master_title}
END:VEVENT
BEGIN:VEVENT
UID:series-1
DTSTAMP:20260101T000000Z
LAST-MODIFIED:{occ_mod}
RECURRENCE-ID:20260112T090000Z
DTSTART:20260112T110000Z
DTEND:20260112T120000Z
SUMMARY:{occ_title}
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode()


def imp(data):
    r = Fr.post(B + f"/api/evcals/{CAL}/import", files={"file": ("c.ics", data, "text/calendar")})
    assert r.ok, r.text
    return r.json()


def ov():
    return json.loads(one("SELECT overrides FROM events WHERE uid='series-1'") or "[]")


check(imp(ics("20200101T000000Z", "20200101T000000Z", "First"))["created"] == 1, "setup: a series with a changed date")
EID = one("SELECT id FROM events WHERE uid='series-1'")
check(Fr.patch(B + f"/api/events/{EID}", json={"title": "Renamed here"}).ok, "setup: the series is renamed here")
j = imp(ics("20200101T000000Z", "20990101T000000Z", "Newer in the file"))
check(j["updated"] == 1 and not j.get("kept_newer") and ov()[0]["title"] == "Newer in the file", f"#3133: an occurrence newer than the change here comes in {j} {ov()}")
check(one("SELECT title FROM events WHERE id=?", EID) == "Renamed here", "#3133: the series changed here stays")
j = imp(ics("20200101T000000Z", "20200101T000000Z", "Older in the file"))
check(j.get("kept_newer") == 1 and ov()[0]["title"] == "Newer in the file", f"#3133: an older occurrence stays out {j}")
j = imp(ics("20990101T000000Z", "20200101T000000Z", "Older again", "New series name"))
check(one("SELECT title FROM events WHERE id=?", EID) == "New series name" and ov()[0]["title"] == "Newer in the file",
      f"#3133: a newer series comes in, the older occurrence in it does not {j} {ov()}")

# ================================================================== 9. the archive number lock
PROBE = '''
from kalmido.docs import store as S, thumbfill as T
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    nid = c.execute("SELECT node_id FROM doc_meta WHERE node_id=?", (%d,)).fetchone()[0]
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    ws = S.meta_row(c, nid)["ws"]
    orig, seen = S.asn_taken, []
    def spy(*a, **k):
        c2 = connect()
        seen.append(c2.execute("SELECT pg_try_advisory_xact_lock(hashtext(?))", (f"doc-asn:{ws}",)).fetchone()[0])
        c2.rollback()
        c2.close()
        return orig(*a, **k)
    S.asn_taken = spy
    T._fill_asn(c, S, nid, 4242, node)
    print(seen, S.meta_row(c, nid)["asn"])
    c.commit()
'''
out = in_ct(PROBE % N)
check(out.startswith("[False] 4242"), f"#3133: the catch-up checks and writes the number under the lock ({out!r})")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido")
for f, what in (("docs/split.py", "split and unsplit"), ("files/fsmove.py", "the files move")):
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        src = fh.read()
    check(src.count("S.asn_lock(c,") >= (2 if "split" in f else 1), f"#3133: {what} take the number lock")
r = A.post(B + "/api/files/move-space", json={"ids": [N], "to": "private"})
check(r.ok and one("SELECT asn FROM doc_meta WHERE node_id=?", N) == 4242, f"#3133: a document keeps its number through the locked move {r.text[:200]}")

sys.exit(kt.done("p2363_3_a"))
