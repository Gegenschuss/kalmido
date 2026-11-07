#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.610.0 B (#4762): the side objects of a project write through the shared core (kalmido/core/objparts.py) -- custom field
options, the people of a task, waiting on, templates, comments, sprints and the trash of sections / planned sprints /
templates. A pure rebuild: the answers stay those of 2.564 / 2.567 (tests/p2564_c_merge, p2564_d_versions, p2567_a_trash
check them); this suite checks what the move brought. Own container (kt.fresh). Invented names only.
freelancer-matrix: lists, tasks, templates
 - the code: the routes call the core (part_write / part_trash / part_restore / part_copy*) and no longer take their own
   lock / version check / trash copy (red before 2.610: ccf_check, write_lock and list_part_trash SQL in the routes)
 - part_merge (the core's merge of a list sent whole against _prev) as tasks.people used it
 - a template PATCH answered 400 inside the core's write step leaves nothing written (also not the name sent along); the 409
   keeps the key "template"; delete -> restore through the core, a second restore 404, another person 404, the limit of
   templates still refuses a restore
 - a section restored twice: the second is 404 (the core's check "back meanwhile"), the comment's 409 keeps the key "comment"
The same as alice (an organisation instance) and as a person without an organisation (frida).
usage: p2610_b_partwrite_test.py <datadir>"""
import ast
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, CT, check  # noqa: E402

ROOT = os.path.dirname(N)

# ================================================================== the code goes through the core
ROUTES = {  # file -> {function: the core call it must make}
    "kalmido/lists/templates.py": {"template_update": "part_write", "template_delete": "part_trash", "template_restore": "part_restore"},
    "kalmido/collab/comments.py": {"comment_update": "part_write"},
    "kalmido/lists/fields.py": {"field_update": "part_write"},
    "kalmido/lists/sprints.py": {"sprint_update": "part_write"},
    "kalmido/tasks/tasks.py": {"set_waiting": "part_write"},
    "kalmido/tasks/lifecycle.py": {"people_merge": "part_merge"},
    "kalmido/lists/parttrash.py": {"section_restore": "part_copy_back", "sprint_restore": "part_copy_back",
                                   "lpt_section_put": "part_copy", "lpt_sprint_put": "part_copy"},
}

# review 2.610 (#4762): the trash steps bind the row to its id (the row checked = the row written), the area's rule only narrows
# it; a template / comment put into the trash meanwhile is not changed by a save under the lock (live condition of the kind)
_op = open(os.path.join(ROOT, "kalmido", "core", "objparts.py"), encoding="utf-8").read()
check('return "id=?" + (f" AND ({where})" if where else "")' in _op and _op.count("w, a = _part_where(rid, where, args)") == 2,
      "review: part_trash and part_restore always bind id=rid, the area's where only narrows it")
check("WHERE id=?{live}" in _op, "review: part_write reads the row under the lock with the kind's live condition")
for _f in ("kalmido/lists/templates.py", "kalmido/collab/comments.py"):
    _src = open(os.path.join(ROOT, _f), encoding="utf-8").read()
    check('live="deleted_at IS NULL")' in _src, f"review: {_f} registers its kind with live=\"deleted_at IS NULL\"")
_tsrc = open(os.path.join(ROOT, "kalmido/lists/templates.py"), encoding="utf-8").read()
check('r["user_id"] == uid if r["org_id"] is None else r["org_id"] in user_orgs_full(c, uid) and tpl_may_write(c, r)' in _tsrc
      and "part_restore(c, TPL_KIND, tid, uid, guard=guard)" in _tsrc,
      "review: a template restore narrows (in the core's guard, under the lock) to the person's own templates or, since 2.609.0 "
      "(#3373), an organisation's template its admin may change")
OWN = ("ccf_check", "write_lock")  # what the core does now


def calls(fn):
    return {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}


for path, fns in ROUTES.items():
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    tree = ast.parse(src)
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name, core in fns.items():
        fn = defs.get(name)
        check(fn is not None, f"code: {path} has {name}")
        if fn is None:
            continue
        cs = calls(fn)
        check(core in cs, f"code: {name} writes through the core's {core}")
        check(not (set(OWN) & cs), f"code: {name} takes no lock / version check of its own any more ({sorted(set(OWN) & cs)})")
        seg = ast.get_source_segment(src, fn) or ""
        check("list_part_trash" not in seg, f"code: {name} reads / writes no trash copy itself")

# ================================================================== the routes
kt.fresh(prefix="P2610B")
# ================================================================== part_merge (in the container: the code as it runs)
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "from kalmido.core.objparts import part_merge as m\n"
                      "print(m([1,2,3],[1,2,3],[1,3]), m([1,2,3,4],[1,2,3],[1,3]), m([2,3],[1,2,3],[1,2,3,5]), m([],[],[7]))"],
                     capture_output=True, text=True)
check(out.stdout.strip() == "[1, 3] [1, 3, 4] [2, 3, 5] [7]",
      "part_merge: unchanged = as sent; a person added elsewhere stays; one removed elsewhere stays gone " + (out.stdout + out.stderr)[-400:])

A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
FID, Fr = freelancer(B, A)
r = A.post(B + "/api/users", json={"username": "otto", "display_name": "Otto", "password": kt.PASSWORD, "email": "otto@example.com"})
assert r.ok, r.text
Ot = kt.sess("otto")
Ot.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})


def tpls(s):
    return {t["id"]: t for t in s.get(B + "/api/templates").json()["templates"]}


def run(who, S):
    L = S.post(B + "/api/lists", json={"name": f"Shoot {who}"}).json()["id"]
    T = S.post(B + "/api/tasks", json={"title": "Location scout", "list_id": L}).json()["id"]
    # ------------------------------------------------------------ templates
    r = S.post(B + "/api/templates", json={"list_id": L, "name": f"Tpl {who}"})
    check(r.ok, f"{who}: a template " + r.text[:200])
    TP = r.json()["id"]
    before = tpls(S)[TP]
    r = S.patch(B + f"/api/templates/{TP}", json={"name": "Renamed", "data": "not a template"})
    check(r.status_code == 400, f"{who}: invalid data inside the core's step -> 400 {r.status_code} {r.text[:200]}")
    now = tpls(S)[TP]
    check(now["name"] == before["name"] and now["updated_at"] == before["updated_at"],
          f"{who}: nothing written by the refused change (also not the name sent along) {now['name']!r}")
    r = S.patch(B + f"/api/templates/{TP}", json={"name": "", "expect_updated_at": before["updated_at"]})
    check(r.status_code == 400 and tpls(S)[TP]["name"] == before["name"], f"{who}: an empty name -> 400, kept {r.status_code}")
    r = S.patch(B + f"/api/templates/{TP}", json={"name": "Old view", "expect_updated_at": "2000-01-01T00:00:00+00:00"})
    check(r.status_code == 409 and (r.json().get("template") or {}).get("id") == TP, f"{who}: an old version -> 409 under 'template' {r.text[:200]}")
    r = S.delete(B + f"/api/templates/{TP}")
    check(r.ok and r.json().get("trash") is True and TP not in tpls(S), f"{who}: deleted into the trash {r.text[:200]}")
    check(S.delete(B + f"/api/templates/{TP}").status_code == 404, f"{who}: deleting it again -> 404 (not live)")
    check(Ot.post(B + f"/api/templates/{TP}/restore").status_code == 404, f"{who}: another person cannot restore it")
    r = S.post(B + f"/api/templates/{TP}/restore")
    check(r.ok and r.json().get("id") == TP and r.json().get("name") == before["name"], f"{who}: restored with its id {r.text[:200]}")
    check(S.post(B + f"/api/templates/{TP}/restore").status_code == 404, f"{who}: a second restore -> 404")
    # ------------------------------------------------------------ a section restored twice
    SEC = S.post(B + "/api/sections", json={"list_id": L, "name": "Doing"}).json()["id"]
    check(S.delete(B + f"/api/sections/{SEC}").ok, f"{who}: section deleted")
    r = S.post(B + f"/api/sections/{SEC}/restore")
    check(r.ok and r.json().get("id") == SEC and r.json().get("name") == "Doing", f"{who}: section back with its id {r.text[:200]}")
    check(S.post(B + f"/api/sections/{SEC}/restore").status_code == 404, f"{who}: a second restore -> 404")
    check(Ot.post(B + f"/api/sections/{SEC}/restore").status_code == 404, f"{who}: another person -> 404")
    # ------------------------------------------------------------ the comment's 409 key
    r = S.post(B + f"/api/tasks/{T}/comments", json={"body": "first words"})
    check(r.ok, f"{who}: a comment " + r.text[:200])
    cm = r.json()
    r = S.patch(B + f"/api/comments/{cm['id']}", json={"body": "late words", "expect_updated_at": "2000-01-01T00:00:00.000Z"})
    check(r.status_code == 409 and (r.json().get("comment") or {}).get("id") == cm["id"], f"{who}: an old version -> 409 under 'comment' {r.text[:200]}")
    r = S.patch(B + f"/api/comments/{cm['id']}", json={"body": "new words"})
    check(r.ok, f"{who}: without a version as before {r.status_code} {r.text[:200]}")
    # ------------------------------------------------------------ waiting on: only the fields sent
    check(S.put(B + f"/api/tasks/{T}/waiting", json={"note": "the venue", "until": "2031-01-02"}).ok, f"{who}: waiting set")
    r = S.put(B + f"/api/tasks/{T}/waiting", json={"note": "the venue owner"})
    check(r.ok and r.json().get("wait_until") == "2031-01-02", f"{who}: a note alone keeps the follow-up day {r.text[:200]}")
    check(S.put(B + "/api/tasks/99999999/waiting", json={"note": "x"}).status_code == 404, f"{who}: an unknown task -> 404")


run("alice", A)
run("frida", Fr)

# the limit of templates still refuses a restore (through the core's guard)
L = Fr.post(B + "/api/lists", json={"name": "Limit"}).json()["id"]
TPL_MAX = int(subprocess.run(["docker", "exec", CT, "python", "-c", "from kalmido.lists.templates import TPL_MAX_PER_USER as m\nprint(m)"],
                             capture_output=True, text=True).stdout.strip() or 0)
check(TPL_MAX > 0, "setup: the template limit")
have = len(tpls(Fr))
GONE = Fr.post(B + "/api/templates", json={"list_id": L, "name": "Spare"}).json()["id"]
check(Fr.delete(B + f"/api/templates/{GONE}").ok, "limit: one template in the trash")
kt.dbx("INSERT INTO templates(user_id, kind, name, data, created_at, updated_at) SELECT ?, 'task', 'Fill ' || n, "
       "'{\"task\": {\"title\": \"Fill\"}}', '2031-01-01T00:00:00Z', '2031-01-01T00:00:00Z' FROM generate_series(1, ?) AS n",
       (FID, TPL_MAX - have))
check(len(tpls(Fr)) >= TPL_MAX, f"limit: {TPL_MAX} live templates")
r = Fr.post(B + f"/api/templates/{GONE}/restore")
check(r.status_code == 400 and GONE not in tpls(Fr), f"limit: restoring beyond the limit -> 400, stays in the trash {r.status_code} {r.text[:200]}")

sys.exit(kt.done("p2610_b_partwrite"))
