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

sys.exit(done("p2566_b_bump"))
