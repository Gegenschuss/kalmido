"""2.43.0 (#1434): "Delete all times of this project" (preview, delete, restore for Undo).
Owner and list admins delete every entry of the list, other members only their own. Entries an invoice already bills stay
(an invoice made from the time of a client's project covers the entry's day and carries the project's name). Running timers stay.
Agent accounts: 403. Restore is the Undo step: the client sends back what the delete returned; the same rights apply."""
from datetime import datetime

from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, list_role, need_list, need_time
from ..accounts.session import me
from ..core.pg import insert_id

TZ_MAX_RESTORE = 20000


def tz_no_agent():
    u = getattr(g, "user", None)
    if u is not None and (u["kind"] if "kind" in u.keys() else "user") == "agent":
        raise Denied(403, tr("Not available for agent accounts"))


def tz_billed_sql(a="e."):
    """SQL fragment: the entry is covered by an invoice (not cancelled) of the list's client that carries the list's name."""
    return (f"EXISTS (SELECT 1 FROM office_docs d JOIN lists bl ON bl.id={a}list_id "
            f"WHERE d.kind='invoice' AND d.status<>'cancelled' AND bl.client_id IS NOT NULL AND d.client_id=bl.client_id "
            f"AND d.org_id=bl.org_id AND COALESCE(d.service_from, d.service_to) IS NOT NULL "
            f"AND substr({a}start,1,10)>=COALESCE(d.service_from, d.service_to) AND substr({a}start,1,10)<=COALESCE(d.service_to, d.service_from) "
            f"AND EXISTS (SELECT 1 FROM office_doc_items i WHERE i.doc_id=d.id AND lower(trim(i.title))=lower(trim(bl.name))))")  # review V2


def tz_scope(c, lid):
    """-> (role, admin): whoever may see the list; admins reach every entry."""
    role = need_list(c, lid, write=False)
    return role, role in ("owner", "admin")


def tz_preview(c, lid, uid, admin):
    own = "" if admin else " AND e.user_id=?"
    args = [lid] + ([] if admin else [uid])
    base = f"FROM time_entries e WHERE e.list_id=? AND e.\"end\" IS NOT NULL{own}"
    tot = c.execute(f"SELECT COUNT(*), COALESCE(SUM(e.seconds),0) {base}", args).fetchone()
    bil = c.execute(f"SELECT COUNT(*), COALESCE(SUM(e.seconds),0) {base} AND {tz_billed_sql()}", args).fetchone()
    return {"count": tot[0] - bil[0], "seconds": int(tot[1] - bil[1]), "billed": bil[0], "billed_seconds": int(bil[1]), "all": admin}


def n43_iso(v):
    """2.63.0 (#1523): a restored timestamp is kept only when it is a real ISO time."""
    if not isinstance(v, str) or not v:
        return None
    try:
        datetime.fromisoformat(v[:40])
    except ValueError:
        return None
    return v[:40]


def n43_restore_ids(c, owner, e):
    """2.63.0 (#1523): -> (client_id, pomo_id) for a restored entry. The timer's device id comes back unless that person already has
    an entry with it (unique time_client: then the entry comes back without it instead of failing). The focus link comes back only for
    the owner's own session that no other entry claims (keeps "imported once" without letting a forged id block someone's import)."""
    cid = e.get("client_id")
    cid = cid[:64] if isinstance(cid, str) and cid else None
    if cid and c.execute("SELECT 1 FROM time_entries WHERE user_id=? AND client_id=?", (owner, cid)).fetchone():
        cid = None
    pid = e.get("pomo_id")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 \
            or not c.execute("SELECT 1 FROM pomos WHERE id=? AND user_id=?", (pid, owner)).fetchone() \
            or c.execute("SELECT 1 FROM time_entries WHERE pomo_id=?", (pid,)).fetchone():
        pid = None
    return cid, pid


@app.get("/api/lists/<int:lid>/time/delete-all")
def tz_delete_all_preview(lid):
    need_time()
    tz_no_agent()
    c = db()
    _, admin = tz_scope(c, lid)
    return jsonify(tz_preview(c, lid, me(), admin))


@app.post("/api/lists/<int:lid>/time/delete-all")
def tz_delete_all(lid):
    need_time()
    tz_no_agent()
    c = db()
    uid = me()
    _, admin = tz_scope(c, lid)
    b = body()
    name = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if str(b.get("confirm") or "").strip() != name:
        raise Denied(400, tr("Type the project name to confirm"))
    own = "" if admin else " AND e.user_id=?"
    args = [lid] + ([] if admin else [uid])
    rows = c.execute(f"SELECT e.* FROM time_entries e WHERE e.list_id=? AND e.\"end\" IS NOT NULL{own} AND NOT {tz_billed_sql()} ORDER BY e.id", args).fetchall()
    ids = [r["id"] for r in rows]
    prev = tz_preview(c, lid, uid, admin)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"DELETE FROM time_entries WHERE id IN ({','.join('?' * len(part))})", part)
    if ids:
        bump(c)
    c.commit()
    # 2.63.0 (#1523): every column comes back, so Undo restores the timer's device id, the focus link and the flags as they were
    back = [{"user_id": r["user_id"], "task_id": r["task_id"], "list_id": lid, "task_title": r["task_title"], "start": r["start"],
             "end": r["end"], "seconds": r["seconds"], "note": r["note"], "source": r["source"], "client_id": r["client_id"],
             "pomo_id": r["pomo_id"], "reminded": r["reminded"], "auto_stopped": r["auto_stopped"],
             "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]
    return jsonify(ok=True, deleted=len(ids), seconds=prev["seconds"], billed=prev["billed"], entries=back)


@app.post("/api/lists/<int:lid>/time/restore")
def tz_restore(lid):
    need_time()
    tz_no_agent()
    c = db()
    uid = me()
    _, admin = tz_scope(c, lid)
    ents = body().get("entries")
    if not isinstance(ents, list) or len(ents) > TZ_MAX_RESTORE:
        raise Denied(400, tr("Invalid value: {0}", "entries"))
    ts, n = iso(now_utc()), 0
    for e in ents:
        if not isinstance(e, dict) or not e.get("start") or not e.get("end"):
            continue
        owner = e.get("user_id")
        if not isinstance(owner, int) or (owner != uid and not admin):
            continue
        if not c.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone() or not list_role(c, lid, owner):
            continue  # review V1: only people of this list get entries back
        try:  # review V1: real times, end after start, seconds at most the span
            t0, t1 = datetime.fromisoformat(str(e["start"])[:40]), datetime.fromisoformat(str(e["end"])[:40])
            span, secs = int((t1 - t0).total_seconds()), int(e.get("seconds") or 0)
        except (ValueError, TypeError):
            continue
        if span < 0:
            continue
        e["seconds"] = min(max(0, secs), span)
        tid = e.get("task_id")
        if tid and not c.execute("SELECT 1 FROM tasks WHERE id=? AND list_id=?", (tid, lid)).fetchone():
            tid = None
        cid, pid = n43_restore_ids(c, owner, e)
        insert_id(c, """INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,"end",seconds,note,source,client_id,pomo_id,
                                                 reminded,auto_stopped,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (owner, tid, lid, str(e.get("task_title") or "")[:500], str(e["start"])[:40], str(e["end"])[:40],
                   max(0, int(e.get("seconds") or 0)), str(e.get("note") or "")[:500],
                   e.get("source") if e.get("source") in ("timer", "manual", "focus") else "manual", cid, pid,
                   1 if e.get("reminded") in (1, True) else 0, 1 if e.get("auto_stopped") in (1, True) else 0,
                   n43_iso(e.get("created_at")) or ts, ts))
        n += 1
    if n:
        bump(c)
    c.commit()
    return jsonify(ok=True, restored=n)
