"""2.414.0 (#3502): the booking archive -- the complete DATEV data of past years, read-only, next to the bookkeeping.

What the tax advisor exports per year comes in as it is (one or more files, also one ZIP with all of them, a ZIP inside it
once more): the booking batch (EXTF / DTVF category 21: EVERY booking line, unchanged, raw columns by name in raw), the
labels of the ledger accounts (category 20), the debtors / creditors (category 16: the DATEV import's own plan of
office/datevimp.py, as a run of its own that the archive run undoes with it; their names label the person accounts) and
the receipt images of the DATEV XML interface (document.xml + files; linked to the bookings by the GUID of their
Beleglink BEDI "<GUID>"). Every original file lies unchanged (sealed with the office's key) in the office's folder
(OFFICE_DIR/<office>/bka-<16 hex>.<ext>) with its SHA-256; the same file or the same batch content a second time is
recognised (the preview says so, the import leaves it out).

The archive is a world of its own: nothing here flows into the EUeR, the VAT figures, the reserve or the cash flow
(office/books.py, kpi.py, cashflow.py never read these tables; a test checks it), nothing can be changed, nothing is booked
anew. The view: years, bookings with filters (account, counter account, either side, period, amount, receipt field, text),
sums per account and year, the receipt image of a booking, the original files. The GoBD export (office/gobdexport.py) takes
the bookings of the chosen period along.

Flow like the other imports: POST .../check = the preview (counts per year, debit = credit control, nothing written), POST
.../import = one run in office_import_runs (kind "datev_archive"), POST .../runs/<id>/undo removes everything of the run
(the files after the commit). Office admins only (a personal office: its owner; groups: the area "books"), never agents
(office_gate). Retention: 10 years from the end of the archived year (core/retention.py RET_LEGAL_YEARS "book", also the
receipt images: the careful side), then deleted for good (ba_retention_tick, the watchdog; only while ret_on("trash"))."""
import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from flask import jsonify, request

from ..core.config import OFFICE_DIR, app
from ..core.access import Denied
from ..core.db import bump, iso, local_now, now_utc
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields, oc_send_file, oc_seal
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.retention import RET_LEGAL_YEARS, ret_due, ret_on, ret_report
from ..core.zipread import ZipLimit, is_zip, zip_read, base_name
from ..personal.timetrack import BadInput
from .model import office_ctx, office_need_feature
from .rights import ofr_allows
from .ledger import ofx_log
from .datevimp import _amount, _day, _person, di_decode, di_import, di_parse, di_plan, di_undo

BA_KIND = "datev_archive"            # office_import_runs.kind
BA_FILE_MAX = 60 * 1024 * 1024       # one booking batch / one receipt image
BA_ROWS_MAX = 250000                 # booking lines of one batch
BA_TOTAL_MAX = 400 * 1024 * 1024     # all files of one ZIP, unpacked
BA_ENTRIES_MAX = 30000               # entries of one ZIP
BA_LIST_MAX = 500                    # bookings per page of the list
BA_PREVIEW = 20                      # names per list of the preview
BA_INS = 1000                        # rows per INSERT batch
BA_VERSIONS = {16: range(1, 6), 20: range(1, 6), 21: range(2, 14)}
BA_COLS = {
    "account": ("konto",),
    "counter": ("gegenkontoohnebuschlüssel", "gegenkonto"),
    "amount": ("umsatzohnesollhabenkz", "umsatz"),
    "side": ("sollhabenkennzeichen",),
    "currency": ("wkzumsatz",),
    "bu": ("buschlüssel",),
    "day": ("belegdatum",),
    "doc1": ("belegfeld1",),
    "doc2": ("belegfeld2",),
    "text": ("buchungstext",),
    "link": ("beleglink",),
    "label": ("kontenbeschriftung", "beschriftung"),
}
BA_NEED = {20: ("account", "label"), 21: ("account", "amount", "side", "day")}
BA_DOC_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff")
BA_DOC_MIME = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif"}
BA_TABLES = ("office_bookarch", "office_bookarch_accts", "office_bookarch_docs", "office_bookarch_files")

BA_NOTE = N_("No tax advice. Whether this archive replaces the DATEV data access for the retention, your tax advisor clarifies.")
BA_DUP = N_("Already in the archive (import of {0})")
BA_DUP_UPLOAD = N_("The same file twice in this upload")
BA_UNKNOWN = N_("Not a DATEV file this archive reads")
BA_NO_YEAR = N_("The year of the batch cannot be read")
BA_ROW_BAD = N_("{0} lines without a readable amount, debit / credit mark or account (only in the original file)")
BA_NOTHING = N_("Nothing to take over")

_GUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_FILE = re.compile(r"bka-[0-9a-f]{16}\.(csv|xml|pdf|jpg|png|tif)")


# ---------------------------------------------------------------- files
def ba_path(oid, name):
    """The stored file name of the archive below the office's folder, None when it is no name of the archive / missing."""
    if not name or not _FILE.fullmatch(name):
        return None
    p = os.path.join(OFFICE_DIR, str(int(oid)), name)
    return p if os.path.isfile(p) else None


def _mime(data):
    h = bytes(data[:8])
    if h.startswith(b"%PDF-"):
        return "application/pdf"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return None


class _Store:
    """The files of one import: written as "<name>.part" before the commit, renamed after it (done(True)) or removed (done(False))
    -- a bka-* file never exists without its row."""
    def __init__(self, c, oid):
        self.c, self.oid, self.parts = c, oid, []
        self.dir = os.path.join(OFFICE_DIR, str(int(oid)))

    def put(self, data, ext):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        name = f"bka-{uuid.uuid4().hex[:16]}{ext}"
        p = os.path.join(self.dir, name)
        fd = os.open(p + ".part", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.parts.append(p)
        with os.fdopen(fd, "wb") as fh:
            fh.write(oc_seal(self.c, self.oid, data, fresh=True))  # sealed with the office's key at rest (sha256 = the original)
        return name

    def done(self, ok):
        for p in self.parts:
            try:
                if ok:
                    os.replace(p + ".part", p)
                else:
                    os.unlink(p + ".part")
            except OSError:
                pass


def ba_unlink(oid, names):
    for n in names:
        p = ba_path(oid, n)
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------- reading the upload
def _unpack(items, with_docs, depth=0, left=None):
    """[(name, bytes)] of the upload -> ([(name, bytes)] files, [names] receipt files left unread (check), [errors]).
    left: the unpacked bytes still allowed, shared by every level (review F1: a ZIP in a ZIP never doubles the budget)."""
    out, names, errors = [], [], []
    left = left if left is not None else [BA_TOTAL_MAX]
    exts = (".csv", ".txt", ".xml", ".zip") + (BA_DOC_EXT if with_docs else ())
    for name, data in items:
        if is_zip(name, data) and depth < 2:
            try:
                z = zip_read(data, exts, BA_FILE_MAX, max(1, left[0]), BA_ENTRIES_MAX, BA_ENTRIES_MAX)
            except ZipLimit as e:
                raise BadInput(str(e)) from None
            left[0] -= z.size
            errors += [{"file": x["file"] or name, "error": x["error"]} for x in z.errors]
            names += [n for n in z.skipped if n.casefold().endswith(BA_DOC_EXT)]
            f, n, e = _unpack(z.files, with_docs, depth + 1, left)
            out, names, errors = out + f, names + n, errors + e
        elif is_zip(name, data):
            errors.append({"file": name, "error": tr("The ZIP file cannot be read")})
        else:
            out.append((name, data))
    return out, names, errors


def _docs_xml(data):
    """document.xml of the DATEV XML interface -> [(guid, file name)] (no DOCTYPE / ENTITY: refused before parsing)."""
    text = di_decode(data)
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise BadInput(tr("The file contains a DOCTYPE or an ENTITY and is not read"))
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)  # review F5: decoded already (a declared windows-1252 is no UTF-8 for the parser)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return None
    out, seen = [], False
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "document":
            continue
        seen = True
        g = _GUID.search(el.get("guid") or "")
        if not g:
            continue
        for x in el.iter():
            if x.tag.rsplit("}", 1)[-1] == "extension" and x.get("name"):
                out.append((g.group(0).lower(), base_name(x.get("name"))))
    return out if seen else None  # review F10: an XML without <document> is no document.xml


def _guid(link):
    m = _GUID.search(link or "")
    return m.group(0).lower() if m else ""


def _cell(p, r, key):
    i = p["cols"].get(key)
    return r[i] if i is not None and i < len(r) else ""


def _period_from(p):
    s = re.sub(r"\D", "", p["head"][14] if len(p["head"]) > 14 else "")
    try:
        return datetime.strptime(s, "%Y%m%d").date() if len(s) == 8 else None
    except ValueError:
        return None


def _batch(p):
    """A booking batch -> {year, rows [booking dicts], bad, debit, credit, no_counter, first, last}."""
    pf = _period_from(p)
    year = (p["fy_start"] or pf).year if (p["fy_start"] or pf) else None
    names = p["names"]
    rows, bad, debit, credit, no_ctr, ls, lh = [], 0, Decimal(0), Decimal(0), 0, Decimal(0), Decimal(0)
    for i, r in enumerate(p["rows"]):
        acct, ctr = re.sub(r"\s+", "", _cell(p, r, "account"))[:12], re.sub(r"\s+", "", _cell(p, r, "counter"))[:12]
        side, amt = _cell(p, r, "side").strip().upper()[:1], _amount(_cell(p, r, "amount"))
        if amt is None or side not in ("S", "H") or not acct:
            bad += 1
            continue
        if amt < 0:
            amt, side = -amt, ("H" if side == "S" else "S")
        d = _day(_cell(p, r, "day"), p["fy_start"], pf)
        raw = {str(names[k]).strip()[:80]: v for k, v in enumerate(r) if k < len(names) and str(v).strip() and str(names[k]).strip()}
        rows.append({"line": i + 3, "day": d.isoformat() if d else "", "account": acct, "counter": ctr, "side": side, "amount": amt,
                     "currency": (_cell(p, r, "currency").strip().upper() or "EUR")[:3], "bu": _cell(p, r, "bu").strip()[:4],
                     "doc1": _cell(p, r, "doc1").strip()[:36], "doc2": _cell(p, r, "doc2").strip()[:12],
                     "text": _cell(p, r, "text").strip()[:200], "link": _guid(_cell(p, r, "link")), "raw": json.dumps(raw, ensure_ascii=False)})
        # the control: every line books on its account AND on its counter account (the other side); a line without counter
        # account books one side only -> debit != credit. ls / lh: the sums of the lines marked S / H (review F4: shown too)
        if side == "S":
            debit += amt
            ls += amt
        else:
            credit += amt
            lh += amt
        if ctr:
            if side == "S":
                credit += amt
            else:
                debit += amt
        else:
            no_ctr += 1
    if year is None:
        days = sorted(x["day"] for x in rows if x["day"])
        year = int(days[0][:4]) if days else None
    days = sorted(x["day"] for x in rows if x["day"])
    return {"year": year, "rows": rows, "bad": bad, "debit": debit, "credit": credit, "no_counter": no_ctr, "lines_s": ls, "lines_h": lh,
            "first": days[0] if days else "", "last": days[-1] if days else ""}


def _content_key(year, rows):
    h = hashlib.sha256(str(year).encode())
    for x in sorted(rows, key=lambda x: (x["day"], x["account"], x["counter"], x["side"], str(x["amount"]), x["doc1"], x["text"], x["line"])):
        h.update(json.dumps([x["day"], x["account"], x["counter"], x["side"], str(x["amount"]), x["doc1"], x["doc2"], x["text"], x["bu"]],
                            ensure_ascii=False).encode())
    return h.hexdigest()


def _cents(v):
    return format(Decimal(str(v or 0)).quantize(Decimal("0.01")), "f")


def ba_plan(c, oid, uid, items, with_docs):
    """The plan of an upload [(name, bytes)]: {files [{name, kind, year, rows, reason, ...}], batches, labels, masters, docs,
    years {year: {...}}, errors}. Nothing is written."""
    files, left, errors = _unpack(items, with_docs)
    known = {r["sha256"]: r["run_id"] for r in c.execute(
        "SELECT f.sha256, f.run_id FROM office_bookarch_files f JOIN office_import_runs r ON r.id=f.run_id "
        "WHERE f.org_id=? AND r.undone_at IS NULL", (oid,))}
    known_ck = {r["content_key"]: r["run_id"] for r in c.execute(
        "SELECT f.content_key, f.run_id FROM office_bookarch_files f JOIN office_import_runs r ON r.id=f.run_id "
        "WHERE f.org_id=? AND r.undone_at IS NULL AND f.content_key<>''", (oid,))}
    runs = {r["id"]: r["created_at"] for r in c.execute("SELECT id, created_at FROM office_import_runs WHERE org_id=? AND kind=?", (oid, BA_KIND))}
    plan = {"files": [], "batches": [], "labels": [], "masters": [], "docs": [], "doc_files": {}, "years": {}, "errors": errors}
    seen, xmls, images = set(), [], {}
    for name, data in files:
        name = base_name(name) or "file"
        low = name.casefold()
        sha = hashlib.sha256(data).hexdigest()
        if low.endswith(BA_DOC_EXT):
            images.setdefault(low, (name, data))
            continue
        item = {"name": name, "kind": "", "year": None, "rows": 0, "reason": "", "sha256": sha, "bytes": len(data)}
        plan["files"].append(item)
        if low.endswith(".xml"):
            entries = _docs_xml(data)
            if entries is None:
                item.update(kind="unknown", reason=tr(BA_UNKNOWN))
                continue
            item.update(kind="docs", rows=len(entries))
            xmls.append((item, data, entries))
            continue
        if sha in seen:
            item.update(kind="duplicate", reason=tr(BA_DUP_UPLOAD))
            continue
        seen.add(sha)
        if sha in known:
            item.update(kind="duplicate", reason=tr(BA_DUP, _when(runs.get(known[sha]))))
            continue
        try:
            p = di_parse(data, BA_VERSIONS, BA_COLS, BA_NEED, BA_FILE_MAX, BA_ROWS_MAX)
        except Denied as e:
            item.update(kind="unknown", reason=e.text())
            continue
        except BadInput as e:
            item.update(kind="unknown", reason=str(e) or tr(BA_UNKNOWN))
            continue
        if p["category"] == 21:
            b = _batch(p)
            ck = _content_key(b["year"], b["rows"])
            item.update(kind="batch", year=b["year"], rows=len(b["rows"]), bad=b["bad"])
            if b["year"] is None:
                item.update(kind="unknown", reason=tr(BA_NO_YEAR))
            elif ck in known_ck or any(x["ck"] == ck for x in plan["batches"]):
                item.update(kind="duplicate", reason=tr(BA_DUP, _when(runs.get(known_ck.get(ck)))) if ck in known_ck else tr(BA_DUP_UPLOAD))
            else:
                plan["batches"].append({"item": item, "data": data, "ck": ck, **b})
                y = plan["years"].setdefault(b["year"], {"year": b["year"], "bookings": 0, "debit": Decimal(0), "credit": Decimal(0),
                                                          "no_counter": 0, "bad": 0, "first": "", "last": "", "lines_s": Decimal(0),
                                                          "lines_h": Decimal(0)})
                y["bookings"] += len(b["rows"])
                y["debit"] += b["debit"]
                y["credit"] += b["credit"]
                y["no_counter"] += b["no_counter"]
                y["lines_s"] += b["lines_s"]
                y["lines_h"] += b["lines_h"]
                y["bad"] += b["bad"]
                y["first"] = min(x for x in (y["first"], b["first"]) if x) if (y["first"] or b["first"]) else ""
                y["last"] = max(y["last"], b["last"])
                if b["bad"]:
                    item["reason"] = tr(BA_ROW_BAD, b["bad"])
        elif p["category"] == 20:
            year = p["fy_start"].year if p["fy_start"] else None
            labels = {}
            for r in p["rows"]:
                a = re.sub(r"\s+", "", _cell(p, r, "account"))[:12]
                t = re.sub(r"\s+", " ", _cell(p, r, "label")).strip()[:80]
                if a and t:
                    labels[a] = t
            item.update(kind="labels", year=year, rows=len(labels))
            plan["labels"].append({"item": item, "data": data, "year": year, "labels": labels})
        else:
            try:  # review F3: a master data file over the DATEV import's limits is this file's problem, not the upload's
                dp, _mplan, counts = di_plan(c, oid, data, ofr_allows(c, uid, oid, "offers", "edit"))
            except Denied as e:
                item.update(kind="unknown", reason=e.text())
                continue
            except BadInput as e:
                item.update(kind="unknown", reason=str(e) or tr(BA_UNKNOWN))
                continue
            names = {}
            for r in dp["rows"]:  # read with the DATEV import's columns (the names)
                a = re.sub(r"\s+", "", _cell(dp, r, "account"))[:12]
                n = _person(dp, r)
                if a and n:
                    names[a] = n
            item.update(kind="master", rows=len(names), counts=counts)
            plan["masters"].append({"item": item, "data": data, "labels": names, "counts": counts})
    # the receipt images: linked by the GUID to a booking of this upload or of the archive
    links = {x["link"]: b["year"] for b in plan["batches"] for x in b["rows"] if x["link"]}
    have = {r["guid"] for r in c.execute("SELECT d.guid FROM office_bookarch_docs d JOIN office_import_runs r ON r.id=d.run_id "
                                         "WHERE d.org_id=? AND r.undone_at IS NULL", (oid,))}
    dn = {"linked": 0, "known": 0, "no_booking": [], "missing": []}
    left_set = {n.casefold() for n in left}
    for item, _data, entries in xmls:
        for guid, fname in entries:
            low = fname.casefold()
            if guid in have or any(d["guid"] == guid for d in plan["docs"]):
                dn["known"] += 1
                continue
            year = links.get(guid)
            if year is None:
                r = c.execute("SELECT year FROM office_bookarch b JOIN office_import_runs r ON r.id=b.run_id WHERE b.org_id=? AND b.link=? "
                              "AND r.undone_at IS NULL LIMIT 1", (oid, guid)).fetchone()
                year = r["year"] if r else None
            if year is None:
                dn["no_booking"].append(fname)
                continue
            if low not in images and low not in left_set:
                dn["missing"].append(fname)
                continue
            plan["docs"].append({"guid": guid, "name": fname, "year": year, "key": low, "xml": item["sha256"]})
            dn["linked"] += 1
    plan["xmls"] = [(item, data) for item, data, _e in xmls]
    plan["doc_files"] = images
    plan["doc_note"] = dn
    return plan


def _when(ts):
    return (ts or "")[:10]


def ba_public(plan):
    years = []
    for y in sorted(plan["years"].values(), key=lambda x: x["year"]):
        years.append({"year": y["year"], "bookings": y["bookings"], "debit": _cents(y["debit"]), "credit": _cents(y["credit"]),
                      "balanced": y["debit"] == y["credit"], "no_counter": y["no_counter"], "bad": y["bad"], "first": y["first"],
                      "lines_debit": _cents(y["lines_s"]), "lines_credit": _cents(y["lines_h"]),
                      "last": y["last"]})
    dn = plan["doc_note"]
    files = [{k: x.get(k) for k in ("name", "kind", "year", "rows", "reason", "bytes", "counts")} for x in plan["files"]]
    counts = {"bookings": sum(y["bookings"] for y in years), "years": len(years), "labels": sum(x["item"]["rows"] for x in plan["labels"]),
              "masters": len(plan["masters"]), "docs": dn["linked"], "docs_known": dn["known"], "docs_no_booking": len(dn["no_booking"]),
              "docs_missing": len(dn["missing"]), "duplicates": sum(1 for x in files if x["kind"] == "duplicate"),
              "unknown": sum(1 for x in files if x["kind"] == "unknown")}
    ok = bool(plan["batches"] or plan["labels"] or plan["masters"] or plan["docs"])
    return {"files": files, "years": years, "counts": counts, "ok": ok, "errors": plan["errors"][:BA_PREVIEW],
            "docs_no_booking": dn["no_booking"][:BA_PREVIEW], "docs_missing": dn["missing"][:BA_PREVIEW], "note": tr(BA_NOTE)}


# ---------------------------------------------------------------- import, undo
def _fname(c, oid, name):
    """review F8: the name of an original file may carry a client's name -> encrypted at rest like the texts."""
    return oc_enc_fields(c, oid, "office_bookarch_files", {"file_name": name[:200]})["file_name"]


def _fields_batch(c, oid, rows):
    """The protected columns (core/orgcrypt.py FIELDS) of many rows."""
    return [oc_enc_fields(c, oid, "office_bookarch", r) for r in rows]


def ba_import(c, oid, uid, items):
    """Takes the upload over -> (run id, public preview, files to rename after the commit: a _Store)."""
    write_lock(c, f"office_import_{int(oid)}")
    plan = ba_plan(c, oid, uid, items, True)
    if not (plan["batches"] or plan["labels"] or plan["masters"] or plan["docs"]):
        raise BadInput(tr(BA_NOTHING))
    ts = iso(now_utc())
    rid = insert_id(c, "INSERT INTO office_import_runs(org_id, kind, created_by, created_at) VALUES(?,?,?,?)", (oid, BA_KIND, uid, ts))
    st = _Store(c, oid)
    try:
        detail = {"master_runs": [], "years": sorted(plan["years"])}
        for b in plan["batches"]:
            f = st.put(b["data"], ".csv")
            c.execute("INSERT INTO office_bookarch_files(org_id, run_id, kind, year, file_name, file, sha256, content_key, bytes, nrows, "
                      "created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, rid, "batch", b["year"], _fname(c, oid, b["item"]["name"]), f, b["item"]["sha256"], b["ck"], len(b["data"]), len(b["rows"]), uid, ts))
            sql = ("INSERT INTO office_bookarch(org_id, run_id, year, line, day, account, counter, side, amount, currency, bu, doc1, doc2, text, "
                   "link, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
            for k in range(0, len(b["rows"]), BA_INS):
                part = _fields_batch(c, oid, [dict(x, amount=format(x["amount"], "f")) for x in b["rows"][k:k + BA_INS]])
                c.executemany(sql, [(oid, rid, b["year"], x["line"], x["day"], x["account"], x["counter"], x["side"], x["amount"], x["currency"],
                                     x["bu"], x["doc1"], x["doc2"], x["text"], x["link"], x["raw"]) for x in part])
        late = max(plan["years"]) if plan["years"] else None  # labels without a year live as long as the newest year of the upload
        for kind, lb in [("labels", x) for x in plan["labels"]] + [("master", x) for x in plan["masters"]]:
            year = lb.get("year") or late
            f = st.put(lb["data"], ".csv")
            c.execute("INSERT INTO office_bookarch_files(org_id, run_id, kind, year, file_name, file, sha256, content_key, bytes, nrows, "
                      "created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, rid, kind, year, _fname(c, oid, lb["item"]["name"]), f, lb["item"]["sha256"], "", len(lb["data"]), len(lb["labels"]), uid, ts))
            rows = [oc_enc_fields(c, oid, "office_bookarch_accts", {"account": a, "label": t}) for a, t in lb["labels"].items()]
            c.executemany("INSERT INTO office_bookarch_accts(org_id, run_id, year, account, label, kind) VALUES(?,?,?,?,?,?)",
                          [(oid, rid, year if kind == "labels" else None, x["account"], x["label"], "person" if kind == "master" else "ledger")
                           for x in rows])
        for m in plan["masters"]:  # the DATEV import's own run (clients / suppliers fill empty fields), undone with this one
            mrid, _p, _pl, _cn = di_import(c, oid, uid, m["data"], ofr_allows(c, uid, oid, "offers", "edit"))
            detail["master_runs"].append(mrid)
        ndocs, xml_years, skipped_docs = 0, {}, []
        for d in plan["docs"]:
            name, data = plan["doc_files"].get(d["key"], (None, None))
            mime = _mime(data) if data else None
            if not mime:  # review F9: no PDF / picture -> left out and named
                skipped_docs.append(d["name"])
                continue
            f = st.put(data, BA_DOC_MIME[mime])
            row = oc_enc_fields(c, oid, "office_bookarch_docs", {"file_name": (name or d["name"])[:200]})
            c.execute("INSERT INTO office_bookarch_docs(org_id, run_id, year, guid, file_name, file, mime, sha256, bytes, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)", (oid, rid, d["year"], d["guid"], row["file_name"], f, mime,
                                                       hashlib.sha256(data).hexdigest(), len(data), ts))
            ndocs += 1
            xml_years[d["xml"]] = max(xml_years.get(d["xml"]) or 0, int(d["year"]))
        for item, data in plan["xmls"]:  # the document.xml of the receipts that came in, as a proof next to them
            if item["sha256"] not in xml_years:
                continue
            f = st.put(data, ".xml")
            c.execute("INSERT INTO office_bookarch_files(org_id, run_id, kind, year, file_name, file, sha256, content_key, bytes, nrows, "
                      "created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, rid, "docs", xml_years[item["sha256"]], _fname(c, oid, item["name"]), f, item["sha256"], "", len(data), item["rows"], uid, ts))
        pub = ba_public(plan)
        counts = {"bookings": pub["counts"]["bookings"], "labels": pub["counts"]["labels"], "docs": ndocs,
                  "files": len(plan["batches"]) + len(plan["labels"]) + len(plan["masters"]), "skipped": pub["counts"]["duplicates"]}
        c.execute("UPDATE office_import_runs SET counts=?, detail=? WHERE id=? AND org_id=?", (json.dumps(counts), json.dumps(detail), rid, oid))
    except BaseException:
        st.done(False)
        raise
    pub["counts"]["docs"] = ndocs
    pub["counts"]["docs_skipped"] = len(skipped_docs)
    pub["docs_skipped"] = skipped_docs[:BA_PREVIEW]
    return rid, pub, st


def ba_undo(c, oid, uid, r):
    """Undoes the archive run r -> (removed, kept, file names to remove after the commit, []) like legacyimport.fi_undo."""
    if r["undone_at"]:
        raise Denied(409, tr("This import has already been undone"))
    rid = r["id"]
    try:
        detail = json.loads(r["detail"] or "{}")
    except ValueError:
        detail = {}
    removed, kept = {"bookings": 0, "labels": 0, "docs": 0, "files": 0, "master": 0}, {"master": 0}
    files = [x["file"] for x in c.execute("SELECT file FROM office_bookarch_files WHERE org_id=? AND run_id=?", (oid, rid))]
    files += [x["file"] for x in c.execute("SELECT file FROM office_bookarch_docs WHERE org_id=? AND run_id=?", (oid, rid))]
    for t, k in (("office_bookarch", "bookings"), ("office_bookarch_accts", "labels"), ("office_bookarch_docs", "docs"),
                 ("office_bookarch_files", "files")):
        removed[k] = max(c.execute(f"DELETE FROM {t} WHERE org_id=? AND run_id=?", (oid, rid)).rowcount or 0, 0)
    for mrid in detail.get("master_runs") or []:
        m = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=? AND kind='datev'", (int(mrid), oid)).fetchone()
        if not m or m["undone_at"]:
            continue
        try:
            with c.savepoint():
                di_undo(c, oid, uid, m)
            removed["master"] += 1
        except Denied:  # its clients are older than a day or used: they stay (the DATEV run can be undone on its own)
            kept["master"] += 1
    c.execute("UPDATE office_import_runs SET undone_at=?, undone_by=? WHERE id=? AND org_id=?", (iso(now_utc()), uid, rid, oid))
    return removed, kept, files, []


# ---------------------------------------------------------------- the view
def _labels(c, oid, year):
    """{account: label}: the year's own ledger labels before those of no year, then the names of the person accounts."""
    out = {}
    for r in c.execute("SELECT a.* FROM office_bookarch_accts a JOIN office_import_runs r ON r.id=a.run_id WHERE a.org_id=? "
                       "AND r.undone_at IS NULL AND (a.year=? OR a.year IS NULL) ORDER BY (a.year IS NULL) DESC, a.id", (oid, year)):
        r = oc_dec_fields(c, oid, "office_bookarch_accts", r)
        out[r["account"]] = r["label"]
    return out


def _year():
    try:
        y = int(request.args.get("year") or 0)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "year")) from None
    if not 1900 <= y <= 2999:
        raise BadInput(tr("Invalid value: {0}", "year"))
    return y


def _filters(oid, year):
    """SQL + args of the plain filters; the text filters (q, doc) are applied after decryption."""
    a = request.args
    sql, args = "b.org_id=? AND b.year=? AND r.undone_at IS NULL", [oid, year]
    for k, col in (("account", "b.account"), ("counter", "b.counter")):
        v = re.sub(r"\s+", "", a.get(k) or "")[:12]
        if v:
            sql += f" AND {col}=?"
            args.append(v)
    v = re.sub(r"\s+", "", a.get("any") or "")[:12]
    if v:
        sql += " AND (b.account=? OR b.counter=?)"
        args += [v, v]
    for k, op in (("from", ">="), ("to", "<=")):
        v = (a.get(k) or "").strip()
        if v:
            try:
                v = date.fromisoformat(v).isoformat()
            except ValueError:
                raise BadInput(tr("Invalid value: {0}", k)) from None
            sql += f" AND b.day{op}?"
            args.append(v)
    for k, op in (("min", ">="), ("max", "<=")):
        v = (a.get(k) or "").strip()
        if v:
            d = _amount(v)
            if d is None:
                raise BadInput(tr("Invalid value: {0}", k))
            sql += f" AND b.amount{op}?"
            args.append(format(abs(d), "f"))
    side = (a.get("side") or "").strip().upper()
    if side in ("S", "H"):
        sql += " AND b.side=?"
        args.append(side)
    return sql, args


def _row_public(r, labels, docs):
    return {"id": r["id"], "line": r["line"], "day": r["day"], "account": r["account"], "account_label": labels.get(r["account"], ""),
            "counter": r["counter"], "counter_label": labels.get(r["counter"], ""), "side": r["side"], "amount": _cents(r["amount"]),
            "currency": r["currency"], "bu": r["bu"], "doc1": r["doc1"], "doc2": r["doc2"], "text": r["text"],
            "doc_id": docs.get(r["link"]) if r["link"] else None}


def ba_bookings(c, oid, year):
    a = request.args
    sql, args = _filters(oid, year)
    q, doc = (a.get("q") or "").strip().casefold()[:100], (a.get("doc") or "").strip().casefold()[:36]
    try:
        offset, limit = max(0, int(a.get("offset") or 0)), min(BA_LIST_MAX, max(1, int(a.get("limit") or 200)))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "offset")) from None
    base = f"FROM office_bookarch b JOIN office_import_runs r ON r.id=b.run_id WHERE {sql}"
    order = " ORDER BY b.day, b.run_id, b.line, b.id"
    cols = "b.id, b.year, b.line, b.day, b.account, b.counter, b.side, b.amount, b.currency, b.bu, b.doc1, b.doc2, b.text, b.link"  # review F2: never raw
    if q or doc:
        rows = []
        for r in c.execute(f"SELECT {cols} {base}{order}", args):
            r = oc_dec_fields(c, oid, "office_bookarch", r)
            if doc and doc not in (r["doc1"] or "").casefold() and doc not in (r["doc2"] or "").casefold():
                continue
            if q and q not in (r["text"] or "").casefold() and q not in (r["doc1"] or "").casefold():
                continue
            rows.append(r)
        total = len(rows)
        debit = sum((Decimal(str(r["amount"])) for r in rows if r["side"] == "S"), Decimal(0))
        credit = sum((Decimal(str(r["amount"])) for r in rows if r["side"] == "H"), Decimal(0))
        page = rows[offset:offset + limit]
    else:
        s = c.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN b.side='S' THEN b.amount ELSE 0 END), 0) AS d, "
                      f"COALESCE(SUM(CASE WHEN b.side='H' THEN b.amount ELSE 0 END), 0) AS h {base}", args).fetchone()
        total, debit, credit = s["n"], s["d"], s["h"]
        page = [oc_dec_fields(c, oid, "office_bookarch", r) for r in c.execute(f"SELECT {cols} {base}{order} LIMIT ? OFFSET ?", [*args, limit, offset])]
    links = sorted({r["link"] for r in page if r["link"]})
    docs = {}
    if links:
        qm = ",".join("?" * len(links))
        for d in c.execute(f"SELECT d.id, d.guid FROM office_bookarch_docs d JOIN office_import_runs r ON r.id=d.run_id WHERE d.org_id=? "
                           f"AND r.undone_at IS NULL AND d.guid IN ({qm})", [oid, *links]):
            docs.setdefault(d["guid"], d["id"])
    labels = _labels(c, oid, year)
    return {"year": year, "total": total, "offset": offset, "limit": limit, "debit": _cents(debit), "credit": _cents(credit),
            "items": [_row_public(r, labels, docs) for r in page]}


def ba_accounts(c, oid, year):
    """Sums per account of the year: every booking on its account and, the other way round, on its counter account."""
    rows = c.execute(
        "SELECT x.acct, COUNT(*) AS n, COALESCE(SUM(CASE WHEN x.side='S' THEN x.amount ELSE 0 END), 0) AS d, "
        "COALESCE(SUM(CASE WHEN x.side='H' THEN x.amount ELSE 0 END), 0) AS h FROM ("
        "SELECT b.account AS acct, b.side, b.amount FROM office_bookarch b JOIN office_import_runs r ON r.id=b.run_id "
        "WHERE b.org_id=? AND b.year=? AND r.undone_at IS NULL "
        "UNION ALL SELECT b.counter, CASE WHEN b.side='S' THEN 'H' ELSE 'S' END, b.amount FROM office_bookarch b "
        "JOIN office_import_runs r ON r.id=b.run_id WHERE b.org_id=? AND b.year=? AND r.undone_at IS NULL AND b.counter<>''"
        ") x GROUP BY x.acct ORDER BY x.acct", (oid, year, oid, year)).fetchall()
    labels = _labels(c, oid, year)
    out = []
    for r in rows:
        d, h = Decimal(str(r["d"])), Decimal(str(r["h"]))
        out.append({"account": r["acct"], "label": labels.get(r["acct"], ""), "count": r["n"], "debit": _cents(d), "credit": _cents(h),
                    "balance": _cents(abs(d - h)), "side": "S" if d >= h else "H"})
    return out


def ba_overview(c, oid):
    years = []
    for r in c.execute("SELECT b.year, COUNT(*) AS n, MIN(b.day) AS first, MAX(b.day) AS last FROM office_bookarch b "
                       "JOIN office_import_runs r ON r.id=b.run_id WHERE b.org_id=? AND r.undone_at IS NULL GROUP BY b.year ORDER BY b.year DESC",
                       (oid,)):
        nd = c.execute("SELECT COUNT(*) FROM office_bookarch_docs d JOIN office_import_runs r ON r.id=d.run_id WHERE d.org_id=? AND d.year=? "
                       "AND r.undone_at IS NULL", (oid, r["year"])).fetchone()[0]
        years.append({"year": r["year"], "bookings": r["n"], "first": r["first"] or "", "last": r["last"] or "", "docs": nd,
                      "keep_until": f"{int(r['year']) + RET_LEGAL_YEARS['book']}-12-31"})
    runs, users = [], {}
    for r in c.execute("SELECT * FROM office_import_runs WHERE org_id=? AND kind=? ORDER BY id DESC LIMIT 100", (oid, BA_KIND)):
        if r["created_by"] and r["created_by"] not in users:
            u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["created_by"],)).fetchone()
            users[r["created_by"]] = (u["display_name"] or u["username"]) if u else ""
        try:
            counts = json.loads(r["counts"] or "{}")
        except ValueError:
            counts = {}
        fl = [{"id": f["id"], "name": f["file_name"], "kind": f["kind"], "year": f["year"], "rows": f["nrows"], "bytes": f["bytes"],
               "sha256": f["sha256"]} for f in (oc_dec_fields(c, oid, "office_bookarch_files", x) for x in
                                                c.execute("SELECT * FROM office_bookarch_files WHERE org_id=? AND run_id=? ORDER BY id", (oid, r["id"])))]
        runs.append({"id": r["id"], "created_at": r["created_at"], "user_name": users.get(r["created_by"], ""), "undone_at": r["undone_at"],
                     "counts": counts, "files": fl})
    return {"years": years, "runs": runs, "note": tr(BA_NOTE)}


# ---------------------------------------------------------------- retention
def ba_retention_tick(c, force=False):
    """The watchdog (daily, system context): archived years whose legal period ended (10 years after the year's end) go
    for good with their receipt images and original files -- only while ret_on("trash"), else counted (run "bookarch")."""
    if not ret_due("bookarch", 86400, force):
        return 0
    cut = local_now().year - RET_LEGAL_YEARS["book"] - 1  # year Y is kept until 31.12. of Y + 10
    with system_ctx(c):  # the purge works across every office area (no content leaves it)
        due = c.execute("SELECT org_id, COUNT(*) AS n FROM office_bookarch WHERE year<=? GROUP BY org_id", (cut,)).fetchall()
        nd = c.execute("SELECT COUNT(*) FROM office_bookarch_docs WHERE year<=?", (cut,)).fetchone()[0]
        nf = c.execute("SELECT COUNT(*) FROM office_bookarch_files WHERE year<=?", (cut,)).fetchone()[0]
        counts = {"archive_bookings": sum(r["n"] for r in due), "archive_docs": nd, "archive_files": nf}
        if not ret_on("trash"):
            ret_report(c, "trash", counts, False, run="bookarch")
            c.commit()
            return 0
        names = {}
        for t in ("office_bookarch_docs", "office_bookarch_files"):
            for r in c.execute(f"SELECT org_id, file FROM {t} WHERE year<=?", (cut,)):
                names.setdefault(r["org_id"], []).append(r["file"])
        for t in BA_TABLES:
            c.execute(f"DELETE FROM {t} WHERE year<=?", (cut,))
        # what has no year (labels / master data of an upload without a batch) goes once the office has no archived booking left
        old = f"{cut + 1}-01-01"
        lone = "org_id NOT IN (SELECT org_id FROM office_bookarch) AND run_id IN (SELECT id FROM office_import_runs WHERE created_at<?)"
        for r in c.execute(f"SELECT org_id, file FROM office_bookarch_files WHERE year IS NULL AND {lone}", (old,)):
            names.setdefault(r["org_id"], []).append(r["file"])
        for t in ("office_bookarch_accts", "office_bookarch_files"):
            c.execute(f"DELETE FROM {t} WHERE year IS NULL AND {lone}", (old,))
        ret_report(c, "trash", counts, True, run="bookarch")
        c.commit()
    for oid, n in names.items():
        ba_unlink(oid, n)
    return counts["archive_bookings"]


# ---------------------------------------------------------------- routes
def _ctx():
    c, uid, oid = office_ctx(admin=True)
    office_need_feature(c, oid, "books.datev")  # DATEV switched off -> no archive (nothing is deleted)
    return c, uid, oid


def _uploads(check):
    out = []
    for f in request.files.getlist("file"):
        raw = f.read(BA_TOTAL_MAX + 1)
        if len(raw) > BA_TOTAL_MAX:
            raise Denied(413, tr("The file is too large (at most {0} MB)", BA_TOTAL_MAX // (1024 * 1024)))
        out.append((base_name(f.filename or "") or "file", raw))
    if not out:
        raise BadInput(tr("No file"))
    return out


@app.get("/api/office/books/archive")
def ba_get():
    """Office admin: {years [{year, bookings, first, last, docs, keep_until}], runs [{id, created_at, user_name, undone_at, counts,
    files [{id, name, kind, year, rows, bytes, sha256}]}], note}."""
    c, uid, oid = _ctx()
    return jsonify(ba_overview(c, oid))


@app.get("/api/office/books/archive/bookings")
def ba_bookings_get():
    """Office admin: the bookings of ?year= with the filters account, counter, any (either side), from, to (ISO days), min, max
    (amount), side (S | H), doc (receipt field 1 / 2 contains), q (text or receipt field 1 contains); offset, limit (at most
    500) -> {year, total, offset, limit, debit, credit (of every match), items [...]}."""
    c, uid, oid = _ctx()
    return jsonify(ba_bookings(c, oid, _year()))


@app.get("/api/office/books/archive/bookings/<int:bid>")
def ba_booking_get(bid):
    """Office admin: one booking with every column of its line as in the batch (raw)."""
    c, uid, oid = _ctx()
    r = c.execute("SELECT b.* FROM office_bookarch b JOIN office_import_runs r ON r.id=b.run_id WHERE b.id=? AND b.org_id=? "
                  "AND r.undone_at IS NULL", (bid, oid)).fetchone()
    if not r:
        raise Denied(404)
    r = oc_dec_fields(c, oid, "office_bookarch", r)
    d = c.execute("SELECT id FROM office_bookarch_docs WHERE org_id=? AND guid=? AND guid<>'' ORDER BY id LIMIT 1", (oid, r["link"] or "")).fetchone()
    out = _row_public(r, _labels(c, oid, r["year"]), {r["link"]: d["id"]} if d else {})
    try:
        out["raw"] = json.loads(r["raw"] or "{}")
    except ValueError:
        out["raw"] = {}
    out["year"] = r["year"]
    return jsonify(out)


@app.get("/api/office/books/archive/accounts")
def ba_accounts_get():
    """Office admin: the sums per account of ?year= {year, items [{account, label, count, debit, credit, balance, side}]}."""
    c, uid, oid = _ctx()
    y = _year()
    return jsonify(year=y, items=ba_accounts(c, oid, y))


def _send(c, p, mime, name, inline):
    resp = oc_send_file(c, p, mimetype=mime, download_name=name, as_attachment=not inline)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"  # a foreign file never runs script under the app origin
    return resp


@app.get("/api/office/books/archive/docs/<int:did>")
def ba_doc_get(did):
    """Office admin: the receipt image of a booking, unchanged (PDF / pictures inline, TIFF as a download)."""
    c, uid, oid = _ctx()
    r = c.execute("SELECT d.* FROM office_bookarch_docs d JOIN office_import_runs r ON r.id=d.run_id WHERE d.id=? AND d.org_id=? "
                  "AND r.undone_at IS NULL", (did, oid)).fetchone()
    p = ba_path(oid, r["file"]) if r else None
    if not p:
        raise Denied(404)
    r = oc_dec_fields(c, oid, "office_bookarch_docs", r)
    ofx_log(c, oid, "open", target="bookarch_doc", detail={"doc_id": did}, dedupe_min=10)
    c.commit()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", r["file_name"] or "").strip("-") or f"beleg-{did}{BA_DOC_MIME.get(r['mime'], '')}"
    return _send(c, p, r["mime"], name, r["mime"] != "image/tiff" and request.args.get("download") != "1")


@app.get("/api/office/books/archive/files/<int:fid>")
def ba_file_get(fid):
    """Office admin: an original export file of the archive, unchanged (download)."""
    c, uid, oid = _ctx()
    r = c.execute("SELECT * FROM office_bookarch_files WHERE id=? AND org_id=?", (fid, oid)).fetchone()
    p = ba_path(oid, r["file"]) if r else None
    if not p:
        raise Denied(404)
    r = oc_dec_fields(c, oid, "office_bookarch_files", r)
    ofx_log(c, oid, "export", target="bookarch_file", detail={"file_id": fid}, dedupe_min=10)
    c.commit()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", r["file_name"] or "").strip("-") or f"datev-{fid}.csv"
    return _send(c, p, "application/octet-stream", name, False)


@app.post("/api/office/books/archive/check")
def ba_check_post():
    """Office admin. multipart 'file' (one or more: EXTF batches, account labels, debtors / creditors, document.xml, ZIPs) ->
    the preview {files, years [{year, bookings, debit, credit, balanced, no_counter, bad, first, last}], counts, ok, errors,
    docs_no_booking, docs_missing, note}. Nothing is stored."""
    c, uid, oid = _ctx()
    return jsonify(ba_public(ba_plan(c, oid, uid, _uploads(True), False)))


@app.post("/api/office/books/archive/import")
def ba_import_post():
    """Office admin. multipart 'file' -> takes over what the preview showed: 201 {run_id, counts, years, docs_skipped (receipt files
    that are no PDF / picture, left out)}."""
    c, uid, oid = _ctx()
    rid, pub, st = ba_import(c, oid, uid, _uploads(False))
    ofx_log(c, oid, "import", target="bookarch", detail={"run_id": rid, "counts": pub["counts"], "years": [y["year"] for y in pub["years"]]})
    bump(c)
    try:
        c.commit()
    except BaseException:
        st.done(False)
        raise
    st.done(True)
    return jsonify(run_id=rid, counts=pub["counts"], years=pub["years"], docs_skipped=pub["docs_skipped"]), 201


@app.post("/api/office/books/archive/runs/<int:rid>/undo")
def ba_undo_post(rid):
    """Office admin: undoes the archive run rid -> {removed, kept}; 409 when already undone."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_import_{int(oid)}")
    r = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=? AND kind=?", (rid, oid, BA_KIND)).fetchone()
    if not r:
        raise Denied(404)
    removed, kept, files, _a = ba_undo(c, oid, uid, r)
    ofx_log(c, oid, "undo", target="bookarch", detail={"run_id": rid, "removed": removed, "kept": kept})
    bump(c)
    c.commit()
    ba_unlink(oid, files)  # after the commit: a failed undo keeps its files
    return jsonify(removed=removed, kept=kept)

