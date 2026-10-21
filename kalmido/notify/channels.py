"""2.142.0 A (#2145, #2146): notification channels (Slack, Matrix, Telegram, Signal) and e-mails for single events.

Channels: a person adds their own (Settings > Notifications > Channels) and picks what goes there (reminders, assignments,
mentions and comments, the daily digest, other notifications, events of their own private lists); an organisation's admins add
channels of the organisation (Settings > Workspaces) for what happens in its lists that every member sees (new task, completed,
assigned, comment) -- never a private area, never a list shared only with some, never the words of a list with the lock.
The address (webhook URL, bot token, numbers) is a secret: sealed with the server key, never sent back (kind, name and a masked
end only). Messages are plain text for people, not JSON events (that is what the webhooks are for). They are queued and sent by
a background loop (short timeout, the request never waits); a failed send is not retried, CH_FAIL_MAX failures in a row turn
the channel off (the settings show why). Outbound only to public https addresses, the webhooks' allow-list of an admin
(Settings > Administration > Advanced, KALMIDO_WEBHOOK_ALLOW_HOSTS) for self-hosted targets -- the same guard as the webhooks.
A person's quiet hours hold back their channel messages (urgent ones excepted). KALMIDO_CHANNELS=0: off.

E-mails for single events (#2146): an assignment or a mention reaches a person without a push device (no Web Push device, no
ntfy topic) by e-mail -- per kind "off / only without a push device / always" (mail_assign, mail_mention; default: only
without a push device). Collected and sent bundled by the watchdog: one mail EVM_DELAY seconds after the first event, at most one
every EVM_GAP seconds and EVM_DAY_MAX a day per person; the content is built at sending time (only tasks the person still sees,
the lock = a neutral word). Agents never get one (they have their events)."""
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import g, has_request_context, jsonify

from ..core.config import app, APP_NAME, APP_VERSION, PUBLIC_URL
from ..core.pg import insert_id, system_ctx
from ..core.i18n import LANGS, md_plain, N_, tr, trn
from ..core.db import body, connect, db, err, inbox_default, iso, local_now, now_utc, uset, usettings
from ..accounts.session import GATE, me
from ..core.access import Denied, ov_open, task_visible
from ..core.errors import BadInput
from ..notify.alerts import _env_int
from ..core.env import env_bool

CH_ON = env_bool("KALMIDO_CHANNELS", True)
CH_KINDS = ("slack", "matrix", "telegram", "signal")
CH_EVENTS_ME = ("reminder", "assign", "comment", "digest", "other", "lists")  # a person's channel
CH_EVENTS_ORG = ("newtask", "complete", "assign", "comment")                   # an organisation's channel
CH_DEFAULT_ME = ("reminder", "assign", "comment")
CH_DEFAULT_ORG = ("newtask", "complete", "assign", "comment")
CH_MAX = 10              # per person and per organisation
CH_FAIL_MAX = _env_int("KALMIDO_CHANNEL_FAILS", 5)  # failures in a row -> off
CH_TICK = _env_int("KALMIDO_CHANNEL_TICK", 5)
CH_TIMEOUT = 8
CH_QUEUE_MAX = 200       # waiting messages per channel (more are dropped)
CH_BATCH = 30
CH_TEXT_MAX = 1500
CH_TEST_LIMIT = 20       # "Send test" per person within the rate window
TELEGRAM_API = (os.environ.get("KALMIDO_TELEGRAM_API", "").strip() or "https://api.telegram.org").rstrip("/")
CH_ERR = {"http": N_("The server answered with an error ({0})"), "timeout": N_("No answer in time"),
          "network": N_("The address could not be reached"), "tls": N_("The secure connection failed"),
          "config": N_("Invalid URL"), "error": N_("Sending failed")}
TG_TOKEN_RE = re.compile(r"\d{3,15}:[A-Za-z0-9_-]{20,80}")
TG_CHAT_RE = re.compile(r"-?\d{1,20}|@[A-Za-z0-9_]{4,64}")
PHONE_RE = re.compile(r"\+\d{6,16}")
SIG_GROUP_RE = re.compile(r"group\.[A-Za-z0-9+/=_-]{8,200}")
_CH_WAKE = threading.Event()
_CH_TL = threading.local()  # .wd = True while the watchdog runs (its pushes are reminders unless tagged otherwise)

EVM_CHOICES = ("off", "nopush", "always")
EVM_KINDS = {"assign": "mail_assign", "mention": "mail_mention"}
EVM_DELAY = _env_int("KALMIDO_EVENT_MAIL_DELAY", 600)   # seconds after the first event
EVM_GAP = _env_int("KALMIDO_EVENT_MAIL_GAP", 600)       # at least this long between two mails to one person
EVM_DAY_MAX = 20
EVM_LINES = 30


# ---------------------------------------------------------------- addresses, sending
def chn_allow(c):
    from ..integrations.webhooks import wh_allow
    return wh_allow(c)


def chn_url(c, u):
    """A checked https URL (or an allow-listed host); BadInput with the reason otherwise."""
    from ..integrations.webhooks import wh_url_check
    u = wh_url_check(c, u)
    if urllib.parse.urlsplit(u).query and len(u) > 1500:
        raise BadInput(tr("Invalid URL"))
    return u


def chn_target(c, kind, b):
    """(target dict, masked hint) from the input of one kind; BadInput when something is missing or wrong."""
    s = lambda k: str(b.get(k) or "").strip()  # noqa: E731
    if kind in ("slack", "matrix"):
        u = chn_url(c, s("url"))
        return {"url": u}, f"{urllib.parse.urlsplit(u).hostname} …{u[-4:]}"
    if kind == "telegram":
        tok, chat = s("token"), s("chat_id")
        if tok.lower().startswith("bot"):
            tok = tok[3:]
        if not TG_TOKEN_RE.fullmatch(tok):
            raise BadInput(tr("Invalid bot token"))
        if not TG_CHAT_RE.fullmatch(chat):
            raise BadInput(tr("Invalid chat ID"))
        return {"token": tok, "chat_id": chat}, f"Telegram …{tok[-4:]}"
    if kind == "signal":
        u, num, to = chn_url(c, s("url")), s("number"), s("recipient")
        if not PHONE_RE.fullmatch(num):
            raise BadInput(tr("Invalid phone number: {0}", tr("Sender")))
        if not (PHONE_RE.fullmatch(to) or SIG_GROUP_RE.fullmatch(to)):
            raise BadInput(tr("Invalid phone number: {0}", tr("Recipient")))
        return {"url": u.rstrip("/"), "number": num, "recipient": to}, f"{urllib.parse.urlsplit(u).hostname} …{to[-4:]}"
    raise BadInput(tr("Invalid value: {0}", "kind"))


def chn_request(kind, t, text):
    """(url, JSON body) of one message."""
    if kind == "telegram":
        return f"{TELEGRAM_API}/bot{t['token']}/sendMessage", {"chat_id": t["chat_id"], "text": text, "disable_web_page_preview": True}
    if kind == "signal":
        return t["url"] + "/v2/send", {"message": text, "number": t["number"], "recipients": [t["recipient"]]}
    return t["url"], {"text": text}  # Slack incoming webhook, a Matrix webhook bridge (hookshot: {"text": ...})


def chn_send(kind, t, text, allow):
    """One POST (no database access): (ok, HTTP status or None, error code or '')."""
    from ..calendars.subscriptions import _cal_opener, cal_host_allowed, CalError
    try:
        url, payload = chn_request(kind, t, text)
    except (KeyError, TypeError):
        return False, None, "config"
    p = urllib.parse.urlsplit(url)
    try:
        port = p.port or {"http": 80, "https": 443}.get(p.scheme)
    except ValueError:
        return False, None, "config"
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or \
            (p.scheme == "http" and not cal_host_allowed(allow, p.hostname, port)):
        return False, None, "config"
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION} (notifications)"})
    try:
        with _cal_opener(allow).open(req, timeout=CH_TIMEOUT) as r:
            r.read(4096)
            code = r.status
        return 200 <= code < 300, code, "" if 200 <= code < 300 else "http"
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        return False, code, "http"
    except urllib.error.URLError as e:
        rs = e.reason
        return False, None, rs.code if isinstance(rs, CalError) else "tls" if isinstance(rs, ssl.SSLError) else \
            "timeout" if isinstance(rs, (TimeoutError, socket.timeout)) else "network"
    except CalError as e:
        return False, None, e.code
    except ssl.SSLError:
        return False, None, "tls"
    except (TimeoutError, socket.timeout):
        return False, None, "timeout"
    except (OSError, ValueError):
        return False, None, "network"


def chn_err_text(code, status=None, lg=None):
    from ..calendars.subscriptions import CAL_ERR
    if code == "blocked":
        return tr(CAL_ERR["blocked"], lg=lg) if lg else tr(CAL_ERR["blocked"])
    m = CH_ERR.get(code, CH_ERR["error"])
    return tr(m, status or "?", lg=lg) if code == "http" else tr(m, lg=lg)


def chn_text(title, msg, click):
    from ..collab.liste2eguard import le2b_net
    title, msg = md_plain(le2b_net(title or "")), md_plain(le2b_net(msg or ""))
    out = "\n".join(x for x in ((title or APP_NAME)[:300], msg, click or "") if x)
    return out[:CH_TEXT_MAX]


# ---------------------------------------------------------------- queue + delivery loop
def chn_enqueue(c, cid, text):
    if c.execute("SELECT COUNT(*) FROM notify_channel_queue WHERE channel_id=?", (cid,)).fetchone()[0] >= CH_QUEUE_MAX:
        return False
    c.execute("INSERT INTO notify_channel_queue(channel_id,text,created_at) VALUES(?,?,?)", (cid, text, time.time()))
    return True


def chn_tick():
    """Sends what waits (one try each); returns the number of messages handled."""
    from ..accounts.login import unseal
    with GATE.bg():
        c = connect()
        try:
            with system_ctx(c):  # background loop: every person's and organisation's channels
                c.execute("DELETE FROM notify_channel_queue WHERE channel_id IN (SELECT id FROM notify_channels WHERE enabled=0)")
                rows = [dict(r) for r in c.execute("""SELECT q.id, q.channel_id, q.text, n.kind, n.target FROM notify_channel_queue q
                                                      JOIN notify_channels n ON n.id=q.channel_id
                                                      ORDER BY q.id LIMIT ?""", (CH_BATCH,))]
                for r in rows:
                    try:
                        r["t"] = json.loads(unseal(c, f"channel:{r['channel_id']}", r["target"]) or "{}")
                    except Exception:  # noqa: BLE001  (InvalidTag, ValueError: the server key changed)
                        r["t"] = None
                    c.execute("DELETE FROM notify_channel_queue WHERE id=?", (r["id"],))
                allow = chn_allow(c)
            c.commit()
        finally:
            c.close()
    res = [(r, chn_send(r["kind"], r["t"], r["text"], allow) if r["t"] else (False, None, "config")) for r in rows]
    if res:
        with GATE.bg():
            c = connect()
            try:
                with system_ctx(c):  # background loop: the results of every channel
                    for r, (ok, status, code) in res:
                        chn_result(c, r["channel_id"], ok, status, code)
                c.commit()
            finally:
                c.close()
    return len(rows)


def chn_result(c, cid, ok, status, code):
    ts = iso(now_utc())
    if ok:
        c.execute("UPDATE notify_channels SET fails=0, last_error='', last_at=? WHERE id=?", (ts, cid))
        return
    c.execute("UPDATE notify_channels SET fails=fails+1, last_error=?, last_at=? WHERE id=?",
              (code + (f" {status}" if status else ""), ts, cid))
    r = c.execute("SELECT fails FROM notify_channels WHERE id=?", (cid,)).fetchone()
    if r and r[0] >= CH_FAIL_MAX:
        c.execute("UPDATE notify_channels SET enabled=0, disabled_reason='failures', updated_at=? WHERE id=?", (ts, cid))
        c.execute("DELETE FROM notify_channel_queue WHERE channel_id=?", (cid,))
        print(f"notification channel {cid} turned off after {r[0]} failed sends ({code} {status or ''})", flush=True)


def chn_loop():
    from ..notify.alerts import aa_count
    while True:
        _CH_WAKE.wait(CH_TICK)
        _CH_WAKE.clear()
        try:
            while chn_tick() >= CH_BATCH:
                pass
        except Exception as e:  # noqa: BLE001
            print("channels error:", type(e).__name__, e, flush=True)
            aa_count("watchdog", f"channels|{type(e).__name__}", "tick")


# ---------------------------------------------------------------- a person's pushes -> their channels (notify())
def chn_kind(kind, tag):
    """The channel event of a push: explicit, else from its tag / origin (the watchdog's pushes are reminders)."""
    if kind:
        return kind
    if tag == "test":
        return None  # the push test of the device settings
    if tag in ("digest", "briefing", "review"):
        return "digest"
    return "reminder" if getattr(_CH_TL, "wd", False) else "other"


def chn_push(uid, title, msg, prio, click, kind, s):
    """Queues one push of uid for their channels that want this kind. Never raises; True when one took it."""
    if not CH_ON or not kind:
        return False
    try:
        from .push import in_quiet
        if str(prio) != "5" and in_quiet(s or {}, local_now()):
            return False
        c = connect()
        try:
            with system_ctx(c):  # the recipient's own channels (a push thread has no request context)
                rows = [r for r in c.execute("""SELECT id, events FROM notify_channels WHERE user_id=? AND org_id IS NULL AND enabled=1""",
                                             (uid,)) if kind in r["events"].split(",")]
                n = sum(1 for r in rows if chn_enqueue(c, r["id"], chn_text(title, msg, click)))
            c.commit()
        finally:
            c.close()
        if n:
            _CH_WAKE.set()
        return n > 0
    except Exception as e:  # noqa: BLE001  (a channel never breaks the push)
        print("channels: queueing failed:", type(e).__name__, e, flush=True)
        return False


def chn_reachable(c, uid):
    """uid has a channel switched on (pushes are worth building for them even without a device)."""
    if not CH_ON:
        return False
    with system_ctx(c):  # the person's own channels, asked for other people too (pushes to them)
        return bool(c.execute("SELECT 1 FROM notify_channels WHERE user_id=? AND org_id IS NULL AND enabled=1 LIMIT 1", (uid,)).fetchone())


# ---------------------------------------------------------------- events of lists -> organisation channels / own list channels
CH_ACT = {"created": "newtask", "complete": "complete", "assign": "assign", "comment": "comment"}


def chn_note(c, tid, kind, cid=None):
    """Collected while a request runs (log_act, a new comment); queued after it succeeded (chn_flush)."""
    ev = CH_ACT.get(kind)
    if not CH_ON or not ev or not has_request_context():
        return
    n = g.setdefault("chn", {})
    e = n.setdefault((tid, ev), {"cid": None})
    if cid:
        e["cid"] = cid


@app.after_request
def chn_flush(resp):
    n = g.pop("chn", None) if has_request_context() else None
    if n and resp.status_code < 400:
        try:
            c = db()
            with system_ctx(c):  # after the request: the channels of the list's organisation / owner, not the actor's
                chn_list_events(c, n)
            c.commit()
        except Exception as e:  # noqa: BLE001  (never fail the request that already succeeded)
            try:
                db().heal()
            except Exception:  # noqa: BLE001
                pass
            print("channels: list events failed:", type(e).__name__, e, flush=True)
    return resp


def chn_list_events(c, n):
    from ..accounts.orgs import org_role
    chans = c.execute("""SELECT id, user_id, org_id, events FROM notify_channels WHERE enabled=1
                         AND (org_id IS NOT NULL OR events ILIKE '%lists%') ORDER BY id""").fetchall()
    if not chans:
        return
    actor = g.user["id"] if g.get("user") and g.get("auth_via") != "public" else None
    sent = 0
    for (tid, ev), e in n.items():
        t = c.execute("""SELECT t.id, t.title, t.status, t.deleted_at, t.assignee_id, t.list_id, l.name AS lname, l.is_inbox, l.owner_id,
                         l.org_id, l.life, l.family, l.org_visibility, l.e2e, l.archived, l.deleted_at AS ldel
                         FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?""", (tid,)).fetchone()
        if not t or t["deleted_at"] or t["ldel"] or t["archived"] or (t["life"] or "") in ("health", "budget"):
            continue
        if ev == "complete" and t["status"] != 2:
            continue  # completed (2) only, not "won't do" or reopened again within the request
        for ch in chans:
            if ev not in ch["events"].split(",") and not (not ch["org_id"] and "lists" in ch["events"].split(",")):
                continue
            if ch["org_id"]:
                # only what every member of the organisation sees: an organisation list open to all of it (ov_open)
                if t["org_id"] != ch["org_id"] or not ov_open(t):
                    continue
                if org_role(c, ch["user_id"], ch["org_id"]) != "admin":  # its creator is no admin there any more: off
                    c.execute("UPDATE notify_channels SET enabled=0, disabled_reason='admin', updated_at=? WHERE id=?",
                              (iso(now_utc()), ch["id"]))
                    c.execute("DELETE FROM notify_channel_queue WHERE channel_id=?", (ch["id"],))
                    continue
            elif t["org_id"] or t["owner_id"] != ch["user_id"]:
                continue  # a person's channel: events of their own private lists only (2.142.0 P4: the private area's channel)
            text = chn_event_text(c, t, ev, e.get("cid"), actor, ch["user_id"])
            if text and chn_enqueue(c, ch["id"], text):
                sent += 1
    if sent:
        _CH_WAKE.set()


def chn_event_text(c, t, ev, cid, actor, owner):
    from ..collab.comments import comment_plain, user_names
    from ..collab.liste2e import le2e_mode, le2e_neutral
    s = usettings(c, owner)
    lg = s.get("lang") if s.get("lang") in LANGS else "en"
    names = user_names(c, [x for x in (actor, t["assignee_id"]) if x])
    who = names.get(actor) or tr("Someone via the public link", lg=lg)
    lname = tr("Basket", lg=lg) if t["is_inbox"] and inbox_default(t["lname"]) else t["lname"]
    lk = bool(le2e_mode(c, t["list_id"]))
    title = le2e_neutral(lg) if lk else md_plain(t["title"] or "")
    if ev == "newtask":
        line = tr("{0} added: {1}", who, title, lg=lg)
    elif ev == "complete":
        line = tr("{0} completed: {1}", who, title, lg=lg)
    elif ev == "assign":
        if not t["assignee_id"]:
            return None
        line = tr("{0} assigned {1}: {2}", who, names.get(t["assignee_id"], "?"), title, lg=lg)
    else:
        line = tr("{0} commented on {1}", who, title, lg=lg)
        if cid and not lk:
            k = c.execute("SELECT body FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
            if k:
                snip = comment_plain(c, k["body"])
                line += ": " + (snip[:280] + ("…" if len(snip) > 280 else ""))
    return chn_text(line, lname, f"{PUBLIC_URL}/#t/{t['id']}")


# ---------------------------------------------------------------- settings API
def chn_need_on():
    if not CH_ON:
        raise Denied(409, tr("Notification channels are turned off on this server"))


def chn_need_person():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))


def chn_need_admin(oid):
    from ..accounts.orgs import _need_org_admin
    _need_org_admin(db(), oid)


def chn_rows(c, oid):
    if oid:
        return c.execute("SELECT * FROM notify_channels WHERE org_id=? ORDER BY id", (oid,)).fetchall()
    return c.execute("SELECT * FROM notify_channels WHERE user_id=? AND org_id IS NULL ORDER BY id", (me(),)).fetchall()


def chn_need(c, chid, oid=None):
    if oid:
        r = c.execute("SELECT * FROM notify_channels WHERE id=? AND org_id=?", (chid, oid)).fetchone()
    else:
        r = c.execute("SELECT * FROM notify_channels WHERE id=? AND user_id=? AND org_id IS NULL", (chid, me())).fetchone()
    if not r:
        raise Denied(404)
    return r


def chn_public(r):
    """What the client sees of a channel: never the address, the token or the numbers."""
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "hint": r["hint"],
            "events": [e for e in r["events"].split(",") if e], "enabled": bool(r["enabled"]),
            "disabled_reason": r["disabled_reason"], "fails": r["fails"],
            "last_error": chn_err_text(*(r["last_error"].split(" ", 1) + [None])[:2]) if r["last_error"] else "",
            "last_at": r["last_at"], "created_at": r["created_at"]}


def chn_fields(c, b, oid, old=None):
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "body"))
    out = {}
    allowed = CH_EVENTS_ORG if oid else CH_EVENTS_ME
    if old is None:
        kind = str(b.get("kind") or "")
        if kind not in CH_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = kind
    kind = out.get("kind") or old["kind"]
    if "name" in b or old is None:
        out["name"] = str(b.get("name") or "").strip()[:60]
    if old is None or any(k in b for k in ("url", "token", "chat_id", "number", "recipient")):
        t, hint = chn_target(c, kind, b)
        out["_target"], out["hint"] = t, hint
    if "events" in b or old is None:
        ev = b.get("events", list(CH_DEFAULT_ORG if oid else CH_DEFAULT_ME))
        if not isinstance(ev, list) or not ev or any(e not in allowed for e in ev):
            raise BadInput(tr("Choose at least one event"))
        out["events"] = ",".join(e for e in allowed if e in ev)
    if "enabled" in b:
        if not isinstance(b["enabled"], bool):
            raise BadInput(tr("Invalid value: {0}", "enabled"))
        out["enabled"] = 1 if b["enabled"] else 0
        if b["enabled"]:
            out["disabled_reason"], out["fails"] = "", 0
    return out


def chn_seal(c, chid, t):
    from ..accounts.login import seal
    c.execute("UPDATE notify_channels SET target=? WHERE id=?", (seal(c, f"channel:{chid}", json.dumps(t)), chid))


def chn_list_do(oid=None):
    c = db()
    out = {"enabled": CH_ON, "kinds": list(CH_KINDS), "events": list(CH_EVENTS_ORG if oid else CH_EVENTS_ME),
           "fail_max": CH_FAIL_MAX, "channels": [chn_public(r) for r in chn_rows(c, oid)]}
    if not oid:
        out["mail"] = evm_info(c, me())
    return jsonify(out)


def chn_create_do(oid=None):
    chn_need_on()
    c = db()
    f = chn_fields(c, body(), oid)
    if len(chn_rows(c, oid)) >= CH_MAX:
        return err(tr("At most {0} channels", CH_MAX), 409)
    ts = iso(now_utc())
    chid = insert_id(c, """INSERT INTO notify_channels(user_id,org_id,kind,name,target,hint,events,enabled,created_at,updated_at)
                           VALUES(?,?,?,?,'',?,?,?,?,?)""", (me(), oid, f["kind"], f["name"], f["hint"], f["events"], f.get("enabled", 1), ts, ts))
    chn_seal(c, chid, f["_target"])
    c.commit()
    return jsonify(chn_public(chn_need(c, chid, oid))), 201


def chn_update_do(chid, oid=None):
    chn_need_on()
    c = db()
    old = chn_need(c, chid, oid)
    f = chn_fields(c, body(), oid, old=old)
    t = f.pop("_target", None)
    if f or t:
        f["updated_at"] = iso(now_utc())
        if oid and f.get("enabled") == 1:
            f["user_id"] = me()  # the admin who switches it on owns it from now on (checked per event)
        if t:
            f["fails"], f["last_error"] = 0, ""
        c.execute(f"UPDATE notify_channels SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), chid])
        if t:
            chn_seal(c, chid, t)
        if f.get("enabled") == 0:
            c.execute("DELETE FROM notify_channel_queue WHERE channel_id=?", (chid,))
        c.commit()
    return jsonify(chn_public(chn_need(c, chid, oid)))


def chn_delete_do(chid, oid=None):
    c = db()
    chn_need(c, chid, oid)
    c.execute("DELETE FROM notify_channels WHERE id=?", (chid,))
    c.commit()
    return jsonify(ok=True)


def chn_test_do(chid, oid=None):
    """Sends a test message now (this request waits for it, at most CH_TIMEOUT seconds); counts like any other send."""
    from ..accounts.login import unseal
    from ..accounts.session import _rate_blocked, _rate_fail
    chn_need_on()
    c = db()
    r = chn_need(c, chid, oid)
    keys = [(f"chntest:{me()}", CH_TEST_LIMIT)]
    if _rate_blocked(keys):
        return err(tr("Too many tests, please wait a few minutes"), 429)
    _rate_fail(keys)
    try:
        t = json.loads(unseal(c, f"channel:{chid}", r["target"]) or "{}")
    except Exception:  # noqa: BLE001
        t = None
    allow = chn_allow(c)
    c.commit()
    text = chn_text(tr("{0}: test", APP_NAME), tr("Notifications are arriving."), PUBLIC_URL)
    ok, status, code = chn_send(r["kind"], t, text, allow) if t else (False, None, "config")
    with system_ctx(c):  # the count of the channel (an organisation's too) after its test
        chn_result(c, chid, ok, status, code)
    c.commit()
    return jsonify(ok=ok, status=status, error=code, error_text=chn_err_text(code, status) if code else "",
                   channel=chn_public(chn_need(c, chid, oid)))


@app.get("/api/me/channels")
def channels_list():
    chn_need_person()
    return chn_list_do()


@app.post("/api/me/channels")
def channel_create():
    chn_need_person()
    return chn_create_do()


@app.patch("/api/me/channels/<int:chid>")
def channel_update(chid):
    chn_need_person()
    return chn_update_do(chid)


@app.delete("/api/me/channels/<int:chid>")
def channel_delete(chid):
    chn_need_person()
    return chn_delete_do(chid)


@app.post("/api/me/channels/<int:chid>/test")
def channel_test(chid):
    chn_need_person()
    return chn_test_do(chid)


@app.get("/api/orgs/<int:oid>/channels")
def org_channels_list(oid):
    chn_need_admin(oid)
    return chn_list_do(oid)


@app.post("/api/orgs/<int:oid>/channels")
def org_channel_create(oid):
    chn_need_admin(oid)
    return chn_create_do(oid)


@app.patch("/api/orgs/<int:oid>/channels/<int:chid>")
def org_channel_update(oid, chid):
    chn_need_admin(oid)
    return chn_update_do(chid, oid)


@app.delete("/api/orgs/<int:oid>/channels/<int:chid>")
def org_channel_delete(oid, chid):
    chn_need_admin(oid)
    return chn_delete_do(chid, oid)


@app.post("/api/orgs/<int:oid>/channels/<int:chid>/test")
def org_channel_test(oid, chid):
    chn_need_admin(oid)
    return chn_test_do(chid, oid)


# ---------------------------------------------------------------- #2146: e-mails for single events
def evm_device(c, uid, s):
    """A push device: a Web Push subscription, or the ntfy topic when the person uses ntfy (channel ntfy / both, or a server
    without Web Push) -- every account gets a topic at creation, so its mere existence says nothing. The channels of #2145
    do not count."""
    from .push import push_channel, WEBPUSH_ON, webpush_count
    if webpush_count(c, uid) > 0:
        return True
    return bool(s.get("ntfy_topic")) and (not WEBPUSH_ON or push_channel(s) in ("ntfy", "both"))


def evm_choice(s, kind):
    v = (s or {}).get(EVM_KINDS[kind])
    return v if v in EVM_CHOICES else "nopush"


def evm_wanted(c, uid, s, kind):
    from ..integrations.mail import MAIL_OUT_ON
    if not MAIL_OUT_ON or kind not in EVM_KINDS:
        return False
    v = evm_choice(s, kind)
    return v == "always" or (v == "nopush" and not evm_device(c, uid, s))


def evm_info(c, uid):
    from ..integrations.mail import MAIL_OUT_ON
    s = usettings(c, uid)
    u = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    return {"enabled": MAIL_OUT_ON, "address": bool(u and (u["email"] or "").strip()), "device": evm_device(c, uid, s),
            "assign": evm_choice(s, "assign"), "mention": evm_choice(s, "mention")}


def evm_note(c, uid, kind, tid, actor, s, cid=None):
    """An assignment / mention for uid: waits for the next bundled mail when uid wants it (setting, no push device)."""
    try:
        if uid == actor or not evm_wanted(c, uid, s, kind):
            return
        u = c.execute("SELECT kind, email, disabled FROM users WHERE id=?", (uid,)).fetchone()
        if not u or u["kind"] == "agent" or u["disabled"] or not (u["email"] or "").strip():
            return
        if c.execute("SELECT COUNT(*) FROM notify_mail_queue WHERE user_id=?", (uid,)).fetchone()[0] >= 200:
            return
        c.execute("INSERT INTO notify_mail_queue(user_id,kind,task_id,comment_id,actor_id,created_at) VALUES(?,?,?,?,?,?)",
                  (uid, kind, tid, cid, actor, time.time()))
    except Exception as e:  # noqa: BLE001  (a mail note never fails the change itself)
        print("event mail: note failed:", type(e).__name__, e, flush=True)


def evm_tick(c, users, S, LG, now):
    """Watchdog: one bundled mail per person whose first waiting event is EVM_DELAY old (and the last mail EVM_GAP)."""
    from ..notify.push import _wd_fail
    rows = c.execute("SELECT user_id, MIN(created_at) AS first FROM notify_mail_queue GROUP BY user_id").fetchall()
    for r in rows:
        uid = r["user_id"]
        if uid not in users:
            c.execute("DELETE FROM notify_mail_queue WHERE user_id=?", (uid,))
            c.commit()
            continue
        if time.time() - r["first"] < EVM_DELAY:
            continue
        try:
            evm_user(c, uid, S[uid], LG[uid], now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "event mail of user", uid, e)


def evm_user(c, uid, s, lg, now):
    from ..admin.hosting import mail_budget
    from ..collab.comments import user_names
    from ..collab.liste2e import le2e_mode, le2e_neutral
    from ..integrations.mail import MAIL_OUT_ON, mail_send
    from ..notify.alerts import aa_err, aa_fail, aa_ok
    if time.time() - float(s.get("evmail_at") or 0) < EVM_GAP:
        return
    q = c.execute("SELECT * FROM notify_mail_queue WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    if not q:
        return
    drop = lambda: c.execute("DELETE FROM notify_mail_queue WHERE user_id=? AND id<=?", (uid, q[-1]["id"]))
    day = now.date().isoformat()
    d, _, k = str(s.get("evmail_day") or "").partition(":")
    sent_today = int(k) if d == day and k.isdigit() else 0
    u = c.execute("SELECT email, kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
    to = (u["email"] or "").strip() if u else ""
    if not MAIL_OUT_ON or not to or u["kind"] == "agent" or u["disabled"] or sent_today >= EVM_DAY_MAX:
        drop()
        c.commit()
        return
    names = user_names(c, list({x["actor_id"] for x in q if x["actor_id"]}))
    lines, seen = [], set()
    for x in q:
        if (x["kind"], x["task_id"]) in seen or not evm_wanted(c, uid, s, x["kind"]):
            continue
        t = c.execute("""SELECT t.id, t.title, t.deleted_at, t.list_id, l.name AS lname, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.id=?""", (x["task_id"],)).fetchone()
        if not t or t["deleted_at"] or not task_visible(c, t["id"], uid, full=True):
            continue  # gone, or out of sight by now: nothing of it in the mail
        seen.add((x["kind"], x["task_id"]))
        who = names.get(x["actor_id"]) or tr("Someone via the public link", lg=lg)
        title = le2e_neutral(lg) if le2e_mode(c, t["list_id"]) else md_plain(t["title"] or "")
        lname = tr("Basket", lg=lg) if t["is_inbox"] and inbox_default(t["lname"]) else t["lname"]
        what = tr("{0} assigned you: {1}", who, title, lg=lg) if x["kind"] == "assign" else tr("{0} mentioned you: {1}", who, title, lg=lg)
        lines.append((what, lname, f"{PUBLIC_URL}/#t/{t['id']}"))
    if not lines:
        drop()
        c.commit()
        return
    if not mail_budget(c, None, to):  # 2.142.0 review: the mail budget is used up - the entries wait for the next round
        c.commit()
        return
    drop()
    uset(c, uid, "evmail_at", str(int(time.time())))
    uset(c, uid, "evmail_day", f"{day}:{sent_today + 1}")
    c.commit()
    m = evm_content(lines[:EVM_LINES], len(lines), lg)
    try:
        mail_send(to, *m)
        aa_ok("smtp")
    except Exception as e:  # noqa: BLE001
        print("mail: event mail for user", uid, "failed:", type(e).__name__, e, flush=True)
        aa_fail("smtp", aa_err(e))


def evm_content(lines, total, lg):
    import html
    subj = f"{APP_NAME}: " + trn("{0} new notification", "{0} new notifications", total, lg=lg)
    more = total - len(lines)
    foot = tr("You get these e-mails for assignments and mentions. Change or turn them off in Settings > Notifications:", lg=lg) + \
        f" {PUBLIC_URL}/#settings/notify"
    text = "\n\n".join(f"- {w} · {ln}\n  {u}" for w, ln, u in lines) + \
        (("\n\n" + trn("and {0} more", "and {0} more", more, lg=lg)) if more > 0 else "") + "\n\n-- \n" + foot + "\n"
    e = html.escape
    hb = "<ul>" + "".join(f'<li><a href="{e(u)}">{e(w)}</a> <span style="color:#666">· {e(ln)}</span></li>' for w, ln, u in lines) + "</ul>"
    if more > 0:
        hb += f"<p>{e(trn('and {0} more', 'and {0} more', more, lg=lg))}</p>"
    hb += f'<p style="color:#666;font-size:90%">{e(foot.rsplit(" ", 1)[0])} <a href="{e(PUBLIC_URL)}/#settings/notify">{e(tr("Settings", lg=lg))}</a></p>'
    return subj, text, f"<!doctype html><html><body style=\"font-family:sans-serif\">{hb}</body></html>"
