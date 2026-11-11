#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.566.0 B (#4706) API test: the write routes that forgot the version tick (bump) move their area counter of
/api/version now, so other devices reload. Own container (start.sh, mode workspaces). Invented names only.
freelancer-matrix: office
 - office: the settings, a master data row (create / change / delete), the import, a bank account, the letterhead
   switches -- each moves "office" exactly once (no double tick from the after-hook)
 - the after-hook of the core (core/db.py lv_auto_bump): a write route of a registered area without its own bump (the
   office rights groups) still moves "office" once; a reading request moves nothing
 - other areas: a new table ("sheets"), a calendar subscription's name / colour ("calendar"), the wiki reading style
   ("wiki"), a bookmark change ("other")
 - a person without an organisation (personal office): settings and bank account the same
usage: p2566_b_bump_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, done, fresh, sess, setup, until  # noqa: E402

O, BA = "/api/office", "/api/office/settings/bank-accounts"
FEAT = {"features": "cal,comments,collab,office,clients,docs,sheets,wiki,events", "lang": "en", "tour": "done"}

fresh({"KALMIDO_INSTANCE_MODE": "workspaces"})
A = setup()
ME = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ME}", json={"email": "alice@example.com"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ME}).json()["id"]
assert A.patch(B + "/api/settings", json={**FEAT, "workspace": f"org:{ORG}"}).ok
Ob = sess("alice")  # the other device of the same person: it reads the counters


def areas():
    r = Ob.get(B + "/api/version")
    assert r.ok, r.text
    return r.json()["a"]


def moved(area, fn, what, exact=1):
    """fn() writes; the counter of area must move by exactly `exact` (None: at least one)."""
    a0 = areas().get(area, 0)
    r = fn()
    a1 = areas().get(area, 0)
    ok = r.status_code < 400 and (a1 - a0 == exact if exact is not None else a1 > a0)
    check(ok, f"#4706 {what}: '{area}' {a0} -> {a1} ({r.status_code} {r.text[:200]})")
    return r


# ================================================================ office core (web.py)
moved("office", lambda: A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel"}, "currency": "EUR"}),
      "office settings PUT")
r = moved("office", lambda: A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "category": "Video", "daily_rate": 800}),
          "master data row POST")
SID = r.json().get("id") if r.ok else 0
moved("office", lambda: A.patch(B + O + f"/services/{SID}", json={"daily_rate": 900}), "master data row PATCH")
moved("office", lambda: A.delete(B + O + f"/services/{SID}"), "master data row DELETE")
moved("office", lambda: A.post(B + O + "/import", json={"kalmido_office": 1, "services": [
    {"name_de": "Ton", "name_en": "Sound", "category": "Audio", "daily_rate": 500}]}), "master data import")

# ================================================================ single office routes
r = moved("office", lambda: A.post(B + BA, json={"iban": "DE02120300000000202051", "label": "Haupt"}), "bank account POST")
AID = (r.json().get("account") or {}).get("id") if r.ok else 0
moved("office", lambda: A.put(B + BA + f"/{AID}", json={"label": "Hauptkonto"}), "bank account PUT")
moved("office", lambda: A.put(B + O + "/letterhead", json={"hide_footer": False}), "letterhead margins / switches PUT")
moved("office", lambda: A.put(B + O + "/letterhead", json={"hide_footer": False}), "letterhead PUT without a change", exact=0)

# ================================================================ 2.937.0 (#5632): the delete / restore routes on the core's trash
# (obj_trash ticks itself; a loop of rows or a route's own bump after it must not add a second tick)
FX = {"label": "Miete", "amount": 500, "start": "2026-01-01", "repeat": "monthly"}
r = A.post(B + O + "/fixed-costs", json=FX)
check(r.status_code == 201, f"#5632 setup: fixed cost ({r.status_code} {r.text[:200]})")
F1 = r.json().get("id") if r.ok else 0
moved("office", lambda: A.delete(B + O + f"/fixed-costs/{F1}"), "#5632 fixed cost DELETE (core trash)")
moved("office", lambda: A.post(B + O + f"/trash/core/ofixed/{F1}/restore"), "#5632 fixed cost restore from the core's trash")
F2 = A.post(B + O + "/fixed-costs", json={**FX, "label": "Strom"}).json().get("id")
moved("office", lambda: A.post(B + O + "/fixed-costs/delete", json={"ids": [F1, F2]}), "#5632 fixed costs delete many (loop of obj_trash)")
r = A.post(B + O + "/cashflow/adjust", json={"month": "2026-03", "dir": "in", "amount": 100})
check(r.status_code == 201, f"#5632 setup: correction ({r.status_code} {r.text[:200]})")
moved("office", lambda: A.delete(B + O + f"/cashflow/adjust/{r.json().get('id')}"), "#5632 cash flow correction DELETE")
r = A.post(B + O + "/rights/groups", json={"name": "Wegdamit"})
moved("office", lambda: A.delete(B + O + f"/rights/groups/{r.json().get('id')}"), "#5632 rights group DELETE")

# ================================================================ the after-hook of the core
moved("office", lambda: A.post(B + O + "/rights/groups", json={"name": "Schnittteam"}), "after-hook: rights group POST (no bump of its own)")
moved("office", lambda: A.get(B + O + "/settings"), "a reading request", exact=0)

# ================================================================ other areas
moved("sheets", lambda: A.post(B + "/api/sheets", json={"title": "Drehplan", "space": f"org:{ORG}"}), "new table (sh_create)")
moved("wiki", lambda: A.put(B + "/api/wiki/style", json={"space": f"org:{ORG}", "style": "book"}), "wiki reading style PUT")

c = dbxm.connect(os.path.join(DATA, "tasks.db"))
try:  # a subscription as the sync leaves it (no calendar server in this suite; name / colour need none)
    CS = c.execute("INSERT INTO cal_subs(user_id, kind, name, url, status, created_at) VALUES(?, 'ics', 'Feiertage', 'x', 'ok', "
                   "'2026-11-05T10:00:00Z') RETURNING id", (ME,)).fetchone()[0]
    c.commit()
finally:
    c.close()
moved("calendar", lambda: A.patch(B + f"/api/calendars/{CS}", json={"name": "Ferien", "color": "#f472b6"}), "calendar subscription name / colour")
moved("calendar", lambda: A.delete(B + f"/api/calendars/{CS}"), "calendar subscription DELETE")

FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/beispiel", "title": "Beispiel"})
check(r.status_code == 201, f"setup: a bookmark ({r.status_code} {r.text[:200]})")
BM = r.json()["bookmark"]["id"] if r.ok else 0
until(lambda: (Fr.get(B + f"/api/bookmarks/{BM}").json() or {}).get("preview") != "pending", 20)  # the preview fetch is done
moved("other", lambda: Fr.patch(B + f"/api/bookmarks/{BM}", json={"note": "Notiz"}), "bookmark PATCH", exact=None)

# ================================================================ a person without an organisation
moved("office", lambda: Fr.put(B + O + "/settings", json={"company": {"name": "Frida"}, "currency": "EUR"}), "personal office: settings PUT")
moved("office", lambda: Fr.post(B + BA, json={"iban": "DE89370400440532013000"}), "personal office: bank account POST")

r = Fr.post(B + O + "/fixed-costs", json=FX)
check(r.status_code == 201, f"#5632 setup: personal fixed cost ({r.status_code} {r.text[:200]})")
moved("office", lambda: Fr.delete(B + O + f"/fixed-costs/{r.json().get('id')}"), "#5632 personal office: fixed cost DELETE")

# ================================================================ 2.937.0 (#5632, Fable F10): a rolled-back tick does not count
# bump's "once per request" ended only with a commit: a first tick inside a savepoint that rolls back hid the next one
F10 = r"""
import json
from flask import g
from kalmido.core.config import app
from kalmido.core.db import bump, db
from kalmido.core.pg import system_ctx
with app.test_request_context("/api/office/x"):
    g.user = None
    c = db()
    with system_ctx(c):
        v = lambda: int((c.execute("SELECT value FROM settings WHERE key='version:office'").fetchone() or ["0"])[0])
        a0 = v()
        try:
            with c.savepoint():
                bump(c, "office")
                raise KeyError
        except KeyError:
            pass
        a1 = v()
        bump(c, "office")
        a2 = v()
        bump(c, "office")
        a3 = v()
    c.rollback()
    print(json.dumps([a0, a1, a2, a3]))
"""
import json  # noqa: E402
import subprocess  # noqa: E402
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
x = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", F10], capture_output=True, text=True)
try:
    got = json.loads(x.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = (x.stdout + x.stderr)[-600:]
check(isinstance(got, list) and got[1] == got[0] and got[2] == got[0] + 1 and got[3] == got[2],
      f"#5632 F10: a tick rolled back with its savepoint -> the next bump of the request counts, a third does not {got}")

sys.exit(done("p2566_b_bump"))
