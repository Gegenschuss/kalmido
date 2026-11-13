#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1086.0 part B (#5820): the help for people in the app, from the same source as the agents' help (#5819). Invented names only.
 - GET /api/help (signed in): the "How to" sections per area (files, agents, office, tasks, calendar) in the person's language,
   the area names in the words of the sidebar; GET /api/help/section: one section in German (the translation of
   docs/help/de.md, numbered steps with the screen's labels), English for an English person; only a user's section (a
   developer section, an operator file, an invented key, a path: 404); signed out: 401
 - GET /api/search?kind=help (the web side of the kind): German and English words find the user's sections only
 - the agents get the same text: GET /api/v1/search?kind=help lists the user's section first (user = files), read_help
   gives it with translated (the same German text as the app) and show (the named place)
 - tools/check_userhelp.py: green on the repository and names the same sections as the server; a renamed menu item (the label
   in static/js), a translation made from an older English text, a German label the screen does not use, a label split
   over two lines -> red
 - a person without an organisation reads the same help (session and token)
usage: p21072_b_help_api_test.py <datadir>"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

V = B + "/api/v1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
USCAN = "files#how-to-set-up-a-scan-inbox"
TOOL = os.path.join(ROOT, "tools", "check_userhelp.py")

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "de", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "de", "tour": "done"})


def de_block(key):
    """The German block of key in docs/help/de.md: (title, text)."""
    with open(os.path.join(ROOT, "docs", "help", "de.md"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"<!-- help: " + re.escape(key) + r" src=\w+ -->\n## ([^\n]+)\n(.*?)(?=\n<!-- help: |\Z)", src, re.S)
    return (m.group(1), m.group(2).strip("\n")) if m else (None, None)


# ---------------------------------------------------------------- the list and one section in German
r = A.get(B + "/api/help")
j = r.json() if r.ok else {}
areas = [a["area"] for a in j.get("areas", [])]
check(r.ok and j.get("lang") == "de" and areas == ["files", "agents", "office", "tasks", "calendar"], f"GET /api/help: the five areas in order ({r.status_code} {areas})")
titles = {a["area"]: a["title"] for a in j.get("areas", [])}
check(titles == {"files": "Dateien", "agents": "Agenten", "office": "Büro", "tasks": "Aufgaben", "calendar": "Kalender"}, f"the areas in the sidebar's words: {titles}")
files = next((a for a in j.get("areas", []) if a["area"] == "files"), {"sections": []})
# 2.1090.0 (#5899): show = the section's named places in order (a list; one <!-- show: --> line per step)
SCAN_SHOW = ["settings.open", "settings.integrations", "files.scan-inbox"]
check(files["sections"] and files["sections"][0] == {"key": USCAN, "title": "Scan-Eingang einrichten", "show": SCAN_SHOW},
      f"Files: the first topic is the scan inbox in German, with its named place ({files['sections'][:1]})")
check(all(2 <= len(a["sections"]) <= 4 for a in j.get("areas", [])), "each area 2-4 short sections")

r = A.get(B + "/api/help/section", params={"key": USCAN})
sec = r.json() if r.ok else {}
t_de, x_de = de_block(USCAN)
check(r.ok and sec.get("lang") == "de" and sec.get("title") == t_de == "Scan-Eingang einrichten" and sec.get("text") == x_de,
      f"the section in German = docs/help/de.md ({r.status_code} {sec.get('title')})")
txt = sec.get("text", "")
check("**Einstellungen** > **Integrationen**" in txt and "**Dokumente: Eingänge**" in txt and "**Scan-Eingang anlegen**" in txt
      and "**Einrichtungscode**" in txt, "the steps name the German labels of the screen")
check(len(re.findall(r"^\d\. ", txt, re.M)) == 4 and "Was dann passiert" in txt, "four numbered steps and what happens then")
check(not re.search(r"/api/|scope|docs:upload|token", txt, re.I), "no API routes or developer words in the user's text")
check(sec.get("area") == "files" and sec.get("show") == SCAN_SHOW, f"area and named places {sec.get('show')}")
# 2.1090.0 (#5899): the steps of "Zeig mir": the places with route, selector and their German heading, no agent's line
stp = sec.get("steps") or []
check([x.get("target") for x in stp] == SCAN_SHOW and [x.get("label") for x in stp] == ["Einstellungen öffnen", "Einstellungen: Integrationen", "Dokumente: Eingänge (Scan-Eingang)"]
      and all(isinstance(x.get("sel"), str) and x["sel"] and "text" not in x for x in stp), f"steps for \"Zeig mir\": {stp}")
pay_key = next((x["key"] for a in j.get("areas", []) for x in a["sections"] if x["title"] == "Eine Zahlung erfassen"), "")
nos = A.get(B + "/api/help/section", params={"key": pay_key}).json()
check(pay_key and nos.get("show") == [] and nos.get("steps") == [], f"a section without marks: no places, no steps ({pay_key})")

# English for an English person (the source text, without the marker comments)
A.patch(B + "/api/settings", json={"lang": "en"})
en = A.get(B + "/api/help/section", params={"key": USCAN}).json()
check(en.get("lang") == "en" and en.get("title") == "Set up a scan inbox" and "**Settings** > **Integrations**" in en.get("text", "")
      and "<!--" not in en.get("text", ""), f"English: the source text ({en.get('title')})")
check(A.get(B + "/api/help").json()["areas"][2]["title"] == "Office", "English area name")
A.patch(B + "/api/settings", json={"lang": "de"})

for bad in ("api#scan-inboxes-folder-watcher", "files#files-and-documents", "self-hosting", "env", "../ENV.md", "docs/FILES.md",
            "files#no-such-heading", "x" * 300, ""):
    check(A.get(B + "/api/help/section", params={"key": bad}).status_code == 404, f"/api/help/section {bad[:40]!r}: 404 (only a user's section)")
check(requests.get(B + "/api/help").status_code == 401 and requests.get(B + "/api/help/section", params={"key": USCAN}).status_code == 401,
      "signed out: 401")

# ---------------------------------------------------------------- the search of the app (the web side of kind help)
def web_search(s, q):
    r = s.get(B + "/api/search", params={"kind": "help", "q": q})
    return r.json().get("data", []) if r.ok else r.status_code


for q, want in (("Scan-Eingang einrichten", USCAN), ("Scan", USCAN), ("scan inbox", USCAN),
                ("Kontoauszug", "office#how-to-record-a-payment"), ("Rechnung", "office#how-to-turn-a-quotation-into-an-invoice"),
                ("wiederkehrende Aufgabe", "tasks#how-to-make-a-task-repeat"), ("Kalender abonnieren", "calendar#how-to-subscribe-to-another-calendar")):
    hits = web_search(A, q)
    keys = [h["key"] for h in hits] if isinstance(hits, list) else hits
    check(isinstance(keys, list) and want in keys[:2], f"search {q!r}: {want} among the first two ({keys})")
hits = web_search(A, "Scan")
check(isinstance(hits, list) and hits and hits[0]["title"] == "Scan-Eingang einrichten" and hits[0]["area"] == "files" and hits[0]["snippet"],
      f"a hit: German title, area, snippet ({hits[:1]})")
check(isinstance(hits, list) and all("#how-to-" in h["key"] for h in hits), "the app's search lists the user's sections only")
check(web_search(A, "frobnicate teleporter") == [], "an unknown question: nothing")

# ---------------------------------------------------------------- the agents get the same text (#5819 tools)
tok = A.post(B + "/api/me/tokens", json={"name": "help", "scopes": ["read"]}).json()["token"]
ag = requests.Session()
ag.headers.update({"Authorization": "Bearer " + tok})
r = ag.get(V + "/search", params={"kind": "help", "q": "Scan-Eingang einrichten"}).json()
check(r["data"] and r["data"][0]["key"] == USCAN and r["data"][0].get("user") == "files", f"search_help: the user's section first ({[h['key'] for h in r['data'][:3]]})")
r = ag.get(V + "/search", params={"kind": "help", "q": "scan inbox folder"}).json()
dev = [h["key"] for h in r["data"] if not h.get("user")]
check(r["data"][0]["key"] == USCAN and dev[:1] == ["api#scan-inboxes-folder-watcher"], "English words: the user's section first, then the developer section")
rd = ag.get(V + "/help/section", params={"key": USCAN, "lang": "de"}).json()
check(rd.get("user") == "files" and "files.scan-inbox" in (rd.get("show") or []) and rd.get("translated", {}).get("text") == sec.get("text")
      and rd["translated"]["title"] == "Scan-Eingang einrichten", "read_help: the same German text as the app (translated)")
# 2.1086.0 (#5820 #5860): read_help's show is the list of a section's named places (#5860, MCP schema: array), the
# user's place among them - part B alone had a single key there
check(rd.get("text", "").startswith("## How to: Set up a scan inbox") and "**Create inbox**" in rd["text"], "read_help: the English source with its labels")
check("translated" not in ag.get(V + "/help/section", params={"key": USCAN, "lang": "en"}).json(), "lang en: no translated")
o = ag.get(V + "/help").json()
check("user" in o.get("how", ""), "the overview tells agents about the user's sections")

# ---------------------------------------------------------------- the lint of the user's help
r = subprocess.run([sys.executable, TOOL, "-v"], capture_output=True, text=True)
check(r.returncode == 0 and "0 finding(s)" in r.stdout, f"check_userhelp.py is green on the repository: {r.stdout[-400:]}")
r = subprocess.run([sys.executable, TOOL, "--src"], capture_output=True, text=True)
tool_keys = [ln.split(" ")[0] for ln in r.stdout.splitlines() if ln.strip()]
srv_keys = [s["key"] for a in A.get(B + "/api/help").json()["areas"] for s in a["sections"]]
check(sorted(tool_keys) == sorted(srv_keys) and len(srv_keys) >= 10, f"the lint and the server name the same sections ({len(tool_keys)} / {len(srv_keys)})")


def lint_copy(change):
    """The lint on a copy of docs/ + static/js + static/i18n with one change -> (exit code, output)."""
    tmp = tempfile.mkdtemp(prefix="uh5820-")
    try:
        for part in ("docs", os.path.join("static", "js"), os.path.join("static", "i18n")):
            shutil.copytree(os.path.join(ROOT, part), os.path.join(tmp, part), ignore=shutil.ignore_patterns("dev", "*.png", "*.jpg"))
        change(tmp)
        r = subprocess.run([sys.executable, TOOL, "--docs", os.path.join(tmp, "docs"), "--js", os.path.join(tmp, "static", "js"),
                            "--i18n", os.path.join(tmp, "static", "i18n")], capture_output=True, text=True)
        return r.returncode, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sub(path, a, b):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    assert a in s, (path, a)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s.replace(a, b))


rc, out = lint_copy(lambda t: None)
check(rc == 0, f"the lint on an unchanged copy: green ({out[-300:]})")
# a renamed button: the screen says "Create scan inbox" now, the help still "Create inbox"
rc, out = lint_copy(lambda t: sub(os.path.join(t, "static", "js", "docscan.js"), "tr('Create inbox')", "tr('Create scan inbox')"))
check(rc == 1 and "**Create inbox** is no text of the interface" in out, f"a renamed menu item turns the lint red: {out[-300:]}")
# the English text changed, the German translation not
rc, out = lint_copy(lambda t: sub(os.path.join(t, "docs", "FILES.md"), "Only you create a scan inbox, never an agent.",
                                  "Only you create a scan inbox, never an agent. It runs for one year."))
check(rc == 1 and USCAN in out and "older English text" in out, f"an outdated translation turns it red: {out[-300:]}")
# a German label the screen does not use
rc, out = lint_copy(lambda t: sub(os.path.join(t, "docs", "help", "de.md"), "**Scan-Eingang anlegen**", "**Eingang erstellen**"))
check(rc == 1 and "**Eingang erstellen**" in out, f"a German label that is not on the screen turns it red: {out[-300:]}")
# 2.1090.0 (#5899): a show line naming a place docs/help-targets.json does not know (was a warning that read the wrong keys)
rc, out = lint_copy(lambda t: sub(os.path.join(t, "docs", "FILES.md"), "<!-- show: files.scan-inbox -->", "<!-- show: files.scan-inbox -->\n<!-- show: files.nowhere -->"))
check(rc == 1 and "show target 'files.nowhere' is not in docs/help-targets.json" in out, f"an unknown show target turns it red: {out[-300:]}")
# a label split over two lines (it would escape the label check)
rc, out = lint_copy(lambda t: sub(os.path.join(t, "docs", "help", "de.md"), "**Ordner-Wächter**", "**Ordner-\nWächter**"))
check(rc == 1 and "split over two lines" in out, f"a label over two lines turns it red: {out[-300:]}")

# ================================================================ a person without an organisation
# a person without an organisation reads the same help (the routes are "public" in the freelancer matrix: no data of anybody)
FID, Fl = freelancer(B, A)
Fl.patch(B + "/api/settings", json={"lang": "de"})
r = Fl.get(B + "/api/help")
check(r.ok and [a["area"] for a in r.json()["areas"]][:1] == ["files"], "freelancer: GET /api/help")
r = Fl.get(B + "/api/help/section", params={"key": USCAN})
check(r.ok and r.json().get("text") == x_de and [x["target"] for x in r.json().get("steps") or []] == SCAN_SHOW,
      "freelancer: the German section with the steps of \"Zeig mir\" (2.1090.0, #5899)")
hits = web_search(Fl, "Scan")
check(isinstance(hits, list) and hits and hits[0]["key"] == USCAN, "freelancer: the app's search")
ft = Fl.post(B + "/api/me/tokens", json={"name": "help", "scopes": ["read"]}).json()["token"]
r = requests.get(V + "/search", params={"kind": "help", "q": "Scan-Eingang"}, headers={"Authorization": "Bearer " + ft}).json()
check(r["data"] and r["data"][0]["key"] == USCAN, "freelancer's token: search_help, the user's section first")

sys.exit(kt.done("p21072_b_help_api"))
