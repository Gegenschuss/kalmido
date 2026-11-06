#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.574.0 part B (#4556): the account import asks connections again like a request by hand. Invented names only (example.com).
Persons without an organisation (freelancer_fixture); an export of gina (connected with otto, quinn and 50 more people) imported
by hanna:
 - otto gets the request as News like discover.conn_request tells one (kind connreq, from hanna, with her name)
 - quinn blocked hanna: the request is hidden and nothing reaches quinn (no News)
 - at most UMZ_CONN_MAX (50) new requests in one run: the rest is not asked and named in its own warning
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2574B_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2574_b_umzug_test.py <datadir>"""
import base64
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, su_get, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
TS = "2026-10-20T06:00:00+00:00"
CAP = 50  # kalmido/admin/umz_more.py UMZ_CONN_MAX


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


def link(x, y):
    lo, hi = sorted((x, y))
    kt.dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?,?,?)", (lo, hi, TS))


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2574B")
A = kt.setup()
GID, G = freelancer(B, A, "gina")
OID, O = freelancer(B, A, "otto")
QID, _ = freelancer(B, A, "quinn")
HID, H = freelancer(B, A, "hanna")
link(GID, OID)
link(GID, QID)
PALS = []
for n in range(1, CAP + 1):  # 50 more: with otto and quinn 52 connections, the export lists them by account id (the last two over)
    r = A.post(B + "/api/users", json={"username": f"pal{n:02d}", "display_name": f"Pal{n:02d}", "password": "password123",
                                       "email": f"pal{n:02d}@example.com", "orgs": []})
    assert r.ok, r.text
    PALS.append(r.json()["id"])
    link(GID, PALS[-1])
kt.dbx("INSERT INTO conn_blocks(user_id, blocked_id, created_at) VALUES(?,?,?)", (QID, HID, TS))
check(one("SELECT count(*) FROM conn_links WHERE ? IN (a_id, b_id)", (GID,)) == CAP + 2, "setup: gina has 52 connections")

# ---- the export of gina, imported by hanna
check(G.post(B + "/api/account/export").status_code == 202, "the export starts")
j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(G.get(B + "/api/account/export").json()), 180) or {}
check(j.get("state") == "done", f"the export is done {j.get('state')}")
ZIP = su_get(G, B + "/api/account/export/file").content
iid, j = upload(H, ZIP)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
r = H.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
j = until(lambda: state_of(H, iid), 180) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
W = [x.get("text", "") for x in (j.get("result") or {}).get("warnings") or []]

# ---- otto: an open request, told like one asked by hand
check(one("SELECT status FROM conn_requests WHERE from_id=? AND to_id=?", (HID, OID)) == "open", "otto: an open request")
nw = kt.dbx("SELECT actor_id, data FROM notifications WHERE user_id=? AND kind='connreq'", (OID,))
check(len(nw) == 1, f"otto: one News about it {nw}")
d = (json.loads(nw[0][1]) if isinstance(nw[0][1], str) else nw[0][1]) if nw else {}
check(bool(nw) and nw[0][0] == HID and d.get("name") == "Hanna" and "via" not in d, f"otto: … from hanna, with her name {nw}")
news = O.get(B + "/api/news").json() if O.get(B + "/api/news").ok else {}
check("Hanna" in json.dumps(news), "otto: the News list shows it")

# ---- quinn blocked hanna: hidden, silent
check(one("SELECT status FROM conn_requests WHERE from_id=? AND to_id=?", (HID, QID)) == "hidden", "quinn: the request is hidden")
check(not one("SELECT count(*) FROM notifications WHERE user_id=? AND kind='connreq'", (QID,)), "quinn: nothing reaches the person who blocked")

# ---- the limit per run
check(one("SELECT count(*) FROM conn_requests WHERE from_id=?", (HID,)) == CAP, f"at most {CAP} new requests in one run "
      f"({one('SELECT count(*) FROM conn_requests WHERE from_id=?', (HID,))})")
check(not one("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id IN (?, ?)", (HID, PALS[-2], PALS[-1])), "the two over the limit are not asked")
over = next((w for w in W if w.startswith("Connections not asked again, more than")), "")
check(f"more than {CAP}" in over and "Pal49" in over and "Pal50" in over and "Pal48" not in over, f"the rest is named in its own warning: {W}")
check(any(w.startswith("Connections asked again") and "Otto" in w for w in W), f"the asked ones are named as before: {W}")
check(not one("SELECT 1 FROM conn_links WHERE ? IN (a_id, b_id)", (HID,)), "never a connection without the other person")

print(f"p2574_b_umzug: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
