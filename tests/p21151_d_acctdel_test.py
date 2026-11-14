#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1151.0 D (#4562): deleting one's own account tells the people of the projects that go along; a vCard without a change
date can overwrite a contact changed here when the import's switch says so. Invented names only.
freelancer-matrix: own (people without an organisation throughout)
 - a): frida asks for the deletion of her account (POST /api/account/delete): her project "Garden plan" goes along, "Shop
   list" is handed to hans. bob (member of the garden plan) finds a News entry orglist / acctdel with the project's name and
   the day; hans (only in the handed-over project), nina (in none of them) and frida herself get none; vera (member of the
   garden plan, the "share" row of her notification settings off) gets none either (switched like the other project
   notices); the entry names nothing of the content (no task title)
 - b): the import of a card without REV over a contact changed here: without the switch the contact keeps its values
   (kept_norev, as 2.533.0); with norev=1 the card's values win (taken_norev); a card WITH an older REV keeps its rule
usage: p21151_d_acctdel_test.py <datadir>"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx  # noqa: E402

PW = "password123"
kt.fresh()
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A, "frida")
BOB, Bo = freelancer(B, A, "bob")
HANS, Ha = freelancer(B, A, "hans")
NINA, Ni = freelancer(B, A, "nina")
VERA, Ve = freelancer(B, A, "vera")
dbx("UPDATE users SET email_proved=lower(COALESCE(email, '')) WHERE email_proved=''")  # sharing by address binds proved addresses

L1 = Fr.post(B + "/api/lists", json={"name": "Garden plan"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Shop list"}).json()["id"]
for lid, mail in ((L1, "bob@example.com"), (L1, "vera@example.com"), (L2, "hans@example.com")):
    r = Fr.put(B + f"/api/lists/{lid}/members", json={"email": mail, "role": "edit"})
    check(r.ok, f"setup: {mail} in project {lid} {r.status_code} {r.text[:150]}")
Fr.post(B + "/api/tasks", json={"title": "Secret tulip bulbs", "list_id": L1})
r = Ve.patch(B + "/api/settings", json={"notify": {"share": {"news": False}}})
check(r.ok, "setup: vera switches the project notices (row share) off " + r.text[:150])


def notices(s):
    items = s.get(B + "/api/news").json().get("items", [])
    return [x for x in items if x.get("kind") == "orglist" and (x.get("data") or {}).get("action") == "acctdel"]


check(not notices(Bo), "before: no notice")
r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": {str(L1): {"delete": True}, str(L2): {"to": HANS}}})
check(r.ok, f"frida asks for the deletion ({r.status_code} {r.text[:200]})")
at = r.json().get("delete_at") or ""
nb = notices(Bo)
check(len(nb) == 1 and nb[0]["data"].get("name") == "Garden plan" and nb[0].get("actor_id") == FID,
      f"#4562: bob (member of the project that goes along) hears it, with the project's name and frida as the actor {nb}")
day = (nb[0]["data"].get("day") or "") if nb else ""
check(len(day) == 10 and abs((date.fromisoformat(day) - date.fromisoformat(at[:10])).days) <= 1,
      f"#4562: the day of the deletion (the server's day of delete_at) {day} {at}")
check(bool(nb) and "tulip" not in str(nb[0]).lower(), "#4562: nothing of the project's content in the notice")
check(not notices(Ha), "#4562: hans (only in the project handed to him) gets no notice")
check(not notices(Ni), "#4562: nina (in none of frida's projects) gets no notice")
check(not notices(Ve), "#4562: vera switched the project notices off: none")
rows = dbx("SELECT user_id FROM notifications WHERE kind='orglist' AND data->>'action'='acctdel'")
check(sorted(r[0] for r in rows) == [BOB], f"#4562: exactly one notice was written (bob's) {rows}")
# review (job/4457): asking, taking back and asking again does not fill bob's bell -- his notice is still unread
r = kt.sess().post(B + "/api/auth/delete-cancel", json={"username": "frida", "password": PW})
check(r.ok, f"frida takes the request back with her password ({r.status_code} {r.text[:150]})")
Fr = kt.sess("frida")
r = Fr.post(B + "/api/account/delete", json={"password": PW, "lists": {str(L1): {"delete": True}, str(L2): {"to": HANS}}})
check(r.ok, f"frida asks again ({r.status_code} {r.text[:200]})")
rows = dbx("SELECT user_id FROM notifications WHERE kind='orglist' AND data->>'action'='acctdel'")
check(len(rows) == 1, f"#4562 review: no second notice while bob's first is unread {rows}")

# ================================================================== b) the vCard switch
def card(uid, fn, email, rev=None):
    L = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{fn}", f"N:{fn.split()[-1]};{fn.split()[0]};;;", f"EMAIL;TYPE=INTERNET:{email}"]
    return "\r\n".join(L + ([f"REV:{rev}"] if rev else []) + ["END:VCARD"]) + "\r\n"


def vimp(s, bid, text, norev=None):
    data = {"norev": norev} if norev is not None else {}
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("k.vcf", text.encode(), "text/vcard")}, data=data)
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:300]}


BID = Bo.post(B + "/api/books", json={"name": "Import 4562"}).json()["id"]
j = vimp(Bo, BID, card("nr-1", "Erika Sample", "erika@example.com") + card("nr-2", "Max Sample", "max@example.com", "2020-01-01T00:00:00Z"))
check(j.get("created") == 2, f"two contacts imported {j}")
C1 = dbx("SELECT id FROM contacts WHERE uid=?", ("nr-1",))[0][0]
C2 = dbx("SELECT id FROM contacts WHERE uid=?", ("nr-2",))[0][0]
for cid in (C1, C2):
    check(Bo.patch(B + f"/api/contacts/{cid}", json={"note": "changed here"}).ok, "a contact changed here")
j = vimp(Bo, BID, card("nr-1", "Erika Sample", "erika.new@example.com"))
d1 = Bo.get(B + f"/api/contacts/{C1}").json()
check(j.get("kept_norev") == 1 and not j.get("taken_norev") and d1["emails"][0]["value"] == "erika@example.com",
      f"#4562: without the switch a card without REV keeps the contact changed here (as 2.533.0) {j} {d1['emails']}")
j = vimp(Bo, BID, card("nr-1", "Erika Sample", "erika.new@example.com"), norev="0")
check(j.get("kept_norev") == 1, f"#4562: norev=0 is the same as off {j}")
j = vimp(Bo, BID, card("nr-1", "Erika Sample", "erika.new@example.com"), norev="1")
d1 = Bo.get(B + f"/api/contacts/{C1}").json()
check(j.get("taken_norev") == 1 and not j.get("kept_norev") and d1["emails"][0]["value"] == "erika.new@example.com",
      f"#4562: with the switch the card without REV overwrites the contact changed here {j} {d1['emails']}")
j = vimp(Bo, BID, card("nr-2", "Max Sample", "max.old@example.com", "2020-01-01T00:00:00Z"), norev="1")
d2 = Bo.get(B + f"/api/contacts/{C2}").json()
check(j.get("kept_newer") == 1 and not j.get("taken_norev") and d2["emails"][0]["value"] == "max@example.com",
      f"#4562: a card WITH an older REV keeps its rule also with the switch {j} {d2['emails']}")

sys.exit(kt.done("p21151_d_acctdel"))
