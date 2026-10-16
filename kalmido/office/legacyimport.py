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
import hashlib
import hmac
import io
import json
import os
import re
import unicodedata
import zipfile
import zlib
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from flask import jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.i18n import N_, tr
from ..core.pg import insert_id, write_lock
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .model import (MD, pb_cl_org, pb_cl_sql, office_create, office_gate, office_in_use, office_number_format, office_org, office_role, office_rows, office_scheme_period,
                    office_settings, office_update)

FI_XLSX_MAX = 10 * 1024 * 1024  # the uploaded spreadsheet
FI_XLSX_UNZIPPED_MAX = 80 * 1024 * 1024  # all members unpacked (zip bomb guard)
FI_PDF_MAX = 20 * 1024 * 1024
FI_ROWS_MAX = 2000  # rows per sheet taken into the preview
FI_NAME_MAX = 80  # clients.name

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
    "one_line": N_("Only one line"),
    "foreign": N_("Address abroad: please check the fields"),
    "person_swap": N_("First line taken as the contact person: please check"),
}


# ---------------------------------------------------------------- reading .xlsx (zipfile + xml.etree)
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _xml(z, name, budget):
    info = z.getinfo(name)
    budget[0] += info.file_size
    if budget[0] > FI_XLSX_UNZIPPED_MAX:
        raise BadInput(tr("The file is too large"))
    data = z.read(name)
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():  # no entity tricks in a spreadsheet
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    return ET.fromstring(data)


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
    return c1, r1, c2, r2


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
    budget = [0]
    try:
        strings = []
        if "xl/sharedStrings.xml" in names:
            for si in _xml(z, "xl/sharedStrings.xml", budget):
                if _local(si.tag) == "si":  # plain <t> or rich text runs <r><t>; phonetic hints <rPh> are not text
                    strings.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t" and not _in_rph(si, t)))
        wb = _xml(z, "xl/workbook.xml", budget)
        wrels = _rels(z, "xl/workbook.xml", budget)
        out = {}
        for sh in wb.iter():
            if _local(sh.tag) != "sheet":
                continue
            rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
            path = wrels.get(rid)
            if not path or path not in names:
                continue
            grid = _sheet(z, path, strings, budget)
            out.setdefault((sh.get("name") or "").strip().lower(), grid)
            for t in _rels(z, path, budget).values():  # the sheet's tables (Excel "Format as table"; Power Query output)
                if t in names and "/tables/" in t:
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
    except (ET.ParseError, KeyError, ValueError, zipfile.BadZipFile, zlib.error, EOFError):  # broken file -> 400, not 500
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None


def _in_rph(si, t):
    for rph in si:
        if _local(rph.tag) == "rPh" and any(x is t for x in rph.iter()):
            return True
    return False


def _sheet(z, path, strings, budget):
    rows = {}
    for row in _xml(z, path, budget).iter():
        if _local(row.tag) != "row":
            continue
        r = int(row.get("r") or (max(rows) + 1 if rows else 1))
        if r > FI_ROWS_MAX + 50:
            break
        cells = {}
        for k, cel in enumerate(x for x in row if _local(x.tag) == "c"):
            ref = cel.get("r")
            ci = _col_index(ref) if ref else k
            if ci > 200:
                continue
            t, v = cel.get("t"), None
            for ch in cel:
                if _local(ch.tag) == "v":
                    v = ch.text or ""
                elif _local(ch.tag) == "is":
                    v = "".join(x.text or "" for x in ch.iter() if _local(x.tag) == "t")
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
            cells[ci] = v
        rows[r] = cells
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
        if m:
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
    return [dict(r) for r in c.execute(f"SELECT id, name, zip, city, street, contact, country, address FROM clients WHERE {pb_cl_sql(c, oid)} ORDER BY id")]


def _cname(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def fk_other_contact(c, a, dup, rows):
    """2.40.0 (#1380): True when duplicate row a names a contact person its client (existing: dup.id; in the file: the
    row dup.row and the rows already added to it) does not have yet."""
    from .contacts_cl import fk_has_name
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
    s = str(v or "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d) > Decimal("1e9"):
        return None
    return float(round(d, 4))


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
        e = {"row": i + 2, "name_de": nm[:200]}
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


def fi_preview(c, oid, raw):
    book = fi_xlsx_read(raw)
    out = {"sheets": sorted(book), "clients": [], "roles": [], "crew": [], "services": [], "equipment": [], "other": {}}
    t = _table(book, "contacts", "kontakte", "kunden", "adressen")
    if t:
        head, rows = t
        ci = _col(head, "addresses", "address", "adresse", "adressen", "anschrift")
        if ci is None and head:
            ci = 0
        known = _org_clients(c, oid)
        kn = [(fi_norm(k["name"]), k["zip"] or "", k) for k in known]
        seen = []
        for i, row in enumerate(rows):
            txt = str(row[ci] if ci is not None and ci < len(row) else "").strip()
            if not txt:
                continue
            a = fi_split_address(txt)
            a["row"] = i + 2
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
            s = {"row": i + 2, "name_de": de[:200], "name_en": cell(row, "en")[:200], "category": (cell(row, "cat") or cat)[:80],
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
            e = {"row": i + 2, "name": nm[:200], "name_en": en[:200], "category": (cell(row, cti) or cat)[:80],
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


def _run_row(c, oid, rid):
    r = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


MERGE_FIELDS = ("contact", "street", "zip", "city", "country", "address")


def _import_client(c, oid, uid, x, rid, ts, counts, merged, clean_client, made=None):
    from .contacts_cl import fk_add, fk_has_name, fk_sync
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
                raise BadInput(tr("Invalid value: {0}", "merge_id")) from None
        else:
            tid = made.get(x.get("contact_row"))
            if not tid:
                raise BadInput(tr("The client of row {0} is not imported", x.get("contact_row") if isinstance(x.get("contact_row"), int) else "?"))
        if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (tid,)).fetchone():
            raise BadInput(tr("Invalid value: {0}", "merge_id"))
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
    f = {k: x.get(k) for k in ("name", "contact", "street", "zip", "city", "country", "address") if x.get(k) is not None}
    if act == "merge":
        try:
            mid = int(x.get("merge_id"))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "merge_id")) from None
        cur = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (mid,)).fetchone()
        if not cur:
            raise BadInput(tr("Invalid value: {0}", "merge_id"))
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
        raise BadInput(tr("Invalid value: {0}", "action"))
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
    from ..team.clients import clean_client
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    lists = {k: b.get(k) or [] for k in FI_AREAS}
    if not all(isinstance(v, list) for v in lists.values()) or sum(len(v) for v in lists.values()) > 5 * FI_ROWS_MAX:
        raise BadInput(tr("Invalid data"))
    areas = bk_areas(b.get("areas"))  # 2.46.1 (#1557): only the areas switched on (absent: all); the others are not even checked
    lists = {k: v if k in areas else [] for k, v in lists.items()}
    rid = _run_new(c, oid, uid, "data")
    counts = {"clients": 0, "merged": 0, "contacts": 0, "services": 0, "equipment": 0, "skipped": 0, "services_filled": 0, "equipment_filled": 0,
              "roles": 0, "roles_filled": 0, "crew": 0, "crew_filled": 0}
    merged, filled = {}, {}
    made = {}
    ts = iso(now_utc())
    for x in lists["clients"]:
        try:
            _import_client(c, oid, uid, x, rid, ts, counts, merged, clean_client, made)
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
    c.execute("UPDATE office_import_runs SET counts=?, detail=? WHERE id=? AND org_id=?",
              (json.dumps(counts), json.dumps({"merged": merged, "filled": filled, "areas": list(areas)}), rid, oid))
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
        from ..core import config
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
                raise BadInput(tr("Row {0}: {1}", x.get("row") if isinstance(x.get("row"), int) else "?", tr("Invalid value: {0}", "action")))
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
            raise BadInput(tr("Invalid value: {0}", "action"))
        row = office_create(c, oid, kind, vals)
        c.execute(f"UPDATE {MD[kind]['table']} SET import_run_id=? WHERE id=? AND org_id=?", (rid, row["id"], oid))
        counts[kind] += 1


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
    return bool(c.execute("SELECT 1 FROM lists WHERE client_id=? LIMIT 1", (cid,)).fetchone()
                or c.execute("SELECT 1 FROM office_docs WHERE client_id=? AND org_id=? LIMIT 1", (cid, oid)).fetchone()
                or c.execute("SELECT 1 FROM office_contracts WHERE client_id=? AND org_id=? LIMIT 1", (cid, oid)).fetchone()
                or c.execute("SELECT 1 FROM office_archive WHERE client_id=? AND org_id=? AND (run_id IS NULL OR run_id!=?) LIMIT 1", (cid, oid, rid)).fetchone())


def fi_undo(c, oid, uid, rid, kinds=None):
    """Undoes run rid: removes its records nothing builds on; -> {removed: {...}, kept: {...}}. 409 when already undone.
    2.46.1 (#1557): kinds = only these areas of a data import (clients | services | equipment); the whole undo later
    takes the areas that are left."""
    write_lock(c, f"office_import_{int(oid)}")
    r = _run_row(c, oid, rid)
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
    removed = {"clients": 0, "services": 0, "equipment": 0, "archive": 0, "merged": 0, "contacts": 0, "filled": 0, "roles": 0, "crew": 0}
    kept = {"clients": 0, "services": 0, "equipment": 0, "roles": 0, "crew": 0}
    kept_ids = set()
    for row in (c.execute(f"SELECT id FROM clients WHERE {pb_cl_sql(c, oid)} AND import_run_id=?", (rid,)).fetchall() if "clients" in todo else []):
        if _client_used(c, oid, row["id"], rid):
            kept["clients"] += 1
            kept_ids.add(row["id"])
            continue
        c.execute(f"DELETE FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (row["id"],))
        removed["clients"] += 1
    s = office_settings(c, oid)
    sr_unfill(c, oid, detail, todo, removed)  # 2.47.0 (#1648): first, so a service lets go of the run's role
    for kind in ("services", "equipment", "roles", "crew"):  # 2.47.0 (#1649): roles after the services that point to them
        if kind not in todo:
            continue
        table = MD[kind]["table"]
        extra = " AND kind=?" if MD[kind].get("kind") else ""
        for row in c.execute(f"SELECT id FROM {table} WHERE org_id=? AND import_run_id=?{extra}", (oid, rid, *((MD[kind]["kind"],) if extra else ()))).fetchall():
            if office_in_use(c, kind, row["id"], oid) or (kind == "services" and s.get("producing_service_id") == row["id"]):
                kept[kind] += 1
                continue
            c.execute(f"DELETE FROM {table} WHERE id=? AND org_id=?", (row["id"], oid))
            removed[kind] += 1
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
    from .contacts_cl import fk_sync
    touched = set()
    kw = f"client_id IN (SELECT id FROM clients WHERE {pb_cl_sql(c, oid)})"  # 2.47.3 (#1360): also a personal office's (org_id NULL)
    for row in (c.execute(f"SELECT id, client_id FROM office_client_contacts WHERE {kw} AND import_run_id=?", (rid,)).fetchall()
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
    return removed, kept, files


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
    from .model import office_row
    try:
        return office_row(c, oid, kind, rid)
    except Denied:
        return None


def _unlink_files(oid, files):
    for f in files:
        p = fi_archive_path(oid, f)
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------- archive: file names, storage, numbers
DATE_PATTERNS = ((r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy"), (r"(\d{1,2})\.(\d{1,2})\.(\d{2})", "dmy2"),
                 (r"(\d{1,2})-(\d{1,2})-(\d{4})", "dmy"), (r"(\d{1,2})-(\d{1,2})-(\d{2})", "dmy2"), (r"(20\d{2})(\d{2})(\d{2})", "ymd"),
                 (r"(\d{2})(\d{2})(\d{2})", "ymd2"))


def fi_parse_date(s):
    s = (s or "").strip()
    for pat, kind in DATE_PATTERNS:
        m = re.fullmatch(pat, s)
        if not m:
            continue
        a, b_, c_ = (int(x) for x in m.groups())
        y, mo, d = {"ymd": (a, b_, c_), "dmy": (c_, b_, a), "dmy2": (2000 + c_, b_, a), "ymd2": (2000 + a, b_, c_)}[kind]
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
        out["sure"] = bool(out["date"])
    else:
        m = re.fullmatch(r"(?P<proj>[^_]+)_(?P<client>[^_]+)_(?P<title>.*?)_{2,}(?P<date>[^_]+)_(?:R|RE|Rechnung)", stem, re.I)
        if m:
            out.update(kind="invoice", project_no=m.group("proj"), client_name=m.group("client"), project=m.group("title").replace("_", " ").strip(),
                       date=fi_parse_date(m.group("date")))
            out["sure"] = bool(out["date"])
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
    cn = fi_norm(out["client_name"])
    if cn and len(cn) >= 3:
        best = None
        for cid, cname in clients:
            n = fi_norm(cname)
            if not n:
                continue
            if n == cn:
                best = (cid, cname)
                break
            if best is None and len(n) >= 4 and (n.startswith(cn) or cn.startswith(n)):
                best = (cid, cname)
        if best:
            out["client_id"] = best[0]
    return out


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
            try:
                d = Decimal(str(a).replace(",", ".")) if not isinstance(a, bool) else None
            except InvalidOperation:
                d = None
            if d is None or not d.is_finite() or abs(d) > Decimal("1e9"):
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
    if raw[:1024].find(b"%PDF-") < 0:
        raise BadInput(tr("Only PDF files can be archived"))
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
    from ..core.orgcrypt import oc_seal
    with os.fdopen(fd, "wb") as fh:
        fh.write(oc_seal(c, oid, raw))  # 2.42.0 (#828): sealed with the organisation's key at rest (sha256 = the original)
    c.execute("UPDATE office_archive SET file=? WHERE id=? AND org_id=?", (name, aid, oid))
    _run_count(c, oid, rid)
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
    if names is not None and r["client_id"]:
        d["client"] = names.get(r["client_id"]) or ""
    return d


def fi_archive_rows(c, oid, kind=""):
    names = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)}")}
    sql, args = "SELECT * FROM office_archive WHERE org_id=?", [oid]
    if kind in ("invoice", "offer"):
        sql += " AND kind=?"
        args.append(kind)
    return [_archive_public(r, names) for r in c.execute(sql + " ORDER BY date DESC, id DESC", args)]


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


FK_PDF_LINES = 45  # lines of the first page looked at


def fk_pdf_block(text, own):
    """The recipient block (list of lines) of a document's text, [] when none is found. own: the organisation's company
    fields (name, zip, city) -- their lines are the sender, not the recipient."""
    first = (text or "").split("\f")[0]
    lines = [re.sub(r"\s+", " ", x).strip() for x in first.replace("\r", "\n").split("\n")]
    lines = [x for x in lines if x][:FK_PDF_LINES]
    oname = fi_norm(own.get("name") or "")
    ozip, ocity = (own.get("zip") or "").replace(" ", ""), (own.get("city") or "").strip().lower()
    ostreet = _cname(own.get("street")).replace(" ", "")

    def own_line(ln):
        n = fi_norm(ln)
        return bool(oname) and len(oname) >= 4 and oname in n
    for i, ln in enumerate(lines):
        if not (FK_ZIPLINE_RE.match(ln) or (NL_ZIP_RE.match(ln) and i)) or len(ln) > 60 or FK_SENDER_RE.search(ln) or own_line(ln):
            continue
        m = ZIP_RE.match(ln)
        if m and ozip and m.group("zip") == ozip and m.group("city").strip().lower() == ocity and any(
                own_line(x) or (ostreet and _cname(x).replace(" ", "") == ostreet) for x in lines[max(0, i - 3):i]):
            continue  # the organisation's own address block (letterhead); a client in the same town stays
        top = i
        while top > 0 and i - top < 5:
            up = lines[top - 1]
            if FK_SENDER_RE.search(up) or FK_STOP_RE.search(up) and not ATTN_RE.match(up) or own_line(up) or len(up) > 70 or fk_value_line(up, (lines[top - 2] if top > 1 else "", lines[top])):
                break
            top -= 1
        if top == i:
            continue  # a postcode line without anything above it is no address
        block = lines[top:i + 1]
        if i + 1 < len(lines) and lines[i + 1].strip(" .").lower() in COUNTRIES:
            block.append(lines[i + 1])
        return block
    return []


def fk_pdf_address(c, oid, raw, uid, client_id=None):
    """-> {status: ok | no_text | none | busy | error, address?: split + reasons, client_id, client_name, new_client,
    add_contact, address_differs}."""
    from ..tasks.attachtext import pdf_text
    from .contacts_cl import fk_has_name
    from .ledger import ofx_company
    t = pdf_text(raw, owner=uid)
    if t.get("error"):
        return {"status": "busy" if t["error"] == "busy" else "error"}
    if t.get("no_text_layer"):
        return {"status": "no_text"}
    block = fk_pdf_block(t.get("text") or "", ofx_company(c, oid) or {})
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
    from ..team.clients import clean_client
    from .contacts_cl import fk_add, fk_has_name, fk_sync
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
    from .invoices import inv_manual_seq, inv_scheme
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
def _ctx(admin=True):
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=admin)
    return c, uid, oid


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
    """Org admin. multipart 'file' (.xlsx) -> the preview: clients (split address, reasons, duplicate), services,
    equipment, other sheets (counted only). Nothing is stored."""
    c, uid, oid = _ctx()
    _f, raw = _upload("file", FI_XLSX_MAX)
    return jsonify(fi_preview(c, oid, raw))


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
    from .ledger import ofx_log
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
    return jsonify(runs=out)


@app.post("/api/office/legacy/runs/<int:rid>/undo")
def fi_undo_post(rid):
    """Org admin. 2.46.1 (#1557): body {kinds: [clients | services | equipment]} = only these areas (none: the whole run)."""
    c, uid, oid = _ctx()
    kinds = (body() or {}).get("kinds")
    removed, kept, files = fi_undo(c, oid, uid, rid, kinds=kinds)
    from .ledger import ofx_log
    ofx_log(c, oid, "undo", target="legacy", detail={"run_id": rid, "removed": removed, "kept": kept, **({"kinds": kinds} if kinds else {})})
    bump(c)
    c.commit()
    _unlink_files(oid, files)  # after the commit: a failed undo keeps its files
    return jsonify(removed=removed, kept=kept)


@app.post("/api/office/legacy/archive/parse")
def fi_parse_post():
    """Org admin. {names: [file name, ...]} -> {items: [the key data each name suggests]} (nothing stored)."""
    c, uid, oid = _ctx()
    names = (body() or {}).get("names")
    if not isinstance(names, list) or len(names) > 500 or not all(isinstance(n, str) for n in names):
        raise BadInput(tr("Invalid data"))
    cl = [(r["id"], r["name"]) for r in c.execute(f"SELECT id, name FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0 ORDER BY id")]
    items = []
    for n in names:
        p = fi_parse_filename(n[:300], cl)
        p["taken"] = _number_used(c, oid, p["number"])
        items.append(p)
    return jsonify(items=items)


@app.post("/api/office/legacy/archive/address")
def fk_archive_address_post():
    """2.40.0 (#1421) org admin. multipart 'file' (PDF) + client_id? (the file name's proposal) -> the recipient's address
    read from the text layer of page 1 and the proposals (new client / contact person / address differs); nothing stored."""
    c, uid, oid = _ctx()
    f, raw = _upload("file", FI_PDF_MAX)
    if raw[:1024].find(b"%PDF-") < 0:
        raise BadInput(tr("Only PDF files can be archived"))
    try:
        cid = int(request.form.get("client_id") or 0) or None
    except ValueError:
        cid = None
    return jsonify(fk_pdf_address(c, oid, raw, uid, cid))


@app.post("/api/office/legacy/archive/run")
def fi_archive_run_post():
    """Org admin: opens an archive run (the uploads that follow carry its id; one run = one "undo")."""
    c, uid, oid = _ctx()
    rid = _run_new(c, oid, uid, "archive")
    c.execute("UPDATE office_import_runs SET counts=? WHERE id=? AND org_id=?", (json.dumps({"archive": 0}), rid, oid))
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
        c.commit()
    except BaseException:
        fk_archive_done(p, False)
        raise
    fk_archive_done(p, True)
    r = c.execute("SELECT * FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    return jsonify(_archive_public(r)), 201


@app.get("/api/office/legacy/archive")
def fi_archive_get():
    """Members read the archive (?kind=invoice|offer): the documents and the sums (all / paid)."""
    c, uid, oid = _ctx(admin=False)
    rows = fi_archive_rows(c, oid, request.args.get("kind") or "")
    tot = sum(Decimal(str(r["amount"])) for r in rows if r["amount"] is not None and r["kind"] == "invoice")
    paid = sum(Decimal(str(r["amount"])) for r in rows if r["amount"] is not None and r["kind"] == "invoice" and r["paid"])
    return jsonify(items=rows, sum_invoices=float(tot), sum_paid=float(paid), admin=office_role(c, uid, oid) == "admin")


@app.patch("/api/office/legacy/archive/<int:aid>")
def fi_archive_patch(aid):
    """Org admin: only the bookkeeping notes of an archived document (amount, paid, client); the PDF and its number stay."""
    c, uid, oid = _ctx()
    if not c.execute("SELECT 1 FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone():
        raise Denied(404)
    b = body() or {}
    f = _archive_fields(c, oid, {k: v for k, v in b.items() if k in ("amount", "paid", "client_id")}, partial=True)
    if f:
        c.execute(f"UPDATE office_archive SET {', '.join(k + '=?' for k in f)} WHERE id=? AND org_id=?", [*f.values(), aid, oid])
        from .ledger import ofx_log
        ofx_log(c, oid, "update", target="archive", detail={"archive_id": aid, "fields": sorted(f)})
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
    from .ledger import ofx_log
    ofx_log(c, oid, "pdf", target="archive", detail={"archive_id": aid}, dedupe_min=10)
    c.commit()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", r["file_name"] or "").strip("-") or f"archive-{aid}.pdf"
    from ..core.orgcrypt import oc_send_file
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
    """Org admin. {kind: invoice | offer, last} -> the counter continues after last (never lowered)."""
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
    c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,?) ON CONFLICT(org_id, kind, period) DO UPDATE SET last=excluded.last",
              (oid, kind, cur["period"], last))
    from .ledger import ofx_log
    ofx_log(c, oid, "number", target="legacy", detail={"kind": kind, "from": cur["last"], "to": last})
    c.commit()
    return jsonify(fi_counter(c, oid, kind))

