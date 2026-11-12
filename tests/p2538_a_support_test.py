#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.538.0 (#4365): a support session books nothing in the office, deletes nothing for good, hands out no upload token and puts
no contents into an organisation that has not granted support access itself. Own container (hosted, a server key). Invented
accounts only.
freelancer-matrix: own
tenant-matrix: support
 - a person without an organisation (frida): every booking way (finalise, unlock, credit note, payment, paid by status, cash book,
   bank, DATEV, period / logbook closing, bookkeeping imports, a series run, the move of the office), deleting for good (office
   trash, purge-done, time delete-all, trial delete-all, deleting a project) and GET httpshortcuts.zip: 403 code
   support_session; her own session is not stopped there; reading stays, editing a task stays
 - a member of an organisation (cara): a new project without org_id lands privately, with org_id of the organisation 403,
   a task into the organisation's project (POST / PATCH list_id) 403; her own session puts it there; once the organisation's
   admin grants support access for it, the support session may
 - 2.538.0 (#4365, review F4-F6): one trip / fixed cost deleted and the number range jump 403 (person without an organisation);
   an event, a contact, a notepad into the organisation's calendar / address book / project 403 without its grant, fine with it
 - 2.538.0 (#4365): the office of her workspace (org:CO): a draft 403 without the organisation's grant, 201 with it and in her
   own office; reminder fee, master data import, fixed costs / trips deleted 403; a reminder draft stays; /api/state and /api/me
   say support_session
usage: p2538_a_support_test.py <datadir>"""
import os
import sys

import kt
from kt import B, FAILS, OKS, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login, org_join  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
SAME = {"Sec-Fetch-Site": "same-origin"}

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"})
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
FID, _Fr = freelancer(B, A)
Fr = login(B, "frida")
assert Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok


def support(uid, own):
    """A support session of account uid: the person grants account access, the operator makes a sign-in link."""
    assert own.post(B + "/api/support-access", json={"hours": 1}).ok
    r = A.post(B + f"/api/users/{uid}/signin-link")
    assert r.ok, r.text
    s = kt.sess(None)
    r = s.post(B + "/api/auth/link", json={"token": r.json()["link"].split("#signin/")[1]})
    assert r.ok, r.text
    return s


def refused(r):
    return r.status_code == 403 and r.headers.get("content-type", "").startswith("application/json") and r.json().get("code") == "support_session"


def code(r):
    return r.json().get("code") if r.headers.get("content-type", "").startswith("application/json") else None


X = support(FID, Fr)
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='support'", (FID,)) == [(1,)], "frida: the operator's session is a support session")
r = X.post(B + "/api/lists", json={"name": "Help project"})
check(r.status_code in (200, 201), "support session: a new project " + r.text[:160])
LID = r.json()["id"]
r = X.post(B + "/api/tasks", json={"title": "Fixed by support", "list_id": LID})
check(r.status_code in (200, 201), "support session: a new task into the own project " + r.text[:160])
TID = r.json()["id"]
check(X.patch(B + f"/api/tasks/{TID}", json={"title": "Fixed by support, 2", "list_id": LID}).ok, "support session: edits a task (its own list_id)")
check(X.patch(B + f"/api/lists/{LID}", json={"archived": True}).ok, "support session: archives the project (undoable)")

# ---------------------------------------------------------------- booking, deleting for good, the upload token: a test per group
WAYS = (
    ("finalise", "post", "/api/office/docs/1/finalize", {}), ("unlock", "post", "/api/office/docs/1/unlock", {}),
    ("cancel: credit note", "post", "/api/office/docs/1/credit", {}), ("payment", "post", "/api/office/docs/1/payments", {"amount": "10"}),
    ("payment removed", "delete", "/api/office/docs/1/payments/1", None), ("paid by status", "post", "/api/office/docs/1/status", {"status": "paid"}),
    ("DATEV", "post", "/api/office/docs/1/datev", {}), ("DATEV import", "post", "/api/office/datev/import", {}),
    ("cash book", "post", "/api/office/cashbooks", {"name": "Till"}), ("cash entry", "post", "/api/office/cashbooks/1/entries", {}),
    ("cash entry cancelled", "post", "/api/office/cash-entries/1/cancel", {}), ("cash book closing", "post", "/api/office/cashbooks/1/closing", {}),
    ("bank import", "post", "/api/office/bank/import", {}), ("bank match", "post", "/api/office/bank/tx/1/match", {}),
    ("period lock", "post", "/api/office/periods/lock", {}), ("logbook closing", "post", "/api/office/logbook/close", {}),
    ("bookkeeping archive import", "post", "/api/office/books/archive/import", {}), ("old program import", "post", "/api/office/legacy/import", {}),
    ("series run", "post", "/api/office/series/1/run", {}), ("document final", "post", "/api/office/gen-docs/1/final", {}),
    ("meal receipt approved", "post", "/api/office/meals/1/approve", {}), ("card statement confirmed", "post", "/api/office/cards/statements/1/confirm", {}),
    ("office move", "post", "/api/office/move", {"name": "Ops", "confirm": True}), ("office move into an organisation", "post", "/api/office/move/org", {}),
    ("office trash for good", "delete", "/api/office/trash/1", None), ("trial delete-all", "post", "/api/office/trial/delete-all", {}),
    ("time delete-all", "post", f"/api/lists/{LID}/time/delete-all", {}), ("purge-done", "post", "/api/tasks/purge-done", {}),
    ("project deleted", "delete", f"/api/lists/{LID}", None),
    # 2.538.0 (#4365): the reminder fee changes a finalised reminder, the master data import the office's structure, the import
    # undos delete for good
    ("reminder fee", "post", "/api/office/docs/1/fee", {"state": "waived"}), ("master data import", "post", "/api/office/import", {}),
    ("fixed costs deleted", "post", "/api/office/fixed-costs/delete", {"ids": [999999]}),
    ("trips deleted", "post", "/api/office/trips/delete", {"ids": [999999]}),
    # 2.538.0 (#4365, review F4 / F6): one trip / fixed cost deleted has only the client's undo; the next running number is the
    # bookkeeping's structure
    ("one trip deleted", "delete", "/api/office/trips/999999", None), ("one fixed cost deleted", "delete", "/api/office/fixed-costs/999999", None),
    ("number range jump", "post", "/api/office/number-ranges/invoice", {"next": 500, "reason": "Support"}))
for what, meth, path, body in WAYS:
    r = getattr(X, meth)(B + path, **({"json": body} if body is not None else {}))
    check(refused(r), f"support session: {what} ({meth.upper()} {path}) -> 403 support_session, {r.status_code} {r.text[:100]}")
    if path.endswith("/time/delete-all") or path in ("/api/tasks/purge-done", f"/api/lists/{LID}", "/api/office/move", "/api/office/move/org"):
        continue  # her own session: these would really delete / move her office; the deletes are checked below on purpose
    r = getattr(Fr, meth)(B + path, **({"json": body} if body is not None else {}))
    check(code(r) != "support_session", f"frida's own session: {what} is not stopped as a support session, {r.status_code} {r.text[:100]}")
check(kt.dbx("SELECT COUNT(*) FROM lists WHERE id=?", (LID,)) == [(1,)] and kt.dbx("SELECT COUNT(*) FROM tasks WHERE id=?", (TID,)) == [(1,)],
      "the project and its task are still there")
r = X.post(B + "/api/office/docs/1/status", json={"status": "sent"})
check(not refused(r), f"support session: a status other than paid is no booking {r.status_code}")
r = X.post(B + "/api/office/docs/reminder", json={"doc_ids": [999999], "level": 1})
check(not refused(r) and r.status_code < 500, f"support session: a reminder draft is no booking {r.status_code} {r.text[:100]}")
r = X.post(B + "/api/office/docs", json={"project_title": "Support draft"})
check(r.status_code == 201, f"support session: a draft in her own office (person without an organisation) {r.status_code} {r.text[:100]}")
check(X.get(B + "/api/state").json()["me"].get("support_session") is True and X.get(B + "/api/me").json().get("support_session") is True,
      "support session: /api/state and /api/me say support_session (the app hides the HTTP Shortcuts download)")
check(Fr.get(B + "/api/state").json()["me"].get("support_session") is False and Fr.get(B + "/api/me").json().get("support_session") is False,
      "frida's own session: support_session false")
r = X.get(B + "/api/me/share/httpshortcuts.zip", headers=SAME)
check(refused(r), f"support session: GET httpshortcuts.zip (a new upload token) 403, {r.status_code}")
r = Fr.get(B + "/api/me/share/httpshortcuts.zip", headers=SAME)
check(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/zip"), f"frida's own session downloads it {r.status_code}")
for path in ("/api/office/docs", "/api/office/cashbooks", "/api/state"):
    r = X.get(B + path)
    check(not refused(r) and r.status_code < 500, f"support session: reading {path} stays, {r.status_code}")
r = Fr.post(B + "/api/tasks/purge-done", json={})
check(code(r) != "support_session" and r.status_code < 500, f"frida's own session: purge-done {r.status_code}")
r = Fr.delete(B + f"/api/lists/{LID}")
check(r.ok, f"frida's own session deletes the project {r.status_code}")

# ---------------------------------------------------------------- an organisation without support access of its own
# cara is a member of the operator's Alpha too (so the operator may make her link at all) and works in carl's Client Studio
ALPHA = A.get(B + "/api/orgs").json()["orgs"][0]["id"]
r = A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl", "password": "password123", "email": "carl@example.com"})
assert r.ok, r.text
CARL = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "cara", "display_name": "Cara", "password": "password123", "email": "cara@example.com",
                                   "orgs": [{"id": ALPHA, "role": "member"}]})
assert r.ok, r.text
CID = r.json()["id"]
Ca, Cc = login(B, "carl"), login(B, "cara")
for s in (Ca, Cc):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab,clients,office"}).ok
r = Ca.post(B + "/api/orgs", json={"name": "Client Studio"})
assert r.status_code == 201, r.text
CO = r.json()["id"]
# 2.635.0 (#5008): since 2.593.0 (#3570) an invitation by e-mail into a company of its own (orgs.self_made) reaches only a
# person its admin may see (else it is dropped): carl and cara are connected first, as colleagues who know each other
kt.dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-01-01T00:00:00Z')", tuple(sorted((CARL, CID))))
kt.proved()  # 2.1021.0 (#5775): an organisation admin invites by address only an account that proved it
assert Ca.put(B + f"/api/orgs/{CO}/members", json={"email": "cara@example.com"}).ok
assert org_join(B, "cara", CO)
assert Cc.patch(B + "/api/settings", json={"workspace": f"org:{CO}"}).ok  # her chosen workspace: the default of a new object
r = Cc.post(B + "/api/lists", json={"name": "Studio project", "org_id": CO})
check(r.status_code in (200, 201), "cara's own session: a project of the organisation " + r.text[:160])
OL = r.json()["id"]
Y = support(CID, Cc)
r = Y.post(B + "/api/lists", json={"name": "Help, default"})
check(r.status_code in (200, 201), "support session (member): a new project without org_id " + r.text[:160])
check(kt.dbx("SELECT org_id FROM lists WHERE id=?", (r.json()["id"],)) == [(None,)], "it lands privately, not in the organisation")
r = Y.post(B + "/api/lists", json={"name": "Help, org", "org_id": CO})
check(refused(r), f"support session: a new project with org_id of the organisation 403, {r.status_code} {r.text[:100]}")
r = Y.post(B + "/api/tasks", json={"title": "Into the studio", "list_id": OL})
check(refused(r), f"support session: POST a task into the organisation's project 403, {r.status_code}")
r = Y.post(B + "/api/lists", json={"name": "Help, mine"})
PL = r.json()["id"]
r = Y.post(B + "/api/tasks", json={"title": "Private", "list_id": PL})
PT = r.json()["id"]
r = Y.patch(B + f"/api/tasks/{PT}", json={"list_id": OL})
check(refused(r), f"support session: PATCH list_id onto the organisation's project 403, {r.status_code}")
check(kt.dbx("SELECT list_id FROM tasks WHERE id=?", (PT,)) == [(PL,)], "the task stayed where it was")
r = Cc.patch(B + f"/api/tasks/{PT}", json={"list_id": OL})
check(r.ok, f"cara's own session moves it there {r.status_code} {r.text[:100]}")
# 2.538.0 (#4365): the office takes its organisation from the workspace (org:CO): no write there without the organisation's grant
r = Cc.post(B + "/api/office/docs", json={"project_title": "Studio job"})
check(r.status_code == 201, f"cara's own session: a draft in the organisation's office {r.status_code} {r.text[:100]}")
r = Y.post(B + "/api/office/docs", json={"project_title": "Studio help"})
check(refused(r), f"support session: a draft in the organisation's office without its own support access 403, {r.status_code} {r.text[:100]}")
check(kt.dbx("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND project_title='Studio help'", (CO,)) == [(0,)], "no draft was made there")
r = Y.get(B + "/api/office/docs")
check(r.ok, f"support session: reading the organisation's office stays {r.status_code}")
# 2.538.0 (#4365, review F5): the organisation of a calendar, an address book, a project's notepad decides too
assert Cc.patch(B + "/api/settings", json={"features": "cal,events,contacts,comments,collab,clients,office"}).ok
r = Cc.post(B + "/api/evcals", json={"name": "Studio calendar", "org_id": CO})
assert r.status_code == 201, r.text
OCAL = r.json()["id"]
r = Cc.post(B + "/api/books", json={"name": "Studio contacts", "org_id": CO})
assert r.status_code == 201, r.text
OBK = r.json()["id"]
r = Y.post(B + "/api/evcals", json={"name": "Help calendar"})
check(r.status_code == 201, f"support session (member): a new calendar without org_id {r.status_code} {r.text[:100]}")
PCAL = r.json()["id"]
check(kt.dbx("SELECT org_id FROM ev_cals WHERE id=?", (PCAL,)) == [(None,)], "it lands privately")
r = Y.post(B + "/api/events", json={"title": "Help call", "cal_id": PCAL, "start": "2027-03-01T10:00"})
check(r.ok, f"support session: an event in her private calendar {r.status_code} {r.text[:100]}")
PEV = r.json()["id"]
F5 = (("an event in the organisation's calendar", "post", "/api/events", {"title": "Studio call", "cal_id": OCAL, "start": "2027-03-01T11:00"}),
      ("an event moved into the organisation's calendar", "patch", f"/api/events/{PEV}", {"cal_id": OCAL}),
      ("a contact in the organisation's address book", "post", "/api/contacts", {"book_id": OBK, "fn": "Studio Example"}),
      ("a notepad on the organisation's project", "post", f"/api/lists/{OL}/notepads", {"title": "Studio pad"}))
for what, meth, path, body in F5:
    r = getattr(Y, meth)(B + path, json=body)
    check(refused(r), f"support session: {what} without its own support access 403, {r.status_code} {r.text[:100]}")
check(kt.dbx("SELECT COUNT(*) FROM events WHERE cal_id=?", (OCAL,)) == [(0,)] and kt.dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (OBK,)) == [(0,)]
      and kt.dbx("SELECT COUNT(*) FROM list_notepads WHERE list_id=?", (OL,)) == [(0,)], "nothing went into the organisation")
r = Cc.post(B + "/api/events", json={"title": "Studio call", "cal_id": OCAL, "start": "2027-03-01T11:00"})
check(r.ok and code(r) != "support_session", f"cara's own session: an event in the organisation's calendar {r.status_code} {r.text[:100]}")
r = Cc.post(B + "/api/contacts", json={"book_id": OBK, "fn": "Studio Example"})
check(r.ok, f"cara's own session: a contact in the organisation's address book {r.status_code} {r.text[:100]}")
assert Ca.post(B + "/api/support-access", json={"hours": 1, "org_id": CO}).ok
for what, meth, path, body in F5:
    r = getattr(Y, meth)(B + path, json=body)
    check(r.ok, f"with the organisation's own support access: {what} {r.status_code} {r.text[:100]}")
r = Y.post(B + "/api/office/docs", json={"project_title": "Studio help"})
check(r.status_code == 201, f"with the organisation's own support access: a draft in its office {r.status_code} {r.text[:100]}")
r = Y.post(B + "/api/tasks", json={"title": "Into the studio", "list_id": OL})
check(r.status_code in (200, 201), f"with the organisation's own support access: a task into its project {r.status_code} {r.text[:100]}")
r = Y.post(B + "/api/lists", json={"name": "Help, org", "org_id": CO})
check(r.status_code in (200, 201), f"with the organisation's own support access: a project with its org_id {r.status_code} {r.text[:100]}")

assert Y.patch(B + "/api/settings", json={"workspace": "private"}).ok  # her own office (the personal office of the account)
r = Y.post(B + "/api/office/docs", json={"project_title": "Private help"})
check(r.status_code == 201, f"support session (member): a draft in her own office {r.status_code} {r.text[:100]}")

print(f"p2538_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
