#!/usr/bin/env python3
"""2.153.0 API tests (#2179): custom fields of documents ("Eigene Felder"), POST/PATCH/DELETE /api/docs/fields, values via
PATCH /api/docs/<id> {custom_fields}. Invented names only, generated file contents.
 - a person without an organisation (freelancer fixture) is the admin of the own documents: fields of every type, nothing
   preset, the checks (name, type, options, duplicates), values set / cleared / validated, sealed in the database, found by
   the search; renaming, removing a select option (its values go), deleting a field (its values go)
 - the own agent of that person (API v1, a share with role edit): sees the fields, sets a value by name (marked "agent"),
   an unknown field 400, no new field
 - an organisation: only admins define fields (a member 403), the member sees them and fills them in on a document she may
   change; another organisation's admin gets 404
 - moving a document private -> organisation: the values go along, the fields are found by name and type or made there
   (2.184.0 B, #2580: by an admin of the target only), a select value by its option's name, sealed with the target's key
 - 2.153.0 (review B1): the key passes on the command line carry the values along: rotating an organisation's key,
   decrypt-all / encrypt-all, docs-to-server-key / docs-to-account-key; editing a select field's options keeps a value
   that cannot be opened
tenant-matrix: document
freelancer-matrix: files
usage: p2108_a_api_test.py <datadir>      (a fresh container; P2108A_NOSTART=1: the container runs already)"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def doc(s, ws, name, text):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code in (200, 201), r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return nid


def cf(s, nid):
    return {x["name"]: x for x in s.get(B + f"/api/docs/{nid}").json().get("custom_fields") or []}


def add(s, ws, name, typ, **kw):
    return s.post(B + "/api/docs/fields", json={"ws": ws, "name": name, "type": typ, **kw})


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol, Beta = dave, frida without an organisation; the server key on
if not os.environ.get("P2108A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY + " -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")  # bundle C: 2.148.1 (#2480) the invited member accepts
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, BOB, CAROL, ORG2, DAVE))
FRIDA, Fr = freelancer(B, A)
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ==== the freelancer: nothing preset, fields of every type
S0 = Fr.get(B + "/api/docs/settings?ws=private").json()
check(S0.get("fields") == [] and "levels" in S0 and "inbox" in S0, f"nothing preset: no fields; the rest of the settings unchanged ({sorted(S0)})")
D1 = doc(Fr, "private", "vertrag.txt", "Mietvertrag Beispielstrasse 1 Sonnenweg")
check(cf(Fr, D1) == {}, "a document without fields has none")
F = {}
for name, typ, kw in (("Vertragsnummer", "text", {}), ("Seiten", "number", {}), ("Kaution", "money", {}), ("Ende", "date", {}),
                      ("Unterschrieben", "checkbox", {}), ("Status", "select", {"options": "Offen, Bezahlt, Offen"}), ("Portal", "url", {})):
    r = add(Fr, "private", name, typ, **kw)
    check(r.status_code == 201, f"freelancer: field {name} ({typ}) made ({r.status_code} {r.text[:200]})")
    F[name] = r.json().get("id") if r.status_code == 201 else None
st = {x["name"]: x for x in Fr.get(B + "/api/docs/settings?ws=private").json()["fields"]}
check(list(st) == ["Vertragsnummer", "Seiten", "Kaution", "Ende", "Unterschrieben", "Status", "Portal"], f"the fields in order ({list(st)})")
check([o["name"] for o in st["Status"]["options"]] == ["Offen", "Bezahlt"], f"select options cleaned, the double one once ({st['Status']})")
check(add(Fr, "private", "vertragsnummer", "text").status_code == 409, "the same name (any case) twice: 409")
check(add(Fr, "private", "", "text").status_code == 400, "no name: 400")
check(add(Fr, "private", "X", "formula").status_code == 400, "an unknown type: 400")
check(add(Fr, "private", "Leer", "select").status_code == 400, "a select field without options: 400")
check(one("SELECT ws FROM doc_fields WHERE id=?", (F["Seiten"],)) == f"u{FRIDA}" and one("SELECT org_id FROM doc_fields WHERE id=?", (F["Seiten"],)) is None,
      "the field belongs to the freelancer's own workspace")

# values
OPT = {o["name"]: o["id"] for o in st["Status"]["options"]}
r = Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(F["Vertragsnummer"]): "MV-4711-Zebra", str(F["Seiten"]): "12,5",
                                                            str(F["Kaution"]): "1.234,50 €", str(F["Ende"]): "2027-03-31",
                                                            str(F["Unterschrieben"]): True, str(F["Status"]): "Bezahlt",
                                                            str(F["Portal"]): "https://portal.example.com/x"}})
check(r.ok, f"values set ({r.status_code} {r.text[:200]})")
v = {k: x.get("value") for k, x in cf(Fr, D1).items()}
check(v == {"Vertragsnummer": "MV-4711-Zebra", "Seiten": "12.5", "Kaution": "1234.50 EUR", "Ende": "2027-03-31", "Unterschrieben": "1",
            "Status": OPT["Bezahlt"], "Portal": "https://portal.example.com/x"}, f"canonical values ({v})")
check(cf(Fr, D1)["Status"]["label"] == "Bezahlt", "a select value's label")
raw = [x[0] for x in dbx("SELECT value FROM doc_field_values WHERE node_id=?", (D1,))]
check(len(raw) == 7 and all(x.startswith("kenc1:") for x in raw) and not any("Zebra" in x for x in raw), f"the values are sealed ({raw[:2]})")
check(dbx("SELECT DISTINCT ws FROM doc_field_values WHERE node_id=?", (D1,)) and one("SELECT ws FROM doc_field_values WHERE node_id=? LIMIT 1", (D1,)) == f"u{FRIDA}",
      "the values carry the workspace")
hits = Fr.get(B + "/api/docs?q=zebra").json()
check(D1 in [d["id"] for d in hits.get("docs") or hits.get("data") or []], f"the search finds a field value ({str(hits)[:200]})")
for bad, what in (({str(F["Seiten"]): "zwölf"}, "a number"), ({str(F["Ende"]): "31.03.2027"}, "a date"), ({str(F["Status"]): "Weg"}, "an option"),
                  ({str(F["Portal"]): "javascript:alert(1)"}, "a link"), ({"999999": "x"}, "an unknown field"), ({str(F["Kaution"]): "viel"}, "an amount")):
    r = Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": bad})
    check(r.status_code == 400, f"invalid {what}: 400 ({r.status_code} {r.text[:120]})")
check(cf(Fr, D1)["Seiten"]["value"] == "12.5", "a refused change leaves the value")
r = Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(F["Unterschrieben"]): False, str(F["Portal"]): None}})
check(r.ok and cf(Fr, D1)["Unterschrieben"]["value"] is None and cf(Fr, D1)["Portal"]["value"] is None, "unchecked / null clears the value")
check(one("SELECT COUNT(*) FROM doc_field_values WHERE node_id=?", (D1,)) == 5, "cleared values have no row")

# definitions: rename, a select option removed, delete
r = Fr.patch(B + f"/api/docs/fields/{F['Seiten']}", json={"name": "Seitenzahl"})
check(r.ok and cf(Fr, D1).get("Seitenzahl", {}).get("value") == "12.5", f"renamed, the value stays ({r.status_code})")
r = Fr.patch(B + f"/api/docs/fields/{F['Seiten']}", json={"name": "Vertragsnummer"})
check(r.status_code == 409, "renamed onto another field's name: 409")
r = Fr.patch(B + f"/api/docs/fields/{F['Status']}", json={"options": [{"id": OPT["Offen"], "name": "Offen"}, {"name": "Gekündigt"}]})
check(r.ok and cf(Fr, D1)["Status"]["value"] is None, f"the option of the value removed: the value goes ({r.status_code} {cf(Fr, D1)['Status']})")
check([o["name"] for o in cf(Fr, D1)["Status"]["options"]] == ["Offen", "Gekündigt"] and cf(Fr, D1)["Status"]["options"][0]["id"] == OPT["Offen"],
      "the kept option keeps its id")
Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": {"Status": "Gekündigt"}})  # by the option's name
check(cf(Fr, D1)["Status"]["label"] == "Gekündigt", "a select value by the option's name")
TMP = add(Fr, "private", "Wegwerf", "text").json()["id"]
Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(TMP): "weg damit"}})
r = Fr.delete(B + f"/api/docs/fields/{TMP}")
check(r.ok and r.json().get("values") == 1 and "Wegwerf" not in cf(Fr, D1), f"deleting a field ({r.status_code} {r.text[:100]})")
check(one("SELECT COUNT(*) FROM doc_field_values WHERE field_id=?", (TMP,)) == 0, "its values are gone")

# ==== the freelancer's own agent (API v1): sees and sets values of a document shared with it (edit)
r = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot"})
assert r.status_code == 201, r.text
FAG, FAGT = r.json()["id"], r.json().get("token") or ""
dbx("DELETE FROM org_members WHERE user_id=?", (FAG,))
dbx("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FRIDA, FAG))
AG = tok(FAGT)
check(AG.get(B + f"/api/v1/documents/{D1}").status_code == 404, "agent: nothing without a share")
r = Fr.post(B + f"/api/files/nodes/{D1}/shares", json={"agent_id": FAG, "role": "edit"})
check(r.status_code == 201, f"freelancer shares the document with the own agent ({r.status_code} {r.text[:200]})")
j = AG.get(B + f"/api/v1/documents/{D1}").json()
acf = {x["name"]: x for x in j.get("custom_fields") or []}
check(acf.get("Vertragsnummer", {}).get("value") == "MV-4711-Zebra" and acf.get("Kaution", {}).get("type") == "money", f"agent: sees the fields ({list(acf)})")
r = AG.patch(B + f"/api/v1/documents/{D1}", json={"custom_fields": {"Vertragsnummer": "MV-4712"}})
check(r.ok, f"agent: sets a value by name ({r.status_code} {r.text[:200]})")
d = Fr.get(B + f"/api/docs/{D1}").json()
check({x["name"]: x["value"] for x in d["custom_fields"]}.get("Vertragsnummer") == "MV-4712" and d["auto"].get(f"cf{F['Vertragsnummer']}") == "agent",
      f"the value is marked as set by an agent ({d['auto']})")
check(AG.patch(B + f"/api/v1/documents/{D1}", json={"custom_fields": {"Neues Feld": "x"}}).status_code == 400, "agent: an unknown field 400, no new field")
check(one("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (f"u{FRIDA}",)) == 7, "agent made no field")
check(AG.post(B + "/api/docs/fields", json={"ws": "private", "name": "Agent", "type": "text"}).status_code in (401, 403), "agent: no definitions")
Fr.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(F["Vertragsnummer"]): "MV-4711-Zebra"}})
check(f"cf{F['Vertragsnummer']}" not in Fr.get(B + f"/api/docs/{D1}").json()["auto"], "a person's change takes the mark away")

# ==== an organisation: admins define, members fill in
check(add(Ca, f"org:{ORG}", "Kundennummer", "text").status_code == 403, "a member defines no field (403)")
r = add(Bo, f"org:{ORG}", "Kundennummer", "text")
check(r.status_code == 201, f"the admin defines a field ({r.status_code} {r.text[:200]})")
KN = r.json().get("id")
check(add(Da, f"org:{ORG}", "Fremd", "text").status_code == 404, "another organisation's admin: 404")
check(Da.patch(B + f"/api/docs/fields/{KN}", json={"name": "X"}).status_code == 404 and Da.delete(B + f"/api/docs/fields/{KN}").status_code == 404,
      "another organisation's admin cannot change / delete it (404)")
check(Ca.patch(B + f"/api/docs/fields/{KN}", json={"name": "X"}).status_code == 403, "a member cannot rename it (403)")
check(Fr.delete(B + f"/api/docs/fields/{KN}").status_code == 404, "the freelancer cannot touch it (404)")
DO = doc(Ca, f"org:{ORG}", "angebot.txt", "Angebot Alpha Beispiel")
check("Kundennummer" in cf(Ca, DO) and Ca.get(B + f"/api/docs/settings?ws=org:{ORG}").json()["fields"][0]["name"] == "Kundennummer",
      "the member sees the organisation's field")
r = Ca.patch(B + f"/api/docs/{DO}", json={"custom_fields": {str(KN): "K-100"}})
check(r.ok and cf(Ca, DO)["Kundennummer"]["value"] == "K-100", f"the member fills it in ({r.status_code})")
check(Ca.patch(B + f"/api/docs/{DO}", json={"custom_fields": {str(F["Vertragsnummer"]): "x"}}).status_code == 400,
      "a field of another workspace is unknown on this document (400)")
check(Da.get(B + f"/api/docs/{DO}").status_code == 404, "another organisation does not see the document")

# ==== moving a document private -> Alpha: the values go along
r = Bo.post(B + "/api/docs/fields", json={"ws": f"org:{ORG}", "name": "Status", "type": "select", "options": "Gekündigt, Aktiv"})
ASTAT = r.json().get("id")
r = Bo.post(B + "/api/docs/fields", json={"ws": f"org:{ORG}", "name": "Seitenzahl", "type": "text"})  # same name, another type
D2 = doc(Ca, "private", "kuendigung.txt", "Kuendigung Beispiel")
r = Ca.post(B + "/api/docs/fields", json={"ws": "private", "name": "Status", "type": "select", "options": "Gekündigt"})
CST = r.json()["id"]
CSE = Ca.post(B + "/api/docs/fields", json={"ws": "private", "name": "Seitenzahl", "type": "number"}).json()["id"]
CNEU = Ca.post(B + "/api/docs/fields", json={"ws": "private", "name": "Akte", "type": "text"}).json()["id"]
r = Ca.patch(B + f"/api/docs/{D2}", json={"custom_fields": {str(CST): "Gekündigt", str(CSE): "3", str(CNEU): "A-77"}})
check(r.ok, "carol's private document with three values")
# 2.184.0 B (#2580): only an admin of the target makes the missing fields there -- carol (a member) is refused, as admin it works
r = Ca.post(B + "/api/files/move-space", json={"ids": [D2], "to": f"org:{ORG}", "parent": None})
check(r.status_code == 409 and one("SELECT ws FROM doc_meta WHERE node_id=?", (D2,)) == f"u{CAROL}", f"a member: refused, nothing moved ({r.status_code} {r.text[:200]})")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, CAROL))
r = Ca.post(B + "/api/files/move-space", json={"ids": [D2], "to": f"org:{ORG}", "parent": None})
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, CAROL))
check(r.ok, f"moved into Alpha ({r.status_code} {r.text[:300]})")
m = cf(Ca, D2)
check(m.get("Status", {}).get("id") == ASTAT and m["Status"]["label"] == "Gekündigt", f"the select value maps onto Alpha's field by the option's name ({m.get('Status')})")
check(m.get("Akte", {}).get("value") == "A-77" and one("SELECT ws FROM doc_fields WHERE id=?", (m["Akte"]["id"],)) == f"o{ORG}", "a missing field is made in Alpha")
check(m.get("Seitenzahl (2)", {}).get("type") == "number" and m["Seitenzahl (2)"]["value"] == "3" and m.get("Seitenzahl", {}).get("value") is None,
      f"the same name with another type: a field 'Seitenzahl (2)' ({ {k: (x['type'], x['value']) for k, x in m.items()} })")
rows = dbx("SELECT ws, org_id, value FROM doc_field_values WHERE node_id=?", (D2,))
check(len(rows) == 3 and all(x[0] == f"o{ORG}" and x[1] == ORG and x[2].startswith("kenc1:") for x in rows), f"the values belong to Alpha, sealed ({rows[:1]})")
check(cf(Bo, D2).get("Akte", {}).get("value") == "A-77", "Alpha's admin reads the value (Alpha's key)")
check(one("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (f"u{CAROL}",)) == 3, "the private definitions stay where they were")

# ==== 2.153.0 (#2179, review B1): the key passes on the command line carry the field values along (rotation, decrypt-all /
# encrypt-all, the private values between account key and server-derived key); editing a select field never drops a value
# it cannot open
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def cli(*args, env=()):
    e = [x for kv in env for x in ("-e", kv)]
    r = subprocess.run(["docker", "exec", "-i", *e, CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args],
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def vals(s, nid):
    return {k: x.get("value") for k, x in cf(s, nid).items()}


def raw(nid):
    return {r[0]: r[1] for r in dbx("SELECT field_id, value FROM doc_field_values WHERE node_id=?", (nid,))}


AV0, FV0 = vals(Bo, D2), vals(Fr, D1)
RA0, RF0 = raw(D2), raw(D1)
check(AV0.get("Akte") == "A-77" and FV0.get("Vertragsnummer") == "MV-4711-Zebra", f"before the key passes ({AV0} {FV0})")
check(one("SELECT COUNT(*) FROM doc_field_values WHERE id IS NULL") == 0 and one("SELECT COUNT(DISTINCT id) FROM doc_field_values") ==
      one("SELECT COUNT(*) FROM doc_field_values"), "every value row has its own row id")
rc, out = cli("rotate", "--org", str(ORG), env=("KALMIDO_ORGCRYPT_ROT_SETTLE=0",))
check(rc == 0 and '"unreadable": 0' in out and '"finished": true' in out, f"rotate Alpha's key: finished, nothing unreadable ({rc} {out[-300:].replace('R2-', 'R2?')})")
RA1 = raw(D2)
check(sorted(RA1) == sorted(RA0) and all(RA1[k].startswith("kenc1:") and RA1[k] != RA0[k] for k in RA0),
      "rotate: Alpha's field values re-encrypted with the new key")
check(vals(Bo, D2) == AV0 and vals(Ca, D2) == AV0, f"rotate: the values still readable ({vals(Bo, D2)})")
check(raw(D1) == RF0, "rotate: the freelancer's values untouched")
rc, out = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, "decrypt-all: no field value left sealed " + out[-300:])
check(not any(v.startswith("kenc1:") for v in list(raw(D2).values()) + list(raw(D1).values())), "decrypt-all: the field values are plain")
check(vals(Bo, D2) == AV0 and vals(Fr, D1) == FV0, "decrypt-all: the values read the same")
rc, out = cli("encrypt-all")
check(rc == 0 and all(v.startswith("kenc1:") for v in list(raw(D2).values()) + list(raw(D1).values())), "encrypt-all: the field values sealed again " + out[-300:])
check(vals(Bo, D2) == AV0 and vals(Fr, D1) == FV0, "encrypt-all: the values read the same")
RF1 = raw(D1)
rc, out = cli("docs-to-server-key")
check(rc == 0 and '"left": 0' in out and '"failed": 0' in out, "docs-to-server-key " + out[-300:])
check(raw(D1) != RF1 and vals(Fr, D1) == FV0, "docs-to-server-key: the freelancer's values in the other form, readable")
rc, out = cli("docs-to-account-key")
check(rc == 0 and '"left": 0' in out and '"failed": 0' in out, "docs-to-account-key " + out[-300:])
check(vals(Fr, D1) == FV0, "docs-to-account-key: the values readable")
# a select value that cannot be opened (sealed for another workspace) stays when the field's options are edited
dbx("UPDATE doc_field_values SET value=? WHERE node_id=? AND field_id=?", (raw(D1)[F["Vertragsnummer"]], D2, ASTAT))
BAD = raw(D2)[ASTAT]
r = Bo.patch(B + f"/api/docs/fields/{ASTAT}", json={"options": [{"name": "Aktiv"}, {"name": "Ruhend"}]})
check(r.ok and raw(D2).get(ASTAT) == BAD, f"editing the options never deletes a value it cannot open ({r.status_code} {r.text[:120]})")

print(f"p2108_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
