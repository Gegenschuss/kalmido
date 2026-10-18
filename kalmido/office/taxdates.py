"""2.90.0 C (#1922): tax dates as recurring tasks (VAT return, income tax prepayments, trade tax).

Setting office `tax_dates` (set only by the routes here, the general settings route ignores it):
{ustva: none|month|quarter, ustva_ext: 0|1, est: 0|1, gewst: 0|1, lead_days: 0-30, user: uid, tasks: {kind: tid|None}, sig: {kind: str}}.
One recurring task per switched-on kind in the inbox of the person (pattern: fixedimport.py, the monthly cash flow check)."""
import calendar
from datetime import date

from flask import jsonify

from ..core.config import PUBLIC_URL, app
from ..core.db import body, bump, iso, local_now, now_utc, write_lock
from ..core.i18n import N_, lang, tr
from ..core.pg import insert_id
from ..personal.timetrack import BadInput
from .cashflow import _ctx
from .fixedimport import fci_people, fci_task_end
from .model import office_settings, office_settings_save

TXD_KINDS = ("ustva", "est", "gewst")
TXD_USTVA = ("none", "month", "quarter")
TXD_LEAD = 3
# kind -> (day of the deadline, titles); the months follow from the configuration (txd_months)
TXD_TITLES = {"ustva": N_("Submit the VAT return (deadline: the 10th)"),
              "est": N_("Pay the income tax prepayment (deadline: the 10th)"),
              "gewst": N_("Pay the trade tax prepayment (deadline: the 15th)")}
TXD_DAY = {"ustva": 10, "est": 10, "gewst": 15}
TXD_TEXT = {"ustva": N_("Prepare and submit the advance VAT return."),
            "est": N_("Pay the quarterly income tax prepayment."),
            "gewst": N_("Pay the quarterly trade tax prepayment.")}
TXD_NOTE = N_("No tax advice; figures without guarantee.")
TXD_WEEKEND = N_("If the deadline falls on a weekend or a public holiday, the next working day applies.")
TXD_HELP = N_("Open the VAT return preparation")


def txd_clean(s):
    """The stored tax_dates with every key present and valid."""
    d = s.get("tax_dates") if isinstance(s.get("tax_dates"), dict) else {}
    lead = d.get("lead_days")
    tasks = d.get("tasks") if isinstance(d.get("tasks"), dict) else {}
    sig = d.get("sig") if isinstance(d.get("sig"), dict) else {}
    return {"ustva": d.get("ustva") if d.get("ustva") in TXD_USTVA else "none",
            "ustva_ext": 1 if d.get("ustva_ext") in (1, True) else 0,
            "est": 1 if d.get("est") in (1, True) else 0, "gewst": 1 if d.get("gewst") in (1, True) else 0,
            "lead_days": lead if isinstance(lead, int) and not isinstance(lead, bool) and 0 <= lead <= 30 else TXD_LEAD,
            "user": d.get("user") if isinstance(d.get("user"), int) and not isinstance(d.get("user"), bool) else None,
            "tasks": {k: tasks.get(k) if isinstance(tasks.get(k), int) else None for k in TXD_KINDS},
            "sig": {k: sig.get(k) if isinstance(sig.get(k), str) else "" for k in TXD_KINDS}}


def txd_months(kind, cfg):
    """The calendar months (1-12) with a deadline of this kind, [] when it is off."""
    if kind == "ustva":
        if cfg["ustva"] == "month":
            return list(range(1, 13))
        if cfg["ustva"] == "quarter":
            sh = 1 if cfg["ustva_ext"] else 0  # permanent extension: one month later
            return [1 + sh, 4 + sh, 7 + sh, 10 + sh]
        return []
    if kind == "est":
        return [3, 6, 9, 12] if cfg["est"] else []
    return [2, 5, 8, 11] if cfg["gewst"] else []


def txd_deadlines(kind, cfg, frm, n=1):
    """The first n deadlines (date) of the kind on or after frm."""
    months = txd_months(kind, cfg)
    out = []
    y, m = frm.year, frm.month
    for _ in range(40):
        if m in months:
            d = date(y, m, TXD_DAY[kind])
            if d >= frm:
                out.append(d)
                if len(out) >= n:
                    break
        y, m = y + (m == 12), m % 12 + 1
    return out


def txd_due(dl, lead):
    return date.fromordinal(dl.toordinal() - lead)


def txd_repeat(kind, cfg, dl, due):
    """RRULE for the task: its due day is the deadline minus the lead; a lead that reaches into the previous month counts from the
    month's end (exact for every month length)."""
    if due.month == dl.month:
        day = due.day
    else:
        day = -(calendar.monthrange(due.year, due.month)[1] - due.day + 1)
    step = 1 if kind == "ustva" and cfg["ustva"] == "month" else 3
    return f"FREQ=MONTHLY;INTERVAL={step};BYMONTHDAY={day}" if step > 1 else f"FREQ=MONTHLY;BYMONTHDAY={day}"


def txd_sig(kind, cfg, person):
    return f"{kind}|{cfg['ustva'] if kind == 'ustva' else 1}|{cfg['ustva_ext'] if kind == 'ustva' else 0}|{cfg['lead_days']}|{person}"


def txd_task_new(c, kind, cfg, person):
    """The recurring task in the person's inbox (theirs, assigned to them), due at the next deadline minus the lead."""
    from ..core.access import my_inbox
    from ..tasks.validation import log_act
    lead = cfg["lead_days"]
    today = local_now().date()
    dl = next((d for d in txd_deadlines(kind, cfg, today, 14) if txd_due(d, lead) >= today), None)
    if dl is None:
        return None
    due = txd_due(dl, lead)
    lg = lang(c, person)
    base = PUBLIC_URL.rstrip("/")
    url = base + "/#office/books/ustva" if kind == "ustva" else base + "/#office/books"
    content = f"{tr(TXD_TEXT[kind], lg=lg)}\n\n[{tr(TXD_HELP, lg=lg)}]({url})\n\n_{tr(TXD_NOTE, lg=lg)} {tr(TXD_WEEKEND, lg=lg)}_"
    lid = my_inbox(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,repeat,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (lid, tr(TXD_TITLES[kind], lg=lg), content, due.isoformat(), txd_repeat(kind, cfg, dl, due), srt, ts, ts, person, url, person))
    log_act(c, tid, "created", uid=person)
    return tid


def txd_alive(c, tid, person):
    """The task still runs: not done, not deleted, still recurring, still the person's."""
    if not tid or not person:
        return False
    return bool(c.execute("SELECT 1 FROM tasks WHERE id=? AND created_by=? AND assignee_id=? AND status=0 AND deleted_at IS NULL AND repeat<>''",
                          (tid, person, person)).fetchone())


def txd_next(cfg, n=3):
    today = local_now().date()
    rows = []
    for k in TXD_KINDS:
        for d in txd_deadlines(k, cfg, today, n):
            rows.append({"kind": k, "date": d.isoformat(), "due": txd_due(d, cfg["lead_days"]).isoformat()})
    rows.sort(key=lambda r: (r["date"], r["kind"]))
    return rows[:n]


def txd_public(c, oid, s):
    cfg = txd_clean(s)
    people = fci_people(c, oid)
    ids = {p["id"] for p in people}
    on = [k for k in TXD_KINDS if txd_months(k, cfg)]
    return {"ustva": cfg["ustva"], "ustva_ext": cfg["ustva_ext"], "est": cfg["est"], "gewst": cfg["gewst"], "lead_days": cfg["lead_days"],
            "user": cfg["user"], "tasks": cfg["tasks"], "people": people, "small_business": bool(s.get("small_business")),
            "lost": bool(on and cfg["user"] and cfg["user"] not in ids), "next": txd_next(cfg)}


@app.get("/api/office/tax-dates")
def txd_get():
    """Office admin. {ustva, ustva_ext, est, gewst, lead_days, user, tasks, people, small_business, lost, next: [{kind, date, due}]}."""
    c, uid, oid = _ctx()
    return jsonify(txd_public(c, oid, office_settings(c, oid)))


@app.put("/api/office/tax-dates")
def txd_put():
    """Office admin, partial body. Each switched-on kind has ONE recurring task for the person; changing a kind or the person ends the old task
    (done, never deleted) and makes a new one; a task the user finished or deleted is made again. A person who is not an admin here: 400."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_taxdates_{int(oid)}")
    s = office_settings(c, oid)
    old = txd_clean(s)
    cfg = dict(old, tasks=dict(old["tasks"]), sig=dict(old["sig"]))
    if "ustva" in b:
        if b["ustva"] not in TXD_USTVA:
            raise BadInput(tr("Invalid value: {0}", "ustva"))
        cfg["ustva"] = b["ustva"]
    for k in ("ustva_ext", "est", "gewst"):
        if k in b:
            cfg[k] = 1 if b[k] in (1, True, "1", "true") else 0
    if "lead_days" in b:
        v = b["lead_days"]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 30:
            raise BadInput(tr("Invalid value: {0}", "lead_days"))
        cfg["lead_days"] = v
    people = {p["id"] for p in fci_people(c, oid)}
    if "user" in b:
        if isinstance(b["user"], bool) or not isinstance(b["user"], int) or b["user"] not in people:
            raise BadInput(tr("This person is not an administrator of this office"))
        cfg["user"] = b["user"]
    person = cfg["user"]
    wanted = [k for k in TXD_KINDS if txd_months(k, cfg)]
    if wanted and person not in people:
        person = uid if uid in people else (sorted(people)[0] if people else None)
        if person is None:
            raise BadInput(tr("This person is not an administrator of this office"))
        cfg["user"] = person
    for k in TXD_KINDS:
        tid = old["tasks"].get(k)
        if k not in wanted:
            fci_task_end(c, tid, old["user"])
            cfg["tasks"][k], cfg["sig"][k] = None, ""
            continue
        sig = txd_sig(k, cfg, person)
        if tid and old["sig"].get(k) == sig and txd_alive(c, tid, person):
            continue
        fci_task_end(c, tid, old["user"])
        cfg["tasks"][k], cfg["sig"][k] = txd_task_new(c, k, cfg, person), sig
    s["tax_dates"] = cfg
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"tax_dates": {k: cfg[k] for k in ("ustva", "ustva_ext", "est", "gewst", "lead_days")}})
    bump(c)
    c.commit()
    return jsonify(txd_public(c, oid, s))
