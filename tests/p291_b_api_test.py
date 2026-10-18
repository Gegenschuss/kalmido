#!/usr/bin/env python3
"""2.91.0 API tests, part B (#1924): subscriptions and tools in the office, own container (start.sh, org encryption on).
Invented companies, people and figures only.
 - the subscription fields of a fixed cost (sub, notice_days, seats, low_use, remind_days, remind_user, url) through the
   existing routes POST / PATCH /api/office/fixed-costs: checked (ranges, people of the area only, the reminder person an
   office admin, http(s) only, control characters out), a client without the new fields works as before
 - computed: next_renewal (the 31st -> the month's last day, quarterly, yearly, once), cancel_by, per_month / per_year gross
   and net; GET /api/office/subs: only sub = 1, sorted by the last day to cancel, totals + saving of the hardly used ones,
   candidates (software / small repeating amounts, never rent), people; the CSV (cells safe against formulas)
 - the cash flow counts a subscription once (as a fixed cost)
 - the reminder (watchdog): one task in the inbox of the person within remind_days before the last day to cancel, never an
   amount in the title, only once; none for a later window
 - the import takes the optional columns "Abo" / "Kündigungsfrist"
 - rights (tenant-matrix: office): a member 403, another organisation 404 / 400 for its people, an agent 403; a person
   without an organisation (freelancer-matrix: office) has the full view in the personal office, only themself as user
usage: p291_b_api_test.py <datadir>      (P291B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import calendar
import csv
import io
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def nxt(start, step, today):
    """The next due day on or after today (the reference for next_renewal; the 31st -> the month's last day)."""
    y, m, d = int(start[:4]), int(start[5:7]), int(start[8:10])
    i = 0
    while True:
        mm = m - 1 + i * step
        yy, mo = y + mm // 12, mm % 12 + 1
        day = date(yy, mo, min(d, calendar.monthrange(yy, mo)[1]))
        if day >= today:
            return day.isoformat()
        i += 1


def year_back(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def xlsx(rows):
    def cell(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
    data = "".join(f'<row r="{i + 1}">' + "".join(cell(f"{chr(65 + j)}{i + 1}", v) for j, v in enumerate(r) if v != "") + "</row>" for i, r in enumerate(rows))
    ns = "http://schemas.openxmlformats.org"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", f'<?xml version="1.0"?><Types xmlns="{ns}/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{ns}/spreadsheetml/2006/main" xmlns:r="{ns}/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Fixkosten" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{ns}/package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="{ns}/spreadsheetml/2006/main"><sheetData>{data}</sheetData></worksheet>')
    return buf.getvalue()


if os.environ.get("P291B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
FEAT = "cal,comments,collab,office,clients,agents"
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
me = lambda s: s.get(B + "/api/state").json()["me"]["id"]  # noqa: E731
ALICE, BOB, CAROL, DORA = me(A), me(Bo), me(Ca), me(Do)
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
F = "/api/office/fixed-costs"
SU = "/api/office/subs"
T0 = testclock.today()
TODAY = T0.isoformat()


def post(s, **kw):
    b = {"label": "X", "amount": 10, "start": TODAY, "repeat": "monthly"}
    b.update(kw)
    return s.post(B + F, json=b)


# ---------------------------------------------------------------- an old client: the fixed cost as before
r = post(A, label="Miete", amount=1200, vat_rate=0)
check(r.status_code == 201, "an old client creates a fixed cost without the new fields " + r.text[:200])
RENT = r.json()
check(all(k in RENT for k in ("id", "label", "amount", "start", "until", "repeat", "category", "vat_rate", "gross")), "all old fields are still there")
check(RENT["sub"] == 0 and RENT["notice_days"] == 0 and RENT["seats"] == [] and RENT["low_use"] == 0 and RENT["remind_user"] is None and RENT["url"] == "",
      f"the new fields default to off {RENT}")
check(RENT["per_month"] == "1200.00" and RENT["per_year"] == "14400.00", f"per month / year of a monthly cost {RENT['per_month']} {RENT['per_year']}")
check(A.patch(B + f"{F}/{RENT['id']}", json={"label": "Büromiete"}).json()["sub"] == 0, "a PATCH of the label leaves sub alone")

# ---------------------------------------------------------------- the subscriptions
S1 = post(A, label="Design Suite", amount=50, vat_rate=19, start="2026-01-31", category="Software", sub=1, seats=[ALICE, BOB, " Freie\x07 Kraft "],
          url="https://example.com/design", notice_days=0).json()
check(S1.get("sub") == 1 and S1["seats"] == [ALICE, BOB, "Freie Kraft"], f"a subscription with users (people + a free name, control characters out) {S1}")
check(S1["next_renewal"] == nxt("2026-01-31", 1, T0), f"next_renewal of a monthly cost on the 31st = the month's last day {S1['next_renewal']}")
check(S1["cancel_by"] == "", "no notice period = no cancel_by")
check((S1["per_month"], S1["per_year"], S1["per_month_net"], S1["per_year_net"]) == ("59.50", "714.00", "50.00", "600.00"), f"monthly normed gross + net {S1}")
S2 = post(A, label="Cloud Storage", amount=30, vat_rate=0, repeat="quarterly", sub=1, low_use=1).json()
check(S2["next_renewal"] == TODAY and (S2["per_month"], S2["per_year"]) == ("10.00", "120.00"), f"quarterly: /3 a month, x4 a year {S2}")
REN = T0 + timedelta(days=40)
S3 = post(A, label="Domain", amount=120, vat_rate=19, repeat="yearly", start=year_back(REN).isoformat(), sub=1, notice_days=30, remind_days=14, remind_user=ALICE).json()
check(S3["next_renewal"] == REN.isoformat(), f"yearly: the renewal this year {S3['next_renewal']} {REN}")
check(S3["cancel_by"] == (REN - timedelta(days=30)).isoformat(), f"cancel_by = renewal - notice period {S3['cancel_by']}")
check((S3["per_month"], S3["per_year"]) == ("11.90", "142.80"), f"yearly: /12 a month, x1 a year {S3}")
S4 = post(A, label="Setup Service", amount=100, repeat="once", start=(T0 + timedelta(days=5)).isoformat(), sub=1).json()
check(S4["next_renewal"] == (T0 + timedelta(days=5)).isoformat() and (S4["per_month"], S4["per_year"]) == ("0.00", "0.00"), f"once: its start, 0 a month / year {S4}")
S5 = post(A, label="Later Tool", amount=5, repeat="yearly", start=year_back(T0 + timedelta(days=60)).isoformat(), sub=1, notice_days=30, remind_days=5, remind_user=ALICE).json()
check(S5["cancel_by"] == (T0 + timedelta(days=30)).isoformat(), "a second reminder further away")

# validation
bad = [({"notice_days": 731}, "notice_days 731"), ({"notice_days": -1}, "notice_days -1"), ({"notice_days": "abc"}, "notice_days text"), ({"notice_days": 1.5}, "notice_days 1.5"),
       ({"remind_days": 91}, "remind_days 91"), ({"sub": 2}, "sub 2"), ({"low_use": "x"}, "low_use x"), ({"url": "javascript:alert(1)"}, "url javascript:"),
       ({"url": "https://example.com/" + "a" * 500}, "url too long"), ({"seats": "x"}, "seats no list"), ({"seats": list(range(41))}, "41 seats"),
       ({"seats": [CAROL]}, "a person of another organisation as user"), ({"seats": [999999]}, "an unknown person as user"), ({"seats": [True]}, "seat true"),
       ({"remind_user": BOB}, "the reminder for a member who is no office admin"), ({"remind_user": CAROL}, "the reminder for a person of another organisation")]
for b, what in bad:
    check(A.patch(B + f"{F}/{S1['id']}", json=b).status_code == 400, f"400: {what}")
r = A.patch(B + f"{F}/{S1['id']}", json={"seats": [ALICE, "N" * 100]})
check(r.ok and r.json()["seats"] == [ALICE, "N" * 80], "a free name is cut to 80 characters")
check(A.patch(B + f"{F}/{S1['id']}", json={"seats": [ALICE, BOB, "Freie Kraft"]}).ok, "users back")
check(A.patch(B + f"{F}/{S1['id']}", json={"url": ""}).json()["url"] == "" and A.patch(B + f"{F}/{S1['id']}", json={"url": "https://example.com/design"}).ok, "url cleared and set")

# candidates: software / a small repeating amount; never rent or insurance, never one already marked
C1 = post(A, label="Notizen App", amount=4, vat_rate=19, category="Tools").json()
C2 = post(A, label="Haftpflichtversicherung", amount=20, repeat="yearly", category="Versicherungen").json()
C3 = post(A, label="Schnittplatz Lizenz", amount=300, repeat="yearly", category="Lizenzen").json()

v = A.get(B + SU)
check(v.status_code == 200, "GET subs " + v.text[:200])
v = v.json()
ids = [f["id"] for f in v["items"]]
check(set(ids) == {S1["id"], S2["id"], S3["id"], S4["id"], S5["id"]}, f"only sub = 1 rows {ids}")
check(ids.index(S3["id"]) < ids.index(S5["id"]) and ids[-1] == S4["id"], f"sorted by the last day to cancel / renewal, ended ones last {ids}")
t = v["totals"]
exp_m = 59.50 + 10 + 11.90 + round(5 / 12, 2)
check(abs(float(t["per_month"]) - exp_m) < 0.011 and float(t["per_year"]) == 714 + 120 + 142.80 + 5, f"totals per month / year (gross) {t}")
check(float(t["per_year_net"]) == 600 + 120 + 120 + 5, f"totals per year (net) {t}")
check(t["low_use_per_year"] == "120.00" and t["low_use_count"] == 1 and t["count"] == 4, f"the hardly used: count + saving a year; once not counted {t}")
cand = {c["id"] for c in v["candidates"]}
check(C1["id"] in cand and C3["id"] in cand, f"candidates: a small tool and a licence {cand}")
check(RENT["id"] not in cand and C2["id"] not in cand and S1["id"] not in cand, f"no rent, no insurance, nothing already marked {cand}")
check(sql("SELECT sub FROM office_fixed_costs WHERE id=?", (C1["id"],))[0][0] == 0, "a candidate is never marked by itself")
ppl = {p["id"] for p in v["people"]}
check(ppl == {ALICE, BOB}, f"people: the members of the organisation {ppl}")
check({p["id"] for p in v["remind_people"]} == {ALICE}, "reminder people: the office admins")
it1 = next(f for f in v["items"] if f["id"] == S1["id"])
check(it1["seat_names"] == ["Alice Admin", "Bob Member", "Freie Kraft"], f"seat names {it1['seat_names']}")
check(str(sql("SELECT amount FROM office_fixed_costs WHERE id=?", (S1["id"],))[0][0]).startswith("kenc1:"), "the amount stays encrypted at rest")

# the fixed costs list shows the same rows (no second list)
fl = {f["id"]: f for f in A.get(B + F).json()["items"]}
check(fl[S1["id"]]["sub"] == 1 and fl[RENT["id"]]["sub"] == 0, "the fixed costs list carries the subscription mark")

# cash flow: a subscription counts once, as a fixed cost
cf = A.get(B + f"/api/office/cashflow?from={TODAY[:7]}&months=3").json()
e1 = [e for e in cf["entries"] if e.get("fixed_id") == S1["id"]]
check(len(e1) == len({e["month"] for e in e1}) and len(e1) >= 2 and all(e["kind"] == "fixed" for e in e1), f"cash flow: one fixed entry per month for a subscription {e1}")
check(not [e for e in cf["entries"] if e.get("kind") not in ("fixed", "payment", "invoice", "offer", "purchase", "trip", "credit", "series")], "no new entry kind for subscriptions")

# CSV safe against formulas
INJ = post(A, label="=HYPERLINK(\"https://example.com\")", amount=1, sub=1, seats=["+Formel"]).json()
r = A.get(B + SU + ".csv")
check(r.status_code == 200 and "text/csv" in r.headers.get("Content-Type", ""), "the CSV")
rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
inj = [x for x in rows if "HYPERLINK" in x[0]]
check(inj and inj[0][0].startswith("'=") and inj[0][10].startswith("'+"), f"CSV: formulas defused {inj}")
check(len(rows) == 1 + 6, f"CSV: a header and one row per subscription {len(rows)}")
A.delete(B + f"{F}/{INJ['id']}")

# ---------------------------------------------------------------- the reminder (watchdog)
def rtasks():
    return [dict(zip(("title", "due", "url", "assignee_id", "content"), r)) for r in
            sql("SELECT title, due, url, assignee_id, content FROM tasks WHERE title LIKE 'Check subscription:%' AND deleted_at IS NULL")]


got = until(lambda: rtasks(), 45)
check(len(got) == 1 and got[0]["title"] == "Check subscription: Domain", f"one reminder task for the near deadline {[x['title'] for x in got]}")
if got:
    g0 = got[0]
    check((g0.get("due") or "")[:10] == S3["cancel_by"], f"due on the last day to cancel {g0.get('due')}")
    check("120" not in g0["title"] and "142" not in g0["title"], "no amount in the title")
    check("#office/subs" in (g0.get("url") or ""), "a link to the view")
    check(g0.get("assignee_id") == ALICE, "assigned to the person")
    check("Cancel or keep?" in (g0.get("content") or ""), "the text asks: cancel or keep")
time.sleep(12)
check(len(rtasks()) == 1, "only once (also after the next round)")
rm = sql("SELECT fixed_id, due, task_id, user_id FROM office_sub_reminders")
check(len(rm) == 1 and rm[0][0] == S3["id"] and rm[0][1] == S3["cancel_by"] and rm[0][3] == ALICE, f"the marker row {rm}")
A.patch(B + f"{F}/{S3['id']}", json={"remind_days": 0})
check(len(rtasks()) == 1, "switching the reminder off keeps the task")

# ---------------------------------------------------------------- import with the optional columns
raw = xlsx([["Name", "Betrag (netto)", "fällig Monat", "Abo", "Kündigungsfrist"], ["Kalender Pro", 9.9, 0, "ja", 30], ["Strom", 80, 0, "", ""],
            ["Falsch", 5, 0, "ja", 999]])
pv = A.post(B + F + "/import/preview", files={"file": ("f.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
check(pv.ok, "import preview " + pv.text[:200])
pr = {x["label"]: x for x in pv.json()["rows"]}
check(pr["Kalender Pro"]["sub"] == 1 and pr["Kalender Pro"]["notice_days"] == 30 and pr["Strom"]["sub"] == 0, f"preview reads Abo + notice period {pr.get('Kalender Pro')}")
check(pr["Falsch"]["status"] == "error", "a notice period above 730 days is an error row")
im = A.post(B + F + "/import", json={"items": [{k: pr["Kalender Pro"][k] for k in ("label", "amount", "repeat", "start", "category", "vat_rate", "sub", "notice_days")}]})
check(im.status_code == 201, "import " + im.text[:200])
if im.ok:
    k = {f["id"]: f for f in A.get(B + F).json()["items"]}[im.json()["ids"][0]]
    check(k["sub"] == 1 and k["notice_days"] == 30, "the imported row is a subscription with its notice period")
    check(A.post(B + F + "/import", json={"items": [{"label": "Y", "amount": 1, "repeat": "monthly", "start": TODAY, "notice_days": 999}]}).status_code == 400, "import: a bad notice period 400")

# ---------------------------------------------------------------- rights (tenant-matrix: office)
check(Bo.get(B + SU).status_code == 403 and Bo.get(B + SU + ".csv").status_code == 403, "a member: 403")
check(Bo.patch(B + f"{F}/{S1['id']}", json={"low_use": 1}).status_code == 403, "a member cannot change a subscription")
cv = Ca.get(B + SU).json()
check(cv["items"] == [] and {p["id"] for p in cv["people"]} == {CAROL}, "another organisation sees none of it")
check(Ca.patch(B + f"{F}/{S1['id']}", json={"low_use": 1}).status_code == 404, "another organisation: 404 for a foreign row")
check(post(Ca, sub=1, seats=[ALICE]).status_code == 400 and post(Ca, sub=1, remind_user=ALICE).status_code == 400, "another organisation cannot use our people (400)")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"})
check(ag.status_code == 201, "an agent " + ag.text[:200])
if ag.ok:
    r = requests.get(B + SU, headers={**H, "Authorization": "Bearer " + ag.json()["token"]})
    check(r.status_code in (401, 403), f"an agent: refused {r.status_code}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
check(Do.get(B + "/api/office/settings").json().get("role") == "admin", "a freelancer is admin of the personal office")
r = post(Do, label="Schnitt Software", amount=25, vat_rate=19, sub=1, seats=[DORA, "Assistenz"], remind_user=DORA, remind_days=7, notice_days=14)
check(r.status_code == 201 and r.json()["seats"] == [DORA, "Assistenz"], "freelancer: a subscription with themself as user " + r.text[:200])
check(post(Do, sub=1, seats=[ALICE]).status_code == 400, "freelancer: a person of an organisation is no user (400)")
check(post(Do, sub=1, remind_user=ALICE).status_code == 400, "freelancer: the reminder only for themself")
dv = Do.get(B + SU).json()
check([f["label"] for f in dv["items"]] == ["Schnitt Software"] and dv["totals"]["per_month"] == "29.75", f"freelancer: own view + totals {dv['totals']}")
check([p["id"] for p in dv["people"]] == [DORA] and [p["id"] for p in dv["remind_people"]] == [DORA], "freelancer: only themself")
check(not any(f["label"] == "Schnitt Software" for f in A.get(B + SU).json()["items"]), "the organisation does not see the personal office")

# delete: the row goes, its reminder marker with it, the task stays
check(A.delete(B + f"{F}/{S3['id']}").ok, "delete a subscription")
check(len(rtasks()) == 1, "the task made stays after the row is deleted")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
