"""Notifications: ntfy, Web Push (RFC 8030 / 8291 / 8292), reminders and nags, the watchdog tick and loop."""
import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import has_request_context, request

from ..core.config import _origin, APP_NAME, NTFY_TOKEN, NTFY_URL, PUBLIC_URL, safe_urlopen, TZ, WATCHDOG_INTERVAL
from ..core.schema import USER_DEFAULTS
from ..core.i18n import LANGS, short_day, tr, trn
from ..core.db import bump, connect, inbox_default, iso, local_now, now_utc, parse_iso, uset, usettings
from ..accounts.session import GATE
from ..core.access import task_visible, vis_sql
from ..tasks.validation import NAG_HOUR_CAP, NAG_MINUTES, valid_hm
from ..tasks.tasks import _wd_followups
from ..integrations.paperless import paperless_poll
from ..collab.comments import collab_on, task_push_tick
from ..collab.news import news_cleanup, news_unread, notif_ok
from ..personal.habits import pomo_close, pomo_elapsed, pomo_planned_end
from ..personal.timetrack import _num, time_watchdog


# ---------------------------------------------------------------- watchdog / ntfy

NTFY_TOPIC_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
PUSH_PRIORITIES = ("3", "4", "5")  # ntfy: 3 default / normal, 4 high, 5 urgent (max)


def push_prio(s, floor=None):
    """ntfy priority for a push to the user with settings s (user setting push_priority, default 4).
    floor: a minimum for pushes that are more urgent by nature (reminder of a high-priority task,
    timer stopped automatically): they never go out BELOW 4, even when the user chose 3."""
    p = str((s or {}).get("push_priority") or USER_DEFAULTS["push_priority"])
    p = p if p in PUSH_PRIORITIES else USER_DEFAULTS["push_priority"]
    return str(max(int(p), floor)) if floor else p


def ntfy(title, msg, prio="4", click=None, topic=None, actions=None, admin=False):
    """One ntfy message. admin = an admin alert (not counted in the "ntfy failing" streak it would report)."""
    from ..notify.alerts import aa_err, aa_fail, aa_ok
    if not topic or not NTFY_TOPIC_RE.fullmatch(topic):
        return False
    hdr = {"Title": title.encode("utf-8"), "Priority": prio}  # no Tags header: no emoji icon in the push
    if click:
        hdr["Click"] = click
    if NTFY_TOKEN:
        hdr["Authorization"] = f"Bearer {NTFY_TOKEN}"
    if actions:  # view actions open the browser (login cookie), http actions could not pass a login proxy
        hdr["Actions"] = "; ".join(f"view, {label}, {url}" for label, url in actions)
    try:
        req = urllib.request.Request(f"{NTFY_URL}/{topic}", data=msg.encode("utf-8"), headers=hdr)
        with safe_urlopen(req, timeout=10) as r:
            r.read()
        if not admin:
            aa_ok("ntfy")
        return True
    except Exception as e:  # noqa: BLE001
        print("ntfy error:", e, flush=True)
        if not admin:
            aa_fail("ntfy", aa_err(e))
        return False


# ---------------------------------------------------------------- Web Push (RFC 8030 / 8291 / 8292)
# Second push channel next to ntfy, no extra app: the browser's own push service delivers it (FCM for
# Chrome / Edge / Samsung Internet on Android, Mozilla autopush for Firefox, Apple for Safari and iOS
# home-screen apps, WNS for Edge on Windows). Each payload is end-to-end encrypted with the keys of the
# subscription (aes128gcm) and signed with the instance's VAPID key (generated on first start, private key
# only in the DB, never sent to a client); the push service sees the endpoint, size and timing, never the text.
# SSRF: the server only ever POSTs to endpoints on WEBPUSH_HOSTS (https, port 443). KALMIDO_WEBPUSH_HOSTS adds
# entries: "host", "*.domain" or an exact origin "http(s)://host:port" (the only way to allow plain http).
WEBPUSH_ON = os.environ.get("KALMIDO_WEBPUSH", "1").strip().lower() not in ("0", "false", "no", "off")
WEBPUSH_HOSTS = ["fcm.googleapis.com",            # Chrome, Edge (Android), Samsung Internet, Opera, Brave, Vivaldi
                 "*.push.services.mozilla.com",   # Firefox (updates.push.services.mozilla.com)
                 "web.push.apple.com", "*.push.apple.com",  # Safari (macOS 13+), iOS / iPadOS 16.4+ home-screen apps
                 "*.notify.windows.com"]          # Edge on Windows (WNS)
WEBPUSH_ORIGINS = set()
for _e in (x.strip().lower() for x in os.environ.get("KALMIDO_WEBPUSH_HOSTS", "").split(",")):
    if _e.startswith(("http://", "https://")):
        _o = _origin(_e)
        if _o:
            WEBPUSH_ORIGINS.add(_o)
    elif _e and re.fullmatch(r"(\*\.)?[a-z0-9.-]+\.[a-z]{2,}", _e):
        WEBPUSH_HOSTS.append(_e)
VAPID_SUBJECT = os.environ.get("KALMIDO_VAPID_SUBJECT", "").strip() or \
    (PUBLIC_URL if PUBLIC_URL.startswith("https://") else "mailto:admin@example.com")
WEBPUSH_MAX_SUBS = 20       # devices per user
WEBPUSH_MAX_PAYLOAD = 3000  # bytes of JSON (one aes128gcm record, the push services accept 4096 bytes in total)
PUSH_CHANNELS = ("ntfy", "webpush", "both")
_VAPID = {}


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s):
    s = str(s or "").strip().rstrip("=")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,2000}", s):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _vapid_load(d):
    key = ec.derive_private_key(int.from_bytes(_b64u_dec(d), "big"), ec.SECP256R1())
    _VAPID.update(key=key, pub=_b64u(key.public_key().public_bytes(serialization.Encoding.X962,
                                                                    serialization.PublicFormat.UncompressedPoint)), jwt={})


def vapid_public():
    return _VAPID.get("pub", "")


def webpush_endpoint_ok(url):
    """True when url is a push endpoint the server may POST to: https on port 443 at an allow-listed push
    service, or an exact origin from KALMIDO_WEBPUSH_HOSTS. Everything else (internal hosts, IPs, other
    ports, credentials in the URL) is refused, so a crafted subscription cannot make the server fetch it."""
    if not isinstance(url, str) or len(url) > 1024 or re.search(r"[\s\\]", url):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if not host or p.username or p.password or p.fragment or host.endswith("."):
        return False
    if p.scheme == "https" and port in (None, 443):
        for h in WEBPUSH_HOSTS:
            if host == h or (h.startswith("*.") and host.endswith(h[1:]) and len(host) > len(h) - 1):
                return True
    return _origin(url) in WEBPUSH_ORIGINS


def webpush_encrypt(p256dh, auth, plaintext, salt=None, eph=None):
    """RFC 8291 message encryption (aes128gcm, one record): salt | rs | idlen | server key | ciphertext."""
    ua_pub, secret = _b64u_dec(p256dh), _b64u_dec(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    eph = eph or ec.generate_private_key(ec.SECP256R1())
    as_pub = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = eph.exchange(ec.ECDH(), ua_key)
    prk_key = hmac.new(secret, shared, hashlib.sha256).digest()
    ikm = hmac.new(prk_key, b"WebPush: info\x00" + ua_pub + as_pub + b"\x01", hashlib.sha256).digest()
    salt = salt or os.urandom(16)
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    cek = hmac.new(prk, b"Content-Encoding: aes128gcm\x00\x01", hashlib.sha256).digest()[:16]
    nonce = hmac.new(prk, b"Content-Encoding: nonce\x00\x01", hashlib.sha256).digest()[:12]
    ct = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02 = last record, no padding
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + ct


def vapid_header(endpoint):
    """RFC 8292: 'vapid t=<ES256 JWT for the endpoint's origin>, k=<public key>'; a JWT is reused for 1 h."""
    p = urllib.parse.urlsplit(endpoint)
    aud, now = f"{p.scheme}://{p.netloc}", int(time.time())
    hit = _VAPID["jwt"].get(aud)
    if not hit or hit[1] - now < 11 * 3600:
        exp = now + 12 * 3600
        seg = [_b64u(json.dumps(x, separators=(",", ":")).encode())
               for x in ({"typ": "JWT", "alg": "ES256"}, {"aud": aud, "exp": exp, "sub": VAPID_SUBJECT})]
        r, s = decode_dss_signature(_VAPID["key"].sign(".".join(seg).encode(), ec.ECDSA(hashes.SHA256())))
        hit = (".".join(seg) + "." + _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big")), exp)
        _VAPID["jwt"][aud] = hit
    return f"vapid t={hit[0]}, k={_VAPID['pub']}"


def webpush_send(sub, payload, prio="4", ttl=86400, topic=None):
    """One encrypted push to one subscription. Returns (HTTP status or 0 = not sent / network error, Retry-After)."""
    if not webpush_endpoint_ok(sub["endpoint"]) or not _VAPID.get("key"):
        return 0, None
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    hdr = {"TTL": str(int(ttl)), "Urgency": "high" if str(prio) in ("4", "5") else "normal",
           "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
           "Authorization": vapid_header(sub["endpoint"])}
    if topic and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", topic):  # push service replaces an undelivered one with the same topic
        hdr["Topic"] = topic
    try:
        req = urllib.request.Request(sub["endpoint"], data=webpush_encrypt(sub["p256dh"], sub["auth"], data),
                                     headers=hdr, method="POST")
        with safe_urlopen(req, timeout=10) as r:
            r.read(4096)
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Retry-After") if e.headers else None
    except Exception as e:  # noqa: BLE001
        print("webpush error:", urllib.parse.urlsplit(sub["endpoint"]).hostname, type(e).__name__, e, flush=True)
        return 0, None


def webpush_user(uid, payload, prio="4", ttl=86400, topic=None, only=None, stats=None):
    """Push to every subscribed device of the user (only: one subscription id). Returns the number of devices
    whose push service accepted it. 404 / 410 = subscription gone -> removed; 429 -> no sends until Retry-After;
    400 / 401 / 403 five times in a row -> removed; 413 = payload too large (logged). stats (dict): gets
    "subs" = the number of subscriptions tried or paused (admin alert "fell back to ntfy")."""
    from ..notify.alerts import aa_count, aa_fail, aa_ok
    if not WEBPUSH_ON:
        return 0
    c = connect()
    try:
        q, a = "SELECT * FROM push_subs WHERE user_id=?", [uid]
        if only is not None:
            q, a = q + " AND id=?", a + [only]
        ok, now = 0, time.time()
        subs = c.execute(q, a).fetchall()
        if stats is not None:
            stats["subs"] = len(subs)
        for sub in subs:
            if sub["backoff_until"] > now:
                continue
            # 2.0.5: a real push also carries the tags of this device's notifications that were handled elsewhere
            # (the only way on iOS, see push_dismiss_tick); the service worker closes them before showing this one
            drop = [r[0] for r in c.execute("SELECT tag FROM push_tags WHERE sub_id=? AND handled_at IS NOT NULL AND tag!=? "
                                            "ORDER BY handled_at LIMIT 30", (sub["id"], payload.get("tag") or ""))]
            st, retry = webpush_send(sub, {**payload, "dismiss": drop} if drop else payload, prio, ttl, topic)
            host = urllib.parse.urlsplit(sub["endpoint"]).hostname
            if (st == 0 and webpush_endpoint_ok(sub["endpoint"])) or st >= 500:
                aa_fail("webpush:" + (host or "?"), f"HTTP {st}" if st else "network")
            elif st:
                aa_ok("webpush:" + (host or "?"))
            if 200 <= st < 300:
                ok += 1
                c.execute("UPDATE push_subs SET last_ok=?, fails=0 WHERE id=?", (iso(now_utc()), sub["id"]))
                push_tag_sent(c, sub["id"], payload.get("tag"), drop)
            elif st in (404, 410):
                c.execute("DELETE FROM push_subs WHERE id=?", (sub["id"],))
                aa_count("webpush", "removed", f"{uid}|{sub['label'][:60]}|{st}")
                print(f"webpush: subscription {sub['id']} of user {uid} is gone ({st}, {host}), removed", flush=True)
            elif st == 429:
                try:
                    wait = min(max(int(retry), 10), 3600)
                except (TypeError, ValueError):
                    wait = 60
                c.execute("UPDATE push_subs SET backoff_until=? WHERE id=?", (now + wait, sub["id"]))
                print(f"webpush: rate limited by {host}, pausing subscription {sub['id']} for {wait} s", flush=True)
            elif st in (400, 401, 403):
                c.execute("UPDATE push_subs SET fails=fails+1 WHERE id=?", (sub["id"],))
                if c.execute("DELETE FROM push_subs WHERE id=? AND fails>=5", (sub["id"],)).rowcount:
                    aa_count("webpush", "removed", f"{uid}|{sub['label'][:60]}|{st}")
                print(f"webpush: {host} rejected the push for subscription {sub['id']} ({st})", flush=True)
            elif st:
                print(f"webpush: {host} answered {st} for subscription {sub['id']}" +
                      (" (payload too large)" if st == 413 else ""), flush=True)
        c.commit()
        return ok
    finally:
        c.close()


# ---- 2.0.5: close a notification on the other devices once it was handled on one (#311)
# Every task notification carries the tag "t-<task id>" (the same notification replaces itself). push_tags remembers per
# device which of them were sent. Completing the task, opening it (POST /api/push/handled, /seen) or reading its News item
# marks the tag handled on the user's OTHER devices (the device it happened on closes its own notification itself, it is
# identified by the X-Kalmido-Device header: its subscription id or endpoint). Then:
#   - the next real push to that device carries "dismiss": [tags] and the service worker closes them first (all devices);
#   - Android / desktop browsers: a "dismiss" push {type: 'dismiss', tags} after DISMISS_WAIT seconds of collecting, at most one
#     per device per DISMISS_GAP and DISMISS_DAY a day, and only for tags really sent there. Browsers require every push to
#     show a notification (userVisibleOnly) and tolerate the odd exception, hence the caps;
#   - Apple (web.push.apple.com): never a silent push (Safari revokes such subscriptions), only the piggyback above.
# Dismiss pushes do not count as delivered notifications (no last_ok, no admin alert bookkeeping).
DISMISS_WAIT = float(os.environ.get("KALMIDO_DISMISS_WAIT", "30"))
DISMISS_GAP = float(os.environ.get("KALMIDO_DISMISS_GAP", "60"))
DISMISS_DAY = int(os.environ.get("KALMIDO_DISMISS_DAY", "30"))
DISMISS_KEEP = 3 * 86400  # a notification older than this is not tracked any more
DISMISS_TAG = re.compile(r"(?:t|team|agents|prop)-\d{1,12}|\*")  # 2.19.0 (#668): chats, agents, proposals; "*" = all
# endpoint prefixes that behave like Apple's push service (tests: the fake push service)
WEBPUSH_APPLE = [x.strip() for x in os.environ.get("KALMIDO_WEBPUSH_APPLE", "").split(",") if x.strip()]


def webpush_apple(endpoint):
    host = (urllib.parse.urlsplit(endpoint or "").hostname or "").lower()
    return host == "push.apple.com" or host.endswith(".push.apple.com") or any(endpoint.startswith(p) for p in WEBPUSH_APPLE)


def push_tag_sent(c, sid, tag, dropped=()):
    """After a push was accepted: its tag is on that device now; the piggybacked dismiss tags are done."""
    if dropped:
        c.execute(f"DELETE FROM push_tags WHERE sub_id=? AND tag IN ({','.join('?' * len(dropped))})", (sid, *dropped))
    if tag and DISMISS_TAG.fullmatch(tag):
        c.execute("""INSERT INTO push_tags(sub_id,tag,sent_at) VALUES(?,?,?)
                     ON CONFLICT(sub_id,tag) DO UPDATE SET sent_at=excluded.sent_at, handled_at=NULL""", (sid, tag, time.time()))


def push_origin(c, uid):
    """The subscription of the device this request comes from (X-Kalmido-Device: its id or endpoint), if it is the user's."""
    v = (request.headers.get("X-Kalmido-Device") or "").strip()[:1100] if has_request_context() else ""
    if not v:
        return None
    r = c.execute("SELECT id FROM push_subs WHERE user_id=? AND " + ("id=?" if v.isdigit() else "endpoint=?"),
                  (uid, int(v) if v.isdigit() else v)).fetchone()
    return r["id"] if r else None


def push_handled(c, uid, task_ids, tags=()):
    """The user handled these tasks on one device: their notifications get closed on the other ones (caller commits).
    tags: more notification tags handled (2.19.0 #668: "team-<room>" read; "*" = everything, e.g. "Mark all as read")."""
    if not WEBPUSH_ON:
        return 0
    tags = list(dict.fromkeys([*(f"t-{int(t)}" for t in task_ids if t), *tags]))[:500]
    if not tags:
        return 0
    if "*" in tags:  # every notification of the user's other devices: one "*" entry per device
        here, now = push_origin(c, uid), time.time()
        for (sid,) in c.execute("SELECT id FROM push_subs WHERE user_id=?", (uid,)).fetchall():
            if sid != here:
                c.execute("INSERT INTO push_tags(sub_id,tag,sent_at,handled_at) VALUES(?,?,?,?) ON CONFLICT(sub_id,tag) "
                          "DO UPDATE SET sent_at=excluded.sent_at, handled_at=excluded.handled_at", (sid, "*", now, now))
    q = ",".join("?" * len(tags))
    here = push_origin(c, uid)
    if here:  # this device closes its own notification (app / service worker)
        c.execute(f"DELETE FROM push_tags WHERE sub_id=? AND tag IN ({q})", (here, *tags))
    return c.execute(f"""UPDATE push_tags SET handled_at=? WHERE handled_at IS NULL AND tag IN ({q})
                         AND sub_id IN (SELECT id FROM push_subs WHERE user_id=?)""", (time.time(), *tags, uid)).rowcount


def push_dismiss_tick(c):
    """Watchdog: one dismiss push per device with handled notifications (not Apple, rate-limited, see above)."""
    now = time.time()
    c.execute("DELETE FROM push_tags WHERE sent_at<?", (now - DISMISS_KEEP,))
    c.commit()
    if not WEBPUSH_ON:
        return
    day = date.today().isoformat()
    subs = c.execute("""SELECT s.*, MIN(t.handled_at) AS first FROM push_tags t JOIN push_subs s ON s.id=t.sub_id
                        WHERE t.handled_at IS NOT NULL GROUP BY s.id""").fetchall()
    for s in subs:
        n = s["dismiss_n"] if s["dismiss_day"] == day else 0
        if webpush_apple(s["endpoint"]) or s["first"] > now - DISMISS_WAIT or s["dismiss_at"] > now - DISMISS_GAP \
                or s["backoff_until"] > now or n >= DISMISS_DAY:
            continue
        tags = [r[0] for r in c.execute("SELECT tag FROM push_tags WHERE sub_id=? AND handled_at IS NOT NULL "
                                        "ORDER BY handled_at LIMIT 50", (s["id"],))]
        c.execute(f"DELETE FROM push_tags WHERE sub_id=? AND tag IN ({','.join('?' * len(tags))})", (s["id"], *tags))
        c.execute("UPDATE push_subs SET dismiss_at=?, dismiss_day=?, dismiss_n=? WHERE id=?", (now, day, n + 1, s["id"]))
        c.commit()
        st, _ = webpush_send(s, {"type": "dismiss", "tags": tags, "badge": badge_count(s["user_id"])}, "3", ttl=3600)
        if st in (404, 410):
            c.execute("DELETE FROM push_subs WHERE id=?", (s["id"],))
            c.commit()


def badge_count(uid):
    """2.19.0 (#668): the number on the app icon (Badging API): unread News + unread team chat messages."""
    from ..collab.teamchat import tchat_unread
    c = connect()
    try:
        s = usettings(c, uid)
        return (news_unread(c, uid, s) if collab_on(s) else 0) + tchat_unread(c, uid)
    except Exception:  # noqa: BLE001 - a badge never stops a push
        return 0
    finally:
        c.close()


def webpush_count(c, uid):
    return c.execute("SELECT COUNT(*) FROM push_subs WHERE user_id=?", (uid,)).fetchone()[0] if WEBPUSH_ON else 0


def push_channel(s):
    v = (s or {}).get("push_channel")
    return v if v in PUSH_CHANNELS else USER_DEFAULTS["push_channel"]


def push_reachable(c, uid, s):
    """The user can receive pushes at all: an ntfy topic or at least one subscribed device."""
    return bool(s.get("ntfy_topic")) or webpush_count(c, uid) > 0


def webpush_payload(title, msg, prio, click=None, actions=None, tag=None, task=None, due=None):
    """What the notification shows, nothing more: title, text, the in-app link (hash only), buttons."""
    hash_ = urllib.parse.urlsplit(click).fragment if click else ""
    p = {"title": (title or APP_NAME)[:200], "body": (msg or "")[:1000], "url": "/#" + hash_ if hash_ else "/",
         "prio": int(prio) if str(prio).isdigit() else 4, "ts": int(time.time() * 1000)}
    if tag:
        p["tag"] = tag[:64]
    if task:
        p["task"] = task
        if due:
            p["due"] = due
    if actions:  # at most 2 buttons (some platforms show no more): comments Reply + Done, reminders Done + Snooze
        acts = [{"action": urllib.parse.urlsplit(u).fragment.split("/")[0] or "open", "title": label[:40],
                 "url": "/#" + urllib.parse.urlsplit(u).fragment} for label, u in actions]
        # 2.7.0 (#413): nags carry a third one (Done, Stop reminding, Snooze); the service worker shows as many as the
        # platform can (Notification.maxActions, at least 2)
        p["actions"] = sorted(acts, key=lambda a: {"reply": 0, "done": 1}.get(a["action"], 2))[:3]
    while len(json.dumps(p, ensure_ascii=False).encode()) > WEBPUSH_MAX_PAYLOAD and len(p["body"]) > 1:
        p["body"] = p["body"][:len(p["body"]) * 3 // 4].rstrip("…") + "…"  # (long digest) shorten the text
    return p


def notify(uid, title, msg, prio="4", click=None, actions=None, tag=None, s=None, task=None, due=None, ttl=86400):
    """One push to one user over the channel of their settings (push_channel):
    ntfy = the ntfy topic; webpush = every subscribed device, and the ntfy topic instead while no device is
    subscribed or none accepted it; both = both. Returns True when at least one channel accepted it."""
    from ..notify.alerts import aa_count
    if s is None:
        c = connect()
        try:
            s = usettings(c, uid)
        finally:
            c.close()
    ch = push_channel(s)
    sent = 0
    if WEBPUSH_ON and ch in ("webpush", "both"):
        tag = tag or (urllib.parse.urlsplit(click).fragment.replace("/", "-") if click else None) or None
        st = {}
        sent = webpush_user(uid, {**webpush_payload(title, msg, prio, click, actions, tag, task, due), "badge": badge_count(uid)},
                            prio, ttl, topic=tag, stats=st)
        if not sent and st.get("subs"):  # devices exist but none accepted it (admin alert, counted per window)
            aa_count("webpush", "fallback", uid)
    if ch in ("ntfy", "both") or not sent:
        return ntfy(title, msg, prio, click, topic=s.get("ntfy_topic"), actions=actions) or sent > 0
    return True


def reminder_recipient(c, t, users):
    """Assignee, else the creator, else the list owner -- the first one that (still) sees the list."""
    for uid in (t["assignee_id"], t["created_by"], t["list_owner"]):
        if uid and uid in users and (uid == t["list_owner"] or task_visible(c, t["id"], uid, full=True)):
            return uid
    return None


def _wd_fail(c, what, key, e):
    """One broken row / user / section is logged and skipped, never stops the rest of the tick."""
    from ..notify.alerts import aa_count
    print(f"watchdog: {what} {key} skipped: {type(e).__name__}: {e}", flush=True)
    aa_count("watchdog", f"{what}|{type(e).__name__}", ":".join(map(str, key)) if isinstance(key, tuple) else key)
    try:
        c.rollback()
    except sqlite3.Error:
        pass


def _wd_section(c, name, fn, *a):
    try:
        fn(c, *a)
    except Exception as e:  # noqa: BLE001
        _wd_fail(c, "section", name, e)


def watchdog_tick(c):
    from ..notify.alerts import aa_tick
    from ..tasks.dayplan import _wd_review
    from ..agents.chat import chat_files_gc
    from ..agents.proposals import prop_cleanup
    from ..agents.usage import audit_cleanup, usage_cleanup
    from ..family.v1 import _wd_rotations
    _wd_section(c, "paperless", paperless_poll)  # 2.1.0: every connection (cheap without pending uploads)
    users = {r["id"]: r for r in c.execute("SELECT * FROM users WHERE disabled=0")}
    S, LG = {}, {}
    for uid in users:
        try:
            S[uid] = usettings(c, uid)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "settings of user", uid, e)
            S[uid] = dict(USER_DEFAULTS)
        LG[uid] = S[uid].get("lang") if S[uid].get("lang") in LANGS else "en"
    _wd_section(c, "collab pushes", task_push_tick, users, S, LG)
    _wd_section(c, "dismiss pushes", push_dismiss_tick)
    _wd_section(c, "news cleanup", news_cleanup)
    _wd_section(c, "usage cleanup", usage_cleanup)  # 2.1.1 (#326)
    _wd_section(c, "audit cleanup", audit_cleanup)  # 2.2.1 (#358)
    _wd_section(c, "proposal cleanup", prop_cleanup)  # 2.3.0
    _wd_section(c, "chat files cleanup", chat_files_gc)  # 2.13.1 (#465)
    _wd_section(c, "time", time_watchdog, users, S, LG)
    now = local_now()
    _wd_section(c, "reminders", _wd_reminders, users, S, LG, now)
    _wd_section(c, "nags", _wd_nags, users, S, LG, now)  # 2.7.0 (#413), after the reminders (a reminder counts as a nag)
    _wd_section(c, "follow-ups", _wd_followups, users, S, LG, now)  # 2.1.0 (#335)
    _wd_section(c, "rotations", _wd_rotations, users, S, LG, now)  # 2.19.0 (#653)
    _wd_section(c, "focus", _wd_focus, users, S, LG)
    _wd_section(c, "habits", _wd_habits, users, S, LG, now)
    _wd_section(c, "digest", _wd_digest, users, S, LG, now)
    _wd_section(c, "review", _wd_review, users, S, LG, now)  # 2.10.0 (#440)
    _wd_section(c, "admin alerts", aa_tick)


def _wd_reminders(c, users, S, LG, now):
    # task reminders -- fire once per (due, offset); skip if missed by > 6 h. Goes to the assignee,
    # unassigned tasks to their creator.
    rows = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox, l.owner_id AS list_owner, l.nag AS list_nag
                        FROM tasks t JOIN lists l ON l.id=t.list_id
                        WHERE t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL
                          AND t.reminders!='' AND l.archived=0""").fetchall()  # 1.5.1: none for archived lists
    for t in rows:
        try:
            _wd_reminder(c, t, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "reminder of task", t["id"], e)


def _wd_reminder(c, t, users, S, LG, now):
    from ..family.v1 import reminder_people
    rcpt = reminder_recipient(c, t, users)
    s = S.get(rcpt, USER_DEFAULTS)
    allday = s.get("allday_time") if valid_hm(s.get("allday_time")) else "09:00"
    base = datetime.fromisoformat(f"{t['due']}T{t['due_time'] or allday}").replace(tzinfo=TZ)
    fired = json.loads(t["reminded"] or "[]")
    changed = False
    for off in t["reminders"].split(","):
        if not off.strip():
            continue
        at = base - timedelta(minutes=int(off))
        key = f"{t['due']} {t['due_time'] or ''}|{off}"
        if key in fired or at > now:
            continue
        fired.append(key)
        changed = True
        if now - at > timedelta(hours=6):
            continue
        # 2.19.0 (#653): everyone who comes along gets it too (in their language, with their settings)
        for who in ([rcpt] if rcpt else []) + reminder_people(c, t, users, rcpt):
            sw, lgw = S.get(who, USER_DEFAULTS), LG.get(who, "en")
            if not notif_ok(c, who, sw, "reminder", "push"):
                continue  # 2.1.0 (#317): reminders can be switched off in the notification settings
            when = tr("all day", lg=lgw) if not t["due_time"] else tr("at {0}", t["due_time"], lg=lgw)
            day = tr("today", lg=lgw) if t["due"] == now.date().isoformat() else \
                short_day(date.fromisoformat(t["due"]), lgw)
            lname = tr("Inbox", lg=lgw) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
            notify(who, t["title"], tr("Due {0} {1} · {2}", day, when, lname, lg=lgw),
                   push_prio(sw, 4 if t["priority"] == 5 else None), f"{PUBLIC_URL}/#t/{t['id']}", s=sw,
                   actions=[(tr("Snooze", lg=lgw), f"{PUBLIC_URL}/#snooze/{t['id']}"),
                            (tr("Done|action", lg=lgw), f"{PUBLIC_URL}/#done/{t['id']}")],
                   task=t["id"], due=t["due"] if t["repeat"] else None)
        if not rcpt or not notif_ok(c, rcpt, s, "reminder", "push"):
            continue
        if nag_minutes(t["nag"], t["list_nag"]):  # 2.7.0 (#413): this reminder counts as a nag (the next one an interval later)
            c.execute("UPDATE tasks SET nag_at=? WHERE id=?", (f"{nag_key(t)}|{now.isoformat()}", t["id"]))
    if changed:
        c.execute("UPDATE tasks SET reminded=? WHERE id=?", (json.dumps(fired[-20:]), t["id"]))
        c.commit()


# ---- 2.7.0 (#413): nags. A task (or, by default, every task of its list) can repeat its reminder until it is done:
# every 5 / 10 / 15 / 30 / 60 minutes or daily, from its first reminder on (no reminders: from the due time). Pushes only,
# to the person a reminder goes to; never during that person's quiet hours (quiet_from / quiet_to: the nag comes when they
# end), never for a muted list bell or with "Reminders again" off in the notification settings. Dedupe: tasks.nag_at keeps
# the due date + the time of the last nag (a reminder that fires counts as one), so a tick, a restart or a second worker
# never sends one twice; a new date (snooze, repeat, edit) starts over. Completed, deleted, archived and undated tasks
# are not looked at, so the nags stop with them. At most NAG_HOUR_CAP nag pushes per person and hour.
_NAG_SENT = {}


def nag_minutes(task_nag, list_nag):
    """The interval of a task in minutes (0 = no nags): its own choice, else its list's default."""
    v = task_nag or ""
    if v == "off":
        return 0
    return NAG_MINUTES.get(v or (list_nag or ""), 0)


def nag_key(t):
    return f"{t['due']} {t['due_time'] or ''}"


def nag_last(raw, key):
    """The time of the last nag for this due date (None = none yet / the date changed since)."""
    k, _, at = (raw or "").partition("|")
    if k != key or not at:
        return None
    try:
        d = datetime.fromisoformat(at)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def in_quiet(s, now):
    """True during the person's quiet hours (local HH:MM range, may span midnight)."""
    a, b = s.get("quiet_from") or "", s.get("quiet_to") or ""
    if not (valid_hm(a) and valid_hm(b)) or a == b:
        return False
    hm = now.strftime("%H:%M")
    return a <= hm < b if a < b else hm >= a or hm < b


def nag_start(t, s):
    """When the nags begin: the first reminder (the largest offset), else the due time."""
    allday = s.get("allday_time") if valid_hm(s.get("allday_time")) else "09:00"
    base = datetime.fromisoformat(f"{t['due']}T{t['due_time'] or allday}").replace(tzinfo=TZ)
    offs = [int(x) for x in str(t["reminders"] or "").split(",") if re.fullmatch(r"-?\d{1,7}", x.strip())]
    return base - timedelta(minutes=max(offs)) if offs else base


def _wd_nags(c, users, S, LG, now):
    rows = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox, l.owner_id AS list_owner, l.nag AS list_nag
                        FROM tasks t JOIN lists l ON l.id=t.list_id
                        WHERE t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL AND l.archived=0
                          AND ((t.nag NOT IN ('', 'off')) OR (t.nag='' AND l.nag!=''))""").fetchall()
    for t in rows:
        try:
            _wd_nag(c, t, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "nag of task", t["id"], e)


def _wd_nag(c, t, users, S, LG, now):
    mins = nag_minutes(t["nag"], t["list_nag"])
    rcpt = reminder_recipient(c, t, users)
    if not mins or not rcpt:
        return
    s, lg = S.get(rcpt, USER_DEFAULTS), LG.get(rcpt, "en")
    if now < nag_start(t, s):
        return
    key, last = nag_key(t), nag_last(t["nag_at"], nag_key(t))
    if last and now < last + timedelta(minutes=mins) - timedelta(seconds=20):
        return
    if in_quiet(s, now) or not notif_ok(c, rcpt, s, "nag", "push", t["list_id"]):
        return
    sent = [x for x in _NAG_SENT.get(rcpt, []) if x > time.time() - 3600]
    c.execute("UPDATE tasks SET nag_at=? WHERE id=?", (f"{key}|{now.isoformat()}", t["id"]))  # before sending: never twice
    c.commit()
    if len(sent) >= NAG_HOUR_CAP:
        _NAG_SENT[rcpt] = sent
        return
    _NAG_SENT[rcpt] = sent + [time.time()]
    when = tr("all day", lg=lg) if not t["due_time"] else tr("at {0}", t["due_time"], lg=lg)
    day = tr("today", lg=lg) if t["due"] == now.date().isoformat() else \
        short_day(date.fromisoformat(t["due"]), lg)
    lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
    head = tr("Deadline", lg=lg) if t["deadline"] else tr("Still open", lg=lg)
    notify(rcpt, t["title"], tr("{0} · due {1} {2} · {3}", head, day, when, lname, lg=lg),
           push_prio(s, 4 if t["priority"] == 5 else None), f"{PUBLIC_URL}/#t/{t['id']}", s=s,
           actions=[(tr("Done|action", lg=lg), f"{PUBLIC_URL}/#done/{t['id']}"),
                    (tr("Stop reminding", lg=lg), f"{PUBLIC_URL}/#nagoff/{t['id']}"),
                    (tr("Snooze", lg=lg), f"{PUBLIC_URL}/#snooze/{t['id']}")],
           task=t["id"], due=t["due"] if t["repeat"] else None)


def _wd_focus(c, users, S, LG):
    # focus sessions finished while the tab is closed
    for p in c.execute("SELECT p.*, t.title FROM pomos p LEFT JOIN tasks t ON t.id=p.task_id "
                       "WHERE p.end IS NULL AND p.paused_at IS NULL").fetchall():
        try:
            _wd_pomo(c, p, users, S, LG)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "focus session", p["id"], e)


def _wd_pomo(c, p, users, S, LG):
    if p["minutes"] == 0:  # stopwatch: stops like a forgotten time-tracking timer (time_autostop_h, same rule)
        stop_h = _num(S.get(p["user_id"], {}).get("time_autostop_h")) if p["user_id"] in users else 0
        if stop_h > 0 and pomo_elapsed(p) >= stop_h * 3600:
            pomo_close(c, p, parse_iso(p["start"]) + timedelta(seconds=stop_h * 3600 + (p["paused_s"] or 0)), 0)
            bump(c)
            c.commit()
        return
    if pomo_elapsed(p) >= p["minutes"] * 60:
        # 1.2: past its planned end with no client open: finished on the server at the planned end, so it never
        # looks like "still running" (the time entry follows the time_focus setting as usual)
        pomo_close(c, p, pomo_planned_end(p), 1)
        bump(c)
        c.commit()
        if p["user_id"] not in users or p["notified"]:  # notified before 1.2 (left open back then): no second push
            return
        s, lg = S[p["user_id"]], LG[p["user_id"]]
        if p["kind"] == "focus":
            notify(p["user_id"], tr("Focus done", lg=lg), tr("{0} min{1}. Time for a break.", p["minutes"], " · " + p["title"] if p["title"] else "", lg=lg),
                   push_prio(s), f"{PUBLIC_URL}/#pomo", s=s)
        else:
            notify(p["user_id"], tr("Break is over", lg=lg), tr("Back to it.", lg=lg), push_prio(s), f"{PUBLIC_URL}/#pomo", s=s)


def _wd_habits(c, users, S, LG, now):
    # habit reminders
    today = now.date().isoformat()
    for h in c.execute("SELECT * FROM habits WHERE archived=0 AND remind_at!='' AND reminded_on!=?",
                       (today,)).fetchall():
        try:
            _wd_habit(c, h, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "habit", h["id"], e)


def _wd_habit(c, h, users, S, LG, now):
    today = now.date().isoformat()
    wd = str(now.isoweekday())
    if not valid_hm(h["remind_at"]) or (not h["per_week"] and wd not in str(h["days"])) \
            or now.strftime("%H:%M") < h["remind_at"]:
        return
    if h["per_week"]:  # "x times a week": no reminder once this week's target is reached
        mon = (now.date() - timedelta(days=now.weekday())).isoformat()
        done_w = c.execute("SELECT COUNT(*) FROM habit_logs WHERE habit_id=? AND day>=? AND day<=? AND count>=?",
                           (h["id"], mon, today, h["goal"])).fetchone()[0]
        if done_w >= h["per_week"]:
            return
    c.execute("UPDATE habits SET reminded_on=? WHERE id=?", (today, h["id"]))
    c.commit()
    if h["user_id"] not in users:
        return
    s, lg = S[h["user_id"]], LG[h["user_id"]]
    done = c.execute("SELECT count FROM habit_logs WHERE habit_id=? AND day=?", (h["id"], today)).fetchone()
    if not done or done[0] < h["goal"]:
        notify(h["user_id"], tr("Habit: {0}", h["name"], lg=lg), tr("Still open today.", lg=lg), push_prio(s),
               f"{PUBLIC_URL}/#habits", s=s, tag=f"habit-{h['id']}")


def _wd_digest(c, users, S, LG, now):
    # daily digest per user: tasks in my own lists (unassigned or mine) + tasks assigned to me
    for uid in users:
        try:
            _wd_digest_user(c, uid, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "digest of user", uid, e)


def _wd_digest_user(c, uid, S, LG, now):
    from ..integrations.mail import digest_mail_user
    today = now.date().isoformat()
    s, lg = S[uid], LG[uid]
    dt = s.get("digest_time") or ""
    if valid_hm(dt) and now.strftime("%H:%M") >= dt:  # 2.17.0 (#443): the summary by e-mail too (its own "sent" day)
        digest_mail_user(c, uid, s, today)
    if not valid_hm(dt) or s.get("digest_sent") == today or now.strftime("%H:%M") < dt:
        return
    uset(c, uid, "digest_sent", today)
    c.commit()
    rows = c.execute(f"""SELECT t.title, t.due, t.due_time FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.status=0 AND t.deleted_at IS NULL AND t.parent_id IS NULL
                           AND t.due IS NOT NULL AND t.due<=? AND l.archived=0
                           AND t.id NOT IN (SELECT item_id FROM sample_items WHERE kind='task')
                           AND ((l.owner_id=? AND (t.assignee_id IS NULL OR t.assignee_id=?))
                                OR (t.assignee_id=? AND t.list_id IN {vis_sql()}))
                         ORDER BY t.due, t.due_time IS NULL, t.due_time, t.priority DESC""",
                     (today, uid, uid, uid, uid, uid)).fetchall()
    if rows:
        over = sum(1 for r in rows if r["due"] < today)
        lines = [f"- {r['title']}" + (f" ({r['due_time']})" if r["due_time"] else "") for r in rows[:15]]
        head = trn("{0} task today", "{0} tasks today", len(rows), lg=lg) + \
            (tr(", {0} of them overdue", over, lg=lg) if over else "")
        notify(uid, tr("Today", lg=lg), head + "\n" + "\n".join(lines), push_prio(s), f"{PUBLIC_URL}/#today", s=s,
               tag="digest", ttl=12 * 3600)


def watchdog():
    from ..notify.alerts import aa_count
    while True:
        time.sleep(WATCHDOG_INTERVAL)
        try:
            with GATE.bg():
                c = connect()
                try:
                    watchdog_tick(c)
                finally:
                    c.close()
        except Exception as e:  # noqa: BLE001
            print("watchdog error:", e, flush=True)
            aa_count("watchdog", f"tick|{type(e).__name__}", "tick")
