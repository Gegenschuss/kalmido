#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.579.0 part D (#4293): after access ends, no side way stays open. Own container (mode workspaces). Invented names only.
tenant-matrix: org

One person (bob) gets something of alice's in each area - a knowledge page, a calendar, an address book, a folder of the file
store, a project (list) - and reads it on every way he has: the page / item itself, its file, the search, the export, his own
calendar feed / task feed, CalDAV / CardDAV with an app password and the REST API with his personal token. Every way must answer
BEFORE (so a probe that is always refused proves nothing) and none AFTER:
 - 1 revoked: each share / membership taken back through its own route (bob has no organisation here: a freelancer)
 - 2 expired: each share with an end date that has passed (the API takes no past date: set in the data)
 - 3 left: the same areas inside an organisation (explicit shares + what every member reads); bob leaves it
 - 4 back as a guest the same day: nothing of before comes back
 - 5 made a guest: what every member reads of the organisation (its knowledge pages) ends
 - 6 retired: the organisation is retired (it keeps finalised office data); a former member reads nothing of it
freelancer-matrix: wiki, events, contacts, files, tasks (scenarios 1 and 2: bob is a person without an organisation)
usage: p2579_d_revoke_test.py <datadir>"""
import os
import re
import sys
from datetime import datetime, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import requests  # noqa: E402
from kt import B, check, sess  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files,wiki,docs,office,clients"
V = B + "/api/v1"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a2e5e3c40000000049454e44ae426082")
PAST = "2001-01-01T00:00:00+00:00"
FROM, TO = "2026-11-01", "2027-01-31"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": "A" * 43 + "=",
          "KALMIDO_API_RATE": "100000"}, prefix="P2579D")  # every way is asked many times: no token limit in the way


def sql(q, args=()):
    return kt.dbx(q, args)


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": []})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
check(not sql("SELECT 1 FROM org_members WHERE user_id=?", (BOB,)), "setup: bob has no organisation (a freelancer)")
# bob's own ways in: an app password (CalDAV / CardDAV) and a personal API token
r = Bo.post(B + "/api/me/app-passwords", json={"name": "phone"})
check(r.status_code == 201 and r.json().get("password"), "setup: bob's app password " + r.text[:120])
APW = r.json().get("password")
r = Bo.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "calendar", "contacts", "files:read", "wiki:read", "attachments:read", "export"]})
check(r.status_code == 201 and r.json().get("token"), "setup: bob's personal token " + r.text[:120])
TOKH = {"Authorization": "Bearer " + (r.json().get("token") or "")}
r = Bo.post(B + "/api/ical", json={"action": "create"})
check(r.ok and r.json().get("url"), "setup: bob's task feed " + r.text[:120])
TFEED = re.sub(r"^https?://[^/]+", "", r.json().get("url") or "")


def v1(path, **kw):
    return requests.get(V + path, headers=TOKH, **kw)


def dav(m, path, body=None, **h):
    hd = {"X-Forwarded-Proto": "https", "Content-Type": "application/xml; charset=utf-8", **{k.replace("_", "-"): v for k, v in h.items()}}
    return requests.request(m, B + path, auth=("bob", APW), data=body.encode() if isinstance(body, str) else body, headers=hd, allow_redirects=False)


PF = '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:resourcetype/><D:displayname/></D:prop></D:propfind>'
CQ = ('<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop>'
      '<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="{0}"/></C:comp-filter></C:filter></C:calendar-query>')
AQ = ('<?xml version="1.0"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/><card:address-data/>'
      '</d:prop><card:filter><card:prop-filter name="FN"><card:text-match collation="i;unicode-casemap" match-type="contains">{0}</card:text-match>'
      '</card:prop-filter></card:filter></card:addressbook-query>')


def body(r):
    return r.text if r.status_code < 400 else ""


def has(r, word):
    """the answer carries word (refused / not found = no)"""
    return r.status_code < 300 and word in r.text


def ok(r):
    return r.status_code == 200


def ids(r, key=None):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get(key) if key else None) or j.get("items") or j.get("data") or []
    return {x.get("id") for x in rows if isinstance(x, dict)}


def dav_home(kind):
    r = dav("PROPFIND", f"/dav/{kind}/bob/", PF, Depth="1")
    return r.text if r.status_code == 207 else ""


# ================================================================== the things of one round, one per area
def make(tag, space, project=True):
    """alice's knowledge page (+ picture), calendar (+ event), address book (+ contact), folder (+ file), project (+ task with a
    file) in space ('private' | 'org:<id>'), each carrying the word W<tag><area> -> dict of ids and words"""
    A.patch(B + "/api/settings", json={"workspace": space})
    oid = int(space[4:]) if space.startswith("org:") else None
    x = {"space": space, "tag": tag}
    w = lambda a: f"Zq{tag}{a}"  # noqa: E731
    x["ww"], x["cw"], x["bw"], x["fw"], x["lw"] = w("wiki"), w("cal"), w("book"), w("file"), w("list")
    # knowledge page in its own folder (a person share of the page / the org folder)
    r = A.post(B + "/api/wiki/pages", json={"space": space, "path": f"{tag}/Plan", "body": f"The plan {x['ww']} here"})
    check(r.status_code == 201, f"{tag} setup: a knowledge page {r.text[:160]}")
    x["wp"] = r.json().get("id")
    r = A.post(B + f"/api/wiki/pages/{x['wp']}/files", files={"file": (f"{x['ww']}.png", PNG, "image/png")})
    check(r.status_code == 201, f"{tag} setup: a picture on the page {r.text[:160]}")
    x["wf"] = ((r.json().get("files") or [{}])[0]).get("id") if r.status_code == 201 else None
    x["wfolder"] = next((f["id"] for f in A.get(B + "/api/wiki", params={"space": space}).json().get("folders", []) if f.get("path") == tag), None)
    # calendar + event
    r = A.post(B + "/api/evcals", json={"name": f"{tag} calendar", **({"org_id": oid} if oid else {})})
    check(r.status_code == 201, f"{tag} setup: a calendar {r.text[:160]}")
    x["cal"] = r.json().get("id")
    r = A.post(B + "/api/events", json={"title": f"Meeting {x['cw']}", "start": "2026-12-01T10:00", "end": "2026-12-01T11:00", "cal_id": x["cal"]})
    check(r.status_code in (200, 201), f"{tag} setup: an event {r.text[:160]}")
    x["ev"] = r.json().get("id")
    # address book + contact
    r = A.post(B + "/api/books", json={"name": f"{tag} contacts", **({"org_id": oid} if oid else {})})
    check(r.status_code == 201, f"{tag} setup: an address book {r.text[:160]}")
    x["book"] = r.json().get("id")
    r = A.post(B + "/api/contacts", json={"book_id": x["book"], "fn": f"Person {x['bw']}", "emails": [{"value": f"{tag.lower()}@example.com"}]})
    check(r.status_code in (200, 201), f"{tag} setup: a contact {r.text[:160]}")
    x["ct"] = r.json().get("id")
    # folder + file of the file store
    r = A.post(B + "/api/files/folders", json={"name": f"{tag} folder", "space": space})
    check(r.status_code in (200, 201), f"{tag} setup: a folder {r.text[:160]}")
    x["fd"] = r.json().get("id")
    r = A.post(B + "/api/files/upload", data={"parent_id": str(x["fd"])}, files={"file": (f"{x['fw']}.txt", f"text {x['fw']} of the file\n".encode() * 20, "text/plain")})
    check(r.ok, f"{tag} setup: a file {r.text[:160]}")
    x["fn"] = ((r.json().get("items") or [{}])[0]).get("id") if r.ok else None
    # project + task + attachment
    if not project:
        A.patch(B + "/api/settings", json={"workspace": "all"})
        return x
    r = A.post(B + "/api/lists", json={"name": f"{tag} project", **({"org_id": oid} if oid else {})})
    check(r.ok, f"{tag} setup: a project {r.text[:160]}")
    x["list"] = r.json().get("id")
    r = A.post(B + "/api/tasks", json={"title": f"Task {x['lw']}", "list_id": x["list"], "due": "2026-12-02"})
    x["task"] = r.json().get("id")
    r = A.post(B + f"/api/tasks/{x['task']}/attachments", files={"file": (f"{x['lw']}.txt", f"attached {x['lw']}\n".encode() * 20, "text/plain")})
    check(r.ok, f"{tag} setup: an attachment {r.text[:160]}")
    j = r.json() if r.ok else {}
    x["att"] = j.get("id") or ((j.get("items") or j.get("attachments") or [{}])[0]).get("id")
    A.patch(B + "/api/settings", json={"workspace": "all"})
    return x


def grant(x, wiki=True):
    """bob gets each thing explicitly (wiki: a person share of the page in a private space, the folder share in an organisation)
    -> the share ids where the area has its own"""
    g = {}
    if wiki and x["space"] == "private":
        r = A.post(B + "/api/wiki/shares", json={"page_id": x["wp"], "kind": "person", "user_id": BOB})
        check(r.status_code == 201, f"{x['tag']} grant: the page shared with bob {r.text[:160]}")
        g["wiki"] = r.json().get("id")
    elif wiki:
        r = A.post(B + f"/api/files/nodes/{x['wfolder']}/shares", json={"user_id": BOB, "role": "view"})
        check(r.status_code == 201, f"{x['tag']} grant: the knowledge folder shared with bob {r.text[:160]}")
        g["wikinode"] = r.json().get("id")
    check(A.put(B + f"/api/evcals/{x['cal']}/members", json={"user_id": BOB, "role": "view"}).ok, f"{x['tag']} grant: bob in the calendar")
    check(A.put(B + f"/api/books/{x['book']}/members", json={"user_id": BOB, "role": "view"}).ok, f"{x['tag']} grant: bob in the address book")
    r = A.post(B + f"/api/files/nodes/{x['fd']}/shares", json={"user_id": BOB, "role": "view"})
    check(r.status_code == 201, f"{x['tag']} grant: the folder shared with bob {r.text[:160]}")
    g["fs"] = r.json().get("id")
    if x.get("list"):
        r = A.put(B + f"/api/lists/{x['list']}/members", json={"user_id": BOB, "role": "view"})
        check(r.ok, f"{x['tag']} grant: bob in the project {r.text[:160]}")
    r = Bo.post(B + f"/api/evcals/{x['cal']}/feed", json={"action": "create"})
    check(r.ok and r.json().get("url"), f"{x['tag']} grant: bob's own feed of the calendar {r.text[:160]}")
    x["feed"] = re.sub(r"^https?://[^/]+", "", r.json().get("url") or "") if r.ok else None
    return g


# ================================================================== every way bob reads, per area: name -> True = bob sees it
def probes(x, areas=("wiki", "cal", "book", "files", "list")):
    P = {}
    ww, cw, bw, fw, lw = x["ww"], x["cw"], x["bw"], x["fw"], x["lw"]
    if "wiki" in areas:
        P["wiki: the page"] = lambda: has(Bo.get(B + f"/api/wiki/pages/{x['wp']}"), ww)
        P["wiki: the shared page"] = lambda: has(Bo.get(B + f"/api/wiki/shared/pages/{x['wp']}"), ww) or (x["space"] != "private" and has(Bo.get(B + f"/api/wiki/pages/{x['wp']}"), ww))
        P["wiki: its picture"] = lambda: ok(Bo.get(B + f"/api/wiki/shared/files/{x['wf']}")) or ok(Bo.get(B + f"/api/wiki/files/{x['wf']}"))
        P["wiki: the list of shared / space pages"] = lambda: x["wp"] in ids(Bo.get(B + "/api/wiki/shared"), "pages") or (
            x["space"] != "private" and has(Bo.get(B + "/api/wiki", params={"space": x["space"]}), f"{x['tag']}/Plan"))
        P["wiki: API v1 page (token)"] = lambda: has(v1(f"/wiki/pages/{x['wp']}"), ww)
        P["wiki: API v1 picture (token)"] = lambda: ok(v1(f"/wiki/files/{x['wf']}"))
        P["wiki: API v1 page list (token)"] = lambda: x["wp"] in ids(v1("/wiki/pages", params={"space": "all"}))
    if "cal" in areas:
        P["calendar: in the list of calendars"] = lambda: x["cal"] in ids(Bo.get(B + "/api/evcals"))
        P["calendar: its events"] = lambda: x["ev"] in {e.get("eid") for e in (Bo.get(B + "/api/events", params={"from": FROM, "to": TO}).json() or {}).get("items") or []}
        P["calendar: the event"] = lambda: has(Bo.get(B + f"/api/events/{x['ev']}"), cw)
        P["calendar: export .ics"] = lambda: has(Bo.get(B + f"/api/evcals/{x['cal']}/export.ics"), cw)
        P["calendar: bob's feed"] = lambda: bool(x.get("feed")) and has(requests.get(B + x["feed"]), cw)
        P["calendar: CalDAV home"] = lambda: f"/e{x['cal']}/" in dav_home("calendars")
        P["calendar: CalDAV query"] = lambda: cw in body(dav("REPORT", f"/dav/calendars/bob/e{x['cal']}/", CQ.format("VEVENT"), Depth="1"))
        P["calendar: API v1 calendars (token)"] = lambda: x["cal"] in ids(v1("/event-calendars"))
        P["calendar: API v1 event (token)"] = lambda: has(v1(f"/events/{x['ev']}"), cw)
        P["calendar: API v1 export (token)"] = lambda: has(v1(f"/event-calendars/{x['cal']}/export"), cw)
    if "book" in areas:
        P["contacts: in the list of address books"] = lambda: x["book"] in ids(Bo.get(B + "/api/books"))
        P["contacts: search"] = lambda: x["ct"] in ids(Bo.get(B + "/api/contacts", params={"q": bw}))
        P["contacts: the contact"] = lambda: has(Bo.get(B + f"/api/contacts/{x['ct']}"), bw)
        P["contacts: export .vcf"] = lambda: has(Bo.get(B + f"/api/books/{x['book']}/export.vcf"), bw)
        P["contacts: export .csv"] = lambda: has(Bo.get(B + f"/api/books/{x['book']}/export.csv"), bw)
        P["contacts: CardDAV home"] = lambda: f"/b{x['book']}/" in dav_home("addressbooks")
        P["contacts: CardDAV query"] = lambda: bw in body(dav("REPORT", f"/dav/addressbooks/bob/b{x['book']}/", AQ.format(bw), Depth="1"))
        P["contacts: API v1 books (token)"] = lambda: x["book"] in ids(v1("/address-books"))
        P["contacts: API v1 search (token)"] = lambda: x["ct"] in ids(v1("/contacts", params={"q": bw}))
        P["contacts: API v1 contact (token)"] = lambda: has(v1(f"/contacts/{x['ct']}"), bw)
        P["contacts: API v1 export (token)"] = lambda: has(v1(f"/address-books/{x['book']}/export"), bw)
    if "files" in areas:
        P["files: the folder"] = lambda: x["fn"] in ids(Bo.get(B + "/api/files", params={"parent": x["fd"]}))
        P["files: the file"] = lambda: ok(Bo.get(B + f"/api/files/nodes/{x['fn']}"))
        P["files: its content"] = lambda: has(Bo.get(B + f"/api/files/nodes/{x['fn']}/content"), fw)
        P["files: zip"] = lambda: ok(Bo.get(B + "/api/files/zip", params={"ids": str(x["fn"])}))
        P["files: search"] = lambda: x["fn"] in ids(Bo.get(B + "/api/search?kind=files", params={"q": fw}))
        P["files: API v1 file (token)"] = lambda: ok(v1(f"/files/{x['fn']}"))
        P["files: API v1 content (token)"] = lambda: has(v1(f"/files/{x['fn']}/content"), fw)
        P["files: API v1 search (token)"] = lambda: x["fn"] in ids(v1("/search?kind=files", params={"q": fw}))
    if "list" in areas and x.get("list"):
        P["project: in the state"] = lambda: x["task"] in ids(Bo.get(B + "/api/state"), "tasks")
        P["project: the task"] = lambda: has(Bo.get(B + f"/api/tasks/{x['task']}"), lw)
        P["project: the attachment"] = lambda: has(Bo.get(B + f"/api/attachments/{x['att']}"), lw)
        P["project: export .csv"] = lambda: has(Bo.get(B + f"/api/lists/{x['list']}/export.csv"), lw)
        P["project: search"] = lambda: lw in body(Bo.get(B + "/api/search", params={"q": lw}))
        P["project: bob's task feed"] = lambda: has(requests.get(B + TFEED), lw)
        P["project: CalDAV home"] = lambda: f"/{x['list']}/" in dav_home("calendars")
        P["project: CalDAV query"] = lambda: lw in body(dav("REPORT", f"/dav/calendars/bob/{x['list']}/", CQ.format("VTODO"), Depth="1"))
        P["project: API v1 list (token)"] = lambda: has(v1(f"/lists/{x['list']}"), f"{x['tag']} project")
        P["project: API v1 task (token)"] = lambda: has(v1(f"/tasks/{x['task']}"), lw)
        P["project: API v1 attachment (token)"] = lambda: has(v1(f"/attachments/{x['att']}"), lw)
        P["project: API v1 search (token)"] = lambda: lw in body(v1("/search", params={"q": lw}))
    return P


# ways that never show something shared with bob (only his own or full-role spaces): checked after only, never before
AFTER_ONLY = {"wiki: search": lambda x: x["ww"] in body(Bo.get(B + "/api/search?kind=wiki", params={"q": x["ww"]})),
              "wiki: export": lambda x: x["ww"].encode() in (Bo.get(B + "/api/wiki/export", params={"space": "all"}).content or b"")}


def before(x, tag, areas=None):
    P = probes(x, *([areas] if areas else []))
    # a file's text is read in the background (search): wait for it once, then every way must answer
    kt.until(lambda: all(f() for f in P.values()), timeout=20)
    miss = [k for k, f in P.items() if not f()]
    check(not miss, f"{tag} before: bob reads on every way (else the probe proves nothing): missing {miss}")
    return P


def after(x, tag, areas=None):
    P = probes(x, *([areas] if areas else []))
    P.update({k: (lambda f=f: f(x)) for k, f in AFTER_ONLY.items() if not areas or "wiki" in areas})
    open_ = [k for k, f in P.items() if f()]
    check(not open_, f"{tag} after: no way is still open: open {open_}")
    return open_


# ================================================================== 1 revoked (bob is a freelancer here)
X1 = make("Rv", "private")
G1 = grant(X1)
before(X1, "1 revoked")
check(A.delete(B + f"/api/wiki/shares/{G1['wiki']}").ok, "1 revoked: the page share taken back")
check(A.delete(B + f"/api/evcals/{X1['cal']}/members/{BOB}").ok, "1 revoked: bob out of the calendar")
check(A.delete(B + f"/api/books/{X1['book']}/members/{BOB}").ok, "1 revoked: bob out of the address book")
check(A.delete(B + f"/api/files/shares/{G1['fs']}").ok, "1 revoked: the folder share taken back")
check(A.delete(B + f"/api/lists/{X1['list']}/members/{BOB}").ok, "1 revoked: bob out of the project")
after(X1, "1 revoked")

# ================================================================== 2 expired (the end date set in the data: the API takes no past date)
X2 = make("Ex", "private")
G2 = grant(X2)
before(X2, "2 expired")
# 2.937.0 (#5244): a person share of a page is its core share (+ its pair), the dialog's id "p<share id>"
W2F = int(str(G2["wiki"]).lstrip("p") or 0)
sql("UPDATE fs_shares SET expires_at=? WHERE id IN (SELECT fs_share_id FROM wiki_share_cards WHERE fs_share_id=? UNION SELECT pair_id FROM wiki_share_cards WHERE fs_share_id=?)", (PAST, W2F, W2F))
for kind, rid in (("evcal", X2["cal"]), ("address_book", X2["book"]), ("list", X2["list"])):
    sql("UPDATE fs_shares SET expires_at=? WHERE user_id=? AND node_id IN (SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?)", (PAST, BOB, kind, rid))
r = A.patch(B + f"/api/files/shares/{G2['fs']}", json={"expires_at": PAST})
check(r.ok, "2 expired: the folder share ends in the past (the file store's own route) " + r.text[:160])
# 2.644.0 (#5030): the watchdog (1 s here) may already have moved the project's own member share that ran out into obj_revoked
# (lf_own_stale, reason 'expired') before this count - on a slow CI runner it did (5 -> 4): such a row counts as ended too
ended = sql("SELECT count(*) FROM fs_shares WHERE user_id=? AND expires_at=?", (BOB, PAST))[0][0] + \
    sql("SELECT count(*) FROM obj_revoked WHERE src='fs_shares' AND user_id=? AND reason='expired' AND CAST(row_json AS TEXT) LIKE ?", (BOB, "%" + PAST[:10] + "%"))[0][0]
check(ended >= 5 and not sql("SELECT 1 FROM fs_shares WHERE user_id=? AND (expires_at IS NULL OR expires_at > ?)", (BOB, PAST)),
      f"2 expired: every core share of bob has its end date in the past (or ran out already) {ended}")
after(X2, "2 expired", ("wiki", "cal", "book", "files"))  # at once
# a project's role ends with the watchdog's next round (lists/lffolder.py lf_expire_tick: an expiry is no change the hooks see; every
# TASKS_WATCHDOG_INTERVAL seconds, 1 s here, 30 s by default) - then every way of the project is closed
check(kt.until(lambda: not sql("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (X2["list"], BOB)), timeout=20),
      "2 expired: the watchdog round ends bob's project role")
after(X2, "2 expired", ("list",))

# ================================================================== 3 left: an organisation's things (shared + what every member reads)
r = A.post(B + "/api/admin/orgs", json={"name": "Kestrel"})
assert r.status_code in (200, 201), r.text
K = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (K, ALICE))


def member(oid, role):
    r = A.put(B + f"/api/orgs/{oid}/members", json={"email": "bob@example.com", "role": role})
    check(r.ok and sql("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, BOB)) == [(role,)], f"setup: bob is {role} of {oid} {r.text[:160]}")


member(K, "member")
X3 = make("Lv", f"org:{K}")
grant(X3)
before(X3, "3 left")
check(A.delete(B + f"/api/orgs/{K}/members/{BOB}").ok, "3 left: bob leaves the organisation")
after(X3, "3 left")

# ================================================================== 4 back as a guest the same day: nothing of before comes back
member(K, "guest")
# 2.579.0 (#4293): coming back within a day brings the project memberships back (#3859, orgleave.py olv_rejoin) - not as a guest
check(not sql("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (X3["list"], BOB)), "4 back as a guest: no old project membership comes back")
after(X3, "4 back as a guest")

# ================================================================== 5 made a guest: what every member reads ends
member(K, "member")
X5 = make("Gs", f"org:{K}")
before(X5, "5 made a guest", ("wiki",))  # every member reads the organisation's knowledge pages, without a share
member(K, "guest")
after(X5, "5 made a guest", ("wiki",))

# ================================================================== 6 retired: a former member reads nothing of it
r = A.post(B + "/api/admin/orgs", json={"name": "Osprey"})
assert r.status_code in (200, 201), r.text
O = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (O, ALICE))
member(O, "member")
X6 = make("Rt", f"org:{O}", project=False)  # an organisation with projects is not retired (they move out first)
grant(X6)
before(X6, "6 retired")
A.patch(B + "/api/settings", json={"workspace": f"org:{O}"})
r = A.post(B + "/api/office/docs", json={"project_title": "Film night"})
check(r.status_code == 201, "6 retired: a document " + r.text[:160])
sql("UPDATE office_docs SET locked_at=?, status='issued', number='RE-2025-077', date='2025-11-20' WHERE id=?",
    (datetime.now(timezone.utc).isoformat(timespec="seconds"), r.json().get("id")))
check(not sql("SELECT 1 FROM lists WHERE org_id=?", (O,)), "6 retired: the organisation has no projects")
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.delete(B + f"/api/admin/orgs/{O}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True, "6 retired: the organisation is retired " + r.text[:200])
after(X6, "6 retired")

sys.exit(kt.done("p2579_d_revoke"))
