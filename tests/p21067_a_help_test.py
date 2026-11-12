#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1050.0 (#5819): the help of the running version for agents (kalmido/api/helpdocs.py, docs/*.md in the image). Invented names only.
 - search: GET /api/v1/search?kind=help (the search registry's kind, not part of kind=all); "scan inbox folder" finds the
   section of docs/API.md with the path of the interface (Settings > Integrations > Documents: inboxes) and the note that
   only a person creates a scan inbox; the five questions of the decision (scan inbox, a knowledge folder shared with an
   agent, quotation -> tasks with a time budget, a recurring task, a calendar subscription) each find a fitting section with
   a click path; an unknown question finds nothing
 - read: GET /api/v1/help/section?key= only by the index key: an invented key, a file name, a path (../, /etc/passwd) -> 404;
   the operator files (SELF-HOSTING ...) only for an instance admin's token with admin-read (else 404, never a hit); a long
   section is cut at 16,000 characters with its parts; ui_terms translate the labels (de)
 - overview: GET /api/v1/help (the feature areas, the files with their keys), no operator file for an agent
 - OpenAPI names the routes (scope read), the kind enum has help; any token reads it (every token has read)
 - MCP: help_overview / search_help / read_help (mcp/kalmido_mcp.py, toolset chat) and kalmido_cli.py docs against the server
 - freelancer-matrix: agents (a person without an organisation: her token and her own agent read the help)
usage: p21050_a_help_test.py <datadir>"""
import importlib.util
import io
import os
import re
import sys

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

V = B + "/api/v1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCAN = "api#scan-inboxes-folder-watcher"

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None, scopes=("read",)):
    body = {"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["token"]


def token(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "help", "scopes": list(scopes)})
    assert r.ok, r.text
    return r.json()["token"]


def search(t, q, **kw):
    r = t.get(V + "/search", params={"kind": "help", "q": q, **kw})
    return r.json() if r.ok else r.status_code


def read(t, key, **kw):
    r = t.get(V + "/help/section", params={"key": key, **kw})
    return r.json() if r.ok else r.status_code


def keys(res, n=5):
    return [h["key"] for h in (res.get("data") or [])[:n]] if isinstance(res, dict) else res


_, AGT = agent("helpbot", org=ORG)
ag = bearer(AGT)
adm = bearer(token(A, ("read", "admin-read")))
adm_plain = bearer(token(A, ("read",)))

# ---------------------------------------------------------------- search + read: the scan inbox (the occasion of #5819)
res = search(ag, "scan inbox folder")
check(keys(res, 1) == [SCAN], f"scan inbox folder: the section of API.md first ({keys(res)})")
h = res["data"][0] if isinstance(res, dict) and res.get("data") else {}
check(h.get("file") == "API.md" and "Scan inboxes: folder watcher" in (h.get("path") or []) and h.get("snippet"),
      f"a hit carries file, the headings and a snippet: {h}")
sec = read(ag, SCAN, lang="de")
txt = sec.get("text", "") if isinstance(sec, dict) else ""
check(txt.startswith("## Scan inboxes: folder watcher") and "Settings > Integrations > *Documents: inboxes*" in txt,
      "read: the section with the path of the interface (Settings > Integrations > Documents: inboxes)")
check("never an" in txt and "only a person can create one" in txt, "read: only a person creates a scan inbox, never an agent")
check("## Help for agents" not in txt and "Web routes of the settings" in txt, "read: up to the next heading of the same rank, not beyond")
ui = sec.get("ui_terms", {}) if isinstance(sec, dict) else {}
check(ui.get("Integrations") == "Integrationen" and ui.get("Documents: inboxes") == "Dokumente: Eingänge"
      and ui.get("New scan inbox") == "Neuer Scan-Eingang", f"ui_terms in German: {ui}")
check(read(ag, SCAN, lang="en").get("ui_terms") == {}, "lang en: no ui_terms (the help is English)")
check(read(ag, SCAN, lang="xx") == 400, "an unknown lang: 400")

# ---------------------------------------------------------------- the five questions of the decision (#5819)
FIVE = [("scan inbox folder watcher", {SCAN}),
        ("share knowledge folder with agent", {"agents#knowledge-pages", "wiki#sharing-a-page-or-a-folder-read-only"}),
        ("quotation tasks budget hours", {"office#tasks-with-a-time-budget-from-the-quotation-post-calculation"}),
        ("recurring task", {"tasks#recurring-tasks"}),
        ("subscribe calendar", {"calendar#calendar-subscription-your-tasks-in-other-calendars",
                                "calendar#calendar-subscriptions-other-calendars-in-kalmido"})]
for q, want in FIVE:
    got = keys(search(ag, q), 3)
    hit = [k for k in got if k in want] if isinstance(got, list) else []
    check(bool(hit), f"{q!r}: a fitting section in the first three ({got})")
    if hit:
        t = read(ag, hit[0]).get("text", "")
        check(">" in t or "›" in t or "*" in t, f"{q!r}: the section names where to click ({hit[0]})")
check(search(ag, "frobnicate quantum teleporter") == {"data": [], "more": False}, "an unknown question: nothing (not a guess)")
check(search(ag, "the and of") == {"data": [], "more": False}, "only small words: nothing")
r = search(ag, "task", limit=2)
check(isinstance(r, dict) and len(r["data"]) == 2 and r["more"] is True, "limit and more")

# ---------------------------------------------------------------- read only by key: no file names, no paths
for bad in ("api#no-such-heading", "../etc/passwd", "/etc/passwd", "API.md", "docs/API.md", "api/../env", "..%2Fenv",
            "dev#kern", "self-hosting", "env", "x" * 300, ""):
    check(read(ag, bad) == 404, f"read {bad[:40]!r}: 404")
check(ag.get(V + "/help/section").status_code == 404, "no key: 404")
check(ag.get(V + "/help/section", params={"key": SCAN, "path": "/etc/passwd"}).status_code == 400, "an unknown parameter: 400")

# the operator files: an instance admin's token with admin-read only
# review 2.1050.0 (F4): every docs/*.md is named a user's file (HELP_PUBLIC) or an operator file (HELP_OPERATOR); a new one
# is closed until named - this turns red so that it gets named
_src = open(os.path.join(ROOT, "kalmido", "api", "helpdocs.py"), encoding="utf-8").read()
_named = set(re.findall(r'"([a-z0-9-]+)"', _src[_src.index("HELP_OPERATOR = frozenset"):_src.index("HELP_READ_MAX =")]))
_files = {re.sub(r"[^a-z0-9]+", "-", f[:-3].lower()).strip("-") for f in os.listdir(os.path.join(ROOT, "docs")) if f.endswith(".md")}
check(not (_files - _named), f"every docs/*.md is named public or operator in helpdocs.py: {sorted(_files - _named)}")
check(read(ag, "about") != 404, "a user's file (ABOUT) is readable for an agent")
check(read(adm_plain, "self-hosting") == 404, "an admin's token without admin-read: no operator file")
r = read(adm, "self-hosting")
check(isinstance(r, dict) and r.get("file") == "SELF-HOSTING.md", "an admin's token with admin-read reads SELF-HOSTING")
q = "reverse proxy environment variables"
check(not [h for h in search(ag, q, limit=20)["data"] if h["file"] in ("SELF-HOSTING.md", "ENV.md")], "an agent never gets an operator file as a hit")
check([h for h in search(adm, q, limit=20)["data"] if h["file"] in ("SELF-HOSTING.md", "ENV.md")], "the admin's token with admin-read does")

# the cap: AGENTS.md as one section is far longer than 16,000 characters
r = read(ag, "agents")
check(isinstance(r, dict) and r["truncated"] is True and 1000 < len(r["text"]) <= 16000 and r["parts"],
      f"a long section is cut, with its parts ({len(r.get('text', '')) if isinstance(r, dict) else r})")
if isinstance(r, dict) and r["parts"]:
    p = read(ag, r["parts"][-1]["key"])
    check(isinstance(p, dict) and p["title"] == r["parts"][-1]["title"], "a part is readable by its key")

# ---------------------------------------------------------------- overview, kind=all, OpenAPI, a token without read
o = ag.get(V + "/help").json()
areas = [a["area"] for a in o.get("features", [])]
check("Projects" in areas and all(a["items"] for a in o["features"]), f"overview: the feature areas with items ({areas})")
fk = {f["key"]: f for f in o.get("files", [])}
check(SCAN in {s["key"] for s in fk.get("api", {}).get("sections", [])}, "overview: the files with their section keys")
check(not {"self-hosting", "env", "upgrading", "architecture"} & set(fk), "overview: no operator file for an agent")
check("self-hosting" in {f["key"] for f in adm.get(V + "/help").json()["files"]}, "overview: the operator files for the admin with admin-read")
r = ag.get(V + "/search", params={"kind": "all", "q": "scan inbox"}).json()
check("help" not in (r.get("groups") or {}), "kind=all stays the person's data (no help group)")
spec = ag.get(V + "/openapi.json").json()
check(spec["paths"]["/help"]["get"]["x-kalmido-scope"] == "read" and spec["paths"]["/help/section"]["get"]["x-kalmido-scope"] == "read",
      "OpenAPI: both routes with scope read")
kinds = [p for p in spec["paths"]["/search"]["get"]["parameters"] if p["name"] == "kind"][0]["schema"]["enum"]
check("help" in kinds, "OpenAPI: kind=help")
r = A.post(B + "/api/me/tokens", json={"name": "timeonly", "scopes": ["time"]})
check(r.ok and bearer(r.json()["token"]).get(V + "/help").status_code == 200,
      "every token has read (api/scopes.py scopes_effective): a token made for time only reads the help too")

# ---------------------------------------------------------------- MCP tools and the command line against the server
sp = importlib.util.spec_from_file_location("kalmido_mcp_t", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mcp)
api = mcp.Kalmido(B, AGT)
check(all(mcp.TOOLSET_OF.get(n) == "chat" and mcp.tool_allowed(api, n) for n in ("help_overview", "search_help", "read_help")),
      "MCP: the three tools in the chat toolset, allowed for a read token")
r = mcp.TOOL_MAP["search_help"][3](api, {"q": "scan inbox folder"})
check(r["data"][0]["key"] == SCAN, "MCP search_help")
r = mcp.TOOL_MAP["read_help"][3](api, {"key": SCAN, "lang": "de"})
check("Settings > Integrations" in r["text"] and r["ui_terms"].get("Folder watcher") == "Ordner-Wächter", "MCP read_help")
check(mcp.TOOL_MAP["help_overview"][3](api, {})["features"], "MCP help_overview")
try:
    mcp.TOOL_MAP["read_help"][3](api, {"key": "../ENV.md"})
    check(False, "MCP read_help with a path: an error")
except mcp.ApiError as e:
    check(e.status == 404, "MCP read_help with a path: 404")
sys.path.insert(0, os.path.join(ROOT, "mcp"))
import kalmido_cli  # noqa: E402
os.environ["KALMIDO_TOKEN"] = AGT
out, err = io.StringIO(), io.StringIO()
rc = kalmido_cli.main(["--url", B, "docs", "scan", "inbox", "folder"], out=out, err=err)
check(rc == 0 and out.getvalue().startswith(SCAN), f"kalmido_cli docs: the hit ({rc}, {err.getvalue()[:200]})")
out = io.StringIO()
rc = kalmido_cli.main(["--url", B, "docs", "frobnicate", "teleporter"], out=out, err=io.StringIO())
check(rc == 0 and "nothing in the help" in out.getvalue(), "kalmido_cli docs: nothing found says so")

# ================================================================ a person without an organisation
# freelancer-matrix: agents
FID, Fl = freelancer(B, A)
_, FAGT = agent("fridabot", owner=FID)
for who, t in (("her token", bearer(token(Fl, ("read",)))), ("her own agent", bearer(FAGT))):
    check(keys(search(t, "scan inbox folder"), 1) == [SCAN], f"{who}: search_help (GET /api/v1/search?kind=help)")
    check("Settings > Integrations" in read(t, SCAN).get("text", ""), f"{who}: read_help (GET /api/v1/help/section)")
    check(t.get(V + "/help").status_code == 200, f"{who}: the overview (GET /api/v1/help)")
    check(read(t, "self-hosting") == 404, f"{who}: no operator file")

sys.exit(kt.done("p21050_a_help"))
