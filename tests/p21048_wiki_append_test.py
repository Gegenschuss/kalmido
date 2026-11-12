#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1048.0 (#5861): an agent adds text at the end of a knowledge page without sending the whole page
(POST /api/v1/wiki/pages/{id}/append, wiki/wkv1.py wkv_append; MCP wiki_append). Invented names only.
 - the text comes after the page's text with exactly one empty line in between (2.1068.0, #5829: was one line break); what
   the agent sent arrives, the rest of the page stays as it was
 - 2.1068.0 (#5829): under = a heading: the text goes to the end of that section (an empty line before the next heading);
   an unknown heading = 404 heading_not_found with the page's headings, nothing written
 - the same save as PATCH: the page's history has the change, the editor is the agent
 - expect_updated_at is optional; given and outdated = 409 with the current page, nothing appended
 - an empty text, an unknown field, a text over the limit = 400; scope wiki:write (403 without); OpenAPI names the route
 - the share decides: no share 404, a view share 403, an edit share appends
 - tenant-matrix: wiki_v1 (the agent of another organisation 404)
 - freelancer-matrix: wiki (a person without an organisation: her own agent with her folder share appends to her private
   page, another person's agent never)
usage: p21048_wiki_append_test.py <datadir>"""
import sys

import requests

import kt
from kt import B, check, dbx, sess
from freelancer_fixture import FEATURES, freelancer

V = B + "/api/v1"
FEAT = "wiki,files,collab,comments"
WS = ["read", "wiki:read", "wiki:write"]

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com", "orgs": []})
assert r.ok, r.text
OLGA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": OLGA})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None, scopes=WS):
    body = {"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def page(s, path, text, space=SP):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def folders(s, space=SP):
    r = s.get(B + "/api/wiki", params={"space": space})
    return {f["path"]: f["id"] for f in r.json().get("folders", [])} if r.ok else {}


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def append(t, pid, **b):
    return t.post(V + f"/wiki/pages/{pid}/append", json=b)


def body_of(s, pid):
    return s.get(B + f"/api/wiki/pages/{pid}").json().get("body")


def versions(s, pid):
    r = s.get(B + f"/api/wiki/pages/{pid}/versions")
    return len(r.json().get("versions", [])) if r.ok else -1


# ================================================================ setup
P1 = page(A, "Handbook/Links", "# Links\n- Shop: https://shop.example.com")
P2 = page(A, "Handbook/Notes", "First line\n")
P3 = page(A, "Secret/Plan", "do not tell")
HB = folders(A).get("Handbook")
check(HB, "setup: the knowledge folder Handbook")
TA, ta = agent("alphabot", org=ORG)
TB, tb = agent("betabot", org=BETA)
_, t0 = agent("noscope", org=ORG, scopes=["read", "wiki:read"])

# ================================================================ scope, OpenAPI
r = append(t0, P1, text="- x")
check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "wiki:write", f"no wiki:write: 403 ({r.status_code} {r.text[:120]})")
spec = requests.get(V + "/openapi.json").json()["paths"]
check(spec.get("/wiki/pages/{id}/append", {}).get("post", {}).get("x-kalmido-scope") == "wiki:write", "OpenAPI: the append route needs wiki:write")

# ================================================================ the share decides
check(append(ta, P1, text="- x").status_code == 404, "no share: 404")
S1 = fshare(A, HB, agent_id=TA, role="view")
check(append(ta, P1, text="- x").status_code == 403 and "- x" not in body_of(A, P1), "a view share: 403, nothing appended")
check(append(ta, P3, text="- x").status_code == 404, "a page outside the shared folder: 404")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok, "setup: the share to edit")

# ================================================================ appending
v0 = versions(A, P1)
r = append(ta, P1, text="- Lights: https://lights.example.com")
check(r.status_code == 200, f"edit share: the agent appends ({r.status_code} {r.text[:200]})")
# 2.1068.0 (#5829): exactly one empty line between the page and the new text (was one line break)
want = "# Links\n- Shop: https://shop.example.com\n\n- Lights: https://lights.example.com"
check(body_of(A, P1) == want, f"alice sees the old text plus one empty line plus the new line: {body_of(A, P1)!r}")
check(r.ok and r.json().get("body") == want, "the answer carries the whole page (wiki:read)")
w = A.get(B + f"/api/wiki/pages/{P1}").json()
check(w.get("updated_by") == TA, "the agent is the page's editor")
check(versions(A, P1) > v0, f"the append is in the page's history ({v0} -> {versions(A, P1)})")
r = append(ta, P2, text="\nA new paragraph")
# 2.1068.0 (#5829): leading / trailing line breaks of text never add a second empty line; the page's last line break stays
check(r.ok and body_of(A, P2) == "First line\n\nA new paragraph\n", f"a page ending with a line break: one empty line, no double {body_of(A, P2)!r}")
check(append(ta, P2, text="Again", expect_updated_at=r.json()["updated_at"]).ok, "the current expect_updated_at: appends")
r = append(ta, P2, text="Too late", expect_updated_at="2000-01-01T00:00:00.000Z")
check(r.status_code == 409 and r.json().get("error", {}).get("page", {}).get("body", "").endswith("Again\n")
      and "Too late" not in body_of(A, P2), f"an outdated expect_updated_at: 409 with the current page, nothing appended ({r.status_code})")
check(append(ta, P1, text="   ").status_code == 400, "an empty text: 400")
check(append(ta, P1, text="x", body="whole").status_code == 400, "an unknown field (body): 400")
check(append(ta, P1, text="x" * 20001).status_code == 400, "a text over 20000 characters: 400")
check(body_of(A, P1) == want, "the refused calls changed nothing")
check(dbx("SELECT COUNT(*) FROM fs_log l JOIN fs_nodes n ON n.id=l.node_id WHERE n.kind='ref' AND n.ref_kind='wiki' AND n.ref_id=? "
          "AND l.agent=1 AND l.action='write'", (P1,))[0][0] >= 1, "the agent's write is noted in the node's history")

# ================================================================ 2.1068.0 (#5829): under a heading
P4 = page(A, "Handbook/Overview", "# Overview\nintro\n\n## 2D\n- [Sketch](sketch)\n\n## 3D\n- [Model](model)\n```\n## Not a heading\n```\n")
v0 = versions(A, P4)
r = append(ta, P4, text="- [Lights](lights)", under="2d")
check(r.ok and body_of(A, P4) == "# Overview\nintro\n\n## 2D\n- [Sketch](sketch)\n\n- [Lights](lights)\n\n## 3D\n- [Model](model)\n```\n## Not a heading\n```\n",
      f"under 2D (case ignored): at the end of that section, one empty line before and before ## 3D ({r.status_code} {body_of(A, P4)!r})")
check(versions(A, P4) > v0, "appending under a heading is a normal version of the page")
r = append(ta, P4, text="- [Print](print)", under="3D")
check(r.ok and body_of(A, P4).endswith("## 3D\n- [Model](model)\n```\n## Not a heading\n```\n\n- [Print](print)\n"),
      f"the last section: at the end of the page, a heading inside a code fence does not end it {body_of(A, P4)!r}")
r = append(ta, P4, text="- [Intro](intro)", under="Overview")
check(r.ok and "- [Print](print)\n\n- [Intro](intro)\n" in body_of(A, P4), "a level-1 heading: its section runs over the level-2 ones to the end")
before = body_of(A, P4)
r = append(ta, P4, text="- x", under="4D")
err = r.json().get("error", {}) if r.status_code == 404 else {}
check(r.status_code == 404 and err.get("code") == "heading_not_found" and err.get("headings") == ["Overview", "2D", "3D"],
      f"an unknown heading: 404 with the page's headings ({r.status_code} {r.text[:200]})")
check(body_of(A, P4) == before, "the unknown heading wrote nothing")
# review (2.1068.0): "# C#" is the heading "C#"; a "# comment" in the frontmatter is no heading; a ~~~ inside a ``` fence does not close it
P5 = page(A, "Handbook/Langs", "---\ntitle: Langs\n# not a heading\n---\n# C#\n- one\n```\n~~~\n# Inside\n```\n# Go\n- two\n")
r = append(ta, P5, text="- three", under="C#")
check(r.ok and "# C#\n- one\n```\n~~~\n# Inside\n```\n\n- three\n\n# Go" in body_of(A, P5), f"under C#: the end of its section, past the fence {r.status_code} {body_of(A, P5)!r}")
r = append(ta, P5, text="- x", under="not a heading")
check(r.status_code == 404 and r.json().get("error", {}).get("headings") == ["C#", "Go"], f"the frontmatter line is no heading {r.text[:200]}")
check(append(ta, P4, text="- x", under="  ").status_code == 400 and append(ta, P4, text="- x", under=3).status_code == 400, "an empty / not a text under: 400")

# ================================================================ tenant-matrix: wiki_v1
# tenant: POST /api/v1/wiki/pages/{}/append
check(append(tb, P1, text="- intruder").status_code == 404 and "intruder" not in body_of(A, P1), "the other organisation's agent: 404")

# ================================================================ a person without an organisation
# freelancer-matrix: wiki
FID, Fl = freelancer(B, A, features=FEATURES + ",wiki,files")
DA, da = agent("fridabot", owner=FID)
AA, aa = agent("alicebot", owner=ALICE)
Q1 = page(Fl, "Clients/Acme", "Contact: Jo", space="private")
check(append(da, Q1, text="Phone: 555-0100").status_code == 404, "her own agent without a share: 404")
fshare(Fl, folders(Fl, "private")["Clients"], agent_id=DA, role="edit")
r = append(da, Q1, text="Phone: 555-0100")
check(r.ok and body_of(Fl, Q1) == "Contact: Jo\n\nPhone: 555-0100", f"her agent with the folder share appends ({r.status_code} {body_of(Fl, Q1)!r})")
check(append(aa, Q1, text="x").status_code == 404 and append(ta, Q1, text="x").status_code == 404, "another person's / an organisation's agent: never")

sys.exit(kt.done("p21048_wiki_append"))
