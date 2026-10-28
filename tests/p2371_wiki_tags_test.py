#!/usr/bin/env python3
# kalmido-suite:
"""2.371 API tests (#3150), own container (start.sh) with a server key (texts sealed at rest). Invented names and texts only.
 - tags: #word in the text (starting with a letter) and "tags:" / "tag:" in the frontmatter; #123 stays a task, a # in a
   word, an address, inline code, a code block, a [[Page#Section]] link or an html entity is no tag; case ignored, the
   first spelling shown; GET /api/wiki/tags lists them (most used first), &tag= gives the pages that have it (no templates)
 - nothing in plain text: the word index holds only hashes of the tags, the texts stay sealed, the log holds no tag of a text
 - a page changed: its tags follow at once; an index made before 2.371 (no 'tv:1') is read at once and indexed again
 - GET /api/wiki/query (the ```abfrage block): tag / ordner / eigenschaft / zeige: aufgaben / sortiere / grenze / als /
   spalten and the English keys; the page holding the block and the templates are never in the result; unknown lines in
   errors; open checkboxes only ("- [x]" and code blocks left out) with their line
 - rights: another organisation's space 404 (tags and query), a guest reading through a folder share sees only the shared
   pages in a query; a space with the lock: {e2e: true} from both routes (the browser runs them)
 - freelancer-matrix: wiki (a person without an organisation: tags and queries in her private space)
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
code = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", "encrypt-wiki"],
                      capture_output=True, text=True, timeout=300).returncode
check(code == 0, "setup: encrypt-wiki (the texts sealed at rest)")

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
check(not sql("SELECT 1 FROM wiki_words WHERE h LIKE '%rojekt%' OR h LIKE '%enchel%' OR h LIKE '%Nord%'"), "the word index holds hashes only")
check(len(sql("SELECT 1 FROM wiki_words WHERE page_id=? AND h LIKE 't:%'", (PA,))) == 3, "one hash per tag of the page")
check(sql("SELECT 1 FROM wiki_words WHERE page_id=? AND h='tv:1'", (PA,)), "the page is marked as indexed with its tags")
check(sql("SELECT body FROM wiki_pages WHERE id=?", (PA,))[0][0].startswith("kenc1:"), "the text stays sealed")

# ================================================================ a change, an old index
r = Fr.patch(B + f"/api/wiki/pages/{PA}", json={"body": TA.replace("#kunde/Nord", "Nord")})
check(r.ok, "setup: the page changed")
t = tags(Fr, "private")
check("kunde/Nord" not in t and t.get("Projekt") == 3, "a removed tag is gone at once " + str(t))
sql("DELETE FROM wiki_words WHERE page_id=? AND (h LIKE 't:%' OR h='tv:1')", (PB,), write=True)  # as indexed before 2.371
check("Kunden/Süd" in tagged(Fr, "private", "intern"), "an index made before the tags: the page is read at once")
ok = False
for _ in range(60):  # the background job indexes it again (a real state: its marker row)
    if sql("SELECT 1 FROM wiki_words WHERE page_id=? AND h='tv:1'", (PB,)):
        ok = True
        break
    time.sleep(0.25)
check(ok and len(sql("SELECT 1 FROM wiki_words WHERE page_id=? AND h LIKE 't:%'", (PB,))) == 2, "and indexed again in the background")

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
check(r.ok and "Secret plan" not in r.text, "and nothing outside the share by folder " + r.text[:300])

# ================================================================ a space with the lock
PL = page(Bo, SP, "Locked/Page", "#kunde")
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1) ON CONFLICT DO NOTHING", (ORG,), write=True)
sql("UPDATE wiki_spaces SET e2e='on', e2e_gen=1 WHERE org_id=?", (ORG,), write=True)
r = Bo.get(B + "/api/wiki/tags", params={"space": SP})
check(r.ok and r.json().get("e2e") is True and r.json()["tags"] == [], "a space with the lock: the tags in the browser " + r.text[:200])
r = query(Bo, PL, "tag: kunde")
check(r.ok and r.json().get("e2e") is True and r.json()["pages"] == [], "and the query too " + r.text[:200])
sql("UPDATE wiki_spaces SET e2e=NULL WHERE org_id=?", (ORG,), write=True)

# ================================================================ nothing logged
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True, timeout=60)
lg = (logs.stdout or "") + (logs.stderr or "")
check(lg and "Fenchelknolle" not in lg and "Angebot schreiben" not in lg, "the server's log holds no tag or checkbox of a text")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
