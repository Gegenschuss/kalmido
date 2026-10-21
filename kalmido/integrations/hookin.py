"""2.115.0 A (#2061): inbound webhooks of a list -- a task per request from n8n, Make, Zapier, Home Assistant, curl."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL, TZ
from ..core.pg import insert_id, system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import client_ip, me
from ..core.access import Denied, list_role, need_list, WRITE_ROLES
from ..core.errors import BadInput, reject_unknown
from ..notify.alerts import _env_int, aa_count
from ..api.v1 import PRIO_VALUES
from ..api.common import hit_limit


# ---------------------------------------------------------------- 2.115.0 A (#2061): inbound webhook per list
# The owner / a list admin (never an agent) adds one or more inbound webhooks to a list (list settings > "Inbound webhook"):
# a secret URL POST /api/hooks/in/<token>, no cookie, no login -- the token in the URL is the credential (shown once, stored
# only as its SHA-256; rotate = a new token, the old one stops at once; delete = gone, undo brings the same URL back).
# A request creates ONE task in exactly this list through the normal create path (tasks.py task_create: activity with
# {"via": "webhook", "hook": id}, pushes, agent events, outgoing webhooks, list rules) with the rights of the person who
# set the webhook up: that person must still be able to write in the list, else the webhook pauses itself (paused_reason)
# and answers 403 -- it never goes on with other rights. Body: JSON {title, notes?, due? (YYYY-MM-DD or ISO date-time),
# priority? (none | low | medium | high), tags? [list tags], fields? {field name | id: value}}, or form fields with the same
# names (tags comma separated), or text/plain (first line = title, the rest = notes). Owner decision of part A: unknown
# keys, list tags the list does not have and fields of other lists are IGNORED (never created, never stored) and named in
# the answer ("ignored"), so a flow keeps running when the list changes; invalid values (date, priority, a field value)
# are a 400. Limits: WHI_MAX_BYTES per body, WHI_PER_MIN / WHI_PER_DAY requests per webhook, WHI_LIST_MAX per list.
WHI_MAX_BYTES = 64 * 1024
WHI_PER_MIN = _env_int("KALMIDO_HOOK_IN_PER_MIN", 60)
WHI_PER_DAY = _env_int("KALMIDO_HOOK_IN_PER_DAY", 1000)
WHI_LIST_MAX = 10
WHI_NAME_MAX = 60
WHI_KEEP_DAYS = 30           # a deleted webhook can be restored this long, then it is removed for good
WHI_PAUSE = {  # paused_reason -> the text the settings show
    "creator": N_("the person who set it up has no access to the list any more"),
    "role": N_("the person who set it up can no longer change the list"),
}
WHI_KEYS = ("title", "notes", "due", "priority", "tags", "fields")


def whi_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def whi_url(tok):
    return f"{PUBLIC_URL.rstrip('/')}/api/hooks/in/{tok}"


def whi_list_ok(c, lid):
    """None when list lid may have inbound webhooks, else the reason (health / budget lists, the basket, locked lists)."""
    from ..collab.liste2eguard import le2b_list_locked
    r = c.execute("SELECT life, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        raise Denied(404)
    if r["life"] in ("health", "budget") or r["is_inbox"]:
        return tr("Inbound webhooks are not available in this list")
    if le2b_list_locked(c, lid):
        return tr("Inbound webhooks are not available in locked lists")
    return None


def whi_need_manage(c, lid):
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    need_list(c, lid, write=False, manage=True)


def whi_purge(c, lid):
    cut = iso(now_utc() - timedelta(days=WHI_KEEP_DAYS))
    c.execute("DELETE FROM hook_in WHERE list_id=? AND deleted_at IS NOT NULL AND deleted_at<?", (lid, cut))


def whi_dict(c, r):
    from ..collab.comments import user_names
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "created_by": r["created_by"],
            "created_by_name": user_names(c, [r["created_by"]]).get(r["created_by"], "") if r["created_by"] else "",
            "last_used_at": r["last_used_at"], "uses": r["uses"], "paused_reason": r["paused_reason"] or None,
            "paused_text": tr(WHI_PAUSE[r["paused_reason"]]) if r["paused_reason"] in WHI_PAUSE else None}


def whi_need(c, hid, deleted=False):
    r = c.execute("SELECT * FROM hook_in WHERE id=?", (hid,)).fetchone()
    if not r or bool(r["deleted_at"]) != deleted:
        raise Denied(404)
    whi_need_manage(c, r["list_id"])
    return r


@app.get("/api/lists/<int:lid>/hooks-in")
def whi_get(lid):
    """The inbound webhooks of a list (never their URLs: shown once). Owner / list admins."""
    c = db()
    whi_need_manage(c, lid)
    whi_purge(c, lid)
    c.commit()
    rows = c.execute("SELECT * FROM hook_in WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (lid,)).fetchall()
    why = whi_list_ok(c, lid)
    return jsonify(hooks=[whi_dict(c, r) for r in rows], limit=WHI_LIST_MAX, available=why is None, reason=why or "",
                   per_min=WHI_PER_MIN, per_day=WHI_PER_DAY, max_kb=WHI_MAX_BYTES // 1024)


@app.post("/api/lists/<int:lid>/hooks-in")
def whi_create(lid):
    """{name?} -> the webhook + its URL (shown this once)."""
    c = db()
    whi_need_manage(c, lid)
    b = body()
    reject_unknown(b, ("name",))
    why = whi_list_ok(c, lid)
    if why:
        return err(why, 409)
    if c.execute("SELECT COUNT(*) FROM hook_in WHERE list_id=? AND deleted_at IS NULL", (lid,)).fetchone()[0] >= WHI_LIST_MAX:
        return err(tr("At most {0} inbound webhooks per list", WHI_LIST_MAX), 409)
    name = str(b.get("name") or "").strip()[:WHI_NAME_MAX] if isinstance(b.get("name"), (str, type(None))) else None
    if name is None:
        raise BadInput(tr("Invalid value: {0}", "name"))
    tok = "khi_" + secrets.token_urlsafe(32)
    hid = insert_id(c, "INSERT INTO hook_in(list_id,created_by,name,token_hash,created_at) VALUES(?,?,?,?,?)",
                    (lid, me(), name, whi_hash(tok), iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify({**whi_dict(c, whi_need(c, hid)), "url": whi_url(tok)}), 201


@app.patch("/api/hooks-in/<int:hid>")
def whi_update(hid):
    """{name} -- rename. A paused webhook starts again when its owner (the current person) takes it over: {resume: true}."""
    c = db()
    r = whi_need(c, hid)
    b = body()
    reject_unknown(b, ("name", "resume"))
    if "name" in b:
        if not isinstance(b["name"], str):
            raise BadInput(tr("Invalid value: {0}", "name"))
        c.execute("UPDATE hook_in SET name=? WHERE id=?", (b["name"].strip()[:WHI_NAME_MAX], hid))
    if b.get("resume") is True and r["paused_reason"]:  # the current person (owner / list admin) takes it over with their rights
        c.execute("UPDATE hook_in SET paused_reason='', created_by=? WHERE id=?", (me(), hid))
    bump(c)
    c.commit()
    return jsonify(whi_dict(c, whi_need(c, hid)))


@app.post("/api/hooks-in/<int:hid>/rotate")
def whi_rotate(hid):
    """A new URL (the old one stops at once), shown this once; the person who rotates becomes its owner."""
    c = db()
    whi_need(c, hid)
    tok = "khi_" + secrets.token_urlsafe(32)
    c.execute("UPDATE hook_in SET token_hash=?, created_by=?, paused_reason='' WHERE id=?", (whi_hash(tok), me(), hid))
    bump(c)
    c.commit()
    return jsonify({**whi_dict(c, whi_need(c, hid)), "url": whi_url(tok)})


@app.delete("/api/hooks-in/<int:hid>")
def whi_delete(hid):
    """Deleted: its URL answers 404 at once. One undo step: POST .../restore (WHI_KEEP_DAYS)."""
    c = db()
    whi_need(c, hid)
    c.execute("UPDATE hook_in SET deleted_at=? WHERE id=?", (iso(now_utc()), hid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/hooks-in/<int:hid>/restore")
def whi_restore(hid):
    c = db()
    r = whi_need(c, hid, deleted=True)
    if c.execute("SELECT COUNT(*) FROM hook_in WHERE list_id=? AND deleted_at IS NULL", (r["list_id"],)).fetchone()[0] >= WHI_LIST_MAX:
        return err(tr("At most {0} inbound webhooks per list", WHI_LIST_MAX), 409)
    c.execute("UPDATE hook_in SET deleted_at=NULL WHERE id=?", (hid,))
    bump(c)
    c.commit()
    return jsonify(whi_dict(c, whi_need(c, hid)))


# ---- the inbound request
def whi_due(v):
    """'YYYY-MM-DD' or an ISO date-time -> (due, due_time | None). With an offset / Z the time is taken to the server's zone."""
    v = str(v).strip()
    if len(v) == 10:
        datetime.strptime(v, "%Y-%m-%d")
        return v, None
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def whi_parse():
    """The request body -> a dict with WHI_KEYS (+ the unknown keys); BadInput when it cannot be read."""
    ct = (request.mimetype or "").lower()
    if ct == "application/json" or ct.endswith("+json"):
        try:
            b = json.loads(request.get_data(cache=True).decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError):
            raise BadInput(tr("The body must be a JSON object")) from None
        if not isinstance(b, dict):
            raise BadInput(tr("The body must be a JSON object"))
        return b
    if ct in ("application/x-www-form-urlencoded", "multipart/form-data"):
        b = {k: request.form.get(k) for k in request.form}
        if isinstance(b.get("tags"), str):
            b["tags"] = [t for t in (x.strip() for x in b["tags"].split(",")) if t]
        return b
    try:
        txt = request.get_data(cache=True).decode("utf-8")
    except UnicodeDecodeError:
        raise BadInput(tr("Invalid value: {0}", "body")) from None
    first, _, rest = txt.strip().partition("\n")
    return {"title": first.strip(), "notes": rest.strip()}


def whi_task_body(c, lid, b):
    """The parsed body -> (the body for task_create, the ignored names)."""
    ignored = sorted(k for k in b if k not in WHI_KEYS)
    title = b.get("title")
    if not isinstance(title, str) or not title.strip():
        raise BadInput(tr("Title missing"))
    out = {"title": title, "list_id": lid}
    notes = b.get("notes")
    if notes not in (None, ""):
        if not isinstance(notes, str):
            raise BadInput(tr("Invalid value: {0}", "notes"))
        out["content"] = notes
    if b.get("due") not in (None, ""):
        try:
            out["due"], t = whi_due(b["due"])
        except (ValueError, TypeError):
            raise BadInput(tr("Invalid value: {0}", "due")) from None
        if t:
            out["due_time"] = t
    p = b.get("priority")
    if p not in (None, ""):
        if isinstance(p, str) and p.strip().lower() in PRIO_VALUES:
            out["priority"] = PRIO_VALUES[p.strip().lower()]
        elif isinstance(p, int) and not isinstance(p, bool) and p in PRIO_VALUES.values():
            out["priority"] = p
        else:
            raise BadInput(tr("Invalid value: {0}", "priority"))
    tags = b.get("tags")
    if tags not in (None, "", []):
        if isinstance(tags, str):
            tags = [x.strip() for x in tags.split(",") if x.strip()]
        if not isinstance(tags, list) or any(not isinstance(x, str) for x in tags):
            raise BadInput(tr("Invalid value: {0}", "tags"))
        have = {r["name"].casefold(): r["name"] for r in c.execute("SELECT name FROM list_tags WHERE list_id=?", (lid,))}
        out["ltags"] = [have[x.strip().casefold()] for x in tags if x.strip().casefold() in have]  # never creates a tag
        ignored += [f"tags.{x.strip()}" for x in tags if x.strip().casefold() not in have]
    fields = b.get("fields")
    if fields not in (None, "", {}):
        if not isinstance(fields, dict):
            raise BadInput(tr("Invalid value: {0}", "fields"))
        rows = c.execute("SELECT id, name FROM list_fields WHERE list_id=?", (lid,)).fetchall()
        by_id, by_name = {str(r["id"]): r["id"] for r in rows}, {r["name"].strip().casefold(): r["id"] for r in rows}
        vals = {}
        for k, v in fields.items():
            fid = by_id.get(str(k).strip()) or by_name.get(str(k).strip().casefold())
            if fid:
                vals[str(fid)] = v
            else:
                ignored.append(f"fields.{str(k)[:60]}")
        if vals:
            out["fields"] = vals
    return out, ignored[:50]


def whi_pause(c, hid, why):
    with system_ctx(c):  # 2.115.0 A (#2061): system on purpose: pausing exactly the webhook whose token was just checked
        c.execute("UPDATE hook_in SET paused_reason=? WHERE id=?", (why, hid))
    c.commit()


@app.post("/api/hooks/in/<token>")
def whi_in(token):
    """Inbound webhook: one task in the webhook's list (see above). 201 {id, url, ignored}."""
    from ..agents.core import is_agent
    from ..tasks.tasks import task_create
    c = db()
    h = whi_hash(token) if len(token) <= 200 else ""
    with system_ctx(c):  # 2.115.0 A (#2061): resolve the token (one row by its hash) across organisations, then act as its owner
        r = c.execute("""SELECT h.*, l.archived FROM hook_in h JOIN lists l ON l.id=h.list_id
                         WHERE h.token_hash=? AND h.deleted_at IS NULL""", (h,)).fetchone() if h else None
        u = c.execute("SELECT * FROM users WHERE id=?", (r["created_by"],)).fetchone() if r and r["created_by"] else None
    if not r:
        aa_count("security", "hookin", client_ip())
        return err(tr("unknown"), 404)
    if (request.content_length or 0) > WHI_MAX_BYTES or len(request.get_data(cache=True) or b"") > WHI_MAX_BYTES:
        return err(tr("The request is too large (at most {0} KB)", WHI_MAX_BYTES // 1024), 413)
    if hit_limit(f"whi:{r['id']}", WHI_PER_MIN) or hit_limit(f"whid:{r['id']}", WHI_PER_DAY, 86400):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    if r["paused_reason"]:
        return err(tr("This webhook is paused: {0}", tr(WHI_PAUSE.get(r["paused_reason"], WHI_PAUSE["creator"]))), 403)
    if not u or u["disabled"] or is_agent(u) or u["kid"]:
        whi_pause(c, r["id"], "creator")
        return err(tr("This webhook is paused: {0}", tr(WHI_PAUSE["creator"])), 403)
    g.user, g.auth_via, g.whi_hook = u, "hook_in", r["id"]  # from here on: exactly the owner's rights and organisations
    role = list_role(c, r["list_id"])
    if role not in WRITE_ROLES:
        whi_pause(c, r["id"], "role" if role else "creator")
        return err(tr("This webhook is paused: {0}", tr(WHI_PAUSE["role" if role else "creator"])), 403)
    why = whi_list_ok(c, r["list_id"])
    if why or r["archived"]:
        return err(why or tr("The list is archived"), 409)
    tb, ignored = whi_task_body(c, r["list_id"], whi_parse())
    g.body = tb
    try:
        res = task_create()
    finally:
        g.body = None
    if isinstance(res, tuple):
        return res
    tid = res.get_json()["id"]
    c.execute("UPDATE hook_in SET uses=uses+1, last_used_at=? WHERE id=?", (iso(now_utc()), r["id"]))
    c.commit()
    print("hook in: task", tid, "list", r["list_id"], "hook", r["id"], flush=True)
    return jsonify(id=tid, url=f"{PUBLIC_URL.rstrip('/')}/#t/{tid}", **({"ignored": ignored} if ignored else {})), 201
