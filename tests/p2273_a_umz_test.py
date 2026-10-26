#!/usr/bin/env python3
"""2.273.0 part A (#3030): the account import says what stays on the old server. Invented names only (example.com).
 - a real account export of a person without an organisation (a table, a knowledge page, a bookmark, the appearance,
   the working days, a task with a code snippet) -> the preview's not_taken names tables, knowledge pages and bookmarks with
   their numbers; every exported part with rows is either read by the import or named (nothing stays behind unseen)
 - the run: the result carries the same list as a warning, the import's record keeps it (report.not_taken); the appearance
   (theme) and the working days come over now, the code snippet too (with the importer as author)
 - a crafted file: an unknown new part keeps its technical name, a task in the trash is named, settings that do not move
   are counted
 - guard (static, the app source): every part of the account export (umz_export_queries, umz_extra_queries, the extra
   parts of umz_build) is either in UMZ_READ or named in UMZ_LEFT; every part umz_write reads is in UMZ_READ
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2273A_NOSTART=1 = the server already runs like that).
usage: p2273_a_umz_test.py <datadir>"""
# freelancer-matrix: own
import ast
import base64
import hashlib
import io
import json
import os
import re
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

SRC = os.path.join(N, "..", "kalmido")
KEY = base64.b64encode(os.urandom(32)).decode()


def src_tree(rel):
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return ast.parse(f.read())


def fn_of(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def dict_keys(fn):
    return {k.value for d in ast.walk(fn) if isinstance(d, ast.Dict) for k in d.keys if isinstance(k, ast.Constant)}


def assigned(tree, name):
    return next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == name for t in n.targets))


# ================================================================== guard (static, no server)
imp = src_tree("admin/acctimport.py")
READ = {e.value for e in assigned(imp, "UMZ_READ").args[0].elts}
LEFT = {}
for e in assigned(imp, "UMZ_LEFT").elts:
    LEFT.update({p.value: e.elts[0].args[0].value for p in e.elts[1].elts})
exp = src_tree("admin/acctexport.py")
parts = dict_keys(fn_of(src_tree("accounts/settings.py"), "umz_export_queries")) | dict_keys(fn_of(exp, "umz_extra_queries"))
parts |= {c.args[2].value for c in ast.walk(fn_of(exp, "umz_build")) if isinstance(c, ast.Call)
          and getattr(c.func, "id", "") == "_put_rows" and isinstance(c.args[2], ast.Constant)}
check({"sheets", "wiki_pages", "bookmarks", "budgets", "people"} <= parts, f"guard: the export parts were found {sorted(parts)[:8]}")
silent = sorted(p for p in parts if p not in READ and p not in LEFT)
check(not silent, f"guard: every export part is read by the import or named as staying behind (UMZ_READ / UMZ_LEFT): {silent}")
check(not READ & set(LEFT), f"guard: a part is read and named as left behind at once {sorted(READ & set(LEFT))}")
wsrc = ast.unparse(fn_of(imp, "umz_write"))
used = set(re.findall(r"data\.get\('([a-z0-9_]+)'", wsrc)) | set(re.findall(r"data\['([a-z0-9_]+)'\]", wsrc))
for tup in re.findall(r"for (?:table|src), [^:]*? in \((.*?)\):", wsrc, re.S):  # the loops over (table, ...) tuples
    used |= set(re.findall(r"\('([a-z0-9_]+)', ", tup))
check({"lists", "tasks", "sections", "attachments", "habits"} <= used, f"guard: the parts umz_write reads were found {sorted(used)[:8]}")
unlisted = sorted(used - READ - {"oi"})
check(not unlisted, f"guard: a part umz_write reads is missing in UMZ_READ (the preview would name it as left behind): {unlisted}")


# ================================================================== server
def export_of(s):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(s.get(B + "/api/account/export").json()), 120)
    assert j and j.get("state") == "done", j
    r = s.get(B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


def run(s, iid):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
    check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
    return until(lambda: state_of(s, iid), 180) or {}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def mkzip(tables):
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": "2026-10-20T06:00:00Z",
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": 1000, "name": "Test Person", "email": "test@example.com"},
         "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    mb = json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs.encode())
        for p, b in entries.items():
            z.writestr(p, b)
    return bio.getvalue()


def named(pv):
    return {x.get("what"): x.get("count") for x in pv.get("not_taken") or []}


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY}, prefix="P2273A")
A = kt.setup()
FID, Fr = freelancer(B, A, features=FEATURES + ",sheets")  # the person moving, without an organisation
GID, Gi = freelancer(B, A, "gina")  # the target account, without an organisation too

LOOK = {"theme": "dark", "accent": "teal"}
check(Fr.patch(B + "/api/settings", json={"look": json.dumps(LOOK), "workdays": "0,1,2,3"}).ok, "the appearance and working days are set")
L = Fr.post(B + "/api/lists", json={"name": "Umzug Projekt"}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Mit Schnipsel", "list_id": L}).json()["id"]
r = Fr.patch(B + f"/api/tasks/{T}", json={"snippets": [{"lang": "py", "path": "a/b.py", "line": 3, "code": "print(1)\n"}]})
check(r.ok, f"a code snippet on the task {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/sheets", json={"title": "Umzug Tabelle", "space": "private"})
check(r.ok, f"a private table {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Umzug Seite", "body": "private page"})
check(r.ok, f"a private knowledge page {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/umzug"})
check(r.ok, f"a bookmark {r.status_code} {r.text[:120]}")

EX = export_of(Fr)
with zipfile.ZipFile(io.BytesIO(EX)) as z:
    rows = {n[5:-5]: len(json.loads(z.read(n))) for n in z.namelist() if n.startswith("data/") and n.endswith(".json")}
check(rows.get("sheets") == 1 and rows.get("wiki_pages") == 1 and rows.get("bookmarks") == 1, f"the export holds them {rows}")
iid, j = upload(Gi, EX)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
pv = j.get("preview") or {}
nt = named(pv)
# the regression of #3030: before 2.273.0 the preview named none of these (a fixed list of connections only)
check(nt.get("Tables") == 1, f"#3030: the preview names the table with its number {nt}")
check(nt.get("Knowledge pages") == 1, f"#3030: ... the knowledge page {nt}")
check(nt.get("Bookmarks") == 1, f"#3030: ... the bookmark {nt}")
check(nt.get("Other settings", 0) >= 1, f"#3030: ... the settings that do not move (counted) {nt}")
check(not any(w in nt for w in ("tasks", "lists", "Tasks in the trash")), f"#3030: nothing that comes over is named {nt}")
labels = {LEFT.get(t, t) for t, n in rows.items() if n and t not in READ}
check(labels <= set(nt), f"#3030: every exported part with rows that the import does not read is named {sorted(labels - set(nt))}")
j = run(Gi, iid)
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
res = j.get("result") or {}
w = " | ".join(x.get("text", "") for x in res.get("warnings") or [])
check("stay on the old server" in w and "Tables (1)" in w and "Knowledge pages (1)" in w, f"#3030: the result names them too: {w[:300]}")
rep = kt.dbx("SELECT report FROM imports WHERE user_id=? ORDER BY id DESC LIMIT 1", (GID,))
rep = json.loads(rep[0][0]) if rep else {}
check({"what": "Tables", "count": 1} in (rep.get("not_taken") or []), f"#3030: the import's record keeps the list {rep.get('not_taken')}")
st = Gi.get(B + "/api/state").json()["settings"]
check(json.loads(st.get("look") or "{}").get("theme") == "dark" and st.get("workdays") == "0,1,2,3",
      f"#3030: the appearance (theme) and the working days come over {st.get('look')!r} {st.get('workdays')!r}")
sn = kt.dbx("SELECT t.snippets FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND t.title='Mit Schnipsel'", (GID,))
sv = sn[0][0] if sn else None
sv = json.loads(sv) if isinstance(sv, str) else sv
check(isinstance(sv, list) and sv and sv[0].get("code") == "print(1)\n" and sv[0].get("by") == GID,
      f"#3030: the code snippet comes over, the importer as author {sv}")

# a crafted file: an unknown part, a task in the trash
ts = "2026-10-20T06:00:00Z"
fz = mkzip({"lists": [{"id": 1, "name": "Crafted", "created_at": ts}],
            "tasks": [{"id": 1, "list_id": 1, "title": "kept", "created_at": ts, "updated_at": ts},
                      {"id": 2, "list_id": 1, "title": "trashed", "created_at": ts, "updated_at": ts, "deleted_at": ts}],
            "zz_future_part": [{"id": 1}, {"id": 2}], "settings": [{"key": "lang", "value": "en"}, {"key": "tour", "value": "done"}]})
iid, j = upload(Gi, fz)
nt = named(j.get("preview") or {})
check(nt.get("zz_future_part") == 2, f"#3030: an unknown part keeps its technical name with its number {nt}")
check(nt.get("Tasks in the trash") == 1 and nt.get("Other settings") == 1, f"#3030: the trashed task and the setting that does not move {nt}")
Gi.delete(B + f"/api/account/import/{iid}")

sys.exit(kt.done("p2273_a_umz"))
