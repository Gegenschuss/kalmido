"""2.141.0 A (#2141, #2138): the own mailbox of a workspace and sending from the e-mail filing (hub/hubmail.py).

Mailbox (hub_mailboxes, one per workspace: an organisation or a person's private space, ws like nl_conns): IMAP (server,
port, SSL, user, password, folder) and SMTP (server, port, TLS starttls | ssl | none, user, password, sender address +
name). Set up by the organisation's admins, a person for their own private space (a person without an organisation is
their own admin there). Both passwords are sealed with the server key (accounts/login.py seal, the purpose names the
workspace), never sent back (only "set"); an empty field keeps them -- unless the server or the port changes: the stored
password only ever goes to the server it was entered for. Servers are checked like calendar subscriptions (no internal
address unless the admin allowed the host, cal_allow). Errors are stored and shown as codes, never a server's text.

Fetching (mbx_loop, the round of KALMIDO_IMAP_INTERVAL): the unseen mails of every active mailbox -> the e-mail filing of
THAT workspace only, then \\Seen. Filing: a hub address (+token) of the same workspace as today; else an answer to a filed
mail of the workspace (In-Reply-To / References) goes to its client / project; else the sender is matched like the hub
inbox (the clients the receiving person sees) and otherwise waits "Not assigned" with the receiving person: the one who set
the mailbox up (an organisation: while still its admin, else its first admin). A Message-ID once per workspace (as before).
The mailbox feeds the e-mail filing only (no tasks by mail, no documents: those stay with the server's mailbox).

Sending (compose / send): a reply to a filed mail (to its sender, "Re: ...", In-Reply-To / References) or a new mail from
a client's / project's filing. Plain text only, no attachments in 2.141.0. Through the SMTP of the workspace of the mail /
client / project, else KALMIDO_SMTP_* when the server has it (sender = the server's address, Reply-To = the person's own),
else nothing (the dialog says why). The mail is filed first (direction out, send_state sending, the .eml in the file store),
then sent; a failure leaves it "failed" with a note (never a sent mail that was not). Who may: the write right on the mail /
the client / the project (hbm_can). Per person 30 mails an hour (through the server's SMTP also its daily e-mail limit). Agents and kid
accounts get nothing (no v1 route, no MCP tool in 2.141.0)."""
import email
import email.policy
import email.utils
import imaplib
import json
import re
import socket
import ssl
import threading
import time

from flask import g, jsonify, request

from ..core.config import EMAIL_RE, app
from ..core.pg import insert_id, system_ctx
from ..core.i18n import N_, lang, tr
from ..core.db import body, bump, db, err, iso, now_utc, connect
from ..core.access import Denied, WRITE_ROLES, acx_of, list_role, need_list
from ..accounts.session import me
from . import hubmail as H
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions

MBX_TLS = ("starttls", "ssl", "none")
MBX_MAIL_MAX = 50 * 1024 * 1024  # review: a larger mail of a workspace's own server is not fetched (marked seen)
MBX_BOX_S = 300         # 2.148.1 D (#2485): time one mailbox gets in a round before its connection is closed
MBX_SEND_HOUR = 30      # mails one person sends from the filing in an hour
MBX_RCPT = 20           # recipients of one mail (To + Cc)
MBX_TEXT_MAX = 100000   # characters of a mail's text
MBX_STALE_S = 600       # a mail still "sending" after this was never confirmed: shown as failed
MBX_PLAIN = N_("Without encryption only a server on this machine or in the local network can be used")


def mbx_local_host(host):
    """2.190.0 D (#2496): host is this machine or an address of the local network (every address it resolves to)."""
    import ipaddress
    h = (host or "").strip().rstrip(".").lower()
    if not h:
        return False
    if h == "localhost" or h.endswith(".localhost"):
        return True
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        return False
    cgnat = ipaddress.ip_network("100.64.0.0/10")  # 2.190.0 R (#2496): shared address space (carrier NAT, VPN meshes) counts as local
    try:
        return bool(addrs) and all((lambda a: a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in cgnat))(
            ipaddress.ip_address(x.split("%")[0])) for x in addrs)
    except ValueError:
        return False


_HOST_RE = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*\.?")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
MBX_ERR = {  # error code -> the text people see (never the server's own words: they may echo a user name)
    "auth": N_("The server refused the user name or the password"),
    "network": N_("The server cannot be reached (address or port wrong, or the server is down)"),
    "blocked": N_("This server is in the local network: an admin has to allow it first (Settings > Administration > Advanced, allowed internal hosts)"),
    "tls": N_("The encrypted connection failed (check SSL / TLS and the port)"),
    "folder": N_("The folder does not exist on the server"),
    "password": N_("The password is missing"),
    "other": N_("The server answered with an error"),
}
MBX_WAKE = threading.Event()
_DUE = set()  # workspaces whose mailbox is fetched in the next round (Fetch now)


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def _gate():
    u = g.user
    if u["kid"] or (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Only people can file e-mails"))


def _ws(c, raw):
    """'private' | 'org:<id>' -> (org or None, ws) with the right to manage that workspace's mailbox (403 / 404)."""
    from ..docs.web import ws_param
    _gate()
    return ws_param(c, raw, me(), manage=True)


def mbx_row(c, ws):
    return c.execute("SELECT * FROM hub_mailboxes WHERE ws=?", (ws,)).fetchone()


def _purpose(ws):
    return f"hub-mailbox:{ws}"


def mbx_secret(c, r):
    """{imap, smtp} -- the plain passwords of a mailbox row ({} when they cannot be opened)."""
    from ..accounts.login import unseal
    if not r or not r["secret"]:
        return {}
    try:
        v = json.loads(unseal(c, _purpose(r["ws"]), r["secret"]))
    except Exception:  # noqa: BLE001 -- another server key / a broken value: as if none were set
        return {}
    return v if isinstance(v, dict) else {}


def _seal(c, ws, secret):
    from ..accounts.login import seal
    secret = {k: v for k, v in secret.items() if v}
    return seal(c, _purpose(ws), json.dumps(secret)) if secret else ""


def mbx_err_text(code, lg=None):
    return tr(MBX_ERR.get(code) or MBX_ERR["other"], lg=lg) if code else ""


def _err_code(e):
    from ..calendars.subscriptions import CalError
    import smtplib
    if isinstance(e, _AuthFailed):
        return "auth"
    if isinstance(e, CalError):
        return "blocked" if e.code == "blocked" else "network"
    if isinstance(e, (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError)):
        return "auth"
    if isinstance(e, ssl.SSLError):
        return "tls"
    if isinstance(e, imaplib.IMAP4.error):
        return "folder" if "select" in str(e).lower() else "other"
    if isinstance(e, (socket.gaierror, socket.timeout, ConnectionError, TimeoutError)):
        return "network"
    if isinstance(e, smtplib.SMTPException):
        return "other"
    if isinstance(e, OSError):
        return "network"
    return "other"


def _folder_arg(folder):
    return f'"{folder}"' if re.search(r'[\s()]', folder) else folder


# ---- the connections (every address checked, calendars/subscriptions.py) ------------------------------------------------
class _SafeIMAP(imaplib.IMAP4):
    def __init__(self, host, port, timeout, allow):
        self._kal_allow = allow
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        from ..calendars.subscriptions import _cal_connector
        return _cal_connector(self._kal_allow)((self.host, self.port), timeout)


class _SafeIMAP_SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port, timeout, allow):
        self._kal_allow = allow
        super().__init__(host, port, timeout=timeout, ssl_context=ssl.create_default_context())  # review: certificate checked

    def _create_socket(self, timeout):
        from ..calendars.subscriptions import _cal_connector
        return self.ssl_context.wrap_socket(_cal_connector(self._kal_allow)((self.host, self.port), timeout), server_hostname=self.host)


def _allow(c):
    from ..calendars.subscriptions import cal_allow
    return cal_allow(c)


def _imap_open(c, r, secret, timeout=30, allow=None):
    pw = secret.get("imap") or ""
    if not pw:
        raise _NoPassword()
    port = int(r["imap_port"] or 0) or (993 if r["imap_ssl"] else 143)
    M = (_SafeIMAP_SSL if r["imap_ssl"] else _SafeIMAP)(r["imap_host"], port, timeout, _allow(c) if allow is None else allow)
    try:
        M.login(r["imap_user"], pw)
    except BaseException as e:
        try:
            M.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if isinstance(e, imaplib.IMAP4.error) and not isinstance(e, imaplib.IMAP4.abort):
            raise _AuthFailed() from None  # the server's own words may echo the user name: never kept
        raise
    return M


class _NoPassword(Exception):
    pass


class _AuthFailed(Exception):
    pass


def mbx_smtp(c, r, secret=None):
    """The SMTP access of mailbox row r for integrations/mail.py mail_send / mail_deliver (smtp=...), None without SMTP."""
    if not r or not r["smtp_host"] or not r["from_addr"]:
        return None
    secret = mbx_secret(c, r) if secret is None else secret
    return {"host": r["smtp_host"], "port": int(r["smtp_port"] or 0), "tls": r["smtp_tls"] or "starttls", "user": r["smtp_user"],
            "password": secret.get("smtp") or "", "from": r["from_addr"], "allow": _allow(c)}


def mbx_check(c, r, secret=None):
    """{imap: code | '' | None (not set up), smtp: ...} -- IMAP login + the folder, SMTP login; nothing is sent."""
    from ..integrations.mail import smtp_open
    secret = mbx_secret(c, r) if secret is None else secret
    out = {"imap": None, "smtp": None}
    if r["imap_host"]:
        try:
            M = _imap_open(c, r, secret)
            try:
                typ, _ = M.select(_folder_arg(r["imap_folder"] or "INBOX"))
                out["imap"] = "" if typ == "OK" else "folder"
            finally:
                try:
                    M.logout()
                except Exception:  # noqa: BLE001
                    pass
        except _NoPassword:
            out["imap"] = "password"
        except Exception as e:  # noqa: BLE001
            out["imap"] = _err_code(e)
    cfg = mbx_smtp(c, r, secret)
    if cfg:
        if cfg["user"] and not cfg["password"]:
            out["smtp"] = "password"
        else:
            try:
                S_ = smtp_open(cfg)
                try:
                    S_.quit()
                except Exception:  # noqa: BLE001
                    pass
                out["smtp"] = ""
            except Exception as e:  # noqa: BLE001
                out["smtp"] = _err_code(e)
    return out


def mbx_take_values(src):
    """2.144.5 B (#2410): the settings of a mailbox row from an export (organisation export / account export; untrusted) as
    columns, checked like mbx_put. The passwords never come with an export: secret stays empty and error "password" makes the
    settings ask for them again (nothing is fetched or sent until then). None = neither a server for receiving nor for sending."""
    if not isinstance(src, dict):
        return None
    v = {}
    for k, n in (("imap_host", 253), ("smtp_host", 253), ("imap_user", 300), ("smtp_user", 300), ("from_name", 120), ("from_addr", 254),
                 ("imap_folder", 200)):
        x = src.get(k)
        x = x.strip() if isinstance(x, str) else ""
        v[k] = "" if len(x) > n or _CTRL.search(x) else x
    for k in ("imap_host", "smtp_host"):
        v[k] = v[k].lower().rstrip(".")
        if v[k] and not _HOST_RE.fullmatch(v[k]):
            v[k] = ""
    if not v["imap_folder"] or '"' in v["imap_folder"] or "\\" in v["imap_folder"]:
        v["imap_folder"] = "INBOX"
    if v["from_addr"] and not EMAIL_RE.fullmatch(v["from_addr"]):
        v["from_addr"] = ""
    for k in ("imap_port", "smtp_port"):
        x = src.get(k)
        v[k] = x if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 65535 else 0
    v["imap_ssl"] = 0 if src.get("imap_ssl") in (0, False) else 1
    # 2.144.5 A2 (#2410, review R6): switched off until the passwords are entered again (_sender takes the server's SMTP
    # meanwhile, the poller leaves it alone); the person switches it on in the settings
    v["active"] = 0
    v["smtp_tls"] = src.get("smtp_tls") if src.get("smtp_tls") in MBX_TLS else "starttls"
    if not v["imap_host"] and not v["smtp_host"]:
        return None
    v.update(secret="", error="password", error_at=_now(), polled_at=None)
    return v


# ---- the settings ---------------------------------------------------------------------------------------------------------
def _public(c, ws, org, r=None, check=None):
    r = r if r is not None else mbx_row(c, ws)
    lg = lang(c, me())
    out = {"ws": f"org:{org}" if org else "private", "box": None}
    if check is not None:
        out["check"] = {k: {"ok": v == "", "code": v, "text": mbx_err_text(v, lg)} for k, v in check.items() if v is not None}
    if not r:
        return out
    sec = mbx_secret(c, r)
    out["box"] = {"active": bool(r["active"]), "imap_host": r["imap_host"], "imap_port": int(r["imap_port"] or 0),
                  "imap_ssl": bool(r["imap_ssl"]), "imap_user": r["imap_user"], "imap_folder": r["imap_folder"],
                  "imap_password_set": bool(sec.get("imap")), "smtp_host": r["smtp_host"], "smtp_port": int(r["smtp_port"] or 0),
                  "smtp_tls": r["smtp_tls"], "smtp_user": r["smtp_user"], "smtp_password_set": bool(sec.get("smtp")),
                  "from_addr": r["from_addr"], "from_name": r["from_name"], "polled_at": r["polled_at"], "error": r["error"],
                  "error_text": mbx_err_text(r["error"], lg), "error_at": r["error_at"]}
    return out


@app.get("/api/hubmail/mailboxes")
def mbx_list():
    """The workspaces I belong to with their mailbox: manage = I may set it up (details only then), set, active, address."""
    c = db()
    _gate()
    uid = me()
    from ..accounts.orgs import is_org_admin
    spaces = [(None, tr("Private|workspace"))]
    for oid in sorted(acx_of(c, uid).org_ids):
        o = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        if o and not o["personal_of"]:
            spaces.append((oid, o["name"]))
    lg = lang(c, uid)
    out = []
    for oid, name in spaces:
        ws = H._ws(oid, uid)
        r = mbx_row(c, ws)
        manage = not oid or is_org_admin(c, uid, oid)
        d = {"ws": f"org:{oid}" if oid else "private", "name": name, "manage": manage, "set": bool(r),
             "active": bool(r and r["active"]), "send": bool(r and r["smtp_host"] and r["from_addr"]),
             "receive": bool(r and r["imap_host"]), "address": (r["from_addr"] or r["imap_user"]) if r else ""}
        if manage and r:
            d.update(error=r["error"], error_text=mbx_err_text(r["error"], lg), polled_at=r["polled_at"])
        out.append(d)
    from ..integrations.mail import MAIL_OUT_ON
    return jsonify(spaces=out, server_send=MAIL_OUT_ON)


@app.get("/api/hubmail/mailbox")
def mbx_get():
    """?ws= -- the mailbox of a workspace (never the passwords: only *_password_set)."""
    c = db()
    org, ws = _ws(c, request.args.get("ws"))
    return jsonify(_public(c, ws, org))


def _s(d, k, n, cur, empty=True):
    """A string field of d (else cur): stripped, at most n characters, no control characters; None = invalid."""
    if k not in d:
        return cur
    v = d[k]
    if v is None:
        v = ""
    if not isinstance(v, str) or len(v.strip()) > n or _CTRL.search(v) or (not empty and not v.strip()):
        return None
    return v.strip()


def _port(d, k, cur):
    if k not in d:
        return cur
    v = d[k]
    if v in (None, ""):
        return 0
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535:
        return None
    return v


@app.put("/api/hubmail/mailbox")
def mbx_put():
    """{ws, active?, imap_host?, imap_port?, imap_ssl?, imap_user?, imap_password?, imap_folder?, smtp_host?, smtp_port?,
    smtp_tls?, smtp_user?, smtp_password?, from_addr?, from_name?, check?} -- sets up / changes the mailbox. An empty or
    missing password keeps the stored one (not when the server / port changes). check = then log in to both (nothing sent)."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    org, ws = _ws(c, d.get("ws"))
    known = {"ws", "active", "imap_host", "imap_port", "imap_ssl", "imap_user", "imap_password", "imap_folder", "smtp_host", "smtp_port",
             "smtp_tls", "smtp_user", "smtp_password", "from_addr", "from_name", "check"}
    unknown = sorted(set(d) - known)
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    r = mbx_row(c, ws)
    cur = dict(r) if r else {"active": 1, "imap_host": "", "imap_port": 0, "imap_ssl": 1, "imap_user": "", "imap_folder": "INBOX",
                             "smtp_host": "", "smtp_port": 0, "smtp_tls": "starttls", "smtp_user": "", "from_addr": "", "from_name": ""}
    v = {}
    for k, n in (("imap_host", 253), ("smtp_host", 253), ("imap_user", 300), ("smtp_user", 300), ("from_name", 120), ("from_addr", 254)):
        v[k] = _s(d, k, n, cur[k])
        if v[k] is None:
            return err(tr("Invalid value: {0}", k))
    v["imap_folder"] = _s(d, "imap_folder", 200, cur["imap_folder"])
    if v["imap_folder"] is None or '"' in v["imap_folder"] or "\\" in v["imap_folder"]:
        return err(tr("Invalid value: {0}", "imap_folder"))
    v["imap_folder"] = v["imap_folder"] or "INBOX"
    for k in ("imap_host", "smtp_host"):
        v[k] = v[k].lower().rstrip(".")
        if v[k] and not _HOST_RE.fullmatch(v[k]):
            return err(tr("Invalid value: {0}", k))
    for k in ("imap_port", "smtp_port"):
        v[k] = _port(d, k, int(cur[k] or 0))
        if v[k] is None:
            return err(tr("Invalid value: {0}", k))
    for k in ("imap_ssl", "active"):
        if k in d and not isinstance(d[k], bool):
            return err(tr("Invalid value: {0}", k))
        v[k] = (1 if d[k] else 0) if k in d else int(cur[k])
    v["smtp_tls"] = d.get("smtp_tls", cur["smtp_tls"])
    if v["smtp_tls"] not in MBX_TLS:
        return err(tr("Invalid value: {0}", "smtp_tls"))
    # 2.190.0 D (#2496): without encryption only to a server of the own machine / local network (a changed setting; a
    # mailbox stored before keeps working as it is)
    if v["imap_host"] and not v["imap_ssl"] and not (r and r["imap_host"] == v["imap_host"] and not r["imap_ssl"]) \
            and not mbx_local_host(v["imap_host"]):
        return err(tr(MBX_PLAIN))
    if v["smtp_host"] and v["smtp_tls"] == "none" and not (r and r["smtp_host"] == v["smtp_host"] and r["smtp_tls"] == "none") \
            and not mbx_local_host(v["smtp_host"]):
        return err(tr(MBX_PLAIN))
    if v["from_addr"] and not EMAIL_RE.fullmatch(v["from_addr"]):
        return err(tr("Invalid value: {0}", tr("Sender address")))
    if v["smtp_host"] and not v["from_addr"]:
        return err(tr("Please enter the sender address"))
    if v["imap_host"] and not v["imap_user"]:
        return err(tr("Please enter the user name of the mailbox"))
    if not v["imap_host"] and not v["smtp_host"]:
        return err(tr("Please enter a server for receiving or for sending"))
    # the stored passwords only ever go to the server they were entered for
    old = mbx_secret(c, r) if r else {}
    secret = {}
    for p, host, port in (("imap", "imap_host", "imap_port"), ("smtp", "smtp_host", "smtp_port")):
        same = r and v[host] == r[host] and v[port] == int(r[port] or 0) and (v["imap_ssl"] == int(r["imap_ssl"]) if p == "imap" else v["smtp_tls"] == r["smtp_tls"])
        secret[p] = old.get(p, "") if same else ""
        k = p + "_password"
        if k in d and d[k] not in (None, ""):
            pw = d[k]
            if not isinstance(pw, str) or len(pw) > 400 or _CTRL.search(pw):
                return err(tr("Invalid value: {0}", k))
            secret[p] = pw
        if not v[host]:
            secret[p] = ""
    if v["imap_host"] and not secret["imap"]:
        return err(tr("Please enter the password of the mailbox"))
    ts = _now()
    sealed = _seal(c, ws, secret)
    cols = ("active", "imap_host", "imap_port", "imap_ssl", "imap_user", "imap_folder", "smtp_host", "smtp_port", "smtp_tls", "smtp_user",
            "from_addr", "from_name")
    if r:
        c.execute(f"UPDATE hub_mailboxes SET {', '.join(k + '=?' for k in cols)}, secret=?, error='', error_at=NULL, updated_at=? WHERE id=?",
                  (*[v[k] for k in cols], sealed, ts, r["id"]))
    else:
        c.execute(f"INSERT INTO hub_mailboxes(org_id, owner_id, ws, {', '.join(cols)}, secret, created_by, created_at, updated_at) "
                  f"VALUES(?,?,?,{','.join('?' * len(cols))},?,?,?,?)", (org, None if org else me(), ws, *[v[k] for k in cols], sealed, me(), ts, ts))
    c.commit()
    r = mbx_row(c, ws)
    chk = None
    if d.get("check") is True and not hit_limit(f"mbxcheck:{me()}", 20, 600):  # review: the same limit as /mailbox/check
        chk = mbx_check(c, r, secret)
        code = chk.get("imap") or chk.get("smtp") or ""
        c.execute("UPDATE hub_mailboxes SET error=?, error_at=? WHERE id=?", (code, ts if code else None, r["id"]))
        c.commit()
        r = mbx_row(c, ws)
    return jsonify(_public(c, ws, org, r, chk))


@app.post("/api/hubmail/mailbox/check")
def mbx_check_route():
    """{ws} -- logs in to the stored IMAP + SMTP (nothing is sent); the result with a text without any secret."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    org, ws = _ws(c, d.get("ws"))
    r = mbx_row(c, ws)
    if not r:
        raise Denied(404, tr("No mailbox is set up"))
    if hit_limit(f"mbxcheck:{me()}", 20, 600):
        return err(tr("Too many tests, please wait a few minutes"), 429)
    chk = mbx_check(c, r)
    code = chk.get("imap") or chk.get("smtp") or ""
    c.execute("UPDATE hub_mailboxes SET error=?, error_at=? WHERE id=?", (code, _now() if code else None, r["id"]))
    c.commit()
    return jsonify(_public(c, ws, org, None, chk))


@app.delete("/api/hubmail/mailbox")
def mbx_del():
    """?ws= -- the mailbox goes (its passwords with it); the filed mails stay."""
    c = db()
    org, ws = _ws(c, request.args.get("ws"))
    c.execute("DELETE FROM hub_mailboxes WHERE ws=?", (ws,))
    c.commit()
    return jsonify(_public(c, ws, org))


@app.post("/api/hubmail/mailbox/poll")
def mbx_poll_now():
    """{ws} -- fetch this mailbox now (instead of waiting for the next round)."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    _org, ws = _ws(c, d.get("ws"))
    r = mbx_row(c, ws)
    if not r or not r["imap_host"]:
        raise Denied(404, tr("No mailbox is set up"))
    _DUE.add(ws)
    MBX_WAKE.set()
    return jsonify(ok=True)


# ---- fetching -----------------------------------------------------------------------------------------------------------
def mbx_holder(c, r):
    """The person a mailbox receives for ("Not assigned" waits with them): the private space's person; an organisation's:
    the one who set it up while an admin there, else its first admin. None = nobody (the mailbox is not fetched)."""
    from ..accounts.orgs import is_org_admin

    def person(uid):
        u = c.execute("SELECT disabled, kind, kid FROM users WHERE id=?", (uid,)).fetchone() if uid else None
        return bool(u) and not u["disabled"] and not u["kid"] and (u["kind"] or "user") != "agent"
    if not r["org_id"]:
        return r["owner_id"] if person(r["owner_id"]) else None
    oid = int(r["org_id"])
    if r["created_by"] and person(r["created_by"]) and is_org_admin(c, r["created_by"], oid):
        return r["created_by"]
    for (uid,) in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role='admin' ORDER BY user_id", (oid,)).fetchall():
        if person(uid):
            return uid
    return None


def _refs(msg):
    ids = []
    for h in ("In-Reply-To", "References"):
        for x in re.findall(r"<[^<>\s]{1,290}>", " ".join(str(v) for v in msg.get_all(h, []))):
            if x not in ids:
                ids.append(x)
    return ids[-30:]


def _parts(d):
    """The addresses of an opened hub mail (its sender and recipients), lower case."""
    return {a.strip().lower() for _n, a in email.utils.getaddresses([d.get("from_addr") or "", d.get("to_addrs") or ""]) if a.strip()}


def _took_part(c, m, frm):
    """2.360.0 C (#2496): the sender of an answer took part in the filed mail m (its sender or a recipient, Cc included).
    2.360.0 R (#2496, review): or is a known address of m's client (its own, a contact person's, a linked contact's)."""
    if frm in _parts(H._open(c, m)):
        return True
    return bool(m["client_id"]) and frm in {a["address"].lower() for a in _client_addrs(c, m["client_id"])}


def mbx_import(c, box, raw):
    """One mail of workspace mailbox box -> the e-mail filing of box's workspace (never another one). Returns the mail id,
    0 when it was not filed (a double, nobody to receive)."""
    from ..integrations.mail import MAIL_TOKEN_RE, mail_text
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    org, ws = box["org_id"] or None, box["ws"]
    with system_ctx(c):  # the background round: the rights are checked here (holder, workspace), like hbm_mail_import
        holder = mbx_holder(c, box)
        if not holder:
            return 0

        def fits(kind, uid, oid, cid, lid):
            ok = H._holder_ok(c, kind, uid, oid, cid, lid)
            return bool(ok) and (ok[0] or None) == org and H._ws(ok[0], uid) == ws
        r = None
        hdrs = " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))
        for t in MAIL_TOKEN_RE.findall(hdrs):  # a hub address of this workspace (another workspace's token counts as none)
            x = c.execute("SELECT * FROM hub_tokens WHERE token=?", (t,)).fetchone()
            if x and fits(x["kind"], x["user_id"], x["org_id"], x["client_id"], x["list_id"]):
                r = dict(x)
                break
        refs = _refs(msg) if r is None else []
        if refs:  # an answer to a filed mail of this workspace: its client / project
            q = ",".join("?" * len(refs))
            # 2.360.0 C (#2496): only when the sender took part in that mail (its sender or a recipient): a known Message-ID
            # alone does not file foreign content with the client / project
            frm = email.utils.parseaddr(str(msg.get("From") or ""))[1].strip().lower()
            p = next((x for x in c.execute(f"SELECT * FROM hub_mails WHERE ws=? AND message_id IN ({q}) AND deleted_at IS NULL AND "
                                           "(client_id IS NOT NULL OR list_id IS NOT NULL) ORDER BY id DESC LIMIT 30", (ws, *refs)).fetchall()
                      if frm and _took_part(c, x, frm)), None)
            if p:
                kind = "list" if p["list_id"] else "client"
                for uid in [x for x in (p["owner_id"], holder) if x]:
                    if fits(kind, uid, org, p["client_id"], p["list_id"]):
                        r = {"kind": kind, "user_id": uid, "org_id": org, "client_id": p["client_id"], "list_id": p["list_id"], "token": ""}
                        break
        if r is None:  # matched by the sender like the hub inbox, else "Not assigned" with the holder
            r = {"kind": "inbox", "user_id": holder, "org_id": org, "client_id": None, "list_id": None, "token": ""}
        out = H._import(c, r, msg, raw, mail_text)
    c.commit()
    return out


def _bg(fn):
    """fn(c) with a connection of its own inside the background gate (never nested: the IMAP session runs outside it)."""
    from ..accounts.session import GATE
    with GATE.bg():
        c = connect()
        try:
            return fn(c)
        finally:
            c.close()


def mbx_poll_one(box, hold=None):
    """Fetch one mailbox (a row as dict); stores polled_at / the error code. Returns how many mails were filed.
    hold (2.148.1 D, #2485): a list that gets the open connection, so the round can close it after its time."""
    from ..integrations.mail import mail_fetch
    n, code = 0, ""
    try:
        secret, allow = _bg(lambda c: (mbx_secret(c, box), _allow(c)))
        M = _imap_open(None, box, secret, allow=allow)
        if hold is not None:
            hold.append(M)
        try:
            n = mail_fetch(M, _folder_arg(box["imap_folder"] or "INBOX"), lambda c2, raw: mbx_import(c2, box, raw), max_bytes=MBX_MAIL_MAX,
                           box=f"mbx:{box['id']}")  # 2.193.0 D (#2220)
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass
    except _NoPassword:
        code = "password"
    except Exception as e:  # noqa: BLE001
        code = "folder" if isinstance(e, imaplib.IMAP4.error) and "select" in str(e).lower() else _err_code(e)
        print("mailbox: ws", box["ws"], type(e).__name__, flush=True)

    def done(c):
        with system_ctx(c):
            c.execute("UPDATE hub_mailboxes SET polled_at=?, error=?, error_at=? WHERE id=?",
                      (_now(), code, _now() if code else None, box["id"]))
        c.commit()
    _bg(done)
    return n


def mbx_poll_all(only=None):
    """One round over the active mailboxes (only = a set of ws: just those)."""
    def boxes(c):
        with system_ctx(c):
            out = [dict(x) for x in c.execute("SELECT * FROM hub_mailboxes WHERE active=1 AND imap_host<>'' ORDER BY id").fetchall()]
        c.commit()
        return out
    n = 0
    for box in _bg(boxes):
        if only is not None and box["ws"] not in only:
            continue
        n += _poll_in_time(box)
    return n


def _poll_in_time(box):
    """2.148.1 D (#2485): one mailbox in a thread of its own with MBX_BOX_S seconds: a slow server is cut off (its socket
    closed) and the round goes on with the next mailbox."""
    out, hold = [0], []

    def run():
        try:
            out[0] = mbx_poll_one(box, hold)
        except Exception as e:  # noqa: BLE001 -- one mailbox never stops the others
            print("mailbox:", type(e).__name__, flush=True)  # 2.240.0 A (#2883): no message text (addresses)
    t = threading.Thread(target=run, name="mailbox-poll", daemon=True)
    t.start()
    t.join(MBX_BOX_S)
    if t.is_alive():
        print("mailbox: ws", box["ws"], "over time, cut off", flush=True)
        for M in hold:
            try:
                M.shutdown()
            except Exception:  # noqa: BLE001
                pass
        t.join(10)
    return out[0]


def mbx_loop():
    from ..integrations.mail import IMAP
    last = 0.0
    while True:
        due = set(_DUE)
        _DUE.difference_update(due)
        full = time.time() - last >= IMAP["interval"]
        try:
            if full:
                last = time.time()
                mbx_poll_all()
            elif due:
                mbx_poll_all(due)
        except Exception as e:  # noqa: BLE001
            print("mailbox:", type(e).__name__, flush=True)  # 2.240.0 A (#2883)
        MBX_WAKE.wait(max(1.0, IMAP["interval"] - (time.time() - last)))
        MBX_WAKE.clear()


# ---- sending -------------------------------------------------------------------------------------------------------------
def _sender(c, org, uid):
    """(smtp access or None = the server's KALMIDO_SMTP_*, from name, reply_to, via) for sending in workspace org as uid;
    via '' = no way to send."""
    from ..integrations.mail import MAIL_OUT_ON
    box = mbx_row(c, H._ws(org, uid))
    u = c.execute("SELECT display_name, username, email FROM users WHERE id=?", (uid,)).fetchone()
    name = (u["display_name"] or u["username"] or "").strip() if u else ""
    if box and box["active"] and box["smtp_host"] and box["from_addr"]:
        return mbx_smtp(c, box), (box["from_name"] or name), None, "workspace"
    if MAIL_OUT_ON:
        own = (u["email"] or "").strip() if u else ""
        return None, name, (own if own and EMAIL_RE.fullmatch(own) else None), "server"
    return None, "", None, ""


def _context(c, src):
    """(org, client_id, list_id, the mail answered or None) of a compose / send request: {reply} | {client_id} | {list_id};
    the write right checked (hbm_can)."""
    uid = me()
    for k in ("reply", "client_id", "list_id"):
        v = src.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise Denied(400, tr("Invalid value: {0}", k))
    if src.get("reply"):
        m = H._need_mail(c, src["reply"], write=True)
        return m["org_id"] or None, m["client_id"], m["list_id"], m
    if src.get("list_id"):
        need_list(c, src["list_id"])
        l = H._list_row(c, src["list_id"])
        if l["no_mail"] or l["e2e"] or list_role(c, l["id"], uid) not in WRITE_ROLES:  # 2.352.0 G (#2752, review M5)
            raise Denied(403)
        cid = None
        if l["client_id"]:
            cl = H._visible_client(c, uid, l["client_id"])
            cid = cl["id"] if cl and (cl["org_id"] or None) == (l["org_id"] or None) else None
        return l["org_id"] or None, cid, l["id"], None
    if src.get("client_id"):
        cl = H._visible_client(c, uid, src["client_id"])
        if not cl:
            raise Denied(404)
        return cl["org_id"] or None, cl["id"], None, None
    raise Denied(400, tr("Invalid data"))


def _client_addrs(c, cid):
    """The e-mail addresses of a client: its own, its contact persons', the linked address book contacts' (in this order)."""
    if not cid:
        return []
    out = []

    def add(name, a):
        a = (a or "").strip()
        if a and EMAIL_RE.fullmatch(a) and a.lower() not in {x["address"].lower() for x in out}:
            out.append({"name": (name or "").strip()[:120], "address": a[:254]})
    r = c.execute("SELECT name, email FROM clients WHERE id=?", (cid,)).fetchone()
    if r:
        for a in H.ADDR_RE.findall(r["email"] or ""):
            add(r["name"], a)
    links = []
    for x in c.execute("SELECT name, email, contact_id FROM office_client_contacts WHERE client_id=? ORDER BY id", (cid,)).fetchall():
        add(x["name"], x["email"])
        if x["contact_id"]:
            links.append(x["contact_id"])
    for ctid in links[:50]:
        ct = c.execute("SELECT fn, given, family, emails FROM contacts WHERE id=?", (ctid,)).fetchone()
        if not ct:
            continue
        try:
            em = json.loads(ct["emails"] or "[]")
        except ValueError:
            em = []
        nm = (ct["fn"] or f"{ct['given']} {ct['family']}").strip()
        for e in em if isinstance(em, list) else []:
            if isinstance(e, dict):
                add(nm, str(e.get("value") or ""))
    return out[:30]


def _re_subject(s):
    s = (s or "").strip()
    return s if re.match(r"^\s*(re|aw|sv|antw)\s*:", s, re.I) else (f"Re: {s}" if s else "Re:")


def _quote(c, m, d):
    when = m["sent_at"] or m["created_at"] or ""
    who = d["from_name"] or d["from_addr"] or ""
    lines = (d["body"] or "").strip().split("\n")[:200]
    head = tr("On {0}, {1} wrote:", when[:16].replace("T", " "), who, lg=lang(c, me()))
    return "\n\n" + head + "\n" + "\n".join("> " + x for x in lines)


@app.get("/api/hubmail/compose")
def mbx_compose():
    """?reply=<mail id> | ?client_id= | ?list_id= -- what the writing dialog starts with: can_send, via (workspace | server |
    ''), the sender, suggested recipients, subject and the quoted text of a reply."""
    c = db()
    _gate()
    a = {}
    for k in ("reply", "client_id", "list_id"):
        if request.args.get(k):
            try:
                a[k] = int(request.args.get(k))
            except ValueError:
                raise Denied(400, tr("Invalid value: {0}", k)) from None
    org, cid, lid, m = _context(c, a)
    smtp, name, reply_to, via = _sender(c, org, me())
    from ..integrations.mail import SMTP
    frm = smtp["from"] if smtp else SMTP["from"] if via == "server" else ""
    out = {"can_send": bool(via), "via": via, "from": {"name": name, "address": frm}, "reply_to": reply_to or "",
           "to": [], "subject": "", "text": "", "client_id": cid, "list_id": lid, "reply": m["id"] if m else None}
    if m:
        d = H._open(c, m)
        if m["direction"] == "out":  # a reply to an own sent mail goes to its recipients again
            out["to"] = [{"name": "", "address": x} for x in H.ADDR_RE.findall(d["to_addrs"] or "")][:MBX_RCPT]
        elif d["from_addr"]:
            out["to"] = [{"name": d["from_name"] or "", "address": d["from_addr"]}]
        out["subject"] = _re_subject(d["subject"])
        out["text"] = _quote(c, m, d)
    out["suggest"] = _client_addrs(c, cid)
    if not via:
        out["hint"] = tr("Sending is not set up: an admin of the workspace enters the mailbox's SMTP access (E-mail filing > Mailbox).")
    return jsonify(out)


def _addr_list(v):
    """'a@x, B <b@y>' or a list of those -> ['a@x', 'b@y'] (each a valid address) or None."""
    if v in (None, "", []):
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v) or sum(len(x) for x in v) > 6000 or any(_CTRL.search(x) for x in v):
        return None  # a line break could smuggle in a header
    out = []
    for name, a in email.utils.getaddresses(v):
        a = a.strip()
        if not a:
            continue
        if not EMAIL_RE.fullmatch(a) or _CTRL.search(a) or "," in a or len(a) > 254:
            return None
        if a.lower() not in {x.lower() for x in out}:
            out.append(a)
    return out


def _file_sent(c, uid, org, cid, lid, ws, m, raw, plain):
    """The sent mail into hub_mails (direction out, sending) + its .eml in the file store; returns the row id."""
    from ..files.store import fs_folder, fs_put
    from ..files.upsafe import UploadRefused
    from ..admin.hosting import QuotaExceeded
    ts = _now()
    enc, sealed = H.hbm_seal(c, org, uid, ws, plain)  # 2.306.0 A (#2885): private ones sealed, too
    mid = insert_id(c, """INSERT INTO hub_mails(org_id,owner_id,client_id,list_id,ws,message_id,from_addr,from_name,to_addrs,subject,
                          sent_at,body,created_at,direction,send_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'out','sending')""",
                    (org, uid, cid, lid, ws, str(m["Message-ID"])[:300], enc["from_addr"], enc["from_name"], enc["to_addrs"],
                     enc["subject"], ts, enc["body"], ts))
    lg = lang(c, uid)
    cn, ln = H._names(c, cid, lid)
    folder, eml_id, notes = None, None, []
    try:
        with c.savepoint():
            label = tr("E-mail", lg=lg) + f" {mid}" if sealed else (plain["subject"] or tr("E-mail", lg=lg))
            folder = fs_folder(c, uid, org, [H.ROOT, cn or ln or tr("Not assigned", lg=lg), f"{ts[:10]} {label}"[:120]])
        name = ("mail" if sealed else re.sub(r"[\\/:*?\"<>|]+", "-", plain["subject"])[:60].strip() or "mail") + ".eml"
        with c.savepoint():
            eml_id = fs_put(c, uid, folder, name, raw, "message/rfc822", org)
    except (Denied, ValueError, UploadRefused, QuotaExceeded) as e:
        print("hubmail: sent mail without .eml", type(e).__name__, flush=True)
        notes.append(tr("The original mail and its attachments could not be filed", lg=lg))
    if eml_id:  # 2.148.1 G (#2488): the filed nodes follow the mail's rights, as for received mail
        c.execute("UPDATE fs_nodes SET hub_mail_id=? WHERE id=?", (mid, eml_id))
    if folder:
        c.execute("UPDATE fs_nodes SET hub_mail_id=? WHERE id=? AND hub_mail_id IS NULL", (mid, folder))
    c.execute("UPDATE hub_mails SET folder_id=?, eml_id=?, note=? WHERE id=?", (folder, eml_id, "\n".join(notes)[:2000], mid))
    H._index(c, mid, ws, plain)
    return mid


@app.post("/api/hubmail/send")
def mbx_send():
    """{reply | client_id | list_id, to, cc?, subject, text} -- sends a plain text mail through the workspace's SMTP (else
    the server's) and files it with the mail's / the client's / the project's mails (direction out). 201 {mail}; a failure
    = 502 {error, mail} (the filed mail is marked failed)."""
    c = db()
    _gate()
    uid = me()
    b = body() if isinstance(body(), dict) else {}
    unknown = sorted(set(b) - {"reply", "client_id", "list_id", "to", "cc", "subject", "text"})
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    org, cid, lid, m0 = _context(c, b)
    to, cc = _addr_list(b.get("to")), _addr_list(b.get("cc"))
    if to is None or cc is None:
        return err(tr("Invalid value: {0}", tr("Recipient")))
    if not to:
        return err(tr("Please enter a recipient"))
    if len(to) + len(cc) > MBX_RCPT:
        return err(tr("At most {0} recipients", MBX_RCPT))
    subj = b.get("subject")
    text = b.get("text")
    if not isinstance(subj, str) or len(subj) > 300 or not isinstance(text, str) or len(text) > MBX_TEXT_MAX:
        return err(tr("Invalid data"))
    subj = re.sub(r"\s+", " ", _CTRL.sub(" ", subj)).strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not subj and not text.strip():
        return err(tr("The mail is empty"))
    smtp, name, reply_to, via = _sender(c, org, uid)
    if not via:
        return jsonify(error=tr("Sending is not set up: an admin of the workspace enters the mailbox's SMTP access (E-mail filing > Mailbox)."),
                       code="no_smtp"), 409
    if hit_limit(f"hubsend:{uid}", MBX_SEND_HOUR, 3600):
        return err(tr("Too many e-mails, please wait a few minutes"), 429)
    if via == "server":  # the server's own SMTP: its daily e-mail limit per person and recipient (a workspace's SMTP is its own)
        from ..admin.hosting import mail_budget
        for a in to + cc:
            if not mail_budget(c, uid, a):
                c.rollback()
                return err(tr("Today's e-mail limit is reached. Try again tomorrow."), 429)
        c.commit()
    from ..integrations.mail import mail_deliver, mail_message
    try:
        msg = mail_message(", ".join(to), subj, text, from_name=name or None, cc=", ".join(cc) or None, reply_to=reply_to, smtp=smtp)
    except (ValueError, TypeError):
        return err(tr("Invalid data"))
    if m0 is not None and m0["message_id"].startswith("<"):
        msg["In-Reply-To"] = m0["message_id"]
        msg["References"] = m0["message_id"]
    ws = H._ws(org, uid)
    frm = smtp["from"] if smtp else str(email.utils.parseaddr(str(msg["From"]))[1])
    plain = {"from_addr": frm.lower()[:300], "from_name": (name or "")[:300], "to_addrs": ", ".join(x.lower() for x in to + cc)[:2000],
             "subject": subj, "body": text[:H.HBM_BODY_MAX]}
    mid = _file_sent(c, uid, org, cid, lid, ws, msg, bytes(msg), plain)
    bump(c)
    c.commit()
    try:
        mail_deliver(msg, smtp)
    except Exception as e:  # noqa: BLE001
        code = _err_code(e)
        print("hubmail: sending failed", type(e).__name__, flush=True)
        lg = lang(c, uid)
        c.execute("UPDATE hub_mails SET send_state='failed', note=? WHERE id=?", (tr("Not sent: {0}", mbx_err_text(code, lg), lg=lg)[:2000], mid))
        bump(c)
        c.commit()
        row = c.execute("SELECT * FROM hub_mails WHERE id=?", (mid,)).fetchone()
        return jsonify(error=tr("Sending failed: {0}", mbx_err_text(code, lg)), code=code, mail=H.hbm_public(c, row)), 502
    c.execute("UPDATE hub_mails SET send_state='' WHERE id=?", (mid,))
    bump(c)
    c.commit()
    row = c.execute("SELECT * FROM hub_mails WHERE id=?", (mid,)).fetchone()
    return jsonify(mail=H.hbm_public(c, row), via=via), 201


def mbx_state(m):
    """'' (received / sent) | sending | failed of a hub_mails row (a mail 'sending' for long was never confirmed: failed)."""
    st = m["send_state"] or ""
    if st == "sending":
        try:
            from datetime import datetime
            age = (now_utc() - datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))).total_seconds()
        except (ValueError, AttributeError, TypeError):
            age = 0
        if age > MBX_STALE_S:
            return "failed"
    return st


def mbx_can_send(c, org, uid):
    """May uid send from the e-mail filing of workspace org at all (its mailbox's SMTP or the server's)?"""
    return bool(_sender(c, org, uid)[3])
