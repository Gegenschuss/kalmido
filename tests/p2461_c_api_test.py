#!/usr/bin/env python3
"""2.46.1 API tests (part C), own container (start.sh).

 - #1554: several contacts at once (POST /api/contacts/bulk, /api/v1/contacts/bulk): delete and move 1,400 contacts in
   one request each (time measured), every contact checked first (a foreign id in the list -> 404, one in a read-only
   address book -> 403, nothing changes), a read-only or foreign target is refused, a contact the target has already
   stays where it is (conflicts), the birthday tasks follow (another birthday list: old ones to the trash, new ones made;
   deleted: to the trash), CardDAV sees the change (the card is gone, the ctag moves), the token API needs "contacts"
"""
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def ids_of(s, bid):
    r = s.get(B + f"/api/contacts?book_id={bid}&limit=2000")
    assert r.ok, r.text
    return sorted(x["id"] for x in r.json()["items"])


def vcf(prefix, n, bday=None):
    out = []
    for i in range(n):
        out += ["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:{prefix.title()} Person {i}", f"N:Person {i};{prefix.title()};;;",
                f"EMAIL;TYPE=HOME:{prefix}{i}@example.org", *([f"BDAY:{bday}"] if bday else []), "END:VCARD"]
    return "\r\n".join(out) + "\r\n"


def tasks_in(s, lid, trashed=False):
    if trashed:  # the token API lists the trash
        r = requests.get(B + f"/api/v1/trash?list_id={lid}", headers=tok(["read"]))
        assert r.ok, r.text
        return r.json()["data"]
    return [t for t in s.get(B + "/api/state").json()["tasks"] if t["list_id"] == lid]


def tok(scopes):
    r = A.post(B + "/api/me/tokens", json={"name": "t" + str(time.time()), "scopes": scopes})
    return {"Authorization": "Bearer " + r.json()["token"]}


def bulk(s, **b):
    return s.post(B + "/api/contacts/bulk", json=b)


if not os.environ.get("KMT_NOSTART"):  # KMT_NOSTART=1: against an app that already runs (a quick local check)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["contacts", "family"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
uids = {}
for u in ("bob", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.org"})
    assert r.ok, r.text
    uids[u] = r.json()["id"]
Bo, Ev = sess("bob"), sess("eve")
for s_ in (Bo, Ev):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def book(s, name):
    r = s.post(B + "/api/books", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== #1554: 1,400 contacts moved + deleted in one request each
A1, A2, A3 = book(A, "Import"), book(A, "Family"), book(A, "Work")
r = A.post(B + f"/api/books/{A1}/import", files={"file": ("big.vcf", vcf("imp", 1400).encode(), "text/vcard")})
check(r.ok and r.json().get("created") == 1400, f"#1554: 1,400 contacts imported {r.status_code} {r.text[:200]}")
big = ids_of(A, A1)
t0 = time.time()
r = bulk(A, action="move", ids=big, book_id=A3)
dt = time.time() - t0
# 2.139.1 (#2378): the answer also counts the contacts copied out of a mirrored address book
check(r.ok and r.json() == {"action": "move", "moved": 1400, "unchanged": 0, "conflicts": [], "copied": 0}, f"#1554: 1,400 moved {r.status_code} {r.text[:200]}")
check(dt < 15, f"#1554: moving 1,400 contacts takes {dt:.1f}s (< 15s)")
print(f"#1554: move 1400 in {dt:.2f}s", flush=True)
check(ids_of(A, A1) == [] and ids_of(A, A3) == big, "#1554: they are all in the target now")
r = bulk(A, action="move", ids=big[:5], book_id=A3)
check(r.ok and r.json()["moved"] == 0 and r.json()["unchanged"] == 5, f"#1554: moving into the same book changes nothing {r.text[:200]}")
t0 = time.time()
r = bulk(A, action="delete", ids=big)
dt = time.time() - t0
check(r.ok and r.json() == {"action": "delete", "deleted": 1400}, f"#1554: 1,400 deleted {r.status_code} {r.text[:200]}")
check(dt < 15, f"#1554: deleting 1,400 contacts takes {dt:.1f}s (< 15s)")
print(f"#1554: delete 1400 in {dt:.2f}s", flush=True)
check(ids_of(A, A3) == [], "#1554: the book is empty")

# ================================================================== #1554: rights, checked before anything changes
BV, BE = book(Bo, "Bob view"), book(Bo, "Bob edit")
EV = book(Ev, "Eve")
check(Bo.put(B + f"/api/books/{BV}/members", json={"user_id": 1, "role": "view"}).ok, "#1554: Bob shares a book with Alice (view)")
check(Bo.put(B + f"/api/books/{BE}/members", json={"user_id": 1, "role": "edit"}).ok, "#1554: and one with edit")
for s_, bid, p in ((A, A1, "own"), (Bo, BV, "bview"), (Bo, BE, "bedit"), (Ev, EV, "eve")):
    r = s_.post(B + f"/api/books/{bid}/import", files={"file": (p + ".vcf", vcf(p, 3).encode(), "text/vcard")})
    assert r.ok and r.json().get("created") == 3, r.text
own, bview, bedit, eve = ids_of(A, A1), ids_of(Bo, BV), ids_of(Bo, BE), ids_of(Ev, EV)
r = bulk(A, action="delete", ids=own + eve[:1])
check(r.status_code == 404, f"#1554: own + one foreign id -> 404 {r.status_code}")
check(ids_of(A, A1) == own and ids_of(Ev, EV) == eve, "#1554: ... and nothing was deleted (no partial damage)")
r = bulk(A, action="move", ids=own + eve[:1], book_id=A2)
check(r.status_code == 404 and ids_of(A, A1) == own and ids_of(Ev, EV) == eve, f"#1554: moving with a foreign id: 404, nothing moved {r.status_code}")
r = bulk(A, action="delete", ids=own + bview[:1])
check(r.status_code == 403 and ids_of(A, A1) == own and ids_of(Bo, BV) == bview, f"#1554: one in a read-only book -> 403, nothing deleted {r.status_code}")
r = bulk(A, action="move", ids=own, book_id=BV)
check(r.status_code == 403 and ids_of(A, A1) == own, f"#1554: a read-only target -> 403 {r.status_code}")
r = bulk(A, action="move", ids=own, book_id=EV)
check(r.status_code == 404 and ids_of(A, A1) == own and ids_of(Ev, EV) == eve, f"#1554: a foreign target -> 404 {r.status_code}")
r = bulk(Ev, action="delete", ids=own)
check(r.status_code == 404 and ids_of(A, A1) == own, f"#1554: Eve cannot delete Alice's contacts {r.status_code}")
r = bulk(A, action="move", ids=own[:1] + bedit[:1], book_id=BE)
check(r.ok and r.json()["moved"] == 1 and r.json()["unchanged"] == 1, f"#1554: into a book shared with edit {r.text[:200]}")
check(len(ids_of(Bo, BE)) == 4, "#1554: Bob sees the moved contact")
r = bulk(A, action="delete", ids=bedit[1:])
check(r.ok and r.json()["deleted"] == 2 and len(ids_of(Bo, BE)) == 2, f"#1554: deleting in an edit-shared book {r.text[:200]}")
for b_, code, what in (({"action": "delete", "ids": []}, 400, "no ids"), ({"action": "zap", "ids": own}, 400, "an unknown action"),
                       ({"action": "delete", "ids": own, "x": 1}, 400, "an unknown field"), ({"action": "delete", "ids": ["a"]}, 400, "a bad id"),
                       ({"action": "move", "ids": own}, 400, "move without book_id"), ({"action": "delete", "ids": list(range(1, 5003))}, 400, "too many ids")):
    r = bulk(A, **b_)
    check(r.status_code == code, f"#1554: {what} -> {code} ({r.status_code} {r.text[:120]})")

# ================================================================== #1554: same UID in the target stays where it is
r = A.post(B + f"/api/books/{A2}/import", files={"file": ("dup.vcf", vcf("own", 3).encode(), "text/vcard")})
own = ids_of(A, A1)
r = bulk(A, action="move", ids=own, book_id=A2)
j = r.json() if r.ok else {}
check(r.ok and j.get("moved") == 0 and sorted(j.get("conflicts", [])) == own, f"#1554: the contact the target has already is listed in conflicts {r.text[:200]}")
check(ids_of(A, A1) == j.get("conflicts"), "#1554: ... and stays in its book")

# ================================================================== #1554: birthday tasks follow
BL1 = A.post(B + "/api/lists", json={"name": "Birthdays 1"}).json()["id"]
BL2 = A.post(B + "/api/lists", json={"name": "Birthdays 2"}).json()["id"]
F1, F2, F3 = book(A, "Bday 1"), book(A, "Bday 2"), book(A, "Bday 2b")
check(A.patch(B + f"/api/books/{F1}", json={"birthdays_list_id": BL1}).ok and A.patch(B + f"/api/books/{F2}", json={"birthdays_list_id": BL2}).ok
      and A.patch(B + f"/api/books/{F3}", json={"birthdays_list_id": BL2}).ok, "#1554: books with birthday lists")
A.post(B + f"/api/books/{F1}/import", files={"file": ("b.vcf", vcf("bd", 3, "1980-05-12").encode(), "text/vcard")})
bd = ids_of(A, F1)
check(len(tasks_in(A, BL1)) == 3, f"#1554: three birthday tasks in list 1 {len(tasks_in(A, BL1))}")
r = bulk(A, action="move", ids=bd, book_id=F2)
check(r.ok and r.json()["moved"] == 3, f"#1554: birthdays moved to a book with another list {r.text[:200]}")
check(len(tasks_in(A, BL1)) == 0 and len(tasks_in(A, BL2)) == 3, f"#1554: the old tasks went, the new list has them {len(tasks_in(A, BL1))} {len(tasks_in(A, BL2))}")
check(len(tasks_in(A, BL1, trashed=True)) == 3, "#1554: the old birthday tasks are in the trash (restorable)")
before = sorted(t["id"] for t in tasks_in(A, BL2))
r = bulk(A, action="move", ids=bd, book_id=F3)
check(r.ok and sorted(t["id"] for t in tasks_in(A, BL2)) == before, "#1554: the same birthday list: the tasks stay as they are")
r = bulk(A, action="delete", ids=bd[:2])
check(r.ok and len(tasks_in(A, BL2)) == 1, f"#1554: deleting contacts trashes their birthday tasks {len(tasks_in(A, BL2))}")
r = A.delete(B + f"/api/contacts/{bd[2]}")
check(r.ok and len(tasks_in(A, BL2)) == 0, "#1554: the single delete does the same")
A.post(B + f"/api/books/{F1}/import", files={"file": ("b2.vcf", vcf("bs", 1, "--07-01").encode(), "text/vcard")})
one = ids_of(A, F1)[0]
r = A.patch(B + f"/api/contacts/{one}", json={"book_id": F2})
check(r.ok and len(tasks_in(A, BL1)) == 0 and len(tasks_in(A, BL2)) == 1, "#1554: the single move to another birthday list does the same")

# ================================================================== #1554: CardDAV sees it
PW = A.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
dav = requests.Session()
dav.auth = ("alice", PW)
A.post(B + f"/api/books/{A3}/import", files={"file": ("d.vcf", vcf("dav", 4).encode(), "text/vcard")})
PF = '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/"><d:prop><cs:getctag/></d:prop></d:propfind>'


def ctag(bid):
    r = dav.request("PROPFIND", B + f"/dav/addressbooks/alice/b{bid}/", data=PF, headers={"Depth": "0"})
    m = re.search(r"getctag[^>]*>([^<]+)<", r.text)
    return m.group(1) if m else None


c0 = ctag(A3)
check(dav.get(B + f"/dav/addressbooks/alice/b{A3}/dav-0.vcf").status_code == 200, "#1554: CardDAV has the card")
time.sleep(0.01)
dd = ids_of(A, A3)
r = bulk(A, action="delete", ids=dd[:2])
check(r.ok and dav.get(B + f"/dav/addressbooks/alice/b{A3}/dav-0.vcf").status_code == 404, "#1554: after the bulk delete CardDAV has it no more")
check(c0 and ctag(A3) != c0, f"#1554: the address book's ctag moved {c0}")

# ================================================================== #1554: token API (scope contacts)
V = B + "/api/v1"
r = requests.post(V + "/contacts/bulk", headers=tok(["read"]), json={"action": "delete", "ids": dd[2:3]})
check(r.status_code == 403 and len(ids_of(A, A3)) == 2, f"#1554: v1 without the scope contacts: 403 {r.status_code}")
r = requests.post(V + "/contacts/bulk", headers=tok(["read", "contacts"]), json={"action": "move", "ids": dd[2:], "book_id": A2})
check(r.ok and r.json().get("moved") == 2, f"#1554: v1 bulk move with the scope contacts {r.status_code} {r.text[:200]}")
r = requests.post(V + "/contacts/bulk", headers=tok(["read", "contacts"]), json={"action": "delete", "ids": own + eve[:1]})
check(r.status_code == 404, f"#1554: v1: a foreign id -> 404 {r.status_code}")
spec = requests.get(V + "/openapi.json", headers=tok(["read"])).json()
check(spec["paths"].get("/contacts/bulk", {}).get("post", {}).get("x-kalmido-scope") == "contacts", "#1554: OpenAPI: /contacts/bulk needs contacts")

# 2.46.1 review: an agent's bulk change of 10 or more contacts waits for a person's approval (202), a smaller one runs
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "contacts"], "username": "bookbot", "display_name": "Book bot"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x")}
AB = A.post(B + "/api/books", json={"name": "Agent book"}).json()["id"]
for bid in (AB, A2):
    A.put(B + f"/api/books/{bid}/members", json={"user_id": ag.get("id"), "role": "edit"})
A.post(B + f"/api/books/{AB}/import", files={"file": ("ag.vcf", vcf("agb", 12).encode(), "text/vcard")})
ag_ids = ids_of(A, AB)
r = requests.post(V + "/contacts/bulk", headers=AGH, json={"action": "delete", "ids": ag_ids})
check(r.status_code == 202 and len(ids_of(A, AB)) == 12, f"review: an agent deleting 12 contacts waits for approval {r.status_code} {r.text[:160]}")
r = requests.post(V + "/contacts/bulk", headers=AGH, json={"action": "move", "ids": ag_ids, "book_id": A2})
check(r.status_code == 202 and len(ids_of(A, AB)) == 12, f"review: an agent moving 12 contacts waits for approval {r.status_code}")
r = requests.post(V + "/contacts/bulk", headers=AGH, json={"action": "delete", "ids": ag_ids[:2]})
check(r.ok and len(ids_of(A, AB)) == 10, f"review: an agent deleting 2 contacts runs at once {r.status_code} {r.text[:160]}")

print(f"p2461_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
