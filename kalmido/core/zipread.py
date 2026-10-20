"""2.146.0 (#2453 #2455 #2457): the one in-memory ZIP reader of the importers -- the bank import of 2.144.1 (#2450,
office/bank.py), receipts, the household budget and contacts read a ZIP the user picked here. Nothing is ever unpacked to
disk and no name of an entry is used as a path.

Rules (2.144.1 review, kept as they were): the entry count of the end record is checked before zipfile builds an object
per entry (zip64 is not taken), folders and the hidden files of packing systems (__MACOSX/, ._x, .x) are left out, nested
ZIPs and other types are skipped (never opened), encrypted entries get a message, the sizes in the ZIP's header are never
trusted (reading stops one byte after the limit), a broken entry never stops the others.

  zip_read(data, exts, file_max, total_max, entries_max) -> ZipRead(files [(name, bytes)], errors [{file, error}],
                                                             skipped [names], n)   raises ZipLimit (a translated text)
  is_zip(name, data)   a ZIP by name or by its first bytes
  base_name(v)         the file name of an upload / entry (no path, no control characters)"""
import io
import struct
import unicodedata
import zipfile

from .i18n import tr

ZIP_ENTRIES_MAX = 2000  # entries in a ZIP's central directory, checked before anything is read
ZIP_FILES_MAX = 400  # wanted files of one ZIP
ZIP_TOTAL_MAX = 60 * 1024 * 1024  # all wanted files together, unpacked


class ZipLimit(ValueError):
    """A hard limit of the whole ZIP (too many entries / files, too large together): the caller answers 400 with the text."""


class ZipRead:
    def __init__(self):
        self.files, self.errors, self.skipped, self.n, self.size = [], [], [], 0, 0


def base_name(v, n=200):
    v = v if isinstance(v, str) else ""
    v = v.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return "".join(ch for ch in v if unicodedata.category(ch)[0] != "C").strip()[:n]


def is_zip(name, data):
    return (name or "").casefold().endswith(".zip") or data[:4] == b"PK\x03\x04"


def _hidden(raw, base):
    return not base or raw.startswith("__MACOSX/") or "/__MACOSX/" in raw or base.startswith(".")


def zip_read(data, exts, file_max, total_max=ZIP_TOTAL_MAX, entries_max=ZIP_ENTRIES_MAX, files_max=ZIP_FILES_MAX):
    """The wanted entries (name ends with one of exts, casefolded) of the ZIP bytes. A file over file_max is an error
    entry, not a stop; total_max / files_max / entries_max stop the whole ZIP (ZipLimit). An unreadable ZIP gives one
    error entry with the name ""."""
    out = ZipRead()
    e = data.rfind(b"PK\x05\x06")
    cnt = struct.unpack_from("<H", data, e + 10)[0] if 0 <= e <= len(data) - 22 else None
    if cnt is not None and cnt > entries_max:
        raise ZipLimit(tr("The ZIP file holds too many entries (at most {0})", entries_max))
    if cnt is None or cnt == 0xFFFF:
        out.errors.append({"file": "", "error": tr("The ZIP file cannot be read")})
        return out
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except Exception:  # BadZipFile, a broken zip64 locator (struct.error) ...: never a 500
        out.errors.append({"file": "", "error": tr("The ZIP file cannot be read")})
        return out
    if len(infos) > entries_max:
        raise ZipLimit(tr("The ZIP file holds too many entries (at most {0})", entries_max))
    exts = tuple(x.casefold() for x in exts)
    for info in infos:
        raw = info.filename.replace("\\", "/")
        base = base_name(raw)
        if info.is_dir() or _hidden(raw, base):
            continue  # folders and the hidden files of the packing system
        if not base.casefold().endswith(exts):
            out.skipped.append(base)  # nested ZIPs included: never opened
            continue
        out.n += 1
        if out.n > files_max:
            raise ZipLimit(tr("At most {0} files per import", files_max))
        if info.flag_bits & 0x1:
            out.errors.append({"file": base, "error": tr("The file is encrypted; please pack it without a password")})
            continue
        try:  # the sizes in the ZIP's header are never trusted: reading stops one byte after the limit
            with zf.open(info) as f:
                part = f.read(file_max + 1)
        except Exception:  # BadZipFile, zlib.error, an unknown compression ...: a broken entry never stops the others
            out.errors.append({"file": base, "error": tr("The file cannot be read")})
            continue
        if len(part) > file_max:
            out.errors.append({"file": base, "error": tr("The file is too large (at most {0} MB)", max(1, file_max // (1024 * 1024)))})
            continue
        out.size += len(part)
        if out.size > total_max:
            raise ZipLimit(tr("The files are too large together (at most {0} MB)", total_max // (1024 * 1024)))
        out.files.append((base, part))
    return out
