#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.556.0 C (#4672) API test, own container (hosted, the operator console on): the hosting operator deletes an account
that keeps records by law (a finalised invoice, a receipt with its file) after the person's retention export -- the route
runs without a person (g.user None), the retention gate takes how=exported (admin/operator.operator_account_delete ->
accounts/users.user_delete_run -> admin/retexport.rx_gate). Invented people only (example.com).
freelancer-matrix: operator (the account is a person without an organisation)
 - without a finished export: 409 code retention with the number of records, the account stays
 - after the person's download: 200 deleted, the account is gone (404, no sign-in), its export row in retention_log stays
 - the server log shows no traceback (the suspected crash at me() without a person)
usage: p2556_c_opdel_test.py <datadir>"""
import base64
import os
import secrets
import shutil
import subprocess
import sys

import requests

import kt
from kt import B, CT, check, su_get

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402

kt.docker_logs_on_first_fail()
DATA = sys.argv[1] if len(sys.argv) > 1 else kt.DATA
OPDIR = os.path.abspath(DATA.rstrip("/")) + "-op"
TOKEN = secrets.token_urlsafe(40)
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"


def op(method, path, **kw):
    return requests.request(method, B + "/api/operator/" + path, headers={"Authorization": "Bearer " + TOKEN}, timeout=60, **kw)


def can_login(user):
    s = requests.Session()
    s.headers.update(kt.H)
    return s.post(B + "/api/auth/login", json={"username": user, "password": kt.PASSWORD}).ok


shutil.rmtree(OPDIR, ignore_errors=True)
os.makedirs(OPDIR)
with open(os.path.join(OPDIR, "token"), "w") as f:
    f.write(TOKEN + "\n")
os.chmod(OPDIR, 0o755)
os.chmod(os.path.join(OPDIR, "token"), 0o644)
env = dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + f" -v {OPDIR}:/run/kop:ro -e KALMIDO_OPERATOR_TOKEN_FILE=/run/kop/token"
                              f" -e KALMIDO_HOSTED=1 -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}").strip())
env.pop("KEEP", None)
r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.abspath(__file__)), "start.sh"), DATA],
                   capture_output=True, text=True, env=env)
assert r.returncode == 0, r.stdout + r.stderr

A = kt.setup()
FID, Fr = freelancer(B, A, "frieda")
r = Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frieda Film", "street": "Teststrasse 1", "zip": "20000",
                                                         "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890",
                                                         "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}})
assert r.ok, r.text
r = Fr.post(B + "/api/clients", json={"name": "Example Client Ltd", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"})
assert r.ok, r.text
r = Fr.post(B + O + "/docs", json={"kind": "invoice", "client_id": r.json()["id"], "service_from": "2026-03-01",
                                   "service_to": "2026-03-02", "items": [{"title": "Schnitt", "qty": 1, "rate": 120}]})
assert r.status_code == 201, r.text
assert Fr.post(B + O + f"/docs/{r.json()['id']}/finalize").ok
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("beleg.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")})
assert r.status_code == 201, r.text
nid = r.json()["ids"][0]
assert Fr.patch(B + f"/api/docs/{nid}", json={"amount": "11.90", "date": "2026-03-06"}).ok
assert Fr.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True}).ok
j = Fr.get(B + "/api/retention/me").json()
check(j.get("needed") is True and j.get("hosted") is True, f"setup: hosted, records to keep {j}")

# ---- without the export: refused, the account stays
r = op("DELETE", f"accounts/{FID}?confirm={FID}")
check(r.status_code == 409 and r.json().get("code") == "retention" and (r.json().get("records") or 0) >= 2,
      f"without an export: 409 retention with the number {r.status_code} {r.text[:200]}")
check(can_login("frieda"), "refused: the account stays")

# ---- after the person's download: the operator deletes it (no person in the request: g.user None)
z = su_get(Fr, B + "/api/retention/me/export.zip")
check(z.ok and z.content.startswith(b"PK"), f"the person's retention export {z.status_code}")
rows = kt.dbx("SELECT kind FROM retention_log WHERE subject=?", (f"user:{FID}",))
check(rows, f"the export is noted {rows}")
r = op("DELETE", f"accounts/{FID}?confirm={FID}")
check(r.ok and r.json().get("deleted") == FID, f"after the export: deleted by the operator {r.status_code} {r.text[:300]}")
check(op("GET", f"accounts/{FID}").status_code == 404 and not can_login("frieda"), "deleted: gone, no sign-in")
check(kt.dbx("SELECT kind FROM retention_log WHERE subject=?", (f"user:{FID}",)) == rows, "the retention log row outlives the account")
check(A.get(B + "/api/state").ok, "the app's admin keeps working")

lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
text = lg.stdout + lg.stderr
check("Traceback" not in text, "no traceback in the server log")
check(f"operator: account-delete #{FID}" in text, "the deletion is logged by number")

shutil.rmtree(OPDIR, ignore_errors=True)
sys.exit(kt.done("p2556_c_opdel"))
