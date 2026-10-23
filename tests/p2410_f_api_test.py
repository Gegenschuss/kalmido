#!/usr/bin/env python3
"""2.41.0 API tests (agent F), own container (start.sh).
 - #1437: vCard import of large files: batches of 200 (each committed), the version row and the book are touched once per
   batch (a parallel write no longer waits for the end of the import), ?background=1 answers 202 {import_id} for a file of
   more than 100 cards and GET /api/books/imports/<id> tells the progress (only the person who started it); a small file
   and the REST API answer as before {created, updated, unchanged, errors}. PERF lines: 1,300 invented contacts with and
   without photos (generated here, no real data)
usage: p2410_f_api_test.py <datadir>"""
import base64
import os
import random
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def vcards(n, photos=False, prefix="lv", photo_bytes=1500):
    """n invented contacts (fictional names, example.com addresses); photos: random bytes (photo_bytes each; the test server
    takes at most 4 MB per request, TASKS_MAX_FILE_MB=1: 1.5 kB photos keep 1,300 cards below it)."""
    rnd = random.Random(7)
    giv = ["Anna", "Ben", "Clara", "Dario", "Eva", "Finn", "Greta", "Hugo", "Ida", "Jon"]
    fam = ["Muster", "Beispiel", "Probe", "Testmann", "Fiktiv", "Erfunden"]
    ph = base64.b64encode(bytes(rnd.getrandbits(8) for _ in range(photo_bytes))).decode() if photos else ""
    out = []
    for i in range(n):
        g, f = giv[i % len(giv)], fam[i % len(fam)]
        c = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:{g} {f} {i}", f"N:{f} {i};{g};;;", f"EMAIL:{g.lower()}.{i}@example.com",
             f"TEL:+49 30 {100000 + i}", f"BDAY:19{50 + i % 50}-0{1 + i % 9}-1{i % 9}" if i % 3 == 0 else "NOTE:fictional"]
        if ph:
            c.append("PHOTO;ENCODING=b;TYPE=JPEG:" + "\r\n ".join(ph[j:j + 74] for j in range(0, len(ph), 74)))
        c.append("END:VCARD")
        out.append("\r\n".join(c))
    return "\r\n".join(out) + "\r\n"


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "contacts"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")

# ================================================================== #1437: vCard import
BK = A.post(B + "/api/books", json={"name": "Big"}).json()["id"]
small = vcards(20, prefix="sm")
r = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("s.vcf", small, "text/vcard")})
# 2.119.1 (#2084): the answer also names the likely duplicates (dupes, dupe_groups)
check(r.status_code == 200 and {k: v for k, v in r.json().items() if k not in ("dupes", "dupe_groups")} == {"created": 20, "updated": 0, "unchanged": 0, "errors": 0}
      and r.json().get("dupes") == 0,
      f"#1437: a small file is answered at once in the old format {r.status_code} {r.text[:200]}")


def timed_write(out):
    time.sleep(0.8)
    t = time.time()
    rr = A.post(B + "/api/tasks", json={"title": "written while importing"})
    out.append((rr.status_code, time.time() - t))


for photos in (False, True):
    BKp = A.post(B + "/api/books", json={"name": f"Perf {photos}"}).json()["id"]
    text = vcards(1300, photos=photos, prefix="p" + str(int(photos)))
    side = []
    th = threading.Thread(target=timed_write, args=(side,))
    t0 = time.time()
    th.start()
    r = A.post(B + f"/api/books/{BKp}/import", files={"file": ("big.vcf", text, "text/vcard")})
    dt = time.time() - t0
    th.join()
    check(r.ok and r.json()["created"] == 1300, f"#1437: 1,300 contacts (photos {photos}) in the synchronous way {r.status_code} {r.text[:200]}")
    print(f"PERF #1437 sync import 1300 contacts photos={photos} size={len(text) // 1024} kB: {dt:.2f} s; a parallel task write took "
          f"{side[0][1]:.2f} s", flush=True)
    check(side and side[0][0] in (200, 201) and side[0][1] < max(1.5, dt * 0.6),
          f"#1437: a parallel write does not wait for the end of the import {side} (import {dt:.2f} s)")

# background
BG = A.post(B + "/api/books", json={"name": "Background"}).json()["id"]
text = vcards(1300, photos=True, prefix="bg")
t0 = time.time()
r = A.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
check(r.status_code == 202 and r.json().get("import_id") and r.json()["state"] == "running" and r.json()["total"] == 1300,
      f"#1437: a large file -> 202 with an import id {r.status_code} {r.text[:200]}")
iid = r.json().get("import_id", "x")
check(Bo.get(B + f"/api/books/imports/{iid}").status_code == 404, "#1437: someone else does not see the import")
seen, st = set(), {}
for _ in range(240):
    st = A.get(B + f"/api/books/imports/{iid}").json()
    seen.add(st.get("done"))
    if st.get("state") != "running":
        break
    time.sleep(0.25)
print(f"PERF #1437 background import 1300 contacts with photos: {time.time() - t0:.2f} s until done", flush=True)
check(st.get("state") == "done" and st["created"] == 1300 and st["done"] == 1300 and st["errors"] == 0 and st["ended_at"],
      f"#1437: the background import ends with its counts {st}")
check(len(seen) >= 2, f"#1437: the progress moves {sorted(x for x in seen if x is not None)}")
cnt = [b for b in A.get(B + "/api/books").json()["items"] if b["id"] == BG][0]["count"]
check(cnt == 1300, f"#1437: all contacts stored {cnt}")
r = A.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
iid2 = r.json().get("import_id")
for _ in range(240):
    st = A.get(B + f"/api/books/imports/{iid2}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.25)
check(st.get("state") == "done" and st["created"] == 0 and st["updated"] == 1300, f"#1437: importing twice updates, no doubles {st}")
# read-only member: no import
A.put(B + f"/api/books/{BG}/members", json={"user_id": 2, "role": "view"})
r = Bo.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
check(r.status_code == 403, f"#1437: a reader cannot import {r.status_code}")
check(A.get(B + "/api/books/imports/nope").status_code == 404, "#1437: unknown import id -> 404")
# a broken card among many: counted as not readable, the rest stored
bad = vcards(150, prefix="br") + "BEGIN:VCARD\r\nVERSION:3.0\r\nNOTE:no name\r\nEND:VCARD\r\n"
BB = A.post(B + "/api/books", json={"name": "Broken"}).json()["id"]
iid3 = A.post(B + f"/api/books/{BB}/import?background=1", files={"file": ("b.vcf", bad, "text/vcard")}).json().get("import_id")
for _ in range(120):
    st = A.get(B + f"/api/books/imports/{iid3}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.25)
check(st.get("state") == "done" and st["created"] == 150 and st["errors"] == 1, f"#1437: a card without a name is not readable {st}")

# ================================================================== #1383: answer buttons / approval cards in comments
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
Ca = sess("carol")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]} if A.get(B + "/api/users").ok else {}
L = A.post(B + "/api/lists", json={"name": "Agent work"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids.get("bob"), "role": "view"})
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids.get("carol"), "role": "edit"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x")}
A.put(B + f"/api/lists/{L}/members", json={"user_id": ag.get("id"), "role": "edit"})
T = A.post(B + "/api/tasks", json={"title": "Release the draft", "list_id": L}).json()["id"]
V = B + "/api/v1"


def agc(body):
    return requests.post(V + f"/tasks/{T}/comments", headers=AGH, json=body)


def evs(since):
    return requests.get(V + "/agent/events", headers=AGH, params={"since": since}).json().get("data", [])


seq0 = max([e.get("seq", 0) for e in evs(0)] or [0])
r = agc({"body": "Shall I publish the draft?", "approval": {"title": "Publish the draft", "what": "it goes online"}})
check(r.status_code == 201 and (r.json().get("choices") or {}).get("approval", {}).get("title") == "Publish the draft"
      and r.json().get("choice_state") == "open", f"#1383: an agent posts an approval card {r.status_code} {r.text[:300]}")
AP = r.json().get("id")
check(A.post(B + f"/api/tasks/{T}/comments", json={"body": "x", "choices": ["a", "b"]}).status_code == 403, "#1383: people post no buttons")
check(agc({"body": "may I?", "choices": ["allow", "deny"]}).status_code == 400, "#1383: no permission questions in comments (they belong to the chat)")
check(agc({"body": "bad", "choices": [{"id": "x y", "label": ""}]}).status_code == 400, "#1383: invalid buttons -> 400")
tl = A.get(B + f"/api/tasks/{T}/timeline").json()
c0 = [x for x in tl["comments"] if x["id"] == AP]
check(c0 and c0[0]["choice_state"] == "open" and c0[0]["choice"] is None, f"#1383: the timeline shows the open card {c0}")
check(Bo.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["yes"]}).status_code == 403, "#1383: a reader cannot answer")
check(requests.post(V + f"/comments/{AP}/choice", headers=AGH, json={"choice_ids": ["yes"]}).status_code == 403, "#1383: an agent never answers")
check(A.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["maybe"]}).status_code == 400, "#1383: unknown choice -> 400")
r = Ca.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["yes"]})
check(r.status_code == 403, f"#1383: an editor the agent does not take instructions from (#928) cannot answer {r.status_code}")
A.patch(B + f"/api/lists/{L}", json={"agent_members": True})  # "Members may see and use the agent"
# 2.144.5 (#2001): an approval card is decided only by an approver (list manager, assignee, admin): an editor alone gets
# 403 and sees no buttons (choice_can false); as the assignee Carol decides it
r = Ca.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["yes"]})
check(r.status_code == 403, f"#2001: an editor who is no approver cannot decide an approval card {r.status_code}")
c1 = [x for x in Ca.get(B + f"/api/tasks/{T}/timeline").json()["comments"] if x["id"] == AP]
check(c1 and c1[0].get("choice_can") is False, f"#2001: the editor's timeline says choice_can false {c1[:1]}")
A.patch(B + f"/api/tasks/{T}", json={"assignee_id": ids.get("carol")})
r = Ca.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["yes"]})
check(r.ok and r.json()["choice_state"] == "answered" and r.json()["choice"]["ids"] == ["yes"] and r.json()["choice"]["user_name"] == "Carol"
      and r.json()["answer_comment_id"] is None, f"#1383: the assignee answers yes {r.status_code} {r.text[:300]}")
check(A.post(B + f"/api/comments/{AP}/choice", json={"choice_ids": ["no"]}).status_code == 409, "#1383: the answer is written once")
acts = A.get(B + f"/api/tasks/{T}/timeline").json()["activity"]
check(any(a["kind"] == "choice" and a["data"].get("approval") == "approved" and a["data"].get("comment") == AP for a in acts),
      f"#1383: the answer is in the history {[a['kind'] for a in acts]}")
ev = [e for e in evs(seq0) if e["event"] == "comment" and (e["data"].get("answer") or {}).get("comment_id") == AP]
check(ev and ev[0]["data"]["answer"]["approval"] == "approved" and ev[0]["data"]["answer"]["user"]["name"] == "Carol",
      f"#1383: the agent hears the answer as a comment event {ev[:1]}")
g = A.get(B + f"/api/comments/{AP}/choice").json()
check(g.get("choice_state") == "answered", f"#1383: GET the state {g}")
# plain buttons / suggestions: only the newest is live (#1037); a press becomes the person's comment
q1 = agc({"body": "Which variant?", "choices": ["Short", "Long"]}).json().get("id")
ap2 = agc({"body": "Delete the old drafts?", "approval": {"title": "Delete old drafts"}}).json().get("id")
q2 = agc({"body": "And the colour?", "choices": [{"id": "blue", "label": "Blue"}, {"id": "green", "label": "Green"}], "multi": True}).json().get("id")
st = {x["id"]: x["choice_state"] for x in A.get(B + f"/api/tasks/{T}/timeline").json()["comments"]}
check(st.get(q1) == "expired" and st.get(q2) == "open" and st.get(ap2) == "open", f"#1383: a newer comment expires older buttons, not an approval card {st}")
check(A.post(B + f"/api/comments/{q1}/choice", json={"choice_ids": ["Short"]}).status_code == 409, "#1383: expired buttons -> 409")
seq1 = max([e.get("seq", 0) for e in evs(0)] or [0])
r = A.post(B + f"/api/comments/{q2}/choice", json={"choice_ids": ["green", "blue"]})
said = r.json().get("answer_comment_id") if r.ok else None
check(r.ok and r.json()["choice"]["ids"] == ["blue", "green"] and said, f"#1383: several with multi {r.status_code} {r.text[:200]}")
cm = [x for x in A.get(B + f"/api/tasks/{T}/timeline").json()["comments"] if x["id"] == said]
check(cm and cm[0]["body"] == "Blue, Green" and cm[0]["reply_to"] == q2, f"#1383: a pressed suggestion is sent as my comment {cm}")
ev = [e for e in evs(seq1) if e["event"] == "comment"]
check(len(ev) == 1 and ev[0]["data"]["answer"]["labels"] == ["Blue", "Green"] and ev[0]["data"]["comment"]["id"] == said,
      f"#1383: one comment event with the answer {[(e['event'], (e['data'].get('answer') or {}).get('labels')) for e in ev]}")
# the agent withdraws an approval card
r = requests.post(V + f"/comments/{ap2}/withdraw", headers=AGH, json={"outcome": "expired"})
check(r.ok and r.json().get("choice_state") == "expired", f"#1383: the agent withdraws its card {r.status_code} {r.text[:200]}")
check(A.post(B + f"/api/comments/{ap2}/choice", json={"choice_ids": ["yes"]}).status_code == 409, "#1383: a withdrawn card cannot be answered")
check(requests.post(V + f"/comments/{AP}/withdraw", headers=AGH, json={}).status_code == 409, "#1383: an answered card cannot be withdrawn")
# REST list carries the state
d = requests.get(V + f"/tasks/{T}/comments", headers=AGH).json()["data"]
check(any(x["id"] == AP and x["choice_state"] == "answered" and x["choice"]["ids"] == ["yes"] for x in d), "#1383: GET comments (REST) has the state")
# a person's token answers in the REST API too
TA = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "comments"]}).json().get("token", "x")
q3 = agc({"body": "Ok?", "choices": ["Yes", "Later"]}).json().get("id")
r = requests.post(V + f"/comments/{q3}/choice", headers={"Authorization": "Bearer " + TA}, json={"choice_ids": ["Later"]})
check(r.ok and r.json()["choice"]["ids"] == ["Later"], f"#1383: a person's token answers {r.status_code} {r.text[:200]}")

print(f"p2410_f_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
