#!/usr/bin/env python3
"""2.138.0 API tests, part D, own container (start.sh, a fresh one per section). Invented companies and names only.
(taken over from the 2.114.0 A / C suites, only the cases of #2256 #2060)
#2256 number ranges of the office:
 - GET /api/office/number-ranges: every series (offer, invoice, credit, reminder, delivery) with scheme, counter period
   (the current year with {yyyy}/{yy}, '' without), last value, next, smallest allowed next value, a preview
 - POST /api/office/number-ranges/<kind> {next, reason?}: admin only; next invoice number 1001 -> the next finalised
   invoice carries it; down / equal to the last given = 400; an invoice / credit note jump without reason = 400, with one
   ok + office log entry (reason kept); a quotation jump needs no reason (logged as well); the same next value = no-op;
   quotations counted per client have no series (not listed, 400)
 - a draft's number by hand (POST /api/office/docs/<id>/number): a quotation's number changed and back, a number
   already used = 400, a sent quotation = 409, an invoice draft with a gap needs a reason and is kept afterwards
 - rights (tenant-matrix: office): a member reads, writes 403; an agent 403; another organisation has its own counters
 - a person without an organisation (freelancer-matrix: office): the same in the personal office, own counters
usage: p2138_d_api_test.py <datadir>      (P2138D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh -
       then only one section, P2138D_PART=numranges|rules, default numranges)"""
import os
import subprocess
import sys
import time

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
NOSTART = os.environ.get("P2138D_NOSTART") == "1"


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


def start():
    if not NOSTART:
        r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        time.sleep(0.8)


# ================================================================ #2256 number ranges
def part_numranges():
    start()
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    A = sess("alice")
    A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
    for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
        r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
        assert r.ok, r.text
    Bo, Ca = sess("bob"), sess("carol")
    FEAT = "cal,comments,collab,office,clients,agents"
    for s in (A, Bo, Ca):
        s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    me = lambda s: s.get(B + "/api/state").json()["me"]["id"]  # noqa: E731
    ALICE, CAROL = me(A), me(Ca)
    ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
    ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
    for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
        s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
    O = "/api/office"
    COMPANY = {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
               "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}
    CLIENTS = {}
    NR = O + "/number-ranges"
    D = O + "/docs"
    Y = str(testclock.today().year)


    def ranges(s):
        r = s.get(B + NR)
        assert r.ok, r.text
        return {x["kind"]: x for x in r.json()["ranges"]}


    def draft(s, kind="invoice", client=False):
        extra = {"client_id": CLIENTS[id(s)], "service_from": testclock.today().isoformat()} if client else {}
        r = s.post(B + D, json={"kind": kind, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}], **extra})
        assert r.status_code == 201, r.text
        return r.json()["id"]


    def log(s):
        return [x for x in s.get(B + O + "/log?limit=100").json()["log"] if x["action"] == "number" and x.get("target") == "number_range"]


    def suite(s, who, other=None):
        """The whole flow for one office area (an organisation's admin or a freelancer in the personal office)."""
        r = s.put(B + O + "/settings", json={"offer_scheme": "A-{seq:03}", "invoice_scheme": "RE-{yyyy}-{seq:03}", "credit_scheme": "GS-{yy}{seq:03}",
                                             "lang": "de", "currency": "EUR", "company_fields": COMPANY})
        check(r.ok, f"{who}: schemes " + r.text[:200])
        CLIENTS[id(s)] = s.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt",
                                                          "country": "DE"}).json()["id"]
        rg = ranges(s)
        check(set(rg) == {"offer", "invoice", "credit", "reminder", "delivery"}, f"{who}: every series {sorted(rg)}")
        check(rg["invoice"]["period"] == Y and rg["invoice"]["yearly"] and rg["offer"]["period"] == "" and not rg["offer"]["yearly"],
              f"{who}: a yearly scheme counts in the current year, one without a year for ever {rg['invoice']['period']!r} {rg['offer']['period']!r}")
        check(rg["credit"]["period"] == Y, f"{who}: {{yy}} is yearly too")
        check(rg["invoice"]["last"] == 0 and rg["invoice"]["next"] == 1 and rg["invoice"]["min_next"] == 1, f"{who}: a fresh series {rg['invoice']}")
        check(rg["invoice"]["preview"] == f"RE-{Y}-001" and rg["invoice"]["reason_needed"] and not rg["offer"]["reason_needed"], f"{who}: preview {rg['invoice']['preview']}")

        # invoices: a jump only with a reason (GoBD), then the next invoice carries the number
        r = s.post(B + NR + "/invoice", json={"next": 1001})
        check(r.status_code == 400 and "reason" in r.json().get("error", ""), f"{who}: an invoice jump without reason = 400 {r.status_code} {r.text[:160]}")
        r = s.post(B + NR + "/invoice", json={"next": 1001, "reason": "abc"})
        check(r.status_code == 400, f"{who}: a too short reason = 400")
        r = s.post(B + NR + "/invoice", json={"next": 1001, "reason": "Nummern bis 1000 im Altprogramm vergeben"})
        check(r.ok and r.json()["next"] == 1001 and r.json()["last"] == 1000 and r.json()["preview"] == f"RE-{Y}-1001", f"{who}: invoice next 1001 " + r.text[:200])
        lg = log(s)
        check(lg and lg[0]["detail"]["after"].get("reason") == "Nummern bis 1000 im Altprogramm vergeben" and lg[0]["detail"]["before"]["next"] == 1
              and lg[0]["detail"]["after"]["next"] == 1001, f"{who}: the jump is in the office log {lg[:1]}")
        # 2.138.0 D (#2256): an invoice gets its number only when finalised (2.126.0 A, #1966)
        i1 = draft(s, "invoice", client=True)
        r = s.post(B + f"{D}/{i1}/finalize")
        check(r.ok and r.json().get("number") == f"RE-{Y}-1001", f"{who}: the next invoice carries 1001 when finalised " + r.text[:200])
        # never down, never to the last given value
        for n in (1001, 500, 0, -3, "x"):
            r = s.post(B + NR + "/invoice", json={"next": n, "reason": "zurück auf alte Nummer"})
            check(r.status_code == 400, f"{who}: next {n!r} after 1001 was given = 400 ({r.status_code})")
        r = s.post(B + NR + "/invoice", json={"next": 1002})
        check(r.ok and r.json()["next"] == 1002, f"{who}: the same next value again = no change, no reason needed " + r.text[:120])
        check(len(log(s)) == len(lg), f"{who}: a no-op writes no log entry")
        r = s.post(B + NR + "/credit", json={"next": 20})
        check(r.status_code == 400, f"{who}: a credit note jump without reason = 400")
        r = s.post(B + NR + "/nonsense", json={"next": 20})
        check(r.status_code == 400, f"{who}: an unknown series = 400")

        # quotations: a jump without reason (logged all the same); reminders the same
        r = s.post(B + NR + "/offer", json={"next": 250})
        check(r.ok and r.json()["preview"] == "A-250", f"{who}: quotation next 250 without reason " + r.text[:160])
        check(len(log(s)) == len(lg) + 1 and log(s)[0]["detail"]["before"]["kind"] == "offer", f"{who}: the quotation jump is logged too")
        check(s.post(B + NR + "/reminder", json={"next": 7}).ok, f"{who}: reminder next 7 without reason")
        o1 = draft(s, "offer")
        d1 = s.get(B + f"{D}/{o1}").json()
        check(d1.get("number") == "A-250", f"{who}: a new quotation gets A-250 ({d1.get('number')})")
        check(ranges(s)["offer"]["next"] == 251, f"{who}: the counter follows")

        # a draft's number by hand: changed, back again (undo), a used one = 400, a sent one = 409
        o2 = draft(s, "offer")
        r = s.post(B + f"{D}/{o2}/number", json={"number": "A-900"})
        check(r.ok and r.json()["number"] == "A-900", f"{who}: a quotation number by hand " + r.text[:160])
        lst = [x for x in s.get(B + D + "?kind=offer").json()["docs"] if x["id"] == o2]
        check(lst and lst[0]["number"] == "A-900", f"{who}: the list shows the new number at once {lst}")
        check(ranges(s)["offer"]["next"] == 252, f"{who}: a quotation's own number leaves the counter as it is")
        r = s.post(B + f"{D}/{o2}/number", json={"number": "A-251"})
        check(r.ok and r.json()["number"] == "A-251", f"{who}: and back (the undo step) " + r.text[:160])
        r = s.post(B + f"{D}/{o2}/number", json={"number": "A-250"})
        check(r.status_code == 400, f"{who}: a number already used = 400 ({r.status_code})")
        r = s.post(B + f"{D}/{o1}/status", json={"status": "sent"})
        check(r.ok, f"{who}: quotation sent " + r.text[:120])
        r = s.post(B + f"{D}/{o1}/number", json={"number": "A-901"})
        check(r.status_code == 409, f"{who}: a sent quotation keeps its number (409, {r.status_code})")
        # an invoice draft by hand: a gap needs a reason, the series follows
        i2 = draft(s, "invoice")
        r = s.post(B + f"{D}/{i2}/number", json={"number": f"RE-{Y}-1010"})
        check(r.status_code == 400, f"{who}: an invoice draft number with a gap and no reason = 400")
        r = s.post(B + f"{D}/{i2}/number", json={"number": f"RE-{Y}-1010", "reason": "Lücke für Altbestand"})
        check(r.ok and ranges(s)["invoice"]["next"] == 1011, f"{who}: with reason ok, the series continues from it " + r.text[:120])
        check(s.delete(B + f"{D}/{i2}").status_code == 409, f"{who}: an invoice draft numbered by hand is kept (no gaps)")
        # 2.138.0 D (#2256): quotations counted per client (2.118.0 A, #2265) have no single series
        check(s.put(B + O + "/settings", json={"offer_counter": "client"}).ok, f"{who}: quotation counter per client")
        check("offer" not in ranges(s), f"{who}: no quotation series while it counts per client {sorted(ranges(s))}")
        check(s.post(B + NR + "/offer", json={"next": 900}).status_code == 400, f"{who}: no quotation series to set (400)")
        check(s.put(B + O + "/settings", json={"offer_counter": "org"}).ok and ranges(s)["offer"]["next"] == 252, f"{who}: back to one counter, unchanged")
        if other is not None:
            check(ranges(other)["invoice"]["last"] == 0, f"{who}: another office area keeps its own counters")


    # ---------------------------------------------------------------- an organisation's admin
    suite(A, "admin", other=Ca)

    # ---------------------------------------------------------------- rights (tenant-matrix: office)
    rb = Bo.get(B + NR)
    check(rb.ok and rb.json()["admin"] is False and {x["kind"]: x for x in rb.json()["ranges"]}["invoice"]["last"] == 1010,
          f"a member reads the series of the organisation {rb.status_code}")
    check(A.get(B + NR).json()["admin"] is True, "the admin flag")
    r = Bo.post(B + NR + "/offer", json={"next": 999})
    check(r.status_code == 403, f"a member cannot set the next number ({r.status_code})")
    check(ranges(A)["offer"]["next"] == 252, "unchanged after the member's try")
    check(Ca.post(B + NR + "/offer", json={"next": 77}).ok and ranges(A)["offer"]["next"] == 252, "another organisation changes only its own series")
    ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"})
    check(ag.status_code == 201, "an agent " + ag.text[:200])
    if ag.ok:
        hd = {**H, "Authorization": "Bearer " + ag.json()["token"]}
        check(requests.get(B + NR, headers=hd).status_code in (401, 403), "an agent cannot read the number ranges")
        check(requests.post(B + NR + "/offer", headers=hd, json={"next": 5000}).status_code in (401, 403), "an agent cannot set them")

    # ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
    FID, Fr = freelancer(B, A)
    check(Fr.get(B + NR).json()["admin"] is True, "a freelancer is the admin of the personal office")
    suite(Fr, "freelancer", other=Ca)
    check(ranges(A)["invoice"]["next"] == 1011 and ranges(Fr)["offer"]["next"] == 252, "the personal office and the organisation count apart")


PARTS = {"numranges": part_numranges}
for name in ([os.environ.get("P2138D_PART") or "numranges"] if NOSTART else PARTS):
    PARTS[name]()
print(f"p2138_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
