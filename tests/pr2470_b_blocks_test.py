#!/usr/bin/env python3
"""2.470.0 B (#3596): one place for texts: the letter blocks are rows of kind letter in office_texts, the routes
/api/office/letter-blocks a thin shell over them. Invented data only. tenant-matrix: office, freelancer-matrix: office
 - the move of the old rows: at the first look of an office, sealed bodies stay sealed (kenc1: under the new column), once only
   (a second look, a block deleted in the texts stays deleted), archived blocks stay archived, the old table keeps its rows
 - a block that cannot be opened: nothing moves, the blocks say so, the other texts still work; next look it moves
 - a block written by an older version after the step back comes over at the next look
 - the list Text blocks shows them for those who may, with the text in clear; search finds the sealed text; a long text survives
   saving there; the kind cannot change; no English text; the log holds no text
 - rights: a group with correspondence only keeps the blocks and does not reach the texts; a group with texts only sees none of them,
   neither by id nor by export; agents see none
 - a second organisation and a person without an organisation: own blocks only
 - the seeded catalogue still arrives when an office has only blocks; documents do not offer them
usage: pr2470_b_blocks_test.py <datadir>"""
# kalmido-suite: fresh
import base64
import os
import subprocess
import sys

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, CT, DATA, check, dbx, docker_logs_on_first_fail, done, fresh, sess, setup

fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()}, prefix="PR2470B")
docker_logs_on_first_fail()
A = setup()
FEAT = "clients,office,docs,files,contacts"
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BL, TX, R = "/api/office/letter-blocks", "/api/office/texts", "/api/office/rights"
uid = {}
for u in ("bob", "carl", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Fr = sess("bob"), sess("carl"), sess("frank")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
for s, w in ((Bo, f"org:{ORG}"), (Ca, f"org:{ORG}"), (Fr, f"org:{BETA}")):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT, "workspace": w})
TS = "2026-01-02T10:00:00Z"


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def old(oid, name, text, archived=0):
    """A block as the versions before 2.470.0 left it."""
    write("INSERT INTO office_letter_blocks(org_id, name, body, archived, created_at, updated_at) VALUES(?,?,?,?,?,?)", (oid, name, text, archived, TS, TS))


def letters(oid):
    # 2.997.0 (#5624): a deleted text lies in the core's trash (#5414, deleted_at) - only the live rows count
    return dbx("SELECT id, key, body, text_de, text_en, archived FROM office_texts WHERE org_id=? AND kind='letter' AND deleted_at IS NULL "
               "ORDER BY id", (oid,))


def blocks(s, q=""):
    return s.get(B + BL + q).json()["blocks"]


# ---------------------------------------------------------------- the move
check(A.get(B + "/api/office/settings").ok, "the office is open")
old(ORG, "Kündigung", "Hiermit kündige ich fristgerecht.")
old(ORG, "Alt", "Ein alter Text.", archived=1)
old(ORG, "Leer", "")
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "encrypt-all"], capture_output=True, text=True, timeout=300)
check(r.returncode == 0, "setup: the old rows are sealed " + r.stderr[-300:])
was = dbx("SELECT id, body FROM office_letter_blocks WHERE org_id=? ORDER BY id", (ORG,))
check(was[0][1].startswith("kenc1:"), "setup: the old body is sealed")
check(not letters(ORG), "nothing moved before the first look")
got = blocks(A)
check([x["name"] for x in got] == ["Kündigung", "Leer"] and got[0]["body"] == "Hiermit kündige ich fristgerecht.", f"the first look brings them over {got}")
rows = letters(ORG)
check(len(rows) == 3, f"three rows, also the archived one {rows}")
check(rows[0][2].startswith("kenc1:") and "kündige" not in str(rows[0]), f"the moved body is sealed, no clear text in the row {rows[0]}")
check(rows[0][3] == "" and rows[0][4] == "", "text_de / text_en stay empty in the database")
check(rows[1][5] == 1 and [x["name"] for x in blocks(A, "?archived=1")] == ["Alt", "Kündigung", "Leer"], "the archived block stays archived")
check(dbx("SELECT id, body FROM office_letter_blocks WHERE org_id=? ORDER BY id", (ORG,)) == was, "the old rows are untouched (the way back)")
check(all(x[0] for x in dbx("SELECT moved_to FROM office_letter_blocks WHERE org_id=?", (ORG,))), "each old row names where it went")
blocks(A)
A.get(B + TX)
check(len(letters(ORG)) == 3, "a second look moves nothing")
K = got[0]["id"]
check(K == rows[0][0], "the block's id is the text row's")
tx = A.get(B + TX).json()["items"]
T = next((x for x in tx if x["id"] == K), {})
check(T.get("kind") == "letter" and T.get("key") == "Kündigung" and T.get("text_de") == "Hiermit kündige ich fristgerecht." and "body" not in T,
      f"the list Text blocks shows it in clear {T}")
check(A.delete(B + f"{TX}/{rows[2][0]}").ok and len(letters(ORG)) == 2, "deleted in the texts")
check(bool(dbx("SELECT 1 FROM office_texts WHERE id=? AND deleted_at IS NOT NULL", (rows[2][0],))), "... it lies in the trash")  # 2.997.0 (#5624)
blocks(A)
check(len(letters(ORG)) == 2, "a deleted block does not come back from the old table")

# a step back to an older version wrote a block: it comes over, the others not again
old(ORG, "Neu aus alter Version", "Text")
check("Neu aus alter Version" in [x["name"] for x in blocks(A)] and len(letters(ORG)) == 3, "a block of an older version comes over")

# what cannot be opened stays where it is; the other texts go on
old(ORG, "Kaputt", "kenc1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
n = len(letters(ORG))
check(A.get(B + BL).status_code >= 400, "a block that cannot be opened: the blocks say so")
r = A.get(B + TX)
check(r.ok and len(letters(ORG)) == n, f"the other texts stay, nothing moved {r.status_code}")
write("UPDATE office_letter_blocks SET body='Wieder lesbar' WHERE org_id=? AND name='Kaputt'", (ORG,))
check("Kaputt" in [x["name"] for x in blocks(A)], "readable again: it comes over")

# ---------------------------------------------------------------- one text in two views
LONG = "Absatz\n" * 2000
r = A.post(B + BL, json={"name": "Lang", "body": LONG})
check(r.status_code == 201 and set(r.json()) >= {"id", "name", "body", "archived"}, "the shell writes " + r.text[:160])
L = r.json()["id"]
r = A.patch(B + f"{TX}/{L}", json={"key": "Länger", "kind": "letter", "text_en": "", "sort": 3})
check(r.ok and r.json()["text_de"] == LONG.strip("\n"), "saving in the texts keeps a text above the limit of the other kinds")
check(next(x for x in blocks(A) if x["id"] == L)["name"] == "Länger", "the block dialog reads the same row")
check(A.patch(B + f"{TX}/{L}", json={"kind": "note"}).status_code == 400, "a letter block stays one")
check(A.patch(B + f"{TX}/{L}", json={"text_en": "No"}).status_code == 400, "one text: an English one is refused, not dropped")
r = A.post(B + TX, json={"kind": "letter", "key": "Aus der Liste", "text_de": "Geheimtext Zebra"})
check(r.status_code == 201, "a new letter block from the list " + r.text[:160])
Z = r.json()["id"]
check(next(x for x in letters(ORG) if x[0] == Z)[2].startswith("kenc1:"), "it is sealed as well")
check(A.post(B + TX, json={"kind": "letter", "key": "", "text_de": "x"}).status_code == 400, "a letter block needs a name")
check([x["id"] for x in A.get(B + TX, params={"q": "zebra"}).json()["items"]] == [Z], "the search finds the sealed text")
N = A.post(B + TX, json={"kind": "note", "key": "plain", "text_de": "Eine Notiz"}).json()["id"]
check(A.patch(B + f"{TX}/{N}", json={"kind": "letter"}).status_code == 400, "a text in clear does not turn into a letter block")
check(A.get(B + f"{BL}").json()["blocks"] and A.patch(B + f"{BL}/{N}", json={"name": "x"}).status_code == 404, "the shell reaches letter rows only")
logs = dbx("SELECT detail FROM office_doc_log WHERE org_id=?", (ORG,))
check(not any("Zebra" in str(x[0]) for x in logs), "the log holds no text of a block")

# ---------------------------------------------------------------- rights
check(Bo.get(B + BL).status_code == 403, "a member without a group: blocks 403 as before")
check(not [x for x in Bo.get(B + TX).json().get("items", []) if x.get("kind") == "letter"], "a member: no letter rows in the texts")
check(Bo.get(B + f"{TX}/{Z}").status_code in (403, 404), "a member: not by id either")
check("Zebra" not in Bo.get(B + "/api/office/export").text, "a member: not in the export")
check("Zebra" not in A.get(B + "/api/office/export").text, "the master data file has no letter blocks at all")
r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Letters only"})
GL = r.json().get("id") or r.json()["group"]["id"]
check(A.patch(B + f"{R}/groups/{GL}", json={"levels": {"letters": "edit"}}).ok, "setup: a group with correspondence only")
r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Texts only"})
GT = r.json().get("id") or r.json()["group"]["id"]
check(A.patch(B + f"{R}/groups/{GT}", json={"levels": {"texts": "edit"}}).ok, "setup: a group with texts only")
check(A.put(B + f"{R}/people/{uid['bob']}", json={"groups": [f"g:{GL}"]}).ok and A.put(B + f"{R}/people/{uid['carl']}", json={"groups": [f"g:{GT}"]}).ok, "setup: the groups")
r = Bo.get(B + BL)
check(r.ok and Z in [x["id"] for x in r.json()["blocks"]], "correspondence only: the blocks stay " + r.text[:120])
check(Bo.post(B + BL, json={"name": "Von Bob", "body": "x"}).status_code == 201, "correspondence only: writes a block")
check(Bo.get(B + TX).status_code == 403, "correspondence only: the texts stay closed")
r = Ca.get(B + TX)
check(r.ok and r.json()["items"] and not [x for x in r.json()["items"] if x["kind"] == "letter"], "texts only: the other texts, no letter rows " + r.text[:120])
check(Ca.get(B + TX, params={"q": "Zebra"}).json()["items"] == [], "texts only: the search finds none")
check(Ca.get(B + f"{TX}/{Z}").status_code == 404, "texts only: not by id")
check(Ca.patch(B + f"{TX}/{Z}", json={"key": "x"}).status_code == 403 and Ca.delete(B + f"{TX}/{Z}").status_code == 403, "texts only: neither change nor delete")
check(Ca.post(B + TX, json={"kind": "letter", "key": "x", "text_de": "y"}).status_code == 403, "texts only: no new block")
check(Ca.get(B + BL).status_code == 403, "texts only: the shell stays closed")
check(Ca.patch(B + f"{TX}/{N}", json={"text_de": "Geändert"}).ok, "texts only: the other kinds as before")

# ---------------------------------------------------------------- tenants and a person without an organisation
check(blocks(Fr) == [], "Beta sees none of Alpha's blocks")
check(Fr.get(B + f"{TX}/{Z}").status_code == 404 and Fr.patch(B + f"{BL}/{Z}", json={"name": "x"}).status_code == 404, "Beta: Alpha's rows 404")
old(BETA, "Beta alt", "Text von Beta")
check([x["name"] for x in blocks(Fr)] == ["Beta alt"], "Beta's own old block comes over")
check([x[1] for x in letters(BETA)] == ["Beta alt"] and "Beta alt" not in [x["name"] for x in blocks(A)], "in its own organisation")
FID, Fi = freelancer(B, A)
check(Fi.get(B + "/api/office/settings").ok, "freelancer: the office opens")
POID = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
old(POID, "Privat alt", "Mein Text")
r = Fi.post(B + BL, json={"name": "Privat neu", "body": "Noch ein Text"})
check(r.status_code == 201, "freelancer: a new block " + r.text[:160])
check(sorted(x["name"] for x in blocks(Fi)) == ["Privat alt", "Privat neu"], "freelancer: moved and new, only the own")
check({x["kind"] for x in Fi.get(B + TX).json()["items"]} >= {"letter"}, "freelancer: the blocks in the own texts (own admin)")
check(Fi.get(B + BL + "/starters?lang=en").ok and Fi.post(B + BL, json={"starter": "cancel", "lang": "en"}).status_code == 201, "freelancer: a sample")

# ---------------------------------------------------------------- catalogue and documents
_, G = freelancer(B, A, "fiona")
check(G.post(B + BL, json={"name": "Zuerst", "body": "Vor allem anderen"}).status_code == 201, "an office whose first text is a block")
G.get(B + "/api/office/settings")
kinds = {x["kind"] for x in G.get(B + TX).json()["items"]}
check("intro" in kinds and "rights_time" in kinds, f"the catalogue of the pack still arrives {kinds}")
sys.exit(done("pr2470_b_blocks"))
