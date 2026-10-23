#!/usr/bin/env python3
"""2.67.0 API tests, part A (#1838: fixed costs from a spreadsheet in the cash flow), own container (start.sh, org encryption
on). Invented names and figures only; the spreadsheet is built here (zipfile).
 - category + VAT rate (0 / 7 / 19) of a fixed cost; existing costs (no rate) stay the same on both bases
 - preview: 24 monthly and 32 yearly rows, group rows -> category, an empty row (skipped), a "0" row and a row without a
   name (errors), German thousands ("1.200,50", "12.500"), a quarterly row -> four yearly rows, duplicates inside the file
   and against what is there; the default VAT (insurances / contributions 0 %, else 19 %); the preview stores nothing
 - take over: the rows with a changed VAT rate, every row checked again (a bad one: 400, nothing stored), ids / org_id of
   another organisation ignored, MAX_FIXED (400, nothing stored), the undo deletes the ids of the own area only
 - cash flow ?basis=net|gross (default gross)
 - the template is a valid .xlsx the import reads
 - the monthly check task: an admin who sees the cash flow (a member / another organisation refused), a recurring task on
   the 1st (RRULE) without amounts, another person = the old one ended, off = ended (not deleted), lost access shown
 - rights: a member, an agent and another organisation get 403 / see nothing
usage: p267_a_api_test.py <datadir>"""
import base64
import io
import os
import re
import subprocess
import sys
import time
import zipfile
from xml.sax.saxutils import escape

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def xlsx(rows):
    """A minimal .xlsx: strings inline, numbers (int / float) as number cells."""
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


def up(s, raw, name="fixkosten.xlsx"):
    return s.post(B + PV, files={"file": (name, raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Second")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "admin"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
DAVE = Da.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2), (Da, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
F = O + "/fixed-costs"
PV, IM = F + "/import/preview", F + "/import"

# ---------------------------------------------------------------- category + VAT rate
r = A.post(B + F, json={"label": "Miete", "amount": "900", "start": "2026-01-01", "repeat": "monthly"})
check(r.status_code == 201 and r.json()["vat_rate"] == 0 and r.json()["category"] == "" and r.json()["gross"] == "900.00", "a fixed cost without a rate: 0 %, gross = net " + r.text[:200])
RENT = r.json()["id"]
r = A.post(B + F, json={"label": "Server", "amount": "100", "start": "2026-01-01", "repeat": "monthly", "category": "IT", "vat_rate": 19})
check(r.status_code == 201 and r.json()["vat_rate"] == 19 and r.json()["category"] == "IT" and r.json()["gross"] == "119.00", "category and 19 % " + r.text[:200])
SRV = r.json()["id"]
check(A.post(B + F, json={"label": "x", "amount": "5", "start": "2026-01-01", "vat_rate": 16}).status_code == 400, "a VAT rate other than 0 / 7 / 19 is refused")
check(A.patch(B + f"{F}/{SRV}", json={"vat_rate": 7}).json()["gross"] == "107.00", "the rate can be changed")
A.patch(B + f"{F}/{SRV}", json={"vat_rate": 19})
check(str(sql("SELECT amount FROM office_fixed_costs WHERE id=?", (SRV,))[0][0]).startswith("kenc1:"), "the amount stays encrypted at rest")

# ---------------------------------------------------------------- preview
rows = [["Kostenübersicht 2026"], [], ["Name", "Betrag (netto)", "fällig Monat"], ["Software"]]
for i in range(24):
    amt = {0: "1.200,50", 1: "12.500", 2: 12.5, 3: "29,90"}.get(i, 10 + i)
    rows.append([f"Abo {i + 1}", amt, 0])
rows.append(["Versicherungen"])
for i in range(32):
    rows.append([f"Police {i + 1}", 100 + i, 1 + i % 12])
rows += [[], ["Nullposten", "0", 0], ["", 50, 0], ["Sonstiges"], ["Beitrag Kammer quartalsweise", 100, 2], ["Abo 1", "1.200,50", 0],
         ["Miete", 900, 0], ["Lager Quartal", 50, 0]]
RAW = xlsx(rows)
before = len(A.get(B + F).json()["items"])
r = up(A, RAW)
check(r.ok, "the preview " + r.text[:300])
P = r.json()
R = P["rows"]
byl = lambda n: [x for x in R if x["label"] == n]
check(P["counts"] == {"new": 61, "dup": 2, "error": 2}, f"24 monthly + 32 yearly + 4 quarterly parts + 1 = 61 new, 2 duplicates, 2 errors {P['counts']}")
check(len(A.get(B + F).json()["items"]) == before, "the preview stores nothing")
check([x["amount"] for x in byl("Abo 1")] == ["1200.50", "1200.50"] and byl("Abo 2")[0]["amount"] == "12500.00" and byl("Abo 3")[0]["amount"] == "12.50"
      and byl("Abo 4")[0]["amount"] == "29.90", f"German thousands and decimal comma {[byl('Abo %d' % k)[0]['amount'] for k in (1, 2, 3, 4)]}")
a1 = byl("Abo 1")
check(a1[0]["status"] == "new" and a1[0]["sel"] and a1[1]["status"] == "dup" and not a1[1]["sel"], f"a duplicate inside the file is marked and not ticked {a1}")
m = byl("Miete")
check(len(m) == 1 and m[0]["status"] == "dup" and not m[0]["sel"], f"a duplicate of an existing cost {m}")
a5 = byl("Abo 5")[0]
check(a5["repeat"] == "monthly" and a5["start"] == "2026-01-01" and a5["category"] == "Software" and a5["vat_rate"] == 19 and a5["gross"] == "16.66",
      f"month 0 = monthly from January 2026, the group row is the category, 19 % {a5}")
p3 = byl("Police 3")[0]
check(p3["repeat"] == "yearly" and p3["start"] == "2026-03-01" and p3["category"] == "Versicherungen" and p3["vat_rate"] == 0, f"month 3 = yearly in March, insurances 0 % {p3}")
q = byl("Beitrag Kammer quartalsweise")
check([(x["repeat"], x["start"], x["part"]) for x in q] == [("yearly", f"2026-{mo:02d}-01", f"{k + 1}/4") for k, mo in enumerate((2, 5, 8, 11))]
      and all(x["vat_rate"] == 0 and x["category"] == "Sonstiges" for x in q), f"a quarterly cost = four yearly rows, a contribution 0 % {q}")
lq = byl("Lager Quartal")
check(len(lq) == 1 and lq[0]["repeat"] == "monthly", f"name says quarterly, the month 0 wins {lq}")
er = [x for x in R if x["status"] == "error"]
check(len(er) == 2 and {x["reason"] for x in er} == {"Amount is 0", "No name"} and not any(x["sel"] for x in er), f"the 0 row and the row without a name are errors {er}")
check(not any(x["label"] in ("Software", "Versicherungen", "Sonstiges", "Kostenübersicht 2026") for x in R), "group rows and the title above the header are no rows")
# bad files
check(up(A, b"not a zip").status_code == 400, "not a spreadsheet: 400")
check(up(A, xlsx([["Foo", "Bar"], ["x", 1]])).status_code == 400, "no header with name and amount: 400")
check(up(A, xlsx([["Name", "Betrag"]] + [[f"r{i}", 1, 0] for i in range(501)])).status_code == 400, "more than 500 rows: 400")
check(up(A, b"PK" + b"\0" * (2 * 1024 * 1024 + 10)).status_code == 400, "a file over 2 MB: 400")
# 2.67.0 (#1838, review): a VAT cell "inf" / "nan" / "1e400" is a row error, not a 500
r = up(A, xlsx([["Name", "Betrag (netto)", "fällig Monat", "USt"], ["Inf-Abo", 5, 0, "inf"], ["Nan-Abo", 5, 0, "nan"], ["Big-Abo", 5, 0, "1e400"]]))
check(r.status_code == 200 and [x["status"] for x in r.json()["rows"]] == ["error"] * 3, "VAT inf / nan / 1e400: row errors " + r.text[:300])
f = up(A, xlsx([["Name", "Betrag", "Monat"], ['=HYPERLINK("http://example.com","x")', 10, 0], ["<script>alert(1)</script>", 10, 0]])).json()
check([x["label"] for x in f["rows"]] == ['=HYPERLINK("http://example.com","x")', "<script>alert(1)</script>"], "formula / script text stays plain text (the client escapes it)")

# ---------------------------------------------------------------- take over
items = [{k: x[k] for k in ("label", "amount", "repeat", "start", "category", "vat_rate")} for x in R if x["sel"]]
items[4]["vat_rate"] = 7  # Abo 5
items[0].update(org_id=ORG2, id=RENT, created_by=CAROL)
n0 = len(A.get(B + F).json()["items"])
check(A.post(B + IM, json={"items": items[:3] + [{**items[3], "vat_rate": 5}]}).status_code == 400 and len(A.get(B + F).json()["items"]) == n0, "one bad row: 400, nothing stored")
check(A.post(B + IM, json={"items": [{**items[3], "repeat": "weekly"}]}).status_code == 400, "an unknown repeat is refused")
check(A.post(B + IM, json={"items": [{**items[3], "amount": "-3"}]}).status_code == 400, "a negative amount is refused")
r = A.post(B + IM, json={"items": items})
check(r.status_code == 201 and r.json()["created"] == 61 and len(r.json()["ids"]) == 61, "61 rows taken over " + r.text[:200])
IDS = r.json()["ids"]
FX = {x["id"]: x for x in A.get(B + F).json()["items"]}
check(len(FX) == n0 + 61, "all in the list")
a5 = [x for x in FX.values() if x["label"] == "Abo 5"][0]
check(a5["vat_rate"] == 7 and a5["gross"] == "14.98" and a5["category"] == "Software", f"the changed VAT rate is stored {a5}")
check(FX[RENT]["label"] == "Miete" and FX[RENT]["amount"] == "900.00", "a foreign id in the row does not touch the existing cost")
check(Ca.get(B + F).json()["items"] == [] and sql("SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=?", (ORG2,))[0][0] == 0, "org_id of another organisation ignored")
check(all(str(v[0]).startswith("kenc1:") for v in sql("SELECT amount FROM office_fixed_costs WHERE org_id=?", (ORG,))), "imported amounts encrypted at rest")
check(sql("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='import' AND target='fixed_costs'", (ORG,))[0][0] == 1, "the office log has the import")
# MAX_FIXED
have = len(FX)
many = [{"label": f"Viel {i}", "amount": 1, "repeat": "monthly", "start": "2026-01-01"} for i in range(500 - have + 1)]
r = A.post(B + IM, json={"items": many})
check(r.status_code == 400 and "500" in r.text and len(A.get(B + F).json()["items"]) == have, "more than 500 fixed costs: 400, nothing stored " + r.text[:200])
# undo: only the own area's ids
check(Ca.post(B + F + "/delete", json={"ids": IDS[:5]}).json().get("deleted") == 0, "another organisation cannot delete them")
check(A.post(B + F + "/delete", json={"ids": ["x"]}).status_code == 400, "bad ids: 400")

# ---------------------------------------------------------------- cash flow net / gross
g = A.get(B + O + "/cashflow?from=2026-01&months=1").json()
nt = A.get(B + O + "/cashflow?from=2026-01&months=1&basis=net").json()
check(g["basis"] == "gross" and nt["basis"] == "net", "gross is the default")
check(A.get(B + O + "/cashflow?basis=foo").status_code == 400, "an unknown basis: 400")
ge = {e["fixed_id"]: e["amount"] for e in g["entries"] if e["kind"] == "fixed"}
ne = {e["fixed_id"]: e["amount"] for e in nt["entries"] if e["kind"] == "fixed"}
check(ge[RENT] == ne[RENT] == "900.00", "a cost without a rate is the same on both bases")
check(ge[SRV] == "119.00" and ne[SRV] == "100.00", f"19 %: gross and net {ge.get(SRV)} {ne.get(SRV)}")
check(ne[a5["id"]] == "14.00" and ge[a5["id"]] == "14.98", f"7 %: net 14.00 -> gross 14.98 {ne.get(a5['id'])} {ge.get(a5['id'])}")
sg = sum(float(v) for v in ge.values())
check(abs(float(g["rows"][0]["out"]["actual"]) + float(g["rows"][0]["out"]["plan"]) - sg) < 0.01, "the month's out = the sum of its gross entries")
# 2.67.0 (#1838): purchases / travel receipts / documents are not touched here (p2473_b_api checks the gross sums of documents)

# ---------------------------------------------------------------- the template
r = A.get(B + PV.replace("/preview", "/template"))
check(r.ok and "spreadsheetml" in r.headers.get("Content-Type", "") and r.content[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(r.content)), "the template is an .xlsx")
t = up(A, r.content, "template.xlsx").json()
tr_ = t.get("rows") or []
check(len(tr_) == 2 and tr_[0]["repeat"] == "monthly" and tr_[0]["amount"] == "29.90" and tr_[0]["vat_rate"] == 19
      and tr_[1]["repeat"] == "yearly" and tr_[1]["start"] == "2026-03-01" and tr_[1]["category"] == "Insurances" and tr_[1]["vat_rate"] == 0,
      f"the import reads its own template {tr_}")

# ---------------------------------------------------------------- the monthly check task
CK = O + "/cashflow/check"
c0 = A.get(B + CK).json()
check(c0["on"] is False and {p["id"] for p in c0["people"]} == {ALICE, DAVE}, f"off by default; the admins who see the cash flow {c0}")
check(A.put(B + CK, json={"on": 1, "user_id": BOB}).status_code == 400, "a member (no cash flow) is refused")
check(A.put(B + CK, json={"on": 1, "user_id": CAROL}).status_code == 400, "a person of another organisation is refused")
r = A.put(B + CK, json={"on": 1, "user_id": ALICE})
check(r.ok and r.json()["on"] and r.json()["task_id"], "on for Alice " + r.text[:200])
T1 = r.json()["task_id"]


def task(tid):
    return sql("SELECT t.title, t.content, t.due, t.repeat, t.status, t.assignee_id, t.deleted_at, t.url, l.owner_id, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,))[0]


t1 = task(T1)
check(t1[3] == "FREQ=MONTHLY;BYMONTHDAY=1" and t1[2].endswith("-01") and t1[4] == 0 and t1[5] == ALICE and t1[8] == ALICE and t1[9] == 1,
      f"a recurring task on the 1st in Alice's inbox, assigned to her {t1}")
check(not re.search(r"\d", t1[0] + t1[1]) and "€" not in t1[0] + t1[1] and t1[7].endswith("/#office/cashflow"), f"no amounts, only the link to the cash flow {t1[:2]} {t1[7]}")
check(A.put(B + CK, json={"on": 1, "user_id": ALICE}).json()["task_id"] == T1, "saving again keeps the task")
r = A.put(B + CK, json={"on": 1, "user_id": DAVE})
T2 = r.json()["task_id"]
check(r.ok and T2 != T1 and task(T1)[4] == 2 and task(T1)[3] == "" and task(T1)[6] is None, "another person: the old task is ended (done, no repeat), not deleted")
check(task(T2)[8] == DAVE and task(T2)[5] == DAVE, "the new one in Dave's inbox")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "member"}).ok
c1 = A.get(B + CK).json()
check(c1["lost"] is True and c1["user_id"] == DAVE and task(T2)[4] == 0, f"Dave lost the cash flow: shown, not reassigned {c1}")
r = A.put(B + CK, json={"on": 0})
check(r.ok and not r.json()["on"] and task(T2)[4] == 2 and task(T2)[6] is None, "off: the task is ended, not deleted")
check(Ca.get(B + CK).json()["on"] is False, "another organisation has its own (off)")

# ---------------------------------------------------------------- 2.122.2 (#2323)
# a sheet as people keep it (invented rows): A1 is a title, not "Name"; a row with only "0" in the month column; the VAT
# default 0 % for bank / credit costs, taxes (not the tax adviser), service charge, memberships, KSK, Knappschaft, BG.
# Also as a person without an organisation (freelancer-matrix: office).
from freelancer_fixture import freelancer  # noqa: E402
_FID, Fr = freelancer(B, A, "fenja")
G = [["Grundkosten 2025", "Betrag", "fällig Monat"], ["Bank"], ["Sparkasse Kontoführung", 12, 0], ["Girokarte", 15, 1],
     ["Kredit Auto Tilgung", 250, 0], ["", "", 0], ["Steuern"], ["Grundsteuer", 80, 2], ["KFZ-Steuer", 120, 5], ["Steuerberater", 150, 0],
     ["Hausgeld", 300, 0], ["ADAC Mitgliedschaft", 59, 3], ["KSK", 40, 0], ["Knappschaft", 90, 0], ["BG ETEM", 70, 4], ["Software"], ["Datenbank Hosting", 9, 0]]
for who, s_ in (("an org admin", A), ("a freelancer", Fr)):
    r = up(s_, xlsx(G))
    check(r.ok, f"{who}: A1 = a title, the first text column is the name {r.status_code} {r.text[:200]}")
    if not r.ok:
        continue
    g = r.json()
    vat = {x["label"]: x["vat_rate"] for x in g["rows"]}
    check(g["counts"]["error"] == 0, f"{who}: a row with only 0 is skipped, no error {g['counts']}")
    check(all(vat.get(n) == 0 for n in ("Sparkasse Kontoführung", "Girokarte", "Kredit Auto Tilgung", "Grundsteuer", "KFZ-Steuer", "Hausgeld",
                                        "ADAC Mitgliedschaft", "KSK", "Knappschaft", "BG ETEM")), f"{who}: bank, taxes, memberships 0 % {vat}")
    check(vat.get("Steuerberater") == 19 and vat.get("Datenbank Hosting") == 19, f"{who}: the tax adviser (also below the group Steuern) and a database 19 % {vat}")
    check(next(x for x in g["rows"] if x["label"] == "Girokarte")["category"] == "Bank", f"{who}: group rows still the category")

# ---------------------------------------------------------------- rights
for what, rr in (("preview", up(Bo, RAW)), ("take over", Bo.post(B + IM, json={"items": items[:1]})), ("template", Bo.get(B + F + "/import/template")),
                 ("delete", Bo.post(B + F + "/delete", json={"ids": IDS[:1]})), ("check", Bo.get(B + CK)), ("check put", Bo.put(B + CK, json={"on": 1, "user_id": BOB}))):
    check(rr.status_code == 403, f"a member: 403 on {what} ({rr.status_code})")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "helper", "display_name": "Helper"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
for what, rr in (("preview", requests.post(B + PV, headers=AG, files={"file": ("a.xlsx", RAW)})), ("take over", requests.post(B + IM, headers=AG, json={"items": items[:1]})),
                 ("check", requests.get(B + CK, headers=AG)), ("list", requests.get(B + F, headers=AG))):
    check(rr.status_code == 403, f"an agent: 403 on {what} ({rr.status_code})")
r = A.post(B + F + "/delete", json={"ids": IDS})
check(r.ok and r.json()["deleted"] == 61 and len(A.get(B + F).json()["items"]) == n0, "the undo deletes the imported rows (one step)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
