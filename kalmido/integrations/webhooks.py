"""Webhooks per user: collecting events during a request, delivery, settings."""
import contextlib
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import uuid
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.exceptions import InvalidTag
from flask import g, has_request_context, jsonify

from ..core.config import app, APP_NAME, APP_VERSION
from ..core.i18n import N_, tr
from ..core.db import body, connect, db, err, inbox_default, iso, iso_ms, now_utc, usettings
from ..accounts.session import _rate_blocked, _rate_fail, GATE, me
from ..accounts.login import seal, unseal
from ..core.access import Denied, list_role, task_visible
from ..collab.comments import collab_on, comment_plain, user_names
from ..personal.timetrack import BadInput
from ..notify.alerts import _env_int, aa_count, aa_now
from ..calendars.subscriptions import (
    _cal_opener, cal_allow, cal_allow_parse, CAL_ERR, cal_host_allowed, cal_ip_public, CalError,
)
from ..api.v1 import act_via, task_core, task_for, WH_ON


# ---------------------------------------------------------------- package B: webhooks (per user)
# A user registers URLs (Settings > Integrations > Webhooks) for events of tasks and lists THEY can see: task.created,
# task.updated, task.completed, task.reopened, task.deleted, comment.created, list.shared. Events are collected while a
# request runs (log_act is the one place every change of a task passes, whatever the client: app, API, public link,
# batch) and queued after the request succeeded -- one payload per subscribed webhook, built for its owner (their
# tags, only lists they see at that moment; the collaboration switches apply). A background thread delivers them:
# POST, JSON, signed with the webhook's secret (X-Kalmido-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>">),
# 10 s timeout, the response body is ignored (at most 4 KB read), no redirects. A failed delivery is retried after
# 1 min, 5 min, 30 min and 2 h; when the last try fails too the webhook is turned off and the admins get an alert.
# SSRF guard: the same as calendar subscriptions (every address the host resolves to must be public, checked when
# connecting); hosts on the admin allow-list (Settings > Users > Whole server) or in KALMIDO_WEBHOOK_ALLOW_HOSTS may be
# internal, and only those may use http://. The secret is stored encrypted and shown once. KALMIDO_WEBHOOKS=0: off.
WH_EVENTS = ("task.created", "task.updated", "task.completed", "task.reopened", "task.deleted", "comment.created", "list.shared")
WH_ALLOW_ENV = os.environ.get("KALMIDO_WEBHOOK_ALLOW_HOSTS", "")
try:  # seconds before retry 1, 2, ... (tests shorten them); the webhook is turned off when the last one fails too
    WH_BACKOFF = [max(1, int(x)) for x in os.environ.get("KALMIDO_WEBHOOK_BACKOFF", "").split(",") if x.strip()] or [60, 300, 1800, 7200]
except ValueError:
    WH_BACKOFF = [60, 300, 1800, 7200]
WH_TICK = _env_int("KALMIDO_WEBHOOK_TICK", 5)
WH_TIMEOUT = 10
WH_READ_MAX = 4096
WH_MAX = 10              # per user
WH_LOG_KEEP = 50         # delivery log rows per webhook
WH_QUEUE_MAX = 500       # pending deliveries per webhook (more are dropped and logged)
WH_BATCH = 20            # deliveries per tick
WH_TEST_LIMIT = 20       # "Send test" per user within FAIL_WINDOW
WH_ACT = {"created": "task.created", "complete": "task.completed", "reopen": "task.reopened", "delete": "task.deleted",
          "purge": "task.deleted", "comment": "comment.created"}
WH_ERR = {"blocked": CAL_ERR["blocked"], "timeout": CAL_ERR["timeout"], "network": CAL_ERR["network"], "tls": CAL_ERR["tls"],
          "redirect": N_("The server answered with a redirect, which is not followed"), "http": N_("The server answered with an error ({0})"),
          "config": N_("Invalid URL"), "error": CAL_ERR["error"], "dropped": N_("Too many pending deliveries, event dropped")}


def need_wh():
    if not WH_ON:
        raise Denied(409, tr("Webhooks are turned off on this server"))


def wh_allow(c):
    return frozenset(cal_allow(c) | set(cal_allow_parse(WH_ALLOW_ENV)[0]))


def wh_url_check(c, u):
    """Normalized webhook URL; BadInput with the reason otherwise (DNS names are checked again when connecting)."""
    u = str(u or "").strip()
    if not u or len(u) > 2000 or any(ch.isspace() or ord(ch) < 32 for ch in u):
        raise BadInput(tr("Invalid URL"))
    p = urllib.parse.urlsplit(u)
    try:
        port = p.port or {"http": 80, "https": 443}.get(p.scheme.lower())
    except ValueError:
        raise BadInput(tr("Invalid URL")) from None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        raise BadInput(tr("Invalid URL"))
    allow = wh_allow(c)
    allowed = cal_host_allowed(allow, p.hostname, port)
    if p.scheme.lower() == "http" and not allowed:
        raise BadInput(tr("Webhooks need https:// (http:// only for hosts an admin allowed)"))
    try:
        ip = ipaddress.ip_address(p.hostname.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None and not allowed and not cal_ip_public(ip):
        raise BadInput(tr(CAL_ERR["blocked"]))
    if p.hostname.lower().rstrip(".") in ("localhost", "localhost.localdomain") and not allowed:
        raise BadInput(tr(CAL_ERR["blocked"]))
    return u


def wh_err_text(code, status=None):
    if code == "http":
        return tr(WH_ERR["http"], status or "?")
    return tr(WH_ERR.get(code, WH_ERR["error"]))


def wh_send(url, secret, event, delivery, attempt, body_bytes, allow):
    """One POST (no database access): (ok, HTTP status or None, milliseconds, error code or '')."""
    t = str(int(time.time()))
    sig = hmac.new(secret.encode(), t.encode() + b"." + body_bytes, hashlib.sha256).hexdigest()
    hd = {"Content-Type": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION} (webhook)", "X-Kalmido-Event": event,
          "X-Kalmido-Delivery": delivery, "X-Kalmido-Attempt": str(attempt), "X-Kalmido-Signature": f"t={t},v1={sig}"}
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    p = urllib.parse.urlsplit(url)
    try:
        port = p.port or {"http": 80, "https": 443}.get(p.scheme)
    except ValueError:
        return False, None, 0, "config"
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or \
            (p.scheme == "http" and not cal_host_allowed(allow, p.hostname, port)):
        return False, None, 0, "config"
    req = urllib.request.Request(url, data=body_bytes, method="POST", headers=hd)
    try:
        with _cal_opener(allow).open(req, timeout=WH_TIMEOUT) as r:
            r.read(WH_READ_MAX)
            code = r.status
        return 200 <= code < 300, code, ms(), "" if 200 <= code < 300 else "http"
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        return False, code, ms(), "redirect" if 300 <= code < 400 else "http"
    except urllib.error.URLError as e:
        rs = e.reason
        err_ = rs.code if isinstance(rs, CalError) else "tls" if isinstance(rs, ssl.SSLError) else \
            "timeout" if isinstance(rs, (TimeoutError, socket.timeout)) else "network"
        return False, None, ms(), err_
    except CalError as e:
        return False, None, ms(), e.code
    except ssl.SSLError:
        return False, None, ms(), "tls"
    except (TimeoutError, socket.timeout):
        return False, None, ms(), "timeout"
    except (OSError, http.client.HTTPException, ValueError):
        return False, None, ms(), "network"


# ---- collecting events during a request (log_act, comments, sharing) and queueing them after it succeeded
def wh_note(c, tid, kind, cid=None):
    if not WH_ON or not has_request_context():
        return
    n = g.setdefault("wh", {})
    e = n.get(("task", tid))
    if e is None:
        e = n[("task", tid)] = {"events": [], "kinds": [], "cid": None, "snap": None}
    ev = WH_ACT.get(kind, "task.updated")
    if ev not in e["events"]:
        e["events"].append(ev)
    if ev == "task.updated" and kind not in e["kinds"]:
        e["kinds"].append(kind)
    if cid:
        e["cid"] = cid
    if kind == "purge":  # deleted for good right after this: keep what the payload needs
        r = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        e["snap"] = dict(r) if r else None


def wh_note_list(lid, event, data):
    if WH_ON and has_request_context():
        g.setdefault("wh", {})[("list", lid, event, data.get("member_id"))] = data


@app.after_request
def wh_flush(resp):
    n = g.pop("wh", None) if has_request_context() else None
    if n and resp.status_code < 400:
        try:
            wh_enqueue(db(), n)
        except Exception as e:  # noqa: BLE001  (never fail the request that already succeeded)
            print("webhooks: queueing failed:", type(e).__name__, e, flush=True)
            aa_count("watchdog", f"webhooks|{type(e).__name__}", "queue")
    return resp


def wh_actor(c):
    if g.get("auth_via") == "public" or not g.get("user"):
        return None
    u = g.user
    return {"id": u["id"], "name": u["display_name"] or u["username"]}


def wh_enqueue(c, n):
    hooks = c.execute("""SELECT w.* FROM webhooks w JOIN users u ON u.id=w.user_id
                         WHERE w.enabled=1 AND u.disabled=0 AND w.agent=0 ORDER BY w.id""").fetchall()
    if not hooks:
        return
    actor, via = wh_actor(c), act_via() or "web"
    lists, settings = {}, {}

    def lst(lid):
        if lid not in lists:
            r = c.execute("SELECT id, name, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
            lists[lid] = {"id": lid, "name": tr("Inbox") if r and r["is_inbox"] and inbox_default(r["name"]) else (r["name"] if r else "")}
        return lists[lid]

    def sett(uid):
        if uid not in settings:
            settings[uid] = usettings(c, uid)
        return settings[uid]
    for key, e in n.items():
        if key[0] == "task":
            tid = key[1]
            row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            base = row or e["snap"]
            if not base:
                continue
            lid, evs = base["list_id"], list(e["events"])
            if "task.created" in evs:
                evs = [x for x in evs if x in ("task.created", "comment.created")]
            elif any(x in evs for x in ("task.completed", "task.reopened", "task.deleted")):
                evs = [x for x in evs if x != "task.updated"]
            for w in hooks:
                want = [x for x in evs if x in w["events"].split(",")]
                if not want or not list_role(c, lid, w["user_id"]):
                    continue
                # 1.10.0: a participant's webhooks only fire for their own tasks (never for context parents)
                sees = task_visible(c, tid, w["user_id"], full=True) if row else \
                    (list_role(c, lid, w["user_id"]) != "participant" or base["assignee_id"] == w["user_id"])
                if not sees:
                    continue
                for ev in want:
                    if ev == "comment.created" and not collab_on(sett(w["user_id"])):
                        continue
                    task = task_for(c, row, w["user_id"]) if row else {**task_core(base, [], {}), "deleted": True}
                    data = {"task": task, "list": lst(lid)}
                    if ev == "task.updated":
                        data["changes"] = e["kinds"]
                    if ev == "task.deleted":
                        data["permanent"] = row is None
                    if ev == "comment.created" and e["cid"]:
                        k = c.execute("SELECT * FROM comments WHERE id=?", (e["cid"],)).fetchone()
                        if not k:
                            continue
                        data["comment"] = {"id": k["id"], "author_id": k["user_id"], "text": comment_plain(c, k["body"]),
                                           "created_at": k["created_at"],
                                           "files": c.execute("SELECT COUNT(*) FROM attachments WHERE comment_id=?", (k["id"],)).fetchone()[0]}
                    wh_queue(c, w, ev, data, actor, via)
        elif key[0] == "list":
            _, lid, ev, member = key
            for w in hooks:
                if ev not in w["events"].split(",") or not list_role(c, lid, w["user_id"]):
                    continue
                if w["user_id"] not in (member, (c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone() or [None])[0]):
                    continue  # list.shared: the owner and the person it was shared with
                data = {"list": lst(lid), "member": {"id": member, "name": user_names(c, [member]).get(member, "")},
                        "role": n[key].get("role")}
                wh_queue(c, w, ev, data, actor, via)
    c.commit()


def wh_queue(c, w, event, data, actor, via):
    if c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (w["id"],)).fetchone()[0] >= WH_QUEUE_MAX:
        wh_log(c, w["id"], "", event, 0, False, None, "dropped", 0)
        return
    delivery = str(uuid.uuid4())
    payload = {"id": delivery, "event": event, "created_at": iso(now_utc()), "webhook_id": w["id"], "actor": actor, "via": via,
               "data": data}
    c.execute("INSERT INTO webhook_queue(webhook_id,delivery,event,payload,attempt,next_at,created_at) VALUES(?,?,?,?,0,?,?)",
              (w["id"], delivery, event, json.dumps(payload, ensure_ascii=False), time.time(), iso(now_utc())))


def wh_log(c, wid, delivery, event, attempt, ok, status, error, ms):
    c.execute("INSERT INTO webhook_log(webhook_id,delivery,event,attempt,ok,status,error,ms,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (wid, delivery, event, attempt, 1 if ok else 0, status, error, ms, iso_ms(now_utc())))
    c.execute("""DELETE FROM webhook_log WHERE webhook_id=? AND id<=(SELECT id FROM webhook_log WHERE webhook_id=?
                 ORDER BY id DESC LIMIT 1 OFFSET ?)""", (wid, wid, WH_LOG_KEEP))


# ---- delivery (background thread; the network part runs outside the maintenance gate)
def wh_tick():
    with GATE.bg():
        c = connect()
        try:
            c.execute("""DELETE FROM webhook_queue WHERE webhook_id IN (SELECT w.id FROM webhooks w JOIN users u ON u.id=w.user_id
                         WHERE w.enabled=0 OR u.disabled=1)""")
            c.commit()
            rows = [dict(r) for r in c.execute("""SELECT q.*, w.url, w.secret, w.user_id FROM webhook_queue q
                                                  JOIN webhooks w ON w.id=q.webhook_id WHERE q.next_at<=? ORDER BY q.next_at, q.id LIMIT ?""",
                                               (time.time(), WH_BATCH))]
            allow = wh_allow(c)
            for r in rows:
                try:
                    r["key"] = unseal(c, f"webhook:{r['webhook_id']}", r["secret"])
                except (InvalidTag, ValueError):
                    r["key"] = None
        finally:
            c.close()
    for r in rows:
        res = wh_send(r["url"], r["key"], r["event"], r["delivery"], r["attempt"] + 1, r["payload"].encode(), allow) \
            if r["key"] else (False, None, 0, "error")
        with GATE.bg():
            c = connect()
            try:
                wh_result(c, r, res)
            finally:
                c.close()
    return len(rows)


def wh_result(c, r, res):
    from ..agents.chat import chat_delivered, chat_event_mids
    ok, status, ms, errc = res
    att = r["attempt"] + 1
    w = c.execute("SELECT w.*, u.username FROM webhooks w JOIN users u ON u.id=w.user_id WHERE w.id=?", (r["webhook_id"],)).fetchone()
    if not w:
        return
    wh_log(c, w["id"], r["delivery"], r["event"], att, ok, status, errc, ms)
    if ok:
        c.execute("DELETE FROM webhook_queue WHERE id=?", (r["id"],))
        if w["agent"] and r["event"] == "chat":  # 2.7.2 (#422): the agent's webhook took the chat message
            with contextlib.suppress(ValueError, TypeError):
                chat_delivered(c, w["user_id"], chat_event_mids([json.loads(r["payload"])]))
    elif att > len(WH_BACKOFF):  # the last retry failed: turn the webhook off, tell the admins
        c.execute("DELETE FROM webhook_queue WHERE webhook_id=?", (w["id"],))
        c.execute("UPDATE webhooks SET enabled=0, disabled_reason='failures', updated_at=? WHERE id=?", (iso(now_utc()), w["id"]))
        print(f"webhook {w['id']} of user {w['user_id']} turned off after {att} failed attempts ({errc} {status or ''})", flush=True)
        aa_now("integration", f"webhook:{w['id']}", N_("Webhook {0} of {1} was turned off after {2} failed attempts to deliver an event (last error: {3})."),
               [w["id"], w["username"], att, errc + (f" {status}" if status else "")])
    else:
        c.execute("UPDATE webhook_queue SET attempt=?, next_at=? WHERE id=?", (att, time.time() + WH_BACKOFF[att - 1], r["id"]))
    c.commit()


def wh_loop():
    while True:
        time.sleep(WH_TICK)
        try:
            wh_tick()
        except Exception as e:  # noqa: BLE001
            print("webhooks error:", type(e).__name__, e, flush=True)
            aa_count("watchdog", f"webhooks|{type(e).__name__}", "tick")


# ---- settings API (Settings > Integrations > Webhooks)
def need_webhook(c, wid):
    r = c.execute("SELECT * FROM webhooks WHERE id=? AND user_id=? AND agent=0", (wid, me())).fetchone()
    if not r:
        raise Denied(404)
    return r


def wh_public(c, r):
    last = c.execute("SELECT ok, status, error, created_at FROM webhook_log WHERE webhook_id=? AND attempt>0 ORDER BY id DESC LIMIT 1",
                     (r["id"],)).fetchone()
    return {"id": r["id"], "name": r["name"], "url": r["url"], "events": [e for e in r["events"].split(",") if e],
            "enabled": bool(r["enabled"]), "disabled_reason": r["disabled_reason"], "created_at": r["created_at"],
            "pending": c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (r["id"],)).fetchone()[0],
            "last": {"ok": bool(last["ok"]), "status": last["status"], "error": last["error"],
                     "error_text": wh_err_text(last["error"], last["status"]) if last["error"] else "", "at": last["created_at"]} if last else None}


def wh_fields(c, b, old=None):
    out = {}
    if "name" in b or old is None:
        out["name"] = str(b.get("name") or "").strip()[:60]
    if "url" in b or old is None:
        out["url"] = wh_url_check(c, b.get("url"))
    if "events" in b or old is None:
        ev = b.get("events")
        if not isinstance(ev, list) or not ev or any(e not in WH_EVENTS for e in ev):
            raise BadInput(tr("Choose at least one event"))
        out["events"] = ",".join(e for e in WH_EVENTS if e in ev)
    if "enabled" in b:
        if not isinstance(b["enabled"], bool):
            raise BadInput(tr("Invalid value: {0}", "enabled"))
        out["enabled"] = 1 if b["enabled"] else 0
        if b["enabled"]:
            out["disabled_reason"] = ""
    return out


@app.get("/api/me/webhooks")
def webhooks_list():
    c = db()
    return jsonify(enabled=WH_ON, events=list(WH_EVENTS), backoff=WH_BACKOFF,
                   hooks=[wh_public(c, r) for r in c.execute("SELECT * FROM webhooks WHERE user_id=? AND agent=0 ORDER BY id", (me(),))])


@app.post("/api/me/webhooks")
def webhook_create():
    """{name, url, events: [...]} -> the webhook + its signing secret (shown this once)."""
    need_wh()
    c = db()
    f = wh_fields(c, body())
    if c.execute("SELECT COUNT(*) FROM webhooks WHERE user_id=? AND agent=0", (me(),)).fetchone()[0] >= WH_MAX:
        return err(tr("At most {0} webhooks", WH_MAX), 409)
    ts, secret = iso(now_utc()), "whsec_" + secrets.token_urlsafe(32)
    wid = c.execute("INSERT INTO webhooks(user_id,name,url,events,secret,enabled,created_at,updated_at) VALUES(?,?,?,?,'',?,?,?)",
                    (me(), f["name"], f["url"], f["events"], f.get("enabled", 1), ts, ts)).lastrowid
    c.execute("UPDATE webhooks SET secret=? WHERE id=?", (seal(c, f"webhook:{wid}", secret), wid))
    c.commit()
    return jsonify({**wh_public(c, need_webhook(c, wid)), "secret": secret}), 201


@app.patch("/api/me/webhooks/<int:wid>")
def webhook_update(wid):
    need_wh()
    c = db()
    need_webhook(c, wid)
    f = wh_fields(c, body(), old=True)
    if f:
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE webhooks SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), wid])
        if f.get("enabled") == 0:
            c.execute("DELETE FROM webhook_queue WHERE webhook_id=?", (wid,))
        c.commit()
    return jsonify(wh_public(c, need_webhook(c, wid)))


@app.delete("/api/me/webhooks/<int:wid>")
def webhook_delete(wid):
    c = db()
    need_webhook(c, wid)
    c.execute("DELETE FROM webhooks WHERE id=?", (wid,))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/me/webhooks/<int:wid>/secret")
def webhook_secret(wid):
    """A new signing secret (the old one stops at once); shown this once."""
    need_wh()
    c = db()
    need_webhook(c, wid)
    secret = "whsec_" + secrets.token_urlsafe(32)
    c.execute("UPDATE webhooks SET secret=?, updated_at=? WHERE id=?", (seal(c, f"webhook:{wid}", secret), iso(now_utc()), wid))
    c.commit()
    return jsonify(secret=secret)


@app.post("/api/me/webhooks/<int:wid>/test")
def webhook_test(wid):
    """Sends a "ping" event right now (no retries) and answers with the result; it shows in the delivery log."""
    need_wh()
    c = db()
    w = need_webhook(c, wid)
    keys = [(f"whtest:{me()}", WH_TEST_LIMIT)]
    if _rate_blocked(keys):
        return err(tr("Too many tests, please wait a few minutes"), 429)
    _rate_fail(keys)
    delivery = str(uuid.uuid4())
    payload = {"id": delivery, "event": "ping", "created_at": iso(now_utc()), "webhook_id": wid, "actor": wh_actor(c),
               "via": "web", "data": {"message": "Kalmido webhook test"}}
    ok, status, ms, errc = wh_send(w["url"], unseal(c, f"webhook:{wid}", w["secret"]), "ping", delivery, 1,
                                   json.dumps(payload).encode(), wh_allow(c))
    wh_log(c, wid, delivery, "ping", 1, ok, status, errc, ms)
    c.commit()
    return jsonify(ok=ok, status=status, ms=ms, error=errc, error_text=wh_err_text(errc, status) if errc else "")


@app.get("/api/me/webhooks/<int:wid>/log")
def webhook_log(wid):
    c = db()
    need_webhook(c, wid)
    return jsonify(items=[{"delivery": r["delivery"], "event": r["event"], "attempt": r["attempt"], "ok": bool(r["ok"]),
                           "status": r["status"], "error": r["error"], "error_text": wh_err_text(r["error"], r["status"]) if r["error"] else "",
                           "ms": r["ms"], "created_at": r["created_at"]}
                          for r in c.execute("SELECT * FROM webhook_log WHERE webhook_id=? ORDER BY id DESC LIMIT ?", (wid, WH_LOG_KEEP))])
