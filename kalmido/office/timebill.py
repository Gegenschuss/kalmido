"""2.144.6 A (#2053): time entries to an invoice -- billable / billed, never twice.

time_entries.billable (default 1) says an entry may go onto an invoice; "invoice from time" (office/invoices.py
inv_from_time) takes only the billable, still open entries of the period and binds them to the new draft
(billed_doc_id, billed_at) in the same transaction. A billed entry keeps its duration, date, task and billable switch
(timetrack.py asks tbill_need_open); its note stays editable. Deleting the draft frees the entries again (odoc_delete calls
tbill_free; a document that vanished otherwise, e.g. deleted by an older version, frees them too: tbill_doc finds nothing).
A finalised invoice keeps them, also once cancelled by a credit note; on a cancelled invoice the office admin frees them
explicitly (POST /api/office/docs/<id>/time-release, undoable with {"undo": ids}).
"""
from datetime import date, timedelta

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, iso, now_utc
from ..core.access import Denied
from ..core.pg import system_ctx
from ..personal.timetrack import BadInput
from .model import office_role, pb_cl_sql

TBL_LOCKED = N_("This time is on invoice {0}: duration, date, task and billable can no longer be changed")
TBL_LOCKED_DEL = N_("This time is on invoice {0} and cannot be deleted")
TBL_LOCKED_ANON = N_("This time is already billed: duration, date, task and billable can no longer be changed")
TBL_LOCKED_DEL_ANON = N_("This time is already billed and cannot be deleted")
TBL_LOG_IDS = 5000  # 2.144.6 A (#2053 review 2): released ids kept in the office log for the undo (fits OFX_DETAIL_MAX)


def tbill_doc(c, did):
    """The document an entry was billed on, if it still exists: {id, org_id, number, kind, status} or None."""
    if not did:
        return None
    # system_ctx: only whether the billing document still exists and its number (to explain the lock to the person who
    # tracked the time, e.g. a guest of a private list), never its content
    with system_ctx(c):
        r = c.execute("SELECT id, org_id, number, kind, status FROM office_docs WHERE id=?", (did,)).fetchone()
    return dict(r) if r else None


def tbill_need_open(c, r, b):
    """409 when entry r is billed and b changes more than the note (PATCH); a vanished document frees the entry first."""
    if not ("billed_doc_id" in r.keys() and r["billed_doc_id"]):
        return
    if b is not None:
        same = {"billable": lambda v: v in (None, "") or tbill_billable(v) == r["billable"],
                "task_id": lambda v: v == r["task_id"], "list_id": lambda v: v == r["list_id"]}
        if all(k not in b or (k in same and same[k](b[k])) for k in ("start", "end", "minutes", "seconds", "task_id", "list_id", "billable")):
            return  # only the note (or unchanged values of a form that sends everything)
    d = tbill_doc(c, r["billed_doc_id"])
    if d is None:
        c.execute("UPDATE time_entries SET billed_doc_id=NULL, billed_at=NULL WHERE id=?", (r["id"],))
        return
    tbill_locked(c, d, b is None)


def tbill_shows(c, d, uid):
    """2.144.6 A (#2053 review 3): whether uid may see the number / id of billing document d -- only with a role in its
    office (in a personal office: its owner); a guest or former member learns "billed", not another area's numbering."""
    if not d or uid is None or not d.get("org_id"):
        return False
    from flask import g, has_request_context
    if c is None:
        from ..core.db import db
        c = db()
    cache = g.setdefault("tbill_roles", {}) if has_request_context() else {}
    k = (uid, d["org_id"])
    if k not in cache:
        cache[k] = office_role(c, uid, d["org_id"]) is not None
    return cache[k]


def tbill_locked(c, d, delete):
    """409 for an entry billed on document d (None = number unknown); the number only for someone with a role there."""
    from flask import g
    u = getattr(g, "user", None)
    if tbill_shows(c, d, u["id"] if u is not None else None):
        raise Denied(409, tr(TBL_LOCKED_DEL if delete else TBL_LOCKED, d["number"] or tr("Draft")))
    raise Denied(409, tr(TBL_LOCKED_DEL_ANON if delete else TBL_LOCKED_ANON))


def tbill_guard(r, b):
    """2.144.6 A (#2053 review 1): whether the UPDATE / DELETE of entry r must carry "AND billed_doc_id IS NULL" -- always,
    except for the note-only PATCH of a billed entry (tbill_need_open let it through). Without the condition a draft made
    between tbill_need_open and the write would keep hours whose entry was then changed or deleted."""
    return not ("billed_doc_id" in r.keys() and r["billed_doc_id"]) or b is None


def tbill_lost(c, eid, delete):
    """The guarded write changed no row: entry eid was billed meanwhile (409 like tbill_need_open) or is gone (404)."""
    r = c.execute("SELECT billed_doc_id FROM time_entries WHERE id=?", (eid,)).fetchone()
    if r is None:
        raise Denied(404)
    tbill_locked(c, tbill_doc(c, r["billed_doc_id"]), delete)


def tbill_billable(v):
    if v in (True, 1, "1", "true"):
        return 1
    if v in (False, 0, "0", "false"):
        return 0
    raise BadInput(tr("Invalid value: {0}", "billable"))


def tbill_out(r, uid=None):
    """The billing fields of an entry row: billable, billed {id, number, at} (None = open). The number comes from tbill_doc
    (cached per request); a document that no longer exists shows the entry open. Only the person who tracked the time
    (uid) sees the document's id and number, and only with a role in the document's office (tbill_shows); others
    (colleagues, guests, former members, agents) see "billed" without them."""
    from flask import g, has_request_context
    from ..core.db import db
    k = r.keys()
    bid = r["billed_doc_id"] if "billed_doc_id" in k else None
    d = None
    if bid:
        if not has_request_context():  # no lookup outside a request: billed, number unknown
            d = {"number": "", "org_id": None}
        else:
            cache = g.setdefault("tbill_docs", {})
            if bid not in cache:
                cache[bid] = tbill_doc(db(), bid)
            d = cache[bid]
    own = uid is not None and "user_id" in k and r["user_id"] == uid and tbill_shows(None, d, uid)
    return {"billable": bool(r["billable"]) if "billable" in k else True,
            "billed": ({"id": bid, "number": d["number"] or "", "at": r["billed_at"]} if own
                       else {"id": None, "number": "", "at": r["billed_at"]}) if d else None}


def tbill_where(c, oid, uid, cid, d_from, d_to, pid):
    """The FROM / WHERE part over the finished time entries of client cid's lists in [d_from, d_to] that uid sees (the lists
    of the office area (org id): an organisation's lists, in a personal office the owner's private lists) -> (sql, args)."""
    from ..core.access import vis_sql
    # 2.144.6 A (#2053): a personal office (no organisation) bills the owner's private lists (before: l.org_id = the hidden
    # office id, which no list carries)
    sql = ("FROM time_entries e JOIN lists l ON l.id=e.list_id "
           f"WHERE l.client_id=? AND {pb_cl_sql(c, oid, 'l.org_id', 'l.owner_id')} AND l.id IN {vis_sql()} AND e.\"end\" IS NOT NULL "
           "AND e.start>=? AND e.start<?")
    args = [cid, uid, uid, d_from + "T00:00:00", (date.fromisoformat(d_to) + timedelta(days=1)).isoformat() + "T00:00:00"]
    if pid not in (None, "", 0):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "project_id"))
        sql += " AND e.list_id=?"
        args.append(pid)
    return sql, args


def tbill_free_stale(c, sql, args):
    """Entries of the period bound to a document that no longer exists (deleted by a version without tbill_free) are open."""
    ids = [r[0] for r in c.execute(f"SELECT e.id {sql} AND e.billed_doc_id IS NOT NULL", args)]
    if not ids:
        return
    with system_ctx(c):  # existence only, across the RLS of office_docs (the billing document may lie in another area)
        c.execute(f"UPDATE time_entries SET billed_doc_id=NULL, billed_at=NULL WHERE id IN ({','.join('?' * len(ids))}) "
                  "AND NOT EXISTS (SELECT 1 FROM office_docs d WHERE d.id=time_entries.billed_doc_id)", ids)


def tbill_summary(c, sql, args):
    """Seconds / entries of the period: open (billable, not billed), billed, not billable."""
    r = c.execute(f"""SELECT COALESCE(SUM(CASE WHEN e.billable=1 AND e.billed_doc_id IS NULL THEN e.seconds END),0) AS open_s,
                             COUNT(CASE WHEN e.billable=1 AND e.billed_doc_id IS NULL THEN 1 END) AS open_n,
                             COALESCE(SUM(CASE WHEN e.billed_doc_id IS NOT NULL THEN e.seconds END),0) AS billed_s,
                             COUNT(CASE WHEN e.billed_doc_id IS NOT NULL THEN 1 END) AS billed_n,
                             COALESCE(SUM(CASE WHEN e.billable=0 AND e.billed_doc_id IS NULL THEN e.seconds END),0) AS nob_s,
                             COUNT(CASE WHEN e.billable=0 AND e.billed_doc_id IS NULL THEN 1 END) AS nob_n {sql}""", args).fetchone()
    return {"open_seconds": int(r["open_s"]), "open_entries": int(r["open_n"]), "billed_seconds": int(r["billed_s"]),
            "billed_entries": int(r["billed_n"]), "unbillable_seconds": int(r["nob_s"]), "unbillable_entries": int(r["nob_n"])}


def tbill_take(c, did, sql, args):
    """Binds the open billable entries of the period to draft did -> (groups [{list_id, lname, secs}], summary before).
    The UPDATE re-checks billed_doc_id IS NULL row by row: of two parallel calls the second waits for the first and then
    takes only what is still open, so the same seconds never land on two invoices."""
    tbill_free_stale(c, sql, args)
    before = tbill_summary(c, sql, args)
    ts = iso(now_utc())
    c.execute(f"UPDATE time_entries SET billed_doc_id=?, billed_at=?, updated_at=? WHERE billed_doc_id IS NULL AND billable=1 "
              f"AND id IN (SELECT e.id {sql})", [did, ts, ts] + args)
    groups = c.execute("SELECT e.list_id, l.name AS lname, SUM(e.seconds) AS secs FROM time_entries e JOIN lists l ON l.id=e.list_id "
                       "WHERE e.billed_doc_id=? GROUP BY e.list_id, l.name ORDER BY l.name", (did,)).fetchall()
    taken = c.execute("SELECT COUNT(*), COALESCE(SUM(seconds),0) FROM time_entries WHERE billed_doc_id=?", (did,)).fetchone()
    return groups, {"taken_entries": int(taken[0]), "taken_seconds": int(taken[1]),
                    "skipped_billed": before["billed_entries"] + before["open_entries"] - int(taken[0]),
                    "skipped_unbillable": before["unbillable_entries"]}


def tbill_free(c, did):
    """The draft did goes away: its entries are open again."""
    c.execute("UPDATE time_entries SET billed_doc_id=NULL, billed_at=NULL, updated_at=? WHERE billed_doc_id=?", (iso(now_utc()), did))


def tbill_doc_time(c, did):
    """{entries, seconds} the document billed (the invoice view shows it, the release button needs it)."""
    r = c.execute("SELECT COUNT(*), COALESCE(SUM(seconds),0) FROM time_entries WHERE billed_doc_id=?", (did,)).fetchone()
    return {"entries": int(r[0]), "seconds": int(r[1])}


def tbill_client_id(c, oid, v):
    try:
        cid = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "client_id"))
    if c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone() is None:
        raise Denied(404)
    return cid


@app.get("/api/office/time-open")
def tbill_open_get():
    """?client_id=&from=&to=&project_id= -> the hours of the period: open billable, already billed, not billable (the
    dialog "Invoice from time" shows them before the draft is made)."""
    from flask import request
    from .docs import _ctx, _date
    c, uid, oid = _ctx()
    a = request.args
    cid = tbill_client_id(c, oid, a.get("client_id"))
    d_from, d_to = _date(a.get("from"), "from"), _date(a.get("to"), "to")
    if not d_from or not d_to or d_to < d_from:
        raise BadInput(tr("Invalid value: {0}", "from/to"))
    sql, args = tbill_where(c, oid, uid, cid, d_from, d_to, a.get("project_id"))
    return jsonify(tbill_summary(c, sql, args))


def tbill_released_ids(c, oid, did):
    """2.144.6 A (#2053 review 2): the ids the last release of document did freed (office log), empty without a release,
    None when the log kept only the count (more than TBL_LOG_IDS entries): then the undo's other conditions alone apply."""
    from .ledger import _log_public
    r = c.execute("SELECT * FROM office_doc_log WHERE org_id=? AND doc_id=? AND action='time_release' ORDER BY id DESC LIMIT 1",
                  (oid, did)).fetchone()
    if r is None:
        return set()
    ids = _log_public(c, r)["detail"].get("ids")
    return set(ids) if isinstance(ids, list) else None


@app.post("/api/office/docs/<int:did>/time-release")
def tbill_release_post(did):
    """The office admin frees the time entries of a cancelled invoice (they can be billed again) -> {released: [ids]}.
    {"undo": [ids]} binds those entries again (the undo step), as long as nobody billed them meanwhile."""
    from .docs import _ctx, doc_row
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    if r["kind"] != "invoice" or r["status"] != "cancelled":
        raise Denied(409, tr("Only the time of a cancelled invoice can be released"))
    b = body()
    from .ledger import ofx_log
    if isinstance(b, dict) and b.get("undo") is not None:
        ids = b["undo"]
        if not isinstance(ids, list) or not all(isinstance(x, int) for x in ids) or len(ids) > 20000:
            raise BadInput(tr("Invalid value: {0}", "undo"))
        freed = tbill_released_ids(c, oid, did)
        if freed is not None:  # 2.144.6 A (#2053 review 2): only what this invoice's last release really freed
            ids = [x for x in ids if x in freed]
        if ids:
            # only open, billable, finished entries of the invoice's client's lists in this office
            ts = iso(now_utc())
            c.execute(f"UPDATE time_entries SET billed_doc_id=?, billed_at=?, updated_at=? WHERE billed_doc_id IS NULL "
                      f"AND billable=1 AND \"end\" IS NOT NULL "
                      f"AND id IN ({','.join('?' * len(ids))}) AND list_id IN (SELECT l.id FROM lists l WHERE l.client_id=? "
                      f"AND {pb_cl_sql(c, oid, 'l.org_id', 'l.owner_id')})", [did, ts, ts] + ids + [r["client_id"]])
        ofx_log(c, oid, "time_rebind", doc_id=did, detail={"entries": len(ids)})
        bump(c)
        c.commit()
        return jsonify(released=[], time_billed=tbill_doc_time(c, did))
    ids = [x[0] for x in c.execute("SELECT id FROM time_entries WHERE billed_doc_id=? ORDER BY id", (did,))]
    tbill_free(c, did)
    # 2.144.6 A (#2053 review 2): the freed ids, the undo checks against them (a huge release keeps only the count)
    ofx_log(c, oid, "time_release", doc_id=did, detail={"entries": len(ids), **({"ids": ids} if len(ids) <= TBL_LOG_IDS else {})})
    bump(c)
    c.commit()
    return jsonify(released=ids, time_billed=tbill_doc_time(c, did))

