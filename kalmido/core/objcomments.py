"""2.972.0 (#5272, stage Q4a of the cross-cutting core, analysis #3563, decided 08.11.2026): comments exist once, in the
shared core.

One table obj_comments (migrations.d/5272_a.py) holds every comment: (kind, ref_id) = the object it stands on, user_id = the
author (NULL = written from outside, ext_name), parent_id = the answered comment of the same object, mentions BIGINT[], extra
JSONB = what a kind adds (a task: suggestion, choices, choice, portal, rule_name), client_ref = the client's key of a comment
sent again. obj_comment_trash keeps the text of a comment in the trash. Kinds today: 'task' (the comments of a task; the
routes, files, answer buttons and pushes of collab/comments.py). Video / picture reviews and document notes follow with stage
Q4b; the team chat keeps its stream and takes the helpers here with Q4c.

The rules exist once:
- reading = obj_role(kind, ref_id) >= 'view' of the core (core/objects.py; a task: its project role, core/objlight.py)
- saying (write, edit, react, answer a button) = ocm_say_refusal: a guest / read-only person of the object's organisation
  (accounts/orgroles.py org_say_refusal) who cannot change the object itself only reads (was need_task_say, #4549)
- editing = the author only, with the version of the edit box (expect_updated_at -> 409 with the comment, core/conflict.py
  through core/objparts.py part_write under the lock comment-<id>, as #4701 / #4762)
- deleting by someone else = the author or whoever has 'manage' on the object (decided 08.11.2026, question 3: one rule for
  tasks, video reviews, document notes, team chat)
- mentions = OCM_MENTION_RE tokens <@id> of people the kind's hook `people` names (a task: who sees it); another token becomes
  '@name' ('@?' for someone the writer may not see) -- the one parser (ocm_mentions_clean)
- a sealed object (a project with the lock, collab/liste2e.py): the body is the browser's ciphertext and the mentions come
  from the browser (the kind's hook `sealed_in`, the le2e guard stays in force); the trash keeps the ciphertext
- the trash: the text waits in obj_comment_trash for the trash period, the row looks deleted (body '', deleted_at); a restore
  (author or 'manage') brings text, mentions and the files of that moment back (the kind's hooks `trash` / `restore`)
- notifying: who reads the object, through the core's send decision (core/objnotify.py obj_notify, step 1 obj_role); agents
  get their event once (agents/core.py agent_comment_events) -- ocm_after does both for every way a comment comes in

Rows: every reader gets the row in its old shape (ocm_old_cols: task_id, reply_to, mentions as "1,2", suggestion as JSON text,
choices / choice, portal 0/1, rule_name, the times as ISO text with milliseconds like before), so answers, the API, exports
and agent events stay as they were.

Interface:
  ocm_old_cols(a='') -> SQL column list of the old shape        ocm_row(c, cid, live=False, lock=False, kind='task') -> row | None
  ocm_list(c, kind, ref_id, uid=None) -> [rows]                  ocm_row_out(r) -> dict (the JSON of a comment, no files)
  ocm_add(c, kind, ref_id, uid, body, *, mentions, extra, ext_name, parent_id, client_ref, created_at, notify) -> id
  ocm_edit(c, cid, uid, b, *, public) -> (row before, row after, new mentions)
  ocm_trash(c, cid, uid, *, check=True) -> ts | None         ocm_restore(c, cid, uid, *, check=True) -> bool
  ocm_mentions_clean(c, kind, ref_id, text) -> (text, [ids])     ocm_text_in(c, kind, ref_id, text) -> (text, [ids])
  ocm_say_refusal(c, kind, ref_id, uid) -> text | None           ocm_need_say(c, kind, ref_id, uid=None)
  ocm_names(c, ids) -> {id: name}                                ocm_visible_names(c, ids) -> {id: name} the writer may see
  ocm_may_delete(c, row, uid) -> bool                            ocm_extra(c, cid, key, value)
  ocm_notify(c, kind, cid, text, mentions, notify_mentions, nfiles, only=None, replied=None) -> pushes
  ocm_after(c, kind, cid, text, mentions, ...) -> pushes          ocm_purge_user(c, uid)
  ocm_move(c) -> rows moved (init_db, once)                       ocm_fk(c, table, col, action)
(A SQLite file of an older version brings its comments in the old table, admin/migrate.py LEGACY_COMMENTS; ocm_move takes them.)
"""
import json
import re
from datetime import datetime, timezone

from flask import g, has_request_context

from .access import collab_all, live_sql
from .config import PUBLIC_URL
from .ctx import me
from .db import iso_ms, now_utc
from .errors import BadInput, Denied
from .i18n import N_, tr, trn
from .objparts import part_kind, part_write
from .objhooks import MOVE, USER_GONE
from .pg import insert_id, qi, st_ids, system_ctx, table_columns
from ..accounts.orgroles import org_say_refusal

OCM_KINDS = ("task",)
OCM_MENTION_RE = re.compile(r"<@(\d+)>")  # THE mention token (was MENTION_RE in collab/comments.py, replies.py, ...)
OCM_MAX = 10000  # characters of a comment (a ciphertext may be longer: the kind's hook text_max)
OCM_TS = 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"'  # the old ISO form with milliseconds (core/db.py iso_ms)
OCM_EXTRA = ("suggestion", "choices", "choice", "portal", "rule_name")  # the keys of a task's extra
OCM_DEL_TXT = N_("Only the author or the project owner can delete this comment")
OCM_EDIT_TXT = N_("Only the author can edit this comment")
OCM_HOOKS = {}  # kind -> {people, sealed, sealed_in, text_max, nfiles, trash, restore, live} (registered by the kind's area)
OCM_PART = "comment"  # the side object of core/objparts.py (lock comment-<id>, 409 key "comment", as since #4701 / #4762)


def ocm_kind(kind, **hooks):
    """Register the hooks of a kind (collab/comments.py for 'task'):
    people(c, ref_id) -> {uid}: who may be mentioned (who reads it)
    sealed(c, ref_id) -> bool: the object is end-to-end locked (the body is a ciphertext)
    sealed_in(c, ref_id, text) -> (text, mentions): the guard of a sealed object
    text_max(text) -> the length limit of this text
    nfiles(c, cid) -> files of the comment that are not in the trash
    trash(c, cid, ts) / restore(c, cid, ts): the kind's own rows (files) with the comment
    live(c, ref_id) -> the object row, or None when it is in the trash / gone (no events then)"""
    if kind not in OCM_KINDS:
        raise ValueError(kind)
    OCM_HOOKS[kind] = hooks


def _hook(kind, name):
    h = OCM_HOOKS.get(kind)
    if h is None:
        raise ValueError(f"objcomments: kind {kind!r} not registered (ocm_kind)")
    return h.get(name)


# ---- rows
def ocm_old_cols(a=""):
    """The columns of a comment in the old shape (module docstring); a = the alias of obj_comments in the query."""
    p = f"{a}." if a else ""

    def ts(col):
        return f"to_char({p}{col} AT TIME ZONE 'UTC', '{OCM_TS}') AS {col}"
    return (f"{p}id, {p}ref_id AS task_id, {p}user_id, {p}body, array_to_string({p}mentions, ',') AS mentions, "
            f"{ts('created_at')}, {ts('edited_at')}, {ts('deleted_at')}, {p}extra->>'suggestion' AS suggestion, "
            f"{p}parent_id AS reply_to, {p}extra->'choices' AS choices, {p}extra->'choice' AS choice, {p}ext_name, "
            f"CASE WHEN COALESCE(({p}extra->>'portal')::boolean, false) THEN 1 ELSE 0 END AS portal, "
            f"{p}extra->>'rule_name' AS rule_name, {p}client_ref")


OCM_COLS = ocm_old_cols() + ", kind, ref_id, org_id, deleted_by"


def ocm_row(c, cid, live=False, lock=False, kind="task"):
    """Comment cid in the old shape (+ kind, ref_id, org_id, deleted_by), None when it is gone (live: or in the trash).
    review 2.972: only a comment of kind (default 'task': the callers outside the core read task comments); None = any kind."""
    return c.execute(f"SELECT {OCM_COLS} FROM obj_comments WHERE id=?" + (" AND kind=?" if kind else "")
                     + (f" AND {live_sql()}" if live else "") + (" FOR UPDATE" if lock else ""),
                     (int(cid), kind) if kind else (int(cid),)).fetchone()


def ocm_list(c, kind, ref_id, uid=None):
    """The comments of (kind, ref_id) outside the trash, oldest first. uid: checked to read the object first (404)."""
    if uid is not None:
        _need_read(c, kind, ref_id, uid)
    return c.execute(f"SELECT {OCM_COLS} FROM obj_comments WHERE kind=? AND ref_id=? AND {live_sql()} ORDER BY id",
                     (kind, int(ref_id))).fetchall()


def ocm_ts(v):
    """A point in time of the table (canonical ISO text, a datetime) -> the old ISO form with milliseconds; None stays None."""
    if v is None or v == "":
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return iso_ms(d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def ocm_row_out(r):
    """A row of the old shape -> the JSON of a comment as before (no files: collab/comments.py comment_dict adds them)."""
    k = r.keys()
    return {"id": r["id"], "user_id": r["user_id"], "body": r["body"], "created_at": r["created_at"],
            "edited_at": r["edited_at"], "mentions": [int(x) for x in (r["mentions"] or "").split(",") if x],
            "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None,
            "reply_to": r["reply_to"] if "reply_to" in k else None, "ext_name": r["ext_name"] if "ext_name" in k else None,
            "portal": bool(r["portal"]) if "portal" in k else False, "rule_name": r["rule_name"] if "rule_name" in k else None}


def ocm_extra(c, cid, key, value):
    """Sets key of the comment's extra to value (a Python value; a suggestion is its JSON text, a string), None takes it out."""
    if key not in OCM_EXTRA:
        raise ValueError(key)
    if value is None:
        c.execute("UPDATE obj_comments SET extra = extra - CAST(? AS TEXT) WHERE id=?", (key, int(cid)))
    else:
        c.execute("UPDATE obj_comments SET extra = jsonb_set(extra, CAST(? AS TEXT[]), CAST(? AS JSONB)) WHERE id=?",
                  ("{" + key + "}", json.dumps(value, ensure_ascii=False), int(cid)))


def _extra(extra):
    """The extra of a new comment: only keys with a value (portal only when true)."""
    out = {}
    for k, v in (extra or {}).items():
        if k not in OCM_EXTRA:
            raise ValueError(k)
        if v is None or v is False or v == "" or (k == "portal" and not v):
            continue
        out[k] = True if k == "portal" else json.loads(v) if k in ("choices", "choice") and isinstance(v, str) else v
    return out


# ---- rights
def _role(c, uid, kind, ref_id):
    from .objects import obj_role
    return obj_role(c, uid, kind, int(ref_id))


def _need_read(c, kind, ref_id, uid):
    if not _role(c, uid, kind, ref_id):
        raise Denied(404)


def ocm_say_refusal(c, kind, ref_id, uid):
    """None when uid may say something on (kind, ref_id) as far as its organisation goes, else the refusal text (accounts/
    orgroles.py RO_MSG / GUEST_MSG, not translated): a guest / read-only person of the object's organisation who cannot change
    the object itself only reads. Private objects and people without that role: None. (Was task_say_refusal, #4549.)"""
    from .objects import OBJ_RANK, obj_space
    sp = obj_space(c, kind, int(ref_id))
    msg = org_say_refusal(c, uid, sp[0]) if sp and sp[0] else None
    return msg if msg and OBJ_RANK[_role(c, uid, kind, ref_id)] < OBJ_RANK["edit"] else None


def ocm_need_say(c, kind, ref_id, uid=None):
    """403 with the organisation role's text when uid (default: me) may only read (kind, ref_id). (Was need_task_say.)"""
    msg = ocm_say_refusal(c, kind, ref_id, uid or me())
    if msg:
        raise Denied(403, tr(msg))


def ocm_may_delete(c, row, uid):
    """The one rule of deleting / restoring a comment (decided 08.11.2026, question 3): its author, or 'manage' on the object."""
    return bool(uid) and (row["user_id"] == uid or _role(c, uid, row["kind"], row["ref_id"]) == "manage")


# ---- mentions
def ocm_names(c, ids):
    """{id: display name} of the accounts ids."""
    ids = [int(i) for i in set(ids) if i]
    if not ids:
        return {}
    return {r["id"]: r["display_name"] or r["username"] for r in c.execute(
        "SELECT id, username, display_name FROM users WHERE id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),))}


def ocm_visible_names(c, ids):
    """2.148.1 A (#2490): {id: name} for the '@name' of a token that is not kept -- only people the writer may see."""
    from ..accounts.orgs import visible_people
    names = ocm_names(c, ids)
    vis = visible_people(c, me()) if has_request_context() and getattr(g, "user", None) is not None else set()
    return names if vis is None else {k: v for k, v in names.items() if k in vis}


def ocm_mentions_clean(c, kind, ref_id, text):
    """THE mention parser: keeps the <@id> tokens of people who read (kind, ref_id) (the kind's hook people); any other token
    becomes '@name' ('@?' for someone the writer may not see). -> (text, [ids] in the order of their first token)."""
    allowed = set(_hook(kind, "people")(c, int(ref_id)))
    names = ocm_visible_names(c, [int(x) for x in OCM_MENTION_RE.findall(text or "")])
    found = []

    def sub(m):
        uid = int(m.group(1))
        if uid in allowed:
            found.append(uid)
            return m.group(0)
        return "@" + names.get(uid, "?")
    return OCM_MENTION_RE.sub(sub, text or ""), list(dict.fromkeys(found))


def ocm_text_in(c, kind, ref_id, text):
    """The text of a new / edited comment -> (text, mentions): a sealed object takes the browser's ciphertext and mentions
    (its guard), else the mentions are cleaned (only with collaboration on: else no mentions at all)."""
    sealed = _hook(kind, "sealed")
    if (sealed and sealed(c, int(ref_id))) or (text or "").startswith("e2e1:"):
        return _hook(kind, "sealed_in")(c, int(ref_id), text)
    return ocm_mentions_clean(c, kind, ref_id, text) if collab_all() else (text, [])


def ocm_text_check(kind, text, nfiles=0):
    """BadInput when the text is too long, or empty without files."""
    mx = _hook(kind, "text_max")
    if len(text) > (mx(text) if mx else OCM_MAX):
        raise BadInput(tr("The comment is too long (max. {0} characters)", OCM_MAX))
    if not text and not nfiles:
        raise BadInput(tr("The comment is empty"))


# ---- writes
def ocm_add(c, kind, ref_id, uid, body, *, mentions=(), extra=None, ext_name=None, parent_id=None, client_ref=None,
            created_at=None, notify=False, nfiles=0, replied=None):
    """A new comment (the caller checked the rights, cleaned the text and commits) -> its id. created_at None = now.
    notify=True: the people who read the object hear of it and the agents get their event (ocm_after; the pushes go out after
    the request, g.pushes)."""
    if kind not in OCM_KINDS:
        raise ValueError(kind)
    cid = insert_id(c, "INSERT INTO obj_comments(kind, ref_id, user_id, ext_name, parent_id, body, mentions, extra, client_ref, created_at) "
                       "VALUES(?,?,?,?,?,?,CAST(? AS BIGINT[]),CAST(? AS JSONB),?,?)",
                    (kind, int(ref_id), uid, ext_name, parent_id, body or "", st_ids(mentions or ()),
                     json.dumps(_extra(extra), ensure_ascii=False), client_ref, created_at or iso_ms(now_utc())))
    if notify:
        p = ocm_after(c, kind, cid, body or "", list(mentions or ()), nfiles=nfiles, replied=replied,
                      author=uid if uid is not None else 0)  # 0 = from outside (no account), as news_add
        if p and has_request_context():
            g.setdefault("pushes", []).extend(p)
        elif p:
            from ..collab.comments import send_pushes
            send_pushes(p)
    return cid


part_kind(OCM_PART, "obj_comments", lock="comment-{id}", version=lambda r: r["edited_at"] or r["created_at"], key="comment",
          live=live_sql())


def ocm_edit(c, cid, uid, b, *, public=None):
    """uid edits comment cid (b = the request body: body, mentions of a sealed object, expect_updated_at). Checks: the comment
    lives and uid reads its object (404), the author (403), may say (403), the version (409 with public(c, row)), the text.
    Writes body, mentions, edited_at; agents that got it learn the change, new mentions are notified (pushes into g.pushes).
    -> (row before, row after, [new mentions])."""
    r = ocm_row(c, cid, live=True, kind=None)
    if r is None:
        raise Denied(404)
    _need_read(c, r["kind"], r["ref_id"], uid)
    if r["user_id"] != uid:
        raise Denied(403, tr(OCM_EDIT_TXT))
    ocm_need_say(c, r["kind"], r["ref_id"], uid)  # 2.607.0 (#4549): a guest / read-only person changes no comment
    r, _ = part_write(c, OCM_PART, cid, b, read=lambda c, i: ocm_row(c, i, live=True, kind=None), public=public)
    kind, ref = r["kind"], r["ref_id"]
    text = (b.get("body") or "").strip()
    nf = _hook(kind, "nfiles")
    ocm_text_check(kind, text, nf(c, cid) if nf else 0)
    text, mentions = ocm_text_in(c, kind, ref, text)
    old = {int(x) for x in (r["mentions"] or "").split(",") if x}
    c.execute("UPDATE obj_comments SET body=?, mentions=CAST(? AS BIGINT[]), edited_at=? WHERE id=?",
              (text, st_ids(mentions), iso_ms(now_utc()), int(cid)))  # ms: the version of the next edit (#4701)
    new_m = [m for m in mentions if m not in old] if collab_all() else []
    after = ocm_row(c, cid, kind=None)
    live = _hook(kind, "live")
    obj = live(c, ref) if live else None
    if obj is not None:  # 2.39.0 (#1179): agents that got this comment as an event learn the change (before new mentions)
        from ..agents.chat import med_comment_edited
        med_comment_edited(c, obj, after, r["body"])
        if new_m:
            p = ocm_after(c, kind, cid, text, mentions, notify_mentions=new_m, only=new_m, created=False, author=uid)
            if p and has_request_context():
                g.setdefault("pushes", []).extend(p)
    return r, after, new_m


def ocm_trash(c, cid, uid, *, check=True):
    """Comment cid into the trash: its text kept in obj_comment_trash (a sealed object's ciphertext as it is), the kind's rows
    (files) with it at the same time. check: the comment lives (404), uid reads the object (404), author or 'manage' (403);
    check=False = a system way (the caller decided). -> the time, None when there was nothing to put there. Caller commits."""
    r = c.execute(f"SELECT id, kind, ref_id, user_id, body FROM obj_comments WHERE id=? AND {live_sql()} FOR UPDATE",
                  (int(cid),)).fetchone()
    if r is None:
        if check:
            raise Denied(404)
        return None
    if check:
        _need_read(c, r["kind"], r["ref_id"], uid)
        if not ocm_may_delete(c, r, uid):
            raise Denied(403, tr(OCM_DEL_TXT))
    ts = iso_ms(now_utc())
    sealed = _hook(r["kind"], "sealed")
    enc = "e2e" if (r["body"] or "").startswith("e2e1:") or (sealed and sealed(c, r["ref_id"])) else None
    c.execute("INSERT INTO obj_comment_trash(comment_id, body, mentions, enc) SELECT id, body, mentions, ? FROM obj_comments WHERE id=? "
              "ON CONFLICT(comment_id) DO UPDATE SET body=excluded.body, mentions=excluded.mentions, enc=excluded.enc", (enc, r["id"]))
    tr_ = _hook(r["kind"], "trash")
    if tr_:
        tr_(c, r["id"], ts)
    c.execute("UPDATE obj_comments SET body='', mentions='{}', deleted_at=?, deleted_by=? WHERE id=?", (ts, uid, r["id"]))
    return ts


def ocm_restore(c, cid, uid, *, check=True):
    """A comment from the trash back (text, mentions, the kind's rows of that moment). check: it is in the trash (404), uid
    reads the object (404), author or 'manage' (403). -> True, False when nothing is kept (the trash run was quicker, or it
    was deleted before 2.530). Caller commits."""
    r = c.execute("SELECT id, kind, ref_id, user_id, deleted_at FROM obj_comments WHERE id=? AND deleted_at IS NOT NULL FOR UPDATE",
                  (int(cid),)).fetchone()
    if r is None:
        if check:
            raise Denied(404)
        return False
    if check:
        _need_read(c, r["kind"], r["ref_id"], uid)
        if not ocm_may_delete(c, r, uid):
            raise Denied(403, tr(OCM_DEL_TXT))
    if not c.execute("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (r["id"],)).fetchone():
        return False
    rs = _hook(r["kind"], "restore")
    if rs:
        rs(c, r["id"], ocm_ts(r["deleted_at"]))  # the files went with the same time (ocm_trash)
    c.execute("UPDATE obj_comments k SET body=x.body, mentions=x.mentions, deleted_at=NULL, deleted_by=NULL FROM obj_comment_trash x "
              "WHERE x.comment_id=k.id AND k.id=?", (r["id"],))
    c.execute("DELETE FROM obj_comment_trash WHERE comment_id=?", (r["id"],))
    return True


def ocm_trash_drop(c, kind, ref_ids):
    """The kept texts of the deleted comments of (kind, ref_ids) go for good (a project's lock switched: they were not
    converted, collab/cmttrash.py ctt_purge_list). Caller commits."""
    c.execute("DELETE FROM obj_comment_trash WHERE comment_id IN (SELECT id FROM obj_comments WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[])))",
              (kind, st_ids(ref_ids)))


def ocm_purge_user(c, uid):
    """An account is deleted (accounts/users.py): the kept texts of its deleted comments go (nobody may bring its words back;
    the rows stay with user_id NULL), and it leaves the mentions of other comments. Caller commits."""
    with system_ctx(c):  # every organisation's comments
        c.execute("DELETE FROM obj_comment_trash WHERE comment_id IN (SELECT id FROM obj_comments WHERE user_id=? AND deleted_at IS NOT NULL)", (uid,))
        c.execute("UPDATE obj_comments SET mentions=array_remove(mentions, CAST(? AS BIGINT)) WHERE CAST(? AS BIGINT) = ANY(mentions)", (uid, uid))


# ---- notifying (one way for every comment that comes in)
def ocm_after(c, kind, cid, text, mentions, *, notify_mentions=None, nfiles=0, only=None, replied=None, created=True, author=None):
    """What follows a new comment (or new mentions of an edited one), only with collaboration on: the people who read the
    object hear of it (ocm_notify) and the agents get their event, once. -> the pushes to send after the commit."""
    if not collab_all():
        return []
    nm = list(mentions) if notify_mentions is None else list(notify_mentions)
    pushes = ocm_notify(c, kind, cid, text, mentions, nm, nfiles, only=only, replied=replied, author=author)
    live = _hook(kind, "live")
    obj = live(c, c.execute("SELECT ref_id FROM obj_comments WHERE id=?", (int(cid),)).fetchone()[0]) if live else None
    if obj is not None:
        from ..agents.core import agent_comment_events
        agent_comment_events(c, obj, cid, list(mentions), nm + ([replied] if replied and replied not in nm else []), created=created)
    return pushes


def ocm_notify(c, kind, cid, text, mentions, notify_mentions, nfiles, only=None, replied=None, author=None):
    """Who hears of comment cid (News + push, burst state in c; the caller commits) -> [(uid, title, message, click, prio,
    extra)] to send after the commit. Recipients: the task's assignee and creator, who commented before, the list's bell
    "All", the task's "Urgent", its watchers, the mentioned people and the author of the answered comment (replied, counted
    like a mention); only = exactly these. Every one of them goes through the core's send decision (core/objnotify.py
    obj_notify: obj_role >= view, agents never, the settings, the News entry), then the task's bell and the push gates."""
    if kind != "task":
        raise ValueError(kind)
    from ..collab.comments import burst_gate, cmt_card_title, collab_user, comment_plain, comment_push_extra, lang_of
    from ..collab.news import agent_push_ok, bell_all_users, bl9_agent_comment_ok, notif_ok
    from ..collab.liste2e import le2e_mode, le2e_neutral
    from ..notify.push import push_prio, push_reachable
    from ..notify.taskbell import tbl_level, tbl_sent, tbl_urgent_users, TBL_PRIO
    from ..tasks.watchers import wat_users
    from .objnotify import obj_notify
    author = me() if author is None else author
    k = c.execute("SELECT ref_id, user_id, extra->'choices' AS choices, extra->>'suggestion' AS suggestion FROM obj_comments WHERE id=?",
                  (int(cid),)).fetchone()
    t = c.execute("SELECT * FROM tasks WHERE id=?", (k["ref_id"],)).fetchone()
    ids = {t["assignee_id"], t["created_by"]} | set(notify_mentions) | ({replied} if replied else set())
    ids |= {r[0] for r in c.execute(f"SELECT DISTINCT user_id FROM obj_comments WHERE kind='task' AND ref_id=? AND {live_sql()} AND id<?",
                                    (t["id"], int(cid)))}
    ids |= bell_all_users(c, t["list_id"], "comment")  # 2.1.0 (#317): the bell "All" of a list: every comment (2.6.1: or "custom")
    ids |= tbl_urgent_users(c, t["id"])  # 2.53.0 C (#1424): "Urgent" on the task: every comment
    ids |= wat_users(c, t["id"])  # 2.473.0 (#3357): watchers like someone who commented
    if only is not None:
        ids = set(only)
    prev = c.execute(f"SELECT user_id FROM obj_comments WHERE kind='task' AND ref_id=? AND {live_sql()} AND id<? ORDER BY id DESC LIMIT 1",
                     (t["id"], int(cid))).fetchone()
    prev = prev[0] if prev else None
    ids.discard(None)
    ids.discard(author)
    if not ids:
        return []
    names = ocm_names(c, [author] + [int(x) for x in OCM_MENTION_RE.findall(text)])
    snippet = comment_plain(c, text, names)
    snippet = snippet[:280] + ("…" if len(snippet) > 280 else "")
    lk = le2e_mode(c, t["list_id"])  # 2.64.2 D (#1817): a list with the lock: no words of the comment, the list's name instead
    lname = (c.execute("SELECT name FROM lists WHERE id=?", (t["list_id"],)).fetchone() or [""])[0] if lk else ""
    ag = {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent'")}
    # 2.62.0 (#1854): approval cards / questions with buttons / suggestions of an agent always arrive (they wait for the person)
    asks = author in ag and (k["choices"] is not None or k["suggestion"] is not None)
    card = cmt_card_title(k["choices"]) if asks else None  # 2.367.2 (#2968): an approval card names what it is about
    who = names.get(author, "?")
    click = f"{PUBLIC_URL}/#t/{t['id']}"
    out = []
    for uid in sorted(ids - ag):  # agents get events (ocm_after), never a push
        s = collab_user(c, uid)
        if not s or "comments" not in (s.get("features") or "").split(","):  # 2.0.6: comments off -> no comment News / pushes
            continue
        # 2.62.0 (#1854): an agent's comment with "only replies to me" (only the task's "Urgent" still wants every comment)
        p61_ok = bl9_agent_comment_ok(s, uid, author, ag, prev, replied, uid in notify_mentions)
        if not asks and not p61_ok and tbl_level(c, uid, t["id"], s) != "urgent":
            continue
        mentioned = uid in notify_mentions or uid == replied
        row = "mention" if mentioned else "comment" if uid in (t["assignee_id"], t["created_by"]) else \
            "reply" if uid == prev else "follow"  # 2.1.0 (#317): the event of the notification settings (first match)
        ment = uid in notify_mentions
        lg = lang_of(s)

        def follow(u, s, uid=uid, row=row, lg=lg):  # the task's bell first: muted = no push, urgent = its own push
            lv = tbl_level(c, u, t["id"], s)  # 2.53.0 C (#1424)
            if lv == "mute":
                return False
            if u in notify_mentions and notif_ok(c, u, s, row, "push", t["list_id"]):  # 2.142.0 A (#2146): by e-mail
                from ..notify.channels import evm_note
                evm_note(c, u, "mention", t["id"], author, s, cid)
            if lv == "urgent":
                if push_reachable(c, u, s) and not tbl_sent(u, t["id"]):
                    out.append((u, tr("Urgent: {0}", le2e_neutral(lg) if lk else t["title"], lg=lg),
                                tr("{0} commented in {1}", who, lname, lg=lg) if lk else
                                tr("{0} commented: {1}", who, snippet or _files_txt(nfiles, lg), lg=lg),
                                click, TBL_PRIO, comment_push_extra(t, lg)))
                return False
            return True

        def gate(u, s, mentioned=mentioned):  # 2.28.0 (#987): an agent's comments push only when wanted; then the burst gate
            if not push_reachable(c, u, s):
                return False
            if not asks and not mentioned and not agent_push_ok(c, u, s, author) and \
                    not (s.get("agent_comments") == "replies" and u == prev):
                return False  # 2.62.0 (#1854): with "only replies to me" a reply right after my comment pushes like one with reply_to
            return asks or burst_gate(c, u, t["id"], mentioned=mentioned)
        # 2.28.0 (#987): a reply to my comment (the one right before) is marked: it counts as "For you" in the News
        news = {"kind": "mention" if ment else "comment", "task_id": t["id"], "comment_id": int(cid), "actor": author,
                "data": {"reply": 1} if not ment and (uid == prev or uid == replied) else
                {"reach": 1} if not ment and not p61_ok else None}  # 2.66.1 (#1943)
        if not obj_notify(c, "task", t["id"], [uid], row=row, lid=t["list_id"], S={uid: s}, news=news, follow=follow, gate=gate):
            continue
        what = snippet or _files_txt(nfiles, lg)
        if lk:
            msg = tr("{0} mentioned you in {1}", who, lname, lg=lg) if ment else \
                tr("{0} replied to your message in {1}", who, lname, lg=lg) if uid == replied else tr("{0} commented in {1}", who, lname, lg=lg)
            out.append((uid, le2e_neutral(lg), msg, click, push_prio(s), {**comment_push_extra(t, lg), **({"ws": "limit"} if asks else {})}))
            continue
        if card is not None:  # 2.367.2 (#2968): the card's own words; a question waits for the person (mark "limit")
            out.append((uid, tr("Approval needed: {0}", card or t["title"], lg=lg), tr("{0} asks in {1}", who, t["title"], lg=lg),
                        click, push_prio(s), {**comment_push_extra(t, lg), "ws": "limit"}))
            continue
        if asks:
            out.append((uid, t["title"], tr("{0} asks: {1}", who, what, lg=lg), click, push_prio(s), {**comment_push_extra(t, lg), "ws": "limit"}))
            continue
        msg = tr("{0} mentioned you: {1}", who, what, lg=lg) if ment else \
            tr("{0} replied to your message: {1}", who, what, lg=lg) if uid == replied else tr("{0} commented: {1}", who, what, lg=lg)
        out.append((uid, t["title"], msg, click, push_prio(s), comment_push_extra(t, lg)))
    return out


def _files_txt(n, lg):
    return trn("{0} file", "{0} files", n, lg=lg)


# ---- the foreign keys on comments and the move of the old tables (once; core/db.py init_db, before AFTER drops them)
OCM_FK = {"git_issue_comments": ("comment_id", "SET NULL"), "cmt_fts": ("comment_id", "CASCADE")}
OCM_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])[T ]([01]\d|2[0-3]):[0-5]\d(:[0-5]\d(\.\d{1,6})?)?(Z|[+-]\d\d(:?\d\d)?)?$"


def ocm_fk(c, table, col, action):
    """The foreign key of table.col points at obj_comments(id) (ON DELETE action): one on another table (comments) goes,
    values without their comment become NULL / their rows go first. Idempotent (every start)."""
    names = {table, col}
    if not c.execute("SELECT to_regclass(?)", (table,)).fetchone()[0]:
        return
    have = c.execute("""SELECT con.conname, con.confrelid::regclass::text FROM pg_constraint con
                        JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1]
                        WHERE con.contype='f' AND con.conrelid=to_regclass(?) AND a.attname=?""", (table, col)).fetchall()
    if any(r[1].strip('"') == "obj_comments" for r in have):
        return
    for r in have:
        c.execute(f"ALTER TABLE {qi(table, names)} DROP CONSTRAINT {qi(r[0], {r[0]})}")
    gone = f"{qi(col, names)} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM obj_comments k WHERE k.id={qi(table, names)}.{qi(col, names)})"
    if action == "SET NULL":
        c.execute(f"UPDATE {qi(table, names)} SET {qi(col, names)}=NULL WHERE {gone}")
    else:
        c.execute(f"DELETE FROM {qi(table, names)} WHERE {gone}")
    c.execute(f"ALTER TABLE {qi(table, names)} ADD FOREIGN KEY ({qi(col, names)}) REFERENCES obj_comments(id) "
              f"ON DELETE {'SET NULL' if action == 'SET NULL' else 'CASCADE'}")


def _old(cols, name, sql, null="NULL"):
    return sql if name in cols else null


def ocm_move(c):
    """2.972.0 (#5272): the rows of comments / comment_trash_text into obj_comments / obj_comment_trash, while those tables
    are there (the first start of 2.972, or again after a version before 2.972 ran and made them anew), with their ids; an id
    there already stays as it is. Mentions "1,2" -> an array, the extras -> extra (only keys with a value), the times -> real
    points in time (a time not in ISO form: now for created_at / deleted_at, NULL for edited_at). Then the identity goes on
    after the highest id and the foreign keys of git_issue_comments / cmt_fts point at obj_comments. The fragment 5272_a drops
    the old tables right after (one-way). Returns the comments moved."""
    n = 0
    if c.execute("SELECT to_regclass('comments')").fetchone()[0]:
        cols = table_columns(c, "comments")

        def ts(col, other):  # NULL / '' stay NULL (a live comment, one never edited); created_at is never NULL (else now)
            return _old(cols, col, f"CASE WHEN COALESCE(k.{col}, '') = '' THEN {'CURRENT_TIMESTAMP' if col == 'created_at' else 'NULL'} "
                                   f"WHEN k.{col} ~ ? THEN k.{col}::timestamptz ELSE {other} END", other)
        iso_args = sum(1 for x in ("created_at", "edited_at", "deleted_at") if x in cols)

        def ex(key, sql):  # a key only when there is a value (no jsonb_strip_nulls: it would cut the nulls inside choices too)
            return _old(cols, key, f"CASE WHEN {sql} IS NOT NULL THEN jsonb_build_object('{key}', {sql}) ELSE '{{}}'::jsonb END", "'{}'::jsonb")
        extra = " || ".join((ex("suggestion", "to_jsonb(NULLIF(k.suggestion, ''))"), ex("choices", "k.choices"), ex("choice", "k.choice"),
                             _old(cols, "portal", "CASE WHEN k.portal <> 0 THEN jsonb_build_object('portal', true) ELSE '{}'::jsonb END", "'{}'::jsonb"),
                             ex("rule_name", "NULLIF(k.rule_name, '')")))
        ment = ("COALESCE((SELECT array_agg(CAST(btrim(x) AS BIGINT) ORDER BY o) FROM unnest(string_to_array(k.mentions, ',')) "
                "WITH ORDINALITY u(x, o) WHERE btrim(x) ~ '^[0-9]{1,18}$'), '{}')")
        n = c.execute(f"""INSERT INTO obj_comments(id, kind, ref_id, org_id, user_id, ext_name, parent_id, body, mentions, extra,
                                                  client_ref, created_at, edited_at, deleted_at)
                          SELECT k.id, 'task', k.task_id, {_old(cols, 'org_id', 'k.org_id')}, k.user_id, {_old(cols, 'ext_name', 'k.ext_name')},
                                 {_old(cols, 'reply_to', 'k.reply_to')}, COALESCE(k.body, ''), {ment if 'mentions' in cols else "'{}'"}, {extra},
                                 {_old(cols, 'client_ref', 'k.client_ref')}, {ts('created_at', 'CURRENT_TIMESTAMP')},
                                 {ts('edited_at', 'NULL')}, {ts('deleted_at', 'CURRENT_TIMESTAMP')}
                          FROM comments k JOIN tasks t ON t.id=k.task_id
                          ON CONFLICT DO NOTHING""", (OCM_ISO,) * iso_args).rowcount
        if c.execute("SELECT to_regclass('comment_trash_text')").fetchone()[0]:
            c.execute(f"""INSERT INTO obj_comment_trash(comment_id, body, mentions)
                          SELECT x.comment_id, x.body, {ment.replace('k.mentions', 'x.mentions')}
                          FROM comment_trash_text x JOIN obj_comments k ON k.id=x.comment_id ON CONFLICT DO NOTHING""")
        # review 2.972: past the old table's last id too (a comment deleted for good keeps its number: never handed out again)
        ol = c.execute("SELECT pg_sequence_last_value(CAST(pg_get_serial_sequence('comments', 'id') AS regclass))").fetchone()[0] or 0
        c.execute("SELECT setval(pg_get_serial_sequence('obj_comments', 'id'), GREATEST(MAX(id), ?, 1), MAX(id) IS NOT NULL OR ? > 0) "
                  "FROM obj_comments", (int(ol), int(ol)))
    for table, (col, action) in OCM_FK.items():
        ocm_fk(c, table, col, action)
    return n


MOVE.append(ocm_move)  # core/db.py init_db, before the fragments' AFTER (core/objhooks.py)
USER_GONE.append(ocm_purge_user)  # accounts/users.py, before an account goes
