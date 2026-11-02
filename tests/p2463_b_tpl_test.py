#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.463.0 (#3860, #3865) the account export and import carry what a template keeps on the server. Invented data only, as people
without an organisation.
 - the export has the template's extra without other people's numbers, lists and tasks of this server
 - the import stores it with the importer's own assignment, the file copy sealed for them; using the template brings it all
 - a template that was there already gets no second file; the undo takes the file along
 - a crafted file: paths, foreign ids and broken parts never reach templates.extra
usage: p2463_b_tpl_test.py <datadir>"""
# freelancer-matrix: own
import hashlib
import json
import os
import sys
import time
import zipfile
from io import BytesIO

import kt
from kt import B, check, dbx, su_get
from freelancer_fixture import freelancer

kt.fresh(prefix="P2463B")
A = kt.setup()
FID, F = freelancer(B, A, "frida")
DATA = sys.argv[1]
OTHER = 987654


def one(q, *a):
    r = dbx(q, a)
    return r[0][0] if r else None


def export_of(s):
    assert s.post(B + "/api/account/export").status_code == 202
    j = {}
    for _ in range(480):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "frida.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid):
    j = {}
    for _ in range(960):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def run(s, data):
    iid = upload(s, data)
    check(wait(s, iid).get("state") == "preview", "the preview")
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}, "again": True})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"the run ends well {j.get('state')} {j.get('error')}")
    return iid, j


def tampered(zdata, edit):
    zs = zipfile.ZipFile(BytesIO(zdata))
    parts = {n[5:-5]: json.loads(zs.read(n)) for n in zs.namelist() if n.startswith("data/") and n.endswith(".json")}
    edit(parts)
    files = {n: zs.read(n) for n in zs.namelist() if n not in ("manifest.json", "checksum.sha256")}
    files.update({f"data/{k}.json": json.dumps(v).encode() for k, v in parts.items()})
    m = json.loads(zs.read("manifest.json"))
    m["files"] = [{"path": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]
    mb = json.dumps(m).encode()
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", "\n".join(f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in [("manifest.json", mb), *files.items()]) + "\n")
    return out.getvalue()


# ---- a template with a file; its extra as the server keeps it, with numbers of this server
L = F.post(B + "/api/lists", json={"name": "Harbour"}).json()["id"]
T = F.post(B + "/api/tasks", json={"title": "Lay deck", "list_id": L, "assignee_id": FID}).json()["id"]
r = F.post(B + f"/api/tasks/{T}/attachments", files={"file": ("plan.txt", b"the plan\n", "text/plain")})
check(r.ok, "a file on the task " + r.text[:160])
r = F.post(B + "/api/templates", json={"list_id": L, "name": "Harbour tpl"})
check(r.ok, "a list template " + r.text[:200])
TP = r.json()["id"]
NODE = one("SELECT node_key FROM template_files WHERE template_id=?", TP)
check(NODE, "the template has its file copy")
x = json.loads(one("SELECT extra FROM templates WHERE id=?", TP))
x["nodes"][NODE].update({"r": OTHER, "g": OTHER, "xt": {str(OTHER): ["theirs"]}, "ln": [OTHER], "lt": ["Urgent"], "sp": 0,
                         "pf": {"0": str(OTHER), "1": str(FID)}, "tf": {"0": {"id": str(OTHER)}, "1": {"k": NODE}}})
x["list"].update({"sprints": [{"name": "One", "goal": "", "state": "planned", "s": 0, "e": 14}], "ltags": [{"name": "Urgent", "color": "", "sort": 1}],
                  "links": [{"title": "Site", "url": "https://example.com/plan"}]})
dbx("UPDATE templates SET extra=? WHERE id=?", (json.dumps(x), TP))
check(x["nodes"][NODE].get("a") == FID, "setup: the task is hers in the template")

# ---- the export
EXP = export_of(F)
zs = zipfile.ZipFile(BytesIO(EXP))
row = [t for t in json.loads(zs.read("data/templates.json")) if t["id"] == TP][0]
n = row["extra"]["nodes"][NODE]
check(n.get("a") == FID and n.get("lt") == ["Urgent"] and n.get("sp") == 0, f"#3860: her own assignment, the tag, the sprint go along {n}")
check(n.get("pf") == {"1": str(FID)} and n.get("tf") == {"1": {"k": NODE}}, f"#3860: of the fields only her and tasks of the template {n}")
check(not {"r", "g", "xt", "ln", "files"} & set(n) and str(OTHER) not in json.dumps(row["extra"]), f"#3860: no numbers of others {n}")

# ---- the import
GID, G = freelancer(B, A, "gina")
_, j = run(G, EXP)
GT = one("SELECT id FROM templates WHERE user_id=? AND name='Harbour tpl'", GID)
check(GT, "the template came along")
gx = json.loads(one("SELECT extra FROM templates WHERE id=?", GT))
gn = gx["nodes"][NODE]
check(gn.get("a") == GID and gn.get("pf") == {"1": str(GID)}, f"#3860: the assignment is the importer's {gn}")
check(gx["list"]["sprints"][0]["name"] == "One" and gx["list"]["links"][0]["url"] == "https://example.com/plan", "#3860: the list's part came along")
gf = dbx("SELECT path, node_key, size FROM template_files WHERE template_id=?", (GT,))
check(len(gf) == 1 and gf[0][1] == NODE and gf[0][2] == 9 and gf[0][0].startswith(f"tplfiles/{GT}/"), f"#3865: the file copy of the template {gf}")
left = " ".join(str(k.get("name")) for k in (j.get("result") or {}).get("left") or [])
check("Files of templates" not in left, "#3865: the preview no longer names them as left behind " + left)

r = G.post(B + f"/api/templates/{GT}/apply", json={"name": "From the export"})
check(r.ok, "the template is used " + r.text[:200])
NL = r.json()["list_id"]
NT = one("SELECT id FROM tasks WHERE list_id=? AND title='Lay deck'", NL)
check(one("SELECT assignee_id FROM tasks WHERE id=?", NT) == GID, "#3860: the new task is the importer's")
AT = one("SELECT id FROM attachments WHERE task_id=?", NT)
check(AT and G.get(B + f"/api/attachments/{AT}").content == b"the plan\n", "#3865: the file opens on the new task")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=?", NL) == 1 and one("SELECT COUNT(*) FROM list_links WHERE list_id=?", NL) == 1, "#3860: sprint and key link")
check(one("SELECT COUNT(*) FROM task_list_tags WHERE task_id=?", NT) == 1, "#3860: the list tag on the task")

# ---- the same file again: the template stays, no second file
run(G, EXP)
check(one("SELECT COUNT(*) FROM template_files WHERE user_id=?", GID) == 1, "#3865: an import of the same file brings no second copy")


# ---- a crafted file
def craft(p):
    for t in p["templates"]:
        t["extra"] = {"skipped": ["x"], "list": {"sprints": [{"name": "S", "s": "a"}, 5], "ltags": ["x", {"name": 3}], "links": [{"url": "javascript:alert(1)"}], "wip": [1], "sprint_cfg": "["},
                      "nodes": {NODE: {"a": OTHER, "files": [{"name": "p", "mime": "", "size": 1, "path": "/etc/passwd", "scan": "clean"}], "sp": "x", "lt": "no", "pf": {"x": "1"}, "tf": {"0": {"k": ["n1"]}}},
                                "n999": {"files": [{"path": "/etc/passwd"}]}, "n998": 5}}
    for f in p["template_files"]:
        f["node_key"] = ["n1"]


KID, K = freelancer(B, A, "kerstin")
run(K, tampered(EXP, craft))
KT = one("SELECT id FROM templates WHERE user_id=? AND name='Harbour tpl'", KID)
kx = one("SELECT extra FROM templates WHERE id=?", KT)
check("passwd" not in kx and "files" not in kx and "javascript" not in kx, f"#3860: nothing of the crafted parts is stored {kx}")
check(one("SELECT COUNT(*) FROM template_files WHERE user_id=?", KID) == 0, "#3865: a file for no task of the template stays away")
r = K.post(B + f"/api/templates/{KT}/apply", json={"name": "Crafted"})
check(r.ok, "the template with the cleaned extra is usable " + r.text[:200])


def craft2(p):
    for t in p["templates"]:
        t["extra"] = json.dumps({"nodes": {NODE: {"files": [{"name": "p", "mime": "", "size": 1, "path": "/etc/passwd", "scan": "clean"}]}}})


LID, Li = freelancer(B, A, "lina")
run(Li, tampered(EXP, craft2))
check("passwd" not in one("SELECT extra FROM templates WHERE user_id=?", LID), "#3860: text in the file's extra is not stored either")

# ---- the undo takes the file along
full = os.path.join(DATA, "attachments", gf[0][0])
had = os.path.isfile(full)
IMP = (j.get("result") or {}).get("import_id")
check(IMP, "the run names its import")
r = G.post(B + f"/api/imports/{IMP}/undo", json={})
check(r.ok or r.status_code == 202, "the undo " + r.text[:200])
for _ in range(100):
    if not one("SELECT COUNT(*) FROM template_files WHERE template_id=?", GT):
        break
    time.sleep(0.1)
check(one("SELECT COUNT(*) FROM template_files WHERE template_id=?", GT) == 0, "#3865: the undo takes the row along")
check(not had or not os.path.isfile(full), "#3865: and the file")

sys.exit(kt.done("p2463_b_tpl"))
