#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1158.0 B API tests (#4566 B): the post-calculation of an accepted quotation as an invoice draft. Own container
(kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - GET /api/office/docs/<id>/postcalc (preview): a draft / sent quotation 409, a flat price quotation 409; accepted: every
   invoice position with planned and actual quantity -- a position in hours with a linked task (task_offer_links) carries
   the tracked hours of the task and its subtasks, rounded to a quarter hour; a day position with a task stays ("not by
   time", its tracked hours shown); a position without a task stays ("no task"); a part's position (form "full") counts
   like a title page position; the planned sum = the quotation's net, the actual sum = what the draft will hold
 - POST: 201 an invoice draft (not finalised, source = the quotation) with the actual hours; the same client_ref again =
   the same invoice; another one 409 invoice_exists unless force; the office log "create" with postcalc
 - only the quotation's project counts: a task moved to another project brings no hours any more
 - rights: an office member who does not see the project 403, an editor of the project (sees only own times) 403, an admin
   of the project 200; a person without the office refused; another workspace's quotation 404
 - the same for a person without an organisation (the personal office, a private project)
usage: p21158_b_nachkalk_test.py <datadir>"""
import base64
import os

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time"
OFC = "/api/office"
D = OFC + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def track(S, tid, minutes, who):
    r = S.post(B + "/api/time/entries", json={"task_id": tid, "start": "2026-11-10T09:00", "minutes": minutes})
    check(r.ok, f"{who}: a time entry {r.text[:160]}")


def scenario(S, who, org=None):
    """-> (quotation id, project id, {title: task id}) after the full flow of S."""
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    items = [{"kind": "service", "title": "Konzept", "qty": 2, "unit": "day", "rate": 800},
             {"kind": "service", "title": "Schnitt", "qty": 6, "unit": "hour", "rate": 95},
             {"kind": "service", "title": "Farbkorrektur", "qty": 4, "unit": "hour", "rate": 120},
             {"kind": "service", "title": "Tonmischung", "qty": 3, "unit": "hour", "rate": 80},
             {"kind": "service", "title": "Musiklizenz", "qty": 1, "unit": "flat", "rate": 400}]
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "project_title": f"Imagefilm {who}", "client_id": cl, "items": items})
    check(r.status_code == 201, f"{who}: the quotation {r.text[:200]}")
    Q = r.json()["id"]
    r = S.post(B + f"{D}/{Q}/parts", json={"title": "Grafik"})
    PG = r.json()["part"]["id"]
    check(S.put(B + f"{D}/{Q}/parts/{PG}/items", json={"items": [{"kind": "service", "title": "Animation", "qty": 5, "unit": "hour", "rate": 70}]}).ok,
          f"{who}: the part's position")
    L = S.post(B + "/api/lists", json={"name": f"Projekt {who}", "ptype": "agency", "time_tracking": True, "org_id": org}).json()["id"]
    check(S.post(B + f"{D}/{Q}/project", json={"list_id": L}).ok, f"{who}: the project")
    pv = S.get(B + f"{D}/{Q}/tasks").json()
    pick = [x["key"] for x in pv["rows"] if x["title"] != "Tonmischung"]  # Tonmischung gets no task
    r = S.post(B + f"{D}/{Q}/tasks", json={"pick": pick})
    check(r.status_code == 201, f"{who}: tasks from the quotation {r.text[:200]}")
    ts = {t: i for i, t in sql("SELECT id, title FROM tasks WHERE list_id=? AND deleted_at IS NULL", (L,))}
    check(set(ts) == {"Konzept", "Schnitt", "Farbkorrektur", "Musiklizenz", "Animation"}, f"{who}: the tasks {sorted(ts)}")
    # ------------------------------------------------------------ not accepted yet: 409
    check(S.get(B + f"{D}/{Q}/postcalc").status_code == 409 and S.post(B + f"{D}/{Q}/postcalc", json={}).status_code == 409,
          f"{who}: a draft quotation 409")
    check(S.post(B + f"{D}/{Q}/status", json={"status": "accepted"}).ok, f"{who}: accepted")
    # ------------------------------------------------------------ the times
    sub = S.post(B + "/api/tasks", json={"title": "Feinschnitt", "list_id": L, "parent_id": ts["Schnitt"]}).json()["id"]
    track(S, ts["Schnitt"], 450, who)  # 7.5 h
    track(S, sub, 40, who)  # + the subtask: 490 min = 8.17 h -> 8.25
    track(S, ts["Animation"], 130, who)  # 2.17 h -> 2.25
    track(S, ts["Konzept"], 600, who)  # a day position: not by time, 10 h shown
    # review F1: a time marked not billable counts nowhere
    r = S.post(B + "/api/time/entries", json={"task_id": ts["Schnitt"], "start": "2026-11-11T09:00", "minutes": 120, "billable": False})
    check(r.ok, f"{who}: a time not billable {r.text[:160]}")
    other = S.post(B + "/api/tasks", json={"title": "Fremd", "list_id": L}).json()["id"]
    track(S, other, 300, who)  # a task without a link counts nowhere
    # ------------------------------------------------------------ the preview
    r = S.get(B + f"{D}/{Q}/postcalc")
    check(r.ok, f"{who}: the preview {r.text[:200]}")
    pv = r.json()
    rb = {x["title"]: x for x in pv.get("rows") or []}
    got = {k: (x["state"], x["plan_qty"], x["actual_qty"]) for k, x in rb.items() if x["state"] != "none" or x["kind"] == "service" and x["unit"] == "hour"}
    want = {"Konzept": ("not_time", 2.0, 2.0), "Schnitt": ("time", 6.0, 8.25), "Farbkorrektur": ("time", 4.0, 0.0),
            "Tonmischung": ("none", 3.0, 3.0), "Musiklizenz": ("not_time", 1.0, 1.0), "Animation": ("time", 5.0, 2.25)}
    check(got == want, f"{who}: states and quantities {got}")
    check(rb["Konzept"]["actual_h"] == 10.0 and rb["Schnitt"]["actual_h"] == 8.17 and rb["Schnitt"]["diff_qty"] == 2.25
          and rb["Tonmischung"]["task_id"] is None and rb["Schnitt"]["task_id"] == ts["Schnitt"], f"{who}: the tracked hours, the diff {rb['Schnitt']} {rb['Konzept']}")
    doc = S.get(B + f"{D}/{Q}").json()
    s = pv["sums"]
    actual = s["plan_net"] + (8.25 - 6) * 95 + (0 - 4) * 120 + (2.25 - 5) * 70  # only the three positions by time change
    check(abs(s["plan_net"] - float(doc["totals"]["net"])) < 0.01 and abs(s["actual_net"] - actual) < 0.01 and abs(s["diff_net"] - (actual - s["plan_net"])) < 0.01,
          f"{who}: planned = the quotation's net {doc['totals']['net']}, actual {actual}: {s}")
    check(s["timed"] == 3 and s["linked"] == 5 and s["plan_net_text"] and s["actual_net_text"], f"{who}: the counters {s}")
    check(not sql("SELECT 1 FROM office_docs WHERE source_doc_id=?", (Q,)), f"{who}: the preview makes nothing")
    # ------------------------------------------------------------ the draft
    r = S.post(B + f"{D}/{Q}/postcalc", json={"client_ref": f"pc-{who}-1"})
    check(r.status_code == 201, f"{who}: the invoice draft {r.text[:200]}")
    inv = r.json()
    check(inv.get("kind") == "invoice" and inv.get("status") == "draft" and not inv.get("locked") and not inv.get("number"),
          f"{who}: a draft, not finalised {inv.get('kind')} {inv.get('status')} {inv.get('locked')} {inv.get('number')}")
    check(sql("SELECT source_doc_id FROM office_docs WHERE id=?", (inv["id"],)) == [(Q,)], f"{who}: from the quotation")
    q = {it["title"]: (it["qty"], it["unit"], it["rate"]) for it in inv.get("items") or [] if it.get("kind") == "service"}
    check(q.get("Schnitt") == (8.25, "hour", 95) and q.get("Animation") == (2.25, "hour", 70) and q.get("Farbkorrektur") == (0, "hour", 120)
          and q.get("Konzept") == (2, "day", 800) and q.get("Tonmischung") == (3, "hour", 80), f"{who}: the positions {q}")
    check(abs(float(inv["totals"]["net"]) - actual) < 0.01, f"{who}: the draft's net = the preview's actual {inv['totals'].get('net')}")
    check(S.post(B + f"{D}/{Q}/postcalc", json={"client_ref": f"pc-{who}-1"}).json().get("id") == inv["id"], f"{who}: sent again = the same draft")
    # review F1: the counted times are billed by the draft (never twice with "invoice from time"), the preview has none left
    bound = sql("SELECT COUNT(*), COUNT(billed_item_id) FROM time_entries WHERE billed_doc_id=?", (inv["id"],))
    check(bound == [(3, 3)], f"{who}: Schnitt, Feinschnitt and Animation bound to the draft with their position {bound}")
    rb = {x["title"]: x for x in S.get(B + f"{D}/{Q}/postcalc").json()["rows"]}
    check(rb["Schnitt"]["actual_qty"] == 0.0 and rb["Konzept"]["actual_h"] == 10.0, f"{who}: billed hours count no more {rb['Schnitt']}")
    r = S.post(B + f"{D}/{Q}/postcalc", json={"client_ref": f"pc-{who}-2"})
    check(r.status_code == 409 and r.json().get("code") == "invoice_exists", f"{who}: a second invoice asks first {r.status_code} {r.text[:160]}")
    r = S.post(B + f"{D}/{Q}/postcalc", json={"client_ref": f"pc-{who}-3", "force": True})
    check(r.status_code == 201 and r.json()["id"] != inv["id"], f"{who}: with force a second draft {r.status_code}")
    inv2 = r.json()["id"]
    check(not sql("SELECT 1 FROM time_entries WHERE billed_doc_id=?", (inv2,)), f"{who}: the second draft bills no time twice")
    log = S.get(B + f"{D}/{inv['id']}/log").json()
    log = log.get("log", log) if isinstance(log, dict) else log
    check(any(x.get("action") == "create" and (x.get("detail") or {}).get("postcalc") for x in log or []), f"{who}: the office log says create (postcalc)")
    # ------------------------------------------------------------ only the quotation's project: a moved task brings no hours
    L2 = S.post(B + "/api/lists", json={"name": f"Anderes {who}", "time_tracking": True, "org_id": org}).json()["id"]
    check(S.patch(B + f"/api/tasks/{ts['Animation']}", json={"list_id": L2}).ok, f"{who}: Animation moved to another project")
    rb = {x["title"]: x for x in S.get(B + f"{D}/{Q}/postcalc").json()["rows"]}
    check(rb["Animation"]["state"] == "none" and rb["Animation"]["actual_qty"] == 5.0, f"{who}: the moved task counts no more {rb['Animation']}")
    # ------------------------------------------------------------ a flat price quotation
    QF = S.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "flat_print": True,
                             "items": [{"kind": "service", "title": "Paket", "qty": 10, "unit": "hour", "rate": 90}]}).json()["id"]
    S.patch(B + f"{D}/{QF}", json={"flat_print": True})
    S.post(B + f"{D}/{QF}/status", json={"status": "accepted"})
    check(S.get(B + f"{D}/{QF}/postcalc").status_code == 409, f"{who}: a flat price quotation 409")
    # an invoice is no quotation
    check(S.get(B + f"{D}/{inv['id']}/postcalc").status_code == 409, f"{who}: an invoice 409")
    for x in (inv2, inv["id"]):  # review F1: deleting the drafts frees the times
        check(S.delete(B + f"{D}/{x}").status_code in (200, 204), f"{who}: draft {x} deleted")
    rb = {x["title"]: x for x in S.get(B + f"{D}/{Q}/postcalc").json()["rows"]}
    check(rb["Schnitt"]["actual_qty"] == 8.25, f"{who}: the times are open again {rb['Schnitt']}")
    return Q, L, ts


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Ca.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab", "tour": "done"})  # no office
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u in ("bob", "carol"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + OFC + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR"})

Q, L, TS = scenario(A, "alice", ORG)

# ------------------------------------------------------------ rights (the paths written out for tenant_coverage)
r = Bo.get(B + f"/api/office/docs/{Q}/postcalc")
check(r.status_code == 403, f"Bob (office, not in the project): 403 {r.status_code}")
check(Bo.post(B + f"/api/office/docs/{Q}/postcalc", json={"force": True}).status_code == 403, "Bob (office, not in the project): no draft 403")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "Bob an editor of the project")
check(Bo.get(B + f"/api/office/docs/{Q}/postcalc").status_code == 403, "Bob the editor sees only his own times: 403")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "admin"}).ok, "Bob an admin of the project")
r = Bo.get(B + f"/api/office/docs/{Q}/postcalc")
check(r.ok and {x["title"]: x["actual_qty"] for x in r.json()["rows"]}.get("Schnitt") == 8.25, f"Bob the project's admin: everyone's times {r.status_code}")
check(Ca.get(B + f"/api/office/docs/{Q}/postcalc").status_code in (403, 404) and Ca.post(B + f"/api/office/docs/{Q}/postcalc", json={}).status_code in (403, 404),
      "Carol without the office: refused")

# ------------------------------------------------------------ a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "frida")
Fr.put(B + OFC + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR"})
FQ, FL, _ = scenario(Fr, "frida")
row = sql("SELECT org_id, owner_id FROM lists WHERE id=?", (FL,))
check(row and row[0][0] is None and row[0][1] == FID, f"frida: a private project of her own {row}")
check(A.get(B + f"/api/office/docs/{FQ}/postcalc").status_code == 404 and A.post(B + f"/api/office/docs/{FQ}/postcalc", json={"force": True}).status_code == 404,
      "Alice: Frida's quotation 404")
check(Fr.get(B + f"/api/office/docs/{Q}/postcalc").status_code == 404 and Fr.post(B + f"/api/office/docs/{Q}/postcalc", json={"force": True}).status_code == 404,
      "Frida: the organisation's quotation 404")

raise SystemExit(kt.done("p21158_b_nachkalk"))
