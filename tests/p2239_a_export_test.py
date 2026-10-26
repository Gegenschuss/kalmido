#!/usr/bin/env python3
"""2.239.0 API tests, part A (#2882): the account export holds what I wrote outside my own lists, GET /api/export.json is
filtered like it, people.json hashes are keyed per export. A fresh container; invented names only (example.com).
freelancer-matrix: own
 - bob comments in alice's list that everyone in the organisation sees (no membership): his comment is in his ZIP
   (written_comments), carol's comment on the same task is not; his message in an organisation channel is in it
   (channel_messages), the task he created there too (other_tasks); devices without secrets (sessions, push_devices)
 - alice's export.json: no webhook address (url_hint only), no server-side setting (ntfy_topic)
 - people.json: email_hash is HMAC-SHA256 with the file's people_salt, never the plain SHA-256 of the address; the
   import still finds the person by it (preview found) and names the salt for the client's address check
 - a person without an organisation gets the account export as before (own comment, the new tables empty)
usage: p2239_a_export_test.py <datadir>      (a fresh server: run_all.sh "fresh")"""
import hashlib
import hmac
import io
import json
import os
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}


def EH(email):  # the unkeyed form of older files
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def EHS(email, salt):  # 2.239.0 A (#2882): the keyed form of the account export
    return hmac.new(salt.encode(), ("kalmido-people|" + email.strip().lower()).encode(), hashlib.sha256).hexdigest()


def export_of(s, secs=120):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = {}
    for _ in range(secs * 4):  # polls the export's state until it is no longer running
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = s.get(B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return r.content, json.loads(z.read("manifest.json")), {n[5:-5]: json.loads(z.read(n)) for n in z.namelist() if n.startswith("data/")}


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "time_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
UID = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "orgs": [ORG]})
    assert r.ok, r.text
    UID[u] = r.json().get("id") or r.json().get("user", {}).get("id")
Bo, Ca = login(B, "bob"), login(B, "carol")
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ================================================================== alice's list, seen by everyone in the organisation
OL = A.post(B + "/api/lists", json={"name": "Nordwind board", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/lists/{OL}", json={"org_visibility": "org", "org_edit": 1}).ok, "setup: everyone in the organisation may edit")
OT = A.post(B + "/api/tasks", json={"list_id": OL, "title": "Plan the launch"}).json()["id"]
r = Bo.post(B + f"/api/tasks/{OT}/comments", json={"body": "Bob writes zq81"})
check(r.status_code in (200, 201), f"setup: bob comments without membership {r.status_code} {r.text[:200]}")
r = Ca.post(B + f"/api/tasks/{OT}/comments", json={"body": "Carol writes zq82"})
check(r.status_code in (200, 201), f"setup: carol comments {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/tasks", json={"list_id": OL, "title": "Bob org task zq83"})
check(r.status_code in (200, 201), f"setup: bob creates a task in alice's list {r.status_code} {r.text[:200]}")
BT = r.json().get("id") if r.ok else None
r = Bo.post(B + "/api/team/channels", json={"name": "Studio", "org_id": ORG})
check(r.status_code in (200, 201), f"setup: bob opens a channel {r.status_code} {r.text[:200]}")
RID = (r.json().get("id") or (r.json().get("room") or {}).get("id")) if r.ok else None
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Channel note zq84"})
check(r.status_code in (200, 201), f"setup: bob writes in the channel {r.status_code} {r.text[:200]}")

# ================================================================== bob's account export
EXP, MAN, D = export_of(Bo)
wc = D.get("written_comments", [])
check(any(x["body"] == "Bob writes zq81" and x["task_id"] == OT and x.get("task_title") == "Plan the launch" for x in wc),
      f"#2882: bob's comment in a list without membership is in his export {wc}")
check(b"Carol writes zq82" not in EXP and not any("zq82" in json.dumps(rows) for rows in D.values()),
      "#2882: carol's comment on the same task is not in bob's export")
cm = D.get("channel_messages", [])
check(any(x["body"] == "Channel note zq84" and x["room_id"] == RID for x in cm), f"#2882: bob's channel message is in it {cm}")
check(not any(x.get("room_kind") == "dm" for x in cm), "#2882: direct messages stay in direct_messages")
ot = D.get("other_tasks", [])
check(any(x["id"] == BT and x["title"] == "Bob org task zq83" for x in ot) and not any(x["id"] == OT for x in ot),
      f"#2882: the task bob created in alice's list is in it, alice's own task not {[x.get('title') for x in ot]}")
ss = D.get("sessions", [])
check(len(ss) >= 1 and all(set(x) <= {"created_at", "expires_at", "via", "last_seen_at", "user_agent"} for x in ss),
      f"#2882: sessions without their token {ss[:1]}")
check("push_devices" in D and all("endpoint" not in x and "p256dh" not in x and "auth" not in x for x in D["push_devices"]),
      "#2882: push devices without address and keys")
check(all(t in D for t in ("notifications", "reactions", "task_people", "kid_stars")), f"#2882: the new personal parts {sorted(D)}")
check(any("lists you can no longer see" in x for x in MAN.get("not_included", [])), "#2882: the manifest names what stays out")

# ================================================================== alice: people.json + export.json
WHU = "https://hooks.example.com/services/T000/Hookpfad2239"
check(A.post(B + "/api/me/webhooks", json={"name": "Hook", "url": WHU, "events": ["task.created"]}).status_code == 201, "setup: a webhook")
check(A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "topic2239a"}).ok, "setup: ntfy topic (admin)")
EJ = A.get(B + "/api/export.json")
check(EJ.ok and WHU not in EJ.text and "Hookpfad2239" not in EJ.text, "#2882: export.json without the webhook address")
ej = EJ.json() if EJ.ok else {}
check(any(x.get("url_hint") and "url" not in x for x in ej.get("webhooks", [])), "#2882: export.json names the webhook by url_hint")
check("topic2239a" not in EJ.text and not any(x.get("key") == "ntfy_topic" for x in ej.get("settings", [])),
      "#2882: export.json without server-side settings")
check(any(t["id"] == OT for t in ej.get("tasks", [])), "export.json keeps the own tasks")
EXP, MAN, D = export_of(A)
salt = MAN.get("people_salt") or ""
pb = [p for p in D.get("people", []) if p.get("user_id") == UID["bob"]]
check(len(salt) == 32 and pb and pb[0]["email_hash"] == EHS("bob@example.com", salt) and pb[0]["email_hash"] != EH("bob@example.com"),
      f"#2882: people.json: HMAC with the file's salt, not the plain SHA-256 {pb}")
check(b"bob@example.com" not in EXP and EH("bob@example.com").encode() not in EXP, "#2882: neither the address nor its plain hash in the file")
# the import (same server, carol) still finds bob by the keyed hash
r = Ca.post(B + "/api/account/import", json={"size": len(EXP), "name": "alice.zip"})
iid, off = r.json()["id"], 0
while off < len(EXP):
    part = EXP[off:off + (1 << 20)]
    r = Ca.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    off += len(part)
j = {}
for _ in range(240 * 4):  # polls the import's state until the preview (or an end state) is there
    j = Ca.get(B + f"/api/account/import/{iid}").json()
    if j.get("state") not in ("upload", "checking", "running"):
        break
    time.sleep(0.25)
pv = j.get("preview") or {}
check(j.get("state") == "preview" and pv.get("people_salt") == salt, f"#2882: the preview names the salt {j.get('state')} {j.get('error')}")
check(any(p["key"] == EHS("bob@example.com", salt) and p["found"] for p in pv.get("people", [])), f"#2882: the import finds bob by the keyed hash {pv.get('people')}")
Ca.delete(B + f"/api/account/import/{iid}")

# ================================================================== a person without an organisation
FID, F = freelancer(B, A)
FL = F.post(B + "/api/lists", json={"name": "Own work"}).json()["id"]
FT = F.post(B + "/api/tasks", json={"list_id": FL, "title": "Own task"}).json()["id"]
F.post(B + f"/api/tasks/{FT}/comments", json={"body": "Own note zq85"})
EXP, MAN, D = export_of(F)
check(any(x["body"] == "Own note zq85" for x in D.get("comments", [])) and any(t["id"] == FT for t in D.get("tasks", [])),
      "freelancer: the own list, task and comment are in the export as before")
check(D.get("written_comments") == [] and D.get("other_tasks") == [] and len(MAN.get("people_salt") or "") == 32,
      "freelancer: the new parts are there (nothing outside the own lists)")
check(F.get(B + "/api/export.json").ok, "freelancer: export.json")

print(f"p2239_a_export: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
