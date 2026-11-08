#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.705.0 A (#5151): the rest of the hardening of #4382 (audit #2483, low findings 5 and 12). Own container with a server
key and a mail-in address (no IMAP server needed). Invented data.
freelancer-matrix: files
 - a receipt fetcher key (kbh_...) gets an optional address rule like an API token / scan inbox key: PATCH
   /api/docs/fetchers/<id> {allowed_ips}; the key from another address answers 403 and reaches nothing; from an allowed
   network it works; [] = any address again; a wrong address 400, an unknown field 400, another person's fetcher 404,
   the list shows the rule (a person without organisation and an organisation's fetcher)
 - the plus address tokens of an older version (plain token, token_hash NULL) in mail_tokens, hub_tokens and doc_mail are
   sealed + hashed by the watchdog's mtk_reseal_tick: not on its first run (it notes the time), not before MTK_RESEAL_DAYS,
   then all of them; a mail still finds them by the plain token and the settings show the same address
usage: p2705_a_harden_test.py <datadir>"""
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.docker_logs_on_first_fail()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1",
              "KALMIDO_IMAP_PORT": "1143", "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido",
              "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "3600"}, prefix="P2705A")
V = B + "/api/v1"
FEAT = "collab,comments,files,docs,office,clients"


def py(code):
    """Python inside the app container -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def fx_key(code):
    raw = code.split(":", 2)[-1] if code else ""
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("key") if raw else ""


A = kt.setup()
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)  # freelancer-matrix: files

# ================================================================== the address rule of a receipt fetcher key
for who, s, ws in (("freelancer", Fr, "private"), ("org", A, f"org:{ORG}")):
    r = s.post(B + "/api/docs/fetchers", json={"ws": ws, "name": "Rechner " + who})
    check(r.status_code == 201, f"{who}: a receipt fetcher {r.text[:200]}")
    FXK, FXID = fx_key(r.json().get("code", "")), r.json().get("id")
    check(requests.get(V + "/fetcher", headers=bearer(FXK)).ok, f"{who}: the key works without a rule")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": "203.0.113.0/24, 198.51.100.7"})
    check(r.ok and r.json().get("allowed_ips") == ["203.0.113.0/24", "198.51.100.7/32"], f"{who}: the rule is stored {r.status_code} {r.text[:200]}")
    lst = s.get(B + "/api/docs/fetchers", params={"ws": ws}).json().get("fetchers") or []
    check([f.get("allowed_ips") for f in lst if f["id"] == FXID] == [["203.0.113.0/24", "198.51.100.7/32"]], f"{who}: the list shows it")
    r = requests.get(V + "/fetcher", headers=bearer(FXK))
    check(r.status_code == 403 and "address" in r.text, f"{who}: the key from another address: 403 ({r.status_code} {r.text[:200]})")
    r = requests.put(V + "/fetcher/status", headers=bearer(FXK), json={"portals": [{"key": "amazon"}]})
    check(r.status_code == 403, f"{who}: ... also its report ({r.status_code})")
    check(not dbx("SELECT 1 FROM doc_fetch_portals WHERE fetcher_id=?", (FXID,)), f"{who}: nothing was stored")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": ["0.0.0.0/0", "::/0"]})
    check(r.ok and requests.get(V + "/fetcher", headers=bearer(FXK)).ok, f"{who}: from an allowed network it works")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": "203.0.113.5"})
    check(r.ok and requests.get(V + "/fetcher", headers=bearer(FXK)).status_code == 403, f"{who}: a single other address: 403 again")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": []})
    check(r.ok and r.json().get("allowed_ips") == [] and requests.get(V + "/fetcher", headers=bearer(FXK)).ok,
          f"{who}: [] = any address again {r.text[:200]}")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": "kein-netz"})
    check(r.status_code == 400 and "kein-netz" in r.text, f"{who}: a wrong address 400 ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": "", "name": "x"})
    check(r.status_code == 400, f"{who}: an unknown field 400 ({r.status_code})")
    other = A if s is Fr else Fr
    r = other.patch(B + f"/api/docs/fetchers/{FXID}", json={"allowed_ips": "0.0.0.0/0"})
    check(r.status_code == 404, f"{who}: another person cannot set the rule ({r.status_code})")
    r = requests.patch(B + f"/api/docs/fetchers/{FXID}", headers=bearer(FXK), json={"allowed_ips": ""})
    check(r.status_code in (401, 403), f"{who}: the key itself cannot change it ({r.status_code})")

# ================================================================== old plain plus address tokens sealed
OLD = {"mail_tokens": "p2705aoldmail1", "hub_tokens": "p2705aoldhub1", "doc_mail": "p2705aolddoc1"}
dbx("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,NULL,?)", (OLD["mail_tokens"], FID, "2026-01-01T00:00:00Z"))
dbx("INSERT INTO hub_tokens(token,kind,user_id,org_id,client_id,list_id,created_at) VALUES(?,?,?,NULL,NULL,NULL,?)",
    (OLD["hub_tokens"], "inbox", FID, "2026-01-01T00:00:00Z"))
dbx("INSERT INTO doc_mail(token,user_id,org_id,created_at) VALUES(?,?,NULL,?)", (OLD["doc_mail"], FID, "2026-01-01T00:00:00Z"))


def plain_left():
    return sorted(t for t, tok in OLD.items() if dbx(f"SELECT 1 FROM {t} WHERE token=? AND token_hash IS NULL", (tok,)))


TICK = r'''
import json, app
from kalmido.core.db import connect
from kalmido.accounts.mailtok import mtk_reseal_tick
c = connect()
print(json.dumps({"n": mtk_reseal_tick(c, force=True)}))
'''
dbx("DELETE FROM settings WHERE key='mtk_reseal_since'")
j = py(TICK)
check(j.get("n") == 0 and plain_left() == sorted(OLD), f"first run: nothing sealed {j} {plain_left()}")
check(dbx("SELECT value FROM settings WHERE key='mtk_reseal_since'"), "first run: the time is noted")
dbx("UPDATE settings SET value=? WHERE key='mtk_reseal_since'", ((kt.today() - timedelta(days=12)).isoformat() + "T00:00:00+00:00",))
j = py(TICK)
check(j.get("n") == 0 and plain_left() == sorted(OLD), f"before MTK_RESEAL_DAYS: nothing sealed {j} {plain_left()}")
dbx("UPDATE settings SET value=? WHERE key='mtk_reseal_since'", ((kt.today() - timedelta(days=15)).isoformat() + "T00:00:00+00:00",))
j = py(TICK)
check(j.get("n", 0) >= 3 and plain_left() == [], f"after MTK_RESEAL_DAYS: all sealed {j} {plain_left()}")
for t, tok in OLD.items():
    h = hashlib.sha256(tok.encode()).hexdigest()
    rows = dbx(f"SELECT token FROM {t} WHERE token_hash=?", (h,))
    check(len(rows) == 1 and rows[0][0].startswith("v1.") and tok not in rows[0][0], f"{t}: sealed + hashed, the plain token is gone")
j = py(TICK)
check(j.get("n") == 0, f"a second run finds nothing left {j}")
j = py(r'''
import email.message, json, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.integrations.mail import mail_target, mail_tokens
from kalmido.hub import hubmail as H
from kalmido.docs import ingest as I
m = email.message.EmailMessage()
m["From"], m["To"], m["Subject"] = "someone@example.com", "tasks+%s@example.test", "x"
m.set_content("x")
c = connect()
out = {}
with system_ctx(c):
    out["task"] = mail_target(c, m)[0]
    r = H._hub_tok_row(c, %r)
    out["hub"] = r["user_id"] if r else None
    r = I._doc_mail_row(c, [%r])
    out["doc"] = r["user_id"] if r else None
    out["mine"] = list(mail_tokens(c, %d).values())
c.rollback()
print(json.dumps(out))
''' % (OLD["mail_tokens"], OLD["hub_tokens"], OLD["doc_mail"], FID))
check(j.get("task") == FID and j.get("hub") == FID and j.get("doc") == FID, f"a mail still finds the sealed old addresses {j}")
check(j.get("mine") == [OLD["mail_tokens"]], f"the settings show the same address {j}")

sys.exit(kt.done("p2705_a_harden"))
