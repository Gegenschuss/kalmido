#!/usr/bin/env python3
# kalmido-suite:
"""2.371 API tests (#3150), own container (start.sh) with a server key (texts sealed at rest). Invented names and texts only.
 - tags: #word in the text (starting with a letter) and "tags:" / "tag:" in the frontmatter; #123 stays a task, a # in a
   word, an address, inline code, a code block, a [[Page#Section]] link or an html entity is no tag; case ignored, the
   first spelling shown; GET /api/wiki/tags lists them (most used first), &tag= gives the pages that have it (no templates)
 - nothing in plain text: the word index holds only hashes of the tags, the texts stay sealed, the log holds no tag of a text
 - a page changed: its tags follow at once; an index made before 2.371 (no 'tv:1') is read at once and indexed again
 - 2.469.0 (#3546): the list stays in the process's memory: a hit opens no text; a text written without updated_at, quick saves
   within one second, trash and restore, a page not indexed yet are seen at once; a person who lost the space 404, a share taken
   away changes the stamp; a reader through a share starts no index job of the space
 - GET /api/wiki/query (the ```abfrage block): tag / ordner / eigenschaft / zeige: aufgaben / sortiere / grenze / als /
   spalten and the English keys; the page holding the block and the templates are never in the result; unknown lines in
   errors; open checkboxes only ("- [x]" and code blocks left out) with their line
 - rights: another organisation's space 404 (tags and query), a guest reading through a folder share sees only the shared
   pages in a query; a space with the lock: {e2e: true} from both routes (the browser runs them)
 - freelancer-matrix: wiki (a person without an organisation: tags and queries in her private workspace)
 - tenant-matrix: wiki (not in the organisation / another person's private page: 404 for tags and query)
usage: p2371_wiki_tags_test.py <datadir>      (P2371_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "wiki,files,collab,comments"


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


def tags(s, space):
    r = s.get(B + "/api/wiki/tags", params={"space": space})
    assert r.ok, r.text
    return {t["tag"]: t["n"] for t in r.json()["tags"]}


def tagged(s, space, tag):
    r = s.get(B + "/api/wiki/tags", params={"space": space, "tag": tag})
    assert r.ok, r.text
    return [p["path"] for p in r.json()["pages"]]


def query(s, pid, text):
    return s.get(B + "/api/wiki/query", params={"page": pid, "q": text})


def qpaths(s, pid, text):
    r = query(s, pid, text)
    assert r.ok, r.text
    return [p["path"] for p in r.json()["pages"]]


if os.environ.get("P2371_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}


def person(name, role):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
    return s


Bo, Gi = person("bob", "member"), person("gina", "guest")
FID, Fr = freelancer(B, A)  # freelancer-matrix: wiki
def up():  # a real state: the server answers again (after a start or the encryption pass)
    for _ in range(120):
        try:
            if requests.get(B + "/api/health", headers=H, timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.25)
    return False


for _ in range(3):  # 2.371: under load the pass met a server still settling (connection reset): once more when it fails
    res = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "encrypt-wiki"],
                         capture_output=True, text=True, timeout=300)
    up()
    if res.returncode == 0:
        break
    print("encrypt-wiki:", res.returncode, (res.stdout + res.stderr)[-600:], flush=True)
check(res.returncode == 0, "setup: encrypt-wiki (the texts sealed at rest)")

# ================================================================ the tags of a person without an organisation
TA = ("Planung für #Projekt und #kunde/Nord. Aufgabe #123 bleibt ein Verweis, mail#nein, https://example.com/#frag, "
      "`#imcode`, [[Plan#Abschnitt]], [Link](#anker), &#35;entity, C#\n\n```\n#imblock\n```\n\n"
      "- [ ] Angebot schreiben #projekt\n- [x] Erledigt schon\n> - [ ] Im Zitat offen\n\n```\n- [ ] im Code\n```\n#Fenchelknolle")
PA = page(Fr, "private", "Kunden/Nord/Plan", TA)
PB = page(Fr, "private", "Kunden/Süd", "---\ntags: [projekt, intern]\nstatus: offen\nkunde: Süd GmbH\n---\nText ohne Tag. - [ ] Offen in B")
PC = page(Fr, "private", "Notizen/Ohne", "Nur Text, kein Tag.")
PD = page(Fr, "private", "Kunden/West", "---\ntag: \"#Projekt, extern\"\nstatus: zu\n---\n")
PT = page(Fr, "private", "Templates/Projektseite", "#projekt #vorlage")
check(sql("SELECT body FROM wiki_pages WHERE id=?", (PA,))[0][0].startswith("kenc1:"), "setup: the text is sealed in the database")
t = tags(Fr, "private")
check(t.get("Projekt") == 3 and "projekt" not in t, "a tag in the text and in the frontmatter, case ignored, the first spelling shown " + str(t))
check(t.get("kunde/Nord") == 1 and t.get("intern") == 1 and t.get("extern") == 1 and t.get("Fenchelknolle") == 1, "#a/b, tags: [..], tag: \"#x, y\" " + str(t))
check(not ({"123", "nein", "frag", "imcode", "imblock", "Abschnitt", "anker", "entity", "vorlage"} & {k for k in t}),
      "no tag: a task #123, a # in a word / an address / code / a code block / a [[link#section]] / a link target / an entity, templates " + str(t))
check(list(t)[0] == "Projekt", "most used first " + str(list(t)))
check(tagged(Fr, "private", "PROJEKT") == ["Kunden/Nord/Plan", "Kunden/Süd", "Kunden/West"], "&tag=: the pages with it, by name, without templates "
      + str(tagged(Fr, "private", "PROJEKT")))
check(tagged(Fr, "private", "fehlt") == [], "an unknown tag: no page")
check(Fr.get(B + "/api/wiki/tags", params={"space": "private", "tag": "12"}).status_code == 400, "a tag starting with a digit is refused (a task)")

# ================================================================ nothing in plain text
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
check(not sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND h LIKE '%rojekt%' OR h LIKE '%enchel%' OR h LIKE '%Nord%'"), "the word index holds hashes only")
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
check(len(sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h LIKE 't:%'", (PA,))) == 3, "one hash per tag of the page")
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
check(sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (PA,)), "the page is marked as indexed with its tags")
check(sql("SELECT body FROM wiki_pages WHERE id=?", (PA,))[0][0].startswith("kenc1:"), "the text stays sealed")

# ================================================================ a change, an old index
r = Fr.patch(B + f"/api/wiki/pages/{PA}", json={"body": TA.replace("#kunde/Nord", "Nord")})
check(r.ok, "setup: the page changed")
t = tags(Fr, "private")
check("kunde/Nord" not in t and t.get("Projekt") == 3, "a removed tag is gone at once " + str(t))
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
sql("DELETE FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND (h LIKE 't:%' OR h='v:2')", (PB,), write=True)  # as indexed before 2.371
check("Kunden/Süd" in tagged(Fr, "private", "intern"), "an index made before the tags: the page is read at once")
ok = False
for _ in range(60):  # the background job indexes it again (a real state: its marker row)
    # 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
    if sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (PB,)):
        ok = True
        break
    time.sleep(0.25)
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
check(ok and len(sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h LIKE 't:%'", (PB,))) == 2, "and indexed again in the background")

# ================================================================ 2.469.0 (#3546): the list in the process's memory
SKIP = "wiki page unreadable, skipped "


def reads(pid):
    """How often the server has opened page pid's text: an unreadable text leaves one line per try (wsb_body_or)."""
    lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
    return ((lg.stdout or "") + (lg.stderr or "")).count(f"{SKIP}{pid}\n")


def reads_reach(pid, n):
    for _ in range(40):  # the log is written behind the answer: its line, not a time
        if reads(pid) >= n:
            break
        time.sleep(0.25)
    return reads(pid)


PS = page(Fr, "private", "Cache/Versiegelt", "#zwischenspeicher")
PW = page(Fr, "private", "Cache/Andere", "#anderes")
sql("UPDATE wiki_pages SET body=? WHERE id=?", ("kenc1:" + "A" * 80, PS), write=True)  # sealed, cannot be opened; the index stays current
r0 = reads(PS)
tags(Fr, "private")
r1 = reads_reach(PS, r0 + 1)
check(r1 == r0 + 1, f"setup: a miss opens the text ({r0} -> {r1})")
t1, t2 = tags(Fr, "private"), tags(Fr, "private")
check(t1 == t2 and t1.get("anderes") == 1, "a hit gives the same list " + str(t1))
check(Fr.patch(B + f"/api/wiki/pages/{PW}", json={"body": "#anderes #neuer"}).ok, "setup: another page changed")
t3 = tags(Fr, "private")
r2 = reads_reach(PS, r1 + 1)
check(t3.get("neuer") == 1, "a change is seen at once " + str(t3))
check(r2 == r1 + 1, f"a hit opens no text: only the one miss after the change counted ({r1} -> {r2})")

sql("UPDATE wiki_pages SET body=? WHERE id=?", ("#ohneDatum", PW), write=True)  # as a move or an import: the text written, updated_at stays
t = tags(Fr, "private")
check(t.get("ohneDatum") == 1 and "neuer" not in t, "a text written without updated_at is a miss " + str(t))
for i in range(4):  # several saves within one second: updated_at (whole seconds) stays the same
    check(Fr.patch(B + f"/api/wiki/pages/{PW}", json={"body": f"#schnell{'abcd'[i]}"}).ok, "setup: a quick save")
    t = tags(Fr, "private")
    check(t.get(f"schnell{'abcd'[i]}") == 1 and len([k for k in t if k.startswith("schnell")]) == 1, "a quick save right after another is seen " + str(t))
check(Fr.delete(B + f"/api/wiki/pages/{PW}").ok, "setup: a page into the trash")
check("schnelld" not in tags(Fr, "private"), "a page in the trash is gone from the list")
check(Fr.post(B + "/api/wiki/restore", json={"ids": [PW]}).ok, "setup: restored")
check(tags(Fr, "private").get("schnelld") == 1, "a restored page is back, though updated_at did not move")
# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
sql("DELETE FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (PW,), write=True)  # late: nothing stored, nothing answered from memory
sql("UPDATE wiki_pages SET body=? WHERE id=?", ("#spaet", PW), write=True)
check(tags(Fr, "private").get("spaet") == 1, "a page not indexed yet: read now, not from memory")
for _ in range(60):
    # 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
    if sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (PW,)):
        break
    time.sleep(0.25)
check(tags(Fr, "private").get("spaet") == 1, "and the list stays right once it is indexed")
check(Fr.delete(B + f"/api/wiki/pages/{PS}").ok and Fr.delete(B + f"/api/wiki/pages/{PW}").ok, "setup: the test pages away")

# ================================================================ the ```abfrage block
PQ = page(Fr, "private", "Übersicht", "#projekt\n\n```abfrage\ntag: projekt\n```")
check(qpaths(Fr, PQ, "tag: projekt") == ["Kunden/Nord/Plan", "Kunden/Süd", "Kunden/West"], "tag: the pages with it, not the block's own page, no templates "
      + str(qpaths(Fr, PQ, "tag: projekt")))
check(qpaths(Fr, PQ, "tag: projekt, intern") == ["Kunden/Süd"] and qpaths(Fr, PQ, "tag: projekt\ntag: #extern") == ["Kunden/West"], "several tags: all of them")
check(qpaths(Fr, PQ, "ordner: Kunden/Nord") == ["Kunden/Nord/Plan"] and qpaths(Fr, PQ, "folder: notizen") == ["Notizen/Ohne"], "ordner / folder (case ignored)")
check(qpaths(Fr, PQ, "eigenschaft: status = offen") == ["Kunden/Süd"] and qpaths(Fr, PQ, "property: status") == ["Kunden/Süd", "Kunden/West"],
      "eigenschaft: key = value, a key alone")
check(qpaths(Fr, PQ, "tag: projekt\nsortiere: status absteigend") == ["Kunden/West", "Kunden/Süd", "Kunden/Nord/Plan"], "sort by a key, pages without it at the end "
      + str(qpaths(Fr, PQ, "tag: projekt\nsortiere: status absteigend")))
check(qpaths(Fr, PQ, "tag: projekt\nsort: updated desc") == ["Kunden/Nord/Plan", "Kunden/West", "Kunden/Süd"], "sort: updated desc (the page changed last first) "
      + str(qpaths(Fr, PQ, "tag: projekt\nsort: updated desc")))
r = query(Fr, PQ, "tag: projekt\ngrenze: 1\nals: tabelle\nspalten: status, kunde\nfoo bar\nzeige: alles")
j = r.json()
check(r.ok and len(j["pages"]) == 1 and j["total"] == 3 and j["more"] is True and j["as"] == "table" and j["cols"] == ["status", "kunde"],
      "grenze / als: tabelle / spalten " + r.text[:300])
check(j["errors"] == ["foo bar", "zeige: alles"], "lines not understood are named " + str(j.get("errors")))
r = query(Fr, PQ, "tag: projekt\nspalten: status")
check(r.ok and r.json()["pages"][1]["attrs"] == {"status": "offen"}, "only the columns' properties come along " + r.text[:300])
r = query(Fr, PQ, "tag: projekt\nzeige: aufgaben")
j = r.json()
check(r.ok and [(x["path"], x["text"]) for x in j["tasks"]] == [("Kunden/Nord/Plan", "Angebot schreiben #projekt"), ("Kunden/Nord/Plan", "Im Zitat offen")],
      "zeige: aufgaben = the open checkboxes (also in a quote; not done ones, not in code, none inside a line) " + r.text[:400])
check(j["tasks"] and j["tasks"][0]["line"] == 7 and j["tasks"][0]["page_id"] == PA, "with their line and page " + str(j["tasks"][:1]))
check(query(Fr, PQ, "show: tasks\nfolder: Notizen").json()["tasks"] == [], "no open checkbox: empty")
PS = page(Fr, "private", "Notizen/Lang", "- [ ] a" + " " * 300_000 + "b\n- [ ]    \n- [ ] Ende   ")  # review: no slow regex on long blanks
t0 = time.time()
r = query(Fr, PQ, "show: tasks\nfolder: Notizen")
check(r.ok and time.time() - t0 < 5 and [x["text"][:1] + str(len(x["text"])) for x in r.json()["tasks"]] == ["a300", "E4"],
      f"a checkbox line with 300 000 blanks answers at once ({time.time() - t0:.1f} s), a blank one is none, trailing blanks cut " + r.text[:200])
check(query(Fr, 0, "tag: projekt").status_code == 404 and query(Fr, 999999, "tag: projekt").status_code == 404, "no page / an unknown page: 404")

# ================================================================ rights
check(Bo.get(B + "/api/wiki/tags", params={"space": "private"}).json()["tags"] == [], "another person's private tags stay hers")
check(query(Bo, PQ, "tag: projekt").status_code == 404, "a query from another person's private page: 404")
P1 = page(A, SP, "Internal/Customer A/Setup", "#kunde setup\n\n```abfrage\ntag: kunde\n```")
P2 = page(A, SP, "Internal/Customer A/Notes", "#kunde notes")
SECRET = page(A, SP, "Internal/Secret plan", "#kunde secret")
check(qpaths(Bo, P1, "tag: kunde") == ["Internal/Customer A/Notes", "Internal/Secret plan"], "a member: every page of the space")
check(tags(Bo, SP).get("kunde") == 3, "a member: the space's tags")
check(Fr.get(B + "/api/wiki/tags", params={"space": SP}).status_code == 404 and query(Fr, P1, "tag: kunde").status_code == 404,
      "not in the organisation: 404 (tags and query)")
check(Gi.get(B + "/api/wiki/tags", params={"space": SP}).status_code == 404, "a guest: no tags of the space")
j = A.get(B + "/api/wiki", params={"space": SP}).json()
FA = next((f["id"] for f in j.get("folders", []) if f["path"] == "Internal/Customer A"), None)
r = Bo.post(B + f"/api/files/nodes/{FA}/shares", json={"user_id": uid["gina"], "role": "view"})
check(r.status_code == 201, "setup: the folder shared with the guest " + r.text[:200])
r = query(Gi, P1, "tag: kunde")
check(r.ok and len(r.json()["pages"]) == 1 and r.json()["pages"][0]["path"].endswith("Notes") and "Internal/" not in r.text and "Secret" not in r.text,
      "a guest through a folder share: only the shared pages, their paths from the share down " + r.text[:300])
r = query(Gi, P1, "ordner: Internal")
check(r.ok and "Secret plan" not in r.text and r.json()["total"] == 0, "the folders above the share are not matched: ordner: Internal finds nothing (review) " + r.text[:300])

# ================================================================ 2.469.0 (#3546): a reader through a share starts no index job of the space
def index_jobs():
    return sql("SELECT COUNT(*) FROM bg_jobs WHERE kind='wiki:index' AND org_id=?", (ORG,))[0][0]


# 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
sql("DELETE FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (P2,), write=True)  # as indexed before 2.371: the page is late
before = index_jobs()
r = query(Gi, P1, "tag: kunde")
check(r.ok and len(r.json()["pages"]) == 1, "#3546: the share reader still gets a page not indexed yet " + r.text[:200])
check(index_jobs() == before, "#3546: and starts no index job of that space")
tags(Bo, SP)
check(index_jobs() > before, "#3546: a person of the space does (the check above can fail)")
for _ in range(60):  # the background job: a real state, its marker row
    # 2.1002.0 (#5279): the shared word index obj_search_words (was doc_words / file_words / wiki_words / hub_words)
    if sql("SELECT 1 FROM obj_search_words WHERE kind='wiki_page' AND ref_id=? AND h='v:2'", (P2,)):
        break
    time.sleep(0.25)

# ================================================================ a space with the lock
PL = page(Bo, SP, "Locked/Page", "#kunde")
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1) ON CONFLICT DO NOTHING", (ORG,), write=True)
sql("UPDATE wiki_spaces SET e2e='on', e2e_gen=1 WHERE org_id=?", (ORG,), write=True)
r = Bo.get(B + "/api/wiki/tags", params={"space": SP})
check(r.ok and r.json().get("e2e") is True and r.json()["tags"] == [], "a space with the lock: the tags in the browser " + r.text[:200])
r = query(Bo, PL, "tag: kunde")
check(r.ok and r.json().get("e2e") is True and r.json()["pages"] == [], "and the query too " + r.text[:200])
sql("UPDATE wiki_spaces SET e2e=NULL WHERE org_id=?", (ORG,), write=True)

# ================================================================ 2.469.0 (#3546): rights and the list in memory
check(tags(Bo, SP).get("kunde"), "setup: the member's list in memory")
check(tags(A, SP).get("kunde") and Fr.get(B + "/api/wiki/tags", params={"space": SP}).status_code == 404, "one entry per person: nobody outside gets it")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "guest"}).ok, "setup: the member becomes a guest")
check(Bo.get(B + "/api/wiki/tags", params={"space": SP}).status_code == 404, "a person who lost the space: 404, nothing from memory")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"}).ok, "setup: a member again")
check(tags(Bo, SP).get("kunde"), "and back: the list again")
# the stamp holds what the person may read: nobody reaches the route through a share today, it must still end with the share
STAMP = f"""
from kalmido.core.db import connect
from kalmido.wiki.wktags import _wkt_stamp
print("STAMP", _wkt_stamp(connect(), {ORG}, None, {uid["gina"]})[-1])
"""


def vis_stamp():
    x = subprocess.run(["docker", "exec", "-i", CT, "python", "-"], input=STAMP, capture_output=True, text=True, timeout=60)
    return next((ln for ln in x.stdout.splitlines() if ln.startswith("STAMP ")), x.stderr[-300:])


v0 = vis_stamp()
sql("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (FA, uid["gina"]), write=True)
v1 = vis_stamp()
check(v0.startswith("STAMP ") and v1.startswith("STAMP ") and v0 != v1, "a share taken away changes the stamp " + str((v0, v1)))

# ================================================================ nothing logged
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
lg = (logs.stdout or "") + (logs.stderr or "")
check(lg and "Fenchelknolle" not in lg and "Angebot schreiben" not in lg, "the server's log holds no tag or checkbox of a text")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
