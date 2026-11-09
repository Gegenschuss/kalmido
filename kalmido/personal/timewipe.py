"""2.43.0 (#1434): "Delete all times of this project" (preview, delete, restore for Undo).
Owner and list admins delete every entry of the list, other members only their own. Entries an invoice already bills stay
(an invoice made from the time of a client's project covers the entry's day and carries the project's name). Running timers stay.
Agent accounts: 403. Restore is the Undo step: the client sends back what the delete returned; the same rights apply.
2.530.0 B (#4315): the deleted entries are kept on the server too (time_wipes, one row per delete): Undo names that row
(wipe), so it works after the tab was closed until the trash period ends; then the trash run (files/trashpurge.py) deletes
the row. The preview names the newest such row of the person (undo).
2.783.0 (#5368, stage 6 of the trash core): that copy is a copy of the core's trash (core/objparts.py: list_part_trash, kind
TZW_KIND, ref_id = the person whose way back it is, snap = {n, seconds}, held = the entries); the core's run (core/writes.py
obj_trash_tick) deletes it after the period. Rows of the old table time_wipes move there at every start (tzw_move)."""
import hashlib
import hmac
import json
from datetime import datetime

from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, list_role, need_list, need_time
from ..accounts.session import me
from ..core.pg import insert_id, system_ctx
from ..core.objparts import PART_TRASH, part_kind  # 2.783.0 (#5368)
from ..core import objhooks  # 2.783.0 (#5368): tzw_move at every start, the copies go with an account
from ..accounts.login import auth_key  # 2.369.5 (#2517): pulled up from functions

TZ_MAX_RESTORE = 20000
H6B_SIG_FIELDS = ("user_id", "task_id", "task_title", "start", "end", "seconds", "note", "source", "client_id", "pomo_id",
                  "reminded", "auto_stopped", "created_at")


def h6b_sig(c, lid, e):
    """2.86.0 (N10): a keyed seal over an entry the delete returned (list id + its values). Restore brings back another person's
    entry only with an intact seal, so an admin cannot create entries with free values for other members; own entries need none."""
    msg = json.dumps([int(lid)] + [e.get(k) for k in H6B_SIG_FIELDS], ensure_ascii=False, sort_keys=True, default=str)
    return hmac.new(auth_key(c), b"kalmido-timewipe-v1|" + msg.encode(), hashlib.sha256).hexdigest()[:40]


def tz_no_agent():
    u = getattr(g, "user", None)
    if u is not None and (u["kind"] if "kind" in u.keys() else "user") == "agent":
        raise Denied(403, tr("Not available for agent accounts"))


def tz_billed_sql(a="e."):
    """SQL fragment: the entry is covered by an invoice (not cancelled) of the list's client with a position of the list
    (2.144.5 C (#1523): its list_id; a position without one = older invoices, by the list's name as before).
    2.144.6 A (#2053): or an invoice took it (billed_doc_id)."""
    return (f"({a}billed_doc_id IS NOT NULL OR EXISTS (SELECT 1 FROM office_docs d JOIN lists bl ON bl.id={a}list_id "
            f"WHERE d.kind='invoice' AND d.status<>'cancelled' AND bl.client_id IS NOT NULL AND d.client_id=bl.client_id "
            # 2.144.5 C (#1523): a private list (org_id NULL) is billed from its owner's personal office (its client is a private one)
            # 2.144.5 A2 (#1523, review R9): only that office, never another organisation's invoice for the same client id
            f"AND (d.org_id=bl.org_id OR bl.org_id IS NULL AND d.org_id=(SELECT po.id FROM orgs po WHERE po.personal_of=bl.owner_id)) "
            f"AND COALESCE(d.service_from, d.service_to) IS NOT NULL "
            f"AND substr({a}start,1,10)>=COALESCE(d.service_from, d.service_to) AND substr({a}start,1,10)<=COALESCE(d.service_to, d.service_from) "
            f"AND EXISTS (SELECT 1 FROM office_doc_items i WHERE i.doc_id=d.id AND (i.list_id=bl.id "
            f"OR i.list_id IS NULL AND lower(trim(i.title))=lower(trim(bl.name))))))")  # review V2


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
    from .timesheet import tsl_locked_ids  # 2.125.0 B (#2119): entries of a closed month stay too
    rows = c.execute(f"SELECT e.id, e.user_id, e.start, e.seconds {base} AND NOT {tz_billed_sql()}", args).fetchall()
    lk = tsl_locked_ids(c, rows)
    lks = sum(r["seconds"] for r in rows if r["id"] in lk)
    return {"count": tot[0] - bil[0] - len(lk), "seconds": int(tot[1] - bil[1] - lks), "billed": bil[0], "billed_seconds": int(bil[1]),
            "all": admin, "locked": len(lk)}


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


TZW_KIND = "time_wipe"  # 2.783.0 (#5368): the Undo copy of "Delete all times" in the core's copy trash (module docstring)
part_kind(TZW_KIND, "time_entries", lock="time-wipe-{id}", agent=False, trash_prune=True, copy=True)


def tzw_dict(r):
    """2.783.0 (#5368): a copy of the core's trash as the fields the routes read: {id, n, seconds, deleted_at, entries}."""
    try:
        snap = json.loads(r["snap"] or "{}")
    except ValueError:
        snap = {}
    snap = snap if isinstance(snap, dict) else {}
    return {"id": r["id"], "n": int(snap.get("n") or 0), "seconds": int(snap.get("seconds") or 0), "deleted_at": r["deleted_at"],
            "entries": r["held"] or "[]"}


def tzw_add(c, uid, lid, entries, n, seconds, at=None):
    """2.783.0 (#5368): a new Undo copy of uid in list lid. -> its id."""
    return insert_id(c, f"INSERT INTO {PART_TRASH}(list_id,kind,ref_id,snap,held,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?)",
                     (lid, TZW_KIND, uid, json.dumps({"n": int(n or 0), "seconds": int(seconds or 0)}), entries, uid,
                      at or iso(now_utc())))


def tzw_set(c, wid, entries):
    """2.783.0 (#5368): what is left of a copy (entries as JSON), or the copy goes (entries None)."""
    if entries is None:
        c.execute(f"DELETE FROM {PART_TRASH} WHERE id=? AND kind=?", (wid, TZW_KIND))
    else:
        c.execute(f"UPDATE {PART_TRASH} SET held=? WHERE id=? AND kind=?", (entries, wid, TZW_KIND))


def tzw_move(c):
    """2.783.0 (#5368): the rows of the old table time_wipes (a version before 2.783, also after a rollback) into the core's copy
    trash with their time; at every start (core/objhooks.START), a no-op once the table is empty. One-way: the version
    before no longer finds the moved copies (Undo by the server's copy works here until the trash period ends)."""
    if not c.execute("SELECT to_regclass('time_wipes')").fetchone()[0]:
        return 0
    n = 0
    with system_ctx(c):  # every workspace's copies (a start-up step; nothing is handed to a person)
        for r in c.execute("SELECT * FROM time_wipes ORDER BY id").fetchall():
            tzw_add(c, r["user_id"], r["list_id"], r["entries"] or "[]", r["n"], r["seconds"], r["deleted_at"])
            c.execute("DELETE FROM time_wipes WHERE id=?", (r["id"],))
            n += 1
    return n


def tzw_revoked(c, uid, org, reason, heir=None, role=None):
    """2.783.0 (#5368): an account that goes takes its Undo copies along (as time_wipes.user_id did by ON DELETE CASCADE)."""
    if reason != "delete" or not uid:
        return {}
    n = c.execute(f"DELETE FROM {PART_TRASH} WHERE kind=? AND ref_id=?", (TZW_KIND, int(uid))).rowcount
    return {"time_wipes": n} if n else {}


objhooks.START.append(("tzw_move5368", False, tzw_move))  # 2.783.0 (#5368): every start (rows of an older version too)
objhooks.REVOKE.append(tzw_revoked)


def tz_wipe_row(c, lid, uid, wid=None):
    """2.530.0 B (#4315): the person's newest Undo copy of this list (or the one named), None = none (any more).
    2.783.0 (#5368): from the core's copy trash (tzw_dict)."""
    q = f"SELECT * FROM {PART_TRASH} WHERE list_id=? AND kind=? AND ref_id=?" + (" AND id=?" if wid is not None else "") + " ORDER BY id DESC LIMIT 1"
    r = c.execute(q, (lid, TZW_KIND, uid) + ((wid,) if wid is not None else ())).fetchone()
    return tzw_dict(r) if r else None


@app.get("/api/lists/<int:lid>/time/delete-all")
def tz_delete_all_preview(lid):
    need_time()
    tz_no_agent()
    c = db()
    _, admin = tz_scope(c, lid)
    w = tz_wipe_row(c, lid, me())
    return jsonify({**tz_preview(c, lid, me(), admin),
                    "undo": {"wipe": w["id"], "count": w["n"], "seconds": w["seconds"], "at": w["deleted_at"]} if w else None})


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
    from .timesheet import tsl_locked_ids
    lk = tsl_locked_ids(c, rows)  # 2.125.0 B (#2119): entries of a closed month stay
    rows = [r for r in rows if r["id"] not in lk]
    ids = [r["id"] for r in rows]
    prev = tz_preview(c, lid, uid, admin)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"DELETE FROM time_entries WHERE id IN ({','.join('?' * len(part))})", part)
    if ids:
        bump(c)
    # 2.63.0 (#1523): every column comes back, so Undo restores the timer's device id, the focus link and the flags as they were
    back = [{"user_id": r["user_id"], "task_id": r["task_id"], "list_id": lid, "task_title": r["task_title"], "start": r["start"],
             "end": r["end"], "seconds": r["seconds"], "note": r["note"], "source": r["source"], "client_id": r["client_id"],
             "pomo_id": r["pomo_id"], "reminded": r["reminded"], "auto_stopped": r["auto_stopped"],
             "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]
    for e in back:
        e["sig"] = h6b_sig(c, lid, e)  # 2.86.0 (N10)
    wid = None
    if back:  # 2.530.0 B (#4315): the Undo copy on the server, in the same transaction as the delete
        wid = tzw_add(c, uid, lid, json.dumps(back, ensure_ascii=False), len(back), sum(int(r["seconds"] or 0) for r in rows))  # 2.783.0 (#5368)
    if ids:  # 2.555.0 (#4570, review F2): the budget marks follow the wipe, so a later crossing tells again
        from .budgetwarn import bw_check
        bw_check(c, [(lid, None)] + [(lid, t) for t in {r["task_id"] for r in rows if r["task_id"]}])
    c.commit()
    return jsonify(ok=True, deleted=len(ids), seconds=prev["seconds"], billed=prev["billed"], entries=back, wipe=wid)


@app.post("/api/lists/<int:lid>/time/restore")
def tz_restore(lid):
    need_time()
    tz_no_agent()
    c = db()
    uid = me()
    _, admin = tz_scope(c, lid)
    b = body()
    w = None
    if "wipe" in b:  # 2.530.0 B (#4315): the Undo copy on the server (only the person who deleted)
        wid = b.get("wipe")
        if not isinstance(wid, int) or isinstance(wid, bool):
            raise Denied(400, tr("Invalid value: {0}", "wipe"))
        w = tz_wipe_row(c, lid, uid, wid)
        if not w:
            raise Denied(404)
        ents = json.loads(w["entries"] or "[]")
    else:
        ents = b.get("entries")
    if not isinstance(ents, list) or len(ents) > TZ_MAX_RESTORE:
        raise Denied(400, tr("Invalid value: {0}", "entries"))
    ts, n, left = iso(now_utc()), 0, []
    for e in ents:
        if not isinstance(e, dict) or not e.get("start") or not e.get("end"):
            continue
        owner = e.get("user_id")
        if not isinstance(owner, int) or (owner != uid and not admin):
            continue
        if owner != uid:  # 2.86.0 (N10): someone else's entry only as the delete returned it, and only once
            sig = e.get("sig")
            if not isinstance(sig, str) or not hmac.compare_digest(sig, h6b_sig(c, lid, e)):
                continue
            if c.execute('SELECT 1 FROM time_entries WHERE user_id=? AND list_id=? AND start=? AND "end"=?',
                         (owner, lid, str(e["start"])[:40], str(e["end"])[:40])).fetchone():
                continue
        if not c.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone() or not list_role(c, lid, owner):
            left.append(e)  # 2.530.0 (#4315, review M1): stays in the server's copy, may come back later
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
        from .timesheet import tsl_is_locked
        from ..collab.liste2e import le2e_mode
        if tsl_is_locked(c, owner, str(e["start"])[:40]):
            left.append(e)  # 2.530.0 (#4315, review M1): stays in the server's copy
            continue  # 2.125.0 B (#2119): never into a closed month
        cid, pid = n43_restore_ids(c, owner, e)
        insert_id(c, """INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,"end",seconds,note,source,client_id,pomo_id,
                                                 reminded,auto_stopped,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (owner, tid, lid, str(e.get("task_title") or "")[:500], str(e["start"])[:40], str(e["end"])[:40],
                   max(0, int(e.get("seconds") or 0)), "" if le2e_mode(c, lid) else str(e.get("note") or "")[:500],  # 2.538.0 (#4372)
                   e.get("source") if e.get("source") in ("timer", "manual", "focus") else "manual", cid, pid,
                   1 if e.get("reminded") in (1, True) else 0, 1 if e.get("auto_stopped") in (1, True) else 0,
                   n43_iso(e.get("created_at")) or ts, ts))
        n += 1
    if w and left:  # 2.530.0 (#4315, review M1): what could not come back (closed month, left the project) stays for later
        tzw_set(c, w["id"], json.dumps(left))  # 2.783.0 (#5368): the core's copy
    elif w:
        tzw_set(c, w["id"], None)  # 2.530.0 B (#4315): its way back is used
    else:  # 2.530.0 B (#4315): the answer's copy came back (an older window): the server's copy of that delete is used up too
        sigs = {e.get("sig") for e in ents if isinstance(e, dict) and isinstance(e.get("sig"), str)}
        for r in c.execute(f"SELECT id, held FROM {PART_TRASH} WHERE list_id=? AND kind=? AND ref_id=?", (lid, TZW_KIND, uid)).fetchall() if sigs else []:
            try:
                xs = [x for x in json.loads(r["held"] or "[]") if isinstance(x, dict)]
                if sigs & {x.get("sig") for x in xs}:  # 2.530.0 (#4315, review M1): only what really came back is used up
                    gone = sigs - {x.get("sig") for x in left}
                    rest = [x for x in xs if x.get("sig") not in gone]
                    tzw_set(c, r["id"], json.dumps(rest) if rest else None)  # 2.783.0 (#5368)
            except ValueError:
                continue
    if n:
        bump(c)
    if n:  # 2.555.0 (#4570, review F2): restored hours count for the budget warning like new ones
        from .budgetwarn import bw_check
        bw_check(c, [(lid, None)] + [(lid, e.get("task_id")) for e in ents if isinstance(e, dict) and isinstance(e.get("task_id"), int)])
    c.commit()
    return jsonify(ok=True, restored=n, left=len(left))
