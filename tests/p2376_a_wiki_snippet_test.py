#!/usr/bin/env python3
# kalmido-suite:
"""2.376 A API tests (#3292), own container (start.sh) with a server key (encryption at rest on). Invented names and texts only.
 - the hits of the knowledge search carry a snippet around the first word found in the text: plain text (no Markdown, no
   frontmatter, no HTML), about two lines, "…" where it is cut, cut at word boundaries, marks [[start, end]] on the query
   words (case and umlauts folded like the index: "kuhlschrank" finds "Kühlschrank", "STRASSE" finds "Straße")
 - a word of 4+ characters also at the beginning of a longer word, a shorter one only whole
 - only the hits of the page shown (limit / offset) and only pages one may read: another organisation finds nothing and
   gets no snippet; a name-only hit has none; a page whose text cannot be opened is found by its name, without a snippet and
   without an error; a space with the lock gives no hits from the server (the browser cuts there)
 - nothing is stored or logged: the server's log and the word index never hold the snippet's words
usage: p2376_a_wiki_snippet_test.py <datadir>      (P2321A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if write:
            c.execute(q, args)
            c.commit()
            return None
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def page(s, space, path, text=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def search(s, q, **kw):
    r = s.get(B + "/api/wiki/search", params={"q": q, **kw})
    assert r.ok, r.text
    return r.json()


def hit(j, pid):
    return next((p for p in j.get("pages", []) if p["id"] == pid), None)


def bold(p):
    return [p["snippet"][a:b] for a, b in p.get("marks", [])]


if os.environ.get("P2321A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"
code = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "encrypt-wiki"],
                      capture_output=True, text=True, timeout=300).returncode
check(code == 0, "setup: encrypt-wiki (the texts sealed at rest)")

# ================================================================ the snippet around the first hit
FILL = " ".join(f"wort{i:03d}" for i in range(80))  # 80 distinct words: every word of a snippet must be one of them
TXT = ("---\ntags: [kueche]\n---\n# Einkauf im Laden\n\n" + FILL + " Hier steht der **Kühlschrank** an der [[Plan/Straße|Straße]] "
       "mit [einem Link](https://example.com/x) und `Code` am Ende. " + FILL.replace("wort", "zeile"))
P1 = page(Bo, SP, "Haushalt/Notizen", TXT)
check(sql("SELECT body FROM wiki_pages WHERE id=?", (P1,))[0][0].startswith("kenc1:"), "setup: the text is sealed in the database")
j = search(Bo, "kuhlschrank")
p = hit(j, P1)
check(p and p.get("snippet"), "a text hit has a snippet " + str(p)[:300])
sn = p.get("snippet", "") if p else ""
check(bold(p) == ["Kühlschrank"] if p else False, "the mark is the word as written (umlaut, capital) " + str(p and bold(p)))
check(sn.startswith("…") and sn.endswith("…"), "cut on both sides: '…' at the edges " + sn)
check(120 <= len(sn) <= 190, "about two lines (120-190 characters) " + str(len(sn)))
check(not any(x in sn for x in ("**", "[[", "](", "`", "#", "---", "https://")), "plain text: no Markdown marks, no link targets " + sn)
check("Straße" in sn and "einem Link" in sn, "link labels stay as text " + sn)
inner = sn.strip("…").split(" ")
known = set(FILL.split(" ")) | set(FILL.replace("wort", "zeile").split(" ")) | set("Hier steht der Kühlschrank an Straße mit einem Link und Code am Ende.".split(" "))
check(all(w in known for w in inner), "cut at word boundaries (no half word at the edges) " + str([w for w in inner if w not in known]))
a = sn.index("Kühlschrank")
check(30 <= a <= 110, "the hit sits in the first part of the snippet, with words before it " + str(a))

# folding like the index: capitals, ß = ss, two words, short words whole only
p = hit(search(Bo, "STRASSE kühl"), P1)
check(p and sorted(bold(p)) == ["Kühl", "Straße"], "STRASSE finds Straße, kühl the beginning of Kühlschrank, both bold " + str(p and bold(p)))
P2 = page(Bo, SP, "Kurz/Abc", "Ein ab und abseits davon")
p = hit(search(Bo, "ab", space=SP), P2)
check(p and bold(p) == ["ab"], "a word of 2-3 characters is marked only whole (not in 'abseits') " + str(p and bold(p)))
check(p and p["snippet"] == "Ein ab und abseits davon", "a short text whole, without '…' " + str(p and p["snippet"]))
P3 = page(Bo, SP, "Einleitung", "Der Fischotter wohnt am Fluss. " + FILL)
p = hit(search(Bo, "fischotter"), P3)
check(p and p["snippet"].startswith("Der Fischotter") and p["snippet"].endswith("…"), "a hit near the beginning: from the beginning, '…' only at the end " + str(p and p["snippet"])[:80])

# a name-only hit has no snippet
P4 = page(Bo, SP, "Mondfisch Ablage", "Nur ein anderer Satz ohne das Suchwort.")
p = hit(search(Bo, "mondfisch"), P4)
check(p is not None and "snippet" not in p and "marks" not in p, "a hit by its name only: no snippet " + str(p))
# HTML in a text: the server gives plain text (the browser escapes), tags left out
P5 = page(Bo, SP, "Html", "Achtung <script>alert(1)</script> Laternenpfahl & Co <b>dick</b>")
p = hit(search(Bo, "laternenpfahl"), P5)
check(p and "<script>" not in p["snippet"] and "<b>" not in p["snippet"] and "Laternenpfahl & Co" in p["snippet"], "tags left out, the text stays plain " + str(p and p["snippet"]))

# ================================================================ only the page shown, only pages one may read
ids = [page(Bo, SP, f"Serie/Seite {i:02d}", f"Ein Text über die Sternfrucht Nummer {i}") for i in range(35)]
j = search(Bo, "sternfrucht", space=SP)
check(j["total"] == 35 and len(j["pages"]) == 30 and all(x.get("snippet") for x in j["pages"]), "30 hits on the first page, each with its snippet")
j2 = search(Bo, "sternfrucht", space=SP, offset=30)
check(len(j2["pages"]) == 5 and all(bold(x) == ["Sternfrucht"] for x in j2["pages"]), "the next page: the other 5 with theirs")
j3 = search(Bo, "sternfrucht", space=SP, limit=5)
check(len(j3["pages"]) == 5 and j3["more"], "limit=5: 5 hits with snippets " + str(len(j3["pages"])))
PC = page(Ca, SP2, "Geheim/Beta", "Die Rezeptur mit Quittenmus bleibt in Beta.")
j = search(Bo, "quittenmus")
check(j["total"] == 0 and not j["pages"], "another organisation's page: no hit, no snippet for Bob " + str(j)[:200])
check(search(Ca, "kuhlschrank")["total"] == 0, "Carol finds nothing of Alpha's texts")
p = hit(search(Ca, "quittenmus"), PC)
check(p and bold(p) == ["Quittenmus"], "Carol sees her own page with its snippet")
PP = page(A, "private", "Privat/Tagebuch", "Heute habe ich Holunderblüten gesammelt.")
check(search(Bo, "holunderbluten")["total"] == 0, "someone else's private page: nothing")
p = hit(search(A, "holunderblüten"), PP)
check(p and bold(p) == ["Holunderblüten"], "the own private page: with its snippet")

# a page whose text cannot be opened: found by its name, no snippet, no error
PU = page(Bo, SP, "Kaputt/Zebrafink", "Zebrafink im Garten")
other = sql("SELECT body FROM wiki_pages WHERE id=?", (PC,))[0][0]  # sealed with Beta's key: Alpha's cannot open it
sql("UPDATE wiki_pages SET body=? WHERE id=?", (other, PU), write=True)
sql("DELETE FROM wiki_words WHERE page_id=?", (PU,), write=True)  # its index is built again (as after a change elsewhere)
r = Bo.get(B + "/api/wiki/search", params={"q": "zebrafink"})
p = hit(r.json(), PU) if r.ok else None
check(r.ok and p is not None and "snippet" not in p, "an unreadable page: found by its name, no snippet, no error " + r.text[:200])

# a space with the lock: the server neither searches nor cuts (the browser does)
P9 = page(Ca, SP2, "Notiz/Laub", "Herbstlaub im Hof")
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG2,), write=True)
r = Ca.get(B + "/api/wiki/search", params={"q": "herbstlaub"})
check(r.ok and r.json()["total"] == 0 and not any(x.get("snippet") for x in r.json()["pages"]), "a space with the lock: no hit and no snippet from the server, no error " + r.text[:200])
r = Ca.get(B + "/api/wiki/search", params={"q": "herbstlaub", "space": SP2})
check(r.ok and r.json()["total"] == 0, "?space= of the locked space: answered without error, empty " + r.text[:200])

# ================================================================ nothing stored or logged
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
lg = (logs.stdout or "") + (logs.stderr or "")
check(lg and not any(w in lg for w in ("Kühlschrank", "Sternfrucht", "Quittenmus", "Laternenpfahl", "Fischotter", "Holunderbl")),
      "the server's log holds no word of a text or a snippet")
check(not sql("SELECT 1 FROM wiki_words WHERE h LIKE '%hlschrank%' OR h LIKE '%ternfrucht%'"), "the word index holds only hashes")
check(sql("SELECT body FROM wiki_pages WHERE id=?", (P1,))[0][0].startswith("kenc1:"), "the text stays sealed after the searches")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
