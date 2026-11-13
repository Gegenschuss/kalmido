#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1111.0 (#5953) API tests: the JSON columns of the areas as JSONB (core/coltype.py CT_JSON, ct_json_migrate).
Own container (start.sh). Invented names only.
   freelancer-matrix: contacts, reading, office
 - a new database: every CT_JSON column is jsonb; the columns kept as TEXT (sealed as a whole, office_docs.totals of the hash
   chain, budget_meta.mappings) are text; the back limit names #5953
 - routes on the JSONB columns (an organisation's admin and a person without one): a contact with e-mails and groups is
   made (the search index trigger reads its lists), found by its group and by a word of its e-mail; a bookmark found by its
   tag; the bank bookings reminder of the office settings is found by the watchdog's query (JSONB sorts "every" behind
   "user" - the old LIKE on the text missed it)
 - the migration on old values (in the container, rolled back): contacts.emails / groups and lists.folder_own turned back
   to TEXT with '' / no JSON / JSON in another form / sealed text; ct_json_migrate turns them: JSON keeps its value, ''
   and no JSON become the default (the log names column and id), the search triggers on contacts are back, sealed text
   keeps the column TEXT, a second run changes nothing
 - the account import takes a JSON column's value (JSONB was "not taken over" before): valid JSON kept, no JSON left out
usage: p21111_b_jsonb_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import CT, B, check, dbx  # noqa: E402

kt.fresh(prefix="P21111B")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done",
                                  "features": "contacts,reading,office,clients,docs,comments,collab"})


def py(code):
    """Runs code in the container (the owner's direct connection c, under system_ctx) -> (the JSON of its last line, stderr)."""
    src = ("import app, json, sys\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.db import connect_direct\n"
           "from kalmido.core.pg import system_ctx\nc = connect_direct(DATABASE_URL)\n"
           "with system_ctx(c):\n" + "".join("    " + x + "\n" for x in code.strip().splitlines()) + "c.close()\n")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", src], capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr
    except (ValueError, IndexError):
        return {"_error": out.stdout[-400:] + out.stderr[-800:]}, out.stderr


# ---- the column types of a new database
ty, _e = py("""
from kalmido.core.coltype import CT_JSON
have = {(t, col): typ for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
want = [(t, col) for t, cols in CT_JSON.items() for col, _ in cols]
kept = [('office_bookarch', 'raw'), ('office_contracts', 'rates'), ('office_doc_log', 'detail'), ('office_doc_parts', 'sheet'), ('office_meals', 'amounts'), ('office_meals', 'guests'), ('office_meals', 'host'), ('office_roles', 'costs'), ('office_trips', 'people'), ('office_docs', 'totals'), ('budget_meta', 'mappings')]
how = c.execute("SELECT value FROM kalmido_meta WHERE key='back_floor_how'").fetchone()
print(json.dumps({"n": len(want), "missing": sorted(f"{t}.{x}" for t, x in want if (t, x) not in have), "other": sorted(f"{t}.{x}={have[(t, x)]}" for t, x in want if (t, x) in have and have[(t, x)] != 'jsonb'), "kept": sorted({have.get(k) for k in kept}), "how": how[0] if how else ''}))
""")
check(ty.get("n", 0) >= 70 and ty.get("missing") == [] and ty.get("other") == [], f"a new database: every CT_JSON column is JSONB {ty}")
check(ty.get("kept") == ["text"], f"a new database: sealed / hash chain / key order columns stay TEXT {ty.get('kept')}")
check("#5953" in (ty.get("how") or ""), f"the back limit names the JSONB move {ty.get('how')}")


# ---- routes on the JSONB columns
def routes(s, who, me):
    r = s.post(B + "/api/contacts", json={"fn": f"{who} Gartenhilfe", "emails": [{"value": f"zaubernuss.{who}@example.com"}],
                                         "groups": ["Obstbau Süd"]})
    check(r.status_code in (200, 201), f"{who}: a contact with e-mails and groups (the search trigger reads them) ({r.status_code} {r.text[:200]})")
    cid = r.json().get("id") if r.ok else None
    one = s.get(B + f"/api/contacts/{cid}").json() if cid else {}
    check([x.get("value") for x in one.get("emails") or []] == [f"zaubernuss.{who}@example.com"] and one.get("groups") == ["Obstbau Süd"],
          f"{who}: the contact reads its lists back {one.get('emails')} {one.get('groups')}")
    items = s.get(B + "/api/contacts", params={"group": "Obstbau Süd"}).json().get("items", [])
    check(cid in {x["id"] for x in items}, f"{who}: the contact list by group (ILIKE on JSONB before) {[x['id'] for x in items]}")
    items = s.get(B + "/api/contacts", params={"group": "Steinobst"}).json().get("items", [])
    check(cid not in {x["id"] for x in items}, f"{who}: another group does not find it")
    items = s.get(B + "/api/contacts", params={"q": "zaubernuss"}).json().get("items", [])
    check(cid in {x["id"] for x in items}, f"{who}: found by a word of its e-mail (search index over the JSONB list)")
    r = s.patch(B + f"/api/contacts/{cid}", json={"groups": ["Steinobst"]})
    check(r.ok, f"{who}: the groups changed ({r.status_code} {r.text[:160]})")
    items = s.get(B + "/api/contacts", params={"group": "Steinobst"}).json().get("items", [])
    check(cid in {x["id"] for x in items}, f"{who}: found by the new group")

    r = s.post(B + "/api/bookmarks", json={"url": f"https://example.com/{who}/quitte", "title": "Quittenernte", "tags": ["obstbau", "herbst"]})
    check(r.status_code in (200, 201), f"{who}: a bookmark with tags ({r.status_code} {r.text[:200]})")
    bid = r.json().get("id") if r.ok else None
    items = s.get(B + "/api/bookmarks", params={"tag": "herbst"}).json().get("items", [])
    check(bid in {x["id"] for x in items}, f"{who}: the bookmarks by tag (ILIKE on JSONB before) {[x['id'] for x in items]}")
    items = s.get(B + "/api/bookmarks", params={"tag": "winter"}).json().get("items", [])
    check(bid not in {x["id"] for x in items}, f"{who}: another tag does not find it")

    r = s.put(B + "/api/office/settings", json={"bank_norc": {"every": "week", "user": me}})
    check(r.ok, f"{who}: the bank bookings reminder on ({r.status_code} {r.text[:200]})")
    got, err = py("""
rows = c.execute("SELECT org_id, CAST(data AS text) FROM office_settings WHERE CAST(data AS jsonb)->'bank_norc'->>'every' IN ('week', 'month')").fetchall()
print(json.dumps({"n": len(rows), "old_like": sum(1 for _, t in rows if '"bank_norc": {"every": "week"' in t)}))
""")
    check(got.get("n", 0) >= 1, f"{who}: the watchdog's query finds the reminder {got} {err[-300:]}")
    return cid, got


CA, GA = routes(A, "alice", ALICE)
FRIDA, F = freelancer(B, A)
CF, GF = routes(F, "frida", FRIDA)
check(GF.get("n", 0) >= 2 and GF.get("old_like", 1) == 0,
      f"regression: JSONB puts \"every\" behind \"user\" - the old LIKE on the text found none {GF}")

# ---- the migration on old values (rolled back)
LISTS = [r[0] for r in dbx("SELECT id FROM lists ORDER BY id LIMIT 2")]
mig, err = py("""
from kalmido.core.coltype import ct_json_migrate, ctj_triggers
def text(t, col):
    trg = ctj_triggers(c, t, col)
    for name, _ in trg:
        c.execute(f'DROP TRIGGER "{name}" ON {t}')
    c.execute(f"ALTER TABLE {t} ALTER COLUMN {col} DROP DEFAULT, ALTER COLUMN {col} TYPE TEXT USING CAST({col} AS text), ALTER COLUMN {col} SET DEFAULT '[]'")
    for _, ddl in trg:
        c.execute(ddl)
    return len(trg)
out = {'trg': text('contacts', 'emails') + text('contacts', 'groups'), 'lists': %(lists)s}
text('lists', 'folder_own')
out['old'] = [c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?", x).fetchone()[0] for x in (('contacts', 'emails'), ('lists', 'folder_own'))]
c.execute("UPDATE contacts SET emails='', groups='[ \\"b\\" ,\\"a\\"]' WHERE id=?", (%(ca)d,))
c.execute("UPDATE contacts SET emails='not json at all', groups='{\\"z\\":1,  \\"a\\":[1,2]}' WHERE id=?", (%(cf)d,))
c.execute("UPDATE lists SET folder_own='kenc1:c2VhbGVk' WHERE id=?", (out['lists'][0],))
out['first'] = ct_json_migrate(c, '2026-11-13T08:00:00+00:00')
ty = lambda t, x: c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?", (t, x)).fetchone()[0]
out['types'] = [ty('contacts', 'emails'), ty('contacts', 'groups'), ty('lists', 'folder_own')]
out['a'] = [json.loads(x) for x in c.execute("SELECT emails, groups FROM contacts WHERE id=?", (%(ca)d,)).fetchone()]
out['f'] = [json.loads(x) for x in c.execute("SELECT emails, groups FROM contacts WHERE id=?", (%(cf)d,)).fetchone()]
out['dflt'] = c.execute("SELECT column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='contacts' AND column_name='emails'").fetchone()[0]
out['trg_after'] = len(ctj_triggers(c, 'contacts', 'emails')) + len(ctj_triggers(c, 'contacts', 'groups'))
c.execute("UPDATE contacts SET fn='Umbenannt' WHERE id=?", (%(ca)d,))
out['sealed'] = c.execute("SELECT folder_own FROM lists WHERE id=?", (out['lists'][0],)).fetchone()[0]
out['second'] = sorted(set(v for k, v in ct_json_migrate(c, '2026-11-13T09:00:00+00:00').items() if k != 'lists.folder_own'))
c.rollback()
print(json.dumps(out))
""" % {"ca": CA, "cf": CF, "lists": json.dumps(LISTS)})
first = mig.get("first") or {}
check(mig.get("old") == ["text", "text"], f"migration: the old state is TEXT {mig}")
check(mig.get("trg", 0) >= 1, f"migration: the search index triggers name the columns (the ALTER must take them off) {mig.get('trg')}")
check(first.get("contacts.emails") == "done" and first.get("contacts.groups") == "done", f"migration: the columns turn {first}")
check(mig.get("types") == ["jsonb", "jsonb", "text"], f"migration: JSONB after the turn, sealed text keeps TEXT {mig.get('types')}")
check(first.get("lists.folder_own") == "kept" and mig.get("sealed") == "kenc1:c2VhbGVk", f"migration: sealed text is not lost {mig.get('sealed')}")
check(mig.get("a") == [[], ["b", "a"]], f"migration: '' = the default, JSON in another form keeps its value {mig.get('a')}")
check(mig.get("f") == [[], {"z": 1, "a": [1, 2]}], f"migration: no JSON = the default, an object keeps its value {mig.get('f')}")
check("'[]'::jsonb" in str(mig.get("dflt") or ""), f"migration: the default is JSONB {mig.get('dflt')}")
check(mig.get("trg_after") == mig.get("trg"), f"migration: the triggers are back {mig.get('trg_after')} / {mig.get('trg')}")
check("5953: contacts.emails: 1 value(s) are no JSON" in err and str(CF) in err, f"migration: the log names the column and the id {err[-600:]}")
check("5953: lists.folder_own stays TEXT: it holds sealed text" in err, f"migration: the log names the sealed column {err[-600:]}")
check(set(mig.get("second") or ["?"]) <= {"present", "missing"}, f"migration: a second run changes nothing {mig.get('second')}")

# ---- the account import takes a JSON column's value
imp, err = py("""
from kalmido.admin.acctimport import umz_row
d = umz_row(c, 'contacts', {'fn': 'Import', 'emails': '[{"value": "x@example.com"}]', 'groups': 'no json', 'urls': [{'value': 'https://example.com'}]}, {}, '2026-11-13T08:00:00+00:00') or {}
print(json.dumps({'emails': d.get('emails'), 'groups': d.get('groups', 'left out'), 'urls': d.get('urls')}))
""")
check(json.loads(imp.get("emails") or "null") == [{"value": "x@example.com"}], f"import: a JSON column keeps its value {imp} {err[-300:]}")
check(imp.get("groups") == "left out", f"import: no JSON is left out (the default) {imp.get('groups')}")
check(json.loads(imp.get("urls") or "null") == [{"value": "https://example.com"}], f"import: a list in the file becomes JSON text {imp.get('urls')}")

sys.exit(kt.done("p21111_b_jsonb"))
