"""2.117.0 B (#2285): PDF files of a framework contract (Office > Framework contracts: the signed contract, addenda).

GET    /api/office/contracts/<cid>/files                 -> {items: [{id, name, size, date, created_at}]} (who sees the contract)
POST   /api/office/contracts/<cid>/files                 multipart file (a PDF), date? (YYYY-MM-DD, default today),
                                                         replace? (the id of a file it replaces: that one goes to the trash) -> 201
GET    /api/office/contracts/<cid>/files/<fid>           the PDF (a download; the app shows it in its PDF viewer)
PATCH  /api/office/contracts/<cid>/files/<fid>           {date}
DELETE /api/office/contracts/<cid>/files/<fid>           -> the trash (deleted_at), the undo is .../restore
                                                         (2.993.0 #5413: the core's trash, also in the office trash)
POST   /api/office/contracts/<cid>/files/<fid>/restore

Rights like the contracts themselves (office/web.py): reading for who works in the office area (members of the organisation
with the module on, the owner of a personal office), writing for its admins; agents and kids 403 (office_gate); a contract
or file of another office area is 404. Only PDFs (magic %PDF-), at most MAX_FILE_MB like every upload, inside the storage
quota. The files lie flat below <data dir>/office/<org_id>/ like the stored quotation PDFs (backups, organisation export),
sealed with the office area's key at rest (oc_write_file; a personal office has its own orgs row = own key), served
decrypted (oc_read_file). Deleting the contract puts its files into the trash (model.office_delete -> dma_trash_contract);
trashed files are purged with their file after the trash period -- 2.993.0 (#5413): by the core's retention run (office/okern.py
ofk_register kind ocfile, obj_on_purge dma_file_purge: the stored file after the commit; dma_purge / dma_purge_tick went)."""
import hashlib
import os
import re
import urllib.parse
import uuid
from datetime import date as _date

from flask import Response, jsonify, request

from ..core.config import app, MAX_FILE_MB, OFFICE_DIR
from ..core.access import Denied, live_sql
from ..core.db import body, bump, db, iso, local_now, now_utc
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_read_file, oc_write_file
from ..core.pg import insert_id, system_ctx
from ..core.errors import BadInput
from ..files.scan import sc_after_store, sc_guard, sc_scan  # 2.190.0 D (#2561): pulled up, the later scan
from .ledger import ofx_log
from .oftref import oft_dropped  # 2.351.0 F (#2749)
from .model import office_gate, office_org
from .okern import ofk_register, ofk_restore, ofk_trash  # 2.993.0 (#5413): the files in the core's trash
from ..core.writes import obj_on_purge  # 2.993.0 (#5413): the stored file after the commit

DMA_MAX_FILES = 50  # per contract (contract + addenda)
DMA_NOT_PDF = N_("Only PDF files can be attached")


from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy
from ..files.upsafe import UploadRefused  # 2.369.5 (#2517): pulled up from functions


def dma_dir(oid):
    return os.path.join(OFFICE_DIR, str(int(oid)))


def dma_path(oid, file):
    """The stored file's path (file = a bare name below the office area's folder, never a path)."""
    if not file or os.path.basename(file) != file:
        return None
    return os.path.join(dma_dir(oid), file)


def dma_contract(c, oid, cid):
    # 2.905.0 (#5414, review): a contract in the trash takes no files (its files went to the files' trash with it)
    r = c.execute(f"SELECT id, name FROM office_contracts WHERE id=? AND org_id=? AND {live_sql()}", (int(cid), oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def dma_file(c, oid, cid, fid, deleted=False):
    r = c.execute("SELECT * FROM office_contract_files WHERE id=? AND org_id=? AND contract_id=?"
                  + ("" if deleted else " AND deleted_at IS NULL"), (int(fid), oid, int(cid))).fetchone()
    if not r:
        raise Denied(404)
    return r


def dma_public(r):
    return {"id": r["id"], "contract_id": r["contract_id"], "name": r["name"], "size": int(r["size"] or 0), "date": r["date"] or "",
            "created_at": r["created_at"]}


def _dma_unlink(p):
    def rm():  # after the commit (core/serializers.py unlink_files): OFFICE_DIR is not below ATT_DIR
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    return rm


def dma_file_purge(c, fid):
    """2.993.0 (#5413): obj_on_purge of a contract file (the core deletes it for good after the trash period or from the
    office trash): its node in a folder goes (2.351.0 F review N2), the stored file after the commit."""
    with system_ctx(c):  # no person in the retention run (ids and stored names only)
        r = c.execute("SELECT id, org_id, file FROM office_contract_files WHERE id=?", (int(fid),)).fetchone()
    if r is None:
        return None
    oft_dropped(c, "contract_file", r["id"])
    p = dma_path(r["org_id"], r["file"])
    return [_dma_unlink(p)] if p else None


def _dma_label(c, oid, row):
    k = c.execute("SELECT name FROM office_contracts WHERE id=? AND org_id=?", (row["contract_id"], oid)).fetchone()
    return " · ".join(x for x in ((k["name"] if k else "") or "", row.get("name") or "") if x)


def _dma_back(c, oid, row):
    """The office trash's restore of a file: only into a contract that is not in the trash (409 before the commit: else the
    file would be live under a contract nobody sees, and outlive its purge)."""
    if not c.execute(f"SELECT 1 FROM office_contracts WHERE id=? AND org_id=? AND {live_sql()}", (row["contract_id"], oid)).fetchone():
        raise Denied(409, tr(DMA_CONTRACT_GONE))


DMA_KIND = "ocfile"  # 2.993.0 (#5413): a contract file in the core's trash (office/okern.py; restorable in the office trash too)
DMA_CONTRACT_GONE = N_("The contract is in the trash; restore it first")
ofk_register(DMA_KIND, "office_contract_files", N_("Contract (PDF)"), "contracts", need="edit",
             view={"kind": "contract_file", "label": _dma_label, "ctx": lambda: _ctx(admin=True), "back": _dma_back}, step=False)
obj_on_purge(DMA_KIND, dma_file_purge)


def dma_counts(c, oid, rows):
    """The contracts list (office/web.py): files = the number of live PDFs per contract (the paper clip). 2.993.0 (#5413): the
    trash is purged by the core's retention run, no more on reading."""
    n = {r["contract_id"]: r["n"] for r in c.execute("SELECT contract_id, COUNT(*) AS n FROM office_contract_files WHERE org_id=? "
                                                      "AND deleted_at IS NULL GROUP BY contract_id", (oid,))}
    for r in rows:
        r["files"] = int(n.get(r["id"], 0))


def dma_trash_contract(c, oid, cid):
    """The contract is deleted: its files go into the trash (2.993.0 #5413: the core's, kind ocfile, purged by its retention run
    after the trash period; the contract's restore brings them back, office/web.py _omd_back)."""
    c.execute("UPDATE office_contract_files SET deleted_at=? WHERE org_id=? AND contract_id=? AND deleted_at IS NULL",
              (iso(now_utc()), oid, int(cid)))


def _date_in(v):
    if v in (None, ""):
        return local_now().date().isoformat()
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise BadInput(tr("Invalid value: {0}", "date"))
    try:
        d = _date.fromisoformat(v)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    if not 1900 <= d.year <= 2200:
        raise BadInput(tr("Invalid value: {0}", "date"))
    return v


def _name(n):
    n = os.path.basename((n or "").replace("\\", "/")).strip()
    n = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]+", "_", n)[:150] or "contract.pdf"
    return n if n.lower().endswith(".pdf") else n[:146] + ".pdf"


@app.get("/api/office/contracts/<int:cid>/files")
def dma_files_get(cid):
    c, uid, oid = _ctx()
    dma_contract(c, oid, cid)
    rows = c.execute("SELECT * FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NULL ORDER BY date, id",
                     (oid, cid)).fetchall()
    return jsonify(items=[dma_public(r) for r in rows])


@app.post("/api/office/contracts/<int:cid>/files")
def dma_files_post(cid):
    from ..admin.hosting import quota_guard
    c, uid, oid = _ctx(admin=True)
    ct = dma_contract(c, oid, cid)
    f = request.files.get("file")
    if f is None:
        raise BadInput(tr("Invalid value: {0}", "file"))
    old = None
    if request.form.get("replace"):
        try:
            old = dma_file(c, oid, cid, int(request.form["replace"]))
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "replace")) from None
    elif c.execute("SELECT COUNT(*) FROM office_contract_files WHERE org_id=? AND contract_id=? AND deleted_at IS NULL",
                   (oid, cid)).fetchone()[0] >= DMA_MAX_FILES:
        raise BadInput(tr("Invalid value: {0}", "file"))
    day = _date_in(request.form.get("date") or (old["date"] if old else None))
    quota_guard(c, uid)
    data = f.stream.read(MAX_FILE_MB * 1024 * 1024 + 1)
    name = _name(f.filename)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise BadInput(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))
    if not data.startswith(b"%PDF-"):
        raise BadInput(tr(DMA_NOT_PDF))
    try:
        scan = sc_scan(name, data)
    except UploadRefused as e:
        raise BadInput(str(e)) from None
    file = f"contract{int(cid)}-{uuid.uuid4().hex[:16]}.pdf"
    os.makedirs(dma_dir(oid), mode=0o700, exist_ok=True)
    path = dma_path(oid, file)
    oc_write_file(c, oid, path, data, fresh=True)  # sealed with the office area's key at rest (bytes from outside)
    os.chmod(path, 0o600)  # like the archive's files (a 0700 folder, 0600 files)
    ts = iso(now_utc())
    try:
        fid = insert_id(c, "INSERT INTO office_contract_files(org_id, contract_id, name, file, size, sha256, date, created_by, created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?)", (oid, cid, name, file, len(data), hashlib.sha256(data).hexdigest(), day, uid, ts))
        sc_after_store(c, "ocf", fid, oid, {"scan": scan})  # 2.190.0 D (#2561): scanner not reachable = checked later
        if old is not None:
            ofk_trash(c, uid, DMA_KIND, old["id"])  # 2.993.0 (#5413): the replaced file into the core's trash
        ofx_log(c, oid, "update", target="contracts", detail={"id": ct["id"], "file_added": name, "file_replaced": old["name"] if old else None})
        bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
        c.commit()
    except Exception:
        c.rollback()
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return jsonify({**dma_public(dma_file(c, oid, cid, fid)), "replaced": old["id"] if old else None}), 201


@app.get("/api/office/contracts/<int:cid>/files/<int:fid>")
def dma_file_get(cid, fid):
    c, uid, oid = _ctx()
    dma_contract(c, oid, cid)
    r = dma_file(c, oid, cid, fid)
    p = dma_path(oid, r["file"])
    if not p or not os.path.isfile(p):
        raise Denied(404)
    sc_guard(c, "ocf", fid)  # 2.190.0 D (#2561): found infected (strict: not checked yet) = locked
    resp = Response(oc_read_file(c, p), mimetype="application/pdf")
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", r["name"]) or "contract.pdf"  # review 2.117.0: fallback for old clients
    resp.headers["Content-Disposition"] = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'' + urllib.parse.quote(r["name"])
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


@app.patch("/api/office/contracts/<int:cid>/files/<int:fid>")
def dma_file_patch(cid, fid):
    c, uid, oid = _ctx(admin=True)
    dma_contract(c, oid, cid)
    r = dma_file(c, oid, cid, fid)
    b = body()
    if not isinstance(b, dict) or "date" not in b:
        raise BadInput(tr("Invalid data"))
    day = _date_in(b.get("date"))
    c.execute("UPDATE office_contract_files SET date=? WHERE id=? AND org_id=?", (day, r["id"], oid))
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(dma_public(dma_file(c, oid, cid, fid)))


@app.delete("/api/office/contracts/<int:cid>/files/<int:fid>")
def dma_file_delete(cid, fid):
    c, uid, oid = _ctx(admin=True)
    ct = dma_contract(c, oid, cid)
    r = dma_file(c, oid, cid, fid)
    ofk_trash(c, uid, DMA_KIND, r["id"])  # 2.993.0 (#5413): the core's trash (deleted_at / deleted_by), purged by its retention run
    ofx_log(c, oid, "update", target="contracts", detail={"id": ct["id"], "file_removed": r["name"]})
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/contracts/<int:cid>/files/<int:fid>/restore")
def dma_file_restore(cid, fid):
    c, uid, oid = _ctx(admin=True)
    dma_contract(c, oid, cid)
    r = dma_file(c, oid, cid, fid, deleted=True)
    if r["deleted_at"]:
        ofk_restore(c, uid, DMA_KIND, r["id"])  # 2.993.0 (#5413): out of the core's trash; past the trash period: gone (404)
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(dma_public(dma_file(c, oid, cid, fid)))
