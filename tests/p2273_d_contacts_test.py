#!/usr/bin/env python3
"""2.273.0 C (#3048): contacts and calendar imports never turn newer values back; CardDAV / bulk undo / merges under a lock.
Invented people and addresses only (@example.com). freelancer-matrix: pim
 - vCard import with the same UID: a field the file does not carry stays (note, title); an older file (REV before the change
   here) leaves the contact as it is and the answer counts it (kept_newer); a newer file changes only the fields it carries;
   importing the same file twice stays "updated" without kept_newer
 - CardDAV: two PUTs with the same If-Match at the same time (threads, several rounds): exactly one 204, the other 412
 - bulk set + undo (restore): a contact changed again after the step is not reset, the answer names it (conflicts)
 - ICS import: an event changed here after the file's LAST-MODIFIED stays (kept_newer); a newer file without ATTENDEE lines
   keeps the attendees
 - 2.273.0 F2 (#3048): a contact without a picture gets the picture of a PHOTO link at a re-import (the fetch is a fake inside
   the server process; before, the column was filtered out and the link dropped from extra: the picture was lost)
 - 2.273.0 F2 (#3048): the own earlier import write is no change here: export E1 (REV 1.1.) imported, then E2 (REV 5.1., a real
   change at the source) is taken (was "kept_newer"); E1 again afterwards stays out (older than the last imported file);
   the same for ICS LAST-MODIFIED
 - 2.273.0 F2 (#3048): a merge in one address book does not wait for a merge of another person (one lock per contact, not one
   for the instance): a merge held open in a first connection, a second person's merge in a second one (lock_timeout) goes through
 - 2.273.0 F2 (#3048): REV with a UTC offset (20261024T154249+0200) is read as UTC (13:42:49), Z / plain date as before
 - the same for a person without an organisation (private address book / calendar)
usage: p2273_d_contacts_test.py <datadir>   (P2273D_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402


def card(uid, fn, email, rev=None, note=None, title=None, tel=None):
    L = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{fn}", f"N:{fn.split()[-1]};{fn.split()[0]};;;", f"EMAIL;TYPE=INTERNET:{email}"]
    L += [f"NOTE:{note}"] if note else []
    L += [f"TITLE:{title}"] if title else []
    L += [f"TEL;TYPE=CELL:{tel}"] if tel else []
    L += [f"REV:{rev}"] if rev else []
    return "\r\n".join(L + ["END:VCARD"]) + "\r\n"


def imp(s, bid, text):
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("k.vcf", text.encode(), "text/vcard")})
    assert r.ok, r.text
    return r.json()


def cid_of(uid):
    return kt.dbx("SELECT id FROM contacts WHERE uid=?", (uid,))[0][0]


def vcard_import(s, who):
    bid = s.post(B + "/api/books", json={"name": f"Import {who}"}).json()["id"]
    u = f"p2273-{who}-1"
    j = imp(s, bid, card(u, "Erika Beispiel", f"erika.{who}@example.com", note="alte Notiz", tel="+49 30 1234567"))
    check(j["created"] == 1, f"{who}: first import created {j}")
    cid = cid_of(u)
    r = s.patch(B + f"/api/contacts/{cid}", json={"note": "neue Notiz", "title": "Leiterin"})
    check(r.ok, f"{who}: note and title changed here " + r.text[:200])
    j = imp(s, bid, card(u, "Erika Beispiel", f"erika.alt.{who}@example.com", rev="20200101T000000Z"))
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(j.get("kept_newer") == 1 and j["updated"] == 0, f"{who}: an older export is counted, not written {j}")
    check(d["note"] == "neue Notiz" and d["title"] == "Leiterin" and d["emails"][0]["value"] == f"erika.{who}@example.com"
          and d["phones"], f"{who}: the newer values stay ({d['note']}, {d['title']}, {d['emails']}, {d['phones']})")
    j = imp(s, bid, card(u, "Erika Beispiel", f"erika.neu.{who}@example.com", rev="20990101T000000Z"))
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(j["updated"] == 1 and not j.get("kept_newer"), f"{who}: a newer file is taken {j}")
    check(d["emails"][0]["value"] == f"erika.neu.{who}@example.com" and d["note"] == "neue Notiz" and d["title"] == "Leiterin" and d["phones"],
          f"{who}: only the fields of the file changed ({d['emails']}, {d['note']}, {d['title']}, {d['phones']})")
    exp = s.get(B + f"/api/books/{bid}/export.vcf").text
    j1, j2 = imp(s, bid, exp), imp(s, bid, exp)
    check(j1["updated"] == 1 and j2["updated"] == 1 and not j1.get("kept_newer") and not j2.get("kept_newer"),
          f"{who}: the own export twice: updated, no conflict ({j1}, {j2})")
    return bid, cid


def carddav(s, user, bid, cid):
    pw = s.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
    href = kt.dbx("SELECT href FROM contacts WHERE id=?", (cid,))[0][0]
    path = f"/dav/addressbooks/{user}/b{bid}/{href}"
    dav = lambda m, body=None, **h: requests.request(m, B + path, auth=(user, pw), data=body.encode() if body else None,  # noqa: E731
                                                     headers={"X-Forwarded-Proto": "https", **{k.replace("_", "-"): v for k, v in h.items()}})
    for i in range(4):
        g = dav("GET")
        check(g.status_code == 200 and g.headers.get("ETag"), f"{user}: GET the card {g.status_code}")
        uid = kt.dbx("SELECT uid FROM contacts WHERE id=?", (cid,))[0][0]
        codes, bar = {}, threading.Barrier(2)

        def put(k):
            bar.wait()
            codes[k] = dav("PUT", card(uid, "Erika Beispiel", f"dav{i}{k}.{user}@example.com", note=f"Telefon {i} {k}"),
                           Content_Type="text/vcard", If_Match=g.headers["ETag"]).status_code

        th = [threading.Thread(target=put, args=(k,)) for k in (0, 1)]
        for t in th:
            t.start()
        for t in th:
            t.join()
        check(sorted(codes.values()) == [204, 412], f"{user} round {i}: same If-Match twice at once: one 204, one 412 ({codes})")


PHOTO_FAKE = '''
import sys
sys.path.insert(0, "/app")
import kalmido.calendars.subscriptions as S
from kalmido.contacts import model as M
from kalmido.core.db import connect
S.cal_http = lambda url, **kw: (200, {}, b"\\xff\\xd8\\xff" + b"1" * 3000, url)
c = connect()
res = M.import_vcards(c, %d, %d, %r, photos=30)
c.commit()
print(res["updated"], "P" if c.execute("SELECT photo FROM contacts WHERE book_id=? AND uid=?", (%d, %r)).fetchone()[0] else "-")
'''


def photo_link(s, who, bid):
    """2.273.0 F2 (#3048): a re-import with a PHOTO link fills the missing picture (not filtered out as 'not in the card')."""
    u = f"p2273-photo-{who}"
    check(imp(s, bid, card(u, "Paula Beispiel", f"paula.{who}@example.com"))["created"] == 1, f"{who}: contact without a picture")
    me = s.get(B + "/api/state").json()["me"]["id"]
    text = (f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{u}\r\nFN:Paula Beispiel\r\n"
            "PHOTO;VALUE=uri:https://lh3.googleusercontent.com/contacts/AG-example2\r\nEND:VCARD\r\n")
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", kt.CT, "python", "-"], input=PHOTO_FAKE % (me, bid, text, bid, u),
                       capture_output=True, text=True)
    check(p.stdout.strip() == "1 P", f"{who}: the linked picture is stored at the re-import ({p.stdout.strip()!r} {p.stderr[-300:]})")


def rev_marker(s, who, bid):
    """2.273.0 F2 (#3048): newer wins against the last import, not against the import's own write time."""
    u = f"p2273-rev-{who}"
    e1 = card(u, "Rita Beispiel", f"rita.{who}@example.com", rev="20200101T000000Z", note="Stand 1")
    e2 = card(u, "Rita Beispiel", f"rita.{who}@example.com", rev="20200105T000000Z", note="Stand 2")
    check(imp(s, bid, e1)["created"] == 1, f"{who}: E1 imported")
    cid = cid_of(u)
    j = imp(s, bid, e2)
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(j["updated"] == 1 and not j.get("kept_newer") and d["note"] == "Stand 2", f"{who}: E2 (newer REV) is taken after E1 ({j}, {d['note']!r})")
    j = imp(s, bid, e1)
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(j.get("kept_newer") == 1 and d["note"] == "Stand 2", f"{who}: E1 again stays out ({j}, {d['note']!r})")
    cal = s.post(B + "/api/evcals", json={"name": f"Rev {who}"}).json()["id"]
    ue = f"p2273-evrev-{who}@example.com"
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(ue, "Stand 1", "20200101T000000Z"), "text/calendar")})
    check(r.ok and r.json()["created"] == 1, f"{who}: event E1 imported {r.text[:200]}")
    eid = kt.dbx("SELECT id FROM events WHERE uid=?", (ue,))[0][0]
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(ue, "Stand 2", "20200105T000000Z"), "text/calendar")})
    t = s.get(B + f"/api/events/{eid}").json()
    check(r.ok and r.json()["updated"] == 1 and not r.json().get("kept_newer") and t["title"] == "Stand 2",
          f"{who}: event E2 is taken after E1 ({r.text[:200]}, {t['title']})")
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(ue, "Stand 1", "20200101T000000Z"), "text/calendar")})
    t = s.get(B + f"/api/events/{eid}").json()
    check(r.ok and r.json().get("kept_newer") == 1 and t["title"] == "Stand 2", f"{who}: event E1 again stays out ({r.text[:200]}, {t['title']})")


MERGE_PAR = '''
import sys
sys.path.insert(0, "/app")
from kalmido.contacts import merge as M, model as CM
from kalmido.core.db import connect
c1, c2 = connect(), connect()
bump = M.bump
M.bump = CM.bump = lambda c: None            # the data version row (every write's last step) is not what is probed here
M.ctm_merge(c1, %d, %d, [%d])                # held open: its merge lock stays until the commit below
M.bump = CM.bump = bump
c2.execute("SET LOCAL lock_timeout = '3s'")
try:
    M.ctm_merge(c2, %d, %d, [%d])
    c2.commit()
    print("ok")
except Exception as e:  # noqa: BLE001
    print("blocked", type(e).__name__)
c1.commit()
'''


def merge_parallel(sa, sb):
    """2.273.0 F2 (#3048): two people's merges at the same time."""
    out = []
    for who, s in (("alice", sa), ("frida", sb)):
        bid = s.post(B + "/api/books", json={"name": f"Merge {who}"}).json()["id"]
        us = [f"p2273-mg-{who}-{k}" for k in (0, 1)]
        imp(s, bid, "".join(card(u, "Mara Beispiel", f"mara.{k}.{who}@example.com") for k, u in enumerate(us)))
        out.append((s.get(B + "/api/state").json()["me"]["id"], cid_of(us[0]), cid_of(us[1])))
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", kt.CT, "python", "-"], input=MERGE_PAR % (*out[0], *out[1]),
                       capture_output=True, text=True)
    check(p.stdout.strip() == "ok", f"a merge of another person does not wait for an open one ({p.stdout.strip()!r} {p.stderr[-300:]})")
    check(not kt.dbx("SELECT 1 FROM contacts WHERE id IN (?, ?)", (out[0][2], out[1][2])), "both merges are stored")


def rev_offset():
    code = ("import sys\nsys.path.insert(0, '/app')\nfrom kalmido.contacts.model import vc_rev\n"
            "print(','.join(vc_rev(x) for x in ('20261024T154249+0200', '2026-10-24T15:42:49-05:00', '20261024T154249Z', '20261024')))")
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", kt.CT, "python", "-"], input=code, capture_output=True, text=True)
    check(p.stdout.strip() == "2026-10-24T13:42:49,2026-10-24T20:42:49,2026-10-24T15:42:49,2026-10-24T00:00:00",
          f"REV with a UTC offset is read as UTC ({p.stdout.strip()!r} {p.stderr[-300:]})")


def bulk_undo(s, who, cid):
    r = s.post(B + "/api/contacts/bulk", json={"action": "set", "ids": [cid], "note_append": "Messe 2026", "org": "Beispiel AG"})
    check(r.ok and r.json()["changed"] == 1 and r.json()["undo"] and r.json()["undo"][0].get("expect"), f"{who}: bulk set with undo + expect " + r.text[:200])
    undo = r.json()["undo"]
    cur = s.get(B + f"/api/contacts/{cid}").json()
    r2 = s.patch(B + f"/api/contacts/{cid}", json={"note": cur["note"] + "\nRückruf am Montag", "expect": cur["updated_at"]})
    check(r2.ok, f"{who}: changed again after the bulk step " + r2.text[:200])
    r = s.post(B + "/api/contacts/bulk", json={"action": "restore", "items": undo})
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(r.ok and r.json().get("conflicts") == [cid] and r.json()["changed"] == 0, f"{who}: the undo names the conflict " + r.text[:200])
    check("Rückruf am Montag" in d["note"] and d["org"] == "Beispiel AG", f"{who}: the later change stays ({d['note']!r}, {d['org']})")
    r = s.post(B + "/api/contacts/bulk", json={"action": "set", "ids": [cid], "org": "Andere GmbH"})
    r = s.post(B + "/api/contacts/bulk", json={"action": "restore", "items": r.json()["undo"]})
    d = s.get(B + f"/api/contacts/{cid}").json()
    check(r.ok and r.json()["changed"] == 1 and not r.json().get("conflicts") and d["org"] == "Beispiel AG", f"{who}: an undo without a change in between works {r.text[:200]}")


def ics(uid, title, mod, attendee=True):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Example//Test//EN", "BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20260101T000000Z",
         f"LAST-MODIFIED:{mod}", "DTSTART:20261203T090000Z", "DTEND:20261203T100000Z", f"SUMMARY:{title}"]
    L += ["ATTENDEE;CN=Gast Beispiel;PARTSTAT=ACCEPTED:mailto:gast@example.com"] if attendee else []
    return ("\r\n".join(L + ["END:VEVENT", "END:VCALENDAR"]) + "\r\n").encode()


def ics_import(s, who):
    cal = s.post(B + "/api/evcals", json={"name": f"Import {who}"}).json()["id"]
    u = f"p2273-ev-{who}@example.com"
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(u, "Planung", "20200101T000000Z"), "text/calendar")})
    check(r.ok and r.json()["created"] == 1, f"{who}: event imported {r.text[:200]}")
    eid = kt.dbx("SELECT id FROM events WHERE uid=?", (u,))[0][0]
    check(kt.dbx("SELECT COUNT(*) FROM event_attendees WHERE event_id=?", (eid,))[0][0] == 1, f"{who}: with its attendee")
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(u, "Planung", "20200101T000000Z"), "text/calendar")})
    check(r.ok and r.json()["updated"] == 1 and not r.json().get("kept_newer"), f"{who}: the same file twice: updated {r.text[:200]}")
    r = s.patch(B + f"/api/events/{eid}", json={"title": "Planung (verschoben)"})
    check(r.ok, f"{who}: event changed here " + r.text[:200])
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(u, "Planung", "20200101T000000Z"), "text/calendar")})
    t = s.get(B + f"/api/events/{eid}").json()
    check(r.ok and r.json().get("kept_newer") == 1 and t["title"] == "Planung (verschoben)", f"{who}: an older file leaves the event ({r.text[:200]}, {t['title']})")
    r = s.post(B + f"/api/evcals/{cal}/import", files={"file": ("a.ics", ics(u, "Planung neu", "20990101T000000Z", attendee=False), "text/calendar")})
    t = s.get(B + f"/api/events/{eid}").json()
    check(r.ok and r.json()["updated"] == 1 and t["title"] == "Planung neu", f"{who}: a newer file is taken ({r.text[:200]}, {t['title']})")
    check(kt.dbx("SELECT COUNT(*) FROM event_attendees WHERE event_id=?", (eid,))[0][0] == 1, f"{who}: a file without attendees keeps them")


kt.fresh(prefix="P2273D")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,contacts,collab,comments", "tour": "done", "workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)

for who, s in (("alice", A), ("frida", Fr)):
    bid, cid = vcard_import(s, who)
    carddav(s, who, bid, cid)
    photo_link(s, who, bid)
    rev_marker(s, who, bid)
    bulk_undo(s, who, cid)
    ics_import(s, who)
merge_parallel(A, Fr)
rev_offset()
sys.exit(kt.done("p2273_d_contacts"))
