#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1002.0 (#5279, stage Q6b of the cross-cutting core): one keyed word index for the sealed texts, obj_search_words
(core/objwords.py), instead of doc_words, file_words, wiki_words and hub_words. Own container. Invented names only.
 - the table is there, the four old ones are gone; the index holds hashes only
 - umlauts (question 13): "Mueller" finds "Müller" and back, "gaertner" finds "Gärtnerei" -- in documents, knowledge pages and
   filed mails
 - word start everywhere (question 14): "ab" finds "Abendessen" (2 characters), "kuehl" finds "Kühlschrank"; "bend" (inside a
   word) finds nothing
 - rights: another organisation finds nothing of Alpha; a guest finds the text of a knowledge page that a share of the core
   opens (question 15), not a page outside the share; the private page / document / mail of a person without an
   organisation is found by her only
 - the start: a database of before (doc_words with its hashes, the shared index's rows gone) keeps its search -- the move copies
   the hashes before the fragment drops the old table, the back limit becomes the minor of this image; the watchdog's catch-up
   indexes the moved objects again by the new rules (the mark v:2)
 - a filed mail deleted for good takes its words along (the delete trigger)
freelancer-matrix: sealed search (a person without an organisation finds her own page, document and mail by umlaut / word start)
usage: p21002_d_sealed_search_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

OLD = ("doc_words", "file_words", "wiki_words", "hub_words")


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def wiki(s, q, **kw):
    r = s.get(B + "/api/search?kind=wiki", params={"q": q, **kw})
    return [p["id"] for p in r.json().get("pages", [])] if r.ok else [("error", r.status_code)]


def docs(s, q):
    r = s.get(B + "/api/docs", params={"ws": "all", "q": q})
    j = r.json() if r.ok else {}
    return {d["id"] for d in j.get("docs") or j.get("data") or []} if r.ok else {("error", r.status_code)}


def inbox(s, q):
    r = s.get(B + "/api/hubmail/inbox", params={"q": q})
    return {m["id"] for m in r.json().get("mails", [])} if r.ok else {("error", r.status_code)}


def doc(s, ws, name, text):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code in (200, 201), r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return nid


def page(s, space, path, body):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def hub_mail(owner, subject, body):
    """A filed mail that is not assigned (the recipient's inbox), written straight into the table and indexed by the area."""
    mid = dbx("INSERT INTO hub_mails(owner_id, ws, message_id, from_addr, from_name, subject, body, created_at) "
              "VALUES(?, ?, ?, 'post@example.com', 'Post', ?, ?, '2026-11-12T10:00:00Z') RETURNING id",
              (owner, f"u{owner}", f"<p21002d-{subject}@example.com>", subject, body))[0][0]
    box(f"from kalmido.hub.hubmail import _index, _open\nm = c.execute('SELECT * FROM hub_mails WHERE id=?', ({mid},)).fetchone()\n"
        "_index(c, m['id'], m['ws'], _open(c, m))")
    return mid


kt.fresh(prefix="P21002D")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
r = A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
assert r.ok, r.text
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = kt.me_id(A)
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("gina", "guest"), ("carl", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    org_join(B, u, ORG)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
check(r.ok, "setup: organisation Beta for carl " + r.text[:100])
check(A.delete(B + f"/api/orgs/{ORG}/members/{uid['carl']}").ok, "setup: carl leaves Alpha")
FID, Fr = freelancer(B, A)
Gi, Ca = kt.sess("gina"), kt.sess("carl")
for s in (Gi, Ca, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

# ================================================================== the table, the old ones gone
check(table_there("obj_search_words"), "the shared word index obj_search_words exists")
check(not [t for t in OLD if table_there(t)], f"the old word indexes are gone {[t for t in OLD if table_there(t)]}")

# ================================================================== knowledge pages
SP = f"org:{ORG}"
WP1 = page(A, SP, "Kunden/Nordhof/Ablauf", "Abendessen mit Familie Müller, der Kühlschrank steht in der Gärtnerei")
WP2 = page(A, SP, "Intern/Plan", "Zaunpfähle für den Mueller-Weg bestellen")
WPF = page(Fr, "private", "Notizen/Garten", "Frida plant die Gärtnerei am Kühlweg")
check(wiki(A, "mueller") and set(wiki(A, "mueller")) == {WP1, WP2}, f"umlaut: mueller finds Müller and Mueller {wiki(A, 'mueller')}")
check(set(wiki(A, "müller")) == {WP1, WP2}, f"... and müller both as well {wiki(A, 'müller')}")
check(set(wiki(A, "ab")) == {WP1}, f"word start of 2 characters: ab finds Abendessen (and Ablauf) {wiki(A, 'ab')}")
check(wiki(A, "kuehl") == [WP1], f"kuehl finds Kühlschrank {wiki(A, 'kuehl')}")
check(wiki(A, "bend") == [], f"inside a word: bend finds nothing {wiki(A, 'bend')}")
check(wiki(A, "gaertnerei familie") == [WP1], "two words, both at a word start (AND)")
check(wiki(Ca, "abendessen") == [], "another organisation: no page of Alpha")
check(wiki(A, "gaertnerei") == [WP1], "alice: not the private page of the freelancer")
# question 15: a share of the core on the folder opens the page for the guest -- its text is found, not a page outside
j = A.get(B + "/api/wiki", params={"space": SP}).json()
FK = next((f["id"] for f in j.get("folders", []) if f["path"] == "Kunden/Nordhof"), None)
r = A.post(B + f"/api/files/nodes/{FK}/shares", json={"user_id": uid["gina"], "role": "view"})
check(r.status_code == 201, f"setup: the folder shared with the guest {r.status_code} {r.text[:200]}")
check(wiki(Gi, "kühlschrank") == [WP1], f"the guest finds the shared page by a word of its text {wiki(Gi, 'kühlschrank')}")
check(wiki(Gi, "zaunpfaehle") == [], "... not a page outside the share")
r = Gi.get(B + f"/api/wiki/pages/{WP1}")
check(r.ok and "Kühlschrank" in (r.json().get("body") or ""), "the hit opens for the guest (the way in)")
j = Gi.get(B + "/api/search?kind=wiki", params={"q": "kuehl"}).json()
check(any(p["id"] == WP1 and "Kühlschrank" in (p.get("snippet") or "") for p in j.get("pages", [])),
      f"the hit carries its snippet with the word {str(j)[:200]}")
check(wiki(Ca, "kühlschrank") == [], "carl (no share, other organisation): nothing")

# ================================================================== documents
D1 = doc(A, SP, "rechnung.txt", "Rechnung Gärtnerei Müller für Zaunpfähle und Abendessen")
DF = doc(Fr, "private", "frida.txt", "Frida Kühlregal Angebot")
check(D1 in docs(A, "mueller") and D1 in docs(A, "gaertner") and D1 in docs(A, "ab"), f"documents: umlaut and word start {docs(A, 'mueller')}")
check(D1 not in docs(A, "bend"), "documents: inside a word finds nothing")
check(D1 not in docs(Ca, "gaertner") and DF not in docs(A, "kuehlregal"), "documents: another organisation / the freelancer's private one: nothing")
hs = [x[0] for x in dbx("SELECT h FROM obj_search_words WHERE kind='doc' AND ref_id=?", (D1,))]
check(hs and "v:2" in hs and not [h for h in hs if "rtner" in h or "ller" in h or "aunpf" in h], "the index holds hashes and the mark only")

# ================================================================== filed mails
M1 = hub_mail(ALICE, "Anfrage Gärtnerei", "Bitte das Abendessen bei Mueller bestätigen")
MF = hub_mail(FID, "Frida Post", "Kühltruhe kommt am Montag")
check(M1 in inbox(A, "gaertnerei") and M1 in inbox(A, "müller") and M1 in inbox(A, "ab"), f"mails: umlaut and word start {inbox(A, 'müller')}")
check(M1 not in inbox(A, "bend") and not inbox(Fr, "gaertnerei"), "mails: inside a word nothing, the freelancer not alice's mail")

# ================================================================== freelancer-matrix: sealed search
check(wiki(Fr, "gaertnerei") == [WPF] and wiki(Fr, "kuehl") == [WPF], "freelancer: her private page by umlaut and word start")
check(DF in docs(Fr, "kuehlr") and inbox(Fr, "kuhltruhe") == {MF}, "freelancer: her document and her mail")

# ================================================================== a filed mail deleted for good: its words go
dbx("DELETE FROM hub_mails WHERE id=?", (M1,))
check(not dbx("SELECT 1 FROM obj_search_words WHERE kind='hub_mail' AND ref_id=?", (M1,)), "a mail deleted for good: its words go (trigger)")

# ================================================================== the start: a database of before (the move)
OLDH = [x[0] for x in dbx("SELECT h FROM obj_search_words WHERE kind='doc' AND ref_id=? AND h<>'v:2'", (D1,))]
dbx("CREATE TABLE doc_words (node_id BIGINT NOT NULL REFERENCES fs_nodes(id) ON DELETE CASCADE, h TEXT NOT NULL, PRIMARY KEY (node_id, h))")
for h in OLDH:
    dbx("INSERT INTO doc_words(node_id, h) VALUES(?, ?)", (D1, h))
dbx("DELETE FROM obj_search_words WHERE kind='doc' AND ref_id=?", (D1,))
dbx("DELETE FROM kalmido_meta WHERE key IN ('back_floor', 'back_floor_how')")
check(D1 not in docs(A, "gaertner"), "setup: the document is out of the shared index (as before the update)")
box("pass")  # the next start of the app
check(not table_there("doc_words"), "the start dropped the old table")
check(D1 in docs(A, "gaertnerei") and D1 in docs(A, "zaunpfaehle"), "the moved hashes find the document at once")
mine = box("from kalmido.core.config import APP_VERSION\nprint(APP_VERSION)")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
check(fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]) and "#5279" in (fl.get("back_floor_how") or ""),
      f"the move raised back_floor to the minor of this image {fl} {mine}")
# the moved document lacks the mark until the catch-up (the server's watchdog may be first: the state, not the run, counts)
out = box("from kalmido.core.objwords import osw_tick\nprint(osw_tick(c, force=True))")
check(dbx("SELECT 1 FROM obj_search_words WHERE kind='doc' AND ref_id=? AND h='v:2'", (D1,)),
      f"the catch-up indexed it again by the new rules ({out})")
check(D1 in docs(A, "ab") and D1 in docs(A, "mueller"), "... and the new rules find it (2 characters, umlaut)")
# review of 2.1002 (#5279): one object a key cannot open holds only itself in the catch-up, never the whole run, and keeps
# the words it has (no mark, skipped in this process); the others of its kind are indexed in the same tick
dbx("DELETE FROM obj_search_words WHERE kind='doc' AND ref_id IN (?, ?) AND h='v:2'", (D1, DF))
out = box(f"from kalmido.core import objwords as W\nr = W.OSW_REINDEX['doc']\nreal = r['reindex']\n"
          f"def bad(c, ids):\n    if {D1} in ids:\n        raise RuntimeError('no key')\n    real(c, ids)\n"
          f"r['reindex'] = bad\nW.osw_tick(c, force=True)\nprint({D1} in W._BAD.get('doc', ()), {D1} in W.osw_late(c, 'doc'))")
check(out.splitlines()[-1:] == ["True False"], f"the failing document is set aside, not asked again in the run ({out})")
check(dbx("SELECT 1 FROM obj_search_words WHERE kind='doc' AND ref_id=? AND h='v:2'", (DF,)),
      "the other document of the same tick got its mark")
check(D1 in docs(A, "gaertnerei"), "the failing document keeps its words (still found)")
sys.exit(kt.done("p21002_d_sealed_search"))
