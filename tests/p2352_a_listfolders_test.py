#!/usr/bin/env python3
"""2.352.0 A (#2748): the folders of the lists are folders of the file store's projects trees (lists/lffolder.py), rights of a
folder share at runtime (list_members.frole) instead of a copy. Invented names only.
 - a folder share reaches every list in it, also lists that come later and lists deeper than 2 levels; revoking it and moving
   the list out take it away; a share set on the list itself stays (the higher role counts)
 - the file store's share routes on a projects folder (person, group) work the same; a group's member who leaves the group,
   a person who leaves the organisation and an expired share (watchdog round, no other change) lose the list
 - removing a person from one list by hand keeps the folder from bringing them back there
 - GET /api/lists/tree, POST /api/lists/folders, POST /api/lists/tree/move (paths follow the tree, depth > 2)
 - the organisation boundary: no share target of another organisation, another organisation's admin sees nothing
 - the one-way migration (lf_migrate): many folders, copies, lists removed / set lower by hand -> who sees what is the same
 - freelancer-matrix: lists (a person without an organisation: her own tree, folders, depth, moving, sharing)
usage: p2352_a_listfolders_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
DATA = sys.argv[1]
if not os.environ.get("P2352A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, capture_output=True, text=True)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, FAILS, OKS, check, dbx, sess  # noqa: E402

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation")
S = {u: sess(u) for u in ("bob", "carl", "dora", "olga")}
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})


def lists_of(s):
    return {l["id"]: l for l in s.get(B + "/api/state").json()["lists"]}


def mem(lid, who):
    """alice's view of a member: (role, via_folder) or None."""
    m = next((x for x in lists_of(A)[lid].get("members", []) if x["user_id"] == uid[who]), None)
    return (m["role"], m.get("via_folder")) if m else None


def new_list(s, name, folder="", org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "folder": folder, "org_id": org})
    check(r.ok, f"setup: list {name} " + r.text[:200])
    return r.json()["id"]


def tree(s):
    r = s.get(B + "/api/lists/tree")
    check(r.ok, "GET /api/lists/tree " + r.text[:200])
    return r.json()["spaces"] if r.ok else []


def node_of(s, lid):
    for sp in tree(s):
        for x in sp["lists"]:
            if x["list_id"] == lid:
                return x, sp
    return None, None


def folder_node(s, path, org=ORG):
    for sp in tree(s):
        if sp["org_id"] == org:
            for f in sp["folders"]:
                if f["path"] == path and f["mine"]:
                    return f["id"]
    return None


# ---------------------------------------------------------------- runtime rights through the old route
L1 = new_list(A, "Website", "Clients")
r = A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": uid["bob"], "role": "edit"})
check(r.ok and r.json().get("shared") == 1, "share the folder: its list " + r.text[:200])
check(mem(L1, "bob") == ("edit", True), f"bob edits the list through the folder (via_folder) {mem(L1, 'bob')}")
L2 = new_list(A, "Deep plan", "Clients/North/Harbour/Pier")
check(L2 in lists_of(S["bob"]) and mem(L2, "bob") == ("edit", True), "a later list four levels deep is shared too (depth > 2)")
check(lists_of(A)[L2]["folder"] == "Clients/North/Harbour/Pier", "the path keeps four levels")
check(A.patch(B + f"/api/lists/{L2}", json={"folder": "Elsewhere"}).ok and L2 not in lists_of(S["bob"]), "moved out of the folder: bob loses it")
L3 = new_list(A, "Budget talk", "Clients")
check(A.put(B + f"/api/lists/{L3}/members", json={"user_id": uid["carl"], "role": "edit"}).ok, "setup: carl directly on L3")
A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": uid["carl"], "role": "view"})
check(mem(L3, "carl") == ("edit", False) and mem(L1, "carl") == ("view", True), f"the higher role counts: carl edit on L3, view on L1 {mem(L3, 'carl')}")
r = A.delete(B + "/api/folders/people", json={"folder": "Clients", "user_id": uid["carl"]})
check(r.ok and mem(L1, "carl") is None and mem(L3, "carl") == ("edit", False), "revoked: carl loses L1, keeps his own share on L3")
check(L1 not in lists_of(S["carl"]), "... carl no longer sees L1")
# 2.352.0 A (#2748): was "stop sharing new lists: the lists stay" (#929) -- a folder's share ends at runtime now
check(A.delete(B + f"/api/lists/{L1}/members/{uid['bob']}").ok and mem(L1, "bob") is None, "bob removed from L1 by hand")
L4 = new_list(A, "Another", "Clients")
check(mem(L4, "bob") == ("edit", True) and mem(L1, "bob") is None, "the folder does not bring bob back to L1, a new list still reaches him")
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["bob"], "role": "view"}).ok and mem(L1, "bob")[0] == "edit",
      "shared again by hand: the folder reaches him there again (edit is higher)")

# ---------------------------------------------------------------- the tree routes
x, sp = node_of(A, L1)
FC = folder_node(A, "Clients")
check(x and FC and x["parent_id"] == FC and sp["org_id"] == ORG, f"the tree: L1's node lies in the folder Clients of the organisation's tree {x}")
check(any(f["path"] == "Clients/North/Harbour/Pier" for f in sp["folders"]), "the tree has the deep folders")
bx, _ = node_of(S["bob"], L1)
check(bx is not None and S["bob"].get(B + "/api/lists/tree").ok, "bob's tree shows the shared list")
r = A.post(B + "/api/lists/folders", json={"parent_id": sp["root"], "name": "Archive"})
check(r.status_code == 201 and r.json().get("path") == "Archive", "a new folder at the top " + r.text[:200])
FA = r.json().get("id")
r = A.post(B + "/api/lists/tree/move", json={"node_id": x["node_id"], "parent_id": FA})
check(r.ok and r.json().get("path") == "Archive" and lists_of(A)[L1]["folder"] == "Archive", "the list moved in the tree: its path follows " + r.text[:200])
check(mem(L1, "bob") == ("view", False), f"moved out of the shared folder: only bob's own share (view) is left {mem(L1, 'bob')}")
r = A.post(B + "/api/lists/tree/move", json={"node_id": FA, "parent_id": FC})
check(r.ok and lists_of(A)[L1]["folder"] == "Clients/Archive" and mem(L1, "bob")[0] == "edit", "a folder moved into the shared one: path and right follow")
check(S["bob"].post(B + "/api/lists/tree/move", json={"node_id": x["node_id"], "parent_id": sp["root"]}).status_code in (403, 404),
      "bob may not move alice's list")

# ---------------------------------------------------------------- a projects folder into the trash: its lists move up, its share ends
LT = new_list(A, "Trash test", "Gone/Inner")
FG = folder_node(A, "Gone")
A.post(B + f"/api/files/nodes/{FG}/shares", json={"user_id": uid["dora"], "role": "edit"})
check(mem(LT, "dora") == ("edit", True), "setup: dora through the folder Gone")
r = A.delete(B + f"/api/files/nodes/{FG}")
check(r.ok and lists_of(A)[LT]["folder"] in ("", "Gone") and LT in lists_of(A), f"the folder in the trash: the list stays, one level up ({r.status_code} {lists_of(A).get(LT, {}).get('folder')!r})")
check(mem(LT, "dora") is None, "... and the folder's share no longer reaches it")
xl, _ = node_of(A, LT)
check(A.delete(B + f"/api/files/nodes/{xl['node_id']}").status_code == 409 and LT in lists_of(A), "a list's node alone cannot go into the trash")

# ---------------------------------------------------------------- folder settings by the folder's node (part E's client)
r = A.put(B + "/api/folders/props", json={"node": FC, "props": {"time_tracking": True}, "apply": "new"})
check(r.ok and A.get(B + "/api/folders/props", params={"folder": "Clients"}).json()["props"].get("time_tracking") is True,
      "folder settings written by node= are the folder's (path) " + r.text[:200])
check(A.get(B + "/api/folders/props", params={"node": FA}).json().get("folder") == "Clients/Archive", "read by node= of a subfolder")
check(S["bob"].get(B + "/api/folders/props", params={"node": FC}).status_code == 404, "another person's folder node: 404")
check(A.get(B + "/api/folders/agents", params={"node": FC}).json().get("folder") == "Clients", "the folder's agents by node=")

# ---------------------------------------------------------------- the file store's share dialog on a projects folder, groups
r = A.post(B + f"/api/files/nodes/{FC}/shares", json={"user_id": uid["dora"], "role": "view"})
check(r.status_code == 201 and mem(L4, "dora") == ("view", True), "a share in the file store's dialog reaches the lists " + r.text[:200])
SD = r.json().get("id")
check(any(p["user_id"] == uid["dora"] for p in A.get(B + "/api/folders/people", params={"folder": "Clients"}).json()["people"]),
      "the old folder people show it (mirror)")
r = A.patch(B + f"/api/files/shares/{SD}", json={"list_role": "admin"})
check(r.ok and mem(L4, "dora") == ("admin", True) and any(x.get("list_role") == "admin" for x in r.json()["shares"]),
      "the dialog's list role: dora is a list admin through the folder " + r.text[:200])
check(A.delete(B + f"/api/files/shares/{SD}").ok and mem(L4, "dora") is None, "the share deleted: dora loses the lists")
G = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [uid["dora"], uid["carl"]]}).json()["id"]
r = A.post(B + f"/api/files/nodes/{FC}/shares", json={"group_id": G, "role": "edit"})
check(r.status_code == 201 and mem(L4, "dora") == ("edit", True) and mem(L4, "carl") == ("edit", True), "a group's share: its members " + r.text[:200])
check(A.patch(B + f"/api/admin/groups/{G}", json={"members": [uid["carl"]]}).ok and mem(L4, "dora") is None and mem(L4, "carl"),
      "dora left the group: she loses the lists, carl keeps them")
# expiry: the share ran out -> the watchdog round takes it away without any other change
SG = r.json().get("id")
dbx("UPDATE fs_shares SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00Z", SG))
p = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                    "import app\nfrom kalmido.core.db import connect\nfrom kalmido.lists.lffolder import lf_expire_tick\n"
                    "c = connect()\nprint(lf_expire_tick(c))"], capture_output=True, text=True)
check(p.returncode == 0 and mem(L4, "carl") is None, f"an expired share: carl loses the lists in the watchdog round {p.stderr[-300:]}")

# ---------------------------------------------------------------- several agents through a folder (like the file store)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AGS = []
for n in ("sortbot", "notebot"):
    r = A.post(B + "/api/my/agents", json={"username": n, "display_name": n.title(), "scopes": ["read"], "org_id": ORG})
    check(r.ok, f"setup: agent {n} " + r.text[:200])
    AGS.append((r.json().get("id"), {"X-Requested-With": "kalmido", "Authorization": "Bearer " + r.json().get("token", "")}))
L7 = new_list(A, "Bot work", "Bots")
FB = folder_node(A, "Bots")
for aid, _ in AGS:
    r = A.post(B + f"/api/files/nodes/{FB}/shares", json={"agent_id": aid, "role": "edit"})
    check(r.status_code == 201, "share the folder with an agent " + r.text[:200])
ms = {m["user_id"]: m for m in lists_of(A)[L7].get("members", [])}
check(all(ms.get(aid, {}).get("via_folder") for aid, _ in AGS), f"both agents of the folder are in the list {list(ms)}")
check(all(requests.get(B + f"/api/v1/lists/{L7}", headers=h).ok for _, h in AGS), "both agents read the list over the API")
vm = requests.get(B + f"/api/v1/lists/{L7}/members", headers=AGS[0][1])
check(vm.ok and any(m.get("via_folder") for m in vm.json().get("data", [])), "the API's members say via_folder " + vm.text[:200])
r = A.put(B + f"/api/lists/{L7}/agent", json={"agent_id": AGS[0][0]})
ms = {m["user_id"]: m for m in lists_of(A)[L7].get("members", [])}
check(r.ok and AGS[1][0] in ms and ms.get(AGS[0][0], {}).get("via_folder") is False, f"the list's own agent set: the other folder agent stays {r.text[:200]}")
check(A.put(B + f"/api/lists/{L7}/agent", json={"agent_id": None}).ok and {a for a, _ in AGS} <= {m["user_id"] for m in lists_of(A)[L7].get("members", [])},
      "the list's own agent removed: it stays one of the folder's agents")

# ---------------------------------------------------------------- "Reading" follows the lists: read later is a list of the tree
A.patch(B + "/api/settings", json={"features": "collab,files,comments,reading"})
r = A.post(B + "/api/reading", json={"url": "https://example.com/article", "title": "An article"})
RL = r.json().get("list_id") if r.ok else None
check(r.status_code in (200, 201) and RL and node_of(A, RL)[0] is not None, "the read-later project lies in the projects tree " + r.text[:200])
check(A.patch(B + f"/api/lists/{RL}", json={"folder": "Bots"}).ok and mem(RL, "bob") is None, "setup: read later in the agents' folder")
ms = {m["user_id"] for m in lists_of(A)[RL].get("members", [])}
check(not any(a in ms for a, _ in AGS), "a folder never shares read later with an agent")
check(all(requests.get(B + f"/api/v1/lists/{RL}", headers=h).status_code in (403, 404) for _, h in AGS), "... the agents cannot read it")

# ---------------------------------------------------------------- the organisation boundary
r = A.post(B + f"/api/files/nodes/{FC}/shares", json={"user_id": uid["olga"], "role": "view"})
check(r.status_code == 409 and L4 not in lists_of(S["olga"]), "another organisation's person is no share target " + r.text[:120])
check(S["olga"].post(B + "/api/lists/tree/move", json={"node_id": x["node_id"], "parent_id": FC}).status_code == 404, "olga: 404 on alice's nodes")
check(not any(sp2["org_id"] == ORG for sp2 in tree(S["olga"])), "olga's tree has no part of alice's organisation")
L5 = new_list(A, "Team list", "Clients")
check(mem(L5, "bob") == ("edit", True), "setup: bob through the folder")
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['bob']}").ok, "bob leaves the organisation")
A.patch(B + f"/api/lists/{L5}", json={"folder": "Clients"})
L6 = new_list(A, "After", "Clients")
check(L5 not in lists_of(S["bob"]) and L6 not in lists_of(S["bob"]), "the folder's share no longer reaches him (the workspace)")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
PL = Fr.post(B + "/api/lists", json={"name": "Own work", "folder": "Jobs/2026/Spring"}).json()["id"]
fsp = [s for s in tree(Fr) if s["org_id"] is None]
check(len(fsp) == 1 and any(l["list_id"] == PL for l in fsp[0]["lists"]), "the freelancer's own tree has her list")
r = Fr.post(B + "/api/lists/folders", json={"parent_id": fsp[0]["root"], "name": "Done"})
check(r.status_code == 201, "she makes a folder at the top " + r.text[:120])
xn = next(l for l in fsp[0]["lists"] if l["list_id"] == PL)
check(Fr.post(B + "/api/lists/tree/move", json={"node_id": xn["node_id"], "parent_id": r.json()["id"]}).ok
      and lists_of(Fr)[PL]["folder"] == "Done", "she moves the list in the tree, the path follows")
check(Fr.post(B + "/api/lists/folders", json={"parent_id": next(s for s in tree(A) if s["org_id"] == ORG)["root"], "name": "x"}).status_code in (403, 404),
      "she cannot add to the organisation's tree")

# ---------------------------------------------------------------- the one-way migration: who sees what stays the same
# old-style data (2.351): path folders, folder_people and their copies in the lists as personal member rows
people = [uid["carl"], uid["dora"]]
mig = []
for i in range(5):
    for j in range(3):
        mig.append((new_list(A, f"M{i}-{j}", f"Mig{i}" + ("/Sub" if j == 2 else "")), i, j))
for lid, i, j in mig:
    for k, p in enumerate(people):
        role = "view" if k else "edit"
        dbx("INSERT INTO folder_people(owner_id,folder,user_id,role,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
            (ALICE, f"Mig{i}", p, role, "2026-10-01T08:00:00Z"))
        if (i + j + k) % 4 == 3:
            continue  # removed by hand before
        own = "view" if (i + k) % 3 == 1 and role == "edit" else role  # set lower by hand
        dbx("INSERT INTO list_members(list_id,user_id,role,own_role,folder,sort,added_at) VALUES(?,?,?,?,?,?,?)",
            (lid, p, own, own, "", 0, "2026-10-01T08:00:00Z"))
ids = ",".join(str(x[0]) for x in mig)
before = sorted((r[0], r[1], r[2]) for r in dbx(f"SELECT list_id, user_id, role FROM list_members WHERE list_id IN ({ids})"))
seen = {p: {l for l in lists_of(S["carl" if p == uid["carl"] else "dora"]) if l in {x[0] for x in mig}} for p in people}
p = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                    "import app, json\nfrom kalmido.core.db import connect\nfrom kalmido.lists.lffolder import lf_migrate\n"
                    "c = connect()\nn = lf_migrate(c)\nc.commit()\nprint(json.dumps(n))"], capture_output=True, text=True)
check(p.returncode == 0, "lf_migrate ran " + (p.stdout + p.stderr)[-400:])
cnt = json.loads((p.stdout.strip().splitlines() or ["{}"])[-1] or "{}") if p.returncode == 0 else {}
after = sorted((r[0], r[1], r[2]) for r in dbx(f"SELECT list_id, user_id, role FROM list_members WHERE list_id IN ({ids})"))
check(before == after, f"who sees what with which role: the same after the migration ({len(before)} rows) {set(before) ^ set(after)}")
seen2 = {p: {l for l in lists_of(S["carl" if p == uid["carl"] else "dora"]) if l in {x[0] for x in mig}} for p in people}
check(seen == seen2, "the people's states show the same lists")
check(cnt.get("shares", 0) >= 10 and cnt.get("folder_rows", 0) > 0 and cnt.get("skips", 0) > 0, f"the migration's counts {cnt}")
fr = dbx(f"SELECT COUNT(*) FROM list_members WHERE list_id IN ({ids}) AND frole IS NOT NULL AND own_role IS NULL")[0][0]
check(fr > 0, f"the copies are folder roles now ({fr})")
p2 = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                     "import app, json\nfrom kalmido.core.db import connect\nfrom kalmido.lists.lffolder import lf_migrate\n"
                     "c = connect()\nn = lf_migrate(c)\nc.commit()\nprint(json.dumps(n))"], capture_output=True, text=True)
again = sorted((r[0], r[1], r[2]) for r in dbx(f"SELECT list_id, user_id, role FROM list_members WHERE list_id IN ({ids})"))
check(p2.returncode == 0 and again == before and '"shares": 0' in p2.stdout, "a second run changes nothing (idempotent) " + p2.stdout[-200:])
A.delete(B + "/api/folders/people", json={"folder": "Mig0", "user_id": uid["carl"]})
gone = {r[0] for r in dbx(f"SELECT list_id FROM list_members WHERE user_id=? AND frole IS NOT NULL AND own_role IS NULL AND list_id IN ({ids})", (uid["carl"],))}
check(not any(lid in gone for lid, i, j in mig if i == 0), "after the migration revoking a folder takes the former copies away")

print(f"p2352_a_listfolders: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
