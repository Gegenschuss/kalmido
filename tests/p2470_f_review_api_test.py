#!/usr/bin/env python3
"""2.47.0 API tests, review follow-ups (#1216 / #1215 / #1649), own container in mode workspaces (start.sh).
Invented crew, services and amounts only.
 - a shoot part: the cached part totals hold no purchase, markup or intern / extern per line (not in the database row,
   not in the answer for a member); the member's sheet has no intern / extern; the admin still sees the purchase;
   a sent quotation prints its shoot part from the cache
 - invoice from a quotation with parts and a percent position (artists' social insurance) in a part with quantity 2
   and a part discount: net / gross = the quotation's in the modes full / title / summary; full: the percent position
   is its amount x the part quantity
 - a part with quantity 0 on the title page adds no positions to the invoice; sort nan / inf -> 400
usage: p2470_f_review_api_test.py <datadir>"""
import io
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
D = "/api/office/docs"
FAILS, OKS = [], [0]
INTERNAL = ("cost", "markup_pct", "intext")


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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def pdf_text(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


def svc(title, qty, rate, intext="intern", unit="day", disc=1):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": intext, "cost": 0, "discountable": disc}


def shoot(doc):
    return next((p for p in doc.get("parts") or [] if p.get("kind") == "shoot"), None)


def leaks(lines):
    return [k for ln in lines or [] if isinstance(ln, dict) for k in INTERNAL if k in ln]


# ---------------------------------------------------------------- setup: Alpha (alice admin, bob member)
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ids = {u: i for u, i in dbx("SELECT username, id FROM users")}
Bo = sess("bob")
for s_ in (A, Bo):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member') ON CONFLICT DO NOTHING", (ORG, ids["bob"]))
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + "/api/office/settings", json={"industry_packs": ["film"]}).ok, "industry pack Film & Video on")

# ---------------------------------------------------------------- #1216: the purchase of a shoot part stays internal
lig = A.post(B + "/api/office/crew", json={"name_de": "Beleuchter", "name_en": "Lighting", "rate_day": 350, "intext": "extern", "markup_pct": 10}).json()
DOC = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Shoot"}).json()["id"]
r = A.post(B + f"{D}/{DOC}/parts", json={"kind": "shoot", "title": "Shooting"})
check(r.status_code in (200, 201), "shoot part " + r.text[:200])
PS = (r.json().get("part") or shoot(r.json()) or {}).get("id")
r = A.patch(B + f"{D}/{DOC}/parts/{PS}", json={"sheet": {"head": {"shoot_days": 2, "travel_days": 0, "prep_days": 0, "nights": 0},
                                                         "producing": {"on": 0}, "meals_on": 0,
                                                         "staff": [{"role_id": lig["id"], "qty": 1, "prep": 0}],
                                                         "extras": [{"name": "Car", "qty": 1, "rate": 100, "intext": "extern", "markup_pct": 20}]}})
check(r.ok, "sheet saved " + r.text[:200])
adm = shoot(A.get(B + f"{D}/{DOC}").json()) or {}
check(float(adm.get("calc", {}).get("costs") or 0) == 800 and float(adm.get("totals", {}).get("costs") or 0) == 800,
      f"admin: purchase 2 x 350 + 100 = 800 {adm.get('calc', {}).get('costs')} {adm.get('totals', {}).get('costs')}")
check(float(adm.get("totals", {}).get("net") or 0) == 890, f"net 2 x 385 + 120 = 890 {adm.get('totals', {}).get('net')}")
check(not leaks(adm.get("totals", {}).get("lines")), f"admin answer: the cached part lines carry no purchase either {leaks(adm.get('totals', {}).get('lines'))}")
raw = dbx("SELECT totals FROM office_doc_parts WHERE id=?", (PS,))[0][0] or ""
tot = json.loads(raw) if raw.startswith("{") else {}
check(tot and not leaks(tot.get("lines")) and not leaks((tot.get("sheet_calc") or {}).get("lines")),
      f"database: the cached totals have no purchase / markup / intern-extern per line {leaks(tot.get('lines'))}")
check('"markup_pct"' not in raw and '"intext"' not in raw and '"cost"' not in raw, "database: no markup / intext / cost key in the totals")
mem = shoot(Bo.get(B + f"{D}/{DOC}").json()) or {}
check(mem and "costs" not in mem.get("totals", {}) and "margin" not in mem.get("totals", {}), f"member: no purchase / surplus in totals {list(mem.get('totals', {}))}")
check(mem and not leaks(mem.get("totals", {}).get("lines")) and not leaks(mem.get("calc", {}).get("lines")),
      "member: no purchase / markup / intern-extern per line")
sh = mem.get("sheet") or {}
check(sh.get("staff") and not any(k in r_ for r_ in (sh.get("staff") or []) + (sh.get("extras") or []) for k in ("intext", "markup_pct")),
      f"member: the sheet without intern / extern and markup {sh.get('staff')} {sh.get('extras')}")
# a sent quotation prints its shoot part from the cached (public) calculation
A.post(B + f"{D}/{DOC}/status", json={"status": "sent"})
r = A.get(B + f"{D}/{DOC}/pdf")
check(r.ok and r.content[:4] == b"%PDF", f"sent quotation with a shoot part: PDF {r.status_code}")
txt = pdf_text(r.content) if r.ok else None
if txt is not None:
    check("Lighting" in txt and "Car" in txt, "PDF of the sent quotation: the shoot rows from the cache")

# ---------------------------------------------------------------- #1649 / #1215: percent position in a part, invoice = quotation
r = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "KSK", "items": [svc("Concept", 1, 800)]})
DOC2 = r.json()["id"]
PA = A.post(B + f"{D}/{DOC2}/parts", json={"title": "Shoot day"}).json()["part"]["id"]
ksk = {**svc("Artists' social insurance", 1, 5, unit="percent"), "intext": "intern"}
r = A.put(B + f"{D}/{DOC2}/parts/{PA}/items", json={"items": [svc("Camera", 1, 1000, intext="extern"), ksk]})
check(r.ok and r.json()["part"]["totals"]["net"] == 1050, f"part A: 1000 + 5 % = 1050 {r.text[:200]}")
PB = A.post(B + f"{D}/{DOC2}/parts", json={"title": "Edit"}).json()["part"]["id"]
r = A.put(B + f"{D}/{DOC2}/parts/{PB}/items", json={"items": [svc("Editing", 1, 3000, intext="extern")]})
items = r.json()["items"]
for it in items:
    if it.get("kind") == "part" and it.get("ref_part_id") == PA:
        it["qty"] = 2
r = A.put(B + f"{D}/{DOC2}/items", json={"items": items})
check(r.ok and r.json()["totals"]["net"] == 5900, f"title page: 800 + 2 x 1050 + 3000 = 5900 {r.text[:200]}")


def invoices(label, ksk_amount):
    off = A.get(B + f"{D}/{DOC2}").json()["totals"]
    for mode in ("full", "title", "summary"):
        r = A.post(B + f"{D}/{DOC2}/invoice", json={"parts_mode": mode})
        check(r.status_code == 201, f"{label}: invoice {mode} " + r.text[:200])
        if r.status_code != 201:
            continue
        it = r.json()
        check(abs(float(it["totals"]["net"]) - off["net"]) < 0.005 and abs(float(it["totals"]["gross"]) - off["gross"]) < 0.005,
              f"{label}: invoice {mode} net / gross = the quotation's ({it['totals'].get('net')} / {it['totals'].get('gross')} vs {off['net']} / {off['gross']})")
        if mode == "full":
            k = [x for x in it["items"] if x.get("title") == "Artists' social insurance"]
            check(len(k) == 1 and k[0]["unit"] == "flat" and float(k[0]["qty"]) == 2 and abs(float(k[0]["rate"]) - ksk_amount) < 0.005,
                  f"{label}: full: the percent position as its amount x 2 {[(x['unit'], x['qty'], x['rate']) for x in k]}")
        A.delete(B + f"{D}/{it['id']}")


invoices("KSK", 50)
# a part discount over the percent position: discountable lines count with their amount (10 % of 1000 + 50)
r = A.patch(B + f"{D}/{DOC2}/parts/{PA}", json={"settings": {"discount_pct": 10}})
check(r.ok and A.get(B + f"{D}/{DOC2}").json()["totals"]["net"] == 5690, "part discount: 800 + 2 x 945 + 3000 = 5690")
invoices("KSK + discount", 50)

# ---------------------------------------------------------------- part quantity 0, sort
items = A.get(B + f"{D}/{DOC2}").json()["items"]
for it in items:
    if it.get("kind") == "part" and it.get("ref_part_id") == PB:
        it["qty"] = 0
check(A.put(B + f"{D}/{DOC2}/items", json={"items": items}).ok, "part B with quantity 0")
for mode in ("full", "title"):
    r = A.post(B + f"{D}/{DOC2}/invoice", json={"parts_mode": mode})
    titles = [x.get("title") for x in r.json().get("items") or []] if r.ok else None
    check(r.ok and titles is not None and "Editing" not in titles and "Edit" not in titles, f"quantity 0: no positions of the part ({mode}) {titles}")
    if r.ok:
        A.delete(B + f"{D}/{r.json()['id']}")
for bad in ("nan", "inf", "-inf"):
    check(A.patch(B + f"{D}/{DOC2}/parts/{PA}", json={"sort": bad}).status_code == 400, f"sort {bad} -> 400")

print(f"p2470_f_review_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
