"""2.67.0 A (#1838): fixed costs of the cash flow from a spreadsheet, and the optional monthly task "Cash flow: check the
actual state".

Import, two steps (office_gate + office_org with the admin of the office area, like every route of the cash flow):
  1. POST /api/office/fixed-costs/import/preview (multipart 'file', .xlsx / .xls / CSV up to 2 MB, at most 500 rows): every row
     of the first sheet with a header row below it -> new / dup / error with a reason. Nothing is stored.
  2. POST /api/office/fixed-costs/import {items: [...]}: the rows the person kept (VAT rates changed there); every row is
     checked again with rk_fixed_clean (nothing from the client unchecked), MAX_FIXED counted, one transaction.
Format: a header row with "Name", "Betrag (netto)" (also "Betrag", "netto"), "fällig Monat" (also "Monat", 2.449.0 (#3768): the same in fr / es / it / nl); optional
"Kategorie", "USt", "Wiederholung". A row with a name but no amount is a group row: the category of the rows below it.
Month 0 = monthly from 2026-01-01, 1..12 = yearly in that month (2026-MM-01); quarterly (by the name or the column
"Wiederholung") with a month X = four yearly rows X, X+3, X+6, X+9; a contradiction name / month: the month wins.
The spreadsheet is read by legacyimport.fi_book (zip budget, entity guard, only the cells' text; formulas are never
evaluated, their stored value is the text)."""
import io
import math
import re
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

from flask import Response, g, jsonify

from ..core.config import PUBLIC_URL, app
from ..core.db import body, bump, iso, local_now, now_utc, write_lock
from ..core.i18n import N_, lang, tr
from ..core.csvimport import amount_text
from ..core.orgcrypt import oc_enc_fields
from ..core.pg import insert_id
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .cashflow import MAX_FIXED, _ctx, fci_gross, rk_fixed, rk_fixed_clean
from .legacyimport import _upload, fi_book, fx_run, fx_settle
from .model import office_settings, office_settings_lock, office_settings_save
from ..core.access import my_inbox  # 2.149.0 G (#2517): pulled up from functions
from .ledger import ofx_log  # 2.369.5 (#2517): pulled up from functions
from .otrash import OTB_MANY, OTB_UNDO, otb_put  # 2.567.0 (#4707)
from .model import office_on, pb_owner  # 2.369.5 (#2517): pulled up from functions
from ..tasks.validation import log_act  # 2.369.5 (#2517): pulled up from functions

FCI_FILE_MAX = 2 * 1024 * 1024
FCI_ROWS_MAX = 500
FCI_UNDO_HOURS = 24  # 2.370.4 (#3089 N15): the undo window of an import (as integrations.importers.IMPORT_UNDO_HOURS)
FCI_YEAR = 2026  # every imported cost starts in January 2026 (decided 2026-10-16)
FCI_HEAD = {  # normalised header (letters / digits only) -> field
    "name": "label", "bezeichnung": "label", "posten": "label",
    "betragnetto": "amount", "betrag": "amount", "netto": "amount", "nettobetrag": "amount", "amountnet": "amount", "amount": "amount",
    "fälligmonat": "month", "faelligmonat": "month", "monat": "month", "duemonth": "month", "month": "month",
    # 2.449.0 (#3768): the headers of the template in fr / es / it / nl
    "nom": "label", "nombre": "label", "nome": "label", "naam": "label", "montantnet": "amount", "montant": "amount", "importeneto": "amount",
    "importe": "amount", "importonetto": "amount", "importo": "amount", "bedrag": "amount", "bedragnetto": "amount", "moisdéchéance": "month", "mois": "month",
    "mesdevencimiento": "month", "mes": "month", "mesediscadenza": "month", "mese": "month", "vervalmaand": "month", "maand": "month",
    "kategorie": "category", "category": "category", "gruppe": "category",
    "ust": "vat_rate", "ustsatz": "vat_rate", "mwst": "vat_rate", "mwstsatz": "vat_rate", "vat": "vat_rate", "vatrate": "vat_rate",
    "wiederholung": "repeat", "rhythmus": "repeat", "turnus": "repeat", "repeat": "repeat",
    # 2.91.0 B (#1924): optional: a subscription / tool (ja / x / 1) and its notice period in days
    "abo": "sub", "abotool": "sub", "subscription": "sub", "kündigungsfrist": "notice_days", "kuendigungsfrist": "notice_days",
    "kündigungsfristtage": "notice_days", "kuendigungsfristtage": "notice_days", "noticedays": "notice_days", "noticeperiod": "notice_days",
}
FCI_YES_RE = re.compile(r"^(ja|j|yes|y|x|1|true|abo|oui|sí|si|sì|wahr)$", re.I)  # 2.91.0 B (#1924)
FCI_VAT_RE = re.compile(r"steuerberat|steuerkanzlei|steuerbüro|steuerbuero|tax\s*(?:advis|consult)", re.I)  # 2.122.2 (#2323): always VAT


def fci_vat_guess(label, category):
    """2.122.2 (#2323): the default VAT rate of a row without one: 0 % for insurances, contributions, bank / credit costs,
    taxes, memberships (by the name or the category); a tax adviser by name always 19 %, also below a group "Steuern"."""
    if FCI_VAT_RE.search(str(label or "")):
        return 19
    return 0 if FCI_NOVAT_RE.search(str(label or "")) or FCI_NOVAT_RE.search(str(category or "")) else 19


FCI_QUARTER_RE = re.compile(r"viertelj|quartal|\bq[1-4]\b|quarter", re.I)
FCI_NOVAT_RE = re.compile(  # 2.122.2 (#2323): + bank and credit costs, taxes (not the tax adviser), service charge, memberships, KSK
    r"versicherung|abgabe|beitrag|kammer|berufsgenossenschaft|rundfunk|insurance|contribution|levy"
    r"|(?<!daten)bank|sparkasse|kontoführ|kontofuehr|girokarte|kredit|zins|provision|tilgung|rückzahl|rueckzahl"
    r"|steuer(?!berat|kanzlei|büro|buero|programm|software)|hausgeld|mitglied|adac|\bksk\b|künstlersozial|kuenstlersozial"
    r"|knappschaft|\bbg\b|\bloan|interest|membership|\btax(?!\s*(?:advis|consult))", re.I)
FCI_REPEATS = (("once", re.compile(r"einmal|once", re.I)), ("quarterly", FCI_QUARTER_RE),
               ("yearly", re.compile(r"jährl|jaehrl|jahr|year|annual", re.I)), ("monthly", re.compile(r"monatl|month", re.I)))
FCI_REASONS = {"name": N_("No name"), "amount": N_("Amount missing or not readable"), "zero": N_("Amount is 0"),
               "month": N_("Due month must be 0 to 12"), "vat": N_("VAT rate must be 0, 7 or 19"),
               "notice": N_("Notice period must be 0 to 730 days")}  # 2.91.0 B (#1924)
FCI_TASK_TITLE = N_("Cash flow: check the actual state")


def fci_num(v):
    """A money amount of a cell -> Decimal or None. German first: "1.200" / "12.500" (exactly three digits after every dot,
    no comma) = thousands, "1.200,50" = 1200.50; "1,200.50" = 1200.50; "650"; "12.5" (the stored form of a number cell) =
    12.5; "29,90" = 29.90. 2.355.0 B (#2843): core/csvimport.amount_text (thousand separators only in groups of three,
    "1,500" unreadable -- was 1.5)."""
    d = amount_text(v)
    if d is None or abs(d) > 10 ** 9:
        return None
    return d


def fci_norm(s):
    return re.sub(r"[\W_]", "", str(s or "").lower())  # 2.449.0 (#3768): every letter ("mois d'échéance"), was a-z + German


def fci_key(label, amount, repeat, start):
    """Two fixed costs are the same: the name (case, spaces), the amount and the repeat; yearly and once also the month."""
    return (" ".join(str(label or "").casefold().split()), dstr(money(dec(amount))), repeat,
            (start or "")[5:7] if repeat in ("yearly", "once") else "")


def _clean_text(v, n):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(v or "")).strip()[:n]


def _vat(v):
    s = re.sub(r"[\s%]", "", str(v or "")).replace(",", ".")
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return "bad"
    if not math.isfinite(f):  # 2.67.0 (#1838, review): "inf" / "nan" / "1e400" are a row error, not a 500
        return "bad"
    if 0 < f < 1:  # 0.19 as a percentage cell
        f *= 100
    r = round(f)
    return r if abs(f - r) < 0.01 and r in (0, 7, 19) else "bad"


def fci_head(grid):
    """(column map, index of the header row) of a sheet's rows, (None, 0) without a header row."""
    cols, hi = None, 0
    heads = []
    for i, row in enumerate(grid[:20]):
        m = {}
        for j, cell in enumerate(row):
            f = FCI_HEAD.get(fci_norm(cell))
            if f and f not in m:
                m[f] = j
        heads.append(m)
        if "label" in m and "amount" in m:
            cols, hi = m, i
            break
    if cols is None:  # 2.122.2 (#2323): an "Amount" column but no "Name" (A1 = "Grundkosten 2025"): the first text column is the name
        for i, m in enumerate(heads):
            if "amount" in m:
                used = set(m.values())
                j = next((j for j, cell in enumerate(grid[i]) if j not in used and str(cell or "").strip() and fci_num(cell) is None), None)
                if j is not None:
                    cols, hi = {**m, "label": j}, i
                    break
    return cols, hi


def fci_preview(c, oid, raw, name=""):
    """{rows: [{row, label, amount, gross, repeat, start, month, category, vat_rate, status new|dup|error, reason, sel,
    part}], counts: {new, dup, error}, header: [...]}.
    2.363.2 (#3106): also .xls / CSV (fi_book); the first sheet with a header row counts, not simply the first sheet."""
    grids = [g for g in fi_book(raw, name).values() if g]
    if not grids:
        raise BadInput(tr("The spreadsheet is empty"))
    grid, cols, hi = grids[0], None, 0
    for g in grids:
        cols, hi = fci_head(g)
        if cols is not None:
            grid = g
            break
    if cols is None:
        raise BadInput(tr("No header row with the columns Name and Amount (net) found"))
    body_rows = [(hi + 2 + k, r) for k, r in enumerate(grid[hi + 1:])]
    while body_rows and not any(str(x).strip() for x in body_rows[-1][1]):
        body_rows.pop()
    if len(body_rows) > FCI_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", FCI_ROWS_MAX))
    seen = fci_seen(c, oid)
    out, group = [], ""

    def cell(r, f):
        j = cols.get(f)
        return str(r[j]).strip() if j is not None and j < len(r) and r[j] is not None else ""

    for no, r in body_rows:
        if not any(str(x).strip() for x in r):
            continue  # empty rows: silently skipped
        if all(not str(x).strip() or fci_num(x) == 0 for x in r):
            continue  # 2.122.2 (#2323): a row with only "0" (a month cell of an empty row) is empty too
        label, amt_s, mon_s = _clean_text(cell(r, "label"), 200), cell(r, "amount"), cell(r, "month")
        cat = _clean_text(cell(r, "category"), 100)
        base = {"row": no, "label": label, "amount": "", "gross": "", "repeat": "", "start": "", "month": mon_s[:10],
                "category": cat or group, "vat_rate": 0, "status": "error", "reason": "", "sel": False, "part": "",
                "sub": 1 if FCI_YES_RE.match(cell(r, "sub")) else 0, "notice_days": 0}  # 2.91.0 B (#1924)
        if label and not amt_s and not mon_s:
            group = cat or label  # a group row: the category of the rows below
            continue
        if not label:
            out.append({**base, "reason": tr(FCI_REASONS["name"])})
            continue
        amt = fci_num(amt_s)
        if amt is None or amt < 0:
            out.append({**base, "reason": tr(FCI_REASONS["amount"])})
            continue
        if money(amt) == 0:
            out.append({**base, "amount": "0.00", "reason": tr(FCI_REASONS["zero"])})
            continue
        base["amount"] = dstr(money(amt))
        mon = fci_num(mon_s) if mon_s else dec(0)
        if mon is None or mon != int(mon) or not 0 <= mon <= 12:
            out.append({**base, "reason": tr(FCI_REASONS["month"])})
            continue
        mon = int(mon)
        vr = _vat(cell(r, "vat_rate"))
        if vr == "bad":
            out.append({**base, "reason": tr(FCI_REASONS["vat"])})
            continue
        if vr is None:
            vr = fci_vat_guess(label, base["category"])
        nd_s = cell(r, "notice_days")  # 2.91.0 B (#1924): whole days, empty = 0
        nd = fci_num(nd_s) if nd_s else dec(0)
        if nd is None or nd != int(nd) or not 0 <= nd <= 730:
            out.append({**base, "reason": tr(FCI_REASONS["notice"])})
            continue
        base["notice_days"] = int(nd)
        rp_s = cell(r, "repeat")
        rp = next((k for k, rx in FCI_REPEATS if rx.search(rp_s)), None) if rp_s else None
        if rp is None:  # the month decides; the name only marks quarterly costs of a month 1..12
            rp = "monthly" if mon == 0 else "quarterly" if FCI_QUARTER_RE.search(label) else "yearly"
        if rp == "monthly":
            parts = [(f"{FCI_YEAR}-01-01", "monthly")]
        elif rp == "quarterly":
            x = mon or 1
            parts = [(f"{FCI_YEAR}-{(x - 1 + 3 * k) % 12 + 1:02d}-01", "yearly") for k in range(4)]
        else:
            parts = [(f"{FCI_YEAR}-{mon or 1:02d}-01", rp)]
        for k, (st, rep) in enumerate(parts):
            key = fci_key(label, base["amount"], rep, st)
            dup = key in seen
            seen.add(key)
            out.append({**base, "repeat": rep, "start": st, "vat_rate": vr, "gross": dstr(fci_gross(base["amount"], vr)),
                        "status": "dup" if dup else "new", "reason": tr("Already there") if dup else "", "sel": not dup,
                        "part": f"{k + 1}/{len(parts)}" if len(parts) > 1 else ""})
    counts = {s: sum(1 for x in out if x["status"] == s) for s in ("new", "dup", "error")}
    return {"rows": out, "counts": counts}


@app.post("/api/office/fixed-costs/import/preview")
def fci_preview_post():
    """Office admin. multipart 'file' (.xlsx, .xls, CSV) -> fci_preview. Nothing is stored."""
    c, uid, oid = _ctx()
    f, raw = _upload("file", FCI_FILE_MAX)
    return jsonify(fci_preview(c, oid, raw, f.filename or ""))


def fci_seen(c, oid):
    """2.68.0 (#1839): the keys (fci_key) of the fixed costs the area already has."""
    return {fci_key(f["label"], f["amount"], f["repeat"], f["start"]) for f in rk_fixed(c, oid)}


def fci_clean_rows(items):
    """2.68.0 (#1839): [{label, amount, repeat, start, until?, category?, vat_rate?}] -> the rows rk_fixed_clean made of them
    (only these fields; BadInput "Row N: ..." for the first bad one)."""
    rows = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid data"))
        try:
            rows.append(rk_fixed_clean({k: it.get(k) for k in ("label", "amount", "repeat", "start", "until", "category", "vat_rate", "sub", "notice_days")}))  # 2.91.0 B (#1924): + sub, notice_days
        except BadInput as x:
            # 2.363.2 (#3106): the row of the sheet when the preview sent it
            no = it["row"] if isinstance(it.get("row"), int) and not isinstance(it.get("row"), bool) else i + 1
            raise BadInput(tr("Row {0}: {1}", no, str(x.args[0] if x.args else x))) from None
    return rows


def fci_write(c, uid, oid, items, detail=None, kept=None, run=False):
    """2.68.0 (#1839): the writing part of the import (the spreadsheet and the agent's import proposal): every row checked
    again (fci_clean_rows), all or nothing, MAX_FIXED counted under the area's lock, one office log line. No commit.
    Returns the new ids. 2.269.0 D (#3046): a row the area already has (fci_key, as in the preview) is skipped unless it
    carries dup_ok (the person ticked a row the preview marked "Already there"): sent twice (two tabs, a retry) = once.
    kept (a list): gets the items actually written, in the order of the returned ids (the import proposal keeps them).
    2.363.2 (#3104): run = an entry in the import runs (the import proposal has its own undo on the job)."""
    rows = fci_clean_rows(items)
    write_lock(c, f"office_fixed_{int(oid)}")
    seen = fci_seen(c, oid)
    pick = [(it, row) for it, row in zip(items, rows) if it.get("dup_ok") in (1, True, "1")
            or fci_key(row["label"], row["amount"], row["repeat"], row["start"]) not in seen]
    rows = [row for _, row in pick]
    if kept is not None:
        kept[:] = [it for it, _ in pick]
    have = c.execute("SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=?", (oid,)).fetchone()[0]
    if have + len(rows) > MAX_FIXED:
        raise BadInput(tr("Too many fixed costs: at most {0}, {1} already there", MAX_FIXED, have))
    ts, ids = iso(now_utc()), []
    for row in rows:
        row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
        row = oc_enc_fields(c, oid, "office_fixed_costs", row)
        ids.append(insert_id(c, f"INSERT INTO office_fixed_costs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ofx_log(c, oid, "import", target="fixed_costs", detail={"count": len(ids), **(detail or {})})
    if run:
        fx_run(c, oid, uid, "fixed_costs", ids)
    return ids


@app.post("/api/office/fixed-costs/import")
def fci_import_post():
    """Office admin. {items: [{label, amount, repeat, start, until?, category?, vat_rate?}]} -> 201 {created, ids}. All or
    nothing: one bad row = 400 with its number, too many in total (MAX_FIXED) = 400."""
    c, uid, oid = _ctx()
    b = body()
    items = b.get("items") if isinstance(b, dict) else None
    if not isinstance(items, list) or not items:
        raise BadInput(tr("Invalid data"))
    if len(items) > FCI_ROWS_MAX * 4:
        raise BadInput(tr("Too many rows (at most {0})", FCI_ROWS_MAX * 4))
    ids = fci_write(c, uid, oid, items, run=True)  # 2.68.0 (#1839): shared with the agent's import proposal (agents/importprop.py)
    bump(c)
    c.commit()
    return jsonify(created=len(ids), ids=ids, skipped=len(items) - len(ids)), 201  # 2.269.0 D (#3046): + skipped (already there)


def fci_remove(c, oid, ids, uid=None):
    """2.272.0 C (#3027): deletes the fixed costs `ids` of the area unchanged since they were made (updated_at = created_at, no
    reminder sent). 2.370.4 (#3089 N15): and made within the undo window (FCI_UNDO_HOURS) - an older row stays.
    2.567.0 (#4707): the ones that go first into the office trash as ONE entry (restore brings the import back whole; uid =
    who took it back). -> how many went. No commit."""
    if not ids:
        return 0
    q = ",".join("?" * len(ids))
    cut = iso(now_utc() - timedelta(hours=FCI_UNDO_HOURS))
    gone = [r[0] for r in c.execute(f"""SELECT id FROM office_fixed_costs f WHERE org_id=? AND id IN ({q}) AND updated_at=created_at AND created_at>=?
                                        AND NOT EXISTS (SELECT 1 FROM office_sub_reminders r WHERE r.fixed_id=f.id) ORDER BY id""", [oid] + ids + [cut]).fetchall()]
    if not gone:
        return 0
    otb_put(c, oid, uid, FCI_TRASH, "office_fixed_costs", gone, tr("Import") + f" · {len(gone)}", sub="import")
    return c.execute("DELETE FROM office_fixed_costs WHERE org_id=? AND id = ANY(CAST(? AS BIGINT[]))", (oid, gone)).rowcount


def fci_trash_back(c, oid, ids):
    """2.567.0 (#4707): after the restore of an import taken back (OTB_MANY): its import run counts as not undone again."""
    c.execute("""UPDATE office_import_runs SET undone_at=NULL, undone_by=NULL WHERE org_id=? AND undone_at IS NOT NULL AND id IN
                 (SELECT import_run_id FROM office_fixed_costs WHERE org_id=? AND id = ANY(CAST(? AS BIGINT[])) AND import_run_id IS NOT NULL)""",
              (oid, oid, list(ids)))


FCI_TRASH = "fixed_import"  # 2.567.0 (#4707): kind of an import of fixed costs taken back, in the office trash
OTB_MANY[FCI_TRASH] = fci_trash_back
OTB_UNDO[FCI_TRASH] = _ctx  # the office admin, as taking it back


@app.post("/api/office/fixed-costs/delete")
def fci_delete_many():
    """Office admin. {ids: [...]} -> deletes these fixed costs of the area (the undo of an import: one step).
    2.272.0 C (#3027): only the ones unchanged since they were made (updated_at = created_at, no reminder sent); the others
    stay (kept: their number)."""
    c, uid, oid = _ctx()
    b = body()
    ids = b.get("ids") if isinstance(b, dict) else None
    if not isinstance(ids, list) or len(ids) > FCI_ROWS_MAX * 4 or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid data"))
    ids = sorted(set(ids))
    q = ",".join("?" * len(ids))
    have = c.execute(f"SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=? AND id IN ({q})", [oid] + ids).fetchone()[0] if ids else 0
    n = fci_remove(c, oid, ids, uid)
    fx_settle(c, oid, uid, "fixed_costs")  # 2.363.2 (#3104)
    bump(c)
    c.commit()
    return jsonify(ok=True, deleted=n, kept=have - n, trash_id=g.get("otb_id") if n else None)  # 2.567.0 (#4707)


# ---------------------------------------------------------------- the template
def _cell(ref, v):
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'


def fci_xlsx(rows, sheet="Sheet1"):
    """A minimal .xlsx (one sheet, inline strings, no styles) of rows [[cell, ...], ...]."""
    data = "".join(f'<row r="{i + 1}">' + "".join(_cell(f"{chr(65 + j)}{i + 1}", v) for j, v in enumerate(r) if v != "") + "</row>"
                   for i, r in enumerate(rows))
    ns = "http://schemas.openxmlformats.org"
    parts = {
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{ns}/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{ns}/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{ns}/spreadsheetml/2006/main" '
        f'xmlns:r="{ns}/officeDocument/2006/relationships"><sheets><sheet name="{escape(sheet[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{ns}/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{ns}/spreadsheetml/2006/main">'
        f'<sheetData>{data}</sheetData></worksheet>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


@app.get("/api/office/fixed-costs/import/template")
def fci_template():
    """Office admin. The template: a header row and three made-up example rows."""
    _ctx()
    head = [tr("Name"), tr("Amount (net)"), tr("Due month")]  # what the import reads (FCI_HEAD); 2.449.0 (#3768): every app language
    rows = [head,
            [tr("Software subscription"), 29.9, 0],
            [tr("Insurances")],
            [tr("Liability insurance"), 240, 3]]
    raw = fci_xlsx(rows, tr("Fixed costs"))
    return Response(raw, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{tr("fixed-costs-template")}.xlsx"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- the monthly check task
def fci_people(c, oid):
    """[{id, name}] who may get the task: the people who see the cash flow of this area (its admins with the module
    "office" on; a personal office: its owner). No agents, no kids."""
    owner = pb_owner(c, oid)
    if owner is not None:
        ids = [owner]
    else:
        ids = [r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role='admin'", (oid,))]
    if not ids:
        return []
    rows = c.execute(f"SELECT * FROM users WHERE id IN ({','.join('?' * len(ids))}) AND disabled=0", ids).fetchall()
    out = []
    for u in rows:
        ks = u.keys()
        if ("kind" in ks and u["kind"] == "agent") or ("kid" in ks and u["kid"]) or not office_on(c, u["id"]):
            continue
        out.append({"id": u["id"], "name": u["display_name"] or u["username"]})
    out.sort(key=lambda x: x["name"].casefold())
    return out


def _first_of_next(today):
    d = date.fromisoformat(today)
    return d.isoformat() if d.day == 1 else date(d.year + (d.month == 12), d.month % 12 + 1, 1).isoformat()


def fci_task_new(c, person):
    """The recurring task in the person's inbox, theirs and assigned to them: due on the 1st of every month, only a link to
    the cash flow (never an amount)."""
    lid = my_inbox(c, person)
    lg = lang(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,repeat,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (lid, tr(FCI_TASK_TITLE, lg=lg), tr("Compare the cash flow in the office with the bank account.", lg=lg),
                     _first_of_next(local_now().date().isoformat()), "FREQ=MONTHLY;BYMONTHDAY=1", srt, ts, ts, person,
                     PUBLIC_URL.rstrip("/") + "/#office/cashflow", person))
    log_act(c, tid, "created", uid=person)
    return tid


def fci_task_end(c, tid, person):
    """Ends the task: the repeat removed and done (never deleted). Only the task this setting made: the person's own and
    assigned to them (a stored id never reaches another task)."""
    if not tid or not person:
        return
    ts = iso(now_utc())
    if c.execute("UPDATE tasks SET repeat='', status=2, completed_at=?, updated_at=? WHERE id=? AND created_by=? AND assignee_id=? AND status=0 "
                 "AND deleted_at IS NULL", (ts, ts, tid, person, person)).rowcount:
        log_act(c, tid, "complete")


def _check_public(c, oid, s):
    people = fci_people(c, oid)
    uid = s.get("cf_check_user")
    return {"on": bool(s.get("cf_check")), "user_id": uid, "task_id": s.get("cf_check_task"), "people": people,
            "lost": bool(s.get("cf_check") and uid and uid not in {p["id"] for p in people})}


@app.get("/api/office/cashflow/check")
def fci_check_get():
    """Office admin. {on, user_id, task_id, people: [{id, name}], lost (the person no longer sees the cash flow)}."""
    c, uid, oid = _ctx()
    return jsonify(_check_public(c, oid, office_settings(c, oid)))


@app.put("/api/office/cashflow/check")
def fci_check_put():
    """Office admin. {on: 0|1, user_id?} -> on: the task for the person (another person: the old task ends, a new one);
    off: the task ends. A person who does not see the cash flow is refused (400)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_cfcheck_{int(oid)}")
    office_settings_lock(c, oid)  # 2.269.0 B (#3014)
    s = office_settings(c, oid)
    on = b.get("on", s.get("cf_check")) in (1, True, "1", "true")
    person = b.get("user_id", s.get("cf_check_user"))
    if on:
        if isinstance(person, bool) or not isinstance(person, int) or person not in {p["id"] for p in fci_people(c, oid)}:
            raise BadInput(tr("This person does not see the cash flow of this office"))
        if not (s.get("cf_check") and s.get("cf_check_user") == person and s.get("cf_check_task")):
            fci_task_end(c, s.get("cf_check_task"), s.get("cf_check_user"))
            s["cf_check_task"] = fci_task_new(c, person)
        s.update(cf_check=1, cf_check_user=person)
    else:
        fci_task_end(c, s.get("cf_check_task"), s.get("cf_check_user"))
        s.update(cf_check=0, cf_check_task=None)
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"cf_check": int(on), "cf_check_user": s.get("cf_check_user")})
    bump(c)
    c.commit()
    return jsonify(_check_public(c, oid, s))
