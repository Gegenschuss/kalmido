#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.654.0 D (#4585): the tasks made from a quotation keep their quotation positions through an organisation export and import.
Own container (kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
 - an organisation's quotation (positions on the title page, a part with positions, a shoot part with a crew function) makes
   its tasks in a new project; a second version (duplicate) carries origin_id on its positions and parts
 - export -> import into an empty organisation: every link (task_offer_links) is there for the new tasks, its key names the
   new positions / parts of the first version (i:<item> | s:<part>:<crew row>), root_id the new first version, doc_id a new
   version; origin_id of the second version's positions / parts points at the new first version's rows (never an old id)
 - the preview of the imported second version: every task linked, no row "new" or ticked; applying every key makes no task
   (one click does not double them)
 - a person without an organisation imports the same file into the private space (the personal office): the same
 - 2.671.0 (#5097): the shoot day of the quotation booked into the disposition (an open place, resource_kind slot) comes
   along; offer_root / offer_doc name the new first version, offer_pos the new part (d:<part>:<crew row>:<n>, the crew row
   as it was); the dispo of the imported second version finds it ("same", nothing ticked) and one click books nothing twice.
   A booking whose place key names a part that did not come along keeps its row with offer_* emptied (an own booking)
usage: p2654_d_offer_links_test.py <datadir>"""
import base64
import os
import time

import kt
from kt import B, check, sess, su_get
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time,dispo"  # 2.671.0 (#5097): + dispo
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def ok(r, what, codes=(200, 201, 202, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def upload(s, data, name="quelle.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid):
    """The import's state once it is no longer working (waits on the state, not on a time)."""
    box = {}

    def settled():
        box["j"] = s.get(B + f"/api/account/import/{iid}").json()
        return box["j"].get("state") not in ("checking", "running", "upload")
    kt.until(settled, timeout=240)
    return box.get("j") or {}


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid


def run(s, iid, target):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import into {target} done {j.get('state')} {j.get('error')}")
    return j


def export(s, oid):
    check(s.post(B + f"/api/orgs/{oid}/export").status_code == 202, f"organisation export {oid} started")
    kt.until(lambda: s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running", timeout=240)
    ox = su_get(s, B + f"/api/orgs/{oid}/export/file").content  # 2.360.0 (#2496): the step-up
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, f"organisation export {oid} + recovery key")
    return ox, rk


# ---------------------------------------------------------------- server, people, organisations
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = ok(A.post(B + "/api/admin/orgs", json={"name": "Quelle Studio", "admin_id": ALICE}), "source organisation")["id"]
ORG2 = ok(A.post(B + "/api/admin/orgs", json={"name": "Ziel Studio", "admin_id": ALICE}), "target organisation")["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ok(A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR", "industry_packs": ["film"]}), "office settings")
CAM = ok(A.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 650, "intext": "intern"}), "crew")["id"]

# ---------------------------------------------------------------- the quotation, its tasks, a second version
CL = ok(A.post(B + "/api/clients", json={**CLIENT, "org_id": ORG}), "client")["id"]
Q = ok(A.post(B + D, json={"kind": "offer", "lang": "de", "project_title": "Imagefilm", "client_id": CL, "service_from": "2027-03-01", "items": [
    {"kind": "service", "title": "Konzept", "detail": "Idee", "qty": 2, "unit": "day", "rate": 800},
    {"kind": "service", "title": "Schnitt", "qty": 6, "unit": "hour", "rate": 95}]}), "the quotation")["id"]
PG = ok(A.post(B + f"{D}/{Q}/parts", json={"title": "Grafik"}), "a part")["part"]["id"]
ok(A.put(B + f"{D}/{Q}/parts/{PG}/items", json={"items": [{"kind": "service", "title": "Animation", "qty": 1.5, "unit": "day", "rate": 700}]}),
   "the part's position")
PS = ok(A.post(B + f"{D}/{Q}/parts", json={"kind": "shoot", "title": "Dreh"}), "a shoot part")["part"]["id"]
ok(A.patch(B + f"{D}/{Q}/parts/{PS}", json={"sheet": {"head": {"shoot_days": 2, "travel_days": 0, "travel_share": 0, "prep_days": 0, "prep_share": 0, "sat_days": 0, "sat_pct": 0},
                                                       "staff": [{"role_id": CAM, "qty": 1, "prep": 0}]}}), "the sheet")
pv = ok(A.get(B + f"{D}/{Q}/tasks"), "the preview")
TITLES = {"Konzept", "Schnitt", "Animation", "Kamera"}
check({x["title"] for x in pv["rows"]} == TITLES and any(x["key"].startswith("s:") for x in pv["rows"]), f"the rows {[(x['title'], x['key']) for x in pv['rows']]}")
r = ok(A.post(B + f"{D}/{Q}/tasks", json={"pick": [x["key"] for x in pv["rows"]], "create": {"name": "Imagefilm Quelle"}}), "tasks made")
L = r.get("list_id")
check(r.get("created") == 4 and L, f"four tasks in a new project {r}")
# 2.671.0 (#5097): the shoot day into the disposition (one open camera place), and a booking with a place key of no part
dd = ok(A.get(B + f"{D}/{Q}/tasks"), "the dispo preview")["dispo"]
check(dd.get("on") and len(dd.get("days") or []) == 1 and dd["days"][0]["state"] == "new", f"one shoot day to book {dd}")
r = ok(A.post(B + f"{D}/{Q}/tasks", json={"pick": [], "dispo": {"pick": [dd["days"][0]["key"]]}}), "the shoot day booked")
check(r.get("dispo", {}).get("booked") == 1, f"one open place booked {r}")
SLOT = sql("SELECT offer_root, offer_doc, offer_pos FROM hub_bookings WHERE org_id=? AND resource_kind='slot' AND deleted_at IS NULL", (ORG,))
check(len(SLOT) == 1 and SLOT[0][0] == Q and SLOT[0][1] == Q and SLOT[0][2].startswith(f"d:{PS}:"), f"the booking names the quotation {SLOT}")
SLOT_POS = SLOT[0][2]
sql("INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,created_by,created_at,updated_at,"
    "offer_root,offer_doc,offer_pos,offer_mark,slot_name) SELECT org_id,'fremd0000000000a','Fremd',start,\"end\",'slot',0,'Fremd','option','',"
    "created_by,created_at,updated_at,offer_root,offer_doc,'d:987654321:zz:1','','Fremd' FROM hub_bookings WHERE org_id=? AND resource_kind='slot'", (ORG,))
Q2 = ok(A.post(B + f"{D}/{Q}/duplicate"), "a second version")["id"]
check(sql("SELECT COUNT(*) FROM office_doc_items WHERE doc_id=? AND origin_id IS NOT NULL", (Q2,))[0][0] >= 3
      and sql("SELECT COUNT(*) FROM office_doc_parts WHERE doc_id=? AND origin_id IS NOT NULL", (Q2,))[0][0] == 2, "the copy names its origins")
pv2 = ok(A.get(B + f"{D}/{Q2}/tasks"), "the second version's preview")
check(pv2["linked"] == 4 and all(x["state"] == "same" and not x["pick"] for x in pv2["rows"]), f"before the move: all linked {[(x['title'], x['state']) for x in pv2['rows']]}")
N_LINKS = sql("SELECT COUNT(*) FROM task_offer_links WHERE list_id=?", (L,))[0][0]
check(N_LINKS == 4, f"four links {N_LINKS}")

OX, RK = export(A, ORG)


def moved(s, who, lid, docs_where, docs_args):
    """The links, keys and origins after the import into a space; the preview and one click on the version there."""
    q1 = sql(f"SELECT id FROM office_docs WHERE kind='offer' AND version_of IS NULL AND {docs_where}", docs_args)
    q2 = sql(f"SELECT id FROM office_docs WHERE kind='offer' AND version_of IS NOT NULL AND {docs_where}", docs_args)
    check(len(q1) == 1 and len(q2) == 1, f"{who}: both versions came along {q1} {q2}")
    nq1, nq2 = q1[0][0], q2[0][0]
    check(sql("SELECT version_of FROM office_docs WHERE id=?", (nq2,))[0][0] == nq1, f"{who}: the chain stays")
    tasks = {t: tid for tid, t in sql("SELECT id, title FROM tasks WHERE list_id=? AND deleted_at IS NULL", (lid,))}
    check(set(tasks) == TITLES, f"{who}: the tasks came along {sorted(tasks)}")
    links = sql("SELECT task_id, list_id, doc_id, root_id, item_key, gone FROM task_offer_links WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)", (lid,))
    check(len(links) == N_LINKS and {x[0] for x in links} == set(tasks.values()), f"{who}: every task has its link {links}")
    items1 = {x[0] for x in sql("SELECT id FROM office_doc_items WHERE doc_id=?", (nq1,))}
    parts1 = {x[0] for x in sql("SELECT id FROM office_doc_parts WHERE doc_id=?", (nq1,))}
    bad = []
    for tid, l2, doc, root, key, gone in links:
        k = key.split(":")
        if l2 != lid or root != nq1 or doc not in (nq1, nq2) or gone:
            bad.append((tid, l2, doc, root, gone))
        elif not ((k[0] == "i" and int(k[1]) in items1) or (k[0] == "s" and int(k[1]) in parts1 and len(k) == 3)):
            bad.append((tid, key))
    check(not bad, f"{who}: list, quotation, root and key on the new ids {bad} items {items1} parts {parts1}")
    o_items = {x[0] for x in sql("SELECT origin_id FROM office_doc_items WHERE doc_id=? AND origin_id IS NOT NULL", (nq2,))}
    o_parts = {x[0] for x in sql("SELECT origin_id FROM office_doc_parts WHERE doc_id=? AND origin_id IS NOT NULL", (nq2,))}
    check(len(o_items) >= 3 and o_items <= items1 and o_parts == parts1, f"{who}: origin_id on the new first version {o_items} {o_parts} / {items1} {parts1}")
    check(not sql("SELECT 1 FROM office_doc_items WHERE doc_id=? AND origin_id IS NOT NULL", (nq1,)), f"{who}: the first version is its own origin")
    pv3 = ok(s.get(B + f"{D}/{nq2}/tasks"), f"{who}: the preview after the move")
    st = [(x["title"], x["state"], x["pick"]) for x in pv3["rows"]]
    check(pv3.get("list_id") == lid and pv3["linked"] == N_LINKS and all(x[1] == "same" and not x[2] for x in st), f"{who}: linked, nothing new or ticked {st}")
    r = ok(s.post(B + f"{D}/{nq2}/tasks", json={"pick": [x["key"] for x in pv3["rows"]]}), f"{who}: one click on every row")
    n = sql("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (lid,))[0][0]
    check(r.get("created") == 0 and n == len(TITLES), f"{who}: no task twice {r} {n}")
    # 2.671.0 (#5097): the bookings of the disposition
    sp = docs_args[0]
    bk = sql("SELECT title, offer_root, offer_doc, offer_pos, offer_mark FROM hub_bookings WHERE org_id=? AND resource_kind='slot' AND deleted_at IS NULL ORDER BY id", (sp,))
    slots = [b for b in bk if b[0] != "Fremd"]
    own = [b for b in bk if b[0] == "Fremd"]
    pos = SLOT_POS.split(":")
    check(len(slots) == 1 and slots[0][1] == nq1 and slots[0][2] == nq1 and slots[0][4] == ""
          and slots[0][3] == f"d:{min(parts1 & {x[0] for x in sql('SELECT id FROM office_doc_parts WHERE doc_id=? AND kind=?', (nq1, 'shoot'))})}:{pos[2]}:{pos[3]}",
          f"{who}: the open place came along on the new quotation and part {bk} / {SLOT_POS}")
    check(len(own) == 1 and own[0][1:] == (None, None, "", ""), f"{who}: a place key of no part: the booking stays, offer_* emptied {own}")
    dp = ok(s.get(B + f"{D}/{nq2}/tasks"), f"{who}: the dispo after the move")["dispo"]
    check(dp.get("on") and [(x["state"], x["pick"]) for x in dp["days"]] == [("same", False)], f"{who}: the dispo finds its booking {dp}")
    r = ok(s.post(B + f"{D}/{nq2}/tasks", json={"pick": [], "dispo": {"pick": [x["key"] for x in dp["days"]]}}), f"{who}: one click on every shoot day")
    n = sql("SELECT COUNT(*) FROM hub_bookings WHERE org_id=? AND resource_kind='slot' AND deleted_at IS NULL", (sp,))[0][0]
    check(r.get("dispo", {}).get("booked") == 0 and n == 2, f"{who}: no shoot day twice {r} {n}")


# ---------------------------------------------------------------- import into the empty organisation
run(A, opened(A, OX, RK), ORG2)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
L2 = sql("SELECT id FROM lists WHERE org_id=? AND name='Imagefilm Quelle' AND deleted_at IS NULL", (ORG2,))
check(L2, "the project came along")
moved(A, "organisation", L2[0][0], "org_id=?", (ORG2,))

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # 2.671.0 (#5097): with the disposition
run(Fr, opened(Fr, OX, RK), "private")
FL = sql("SELECT id FROM lists WHERE org_id IS NULL AND owner_id=? AND name='Imagefilm Quelle' AND deleted_at IS NULL", (FID,))
PB = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(FL and PB, f"frida: the project and her personal office {FL} {PB}")
moved(Fr, "frida", FL[0][0], "org_id=?", (PB[0][0],))

raise SystemExit(kt.done("p2654_d_offer_links"))
