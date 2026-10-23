#!/usr/bin/env python3
"""2.199.0 A (#2742) the guard of the folder principle (like #1919 for freelancers): in EVERY area that keeps its documents in
folders of the file store (fs_nodes / fs_shares), a folder share works like a file system. Per area the same table of cases:
 1. a share view / edit on a folder gives that role on what lies in it, in its subfolders and on what is added LATER
 2. withdrawing the share takes it away; moving the item out of the folder takes it away
 3. an agent only with a share on exactly it (the organisation's "every member" access gives it nothing)
 4. the same in a private space -- a person WITHOUT an organisation (tests/freelancer_fixture.py) with her private agent
An area is one entry of AREAS (functions, below); 2.199 B (office) / C (sheets) fill their sections, 2.200 (knowledge),
2.201 (lists / projects), 2.202 (address books, contracts) add theirs. Invented names only.
freelancer-matrix: files
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
FEAT = "cal,comments,collab,files,docs,office,clients,sheets"

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
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "files:read", "office", "sheets:read"], **({"org_id": org} if org else {})})
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
for area, f in AREAS.items():
    parity(area, f, f"org:{ORG}", A, Bo, BOB, AGH, AG, tag="organisation")
    parity(area, f, "private", A, Bo, BOB, tag="private with a person")
    parity(area, f, "private", Fr, None, None, FAGH, FAG, tag="freelancer")  # freelancer-matrix: files (no organisation)

print(f"folder_parity: {OKS[0]} ok, {len(FAILS)} failed -- areas: {', '.join(AREAS)}")
sys.exit(1 if FAILS else 0)
