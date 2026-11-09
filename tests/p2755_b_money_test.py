#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.755.0 (#5293) API tests: the plain money columns of the office as NUMERIC(14,2) (core/moneycol.py). Own container (start.sh,
org encryption on). Invented companies, people and figures only.
 - the columns office_doc_items.net / tax_amount, office_cash_entries.amount, office_ledger_entries.amount are numeric(14,2);
   the encrypted ones stay text (office_cf_adjust.amount, office_bank_tx.amount)
 - the answers keep their form: the positions of a finalised invoice carry net / tax_amount as "1000.00" text, a cash entry
   "23.80", a balance-sheet entry "500.00"; the hash chain of the finalised documents is intact
 - the migration on old values (in the container, rolled back): '12.5', '0', '' and a value with three places; the value with
   three places keeps the column TEXT and the log names it (no abort); corrected, the column turns and every value is the
   same number ('' = 0 in the NOT NULL cash column, NULL in the nullable position columns); the chained positions turn and
   the chain stays intact; a chained position stored as '-0.00' keeps its column TEXT (its checksum would change)
 - a person without an organisation (freelancer-matrix: office): the same answers in the personal office
 - review N4: the organisation import of an older export with '' in the four columns: NULL / 0 as the migration
 - review H1: the real start as the database's owner without superuser / BYPASSRLS (row-level security holds): a chained position
   of an organisation with '-0.00' keeps its column TEXT, the log names the id, /log/chain stays intact
usage: p2755_b_money_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import CT, FAILS, OKS, B, H, DATA, check, sess, until  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
OFC = "/api/office"
FEAT = "cal,comments,collab,office,clients,docs"
TODAY = testclock.today()
Y = TODAY.year
T0 = TODAY.isoformat()
COLS = (("office_doc_items", "net"), ("office_doc_items", "tax_amount"), ("office_cash_entries", "amount"), ("office_ledger_entries", "amount"))

if not os.environ.get("P2755B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)


def _up():
    try:
        return s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"})
    except requests.ConnectionError:
        return None


r = until(_up, 30)  # the server is up once setup answers (a real state, not a fixed time)
assert r is not None and r.ok, r and r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def py(code):
    """Runs code in the container (the owner's direct connection c, as init_db has it, under system_ctx) -> the JSON it prints on
    its last line."""
    src = ("import app, json, sys\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.db import connect_direct\n"
           "from kalmido.core.pg import system_ctx\nc = connect_direct(DATABASE_URL)\n"
           "with system_ctx(c):\n" + "".join("    " + x + "\n" for x in code.strip().splitlines()) + "c.close()\n")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", src], capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr
    except (ValueError, IndexError):
        return {"_error": out.stdout[-400:] + out.stderr[-800:]}, out.stderr


def office(s, who):
    """The answers in the office s works in (an organisation or the personal office) -> (invoice id, cash entry id, draft id)."""
    check(s.put(B + OFC + "/settings", json={"lang": "de", "currency": "EUR",
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}}).ok,
          f"{who}: office settings")
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde GmbH", "street": "Kundenweg 2", "zip": "54321", "city": "Kundenstadt", "country": "DE"}).json()["id"]
    r = s.post(B + OFC + "/docs", json={"kind": "invoice", "client_id": cl, "project_title": "Job", "service_from": T0,
                                       "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}, {"title": "Farbe", "qty": 1.5, "rate": 33.33}]})
    check(r.status_code == 201, f"{who}: an invoice {r.text[:200]}")
    did = r.json()["id"]
    check(s.post(B + OFC + f"/docs/{did}/finalize").ok, f"{who}: finalised")
    d = s.get(B + OFC + f"/docs/{did}").json()
    its = [(x.get("net"), x.get("tax_amount")) for x in d.get("items", [])]
    check(its == [("1000.00", "190.00"), ("50.00", "9.50")], f"{who}: the positions carry net / tax as text with two places {its}")
    r = s.post(B + OFC + "/docs", json={"kind": "invoice", "client_id": cl, "project_title": "Entwurf", "items": [{"title": "Alt", "qty": 1, "rate": 10}]})
    draft = r.json()["id"] if r.status_code == 201 else None
    check(draft and [x.get("net") for x in s.get(B + OFC + f"/docs/{draft}").json().get("items", [])] == [None], f"{who}: a draft: no net yet {r.text[:200]}")
    ch = s.get(B + OFC + "/log/chain").json()
    check(ch.get("ok") is True and ch.get("count", 0) >= 1, f"{who}: the hash chain is intact {ch}")
    r = s.post(B + OFC + "/cashbooks", json={"name": "Handkasse", "opening": "0.00", "opening_day": f"{Y}-01-01"})
    check(r.status_code == 201, f"{who}: a cash box {r.text[:200]}")
    E = OFC + f"/cashbooks/{r.json()['id']}/entries"
    check(s.post(B + E, json={"day": f"{Y}-01-01", "dir": "in", "amount": "200", "text": "Einlage"}).status_code == 201, f"{who}: cash in")
    r = s.post(B + E, json={"day": f"{Y}-01-01", "dir": "out", "amount": "23.8", "vat_pct": "19", "text": "Porto"})
    check(r.status_code == 201 and r.json().get("amount") == "23.80", f"{who}: a cash entry answers 23.80 {r.text[:200]}")
    eid = r.json()["id"]
    lst = s.get(B + E).json()
    am = sorted(x["amount"] for x in lst.get("entries", lst.get("items", [])))
    check(am == ["200.00", "23.80"], f"{who}: the list carries the amounts as text {am} {str(lst)[:300]}")
    lg = s.get(B + OFC + f"/cash-entries/{eid}/log").json()
    check(lg.get("log") is not None, f"{who}: the change log of the entry reads {str(lg)[:200]}")
    # the balance sheet: an entry by hand
    check(s.put(B + "/api/office/books/ledger/settings", json={"method": "balance", "size": "small"}).ok, f"{who}: balance sheet chosen")
    r = s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": "4950", "credit": "0970", "amount": "500", "text": "Rückstellung"})
    if r.status_code == 400:  # SKR04 in the personal office
        r = s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": "6825", "credit": "3070", "amount": "500", "text": "Rückstellung"})
    check(r.status_code == 201 and r.json()["amount"] == "500.00", f"{who}: a ledger entry answers 500.00 {r.text[:200]}")
    led = r.json()
    r = s.put(B + f"/api/office/books/ledger/entries/{led['id']}", json={"amount": "8", "expect_updated_at": led["updated_at"]})
    check(r.ok and r.json()["amount"] == "8.00", f"{who}: read back from the database: 8.00 {r.text[:200]}")
    rep = s.get(B + f"/api/office/books/ledger?year={Y}&journal=1").json()
    check(any(x.get("amount") == "8.00" for x in rep.get("journal", [])), f"{who}: the journal shows 8.00")
    return did, eid, draft


# ---- the column types
ty, _e = py("rows = c.execute(\"SELECT table_name, column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name IN ('office_doc_items', 'office_cash_entries', 'office_ledger_entries', "
            "'office_cf_adjust', 'office_bank_tx') AND column_name IN ('net', 'tax_amount', 'amount')\").fetchall()\n"
            "print(json.dumps({f'{r[0]}.{r[1]}': [r[2], r[3], r[4]] for r in rows}))")
for t, col in COLS:
    check(ty.get(f"{t}.{col}") == ["numeric", 14, 2], f"{t}.{col} is numeric(14,2) {ty.get(f'{t}.{col}')} {ty.get('_error', '')}")
check(ty.get("office_cf_adjust.amount", [""])[0] == "text" and ty.get("office_bank_tx.amount", [""])[0] == "text", f"the encrypted ones stay text {ty}")
check(ty.get("office_cash_entries.amount") and A.get(B + "/api/health").ok, "the server started with the turned columns")

DID, EID, DRAFT = office(A, "org")

# ---- the migration on old values (rolled back at the end: the suite's data stay as they are)
mig, err = py(f"""
from kalmido.core.moneycol import mc_migrate, mc_type
from kalmido.office.chain import hch_check
out = {{}}
c.execute("ALTER TABLE office_cash_entries ALTER COLUMN amount TYPE TEXT USING amount::text, ALTER COLUMN amount SET DEFAULT '0.00'")
c.execute("ALTER TABLE office_doc_items ALTER COLUMN net TYPE TEXT USING net::text, ALTER COLUMN tax_amount TYPE TEXT USING tax_amount::text")
out['old_text'] = [mc_type(c, 'office_cash_entries', 'amount'), mc_type(c, 'office_doc_items', 'net')]
out['chain_text'] = hch_check(c, {ORG})['ok']
b = c.execute("SELECT book_id, org_id FROM office_cash_entries WHERE id=?", ({EID},)).fetchone()
ids = []
for i, v in enumerate(['12.5', '0', '', '1234.567']):
    ids.append(c.execute("INSERT INTO office_cash_entries(org_id, book_id, no, day, dir, amount, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                         (b['org_id'], b['book_id'], 900 + i, '{Y}-01-02', 'in', v, 'x', 'x')).fetchone()[0])
d = c.execute("SELECT id FROM office_doc_items WHERE doc_id=? ORDER BY sort, id", ({DID},)).fetchall()
draft = {DRAFT}
c.execute("UPDATE office_doc_items SET net='', tax_amount='7.5' WHERE doc_id=?", (draft,))
out['first'] = mc_migrate(c, 'x')
out['kept_type'] = mc_type(c, 'office_cash_entries', 'amount')
c.execute("UPDATE office_cash_entries SET amount='1234.50' WHERE id=?", (ids[3],))
out['second'] = mc_migrate(c, 'x')
out['values'] = [str(c.execute("SELECT amount::text FROM office_cash_entries WHERE id=?", (i,)).fetchone()[0]) for i in ids]
out['orig'] = c.execute("SELECT amount::text FROM office_cash_entries WHERE id=?", ({EID},)).fetchone()[0]
out['draft'] = [list(x) for x in c.execute("SELECT net::text, tax_amount::text FROM office_doc_items WHERE doc_id=?", (draft,)).fetchall()]
out['dflt'] = c.execute("SELECT column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_cash_entries' AND column_name='amount'").fetchone()[0]
out['chain_num'] = hch_check(c, {ORG})['ok']
out['third'] = mc_migrate(c, 'x')
c.execute("ALTER TABLE office_doc_items ALTER COLUMN tax_amount TYPE TEXT USING tax_amount::text")
c.execute("UPDATE office_doc_items SET tax_amount='-0.00' WHERE id=?", (d[1]['id'],))
out['chained_negzero'] = mc_migrate(c, 'x')['office_doc_items.tax_amount']
c.rollback()
print(json.dumps(out))
""")
check(mig.get("old_text") == ["text", "text"] and mig.get("chain_text") is True, f"migration: the old state (text, chain intact) {mig}")
check((mig.get("first") or {}).get("office_cash_entries.amount") == "kept" and mig.get("kept_type") == "text",
      f"migration: a value with three places keeps the column TEXT {mig.get('first')}")
check("5293: office_cash_entries.amount stays TEXT, 1 value(s)" in err, f"migration: the log names the column and the value {err[-600:]}")
check((mig.get("first") or {}).get("office_doc_items.net") == "done" and (mig.get("first") or {}).get("office_doc_items.tax_amount") == "done",
      f"migration: the positions turn on their own {mig.get('first')}")
check((mig.get("second") or {}).get("office_cash_entries.amount") == "done", f"migration: corrected, the column turns {mig.get('second')}")
check(mig.get("values") == ["12.50", "0.00", "0.00", "1234.50"] and mig.get("orig") == "23.80", f"migration: the same numbers ('' = 0) {mig.get('values')} {mig.get('orig')}")
check(mig.get("draft") == [[None, "7.50"]], f"migration: '' in a nullable position column = NULL {mig.get('draft')}")
check(str(mig.get("dflt") or "").startswith("0"), f"migration: the default is 0 {mig.get('dflt')}")
check(mig.get("chain_num") is True, "migration: the hash chain is intact after the turn")
check(set((mig.get("third") or {}).values()) == {"present"}, f"migration: a second start changes nothing {mig.get('third')}")
check(mig.get("chained_negzero") == "kept", f"migration: a chained position '-0.00' keeps its column (its checksum) {mig.get('chained_negzero')}")
ty2, _e = py("print(json.dumps(c.execute(\"SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() "
             "AND table_name='office_cash_entries' AND column_name='amount'\").fetchone()[0]))")
check(ty2 == "numeric", f"migration: rolled back, the suite's database is as before {ty2}")

# ---- review N4: the organisation import (admin/oi_office.py specs -> acctimport.umz_row / umz_insert) of an older export
# with '' / '23.8' / '-0.00' in the four columns: '' as in the migration (NULL in the nullable position columns, the default 0 in
# the NOT NULL ones), the others the same number (rolled back)
imp, _e = py(f"""
from kalmido.admin.acctimport import umz_insert, umz_row
b = c.execute("SELECT book_id, org_id FROM office_cash_entries WHERE id=?", ({EID},)).fetchone()
out = {{}}
d = umz_row(c, 'office_doc_items', {{'net': '', 'tax_amount': '23.8', 'title': 'Alt', 'qty': '1', 'rate': '0'}}, {{'doc_id': {DRAFT}, 'org_id': {ORG}}}, 'x')
out['item'] = umz_insert(c, 'office_doc_items', d)
d = umz_row(c, 'office_cash_entries', {{'amount': '', 'no': 801, 'day': '{Y}-01-03', 'dir': 'in', 'text': 'Alt'}}, {{'book_id': b['book_id'], 'org_id': b['org_id']}}, 'x')
out['cash0'] = umz_insert(c, 'office_cash_entries', d)
d = umz_row(c, 'office_cash_entries', {{'amount': '-0.00', 'no': 802, 'day': '{Y}-01-03', 'dir': 'in', 'text': 'Alt'}}, {{'book_id': b['book_id'], 'org_id': b['org_id']}}, 'x')
out['cash1'] = umz_insert(c, 'office_cash_entries', d)
d = umz_row(c, 'office_ledger_entries', {{'amount': '', 'year': {Y}, 'day': '{Y}-12-31', 'debit': '4950', 'credit': '0970'}}, {{'org_id': {ORG}}}, 'x')
out['led'] = umz_insert(c, 'office_ledger_entries', d)
out['vals'] = [c.execute("SELECT net::text, tax_amount::text FROM office_doc_items WHERE id=?", (out['item'],)).fetchone() if out['item'] else None,
               [c.execute("SELECT amount::text FROM office_cash_entries WHERE id=?", (i,)).fetchone()[0] if i else None for i in (out['cash0'], out['cash1'])],
               c.execute("SELECT amount::text FROM office_ledger_entries WHERE id=?", (out['led'],)).fetchone()[0] if out['led'] else None]
out['vals'][0] = list(out['vals'][0]) if out['vals'][0] else None
c.rollback()
print(json.dumps(out))
""")
check(imp.get("vals") == [[None, "23.80"], ["0.00", "0.00"], "0.00"],
      f"import of an older export: '' -> NULL / 0, '23.8' -> 23.80, '-0.00' -> 0.00 in the NUMERIC columns {imp}")

# 2.765.0 (#5315): an amount NUMERIC(14,2) would have to round (1234.567) is not rounded silently: umz_row leaves the row out,
# umz_money_misfit names column and value for the import's report (orgimport.oi_write warns with it); 1234.560 / 23.8 still fit;
# review M1 / N1: no plain number ('x', '1e3', 'NaN') is named too instead of becoming the default 0 silently (the migration's rule)
mis, _e = py(f"""
from kalmido.admin.acctimport import umz_money_misfit, umz_row
b = c.execute("SELECT book_id, org_id FROM office_cash_entries WHERE id=?", ({EID},)).fetchone()
fx = {{'book_id': b['book_id'], 'org_id': b['org_id']}}
row = lambda a: {{'amount': a, 'no': 803, 'day': '{Y}-01-04', 'dir': 'in', 'text': 'Alt'}}
out = {{'mis': [umz_money_misfit(c, 'office_cash_entries', row(a)) for a in ('1234.567', 12.345, '1234.560', '23.8', '', 'x', '1e3', 'NaN', ' 12.30 ')],
        'item': umz_money_misfit(c, 'office_doc_items', {{'net': '10.00', 'tax_amount': '1.905', 'title': 'Alt'}}),
        'rows': [umz_row(c, 'office_cash_entries', row(a), fx, 'x') is None for a in ('1234.567', '1234.560')]}}
out['mis'] = [list(m) if m else None for m in out['mis']]
out['item'] = list(out['item']) if out['item'] else None
c.rollback()
print(json.dumps(out))
""")
check(mis.get("mis") == [["amount", "1234.567"], ["amount", "12.345"], None, None, None, ["amount", "x"], ["amount", "1e3"], ["amount", "NaN"], None] and mis.get("item") == ["tax_amount", "1.905"]
      and mis.get("rows") == [True, False], f"#5315: the import names an amount with a third decimal place and does not round it {mis}")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer")

# ---------------------------------------------------------------- review H1: the real start under a login without superuser / BYPASSRLS
# 2.755.0 (#5293, review H1): the standard run logs in as the image's superuser, there row-level security never holds. Here the
# app logs in as the database's owner without superuser / BYPASSRLS (start.sh KALMIDO_TEST_DB_LOGIN=owner, as tests/rls_owner_test.py):
# the policies hold for it through FORCE, init_db's connection has no organisation. A chained position of an organisation stores
# '-0.00' (an old value, the chain hashed it so), the column is TEXT again; a real restart (KEEP=1) runs mc_migrate in init_db.
# Should the check see no row of the organisation, the ALTER turns '-0.00' into 0.00: column numeric, chain red. (A direct
# connection starts as "system" already, core/pg.py Conn #3139: this guards the real start, the reviewed fault did not occur.)
def start_owner(keep):
    e = dict(os.environ, KALMIDO_TEST_DB_LOGIN="owner", EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    e.pop("KEEP", None)
    if keep:
        e["KEEP"] = "1"
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


start_owner(False)
r = until(_up, 30)
assert r is not None and r.ok, r and r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
DID, _eid, _draft = office(A, "owner")
h1, _e = py(f"""
from kalmido.core.moneycol import mc_type
from kalmido.office.chain import hch_canon, hch_check, hch_hash
out = {{'login': list(c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())}}
c.execute("ALTER TABLE office_doc_items ALTER COLUMN tax_amount TYPE TEXT USING tax_amount::text")
it = c.execute("SELECT id FROM office_doc_items WHERE doc_id=? ORDER BY sort, id", ({DID},)).fetchall()[1]['id']
c.execute("UPDATE office_doc_items SET tax_amount='-0.00' WHERE id=?", (it,))
d = c.execute("SELECT * FROM office_docs WHERE id=?", ({DID},)).fetchone()
c.execute("SELECT set_config('kalmido.locked_ok', 'on', true)")  # the finalised row's chain_hash (core/migrations.d/4598.py)
c.execute("UPDATE office_docs SET chain_hash=? WHERE id=?", (hch_hash(d['chain_prev'] or '', hch_canon(c, {ORG}, d)), {DID}))
out['it'] = it
out['org'] = d['org_id']
out['chain'] = hch_check(c, {ORG})['ok']
out['type'] = mc_type(c, 'office_doc_items', 'tax_amount')
c.commit()
print(json.dumps(out))
""")
check(h1.get("login") == [False, False], f"H1: the app's login has no superuser / BYPASSRLS {h1}")
check(h1.get("type") == "text" and h1.get("chain") is True and h1.get("org") == ORG, f"H1: the old state: TEXT, '-0.00' hashed into the chain {h1}")
start_owner(True)  # the real start: init_db -> mc_migrate
A = sess("alice")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
lg = lg.stdout + lg.stderr
ty3, _e = py("r = c.execute(\"SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_doc_items' "
             "AND column_name='tax_amount'\").fetchone()[0]\nv = c.execute('SELECT tax_amount::text FROM office_doc_items WHERE id=?', (%d,)).fetchone()[0]\n"
             "print(json.dumps([r, v]))" % h1.get("it", 0))
check(ty3 == ["text", "-0.00"], f"H1: after the real start the column stays TEXT, the value as it was {ty3}")
check("5293: office_doc_items.tax_amount stays TEXT, 1 value(s)" in lg and f"(ids {h1.get('it')})" in lg,
      f"H1: the start's log names the column and the id {lg[-800:]}")
ch = A.get(B + OFC + "/log/chain").json()
check(ch.get("ok") is True and ch.get("count", 0) >= 1, f"H1: /log/chain intact after the real start {ch}")

print(f"p2755_b_money: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
