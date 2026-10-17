"""2.67.0 A (#1838): fixed costs of the cash flow from a spreadsheet, and the optional monthly task "Cash flow: check the
actual state".

Import, two steps (office_gate + office_org with the admin of the office area, like every route of the cash flow):
  1. POST /api/office/fixed-costs/import/preview (multipart 'file', .xlsx up to 2 MB, at most 500 rows): every row of the
     first sheet below its header row -> new / dup / error with a reason. Nothing is stored.
  2. POST /api/office/fixed-costs/import {items: [...]}: the rows the person kept (VAT rates changed there); every row is
     checked again with rk_fixed_clean (nothing from the client unchecked), MAX_FIXED counted, one transaction.
Format: a header row with "Name", "Betrag (netto)" (also "Betrag", "netto"), "fällig Monat" (also "Monat"); optional
"Kategorie", "USt", "Wiederholung". A row with a name but no amount is a group row: the category of the rows below it.
Month 0 = monthly from 2026-01-01, 1..12 = yearly in that month (2026-MM-01); quarterly (by the name or the column
"Wiederholung") with a month X = four yearly rows X, X+3, X+6, X+9; a contradiction name / month: the month wins.
The spreadsheet is read by legacyimport.fi_xlsx_read (zip budget, entity guard, only the cells' text; formulas are never
evaluated, their stored value is the text)."""
import io
import math
import re
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from flask import Response, jsonify

from ..core.config import PUBLIC_URL, app
from ..core.db import body, bump, iso, local_now, now_utc, write_lock
from ..core.i18n import N_, lang, tr
from ..core.orgcrypt import oc_enc_fields
from ..core.pg import insert_id
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .cashflow import MAX_FIXED, _ctx, fci_gross, rk_fixed, rk_fixed_clean
from .model import office_settings, office_settings_save

FCI_FILE_MAX = 2 * 1024 * 1024
FCI_ROWS_MAX = 500
FCI_YEAR = 2026  # every imported cost starts in January 2026 (decided 2026-10-16)
FCI_HEAD = {  # normalised header (letters / digits only) -> field
    "name": "label", "bezeichnung": "label", "posten": "label",
    "betragnetto": "amount", "betrag": "amount", "netto": "amount", "nettobetrag": "amount", "amountnet": "amount", "amount": "amount",
    "fälligmonat": "month", "faelligmonat": "month", "monat": "month", "duemonth": "month", "month": "month",
    "kategorie": "category", "category": "category", "gruppe": "category",
    "ust": "vat_rate", "ustsatz": "vat_rate", "mwst": "vat_rate", "mwstsatz": "vat_rate", "vat": "vat_rate", "vatrate": "vat_rate",
    "wiederholung": "repeat", "rhythmus": "repeat", "turnus": "repeat", "repeat": "repeat",
}
FCI_QUARTER_RE = re.compile(r"viertelj|quartal|\bq[1-4]\b|quarter", re.I)
FCI_NOVAT_RE = re.compile(r"versicherung|abgabe|beitrag|kammer|berufsgenossenschaft|rundfunk|insurance|contribution|levy", re.I)
FCI_REPEATS = (("once", re.compile(r"einmal|once", re.I)), ("quarterly", FCI_QUARTER_RE),
               ("yearly", re.compile(r"jährl|jaehrl|jahr|year|annual", re.I)), ("monthly", re.compile(r"monatl|month", re.I)))
FCI_REASONS = {"name": N_("No name"), "amount": N_("Amount missing or not readable"), "zero": N_("Amount is 0"),
               "month": N_("Due month must be 0 to 12"), "vat": N_("VAT rate must be 0, 7 or 19")}
FCI_TASK_TITLE = N_("Cash flow: check the actual state")


def fci_num(v):
    """A money amount of a cell -> Decimal or None. German first: "1.200" / "12.500" (exactly three digits after every dot,
    no comma) = thousands, "1.200,50" = 1200.50; "1,200.50" = 1200.50; "650"; "12.5" (the stored form of a number cell) =
    12.5; "29,90" = 29.90."""
    s = re.sub(r"[\s  €]|EUR", "", str(v or ""))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "." in s and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    else:
        s = s.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    d = dec(s, "NaN")
    if d.is_nan() or not d.is_finite() or abs(d) > 10 ** 9:
        return None
    return d


def fci_norm(s):
    return re.sub(r"[^0-9a-zäöüß]", "", str(s or "").lower())


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


def fci_preview(c, oid, raw):
    """{rows: [{row, label, amount, gross, repeat, start, month, category, vat_rate, status new|dup|error, reason, sel,
    part}], counts: {new, dup, error}, header: [...]}."""
    from .legacyimport import fi_xlsx_read
    sheets = fi_xlsx_read(raw)
    grid = next(iter(sheets.values()), None) if sheets else None
    if not grid:
        raise BadInput(tr("The spreadsheet is empty"))
    cols, hi = None, 0
    for i, row in enumerate(grid[:20]):
        m = {}
        for j, cell in enumerate(row):
            f = FCI_HEAD.get(fci_norm(cell))
            if f and f not in m:
                m[f] = j
        if "label" in m and "amount" in m:
            cols, hi = m, i
            break
    if cols is None:
        raise BadInput(tr("No header row with the columns Name and Amount (net) found"))
    body_rows = [(hi + 2 + k, r) for k, r in enumerate(grid[hi + 1:])]
    while body_rows and not any(str(x).strip() for x in body_rows[-1][1]):
        body_rows.pop()
    if len(body_rows) > FCI_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", FCI_ROWS_MAX))
    seen = {fci_key(f["label"], f["amount"], f["repeat"], f["start"]) for f in rk_fixed(c, oid)}
    out, group = [], ""

    def cell(r, f):
        j = cols.get(f)
        return str(r[j]).strip() if j is not None and j < len(r) and r[j] is not None else ""

    for no, r in body_rows:
        if not any(str(x).strip() for x in r):
            continue  # empty rows: silently skipped
        label, amt_s, mon_s = _clean_text(cell(r, "label"), 200), cell(r, "amount"), cell(r, "month")
        cat = _clean_text(cell(r, "category"), 100)
        base = {"row": no, "label": label, "amount": "", "gross": "", "repeat": "", "start": "", "month": mon_s[:10],
                "category": cat or group, "vat_rate": 0, "status": "error", "reason": "", "sel": False, "part": ""}
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
            vr = 0 if FCI_NOVAT_RE.search(label) or FCI_NOVAT_RE.search(base["category"]) else 19
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
    """Office admin. multipart 'file' (.xlsx) -> fci_preview. Nothing is stored."""
    from .legacyimport import _upload
    c, uid, oid = _ctx()
    _f, raw = _upload("file", FCI_FILE_MAX)
    return jsonify(fci_preview(c, oid, raw))


@app.post("/api/office/fixed-costs/import")
def fci_import_post():
    """Office admin. {items: [{label, amount, repeat, start, until?, category?, vat_rate?}]} -> 201 {created, ids}. All or
    nothing: one bad row = 400 with its number, too many in total (MAX_FIXED) = 400."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    b = body()
    items = b.get("items") if isinstance(b, dict) else None
    if not isinstance(items, list) or not items:
        raise BadInput(tr("Invalid data"))
    if len(items) > FCI_ROWS_MAX * 4:
        raise BadInput(tr("Too many rows (at most {0})", FCI_ROWS_MAX * 4))
    rows = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid data"))
        try:
            rows.append(rk_fixed_clean({k: it.get(k) for k in ("label", "amount", "repeat", "start", "until", "category", "vat_rate")}))
        except BadInput as x:
            raise BadInput(tr("Row {0}: {1}", i + 1, str(x.args[0] if x.args else x))) from None
    write_lock(c, f"office_fixed_{int(oid)}")
    have = c.execute("SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=?", (oid,)).fetchone()[0]
    if have + len(rows) > MAX_FIXED:
        raise BadInput(tr("Too many fixed costs: at most {0}, {1} already there", MAX_FIXED, have))
    ts, ids = iso(now_utc()), []
    for row in rows:
        row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
        row = oc_enc_fields(c, oid, "office_fixed_costs", row)
        ids.append(insert_id(c, f"INSERT INTO office_fixed_costs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ofx_log(c, oid, "import", target="fixed_costs", detail={"count": len(ids)})
    bump(c)
    c.commit()
    return jsonify(created=len(ids), ids=ids), 201


@app.post("/api/office/fixed-costs/delete")
def fci_delete_many():
    """Office admin. {ids: [...]} -> deletes these fixed costs of the area (the undo of an import: one step)."""
    c, uid, oid = _ctx()
    b = body()
    ids = b.get("ids") if isinstance(b, dict) else None
    if not isinstance(ids, list) or len(ids) > FCI_ROWS_MAX * 4 or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid data"))
    ids = sorted(set(ids))
    n = c.execute(f"DELETE FROM office_fixed_costs WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", [oid] + ids).rowcount if ids else 0
    bump(c)
    c.commit()
    return jsonify(ok=True, deleted=n)


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
    head = ["Name", "Betrag (netto)", "fällig Monat"] if lang() == "de" else ["Name", "Amount (net)", "Due month"]  # what the import reads
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
    from .model import office_on, pb_owner
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
    from ..core.access import my_inbox
    from ..tasks.validation import log_act
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
    from ..tasks.validation import log_act
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
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_cfcheck_{int(oid)}")
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
