"""2.36.2 (#1133): security alerts of the app itself. Reported at once through the admin alerts (kind "security", can be
switched off like the other kinds, own key per event + the cooldown) and as one machine-readable line in the server log
(prefix "kalmido-security:", JSON), so an operator's log watcher can pick it up without access to the data:
  - a new instance admin (role change, a new account with the admin flag, sign-on group sync, anything else)
  - a new admin of an organisation (instance admins are left out: they are admins of every organisation)
  - a new agent and a new agent token
  - an admin (instance or organisation) signing in from an address not among their last SEV_IPS addresses
Admins / agents / tokens are compared with what the watch saw before (table sev_known) on every watchdog tick, so every way
of becoming an admin is covered, not only the app's own routes. The first tick after the update only takes the baseline
(no alerts); likewise the first sign-in of an admin after the update only stores the address. Addresses are stored as a
keyed hash; the alert itself names the address. Alerts carry ids, usernames and addresses only, never content."""
import hashlib
import hmac
import json
import sys
from datetime import timedelta

from ..core.config import app, SECRET_KEY
from ..core.i18n import N_
from ..core.db import iso, now_utc
from .alerts import _AA, _AA_LOCK, aa_now

SEV_IPS = 10  # sign-in addresses remembered per admin
SEV_KINDS = ("admin", "org_admin", "agent", "agent_token")


def sev_log(event, **kw):
    """One line for log watchers: kalmido-security: {"event": ..., ...} (never raises)."""
    line = "kalmido-security: " + json.dumps({"event": event, **kw}, sort_keys=True, ensure_ascii=True, default=str)
    try:
        app.logger.warning(line)
    except Exception:  # noqa: BLE001
        print(line, file=sys.stderr, flush=True)


def sev_ip_hash(ip):
    key = SECRET_KEY or b"kalmido-admin-login-ip"
    return hmac.new(key, (ip or "").encode(), hashlib.sha256).hexdigest()


def _sev_current(c, kind):
    """{ref: (user id, username, org id | token id | None)} of everything of this kind that exists now."""
    if kind == "admin":
        q = "SELECT id, id, username, NULL FROM users WHERE is_admin=1 AND kind!='agent'"
    elif kind == "org_admin":
        q = ("SELECT m.org_id, m.user_id, u.username, m.org_id FROM org_members m JOIN users u ON u.id=m.user_id "
             "WHERE m.role='admin' AND u.is_admin=0 AND u.kind!='agent'")
    elif kind == "agent":
        q = "SELECT id, id, username, NULL FROM users WHERE kind='agent'"
    else:
        # the token's hash, not its id: a new token of an agent may get the id of the one it replaced
        q = "SELECT t.token_hash, t.user_id, u.username, t.id FROM api_tokens t JOIN users u ON u.id=t.user_id WHERE u.kind='agent'"
    return {(f"{r[0]}:{r[1]}" if kind == "org_admin" else str(r[0])[:32]): (r[1], r[2], r[3]) for r in c.execute(q).fetchall()}


SEV_TEXT = {"admin": N_("{0} is now an instance admin."),
            "org_admin": N_("{0} is now an admin of organisation #{1}."),
            "agent": N_("A new agent was added: {0}."),
            "agent_token": N_("A new token was created for agent {0} (token #{1}).")}


def _sev_reported(c, keys):
    """An alert with one of these keys is already waiting or was listed in the last day (the user routes and the sign-on
    sync report a new admin themselves, with who did it): the watch then only writes the log line."""
    with _AA_LOCK:
        if any(q[1] in keys for q in _AA["q"]):
            return True
    since = iso(now_utc() - timedelta(days=1))
    return bool(c.execute(f"SELECT 1 FROM admin_alerts WHERE kind='security' AND key IN ({','.join('?' * len(keys))}) AND created_at>?",
                          (*keys, since)).fetchone())


def sev_scan(c):
    """Watchdog: compares admins, org admins, agents and agent tokens with the last tick and reports the new ones."""
    now, new_agents = iso(now_utc()), set()
    for kind in SEV_KINDS:
        cur = _sev_current(c, kind)
        known = {r[0] for r in c.execute("SELECT ref FROM sev_known WHERE kind=?", (kind,)).fetchall()}
        baseline = "*" in known
        known.discard("*")
        new = [k for k in cur if k not in known]
        gone = [k for k in known if k not in cur]
        if not new and not gone and baseline:
            continue
        for ref in gone:  # someone who loses the role and gets it again is reported again
            c.execute("DELETE FROM sev_known WHERE kind=? AND ref=?", (kind, ref))
        for ref in new:
            c.execute("INSERT INTO sev_known(kind,ref,at) VALUES(?,?,?) ON CONFLICT(kind,ref) DO NOTHING", (kind, ref, now))
            if not baseline:
                continue
            uid, name, oid = cur[ref]
            if kind == "org_admin":
                args, ev = [name, oid], {"user_id": uid, "username": name, "org_id": oid}
            elif kind == "agent_token":
                args, ev = [name, oid], {"agent_id": uid, "username": name, "token_id": oid}
            else:
                args, ev = [name], {"user_id": uid, "username": name}
            if kind == "agent":
                new_agents.add(uid)
            if kind == "admin" and not known:  # the first admin of a new instance (first-run setup): nobody to tell
                pass
            elif kind == "agent_token" and uid in new_agents:  # the first token of a new agent: one alert (the agent)
                pass
            elif not (kind == "admin" and _sev_reported(c, [f"admin:{name}", f"oidc:admin:{name}:1"])):
                aa_now("security", f"sev:{kind}:{ref}", SEV_TEXT[kind], args)
            sev_log("new_" + kind, **ev)
        if not baseline:
            c.execute("INSERT INTO sev_known(kind,ref,at) VALUES(?,'*',?) ON CONFLICT(kind,ref) DO NOTHING", (kind, now))
    c.commit()


def sev_is_admin(c, uid):
    return bool(c.execute("SELECT 1 FROM users WHERE id=? AND kind!='agent' AND (is_admin=1 OR id IN "
                          "(SELECT user_id FROM org_members WHERE role='admin'))", (uid,)).fetchone())


def sev_login(c, uid, ip, via="password"):
    """A sign-in (start_session): an admin from an address not among their last SEV_IPS ones is reported. The first sign-in
    of an admin after the update only stores the address. Never raises (a sign-in never fails on this)."""
    try:
        if not ip or not sev_is_admin(c, uid):
            return
        h, now = sev_ip_hash(ip), iso(now_utc())
        rows = {r[0] for r in c.execute("SELECT ip_hash FROM admin_login_ips WHERE user_id=?", (uid,)).fetchall()}
        if h in rows:
            c.execute("UPDATE admin_login_ips SET last_at=? WHERE user_id=? AND ip_hash=?", (now, uid, h))
            c.commit()
            return
        c.execute("INSERT INTO admin_login_ips(user_id,ip_hash,first_at,last_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(user_id,ip_hash) DO UPDATE SET last_at=excluded.last_at", (uid, h, now, now))
        c.execute("DELETE FROM admin_login_ips WHERE user_id=? AND ip_hash NOT IN (SELECT ip_hash FROM admin_login_ips "
                  "WHERE user_id=? ORDER BY last_at DESC LIMIT ?)", (uid, uid, SEV_IPS))
        c.commit()
        if rows:
            name = (c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone() or [""])[0]
            aa_now("security", f"sev:login:{uid}:{h[:16]}", N_("Admin {0} signed in from a new address: {1}."), [name, ip])
            sev_log("admin_login_new_ip", user_id=uid, username=name, ip=ip, via=via)
    except Exception as e:  # noqa: BLE001
        print("admin sign-in check skipped:", type(e).__name__, e, flush=True)
