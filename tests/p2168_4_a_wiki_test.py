#!/usr/bin/env python3
"""2.210 A (#2755) API tests: a deep knowledge wiki (as exported by other wiki tools: many folder levels, long names,
folders that are a page too, mixed case, umlauts, spaces) is imported completely and every page is in the index.
 - limits: a page path may have up to 500 characters and 32 levels (was 200 / 12); 501 characters / 33 levels are refused
 - ZIP import: every page arrives, also 7+ levels deep and with paths longer than 200 characters; "Audio" and "Audio/Mix"
   (a folder that is a page too) and "audio/Recording" (other case) end up in one folder; a name stored as UTF-8 without the
   archive's UTF-8 mark (cp437 for Python's zipfile) keeps its umlauts; NFD umlauts become NFC
 - too long (> 500) / too deep (> 32 levels) paths are shortened, not skipped: listed in "shortened" ({name, path}) with
   "shortened_n", the folder of two shortened pages stays one folder, [[links]] to a shortened page get its new name;
   importing the same ZIP again with replace=1 replaces the same pages (the short names are stable)
 - two names that are the same after cleaning ("A#B" / "AB") both arrive, the second as "AB (2)"
 - spaces: a member of an organisation imports into the organisation's space (tenant-matrix: wiki), another organisation's
   member does not see those pages; a person without an organisation (freelancer-matrix: wiki) imports into the own private
   space and reads every page back
usage: p2168_4_a_wiki_test.py <datadir>"""
import io
import os
import subprocess
import sys
import time
import unicodedata
import zipfile

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
from kt import B, H, check, done, sess  # 2.210 (#2755): the shared helpers (check_layout: new suites use kt)

LONG = "Ein sehr langer Ordnername für Aufnahmen und Notizen"  # 52 characters
DEEP7 = "Audio/Mix/Mastering/Loudness/Targets/Streaming/Spotify"
L260 = "Wiki/" + "/".join([LONG] * 4) + "/Ende"  # about 225 characters: over the old limit, under the new one
L600 = "Archiv/" + "/".join([LONG + f" {i}" for i in range(11)])  # about 600 characters: shortened
D35 = "/".join(f"Ebene {i}" for i in range(35))  # 35 levels: shortened
PAGES = {  # path in the archive -> expected path in the space (None: shortened, checked separately)
    "Audio.md": "Audio",
    "Audio/Mix.md": "Audio/Mix",
    DEEP7 + ".md": DEEP7,
    "audio/Recording/Mics.md": "audio/Recording/Mics",
    "Claude/Apps/Kalmido/Releases/2.168/Notes/Part A.md": "Claude/Apps/Kalmido/Releases/2.168/Notes/Part A",
    unicodedata.normalize("NFD", "Privat/Ärzte/Zahnärztin Übersicht.md"): "Privat/Ärzte/Zahnärztin Übersicht",
    "Wiki/Leer zeichen/Seite  mit   Abständen (1) & Co.md": "Wiki/Leer zeichen/Seite mit Abständen (1) & Co",
    L260 + ".md": L260,
    L600 + "/Seite eins.md": None,
    L600 + "/Seite zwei.md": None,
    D35 + "/Tief.md": None,
    "A#B.md": "AB",
    "AB.md": "AB (2)",
    "Links.md": "Links",
}
CP437_NAME = "Übersicht/Grüße.md"  # stored as UTF-8 bytes without the UTF-8 mark
PLACE = "X" * len(CP437_NAME.encode())


def wiki_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name in PAGES:
            body = f"# {os.path.basename(name)[:-3]}\n\nText.\n"
            if name == "Links.md":
                body = f"Siehe [[{L600}/Seite eins]] und [[{L600}/Seite zwei|zwei]] und [[Audio/Mix]].\n"
            z.writestr(name, body)
        z.writestr(PLACE, "Grüße\n")
    raw = b.getvalue()
    assert raw.count(PLACE.encode()) == 2  # local header + central directory: same length, so offsets stay right
    return raw.replace(PLACE.encode(), CP437_NAME.encode())


def index(s, sp):
    r = s.get(B + "/api/wiki", params={"space": sp})
    assert r.ok, r.text
    return r.json()


def imp(s, sp, data, replace=False):
    p = {"space": sp, **({"replace": "1"} if replace else {})}
    r = s.post(B + "/api/wiki/import", params=p, files={"file": ("wiki.zip", data, "application/zip")})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


def check_import(s, sp, who):
    data = wiki_zip()
    st, j = imp(s, sp, data)
    check(st == 200, f"{who}: import answers 200 {st} {str(j)[:300]}")
    n_md = len(PAGES) + 1
    check(len(j.get("created") or []) == n_md, f"{who}: every page created ({len(j.get('created') or [])} of {n_md}); skipped {j.get('skipped_detail')}")
    check(j.get("skipped_n") == 0, f"{who}: nothing skipped {j.get('skipped_detail')}")
    sh = j.get("shortened") or []
    check(j.get("shortened_n") == 4 and len(sh) == 4, f"{who}: the two long, the deep and the doubled name are reported shortened {sh}")
    check(all(x.get("name") and x.get("path") for x in sh), f"{who}: a shortened entry names the archive name and the new path")
    idx = index(s, sp)
    paths = {p["path"] for p in idx["pages"]}
    check(not idx.get("more"), f"{who}: the index is complete")
    for name, want in PAGES.items():
        if want:
            check(want in paths, f"{who}: page {want[:80]!r} is in the index")
    check("Übersicht/Grüße" in paths, f"{who}: a UTF-8 name without the UTF-8 mark keeps its umlauts {sorted(p for p in paths if 'bersicht' in p)}")
    check(all(len(p) <= 500 and p.count("/") < 32 for p in paths), f"{who}: every path within 500 characters / 32 levels")
    longp = sorted(p for p in paths if p.startswith("Archiv/"))
    check(len(longp) == 2 and len({p.rsplit("/", 1)[0] for p in longp}) == 1, f"{who}: the two shortened pages share one folder {longp}")
    check(any(p.endswith("Seite eins") for p in longp) and any(p.endswith("Seite zwei") for p in longp), f"{who}: the page names stay readable {longp}")
    deep = [p for p in paths if p.startswith("Ebene 0/")]
    check(len(deep) == 1 and deep[0].count("/") == 31 and deep[0].endswith("Tief"), f"{who}: 35 levels become 32, the deeper ones join the page name {deep}")
    check(sum(p.lower().startswith("audio/") or p == "Audio" for p in paths) == 4, f"{who}: Audio, Audio/Mix, the deep page and audio/Recording/Mics")
    lk = next(p for p in idx["pages"] if p["path"] == "Links")
    body = s.get(B + f"/api/wiki/pages/{lk['id']}").json().get("body", "")
    check(all(f"[[{p}" in body for p in longp) and "[[Audio/Mix]]" in body, f"{who}: links to shortened pages get the new name {body[:400]!r}")
    pg = s.get(B + f"/api/wiki/pages/{lk['id']}").json()
    deep_id = next(p["id"] for p in idx["pages"] if p["path"] == DEEP7)
    check(s.get(B + f"/api/wiki/pages/{deep_id}").json().get("path") == DEEP7, f"{who}: the page 7 levels deep opens")
    check(isinstance(pg.get("backlinks"), list), f"{who}: the link page opens")
    # again with replace: the same pages, nothing new
    st, j2 = imp(s, sp, data, replace=True)
    check(st == 200 and not j2.get("created") and len(j2.get("updated") or []) == n_md, f"{who}: the same ZIP with replace=1 replaces the same pages {len(j2.get('created') or [])} new, {len(j2.get('updated') or [])} replaced")
    check(len(index(s, sp)["pages"]) == n_md, f"{who}: still {n_md} pages")
    return paths


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]

# ---- limits of a single page
FID, Fr = freelancer(B, A)
mk = lambda s, p: s.post(B + "/api/wiki/pages", json={"space": "private", "path": p, "body": "x"})
check(mk(Fr, "/".join(["Abschnitt " + "z" * 50] * 8) + "/" + "x" * 12).status_code == 201, "a path of 500 characters is taken")
check(mk(Fr, "y" * 501).status_code == 400, "501 characters are refused")
check(mk(Fr, "/".join(f"L{i}" for i in range(32))).status_code == 201, "32 levels are taken")
check(mk(Fr, "/".join(f"M{i}" for i in range(33))).status_code == 400, "33 levels are refused")
for p in Fr.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]:
    Fr.delete(B + f"/api/wiki/pages/{p['id']}")

# ---- freelancer-matrix: wiki -- a person without an organisation, the private space
check_import(Fr, "private", "freelancer")

# ---- tenant-matrix: wiki -- an organisation's space
me_bob = Bo.get(B + "/api/state").json()["me"]
SP = f"org:{ORG}"
if any(w.get("id") == ORG for w in me_bob.get("workspaces") or []):
    org_paths = check_import(Bo, SP, "member")
    check(Ca.get(B + "/api/wiki", params={"space": SP}).status_code in (403, 404), "another organisation's member cannot read the space")
    check(not any(p["path"] in org_paths for p in index(Ca, f"org:{ORG2}")["pages"]), "the other organisation's space has none of the pages")
else:
    check(False, f"setup: bob is a member of Alpha {me_bob.get('workspaces')}")

sys.exit(done("p2168_4_a_wiki"))
