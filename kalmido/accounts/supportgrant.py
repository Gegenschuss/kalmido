"""2.485.0 (#3939): support access only with the client's consent (hosted instances).

On a hosted instance (KALMIDO_HOSTED=1) the operator stays out of its clients' organisations and accounts (2.399.0, #2687:
accounts/orgs.py op_foreign_org / op_foreign_account answer "foreign" and every instance-admin way in answers 403). When a
client needs help, the client opens the door for a limited time -- never the operator:

  - a person grants support access to the own account (Settings > Account > Support access): the operator's admin ways into
    that account work again as on a self-hosted server (sign-in link, password link, its private projects, its agents) -- and
    into the person's own office (the organisation personal_of the person: P4, a freelancer's office follows the account);
  - an organisation admin grants it for the organisation: its name, members, roles, projects and agents.

A grant runs 1 hour, 1 day, 3 days or 7 days (SGA_HOURS), ends by itself and can be ended at any time by the person / by any
admin of the organisation. A new grant of the same scope replaces the open one. Every request in which the operator (an
instance admin) passed the guard only thanks to a grant is logged on the grant: time, who, method, route pattern and status
(never values or contents); reading the same route again within SGA_GET_GAP_S is one entry. The client sees the grant and its
log; the operator sees nothing of it except that the doors are open. An organisation grant holds only while the admin who
granted it is still an admin of the organisation (and it is not retired). Agents and API tokens cannot grant (a session or the
proxy sign-in only). A self-hosted server has no use for it: the routes answer hosted=false and refuse a grant (409).

  GET    /api/support-access          {hosted, hours, account: grant|null, orgs: [{org_id, name, grant|null}], past: [grant]}
  POST   /api/support-access          {hours, org_id?} -> {grant}
  DELETE /api/support-access/<id>     ends a grant early -> {ok}
"""
import json
from datetime import timedelta

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.db import body, connect, db, err, iso, now_utc, parse_iso
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.pg import insert_id, system_ctx
from .session import me

SGA_HOURS = (1, 24, 72, 168)
SGA_USES_MAX = 300
SGA_GET_GAP_S = 600
SGA_PAST = 10


def sga_hosted():
    from .orgs import _operator_apart
    return bool(_operator_apart())


def sga_open(c, uid=None, oid=None, note=True):
    """The id of the open grant that lets the operator into account uid (org_id NULL) or organisation oid, else None. note: the
    current request of an instance admin is logged on the grant (sga_flush)."""
    now = iso(now_utc())
    with system_ctx(c):  # grants of other people's accounts and organisations: structure only, no content
        if oid:
            r = c.execute("SELECT s.id FROM support_grants s JOIN orgs o ON o.id=s.org_id JOIN org_members m ON m.org_id=s.org_id "
                          "AND m.user_id=s.user_id AND m.role='admin' JOIN users u ON u.id=s.user_id AND u.disabled=0 "
                          "WHERE s.org_id=? AND s.ended_at IS NULL AND s.ends_at>? "
                          "AND o.retired_at IS NULL ORDER BY s.id DESC LIMIT 1", (oid, now)).fetchone()
            if not r:  # a person's own office follows the person's account grant (P4)
                r = c.execute("SELECT s.id FROM support_grants s JOIN orgs o ON o.personal_of=s.user_id WHERE o.id=? AND s.org_id IS NULL "
                              "AND s.ended_at IS NULL AND s.ends_at>? ORDER BY s.id DESC LIMIT 1", (oid, now)).fetchone()
        elif uid:
            r = c.execute("SELECT id FROM support_grants WHERE user_id=? AND org_id IS NULL AND ended_at IS NULL AND ends_at>? "
                          "ORDER BY id DESC LIMIT 1", (uid, now)).fetchone()
        else:
            r = None
    if r and note:
        sga_note(r[0])
    return r[0] if r else None


def sga_until(c, uid):
    """The end of the open support access of account uid ('' = none), for the operator's account list."""
    with system_ctx(c):
        r = c.execute("SELECT ends_at FROM support_grants WHERE user_id=? AND org_id IS NULL AND ended_at IS NULL AND ends_at>? "
                      "ORDER BY id DESC LIMIT 1", (uid, iso(now_utc()))).fetchone()
    return r[0] if r else ""


def sga_note(gid):
    """Marks grant gid as used by the current request (an instance admin's only: the operator)."""
    if not has_request_context():
        return
    u = g.get("user")
    if u is None or not u["is_admin"]:
        return
    used = g.get("sga_used")
    if used is None:
        used = g.sga_used = set()
    used.add(int(gid))


def sga_link_exp(c, exp):
    """The end of a sign-in / password link made in this request: no later than the grants that let the operator make it
    (invite.invite_new). A link made without a grant keeps exp."""
    used = sorted(g.get("sga_used") or ()) if has_request_context() else []
    if not used:
        return exp
    with system_ctx(c):
        r = c.execute(f"SELECT MIN(ends_at) FROM support_grants WHERE id IN ({','.join('?' * len(used))})", used).fetchone()
    return min(exp, r[0]) if r and r[0] else exp


def sga_link_support(c, uid):
    """The end of the support access through which an instance admin made account uid's current sign-in link, or '' (a link of
    the person's parents / organisation admins, or none)."""
    if not sga_hosted():
        return ""
    with system_ctx(c):
        r = c.execute("SELECT i.created_at FROM user_invites i JOIN users a ON a.id=i.created_by WHERE i.user_id=? AND i.kind='login' "
                      "AND i.created_by<>i.user_id AND a.is_admin=1", (uid,)).fetchone()
        if not r:
            return ""
        s = c.execute("SELECT MAX(ends_at) FROM support_grants WHERE user_id=? AND org_id IS NULL AND created_at<=? AND ends_at>=?",
                      (uid, r[0], r[0])).fetchone()
    return s[0] if s and s[0] else ""


def sga_session_cap(c, uid, token_hash):
    """2.485.0 (#3939): a session started with a sign-in link the operator made through the account's support access ends with
    that access at the latest and is marked via 'support' (no credentials in it, sga_guard; ended with the access, sga_close)."""
    end = sga_link_support(c, uid)
    if end:
        with system_ctx(c):
            c.execute("UPDATE sessions SET via='support', expires_at=LEAST(expires_at, ?) WHERE token_hash=?", (end, token_hash))


def sga_close(c, r, now):
    """Grant row r ends now (early): the links the operator made through the account's support access and the sessions started
    with such links end too -- since the oldest grant of the account whose planned end is still ahead (a grant replaced by a
    longer one still caps its sessions at its own end, sga_session_cap). An organisation's grant opens no account."""
    if r["org_id"]:
        return
    with system_ctx(c):
        since = c.execute("SELECT MIN(created_at) FROM support_grants WHERE user_id=? AND org_id IS NULL AND ends_at>?",
                          (r["user_id"], iso(now))).fetchone()[0] or r["created_at"]
        since = min(since, r["created_at"])
        # review F6: only the operator's sign-in links and support sessions (a parent's / an organisation admin's link stays)
        c.execute("DELETE FROM user_invites WHERE user_id=? AND kind='login' AND created_at>=? AND created_by<>user_id "
                  "AND created_by IN (SELECT id FROM users WHERE is_admin=1)", (r["user_id"], since))
        gone = [x[0] for x in c.execute("SELECT token_hash FROM sessions WHERE user_id=? AND via='support'", (r["user_id"],)).fetchall()]
    if gone:
        from .sessions import ses_end
        ses_end(c, r["user_id"], gone)


# 2.485.0 (#3939, review F1): what a support session (via 'support', sga_session_cap) never does: credentials, ways out to other
# services and support access itself -- they would outlive the client's consent. Writes only; reading stays.
SGA_GUARD = ("/api/me/2fa", "/api/me/app-passwords", "/api/me/passkeys", "/api/me/tokens", "/api/me/drop-token", "/api/me/mail/token",
             "/api/me/webhooks", "/api/me/channels", "/api/me/ntfy-inbox", "/api/me/sessions", "/api/my/agents", "/api/support-access",
             "/api/stepup")
SGA_GUARD_ME = {"password", "email", "username", "current_password", "new_password"}


@app.before_request
def sga_guard():
    if request.method in ("GET", "HEAD", "OPTIONS") or g.get("auth_via") != "session" or g.get("user") is None:
        return None
    p = request.path
    hit = p.startswith(SGA_GUARD)
    if not hit and p == "/api/me" and request.method == "PATCH":
        b = request.get_json(silent=True)
        hit = isinstance(b, dict) and bool(set(b) & SGA_GUARD_ME)
    if not hit:
        return None
    from .session import COOKIE, _token_hash
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    c = db()
    r = c.execute("SELECT via FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone()
    if r and r[0] == "support":
        return jsonify(error=tr("Support access does not hand out sign-in data or add people: the client does that"), code="support_session"), 403
    return None


def _route():
    r = request.url_rule
    return (r.rule if r is not None else request.path)[:120]


@app.after_request
def sga_flush(resp):
    """Writes the uses of this request on their grants (own connection: a reading request commits nothing)."""
    used = g.get("sga_used") if has_request_context() else None
    if not used:
        return resp
    try:
        now = now_utc()
        e = {"at": iso(now), "by": int(g.user["id"]), "m": request.method[:8], "r": _route(), "s": int(resp.status_code)}
        c = connect()
        try:
            c.execute("SET LOCAL lock_timeout = '2s'")  # review F7: never stall a response behind the request's own locks
            for gid in sorted(used):
                row = c.execute("SELECT uses FROM support_grants WHERE id=? FOR UPDATE", (gid,)).fetchone()
                if not row:
                    continue
                try:
                    uses = json.loads(row[0] or "[]")
                except ValueError:
                    uses = []
                last = uses[-1] if uses and isinstance(uses[-1], dict) else None
                if (last and e["m"] in ("GET", "HEAD") and (last.get("m"), last.get("r"), last.get("by"), last.get("s")) == (e["m"], e["r"], e["by"], e["s"])
                        and (parse_iso(last.get("at") or "") or now) > now - timedelta(seconds=SGA_GET_GAP_S)):
                    continue  # the same reading again: one entry
                uses.append(e)
                while len(uses) > SGA_USES_MAX:  # review F4: readings go first, a change is never pushed out
                    i = next((k for k, u in enumerate(uses) if not isinstance(u, dict) or u.get("m") in ("GET", "HEAD")), 0)
                    uses.pop(i)
                c.execute("UPDATE support_grants SET uses=? WHERE id=?", (json.dumps(uses, separators=(",", ":")), gid))
            c.commit()
        finally:
            c.close()
    except Exception as x:  # noqa: BLE001  the log must never break a request
        print("support access log error:", type(x).__name__, flush=True)
    return resp


def _names(c, ids):
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    with system_ctx(c):  # the operator's and the granting admin's names, shown to the client
        rows = c.execute(f"SELECT id, display_name, username FROM users WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {r["id"]: r["display_name"] or r["username"] for r in rows}


def sga_public(c, r, names=None):
    now = iso(now_utc())
    try:
        uses = json.loads(r["uses"] or "[]")
    except ValueError:
        uses = []
    uses = [u for u in uses if isinstance(u, dict)]
    if names is None:
        names = _names(c, [r["user_id"], r["ended_by"]] + [u.get("by") for u in uses])
    return {"id": r["id"], "org_id": r["org_id"], "created_at": r["created_at"], "ends_at": r["ends_at"], "ended_at": r["ended_at"] or "",
            "active": not r["ended_at"] and r["ends_at"] > now, "by": names.get(r["user_id"], ""),
            "ended_by": names.get(r["ended_by"], "") if r["ended_by"] else "",
            "uses": [{"at": u.get("at") or "", "by": names.get(u.get("by"), ""), "method": u.get("m") or "", "route": u.get("r") or "",
                      "status": u.get("s") or 0} for u in reversed(uses)]}


def _need_person():
    """A person in a session (or the proxy sign-in) -- never an agent or an API token: a door into the account."""
    from ..agents.core import is_agent
    if g.user is None or is_agent(g.user) or g.get("auth_via") not in ("session", "proxy"):
        raise Denied(403, tr("Only you can grant support access, signed in in the app"))


def _my_orgs(c):
    """The organisations the current person administers (not a personal office, not retired): [(id, name)]."""
    with system_ctx(c):
        return [(r["id"], r["name"]) for r in c.execute(
            "SELECT o.id, o.name FROM orgs o JOIN org_members m ON m.org_id=o.id WHERE m.user_id=? AND m.role='admin' "
            "AND o.personal_of IS NULL AND o.retired_at IS NULL ORDER BY o.name, o.id", (me(),)).fetchall()]


def _may_end(c, r):
    if r["org_id"]:
        from .orgs import is_org_admin
        return is_org_admin(c, me(), r["org_id"])
    return r["user_id"] == me()


@app.get("/api/support-access")
def support_access_get():
    c = db()
    orgs = _my_orgs(c)
    oids = [o for o, _n in orgs]
    with system_ctx(c):
        q = "SELECT * FROM support_grants WHERE (user_id=? AND org_id IS NULL)"
        args = [me()]
        if oids:
            q += f" OR org_id IN ({','.join('?' * len(oids))})"
            args += oids
        rows = c.execute(q + " ORDER BY id DESC LIMIT 200", args).fetchall()
    pub = [sga_public(c, r) for r in rows]
    open_ = {}
    for p in pub:
        if p["active"]:
            open_.setdefault(p["org_id"], p)
    return jsonify(hosted=sga_hosted(), hours=list(SGA_HOURS), account=open_.get(None),
                   orgs=[{"org_id": o, "name": n, "grant": open_.get(o)} for o, n in orgs],
                   past=[p for p in pub if not p["active"]][:SGA_PAST])


@app.post("/api/support-access")
def support_access_grant():
    _need_person()
    c = db()
    if not sga_hosted():
        return err(tr("Support access is only needed on a hosted server"), 409)
    b = body()
    if not isinstance(b, dict):
        b = {}
    h = b.get("hours")
    if isinstance(h, bool) or h not in SGA_HOURS:
        return err(tr("Invalid value: {0}", "hours"))
    oid = b.get("org_id")
    if oid is not None:
        if isinstance(oid, bool) or not isinstance(oid, int) or oid not in [o for o, _n in _my_orgs(c)]:
            raise Denied(403, tr("Only an admin of the organisation can grant support access to it"))
    now = now_utc()
    with system_ctx(c):  # the grants of an organisation are its admins' together (row-level security: system)
        if oid is None:
            c.execute("UPDATE support_grants SET ended_at=?, ended_by=? WHERE user_id=? AND org_id IS NULL AND ended_at IS NULL",
                      (iso(now), me(), me()))
        else:
            c.execute("UPDATE support_grants SET ended_at=?, ended_by=? WHERE org_id=? AND ended_at IS NULL", (iso(now), me(), oid))
        gid = insert_id(c, "INSERT INTO support_grants(user_id, org_id, created_at, ends_at) VALUES(?,?,?,?)",
                        (me(), oid, iso(now), iso(now + timedelta(hours=h))))
        r = c.execute("SELECT * FROM support_grants WHERE id=?", (gid,)).fetchone()
    c.commit()
    print("support access granted:", "org" if oid else "account", f"#{oid or me()}", f"{h} h", flush=True)
    return jsonify(grant=sga_public(c, r))


@app.delete("/api/support-access/<int:gid>")
def support_access_end(gid):
    _need_person()
    c = db()
    with system_ctx(c):
        r = c.execute("SELECT * FROM support_grants WHERE id=?", (gid,)).fetchone()
    if not r or not _may_end(c, r):
        return err(tr("Not found"), 404)
    if not r["ended_at"]:
        now = now_utc()
        with system_ctx(c):
            c.execute("UPDATE support_grants SET ended_at=?, ended_by=? WHERE id=? AND ended_at IS NULL", (iso(now), me(), gid))
        sga_close(c, r, now)
        c.commit()
        print("support access ended:", f"grant #{gid}", flush=True)
    return jsonify(ok=True)
