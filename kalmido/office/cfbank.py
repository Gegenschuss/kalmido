"""Office & finance (2.124.0 D, #2342): the account balance from the bank reconciliation -- the balances a statement carries
(office/bank.py) are stored per import and shown in the cash flow next to the computed balance of office/cfstart.py.
No bank access, no external service, never a booking of its own.

- CAMT.052 / .053: every Stmt / Rpt gives its account (Acct/Id/IBAN, else Acct/Id/Othr/Id) and its balances Bal: OPBD / PRCD
  = opening (open), CLBD / CLAV = closing (close; CLBD before CLAV on the same day); amount signed by CdtDbtInd, day from
  Dt/Dt or Dt/DtTm. Balances in another currency than the office are left out. bnk_camt's bookings stay as they are.
- CSV: an optional column "balance" in the mapping (mapping.balance, the household budget's helpers ignore it); the balance
  of the chronologically last row counts: on the newest day the last row in file order, or the first one when the file runs
  newest first (most bank exports do). The account: the IBAN of an optional column mapping.account, else the name typed
  in the import dialog (body.account; default "Main account").
- office_bank_balances: one row per balance and import (amount + account encrypted at rest, orgcrypt FIELDS). A balance
  counts while its import is active: taking the import back (bnk_import_undo) hides it, restoring brings it back.
- In the cash flow (cashflow.rk_cashflow, after cfstart.cfs_apply): bank {day, amount, accounts[], computed?, diff?,
  suggest_start} with the newest closing balance of every account added up (day = the oldest of them; an opening balance
  counts as the closing balance of the day before) and per month bank {day, amount, computed?, diff?} from the balances
  inside that month. computed = the running balance of #2341 at the end of that day. A start balance or a real balance by
  hand always wins; the bank only suggests (the client takes it over through the routes of cfstart.py).
Only for the admins of the office area (the cash flow and the bank reconciliation are admin only); a person without an
organisation is the admin of the personal office."""
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal

from ..core import mt940 as mt  # 2.299.0 A (#3190)
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.errors import BadInput
from .calc import dec, dstr, money

CFB_OPEN = ("OPBD", "PRCD")
CFB_CLOSE = ("CLBD", "CLAV")
CFB_LIMIT = Decimal(10) ** 10
CFB_ACCOUNT_MAX = 60
CFB_GUESS_BALANCE = ("saldo", "kontostand", "balance", "saldo nach buchung", "neuer saldo", "running balance")
CFB_GUESS_ACCOUNT = ("auftragskonto", "iban auftragskonto", "eigenes konto", "own account")


def cfb_account_name(v):
    """A typed account name (CSV import dialog), default "Main account"."""
    v = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "")).strip()[:CFB_ACCOUNT_MAX]
    return v or tr("Main account")


def _amount(text, credit=True):
    try:
        a = Decimal((text or "").strip())
    except (ArithmeticError, ValueError):
        return None
    if not a.is_finite() or abs(a) >= CFB_LIMIT:
        return None
    return money(a if credit else -a)


# ---------------------------------------------------------------- reading the balances of a statement
def cfb_camt_balances(text, home):
    """CAMT.052 / .053 text -> [{account, day, amount (signed Decimal), kind open|close}] in currency home. bnk_camt has read
    (and checked) the same text before; an unreadable document gives []."""
    from .bank import _kid, _kids, _local, _txt
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        return []
    try:
        root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("﻿")).encode("utf-8"))
    except (ET.ParseError, ValueError):
        return []
    out = []
    for st in root.iter():
        if _local(st.tag) not in ("Stmt", "Rpt"):
            continue
        acct = (_txt(st, "Acct", "Id", "IBAN") or _txt(st, "Acct", "Id", "Othr", "Id")).replace(" ", "").upper()[:CFB_ACCOUNT_MAX]
        best = {}  # (kind, day) -> (rank, amount): CLBD before CLAV, OPBD before PRCD
        for bal in _kids(st, "Bal"):
            code = (_txt(bal, "Tp", "CdOrPrtry", "Cd") or _txt(bal, "Tp", "CdOrPrtry", "Prtry")).upper()
            kind = "open" if code in CFB_OPEN else "close" if code in CFB_CLOSE else None
            amt_el = _kid(bal, "Amt")
            if kind is None or amt_el is None or ((amt_el.get("Ccy") or home).upper() != home):
                continue
            a = _amount(amt_el.text, _txt(bal, "CdtDbtInd") != "DBIT")
            v = _txt(bal, "Dt", "Dt") or _txt(bal, "Dt", "DtTm")[:10]
            try:
                day = date.fromisoformat(v[:10]).isoformat() if v else None
            except ValueError:
                day = None
            if a is None or day is None:
                continue
            rank = (CFB_OPEN if kind == "open" else CFB_CLOSE).index(code)
            if (kind, day) not in best or rank < best[(kind, day)][0]:
                best[(kind, day)] = (rank, a)
        out += [{"account": acct or tr("Main account"), "day": d, "amount": a, "kind": k} for (k, d), (_r, a) in sorted(best.items(), key=lambda x: x[0][1])]
    return out


def _col(mapping, key, ncols):
    v = mapping.get(key) if isinstance(mapping, dict) else None
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < ncols:
        raise BadInput(tr("Invalid value: {0}", key))
    return v


def cfb_csv_balance(text, mapping, account=None):
    """CSV text + mapping with an optional mapping.balance -> [{account, day, amount, kind close}] (the balance of the
    chronologically last row; [] without a balance column or without a readable balance)."""
    from .bank import IBAN_RE
    from ..life.budget import BUD_DATE_FORMATS, _parse_amount, _parse_day, bud_csv_table
    if not isinstance(mapping, dict):
        return []
    _d, header, rows = bud_csv_table(text)
    bi, ai = _col(mapping, "balance", len(header)), _col(mapping, "account", len(header))
    if bi is None:
        return []
    di = _col(mapping, "date", len(header))
    if di is None:
        return []
    fmt = mapping.get("date_format") if mapping.get("date_format") in BUD_DATE_FORMATS else "DD.MM.YYYY"
    decimal = mapping.get("decimal") if mapping.get("decimal") in (",", ".") else ","
    seen = []  # (day, n, balance, row) in file order
    for n, r in enumerate(rows):
        day = _parse_day(r[di], fmt) if di < len(r) else None
        if not day:
            continue
        b = _parse_amount(r[bi], decimal) if bi < len(r) else None
        seen.append((day, n, b, r))
    if not seen:
        return []
    desc = seen[0][0] > seen[-1][0]  # newest first: the first row of the newest day is the latest booking
    if seen[0][0] == seen[-1][0]:  # 2.355.0 B (#2847): one day only -- the order from the balances (row before + amount)
        desc = _cfb_desc(seen, mapping, len(header), decimal, _parse_amount)
    newest = max(s[0] for s in seen)
    day_rows = [s for s in seen if s[0] == newest]
    pick = day_rows[0] if desc else day_rows[-1]
    if pick[2] is None or abs(pick[2]) >= CFB_LIMIT:
        return []
    acct = ""
    if ai is not None and ai < len(pick[3]):
        acct = pick[3][ai].replace(" ", "").upper()
        acct = acct if IBAN_RE.match(acct) else ""
    return [{"account": acct or cfb_account_name(account), "day": newest, "amount": money(pick[2]), "kind": "close"}]


def _cfb_desc(seen, mapping, ncols, decimal, parse):
    """2.355.0 B (#2847): True when the rows of one day are newest first: each balance = the next row's balance + its own
    amount (oldest first: the row before's balance + its own amount). Unknown (no amount column, no two balances) = False."""
    cols = {k: _col(mapping, k, ncols) for k in ("amount", "amount_in", "amount_out")}

    def amt(r):
        get = lambda k: parse(r[cols[k]], decimal) if cols[k] is not None and cols[k] < len(r) else None  # noqa: E731
        if cols["amount"] is not None:
            return get("amount")
        a_in, a_out = get("amount_in"), get("amount_out")
        return a_in if a_in else -abs(a_out) if a_out else None
    up = down = 0
    for (_d, _n, b0, r0), (_d1, _n1, b1, r1) in zip(seen, seen[1:]):
        a0, a1 = amt(r0), amt(r1)
        if None in (b0, b1):
            continue
        up += a1 is not None and b0 + a1 == b1
        down += a0 is not None and b1 + a0 == b0
    return down > up


def cfb_guess(header):
    """The guessed balance / own account column of a CSV header (None = none)."""
    low = [re.sub(r"\s+", " ", (h or "").casefold()).strip() for h in header]
    out = {}
    for k, names in (("balance", CFB_GUESS_BALANCE), ("account", CFB_GUESS_ACCOUNT)):
        out[k] = next((i for n in names for i, h in enumerate(low) if h == n), None)
        if out[k] is None:
            out[k] = next((i for n in names for i, h in enumerate(low) if n in h), None)
    return out


def cfb_mt940_balances(text, home):
    """2.299.0 A (#3190): MT940 / MT942 text -> the balances like cfb_camt_balances (core/mt940.mt_parse); other currency
    than home left out; an unreadable file gives []."""
    try:
        bals = mt.mt_parse(text)[1]
    except BadInput:
        return []
    return [{"account": x["account"] or tr("Main account"), "day": x["day"], "amount": x["amount"], "kind": x["kind"]}
            for x in bals if (x["currency"] or home) == home]


def cfb_read(c, oid, fmt, b):
    """The balances of the statement in body b (fmt camt | csv)."""
    from .bank import _home
    text = b.get("text") or ""
    if fmt == "camt":
        return cfb_camt_balances(text, _home(c, oid))
    if fmt == "mt940":  # 2.299.0 A (#3190): :60F: / :62F: of the statement, account from :25:
        return cfb_mt940_balances(text, _home(c, oid))
    if b.get("mapping") is None:
        return []
    return cfb_csv_balance(text, b["mapping"], b.get("account"))


def cfb_read_all(c, oid, fmt, b, parts=None):
    """2.144.1 B (#2450): the balances of every statement of one import (parts = [{fmt, text}] from bank.bnk_parse; without
    them the body's text). Every file's balance is a real bank balance of its day (the cash flow uses them per month), so all
    are kept and the newest one is the current balance; an equal balance in two files (day and month statement) counts once."""
    if parts is None:
        return cfb_read(c, oid, fmt, b)
    out, seen = [], set()
    for p in parts:
        for x in cfb_read(c, oid, p["fmt"], {"text": p["text"], "mapping": b.get("mapping"), "account": b.get("account")}):
            k = (x["account"], x["day"], x["kind"], x["amount"])
            if k not in seen:
                seen.add(k)
                out.append(x)
    return out


def _bal_out(x):
    return {"account": x["account"], "day": x["day"], "amount": dstr(x["amount"]), "kind": x["kind"]}


def cfb_preview(c, oid, fmt, b, cols, parts=None):
    """The additions of bnk_preview: CSV columns -> guess.balance / guess.account (into cols) and the known accounts;
    rows -> balances [{account, day, amount, kind}]."""
    if cols is not None:
        g = cfb_guess(cols.get("columns") or [])
        taken = {v for k, v in (cols.get("guess") or {}).items() if k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart")}
        for k, v in g.items():
            (cols.setdefault("guess", {}))[k] = v if v not in taken else None
        return {"accounts": cfb_accounts(c, oid)}
    return {"balances": [_bal_out(x) for x in cfb_read_all(c, oid, fmt, b, parts)]}


def cfb_store(c, oid, iid, fmt, b, ts, parts=None):
    """Stores the balances of import iid (called inside bnk_import's transaction) -> their number."""
    bals = cfb_read_all(c, oid, fmt, b, parts)
    for x in bals:
        row = oc_enc_fields(c, oid, "office_bank_balances", {"org_id": oid, "import_id": iid, "account": x["account"], "day": x["day"],
                                                             "amount": dstr(x["amount"]), "kind": x["kind"], "created_at": ts})
        c.execute(f"INSERT INTO office_bank_balances({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return len(bals)


# ---------------------------------------------------------------- the balances that count
def cfb_balances(c, oid):
    """Every balance of an active import of area oid: [{account, day (end of day), amount Decimal, import_id, id}]; an opening
    balance is the closing balance of the day before."""
    out = []
    for r in c.execute("SELECT b.* FROM office_bank_balances b JOIN office_bank_imports i ON i.id=b.import_id AND i.org_id=b.org_id "
                       "WHERE b.org_id=? AND i.undone_at IS NULL", (oid,)).fetchall():
        d = oc_dec_fields(c, oid, "office_bank_balances", r)
        try:
            day = date.fromisoformat(d["day"])
            amt = dec(d["amount"], "NaN")
        except (TypeError, ValueError):
            continue
        if amt.is_nan():
            continue
        if d["kind"] == "open":
            day -= timedelta(days=1)
        out.append({"account": d["account"] or "", "day": day.isoformat(), "amount": amt, "rank": 1 if d["kind"] == "close" else 0,
                    "import_id": d["import_id"], "id": d["id"]})
    return out


def cfb_accounts(c, oid):
    return sorted({x["account"] for x in cfb_balances(c, oid) if x["account"]})


def _newest(bals):
    """Per account the newest balance -> sorted list."""
    best = {}
    for x in bals:
        k = (x["day"], x["rank"], x["import_id"], x["id"])
        if x["account"] not in best or k > best[x["account"]][0]:
            best[x["account"]] = (k, x)
    return [best[a][1] for a in sorted(best)]


def _sum(latest):
    return {"day": min(x["day"] for x in latest), "amount": dstr(money(sum((x["amount"] for x in latest), dec(0)))),
            "accounts": [{"account": x["account"], "day": x["day"], "amount": dstr(money(x["amount"]))} for x in latest]}


def _later(ents, month, day):
    """Money in - out of the entries of month after day (they are in the month-end balance, not yet in day's)."""
    s = dec(0)
    for e in ents:
        if e["month"] == month and e["date"] > day:
            s += dec(e["amount"]) if e["dir"] == "in" else -dec(e["amount"])
    return s


def cfb_apply(c, oid, out, today):
    """Called at the end of cashflow.rk_cashflow after cfstart.cfs_apply: adds bank (all accounts) and rows[].bank (the
    balances inside a month). Without balances the answer stays exactly as before."""
    from .cashflow import rk_cashflow
    from .cfstart import cfs_apply
    rows = out.get("rows") or []
    bals = cfb_balances(c, oid) if rows else []
    if not bals:
        return out
    today = out.get("today") or today
    st = out.get("start")
    gross = {}  # month -> (account at its end, gross entries) for the computed balance on a day

    def computed(day):
        if not st or day < st["day"]:
            return None
        mo = day[:7]
        if mo not in gross:
            row = next((r for r in rows if r["month"] == mo), None)
            if row is not None:  # rows[].account is on gross already (cfs_apply); the net basis needs the gross entries once
                if out.get("basis") == "net" and "" not in gross:
                    gross[""] = (None, rk_cashflow(c, oid, rows[0]["month"], len(rows), today, "gross", cfs=False)["entries"])
                gross[mo] = (row.get("account"), gross[""][1] if out.get("basis") == "net" else out["entries"])
            else:  # outside the months shown: that month once more (gross, with the account balance)
                sub = rk_cashflow(c, oid, mo, 1, today, "gross", cfs=False)
                cfs_apply(c, oid, sub, today)
                gross[mo] = (sub["rows"][0].get("account") if sub["rows"] else None, sub["entries"])
        acc, ents = gross[mo]
        return None if acc is None else money(dec(acc) - _later(ents, mo, day))

    def with_diff(t):
        v = computed(t["day"])
        if v is not None:
            t["computed"], t["diff"] = dstr(v), dstr(money(dec(t["amount"]) - v))
        return t

    out["bank"] = with_diff(_sum(_newest(bals)))
    out["bank"]["suggest_start"] = not st
    for r in rows:
        mine = [x for x in bals if x["day"][:7] == r["month"]]
        if mine:
            t = _sum(_newest(mine))
            t.pop("accounts")
            r["bank"] = with_diff(t)
    return out
