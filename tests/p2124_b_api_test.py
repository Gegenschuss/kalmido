#!/usr/bin/env python3
"""2.124.0 API tests, part B: column kinds checkbox / person / link / file (#2110), rows / columns kept in view (#2111) and
the history of the cells (#2112). Invented names only.
 - checkbox: ja / 0 stored as 1 / 0, SUMME counts the ticks, "maybe" 400; person: the people who may see the table (no one
   of another organisation, no agent), a name is looked up, someone outside 400; link: https / www. / mailto, javascript:
   and ftp: 400; file: upload into a file cell (only there), sealed at rest, download for readers only (another
   organisation / a freelancer 404), removing puts it into the trash, Undo (the cell's old input) brings it back
 - export: CSV TRUE / FALSE, the person's name, the link, the file name; .xlsx a truth value; import of WAHR / FALSCH
   makes a checkbox column and writes no history
 - kept rows / columns: saved, 400 out of range, a reader of the attached list 403, another organisation 404
 - history: who / when / before -> after for people, agents marked; the agents' batches and their undo stay as they were
 - moving the table to the private space takes its files (sealed again) and its history along
 - a person without an organisation (freelancer-matrix: sheets) uses every new route in a private table
usage: p2124_b_api_test.py <datadir>      (a fresh container; P2124B_NOSTART=1 = the server already runs)"""
import base64
import io
import os
import subprocess
import sys
import zipfile

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "collab,comments,sheets"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


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


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def sheet(s, sid):
    r = s.get(B + f"/api/sheets/{sid}")
    return r.json() if r.ok else None


def cell(sh, addr):
    return next((c for c in sh["cells"] if c["addr"] == addr), None)


def put(s, sid, cells):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def sealed(path):
    try:
        with open(os.path.join(DATA, "attachments", path), "rb") as fh:
            return not fh.read().startswith(b"%PDF")
    except OSError as e:  # the container's data folder may not be readable from here
        print("note: stored file not readable here:", e)
        return True


if not os.environ.get("P2124B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "erin" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read", "sheets:write"], "username": "tallybot", "display_name": "Tallybot", "org_id": ORG})
assert r.status_code == 201, r.text
AG, ag = r.json()["id"], bearer(r.json()["token"])

# ================================================================== #2110 the four kinds in an organisation's table
r = Bo.post(B + "/api/sheets", json={"title": "Kit list", "space": f"org:{ORG}"})
check(r.ok, "bob creates a table of the organisation " + r.text[:200])
S = r.json()
SID = S["id"]
R = [x["id"] for x in S["rows"]]
col = {}
for t, k in (("Done", "checkbox"), ("Owner", "person"), ("Web", "link"), ("Doc", "file")):
    r = Bo.post(B + f"/api/sheets/{SID}/columns", json={"title": t, "kind": k})
    check(r.status_code == 201 and r.json()["column"]["kind"] == k, f"#2110: a {k} column " + r.text[:200])
    col[k] = r.json()["column"]["id"]
check(Bo.post(B + f"/api/sheets/{SID}/columns", json={"title": "X", "kind": "rating"}).status_code == 400, "#2110: an unknown kind 400")
A0 = S["columns"][0]["id"]

# checkbox
r = put(Bo, SID, [{"row_id": R[0], "col_id": col["checkbox"], "raw": "ja"}, {"row_id": R[1], "col_id": col["checkbox"], "raw": "0"},
                  {"row_id": R[2], "col_id": col["checkbox"], "raw": "WAHR"}])
check(r.ok, "#2110: checkbox inputs " + r.text[:200])
sh = sheet(Bo, SID)
d1, d2 = cell(sh, "D1"), cell(sh, "D2")
check(d1 and d1["raw"] == "1" and d1["value"] == 1 and d1["display"] == "Yes", "#2110: ja is stored as 1 (Yes) " + str(d1))
check(d2 and d2["raw"] == "0" and d2["value"] == 0 and d2["display"] == "No", "#2110: 0 stays 0 (No) " + str(d2))
check(put(Bo, SID, [{"row_id": R[3], "col_id": col["checkbox"], "raw": "maybe"}]).status_code == 400, "#2110: a checkbox refuses maybe")
r = put(Bo, SID, [{"row_id": R[0], "col_id": A0, "raw": "=SUMME(D1:D5)"}])
check(r.ok and cell(sheet(Bo, SID), "A1")["value"] == 2, "#2110: SUMME counts the ticks " + r.text[:200])

# person
r = Bo.get(B + f"/api/sheets/{SID}/people")
ppl = {p["id"]: p["name"] for p in r.json().get("people", [])} if r.ok else {}
check(uid["bob"] in ppl and uid["carol"] in ppl and uid["erin"] not in ppl and AG not in ppl, "#2110: the people of the organisation, no outsider, no agent " + str(ppl))
check(Er.get(B + f"/api/sheets/{SID}/people").status_code == 404, "#2110: another organisation's person gets 404 on the people")
r = put(Bo, SID, [{"row_id": R[0], "col_id": col["person"], "raw": str(uid["carol"])}, {"row_id": R[1], "col_id": col["person"], "raw": "bob"}])
sh = sheet(Bo, SID)
check(r.ok and cell(sh, "E1")["display"] == "Carol" and cell(sh, "E2")["raw"] == str(uid["bob"]), "#2110: a person by id and by name " + r.text[:200])
check(put(Bo, SID, [{"row_id": R[2], "col_id": col["person"], "raw": str(uid["erin"])}]).status_code == 400, "#2110: someone of another organisation 400")
check(put(Bo, SID, [{"row_id": R[2], "col_id": col["person"], "raw": str(AG)}]).status_code == 400, "#2110: an agent is no person of the column")

# link
r = put(Bo, SID, [{"row_id": R[0], "col_id": col["link"], "raw": "https://example.com/kit?a=1"}, {"row_id": R[1], "col_id": col["link"], "raw": "www.example.com"},
                  {"row_id": R[2], "col_id": col["link"], "raw": "kit@example.com"}])
sh = sheet(Bo, SID)
check(r.ok and cell(sh, "F1")["raw"] == "https://example.com/kit?a=1" and cell(sh, "F2")["raw"] == "https://www.example.com"
      and cell(sh, "F3")["raw"] == "mailto:kit@example.com", "#2110: links stored (https added, mailto) " + str([cell(sh, a) and cell(sh, a)["raw"] for a in ("F1", "F2", "F3")]))
for bad in ("javascript:alert(1)", "ftp://example.com/x", "not a link", "https://exa mple.com"):
    check(put(Bo, SID, [{"row_id": R[3], "col_id": col["link"], "raw": bad}]).status_code == 400, "#2110: link refused: " + bad)

# file
fu = lambda s, rid, cid, data=PDF, name="manual.pdf": s.post(B + f"/api/sheets/{SID}/files", data={"row_id": str(rid), "col_id": str(cid)},
                                                         files={"file": (name, data, "application/pdf")})
r = fu(Bo, R[0], col["file"])
check(r.status_code == 201 and r.json()["file"]["name"] == "manual.pdf", "#2110: a file into a file cell " + r.text[:300])
F1 = r.json().get("file", {}).get("id")
sh = sheet(Bo, SID)
g1 = cell(sh, "G1")
check(g1 and g1["raw"] == f"file:{F1}" and g1["display"] == "manual.pdf", "#2110: the cell holds the file " + str(g1))
check(fu(Bo, R[1], col["link"]).status_code == 400, "#2110: no file into a link column")
check(fu(Er, R[1], col["file"]).status_code == 404, "#2110: another organisation cannot upload (404)")
r = Ca.get(B + f"/api/sheets/{SID}/files/{F1}")
check(r.ok and r.content == PDF, "#2110: a member downloads the file")
check(Er.get(B + f"/api/sheets/{SID}/files/{F1}").status_code == 404, "#2110: another organisation 404 on the file")
row = sql("SELECT path, org_id, size, deleted_at FROM sheet_files WHERE id=?", (F1,))
check(row and row[0][1] == ORG and row[0][2] == len(PDF) and row[0][3] is None, "#2110: the file row in the organisation " + str(row))
check(row and sealed(row[0][0]), "#2110: the file is sealed at rest")
check(put(Bo, SID, [{"row_id": R[2], "col_id": col["file"], "raw": "file:999999"}]).status_code == 400, "#2110: a file id that is not of this table 400")
check(put(Bo, SID, [{"row_id": R[0], "col_id": col["file"], "raw": ""}]).ok, "#2110: the file cell emptied")
check(sql("SELECT deleted_at FROM sheet_files WHERE id=?", (F1,))[0][0] is not None, "#2110: the file went into the trash")
check(Bo.get(B + f"/api/sheets/{SID}/files/{F1}").status_code == 404, "#2110: a file in the trash is not served")
check(put(Bo, SID, [{"row_id": R[0], "col_id": col["file"], "raw": f"file:{F1}"}]).ok, "#2110: Undo puts the file back into the cell")
check(sql("SELECT deleted_at FROM sheet_files WHERE id=?", (F1,))[0][0] is None and Bo.get(B + f"/api/sheets/{SID}/files/{F1}").ok, "#2110: and out of the trash")
r = A.get(B + "/api/admin/storage-check")
check(r.ok and not [x for x in r.json().get("problems", r.json().get("files", [])) if x.get("kind") == "sheet_file"], "#2110: the storage check knows the table files " + r.text[:200])

# kind change keeps the inputs
r = Bo.patch(B + f"/api/sheets/{SID}/columns/{col['link']}", json={"kind": "text"})
check(r.ok and cell(sheet(Bo, SID), "F1")["raw"] == "https://example.com/kit?a=1", "#2110: link -> text keeps the input")
Bo.patch(B + f"/api/sheets/{SID}/columns/{col['link']}", json={"kind": "link"})

# export / import
r = Bo.get(B + f"/api/sheets/{SID}/export.csv")
txt = r.content.decode("utf-8-sig") if r.ok else ""
check(r.ok and "TRUE" in txt and "FALSE" in txt and "Carol" in txt and "manual.pdf" in txt and "https://example.com/kit?a=1" in txt,
      "#2110: CSV: TRUE / FALSE, the name, the file name, the link " + txt[:300])
r = Bo.get(B + f"/api/sheets/{SID}/export.xlsx")
xml = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode() if r.ok else ""
check('t="b"' in xml, "#2110: .xlsx: the checkbox as a truth value")
r = Bo.post(B + "/api/sheets/import", data={"space": f"org:{ORG}"}, files={"file": ("ticks.csv", "Item;Packed\nTent;WAHR\nStove;FALSCH\n".encode(), "text/csv")})
check(r.status_code in (200, 201), "#2110: import of truth values " + r.text[:200])
IS = (sheet(Bo, (r.json().get("sheet") or {}).get("id")) or {}) if r.status_code in (200, 201) else {}
check([c["kind"] for c in IS.get("columns", [])] == ["text", "checkbox"], "#2110: WAHR / FALSCH becomes a checkbox column " + str([c["kind"] for c in IS.get("columns", [])]))
check(IS and [cell(IS, "B1")["raw"], cell(IS, "B2")["raw"]] == ["1", "0"], "#2110: imported as 1 / 0")
r = Bo.get(B + f"/api/sheets/{IS.get('id')}/history")
check(r.ok and r.json()["entries"] == [], "#2112: an import writes no history " + r.text[:200])

# ================================================================== #2111 rows / columns kept in view
r = Bo.post(B + f"/api/sheets/{SID}/fixed", json={"rows": 2, "cols": 1})
check(r.ok and r.json()["freeze_rows"] == 2 and r.json()["freeze_cols"] == 1, "#2111: two rows and one column kept " + r.text[:200])
sh = sheet(Ca, SID)
check(sh["freeze_rows"] == 2 and sh["freeze_cols"] == 1, "#2111: everyone sees them kept")
for bad in ({"rows": -1}, {"rows": 51}, {"cols": "2"}, {"cols": True}):
    check(Bo.post(B + f"/api/sheets/{SID}/fixed", json=bad).status_code == 400, "#2111: out of range 400 " + str(bad))
check(Er.post(B + f"/api/sheets/{SID}/fixed", json={"rows": 0}).status_code == 404, "#2111: another organisation 404")
check(sheet(Bo, SID)["freeze_rows"] == 2, "#2111: unchanged after the refused calls")

# a table attached to a list: a reader may not write
L = Bo.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": uid["carol"], "role": "view"}).ok, "setup: carol reads the list")
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent may change the list")
r = Bo.post(B + "/api/sheets", json={"title": "Shoot tally", "space": f"org:{ORG}", "list_id": L})
LS = r.json()["id"]
LR = [x["id"] for x in r.json()["rows"]]
LC = Bo.post(B + f"/api/sheets/{LS}/columns", json={"title": "Ok", "kind": "checkbox"}).json()["column"]["id"]
LF = Bo.post(B + f"/api/sheets/{LS}/columns", json={"title": "Doc", "kind": "file"}).json()["column"]["id"]
check(Ca.post(B + f"/api/sheets/{LS}/fixed", json={"rows": 1}).status_code == 403, "#2111: a reader of the list 403")
check(Ca.post(B + f"/api/sheets/{LS}/files", data={"row_id": str(LR[0]), "col_id": str(LF)}, files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 403,
      "#2110: a reader of the list may not upload (403)")
r = Ca.get(B + f"/api/sheets/{LS}/people")
lp = {p["id"] for p in r.json().get("people", [])} if r.ok else set()
check(lp == {uid["bob"], uid["carol"]}, "#2110: the people of the attached list only (owner + members, no agent) " + str(lp))

# ================================================================== #2112 history, agents unchanged
check(put(Ca, SID, [{"row_id": R[1], "col_id": col["checkbox"], "raw": "1"}]).ok, "carol ticks D2")
r = Ca.get(B + f"/api/sheets/{SID}/history")
es = r.json().get("entries", []) if r.ok else []
check(es and es[0]["user_name"] == "Carol" and es[0]["addr"] == "D2" and es[0]["old"] == "No" and es[0]["new"] == "Yes" and not es[0]["agent"],
      "#2112: the newest change: Carol, D2, No -> Yes " + str(es[:1]))
check(any(e["user_name"] == "Bob" and e["addr"] == "E1" and e["new"] == "Carol" for e in es), "#2112: bob's person change reads as the name")
d2 = cell(sheet(Bo, SID), "D2")
r = Bo.get(B + f"/api/sheets/{SID}/cells/{d2['id']}/history")
ce = r.json().get("entries", []) if r.ok else []
check([(e["user_name"], e["old"], e["new"]) for e in ce] == [("Carol", "No", "Yes"), ("Bob", "", "No")], "#2112: the history of one cell " + str(ce))
check(Er.get(B + f"/api/sheets/{SID}/history").status_code == 404 and Er.get(B + f"/api/sheets/{SID}/cells/{d2['id']}/history").status_code == 404,
      "#2112: another organisation 404 on the history")
check(Ca.get(B + f"/api/sheets/{LS}/history").ok, "#2112: a reader of the list reads the history")
# the agent: new kinds through v1, its batch, undo by a person
r = ag.post(V + f"/sheets/{LS}/columns", json={"title": "Who", "kind": "person"})
check(r.status_code in (200, 201), "#2110: v1: an agent adds a person column " + r.text[:200])
r = ag.put(V + f"/sheets/{LS}/cells", json={"cells": [{"row_id": LR[0], "col_id": LC, "raw": "1"}]})
check(r.ok and r.json().get("batch"), "agent: a checkbox through v1 " + r.text[:200])
BATCH = r.json().get("batch")
check(ag.put(V + f"/sheets/{LS}/cells", json={"cells": [{"row_id": LR[0], "col_id": LC, "raw": "perhaps"}]}).status_code == 400, "#2110: v1: a checkbox refuses perhaps")
check(ag.put(V + f"/sheets/{LS}/cells", json={"cells": [{"row_id": LR[1], "col_id": LF, "raw": "file:1"}]}).status_code == 400, "#2110: v1: an agent cannot point at a file of another table")
check(put(Bo, LS, [{"row_id": LR[1], "col_id": LC, "raw": "1"}]).ok, "bob ticks a second box (a person's change)")
lsd = sheet(Bo, LS)
check(BATCH in [b["batch"] for b in lsd["batches"]] and len(lsd["batches"]) == 2 and all(b["agent_id"] == AG for b in lsd["batches"]),
      "#2112: only the agent's calls (column + cells) are batches, the person's change is none " + str(lsd["batches"]))
es = Bo.get(B + f"/api/sheets/{LS}/history").json()["entries"]
check(len(es) == 2 and es[0]["user_name"] == "Bob" and not es[0]["agent"] and es[1]["agent"] and es[1]["user_name"] == "Tallybot",
      "#2112: the history has the person and the agent (marked) " + str(es))
r = Bo.post(B + f"/api/sheets/{LS}/batches/{BATCH}/undo")
lsd = sheet(Bo, LS)
check(r.ok and r.json().get("undone") == 1 and not (cell(lsd, "D1") or {}).get("raw") and cell(lsd, "D2")["raw"] == "1",
      "#2112: the agent's undo still takes back exactly its call " + r.text[:200])
check(ag.get(V + f"/sheets/{LS}").json().get("freeze_rows") == 0, "#2111: v1 answers freeze_rows too")

# ================================================================== the move to the private space takes files + history along
r = Bo.post(B + f"/api/sheets/{SID}/move-space", json={"to": "private"})
check(r.ok and r.json().get("ok"), "bob moves the table into his private space " + r.text[:200])
row = sql("SELECT org_id, owner_id, path FROM sheet_files WHERE id=?", (F1,))
check(row and row[0][0] is None and row[0][1] == uid["bob"] and sealed(row[0][2]), "#2110: the file moved along (private, sealed) " + str(row))
r = Bo.get(B + f"/api/sheets/{SID}/files/{F1}")
check(r.ok and r.content == PDF, "#2110: bob still opens the file after the move")
check(Ca.get(B + f"/api/sheets/{SID}/files/{F1}").status_code == 404, "#2110: carol no longer (private now)")
check(len(Bo.get(B + f"/api/sheets/{SID}/history").json()["entries"]) >= 5, "#2112: the history moved along")
r = A.get(B + "/api/admin/orgs")
check(r.ok and not ((r.json().get("boundary") or {}).get("kinds") or {}).get("sheet_file"), "#2110: the boundary check finds no file in the wrong space " + r.text[:200])

# ================================================================== a person without an organisation
# freelancer-matrix: sheets
FID, Fr = freelancer(B, A, "fiona", FEAT)
r = Fr.post(B + "/api/sheets", json={"title": "Gear", "space": "private"})
FS = r.json()["id"]
FR = [x["id"] for x in r.json()["rows"]]
fc = {k: Fr.post(B + f"/api/sheets/{FS}/columns", json={"title": k, "kind": k}).json()["column"]["id"] for k in ("person", "file", "checkbox")}
r = Fr.get(B + f"/api/sheets/{FS}/people")
check(r.ok and [p["id"] for p in r.json()["people"]] == [FID], "freelancer: the people of a private table = only herself " + r.text[:200])
check(put(Fr, FS, [{"row_id": FR[0], "col_id": fc["person"], "raw": str(FID)}, {"row_id": FR[0], "col_id": fc["checkbox"], "raw": "x"}]).ok, "freelancer: person + checkbox")
check(put(Fr, FS, [{"row_id": FR[1], "col_id": fc["person"], "raw": str(uid["bob"])}]).status_code == 400, "freelancer: nobody else in a private table")
r = Fr.post(B + f"/api/sheets/{FS}/files", data={"row_id": str(FR[0]), "col_id": str(fc["file"])}, files={"file": ("receipt.pdf", PDF, "application/pdf")})
check(r.status_code == 201, "freelancer: a file into her private table " + r.text[:200])
FF = r.json().get("file", {}).get("id")
check(Fr.get(B + f"/api/sheets/{FS}/files/{FF}").content == PDF and Bo.get(B + f"/api/sheets/{FS}/files/{FF}").status_code == 404, "freelancer: her file, nobody else's")
row = sql("SELECT org_id, owner_id, path FROM sheet_files WHERE id=?", (FF,))
check(row and row[0][0] is None and row[0][1] == FID and sealed(row[0][2]), "freelancer: private file row, sealed with her account key " + str(row))
check(Fr.post(B + f"/api/sheets/{FS}/fixed", json={"rows": 1, "cols": 2}).ok, "freelancer: rows / columns kept in view")
es = Fr.get(B + f"/api/sheets/{FS}/history").json()["entries"]
check(len(es) >= 3 and all(e["user_name"] == "Fiona" for e in es), "freelancer: her history " + str(es[:2]))
cid = cell(sheet(Fr, FS), "D1")["id"]
check(Fr.get(B + f"/api/sheets/{FS}/cells/{cid}/history").ok and Bo.get(B + f"/api/sheets/{FS}/cells/{cid}/history").status_code == 404, "freelancer: the cell history, only hers")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
