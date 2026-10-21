"""2.146.0 C (#2455): the uploaded statements of one request -- the office's bank import (office/bank.py, 2.144.1 B #2450)
and the household budget's import (life/budget.py) take the same files the same way: several files or a ZIP in one
multipart request (field files), or the JSON body {text, filename} of earlier clients. Everything is read in memory only
(a ZIP through core/zipread, nothing is ever unpacked to disk); a file or entry name is shown, never used as a path.

  stmt_req(upload_max)          the request as a dict (JSON body, or the form fields of a multipart upload: mapping, account)
  stmt_uploads(b, limits)       -> StmtFiles: files [{name, text}], errors [{file, error}], skipped [names], labels
  stmt_decode / stmt_fname / is_mt940
Limits (STMT_LIMITS, the bank import's of 2.144.1): 2 MB per statement, 20 MB per request, 400 statements, 60 MB unpacked,
2000 ZIP entries."""
import json
import re

from flask import request

from . import zipread as zr
from .csvimport import csv_clean
from .db import body
from .i18n import tr

STMT_LIMITS = {"file_max": 2 * 1024 * 1024, "upload_max": 20 * 1024 * 1024, "files_max": 400, "unpacked_max": 60 * 1024 * 1024,
               "entries_max": 2000, "exts": (".xml", ".csv", ".txt")}
MT940_RE = re.compile(r"^:(20|25|28C|60[FM]|61|62[FM]):", re.M)


def _bad(msg):
    from ..core.errors import BadInput  # noqa: PLC0415 -- the app's 400 (a domain class; core imports it here only)
    return BadInput(msg)


def is_mt940(text):
    """A SWIFT MT940 / MT942 statement (its :20: / :60F: / :61: fields) -- not read; the dialogs ask for CAMT."""
    return len(MT940_RE.findall((text or "")[:20000])) >= 2


def stmt_fname(v):
    """Only the file name of an upload / a ZIP entry (no path, no control characters) -- shown, never used as a path."""
    v = v if isinstance(v, str) else ""
    return csv_clean(v.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1], 200)


def stmt_decode(data):
    """Bytes of a statement -> text: UTF-8 (a BOM dropped), else windows-1252 (as the clients did before)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


class StmtFiles:
    """The statements of one request: files [{name, text}], errors [{file, error}] (unreadable ones), skipped [names]
    (ZIP entries that are no statement), labels (the import's file name)."""

    def __init__(self, limits=None):
        self.lim = {**STMT_LIMITS, **(limits or {})}
        self.files, self.errors, self.skipped, self.labels, self.unpacked = [], [], [], [], 0

    def add(self, name, data):
        lim = self.lim
        if len(self.files) + len(self.errors) >= lim["files_max"]:
            raise _bad(tr("At most {0} files per import", lim["files_max"]))
        if len(data) > lim["file_max"]:
            self.errors.append({"file": name, "error": tr("The file is too large (at most {0} MB)", lim["file_max"] // (1024 * 1024))})
            return
        self.unpacked += len(data)
        if self.unpacked > lim["unpacked_max"]:
            raise _bad(tr("The files are too large together (at most {0} MB)", lim["unpacked_max"] // (1024 * 1024)))
        text = stmt_decode(data)
        if not text.strip():
            self.errors.append({"file": name, "error": tr("The file is empty")})
        else:
            self.files.append({"name": name, "text": text})

    def add_zip(self, name, data):
        # the shared in-memory reader (core/zipread, same rules as 2.144.1); its limits stop the whole import
        lim = self.lim
        try:
            z = zr.zip_read(data, lim["exts"], lim["file_max"], lim["unpacked_max"], lim["entries_max"], lim["files_max"])
        except zr.ZipLimit as x:
            raise _bad(str(x)) from None
        self.errors += [{**e, "file": e["file"] or name} for e in z.errors]
        if any(not e["file"] for e in z.errors):
            return
        self.skipped += z.skipped
        for base, part in z.files:
            self.add(base, part)
        n = z.n
        self.labels.append(tr("{0} ({1} files)", name, n) if n != 1 else name)


def stmt_uploads(b, limits=None):
    """The statements of the request: multipart (field files, several; a ZIP is opened) or the JSON body {text, filename}."""
    fs = StmtFiles(limits)
    lim = fs.lim
    if request.files:
        ups = [f for f in request.files.getlist("files") if f]
        if not ups:
            raise _bad(tr("The file is empty"))
        total, names = 0, []
        for f in ups:
            name = stmt_fname(f.filename) or tr("File")
            data = f.stream.read(lim["upload_max"] + 1 - total)
            total += len(data)
            if total > lim["upload_max"]:
                raise _bad(tr("The upload is too large (at most {0} MB)", lim["upload_max"] // (1024 * 1024)))
            if name.casefold().endswith(".zip") or data[:4] == b"PK\x03\x04":
                fs.add_zip(name, data)
            elif not name.casefold().endswith(lim["exts"]) and not is_mt940(stmt_decode(data[:20000])):  # MT940 (.sta ...) gets its own message
                fs.errors.append({"file": name, "error": tr("Not a bank statement (only XML, CSV or ZIP)")})  # 2.144.1 (review)
            else:
                fs.add(name, data)
                fs.labels.append(name)
            names.append(name)
        if len(ups) > 1:
            fs.labels = [csv_clean(tr("{0} files: {1}", len(ups), ", ".join(names)), 200)]
        return fs
    text = b.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _bad(tr("The file is empty"))
    if len(text.encode("utf-8", "ignore")) > lim["file_max"]:
        raise _bad(tr("The file is too large (at most {0} MB)", lim["file_max"] // (1024 * 1024)))
    fs.files.append({"name": stmt_fname(b.get("filename")), "text": text})
    fs.labels.append(csv_clean(b.get("filename"), 200))
    return fs


def stmt_req(upload_max=STMT_LIMITS["upload_max"]):
    """The request as a dict: the JSON body, or the form fields of a multipart upload (mapping as a JSON string, account)."""
    request.max_content_length = upload_max + 1024 * 1024  # 2.144.1 (review): werkzeug refuses a longer body itself, on any server
    if (request.content_length or 0) > request.max_content_length:  # before the form is parsed
        raise _bad(tr("The upload is too large (at most {0} MB)", upload_max // (1024 * 1024)))
    if not request.files:
        b = body()
        if not isinstance(b, dict):
            raise _bad(tr("Invalid data"))
        return b
    b = {}
    m = request.form.get("mapping")
    if m:
        try:
            b["mapping"] = json.loads(m)
        except ValueError:
            raise _bad(tr("Invalid data")) from None
    if request.form.get("account"):
        b["account"] = request.form.get("account")
    return b
