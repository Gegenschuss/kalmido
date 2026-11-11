#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.647.0 (#5047): table shares have no card without its core share any more. Invented names only.
 - organisation import: a table shared with a guest comes along with its card AND its core share (fs_shares of the store) --
   bound to each other, one right only; ending it in the table's dialog ends the core share too, ending it in the file
   store's dialog ends the card too (before: two unbound rights, one of them stayed open)
 - the undo of a table's move between workspaces: the shares back get their core share again -- the guest reads the table
   again and the dialog lists her (before: only revoked_at was cleared, the core share was gone, she read nothing)
 - no fallback: a card without a core share (core_id NULL) gives nothing; a change of its role in the dialog hangs it on
   the core (person without organisation: freelancer-matrix)
2.937.0 (#5244, stage 7c): no card any more -- the import brings the core shares only (both dialogs show the same row, ending
it in one ends it in the other), the undo of a move restores the core share, a person without organisation shares by name on
the core; the forward copy of old rows and their drop: p2937_a_kern_sheets_test.
Starts its OWN container (workspaces mode + KALMIDO_SECRET_KEY for the organisation export; P2647B_NOSTART=1 = it runs).
usage: p2647_b_sheet_core_test.py <datadir>"""
# freelancer-matrix: sheets
# tenant-matrix: sheet_share
import base64
import hashlib
import os
import sys
import time

import requests

import kt
from freelancer_fixture import FEATURES, freelancer
from kt import B, check, dbx, sess, su_get

FEAT = FEATURES if "sheets" in FEATURES else FEATURES + ",sheets"
kt.fresh(prefix="P2647B", env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(),
                               "KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
orgs = {}
for name in ("Alpha Team", "Gamma Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORG3 = orgs["Alpha Team"], orgs["Gamma Leer"]
r = A.post(B + "/api/users", json={"username": "gina", "display_name": "Gina Gast", "password": "password123", "email": "gina@example.com"})
assert r.ok, r.text
GINA = r.json()["id"]
for o in (ORG, ORG3):  # a guest reads an organisation's table only through a share
    assert A.put(B + f"/api/orgs/{o}/members", json={"email": "gina@example.com", "role": "guest"}).ok
Gi = sess("gina")
Gi.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def table(s, title, space):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def share(s, sid, who, role="read"):
    r = s.post(B + f"/api/sheets/{sid}/shares", json={"user_id": who, "role": role})
    check(r.status_code == 201, f"setup: table {sid} shared with {who} {r.status_code} {r.text[:160]}")
    return r.json().get("id")


def core(sid, who):
    """The core shares (fs_shares ids) of who on table sid's own node."""
    return [x[0] for x in dbx("SELECT s.id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' "
                              "AND n.ref_id=? AND (s.user_id=? OR s.agent_id=?)", (sid, who, who))]


def listed(s, sid):
    return [x.get("user_id") for x in s.get(B + f"/api/sheets/{sid}/shares").json().get("shares", [])]


def dlg_id(s, sid, who):
    """2.937.0 (#5244): the id of who's row in the table's dialog (= its core share's)."""
    return next((x["id"] for x in s.get(B + f"/api/sheets/{sid}/shares").json().get("shares", []) if x.get("user_id") == who), None)


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def wait_import(iid):
    j = {}
    for _ in range(960):  # until the import left its working states
        j = A.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


# ================================================================ organisation import: card and core share bound
# T1 / T2 in a folder of the tables' panel: their node and its core share come along with the store (the audit's case of two
# rights); T0 at the top of the tree: its node stays behind, the card gets a new core share in the target
T0 = table(A, "Loose", f"org:{ORG}")
T1 = table(A, "Rates", f"org:{ORG}")
T2 = table(A, "Costs", f"org:{ORG}")
r = A.post(B + "/api/sheets/folders", json={"space": f"org:{ORG}", "name": "Finance"})
check(r.status_code == 201, f"setup: a folder of the tables {r.status_code} {r.text[:120]}")
FOLD = r.json()["folder"]["id"]
for t in (T0, T1, T2):
    share(A, t, GINA)
for t in (T1, T2):
    check(A.post(B + "/api/files/refs", json={"ref_kind": "sheet", "ref_id": t, "parent_id": FOLD}).ok, f"setup: table {t} into the folder")
check(all(Gi.get(B + f"/api/sheets/{t}").status_code == 200 for t in (T0, T1, T2)), "setup: the guest reads all three")

r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"organisation export started {r.text[:120]}")
for _ in range(960):  # until the export is no longer running
    if A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")

r = A.post(B + "/api/account/import", json={"size": len(OX), "name": "alpha.kalmido-export"})
assert r.ok, r.text
IID, off = r.json()["id"], 0
while off < len(OX):
    part = OX[off:off + (1 << 20)]
    r = A.put(B + f"/api/account/import/{IID}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    off += len(part)
j = wait_import(IID)
check(j.get("state") == "key", f"the import asks for the recovery key {j.get('state')} {j.get('error')}")
check(A.post(B + f"/api/account/import/{IID}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
check(wait_import(IID).get("state") == "preview", "the archive is opened")
r = A.post(B + f"/api/account/import/{IID}/run", json={"again": True, "target": ORG3, "people": {EH("gina@example.com"): {"share": True}}})
check(r.status_code == 202, f"the import runs {r.status_code} {r.text[:160]}")
j = wait_import(IID)
check(j.get("state") == "done", f"imported into the empty organisation {j.get('state')} {j.get('error')}")

N0, N1, N2 = ((dbx("SELECT id FROM sheets WHERE org_id=? AND title=?", (ORG3, t)) or [[None]])[0][0] for t in ("Loose", "Rates", "Costs"))
check(N0 and N1 and N2, f"the tables came along {N0} {N1} {N2}")
for n in (N0, N1, N2):
    # 2.937.0 (#5244): was "one card, one core share, bound to each other" -- now the core share alone, the dialog shows it
    cards = dbx("SELECT id FROM sheet_shares WHERE sheet_id=?", (n,))
    cs = core(n, GINA)
    check(not cards and len(cs) == 1 and dlg_id(A, n, GINA) == cs[0],
          f"#5244: one core share, the table's dialog shows that row (no card) {[tuple(x) for x in cards]} {cs}")
    check(Gi.get(B + f"/api/sheets/{n}").status_code == 200 and listed(A, n) == [GINA], "the guest reads the imported table, the dialog lists her")

# ending it in the table's dialog ends the core share too
c1 = dlg_id(A, N1, GINA)
check(A.delete(B + f"/api/sheets/{N1}/shares/{c1}").ok, "ended in the table's dialog")
check(not core(N1, GINA), "#5047: ... the core share is gone too")
check(Gi.get(B + f"/api/sheets/{N1}").status_code == 404, "#5047: ... the guest reads nothing any more")

# ending it in the file store's dialog ends it in the table's dialog too
fs2 = (core(N2, GINA) or [0])[0]
check(A.delete(B + f"/api/files/shares/{fs2}").ok, "ended in the file store's dialog")
check(Gi.get(B + f"/api/sheets/{N2}").status_code == 404 and listed(A, N2) == [], "#5047: ... the guest reads nothing, the dialog is empty")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "the source organisation's share stays untouched")

# ================================================================ the undo of a move between workspaces
T3 = table(A, "Moved", f"org:{ORG}")
share(A, T3, GINA)
r = A.post(B + f"/api/sheets/{T3}/move-space", json={"to": "private"})
MID = r.json().get("move_id") if r.ok else None
check(MID and Gi.get(B + f"/api/sheets/{T3}").status_code == 404 and not core(T3, GINA), f"moved to Private: the share ends {r.text[:160]}")
r = A.post(B + f"/api/sheets/{T3}/move-space", json={"to": f"org:{ORG}", "undo": MID})
check(r.ok and r.json().get("shares_back") == 1, f"the undo names the share back {r.text[:160]}")
check(len(core(T3, GINA)) == 1, "#5047: the share back is a core share on the table's node again")  # 2.937.0 (#5244): no card
check(Gi.get(B + f"/api/sheets/{T3}").status_code == 200, "#5047: the guest reads the table again")
check(listed(A, T3) == [GINA], "#5047: the dialog lists her again")

# ================================================================ a person without organisation (freelancer-matrix: sheets)
# 2.937.0 (#5244): was "no fallback: a card without a core share" -- there are no cards any more: a share by name is the core share
FID, Fr = freelancer(B, A, "frida", features=FEAT)
FIO, Fi = freelancer(B, A, "fiona", features=FEAT)
dbx("UPDATE users SET email_proved=lower(email) WHERE id=?", (FIO,))  # 2.983.0 (#5643): a share by address binds only a proved address (a mailed link / OIDC); here set directly
P1 = table(Fr, "Own rates", "private")
dbx("INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,email_key) VALUES(?,NULL,?,'read',?,?,'')",
    (P1, FIO, FID, "2026-11-07T10:00:00.000+00:00"))  # an old person row (only an older database has them): gives nothing
check(Fi.get(B + f"/api/sheets/{P1}").status_code == 404 and listed(Fr, P1) == [], "#5244: an old person row gives nothing and is not listed")
dbx("DELETE FROM sheet_shares WHERE sheet_id=?", (P1,))
# two people without organisation see each other only by address (no shared list): the address is bound to her account at once
r = Fr.post(B + f"/api/sheets/{P1}/shares", json={"email": "fiona@example.com", "role": "read"})
cp = next((x["id"] for x in Fr.get(B + f"/api/sheets/{P1}/shares").json().get("shares", [])), None)
check(r.status_code == 201 and cp and cp < 0 and len(core(P1, FIO)) == 1 and Fi.get(B + f"/api/sheets/{P1}").status_code == 200,
      f"a share by address: bound, the core share, she reads it {r.text[:160]}")
check(any(x["id"] == P1 for x in Fi.get(B + "/api/sheets?space=shared").json().get("sheets", [])), "... in 'Shared with me'")
check(Fr.patch(B + f"/api/sheets/{P1}/shares/{cp}", json={"role": "write"}).ok and Fi.patch(B + f"/api/sheets/{P1}", json={"title": "Rates x"}).ok,
      "a change in the dialog changes the core share's role")
check(Fr.delete(B + f"/api/sheets/{P1}/shares/{cp}").ok and Fi.get(B + f"/api/sheets/{P1}").status_code == 404 and not core(P1, FIO),
      "ended: the core share goes")

sys.exit(kt.done("p2647_b_sheet_core"))
