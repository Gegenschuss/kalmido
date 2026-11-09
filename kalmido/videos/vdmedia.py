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
import io
import os

from flask import request

from ..core.config import ATT_DIR, MAX_FILE_MB
from ..core.access import Denied
from ..core.db import body, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_is_sealed_file, oc_plain_size, oc_read_file, oc_send_file
from ..core.pg import system_ctx
from ..files.fslock import fsl_of_chain
from ..files.scan import sc_guard
from ..files.store import fs_chain, fs_deleted, fs_folder, fs_log_add, fs_put, fs_role, fs_version_row, need_node, safe_fs_name
from ..files.upsafe import h6d_read
from ..files.web import _send_headers

VDM_KINDS = ("video", "image", "pdf")
VDM_HEAD = 1024  # 2.658.0 (#5043): the type is read from the first VDM_HEAD bytes only (never the whole file)
VDM_PAGE_MAX = 9999
VDM_FOLDER = N_("Approvals|sign-off")
VDM_TYPES = N_("Please select an image (JPG, PNG, WebP), a PDF or an audio file (MP3, M4A, AAC, WAV, OGG, Opus, FLAC).")  # 2.658.0 (#5015): + audio
VDM_SPACE = N_("Only files of the same workspace can be added")
VDM_NOMOVE = N_("An approval of images or PDFs stays in the workspace of its files")
# 2.773.0 (#5330): a sealed file (core/orgcrypt.py, decrypted whole per request) above this size is not handed out through
# the customer link (no sign-in), only signed in (vdm_send); a plain file streams from disk and has no such limit
VDM_PUB_SEALED_MB = float(os.environ.get("KALMIDO_REVIEW_LINK_SEALED_MAX_MB") or 50)


def vdm_sniff(data):
    """The type of the bytes by their first bytes: image/jpeg | image/png | image/webp | application/pdf, else None (SVG,
    HTML, anything else). The PDF header may sit within the first 1024 bytes (the PDF rule)."""
    d = bytes(data[:VDM_HEAD]) if data else b""
    if d[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        return "image/webp"
    a = vdm_sniff_audio(d)  # 2.658.0 (#5015): before the PDF rule (its header may sit anywhere in the first bytes)
    if a:
        return a
    if b"%PDF-" in d:
        return "application/pdf"
    return None


def vdm_sniff_audio(d):
    """2.658.0 (#5015): an audio file by its first bytes -- WAV, OGG (Vorbis / Opus), FLAC, M4A, MP3 (ID3 tag or a frame),
    AAC (ADTS) -- else None. The <audio> element plays it; a version from the file store is a timed medium like an audio link."""
    if d[:4] == b"RIFF" and d[8:12] == b"WAVE":
        return "audio/wav"
    if d[:4] == b"OggS":
        return "audio/ogg"
    if d[:4] == b"fLaC":
        return "audio/flac"
    if d[4:8] == b"ftyp" and d[8:11] in (b"M4A", b"M4B"):
        return "audio/mp4"
    if d[:3] == b"ID3":
        return "audio/mpeg"
    if len(d) >= 4 and d[0] == 0xFF:
        if d[1] & 0xF6 == 0xF0:  # ADTS: sync, layer 00
            return "audio/aac"
        # an MPEG audio frame: sync, a version (not the reserved 01), layer III or II (2.658.0 Fable review: layer I / the
        # bits of a UTF-16 LE byte order mark FF FE are no MP3), a bit rate, a sample rate (not the reserved 11)
        if (d[1] & 0xE0 == 0xE0 and d[1] & 0x18 != 0x08 and d[1] & 0x06 in (0x02, 0x04)
                and d[2] & 0xF0 not in (0x00, 0xF0) and d[2] & 0x0C != 0x0C):
            return "audio/mpeg"
    return None


def vdm_kind(mime):
    """The version kind of a sniffed type: pdf | image | video (2.658.0 #5015: audio = the timed medium, provider audio)."""
    if not mime:
        return None
    return "pdf" if mime == "application/pdf" else "video" if mime.startswith("audio/") else "image"


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
    mime = vdm_sniff(vdm_head(c, vdm_path(c, file_id, v["no"])))
    if not mime:
        raise BadInput(tr(VDM_TYPES))
    return {"url": "", "provider": "audio" if mime.startswith("audio/") else "store", "embed_id": "", "kind": vdm_kind(mime), "file_id": file_id, "file_no": v["no"],
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
    return dict(vdm_file_version(c, org_id, nid), uploaded=1)  # 2.662.0 (#5041): this version's file follows the review's rights


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
def vdm_by_review(c, v, chain):
    """2.662.0 (#5041): may the review's rights (vdr_may) stand in for the file store's for version row v's file? Only for a
    file uploaded through the sign-off for exactly this version (uploaded = 1), still a plain file of the review's workspace,
    in no locked folder and under no filed mail (those keep their own rules); else the file right decides (strict)."""
    if not v["uploaded"] or not chain or chain[0]["kind"] != "file" or (chain[0]["org_id"] or None) != (v["org_id"] or None):
        return False
    if any(r["hub_mail_id"] for r in chain):
        return False
    return fsl_of_chain(c, chain) is None


def vdm_node(c, v):
    """2.662.0 (#5041): the file row of version row v for vdm_send: a file uploaded for exactly this version (vdm_by_review)
    without the file right (the caller checked the review: vdr_need / vdr_v1_need), still 404 in the trash; else need_node."""
    chain = fs_chain(c, v["file_id"])
    if not vdm_by_review(c, v, chain):
        return need_node(c, v["file_id"])
    if fs_deleted(chain):
        raise Denied(404)
    return dict(chain[0])


def vdm_files_ok(c, uid, rid):
    """Every file of review rid's versions is visible to uid (a file removed for good: file_id NULL, no hindrance).
    2.662.0 (#5041): the file of a version uploaded through the sign-off needs no file right (vdm_by_review: the review's
    place decides, vdr_may); a file chosen from the file store does, also when it was uploaded for another review."""
    rows = c.execute("SELECT file_id, uploaded, org_id FROM video_versions WHERE review_id=? AND file_id IS NOT NULL", (rid,)).fetchall()
    need = {r["file_id"] for r in rows if not r["uploaded"]}
    for r in rows:
        if r["file_id"] not in need and not vdm_by_review(c, r, fs_chain(c, r["file_id"])):
            need.add(r["file_id"])
    return all(fs_role(c, i, uid) for i in need)


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
def vdm_path(c, file_id, no):
    """2.658.0 (#5043): the stored file of version no of file file_id (no rights check: need_node first); a version found
    infected later is locked (sc_guard), a missing one is 404."""
    v = fs_version_row(c, file_id, no)
    if not v:
        raise Denied(404)
    sc_guard(c, "fs", file_id, v["no"])
    full = os.path.join(ATT_DIR, v["path"])
    if not os.path.isfile(full):
        raise Denied(404)
    return full


def vdm_open(c, full):
    """2.658.0 (#5043): (head, data) of a stored file: head = its first VDM_HEAD plain bytes; a plain file reads only those
    (data None: streamed later), a sealed one (core/orgcrypt.py: AES-GCM opens the file only whole) is decrypted ONCE here
    and data = its plain bytes for the answer (Fable review: was decrypted twice per request, the head and the send)."""
    if oc_is_sealed_file(full):
        data = oc_read_file(c, full)
        return data[:VDM_HEAD], data
    with open(full, "rb") as f:
        return f.read(VDM_HEAD), None


def vdm_head(c, full):
    """The first VDM_HEAD plain bytes of a stored file (vdm_open)."""
    return vdm_open(c, full)[0]


def vdm_stream(c, full, data, **kw):
    """The answer for a stored file opened with vdm_open: a plain file streamed (range requests), a sealed one from the bytes
    already decrypted (range requests on them, no ETag: as core/orgcrypt.py oc_send_file)."""
    if data is None:
        return oc_send_file(c, full, conditional=True, **kw)
    from flask import send_file
    return send_file(io.BytesIO(data), conditional=True, etag=False, last_modified=os.path.getmtime(full), **kw)


def vdm_send(c, v):
    """The image / PDF / audio of version row v (the review was checked by the caller): the file store decides again
    (need_node: rights, trash, locked folder); served only as the type its first bytes have, sandboxed. 2.658.0 (#5043):
    streamed through the file store's way (files/web.py _send: oc_send_file, range requests, 206), not read into memory."""
    if not v or not v["file_id"]:
        raise Denied(404)
    n = vdm_node(c, v)  # 2.662.0 (#5041): was need_node -- an upload of this version follows the review (checked by the caller)
    if n["kind"] != "file":
        raise Denied(404)
    full = vdm_path(c, v["file_id"], v["file_no"])
    head, data = vdm_open(c, full)
    mime = vdm_sniff(head)
    if not mime:
        raise Denied(404)
    fs_log_add(c, v["file_id"], "read", f"approval {int(v['review_id'])}")
    c.commit()
    dl = request.args.get("dl") == "1"
    resp = vdm_stream(c, full, data, mimetype=mime, as_attachment=dl, download_name=v["file_name"] or n["name"] or "file",
                      max_age=0)
    return _send_headers(resp, mime)


def vdm_pub_send(c, v, s):
    """2.658.0 (#5015): the audio file of version row v for customer link s (office/signoff.py, checked open by the caller):
    only a file of the link's workspace, still in the file store (not in the trash, not in a locked folder), still visible
    to the person who made the link (the file's access), only as audio by its first bytes; streamed (range requests).
    None = not available (the caller answers like an unknown link). 2.773.0 (#5330): "too_big" = a sealed file above
    VDM_PUB_SEALED_MB (no content, the caller answers 413); a fetch that starts playing is noted in the file's history
    (action ext_view, detail "approval <id>": the file store shows it as an external link, files/extlinks.py xl_log)."""
    if not v or not v["file_id"] or v["provider"] != "audio":
        return None
    with system_ctx(c):  # the public page reads as "anon"; the checks below bind it to exactly this link's file and workspace
        chain = fs_chain(c, v["file_id"])
        if (not chain or chain[0]["kind"] != "file" or fs_deleted(chain) or fsl_of_chain(c, chain) is not None
                or (chain[0]["org_id"] or None) != (s["org_id"] or None) or not fs_role(c, v["file_id"], s["created_by"], chain=chain)
                # 2.658.0 (Fable review): a disabled account's link no longer serves the file (as the list links, signoff.py)
                or not c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (s["created_by"],)).fetchone()):
            return None
        try:
            full = vdm_path(c, v["file_id"], v["file_no"])
        except Denied:
            return None
        if vdm_pub_too_big(full):  # 2.773.0 (#5330): checked BEFORE anything is decrypted
            return "too_big"
        head, data = vdm_open(c, full)
        mime = vdm_sniff(head)
        if not mime or not mime.startswith("audio/"):
            return None
        if vdm_pub_first(request.headers.get("Range")):  # 2.773.0 (#5330): the guest's fetch in the file's history (as vdm_send)
            c.execute("INSERT INTO fs_log(node_id,user_id,agent,action,detail,at) VALUES(?,?,?,?,?,?)",
                      (int(v["file_id"]), None, 0, "ext_view", f"approval {int(v['review_id'])}", iso(now_utc())))
            c.commit()
        resp = vdm_stream(c, full, data, mimetype=mime, as_attachment=False, download_name=v["file_name"] or "audio", max_age=0)
    return _send_headers(resp, mime)


def vdm_pub_too_big(full):
    """2.773.0 (#5330): a sealed stored file larger than VDM_PUB_SEALED_MB: the customer link does not hand it out (each request
    would decrypt it whole, many addresses could keep the server busy with one link)."""
    return oc_is_sealed_file(full) and oc_plain_size(full) > VDM_PUB_SEALED_MB * 1024 * 1024


def vdm_pub_first(rng):
    """2.773.0 (#5330): a request that starts playing (no range, or a range from byte 0) -- only those go into the file's history,
    not every seek of the <audio> element (as files/extlinks.py logs one entry per page view)."""
    if not rng:
        return True
    r = rng.strip().lower().replace(" ", "")
    # review 2.773 F2: Safari's probe "bytes=0-1" (and any closed range from 0) is no start of playing - only an open "bytes=0-"
    return r == "bytes=0-"


def vdm_version_row(c, rid, nid):
    return c.execute("SELECT * FROM video_versions WHERE id=? AND review_id=?", (nid, rid)).fetchone()
