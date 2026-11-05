#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.537.0 C API tests (#3433): tasks in the project from a quotation, with a time budget per position. Own container
(kt.fresh). Invented people, firms and figures only.
freelancer-matrix: office
 - GET /api/office/docs/<id>/tasks (preview): a position of the title page = a row without a section, a part = a section, a
   shoot part = one row per crew function with its days; text and heading lines are no rows; hours: hour = qty, minute =
   qty / 60, day = qty x the project's hours per day (8 by default, the list's own value when set), a part used twice
   counts twice, piece / flat rate: none; no price in a row
 - POST {pick, hours, create}: a quotation without a project gets a new agency project (the field "Budget h"), the
   ticked rows become tasks (title, description, section), the hours land in "Budget h", a value typed in the preview
   too (a flat rate); the office log says "tasks"; the quotation shows offer_tasks; the project's office answer has the budget
   (hours + the quotation's net); nothing ticked 400, an invoice 400
 - a new version (duplicate): unchanged rows "same", a changed position "changed" (new budget), one whose task budget was
   changed by hand "manual" (not ticked, kept), a new position "new", a removed one "gone" (only marked: the task stays,
   history "offer_gone"); the budget follows the new version's net
 - a project without "Budget h" (a plain list) gets the field
 - two versions of one chain applied at the same moment make every task once (review M1); a unit changed to a flat rate
   in a new version keeps the entered budget (review L1, "update never deletes")
 - rights: an office member who does not see the project 404, a viewer of the project 403, a person without office 403/404;
   a person without an organisation (the personal office, a private project): the same flow
usage: p3433_c_offer_tasks_test.py <datadir>"""
import base64
import os
import threading

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time"
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def rows_by_title(pv):
    return {x["title"]: x for x in pv.get("rows") or []}


def tasks_of(lid):
    """{title: (task id, section name, content, budget value)} of list lid."""
    out = {}
    for tid, title, sec, content in sql("SELECT t.id, t.title, s.name, t.content FROM tasks t LEFT JOIN sections s ON s.id=t.section_id "
                                        "WHERE t.list_id=? AND t.deleted_at IS NULL ORDER BY t.id", (lid,)):
        v = sql("SELECT v.value FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE v.task_id=? AND f.name='Budget h'", (tid,))
        out[title] = (tid, sec, content, float(v[0][0]) if v else None)
    return out


def scenario(S, who, shoot=False, member=None):
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")
    items = [{"kind": "service", "title": "Konzept", "detail": "Idee und Treatment", "qty": 2, "unit": "day", "rate": 800},
             {"kind": "text", "title": "Hinweis: Preise netto"},
             {"kind": "heading", "title": "Postproduktion"},
             {"kind": "service", "title": "Schnitt", "qty": 6, "unit": "hour", "rate": 95},
             {"kind": "service", "title": "Sprachaufnahme", "qty": 90, "unit": "minute", "rate": 2},
             {"kind": "service", "title": "Musiklizenz", "qty": 1, "unit": "flat", "rate": 400}]
    r = S.post(B + D, json={"kind": "offer", "lang": "de", "project_title": f"Imagefilm {who}", "client_id": cl, "items": items})
    check(r.status_code == 201, f"{who}: the quotation {r.text[:200]}")
    Q = r.json()["id"]
    r = S.post(B + f"{D}/{Q}/parts", json={"title": "Grafik"})
    check(r.status_code in (200, 201), f"{who}: a part {r.text[:200]}")
    PG = r.json()["part"]["id"]
    r = S.put(B + f"{D}/{Q}/parts/{PG}/items", json={"items": [{"kind": "service", "title": "Animation", "detail": "2D", "qty": 1.5, "unit": "day", "rate": 700},
                                                               {"kind": "service", "title": "Druckdaten", "qty": 2, "unit": "piece", "rate": 50}]})
    check(r.ok, f"{who}: the part's positions {r.text[:200]}")
    if shoot:
        r = S.post(B + f"{D}/{Q}/parts", json={"kind": "shoot", "title": "Dreh"})
        check(r.status_code in (200, 201), f"{who}: a shoot part {r.text[:200]}")
        PS = r.json()["part"]["id"]
        sheet = {"head": {"shoot_days": 2, "travel_days": 1, "travel_share": 0.5, "prep_days": 1, "prep_share": 1, "sat_days": 1, "sat_pct": 25},
                 "staff": [{"role_id": CAM, "qty": 1, "prep": 1}, {"role_id": LIG, "qty": 2, "prep": 0}]}
        check(S.patch(B + f"{D}/{Q}/parts/{PS}", json={"sheet": sheet}).ok, f"{who}: the sheet")
    # ------------------------------------------------------------ the preview
    check(S.post(B + f"{D}/{Q}/tasks", json={"pick": []}).status_code == 400, f"{who}: nothing ticked 400")
    r = S.get(B + f"{D}/{Q}/tasks")
    check(r.ok, f"{who}: the preview {r.text[:200]}")
    pv = r.json()
    rb = rows_by_title(pv)
    check(pv.get("list_id") is None and pv.get("linked") == 0 and pv.get("day_hours") == 8, f"{who}: no project yet, 8 h a day {pv.get('day_hours')}")
    want = {"Konzept": ("", 16.0), "Schnitt": ("", 6.0), "Sprachaufnahme": ("", 1.5), "Musiklizenz": ("", None), "Animation": ("Grafik", 12.0),
            "Druckdaten": ("Grafik", None)}
    if shoot:
        want.update({"Kamera": ("Dreh", 32.0), "Beleuchter": ("Dreh", 48.0)})  # 1 x (2 + 1 + 1 prep) days, 2 x (2 + 1) days; no shares / surcharges
    check({k: (x["section"], x["hours"]) for k, x in rb.items()} == want, f"{who}: rows, sections and hours {[(k, x['section'], x['hours']) for k, x in rb.items()]}")
    check("Hinweis: Preise netto" not in rb and "Postproduktion" not in rb, f"{who}: no text / heading rows")
    check(rb["Konzept"]["text"] == "Idee und Treatment" and all(x["state"] == "new" and x["pick"] for x in pv["rows"]), f"{who}: description, all new and ticked")
    check(not any(k in x for x in pv["rows"] for k in ("rate", "net", "total", "price")) and "800" not in str(pv["rows"]), f"{who}: no price in the rows")
    check(pv.get("net_text") and pv.get("total_h") == round(sum(v[1] or 0 for v in want.values()), 2), f"{who}: the sums {pv.get('total_h')} {pv.get('net_text')}")
    # ------------------------------------------------------------ apply: a new project
    pick = [x["key"] for x in pv["rows"] if x["title"] != "Druckdaten"]
    r = S.post(B + f"{D}/{Q}/tasks", json={"pick": pick, "hours": {rb["Musiklizenz"]["key"]: 3}, "create": {"name": f"Beispiel Kunde AG – Imagefilm {who}"}})
    check(r.status_code == 201 and r.json().get("made_project") is True and r.json().get("created") == len(pick), f"{who}: tasks created {r.text[:200]}")
    L = r.json().get("list_id")
    row = sql("SELECT ptype, client_id FROM lists WHERE id=?", (L,))
    check(row and row[0][0] == "agency" and row[0][1] == cl and r.json().get("field_made") is False, f"{who}: an agency project with the client, its own field {row}")
    doc = S.get(B + f"{D}/{Q}").json()
    check(doc.get("list_id") == L and doc.get("offer_tasks") == len(pick), f"{who}: the quotation is in the project, offer_tasks {doc.get('offer_tasks')}")
    ts = tasks_of(L)
    check(set(ts) == set(pick and [x["title"] for x in pv["rows"] if x["key"] in pick]), f"{who}: the ticked rows only {sorted(ts)}")
    check(ts["Konzept"][1] is None and ts["Konzept"][2] == "Idee und Treatment" and ts["Konzept"][3] == 16.0, f"{who}: Konzept {ts['Konzept']}")
    check(ts["Animation"][1] == "Grafik" and ts["Animation"][3] == 12.0 and ts["Musiklizenz"][3] == 3.0, f"{who}: section and hours, the typed flat rate {ts['Animation']} {ts['Musiklizenz']}")
    if shoot:
        check(ts["Kamera"][1] == "Dreh" and ts["Kamera"][3] == 32.0 and ts["Beleuchter"][3] == 48.0, f"{who}: one task per crew function {ts.get('Kamera')} {ts.get('Beleuchter')}")
    check(sql("SELECT 1 FROM activity WHERE task_id=? AND kind='created' AND data::text LIKE ?", (ts["Konzept"][0], '%offer%')), f"{who}: history 'created from a quotation'")
    log = S.get(B + f"{D}/{Q}/log").json()
    log = log.get("log", log) if isinstance(log, dict) else log
    check(any(x.get("action") == "tasks" for x in log or []), f"{who}: the office log says 'tasks'")
    j = S.get(B + f"/api/lists/{L}/office-docs").json()
    hours = sum(v[3] or 0 for v in ts.values())
    check(j.get("budget") and j["budget"]["doc_id"] == Q and j["budget"]["hours"] == hours and j["budget"]["net_text"] == pv["net_text"],
          f"{who}: the project's budget from the quotation {j.get('budget')} / {hours}")
    pv2 = S.get(B + f"{D}/{Q}/tasks").json()
    st = {x["title"]: x["state"] for x in pv2["rows"]}
    check(pv2["list_id"] == L and pv2["linked"] == len(pick) and st["Konzept"] == "same" and st["Druckdaten"] == "new", f"{who}: the preview again {st}")

    # ------------------------------------------------------------ a new version
    sql("UPDATE task_field_values SET value='10' WHERE task_id=? AND field_id=(SELECT id FROM list_fields WHERE list_id=? AND name='Budget h')",
        (ts["Schnitt"][0], L))  # Schnitt changed by hand
    r = S.post(B + f"{D}/{Q}/duplicate")
    check(r.status_code == 201 and r.json().get("version_of") == Q and r.json().get("list_id") == L, f"{who}: a new version {r.text[:200]}")
    Q2 = r.json()["id"]
    d2 = S.get(B + f"{D}/{Q2}").json()
    keep = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "ref_part_id")
    new_items = []
    for it in d2["items"]:
        x = {k: it.get(k) for k in keep}
        if x["title"] == "Konzept":
            x["qty"] = 3
        if x["title"] == "Schnitt":
            x["qty"] = 8
        if x["title"] == "Sprachaufnahme":
            continue  # removed
        new_items.append(x)
    new_items.append({"kind": "service", "title": "Farbkorrektur", "qty": 4, "unit": "hour", "rate": 120})
    r = S.put(B + f"{D}/{Q2}/items", json={"items": new_items, "parts_known": [p["id"] for p in d2.get("parts") or []]})
    check(r.ok, f"{who}: the new version's positions {r.text[:200]}")
    pv3 = S.get(B + f"{D}/{Q2}/tasks").json()
    st = {x["title"]: (x["state"], x["pick"], x["hours"]) for x in pv3["rows"]}
    check(pv3["linked"] == len(pick) and st["Konzept"] == ("changed", True, 24.0) and st["Schnitt"][:2] == ("manual", False) and st["Farbkorrektur"] == ("new", True, 4.0)
          and st["Animation"][0] == "same" and st["Musiklizenz"][0] == "same", f"{who}: the version's states {st}")
    gone = pv3.get("gone") or []
    check([g["title"] for g in gone] == ["Sprachaufnahme"] and gone[0]["pick"], f"{who}: the removed position {gone}")
    check(next(x for x in pv3["rows"] if x["title"] == "Schnitt").get("task_hours") == 10, f"{who}: the hand value shown")
    pick3 = [x["key"] for x in pv3["rows"] if x["pick"]] + [g["key"] for g in gone]
    r = S.post(B + f"{D}/{Q2}/tasks", json={"pick": pick3})
    # created: Farbkorrektur and Druckdaten (left unticked the first time, still new and ticked by default)
    check(r.ok and r.json().get("created") == 2 and r.json().get("updated") == 1 and r.json().get("marked") == 1 and r.json().get("made_project") is False,
          f"{who}: update applied {r.text[:200]}")
    ts2 = tasks_of(L)
    check(ts2["Konzept"][3] == 24.0 and ts2["Schnitt"][3] == 10.0 and ts2["Farbkorrektur"][3] == 4.0 and ts2["Konzept"][0] == ts["Konzept"][0],
          f"{who}: the new budget, the hand value kept, the new task {ts2.get('Konzept')} {ts2.get('Schnitt')} {ts2.get('Farbkorrektur')}")
    check("Sprachaufnahme" in ts2 and sql("SELECT gone FROM task_offer_links WHERE task_id=?", (ts["Sprachaufnahme"][0],)) == [(1,)]
          and sql("SELECT 1 FROM activity WHERE task_id=? AND kind='offer_gone'", (ts["Sprachaufnahme"][0],)), f"{who}: the removed position only marked")
    j = S.get(B + f"/api/lists/{L}/office-docs").json()
    check(j["budget"]["doc_id"] == Q2 and j["budget"]["net_text"] == pv3["net_text"], f"{who}: the budget follows the new version {j.get('budget')}")
    check(S.get(B + f"{D}/{Q2}").json().get("offer_tasks") == len(ts2) and S.get(B + f"{D}/{Q}").json().get("offer_tasks") == len(ts2), f"{who}: both versions count the tasks")
    pv4 = S.get(B + f"{D}/{Q2}/tasks").json()
    check(all(x["state"] in ("same", "manual") for x in pv4["rows"] if x["title"] != "Druckdaten") and pv4["gone"][0]["marked"] and not pv4["gone"][0]["pick"],
          f"{who}: nothing left to do {[(x['title'], x['state']) for x in pv4['rows']]}")

    # ------------------------------------------------------------ a plain list without "Budget h", the project's own hours per day
    r = S.post(B + "/api/lists", json={"name": f"Schlicht {who}", "org_id": ORG if member else None})
    LP = r.json()["id"]
    sql("UPDATE lists SET day_hours=6 WHERE id=?", (LP,))
    Q3 = S.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "items": [{"kind": "service", "title": "Moderation", "qty": 2, "unit": "day", "rate": 600}]}).json()["id"]
    check(S.post(B + f"{D}/{Q3}/project", json={"list_id": LP}).ok, f"{who}: the plain list as the project")
    pv5 = S.get(B + f"{D}/{Q3}/tasks").json()
    check(pv5["day_hours"] == 6 and pv5["rows"][0]["hours"] == 12.0 and pv5.get("field") is None, f"{who}: 6 h a day, no field yet {pv5.get('day_hours')} {pv5['rows']}")
    r = S.post(B + f"{D}/{Q3}/tasks", json={"pick": [pv5["rows"][0]["key"]]})
    check(r.status_code == 201 and r.json().get("field_made") is True and tasks_of(LP)["Moderation"][3] == 12.0, f"{who}: the field made, the budget in it {r.text[:200]}")
    # an invoice is no quotation
    inv = S.post(B + D, json={"kind": "invoice", "client_id": cl, "items": [{"title": "X", "qty": 1, "rate": 1}]}).json()["id"]
    check(S.get(B + f"{D}/{inv}/tasks").status_code == 400 and S.post(B + f"{D}/{inv}/tasks", json={"pick": ["i:1"]}).status_code == 400, f"{who}: an invoice 400")
    return Q, Q2, L


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
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
A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR", "industry_packs": ["film"]})
CAM = A.post(B + O + "/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 650, "intext": "intern"}).json()["id"]
LIG = A.post(B + O + "/crew", json={"name_de": "Beleuchter", "name_en": "Lighting", "rate_day": 350, "intext": "extern"}).json()["id"]

Q, Q2, L = scenario(A, "alice", shoot=True, member=Bo)

# ------------------------------------------------------------ rights
check(Bo.get(B + f"{D}/{Q2}/tasks").json().get("list_id") is None and Bo.get(B + f"{D}/{Q2}/tasks").json().get("list_known") is False,
      "Bob (office, not in the project): the preview does not name the project")
any_key = [x["key"] for x in A.get(B + f"{D}/{Q2}/tasks").json()["rows"]][:1]
check(Bo.post(B + f"{D}/{Q2}/tasks", json={"pick": any_key}).status_code == 404, "Bob does not see the project: 404")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "view"}).ok, "Bob a viewer of the project")
pvb = Bo.get(B + f"{D}/{Q2}/tasks").json()
check(pvb.get("list_id") == L and pvb.get("can") is False, f"Bob the viewer: preview, may not apply {pvb.get('can')}")
check(Bo.post(B + f"{D}/{Q2}/tasks", json={"pick": any_key}).status_code == 403, "Bob the viewer: 403")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "Bob an editor of the project")
check(Bo.get(B + f"{D}/{Q2}/tasks").json().get("can") is True, "Bob the editor may apply")
check(Ca.get(B + f"{D}/{Q2}/tasks").status_code in (403, 404) and Ca.post(B + f"{D}/{Q2}/tasks", json={"pick": any_key}).status_code in (403, 404),
      "Carol without the office: refused")

# ------------------------------------------------------------ 2.537.0 (#3433, review M1): two versions of one chain at once
def parallel(*calls):
    bar, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        bar.wait()
        out[i] = fn()
    ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


A2 = sess("alice")  # a second tab of its own
A2.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
cl_m = A.post(B + "/api/clients", json={**CLIENT, "name": "Parallel Kunde AG"}).json()["id"]
bad = []
for i in range(4):
    LM = A.post(B + "/api/lists", json={"name": f"Parallel {i}", "ptype": "agency", "org_id": ORG}).json()["id"]
    QM = A.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl_m, "items": [
        {"kind": "service", "title": f"Position {n}", "qty": n + 1, "unit": "hour", "rate": 90} for n in range(30)]}).json()["id"]
    check(A.post(B + f"{D}/{QM}/project", json={"list_id": LM}).ok, f"M1 round {i}: the project")
    QV = A.post(B + f"{D}/{QM}/duplicate").json()["id"]
    k1 = [x["key"] for x in A.get(B + f"{D}/{QM}/tasks").json()["rows"]]
    k2 = [x["key"] for x in A2.get(B + f"{D}/{QV}/tasks").json()["rows"]]
    r1, r2 = parallel(lambda: A.post(B + f"{D}/{QM}/tasks", json={"pick": k1}), lambda: A2.post(B + f"{D}/{QV}/tasks", json={"pick": k2}))
    n = sql("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (LM,))[0][0]
    if not (r1.ok and r2.ok and n == 30 and sorted([r1.json()["created"], r2.json()["created"]]) == [0, 30]):
        bad.append((i, r1.status_code, r2.status_code, n))
check(not bad, f"M1: version 1 and version 2 applied at the same moment make every task once (30), not twice: {bad}")

# ------------------------------------------------------------ 2.537.0 (#3433, review L1): a unit changed to a flat rate keeps the budget
LU = A.post(B + "/api/lists", json={"name": "Einheit", "ptype": "agency", "org_id": ORG}).json()["id"]
QU = A.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl_m, "items": [{"kind": "service", "title": "Konzept", "qty": 2, "unit": "day", "rate": 800}]}).json()["id"]
check(A.post(B + f"{D}/{QU}/project", json={"list_id": LU}).ok, "L1: the project")
ku = [x["key"] for x in A.get(B + f"{D}/{QU}/tasks").json()["rows"]]
check(A.post(B + f"{D}/{QU}/tasks", json={"pick": ku}).ok and tasks_of(LU)["Konzept"][3] == 16.0, "L1: 2 days = 16 h")
QU2 = A.post(B + f"{D}/{QU}/duplicate").json()["id"]
du = A.get(B + f"{D}/{QU2}").json()
items_u = [{**{k: it.get(k) for k in ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "ref_part_id")}, "qty": 1, "unit": "flat"} for it in du["items"]]
check(A.put(B + f"{D}/{QU2}/items", json={"items": items_u, "parts_known": [p["id"] for p in du.get("parts") or []]}).ok, "L1: the new version: a flat rate")
pu = A.get(B + f"{D}/{QU2}/tasks").json()["rows"]
check(pu and pu[0]["state"] == "changed" and pu[0]["hours"] is None, f"L1: the preview shows the change (no hours) {pu}")
r = A.post(B + f"{D}/{QU2}/tasks", json={"pick": [x["key"] for x in pu], "hours": {x["key"]: None for x in pu}})  # as the app sends an empty field
check(r.ok and tasks_of(LU)["Konzept"][3] == 16.0, f"L1: the entered budget stays (16 h), not deleted: {r.text[:160]} {tasks_of(LU).get('Konzept')}")
pu2 = A.get(B + f"{D}/{QU2}/tasks").json()["rows"]
check(pu2 and pu2[0]["state"] == "same", f"L1: afterwards nothing left to do {[(x['title'], x['state']) for x in pu2]}")

# ------------------------------------------------------------ a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "frida")
Fr.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR"})
FQ, FQ2, FL = scenario(Fr, "frida")
row = sql("SELECT org_id, owner_id FROM lists WHERE id=?", (FL,))
check(row and row[0][0] is None and row[0][1] == FID, f"frida: a private project of her own {row}")
check(A.get(B + f"{D}/{FQ}/tasks").status_code == 404 and A.post(B + f"{D}/{FQ}/tasks", json={"pick": ["i:1"]}).status_code == 404, "Alice: Frida's quotation 404")

raise SystemExit(kt.done("p3433_c_offer_tasks"))
