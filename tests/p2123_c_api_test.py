#!/usr/bin/env python3
"""2.123.0 C API tests: files of the file store and tables in knowledge pages (#2103, #2107), checkbox lines as tasks (#2108).
 - a page references Ablage files by ![..](/api/files/nodes/<id>/content) and links [[datei:<path or id>]] /
   [[tabelle:<name or id>]]: wiki_links keeps to_file / to_sheet (not as a page link), [[Dateien]] stays a page link
 - POST /api/wiki/pages/<id>/refs answers only what the reader may open in the file store / the table: an organisation
   member without access to a file gets nothing about it (no name in the answer), a file / table of another space (the
   person's private one, another organisation) is never resolved, a file in the trash is gone
 - GET /api/wiki/refs?file= | sheet= = the pages one may read that reference it (404 without access to the file / table)
 - a move to the private space ends the references into the organisation's file store (rows rebuilt, text kept); the ZIP
   export keeps the references as text; a file deleted for good takes its backlink rows with it
 - #2108: a converted checkbox line "- [ ] … #<id>" links the task (to_task, "Mentioned in"); the parser runs in the
   browser (p2123_c_ui.js)
 - rights (tenant-matrix: wiki): another organisation 404 on the page's refs; a person without an organisation
   (freelancer-matrix: wiki) uses her own private file store / tables in her private pages, nobody else resolves them
usage: p2123_c_api_test.py <datadir>      (P2123C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import dbx as dbxm
import requests
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def upload(s, name, data, mime, **form):
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def links(pid):
    rows = sql("SELECT to_path, to_task, to_file, to_sheet FROM wiki_links WHERE from_id=?", (pid,))
    return {"path": sorted(r[0] for r in rows if r[0]), "task": sorted(r[1] for r in rows if r[1]),
            "file": sorted(r[2] for r in rows if r[2]), "sheet": sorted(r[3] for r in rows if r[3])}


def refs(s, pid, files=(), lk=()):
    return s.post(B + f"/api/wiki/pages/{pid}/refs", json={"files": list(files), "links": list(lk)})


if os.environ.get("P2123C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = FEATURES + ",sheets"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"
FID, Fr = freelancer(B, A)
_, Fo = freelancer(B, A, "fiona")
for s in (Fr, Fo):
    s.patch(B + "/api/settings", json={"features": FEAT})

# ---------------------------------------------------------------- the file store of the organisation
TEAM = A.post(B + "/api/files/folders", json={"name": "Team", "space": SP}).json()["id"]
check(A.patch(B + f"/api/files/nodes/{TEAM}", json={"org_access": "view"}).ok, "setup: the folder Team is open to the organisation")
DOCS = A.post(B + "/api/files/folders", json={"name": "Docs", "parent_id": TEAM}).json()["id"]
F_PIC = upload(A, "plan.png", PNG, "image/png", parent_id=TEAM)
F_PDF = upload(A, "vertrag.pdf", PDF, "application/pdf", parent_id=DOCS)
F_SECRET = upload(A, "geheim-lohnliste.pdf", PDF, "application/pdf", space=SP)  # the organisation's top, not opened: only Alice (admin)
F_PRIV = upload(A, "privat.pdf", PDF, "application/pdf", space="private")   # Alice's private file store
F_C = upload(Ca, "beta.pdf", PDF, "application/pdf", space=SP2)            # another organisation
check(Bo.get(B + f"/api/files/nodes/{F_PIC}/content").ok and Bo.get(B + f"/api/files/nodes/{F_SECRET}/content").status_code == 404,
      "setup: Bob opens the Team files, not the closed one")
SH = A.post(B + "/api/sheets", json={"title": "Budget", "space": SP})
check(SH.status_code == 201, "setup: a table of the organisation " + SH.text[:200])
SH = SH.json()["id"]
SH_C = Ca.post(B + "/api/sheets", json={"title": "Budget", "space": SP2}).json()["id"]

BODY = (f"# Projekt\n\n![Plan](/api/files/nodes/{F_PIC}/content)\n\nDer [Vertrag](/api/files/nodes/{F_PDF}/content), "
        f"[[datei:Team/Docs/Vertrag.PDF]], [[datei:{F_SECRET}|Liste]], [[tabelle:budget]], [[Tabelle: {SH}|Zahlen]], "
        f"[[datei:{F_PRIV}]], [[datei:{F_C}]], [[tabelle:{SH_C}]], ![x](/api/files/nodes/{F_C}/content) und [[Dateien]].\n")
r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": "Projekt", "body": BODY})
check(r.status_code == 201, "a page with references " + r.text[:200])
PG = r.json()["id"]
L = links(PG)
check(L["path"] == ["dateien"], f"#2107: [[datei:…]] / [[tabelle:…]] are no page links, [[Dateien]] is one {L['path']}")
check(L["file"] == sorted({F_PIC, F_PDF, F_SECRET}), f"#2103 #2107: the files of the same space are kept (id, path, embed), not the private / foreign ones {L['file']}")
check(L["sheet"] == [SH], f"#2107: the table by name and by id, not the one of another organisation {L['sheet']}")

# ---------------------------------------------------------------- what a reader may see
ALL_F = [F_PIC, F_PDF, F_SECRET, F_PRIV, F_C]
ALL_L = ["datei:Team/Docs/Vertrag.PDF", f"datei:{F_SECRET}", "tabelle:budget", f"tabelle:{SH}", f"datei:{F_PRIV}", f"datei:{F_C}", f"tabelle:{SH_C}"]
r = refs(A, PG, ALL_F, ALL_L)
j = r.json() if r.ok else {}
check(r.ok and set(j.get("files", {})) == {str(F_PIC), str(F_PDF), str(F_SECRET)}, "#2103: the admin sees the files of the organisation " + r.text[:300])
fp = j.get("files", {}).get(str(F_PIC), {})
check(fp.get("image") is True and fp.get("url") == f"/api/files/nodes/{F_PIC}/content" and fp.get("name") == "plan.png",
      "#2103: a picture with its address in the file store (no copy) " + str(fp))
lk = j.get("links", {})
check(lk.get("datei:team/docs/vertrag.pdf", {}).get("id") == F_PDF, "#2107: [[datei:<path>]] is found by folders and name (case does not matter) " + str(lk))
check(lk.get("tabelle:budget", {}).get("id") == SH and lk.get(f"tabelle:{SH}", {}).get("url") == f"#sheets/{SH}", "#2107: [[tabelle:…]] by name and by id " + str(lk))
check(f"datei:{F_PRIV}" not in lk and f"datei:{F_C}" not in lk and f"tabelle:{SH_C}" not in lk and str(F_PRIV) not in j.get("files", {}),
      "#2103: a file / table of another space is never resolved (also for its owner)")
check(sql("SELECT COUNT(*) FROM fs_nodes WHERE name='plan.png'")[0][0] == 1, "#2103: no copy of the file")

r = refs(Bo, PG, ALL_F, ALL_L)
j = r.json() if r.ok else {}
check(r.ok and set(j.get("files", {})) == {str(F_PIC), str(F_PDF)} and f"datei:{F_SECRET}" not in j.get("links", {}),
      "#2103: a member sees only the files open to her in the file store " + r.text[:300])
check("geheim" not in r.text.lower() and "privat.pdf" not in r.text and "beta.pdf" not in r.text, "#2103: nothing about a closed file (no name)")
check(Bo.get(B + f"/api/files/nodes/{F_SECRET}/content").status_code == 404, "#2103: the content route keeps its own rights")
# tenant-matrix: wiki -- another organisation
r = refs(Ca, PG, [F_C], [f"datei:{F_C}"])
check(r.status_code == 404, f"#2103: a page of another organisation: 404 ({r.status_code})")
r = refs(A, PG, ["x"], [])
check(r.status_code == 400, f"#2103: invalid ids are refused ({r.status_code})")
r = refs(A, PG, list(range(1, 300)), [])
check(r.status_code == 400, f"#2103: at most 200 references per question ({r.status_code})")

# ---------------------------------------------------------------- backlinks
r = A.get(B + "/api/wiki/refs", params={"file": F_PDF})
check(r.ok and [p["id"] for p in r.json().get("pages", [])] == [PG], "#2107: the pages that reference a file " + r.text[:200])
r = Bo.get(B + "/api/wiki/refs", params={"file": F_PIC})
check(r.ok and [p["id"] for p in r.json().get("pages", [])] == [PG], "#2107: a member sees the backlinks of a file she may open")
check(Bo.get(B + "/api/wiki/refs", params={"file": F_SECRET}).status_code == 404, "#2107: no backlinks of a file one may not open")
check(Ca.get(B + "/api/wiki/refs", params={"file": F_PDF}).status_code == 404, "#2107: another organisation: 404")
r = A.get(B + "/api/wiki/refs", params={"sheet": SH})
check(r.ok and [p["id"] for p in r.json().get("pages", [])] == [PG], "#2107: the pages that link a table")
check(Ca.get(B + "/api/wiki/refs", params={"sheet": SH}).status_code == 404, "#2107: a table of another organisation: 404")
check(A.get(B + "/api/wiki/refs").status_code == 400, "#2107: file or sheet is needed")

# ---------------------------------------------------------------- the trash, the export, a file deleted for good
check(A.delete(B + f"/api/files/nodes/{F_PIC}").ok, "setup: the picture into the trash")
j = refs(A, PG, [F_PIC], []).json()
check(str(F_PIC) not in j.get("files", {}), "#2103: a file in the trash shows as not available")
check(A.get(B + "/api/wiki/refs", params={"file": F_PIC}).status_code == 404, "#2107: no backlinks of a file in the trash")
A.post(B + f"/api/files/nodes/{F_PIC}/restore")
check(str(F_PIC) in refs(A, PG, [F_PIC], []).json().get("files", {}), "#2103: back from the trash, visible again")
r = A.get(B + "/api/wiki/export", params={"space": SP})
with zipfile.ZipFile(io.BytesIO(r.content)) as z:
    md = z.read("Projekt.md").decode()
check(f"[[datei:{F_SECRET}|Liste]]" in md and f"/api/files/nodes/{F_PIC}/content" in md, "#2107: the export keeps the references as text")
check(A.delete(B + f"/api/files/nodes/{F_SECRET}").ok and A.delete(B + f"/api/files/nodes/{F_SECRET}", params={"purge": "1"}).ok,
      "setup: a file deleted for good")
check(F_SECRET not in links(PG)["file"], "#2103: the backlink rows of a file deleted for good are gone")

# ---------------------------------------------------------------- #2108: a converted checkbox line links its task
T = A.post(B + "/api/tasks", json={"title": "Angebot schicken", "priority": 3}).json()
r = A.patch(B + f"/api/wiki/pages/{PG}", json={"body": BODY + f"\n- [ ] Angebot schicken #{T['id']}\n- [ ] Noch offen\n"})
check(r.ok and links(PG)["task"] == [T["id"]], "#2108: the line links the task (to_task)")
r = A.get(B + "/api/wiki/mentions", params={"task": T["id"]})
check(r.ok and [p["id"] for p in r.json()["pages"]] == [PG], "#2108: the task shows the page under 'Mentioned in'")

# ---------------------------------------------------------------- a move to the private space ends the references
r = A.post(B + "/api/wiki/move-space", json={"pages": [PG], "space": SP, "to": "private", "dest": ""})
check(r.ok, "setup: the page into the private space " + r.text[:200])
L = links(PG)
check(L["file"] == [F_PRIV] and L["sheet"] == [], f"#2103: after the move no reference into the organisation's file store, the own private file now is one {L}")
j = refs(A, PG, ALL_F, ALL_L).json()
check(set(j.get("files", {})) == {str(F_PRIV)} and set(j.get("links", {})) == {f"datei:{F_PRIV}"},
      "#2103: only the private one is shown now (the text stays) " + str(j)[:300])
check(A.get(B + f"/api/wiki/pages/{PG}").json()["body"].startswith(BODY), "#2103: the text is unchanged")

# ---------------------------------------------------------------- freelancer-matrix: wiki (a person without an organisation)
FP = upload(Fr, "skizze.png", PNG, "image/png", space="private")
FS = Fr.post(B + "/api/sheets", json={"title": "Stunden", "space": "private"}).json()["id"]
OP = upload(Fo, "fremd.pdf", PDF, "application/pdf", space="private")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kunde/Notizen",
                                         "body": f"![s](/api/files/nodes/{FP}/content) [[tabelle:Stunden]] [[datei:skizze.png]] [[datei:{OP}]]"})
check(r.status_code == 201, "freelancer: a private page " + r.text[:200])
FPG = r.json()["id"]
check(links(FPG)["file"] == [FP] and links(FPG)["sheet"] == [FS], f"freelancer: own file and table kept, not another person's {links(FPG)}")
r = refs(Fr, FPG, [FP, OP], ["tabelle:stunden", "datei:skizze.png", f"datei:{OP}"])
j = r.json() if r.ok else {}
check(r.ok and set(j.get("files", {})) == {str(FP)} and set(j.get("links", {})) == {"tabelle:stunden", "datei:skizze.png"},
      "freelancer: sees her own file and table in her page, not another person's " + r.text[:300])
check(Fr.get(B + "/api/wiki/refs", params={"file": FP}).json().get("pages", [{}])[0].get("id") == FPG, "freelancer: the backlinks of her file")
check(Fr.get(B + "/api/wiki/refs", params={"sheet": FS}).ok, "freelancer: the backlinks of her table")
check(refs(Fo, FPG, [FP], []).status_code == 404 and Fo.get(B + "/api/wiki/refs", params={"file": FP}).status_code == 404,
      "freelancer: another person reaches neither the page nor the file")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
