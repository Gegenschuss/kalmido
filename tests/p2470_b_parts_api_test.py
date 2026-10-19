#!/usr/bin/env python3
"""2.47.0 API tests, part B (#1215 parts of a quotation / Teilangebote), own container in mode workspaces (start.sh).
Invented services and amounts only.
 - a quotation without parts computes, answers and prints as before (parts: [])
 - POST /api/office/docs/<id>/parts puts the new part on the title page (kind 'part', qty 1); PUT .../parts/<pid>/items
   fills it; the title page counts net x qty, the tax bases per rate x qty (mixed rates), optional raw data x qty stays
   optional (net incl. raw data), included raw data stays included (net excl. raw data), the purchase x qty; a part that
   is not on the title page counts nothing; the title page discount takes in part lines marked discountable
 - the stored rate of a title page part line is the part's net (an older version shows plausible sums)
 - rights: a member sees the parts without purchase / surplus, another organisation gets 404; sent = 409
 - duplicate copies the parts with their positions and points the title page lines to the copies
 - PDF: one page more per printed part that stands on the title page; a part not printed is left out
 - invoice from the quotation: modes full / title / summary give the quotation's net and gross; summary = one position
   per tax rate with the title of the settings (default "Film production" in English)
usage: p2470_b_parts_api_test.py <datadir>"""
import io
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


def pdf_pages(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def svc(title, qty, rate, tax="standard", raw=0, cost=0, unit="day", disc=1):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": tax, "raw_fee": raw, "producing": 0,
            "intext": "intern", "cost": cost, "discountable": disc}


# ---------------------------------------------------------------- setup: organisation Alpha (alice admin, bob member), Beta (carol)
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
if not os.environ.get("P2470_B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ids = {u: i for u, i in dbx("SELECT username, id FROM users")}
Bo, Ca = sess("bob"), sess("carol")
for s_ in (A, Bo, Ca):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member') ON CONFLICT DO NOTHING", (ORG, ids["bob"]))
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
r = A.put(B + "/api/office/settings", json={"raw_on": 1, "producing_on": 1, "raw_factor": 0.25, "prod_quotient": 3, "producing_rate": 600})
check(r.ok, "office settings " + r.text[:200])
check(r.json()["settings"].get("parts_invoice_mode") == "full", f"settings: app default for invoices from parts = full {r.json()['settings'].get('parts_invoice_mode')}")

# ---------------------------------------------------------------- a quotation without parts: as before
r = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Plain", "items": [svc("Concept", 1, 800), svc("Edit", 2, 450, raw=1)]})
check(r.status_code == 201, "create plain " + r.text[:200])
PLAIN = r.json()
check(PLAIN.get("parts") == [] and PLAIN["totals"]["net"] == 1700 and PLAIN["totals"]["net_incl_raw"] == 1925,
      f"plain quotation: no parts, net 1700, incl. raw data 1925 {PLAIN.get('parts')} {PLAIN['totals'].get('net')} {PLAIN['totals'].get('net_incl_raw')}")
pp = pdf_pages(A.get(B + f"{D}/{PLAIN['id']}/pdf").content)
PLAIN_PAGES = len(pp) if pp is not None else None

# ---------------------------------------------------------------- parts
r = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Campaign", "items": [svc("Concept", 1, 800)]})
DOC = r.json()["id"]
r = A.post(B + f"{D}/{DOC}/parts", json={"title": "Interactive module"})
check(r.status_code == 201 and r.json().get("part", {}).get("title") == "Interactive module", "POST part " + r.text[:200])
P1 = r.json()["part"]["id"]
t_items = r.json()["items"]
check([(x["kind"], x["ref_part_id"], float(x["qty"])) for x in t_items][-1] == ("part", P1, 1.0), f"the new part stands on the title page once {t_items}")
r = A.put(B + f"{D}/{DOC}/parts/{P1}/items", json={"items": [svc("Animation", 2, 500, raw=1, cost=100), svc("Booklet", 1, 200, tax="reduced", cost=50, unit="flat")]})
check(r.ok, "PUT part items " + r.text[:200])
p1 = r.json()["part"]
check(p1["totals"]["net"] == 1200 and p1["totals"]["net_incl_raw"] == 1450 and p1["totals"]["costs"] == 250,
      f"part: net 1200, incl. raw data 1450, purchase 250 {p1['totals'].get('net')} {p1['totals'].get('net_incl_raw')} {p1['totals'].get('costs')}")
check(r.json()["totals"]["net"] == 2000, f"title page: concept 800 + part 1200 {r.json()['totals'].get('net')}")
# quantity 5 on the title page, a second part (not printed) once, a third part not on the title page
items = r.json()["items"]
items[-1]["qty"] = 5
r = A.put(B + f"{D}/{DOC}/items", json={"items": items})
check(r.ok and r.json()["totals"]["net"] == 6800, f"title page: part x 5 -> 800 + 6000 {r.text[:200]}")
r = A.post(B + f"{D}/{DOC}/parts", json={"title": "Extra", "print": 0})
P2 = r.json()["part"]["id"]
A.put(B + f"{D}/{DOC}/parts/{P2}/items", json={"items": [svc("Extra shoot", 1, 300)]})
r = A.post(B + f"{D}/{DOC}/parts", json={"title": "Alternative", "add_to_title": False})
P3 = r.json()["part"]["id"]
r = A.put(B + f"{D}/{DOC}/parts/{P3}/items", json={"items": [svc("Alternative", 1, 999)]})
d = r.json()
t = d["totals"]
check(t["net"] == 7100, f"title page: 800 + 6000 + 300; the part not on the title page counts nothing {t.get('net')}")
tax = {x["rate_key"]: (x["base"], x["amount"]) for x in t["tax_lines"]}
check(tax == {"standard": (6100, 1159), "reduced": (1000, 70)}, f"mixed rates: bases per rate x qty {tax}")
check(t["gross"] == 8329, f"gross 8329 {t.get('gross')}")
check(t["net_incl_raw"] == 8350 and t.get("net_excl_raw") is None, f"optional raw data of the part x 5 stays optional (8350) {t.get('net_incl_raw')}")
check(t["costs"] == 1250 and t["margin"] == 5850, f"purchase x qty 1250, surplus 5850 {t.get('costs')} {t.get('margin')}")
used = {p["id"]: p["used"] for p in d["parts"]}
check(used == {P1: 1, P2: 1, P3: 0}, f"parts: used on the title page {used}")
rates = {x["ref_part_id"]: float(x["rate"]) for x in d["items"] if x["kind"] == "part"}
check(rates == {P1: 1200.0, P2: 300.0}, f"stored rate of a part line = the part's net (older versions) {rates}")
pl = [x for x in t["lines"] if x.get("part_id") == P1]
check(len(pl) == 1 and pl[0]["total"] == 6000 and pl[0]["qty"] == 5 and pl[0].get("mixed_tax"), f"the part line: 5 x 1200 {pl}")

# discount of the title page: the concept and the part line marked discountable; the second part line not
items = d["items"]
for x in items:
    if x.get("ref_part_id") == P2:
        x["discountable"] = 0
A.put(B + f"{D}/{DOC}/items", json={"items": items})
r = A.patch(B + f"{D}/{DOC}", json={"discount_pct": 10})
t = r.json()["totals"]
tax = {x["rate_key"]: (x["base"], x["amount"]) for x in t["tax_lines"]}
check(t["discount"] == 680 and t["net"] == 6420 and tax == {"standard": (5520, 1048.8), "reduced": (900, 63)},
      f"discount 10 % on concept + part line per rate {t.get('discount')} {t.get('net')} {tax}")

# included raw data in the part: net grows by 5 x 250, the title page shows the net without raw data
r = A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"settings": {"raw_mode": "included"}})
t = r.json()["doc_totals"]
check(r.ok and r.json()["part"]["settings"] == {"raw_mode": "included"} and r.json()["part"]["totals"]["net"] == 1450, "PATCH part settings " + r.text[:200])
# part 1450 x 5 = 7250 (std 6250, red 1000) + 800 + 300; discount (6250 + 800 + 1000) x 10 % = 805
check(t["net"] == 7545 and t.get("net_incl_raw") is None and t.get("net_excl_raw") == 6295,
      f"included raw data stays included: net {t.get('net')} excl. {t.get('net_excl_raw')}")
A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"settings": {"raw_mode": None}})
r = A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"title": "Interactive module (web)", "sort": 0.5})
check(r.ok and r.json()["part"]["title"] == "Interactive module (web)", "PATCH part title")
check(A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"settings": {"raw_mode": "sometimes"}}).status_code == 400, "PATCH bad settings -> 400")
check(A.post(B + f"{D}/{DOC}/parts", json={"kind": "nonsense"}).status_code == 400, "POST bad kind -> 400")
check(A.put(B + f"{D}/{DOC}/parts/{P1}/items", json={"items": [{"kind": "part", "ref_part_id": P2}]}).status_code == 400, "a part inside a part -> 400")
check(A.put(B + f"{D}/{DOC}/items", json={"items": [{"kind": "part", "ref_part_id": 999999}]}).status_code == 404, "title line of a foreign part -> 404")
A.patch(B + f"{D}/{DOC}", json={"discount_pct": 0})

# ---------------------------------------------------------------- rights
r = Bo.get(B + f"{D}/{DOC}")
check(r.ok and len(r.json()["parts"]) == 3, "member: reads the parts " + r.text[:200])
mp = r.json()["parts"]
check(all("costs" not in p["totals"] and "margin" not in p["totals"] for p in mp) and all(it.get("cost") is None for p in mp for it in p["items"])
      and "costs" not in r.json()["totals"], "member: no purchase / surplus in parts, positions and totals")
r = Bo.put(B + f"{D}/{DOC}/parts/{P2}/items", json={"items": [svc("Extra shoot", 1, 300, cost=999)]})
check(r.ok and "costs" not in r.json()["part"]["totals"], "member: edits a part, the answer has no purchase")
check(A.get(B + f"{D}/{DOC}").json()["parts"][[p["id"] for p in mp].index(P2)]["items"][0]["cost"] in (0, None, 0.0), "member cannot set a purchase price")
rd = Bo.get(B + f"{D}/{DOC}/render").json()
check(rd.get("internal") is None and all("costs" not in str(p) for p in rd.get("parts", [])), "member: print model without purchase")
for meth, url, js in (("GET", f"{D}/{DOC}", None), ("POST", f"{D}/{DOC}/parts", {"title": "x"}), ("PATCH", f"{D}/{DOC}/parts/{P1}", {"title": "x"}),
                      ("PUT", f"{D}/{DOC}/parts/{P1}/items", {"items": []}), ("DELETE", f"{D}/{DOC}/parts/{P1}", None)):
    r = Ca.request(meth, B + url, json=js)
    check(r.status_code == 404, f"other organisation: {meth} {url} -> 404 ({r.status_code})")
r = A.get(B + f"{D}/{PLAIN['id']}")
check(A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"title": "Interactive module"}).ok, "rename back")

# ---------------------------------------------------------------- print model + PDF
rd = A.get(B + f"{D}/{DOC}/render").json()
check([p["title"] for p in rd.get("parts", [])] == ["Interactive module"], f"print model: only printed parts on the title page {[p['title'] for p in rd.get('parts', [])]}")
pg = pdf_pages(A.get(B + f"{D}/{DOC}/pdf").content)
if pg is not None and PLAIN_PAGES is not None:
    check(len(pg) == PLAIN_PAGES + 1, f"PDF: one page more for the printed part ({len(pg)} vs {PLAIN_PAGES})")
    ppg = pg[-2] if len(pg) > 1 and "TRANSFEROFRIGHTS" in "".join(pg[-1].split()) else pg[-1]  # 2.114.1 (#2258): the rights appendix comes after the parts
    check("interactive module" in ppg.lower() and "Animation" in ppg and "Booklet" in ppg, "PDF: the part's page has its positions (title in capitals)")
    check(not any("Alternative" in x for x in pg) and not any("Extra shoot" in x for x in pg), "PDF: parts not printed / not used are left out")
    check("Interactive module" in pg[0] and "6,000.00" in pg[0].replace("€", ""), "PDF: the title page has the part line x 5")
    check(not any("1,250.00" in x and "urchase" in x for x in pg), "PDF: no purchase")
else:
    print("pypdf missing: PDF checks skipped")

# ---------------------------------------------------------------- invoices from the quotation
off = A.get(B + f"{D}/{DOC}").json()["totals"]
for mode in ("full", "title", "summary"):
    r = A.post(B + f"{D}/{DOC}/invoice", json={"parts_mode": mode})
    check(r.status_code == 201, f"invoice {mode} " + r.text[:200])
    it = r.json()
    check(abs(float(it["totals"]["net"]) - off["net"]) < 0.005 and abs(float(it["totals"]["gross"]) - off["gross"]) < 0.005,
          f"invoice {mode}: net / gross = the quotation's ({it['totals'].get('net')} / {it['totals'].get('gross')} vs {off['net']} / {off['gross']})")
    kinds = [x["kind"] for x in it["items"]]
    if mode == "summary":
        check([(x["title"], x["tax"]) for x in it["items"]] == [("Film production", "standard"), ("Film production", "reduced")],
              f"summary: one position per tax rate {[(x['title'], x['tax']) for x in it['items']]}")
    if mode == "full":
        check("heading" in kinds and any(x["title"] == "Animation" and float(x["qty"]) == 10 for x in it["items"]),
              f"full: heading + the part's positions qty x 5 {[(x['title'], x['qty']) for x in it['items']]}")
    if mode == "title":
        check(not any(x["title"] == "Animation" for x in it["items"]) and sum(1 for x in it["items"] if x["title"] == "Interactive module") == 2,
              "title: the part as positions with its amount (two tax rates)")
# with a discount on the title page AND inside the part (per tax rate), producing on the title page
A.patch(B + f"{D}/{DOC}", json={"discount_pct": 10})
A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"settings": {"discount_pct": 5}})
off2 = A.get(B + f"{D}/{DOC}").json()["totals"]
for mode in ("full", "title", "summary"):
    it = A.post(B + f"{D}/{DOC}/invoice", json={"parts_mode": mode}).json()
    check(abs(float(it["totals"]["net"]) - off2["net"]) < 0.005 and abs(float(it["totals"]["gross"]) - off2["gross"]) < 0.005,
          f"invoice {mode} with discounts: net / gross = the quotation's ({it['totals'].get('net')} / {it['totals'].get('gross')} vs {off2['net']} / {off2['gross']})")
A.patch(B + f"{D}/{DOC}", json={"discount_pct": 0})
A.patch(B + f"{D}/{DOC}/parts/{P1}", json={"settings": {"discount_pct": None}})
r = A.post(B + f"{D}/{DOC}/invoice", json={"parts_mode": "summary", "parts_title": "Production"})
check(r.ok and {x["title"] for x in r.json()["items"]} == {"Production"}, "summary: own title")
check(A.post(B + f"{D}/{DOC}/invoice", json={"parts_mode": "bogus"}).status_code == 400, "bad mode -> 400")
A.put(B + "/api/office/settings", json={"parts_invoice_mode": "summary", "parts_summary_title_en": "Video production"})
r = A.post(B + f"{D}/{DOC}/invoice", json={})
check(r.ok and {x["title"] for x in r.json()["items"]} == {"Video production"}, "the organisation's default mode + title")
r = A.post(B + f"{D}/{PLAIN['id']}/invoice", json={})
check(r.ok and [x["title"] for x in r.json()["items"]][:2] == ["Concept", "Edit"], "a quotation without parts: invoice as before")

# ---------------------------------------------------------------- duplicate, delete, sent
r = A.post(B + f"{D}/{DOC}/duplicate")
check(r.status_code == 201, "duplicate " + r.text[:200])
cp = r.json()
newp = {p["title"]: p["id"] for p in cp["parts"]}
check(len(cp["parts"]) == 3 and set(newp.values()).isdisjoint({P1, P2, P3}), "duplicate: three new parts")
check({x["ref_part_id"] for x in cp["items"] if x["kind"] == "part"} == {newp["Interactive module"], newp["Extra"]}, "duplicate: title lines point to the copies")
check(cp["totals"]["net"] == off["net"] and any(p["items"] for p in cp["parts"]), f"duplicate: same net with the parts' positions {cp['totals'].get('net')}")
r = A.delete(B + f"{D}/{DOC}/parts/{P2}")
check(r.ok and r.json()["totals"]["net"] == off["net"] - 300 and not any(x.get("ref_part_id") == P2 for x in r.json()["items"]),
      "delete part: its title line goes, the sum shrinks")
A.post(B + f"{D}/{DOC}/status", json={"status": "sent"})
check(A.post(B + f"{D}/{DOC}/parts", json={"title": "late"}).status_code == 409, "sent quotation: no new part (409)")
check(A.put(B + f"{D}/{DOC}/parts/{P1}/items", json={"items": []}).status_code == 409, "sent quotation: part positions locked (409)")
r = A.delete(B + f"{D}/{cp['id']}")
check(r.ok and not dbx("SELECT id FROM office_doc_parts WHERE doc_id=?", (cp["id"],)), "deleting the quotation removes its parts")
check(A.post(B + f"{D}/{r.json() and DOC}/parts", json={"kind": "shoot"}).status_code in (400, 409), "shoot part only with the shoot calculation")

print(f"p2470_b_parts_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
