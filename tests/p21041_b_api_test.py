#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1041.0 API tests, part B (#5814 #5816 #5817): optional / alternative positions, a subtotal per section, the flat price
quotation. Own container (start.sh). Invented companies, people and figures only. freelancer-matrix: office
 - #5814: a position of a quotation is normal / optional / alternative (opt); optional and alternative ones carry their amount in
   the calculation's lines but count in no sum (net, discount, tax, surplus), the totals name it (opt_note); the print model has
   "Optional:" / "Alternativ:" in the document's language; PDF and approval page show the label and the amount in brackets;
   the invoice made from the quotation leaves them out; back to normal = counted again; a wrong value 400; an invoice ignores it
 - #5816: the switch subtotals on quotations and invoices (default from the office setting subtotals_on): a line kind subtotal
   after every section (none before the first heading), the sums unchanged; editor lines, print model, PDF, approval page
 - #5817: flat_print on a quotation (an invoice ignores it): the print model has no quantity / unit price / amount per position
   and no calculation lines, the sums stay; the optional position keeps its amount; PDF and approval page without prices; the
   invoice made from it: one position per tax rate with the same net
 - a quotation without the new switches prints and is hashed as before (no new keys in its lines / totals)
 - a person without an organisation does the same in the personal office
usage: p21041_b_api_test.py <datadir>      (P21041B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import io
import os
import subprocess
import sys

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,office,clients"
O, D = "/api/office", "/api/office/docs"
from kt import FAILS, OKS, check, sess  # noqa: E402  shared helpers (tests/kt.py)

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

if not os.environ.get("P21041B_NOSTART"):
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
assert A.put(B + O + "/settings", json={"lang": "de"}).ok


def new(s, **kw):
    r = s.post(B + D, json={"project_title": "Beispielfilm", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def items(s, did, its, code=200):
    r = s.put(B + f"{D}/{did}/items", json={"items": its})
    assert r.status_code == code, r.text
    return r.json()


def lines(doc, kind=None):
    return [x for x in (doc.get("totals") or {}).get("lines") or [] if kind is None or x["kind"] == kind]


def pdf_text(s, did):
    if PdfReader is None:
        return None
    r = s.get(B + f"{D}/{did}/pdf")
    if not r.ok:
        return ""
    return " ".join(x.extract_text() or "" for x in PdfReader(io.BytesIO(r.content)).pages)


def svc(title, qty, rate, opt="", **kw):
    return {"kind": "service", "title": title, "qty": qty, "rate": rate, "unit": "day", "tax": "standard", "opt": opt, **kw}


ITEMS = [{"kind": "heading", "title": "Vorproduktion"}, svc("Konzept", 2, 1000), svc("Moodfilm", 1, 400, "optional"),
         {"kind": "heading", "title": "Dreh"}, svc("Kamera", 3, 800, cost=300), svc("Drohne", 1, 550, "alternative", cost=200)]

# ---------------------------------------------------------------- a quotation without the new switches: as before
Q0 = new(A)
j0 = items(A, Q0["id"], [{"kind": "heading", "title": "Vorproduktion"}, svc("Konzept", 2, 1000)])
check(Q0.get("subtotals") is False and Q0.get("flat_print") is False, "a new quotation: subtotals and flat price off " + str((Q0.get("subtotals"), Q0.get("flat_print"))))
rd0 = A.get(B + f"{D}/{Q0['id']}/render").json()
check(not any("opt" in x or "opt_label" in x for x in rd0["lines"]) and "opt_note" not in rd0["totals"] and not lines(j0, "subtotal") and not rd0.get("flat"),
      "without the new switches the lines and totals of the print model carry no new key (the approval hash stays)")

# ---------------------------------------------------------------- #5814 optional / alternative positions
Q = new(A)
j = items(A, Q["id"], ITEMS)
its = {x["title"]: x for x in j["items"]}
check(its["Moodfilm"]["opt"] == "optional" and its["Drohne"]["opt"] == "alternative" and its["Konzept"]["opt"] == "", "#5814: opt stored per position " + str({k: v.get("opt") for k, v in its.items()}))
t = j["totals"]
check(t["items_net"] == 2000 + 2400 and t["net"] == 4400, "#5814: the net counts the normal positions only " + str(t["net"]))
il = {x["title"]: x for x in lines(j, "item")}
check(il["Moodfilm"]["total"] == 400 and il["Moodfilm"]["opt"] == "optional" and il["Drohne"]["total"] == 550 and "opt" not in il["Konzept"],
      "#5814: an optional / alternative line keeps its amount and says so " + str(il["Moodfilm"]))
check(t["costs"] == 900 and t["margin"] == 4400 - 900, "#5814: the purchase of the alternative position does not count " + str((t["costs"], t["margin"])))
check(its["Drohne"].get("margin") is None and its["Kamera"].get("margin") == 2400 - 900, "#5814: no surplus per position for the alternative " + str(its["Drohne"].get("margin")))
check(t.get("opt_note") == "Optionale und alternative Positionen sind nicht in der Summe enthalten.", "#5814: the totals name it in the document's language " + str(t.get("opt_note")))
j = A.patch(B + f"{D}/{Q['id']}", json={"discount_pct": 10}).json()
check(j["totals"]["discount"] == 440 and j["totals"]["net"] == 3960, "#5814: the discount takes in the normal positions only " + str(j["totals"]["discount"]))
check(abs(j["totals"]["gross"] - 3960 * 1.19) < 0.01, "#5814: the tax only on the counted net " + str(j["totals"]["gross"]))
rd = A.get(B + f"{D}/{Q['id']}/render").json()
rl = {x.get("title"): x for x in rd["lines"] if x["kind"] == "item"}
check(rl["Moodfilm"].get("opt_label") == "Optional:" and rl["Drohne"].get("opt_label") == "Alternativ:" and "opt_label" not in rl["Konzept"],
      "#5814: the print model labels them in German " + str((rl["Moodfilm"].get("opt_label"), rl["Drohne"].get("opt_label"))))
j = A.patch(B + f"{D}/{Q['id']}", json={"lang": "en"}).json()
rl = {x.get("title"): x for x in A.get(B + f"{D}/{Q['id']}/render").json()["lines"] if x["kind"] == "item"}
check(rl["Moodfilm"].get("opt_label") == "Optional:" and rl["Drohne"].get("opt_label") == "Alternative:" and j["totals"]["opt_note"].startswith("Optional and alternative"),
      "#5814: ... and in English for an English quotation")
A.patch(B + f"{D}/{Q['id']}", json={"lang": "de"})
txt = pdf_text(A, Q["id"])
if txt is not None:
    check("Optional: Moodfilm" in txt and "(400,00 €)" in txt and "Alternativ: Drohne" in txt and "(550,00 €)" in txt,
          "#5814: the PDF labels them and sets the amount in brackets " + txt[:900].replace("\n", " | "))
    check("nicht in der Summe enthalten" in txt, "#5814: the PDF has the note below the sums")
bad = items(A, Q["id"], [svc("Konzept", 2, 1000, "maybe")], code=400)
check("opt" in str(bad), "#5814: an unknown kind of position is refused " + str(bad)[:120])
# an invoice from the quotation: only the normal positions
r = A.post(B + f"{D}/{Q['id']}/invoice", json={})
check(r.status_code == 201, "an invoice from the quotation " + r.text[:200])
inv = r.json()
check(sorted(x["title"] for x in inv["items"] if x["kind"] == "service") == ["Kamera", "Konzept"] and inv["totals"]["net"] == "3960.00",
      "#5814: the invoice takes the normal positions only, same net " + str([x["title"] for x in inv["items"]]) + " " + str(inv["totals"]["net"]))
check(not any(x.get("opt") for x in inv["items"]), "#5814: an invoice position is never optional")
# back to normal: counted at once
cur = A.get(B + f"{D}/{Q['id']}").json()["items"]
for x in cur:
    if x["title"] == "Moodfilm":
        x["opt"] = ""
j = items(A, Q["id"], cur)
check(j["totals"]["items_net"] == 4800 and not any(x.get("opt") for x in lines(j, "item") if x["title"] == "Moodfilm"), "#5814: back to normal it counts " + str(j["totals"]["items_net"]))
j = items(A, Q["id"], [{k: v for k, v in x.items() if k != "opt"} for x in cur])
check({x["title"]: x["opt"] for x in j["items"] if x["kind"] == "service"} == {"Konzept": "", "Moodfilm": "", "Kamera": "", "Drohne": "alternative"},
      "#5814: a save without opt keeps what is stored (an older client)")

# ---------------------------------------------------------------- #5816 subtotals
j = items(A, Q["id"], ITEMS)
net_off = j["totals"]["net"]
j = A.patch(B + f"{D}/{Q['id']}", json={"subtotals": 1}).json()
st = lines(j, "subtotal")
check(j["subtotals"] is True and [(x["sec"], x["title"], x["total"]) for x in st] == [(0, "Vorproduktion", 2000), (1, "Dreh", 2400)],
      "#5816: one subtotal per section, optional / alternative not in it " + str(st))
check(st and st[0]["label"] == "Zwischensumme Vorproduktion" and st[0]["total_text"] == "2.000,00 €", "#5816: label and amount in the document's language " + str(st[:1]))
kinds = [x["kind"] for x in lines(j)]
check(kinds.index("subtotal") < kinds.index("heading", 1) and kinds[-1] == "discount" and kinds[-2] == "subtotal",
      "#5816: the subtotal stands at the end of its section, before the calculation lines " + str(kinds))
check(j["totals"]["net"] == net_off and j["totals"]["gross"] == round(net_off * 1.19, 2), "#5816: the sums do not change " + str(j["totals"]["net"]))
j = items(A, Q["id"], [svc("Briefing", 1, 300)] + ITEMS)
check([x["total"] for x in lines(j, "subtotal")] == [2000, 2400], "#5816: positions before the first heading get no subtotal")
txt = pdf_text(A, Q["id"])
if txt is not None:
    check("Zwischensumme Vorproduktion" in txt and "Zwischensumme Dreh" in txt and "2.400,00 €" in txt, "#5816: the PDF prints the subtotals " + txt[:900].replace("\n", " | "))
r = A.put(B + O + "/settings", json={"subtotals_on": 1})
check(r.ok and r.json()["settings"]["subtotals_on"] == 1, "#5816: the office setting is saved " + r.text[:120])
check(new(A)["subtotals"] is True, "#5816: a new quotation takes the office setting")
r = A.post(B + D, json={"kind": "invoice"})
check(r.status_code == 201 and r.json()["subtotals"] is True, "#5816: a new invoice too " + r.text[:120])
IV = r.json()
j = items(A, IV["id"], [{"kind": "heading", "title": "Dreh"}, svc("Kamera", 3, 800), {"kind": "discount", "title": "Nachlass", "qty": 1, "rate": 100, "unit": "flat", "tax": "standard"},
                         {"kind": "heading", "title": "Schnitt"}, svc("Schnitt", 2, 700)])
check([(x["title"], x["total"]) for x in lines(j, "subtotal")] == [("Dreh", 2300), ("Schnitt", 1400)] and j["totals"]["net"] == "3700.00",
      "#5816: invoice: the discount position counts in its section, the net unchanged " + str(lines(j, "subtotal")))
j = A.patch(B + f"{D}/{IV['id']}", json={"subtotals": 0}).json()
check(j["subtotals"] is False and not lines(j, "subtotal") and j["totals"]["net"] == "3700.00", "#5816: off on the invoice: no subtotal lines")
check(A.patch(B + f"{D}/{IV['id']}", json={"flat_print": 1}).json().get("flat_print") is False, "#5817: an invoice is never a flat price")
assert A.put(B + O + "/settings", json={"subtotals_on": 0}).ok

# ---------------------------------------------------------------- #5817 the flat price quotation
QF = new(A)
j = items(A, QF["id"], ITEMS)
j = A.patch(B + f"{D}/{QF['id']}", json={"discount_pct": 10, "subtotals": 1}).json()
tot_before = (j["totals"]["net"], j["totals"]["gross"])
j = A.patch(B + f"{D}/{QF['id']}", json={"flat_print": 1}).json()
check(j["flat_print"] is True and (j["totals"]["net"], j["totals"]["gross"]) == tot_before, "#5817: flat price on, the sums the same " + str(tot_before))
check(any(x.get("rate") == 800 for x in lines(j, "item")), "#5817: the editor keeps every price")
rd = A.get(B + f"{D}/{QF['id']}/render").json()
il = {x.get("title"): x for x in rd["lines"] if x["kind"] == "item"}
check(rd.get("flat") is True and not any(k in il["Kamera"] for k in ("qty", "qty_text", "rate", "rate_text", "total", "total_text", "unit_text")),
      "#5817: the print model has no quantity, price or amount of a position " + str(il["Kamera"]))
check(il["Moodfilm"].get("total_text") == "400,00 €" and "rate_text" not in il["Moodfilm"], "#5817: the optional position keeps its amount only " + str(il["Moodfilm"]))
check(not [x for x in rd["lines"] if x["kind"] in ("discount", "producing", "surcharge")] and [x["total"] for x in rd["lines"] if x["kind"] == "subtotal"] == [2000, 2400],
      "#5817: no calculation lines; the subtotals stay")
check(rd["totals"]["net"] == tot_before[0] and rd["totals"]["gross"] == tot_before[1], "#5817: net and gross in the print model")
txt = pdf_text(A, QF["id"])
if txt is not None:
    check("Kamera" in txt and "800,00" not in txt and "1.000,00" not in txt and "Rabatt" not in txt and "3.960,00 €" in txt,
          "#5817: the PDF has the positions without prices, the net total " + txt[:1200].replace("\n", " | "))
check(A.post(B + f"{D}/{QF['id']}/status", json={"status": "sent"}).ok, "the flat price quotation sent")
r = A.post(B + f"{D}/{QF['id']}/signoff", json={})
check(r.ok and r.json().get("url"), "an approval link " + r.text[:120])
pg = requests.get(B + "/s/q/" + r.json()["url"].split("/s/q/")[1], allow_redirects=False).text if r.ok else ""
check("Kamera" in pg and "800,00" not in pg and "2.400,00 €" in pg and "3.960,00 €" in pg and "Optional: Moodfilm" in pg and "(400,00 €)" in pg,
      "#5817 / #5816 / #5814: the approval page: no line prices, the subtotals, the option in brackets " + pg[pg.find("<table"):pg.find("<table") + 900])
check("Zwischensumme Dreh" in pg and "nicht in der Summe enthalten" in pg, "#5816 / #5814: subtotal label and note on the approval page")
r = A.post(B + f"{D}/{QF['id']}/invoice", json={})
inv = r.json() if r.status_code == 201 else {}
sv = [x for x in inv.get("items") or [] if x["kind"] == "service"]
check(len(sv) == 1 and sv[0]["qty"] == 1 and sv[0]["unit"] == "flat" and inv["totals"]["net"] == "3960.00" and sv[0]["cost"] == 900,
      "#5817: the invoice from a flat price quotation: one position per tax rate, same net, the purchase on it " + str(sv)[:300])

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "fiona")
QP = new(Fr)
j = items(Fr, QP["id"], ITEMS)
check(j["totals"]["net"] == 4400 and [x["title"] for x in lines(j, "item") if x.get("opt")] == ["Moodfilm", "Drohne"], "freelancer: optional / alternative positions in the own office")
j = Fr.patch(B + f"{D}/{QP['id']}", json={"subtotals": 1, "flat_print": 1}).json()
check([x["total"] for x in lines(j, "subtotal")] == [2000, 2400] and j["flat_print"] is True, "freelancer: subtotals and flat price")
rd = Fr.get(B + f"{D}/{QP['id']}/render").json()
check(rd.get("flat") is True and not any("rate_text" in x for x in rd["lines"] if x["kind"] == "item"), "freelancer: the print model without prices")
check(Fr.put(B + O + "/settings", json={"subtotals_on": 1}).ok and new(Fr)["subtotals"] is True, "freelancer: the office setting in the own office")
check(A.get(B + f"{D}/{QP['id']}").status_code in (403, 404), "freelancer: the organisation's admin does not see the quotation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
