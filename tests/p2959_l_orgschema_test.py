#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.959.0 (#4031): the organisation export carries the organisation's own ticket types and its field schema, and the import
rebuilds them with new ids and the links of the projects (the labels: org/labels.json since 2.947.0, #5275). Invented names only.
 - an organisation with an own ticket type (incident), a schema field (client, select) switched on in a project, a task of the
   own type with a value; another organisation of the same admin with its own type / field
   -> exported -> imported into an empty organisation: the type and the field are there with new ids in the target, the
   project's field points at the target's schema field (the app lists it with its project), the task keeps its value and its
   type (the project offers it); nothing of the other organisation came along
 - into an organisation that already has a field with the key but another type: no second one, the project field stays
   unlinked (the existing field stays as it was)
 - undo of the first import: the type and the field go again; the undo of the second leaves the existing field
 - freelancer-matrix: a person without an organisation imports the export into the private workspace: the type and the field as
   their own (org_id NULL, owner_id them), the project field linked to their own field
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2959L_NOSTART=1 = the server already runs like that).
usage: p2959_l_orgschema_test.py <datadir>"""
# freelancer-matrix: tasks
# tenant-matrix: own
import base64
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess, su_get  # noqa: E402
FEAT = FEATURES + ",fields,collab"


def dbx(sql, args=()):
    return [dict(zip(r.keys(), r)) for r in dbxm.connect(DATA).execute(sql, args).fetchall()]


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0] if r else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "alpha.kalmido-export"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, "organisation export started " + r.text[:120])
    st = {}
    for _ in range(480):
        st = s.get(B + f"/api/orgs/{oid}/export").json()
        if st.get("state") != "running":
            break
        time.sleep(0.25)
    check(st.get("state") == "done", f"organisation export done {st}")
    ox = su_get(s, B + f"/api/orgs/{oid}/export/file", "password123").content
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, "organisation export + recovery key")
    return ox, rk


def imp(s, ox, rk, target):
    iid = upload(s, ox)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    res = j.get("result") or {}
    check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {res.get('warnings')}")
    return iid, res.get("import_id")


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "tickets": True, **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def schema(s, oid, name, field, ttype):
    """An own ticket type and a schema field (select) of organisation oid."""
    r = s.post(B + "/api/ticket-types", json={"space": f"org:{oid}", "name": ttype, "icon": "zap", "color": "#aa3300",
                                              "template": "**Impact**\n"})
    check(r.ok, f"{name}: an own ticket type {r.text[:160]}")
    r = s.post(B + "/api/org-fields", json={"space": f"org:{oid}", "name": field, "type": "select",
                                            "options": {"options": [{"id": "acme", "name": "Acme"}, {"id": "init", "name": "Initech"}]}})
    check(r.ok, f"{name}: a schema field {r.text[:160]}")
    return r.json()["id"]


def project_of(oid, name):
    r = one("SELECT id FROM lists WHERE org_id=? AND name=? AND deleted_at IS NULL", (oid, name))
    return r["id"] if r else 0


def own_lists_of(uid, name):
    r = one("SELECT id FROM lists WHERE owner_id=? AND org_id IS NULL AND name=? AND deleted_at IS NULL", (uid, name))
    return r["id"] if r else 0


if not os.environ.get("P2959L_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Ablage", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORGS = {}
for k, n in (("src", "Alpha Quelle"), ("oth", "Omega Fremd"), ("gam", "Gamma Ziel"), ("del", "Delta Ziel"), ("eps", "Epsilon Ziel")):
    ORGS[k] = A.post(B + "/api/admin/orgs", json={"name": n, "admin_id": ALICE}).json()["id"]
SRC, OTH, GAM, DEL, EPS = (ORGS[k] for k in ("src", "oth", "gam", "del", "eps"))

# ---------------------------------------------------------------- the source and another organisation
OF = schema(A, SRC, "source", "Client", "Incident")
schema(A, OTH, "other", "Spyfield", "Spytype")
L1 = mklist(A, "Support", SRC)
r = A.put(B + f"/api/lists/{L1}/org-fields/{OF}", json={"on": True})
F1 = r.json().get("field_id")
check(r.ok and F1, f"the schema field switched on in the project {r.text[:160]}")
r = A.post(B + "/api/tasks", json={"title": "Printer jams", "list_id": L1, "ttype": "incident", "fields": {str(F1): "init"}})
check(r.ok and r.json().get("ttype") == "incident", f"a task of the own type with a value {r.text[:200]}")
T1 = r.json()["id"]
src_before = {t: one(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (SRC,))["n"] for t in ("ticket_types", "org_fields")}
OX, RK = export(A, SRC)

# ---------------------------------------------------------------- into an empty organisation
iid, IMP = imp(A, OX, RK, GAM)
gt = dbx("SELECT * FROM ticket_types WHERE org_id=?", (GAM,))
check([(x["key"], x["name"], x["icon"], x["color"], x["tpl"], x["enabled"]) for x in gt] == [("incident", "Incident", "zap", "#aa3300", "**Impact**\n", 1)],
      f"the own ticket type came along {[(x['key'], x['name']) for x in gt]}")
check(all(x["owner_id"] is None for x in gt), "the type belongs to the organisation, not to a person")
gf = dbx("SELECT * FROM org_fields WHERE org_id=?", (GAM,))
check(len(gf) == 1 and gf[0]["key"] == "client" and gf[0]["type"] == "select" and gf[0]["id"] != OF and "Initech" in gf[0]["options"],
      f"the schema field came along with a new id {[(x['id'], x['key']) for x in gf]}")
GL1 = project_of(GAM, "Support")
check(GL1 and GL1 != L1, "the project came along")
gfld = one("SELECT id, org_field_id, name FROM list_fields WHERE list_id=?", (GL1,))
check(gfld and gf and gfld["org_field_id"] == gf[0]["id"], f"the project field is linked to the target's schema field {gfld}")
gtask = one("SELECT id, ttype FROM tasks WHERE list_id=? AND title='Printer jams'", (GL1,))
check(gtask and gtask["ttype"] == "incident", f"the task keeps its own type {gtask}")
check(gtask and gfld and one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (gtask["id"], gfld["id"])) is not None,
      "the task keeps its value in the linked field")
# what a person sees in the app: the target's field lists its project, the project offers the type, the task shows its type
r = A.get(B + "/api/org-fields")
mine = [x for x in r.json().get("fields", []) if x.get("org_id") == GAM]
check(r.ok and len(mine) == 1 and mine[0]["key"] == "client" and mine[0].get("lists") == 1,
      f"the app lists the target's field with its project {mine}")
r = A.get(B + f"/api/lists/{GL1}/ticket-types")
check(r.ok and "incident" in r.text, f"the imported project offers the own type {r.text[:200]}")
r = A.get(B + f"/api/lists/{GL1}/org-fields")
check(r.ok and any(x.get("field_id") == (gfld or {}).get("id") for x in r.json().get("fields", [])),
      f"the project shows the schema field switched on {r.text[:200]}")
st = A.get(B + "/api/state").json()
tk = next((t for t in st.get("tasks", []) if t["id"] == (gtask or {}).get("id")), {})
check(tk.get("ttype") == "incident", f"the task in the app: its type {tk.get('ttype')}")
# the boundary: nothing of the other organisation, the source untouched
for t, col, v in (("ticket_types", "key", "spytype"), ("org_fields", "key", "spyfield")):
    check(not dbx(f"SELECT 1 AS x FROM {t} WHERE org_id=? AND {col}=?", (GAM, v)), f"nothing of the other organisation: {t}")
check({t: one(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (SRC,))["n"] for t in src_before} == src_before, "the source is untouched")
check(one("SELECT org_field_id FROM list_fields WHERE id=?", (F1,))["org_field_id"] == OF, "the source's project keeps its link")

# ---------------------------------------------------------------- into an organisation that has a field with the key already
r = A.post(B + "/api/org-fields", json={"space": f"org:{DEL}", "name": "Kunde", "type": "text", "key": "client"})
check(r.ok, f"the target has a field with the key {r.text[:160]}")
DOF = r.json()["id"]
iid2, IMP2 = imp(A, OX, RK, DEL)
check([x["id"] for x in dbx("SELECT id FROM org_fields WHERE org_id=?", (DEL,))] == [DOF], "no second field with the key")
dfo = one("SELECT name, type FROM org_fields WHERE id=?", (DOF,))
check(dfo["name"] == "Kunde" and dfo["type"] == "text", "the existing field stays as it was")
DL1 = project_of(DEL, "Support")
# 2.959.0 (#4031): the archive's field is a select, the target's of the same key a text field: linking it would let the
# target's field rewrite the project field (options gone), so the project field stays unlinked
check(one("SELECT org_field_id FROM list_fields WHERE list_id=?", (DL1,))["org_field_id"] is None,
      "another type under the same key: the project field stays unlinked")
check([x["key"] for x in dbx("SELECT key FROM ticket_types WHERE org_id=?", (DEL,))] == ["incident"], "the type came along")

# 2.976.0 (#5657, review 2.959 F7): a select field with the key and the same option ids, but one option under another name:
# linking would let the target's field rename the project's values, so the project field stays unlinked (red before: linked)
r = A.post(B + "/api/org-fields", json={"space": f"org:{EPS}", "name": "Kunde", "type": "select", "key": "client",
                                        "options": {"options": [{"id": "acme", "name": "Acme"}, {"id": "init", "name": "Umbrella"}]}})
check(r.ok, f"the target has a select field with the key, an option renamed {r.text[:160]}")
EOF_ID = r.json().get("id")
iid4, IMP4 = imp(A, OX, RK, EPS)
check([x["id"] for x in dbx("SELECT id FROM org_fields WHERE org_id=?", (EPS,))] == [EOF_ID], "no second field with the key (select)")
EL1 = project_of(EPS, "Support")
check(EL1 and one("SELECT org_field_id FROM list_fields WHERE list_id=?", (EL1,))["org_field_id"] is None,
      "the same option ids under another name: the project field stays unlinked")
check(one("SELECT options FROM org_fields WHERE id=?", (EOF_ID,))["options"].count("Umbrella") == 1, "the target's field keeps its names")
A.post(B + f"/api/imports/{IMP4}/undo")
A.delete(B + f"/api/account/import/{iid4}")

# ---------------------------------------------------------------- undo
r = A.post(B + f"/api/imports/{IMP}/undo")
check(r.ok, "undo of the first import " + r.text[:160])
for t in ("ticket_types", "org_fields"):
    check(not dbx(f"SELECT 1 AS x FROM {t} WHERE org_id=?", (GAM,)), f"undo takes {t} out again")
r = A.post(B + f"/api/imports/{IMP2}/undo")
check(r.ok, "undo of the second import " + r.text[:160])
check(one("SELECT id FROM org_fields WHERE id=?", (DOF,)), "the undo leaves the target's own field")
check(not dbx("SELECT 1 AS x FROM ticket_types WHERE org_id=?", (DEL,)), "the undo takes the imported type out")
A.delete(B + f"/api/account/import/{iid}")
A.delete(B + f"/api/account/import/{iid2}")

# ---------------------------------------------------------------- freelancer-matrix: into the private workspace
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
iid3, FIMP = imp(Fr, OX, RK, "private")
ft = dbx("SELECT key, org_id, owner_id FROM ticket_types WHERE owner_id=?", (FID,))
check([(x["key"], x["org_id"]) for x in ft] == [("incident", None)], f"freelancer: the type as their own {ft}")
ff = dbx("SELECT id, key, org_id FROM org_fields WHERE owner_id=?", (FID,))
check([(x["key"], x["org_id"]) for x in ff] == [("client", None)], f"freelancer: the field as their own {ff}")
FL1 = own_lists_of(FID, "Support")
check(FL1 and ff and one("SELECT org_field_id FROM list_fields WHERE list_id=?", (FL1,))["org_field_id"] == ff[0]["id"],
      "freelancer: the project field linked to their own field")
r = Fr.get(B + "/api/ticket-types", params={"space": "private"})
check(r.ok and [x["key"] for x in r.json().get("types", [])] == ["incident"], f"freelancer: the app lists the own type {r.text[:200]}")
r = Fr.get(B + "/api/org-fields")
check(r.ok and [x["key"] for x in r.json().get("fields", [])] == ["client"], f"freelancer: the app lists the own field {r.text[:200]}")
check(not dbx("SELECT 1 AS x FROM org_fields WHERE owner_id=? AND key='spyfield'", (FID,)), "freelancer: nothing of the other organisation")
r = Fr.post(B + f"/api/imports/{FIMP}/undo")
check(r.ok and not dbx("SELECT 1 AS x FROM ticket_types WHERE owner_id=?", (FID,)) and not dbx("SELECT 1 AS x FROM org_fields WHERE owner_id=?", (FID,)),
      "freelancer: undo takes them out again")

if FAILS:
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "80", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-8000:], flush=True)
print(f"p2959_l_orgschema: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
