"""Admin alerts via ntfy (recording, sending, settings)."""
import errno
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from flask import g, jsonify

from ..core.config import app, ATT_DIR, DB, NTFY_URL, PL_TOKEN, PUBLIC_URL
from ..core.schema import GLOBAL_DEFAULTS
from ..core.i18n import lang, LANGS, N_, tr, trn
from ..core.db import body, db, default_uid, err, gset, gsetting, iso, local_now, now_utc, usettings
from ..accounts.session import me
from ..tasks.validation import valid_hm
from ..integrations.paperless import PaperlessError, pl_legacy, pl_req
from ..personal.timetrack import BadInput
from ..accounts.users import need_admin
from ..notify.push import (
    ntfy, NTFY_TOPIC_RE, push_channel, PUSH_PRIORITIES, webpush_count, WEBPUSH_ON, webpush_payload, webpush_user,
)


# ---------------------------------------------------------------- admin alerts (ntfy, admins only)
# Operational warnings for the admins, independent of the users' push channel: always ntfy, to every enabled
# admin's own topic (or one shared admin topic). The code that notices something records it in memory
# (aa_now: one alert; aa_count: counted per window and summed up; aa_fail / aa_ok: an integration that keeps
# failing) and the watchdog sends it (aa_tick): each kind can be switched off, identical alerts (same kind +
# key) wait out a cooldown, at most N go out per hour, or everything is collected into one daily summary.
# Alerts only carry counts, ids, usernames, device labels, IPs and error classes -- never task titles,
# comments, list names or other content.
def _env_int(name, dflt, lo=1):
    try:
        return max(lo, int(os.environ.get(name, "") or dflt))
    except ValueError:
        return dflt


AA_ENV = os.environ.get("KALMIDO_ADMIN_ALERTS", "1").strip().lower() not in ("0", "false", "no", "off")
AA_TOPIC_ENV = os.environ.get("KALMIDO_ADMIN_TOPIC", "").strip()
AA_WINDOW = _env_int("KALMIDO_ADMIN_ALERT_WINDOW", 3600)  # s: counted events are summed up over this window
AA_KINDS = ("update", "webpush", "watchdog", "integration", "security", "storage")
AA_LABEL = {"update": N_("Update available"), "webpush": N_("Web Push delivery"), "watchdog": N_("Watchdog errors"),
            "integration": N_("Integration problems"), "security": N_("Security events"),
            "storage": N_("Storage and health"), "test": N_("Test alert")}
AA_BURST = 5          # failed logins / invalid tokens within the window before they are reported
AA_FAIL_ROW = 5       # outbound pushes failing in a row before they are reported
AA_KEEP = 500         # rows kept in admin_alerts
AA_LIST = 50          # rows shown in the settings
AA_STORAGE_EVERY = 600
AA_QC_EVERY = 86400
AA_PL_PROBE_EVERY = 600
# names of the watchdog parts in _wd_fail (shown in the alert)
AA_WD_WHAT = {"section": N_("a whole watchdog part"), "settings of user": N_("user settings"),
              "reminder of task": N_("reminders"), "focus session": N_("focus sessions"), "habit": N_("habit reminders"),
              "digest of user": N_("daily digests"), "paperless link": N_("Paperless uploads"),
              "collab push": N_("collaboration pushes"), "time entry": N_("time tracking"), "tick": N_("the watchdog loop")}
AA_SWITCH_LABEL = {"collab_all": N_("Collaboration for everyone"), "time_all": N_("Time tracking for everyone"),
                   "update_check": N_("Check daily for a new version"), "aa_on": N_("Admin alerts"),
                   "twofa_required": N_("Require two-factor authentication for built-in logins"),
                   "passkey_login": N_("Allow logging in with a passkey without the password"),
                   "oidc_autocreate": N_("Create accounts on the first OIDC login"), "bk_on": N_("Automatic backups"),
                   "public_links": N_("Public links to lists")}
_AA_LOCK = threading.Lock()
_AA = {"q": [], "b": {}, "int": {}, "disk_at": 0.0, "qc_at": 0.0, "pl_at": 0.0, "storage": {}, "qc": {}}


def _clamp_int(v, lo, hi, dflt):
    try:
        x = int(str(v).strip())
    except (TypeError, ValueError):
        return dflt
    return min(max(x, lo), hi)


def aa_cfg(c):
    v = {k: gsetting(c, k) for k in GLOBAL_DEFAULTS if k.startswith("aa_")}
    return {"on": AA_ENV and v["aa_on"] != "0", "topic": AA_TOPIC_ENV or v["aa_topic"],
            "prio": v["aa_prio"] if v["aa_prio"] in PUSH_PRIORITIES else "4",
            "kinds": [k for k in v["aa_kinds"].split(",") if k in AA_KINDS],
            "mode": "digest" if v["aa_mode"] == "digest" else "instant",
            "digest_time": v["aa_digest_time"] if valid_hm(v["aa_digest_time"]) else "08:00",
            "cooldown_h": _clamp_int(v["aa_cooldown_h"], 0, 168, 6), "max_hour": _clamp_int(v["aa_max_hour"], 1, 100, 10),
            "disk_pct": _clamp_int(v["aa_disk_pct"], 0, 99, 5), "disk_mb": _clamp_int(v["aa_disk_mb"], 0, 10_000_000, 1024),
            "integ_min": _clamp_int(v["aa_integ_min"], 1, 1440, 15)}


# ---- recording (any thread, never raises, never touches the database)
def Nn_(one, other):
    """A plural alert text (trn with the count n): marks both forms for tools/i18n_check.py."""
    return [one, other]


def aa_now(kind, key, text, args=(), n=None, click=None):
    """One alert, sent by the next watchdog tick. text: a text marked with N_ (or a plural pair from Nn_, + n); args: plain
    values or {"t": key} (translated when sent)."""
    try:
        with _AA_LOCK:
            if len(_AA["q"]) < 200:
                _AA["q"].append((kind, str(key)[:200], text, list(args), n, click))
    except Exception:  # noqa: BLE001
        pass


def aa_count(kind, key, item=None, **extra):
    """One event of (kind, key) in the current window; item (an id, a user, an IP) and the extra values are
    tallied and listed in the summary."""
    try:
        with _AA_LOCK:
            b = _AA["b"].get((kind, key))
            if b is None:
                if len(_AA["b"]) >= 200:
                    return
                b = _AA["b"][(kind, key)] = {"first": time.time(), "n": 0, "items": {}, "extra": {}}
            b["n"] += 1
            for d, v in [(b["items"], item)] + [(b["extra"].setdefault(k, {}), x) for k, x in extra.items()]:
                if v is None:
                    continue
                v = str(v)[:120]
                if v in d or len(d) < 200:
                    d[v] = d.get(v, 0) + 1
    except Exception:  # noqa: BLE001
        pass


def aa_fail(name, err):
    """Integration `name` failed (err: an error class / HTTP status); the streak starts with the first failure."""
    try:
        with _AA_LOCK:
            s = _AA["int"].setdefault(name, {"since": time.time(), "n": 0, "alerted": 0.0})
            s["n"] += 1
            s["err"] = str(err)[:80]
    except Exception:  # noqa: BLE001
        pass


def aa_ok(name):
    if name in _AA["int"]:
        with _AA_LOCK:
            _AA["int"].pop(name, None)


def aa_oserr(e):
    """Error class of a file system error, e.g. 'OSError ENOSPC'."""
    return type(e).__name__ + (f" {errno.errorcode.get(e.errno, e.errno)}" if getattr(e, "errno", None) else "")


def aa_err(e):
    """Error class for an alert (never the message: it could quote content)."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException):
        return f"{type(e).__name__}/{type(e.reason).__name__}"
    return type(e).__name__


# ---- sending
def aa_text(text, n, args, lg):
    a = [tr(x["t"], lg=lg) if isinstance(x, dict) else x for x in args]
    return trn(text[0], text[1], n or 0, *a, lg=lg) if isinstance(text, (list, tuple)) else tr(text, *a, lg=lg)


def aa_row_text(r, lg):
    try:
        text, n, args, _ = json.loads(r["tmpl"])
        return aa_text(text, n, args, lg)
    except (ValueError, TypeError, KeyError, IndexError):
        return r["message"]


# 2.5.2 (UX audit 2, K04): nothing goes to the PUBLIC ntfy.sh unless someone chose it. With NTFY_URL on ntfy.sh (the
# default) an admin on the default channel Web Push gets the alerts on their subscribed devices, and none at all while no
# device is subscribed (Settings > Notifications); ntfy only for the channels ntfy / both or a shared admin topic. With an
# own ntfy server (NTFY_URL elsewhere) the admins' own topics keep getting them, whatever channel they use (as before).
NTFY_PUBLIC = (urllib.parse.urlsplit(NTFY_URL).hostname or "").lower().rstrip(".") in ("ntfy.sh", "www.ntfy.sh")


def aa_admin_via(c, uid, s=None):
    """How the admin alerts reach this admin (without a shared admin topic): {"ntfy": topic or "", "webpush": n devices}."""
    s = s or usettings(c, uid)
    ch, t = push_channel(s), s.get("ntfy_topic") or ""
    dev = webpush_count(c, uid) if WEBPUSH_ON and ch in ("webpush", "both") else 0
    t_ok = bool(t) and bool(NTFY_TOPIC_RE.fullmatch(t)) and (ch in ("ntfy", "both") or not WEBPUSH_ON or not NTFY_PUBLIC)
    return {"ntfy": t if t_ok else "", "webpush": 0 if t_ok and ch == "webpush" else dev}


def aa_recipients(c, cfg):
    """[(via, target, language)]: ("ntfy", the shared admin topic, the first admin's language), else per enabled admin
    ("ntfy", own topic, language) and / or ("webpush", user id, language), see aa_admin_via (a topic shared by two admins
    gets one message)."""
    if cfg["topic"]:
        return [("ntfy", cfg["topic"], lang(c, default_uid(c)))] if NTFY_TOPIC_RE.fullmatch(cfg["topic"]) else []
    out, seen = [], set()
    for (uid,) in c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 ORDER BY id").fetchall():
        s = usettings(c, uid)
        lg = s.get("lang") if s.get("lang") in LANGS else "en"
        v = aa_admin_via(c, uid, s)
        if v["ntfy"] and v["ntfy"] not in seen:
            seen.add(v["ntfy"])
            out.append(("ntfy", v["ntfy"], lg))
        if v["webpush"]:
            out.append(("webpush", uid, lg))
    return out


def aa_deliver(c, cfg, title_fn, body_fn, click=None):
    """ntfy / Web Push to every recipient, each in their language. Returns the number of recipients that accepted it."""
    ok, click = 0, click or f"{PUBLIC_URL}/#settings"
    for via, target, lg in aa_recipients(c, cfg):
        if via == "ntfy":
            ok += 1 if ntfy(title_fn(lg), body_fn(lg), cfg["prio"], click, topic=target, admin=True) else 0
        else:
            ok += 1 if webpush_user(target, webpush_payload(title_fn(lg), body_fn(lg), cfg["prio"], click),
                                    cfg["prio"]) else 0
    return ok


def aa_title(kind, lg):
    return tr("Kalmido test alert", lg=lg) if kind == "test" else tr("Kalmido admin: {0}", tr(AA_LABEL[kind], lg=lg), lg=lg)


def aa_emit(c, cfg, kind, key, text, args=(), n=None, click=None):
    """Cooldown per (kind, key), then the daily summary queue or the hourly cap, then ntfy. Stores the alert
    (the settings list) and returns its state: sent | failed | queued | capped | cooldown | '' (off)."""
    if not cfg["on"] or (kind != "test" and kind not in cfg["kinds"]):
        return ""
    args, now = list(args), now_utc()
    if kind != "test" and cfg["cooldown_h"]:
        r = c.execute("SELECT id FROM admin_alerts WHERE kind=? AND key=? AND created_at>? AND state!='capped' "
                      "ORDER BY id DESC LIMIT 1", (kind, key, iso(now - timedelta(hours=cfg["cooldown_h"])))).fetchone()
        if r:
            c.execute("UPDATE admin_alerts SET repeats=repeats+1 WHERE id=?", (r[0],))
            c.commit()
            return "cooldown"
    sent, ok = None, 0
    if kind != "test" and cfg["mode"] == "digest":
        state = "queued"
    elif kind != "test" and c.execute("SELECT COUNT(*) FROM admin_alerts WHERE kind!='test' AND state IN ('sent','failed') "
                                      "AND sent_at>?", (iso(now - timedelta(hours=1)),)).fetchone()[0] >= cfg["max_hour"]:
        state = "capped"
    elif not aa_recipients(c, cfg):  # 2.5.2 (K04): nobody to send it to yet (no device / topic): only listed
        state = "listed"
    else:
        ok = aa_deliver(c, cfg, lambda lg: aa_title(kind, lg), lambda lg: aa_text(text, n, args, lg), click)
        state, sent = ("sent" if ok else "failed"), iso(now_utc())
    c.execute("INSERT INTO admin_alerts(kind,key,message,tmpl,created_at,sent_at,delivered,state) VALUES(?,?,?,?,?,?,?,?)",
              (kind, key[:200], aa_text(text, n, args, "en")[:1000],
               json.dumps([text, n, args, click], ensure_ascii=False), iso(now), sent, 1 if ok else 0, state))
    c.execute("DELETE FROM admin_alerts WHERE id<=(SELECT id FROM admin_alerts ORDER BY id DESC LIMIT 1 OFFSET ?)", (AA_KEEP,))
    c.commit()
    return state


def _aa_names(c, uids):
    uids = [int(u) for u in uids if str(u).isdigit()]
    return {r[0]: r[1] for r in c.execute(f"SELECT id, username FROM users WHERE id IN ({','.join('?' * len(uids)) or 'NULL'})", uids)}


def _aa_list(d, fmt=str, limit=8):
    items = sorted(d.items(), key=lambda x: (-x[1], x[0]))
    s = ", ".join(fmt(k) + (f" ×{v}" if v > 1 else "") for k, v in items[:limit])
    return s + (f", … (+{len(items) - limit})" if len(items) > limit else "")


def _aa_build(c, kind, key, b):
    """A finished window of counted events -> (key, text, args, n) for aa_emit, or None (below the threshold)."""
    items, mins = b["items"], max(1, AA_WINDOW // 60)
    if kind == "webpush" and key == "removed":
        names = _aa_names(c, [k.split("|", 1)[0] for k in items])

        def dev(k):
            uid, _, rest = k.partition("|")
            label, _, st = rest.rpartition("|")  # the label may contain "|"
            return f"{names.get(int(uid), '#' + uid) if uid.isdigit() else '?'} · {label or '?'} ({st})"
        return ("removed:" + ",".join(sorted(items))[:150],
                Nn_("{0} device was removed after its push service refused it: {1}",
                    "{0} devices were removed after their push service refused them: {1}"), [_aa_list(items, dev)], len(items))
    if kind == "webpush" and key == "fallback":
        names = _aa_names(c, items)
        users = {names.get(int(k), "#" + k) if k.isdigit() else k: v for k, v in items.items()}
        return ("fallback:" + ",".join(sorted(users))[:150],
                Nn_("{0} push went to ntfy instead because none of the user's devices accepted it: {1}",
                    "{0} pushes went to ntfy instead because none of the users' devices accepted them: {1}"), [_aa_list(users)], b["n"])
    if kind == "watchdog":
        what, _, cls = key.partition("|")
        ids = sorted(items, key=lambda x: (len(x), x))
        return (f"{key}|" + ",".join(ids[:10])[:150], Nn_("Watchdog: {0} entry of {1} was skipped ({2}), id: {3}",
                                                          "Watchdog: {0} entries of {1} were skipped ({2}), ids: {3}"),
                [{"t": AA_WD_WHAT.get(what, what)}, cls, ", ".join(ids[:10]) + (" …" if len(ids) > 10 else "")], len(ids))
    if kind == "security" and key == "logins":
        if b["n"] < AA_BURST:
            return None
        top = max(items, key=items.get) if items else "?"
        return ("logins:" + top, Nn_("{0} failed login within {1} min (users: {2}; IPs: {3})",
                                     "{0} failed logins within {1} min (users: {2}; IPs: {3})"),
                [mins, _aa_list(b["extra"].get("user", {})), _aa_list(items)], b["n"])
    if kind == "security" and key in ("drop", "ics", "api", "publink"):
        if b["n"] < AA_BURST:
            return None
        top = max(items, key=items.get) if items else "?"
        if key == "api":
            return ("api:" + top, Nn_("{0} API request with an invalid token within {1} min, from {2}",
                                      "{0} API requests with an invalid token within {1} min, from {2}"), [mins, _aa_list(items)], b["n"])
        if key == "publink":
            return ("publink:" + top, Nn_("{0} public link request with an unknown link or a wrong password within {1} min, from {2}",
                                          "{0} public link requests with an unknown link or a wrong password within {1} min, from {2}"),
                    [mins, _aa_list(items)], b["n"])
        if key == "drop":
            return ("drop:" + top, Nn_("{0} upload (/drop) with an invalid token within {1} min, from {2}",
                                       "{0} uploads (/drop) with an invalid token within {1} min, from {2}"), [mins, _aa_list(items)], b["n"])
        return ("ics:" + top, Nn_("{0} calendar feed request with an invalid link within {1} min, from {2}",
                                  "{0} calendar feed requests with an invalid link within {1} min, from {2}"), [mins, _aa_list(items)], b["n"])
    if kind == "storage" and key == "attachments":
        return ("attachments:" + ",".join(sorted(items))[:150], Nn_("Attachment folder: {0} write error ({1})",
                                                                   "Attachment folder: {0} write errors ({1})"), [_aa_list(items)], b["n"])
    return None


def _gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def aa_disk():
    try:
        du = shutil.disk_usage(os.path.dirname(os.path.abspath(DB)))
    except OSError:
        return {}
    return {"free": du.free, "total": du.total, "pct": round(du.free * 100 / du.total, 1) if du.total else 0.0}


def _aa_storage(c, cfg, now):
    if now - _AA["disk_at"] >= AA_STORAGE_EVERY:
        _AA["disk_at"] = now
        d = aa_disk()
        _AA["storage"] = {**d, "at": iso(now_utc()), "att_ok": os.access(ATT_DIR, os.W_OK)}
        if d and ((cfg["disk_pct"] and d["pct"] < cfg["disk_pct"]) or (cfg["disk_mb"] and d["free"] < cfg["disk_mb"] * 1024 * 1024)):
            aa_emit(c, cfg, "storage", "disk", N_("Low disk space on the data volume: {0} free ({1} %)."), [_gb(d["free"]), d["pct"]])
        if not _AA["storage"]["att_ok"]:
            aa_emit(c, cfg, "storage", "attachments:readonly", N_("The attachment folder is not writable."))
    if now - _AA["qc_at"] >= AA_QC_EVERY:
        _AA["qc_at"] = now
        rows = [str(r[0]) for r in c.execute("PRAGMA quick_check(20)").fetchall()]
        ok = rows == ["ok"]
        _AA["qc"] = {"at": iso(now_utc()), "ok": ok}
        if not ok:
            aa_emit(c, cfg, "storage", "quick_check", Nn_("Database integrity check (quick_check) failed: {1}",
                                                          "Database integrity check (quick_check) found {0} problems, the first: {1}"),
                    [rows[0][:160]], len(rows))


def _aa_integrations(c, cfg, ints, now):
    if PL_TOKEN and now - _AA["pl_at"] >= AA_PL_PROBE_EVERY:  # nobody used Paperless lately: ask it once
        _AA["pl_at"] = now
        try:
            pl_req(pl_legacy(), "/api/correspondents/?page_size=1&fields=id", timeout=8)
        except PaperlessError:
            pass
        ints = {k: dict(v) for k, v in _AA["int"].items()}
    for name, s in ints.items():
        if s.get("alerted") and now - s["alerted"] < max(cfg["cooldown_h"] * 3600, AA_WINDOW):
            continue
        mins = int((now - s["since"]) // 60)
        if name in ("inbox", "paperless"):
            if now - s["since"] < cfg["integ_min"] * 60:
                continue
            if name == "inbox":
                st = aa_emit(c, cfg, "integration", "inbox:" + s["err"],
                             N_("The ntfy share inbox has not reached its ntfy server for {0} min ({1})."), [mins, s["err"]])
            else:
                st = aa_emit(c, cfg, "integration", "paperless:" + s["err"], N_("Paperless has been failing for {0} min ({1})."),
                             [mins, s["err"]])
        elif s["n"] >= AA_FAIL_ROW and name == "oidc":
            st = aa_emit(c, cfg, "integration", "oidc:" + s["err"], N_("{0} logins with the OIDC provider in a row failed ({1})."),
                         [s["n"], s["err"]])
        elif s["n"] >= AA_FAIL_ROW and name == "ntfy":
            st = aa_emit(c, cfg, "integration", "ntfy:" + s["err"], N_("{0} ntfy pushes in a row failed ({1})."), [s["n"], s["err"]])
        elif s["n"] >= AA_FAIL_ROW and name.startswith("webpush:"):
            st = aa_emit(c, cfg, "integration", name + ":" + s["err"], N_("{0} Web Push deliveries in a row failed at {1} ({2})."),
                         [s["n"], name[8:], s["err"]])
        else:
            continue
        if st:
            with _AA_LOCK:
                if name in _AA["int"]:
                    _AA["int"][name]["alerted"] = now


def _aa_digest(c, cfg):
    """Daily summary at digest_time (and at once after switching back to instant) of the queued alerts."""
    lnow = local_now()
    if cfg["mode"] == "digest":
        today = lnow.date().isoformat()
        if lnow.strftime("%H:%M") < cfg["digest_time"] or gsetting(c, "aa_digest_sent") == today:
            return
        gset(c, "aa_digest_sent", today)
        c.commit()
    rows = c.execute("SELECT * FROM admin_alerts WHERE state='queued' ORDER BY id LIMIT 200").fetchall()
    if not rows:
        return

    def body(lg):
        lines = []
        for r in rows[:25]:
            lines.append(f"- {tr(AA_LABEL.get(r['kind'], r['kind']), lg=lg)}: {aa_row_text(r, lg)}")
        more = [tr("… and {0} more (Settings > Administration)", len(rows) - 25, lg=lg)] if len(rows) > 25 else []
        return trn("{0} alert since the last summary:", "{0} alerts since the last summary:", len(rows), lg=lg) + "\n" + "\n".join(lines + more)
    ok = aa_deliver(c, cfg, lambda lg: tr("Kalmido admin: daily summary", lg=lg), body)
    c.execute("UPDATE admin_alerts SET state='summarized', sent_at=?, delivered=? WHERE state='queued' AND id<=?",
              (iso(now_utc()), 1 if ok else 0, rows[-1]["id"]))
    c.commit()


def aa_tick(c):
    """Watchdog: send what was recorded since the last tick, close finished windows, integrations, storage checks,
    daily summary. Off (switch / env): everything recorded is dropped."""
    cfg = aa_cfg(c)
    now = time.time()
    with _AA_LOCK:
        q, _AA["q"] = _AA["q"], []
        due = [(k, b) for k, b in _AA["b"].items() if now - b["first"] >= AA_WINDOW]
        for k, _ in due:
            del _AA["b"][k]
        ints = {k: dict(v) for k, v in _AA["int"].items()}
    if not cfg["on"]:
        return
    for kind, key, text, args, n, click in q:
        aa_emit(c, cfg, kind, key, text, args, n, click)
    for (kind, key), b in due:
        a = _aa_build(c, kind, key, b)
        if a:
            aa_emit(c, cfg, kind, *a)
    if "integration" in cfg["kinds"]:
        _aa_integrations(c, cfg, ints, now)
    if "storage" in cfg["kinds"]:
        _aa_storage(c, cfg, now)
    _aa_digest(c, cfg)


def aa_switch(c, admin, key, value, cfg=None):
    """Security alert for a changed instance switch; cfg = send now with this config (switching alerts off)."""
    args = [admin["username"], {"t": AA_SWITCH_LABEL[key]}, {"t": N_("on|switch") if value else N_("off|switch")}]
    k = f"switch:{key}:{int(bool(value))}:{int(time.time())}"
    if cfg:
        aa_emit(c, cfg, "security", k, N_("{0} set “{1}” to {2}."), args)
    else:
        aa_now("security", k, N_("{0} set “{1}” to {2}."), args)


# ---- settings API (admins): Settings > Users > Whole server > Admin alerts
def aa_public(c):
    cfg, lg = aa_cfg(c), lang()
    items = []
    for r in c.execute("SELECT * FROM admin_alerts ORDER BY id DESC LIMIT ?", (AA_LIST,)).fetchall():
        items.append({"id": r["id"], "kind": r["kind"], "label": tr(AA_LABEL.get(r["kind"], r["kind"])), "message": aa_row_text(r, lg),
                      "created_at": r["created_at"], "sent_at": r["sent_at"], "delivered": bool(r["delivered"]),
                      "state": r["state"], "repeats": r["repeats"]})
    admins = []
    for u in c.execute("SELECT id, username FROM users WHERE is_admin=1 AND disabled=0 ORDER BY id").fetchall():
        v = aa_admin_via(c, u["id"])  # 2.5.2 (K04): topic = only where it really goes; devices = Web Push
        admins.append({"username": u["username"], "topic": v["ntfy"], "devices": v["webpush"], "me": u["id"] == me()})
    return {"env": AA_ENV, "topic_env": bool(AA_TOPIC_ENV), "on": gsetting(c, "aa_on") != "0",
            "topic": AA_TOPIC_ENV or gsetting(c, "aa_topic"), "prio": cfg["prio"], "kinds": cfg["kinds"],
            "all_kinds": [{"kind": k, "label": tr(AA_LABEL[k])} for k in AA_KINDS], "mode": cfg["mode"],
            "digest_time": cfg["digest_time"], "cooldown_h": cfg["cooldown_h"], "max_hour": cfg["max_hour"],
            "disk_pct": cfg["disk_pct"], "disk_mb": cfg["disk_mb"], "integ_min": cfg["integ_min"], "admins": admins,
            "ntfy_url": NTFY_URL, "ntfy_public": NTFY_PUBLIC, "webpush": WEBPUSH_ON,
            "storage": _AA["storage"], "quick_check": _AA["qc"], "items": items}


@app.get("/api/admin/alerts")
def admin_alerts_get():
    need_admin()
    return jsonify(aa_public(db()))


def _aa_clean(b):
    """Validated {setting key: stored value} from the PATCH body; BadInput on an invalid value."""
    out = {}

    def num(k, lo, hi):
        v = b[k]
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not re.fullmatch(r"\d{1,8}", str(v).strip()) \
                or not lo <= int(v) <= hi:
            raise BadInput(tr("Invalid value: {0}", k))
        return str(int(v))
    for k, v in b.items():
        if k == "on":
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", k))
            out["aa_on"] = "1" if v else "0"
        elif k == "topic":
            t = str(v or "").strip()
            if t and not NTFY_TOPIC_RE.fullmatch(t):
                raise BadInput(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
            out["aa_topic"] = t
        elif k == "prio":
            if str(v) not in PUSH_PRIORITIES:
                raise BadInput(tr("Invalid value: {0}", k))
            out["aa_prio"] = str(v)
        elif k == "kinds":
            if not isinstance(v, list) or not all(x in AA_KINDS for x in v):
                raise BadInput(tr("Invalid value: {0}", k))
            out["aa_kinds"] = ",".join(x for x in AA_KINDS if x in v)
        elif k == "mode":
            if v not in ("instant", "digest"):
                raise BadInput(tr("Invalid value: {0}", k))
            out["aa_mode"] = v
        elif k == "digest_time":
            if not valid_hm(v):
                raise BadInput(tr("Invalid value: {0}", k))
            out["aa_digest_time"] = v
        elif k in ("cooldown_h", "max_hour", "disk_pct", "disk_mb", "integ_min"):
            out["aa_" + k] = num(k, *{"cooldown_h": (0, 168), "max_hour": (1, 100), "disk_pct": (0, 99),
                                      "disk_mb": (0, 10_000_000), "integ_min": (1, 1440)}[k])
    return out


@app.patch("/api/admin/alerts")
def admin_alerts_patch():
    need_admin()
    c = db()
    vals = _aa_clean(body())
    before = aa_cfg(c)
    was_on, old_topic = gsetting(c, "aa_on") != "0", gsetting(c, "aa_topic")
    if vals.get("aa_on") == "0" and was_on:  # the last alert goes out with the old settings
        aa_switch(c, g.user, "aa_on", False, cfg=before)
    for k, v in vals.items():
        gset(c, k, v)
    if "aa_digest_time" in vals or vals.get("aa_mode") == "digest":
        gset(c, "aa_digest_sent", "")
    c.commit()
    if vals.get("aa_on") == "1" and not was_on:
        aa_switch(c, g.user, "aa_on", True)
    if "aa_topic" in vals and vals["aa_topic"] != old_topic and not AA_TOPIC_ENV:
        aa_now("security", f"topic:{int(time.time())}", N_("{0} changed the admin alert topic."), [g.user["username"]])
    _AA["disk_at"] = 0.0  # re-check the disk with the new thresholds on the next tick
    return jsonify(aa_public(c))


@app.post("/api/admin/alerts/test")
def admin_alerts_test():
    """A clearly labelled test alert with the saved settings (also while the switch is off), now."""
    need_admin()
    if not AA_ENV:
        return err(tr("Admin alerts are switched off by the server operator."), 409)
    c = db()
    cfg = {**aa_cfg(c), "on": True}
    if not aa_recipients(c, cfg):
        return err(tr("No admin can receive admin alerts yet: subscribe a device under Settings > Notifications or set an admin topic"), 409)
    st = aa_emit(c, cfg, "test", f"test:{int(time.time())}", N_("Test from {0}: admin alerts arrive on this topic."),
                 [g.user["username"]])
    return jsonify(ok=st == "sent", alerts=aa_public(c))


@app.delete("/api/admin/alerts")
def admin_alerts_clear():
    need_admin()
    c = db()
    c.execute("DELETE FROM admin_alerts")
    c.commit()
    return jsonify(aa_public(c))
