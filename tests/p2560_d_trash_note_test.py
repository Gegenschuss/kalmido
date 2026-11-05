#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.560.0 D (#4667): the undo of deleting a trip (and of a credit card position) writes its office trash copy back like the
general office trash and says the same: a client deleted for good meanwhile is emptied (gone) and the answer carries the
sentence (restore_note for a trip - the trip has a note of its own; note for a card position). Own container (kt.fresh,
mode workspaces). Invented names only (example.com); the person without an organisation (tests/freelancer_fixture.py) does
every step, an organisation admin the trip step once more.
freelancer-matrix: office
usage: p2560_d_trash_note_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import os
import sys
from datetime import date

import requests

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import FEATURES, freelancer

O = "/api/office"
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def kt_src(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2560D")
s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD}).ok
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})  # Alice admins the organisation Alpha
A = kt.sess("alice")
check(A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok, "setup: Alice's features")
FID, Fr = freelancer(B, A)
D = date.today().isoformat()


def trip_client_gone(S, who):
    """A trip naming a client goes to the office trash, the client is deleted for good, the trip's undo brings it back."""
    cid = S.post(B + "/api/clients", json={"name": f"Reisekunde {who} GmbH", "email": f"reise-{who}@example.com"}).json()["id"]
    r = S.post(B + O + "/trips", json={"date_from": D, "date_to": D, "dest": f"Beispielstadt {who}", "client_id": cid, "note": "eigene Notiz"})
    check(r.ok, f"{who}: a trip with a client {r.status_code} {r.text[:160]}")
    tid = r.json()["id"]
    check(sql("SELECT client_id FROM office_trips WHERE id=?", (tid,))[0][0] == cid, f"{who}: the trip names the client")
    r = S.delete(B + O + f"/trips/{tid}")
    ttid = r.json().get("trash_id") if r.ok else None
    check(bool(ttid), f"{who}: the trip is in the office trash {r.status_code} {r.text[:160]}")
    check(S.delete(B + f"/api/clients/{cid}").ok, f"{who}: the client goes to the trash")
    r = S.delete(B + f"/api/clients/{cid}/purge")
    check(r.ok and not sql("SELECT 1 FROM clients WHERE id=?", (cid,)), f"{who}: the client is deleted for good {r.status_code} {r.text[:160]}")
    r = S.post(B + O + f"/trips/trash/{ttid}/restore")
    j = r.json() if r.ok else {}
    check(r.ok and j.get("id") == tid, f"{who}: the trip comes back {r.status_code} {r.text[:200]}")
    check("client_id" in (j.get("gone") or []), f"{who}: the answer names the emptied client (gone): {j}")
    check("without a client" in (j.get("restore_note") or ""), f"{who}: the answer carries the sentence (restore_note): {j}")
    check(j.get("note") == "eigene Notiz", f"{who}: the trip's own note stays its note: {j.get('note')!r}")
    check(sql("SELECT client_id FROM office_trips WHERE id=?", (tid,))[0][0] is None, f"{who}: the trip has no client now")
    # a trip whose client is still there: no gone, no sentence
    r = S.post(B + O + "/trips", json={"date_from": D, "date_to": D, "dest": f"Ohnehin {who}"})
    tid2 = r.json()["id"]
    ttid2 = S.delete(B + O + f"/trips/{tid2}").json().get("trash_id")
    j = S.post(B + O + f"/trips/trash/{ttid2}/restore").json()
    check(j.get("id") == tid2 and "gone" not in j and "restore_note" not in j, f"{who}: nothing gone, nothing said: {j}")


trip_client_gone(Fr, "freelancer")
trip_client_gone(A, "org")

# a credit card position: the undo answer has the same shape (its table has no reference that can go, so nothing is said)
card = Fr.post(B + O + "/cards", json={"holder_id": FID, "last4": "2468"})
check(card.ok, f"card: freelancer card {card.status_code} {card.text[:160]}")
st = Fr.post(B + f"{O}/cards/{card.json()['id']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]})
SID = st.json()["statement"]["id"]
LID = Fr.post(B + f"{O}/cards/statements/{SID}/lines", json={"day": D, "merchant": "Hinweisweg Beispiel", "amount": "4.00"}).json()["line"]["id"]
TID = Fr.delete(B + f"{O}/cards/lines/{LID}").json().get("trash_id")
r = Fr.post(B + f"{O}/cards/trash/{TID}/restore")
j = r.json() if r.ok else {}
check(r.ok and j["line"]["id"] == LID and "gone" not in j and "note" not in j, f"card: the position comes back, nothing gone {r.status_code} {r.text[:200]}")

# the app shows the sentence: the trip's undo toasts restore_note, the card undo hands note to the history's message
tj, cj, uj = kt_src("static/js/office_travel.js"), kt_src("static/js/office_cards.js"), kt_src("static/js/undo.js")
check(tj.count("r?.restore_note") == 2, "UI: both trip deletes show restore_note after the undo")
check("return r.note ? {note: r.note}" in cj and "return r?.note ? {note: r.note}" in cj, "UI: the card position's undo hands the note on")
check("toast(note ||" in uj, "UI: the history's message says the note instead of 'Undone: …'")

sys.exit(done("p2560_d_trash_note"))
