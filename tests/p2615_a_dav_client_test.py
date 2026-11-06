#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.615.0 A (#4513): a CalDAV smoke test with a REAL client, vdirsyncer (the other CalDAV suites only replay the requests of
Thunderbird / Tasks.org by hand). Own container, invented names only, no network outside the test container.
Per person (an organisation member, and a person without an organisation: CalDAV tasks are the private area, freelancer-matrix: pim):
 - a list made in the app is found by `vdirsyncer discover` and `sync` as a local folder (storage caldav -> filesystem, VTODO only),
   the task made in the app is a local .ics file
 - a new .ics file made locally ("the phone") is a task in the app after the next sync
 - a changed title in the app comes down, a changed title in the local file goes up
 - a deleted local file removes the task in the app; a task deleted in the app removes the local file
vdirsyncer comes from tests/requirements.txt (CI and the Mac runner install it from there); when it is missing the suite FAILS
(a hard red, never a silent green).
usage: p2615_a_dav_client_test.py <datadir>      (a fresh container; P2615A_NOSTART=1 = the server already runs)"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, until  # noqa: E402

TMP = tempfile.mkdtemp(prefix="p2615a-")
# the venv's bin folder first (the Mac runner and CI install the requirements into the interpreter's environment)
BIN = shutil.which("vdirsyncer", path=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))


def vds(cfg, *args):
    r = subprocess.run([BIN, "-c", cfg, *args], capture_output=True, text=True, timeout=120, input="y\n" * 20)  # discover asks once per new local folder: yes
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def config(name, user, pw):
    root = os.path.join(TMP, name)
    cfg = os.path.join(root, "config")
    os.makedirs(os.path.join(root, "status"), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(f'''[general]
status_path = "{root}/status/"

[pair tasks]
a = "local"
b = "remote"
collections = ["from b"]
conflict_resolution = "b wins"

[storage local]
type = "filesystem"
path = "{root}/local/"
fileext = ".ics"

[storage remote]
type = "caldav"
url = "{B}/dav/"
username = "{user}"
password = "{pw}"
item_types = ["VTODO"]
''')
    return cfg, os.path.join(root, "local")


def titles(lid):
    return [r[0] for r in kt.dbx("SELECT title FROM tasks WHERE list_id=? AND deleted_at IS NULL", (lid,))]


def files(folder):
    """{path: text} of the local .ics files of a folder."""
    out = {}
    for p in glob.glob(os.path.join(folder, "*.ics")):
        with open(p, encoding="utf-8") as f:
            out[p] = f.read()
    return out


def file_with(folder, title):
    return next((p for p, t in files(folder).items() if re.search(r"^SUMMARY:" + re.escape(title) + r"\s*$", t.replace("\r\n ", ""), re.M)), None)


def scenario(s, user, tag):
    r = s.post(B + "/api/me/app-passwords", json={"name": "vdirsyncer " + tag})
    check(r.ok, f"{tag}: app password ({r.status_code})")
    cfg, local = config(tag, user, r.json()["password"])
    lid = s.post(B + "/api/lists", json={"name": "Smoke " + tag}).json()["id"]
    s.post(B + "/api/tasks", json={"title": f"{tag} from the app", "list_id": lid})

    ok, out = vds(cfg, "discover", "tasks")
    check(ok, f"{tag}: vdirsyncer discover: {out}")
    ok, out = vds(cfg, "sync", "tasks")
    check(ok, f"{tag}: first sync: {out}")
    folder = os.path.join(local, str(lid))
    check(os.path.isdir(folder), f"{tag}: the list is a local folder named by its id ({os.listdir(local) if os.path.isdir(local) else 'no local folder'})")
    if not os.path.isdir(folder):
        return
    p = file_with(folder, f"{tag} from the app")
    check(p and "BEGIN:VTODO" in files(folder)[p], f"{tag}: the task made in the app is a local VTODO file ({list(files(folder).values())[:1]})")

    # a new file made locally -> a task in the app
    uid = f"p2615a-{tag}-local-1"
    with open(os.path.join(folder, uid + ".ics"), "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//vdirsyncer//EN", "BEGIN:VTODO", f"UID:{uid}",
                             "DTSTAMP:20261101T100000Z", f"SUMMARY:{tag} from the phone", "STATUS:NEEDS-ACTION", "END:VTODO",
                             "END:VCALENDAR", ""]))
    ok, out = vds(cfg, "sync", "tasks")
    check(ok, f"{tag}: sync with a new local file: {out}")
    check(until(lambda: f"{tag} from the phone" in titles(lid), 10), f"{tag}: the local file is a task in the app ({titles(lid)})")

    # a change in the app comes down
    tid = kt.dbx("SELECT id FROM tasks WHERE list_id=? AND title=?", (lid, f"{tag} from the app"))[0][0]
    check(s.patch(B + f"/api/tasks/{tid}", json={"title": f"{tag} renamed in the app"}).ok, f"{tag}: rename in the app")
    ok, out = vds(cfg, "sync", "tasks")
    check(ok, f"{tag}: sync after the rename: {out}")
    check(file_with(folder, f"{tag} renamed in the app") and not file_with(folder, f"{tag} from the app"),
          f"{tag}: the new title is in the local file")

    # a change in the local file goes up
    p = file_with(folder, f"{tag} from the phone")
    with open(p, encoding="utf-8", newline="") as f:
        txt = f.read()
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(txt.replace(f"SUMMARY:{tag} from the phone", f"SUMMARY:{tag} renamed on the phone"))
    ok, out = vds(cfg, "sync", "tasks")
    check(ok, f"{tag}: sync after the local change: {out}")
    check(until(lambda: f"{tag} renamed on the phone" in titles(lid), 10) and f"{tag} from the phone" not in titles(lid),
          f"{tag}: the local title is in the app ({titles(lid)})")

    # the server stores a task in its own form, so the first sync after an upload takes that form down once (RFC 4791 allows it);
    # after that a sync must change nothing: otherwise a deletion on one side would be answered with a copy from the other
    ok, out = vds(cfg, "sync", "tasks")
    check(ok and "Copying (updating) item p2615a-" in out, f"{tag}: the first sync after an upload takes the server's form down once: {out}")
    ok, out = vds(cfg, "sync", "tasks")
    check(ok and "Copying" not in out and "Deleting" not in out, f"{tag}: then a sync changes nothing: {out}")
    # deleting: local file -> task gone in the app; task in the app -> file gone locally
    os.remove(file_with(folder, f"{tag} renamed on the phone"))
    ok, out = vds(cfg, "sync", "tasks")
    check(ok, f"{tag}: sync after deleting a local file: {out}")
    check(until(lambda: f"{tag} renamed on the phone" not in titles(lid), 10), f"{tag}: the deleted file removed the task in the app ({titles(lid)})")
    check(s.delete(B + f"/api/tasks/{tid}").ok, f"{tag}: delete in the app")
    ok, out = vds(cfg, "sync", "--force-delete", "tasks")  # the last task: vdirsyncer's own guard against an emptied collection
    check(ok, f"{tag}: sync after deleting in the app: {out}")
    check(not files(folder), f"{tag}: the task deleted in the app is gone locally ({list(files(folder))})")


try:
    if not BIN:
        check(False, "vdirsyncer is not installed (pip install -r tests/requirements.txt): the suite cannot run, and a missing tool is never green")
    else:
        kt.fresh(prefix="P2615A")
        A = kt.setup()
        FID, Fr = freelancer(B, A)
        scenario(A, "alice", "org")
        scenario(Fr, "frida", "solo")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(kt.done("p2615_a_dav_client"))
