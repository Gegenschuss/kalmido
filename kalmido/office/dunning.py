"""2.147.1 B (#2054): payment reminders suggested for overdue invoices (drafts only; nothing is sent automatically).

The watchdog (dun_tick, every DUN_EVERY_TICKS intervals) looks at every office area -- organisations AND the personal
office of a person without one -- that has finalised, open invoices (issued / sent, an open amount, not cancelled) and
makes ONE reminder draft per client + currency + level with the same steps as "Create reminder"
(invoices.inv_make_reminder, recalc, the office log "create" with auto 1) when, with the setting "dunning_suggest" on:
  - level 1: the due date lies more than "dunning_grace_days" days back (default 7),
  - level n+1 (max 3): the last finalised reminder of the invoice has passed its deadline (its date + deadline days) by
    more than those days,
  - no reminder DRAFT names the invoice yet (it waits for a person) and the invoice + level was never suggested before
    (office_dunning_marks; a draft deleted by hand is not suggested again on the same level -- only on the next one).
The people of the area (fixedimport.fci_people: its admins with the office on; a personal office: its owner) get one task
in their inbox per run with new drafts (recurring.rin_task: link, no amounts). Sending stays the person's (the send
dialog). GET /api/office/docs answers "dunning" {suggested: open suggested drafts} for the invoice + reminder lists and
marks those drafts "suggested". No agent reaches any of this (like invoices.py)."""
import json
import time
from datetime import date, timedelta

from flask import g

from ..core.config import app
from ..core.db import iso, local_now, now_utc
from ..core.i18n import N_, lang, tr
from ..core.pg import system_ctx, write_lock

DUN_EVERY_TICKS = 10          # like the invoice series: whole days matter, not seconds
_DUN_LAST = {"at": 0.0}
DUN_MAX_LEVEL = 3
DUN_MAX_IDS = 50              # inv_make_reminder takes at most 50 invoices
DUN_TASK = N_("Payment reminders suggested: {0}")


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def dun_tick(c, now=None):
    """Every office area with an overdue open invoice: the suggestions of dun_area (see the module text)."""
    from ..core.config import WATCHDOG_INTERVAL
    if time.monotonic() - _DUN_LAST["at"] < DUN_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _DUN_LAST["at"] = time.monotonic()
    today = (now or local_now()).date().isoformat()
    with system_ctx(c):  # which office areas have an overdue open invoice at all; each is then handled in its admin's own context
        oids = [r[0] for r in c.execute("SELECT DISTINCT org_id FROM office_docs WHERE kind='invoice' AND locked_at IS NOT NULL AND status IN ('issued','sent') "
                                        "AND trial=0 AND COALESCE(due_date, '')<>'' AND due_date<? ORDER BY org_id LIMIT 2000", (today,)).fetchall()]
    c.commit()
    for oid in oids:
        try:
            dun_area(c, oid, today)
        except Exception as e:  # noqa: BLE001 -- one broken area never stops the others
            c.rollback()
            print("dunning suggestion", oid, "failed:", e, flush=True)


def dun_area(c, oid, today):
    """The suggestions of office area oid on day today (ISO); returns the ids of the reminder drafts made."""
    from .fixedimport import fci_people
    with system_ctx(c):  # who acts for this area (its admins / the owner), read before entering their context
        people = [p["id"] for p in fci_people(c, oid)]
    c.commit()
    if not people:
        return []
    prev = c.ctx
    try:
        return _dun_as(c, oid, today, people)
    finally:
        c.rollback()  # whatever is left open; then the watchdog's own context again (the hook followed g.user)
        c.set_ctx(*prev)


def _dun_as(c, oid, today, people):
    from .model import office_on, office_role, office_settings
    actor = people[0]
    with app.test_request_context("/api/office/docs/reminder"):
        g.user = c.execute("SELECT * FROM users WHERE id=?", (actor,)).fetchone()  # the area's admin: the log, the draft's creator
        if g.user is None or office_role(c, actor, oid) != "admin" or not office_on(c, actor):
            return []
        s = office_settings(c, oid)
        if not int(s.get("dunning_suggest", 1) or 0):
            return []
        write_lock(c, f"office_dunning_{int(oid)}")  # two app processes never suggest the same reminder twice
        groups = dun_due(c, oid, today, int(s.get("dunning_grace_days", 7) or 0))
        made = []
        for (_who, _cur, level), ids in sorted(groups.items(), key=lambda x: (x[0][2], x[1][0])):
            did = dun_make(c, oid, actor, ids[:DUN_MAX_IDS], level)
            if did:
                made.append(did)
        if made:
            from .recurring import rin_task
            for p in people:
                lg = lang(c, p)
                rin_task(c, p, tr(DUN_TASK, len(made), lg=lg),
                         tr("Overdue invoices: {0} reminder drafts are ready. Check them and send them like any reminder - nothing was sent.", len(made), lg=lg),
                         made[0])
            from ..core.db import bump
            bump(c)
        c.commit()
        return made


def dun_due(c, oid, today, grace):
    """{(client key, currency, level): [invoice ids]} of area oid that get a suggestion today (see the module text)."""
    from .invoices import inv_money_fields, inv_paid_map, inv_state
    # 2.144.10 B (#2576): the automatic dunning run never picks trial invoices
    invs = c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind='invoice' AND locked_at IS NOT NULL AND status IN ('issued','sent') "
                     "AND trial=0 AND COALESCE(due_date, '')<>'' AND due_date<? ORDER BY due_date, id LIMIT 2000", (oid, today)).fetchall()
    if not invs:
        return {}
    pm = inv_paid_map(c, oid, [r["id"] for r in invs])
    # the reminders naming each invoice: drafts block, the highest finalised level and its deadline count
    rems = {}
    for x in c.execute("SELECT id, ref_doc_ids, reminder_level, reminder_deadline_days, date, locked_at FROM office_docs WHERE org_id=? AND kind='reminder'", (oid,)):
        for i in _j(x["ref_doc_ids"] or "[]", []):
            if str(i).isdigit():
                rems.setdefault(int(i), []).append(x)
    marks = {(r[0], r[1]) for r in c.execute("SELECT doc_id, level FROM office_dunning_marks WHERE org_id=?", (oid,))}
    t0 = date.fromisoformat(today)
    out = {}
    for r in invs:
        if inv_state(r, pm, today) in ("paid", "cancelled") or float(inv_money_fields(r, pm)["open"]) <= 0:
            continue
        mine = rems.get(r["id"], [])
        if any(not x["locked_at"] for x in mine):
            continue  # a draft waits for a person
        done = [x for x in mine if x["locked_at"]]
        last = max(done, key=lambda x: (int(x["reminder_level"] or 1), x["date"] or "", x["id"])) if done else None
        level = (int(last["reminder_level"] or 1) + 1) if last else 1
        if level > DUN_MAX_LEVEL or (r["id"], level) in marks:
            continue
        try:
            since = date.fromisoformat(r["due_date"]) if last is None else \
                date.fromisoformat(last["date"]) + timedelta(days=int(last["reminder_deadline_days"] or 0))
        except (TypeError, ValueError):
            continue
        if since + timedelta(days=grace) >= t0:
            continue
        who = r["client_id"] if r["client_id"] else (_j(r["recipient"], {}).get("name") or "").strip().lower()
        out.setdefault((str(who), r["currency"], level), []).append(r["id"])
    return out


def dun_make(c, oid, uid, ids, level):
    """One reminder draft over invoices ids on level (the office's fee and deadline), the marks; None when the invoices
    no longer fit one reminder (checked again by inv_make_reminder)."""
    from .docs import recalc
    from .invoices import inv_make_reminder
    from .ledger import ofx_log
    from ..core.access import Denied
    from ..personal.timetrack import BadInput
    try:
        with c.savepoint():
            did = inv_make_reminder(c, oid, uid, {"doc_ids": ids, "level": level})
    except (BadInput, Denied):
        return None
    recalc(c, oid, did)
    ofx_log(c, oid, "create", doc_id=did, detail={"kind": "reminder", "doc_ids": ids, "level": level, "auto": 1})
    ts = iso(now_utc())
    for i in ids:
        c.execute("INSERT INTO office_dunning_marks(org_id, doc_id, level, reminder_id, created_at) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(doc_id, level) DO NOTHING", (oid, i, level, did, ts))
    return did


def dun_list_extra(c, oid, kind, rows):
    """For GET /api/office/docs: marks suggested reminder drafts (suggested 1) and returns {suggested: N, first: id} --
    the reminder drafts of area oid the watchdog made that are still drafts."""
    if kind not in ("invoice", "reminder"):
        return None
    ids = [r[0] for r in c.execute("SELECT DISTINCT d.id FROM office_dunning_marks m JOIN office_docs d ON d.id=m.reminder_id AND d.org_id=m.org_id "
                                   "WHERE m.org_id=? AND d.kind='reminder' AND d.locked_at IS NULL ORDER BY d.id", (oid,))]
    sug = set(ids)
    for d in rows:
        if d.get("kind") == "reminder" and d.get("id") in sug:
            d["suggested"] = 1
    return {"suggested": len(ids), "first": ids[0] if ids else None}
