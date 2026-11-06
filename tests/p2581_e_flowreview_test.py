#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.581.0 E (#4803 review): the four findings of the review of the document flows ("Abläufe", kalmido/docs/flows.py).
Invented names only, generated PDFs with a text layer.
 - export: an organisation's flow with a webhook goes into the organisation export without its secret and without the
   webhook address (admin/orgexport.py _ox_dec_row); the flow itself (name, task) is in the archive
 - import: the person of a flow's task is an id of the source server: a person ticked in the import keeps the task, one not
   ticked is taken out (the task goes to the flow's author) (admin/oi_store.py _rule)
 - undo: a person who may edit the document but not the folder it came from takes a run back: the folder part stays, the
   rest goes back (flows.py _undo_vals); an admin, who may edit the folder, gets it moved back
 - scheduled: an old flow (saved long ago) turned into a scheduled one counts from the day of that change, not over the whole
   archive (flows.py fl_clean "since", fl_tick)
freelancer-matrix: files
tenant-matrix: document
usage: p2581_e_flowreview_test.py <datadir>      (a fresh container; P2581E_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, sess, su_get, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_DOCFLOW_TICK_S": "1", "KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY,
              "KALMIDO_ORGCRYPT_DELAY": "0"}, prefix="P2581E")
A = kt.setup()
_spec = importlib.util.spec_from_file_location("kx", os.path.join(N, "..", "tools", "kalmido_export_decrypt.py"))
KX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KX)


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


def tags(d):
    return sorted(t["name"] for t in (d or {}).get("tags") or [])


def flow(s, ws, **kw):
    return s.post(B + "/api/docs/rules", json={"ws": ws, **kw})


def rules(s, ws):
    return {x.get("name"): x for x in s.get(B + "/api/docs/settings", params={"ws": ws}).json()["rules"]}


def parent(nid):
    return dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (nid,))[0][0]


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def wait_imp(s, iid):
    return until(lambda: (lambda j: j if j.get("state") not in ("checking", "running", "upload") else None)(
        s.get(B + f"/api/account/import/{iid}").json()), 240) or {}


# ---- setup: frida without an organisation, gina; Alpha (alice admin) with bob + carol; Beta (empty) as the import's target
FR, Fr = freelancer(B, A, "frida")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ids = {}
for u in ("bob", "carol", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta Ziel", "admin_id": ALICE}).json()["id"]
OWS = f"org:{ORG}"
for u in ("bob", "carol"):
    check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok and org_join(B, u, ORG), f"setup: {u} in Alpha")
check(A.put(B + f"/api/orgs/{BETA}/members", json={"email": "bob@example.com", "role": "member"}).ok and org_join(B, "bob", BETA),
      "setup: bob in Beta (the import maps only members of the target)")
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

# ---- 1 + 2: organisation export without the webhook secret; import maps the task's person
r = flow(A, OWS, name="Hook", kind="any", match="Gutachten", webhook="https://hooks.example.com/geheimpfad-4803",
         task={"title": "Pruefen", "to": ids["carol"]})
check(r.status_code == 201 and r.json().get("hook_secret"), f"setup: a flow with a webhook and a task for carol {r.status_code} {r.text[:200]}")
SECRET = (r.json() if r.ok else {}).get("hook_secret") or "none-given"
r = flow(A, OWS, name="FuerBob", kind="any", match="Angebot", task={"title": "Ansehen", "to": ids["bob"]})
check(r.status_code == 201, f"setup: a flow with a task for bob {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"export started {r.status_code} {r.text[:200]}")
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 240)
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "the export and its recovery key")
with tempfile.TemporaryDirectory() as tmp:
    src, dst = os.path.join(tmp, "a.kalmido-export"), os.path.join(tmp, "a.zip")
    with open(src, "wb") as f:
        f.write(OX)
    KX.decrypt(src, dst, KX.parse_key(RK))
    with open(dst, "rb") as f:
        ZF = zipfile.ZipFile(io.BytesIO(f.read()))
raw = ZF.read("documents/rules.json")
every = b"".join(ZF.read(n) for n in ZF.namelist() if not n.startswith("files/"))
check(SECRET.encode() not in every, "export: the flow's webhook secret is nowhere in the archive")
check(b"geheimpfad-4803" not in raw, "export: the webhook address stays out (a key itself for many services, like the webhooks table)")
fl = [json.loads(x["data"]) if isinstance(x.get("data"), str) else (x.get("data") or {}) for x in json.loads(raw)]
hook = [x for x in fl if x.get("name") == "Hook"]
check(hook and hook[0].get("task", {}).get("title") == "Pruefen" and "hook_secret" not in hook[0] and "webhook" not in hook[0],
      f"export: the flow itself is in the archive, without secret and address {hook}")

iid = A.post(B + "/api/account/import", json={"size": len(OX), "name": "alpha.kalmido-export"}).json()["id"]
check(A.put(B + f"/api/account/import/{iid}?offset=0", data=OX, headers={"Content-Type": "application/octet-stream"}).ok, "import: the archive uploaded")
check(wait_imp(A, iid).get("state") == "key", "import: asks for the recovery key")
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "import: the key is taken")
check(wait_imp(A, iid).get("state") == "preview", "import: preview")
r = A.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": BETA, "people": {EH("bob@example.com"): {"share": True}}})
check(r.status_code == 202, f"import: run starts {r.status_code} {r.text[:200]}")
j = wait_imp(A, iid)
check(j.get("state") == "done", f"import: done {j.get('state')} {j.get('error')}")
rb = rules(A, f"org:{BETA}")
check("Hook" in rb and "to" not in (rb["Hook"].get("task") or {}) and "webhook" not in rb["Hook"],
      f"import: carol (not ticked) is taken out of the task, the task goes to the author {rb.get('Hook')}")
check((rb.get("FuerBob", {}).get("task") or {}).get("to") == ids["bob"], f"import: bob (ticked) keeps his task {rb.get('FuerBob')}")

# ---- 3: undo by a person who may edit the document but not the folder it came from (alice's document of Alpha shared with
# carol to edit; alice's folder Alt is not open to the members)
r = flow(A, OWS, name="Umlegen", trigger="changed", on=["tags"], has_tags=["Erledigt"], folder="Neu")
check(r.status_code == 201, f"setup: a changed flow that files into Neu {r.status_code} {r.text[:200]}")
d1 = upload(A, "ablage.pdf", ["Ablage", "Brief"], ws=OWS)
done(A, d1)
check(A.patch(B + f"/api/docs/{d1}", json={"folder": "Alt"}).ok, "setup: the document lies in the folder Alt")
ALT = parent(d1)
d2 = upload(A, "ablage2.pdf", ["Ablage", "Zweiter Brief"], ws=OWS)
done(A, d2)
check(A.patch(B + f"/api/docs/{d2}", json={"folder": "Alt"}).ok and parent(d2) == ALT, "setup: a second one in Alt")
r = A.post(B + f"/api/files/nodes/{d1}/shares", json={"user_id": ids["carol"], "role": "edit"})
check(r.ok, f"setup: the document (only) shared with carol to edit {r.status_code} {r.text[:200]}")
for d in (d1, d2):
    check(A.patch(B + f"/api/docs/{d}", json={"tags": ["Erledigt"]}).ok, "setup: tag Erledigt")
NEU = parent(d1)
check(NEU != ALT and parent(d2) == NEU, f"the flow moved both into Neu {ALT} -> {NEU}")
check(Ca.get(B + f"/api/files/nodes/{ALT}").status_code in (403, 404), "carol does not see the folder Alt")
rr = runs(Ca, d1)
check(rr and rr[0]["did"] == ["folder"], f"carol sees the run on the shared document {rr}")
r = Ca.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo") if rr else None
check(r is not None and r.ok, f"carol may take the run back {r is not None and r.status_code}")
check(parent(d1) == NEU, f"undo: no move into the folder Alt that carol may not edit (stays in Neu) {parent(d1)}")
rr2 = runs(A, d2)
check(rr2 and A.post(B + f"/api/docs/flowruns/{rr2[0]['id']}/undo").ok and parent(d2) == ALT, "undo: alice, who may edit Alt, gets her document moved back")

# ---- 4: an old flow turned into a scheduled one does not run over the archive
r = flow(Fr, "private", name="Spaet", kind="any", match="Rueckblick", tags=["Vorher"])
check(r.status_code == 201, f"setup: an old flow {r.status_code} {r.text[:200]}")
SP = r.json().get("id") or rules(Fr, "private")["Spaet"]["id"]
dbx("UPDATE doc_rules SET created_at=? WHERE id=?", ("2020-01-02T08:00:00Z", SP))  # saved long ago
o1 = upload(Fr, "rueckblick-alt.pdf", ["Rueckblick", "Altes Schreiben"])
done(Fr, o1)
check(Fr.patch(B + f"/api/docs/{o1}", json={"date": "2021-03-01"}).ok, "setup: an archived document of 2021")
o2 = upload(Fr, "rueckblick-neu.pdf", ["Rueckblick", "Neues Schreiben"])
done(Fr, o2)
check(Fr.patch(B + f"/api/docs/{o2}", json={"date": date.today().isoformat()}).ok, "setup: a document of today")
r = Fr.patch(B + f"/api/docs/rules/{SP}", json={"name": "Spaet", "kind": "any", "match": "Rueckblick", "trigger": "scheduled", "days": 0,
                                               "from": "date", "tags": ["Rueckwirkend"]})
check(r.ok, f"the old flow turned into a scheduled one {r.status_code} {r.text[:200]}")
check(rules(Fr, "private")["Spaet"].get("since") == date.today().isoformat(), f"its day is the day of the change {rules(Fr, 'private')['Spaet']}")
check(until(lambda: "Rueckwirkend" in tags(doc(Fr, o2)), 30), "scheduled: the document of today is tagged")
check("Rueckwirkend" not in tags(doc(Fr, o1)), f"scheduled: the archived document of 2021 is left alone {tags(doc(Fr, o1))}")
r = Fr.patch(B + f"/api/docs/rules/{SP}", json={"name": "Spaet2", "kind": "any", "match": "Rueckblick", "trigger": "scheduled", "days": 0,
                                               "from": "date", "tags": ["Rueckwirkend"]})
check(r.ok and rules(Fr, "private")["Spaet2"].get("since") == date.today().isoformat(), "a new name keeps the day (the timing is the same)")

sys.exit(kt.done("p2581_e_flowreview"))
