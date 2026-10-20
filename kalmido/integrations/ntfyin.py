"""2.142.0 C (#2150): the ntfy share inbox per person. Everyone can switch on an own topic (and optionally an own ntfy server
with a read token) in Settings > Notifications; what is shared to it lands in THAT person's inbox. The environment's
NTFY_INBOX_* inbox (core/pages.py ntfy_inbox_loop) stays as the fallback and works unchanged. The loop here polls (poll=1)
the topics of all switched-on people, one after the other, every failure is counted per person only."""
import json
import os
import secrets
import time
import urllib.parse

from flask import jsonify

from ..core.config import app, MAX_FILE_MB, NTFY_URL, ntfy_inbox_allowed, _origin
from ..core.i18n import tr
from ..core.db import body, connect, db, err, iso, now_utc
from ..accounts.session import GATE, me
from ..accounts.login import seal, unseal
from ..calendars.subscriptions import cal_allow, cal_http, CalError, cal_norm_url
from ..core.pages import ntfy_inbox_import

NI_ROUND_S = int(os.environ.get("KALMIDO_NTFYIN_TICK", "") or 20)  # s between two rounds (tests: 1)
NI_MAX_BYTES = 4 * 1024 * 1024  # one answer of a poll
NI_MAX_MSGS = 100        # messages taken per person and round
NI_BACKOFF_MAX = 600     # s, after repeated failures of one person
_NEXT = {}               # user id -> unix time of the next try (in memory)


def ni_new_topic():
    """A long random topic (24 characters, a-z A-Z 0-9 - _): not guessable."""
    return "kalmido-" + secrets.token_urlsafe(18)[:24]


def ni_row(c, uid):
    return c.execute("SELECT * FROM ntfy_inboxes WHERE user_id=?", (uid,)).fetchone()


def ni_base(r):
    return (r["url"] or NTFY_URL).rstrip("/")


def ni_public(c, uid):
    """What the client sees: never the token, only whether one is set."""
    r = ni_row(c, uid)
    return {"enabled": bool(r and r["enabled"]), "topic": (r["topic"] if r else "") or "", "url": (r["url"] if r else "") or "",
            "default_server": NTFY_URL.rstrip("/"), "has_token": bool(r and r["token"]),
            "last_ok": (r["last_ok"] if r else None), "fails": (r["fails"] if r else 0), "last_error": (r["last_error"] if r else "") or "",
            "suggest": ni_new_topic()}


@app.get("/api/me/ntfy-inbox")
def ni_get():
    return jsonify(ni_public(db(), me()))


@app.put("/api/me/ntfy-inbox")
def ni_put():
    """Switch on / off, topic, own server, read token (token: a string sets it, "" removes it, absent keeps it)."""
    from ..notify.push import NTFY_TOPIC_RE
    b = body()
    c = db()
    uid = me()
    old = ni_row(c, uid)
    enabled = bool(b["enabled"]) if "enabled" in b else bool(old and old["enabled"])
    topic = ni_new_topic() if b.get("new_topic") else str(b["topic"] if "topic" in b else (old["topic"] if old else "") or "").strip()
    url = str(b["url"] if "url" in b else (old["url"] if old else "") or "").strip()
    if url:
        url = cal_norm_url(url)
        if not url:
            return err(tr("Invalid value: {0}", "url"))
        url = url.rstrip("/")
    if enabled and not topic:
        topic = ni_new_topic()
    if topic and not NTFY_TOPIC_RE.fullmatch(topic):
        return err(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
    if enabled and not ntfy_inbox_allowed(url or NTFY_URL, topic):
        return err(tr("This topic on the public ntfy.sh can be guessed, anyone could publish to it. Use at least 16 characters (the dice button makes one) or an own ntfy server."))
    token = old["token"] if old else ""
    if "token" in b:
        t = str(b["token"] or "").strip()
        if len(t) > 400 or any(ch.isspace() or ord(ch) < 32 for ch in t):
            return err(tr("Invalid value: {0}", "token"))
        token = seal(c, f"ntfyin:{uid}", t)
    changed = not old or (old["topic"], old["url"]) != (topic, url) or (enabled and not old["enabled"])
    since = str(int(time.time())) if changed else (old["since"] or "")  # a new place: only messages from now on
    c.execute("INSERT INTO ntfy_inboxes(user_id,enabled,topic,url,token,since,fails,last_error,updated_at) VALUES(?,?,?,?,?,?,0,'',?) "
              "ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, topic=excluded.topic, url=excluded.url, token=excluded.token, "
              "since=excluded.since, fails=CASE WHEN ? THEN 0 ELSE ntfy_inboxes.fails END, "
              "last_error=CASE WHEN ? THEN '' ELSE ntfy_inboxes.last_error END, updated_at=excluded.updated_at",
              (uid, 1 if enabled else 0, topic, url, token, since, iso(now_utc()), changed, changed))
    _NEXT.pop(uid, None)
    c.commit()
    return jsonify(ni_public(c, uid))


# ---- the polling loop
def _fetch_att(c, r, base, token, allow):
    """The attachment of a message, only from this person's own ntfy server (same origin and path below it)."""
    def fetch(u):
        if not isinstance(u, str) or len(u) > 2000 or _origin(u) != _origin(base):
            return None
        bpath = urllib.parse.urlsplit(base).path.rstrip("/")
        path = urllib.parse.urlsplit(u).path
        if not path.startswith(bpath + "/") or "/../" in path + "/" or "/./" in path + "/":
            return None
        try:
            _st, _h, data, _u = cal_http(u, headers={"Authorization": f"Bearer {token}"} if token else {}, allow=allow,
                                         max_bytes=MAX_FILE_MB * 1024 * 1024, timeout=60, deadline=120)
        except CalError as e:
            print("ntfy inbox (person): attachment download failed:", e.stored(), flush=True)
            return None
        return data
    return fetch


def ni_poll_one(c, r):
    """One person: ask the topic for what is new, import it into their inbox. Raises CalError on a network problem."""
    uid = r["user_id"]
    base = ni_base(r)
    token = unseal(c, f"ntfyin:{uid}", r["token"]) if r["token"] else ""
    allow = cal_allow(c)
    since = r["since"] or str(int(time.time()))
    url = f"{base}/{urllib.parse.quote(r['topic'], safe='')}/json?poll=1&since={urllib.parse.quote(since, safe='')}"
    _st, _h, data, _u = cal_http(url, headers={"Authorization": f"Bearer {token}"} if token else {}, allow=allow,
                                 max_bytes=NI_MAX_BYTES, timeout=15, deadline=40)
    last = [since]

    def put_since(mid):
        last[0] = mid
        c.execute("UPDATE ntfy_inboxes SET since=? WHERE user_id=?", (mid, uid))
    who = {"uid": uid, "fetch": _fetch_att(c, r, base, token, allow), "since": put_since}
    n = 0
    for line in data.splitlines():
        if n >= NI_MAX_MSGS:
            break
        try:
            m = json.loads(line or b"{}")
        except ValueError:
            continue
        if isinstance(m, dict) and m.get("event") == "message" and isinstance(m.get("id"), str) and m["id"]:
            ntfy_inbox_import(c, m, who)
            n += 1
    return n


def ni_round():
    """One round over all switched-on people (an error of one never stops the others)."""
    c = connect()
    try:
        rows = c.execute("SELECT n.* FROM ntfy_inboxes n JOIN users u ON u.id=n.user_id WHERE n.enabled=1 AND u.disabled=0 ORDER BY n.user_id").fetchall()
        for r in rows:
            uid = r["user_id"]
            if _NEXT.get(uid, 0) > time.time():
                continue
            try:
                with GATE.bg():
                    ni_poll_one(c, r)
                c.execute("UPDATE ntfy_inboxes SET fails=0, last_error='', last_ok=? WHERE user_id=?", (iso(now_utc()), uid))
                _NEXT.pop(uid, None)
            except Exception as e:  # noqa: BLE001
                c.rollback()
                code = e.stored() if isinstance(e, CalError) else type(e).__name__
                fails = (r["fails"] or 0) + 1
                c.execute("UPDATE ntfy_inboxes SET fails=?, last_error=? WHERE user_id=?", (fails, str(code)[:40], uid))
                _NEXT[uid] = time.time() + min(NI_BACKOFF_MAX, NI_ROUND_S * 2 ** min(fails, 5))
                print("ntfy inbox (person", uid, "):", code, flush=True)
            c.commit()
    finally:
        c.close()


def ni_loop():
    while True:
        try:
            ni_round()
        except Exception as e:  # noqa: BLE001
            print("ntfy inbox (persons):", type(e).__name__, e, flush=True)
        time.sleep(NI_ROUND_S)
