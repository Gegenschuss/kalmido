"""2.959.0 (#4805): several PDF documents merged into one -- POST /api/docs/merge {ids: [first, ...], expect_version?}.

The pages of all chosen documents in the order of ids become a NEW VERSION of the first document's file (files/store.py
fs_new_version, as docs/pages.py): the first document keeps its id, archive number, sender, tags and links and is recognised
again (text, page count, preview); its older version stays (tab History). The other documents go into the trash through the
file store's own way (files/fskern.py fsk_trash = the core's obj_trash, as DELETE /api/files/nodes/<id>) and can be restored
from there. The whole merge is ONE step group of the person's undo list (GET /api/undo): taken back, the first file points at
its version before and the others come out of the trash.

Safety, as docs/pages.py: people only (agents 403), write ('edit') on EVERY document (need_node: 404 unseen, 403 read only),
all in one workspace (one organisation, or the same person's private area: 403 otherwise), only PDFs (409), not encrypted
(409), no document still being recognised (409), not in a locked folder (409 fs_locked), no receipt of a locked month or one
the bookkeeping has taken over (office/periodlock.py pl_receipt_need_open / pl_tree_need_open: 409) -- neither the first nor
one of the others. At most DM_DOCS documents, DP_PAGES pages and DP_BYTES bytes together (413). pypdf runs in the same
limited child process as docs/pages.py (memory, CPU, no files written), the page count of every PDF checked there again."""
import json

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, now_iso
from ..core.i18n import tr
from ..core.pg import write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..files.store import fs_log_add, fs_new_version, need_node
from ..files.web import fs_web_expect
from ..files.fsundo import fsu_post, fsu_pre
from ..files.fsref import fs_ref_trashed, fs_trash_prepare
from ..files.fsroots import fs_area_before, fs_area_root_need_free
from ..files.fslock import fsl_need_unlocked
from ..office.periodlock import pl_receipt_need_open, pl_tree_need_open
from .batch import dsr_idlist
from .ingest import docs_kick
from .pages import DP_BYTES, DP_PAGES, PAGES_WORKER, _dp_run, _known_pages, _pdf_doc, dp_count
from .split import _no_agent

DM_DOCS = 50  # documents merged at most at once

# the PDFs one after the other on stdin, argv JSON {lens: [bytes of each], ns: [pages of each]}; out: the merged PDF.
# Exit 3 = one is encrypted, 4 = the output budget exceeded, 5 = a page count is not the one the server checked against.
MERGE_WORKER = PAGES_WORKER[:PAGES_WORKER.index("ch = json.loads")] + r"""
ch = json.loads(sys.argv[1])
src = sys.stdin.buffer.read()
if sum(ch["lens"]) != len(src) or len(ch["lens"]) != len(ch["ns"]):
    sys.exit(5)
w = PdfWriter()
at = 0
for ln, n in zip(ch["lens"], ch["ns"]):
    r = PdfReader(io.BytesIO(src[at:at + ln]))
    at += ln
    if r.is_encrypted and not r.decrypt(""):
        sys.exit(3)
    if len(r.pages) != n:
        sys.exit(5)
    for p in r.pages:
        w.add_page(p)
b = io.BytesIO()
w.write(b)
out = b.getvalue()
if len(out) > 2 * len(src) + (32 << 20):
    sys.exit(4)
sys.stdout.buffer.write(out)
"""


def dm_same_space(nodes):
    """403 unless every node lies in the first one's workspace: the same organisation, or (none) the same owner's private area."""
    org, own = nodes[0]["org_id"] or None, nodes[0]["owner_id"]
    for n in nodes[1:]:
        if (n["org_id"] or None) != org or (org is None and n["owner_id"] != own):
            raise Denied(403, tr("Only documents of one workspace can be merged"))


def _merge(parts):
    """parts = [(bytes, pages)] -> the merged PDF, else Denied(409) (the messages of docs/pages.py _edit)."""
    p = _dp_run(MERGE_WORKER, json.dumps({"lens": [len(d) for d, _n in parts], "ns": [n for _d, n in parts]}), b"".join(d for d, _n in parts), 240)
    if p is None:
        raise Denied(409, tr("The pages cannot be read right now, try again later"))
    if p.returncode == 3:
        raise Denied(409, tr("The PDF is encrypted and cannot be changed"))
    if p.returncode == 5:
        raise Denied(409, tr("The PDF cannot be read"))
    if p.returncode != 0 or not p.stdout.startswith(b"%PDF"):
        raise Denied(409, tr("The pages cannot be read right now, try again later"))
    return p.stdout


@app.post("/api/docs/merge")
def docs_merge():
    """{ids: [first, second, ...] (the order of the pages), expect_version?: of the first} -> 201 {id, version, was, pages,
    trashed: [ids]}. The first document gets the new version, the others go into the trash."""
    _no_agent()
    c = db()
    uid = me()
    b = body()
    ids = dsr_idlist(b.get("ids"), DM_DOCS)
    if len(ids) < 2:
        raise Denied(400, tr("Select at least two documents"))
    nodes = [need_node(c, i, write=True) for i in ids]  # 404 unseen / 403 read only, before anything is read
    dm_same_space(nodes)
    for n in nodes:  # a locked folder, a locked month or a receipt taken over: nothing is read (fs_new_version checks the first again)
        fsl_need_unlocked(c, n["id"])
        pl_receipt_need_open(c, n["id"], uid=uid)
    for n in nodes[1:]:  # the others go into the trash: the checks of DELETE /api/files/nodes/<id>
        if n["parent_id"] is None and n["role"] != "owner":
            raise Denied(403)
        fs_area_root_need_free(c, n["id"])
        fs_area_before(c, uid, n)
        pl_tree_need_open(c, n["id"])
    first = ids[0]
    for i in sorted(ids):  # review F1: every document's lock (the same as an upload / docs/pages.py), sorted against a deadlock;
        write_lock(c, f"fs_version:{int(i)}")  # _pdf_doc below reads each one again under it (a merge in reverse order waits)
    fs_web_expect(c, first, b.get("expect_version"))
    parts, size, total, was = [], 0, 0, None
    for i in ids:
        m, n, data = _pdf_doc(c, i, True)  # 409 not a PDF, 413 too large, fs_locked
        if m["state"] in ("wait", "run"):
            return err(tr("The document is still being recognised"), 409)
        np = _known_pages(m, n) or dp_count(data)
        if np is None:
            return err(tr("The pages cannot be read right now, try again later"), 409)
        size += len(data)
        total += np
        if size > DP_BYTES:
            return err(tr("The file is too large (at most {0} MB)", DP_BYTES >> 20), 413)
        if total > DP_PAGES:
            return err(tr("At most {0} pages can be changed here", DP_PAGES), 413)
        parts.append((data, np))
        if i == first:
            was = n
    out = _merge(parts)
    fsu_pre(c, uid, was, "version")  # ONE step group of the request: the version of the first + the others into the trash
    try:
        no = fs_new_version(c, first, out, "application/pdf")
    except ValueError as e:
        c.rollback()
        return err(str(e))
    fs_log_add(c, first, "version", str(no))
    fsu_post(c)
    from ..files.fskern import fsk_trash  # the core's trash, as DELETE /api/files/nodes/<id>
    for n in nodes[1:]:
        fsu_pre(c, uid, n, "delete")
        _kept, refs = fs_trash_prepare(c, uid, n)
        fsk_trash(c, uid, n["id"])
        fs_log_add(c, n["id"], "trash")
        for r in refs:
            fs_ref_trashed(c, uid, r, False)
        fsu_post(c)
    # recognised again (text, page count, preview); the values set by hand and the archive number stay (as docs/pages.py)
    c.execute("UPDATE doc_meta SET state='wait', tries=0, error='', updated_at=? WHERE node_id=?", (now_iso(), first))
    bump(c)
    c.commit()
    docs_kick()
    return jsonify(id=first, version=no, was=was["cur_version"], pages=total, trashed=ids[1:]), 201
