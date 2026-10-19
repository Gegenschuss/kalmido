#!/usr/bin/env python3
"""2.113.1 API tests, part A (#2251, #2252): calculation options of industry packs and own packs of an instance.
Invented companies, people and figures only. freelancer-matrix: office
 - an older quotation (producing_mode NULL) keeps the calculation by quantities / quotient, also after a changed quotient
   and with a pack switched on later; a new quotation without a pack option starts without producing
 - own packs from the data folder (<datadir>/packs/industry/*.json): a valid one is listed and can be switched on; a
   broken one (factor out of range) and one with the code of a shipped pack are refused, the shipped pack stays
 - "share by amount" (option of the example pack): amount of the marked positions / day rate x factor, half days, the
   line text; USD: amount and rate in the same currency; limits of the factor (0.01..10) on the document, the part and
   the office settings; a part with its own factor; a copy keeps the mode; the office settings share_factor / share_rate
 - the film pack: handling costs (4 %, on) and markup (10 %, off): marks per position, markup stacked on the handling
   costs, renamed line titles, the lines on the invoice made from the quotation and in the print model
 - no file or text of a private pack under kalmido/office/packs (the public repository)
 - a person without an organisation does the same in their own office
usage: p2113b_a_api_test.py <datadir>"""
import hashlib
import io
import json
import os
import re
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
PACKS = os.path.join(N, "..", "kalmido", "office", "packs")
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


if not os.environ.get("P2113BA_NOSTART"):
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr

# ---------------------------------------------------------------- own packs in the data folder
FILM = json.load(open(os.path.join(PACKS, "industry", "film.json"), encoding="utf-8"))


def pack(code, name, calc):
    d = json.loads(json.dumps(FILM))
    d.update(code=code, name={"de": name, "en": name}, version=1, calc=calc)
    return d


IND = os.path.join(DATA, "packs", "industry")
os.makedirs(IND, exist_ok=True)
SHARE = {"label": {"de": "Organisation", "en": "Organisation"}, "rate": 500, "factor": 0.5}
for fn, d in (("example_share.json", pack("example_share", "Beispiel Anteil", {"share": SHARE})),
              ("broken_share.json", pack("broken_share", "Kaputt", {"share": {**SHARE, "factor": 50}})),
              ("film.json", pack("film", "Falscher Film", {}))):
    with open(os.path.join(IND, fn), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
for root, dirs, files in os.walk(os.path.join(DATA, "packs")):
    os.chmod(root, 0o755)
    for x in files:
        os.chmod(os.path.join(root, x), 0o644)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
assert A.put(B + O + "/settings", json={"lang": "de", "producing_on": 1}).ok


def svc(s, name, rate):
    r = s.post(B + O + "/services", json={"name_de": name, "name_en": name, "category": "Video", "daily_rate": rate, "unit": "day", "producing": 1})
    assert r.ok, r.text
    return r.json()["id"]


SV = svc(A, "Dreh", 1000)


def new(s, **kw):
    r = s.post(B + D, json={"project_title": "Beispielprojekt", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def items(s, did, its):
    r = s.put(B + f"{D}/{did}/items", json={"items": its})
    assert r.ok, r.text
    return r.json()


def line(doc, kind, slot=None):
    return next((x for x in doc["totals"].get("lines") or [] if x["kind"] == kind and (slot is None or x.get("slot") == slot)), None)


# ---------------------------------------------------------------- the pack list
ind = {x["code"]: x for x in A.get(B + O + "/packs").json()["industry"]}
check("example_share" in ind and ind["example_share"]["source"] == "local", "#2252: the own pack of the data folder is listed " + str(list(ind)))
check("broken_share" not in ind, "#2252: the validator refuses a pack with a factor out of range")
check(ind.get("film", {}).get("name") == "Film & Video" and ind["film"]["source"] == "builtin", "#2252: a data folder file with a shipped code is refused, the shipped pack stays")

# ---------------------------------------------------------------- an older quotation: quantities / quotient
Q0 = new(A)
check(Q0["producing_on"] == 0 and Q0.get("producing_mode") is None, "#2251: without a pack option a new quotation has no producing " + str(Q0.get("producing_on")))
A.patch(B + f"{D}/{Q0['id']}", json={"producing_on": 1, "prod_quotient": 3, "producing_rate": 600})
j = items(A, Q0["id"], [{"kind": "service", "service_id": SV, "qty": 6}])
pl = line(j, "producing")
check(pl and pl["qty"] == 2 and pl["total"] == 1200 and "Produktionstage" in pl["detail"], "#2251: an older quotation: 6 days / 3 = 2 producing days " + str(pl))
j = A.patch(B + f"{D}/{Q0['id']}", json={"prod_quotient": 2}).json()
check(j.get("producing_mode") is None and line(j, "producing")["qty"] == 3, "#2251: a changed quotient keeps the old calculation (6 / 2 = 3 days)")

# ---------------------------------------------------------------- share by amount
r = A.put(B + O + "/settings", json={"industry_packs": ["example_share"]})
check(r.ok and r.json()["settings"]["industry_packs"] == ["example_share"], "#2252: the own pack is switched on " + r.text[:120])
st = A.get(B + O + "/settings").json()
check(any((x.get("calc") or {}).get("share", {}).get("factor") == 0.5 for x in st.get("industry") or []), "#2251: the settings carry the pack's option")
Q1 = new(A)
check(Q1["producing_mode"] == "amount" and Q1["producing_on"] == 1 and Q1["prod_quotient"] == 0.5 and Q1["producing_rate"] == 500
      and Q1["share_label"] == {"de": "Organisation", "en": "Organisation"}, "#2251: a new quotation takes the option of the pack " + str({k: Q1.get(k) for k in ("producing_mode", "prod_quotient", "producing_rate")}))
j = items(A, Q1["id"], [{"kind": "service", "service_id": SV, "qty": 10}, {"kind": "service", "title": "Musik", "qty": 1, "rate": 300, "unit": "flat"}])
pl = line(j, "producing")
check(pl and pl["qty"] == 10 and pl["total"] == 5000 and pl["title"] == "Organisation", "#2251: 10.000 / 500 x 0,5 = 10 days = 5.000 " + str(pl))
check(pl and pl["detail"].startswith("10.000,00 € / 500,00 € x 0,5 = 10 Tage"), "#2251: the line explains the calculation " + str(pl and pl["detail"]))
check(j["totals"]["net"] == 10000 + 300 + 5000, "#2251: the net with the share line " + str(j["totals"]["net"]))
rd = A.get(B + f"{D}/{Q1['id']}/render").json()
check([x["detail"] for x in rd["lines"] if x["kind"] == "producing"] == [""], "#2251: the print model has the share line without its calculation")
j = items(A, Q1["id"], [{"kind": "service", "service_id": SV, "qty": 1, "rate": 1300}])
check(line(j, "producing")["qty"] == 1.5 and line(j, "producing")["total"] == 750, "#2251: 1.300 / 500 x 0,5 = 1,3 -> 1,5 days (half days)")
j = items(A, Q1["id"], [{"kind": "service", "service_id": SV, "qty": 10}])
j = A.patch(B + f"{D}/{Q1['id']}", json={"currency": "USD", "fx_rate": 1.2}).json()
pl = line(j, "producing")
check(pl and pl["qty"] == 10 and pl["rate"] == 600 and pl["total"] == 6000, "#2251: USD: 12.000 $ / 600 $ x 0,5 = 10 days (both in the document's currency) " + str(pl))
A.patch(B + f"{D}/{Q1['id']}", json={"currency": "EUR"})
for v, ok in ((0.005, False), (11, False), (0.01, True), (10, True)):
    r = A.patch(B + f"{D}/{Q1['id']}", json={"prod_quotient": v})
    check(r.ok == ok, f"#2251: factor {v} {'accepted' if ok else 'refused'} " + str(r.status_code))
j = A.patch(B + f"{D}/{Q1['id']}", json={"prod_quotient": 0.5}).json()
# a part with its own factor
r = A.post(B + f"{D}/{Q1['id']}/parts", json={"kind": "items", "title": "Teil"})
check(r.status_code == 201, "a part " + r.text[:120])
PID = r.json()["part"]["id"]
r = A.put(B + f"{D}/{Q1['id']}/parts/{PID}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 2}]})
check(r.ok, "the part's positions " + r.text[:120])
r = A.patch(B + f"{D}/{Q1['id']}/parts/{PID}", json={"settings": {"prod_quotient": 11}})
check(r.status_code == 400, "#2251: a part's factor above 10 is refused " + str(r.status_code))
r = A.patch(B + f"{D}/{Q1['id']}/parts/{PID}", json={"settings": {"prod_quotient": 1}})
check(r.ok, "#2251: a part's own factor " + r.text[:120])
pt = next(p for p in r.json()["parts"] if p["id"] == PID)
check(pt["totals"]["producing_total"] == 2000 and pt["totals"]["producing_days"] == 4, "#2251: the part: 2.000 / 500 x 1 = 4 days " + str(pt["totals"].get("producing_days")))
# a copy keeps the mode; the older quotation keeps its own
r = A.post(B + f"{D}/{Q1['id']}/duplicate")
check(r.ok and r.json()["producing_mode"] == "amount" and r.json()["prod_quotient"] == 0.5, "#2251: a copy keeps share by amount")
j = items(A, Q0["id"], [{"kind": "service", "service_id": SV, "qty": 6}])
check(j.get("producing_mode") is None and line(j, "producing")["qty"] == 3, "#2251: the older quotation computes as before with the pack on")
# office settings: own factor / rate
for v, ok in ((20, False), (0.75, True)):
    r = A.put(B + O + "/settings", json={"share_factor": v})
    check(r.ok == ok, f"#2251: office share_factor {v} " + str(r.status_code))
A.put(B + O + "/settings", json={"share_rate": 400})
Q2 = new(A)
check(Q2["prod_quotient"] == 0.75 and Q2["producing_rate"] == 400, "#2251: the office's own factor / rate win over the pack's")
# the pack off: the documents still compute and keep their switch
A.put(B + O + "/settings", json={"industry_packs": []})
j = items(A, Q1["id"], [{"kind": "service", "service_id": SV, "qty": 10}])
check(j["producing_mode"] == "amount" and line(j, "producing")["total"] == 5000, "#2251: with the pack off a quotation keeps share by amount")
check(new(A)["producing_mode"] is None, "#2251: a new quotation without the pack has no producing")

# ---------------------------------------------------------------- film: handling costs + markup
A.put(B + O + "/settings", json={"industry_packs": ["film"]})
Q3 = new(A)
check(Q3["handling_pct"] == 4 and Q3["markup_pct"] is None and Q3["markup_stacked"] == 0 and Q3["handling_label"]["de"] == "Handlungskosten",
      "#2252: film: handling costs 4 % on, markup off " + str({k: Q3.get(k) for k in ("handling_pct", "markup_pct", "markup_stacked")}))
j = items(A, Q3["id"], [{"kind": "service", "service_id": SV, "qty": 2}, {"kind": "service", "title": "Hotel", "qty": 1, "rate": 500, "unit": "flat",
                                                                            "in_handling": 0, "in_markup": 0}])
check(j["items"][0]["in_handling"] == 1 and j["items"][1]["in_handling"] == 0, "#2252: a new position is in, a pass-through can be left out")
hl = line(j, "surcharge", "handling")
check(hl and hl["total"] == 80 and hl["title"] == "Handlungskosten" and j["totals"]["net"] == 2580, "#2252: 4 % of 2.000 = 80 " + str(hl))
j = A.patch(B + f"{D}/{Q3['id']}", json={"markup_pct": 10}).json()
ml = line(j, "surcharge", "markup")
check(ml and ml["total"] == 200 and ml["title"] == "Markup" and j["totals"]["net"] == 2780, "#2252: markup 10 % of 2.000 = 200 " + str(ml))
j = A.patch(B + f"{D}/{Q3['id']}", json={"markup_stacked": 1, "markup_label": "Production Fee", "handling_label": "HU"}).json()
ml = line(j, "surcharge", "markup")
check(ml and ml["total"] == 208 and ml["title"] == "Production Fee" and line(j, "surcharge", "handling")["title"] == "HU",
      "#2252: stacked: 10 % of 2.000 + 80 = 208, renamed lines " + str(ml))
j = A.patch(B + f"{D}/{Q3['id']}", json={"handling_label": ""}).json()
check(line(j, "surcharge", "handling")["title"] == "Handlungskosten", "#2252: an empty title = the pack's again")
j = A.patch(B + f"{D}/{Q3['id']}", json={"lang": "en"}).json()
check(line(j, "surcharge", "handling")["title"] == "Handling costs", "#2252: the pack's title in the document's language")
for v in (101, -1):
    check(A.patch(B + f"{D}/{Q3['id']}", json={"handling_pct": v}).status_code == 400, f"#2252: handling costs {v} % refused")
j = A.patch(B + f"{D}/{Q3['id']}", json={"discount_pct": 10}).json()
check(j["totals"]["discount"] == 250 and j["totals"]["net"] == 2500 + 80 + 208 - 250, "#2252: the discount takes in the positions only " + str(j["totals"]["net"]))
rd = A.get(B + f"{D}/{Q3['id']}/render").json()
check(sum(1 for x in rd.get("lines") or [] if x.get("kind") == "surcharge" and x.get("total_text")) == 2, "#2252: both lines in the print model")
# Moritz 19.10.2026: how a line was computed stays internal: the editor shows it, the customer's documents do not
check(all(x.get("detail") == "" for x in rd["lines"] if x["kind"] in ("producing", "surcharge")) and line(j, "surcharge", "markup")["detail"],
      "#2251: the print model has no calculation text, the editor has")
QS = A.post(B + f"{D}/{Q3['id']}/duplicate").json()
check(A.post(B + f"{D}/{QS['id']}/status", json={"status": "sent"}).ok, "the copy sent")
r = A.post(B + f"{D}/{QS['id']}/signoff", json={})
check(r.ok and r.json().get("url"), "an approval link " + r.text[:120])
pg = requests.get(B + "/s/q/" + r.json()["url"].split("/s/q/")[1], allow_redirects=False).text if r.ok else ""
check("Production Fee" in pg and "marked positions" not in pg and "markierten Positionen" not in pg, "#2251: the approval page has the line, not its calculation")
try:
    from pypdf import PdfReader
    pdf = A.get(B + f"{D}/{QS['id']}/pdf")
    txt = " ".join(x.extract_text() or "" for x in PdfReader(io.BytesIO(pdf.content)).pages)
    check(pdf.ok and "Production Fee" in txt and "marked positions" not in txt, "#2251: the PDF has the line, not its calculation")
except ImportError:
    print("pypdf missing: PDF text not checked")
r = A.post(B + f"{D}/{Q3['id']}/invoice")
titles = [x["title"] for x in r.json().get("items") or []] if r.ok else []
check(r.status_code == 201 and "Handling costs" in titles and "Production Fee" in titles, "#2252: the invoice from the quotation has both lines " + str(titles))
check(r.ok and all(not x.get("detail") for x in r.json()["items"] if x["title"] in ("Handling costs", "Production Fee")), "#2251: the invoice positions without the calculation")
j = A.patch(B + f"{D}/{Q3['id']}", json={"handling_pct": None, "markup_pct": None}).json()
check(line(j, "surcharge") is None and j["totals"]["net"] == 2250, "#2252: both switched off, no line")

# ---------------------------------------------------------------- no private pack in the repository
# only the shipped pack files, and no word whose hash is the private pack's name (the name itself stays out of the repository)
PRIVATE = {"284fe9eb10533a2a9c106e5c168c69ff825140ab3f2dbcd5ea4566d76101f513"}
files, hits = [], []
for root, dirs, fs in os.walk(PACKS):
    for x in fs:
        rel = os.path.relpath(os.path.join(root, x), PACKS)
        files.append(rel)
        words = set(re.findall(r"[a-z0-9_]+", (rel + " " + open(os.path.join(root, x), encoding="utf-8", errors="replace").read()).lower()))
        if any(hashlib.sha256(w.encode()).hexdigest() in PRIVATE for w in words):
            hits.append(rel)
check(sorted(files) == ["de.json", os.path.join("industry", "film.json")], "#2251: only the shipped packs under kalmido/office/packs " + str(files))
check(not hits, "#2251: no private pack name under kalmido/office/packs " + str(hits))

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "fiona")
check(Fr.put(B + O + "/settings", json={"industry_packs": ["example_share", "film"], "producing_on": 1}).ok, "freelancer: both packs in the own office")
SVF = svc(Fr, "Schnitt", 800)
QF = new(Fr)
check(QF["producing_mode"] == "amount" and QF["handling_pct"] == 4, "freelancer: share by amount + handling costs in the own office")
j = items(Fr, QF["id"], [{"kind": "service", "service_id": SVF, "qty": 5}])
check(line(j, "producing")["total"] == 2000 and line(j, "surcharge", "handling")["total"] == 160, "freelancer: 4.000 / 500 x 0,5 = 4 days = 2.000, 4 % = 160")
check(A.get(B + f"{D}/{QF['id']}").status_code in (403, 404), "freelancer: the organisation's admin does not see the quotation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
