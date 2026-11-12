#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1072.0 (#5860): "Show me" -- an agent's chat message names places of the app (show: [{target, text}]) from the fixed list
docs/help-targets.json (kalmido/api/showme.py). Invented names only.
 - API v1 POST /api/v1/agent/chats/<uid>: an unknown key, a selector, an address, a wrong shape, too many steps, a too long
   text, an extra field -> 400 and no message; show on a notice / an approval / a permission question -> 400; a known key is
   stored: the answer gives show back as sent ([{target, text}]), the person's chat (GET /api/agents/<id>/chat) each step
   with route, sel and label (in the person's language); a message without show: null; a multipart form carries show as JSON
 - the help: GET /api/v1/help show_targets = every key of the list; a section of GET /api/v1/help/section names its marks
   in show (a list)
 - the list itself: every key has a selector, a route (null or #...), a label marked for the translations (showme.py
   SHOW_LABELS) and translated (de); each attribute a selector names exists in the web client; the image carries the file
   (Dockerfile)
 - MCP send_chat: the field show in its schema, sent through; an unknown key -> ApiError 400
 - freelancer-matrix: agents (a person without an organisation, her personal agent sends show; she gets the steps)
usage: p21072_c_show_test.py <datadir>"""
import glob
import importlib.util
import json
import os
import re
import sys

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

V = B + "/api/v1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "docs", "help-targets.json"), encoding="utf-8") as f:
    TARGETS = json.load(f)["targets"]

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ORG = ME["workspaces"][0]["id"]


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None):
    body = {"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["token"]


AID, AGT = agent("showbot", org=ORG)
ag = bearer(AGT)
L = A.post(B + "/api/lists", json={"name": "Shown", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"}).ok


def say(t, uid, **kw):
    return t.post(V + f"/agent/chats/{uid}", json={"body": "This is the way.", **kw})


def person_chat(s, aid):
    return s.get(B + f"/api/agents/{aid}/chat").json().get("messages") or []


# ---------------------------------------------------------------- refused: only keys of the list, nothing else
n0 = len(person_chat(A, AID))
BAD = [("an unknown key", [{"target": "settings.frobnicate"}]),
       ("a CSS selector", [{"target": "#side .sset"}]),
       ("an address", [{"target": "#office/offers"}]),
       ("a URL", ["https://example.com/"]),
       ("a script-like key", [{"target": "javascript:alert(1)"}]),
       ("an empty list item", [{}]),
       ("a number", [12]),
       ("not a list", {"target": "tasks.new"}),
       ("nine steps", [{"target": "tasks.new"}] * 9),
       ("a text too long", [{"target": "tasks.new", "text": "x" * 301}]),
       ("a text not a string", [{"target": "tasks.new", "text": 5}]),
       ("an extra field (a selector of its own)", [{"target": "tasks.new", "sel": "#view"}]),
       ("broken JSON text", "[{\"target\":")]
for what, v in BAD:
    r = say(ag, ME["id"], show=v)
    check(r.status_code == 400, f"{what}: 400 ({r.status_code} {r.text[:120]})")
for what, extra in (("a notice", {"kind": "notice"}), ("a permission question", {"permission": True}),
                    ("an approval request", {"approval": {"title": "Go?", "what": "it goes"}})):
    r = say(ag, ME["id"], show=[{"target": "tasks.new"}], **extra)
    check(r.status_code == 400, f"show on {what}: 400 ({r.status_code} {r.text[:120]})")
check(len(person_chat(A, AID)) == n0, "no refused message reached the chat")

# ---------------------------------------------------------------- stored and delivered
STEPS = [{"target": "settings.open", "text": "Open the settings  here."}, {"target": "settings.integrations", "text": "Then Integrations."},
         {"target": "files.scan-inbox"}]
r = say(ag, ME["id"], show=STEPS)
check(r.status_code == 201, f"three known keys: 201 ({r.status_code} {r.text[:200]})")
m = r.json() if r.ok else {}
check(m.get("show") == [{"target": "settings.open", "text": "Open the settings here."}, {"target": "settings.integrations", "text": "Then Integrations."},
                        {"target": "files.scan-inbox"}], f"the answer: show as sent (spaces folded, no route / selector) {m.get('show')}")
pm = next((x for x in person_chat(A, AID) if x["id"] == m.get("id")), {})
sh = pm.get("show") or []
check([x.get("target") for x in sh] == ["settings.open", "settings.integrations", "files.scan-inbox"], f"the person's chat: the steps {sh}")
check(all(x.get("sel") == TARGETS[x["target"]]["sel"] and x.get("route") == TARGETS[x["target"]]["route"] for x in sh),
      "... each with the selector and route of the list")
check(sh and sh[0].get("label") == "Open the settings" and sh[0].get("text") == "Open the settings here.", f"... label + text {sh[:1]}")
plain = say(ag, ME["id"]).json()
check(plain.get("show") is None and next(x for x in person_chat(A, AID) if x["id"] == plain["id"]).get("show") is None,
      "a message without show: null on both sides")
r = ag.post(V + f"/agent/chats/{ME['id']}", data={"body": "With a form.", "show": json.dumps([{"target": "files.upload", "text": "Here"}])},
            files={"file": ("note.txt", b"hello", "text/plain")})
check(r.status_code == 201 and r.json().get("show") == [{"target": "files.upload", "text": "Here"}], f"multipart: show as JSON text ({r.status_code} {r.text[:160]})")
r = say(ag, ME["id"], show=["tasks.new", "calendar.new"])
check(r.status_code == 201 and r.json().get("show") == [{"target": "tasks.new"}, {"target": "calendar.new"}], "a plain list of keys works too")
# the label follows the person's language
A.patch(B + "/api/settings", json={"lang": "de"})
pm = next((x for x in person_chat(A, AID) if x["id"] == m.get("id")), {})
check((pm.get("show") or [{}])[0].get("label") == "Einstellungen öffnen", f"German: the label translated {pm.get('show', [{}])[:1]}")
A.patch(B + "/api/settings", json={"lang": "en"})
# the agent's own read of the chat: the stored form
rows = ag.get(V + "/agent/chats", params={"user_id": ME["id"]}).json().get("data") or []
am = next((x for x in rows if x["id"] == m.get("id")), {})
check(am.get("show") == m.get("show"), f"the agent reads its steps back as sent {am.get('show')}")

# ---------------------------------------------------------------- the help names the keys
ov = ag.get(V + "/help").json()
check(sorted(x["key"] for x in ov.get("show_targets") or []) == sorted(TARGETS), f"help_overview: show_targets = the list {ov.get('show_targets')}")
check("show" in (ov.get("how") or ""), "help_overview: how names send_chat show")
sec = ag.get(V + "/help/section", params={"key": "api#scan-inboxes-folder-watcher"}).json()
check(isinstance(sec.get("show"), list) and all(k in TARGETS for k in sec["show"]), f"read_help: show = the section's marks (known keys) {sec.get('show')}")

# ---------------------------------------------------------------- the list itself
src = open(os.path.join(ROOT, "kalmido", "api", "showme.py"), encoding="utf-8").read()
de = json.load(open(os.path.join(ROOT, "static", "i18n", "de.json"), encoding="utf-8"))
web = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(ROOT, "static", "js", "*.js")) + [os.path.join(ROOT, "static", "index.html")])
for k, t in TARGETS.items():
    check(re.fullmatch(r"[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*){1,2}", k) and isinstance(t.get("sel"), str) and t["sel"].strip(), f"{k}: key + selector")
    check(t.get("route") is None or re.fullmatch(r"#[a-z][a-z0-9/._-]*", t["route"]), f"{k}: route null or #... ({t.get('route')})")
    check(f'N_("{t["label_en"]}")' in src and de.get(t["label_en"]), f"{k}: label marked (SHOW_LABELS) and translated ({t.get('label_en')})")
    for name, val in re.findall(r'\[([a-z-]+)="([^"]+)"\]', t["sel"]):
        check(f'{name}="{val}"' in web or f'{name}="${{' in web and val in web, f"{k}: the web client has {name}=\"{val}\"")
    for idn in re.findall(r"#([a-z][a-z0-9-]*)", t["sel"]):
        check(f'id="{idn}"' in web, f"{k}: the web client has id {idn}")
dock = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
check("COPY docs/help-targets.json /app/docs/" in dock, "the image carries docs/help-targets.json")

# ---------------------------------------------------------------- MCP send_chat
sp = importlib.util.spec_from_file_location("kalmido_mcp_t", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mcp)
api = mcp.Kalmido(B, AGT)
schema = mcp.TOOL_MAP["send_chat"][2]
check("show" in schema["properties"] and schema["properties"]["show"]["maxItems"] == 8, "MCP send_chat: show in the schema")
r = mcp.TOOL_MAP["send_chat"][3](api, {"user_id": ME["id"], "body": "Via MCP.", "show": [{"target": "office.offer-new", "text": "Here"}]})
check(r.get("show") == [{"target": "office.offer-new", "text": "Here"}], f"MCP send_chat: show sent {r.get('show')}")
r = mcp.TOOL_MAP["send_chat"][3](api, {"user_id": ME["id"], "body": "Via MCP with a file.", "show": [{"target": "files.upload"}],
                                        "files": [{"name": "a.txt", "base64": "aGk="}]})
check(r.get("show") == [{"target": "files.upload"}], f"MCP send_chat with files: show as JSON in the form {r.get('show')}")
try:
    mcp.TOOL_MAP["send_chat"][3](api, {"user_id": ME["id"], "body": "x", "show": [{"target": "office.frobnicate"}]})
    check(False, "MCP send_chat with an unknown key: an error")
except mcp.ApiError as e:
    check(e.status == 400, f"MCP send_chat with an unknown key: 400 ({e.status})")
check("show_targets" in mcp.TOOL_MAP["help_overview"][3](api, {}), "MCP help_overview: show_targets")

# ================================================================ a person without an organisation
# freelancer-matrix: agents
FID, Fl = freelancer(B, A)
FAID, FAGT = agent("fridabot", owner=FID)
fa = bearer(FAGT)
r = say(fa, FID, show=[{"target": "tasks.new", "text": "Type it here"}, {"target": "calendar.new"}])
check(r.status_code == 201, f"her personal agent sends show: 201 ({r.status_code} {r.text[:160]})")
fm = next((x for x in person_chat(Fl, FAID) if x["id"] == (r.json().get("id") if r.ok else 0)), {})
check([x.get("target") for x in fm.get("show") or []] == ["tasks.new", "calendar.new"] and (fm.get("show") or [{}])[0].get("route") == "#today",
      f"she gets the steps with route and selector {fm.get('show')}")
check(say(fa, FID, show=[{"target": "nope.nope"}]).status_code == 400, "her agent: an unknown key 400")

sys.exit(kt.done("p21072_c_show"))
