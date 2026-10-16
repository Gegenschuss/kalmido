#!/usr/bin/env python3
"""2.49.0 API tests, part C (#1199 knowledge pages, #1201 mind map). Invented names only.
 - an organisation's pages: every member reads and writes; another organisation: 404 (also by id, search, export)
 - private pages (no organisation): only their owner
 - [[links]] give backlinks; renaming a page changes the links to it; the frontmatter becomes attrs
 - delete = trash, restore (Undo); a taken name: 409; templates (template_id)
 - #123 to a task of another organisation tells nothing (no title; "mentioned in" only for whoever sees the task)
 - export / import as a ZIP of .md files: paths cleaned ("../"), only Markdown, replace=1
 - list view "mindmap" is stored; the outline parser (Markdown, OPML, FreeMind) and hostile XML (DOCTYPE / ENTITY)
 - rollback: only new tables
usage: p249_c_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
# tenant-matrix: wiki
import io
import os
import subprocess
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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


if not os.environ.get("P249C_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id!=?)", (ORG, BOB, CAROL, ORG2, DAVE), write=True)
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"

# ---- rollback: new tables only
t = {r[0] for r in dbx("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'wiki_%'")}
check({"wiki_pages", "wiki_links"} <= t, f"new tables wiki_pages + wiki_links ({t})")

# ---- organisation pages: members read and write
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Processes/Shoot day/Checklist",
                                         "body": "---\nstatus: draft\ntags: [shoot, crew]\n---\n# Checklist\n- Camera\n- Light\n"})
check(r.status_code == 201, f"bob creates an organisation page ({r.status_code} {r.text[:200]})")
P1 = r.json()["id"]
check(r.json().get("attrs") == {"status": "draft", "tags": ["shoot", "crew"]}, f"frontmatter -> attrs ({r.json().get('attrs')})")
r = Ca.get(B + f"/api/wiki/pages/{P1}")
check(r.ok and "Camera" in r.json().get("body", ""), "carol (member) reads the page")
r = Ca.patch(B + f"/api/wiki/pages/{P1}", json={"body": r.json()["body"] + "- Sound\n", "expect_updated_at": r.json()["updated_at"]})
check(r.ok and "Sound" in r.json()["body"], "carol (member) writes the page")
r2 = Bo.patch(B + f"/api/wiki/pages/{P1}", json={"body": "old", "expect_updated_at": "2000-01-01T00:00:00.000+00:00"})
check(r2.status_code == 409 and r2.json().get("page", {}).get("body", "").endswith("- Sound\n"), f"stale save: 409 with the current page ({r2.status_code})")
check(Da.get(B + f"/api/wiki/pages/{P1}").status_code == 404, "another organisation: 404 by id")
check(Da.patch(B + f"/api/wiki/pages/{P1}", json={"body": "x"}).status_code == 404, "another organisation: no write (404)")
check(Da.delete(B + f"/api/wiki/pages/{P1}").status_code == 404, "another organisation: no delete (404)")
check(Da.get(B + "/api/wiki", params={"space": SP}).status_code == 404, "another organisation's space: 404")
check(Da.post(B + "/api/wiki/pages", json={"space": SP, "path": "Intruder"}).status_code == 404, "no page in another organisation's space")
check(Da.get(B + "/api/wiki/export", params={"space": SP}).status_code == 404, "no export of another organisation's space")
check(not Da.get(B + "/api/wiki/search", params={"q": "Checklist"}).json()["pages"], "search: nothing of another organisation")
check(any(p["id"] == P1 for p in Ca.get(B + "/api/wiki/search", params={"q": "checklist"}).json()["pages"]), "search: the member finds it")
idx = Ca.get(B + "/api/wiki", params={"space": SP}).json()
check([p["path"] for p in idx["pages"]] == ["Processes/Shoot day/Checklist"] and "body" not in idx["pages"][0], "index: paths without text")
check(Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "processes/shoot day/checklist"}).status_code == 409, "a taken name (any case): 409")
check(Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": " / .. / "}).status_code == 400, "a name of dots / slashes only: 400")

# ---- private pages: only the owner
r = Ca.post(B + "/api/wiki/pages", json={"space": "private", "path": "Diary", "body": "secret"})
check(r.status_code == 201 and r.json()["space"] == "private", "carol creates a private page")
PP = r.json()["id"]
check(Bo.get(B + f"/api/wiki/pages/{PP}").status_code == 404, "bob (same organisation) does not see carol's private page")
check(all(p["id"] != PP for p in Bo.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]), "bob's private space: not carol's page")
check(not Bo.get(B + "/api/wiki/search", params={"q": "secret"}).json()["pages"], "search: not another person's private page")
check(Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": "Diary"}).status_code == 201, "the same name in another private space is fine")

# ---- links, backlinks, rename
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Home", "body": "See [[Processes/Shoot day/Checklist]] and [[processes/shoot day/checklist|the list]]."})
HOME = r.json()["id"]
bl = Ca.get(B + f"/api/wiki/pages/{P1}").json().get("backlinks")
check(bl == [{"id": HOME, "path": "Home"}], f"backlinks of the checklist ({bl})")
r = Bo.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Processes/Shoot/Checklist"})
check(r.ok and r.json().get("relinked") == 1, f"rename: one page relinked ({r.text[:200]})")
hb = Bo.get(B + f"/api/wiki/pages/{HOME}").json()["body"]
check("[[Processes/Shoot/Checklist]]" in hb and "[[Processes/Shoot/Checklist|the list]]" in hb, f"rename changed the links ({hb})")
check(Ca.get(B + f"/api/wiki/pages/{P1}").json().get("backlinks") == [{"id": HOME, "path": "Home"}], "backlinks follow the new name")
r = Bo.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Processes/Shoot day/Checklist", "relink": False})
check(r.ok and r.json().get("relinked") == 0 and "[[Processes/Shoot/Checklist]]" in Bo.get(B + f"/api/wiki/pages/{HOME}").json()["body"], "relink false: links stay")
Bo.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Processes/Shoot/Checklist"})

# ---- rename a folder: every page under it moves, links follow; taken names: 409
pa = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Proj/A"}).json()["id"]
pb = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Proj/Sub/B"}).json()["id"]
pl = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Index", "body": "[[Proj/A]] [[Proj/Sub/B|b]]"}).json()["id"]
r = Ca.post(B + "/api/wiki/move", json={"space": SP, "from": "Proj", "to": "Projects/2026"})
check(r.ok and len(r.json().get("moved", [])) == 2 and r.json().get("relinked") == 2, f"folder renamed: two pages, links changed ({r.text[:200]})")
check(Bo.get(B + f"/api/wiki/pages/{pb}").json()["path"] == "Projects/2026/Sub/B", "the page under the folder moved")
check(Bo.get(B + f"/api/wiki/pages/{pl}").json()["body"] == "[[Projects/2026/A]] [[Projects/2026/Sub/B|b]]", "links to the moved pages follow")
Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Other/A"})
r = Bo.post(B + "/api/wiki/move", json={"space": SP, "from": "Projects/2026", "to": "Other"})
check(r.status_code == 409 and r.json().get("taken") == ["Other/A"], f"a taken name: 409 with the names ({r.text[:200]})")
check(Bo.get(B + f"/api/wiki/pages/{pa}").json()["path"] == "Projects/2026/A", "after the 409 nothing moved")
check(Da.post(B + "/api/wiki/move", json={"space": SP, "from": "Projects", "to": "X"}).status_code == 404, "another organisation cannot move folders")
check(Bo.post(B + "/api/wiki/move", json={"space": SP, "from": "Projects", "to": "Projects/inner"}).status_code == 400, "a folder cannot move into itself")

# ---- templates
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Templates/Meeting", "body": "## Agenda\n- \n"})
TPL = r.json()["id"]
check(r.json().get("template") is True, "a page under Templates/ is a template")
r = Ca.post(B + "/api/wiki/pages", json={"space": SP, "path": "Meetings/Kickoff", "template_id": TPL})
check(r.status_code == 201 and r.json()["body"].startswith("## Agenda"), "new page from a template")
check(Da.post(B + "/api/wiki/pages", json={"space": "private", "path": "Steal", "template_id": TPL}).status_code == 404, "template of another organisation: 404")

# ---- delete = trash, restore
r = Ca.delete(B + f"/api/wiki/pages/{HOME}")
check(r.ok, "carol deletes a page")
check(Bo.get(B + f"/api/wiki/pages/{HOME}").status_code == 404, "deleted: gone")
check(Bo.get(B + f"/api/wiki/pages/{P1}").json().get("backlinks") == [], "no backlinks from deleted pages")
r = Bo.post(B + "/api/wiki/restore", json={"ids": [HOME]})
check(r.ok and r.json().get("ids") == [HOME], "restore (Undo)")
check(Bo.get(B + f"/api/wiki/pages/{HOME}").ok, "restored page is back")
check(Da.post(B + "/api/wiki/trash", json={"ids": [HOME]}).json().get("skipped") == [HOME], "another organisation cannot trash it")

# ---- #123: a task of another organisation tells nothing
r = Da.post(B + "/api/lists", json={"name": "Beta secret", "org_id": ORG2})
check(r.status_code in (200, 201), f"dave: list in Beta ({r.status_code} {r.text[:200]})")
BL = r.json()["id"]
r = Da.post(B + "/api/tasks", json={"title": "Secret merger plan", "list_id": BL})
FT = r.json()["id"]
r = Bo.post(B + "/api/lists", json={"name": "Alpha work", "org_id": ORG})
AL = r.json()["id"]
OT = Bo.post(B + "/api/tasks", json={"title": "Own task", "list_id": AL}).json()["id"]
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Links", "body": f"Mine #{OT}, foreign #{FT}"})
LP = r.json()["id"]
check("Secret merger" not in Bo.get(B + f"/api/wiki/pages/{LP}").text, "a page never carries the title of a linked task")
check(Bo.get(B + "/api/wiki/mentions", params={"task": FT}).status_code == 404, "mentions of a task one cannot see: 404")
m = Bo.get(B + "/api/wiki/mentions", params={"task": OT}).json().get("pages")
check(m and m[0]["id"] == LP, f"own task: mentioned in the page ({m})")
check(Da.get(B + "/api/wiki/mentions", params={"task": FT}).json().get("pages") == [], "dave: his task is mentioned in no page HE can read")

# ---- export / import
r = Bo.get(B + "/api/wiki/export", params={"space": SP})
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip"), "export: a ZIP")
names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
check("Processes/Shoot/Checklist.md" in names and "Templates/Meeting.md" in names, f"export: folders + .md ({names})")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("../../etc/evil.md", "x")
    z.writestr("/abs/Path.md", "y")
    z.writestr("Notes/Fresh.md", "---\nowner: crew\n---\nNew [[Home]]")
    z.writestr("Processes/Shoot/Checklist.md", "replaced")
    z.writestr("script.js", "alert(1)")
    z.writestr("Notes/.hidden.md", "h")
buf.seek(0)
r = Ca.post(B + "/api/wiki/import", params={"space": SP}, files={"file": ("w.zip", buf.getvalue(), "application/zip")})
j = r.json()
check(r.ok and len(j["created"]) == 2, f"import: two new pages ({j})")
paths = {p["path"] for p in Ca.get(B + "/api/wiki", params={"space": SP}).json()["pages"]}
check({"abs/Path", "Notes/Fresh"} <= paths and not any("evil" in p or ".." in p for p in paths), f"import: absolute path cleaned, ../ refused ({paths})")
check("../../etc/evil.md" in j["skipped"] and "script.js" in j["skipped"] and "Notes/.hidden.md" in j["skipped"] and "Processes/Shoot/Checklist.md" in j["skipped"], "import: non-Markdown, hidden and existing skipped")
check(Ca.get(B + f"/api/wiki/pages/{HOME}").json().get("backlinks", [{}])[0].get("path") == "Notes/Fresh", "imported links count as backlinks")
r = Ca.post(B + "/api/wiki/import", params={"space": SP, "replace": "1"}, files={"file": ("w.zip", buf.getvalue(), "application/zip")})
check(r.ok and P1 in r.json()["updated"] and Bo.get(B + f"/api/wiki/pages/{P1}").json()["body"] == "replaced", "import replace=1 overwrites")
r = Ca.post(B + "/api/wiki/trash", json={"ids": j["created"]})
check(r.json().get("ids") == j["created"], "Undo of the import: the new pages to the trash")
r = Da.post(B + "/api/wiki/import", params={"space": SP}, files={"file": ("w.zip", buf.getvalue(), "application/zip")})
check(r.status_code == 404, "import into another organisation: 404")
r = Ca.post(B + "/api/wiki/import", params={"space": SP}, files={"file": ("w.zip", b"not a zip", "application/zip")})
check(r.status_code == 400, "import: not a ZIP -> 400")

# ---- mind map: the list view and the outline parser
r = Bo.patch(B + f"/api/lists/{AL}", json={"view": "mindmap"})
check(r.ok and any(x["id"] == AL and x.get("view") == "mindmap" for x in Bo.get(B + "/api/state").json()["lists"]), f"list view mindmap is stored ({r.text[:120]})")
r = Bo.post(B + "/api/outline/parse", json={"text": "# Launch\n- Plan\n  - Budget\n  - Team\n- Shoot\n\t- Day 1\n"})
j = r.json()
check(r.ok and j["format"] == "md" and [c["title"] for c in j["children"]] == ["Launch"], f"Markdown: heading on top ({j})")
kids = j["children"][0]["children"] if r.ok else []
check([k["title"] for k in kids] == ["Plan", "Shoot"] and [k["title"] for k in kids[0]["children"]] == ["Budget", "Team"]
      and kids[1]["children"][0]["title"] == "Day 1", "Markdown: the indentation makes the tree")
opml = '<?xml version="1.0"?><opml version="2.0"><head><title>Ideas</title></head><body><outline text="A"><outline text="A1"/></outline><outline text="B"/></body></opml>'
j = Bo.post(B + "/api/outline/parse", json={"text": opml}).json()
check(j.get("format") == "opml" and j["title"] == "Ideas" and j["children"][0]["children"][0]["title"] == "A1", f"OPML ({j})")
fm = '<map version="1.0.1"><node TEXT="Root"><node TEXT="X"><node TEXT="X1"/></node><node TEXT="Y"/></node></map>'
j = Bo.post(B + "/api/outline/parse", json={"text": fm}).json()
check(j.get("format") == "mm" and j["title"] == "Root" and [c["title"] for c in j["children"]] == ["X", "Y"], f"FreeMind ({j})")
evil = '<?xml version="1.0"?><!DOCTYPE opml [<!ENTITY x SYSTEM "file:///etc/passwd">]><opml><body><outline text="&x;"/></body></opml>'
r = Bo.post(B + "/api/outline/parse", json={"text": evil})
check(r.status_code == 400 and "passwd" not in r.text and "root:" not in r.text, f"hostile XML (external entity) refused ({r.status_code})")
lol = '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><map><node TEXT="&lol2;"/></map>'
check(Bo.post(B + "/api/outline/parse", json={"text": lol, "format": "mm"}).status_code == 400, "entity expansion refused")
check(Bo.post(B + "/api/outline/parse", json={"text": "<opml><body"}).status_code == 400, "broken XML: 400")
check(Bo.post(B + "/api/outline/parse", json={"text": "just text"}).status_code == 400, "no list: 400 (nothing to import)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
