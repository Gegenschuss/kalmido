"""2.61.0 (#1818 #1819 #1820): the shared upload path. Every writer of uploaded bytes (Ablage fs_put / fs_new_version,
task and comment files save_attachments / save_attachment_bytes, project files, chat files) runs

    up_check(...)        before the bytes are written / sealed: virus scan (files/scan.py), type from the content,
                         photo metadata removed (files/photometa.py); a find raises UploadRefused
    up_after_store(...)  after the row exists: an unchecked file is remembered for a later scan, the text recognition
                         of the file is queued (files/textscan.py)

Browser-encrypted files (e2e, 2.42.0 #828) never come here: the server cannot read them.
kind names the stored row: "fs" (fs_nodes id), "att" (attachments id), "list" (list_files id), "chat" (chat_files id), "wiki" (wiki_files id, 2.99.0 A #2182), "sheet" (sheet_files id, 2.124.0 B #2110)."""
import os
from ..core.config import MAX_FILE_MB  # 2.149.0 G (#2517): pulled up from functions

KINDS = ("fs", "att", "list", "chat", "tchat")  # 2.113.1 (#2059): tchat = tchat_files id


class UploadRefused(ValueError):
    """The upload is refused (a virus find); the message is shown to the uploader as it is."""


H6D_CHUNK = 1024 * 1024
H6D_SLACK = 1024 * 1024  # form fields + multipart framing around one file


def h6d_cap():
    return MAX_FILE_MB * 1024 * 1024


def h6d_one_file_request():
    """2.86.0 (N22): a route taking ONE file refuses a longer body from its Content-Length before anything is read
    (werkzeug answers 413, core/pages.py too_large; also counted while a body without a length streams in)."""
    from flask import request
    request.max_content_length = min(request.max_content_length or 1 << 62, h6d_cap() + H6D_SLACK)


def h6d_read(f, cap=None):
    """2.86.0 (N22): an uploaded file's bytes, at most cap + 1 (MAX_FILE_MB): the caller's size check refuses an
    oversize file without its whole content in memory."""
    return f.stream.read((h6d_cap() if cap is None else cap) + 1)


def h6d_save(f, full, cap=None):
    """2.86.0 (N22): f saved to full in pieces; stops after cap + 1 bytes (MAX_FILE_MB), so the caller's size check
    (os.path.getsize) refuses an oversize file without writing all of it. Returns the bytes written."""
    cap = h6d_cap() if cap is None else cap
    n = 0
    with open(full, "wb") as out:
        while n <= cap:
            b = f.stream.read(min(H6D_CHUNK, cap + 1 - n))
            if not b:
                break
            out.write(b)
            n += len(b)
    return n


def up_check(c, name, data, mime, uid=None, org_id=None, kind="att"):
    """The checks before the bytes are stored. Returns (data, mime, info): data maybe without photo metadata, mime maybe
    corrected from the content, info a dict for up_after_store (scan state, capture date ...). Raises UploadRefused."""
    from . import scan, photometa
    info = {"kind": kind}
    mime = scan.sc_sniff_mime(name, data, mime) or mime
    info["scan"] = scan.sc_scan(name, data)  # "clean" | "unchecked" | "off"; raises UploadRefused on a find
    out, meta = photometa.pm_strip(c, data, mime, uid, org_id)
    if out is not data and out != data and info["scan"] == "clean":  # the cut bytes are what is stored: scanned again
        info["scan"] = scan.sc_scan(name, out)
    data = out
    info.update(meta or {})
    return data, mime, info


def up_check_path(c, full, name, mime, uid=None, org_id=None, kind="att"):
    """up_check for a file a writer already saved in plain at `full` (before it is sealed). Rewrites the file when the
    bytes changed. Returns (size, mime, info); on UploadRefused the file is removed and the error raised on."""
    with open(full, "rb") as f:
        data = f.read()
    try:
        out, mime, info = up_check(c, name, data, mime, uid, org_id, kind)
    except UploadRefused:
        try:
            os.remove(full)
        except OSError:
            pass
        raise
    if out is not data and out != data:
        with open(full + ".up", "wb") as f:
            f.write(out)
        os.replace(full + ".up", full)
    return len(out), mime, info


def up_after_store(c, kind, ref_id, org_id, info):
    """After the row of the stored file exists (same transaction; the caller commits)."""
    from . import scan, textscan
    if not ref_id or not info:
        return
    scan.sc_after_store(c, kind, ref_id, org_id, info)
    textscan.ts_after_store(c, kind, ref_id, org_id, info)


def up_marks(c, kind, ids):
    """The marks of stored files for the client: {id: {"scan": "unchecked"|"infected", "text": "found"|"none"|"wait"}}, only
    ids with a mark. Every serializer of a file list (attachments, project files, Ablage, chat files) adds them as
    `up` to its rows."""
    from . import scan, textscan
    ids = [int(i) for i in ids if i]
    out = {}
    if not ids:
        return out
    for part in (scan.sc_marks(c, kind, ids), textscan.ts_marks(c, kind, ids)):
        for i, m in (part or {}).items():
            out.setdefault(i, {}).update(m)
    return out
