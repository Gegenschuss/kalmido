#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.571.0 C (#4766, #4776): the shared core -- the own fields of tables and knowledge pages, the file store's revocation, who
changed events / contacts last, the leads' history and their millisecond versions. Own container (kt.fresh). Invented names.
 - #4766 tables: a new title (and a sheet's name) = ONE entry of obj_history (kind sheet; the changes of one person within ten
   minutes merge), none in sheet_hist; an old expect_updated_at = 409 with "current", the title stays; without one as before;
   GET /api/sheets/<id>/history shows it (what title / tab) next to an old sheet_hist row of 2.564 (still read)
 - #4766 knowledge: a rename = ONE obj_history entry (kind wiki) and no new version; an old expect_updated_at = 409 "page";
   GET .../versions carries it under "renames"
 - #4766 files: a folder's share taken back in the file store's dialog (DELETE /api/files/shares/<id>) is deleted with its log
   line, never kept dead in obj_revoked (review F7; only a core object's reference node goes there)
 - #4776: events and contacts carry updated_by: the app, the API (an agent with its version), CalDAV / CardDAV, the trash
 - #4776: a lead made in the app has a millisecond updated_at; its change is in obj_history (kind office_deal); a row with an
   old whole-second updated_at still matches expect_updated_at (200), an older one = 409
 - freelancer-matrix: sheets, wiki, files, pim, office (a person without an organisation, her own agent, her personal office)
usage: p2571_c_kern_test.py <datadir>      (P2571C_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import re
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,events,contacts,collab,comments,wiki,files,sheets,office,clients,docs"
MS = re.compile(r"\.\d{3}")
EV = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Example//Device//EN", "BEGIN:VEVENT", "UID:{uid}",
                  "DTSTAMP:20261101T100000Z", "DTSTART:20261203T090000Z", "DTEND:20261203T100000Z", "SUMMARY:{title}",
                  "END:VEVENT", "END:VCALENDAR", ""])


def card(uid, fn, note):
    return "\r\n".join(["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{fn}", f"N:{fn.split()[-1]};{fn.split()[0]};;;",
                        f"NOTE:{note}", "END:VCARD", ""])


def hd(token):
    return {**H, "Authorization": "Bearer " + token}


def hist(kind, rid):
    return dbx("SELECT user_id, agent, action, vals_before, vals_after FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id", (kind, rid))


def by(table, rid):
    return dbx(f"SELECT updated_by FROM {table} WHERE id=?", (rid,))[0][0]


class Dav:
    def __init__(self, s, user):
        r = s.post(B + "/api/me/app-passwords", json={"name": "Phone"})
        assert r.ok, r.text
        self.user, self.pw = user, r.json()["password"]

    def req(self, m, path, data=None, **h):
        return requests.request(m, B + path, auth=(self.user, self.pw), data=data.encode() if isinstance(data, str) else data,
                                headers={"X-Forwarded-Proto": "https", **{k.replace("_", "-"): v for k, v in h.items()}}, allow_redirects=False)


# ================================================================ #4766 tables
def sheets(who, s, me, space):
    r = s.post(B + "/api/sheets", json={"title": f"Budget {who}", "space": space})
    check(r.status_code == 201, f"{who}: setup: a table {r.text[:200]}")
    sid = r.json()["id"]
    u0 = s.get(B + f"/api/sheets/{sid}").json()["updated_at"]
    r = s.patch(B + f"/api/sheets/{sid}", json={"title": f"Budget {who} 2", "expect_updated_at": u0})
    check(r.ok and r.json()["title"] == f"Budget {who} 2", f"{who}: rename with the version read {r.status_code} {r.text[:200]}")
    h = hist("sheet", sid)
    check(len(h) == 1 and h[0][0] == me and not h[0][1] and '"title"' in h[0][4], f"{who}: one obj_history entry for the title {h}")
    check(not dbx("SELECT 1 FROM sheet_hist WHERE sheet_id=? AND what IN ('title', 'tab')", (sid,)),
          f"{who}: no second entry in sheet_hist")
    r = s.patch(B + f"/api/sheets/{sid}", json={"title": "Stale", "expect_updated_at": u0})
    check(r.status_code == 409 and (r.json().get("current") or {}).get("title") == f"Budget {who} 2",
          f"{who}: an old version 409 with the table now {r.status_code} {r.text[:200]}")
    check(s.get(B + f"/api/sheets/{sid}").json()["title"] == f"Budget {who} 2", f"{who}: the title stays after the 409")
    r = s.patch(B + f"/api/sheets/{sid}", json={"title": f"Budget {who} 3"})
    check(r.ok, f"{who}: without a version as before {r.status_code} {r.text[:200]}")
    h = hist("sheet", sid)
    check(len(h) == 1 and f"Budget {who} 3" in h[0][4] and f'"Budget {who}"' in h[0][3],
          f"{who}: a second rename within ten minutes merges into the same entry {h}")
    r = s.post(B + f"/api/sheets/{sid}/tabs", json={})
    check(r.status_code == 201, f"{who}: setup: a second sheet {r.text[:200]}")
    tid = r.json()["tab"]["id"]
    check(s.patch(B + f"/api/sheets/{sid}/tabs/{tid}", json={"name": "Costs"}).ok, f"{who}: the second sheet renamed")
    check(len(hist("sheet", tid)) == 1 and not dbx("SELECT 1 FROM sheet_hist WHERE sheet_id=? AND what='tab'", (tid,)),
          f"{who}: the sheet's name in obj_history only {hist('sheet', tid)}")
    # an entry of 2.564 (sheet_hist.what) stays readable next to the core's
    dbx("INSERT INTO sheet_hist(sheet_id, user_id, old_raw, new_raw, at, what) VALUES(?,?,?,?,?,?)",
        (sid, me, "Old A", "Old B", "2026-01-01T08:00:00.000+00:00", "title"))
    es = [(e.get("what"), e["old"], e["new"]) for e in s.get(B + f"/api/sheets/{sid}/history").json()["entries"] if e.get("what")]
    check(es == [("title", f"Budget {who}", f"Budget {who} 3"), ("title", "Old A", "Old B")],
          f"{who}: the history shows the core's entry and the old one, newest first {es}")
    es = [(e.get("what"), e["new"]) for e in s.get(B + f"/api/sheets/{tid}/history").json()["entries"] if e.get("what")]
    check(es == [("tab", "Costs")], f"{who}: the sheet name in its history {es}")
    return sid


# ================================================================ #4766 knowledge
def wiki(who, s, me, space):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": f"Notes/Alpha {who}", "body": "Ein Text"})
    check(r.status_code == 201, f"{who}: setup: a page {r.text[:200]}")
    pid = r.json()["id"]
    u0 = s.get(B + f"/api/wiki/pages/{pid}").json()["updated_at"]
    nv = dbx("SELECT COUNT(*) FROM wiki_versions WHERE page_id=?", (pid,))[0][0]
    r = s.patch(B + f"/api/wiki/pages/{pid}", json={"path": f"Notes/Beta {who}", "expect_updated_at": u0})
    check(r.ok and r.json()["path"] == f"Notes/Beta {who}", f"{who}: page renamed {r.status_code} {r.text[:200]}")
    h = hist("wiki", pid)
    check(len(h) == 1 and h[0][0] == me and f"Notes/Alpha {who}" in h[0][3] and f"Notes/Beta {who}" in h[0][4],
          f"{who}: one obj_history entry for the rename {h}")
    check(dbx("SELECT COUNT(*) FROM wiki_versions WHERE page_id=?", (pid,))[0][0] == nv, f"{who}: a rename alone makes no version")
    r = s.patch(B + f"/api/wiki/pages/{pid}", json={"path": "Notes/Stale", "expect_updated_at": u0})
    check(r.status_code == 409 and r.json().get("page"), f"{who}: an old version 409 with the page {r.status_code} {r.text[:200]}")
    check(len(hist("wiki", pid)) == 1, f"{who}: the 409 notes nothing")
    j = s.get(B + f"/api/wiki/pages/{pid}/versions").json()
    rn = j.get("renames") or []
    check(len(rn) == 1 and rn[0]["from"] == f"Notes/Alpha {who}" and rn[0]["to"] == f"Notes/Beta {who}",
          f"{who}: the versions answer carries the rename {rn}")
    check(not j["versions"] or j["versions"][0]["current"], f"{who}: the newest version is still the current text {j['versions']}")


# ================================================================ #4766 the file store's revocation
def files_revoke(who, s, space, agid):
    r = s.post(B + "/api/sheets/folders", json={"name": f"Shared {who}", "space": space})
    check(r.status_code == 201, f"{who}: setup: a folder {r.text[:200]}")
    nid = r.json()["folder"]["id"]
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json={"agent_id": agid, "role": "view"})
    check(r.status_code == 201, f"{who}: setup: the folder shared with the agent {r.text[:200]}")
    shid = r.json()["id"]
    check(s.delete(B + f"/api/files/shares/{shid}").ok, f"{who}: the share taken back in the dialog")
    check(not dbx("SELECT 1 FROM fs_shares WHERE id=?", (shid,)), f"{who}: the share is gone")
    # 2.571.0 (#4766): review F7 - a folder's share has no restore way, so it is deleted as before (no dead obj_revoked row)
    rv = [x for x in dbx("SELECT src, reason, row_json FROM obj_revoked WHERE src='fs_shares'") if f'"id": {shid},' in x[2]]
    check(rv == [], f"{who}: a folder's share is not kept in obj_revoked {rv}")
    check(dbx("SELECT 1 FROM fs_log WHERE node_id=? AND action='unshare' AND detail=?", (nid, str(shid))), f"{who}: the log line as before")


# ================================================================ #4776 events and contacts
def pim(who, s, me, user, ag_tok, agid):
    AH = hd(ag_tok)
    dav = Dav(s, user)
    cal = s.post(B + "/api/evcals", json={"name": f"Team {who}"}).json()["id"]
    check(s.put(B + f"/api/evcals/{cal}/members", json={"user_id": agid, "role": "edit"}).ok, f"{who}: setup: the calendar shared with the agent")
    r = s.post(B + "/api/events", json={"title": "Planung", "start": "2026-12-03T09:00", "end": "2026-12-03T10:00", "cal_id": cal})
    check(r.ok and r.json().get("updated_by") == me, f"{who}: event made in the app: updated_by = her {r.text[:200]}")
    eid = r.json()["id"]
    seen = requests.get(V + f"/events/{eid}", headers=AH).json()
    r = requests.patch(V + f"/events/{eid}", headers=AH, json={"location": "Raum 2", "expect_updated_at": seen["updated_at"]})
    check(r.ok and by("events", eid) == agid, f"{who}: event changed by the agent: updated_by = the agent {r.status_code} {by('events', eid)}")
    check(requests.get(V + f"/events/{eid}", headers=AH).json().get("updated_by") == agid, f"{who}: the API shows it")
    href = dbx("SELECT href, uid FROM events WHERE id=?", (eid,))[0]
    r = dav.req("PUT", f"/dav/calendars/{user}/e{cal}/{href[0]}", EV.format(uid=href[1], title="Planung neu"), Content_Type="text/calendar")
    check(r.status_code in (201, 204) and by("events", eid) == me, f"{who}: event changed over CalDAV: updated_by = her {r.status_code} {by('events', eid)}")
    r = dav.req("PUT", f"/dav/calendars/{user}/e{cal}/dav-{who}.ics", EV.format(uid=f"dav-{who}", title="Vom Telefon"), Content_Type="text/calendar")
    nid = (dbx("SELECT id FROM events WHERE uid=?", (f"dav-{who}",)) or [[0]])[0][0]
    check(r.status_code == 201 and nid and by("events", nid) == me, f"{who}: event made over CalDAV: updated_by = her {r.status_code}")
    requests.patch(V + f"/events/{eid}", headers=AH, json={"location": "Raum 3", "expect_updated_at": s.get(B + f"/api/events/{eid}").json()["updated_at"]})
    check(s.delete(B + f"/api/events/{eid}").ok and by("events", eid) == me, f"{who}: event into the trash: updated_by = her")
    check(s.post(B + f"/api/events/{eid}/restore").ok and by("events", eid) == me, f"{who}: event restored: updated_by = her")

    bid = s.post(B + "/api/books", json={"name": f"Kunden {who}"}).json()["id"]
    check(s.put(B + f"/api/books/{bid}/members", json={"user_id": agid, "role": "edit"}).ok, f"{who}: setup: the address book shared with the agent")
    r = s.post(B + "/api/contacts", json={"fn": "Erika Beispiel", "book_id": bid})
    check(r.ok and r.json().get("updated_by") == me, f"{who}: contact made in the app: updated_by = her {r.text[:200]}")
    cid = r.json()["id"]
    cseen = requests.get(V + f"/contacts/{cid}", headers=AH).json()
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "vom Agenten", "expect_updated_at": cseen["updated_at"]})
    check(r.ok and by("contacts", cid) == agid and r.json().get("updated_by") == agid,
          f"{who}: contact changed by the agent: updated_by = the agent {r.status_code} {by('contacts', cid)}")
    chref, cuid = dbx("SELECT href, uid FROM contacts WHERE id=?", (cid,))[0]
    r = dav.req("PUT", f"/dav/addressbooks/{user}/b{bid}/{chref}", card(cuid, "Erika Beispiel", "vom Telefon"), Content_Type="text/vcard")
    check(r.status_code in (201, 204) and by("contacts", cid) == me, f"{who}: contact changed over CardDAV: updated_by = her {r.status_code} {by('contacts', cid)}")
    r = requests.patch(V + f"/contacts/{cid}", headers=AH, json={"note": "noch mal", "expect_updated_at": s.get(B + f"/api/contacts/{cid}").json()["updated_at"]})
    check(r.ok and by("contacts", cid) == agid, f"{who}: setup: the agent changed it again")
    check(s.delete(B + f"/api/contacts/{cid}").ok and by("contacts", cid) == me, f"{who}: contact into the trash: updated_by = her")
    check(s.post(B + f"/api/contacts/{cid}/restore").ok and by("contacts", cid) == me, f"{who}: contact restored: updated_by = her")


# ================================================================ #4776 leads
def leads(who, s, me):
    O = "/api/office"
    r = s.post(B + O + "/deals", json={"title": f"Anfrage {who}", "stage": "lead", "note": "erst"})
    check(r.status_code == 201 and MS.search(r.json().get("updated_at") or ""), f"{who}: a lead made in the app: updated_at in ms {r.text[:200]}")
    did = r.json()["id"]
    r = s.patch(B + f"{O}/deals/{did}", json={"note": "dann", "expect_updated_at": r.json()["updated_at"]})
    check(r.ok and MS.search(r.json().get("updated_at") or ""), f"{who}: the lead changed {r.status_code} {r.text[:200]}")
    h = hist("office_deal", did)
    check(len(h) == 1 and h[0][0] == me and h[0][2] == "update" and "note" in h[0][4], f"{who}: the change is in obj_history {h}")
    old = "2026-01-02T10:00:05+00:00"  # a row of an older version: whole seconds
    dbx("UPDATE office_deals SET updated_at=? WHERE id=?", (old, did))
    r = s.patch(B + f"{O}/deals/{did}", json={"note": "alt", "expect_updated_at": "2026-01-02T10:00:04+00:00"})
    check(r.status_code == 409, f"{who}: an older whole-second version 409 {r.status_code} {r.text[:200]}")
    r = s.patch(B + f"{O}/deals/{did}", json={"note": "alt", "expect_updated_at": old})
    check(r.ok and r.json()["note"] == "alt" and MS.search(r.json()["updated_at"]), f"{who}: the whole-second version as read 200, now ms {r.status_code} {r.text[:200]}")


# ================================================================ setup
kt.fresh(prefix="P2571C")
kt.docker_logs_on_first_fail()
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude", "scopes": ["read", "calendar", "contacts"], "org_id": ORG})
check(r.ok, "setup: alice's agent " + r.text[:200])
ATK = r.json()["token"]
AAG = requests.get(V + "/me", headers=hd(ATK)).json().get("id")
SP = f"org:{ORG}"

sheets("alice", A, ALICE, SP)
wiki("alice", A, ALICE, SP)
files_revoke("alice", A, SP, AAG)
pim("alice", A, ALICE, "alice", ATK, AAG)
leads("alice", A, ALICE)

# freelancer-matrix: sheets, wiki, files, pim, office
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "private"})
Fr.get(B + "/api/office/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "calendar", "contacts"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FTK = r.json()["id"], r.json()["token"]
sheets("frida", Fr, FID, "private")
wiki("frida", Fr, FID, "private")
files_revoke("frida", Fr, "private", FAG)
pim("frida", Fr, FID, "frida", FTK, FAG)
leads("frida", Fr, FID)
sys.exit(kt.done("p2571_c_kern"))
