"""Running Kalmido for others (2.24.0): storage quotas, the maintenance / announcement banner, daily e-mail limits."""
import json
import os
import re
from datetime import timedelta
from flask import g, jsonify, request

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, connect, db, err, gset, gsetting, iso, now_utc, parse_iso, usettings
from ..accounts.session import me
from ..api.v1 import v1_args, v1_err, v1_json, v1_view

# ---- the kind of server (#905). KALMIDO_HOSTED=1: an instance run as a service for others (no private networks behind it):
# integrations may only reach public HTTPS addresses (the admin's internal-host allow-list does not apply).
# Self-hosted servers (the default) keep everything as before.
HOSTED = os.environ.get("KALMIDO_HOSTED", "0").strip().lower() in ("1", "true", "yes", "on")
SELFHOST_DOCS = "https://github.com/Gegenschuss/kalmido#readme"


def hosted():
    return HOSTED


# ---- #910: storage quota per person. Counts every file a person uploaded (task + comment files, project files, files in
# an agent chat). Limit: the person's own value (admin, users.storage_quota_mb), else the instance default (admin setting
# storage_quota_mb, else KALMIDO_STORAGE_QUOTA_MB; 0 / empty = unlimited, the default of a self-hosted server). Pool
# "org": the members of an organisation share quota x members (an organisation's plan). At 80 / 95 % the app warns; at
# 100 % uploads are refused (413, code quota_exceeded) and nothing is ever deleted; the app offers "Contact support".
QUOTA_ENV_MB = os.environ.get("KALMIDO_STORAGE_QUOTA_MB", "").strip()
SUPPORT_EMAIL_ENV = os.environ.get("KALMIDO_SUPPORT_EMAIL", "").strip()[:200]
QUOTA_MAX_MB = 10_000_000


class QuotaExceeded(Exception):
    def __init__(self, info):
        super().__init__("quota")
        self.info = info


def _mb(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= QUOTA_MAX_MB else None


def quota_default_mb(c):
    v = gsetting(c, "storage_quota_mb")
    n = _mb(v) if v != "" else None
    if n is None:
        n = _mb(QUOTA_ENV_MB) or 0
    return n


def _user_bytes(c, uids):
    if not uids:
        return 0
    q = ",".join("?" * len(uids))
    a = c.execute(f"SELECT COALESCE(SUM(size),0) FROM attachments WHERE user_id IN ({q})", uids).fetchone()[0]
    b = c.execute(f"SELECT COALESCE(SUM(size),0) FROM list_files WHERE user_id IN ({q})", uids).fetchone()[0]
    d = c.execute(f"""SELECT COALESCE(SUM(f.size),0) FROM chat_files f JOIN agent_chat m ON m.id=f.message_id
                      WHERE m.sender='user' AND m.user_id IN ({q})""", uids).fetchone()[0]
    return int(a + b + d)


def quota_info(c, uid):
    """{used, limit (bytes, null = unlimited), pct, level: ok | warn | high | full, pool: user | org, support}."""
    u = c.execute("SELECT id, storage_quota_mb FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    pool = gsetting(c, "storage_pool") or "user"
    own = u["storage_quota_mb"]
    members = [uid]
    if pool == "org" and own is None:
        r = c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id LIMIT 1", (uid,)).fetchone()
        if r:
            members = [x[0] for x in c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id
                                                  WHERE m.org_id=? AND u.kind!='agent' AND u.storage_quota_mb IS NULL""", (r[0],))] or [uid]
        else:
            pool = "user"
    else:
        pool = "user"
    mb = own if own is not None else quota_default_mb(c)
    limit = mb * 1024 * 1024 * (len(members) if pool == "org" else 1) if mb else None
    used = _user_bytes(c, members)
    pct = round(used * 100 / limit, 1) if limit else 0
    level = "ok" if not limit or pct < 80 else "warn" if pct < 95 else "high" if used < limit else "full"
    return {"used": used, "limit": limit, "pct": pct, "level": level, "pool": pool, "members": len(members) if pool == "org" else 1,
            "support": support_email(c)}


def support_email(c):
    v = gsetting(c, "support_email") or SUPPORT_EMAIL_ENV
    if v:
        return v
    r = c.execute("SELECT email FROM users WHERE is_admin=1 AND disabled=0 AND email IS NOT NULL AND email!='' ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else ""


def quota_guard(c, uid, incoming=None):
    """Raises QuotaExceeded when uid's upload of `incoming` bytes (default: the request's size) does not fit any more."""
    if not uid:
        return
    info = quota_info(c, uid)
    if not info or not info["limit"]:
        return
    n = request.content_length if incoming is None else incoming
    if info["used"] + max(0, int(n or 0)) > info["limit"]:
        raise QuotaExceeded(info)


def quota_fits(c, uid, n):
    """For uploads without a person in front of them (mail-in, share inbox): False = skip the file, never raise."""
    try:
        quota_guard(c, uid, n)
        return True
    except QuotaExceeded:
        return False


def quota_text(info, lg=None):
    lim = info["limit"] or 0
    return tr("Your storage is full ({0} of {1}). Delete files you no longer need or contact support.", fmt_bytes(info["used"]), fmt_bytes(lim), lg=lg)


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return f"{n:.1f} TB"


@app.errorhandler(QuotaExceeded)
def quota_exceeded(e):
    info = e.info
    msg = quota_text(info)
    extra = {"used": info["used"], "limit": info["limit"]}
    if request.path.startswith("/api/v1/"):
        return v1_err(413, msg, name="quota_exceeded", **extra)
    return jsonify(error=msg, code="quota_exceeded", support=info.get("support") or "", **extra), 413


def quota_backfill(c):
    """Once (2.24.0): the uploader of files from before (attachments.user_id): a comment's author, else the task's creator."""
    if HOSTED and gsetting(c, "migr_hosted_pl") != "1":  # #905: a hosted server starts new accounts without Paperless
        from ..core.schema import USER_DEFAULTS
        fs = [f for f in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if f and f != "paperless"]
        gset(c, "default_features", ",".join(fs))
        gset(c, "migr_hosted_pl", "1")
    if gsetting(c, "migr_att_user") == "1":
        return
    c.execute("""UPDATE attachments SET user_id=(SELECT user_id FROM comments WHERE comments.id=attachments.comment_id)
                 WHERE user_id IS NULL AND comment_id IS NOT NULL""")
    c.execute("""UPDATE attachments SET user_id=(SELECT created_by FROM tasks WHERE tasks.id=attachments.task_id)
                 WHERE user_id IS NULL""")
    gset(c, "migr_att_user", "1")


@app.get("/api/me/storage")
def my_storage():
    c = db()
    return jsonify(quota_info(c, me()))


# ---- #907: announcement / maintenance banner. One notice at a time (admin setting "announce", JSON): text, level
# info | maintenance, optional from / until (UTC ISO). Every client shows it above the app while it is current (a person
# can hide it; a changed notice comes back). Optional: a push to everyone once when saved. Scripts set it before a planned
# restart: `python app.py announce "text" --minutes 30` (kalmido-app-update.sh) or PUT /api/v1/admin/announcement.
ANN_TEXT_MAX = 500


def announce_get(c, all_=False):
    try:
        a = json.loads(gsetting(c, "announce") or "{}")
    except ValueError:
        a = {}
    if not isinstance(a, dict) or not a.get("text"):
        return None
    now = now_utc()
    fr, un = parse_iso(a.get("starts_at") or "") if a.get("starts_at") else None, parse_iso(a.get("ends_at") or "") if a.get("ends_at") else None
    a["active"] = (not fr or fr <= now + timedelta(seconds=1)) and (not un or un > now)
    if not all_ and (not a["active"] and not (fr and fr > now)):
        return None
    return a


def announce_clean(b):
    """-> (dict or None, error text). b: {text, level?, starts_at?, ends_at?, minutes?}"""
    text = re.sub(r"\s+", " ", str(b.get("text") or "")).strip()
    if not text:
        return None, None
    if len(text) > ANN_TEXT_MAX:
        return None, tr("At most {0} characters", ANN_TEXT_MAX)
    level = b.get("level") or "info"
    if level not in ("info", "maintenance"):
        return None, tr("Invalid value: {0}", "level")
    out = {"text": text, "level": level, "id": now_utc().strftime("%Y%m%d%H%M%S")}
    for k in ("starts_at", "ends_at"):
        v = b.get(k)
        if v in (None, ""):
            continue
        d = parse_iso(str(v)) if isinstance(v, str) else None
        if not d:
            return None, tr("Invalid value: {0}", k)
        out[k] = iso(d)
    if b.get("minutes") not in (None, ""):
        m = b["minutes"]
        if isinstance(m, bool) or not isinstance(m, int) or not 1 <= m <= 7 * 24 * 60:
            return None, tr("Invalid value: {0}", "minutes")
        out["ends_at"] = iso(now_utc() + timedelta(minutes=m))
    if out.get("starts_at") and out.get("ends_at") and out["ends_at"] <= out["starts_at"]:
        return None, tr("The end must be after the start")
    return out, None


def announce_set(c, b, by=None):
    """Stores (or clears) the notice; queues a push to everyone with b.push (caller commits). -> error text or None."""
    a, e = announce_clean(b if isinstance(b, dict) else {})
    if e:
        return e
    gset(c, "announce", json.dumps(a, ensure_ascii=False) if a else "")
    if a and b.get("push") is True and g.get("pushes") is not None:
        from ..notify.push import push_prio, push_reachable
        from ..core.i18n import lang_of
        for r in c.execute("SELECT id FROM users WHERE disabled=0 AND kind!='agent'").fetchall():
            s = usettings(c, r[0])
            if push_reachable(c, r[0], s):
                g.pushes.append((r[0], tr("{0}: notice", APP_NAME, lg=lang_of(s)), a["text"], f"{PUBLIC_URL}/", push_prio(s)))
    print("announcement", "cleared" if not a else f"set ({a['level']})", "by", by or "?", flush=True)
    return None


@app.put("/api/admin/announcement")
def admin_announce_put():
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    e = announce_set(c, body(), g.user["username"])
    if e:
        return err(e)
    bump(c)
    c.commit()
    return jsonify(announce_get(c, True) or {})


@app.get("/api/v1/announcement")
@v1_view
def v1_announce_get():
    """The current notice (any token) -- {} when there is none."""
    v1_args(())
    return jsonify(announce_get(db()) or {})


@app.put("/api/v1/admin/announcement")
@v1_view
def v1_announce_put():
    """{text, level?, starts_at?, ends_at?, minutes?, push?} -- set the notice ({"text": ""} clears it). Admin tokens only."""
    v1_args(())
    if not g.user["is_admin"]:
        return v1_err(403, tr("Admins only"))
    c = db()
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("text", "level", "starts_at", "ends_at", "minutes", "push"))
    if unknown:
        from ..personal.timetrack import UnknownFields
        raise UnknownFields(unknown)
    e = announce_set(c, b, g.user["username"])
    if e:
        return v1_err(400, e)
    bump(c)
    c.commit()
    return jsonify(announce_get(c, True) or {})


def announce_cli(args):
    """python app.py announce "text" [--minutes N] [--maintenance] | announce --clear"""
    c = connect()
    try:
        if "--clear" in args:
            e = announce_set(c, {"text": ""}, "cli")
        else:
            text = " ".join(a for a in args if not a.startswith("--") and not a.isdigit())
            mins = next((int(args[i + 1]) for i, a in enumerate(args) if a == "--minutes" and i + 1 < len(args) and args[i + 1].isdigit()), None)
            e = announce_set(c, {"text": text, "level": "maintenance" if "--maintenance" in args else "info", "minutes": mins}, "cli")
        if e:
            print("error:", e)
            return 2
        bump(c)
        c.commit()
        print(json.dumps(announce_get(c, True) or {}, ensure_ascii=False))
        return 0
    finally:
        c.close()


# ---- #899 (part): daily e-mail limits. Mails a person makes the server send (invitations, new links) count per sender and
# per receiving address and day; over the limit the mail is not sent (the link still works and can be copied).
MAIL_DAY_SENDER = 30   # per account and day (admin setting mail_day_limit)
MAIL_DAY_RCPT = 5      # per receiving address and day


def mail_day_limit(c):
    v = _mb(gsetting(c, "mail_day_limit"))
    return v if v else MAIL_DAY_SENDER


def mail_budget(c, sender, rcpt):
    """True and counted if one more mail from sender to rcpt fits today; False otherwise (caller commits)."""
    day = now_utc().strftime("%Y-%m-%d")
    c.execute("DELETE FROM mail_counts WHERE day<?", (day,))
    keys = [(f"r:{(rcpt or '').strip().lower()}", MAIL_DAY_RCPT)]
    if sender:
        keys.append((f"s:{sender}", mail_day_limit(c)))
    for k, lim in keys:
        r = c.execute("SELECT n FROM mail_counts WHERE k=? AND day=?", (k, day)).fetchone()
        if r and r[0] >= lim:
            return False
    for k, _ in keys:
        c.execute("""INSERT INTO mail_counts(k,day,n) VALUES(?,?,1) ON CONFLICT(k) DO UPDATE SET
                     n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+1 ELSE 1 END, day=excluded.day""", (k, day))
    return True


# ---- admin settings (PATCH /api/admin/settings) and what the admin sees (about_info)
def hosting_settings(c, b):
    """storage_quota_mb (null/'' = the server default), storage_pool user | org, support_email, mail_day_limit. Error or None."""
    from ..core.config import EMAIL_RE
    if "storage_quota_mb" in b:
        v = b["storage_quota_mb"]
        if v in (None, ""):
            gset(c, "storage_quota_mb", "")
        elif isinstance(v, bool) or not isinstance(v, int) or _mb(v) is None:
            return err(tr("Invalid value: {0}", "storage_quota_mb"))
        else:
            gset(c, "storage_quota_mb", str(v))
    if "storage_pool" in b:
        if b["storage_pool"] not in ("user", "org"):
            return err(tr("Invalid value: {0}", "storage_pool"))
        gset(c, "storage_pool", b["storage_pool"])
    if "support_email" in b:
        v = str(b["support_email"] or "").strip()[:200]
        if v and not EMAIL_RE.fullmatch(v):
            return err(tr("Invalid value: {0}", "support_email"))
        gset(c, "support_email", v)
    if "mail_day_limit" in b:
        v = b["mail_day_limit"]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 1000:
            return err(tr("Invalid value: {0}", "mail_day_limit"))
        gset(c, "mail_day_limit", str(v))
    if "org_name" in b:  # 2.24.0 (UX-23): the organisation of an "organisation" server can be renamed (unless KALMIDO_ORG_NAME)
        from ..accounts.orgs import instance_mode, main_org, ORG_NAME_ENV
        nm = re.sub(r"\s+", " ", str(b["org_name"] or "")).strip()[:60]
        if not nm or instance_mode(c) != "organisation" or ORG_NAME_ENV or not main_org(c):
            return err(tr("Invalid value: {0}", "org_name"))
        c.execute("UPDATE orgs SET name=? WHERE id=?", (nm, main_org(c)))
    if "announce" in b:
        e = announce_set(c, b["announce"] if isinstance(b["announce"], dict) else {"text": ""}, g.user["username"] if g.get("user") else None)
        if e:
            return err(e)
    return None


def hosting_admin(c):
    v = gsetting(c, "storage_quota_mb")
    return {"hosted": HOSTED, "storage_quota_mb": _mb(v) if v != "" else None, "storage_quota_env": _mb(QUOTA_ENV_MB) or 0,
            "storage_pool": gsetting(c, "storage_pool") or "user", "support_email": gsetting(c, "support_email"),
            "support_email_env": SUPPORT_EMAIL_ENV, "mail_day_limit": mail_day_limit(c), "announce_all": announce_get(c, True),
            "user_agents": gsetting(c, "user_agents") == "1"}


def user_storage(c, uid):
    """For the admin's user list: bytes used by this person and their own quota (MB, null = default)."""
    r = c.execute("SELECT storage_quota_mb FROM users WHERE id=?", (uid,)).fetchone()
    return {"used": _user_bytes(c, [uid]), "quota_mb": r[0] if r else None}


@app.get("/api/v1/me/storage")
@v1_view
def v1_my_storage():
    """2.24.0 (#910): the token user's storage: used / limit (bytes), level ok | warn | high | full."""
    v1_args(())
    return jsonify(quota_info(db(), me()))


def hosting_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    schemas["Storage"] = {"type": "object", "properties": {
        "used": {"type": "integer", "description": "Bytes of the files you uploaded (with the pool: your organisation's)"},
        "limit": nul("integer", description="Bytes; null = unlimited"), "pct": {"type": "number"},
        "level": {"type": "string", "enum": ["ok", "warn", "high", "full"], "description": "warn from 80 %, high from 95 %, full = uploads refused (413 quota_exceeded)"},
        "pool": {"type": "string", "enum": ["user", "org"]}, "members": {"type": "integer"},
        "support": {"type": "string", "description": "Where to ask for more space"}}}
    schemas["Announcement"] = {"type": "object", "properties": {
        "text": {"type": "string"}, "level": {"type": "string", "enum": ["info", "maintenance"]}, "id": {"type": "string"},
        "starts_at": {"type": "string"}, "ends_at": {"type": "string"}, "active": {"type": "boolean"}}}
    paths["/me/storage"] = {"get": op("2.24.0: your storage quota and what you use", "Account", ok(ref("Storage")))}
    paths["/announcement"] = {"get": op("2.24.0: the server's current notice (maintenance / announcement), {} when there is none",
                                        "Account", ok(ref("Announcement")))}
    paths["/admin/announcement"] = {"put": op(
        "2.24.0: set the notice every app shows above its content (admins); {\"text\": \"\"} clears it", "Admin",
        ok(ref("Announcement")) | errs("400", "403"), body={"type": "object", "additionalProperties": False, "properties": {
            "text": {"type": "string", "maxLength": ANN_TEXT_MAX}, "level": {"type": "string", "enum": ["info", "maintenance"]},
            "starts_at": {"type": "string", "description": "ISO 8601 (UTC)"}, "ends_at": {"type": "string"},
            "minutes": {"type": "integer", "minimum": 1, "description": "Ends this many minutes from now"},
            "push": {"type": "boolean", "description": "Also a push to everyone, once"}}, "required": ["text"]}, scope="account")}


# ---- #896: agents are connected by people themselves (their own provider / key / computer). When one joins a list, every
# person of the list learns it in their News: which agent, who added it and where it runs (agents.provider) -- the data of
# the list then also reaches that provider. Who may connect agents at all: the organisation's setting user_agents (off by
# default, Settings > Administration > Organisation: "Members may connect agents").
def agent_joined_notice(c, lid, aid, actor):
    from ..collab.news import news_add
    a = c.execute("""SELECT u.display_name, u.username, COALESCE(g.provider,'') AS provider, g.owner_id FROM users u
                     LEFT JOIN agents g ON g.user_id=u.id WHERE u.id=?""", (aid,)).fetchone()
    l = c.execute("SELECT name, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not a or not l:
        return
    people = {l["owner_id"]} | {r[0] for r in c.execute("""SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id
                                                          WHERE m.list_id=? AND u.kind!='agent' AND u.disabled=0""", (lid,))}
    for uid in people:
        if uid and uid != actor:
            news_add(c, uid, "agentjoin", list_id=lid, data={"name": l["name"], "agent": a["display_name"] or a["username"],
                                                             "agent_id": aid, "provider": a["provider"][:80]}, actor=actor, row="share")
