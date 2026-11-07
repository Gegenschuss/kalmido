"""Office & finance (2.39.1, #1182): the legacy import -- one's own clients, services and equipment from a spreadsheet
(.xlsx, read with zipfile + xml.etree only) and old invoices / quotations as a read-only archive of PDFs.

The person uploads the files, sees a preview, corrects it and confirms; nothing is guessed behind their back and no
language model is involved. Clients come from the sheet / table "Contacts" (column "addresses": ONE text per address),
split by rules into company, contact, street, postcode, city and country; uncertain splits carry their reasons. Duplicates
(normalised name + postcode) against the organisation's clients and within the file are skipped by default (or merged /
added). "Services" and "Equipment" fill the master data of the same name; separator rows like "---- VIDEO ----" are
categories. Sheets without a model in Kalmido (staff, freelancers) are only counted.

Archive: one PDF per old invoice / quotation, the key data proposed from the file name
(<project no>_<client>_<project>__<date>_R.pdf, quotations <project>_<client>_KV<n>_<date>_<initials>.pdf), the amount and
"paid" by hand. Stored unchanged below the organisation's office folder (in backups); never re-rendered, renumbered, sent
or turned into an e-invoice. New invoice numbers never collide with archived ones (fi_number_taken, used by
docs._assign_number); the counter can be set above the highest imported number (the person confirms the proposal).

Every confirmed import is a run (office_import_runs); its records carry the run id. Undoing a run removes what nothing
builds on yet (a client with a list, document, contract or archived document stays; so does a service used in a
document) and says what stayed. Only the organisation's admins (the stricter of "master data" and "clients"); agent
tokens and kids are stopped by office_gate."""
import codecs
import contextlib
import hashlib
import hmac
import io
import json
import os
import re
import threading
import unicodedata
import zipfile
import zlib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from flask import jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.i18n import N_, tr
from ..core.pg import insert_id, write_lock
from ..core.db import body, bump, db, iso, local_now, now_utc, parse_iso
from ..core.access import Denied
from ..core.errors import BadInput
from .model import (MD, pb_cl_org, pb_cl_sql, office_create, office_gate, office_in_use, office_number_format, office_org, office_role, office_rows, office_scheme_period,
                    office_settings, office_update)
from ..core.csvimport import amount_text, csv_table  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_seal, oc_send_file  # 2.149.0 G (#2517): pulled up from functions
from ..files.scan import sc_guard, sc_up  # 2.209.0 D (#1856)
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..team.clients import cl_refs, cl_trash
from .contacts_cl import fk_has_name, fk_add, fk_sync  # 2.369.5 (#2517): pulled up from functions
from ..team.clients import clean_client  # 2.369.5 (#2517): pulled up from functions
from .model import office_row  # 2.369.5 (#2517): pulled up from functions
from .model import office_settings_lock, office_settings_save  # 2.621.0 (#4600): the kept file name template
from ..files.upsafe import UploadRefused  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachtext import pdf_text, PDF_RATE  # 2.369.5 (#2517): pulled up from functions
from .ledger import ofx_company, ofx_log  # 2.369.5 (#2517): pulled up from functions
from .invoices import inv_manual_seq, inv_scheme  # 2.369.5 (#2517): pulled up from functions
from ..core import config  # 2.369.5 (#2517): pulled up from functions

FI_XLSX_MAX = 10 * 1024 * 1024  # the uploaded spreadsheet
FI_XLSX_UNZIPPED_MAX = 80 * 1024 * 1024  # all members unpacked (zip bomb guard)
FI_PDF_MAX = 20 * 1024 * 1024
FI_ROWS_MAX = 2000  # rows per sheet taken into the preview
FI_COLS_MAX = 200  # 2.148.1 D (#2485): columns per sheet / table range
FI_PARTS_MAX = 64  # 2.148.1 D (#2485): sheets and tables read per workbook
FI_NAME_MAX = 80  # clients.name
# 2.576.0 (#4188): the parts are read as a stream (iterparse): a sheet stops at its row limit, the filled cells of the
# whole workbook at FI_CELLS_MAX, before the file is read in all; a part read as a tree holds at most XL_TREE_MAX elements
FI_CELLS_MAX = 200_000  # filled cells of all sheets together
XL_STRINGS_MAX = 200_000  # entries of sharedStrings.xml (sheets/io.py uses the same reader)
XL_TREE_MAX = 200_000  # elements of a part kept as a whole tree (workbook, styles, relations, tables)
XL_DEPTH_MAX = 64  # 2.576.0 (#4188): open elements at once (OOXML needs fewer than 10); deeper = not a spreadsheet
XL_CHUNK = 1 << 16  # bytes fed to the parser at once
XL_IMPORTS_AT_ONCE = 2  # .xlsx files read at the same time (per app process); one more = 429 at once, no waiting
_XL_SLOTS = threading.BoundedSemaphore(XL_IMPORTS_AT_ONCE)

# ---------------------------------------------------------------- reasons shown next to an uncertain split
FI_REASONS = {
    "no_zip": N_("No postcode found"),
    "zip4": N_("Postcode with 4 digits: Austria or Switzerland?"),
    "no_street": N_("No street found"),
    "po_box": N_("P.O. box instead of a street"),
    "extra_lines": N_("More lines than expected: please check company and contact"),
    "country": N_("Country not recognised"),
    "co": N_("c/o line moved to the contact"),
    "long_name": N_("Name shortened"),
    "bad_email": N_("E-mail address not readable, left out"),  # 2.363.0 (#3103)
    "bad_vat": N_("VAT ID too long, left out"),  # 2.363.0 (#3103)
    "one_line": N_("Only one line"),
    "foreign": N_("Address abroad: please check the fields"),
    "person_swap": N_("First line taken as the contact person: please check"),
}


# ---------------------------------------------------------------- reading .xlsx (zipfile + xml.etree)
def _local(tag):
    return tag.rsplit("}", 1)[-1]


@contextlib.contextmanager
def xl_slot():
    """2.576.0 (#4188): one of the XL_IMPORTS_AT_ONCE places for reading an .xlsx; none free = Denied 429 with a clear text
    (a third large file must not wait in a request thread nor push the app over its memory)."""
    if not _XL_SLOTS.acquire(blocking=False):
        raise Denied(429, tr("Two spreadsheet imports are running already. Please try again in a minute."))
    try:
        yield
    finally:
        _XL_SLOTS.release()


def xl_events(z, name, budget, most, events=("start", "end")):
    """2.576.0 (#4188): a part of the archive as (event, element) pairs of ET.XMLPullParser, read in XL_CHUNK pieces. The
    unpacked size counts against budget (at most `most` for the whole file); the guards against entity tricks stay
    (no DOCTYPE in the first 4 KB, no ENTITY anywhere, single-byte encodings only), checked on every piece BEFORE the
    parser sees it. The caller clears what it has read; stopping early stops reading the part. Open elements nest at
    most XL_DEPTH_MAX deep (counted here for every reader: elements that never end hold memory no end event counts)."""
    info = z.getinfo(name)
    if info.file_size + budget[0] > most:
        raise BadInput(tr("The file is too large"))
    budget[0] += info.file_size
    bad = BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    p = ET.XMLPullParser(("start", "end"))
    seen, tail, depth = 0, b"", 0
    with z.open(name) as fh:  # ZipExtFile reads at most file_size bytes
        while True:
            chunk = fh.read(XL_CHUNK)
            if not chunk:
                break
            if not seen and (chunk[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in chunk[:4]):  # 2.148.1 G (#2496)
                raise bad
            probe = (tail + chunk).upper()  # a word cut between two pieces is still seen
            if b"<!ENTITY" in probe or (seen < 4096 and b"<!DOCTYPE" in probe[:4096 - seen + len(tail)]):
                raise bad
            seen += len(chunk)
            tail = chunk[-16:]
            p.feed(chunk)
            for ev, el in p.read_events():
                depth += 1 if ev == "start" else -1
                if depth > XL_DEPTH_MAX:
                    raise bad
                if ev in events:
                    yield ev, el
    p.close()
    for ev, el in p.read_events():
        if ev in events:
            yield ev, el


def _xml(z, name, budget, most=FI_XLSX_UNZIPPED_MAX):
    """A (small) part as a whole tree; 2.576.0 (#4188): streamed, at most XL_TREE_MAX elements (counted when they start:
    an element without its end holds memory as well)."""
    root, n = None, 0
    for ev, el in xl_events(z, name, budget, most):
        if ev == "end":
            continue
        if root is None:
            root = el
        n += 1
        if n > XL_TREE_MAX:
            raise BadInput(tr("The file is too large"))
    if root is None:
        raise ET.ParseError("empty part")
    return root


def xl_strings(z, budget, most):
    """2.576.0 (#4188): the texts of xl/sharedStrings.xml, one <si> after the other (plain <t> or rich text runs <r><t>;
    phonetic hints <rPh> are not text); at most XL_STRINGS_MAX entries. Every child of <sst> leaves the tree when it ends;
    n counts the elements since the last <si> left (fable review: not reset by anything else)."""
    out, open_, n = [], [], 0
    for ev, el in xl_events(z, "xl/sharedStrings.xml", budget, most):
        if ev == "start":
            open_.append(el)
            continue
        open_.pop()
        n += 1
        if n > XL_TREE_MAX:  # one <si> with endless runs, or anything else between the entries
            raise BadInput(tr("The file is too large"))
        if len(open_) != 1:  # inside an entry (kept until it ends) or the root itself
            continue
        sst = open_[0]
        if _local(el.tag) == "si":
            out.append("".join(t.text or "" for t in el.iter() if _local(t.tag) == "t" and not _in_rph(el, t)))
            if len(out) > XL_STRINGS_MAX:
                raise BadInput(tr("Too many filled cells (at most {0})", XL_STRINGS_MAX))
            el.clear()
            sst.remove(el)
            n = 0
        else:
            sst.remove(el)  # not an entry: gone, still counted until the next <si>
    return out


def _col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]*", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return max(n - 1, 0)


def _range(ref):
    m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", ref or "")
    if not m:
        return None
    c1, r1 = _col_index(m.group(1)), int(m.group(2))
    c2, r2 = (_col_index(m.group(3)), int(m.group(4))) if m.group(3) else (c1, r1)
    if c1 > FI_COLS_MAX:  # 2.148.1 D (#2485): cap the column span like the sheet reader does
        return None
    return c1, r1, min(c2, FI_COLS_MAX), r2


def _rels(z, path, budget):
    """{rId: target path inside the archive} of a part's relations."""
    d, f = os.path.split(path)
    rp = f"{d}/_rels/{f}.rels" if d else f"_rels/{f}.rels"
    if rp not in z.namelist():
        return {}
    out = {}
    for el in _xml(z, rp, budget):
        t = el.get("Target") or ""
        if t.startswith("/"):
            t = t[1:]
        else:
            t = os.path.normpath(os.path.join(d, t)).replace(os.sep, "/")
        out[el.get("Id")] = t
    return out


def fi_xlsx_read(raw):
    """{lower-case name: [[cell text, ...], ...]} of every sheet and every table (a table: only its range) of an .xlsx.
    Cells are text ('' when empty); numbers keep their stored form (e.g. '650' or '12.5'). BadInput for anything else."""
    if not raw.startswith(b"PK"):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
    except (zipfile.BadZipFile, ValueError):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None
    if "xl/workbook.xml" not in names or len(names) > 2000:
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    with xl_slot():  # 2.576.0 (#4188): at most two at once
        return _xlsx_book(z, names)


def _xlsx_book(z, names):
    budget, filled = [0], [0]
    try:
        strings = xl_strings(z, budget, FI_XLSX_UNZIPPED_MAX) if "xl/sharedStrings.xml" in names else []  # 2.576.0 (#4188)
        wb = _xml(z, "xl/workbook.xml", budget)
        wrels = _rels(z, "xl/workbook.xml", budget)
        zeros = _fmt_zeros(z, names, budget)
        out = {}
        parts = 0
        for sh in wb.iter():
            if _local(sh.tag) != "sheet":
                continue
            parts += 1
            if parts > FI_PARTS_MAX:  # 2.148.1 D (#2485): bounded number of sheets / tables
                raise BadInput(tr("The file is too large"))
            rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
            path = wrels.get(rid)
            if not path or path not in names:
                continue
            grid = _sheet(z, path, strings, budget, zeros, filled)
            out.setdefault((sh.get("name") or "").strip().lower(), grid)
            for t in _rels(z, path, budget).values():  # the sheet's tables (Excel "Format as table"; Power Query output)
                if t in names and "/tables/" in t:
                    parts += 1
                    if parts > FI_PARTS_MAX:
                        raise BadInput(tr("The file is too large"))
                    tb = _xml(z, t, budget)
                    rg = _range(tb.get("ref"))
                    if not rg:
                        continue
                    c1, r1, c2, r2 = rg
                    rows = [[(grid[r - 1][c] if r - 1 < len(grid) and c < len(grid[r - 1]) else "") for c in range(c1, c2 + 1)]
                            for r in range(r1, min(r2, r1 + FI_ROWS_MAX) + 1)]
                    for nm in (tb.get("displayName"), tb.get("name")):
                        if nm:
                            out.setdefault(nm.strip().lower(), rows)
        return out
    # 2.148.1 D (#2485): encrypted / unsupported compression (RuntimeError, NotImplementedError) -> 400 as well
    except (ET.ParseError, KeyError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError):  # broken file -> 400, not 500
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None


def _in_rph(si, t):
    for rph in si:
        if _local(rph.tag) == "rPh" and any(x is t for x in rph.iter()):
            return True
    return False


def _fmt_zeros(z, names, budget):
    """2.363.0 (#3103): {cell style index: digits} of the styles that show a number with leading zeros (format "00000"):
    a postcode or customer number stored as a number keeps them, as Excel shows it."""
    if "xl/styles.xml" not in names:
        return {}
    try:
        st = _xml(z, "xl/styles.xml", budget)
    except (ET.ParseError, BadInput):
        return {}  # only a nicety: a broken style part does not stop the import
    fmts = {x.get("numFmtId"): x.get("formatCode") or "" for x in st.iter() if _local(x.tag) == "numFmt"}
    out = {}
    for sec in st:
        if _local(sec.tag) == "cellXfs":
            for i, xf in enumerate(x for x in sec if _local(x.tag) == "xf"):
                m = re.fullmatch(r"(?:\[\$-[0-9A-Fa-f]+\])?(0{2,})", fmts.get(xf.get("numFmtId"), ""))
                if m:
                    out[str(i)] = len(m.group(1))
    return out


def _sheet(z, path, strings, budget, zeros=None, filled=None):
    """2.576.0 (#4188): streamed, one cell after the other: reading stops after FI_ROWS_MAX + 50 rows; the filled cells of
    the workbook (filled = [count] shared by its sheets) stop at FI_CELLS_MAX. Every child of the root, of <sheetData> and
    of a <row> leaves the tree when it ends; n counts the elements since the last row left (fable review: a cell does not
    reset it, so nothing between the cells or rows piles up uncounted)."""
    rows, filled = {}, [0] if filled is None else filled
    sd = row = cells = None
    open_ = []  # the open elements, root first
    k = r = n = 0
    for ev, el in xl_events(z, path, budget, FI_XLSX_UNZIPPED_MAX):
        tag = _local(el.tag)
        if ev == "start":
            if len(open_) == 1 and sd is None and tag == "sheetData":
                sd = el
            elif sd is not None and open_[-1] is sd and tag == "row":
                r = int(el.get("r") or (max(rows) + 1 if rows else 1))
                if r > FI_ROWS_MAX + 50:
                    break
                row, cells, k = el, {}, 0
            open_.append(el)
            continue
        open_.pop()
        n += 1
        if n > XL_TREE_MAX:  # one cell or row with endless children, or anything else between them
            raise BadInput(tr("The file is too large"))
        parent = open_[-1] if open_ else None
        if parent is None:
            continue
        if parent is not row and parent is not sd and len(open_) != 1:
            continue  # inside a cell or another element: kept until that one ends
        if el is sd:
            break  # the rest of the sheet (merged cells, tables, ...) is not read
        if el is not row and (parent is not row or tag != "c"):
            parent.remove(el)  # not a row / cell (or a part of the sheet before <sheetData>): gone, still counted
            continue
        if parent is row:
            cel, k = el, k + 1
            ref = cel.get("r")
            ci = _col_index(ref) if ref else k - 1
            v = None
            if ci <= 200:
                t = cel.get("t")
                for ch in cel:
                    if _local(ch.tag) == "v":
                        v = ch.text or ""
                    elif _local(ch.tag) == "is":
                        v = "".join(x.text or "" for x in ch.iter() if _local(x.tag) == "t")
            row.remove(cel)
            if v is None:
                continue
            if t == "s":
                try:
                    v = strings[int(v)]
                except (ValueError, IndexError):
                    v = ""
            elif t == "b":
                v = "1" if v == "1" else "0"
            elif t == "e":
                v = ""
            elif t in (None, "n") and re.fullmatch(r"-?\d+\.0+", v):
                v = v.split(".")[0]
            if zeros and t in (None, "n") and v.isdigit() and cel.get("s") in zeros:
                v = v.zfill(zeros[cel.get("s")])
            if v != "" and ci not in cells:
                filled[0] += 1
                if filled[0] > FI_CELLS_MAX:
                    raise BadInput(tr("Too many filled cells (at most {0})", FI_CELLS_MAX))
            cells[ci] = v
        else:  # the row ends
            rows[r] = cells
            row.clear()
            sd.remove(row)
            row = cells = None
            n = 0
    if not rows:
        return []
    width = max((max(c) + 1 for c in rows.values() if c), default=0)
    return [[rows.get(r, {}).get(c, "") for c in range(width)] for r in range(1, max(rows) + 1)]


def _table(book, *names):
    """(header [lower-case], data rows) of the first sheet / table of that name; None when the file has none."""
    for n in names:
        rows = book.get(n)
        if rows is None:
            continue
        for i, row in enumerate(rows[:10]):  # the header: the first row with text
            if any(str(x).strip() for x in row):
                return [str(x).strip().lower() for x in row], rows[i + 1:]
        return [], []
    return None


# ---------------------------------------------------------------- the address splitter
COUNTRIES = {
    "deutschland": "DE", "germany": "DE", "brd": "DE", "allemagne": "DE", "österreich": "AT", "oesterreich": "AT", "austria": "AT",
    "schweiz": "CH", "switzerland": "CH", "suisse": "CH", "svizzera": "CH", "frankreich": "FR", "france": "FR", "niederlande": "NL",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "belgien": "BE", "belgium": "BE", "belgique": "BE", "luxemburg": "LU",
    "luxembourg": "LU", "italien": "IT", "italy": "IT", "italia": "IT", "spanien": "ES", "spain": "ES", "españa": "ES", "dänemark": "DK",
    "denmark": "DK", "danmark": "DK", "schweden": "SE", "sweden": "SE", "norwegen": "NO", "norway": "NO", "polen": "PL", "poland": "PL",
    "tschechien": "CZ", "czech republic": "CZ", "czechia": "CZ", "großbritannien": "GB", "grossbritannien": "GB", "vereinigtes königreich": "GB",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "great britain": "GB", "irland": "IE", "ireland": "IE", "portugal": "PT",
    "usa": "US", "u.s.a.": "US", "united states": "US", "united states of america": "US", "vereinigte staaten": "US", "kanada": "CA",
    "canada": "CA", "liechtenstein": "LI", "finnland": "FI", "finland": "FI", "ungarn": "HU", "hungary": "HU", "griechenland": "GR", "greece": "GR",
}
ZIP_PREFIX = {"D": "DE", "DE": "DE", "A": "AT", "AT": "AT", "CH": "CH", "F": "FR", "FR": "FR", "NL": "NL", "B": "BE", "BE": "BE", "L": "LU",
              "LU": "LU", "I": "IT", "IT": "IT", "DK": "DK", "FL": "LI", "LI": "LI"}
ZIP_RE = re.compile(r"^(?:(?P<pre>[A-Z]{1,2})\s?[-–]\s?)?(?P<zip>\d{4,5})\s+(?P<city>\S.*)$")
NL_ZIP_RE = re.compile(r"^(?P<zip>\d{4}\s?[A-Z]{2})\s+(?P<city>\S.*)$")
UK_ZIP_RE = re.compile(r"^(?P<city>.*?)[,\s]+(?P<zip>[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})$", re.I)
UK_ZIP_FRONT_RE = re.compile(r"^(?P<zip>[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2})\s+(?P<city>[A-Z][A-Za-z .'-]{1,30})$")
US_ZIP_RE = re.compile(r"^(?P<city>.+?),?\s+(?P<st>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)$")
ATTN_RE = re.compile(r"^(?:z\.\s?h(?:d|än)?\.?|zu\s+händen|zh\.?|attn\.?:?|attention:?|to the attention of)\s*:?\s*", re.I)
CO_RE = re.compile(r"^c\s?/\s?o\b\.?\s*", re.I)
POBOX_RE = re.compile(r"^(?:postfach|p\.?\s?o\.?\s?box|postbox|case postale|boîte postale|bp)\b", re.I)
FI_NAME_RE = re.compile(r"^(?:[A-ZÄÖÜ][a-zäöüß'’.-]+\s+){1,3}[A-ZÄÖÜ][a-zäöüß'’-]+$")  # 2.46.2 (#1646): "Lena Muster"
PERSON_RE = re.compile(r"^(?:herrn?|frau|mr\.?|mrs\.?|ms\.?|dr\.?|prof\.?)\s+\S", re.I)
LEGAL_RE = re.compile(r"\b(?:gmbh|mbh|ag|kg|ohg|gbr|ug|se|e\.?\s?v\.?|e\.?\s?k\.?|ltd\.?|limited|inc\.?|llc|llp|plc|corp\.?|s\.?a\.?r?\.?l?\.?|b\.?v\.?|"
                      r"s\.?r\.?l\.?|sas|oy|ab|as|aps|& co\.?|co\. kg|\w*gesellschaft|agentur|studio|verlag|stiftung|verein|institut|universität|"
                      r"hochschule|ministerium|amt|bank|group|media|medien|film|production|productions)\b", re.I)
STREET_RE = re.compile(r"(?:\d+\s*[a-zA-Z]?(?:\s*[-/]\s*\d+\s*[a-zA-Z]?)?\s*$|^\d+[a-zA-Z]?\s+\S|str\.|straße|strasse|weg\b|platz\b|allee\b|"
                       r"gasse\b|ring\b|damm\b|ufer\b|chaussee\b|markt\b|street|road|avenue|lane|rue\b|via\b|calle\b|laan\b|straat\b)", re.I)


def _clean_line(s):
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s or "")
    return re.sub(r"\s+", " ", s).strip(" ,;\t")


def fi_split_address(text):
    """One address text -> {name, contact, street, zip, city, country, address, flags} (flags: keys of FI_REASONS; empty =
    a confident split). Works on lines; a one-line address is cut at commas."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_clean_line(x) for x in raw.split("\n")]
    lines = [x for x in lines if x]
    flags = []
    if len(lines) == 1 and "," in lines[0]:
        lines = [_clean_line(x) for x in lines[0].split(",") if _clean_line(x)]
    out = {"name": "", "contact": "", "street": "", "zip": "", "city": "", "country": "", "address": "\n".join(lines)[:500], "flags": flags}
    if not lines:
        return out
    if len(lines) == 1:
        out["name"] = lines[0]
        flags.append("one_line")
        _shorten(out)
        return out
    country = ""
    last = lines[-1].strip(" .").lower()
    if last in COUNTRIES:
        country = COUNTRIES[last]
        lines = lines[:-1]
    elif re.fullmatch(r"[A-Za-zÄÖÜäöüß .'-]{3,40}", lines[-1]) and len(lines) >= 4 and not STREET_RE.search(lines[-1]) \
            and not LEGAL_RE.search(lines[-1]):
        flags.append("country")  # a last line that reads like a country name nobody knows here
    contacts = []
    rest = []
    for ln in lines:
        m = ATTN_RE.match(ln)
        if m and ln[m.end():].strip():
            contacts.append(ln[m.end():].strip())
            continue
        if CO_RE.match(ln):
            contacts.append(ln)
            flags.append("co")
            continue
        rest.append(ln)
    # the postcode + city line: from the bottom
    zi = None
    for i in range(len(rest) - 1, 0, -1):
        ln = rest[i]
        m = ZIP_RE.match(ln)
        if m:
            pre = (m.group("pre") or "").upper()
            z = m.group("zip")
            out["zip"], out["city"] = z, m.group("city").strip()
            if pre and pre in ZIP_PREFIX:
                country = country or ZIP_PREFIX[pre]
            if not country:
                if len(z) == 5:
                    country = "DE"
                else:
                    flags.append("zip4")
            elif len(z) == 5 and country in ("AT", "CH"):
                flags.append("no_zip")
            zi = i
            break
        m = NL_ZIP_RE.match(ln) if country in ("NL", "") else None
        if m and country == "NL":
            out["zip"], out["city"], zi = m.group("zip"), m.group("city"), i
            break
        m = US_ZIP_RE.match(ln) if country in ("US", "") else None
        if m:
            out["zip"], out["city"], zi = m.group("zip"), f"{m.group('city').strip()}, {m.group('st')}", i
            country = country or "US"
            break
        m = UK_ZIP_RE.match(ln) if country in ("GB", "IE") else None
        m = m or (UK_ZIP_FRONT_RE.match(ln) if country in ("GB", "IE", "") else None)  # 2.56.1 (#1813): "EC4M 7RB London"
        if m:
            country = country or "GB"
            out["zip"], out["city"], zi = m.group("zip").upper(), m.group("city").strip(" ,"), i
            break
    if zi is None:
        flags.append("no_zip")
        # without a postcode the last line is taken as the city (a foreign address in a free form)
        if len(rest) >= 2 and not re.search(r"\d", rest[-1]) and not POBOX_RE.match(rest[-1]):
            out["city"] = rest[-1]
            zi = len(rest) - 1
    head = rest[:zi] if zi is not None else rest[:]
    after = rest[zi + 1:] if zi is not None else []
    if after:  # lines below the city (a district, a second country line): keep them in the free text only
        flags.append("extra_lines")
    # the street: the line right above the postcode line
    if len(head) >= 2:
        cand = head[-1]
        if POBOX_RE.match(cand):
            out["street"] = cand
            flags.append("po_box")
            head = head[:-1]
        elif STREET_RE.search(cand):
            out["street"] = cand
            head = head[:-1]
        else:
            flags.append("no_street")
    else:
        flags.append("no_street")
    # company and contact from the remaining head lines
    if head:
        first = head[0]
        others = head[1:]
        # 2.46.2 (#1646): a plain person's name (also without "Frau"/"Herr") above a whole company name with a legal form is
        # the person; a company name on two lines ("Musterfirma" / "GmbH & Co. KG") stays together
        swap = others and LEGAL_RE.search(others[0]) and not PERSON_RE.match(others[0])
        if swap and PERSON_RE.match(first):  # "Frau X" above "Firma GmbH"
            contacts.insert(0, first)
            first, others = others[0], others[1:]
        elif swap and FI_NAME_RE.match(first) and not LEGAL_RE.match(others[0]) and not others[0].startswith("&") \
                and len(others[0].split()) > 1:
            contacts.insert(0, first)
            first, others = others[0], others[1:]
            flags.append("person_swap")
        out["name"] = first
        for ln in others:
            if LEGAL_RE.search(ln) and not PERSON_RE.match(ln) and len(out["name"]) + len(ln) < FI_NAME_MAX:
                out["name"] = f"{out['name']} {ln}"  # a company name on two lines
            else:
                contacts.append(ln)
        if len(others) > 1:
            flags.append("extra_lines")
    elif contacts:
        out["name"] = contacts.pop(0)
    out["contact"] = ", ".join(contacts)[:120]
    out["country"] = country
    if country and country not in ("DE",) and "foreign" not in flags and (not out["zip"] or country not in ("AT", "CH")):
        flags.append("foreign")
    _shorten(out)
    out["flags"] = list(dict.fromkeys(flags))
    return out


def _shorten(out):
    if len(out["name"]) > FI_NAME_MAX:
        out["name"] = out["name"][:FI_NAME_MAX].rstrip()
        out["flags"].append("long_name")


# ---------------------------------------------------------------- duplicates
LEGAL_WORDS = re.compile(r"\b(?:gmbh|mbh|ag|kg|ohg|gbr|ug|haftungsbeschrankt|se|ev|ek|ltd|limited|inc|llc|plc|corp|co|und|and|the|die|der|das)\b")


def fi_norm(name):
    """A company name for comparing: lower case, without accents, legal forms, punctuation and spaces."""
    s = unicodedata.normalize("NFKD", (name or "").lower().replace("ß", "ss"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[&+.,/()'\"-]", " ", s)
    s = LEGAL_WORDS.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _same(a_norm, a_zip, b_norm, b_zip):
    if not a_norm or a_norm != b_norm:
        return False
    return not a_zip or not b_zip or a_zip.replace(" ", "") == b_zip.replace(" ", "")


def _org_clients(c, oid):
    return [dict(r) for r in c.execute(f"SELECT id, name, zip, city, street, contact, country, address FROM clients WHERE {pb_cl_sql(c, oid)} AND deleted_at IS NULL ORDER BY id")]


def _cname(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def fk_other_contact(c, a, dup, rows):
    """2.40.0 (#1380): True when duplicate row a names a contact person its client (existing: dup.id; in the file: the
    row dup.row and the rows already added to it) does not have yet."""
    n = _cname(a.get("contact"))
    if not n:
        return False
    if dup["kind"] == "existing":
        cl = c.execute("SELECT contact FROM clients WHERE id=?", (dup["id"],)).fetchone()
        return not fk_has_name(c, dup["id"], a["contact"]) and not (cl and _cname(cl["contact"]) == n)
    for x in rows:
        if x["row"] == dup["row"] or (x.get("dup") or {}).get("row") == dup["row"]:
            if _cname(x.get("contact")) == n:
                return False
    return True


# ---------------------------------------------------------------- preview of a spreadsheet
def _num(v):
    # 2.355.0 B (#2843): core/csvimport.amount_text (thousand separators only in groups of three; "1,500" unreadable, was 1.5)
    d = amount_text(v)
    if d is None or abs(d) > Decimal("1e9"):
        return None
    return float(round(d, 4))


# 2.80.0 (#1837): money amounts as people type them: German "2.436,53" / "1.500" (thousand dots), "2436,53", English
# "2436.53" / "2,436.53", with "€" / "EUR" / spaces. A dot followed by exactly three digit groups is a thousand
# separator ("1.500" = 1500); anything else that is not a plain number stays invalid (None).
def _amount(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            return None
    else:
        d = amount_text(v)  # 2.355.0 B (#2843): the shared reader (core/csvimport; "1,500" unreadable, was 1.5)
    return d if d is not None and d.is_finite() and abs(d) <= Decimal("1e9") else None


def _flag01(v):
    return 1 if str(v or "").strip().lower() in ("1", "x", "ja", "yes", "true", "wahr", "y", "j") else 0


SEP_RE = re.compile(r"^\s*[-=*#_]{2,}\s*(.*?)\s*[-=*#_]{2,}\s*$")


EQ_ID_COLS = ("id", "nr", "no", "number", "artikel", "artikelnr", "artikelnummer", "article", "articleno", "itemno", "sku", "inventarnr")


def eq_head(h):
    """2.45.1 (#1556): a header cell without spaces, underscores, hyphens, dots ("Device DE" -> "devicede")."""
    return re.sub(r"[\s_.\-]+", "", str(h or "").lower())


def _col(head, *names):
    for n in names:
        if n in head:
            return head.index(n)
    return None


# 2.47.0 (#1648): a duplicate of an existing row is completed ("fill"): only its EMPTY fields take the file's value, set
# values are never overwritten. Empty = '' / NULL; for the flags and the order also 0. The run keeps what it filled
# (detail {"filled": {area: {id: {field: value}}}}); the undo empties a field again while it still holds that value.
SR_FILL = {"services": ("name_en", "category", "sort", "daily_rate", "hourly_rate", "raw_fee", "producing", "role", "role_id"),
           "equipment": ("name_en", "category", "daily_rate"),
           "roles": ("name_en", "cost_day", "cost_hour"), "crew": ("name_en", "rate_day")}  # 2.47.0 (#1649)
SR_ZERO = ("raw_fee", "producing", "sort")  # 0 counts as empty
SR_ERR_RE = re.compile(r"^#(?:NV|N/A|REF!|VALUE!|DIV/0!|NAME\?|NUM!|NULL!|BEZUG!|WERT!|ZAHL!)$", re.I)  # Excel error cells = empty


def _sr_empty(f, v):
    return v is None or v == "" or (f in SR_ZERO and not v)


def sr_fill(kind, cur, new):
    """{field: the file's value} for every empty field of the existing row cur the file row new has a value for."""
    return {f: new[f] for f in SR_FILL[kind] if f in new and not _sr_empty(f, new[f]) and _sr_empty(f, cur.get(f))}


def sr_cell(v):
    """A cell as text; Excel error values (#NV, #REF! ...) are empty."""
    v = str(v if v is not None else "").strip()
    return "" if SR_ERR_RE.match(v) else v


def sr_table(book, *names):
    """_table, also for Excel's renamed copies of a table ("Services_2")."""
    t = _table(book, *names)
    if t is not None:
        return t
    for n in names:
        for k in sorted(book):
            if re.fullmatch(re.escape(n) + r"_\d{1,3}", k):
                return _table(book, k)
    return None


def sr_have(c, oid, kind, *cols):
    """{lower-case name: row} of the organisation's rows of kind (every name column in cols)."""
    have = {}
    for r in office_rows(c, oid, kind):
        for col in cols:
            v = (r.get(col) or "").strip().lower()
            if v:
                have.setdefault(v, r)
    return have


def sr_cat_orders(book):
    """2.47.0 (#1648): {lower-case category: order} from a table category / order of the file ({} without one)."""
    t = sr_table(book, "category", "categories", "kategorie", "kategorien")
    if not t:
        return {}
    head, rows = t
    ci, oi = _col(head, "category", "kategorie"), _col(head, "order", "sort", "reihenfolge")
    out = {}
    for row in rows:
        cat = sr_cell(row[ci]) if ci is not None and ci < len(row) else ""
        o = _num(sr_cell(row[oi])) if oi is not None and oi < len(row) else None
        if cat and o is not None:
            out.setdefault(cat.strip().title().lower(), o)
    return out


# 2.47.0 (#1649): the blocks Freelancer (-> master "roles", the purchase price) and Staff / Crew (-> master "crew"): ONE
# way for both, only the column map differs. Variants like "Kamera (Premium)" are roles of their own.
SR_BLOCKS = {"roles": {"tables": ("freelancer", "freelancers", "freelancer-rollen"),
                       "cols": {"name_de": ("jobtitle", "jobtitlede", "rolle", "role"), "name_en": ("jobtitleen",),
                                "cost_day": ("dailyrate", "tagessatz"), "cost_hour": ("hourlyrate", "stundensatz")}},
             "crew": {"tables": ("staff", "crew", "drehpersonal"),
                      "cols": {"name_de": ("jobtitlede", "jobtitle", "funktion"), "name_en": ("jobtitleen",),
                               "rate_day": ("dailyrate", "tagessatz"), "intext": ("intext",)}}}
SR_NUMS = ("cost_day", "cost_hour", "rate_day")


def sr_role_rows(c, oid, book, kind):
    """The preview rows of block kind (roles | crew) of the file, or None without the block."""
    spec = SR_BLOCKS[kind]
    t = sr_table(book, *spec["tables"])
    if t is None:
        return None
    at = fi_head_at(book, *spec["tables"])
    head, rows = t
    head = [eq_head(h) for h in head]
    ix = {f: _col(head, *n) for f, n in spec["cols"].items()}
    if ix["name_de"] is None:
        return []
    have = sr_have(c, oid, kind, "name_de", "name_en")
    out, names = [], set()
    for i, row in enumerate(rows):
        get = lambda f: sr_cell(row[ix[f]]) if ix[f] is not None and ix[f] < len(row) else ""  # noqa: E731
        nm = get("name_de")
        if not nm or SEP_RE.match(nm):
            continue
        e = {"row": i + at + 2, "name_de": nm[:200]}  # 2.363.2 (#3106): the row in Excel, also below title rows
        for f in spec["cols"]:
            if f in SR_NUMS:
                e[f] = _num(get(f))
            elif f == "intext":
                e[f] = "intern" if get(f).lower().startswith("int") else "extern"
            elif f != "name_de":
                e[f] = get(f)[:200]
        keys = {nm.lower(), (e.get("name_en") or "").lower()} - {""}
        cur = next((have[k] for k in keys if k in have), None)
        e["dup"] = bool(cur) or any(k in names for k in keys)
        e["fill"] = sr_fill(kind, cur, e) if cur else {}
        e["action"] = "fill" if e["fill"] else ("skip" if e["dup"] else "new")
        names |= keys
        out.append(e)
    return out


def sr_intext(v):
    """2.47.0 (#1649): intern / extern / shooting of a service from the file."""
    v = (v or "").lower()
    return "intern" if v.startswith("int") else ("shooting" if v.startswith(("shoot", "dreh")) else "extern")


# 2.146.0 E (#2456): the clients' address in separate columns (Company | Street | Postcode | City | Country) as most
# exports have it, beside the one-cell address; a CSV file is read like a sheet. The columns are found from the header
# (or the person assigns them in the preview: form field "map"); without street / postcode / city columns the one-cell way stays.
FI_ADDR_COLS = {
    "name": ("firma", "company", "companyname", "firmenname", "name", "kunde", "kundenname", "client", "customer", "organisation",
             "organization", "unternehmen", "name1"),
    "contact": ("ansprechpartner", "ansprechperson", "kontaktperson", "contactperson", "contact", "kontakt", "name2", "zhd"),
    "street": ("straße", "strasse", "str", "street", "streetaddress", "addressline1", "adresszeile1", "straßeundhausnummer",
               "strasseundhausnummer", "straßenr", "strassenr", "straßehausnummer", "strassehausnummer", "street1"),
    "house": ("hausnummer", "hausnr", "nr", "housenumber", "houseno"),
    "zip": ("plz", "postleitzahl", "zip", "zipcode", "postcode", "postalcode", "postal", "postleitzahlplz"),
    "city": ("ort", "stadt", "city", "town", "wohnort", "ortschaft", "gemeinde"),
    "country": ("land", "country", "staat", "countrycode", "ländercode", "laendercode"),
    "address": ("addresses", "address", "adresse", "adressen", "anschrift"),
    # 2.363.0 (#3103): the other client fields such exports have (also beside the one-cell address)
    "email": ("email", "mail", "emailadresse", "mailadresse"),
    "phone": ("telefon", "telefonnummer", "tel", "phone", "phonenumber", "telephone", "mobil", "mobile", "handy"),
    "customer_no": ("kundennummer", "kundennr", "kdnr", "knr", "debitor", "debitornummer", "customerno", "customernumber"),
    "vat_id": ("ustidnr", "ustid", "ustidnummer", "umsatzsteuerid", "vatid", "vatnumber", "vatno"),
}
FI_MAP_KEYS = tuple(FI_ADDR_COLS)
FI_CSV_NAMES = ("services", "leistungen", "equipment", "geräte", "technik", "freelancer", "staff", "crew")  # a CSV named so is that table
FI_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # an old Excel file (.xls, BIFF in an OLE container)
FI_NOT_CSV = (b"%PDF", b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"<?xml", b"{\\rtf")  # files that are surely no CSV


def fi_xls_read(raw):
    """2.185.0 B (#2598): {lower-case sheet name: rows} of an old Excel file (.xls, BIFF2-8) like fi_xlsx_read: cells as text,
    whole numbers without ".0", dates as their stored serial number (as the .xlsx reader gives them), booleans "1" / "0",
    error cells empty; trailing empty rows and columns cut. xlrd is imported here: without it the old hint stays."""
    try:
        import xlrd
    except ImportError:
        raise BadInput(tr("Old Excel files (.xls) cannot be read. Please save the file as .xlsx or CSV and choose it again.")) from None
    if len(raw) > FI_XLSX_MAX:
        raise BadInput(tr("The file is too large"))
    try:
        wb = xlrd.open_workbook(file_contents=raw, on_demand=True, ragged_rows=True, logfile=io.StringIO(), verbosity=0)
    except Exception as e:  # a third-party parser on an upload: every failure is a 400, never a 500
        if "encrypt" in str(e).lower():
            raise BadInput(tr("This .xls file is protected with a password. Please remove the password or save the file as .xlsx or CSV and choose it again.")) from None
        raise BadInput(tr("This .xls file cannot be read (damaged or an unknown format). Please save it as .xlsx or CSV and choose it again.")) from None
    try:
        if wb.nsheets > FI_PARTS_MAX:
            raise BadInput(tr("The file is too large"))
        out = {}
        for i in range(wb.nsheets):
            sh = wb.sheet_by_index(i)
            grid = []
            for r in range(min(sh.nrows, FI_ROWS_MAX + 50)):
                row = []
                for c in range(min(sh.row_len(r), FI_COLS_MAX + 1)):
                    t, v = sh.cell_type(r, c), sh.cell_value(r, c)
                    if t in (xlrd.XL_CELL_NUMBER, xlrd.XL_CELL_DATE):
                        v = str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else repr(float(v))
                    elif t == xlrd.XL_CELL_BOOLEAN:
                        v = "1" if v else "0"
                    elif t == xlrd.XL_CELL_TEXT:
                        v = str(v)
                    else:  # empty, blank, error
                        v = ""
                    row.append(v)
                while row and row[-1] == "":
                    row.pop()
                grid.append(row)
            while grid and not grid[-1]:
                grid.pop()
            width = max((len(x) for x in grid), default=0)
            out.setdefault((sh.name or "").strip().lower(), [x + [""] * (width - len(x)) for x in grid])
            wb.unload_sheet(i)
        return out
    except BadInput:
        raise
    except Exception:
        raise BadInput(tr("This .xls file cannot be read (damaged or an unknown format). Please save it as .xlsx or CSV and choose it again.")) from None
    finally:
        wb.release_resources()


FI_XLS_BIFF_OLD = (b"\x09\x00", b"\x09\x02", b"\x09\x04")  # 2.185.0 B (#2598): BOF record of a BIFF2-4 .xls (no OLE container)


def fi_book(raw, name=""):
    """2.146.0 E (#2456): {lower-case name: rows} of an upload: .xlsx (fi_xlsx_read) or CSV (one table, named after the
    file when that is a known table, else "contacts"). 2.185.0 B (#2598): an old .xls is read by fi_xls_read; a text file
    named .xls (some programs export CSV / tab text so) is read as CSV."""
    if raw.startswith(b"PK"):
        return fi_xlsx_read(raw)
    if raw.startswith(FI_XLS_MAGIC) or raw.startswith(FI_XLS_BIFF_OLD) or ((name or "").lower().endswith(".xls")
                                                                          and (b"\x00" in raw[:4096] or raw.lstrip()[:1] == b"<")):
        return fi_xls_read(raw)
    if (name or "").lower().endswith((".xlsx", ".xlsm")):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    utf16 = raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)  # 2.363.0 (#3103): Excel's "Unicode text"
    if utf16:
        pass
    elif b"\x00" in raw[:4096] or raw.startswith(FI_NOT_CSV) or (name or "").lower().endswith((".pdf", ".zip", ".png", ".jpg", ".jpeg", ".heic")):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx or CSV)"))
    try:
        text = raw.decode("utf-16", "replace") if utf16 else raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    _d, head, body_ = csv_table(text, max_rows=FI_ROWS_MAX)
    stem = re.sub(r"\.[^.]*$", "", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip().lower()
    return {stem if stem in FI_CSV_NAMES else "contacts": [head] + body_[:FI_ROWS_MAX]}


def fi_head_at(book, *names):
    """2.363.0 (#3103): the index of the header row of that table (title rows above it count for the row numbers)."""
    for n in names:
        for i, row in enumerate((book.get(n) or [])[:10]):
            if any(str(x).strip() for x in row):
                return i
    return 0


def fi_head_orig(book, *names):
    """The header row of that table as written in the file (for the column choice)."""
    for n in names:
        rows = book.get(n)
        if rows is None:
            continue
        for row in rows[:10]:
            if any(str(x).strip() for x in row):
                return [str(x).strip()[:80] for x in row]
        return []
    return []


def fi_addr_map(head, amap=None):
    """{field: column index} of the client columns: the person's choice (amap, validated) or found from the header."""
    n = len(head)
    if isinstance(amap, dict):
        out = {}
        for k in FI_MAP_KEYS:
            v = amap.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < n:
                out[k] = v
        return out
    h = [eq_head(x) for x in head]
    out, used = {}, set()
    for k in FI_MAP_KEYS:
        for nm in FI_ADDR_COLS[k]:
            if nm in h and h.index(nm) not in used:
                out[k] = h.index(nm)
                used.add(out[k])
                break
    return out


def fi_addr_columns(m):
    """True when the clients come from separate columns (street, postcode or city assigned)."""
    return any(k in m for k in ("street", "zip", "city"))


def fi_country(v):
    """A country cell -> (ISO code, recognised)."""
    v = _clean_line(v)
    if not v:
        return "", True
    if re.fullmatch(r"[A-Za-z]{2}", v):
        return v.upper(), True
    code = COUNTRIES.get(v.strip(" .").lower())
    return (code, True) if code else ("", False)


def fi_columns_client(row, m):
    """2.146.0 E (#2456): one client from separate columns -> the splitter's shape {name, contact, street, zip, city,
    country, address, flags}; an address column beside street-less columns counts as the street."""
    get = lambda k: _clean_line(str(row[m[k]])) if k in m and m[k] < len(row) else ""  # noqa: E731
    street = get("street") or (get("address") if "street" not in m else "")
    if get("house") and street and not street.endswith(get("house")):
        street = f"{street} {get('house')}"
    elif get("house") and not street:
        street = get("house")
    out = {"name": get("name"), "contact": get("contact")[:120], "street": street[:200], "zip": get("zip")[:20], "city": get("city")[:120],
           "country": "", "flags": []}
    if not out["name"] and "name" not in m and row:  # no company column: the first column that is no address part
        free = next((j for j in range(len(row)) if j not in m.values()), None)
        out["name"] = _clean_line(str(row[free])) if free is not None else ""
    flags = out["flags"]
    code, ok = fi_country(get("country"))
    if not ok:
        flags.append("country")
    if not code and re.fullmatch(r"\d{5}", out["zip"]):
        code = "DE"
    out["country"] = code
    if not out["zip"]:
        flags.append("no_zip")
    if not out["street"]:
        flags.append("no_street")
    elif POBOX_RE.match(out["street"]):
        flags.append("po_box")
    if code and code != "DE":
        flags.append("foreign")
    out["address"] = "\n".join(x for x in (out["name"], out["contact"], out["street"], " ".join(x for x in (out["zip"], out["city"]) if x),
                                            get("country")) if x)[:500]
    _shorten(out)
    out["flags"] = list(dict.fromkeys(flags))
    return out


def fi_client_extras(a, row, m):
    """2.363.0 (#3103): e-mail, phone, customer number, VAT ID of the client's row into a; what the import would refuse
    stays out with a flag (one bad cell must not stop the whole file)."""
    get = lambda k: _clean_line(str(row[m[k]])) if k in m and m[k] < len(row) else ""  # noqa: E731
    mail = get("email")
    if mail and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", mail):
        mail = ""
        a["flags"].append("bad_email")
    vat = get("vat_id").replace(" ", "").upper()
    if len(vat) > 20:
        vat = ""
        a["flags"].append("bad_vat")
    a.update(email=mail[:200], phone=get("phone")[:60], customer_no=get("customer_no")[:40], vat_id=vat)


def fi_unused_cols(orig, rows, used):
    """2.363.0 (#3103): the headers of the columns with content that nothing takes over (the preview names them)."""
    return [orig[j] or tr("Column {0}", j + 1) for j in range(len(orig))
            if j not in used and any(j < len(r) and str(r[j]).strip() for r in rows)][:30]


def fi_preview(c, oid, raw, name="", amap=None):
    book = fi_book(raw, name)  # 2.146.0 E (#2456): also CSV
    out = {"sheets": sorted(book), "clients": [], "roles": [], "crew": [], "services": [], "equipment": [], "other": {}}
    t = _table(book, "contacts", "kontakte", "kunden", "adressen")
    if t:
        head, rows = t
        ci = _col(head, "addresses", "address", "adresse", "adressen", "anschrift")
        if ci is None and head:
            ci = 0
        orig = fi_head_orig(book, "contacts", "kontakte", "kunden", "adressen")
        amap = fi_addr_map(orig, amap)  # 2.146.0 E (#2456): separate address columns
        cols = fi_addr_columns(amap)
        if isinstance(amap.get("address"), int) and not cols:
            ci = amap["address"]
        out["columns"] = {"head": orig[:60], "map": amap, "mode": "columns" if cols else "one"}
        at = fi_head_at(book, "contacts", "kontakte", "kunden", "adressen")
        used = set(amap.values()) | ({ci} if not cols and ci is not None else set())
        if cols and "name" not in amap:  # the first free column is the name (fi_columns_client)
            used.add(next((j for j in range(len(orig)) if j not in used), -1))
        out["columns"]["unused"] = fi_unused_cols(orig, rows, used)
        if at + 1 + len(rows) > FI_ROWS_MAX:
            out["columns"]["cut"] = FI_ROWS_MAX
        known = _org_clients(c, oid)
        kn = [(fi_norm(k["name"]), k["zip"] or "", k) for k in known]
        seen = []
        for i, row in enumerate(rows):
            if cols:
                if not any(str(x).strip() for x in row):
                    continue
                a = fi_columns_client(row, amap)
                if not a["name"] and not a["street"]:
                    continue
            else:
                txt = str(row[ci] if ci is not None and ci < len(row) else "").strip()
                if not txt:
                    continue
                a = fi_split_address(txt)
            fi_client_extras(a, row, amap)
            a["row"] = i + at + 2  # 2.363.0 (#3103): the row of the file, also below title rows
            n = fi_norm(a["name"])
            a["dup"] = None
            for nn, zz, k in kn:
                if _same(n, a["zip"], nn, zz):
                    a["dup"] = {"kind": "existing", "id": k["id"], "name": k["name"]}
                    break
            if not a["dup"]:
                for prev in seen:
                    if _same(n, a["zip"], prev[0], prev[1]):
                        a["dup"] = {"kind": "file", "row": prev[2], "name": prev[3]}
                        break
            seen.append((n, a["zip"], a["row"], a["name"]))
            a["action"] = "skip" if a["dup"] else "new"
            if a["dup"] and fk_other_contact(c, a, a["dup"], out["clients"]):
                a["action"] = "contact"  # 2.40.0 (#1380): same company + postcode, another contact person: add them to the client
            a["reasons"] = [tr(FI_REASONS[f]) for f in a["flags"]]
            out["clients"].append(a)
    t = sr_table(book, "services", "leistungen")
    if t:
        head, rows = t
        have = sr_have(c, oid, "services", "name_de")
        at = fi_head_at(book, "services", "leistungen")
        ix = {k: _col(head, *v) for k, v in {"de": ("servicede", "service", "leistung"), "en": ("serviceen",), "day": ("dailyrate", "tagessatz"),
                                              "hour": ("hourlyrate", "stundensatz"), "raw": ("rawfee",), "prod": ("producingfee", "producing"),
                                              "order": ("order", "sort"), "cat": ("category", "kategorie"), "role": ("freelancer", "role"),
                                              "ie": ("intext",)}.items()}
        cell = lambda row, k: sr_cell(row[ix[k]]) if ix[k] is not None and ix[k] < len(row) else ""  # noqa: E731
        # 2.47.0 (#1645): the raw data / producing columns are always read (the switches of the office are only defaults now)
        cat = ""
        names = set()
        orders, last = sr_cat_orders(book), 0
        for i, row in enumerate(rows):
            de = cell(row, "de")
            m = SEP_RE.match(de)
            if m:  # "---- VIDEO ----": the category of the rows below
                cat = m.group(1).strip().title()
                continue
            if not de:
                continue
            day, hour = _num(cell(row, "day")), _num(cell(row, "hour"))
            s = {"row": i + at + 2, "name_de": de[:200], "name_en": cell(row, "en")[:200], "category": (cell(row, "cat") or cat)[:80],
                 "daily_rate": day, "hourly_rate": hour, "unit": "hour" if hour is not None and day is None else "day",
                 "raw_fee": _flag01(cell(row, "raw")), "producing": _flag01(cell(row, "prod")),
                 "role": cell(row, "role")[:80], "intext": sr_intext(cell(row, "ie"))}  # 2.47.0 (#1649): also shooting
            if "künstlersozialkasse" in de.lower():  # 2.47.0 (#1649): a rate in percent of the external fees (0.05 -> 5 %)
                v = day if day is not None else hour
                s.update(unit="percent", hourly_rate=None, daily_rate=None if v is None else (round(v * 100, 4) if abs(v) < 1 else v), percent=True)
            # 2.47.0 (#1648): the column order is the order of the CATEGORY (a table category / order wins); inside a
            # category the rows keep the file's order -> sort = category order * 10000 + row
            o = orders.get(s["category"].lower())
            if o is None:
                o = _num(cell(row, "order"))
                o = last if o is None else o
                if s["category"]:
                    orders.setdefault(s["category"].lower(), o)
            last = o
            s["sort"] = float(o) * 10000 + i + 1
            key = de.lower()
            s["dup"] = key in have or key in names
            s["fill"] = sr_fill("services", have[key], s) if key in have else {}  # 2.47.0 (#1648)
            if key in have and s["role"] and not have[key].get("role_id"):  # 2.47.0 (#1649): the role (resolved at the import)
                s["fill"]["role_id"] = s["role"]
            s["action"] = "fill" if s["fill"] else ("skip" if s["dup"] else "new")
            names.add(key)
            out["services"].append(s)
    t = _table(book, "equipment", "geräte", "technik")
    if t:
        head, rows = t
        have = sr_have(c, oid, "equipment", "name", "name_en")  # 2.47.0 (#1648): name -> row (to fill)
        at = fi_head_at(book, "equipment", "geräte", "technik")
        # 2.45.1 (#1556): "Device DE" / "Device EN" (spaces, underscores, hyphens and case do not matter); DE before the plain names
        head = [eq_head(h) for h in head]
        ni = _col(head, "devicede", "gerätde", "geraetde", "namede", "device", "name", "gerät", "geraet")
        ei = _col(head, "deviceen", "geräten", "geraeten", "nameen")
        cti, di = _col(head, "category", "kategorie"), _col(head, "dailyrate", "tagessatz")
        ii, li = _col(head, *EQ_ID_COLS), _col(head, "language", "lang", "sprache")
        cell = lambda row, j: sr_cell(row[j]) if j is not None and j < len(row) else ""  # noqa: E731
        cat, names, by_id = "", set(), {}
        for i, row in enumerate(rows):
            nm = cell(row, ni)
            m = SEP_RE.match(nm)
            if m:
                cat = m.group(1).strip().title()
                continue
            if not nm:
                continue
            en = cell(row, ei)
            rid_, lang = cell(row, ii).lower(), cell(row, li).lower()[:2]
            if li is not None and lang == "en" and rid_ and rid_ in by_id and not by_id[rid_]["name_en"]:
                # the English row of a device listed before under the same id: only its second name (nothing guessed without both columns)
                by_id[rid_]["name_en"] = nm[:200]
                if nm.lower() in have or nm.lower() in names:  # 2.45.1 (#1556) review: the English name may already exist
                    by_id[rid_]["dup"], by_id[rid_]["action"] = True, "skip"
                    cur = have.get(nm.lower()) or have.get(by_id[rid_]["name"].lower())
                    by_id[rid_]["fill"] = sr_fill("equipment", cur, by_id[rid_]) if cur else {}  # 2.47.0 (#1648)
                    by_id[rid_]["action"] = "fill" if by_id[rid_]["fill"] else "skip"
                names.add(nm.lower())
                continue
            e = {"row": i + at + 2, "name": nm[:200], "name_en": en[:200], "category": (cell(row, cti) or cat)[:80],
                 "daily_rate": _num(sr_cell(row[di])) if di is not None and di < len(row) else None}
            e["dup"] = any(v in have or v in names for v in {nm.lower(), en.lower()} - {""})  # 2.45.1 (#1556): either name
            cur = have.get(nm.lower()) or have.get(en.lower())
            e["fill"] = sr_fill("equipment", cur, e) if cur else {}  # 2.47.0 (#1648)
            e["action"] = "fill" if e["fill"] else ("skip" if e["dup"] else "new")
            names.add(nm.lower())
            if en:
                names.add(en.lower())
            if rid_ and rid_ not in by_id:
                by_id[rid_] = e
            out["equipment"].append(e)
    for kind in ("roles", "crew"):  # 2.47.0 (#1649): imported now (were only counted in out["other"])
        out[kind] = sr_role_rows(c, oid, book, kind) or []
    known = {k for k, r in sr_have(c, oid, "roles", "name_de", "name_en").items() if not r.get("archived")}
    known |= {x["name_de"].lower() for x in out["roles"]}
    for s in out["services"]:  # a role the import cannot find is no fill
        if "role_id" in s.get("fill", {}) and s["role"].lower() not in known:
            del s["fill"]["role_id"]
            if not s["fill"]:
                s["action"] = "skip"
    return out


# ---------------------------------------------------------------- confirming an import
def _run_new(c, oid, uid, kind):
    return insert_id(c, "INSERT INTO office_import_runs(org_id, kind, created_by, created_at) VALUES(?,?,?,?)", (oid, kind, uid, iso(now_utc())))


# 2.363.2 (#3104): the imports of fixed costs, trips and leads are runs too: {kind: (table, what still counts as there)}.
FX_RUNS = {"fixed_costs": ("office_fixed_costs", ""), "trips": ("office_trips", ""), "leads": ("office_deals", " AND t.deleted_at IS NULL")}
FX_UNDO_LATE = N_("This import is older than 24 hours and can no longer be undone.")


def fx_run(c, oid, uid, kind, ids):
    """A run for the new rows `ids` of kind (no rows: no run). Their rows carry the run id, like the master data. No commit."""
    if not ids:
        return None
    rid = _run_new(c, oid, uid, kind)
    c.execute("UPDATE office_import_runs SET counts=? WHERE id=? AND org_id=?", (json.dumps({kind: len(ids)}), rid, oid))
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"UPDATE {FX_RUNS[kind][0]} SET import_run_id=? WHERE org_id=? AND id IN ({','.join('?' * len(part))})", [rid, oid] + part)
    return rid


def fx_settle(c, oid, uid, kind):
    """The runs of kind with nothing left (the toast's undo, every row deleted by hand) count as undone. No commit."""
    table, alive = FX_RUNS[kind]
    c.execute(f"""UPDATE office_import_runs r SET undone_at=?, undone_by=? WHERE org_id=? AND kind=? AND undone_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.org_id=r.org_id AND t.import_run_id=r.id{alive})""",
              (iso(now_utc()), uid, oid, kind))


def fx_undo(c, oid, uid, r):
    """Undoes a run of FX_RUNS within OLK_UNDO_HOURS, by the rules of the toast's undo (what changed since stays).
    -> as fi_undo."""
    if r["undone_at"]:
        raise Denied(409, tr("This import has already been undone"))
    try:
        at = parse_iso(r["created_at"])
    except (TypeError, ValueError):
        at = None
    if at is None or now_utc() - at > timedelta(hours=OLK_UNDO_HOURS):
        raise Denied(409, tr(FX_UNDO_LATE))
    kind = r["kind"]
    table, alive = FX_RUNS[kind]
    ids = [x[0] for x in c.execute(f"SELECT t.id FROM {table} t WHERE t.org_id=? AND t.import_run_id=?{alive} ORDER BY t.id", (oid, r["id"]))]
    if kind == "fixed_costs":
        from .fixedimport import fci_remove
        n = fci_remove(c, oid, ids, uid)  # 2.567.0 (#4707): who took it back (office trash)
    elif kind == "trips":
        from .vmaimport import vmi_remove
        n = vmi_remove(c, oid, ids, uid)["deleted"]  # 2.567.0 (#4707)
    else:
        from .leads import lead_bin
        n = lead_bin(c, oid, ids)
    c.execute("UPDATE office_import_runs SET undone_at=?, undone_by=? WHERE id=? AND org_id=?", (iso(now_utc()), uid, r["id"], oid))
    return {kind: n}, {"entries": len(ids) - n}, [], []


def _run_row(c, oid, rid):
    r = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


MERGE_FIELDS = ("contact", "street", "zip", "city", "country", "address", "email", "phone", "customer_no", "vat_id")


def _import_client(c, oid, uid, x, rid, ts, counts, merged, clean_client, made=None, pre=None):
    if not isinstance(x, dict):
        raise BadInput(tr("Invalid data"))
    made = {} if made is None else made  # row -> the client it became (new / merged), for "contact" rows of the same file
    act = x.get("action") or "new"
    if act == "skip":
        counts["skipped"] += 1
        return
    if act == "contact":  # 2.40.0 (#1380): add the row's contact person to an existing client / the client of an earlier row
        if x.get("merge_id") not in (None, ""):
            try:
                tid = int(x.get("merge_id"))
            except (TypeError, ValueError):
                raise BadInput(tr("The chosen client no longer exists")) from None
        else:
            tid = made.get(x.get("contact_row"))
            if not tid:
                raise BadInput(tr("The client of row {0} is not imported", x.get("contact_row") if isinstance(x.get("contact_row"), int) else "?"))
        if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (tid,)).fetchone():
            raise BadInput(tr("The chosen client no longer exists"))
        name = str(x.get("contact") or "").strip()
        if not name:
            raise BadInput(tr("Name missing"))
        if not fk_has_name(c, tid, name):
            fk_add(c, tid, pb_cl_org(c, oid), {"name": name[:120]}, run_id=rid)
            fk_sync(c, tid)
            counts["contacts"] = counts.get("contacts", 0) + 1
        else:
            counts["skipped"] += 1
        if isinstance(x.get("row"), int):
            made[x["row"]] = tid
        return
    f = {k: x.get(k) for k in ("name", "contact", "street", "zip", "city", "country", "address", "email", "phone", "customer_no", "vat_id") if x.get(k) is not None}
    if act == "merge":
        try:
            mid = int(x.get("merge_id"))
        except (TypeError, ValueError):
            raise BadInput(tr("The chosen client no longer exists")) from None
        cur = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (mid,)).fetchone()
        if not cur:
            raise BadInput(tr("The chosen client no longer exists"))
        f.pop("name", None)
        f = clean_client(c, uid, f)
        fill = {k: v for k, v in f.items() if k in MERGE_FIELDS and v and not (cur[k] or "").strip()}
        if fill:
            c.execute(f"UPDATE clients SET {', '.join(k + '=?' for k in fill)}, updated_at=? WHERE id=? AND {pb_cl_sql(c, oid)}", [*fill.values(), ts, mid])
            merged[str(mid)] = {**merged.get(str(mid), {}), **fill}
            if fill.get("contact") and not fk_has_name(c, mid, fill["contact"]):  # 2.40.0 (#1380): the filled contact = a contact person
                fk_add(c, mid, pb_cl_org(c, oid), {"name": fill["contact"]}, run_id=rid, default=True)
                fk_sync(c, mid)
        if isinstance(x.get("row"), int):
            made[x["row"]] = mid
        counts["merged"] += 1
        return
    if act != "new":
        raise BadInput(tr("Unknown choice for this row"))
    # 2.269.0 D (#3046): sent again (two tabs, a retry) = a client that is there by now is skipped like in the preview;
    # dup_ok = the person chose "new" for a row the preview found (pre = the clients before this run)
    if pre and x.get("dup_ok") not in (1, True, "1"):
        n = fi_norm(str(f.get("name") or ""))
        if any(_same(n, str(f.get("zip") or ""), nn, zz) for nn, zz in pre):
            counts["skipped"] += 1
            return
    f["org_id"] = pb_cl_org(c, oid)  # 2.47.3 (#1360): a personal office's clients are private clients
    f = clean_client(c, uid, f, new=True)
    f.update(org_id=pb_cl_org(c, oid), created_by=uid, created_at=ts, updated_at=ts, import_run_id=rid)
    cid = insert_id(c, f"INSERT INTO clients({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
    if f.get("contact"):  # 2.40.0 (#1380): the default contact person (removed with the client by the undo)
        fk_add(c, cid, pb_cl_org(c, oid), {"name": f["contact"]}, run_id=rid, default=True)
    if isinstance(x.get("row"), int):
        made[x["row"]] = cid
    counts["clients"] += 1


def fi_import(c, oid, uid, b):
    """Body {clients: [...], services: [...], equipment: [...]} (the preview's rows as corrected; action new | merge | skip,
    merge_id = the existing client to fill). -> (run id, counts). Everything in one transaction."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    lists = {k: b.get(k) or [] for k in FI_AREAS}
    if not all(isinstance(v, list) for v in lists.values()) or sum(len(v) for v in lists.values()) > 5 * FI_ROWS_MAX:
        raise BadInput(tr("Invalid data"))
    areas = bk_areas(b.get("areas"))  # 2.46.1 (#1557): only the areas switched on (absent: all); the others are not even checked
    lists = {k: v if k in areas else [] for k, v in lists.items()}
    pre = {r["id"]: r.get("sort") for r in office_rows(c, oid, "services")} if lists["services"] else {}  # 2.144.6 B (#2400 F1)
    rid = _run_new(c, oid, uid, "data")
    counts = {"clients": 0, "merged": 0, "contacts": 0, "services": 0, "equipment": 0, "skipped": 0, "services_filled": 0, "equipment_filled": 0,
              "roles": 0, "roles_filled": 0, "crew": 0, "crew_filled": 0}
    merged, filled = {}, {}
    made = {}
    ts = iso(now_utc())
    pre_cl = [(fi_norm(k["name"]), k["zip"] or "") for k in _org_clients(c, oid)] if lists["clients"] else []  # 2.269.0 D (#3046); own name: pre = the services' order
    for x in lists["clients"]:
        try:
            _import_client(c, oid, uid, x, rid, ts, counts, merged, clean_client, made, pre_cl)
        except BadInput as e:  # say which row: the preview can be long
            raise BadInput(tr("Row {0}: {1}", x.get("row") if isinstance(x, dict) and isinstance(x.get("row"), int) else "?", str(e))) from None
    # 2.47.0 (#1649): roles and crew first, so the column freelancer of a service finds its (new or existing) role
    for kind in ("roles", "crew"):
        sr_import_rows(c, oid, rid, kind, lists[kind], tuple(SR_BLOCKS[kind]["cols"]), counts, filled)
    roles = sr_have(c, oid, "roles", "name_de", "name_en")

    def role_of(vals):
        r = roles.get(str(vals.get("role") or "").strip().lower())
        return {**vals, "role_id": r["id"]} if r and not r.get("archived") else vals

    for kind, cols in (("services", ("name_de", "name_en", "category", "sort", "unit", "daily_rate", "hourly_rate", "raw_fee", "producing", "intext", "role")),
                       ("equipment", ("name", "name_en", "category", "daily_rate"))):  # 2.45.1 (#1556): name_en
        sr_import_rows(c, oid, rid, kind, lists[kind], cols, counts, filled, role_of if kind == "services" else None)
    if lists["services"]:  # 2.138.0 E (#2237): the file's order also for the services that existed before
        imr_renumber(c, oid, imr_file_order(lists["services"]))
        for v in (filled.get("services") or {}).values():  # the order is renumbered, never emptied again by the undo
            v.pop("sort", None)
    # 2.144.6 B (#2400 F1): {service id: [sort before the import, sort after]} so the undo puts the old order back
    order = {str(r["id"]): [pre[r["id"]], r.get("sort")] for r in (office_rows(c, oid, "services") if pre else [])
             if r["id"] in pre and r.get("sort") != pre[r["id"]]}
    c.execute("UPDATE office_import_runs SET counts=?, detail=? WHERE id=? AND org_id=?",
              (json.dumps(counts), json.dumps({"merged": merged, "filled": filled, "areas": list(areas), **({"order": order} if order else {})}), rid, oid))
    return rid, counts


SR_NAMES = {"services": ("name_de",), "equipment": ("name", "name_en"), "roles": ("name_de", "name_en"), "crew": ("name_de", "name_en")}


def sr_mark(oid, rid, f, v):
    """2.47.0 (#1648): what the run keeps of a filled value (compared at the undo); 2.47.0 (#1649): a purchase price only
    as a keyed hash (the run's detail is not encrypted)."""
    if f in ("cost_day", "cost_hour"):
        msg = f"{oid}:{rid}:{f}:{v!r}".encode()
        key = sr_mark_key()
        if key:  # 2.47.0 (#1649): keyed with the server secret, a day rate cannot be guessed back from the run's detail
            return "k:" + hmac.new(key, msg, hashlib.sha256).hexdigest()[:24]
        return "h:" + hashlib.sha256(msg).hexdigest()[:24]  # no server secret: nothing is encrypted at rest anyway
    return v


_SR_MARK_KEY = []


def sr_mark_key():
    """The key of sr_mark: derived from the server secret (KALMIDO_SECRET_KEY / secret file), None without one."""
    if not _SR_MARK_KEY:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        m = getattr(config, "SECRET_KEY", None)
        _SR_MARK_KEY.append(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-import-mark-v1").derive(m) if m else None)
    return _SR_MARK_KEY[0]


def sr_import_rows(c, oid, rid, kind, rows, cols, counts, filled, resolve=None):
    """2.47.0 (#1648): the rows of one master data area: new -> created with the run id, fill -> the empty fields of the
    existing row of that name filled (recomputed here, never taken from the client), skip -> nothing. resolve(values)
    may complete the values (the role of a service)."""
    have = sr_have(c, oid, kind, *SR_NAMES[kind])
    for x in rows:
        if not isinstance(x, dict):
            raise BadInput(tr("Invalid data"))
        act = x.get("action") or "new"
        if act == "skip":
            counts["skipped"] += 1
            continue
        vals = {k: x[k] for k in cols if k in x and x[k] is not None}
        if resolve:
            vals = resolve(vals)
        if act == "fill":
            names = [str(x.get(n) or "").strip().lower() for n in SR_NAMES[kind]]
            cur = next((have[n] for n in names if n and n in have), None)
            if not cur:
                raise BadInput(tr("Row {0}: {1}", x.get("row") if isinstance(x.get("row"), int) else "?", tr("Unknown choice for this row")))
            f = sr_fill(kind, cur, vals)
            if not f:
                counts["skipped"] += 1
                continue
            new = office_update(c, oid, kind, cur["id"], f)
            done = filled.setdefault(kind, {}).setdefault(str(cur["id"]), {})
            done.update({k: sr_mark(oid, cur["id"], k, new.get(k)) for k in f})
            for n in names:
                if n in have:
                    have[n] = new
            counts[kind + "_filled"] = counts.get(kind + "_filled", 0) + 1
            continue
        if act != "new":
            raise BadInput(tr("Row {0}: {1}", x.get("row") if isinstance(x.get("row"), int) else "?", tr("Unknown choice for this row")))
        # 2.269.0 D (#3046): sent again = a row of that name there by now is skipped (the preview's dup = "new" on purpose)
        nm = str(x.get(SR_NAMES[kind][0]) or "").strip().lower()
        if nm and not x.get("dup") and nm in have:
            counts["skipped"] += 1
            continue
        row = office_create(c, oid, kind, vals)
        c.execute(f"UPDATE {MD[kind]['table']} SET import_run_id=? WHERE id=? AND org_id=?", (rid, row["id"], oid))
        counts[kind] += 1


# 2.138.0 E (#2237): the order of the services. An import takes the file's order also for the services that existed
# before (only sort is overwritten, every other field is still only filled), then every service is numbered 1..n without
# gaps in the order the list shows (grouped by category, the categories in their first appearance). "Renumber" in the
# services does the same with the current order.
def imr_file_order(rows):
    """{lower-case German name: the file's sort} of the import's service rows (every action, also skip)."""
    out = {}
    for x in rows:
        if isinstance(x, dict) and isinstance(x.get("sort"), (int, float)) and not isinstance(x.get("sort"), bool):
            nm = str(x.get("name_de") or "").strip().lower()
            if nm and abs(x["sort"]) < 1e12:
                out.setdefault(nm, float(x["sort"]))
    return out


def imr_renumber(c, oid, first=None):
    """Numbers the services of office area oid 1..n; first = {lower-case name: sort}: these come first in that order (the
    file of an import), the others after them in their current order. -> the number of services whose order changed."""
    rows = office_rows(c, oid, "services")  # already in the list's order (sort, category, name, id)
    first = first or {}
    pos = {r["id"]: i for i, r in enumerate(rows)}
    key = lambda r: (0, first[(r.get("name_de") or "").strip().lower()], pos[r["id"]]) if (r.get("name_de") or "").strip().lower() in first else (1, 0, pos[r["id"]])  # noqa: E731
    groups = {}
    for r in sorted(rows, key=key):
        groups.setdefault(r.get("category") or "", []).append(r)
    n, changed, ts = 0, 0, iso(now_utc())
    for g in groups.values():
        for r in g:
            n += 1
            if float(r.get("sort") or 0) != n:
                c.execute("UPDATE office_services SET sort=?, updated_at=? WHERE id=? AND org_id=?", (n, ts, r["id"], oid))
                changed += 1
    return changed


# 2.46.1 (#1557): the areas of a data import, each imported and undone on its own. The run keeps per area when it was
# undone in its detail JSON ({"undone": {"equipment": "<iso>"}}, no new column); undone_at = the whole run (every area
# with entries undone, or the whole undo).
FI_AREAS = ("clients", "roles", "crew", "services", "equipment")  # 2.47.0 (#1649): roles, crew


def bk_areas(v, empty_ok=True):
    if v is None:
        return FI_AREAS
    if not isinstance(v, list) or any(x not in FI_AREAS for x in v) or (not v and not empty_ok):
        raise BadInput(tr("Invalid value: {0}", "areas"))
    return tuple(a for a in FI_AREAS if a in v)


def bk_area_counts(counts):
    """{area: number of entries the run made / changed in it} (only areas with entries)."""
    n = {"clients": sum(int(counts.get(k) or 0) for k in ("clients", "merged", "contacts"))}
    for k in FI_AREAS[1:]:  # 2.47.0 (#1648): new + filled rows
        n[k] = int(counts.get(k) or 0) + int(counts.get(k + "_filled") or 0)
    return {k: v for k, v in n.items() if v}


def bk_detail(r):
    try:
        d = json.loads(r["detail"] or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------- undo
def _client_used(c, oid, cid, rid):
    """2.272.0 D (#3029, #3027): anything points at client cid (the foreign-key catalogue, every workspace, + projects) but its
    own contact persons and the archive entries of run rid -> the undo keeps it."""
    own = {r[0] for r in c.execute("SELECT id FROM office_archive WHERE client_id=? AND org_id=? AND run_id=?", (cid, oid, rid))}
    return bool(cl_refs(c, cid, skip=("office_client_contacts",), skip_ids={"office_archive": own} if own else None))


OLK_CL_LATE = N_("Imported clients can only be taken out again within 24 hours of their import.")


def fi_client_undo_check(c, oid, r):
    """2.272.0 D (#3027): the clients of run r (still there, not in the trash) go back only within OLK_UNDO_HOURS of the
    import, like the old invoices (409 otherwise, nothing of the run is removed)."""
    if not c.execute(f"SELECT 1 FROM clients WHERE {pb_cl_sql(c, oid)} AND import_run_id=? AND deleted_at IS NULL LIMIT 1", (r["id"],)).fetchone():
        return
    try:
        at = parse_iso(r["created_at"])
    except (TypeError, ValueError):
        at = None
    if at is None or now_utc() - at > timedelta(hours=OLK_UNDO_HOURS):
        raise Denied(409, tr(OLK_CL_LATE))


OLK_UNDO_HOURS = 24
OLK_UNDO_LATE = N_("Old invoices can only be taken out again within 24 hours of their import.")
OLK_UNDO_TOUCHED = N_("Old invoices of this import were edited or marked as paid since: the import can no longer be undone.")


def olk_undo_check(c, oid, r):
    """2.152.0 C (#2168): the undo of an import that brought old invoices (office_archive) removes records that may already
    be part of the books: only within OLK_UNDO_HOURS of the import and while none of them was edited or marked paid (every
    change of an entry lands in office_archive_log). Else 409 with the reason and nothing of the run is removed."""
    if not c.execute("SELECT 1 FROM office_archive WHERE org_id=? AND run_id=? LIMIT 1", (oid, r["id"])).fetchone():
        return
    try:
        at = parse_iso(r["created_at"])
    except (TypeError, ValueError):
        at = None
    if at is None or now_utc() - at > timedelta(hours=OLK_UNDO_HOURS):
        raise Denied(409, tr(OLK_UNDO_LATE))
    if c.execute("""SELECT 1 FROM office_archive_log l JOIN office_archive a ON a.id=l.archive_id
                    WHERE a.org_id=? AND a.run_id=? LIMIT 1""", (oid, r["id"])).fetchone():
        raise Denied(409, tr(OLK_UNDO_TOUCHED))


def fi_undo(c, oid, uid, rid, kinds=None):
    """Undoes run rid: removes its records nothing builds on; -> {removed: {...}, kept: {...}}. 409 when already undone.
    2.46.1 (#1557): kinds = only these areas of a data import (clients | services | equipment); the whole undo later
    takes the areas that are left."""
    write_lock(c, f"office_import_{int(oid)}")
    r = _run_row(c, oid, rid)
    if r["kind"] == "datev":  # 2.148.0 D (#2458): a DATEV import run (office/datevimp.py) has its own undo
        from .datevimp import di_undo
        return di_undo(c, oid, uid, r)
    if r["kind"] == "datev_archive":  # 2.414.0 (#3502): a run of the booking archive (office/bookarch.py)
        from .bookarch import ba_undo
        return ba_undo(c, oid, uid, r)
    if r["kind"] in FX_RUNS:
        return fx_undo(c, oid, uid, r)
    if r["undone_at"]:
        raise Denied(409, tr("This import has already been undone"))
    detail = bk_detail(r)
    undone = detail.get("undone") if isinstance(detail.get("undone"), dict) else {}
    if kinds is not None:
        kinds = bk_areas(kinds, empty_ok=False)
        if r["kind"] != "data":
            raise BadInput(tr("Invalid value: {0}", "kinds"))
        if any(k in undone for k in kinds):
            raise Denied(409, tr("This part of the import has already been undone"))
    todo = [k for k in (kinds or FI_AREAS) if k not in undone]
    if kinds is None:
        olk_undo_check(c, oid, r)  # 2.152.0 C (#2168): old invoices of the run are records: 24 h and untouched only
    if "clients" in todo:
        fi_client_undo_check(c, oid, r)  # 2.272.0 D (#3027): clients 24 h too
    removed = {"clients": 0, "services": 0, "equipment": 0, "archive": 0, "merged": 0, "contacts": 0, "filled": 0, "roles": 0, "crew": 0}
    kept = {"clients": 0, "services": 0, "equipment": 0, "roles": 0, "crew": 0}
    kept_ids = set()
    archived = []  # 2.138.0 E (#2241): the used services / devices the undo archived (name + where they are used)
    for row in (c.execute(f"SELECT id FROM clients WHERE {pb_cl_sql(c, oid)} AND import_run_id=? AND deleted_at IS NULL", (rid,)).fetchall()
                if "clients" in todo else []):
        if _client_used(c, oid, row["id"], rid):
            kept["clients"] += 1
            kept_ids.add(row["id"])
            continue
        cl_trash(c, row["id"])  # 2.272.0 D (#3027): into the clients' trash (restorable until the trash period ends)
        removed["clients"] += 1
    s = office_settings(c, oid)
    sr_unfill(c, oid, detail, todo, removed)  # 2.47.0 (#1648): first, so a service lets go of the run's role
    for kind in ("services", "equipment", "roles", "crew"):  # 2.47.0 (#1649): roles after the services that point to them
        if kind not in todo:
            continue
        table = MD[kind]["table"]
        extra = " AND kind=?" if MD[kind].get("kind") else ""
        for row in c.execute(f"SELECT id FROM {table} WHERE org_id=? AND import_run_id=?{extra}", (oid, rid, *((MD[kind]["kind"],) if extra else ()))).fetchall():
            if kind == "services" and s.get("producing_service_id") == row["id"]:  # the calculation rules' producing service stays active
                kept[kind] += 1
                continue
            if office_in_use(c, kind, row["id"], oid):
                if kind in IMR_KINDS:  # 2.138.0 E (#2241): a used service / device is archived (its documents keep their copy)
                    archived.append(imr_archive(c, oid, kind, row["id"]))
                else:
                    kept[kind] += 1
                continue
            c.execute(f"DELETE FROM {table} WHERE id=? AND org_id=?", (row["id"], oid))
            removed[kind] += 1
    # 2.144.6 B (#2400 F1): the services the import renumbered get their old order back while nobody reordered them since
    order = detail.get("order") if "services" in todo and isinstance(detail.get("order"), dict) else {}
    for sid, (old, new) in ((k, v) for k, v in order.items() if str(k).isdigit() and isinstance(v, list) and len(v) == 2):
        c.execute("UPDATE office_services SET sort=?, updated_at=? WHERE id=? AND org_id=? AND sort=?", (old, iso(now_utc()), int(sid), oid, new))
    merged = (detail.get("merged") or {}) if "clients" in todo else {}
    for cid, fill in merged.items():  # merged clients: empty the filled fields again while they still hold the imported value
        cur = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (int(cid),)).fetchone()
        if not cur:
            continue
        back = [k for k, v in fill.items() if k in MERGE_FIELDS and (cur[k] or "") == v]
        if back:
            c.execute(f"UPDATE clients SET {', '.join(k + '=?' for k in back)}, updated_at=? WHERE id=? AND {pb_cl_sql(c, oid)}",
                      [""] * len(back) + [iso(now_utc()), int(cid)])
            removed["merged"] += 1
    # 2.40.0 (#1380): the contact persons the run added to other clients (a kept client of the run keeps its own)
    touched = set()
    kw = f"client_id IN (SELECT id FROM clients WHERE {pb_cl_sql(c, oid)})"  # 2.47.3 (#1360): also a personal office's (org_id NULL)
    # 2.272.0 F (#3027): the contact persons of a client that just went into the trash stay with it (restore brings them back)
    for row in (c.execute(f"SELECT id, client_id FROM office_client_contacts WHERE {kw} AND import_run_id=? "
                          "AND client_id IN (SELECT id FROM clients WHERE deleted_at IS NULL)", (rid,)).fetchall()
                if "clients" in todo else []):
        if row["client_id"] in kept_ids:
            continue
        c.execute(f"DELETE FROM office_client_contacts WHERE id=? AND {kw}", (row["id"],))
        touched.add(row["client_id"])
        removed["contacts"] += 1
    for cid in touched:
        fk_sync(c, cid)
    files = []
    for row in (c.execute("SELECT id, file FROM office_archive WHERE org_id=? AND run_id=?", (oid, rid)).fetchall() if kinds is None else []):
        files.append(row["file"])
        c.execute("DELETE FROM office_archive WHERE id=? AND org_id=?", (row["id"], oid))
        removed["archive"] += 1
    ts = iso(now_utc())
    if r["kind"] == "data":
        undone.update({k: ts for k in todo})
        detail["undone"] = undone
        c.execute("UPDATE office_import_runs SET detail=? WHERE id=? AND org_id=?", (json.dumps(detail), rid, oid))
    try:
        counts = json.loads(r["counts"] or "{}")
    except ValueError:
        counts = {}
    areas = bk_area_counts(counts if isinstance(counts, dict) else {}) or FI_AREAS  # 2.58.0 (#1557): a run without entries: every area
    if kinds is None or all(k in undone for k in areas):
        c.execute("UPDATE office_import_runs SET undone_at=?, undone_by=? WHERE id=? AND org_id=?", (ts, uid, rid, oid))
    return removed, kept, files, archived


# 2.138.0 E (#2241): undoing an import archives the services and devices of the run that documents, contracts or sets
# use (before: they stayed active). The service the calculation rules name as the producing one stays active. The answer
# names each archived entry and where it is used; "restore" is the normal edit (archived 0). Runs undone before this
# release: "Archive leftover entries" archives what is still active of the run's undone areas (nothing is deleted).
IMR_KINDS = ("services", "equipment")


def imr_used(c, oid, kind, rid, limit=3):
    """Where row rid of kind is used: up to limit labels (document number / title, contract, set) of organisation oid."""
    out = []
    if kind == "services":
        for d in c.execute("SELECT DISTINCT d.id, d.number, d.project_title FROM office_doc_items i JOIN office_docs d ON d.id=i.doc_id "
                           "WHERE i.service_id=? AND d.org_id=? ORDER BY d.id DESC LIMIT ?", (rid, oid, limit)):
            out.append(" · ".join(x for x in (d["number"], d["project_title"]) if x) or tr("Draft"))
        if len(out) < limit:
            out += [x.get("name") or "" for x in office_rows(c, oid, "contracts") if str(rid) in (x.get("rates") or {})][:limit - len(out)]
    elif kind == "equipment":
        for x in c.execute("SELECT name FROM office_sets WHERE org_id=? AND (items ILIKE ? OR items ILIKE ?) ORDER BY id LIMIT ?",
                           (oid, f'%"equipment_id": {int(rid)},%', f'%"equipment_id": {int(rid)}}}%', limit)):
            out.append(x["name"])
    return out


def imr_archive(c, oid, kind, rid):
    """Archives row rid of kind (organisation oid) -> {kind, id, name, used: [labels]}."""
    c.execute(f"UPDATE {MD[kind]['table']} SET archived=1, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), rid, oid))
    r = c.execute(f"SELECT {MD[kind]['label']} AS name FROM {MD[kind]['table']} WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    return {"kind": kind, "id": rid, "name": r["name"] if r else "", "used": imr_used(c, oid, kind, rid)}


def imr_leftover_ids(c, oid, r):
    """[(kind, id)] of run r: its still active services / devices of the areas already undone (not the producing service)."""
    if r["kind"] != "data":
        return []
    undone = bk_detail(r).get("undone")
    undone = undone if isinstance(undone, dict) else {}
    prod = office_settings(c, oid).get("producing_service_id")
    kept = bk_detail(r).get("restored")  # 2.144.6 B (#2400 F4): entries restored on purpose stay active
    kept = kept if isinstance(kept, dict) else {}
    out = []
    for kind in IMR_KINDS:
        if not (r["undone_at"] or kind in undone):
            continue
        for x in c.execute(f"SELECT id FROM {MD[kind]['table']} WHERE org_id=? AND import_run_id=? AND archived=0 ORDER BY id", (oid, r["id"])):
            if not (kind == "services" and x["id"] == prod) and x["id"] not in (kept.get(kind) or []):
                out.append((kind, x["id"]))
    return out


def imr_restored(c, oid, kind, old, new):
    """2.144.6 B (#2400 F4): an archived service / device of an import restored by hand (archived 1 -> 0) is noted in its
    run's detail ({"restored": {kind: [ids]}}, no new column); "Archive leftover entries" leaves it alone."""
    if kind not in IMR_KINDS or not old.get("import_run_id") or not old.get("archived") or new.get("archived"):
        return
    write_lock(c, f"office_import_{int(oid)}")
    r = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=?", (old["import_run_id"], oid)).fetchone()
    if not r:
        return
    d = bk_detail(r)
    kept = d.get("restored") if isinstance(d.get("restored"), dict) else {}
    if old["id"] not in kept.setdefault(kind, []):
        kept[kind].append(old["id"])
        d["restored"] = kept
        c.execute("UPDATE office_import_runs SET detail=? WHERE id=? AND org_id=?", (json.dumps(d), r["id"], oid))


def imr_tidy(c, oid, rid):
    """Archives the leftover entries of undone run rid -> [{kind, id, name, used}]. 409 when the run was not undone."""
    write_lock(c, f"office_import_{int(oid)}")
    r = _run_row(c, oid, rid)
    und = bk_detail(r).get("undone")
    if r["kind"] != "data" or not (r["undone_at"] or (isinstance(und, dict) and any(k in und for k in IMR_KINDS))):
        raise Denied(409, tr("This import has not been undone"))
    return [imr_archive(c, oid, kind, i) for kind, i in imr_leftover_ids(c, oid, r)]


def sr_unfill(c, oid, detail, todo, removed):
    """2.47.0 (#1648): the fields a run filled (areas in todo) emptied again while they still hold the imported value."""
    filled = detail.get("filled") if isinstance(detail.get("filled"), dict) else {}
    for kind in todo:
        rows = filled.get(kind)
        if kind not in SR_FILL or not isinstance(rows, dict):
            continue
        for rid_, fields in rows.items():
            row = sr_row(c, oid, kind, rid_)
            if row is None or not isinstance(fields, dict):  # deleted since (or another organisation's id: 404 -> None)
                continue
            back = {f: sr_blank(f) for f, v in fields.items() if f in SR_FILL[kind] and sr_mark(oid, row["id"], f, row.get(f)) == v}
            if back:
                office_update(c, oid, kind, row["id"], back)
                removed["filled"] += 1


def sr_blank(f):
    """The empty value of a fillable field."""
    return 0 if f in SR_ZERO else (None if f in ("daily_rate", "hourly_rate", "role_id", "cost_day", "cost_hour", "rate_day") else "")


def sr_row(c, oid, kind, rid):
    try:
        return office_row(c, oid, kind, rid)
    except Denied:
        return None


def _unlink_files(oid, files):
    from .bookarch import ba_path  # 2.414.0 (#3502): the files of an undone booking archive run
    for f in files:
        p = fi_archive_path(oid, f) or ba_path(oid, f)
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------- archive: file names, storage, numbers
DATE_PATTERNS = ((r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy"), (r"(\d{1,2})\.(\d{1,2})\.(\d{2})", "dmy2"),
                 (r"(\d{1,2})-(\d{1,2})-(\d{4})", "dmy"), (r"(\d{1,2})-(\d{1,2})-(\d{2})", "dmy2"), (r"(20\d{2})(\d{2})(\d{2})", "ymd"))


def fi_six_digits(s):
    """2.363.0 (#3103): the readings of six digits as a date, German first: [DDMMYY, YYMMDD], without impossible and future days."""
    if not re.fullmatch(r"\d{6}", s):
        return []
    a, b_, c_ = int(s[:2]), int(s[2:4]), int(s[4:])
    out = []
    for y, mo, d in ((2000 + c_, b_, a), (2000 + a, b_, c_)):
        try:
            x = date(y, mo, d)
        except ValueError:
            continue
        if x <= local_now().date() and x.isoformat() not in out:
            out.append(x.isoformat())
    return out


def fi_date_open(s):
    """2.363.0 (#3103): True when a date in a file name can be read two ways: it is proposed, not "sure"."""
    return len(fi_six_digits((s or "").strip())) > 1


def fi_parse_date(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{6}", s):
        return next(iter(fi_six_digits(s)), "")
    for pat, kind in DATE_PATTERNS:
        m = re.fullmatch(pat, s)
        if not m:
            continue
        a, b_, c_ = (int(x) for x in m.groups())
        y, mo, d = {"ymd": (a, b_, c_), "dmy": (c_, b_, a), "dmy2": (2000 + c_, b_, a)}[kind]
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return ""


def fi_parse_filename(name, clients=()):
    """The key data an old document's file name suggests: {kind, number, project_no, project, client_name, client_id, date,
    sure}. clients: [(id, name)] of the organisation for the client proposal."""
    base = os.path.basename((name or "").replace("\\", "/"))
    stem = re.sub(r"\.pdf$", "", base, flags=re.I).strip()
    out = {"file_name": base[:255], "kind": "", "number": stem[:120], "project_no": "", "project": "", "client_name": "", "client_id": None, "date": "", "sure": False}
    toks = [t for t in re.split(r"_", stem)]
    m = re.fullmatch(r"(?P<proj>[^_]+)_(?P<client>.+?)_KV(?P<lfd>\d+)_(?P<date>[^_]+)(?:_(?P<ini>[^_]+))?", stem, re.I)
    if m:
        out.update(kind="offer", client_name=m.group("client").replace("_", " "), date=fi_parse_date(m.group("date")))
        if m.group("proj").isdigit():
            out["project_no"] = m.group("proj")
        else:
            out["project"] = m.group("proj")
        out["sure"] = bool(out["date"]) and not fi_date_open(m.group("date"))
    else:
        # 2.533.0 (#4499): one underscore before the date is enough ("657_Client_2026-03-11_R": no title; was: two
        # underscores required, the name stayed unrecognised) -- when the date really is one
        m = re.fullmatch(r"(?P<proj>[^_]+)_(?P<client>[^_]+)(?:_(?P<title>.*?))?_+(?P<date>[^_]+)_(?:R|RE|Rechnung)", stem, re.I)
        if m and not fi_parse_date(m.group("date")):
            m = None
        if m:
            out.update(kind="invoice", project_no=m.group("proj"), client_name=m.group("client"), project=(m.group("title") or "").replace("_", " ").strip(),
                       date=fi_parse_date(m.group("date")))
            out["sure"] = bool(out["date"]) and not fi_date_open(m.group("date"))
        else:  # a free form: the first number is the project, a date anywhere, R / KV mark the kind
            if toks and toks[0].isdigit():
                out["project_no"] = toks[0]
                if len(toks) > 2:
                    out["client_name"] = toks[1]
            for t in toks:
                d = fi_parse_date(t)
                if d:
                    out["date"] = d
                    break
            if toks and toks[-1].upper() in ("R", "RE"):
                out["kind"] = "invoice"
            elif re.search(r"(^|_)KV\d*(_|$)", stem, re.I):
                out["kind"] = "offer"
    if not out["kind"]:
        out["kind"] = "invoice"
    out["client_id"] = ofb_client_match(out["client_name"], clients)
    return out


# 2.621.0 (#4600): file name templates of the archive import -- fixed building blocks + one separator, never a pattern of
# the person (no regex from outside, so no catastrophic backtracking). "standard" = fi_parse_filename above, unchanged.
# The choice is kept per office area in office_settings.data["legacy_fn_template"] ({name, custom: {fields, sep}}).
FNT_FIELDS = ("kind", "number", "project_no", "project", "client", "date", "skip")
FNT_SEPS = ("_", "-", " ", ".")
FNT_CUSTOM_MAX = 6  # building blocks of an own template
FNT_TEMPLATES = {"standard": None,
                 "date_number_client": {"fields": ("date", "number", "client"), "sep": "_"},
                 "number_client_date": {"fields": ("number", "client", "date"), "sep": "_"},
                 "client_number": {"fields": ("client", "number"), "sep": "_"},
                 "custom": None}  # built from FNT_FIELDS + FNT_SEPS (fnt_clean)
# the word of a kind block / a marker anywhere in the name -> the kind (lower case; de, en, fr, es, it)
FNT_KIND_WORDS = {"r": "invoice", "re": "invoice", "rg": "invoice", "rechnung": "invoice", "invoice": "invoice", "inv": "invoice",
                  "facture": "invoice", "factura": "invoice", "fattura": "invoice",
                  "kv": "offer", "an": "offer", "ang": "offer", "angebot": "offer", "offer": "offer", "quote": "offer", "quotation": "offer",
                  "devis": "offer", "presupuesto": "offer", "preventivo": "offer"}
FNT_DATE_RE = r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}\.\d{2,4}|\d{1,2}-\d{1,2}-\d{2,4}|\d{8}|\d{6}"


def fnt_custom_clean(v):
    """{fields: [block, ...], sep} of an own template, checked -> the clean dict; BadInput for anything else."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "fields"))
    f, sep = v.get("fields"), v.get("sep", "_")
    if not isinstance(f, list) or not 1 <= len(f) <= FNT_CUSTOM_MAX or not all(isinstance(x, str) and x in FNT_FIELDS for x in f):
        raise BadInput(tr("Invalid value: {0}", "fields"))
    real = [x for x in f if x != "skip"]
    if not real or len(set(real)) != len(real):
        raise BadInput(tr("Own file name template: each part only once"))
    if sep not in FNT_SEPS:
        raise BadInput(tr("Invalid value: {0}", "sep"))
    return {"fields": list(f), "sep": sep}


def fnt_clean(b, cur=None):
    """The template a request names ({template: name, fields?, sep?}) -> {name, custom}; an unknown name or a broken own
    template is BadInput (400). cur: the kept choice (its own template stays when another one is chosen)."""
    name = b.get("template")
    if not isinstance(name, str) or name not in FNT_TEMPLATES:
        raise BadInput(tr("Unknown file name template"))
    custom = (cur or {}).get("custom")
    if name == "custom":
        custom = fnt_custom_clean({"fields": b.get("fields"), "sep": b.get("sep", "_")})
    return {"name": name, "custom": custom if isinstance(custom, dict) else None}


def fnt_stored(s):
    """The kept choice of the office settings s -> {name, custom} (anything broken or unknown = the standard)."""
    v = s.get("legacy_fn_template") if isinstance(s.get("legacy_fn_template"), dict) else {}
    name = v.get("name") if v.get("name") in FNT_TEMPLATES else "standard"
    try:
        custom = fnt_custom_clean(v["custom"]) if v.get("custom") else None
    except BadInput:
        custom = None
    if name == "custom" and not custom:
        name = "standard"
    return {"name": name, "custom": custom}


def fnt_spec(t):
    """{name, custom} -> (fields, sep) of the template, or None for the standard."""
    if t["name"] == "custom":
        return tuple(t["custom"]["fields"]), t["custom"]["sep"]
    x = FNT_TEMPLATES.get(t["name"])
    return (tuple(x["fields"]), x["sep"]) if x else None


def fnt_regex(fields, sep):
    """The pattern of a template, built only from the fixed blocks: every block one piece without the separator, a date one
    of the known date forms, the client (else the project) may hold the separator -- only ONE such open block."""
    s = re.escape(sep)
    wide = "client" if "client" in fields else ("project" if "project" in fields else None)
    parts = []
    for f in fields:
        if f == "date":
            parts.append(f"(?P<date>{FNT_DATE_RE})")
        elif f == "skip":
            parts.append(f"[^{s}]+")
        elif f == wide:
            parts.append(f"(?P<{f}>.+?)")
        else:
            parts.append(f"(?P<{f}>[^{s}]+)")
    return re.compile(s.join(parts), re.I)


def fnt_parse(name, clients=(), t=None):
    """The key data a file name suggests under template t ({name, custom}; None = the standard): the same keys as
    fi_parse_filename. A name that does not fit the template gets the standard's reading, never "sure"."""
    spec = fnt_spec(t) if t else None
    if not spec:
        return fi_parse_filename(name, clients)
    fields, sep = spec
    base = os.path.basename((name or "").replace("\\", "/"))
    stem = re.sub(r"\.pdf$", "", base, flags=re.I).strip()
    m = fnt_regex(fields, sep).fullmatch(stem[:300])
    g = m.groupdict() if m else {}
    raw_date = g.get("date") or ""
    d = fi_parse_date(raw_date)
    kind = FNT_KIND_WORDS.get((g.get("kind") or "").lower(), "") if "kind" in fields else ""
    if not m or ("date" in fields and not d) or ("kind" in fields and not kind):
        out = fi_parse_filename(name, clients)
        out["sure"] = False
        return out
    if not kind:  # no kind block: the number's prefix (KV12, RE-104), a marker word outside client / project (the last one counts), else an invoice
        pre = re.match(r"([^\W\d_]+)[-.]?\d", g.get("number") or "")
        kind = FNT_KIND_WORDS.get(pre.group(1).lower(), "") if pre else ""
        rest = stem[:300]
        for f in sorted((f for f in ("client", "project") if g.get(f)), key=m.start, reverse=True):
            rest = rest[:m.start(f)] + " " + rest[m.end(f):]
        for tok in re.split(r"[_\-. ]+", rest):
            kind = FNT_KIND_WORDS.get(tok.lower(), kind)
    words = lambda v: re.sub(r"\s+", " ", (v or "").replace(sep, " ")).strip()  # noqa: E731
    out = {"file_name": base[:255], "kind": kind or "invoice", "number": (g.get("number") or stem)[:120], "project_no": (g.get("project_no") or "")[:120],
           "project": words(g.get("project")), "client_name": words(g.get("client")), "client_id": None, "date": d, "sure": False}
    # 2.621.0 (#4600) review: "sure" only with a kind really read (block, number prefix or marker word), never the invoice fallback
    out["sure"] = bool(kind) and (bool(d) and not fi_date_open(raw_date) if "date" in fields else bool(g.get("number") or g.get("client")))
    out["client_id"] = ofb_client_match(out["client_name"], clients)
    return out


def fnt_public(t):
    """The templates for the import page: the fixed ones with their blocks, the blocks and separators of an own one, the choice."""
    return {"templates": [{"name": k, **({"fields": list(v["fields"]), "sep": v["sep"]} if v else {})} for k, v in FNT_TEMPLATES.items()],
            "fields": list(FNT_FIELDS), "seps": list(FNT_SEPS), "custom_max": FNT_CUSTOM_MAX, "current": t["name"], "custom": t["custom"]}


def fnt_remember(c, oid, b):
    """The template named in request body b (if any) is checked and kept for office area oid (only when it changed: the
    settings' version moves on only then) -> the template to read with."""
    if "template" not in b:
        return fnt_stored(office_settings(c, oid))
    office_settings_lock(c, oid)  # the lock before the read (core: write_lock), as every read-change-write of the settings
    s = office_settings(c, oid)
    cur = fnt_stored(s)
    t = fnt_clean(b, cur)
    if t != cur:  # the standard never stored on its own (a new office keeps its first-visit country question)
        s["legacy_fn_template"] = t
        office_settings_save(c, oid, s)
        ofx_log(c, oid, "update", target="settings", detail={"legacy_fn_template": t["name"]})
        bump(c)
        c.commit()
    return t


def ofb_client_match(name, clients):
    """The id of the client [(id, name)] a file name's client field means (the same name, else a prefix of 4+), or None."""
    cn = fi_norm(name)
    if not cn or len(cn) < 3:
        return None
    best = None
    for cid, cname in clients:
        n = fi_norm(cname)
        if not n:
            continue
        if n == cn:
            return cid
        if best is None and len(n) >= 4 and (n.startswith(cn) or cn.startswith(n)):
            best = cid
    return best


def ofb_firm_is(firm, field):
    """2.533.0 (#4499): True when a file name field names the company read from the PDF (the same, or the start of it)."""
    f, n = fi_norm(firm), fi_norm(field)
    return bool(f and n and len(n) >= 3 and (f == n or f.startswith(n) or (len(f) >= 3 and n.startswith(f))))


def ofb_swap(p, firms, clients=()):
    """2.533.0 (#4499): client and project of a file name the wrong way round ("Client_Project_KV04_..."): when the client
    field does not name the company of the PDF (firms: the names read / the client found) but the first field does, the
    proposal with both swapped {client_name, client_id, project, project_no}; else None."""
    toks = re.sub(r"\.pdf$", "", os.path.basename(p.get("file_name") or ""), flags=re.I).strip().split("_")
    firms = [f for f in firms if f]
    if len(toks) < 3 or not firms or not p.get("client_name"):
        return None
    first, second = toks[0], toks[1]
    if first.isdigit() or p["client_name"] != second:
        return None
    if any(ofb_firm_is(f, second) for f in firms) or not any(ofb_firm_is(f, first) for f in firms):
        return None
    rest = p.get("project") if p.get("project") != first else ""
    return {"client_name": first, "client_id": ofb_client_match(first, clients),
            "project": " ".join(x for x in (second, rest) if x), "project_no": "" if p.get("project_no") == first else p.get("project_no") or ""}


def fi_number_taken(c, oid, num):
    """True when an archived document of organisation oid carries number num (new numbers must not collide with it)."""
    return bool(num) and bool(c.execute("SELECT 1 FROM office_archive WHERE org_id=? AND number=? LIMIT 1", (oid, num)).fetchone())


def fi_archive_path(oid, name):
    if not name or not re.fullmatch(r"archive-\d{1,12}-[0-9a-f]{16}\.pdf", name):
        return None
    p = os.path.join(OFFICE_DIR, str(int(oid)), name)
    return p if os.path.isfile(p) else None


def _txt(v, n):
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise BadInput(tr("Invalid data"))
    v = re.sub(r"[\x00-\x1f\x7f]", "", str(v)).strip()
    return v[:n]


def _archive_fields(c, oid, b, partial=False):
    f = {}
    if not partial or "kind" in b:
        k = _txt(b.get("kind"), 20) or "invoice"
        if k not in ("invoice", "offer"):
            raise BadInput(tr("Invalid value: {0}", "kind"))
        f["kind"] = k
    for k, n in (("number", 120), ("project_no", 40), ("project", 200), ("client_name", 200)):
        if not partial or k in b:
            f[k] = _txt(b.get(k), n)
    if "number" in f and re.search(r"[<>\"\\]", f["number"]):
        raise BadInput(tr("Invalid value: {0}", "number"))
    if not partial or "date" in b:
        d = _txt(b.get("date"), 10)
        if d:
            try:
                d = date.fromisoformat(d).isoformat()
            except ValueError:
                raise BadInput(tr("Invalid value: {0}", "date")) from None
        f["date"] = d
    if not partial or "amount" in b:
        a = b.get("amount")
        if a in (None, ""):
            f["amount"] = None
        else:
            d = _amount(a)  # 2.80.0 (#1837): thousand separators ("2.436,53", "1.500")
            if d is None:
                raise BadInput(tr("Invalid value: {0}", "amount"))
            f["amount"] = str(round(d, 2))
    if not partial or "paid" in b:
        f["paid"] = 1 if b.get("paid") in (1, True, "1", "true", "on") else 0
    if not partial or "client_id" in b:
        cid = b.get("client_id")
        if cid in (None, "", 0, "0"):
            f["client_id"] = None
        else:
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", "client_id")) from None
            if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone():
                raise BadInput(tr("Invalid value: {0}", "client_id"))
            f["client_id"] = cid
    return f


def _number_used(c, oid, num, aid=0):
    return bool(num) and bool(c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=?", (oid, num)).fetchone()
                              or c.execute("SELECT 1 FROM office_archive WHERE org_id=? AND number=? AND id!=?", (oid, num, aid)).fetchone())


def fi_archive_add(c, oid, uid, raw, file_name, b):
    if len(raw) > FI_PDF_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", FI_PDF_MAX // (1024 * 1024)))
    from ..files.scan import _sc_magic, sc_after_store, sc_scan
    if _sc_magic(raw) != "application/pdf":  # 2.61.0 review (#1818): by the content (no "<html>...%PDF-" polyglot)
        raise BadInput(tr("Only PDF files can be archived"))
    try:
        scan = sc_scan(file_name or "archive.pdf", raw)  # an unreachable scanner lets it through (decision 16.10.2026)
    except UploadRefused as e:
        raise BadInput(str(e))
    try:
        rid = int(b.get("run_id"))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "run_id")) from None
    run = _run_row(c, oid, rid)
    if run["kind"] != "archive" or run["undone_at"]:
        raise BadInput(tr("Invalid value: {0}", "run_id"))
    with c.savepoint():  # 2.40.0 (#1421): the ticked proposals of the PDF's address (new client / contact person)
        made = fk_archive_people(c, oid, uid, b, rid)
    if made:
        b = dict(b, client_id=made)
    f = _archive_fields(c, oid, b)
    if not f["number"]:
        f["number"] = _txt(re.sub(r"\.pdf$", "", file_name or "", flags=re.I), 120)
    write_lock(c, f"office_num_{int(oid)}")  # the same lock as the number of a new document (docs._assign_number)
    if _number_used(c, oid, f["number"]):
        raise Denied(409, tr("The number {0} is already used", f["number"]))
    sha = hashlib.sha256(raw).hexdigest()
    if c.execute("SELECT 1 FROM office_archive WHERE org_id=? AND sha256=?", (oid, sha)).fetchone():
        raise Denied(409, tr("This PDF is already in the archive"))
    s = office_settings(c, oid)
    row = dict(f, org_id=oid, run_id=rid, currency=s.get("currency") or "EUR", file_name=_txt(os.path.basename((file_name or "").replace("\\", "/")), 255),
               file="", sha256=sha, bytes=len(raw), created_by=uid, created_at=iso(now_utc()))
    aid = insert_id(c, f"INSERT INTO office_archive({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    name = f"archive-{int(aid)}-{sha[:16]}.pdf"
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    os.makedirs(d, mode=0o700, exist_ok=True)  # like the stored invoices (2.39.0 #1209 audit N8)
    p = os.path.join(d, name)
    # 2.40.0 (#1335): only the ".part" is written here; the caller renames it to its name after the commit (fk_archive_done)
    # and removes it when the commit fails -- an archive-*.pdf never exists without its row
    fd = os.open(p + ".part", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:  # 2.81.0 (#1462): any failure after the open leaves no orphan ".part" (the caller only cleans up after a return)
        with os.fdopen(fd, "wb") as fh:
            fh.write(oc_seal(c, oid, raw, fresh=True))  # 2.42.0 (#828): sealed with the organisation's key at rest (sha256 = the original)
        c.execute("UPDATE office_archive SET file=? WHERE id=? AND org_id=?", (name, aid, oid))
        sc_after_store(c, "oar", aid, oid, {"scan": scan})  # 2.209.0 D (#1856): scanner not reachable = marked, checked later
        _run_count(c, oid, rid)
    except BaseException:
        fk_archive_done(p, False)
        raise
    return aid, p


def fk_archive_done(p, committed):
    """2.40.0 (#1335): after the commit the .part becomes the archived file; without a commit it is removed."""
    try:
        if committed:
            os.replace(p + ".part", p)
        else:
            os.unlink(p + ".part")
    except OSError:
        pass


def _run_count(c, oid, rid):
    n = c.execute("SELECT COUNT(*) FROM office_archive WHERE org_id=? AND run_id=?", (oid, rid)).fetchone()[0]
    c.execute("UPDATE office_import_runs SET counts=? WHERE id=? AND org_id=?", (json.dumps({"archive": int(n)}), rid, oid))


def _archive_public(r, names=None):
    d = {k: r[k] for k in ("id", "kind", "number", "project_no", "project", "client_id", "client_name", "date", "currency", "file_name", "bytes", "run_id")}
    d["amount"] = float(r["amount"]) if r["amount"] is not None else None
    d["paid"] = int(r["paid"] or 0)
    d["archive"] = True
    if "copy_of" in r.keys() and r["copy_of"]:  # 2.97.0 C (#2049): a read-only copy taken along by a move between offices
        try:
            cp = json.loads(r["copy_of"])
        except ValueError:
            cp = {}
        d["copy"] = {k: cp.get(k) or "" for k in ("from", "name", "kind", "number")} if isinstance(cp, dict) else {}
    if names is not None and r["client_id"]:
        d["client"] = names.get(r["client_id"]) or ""
    from .archiveedit import r81b_public
    return r81b_public(d, r)  # 2.81.0 (#1834): net + tax lines when known


def fi_archive_rows(c, oid, kind="", client_id=0):
    names = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)}")}
    sql, args = "SELECT * FROM office_archive WHERE org_id=?", [oid]
    if kind in ("invoice", "offer"):
        sql += " AND kind=?"
        args.append(kind)
    if client_id:  # 2.81.0 (#1834): the documents of one client
        sql += " AND client_id=?"
        args.append(client_id)
    return sc_up(c, "oar", [_archive_public(r, names) for r in c.execute(sql + " ORDER BY date DESC, id DESC", args)])  # 2.209.0 D (#1856): scan mark as `up`


# ---------------------------------------------------------------- 2.40.0 (#1421): the recipient's address of an old PDF
# The text layer of the first page (tasks.attachtext.pdf_text, no OCR: a scan only gets a hint). The recipient block is
# the lines above the first postcode + city line that is not the organisation's own (its postcode / city, its name, a
# one-line sender "Firma · Straße · PLZ Ort"); split like a spreadsheet address (fi_split_address), with its reasons.
# Then the proposals, each only a suggestion the person ticks: a new client (no client matches), the contact person for a
# client that has another one, a note when the address differs from the client card.
FK_STOP_RE = re.compile(r"(?:\btel\b|telefon|phone|\bfax\b|e-?mail|www\.|https?:|@|\biban\b|\bbic\b|ust-?id|steuer|vat\b|"
                        r"rechnung|angebot|kostenvoranschlag|gutschrift|invoice|quotation|offer\b|datum|date\b|seite|page\b|kunden-?nr|customer)", re.I)
FK_SENDER_RE = re.compile(r"[·•|]|\s[-–]\s.*\d{4,5}")
FK_ZIPLINE_RE = re.compile(r"^(?:[A-Z]{1,2}\s?[-–]\s?)?\d{4,5}\s+\S")
# 2.46.2 (#1646): bank and contact VALUES without their label (a template prints the labels in a column of their own and the
# values above the recipient): the walk up from the postcode line stops at them
FK_VALUE_RE = re.compile(
    r"^(?:[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\s?[A-Z0-9]{1,4}"  # IBAN
    r"|[A-Z]{4}(?:DE|AT|CH|NL|BE|LU|FR|IT|ES|PT|GB|IE|DK|SE|NO|FI|PL|CZ|US)[A-Z0-9]{2}(?:[A-Z0-9]{3})?"  # BIC
    r"|\+?[\d ()/.-]{7,}"  # phone
    r"|\d{2,3}/\d{3,4}/\d{4,5}"  # tax number
    r"|[A-Z]{2} ?U?\d[\d ]{7,11}"  # VAT id (ATU12345678)
    r"|(?:[\w-]+\.)+[a-z]{2,})$")  # a bare domain
FK_BANKNAME_RE = re.compile(r"\b(?:sparkasse|volksbank|raiffeisenbank|postbank|commerzbank|[a-zäöüß]*bank)\b", re.I)
FK_SALUTATION_RE = re.compile(r"^(?:sehr geehrte|guten tag|(?:liebe[rs]?|hallo|dear|hello)\b(?=.*[,!]$|\s+(?:herr|frau|mr|ms|mrs)\b))", re.I)
FK_FORM_RE = re.compile(r"\b(?:gmbh|ag|kg|ohg|gbr|ug|se|eg|e\.?\s?v\.?|\w*gesellschaft)\b", re.I)


def fk_value_line(ln, near=()):
    """True for a line that is no recipient line: a bank or contact value (IBAN, BIC, phone, tax / VAT number, bare domain) or the
    salutation; a bank's name only next to such a value (a savings bank can be the recipient itself). near: the neighbour lines."""
    t = ln.strip()
    if FK_SALUTATION_RE.match(t) and not LEGAL_RE.search(t):
        return True
    if FK_VALUE_RE.match(t) and (sum(ch.isdigit() for ch in t) >= 7 or "." in t
                                 or re.match(r"^[A-Z]{6}", t) and (not t.isalpha() or t.endswith("XXX"))):
        return True
    if FK_BANKNAME_RE.search(t) and not FK_FORM_RE.search(t) and not PERSON_RE.match(t) and not ATTN_RE.match(t):
        return any(fk_value_line(x) for x in near if x)
    return False


FK_PDF_LINES = 100  # 2.56.1 (#1813): the whole first page (pdf_text joins pages without a mark; a dense page has 60-75 lines)
# 2.56.1 (#1813): postcode lines with the city first: "New York NY 10017" (a real US state), "London SW1A 1AA", and the
# UK postcode in front ("EC4M 7RB London"); amounts and totals are never an address line
FKA_US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
                    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
FKA_US_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,30}?,?\s+(?P<st>[A-Z]{2})\s+\d{5}(?:-\d{4})?$")
FKA_UK_PC = r"[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2}"
FKA_UK_RE = re.compile(rf"^(?:{FKA_UK_PC}\s+[A-Z][A-Za-z .'-]{{1,30}}|[A-Z][A-Za-z .'-]{{1,30}}?,?\s+{FKA_UK_PC})$")
FKA_AMOUNT_RE = re.compile(r"[€$£%]|\d,\d{2}(?!\d)|\d[.,]\d{3}[.,]\d{2}(?!\d)|\b(?:summe|zwischensumme|mwst|netto|brutto|subtotal|total)\b", re.I)
# a quantity of a line item ("10000 Stück Flyer", "1200 x A4", "2026 konzept"): a unit or a lower-case word after the number
FKA_QTY_RE = re.compile(r"^\d{4,5}\s+(?:[a-zäöüß]|(?i:stück|stk|std|stunden|tage|seiten|exemplare|minuten|min|kg|x)\b)")
FKA_TAIL_COUNTRY_RE = re.compile(r"^(?P<head>.*?\S)\s*(?:[,/]|\s[-–])\s*(?P<country>[A-Za-zÄÖÜäöü. ]{2,30})$")


def fka_zipline(ln, i):
    """2.56.1 (#1813): True for a postcode + city line (German / European postcode first, Dutch, US, UK)."""
    if len(ln) > 60 or FKA_AMOUNT_RE.search(ln) or FKA_QTY_RE.match(ln):
        return False
    if FK_ZIPLINE_RE.match(ln) or (NL_ZIP_RE.match(ln) and i):
        return True
    m = FKA_US_RE.match(ln)
    return bool(m and m.group("st") in FKA_US_STATES) or bool(FKA_UK_RE.match(ln))


def fka_norm(s):
    """2.56.1 (#1813): a name for comparing with the organisation's own: fi_norm, also without eGbR / e.K. / PartG and the
    space a PDF puts before a comma ("Name , Name & Name eGbR")."""
    s = re.sub(r"\b(?:e\.?\s?gbr|e\.\s?k(?:fm|fr)?\.?|partg(?:\s?mbb)?)(?=\W|$)", " ", (s or "").lower())
    return fi_norm(s)


def fka_street(s):
    s = _cname(s).replace("ß", "ss")
    s = re.sub(r"stra?sse\b|str\b\.?", "str", s)
    return re.sub(r"[^a-z0-9äöü]+", "", s)


def fka_split_country(ln):
    """2.56.1 (#1813): "50733 Cologne / Germany", "10178 Berlin, Germany" -> ("50733 Cologne", "Germany"); else (ln, "")."""
    m = FKA_TAIL_COUNTRY_RE.match(ln)
    if m and m.group("country").strip(" .").lower() in COUNTRIES:
        return m.group("head"), m.group("country").strip()
    return ln, ""


def fk_pdf_block(text, own):
    """The recipient block (list of lines) of a document's text, [] when none is found. own: the organisation's company
    fields (name, street, zip, city; each may be empty) -- their lines are the sender, not the recipient. 2.56.1 (#1813):
    the first block on the first page that is not the organisation's own; the walk up stops at another postcode line and at
    the own name / street (a name on two lines, eGbR, a city in another language: the own block is its street or name)."""
    first = (text or "").split("\f")[0]
    lines = [re.sub(r"\s+", " ", x).strip() for x in first.replace("\r", "\n").split("\n")]
    lines = [x for x in lines if x][:FK_PDF_LINES]
    oname = fka_norm(own.get("name") or "")
    ozip, ocity = (own.get("zip") or "").replace(" ", ""), (own.get("city") or "").strip().lower()
    ostreet = fka_street(own.get("street"))
    norms = [fka_norm(x) for x in lines]

    def part(k):  # a piece of the own name (4+ characters), e.g. one line of a name on two lines
        return 0 <= k < len(lines) and len(oname) >= 4 and len(norms[k]) >= 4 and norms[k] in oname

    def own_line(k):
        n = norms[k]
        if len(oname) >= 4 and oname in n:
            return True
        if not part(k):
            return False
        # alone a line counts only when it covers two thirds of the own name (a client "Name" of "Name Film GmbH" stays a client)
        return len(n) >= 6 and 3 * len(n) >= 2 * len(oname) or part(k - 1) or part(k + 1) \
            or k > 0 and len(norms[k - 1] + n) >= 4 and (norms[k - 1] + n) in oname

    def own_street(k):
        st = fka_street(lines[k])
        return bool(ostreet) and len(ostreet) >= 4 and (st == ostreet or st.startswith(ostreet) and not st[len(ostreet):][:1].isdigit())
    zips = [fka_zipline(ln, i) for i, ln in enumerate(lines)]
    for i, ln in enumerate(lines):
        if not zips[i] or FK_SENDER_RE.search(ln) or own_line(i):
            continue
        zl, country = fka_split_country(ln)
        m = ZIP_RE.match(zl)
        same_zip = bool(m and ozip and m.group("zip") == ozip)
        top, own_seen = i, False
        while top > 0 and i - top < 5:
            up = lines[top - 1]
            # the own street counts only with the own postcode (or none known): a client in the same street of another town stays
            if own_line(top - 1) or own_street(top - 1) and (same_zip or not ozip):
                own_seen = True
                break
            if zips[top - 1] or FK_SENDER_RE.search(up) or FK_STOP_RE.search(up) and not ATTN_RE.match(up) or len(up) > 70 \
                    or FKA_AMOUNT_RE.search(up) or up.endswith(":") or len(up.split()) > 8 \
                    or fk_value_line(up, (lines[top - 2] if top > 1 else "", lines[top])) \
                    or len(up) <= 14 and " " in up and fk_value_line(up.replace(" ", "")):  # a BIC split by the PDF: "COL SDE33"
                break
            top -= 1
        if own_seen and (top == i or same_zip or not ozip):
            continue  # the organisation's own address block (letterhead / sender column); a client in the same town stays
        if same_zip and m.group("city").strip().lower() == ocity and top == i:
            continue
        if top == i:
            continue  # a postcode line without anything above it is no address
        block = lines[top:i] + [zl] + ([country] if country else [])
        if not country and i + 1 < len(lines) and lines[i + 1].strip(" .").lower() in COUNTRIES:
            block.append(lines[i + 1])
        return block
    return []


def fka_own(c, oid, own):
    """2.56.1 (#1813): the company fields, empty ones filled from the free company lines of the settings (an organisation
    that never filled the fields prints those)."""
    own = dict(own)
    if own.get("name") and own.get("street") and own.get("zip"):
        return own
    free = (office_settings(c, oid) or {}).get("company") or {}
    own["name"] = own.get("name") or free.get("name") or ""
    for ln in (x for y in free.get("lines") or [] for x in str(y).split(",")):  # "Straße 1, 12345 Ort" on one line too
        ln = _clean_line(ln)
        m = ZIP_RE.match(ln)
        if m and not own.get("zip"):
            own["zip"], own["city"] = m.group("zip"), own.get("city") or m.group("city")
        elif not m and STREET_RE.search(ln) and not own.get("street"):
            own["street"] = ln
    return own


def fk_pdf_address(c, oid, raw, uid, client_id=None):
    """-> {status: ok | no_text | none | busy | error, address?: split + reasons, client_id, client_name, new_client,
    add_contact, address_differs}."""
    t = pdf_text(raw, owner=uid)
    if t.get("error"):
        return {"status": "busy" if t["error"] == "busy" else "error"}
    if t.get("no_text_layer"):
        return {"status": "no_text"}
    block = fk_pdf_block(t.get("text") or "", fka_own(c, oid, ofx_company(c, oid) or {}))
    if not block:
        return {"status": "none"}
    a = fi_split_address("\n".join(block))
    if len(block) < 3 and "one_line" not in a["flags"]:
        a["flags"].append("extra_lines" if len(block) > 4 else "no_street")
    a["reasons"] = [tr(FI_REASONS[f]) for f in dict.fromkeys(a["flags"])]
    out = {"status": "ok", "address": a, "unsure": bool(a["flags"]), "client_id": None, "client_name": "", "new_client": False,
           "add_contact": "", "address_differs": False}
    n = fi_norm(a["name"])
    known = _org_clients(c, oid)
    hit = next((k for k in known if _same(n, a["zip"], fi_norm(k["name"]), k["zip"] or "")), None)
    if hit is None and client_id:
        hit = next((k for k in known if k["id"] == client_id), None)
    if hit is None:
        out["new_client"] = bool(a["name"])
        return out
    out["client_id"], out["client_name"] = hit["id"], hit["name"]
    if a["contact"] and not fk_has_name(c, hit["id"], a["contact"]) and _cname(hit["contact"]) != _cname(a["contact"]):
        out["add_contact"] = a["contact"][:120]
    for k in ("street", "zip", "city"):
        if a[k] and (hit[k] or "") and _cname(a[k]).replace(" ", "") != _cname(hit[k]).replace(" ", ""):
            out["address_differs"] = True
    return out


def fk_archive_people(c, oid, uid, b, rid):
    """2.40.0 (#1421): the ticked proposals of an archived PDF -- new_client (JSON {name, contact, street, zip, city,
    country}: a client of this run; the same company + postcode again in the run reuses it) and add_contact (a name for
    the client_id) -> the client id to file the document under (or None)."""
    cid = None
    raw = b.get("new_client")
    if raw:
        try:
            x = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "new_client")) from None
        if not isinstance(x, dict):
            raise BadInput(tr("Invalid value: {0}", "new_client"))
        f = {k: x.get(k) for k in ("name", "contact", "street", "zip", "city", "country") if isinstance(x.get(k), str)}
        n = fi_norm(f.get("name") or "")
        same = next((k for k in _org_clients(c, oid) if _same(n, f.get("zip") or "", fi_norm(k["name"]), k["zip"] or "")), None)
        if same:
            cid = same["id"]
        else:
            f["org_id"] = pb_cl_org(c, oid)  # 2.47.3 (#1360)
            f = clean_client(c, uid, f, new=True)
            ts = iso(now_utc())
            f.update(org_id=pb_cl_org(c, oid), created_by=uid, created_at=ts, updated_at=ts, import_run_id=rid)
            cid = insert_id(c, f"INSERT INTO clients({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
            if f.get("contact"):
                fk_add(c, cid, pb_cl_org(c, oid), {"name": f["contact"]}, run_id=rid, default=True)
    name = str(b.get("add_contact") or "").strip()
    if name:
        tid = cid
        if tid is None:
            try:
                tid = int(b.get("client_id"))
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", "client_id")) from None
        if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (tid,)).fetchone():
            raise BadInput(tr("Invalid value: {0}", "client_id"))
        if not fk_has_name(c, tid, name):
            fk_add(c, tid, pb_cl_org(c, oid), {"name": name[:120]}, run_id=rid)
            fk_sync(c, tid)
    return cid


# ---------------------------------------------------------------- the counter proposal
def fi_counter(c, oid, kind):
    """The proposal for the counter of kind (invoice | offer): the highest number found in the archive (a number that
    follows today's scheme, else the project number of the file name) next to the counter's current value."""
    s = office_settings(c, oid)
    scheme = inv_scheme(s, kind)
    period = office_scheme_period(scheme)
    r = c.execute("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, kind, period)).fetchone()
    last = int(r["last"]) if r else 0
    high, src = 0, ""
    for a in c.execute("SELECT number, project_no FROM office_archive WHERE org_id=? AND kind=?", (oid, kind)):
        seq = inv_manual_seq(scheme, a["number"] or "")
        if seq is None and (a["project_no"] or "").isdigit() and len(a["project_no"]) <= 9:
            seq = int(a["project_no"])
        if seq is not None and seq > high:
            high, src = seq, a["number"]
    sug = max(high, last)
    return {"kind": kind, "scheme": scheme, "period": period, "last": last, "highest": high, "highest_number": src, "proposal": sug,
            "next_now": office_number_format(scheme, last + 1), "next_after": office_number_format(scheme, sug + 1)}


# ---------------------------------------------------------------- routes (org admins; members read the archive)
from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _upload(name, mx):
    f = request.files.get(name)
    if not f:
        raise BadInput(tr("No file"))
    raw = f.read(mx + 1)
    if len(raw) > mx:
        raise BadInput(tr("The file is too large (at most {0} MB)", mx // (1024 * 1024)))
    return f, raw


@app.post("/api/office/legacy/preview")
def fi_preview_post():
    """Org admin. multipart 'file' (.xlsx or CSV, 2.146.0 E #2456; optional 'map' = the client columns) -> the preview: clients (split address, reasons, duplicate), services,
    equipment, other sheets (counted only). Nothing is stored."""
    c, uid, oid = _ctx()
    f, raw = _upload("file", FI_XLSX_MAX)
    amap = None
    if request.form.get("map"):  # 2.146.0 E (#2456): the person's column choice {field: column index}
        try:
            amap = json.loads(request.form["map"][:2000])
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "map")) from None
    return jsonify(fi_preview(c, oid, raw, f.filename or "", amap))


@app.post("/api/office/legacy/split")
def fi_split_post():
    """Org admin. {address} -> the split of one address (the preview's "split again" after an edit of the text)."""
    _ctx()
    t = (body() or {}).get("address")
    a = fi_split_address(t[:2000] if isinstance(t, str) else "")
    a["reasons"] = [tr(FI_REASONS[f]) for f in a["flags"]]
    return jsonify(a)


@app.post("/api/office/legacy/import")
def fi_import_post():
    c, uid, oid = _ctx()
    write_lock(c, f"office_import_{int(oid)}")
    rid, counts = fi_import(c, oid, uid, body())
    ofx_log(c, oid, "import", target="legacy", detail={"run_id": rid, "counts": counts})
    bump(c)
    c.commit()
    return jsonify(run_id=rid, counts=counts), 201


@app.get("/api/office/legacy/runs")
def fi_runs_get():
    c, uid, oid = _ctx()
    users = {}
    out = []
    for r in c.execute("SELECT * FROM office_import_runs WHERE org_id=? ORDER BY id DESC LIMIT 100", (oid,)):
        try:
            counts = json.loads(r["counts"] or "{}")
        except ValueError:
            counts = {}
        if r["created_by"] and r["created_by"] not in users:
            u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["created_by"],)).fetchone()
            users[r["created_by"]] = (u["display_name"] or u["username"]) if u else ""
        out.append({"id": r["id"], "kind": r["kind"], "counts": counts, "total": sum(v for k, v in counts.items() if k != "skipped" and isinstance(v, int)),
                    "created_at": r["created_at"], "user_name": users.get(r["created_by"], ""), "undone_at": r["undone_at"]})
        if r["kind"] == "data":  # 2.46.1 (#1557): per area: its entries and when it was undone
            und = bk_detail(r).get("undone") or {}
            out[-1]["areas"] = {k: {"count": n, "undone_at": und.get(k) if isinstance(und, dict) else None}
                                for k, n in bk_area_counts(counts if isinstance(counts, dict) else {}).items()}
            out[-1]["leftover"] = len(imr_leftover_ids(c, oid, r)) if r["undone_at"] or und else 0  # 2.138.0 E (#2241)
    return jsonify(runs=out)


@app.post("/api/office/legacy/runs/<int:rid>/undo")
def fi_undo_post(rid):
    """Org admin. 2.46.1 (#1557): body {kinds: [clients | services | equipment]} = only these areas (none: the whole run)."""
    c, uid, oid = _ctx()
    kinds = (body() or {}).get("kinds")
    removed, kept, files, archived = fi_undo(c, oid, uid, rid, kinds=kinds)
    ofx_log(c, oid, "undo", target="legacy", detail={"run_id": rid, "removed": removed, "kept": kept, **({"kinds": kinds} if kinds else {}),
                                                     **({"archived": [{"kind": a["kind"], "id": a["id"]} for a in archived]} if archived else {})})
    bump(c)
    c.commit()
    _unlink_files(oid, files)  # after the commit: a failed undo keeps its files
    return jsonify(removed=removed, kept=kept, archived=archived)  # 2.138.0 E (#2241): + the archived entries


@app.post("/api/office/legacy/runs/<int:rid>/tidy")
def imr_tidy_post(rid):
    """Org admin. 2.138.0 E (#2241): archives what an earlier undo of run rid left active (its services / devices of the
    undone areas, never the producing service; nothing deleted) -> {archived: [{kind, id, name, used}]}."""
    c, uid, oid = _ctx()
    archived = imr_tidy(c, oid, rid)
    if archived:
        ofx_log(c, oid, "archive", target="legacy", detail={"run_id": rid, "archived": [{"kind": a["kind"], "id": a["id"]} for a in archived]})
    bump(c)
    c.commit()
    return jsonify(archived=archived)


@app.post("/api/office/services/renumber")
def imr_renumber_post():
    """Org admin (like editing a service). 2.138.0 E (#2237): numbers the services 1..n in the order the list shows;
    body {sorts: {id: sort}} instead sets exactly these values (the undo / redo of the client; only own services).
    -> {changed, before: {id: sort}} (before = the old values of the changed services)."""
    c, uid, oid = _ctx()
    b = body() or {}
    write_lock(c, f"office_import_{int(oid)}")
    before = {str(r["id"]): r["sort"] for r in office_rows(c, oid, "services")}
    sorts = b.get("sorts") if isinstance(b, dict) else None
    if sorts is not None:
        if not isinstance(sorts, dict) or len(sorts) > 5000:
            raise BadInput(tr("Invalid data"))
        ts = iso(now_utc())
        for k, v in sorts.items():
            if k not in before or not isinstance(v, (int, float)) or isinstance(v, bool) or abs(v) >= 1e12:
                raise BadInput(tr("Invalid data"))
            c.execute("UPDATE office_services SET sort=?, updated_at=? WHERE id=? AND org_id=?", (float(v), ts, int(k), oid))
    else:
        imr_renumber(c, oid)
    after = {str(r["id"]): r["sort"] for r in office_rows(c, oid, "services")}
    old = {k: v for k, v in before.items() if after.get(k) != v}
    if old:
        ofx_log(c, oid, "update", target="services", detail={"renumber": len(old)})
    bump(c)
    c.commit()
    return jsonify(changed=len(old), before=old)


@app.post("/api/office/legacy/archive/parse")
def fi_parse_post():
    """Org admin. {names: [file name, ...], template?, fields?, sep?} -> {items: [the key data each name suggests], template}.
    2.621.0 (#4600): template = a name of FNT_TEMPLATES ("custom": fields + sep from the fixed blocks); given, it is kept for
    the office area (an unknown name: 400); left out, the kept one reads. Nothing else is stored."""
    c, uid, oid = _ctx()
    b = body() or {}
    names = b.get("names") if isinstance(b, dict) else None
    if not isinstance(names, list) or len(names) > 500 or not all(isinstance(n, str) for n in names):
        raise BadInput(tr("Invalid data"))
    t = fnt_remember(c, oid, b)
    cl = [(r["id"], r["name"]) for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 AND deleted_at IS NULL ORDER BY id")]
    items = []
    for n in names:
        p = fnt_parse(n[:300], cl, t)
        p["taken"] = _number_used(c, oid, p["number"])
        items.append(p)
    return jsonify(items=items, template=t)


@app.get("/api/office/legacy/archive/templates")
def fnt_get():
    """2.621.0 (#4600) org admin: the file name templates of the archive import and the one kept for this office area."""
    c, uid, oid = _ctx()
    return jsonify(fnt_public(fnt_stored(office_settings(c, oid))))


@app.post("/api/office/legacy/archive/address")
def fk_archive_address_post():
    """2.40.0 (#1421) org admin. multipart 'file' (PDF) + client_id? (the file name's proposal) + file_name? -> the recipient's
    address read from the text layer of page 1 and the proposals (new client / contact person / address differs; 2.533.0
    #4499: swap = client and project of the file name swapped when only its first field names the PDF's company); nothing stored."""
    c, uid, oid = _ctx()
    if hit_limit(f"pdftext:{uid}", PDF_RATE, 600):  # 2.81.0 (#1463): the same budget as POST /api/pdf-text
        raise Denied(429, tr("Too many requests, please slow down"))
    f, raw = _upload("file", FI_PDF_MAX)
    if raw[:1024].find(b"%PDF-") < 0:
        raise BadInput(tr("Only PDF files can be archived"))
    try:
        cid = int(request.form.get("client_id") or 0) or None
    except ValueError:
        cid = None
    out = fk_pdf_address(c, oid, raw, uid, cid)
    # 2.533.0 (#4499): file_name (optional): client / project of the name checked against the company of the PDF -> swap
    fn = str(request.form.get("file_name") or "")[:300]
    if fn and out.get("status") == "ok" and fnt_stored(office_settings(c, oid))["name"] != "standard":
        out["swap"] = None  # 2.621.0 (#4600): the swap knows only the standard names (Project_Client_KV..)
    elif fn and out.get("status") == "ok":
        cl = [(r["id"], r["name"]) for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 AND deleted_at IS NULL ORDER BY id")]
        p = fi_parse_filename(fn, cl)
        # the company found among the clients counts only when the PDF's name led there (not the file name's client_id)
        known = out["client_name"] if out.get("client_id") and out["client_id"] != cid else ""
        out["swap"] = ofb_swap(p, [(out.get("address") or {}).get("name") or "", known], cl)
        if out["swap"] and cid and out.get("client_id") == cid:
            # review 2.533.0 (#4499): the client was found only through the file name's (wrong) client_id: read again
            # without it, so the swapped name gets its own client or the "new client" proposal (was: kept the wrong one)
            sw = out["swap"]
            out = fk_pdf_address(c, oid, raw, uid, sw.get("client_id"))
            out["swap"] = sw
    return jsonify(out)


@app.post("/api/office/legacy/archive/run")
def fi_archive_run_post():
    """Org admin: opens an archive run (the uploads that follow carry its id; one run = one "undo")."""
    c, uid, oid = _ctx()
    rid = _run_new(c, oid, uid, "archive")
    c.execute("UPDATE office_import_runs SET counts=? WHERE id=? AND org_id=?", (json.dumps({"archive": 0}), rid, oid))
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(run_id=rid), 201


@app.post("/api/office/legacy/archive")
def fi_archive_post():
    """Org admin. multipart 'file' (PDF) + fields run_id, kind (invoice | offer), number, project_no, project, client_id,
    client_name, date (YYYY-MM-DD), amount, paid -> 201 the archived document. 409 for a used number or the same PDF."""
    c, uid, oid = _ctx()
    f, raw = _upload("file", FI_PDF_MAX)
    aid, p = fi_archive_add(c, oid, uid, raw, f.filename or "", request.form.to_dict())
    try:
        from .ledger import ofx_log
        ofx_log(c, oid, "upload", target="archive", detail={"archive_id": aid, "bytes": len(raw)})
        bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
        c.commit()
    except BaseException:
        fk_archive_done(p, False)
        raise
    fk_archive_done(p, True)
    r = c.execute("SELECT * FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    return jsonify(_archive_public(r)), 201


@app.get("/api/office/legacy/archive")
def fi_archive_get():
    """Members read the archive (?kind=invoice|offer, ?client_id=): the documents and the sums (all / paid)."""
    c, uid, oid = _ctx(admin=False)
    try:
        cid = int(request.args.get("client_id") or 0)
    except ValueError:
        cid = 0
    rows = fi_archive_rows(c, oid, request.args.get("kind") or "", cid)
    own = [r for r in rows if not r.get("copy")]  # 2.97.0 C (#2049): copies of another office's documents count there, not here
    tot = sum(Decimal(str(r["amount"])) for r in own if r["amount"] is not None and r["kind"] == "invoice")
    paid = sum(Decimal(str(r["amount"])) for r in own if r["amount"] is not None and r["kind"] == "invoice" and r["paid"])
    return jsonify(items=rows, sum_invoices=float(tot), sum_paid=float(paid), admin=office_role(c, uid, oid) == "admin")


@app.patch("/api/office/legacy/archive/<int:aid>")
def fi_archive_patch(aid):
    """Members (2.81.0 #1834, before: org admins): only the bookkeeping notes of an archived document (client, amount or
    tax_lines [{net, tax: 19|7|0|rc}], paid for invoices); the PDF and its number stay. Each change goes into its history.
    Audit B3 (#1968): members only the client; amount / tax_lines / paid an office admin (403), never negative (400)."""
    c, uid, oid = _ctx(admin=False)
    b = body() or {}
    from .archiveedit import r81b_archive_patch
    f = r81b_archive_patch(c, oid, uid, aid, b if isinstance(b, dict) else {})
    if f:
        ofx_log(c, oid, "update", target="archive", detail={"archive_id": aid, "fields": sorted(f)})
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(_archive_public(c.execute("SELECT * FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()))


@app.get("/api/office/legacy/archive/<int:aid>/pdf")
def fi_archive_pdf(aid):
    """Members: the original PDF, unchanged."""
    c, uid, oid = _ctx(admin=False)
    r = c.execute("SELECT file, file_name FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    p = fi_archive_path(oid, r["file"]) if r else None
    if not p:
        raise Denied(404)
    sc_guard(c, "oar", aid)  # 2.209.0 D (#1856): found infected (strict: not checked yet) = locked
    ofx_log(c, oid, "pdf", target="archive", detail={"archive_id": aid}, dedupe_min=10)
    c.commit()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", r["file_name"] or "").strip("-") or f"archive-{aid}.pdf"
    resp = oc_send_file(c, p, mimetype="application/pdf", download_name=name, as_attachment=request.args.get("download") == "1")  # 2.42.0 (#828)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"  # a foreign PDF never runs script under the app origin
    return resp


@app.get("/api/office/legacy/counter")
def fi_counter_get():
    c, uid, oid = _ctx()
    return jsonify(invoice=fi_counter(c, oid, "invoice"), offer=fi_counter(c, oid, "offer"))


@app.post("/api/office/legacy/counter")
def fi_counter_post():
    """Org admin. {kind: invoice | offer, last, reason?} -> the counter continues after last (never lowered); raising the
    invoice counter needs a reason like the number ranges (2.144.6 B, #2400 F2)."""
    c, uid, oid = _ctx()
    b = body() or {}
    kind = b.get("kind")
    if kind not in ("invoice", "offer"):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    try:
        last = int(b.get("last"))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "last")) from None
    write_lock(c, f"office_num_{int(oid)}")
    cur = fi_counter(c, oid, kind)
    if isinstance(b.get("last"), bool) or last < cur["last"] or last > 10 ** 9:
        raise BadInput(tr("The counter can only be raised (now {0})", cur["last"]))
    from .numranges import onum_reason  # 2.144.6 B (#2400 F2): the same reason duty (GoBD) as the number ranges
    reason = onum_reason(kind, last - cur["last"], b.get("reason"))
    if reason is None:
        raise BadInput(tr("The number skips {0} numbers of the series; give a reason (GoBD)", last - cur["last"]))
    c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,?) ON CONFLICT(org_id, kind, period) DO UPDATE SET last=excluded.last",
              (oid, kind, cur["period"], last))
    ofx_log(c, oid, "number", target="legacy", detail={"kind": kind, "from": cur["last"], "to": last, **({"reason": reason} if reason else {})})
    bump(c)  # 2.566.0 (#4706): the area tick, other devices reload
    c.commit()
    return jsonify(fi_counter(c, oid, kind))

