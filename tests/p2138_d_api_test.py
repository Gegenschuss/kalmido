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
#2060 rules (freelancer-matrix: lists):
 - triggers created, assigned (one person / anybody; only when the person is new, not via an approval request) and field
   (any change / a selection option / checked / unchecked); actions priority, tag (a list tag), field (a fixed value)
 - loop protection depth 0 stays: a value set by a rule never starts a "field changed" rule
 - invalid references 400 (formula field, wrong value type, unknown option, a tag of another list, a person outside the
   list, a checkbox trigger without a checkbox value)
 - only the owner / a list admin creates rules (an edit member 403); a deleted field / list tag pauses the rule
 - agents read and propose the new kinds; OpenAPI lists every enum value
 - a person without an organisation (freelancer) has the new rules in a private list
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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
NOSTART = os.environ.get("P2138D_NOSTART") == "1"


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


# ================================================================ #2060 rule triggers / actions
def part_rules():
    start()
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
    A = sess("alice")
    A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
    A.patch(B + "/api/settings", json={"lang": "en"})
    ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
    uid = {}
    for u in ("bob", "carol"):
        r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                           "email": f"{u}@example.com"})
        assert r.ok, r.text
        uid[u] = r.json()["id"]
    BOB, CAROL = uid["bob"], uid["carol"]
    ALICE = A.get(B + "/api/state").json()["me"]["id"]
    Bo, Ca = sess("bob"), sess("carol")
    OUT, Out = freelancer(B, A, "otto")  # someone outside the lists of alice


    def mklist(s, name, org=ORG):
        r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
        assert r.ok, r.text
        lid = r.json()["id"]
        if s is A and org:
            s.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"})
            s.put(B + f"/api/lists/{lid}/members", json={"user_id": CAROL, "role": "edit"})
        return lid


    def field(s, lid, name, ftype, **k):
        r = s.post(B + f"/api/lists/{lid}/fields", json={"name": name, "type": ftype, **k})
        assert r.ok, r.text
        return r.json()


    def task(s, lid, title, **k):
        r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
        assert r.ok, r.text
        return r.json()["id"]


    def get(s, tid):
        return s.get(B + f"/api/tasks/{tid}").json()


    def rule(s, lid, name, trig, act, code=201):
        r = s.post(B + f"/api/lists/{lid}/rules", json={"name": name, "trigger": trig, "action": act})
        check(r.status_code == code, f"rule {name}: {code} (got {r.status_code} {r.text[:200]})")
        return r.json().get("id") if r.ok else None


    def rules(s, lid):
        return {r["id"]: r for r in s.get(B + f"/api/lists/{lid}/rules").json()["rules"]}


    def comments(s, tid, name):
        return [c for c in s.get(B + f"/api/tasks/{tid}/timeline").json()["comments"] if c.get("rule_name") == name]


    def ltags(s, tid):
        return get(s, tid).get("ltags") or []


    # ---- created -> priority high (also for a task bob creates; history marks the rule)
    L1 = mklist(A, "Inbox work")
    check(Bo.post(B + f"/api/lists/{L1}/rules", json={"name": "x", "trigger": {"kind": "created"},
                                                      "action": {"kind": "priority", "priority": "high"}}).status_code == 403,
          "an edit member cannot add a rule with the new kinds (403)")
    rule(A, L1, "bad prio", {"kind": "created"}, {"kind": "priority", "priority": "urgent"}, 400)
    R1 = rule(A, L1, "Hot", {"kind": "created"}, {"kind": "priority", "priority": "high"})
    t1 = task(Bo, L1, "New lead")
    check(get(A, t1).get("priority") == 5, f"created -> priority high ({get(A, t1).get('priority')})")
    act = [a for a in A.get(B + f"/api/tasks/{t1}/timeline").json()["activity"] if (a["data"].get("rule") or {}).get("id") == R1]
    check(act and act[0]["user_id"] == ALICE, "history: the priority change is marked with the rule, run as alice")
    t1b = task(A, L1, "Later")
    A.patch(B + f"/api/tasks/{t1b}", json={"priority": 1})
    A.patch(B + f"/api/tasks/{t1b}", json={"title": "Later still"})
    check(get(A, t1b).get("priority") == 1, "a change is not a creation: the rule does not run again")

    # ---- assigned (carol -> tag hot; anybody -> comment)
    L2 = mklist(A, "Team")
    HOT = A.post(B + f"/api/lists/{L2}/tags", json={"name": "hot"}).json()["id"]
    OTHERTAG = A.post(B + f"/api/lists/{L1}/tags", json={"name": "elsewhere"}).json()["id"]
    rule(A, L2, "stranger", {"kind": "assigned", "user_id": OUT}, {"kind": "comment", "text": "x"}, 400)
    rule(A, L2, "foreign tag", {"kind": "created"}, {"kind": "tag", "tag_id": OTHERTAG}, 400)
    R2 = rule(A, L2, "Carol", {"kind": "assigned", "user_id": CAROL}, {"kind": "tag", "tag_id": HOT})
    R3 = rule(A, L2, "Anyone", {"kind": "assigned"}, {"kind": "comment", "text": "Assigned"})
    t2 = task(A, L2, "Plan")
    check(not comments(A, t2, "Anyone"), "no assignee: the assigned rule does not run")
    A.patch(B + f"/api/tasks/{t2}", json={"assignee_id": BOB})
    check(len(comments(A, t2, "Anyone")) == 1 and "hot" not in ltags(A, t2), "assigned to bob: 'anybody' runs, 'carol' does not")
    A.patch(B + f"/api/tasks/{t2}", json={"title": "Plan 2"})
    check(len(comments(A, t2, "Anyone")) == 1, "the same person again: no new run")
    A.patch(B + f"/api/tasks/{t2}", json={"assignee_id": CAROL})
    check(len(comments(A, t2, "Anyone")) == 2 and "hot" in ltags(A, t2), f"assigned to carol: tag hot ({ltags(A, t2)})")
    t2b = task(A, L2, "Born assigned", assignee_id=CAROL)
    check("hot" in ltags(A, t2b), "created with carol as assignee: the person is new -> tag hot")
    t2c = task(A, L2, "Needs a yes")
    ap = A.post(B + f"/api/tasks/{t2c}/approval", json={"action": "request", "approver_id": CAROL})
    # 2.144.6 B (#2400 F3): an approval request hands the task to the approver, but that is no "assigned" for the rules
    check(ap.ok and "hot" not in ltags(A, t2c), f"an approval request makes carol the assignee, no rule runs ({ap.status_code} {ltags(A, t2c)})")

    # ---- field triggers / field action + loop protection
    L3 = mklist(A, "Pipeline")
    ST = field(A, L3, "Stage", "select", options={"options": [{"name": "Lead"}, {"name": "Won"}]})
    OPT = {o["name"]: o["id"] for o in ST["options"]["options"]}
    OK = field(A, L3, "Signed", "checkbox")
    HRS = field(A, L3, "Hours", "number")
    FX = field(A, L3, "Double", "formula", formula="{Hours} * 2")
    rule(A, L3, "formula", {"kind": "field", "field_id": FX["id"]}, {"kind": "priority", "priority": "low"}, 400)
    rule(A, L3, "bad option", {"kind": "field", "field_id": ST["id"], "value": "nope"}, {"kind": "priority", "priority": "low"}, 400)
    rule(A, L3, "bad checkbox", {"kind": "field", "field_id": OK["id"], "value": "yes"}, {"kind": "priority", "priority": "low"}, 400)  # 2.138.0 D (#2060, review): no checkbox value
    rule(A, L3, "bad number", {"kind": "created"}, {"kind": "field", "field_id": HRS["id"], "value": "abc"}, 400)
    rule(A, L3, "set formula", {"kind": "created"}, {"kind": "field", "field_id": FX["id"], "value": "1"}, 400)
    R4 = rule(A, L3, "Won", {"kind": "field", "field_id": ST["id"], "value": OPT["Won"]}, {"kind": "priority", "priority": "high"})
    R5 = rule(A, L3, "Signed", {"kind": "field", "field_id": OK["id"], "value": "1"}, {"kind": "field", "field_id": HRS["id"], "value": "8"})
    R6 = rule(A, L3, "Hours", {"kind": "field", "field_id": HRS["id"]}, {"kind": "comment", "text": "Hours changed"})
    R7 = rule(A, L3, "Unsigned", {"kind": "field", "field_id": OK["id"], "value": "0"}, {"kind": "priority", "priority": "low"})
    rv = rules(A, L3)
    check(rv[R4]["trigger"] == {"kind": "field", "field_id": ST["id"], "value": OPT["Won"]} and rv[R4]["names"].get("value") == "Won",
          f"GET: the field trigger with its option name ({rv[R4]['trigger']}, {rv[R4]['names']})")
    check(rv[R7]["trigger"].get("value") == "0" and rv[R5]["action"] == {"kind": "field", "field_id": HRS["id"], "value": "8"},
          f"GET: unchecked = '0', the action keeps its value ({rv[R7]['trigger']}, {rv[R5]['action']})")
    t3 = task(A, L3, "Deal")
    Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(ST["id"]): OPT["Lead"]}})
    check(get(A, t3).get("priority") == 0, "Stage = Lead: the 'Won' rule does not run")
    Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(ST["id"]): OPT["Won"]}})
    check(get(A, t3).get("priority") == 5, "Stage = Won -> priority high")
    Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(OK["id"]): True}})
    x = get(A, t3)
    check((x.get("fields") or {}).get(str(HRS["id"])) == "8", f"checked -> Hours set to 8 by the rule ({x.get('fields')})")
    check(not comments(A, t3, "Hours changed") and not comments(A, t3, "Hours"),
          "depth 0: the value the rule set does not start the 'Hours changed' rule")
    Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(HRS["id"]): "3"}})
    check(len(comments(A, t3, "Hours")) == 1, "a person changes Hours -> the field rule runs once")
    Bo.patch(B + f"/api/tasks/{t3}", json={"title": "Deal 2"})
    check(len(comments(A, t3, "Hours")) == 1, "another change: the field rule does not run")
    Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(OK["id"]): None}})
    check(get(A, t3).get("priority") == 1, "unchecked -> priority low")
    t3b = task(A, L3, "Signed at once", fields={str(OK["id"]): True})
    check((get(A, t3b).get("fields") or {}).get(str(HRS["id"])) == "8", "created with the box checked: the field rule runs")

    # switching a rule off and on again re-checks the stored trigger / action (round trip of GET -> PATCH)
    check(A.patch(B + f"/api/rules/{R5}", json={"active": False}).ok and A.patch(B + f"/api/rules/{R5}", json={"active": True}).ok,
          "a field rule can be switched off and on again")

    # ---- deleted field / tag -> paused
    check(A.delete(B + f"/api/fields/{HRS['id']}").ok, "the field Hours is deleted")
    rv = rules(A, L3)
    check(not rv[R5]["active"] and rv[R5]["paused_reason"] == "field" and rv[R6]["paused_reason"] == "field",
          f"rules using the deleted field pause: field ({rv[R5]['paused_reason']}, {rv[R6]['paused_reason']})")
    check(A.delete(B + f"/api/list-tags/{HOT}").ok, "the tag hot is deleted")
    rv2 = rules(A, L2)
    check(rv2[R2]["paused_reason"] == "tag" and rv2[R3]["active"], f"the tag rule pauses: tag ({rv2[R2]['paused_reason']})")

    # ---- agents: read + propose the new kinds; OpenAPI
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "robo", "display_name": "Robo"})
    assert r.ok, r.text
    AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
    A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
    A.put(B + f"/api/lists/{L3}/members", json={"user_id": AG, "role": "edit"})
    g = requests.get(V + f"/lists/{L3}/rules", headers=AGH)
    check(g.ok and {r["trigger"]["kind"] for r in g.json()["data"]} >= {"field"}, f"agent reads field rules ({g.status_code})")
    pp = requests.post(V + f"/lists/{L3}/rules/proposals", headers=AGH, json={"name": "Agent stage", "summary": "Saves time",
                       "trigger": {"kind": "created"}, "action": {"kind": "field", "field_id": ST["id"], "value": OPT["Lead"]}})
    check(pp.status_code == 201, f"agent proposes a created -> field rule ({pp.status_code} {pp.text[:200]})")
    if pp.ok:
        v = A.get(B + f"/api/proposals/{pp.json()['id']}").json()
        check((v.get("rule_view") or {}).get("names", {}).get("value_to") == "Lead", f"the card names the value ({v.get('rule_view')})")
        ac = A.post(B + f"/api/proposals/{pp.json()['id']}/apply", json={"select": ["0"]})
        check(ac.ok, f"alice accepts ({ac.status_code})")
        t4 = task(A, L3, "From the agent's rule")
        check((get(A, t4).get("fields") or {}).get(str(ST["id"])) == OPT["Lead"], "the accepted rule sets Stage = Lead on new tasks")
    pa = requests.post(V + f"/lists/{L3}/rules/proposals", headers=AGH, json={"name": "a", "trigger": {"kind": "assigned", "user_id": OUT},
                       "action": {"kind": "priority", "priority": "medium"}})
    check(pa.status_code == 400, f"agent: assigned to someone outside the list -> 400 ({pa.status_code})")
    sch = requests.get(V + "/openapi.json").json()["components"]["schemas"]["ListRule"]["properties"]
    check(set(sch["trigger"]["properties"]["kind"]["enum"]) >= {"created", "assigned", "field"}
          and set(sch["action"]["properties"]["kind"]["enum"]) >= {"priority", "tag", "field"}
          and sch["action"]["properties"]["priority"]["enum"] == ["none", "low", "medium", "high"], "OpenAPI: every new enum value")

    # ---- a person without an organisation: private list with the new rules (freelancer-matrix: lists)
    FID, Fr = freelancer(B, A, "frida")
    FL = Fr.post(B + "/api/lists", json={"name": "Gigs", "org_id": None}).json()["id"]
    FB = field(Fr, FL, "Paid", "checkbox")
    FT = Fr.post(B + f"/api/lists/{FL}/tags", json={"name": "done-paid"}).json()["id"]
    rule(Fr, FL, "Prio", {"kind": "created"}, {"kind": "priority", "priority": "medium"})
    rule(Fr, FL, "Paid", {"kind": "field", "field_id": FB["id"], "value": "1"}, {"kind": "tag", "tag_id": FT})
    ft = task(Fr, FL, "Logo")
    check(get(Fr, ft).get("priority") == 3, "freelancer: created -> priority medium")
    Fr.patch(B + f"/api/tasks/{ft}", json={"fields": {str(FB["id"]): True}})
    check("done-paid" in ltags(Fr, ft), f"freelancer: checked -> list tag ({ltags(Fr, ft)})")
    check(A.get(B + f"/api/lists/{FL}/rules").status_code == 404, "someone else cannot see the freelancer's rules")


PARTS = {"numranges": part_numranges, "rules": part_rules}
for name in ([os.environ.get("P2138D_PART") or "numranges"] if NOSTART else PARTS):
    PARTS[name]()
print(f"p2138_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
