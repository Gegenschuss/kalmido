#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1115.0 (#5951) part D2: the time columns of the accounts and the ways in (sessions, users, OAuth, API tokens, portal,
public links, organisations, admin alerts, webhooks, ...) onto TIMESTAMPTZ / DATE (core/coltime.py CT_D2). Own container
(start.sh). Invented names only.
   freelancer-matrix: n/a (no route of its own; the areas' suites cover their routes)
 - a new database: the 45 D2 columns are TIMESTAMPTZ, orgs.retain_until / webhooks.org_grace_until DATE; sessions.last_seen_at /
   stepup_at and webhooks.org_grace_until nullable without the DEFAULT ''
 - an older database (columns as TEXT again, in a rolled back transaction), the turn fails closed: a used recovery code with ''
   or a misfit stays used (CT_D2_CLOSED "all"), an API token's misfit expiry counts as ended while '' stays "never" ("misfit"),
   a session's '' expiry is the past, last_seen_at '' is NULL, a webhook's grace '' is NULL and a day stays that day
 - expired = refused after the turn: a session past its end (401), an API token past its end (401 "expired"), an API token
   whose misfit end was turned (401)
 - the code that read these columns as text: the session touch writes over NULL (sessions.ses_touch), the account numbers of
   the operator (admin/operator.py _op_account, admin/hosting.py org_activity), the invitation purge (OJN_PURGE_SQL), the
   prune of retired organisations (orgs.retain_until DATE), the end of a webhook's grace (NULL, not ''), the revoked_creds
   trigger of a deleted API token (exp in the canonical form, no error on TIMESTAMPTZ), the recovery-key showing check
usage: p21115_d2_access_coltime_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, check  # noqa: E402

kt.fresh(prefix="P21115D2")
A = kt.setup()


def py(code):
    """Runs code in the container (the owner's direct connection c under system_ctx) -> (the JSON of its last line, stderr)."""
    src = ("import app, json, sys\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.db import connect_direct\n"
           "from kalmido.core.pg import system_ctx\nc = connect_direct(DATABASE_URL)\n"
           "with system_ctx(c):\n" + "".join("    " + x + "\n" for x in code.strip().splitlines()) + "c.close()\n")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", src], capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr
    except (ValueError, IndexError):
        return {"_error": out.stdout[-400:] + out.stderr[-800:]}, out.stderr


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


NOW = datetime.now(timezone.utc)
UID = kt.dbx("SELECT id FROM users WHERE username='alice'")[0][0]

# ---- a new database
ty, _e = py("""
from kalmido.core.coltime import CT_D2, CT_D2_CLOSED
have = {(t, col): (typ, nl, d) for t, col, typ, nl, d in c.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
want = {"ts": "timestamp with time zone", "date": "date"}
print(json.dumps({"n": len(CT_D2), "dates": sorted(f"{t}.{col}" for (t, col), k in CT_D2.items() if k == "date"),
                  "other": sorted(f"{t}.{col}={(have.get((t, col)) or ['?'])[0]}" for (t, col), k in CT_D2.items() if (have.get((t, col)) or ['?'])[0] != want[k]),
                  "closed_in": all(k in CT_D2 for k in CT_D2_CLOSED),
                  "open": {f"{t}.{col}": list(have.get((t, col)) or [])[1:] for t, col in (("sessions", "last_seen_at"), ("sessions", "stepup_at"), ("webhooks", "org_grace_until"))}}))
""")
check(ty.get("n") == 45 and ty.get("other") == [], f"a new database: the 45 D2 columns have their type ({ty})")
check(ty.get("dates") == ["orgs.retain_until", "webhooks.org_grace_until"], f"the two days are DATE ({ty.get('dates')})")
check(ty.get("closed_in") is True, "every fail-closed column is a D2 column")
check(ty.get("open") == {"sessions.last_seen_at": ["YES", None], "sessions.stepup_at": ["YES", None], "webhooks.org_grace_until": ["YES", None]},
      f"the former NOT NULL DEFAULT '' columns are nullable without a default ({ty.get('open')})")

# ---- an older database: some columns as TEXT again (rolled back), then the start's turn. Fails closed.
old, err = py(f"""
import kalmido.core.coltype as ct
from kalmido.core.coltype import ct_iso
from kalmido.core.db import parse_iso
from kalmido.core.db import now_utc
uid = {UID}
c.execute("ALTER TABLE recovery_codes ALTER COLUMN used_at TYPE TEXT USING " + ct_iso("used_at"))
c.execute("ALTER TABLE api_tokens ALTER COLUMN expires_at TYPE TEXT USING " + ct_iso("expires_at"))
c.execute("ALTER TABLE sessions ALTER COLUMN expires_at TYPE TEXT USING " + ct_iso("expires_at") + ", ALTER COLUMN last_seen_at TYPE TEXT USING COALESCE(" + ct_iso("last_seen_at") + ", ''), ALTER COLUMN last_seen_at SET DEFAULT '', ALTER COLUMN last_seen_at SET NOT NULL")
c.execute("ALTER TABLE webhooks ALTER COLUMN org_grace_until TYPE TEXT USING CAST(org_grace_until AS text), ALTER COLUMN org_grace_until SET DEFAULT ''")
c.execute("UPDATE webhooks SET org_grace_until='' WHERE org_grace_until IS NULL")
c.execute("ALTER TABLE webhooks ALTER COLUMN org_grace_until SET NOT NULL")
made = '2026-02-01T09:00:00+00:00'
for h, used in (('rc5951a', '2026-03-01T10:00:00Z'), ('rc5951b', ''), ('rc5951c', 'once'), ('rc5951d', None)):
    c.execute("INSERT INTO recovery_codes(user_id, code_hash, created_at, used_at) VALUES(?,?,?,?)", (uid, h, made, used))
for h, exp in (('tk5951a', ''), ('tk5951b', 'soon'), ('tk5951c', '2099-01-01T00:00:00+00:00')):
    c.execute("INSERT INTO api_tokens(user_id, name, token_hash, prefix, scopes, expires_at, created_at) VALUES(?,?,?,?,?,?,?)", (uid, h, h, h[:8], 'read', exp, made))
c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES('se5951a', ?, ?, '', ''), ('se5951b', ?, ?, '2099-01-01T00:00:00+00:00', '')", (uid, made, uid, made))
for n, until in (('wh5951a', ''), ('wh5951b', '2026-12-31')):
    c.execute("INSERT INTO webhooks(user_id, name, url, events, secret, created_at, updated_at, org_grace_until) VALUES(?,?,?,?,?,?,?,?)", (uid, n, 'https://hooks.example.com/x', '', 'x', made, made, until))
keys = ('recovery_codes.used_at', 'api_tokens.expires_at', 'sessions.expires_at', 'sessions.last_seen_at', 'webhooks.org_grace_until')
out = {{"turn": {{k: v for k, v in ct._ct_more(c, '2026-11-13T08:00:00+00:00').items() if k in keys}}}}
out["codes"] = [list(r) for r in c.execute("SELECT code_hash, used_at FROM recovery_codes WHERE code_hash LIKE 'rc5951%' ORDER BY code_hash").fetchall()]
out["left"] = c.execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND code_hash LIKE 'rc5951%' AND used_at IS NULL", (uid,)).fetchone()[0]
toks = c.execute("SELECT token_hash, expires_at FROM api_tokens WHERE token_hash LIKE 'tk5951%' ORDER BY token_hash").fetchall()
out["toks"] = [[r[0], r[1], bool(r[1] and parse_iso(r[1]) <= now_utc())] for r in toks]
out["ses"] = [list(r) for r in c.execute("SELECT token_hash, expires_at, last_seen_at FROM sessions WHERE token_hash LIKE 'se5951%' ORDER BY token_hash").fetchall()]
out["live"] = [r[0] for r in c.execute("SELECT token_hash FROM sessions WHERE token_hash LIKE 'se5951%' AND expires_at>? ORDER BY token_hash", (now_utc().isoformat(),)).fetchall()]
out["hooks"] = [list(r) for r in c.execute("SELECT name, org_grace_until FROM webhooks WHERE name LIKE 'wh5951%' ORDER BY name").fetchall()]
out["cols"] = {{f"{{r[0]}}.{{r[1]}}": [r[2], r[3], r[4]] for r in c.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND (table_name, column_name) IN (('sessions', 'last_seen_at'), ('webhooks', 'org_grace_until'), ('recovery_codes', 'used_at'))").fetchall()}}
c.rollback()
print(json.dumps(out))
""")
check(set((old.get("turn") or {}).values()) == {"done"} and len(old.get("turn") or {}) == 5, f"older database: the five columns turn {old}")
check(old.get("codes") == [["rc5951a", "2026-03-01T10:00:00+00:00"], ["rc5951b", "2026-02-01T09:00:00+00:00"],
                           ["rc5951c", "2026-02-01T09:00:00+00:00"], ["rc5951d", None]],
      f"recovery codes fail closed: '' and a misfit stay used (the row's created_at), never NULL {old.get('codes')}")
check(old.get("left") == 1, f"only the never used code is left ({old.get('left')})")
check(old.get("toks") == [["tk5951a", None, False], ["tk5951b", "2026-02-01T09:00:00+00:00", True], ["tk5951c", "2099-01-01T00:00:00+00:00", False]],
      f"API tokens: '' stays 'never', a misfit end counts as ended, a real end stays {old.get('toks')}")
check(old.get("ses") == [["se5951a", "2026-02-01T09:00:00+00:00", None], ["se5951b", "2099-01-01T00:00:00+00:00", None]],
      f"sessions: '' expiry = its created_at (ended), last_seen_at '' = NULL {old.get('ses')}")
check(old.get("live") == ["se5951b"], f"the session check sees only the live one ({old.get('live')})")
check(old.get("hooks") == [["wh5951a", None], ["wh5951b", "2026-12-31"]], f"webhooks: grace '' = NULL, a day stays that day {old.get('hooks')}")
cols = old.get("cols") or {}
check(cols.get("sessions.last_seen_at") == ["timestamp with time zone", "YES", None] and cols.get("webhooks.org_grace_until") == ["date", "YES", None]
      and cols.get("recovery_codes.used_at") == ["timestamp with time zone", "YES", None], f"the types after the turn {cols}")

# ---- expired = refused (after the turn the comparisons run on TIMESTAMPTZ)
S2 = kt.sess("alice")
check(S2.get(B + "/api/state").ok, "a second session of alice works")
kt.dbx("UPDATE sessions SET expires_at=? WHERE user_id=? AND created_at=(SELECT MAX(created_at) FROM sessions WHERE user_id=?)",
       (iso(NOW - timedelta(minutes=1)), UID, UID))
check(S2.get(B + "/api/state").status_code == 401, "a session past its end is refused")
check(A.get(B + "/api/state").ok, "the other session goes on")
r = A.post(B + "/api/me/tokens", json={"name": "zz5951", "scopes": ["read"], "expires_days": 5})
tok, tid = (r.json().get("token"), r.json().get("id")) if r.ok else (None, None)
api = lambda: kt.sess().get(B + "/api/v1/me", headers={"Authorization": f"Bearer {tok}"})  # noqa: E731
check(bool(tok) and api().ok, f"an API token with an end works before it ({r.status_code})")
kt.dbx("UPDATE api_tokens SET expires_at=? WHERE id=?", (iso(NOW - timedelta(seconds=5)), tid))
r = api()
check(r.status_code == 401 and "expired" in r.text.lower(), f"an API token past its end is refused ({r.status_code} {r.text[:120]})")
kt.dbx("UPDATE api_tokens SET expires_at=NULL WHERE id=?", (tid,))
check(api().ok, "without an end it works again (NULL = never)")

# ---- the code that read these columns as text
ses_hash = "tch5951" + "0" * 57
kt.dbx("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES(?,?,?,?,NULL)",
       (ses_hash, UID, iso(NOW), iso(NOW + timedelta(days=1))))
code, err = py(f"""
from kalmido.accounts.sessions import ses_touch
from kalmido.admin.operator import _op_account
from kalmido.admin.hosting import org_activity
from kalmido.accounts.orginvite import OJN_PURGE_SQL
from kalmido.core.orgcrypt import rck_admin_gone
out = {{}}
ses_touch(c, '{ses_hash}')
out["touched"] = c.execute("SELECT last_seen_at IS NOT NULL FROM sessions WHERE token_hash=?", ('{ses_hash}',)).fetchone()[0]
def safe(k, fn):
    try:
        with c.savepoint():
            out[k] = fn()
    except Exception as e:
        out[k] = "error: " + type(e).__name__ + ": " + str(e)[:160]
safe("op", lambda: bool(_op_account(c, {UID})))
safe("act", lambda: isinstance(org_activity(c), (list, dict)))
safe("purge", lambda: c.execute(OJN_PURGE_SQL, ('2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00')).rowcount)
oid = c.execute("INSERT INTO orgs(name, created_at) VALUES('Theta 5951', now()) RETURNING id").fetchone()[0]
c.execute("INSERT INTO org_keys(org_id, wrapped, kek_check, created_at, recovery_shown_at) VALUES(?, 'x', 'x', now(), now())", (oid,))
safe("rck", lambda: rck_admin_gone(c, oid, {UID}))
c.execute("UPDATE org_keys SET rotated_at=now() WHERE org_id=?", (oid,))
safe("rck2", lambda: rck_admin_gone(c, oid, {UID}))
c.execute("INSERT INTO api_tokens(user_id, name, token_hash, prefix, scopes, expires_at, created_at) VALUES(?,?,?,?,?,?,?)", ({UID}, 'zzdel', 'del5951', 'del5951', 'read', '2026-05-01T10:00:00.5Z', '2026-02-01T09:00:00+00:00'))
safe("del", lambda: c.execute("DELETE FROM api_tokens WHERE token_hash='del5951'").rowcount)
out["exp"] = (c.execute("SELECT exp FROM revoked_creds WHERE hash='del5951'").fetchone() or [None])[0]
c.rollback()
print(json.dumps(out))
""")
check(code.get("touched") is True, f"the session touch writes over NULL (was '' < x) {code}")
check(code.get("op") is True and code.get("act") is True, f"the operator's numbers read last_seen_at on TIMESTAMPTZ {code}")
check(isinstance(code.get("purge"), int), f"the invitation purge runs on TIMESTAMPTZ used_at {code.get('purge')}")
check(code.get("rck") == 0 and code.get("rck2") == 0, f"the recovery-key showing check runs with and without a rotation (no '' against a time) {code}")
check(code.get("del") == 1 and code.get("exp") == "2026-05-01T10:00:00+00:00",
      f"a deleted API token: the trigger writes exp in the canonical form, no error on TIMESTAMPTZ {code}")

# ---- a retired organisation past its day goes, one still kept stays (orgs.retain_until DATE)
pr, err = py("""
from kalmido.accounts.orgretain import odl_retired_prune
import kalmido.accounts.orgretain as orr
oa = c.execute("INSERT INTO orgs(name, created_at, retired_at, retain_until) VALUES('Zeta 5951', now(), now(), '2020-12-31') RETURNING id").fetchone()[0]
ob = c.execute("INSERT INTO orgs(name, created_at, retired_at, retain_until) VALUES('Eta 5951', now(), now(), '2099-12-31') RETURNING id").fetchone()[0]
seen = []
real = orr.odl_dismantle
orr.ret_on = lambda kind: True
orr.odl_dismantle = lambda c, oid: seen.append(oid) or []
orr.odl_retention = lambda c, oid: {"counts": {}, "until": None}
odl_retired_prune(c, force=True)
orr.odl_dismantle = real
c.execute("DELETE FROM orgs WHERE id IN (?, ?)", (oa, ob))  # the prune commits: the two invented organisations go again
c.commit()
print(json.dumps({"seen": [x for x in seen if x in (oa, ob)], "oa": oa, "ob": ob}))
""")
check(pr.get("seen") == [pr.get("oa")], f"only the organisation past its day is dismantled {pr}")

# ---- review (#5951): an organisation held / retired with '' or a text that is no time stays held / retired (CT_D2_CLOSED "all")
og, err = py("""
import kalmido.core.coltype as ct
from kalmido.core.coltype import ct_iso
c.execute("ALTER TABLE orgs ALTER COLUMN ret_hold_at TYPE TEXT USING " + ct_iso("ret_hold_at") + ", ALTER COLUMN retired_at TYPE TEXT USING " + ct_iso("retired_at"))
o1 = c.execute("INSERT INTO orgs(name, created_at, ret_hold_at, retired_at) VALUES('Iota 5951', '2026-02-01T09:00:00+00:00', '', 'gone') RETURNING id").fetchone()[0]
o2 = c.execute("INSERT INTO orgs(name, created_at, ret_hold_at, retired_at) VALUES('Kappa 5951', '2026-02-01T09:00:00+00:00', 'held', '') RETURNING id").fetchone()[0]
turn = {k: v for k, v in ct._ct_more(c, '2026-11-13T08:00:00+00:00').items() if k.startswith('orgs.')}
rows = [list(r) for r in c.execute("SELECT ret_hold_at, retired_at FROM orgs WHERE id IN (?, ?) ORDER BY id", (o1, o2)).fetchall()]
c.rollback()
print(json.dumps({"turn": turn, "rows": rows}))
""")
check((og.get("turn") or {}).get("orgs.ret_hold_at") == "done" and (og.get("turn") or {}).get("orgs.retired_at") == "done", f"orgs: the marks turn {og}")
# 2.1115.0 (#5951): review - '' / a misfit was NULL = lock off, organisation active again
check(og.get("rows") == [["2026-02-01T09:00:00+00:00"] * 2] * 2, f"orgs: '' and a misfit stay held / retired (the row's created_at) {og.get('rows')}")

# ---- review (#5951, F2): the two columns stay TEXT (a view blocks the ALTER): the prune keeps a retired organisation with
# retain_until '', the end of a webhook's grace writes NULL into the old TEXT NOT NULL DEFAULT '' column without an error
kp, err = py(f"""
import kalmido.core.coltype as ct
import kalmido.accounts.orgretain as orr
from kalmido.integrations.webhooks import wh_grace_ok
c.commit = lambda: None  # the prune commits; here everything is rolled back
c.execute("ALTER TABLE orgs ALTER COLUMN retain_until TYPE TEXT USING CAST(retain_until AS text)")
c.execute("ALTER TABLE webhooks ALTER COLUMN org_grace_until TYPE TEXT USING CAST(org_grace_until AS text), ALTER COLUMN org_grace_until SET DEFAULT ''")
c.execute("UPDATE webhooks SET org_grace_until='' WHERE org_grace_until IS NULL")
c.execute("ALTER TABLE webhooks ALTER COLUMN org_grace_until SET NOT NULL")
c.execute("CREATE VIEW zz5951kv AS SELECT o.retain_until, w.org_grace_until FROM orgs o, webhooks w")
turn = {{k: v for k, v in ct._ct_more(c, '2026-11-13T08:00:00+00:00').items() if k in ('orgs.retain_until', 'webhooks.org_grace_until')}}
oe = c.execute("INSERT INTO orgs(name, created_at, retired_at, retain_until) VALUES('Lambda 5951', now(), now() - interval '9 years', '') RETURNING id").fetchone()[0]
seen = []
orr.ret_on = lambda kind: True
orr.odl_dismantle = lambda c, oid: seen.append(oid) or []
orr.odl_retention = lambda c, oid: {{"counts": {{}}, "until": None}}
orr.odl_retired_prune(c, force=True)
wid = c.execute("INSERT INTO webhooks(user_id, name, url, events, secret, created_at, updated_at, org_grace_until) VALUES(?,?,?,?,?,now(),now(),'2020-01-01') RETURNING id", ({UID}, 'zz5951k', 'https://hooks.example.com/z', '', 'x')).fetchone()[0]
w = c.execute("SELECT * FROM webhooks WHERE id=?", (wid,)).fetchone()
try:
    with c.savepoint():
        ok = wh_grace_ok(c, w, None)
    grace = [ok, c.execute("SELECT org_grace_until FROM webhooks WHERE id=?", (wid,)).fetchone()[0]]
except Exception as e:
    grace = "error: " + type(e).__name__
c.rollback()
print(json.dumps({{"turn": turn, "seen": oe in seen, "grace": grace}}))
""")
check(kp.get("turn") == {"orgs.retain_until": "kept", "webhooks.org_grace_until": "kept"}, f"kept: both stay TEXT {kp}")
check(kp.get("seen") is False, f"kept: a retired organisation with retain_until '' is never dismantled {kp}")
check(kp.get("grace") == [False, None], f"kept: the end of a webhook's grace writes NULL on the TEXT column, no error {kp}")

# ---- the end of a webhook's grace writes NULL (was ''), the recovery-key showing check runs without a rotation
wh, err = py(f"""
from kalmido.integrations.webhooks import wh_grace_ok
wid = c.execute("INSERT INTO webhooks(user_id, name, url, events, secret, created_at, updated_at, org_grace_until) VALUES(?,?,?,?,?,now(),now(),'2020-01-01') RETURNING id", ({UID}, 'zz5951', 'https://hooks.example.com/y', '', 'x')).fetchone()[0]
w = c.execute("SELECT * FROM webhooks WHERE id=?", (wid,)).fetchone()
ok = wh_grace_ok(c, w, None)
after = c.execute("SELECT org_grace_until FROM webhooks WHERE id=?", (wid,)).fetchone()[0]
w2 = c.execute("SELECT * FROM webhooks WHERE id=?", (wid,)).fetchone()
again = wh_grace_ok(c, w2, None)
c.rollback()
print(json.dumps({{"ok": ok, "after": after, "again": again}}))
""")
check(wh.get("ok") is False and "after" in wh and wh["after"] is None and wh.get("again") is False,
      f"a grace past its day ends for good: NULL, no second end {wh}")

sys.exit(kt.done("p21115_d2_access_coltime"))
