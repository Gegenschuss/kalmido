#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.568.0 A (#4739): stage 6 of the shared core -- the projects (lists) on the core (kalmido/lists/lmcore.py). Invented names only.
 - a member added (PUT /api/lists/<id>/members): the core's share row on the project's node (list_role, list_own) and the
   list_members row; removed: the row goes into obj_revoked (restorable), the person no longer sees the project (404),
   POST /api/lists/<id>/shares/<rid>/restore -> back with the role; the file store's dialog does not show / change the row
 - a share with an expiry: after the expiry (the watchdog round) no access
 - leaving the organisation: the project roles and the core's rows go (obj_revoke_person 'leave'); a restore then is refused
   by the project's rules (409)
 - A-F10: a group shared on an organisation's project gives a guest / accounting person no role (also through a folder);
   a member demoted to guest loses it, made a member again gets it back; coming back as a guest revives nothing; a personal
   share still reaches a guest
 - one agent per project stays the area's rule (409 for a second one), the core's row is the agent's
 - PATCH /api/lists/<id> columns / kpis / props: an entry with before / after in the history (GET /api/lists/<id>/history)
 - 2.568.0 A2 (review F1-F7): the agent's / organisation agent's / a role's row goes on every way a role ends (health,
   ol_private, the watchdog); an expired row is 'expired' and comes back without its expiry; restore only turns the
   project's own rows into memberships (a file store row stays one, a group's own row 409); a participant gets 403 on the
   history; the own rows add nothing in the file store; coming back names who shared; restore as a list admin, after a new
   share (409, the row goes), for a disabled account; an agent's token on the new routes
tenant-matrix: list (another organisation's admin: 404 on the shares, the restore and the history of a project)
freelancer-matrix: lists (a person without an organisation: her private project shared by e-mail, removed, restored, history)
usage: p2568_a_lists_core_test.py <datadir>"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, dbx, docker_logs_on_first_fail, done, fresh, sess  # noqa: E402

fresh(prefix="P2568A")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments,fields"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u, rk in (("bob", "member"), ("carl", "member"), ("dora", "member"), ("gina", "guest"), ("acco", "accounting")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation")
S = {u: sess(u) for u in ("bob", "carl", "dora", "gina", "acco", "olga")}
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments,fields"})
Ol = S["olga"]


def lists_of(s):
    return {l["id"]: l for l in s.get(B + "/api/state").json()["lists"]}


def role_of(lid, who, s=A):
    m = next((x for x in lists_of(s)[lid].get("members", []) if x["user_id"] == uid[who]), None)
    return m["role"] if m else None


def sees(s, lid):
    """True when session s sees project lid (its state lists it and its overview answers)."""
    return lid in lists_of(s) and s.get(B + f"/api/lists/{lid}/overview").ok


def new_list(s, name, org=ORG, folder=""):
    r = s.post(B + "/api/lists", json={"name": name, "folder": folder, **({"org_id": org} if org else {})})
    assert r.ok, (name, r.status_code, r.text[:300])
    return r.json()["id"]


def core_row(lid, who_id):
    """The core's own share row of who_id on project lid: (role, list_role, list_own, expires_at) or None."""
    r = dbx("""SELECT s.role, s.list_role, s.list_own, s.expires_at FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
               WHERE n.kind='ref' AND n.ref_kind='list' AND n.ref_id=? AND COALESCE(s.user_id, s.agent_id)=? AND s.list_own=1""",
            (lid, who_id))
    return tuple(r[0]) if r else None


def watchdog_round():
    p = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app\nfrom kalmido.core.db import connect\nfrom kalmido.lists.lffolder import lf_expire_tick\n"
                        "c = connect()\nprint(lf_expire_tick(c))"], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)[-300:]


# ---------------------------------------------------------------- a member: the core's row, removed, restored
L1 = new_list(A, "Harbour plan")
r = A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["carl"], "role": "edit"})
check(r.ok and role_of(L1, "carl") == "edit" and sees(S["carl"], L1), "carl added as an editor " + r.text[:200])
check(core_row(L1, uid["carl"]) == ("view", "edit", 1, None), f"the core's share row: list role edit, node role view (H1) {core_row(L1, uid['carl'])}")
r = A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["bob"], "role": "admin"})
check(r.ok and core_row(L1, uid["bob"]) == ("edit", "admin", 1, None), f"an admin's row gives 'edit' on the node {core_row(L1, uid['bob'])}")
sh = A.get(B + f"/api/lists/{L1}/shares")
check(sh.ok and {x.get("user_id"): x.get("list_role") for x in sh.json()["shares"]} == {uid["carl"]: "edit", uid["bob"]: "admin"},
      "GET .../shares lists the members' rows " + sh.text[:300])
NODE = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='list' AND ref_id=?", (L1,))[0][0]
fs = A.get(B + f"/api/files/nodes/{NODE}")
check(fs.ok and not any(x.get("user_id") in (uid["carl"], uid["bob"]) for x in fs.json().get("shares") or []),
      "the file store's dialog does not show a project's member rows " + fs.text[:200])
SID = dbx("SELECT s.id FROM fs_shares s WHERE s.node_id=? AND s.user_id=?", (NODE, uid["carl"]))[0][0]
check(A.delete(B + f"/api/files/shares/{SID}").status_code == 404 and A.patch(B + f"/api/files/shares/{SID}", json={"role": "edit"}).status_code == 404,
      "nor changes / deletes it (404: the members dialog's)")
check(S["carl"].get(B + f"/api/lists/{L1}/shares").status_code == 403, "an editor does not manage the shares (403)")

r = A.delete(B + f"/api/lists/{L1}/members/{uid['carl']}")
RID = r.json().get("revoked_id") if r.ok else None
check(r.ok and RID and role_of(L1, "carl") is None, "carl removed: the answer names the revoked row " + r.text[:200])
check(not sees(S["carl"], L1) and S["carl"].get(B + f"/api/lists/{L1}/overview").status_code == 404, "carl no longer sees the project (404)")
check(core_row(L1, uid["carl"]) is None and dbx("SELECT reason, kind, ref_id FROM obj_revoked WHERE id=?", (RID,)) == [("unshare", "list", L1)],
      "the core's row is in obj_revoked (unshare, kind list)")
sh = A.get(B + f"/api/lists/{L1}/shares").json()
check(any(x["id"] == RID and x["user_id"] == uid["carl"] and x["role"] for x in sh["revoked"]), f"GET .../shares names it as taken back {sh['revoked']}")
r = A.post(B + f"/api/lists/{L1}/shares/{RID}/restore")
check(r.ok and role_of(L1, "carl") == "edit" and sees(S["carl"], L1) and core_row(L1, uid["carl"]) == ("view", "edit", 1, None),
      "restored: carl is an editor again " + r.text[:200])
check(A.post(B + f"/api/lists/{L1}/shares/{RID}/restore").status_code == 404, "a second restore: 404 (gone from obj_revoked)")
# a member from before 2.568.0 (no row of the core): removing writes it first, so it can come back the same way
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (L1, uid["dora"], "view", "view", 0, "2026-10-01T08:00:00Z"))
check(core_row(L1, uid["dora"]) is None and sees(S["dora"], L1), "dora: an old member row without the core's row")
r = A.delete(B + f"/api/lists/{L1}/members/{uid['dora']}")
RD = r.json().get("revoked_id") if r.ok else None
check(r.ok and RD and not sees(S["dora"], L1), "dora removed: restorable all the same " + r.text[:200])
check(A.post(B + f"/api/lists/{L1}/shares/{RD}/restore").ok and role_of(L1, "dora") == "view", "dora restored as a viewer")
# leaving on her own (not a manager): the row goes too
r = S["dora"].delete(B + f"/api/lists/{L1}/members/{uid['dora']}")
check(r.ok and not sees(S["dora"], L1) and core_row(L1, uid["dora"]) is None, "dora leaves on her own: her row goes " + r.text[:200])

# ---------------------------------------------------------------- an expiry
L2 = new_list(A, "Short job")
r = A.put(B + f"/api/lists/{L2}/members", json={"user_id": uid["carl"], "role": "edit", "expires_at": "2099-12-31"})
row = core_row(L2, uid["carl"])
check(r.ok and row and row[3] and str(row[3]).startswith("2099") and sees(S["carl"], L2), f"a share until 2099 {row} " + r.text[:160])
check(A.put(B + f"/api/lists/{L2}/members", json={"user_id": uid["carl"], "role": "view"}).ok and str(core_row(L2, uid["carl"])[3]).startswith("2099"),
      "a role change without expires_at keeps the expiry")
check(A.put(B + f"/api/lists/{L2}/members", json={"user_id": uid["carl"], "role": "edit", "expires_at": "2000-01-01"}).status_code == 400,
      "an expiry in the past: 400")
dbx("UPDATE fs_shares SET expires_at=? WHERE list_own=1 AND user_id=? AND node_id=(SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='list' AND ref_id=?)",
    ("2000-01-01T00:00:00Z", uid["carl"], L2))
rc, out = watchdog_round()
check(rc == 0 and role_of(L2, "carl") is None and not sees(S["carl"], L2), f"the share ran out: the watchdog round ends carl's role {out}")
check(sees(S["carl"], L1), "his other project stays")

# ---------------------------------------------------------------- leaving the organisation
r = A.delete(B + f"/api/orgs/{ORG}/members/{uid['carl']}")
check(r.ok and not sees(S["carl"], L1) and core_row(L1, uid["carl"]) is None, "carl leaves the organisation: the project and the core's row go " + r.text[:200])
rv = [x for x in A.get(B + f"/api/lists/{L1}/shares").json()["revoked"] if x["user_id"] == uid["carl"] and x["reason"] == "leave"]
check(len(rv) == 1, f"the core keeps it as taken back (leave) {rv}")
check(rv and A.post(B + f"/api/lists/{L1}/shares/{rv[0]['id']}/restore").status_code in (404, 409) and not sees(S["carl"], L1),
      "a restore after leaving: the project's rules refuse it (not in the organisation)")
check(rv and any(x["id"] == rv[0]["id"] for x in A.get(B + f"/api/lists/{L1}/shares").json()["revoked"]), "the refused restore changed nothing")

# ---------------------------------------------------------------- A-F10: groups and the organisation role
G = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [uid["bob"], uid["dora"], uid["gina"], uid["acco"]]}).json()["id"]
L3 = new_list(A, "Crew board")
check(A.put(B + f"/api/lists/{L3}/groups/{G}", json={"role": "edit"}).ok, "the group gets the project")
check(sees(S["dora"], L3) and role_of(L3, "dora") == "edit", "a member of the group: edit")
check(not sees(S["gina"], L3) and role_of(L3, "gina") is None, "a guest in the group: no role through it (A-F10)")
check(not sees(S["acco"], L3) and role_of(L3, "acco") is None, "accounting in the group: none either")
r = A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["dora"], "role": "guest"})
check(r.ok and not sees(S["dora"], L3) and role_of(L3, "dora") is None, "dora demoted to guest: the group's role is gone " + r.text[:160])
r = A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["dora"], "role": "member"})
check(r.ok and sees(S["dora"], L3) and role_of(L3, "dora") == "edit", "a member again: the group's role is back " + r.text[:160])
# through a folder shared with the group in the file store
L4 = new_list(A, "Folder work", folder="Crew")
FN = dbx("SELECT id FROM fs_nodes WHERE kind='folder' AND name='Crew' AND org_id=? AND deleted_at IS NULL", (ORG,))[0][0]
r = A.post(B + f"/api/files/nodes/{FN}/shares", json={"group_id": G, "role": "edit"})
check(r.status_code == 201 and role_of(L4, "bob") == "edit" and role_of(L4, "gina") is None, "a group's folder share: the member yes, the guest no " + r.text[:160])
# coming back as a guest
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['bob']}").ok and not sees(S["bob"], L3), "bob leaves the organisation")
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "guest"})
check(r.ok and dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["bob"])) == [("guest",)]
      and not sees(S["bob"], L3) and not sees(S["bob"], L4) and role_of(L3, "bob") is None,
      "bob back as a guest: the group revives nothing " + r.text[:160])
r = A.put(B + f"/api/lists/{L3}/members", json={"user_id": uid["gina"], "role": "view"})
check(r.ok and sees(S["gina"], L3) and role_of(L3, "gina") == "view", "a personal share still reaches a guest " + r.text[:160])

# ---------------------------------------------------------------- one agent per project
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG = []
for n in ("planbot", "sortbot"):
    r = A.post(B + "/api/my/agents", json={"username": n, "display_name": n.title(), "scopes": ["read"], "org_id": ORG})
    check(r.ok, f"setup: agent {n} " + r.text[:200])
    AG.append(r.json().get("id"))
L5 = new_list(A, "Bot project")
r = A.put(B + f"/api/lists/{L5}/agent", json={"agent_id": AG[0]})
check(r.ok and core_row(L5, AG[0]) == ("view", "edit", 1, None), f"the project's agent: the core's row is the agent's {core_row(L5, AG[0])} " + r.text[:160])
r = A.put(B + f"/api/lists/{L5}/members", json={"user_id": AG[1], "role": "edit"})
check(r.status_code == 409 and core_row(L5, AG[1]) is None, "a second agent: 409 as before, no row " + r.text[:160])
r = A.put(B + f"/api/lists/{L5}/agent", json={"agent_id": AG[1]})
check(r.ok and core_row(L5, AG[0]) is None and core_row(L5, AG[1]) == ("view", "edit", 1, None), "the agent swapped: the old row taken back, the new one there")

# ---------------------------------------------------------------- the settings' history
check(A.patch(B + f"/api/lists/{L1}", json={"columns": ["prio", "due"]}).ok, "columns set")
check(A.patch(B + f"/api/lists/{L1}", json={"props": {"video": 1}}).ok, "properties set")
h = A.get(B + f"/api/lists/{L1}/history")
e = h.json()["history"] if h.ok else []
check(h.ok and len(e) == 1 and (e[0]["after"].get("props") or {}).get("video") == 1 and "columns" in e[0]["after"] and "columns" in e[0]["before"]
      and e[0]["user_id"] == ALICE and e[0]["agent"] is False, f"one entry (ten minutes merge): before / after of columns and props {e}")
check(S["dora"].get(B + f"/api/lists/{L1}/history").status_code == 404, "who does not see the project: 404")
r = A.patch(B + f"/api/lists/{L1}", json={"name": "Harbour plan 2"})
check(r.ok and len(A.get(B + f"/api/lists/{L1}/history").json()["history"]) == 1, "a name change is no settings entry")
# tenant matrix: another organisation's admin
check(Ol.get(B + f"/api/lists/{L1}/shares").status_code == 404 and Ol.get(B + f"/api/lists/{L1}/history").status_code == 404
      and Ol.post(B + f"/api/lists/{L1}/shares/{RID}/restore").status_code == 404, "another organisation: 404 on shares, history, restore")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
PL = new_list(Fr, "Own studio", org=None)
r = Fr.put(B + f"/api/lists/{PL}/members", json={"email": "fiona@example.com", "role": "edit"})
check(r.ok and sees(Fi, PL), "frida shares her private project with fiona by e-mail " + r.text[:160])
r = Fr.delete(B + f"/api/lists/{PL}/members/{FIO}")
RF = r.json().get("revoked_id") if r.ok else None
check(r.ok and RF and not sees(Fi, PL), "removed: fiona no longer sees it " + r.text[:160])
check(Fr.post(B + f"/api/lists/{PL}/shares/{RF}/restore").ok and sees(Fi, PL), "restored: fiona sees it again")
check(Fr.patch(B + f"/api/lists/{PL}", json={"kpis": []}).ok, "frida's key figures")
check(Fr.patch(B + f"/api/lists/{PL}", json={"columns": ["due"]}).ok and len(Fr.get(B + f"/api/lists/{PL}/history").json()["history"]) == 1,
      "her project's history")
check(Fi.get(B + f"/api/lists/{PL}/shares").status_code == 403 and A.get(B + f"/api/lists/{PL}/shares").status_code == 404,
      "fiona (an editor) does not manage the shares, the instance admin does not see them")


# ---------------------------------------------------------------- 2.568.0 A2 (#4739): the review's findings (F1-F7)
import json  # noqa: E402


def pyx(code):
    """Runs code in the app's container (an app context, the system's row rules) -> (exit code, output)."""
    p = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app\nfrom kalmido.core.config import app as fa\nfrom kalmido.core.db import connect\n"
                        "from kalmido.core.pg import system_ctx\nc = connect()\nwith fa.app_context(), system_ctx(c):\n"
                        + "".join("    " + x + "\n" for x in code.strip().splitlines()) + "c.commit()\n"],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)[-400:]


def revoked_of(lid, who_id):
    """[(id, reason, by_id, row)] of the core's rows taken from who_id on project lid, newest first."""
    return [(r[0], r[1], r[2], json.loads(r[3])) for r in
            dbx("SELECT id, reason, by_id, row_json FROM obj_revoked WHERE src='fs_shares' AND kind='list' AND ref_id=? AND user_id=? ORDER BY id DESC",
                (lid, who_id))]


def node_of(lid):
    r = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='list' AND ref_id=?", (lid,))
    return r[0][0] if r else None


for u in ("erik", "fynn"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} " + r.text[:200])
    uid[u] = r.json().get("id")
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments,fields"})

# F1: the ways a role ends besides the members dialog take the core's row too
FB = Fr.post(B + "/api/my/agents", json={"username": "frhealth", "display_name": "Health bot", "scopes": ["read"]})
check(FB.ok, "setup: frida's own agent " + FB.text[:160])
FB = FB.json().get("id")
FH = new_list(Fr, "Frida check-ups", org=None)
r = Fr.put(B + f"/api/lists/{FH}/agent", json={"agent_id": FB})
check(r.ok and core_row(FH, FB) is not None, "F1: frida's agent on her project: the core's row " + r.text[:160])
r = Fr.patch(B + f"/api/lists/{FH}", json={"life": "health"})
check(r.ok and core_row(FH, FB) is None and [x[1] for x in revoked_of(FH, FB)] == ["unshare"],
      f"F1: a health project: the agent leaves and its core row goes (restorable) {core_row(FH, FB)} {revoked_of(FH, FB)} " + r.text[:120])
L7 = new_list(A, "Moving out")
r = A.put(B + f"/api/lists/{L7}/agent", json={"agent_id": AG[0]})
check(r.ok and core_row(L7, AG[0]) is not None, "F1: setup: the organisation agent on a project " + r.text[:160])
# ol_private as org_leave calls it for a brought-in project (an organisation agent not of the person leaves)
rc, out = pyx(f"from kalmido.accounts.orgs import ol_private\nol_private(c, {L7}, {uid['dora']})")
check(rc == 0 and core_row(L7, AG[0]) is None and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L7, AG[0])) == [],
      f"F1: the project leaves the organisation: the organisation agent's core row goes with it {core_row(L7, AG[0])} {out}")
# a role ended on a way nobody told the core about: the watchdog round catches it
check(core_row(L3, uid["gina"]) is not None, "F1: gina's own row on the crew board")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (L3, uid["gina"]))
rc, out = watchdog_round()
check(rc == 0 and core_row(L3, uid["gina"]) is None and revoked_of(L3, uid["gina"])[:1] and revoked_of(L3, uid["gina"])[0][1] == "unshare",
      f"F1: the watchdog round takes a core row without its list_members row {out}")

sys.exit(done("p2568_a_lists_core"))
