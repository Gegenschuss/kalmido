"""2.95.0 B (#1932): the import of a per diem spreadsheet (one sheet = one person, a row = a trip: from, to, start, end,
place, occasion, per diem; cell comments = note and the split by country). Two steps like office/fixedimport.py: preview
(nothing stored) and import (every row checked again by travel.rk_trip_clean), plus the undo of an import.
Every route: office_gate + office_org with the admin of the office area (travel._ctx).

Format: a header row with "Vom" / "bis" / "Start" / "Ende" / "Ort" / "Anlass" / "MVA" (also English names, VMI_HEAD);
dates as Excel date numbers or DD.MM.YYYY, times as a fraction of a day or HH:MM, the per diem as a number (a formula: its
stored value; never evaluated). The person: the title above the header ("... Arbeitsliste <name> - <year>") or the sheet's
name. A row "Summe" is the sheet's sum. A comment with lines "<country>: n x rate EUR + ... = sum EUR" (the per diem block)
gives the country of every day (the partial days on the first / last day, the full days of the countries in the block's
order in between); every other comment text goes into the trip's note. The rows are recalculated with vma.vma_trip and
compared with the spreadsheet's amount (status warn when they differ or there is no amount); nothing is ever guessed: a
hint of the spreadsheet (meals paid, an unknown change of country) stays a note."""
import io
import json
import lzma
import re
import zipfile
import zlib
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, iso, now_utc
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_enc_fields
from ..core.pg import insert_id
from ..core.errors import BadInput
from .calc import dstr, money
from .vma import VMA_HOME, VMA_NAMES, vma_dates, vma_places, vma_rate, vma_trip

VMI_FILE_MAX = 2 * 1024 * 1024
VMI_SHEETS_MAX = 30
VMI_ROWS_MAX = 500  # trip rows per sheet
VMI_IMPORT_MAX = 2000  # trips per import / per undo
VMI_HEAD = {  # normalised header (letters / digits only) -> field
    "vom": "date_from", "von": "date_from", "ab": "date_from", "datumvon": "date_from", "from": "date_from", "datefrom": "date_from",
    "abreise": "date_from", "bis": "date_to", "datumbis": "date_to", "to": "date_to", "until": "date_to", "dateto": "date_to",
    "rückkehr": "date_to", "rueckkehr": "date_to",
    "start": "t_start", "startzeit": "t_start", "beginn": "t_start", "abfahrt": "t_start", "starttime": "t_start",
    "ende": "t_end", "endzeit": "t_end", "end": "t_end", "ankunft": "t_end", "endtime": "t_end",
    "ort": "dest", "ziel": "dest", "reiseziel": "dest", "orte": "dest", "destination": "dest", "place": "dest",
    "anlass": "purpose", "zweck": "purpose", "reisezweck": "purpose", "purpose": "purpose", "occasion": "purpose",
    "mva": "vma", "vma": "vma", "verpflegungsmehraufwand": "vma", "verpflegungspauschale": "vma", "pauschale": "vma",
    "perdiem": "vma", "perdiems": "vma", "mealallowance": "vma",
}
VMI_ACQ = {"recherche/akquise", "akquise/recherche", "akquise", "recherche", "akquise / recherche", "recherche / akquise",
           "acquisition", "research", "acquisition/research", "research/acquisition"}
VMI_SUM_RE = re.compile(r"^(summe|gesamt|total|sum)\b", re.I)
VMI_TITLE_RE = re.compile(r"(?:arbeitsliste|reiseliste|reisen|liste|list|trips)\s+(?P<name>.+?)\s*[–—-]\s*(?P<year>\d{4})\s*$", re.I)
VMI_BLOCK_RE = re.compile(r"^\s*(?P<name>[^:\n]+?)\s*:\s*(?P<parts>\d+\s*[×xX*]\s*\d+(?:[.,]\d+)?\s*(?:€|EUR)?"
                          r"(?:\s*\+\s*\d+\s*[×xX*]\s*\d+(?:[.,]\d+)?\s*(?:€|EUR)?)*)\s*=\s*(?P<sum>\d[\d.,]*)\s*(?:€|EUR)?\s*$")
VMI_PART_RE = re.compile(r"(\d+)\s*[×xX*]\s*(\d+(?:[.,]\d+)?)")
VMI_BLOCK_HEAD_RE = re.compile(r"(auslands|inlands)?pauschal|per diem|land\s*=\s*wo", re.I)
VMI_REASONS = {
    "date": N_("Date missing or not readable"), "order": N_("The end is before the start"),
    "times": N_("Start and end time missing: no per diem"), "year": N_("No per diem rates for {0}"),
    "diff": N_("Differs from the spreadsheet"), "days": N_("The days in the comment do not match the period"),
    "country": N_("Country not recognised: {0}"), "rate": N_("Rate {0} not in the table for {1}"),
    "time": N_("Time not readable: {0}"), "dup": N_("Already there"),
}


# ---------------------------------------------------------------- reading the spreadsheet (cells + comments)
def vmi_comments(z, path, names, budget):
    """{(row 1-based, col 0-based): text} of the comments (notes) of a sheet part; the author's "Name:" prefix Excel puts
    in front is dropped. Read with the guards of legacyimport (_xml: size budget, no entities)."""
    from .legacyimport import _col_index, _local, _rels, _xml
    out = {}
    for t in _rels(z, path, budget).values():
        if t not in names or not re.search(r"/comments\d*\.xml$", t):
            continue
        root = _xml(z, t, budget)
        authors = [a.text or "" for a in root.iter() if _local(a.tag) == "author"]
        for cm in root.iter():
            if _local(cm.tag) != "comment":
                continue
            m = re.fullmatch(r"([A-Z]{1,3})(\d+)", cm.get("ref") or "")
            if not m:
                continue
            txt = "".join(x.text or "" for x in cm.iter() if _local(x.tag) == "t")
            txt = txt.replace("\r\n", "\n").replace("\r", "\n").strip()
            try:
                au = authors[int(cm.get("authorId") or 0)]
            except (ValueError, IndexError):
                au = ""
            if au and txt.startswith(au + ":"):
                txt = txt[len(au) + 1:].strip()
            if txt.startswith("[Threaded comment]"):
                txt = txt.split("\n", 1)[-1].strip()
            if txt:
                out[(int(m.group(2)), _col_index(m.group(1)))] = txt[:4000]
    return out


def vmi_xlsx(raw):
    """[{name, grid: [[cell text]], comments: {(row, col): text}}] of every sheet (in the workbook's order). BadInput for
    anything that is not a readable .xlsx or has more than VMI_SHEETS_MAX sheets."""
    from .legacyimport import _local, _rels, _sheet, _xml, _in_rph
    bad = tr("This is not a spreadsheet file (.xlsx)")
    if not raw.startswith(b"PK"):
        raise BadInput(bad)
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
    except (zipfile.BadZipFile, ValueError):
        raise BadInput(bad) from None
    if "xl/workbook.xml" not in names or len(names) > 2000:
        raise BadInput(bad)
    budget = [0]
    try:
        strings = []
        if "xl/sharedStrings.xml" in names:
            for si in _xml(z, "xl/sharedStrings.xml", budget):
                if _local(si.tag) == "si":
                    strings.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t" and not _in_rph(si, t)))
        wb = _xml(z, "xl/workbook.xml", budget)
        wrels = _rels(z, "xl/workbook.xml", budget)
        sheets = [sh for sh in wb.iter() if _local(sh.tag) == "sheet"]
        if len(sheets) > VMI_SHEETS_MAX:
            raise BadInput(tr("Too many sheets (at most {0})", VMI_SHEETS_MAX))
        out = []
        for sh in sheets:
            rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
            path = wrels.get(rid)
            if not path or path not in names:
                continue
            out.append({"name": (sh.get("name") or "").strip(), "grid": _sheet(z, path, strings, budget),
                        "comments": vmi_comments(z, path, names, budget)})
        return out
    # 2.95.0 (review): an encrypted / exotically packed zip (RuntimeError, NotImplementedError, OSError, LZMAError) -> 400 too
    except (ET.ParseError, KeyError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError, OSError,
            lzma.LZMAError):  # broken file -> 400, not 500
        raise BadInput(bad) from None


# ---------------------------------------------------------------- cells
def vmi_norm(s):
    return re.sub(r"[^0-9a-zäöüß]", "", str(s or "").lower())


def vmi_date(v):
    """An Excel date number ('45714', also with a time fraction), DD.MM.YYYY / DD.MM.YY or YYYY-MM-DD -> 'YYYY-MM-DD' or None."""
    s = str(v or "").strip()
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{4,6}(\.\d+)?", s):
            f = float(s)
            if 1 <= f < 2958466:
                return (date(1899, 12, 30) + timedelta(days=int(f))).isoformat()
            return None
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", s)
        if m:
            y = int(m.group(3))
            return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1))).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except (ValueError, OverflowError):
        return None
    return None


def vmi_time(v):
    """A fraction of a day ('0.375', also a date number with a time) or 'H:MM' / 'HH.MM' (also '8:00 Uhr') -> 'HH:MM';
    '' when empty; None when not readable."""
    s = str(v or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d+(\.\d+)?([eE]-?\d+)?", s):
        try:
            f = float(s)
        except ValueError:
            return None
        mins = round((f % 1) * 1440)
        if mins >= 1440:
            mins = 1439
        return f"{mins // 60:02d}:{mins % 60:02d}"
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?::\d{2})?\s*(?:uhr|h)?", s, re.I)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def vmi_num(v):
    """The per diem cell -> Decimal or None ('372', '372.5', '372,50 €')."""
    s = re.sub(r"[\s  €]|EUR", "", str(v or ""))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() and abs(d) < 10 ** 7 else None


def _clean(v, n):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()[:n]


# ---------------------------------------------------------------- the per diem block of a comment
_NAMES = {}


def vmi_country(name):
    """A country's name (German, English or the BMF letter's own name; "Inland" = Germany) -> (ISO code, place) or None.
    "Schweiz (Genf)" -> ("CH", "Genf")."""
    if not _NAMES:
        for code, ns in VMA_NAMES.items():
            for n in ns:
                if n:
                    _NAMES.setdefault(n.casefold(), code)
        for n in ("inland", "deutschland", "germany", "domestic"):
            _NAMES[n] = "DE"
    s = " ".join(str(name or "").split()).strip(" .")
    place = ""
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", s)
    if m and m.group(1).casefold() in _NAMES:
        s, place = m.group(1), m.group(2).strip()
    code = _NAMES.get(s.casefold())
    return (code, place) if code else None


def vmi_block(text):
    """(entries [{name, code, place, parts: [(n, rate)]}], the rest of the text) of a comment: the lines of the per diem
    block (and its heading line) are taken out, every other line stays."""
    entries, rest = [], []
    for ln in str(text or "").split("\n"):
        m = VMI_BLOCK_RE.match(" ".join(ln.split())[:400])  # review: single spaces, a short line -> no long backtracking
        if m:
            cp = vmi_country(m.group("name"))
            entries.append({"name": m.group("name").strip(), "code": cp[0] if cp else None, "place": cp[1] if cp else "",
                            "parts": [(int(n), Decimal(r.replace(",", "."))) for n, r in VMI_PART_RE.findall(m.group("parts"))]})
            continue
        rest.append(ln)
    if entries:  # the heading of the block ("Auslandspauschalen 2025 (BMF ...), Land = wo man vor 24 Uhr war:")
        rest = [ln for ln in rest if not (VMI_BLOCK_HEAD_RE.search(ln) and ln.rstrip().endswith(":"))]
    return entries, "\n".join(x for x in rest if x.strip()).strip()


def _rate_place(year, code, rate, want=""):
    """(place, kind full|partial) of the year's table where the country's rate equals rate (the named place first, then
    "im Uebrigen", then the cities), or None."""
    if code == "DE":
        f, p = VMA_HOME.get(year, (None, None))
        return ("", "full") if rate == f else ("", "partial") if rate == p else None
    places = (vma_places(year) or {}).get(code)
    if not places:
        r = vma_rate(year, code, want)  # alias / Luxembourg: the rate of another country
        if not r:
            return None
        return ("", "full") if rate == r[0] else ("", "partial") if rate == r[1] else None
    order = ([want] if want in places else []) + [p for p in places if p != want]
    for p in order:
        f, pt = vma_rate(year, code, p)[:2]
        if rate == f:
            return p, "full"
        if rate == pt:
            return p, "partial"
    return None


def vmi_days(ds, entries, year):
    """The country of every day from the block: [(code, place)] per date (or None), plus reasons [(key, arg)]. The partial
    days go to the first / last day, the full days of the countries in the block's order in between."""
    part, full, why = [], [], []
    for e in entries:
        if not e["code"]:
            why.append(("country", e["name"]))
            continue
        for n, rate in e["parts"]:
            rp = _rate_place(year, e["code"], rate, e["place"])
            if rp is None:
                why.append(("rate", (f"{dstr(rate)} €".replace(".00 ", " "), e["name"])))
                rp = (e["place"], "full")
            (part if rp[1] == "partial" else full).extend([(e["code"], rp[0])] * min(n, 400))
    if not part and not full:
        return None, why
    if len(ds) == 1:
        seq = (part + full)[:1]
        if len(part) + len(full) != 1:
            why.append(("days", None))
    else:
        seq = part[:1] + full + part[1:]
        if len(seq) != len(ds) or len(part) > 2 or (len(part) < 2 and full):
            why.append(("days", None))
        while len(seq) < len(ds):
            seq.append(seq[-1])
        seq = seq[:len(ds)]
    return seq, why


def vmi_place_country(dest):
    """The country named in brackets in the place ("Chania, Kreta (Griechenland)") -> ISO code or ''."""
    for x in re.findall(r"\(([^()]+)\)", dest or ""):
        cp = vmi_country(x)
        if cp:
            return cp[0]
    return ""


# ---------------------------------------------------------------- a sheet -> trips
def vmi_person(sheet, grid, hi, known):
    """The sheet's person: the name in the title above the header ("Reise - Arbeitsliste <name> - 2025"), else the sheet's
    name -> {id, name} of a person of the office with the same name (case and spaces ignored) or {name}."""
    name = ""
    for row in grid[:hi]:
        for v in row:
            m = VMI_TITLE_RE.search(str(v or ""))
            if m:
                name = m.group("name")
                break
        if name:
            break
    name = _clean(" ".join((name or sheet).split()), 120)
    key = name.casefold()
    for p in known:
        if " ".join(str(p["name"] or "").split()).casefold() == key:
            return {"id": p["id"], "name": p["name"]}
    return {"name": name}


def vmi_pkey(p):
    return f"u{p['id']}" if p.get("id") else "n:" + " ".join(str(p.get("name") or "").split()).casefold()


def vmi_trip_key(pk, df, dt, dest):
    return (pk, df, dt or df, " ".join(str(dest or "").split()).casefold())


def vmi_sheet(sh, known, seen):
    """One sheet -> {sheet, person, rows, sum_excel, sum_calc, counts} or None (no header row: not a trip list)."""
    grid, com = sh["grid"], sh["comments"]
    cols, hi = None, 0
    for i, row in enumerate(grid[:20]):
        m = {}
        for j, cell in enumerate(row):
            f = VMI_HEAD.get(vmi_norm(cell))
            if f and f not in m:
                m[f] = j
        if "date_from" in m and "dest" in m:
            cols, hi = m, i
            break
    if cols is None:
        return None
    person = vmi_person(sh["name"], grid, hi, known)
    pk = vmi_pkey(person)

    def cell(r, f):
        j = cols.get(f)
        return str(r[j]).strip() if j is not None and j < len(r) and r[j] is not None else ""

    out, sum_excel = [], None
    body_rows = [(hi + 2 + k, r) for k, r in enumerate(grid[hi + 1:])]
    if sum(1 for _, r in body_rows if any(str(x).strip() for x in r)) > VMI_ROWS_MAX + 5:
        raise BadInput(tr("Too many rows (at most {0})", VMI_ROWS_MAX))
    for no, r in body_rows:
        if not any(str(x).strip() for x in r):
            continue
        df_s = cell(r, "date_from")
        if not df_s and any(VMI_SUM_RE.match(str(x).strip()) for x in r):
            sum_excel = vmi_num(cell(r, "vma"))
            continue
        notes, entries = [], []
        for j in sorted({c for (rr, c) in com if rr == no}):
            ent, rest = vmi_block(com[(no, j)])
            entries += ent
            if rest:
                notes.append(rest)
        dest = _clean(cell(r, "dest"), 300)
        occ = _clean(cell(r, "purpose"), 200)
        acq = " ".join(occ.split()).casefold() in VMI_ACQ
        excel = vmi_num(cell(r, "vma"))
        row = {"row": no, "date_from": "", "date_to": "", "t_start": "", "t_end": "", "dest": dest,
               "purpose": "acquisition" if acq else "job", "project": "" if acq else occ, "overnight": 0,
               "note": _clean("\n\n".join(notes), 2000), "country": "", "place": "", "vma_days": [],
               "excel": dstr(money(excel)) if excel is not None else None, "amount": None, "lines": [],
               "status": "error", "reasons": [], "sel": False}
        df, dt = vmi_date(df_s), vmi_date(cell(r, "date_to")) if cell(r, "date_to") else None
        if df and not dt and not cell(r, "date_to"):
            dt = df
        if not df or not dt:
            row["reasons"].append(tr(VMI_REASONS["date"]))
            out.append(row)
            continue
        if dt < df:
            row.update(date_from=df, date_to=dt)
            row["reasons"].append(tr(VMI_REASONS["order"]))
            out.append(row)
            continue
        ds = vma_dates(df, dt)
        if not ds:
            row["reasons"].append(tr(VMI_REASONS["date"]))
            out.append(row)
            continue
        why = []
        for k in ("t_start", "t_end"):
            t = vmi_time(cell(r, k))
            if t is None:
                why.append(tr(VMI_REASONS["time"], cell(r, k)[:20]))
                t = ""
            row[k] = t
        row.update(date_from=df, date_to=dt, overnight=1 if dt > df else 0)
        seq, bw = vmi_days(ds, entries, int(df[:4])) if entries else (None, [])
        for k, a in bw:
            why.append(tr(VMI_REASONS[k], *(a if isinstance(a, tuple) else (a,) if a is not None else ())))
        if seq:
            base = Counter(seq).most_common(1)[0][0]
            row["country"], row["place"] = ("" if base[0] == "DE" else base[0]), base[1]
            row["vma_days"] = [dict({"date": d, "country": c}, **({"place": p} if p else {})) for d, (c, p) in zip(ds, seq) if (c, p) != base]
        else:
            row["country"] = vmi_place_country(dest)
        v = vma_trip({k: row[k] for k in ("date_from", "date_to", "country", "place", "t_start", "t_end", "overnight", "vma_days")})
        row["amount"], row["lines"] = v["amount"], v["lines"]
        for h in v["hints"]:
            if h["key"] == "times":
                why.append(tr(VMI_REASONS["times"]))
            elif h["key"] == "year":
                why.append(tr(VMI_REASONS["year"], h["year"]))
        if row["amount"] != row["excel"] and not (row["amount"] is None and row["excel"] is None):
            why.append(tr(VMI_REASONS["diff"]))
        key = vmi_trip_key(pk, df, dt, dest)
        if key in seen:
            row.update(status="dup", reasons=[tr(VMI_REASONS["dup"])] + why, sel=False)
        else:
            row.update(status="warn" if why else "new", reasons=why, sel=True)
        seen.add(key)
        out.append(row)
    if len(out) > VMI_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", VMI_ROWS_MAX))
    calc = sum((Decimal(x["amount"]) for x in out if x["status"] != "error" and x["amount"] is not None), Decimal(0))
    if sum_excel is None:
        sum_excel = sum((Decimal(x["excel"]) for x in out if x["excel"] is not None), Decimal(0))
    return {"sheet": sh["name"][:100], "person": person, "rows": out, "sum_excel": dstr(money(sum_excel)), "sum_calc": dstr(money(calc)),
            "counts": {s: sum(1 for x in out if x["status"] == s) for s in ("new", "warn", "dup", "error")}}


def vmi_parse(raw, known, seen):
    """The preview without the database: known = the people of the office [{id, name}], seen = the keys (vmi_trip_key) of
    the trips the office already has (filled while reading, so a trip twice in the file is a dup the second time)."""
    sheets = [s for s in (vmi_sheet(sh, known, seen) for sh in vmi_xlsx(raw)) if s]
    if not sheets:
        raise BadInput(tr("No header row with the columns From and Place found"))
    counts = {k: sum(s["counts"][k] for s in sheets) for k in ("new", "warn", "dup", "error")}
    return {"sheets": sheets, "counts": counts}


# ---------------------------------------------------------------- routes
def vmi_seen(c, oid):
    """The keys of the trips the office has: one per participant (a trip without participants: 'none')."""
    from .travel import rk_trips
    out = set()
    for t in rk_trips(c, oid):
        for p in (t["people"] or [{}]):
            out.add(vmi_trip_key(vmi_pkey(p) if p else "none", t["date_from"], t["date_to"], t["dest"]))
    return out


@app.post("/api/office/trips/import/preview")
def vmi_preview_post():
    """Office admin. multipart 'file' (.xlsx up to 2 MB, at most 30 sheets / 500 rows each) -> {sheets: [{sheet, person,
    rows: [{row, date_from, date_to, t_start, t_end, dest, purpose, project, overnight, note, country, place, vma_days,
    excel, amount, lines, status new|warn|dup|error, reasons, sel}], sum_excel, sum_calc, counts}], counts, people}.
    Nothing is stored."""
    from .legacyimport import _upload
    from .travel import _ctx, rk_people
    c, uid, oid = _ctx()
    _f, raw = _upload("file", VMI_FILE_MAX)
    known = rk_people(c, oid, uid)
    out = vmi_parse(raw, known, vmi_seen(c, oid))
    out["people"] = known
    from .travel import rka_purposes  # 2.117.0 A (#2292): an occasion named like an own purpose becomes that purpose
    own = {p["name"].casefold(): p["name"] for p in rka_purposes(c, oid)}
    for sh in out.get("sheets") or []:
        for r in sh.get("rows") or []:
            n = own.get(" ".join((r.get("project") or "").split()).casefold()) if r.get("purpose") == "job" else None
            if n:
                r["purpose"], r["project"] = n, ""
    return jsonify(out)


VMI_FIELDS = ("date_from", "date_to", "dest", "overnight", "people", "purpose", "project", "note", "country", "place", "t_start",
              "t_end", "vma_days")


@app.post("/api/office/trips/import")
def vmi_import_post():
    """Office admin. {trips: [{date_from, date_to, dest, overnight, people, purpose, project, note, country, place, t_start,
    t_end, vma_days}]} -> 201 {created, ids}. Every trip checked again by rk_trip_clean (only these fields; no client, no
    receipts); all or nothing: one bad trip = 400 with its number."""
    from .ledger import ofx_log
    from .travel import _ctx, rk_trip_clean
    c, uid, oid = _ctx()
    b = body()
    trips = b.get("trips") if isinstance(b, dict) else None
    if not isinstance(trips, list) or not trips:
        raise BadInput(tr("Invalid data"))
    if len(trips) > VMI_IMPORT_MAX:
        raise BadInput(tr("Too many rows (at most {0})", VMI_IMPORT_MAX))
    rows = []
    for i, t in enumerate(trips):
        if not isinstance(t, dict):
            raise BadInput(tr("Invalid data"))
        try:
            rows.append(rk_trip_clean(c, oid, uid, {k: t.get(k) for k in VMI_FIELDS}))
        except BadInput as x:
            raise BadInput(tr("Row {0}: {1}", i + 1, str(x.args[0] if x.args else x))) from None
    from .periodlock import period_need_open
    period_need_open(c, oid, *[d for r in rows for d in (r.get("date_from"), r.get("date_to"))])  # 2.148.0 A (#2471)
    ts, ids = iso(now_utc()), []
    from .travel import rka_purposes_adopt
    rka_purposes_adopt(c, oid, uid, [r["purpose"] for r in rows])  # 2.117.0 A (#2292): unknown purposes become own ones
    for row in rows:
        row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
        row = oc_enc_fields(c, oid, "office_trips", row)
        ids.append(insert_id(c, f"INSERT INTO office_trips({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ofx_log(c, oid, "import", target="trips", detail={"count": len(ids)})
    bump(c)
    c.commit()
    return jsonify(created=len(ids), ids=ids), 201


@app.post("/api/office/trips/delete")
def vmi_delete_many():
    """Office admin. {ids: [...]} -> deletes these trips of the office (the undo of an import: one step) with their
    receipts; a trip with a receipt billed on to a client stays (skipped). Answers the deleted trips as they were."""
    from .travel import _ctx, rk_trips
    c, uid, oid = _ctx()
    b = body()
    ids = b.get("ids") if isinstance(b, dict) else None
    if not isinstance(ids, list) or len(ids) > VMI_IMPORT_MAX or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid data"))
    ids = sorted(set(ids))
    if not ids:
        return jsonify(ok=True, deleted=0, trips=[], skipped=[])
    q = ",".join("?" * len(ids))
    mine = {r[0] for r in c.execute(f"SELECT id FROM office_trips WHERE org_id=? AND id IN ({q})", [oid] + ids)}
    billed = {r[0] for r in c.execute(f"SELECT DISTINCT trip_id FROM office_trip_items WHERE org_id=? AND billed_doc_id IS NOT NULL "
                                      f"AND trip_id IN ({q})", [oid] + ids)}
    gone = sorted(mine - billed)
    from .travel import _trip, _trip_need_open
    for i in gone:
        _trip_need_open(c, oid, _trip(c, oid, i))  # 2.148.0 A (#2471)
    old = [t for i in gone for t in rk_trips(c, oid, trip_id=i)]
    if gone:
        c.execute(f"DELETE FROM office_trip_items WHERE org_id=? AND trip_id IN ({','.join('?' * len(gone))})", [oid] + gone)
        c.execute(f"DELETE FROM office_trips WHERE org_id=? AND id IN ({','.join('?' * len(gone))})", [oid] + gone)
    bump(c)
    c.commit()
    return jsonify(ok=True, deleted=len(gone), trips=old, skipped=sorted(mine & billed))
