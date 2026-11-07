#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.635.0 D API tests (#4856): document flows ("Abläufe") are edited (PATCH with expect_updated_at, 409 when changed in the
meantime) and get the action "share" through the shared core (docs/flows.py _share -> core/objects.py obj_node_share); the
Paperless-ngx import maps a workflow's owner / permissions onto it (paperless/learn.py). Invented names only.
 - edit: the settings give each flow its version (updated_at); PATCH with it saves, the same old version again -> 409 with the
   flows under "rules"; without a version (old clients) it saves as before
 - share, saved: only people / groups of the workspace the saving person may share with (a stranger, a person of another
   organisation -> 400); frida (no organisation) cannot name bob
 - share, run: carol's new document matching bob's flow is shared with erin (view): erin reads it, cannot change it; a document
   the flow does not match stays hidden from erin; the run lists shared = 1, its undo takes the share back (into obj_revoked)
 - share, checked again on the run: erin out of the organisation -> the next matching document is not shared with her
 - Paperless: an assignment action with "view users" + owner becomes a flow with the action share for the people found by user
   name (share_by = the importing person); an owner not found is reported ("owner")
freelancer-matrix: docs
tenant-matrix: document
usage: p2635_d_flows_test.py <datadir>      (a fresh container; P2635D_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx, sess, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

kt.fresh(prefix="P2635D")
A = kt.setup()


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, name, lines, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(lines), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), 90)


def runs(s, nid):
    r = s.get(B + f"/api/docs/{nid}/flowruns")
    return r.json()["runs"] if r.ok else None


def flow(s, ws, **kw):
    return s.post(B + "/api/docs/rules", json={"ws": ws, **kw})


def rules(s, ws):
    return s.get(B + f"/api/docs/settings?ws={ws}").json()["rules"]


def py(code):
    p = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return p.stdout.strip(), p.stderr[-800:]


# ---- setup: frida without an organisation; Alpha = bob (admin) + carol + erin; gina a stranger, Beta = hugo
FR, Fr = freelancer(B, A, "frida")
ids = {}
for u in ("bob", "carol", "erin", "gina", "hugo"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
OWS = f"org:{ORG}"
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["hugo"]})
assert r.status_code == 201, r.text
Bo = sess("bob")
for u in ("carol", "erin"):
    check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG), f"setup: {u} joins Alpha")
Ca, Er, Gi = sess("carol"), sess("erin"), sess("gina")
for s in (Bo, Ca, Er, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

# ---- edit with the version (frida: a person without an organisation)
r = flow(Fr, "private", name="Strom", kind="any", match="Stadtwerke", type="Abschlag")
check(r.status_code == 201, f"frida: a flow saved {r.status_code} {r.text[:200]}")
FID = r.json()["id"]
f0 = [x for x in rules(Fr, "private") if x["id"] == FID][0]
check(f0.get("updated_at"), f"edit: the settings give the flow its version {f0}")
r = Fr.patch(B + f"/api/docs/rules/{FID}", json={**f0, "id": None, "name": "Strom neu", "type": "Strom", "expect_updated_at": f0["updated_at"]})
check(r.ok and any(x["id"] == FID and x.get("name") == "Strom neu" and x.get("type") == "Strom" for x in r.json()["rules"]),
      f"edit: PATCH with the version saves {r.status_code} {r.text[:200]}")
f1 = [x for x in r.json()["rules"] if x["id"] == FID][0] if r.ok else {}
check(f1.get("updated_at") and f1["updated_at"] != f0["updated_at"], f"edit: the version moved {f0.get('updated_at')} -> {f1.get('updated_at')}")
r = Fr.patch(B + f"/api/docs/rules/{FID}", json={**f0, "id": None, "name": "Strom alt", "expect_updated_at": f0["updated_at"]})
check(r.status_code == 409 and isinstance(r.json().get("rules"), list) and r.json().get("error"),
      f"edit: the old version again -> 409 with the flows {r.status_code} {r.text[:200]}")
check([x for x in rules(Fr, "private") if x["id"] == FID][0].get("name") == "Strom neu", "edit: the 409 changed nothing")
r = Fr.patch(B + f"/api/docs/rules/{FID}", json={"name": "Strom ohne Version", "kind": "any", "match": "Stadtwerke", "type": "Strom"})
check(r.ok, f"edit: without a version (old clients) it saves as before {r.status_code} {r.text[:200]}")
check(flow(Fr, "private", kind="any", match="x", share=[{"user_id": ids["bob"], "role": "view"}]).status_code == 400,
      "share: frida (no organisation) cannot name bob")
check(flow(Fr, "private", kind="any", match="x", share=[{"user_id": ids["bob"], "role": "owner"}]).status_code == 400, "share: role owner refused")

# ---- share: saved only with targets of the workspace
check(flow(Bo, OWS, kind="any", match="x", share=[{"user_id": ids["gina"], "role": "view"}]).status_code == 400, "share: a stranger refused")
check(flow(Bo, OWS, kind="any", match="x", share=[{"user_id": ids["hugo"], "role": "view"}]).status_code == 400, "share: a person of another organisation refused")
check(flow(Ca, OWS, kind="any", match="x", share=[{"user_id": ids["erin"], "role": "view"}]).status_code in (403, 404), "share: a member who is no admin makes no flow")
r = flow(Bo, OWS, name="Vertrag teilen", kind="any", match="Mietvertrag", share=[{"user_id": ids["erin"], "role": "view"}])
check(r.status_code == 201, f"share: a flow of the organisation with erin {r.status_code} {r.text[:200]}")
SF = r.json()["id"] if r.ok else 0
sf = [x for x in rules(Bo, OWS) if x["id"] == SF]
check(sf and sf[0].get("share") == [{"user_id": ids["erin"], "role": "view"}], f"share: stored as given {sf}")
check(any(x.get("key") == "user_id" and x.get("id") == ids["erin"] for x in Bo.get(B + f"/api/docs/settings?ws={OWS}").json().get("share_to") or []),
      "share: the form gets the pool (share_to)")

# ---- share: the run
o1 = upload(Ca, "mietvertrag.pdf", ["Mietvertrag Wohnung", "Seite 1"], ws=OWS)
o2 = upload(Ca, "notiz.pdf", ["Einkaufsliste", "Seite 1"], ws=OWS)
done(Ca, o1)
done(Ca, o2)
rr = until(lambda: [x for x in runs(Bo, o1) or [] if x.get("shared")], 30)
check(rr and rr[0]["shared"] == 1, f"run: the flow shared the document once {rr}")
check(doc(Er, o1) is not None, "run: erin reads the shared document")
check(Er.patch(B + f"/api/docs/{o1}", json={"tags": ["x"]}).status_code in (403, 404), "run: erin (view) cannot change it")
check(doc(Er, o2) is None, "run: the document the flow does not match stays hidden from erin")
check(len(dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (o1, ids["erin"]))) == 1, "run: one share row of the core (fs_shares)")
r = Bo.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo") if rr else None
check(r is not None and r.ok, f"undo: the admin takes the run back {r is not None and r.status_code}")
check(doc(Er, o1) is None and not dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (o1, ids["erin"])),
      "undo: the share is gone, erin does not see the document any more")
check(dbx("SELECT id FROM obj_revoked WHERE src='fs_shares' AND reason='flow-undo'"), "undo: the share went into obj_revoked (restorable)")

# ---- share: checked again on the run (erin out of the organisation)
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{ids['erin']}").ok, "setup: erin leaves Alpha")
o3 = upload(Ca, "mietvertrag2.pdf", ["Mietvertrag Garage", "Seite 1"], ws=OWS)
done(Ca, o3)
check(until(lambda: runs(Bo, o3) is not None, 10) is not None and not dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (o3, ids["erin"])),
      "run: a person who left is not given a share any more")

# ---- Paperless: owner / view users -> the action share (by user name), share_by = who imports
CODE = f"""
import json
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.docs import store as S
from kalmido.paperless import learn as L
c = connect()
with system_ctx(c):
    wf = L.pll_wf_export([(7, {{"name": "Rechte", "enabled": True, "triggers": [1], "actions": [2]}}),
                          (8, {{"name": "Nur Besitzer", "enabled": True, "triggers": [3], "actions": [4]}})],
                         {{1: {{"type": 1, "filter_filename": "*rechte*"}}, 3: {{"type": 1, "filter_filename": "*besitz*"}}}},
                         {{2: {{"type": 1, "assign_view_users": [11], "assign_change_users": [13]}}, 4: {{"type": 1, "assign_owner": 12}}}})
    labels = {{"workflows": wf, "_people": {{"users": {{"11": "Carol", "12": "nobody", "13": "gina"}}, "groups": {{}}}}}}
    res = L.pll_finish(c, "o{ORG}", {ORG}, {ids['bob']}, "test-src", "2099-01-01", labels, {{}})
    c.commit()
    fl = [r for r in S.rules_get(c, "o{ORG}") if r.get("name") in ("Rechte", "Nur Besitzer")]
    print(json.dumps({{"res": res, "flows": fl}}))
"""
out, errs = py(CODE)
try:
    j = json.loads(out.splitlines()[-1])
except (ValueError, IndexError):
    j = {}
check(j, f"paperless: the learning ran {out[-300:]} {errs}")
pf = {x["name"]: x for x in j.get("flows") or []}
check(pf.get("Rechte", {}).get("share") == [{"user_id": ids["carol"], "role": "view"}] and pf["Rechte"].get("share_by") == ids["bob"],
      f"paperless: view user carol (by user name) -> share view, share_by = bob; gina (not in Alpha) left out {pf.get('Rechte')}")
check("Nur Besitzer" not in pf, f"paperless: an owner not found gives no flow without actions {list(pf)}")
why = {(x["name"], x["why"]) for x in (j.get("res") or {}).get("unsupported") or []}
check(("Rechte", "owner") in why and ("Nur Besitzer", "owner") in why, f"paperless: what was not found is reported as owner {why}")

# ---- 2.635.0 E (#4856): a group as the share target (own group allowed, a foreign group 400, the run shares through the core)
# (the admin cannot put organisation members into a group, so the admin alice makes the group and is the flow's author)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
g1 = A.post(B + "/api/admin/groups", json={"name": "Crew Eins"})
GOWN = g1.json().get("id")
check(GOWN, f"group: the group made {g1.status_code} {g1.text[:150]}")
check(flow(Fr, "private", kind="any", match="x", share=[{"group_id": GOWN, "role": "view"}]).status_code == 400, "group: frida (not in it) cannot name a foreign group")
r = flow(A, "private", name="Gruppe teilen", kind="any", match="Gruppenvertrag", share=[{"group_id": GOWN, "role": "view"}])
check(r.status_code == 201, f"group: a flow with the own group saved {r.status_code} {r.text[:200]}")
gp = upload(A, "gruppenvertrag.pdf", ["Gruppenvertrag Nummer 1", "Seite 1"])
done(A, gp)
rg = until(lambda: [x for x in runs(A, gp) or [] if x.get("shared")], 30)
check(rg and rg[0]["shared"] == 1, f"group: the run shared the document once {rg}")
check(len(dbx("SELECT id FROM fs_shares WHERE node_id=? AND group_id=?", (gp, GOWN))) == 1, "group: one share row of the core for the group")

# ---- 2.635.0 E (#4856): on / off sends the flow's version -- an old version -> 409, nothing changed
r = flow(Fr, "private", name="Umschalten", kind="any", match="Umschalt", type="U")
TID = r.json()["id"]
t0 = [x for x in rules(Fr, "private") if x["id"] == TID][0]
r = Fr.patch(B + f"/api/docs/rules/{TID}", json={**t0, "id": None, "off": True, "expect_updated_at": t0["updated_at"]})
check(r.ok and [x for x in r.json()["rules"] if x["id"] == TID][0].get("off"), f"toggle: off with the current version {r.status_code}")
r = Fr.patch(B + f"/api/docs/rules/{TID}", json={**t0, "id": None, "off": True, "name": "Anders", "expect_updated_at": t0["updated_at"]})
check(r.status_code == 409 and isinstance(r.json().get("rules"), list), f"toggle: a stale version -> 409 {r.status_code} {r.text[:150]}")
check([x for x in rules(Fr, "private") if x["id"] == TID][0].get("name") == "Umschalten", "toggle: the 409 changed nothing")

sys.exit(kt.done("p2635_d_flows"))
