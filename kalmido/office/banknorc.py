"""2.299.0 C (#3192): bank bookings without a receipt -- the list, the counter of the office start page and the reminder task.

A booking "without a receipt" is an open one (office_bank_tx.match_kind NULL): money paid out that no receipt matched yet
(dir=out), or money received that no invoice matched yet (dir=in, the second filter). Private / ignored / "needs no receipt"
(match_kind noreceipt, office/bank.py) and matched bookings are not on the list. Every row carries day, amount, counterpart
and IBAN, so a later mailbox fetch can look for the receipt of exactly this booking (amount + day + sender).
The reminder (setting "bank_norc", set only by its own route here, the general settings route ignores it):
{every: off|week|month, user: uid, task: tid|None, next: ISO day}. While on, the watchdog keeps ONE open task in the inbox
of the person (one of the office admins; a personal office: its owner) as long as bookings without a receipt are there; it
is done by itself once the list is empty, a new one comes at the next date (weekly / monthly) when the list is not empty
again. No push of its own: the task is a normal task (due today).
Every route: office_ctx_admin like office/bank.py -- admins of the office area only (the person in a personal office);
agents and kids 403, foreign ids 404."""
import calendar
import re
import time
from datetime import date, timedelta

from flask import jsonify, request

from ..core.access import my_inbox
from ..core.config import PUBLIC_URL, WATCHDOG_INTERVAL, app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, lang, tr, trn
from ..core.pg import insert_id, system_ctx
from ..tasks.validation import log_act
from .bank import BNK_LIST_MAX, BNK_KINDS, _ctx, _home, _receipts, _shift, _tx_dec
from .books import bk_ws
from .calc import dec, dstr, money
from .cfbank import cfb_balances
from .fixedimport import fci_people, fci_task_end
from .ledger import ofx_log
from .model import office_settings, office_settings_lock, office_settings_save
from .periodlock import pl_is_locked

BNR_DIRS = ("out", "in")
BNR_EVERY = ("off", "week", "month")
BNR_EVERY_TICKS = 10  # the watchdog looks every 10th interval (5 min in production; whole days count)
_BNR_LAST = {"at": 0.0}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
BNR_RECEIPTS_MAX = 100
BNR_TASK_TEXT = N_("Upload the receipts of these bank bookings or mark them as not needing a receipt. The task is done by itself once every booking has its receipt.")
BNR_TASK_HELP = N_("Open the bookings without a receipt")


def _acct_by_import(c, oid):
    """{import id: account} for the imports whose balances name exactly one account (several or none: no account)."""
    seen = {}
    for b in cfb_balances(c, oid):
        if b["account"]:
            seen.setdefault(b["import_id"], set()).add(b["account"])
    return {i: next(iter(a)) for i, a in seen.items() if len(a) == 1}


def bnr_open(c, oid, direction="out", month=None, account=None):
    """The open bookings of area oid in direction out (amount < 0) | in (> 0), optionally of one month (YYYY-MM) and one
    account (cfbank's names); decrypted rows with "account" ('' = not known), newest first, at most BNK_LIST_MAX."""
    q, args = "SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL", [oid]
    if month:
        q += " AND day>=? AND day<=?"
        args += [month + "-01", month + "-31"]
    accts = _acct_by_import(c, oid)
    out = []
    for r in c.execute(q + " ORDER BY day DESC, id DESC", args).fetchall():
        t = _tx_dec(c, oid, r)
        if (t["amount"] < 0) != (direction == "out") or t["amount"] == 0:
            continue
        t["account"] = accts.get(t["import_id"], "")
        if account and t["account"] != account:
            continue
        out.append(t)
        if len(out) >= BNK_LIST_MAX:
            break
    return out


def bnr_counts(c, oid):
    """{out, in}: how many open bookings each direction has (all months, all accounts)."""
    n = {"out": 0, "in": 0}
    for r in c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL", (oid,)).fetchall():
        a = _tx_dec(c, oid, r)["amount"]
        if a:
            n["out" if a < 0 else "in"] += 1
    return n


def _row(c, oid, t):
    # the fields a later mailbox fetch needs to find the receipt: amount, day, counterpart (sender), IBAN
    return {"id": t["id"], "day": t["day"], "amount": dstr(t["amount"]), "currency": t["currency"], "counterpart": t["counterpart"] or "",
            "purpose": t["purpose"] or "", "iban": t["iban"], "account": t["account"], "locked": pl_is_locked(c, oid, t["day"])}


@app.get("/api/office/bank/noreceipt")
def bnr_list():
    """?dir=out|in (default out)&month=YYYY-MM&account= -> {items: [{id, day, amount, currency, counterpart, purpose, iban, account,
    locked}], counts: {out, in}, months (with open bookings of the direction), accounts (cfbank's, when more than one),
    receipts (not matched, without payment day, around the shown bookings: for dragging one onto a row), currency, upload_ws
    (the documents space for POST /api/docs), kinds (the match kinds this server knows)}."""
    c, uid, oid = _ctx()
    d = request.args.get("dir") or "out"
    if d not in BNR_DIRS:
        raise BadInput(tr("Invalid value: {0}", "dir"))
    mo = request.args.get("month") or ""
    if mo and not MONTH_RE.match(mo):
        raise BadInput(tr("Invalid value: {0}", "month"))
    acct = (request.args.get("account") or "")[:100]
    alls = bnr_open(c, oid, d)
    months = sorted({t["day"][:7] for t in alls if t["day"]}, reverse=True)
    accounts = sorted({t["account"] for t in alls if t["account"]})
    rows = [t for t in alls if (not mo or t["day"][:7] == mo) and (not acct or t["account"] == acct)]
    receipts = []
    if d == "out" and rows:
        taken = {r[0] for r in c.execute("SELECT match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt'", (oid,))}
        for r in _receipts(c, oid, _shift(min(t["day"] for t in rows), -60), _shift(max(t["day"] for t in rows), 60), uid):
            if r["node_id"] in taken or r.get("paid_at"):
                continue
            receipts.append({"id": r["node_id"], "label": r.get("title") or "", "amount": dstr(money(dec(r["amount"]))), "date": r["date"]})
        receipts = receipts[-BNR_RECEIPTS_MAX:][::-1]
    ws = bk_ws(c, oid)
    return jsonify(items=[_row(c, oid, t) for t in rows], counts=bnr_counts(c, oid), months=months, accounts=accounts if len(accounts) > 1 else [],
                   receipts=receipts, currency=_home(c, oid), upload_ws="private" if ws[0] == "u" else f"org:{oid}", kinds=list(BNK_KINDS))


@app.get("/api/office/bank/noreceipt/count")
def bnr_count():
    """{out, in} for the counter of the office start page (admins only, like every bank route: others 403)."""
    c, _uid, oid = _ctx()
    return jsonify(bnr_counts(c, oid))


# ---------------------------------------------------------------- the reminder
def bnr_clean(s):
    v = s.get("bank_norc") if isinstance(s.get("bank_norc"), dict) else {}
    every = v.get("every") if v.get("every") in BNR_EVERY else "off"
    user = v.get("user") if isinstance(v.get("user"), int) and not isinstance(v.get("user"), bool) else None
    task = v.get("task") if isinstance(v.get("task"), int) and not isinstance(v.get("task"), bool) else None
    nxt = v.get("next") if isinstance(v.get("next"), str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v.get("next")) else ""
    return {"every": every, "user": user, "task": task, "next": nxt}


def _next(day, every):
    d = date.fromisoformat(day)
    if every == "week":
        return (d + timedelta(days=7)).isoformat()
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def _alive(c, tid, person):
    """The task still waits: not done, not deleted, still the person's (a stored id never reaches another task)."""
    if not tid or not person:
        return False
    return bool(c.execute("SELECT 1 FROM tasks WHERE id=? AND created_by=? AND assignee_id=? AND status=0 AND deleted_at IS NULL",
                          (tid, person, person)).fetchone())


def _title(n, lg):
    return trn("{0} booking without a receipt", "{0} bookings without a receipt", n, lg=lg)


def _task_new(c, person, n, today):
    lg = lang(c, person)
    url = PUBLIC_URL.rstrip("/") + "/#office/bank/norc"
    content = f"{tr(BNR_TASK_TEXT, lg=lg)}\n\n[{tr(BNR_TASK_HELP, lg=lg)}]({url})"
    lid = my_inbox(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (lid, _title(n, lg), content, today, srt, ts, ts, person, url, person))
    log_act(c, tid, "created", uid=person)
    return tid


def bnr_apply(c, oid, s, today=None):
    """The reminder of area oid with settings s (the caller holds office_settings_lock and saves s when this returns True):
    a task while bookings without a receipt are there and the date is reached, its title follows the count, done when the
    list is empty. Returns True when s (or the task's title) changed."""
    cfg = bnr_clean(s)
    if cfg["every"] == "off":
        return False
    today = today or local_now().date().isoformat()
    person = cfg["user"]
    if person not in {p["id"] for p in fci_people(c, oid)}:
        return False  # no admin (any more): nothing until someone else is chosen (the settings show it)
    n = bnr_counts(c, oid)["out"]
    changed = False
    if _alive(c, cfg["task"], person):
        if n == 0:
            fci_task_end(c, cfg["task"], person)
            cfg["task"], changed = None, True
        else:
            t = _title(n, lang(c, person))
            changed = c.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=? AND title<>?", (t, iso(now_utc()), cfg["task"], t)).rowcount > 0
    elif n and (not cfg["next"] or cfg["next"] <= today):
        cfg["task"], cfg["next"], changed = _task_new(c, person, n, today), _next(today, cfg["every"]), True
    elif cfg["task"]:
        cfg["task"], changed = None, True  # done / deleted by the person: the next one at the next date
    if changed:
        s["bank_norc"] = cfg
    return changed


def bnr_area(c, oid, today=None):
    """One area's reminder in its own transaction under the settings lock (two runs at once: one task)."""
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    if bnr_apply(c, oid, s, today):
        office_settings_save(c, oid, s)
        bump(c)
    c.commit()


def bnr_tick(c, now=None, force=False):
    """Watchdog: every office area with the reminder on (see the module text). At most every BNR_EVERY_TICKS intervals."""
    if not force and time.monotonic() - _BNR_LAST["at"] < BNR_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _BNR_LAST["at"] = time.monotonic()
    today = (now or local_now()).date().isoformat()
    with system_ctx(c):  # which areas have the reminder at all; each is then read under its own lock
        oids = [r[0] for r in c.execute("SELECT org_id FROM office_settings WHERE data LIKE ? OR data LIKE ? ORDER BY org_id",  # pg-ok: exact JSON text, case-sensitive on purpose
                                        ('%"bank_norc": {"every": "week"%', '%"bank_norc": {"every": "month"%')).fetchall()]
    c.commit()
    for oid in oids:
        try:
            with system_ctx(c):
                bnr_area(c, oid, today)
        except Exception as e:  # noqa: BLE001 -- one broken area never stops the others
            c.rollback()
            print("bank bookings reminder", oid, "failed:", e, flush=True)


def _public(c, oid, s):
    cfg = bnr_clean(s)
    people = fci_people(c, oid)
    return {"every": cfg["every"], "user": cfg["user"], "task": cfg["task"] if _alive(c, cfg["task"], cfg["user"]) else None,
            "next": cfg["next"], "people": people, "count": bnr_counts(c, oid)["out"],
            "lost": bool(cfg["every"] != "off" and cfg["user"] and cfg["user"] not in {p["id"] for p in people})}


@app.get("/api/office/bank/noreceipt/reminder")
def bnr_rem_get():
    """{every: off|week|month, user, task (the open reminder task or null), next, people (who may get it), count, lost}."""
    c, _uid, oid = _ctx()
    return jsonify(_public(c, oid, office_settings(c, oid)))


@app.put("/api/office/bank/noreceipt/reminder")
def bnr_rem_put():
    """{every?, user?} (partial). Off: the open task is done (never deleted). Another person: the old task is done, the new
    person gets one. Switched on: the first task at once when bookings without a receipt are there. A person who is not
    an admin of this office: 400. Default person: the one who switches it on."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    old = bnr_clean(s)
    cfg = dict(old)
    if "every" in b:
        if b["every"] not in BNR_EVERY:
            raise BadInput(tr("Invalid value: {0}", "every"))
        cfg["every"] = b["every"]
    people = {p["id"] for p in fci_people(c, oid)}
    if "user" in b:
        if isinstance(b["user"], bool) or not isinstance(b["user"], int) or b["user"] not in people:
            raise BadInput(tr("This person is not an administrator of this office"))
        cfg["user"] = b["user"]
    if cfg["every"] != "off" and cfg["user"] not in people:
        cfg["user"] = uid if uid in people else (sorted(people)[0] if people else None)
        if cfg["user"] is None:
            raise BadInput(tr("This person is not an administrator of this office"))
    if cfg["every"] == "off" or cfg["user"] != old["user"]:
        fci_task_end(c, old["task"], old["user"])
        cfg["task"] = None
    if cfg["every"] != old["every"] or cfg["user"] != old["user"]:
        cfg["next"] = ""  # (again) on / another rhythm or person: the first reminder now
    s["bank_norc"] = cfg
    bnr_apply(c, oid, s)
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"bank_norc": {"every": s["bank_norc"]["every"], "user": s["bank_norc"]["user"]}})
    bump(c)
    c.commit()
    return jsonify(_public(c, oid, s))
