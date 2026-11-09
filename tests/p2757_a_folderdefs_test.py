#!/usr/bin/env python3
# kalmido-suite:
"""2.757.0 API tests (#4501: more folder defaults), own container (start.sh). Invented data only.
 - PUT /api/folders/props sets view, nag, day_hours, rate, show_progress, and columns / fields / ltags (also {from: list id});
   "apply all" gives them to the lists in the folder (fields and tags only added, columns mapped to the list's own field ids)
 - bad values = 400 (unknown view, formula field, a list of another person as the source, a rate that is no number)
 - a new list in the folder gets them; an explicit view other than the folder's differs, the same one does not
 - a setting changed on its own differs from the folder (folder_own), keeps its value on the next folder change, and
   "Back to the folder" (folder-reset) takes the folder's value again; a renamed folder field and an own progress-bar
   choice differ as well
 - a folder change never deletes a field, a tag or a task's field value
 - a list moved into the folder (no workspace question) takes them
 - another person's list in a folder of the same name stays untouched
P4: a person without an organisation (tests/freelancer_fixture.py) gets the same (freelancer-matrix: lists)
usage: p2757_a_folderdefs_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="P2757A")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})


def state(s):
    return s.get(B + "/api/state").json()


def lst(s, lid):
    return next((x for x in state(s)["lists"] if x["id"] == lid), {})


def own(s, lid):
    import json
    return json.loads(lst(s, lid).get("folder_own") or "[]")


def fields(s, lid):
    return {f["name"]: f["id"] for f in state(s).get("fields", []) if f["list_id"] == lid}


def tags(s, lid):
    return {(x["name"] if isinstance(x, dict) else x) for x in lst(s, lid).get("tags") or []}


def new(s, **b):
    r = s.post(B + "/api/lists", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def props(s, p, apply="all", **kw):
    return s.put(B + "/api/folders/props", json={"folder": "Clients", "props": p, "apply": apply, **kw})


def prog(s):
    return [x for x in (state(s)["settings"].get("show_progress") or "").split(",") if x]


def case(s, who, other):
    src = new(s, name="Source")
    r = s.post(B + f"/api/lists/{src}/fields", json={"name": "Budget", "type": "number"})
    assert r.ok, r.text
    bud = r.json()["id"]
    assert s.post(B + f"/api/lists/{src}/fields", json={"name": "Stage", "type": "select", "options": {"options": [{"name": "New"}, {"name": "Done"}]}}).ok
    assert s.post(B + f"/api/lists/{src}/tags", json={"name": "urgent", "color": "#dd3333"}).ok
    assert s.patch(B + f"/api/lists/{src}", json={"columns": ["due", f"f:{bud}"]}).ok
    old = new(s, name="Old", folder="Clients")
    t = s.post(B + "/api/tasks", json={"title": "Keep my value", "list_id": old}).json()["id"]

    # bad values
    check(props(s, {"view": "nope"}).status_code == 400, f"{who}: an unknown view = 400")
    check(props(s, {"fields": [{"name": "Sum", "type": "formula", "options": {}}]}).status_code == 400, f"{who}: a formula field = 400")
    check(props(s, {"columns": {"from": other}}).status_code == 400, f"{who}: another person's list as the source = 400")
    check(props(s, {"rate": "lots"}).status_code == 400, f"{who}: a rate that is no number = 400")

    # the folder defaults, applied to the list in it
    r = props(s, {"view": "kanban", "nag": "1d", "day_hours": 6, "rate": 90.5, "show_progress": True,
                  "fields": {"from": src}, "columns": {"from": src}, "ltags": {"from": src}})
    check(r.ok and r.json()["changed"] >= 8, f"{who}: the folder defaults are saved and applied {r.status_code} {r.text[:200]}")
    st = (s.get(B + "/api/folders/props?folder=Clients").json() or {}).get("props") or {}
    check(st.get("columns") == ["due", "fn:Budget"] and [x["name"] for x in st.get("fields", [])] == ["Budget", "Stage"]
          and st.get("ltags") == [{"name": "urgent", "color": "#dd3333"}] and st.get("rate") == 90.5,
          f"{who}: {{from}} is stored as the source's columns (by name), fields and tags {st}")
    x, fo = lst(s, old), fields(s, old)
    check(x.get("view") == "kanban" and x.get("nag") == "1d" and x.get("day_hours") == 6 and x.get("rate") == 90.5,
          f"{who}: view, reminder, hours and rate follow {(x.get('view'), x.get('nag'), x.get('day_hours'), x.get('rate'))}")
    check(set(fo) == {"Budget", "Stage"} and x.get("columns") == ["due", f"f:{fo.get('Budget')}"],
          f"{who}: the fields are added and the columns name the list's own field {fo} {x.get('columns')}")
    check(tags(s, old) == {"urgent"} and str(old) in prog(s), f"{who}: the project tag and the progress bar follow {tags(s, old)} {prog(s)}")
    check(not own(s, old), f"{who}: nothing differs yet {own(s, old)}")
    # review: a column name with blanks around it is stored trimmed (it would never match the list's field otherwise)
    r = props(s, {"columns": ["due", "fn: Budget "]})
    st = (s.get(B + "/api/folders/props?folder=Clients").json() or {}).get("props") or {}
    check(r.ok and st.get("columns") == ["due", "fn:Budget"] and lst(s, old).get("columns") == ["due", f"f:{fo.get('Budget')}"],
          f"{who}: a padded field column is trimmed and still mapped {st.get('columns')} {lst(s, old).get('columns')}")

    # a task's value, a field and a tag are never deleted by the folder
    assert s.patch(B + f"/api/tasks/{t}", json={"fields": {str(fo["Budget"]): "5"}}).ok
    r = props(s, {"fields": [{"name": "Stage", "type": "text"}], "ltags": []})
    check(r.ok and set(fields(s, old)) == {"Budget", "Stage"} and tags(s, old) == {"urgent"},
          f"{who}: a smaller folder default removes no field or tag {fields(s, old)} {tags(s, old)}")
    check([v for (v,) in kt.dbx("SELECT value FROM task_field_values WHERE task_id=?", (t,))] == ["5"], f"{who}: the task keeps its field value")

    # a new list in the folder; an explicit view
    n1 = new(s, name="Fresh", folder="Clients")
    x = lst(s, n1)
    check(x.get("view") == "kanban" and x.get("rate") == 90.5 and "Stage" in fields(s, n1) and not own(s, n1),
          f"{who}: a new list in the folder takes the defaults {x.get('view')} {fields(s, n1)} {own(s, n1)}")
    n2 = new(s, name="Same view", folder="Clients", view="kanban")
    check(not own(s, n2), f"{who}: the same view as the folder's is no own one {own(s, n2)}")
    n3 = new(s, name="Own view", folder="Clients", view="list")
    check(lst(s, n3).get("view") == "list" and own(s, n3) == ["view"], f"{who}: an explicit other view differs {lst(s, n3).get('view')} {own(s, n3)}")

    # changed on its own -> differs, kept on the next folder change, back to the folder
    assert s.patch(B + f"/api/lists/{old}", json={"view": "list", "rate": 70}).ok
    check(set(own(s, old)) == {"view", "rate"}, f"{who}: view and rate changed on their own differ {own(s, old)}")
    r = props(s, {"view": "timeline", "rate": 100})
    check(r.ok and lst(s, old).get("view") == "list" and lst(s, old).get("rate") == 70 and lst(s, n1).get("view") == "timeline",
          f"{who}: the differing list keeps its values, the others follow {lst(s, old).get('view')} {lst(s, n1).get('view')}")
    check(any(y["id"] == old and set(y["own"]) == {"view", "rate"} for y in r.json().get("lists", [])), f"{who}: the answer names the differing list {r.json().get('lists')}")
    r = s.post(B + f"/api/lists/{old}/folder-reset", json={})
    check(r.ok and lst(s, old).get("view") == "timeline" and lst(s, old).get("rate") == 100 and not own(s, old),
          f"{who}: Back to the folder takes its values again {r.text[:160]} {own(s, old)}")
    assert s.patch(B + f"/api/fields/{fields(s, old)['Stage']}", json={"name": "Phase"}).ok
    check("fields" in own(s, old), f"{who}: a folder field renamed in the list differs {own(s, old)}")
    assert s.patch(B + "/api/settings", json={"set_delta": {"show_progress": {"remove": [str(old)]}}}).ok
    check("show_progress" in own(s, old), f"{who}: an own progress-bar choice differs {own(s, old)}")
    r = s.post(B + f"/api/lists/{old}/folder-reset", json={})
    check(r.ok and "Stage" in fields(s, old) and "Phase" in fields(s, old) and str(old) in prog(s),
          f"{who}: back to the folder adds the field again (the renamed one stays) and shows the bar {fields(s, old)}")

    # moved into the folder (no workspace / agent question)
    mv = new(s, name="Mover")
    r = s.patch(B + f"/api/lists/{mv}", json={"folder": "Clients"})
    x = lst(s, mv)
    check(r.ok and x.get("view") == "timeline" and x.get("nag") == "1d" and x.get("day_hours") == 6 and "Stage" in fields(s, mv),
          f"{who}: a list moved into the folder takes the defaults {(x.get('view'), x.get('nag'), x.get('day_hours'))} {fields(s, mv)}")


case(A, "alice", 0)
FID, Fr = freelancer(B, A)
alice_src = next(x["id"] for x in state(A)["lists"] if x["name"] == "Source")
case(Fr, "frida (no organisation)", alice_src)
# alice's folder defaults never reach frida's list in her folder "Clients" (and the other way round)
fl = next(x for x in state(Fr)["lists"] if x["name"] == "Old")
check(fl.get("rate") == 100, f"frida's list keeps her own folder's values {fl.get('rate')}")
r = props(A, {"rate": 12})
check(r.ok and next(x for x in state(Fr)["lists"] if x["name"] == "Old").get("rate") == 100, "alice's folder change leaves frida's list alone")
# agents never set folder defaults
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
r = sess().put(B + "/api/folders/props", headers={"Authorization": "Bearer " + r.json()["token"]}, json={"folder": "Clients", "props": {"view": "list"}})
check(r.status_code in (401, 403), f"an agent cannot set folder defaults {r.status_code}")

sys.exit(kt.done("p2757_a_folderdefs"))
