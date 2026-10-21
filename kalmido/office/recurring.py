"""2.91.0 A (#1923): invoice series -- a template invoice repeated every month / quarter / year (drafts or sent).

A series (office_inv_series) points at a template invoice of its office area (draft or finalised, not cancelled). For every
period start from `start` (the day of the month kept, the 31st becomes the month's last day; `until` = the optional last
period start) the watchdog makes a NEW invoice draft from the template with the same internal steps as duplicating a document
(office/docs.py DUP_SKIP, positions, number only at finalising, recalc): date = the day it is made, period of service = the
period (service_from .. the day before the next period start), the placeholders {period} {month} {quarter} {year} filled in
the project title, introduction, closing and the positions (unknown braces stay; the template keeps its placeholders).
auto_send 0: the draft waits for a person (a task in the inbox of the series' creator, else the area's admins); auto_send 1:
finalised (ledger.ofx_finalize: number, PDF / e-invoice) and mailed to the client (invoices.inv_send: checks, day budget);
when a check fails the invoice stays a draft and the task names the reason. The invoices made carry series_id +
series_period; the unique index office_docs_series keeps one per period. At most one period per series and run; more than
RIN_MAX_MISSED missed periods: only the newest is made, the task names the rest. The cash flow shows the expected income of
the coming periods (rin_cashflow, kind series). Every route: office_gate + office_org with the admin (like the cash flow)."""
import json
import re
import time
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import PUBLIC_URL, app
from ..core.db import IntegrityError, body, bump, db, iso, local_now, now_utc
from ..core.access import Denied
from ..core.i18n import N_, lang, tr
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.orgcrypt import oc_item_store
from ..personal.timetrack import BadInput
from .calc import dec, dstr, fmt_money, money
from .model import office_gate, office_on, office_org, office_role, office_settings, pb_cl_sql, pb_owner

RIN_EVERY = ("monthly", "quarterly", "yearly")
RIN_STEP = {"monthly": 1, "quarterly": 3, "yearly": 12}
RIN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RIN_MAX = 200                 # series per office area
RIN_MAX_MISSED = 3            # more missed periods than this: only the newest one is made
RIN_EVERY_TICKS = 10          # the watchdog section runs every 10th interval (the periods are whole days)
_RIN_LAST = {"at": 0.0}
RIN_PH_RE = re.compile(r"\{(period|month|quarter|year)\}")
RIN_MONTHS = {"de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"),
              "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")}
RIN_TASK_DRAFT = N_("Check and send the invoice draft of series {0}")
RIN_TASK_FAIL = N_("Invoice of series {0} not sent")
RIN_TASK_PAUSED = N_("Invoice series {0} paused")


def _ctx():
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=True)


def _j(s):
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


# ---------------------------------------------------------------- periods
def rin_nth(start, every, i):
    """The i-th period start (ISO day) of a series from start: i steps of months, the day of start kept (the 31st becomes
    the month's last day, like the fixed costs, cashflow.rk_fixed_days)."""
    y, m, d = int(start[:4]), int(start[5:7]), int(start[8:10])
    mm = m - 1 + i * RIN_STEP.get(every, 1)
    yy, mo = y + mm // 12, mm % 12 + 1
    nxt = date(yy + (mo == 12), mo % 12 + 1, 1)
    return date(yy, mo, min(d, (nxt - date(yy, mo, 1)).days)).isoformat()


def rin_index(start, every, day):
    """The index of the first period start on or after day (0 for a day up to start)."""
    if not day or day <= start:
        return 0
    step = RIN_STEP.get(every, 1)
    i = max(0, ((int(day[:4]) - int(start[:4])) * 12 + int(day[5:7]) - int(start[5:7])) // step - 1)
    while rin_nth(start, every, i) < day:
        i += 1
    return i


def rin_after(start, every, day):
    """The first period start after day."""
    i = rin_index(start, every, day)
    return rin_nth(start, every, i + (rin_nth(start, every, i) == day))


def rin_periods(s, first, last, limit=400):
    """The period starts of series row s from its next_date within [first, last] (ISO days), up to its until."""
    st, ev = s["start"], s["every"]
    if not st or not s["next_date"]:
        return []
    end = min(last, s["until"] or last)
    out, i = [], rin_index(st, ev, max(first, s["next_date"]))
    while len(out) < limit:
        p = rin_nth(st, ev, i)
        if p > end:
            break
        out.append(p)
        i += 1
    return out


# ---------------------------------------------------------------- placeholders
def rin_fill(text, period, nxt, lg, pack):
    """text with {period} {month} {quarter} {year} of the period [period, nxt) in the document's language lg; other braces stay."""
    if not text or "{" not in text:
        return text
    from .docs import _fmt_date
    p = date.fromisoformat(period)
    last = (date.fromisoformat(nxt) - timedelta(days=1)).isoformat()
    vals = {"period": f"{_fmt_date(period, pack)} - {_fmt_date(last, pack)}",
            "month": f"{RIN_MONTHS.get(lg, RIN_MONTHS['en'])[p.month - 1]} {p.year}",
            "quarter": f"Q{(p.month - 1) // 3 + 1} {p.year}", "year": str(p.year)}
    return RIN_PH_RE.sub(lambda m: vals[m.group(1)], text)


# ---------------------------------------------------------------- rows
def rin_row(c, oid, sid, deleted=False):
    r = c.execute("SELECT * FROM office_inv_series WHERE id=? AND org_id=?" + ("" if deleted else " AND deleted_at IS NULL"), (sid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def rin_template_ok(c, oid, tid):
    """The template row: an invoice of the area that is not cancelled; 404 otherwise (another area's id too)."""
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if not r or r["kind"] != "invoice":
        raise Denied(404)
    if r["status"] == "cancelled":
        raise BadInput(tr("A cancelled invoice cannot be repeated"))
    return r


def _date(v, name, required=False):
    if v in (None, ""):
        if required:
            raise BadInput(tr("Invalid value: {0}", name))
        return ""
    if isinstance(v, str) and RIN_DATE_RE.match(v.strip()):
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def _flag(v, name):
    if v in (True, 1, "1", "true"):
        return 1
    if v in (False, 0, "0", "false", None):
        return 0
    raise BadInput(tr("Invalid value: {0}", name))


def rin_clean(c, oid, b, cur=None):
    """The columns of a new series (cur None) or the changed ones of series row cur."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    new = cur is None
    if "template_id" in b or new:
        out["template_id"] = rin_template_ok(c, oid, b.get("template_id"))["id"]
    if "every" in b or new:
        ev = b.get("every") or "monthly"
        if ev not in RIN_EVERY:
            raise BadInput(tr("Invalid value: {0}", "every"))
        out["every"] = ev
    if "start" in b or new:
        out["start"] = _date(b.get("start"), "start", required=True)
    if "until" in b or new:
        out["until"] = _date(b.get("until"), "until")
    if "auto_send" in b or new:
        out["auto_send"] = _flag(b.get("auto_send"), "auto_send")
    if "active" in b and not new:
        out["active"] = _flag(b.get("active"), "active")
    if "title" in b or new:
        v = b.get("title")
        if v is not None and not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", "title"))
        out["title"] = re.sub(r"[\x00-\x1f\x7f]", "", v or "").strip()[:200]
    st, un = out.get("start", cur["start"] if cur else ""), out.get("until", cur["until"] if cur else "")
    if st and un and un < st:
        raise BadInput(tr("The end is before the start"))
    if "next_date" in b and not new:  # the client's undo of "make now" (a period start of the schedule)
        nd = _date(b.get("next_date"), "next_date", required=True)
        if nd < st or rin_nth(st, out.get("every", cur["every"]), rin_index(st, out.get("every", cur["every"]), nd)) != nd:
            raise BadInput(tr("Invalid value: {0}", "next_date"))
        out["next_date"] = nd
    return out


def _last_made(c, oid, sid):
    r = c.execute("SELECT MAX(series_period) FROM office_docs WHERE org_id=? AND series_id=? AND series_period<>''", (oid, sid)).fetchone()
    return r[0] if r and r[0] else ""


def rin_public(c, oid, r, made_all=None):
    from .invoices import inv_money_fields, inv_paid_map, inv_state
    t = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (r["template_id"], oid)).fetchone() if r["template_id"] else None
    tt = _j(t["totals"]) if t else {}
    tpl = None
    if t is not None:
        tpl = {"id": t["id"], "number": t["number"], "status": t["status"], "client_id": t["client_id"],
               "client": (_j(t["recipient"]).get("name") or ""), "project_title": t["project_title"] or "", "lang": t["lang"],
               "currency": t["currency"], "gross": tt.get("gross") or 0, "gross_text": fmt_money(tt.get("gross") or 0, t["lang"], t["currency"])}
    made = made_all.get(r["id"], []) if made_all is not None else _made(c, oid, [r["id"]]).get(r["id"], [])
    pm = inv_paid_map(c, oid, [x["id"] for x in made[:12]]) if made else {}
    rows = []
    for x in made[:12]:
        xt = _j(x["totals"])
        rows.append({"doc_id": x["id"], "number": x["number"], "status": x["status"], "state": inv_state(x, pm), "period": x["series_period"],
                     "gross": xt.get("gross") or 0, "gross_text": fmt_money(xt.get("gross") or 0, x["lang"], x["currency"]),
                     "open": inv_money_fields(x, pm)["open"] if x["locked_at"] else None})
    nxt = rin_periods(r, r["next_date"] or r["start"], "9999-12-31", 3) if r["active"] and not r["deleted_at"] else []
    # 2.144.5 C (#2021): without an own title the template's project title without placeholders (as in the cash flow)
    return {"id": r["id"], "title": r["title"] or rin_bare((tpl or {}).get("project_title")) or (tpl or {}).get("client") or "", "template_id": r["template_id"],
            "template": tpl, "every": r["every"], "start": r["start"], "until": r["until"], "next_date": r["next_date"],
            "auto_send": int(r["auto_send"] or 0), "active": int(r["active"] or 0), "made": rows, "made_count": len(made),
            "next_periods": nxt, "deleted": bool(r["deleted_at"]), "deleted_at": r["deleted_at"], "updated_at": r["updated_at"]}


def _made(c, oid, sids):
    out = {}
    if not sids:
        return out
    for x in c.execute(f"SELECT * FROM office_docs WHERE org_id=? AND series_id IN ({','.join('?' * len(sids))}) ORDER BY series_period DESC, id DESC",
                       (oid, *sids)):
        out.setdefault(x["series_id"], []).append(x)
    return out


# ---------------------------------------------------------------- making an invoice
def rin_make(c, oid, uid, s, period):
    """A new invoice draft of series row s for the period starting at period (see the module text); its id, or None when
    the period has its invoice already (unique index) or the template is gone. The caller commits."""
    from .docs import DUP_ITEM_SKIP, DUP_SKIP, _assign_number, doc_items, recalc
    from .ledger import ofx_log, ofx_number_at_finalize
    from .packs import office_pack
    t = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (s["template_id"], oid)).fetchone() if s["template_id"] else None
    if t is None or t["kind"] != "invoice" or t["status"] == "cancelled":
        return None
    from ..core.orgcrypt import oc_dec_fields
    t = oc_dec_fields(c, oid, "office_docs", t)
    st = office_settings(c, oid)
    pack = office_pack(st["pack"]) or office_pack("DE") or {}
    lg = "en" if t["lang"] == "en" else "de"
    nxt = rin_after(s["start"], s["every"], period)

    def fill(v):
        return rin_fill(v, period, nxt, lg, pack) if isinstance(v, str) else v
    row = {k: t[k] for k in t.keys() if k not in DUP_SKIP}
    today = local_now().date()
    ts = iso(now_utc())
    row.update(number="", status="draft", date=today.isoformat(), totals="{}", created_by=uid, created_at=ts, updated_at=ts, sent_at=None, valid_until="",
               service_from=period, service_to=(date.fromisoformat(nxt) - timedelta(days=1)).isoformat(), series_id=s["id"], series_period=period)
    for k in ("project_title", "intro", "closing"):
        if k in row:
            row[k] = fill(row[k])
    try:
        with c.savepoint():
            nid = insert_id(c, f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    except IntegrityError:
        return None  # this period has its invoice already
    for it in doc_items(c, t["id"], oid):
        it = {k: v for k, v in it.items() if k not in DUP_ITEM_SKIP}
        it.update(doc_id=nid, org_id=oid, title=fill(it.get("title")), detail=fill(it.get("detail")))
        it = oc_item_store(c, oid, it)
        c.execute(f"INSERT INTO office_doc_items({','.join(it)}) VALUES({','.join('?' * len(it))})", list(it.values()))
    if not ofx_number_at_finalize(st, "invoice"):
        _assign_number(c, oid, nid, st)
    recalc(c, oid, nid)
    ofx_log(c, oid, "series", doc_id=nid, detail={"series_id": s["id"], "period": period, "from_id": t["id"], "from_number": t["number"]})
    return nid


def rin_client_mail(c, oid, cid):
    if not cid:
        return ""
    cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone()
    if cl is None:
        return ""
    ks = cl.keys()
    return ((cl["email_invoice"] if "email_invoice" in ks else "") or (cl["email"] if "email" in ks else "") or "").strip()


def rin_send(c, oid, uid, did):
    """auto_send: finalise and mail invoice did (its client's invoice address) like the routes /finalize and /send do. On
    any failed check nothing is kept (savepoint): the invoice stays a draft. (ok, reason text, datev due)."""
    from ..integrations.mail import MAIL_OUT_ON
    from .docs import doc_row
    from .invoices import inv_send
    from .ledger import ofx_finalize
    if not MAIL_OUT_ON:
        return False, tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"), False
    to = rin_client_mail(c, oid, doc_row(c, oid, did)["client_id"])
    if not to:
        return False, tr("The client has no e-mail address for invoices"), False
    try:
        with c.savepoint():
            r = ofx_finalize(c, oid, uid, did)
            _files, datev = inv_send(c, oid, uid, r, {"to": to})
    except (BadInput, Denied) as e:
        return False, (e.text() if hasattr(e, "text") else str(e)) or tr("unknown"), False
    except Exception as e:  # noqa: BLE001 -- a mail server error: the draft stays, the reason goes to the person
        print("invoice series: sending", did, "failed:", e, flush=True)  # 2.91.0 review L3: the raw error (host, port) only in the log
        return False, tr("The mail server refused the mail or could not be reached"), False
    return True, "", datev


def rin_datev(c, oid, did):
    """The DATEV copy after the customer mail was committed (like the route /send); a failure is only reported."""
    from .docs import doc_row
    from .invoices import inv_datev
    try:
        inv_datev(c, oid, doc_row(c, oid, did))
        bump(c)
        c.commit()
    except Exception:  # noqa: BLE001
        c.rollback()


# ---------------------------------------------------------------- who hears about it
def rin_people(c, oid, s):
    """The persons who get the tasks of series row s: its creator while still an admin of the area with the office on, else
    the area's admins (fixedimport.fci_people). Never agents or kids."""
    from .fixedimport import fci_people
    people = fci_people(c, oid)
    ids = [p["id"] for p in people]
    if s["created_by"] in ids:
        return [s["created_by"]]
    return ids


def rin_task(c, person, title, text, doc_id=None):
    """A task in the person's inbox, theirs and assigned to them, due today: a link into the office, never an amount."""
    from ..core.access import my_inbox
    from ..tasks.validation import log_act
    lid = my_inbox(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    url = PUBLIC_URL.rstrip("/") + (f"/#office/offers/{int(doc_id)}" if doc_id else "/#office/offers")
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (lid, title[:300], text[:4000], local_now().date().isoformat(), srt, ts, ts, person, url, person))
    log_act(c, tid, "created", uid=person)
    return tid


def _tell(c, people, key, name, text, doc_id=None):
    for p in people:
        lg = lang(c, p)
        rin_task(c, p, tr(key, name, lg=lg), text(lg), doc_id)


def _name(c, oid, s):
    if s["title"]:
        return s["title"]
    t = c.execute("SELECT project_title, recipient FROM office_docs WHERE id=? AND org_id=?", (s["template_id"], oid)).fetchone() if s["template_id"] else None
    return (rin_bare(t["project_title"]) or _j(t["recipient"]).get("name") or "") if t else ""


def rin_bare(text):
    """2.91.0 review L4: a template's text without its placeholders (names of a series, cash flow labels)."""
    return re.sub(r"\s{2,}", " ", RIN_PH_RE.sub("", text or "")).strip(" -·,")


def _period_txt(period, nxt):
    try:
        return f"{date.fromisoformat(period).strftime('%d.%m.%Y')} - {(date.fromisoformat(nxt) - timedelta(days=1)).strftime('%d.%m.%Y')}"
    except ValueError:
        return period


# ---------------------------------------------------------------- one period of one series
def rin_step(c, oid, uid, s, period, people, missed=()):
    """Makes the invoice of period for series row s (draft or sent), moves next_date on, ends the series after until and
    tells the people. Returns (doc id or None, sent, datev due, why not sent). The caller commits."""
    nxt = rin_after(s["start"], s["every"], period)
    ts = iso(now_utc())
    act = 0 if s["until"] and nxt > s["until"] else int(s["active"] or 0)
    did = rin_make(c, oid, uid, s, period)
    c.execute("UPDATE office_inv_series SET next_date=?, active=?, updated_at=? WHERE id=? AND org_id=?", (nxt, act, ts, s["id"], oid))
    if did is None:
        return None, False, False, ""
    sent, why, datev = (rin_send(c, oid, uid, did) if s["auto_send"] else (False, "", False))
    name = _name(c, oid, s)
    pt = _period_txt(period, nxt)
    gone = (lambda lg: "\n" + tr("Missed periods without an invoice: {0}", ", ".join(missed), lg=lg)) if missed else (lambda lg: "")
    if s["auto_send"] and not sent:
        _tell(c, people, RIN_TASK_FAIL, name, lambda lg: tr("Period {0}. The invoice stays a draft: {1}", pt, why, lg=lg) + gone(lg), did)
    elif not sent:
        _tell(c, people, RIN_TASK_DRAFT, name, lambda lg: tr("Period {0}. Open the draft, check it and send it like any invoice.", pt, lg=lg) + gone(lg), did)
    elif missed:
        _tell(c, people, RIN_TASK_DRAFT, name, lambda lg: tr("Period {0} was sent.", pt, lg=lg) + gone(lg), did)
    return did, sent, datev, why


# ---------------------------------------------------------------- the watchdog
def rin_tick(c, now=None):
    """Every active series with next_date up to today (local): one period each (see the module text). Runs at most every
    RIN_EVERY_TICKS watchdog intervals. A series whose template is gone or cancelled is paused with a task."""
    from ..core.config import WATCHDOG_INTERVAL
    if time.monotonic() - _RIN_LAST["at"] < RIN_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _RIN_LAST["at"] = time.monotonic()
    today = (now or local_now()).date().isoformat()
    with system_ctx(c):  # the due series of every office area; each is then made in its admin's own context below
        due = c.execute("SELECT id, org_id FROM office_inv_series WHERE deleted_at IS NULL AND active=1 AND next_date<>'' AND next_date<=? "
                        "ORDER BY next_date, id LIMIT 500", (today,)).fetchall()
    c.commit()
    for d in due:
        try:
            _rin_one(c, d["org_id"], d["id"], today)
        except Exception as e:  # noqa: BLE001 -- one broken series never stops the others
            c.rollback()
            print("invoice series", d["id"], "failed:", e, flush=True)


def _rin_one(c, oid, sid, today):
    with system_ctx(c):  # who acts for this area (its admins), read before entering their context
        s0 = c.execute("SELECT * FROM office_inv_series WHERE id=? AND org_id=?", (sid, oid)).fetchone()
        people = rin_people(c, oid, s0) if s0 else []
    c.commit()
    if not s0 or not people:
        return
    actor = people[0]
    prev = c.ctx
    try:
        _rin_as(c, oid, sid, today, actor, people)
    finally:
        c.rollback()  # whatever is left open; then the watchdog's own context ("system") again (the hook followed g.user)
        c.set_ctx(*prev)


def _rin_as(c, oid, sid, today, actor, people):
    with app.test_request_context("/api/office/series"):
        g.user = c.execute("SELECT * FROM users WHERE id=?", (actor,)).fetchone()  # the area's admin: the log, the mail's sender name
        if g.user is None or office_role(c, actor, oid) != "admin" or not office_on(c, actor):
            return
        write_lock(c, f"office_series_{int(sid)}")
        s = c.execute("SELECT * FROM office_inv_series WHERE id=? AND org_id=? AND deleted_at IS NULL AND active=1", (sid, oid)).fetchone()
        if s is None or not s["next_date"] or s["next_date"] > today:
            c.rollback()
            return
        t = c.execute("SELECT kind, status FROM office_docs WHERE id=? AND org_id=?", (s["template_id"], oid)).fetchone() if s["template_id"] else None
        if t is None or t["kind"] != "invoice" or t["status"] == "cancelled":
            c.execute("UPDATE office_inv_series SET active=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
            name = _name(c, oid, s)
            _tell(c, people, RIN_TASK_PAUSED, name, lambda lg: tr("The template invoice of the series was deleted or cancelled. Pick another one and switch the series on again.", lg=lg))
            bump(c)
            c.commit()
            return
        if s["until"] and s["next_date"] > s["until"]:
            c.execute("UPDATE office_inv_series SET active=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
            bump(c)
            c.commit()
            return
        due = rin_periods(s, s["next_date"], today, limit=1000)
        missed = []
        period = s["next_date"]
        if len(due) > RIN_MAX_MISSED:
            period, missed = due[-1], due[:-1]
        did, sent, datev, _why = rin_step(c, oid, actor, s, period, people, [_period_txt(p, rin_after(s["start"], s["every"], p)) for p in missed[-12:]])
        bump(c)
        c.commit()
        if sent and datev:
            rin_datev(c, oid, did)


# ---------------------------------------------------------------- the cash flow
def rin_cashflow(c, oid, put, first, last_day, today, nf):
    """Planned income of the series in [first, last_day] for cashflow.rk_cashflow: their drafts (not yet in the plan as an
    open invoice) on the expected due day, and every coming period from next_date up to until on its period start plus the
    template's payment days. Amount = the template's gross (office currency through its rate), net through nf. Paused and
    deleted series count not; finalised invoices of a series are in the plan already (kind invoice)."""
    from .cashflow import _fx
    home = (office_settings(c, oid).get("currency") or "EUR").upper()
    sts = c.execute("SELECT * FROM office_inv_series WHERE org_id=? AND deleted_at IS NULL AND active=1", (oid,)).fetchall()
    if not sts:
        return
    st = office_settings(c, oid)
    days0 = int(st.get("payment_days") or 14)
    for d in c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind='invoice' AND series_id IS NOT NULL AND status='draft' "
                       "AND (locked_at IS NULL OR locked_at='')", (oid,)):
        if not any(s["id"] == d["series_id"] for s in sts):
            continue
        days = d["payment_days"] if d["payment_days"] is not None else days0
        day = (date.fromisoformat(d["date"]) + timedelta(days=int(days))).isoformat() if d["date"] else today
        day = today if day < today else day
        if first <= day <= last_day:
            put(day, "in", "plan", "series", dec(_j(d["totals"]).get("gross") or 0) / _fx(d, home) * nf(d), d["project_title"] or "",
                number=d["number"], doc_id=d["id"], series_id=d["series_id"], period=d["series_period"])
    for s in sts:
        t = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (s["template_id"], oid)).fetchone() if s["template_id"] else None
        if t is None or t["kind"] != "invoice" or t["status"] == "cancelled":
            continue
        gross = dec(_j(t["totals"]).get("gross") or 0) / _fx(t, home) * nf(t)
        days = t["payment_days"] if t["payment_days"] is not None else days0
        span = timedelta(days=int(days or 0))
        lo = (date.fromisoformat(first) - span).isoformat()
        for p in rin_periods(s, lo, last_day):
            day = (date.fromisoformat(p) + span).isoformat()
            day = today if day < today else day
            if first <= day <= last_day:
                put(day, "in", "plan", "series", gross, s["title"] or rin_bare(t["project_title"]), series_id=s["id"], period=p)


# ---------------------------------------------------------------- routes
@app.get("/api/office/series")
def rin_list():
    """?bin=1 = the deleted ones -> {items: [rin_public], docs: {doc id: [series id, period]}} (admins of the office area)."""
    c, uid, oid = _ctx()
    binq = request.args.get("bin") == "1"
    rows = c.execute("SELECT * FROM office_inv_series WHERE org_id=? AND deleted_at IS " + ("NOT NULL" if binq else "NULL") + " ORDER BY lower(title), id",
                     (oid,)).fetchall()
    made = _made(c, oid, [r["id"] for r in rows])
    docs = {}
    for sid, xs in made.items():
        for x in xs[:500]:
            docs[str(x["id"])] = [sid, x["series_period"]]
    return jsonify(items=[rin_public(c, oid, r, made) for r in rows], docs=docs)


@app.post("/api/office/series")
def rin_create():
    """{template_id, every, start, until?, auto_send?, title?} -> 201 the series (next_date = start)."""
    c, uid, oid = _ctx()
    b = body()
    if c.execute("SELECT COUNT(*) FROM office_inv_series WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= RIN_MAX:
        raise BadInput(tr("Too many entries"))
    row = rin_clean(c, oid, b)
    ts = iso(now_utc())
    row.update(org_id=oid, next_date=row["start"], active=1, created_by=uid, created_at=ts, updated_at=ts)
    sid = insert_id(c, f"INSERT INTO office_inv_series({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    from .ledger import ofx_log
    ofx_log(c, oid, "series_create", target="series", doc_id=row["template_id"], detail={"series_id": sid, "every": row["every"], "start": row["start"],
                                                                                         "until": row["until"], "auto_send": row["auto_send"]})
    bump(c)
    c.commit()
    return jsonify(rin_public(c, oid, rin_row(c, oid, sid))), 201


@app.patch("/api/office/series/<int:sid>")
def rin_patch(sid):
    """{every?, start?, until?, auto_send?, active?, title?, template_id?, next_date?} -> the series. A changed schedule
    starts again after the last period that has its invoice (else at start)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_series_{int(sid)}")
    cur = rin_row(c, oid, sid)
    row = rin_clean(c, oid, body(), cur)
    if row:
        if ("start" in row or "every" in row) and "next_date" not in row:
            st, ev = row.get("start", cur["start"]), row.get("every", cur["every"])
            last = _last_made(c, oid, sid)
            row["next_date"] = rin_after(st, ev, last) if last and last >= st else st
        if row.get("active") == 1 and not cur["active"]:
            nd, un = row.get("next_date", cur["next_date"]), row.get("until", cur["until"])
            if un and nd > un:
                raise Denied(409, tr("The series has ended; set a later end first"))
        row["updated_at"] = iso(now_utc())
        before = {k: cur[k] for k in row if k in cur.keys() and k != "updated_at"}
        c.execute(f"UPDATE office_inv_series SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [sid, oid])
        from .ledger import ofx_log
        ofx_log(c, oid, "series_update", target="series", doc_id=cur["template_id"], detail={"series_id": sid, "before": before,
                                                                                             "after": {k: v for k, v in row.items() if k != "updated_at"}})
        bump(c)
        c.commit()
    return jsonify(rin_public(c, oid, rin_row(c, oid, sid)))


@app.delete("/api/office/series/<int:sid>")
def rin_delete(sid):
    """Into the bin (the invoices made stay as they are); POST .../restore takes it back."""
    c, uid, oid = _ctx()
    r = rin_row(c, oid, sid)
    ts = iso(now_utc())
    c.execute("UPDATE office_inv_series SET deleted_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, sid, oid))
    from .ledger import ofx_log
    ofx_log(c, oid, "series_delete", target="series", doc_id=r["template_id"], detail={"series_id": sid})
    bump(c)
    c.commit()
    return jsonify(ok=True, item=rin_public(c, oid, rin_row(c, oid, sid, deleted=True)))


@app.post("/api/office/series/<int:sid>/restore")
def rin_restore(sid):
    c, uid, oid = _ctx()
    r = rin_row(c, oid, sid, deleted=True)
    if r["deleted_at"]:
        c.execute("UPDATE office_inv_series SET deleted_at=NULL, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
        from .ledger import ofx_log
        ofx_log(c, oid, "series_restore", target="series", doc_id=r["template_id"], detail={"series_id": sid})
        bump(c)
        c.commit()
    return jsonify(rin_public(c, oid, rin_row(c, oid, sid)))


@app.post("/api/office/series/<int:sid>/run")
def rin_run(sid):
    """"Make now": the invoice of the next period at once (also before its day); next_date moves on. One period per call.
    -> {series, doc_id, sent, error?}; 409 after the end, without a template or when the period has its invoice already."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_series_{int(sid)}")
    s = rin_row(c, oid, sid)
    if not s["next_date"] or (s["until"] and s["next_date"] > s["until"]):
        raise Denied(409, tr("The series has ended; set a later end first"))
    t = c.execute("SELECT kind, status FROM office_docs WHERE id=? AND org_id=?", (s["template_id"], oid)).fetchone() if s["template_id"] else None
    if t is None or t["kind"] != "invoice" or t["status"] == "cancelled":
        raise Denied(409, tr("The template invoice of the series was deleted or cancelled. Pick another one and switch the series on again."))
    prev = s["next_date"]
    nid, sent, datev, why = rin_step(c, oid, uid, s, s["next_date"], [])  # the person is here: no task for what they just did
    bump(c)
    c.commit()
    if nid is None:
        raise Denied(409, tr("This period has its invoice already"))
    if sent and datev:
        rin_datev(c, oid, nid)
    return jsonify(series=rin_public(c, oid, rin_row(c, oid, sid)), doc_id=nid, sent=bool(sent), prev_next_date=prev,
                   error=tr("The invoice stays a draft: {0}", why) if s["auto_send"] and not sent else None)
