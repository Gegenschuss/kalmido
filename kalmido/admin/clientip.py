"""2.33.0 (#834): does the client's real address reach Kalmido? Behind a reverse proxy in Docker with published ports
(docker-proxy) every request seems to come from the Docker gateway (172.x.0.1): the sign-in lockout then hits everyone at
once and the logs are worthless. Kalmido remembers successful sign-ins from PRIVATE addresses (address + account + last
time, table login_ips, kept LOGIN_IP_DAYS days; public addresses are never stored) and warns -- in the server log (at
the start and when it first happens) and under Admin > Server -- when many different accounts sign in from exactly one
private address. Admin > Server also shows "Your IP" as the server sees it (self-test).
"""
import sys
import ipaddress
import os
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app, TRUSTED_PROXIES
from ..core.db import connect, db, iso, now_utc
from ..accounts.session import _ip_in, client_ip
from ..accounts.users import need_admin

LOGIN_IP_DAYS = 14
LOGIN_IP_WINDOW = 7  # days looked at
LOGIN_IP_MIN = max(2, int(os.environ.get("KALMIDO_IP_WARN_ACCOUNTS", "3") or 3))  # accounts from one address before it warns
LOGIN_IP_SHARE = 0.8  # ... and at least this share of all accounts that signed in during the window
_WARNED = set()


def ip_private(ip):
    try:
        a = ipaddress.ip_address((ip or "").split("%")[0])
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local


def login_seen(c, uid):
    """A successful sign-in (start_session): remember it when it came from a private address; warn once per address."""
    try:
        ip = client_ip()
        if not ip or not ip_private(ip):
            return
        now = now_utc()
        c.execute("INSERT INTO login_ips(ip,user_id,at) VALUES(?,?,?) ON CONFLICT(ip,user_id) DO UPDATE SET at=excluded.at", (ip, uid, iso(now)))
        c.execute("DELETE FROM login_ips WHERE at<?", (iso(now - timedelta(days=LOGIN_IP_DAYS)),))
        w = ip_warning(c)
    except Exception as e:  # noqa: BLE001 - no request (a script) or a database hiccup: a sign-in never fails on this
        print("client address check skipped:", type(e).__name__, e, flush=True)
        return
    if w and w["ip"] not in _WARNED:
        _WARNED.add(w["ip"])
        print(warn_text(w), file=sys.stderr, flush=True)  # stderr: the log, not the output of one-off commands


def ip_warning(c):
    """{ip, accounts, total} when many accounts sign in from exactly one private address, else None."""
    since = iso(now_utc() - timedelta(days=LOGIN_IP_WINDOW))
    rows = c.execute("SELECT ip, COUNT(DISTINCT user_id) AS n FROM login_ips WHERE at>=? GROUP BY ip ORDER BY n DESC", (since,)).fetchall()
    if not rows or rows[0]["n"] < LOGIN_IP_MIN:
        return None
    total = c.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE created_at>=?", (since,)).fetchone()[0]
    total = max(total, rows[0]["n"])
    if rows[0]["n"] < LOGIN_IP_SHARE * total:
        return None
    return {"ip": rows[0]["ip"], "accounts": rows[0]["n"], "total": total}


def warn_text(w):
    return (f"WARNING client addresses do not arrive: {w['accounts']} of {w['total']} accounts signed in from the one private "
            f"address {w['ip']} during the last {LOGIN_IP_WINDOW} days -- check the reverse proxy (Docker: run it with "
            "network_mode: host or \"userland-proxy\": false, and set KALMIDO_TRUSTED_PROXIES), see docs/SELF-HOSTING.md")


def ip_startup_check():
    c = connect()
    try:
        w = ip_warning(c)
        if w:
            _WARNED.add(w["ip"])
            print(warn_text(w), file=sys.stderr, flush=True)  # stderr: the log, not the output of one-off commands
    except Exception as e:  # noqa: BLE001 - a check never stops the start
        print("client address check skipped:", type(e).__name__, e, flush=True)
    finally:
        c.close()


@app.get("/api/admin/client-ip")
def admin_client_ip():
    """Admins: the address the server sees for this request, the direct peer (a proxy?) and whether it is trusted, and the
    warning when many accounts sign in from one private address."""
    need_admin()
    c = db()
    ip = client_ip()
    peer = (request.environ.get("kalmido.peer") or "")[:64]
    return jsonify(ip=ip, private=ip_private(ip), peer=peer, peer_trusted=_ip_in(peer, TRUSTED_PROXIES), via_proxy=bool(peer) and peer != ip,
                   trusted_proxies=[str(n) for n in TRUSTED_PROXIES], warning=ip_warning(c))
