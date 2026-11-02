#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.3 (#3138): measurement - POST /api/wiki/move of a knowledge folder with 2.000 and 10.000 pages (decision 28.10.2026:
above 5 s the big move becomes a background job, else the task is closed with the values). Own container. Invented pages only.
freelancer-matrix: wiki
 - pages filled by SQL (a text of about 1 KB, every 10th page links to a page of the folder, 40 pages outside link into it)
 - PERF lines: wall time, database time and statements (Server-Timing) and answer size of a rename and of a move into another
   folder, for 2.000 and 10.000 pages (organisation space) and 2.000 pages (a person without an organisation)
 - every page is under the new name afterwards, the links follow (relinked count)
usage: p3138_wiki_move_measure_test.py <datadir>   (P3138_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import re
import sys
import time

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup

TIMING = re.compile(r'db;dur=([\d.]+);desc="n=(\d+)"')
LIMIT_S = 5.0
BODY = ("Shot list notes for the morning block. Lens choices, light setup and the order of the scenes are written down "
        "here so the crew can prepare. ") * 8


def timing(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return (float(m.group(1)), int(m.group(2))) if m else (-1.0, -1)


def page(s, sp, path, body):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": body})
    assert r.ok, r.text
    return r.json()["page"]["id"] if "page" in r.json() else r.json()["id"]


COLS = None


def fill(tpl, folder, n):
    """n copies of page tpl under folder/Page NNNNN (every 10th links to its neighbour inside the folder, link rows too)."""
    global COLS
    if COLS is None:
        COLS = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='wiki_pages' "
                                  "AND column_name<>'id' ORDER BY ordinal_position")]
    sel = []
    for col in COLS:
        if col == "path":
            sel.append(f"'{folder}/Page ' || lpad(g::text, 5, '0')")
        elif col == "body":
            sel.append(f"CASE WHEN mod(g, 10) = 0 THEN body || ' See [[{folder}/Page ' || lpad((g-1)::text, 5, '0') || ']].' ELSE body END")
        elif col == "title":
            sel.append("'Page ' || lpad(g::text, 5, '0')")
        else:
            sel.append(col)
    dbx(f"INSERT INTO wiki_pages({','.join(COLS)}) SELECT {','.join(sel)} FROM wiki_pages, generate_series(1, {int(n)}) g "
        f"WHERE id={int(tpl)}")
    dbx(f"INSERT INTO wiki_links(from_id, to_path) SELECT id, lower('{folder}/Page ' || lpad((CAST(substring(path from 'Page ([0-9]+)$') AS int) - 1)::text, 5, '0')) "
        f"FROM wiki_pages WHERE path LIKE '{folder}/Page %' AND mod(CAST(substring(path from 'Page ([0-9]+)$') AS int), 10) = 0")


def move(s, sp, src, dst, n, who):
    t0 = time.monotonic()
    r = s.post(B + "/api/wiki/move", json={"space": sp, "from": src, "to": dst}, timeout=600)
    wall = time.monotonic() - t0
    dbms, ns = timing(r)
    j = r.json() if r.ok else {}
    check(r.ok and len(j.get("moved", [])) == n, f"{who}: {n} pages {src} -> {dst} {r.status_code} {r.text[:200] if not r.ok else ''}")
    print(f"PERF #3138 {who} {n} pages {src} -> {dst}: {wall:.2f} s wall, db {dbms:.0f} ms, {ns} statements, "
          f"answer {len(r.content) / 1e6:.2f} MB, relinked {j.get('relinked')} (limit {LIMIT_S:.0f} s: "
          f"{'OVER' if wall > LIMIT_S else 'under'})", flush=True)
    return wall, j


def run(s, sp, who, sizes):
    tpl = page(s, sp, f"Tpl {who}", BODY)
    for n in sizes:
        f = f"Big{n}"
        fill(tpl, f, n)
        for i in range(40):  # pages outside the folder that link into it
            page(s, sp, f"Out{n}/Link {i:02d}", f"See [[{f}/Page {i + 1:05d}]] for the scene.")
        w1, j1 = move(s, sp, f, f"{f}x", n, who)
        check(j1.get("relinked", 0) == 40 + n // 10, f"{who}: the links into and inside the folder follow ({j1.get('relinked')})")
        inner = dbx("SELECT COUNT(*) FROM wiki_pages WHERE deleted_at IS NULL AND path LIKE ? AND body LIKE ?", (f + "x/%", f"%[[{f}x/Page %"))[0][0]
        check(inner == n // 10, f"{who}: the links inside the moved folder point to the new name ({inner})")
        left = dbx("SELECT COUNT(*) FROM wiki_pages WHERE deleted_at IS NULL AND path LIKE ?", (f + "/%",))[0][0]
        check(left == 0, f"{who}: no page left under the old name ({left})")
        w2, _ = move(s, sp, f"{f}x", f"Archive/{f}", n, who)
        RES.append((who, n, w1, w2))


RES = []
fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, "P3138")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
run(A, f"org:{ORG}", "organisation", (2000, 10000))
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
run(Fr, "private", "freelancer", (2000,))
print("RESULT #3138 " + "; ".join(f"{w} {n}: rename {a:.2f} s, move {b:.2f} s" for w, n, a, b in RES), flush=True)
sys.exit(done("p3138_wiki_move_measure"))
