#!/usr/bin/env python3
"""2.56.0 API tests (part B).
 - #1795 organisation admins change the name (with its emoji), the picture icon and the colour of a list of their organisation
   (PATCH /api/orgs/{id}/lists/{id}, PUT / POST / DELETE /api/orgs/{id}/lists/{id}/icon), also without a role in the list --
   and nothing else: other fields 403, no tasks, sections, members or contents (the list routes stay 403 / 404); a plain
   member 403, an agent 403 (also with the organisation's admin role), another organisation's admin 404, a private list /
   an inbox 404, an admin who lost the role 403; the history (old -> new, never the picture's token), News for the owner and
   the members (rename with the old name, restyle for colour / icon), the picture readable for the admin; the list admin's
   way of 2.40.0 (#1431) stays as it was
tenant-matrix: org
usage: p256_b_api_test.py <datadir>"""
import os
import struct
import subprocess
import sys
import zlib

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
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


def news(s):
    return [x.get("data") or {} for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == "orglist"]


def png(w=4, h=4):
    """A tiny valid PNG (red square), no image library needed."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def row(lid):
    return dict(dbx("SELECT name, color, icon, kind, archived, owner_id FROM lists WHERE id=?", (lid,))[0])


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE username='alice')", (ORG,), write=True)

# bob's lists: TEAM of the organisation (carol edits), ADM of the organisation (dave is its list admin), PRIV private (shared
# with carol), his inbox. Alice (organisation admin) has no role in any of them.
TEAM = Bo.post(B + "/api/lists", json={"name": "Bob Team", "org_id": ORG}).json()["id"]
ADM = Bo.post(B + "/api/lists", json={"name": "Bob Admin", "org_id": ORG}).json()["id"]
PRIV = Bo.post(B + "/api/lists", json={"name": "Bob Private", "org_id": None}).json()["id"]
check(Bo.put(B + f"/api/lists/{TEAM}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol edits bob's team list")
check(Bo.put(B + f"/api/lists/{ADM}/members", json={"user_id": DAVE, "role": "admin"}).ok, "setup: dave is a list admin")
check(Bo.put(B + f"/api/lists/{PRIV}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol in bob's private list")
T1 = Bo.post(B + "/api/tasks", json={"title": "Secret task one", "list_id": TEAM}).json()["id"]
BINBOX = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]
check(not dbx("SELECT 1 FROM list_members WHERE list_id IN (?,?,?) AND user_id=(SELECT id FROM users WHERE username='alice')", (TEAM, ADM, PRIV)),
      "setup: alice has no role in bob's lists")
check(Bo.patch(B + f"/api/lists/{TEAM}", json={"color": "#2dd4bf"}).ok, "setup: the team list has a colour")
base = f"/api/orgs/{ORG}/lists/{TEAM}"

# ================================================================== the organisation admin: name, colour
r = A.patch(B + base, json={"name": "\U0001F680 Team renamed", "color": "#6d8cff"})
check(r.ok, "#1795: the organisation admin renames / recolours a list without a role in it " + r.text[:160])
check(row(TEAM)["name"] == "\U0001F680 Team renamed" and row(TEAM)["color"] == "#6d8cff", "#1795: name (with its emoji) and colour stored")
x = [x for x in r.json().get("lists", []) if x["id"] == TEAM]
check(x and x[0]["name"] == "\U0001F680 Team renamed" and x[0]["color"] == "#6d8cff" and "icon" in x[0], "#1795: the overview has name, colour, icon")
check("Secret" not in r.text, "#1795: the answer has no task titles")
check(A.patch(B + base, json={"name": "  "}).status_code == 400, "#1795: an empty name: 400")
check(A.patch(B + base, json={}).status_code == 403, "#1795: nothing to change: 403")
for k, v in (("kind", "project"), ("folder", "Elsewhere"), ("archived", True), ("rate", 50), ("ticket_tpl", {}), ("org_id", None),
             ("view", "kanban"), ("family", "shopping"), ("agent_tidy", True), ("note", "x")):
    r = A.patch(B + base, json={"name": "Sneaky", k: v})
    check(r.status_code == 403, f"#1795: another field ({k}) with the name: 403 ({r.status_code})")
check(row(TEAM)["name"] == "\U0001F680 Team renamed" and row(TEAM)["kind"] == "list", "#1795: ... and nothing changed")

# the list's own routes stay closed for her (no contents, no members, no sections, no settings)
check(A.patch(B + f"/api/lists/{TEAM}", json={"name": "Through the list route"}).status_code in (403, 404), "#1795: PATCH /api/lists stays closed")
check(A.post(B + "/api/tasks", json={"title": "Admin task", "list_id": TEAM}).status_code in (403, 404), "#1795: no new task in the list")
check(A.get(B + f"/api/tasks/{T1}").status_code in (403, 404), "#1795: no task of the list readable")
check(A.patch(B + f"/api/tasks/{T1}", json={"title": "x"}).status_code in (403, 404), "#1795: no task changed")
check(A.post(B + f"/api/lists/{TEAM}/sections", json={"name": "S"}).status_code in (403, 404), "#1795: no section")
check(A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": DAVE, "role": "edit"}).status_code in (403, 404), "#1795: no member")
check(A.put(B + f"/api/lists/{TEAM}/icon", json={"preset": "kalmido"}).status_code in (403, 404), "#1795: the list's own icon route stays closed")
check(all(t["id"] != T1 for t in A.get(B + "/api/state").json().get("tasks", [])), "#1795: the state has none of its tasks")
check(all(l["id"] != TEAM for l in A.get(B + "/api/state").json().get("lists", [])), "#1795: the list is not in her sidebar")

# ================================================================== News for the owner and the members, the history
nb, nc = news(Bo), news(Ca)
check(any(d.get("action") == "rename" and d.get("old") == "Bob Team" and d.get("name") == "\U0001F680 Team renamed" for d in nb),
      f"#1795: the owner hears about the rename (old -> new): {nb}")
check(any(d.get("action") == "rename" for d in nc), "#1795: the member hears about it too")
check(not any(d.get("action") == "rename" for d in news(Da)), "#1795: someone outside the list hears nothing")
log = A.get(B + f"/api/orgs/{ORG}/lists").json()["log"]
e = [r for r in log if r["action"] == "edit" and r["list_id"] == TEAM]
check(e and e[0]["detail"].get("name") == ["Bob Team", "\U0001F680 Team renamed"] and e[0]["detail"].get("color") == ["#2dd4bf", "#6d8cff"]
      and e[0]["by"] == "Alice", f"#1795: the history has who and old -> new: {e[:1]}")
r = A.patch(B + base, json={"color": "#f87171"})
check(r.ok and row(TEAM)["color"] == "#f87171", "#1795: colour alone")
# 2.58.0 (#1804): a colour change right after the rename joins the owner's unread rename item (one item, no second one)
check(any(d.get("action") in ("restyle", "rename") for d in news(Bo)) and len([d for d in news(Bo) if d.get("action") in ("restyle", "rename")]) == 1,
      "#1795: a colour change tells the owner (joined with the rename, #1804)")
n0 = len(A.get(B + f"/api/orgs/{ORG}/lists").json()["log"])
check(A.patch(B + base, json={"color": "#f87171"}).ok and len(A.get(B + f"/api/orgs/{ORG}/lists").json()["log"]) == n0,
      "#1795: the same value again: no history entry")

# ================================================================== the picture icon
r = A.put(B + base + "/icon", json={"preset": "kalmido"})
check(r.ok and row(TEAM)["icon"] == "p:kalmido" and r.json().get("icon") == "/static/icon.svg", "#1795: a preset icon " + r.text[:120])
check(A.put(B + base + "/icon", json={"preset": "../../etc"}).status_code == 400, "#1795: an unknown preset: 400")
r = A.post(B + base + "/icon", files={"file": ("i.png", png(), "image/png")}, headers=H)
check(r.ok and (row(TEAM)["icon"] or "").startswith("u:"), "#1795: an own picture " + r.text[:160])
url = r.json().get("icon", "") if r.ok else ""
check(url.startswith(f"/api/list-icon/{TEAM}/"), "#1795: the picture's URL")
check(A.get(B + url).status_code == 200, "#1795: the organisation admin sees the picture she set")
check(Bo.get(B + url).status_code == 200 and Ca.get(B + url).status_code == 200, "#1795: owner and member see it")
check(Da.get(B + url).status_code == 404, "#1795: an organisation member outside the list does not")
check(A.post(B + base + "/icon", files={"file": ("x.png", b"not a picture", "image/png")}, headers=H).status_code == 400, "#1795: no picture: 400")
check(A.post(B + base + "/icon", headers=H).status_code == 400, "#1795: no file: 400")
tok = row(TEAM)["icon"]
check(A.delete(B + base + "/icon").ok and row(TEAM)["icon"] is None, "#1795: the icon removed")
check(A.get(B + url).status_code == 404, "#1795: the old picture is gone")
log = A.get(B + f"/api/orgs/{ORG}/lists").json()["log"]
ic = [r["detail"]["icon"] for r in log if r["action"] == "icon"]
check(["picture", ""] in ic and ["kalmido", "picture"] in ic and ["", "kalmido"] in ic, f"#1795: the icon history: {ic}")
check(tok[2:] not in str(log), "#1795: the history never names the picture's token")

# ================================================================== who may not
check(Ca.patch(B + base, json={"name": "Carol was here"}).status_code == 403, "#1795: a member of the organisation (and of the list): 403")
check(Ca.put(B + base + "/icon", json={"preset": "kalmido"}).status_code == 403, "#1795: ... no icon either")
check(Bo.patch(B + base, json={"name": "Owner via org"}).status_code == 403, "#1795: the owner (no organisation admin) uses his own route")
for lid in (PRIV, BINBOX, 999999):
    check(A.patch(B + f"/api/orgs/{ORG}/lists/{lid}", json={"name": "x"}).status_code == 404, f"#1795: list {lid} (private / inbox / none): 404")
    check(A.put(B + f"/api/orgs/{ORG}/lists/{lid}/icon", json={"preset": "kalmido"}).status_code == 404, f"#1795: icon of list {lid}: 404")
    check(A.delete(B + f"/api/orgs/{ORG}/lists/{lid}/icon").status_code == 404, f"#1795: icon delete of list {lid}: 404")
check(row(PRIV)["name"] == "Bob Private" and row(PRIV)["icon"] is None, "#1795: the private list unchanged")

# an agent, even with the organisation's admin role and instance admin rights
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
AG = r.json()["id"]
dbx("UPDATE users SET is_admin=1 WHERE id=?", (AG,), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT DO NOTHING", (ORG, AG), write=True)
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, AG), write=True)
for m, u, b in (("PATCH", base, {"name": "Agent"}), ("PUT", base + "/icon", {"preset": "kalmido"}), ("DELETE", base + "/icon", None)):
    r = requests.request(m, B + u, headers=AGH, json=b)
    check(r.status_code in (401, 403), f"#1795: an agent with admin rights gets no access ({m} {u}): {r.status_code}")
check(row(TEAM)["name"] == "\U0001F680 Team renamed", "#1795: the agent changed nothing")

# another organisation's admin
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "icon": "B", "admin_id": DAVE})
check(r.status_code == 201, "setup: a second organisation with dave as its admin " + r.text[:120])
BETA = r.json()["id"]
check(A.delete(B + f"/api/orgs/{ORG}/members/{DAVE}").ok, "setup: dave leaves the first organisation")
Da = sess("dave")
check(Da.patch(B + base, json={"name": "Beta took it"}).status_code == 404, "#1795: another organisation's admin: 404 for our list")
check(Da.patch(B + f"/api/orgs/{BETA}/lists/{TEAM}", json={"name": "Beta took it"}).status_code == 404, "#1795: our list through Beta: 404")
check(Da.put(B + f"/api/orgs/{BETA}/lists/{TEAM}/icon", json={"preset": "kalmido"}).status_code == 404, "#1795: ... its icon neither")
check(row(TEAM)["name"] == "\U0001F680 Team renamed", "#1795: Beta changed nothing")

# ================================================================== #1431 the list admin's way is unchanged
Bo.put(B + f"/api/lists/{ADM}/members", json={"user_id": CAROL, "role": "admin"})
r = Ca.patch(B + f"/api/lists/{ADM}", json={"name": "Carol renamed", "color": "#c084fc"})
check(r.ok and row(ADM)["name"] == "Carol renamed" and row(ADM)["color"] == "#c084fc", "#1431: a list admin still renames / recolours " + r.text[:120])
check(Ca.patch(B + f"/api/lists/{ADM}", json={"kind": "project"}).status_code == 403, "#1431: ... and still not the type")
check(any(d.get("action") == "lrename" for d in news(Bo)), "#1431: the owner still gets lrename")

# ================================================================== the role taken away
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE username='alice')", (ORG,), write=True)
check(A.patch(B + base, json={"name": "After demotion"}).status_code == 403, "#1795: no longer an organisation admin: 403")
check(A.put(B + base + "/icon", json={"preset": "kalmido"}).status_code == 403, "#1795: ... no icon either")

print(f"p256_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
