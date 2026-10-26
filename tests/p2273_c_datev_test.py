#!/usr/bin/env python3
"""2.273.0 C (#3051 point 9): the undo of a DATEV master data run leaves a supplier that was changed since (an IBAN filled
in by a later run) and counts it (kept.suppliers); an unchanged one goes as before. Invented companies and accounts only
(EXTF files written here). freelancer-matrix: office
 - run 1 makes supplier 70020 without IBAN, run 2 fills its IBAN; undoing run 1 keeps the supplier with the IBAN, undoing
   run 2 empties the IBAN again; a supplier of a run that nothing changed is removed by its undo
 - the same for a person without an organisation (personal office)
usage: p2273_c_datev_test.py <datadir>   (P2273CD_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

O = "/api/office"
I = O + "/datev/import"
COLS16 = ("Konto", "Name (Adressatentyp Unternehmen)", "Straße", "Postleitzahl", "Ort", "IBAN-Nr. 1")


def q(v):
    return '"' + str(v).replace('"', '""') + '"' if v != "" else ""


def extf16(rows):
    f = ['"EXTF"', "700", "16", '"Debitoren/Kreditoren"', "5", "20260101120000000", "", '"RE"', '""', '""', "1234567", "12345", "20260101", "4"]
    lines = [";".join(f + [""] * (31 - len(f))), ";".join(q(c) for c in COLS16)]
    lines += [";".join(q(r.get(c, "")) for c in COLS16) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def up(s, raw):
    r = s.post(B + I, files={"file": ("extf.csv", raw, "text/csv")})
    check(r.status_code == 201, "import " + r.text[:200])
    return r.json()["run_id"]


def sups(s):
    return {x["account_no"]: x for x in s.get(B + O + "/datev/suppliers").json()["items"]}


def run(s, who):
    r1 = up(s, extf16([{"Konto": "70020", "Name (Adressatentyp Unternehmen)": "Papier Muster GmbH", "Ort": "Halle"},
                       {"Konto": "70021", "Name (Adressatentyp Unternehmen)": "Druck Beispiel KG", "Ort": "Jena"}]))
    check(set(sups(s)) == {"70020", "70021"} and not sups(s)["70020"].get("iban"), f"{who}: run 1 made two suppliers without IBAN {sups(s)}")
    r2 = up(s, extf16([{"Konto": "70020", "Name (Adressatentyp Unternehmen)": "Papier Muster GmbH", "Ort": "Halle", "IBAN-Nr. 1": "DE02 1203 0000 0000 2020 51"}]))
    check(sups(s)["70020"].get("iban") == "DE02120300000000202051", f"{who}: run 2 filled the IBAN {sups(s).get('70020')}")
    r = s.post(B + I + f"/{r1}/undo")
    check(r.ok and r.json()["kept"].get("suppliers") == 1 and r.json()["removed"]["suppliers"] == 1, f"{who}: undo of run 1 keeps the changed supplier " + r.text[:200])
    sp = sups(s)
    check(set(sp) == {"70020"} and sp["70020"].get("iban") == "DE02120300000000202051", f"{who}: supplier with the IBAN stays, the unchanged one is gone {sp}")
    r = s.post(B + I + f"/{r2}/undo")
    check(r.ok and not sups(s)["70020"].get("iban"), f"{who}: undo of run 2 empties the IBAN again {r.text[:200]} {sups(s)}")


kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0"}, prefix="P2273CD")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done", "workspace": f"org:{ORG}"})
r = A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
assert r.ok, r.text
FID, Er = freelancer(B, A, "erin")

run(A, "alice")
run(Er, "erin")
sys.exit(kt.done("p2273_c_datev"))
