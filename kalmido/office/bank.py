"""2.90.0 B (#1921): bank reconciliation -- CSV / CAMT.053 import, matching bookings to invoices and receipts.

A statement (CSV from the bank's export with the column mapping of the household budget, or CAMT.052 / .053 XML) becomes
bookings (office_bank_tx, one office area; amount signed, + = in). A booking is matched to an open invoice (a payment is
recorded through the invoices' own logic, invoices.inv_pay_add: paid / partly paid follow), to a receipt (its payment day,
books.bk_receipt_set_paid), or marked private / ignored. Every match can be undone; an import can be taken back as long as
none of its bookings is matched. No bank access, no external service.
Every route: office_gate + office_org(admin=True) -- admins of the office area only (the person in a personal office);
agents and kids 403, foreign ids 404. amount / counterpart / purpose / iban are encrypted at rest (orgcrypt)."""
import hashlib
import hmac
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

from flask import jsonify, request

from ..core.config import SECRET_KEY, app
from ..core import csvimport as cx  # 2.140.0 B (#2134): the shared statement reader
from ..core import stmtfiles as sf  # 2.146.0 C (#2455): uploads, several files / a ZIP
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings

BNK_KINDS = ("invoice", "receipt", "private", "ignored")
BNK_STATES = ("open", "matched", "all")
BNK_LIST_MAX = 2000
BNK_TEXT_MAX = 300
BNK_WINDOW = 14  # days around a booking for receipts
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")
# 2.144.1 B (#2450): several files or a ZIP in one import -- read in memory only (nothing is ever unpacked to disk)
BNK_FILE_MAX = 2 * 1024 * 1024  # one statement (as before)
BNK_FILE_ROWS = 3000  # rows of one statement (as before)
BNK_UPLOAD_MAX = 20 * 1024 * 1024  # all uploaded files of one request
BNK_FILES_MAX = 400  # statements of one import (after unpacking)
BNK_UNPACKED_MAX = 60 * 1024 * 1024  # all statements together, unpacked
BNK_ROWS_MAX = 20000  # rows of one import
BNK_ZIP_ENTRIES_MAX = 2000  # entries in a ZIP's central directory, checked before anything is read
BNK_EXTS = (".xml", ".csv", ".txt")


def _ctx():
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=True)


def _home(c, oid):
    return (office_settings(c, oid).get("currency") or "EUR").upper()


def _clean(v, n=BNK_TEXT_MAX):
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "")
    return re.sub(r"\s+", " ", v).strip()[:n]


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return re.sub(r"[^0-9a-z]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def bnk_hash(oid, day, amount, counterpart, purpose, ref):
    """The keyed fingerprint of a booking in area oid (stored in plain text, so keyed with the server key)."""
    key = SECRET_KEY if isinstance(SECRET_KEY, bytes) else str(SECRET_KEY).encode()
    msg = "\x1f".join([str(oid), day or "", dstr(money(dec(amount))), _norm(counterpart), _norm(purpose), (ref or "").strip()])
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()[:40]


def bnk_rkey(oid, part):
    """2.146.0 C (#2469): the keyed reference key of a booking in area oid (core/csvimport.csv_ref_parts: AcctSvcrRef /
    EndToEndId with the amount) -- stored space separated in office_bank_tx.rkeys, never the reference itself."""
    key = SECRET_KEY if isinstance(SECRET_KEY, bytes) else str(SECRET_KEY).encode()
    return hmac.new(key, f"bank-ref\x1f{oid}\x1f{part}".encode(), hashlib.sha256).hexdigest()[:40]


def _rkeys(c, oid):
    """2.146.0 C (#2469): the reference keys of the area's active bookings."""
    out = set()
    for r in c.execute("SELECT rkeys FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND rkeys<>''", (oid,)):
        out.update(r[0].split())
    return out


# ---------------------------------------------------------------- reading statements
# 2.140.0 B (#2134): CSV and CAMT are read by core/csvimport.py (shared with the household budget); the names stay
# (cfbank.py reads the balances with the CAMT helpers)
bnk_is_camt = cx.camt_is
_local, _kids, _kid, _txt = cx.camt_local, cx.camt_kids, cx.camt_kid, cx.camt_txt


def bnk_camt(text):
    """CAMT.052 / .053 XML -> [{day, amount (signed Decimal), currency, counterpart, purpose, iban, ref, error}]
    (core/csvimport.camt_rows: DOCTYPE / ENTITY refused before parsing)."""
    return cx.camt_rows(text, BNK_TEXT_MAX)


_iban_col = cx.csv_iban_col  # 2.146.0 C (#2455): the counterpart's IBAN column (an own-account IBAN column only when alone)


def bnk_csv(text, mapping):
    """CSV with a column mapping (core/csvimport.py, like the household budget) -> rows like bnk_camt."""
    _d, header, rows = cx.csv_table(text)
    m = cx.csv_mapping(mapping, len(header))
    if len(rows) > cx.CSV_ROWS:
        raise BadInput(tr("At most {0} rows per import", cx.CSV_ROWS))
    ic = _iban_col(header)
    out = []
    for r in rows:
        x = cx.csv_row(r, m)
        amt = None
        if x["amount"] is not None:
            amt = money(dec(x["amount"]))
            amt = amt if x["kind"] == "in" else -amt
        cp = _clean(x["counterpart"], 200)
        purpose = _clean(r[m["title"]] if m.get("title") is not None and m["title"] < len(r) else "")
        iban = (r[ic] if ic is not None and ic < len(r) else "").replace(" ", "").upper()
        out.append({"day": x["day"], "amount": amt, "currency": "", "counterpart": cp, "purpose": purpose,
                    "iban": iban if IBAN_RE.match(iban) else None, "ref": None, "error": x["error"], "pending": False})
    return out


def _hashes(c, oid):
    return Counter(r[0] for r in c.execute("SELECT hash FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL", (oid,)))


# 2.146.0 C (#2455): the uploads of a request are read by core/stmtfiles (shared with the household budget's import;
# the same limits and messages as 2.144.1)
_LIMITS = {"file_max": BNK_FILE_MAX, "upload_max": BNK_UPLOAD_MAX, "files_max": BNK_FILES_MAX, "unpacked_max": BNK_UNPACKED_MAX,
           "entries_max": BNK_ZIP_ENTRIES_MAX, "exts": BNK_EXTS}
_fname, _decode = sf.stmt_fname, sf.stmt_decode
bnk_is_mt940 = sf.is_mt940  # a SWIFT MT940 / MT942 statement -- not read; the dialog asks for CAMT.053


def _uploads(b):
    """The statements of the request: multipart (field files, several; a ZIP is opened) or the JSON body {text, filename}."""
    return sf.stmt_uploads(b, _LIMITS)


def _req():
    """The request as a dict: the JSON body, or the form fields of a multipart upload (mapping as a JSON string, account)."""
    return sf.stmt_req(BNK_UPLOAD_MAX)


def bnk_parse(c, oid, b, fs=None):
    """{text, filename?, mapping?} or the uploads of the request (fs) -> (fmt, rows, preview_of_columns|None, parts, info).
    Rows carry n, error and dup (an equal booking is there already: two equal rows of one file need two existing ones);
    2.144.1 B (#2450): several statements give one list sorted by day; a booking in two files (day and month statement) counts
    once -- per fingerprint the largest number of the database or of one earlier file counts, never their sum. parts =
    [{name, fmt, text}] of the readable statements, info = {files, file_errors, skipped_files, label} for the answer; fmt
    camt | csv | mixed (the column is free text)."""
    fs = fs or _uploads(b)
    home = _home(c, oid)
    mapping = b.get("mapping")
    parts, n_files = [], len(fs.files) + len(fs.errors)
    for f in fs.files:
        if bnk_is_camt(f["text"]):
            parts.append({**f, "fmt": "camt"})
        elif bnk_is_mt940(f["text"]):
            fs.errors.append({"file": f["name"], "error": tr("MT940 / MT942 is not read; please export CAMT.053 (XML) from your online banking")})
        else:
            parts.append({**f, "fmt": "csv"})
    info = {"files": n_files, "file_errors": fs.errors, "skipped_files": fs.skipped, "label": ", ".join(fs.labels)}
    if not parts:
        raise BadInput(fs.errors[0]["error"] if len(fs.errors) == 1 else
                       "; ".join(f"{e['file']}: {e['error']}" for e in fs.errors[:5]) if fs.errors else tr("No statement found in the files"))
    csvs = [p for p in parts if p["fmt"] == "csv"]
    if csvs:
        key = None
        for p in csvs:
            try:
                d, header, sample = cx.csv_table(p["text"])
            except BadInput:
                if len(parts) == 1:
                    raise
                p["error"] = tr("The file cannot be read")
                continue
            k = cx.csv_hkey(header)
            if key is None:
                key, first = k, (d, header, sample)
            elif k != key:
                raise BadInput(tr("CSV files with different columns: please import them one by one"))
        if mapping is None and key is not None:
            d, header, sample = first
            return "csv", None, {"columns": header, "sample": sample[:8], "delimiter": d, "guess": cx.csv_guess(header, sample)}, parts, info
    rows = []
    for fi, p in enumerate(parts):
        if isinstance(p.get("error"), str):
            fs.errors.append({"file": p["name"], "error": p["error"]})
            continue
        try:
            got = bnk_camt(p["text"]) if p["fmt"] == "camt" else bnk_csv(p["text"], mapping)
            if len(got) > BNK_FILE_ROWS:
                raise BadInput(tr("At most {0} rows per import", BNK_FILE_ROWS))
        except BadInput as x:
            if len(parts) == 1:
                raise
            fs.errors.append({"file": p["name"], "error": x.args[0] if x.args else tr("The file cannot be read")})
            p["error"] = True
            continue
        for n, r in enumerate(got, 1):
            r["n"], r["fi"], r["file"] = n, fi, p["name"]
        rows += got
        if len(rows) > BNK_ROWS_MAX:
            raise BadInput(tr("At most {0} rows per import", BNK_ROWS_MAX))
    parts[:] = [p for p in parts if not p.get("error")]
    if not parts:
        raise BadInput("; ".join(f"{e['file']}: {e['error']}" for e in fs.errors[:5]))
    have = _hashes(c, oid)
    refs = _rkeys(c, oid)  # 2.146.0 C (#2469): references of the database and of the earlier files of this import
    for fi in sorted({r["fi"] for r in rows}):
        mine, local = [r for r in rows if r["fi"] == fi], Counter(have)
        seen, got_refs = Counter(), set()
        for r in mine:
            r["dup"] = False
            r["pending"] = bool(r.get("pending"))  # 2.146.0 C (#2469): a pending CAMT.052 entry is shown, never imported
            r["currency"] = r["currency"] or home
            if r["error"] is None and r["currency"] != home:
                r["error"] = tr("Other currency than the office ({0})", home)
            if r["error"] is None and not r["pending"]:
                r["hash"] = bnk_hash(oid, r["day"], r["amount"], r["counterpart"], r["purpose"], r["ref"])
                # 2.146.0 C (#2469): the same reference in an earlier file / import = the same booking (also with another
                # day or text, e.g. pending first, booked later); else the fingerprint as before
                r["rkeys"] = [bnk_rkey(oid, x) for x in cx.csv_ref_parts(r)]
                r["dup"] = any(k in refs for k in r["rkeys"]) or cx.csv_dup_take(local, r["hash"])
                got_refs.update(r["rkeys"])
                seen[r["hash"]] += 1
        refs |= got_refs
        for h, k in seen.items():
            have[h] = max(have.get(h, 0), k)
    if len(parts) > 1:  # one list by day: day, then file, then row (rows without a day at the end)
        rows.sort(key=lambda r: (r["day"] is None, r["day"] or "", r["fi"], r["n"]))
    kinds = {p["fmt"] for p in parts}
    info["camt052"] = any(p["fmt"] == "camt" and cx.camt_version(p["text"]) == "052" for p in parts)  # 2.146.0 C (#2469): the hint
    return (kinds.pop() if len(kinds) == 1 else "mixed"), rows, None, parts, info


def _row_out(r):
    return {k: (dstr(r[k]) if k == "amount" and r[k] is not None else r.get(k)) for k in
            ("n", "day", "amount", "currency", "counterpart", "purpose", "iban", "ref", "error", "dup", "file", "pending")}


def _info_out(info):
    return {"files": info["files"], "file_errors": info["file_errors"], "skipped_files": info["skipped_files"][:100],
            "camt052": bool(info.get("camt052"))}  # 2.146.0 C (#2469)


@app.post("/api/office/bank/import/preview")
def bnk_preview():
    """{text, filename?, mapping?}: CSV without a mapping -> {fmt: csv, columns, sample, delimiter, guess}; CAMT or CSV
    with a mapping -> {fmt, rows, count, dup_count, skipped}. Nothing is stored."""
    c, uid, oid = _ctx()
    b = _req()  # 2.144.1 B (#2450): or a multipart upload (files, several / a ZIP)
    fmt, rows, cols, parts, info = bnk_parse(c, oid, b)
    from .cfbank import cfb_preview
    extra = cfb_preview(c, oid, fmt, b, cols, parts)  # 2.124.0 D (#2342): the statement's balances / the guessed balance column
    if rows is None:
        return jsonify(fmt=fmt, **cols, **extra, **_info_out(info))
    ok = [r for r in rows if not r["error"] and not r["pending"]]  # 2.146.0 C (#2469): pending ones counted apart
    return jsonify(fmt=fmt, rows=[_row_out(r) for r in rows], count=sum(1 for r in ok if not r["dup"]),
                   dup_count=sum(1 for r in ok if r["dup"]), pending_count=sum(1 for r in rows if not r["error"] and r["pending"]),
                   skipped=sum(1 for r in rows if r["error"]), **extra, **_info_out(info))


def _import_public(r):
    return {k: r[k] for k in ("id", "filename", "fmt", "count", "dup_count", "created_at", "undone_at")}


@app.post("/api/office/bank/import")
def bnk_import():
    """{text, filename?, mapping? (CSV)} -> 201 {import, count, dup_count, skipped}. The file is read again here (the
    preview's rows are never taken from the client); duplicates and unreadable rows are skipped."""
    c, uid, oid = _ctx()
    b = _req()  # 2.144.1 B (#2450): or a multipart upload (files, several / a ZIP)
    fs = _uploads(b)
    if b.get("mapping") is None and any(not bnk_is_camt(f["text"]) and not bnk_is_mt940(f["text"]) for f in fs.files):
        raise BadInput(tr("Please choose the columns for the date and the amount"))
    write_lock(c, f"office_bank_import_{oid}")
    fmt, rows, _cols, parts, info = bnk_parse(c, oid, b, fs)
    new = [r for r in rows if not r["error"] and not r["dup"] and not r["pending"]]  # 2.146.0 C (#2469): never a pending one
    dup = sum(1 for r in rows if not r["error"] and r["dup"])
    if not new and not dup:
        raise BadInput(tr("Nothing to import"))
    ts = iso(now_utc())
    fname = _clean(info["label"], 200)
    iid = insert_id(c, "INSERT INTO office_bank_imports(org_id, filename, fmt, count, dup_count, created_by, created_at) VALUES(?,?,?,?,?,?,?)",
                    (oid, fname, fmt, len(new), dup, uid, ts))
    for r in new:
        row = {"org_id": oid, "import_id": iid, "day": r["day"], "amount": dstr(r["amount"]), "currency": r["currency"],
               "counterpart": r["counterpart"], "purpose": r["purpose"], "iban": r["iban"], "ref": r["ref"], "hash": r["hash"],
               "rkeys": " ".join(r["rkeys"]), "created_at": ts}
        row = oc_enc_fields(c, oid, "office_bank_tx", row)
        c.execute(f"INSERT INTO office_bank_tx({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    from .cfbank import cfb_store
    bal_n = cfb_store(c, oid, iid, fmt, b, ts, parts)  # 2.124.0 D (#2342): the statement's balances, counted while the import is active
    bump(c)
    c.commit()
    imp = c.execute("SELECT * FROM office_bank_imports WHERE id=?", (iid,)).fetchone()
    return jsonify({"import": _import_public(imp), "count": len(new), "dup_count": dup,
                    "pending_count": sum(1 for r in rows if not r["error"] and r["pending"]),
                    "skipped": sum(1 for r in rows if r["error"]), "balances": bal_n, **_info_out(info)}), 201


@app.get("/api/office/bank/imports")
def bnk_imports():
    c, uid, oid = _ctx()
    return jsonify(items=[_import_public(r) for r in c.execute(
        "SELECT * FROM office_bank_imports WHERE org_id=? ORDER BY id DESC LIMIT 200", (oid,))])


def _import_row(c, oid, iid):
    r = c.execute("SELECT * FROM office_bank_imports WHERE id=? AND org_id=?", (iid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return r


@app.post("/api/office/bank/imports/<int:iid>/undo")
def bnk_import_undo(iid):
    """Takes an import back: its bookings go (deleted_at; the client's undo restores them). 409 while one is matched."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_import_{oid}")
    r = _import_row(c, oid, iid)
    if r["undone_at"]:
        raise Denied(409, tr("This import was already taken back"))
    if c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND import_id=? AND deleted_at IS NULL AND match_kind IS NOT NULL LIMIT 1",
                 (oid, iid)).fetchone():
        raise Denied(409, tr("Bookings of this import are matched; undo the matches first"))
    ts = iso(now_utc())
    c.execute("UPDATE office_bank_tx SET deleted_at=? WHERE org_id=? AND import_id=? AND deleted_at IS NULL AND match_kind IS NULL", (ts, oid, iid))
    c.execute("UPDATE office_bank_imports SET undone_at=? WHERE id=? AND org_id=?", (ts, iid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, item=_import_public(_import_row(c, oid, iid)))


@app.post("/api/office/bank/imports/<int:iid>/restore")
def bnk_import_restore(iid):
    """The undo of a take-back: the bookings removed with it come back (one imported again meanwhile stays away)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_import_{oid}")
    r = _import_row(c, oid, iid)
    if not r["undone_at"]:
        raise Denied(409, tr("This import is active"))
    have, refs = _hashes(c, oid), _rkeys(c, oid)
    back = 0
    for t in c.execute("SELECT id, hash, rkeys FROM office_bank_tx WHERE org_id=? AND import_id=? AND deleted_at=?", (oid, iid, r["undone_at"])).fetchall():
        if have.get(t["hash"]) or any(k in refs for k in (t["rkeys"] or "").split()):  # 2.146.0 C (#2469): or by reference
            continue
        c.execute("UPDATE office_bank_tx SET deleted_at=NULL WHERE id=? AND org_id=?", (t["id"], oid))
        back += 1
    c.execute("UPDATE office_bank_imports SET undone_at=NULL, count=? WHERE id=? AND org_id=?", (back, iid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, item=_import_public(_import_row(c, oid, iid)))


# ---------------------------------------------------------------- matching
def _receipts(c, oid, frm, to, uid):
    """books.bk_receipts (part A): the receipts of the area uid sees -- [] while it is not there."""
    try:
        from .books import bk_receipts
    except ImportError:
        return []
    return bk_receipts(c, oid, frm, to, uid=uid)


def _shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def bnk_open_invoices(c, oid):
    """Finalised, open invoices of the area: [{id, number, client, title, currency, open (Decimal), gross, date, due}]."""
    from .invoices import _j, inv_money_fields, inv_paid_map
    rows = c.execute("SELECT d.*, cl.name AS client_name FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id "
                     "WHERE d.org_id=? AND d.kind='invoice' AND d.locked_at IS NOT NULL AND d.status NOT IN ('draft', 'cancelled', 'paid')",
                     (oid,)).fetchall()
    pm = inv_paid_map(c, oid, [r["id"] for r in rows])
    out = []
    for r in rows:
        o = dec(inv_money_fields(r, pm)["open"])
        if o <= 0:
            continue
        out.append({"id": r["id"], "number": r["number"] or "", "client": r["client_name"] or "", "title": r["project_title"] or "",
                    "currency": (r["currency"] or "EUR").upper(), "open": money(o),
                    "gross": money(dec(_j(r["totals"], {}).get("gross") or 0)), "date": r["date"] or "", "due": r["due_date"] or ""})
    return out


def _name_hit(a, b):
    """Some word (3+ letters) of name a appears in text b."""
    wb = set(_norm(b).split())
    return any(len(w) >= 3 and w in wb for w in _norm(a).split())


def bnk_suggest(t, invoices, receipts, taken):
    """At most 3 suggestions [{kind, id, label, amount, reason}] for open booking t (amount signed Decimal)."""
    out = []
    amt = t["amount"]
    text = f"{t['counterpart']} {t['purpose']}"
    if amt > 0:
        for i in invoices:
            if i["currency"] != t["currency"] or amt > i["open"]:
                continue
            score, why = 0, []
            if amt == i["open"]:
                score += 3
                why.append(tr("same amount as open"))
            if i["number"] and _norm(i["number"]) and f" {_norm(i['number'])} " in f" {_norm(t['purpose'])} ":
                score += 4
                why.append(tr("invoice number in the purpose"))
            if i["client"] and _name_hit(i["client"], t["counterpart"] or text):
                score += 2
                why.append(tr("name matches"))
            if score >= 2:
                if amt < i["open"]:
                    why.append(tr("part payment"))
                out.append((score, {"kind": "invoice", "id": i["id"], "label": " · ".join(x for x in (i["number"], i["client"] or i["title"]) if x),
                                    "amount": dstr(i["open"]), "reason": ", ".join(why)}))
    elif amt < 0:
        for r in receipts:
            if r["node_id"] in taken or r.get("paid_at"):
                continue
            if abs((date.fromisoformat(r["date"][:10]) - date.fromisoformat(t["day"])).days) > BNK_WINDOW:
                continue
            score, why = 0, []
            if money(dec(r["amount"])) == -amt:
                score += 3
                why.append(tr("same amount"))
            name = f"{r.get('title') or ''} {r.get('category') or ''}"
            if t["counterpart"] and _name_hit(t["counterpart"], name):
                score += 2
                why.append(tr("name matches"))
            if score >= 2:
                why.append(tr("date close"))
                out.append((score, {"kind": "receipt", "id": r["node_id"], "label": r.get("title") or "", "amount": dstr(money(dec(r["amount"]))),
                                    "reason": ", ".join(why), "date": r["date"]}))
    out.sort(key=lambda x: -x[0])
    return [x[1] for x in out[:3]]


def _tx_dec(c, oid, r):
    d = oc_dec_fields(c, oid, "office_bank_tx", r)
    d["amount"] = money(dec(d["amount"]))
    return d


def _tx_public(t, inv_by_id, rc_by_id):
    m = None
    if t["match_kind"]:
        m = {"kind": t["match_kind"], "id": t["match_id"], "label": "", "at": t["matched_at"]}
        if t["match_kind"] == "invoice":
            i = inv_by_id.get(t["match_id"])
            m["label"] = " · ".join(x for x in (i["number"], i["client"]) if x) if i else ""
        elif t["match_kind"] == "receipt":
            r = rc_by_id.get(t["match_id"])
            m["label"] = (r.get("title") or "") if r else ""
    return {"id": t["id"], "day": t["day"], "amount": dstr(t["amount"]), "currency": t["currency"], "counterpart": t["counterpart"] or "",
            "purpose": t["purpose"] or "", "iban": t["iban"], "ref": t["ref"], "import_id": t["import_id"], "match": m}


def _inv_labels(c, oid, ids):
    if not ids:
        return {}
    ids = list(ids)
    q = ",".join("?" * len(ids))
    return {r["id"]: {"number": r["number"] or "", "client": r["client_name"] or r["project_title"] or ""} for r in c.execute(
        f"SELECT d.id, d.number, d.project_title, cl.name AS client_name FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id "
        f"WHERE d.org_id=? AND d.id IN ({q})", [oid] + ids)}


@app.get("/api/office/bank/tx")
def bnk_tx_list():
    """?state=open|matched|all (default open)&from&to (ISO days) -> {items: [... with suggestions on open ones], currency,
    counts: {open, matched}}. Newest first, at most 2000."""
    c, uid, oid = _ctx()
    st = request.args.get("state") or "open"
    if st not in BNK_STATES:
        raise BadInput(tr("Invalid value: {0}", "state"))
    q, args = "SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL", [oid]
    for k, op in (("from", ">="), ("to", "<=")):
        v = request.args.get(k) or ""
        if v:
            if not DATE_RE.match(v):
                raise BadInput(tr("Invalid value: {0}", k))
            q += f" AND day{op}?"
            args.append(v)
    counts = {"open": 0, "matched": 0}
    for r in c.execute("SELECT match_kind IS NULL AS o, COUNT(*) AS n FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL GROUP BY 1", (oid,)):
        counts["open" if r["o"] else "matched"] += r["n"]
    if st == "open":
        q += " AND match_kind IS NULL"
    elif st == "matched":
        q += " AND match_kind IS NOT NULL"
    rows = [_tx_dec(c, oid, r) for r in c.execute(q + f" ORDER BY day DESC, id DESC LIMIT {BNK_LIST_MAX}", args).fetchall()]
    receipts, invoices = [], []
    if rows:
        receipts = _receipts(c, oid, _shift(min(t["day"] for t in rows), -BNK_WINDOW), _shift(max(t["day"] for t in rows), BNK_WINDOW), uid)
        if any(t["match_kind"] is None and t["amount"] > 0 for t in rows):
            invoices = bnk_open_invoices(c, oid)
    taken = {r[0] for r in c.execute("SELECT match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt'", (oid,))}
    inv_lbl = _inv_labels(c, oid, {t["match_id"] for t in rows if t["match_kind"] == "invoice"})
    rc_by_id = {r["node_id"]: r for r in receipts}
    items = []
    for t in rows:
        p = _tx_public(t, inv_lbl, rc_by_id)
        if t["match_kind"] is None:
            p["suggestions"] = bnk_suggest(t, invoices, receipts, taken)
        items.append(p)
    return jsonify(items=items, currency=_home(c, oid), counts=counts)


@app.get("/api/office/bank/tx/<int:tid>/candidates")
def bnk_candidates(tid):
    """?q= -> what booking tid can be matched with: open invoices (money in) or receipts of +-60 days (money out), filtered
    by number / name / title; at most 30."""
    c, uid, oid = _ctx()
    t = _tx_dec(c, oid, _tx_row(c, oid, tid))
    q = _norm(request.args.get("q") or "")[:100]
    out = []
    if t["amount"] > 0:
        for i in bnk_open_invoices(c, oid):
            if i["currency"] != t["currency"]:
                continue
            lbl = " · ".join(x for x in (i["number"], i["client"] or i["title"]) if x)
            if q and q not in _norm(f"{lbl} {i['title']} {dstr(i['open'])}"):
                continue
            out.append({"kind": "invoice", "id": i["id"], "label": lbl, "amount": dstr(i["open"]), "date": i["date"]})
    else:
        taken = {r[0] for r in c.execute("SELECT match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt'", (oid,))}
        for r in _receipts(c, oid, _shift(t["day"], -60), _shift(t["day"], 60), uid):
            if r["node_id"] in taken or r.get("paid_at"):
                continue
            lbl = r.get("title") or ""
            if q and q not in _norm(f"{lbl} {r.get('category') or ''} {dstr(money(dec(r['amount'])))}"):
                continue
            out.append({"kind": "receipt", "id": r["node_id"], "label": lbl, "amount": dstr(money(dec(r["amount"]))), "date": r["date"]})
    return jsonify(items=out[:30])


def _tx_row(c, oid, tid):
    r = c.execute("SELECT * FROM office_bank_tx WHERE id=? AND org_id=? AND deleted_at IS NULL", (tid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return r


def _tx_answer(c, oid, uid, tid):
    t = _tx_dec(c, oid, _tx_row(c, oid, tid))
    inv = _inv_labels(c, oid, {t["match_id"]} if t["match_kind"] == "invoice" else set())
    rc = {}
    if t["match_kind"] == "receipt":
        rc = {r["node_id"]: r for r in _receipts(c, oid, t["day"], t["day"], uid)}
    return _tx_public(t, inv, rc)


@app.post("/api/office/bank/tx/<int:tid>/match")
def bnk_match(tid):
    """{kind: invoice|receipt|private|ignored, id?} -> the booking. invoice: a payment (day, amount of the booking, transfer)
    on that open invoice (a smaller amount = partly paid); receipt: its payment day = the booking's day. 409 when the booking
    is matched already, the direction or currency does not fit or the amount exceeds the open rest; foreign ids 404."""
    from .invoices import inv_pay_add
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    kind = b.get("kind")
    if kind not in BNK_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    write_lock(c, f"office_bank_tx_{tid}")
    t = _tx_dec(c, oid, _tx_row(c, oid, tid))
    if t["match_kind"]:
        raise Denied(409, tr("This booking is matched already"))
    mid = pid = None
    if kind in ("invoice", "receipt"):
        try:
            mid = int(b.get("id"))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "id")) from None
    if kind == "invoice":
        from .docs import doc_row
        r = doc_row(c, oid, mid)  # 404 outside the area
        if t["amount"] <= 0:
            raise Denied(409, tr("Only money received can pay an invoice"))
        if (r["currency"] or "EUR").upper() != t["currency"]:
            raise Denied(409, tr("The invoice has another currency"))
        if t["day"] > date.today().isoformat():  # a booking marked in advance (value date tomorrow) cannot pay yet
            raise Denied(409, tr("The booking lies in the future, match it on its day"))
        pid = inv_pay_add(c, oid, uid, mid, {"date": t["day"], "amount": dstr(t["amount"]), "method": "transfer"})
    elif kind == "receipt":
        from .books import bk_receipt_set_paid
        from ..files.store import fs_role
        if t["amount"] >= 0:
            raise Denied(409, tr("Only money paid out can pay a receipt"))
        if c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt' AND match_id=? LIMIT 1",
                     (oid, mid)).fetchone():
            raise Denied(409, tr("This receipt is matched with another booking"))
        if not fs_role(c, mid, uid):  # as bk_receipts: only documents the person sees
            raise Denied(404)
        bk_receipt_set_paid(c, oid, mid, t["day"])  # 404 outside the area
    c.execute("UPDATE office_bank_tx SET match_kind=?, match_id=?, payment_id=?, matched_by=?, matched_at=? WHERE id=? AND org_id=?",
              (kind, mid, pid, uid, iso(now_utc()), tid, oid))
    bump(c)
    c.commit()
    return jsonify(_tx_answer(c, oid, uid, tid))


@app.post("/api/office/bank/tx/<int:tid>/unmatch")
def bnk_unmatch(tid):
    """Undoes the match of a booking: the payment it booked goes (state of the invoice follows), the receipt's payment day
    goes. Answers the booking and the match it had ({kind, id}; the client's undo posts it to /match again)."""
    from .invoices import inv_pay_del
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_tx_{tid}")
    t = _tx_row(c, oid, tid)
    if not t["match_kind"]:
        raise Denied(409, tr("This booking is not matched"))
    was = {"kind": t["match_kind"], "id": t["match_id"]}
    if t["match_kind"] == "invoice" and t["payment_id"]:
        try:
            inv_pay_del(c, oid, t["match_id"], t["payment_id"], uid=uid)
        except Denied as e:  # removed by hand meanwhile (2.152.0 C (#2168): or already reversed by hand = 409)
            if e.code not in (404, 409):
                raise
    elif t["match_kind"] == "receipt":
        from .books import bk_receipt_set_paid
        try:
            bk_receipt_set_paid(c, oid, t["match_id"], None)
        except Denied as e:  # the receipt is gone
            if e.code != 404:
                raise
    c.execute("UPDATE office_bank_tx SET match_kind=NULL, match_id=NULL, payment_id=NULL, matched_by=NULL, matched_at=NULL WHERE id=? AND org_id=?",
              (tid, oid))
    bump(c)
    c.commit()
    return jsonify(item=_tx_answer(c, oid, uid, tid), was=was)
