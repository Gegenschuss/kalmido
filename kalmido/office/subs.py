"""2.91.0 B (#1924): subscriptions and tools -- fixed costs with a notice period, users and a reminder before they renew.

A subscription IS a fixed cost (office_fixed_costs, sub = 1): the fixed costs list, its import and this view edit the same rows
through the same routes (POST / PATCH / DELETE /api/office/fixed-costs; rk_fixed_clean calls abo_clean, _fixed_public calls
abo_public), the cash flow counts it once as a fixed cost. This module only adds the reading view:
  GET /api/office/subs      {items (sub = 1, by the last day to cancel / the next renewal), totals, candidates, people}
  GET /api/office/subs.csv  the same items as CSV (cells safe against formulas)
and the watchdog abo_tick: a task "Check subscription: <name>" in the inbox of remind_user remind_days before the last day
to cancel (without a notice period: before the renewal), once per row and day (office_sub_reminders). Never an amount in
the title, no push kind of its own (the task has the person's normal reminders).
Every route: office_gate + office_org with the admin of the office area (like the cash flow); a personal office: its owner."""
import csv
import io
import json
import re
import time
from datetime import date, timedelta

from flask import Response, jsonify

from ..core.config import PUBLIC_URL, app, WATCHDOG_INTERVAL
from ..core.db import iso, local_now, now_utc
from ..core.i18n import N_, lang, tr
from ..core.pg import insert_id
from ..personal.timetrack import _csv_cell
from ..core.errors import BadInput
from .calc import dec, dstr, money
from ..core.access import my_inbox  # 2.149.0 G (#2517): pulled up from functions

ABO_NOTICE_MAX = 730
ABO_REMIND_MAX = 90
ABO_SEATS_MAX = 40
ABO_SEAT_LEN = 80
ABO_URL_MAX = 500
ABO_CANDIDATES_MAX = 20
ABO_SMALL_MONTH = dec(50)  # a monthly / yearly cost up to 50 a month (gross) may be a tool
ABO_CAT_RE = re.compile(r"software|abo|tool|lizenz|licen[cs]|saas|subscri|cloud|hosting|app\b|logiciel|abonnement|suscrip|"
                        r"abbonament|programm|licentie", re.I)
ABO_NOT_RE = re.compile(r"miete|rent|loyer|alquiler|affitto|huur|versicherung|insurance|assurance|seguro|assicura|verzeker|"
                        r"steuer|tax|kammer|beitrag|rundfunk|gehalt|lohn|salary", re.I)
ABO_PER = {"monthly": (dec(1), dec(12)), "quarterly": (dec(1) / 3, dec(4)), "yearly": (dec(1) / 12, dec(1)), "once": (dec(0), dec(0))}
ABO_EVERY_TICKS = 10  # the reminders run every 10th watchdog interval (whole days)
_ABO_LAST = {"at": 0.0}
ABO_TASK_TITLE = N_("Check subscription: {0}")
ABO_TASK_TEXT = N_("Cancel or keep? The last day to cancel is {0}.")
ABO_TASK_TEXT_RENEW = N_("Cancel or keep? It renews on {0}.")


def _today():
    return local_now().date().isoformat()


def _int(v, name, hi):
    if isinstance(v, bool) or v in (None, ""):
        v = 0
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None
    if n != (float(v) if isinstance(v, (int, float)) else n) or not 0 <= n <= hi:
        raise BadInput(tr("Invalid value: {0}", name))
    return n


def _flag(v, name):
    if v in (1, True, "1", "true"):
        return 1
    if v in (0, False, "0", "false", None, ""):
        return 0
    raise BadInput(tr("Invalid value: {0}", name))


def abo_seats(raw):
    """The stored seats (JSON [user id | free name]) as a list; anything broken = []."""
    try:
        v = json.loads(raw) if isinstance(raw, str) and raw else raw
    except ValueError:
        return []
    return [x for x in v if (isinstance(x, int) and not isinstance(x, bool)) or isinstance(x, str)] if isinstance(v, list) else []


def abo_people(c, oid):
    """[{id, name}] who can be a user of a subscription of office area oid: the members of the organisation (no agents, no
    kids, no disabled accounts); a personal office: only its owner."""
    from .model import pb_owner
    owner = pb_owner(c, oid)
    if owner is not None:
        ids = [owner]
    else:
        # 2.143.0 A (#2151, review): the organisation's staff (admin, member, read-only), not guests / accounting
        ids = [r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role IN ('admin','member','readonly')", (oid,))]
    if not ids:
        return []
    out = []
    for u in c.execute(f"SELECT * FROM users WHERE id IN ({','.join('?' * len(ids))}) AND disabled=0", ids).fetchall():
        ks = u.keys()
        if ("kind" in ks and u["kind"] == "agent") or ("kid" in ks and u["kid"]):
            continue
        out.append({"id": u["id"], "name": u["display_name"] or u["username"]})
    out.sort(key=lambda x: x["name"].casefold())
    return out


def abo_clean(c, oid, b, cur):
    """The subscription fields of a fixed cost body b (rk_fixed_clean; cur = the row as it is, {} for a new one): sub 0/1,
    notice_days 0..730, seats [person of the area | free name] (<= 40, a name <= 80 characters), low_use 0/1,
    remind_days 0..90, remind_user an office admin (fci_people) or none, url http(s) <= 500. A person id that is no longer in
    the area may stay where it already was (the row can still be saved); a new foreign id = 400. Without c (the import:
    fci_clean_rows) seats and remind_user are left alone (their defaults)."""
    from .fixedimport import fci_people
    out = {}
    new = not cur
    if c is None:
        b = {k: v for k, v in b.items() if k not in ("seats", "remind_user")}
    if "sub" in b or new:
        out["sub"] = _flag(b.get("sub", 0), "sub")
    if "notice_days" in b or new:
        out["notice_days"] = _int(b.get("notice_days", 0), "notice_days", ABO_NOTICE_MAX)
    if "low_use" in b or new:
        out["low_use"] = _flag(b.get("low_use", 0), "low_use")
    if "remind_days" in b or new:
        out["remind_days"] = _int(b.get("remind_days", 0), "remind_days", ABO_REMIND_MAX)
    if "seats" in b or (new and c is not None):
        v = b.get("seats") or []
        if not isinstance(v, list) or len(v) > ABO_SEATS_MAX:
            raise BadInput(tr("Invalid value: {0}", "seats"))
        known = {p["id"] for p in abo_people(c, oid)} | {x for x in abo_seats(cur.get("seats")) if isinstance(x, int)}
        seats = []
        for x in v:
            if isinstance(x, bool):
                raise BadInput(tr("Invalid value: {0}", "seats"))
            if isinstance(x, int):
                if x not in known:
                    raise BadInput(tr("Invalid value: {0}", "seats"))
            elif isinstance(x, str):
                x = re.sub(r"[\x00-\x1f\x7f]", "", x).strip()[:ABO_SEAT_LEN]
                if not x:
                    continue
            else:
                raise BadInput(tr("Invalid value: {0}", "seats"))
            if x not in seats:
                seats.append(x)
        out["seats"] = json.dumps(seats, ensure_ascii=False)
    if "remind_user" in b or (new and c is not None):
        v = b.get("remind_user")
        if v in (None, "", 0):
            out["remind_user"] = None
        else:
            if isinstance(v, bool) or not isinstance(v, int) or (v != cur.get("remind_user") and v not in {p["id"] for p in fci_people(c, oid)}):
                raise BadInput(tr("Invalid value: {0}", "remind_user"))
            out["remind_user"] = v
    if "url" in b or new:
        v = b.get("url") or ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", "url"))
        v = re.sub(r"[\x00-\x20\x7f]", "", v)
        if v and (len(v) > ABO_URL_MAX or not re.match(r"^https?://[^/?#]+", v, re.I)):
            raise BadInput(tr("Invalid value: {0}", "url"))
        out["url"] = v
    return out


def abo_next(f, today):
    """The next due day of fixed cost f on or after today ('' when there is none any more): the day rk_fixed_days would
    give, without walking from the start (the 31st becomes the month's last day)."""
    st = f.get("start") or ""
    if not st:
        return ""
    un = f.get("until") or ""
    if f.get("repeat") == "once":
        return st if st >= today and (not un or st <= un) else ""
    step = {"quarterly": 3, "yearly": 12}.get(f.get("repeat"), 1)
    y, m, d = int(st[:4]), int(st[5:7]), int(st[8:10])
    ty, tm = int(today[:4]), int(today[5:7])
    i = max(0, ((ty - y) * 12 + tm - m) // step - 1)
    for _ in range(4):
        mm = m - 1 + i * step
        yy, mo = y + mm // 12, mm % 12 + 1
        nxt = date(yy + (mo == 12), mo % 12 + 1, 1)
        day = date(yy, mo, min(d, (nxt - date(yy, mo, 1)).days)).isoformat()
        if day >= today:
            return day if not un or day <= un else ""
        i += 1
    return ""


def abo_public(d, out, today=None):
    """The subscription fields of a fixed cost for _fixed_public (d = the decrypted row, out = the public fields so far):
    the stored ones and next_renewal, cancel_by (next_renewal - notice_days, '' without one), per_month / per_year (gross)
    and per_month_net / per_year_net (monthly x1 / x12, quarterly /3 x4, yearly /12 x1, once 0)."""
    today = today or _today()
    ks = d.keys() if hasattr(d, "keys") else ()
    g = lambda k, dv=0: d.get(k) if k in ks and d.get(k) is not None else dv  # noqa: E731 (a row of the version before)
    nr = abo_next(out, today)
    nd = int(g("notice_days") or 0)
    cb = (date.fromisoformat(nr) - timedelta(days=nd)).isoformat() if nr and nd else ""
    # 2.144.5 C (#2021): the last day for the next renewal has passed -> cancel_missed = 1 and cancel_next = the last day of
    # the first later renewal that can still be reached ('' when the cost ends before); cancel_by keeps its meaning
    missed, cn = int(bool(cb) and cb < today), ""
    if missed:
        day = nr
        for _ in range(40):  # notice <= 730 days: a monthly cost needs at most ~25 steps
            day = abo_next(out, (date.fromisoformat(day) + timedelta(days=1)).isoformat())
            if not day:
                break
            x = (date.fromisoformat(day) - timedelta(days=nd)).isoformat()
            if x >= today:
                cn = x
                break
    pm, py = ABO_PER.get(out.get("repeat"), ABO_PER["monthly"])
    gross, net = dec(out["gross"]), dec(out["amount"])
    return {"sub": int(g("sub") or 0), "notice_days": nd, "seats": abo_seats(g("seats", "[]")), "low_use": int(g("low_use") or 0),
            "remind_days": int(g("remind_days") or 0), "remind_user": g("remind_user", None), "url": g("url", "") or "",
            "next_renewal": nr, "cancel_by": cb, "cancel_missed": missed, "cancel_next": cn,
            "per_month": dstr(money(gross * pm)), "per_year": dstr(money(gross * py)),
            "per_month_net": dstr(money(net * pm)), "per_year_net": dstr(money(net * py))}


def _running(f, today):
    return f["repeat"] != "once" and (not f["until"] or f["until"] >= today)


def abo_candidate(f, today):
    """A fixed cost that looks like a subscription / tool (a proposal only, never marked by itself): its category or name
    reads like software / subscription / licence, or it repeats monthly / yearly with a small amount; never rent, insurance,
    taxes or salaries, nothing that has ended."""
    if f["sub"] or not _running(f, today) or f["repeat"] == "quarterly":
        return False
    txt = f"{f['category']} {f['label']}"
    if ABO_NOT_RE.search(txt):
        return False
    return bool(ABO_CAT_RE.search(txt)) or dec(f["per_month"]) <= ABO_SMALL_MONTH


def abo_view(c, oid):
    from .cashflow import rk_fixed
    today = _today()
    fx = rk_fixed(c, oid)
    people = abo_people(c, oid)
    names = {p["id"]: p["name"] for p in people}
    items = [f for f in fx if f["sub"]]
    for f in items:
        f["seat_names"] = [names.get(x, "") if isinstance(x, int) else x for x in f["seats"]]
        f["running"] = _running(f, today)
    # 2.144.5 C (#2021): a missed notice sorts by its next chance
    items.sort(key=lambda f: (not f["running"], (f["cancel_next"] or "9999") if f["cancel_missed"] else f["cancel_by"] or f["next_renewal"] or "9999",
                              f["label"].casefold(), f["id"]))
    run = [f for f in items if f["running"]]
    low = [f for f in run if f["low_use"]]
    s = lambda xs, k: dstr(money(sum((dec(f[k]) for f in xs), dec(0))))  # noqa: E731
    totals = {"per_month": s(run, "per_month"), "per_year": s(run, "per_year"), "per_month_net": s(run, "per_month_net"),
              "per_year_net": s(run, "per_year_net"), "low_use_per_year": s(low, "per_year"), "low_use_per_year_net": s(low, "per_year_net"),
              "count": len(run), "low_use_count": len(low)}
    cands = [{k: f[k] for k in ("id", "label", "category", "amount", "gross", "repeat", "per_month", "per_month_net")}
             for f in fx if abo_candidate(f, today)][:ABO_CANDIDATES_MAX]
    from .fixedimport import fci_people
    return {"items": items, "totals": totals, "candidates": cands, "people": people, "remind_people": fci_people(c, oid), "today": today}


@app.get("/api/office/subs")
def abo_get():
    """Office admin. {items: the fixed costs with sub = 1 (+ seat_names, running), totals: {per_month, per_year (gross),
    *_net, low_use_per_year (the saving), count, low_use_count}, candidates: fixed costs that look like a subscription,
    people: who can be a user, remind_people: who can get the reminder}."""
    from .cashflow import _ctx
    c, uid, oid = _ctx()
    return jsonify(abo_view(c, oid))


@app.get("/api/office/subs.csv")
def abo_csv():
    """Office admin. The subscriptions as CSV (German: ';' and decimal comma); every text cell safe against formulas."""
    from .cashflow import _ctx
    c, uid, oid = _ctx()
    v = abo_view(c, oid)
    de = lang() == "de"
    num = (lambda x: x.replace(".", ",")) if de else (lambda x: x)  # noqa: E731
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if de else ",")
    w.writerow([tr("Name"), tr("Category"), tr("Repeat"), tr("Amount") + " (" + tr("net") + ")", tr("VAT rate"), tr("per month"),
                tr("per year"), tr("Next renewal"), tr("Cancel by"), tr("Notice period (days)"), tr("Users"), tr("Hardly used"), tr("Web address")])
    for f in v["items"]:
        w.writerow([_csv_cell(f["label"]), _csv_cell(f["category"]), tr(f["repeat"]), num(f["amount"]), f["vat_rate"], num(f["per_month"]),
                    num(f["per_year"]), f["next_renewal"], f["cancel_by"], f["notice_days"], _csv_cell(", ".join(x for x in f["seat_names"] if x)),
                    tr("yes") if f["low_use"] else "", _csv_cell(f["url"])])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{tr("subscriptions")}.csv"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- the reminder
def abo_task_new(c, person, label, due, text):
    """The reminder task in the person's inbox, theirs and assigned to them (the pattern of fci_task_new): the name, never an
    amount; due on the last day to cancel; a link to the view."""
    from ..tasks.validation import log_act
    lid = my_inbox(c, person)
    lg = lang(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (lid, tr(ABO_TASK_TITLE, label[:150], lg=lg), text, due, srt, ts, ts, person, PUBLIC_URL.rstrip("/") + "/#office/subs", person))
    log_act(c, tid, "created", uid=person)
    return tid


def _fmt_day(day, lg):
    d = date.fromisoformat(day)
    return d.isoformat() if lg == "en" else f"{d.day:02d}-{d.month:02d}-{d.year}" if lg == "nl" else \
        f"{d.day:02d}.{d.month:02d}.{d.year}" if lg == "de" else f"{d.day:02d}/{d.month:02d}/{d.year}"


def abo_tick(c, now=None, force=False):
    """Watchdog: for every running subscription with a reminder (remind_days > 0, remind_user) the task once per last day
    to cancel (cancel_by; without a notice period the next renewal) from that day - remind_days up to that day. Nothing
    when the person is no longer an office admin of the area, their account is disabled or the office is off for them
    (fci_people). A task once made stays (also when the row is deleted or the reminder switched off). Runs at most every
    ABO_EVERY_TICKS watchdog intervals."""
    from .cashflow import _fixed_public
    from .fixedimport import fci_people
    if not force and time.monotonic() - _ABO_LAST["at"] < ABO_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _ABO_LAST["at"] = time.monotonic()
    today = _today()
    rows = c.execute("SELECT * FROM office_fixed_costs WHERE sub=1 AND remind_days>0 AND remind_user IS NOT NULL ORDER BY org_id, id").fetchall()
    people = {}
    for r in rows:
        oid = r["org_id"]
        try:
            f = _fixed_public(c, oid, r)
        except Exception:  # noqa: BLE001 (a row that cannot be read, e.g. no key: the next one)
            continue
        due = f["cancel_by"] or f["next_renewal"]
        if f.get("cancel_missed") and f.get("cancel_next"):  # 2.144.5 C (#2021): the next reachable last day, not the missed one
            due = f["cancel_next"]
        if not due or not _running(f, today) or today > due:
            continue
        if today < (date.fromisoformat(due) - timedelta(days=f["remind_days"])).isoformat():
            continue
        if c.execute("SELECT 1 FROM office_sub_reminders WHERE fixed_id=? AND due=?", (r["id"], due)).fetchone():
            continue
        if oid not in people:
            people[oid] = {p["id"] for p in fci_people(c, oid)}
        pid = f["remind_user"]
        if pid not in people[oid]:
            continue
        # 2.91.0 review M1: one row that fails (inbox, database) must not hold back the reminders of every row after it
        try:
            if not c.execute("INSERT INTO office_sub_reminders(org_id,fixed_id,due,user_id,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                             (oid, r["id"], due, pid, iso(now_utc()))).rowcount:
                continue
            lg = lang(c, pid)
            tid = abo_task_new(c, pid, f["label"], due, tr(ABO_TASK_TEXT if f["cancel_by"] else ABO_TASK_TEXT_RENEW, _fmt_day(due, lg), lg=lg))
            c.execute("UPDATE office_sub_reminders SET task_id=? WHERE fixed_id=? AND due=?", (tid, r["id"], due))
            c.commit()
        except Exception as e:  # noqa: BLE001
            c.rollback()
            print("subscription reminder", r["id"], "failed:", e, flush=True)
