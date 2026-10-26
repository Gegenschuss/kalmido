"""2.361.2 (#2923): the way back out of an organisation for a member (decided 23.10.2026: the member asks, an admin releases it
with one click; nothing goes back silently).

A member who brought something into an organisation or made it there (accounts/orgout.py OO_KINDS: a project they own, a
table or file they made) asks its admins for it (POST /api/orgs/<oid>/out-requests {kind, id}); the admins get a News entry
and see the open requests in "Projects of the organisation" (orglists.py). An admin releases or declines it (POST
/api/orgs/<oid>/out-requests/<rid> {decision}); the member hears about it. A released request lets that person move that one
thing into their private space with the usual move (and its preview) within OO_GRANT_DAYS; org_out() uses it up and logs
the move like an admin's ("moveout", released). Releasing and declining are written to the organisation's list log.
People only (agents 403). App only (APP_ONLY "* /api/orgs" in tests/parity_test.py)."""
import json
from datetime import timedelta

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, db, iso, now_utc
from ..core.pg import insert_id, system_ctx
from ..core.access import Denied
from ..accounts.session import me
from .orgout import OO_GRANT_DAYS, OO_KINDS, oo_grant, oo_mine, oo_news
from .orgs import _need_org_admin, org_need_person

OOR_LIMIT = 30  # decided requests shown next to the open ones
OOR_PAUSE_DAYS = 3  # after a decline the same thing is asked again only after this many days


def oor_admins(c, oid):
    with system_ctx(c):  # the organisation's admins (structure)
        return [r[0] for r in c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id
                                           WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent'""", (oid,))]


def oor_org_name(c, oid):
    with system_ctx(c):  # the name of an organisation (structure)
        return (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]


def oor_rows(c, oid, by=None):
    """The open requests of organisation oid and the last decided ones (by = only that person's), newest first."""
    w, a = ("AND by_id=?", (by,)) if by else ("", ())
    rows = c.execute(f"SELECT * FROM org_out_requests WHERE org_id=? AND state='open' {w} ORDER BY id DESC", (oid, *a)).fetchall()
    rows += c.execute(f"SELECT * FROM org_out_requests WHERE org_id=? AND state!='open' {w} ORDER BY id DESC LIMIT ?", (oid, *a, OOR_LIMIT)).fetchall()
    ids = sorted({x for r in rows for x in (r["by_id"], r["decided_by"]) if x})
    names = {r[0]: r[1] for r in c.execute(f"SELECT id, COALESCE(NULLIF(display_name, ''), username) FROM users WHERE id IN ({','.join('?' * len(ids))})",
                                           ids)} if ids else {}  # members of the organisation (they see each other)
    return [{"id": r["id"], "kind": r["kind"], "obj_id": r["obj_id"], "name": r["name"], "state": r["state"],
             "by_id": r["by_id"], "by": names.get(r["by_id"], ""), "decided_by": names.get(r["decided_by"], ""),
             "decided_at": r["decided_at"], "created_at": r["created_at"]} for r in rows]


def oor_log(c, oid, r, action):
    c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at,detail) VALUES(?,?,?,?,?,?,?,?,?)",
              (oid, r["obj_id"] if r["kind"] == "list" else None, r["name"], action, me(), r["by_id"], None, iso(now_utc()),
               json.dumps({"kind": r["kind"]})))


@app.get("/api/orgs/<int:oid>/out-requests")
def oor_list(oid):
    """Admins: the organisation's requests (open first); a member: their own."""
    c = db()
    role = org_need_person(c, oid)
    return jsonify({"requests": oor_rows(c, oid, None if role == "admin" else me()), "days": OO_GRANT_DAYS, "admin": role == "admin"})


@app.post("/api/orgs/<int:oid>/out-requests")
def oor_ask(oid):
    """{kind, id}: ask the admins of oid to give back what I brought in or made (into my private space). An open or released
    request for the same thing is answered again (no second one); an admin moves it themselves (409)."""
    c, b = db(), body()
    role = org_need_person(c, oid)
    kind, obj = b.get("kind"), b.get("id")
    if not isinstance(kind, str) or kind not in OO_KINDS:
        raise Denied(400, tr("Invalid value: {0}", "kind"))
    if kind == "sheet" and isinstance(obj, int) and not isinstance(obj, bool):  # a further sheet: the table it belongs to
        r = c.execute("SELECT id, book_id FROM sheets WHERE id=?", (obj,)).fetchone()
        obj = (r["book_id"] or r["id"]) if r else obj
    mine = oo_mine(c, kind, obj, me())
    if not mine or mine[0] != oid:
        raise Denied(403, tr("Only what you brought into the organisation or made there can be asked back"))
    if role == "admin":
        raise Denied(409, tr("You are an admin of the organisation: move it yourself"))
    old = c.execute("SELECT * FROM org_out_requests WHERE org_id=? AND kind=? AND obj_id=? AND by_id=? AND state IN ('open', 'approved') "
                    "ORDER BY id DESC LIMIT 1", (oid, kind, obj, me())).fetchone()
    if old and (old["state"] == "open" or oo_grant(c, oid, kind, obj)):
        return jsonify({"ok": True, "id": old["id"], "state": old["state"], "again": True})
    if c.execute("SELECT 1 FROM org_out_requests WHERE org_id=? AND kind=? AND obj_id=? AND by_id=? AND state='declined' AND decided_at>=?",
                 (oid, kind, obj, me(), iso(now_utc() - timedelta(days=OOR_PAUSE_DAYS)))).fetchone():  # review: no News spam after a no
        raise Denied(409, tr("An admin declined this a short while ago. Ask again in a few days or talk to the admins."))
    rid = insert_id(c, "INSERT INTO org_out_requests(org_id,kind,obj_id,name,by_id,state,created_at) VALUES(?,?,?,?,?,'open',?)",
                    (oid, kind, obj, mine[1], me(), iso(now_utc())))
    oo_news(c, oor_admins(c, oid), {"action": "outreq", "name": mine[1], "org": oor_org_name(c, oid), "org_id": oid, "kind": kind})
    c.commit()
    return jsonify({"ok": True, "id": rid, "state": "open"})


@app.post("/api/orgs/<int:oid>/out-requests/<int:rid>")
def oor_decide(oid, rid):
    """{decision: approve | decline}: an admin of oid releases (the person may then move it into their private space for
    OO_GRANT_DAYS days) or declines an open request. Logged; the person is told."""
    c, b = db(), body()
    _need_org_admin(c, oid)
    d = b.get("decision")
    if d not in ("approve", "decline"):
        raise Denied(400, tr("Invalid value: {0}", "decision"))
    r = c.execute("SELECT * FROM org_out_requests WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["state"] != "open":
        raise Denied(409, tr("This request was already decided"))
    gone = oo_mine(c, r["kind"], r["obj_id"], r["by_id"])
    if d == "approve" and (not gone or gone[0] != oid):
        c.execute("UPDATE org_out_requests SET state='declined', decided_by=?, decided_at=? WHERE id=?", (me(), iso(now_utc()), rid))
        c.commit()
        raise Denied(409, tr("It is no longer in the organisation or no longer the person's: the request is closed"))
    state = "approved" if d == "approve" else "declined"
    c.execute("UPDATE org_out_requests SET state=?, decided_by=?, decided_at=? WHERE id=?", (state, me(), iso(now_utc()), rid))
    oor_log(c, oid, r, "outok" if state == "approved" else "outno")
    oo_news(c, [r["by_id"]], {"action": "outok" if state == "approved" else "outno", "name": r["name"], "org": oor_org_name(c, oid),
                              "org_id": oid, "kind": r["kind"], "obj": r["obj_id"], "days": OO_GRANT_DAYS},
            list_id=r["obj_id"] if r["kind"] == "list" and state == "approved" else None)
    c.commit()
    return jsonify({"ok": True, "state": state, "requests": oor_rows(c, oid)})
