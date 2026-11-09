"""2.777.0 B (#4874): pages of a PDF document deleted or turned by 90 degrees -- saved as a NEW VERSION of its file.

The document view's page strip (static/js/docpages.js) marks pages, deletes them (Del / the strip's buttons) and turns
them; "Save" sends the whole change at once: POST /api/docs/<id>/pages {delete: [1-based pages], rotate: {"<page>": 90 |
180 | 270}, expect_version}. The file gets a new version through the file store's version path (files/store.py
fs_new_version: rights, locked receipts / folders, quota, the upload checks); the older version stays and is the undo
("Restore version" of the tab History, files/web.py files_version_restore -- one step). The document keeps its id, archive
number, sender, tags and links; only the recognition runs again for the new content (text, page count, preview -- values
set by hand stay, docs/store.py HAND_FIELDS), no new sorting. Unlike "Split stack" (docs/split.py) nothing new is made.

GET /api/docs/<id>/pages gives what the strip needs: the page count, the file's version (expect_version), the pages the
stack scan found blank (doc_meta.split_scan pages[].blank -- a suggestion, nothing is deleted by it) and whether the
document is a receipt of the office (the strip says the original stays as a version).

Safety: people only (no agents, like the split), the right to write (need_node: 404 unseen, 403 read only), only PDFs (409
another kind, encrypted 409), at most DP_PAGES pages and DP_BYTES bytes (413), every page index checked here AND in the
child process against the real page count (400). pypdf runs in a limited child process like split.py CUT_WORKER (memory,
CPU, no files written, its output at most a few times the input). The check of the version (expect_version, 409 with the
file as it is now) and the new version are taken under the same lock as an upload (files/web.py fs_web_expect)."""
import json
import os
import subprocess
import sys
import threading

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, now_iso
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.pg import write_lock
from ..core.access import Denied
from ..accounts.session import me  # 2.777.0 (#5254)
from ..files.store import fs_log_add, fs_new_version, fs_read, need_node
from ..files.web import fs_web_expect
from ..files.fsundo import FSU_VERSION_HOOKS, fsu_post, fsu_pre  # 2.777.0 (#5254 #4874): the save is a step of the undo list
from ..tasks.attachtext import file_kind
from . import store as S
from .area import ar_is_receipt
from .ingest import docs_kick
from .split import _get as sp_get, _put as sp_put, _no_agent

DP_PAGES = 1000              # pages of a PDF this edits at most
DP_BYTES = 100 << 20         # bytes of a PDF this edits at most (the child process holds it a few times)
DP_TURNS = (90, 180, 270)
DP_WAIT = 20                 # review F3: seconds a request waits for a free place to read a PDF, then 409 "busy"
_DP_SEM = threading.BoundedSemaphore(2)  # review F3: at most two pypdf child processes of this route at once (like split.py _THUMB_SEM)
DP_BUSY = N_("Several PDFs are being read right now, try again in a moment.")  # the text of tasks/attachtext.py ERR_MSG busy

# pypdf in a limited child process: the PDF on stdin, the change as argv (JSON {n, delete, rotate}); out: the new PDF.
# Exit 3 = encrypted, 4 = the output budget exceeded, 5 = the page count is not the one the server checked against.
PAGES_WORKER = r"""
import io, json, resource, sys
for k, v in ((resource.RLIMIT_AS, 1024 << 20), (resource.RLIMIT_CPU, 120), (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
ch = json.loads(sys.argv[1])
src = sys.stdin.buffer.read()
r = PdfReader(io.BytesIO(src))
if r.is_encrypted and not r.decrypt(""):
    sys.exit(3)
n = len(r.pages)
if n != ch["n"]:
    sys.exit(5)
gone = set(ch["delete"])
turn = {int(k): v for k, v in ch["rotate"].items()}
w = PdfWriter()
for i in range(1, n + 1):
    if i in gone:
        continue
    p = w.add_page(r.pages[i - 1])
    if turn.get(i):
        p.rotate(turn[i])
        p[NameObject("/Rotate")] = NumberObject(int(p.get("/Rotate", 0) or 0) % 360)
b = io.BytesIO()
w.write(b)
out = b.getvalue()
if len(out) > 2 * len(src) + (32 << 20):
    sys.exit(4)
sys.stdout.buffer.write(out)
"""


COUNT_WORKER = PAGES_WORKER[:PAGES_WORKER.index("n = len(r.pages)")] + "sys.stdout.write(str(len(r.pages)))\n"


def _dp_run(code, arg, data, secs):
    """A limited pypdf child process (code, its argv JSON, the PDF on stdin). review F3: at most two at once, a request waits
    DP_WAIT seconds for a place (else 409 busy); review F2: a timeout or a failed start (fork) = None (the callers: 409)."""
    if not _DP_SEM.acquire(timeout=DP_WAIT):
        raise Denied(409, tr(DP_BUSY))
    try:
        return subprocess.run([sys.executable, "-I", "-c", code, arg], input=data, capture_output=True, timeout=secs, close_fds=True,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        _DP_SEM.release()


def dp_count(data):
    """The real page count of a PDF (the same limited child process, nothing written), None when it cannot be read."""
    p = _dp_run(COUNT_WORKER, "{}", data, 60)
    if p is None:
        return None
    try:
        return int(p.stdout.decode().strip()) if p.returncode == 0 else None
    except ValueError:
        return None


def dp_clean(b, n):
    """(delete [1-based pages, ascending], rotate {page: 90|180|270}) of a request body for a PDF of n pages, else BadInput.
    At least one page stays, at least one change."""
    dl, rt = b.get("delete", []), b.get("rotate", {})
    if not isinstance(dl, list) or not isinstance(rt, dict) or len(dl) > n or len(rt) > n:
        raise BadInput(tr("Invalid value: {0}", "pages"))
    gone = set()
    for p in dl:
        if not isinstance(p, int) or isinstance(p, bool) or not 1 <= p <= n or p in gone:
            raise BadInput(tr("Invalid value: {0}", "delete"))
        gone.add(p)
    turn = {}
    for k, v in rt.items():
        p = int(k) if isinstance(k, str) and k.isdigit() else None
        if p is None or not 1 <= p <= n or isinstance(v, bool) or not isinstance(v, int) or v % 360 not in (0, *DP_TURNS):
            raise BadInput(tr("Invalid value: {0}", "rotate"))
        if v % 360 and p not in gone:
            turn[p] = v % 360
    if len(gone) >= n:
        raise BadInput(tr("At least one page must stay"))
    if not gone and not turn:
        raise BadInput(tr("Nothing to change"))
    return sorted(gone), turn


def _edit(data, n, gone, turn):
    p = _dp_run(PAGES_WORKER, json.dumps({"n": n, "delete": gone, "rotate": {str(k): v for k, v in turn.items()}}), data, 180)
    if p is None:
        raise Denied(409, tr("The pages cannot be read right now, try again later"))
    if p.returncode == 3:
        raise Denied(409, tr("The PDF is encrypted and cannot be changed"))
    if p.returncode == 5:
        raise Denied(409, tr("The document is still being recognised"))
    if p.returncode != 0 or not p.stdout.startswith(b"%PDF"):
        raise Denied(409, tr("The pages cannot be read right now, try again later"))
    return p.stdout


def _pdf_doc(c, nid, write):
    """(meta, node, bytes) of a PDF document the signed-in person may see (write: change), else Denied."""
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m or n["kind"] != "file":
        raise Denied(404)
    if int(n["size"] or 0) > DP_BYTES:
        raise Denied(413, tr("The file is too large (at most {0} MB)", DP_BYTES >> 20))
    data = fs_read(c, nid)
    if file_kind(n["name"], n["mime"], data[:2048]) != "pdf":
        raise Denied(409, tr("Only the pages of a PDF can be changed"))
    return m, n, data


def _blank(m, n):
    """The 1-based pages the stack scan found blank, only while its pages are those of the file (a suggestion)."""
    pages = sp_get(m).get("pages")
    if not isinstance(pages, list) or len(pages) != n:
        return []
    return [i + 1 for i, p in enumerate(pages) if isinstance(p, dict) and p.get("blank")]


@app.get("/api/docs/<int:nid>/pages")
def docs_pages_get(nid):
    """{pages, version, blank: [1-based], receipt, max} of a PDF document (the page strip of the document view)."""
    _no_agent()
    c = db()
    m, n, data = _pdf_doc(c, nid, False)
    np = _known_pages(m, n)
    if np < 1:
        np = dp_count(data)
    return jsonify(pages=np or 0, version=n["cur_version"], blank=_blank(m, np or 0), receipt=ar_is_receipt(c, nid),
                   write=n["role"] != "view", max=DP_PAGES)


def _known_pages(m, n):
    """review F5: the page count the recognition found for the file's current version (0: not known, count it)."""
    if m["state"] == "done" and int(m["version"] or 0) == int(n["cur_version"] or 0):
        return int(m["pages"] or 0)
    return 0


@app.post("/api/docs/<int:nid>/pages")
def docs_pages_save(nid):
    """{delete?: [1-based pages], rotate?: {"<page>": 90|180|270}, expect_version?} -> the document with its new version
    (201). The file's older version stays (the undo: files_version_restore)."""
    _no_agent()
    c = db()
    b = body()
    need_node(c, nid, write=True)  # 403 / 404 before anything is read
    write_lock(c, f"fs_version:{int(nid)}")  # the same lock as an upload: no other version between the read and the write
    fs_web_expect(c, nid, b.get("expect_version"))
    m, n, data = _pdf_doc(c, nid, True)
    if m["state"] in ("wait", "run"):
        return err(tr("The document is still being recognised"), 409)
    np = _known_pages(m, n) or dp_count(data)  # review F5: the worker checks the count again (exit 5)
    if np is None:
        return err(tr("The pages cannot be read right now, try again later"), 409)
    if np > DP_PAGES:
        return err(tr("At most {0} pages can be changed here", DP_PAGES), 413)
    gone, turn = dp_clean(b, np)
    out = _edit(data, np, gone, turn)
    fsu_pre(c, me(), n, "version")  # 2.777.0 (#5254): the step points at the version before (taken back from the list too)
    try:
        no = fs_new_version(c, nid, out, "application/pdf")
    except ValueError as e:
        c.rollback()
        return err(str(e))
    fs_log_add(c, nid, "version", str(no))
    v = sp_get(m)  # the blank marks follow the pages that stay (the next recognition run reads them again)
    if isinstance(v.get("pages"), list) and len(v["pages"]) == np:
        sp_put(c, nid, {**v, "n": np - len(gone), "pages": [p for i, p in enumerate(v["pages"]) if i + 1 not in gone]})
    # recognised again (text, page count, preview); the sorting and the values set by hand stay (docs_redo without its undo copy)
    c.execute("UPDATE doc_meta SET state='wait', tries=0, error='', updated_at=? WHERE node_id=?", (now_iso(), nid))
    bump(c)
    fsu_post(c)
    c.commit()
    docs_kick()
    return jsonify(id=nid, version=no, was=n["cur_version"], pages=np - len(gone)), 201


def dp_version_back(c, uid, nid):
    """2.777.0 (#5254): an undo from the list pointed the file at another version (files/fsundo.py FSU_VERSION_HOOKS): the
    document is recognised again at once, as after files_version_restore (the values set by hand stay)."""
    c.execute("UPDATE doc_meta SET state='wait', tries=0 WHERE node_id=? AND state IN ('done', 'failed')", (int(nid),))


FSU_VERSION_HOOKS.append(dp_version_back)
