#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.353.0 C (#2829): the organisation export carries the areas' trees of the file store -- the knowledge tree (empty
folders, the order by hand, folder shares, the page nodes, a file put there under 2.199) and the tables' root with its folder
and table reference -- and the import rebuilds them in the target. Invented names only.
 - an organisation with a knowledge folder that stays empty, a folder with two pages in a hand-made order, shared with a
   member, a file put into that folder the 2.199 way (database), a tables folder with a table in it
   -> exported -> imported into an empty organisation: one knowledge root (marked), the empty folder, the order, the share
   (ticked member), the file with its version, the tables' root (marked) with the folder and the table's node; opening the
   knowledge index (the path <-> tree check) changes nothing, no second root; undo removes the tree and the marks
 - into an organisation that already has a knowledge root and a folder of the same name: that root and that folder take the
   archive's (no second root, no second folder)
 - an export without the tree (a pre-2.353 archive: no knowledge nodes, no marks) still gives the pages, the tree is built
   from their paths as before
 - the organisation boundary: every row made lies in the target organisation, the source is untouched
 - freelancer-matrix: a person without an organisation imports the export into the private space: the tree in their own
   space (the export itself is an organisation's thing; the private space has no export of its own)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2353C_NOSTART=1 = the server already runs like that).
usage: p2353_c_orgexport_test.py <datadir>"""
# freelancer-matrix: wiki
# freelancer-matrix: sheets
# tenant-matrix: wiki
import base64
import hashlib
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
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = FEATURES + ",sheets"


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


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
    for _ in range(480):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    ox = s.get(B + f"/api/orgs/{oid}/export/file").content
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, "organisation export + recovery key")
    return ox, rk


def imp(s, ox, rk, target, people=None):
    iid = upload(s, ox)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {(j.get('result') or {}).get('warnings')}")
    return iid, (j.get("result") or {}).get("import_id")


def root_of(ws, area):
    r = one("SELECT node_id FROM fs_area_roots WHERE ws=? AND area=?", (ws, area))
    return r["node_id"] if r else None


def kids(pid):
    return {r["name"]: r for r in dbx("SELECT id, kind, name, sort_no, ref_kind, ref_id, org_id, owner_id FROM fs_nodes "
                                      "WHERE parent_id=? AND deleted_at IS NULL", (pid,))}


def wiki_new(s, space, path, body="Text"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    check(r.ok, f"a knowledge page {path} " + r.text[:160])
    return r.json().get("id") or (r.json().get("page") or {}).get("id")


def tops(oid, name):
    return dbx("SELECT id FROM fs_nodes WHERE org_id=? AND parent_id IS NULL AND name=? AND deleted_at IS NULL", (oid, name))


if not os.environ.get("P2353C_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Ablage", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Mitglied", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORGS = {}
for k, n in (("src", "Alpha Quelle"), ("gam", "Gamma Ziel"), ("del", "Delta Ziel"), ("alt", "Alt Quelle"), ("zed", "Zeta Ziel")):
    ORGS[k] = A.post(B + "/api/admin/orgs", json={"name": n, "admin_id": ALICE}).json()["id"]
    check(A.put(B + f"/api/orgs/{ORGS[k]}/members", json={"email": "bob@example.com", "role": "member"}).ok, f"bob in {n}")
ORG, GAM, DEL, ALT, ZED = (ORGS[k] for k in ("src", "gam", "del", "alt", "zed"))
SP = f"org:{ORG}"

# ---------------------------------------------------------------- the source: knowledge tree + tables folder
r = A.post(B + "/api/wiki/folders", json={"space": SP, "name": "Leer"})
check(r.status_code == 201, "an empty knowledge folder " + r.text[:160])
r = A.post(B + "/api/wiki/folders", json={"space": SP, "name": "Handbuch"})
check(r.status_code == 201, "a knowledge folder " + r.text[:160])
HB = r.json()["folder"]["id"]
P1, P2 = wiki_new(A, SP, "Handbuch/Eins", "Erste Seite"), wiki_new(A, SP, "Handbuch/Zwei", "Zweite Seite")
n1, n2 = (one("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (p,)) for p in (P1, P2))
check(n1 and n2, "the pages have their nodes")
r = A.post(B + f"/api/files/nodes/{n2['id'] if n2 else 0}/order", json={"before": n1["id"] if n1 else 0})
check(r.ok, "Zwei before Eins by hand " + r.text[:160])
check(A.post(B + f"/api/files/nodes/{HB}/shares", json={"user_id": BOB, "role": "edit"}).ok, "the knowledge folder shared with bob")
WROOT = root_of(f"o{ORG}", "wiki")
check(WROOT and kids(WROOT).get("Handbuch", {}).get("id") == HB, "the source has its knowledge root")
# a file put into the knowledge tree under 2.199 (after a rollback; 2.200 refuses it): made elsewhere, moved in the database
PLAIN = b"Notiz aus 2.199 " + os.urandom(6).hex().encode()
r = A.post(B + "/api/files/folders", json={"name": "Ablage", "space": SP})
check(r.status_code == 201, "a store folder " + r.text[:160])
r = A.post(B + "/api/files/upload", data={"parent_id": str(r.json()["id"])}, files={"file": ("notiz.txt", PLAIN, "text/plain")})
check(r.status_code == 201, "a file " + r.text[:160])
WF = r.json()["items"][0]["id"]
dbx("UPDATE fs_nodes SET parent_id=? WHERE id=?", (HB, WF))
r = A.post(B + "/api/sheets/folders", json={"space": SP, "name": "Kalkulationen"})
check(r.status_code == 201, "a tables folder " + r.text[:160])
SF = r.json()["folder"]["id"]
r = A.post(B + "/api/sheets", json={"title": "Budget", "space": SP, "folder_id": SF})
check(r.status_code == 201, "a table in the folder " + r.text[:160])
SID = r.json()["id"]
check(one("SELECT parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id=?", (SID,))["parent_id"] == SF, "the table lies in it")
SROOT = root_of(f"o{ORG}", "sheets")
src_n = dbx("SELECT COUNT(*) AS n FROM fs_nodes WHERE org_id=?", (ORG,))[0]["n"]
OX, RK = export(A, ORG)

# ---------------------------------------------------------------- into an empty organisation
iid, IMP = imp(A, OX, RK, GAM, people={EH("bob@example.com"): {"share": True}})
g_root = root_of(f"o{GAM}", "wiki")
check(g_root and one("SELECT parent_id, org_id, kind FROM fs_nodes WHERE id=?", (g_root,))["org_id"] == GAM,
      f"the knowledge root came along and is marked {g_root}")
gk = kids(g_root or 0)
check({"Leer", "Handbuch"} <= set(gk), f"the empty folder and the folder came along {sorted(gk)}")
check(not kids(gk.get("Leer", {}).get("id") or 0), "the empty folder is empty")
GHB = gk.get("Handbuch", {}).get("id") or 0
hk = kids(GHB)
gp1, gp2 = (one("SELECT id FROM wiki_pages WHERE org_id=? AND path=?", (GAM, p)) for p in ("Handbuch/Eins", "Handbuch/Zwei"))
check(gp1 and gp2, "the pages came along")
check(hk.get("Eins", {}).get("ref_id") == (gp1 or {}).get("id") and hk.get("Zwei", {}).get("ref_id") == (gp2 or {}).get("id"),
      f"the page nodes point at the new pages {[(k, v['ref_id']) for k, v in hk.items()]}")
check((hk.get("Zwei", {}).get("sort_no") or 0) < (hk.get("Eins", {}).get("sort_no") or 0), "the order by hand came along")
sh = {x["user_id"] for x in dbx("SELECT user_id FROM fs_shares WHERE node_id=?", (GHB,))}
check(sh == {BOB}, f"the folder share came along (ticked member) {sh}")
gf = hk.get("notiz.txt")
check(gf and gf["kind"] == "file", "the file put into the knowledge tree came along")
GF = gf["id"] if gf else 0
check(dbx("SELECT COUNT(*) AS n FROM fs_versions WHERE node_id=?", (GF,))[0]["n"] == 1, "with its version")
check(A.get(B + f"/api/files/nodes/{GF}/content").content == PLAIN, "the file is readable")
s_root = root_of(f"o{GAM}", "sheets")
sk = kids(s_root or 0)
GSF = sk.get("Kalkulationen", {}).get("id") or 0
gs = one("SELECT id FROM sheets WHERE org_id=? AND title='Budget'", (GAM,))
tn = kids(GSF)
check(s_root and GSF and gs and any(v["kind"] == "ref" and v["ref_kind"] == "sheet" and v["ref_id"] == gs["id"] for v in tn.values()),
      f"the tables root (marked), its folder and the table's node {s_root} {sorted(sk)} {list(tn)}")
fl = A.get(B + "/api/sheets/folders").json()
check(any(f.get("id") == GSF and f.get("space") == f"org:{GAM}" for f in fl.get("folders") or []), "the tables panel lists the folder")
check(len(tops(GAM, one("SELECT name FROM fs_nodes WHERE id=?", (g_root,))["name"])) == 1, "one knowledge root at the top")
r = A.get(B + "/api/wiki", params={"space": f"org:{GAM}"})  # the path <-> tree check of the space
check(r.ok, "the knowledge index opens " + r.text[:120])
check(root_of(f"o{GAM}", "wiki") == g_root and kids(GHB).keys() == hk.keys(), "the index changes nothing: no second root, same tree")
check(len(dbx("SELECT id FROM fs_nodes WHERE org_id=? AND kind='ref' AND ref_kind='wiki'", (GAM,))) == 2, "one node per page")
# the organisation boundary: everything made lies in the target, the source is untouched
made = dbx("SELECT k.id, k.org_id FROM fs_nodes k JOIN fs_nodes p ON p.id=k.parent_id WHERE p.org_id=? AND COALESCE(k.org_id, 0)<>?",
           (GAM, GAM))
check(not made and one("SELECT org_id FROM fs_area_roots WHERE ws=? AND area='wiki'", (f"o{GAM}",))["org_id"] == GAM,
      f"only rows of the target organisation {made}")
check(dbx("SELECT COUNT(*) AS n FROM fs_nodes WHERE org_id=?", (ORG,))[0]["n"] == src_n and root_of(f"o{ORG}", "wiki") == WROOT
      and root_of(f"o{ORG}", "sheets") == SROOT, "the source's tree is untouched")
r = A.post(B + f"/api/imports/{IMP}/undo")
check(r.ok, "undo " + r.text[:160])
check(not dbx("SELECT 1 FROM fs_nodes WHERE org_id=?", (GAM,)) and not dbx("SELECT 1 FROM fs_area_roots WHERE ws=?", (f"o{GAM}",)),
      "undo removes the tree and the marks")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- into an organisation with its own knowledge root
r = A.post(B + "/api/wiki/folders", json={"space": f"org:{DEL}", "name": "Handbuch"})
check(r.status_code == 201, "the target's own knowledge folder " + r.text[:160])
DHB, DROOT = r.json()["folder"]["id"], root_of(f"o{DEL}", "wiki")
iid, _ = imp(A, OX, RK, DEL)
check(root_of(f"o{DEL}", "wiki") == DROOT, "the target's knowledge root stays the root")
dk = kids(DROOT)
check(len(tops(DEL, one("SELECT name FROM fs_nodes WHERE id=?", (DROOT,))["name"])) == 1, "no second knowledge root")
check(dk.get("Handbuch", {}).get("id") == DHB and "Leer" in dk, f"the folder of the same name takes the archive's {sorted(dk)}")
check({"Eins", "Zwei"} <= set(kids(DHB)), "the pages lie in the target's folder")
r = A.get(B + "/api/wiki", params={"space": f"org:{DEL}"})
check(r.ok and root_of(f"o{DEL}", "wiki") == DROOT and {"Eins", "Zwei"} <= set(kids(DHB)), "the index keeps it so")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- an export without the tree (as before 2.353)
wiki_new(A, f"org:{ALT}", "Alt/Seite", "Alte Seite")
ar = root_of(f"o{ALT}", "wiki")
dbx("DELETE FROM fs_area_roots WHERE ws=?", (f"o{ALT}",))
dbx("DELETE FROM fs_nodes WHERE id=?", (ar,))  # the tree goes with its root (cascade): the archive has no knowledge nodes
OX2, RK2 = export(A, ALT)
iid, _ = imp(A, OX2, RK2, ZED)
zp = one("SELECT id FROM wiki_pages WHERE org_id=? AND path='Alt/Seite'", (ZED,))
check(zp, "an export without the tree: the page came along")
r = A.get(B + "/api/wiki", params={"space": f"org:{ZED}"})
zr = root_of(f"o{ZED}", "wiki")
zn = one("SELECT parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", ((zp or {}).get("id") or 0,))
check(r.ok and zr and zn and kids(zr).get("Alt", {}).get("id") == zn["parent_id"], "the tree is built from the page's path as before")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- freelancer-matrix: into the private space
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
iid, FIMP = imp(Fr, OX, RK, "private")
fr = root_of(f"u{FID}", "wiki")
fk = kids(fr or 0)
check(fr and {"Leer", "Handbuch"} <= set(fk), f"freelancer: the knowledge tree in the private space {sorted(fk)}")
check(all(v["org_id"] is None and v["owner_id"] == FID for v in fk.values()), "freelancer: their own nodes")
fp = one("SELECT id FROM wiki_pages WHERE owner_id=? AND org_id IS NULL AND path='Handbuch/Zwei'", (FID,))
fh = kids(fk.get("Handbuch", {}).get("id") or 0)
check(fp and fh.get("Zwei", {}).get("ref_id") == fp["id"], "freelancer: the page node points at the private page")
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=?", (fk.get("Handbuch", {}).get("id") or 0,)), "freelancer: shared with nobody")
fsr = root_of(f"u{FID}", "sheets")
check(fsr and "Kalkulationen" in kids(fsr), "freelancer: the tables root and folder")
r = Fr.get(B + "/api/wiki", params={"space": "private"})
check(r.ok and root_of(f"u{FID}", "wiki") == fr, "freelancer: the index keeps the root")
check(Bo.get(B + f"/api/files/nodes/{fk.get('Handbuch', {}).get('id') or 0}").status_code in (403, 404), "bob does not see it")
r = Fr.post(B + f"/api/imports/{FIMP}/undo")
check(r.ok and not dbx("SELECT 1 FROM fs_nodes WHERE owner_id=?", (FID,)) and not dbx("SELECT 1 FROM fs_area_roots WHERE ws=?", (f"u{FID}",)),
      "freelancer: undo removes it again")

if FAILS:
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "80", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-8000:], flush=True)
print(f"p2353_c_orgexport: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
