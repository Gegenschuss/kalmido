#!/usr/bin/env python3
"""2.40.0 API tests, part E (office settings), own container (start.sh, mode workspaces). Invented companies only.
 - #1378: no fetch() in static/js writes (POST / PUT / PATCH / DELETE) without the CSRF header X-Requested-With;
   the logo upload and the settings import work with the header and are refused without it
 - #1379: producing / raw data as switches: a new organisation starts with both off (no producing / raw data line, raw
   data "none", catalogue flags not taken over, contracts keep the raw mode), switched on they work as before, an existing
   document stays as it was; the one-time start migration switches both on for an organisation that uses them and never
   again (switching off stays off); an invoice made from a quotation and its e-invoice carry no producing line when off
 - #1377: the word before the management's names in the footer (DE / EN per document language), default unchanged
 - #1382: the number preview of every scheme kind (counter restart), errors of a scheme in plain words
usage: p2400_e_api_test.py <datadir>"""
import os
import re
import subprocess
import sys
import datetime
import json
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
# a 1x1 PNG (2.40.0 (#1378): a valid one - the former IDAT did not decode, Pillow refused it)
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082")


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


# ---------------------------------------------------------------- #1378: the static check (no container needed)
def fetch_calls(src):
    """(line, argument text) of every fetch( call; strings and nested parentheses are skipped."""
    for m in re.finditer(r"\bfetch\(", src):
        i, d, q = m.end(), 1, None
        while i < len(src) and d:
            c = src[i]
            if q:
                if c == "\\":
                    i += 1
                elif c == q:
                    q = None
            elif c in "'\"`":
                q = c
            elif c == "(":
                d += 1
            elif c == ")":
                d -= 1
            i += 1
        yield src.count("\n", 0, m.start()) + 1, src[m.end():i - 1]


# fetch() calls whose options come from a variable: reviewed by hand
FETCH_VAR_OK = {
    ("core.js", "url, opt"),  # rawFetch0: opt is built with the header right above
}
JS = os.path.join(N, "..", "static", "js")
bad = []
for fn in sorted(os.listdir(JS)):
    if not fn.endswith(".js"):
        continue
    for ln, a in fetch_calls(open(os.path.join(JS, fn), encoding="utf-8").read()):
        a1 = " ".join(a.split())
        if "X-Requested-With" in a1:
            continue
        if re.fullmatch(r"[\w.]+\s*,\s*[\w.]+", a1):  # options from a variable
            if (fn, a1) not in FETCH_VAR_OK:
                bad.append(f"{fn}:{ln}: options from a variable, not reviewed: {a1}")
            continue
        if "method" not in a1 or re.search(r"method:\s*'GET'", a1):
            continue  # a GET needs no header
        bad.append(f"{fn}:{ln}: {a1[:90]}")
check(not bad, "#1378: every writing fetch() sends X-Requested-With " + repr(bad))

# ---------------------------------------------------------------- the container
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"

# ---------------------------------------------------------------- #1378: logo + import with / without the header
naked = requests.Session()
naked.cookies.update(A.cookies)
r = naked.post(B + O + "/logo", files={"file": ("logo.png", PNG, "image/png")})
check(r.status_code in (400, 403), f"#1378: a logo upload without the header is refused {r.status_code}")
r = A.post(B + O + "/logo", files={"file": ("logo.png", PNG, "image/png")})
check(r.ok, "#1378: the logo upload with the header " + r.text[:160])
check(bool(A.get(B + O + "/settings").json()["settings"].get("logo")), "#1378: the logo is set")
exp = A.get(B + O + "/export")
check(exp.ok, "#1378: export")
r = A.post(B + O + "/import", files={"file": ("office.json", exp.content, "application/json")})
check(r.ok, "#1378: the settings import with the header " + r.text[:160])
r = naked.post(B + O + "/import", files={"file": ("office.json", exp.content, "application/json")})
check(r.status_code in (400, 403), f"#1378: an import without the header is refused {r.status_code}")

# ---------------------------------------------------------------- #1379: producing / raw data switched on per organisation
D = O + "/docs"
Y = datetime.date.today().year


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


st = A.get(B + O + "/settings").json()["settings"]
check(st.get("producing_on") == 0 and st.get("raw_on") == 0, f"#1379: a new organisation starts without producing / raw data {st.get('producing_on')} {st.get('raw_on')}")
r = A.put(B + O + "/settings", json={"lang": "de", "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                                    "country": "DE", "email": "hallo@nordlicht.example", "tax_number": "12/345/67890",
                                                                    "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "company data " + r.text[:160])
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
SV = A.post(B + O + "/services", json={"name_de": "Dreh", "daily_rate": 1000, "producing": 1, "raw_fee": 1}).json()["id"]
CT = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag", "client_id": CL, "raw_included": 1}).json()["id"]
Q1 = A.post(B + D, json={"project_title": "Film", "client_id": CL}).json()
check(Q1.get("raw_mode") == "none", "#1379 off: a new quotation has no raw data line " + str(Q1.get("raw_mode")))
j = A.put(B + f"{D}/{Q1['id']}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 6}]}).json()
kinds = [x["kind"] for x in j["totals"]["lines"]]
check(kinds == ["item"] and j["totals"]["net"] == 6000 and j["items"][0]["producing"] == 0 and j["items"][0]["raw_fee"] == 0,
      f"#1379 off: no producing / raw data, the catalogue flags are not taken over {kinds} {j['totals']['net']}")
j = A.patch(B + f"{D}/{Q1['id']}", json={"contract_id": CT}).json()
check(j.get("raw_mode") == "none", "#1379 off: a contract with raw data included leaves the mode alone " + str(j.get("raw_mode")))
r = A.post(B + f"{D}/{Q1['id']}/invoice")
check(r.status_code == 201 and [x["title"] for x in r.json()["items"]] == ["Dreh"], "#1379 off: the invoice from the quotation has only the position " + r.text[:120])
INV = r.json()["id"]
A.patch(B + f"{D}/{INV}", json={"service_from": f"{Y}-01-05"})
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "#1379: invoice finalised " + r.text[:160])
x = A.get(B + f"{D}/{INV}/xml")
check(x.ok and "Dreh" in x.text and "Producing" not in x.text and "Rohdaten" not in x.text, f"#1379 off: the e-invoice has no producing / raw data line {x.status_code}")
# switched on: the same as before 2.40
r = A.put(B + O + "/settings", json={"producing_on": 1, "raw_on": True})
check(r.ok and r.json()["settings"]["producing_on"] == 1 and r.json()["settings"]["raw_on"] == 1, "#1379: both switched on " + r.text[:120])
Q2 = A.post(B + D, json={"project_title": "Film 2", "client_id": CL}).json()
j = A.put(B + f"{D}/{Q2['id']}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 6}]}).json()
kinds = [x["kind"] for x in j["totals"]["lines"]]
check(Q2.get("raw_mode") == "optional" and kinds == ["item", "producing", "raw"] and j["totals"]["net"] == 7200,
      f"#1379 on: producing 2 days x 600 + raw data option as before {kinds} {j['totals']['net']}")
j = A.patch(B + f"{D}/{Q2['id']}", json={"contract_id": CT}).json()
check(j.get("raw_mode") == "included", "#1379 on: the contract presets raw data included")
j = A.get(B + f"{D}/{Q1['id']}").json()
check(j.get("raw_mode") == "none" and [x["kind"] for x in j["totals"]["lines"]] == ["item"], "#1379: the existing quotation stays as it was")
# the start migration: once per database, for organisations that use producing / raw data
A.put(B + O + "/settings", json={"producing_on": 0, "raw_on": 0})
sql("DELETE FROM kalmido_meta WHERE key='fe_office_rules'")
sql("UPDATE office_settings SET data=(data::jsonb - 'producing_on' - 'raw_on')::text WHERE org_id=?", (ORG,))
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE})
ORG3 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
A.put(B + O + "/settings", json={"lang": "de"})  # an organisation without producing / raw data
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
A = sess("alice")
st = A.get(B + O + "/settings").json()["settings"]
check(st["producing_on"] == 1 and st["raw_on"] == 1, f"#1379 migration: an organisation using producing / raw data keeps both on {st['producing_on']} {st['raw_on']}")
g3 = json.loads(sql("SELECT data FROM office_settings WHERE org_id=?", (ORG3,))[0][0])
check(g3.get("producing_on") == 0 and g3.get("raw_on") == 0, f"#1379 migration: an organisation without them starts off {g3}")
check(bool(sql("SELECT 1 FROM kalmido_meta WHERE key='fe_office_rules'")), "#1379 migration: marked as done")
A.put(B + O + "/settings", json={"producing_on": 0})
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
A = sess("alice")
check(A.get(B + O + "/settings").json()["settings"]["producing_on"] == 0, "#1379 migration: runs once, switching off stays off")
A.put(B + O + "/settings", json={"producing_on": 1})

# ---------------------------------------------------------------- #1377: the word before the management's names
A.put(B + O + "/settings", json={"company_fields": {"managing_directors": "Erika Muster, Max Muster"}})


def footer(lang):
    q = A.post(B + D, json={"project_title": "Fuss"}).json()["id"]
    A.patch(B + f"{D}/{q}", json={"lang": lang})
    m = json.dumps(A.get(B + f"{D}/{q}/render").json(), ensure_ascii=False)
    A.delete(B + f"{D}/{q}")
    return m


m = footer("de")
check("Geschäftsführung: Erika Muster, Max Muster" in m, "#1377: default stays Geschäftsführung")
check(A.get(B + O + "/settings").json()["company_fields"].get("md_label") == "", "#1377: existing company data keep the default")
for key, de, en in (("shareholders", "Gesellschafter", "Shareholders"), ("owner_f", "Inhaberin", "Owner"), ("board", "Vorstand", "Executive board"),
                    ("partners", "Partner", "Partners"), ("owner_m", "Inhaber", "Owner")):
    r = A.put(B + O + "/settings", json={"company_fields": {"md_label": key}})
    check(r.ok and r.json()["company_fields"]["md_label"] == key, f"#1377: {key} saved " + r.text[:100])
    check(f"{de}: Erika Muster" in footer("de") and f"{en}: Erika Muster" in footer("en"), f"#1377: footer {de} / {en}")
r = A.put(B + O + "/settings", json={"company_fields": {"md_label": "chief"}})
check(r.status_code == 400, "#1377: an unknown word is refused")
A.put(B + O + "/settings", json={"company_fields": {"md_label": ""}})
check("Managing directors: Erika Muster" in footer("en"), "#1377: back to the default (EN)")

# ---------------------------------------------------------------- #1382: number schemes
for kind, scheme, want, yearly in (("invoice", "RE-{yyyy}-{seq:03}", f"RE-{Y}-00", True), ("credit", "R{yy}{seq:03}", f"R{str(Y)[2:]}00", True),
                                   ("reminder", "MA-{seq:04}", "MA-000", False), ("offer", "{yyyy}-{seq:04}", f"{Y}-000", True)):
    j = A.get(B + O + "/number-preview", params={"kind": kind, "scheme": scheme}).json()
    check(j.get("valid") and j["preview"].startswith(want) and j.get("yearly") is yearly, f"#1382: preview of {kind} {j}")
j = A.get(B + O + "/number-preview", params={"kind": "invoice", "scheme": "RE-{yyyy}"}).json()
check(not j["valid"] and "running number" in j["error"] and "{seq}" in j["error"], "#1382: plain error without {seq}: " + str(j))
j = A.get(B + O + "/number-preview", params={"scheme": "RE-{jahr}-{seq}"}).json()
check(not j["valid"] and "{jahr}" in j["error"] and "{yyyy}" in j["error"], "#1382: plain error names the unknown block: " + str(j))
r = A.put(B + O + "/settings", json={"credit_scheme": "GS/{seq}"})
check(r.status_code == 400 and r.json()["error"].startswith("Credit note numbers:"), "#1382: the settings error names the scheme " + r.text[:160])
r = A.put(B + O + "/settings", json={"invoice_scheme": ""})
check(r.status_code == 400 and "empty" in r.json()["error"], "#1382: an empty scheme " + r.text[:160])


print(f"p2400_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
