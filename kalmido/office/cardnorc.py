"""2.444.0 (#3447): credit card positions without a receipt -- the reminder task of the holder and the rows of the exports.

The reminder (setting "card_norc", set only by its own route here, the general settings route ignores it): {every: off|week|
month, user: uid, tasks: {uid: {task, next}}}. While on, the watchdog keeps ONE open task in the inbox of every holder with an
account as long as positions of their cards are open (a card with a free name: the person chosen in user, an admin of the
office); done by itself once they have all their receipts, a new one at the next date. No push of its own: a normal task, due
today. Exports: office/bkexport.py rows "card" (cc_bk_rows), office/datevin.py (cc_dv_rows, cc_dv_nodes): the card is an account
of its own, a receipt matched with a position is booked against it, fees against the expense account, private ones against the
private account, the bank booking of the total takes the card account back to zero."""
import time

from flask import jsonify

from ..core.access import my_inbox
from ..core.config import PUBLIC_URL, WATCHDOG_INTERVAL, app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, lang, tr, trn
from ..core.orgcrypt import oc_dec_fields
from ..core.pg import insert_id, system_ctx
from ..tasks.validation import log_act
from .banknorc import BNR_EVERY, _alive, _next
from .calc import dec, money
from .fixedimport import fci_people, fci_task_end
from .ledger import ofx_log
from .model import office_ctx_admin, office_role, office_settings, office_settings_lock, office_settings_save
from ..files.store import fs_role  # 2.369.5 (#2517): pulled up from functions
from .books import _uid_filter  # 2.369.5 (#2517): pulled up from functions
from .datev import _acct  # 2.369.5 (#2517): pulled up from functions
from .datevin import DV_CC_OPEN, DV_CC_OPEN_1, _line, dv_card_account, dv_card_private, dv_cat_account  # 2.369.5 (#2517): pulled up from functions
from .homecur import hc_home  # 2.369.5 (#2517): pulled up from functions

CCN_EVERY_TICKS = 10
_CCN_LAST = {"at": 0.0}
CCN_TASK_TEXT = N_("Upload the receipts of these card positions or mark them as not needing a receipt. The task is done by itself once every position has its receipt.")
CCN_TASK_HELP = N_("Open the credit cards")


def ccn_clean(s):
    v = s.get("card_norc") if isinstance(s.get("card_norc"), dict) else {}
    every = v.get("every") if v.get("every") in BNR_EVERY else "off"
    user = v.get("user") if isinstance(v.get("user"), int) and not isinstance(v.get("user"), bool) else None
    t = v.get("tasks") if isinstance(v.get("tasks"), dict) else {}
    return {"every": every, "user": user, "tasks": {k: x for k, x in t.items() if isinstance(x, dict) and str(k).isdigit()}}


def ccn_counts(c, oid, fallback):
    """{person: open positions} of confirmed statements of cards in the list; a card with a free name counts for fallback."""
    out = {}
    for r in c.execute("SELECT k.holder_id, COUNT(*) AS n FROM office_cc_lines l JOIN office_cc_statements s ON s.id=l.statement_id "
                       "JOIN office_cc_cards k ON k.id=s.card_id WHERE l.org_id=? AND l.state='open' AND s.state='confirmed' "
                       "AND s.deleted_at IS NULL AND k.deleted_at IS NULL GROUP BY k.holder_id", (oid,)).fetchall():
        who = r["holder_id"] or fallback
        if who:
            out[who] = out.get(who, 0) + r["n"]
    return out


def _title(n, lg):
    return trn("{0} card position without a receipt", "{0} card positions without a receipt", n, lg=lg)


def _task_new(c, person, n, today):
    lg = lang(c, person)
    url = PUBLIC_URL.rstrip("/") + "/#office/cards"
    lid = my_inbox(c, person)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,due,sort,created_at,updated_at,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (lid, _title(n, lg), f"{tr(CCN_TASK_TEXT, lg=lg)}\n\n[{tr(CCN_TASK_HELP, lg=lg)}]({url})", today, srt, ts, ts, person, url, person))
    log_act(c, tid, "created", uid=person)
    return tid


def ccn_apply(c, oid, s, today=None):
    """The reminder of area oid with settings s (the caller holds the settings lock and saves s when True returns)."""
    cfg = ccn_clean(s)
    if cfg["every"] == "off":
        return False
    today = today or local_now().date().isoformat()
    fall = cfg["user"] if cfg["user"] in {p["id"] for p in fci_people(c, oid)} else None
    counts = ccn_counts(c, oid, fall)
    changed = False
    for key in sorted(set(cfg["tasks"]) | {str(p) for p in counts}):
        person = int(key)
        st = cfg["tasks"].get(key) or {}
        n = counts.get(person, 0) if office_role(c, person, oid) else 0
        task = st.get("task") if isinstance(st.get("task"), int) else None
        if _alive(c, task, person):
            if n == 0:
                fci_task_end(c, task, person)
                st["task"], changed = None, True
            else:
                t = _title(n, lang(c, person))
                changed = c.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=? AND title<>?", (t, iso(now_utc()), task, t)).rowcount > 0 or changed
        elif n and (not st.get("next") or st["next"] <= today):
            st = {"task": _task_new(c, person, n, today), "next": _next(today, cfg["every"])}
            changed = True
        elif task:
            st["task"], changed = None, True  # done / deleted by the person: the next one at the next date
        cfg["tasks"][key] = st
    if changed:
        s["card_norc"] = cfg
    return changed


def ccn_area(c, oid, today=None):
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    if ccn_apply(c, oid, s, today):
        office_settings_save(c, oid, s)
        bump(c)
    c.commit()


def ccn_tick(c, now=None, force=False):
    """Watchdog: every office area with the reminder on. At most every CCN_EVERY_TICKS intervals."""
    if not force and time.monotonic() - _CCN_LAST["at"] < CCN_EVERY_TICKS * WATCHDOG_INTERVAL:
        return
    _CCN_LAST["at"] = time.monotonic()
    today = (now or local_now()).date().isoformat()
    with system_ctx(c):  # which areas have the reminder at all; each is then read under its own lock
        oids = [r[0] for r in c.execute("SELECT org_id FROM office_settings WHERE data LIKE ? OR data LIKE ? ORDER BY org_id",  # pg-ok: exact JSON text, case-sensitive on purpose
                                        ('%"card_norc": {"every": "week"%', '%"card_norc": {"every": "month"%')).fetchall()]
    c.commit()
    for oid in oids:
        try:
            with system_ctx(c):
                ccn_area(c, oid, today)
        except Exception as e:  # noqa: BLE001 -- one broken area never stops the others
            c.rollback()
            print("card positions reminder", oid, "failed:", e, flush=True)


def _public(c, oid, s):
    cfg = ccn_clean(s)
    people = fci_people(c, oid)
    return {"every": cfg["every"], "user": cfg["user"], "people": people, "count": sum(ccn_counts(c, oid, cfg["user"] or -1).values())}


@app.get("/api/office/cards/reminder")
def ccn_get():
    """{every: off|week|month, user (gets the positions of cards with a free name), people (who may), count}."""
    c, _uid, oid = office_ctx_admin()
    return jsonify(_public(c, oid, office_settings(c, oid)))


@app.put("/api/office/cards/reminder")
def ccn_put():
    """{every?, user?} (partial). Off: the open tasks are done (never deleted). Switched on: the first tasks at once."""
    c, uid, oid = office_ctx_admin()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    cfg = ccn_clean(s)
    old = cfg["every"]
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
    if cfg["every"] == "off":
        for k, st in cfg["tasks"].items():
            fci_task_end(c, st.get("task"), int(k))
        cfg["tasks"] = {}
    elif cfg["every"] != old:
        for st in cfg["tasks"].values():
            st["next"] = ""  # (again) on / another rhythm: the first reminder now
    s["card_norc"] = cfg
    ccn_apply(c, oid, s)
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"card_norc": {"every": s["card_norc"]["every"], "user": s["card_norc"]["user"]}})
    bump(c)
    c.commit()
    return jsonify(_public(c, oid, s))


# ---------------------------------------------------------------- the exports
def _lines(c, oid, frm, to):
    """The positions of confirmed statements in [frm, to]: (decrypted row with its statement and card columns)."""
    out = []
    for r in c.execute("SELECT l.*, s.month AS s_month, s.node_id AS s_node, k.last4 AS k_last4, k.holder_id AS k_holder, k.holder_name AS k_name "
                       "FROM office_cc_lines l JOIN office_cc_statements s ON s.id=l.statement_id JOIN office_cc_cards k ON k.id=s.card_id "
                       "WHERE l.org_id=? AND s.state='confirmed' AND s.deleted_at IS NULL AND l.day>=? AND l.day<=? ORDER BY l.day, l.id", (oid, frm, to)).fetchall():
        x = oc_dec_fields(c, oid, "office_cc_lines", r)
        x["last4"] = oc_dec_fields(c, oid, "office_cc_cards", {"last4": r["k_last4"]})["last4"]
        x["amount"] = money(dec(x["amount"], "0"))
        out.append(x)
    return out


def _settled(c, oid, frm, to):
    """The statements whose bank booking lies in [frm, to]: [(statement id, day of the booking, total, node_id, month)]."""
    out = []
    for r in c.execute("SELECT s.id, s.total, s.node_id, s.month, b.day FROM office_bank_tx b JOIN office_cc_statements s ON s.id=b.match_id AND s.org_id=b.org_id "
                       "WHERE b.org_id=? AND b.match_kind='card' AND b.deleted_at IS NULL AND s.deleted_at IS NULL AND b.day>=? AND b.day<=? ORDER BY b.day, s.id", (oid, frm, to)).fetchall():
        d = oc_dec_fields(c, oid, "office_cc_statements", {"total": r["total"]})
        out.append((r["id"], r["day"], money(dec(d["total"], "0")), r["node_id"], r["month"]))
    return out


def cc_norc_lines(c, oid, frm, to):
    """2.536.0 (#4334): the positions without a receipt (fees, interest, marked "no receipt needed") of confirmed statements in
    [frm, to] as the EUeR and the cash flow count them, like cc_dv_rows books them: [{day, amount (plus = money out), merchant,
    statement_id, s_node, s_month, last4}]. Private positions are no business expense, matched ones count through their receipt
    (books.bk_receipts), open ones still wait; the bank booking of the total (_settled) only moves money from the bank to the
    card account and is no expense of its own."""
    return [x for x in _lines(c, oid, frm, to) if x["state"] == "noreceipt" and x["amount"]]


def cc_bk_rows(c, oid, frm, to, uid=None, meals=()):
    """The rows of the neutral export (bkexport.py type card): one per position (minus = money out), one without an amount per
    statement of the period with its PDF. _node = the file behind a row (only files the person sees).
    2.610.0 (#4932 review M1): meals = ids of open positions an entertainment receipt counts through (a strict year,
    books.bk_meals_strict): the meal's rows carry the amount, the position only the link (as a matched one)."""
    uid = _uid_filter(uid)
    rows, seen = [], set()

    def see(nid):
        return nid if nid and (not uid or fs_role(c, nid, uid)) else None
    labels = {"private": tr("Private"), "noreceipt": tr("No receipt needed"), "open": tr("Receipt missing")}
    home = None
    for x in _lines(c, oid, frm, to):
        if home is None:
            home = hc_home(office_settings(c, oid))
        # a position with its receipt: the receipt's own row carries the amount, this one only the link (the rows of a type add up)
        meal = x["state"] == "open" and x["id"] in meals
        rows.append({"type": "card", "date": x["day"], "number": f"{x['s_month']} ·· {x['last4']}", "counterparty": x["merchant"] or "",
                     "text": tr("Entertainment receipt") if meal else labels.get(x["state"], ""),
                     "category": "", "tax_pct": "", "net": "", "tax": "", "gross": "" if x["state"] == "matched" or meal else -x["amount"], "currency": home, "file": "", "_node": see(x["node_id"])})
        if x["statement_id"] not in seen:
            seen.add(x["statement_id"])
            rows.append({"type": "card", "date": f"{x['s_month']}-01", "number": f"{x['s_month']} ·· {x['last4']}", "counterparty": "", "text": tr("Credit card statement"),
                         "category": "", "tax_pct": "", "net": "", "tax": "", "gross": "", "currency": home, "file": "", "_node": see(x["s_node"])})
    return rows


def cc_dv_nodes(c, oid):
    """{node id}: the receipts matched with a position (booked against the card account, not the creditor)."""
    return {r[0] for r in c.execute("SELECT node_id FROM office_cc_lines WHERE org_id=? AND state='matched' AND node_id IS NOT NULL", (oid,))}


def cc_dv_rows(c, oid, d_from, d_to, st, _s):
    """(rows, hints) of DATEV's input side: fees and positions without a receipt on the expense account, private ones on the
    private account, each against the card account; the bank booking of a total card account against bank. Positions still
    waiting for their receipt are not booked, a hint names them."""
    card, rows, wait = dv_card_account(st), [], 0
    for x in _lines(c, oid, d_from, d_to):
        if x["state"] == "open":
            wait += 1
        elif x["state"] in ("noreceipt", "private") and x["amount"]:
            konto = dv_cat_account(st, "bank") if x["state"] == "noreceipt" else dv_card_private(st)
            rows.append(_line(x["amount"], konto, card, "", x["day"], f"K{x['id']}", x["merchant"], node=x["s_node"]))
    for sid, day, total, node, month in _settled(c, oid, d_from, d_to):
        rows.append(_line(total, card, st["bank"] or _acct(st, "bank"), "", day, f"KA{sid}", f"{tr('Credit card statement')} {month}", node=node))
    hints = [{"key": "card_open", "count": wait, "text": tr(DV_CC_OPEN_1) if wait == 1 else tr(DV_CC_OPEN, wait)}] if wait else []
    return rows, hints


