"""2.146.0 B (#2453): the files inside a ZIP or a winmail.dat (Outlook's TNEF) of a receipt upload or a mail to a document
address. Everything stays in memory; no name of an entry is used as a path (only its file name, core/zipread.base_name).

 - ZIP: only through core/zipread.py (its rules: entry count first, no nested ZIPs, sizes never trusted). Wanted: PDF,
   pictures and XML (an e-invoice); other entries are left out and counted.
 - winmail.dat: a small reader of TNEF's attachment attributes (attAttachTitle = the name, attAttachData = the bytes). Every
   length is checked against the rest of the file, at most TNEF_FILES attachments, the same size limits as a ZIP. The MAPI
   properties (long file names, the mail's own body) are not read: a short name gets its type from the content.

  doc_unpack(name, data, files_max) -> (items [(name, bytes, mime)], errors [text])   None when data is neither"""
import mimetypes
import struct

from ..core.config import MAX_FILE_MB
from ..core.i18n import tr
from ..core import zipread as zr

DOC_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".xml")
DOC_FILE_MAX = MAX_FILE_MB * 1024 * 1024
DOC_UNPACKED_MAX = 60 * 1024 * 1024  # all files of one ZIP / winmail.dat together (as in the bank import)
DOC_FILES_MAX = 100  # wanted files of one ZIP (narrower than the bank import: each one becomes a document)
TNEF_SIG = 0x223E9F78
TNEF_FILES = 50
_ATT_REND, _ATT_TITLE, _ATT_DATA = 0x00069002, 0x00018010, 0x0006800F


def is_tnef(name, data):
    return (name or "").casefold() == "winmail.dat" or (len(data) >= 4 and struct.unpack_from("<I", data)[0] == TNEF_SIG)


def _mime(name, data):
    if data[:4] == b"%PDF":
        return "application/pdf"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _sniff_ext(name, data):
    """A TNEF title without a known type ("RECHNU~1", "ATT00001"): the type from the first bytes."""
    if name.casefold().endswith(DOC_EXTS):
        return name
    for head, ext in ((b"%PDF", ".pdf"), (b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png")):
        if data.startswith(head):
            return (name or "attachment") + ext
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1"):
        return (name or "attachment") + ".heic"
    if data.lstrip()[:5] == b"<?xml":
        return (name or "attachment") + ".xml"
    return name


def tnef_files(data):
    """[(name, bytes)] of the attachments of a TNEF stream; raises ValueError when it is no TNEF / broken."""
    if len(data) < 6 or struct.unpack_from("<I", data)[0] != TNEF_SIG:
        raise ValueError("no tnef")
    pos, n, out, cur, total = 6, len(data), [], None, 0
    while pos + 9 <= n:
        lvl, attr, ln = struct.unpack_from("<BII", data, pos)
        pos += 9
        if lvl not in (1, 2) or ln > n - pos - 2:
            raise ValueError("broken tnef")
        val = data[pos:pos + ln]
        pos += ln + 2  # the checksum is not checked (a wrong one only means a careless writer)
        if lvl != 2:
            continue
        if attr == _ATT_REND:
            if len(out) >= TNEF_FILES:
                break
            cur = {"name": "", "data": None}
            out.append(cur)
        elif cur is not None and attr == _ATT_TITLE:
            cur["name"] = zr.base_name(val.split(b"\x00", 1)[0].decode("cp1252", "replace"))
        elif cur is not None and attr == _ATT_DATA:
            total += len(val)
            if total > DOC_UNPACKED_MAX:
                raise zr.ZipLimit(tr("The files are too large together (at most {0} MB)", DOC_UNPACKED_MAX // (1024 * 1024)))
            cur["data"] = val
    return [(_sniff_ext(a["name"], a["data"]), a["data"]) for a in out if a["data"]]


def doc_unpack(name, data, files_max=DOC_FILES_MAX):
    """(items, errors) of a ZIP / winmail.dat; None when data is neither (the caller stores it as it is)."""
    name = zr.base_name(name) or "file"
    items, errors = [], []
    if zr.is_zip(name, data):
        try:
            z = zr.zip_read(data, DOC_EXTS, DOC_FILE_MAX, DOC_UNPACKED_MAX, zr.ZIP_ENTRIES_MAX, files_max)
        except zr.ZipLimit as x:
            return [], [f"{name}: {x}"]
        items = [(n, b, _mime(n, b)) for n, b in z.files]
        errors = [f"{name}: {e['file']}: {e['error']}" if e["file"] else f"{name}: {e['error']}" for e in z.errors]
        skipped = len(z.skipped)
    elif is_tnef(name, data):
        try:
            got = tnef_files(data)
        except zr.ZipLimit as x:
            return [], [f"{name}: {x}"]
        except (ValueError, struct.error):
            return [], [tr("{0}: the Outlook attachment (winmail.dat) cannot be read", name)]
        skipped = 0
        for n, b in got:
            if not n.casefold().endswith(DOC_EXTS):
                skipped += 1
            elif len(b) > DOC_FILE_MAX:
                errors.append(f"{name}: {n}: " + tr("The file is too large (at most {0} MB)", MAX_FILE_MB))
            else:
                items.append((n, b, _mime(n, b)))
    else:
        return None
    if skipped:
        errors.append(tr("{0}: {1} files of another type were left out", name, skipped))
    if not items and not errors:
        errors.append(tr("{0}: no PDF or picture inside", name))
    return items, errors
