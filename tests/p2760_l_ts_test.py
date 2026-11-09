#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.760.0 (#5311): the core template on real time types -- the test kind 'objprobe' (tests/obj_probe.py) has
created_at / updated_at / deleted_at as TIMESTAMPTZ, as docs/dev/kern.md now says. Invented names only.
 - the columns are TIMESTAMPTZ; the answers carry them as ISO text in ONE canonical form (UTC, +00:00), never a date
   string of another shape (kalmido/core/pg.py ts_canon + the TIMESTAMPTZ loader)
 - expect_updated_at compares canonically (kalmido/core/conflict.py ccf_check): the same instant written with Z or another
   offset passes (red before 2.760: a plain text compare said 409), an older one is 409 with the current state
 - the trash: deleted_at set and cleared on a TIMESTAMPTZ column, the trash list reads it
 - ts_canon itself inside the app (datetime, offsets, a space, '', text that is no time) and a TIMESTAMPTZ read
freelancer-matrix: obj (a person without an organisation: create, change with a version in another form, trash)
usage: p2760_l_ts_test.py <datadir>"""
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, sess  # noqa: E402
from obj_probe import K, in_app, new, start  # noqa: E402

start("P2760L")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FID, Fr = freelancer(B, A)
CANON = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{6})?\+00:00$")


def get(s, oid):
    return s.get(B + f"/api/obj/{K}/{oid}").json()


def other_forms(ts):
    """The same instant as Z and as +01:00 (ts is canonical, UTC)."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromisoformat(ts)
    return ts.replace("+00:00", "Z"), d.astimezone(timezone(timedelta(hours=1))).isoformat()


# ---------------------------------------------------------------- the column types
types = dbx("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='obj_probe' "
            "AND column_name IN ('created_at','updated_at','deleted_at') ORDER BY column_name")
check([tuple(x) for x in types] == [("created_at", "timestamp with time zone"), ("deleted_at", "timestamp with time zone"),
                                     ("updated_at", "timestamp with time zone")], f"the probe table follows the template {types}")

for who, s, org in (("org member", A, ORG), ("freelancer", Fr, None)):
    o = new(s, "Plan " + who, org, note="first")
    oid = o["id"]
    check(CANON.match(o.get("updated_at") or "") and CANON.match(o.get("created_at") or "") and o.get("deleted_at") in (None, ""),
          f"{who}: created_at / updated_at as canonical ISO text {o.get('created_at')!r} {o.get('updated_at')!r}")
    check(get(s, oid)["updated_at"] == o["updated_at"], f"{who}: the read gives the same text as the create")
    z, plus1 = other_forms(o["updated_at"])
    r = s.patch(B + f"/api/obj/{K}/{oid}", json={"note": "second", "expect_updated_at": z})
    check(r.ok and r.json().get("note") == "second", f"{who}: the same instant with Z is no conflict ({r.status_code} {r.text[:200]})")
    cur = r.json() if r.ok else get(s, oid)
    check(CANON.match(cur.get("updated_at") or ""), f"{who}: the new version canonical {cur.get('updated_at')!r}")
    r = s.patch(B + f"/api/obj/{K}/{oid}", json={"note": "third", "expect_updated_at": other_forms(cur["updated_at"])[1]})
    check(r.ok and r.json().get("note") == "third", f"{who}: the same instant as +01:00 is no conflict ({r.status_code} {r.text[:200]})")
    r = s.patch(B + f"/api/obj/{K}/{oid}", json={"note": "stale", "expect_updated_at": "2000-01-01T00:00:00Z"})
    body = r.json() if r.status_code == 409 else {}
    check(r.status_code == 409 and body.get("current", {}).get("note") == "third" and CANON.match(body["current"].get("updated_at") or "")
          and get(s, oid)["note"] == "third", f"{who}: an older version 409 with the current state, nothing written ({r.status_code} {r.text[:200]})")
    check(s.post(B + f"/api/obj/{K}/{oid}/trash").ok, f"{who}: to the trash")
    tr_items = s.get(B + f"/api/obj/{K}", params={"trash": "1"}).json().get("items", [])
    t = [x for x in tr_items if x["id"] == oid]
    check(t and CANON.match(t[0].get("deleted_at") or t[0].get("updated_at") or ""), f"{who}: the trash list reads the TIMESTAMPTZ row {t}")
    check(s.post(B + f"/api/obj/{K}/{oid}/restore").ok and get(s, oid).get("deleted_at") in (None, ""), f"{who}: restored, deleted_at cleared")

# ---------------------------------------------------------------- ts_canon inside the app
out = in_app("""from datetime import datetime, timezone, timedelta
from kalmido.core.pg import ts_canon
from kalmido.core.conflict import ccf_check, Conflict
cases = [ts_canon(datetime(2026, 11, 9, 2, 0, 0)), ts_canon(datetime(2026, 11, 9, 3, 0, 0, tzinfo=timezone(timedelta(hours=1)))),
         ts_canon("2026-11-09 03:00:00+01:00"), ts_canon("2026-11-09T02:00:00Z"), ts_canon("2026-11-09T02:00:00.120+00:00"),
         ts_canon(""), ts_canon(None), ts_canon("not a time")]
print("CASES", cases)
print("READ", repr(c.execute("SELECT '2026-11-09T02:00:00.5Z'::timestamptz AS t").fetchone()["t"]))
try:
    ccf_check({"expect_updated_at": "2026-11-09T03:00:00+01:00"}, "2026-11-09T02:00:00+00:00", "cur", lambda: 1)
    print("SAME ok")
except Conflict:
    print("SAME conflict")
try:
    ccf_check({"expect_updated_at": "2026-11-09T02:00:01Z"}, "2026-11-09T02:00:00+00:00", "cur", lambda: 1)
    print("OTHER ok")
except Conflict:
    print("OTHER conflict")
print("OVER", repr(ts_canon("0001-01-01T00:00:00+01:00")))
from kalmido.admin.acctimport import _coerce, _BAD
print("COERCE", repr(_coerce("2026-11-09T02:00:00+00:00", "timestamp with time zone")), _coerce("nope", "timestamp with time zone") is _BAD)""")
exp = ["2026-11-09T02:00:00+00:00"] * 4 + ["2026-11-09T02:00:00.120000+00:00", "", "", "not a time"]
check(f"CASES {exp!r}" in out, f"ts_canon: one form for datetime, offsets, a space, ms; '' / None empty; other text kept\n{out[-600:]}")
check("READ '2026-11-09T02:00:00.500000+00:00'" in out, f"a TIMESTAMPTZ reads as canonical ISO text\n{out[-400:]}")
check("SAME ok" in out and "OTHER conflict" in out, f"ccf_check: same instant passes, another one is a conflict\n{out[-400:]}")

check("OVER '0001-01-01T00:00:00+01:00'" in out, f"review: a time out of range stays as given, no 500\n{out[-400:]}")
check("COERCE '2026-11-09T02:00:00+00:00' True" in out, f"review: the account import takes a TIMESTAMPTZ column over (a bad one not)\n{out[-400:]}")
sys.exit(done("p2760_l_ts"))
