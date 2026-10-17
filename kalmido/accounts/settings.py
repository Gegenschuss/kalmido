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
from ..collab.news import NEWS_GROUPS, notif_update
from ..personal.timetrack import BadInput
from .layouts import LAYOUT_KEYS


# ---------------------------------------------------------------- settings / export (per user)

SETTINGS_SERVER_ONLY = ("digest_sent", "digest_mail_sent", "review_sent", "ntfy_topic", "features_rev", "onboard", "sample_ask", "agent_share",
                        "purpose", "evcals_hidden", "care_sent",
                        "brief_sent", "brief_read",  # 2.34.0 (#264)
                        "fav_asked")  # 2.46.1 (#1361): lists already offered as a favourite
SIDE_GROUPS = ("focus", "clients", "lists", "filters", "tags", "views", "areas", "team")  # 2.25.0 (UX-03); 2.39.1 (#1185): areas
DASH_WIDGETS = ("wait", "today", "news", "chat", "projects", "pinned", "notes", "agents", "stats", "search", "family", "kpi")  # 2.17.0 (#475), 2.19.0; 2.55.1: kpi (2.50.0 #1197, office admins)
SETTINGS_FLAGS = ("hide_blocked_today", "progress_subtasks", "ical_alarms", "time_focus", "celebrate", "cal_today",
                  "date_confirm", "digest_mail", "mail_from_me", "mail_trim_fwd", "mail_trim_eml",  # 2.49.0 (#971)
                  "today_inbox", "agent_push",  # 2.28.0 (#987): agent_push
                  "detail_cm_fold",  # 2.31.0 (#344)
                  "list_emoji",  # 2.32.0 (#1077)
                  "side_progress",  # 2.36.0 (#1117)
                  "cal_tasks",  # 2.36.1 (#1127)
                  "agent_steps_live", "agent_steps_always",  # 2.32.0 (#1081)
                  "show_done_default",  # 2.39.1 (#1214): "Hide completed" as the default of every view (0 = hide)
                  "show_done_new",  # 2.49.0 (#1535): new lists hide completed tasks
                  "fav_only",  # 2.40.0 (#1361): the sidebar shows only the favourites
                  "fav_quiet", "fav_suggest",  # 2.46.1 (#1361): quieter pushes from lists without a star; favourite suggestions
                  "person_colors",  # 2.47.1 (#1721): people in their account colour (0 = only agents coloured)
                  "list_color_dot",  # 2.53.0 (#1426): list colours only as the dot
                  "mods_all",  # 2.46.1 (#1591): "Switch on all modules" with the purpose
                  "tbl_accept")  # 2.53.0 C (#1424): accept "Urgent" on a task set by someone else
SETTINGS_NUM = {"pomo_focus": (0, 600), "pomo_short": (0, 600), "pomo_long": (0, 600), "pomo_long_every": (1, 50),
                "time_rounding": (0, 1440), "time_remind_h": (0, 1000), "time_autostop_h": (0, 1000), "time_target": (0, 24),
                "detail_split": (20, 85)}  # 2.31.0 (#344)


def clean_setting(k, v):
    """A user setting from the client as the stored string; None = leave unchanged; BadInput if invalid.
    The watchdog reads these for every user, so malformed values are never stored."""
    from ..notify.push import PUSH_CHANNELS, PUSH_PRIORITIES
    bad = BadInput(tr("Invalid value: {0}", k))
    if isinstance(v, (dict, list)) and k not in ("folders", "folders_closed", "show_done_views", "group_order", "folder_colors", *CAL_LIST_KEYS):
        raise bad
    sv = "" if v is None else str(v).strip()
    if k == "allday_time":
        if not valid_hm(sv):
            raise bad
        return sv
    if k in ("digest_time", "review_time", "brief_time"):  # 2.34.0 (#264): brief_time
        if sv and not valid_hm(sv):
            raise bad
        return sv
    if k in ("work_start", "work_end"):  # 2.10.0 (#440)
        if not valid_hm(sv):
            raise bad
        return sv
    if k == "default_reminder":
        return clean_reminders(sv)
    if k == "capacity_h":  # 2.23.0 (#463): working hours per week ('' = the default: 5 x the hours per day)
        if sv == "":
            return ""
        try:
            x = float(sv.replace(",", "."))
        except ValueError:
            raise bad from None
        if not math.isfinite(x) or not 0 <= x <= 168:
            raise bad
        return str(round(x, 2))
    if k in ("quiet_from", "quiet_to"):  # 2.7.0 (#413)
        if sv and not valid_hm(sv):
            raise bad
        return sv
    if k in ("hide_progress", "show_progress", "fav_lists", "agents_hidden"):  # 2.40.0: show_progress (#1190), fav_lists (#1361)
        ids = [x.strip() for x in sv.split(",") if x.strip()]
        if len(ids) > 500 or not all(x.isdigit() and len(x) < 12 for x in ids):
            raise bad
        return ",".join(dict.fromkeys(ids))
    if k == "roadmap":
        return clean_roadmap_pref(v)
    if k == "workspace":  # 2.28.0 (#935): all | private | org:<id> (an organisation the person belongs to)
        from ..accounts.orgs import user_orgs
        if sv in ("", "all", "private"):
            return sv or "all"
        m = re.fullmatch(r"org:(\d{1,9})", sv)
        if not m or int(m.group(1)) not in user_orgs(db(), me()):
            raise bad
        return sv
    if k == "sidebar":  # 2.25.0 (UX-03): {"order": [groups], "hidden": ["g:<group>" | "e:<entry>"]} ('' = default)
        if sv == "":
            return ""
        try:
            o = json.loads(v) if isinstance(v, str) else None
        except ValueError:
            raise bad from None
        if not isinstance(o, dict) or set(o) - {"order", "hidden"}:
            raise bad
        order, hidden = o.get("order", []), o.get("hidden", [])
        if not isinstance(order, list) or not all(isinstance(x, str) and x in SIDE_GROUPS for x in order) \
                or not isinstance(hidden, list) or len(hidden) > 60 \
                or not all(isinstance(x, str) and re.fullmatch(r"[ge]:[a-z_]{1,24}", x) for x in hidden):
            raise bad
        return json.dumps({"order": list(dict.fromkeys(order)), "hidden": list(dict.fromkeys(hidden))})
    if k == "dashboard":  # 2.17.0 (#475); 2.32.0 (#1063): the shape of every view layout (widths, phone arrangement)
        from .layouts import clean_layout
        try:
            return clean_layout(v if isinstance(v, str) else None, DASH_WIDGETS)
        except BadInput:
            raise bad from None
    if k in LAYOUT_KEYS:  # 2.32.0 (#1063)
        from .layouts import clean_layout
        try:
            return clean_layout(v if isinstance(v, str) else None)
        except BadInput:
            raise bad from None
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
    if k == "mine_view":  # 2.40.0 (#1344): "My tasks" in the own order or grouped by list
        if sv not in ("own", "lists"):
            raise bad
        return sv
    if k == "fav_views":  # 2.40.0 (#1361): the views filtered to favourites (route keys of the smart views)
        ks = [x.strip() for x in sv.split(",") if x.strip()]
        if len(ks) > 40 or not all(re.fullmatch(r"[a-z]{2,12}", x) for x in ks):
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
    if k == "folder_colors":  # 2.53.0 (#1426): {folder path: "#rrggbb"} of my folders
        return lp_clean_folder_colors(v)
    if k == "show_done_views":
        return clean_done_views(v)
    if k == "wgstd_hide":  # 2.46.2 (#1726): {view key: short signature}
        try:
            o = json.loads(sv or "{}")
        except ValueError:
            raise bad from None
        if not isinstance(o, dict) or len(o) > 200 or not all(isinstance(a, str) and 0 < len(a) <= 80 and isinstance(b, str) and len(b) <= 40 for a, b in o.items()):
            raise bad
        return json.dumps(o, ensure_ascii=False)
    if k == "group_order":  # 2.39.1 (#1221)
        return kb_clean_group_order(v)
    if k in CAL_LIST_KEYS:  # 2.36.1 (#1127, #956): json lists (list ids / calendar keys "e:<id>" | "s:<id>")
        return clean_cal_list(k, v)
    if k == "side_icons":  # 2.36.0 (#1117)
        if sv not in ("line", "emoji", "dot"):
            raise bad
        return sv
    if k == "prio_bg":  # 2.40.0 (#1416): priority as the row's background
        if sv not in ("", "soft", "strong"):
            raise bad
        return sv
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
# 2.36.1 (#1127, #956): the calendar visibility lists (a json list each; stored sorted and without doubles)
CAL_LIST_KEYS = ("cal_lists_hidden", "today_cals_hidden", "plan_cals_off")
CAL_LIST_MAX = 500


def clean_cal_list(k, v):
    """cal_lists_hidden: list ids (ints); today_cals_hidden / plan_cals_off: calendar keys "e:<evcal id>" | "s:<sub id>".
    -> stored json; BadInput if malformed. Ids of calendars / lists that no longer exist are harmless (never matched)."""
    bad = BadInput(tr("Invalid value: {0}", k))
    if v is None or (isinstance(v, str) and not v.strip()):
        return "[]"
    try:
        arr = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(arr, list) or len(arr) > CAL_LIST_MAX:
        raise bad
    if k == "cal_lists_hidden":
        if not all(isinstance(x, int) and not isinstance(x, bool) and 0 < x < 10 ** 12 for x in arr):
            raise bad
        return json.dumps(sorted(set(arr)))
    if not all(isinstance(x, str) and re.fullmatch(r"[es]:[1-9][0-9]{0,11}", x) for x in arr):
        raise bad
    return json.dumps(sorted(set(arr)))


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


# 2.40.0 (#1334): bounded, since the setting travels with every state load: route keys and group ids up to 60 characters
# (longer ones are left out), up to 200 groups per view and 40 views (the oldest views, i.e. the first keys, fall away)
KB_GROUP_VIEWS_MAX, KB_GROUPS_MAX, KB_GROUP_KEY_MAX = 40, 200, 60


def kb_clean_group_order(v):
    """2.39.1 (#1221): the own order of the groups per view (json object route key -> [group ids such as "l:12"]) -> stored
    json; an empty list or '' drops it (back to the sidebar order). BadInput if malformed; too many / too long entries are
    cut silently (2.40.0, #1334)."""
    bad = BadInput(tr("Invalid value: {0}", "group_order"))
    if v in (None, ""):
        return "{}"
    try:
        o = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(o) > 1000:
        raise bad
    out = {}
    for k, arr in o.items():
        if not isinstance(k, str) or not k or not isinstance(arr, list) or len(arr) > 2000 \
                or not all(isinstance(x, str) and x for x in arr):
            raise bad
        arr = [x for x in dict.fromkeys(arr) if len(x) <= KB_GROUP_KEY_MAX][:KB_GROUPS_MAX]
        if arr and len(k) <= KB_GROUP_KEY_MAX:
            out[k] = arr
    out = dict(list(out.items())[-KB_GROUP_VIEWS_MAX:])
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


def lp_clean_folder_colors(v):
    """2.53.0 (#1426): the colours of my folders as stored json; a folder without colour is left out."""
    from ..lists.lists import LIST_COLOR_RE, clean_folder
    bad = BadInput(tr("Invalid value: {0}", "folder_colors"))
    try:
        o = json.loads(v or "{}") if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(o) > 400:
        raise bad
    out = {}
    for f, col in o.items():
        if not isinstance(f, str) or not isinstance(col, str) or (col and not LIST_COLOR_RE.fullmatch(col)):
            raise bad
        f = clean_folder(f, False)
        if f and col:
            out[f] = col
    return json.dumps(out, ensure_ascii=False)


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
    if any(k in b for k in ("dashboard", *LAYOUT_KEYS)):  # 2.32.0 (#1063): only the person arranges their views
        from .layouts import need_person
        need_person()
    for k, v in b.items():
        if k in USER_DEFAULTS and k not in SETTINGS_SERVER_ONLY:
            if k == "lang" and v not in LANGS:
                continue
            v = clean_setting(k, v)  # BadInput: 400, nothing stored
            if v is not None:
                vals[k] = v
    if "show_done_views" in vals:  # 2.46.1 (#1422): an own choice against a folder's "Hide completed" is marked
        from ..lists.folders import lc_done_sync
        lc_done_sync(c, me(), usettings(c, me()).get("show_done_views"), vals["show_done_views"])
    for k, v in vals.items():
        uset(c, me(), k, v)
        if k == "dashboard" or k in LAYOUT_KEYS:  # 2.55.0 (#1069): the active saved arrangement follows
            from .layoutsets import lyv_follow
            lyv_follow(c, me(), k, v)
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
        "comments": (f"SELECT * FROM comments WHERE task_id IN {task_ids} AND deleted_at IS NULL", (uid,)),
        # 2.71.0 (#1459, review N5): "also in list X" lines without the id of a list the person may not see
        "activity": (f"SELECT id, task_id, user_id, kind, CASE WHEN kind IN ('ml_add', 'ml_rm') THEN '{{}}'::jsonb ELSE data END AS data, "
                     f"created_at FROM activity WHERE task_id IN {task_ids}", (uid,)),
        # 2.48.0 (#1642): notes locked with a password, as stored (ciphertext; their tasks have an empty note)
        "task_note_locks": (f"SELECT * FROM task_note_locks WHERE task_id IN {task_ids}", (uid,)),
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
        "list_layouts": ("SELECT * FROM list_layouts WHERE user_id=?", (uid,)),
        "view_layouts": ("SELECT * FROM view_layouts WHERE user_id=?", (uid,)),  # 2.55.0 (#1069): my saved arrangements
        "view_layout_offers": ("SELECT * FROM view_layout_offers WHERE from_user=? OR to_user=?", (uid, uid)),  # 2.55.0 (#1068)
        "list_notepads": ("SELECT * FROM list_notepads WHERE created_by=?", (uid,)),  # 2.43.0 (#1346)
        "list_notif": (f"SELECT * FROM list_notif WHERE list_id IN {own}", (uid,)),  # 2.33.0 (#927): my notification templates
        "folder_notif": ("SELECT * FROM folder_notif WHERE owner_id=?", (uid,)),
        "task_bell": ("SELECT task_id, level, until, set_by, created_at, updated_at FROM task_bell WHERE user_id=?", (uid,)),  # 2.53.0 C (#1424)
        "agent_steps": ("SELECT id, agent_id, job_id, message_id, text, created_at FROM agent_steps WHERE user_id=?", (uid,)),  # 2.32.0 (#1081)  # 2.32.0 (#1063): my own project page arrangements
        "agent_schedules": ("SELECT * FROM agent_schedules WHERE user_id=?", (uid,)),  # 2.34.0 (#272): my planned agent jobs
        # 2.39.0 (#1168): the Playbooks of my lists and folders (every version) and the agents' proposals for my lists
        "playbooks": (f"SELECT * FROM playbooks WHERE list_id IN {own} OR (list_id IS NULL AND owner_id=?) ORDER BY list_id, folder, version",
                      (uid, uid)),
        "playbook_proposals": (f"SELECT * FROM playbook_proposals WHERE list_id IN {own}", (uid,)),
        "org_list_actions": ("SELECT * FROM org_list_log WHERE by_id=?", (uid,)),  # 2.35.0 (#1101): what I did as an organisation admin
        # 2.21.0 (#659 / #658): my event calendars with their events + attendees, my address books with their contacts
        "event_calendars": ("SELECT * FROM ev_cals WHERE owner_id=?", (uid,)),
        "events": ("SELECT * FROM events WHERE cal_id IN (SELECT id FROM ev_cals WHERE owner_id=?)", (uid,)),
        "event_attendees": ("SELECT * FROM event_attendees WHERE event_id IN (SELECT e.id FROM events e JOIN ev_cals k ON k.id=e.cal_id "
                            "WHERE k.owner_id=?)", (uid,)),
        "address_books": ("SELECT id, name, color, created_at FROM books WHERE owner_id=? AND owner_org_id IS NULL", (uid,)),  # 2.52.0 C (#1438): own books
        "contacts": ("SELECT * FROM contacts WHERE book_id IN (SELECT id FROM books WHERE owner_id=? AND owner_org_id IS NULL)", (uid,)),
        # 2.55.0 (#1455): my own newsletter connection (never the access data), its segments and log
        "newsletter_connection": ("SELECT id, kind, url, mode, auto, synced_at, created_at, updated_at FROM nl_conns WHERE owner_id=? "
                                  "AND org_id IS NULL", (uid,)),
        "newsletter_segments": ("SELECT * FROM nl_segments WHERE conn_id IN (SELECT id FROM nl_conns WHERE owner_id=? AND org_id IS NULL)", (uid,)),
        "newsletter_runs": ("SELECT * FROM nl_runs WHERE conn_id IN (SELECT id FROM nl_conns WHERE owner_id=? AND org_id IS NULL)", (uid,)),
        # 2.22.0 (#663): my journal, whom I stay in touch with, my Karakeep connection (without the API key)
        "journal": ("SELECT day, text, mood, updated_at FROM journal WHERE user_id=? ORDER BY day", (uid,)),
        "contact_care": ("SELECT contact_id, every_days, last, note, updated_at FROM contact_care WHERE user_id=?", (uid,)),
        "karakeep": ("SELECT url, list_id, source, archive, synced_at, created_at FROM kk_conns WHERE user_id=?", (uid,)),
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
    for a in data["activity"]:  # 2.36.0 (#1116): old entries of the removed Paperless connection carry no document data
        if a["kind"] in ("paperless", "paperless_rm", "paperless_send"):
            a["data"] = "{}"
    data["user"] = user_public(g.user)
    name = f"kalmido-export-{local_now():%Y-%m-%d}.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
