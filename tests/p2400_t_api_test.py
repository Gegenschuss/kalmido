#!/usr/bin/env python3
"""2.40.0 API tests (agent T), own container (start.sh).
 - #1416: the setting prio_bg ("Priority as background"): '' / soft / strong, anything else 400, per person
 - #1409: titles with Markdown are stored as typed (the source); md_plain (core/i18n.py) takes the marks out for push,
   ntfy and the calendar feed (SUMMARY); HTML in a title stays text; "Turn the open checklist items into subtasks"
   (PATCH content with _act md_subtasks) keeps the text before in the history (activity md_subtasks, data.prev, its own
   entry, never merged), a plain edit still logs "content" without the text
usage: p2400_t_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def py(code):
    p = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", code], capture_output=True, text=True)
    return p.stdout.strip(), p.stderr[-400:]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")

# ================================================================== #1416: prio_bg
st = lambda s: s.get(B + "/api/state").json()["settings"]  # noqa: E731
check(st(A).get("prio_bg", "") == "", "#1416: off by default")
for v in ("soft", "strong", ""):
    r = A.patch(B + "/api/settings", json={"prio_bg": v})
    check(r.ok and st(A).get("prio_bg") == v, f"#1416: prio_bg {v!r} is stored " + r.text[:120])
r = A.patch(B + "/api/settings", json={"prio_bg": "loud"})
check(r.status_code == 400, "#1416: an unknown value is refused " + r.text[:120])
A.patch(B + "/api/settings", json={"prio_bg": "strong"})
check(st(Bo).get("prio_bg", "") == "", "#1416: per person (bob keeps off)")

# ================================================================== #1409: titles keep their source, md_plain
L = A.post(B + "/api/lists", json={"name": "Project notes"}).json()["id"]
SRC = "**Master data:** read `.xlsx` and see [the docs](https://example.com/docs) ~~old~~"
t = A.post(B + "/api/tasks", json={"title": SRC, "list_id": L, "due": "2026-11-02"}).json()
check(t.get("title") == SRC, "#1409: the title is stored as typed " + repr(t.get("title")))
x = A.post(B + "/api/tasks", json={"title": "<img src=x onerror=alert(1)> [x](javascript:alert(1))", "list_id": L}).json()
check(x.get("title", "").startswith("<img"), "#1409: HTML in a title is kept as text (the app escapes it)")
out, e = py("from kalmido.core.i18n import md_plain as m; print('|'.join(m(x) for x in ["
            "'**Master data:** read `.xlsx`', '[the docs](https://example.com/docs) and *it* ~~old~~', '2*3 = 6 and a*b*c', "
            "r'\\*not\\*', '[x](javascript:alert(1))', 'plain']))")
check(out == "Master data: read .xlsx|the docs and it old|2*3 = 6 and a*b*c|*not*|[x](javascript:alert(1))|plain", "#1409: md_plain " + repr(out + e))
out, e = py("from kalmido.notify.push import webpush_payload as w; p = w('**Bold** [x](https://example.com)', 'Due · `code`', '4'); print(p['title'] + '|' + p['body'])")
check(out == "Bold x|Due · code", "#1409: a push shows the title without the marks " + repr(out + e))
r = A.post(B + "/api/ical", json={"action": "create"})
url = (r.json() or {}).get("url") or ""  # 2.138.0 (#1907): the feed link is only in the answer of create / rotate
check(bool(url), "#1409: calendar feed link (setup) " + r.text[:120])
if url:
    ics = requests.get(B + "/ical/" + url.rsplit("/ical/", 1)[-1]).text
    check("SUMMARY:Master data: read .xlsx and see the docs old" in ics.replace("\r\n ", ""), "#1409: the calendar feed has the plain title " + ics[:300])

# ================================================================== #1409: checklist -> subtasks keeps the text before
BEFORE = "Intro\n- [ ] one\n  more about one\n- [x] done"
p = A.post(B + "/api/tasks", json={"title": "Checklist", "list_id": L, "content": BEFORE}).json()["id"]
r = A.patch(B + f"/api/tasks/{p}", json={"content": "Intro\n- [x] done", "_act": "md_subtasks"})
check(r.ok and r.json()["content"] == "Intro\n- [x] done", "#1409: the description without the items " + r.text[:120])
acts = A.get(B + f"/api/tasks/{p}/timeline").json().get("activity", [])
ms = [a for a in acts if a["kind"] == "md_subtasks"]
check(len(ms) == 1 and ms[0]["data"].get("prev") == BEFORE, "#1409: the history keeps the text before " + repr(acts)[:300])
r = A.patch(B + f"/api/tasks/{p}", json={"content": "Intro\n- [x] done\nmore"})
acts = A.get(B + f"/api/tasks/{p}/timeline").json().get("activity", [])
check([a["kind"] for a in acts].count("md_subtasks") == 1 and any(a["kind"] == "content" and "prev" not in a["data"] for a in acts),
      "#1409: a plain edit logs 'content' without the text, the entry before stays " + repr([a["kind"] for a in acts]))
r = A.patch(B + f"/api/tasks/{p}", json={"content": BEFORE})
check(r.ok and r.json()["content"] == BEFORE, "#1409: restoring = a normal change of the description")
acts = A.get(B + f"/api/tasks/{p}/timeline").json().get("activity", [])
check([a["kind"] for a in acts].count("md_subtasks") == 1, "#1409: restoring does not add another md_subtasks entry")

print(f"p2400_t_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
