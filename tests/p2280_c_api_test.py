#!/usr/bin/env python3
"""2.280.0 C API tests (#3114, own container): the knowledge pages' texts in pages, a search that writes nothing, a big
folder renamed in a few statements. Invented pages only.
freelancer-matrix: wiki
 - GET /api/wiki?offline=1&bodies=1&bn=<n>: the index with the first n texts and the cursor bnext; ?nolist=1&bafter=<cursor>
   the next texts only -- together exactly the texts of one answer without bn (also with since=); an open space without
   offline=1 gets no texts (400), a bad cursor 400, another organisation's space stays closed (403/404)
 - GET /api/wiki/search over pages whose word index is old (a folder renamed): the same hits as after the background job
   indexed them; the statements do not grow with the number of such pages (before: the GET indexed up to 300 pages);
   the background job indexes every page of the space
 - POST /api/wiki/move of a folder with 300 pages: complete (every page under the new name, the links to them follow, the
   relinked count as before), the statements do not grow per page; a taken name still answers 409
 - a person without an organisation: the same in the private space; nobody else reads it
usage: p2280_c_api_test.py <datadir>      (P2280C_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import re
import sys

from freelancer_fixture import freelancer
from kt import B, FAILS, OKS, check, dbx, done, fresh, sess, setup, until  # 2.206.0 (#2762): shared helpers (tests/kt.py)

TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def page(s, sp, path, body):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": body})
    assert r.ok, r.text
    return r.json()["id"]


def idx(s, sp, **kw):
    r = s.get(B + "/api/wiki", params={"space": sp, "bodies": "1", **kw})
    return r.status_code, (r.json() if r.ok else {})


def paged(s, sp, bn, **kw):
    """Every text through the pages of bn: (index answer, {id: text}, number of answers)."""
    st, j = idx(s, sp, offline="1", bn=str(bn), **kw)
    assert st == 200, st
    got = {p["id"]: p["body"] for p in j["pages"] if "body" in p}
    nx, n = j.get("bnext"), 1
    while nx and n < 50:
        st, k = idx(s, sp, offline="1", bn=str(bn), nolist="1", bafter=nx, **kw)
        assert st == 200 and "pages" not in k, (st, k)
        for i, b in k["bodies"].items():
            assert int(i) not in got, ("twice", i)
            got[int(i)] = b
        nx, n = k.get("bnext"), n + 1
    return j, got, n


def search(s, sp, q, **kw):
    r = s.get(B + "/api/wiki/search", params={"space": sp, "q": q, "limit": "100", **kw})
    assert r.ok, r.text
    j = r.json()
    return [p["id"] for p in j["pages"]], j["total"], nstmt(r)


def stale(ids):
    """Pages of ids whose word index is missing or older than the page (what the search's background job indexes)."""
    if not ids:
        return 0
    q = ",".join(str(int(i)) for i in ids)
    return dbx(f"SELECT COUNT(*) FROM wiki_pages p WHERE p.id IN ({q}) AND NOT EXISTS (SELECT 1 FROM wiki_words x "
               "WHERE x.page_id=p.id AND x.h = 'u:' || p.updated_at)")[0][0]


fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, "P2280C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"

# ---------------------------------------------------------------- the texts in pages (bn / bafter / nolist)
ids = [page(A, SP, f"Pg/{n}", f"Text {n} papaya") for n in ("b", "A", "c", "d", "E")]
st, full = idx(A, SP, offline="1")
want = {p["id"]: p["body"] for p in full["pages"]}
check(st == 200 and set(want) == set(ids), f"setup: five pages with texts {st}")
j, got, n = paged(A, SP, 2)
check(got == want and n == 3, f"bn=2: three answers, together every text of the one answer without bn ({n})")
check([p["id"] for p in j["pages"]] == [p["id"] for p in full["pages"]] and j.get("more") is False,
      "bn: the index itself is the same (every page, the same order)")
check(sum("body" in p for p in j["pages"]) == 2 and j.get("bnext"), "bn: the first answer carries the first two texts and the cursor")
j, got, n = paged(A, SP, 500)
check(got == want and n == 1 and j.get("bnext") == "", "bn=500: one answer, no cursor")
since = max(p["updated_at"] for p in full["pages"])
check(A.patch(B + f"/api/wiki/pages/{ids[2]}", json={"body": "Text c changed"}).ok, "setup: a text changed")
st, ws = idx(A, SP, offline="1", since=since)
wsb = {p["id"]: p["body"] for p in ws["pages"] if "body" in p}
j, got, n = paged(A, SP, 1, since=since)
check(got == wsb and got.get(ids[2]) == "Text c changed", f"since + bn: the same texts as since without bn {sorted(got)} {sorted(wsb)}")
st, _ = idx(A, SP, bn="2", nolist="1")
check(st == 400, f"an open space without offline=1: no texts in pages either ({st})")
st, _ = idx(A, SP, offline="1", bn="2", nolist="1", bafter="x:abc")
check(st == 400, f"a bad cursor: 400 ({st})")
st, k = idx(A, SP, offline="1", bn="2", nolist="1", bafter="0:' OR 1=1 --")
check(st == 200 and isinstance(k.get("bodies"), dict), f"a strange cursor path is only compared, never run ({st})")
A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG2]})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
st, k = idx(Bo, SP, offline="1", bn="2", nolist="1")
check(st in (403, 404) and not k.get("bodies"), f"another organisation's space: closed for the texts in pages ({st})")


# ---------------------------------------------------------------- search over an old index + a big folder renamed
def big(s, sp, who):
    """30 pages renamed (old index), the search; 270 more, renamed, the search: statements per size; the job; the hits."""
    link = page(s, sp, "Links", "See [[Big/Page 001]] and [[big/page 002|two]] and [[Big/Page 003#top]].")
    mine = [page(s, sp, f"Big/Page {i:03d}", f"Note {i} kiwi" + (" mangoes" if i % 3 == 0 else "")) for i in range(30)]
    r = s.post(B + "/api/wiki/move", json={"space": sp, "from": "Big", "to": "Mid"})
    m30 = nstmt(r)
    check(r.ok and len(r.json()["moved"]) == 30 and r.json()["relinked"] == 3, f"{who}: 30 pages renamed, the links follow {r.status_code} {r.text[:200]}")
    check(stale(mine) == 30, f"{who}: the renamed pages' index is old now (the setup of the next checks)")
    h30, t30, s30 = search(s, sp, "kiwi")
    check(t30 == 30 and set(h30) == set(mine), f"{who}: an old index: the words of the text are found anyway ({t30})")
    hm, tm, _ = search(s, sp, "mango")
    check(tm == 10 and set(hm) == {p for i, p in enumerate(mine) if i % 3 == 0}, f"{who}: a word start (prefix) in an old index ({tm})")
    mine += [page(s, sp, f"Mid/Page {i:03d}", f"Note {i} kiwi" + (" mangoes" if i % 3 == 0 else "")) for i in range(30, 300)]
    r = s.post(B + "/api/wiki/move", json={"space": sp, "from": "Mid", "to": "Big"})
    m300 = nstmt(r)
    mv = r.json() if r.ok else {}
    check(r.ok and len(mv.get("moved", [])) == 300 and mv.get("relinked") == 3, f"{who}: 300 pages renamed, the links follow {r.status_code}")
    check(m300 <= m30 + 12, f"{who}: renaming 300 pages does not cost more statements than 30 (30: {m30}, 300: {m300})")
    st, j = idx(s, sp)
    paths = {p["id"]: p["path"] for p in j["pages"]}
    check(all(paths.get(p, "").startswith("Big/Page ") for p in mine) and not any(x.startswith("Mid/") for x in paths.values()),
          f"{who}: every page under the new name, none under the old")
    lb = s.get(B + f"/api/wiki/pages/{link}").json().get("body", "")
    check("[[Big/Page 001]]" in lb and "[[Big/Page 002|two]]" in lb and "[[Big/Page 003#top]]" in lb, f"{who}: the links follow the folder {lb}")
    h1, t1, s300 = search(s, sp, "kiwi")
    check(t1 == 300 and len(h1) == 100 and set(h1) <= set(mine), f"{who}: 300 pages with an old index: every hit counted ({t1})")
    check(s300 <= s30 + 6, f"{who}: the search's statements do not grow with the pages of an old index (30: {s30}, 300: {s300})")
    hp1, tp1, _ = search(s, sp, "page mango")
    check(until(lambda: stale(mine) == 0, timeout=60), f"{who}: the background job indexed every page ({stale(mine)} left)")
    h2, t2, _ = search(s, sp, "kiwi")
    hp2, tp2, _ = search(s, sp, "page mango")
    check((h1, t1) == (h2, t2) and (hp1, tp1) == (hp2, tp2) and tp2 == 100, f"{who}: the same hits and order before and after the index job ({tp1} {tp2})")
    h3, t3, _ = search(s, sp, "kiwi", offset="100")
    check(t3 == 300 and len(h3) == 100 and not set(h3) & set(h2), f"{who}: the next page of hits")
    hz, tz, _ = search(s, sp, "")
    check(tz == len(paths) and hz[0] in mine, f"{who}: an empty query: the pages changed last ({tz} of {len(paths)})")
    page(s, sp, "Other/Page 001", "taken")
    r = s.post(B + "/api/wiki/move", json={"space": sp, "from": "Big", "to": "Other"})
    check(r.status_code == 409 and "Other/Page 001" in r.json().get("taken", []), f"{who}: a taken name: 409 as before {r.status_code}")
    return mine


big(A, SP, "organisation")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: wiki)
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
fm = big(Fr, "private", "freelancer")
j, got, n = paged(Fr, "private", 100)
check(n == 4 and len(got) == len(j["pages"]) == 302, f"freelancer: the private texts in pages of 100 ({n}, {len(got)})")
st, j = idx(A, "private", offline="1", bn="100")
check(st == 200 and not set(p["id"] for p in j.get("pages", [])) & set(fm), "freelancer: nobody else's private space shows the pages")
h, t, _ = search(A, "", "kiwi")
check(not set(h) & set(fm), "freelancer: another account's search never finds the private pages")
# ---------------------------------------------------------------- 2.280.0 (#3114, review): a page whose stored text looks sealed
# ('e2e1:', older data in an open space) gets no index mark - the background job must end anyway (before: an endless loop),
# and a waiting job of one space must not swallow the job of another space (once per space).
sealed = page(A, SP, "Sealed/One", "plain papaya")
dbx("UPDATE wiki_pages SET body=? WHERE id=?", ("e2e1:QUJDREVGR0g=", sealed))
dbx("DELETE FROM wiki_words WHERE page_id=?", (sealed,))
dbx("DELETE FROM bg_jobs WHERE kind='wiki:index'")
search(A, SP, "papaya")
check(until(lambda: dbx("SELECT COUNT(*) FROM bg_jobs WHERE kind='wiki:index' AND state IN ('wait', 'run')")[0][0] == 0
            and dbx("SELECT COUNT(*) FROM bg_jobs WHERE kind='wiki:index'")[0][0] >= 1, timeout=60),
      "a page with a sealed-looking text: the index job ends (no endless loop)")
hs, ts, _ = search(A, SP, "QUJDREVGR0g")
check(sealed not in hs, f"a sealed-looking text gives no search words ({ts})")
dbx("DELETE FROM bg_jobs WHERE kind='wiki:index'")
dbx("INSERT INTO bg_jobs(kind, org_id, user_id, payload, state, attempts, run_after, created_at) "
    "VALUES('wiki:index', ?, NULL, '', 'wait', 0, '2999-01-01T00:00:00', '2026-01-01T00:00:00')", (ORG2,))
dbx("DELETE FROM wiki_words WHERE page_id=?", (ids[0],))
search(A, SP, "papaya")
check(dbx("SELECT COUNT(*) FROM bg_jobs WHERE kind='wiki:index' AND org_id=?", (ORG,))[0][0] >= 1,
      "a waiting index job of another space does not swallow this space's job")
dbx("DELETE FROM bg_jobs WHERE kind='wiki:index' AND org_id=?", (ORG2,))


sys.exit(done("p2280_c_api"))
