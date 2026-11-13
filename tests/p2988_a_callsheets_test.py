#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.988.0 (#5651): the tab "Call sheets" of a project (hub/callsheet.py cs_list / cs_new). Invented people and names only.
 - GET /api/team/dispo/callsheets?list=<id>: without Film & Video nothing and no "new"; with it an empty list and can_add
 - POST {list_id, date}: the shoot day is made in the background (one open place of the disposition, pencilled in, the
   project's name, the project linked), the call sheet's row with the next shoot day number; the call sheet opens as before
   (GET /api/team/dispo/callsheet/<job>) and the disposition shows the shoot day; a bad date 400
 - the rows: date, shoot day no., location (after a save of the call sheet), oldest day first; a shoot day made in the
   disposition with a saved call sheet is in the list too, one without a saved call sheet is not (no call sheet yet)
 - Film & Video as the second industry of the area: the call sheet opens and lists (the first industry alone hid it)
 - review 2.988: the shoot day's title is "Shoot day" (F3), the next number is the highest + 1 (F4), an archived project / the
   inbox take none (F6)
 - undo of "new": the shoot day's bookings deleted -> the call sheet leaves the list; restored -> back
 - rights: another person 404 (list and new; an agent: hub/dispo.py _gate as every route of the disposition), the module Disposition off 403 / 409; an organisation: the
   admin adds, a read-only member sees the rows without can_add and POST 403
freelancer-matrix: hub (frida has no organisation: her own area, her own projects)
tenant-matrix: hub (greta, another person: frida's project 404 for the list and for a new call sheet)
usage: p2988_a_callsheets_test.py <datadir>"""
import kt
from kt import B, check
from freelancer_fixture import freelancer

A = kt.setup()
FID, Fr = freelancer(B, A, "frida")
GID, Gr = freelancer(B, A, "greta")
FEAT = "cal,collab,comments,kanban,fields,files,contacts,office,clients,dispo,workload"
for s in (Fr, Gr):
    check(s.patch(B + "/api/settings", json={"features": FEAT}).ok, "the modules incl. Disposition")
URL = B + "/api/team/dispo/callsheets"
L = Fr.post(B + "/api/lists", json={"name": "Werbefilm Garten", "kind": "project"}).json()["id"]

# ------------------------------------------------------------ without Film & Video: nothing to add
r = Fr.get(URL + f"?list={L}")
check(r.ok and r.json().get("callsheets") == [] and r.json().get("can_add") is False, f"no Film & Video: no rows, no new {r.text[:160]}")
check(Fr.post(URL, json={"list_id": L, "date": "2027-05-03"}).status_code == 404, "no Film & Video: no new call sheet")

# ------------------------------------------------------------ Film & Video as the SECOND industry (#5511: several at once)
r = Fr.put(B + "/api/industry", json={"industries": ["agency", "film"]})
check(r.ok, "frida: Agency & services + Film & Video " + r.text[:160])
r = Fr.get(URL + f"?list={L}")
check(r.ok and r.json() == {"callsheets": [], "can_add": True, "locked": False}, f"empty, can add {r.text[:160]}")

r = Fr.post(URL, json={"list_id": L, "date": "2027-05-04"})
check(r.status_code == 201, "a call sheet for 4 May " + r.text[:200])
c1 = r.json().get("callsheet") or {}
check(c1.get("date") == "2027-05-04" and c1.get("day_no") == "1" and c1.get("title") == "Shoot day" and c1.get("location") == "",
      f"its row: the day, shoot day 1, the title Shoot day (review F3: not the project's name), no location yet {c1}")
B1 = r.json().get("booking_id")
J1, ORG1 = c1.get("job"), c1.get("org_id")
bk = [tuple(x) for x in kt.dbx("SELECT resource_kind, resource_id, status, list_id, start, \"end\" FROM hub_bookings WHERE job=?", (J1,))]
check(bk == [("slot", 0, "option", L, "2027-05-04", "2027-05-04")], f"the shoot day in the background: one open place, pencilled in {bk}")
cs = Fr.get(B + f"/api/team/dispo/callsheet/{J1}?org={ORG1}")
check(cs.ok and cs.json()["callsheet"]["data"].get("day_no") == "1" and cs.json()["callsheet"]["updated_at"],
      f"the call sheet opens (Film & Video not the first industry) with its number {cs.text[:200]}")
dp = Fr.get(B + f"/api/team/dispo?start=2027-05-04&days=1&org={ORG1}").json()
check(any(x["job"] == J1 and x["kind"] == "slot" for x in dp.get("bookings", [])), "the disposition shows the shoot day (an open place)")
check(Fr.get(B + f"/api/team/dispo/callsheet/{J1}/pdf?org={ORG1}").headers.get("Content-Type", "").startswith("application/pdf"),
      "its PDF")

# a second, earlier day: number 2, the rows by date
r = Fr.post(URL, json={"list_id": L, "date": "2027-05-02"})
check(r.status_code == 201 and r.json()["callsheet"]["day_no"] == "2", "a second call sheet: shoot day 2 " + r.text[:160])
J2 = r.json()["callsheet"]["job"]
for bad in ("2027-02-30", "morgen", "", None):
    check(Fr.post(URL, json={"list_id": L, "date": bad}).status_code == 400, f"a bad date 400 ({bad!r})")

# the location after a save of the call sheet
cur = Fr.get(B + f"/api/team/dispo/callsheet/{J1}?org={ORG1}").json()["callsheet"]
r = Fr.put(B + f"/api/team/dispo/callsheet/{J1}?org={ORG1}", json={"data": {**cur["data"], "loc_name": "Gaertnerei Beispiel"},
                                                                   "expect_updated_at": cur["updated_at"]})
check(r.ok, "the location saved " + r.text[:160])
rows = Fr.get(URL + f"?list={L}").json()["callsheets"]
check([(x["date"], x["day_no"], x["location"]) for x in rows] == [("2027-05-02", "2", ""), ("2027-05-04", "1", "Gaertnerei Beispiel")],
      f"the rows, oldest day first, with the location {rows}")

# a shoot day made in the disposition: in the list once its call sheet is saved
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Dreh Nacht", "start": "2027-05-06T18:00", "end": "2027-05-06T23:00",
                                                  "status": "firm", "org": ORG1, "list_id": L, "resources": [{"kind": "user", "id": FID}]})
check(r.status_code == 201, "a shoot day in the disposition " + r.text[:160])
J3 = r.json()["bookings"][0]["job"]
check(J3 not in [x["job"] for x in Fr.get(URL + f"?list={L}").json()["callsheets"]], "no saved call sheet yet: not in the list")
check(Fr.put(B + f"/api/team/dispo/callsheet/{J3}?org={ORG1}", json={"data": {"day_no": "3", "set_name": "Hof"}}).ok, "its call sheet saved")
rows = Fr.get(URL + f"?list={L}").json()["callsheets"]
x3 = next((x for x in rows if x["job"] == J3), {})
check(x3.get("start") == "18:00" and x3.get("location") == "Hof" and x3.get("day_no") == "3", f"now in the list (the set's name as location) {x3}")

# undo of "new": the bookings of the shoot day deleted -> the call sheet leaves the list; restored -> back
r = Fr.delete(B + f"/api/team/dispo/bookings/{B1}?all=1")
check(r.ok, "undo: the shoot day deleted " + r.text[:120])
check(J1 not in [x["job"] for x in Fr.get(URL + f"?list={L}").json()["callsheets"]], "undo: the call sheet left the list")
check(Fr.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json()["ids"]}).ok, "redo: restored")
check(J1 in [x["job"] for x in Fr.get(URL + f"?list={L}").json()["callsheets"]], "redo: the call sheet is back")

# review F4: the next number is the highest + 1 (a deleted shoot day does not give its number twice; its call sheet in the trash counts)
B2 = kt.dbx("SELECT id FROM hub_bookings WHERE job=?", (J2,))[0][0]
check(Fr.delete(B + f"/api/team/dispo/bookings/{B2}?all=1").ok, "shoot day 2 deleted")
r = Fr.post(URL, json={"list_id": L, "date": "2027-05-08"})
check(r.status_code == 201 and r.json()["callsheet"]["day_no"] == "4", f"the next one: shoot day 4 (1, 3 and 2 in the trash) {r.text[:160]}")

# ------------------------------------------------------------ rights
check(Gr.get(B + f"/api/team/dispo/callsheets?list={L}").status_code == 404, "greta: frida's project 404")
check(Gr.post(B + "/api/team/dispo/callsheets", json={"list_id": L, "date": "2027-05-04"}).status_code == 404, "greta: no call sheet in frida's project")
check(len(kt.dbx("SELECT 1 FROM hub_bookings WHERE list_id=? AND created_by=?", (L, GID))) == 0, "nothing made by greta's try")
check(Fr.get(URL + "?list=x").status_code == 400 and Fr.get(URL + "?list=99999999").status_code == 404, "an unknown project")
check(Fr.patch(B + "/api/settings", json={"features": FEAT.replace(",dispo", "")}).ok, "frida switches Disposition off")
check(Fr.get(URL + f"?list={L}").status_code in (403, 409) and Fr.post(URL, json={"list_id": L, "date": "2027-05-04"}).status_code in (403, 409),
      "module off: refused")
check(Fr.patch(B + "/api/settings", json={"features": FEAT}).ok, "and on again")
# review F6: an archived project and the inbox take no new call sheet
LA = Fr.post(B + "/api/lists", json={"name": "Altes Projekt", "kind": "project"}).json()["id"]
check(Fr.patch(B + f"/api/lists/{LA}", json={"archived": 1}).ok, "a project archived")
check(Fr.get(URL + f"?list={LA}").json().get("can_add") is False and Fr.post(URL, json={"list_id": LA, "date": "2027-05-04"}).status_code == 403,
      "archived: no new call sheet (403)")
INBOX = kt.dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox", (FID,))
if INBOX:
    check(Fr.post(URL, json={"list_id": INBOX[0][0], "date": "2027-05-04"}).status_code == 404, "the inbox: 404")
check(len(kt.dbx("SELECT 1 FROM hub_bookings WHERE list_id=?", (LA,))) == 0, "nothing made in the archived project")

# ------------------------------------------------------------ an organisation: the admin adds, a read-only member only reads
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beispiel Studio", "admin_id": ALICE})
check(r.ok, "an organisation, alice its admin " + r.text[:160])
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "readonly"}], "username": "rita", "display_name": "Rita",
                                   "password": kt.PASSWORD, "email": "rita@example.com"})
check(r.ok, "rita, read-only " + r.text[:120])
RITA = r.json()["id"]
Ri = kt.sess("rita")
for s in (A, Ri):
    check(s.patch(B + "/api/settings", json={"features": FEAT, "workspace": f"org:{ORG}"}).ok, "modules + the organisation's workspace")
check(A.put(B + "/api/industry", json={"industries": ["film"]}).ok, "the organisation: Film & Video")
LO = A.post(B + "/api/lists", json={"name": "Kinospot Winter", "kind": "project", "org_id": ORG}).json()["id"]
# shared with rita as "edit": her read-only role in the organisation still decides (the area's write role, not the list's)
check(A.put(B + f"/api/lists/{LO}/members", json={"user_id": RITA, "role": "edit"}).ok, "the project shared with rita")
r = A.get(URL + f"?list={LO}")
check(r.ok and r.json()["can_add"] is True, f"the admin may add {r.text[:160]}")
r = A.post(URL, json={"list_id": LO, "date": "2027-06-01"})
check(r.status_code == 201 and r.json()["callsheet"]["org_id"] == ORG, "a call sheet in the organisation's area " + r.text[:160])
r = Ri.get(URL + f"?list={LO}")
check(r.ok and r.json()["can_add"] is False and [x["date"] for x in r.json()["callsheets"]] == ["2027-06-01"],
      f"rita (read-only) sees the row, no new {r.text[:200]}")
check(Ri.post(URL, json={"list_id": LO, "date": "2027-06-02"}).status_code == 403, "rita: no new call sheet (403)")
check(len(kt.dbx("SELECT 1 FROM hub_bookings WHERE list_id=?", (LO,))) == 1, "nothing made by her try")

raise SystemExit(kt.done("p2988_a_callsheets"))
