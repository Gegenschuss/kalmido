"""2.148.0 D (#2458): the DATEV import -- master data and booking batches the tax advisor sends (the other way round of
office/datev.py).

A file in the DATEV format (EXTF, also DTVF): Windows-1252 (or UTF-8 with / without BOM), semicolons, text in double quotes,
CRLF. Line 1 = the header (category 16 "Debitoren/Kreditoren" or 21 "Buchungsstapel", its format version, the ledger
length, the start of the fiscal year), line 2 = the column names (read by NAME, never by position), then the rows.
 - category 16: a debtor account (ledger length + 1 digits, first digit 1-6, like datev.py dx_debtor) becomes a client
   (customer_no = the account): a client of the office with the same customer number (else with the same name and no
   number) only gets its EMPTY fields filled (nothing is overwritten; the preview names what differs), else a new client.
   A creditor account (first digit 7-9) becomes a supplier (office_suppliers, name / address / VAT id / IBAN encrypted at
   rest); datevin.py books a receipt whose sender matches a supplier's name on its creditor account.
 - category 21: only the opening bookings (account or counter account 9000 / 9008 / 9009, stretched to the ledger length, or
   a booking text starting with "EB") become opening balances of their year (office_opening_balances); every other booking is
   counted, never taken over (Kalmido is no financial accounting). Importing the same account and year again replaces it.
   An opening booking in a locked month (office/periodlock.py) refuses the whole file (409).
Flow like the other imports: POST .../check = the preview (nothing written), POST .../import = one run in
office_import_runs (kind "datev"); undo per run removes what the run made (a client something builds on stays), empties
the fields it filled while they still hold the imported value and puts replaced opening balances back. Admins only
(a personal office: its owner); agents never reach it (office_gate)."""
import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.pg import insert_id, write_lock
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..personal.timetrack import BadInput
from .model import office_gate, office_org, office_settings, pb_cl_org, pb_cl_sql

DI_MAX = 10 * 1024 * 1024       # the uploaded file
DI_ROWS_MAX = 20000             # data rows of one file
DI_PREVIEW = 20                 # rows shown in the preview
DI_TRASH_DAYS = 30              # a deleted supplier (undo possible) is purged after this
DI_MAX_TEXT = {"name": 80, "street": 200, "zip": 20, "city": 120, "country": 2, "vat_id": 20, "iban": 34, "email": 200, "label": 60}
DI_EB = ("9000", "9008", "9009")  # Saldenvorträge Sachkonten / Debitoren / Kreditoren (SKR03 and SKR04)
DI_VERSIONS = {16: range(1, 6), 21: range(2, 14)}

DI_BAD_HEAD = N_("This is no DATEV file (EXTF): the first line must start with \"EXTF\"")
DI_BAD_CAT = N_("Only DATEV master data of debtors / creditors (category 16) and booking batches (category 21) can be read")
DI_BAD_VER = N_("Unsupported format version {0} of the DATEV file")
DI_NO_COLS = N_("The column names in line 2 are missing ({0})")
DI_TOO_BIG = N_("The file is too large (at most {0} MB)")
DI_TOO_MANY = N_("The file has more than {0} rows")
DI_UNREADABLE = N_("The file cannot be read as CSV")
DI_NOT_FIBU = N_("Kalmido is no financial accounting: only opening balances are taken over")
R_NO_ACCOUNT = N_("No account number")
R_NOT_DC = N_("Account {0} is neither a debtor nor a creditor account")
R_NO_NAME = N_("Name missing")
R_TWICE = N_("Account {0} appears twice in the file")
R_SAME = N_("Nothing new")
R_EMAIL = N_("E-mail address not valid: left out")
R_COUNTRY = N_("Country not recognised: left out")
R_NOT_EB = N_("No opening booking")
R_DATE = N_("Document date not valid")
R_AMOUNT = N_("Amount not valid")
R_REPLACE = N_("Replaces the opening balance of account {0} in {1}")
R_SAME_NAME = N_("Same name, no customer number yet")

_TEXT_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# the columns this module reads, by their normalised DATEV name (see _norm)
DI_COLS = {
    "account": ("konto",),
    "company": ("nameadressatentypunternehmen",),
    "last": ("nameadressatentypnatürlperson", "nameadressatentypnatperson"),
    "first": ("vornameadressatentypnatürlperson", "vornameadressatentypnatperson"),
    "plain": ("nameadressatentypkeineangabe",),
    "short": ("kurzbezeichnung",),
    "street": ("straße", "strasse"),
    "zip": ("postleitzahl",),
    "city": ("ort",),
    "country": ("land",),
    "eu_land": ("euland",),
    "vat_id": ("euustid", "ustid"),
    "email": ("email",),
    "iban": ("ibannr1", "iban1", "ibannr", "iban"),
    "amount": ("umsatzohnesollhabenkz", "umsatz"),
    "side": ("sollhabenkennzeichen",),
    "counter": ("gegenkontoohnebuschlüssel", "gegenkonto"),
    "day": ("belegdatum",),
    "text": ("buchungstext",),
}


def _norm(name):
    return re.sub(r"[^0-9a-zäöüß]+", "", str(name or "").casefold())


def _txt(v, key):
    v = re.sub(r"\s+", " ", _TEXT_CTRL.sub(" ", str(v or ""))).strip()
    return v[:DI_MAX_TEXT[key]]


# ---------------------------------------------------------------- reading the file
def di_decode(raw):
    """The file's text: UTF-8 with BOM, else UTF-8 when it decodes (a Windows-1252 text with umlauts never does), else
    Windows-1252 (DATEV's own encoding)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def di_parse(raw):
    """The file -> {category, version, acct_len, fy_start (date | None), cols {key: index}, rows [[...]]}. BadInput (400)
    with a readable reason on a wrong header, missing columns or too many rows; 413 when too large."""
    if len(raw) > DI_MAX:
        raise Denied(413, tr(DI_TOO_BIG, DI_MAX // (1024 * 1024)))
    text = di_decode(raw)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=";", quotechar='"')
        head = next(reader, None)
        names = next(reader, None)
        rows = []
        for r in reader:
            if not any(x.strip() for x in r):
                continue
            rows.append(r)
            if len(rows) > DI_ROWS_MAX:
                raise BadInput(tr(DI_TOO_MANY, DI_ROWS_MAX))
    except csv.Error:
        raise BadInput(tr(DI_UNREADABLE)) from None
    if not head or head[0].strip().upper() not in ("EXTF", "DTVF"):
        raise BadInput(tr(DI_BAD_HEAD))
    try:
        cat = int((head[2] if len(head) > 2 else "").strip())
    except ValueError:
        cat = 0
    if cat not in DI_VERSIONS:
        raise BadInput(tr(DI_BAD_CAT))
    ver = (head[4] if len(head) > 4 else "").strip()
    if not ver.isdigit() or int(ver) not in DI_VERSIONS[cat]:
        raise BadInput(tr(DI_BAD_VER, ver[:10] or "?"))
    alen = (head[13] if len(head) > 13 else "").strip()
    fy = (head[12] if len(head) > 12 else "").strip()
    try:
        fy_start = datetime.strptime(fy, "%Y%m%d").date() if fy else None
    except ValueError:
        fy_start = None
    idx = {}
    for i, n in enumerate(names or []):
        k = _norm(n)
        for key, aliases in DI_COLS.items():
            if k in aliases and key not in idx:
                idx[key] = i
    need = ("account",) if cat == 16 else ("account", "amount", "side", "counter", "day")
    miss = [k for k in need if k not in idx]
    if miss:
        raise BadInput(tr(DI_NO_COLS, ", ".join(miss)))
    return {"category": cat, "version": int(ver), "acct_len": int(alen) if alen.isdigit() and 4 <= int(alen) <= 8 else None,
            "fy_start": fy_start, "cols": idx, "rows": rows}


def _cell(p, r, key):
    i = p["cols"].get(key)
    return r[i] if i is not None and i < len(r) else ""


def _acct_len(c, oid, p):
    """The ledger length: the file's, else the DATEV settings'."""
    if p["acct_len"]:
        return p["acct_len"]
    from .datev import dx_settings
    return int(dx_settings(office_settings(c, oid))["acct_len"])


# ---------------------------------------------------------------- category 16: debtors / creditors
def _person(p, r):
    """The name of a master data row: company, else first + last name, else the name without type, else the short name."""
    n = _cell(p, r, "company").strip()
    if not n:
        n = " ".join(x for x in (_cell(p, r, "first").strip(), _cell(p, r, "last").strip()) if x)
    return _txt(n or _cell(p, r, "plain") or _cell(p, r, "short"), "name")


def _vat(p, r):
    v = re.sub(r"\s+", "", _cell(p, r, "vat_id")).upper()
    land = re.sub(r"[^A-Z]", "", _cell(p, r, "eu_land").upper())[:2]
    if v and land and not re.match(r"[A-Z]{2}", v):
        v = land + v
    return v[:DI_MAX_TEXT["vat_id"]]


def _master_row(p, r, notes):
    from .countries import fk_country_code
    out = {"name": _person(p, r), "street": _txt(_cell(p, r, "street"), "street"), "zip": _txt(_cell(p, r, "zip"), "zip"),
           "city": _txt(_cell(p, r, "city"), "city"), "vat_id": _vat(p, r)}
    cc = fk_country_code(_cell(p, r, "country"))
    if cc is None:
        notes.append(tr(R_COUNTRY))
        cc = ""
    out["country"] = cc
    mail = _txt(_cell(p, r, "email"), "email")
    if mail and not _EMAIL.fullmatch(mail):
        notes.append(tr(R_EMAIL))
        mail = ""
    out["email"] = mail
    out["iban"] = re.sub(r"\s+", "", _cell(p, r, "iban")).upper()[:DI_MAX_TEXT["iban"]]
    return out


DI_CLIENT_FIELDS = ("street", "zip", "city", "country", "vat_id", "email")
DI_SUPPLIER_FIELDS = ("street", "zip", "city", "country", "vat_id", "iban")


def di_suppliers(c, oid, deleted=False):
    """The suppliers of office area oid (decrypted), by account."""
    rows = c.execute("SELECT * FROM office_suppliers WHERE org_id=? AND deleted_at IS " + ("NOT NULL" if deleted else "NULL")
                     + " ORDER BY account_no, id", (oid,)).fetchall()
    return [oc_dec_fields(c, oid, "office_suppliers", r) for r in rows]


def _plan16(c, oid, p):
    """The plan of a master data file: [{row, account, kind debtor | creditor, action new | update | skip, target id, values,
    fill, differ, reason, notes}]."""
    from .legacyimport import fi_norm
    n = _acct_len(c, oid, p)
    clients = c.execute(f"SELECT * FROM clients WHERE {pb_cl_sql(c, oid)} ORDER BY id", ()).fetchall()
    by_no = {}
    by_name = {}
    for x in clients:
        no = (x["customer_no"] or "").strip()
        if no:
            by_no.setdefault(no, x)
        elif fi_norm(x["name"]):
            by_name.setdefault(fi_norm(x["name"]), x)
    sups = {}
    for x in di_suppliers(c, oid):
        sups.setdefault(x["account_no"], x)
    seen = set()
    plan = []
    for i, r in enumerate(p["rows"]):
        notes = []
        acct = re.sub(r"\s+", "", _cell(p, r, "account"))
        item = {"row": i + 3, "account": acct[:12], "kind": "", "action": "skip", "id": None, "values": {}, "fill": {}, "differ": {},
                "reason": "", "notes": notes}
        plan.append(item)
        if not acct:
            item["reason"] = tr(R_NO_ACCOUNT)
            continue
        if re.fullmatch(r"[1-6]\d{%d}" % n, acct):
            item["kind"] = "debtor"
        elif re.fullmatch(r"[7-9]\d{%d}" % n, acct):
            item["kind"] = "creditor"
        else:
            item["reason"] = tr(R_NOT_DC, acct[:12])
            continue
        if acct in seen:
            item["reason"] = tr(R_TWICE, acct)
            continue
        seen.add(acct)
        v = _master_row(p, r, notes)
        item["values"] = {k: v[k] for k in ("name", *(DI_CLIENT_FIELDS if item["kind"] == "debtor" else DI_SUPPLIER_FIELDS))}
        if not v["name"]:
            item["reason"] = tr(R_NO_NAME)
            continue
        if item["kind"] == "debtor":
            cur = by_no.get(acct)
            if cur is None and fi_norm(v["name"]) in by_name:
                cur = by_name.pop(fi_norm(v["name"]))
                notes.append(tr(R_SAME_NAME))
                item["fill"]["customer_no"] = acct
            fields = DI_CLIENT_FIELDS
        else:
            cur = sups.get(acct)
            fields = DI_SUPPLIER_FIELDS
        if cur is None:
            item["action"] = "new"
            continue
        item["id"] = cur["id"]
        item["current"] = cur["name"] or ""
        for k in fields:
            nv, ov = v[k], (cur[k] or "").strip()
            if not nv:
                continue
            if not ov:
                item["fill"][k] = nv
            elif ov.casefold() != nv.casefold():
                item["differ"][k] = {"now": ov, "file": nv}
        if item["fill"]:
            item["action"] = "update"
        else:
            item["reason"] = tr(R_SAME)
    return plan


def _counts16(plan):
    out = {"new": 0, "updated": 0, "skipped": 0, "debtors": 0, "creditors": 0}
    for x in plan:
        out[{"new": "new", "update": "updated"}.get(x["action"], "skipped")] += 1
        if x["action"] != "skip":
            out["debtors" if x["kind"] == "debtor" else "creditors"] += 1
    return out


def _apply16(c, oid, uid, rid, plan, ts):
    from ..team.clients import clean_client
    filled_c, filled_s = {}, {}
    for x in plan:
        if x["action"] == "new" and x["kind"] == "debtor":
            f = {k: x["values"][k] for k in ("name", *DI_CLIENT_FIELDS) if x["values"].get(k)}
            f["customer_no"] = x["account"]
            f["org_id"] = pb_cl_org(c, oid)
            f = clean_client(c, uid, f, new=True)
            f.update(org_id=pb_cl_org(c, oid), created_by=uid, created_at=ts, updated_at=ts, import_run_id=rid)
            insert_id(c, f"INSERT INTO clients({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
        elif x["action"] == "update" and x["kind"] == "debtor":
            cur = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (x["id"],)).fetchone()
            if not cur:
                continue
            f = clean_client(c, uid, dict(x["fill"]))
            f = {k: v for k, v in f.items() if v and not (cur[k] or "").strip()}
            if f:
                c.execute(f"UPDATE clients SET {', '.join(k + '=?' for k in f)}, updated_at=? WHERE id=? AND {pb_cl_sql(c, oid)}",
                          [*f.values(), ts, x["id"]])
                filled_c[str(x["id"])] = f
        elif x["action"] == "new":
            row = {"org_id": oid, "account_no": x["account"], **{k: x["values"].get(k) or "" for k in ("name", *DI_SUPPLIER_FIELDS)},
                   "import_run_id": rid, "created_at": ts, "updated_at": ts}
            row = oc_enc_fields(c, oid, "office_suppliers", row)
            insert_id(c, f"INSERT INTO office_suppliers({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
        elif x["action"] == "update":
            r = c.execute("SELECT * FROM office_suppliers WHERE id=? AND org_id=? AND deleted_at IS NULL", (x["id"], oid)).fetchone()
            if not r:
                continue
            cur = oc_dec_fields(c, oid, "office_suppliers", r)
            f = {k: v for k, v in x["fill"].items() if k in DI_SUPPLIER_FIELDS and v and not (cur[k] or "").strip()}
            if f:
                enc = oc_enc_fields(c, oid, "office_suppliers", dict(f))
                c.execute(f"UPDATE office_suppliers SET {', '.join(k + '=?' for k in enc)}, updated_at=? WHERE id=? AND org_id=?",
                          [*enc.values(), ts, x["id"], oid])
                filled_s[str(x["id"])] = f
    return {"filled_clients": filled_c, "filled_suppliers": filled_s}


# ---------------------------------------------------------------- category 21: opening balances
def _amount(s):
    s = str(s or "").strip().replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d) >= Decimal("1e12"):
        return None
    return d.quantize(Decimal("0.01"))


def _day(s, fy_start, period_from=None):
    """The document date (DDMM, also DDMMYYYY / TTMMJJ) -> a date; the year from the fiscal year of the header."""
    s = re.sub(r"\D", "", str(s or ""))
    try:
        if len(s) == 8:
            return date(int(s[4:8]), int(s[2:4]), int(s[0:2]))
        if len(s) == 6:
            return date(2000 + int(s[4:6]), int(s[2:4]), int(s[0:2]))
        if len(s) in (3, 4):
            s = s.zfill(4)
            d, m = int(s[0:2]), int(s[2:4])
            base = fy_start or period_from or date.today().replace(month=1, day=1)
            y = base.year if (m, d) >= (base.month, base.day) else base.year + 1
            return date(y, m, d)
    except ValueError:
        return None
    return None


def _is_eb_text(t):
    t = (t or "").strip()
    return t[:2].upper() == "EB" and (len(t) == 2 or not t[2].isalpha())


def _plan21(c, oid, p):
    n = _acct_len(c, oid, p)
    eb = {a.ljust(n, "0") for a in DI_EB} | set(DI_EB)
    plan = []
    for i, r in enumerate(p["rows"]):
        acct, ctr = re.sub(r"\s+", "", _cell(p, r, "account")), re.sub(r"\s+", "", _cell(p, r, "counter"))
        text = _txt(_cell(p, r, "text"), "label")
        item = {"row": i + 3, "account": "", "label": text, "amount": None, "side": "", "year": None, "day": "", "action": "skip", "reason": ""}
        plan.append(item)
        side = _cell(p, r, "side").strip().upper()[:1]
        if acct in eb and ctr not in eb:
            account, side = ctr, ("H" if side == "S" else "S")  # the booking seen from the account opened
        elif ctr in eb or _is_eb_text(text):
            account = acct
        else:
            item.update(account=acct[:12], reason=tr(R_NOT_EB), action="other")
            continue
        item["account"] = account[:12]
        if not account.isdigit():
            item["reason"] = tr(R_NO_ACCOUNT)
            continue
        amt = _amount(_cell(p, r, "amount"))
        if amt is None or side not in ("S", "H"):
            item["reason"] = tr(R_AMOUNT)
            continue
        if amt < 0:
            amt, side = -amt, ("H" if side == "S" else "S")
        d = _day(_cell(p, r, "day"), p["fy_start"])
        if d is None:
            item["reason"] = tr(R_DATE)
            continue
        item.update(amount=format(amt, "f"), side=side, year=d.year, day=d.isoformat(), action="new")
    have = {}
    for x in plan:
        if x["action"] == "new":
            key = (x["year"], x["account"])
            if key not in have:
                have[key] = c.execute("SELECT COUNT(*) AS n FROM office_opening_balances WHERE org_id=? AND year=? AND account=?",
                                      (oid, x["year"], x["account"])).fetchone()["n"]
                if have[key]:
                    x["action"] = "replace"
                    x["reason"] = tr(R_REPLACE, x["account"], x["year"])
    return plan


def _counts21(plan):
    out = {"opening": 0, "replaced": 0, "other": 0, "skipped": 0}
    for x in plan:
        if x["action"] in ("new", "replace"):
            out["opening"] += 1
            out["replaced"] += x["action"] == "replace"
        elif x["action"] == "other":
            out["other"] += 1
        else:
            out["skipped"] += 1
    return out


def _check_locks(c, oid, plan):
    from .periodlock import period_need_open
    days = sorted({x["day"] for x in plan if x.get("day") and x["action"] in ("new", "replace")})
    period_need_open(c, oid, *days)


def _apply21(c, oid, rid, plan, ts):
    keys = sorted({(x["year"], x["account"]) for x in plan if x["action"] in ("new", "replace")})
    replaced = []
    for y, a in keys:
        for r in c.execute("SELECT * FROM office_opening_balances WHERE org_id=? AND year=? AND account=?", (oid, y, a)).fetchall():
            replaced.append({"year": r["year"], "account": r["account"], "label": r["label"], "amount": format(Decimal(str(r["amount"])), "f"),
                             "side": r["side"], "import_run_id": r["import_run_id"], "created_at": r["created_at"]})
        c.execute("DELETE FROM office_opening_balances WHERE org_id=? AND year=? AND account=?", (oid, y, a))
    for x in plan:
        if x["action"] in ("new", "replace"):
            c.execute("INSERT INTO office_opening_balances(org_id, year, account, label, amount, side, import_run_id, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (oid, x["year"], x["account"], x["label"], x["amount"], x["side"], rid, ts))
    return {"replaced": replaced}


def di_opening(c, oid, year):
    """The opening balances of office area oid in year: [{id, account, label, amount, side}] + debit / credit sums."""
    rows = c.execute("SELECT * FROM office_opening_balances WHERE org_id=? AND year=? ORDER BY account, id", (oid, year)).fetchall()
    out = [{"id": r["id"], "account": r["account"], "label": r["label"], "amount": format(Decimal(str(r["amount"])), "f"), "side": r["side"]}
           for r in rows]
    s = sum((Decimal(x["amount"]) for x in out if x["side"] == "S"), Decimal(0))
    h = sum((Decimal(x["amount"]) for x in out if x["side"] == "H"), Decimal(0))
    return out, format(s, "f"), format(h, "f")


# ---------------------------------------------------------------- check, import, undo
def di_plan(c, oid, raw):
    p = di_parse(raw)
    if p["category"] == 16:
        plan = _plan16(c, oid, p)
        counts = _counts16(plan)
    else:
        plan = _plan21(c, oid, p)
        counts = _counts21(plan)
        _check_locks(c, oid, plan)
    return p, plan, counts


def _public(p, plan, counts, c, oid):
    hints = []
    if p["category"] == 21 and counts["other"]:
        hints.append(tr(DI_NOT_FIBU))
    from .datev import dx_settings
    mine = int(dx_settings(office_settings(c, oid))["acct_len"])
    if p["acct_len"] and p["acct_len"] != mine:
        hints.append(tr("The file uses ledger accounts with {0} digits, your DATEV settings {1}", p["acct_len"], mine))
    rows = [x for x in plan if x["action"] != "other"] if p["category"] == 21 else plan
    keys = ("row", "account", "kind", "action", "values", "fill", "differ", "reason", "notes", "current") if p["category"] == 16 else \
        ("row", "account", "label", "amount", "side", "year", "action", "reason")
    return {"category": p["category"], "kind": "master" if p["category"] == 16 else "opening", "counts": counts, "hints": hints,
            "total": len(plan), "rows": [{k: x.get(k) for k in keys} for x in rows[:DI_PREVIEW]]}


def di_import(c, oid, uid, raw):
    write_lock(c, f"office_import_{int(oid)}")
    p, plan, counts = di_plan(c, oid, raw)
    ts = iso(now_utc())
    rid = insert_id(c, "INSERT INTO office_import_runs(org_id, kind, created_by, created_at) VALUES(?,?,?,?)", (oid, "datev", uid, ts))
    detail = _apply16(c, oid, uid, rid, plan, ts) if p["category"] == 16 else _apply21(c, oid, rid, plan, ts)
    detail["category"] = p["category"]
    # the runs list counts every int but "skipped": the entries taken over
    stored = {k: v for k, v in counts.items() if k in ("new", "updated", "opening", "skipped")}
    c.execute("UPDATE office_import_runs SET counts=?, detail=? WHERE id=? AND org_id=?", (json.dumps(stored), json.dumps(detail), rid, oid))
    return rid, p, plan, counts


def di_undo(c, oid, uid, r):
    """Undoes the DATEV run r (an office_import_runs row of oid) -> (removed, kept, files, archived) like
    legacyimport.fi_undo (whose undo route hands kind "datev" here)."""
    from .legacyimport import _client_used, bk_detail
    rid = r["id"]
    if r["undone_at"]:
        raise Denied(409, tr("This import has already been undone"))
    detail = bk_detail(r)
    ts = iso(now_utc())
    removed = {"clients": 0, "suppliers": 0, "opening": 0, "filled": 0, "restored": 0}
    kept = {"clients": 0}
    for row in c.execute(f"SELECT id FROM clients WHERE {pb_cl_sql(c, oid)} AND import_run_id=?", (rid,)).fetchall():
        if _client_used(c, oid, row["id"], rid):
            kept["clients"] += 1
            continue
        c.execute(f"DELETE FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (row["id"],))
        removed["clients"] += 1
    for cid, fill in (detail.get("filled_clients") or {}).items():
        cur = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (int(cid),)).fetchone()
        back = [k for k, v in fill.items() if cur is not None and k in ("customer_no", *DI_CLIENT_FIELDS) and (cur[k] or "") == v]
        if back:
            c.execute(f"UPDATE clients SET {', '.join(k + '=?' for k in back)}, updated_at=? WHERE id=? AND {pb_cl_sql(c, oid)}",
                      [""] * len(back) + [ts, int(cid)])
            removed["filled"] += 1
    n = c.execute("DELETE FROM office_suppliers WHERE org_id=? AND import_run_id=?", (oid, rid)).rowcount
    removed["suppliers"] = max(n or 0, 0)
    for sid, fill in (detail.get("filled_suppliers") or {}).items():
        r2 = c.execute("SELECT * FROM office_suppliers WHERE id=? AND org_id=?", (int(sid), oid)).fetchone()
        if not r2:
            continue
        cur = oc_dec_fields(c, oid, "office_suppliers", r2)
        back = [k for k, v in fill.items() if k in DI_SUPPLIER_FIELDS and (cur[k] or "") == v]
        if back:
            c.execute(f"UPDATE office_suppliers SET {', '.join(k + '=?' for k in back)}, updated_at=? WHERE id=? AND org_id=?",
                      [""] * len(back) + [ts, int(sid), oid])
            removed["filled"] += 1
    n = c.execute("DELETE FROM office_opening_balances WHERE org_id=? AND import_run_id=?", (oid, rid)).rowcount
    removed["opening"] = max(n or 0, 0)
    for x in detail.get("replaced") or []:
        if not isinstance(x, dict):
            continue
        c.execute("INSERT INTO office_opening_balances(org_id, year, account, label, amount, side, import_run_id, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?)", (oid, int(x.get("year") or 0), str(x.get("account") or "")[:12], str(x.get("label") or "")[:60],
                                              str(x.get("amount") or "0"), "H" if x.get("side") == "H" else "S", x.get("import_run_id"),
                                              x.get("created_at") or ts))
        removed["restored"] += 1
    c.execute("UPDATE office_import_runs SET undone_at=?, undone_by=? WHERE id=? AND org_id=?", (ts, uid, rid, oid))
    return removed, kept, [], []


def _ctx():
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    return c, uid, oid


def _upload():
    f = request.files.get("file")
    if not f:
        raise BadInput(tr("No file"))
    raw = f.read(DI_MAX + 1)
    if len(raw) > DI_MAX:
        raise Denied(413, tr(DI_TOO_BIG, DI_MAX // (1024 * 1024)))
    return raw


@app.post("/api/office/datev/import/check")
def di_check_post():
    """Org admin (a personal office: its owner). multipart 'file' (DATEV EXTF, category 16 or 21) -> the preview
    {category, kind master | opening, counts, hints, total, rows (the first 20)}. Nothing is stored."""
    c, uid, oid = _ctx()
    p, plan, counts = di_plan(c, oid, _upload())
    return jsonify(_public(p, plan, counts, c, oid))


@app.post("/api/office/datev/import")
def di_import_post():
    """Org admin. multipart 'file' -> takes the file over as the preview showed it: {run_id, category, counts}."""
    c, uid, oid = _ctx()
    rid, p, plan, counts = di_import(c, oid, uid, _upload())
    from .ledger import ofx_log
    ofx_log(c, oid, "import", target="datev_in", detail={"run_id": rid, "kind": p["category"], "counts": counts})
    bump(c)
    c.commit()
    return jsonify(run_id=rid, category=p["category"], counts=counts), 201


@app.post("/api/office/datev/import/<int:rid>/undo")
def di_undo_post(rid):
    """Org admin: undoes the DATEV import run rid -> {removed, kept}; 409 when already undone."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_import_{int(oid)}")
    r = c.execute("SELECT * FROM office_import_runs WHERE id=? AND org_id=? AND kind='datev'", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    removed, kept, _f, _a = di_undo(c, oid, uid, r)
    from .ledger import ofx_log
    ofx_log(c, oid, "undo", target="datev_in", detail={"run_id": rid, "removed": removed, "kept": kept})
    bump(c)
    c.commit()
    return jsonify(removed=removed, kept=kept)


# ---------------------------------------------------------------- the suppliers list (DATEV settings)
def _purge(c, oid):
    """Suppliers deleted longer than DI_TRASH_DAYS ago are removed for good."""
    cut = iso(now_utc() - timedelta(days=DI_TRASH_DAYS))
    c.execute("DELETE FROM office_suppliers WHERE org_id=? AND deleted_at IS NOT NULL AND deleted_at<?", (oid, cut))


def _sup_public(x):
    return {"id": x["id"], "account_no": x["account_no"], "name": x["name"], "street": x["street"], "zip": x["zip"], "city": x["city"],
            "country": x["country"], "vat_id": x["vat_id"], "iban": x["iban"]}


def _sup_row(c, oid, sid, deleted=False):
    r = c.execute("SELECT * FROM office_suppliers WHERE id=? AND org_id=? AND deleted_at IS " + ("NOT NULL" if deleted else "NULL"),
                  (sid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/office/datev/suppliers")
def di_suppliers_get():
    """Org admin: the suppliers (creditors) of the DATEV import {items: [{id, account_no, name, street, zip, city, country,
    vat_id, iban}]}."""
    c, uid, oid = _ctx()
    _purge(c, oid)
    c.commit()
    return jsonify(items=[_sup_public(x) for x in di_suppliers(c, oid)])


@app.put("/api/office/datev/suppliers/<int:sid>")
def di_supplier_put(sid):
    """Org admin: {name} renames a supplier."""
    c, uid, oid = _ctx()
    _sup_row(c, oid, sid)
    b = body() or {}
    if not isinstance(b.get("name"), str):
        raise BadInput(tr("Invalid value: {0}", "name"))
    name = _txt(b["name"], "name")
    if not name:
        raise BadInput(tr(R_NO_NAME))
    enc = oc_enc_fields(c, oid, "office_suppliers", {"name": name})
    c.execute("UPDATE office_suppliers SET name=?, updated_at=? WHERE id=? AND org_id=?", (enc["name"], iso(now_utc()), sid, oid))
    c.commit()
    return jsonify(_sup_public(oc_dec_fields(c, oid, "office_suppliers", _sup_row(c, oid, sid))))


@app.delete("/api/office/datev/suppliers/<int:sid>")
def di_supplier_delete(sid):
    """Org admin: deletes a supplier (restore possible for DI_TRASH_DAYS days, then removed for good)."""
    c, uid, oid = _ctx()
    _sup_row(c, oid, sid)
    c.execute("UPDATE office_suppliers SET deleted_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/datev/suppliers/<int:sid>/restore")
def di_supplier_restore(sid):
    """Org admin: puts a deleted supplier back."""
    c, uid, oid = _ctx()
    _sup_row(c, oid, sid, deleted=True)
    c.execute("UPDATE office_suppliers SET deleted_at=NULL, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    c.commit()
    return jsonify(ok=True)


@app.get("/api/office/datev/opening")
def di_opening_get():
    """Org admin: the opening balances of ?year= (default: this year) {year, years (with balances), items, debit, credit}."""
    c, uid, oid = _ctx()
    try:
        year = int(request.args.get("year") or datetime.now(timezone.utc).year)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "year")) from None
    if not 1900 <= year <= 2999:
        raise BadInput(tr("Invalid value: {0}", "year"))
    items, s, h = di_opening(c, oid, year)
    years = [r["year"] for r in c.execute("SELECT DISTINCT year FROM office_opening_balances WHERE org_id=? ORDER BY year DESC", (oid,))]
    return jsonify(year=year, years=years, items=items, debit=s, credit=h)


# ---------------------------------------------------------------- the creditor of a receipt (office/datevin.py)
def di_creditor_map(c, oid):
    """{normalised name: creditor account} of the suppliers of oid whose normalised name is unique."""
    from .legacyimport import fi_norm
    seen = {}
    for x in di_suppliers(c, oid):
        k = fi_norm(x["name"])
        if k:
            seen.setdefault(k, set()).add(x["account_no"])
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
