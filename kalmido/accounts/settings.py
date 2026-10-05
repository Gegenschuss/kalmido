"""Per-user settings, the data export and Web Push subscriptions."""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives.asymmetric import ec
from flask import g, jsonify, Response

from ..core.config import app, PUBLIC_URL
from ..core.schema import USER_DEFAULTS
from ..core.i18n import LANGS, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, uset, usettings
from ..accounts.session import me, user_public
from ..lists.lists import clean_folder
from ..tasks.validation import clean_reminders, valid_hm
from ..integrations.paperless import pl_conns_for, pl_usable_ids
from ..collab.news import NEWS_GROUPS, notif_update
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- settings / export (per user)

SETTINGS_SERVER_ONLY = ("digest_sent", "digest_mail_sent", "review_sent", "ntfy_topic", "features_rev", "onboard", "sample_ask", "agent_share",
                        "purpose")
DASH_WIDGETS = ("wait", "today", "news", "chat", "projects", "pinned", "notes", "agents", "stats", "search", "family")  # 2.17.0 (#475), 2.19.0
SETTINGS_FLAGS = ("hide_blocked_today", "progress_subtasks", "ical_alarms", "time_focus", "paperless_keep", "celebrate", "cal_today",
                  "date_confirm", "digest_mail", "mail_from_me")
SETTINGS_NUM = {"pomo_focus": (0, 600), "pomo_short": (0, 600), "pomo_long": (0, 600), "pomo_long_every": (1, 50),
                "time_rounding": (0, 1440), "time_remind_h": (0, 1000), "time_autostop_h": (0, 1000), "time_target": (0, 24)}


def clean_setting(k, v):
    """A user setting from the client as the stored string; None = leave unchanged; BadInput if invalid.
    The watchdog reads these for every user, so malformed values are never stored."""
    from ..notify.push import PUSH_CHANNELS, PUSH_PRIORITIES
    bad = BadInput(tr("Invalid value: {0}", k))
    if isinstance(v, (dict, list)) and k not in ("folders", "folders_closed", "show_done_views"):
        raise bad
    sv = "" if v is None else str(v).strip()
    if k == "allday_time":
        if not valid_hm(sv):
            raise bad
        return sv
    if k in ("digest_time", "review_time"):
        if sv and not valid_hm(sv):
            raise bad
        return sv
    if k in ("work_start", "work_end"):  # 2.10.0 (#440)
        if not valid_hm(sv):
            raise bad
        return sv
    if k == "default_reminder":
        return clean_reminders(sv)
    if k in ("quiet_from", "quiet_to"):  # 2.7.0 (#413)
        if sv and not valid_hm(sv):
            raise bad
        return sv
    if k in ("hide_progress", "agents_hidden"):
        ids = [x.strip() for x in sv.split(",") if x.strip()]
        if len(ids) > 500 or not all(x.isdigit() and len(x) < 12 for x in ids):
            raise bad
        return ",".join(dict.fromkeys(ids))
    if k == "roadmap":
        return clean_roadmap_pref(v)
    if k == "dashboard":  # 2.17.0 (#475)
        if sv == "":
            return ""
        try:
            o = json.loads(v) if isinstance(v, str) else None
        except ValueError:
            raise bad from None
        if not isinstance(o, dict) or set(o) - {"order", "hidden"}:
            raise bad
        out = {}
        for key in ("order", "hidden"):
            xs = o.get(key, [])
            if not isinstance(xs, list) or not all(isinstance(x, str) and x in DASH_WIDGETS for x in xs):
                raise bad
            out[key] = list(dict.fromkeys(xs))
        return json.dumps(out)
    if k in SETTINGS_FLAGS:
        if sv in ("true", "True"):
            return "1"
        if sv in ("false", "False", ""):
            return "0"
        if sv not in ("0", "1"):
            raise bad
        return sv
    if k in SETTINGS_NUM:
        if sv == "":
            return None
        try:
            x = float(sv.replace(",", "."))
        except ValueError:
            raise bad from None
        lo, hi = SETTINGS_NUM[k]
        if not math.isfinite(x) or not lo <= x <= hi:
            raise bad
        return sv.replace(",", ".")
    if k == "tour":  # the client can only finish the tour (restarting it is local)
        if sv != "done":
            raise bad
        return sv
    if k == "ical_scope":
        if sv not in ("all", "mine"):
            raise bad
        return sv
    if k == "push_priority":
        if sv not in PUSH_PRIORITIES:
            raise bad
        return sv
    if k == "push_channel":
        if sv not in PUSH_CHANNELS:
            raise bad
        return sv
    if k == "news_kinds":
        ks = [x for x in sv.split(",") if x]
        if any(x not in NEWS_GROUPS for x in ks):
            raise bad
        return ",".join(dict.fromkeys(ks))
    if k in ("features", "nav_order"):
        if len(sv) > 500 or not re.fullmatch(r"[a-z_,]*", sv):
            raise bad
        return sv
    if k == "folders":
        try:
            arr = json.loads(v) if isinstance(v, str) else v
        except ValueError:
            raise bad from None
        if not isinstance(arr, list) or len(arr) > 200 or not all(isinstance(x, str) for x in arr):
            raise bad
        return json.dumps(list(dict.fromkeys(f for f in (clean_folder(x) for x in arr) if f)), ensure_ascii=False)
    if k == "folders_closed":  # 2.4.0 (#361): the folders this user folded in the sidebar (paths)
        try:
            arr = json.loads(v) if isinstance(v, str) else v
        except ValueError:
            raise bad from None
        if not isinstance(arr, list) or len(arr) > 400 or not all(isinstance(x, str) for x in arr):
            raise bad
        return json.dumps(list(dict.fromkeys(f for f in (clean_folder(x, False) for x in arr) if f)), ensure_ascii=False)
    if k == "show_done_views":
        return clean_done_views(v)
    if k == "comment_order":  # 2.4.2 (#386)
        if sv not in ("old", "new"):
            raise bad
        return sv
    if k == "time_currency":
        return sv[:8]
    if k == "lang":
        return sv
    return sv[:200]


DONE_VIEWS_MAX = 500


def clean_done_views(v):
    """Per-view "Show completed" (json object route key -> 0/1) -> stored json; BadInput if malformed."""
    bad = BadInput(tr("Invalid value: {0}", "show_done_views"))
    if v in (None, ""):
        return "{}"
    try:
        o = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(o) > DONE_VIEWS_MAX:
        raise bad
    out = {}
    for k, x in o.items():
        if not isinstance(k, str) or not 0 < len(k) <= 120 or x not in (0, 1, "0", "1"):
            raise bad
        out[k] = int(x)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


ROADMAP_KEY_RE = re.compile(r"(l\d{1,12}|f:.{1,80})", re.S)


def clean_roadmap_pref(v):
    """The roadmap view prefs (json object, see USER_DEFAULTS["roadmap"]) -> stored json; BadInput if malformed."""
    bad = BadInput(tr("Invalid value: {0}", "roadmap"))
    if v in (None, ""):
        return ""
    try:
        o = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(json.dumps(o)) > 20000:
        raise bad
    out = {}
    for k, x in o.items():
        if k == "v" and x in ("list", "timeline"):
            out[k] = x
        elif k == "z" and x in ("week", "month", "quarter"):
            out[k] = x
        elif k == "def" and x in ("auto", "c", "e"):
            out[k] = x
        elif k in ("po", "hd", "nd") and (x is None or isinstance(x, bool)):  # 2.0.6: nd = "No date" rows
            out[k] = x
        elif k == "who" and isinstance(x, str) and re.fullmatch(r"|me|none|\d{1,12}", x):
            out[k] = x
        elif k == "ls" and isinstance(x, list) and len(x) <= 500 and all(isinstance(i, int) and not isinstance(i, bool) and 0 < i < 10 ** 12 for i in x):
            out[k] = list(dict.fromkeys(x))
        elif k == "t" and isinstance(x, dict) and len(x) <= 1000 and all(isinstance(g_, str) and ROADMAP_KEY_RE.fullmatch(g_) and y in (0, 1) and not isinstance(y, bool) for g_, y in x.items()):
            out[k] = x
        else:
            raise bad
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


@app.patch("/api/settings")
def settings_update():
    b = body()
    c = db()
    vals = {}
    if "notify" in b:  # 2.1.0 (#317): the notification matrix
        cur = usettings(c, me())
        v = b["notify"]
        if isinstance(v, str):  # the web app: the whole stored value (undo / redo send the old one back, '' = defaults)
            vals["notify"] = notif_update({**cur, "notify": ""}, v)["notify"] if v.strip() else ""
            b = {k: x for k, x in b.items() if k != "notify"}
        else:  # a partial change {event: {news?, push?}} (writes notify + news_kinds)
            if "news_kinds" in b:
                cur["news_kinds"] = clean_setting("news_kinds", b["news_kinds"])
            vals.update(notif_update(cur, v))
            b = {k: x for k, x in b.items() if k not in ("notify", "news_kinds")}
    for k, v in b.items():
        if k in USER_DEFAULTS and k not in SETTINGS_SERVER_ONLY:
            if k == "lang" and v not in LANGS:
                continue
            v = clean_setting(k, v)  # BadInput: 400, nothing stored
            if v is not None:
                vals[k] = v
    for k, v in vals.items():
        uset(c, me(), k, v)
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/ntfy/test")
def ntfy_test():
    from ..notify.push import ntfy, push_prio
    s = usettings(db(), me())
    ok = ntfy("Kalmido: Test", tr("Notifications are arriving."), push_prio(s), PUBLIC_URL, topic=s["ntfy_topic"])
    return jsonify(ok=ok)


# ---- Web Push subscriptions (per device; see "Web Push" in the watchdog section)
def push_sub_public(r):
    return {"id": r["id"], "endpoint": r["endpoint"], "label": r["label"], "host": urllib.parse.urlsplit(r["endpoint"]).hostname,
            "created_at": r["created_at"], "last_ok": r["last_ok"]}


@app.get("/api/push/vapid")
def push_vapid():
    from ..notify.push import vapid_public, WEBPUSH_ON
    return jsonify(enabled=WEBPUSH_ON, key=vapid_public() if WEBPUSH_ON else "")


@app.get("/api/push/subs")
def push_subs_list():
    from ..notify.push import push_channel, WEBPUSH_ON
    c = db()
    s = usettings(c, me())
    rows = c.execute("SELECT * FROM push_subs WHERE user_id=? ORDER BY id", (me(),)).fetchall()
    return jsonify(enabled=WEBPUSH_ON, channel=push_channel(s), ntfy=bool(s.get("ntfy_topic")),
                   subs=[push_sub_public(r) for r in rows])


@app.post("/api/push/subs")
def push_subs_add():
    """Stores the PushSubscription of this browser (subscription.toJSON() + label) for the current user.
    The same endpoint again (another user logged in on this device, or a renewal) updates the row;
    'replaces' = the old endpoint after a pushsubscriptionchange (the row keeps its label);
    'sync' = the app's daily check-in: only updates a device that is still registered, never adds one."""
    from ..notify.push import _b64u_dec, webpush_endpoint_ok, WEBPUSH_MAX_SUBS, WEBPUSH_ON
    if not WEBPUSH_ON:
        return err(tr("Web Push is turned off on this server"), 404)
    b = body()
    ep, keys = b.get("endpoint"), b.get("keys") if isinstance(b.get("keys"), dict) else {}
    if not webpush_endpoint_ok(ep):
        return err(tr("This push service is not allowed on this server"))
    try:
        ua = _b64u_dec(keys.get("p256dh"))
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua)
        if len(ua) != 65 or len(_b64u_dec(keys.get("auth"))) != 16:
            raise ValueError("length")
    except (ValueError, TypeError):
        return err(tr("Invalid subscription"))
    label = re.sub(r"[\x00-\x1f<>]", "", str(b.get("label") or ""))[:60].strip()
    c = db()
    uid = me()
    old = b.get("replaces")
    if b.get("sync") and not c.execute("SELECT 1 FROM push_subs WHERE user_id=? AND endpoint IN (?,?)",
                                       (uid, ep, old if isinstance(old, str) else ep)).fetchone():
        return jsonify(known=False)  # daily check-in of a device that was removed meanwhile: not re-added
    if isinstance(old, str) and old != ep:
        r = c.execute("SELECT id, label FROM push_subs WHERE endpoint=? AND user_id=?", (old, uid)).fetchone()
        if r:
            label = label or r["label"]
            c.execute("DELETE FROM push_subs WHERE id=?", (r["id"],))
    if not c.execute("SELECT 1 FROM push_subs WHERE endpoint=? AND user_id=?", (ep, uid)).fetchone() \
            and c.execute("SELECT COUNT(*) FROM push_subs WHERE user_id=?", (uid,)).fetchone()[0] >= WEBPUSH_MAX_SUBS:
        return err(tr("Too many devices (at most {0}). Remove one first.", WEBPUSH_MAX_SUBS))
    c.execute("""INSERT INTO push_subs(user_id,endpoint,p256dh,auth,label,created_at) VALUES(?,?,?,?,?,?)
                 ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth,
                   label=CASE WHEN excluded.label!='' THEN excluded.label ELSE push_subs.label END, fails=0, backoff_until=0""",
              (uid, ep, keys["p256dh"].rstrip("="), keys["auth"].rstrip("="), label, iso(now_utc())))
    c.commit()
    r = c.execute("SELECT * FROM push_subs WHERE endpoint=?", (ep,)).fetchone()
    return jsonify({**push_sub_public(r), "known": True})


@app.delete("/api/push/subs/<int:sid>")
def push_subs_delete(sid):
    c = db()
    n = c.execute("DELETE FROM push_subs WHERE id=? AND user_id=?", (sid, me())).rowcount
    c.commit()
    return jsonify(ok=True) if n else err(tr("Not found"), 404)


@app.post("/api/push/unsubscribe")
def push_unsubscribe():
    """This device turned off (or logged out): remove the subscription with this endpoint, if it is mine."""
    c = db()
    n = c.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (str(body().get("endpoint") or ""), me())).rowcount
    c.commit()
    return jsonify(ok=True, removed=n)


@app.post("/api/push/handled")
def push_handled_api():
    """{tasks: [ids]}: the app opened these tasks on this device -> their notifications close on the user's other devices
    (only the user's own subscriptions are touched; ids of tasks they do not see match nothing of theirs)."""
    from ..notify.push import push_handled
    try:
        ids = [int(x) for x in (body().get("tasks") or [])][:50]
    except (TypeError, ValueError):
        return err(tr("Invalid data"))
    c = db()
    n = push_handled(c, me(), ids)
    c.commit()
    return jsonify(ok=True, marked=n)


@app.post("/api/push/test")
def push_test():
    """Test push. {"id": n} = only that device (Web Push); without = over the user's channel, like a reminder."""
    from ..notify.push import notify, push_channel, push_prio, webpush_count, webpush_payload, webpush_user
    c = db()
    s = usettings(c, me())
    sid = body().get("id")
    if sid is not None:
        if not isinstance(sid, int) or not c.execute("SELECT 1 FROM push_subs WHERE id=? AND user_id=?", (sid, me())).fetchone():
            return err(tr("Not found"), 404)
        n = webpush_user(me(), webpush_payload("Kalmido: Test", tr("Notifications are arriving."), push_prio(s), tag="test"),
                         push_prio(s), ttl=600, topic="test", only=sid)
        return jsonify(ok=n > 0, webpush=n)
    ok = notify(me(), "Kalmido: Test", tr("Notifications are arriving."), push_prio(s), PUBLIC_URL, s=s, tag="test")
    return jsonify(ok=ok, channel=push_channel(s), devices=webpush_count(c, me()))


@app.get("/api/export.json")
def export_json():
    """My data: lists I own (also shared ones, with their tasks incl. link / sections / files / comments /
    activity / custom fields + values / dependencies / status updates), my tags, habits, focus sessions, my time entries, filters and settings. Attachment files stay in data/attachments/."""
    c = db()
    uid = me()
    own = "(SELECT id FROM lists WHERE owner_id=?)"
    task_ids = f"(SELECT id FROM tasks WHERE list_id IN {own})"
    q = {
        "lists": ("SELECT * FROM lists WHERE owner_id=?", (uid,)),
        "list_members": (f"SELECT * FROM list_members WHERE list_id IN {own}", (uid,)),
        "sections": (f"SELECT * FROM sections WHERE list_id IN {own}", (uid,)),
        "tasks": (f"SELECT * FROM tasks WHERE list_id IN {own}", (uid,)),
        "task_tags": ("SELECT * FROM task_tags WHERE user_id=?", (uid,)),
        "habits": ("SELECT * FROM habits WHERE user_id=?", (uid,)),
        "habit_logs": ("SELECT * FROM habit_logs WHERE habit_id IN (SELECT id FROM habits WHERE user_id=?)", (uid,)),
        "pomos": ("SELECT * FROM pomos WHERE user_id=?", (uid,)),
        "filters": ("SELECT * FROM filters WHERE user_id=?", (uid,)),
        "attachments": (f"SELECT * FROM attachments WHERE task_id IN {task_ids}", (uid,)),
        "paperless_links": (f"SELECT * FROM paperless_links WHERE task_id IN {task_ids}", (uid,)),
        "comments": (f"SELECT * FROM comments WHERE task_id IN {task_ids} AND deleted_at IS NULL", (uid,)),
        "activity": (f"SELECT * FROM activity WHERE task_id IN {task_ids}", (uid,)),
        "settings": ("SELECT key, value FROM user_settings WHERE user_id=?", (uid,)),
        "templates": ("SELECT id, kind, name, data, created_at, updated_at FROM templates WHERE user_id=?", (uid,)),
        "time_entries": ("SELECT * FROM time_entries WHERE user_id=? ORDER BY start", (uid,)),
        "list_fields": (f"SELECT * FROM list_fields WHERE list_id IN {own}", (uid,)),
        "task_field_values": (f"SELECT * FROM task_field_values WHERE task_id IN {task_ids}", (uid,)),
        "task_deps": (f"SELECT * FROM task_deps WHERE task_id IN {task_ids} OR blocker_id IN {task_ids}", (uid, uid)),
        "list_status": (f"SELECT * FROM list_status WHERE list_id IN {own}", (uid,)),
        # 2.7.1 (#410): the overview of project lists (project files stay in data/attachments/lists/)
        "list_links": (f"SELECT * FROM list_links WHERE list_id IN {own}", (uid,)),
        "list_milestones": (f"SELECT * FROM list_milestones WHERE list_id IN {own}", (uid,)),
        "list_files": (f"SELECT * FROM list_files WHERE list_id IN {own}", (uid,)),
        "list_paperless": (f"SELECT * FROM list_paperless WHERE list_id IN {own}", (uid,)),
        # calendar subscriptions without the (encrypted) link / password
        "calendar_subscriptions": ("SELECT id, kind, name, color, visible, interval, url_hint, username, created_at FROM cal_subs "
                                   "WHERE user_id=?", (uid,)),
        # package B, without secrets: API tokens (no hash), webhooks (no signing secret), public links (no token / password)
        "api_tokens": ("SELECT id, name, prefix, scopes, expires_at, created_at, last_used_at FROM api_tokens WHERE user_id=?", (uid,)),
        "webhooks": ("SELECT id, name, url, events, enabled, created_at FROM webhooks WHERE user_id=?", (uid,)),
        "public_links": (f"SELECT list_id, mode, notes, password_hash IS NOT NULL AS has_password, expires_at, created_at FROM public_links "
                         f"WHERE list_id IN {own}", (uid,)),
    }
    data = {t: [dict(r) for r in c.execute(sql, args)] for t, (sql, args) in q.items()}
    pl_ok = pl_usable_ids(c, uid)  # 2.1.0: documents of connections I cannot use: no titles
    for p in data["paperless_links"] + data["list_paperless"]:
        if (p.get("conn_id") or 0) not in pl_ok:
            p.update(doc_id=None, title="", correspondent="", created="", **({"message": ""} if "message" in p else {}))
    for a in data["activity"]:
        if a["kind"] in ("paperless", "paperless_rm") and (json.loads(a["data"] or "{}").get("conn") or 0) not in pl_ok:
            a["data"] = "{}"
    # my own connections (name + URL; tokens never leave the server)
    data["paperless_connections"] = [{k: x[k] for k in ("id", "kind", "name", "url", "token_set")} for x in pl_conns_for(c, uid)]
    data["user"] = user_public(g.user)
    name = f"kalmido-export-{local_now():%Y-%m-%d}.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
