#!/usr/bin/env python3
"""2.199.0 A (#2742) the guard of the folder principle (like #1919 for freelancers): in EVERY area that keeps its documents in
folders of the file store (fs_nodes / fs_shares), a folder share works like a file system. Per area the same table of cases:
 1. a share view / edit on a folder gives that role on what lies in it, in its subfolders and on what is added LATER
 2. withdrawing the share takes it away; moving the item out of the folder takes it away
 3. an agent only with a share on exactly it (the organisation's "every member" access gives it nothing)
 4. the same in a private space -- a person WITHOUT an organisation (tests/freelancer_fixture.py) with her private agent
An area is one entry of AREAS (functions, below); 2.199 B (office) / C (sheets) fill their sections, 2.200 (knowledge),
2.201 (lists / projects), 2.202 (address books, contracts) add theirs. Invented names only.
freelancer-matrix: files  freelancer-matrix: office  freelancer-matrix: wiki
usage: folder_parity_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,files,docs,office,clients,sheets,wiki"  # 2.200.0 B (#2747): + wiki

if not os.environ.get("FOLDERPAR_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, "setup: bob as member " + r.text[:200])
BOB = r.json().get("id")
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def agent(s, name, org=None):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "files:read", "office", "sheets:read", "wiki:read"], **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}


# ---------------------------------------------------------------- the areas
# An area: dict of functions (s = a logged-in session of the folder's owner, ws = "org:<id>" | "private"):
#   folder(s, ws, name, parent=None) -> folder node id    item(s, ws, folder) -> the item's id (a document of the area in it)
#   role(s, item) -> None | 'view' | 'edit' (the person's role on the item)   agent_role(headers, item) -> the same for an agent
#   move_out(s, ws, item, folder) -> moves the item into another folder of the same workspace
# Shares are always the file store's (POST /api/files/nodes/<folder>/shares), the same for every area.
def _up(s, parent, name):
    r = s.post(B + "/api/files/upload", data={"parent_id": parent}, files={"file": (name, f"text of {name}".encode(), "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def _folder(s, ws, name, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": ws})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fs_role(s, item):
    r = s.get(B + f"/api/files/nodes/{item}")
    if not r.ok:
        return None
    x = r.json().get("role")
    return "edit" if x == "owner" else x


def _fs_agent_role(h, item):
    r = requests.get(B + f"/api/v1/files/{item}", headers=h)
    if not r.ok:
        return None
    x = r.json().get("role")
    return "edit" if x == "owner" else x


AREAS = {}
# --- area: file store (2.199 A)
AREAS["files"] = {"folder": _folder, "item": lambda s, ws, f: _up(s, f, f"doc-{f}.txt"), "role": _fs_role, "agent_role": _fs_agent_role,
                  "move_out": lambda s, ws, item, f: s.patch(B + f"/api/files/nodes/{item}", json={"parent_id": f}).raise_for_status()}
# --- area: office (2.199 B) ---
# Fill in: folder = the office's folders (fs_nodes below the office root), item = an office document filed there (a
# reference node, files/fsref.py: POST /api/files/refs), role = the role the office's own routes give (read / edit the
# DOCUMENT, never a special right), agent_role = the same over /api/v1, move_out = POST /api/files/refs with another parent.
# 2.199.0 B (#2742): a quotation of the office of ws (the organisation's / a personal office = private) filed by a reference
# node; role = what the folder way gives (GET /api/fsref/office_doc/<id>: the higher one of folder and office group), the
# agent's role = its role on the node over /api/v1 (agents only read). Bob is put into the office group "Staff" (no
# quotations), so the office alone gives him nothing and every role he gets comes from the folder.
OF_NODE = {}


def _of_item(s, ws, folder):
    s.patch(B + "/api/settings", json={"workspace": ws, "features": FEAT})
    r = s.post(B + "/api/office/docs", json={"kind": "offer", "items": [{"title": "Edit day", "qty": 1, "rate": 800}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + "/api/files/refs", json={"ref_kind": "office_doc", "ref_id": did, "parent_id": folder})
    assert r.ok, r.text
    OF_NODE[did] = r.json()["node"]["id"]
    return did


def _of_role(s, did):
    r = s.get(B + f"/api/fsref/office_doc/{did}")
    return r.json().get("folder_role") if r.ok else None


def _of_agent_role(h, did):
    return _fs_agent_role(h, OF_NODE[did])


def _of_move(s, ws, did, folder):
    r = s.post(B + "/api/files/refs", json={"ref_kind": "office_doc", "ref_id": did, "parent_id": folder})
    assert r.ok, r.text


A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "office: bob in the group Staff (no quotations)")
AREAS["office"] = {"folder": _folder, "item": _of_item, "role": _of_role, "agent_role": _of_agent_role, "move_out": _of_move}
_OPEN = _folder(A, f"org:{ORG}", "Open to the organisation")
check(A.patch(B + f"/api/files/nodes/{_OPEN}", json={"org_access": "edit"}).ok, "office: a folder opened to every member (org_access)")
_OQ = _of_item(A, f"org:{ORG}", _OPEN)
check(_of_role(Bo, _OQ) is None and Bo.get(B + f"/api/fsref/office_doc/{_OQ}/pdf").status_code == 404,
      "office: org_access never opens a filed quotation to a member without an office group for it (only shares with exactly him)")
# --- area: sheets (2.199 C) ---
# folder = a folder of the tables (POST /api/sheets/folders: below the workspace's root "Tables"), item = a table made right
# in it (folder_id); in an organisation attached to a project only its owner sees (else every member has a role through the
# space), role = the web route's can_write, agent_role = the same over /api/v1/sheets, move_out = POST /api/files/refs.
_SH_LISTS, _SH_ON = {}, set()


def _sh_feature(s):
    """The module "sheets" on for this session's person (the freelancer fixture's FEATURES lack it)."""
    if id(s) in _SH_ON:
        return
    f = (s.get(B + "/api/state").json().get("settings", {}).get("features") or "").split(",")
    if "sheets" not in f:
        s.patch(B + "/api/settings", json={"features": ",".join([x for x in f if x] + ["sheets"])})
    _SH_ON.add(id(s))


def _sh_folder(s, ws, name, parent=None):
    _sh_feature(s)
    r = s.post(B + "/api/sheets/folders", json={"name": name, "space": ws, **({"parent_id": parent} if parent else {})})
    assert r.status_code == 201, r.text
    return r.json()["folder"]["id"]


def _sh_item(s, ws, folder):
    b = {"title": f"Table in {folder}", "space": ws, "folder_id": folder}
    if ws.startswith("org:"):
        if ws not in _SH_LISTS:
            _SH_LISTS[ws] = s.post(B + "/api/lists", json={"name": "Owner only", "org_id": int(ws[4:])}).json()["id"]
        b["list_id"] = _SH_LISTS[ws]
    r = s.post(B + "/api/sheets", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sh_role(s, item):
    r = s.get(B + f"/api/sheets/{item}")
    return ("edit" if r.json().get("can_write") else "view") if r.ok else None


def _sh_agent_role(h, item):
    r = requests.get(B + f"/api/v1/sheets/{item}", headers=h)
    return ("edit" if r.json().get("can_write") else "view") if r.ok else None


AREAS["sheets"] = {"folder": _sh_folder, "item": _sh_item, "role": _sh_role, "agent_role": _sh_agent_role,
                   "move_out": lambda s, ws, item, f: s.post(B + "/api/files/refs", json={"ref_kind": "sheet", "ref_id": item,
                                                                                         "parent_id": f}).raise_for_status()}


# --- area: knowledge (2.200 B, #2747) ---
# folder = a knowledge folder (POST /api/wiki/folders: below the workspace's root "Knowledge"), item = a page made in it (its
# path = the folder path + its name; the tree check files it), role = GET /api/wiki/pages/<id> "role" (the higher one of space
# and folder shares), agent_role = GET /api/v1/wiki/pages/<id> "role" (scope wiki:read), move_out = the
# page's node into another folder (the file store's route; the path follows). In an organisation every member reads the
# pages through the space (as before 2.200): the person without a role of their own is a guest there (org_other).
WK_PATH, WK_NODE, WK_N = {}, {}, [0]


def _wk_feature(s):
    f = (s.get(B + "/api/state").json().get("settings", {}).get("features") or "").split(",")
    if "wiki" not in f:
        s.patch(B + "/api/settings", json={"features": ",".join([x for x in f if x] + ["wiki"])})


def _wk_folder(s, ws, name, parent=None):
    _wk_feature(s)
    r = s.post(B + "/api/wiki/folders", json={"space": ws, "name": name, **({"parent_id": parent} if parent else {})})
    assert r.status_code == 201, r.text
    WK_PATH[r.json()["folder"]["id"]] = r.json()["folder"]["path"]
    return r.json()["folder"]["id"]


def _wk_item(s, ws, folder):
    WK_N[0] += 1
    r = s.post(B + "/api/wiki/pages", json={"space": ws, "path": f"{WK_PATH[folder]}/Page {WK_N[0]}", "body": "text"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    WK_NODE[pid] = s.get(B + f"/api/wiki/pages/{pid}").json()["node_id"]
    return pid


def _wk_role(s, pid):
    r = s.get(B + f"/api/wiki/pages/{pid}")
    return r.json().get("role") if r.ok else None


def _wk_agent_role(h, pid):
    # 2.200.0 (#1781): the agents' knowledge route (wiki:read; a knowledge node over /api/v1/files needs it too)
    r = requests.get(B + f"/api/v1/wiki/pages/{pid}", headers=h)
    return r.json().get("role") if r.ok else None


def _wk_move(s, ws, pid, folder):
    r = s.patch(B + f"/api/files/nodes/{WK_NODE[pid]}", json={"parent_id": folder})
    assert r.ok, r.text


r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "guest"}], "username": "gina", "display_name": "Gina",
                                   "password": "password123", "email": "gina@example.com"})
check(r.ok, "setup: gina as guest " + r.text[:200])
GINA, Gi = r.json().get("id"), sess("gina")
AREAS["wiki"] = {"folder": _wk_folder, "item": _wk_item, "role": _wk_role, "agent_role": _wk_agent_role, "move_out": _wk_move,
                 "org_other": (Gi, GINA)}


def parity(area, f, ws, owner, other=None, other_id=None, agent_h=None, agent_id=None, tag=""):
    """The cases of one area in one workspace. other = a person of the workspace without a role of their own (None in a
    private space without people: only the agent's cases)."""
    root = f["folder"](owner, ws, f"Shared {tag}")
    sub = f["folder"](owner, ws, f"Sub {tag}", root)
    away = f["folder"](owner, ws, f"Away {tag}")
    i1, i2 = f["item"](owner, ws, root), f["item"](owner, ws, sub)
    pre = f"{area} / {tag}"
    check(f["role"](owner, i1) == "edit", f"{pre}: the owner edits")
    if other:
        check(f["role"](other, i1) is None and f["role"](other, i2) is None, f"{pre}: not shared = no role")
        r = owner.post(B + f"/api/files/nodes/{root}/shares", json={"user_id": other_id, "role": "view"})
        check(r.status_code == 201, f"{pre}: share view " + r.text[:200])
        sid = r.json().get("id")
        check(f["role"](other, i1) == "view" and f["role"](other, i2) == "view", f"{pre}: view on the content and in the subfolder")
        i3 = f["item"](owner, ws, sub)
        check(f["role"](other, i3) == "view", f"{pre}: view on what is added later")
        check(owner.patch(B + f"/api/files/shares/{sid}", json={"role": "edit"}).ok and f["role"](other, i2) == "edit", f"{pre}: share edit = edit")
        f["move_out"](owner, ws, i1, away)
        check(f["role"](other, i1) is None and f["role"](other, i2) == "edit", f"{pre}: moved out = no role, the rest stays")
        check(owner.delete(B + f"/api/files/shares/{sid}").ok and f["role"](other, i2) is None and f["role"](other, i3) is None, f"{pre}: withdrawn = no role")
    if agent_h:
        if ws.startswith("org:"):
            owner.patch(B + f"/api/files/nodes/{root}", json={"org_access": "view"})
        check(f["agent_role"](agent_h, i2) is None, f"{pre}: the agent without a share: nothing (also with organisation access)")
        r = owner.post(B + f"/api/files/nodes/{root}/shares", json={"agent_id": agent_id, "role": "view"})
        check(r.status_code == 201, f"{pre}: share with the agent " + r.text[:200])
        check(f["agent_role"](agent_h, i2) == "view", f"{pre}: the agent with its share: view in the subfolder")
        i4 = f["item"](owner, ws, sub)
        check(f["agent_role"](agent_h, i4) == "view", f"{pre}: the agent: view on what is added later")
        owner.delete(B + f"/api/files/shares/{r.json().get('id')}")
        check(f["agent_role"](agent_h, i2) is None, f"{pre}: the agent: withdrawn = nothing")
        if ws.startswith("org:"):
            owner.patch(B + f"/api/files/nodes/{root}", json={"org_access": ""})


AG, AGH = agent(A, "orgshelf", ORG)
FID, Fr = freelancer(B, A)
FAG, FAGH = agent(Fr, "fridashelf")
# 2.238.0 A (#2863): a filed office document opens to an agent only with the office's agent switches (like /api/v1/office)
for s_, ag_ in ((A, AG), (Fr, FAG)):
    check(s_.patch(B + f"/api/office/agents/{ag_}", json={"office_drafts": True}).ok and s_.put(B + "/api/office/settings", json={"agents_read": 1}).ok,
          "office: the agent's switch and the area's agents switch on")
for area, f in AREAS.items():
    oo, ooid = f.get("org_other", (Bo, BOB))  # 2.200.0 B (#2747): the knowledge area: a guest (members read every page)
    parity(area, f, f"org:{ORG}", A, oo, ooid, AGH, AG, tag="organisation")
    parity(area, f, "private", A, Bo, BOB, tag="private with a person")
    parity(area, f, "private", Fr, None, None, FAGH, FAG, tag="freelancer")  # freelancer-matrix: files (no organisation)

print(f"folder_parity: {OKS[0]} ok, {len(FAILS)} failed -- areas: {', '.join(AREAS)}")
sys.exit(1 if FAILS else 0)
