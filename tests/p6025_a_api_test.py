#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1138.0 (#6025, #6026, #6027): a knowledge page shared by e-mail address must not tell the sharer whether the address has
an account (Fable review 2.1115, H1 / H2 / M2 / N1 / N3). Invented people and pages only, everyone a person without an
organisation.
freelancer-matrix: wiki
 - #6026: the tree's mark, the page's counter and WSH_MAX see an open share by address like one that found its account
 - #6025: the file store's view of the page's node (GET /api/files/nodes/<id>: shares, mark, history) is the same for both;
   its share routes do not reach a share by address (404)
 - #6027 M2: an address whose account has the page by name already gets an entry of its own, bound once the name share ends
 - #6027 N3: at the limit of shares by address (ADS_MAX) both kinds get the same refusal
 - #6027 N1: the Undo of an open share whose address was proved in between makes the share at once
usage: p6025_a_api_test.py <datadir>      (KMT_NOSTART=1 / P6025A_NOSTART=1: a running server)"""
import sys

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P6025A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FEAT = "wiki,files,collab"

FID, F = freelancer(B, A, "frida", features=FEAT)
UID, U = freelancer(B, A, "uma", features=FEAT)
VID, V = freelancer(B, A, "vera", features=FEAT)
MID, M = freelancer(B, A, "mia", features=FEAT)
LID, L = freelancer(B, A, "lena", features=FEAT)
dbx("UPDATE users SET email_proved=email WHERE id IN (?, ?)", (UID, VID))  # uma and vera proved their address, lena not


def page(path):
    r = F.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": "text of " + path})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def share_mail(pid, em):
    return F.post(B + "/api/wiki/shares", json={"page_id": pid, "kind": "person", "email": em})


def people(pid):
    return [s for s in F.get(B + "/api/wiki/shares", params={"page": pid}).json().get("shares", []) if s["kind"] == "person"]


def node_of(pid):
    return dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (pid,))[0][0]


def shares_log(nid):
    return [x for x in F.get(B + f"/api/files/nodes/{nid}").json().get("log", []) if x["action"] in ("share", "unshare", "share_change")]


def shared_with(s):
    return {x["path"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


PB, PO = page("Bound offer"), page("Open offer")
PM0 = page("Mia's page")
check(share_mail(PM0, "mia@example.com").ok, "(setup) mia's unproved address: an open share")
for pid, em in ((PB, "uma@example.com"), (PO, "nobody@example.com")):
    r = share_mail(pid, em)
    check(r.ok and r.json() == {"ok": True, "by_email": True}, f"(setup) {em} by address {r.status_code} {r.text[:200]}")
check("Bound offer" in shared_with(U), "(setup) uma's proved address found her account")

# ================================================================ #6026: mark, counter, WSH_MAX
tree = {d["path"]: d for d in F.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}
check(tree["Bound offer"].get("shared") == 1 and tree["Open offer"].get("shared") == 1,
      f"#6026: the tree marks both pages shared {tree['Bound offer'].get('shared')} {tree['Open offer'].get('shared')}")
cb, co = (F.get(B + f"/api/wiki/pages/{p}").json().get("shares") for p in (PB, PO))
check(cb == co == 1, f"#6026: the page's counter is 1 for both kinds {cb} {co}")
row = dbx("SELECT id FROM obj_addr_shares WHERE kind='wiki' AND created_by=? ORDER BY id LIMIT 1", (FID,))[0][0]
dbx("INSERT INTO obj_addr_shares(kind,ref_id,owner_id,org_id,path,body,email_seal,email_key,created_by,created_at) "
    "SELECT kind, NULL, owner_id, org_id, 'zz6026/' || g, CAST('{}' AS JSONB), email_seal, email_key, created_by, created_at "
    "FROM obj_addr_shares, generate_series(1, 300) g WHERE id=?", (row,))
r = F.post(B + "/api/wiki/shares", json={"page_id": PB, "kind": "link"})
check(r.status_code == 400 and "Too many shares" in r.text, f"#6026: open shares count towards WSH_MAX {r.status_code} {r.text[:200]}")
# Fable review 2.1138 F1: at WSH_MAX the replay of an open share (counted already) still binds it, it is not dropped
dbx("UPDATE users SET email_proved=email WHERE id=?", (MID,))
M = sess("mia")
check("Mia's page" in shared_with(M), "#6026 (F1): at WSH_MAX mia's sign-in still makes her open share")
dbx("DELETE FROM obj_addr_shares WHERE path LIKE 'zz6026/%'")

# ================================================================ #6025: the file store's view of the page's node
NB, NO = node_of(PB), node_of(PO)
jb, jo = (F.get(B + f"/api/files/nodes/{n}").json() for n in (NB, NO))
check(set(jb) == set(jo) and jb.get("shares") == jo.get("shares") == [] and jb.get("inherited") == jo.get("inherited") == [],
      f"#6025: the node's shares look the same for both kinds (none) {sorted(set(jb) ^ set(jo))} {jb.get('shares')} {jo.get('shares')}")
check(jb.get("shared") == jo.get("shared"), f"#6025: the node's shared mark is the same {jb.get('shared')} {jo.get('shared')}")
check(shares_log(NB) == shares_log(NO) == [], f"#6025: no history line names uma's account {shares_log(NB)}")
fid = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (NB, UID))[0][0]
check(F.patch(B + f"/api/files/shares/{fid}", json={"role": "edit"}).status_code == 404
      and F.delete(B + f"/api/files/shares/{fid}").status_code == 404,
      "#6025: the file store's routes do not reach a share by address (as there is no row for an open one)")
ub = next((s for s in people(PB) if s["user"]["name"] == "uma@example.com"), None)
check(ub is not None and F.delete(B + f"/api/wiki/shares/{ub['id']}").ok and F.post(B + f"/api/wiki/shares/{ub['id']}/restore").ok,
      "(setup) uma's share by address ends and comes back in the knowledge dialog")
check(shares_log(NB) == [], f"#6025: ... still no history line with her account {shares_log(NB)}")
check("Bound offer" in shared_with(U), "#6025: uma still reads the page")

# ================================================================ #6027 M2: by name first, then the address
PM = page("Name first")
r = F.post(B + "/api/wiki/shares", json={"page_id": PM, "kind": "person", "user_id": VID})
check(r.status_code == 201, f"(setup) vera by name {r.status_code} {r.text[:200]}")
r = share_mail(PM, "vera@example.com")
check(r.ok and r.json() == {"ok": True, "by_email": True}, f"#6027 M2: the answer of any address {r.status_code} {r.text[:200]}")
ppl = people(PM)
check(sorted((s["user"].get("by_email") is True, s["user"]["name"]) for s in ppl) == [(False, "Vera"), (True, "vera@example.com")],
      f"#6027 M2: the address gets an entry of its own next to the share by name {[(s['user']) for s in ppl]}")
V = sess("vera")
check(len(people(PM)) == 2, "#6027 M2: vera's sign-in leaves both entries (the share by name is still there)")
byname = next(s for s in ppl if not s["user"].get("by_email"))
check(F.delete(B + f"/api/wiki/shares/{byname['id']}").ok, "(setup) the share by name ends")
V = sess("vera")
ppl = people(PM)
check([s["user"]["name"] for s in ppl] == ["vera@example.com"] and "Name first" in shared_with(V)
      and not dbx("SELECT 1 FROM obj_addr_shares WHERE kind='wiki' AND ref_id=?", (PM,)),
      f"#6027 M2: at her next sign-in the share by address is made {[s['user'] for s in ppl]}")

# ================================================================ #6027 N3: the limit, the same refusal for both kinds
n = dbx("SELECT COUNT(*) FROM obj_addr_shares WHERE created_by=?", (FID,))[0][0] + dbx(
    "SELECT COUNT(*) FROM wiki_share_cards k JOIN fs_shares f ON f.id=k.fs_share_id WHERE k.email<>'' AND f.created_by=?", (FID,))[0][0]
dbx("INSERT INTO obj_addr_shares(kind,ref_id,owner_id,org_id,path,body,email_seal,email_key,created_by,created_at) "
    "SELECT kind, NULL, owner_id, org_id, 'zz6027/' || g, CAST('{}' AS JSONB), email_seal, email_key, created_by, created_at "
    "FROM obj_addr_shares, generate_series(1, ?) g WHERE id=?", (200 - n, row))
PL = page("At the limit")
ra, rb = share_mail(PL, "uma@example.com"), share_mail(PL, "nobody2@example.com")
check(ra.status_code == rb.status_code == 409 and ra.json() == rb.json(),
      f"#6027 N3: at ADS_MAX both kinds get the same refusal {ra.status_code} {ra.text[:120]} | {rb.status_code} {rb.text[:120]}")
check("At the limit" not in shared_with(U), "#6027 N3: ... and uma's account got nothing")
dbx("DELETE FROM obj_addr_shares WHERE path LIKE 'zz6027/%'")
ra, rb = share_mail(PL, "uma@example.com"), share_mail(PL, "nobody2@example.com")
check(ra.ok and rb.ok and ra.json() == rb.json(), f"#6027 N3: under the limit both work again {ra.status_code} {rb.status_code}")

# ================================================================ #6027 N1: proved between the end and the Undo
PN = page("Late proof")
check(share_mail(PN, "lena@example.com").ok, "(setup) lena's unproved address: an open share")
ln = next(s for s in people(PN) if s["user"]["name"] == "lena@example.com")
check(F.delete(B + f"/api/wiki/shares/{ln['id']}").ok, "(setup) the open share ends")
dbx("UPDATE users SET email_proved=email WHERE id=?", (LID,))  # lena proves her address while it is ended
r = F.post(B + f"/api/wiki/shares/{ln['id']}/restore")
check(r.ok and r.json().get("id") == ln["id"], f"#6027 N1: the Undo answers as for any address {r.status_code} {r.text[:200]}")
check("Late proof" in shared_with(L) and not dbx("SELECT 1 FROM obj_addr_shares WHERE kind='wiki' AND ref_id=?", (PN,)),
      "#6027 N1: the share is made at once (no open row left until her next sign-in)")
check([s["user"]["name"] for s in people(PN)] == ["lena@example.com"], "#6027 N1: the dialog still shows the address")

sys.exit(done("p6025_a_api"))
