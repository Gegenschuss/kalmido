#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.410.0 A (#3514) API tests, own container (kt.fresh): a choice field marked "Ordered (stages)".
 - a select field with options.stages = 1 and options with special "red" / "orange" keeps them (create and change);
   any other special value is 400; stages / special on a multiselect are dropped
 - a change that leaves out stages / an option's special (an API or MCP client) keeps the stored ones; an explicit
   stages: false / special: "" clears them
 - a list template carries stages and the special states into the new list
 - freelancer-matrix: lists (the person without an organisation creates and changes such a field the same way)
usage: p24100_a_api_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,fields,kanban"})
FID, Fr = freelancer(B, A, "frida")

OPTS = [{"name": "Planned"}, {"name": "Needs you", "special": "orange"}, {"name": "Building"}, {"name": "Review"},
        {"name": "Parked", "special": "red"}, {"name": "Live"}]


def new_list(s, name):
    r = s.post(B + "/api/lists", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def field(s, lid, name, ftype="select", **opts):
    return s.post(B + f"/api/lists/{lid}/fields", json={"name": name, "type": ftype, "options": opts})


def specials(f):
    return {o["name"]: o.get("special") for o in f["options"]["options"]}


def fields_of(s, lid):
    return {f["name"]: f for f in s.get(B + "/api/state").json()["fields"] if f["list_id"] == lid}


for who, S in (("admin", A), ("freelancer", Fr)):
    L = new_list(S, f"Releases {who}")
    r = field(S, L, "Build", stages=1, options=OPTS)
    f = r.json() if r.ok else {}
    check(r.ok and f["options"].get("stages") == 1, f"#3514 {who}: a select field keeps stages {r.status_code} {r.text[:200]}")
    check(r.ok and specials(f) == {"Planned": None, "Needs you": "orange", "Building": None, "Review": None, "Parked": "red", "Live": None},
          f"#3514 {who}: the special states red / orange are kept per option {f.get('options')}")
    r = field(S, L, "Bad", stages=1, options=[{"name": "A"}, {"name": "B", "special": "purple"}])
    check(r.status_code == 400, f"#3514 {who}: an unknown signal colour is refused {r.status_code} {r.text[:200]}")
    r = field(S, L, "Bad 2", stages=1, options=[{"name": "A", "special": "<b>"}])
    check(r.status_code == 400, f"#3514 {who}: a special value that is no colour name is refused {r.status_code}")
    r = field(S, L, "Tags", "multiselect", stages=1, options=[{"name": "A", "special": "red"}])
    check(r.ok and "stages" not in r.json()["options"] and "special" not in r.json()["options"]["options"][0],
          f"#3514 {who}: a multiselect gets no stages / special states {r.text[:200]}")
    r = field(S, L, "Plain", options=[{"name": "A"}])
    check(r.ok and "stages" not in r.json()["options"], f"#3514 {who}: a select without the switch stays unordered {r.text[:200]}")
    if not f:
        continue
    # an API client that only renames / sends the options without the new keys keeps them
    r = S.patch(B + f"/api/fields/{f['id']}", json={"name": "Build stage"})
    g = r.json() if r.ok else {}
    check(r.ok and g["options"].get("stages") == 1 and specials(g)["Parked"] == "red", f"#3514 {who}: a rename keeps stages and special states {r.text[:200]}")
    plain = [{"id": o["id"], "name": o["name"], "color": o["color"]} for o in f["options"]["options"]]
    r = S.patch(B + f"/api/fields/{f['id']}", json={"options": {"options": plain + [{"name": "Staging"}]}})
    g = r.json() if r.ok else {}
    check(r.ok and g["options"].get("stages") == 1 and specials(g)["Needs you"] == "orange" and specials(g)["Staging"] is None,
          f"#3514 {who}: options sent without stages / special keep the stored ones {r.text[:300]}")
    # the dialog sends both explicitly: clearing works
    opts2 = [{**o, "special": "" if o["name"] == "Needs you" else o.get("special", "")} for o in g.get("options", {}).get("options", [])]
    r = S.patch(B + f"/api/fields/{f['id']}", json={"options": {"options": opts2, "stages": True}})
    g = r.json() if r.ok else {}
    check(r.ok and specials(g)["Needs you"] is None and specials(g)["Parked"] == "red", f"#3514 {who}: special \"\" turns an option back into a stage {r.text[:300]}")
    r = S.patch(B + f"/api/fields/{f['id']}", json={"options": {"options": g["options"]["options"], "stages": False}})
    check(r.ok and "stages" not in r.json()["options"], f"#3514 {who}: stages false switches the bar off {r.text[:200]}")
    S.patch(B + f"/api/fields/{f['id']}", json={"options": {"options": g["options"]["options"], "stages": 1}})
    # a value can be set on a special state like on any option
    t = S.post(B + "/api/tasks", json={"title": "Stage task", "list_id": L}).json()
    park = next(o["id"] for o in fields_of(S, L)["Build stage"]["options"]["options"] if o["name"] == "Parked")
    r = S.patch(B + f"/api/tasks/{t['id']}", json={"fields": {str(f["id"]): park}})
    check(r.ok and S.get(B + f"/api/tasks/{t['id']}").json()["fields"].get(str(f["id"])) == park, f"#3514 {who}: a special state is a value like any option {r.text[:200]}")
    # a list template carries the switch and the special states
    tp = S.post(B + "/api/templates", json={"kind": "list", "list_id": L, "name": f"Releases template {who}"})
    ap = S.post(B + f"/api/templates/{tp.json().get('id')}/apply", json={"name": f"Releases 2 {who}"}) if tp.ok else tp
    L2 = (ap.json().get("list_id") or ap.json().get("id")) if ap.ok else None
    f2 = fields_of(S, L2).get("Build stage") if L2 else None
    check(f2 and f2["options"].get("stages") == 1 and specials(f2).get("Parked") == "red" and specials(f2).get("Planned") is None,
          f"#3514 {who}: a list template keeps stages and special states {tp.status_code} {ap.status_code} {f2}")

sys.exit(kt.done("p24100_a"))
