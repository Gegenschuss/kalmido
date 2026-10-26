#!/usr/bin/env python3
"""2.299.0 B (#3191) API tests: bank rules -- bookings marked by rule after an import, rules learned from what a person
confirms, own container (start.sh through kt.fresh, org encryption on). Invented companies, people, accounts and figures only.
tenant-matrix: office  freelancer-matrix: office
 - a rule (counterpart word part / IBAN / purpose word / amount range / direction) -> private | ignored | noreceipt marks the
   open bookings it decides (apply_open), the next import marks on its own ("ruled" in the answer); the booking shows
   by_rule with the rule's name; unmatch lifts it (rule_id NULL); never a booking matched already
 - specificity: IBAN beats the name, an amount range counts; a tie of rules with different outcomes marks nothing (rule_hint
   tie); a switched-off rule does nothing (apply 409); delete + restore; "undo its marks" opens what the rule marked
 - learning: the second same mark of a counterpart (name, else IBAN) answers a rule suggestion, a declined one is not asked
   again; a receipt of the same category twice -> a category suggestion; a category rule names the category of a receipt
   matched by hand when it has none (never a match by rule)
 - an import with bookings marked by rule can be taken back (and restored, marked again)
 - a locked month stays untouched (apply counts it, revert leaves it)
 - two imports / two applies at the same moment mark every booking once (hits = marks)
 - rights: a member 403, another organisation 404, an agent 403; a person without an organisation does all of it the same
   way in the personal office; texts, IBAN and amounts of a rule encrypted at rest
 - the rule action noreceipt marks only once part C (#3192, match_kind noreceipt) is in this branch (else skipped)
usage: p2299_b_bankrules_test.py <datadir>"""
import base64
import os
import sys
import threading
from datetime import timedelta

import kt
from kt import B, H, check, dbx, sess
from freelancer_fixture import freelancer
import testclock

KEY = base64.b64encode(os.urandom(32)).decode()
SKIPS = []
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2299B")
import requests  # noqa: E402

A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients,files,docs"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
K = "/api/office/bank"
R = K + "/rules"
TODAY = testclock.today()
DAY = [(TODAY - timedelta(days=n)).isoformat() for n in range(0, 21)]
OLD = (TODAY - timedelta(days=100)).isoformat()  # a month that gets locked at the end
OLD_M = OLD[:7]
IB1, IB2, IB3 = "DE89370400440532013000", "DE75512108001245126199", "DE44500105175407324931"
REF = [0]


def camt(rows):
    """A CAMT.053 statement made here: rows (signed amount, day, name, IBAN or None, purpose)."""
    out = []
    for amt, day, name, iban, purpose in rows:
        REF[0] += 1
        who, acc = ("Dbtr", "DbtrAcct") if amt > 0 else ("Cdtr", "CdtrAcct")
        ib = f"<{acc}><Id><IBAN>{iban}</IBAN></Id></{acc}>" if iban else ""
        out.append(f'<Ntry><Amt Ccy="EUR">{abs(amt):.2f}</Amt><CdtDbtInd>{"CRDT" if amt > 0 else "DBIT"}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
                   f"<BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>P2299B-{REF[0]:05d}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties>"
                   f"<{who}><Pty><Nm>{name}</Nm></Pty></{who}>{ib}</RltdPties><RmtInf><Ustrd>{purpose}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
            f'<Id>S{REF[0]}</Id>{"".join(out)}</Stmt></BkToCstmrStmt></Document>')


def imp(s, rows):
    r = s.post(B + K + "/import", json={"text": camt(rows), "filename": "auszug.xml"})
    assert r.status_code == 201, r.text
    return r.json()


def txs(s):
    return s.get(B + K + "/tx?state=all").json()["items"]


def tx(s, purpose):
    m = [t for t in txs(s) if t["purpose"] == purpose]
    assert len(m) == 1, (purpose, len(m))
    return m[0]


def rule(s, **spec):
    r = s.post(B + R, json=spec)
    assert r.status_code == 201, r.text
    return r.json()


def db_tx(tid):
    return dict(dbx("SELECT match_kind, rule_id, matched_by FROM office_bank_tx WHERE id=?", (tid,))[0])


r = A.post(B + K + "/tx/0/match", json={"kind": "noreceipt"})
NORC = r.status_code == 404  # part C (#3192) knows the kind (unknown booking = 404), else 400 (unknown kind)
if not NORC:
    SKIPS.append("action noreceipt: part C (#3192, match_kind noreceipt) is not in this branch yet")

# ======================================================================== the same flow in an organisation and the personal office
for who, s in (("org", A), ("freelancer", Fr)):
    p = f"{who}: "
    imp(s, [(-9.90, DAY[3], "Bank Beispiel AG", None, f"Kontofuehrung {who} 1"), (-45.00, DAY[3], "Druckerei Beispiel", IB2, f"Flyer {who}"),
            (-12.00, DAY[2], "Druckerei Beispiel", None, f"Visitenkarten {who}"), (-20.00, DAY[2], "Laden Beispiel", None, f"Einkauf {who}"),
            (-30.00, DAY[2], "Tankstelle Beispiel", None, f"Tanken klein {who}"), (-80.00, DAY[2], "Tankstelle Beispiel", None, f"Tanken gross {who}"),
            (-5.00, DAY[4], "Kiosk Beispiel", None, f"Kiosk {who} 1"), (-6.00, DAY[4], "Kiosk Beispiel", None, f"Kiosk {who} 2"),
            (-7.00, DAY[4], "Kiosk Beispiel", None, f"Kiosk {who} 3"), (-3.00, DAY[5], "Spende Verein", IB3, f"Spende {who} 1"),
            (-4.00, DAY[5], "Spendenkonto", IB3, f"Spende {who} 2"), (150.00, DAY[5], "Bank Beispiel AG", None, f"Zinsen {who}")])

    # ---- validation
    for bad, why in (({"action": "private"}, "no condition"), ({"counterpart": "x y", "action": "nope"}, "unknown action"),
                     ({"iban": "DE12", "action": "private"}, "bad IBAN"), ({"counterpart": "Laden", "action": "category"}, "category without one"),
                     ({"counterpart": "Laden", "action": "private", "amount_min": "50", "amount_max": "10"}, "min above max"),
                     ({"counterpart": "Laden", "action": "private", "direction": "up"}, "unknown direction"),
                     ({"counterpart": "Laden", "action": "private", "amount_min": "abc"}, "an amount that is no number")):
        check(s.post(B + R, json=bad).status_code == 400, p + f"a rule with {why} is 400")

    # ---- a rule marks the open bookings it decides; direction out leaves the interest alone
    j = rule(s, name="Bankgebuehren", counterpart="bank beispiel", direction="out", action="ignored", apply_open=True)
    RB = j["rule"]["id"]
    check(j["applied"] == 1 and j["locked"] == 0 and j["rule"]["name"] == "Bankgebuehren" and j["rule"]["hits"] == 1, p + f"apply_open marked one booking {j}")
    t = tx(s, f"Kontofuehrung {who} 1")
    check(t["match"] and t["match"]["kind"] == "ignored" and t["match"]["by_rule"] == {"id": RB, "name": "Bankgebuehren"}, p + f"the booking shows by rule {t['match']}")
    check(db_tx(t["id"]) == {"match_kind": "ignored", "rule_id": RB, "matched_by": None}, p + "stored: rule_id, nobody matched it by hand")
    check(tx(s, f"Zinsen {who}")["match"] is None, p + "direction out: the money in stays open")
    # the next import marks on its own
    j = imp(s, [(-9.90, DAY[1], "BANK BEISPIEL AG", None, f"Kontofuehrung {who} 2")])
    t2 = tx(s, f"Kontofuehrung {who} 2")
    check(j["ruled"] == 1 and t2["match"]["kind"] == "ignored" and t2["match"]["by_rule"]["id"] == RB, p + f"the import marked by rule (case does not matter) {j.get('ruled')}")
    # unmatch lifts the rule's mark
    r = s.post(B + f"{K}/tx/{t2['id']}/unmatch")
    check(r.ok and r.json()["item"]["match"] is None and db_tx(t2["id"])["rule_id"] is None, p + "unmatch lifts a rule's mark (rule_id NULL)")

    # ---- specificity: IBAN beats the name; an amount range
    RD = rule(s, counterpart="Druckerei", action="private")["rule"]["id"]
    RI = rule(s, iban=IB2.lower(), action="ignored")["rule"]["id"]
    ja, jb = s.post(B + f"{R}/{RD}/apply").json(), s.post(B + f"{R}/{RI}/apply").json()
    check(ja["applied"] == 1 and jb["applied"] == 1, p + f"each rule marks only what it decides {ja} {jb}")
    check(tx(s, f"Flyer {who}")["match"]["kind"] == "ignored" and tx(s, f"Visitenkarten {who}")["match"]["kind"] == "private",
          p + "the IBAN rule decides the booking with that IBAN, the name rule the other")
    rule(s, counterpart="Tankstelle", amount_max="50", action="private", apply_open=True)
    check(tx(s, f"Tanken klein {who}")["match"]["kind"] == "private" and tx(s, f"Tanken gross {who}")["match"] is None, p + "the amount range: 30 marked, 80 not")
    # ---- a tie with different outcomes marks nothing, the booking names it
    rule(s, counterpart="Laden", action="private")
    j = rule(s, counterpart="Laden Beispiel", action="ignored", apply_open=True)
    t = tx(s, f"Einkauf {who}")
    check(t["match"] is None and t.get("rule_hint", {}).get("tie") is True and j["applied"] == 0, p + f"tie: nothing marked, the hint says so {t.get('rule_hint')}")
    # ---- never over a match by hand
    k1 = tx(s, f"Kiosk {who} 1")
    r = s.post(B + f"{K}/tx/{k1['id']}/match", json={"kind": "private"})
    check(r.ok and r.json().get("rule_suggestion") is None, p + "learning: the first private mark asks nothing")
    k2 = tx(s, f"Kiosk {who} 2")
    r = s.post(B + f"{K}/tx/{k2['id']}/match", json={"kind": "private"})
    sug = r.json().get("rule_suggestion") or {}
    check(r.ok and sug.get("action") == "private" and sug.get("counterpart") == "Kiosk Beispiel" and sug.get("count") == 2 and sug.get("iban") is None,
          p + f"learning: the second time the same way -> a suggestion {sug}")
    check(s.post(B + R + "/decline", json={"counterpart": "Kiosk Beispiel"}).ok, p + "decline the suggestion")
    k3 = tx(s, f"Kiosk {who} 3")
    r = s.post(B + f"{K}/tx/{k3['id']}/match", json={"kind": "private"})
    check(r.ok and r.json().get("rule_suggestion") is None, p + "a declined suggestion is not asked again")
    j = rule(s, counterpart="Kiosk", action="ignored", apply_open=True)
    dk = [db_tx(x["id"]) for x in (k1, k2, k3)]
    check(j["applied"] == 0 and all(d["match_kind"] == "private" and d["rule_id"] is None and d["matched_by"] for d in dk), p + f"a new rule never changes a match by hand {dk}")
    # learning by IBAN (two names, the same account)
    for n in (1, 2):
        r = s.post(B + f"{K}/tx/{tx(s, f'Spende {who} {n}')['id']}/match", json={"kind": "ignored"})
    sug = r.json().get("rule_suggestion") or {}
    check(sug.get("iban") == IB3 and sug.get("action") == "ignored", p + f"learning by the IBAN {sug}")
    j = rule(s, iban=sug["iban"], action="ignored", apply_open=True)
    check(j["applied"] == 0, p + "the rule from the suggestion leaves the two marked by hand as they are")

    # ---- switched off, delete, restore, the list
    r = s.put(B + f"{R}/{RB}", json={"active": False})
    check(r.ok and r.json()["rule"]["active"] is False, p + "switched off")
    check(s.post(B + f"{R}/{RB}/apply").status_code == 409, p + "a switched-off rule cannot be applied (409)")
    j = imp(s, [(-9.90, DAY[0], "Bank Beispiel AG", None, f"Kontofuehrung {who} 3")])
    check(j["ruled"] == 0 and tx(s, f"Kontofuehrung {who} 3")["match"] is None, p + "a switched-off rule marks nothing on import")
    check(s.put(B + f"{R}/{RB}", json={"active": True, "name": "Gebuehren Bank"}).ok, p + "switched on again, renamed")
    r = s.post(B + f"{R}/{RB}/apply")
    check(r.ok and r.json()["applied"] == 2, p + f"apply marks the two open ones {r.text[:200]}")
    check(tx(s, f"Kontofuehrung {who} 1")["match"]["by_rule"]["name"] == "Gebuehren Bank", p + "by rule shows the new name")
    items = s.get(B + R).json()["items"]
    check(items[0]["id"] > items[-1]["id"] and any(x["id"] == RB and x["hits"] == 4 for x in items), p + f"the list: newest first, hits counted {[(x['id'], x['hits']) for x in items]}")
    check(s.delete(B + f"{R}/{RB}").ok and not any(x["id"] == RB for x in s.get(B + R).json()["items"]), p + "deleted: not in the list")
    check(tx(s, f"Kontofuehrung {who} 1")["match"]["by_rule"]["name"] == "Gebuehren Bank", p + "a deleted rule's marks keep its name")
    check(s.post(B + f"{R}/{RB}/apply").status_code == 404 and s.put(B + f"{R}/{RB}", json={"active": False}).status_code == 404, p + "a deleted rule: 404")
    check(s.post(B + f"{R}/{RB}/restore").ok and any(x["id"] == RB for x in s.get(B + R).json()["items"]), p + "restore brings it back")
    check(s.post(B + f"{R}/{RB}/restore").status_code == 409, p + "restore of a rule that is there: 409")
    # ---- undo its marks
    r = s.post(B + f"{R}/{RB}/revert")
    check(r.ok and r.json()["undone"] == 3 and all(tx(s, f"Kontofuehrung {who} {n}")["match"] is None for n in (1, 2, 3)), p + f"undo its marks: open again {r.text[:120]}")
    check(not dbx("SELECT 1 FROM office_bank_tx WHERE rule_id=? AND match_kind IS NULL", (RB,)), p + "no rule_id left on the open ones")

    # ---- an import with marks by rule can be taken back and restored
    j = imp(s, [(-2.50, DAY[0], "Bank Beispiel AG", None, f"Gebuehr Rueck {who}"), (-1.00, DAY[0], "Jemand Anders", None, f"Rest {who}")])
    iid = j["import"]["id"]
    check(j["ruled"] == 1, p + "the import marked one by rule")
    r = s.post(B + f"{K}/imports/{iid}/undo")
    check(r.ok, p + f"take back works although a rule marked one of it {r.text[:200]}")
    r = s.post(B + f"{K}/imports/{iid}/restore")
    check(r.ok and tx(s, f"Gebuehr Rueck {who}")["match"]["kind"] == "ignored", p + "restore marks it by rule again")

    # ---- noreceipt (part C)
    if NORC:
        j = rule(s, counterpart="Finanzamt", action="noreceipt")
        imp(s, [(-100.00, DAY[1], "Finanzamt Beispielstadt", None, f"Umsatzsteuer {who}")])
        check(tx(s, f"Umsatzsteuer {who}")["match"]["kind"] == "noreceipt", p + "a noreceipt rule marks the booking")
    # ---- encrypted at rest
    enc = dbx("SELECT name, counterpart, amount_max FROM office_bank_rules WHERE counterpart<>'' AND amount_max<>''")
    check(enc and all(str(v).startswith("kenc1:") for row in enc for v in row), p + f"name, counterpart, amount of a rule encrypted at rest {enc[:1]}")
    enc = dbx("SELECT iban FROM office_bank_rules WHERE iban<>''")
    check(enc and all(str(row[0]).startswith("kenc1:") for row in enc), p + "the IBAN of a rule encrypted at rest")

# ======================================================================== receipts: a category rule, learning by category (organisation)
def tiny_pdf(text):
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def receipt(name, amount, day, cat):
    r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": (f"{name}.pdf", tiny_pdf(name), "application/pdf")})
    if not r.ok:
        return None
    j = r.json()
    nid = (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []] or [None])[0]
    ok = nid and A.put(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok and A.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": "19"}).ok
    return nid if ok else None


N1 = receipt("Software Abo Beispiel", "119.00", DAY[6], "")
if not N1:
    SKIPS.append("receipts: no receipt could be made (documents area)")
else:
    rule(A, counterpart="Software Beispiel", action="category", category="Software", account="4806")
    imp(A, [(-119.00, DAY[6], "Software Beispiel GmbH", None, "Abo Oktober")])
    t = tx(A, "Abo Oktober")
    check(t["match"] is None and t.get("rule_hint", {}).get("action") == "category" and t["rule_hint"]["category"] == "Software",
          f"a category rule never matches, it shows the hint {t.get('rule_hint')}")
    r = A.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "receipt", "id": N1})
    check(r.ok and (r.json().get("rule_category") or {}).get("category") == "Software"
          and dbx("SELECT category FROM rc_receipts WHERE node_id=?", (N1,))[0][0] == "Software", "matched by hand: the receipt without category gets the rule's " + r.text[:200])
    N2, N3 = receipt("Bahn Beispiel 1", "49.00", DAY[7], "Reise"), receipt("Bahn Beispiel 2", "59.00", DAY[7], "Reise")
    imp(A, [(-49.00, DAY[7], "Bahn Beispiel", None, "Ticket 1"), (-59.00, DAY[7], "Bahn Beispiel", None, "Ticket 2")])
    A.post(B + f"{K}/tx/{tx(A, 'Ticket 1')['id']}/match", json={"kind": "receipt", "id": N2})
    r = A.post(B + f"{K}/tx/{tx(A, 'Ticket 2')['id']}/match", json={"kind": "receipt", "id": N3})
    sug = r.json().get("rule_suggestion") or {}
    check(r.ok and sug.get("action") == "category" and sug.get("category") == "Reise" and sug.get("direction") == "out", f"learning: two receipts of the same category -> a category suggestion {sug}")
    N4 = receipt("Software Abo Beispiel 2", "119.00", DAY[8], "Lizenzen")
    imp(A, [(-119.00, DAY[8], "Software Beispiel GmbH", None, "Abo November")])
    A.post(B + f"{K}/tx/{tx(A, 'Abo November')['id']}/match", json={"kind": "receipt", "id": N4})
    check(dbx("SELECT category FROM rc_receipts WHERE node_id=?", (N4,))[0][0] == "Lizenzen", "a receipt with its own category keeps it")

# ======================================================================== two at the same moment
imp(A, [(-1.00 - n, DAY[9], "Parallel Beispiel", None, f"Par {n}") for n in range(6)])
RP = rule(A, counterpart="Parallel Beispiel", action="private")["rule"]["id"]
out = []
th = [threading.Thread(target=lambda: out.append(A.post(B + f"{R}/{RP}/apply").json())) for _ in range(2)]
for x in th:
    x.start()
for x in th:
    x.join()
hits = [x["hits"] for x in A.get(B + R).json()["items"] if x["id"] == RP][0]
check(sorted(x.get("applied") for x in out) == [0, 6] and hits == 6, f"two applies at once: every booking once, hits 6 {out} {hits}")
res = []
th = [threading.Thread(target=lambda n=n: res.append(A.post(B + K + "/import", json={"text": camt([(-2.00 - n, DAY[9], "Parallel Beispiel", None, f"Par imp {n}")]),
                                                                                       "filename": f"p{n}.xml"}).json())) for n in range(2)]
for x in th:
    x.start()
for x in th:
    x.join()
hits = [x["hits"] for x in A.get(B + R).json()["items"] if x["id"] == RP][0]
check([x.get("ruled") for x in res] == [1, 1] and hits == 8 and all(tx(A, f"Par imp {n}")["match"]["kind"] == "private" for n in range(2)),
      f"two imports at once: each marked by rule once {res} {hits}")

# ======================================================================== rights and areas
RA = rule(A, counterpart="Rechte Beispiel", action="private")["rule"]["id"]
rows = (("GET", R, None), ("POST", R, {"counterpart": "x", "action": "private"}), ("PUT", f"{R}/{RA}", {"active": False}),
        ("DELETE", f"{R}/{RA}", None), ("POST", f"{R}/{RA}/restore", None), ("POST", f"{R}/{RA}/apply", None),
        ("POST", f"{R}/{RA}/revert", None), ("POST", f"{R}/decline", {"counterpart": "x"}))
check(all(Bo.request(m, B + u, json=b).status_code == 403 for m, u, b in rows), "rights: a member of the organisation gets 403 everywhere")
check(all(Ca.request(m, B + u, json=b).status_code == 404 for m, u, b in rows if str(RA) in u), "rights: another organisation reaches no rule (404)")
check(not any(x["id"] == RA for x in Ca.get(B + R).json()["items"]) and Ca.post(B + R, json={"counterpart": "Rechte Beispiel", "action": "private"}).status_code == 201,
      "rights: another organisation sees none of these rules, makes its own")
check(all(Fr.request(m, B + u, json=b).status_code == 404 for m, u, b in rows if str(RA) in u), "rights: the freelancer reaches no rule of the organisation (404)")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "rulebot", "display_name": "Rule Bot"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(requests.request(m, B + u, headers=AG, json=b).status_code in (401, 403) for m, u, b in rows), "rights: an agent gets 403")
check(dbx("SELECT org_id FROM office_bank_rules WHERE id=?", (RA,))[0][0] == ORG, "the rule belongs to the organisation")

# ======================================================================== a locked month stays as it is (organisation, last: locks the month)
imp(A, [(-15.00, OLD, "Altbank Beispiel", None, "Alt 1")])
RO = rule(A, counterpart="Altbank Beispiel", action="private", apply_open=True)
check(RO["applied"] == 1, "the old month: marked while it is open")
imp(A, [(-16.00, OLD, "Altladen Beispiel", None, "Alt 2")])
r = A.post(B + "/api/office/periods/lock", json={"through": OLD_M, "confirm": f"{OLD_M[5:7]}/{OLD_M[:4]}"})
check(r.ok, "the old month locked " + r.text[:200])
j = rule(A, counterpart="Altladen Beispiel", action="ignored", apply_open=True)
check(j["applied"] == 0 and j["locked"] == 1 and tx(A, "Alt 2")["match"] is None, f"a locked month: nothing marked, counted {j}")
r = A.post(B + f"{R}/{RO['rule']['id']}/revert")
check(r.ok and r.json()["undone"] == 0 and r.json()["locked"] == 1 and tx(A, "Alt 1")["match"]["kind"] == "private", f"a locked month: its marks stay {r.text[:120]}")

for x in SKIPS:
    print("SKIP:", x)
sys.exit(kt.done("p2299_b_bankrules"))
