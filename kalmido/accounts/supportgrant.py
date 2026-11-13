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
(never values or contents); reading the same route again, or the same refusal, within SGA_GET_GAP_S is one entry. 2.503.0 (#4307): so is every request
of a support session (a sign-in link the operator made through the grant, the session runs as the client: via 'support'), the
sign-in itself included; such an entry is marked as done by support and goes on the newest grant of the account. At most SGA_USES_MAX entries
per grant, readings go first. The client sees the grant and its log; the operator sees nothing of it except that the doors are open. An organisation grant holds only while the admin who
granted it is still an admin of the organisation (and it is not retired). Agents and API tokens cannot grant (a session or the
proxy sign-in only). A self-hosted server has no use for it: the routes answer hosted=false and refuse a grant (409).

  GET    /api/support-access          {hosted, hours, account: grant|null, orgs: [{org_id, name, grant|null}], past: [grant]}
  POST   /api/support-access          {hours, org_id?} -> {grant}
  DELETE /api/support-access/<id>     ends a grant early -> {ok}
"""
import json
import re
from datetime import timedelta

from flask import g, has_request_context, jsonify, request

from ..core.config import app, COOKIE
from ..core.db import body, connect, db, err, iso, now_utc, parse_iso
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.pg import insert_id, system_ctx
from ..core.env import env_bool
from .session import _token_hash, me
from .sessions import ses_end

SGA_HOURS = (1, 24, 72, 168)
SGA_USES_MAX = 300
SGA_GET_GAP_S = 600
SGA_PAST = 10


def sga_hosted():
    return env_bool("KALMIDO_HOSTED", False)  # admin.hosting.hosted() / orgs._operator_apart (the same switch)


def sga_open(c, uid=None, oid=None, note=True):
    """The id of the open grant that lets the operator into account uid (org_id NULL) or organisation oid, else None. note: the
    current request of an instance admin is logged on the grant (sga_flush)."""
    now = iso(now_utc())
    with system_ctx(c):  # grants of other people's accounts and organisations: structure only, no content
        if oid:
            r = c.execute("SELECT s.id FROM support_grants s JOIN orgs o ON o.id=s.org_id JOIN org_members m ON m.org_id=s.org_id "
                          "AND m.user_id=s.user_id AND m.role='admin' JOIN users u ON u.id=s.user_id AND NOT u.disabled "
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
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
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
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
        r = c.execute(f"SELECT MIN(ends_at) FROM support_grants WHERE id IN ({','.join('?' * len(used))})", used).fetchone()
    return min(exp, r[0]) if r and r[0] else exp


def sga_link_support(c, uid):
    """The end of the support access through which an instance admin made account uid's current sign-in link, or '' (a link of
    the person's parents / organisation admins, or none)."""
    if not sga_hosted():
        return ""
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
        r = c.execute("SELECT i.created_at FROM user_invites i JOIN users a ON a.id=i.created_by WHERE i.user_id=? AND i.kind='login' "
                      "AND i.created_by<>i.user_id AND a.is_admin", (uid,)).fetchone()
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
        with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
            c.execute("UPDATE sessions SET via='support', expires_at=LEAST(expires_at, ?) WHERE token_hash=?", (end, token_hash))
        if has_request_context():  # 2.503.0 (#4307): the sign-in is the first entry of the log
            g.sga_support = uid


def sga_close(c, r, now):
    """Grant row r ends now (early): the links the operator made through the account's support access and the sessions started
    with such links end too -- since the oldest grant of the account whose planned end is still ahead (a grant replaced by a
    longer one still caps its sessions at its own end, sga_session_cap). An organisation's grant opens no account."""
    if r["org_id"]:
        return
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
        since = c.execute("SELECT MIN(created_at) FROM support_grants WHERE user_id=? AND org_id IS NULL AND ends_at>?",
                          (r["user_id"], iso(now))).fetchone()[0] or r["created_at"]
        since = min(since, r["created_at"])
        # review F6: only the operator's sign-in links and support sessions (a parent's / an organisation admin's link stays)
        c.execute("DELETE FROM user_invites WHERE user_id=? AND kind='login' AND created_at>=? AND created_by<>user_id "
                  "AND created_by IN (SELECT id FROM users WHERE is_admin)", (r["user_id"], since))
        gone = [x[0] for x in c.execute("SELECT token_hash FROM sessions WHERE user_id=? AND via='support'", (r["user_id"],)).fetchall()]
    if gone:
        ses_end(c, r["user_id"], gone)


# 2.500.0 (#4070, decision of 03.11.2026): a support session (via 'support', sga_session_cap) reads and edits contents, nothing
# else (2.485.0, #3939, review F1, named only credentials; the audit found ways that outlive the consent beside them). A positive list:
# a write goes through only in a contents' area (SGA_CONTENT, the path's second segment) and when no segment of its path hands out
# access, leaves the account or cannot be taken back (SGA_NOT_CONTENT). Everything else, a new area too, is refused; reading stays.
SGA_CONTENT = frozenset((
    "tasks", "comments", "lists", "sections", "section-templates", "list-checks", "list-files", "list-tags", "deps", "tags", "fields",
    "filters", "sprints", "templates", "layouts", "folders", "folder-heads", "docs", "files", "attachments", "receipt-suggestions",
    "wiki", "sheets", "contacts", "events", "evcals", "notes", "notepads", "outline", "bookmarks", "habits", "pomo", "time", "budget",
    "clients", "office", "fsref", "videos", "books", "reading"))
SGA_NOT_CONTENT = frozenset((
    "public-link", "public-links", "regenerate", "members", "people", "groups", "owner", "org", "shares", "ext-links", "portal-link",
    "requests", "signoff", "signoffs", "agent", "agents", "ask-agent", "hooks-in", "error-hook", "repos", "folder-repo", "envs", "rules",
    "forms", "e2e", "keys", "lock", "scan-keys", "feed", "fetchers", "rights", "settings", "payonline", "peppol", "mail", "mail-notice",
    "mail-profile", "receipt-mail", "mail-addresses", "notify-template", "send", "send-mail", "purge", "anonymize", "pay-online", "move-space"))
SGA_PLAIN = frozenset(("/api/auth/logout", "/api/client-errors", "/api/settings", "/api/me"))  # /api/me: never SGA_GUARD_ME
SGA_GUARD_ME = {"password", "email", "username", "current_password", "new_password"}
SGA_GUARD_SCOPE = {"org_id", "org_visibility", "org_edit"}  # review F2: a PATCH that carries contents out of the account's scope
SGA_SECRET_READ = frozenset(("public-link", "public-links", "feed", "ext-links"))  # review F1: answers with a working link: it would outlive the grant
# 2.536.0 (#4363): the OIDC start would link a provider identity to the client's account and swap the support session for one
# without the mark (sga_close would not end it) -- refused like a write; the callback refuses a support session itself (oidc.py)
# review of 2.536.0: the HTTP Shortcuts ZIP makes a new drop token of the client on GET (users.py) -- it would outlive the grant
SGA_GET_REFUSED = frozenset(("/api/auth/oidc/start", "/api/me/share/httpshortcuts.zip"))
SGA_REFUSED = N_("Support access does not hand out sign-in data or add people: the client does that")
# 2.538.0 (#4365, decision of 04.11.2026): a support session books nothing in the office; editing contents is neither
# booking nor changing the account's structure. Refused besides SGA_NOT_CONTENT, whatever the area: finalising, cancelling,
# unlocking, payments, the cash book, the bank, DATEV, period / logbook closing, bookkeeping imports, the move of the personal
# office, deleting for good (trash, purge, delete-all) and deleting a project. (methods or None = every write, the whole path)
SGA_NO_WRITE = tuple((m, re.compile(p)) for m, p in (
    (None, r"/api/office/docs/\d+/(finalize|unlock|credit|datev|fee|payments(/\d+)?)"),  # fee: changes a finalised reminder
    (None, r"/api/office/(cashbooks|cash-entries|bank|datev|books|legacy|periods|move)(/.*)?"),
    (None, r"/api/office/(logbook/close|trial/delete-all|series/\d+/run|gen-docs/\d+/final)"),
    (None, r"/api/office/(meals/\d+/(approve|unlock)|cards/statements/\d+/(confirm|reopen)|cards/lines/\d+/(match|unmatch))"),
    (("DELETE",), r"/api/office/trash/\d+"),
    (None, r"/api/tasks/purge-done|/api/lists/\d+/time/delete-all"),
    # 2.538.0 (#4365): the master data import changes the office's structure; the import undos delete for good
    (None, r"/api/office/(import|fixed-costs/delete|trips/delete)"),
    (("DELETE",), r"/api/lists/\d+"),
    # 2.538.0 (#4365, review F4): deleting one trip / fixed cost has the client's undo only, like the bulk delete above
    (("DELETE",), r"/api/office/(trips|fixed-costs)/\d+"),
    # 2.538.0 (#4365, review F6): the next running number (a gap in the invoice series) is the bookkeeping's structure
    (None, r"/api/office/number-ranges/[^/]+"),
))
SGA_BOOKING = N_("A support session books nothing in the office and deletes nothing permanently: the client does that")
SGA_FOREIGN = N_("A support session puts nothing into an organisation that has not granted support access")


def sga_may_write(path):
    """True when a support session may write to path."""
    if path in SGA_PLAIN:
        return True
    seg = path.split("/")
    return len(seg) > 2 and seg[1] == "api" and seg[2] in SGA_CONTENT and not SGA_NOT_CONTENT.intersection(seg)


def sga_no_write(method, path, b):
    """2.538.0 (#4365): True when a support session may not make this write (SGA_NO_WRITE; a status change to / from paid is
    a payment)."""
    if any((m is None or method in m) and rx.fullmatch(path) for m, rx in SGA_NO_WRITE):
        return True
    return bool(re.fullmatch(r"/api/office/docs/\d+/status", path)) and isinstance(b, dict) and b.get("status") == "paid"


def sga_is_support(c):
    """True when this request runs in a support session (the session cookie's row, via 'support'). Asked once per request."""
    if not has_request_context() or g.get("user") is None:
        return False
    if "sga_is_sup" not in g:
        tok = request.cookies.get(COOKIE) if g.get("auth_via") == "session" else None
        r = c.execute("SELECT via FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone() if tok else None
        g.sga_is_sup = bool(r) and r[0] == "support"
    return g.sga_is_sup


def sga_org_foreign(c, oid):
    """2.538.0 (#4365): True when this request is one of a support session and organisation oid is neither the person's own
    office nor under an open support access of its own (sga_open): a support session puts no contents there."""
    if not oid or not sga_is_support(c):
        return False
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        return False  # not an organisation's id: the route answers it
    with system_ctx(c):  # the organisation's kind and grants: structure, no content
        r = c.execute("SELECT personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
    if r is None:
        return False  # no such organisation: the route answers it (no hint for the support session)
    return r[0] != g.user["id"] and not sga_open(c, oid=oid, note=False)


def sga_list_foreign(c, lid):
    """2.538.0 (#4365): sga_org_foreign for the organisation of list lid (a task / document put into it)."""
    if isinstance(lid, bool) or not isinstance(lid, (int, str)) or not str(lid).isdigit() or not sga_is_support(c):
        return False
    with system_ctx(c):  # only the list's organisation id: structure, no content
        r = c.execute("SELECT org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    return bool(r) and sga_org_foreign(c, r[0])


# 2.538.0 (#4365, review F5): a new event / contact / note goes into the organisation of its container: the calendar (cal_id),
# the address book (book_id, an organisation's own book first) or the project in the path (its notes, notepads, checks, files,
# links, milestones)
SGA_BOX_ORG = {"cal_id": "SELECT org_id FROM ev_cals WHERE id=?", "book_id": "SELECT COALESCE(owner_org_id, org_id) FROM books WHERE id=?"}
SGA_LIST_NEW = re.compile(r"/api/lists/(\d+)/(notes|notepads|checklist|checks|files|links|milestones)")


def sga_box_foreign(c, method, path, b):
    """2.538.0 (#4365, review F5): True when a support session's write puts contents into an organisation without its own
    support access through a container: cal_id / book_id in the body or a new item of the project in the path (POST)."""
    if not sga_is_support(c):
        return False
    for k, q in SGA_BOX_ORG.items():
        v = b.get(k) if isinstance(b, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isdigit():
            continue  # none / not an id: the route answers it (an empty one picks the person's default)
        with system_ctx(c):  # only the container's organisation id: structure, no content
            r = c.execute(q, (int(v),)).fetchone()
        if r and sga_org_foreign(c, r[0]):
            return True
    m = SGA_LIST_NEW.fullmatch(path) if method == "POST" else None
    return bool(m) and sga_list_foreign(c, m.group(1))


def sga_scope_check(c, oid):
    """2.538.0 (#4365): for the routes that work out an organisation themselves (a default workspace): Denied 403 code
    support_session when a support session would put contents into an organisation without support access."""
    if sga_org_foreign(c, oid):
        raise Denied(403, tr(SGA_FOREIGN), data={"code": "support_session"})


def sga_session_mark(c, token_hash):
    """2.503.0 (#4307): the current request is one of a support session: it goes into the client's log (sga_flush). Called by
    authenticate, so a request an early gate refuses is listed too, a reading as well as a write. Only a hosted server makes such sessions."""
    if request.method == "OPTIONS" or not sga_hosted():
        return
    r = c.execute("SELECT via FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
    if r and r[0] == "support":
        g.sga_support = g.user["id"]


@app.before_request
def sga_guard():
    if g.get("auth_via") != "session" or g.get("user") is None or request.method == "OPTIONS":
        return None
    if request.method in ("GET", "HEAD"):
        p = request.path
        if ((p in SGA_GET_REFUSED or (p.startswith("/api/") and p.rsplit("/", 1)[-1] in SGA_SECRET_READ))
                and sga_is_support(db())):
            return jsonify(error=tr(SGA_REFUSED), code="support_session"), 403
        return None
    c = db()
    if not sga_is_support(c):
        return None
    # 2.500.0 (#4070): every write of a support session stands on the grant's log, a refused one too (sga_flush): the client sees it
    gid = sga_open(c, uid=g.user["id"], note=False)
    if gid:
        g.sga_used = {*(g.get("sga_used") or ()), int(gid)}
        g.sga_support = g.user["id"]
    p = request.path
    hit = not sga_may_write(p)
    b = request.get_json(silent=True) if request.is_json else None
    if not hit and request.method == "PATCH":
        hit = isinstance(b, dict) and bool(set(b) & (SGA_GUARD_ME if p == "/api/me" else SGA_GUARD_SCOPE))
    if hit:
        return jsonify(error=tr(SGA_REFUSED), code="support_session"), 403
    if sga_no_write(request.method, p, b):  # 2.538.0 (#4365): no booking, nothing deleted for good
        return jsonify(error=tr(SGA_BOOKING), code="support_session"), 403
    # 2.538.0 (#4365): contents go into no organisation without its own support access (a new object's org_id, a list_id)
    if (isinstance(b, dict) and (sga_org_foreign(c, b.get("org_id")) or sga_list_foreign(c, b.get("list_id")))) \
            or sga_box_foreign(c, request.method, p, b):  # review F5: through a calendar, an address book, a project's path
        return jsonify(error=tr(SGA_FOREIGN), code="support_session"), 403
    return None


def _route():
    """The route pattern, never the address: a path without a route could carry a value (2.503.0, #4307)."""
    r = request.url_rule
    return r.rule[:120] if r is not None else "(unknown)"


def sga_read_again(uses, e, now):
    """Entry e is a reading or a refused request the log of a grant already has within SGA_GET_GAP_S (2.503.0, #4307: anywhere in
    that time, not only as the last entry: the app reads a few routes in turn, and that alone filled the log; review: refused
    requests in a row must not push the readings out of the log, a request that went through always counts)."""
    if e["m"] not in ("GET", "HEAD") and e["s"] < 400:
        return False
    since = now - timedelta(seconds=SGA_GET_GAP_S)
    for u in reversed(uses):
        if not isinstance(u, dict):
            continue
        at = parse_iso(u.get("at") or "")
        if at is None or at <= since:
            return False
        if (u.get("m"), u.get("r"), u.get("by"), u.get("s"), u.get("sup")) == (e["m"], e["r"], e["by"], e["s"], e.get("sup")):
            return True
    return False


@app.after_request
def sga_flush(resp):
    """Writes the uses of this request on their grants (own connection: a reading request commits nothing)."""
    used = g.get("sga_used") if has_request_context() else None
    sup = g.get("sga_support") if has_request_context() else None
    if not used and not sup:
        return resp
    try:
        now = now_utc()
        e = {"at": iso(now), "by": int(sup or g.user["id"]), "m": request.method[:8], "r": _route(), "s": int(resp.status_code)}
        if sup:  # 2.500.0 (#4070): done in a support session, not by the person
            e["sup"] = 1
        c = connect()
        try:
            with system_ctx(c):  # an organisation's grant is behind row-level security; this connection runs inside a request
                c.execute("SET LOCAL lock_timeout = '2s'")  # review F7: never stall a response behind the request's own locks
                gids = {int(gid) for gid in used or ()}
                if sup:  # 2.503.0 (#4307): a reading or the sign-in of a support session goes on the account's newest grant
                    row = c.execute("SELECT id FROM support_grants WHERE user_id=? AND org_id IS NULL ORDER BY id DESC LIMIT 1", (int(sup),)).fetchone()
                    if row:
                        gids.add(int(row[0]))
                for gid in sorted(gids):
                    row = c.execute("SELECT uses FROM support_grants WHERE id=? FOR UPDATE", (gid,)).fetchone()
                    if not row:
                        continue
                    try:
                        uses = json.loads(row[0] or "[]")
                    except ValueError:
                        uses = []
                    if sga_read_again(uses, e, now):
                        continue  # the same reading / refusal again: one entry
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
            "uses": [{"at": u.get("at") or "", "by": tr("Support access") if u.get("sup") else names.get(u.get("by"), ""), "method": u.get("m") or "", "route": u.get("r") or "",
                      "status": u.get("s") or 0} for u in reversed(uses)]}


def _need_person():
    """A person in a session (or the proxy sign-in) -- never an agent or an API token: a door into the account."""
    if g.user is None or (g.user["kind"] or "user") == "agent" or g.get("auth_via") not in ("session", "proxy"):
        raise Denied(403, tr("Only you can grant support access, signed in in the app"))


def _my_orgs(c):
    """The organisations the current person administers (not a personal office, not retired): [(id, name)]."""
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
        return [(r["id"], r["name"]) for r in c.execute(
            "SELECT o.id, o.name FROM orgs o JOIN org_members m ON m.org_id=o.id WHERE m.user_id=? AND m.role='admin' "
            "AND o.personal_of IS NULL AND o.retired_at IS NULL ORDER BY o.name, o.id", (me(),)).fetchall()]


def _may_end(c, r):
    if r["org_id"]:
        with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
            return bool(c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=? AND role='admin'", (r["org_id"], me())).fetchone())
    return r["user_id"] == me()


@app.get("/api/support-access")
def support_access_get():
    c = db()
    orgs = _my_orgs(c)
    oids = [o for o, _n in orgs]
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
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
    with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
        r = c.execute("SELECT * FROM support_grants WHERE id=?", (gid,)).fetchone()
    if not r or not _may_end(c, r):
        return err(tr("Not found"), 404)
    if not r["ended_at"]:
        now = now_utc()
        with system_ctx(c):  # support grants of other accounts / organisations (row-level security): structure, no content
            c.execute("UPDATE support_grants SET ended_at=?, ended_by=? WHERE id=? AND ended_at IS NULL", (iso(now), me(), gid))
        sga_close(c, r, now)
        c.commit()
        print("support access ended:", f"grant #{gid}", flush=True)
    return jsonify(ok=True)
