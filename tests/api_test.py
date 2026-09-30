#!/usr/bin/env python3
"""API tests: comments, mentions, pushes (stub ntfy), activity, comment files, unread, link, IDOR, collab flag.
Runs against the TEST container (built-in login on 127.0.0.1:3048, data dir DATA). Fresh DB expected."""
import json, os, sys, time, subprocess
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def pushes():
    try:
        return [json.loads(l) for l in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def wait_pushes(n, timeout=6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = pushes()
        if len(p) >= n:
            return p
        time.sleep(0.2)
    return pushes()


def clear_pushes():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


# ---- setup
s0 = sess()
r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("carol", "Carol"), ("dave", "Dave"), ("eve", "Eve")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bb, C, D, E = sess("bob"), sess("carol"), sess("dave"), sess("eve")
Bb.patch(B + "/api/settings", json={"lang": "de"})
st = E.get(B + "/api/state").json()
check("collab" in st["settings"]["features"] and "links" not in st["settings"]["features"], "new users: collab on by default, no links flag")
E.patch(B + "/api/settings", json={"features": ",".join(f for f in st["settings"]["features"].split(",") if f != "collab")})
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for u, role in (("bob", "edit"), ("carol", "view"), ("eve", "edit")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role}).ok
PT = A.post(B + "/api/tasks", json={"title": "Private A"}).json()["id"]
PB = Bb.post(B + "/api/tasks", json={"title": "Private B"}).json()["id"]
ST = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": L, "assignee_id": ids["bob"]}).json()["id"]
p = wait_pushes(1)
check(len(p) == 1 and p[0]["topic"] == "t-bob" and p[0]["title"] == "Alice hat dir zugewiesen: Shared task" and p[0]["msg"] == "Shared",
      f"create with assignee: German assign push to bob: {p}")
time.sleep(3.3)
clear_pushes()

# ---- comments + mentions + pushes
v0 = A.get(B + "/api/version").json()["v"]
r = A.post(B + f"/api/tasks/{ST}/comments", json={"body": f"Hello <@{ids['bob']}>, see <@{ids['dave']}>"})
check(r.ok, "A comments on shared task")
c1 = r.json()
check(c1["mentions"] == [ids["bob"]], "mentions: only people who see the task (dave dropped)")
check("@Dave" in c1["body"] and f"<@{ids['dave']}>" not in c1["body"], "invisible mention becomes plain @name")
check(A.get(B + "/api/version").json()["v"] > v0, "comment bumps the version")
p = wait_pushes(1)
check(len(p) == 1 and p[0]["topic"] == "t-bob", f"push only to bob (assignee), got {[x['topic'] for x in p]}")
if p:
    check(p[0]["msg"].startswith("Alice hat dich erwähnt:"), f"bob's push in German + mention: {p[0]['msg']!r}")
    check(p[0]["click"].endswith(f"/#t/{ST}"), "click url opens the task")
    check(p[0]["title"] == "Shared task", "push title = task title")
# view-only carol can comment, cannot change the task
r = C.post(B + f"/api/tasks/{ST}/comments", json={"body": "view-only here"})
check(r.ok, "view-only member can comment")
c2 = r.json()
check(C.patch(B + f"/api/tasks/{ST}", json={"title": "x"}).status_code == 403, "view-only cannot change the task")
p = wait_pushes(2)
check([x["topic"] for x in p[1:]] == ["t-alice"], f"carol's comment: push to alice now, bob in burst window: {[x['topic'] for x in p]}")
if len(p) > 1:
    check(p[1]["msg"].startswith("Carol commented:"), f"alice push English: {p[1]['msg']!r}")
# burst summary for bob (gap = 3 s in the test container, watchdog every 1 s)
p = wait_pushes(3, timeout=10)
check(len(p) >= 3 and p[2]["topic"] == "t-bob" and "1 weiterer Kommentar" in p[2]["msg"], f"bob summary push: {p[2:] if len(p) > 2 else p}")
# mention of a non-participant (carol is only a view member, not a participant yet... she commented; use eve collab off)
clear_pushes()
time.sleep(3.2)
r = Bb.post(B + f"/api/tasks/{ST}/comments", json={"body": f"<@{ids['eve']}> and <@{ids['carol']}> look"})
c3 = r.json()
check(set(c3["mentions"]) == {ids["eve"], ids["carol"]}, "bob mentions eve + carol")
p = wait_pushes(2)
tops = sorted(x["topic"] for x in p)
check("t-eve" not in tops, "collab off: eve gets no push")
check(tops == ["t-alice", "t-carol"], f"recipients alice (creator/commenter) + carol (mention): {tops}")
cm = [x for x in p if x["topic"] == "t-carol"]
check(cm and cm[0]["msg"].startswith("Bob mentioned you:") and "@Eve and @Carol look" in cm[0]["msg"], f"carol mention push text: {cm}")
# dave (no access) mentioned by name token -> nothing
clear_pushes()
time.sleep(3.2)
A.post(B + f"/api/tasks/{PT}/comments", json={"body": "note to self"})
time.sleep(1.5)
check(pushes() == [], "private task comment: no push (only the owner)")
# mention on edit notifies only newly mentioned
clear_pushes()
time.sleep(3.2)
r = A.patch(B + f"/api/comments/{c1['id']}", json={"body": f"Hello <@{ids['bob']}> and <@{ids['carol']}>"})
check(r.ok and r.json()["edited_at"], "author edits own comment (edited_at set)")
p = wait_pushes(1)
time.sleep(0.8)
p = pushes()
check([x["topic"] for x in p] == ["t-carol"], f"edit: only newly mentioned carol notified: {[x['topic'] for x in p]}")

# ---- edit / delete rights
check(Bb.patch(B + f"/api/comments/{c1['id']}", json={"body": "hijack"}).status_code == 403, "others cannot edit a comment")
check(Bb.delete(B + f"/api/comments/{c1['id']}").status_code == 403, "edit member cannot delete others' comment")
check(C.delete(B + f"/api/comments/{c3['id']}").status_code == 403, "view member cannot delete others' comment")
check(A.patch(B + f"/api/comments/{c2['id']}", json={"body": "x"}).status_code == 403, "list owner cannot EDIT others' comment")
check(A.delete(B + f"/api/comments/{c2['id']}").ok, "list owner may delete (moderation)")
tl = A.get(B + f"/api/tasks/{ST}/timeline").json()
check(c2["id"] not in [c["id"] for c in tl["comments"]], "deleted comment disappears")
check(C.patch(B + f"/api/comments/{c2['id']}", json={"body": "back"}).status_code == 404, "deleted comment cannot be edited")
check(C.post(B + f"/api/tasks/{ST}/comments", json={"body": "  "}).status_code == 400, "empty comment rejected")
check(C.post(B + f"/api/tasks/{ST}/comments", json={"body": "x" * 10001}).status_code == 400, "too long comment rejected")

# ---- mention picker / people
ppl = {p["id"] for p in tl["people"]}
check(ppl == {ids["alice"], ids["bob"], ids["carol"], ids["eve"]}, f"picker = users who see the task: {ppl}")
ppl2 = {p["id"] for p in A.get(B + f"/api/tasks/{PT}/timeline").json()["people"]}
check(ppl2 == {ids["alice"]}, "picker on a private task = only the owner")

# ---- IDOR
for who, S_, tid in (("dave", D, ST), ("bob", Bb, PT), ("carol", C, PT)):
    check(S_.get(B + f"/api/tasks/{tid}/timeline").status_code == 404, f"{who}: timeline of invisible task 404")
    check(S_.post(B + f"/api/tasks/{tid}/comments", json={"body": "x"}).status_code == 404, f"{who}: comment on invisible task 404")
    check(S_.post(B + f"/api/tasks/{tid}/seen").status_code == 404, f"{who}: seen on invisible task 404")
pc = A.get(B + f"/api/tasks/{PT}/timeline").json()["comments"][0]["id"]
check(Bb.patch(B + f"/api/comments/{pc}", json={"body": "x"}).status_code == 404, "bob: edit comment on A's private task 404")
check(Bb.delete(B + f"/api/comments/{pc}").status_code == 404, "bob: delete comment on A's private task 404")
check(D.patch(B + f"/api/comments/{c1['id']}", json={"body": "x"}).status_code == 404, "dave: edit comment in list he cannot see 404")
check(D.delete(B + f"/api/comments/{c1['id']}").status_code == 404, "dave: delete comment in list he cannot see 404")
check(A.get(B + f"/api/tasks/{PB}/timeline").status_code == 404, "admin alice cannot read bob's private timeline")
check(A.post(B + f"/api/comments/{pc}", json={}).status_code in (404, 405), "no POST on comment id")
# CSRF header required
check(requests.post(B + f"/api/tasks/{ST}/comments", json={"body": "x"}, cookies=A.cookies).status_code == 403, "CSRF: comment without header blocked")

# ---- comment files
png = b"\x89PNG\r\n\x1a\n" + b"\0" * 100
r = C.post(B + f"/api/tasks/{ST}/comments", data={"body": "files"}, files=[("file", ("pic.png", png, "image/png")), ("file", ("n.txt", b"hello", "text/plain")), ("file", ("x.svg", b"<svg/>", "image/svg+xml"))])
check(r.ok and len(r.json()["attachments"]) == 3, "view-only member posts a comment with 3 files")
cf = r.json()
att = {a["name"]: a for a in cf["attachments"]}
state_t = [t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == ST][0]
check(state_t["attachments"] == [], "comment files are NOT in the task's attachment list")
g = Bb.get(B + f"/api/attachments/{att['pic.png']['id']}")
check(g.ok and g.headers["Content-Type"].startswith("image/png") and "sandbox" in g.headers.get("Content-Security-Policy", ""), "image inline with sandbox CSP")
g = Bb.get(B + f"/api/attachments/{att['x.svg']['id']}")
check(g.ok and "attachment" in g.headers.get("Content-Disposition", "") and g.headers["Content-Type"].startswith("application/octet-stream"), "svg in a comment served as download")
check(D.get(B + f"/api/attachments/{att['pic.png']['id']}").status_code == 404, "dave cannot download comment file")
check(requests.get(B + f"/api/attachments/{att['pic.png']['id']}").status_code == 401, "anonymous cannot download comment file")
check(Bb.delete(B + f"/api/attachments/{att['n.txt']['id']}").status_code == 403, "edit member cannot delete someone else's comment file")
check(A.post(B + f"/api/attachments/{att['n.txt']['id']}/to-paperless").status_code == 400, "comment file cannot go to Paperless")
check(C.delete(B + f"/api/attachments/{att['n.txt']['id']}").ok, "author removes one file from own comment")
paths = [os.path.join(DATA, "attachments", str(ST))]
nfiles = lambda: sum(len(fs) for _, _, fs in os.walk(os.path.join(DATA, "attachments")))
n_before = nfiles()
check(C.delete(B + f"/api/comments/{cf['id']}").ok, "author deletes comment with files")
check(nfiles() == n_before - 2, f"comment files unlinked on delete ({n_before} -> {nfiles()})")
check(Bb.get(B + f"/api/attachments/{att['pic.png']['id']}").status_code == 404, "file of deleted comment 404")
# size limit (container TASKS_MAX_FILE_MB=1): no comment, no file left
n_before, cnt_before = nfiles(), len(A.get(B + f"/api/tasks/{ST}/timeline").json()["comments"])
r = C.post(B + f"/api/tasks/{ST}/comments", data={"body": "big"}, files=[("file", ("a.bin", b"a" * 1000, "application/octet-stream")), ("file", ("big.bin", b"x" * (1024 * 1024 + 10), "application/octet-stream"))])
check(r.status_code == 400, f"too large file rejected ({r.status_code})")
check(nfiles() == n_before and len(A.get(B + f"/api/tasks/{ST}/timeline").json()["comments"]) == cnt_before, "rejected upload leaves no comment and no files")

# ---- unread
clear_pushes()
st = A.get(B + "/api/state").json()
t = [x for x in st["tasks"] if x["id"] == ST][0]
check(t["unread"] >= 1 and t["comment_count"] >= 2, f"alice sees unread comments ({t['unread']}/{t['comment_count']})")
A.post(B + f"/api/tasks/{ST}/seen")
t = [x for x in A.get(B + "/api/state").json()["tasks"] if x["id"] == ST][0]
check(t["unread"] == 0, "seen clears unread")
A.post(B + f"/api/tasks/{ST}/comments", json={"body": "my own"})
t = [x for x in A.get(B + "/api/state").json()["tasks"] if x["id"] == ST][0]
check(t["unread"] == 0, "own comment is not unread")
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["id"] == ST][0]
check(t["unread"] >= 1, "bob sees alice's comment as unread")
Bb.post(B + f"/api/tasks/{ST}/seen")
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["id"] == ST][0]
check(t["unread"] == 0, "bob seen")
t = [x for x in C.get(B + "/api/state").json()["tasks"] if x["id"] == ST][0]
check(t["unread"] >= 1, "carol still unread (per user)")

# ---- activity
T = A.post(B + "/api/tasks", json={"title": "Act", "list_id": L}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Other"}).json()["id"]
A.post(B + f"/api/lists/{L2}/members", json={})
A.put(B + f"/api/lists/{L2}/members", json={"user_id": ids["bob"], "role": "edit"})
sec = A.post(B + "/api/sections", json={"list_id": L, "name": "Col"}).json()["id"]
P = A.post(B + "/api/tasks", json={"title": "Parent", "list_id": L}).json()["id"]
A.patch(B + f"/api/tasks/{T}", json={"title": "Act 2"})
A.patch(B + f"/api/tasks/{T}", json={"title": "Act 3"})  # merged
A.patch(B + f"/api/tasks/{T}", json={"content": "desc"})
A.patch(B + f"/api/tasks/{T}", json={"due": "2026-10-02", "due_time": "10:00"})
Bb.patch(B + f"/api/tasks/{T}", json={"due": "2026-10-03", "due_time": "11:00", "_act": "snooze"})
A.patch(B + f"/api/tasks/{T}", json={"priority": 5})
A.patch(B + f"/api/tasks/{T}", json={"assignee_id": ids["bob"]})
A.patch(B + f"/api/tasks/{T}", json={"section_id": sec})
A.patch(B + f"/api/tasks/{T}", json={"repeat": "FREQ=WEEKLY"})
A.patch(B + f"/api/tasks/{T}", json={"url": "https://github.com/x/y"})
A.patch(B + f"/api/tasks/{T}", json={"pinned": 1, "sort": 5, "reminders": "15"})  # noise: nothing
A.post(B + f"/api/tasks/{T}/skip")
A.post(B + f"/api/tasks/{T}/complete", json={})  # recurring -> next occurrence
A.patch(B + f"/api/tasks/{T}", json={"repeat": ""})
A.post(B + f"/api/tasks/{T}/complete", json={})
A.post(B + f"/api/tasks/{T}/reopen")
A.post(B + f"/api/tasks/{T}/complete", json={"status": -1})
A.post(B + f"/api/tasks/{T}/reopen")
A.post(B + f"/api/tasks/{T}/attachments", files=[("file", ("doc.pdf", b"%PDF-1.4", "application/pdf"))])
aid = [t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T][0]["attachments"][0]["id"]
A.delete(B + f"/api/attachments/{aid}")
A.post(B + "/api/tasks", json={"title": "Child", "parent_id": T})
A.patch(B + f"/api/tasks/{T}", json={"parent_id": P})
A.patch(B + f"/api/tasks/{T}", json={"parent_id": None})
A.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
A.post(B + "/api/tasks/batch", json={"ids": [T], "action": "patch", "data": {"priority": 1}})
A.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "sort": 3}]})  # sort only: nothing
A.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "due": "2026-11-01"}]})
A.delete(B + f"/api/tasks/{T}")
A.post(B + f"/api/tasks/{T}/restore")
acts = A.get(B + f"/api/tasks/{T}/timeline").json()["activity"]
kinds = [a["kind"] for a in acts]
print("activity kinds:", kinds)
for k in ("created", "title", "content", "due", "snooze", "priority", "assign", "section", "repeat", "link", "skip", "complete",
          "wont", "reopen", "attach", "attach_rm", "subtask", "parent", "list", "delete", "restore"):
    check(k in kinds, f"activity logs {k}")
check(kinds.count("title") == 1 and [a for a in acts if a["kind"] == "title"][0]["data"]["to"] == "Act 3", "title edits merged into one entry")
check(any(a["kind"] == "snooze" and a["user_id"] == ids["bob"] for a in acts), "snooze by bob logged with bob as actor")
check(any(a["kind"] == "complete" and a["data"].get("next") for a in acts), "recurring completion logs the next occurrence")
check(not any(a["kind"] in ("pinned", "sort", "reminders") for a in acts), "no noise entries")
check(any(a["kind"] == "due" and a["data"].get("due") == "2026-11-01" for a in acts), "reorder with a new due date logged")
check(A.get(B + f"/api/tasks/{P}/timeline").json()["activity"][0]["kind"] == "created", "parent has its own history")
# comments on a task in the trash
A.delete(B + f"/api/tasks/{T}")
check(A.post(B + f"/api/tasks/{T}/comments", json={"body": "x"}).status_code == 409, "no comments on a trashed task")
A.post(B + f"/api/tasks/{T}/restore")

# ---- link field
check(A.patch(B + f"/api/tasks/{PT}", json={"url": "ftp://x.org"}).status_code == 400, "ftp link rejected")
check(A.patch(B + f"/api/tasks/{PT}", json={"url": "javascript:alert(1)"}).status_code == 400, "javascript: link rejected")
check(A.post(B + "/api/tasks", json={"title": "bad", "url": "data:text/html,x"}).status_code == 400, "data: link rejected on create")
r = A.patch(B + f"/api/tasks/{PT}", json={"url": "https://example.org/page?q=1"})
check(r.ok and r.json()["url"] == "https://example.org/page?q=1", "valid link stored")
check(A.patch(B + f"/api/tasks/{PT}", json={"url": ""}).json()["url"] is None, "empty link clears it")
A.patch(B + f"/api/tasks/{PT}", json={"url": "https://docs.example.net/x"})
res = A.get(B + "/api/tasks", params={"scope": "search", "q": "docs.example"}).json()["tasks"]
check([t["id"] for t in res] == [PT], "search matches the link")
exp = A.get(B + "/api/export.json").json()
check(any(t["id"] == PT and t["url"] == "https://docs.example.net/x" for t in exp["tasks"]), "export contains the link")
check("comments" in exp and "activity" in exp and any(c["task_id"] == ST for c in exp["comments"]), "export contains comments + activity")
# /drop + /share with links
tok = Bb.get(B + "/api/me").json()["drop_token"]
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, data={"text": "Read this https://github.com/abc/def."})
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["title"] == "Read this"]
check(t and t[0]["url"] == "https://github.com/abc/def", f"/drop: link into the field, removed from the title ({r.text.strip()})")
requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, data={"text": "https://www.example.com/some/path/"})
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x.get("url") == "https://www.example.com/some/path/"]
check(t and t[0]["title"] == "example.com/some/path", f"/drop only a URL: title = domain + path ({t[0]['title'] if t else None})")
requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, data={"text": "Title line\nbody with https://x.org/a link"})
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["title"] == "Title line"]
check(t and t[0]["url"] == "https://x.org/a" and "https://x.org/a" in t[0]["content"], "/drop: URL in the body -> link field, body unchanged")
requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, data={"text": "No link here"})
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["title"] == "No link here"]
check(t and t[0]["url"] is None, "/drop without a link unchanged")
r = Bb.post(B + "/share", data={"title": "", "text": "Cool page https://news.example.org/item?id=5", "url": ""}, allow_redirects=False)
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x["title"] == "Cool page"]
check(r.status_code == 303 and t and t[0]["url"] == "https://news.example.org/item?id=5" and t[0]["content"] == "", "POST /share: link field, title without URL")
r = Bb.post(B + "/share", data={"title": "", "text": "", "url": "https://only.example.org/p"}, allow_redirects=False)
t = [x for x in Bb.get(B + "/api/state").json()["tasks"] if x.get("url") == "https://only.example.org/p"]
check(t and t[0]["title"] == "only.example.org/p", "POST /share only url: title domain + path")
acts = Bb.get(B + f"/api/tasks/{t[0]['id']}/timeline").json()["activity"] if t else []
check([a["kind"] for a in acts] == ["created"] and acts[0]["user_id"] == ids["bob"], "shared task has a 'created' entry by its user")

# ---- collab flag off: API still works for eve
r = E.post(B + f"/api/tasks/{ST}/comments", json={"body": "eve via API"})
check(r.ok, "collab off: API keeps working")

# ---- user delete: comments stay, author cleared
tmp = A.post(B + "/api/users", json={"username": "tmpu", "display_name": "Tmp", "password": "password123"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": tmp, "role": "view"})
TU = sess("tmpu")
cid = TU.post(B + f"/api/tasks/{ST}/comments", json={"body": "bye"}).json()["id"]
A.delete(B + f"/api/users/{tmp}")
cc = [c for c in A.get(B + f"/api/tasks/{ST}/timeline").json()["comments"] if c["id"] == cid]
check(cc and cc[0]["user_id"] is None, "deleted user's comment stays, author cleared")

# ---- hard delete removes comment files
X = A.post(B + "/api/tasks", json={"title": "Hard", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{X}/comments", data={"body": "f"}, files=[("file", ("a.txt", b"x", "text/plain"))])
n_before = nfiles()
A.delete(B + f"/api/tasks/{X}", params={"hard": "1"})
check(nfiles() == n_before - 1, "hard delete unlinks comment files")

# ---- task event pushes (assign / unassign / complete), shared burst rule
GAP = 3.3
time.sleep(GAP + 1.5); clear_pushes()  # summaries of the earlier comment tests are through
today = time.strftime("%Y-%m-%d")
EV1 = A.post(B + "/api/tasks", json={"title": "EV1", "list_id": L, "due": today, "due_time": "18:30"}).json()["id"]
A.patch(B + f"/api/tasks/{EV1}", json={"assignee_id": ids["bob"]})
p = wait_pushes(1); time.sleep(0.5); p = pushes()
check([x["topic"] for x in p] == ["t-bob"] and p[0]["title"] == "Alice hat dir zugewiesen: EV1" and p[0]["msg"] == "Shared · fällig heute 18:30"
      and p[0]["click"].endswith(f"#t/{EV1}"), f"assign push (German, list + due): {p}")
clear_pushes()
EV2 = A.post(B + "/api/tasks", json={"title": "EV2", "list_id": L}).json()["id"]
Bb.patch(B + f"/api/tasks/{EV2}", json={"assignee_id": ids["bob"]})
time.sleep(1)
check(pushes() == [], "self-assignment: no push")
time.sleep(GAP); clear_pushes()
A.patch(B + f"/api/tasks/{EV1}", json={"assignee_id": ids["carol"]})
p = wait_pushes(2); time.sleep(0.5); p = pushes()
got = {x["topic"]: x for x in p}
check(set(got) == {"t-bob", "t-carol"}, f"reassign: carol (assign) + bob (unassign): {list(got)}")
check(got.get("t-carol", {}).get("title") == "Alice assigned you: EV1", "carol assign push English")
check(got.get("t-bob", {}).get("title") == "Alice hat deine Zuweisung aufgehoben: EV1", f"bob unassign push German: {got.get('t-bob')}")
time.sleep(GAP); clear_pushes()
A.patch(B + f"/api/tasks/{EV1}", json={"assignee_id": None})
p = wait_pushes(1); time.sleep(0.5); p = pushes()
check([x["topic"] for x in p] == ["t-carol"] and "unassigned you from: EV1" in p[0]["title"], f"unassign push to previous assignee only: {p}")
acts = A.get(B + f"/api/tasks/{EV1}/timeline").json()["activity"]
check([(a["data"].get("to"), a["data"].get("from")) for a in acts if a["kind"] == "assign"][-1] == (None, ids["carol"]), "activity: assign with from/to")
# complete: dedupe creator + assigner
time.sleep(GAP); clear_pushes()
EV4 = A.post(B + "/api/tasks", json={"title": "EV4", "list_id": L, "assignee_id": ids["bob"]}).json()["id"]
time.sleep(GAP); clear_pushes()
Bb.post(B + f"/api/tasks/{EV4}/complete", json={})
p = wait_pushes(1); time.sleep(0.7); p = pushes()
check([x["topic"] for x in p] == ["t-alice"] and p[0]["title"] == "Bob completed: EV4" and p[0]["msg"] == "Shared", f"complete: one push to alice (creator+assigner deduped): {p}")
clear_pushes()
EV3 = Bb.post(B + "/api/tasks", json={"title": "EV3", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{EV3}/complete", json={})
p = wait_pushes(1); time.sleep(0.5); p = pushes()
check([x["topic"] for x in p] == ["t-bob"] and p[0]["title"] == "Alice hat erledigt: EV3", f"complete push to the creator (German): {p}")
clear_pushes()
EV6 = A.post(B + "/api/tasks", json={"title": "EV6", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{EV6}/complete", json={})
EV7 = E.post(B + "/api/tasks", json={"title": "EV7", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{EV7}/complete", json={})
PV = A.post(B + "/api/tasks", json={"title": "PV"}).json()["id"]
A.post(B + f"/api/tasks/{PV}/complete", json={})
A.post(B + "/api/tasks/batch", json={"ids": [EV2], "action": "complete"})  # bob assigned himself, alice created
time.sleep(1.2)
p = pushes()
check([x["topic"] for x in p] == ["t-bob"] and p[0]["title"] == "Alice hat erledigt: EV2",
      f"own completion / collab-off creator / private list: no push; batch complete notifies bob (self-assigner): {[(x['topic'], x['title']) for x in p]}")
# shared burst: assign, then a comment and a reassign within the gap -> one summary
time.sleep(GAP); clear_pushes()
EV5 = A.post(B + "/api/tasks", json={"title": "EV5", "list_id": L}).json()["id"]
A.patch(B + f"/api/tasks/{EV5}", json={"assignee_id": ids["bob"]})
A.post(B + f"/api/tasks/{EV5}/comments", json={"body": "context"})
p = wait_pushes(1); time.sleep(0.5)
check([x["title"] for x in pushes()] == ["Alice hat dir zugewiesen: EV5"], f"burst: comment right after the assignment is held back: {pushes()}")
A.patch(B + f"/api/tasks/{EV5}", json={"title": "EV5b"})  # not a push event
C.post(B + f"/api/tasks/{EV5}/complete", json={})  # view-only -> 403, nothing
Bb.patch(B + f"/api/tasks/{EV5}", json={"due": today})
A.post(B + f"/api/tasks/{EV5}/comments", json={"body": f"and <@{ids['bob']}> once more"})
p = wait_pushes(2, timeout=10)
check(len(p) == 2 and p[1]["topic"] == "t-bob" and p[1]["msg"] == "2 weitere Kommentare · du wurdest erwähnt" and p[1]["title"] == "EV5b", f"burst summary: {p}")
time.sleep(GAP); clear_pushes()
A.patch(B + f"/api/tasks/{EV5}", json={"assignee_id": ids["carol"]})
Bb.post(B + f"/api/tasks/{EV5}/comments", json={"body": "ok"})
p = wait_pushes(4, timeout=10)
check(any(x["topic"] == "t-alice" and x["msg"] == "Bob commented: ok" for x in p), "alice (creator, commenter) gets bob's comment")
bobs = [x for x in p if x["topic"] == "t-bob"]
check(len(bobs) == 1 and "aufgehoben" in bobs[0]["title"], "bob: unassign push, own comment does not notify himself")
car = [x for x in p if x["topic"] == "t-carol"]
check(len(car) == 2 and car[0]["title"] == "Alice assigned you: EV5b" and car[1]["msg"] == "1 more comment", f"carol: assign push, then the comment in the summary: {car}")
# collab off: eve assigned -> no push
time.sleep(GAP); clear_pushes()
A.patch(B + f"/api/tasks/{EV5}", json={"assignee_id": ids["eve"]})
time.sleep(1.2)
check([x["topic"] for x in pushes()] == ["t-carol"], f"collab off: eve not notified (only carol's unassign): {[x['topic'] for x in pushes()]}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
json.dump({"ids": ids, "ST": ST, "PT": PT, "L": L}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ids.json"), "w"))
sys.exit(1 if FAILS else 0)
