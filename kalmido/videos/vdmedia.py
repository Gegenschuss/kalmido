"""2.641.0 (#4769): the sign-off (videos/review.py) for images (JPG, PNG, WebP) and PDFs -- the same review, versions,
comments and states as a video, no second way. Columns: core/migrations.d/4769_a.py.

- A version of kind image | pdf points at a FILE OF THE FILE STORE (file_id + the file's version file_no); the file stays
  there. It comes from the file store (file_id, the person must see it) or as an upload, which lands in the folder
  "Approvals" at the top of the review's workspace (files/store.py fs_folder / fs_put: the store's size limit, quota and
  upload checks). Only files of the review's own workspace (the tenant boundary).
- The type is read from the CONTENT, never from the name or the browser's type: JPEG, PNG, WebP or PDF (vdm_sniff); SVG and
  everything else are refused (a picture with script). The bytes are served as that type only, sandboxed (files/web.py
  _send_headers, nosniff).
- Rights: the review's place decides as before (review.py vdr_may) AND every file of its versions must be visible to the
  person (files/store.py fs_role, also the locked folders and the agents' shares): who may not see the file sees no review
  (404). The content route asks the file store again (need_node: the trash, a locked folder).
- A comment's place: video {t} (at_sec), image {x, y}, PDF {page, x, y} (x / y = 0..1 of the width / height of the image or
  page; a PDF comment may name a page only). Numbered points: the app numbers the comments with a point per version in
  their order (page, then oldest first), the export the same.
- The customer link (signoff kind video) stays for videos: an image / PDF version is no public file (sharing outside = a task
  of its own). A review with files does not move to another workspace (its files stay in theirs)."""
from urllib.parse import quote

from flask import Response, request

from ..core.config import MAX_FILE_MB
from ..core.access import Denied
from ..core.db import body
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..files.store import fs_folder, fs_log_add, fs_put, fs_read, fs_role, fs_version_row, need_node, safe_fs_name
from ..files.upsafe import h6d_read
from ..files.web import _send_headers

VDM_KINDS = ("video", "image", "pdf")
VDM_PAGE_MAX = 9999
VDM_FOLDER = N_("Approvals|sign-off")
VDM_TYPES = N_("Please select an image (JPG, PNG, WebP) or a PDF.")
VDM_SPACE = N_("Only files of the same workspace can be added")
VDM_NOMOVE = N_("An approval of images or PDFs stays in the workspace of its files")


def vdm_sniff(data):
    """The type of the bytes by their first bytes: image/jpeg | image/png | image/webp | application/pdf, else None (SVG,
    HTML, anything else). The PDF header may sit within the first 1024 bytes (the PDF rule)."""
    d = bytes(data[:1024]) if data else b""
    if d[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        return "image/webp"
    if b"%PDF-" in d:
        return "application/pdf"
    return None


def vdm_kind(mime):
    return "pdf" if mime == "application/pdf" else "image" if mime else None


# ---------------------------------------------------------------- a version from the file store / an upload
def vdm_file_version(c, org_id, file_id):
    """A version dict (as review.vdr_parse's, plus kind / file_id / file_no / file_name / mime) of file file_id of the file
    store: the signed-in person must see it (need_node), a plain file of the review's workspace, an image or PDF by content."""
    if isinstance(file_id, bool) or not isinstance(file_id, int) or not 0 < file_id < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", "file_id"))
    n = need_node(c, file_id)
    if n["kind"] != "file":
        raise Denied(409, tr("Not a file"))
    if (n["org_id"] or None) != (org_id or None):
        raise Denied(409, tr(VDM_SPACE))
    v = fs_version_row(c, file_id)
    if not v:
        raise Denied(404)
    mime = vdm_sniff(fs_read(c, file_id, v["no"]))
    if not mime:
        raise BadInput(tr(VDM_TYPES))
    return {"url": "", "provider": "store", "embed_id": "", "kind": vdm_kind(mime), "file_id": file_id, "file_no": v["no"],
            "file_name": n["name"], "mime": mime}


def vdm_upload(c, uid, org_id, f):
    """An uploaded image / PDF -> into the folder "Approvals" at the top of workspace org_id (the person's own space when
    None) -> its version dict. The type is checked by content BEFORE anything is stored."""
    data = h6d_read(f)  # at most MAX_FILE_MB + 1 bytes in memory (fs_put refuses more)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise BadInput(tr("{0}: larger than {1} MB", safe_fs_name(f.filename or "") or "file", MAX_FILE_MB))
    mime = vdm_sniff(data)
    if not mime:
        raise BadInput(tr(VDM_TYPES))
    try:
        folder = fs_folder(c, uid, org_id, [tr(VDM_FOLDER)])
        nid = fs_put(c, uid, folder, safe_fs_name(f.filename or "") or "file", data, mime, org_id)
    except ValueError as e:
        raise BadInput(str(e)) from None
    fs_log_add(c, nid, "upload", "approval")
    return vdm_file_version(c, org_id, nid)


def vdm_body():
    """The request's fields: JSON, or a multipart form (an upload) with its numbers as numbers."""
    if request.mimetype != "multipart/form-data":
        b = body()
        return b if isinstance(b, dict) else {}
    b = {}
    for k, v in request.form.items():
        b[k] = int(v) if k in ("task_id", "list_id", "client_id", "file_id") and v.isdigit() else v
    return b


def vdm_media(c, uid, org_id, b, vdr_parse):
    """What a new review / a new version shows: an uploaded file (multipart "file"), a file of the file store {file_id} or a
    video link {url} (vdr_parse: review.py's, handed in -- review.py imports this module)."""
    f = request.files.get("file") if request.mimetype == "multipart/form-data" else None
    if f is not None:
        return vdm_upload(c, uid, org_id, f)
    if b.get("file_id") not in (None, "", 0):
        return vdm_file_version(c, org_id, b.get("file_id"))
    return dict(vdr_parse(b.get("url")), kind="video")


# ---------------------------------------------------------------- rights
def vdm_files_ok(c, uid, rid):
    """Every file of review rid's versions is visible to uid (a file removed for good: file_id NULL, no hindrance)."""
    ids = [r[0] for r in c.execute("SELECT DISTINCT file_id FROM video_versions WHERE review_id=? AND file_id IS NOT NULL", (rid,))]
    return all(fs_role(c, i, uid) for i in ids)


def vdm_has_files(c, rid):
    return bool(c.execute("SELECT 1 FROM video_versions WHERE review_id=? AND file_id IS NOT NULL LIMIT 1", (rid,)).fetchone())


def vdm_need_movable(c, rid):
    if vdm_has_files(c, rid):
        raise Denied(409, tr(VDM_NOMOVE))


# ---------------------------------------------------------------- a comment's place
def vdm_num(v, what, lo, hi, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < lo or v > hi or (integer and int(v) != v):
        raise BadInput(tr("Invalid value: {0}", what))
    return int(v) if integer else round(float(v), 4)


def vdm_pos(kind, b, at_parse):
    """(at_sec, page, x, y) of a new comment on a version of `kind` from {pos: {t} | {x, y} | {page, x?, y?}} or the older
    {at_sec}; all None = without a place. A place that does not fit the medium is refused (BadInput)."""
    p = b.get("pos")
    if p in (None, "", {}):
        p = {"t": b.get("at_sec")} if b.get("at_sec") not in (None, "") else {}
    if not isinstance(p, dict) or set(p) - {"t", "x", "y", "page"}:
        raise BadInput(tr("Invalid value: {0}", "pos"))
    if kind == "video":
        if set(p) - {"t"}:
            raise BadInput(tr("Invalid value: {0}", "pos"))
        return at_parse(p.get("t")), None, None, None
    if "t" in p or (("x" in p) != ("y" in p)) or (kind == "image" and "page" in p) or (kind == "pdf" and "x" in p and "page" not in p):
        raise BadInput(tr("Invalid value: {0}", "pos"))
    x = vdm_num(p["x"], "pos.x", 0, 1) if "x" in p else None
    y = vdm_num(p["y"], "pos.y", 0, 1) if "y" in p else None
    page = vdm_num(p["page"], "pos.page", 1, VDM_PAGE_MAX, integer=True) if "page" in p else None
    return None, page, x, y


def vdm_pos_dict(x):
    """A comment row's place for the answers: {t} | {x, y} | {page} | {page, x, y} | None."""
    if x["at_sec"] is not None:
        return {"t": x["at_sec"]}
    d = {"page": x["page"]} if x["page"] is not None else {}
    if x["pos_x"] is not None:
        d.update(x=x["pos_x"], y=x["pos_y"])
    return d or None


def vdm_marks(rows):
    """{comment id: number} of the numbered points: per version the top-level comments with a point (x / y), in the list's
    order (page, then oldest first) -- the app counts the same way."""
    out, n = {}, {}
    for x in sorted((x for x in rows if not x["parent_id"] and x["pos_x"] is not None),
                    key=lambda x: (x["version_id"] or 0, x["page"] or 0, x["id"])):
        n[x["version_id"]] = n.get(x["version_id"], 0) + 1
        out[x["id"]] = n[x["version_id"]]
    return out


def vdm_pos_text(x, mark=None):
    """The place of a comment for the exports: "Page 2 · 3" / "3" (the point's number) / "Page 2"; "" without."""
    parts = [tr("Page {0}", x["page"])] if x["page"] is not None else []
    if mark:
        parts.append(f"{mark}")
    return " · ".join(parts)


# ---------------------------------------------------------------- the bytes of a version
def vdm_send(c, v):
    """The image / PDF of version row v (the review was checked by the caller): the file store decides again (need_node:
    rights, trash, locked folder); served only as the type its content has, sandboxed."""
    if not v or not v["file_id"]:
        raise Denied(404)
    n = need_node(c, v["file_id"])
    if n["kind"] != "file":
        raise Denied(404)
    data = fs_read(c, v["file_id"], v["file_no"])
    mime = vdm_sniff(data)
    if not mime:
        raise Denied(404)
    fs_log_add(c, v["file_id"], "read", f"approval {int(v['review_id'])}")
    c.commit()
    name = v["file_name"] or n["name"] or "file"
    dl = request.args.get("dl") == "1"
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = f"{'attachment' if dl else 'inline'}; filename*=UTF-8''{quote(name)}"
    return _send_headers(resp, mime)


def vdm_version_row(c, rid, nid):
    return c.execute("SELECT * FROM video_versions WHERE id=? AND review_id=?", (nid, rid)).fetchone()
