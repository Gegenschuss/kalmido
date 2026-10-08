"""Users and the own account (admin user management, passwords, deletion)."""
import io
import json
import os
import re
import uuid
import secrets
import time
import zipfile
from flask import g, jsonify, request, Response, send_file
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.config import app, COOKIE, EMAIL_RE, MIN_PASSWORD, PUBLIC_URL, USERNAME_RE
from ..core.i18n import lang, LANGS, N_, tr, trn
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, now_utc, uset, usettings
from ..accounts.session import _rate_blocked, _rate_fail, _rate_keys, _token_hash, me, user_public
from ..accounts.pictures import (
    AVATAR_DIR, avatar_drop_file, AVATAR_MAX_MB, avatar_path, AVATAR_PRESETS, avatar_process, avatar_url, LIST_ICON_DIR,
    list_icon_drop_file, list_icon_path, LIST_ICON_PRESETS, list_icon_process, list_icon_url,
)
from ..accounts.login import session_via, twofa_clear, twofa_methods
from ..core.access import collab_all, Denied, list_role, need_list, vis_sql
from ..core.serializers import attachment_files, unlink_files
from ..integrations.paperless import pl_forget_user
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- users / account

def need_admin():
    if not g.user["is_admin"]:
        raise Denied(403)


def _invite_state(c, uid):
    from ..accounts.invite import invite_state
    return invite_state(c, uid)


def user_admin_dict(c, u):
    from ..family.family import kid_parents
    return {**user_public(u), "kind": u["kind"] or "user", "is_admin": bool(u["is_admin"]), "disabled": bool(u["disabled"]),
            "has_password": bool(u["password_hash"]), "proxy_login": u["proxy_login"] or "",
            "created_at": u["created_at"], "ntfy_topic": usettings(c, u["id"])["ntfy_topic"],
            "paperless_access": bool(u["paperless_access"]), "email": u["email"] or "",
            "twofa": twofa_methods(c, u), "oidc_linked": bool(u["oidc_subject"]),
            "parents": kid_parents(c, u["id"]) if u["kid"] else [],  # 2.19.0 (#653)
            "invite": _invite_state(c, u["id"]),  # 2.22.0 (#697): invited | expired | null
            "signup": u["signup"] or "",  # 2.23.0 (#711): confirm (e-mail not confirmed) | pending (waits for approval) | ''
            "kid": bool(u["kid"]),
            "orgs": [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (u["id"],))],  # 2.22.0 (#752)
            **({"org_id": (c.execute("SELECT org_id FROM agents WHERE user_id=?", (u["id"],)).fetchone() or [None])[0]} if (u["kind"] or "user") == "agent" else {}),  # 2.28.0 (#935)
            "lists": c.execute("SELECT COUNT(*) FROM lists WHERE owner_id=? AND is_inbox=0", (u["id"],)).fetchone()[0],
            "storage": _storage(c, u["id"])}  # 2.24.0 (#910): {used, quota_mb}


def _storage(c, uid):
    from ..admin.hosting import user_storage
    return user_storage(c, uid)


def admin_sees(c, uid):
    """2.28.0 (#935): in the mode workspaces an instance admin manages only the people they may see (their organisations and
    connections); elsewhere every account."""
    from ..accounts.orgs import instance_mode, may_see
    return instance_mode(c) != "workspaces" or may_see(c, me(), uid)


def user_orgs_public(c, uid):
    return [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]


@app.get("/api/users")
def users_list():
    """Everyone: enabled users (for sharing). Admins: all users with account details (2.28.0, mode workspaces: only the
    people they may see, plus the number of the others)."""
    c = db()
    from ..accounts.orgs import visible_people
    if g.user["is_admin"]:
        from ..integrations.mail import MAIL_OUT_ON
        vis = visible_people(c, me())
        rows = c.execute("SELECT * FROM users ORDER BY id").fetchall()
        return jsonify(users=[user_admin_dict(c, u) for u in rows if vis is None or u["id"] in vis], mail_out=MAIL_OUT_ON,
                       others=sum(1 for u in rows if vis is not None and u["id"] not in vis))
    if not collab_all():  # nobody to share with
        return jsonify(users=[user_public(g.user)])
    mine = me()  # 2.7.2 (#420): somebody else's personal agent is not in the list
    vis = visible_people(c, mine)  # 2.22.0 (#752): only the people this person may see (organisation / contacts)
    # 2.28.0 (#935): + the organisations of each person (ids), so the share dialog offers only the list's workspace; agents
    # carry the workspace they work in
    ag_org = {r[0]: r[1] for r in c.execute("SELECT user_id, org_id FROM agents")}
    return jsonify(users=[{**user_public(u), "orgs": user_orgs_public(c, u["id"]), **({"org_id": ag_org.get(u["id"])} if u["id"] in ag_org else {})}
                          for u in c.execute("""SELECT * FROM users WHERE disabled=0 AND id NOT IN
                                                (SELECT user_id FROM agents WHERE owner_id IS NOT NULL AND owner_id!=?) ORDER BY id""", (mine,))
                          if vis is None or u["id"] in vis])


def _proxy_taken(c, login, uid=None):
    return bool(login) and bool(c.execute("SELECT 1 FROM users WHERE proxy_login=? COLLATE NOCASE AND id IS NOT ?",
                                          (login, uid)).fetchone())


def _active_admins(c, without=None):
    return c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND disabled=0 AND id IS NOT ?", (without,)).fetchone()[0]


@app.post("/api/users")
def user_create():
    from ..notify.push import NTFY_TOPIC_RE
    from ..notify.alerts import aa_now
    from ..family.family import kid_set
    need_admin()
    b = body()
    c = db()
    username = (b.get("username") or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return err(tr("Username already exists"), 409)
    pw = b.get("password") or ""
    if pw and len(pw) < MIN_PASSWORD:
        return err(tr("Password: at least {0} characters", MIN_PASSWORD))
    proxy = (b.get("proxy_login") or "").strip() or None
    if _proxy_taken(c, proxy):
        return err(tr("This proxy login is already assigned"), 409)
    topic = str(b.get("ntfy_topic") or "").strip()
    if topic and not NTFY_TOPIC_RE.fullmatch(topic):
        return err(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
    uid = create_user(c, username, (b.get("display_name") or "").strip()[:60] or username, pw or None, proxy,
                      bool(b.get("is_admin")), ntfy_topic=topic or None, onboard=True,
                      paperless_access=bool(b["paperless_access"]) if "paperless_access" in b else bool(b.get("is_admin")))
    email = str(b.get("email") or "").strip()[:200]
    if email and not EMAIL_RE.fullmatch(email):
        c.rollback()
        return err(tr("Invalid value: {0}", "email"))
    if email:
        c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
    # 2.15.0 (#632): the language given for the person (lang), else the admin's as before; the inbox (and later the
    # "Getting started" list) are created in it
    lg = str(b.get("lang")) if b.get("lang") in LANGS else usettings(c, me())["lang"]
    if b.get("lang") and b["lang"] not in LANGS:
        c.rollback()
        return err(tr("Invalid value: {0}", "lang"))
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    if b.get("kid") is not True:  # 2.22.0 (#739): new people start with the module Agents on (kids not; existing users unchanged)
        from ..core.schema import USER_DEFAULTS
        fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
        uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))
    ensure_inbox(c, uid)
    if b.get("kid") is True:  # 2.19.0 (#653): a kid account (never an admin)
        e = kid_set(c, uid, True, b.get("parents"))
        if e:
            c.rollback()
            return err(e)
    # 2.22.0 (#752): the organisations of the new person: given, else the creating admin's (else the instance's first)
    orgs = b.get("orgs")
    from ..accounts.orgs import instance_mode
    if instance_mode(c) not in ("multi", "workspaces"):  # 2.23.0 (#799): organisation = the one (create_user), shared = none
        orgs = []
    if orgs is None:
        orgs = [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=?", (me(),))]
    if not isinstance(orgs, list) or not all(isinstance(x, int) for x in orgs):
        c.rollback()
        return err(tr("Invalid value: {0}", "orgs"))
    known = [x for x in orgs if c.execute("SELECT 1 FROM orgs WHERE id=?", (x,)).fetchone()]
    if known:
        c.execute("DELETE FROM org_members WHERE user_id=?", (uid,))
        for o in known:
            c.execute("INSERT OR IGNORE INTO org_members(org_id,user_id) VALUES(?,?)", (o, uid))
    inv = None
    if b.get("invite") is True and not pw:  # 2.22.0 (#697): no password: a one-time link to set it (by e-mail when possible)
        from ..accounts.invite import invite_new
        inv = invite_new(c, uid, me(), send=b.get("send", True) is not False)
    bump(c)
    c.commit()
    if b.get("is_admin"):
        aa_now("security", f"admin:{username}", N_("{0} is now an admin (set by {1})."), [username, g.user["username"]])
    out = user_admin_dict(c, c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify({**out, **({"invitation": inv} if inv else {})})


@app.patch("/api/users/<int:uid>")
def user_update(uid):
    from ..notify.push import NTFY_TOPIC_RE
    from ..notify.alerts import aa_now
    from ..agents.core import agent_row, is_agent
    from ..agents.admin import make_agent
    from ..family.family import kid_set
    need_admin()
    b = body()
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not admin_sees(c, uid):  # 2.28.0 (#935): mode workspaces: only people the admin may see
        return err(tr("unknown user"), 404)
    from ..accounts.orgs import instance_mode
    if "orgs" in b and instance_mode(c) in ("multi", "workspaces"):  # 2.22.0 (#752): the person's organisations (replaces them); 2.23.0: multi only; 2.28.0: + workspaces
        if not isinstance(b["orgs"], list) or not all(isinstance(x, int) for x in b["orgs"]):
            return err(tr("Invalid value: {0}", "orgs"))
        from ..accounts.orgs import org_leave
        have = {r[0]: r[1] for r in c.execute("SELECT org_id, role FROM org_members WHERE user_id=?", (uid,))}
        for o in sorted(set(have) - set(b["orgs"])):  # 2.28.0 (#935): taken out of an organisation = leaving it (lists stay with it)
            heir = (c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (o, uid)).fetchone() or [me()])[0]
            org_leave(c, o, uid, heir if heir != uid else me())
        for o in b["orgs"]:
            if o not in have:
                c.execute("INSERT OR IGNORE INTO org_members(org_id,user_id,role) SELECT id, ?, 'member' FROM orgs WHERE id=?", (uid, o))
    if uid == me() and (("is_admin" in b and not b["is_admin"]) or b.get("disabled") or b.get("kind") == "agent"):
        return err(tr("You cannot remove your own admin rights or disable yourself"))
    if "kind" in b:  # 2.0.0: person <-> agent
        if b["kind"] not in ("user", "agent"):
            return err(tr("Invalid value: {0}", "kind"))
        if b["kind"] == "agent" and not is_agent(u):
            if u["is_admin"] or b.get("is_admin"):
                return err(tr("Remove the admin rights first: an agent is never an admin"))
            make_agent(c, uid)
        elif b["kind"] == "user" and is_agent(u):
            a = agent_row(c, uid)
            if a and a["webhook_id"]:
                c.execute("DELETE FROM webhooks WHERE id=?", (a["webhook_id"],))
            c.execute("DELETE FROM agents WHERE user_id=?", (uid,))
            c.execute("UPDATE users SET kind='user' WHERE id=?", (uid,))
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if is_agent(u) and (b.get("is_admin") or b.get("paperless_access")):
        c.rollback()
        return err(tr("An agent is never an admin and has no Paperless access"))
    if (("is_admin" in b and not b["is_admin"]) or b.get("disabled")) and u["is_admin"] and not _active_admins(c, uid):
        return err(tr("At least one active admin is needed"))
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((b["display_name"] or "").strip()[:60] or u["username"], uid))
    if "proxy_login" in b:
        proxy = (b["proxy_login"] or "").strip() or None
        if _proxy_taken(c, proxy, uid):
            return err(tr("This proxy login is already assigned"), 409)
        c.execute("UPDATE users SET proxy_login=? WHERE id=?", (proxy, uid))
    if "is_admin" in b:
        c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if b["is_admin"] else 0, uid))
    if "disabled" in b:
        c.execute("UPDATE users SET disabled=? WHERE id=?", (1 if b["disabled"] else 0, uid))
        if b["disabled"]:
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    if "password" in b:  # reset ('' = remove the built-in login)
        pw = b["password"] or ""
        if pw and len(pw) < MIN_PASSWORD:
            return err(tr("Password: at least {0} characters", MIN_PASSWORD))
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw) if pw else None, uid))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    if "ntfy_topic" in b:
        topic = str(b["ntfy_topic"] or "").strip()
        if topic and not NTFY_TOPIC_RE.fullmatch(topic):
            return err(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
        uset(c, uid, "ntfy_topic", topic)
    if "avatar_preset" in b:  # 1.9.0: a preset picture or none (e.g. for the bot user of an API integration);
        p = b["avatar_preset"]  # an own photo is uploaded by the user only, an admin can remove it (null)
        if p is not None and p not in AVATAR_PRESETS:
            c.rollback()
            return err(tr("Invalid value: {0}", "avatar_preset"))
        c.execute("UPDATE users SET avatar=? WHERE id=?", (f"p:{p}" if p else None, uid))
        if (u["avatar"] or "") != (f"p:{p}" if p else ""):
            avatar_drop_file(uid, u["avatar"])
    if "paperless_access" in b:  # Paperless = the archive of the token owner: only for users an admin allows
        c.execute("UPDATE users SET paperless_access=? WHERE id=?", (1 if b["paperless_access"] else 0, uid))
    if "email" in b:  # optional; OIDC links a user by it (verified e-mail claim)
        email = str(b["email"] or "").strip()[:200]
        if email and not EMAIL_RE.fullmatch(email):
            c.rollback()
            return err(tr("Invalid value: {0}", "email"))
        c.execute("UPDATE users SET email=? WHERE id=?", (email or None, uid))
    if "storage_quota_mb" in b:  # 2.24.0 (#910): the person's own storage quota in MB (null = the server's default, 0 = unlimited)
        q = b["storage_quota_mb"]
        if q is not None and (isinstance(q, bool) or not isinstance(q, int) or not 0 <= q <= 10_000_000):
            c.rollback()
            return err(tr("Invalid value: {0}", "storage_quota_mb"))
        c.execute("UPDATE users SET storage_quota_mb=? WHERE id=?", (q, uid))
    if b.get("oidc_unlink") is True:  # the next OIDC login links again (by user name / e-mail)
        c.execute("UPDATE users SET oidc_subject=NULL WHERE id=?", (uid,))
    if "kid" in b or "parents" in b or (b.get("is_admin") and u["kid"]):  # 2.19.0 (#653): a kid account and who looks after it
        e = kid_set(c, uid, b["kid"] if "kid" in b else bool(u["kid"]), b.get("parents"))
        if e:
            c.rollback()
            return err(e)
    reset = b.get("reset_2fa") is True and bool(twofa_methods(c, u) or u["totp_secret"])
    if reset:  # lost phone and recovery codes: the user logs in with the password alone (or must enrol again)
        twofa_clear(c, uid)
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    bump(c)
    c.commit()
    if reset:
        aa_now("security", f"2fareset:{u['username']}:{int(time.time())}", N_("{0} reset the two-factor authentication of {1}."),
               [g.user["username"], u["username"]])
    if b.get("is_admin") and not u["is_admin"]:
        aa_now("security", f"admin:{u['username']}", N_("{0} is now an admin (set by {1})."), [u["username"], g.user["username"]])
    return jsonify(user_admin_dict(c, c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))


@app.delete("/api/users/<int:uid>")
def user_delete(uid):
    """Refused while the user owns lists besides the inbox (the safer option: nothing shared with
    others disappears). Deletes their inbox (+ its tasks), habits, focus sessions, time entries, filters, tags and
    settings; tasks they created in other people's lists stay (creator cleared)."""
    need_admin()
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not admin_sees(c, uid):  # 2.28.0 (#935)
        return err(tr("unknown user"), 404)
    if uid == me():
        return err(tr("You cannot delete yourself"))
    n = c.execute("SELECT COUNT(*) FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()[0]
    if n:
        return err(trn("The user still owns {0} list. Delete it or disable the user instead.",
                       "The user still owns {0} lists. Delete them or disable the user instead.", n), 409)
    files = user_purge(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    avatar_drop_file(uid, u["avatar"])
    return jsonify(ok=True)


def user_purge(c, uid):
    """Deletes user uid (no own lists besides the inbox left; the caller checked and commits). Returns the files to unlink."""
    inbox = [r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=?", (uid,))]
    files = attachment_files(c, [r[0] for r in c.execute(
        f"SELECT id FROM tasks WHERE list_id IN ({','.join('?' * len(inbox)) or 'NULL'})", inbox)])
    for lid in inbox:
        c.execute("DELETE FROM lists WHERE id=?", (lid,))
    c.execute("DELETE FROM habits WHERE user_id=?", (uid,))
    c.execute("DELETE FROM pomos WHERE user_id=?", (uid,))
    c.execute("DELETE FROM time_entries WHERE user_id=?", (uid,))
    c.execute("DELETE FROM filters WHERE user_id=?", (uid,))
    c.execute("DELETE FROM task_tags WHERE user_id=?", (uid,))
    c.execute("UPDATE tasks SET assignee_id=NULL WHERE assignee_id=?", (uid,))
    c.execute("UPDATE tasks SET created_by=NULL WHERE created_by=?", (uid,))
    c.execute("DELETE FROM task_field_values WHERE value=? AND field_id IN (SELECT id FROM list_fields WHERE type='person')", (str(uid),))
    pl_forget_user(c, uid)  # 2.1.0: personal Paperless connections, tokens, grants; list bells
    a = c.execute("SELECT webhook_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    if a and a["webhook_id"]:
        c.execute("DELETE FROM webhooks WHERE id=?", (a["webhook_id"],))
    c.execute("DELETE FROM users WHERE id=?", (uid,))  # cascades: settings, memberships, sessions
    return files


@app.get("/api/me")
def me_get():
    c = db()
    u = g.user
    return jsonify({**user_public(u), "is_admin": bool(u["is_admin"]), "auth": g.auth_via,
                    "via": "proxy" if g.auth_via == "proxy" else session_via(c), "twofa": twofa_methods(c, u),
                    "has_password": bool(u["password_hash"]), "proxy_login": u["proxy_login"] or "",
                    "drop_token": u["drop_token"] or "", "ntfy_topic": usettings(c, u["id"])["ntfy_topic"]})


@app.patch("/api/me")
def me_update():
    """Own display name and password (the current password is required when one is set)."""
    b = body()
    c = db()
    u = g.user
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((b["display_name"] or "").strip()[:60] or u["username"], u["id"]))
    if "password" in b:
        keys = _rate_keys(u["username"])
        if _rate_blocked(keys):
            return err(tr("Too many failed logins, please wait a few minutes"), 429)
        if u["password_hash"] and not check_password_hash(u["password_hash"], b.get("current_password") or ""):
            _rate_fail(keys)
            return err(tr("Current password is wrong"), 403)
        pw = b["password"] or ""
        if len(pw) < MIN_PASSWORD:
            return err(tr("Password: at least {0} characters", MIN_PASSWORD))
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), u["id"]))
        tok = request.cookies.get(COOKIE)  # other sessions end, this one stays
        c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash IS NOT ?", (u["id"], _token_hash(tok) if tok else None))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/me/drop-token")
def me_drop_token():
    c = db()
    tok = secrets.token_urlsafe(24)
    c.execute("UPDATE users SET drop_token=? WHERE id=?", (tok, me()))
    c.commit()
    return jsonify(drop_token=tok)


def httpshortcuts_zip(url, token, lg):
    """Import file for the Android app HTTP Shortcuts (format compatibilityVersion 90): two shortcuts, one for files
    (several at once, form field "file") and one for text / links (form field "text", filled from the share dialog by a
    global variable with "receive value from share dialog"), both POST <url> with the user's upload token."""
    icon = f"custom-icon_{secrets.randbelow(9 * 10 ** 10) + 10 ** 10}_circle.png"
    var_id = str(uuid.uuid4())
    common = {"method": "POST", "url": url, "iconName": icon, "bodyContent": "", "requestBodyType": "form_data",
              "headers": [{"key": "Authorization", "value": "Bearer " + token}],
              "responseHandling": {"actions": ["rerun", "share", "save"]}}
    data = {
        "categories": [{"id": str(uuid.uuid4()), "name": "Kalmido", "shortcuts": [
            {**common, "id": str(uuid.uuid4()), "name": "Kalmido",
             "description": tr("Share files to your Kalmido inbox", lg=lg),
             "parameters": [{"key": "file", "type": "file", "fileUploadOptions": {"fileUploadType": "file_picker_multi"}}]},
            {**common, "id": str(uuid.uuid4()), "name": tr("Kalmido text", lg=lg),
             "description": tr("Share text or links to your Kalmido inbox", lg=lg), "excludeFromFileSharing": True,
             "parameters": [{"key": "text", "type": "string", "value": "{{" + var_id + "}}"}]},
        ]}],
        "variables": [{"id": var_id, "key": "kalmido_shared_text", "type": "constant", "value": "", "isShareText": True,
                       "isMultiline": True}],
        "compatibilityVersion": 90,
        "version": 91,
        "createdAt": now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("shortcuts.json", json.dumps(data, ensure_ascii=False, indent=1))
        z.write(os.path.join(app.static_folder, "icon-512.png"), icon)
    return out.getvalue()


@app.get("/api/me/share/httpshortcuts.zip")
def me_share_httpshortcuts():
    """1.9.0: my ready-made HTTP Shortcuts import (address + my upload token inside: treat it like a password)."""
    c = db()
    u = c.execute("SELECT drop_token FROM users WHERE id=?", (me(),)).fetchone()
    tok = u["drop_token"] if u else ""
    if not tok:  # a user from before per-user tokens: create one now
        tok = secrets.token_urlsafe(24)
        c.execute("UPDATE users SET drop_token=? WHERE id=?", (tok, me()))
        c.commit()
    data = httpshortcuts_zip(PUBLIC_URL.rstrip("/") + "/drop", tok, lang(c, me()))
    r = Response(data, mimetype="application/zip")
    r.headers["Content-Disposition"] = 'attachment; filename="kalmido-http-shortcuts.zip"'
    r.headers["Cache-Control"] = "no-store"
    return r


def _avatar_set(c, uid, value):
    old = c.execute("SELECT avatar FROM users WHERE id=?", (uid,)).fetchone()
    c.execute("UPDATE users SET avatar=? WHERE id=?", (value, uid))
    bump(c)
    c.commit()
    if old and old[0] != value:
        avatar_drop_file(uid, old[0])


@app.put("/api/me/avatar")
def me_avatar_preset():
    """{preset: "coffee" | ... | null}: a preset picture, or none (initials)."""
    p = body().get("preset")
    if p is not None and p not in AVATAR_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    c = db()
    _avatar_set(c, me(), f"p:{p}" if p else None)
    return jsonify(avatar=avatar_url(c.execute("SELECT id, avatar FROM users WHERE id=?", (me(),)).fetchone()))


@app.post("/api/me/avatar")
def me_avatar_upload():
    """multipart "file": an own photo (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB), stored as a square JPEG."""
    return avatar_upload(me())


def avatar_upload(uid):
    """The uploaded picture (multipart "file") becomes uid's photo (2.1.2: also an agent's, set by an admin)."""
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        jpg = avatar_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(AVATAR_DIR, exist_ok=True)
    tmp = avatar_path(uid, tok) + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(jpg)
    os.replace(tmp, avatar_path(uid, tok))
    c = db()
    _avatar_set(c, uid, "u:" + tok)
    return jsonify(avatar=avatar_url({"id": uid, "avatar": "u:" + tok}))


@app.delete("/api/me/avatar")
def me_avatar_delete():
    c = db()
    _avatar_set(c, me(), None)
    return jsonify(avatar="")


@app.get("/api/avatar/<int:uid>/<tok>.jpg")
def avatar_get(uid, tok):
    """A user's own photo: for the user, admins and people sharing a list with them."""
    c = db()
    u = c.execute("SELECT id, avatar FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["avatar"] != "u:" + tok or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok):
        raise Denied(404)
    if uid != me() and not g.user["is_admin"] and not c.execute(
            f"""SELECT 1 FROM lists WHERE id IN {vis_sql()} AND (owner_id=? OR id IN (SELECT list_id FROM list_members WHERE user_id=?))
                LIMIT 1""", (me(), me(), uid, uid)).fetchone():
        raise Denied(404)
    p = avatar_path(uid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    r = send_file(p, mimetype="image/jpeg", max_age=31536000)
    r.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return r


def _list_icon_set(c, lid, value):
    old = c.execute("SELECT icon FROM lists WHERE id=?", (lid,)).fetchone()
    c.execute("UPDATE lists SET icon=? WHERE id=?", (value, lid))
    bump(c)
    c.commit()
    if old and old[0] != value:
        list_icon_drop_file(lid, old[0])
    return jsonify(icon=list_icon_url({"id": lid, "icon": value}))


@app.put("/api/lists/<int:lid>/icon")
def list_icon_preset(lid):
    """{preset: "kalmido" | "coffee" | ... | null} -- the owner picks a preset icon for the list, or none."""
    c = db()
    need_list(c, lid, owner=True)
    p = body().get("preset")
    if p is not None and p not in LIST_ICON_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    return _list_icon_set(c, lid, f"p:{p}" if p else None)


@app.post("/api/lists/<int:lid>/icon")
def list_icon_upload(lid):
    """multipart "file": an own picture for the list (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB), stored as a square PNG."""
    c = db()
    need_list(c, lid, owner=True)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        png = list_icon_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(LIST_ICON_DIR, exist_ok=True)
    tmp = list_icon_path(lid, tok) + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(png)
    os.replace(tmp, list_icon_path(lid, tok))
    return _list_icon_set(c, lid, "u:" + tok)


@app.delete("/api/lists/<int:lid>/icon")
def list_icon_delete(lid):
    c = db()
    need_list(c, lid, owner=True)
    return _list_icon_set(c, lid, None)


@app.get("/api/list-icon/<int:lid>/<tok>.png")
def list_icon_get(lid, tok):
    """A list's own icon: for everybody who sees the list."""
    c = db()
    r = c.execute("SELECT id, icon FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["icon"] != "u:" + tok or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok) or not list_role(c, lid):
        raise Denied(404)
    p = list_icon_path(lid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    rs = send_file(p, mimetype="image/png", max_age=31536000)
    rs.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return rs
