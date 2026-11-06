#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.516.0 (#4364): the undo of an import keeps the stored PDF / XML of a finalised document that stays, and the logo /
letterhead copies a document that stays names. Invented names only (example.com). A person without an organisation
(freelancer-matrix: office) finalises two invoices in the personal office (sealed: KALMIDO_SECRET_KEY); inside the app:
 - the import records the owner row of each office file it writes (oi_office._oi_own: the real path -> office_docs id)
 - an invoice of the import that stays (a payment booked since): its PDF and XML stay, also when the import is from before the
   owners were recorded (no oi_file_rows: judged by the id in the name)
 - an invoice of the import that goes: its PDF goes
 - logo-<hash>.png / lhs-<hash>.pdf: stays while a document that does not go names it in its (sealed) sender, also one
   finalised after the import; goes when none does
 - an attachment no row names goes as before
usage: p2516_a_undo_files_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
D = "/api/office/docs"


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json, os, types\nimport app\nfrom kalmido.core.db import connect\nc = connect()\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", kt.CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2516A")
A = kt.setup()
FID, Fr = freelancer(B, A)
check(Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Studio Beispiel", "street": "Hafenweg 2", "zip": "12345",
                                                                  "city": "Musterstadt", "iban": "DE02120300000000202051",
                                                                  "tax_number": "12/345/67890"},
                                               "lang": "en", "currency": "EUR"}).ok, "office settings")
CL = Fr.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "street": "Musterweg 1", "zip": "12345",
                                       "city": "Musterstadt"}).json()["id"]
INV = []
for t in ("Eins", "Zwei"):
    r = Fr.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": t, "service_from": "2026-05-01",
                             "items": [{"title": "Beratung", "qty": 1, "rate": 300}]})
    check(r.status_code in (200, 201), f"invoice {t} {r.text[:200]}")
    did = r.json().get("id")
    r = Fr.post(B + f"{D}/{did}/finalize")
    check(r.ok and r.json().get("locked"), f"invoice {t} finalised {r.status_code} {r.text[:300]}")
    INV.append(did)
I1, I2 = INV
OID = kt.dbx("SELECT org_id FROM office_docs WHERE id=?", (I1,))[0][0]

j = in_app(f"""
from kalmido.admin import oi_office
from kalmido.admin.orgimport import oi_undo_files_left
from kalmido.admin.umz_undoplan import UndoPlan
from kalmido.core.config import ATT_DIR, OFFICE_DIR
from kalmido.core.orgcrypt import oc_enc_fields
out = {{}}
I1, I2, OID, GONE = {I1}, {I2}, {OID}, 987654321
d = os.path.join(OFFICE_DIR, str(OID))
os.makedirs(d, exist_ok=True)
def f(n, base=d):
    p = os.path.realpath(os.path.join(base, n))
    with open(p, "wb") as fh:
        fh.write(b"invented")
    return p
LOGO_USED, LOGO_FREE, LHS_USED = "logo-" + "a" * 16 + ".png", "logo-" + "b" * 16 + ".png", "lhs-" + "c" * 16 + ".pdf"
# invoice 2 (not of the import: finalised after it) names the logo and the letterhead copy in its sealed sender
snd = json.dumps({{"name": "Studio Beispiel", "logo": LOGO_USED, "letterhead": {{"file": LHS_USED}}}})
enc = oc_enc_fields(c, OID, "office_docs", {{"sender": snd}})["sender"]
from kalmido.office.model import ofx_release
with ofx_release(c):  # the hand-made setup writes a finalised row: past the trigger of #4598, like the app's deliberate exceptions
    c.execute("UPDATE office_docs SET sender=? WHERE id=?", (enc, I2))
c.commit()
out["sealed"] = LOGO_USED not in str(c.execute("SELECT sender FROM office_docs WHERE id=?", (I2,)).fetchone()[0])
# the recording of _a_doc: the real path -> its rows
ctx = types.SimpleNamespace(space=OID, run=types.SimpleNamespace(created={{}}))
oi_office._oi_own(ctx, f"doc{{I1}}-invoice-1.pdf", ("office_docs", I1))
oi_office._oi_own(ctx, f"doc{{I1}}-invoice-1.pdf", ("office_docs", I1))
oi_office._oi_own(ctx, None, ("office_docs", I1))
out["rows"] = ctx.run.created.get("oi_file_rows")
out["want_rows"] = {{os.path.realpath(os.path.join(d, f"doc{{I1}}-invoice-1.pdf")): [["office_docs", I1]]}}
paths = {{
    "keep_pdf": f(f"doc{{I1}}-invoice-1.pdf"), "keep_xml": f(f"doc{{I1}}-invoice-1.xml"),
    "legacy_pdf": f(f"doc{{I1}}-invoice-1.accepted-5.pdf"),
    "go_pdf": f(f"doc{{GONE}}-invoice-9.pdf"),
    "logo_used": f(LOGO_USED), "logo_free": f(LOGO_FREE), "lhs_used": f(LHS_USED),
    "att": f("p2516-" + os.urandom(4).hex() + "-note.txt", ATT_DIR),
}}
own = {{paths[k]: [["office_docs", I1]] for k in ("keep_pdf", "keep_xml")}}
own.update({{paths[k]: [["office_docs", GONE]] for k in ("go_pdf", "logo_used", "logo_free", "lhs_used")}})
plan = UndoPlan()
plan.exist = {{("office_docs", I1), ("office_docs", GONE)}}
plan.keep = {{("office_docs", I1)}}  # invoice 1 of the import stays (a payment booked since), GONE goes
left = oi_undo_files_left(c, plan, {{"oi_files": list(paths.values()), "oi_file_rows": own}}, [])
out["left"] = sorted(k for k, p in paths.items() if p in left)
# an import from before the owners were recorded: the same without oi_file_rows
left = oi_undo_files_left(c, plan, {{"oi_files": list(paths.values())}}, [])
out["left_old"] = sorted(k for k, p in paths.items() if p in left)
for p in paths.values():
    os.remove(p)
""")
check(j["sealed"], "the sender of invoice 2 is sealed (the logo name stands in no plain column)")
check(j["rows"] == j["want_rows"], f"_oi_own records the owner row once per file: {j['rows']}")
check(j["left"] == ["att", "go_pdf", "logo_free"],
      f"the undo deletes only the files of rows that go (PDF / XML of the staying invoice and the named logo / letterhead copies stay): {j['left']}")
check(j["left_old"] == ["att", "go_pdf", "logo_free"], f"an older import without owners: the same by the id in the name {j['left_old']}")

sys.exit(kt.done("p2516_a_undo_files"))
