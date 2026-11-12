#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.985.0 (#5394): undo across devices, stage 6 rest -- settings, whole calendars and address books, the writes of CalDAV /
CardDAV / API v1 and budget entries record their steps in the core's step groups and go back from the list "Recent steps"
(POST /api/undo/to/<id>), also from another device (another sign-in) of the same person. Invented names only.
 - a setting changed on the laptop (PATCH /api/settings): the phone lists it (area self, its readable name, the device) and
   takes it back -> the old value; redo -> the new one; changed again since -> the part stays (named); a reset of the
   settings is one step ("Settings reset to the standard") -> back = the values before; PATCH /api/v1/me/notifications of a
   person's token records its step too; the label in German for a reader in German
 - a whole calendar into the trash (DELETE /api/evcals/<id>) -> listed with its name -> back: the calendar and its event are
   there again; redo -> in the trash again; a restore is a step as well (back = into the trash)
 - a whole address book into the trash -> back: the book and its contact; redo -> in the trash again
 - CalDAV: PUT of a changed event and DELETE record a step (device = the app password's name) -> back: old title / the event
   is there again; CardDAV: PUT of a changed card and DELETE -> back; API v1: PATCH of an event and a contact with a person's
   token -> back
 - budget: a changed entry -> back (old amount), redo; into the trash -> back; the copy holds the amount / title sealed (no
   plain text in obj_undo, none in the label: the entry's day instead); the lock per list space: the list moved into another
   space since -> refused with "the key of its space was changed", nothing written; the key of the list's space rotated after
   the step -> refused the same way; rotated before the step -> goes back
2.985.0 (#5394, review F1-F11, every one red without its fix):
 - F1 a CardDAV DELETE waits for the contact's lock WITHOUT holding the contact's row (the app's order: no deadlock)
 - F2 the history of a budget entry's undo holds none of its sealed fields; switching the encryption of a plain list on and
   resealing it (bud_settle) takes the entry's plain undo copies, their group and its history rows
 - F3 taking back the restore of a calendar with an invited external attendee books no mail on the day's counter
 - F4 taking back a reset brings the view state (Task panel layout) and the active saved arrangement back, and empties the
   app's own "undo the reset"
 - F5 a key without a readable name is labelled "Setting changed" (no raw key); a privacy choice is no step; an old part of
   one (planted) is refused by su_run, nothing written
 - F6 a CardDAV DELETE and the PUT that brings the card back within 10 minutes = one group "Several changes"; a device's
   change does not end the person's way forward (redo still works); the same setting twice from one device = one group
 - F7 a step whose category went into the trash since stays ("no longer there"); a plain copy of a list sealed since says
   "The list was encrypted"; F8 a booking that collides at the write (unique index, here a test trigger) = the part stays
   (409 "already booked"), no error 500
 - F10 the app's restore of an address book waits for the book's lock (obj-address_book-<id>); F11 PATCH
   /api/v1/me/notifications waits for the settings lock (usettings-<id>)
 - N4 a reset's step brings the quiet hours back; the app's own "undo the reset" is a step of the same keys; N5 (CardDAV row
   read again with its book and name) runs in the F1 check; N6 redo compares against the value as cleaned on the way back
2.985.0 (#5394, second Fable review, each red without its fix):
 - F2 a save that seals the entry with another space's key (encryption on, bud_settle not there yet) takes its plain copies,
   labels and history; F7 a toobig group's plain label goes with them; F8 a group counts a part relative to its row
 - F3 assistant_on, digest_mail, mail_assign, mail_mention, ical_scope are no step; F6 a device's change after an app step is a
   new group; F9 a card deleted for good while its PUT from the trash waited becomes a new card (no 500)
freelancer-matrix: undo (a person without an organisation: her setting and her budget entry go back from the list)
usage: p2930_a_undo_rest_test.py <datadir>"""
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
# review F3: mail sending on (an SMTP sink inside the container, tests/stub_mail.py) so invitations count on the day's counter
if not kt.nostart("P2824B"):
    kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_ORGCRYPT_PAUSE": "0", "KALMIDO_SMTP_HOST": "127.0.0.1",
                  "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none", "KALMIDO_MAIL_FROM": "kalmido@example.test"}, prefix="P2824B")
    shutil.copy(os.path.join(N, "stub_mail.py"), kt.DATA)
    subprocess.run(["docker", "exec", "-d", kt.CT, "python", "/data/stub_mail.py"])
kt.docker_logs_on_first_fail()
DBC, DBN = open(os.path.join(kt.DATA, ".kalmido-db")).read().split()
FEAT = "cal,events,contacts,collab,comments,budget"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
LAP = {"X-Kalmido-Device": "Laptop (Test)"}
PHONE = kt.sess("alice", headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in of alice = another device
FID, Fr = freelancer(B, A, features=FEAT)
D = (date.today() + timedelta(days=3)).isoformat()
DAVH = {"X-Forwarded-Proto": "https"}


def one(q, args=()):
    r = kt.dbx(q, args)
    return r[0][0] if r else None


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def back(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def redo(s, gid):
    r = s.post(B + f"/api/undo/{gid}/redo")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def setting(uid, k):
    return one("SELECT value FROM user_settings WHERE user_id=? AND key=?", (uid, k))


def lock_rows(name):
    """[granted, ...] of the advisory locks on name (write_lock: pg_advisory_xact_lock(hashtext(name)))."""
    return [bool(x[0]) for x in kt.dbx("SELECT granted FROM pg_locks WHERE locktype='advisory' AND objsubid=1 "
                                       "AND objid::text::bigint = (hashtext(?)::bigint & 4294967295)", (name,))]


class Holder:
    """Another connection holding the write_lock name (an open transaction in psql) until release()."""
    def __init__(self, name):
        self.p = subprocess.Popen(["docker", "exec", "-i", DBC, "psql", "-U", "kalmido", "-d", DBN, "-X", "-q"], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        self.p.stdin.write(f"BEGIN;\nSELECT pg_advisory_xact_lock(hashtext('{name}'));\n")
        self.p.stdin.flush()
        self.ok = bool(kt.until(lambda: True in lock_rows(name), 20))

    def release(self):
        self.p.stdin.write("COMMIT;\n\\q\n")
        self.p.stdin.close()
        self.p.wait(30)


def waits(name, call, during=None):
    """call() (one request) while another connection holds the lock name: -> (it waited for that lock, what during() saw
    meanwhile, the response after the release)."""
    h = Holder(name)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=call()))
    t.start()
    blocked = bool(kt.until(lambda: False in lock_rows(name) or not t.is_alive(), 20)) and t.is_alive()
    mid = during() if during else None
    h.release()
    t.join(60)
    return h.ok and blocked, mid, out.get("r")


# ================================================================ settings
# 2.997.0 (#5702 #5607 #5615): the first look of the account (the app uploads the device's own appearance by itself,
# dialogs.js lookAdopt) is no step of the person - as one it was the newest group right after sign-in and an entry with its
# own way back took it over (its undo took back the look); a change of the look afterwards is a step as before
check(not (setting(ALICE, "look") or ""), f"(setup) the account has no look yet {setting(ALICE, 'look')}")
n0 = newest(A).get("id")
r = A.patch(B + "/api/settings", json={"look": json.dumps({"theme": "light"})})
check(r.ok and "light" in (setting(ALICE, "look") or "") and newest(A).get("id") == n0, f"the first look is stored, no step {r.status_code} {newest(A)}")
r = A.patch(B + "/api/settings", json={"look": json.dumps({"theme": "dark"})})
g = newest(A)
check(r.ok and g.get("id") != n0 and g.get("kind") == "setting" and "Colour scheme" in (g.get("label") or ""), f"a later change of the look is a step {g}")
# 2.997.0 (#5625): the roadmap's view state (zoom, collapsed projects) is no step either (SU_QUIET, like the column widths)
r = A.patch(B + "/api/settings", json={"roadmap": json.dumps({"z": "week"})})
check(r.ok and "week" in (setting(ALICE, "roadmap") or "") and newest(A).get("id") == g.get("id"), f"the roadmap's zoom is stored, no step {r.status_code} {newest(A)}")
r = A.patch(B + "/api/settings", json={"fav_only": "1"}, headers=LAP)
check(r.ok and setting(ALICE, "fav_only") == "1", f"(setup) the laptop shows only the favourites {r.status_code}")
g = newest(PHONE)
check(g.get("area") == "self" and g.get("label") == "Setting changed: Only favourites in the sidebar" and g.get("device") == "Laptop (Test)"
      and g.get("kind") == "setting" and g.get("ref_id") == ALICE and g.get("undo"),
      f"the phone lists the laptop's setting: area, readable name, device {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and not res.get("stayed") and setting(ALICE, "fav_only") in (None, "0"),
      f"taken back from the phone: the sidebar shows every list again {res} {setting(ALICE, 'fav_only')}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and setting(ALICE, "fav_only") == "1", f"redo: only the favourites again {res}")
A.patch(B + "/api/settings", json={"prio_bg": "soft"})
GP = newest(A)["id"]
A.patch(B + "/api/settings", json={"prio_bg": "strong"}, headers={"X-Kalmido-Device": "Tablet (Test)"})
GN = newest(A)["id"]
check(GN != GP and setting(ALICE, "prio_bg") == "strong", "(setup) two steps of the priority colour")
kt.dbx("UPDATE user_settings SET value='soft' WHERE user_id=? AND key='prio_bg'", (ALICE,))  # changed elsewhere (no step of its own)
res = back(PHONE, GN)
st = res.get("stayed") or []
check(not res.get("undone") and [x["kind"] for x in st] == ["setting"] and st[0]["code"] == "conflict"
      and "Changed again" in st[0]["reason"] and setting(ALICE, "prio_bg") == "soft",
      f"changed again since: the part stays, named, nothing written {res}")
kt.dbx("UPDATE user_settings SET value='strong' WHERE user_id=? AND key='prio_bg'", (ALICE,))
res = back(PHONE, GP)
check(GN in (res.get("undone") or []) and GP in (res.get("undone") or []) and setting(ALICE, "prio_bg") in (None, ""),
      f"back up to the first of both: no priority colour again {res}")
# the reset of the settings: one step of every key it put back
A.patch(B + "/api/settings", json={"cal_tasks": "0", "fav_only": "1"})
r = A.post(B + "/api/settings/reset", json={})
check(r.ok and setting(ALICE, "cal_tasks") == "1" and setting(ALICE, "fav_only") == "0", f"(setup) the settings reset {r.status_code} {r.text[:160]}")
g = newest(PHONE)
check(g.get("label") == "Settings reset to the standard" and g.get("area") == "self" and g.get("parts", 0) >= 2,
      f"the reset is one listed step with a part per key {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and setting(ALICE, "cal_tasks") == "0" and setting(ALICE, "fav_only") == "1",
      f"taken back from the phone: the values before the reset {res}")
# API v1 with a person's token: the notifications
r = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write", "calendar", "contacts"]})
check(r.status_code == 201 and r.json().get("token"), f"(setup) alice's personal token {r.status_code} {r.text[:120]}")
TOKH = {"Authorization": "Bearer " + (r.json().get("token") or "")}
n0 = setting(ALICE, "notify")
r = requests.patch(B + "/api/v1/me/notifications", json={"events": {"comment": {"push": False}}}, headers=TOKH)
g = newest(PHONE)
check(r.ok and setting(ALICE, "notify") != n0 and g.get("kind") == "setting" and g.get("area") == "self" and g.get("label"),
      f"PATCH /api/v1/me/notifications records the person's step {r.status_code} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and setting(ALICE, "notify") == n0, f"... and goes back from the list {res}")

# ---------------------------------------------------------------- review F11 + F4-F6 (settings)
ok, _, r = waits(f"usettings-{ALICE}", lambda: requests.patch(B + "/api/v1/me/notifications", json={"events": {"comment": {"push": True}}},
                                                              headers=TOKH))
check(ok and r is not None and r.ok, f"F11: PATCH /api/v1/me/notifications waits for the settings lock ({ok} {r is not None and r.status_code})")
# F5: a key without a readable name is never labelled with its raw name
dc = "0" if setting(ALICE, "date_confirm") == "1" else "1"
A.patch(B + "/api/settings", json={"date_confirm": dc})
g = newest(PHONE)
check(g.get("kind") == "setting" and g.get("label") == "Setting changed", f"F5: no raw key in the label, \"Setting changed\" {g}")
GDC = g["id"]
# F5: a privacy choice is no step; an old part of one (planted into the step above) is refused, nothing written
A.patch(B + "/api/settings", json={"push_title_only": "1" if setting(ALICE, "push_title_only") != "1" else "0"})
check(newest(PHONE).get("id") == GDC, f"F5: a privacy choice (push_title_only) records no step {newest(PHONE)}")
pt = setting(ALICE, "push_title_only")
kt.dbx("UPDATE obj_undo SET snap=? WHERE group_id=?", (json.dumps({"k": "push_title_only", "b": "0" if pt == "1" else "1", "a": pt}), GDC))
res = back(PHONE, GDC)
check(not res.get("undone") and [x.get("code") for x in res.get("stayed") or []] == ["noaccess"] and setting(ALICE, "push_title_only") == pt,
      f"F5: su_run refuses a privacy key, nothing written {res} {setting(ALICE, 'push_title_only')}")
# 2.985.0 (#5394, review F3): consent to the assistant, contents leaving by mail and the calendar feed's scope are no step
# either ("Back to here" must never switch them back silently); trial_mode is in SU_PRIVATE too (needs an office, not set here)
for k, a, b in (("assistant_on", "1", "0"), ("digest_mail", "1", "0"), ("mail_assign", "always", "off"), ("mail_mention", "always", "off"),
                ("ical_scope", "mine", "all")):
    g0 = newest(PHONE).get("id")
    r = A.patch(B + "/api/settings", json={k: b if setting(ALICE, k) == a else a})
    check(r.ok and newest(PHONE).get("id") == g0, f"F3: {k} records no step {r.status_code} {r.text[:120]} {newest(PHONE)}")
# F6: the same setting twice from the same device within 10 minutes = one step; back = the value before both
pb0 = setting(ALICE, "prio_bg")
A.patch(B + "/api/settings", json={"prio_bg": "soft"}, headers=LAP)
G1 = newest(PHONE)["id"]
A.patch(B + "/api/settings", json={"prio_bg": "strong"}, headers=LAP)
g = newest(PHONE)
check(g.get("id") == G1 and g.get("parts") == 2 and setting(ALICE, "prio_bg") == "strong", f"F6: the same key again from the laptop joins its step {g}")
res = back(PHONE, G1)
check(res.get("undone") == [G1] and setting(ALICE, "prio_bg") == pb0, f"F6: ... and goes back to the value before both {res} {setting(ALICE, 'prio_bg')}")
# F4: the reset takes back the view state (Task panel layout) and the active saved arrangement too
LAYOUT = json.dumps({"order": ["tasks", "brief"], "hidden": ["inbox"], "opts": {"tasks": {"lw": 4}}})


def lyv_active_v(sid):
    return one("SELECT active FROM view_layouts WHERE id=?", (sid,)) in (1, True)


r = A.post(B + "/api/layouts/saved", json={"key": "view_today", "name": "Fokus Beispiel", "layout": LAYOUT, "activate": True})
SV = r.json()["saved"]["id"] if r.ok else None
A.patch(B + "/api/settings", json={"detail_split": "40"})
VT0 = setting(ALICE, "view_today") or ""
check(r.ok and VT0 and lyv_active_v(SV) and setting(ALICE, "detail_split") == "40", f"(setup) an active arrangement, the panel at 40 {r.status_code} {r.text[:160]}")


def lyv_active(sid=None):
    return lyv_active_v(sid or SV)


r = A.post(B + "/api/settings/reset", json={})
g = newest(PHONE)
check(r.ok and g.get("label") == "Settings reset to the standard" and setting(ALICE, "detail_split") != "40" and not lyv_active()
      and (setting(ALICE, "reset_undo") or "") != "", f"(setup) the reset ended the arrangement, the panel is standard {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and setting(ALICE, "detail_split") == "40", f"F4: back: the Task panel layout (view state) too {res} {setting(ALICE, 'detail_split')}")
check(lyv_active() and json.loads(setting(ALICE, "view_today") or "{}") == json.loads(VT0), f"F4: back: the saved arrangement is active again {lyv_active()}")
check((setting(ALICE, "reset_undo") or "") == "", f"F4: back from the list empties the app's own \"undo the reset\" {setting(ALICE, 'reset_undo')}")
# review N4: the reset puts the quiet hours back too (private, so no step of their own): its step brings them back, and the
# app's own "undo the reset" is a step of the same keys
A.patch(B + "/api/settings", json={"quiet_from": "21:30"})
r = A.post(B + "/api/settings/reset", json={})
g = newest(PHONE)
check(r.ok and setting(ALICE, "quiet_from") != "21:30", f"(setup) the reset put the quiet hours back {setting(ALICE, 'quiet_from')}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and setting(ALICE, "quiet_from") == "21:30", f"N4: back from the list: the quiet hours too {res} {setting(ALICE, 'quiet_from')}")
A.post(B + "/api/settings/reset", json={})
qf = setting(ALICE, "quiet_from")
r = A.post(B + "/api/settings/reset", json={"undo": True})
g = newest(PHONE)
check(r.ok and setting(ALICE, "quiet_from") == "21:30" and one("SELECT COUNT(*) FROM obj_undo WHERE group_id=? AND snap LIKE ?", (g["id"], '%"quiet_from"%')) == 1,
      f"N4: the app's own \"undo the reset\" is a step with the quiet hours {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and setting(ALICE, "quiet_from") == qf, f"N4: ... taken back: the reset's values again {res} {setting(ALICE, 'quiet_from')}")
A.patch(B + "/api/settings", json={"features": FEAT})  # (the reset's standard switched modules off: on again for the checks below)
# review N6: a value cleaned on the way back (a flag stored as "true" is written as "1") is what the way forward compares
kt.dbx("UPDATE user_settings SET value='true' WHERE user_id=? AND key='fav_only'", (ALICE,))
A.patch(B + "/api/settings", json={"fav_only": "0"})
GN6 = newest(PHONE)["id"]
res = back(PHONE, GN6)
check(res.get("undone") == [GN6] and setting(ALICE, "fav_only") == "1", f"(setup) back: the flag as cleaned {res} {setting(ALICE, 'fav_only')}")
res = redo(PHONE, GN6)
check(res.get("redone") == 1 and setting(ALICE, "fav_only") == "0", f"N6: redo compares against the cleaned value {res} {setting(ALICE, 'fav_only')}")

# ================================================================ a whole calendar
r = A.post(B + "/api/evcals", json={"name": "Drehplan Beispiel"})
check(r.status_code in (200, 201), f"(setup) a calendar {r.status_code} {r.text[:120]}")
CAL = r.json()["id"]
r = A.post(B + "/api/events", json={"title": "Motivsuche", "start": f"{D}T10:00", "end": f"{D}T11:00", "cal_id": CAL})
check(r.status_code in (200, 201), f"(setup) its event {r.status_code} {r.text[:120]}")
EV = r.json()["id"]


def cal_ids(s=A):
    return [x["id"] for x in s.get(B + "/api/evcals").json().get("items", [])]


r = A.delete(B + f"/api/evcals/{CAL}", headers=LAP)
check(r.ok and CAL not in cal_ids() and A.get(B + f"/api/events/{EV}").status_code == 404, f"the calendar went into the trash with its event {r.status_code}")
g = newest(PHONE)
check(g.get("label") == "Moved to the trash: Drehplan Beispiel" and g.get("area") == "calendar" and g.get("kind") == "evcal"
      and g.get("device") == "Laptop (Test)", f"the phone lists the whole calendar's step with its name {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and CAL in cal_ids() and A.get(B + f"/api/events/{EV}").ok,
      f"taken back from the phone: the calendar and its event are there again {res}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and CAL not in cal_ids() and A.get(B + f"/api/events/{EV}").status_code == 404, f"redo: in the trash again {res}")
r = A.post(B + f"/api/evcals/{CAL}/restore")
g = newest(A)
check(r.ok and CAL in cal_ids() and g.get("label") == "Restored from the trash: Drehplan Beispiel", f"the restore is a step too {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and CAL not in cal_ids(), f"its undo puts the calendar into the trash again {res}")
res = redo(A, g["id"])
check(res.get("redone") == 1 and CAL in cal_ids() and A.get(B + f"/api/events/{EV}").ok, f"... redo: out of the trash with its event {res}")

# review F3: taking back the restore of a calendar whose event invited an external attendee books no mail
kt.dbx("UPDATE users SET email='alice@example.com' WHERE id=? AND (email IS NULL OR email='')", (ALICE,))
C3 = A.post(B + "/api/evcals", json={"name": "Einladungen Beispiel"}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": C3, "title": "Abnahme Beispiel", "start": f"{D}T14:00", "end": f"{D}T15:00", "send_invites": True,
                                    "attendees": [{"email": "gast@example.com", "name": "Gast Beispiel"}]})
E3 = r.json().get("id") if r.status_code == 201 else None
invited = one("SELECT COUNT(*) FROM event_attendees WHERE event_id=? AND invited_seq IS NOT NULL", (E3,)) if E3 else 0


def mails_today():
    return one("SELECT COALESCE(SUM(n), 0) FROM ev_invite_day WHERE user_id=?", (ALICE,)) or 0


check(r.status_code == 201 and invited == 1 and mails_today() >= 1, f"(setup) an event with an invited external attendee {r.status_code} {invited} {mails_today()}")
A.delete(B + f"/api/evcals/{C3}")
r = A.post(B + f"/api/evcals/{C3}/restore")
g = newest(A)
check(r.ok and C3 in cal_ids() and g.get("kind") == "evcal", f"(setup) the calendar deleted and restored, a step {g}")
n0 = mails_today()
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and C3 not in cal_ids() and mails_today() == n0,
      f"F3: back = into the trash again, no cancellation mail counted ({n0} -> {mails_today()}) {res}")

# ================================================================ a whole address book
BK = A.post(B + "/api/books", json={"name": "Kunden Beispiel", "org_id": None}).json()["id"]
CT = A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Erika Beispiel", "given": "Erika", "family": "Beispiel"}).json()["id"]


def book_live(bid=BK):
    return one("SELECT deleted_at FROM books WHERE id=?", (bid,)) is None


r = A.delete(B + f"/api/books/{BK}", headers=LAP)
check(r.ok and not book_live() and A.get(B + f"/api/contacts/{CT}").status_code == 404, f"the address book went into the trash {r.status_code}")
g = newest(PHONE)
check(g.get("label") == "Moved to the trash: Kunden Beispiel" and g.get("kind") == "address_book", f"listed with its name {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and book_live() and A.get(B + f"/api/contacts/{CT}").ok
      and BK in [x["id"] for x in A.get(B + "/api/books").json().get("items", [])], f"taken back: the book and its contact are back {res}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and not book_live(), f"redo: in the trash again {res}")
ok, mid, r = waits(f"obj-address_book-{BK}", lambda: A.post(B + f"/api/books/{BK}/restore"), lambda: book_live())
check(ok and mid is False and r is not None and r.ok and book_live(),
      f"F10: the app's restore of the book waits for the book's lock, then goes through ({ok} {mid} {r is not None and r.status_code})")

# ================================================================ CalDAV / CardDAV
PW = A.post(B + "/api/me/app-passwords", json={"name": "Handy Kalender"}).json()["password"]


def dav(m, path, body=None, **h):
    hd = {**DAVH, **{k.replace("_", "-"): v for k, v in h.items()}}
    return requests.request(m, B + path, auth=("alice", PW), data=body.encode() if isinstance(body, str) else body, headers=hd)


def vevent(uid, title):
    d = D.replace("-", "")
    return (f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Example//EN\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:{d}T080000Z\r\n"
            f"DTSTART:{d}T090000Z\r\nDTEND:{d}T100000Z\r\nSUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


r = dav("PUT", f"/dav/calendars/alice/e{CAL}/p2824b.ics", vevent("p2824b-1", "Probe Beispiel"), Content_Type="text/calendar")
check(r.status_code == 201, f"(setup) a device creates an event {r.status_code} {r.text[:160]}")
DE = one("SELECT id FROM events WHERE cal_id=? AND href='p2824b.ics'", (CAL,))
r = dav("PUT", f"/dav/calendars/alice/e{CAL}/p2824b.ics", vevent("p2824b-1", "Probe verschoben"), Content_Type="text/calendar")
g = newest(PHONE)
check(r.status_code == 204 and g.get("kind") == "event" and g.get("ref_id") == DE and "Probe Beispiel" in (g.get("label") or "")
      and g.get("device") == "Handy Kalender", f"CalDAV PUT: the step, named by the app password's device {r.status_code} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/events/{DE}").json().get("title") == "Probe Beispiel", f"taken back: the old title {res}")
r = dav("DELETE", f"/dav/calendars/alice/e{CAL}/p2824b.ics")
g = newest(A)
check(r.status_code == 204 and A.get(B + f"/api/events/{DE}").status_code == 404 and g.get("label") == "Deleted: Probe Beispiel",
      f"CalDAV DELETE: a step {r.status_code} {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/events/{DE}").ok, f"taken back: the event is there again {res}")


def vcard(uid, fn):
    return f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{fn}\r\nN:{fn};;;;\r\nEND:VCARD\r\n"


r = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b.vcf", vcard("p2824b-c", "Max Beispiel"), Content_Type="text/vcard")
check(r.status_code == 201, f"(setup) a device creates a contact {r.status_code} {r.text[:160]}")
DC = one("SELECT id FROM contacts WHERE book_id=? AND href='p2824b.vcf'", (BK,))
r = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b.vcf", vcard("p2824b-c", "Max Muster"), Content_Type="text/vcard")
g = newest(PHONE)
check(r.status_code == 204 and g.get("kind") == "contact" and g.get("ref_id") == DC and "Max Beispiel" in (g.get("label") or ""),
      f"CardDAV PUT: the step {r.status_code} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/contacts/{DC}").json().get("fn") == "Max Beispiel", f"taken back: the old name {res}")
# review F1: the DELETE waits for the contact's lock (the one of the app's saves and of the undo) BEFORE it locks the row,
# so the app / an undo holding that lock and wanting the row never meets a DELETE holding the row and wanting the lock


def row_free(cid):
    return one("SELECT COUNT(*) FROM (SELECT id FROM contacts WHERE id=? FOR UPDATE SKIP LOCKED) x", (cid,)) == 1


ok, mid, r = waits(f"contact-{DC}", lambda: dav("DELETE", f"/dav/addressbooks/alice/b{BK}/p2824b.vcf"), lambda: row_free(DC))
check(ok and mid is True, f"F1: the CardDAV DELETE waits for the contact's lock without holding its row ({ok} {mid})")
g = newest(A)
check(r is not None and r.status_code == 204 and A.get(B + f"/api/contacts/{DC}").status_code == 404 and g.get("label") == "Deleted: Max Beispiel",
      f"CardDAV DELETE: a step {r is not None and r.status_code} {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/contacts/{DC}").ok, f"taken back: the contact is back {res}")
r = dav("DELETE", f"/dav/addressbooks/alice/b{BK}/p2824b.vcf")
GD = newest(A)["id"]
r = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b.vcf", vcard("p2824b-c", "Max Beispiel"), Content_Type="text/vcard")
g = newest(A)
# review F6: a bundle holds one step per object -- the same card again within the 10 minutes is a group of its own
check(r.status_code == 201 and A.get(B + f"/api/contacts/{DC}").ok and g.get("id") != GD and g.get("label") == "Restored: Max Beispiel",
      f"CardDAV PUT of a card in the trash: out of the trash is a step (the same card again: a group of its own) {r.status_code} {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/contacts/{DC}").status_code == 404, f"taken back: in the trash again {res}")
# review F6: a device's changes of two cards within 10 minutes are one group of its app password ("Several changes")
for nm, fn in (("p2824b2.vcf", "Lena Beispiel"), ("p2824b3.vcf", "Jan Beispiel")):
    dav("PUT", f"/dav/addressbooks/alice/b{BK}/{nm}", vcard(nm[:-4], fn), Content_Type="text/vcard")
C2, C3B = (one("SELECT id FROM contacts WHERE book_id=? AND href=?", (BK, x)) for x in ("p2824b2.vcf", "p2824b3.vcf"))
r1 = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b2.vcf", vcard("p2824b2", "Lena Muster"), Content_Type="text/vcard")
G2 = newest(A)["id"]
r2 = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b3.vcf", vcard("p2824b3", "Jan Muster"), Content_Type="text/vcard")
g = newest(A)
check(r1.status_code == 204 and r2.status_code == 204 and g.get("id") == G2 and g.get("parts") == 2 and g.get("label") == "Several changes",
      f"F6: the device's changes of two cards are one group {r1.status_code} {r2.status_code} {g}")
res = back(A, G2)
check(res.get("undone") == [G2] and A.get(B + f"/api/contacts/{C2}").json().get("fn") == "Lena Beispiel"
      and A.get(B + f"/api/contacts/{C3B}").json().get("fn") == "Jan Beispiel", f"F6: taken back: both old names {res}")
# review F6: a device's change does not end the person's way forward (an undone step of the app can still be redone)
r = A.patch(B + f"/api/events/{EV}", json={"title": "Motivsuche Sued"})
GU = newest(A)["id"]
res = back(A, GU)
check(r.ok and res.get("undone") == [GU] and A.get(B + f"/api/events/{EV}").json().get("title") == "Motivsuche", f"(setup) an undone step of the app {res}")
r = dav("PUT", f"/dav/calendars/alice/e{CAL}/p2824b.ics", vevent("p2824b-1", "Probe am Abend"), Content_Type="text/calendar")
res = redo(A, GU)
check(r.status_code == 204 and res.get("redone") == 1 and A.get(B + f"/api/events/{EV}").json().get("title") == "Motivsuche Sued",
      f"F6: after the device's change the app's step can still be redone {r.status_code} {res}")
A.patch(B + f"/api/events/{EV}", json={"title": "Motivsuche"})  # (as before, for the API v1 checks)
# 2.985.0 (#5394, review F6): a device's change joins its bundle only while that is the person's newest group - after an
# app step in between it opens a new one (else "Back to here" met the older group first and said "changed by someone else")
dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b2.vcf", vcard("p2824b2", "Lena Nord"), Content_Type="text/vcard")
GA = newest(A)["id"]
A.patch(B + f"/api/events/{EV}", json={"title": "Motivsuche West"})
GB = newest(A)["id"]
r = dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b3.vcf", vcard("p2824b3", "Jan Nord"), Content_Type="text/vcard")
g = newest(A)
check(r.status_code == 204 and GB != GA and g.get("id") not in (GA, GB) and g.get("kind") == "contact",
      f"F6: after an app step the device's next change is a new, newest group {r.status_code} {GA} {GB} {g}")
A.patch(B + f"/api/events/{EV}", json={"title": "Motivsuche"})
# 2.985.0 (#5394, review F9): a card PUT back from the trash reads the row again under the contact's lock - deleted for good
# meanwhile, it becomes a new card (before: contact_store on a missing row, error 500)
dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b9.vcf", vcard("p2824b9", "Ole Beispiel"), Content_Type="text/vcard")
C9 = one("SELECT id FROM contacts WHERE book_id=? AND href='p2824b9.vcf'", (BK,))
r = dav("DELETE", f"/dav/addressbooks/alice/b{BK}/p2824b9.vcf")
check(C9 and r.status_code == 204 and one("SELECT deleted_at FROM contacts WHERE id=?", (C9,)) is not None, f"(setup) a card in the trash {r.status_code}")
ok, _, r = waits(f"contact-{C9}", lambda: dav("PUT", f"/dav/addressbooks/alice/b{BK}/p2824b9.vcf", vcard("p2824b9", "Ole Beispiel"),
                                              Content_Type="text/vcard"),
                 lambda: kt.dbx("DELETE FROM contacts WHERE id=?", (C9,)))
n9 = one("SELECT id FROM contacts WHERE book_id=? AND href='p2824b9.vcf' AND deleted_at IS NULL", (BK,))
check(ok and r is not None and r.status_code == 201 and n9 and n9 != C9,
      f"F9: deleted for good while the PUT waited: a new card, no error ({ok} {r is not None and r.status_code} {n9})")

# ---------------------------------------------------------------- API v1 (a person's token)
r = requests.patch(B + f"/api/v1/events/{EV}", json={"title": "Motivsuche Nord"}, headers=TOKH)
g = newest(PHONE)
check(r.ok and g.get("kind") == "event" and g.get("ref_id") == EV, f"API v1 PATCH of an event: the step {r.status_code} {r.text[:120]} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/events/{EV}").json().get("title") == "Motivsuche", f"taken back: the old title {res}")
r = requests.patch(B + f"/api/v1/contacts/{CT}", json={"fn": "Erika Muster"}, headers=TOKH)
g = newest(PHONE)
check(r.ok and g.get("kind") == "contact" and g.get("ref_id") == CT, f"API v1 PATCH of a contact: the step {r.status_code} {r.text[:120]} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and A.get(B + f"/api/contacts/{CT}").json().get("fn") == "Erika Beispiel", f"taken back: the old name {res}")

# ================================================================ budget entries (sealed with the key of the list's space)
L = A.post(B + "/api/budget/lists", json={}).json()["list_id"]
r = A.post(B + f"/api/budget/{L}/entries", json={"day": D, "amount": "12,50", "kind": "out", "title": "Baeckerei Beispiel"})
check(r.status_code == 201, f"(setup) a budget entry {r.status_code} {r.text[:160]}")
BE = r.json()["id"]
check(one("SELECT sid FROM budget_entries WHERE id=?", (BE,)) == -ALICE, "(setup) the entry is sealed with alice's own key (sid = her space)")


def entry(s=A, eid=BE):
    r = s.get(B + f"/api/budget/entries/{eid}")
    return r.json() if r.ok else {"status": r.status_code}


r = A.patch(B + f"/api/budget/entries/{BE}", json={"amount": "20"}, headers=LAP)
g = newest(PHONE)
check(r.ok and entry()["amount"] == 20 and g.get("area") == "budget" and g.get("kind") == "budget_entry"
      and g.get("label") == f"Changed: Budget entry of {D}" and "Baeckerei" not in (g.get("label") or ""),
      f"the phone lists the entry's step, its day in the label, never the sealed title {g}")
snap = one("SELECT snap FROM obj_undo WHERE group_id=?", (g["id"],)) or ""
check("kenc1:" in snap and "Baeckerei" not in snap and "12.50" not in snap, "the copy holds the values sealed, nothing in plain text")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and entry()["amount"] == 12.5 and entry()["title"] == "Baeckerei Beispiel",
      f"taken back from the phone: the old amount, still readable {res} {entry()}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and entry()["amount"] == 20, f"redo: the new amount {res}")
hist = kt.dbx("SELECT CAST(vals_before AS TEXT), CAST(vals_after AS TEXT) FROM obj_history WHERE kind='budget_entry' AND ref_id=?", (BE,))
check(not [h for h in hist if any(f'"{k}"' in (x or "") for x in h for k in ("amount", "title", "note", "counterpart"))],
      f"F2: the history of the undo / redo holds none of the sealed fields {hist}")
r = A.delete(B + f"/api/budget/entries/{BE}")
g = newest(A)
check(r.ok and entry().get("status") == 404 and g.get("label") == f"Deleted: Budget entry of {D}", f"into the trash: a step {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and entry().get("amount") == 20, f"taken back: the entry is there again {res}")
# the lock per list space: the list moved into another space since the step
A.patch(B + f"/api/budget/entries/{BE}", json={"amount": "30"})
GS = newest(A)["id"]
kt.dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, L))  # as a move into the organisation before its rows are resealed
res = back(A, GS)
st = res.get("stayed") or []
check([x["kind"] for x in st] == ["budget_entry"] and "key of its space" in (st[0].get("reason") or "")
      and one("SELECT amount FROM budget_entries WHERE id=?", (BE,)).startswith("kenc1:") and entry()["amount"] == 30,
      f"the list's space changed since: refused with a clear answer, nothing written {res}")
# the key of the list's space (the organisation's now) rotated after the step
A.patch(B + f"/api/budget/entries/{BE}", json={"amount": "40"})
check(one("SELECT sid FROM budget_entries WHERE id=?", (BE,)) == ORG, "(setup) a save seals the entry with the organisation's key now")
A.patch(B + f"/api/budget/entries/{BE}", json={"amount": "50"})
GR = newest(A)["id"]
rot0 = one("SELECT rotated_at FROM org_keys WHERE org_id=?", (ORG,))
kt.dbx("UPDATE org_keys SET rotated_at=to_char(now() + interval '1 hour', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00') WHERE org_id=?", (ORG,))
res = back(A, GR)
st = res.get("stayed") or []
check([x["kind"] for x in st] == ["budget_entry"] and "key of its space" in (st[0].get("reason") or "") and entry()["amount"] == 50,
      f"rotated after the step: refused, the copy is never written back {res}")
kt.dbx("UPDATE org_keys SET rotated_at='2026-01-01T00:00:00+00:00' WHERE org_id=?", (ORG,))
res = back(A, GR)
check(GR in (res.get("undone") or []) and entry()["amount"] == 40, f"rotated before the step: it goes back as usual {res}")
kt.dbx("UPDATE org_keys SET rotated_at=? WHERE org_id=?", (rot0, ORG))

# ---------------------------------------------------------------- review F7 / F8 (a second list of alice, her own space)
L2 = A.post(B + "/api/budget/lists", json={}).json()["list_id"]
K1 = A.post(B + f"/api/budget/{L2}/cats", json={"name": "Lebensmittel", "kind": "out"}).json()["id"]
K2 = A.post(B + f"/api/budget/{L2}/cats", json={"name": "Haushalt", "kind": "out"}).json()["id"]
E7 = A.post(B + f"/api/budget/{L2}/entries", json={"day": D, "amount": "9", "kind": "out", "title": "Markt", "cat_id": K1}).json()["id"]
r = A.patch(B + f"/api/budget/entries/{E7}", json={"cat_id": K2})
G7 = newest(A)["id"]
r2 = A.delete(B + f"/api/budget/cats/{K1}")
check(r.ok and r2.ok and one("SELECT deleted_at FROM budget_cats WHERE id=?", (K1,)) is not None, f"(setup) another category, the old one in the trash {r2.status_code}")
# 2.1013.0 (#5513): the category's trash is a step of its own now: back to the entry's step takes it back first (the category is
# there again), then the entry's (its old category)
GK = newest(A)["id"]
res = back(A, G7)
check(res.get("undone") == [GK, G7] and one("SELECT deleted_at FROM budget_cats WHERE id=?", (K1,)) is None
      and one("SELECT cat_id FROM budget_entries WHERE id=?", (E7,)) == K1, f"#5513: back over the category's trash step, then the entry's {res}")
# F7 as before: the category went into the trash without a step of the person (another way: written directly here)
r = A.patch(B + f"/api/budget/entries/{E7}", json={"cat_id": K2})
G7 = newest(A)["id"]
kt.dbx("UPDATE budget_cats SET deleted_at='2026-11-01T10:00:00+00:00', deleted_by=? WHERE id=?", (ALICE, K1))
check(r.ok and one("SELECT deleted_at FROM budget_cats WHERE id=?", (K1,)) is not None, "(setup) the old category in the trash again (no step)")
res = back(A, G7)
st = res.get("stayed") or []
check(not res.get("undone") and [x["kind"] for x in st] == ["budget_entry"] and "no longer there" in (st[0].get("reason") or "")
      and one("SELECT cat_id FROM budget_entries WHERE id=?", (E7,)) == K2, f"F7: the copy's category is in the trash: the part stays, nothing written {res}")
# F8: the month of a booked template written back collides at the write (a test trigger raises the unique index's error)
M0, D8 = D[:7], (date.today() + timedelta(days=40)).isoformat()
R8 = A.post(B + f"/api/budget/{L2}/recurring", json={"title": "Miete Beispiel", "amount": 500, "kind": "out", "per": "month", "start": M0}).json()["id"]
r = A.post(B + f"/api/budget/recurring/{R8}/book", json={"month": M0, "day": D})
E8 = r.json().get("id") if r.status_code == 201 else None
r = A.patch(B + f"/api/budget/entries/{E8}", json={"day": D8})
G8 = newest(A)["id"]
check(r.ok and one("SELECT rmonth FROM budget_entries WHERE id=?", (E8,)) == D8[:7], f"(setup) a booked template moved into another month {r.status_code} {r.text[:120]}")
kt.dbx("CREATE OR REPLACE FUNCTION p2824b_boom() RETURNS trigger AS $$ BEGIN IF NEW.rmonth IS DISTINCT FROM OLD.rmonth THEN "
       "RAISE unique_violation USING MESSAGE = 'p2824b test'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql")
kt.dbx(f"CREATE TRIGGER p2824b_boom BEFORE UPDATE ON budget_entries FOR EACH ROW WHEN (NEW.id = {int(E8)}) EXECUTE FUNCTION p2824b_boom()")
rr = PHONE.post(B + f"/api/undo/to/{G8}")
kt.dbx("DROP TRIGGER IF EXISTS p2824b_boom ON budget_entries")
kt.dbx("DROP FUNCTION IF EXISTS p2824b_boom()")
res = rr.json() if rr.ok else {}
st = res.get("stayed") or []
check(rr.status_code == 200 and [x["kind"] for x in st] == ["budget_entry"] and "already booked" in (st[0].get("reason") or "")
      and one("SELECT day FROM budget_entries WHERE id=?", (E8,)) == D8, f"F8: the collision = the part stays (409), no error {rr.status_code} {rr.text[:200]}")

# ================================================================ a person without an organisation (freelancer-matrix: undo)
r = Fr.patch(B + "/api/settings", json={"fav_only": "1"})
g = newest(Fr)
check(r.ok and g.get("kind") == "setting", f"frida's setting is a step {g}")
res = back(Fr, g["id"])
check(res.get("undone") == [g["id"]] and setting(FID, "fav_only") in (None, "0"), f"... and goes back {res}")
FL = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
FE = Fr.post(B + f"/api/budget/{FL}/entries", json={"day": D, "amount": "5", "kind": "out", "title": "Kaffee"}).json()["id"]
r = Fr.patch(B + f"/api/budget/entries/{FE}", json={"amount": "7"})
g = newest(Fr)
res = back(Fr, g["id"])
check(r.ok and res.get("undone") == [g["id"]] and entry(Fr, FE)["amount"] == 5, f"frida's budget entry goes back {res}")
check(A.post(B + f"/api/undo/to/{g['id']}").status_code == 404 and not [x for x in lst(A) if x["id"] == g["id"]],
      "alice neither lists nor takes back frida's step (404)")

# ================================================================ the label in the reader's language
A.patch(B + "/api/settings", json={"lang": "de"})
g = newest(A)
check(g.get("label") == "Einstellung geändert: Sprache", f"in German: the setting's step names it {g}")
g = [x for x in lst(A) if x.get("kind") == "budget_entry"][0]
check(g.get("label", "").startswith("Geändert: Budgeteintrag vom"), f"... and the budget entry's {g}")

# ================================================================ review F2 / F7: a plain list sealed later (frida's own space)


def box(code):
    """Python code inside the app container (a fresh process with the server's settings), as tests/p2306_a_private_seal_test.py."""
    r = subprocess.run(["docker", "exec", kt.CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code
                        + "\nc.commit()\nc.close()"], capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip()


r = subprocess.run(["docker", "exec", "-i", kt.CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "decrypt-private"], capture_output=True, text=True, timeout=300)
check(one("SELECT sid FROM budget_entries WHERE id=?", (FE,)) == 0, f"(setup) decrypt-private: frida's entry is plain {r.returncode} {r.stdout[-200:]}")
r = Fr.patch(B + f"/api/budget/entries/{FE}", json={"title": "Kaffee Nord"})
GF = newest(Fr)["id"]
snap = one("SELECT snap FROM obj_undo WHERE group_id=?", (GF,)) or ""
check(r.ok and "Kaffee" in snap, "(setup) a step of the plain list: its copy is plain")
kt.dbx("UPDATE settings SET value='1' WHERE key='private_encrypt'")  # switched on again, the rows not resealed yet
res = back(Fr, GF)
st = res.get("stayed") or []
check(not res.get("undone") and [x["kind"] for x in st] == ["budget_entry"] and "list was encrypted" in (st[0].get("reason") or ""),
      f"F7: the plain copy of a list sealed since: \"The list was encrypted\" {res}")
out = box(f"from kalmido.life.budget import bud_settle\nprint('settled', bud_settle(c, [{int(FL)}]))")
check(one("SELECT sid FROM budget_entries WHERE id=?", (FE,)) == -FID, f"(setup) the list resealed for frida's space {out[-300:]}")
check(one("SELECT COUNT(*) FROM obj_undo WHERE kind='budget_entry' AND ref_id=?", (FE,)) == 0
      and one("SELECT COUNT(*) FROM undo_groups WHERE id=?", (GF,)) == 0
      and one("SELECT COUNT(*) FROM obj_history WHERE kind='budget_entry' AND ref_id=?", (FE,)) == 0
      and not [x for x in kt.dbx("SELECT CAST(label_args AS TEXT) FROM undo_groups WHERE user_id=?", (FID,)) if "Kaffee" in (x[0] or "")],
      "F2: the reseal took the entry's plain undo copies, their group and its history rows")

# ================================================================ review F2 / F7 (2.985.0, #5394): the save itself reseals
r = subprocess.run(["docker", "exec", "-i", kt.CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "decrypt-private"], capture_output=True, text=True, timeout=300)
check(one("SELECT sid FROM budget_entries WHERE id=?", (FE,)) == 0, f"(setup) frida's entry plain again {r.returncode} {r.stdout[-200:]}")
# F7: a toobig group (its parts went, ug_fits) whose label names the plain title
now = date.today().isoformat() + "T00:00:00+00:00"
kt.dbx("INSERT INTO undo_groups(user_id, area, label_key, label_args, state, parts, bytes, created_at, updated_at) "
       "VALUES(?, 'budget', 'Changed: {0}', '[\"Kaffee West\"]', 'toobig', 900, 0, ?, ?)", (FID, now, now))
kt.dbx("UPDATE settings SET value='1' WHERE key='private_encrypt'")  # switched on again, bud_settle has not reached the row
r = Fr.patch(B + f"/api/budget/entries/{FE}", json={"title": "Kaffee Sued"})
check(r.ok and one("SELECT sid FROM budget_entries WHERE id=?", (FE,)) == -FID, f"(setup) the save sealed the entry with frida's key {r.status_code}")
# F2: without the fix the step kept the plain copy (title, amount) and its label the plain title, up to 30 days
check(one("SELECT COUNT(*) FROM obj_undo WHERE kind='budget_entry' AND ref_id=?", (FE,)) == 0
      and one("SELECT COUNT(*) FROM obj_history WHERE kind='budget_entry' AND ref_id=?", (FE,)) == 0
      and not [x for x in kt.dbx("SELECT CAST(label_args AS TEXT) FROM undo_groups WHERE user_id=? AND label_args::text LIKE '%Kaffee Nord%'", (FID,))],
      "F2: a save that seals the entry anew takes its plain undo copies, their labels and its history rows")
check(not [x for x in kt.dbx("SELECT CAST(label_args AS TEXT) FROM undo_groups WHERE user_id=?", (FID,)) if "Kaffee West" in (x[0] or "")],
      "F7: the toobig group's plain label went as well")
# F8: a part counts relative to the row - a request's stale copy of the group (another request counted meanwhile) loses nothing
out = box("from kalmido.core.undogroups import ug_added\n"
          f"gid = c.execute(\"INSERT INTO undo_groups(user_id, area, parts, bytes, created_at, updated_at) VALUES({int(FID)}, 'budget', 5, 50, now(), now()) RETURNING id\").fetchone()[0]\n"
          "grp = {'id': gid, 'state': 'done', 'parts': 0, 'bytes': 0}\n"
          "ug_added(c, grp, 10)\n"
          "r = c.execute('SELECT parts, bytes FROM undo_groups WHERE id=?', (gid,)).fetchone()\n"
          "print('counted', r[0], r[1], grp['parts'])\n"
          "c.execute('DELETE FROM undo_groups WHERE id=?', (gid,))")
check("counted 6 60 6" in out, f"F8: the group counts the part relative to the row (6 parts, 60 bytes), the request's copy follows {out[-300:]}")

sys.exit(done("p2824_b_undo_rest"))
