"""Comments, mentions, the activity timeline and collaboration pushes."""
import json
import os
import re
import time
from datetime import date
from flask import g, has_request_context, jsonify, request

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.env import env_bool
from ..core.pg import insert_id, write_lock
from ..core.i18n import LANGS, short_day, tr, trn
from ..core.db import body, bump, db, err, inbox_default, iso, iso_ms, local_now, now_utc, usettings
from ..accounts.session import me
from ..accounts.bgjobs import bgj_add, bgj_fn  # 2.370.3 (#2760)
from ..core.access import collab_all, Denied, list_people, list_role, MANAGE_ROLES, need_feat, need_task, task_visible, pvis
from ..core.serializers import unlink_files
from ..tasks.tasks import WEB_COMMENT
from ..tasks.validation import ACT_NOTES  # 2.394.0 C (#3377)
from ..tasks.attachments import save_attachments
from ..tasks.oneway import dec_list, gate_irreversible
from .replies import reply_check, with_replies
from ..core.errors import BadInput, web_fields  # 2.149.0 G (#2517): pulled up from functions


# ---------------------------------------------------------------- comments + activity timeline
# Everyone who sees a task may comment on it (view-only members too; they still cannot change the
# task). A private task's comments are a personal log. Authors edit / delete their own comments; the
# list owner and the list's admins (1.10.0) may delete any comment in the list (moderation). Instance admins have no extra
# rights here. Participants comment only on their own tasks (never on a context parent).
# Deleted comments disappear (soft delete: body, mentions and files are wiped).
# Mentions are stored as <@user_id> tokens (+ comments.mentions); only people who see the task count.
MAX_COMMENT = 10000
MAIL_REPLY = {}  # 2.393.2 B (#3375): integrations/taskmail.py (info / check / send of "also by e-mail to the reporter")
MENTION_RE = re.compile(r"<@(\d+)>")


def user_names(c, ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r["display_name"] or r["username"]
            for r in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q})", ids)}


def h6r_shared_people(c, lid, uid):
    """2.86.0 (N20 review): the people a participant uid of list lid may see in it -- the owner, uid and everybody who
    shares a task with uid (full roles see every task, other participants only their own); None = uid is no participant."""
    if list_role(c, lid, uid) != "participant":
        return None
    own = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    keep = {uid, own[0]} if own else {uid}
    mine = pvis(c, uid, lid)[1]  # the tasks uid sees in full
    if not mine:
        return keep
    for (p,) in c.execute("SELECT user_id FROM list_members WHERE list_id=? AND user_id<>?", (lid, uid)).fetchall():
        role = list_role(c, lid, p)
        if role and (role != "participant" or pvis(c, p, lid)[1] & mine):
            keep.add(p)
    return keep


def task_people(c, lid, tid=None):
    """Enabled users who can see the tasks of a list (owner + members): the mention picker."""
    ids = list_people(c, lid)
    if not tid and has_request_context():  # 2.86.0 (N20 review): a participant without a task: who shares one with them
        sh = h6r_shared_people(c, lid, me())
        if sh is not None:
            ids = ids & sh
    q = ",".join("?" * len(ids)) or "NULL"
    out = [{"id": r["id"], "name": r["display_name"] or r["username"]}
           for r in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q}) AND disabled=0 ORDER BY id",
                              list(ids))]
    if tid and has_request_context() and list_role(c, lid) == "participant":
        # 2.86.0 (N20): a participant sees only the people who share this task with them, not the whole member list
        out = [p for p in out if p["id"] == me() or task_visible(c, tid, p["id"], full=True)]
    return out


def mention_names(c, ids):
    """2.148.1 A (#2490): {id: name} for the '@name' of a mention that is not kept -- only people the writer may see
    (else '@?', so a mention never tells the name of an unknown account)."""
    from ..accounts.orgs import visible_people
    names = user_names(c, ids)
    vis = visible_people(c, me()) if has_request_context() and getattr(g, "user", None) is not None else set()
    return names if vis is None else {k: v for k, v in names.items() if k in vis}


def clean_mentions(c, lid, text, tid=None):
    """Keeps <@id> tokens of people who see the list; any other token becomes plain '@name' (2.148.1 A, #2490: '@?' for
    someone the writer may not see)."""
    allowed = {p["id"] for p in task_people(c, lid, tid)}  # 2.86.0 (N20): tid narrows it for a participant
    names = mention_names(c, [int(x) for x in MENTION_RE.findall(text)])
    found = []

    def sub(m):
        uid = int(m.group(1))
        if uid in allowed:
            found.append(uid)
            return m.group(0)
        return "@" + names.get(uid, "?")
    text = MENTION_RE.sub(sub, text)
    return text, list(dict.fromkeys(found))


def comment_plain(c, text, names=None):
    """Comment text for a push: tokens -> @name, whitespace collapsed."""
    names = names or user_names(c, [int(x) for x in MENTION_RE.findall(text)])
    return re.sub(r"\s+", " ", MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), text)).strip()


def att_dicts(c, where, args):
    out = {}
    for a in c.execute(f"SELECT id, comment_id, name, mime, size, created_at, enc, e2e_gen FROM attachments WHERE ({where}) AND deleted_at IS NULL ORDER BY id", args):  # 2.272.0 E2 (#3038): not the trash
        d = {k: a[k] for k in ("id", "name", "mime", "size", "created_at")}
        if a["enc"] == 2:  # 2.64.2 B (#1817): a list file (name = list ciphertext)
            d.update(enc=2, e2e_gen=a["e2e_gen"])
        out.setdefault(a["comment_id"], []).append(d)
    if out:  # 2.61.0 (#1818): + up (virus scan marks)
        from ..files.scan import sc_up
        sc_up(c, "att", [d for v in out.values() for d in v])
    return out


def comment_dict(r, atts):
    return {"id": r["id"], "user_id": r["user_id"], "body": r["body"], "created_at": r["created_at"],
            "edited_at": r["edited_at"], "mentions": [int(x) for x in (r["mentions"] or "").split(",") if x],
            "attachments": atts.get(r["id"], []), "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None,
            "reply_to": r["reply_to"] if "reply_to" in r.keys() else None,  # 2.33.0 (#1076): + reply (with_replies)
            "ext_name": r["ext_name"] if "ext_name" in r.keys() else None,  # 2.50.0 (#329): written by a customer through the public link
            "portal": bool(r["portal"]) if "portal" in r.keys() else False,  # 2.63.0 B (#1513): the customer sees it (answer / their own)
            "rule_name": r["rule_name"] if "rule_name" in r.keys() else None}  # 2.71.0 A (#1457): written by a list rule


def need_live_comment(c, cid):
    """(comment row, my role in its list): 404 if the comment is gone or its task is not visible."""
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    return r, need_task(c, r["task_id"], write=False, full=True)


@app.get("/api/tasks/<int:tid>/timeline")
def timeline(tid):
    """Comments + activity of a task (loaded when the detail panel opens) and the mention picker.
    2.0.6 (#315): comments no longer need collaboration (personal notes); without it (instance switch off)
    there is no activity and nobody to mention."""
    from ..personal.timetrack import vis_ids
    from ..tasks.dependencies import DEP_ACTS
    from ..team.portal import pt_ticket_info
    from ..agents.core import agent_ids, is_approver
    from ..collab.reactions import with_reactions
    c = db()
    role = need_task(c, tid, write=False, full=True)
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    rows = c.execute("SELECT * FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,)).fetchall()
    atts = att_dicts(c, "task_id=? AND comment_id IS NOT NULL", (tid,))
    # 2.370.4 (#3089 E2-N11): a comment without text whose files all lie in the trash is not shown (restoring one brings it back)
    gone = {r[0] for r in c.execute("SELECT DISTINCT comment_id FROM attachments WHERE task_id=? AND comment_id IS NOT NULL "
                                    "AND deleted_at IS NOT NULL", (tid,))}
    rows = [r for r in rows if not (r["id"] in gone and r["id"] not in atts and not (r["body"] or "").strip() and not r["suggestion"])]
    acts = [{"id": a["id"], "user_id": a["user_id"], "kind": a["kind"], "data": json.loads(a["data"] or "{}"),
             "created_at": a["created_at"]}
            for a in c.execute("SELECT * FROM activity WHERE task_id=? ORDER BY id", (tid,))] if collab_all() else []
    vis = None
    acts = [a for a in acts if a["kind"] not in ("paperless", "paperless_rm", "paperless_send")]  # 2.36.0 (#1116): connection removed
    for a in acts:
        if a["kind"] in DEP_ACTS and a["data"].get("id"):
            vis = vis if vis is not None else vis_ids(c, me())
            o = c.execute("SELECT list_id FROM tasks WHERE id=?", (a["data"]["id"],)).fetchone()
            if not o or o["list_id"] not in vis or not task_visible(c, a["data"]["id"], me()):
                a["data"] = {"hidden": True}
    from ..tasks.multilist import ml_acts
    ml_acts(c, acts)  # 2.71.0 B (#1459): a further list's name only for who sees it
    comments = with_replies(c, "c", with_reactions(c, [comment_dict(r, atts) for r in rows]))
    from .cchoice import lv_with_choices
    lv_with_choices(c, tid, rows, comments)  # 2.41.0 (#1383): answer buttons / approval cards
    ids = {x["user_id"] for x in comments + acts} | {m for x in comments for m in x["mentions"]} \
        | {a["data"].get("to") for a in acts if a["kind"] == "assign"} | {a["data"].get("agent") for a in acts} | {a["data"].get("approver") for a in acts} \
        | {a["data"].get("by") for a in acts} | {u["id"] for x in comments for e in x["reactions"] for u in e["users"]} \
        | {x["reply"]["user_id"] for x in comments if x.get("reply")} \
        | {a["data"].get("reviewer") for a in acts if a["kind"] == "review"}  # 2.82.0 (#1880): a reviewer has access to the list
    seen = c.execute("SELECT seen_id FROM task_seen WHERE user_id=? AND task_id=?", (me(), tid)).fetchone()
    ag = agent_ids(c)
    from .chatsave import chat_save_of  # 2.42.0 (#1383): an agent's comment I saved as a task
    saved = chat_save_of(c, me(), "comment", [x["id"] for x in comments])  # 2.139.0 D (#2130): every comment
    trow = None
    for x in comments:
        if x["id"] in saved:
            x["saved_task_id"] = saved[x["id"]]
        sk = (x.get("suggestion") or {}).get("kind") if isinstance(x.get("suggestion"), dict) else None
        if sk in ("merge_request", "integrate", "deploy") and x["user_id"] in ag:  # 2.190.0 C (#2561): who may decide this request
            trow = trow or c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            x["may_decide"] = is_approver(c, trow, me(), agent=x["user_id"], assignee=sk == "merge_request")
            if sk != "merge_request" and x["suggestion"].get("state") == "open":  # 2.392.0 C (#3370): what blocks NOW, for this reader
                x["suggestion"]["irreversible"] = gate_irreversible(c, trow, sk, me())
    ppl = task_people(c, t["list_id"], tid) if collab_all() else []  # 2.86.0 (N20)
    for p in ppl:
        if p["id"] in ag:
            p["agent"] = True
    return jsonify(comments=comments, activity=acts, users={str(k): v for k, v in user_names(c, ids).items()},
                   people=ppl, seen=seen[0] if seen else 0, moderator=role in MANAGE_ROLES,
                   agents=sorted(i for i in ids | {p["id"] for p in ppl} if i in ag),
                   can_write=task_visible(c, tid, me(), write=True),
                   approver=is_approver(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), me()),  # 2.2.0 (#339)
                   ticket=pt_ticket_info(c, tid, me()),  # 2.63.0 B (#1513): a customer's report (box in the task panel)
                   mail_reporter=MAIL_REPLY["info"](c, tid, me()) if MAIL_REPLY else None,  # 2.393.2 B (#3375)
                   decisions=dec_list(c, tid),  # 2.392.0 C (#3370): the section at the top of the task panel
                   may_yes=is_approver(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), me(), assignee=False))  # who gives the yes to a one-way task


@app.post("/api/tasks/<int:tid>/seen")
def timeline_seen(tid):
    """Marks every comment of the task as seen by me (no version bump: only my unread dot changes)."""
    from ..notify.push import push_handled
    c = db()
    need_task(c, tid, write=False, full=True)
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM comments WHERE task_id=?", (tid,)).fetchone()[0]
    c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
              "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=GREATEST(task_seen.seen_id, excluded.seen_id)", (me(), tid, top))
    c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND task_id=? AND read_at IS NULL", (iso(now_utc()), me(), tid))
    push_handled(c, me(), [tid])
    c.commit()
    return jsonify(ok=True, seen=top)


def comment_input():
    """(text, files) from a JSON body or a multipart form (comment with files)."""
    if request.files or request.form:
        web_fields({k: 1 for k in [*request.form, *request.files]}, {"body", "file", "reply_to", "portal", "client_ref", "mail_reporter"}, "POST /api/tasks/{tid}/comments (form)")
        return (request.form.get("body") or "").strip(), [f for f in request.files.getlist("file") if f and f.filename]
    web_fields(body(), WEB_COMMENT, "POST /api/tasks/{tid}/comments")
    return (body().get("body") or "").strip(), []


def comment_reply_in():
    """2.33.0 (#1076): reply_to of a JSON body or a multipart form."""
    return request.form.get("reply_to") if (request.files or request.form) else body().get("reply_to")


def comment_ref(c, tid):
    """2.370.2 (#3088): (client_ref of the request or None, the person's comment already made with it or None): sent again
    (the answer got lost) = that comment. One deleted since gives its ref free: the same text may come anew."""
    v = request.form.get("client_ref") if (request.files or request.form) else body().get("client_ref")
    ref = v.strip()[:64] or None if isinstance(v, str) else None
    if not ref:
        return None, None
    write_lock(c, f"comment-ref-{me()}")
    r = c.execute("SELECT * FROM comments WHERE task_id=? AND user_id=? AND client_ref=?", (tid, me(), ref)).fetchone()
    if r and r["deleted_at"]:
        c.execute("UPDATE comments SET client_ref=NULL WHERE id=?", (r["id"],))
        r = None
    return ref, r


def comment_answer(c, tid, r):
    from ..collab.reactions import with_reactions
    from .cchoice import lv_with_choices
    return jsonify(lv_with_choices(c, tid, [r], with_replies(c, "c", with_reactions(c, [comment_dict(r, att_dicts(c, "comment_id=?", (r["id"],)))])))[0])


@app.post("/api/tasks/<int:tid>/comments")
def comment_create(tid):
    """2.0.6 (#315): also without collaboration (a personal note). Only with collaboration on (instance switch):
    @mentions, pushes, News and agent events; comments off in my settings: refused (409), agents excepted."""
    from ..integrations.webhooks import wh_note
    from ..agents.core import agent_comment_events, is_agent, tidy_agent_of
    from ..collab.reactions import clean_suggestion, with_reactions
    from ..integrations.git import GIT_COMMENT_CMD, git_merge_link, git_merge_request
    c = db()
    if not is_agent(g.user):
        need_feat("comments")
    need_task(c, tid, write=False, full=True)  # view-only members may comment (participants: on their own tasks)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if t["deleted_at"]:
        return err(tr("The task is in the trash"), 409)
    text, files = comment_input()
    ref, hit = comment_ref(c, tid)  # 2.370.2 (#3088)
    if hit:
        return comment_answer(c, tid, hit)
    from .liste2e import le2a_comment_in, le2a_text_max, le2e_mode
    if len(text) > le2a_text_max(text, MAX_COMMENT):  # 2.64.1 (#1817): a ciphertext is longer than its text
        return err(tr("The comment is too long (max. {0} characters)", MAX_COMMENT))
    if not text and not files:
        return err(tr("The comment is empty"))
    mrep = request.form.get("mail_reporter") if (request.files or request.form) else body().get("mail_reporter")
    try:  # 2.393.2 B (#3375): "also by e-mail to the reporter" (people who may change the task, never a list with the lock)
        mrep = MAIL_REPLY["check"](c, tid, me(), mrep) if MAIL_REPLY else False
    except ValueError as e:
        return err(str(e))
    if le2e_mode(c, t["list_id"]) or text.startswith("e2e1:"):  # 2.64.1 (#1817): ciphertext + mentions from the browser
        text, mentions = le2a_comment_in(c, t["list_id"], text, t["id"])  # 2.86.0 (N20 review): + task
    else:
        text, mentions = clean_mentions(c, t["list_id"], text, t["id"]) if collab_all() else (text, [])
    try:  # 2.33.0 (#1076): a reply to a comment of the same task (else 400)
        orig = reply_check(c, "c", comment_reply_in(), task_id=tid)
    except BadInput as e:
        return err(str(e))
    sug = body().get("suggestion") if not (request.files or request.form) else None
    if isinstance(sug, dict) and sug.get("kind") == "merge_request":  # 2.2.0 (#339): "ready to merge" of a coding agent
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        try:
            sug = git_merge_request(c, t, sug)
        except BadInput as e:
            return err(str(e))
    elif isinstance(sug, dict) and sug.get("kind") in ("integrate", "deploy"):  # 2.26.0 (#949): ready to integrate / deploy
        from ..agents.gates import gate_clean
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        try:
            sug = gate_clean(c, t, sug)
        except BadInput as e:
            return err(str(e))
    elif sug is not None:  # 2.0.0: a tidy suggestion (agents, in lists with tidying on)
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if (c.execute("SELECT agent_tidy FROM lists WHERE id=?", (t["list_id"],)).fetchone()[0] or "off") == "off":
            return err(tr("Tidying up is turned off in this project"), 409)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        if tidy_agent_of(c, t["list_id"]) != me():  # 2.4.1 (#379)
            return err(tr("Another agent tidies up this project"), 403)
        try:
            sug = {**clean_suggestion(c, t, sug), "state": "open"}
        except BadInput as e:
            return err(str(e))
    from ..team.portal import pt_comment_flag
    try:  # 2.63.0 B (#1513): portal = an answer the customer sees (only on a task with a ticket, by people who may change it)
        portal = pt_comment_flag(c, tid, me(), request.form.get("portal") if (request.files or request.form) else body().get("portal"))
    except BadInput as e:
        return err(str(e))
    from .cchoice import lv_choices_in, lv_with_choices
    try:  # 2.41.0 (#1383): an agent's answer buttons / approval card (the chat's format)
        chs = lv_choices_in(body(), is_agent(g.user)) if not (request.files or request.form) else None
    except BadInput as e:
        return err(str(e))
    if portal and (sug or chs):  # 2.63.0 B (#1513): the customer sees text (and the files are not shown to them)
        return err(tr("Suggestions and answer buttons cannot go to a client"))
    if mrep and (sug or chs):  # the files of the comment stay in Kalmido (the mail carries the text)
        return err(tr("Only a text goes to the reporter by e-mail"))
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,suggestion,reply_to,choices,portal,client_ref) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (tid, me(), text, ",".join(map(str, mentions)), iso_ms(now_utc()),
                     json.dumps(sug, ensure_ascii=False) if sug else None, orig["id"] if orig else None, chs, portal, ref))
    replied = orig["user_id"] if orig and orig["user_id"] != me() else None
    if sug and sug.get("kind") == "merge_request":
        git_merge_link(c, t, sug)
    saved = []
    if files and le2e_mode(c, t["list_id"]):  # 2.64.2 B (#1817): list files, encrypted in the browser (names: list ciphertexts)
        from .liste2efile import le2f_save
        e = le2f_save(c, tid, files, request.form.getlist("le2e_name"), comment_id=cid, saved=saved)
    else:
        e = save_attachments(c, tid, files, comment_id=cid, saved=saved) if files else None
    if e:
        c.rollback()
        unlink_files(saved)
        return err(e)
    c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
              "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=GREATEST(task_seen.seen_id, excluded.seen_id)", (me(), tid, cid))
    ptext = text
    if chs and json.loads(chs).get("approval"):  # 2.41.0 (#1383): the push says that an approval is needed
        ptext = tr("Approval needed") + ": " + json.loads(chs)["approval"]["title"] + ("\n" + text if text else "")
    pushes = comment_pushes(c, t, cid, ptext, mentions, mentions, len(files), replied=replied) if collab_all() else []
    if collab_all():  # 2.33.0 (#1076): an agent whose comment is answered hears it like a mention
        agent_comment_events(c, t, cid, mentions, mentions + ([replied] if replied and replied not in mentions else []))
    wh_note(c, tid, "comment", cid=cid)
    from ..notify.channels import chn_note
    chn_note(c, tid, "comment", cid=cid)  # 2.142.0 A (#2145): organisation channels / channels of own lists
    if not portal and not sug and not chs:  # 2.394.0 C (#3377): a comment of a linked task goes to its issue
        for f in ACT_NOTES:
            f(c, tid, "comment", cid)
    bump(c)
    c.commit()
    send_pushes(pushes)
    hint = GIT_COMMENT_CMD[0](c, t, text) if not portal else None  # 2.392.0 B (#3364): "partly: rest in Y" in the first line
    sent = MAIL_REPLY["send"](c, tid, me(), cid) if mrep else None  # 2.393.2 B (#3375): '' = sent, else an error code
    r = comment_answer(c, tid, c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone())
    extra = {**({"partial": hint} if hint else {}), **({"mail_reporter": sent or "sent"} if mrep else {})}
    return jsonify({**r.get_json(), **extra}) if extra else r


@app.patch("/api/comments/<int:cid>")
def comment_update(cid):
    """Only the author edits a comment; people mentioned for the first time are notified (with collaboration on)."""
    from ..agents.core import agent_comment_events, is_agent
    from ..collab.reactions import with_reactions
    c = db()
    if not is_agent(g.user):
        need_feat("comments")
    r, _ = need_live_comment(c, cid)
    if r["user_id"] != me():
        return err(tr("Only the author can edit this comment"), 403)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
    text = (web_fields(body(), {"body", "mentions"}, "PATCH /api/comments/{cid}").get("body") or "").strip()
    from .liste2e import le2a_comment_in, le2a_text_max, le2e_mode
    if len(text) > le2a_text_max(text, MAX_COMMENT):  # 2.64.1 (#1817)
        return err(tr("The comment is too long (max. {0} characters)", MAX_COMMENT))
    nfiles = c.execute("SELECT COUNT(*) FROM attachments WHERE comment_id=? AND deleted_at IS NULL", (cid,)).fetchone()[0]
    if not text and not nfiles:
        return err(tr("The comment is empty"))
    if le2e_mode(c, t["list_id"]) or text.startswith("e2e1:"):  # 2.64.1 (#1817): ciphertext + mentions from the browser
        text, mentions = le2a_comment_in(c, t["list_id"], text, t["id"])  # 2.86.0 (N20 review): + task
    else:
        text, mentions = clean_mentions(c, t["list_id"], text, t["id"]) if collab_all() else (text, [])
    old = {int(x) for x in (r["mentions"] or "").split(",") if x}
    c.execute("UPDATE comments SET body=?, mentions=?, edited_at=? WHERE id=?",
              (text, ",".join(map(str, mentions)), iso(now_utc()), cid))
    new_m = [m for m in mentions if m not in old] if collab_all() else []
    if not t["deleted_at"]:  # 2.39.0 (#1179): agents that got this comment as an event learn the change (before new mentions)
        from ..agents.chat import med_comment_edited
        med_comment_edited(c, t, c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone(), r["body"])
    pushes = comment_pushes(c, t, cid, text, mentions, new_m, 0, only=new_m) if new_m and not t["deleted_at"] else []
    if new_m and not t["deleted_at"]:
        agent_comment_events(c, t, cid, mentions, new_m, created=False)
    bump(c)
    c.commit()
    send_pushes(pushes)
    return jsonify(with_replies(c, "c", with_reactions(c, [comment_dict(c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone(),
                                                                         att_dicts(c, "comment_id=?", (cid,)))]))[0])


@app.delete("/api/comments/<int:cid>")
def comment_delete(cid):
    """Author, or the owner of the list (moderation). The comment disappears with its files."""
    c = db()
    r, role = need_live_comment(c, cid)
    if r["user_id"] != me() and role not in MANAGE_ROLES:
        return err(tr("Only the author or the project owner can delete this comment"), 403)
    files = [a[0] for a in c.execute("SELECT path FROM attachments WHERE comment_id=?", (cid,))]
    c.execute("DELETE FROM attachments WHERE comment_id=?", (cid,))
    c.execute("UPDATE comments SET body='', mentions='', deleted_at=? WHERE id=?", (iso(now_utc()), cid))
    c.execute("UPDATE agent_rules SET source_excerpt='' WHERE source_kind='comment' AND source_id=?", (cid,))  # 2.235.0 B2 (#2903): nor its copy in a rule
    from ..collab.news import news_forget_comment
    news_forget_comment(c, cid)  # 2.306.0 C (#2889)
    bump(c)
    c.commit()
    unlink_files(files)
    return jsonify(ok=True)


# ---- collaboration pushes (module "collab" of the recipient must be on; never to the person who acted;
# only users who still see the task; each via their own ntfy topic, in their own language; click opens it)
#  - comment: assignee, creator, watchers, everyone who commented before + mentioned people (even non-participants)
#  - assign / unassign: the new assignee / the previous one when someone else (re)assigns the task
#  - complete: creator + whoever assigned it, when someone else completes a task in a shared list
# Burst rule, shared by all of them (per recipient and task): the first push goes out right away; anything
# else on that task in the next TASK_PUSH_GAP seconds is only counted, and once that minute is over the
# watchdog sends ONE summary ("2 more comments · 1 more change", "you were mentioned").
TASK_PUSH_GAP = int(os.environ.get("TASKS_PUSH_GAP", "60"))  # seconds


def collab_on(s):
    return collab_all() and "collab" in (s.get("features") or "").split(",")


def collab_user(c, uid, lid=None):
    """Settings of a user who takes part in collaboration notifications (News feed and pushes) about
    list lid -- enabled, module "collab" on, still sees the list (lid None: no list check) -- else None.
    The feed entry is written for every such user; the push additionally needs an ntfy topic + burst gate."""
    u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or (lid is not None and not list_role(c, lid, uid)):
        return None
    s = usettings(c, uid)
    return s if collab_on(s) else None


# 2.367 (#2967): the gate above is per task, so 10 tasks assigned at once were 10 pushes. push_gate counts per person and
# scope: a<actor> = from the third push of one actor inside the gap only counted (PERSON_PUSH_FREE; an @mention always
# comes), r<room> = one chat push per room and gap. The watchdog then sends one summary with the count (never a text).
PUSH_BUNDLE_ON = env_bool("KALMIDO_PUSH_BUNDLE", True)  # the test containers switch it off (start.sh), the suites count single pushes
PERSON_PUSH_FREE = 2


def push_gate(c, uid, scope, free, kind="", ref=0, actor=0):
    """True = push now; False = counted for the summary. The caller commits."""
    if not PUSH_BUNDLE_ON:
        return True
    now = time.time()
    r = c.execute("SELECT * FROM push_gate WHERE user_id=? AND scope=?", (uid, scope)).fetchone()
    if r and (r["held"] or now - r["started_at"] < TASK_PUSH_GAP):  # (held: the watchdog has not sent the summary yet)
        hold = r["n"] >= free
        c.execute("UPDATE push_gate SET n=n+1, held=held+?, kind=?, ref=?, actor=? WHERE user_id=? AND scope=?",
                  (1 if hold else 0, kind if r["kind"] == kind else "", ref if r["ref"] == ref else 0,
                   actor if r["actor"] == actor else 0, uid, scope))
        return not hold
    c.execute("""INSERT INTO push_gate(user_id,scope,started_at,n,held,kind,ref,actor) VALUES(?,?,?,1,0,?,?,?)
                 ON CONFLICT(user_id,scope) DO UPDATE SET started_at=excluded.started_at, n=1, held=0, kind=excluded.kind,
                 ref=excluded.ref, actor=excluded.actor""", (uid, scope, now, kind, ref, actor))
    return True


def push_gate_due(c, prefix):
    """The gates of one scope type whose window is over and that hold something."""
    return c.execute("SELECT * FROM push_gate WHERE held>0 AND started_at<=? AND substr(scope,1,1)=?",
                     (time.time() - TASK_PUSH_GAP, prefix)).fetchall()


def push_gate_reset(c, p):
    """The summary of gate row p goes out now: a new window starts with it (so the room's "one per gap" holds), before sending: never twice."""
    c.execute("UPDATE push_gate SET started_at=?, n=?, held=0, kind='', ref=0, actor=0 WHERE user_id=? AND scope=?",
              (time.time(), PERSON_PUSH_FREE, p["user_id"], p["scope"]))
    c.commit()


def push_gate_tick(c, users, S, LG):
    """Watchdog: one summary per person and actor ("Anna assigned you 10 tasks", opens the list when it was one list)."""
    from ..notify.push import _wd_fail
    for p in push_gate_due(c, "a"):
        try:
            _push_gate_one(c, p, users, S, LG)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "bundled push", (p["user_id"], p["scope"]), e)
    c.execute("DELETE FROM push_gate WHERE held=0 AND started_at<?", (time.time() - 86400,))
    c.commit()


def _push_gate_one(c, p, users, S, LG):
    from ..notify.push import notify, push_prio
    push_gate_reset(c, p)
    uid = p["user_id"]
    if uid not in users:
        return
    lg, click = LG[uid], f"{PUBLIC_URL}/#today"
    if p["ref"] and list_role(c, p["ref"], uid):  # the person can still open that list
        click = f"{PUBLIC_URL}/#l/{p['ref']}"
    who = user_names(c, [p["actor"]]).get(p["actor"]) if p["actor"] else None
    msg = trn("assigned you {0} task", "assigned you {0} tasks", p["n"], lg=lg) if p["kind"] == "assign" else \
        trn("{0} notification", "{0} notifications", p["n"], lg=lg)
    notify(uid, who or APP_NAME, msg, push_prio(S[uid]), click, s=S[uid], tag=f"gate-{p['actor']}", kind="assign" if p["kind"] == "assign" else "other")


def burst_gate(c, uid, tid, mentioned=False, event=False, kind=""):
    """True = push now (time remembered); False = counted for the watchdog's summary.
    2.367 (#2967): kind = what the second gate's summary says (push_gate); an @mention passes it."""
    if any(f(c, uid) for f in PUSH_BURST_SKIP):  # 2.236.0 (#2909 #2905): an agent's work style drops / holds it
        return False
    now = time.time()
    st = c.execute("SELECT sent_at FROM task_push WHERE user_id=? AND task_id=?", (uid, tid)).fetchone()
    if st and now - st["sent_at"] < TASK_PUSH_GAP:
        c.execute("""UPDATE task_push SET pending=pending+?, events=events+?, mentioned=GREATEST(mentioned,?)
                     WHERE user_id=? AND task_id=?""", (0 if event else 1, 1 if event else 0, 1 if mentioned else 0, uid, tid))
        return False
    if not mentioned:
        actor = g.get("user") if has_request_context() else None
        tl = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
        if not push_gate(c, uid, f"a{actor['id'] if actor else 0}", PERSON_PUSH_FREE, kind, tl[0] if tl else 0, actor["id"] if actor else 0):
            return False
    # 2.421.0 (#3512): the counters of the last window stay - the watchdog sends them (also "you were mentioned") one gap later
    c.execute("INSERT INTO task_push(user_id,task_id,sent_at) VALUES(?,?,?) ON CONFLICT(user_id,task_id) "
              "DO UPDATE SET sent_at=excluded.sent_at", (uid, tid, now))
    return True


def lang_of(s):
    return s.get("lang") if s.get("lang") in LANGS else "en"


def comment_pushes(c, t, cid, text, mentions, notify_mentions, nfiles, only=None, replied=None):
    """Decides who gets a push for this comment (burst state updated in c, caller commits).
    Returns [(user id, title, message, click, priority)] to send after the commit.
    2.33.0 (#1076): replied = the author of the answered comment: "replied to your message", counted like a mention."""
    from ..collab.news import agent_push_ok, bell_all_users, bl9_agent_comment_ok, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_ids
    author = me()
    ids = {t["assignee_id"], t["created_by"]} | set(notify_mentions) | ({replied} if replied else set())
    before = {r[0] for r in c.execute("SELECT DISTINCT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id<?",
                                      (t["id"], cid))}
    ids |= before
    ids |= bell_all_users(c, t["list_id"], "comment")  # 2.1.0 (#317): the bell "All" of a list: every comment (2.6.1: or "custom")
    from ..notify.taskbell import tbl_level, tbl_sent, tbl_urgent_users, TBL_PRIO
    ids |= tbl_urgent_users(c, t["id"])  # 2.53.0 C (#1424): "Urgent" on the task: every comment
    from ..tasks.watchers import wat_users
    ids |= wat_users(c, t["id"])  # 2.473.0 (#3357): watchers like someone who commented (row "follow"); rights checked per person below
    if only is not None:
        ids = set(only)
    prev = c.execute("SELECT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id<? ORDER BY id DESC LIMIT 1",
                     (t["id"], cid)).fetchone()
    prev = prev[0] if prev else None
    ids.discard(None)
    ids.discard(author)
    if not ids:
        return []
    names = user_names(c, [author] + [int(x) for x in MENTION_RE.findall(text)])
    snippet = comment_plain(c, text, names)
    snippet = snippet[:280] + ("…" if len(snippet) > 280 else "")
    from .liste2e import le2e_mode, le2e_neutral
    lk = le2e_mode(c, t["list_id"])  # 2.64.2 D (#1817): a list with the lock: no words of the comment, the list's name instead
    lname = (c.execute("SELECT name FROM lists WHERE id=?", (t["list_id"],)).fetchone() or [""])[0] if lk else ""
    out = []
    ag = agent_ids(c)
    # 2.62.0 (#1854): approval cards / questions with buttons / suggestions of an agent always arrive (they wait for the person)
    ask = c.execute("SELECT choices, suggestion FROM comments WHERE id=?", (cid,)).fetchone()
    asks = author in ag and (ask["choices"] is not None or ask["suggestion"] is not None)
    card = cmt_card_title(ask["choices"]) if asks else None  # 2.367.2 (#2968): an approval card names what it is about
    for uid in sorted(ids):
        s = collab_user(c, uid, t["list_id"]) if uid not in ag else None  # 2.0.0: agents get events (agent_comment_events)
        if not s or not task_visible(c, t["id"], uid, full=True):  # 1.10.0: participants only about their tasks
            continue
        if "comments" not in (s.get("features") or "").split(","):  # 2.0.6: comments off -> no comment News / pushes
            continue
        # 2.62.0 (#1854): an agent's comment with "only replies to me" (also against a list bell "All": the person chose it for
        # agents explicitly; only the task's "Urgent" still wants every comment)
        p61_ok = bl9_agent_comment_ok(s, uid, author, ag, prev, replied, uid in notify_mentions)
        if not asks and not p61_ok and tbl_level(c, uid, t["id"], s) != "urgent":
            continue
        mentioned = uid in notify_mentions or uid == replied
        # 2.1.0 (#317): which event of the notification settings this comment is for uid (first match)
        row = "mention" if mentioned else "comment" if uid in (t["assignee_id"], t["created_by"]) else \
            "reply" if uid == prev else "follow"
        # 2.28.0 (#987): a reply to my comment (the one right before) is marked: it counts as "For you" in the News
        ment = uid in notify_mentions
        news_add(c, uid, "mention" if ment else "comment", task_id=t["id"], comment_id=cid, actor=author, row=row, s=s,
                 data={"reply": 1} if not ment and (uid == prev or uid == replied) else
                 {"reach": 1} if not ment and not p61_ok else None)  # 2.66.1 (#1943): an agent's ask / an "Urgent" task reached me past "only replies"
        lv = tbl_level(c, uid, t["id"], s)  # 2.53.0 C (#1424): the task's bell before the list's
        if lv == "mute":
            continue
        if uid in notify_mentions and notif_ok(c, uid, s, row, "push", t["list_id"]):  # 2.142.0 A (#2146): by e-mail without a push device
            from ..notify.channels import evm_note
            evm_note(c, uid, "mention", t["id"], author, s, cid)
        if lv == "urgent":
            if push_reachable(c, uid, s) and not tbl_sent(uid, t["id"]):
                lg = lang_of(s)
                if lk:
                    out.append((uid, tr("Urgent: {0}", le2e_neutral(lg), lg=lg), tr("{0} commented in {1}", names.get(author, "?"), lname, lg=lg),
                                f"{PUBLIC_URL}/#t/{t['id']}", TBL_PRIO, comment_push_extra(t, lg)))
                    continue
                lg = lang_of(s)
                out.append((uid, tr("Urgent: {0}", t["title"], lg=lg), tr("{0} commented: {1}", names.get(author, "?"), snippet or
                            trn("{0} file", "{0} files", nfiles, lg=lg), lg=lg), f"{PUBLIC_URL}/#t/{t['id']}", TBL_PRIO, comment_push_extra(t, lg)))
            continue
        if not notif_ok(c, uid, s, row, "push", t["list_id"]) or not push_reachable(c, uid, s):
            continue
        # 2.28.0 (#987): an agent's comments push only when wanted; 2.367.2 (#2968): that goes first (it used to leave a "1 more
        # comment" for the summary); an agent's question / approval card goes past agent_push and the burst gate, like a mention
        if not asks and not mentioned and not agent_push_ok(c, uid, s, author) and \
                not (s.get("agent_comments") == "replies" and uid == prev):
            continue  # 2.62.0 (#1854): with "only replies to me" a reply right after my comment pushes like one with reply_to
        if not asks and not burst_gate(c, uid, t["id"], mentioned=mentioned):
            continue
        lg = lang_of(s)
        what = snippet or trn("{0} file", "{0} files", nfiles, lg=lg)
        who = names.get(author, "?")
        if lk:
            msg = tr("{0} mentioned you in {1}", who, lname, lg=lg) if uid in notify_mentions else \
                tr("{0} replied to your message in {1}", who, lname, lg=lg) if uid == replied else tr("{0} commented in {1}", who, lname, lg=lg)
            out.append((uid, le2e_neutral(lg), msg, f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s),
                        {**comment_push_extra(t, lg), **({"ws": "limit"} if asks else {})}))
            continue
        msg = tr("{0} mentioned you: {1}", who, what, lg=lg) if uid in notify_mentions else \
            tr("{0} replied to your message: {1}", who, what, lg=lg) if uid == replied else tr("{0} commented: {1}", who, what, lg=lg)
        if card is not None:  # 2.367.2 (#2968): the card's own words; a question waits for the person like the chat's approval (mark "limit")
            out.append((uid, tr("Approval needed: {0}", card or t["title"], lg=lg), tr("{0} asks in {1}", who, t["title"], lg=lg),
                        f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s), {**comment_push_extra(t, lg), "ws": "limit"}))
            continue
        if asks:
            out.append((uid, t["title"], tr("{0} asks: {1}", who, what, lg=lg), f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s),
                        {**comment_push_extra(t, lg), "ws": "limit"}))
            continue
        out.append((uid, t["title"], msg, f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s), comment_push_extra(t, lg)))
    return out


def cmt_card_title(choices):
    """2.367.2 (#2968): the title of an approval card in a comment's choices ("" = a card without one), None = no card."""
    ch = (json.loads(choices) if isinstance(choices, str) else choices) if choices else None
    ap = ch.get("approval") if isinstance(ch, dict) else None
    return (ap.get("title") or "") if isinstance(ap, dict) else None


def comment_push_extra(t, lg):
    """2.0.8 (#331): comment / mention pushes get the buttons Reply (opens the task with the comment box focused) and
    Done (completes it in the background, like the reminder's). An open task only; a completed one gets Reply alone."""
    acts = [(tr("Reply", lg=lg), f"{PUBLIC_URL}/#reply/{t['id']}")]
    if not t["status"] and not t["deleted_at"]:
        acts.append((tr("Done|action", lg=lg), f"{PUBLIC_URL}/#done/{t['id']}"))
    return {"actions": acts, "task": t["id"], "kind": "comment"}  # 2.142.0 A (#2145): kind = the notification channels' event


def push_day(due, due_time, lg):
    day = tr("today", lg=lg) if due == local_now().date().isoformat() else \
        short_day(date.fromisoformat(due), lg)
    return day + (" " + due_time if due_time else "")


def task_event(c, tid, kind, prev_assignee=None, skip=None):
    """assign / unassign / complete pushes; queued in g.pushes and sent once the request succeeded.
    2.367.2 (#2968): skip = a person who hears of this through an event of its own."""
    from ..collab.news import agent_push_ok, bell_all_users, KIND_ROW, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_assign_event, agent_ids
    actor = me()
    t = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                     WHERE t.id=?""", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        return
    if kind == "assign":
        rcpt = {t["assignee_id"]}
        agent_assign_event(c, tid, "assigned", t["assignee_id"])
    elif kind == "unassign":
        rcpt = {prev_assignee}
        agent_assign_event(c, tid, "unassigned", prev_assignee)
    else:  # complete: only in shared lists (in a private list the creator is the one completing), or via a public link
        if actor and not c.execute("SELECT 1 FROM list_members WHERE list_id=?", (t["list_id"],)).fetchone():
            return
        rcpt = {t["created_by"], t["assigned_by"]} | bell_all_users(c, t["list_id"], "complete")  # 2.1.0: bell "All" (2.6.1: "custom")
    from ..notify.taskbell import tbl_level, tbl_urgent_users
    if kind == "complete":
        rcpt |= tbl_urgent_users(c, tid)  # 2.53.0 C (#1424): "Urgent" on the task (the push itself: tbl_note of the history line)
    rcpt.discard(None)
    rcpt.discard(actor)
    rcpt.discard(skip)
    rcpt -= agent_ids(c)  # 2.0.0: agents get events (agent_assign_event), no pushes / News
    name = user_names(c, [actor]).get(actor, "?")
    for uid in sorted(rcpt):
        s = collab_user(c, uid, t["list_id"])
        if not s:
            continue
        if not task_visible(c, tid, uid, full=True):  # 2.36.2 (#1142): also for "unassign"
            if kind == "unassign":  # 2.38.0 (#1155): out of sight -> a note with the list name only, no task content
                fx2_unassign_hidden(c, uid, t, actor, name, s)
            continue
        news_add(c, uid, kind, task_id=tid, actor=actor, s=s)
        if tbl_level(c, uid, tid, s, done_ok=kind == "complete"):  # 2.53.0 C (#1424): muted / urgent (pushed by tbl_note)
            continue
        if kind == "assign" and notif_ok(c, uid, s, KIND_ROW[kind], "push", t["list_id"]):  # 2.142.0 A (#2146): by e-mail
            from ..notify.channels import evm_note
            evm_note(c, uid, "assign", tid, actor, s)
        if not notif_ok(c, uid, s, KIND_ROW[kind], "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not burst_gate(c, uid, tid, event=True, kind=kind):
            continue
        if kind == "complete" and not agent_push_ok(c, uid, s, actor):  # 2.28.0 (#987)
            continue
        lg = lang_of(s)
        who = name if actor else tr("Someone via the public link", lg=lg)
        lname = tr("Basket", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
        if kind == "assign":
            title = tr("{0} assigned you: {1}", who, t["title"], lg=lg)
            msg = lname + (" · " + tr("due {0}", push_day(t["due"], t["due_time"], lg), lg=lg) if t["due"] else "")
        elif kind == "unassign":
            title, msg = tr("{0} unassigned you from: {1}", who, t["title"], lg=lg), lname
        else:
            title, msg = tr("{0} completed: {1}", who, t["title"], lg=lg), lname
        g.pushes.append((uid, title, msg, f"{PUBLIC_URL}/#t/{tid}", push_prio(s), {"kind": "other" if kind == "complete" else "assign"}))


def fx2_unassign_hidden(c, uid, t, actor, name, s):
    """2.38.0 (#1155): someone who no longer sees the task after losing it (a participant) still learns about it: a News
    entry about the list (no task id, no title) and the push of the "Assignments" row with the list name only."""
    from ..collab.news import KIND_ROW, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    news_add(c, uid, "unassign", list_id=t["list_id"], actor=actor, s=s, data={"hidden": 1})
    if not notif_ok(c, uid, s, KIND_ROW["unassign"], "push", t["list_id"]) or not push_reachable(c, uid, s) or \
            not burst_gate(c, uid, t["id"], event=True):
        return
    lg = lang_of(s)
    who = name if actor else tr("Someone via the public link", lg=lg)
    lname = tr("Basket", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
    g.pushes.append((uid, tr("{0} removed you as assignee of a task in {1}", who, lname, lg=lg), lname,
                     f"{PUBLIC_URL}/#l/{t['list_id']}", push_prio(s), {"kind": "assign"}))


def assignment_events(c, tid, old_assignee, new_assignee):
    if old_assignee == new_assignee:
        return
    if new_assignee:
        task_event(c, tid, "assign")
    if old_assignee:
        task_event(c, tid, "unassign", prev_assignee=old_assignee)


def send_pushes(pushes):
    if pushes and has_request_context():
        pushes = push_filtered(pushes)
    if pushes:
        # (uid, title, msg, click, prio[, extra]): extra = notify() keywords (2.0.8: actions + task of comment pushes)
        # 2.142.0 A (#2145): kind "other" for the notification channels unless the push names its own
        push_later([(x[0], x[1], x[2], {"prio": x[4], "click": x[3], "kind": "other", **(x[5] if len(x) > 5 else {})})
                    for x in pushes])  # 2.370.2 (#2779): through the maintenance gate; 2.370.3 (#2760): a queue row


PUSH_SKIP_KW = ("s", "ws")  # 2.370.3 (#2760): no settings snapshot in the row (notify reads them), "ws" is no notify keyword


def push_later(calls):
    """2.370.3 (#2760): the pushes after a request as ONE row of the queue (bgjobs "push:send": the worker sends them, through
    the maintenance gate) instead of a thread of the web process. calls = [(uid, title, msg, notify keywords)]."""
    calls = [[int(u), t, m, {k: v for k, v in (kw or {}).items() if k not in PUSH_SKIP_KW}] for u, t, m, kw in calls or ()]
    if calls:
        bgj_add("push:send", calls)


@bgj_fn("push:send", tries=1)  # a push is never sent twice: a lost run is failed, not repeated
def push_rows(calls):
    from ..notify.push import notify
    for uid, title, msg, kw in calls:
        try:
            notify(uid, title, msg, **kw)
        except Exception as e:  # noqa: BLE001 -- one push that fails never holds the others back
            print("push failed:", type(e).__name__, flush=True)


PUSH_BURST_SKIP = []  # 2.236.0 (#2909): f(c, uid) -> True = no push and no burst count (agents/workstyle.py ws_burst_skip)
PUSH_FILTERS = []  # 2.236.0 B (#2909): f(c, actor, pushes) -> the pushes that may go out (registered by agents/workstyle.py)


def push_filtered(p):
    """2.236.0 B (#2909, #2905): the pushes of a request (sent after its commit) through PUSH_FILTERS: an agent's pushes
    follow its work style (push mode, quiet window; agents/workstyle.py)."""
    try:
        for f in PUSH_FILTERS:
            p = f(db(), g.get("user"), p)
        return p
    except Exception as e:  # noqa: BLE001
        print("agent push filter failed:", type(e).__name__, str(e)[:200], flush=True)
        return [(*x[:5], {k: v for k, v in x[5].items() if k != "ws"}) if len(x) > 5 and isinstance(x[5], dict) else x for x in p]


@app.after_request
def send_queued_pushes(resp):
    p = g.pop("pushes", None) if has_request_context() else None
    if p and resp.status_code < 400:
        send_pushes(p)
    return resp


def task_push_tick(c, users, S, LG):
    """Watchdog: one summary push for everything collected during the burst window."""
    from ..notify.push import _wd_fail
    now = time.time()
    rows = c.execute("""SELECT p.*, t.title, t.list_id, t.deleted_at FROM task_push p JOIN tasks t ON t.id=p.task_id
                        WHERE (p.pending>0 OR p.events>0 OR p.mentioned>0) AND p.sent_at<=?""", (now - TASK_PUSH_GAP,)).fetchall()
    for p in rows:
        try:
            _push_tick_one(c, p, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "collab push", (p["user_id"], p["task_id"]), e)
    c.execute("DELETE FROM task_push WHERE pending=0 AND events=0 AND mentioned=0 AND sent_at<?", (now - 86400,))
    c.commit()


def _push_tick_one(c, p, users, S, LG, now):
    from ..notify.push import notify, push_prio
    c.execute("UPDATE task_push SET sent_at=?, pending=0, events=0, mentioned=0 WHERE user_id=? AND task_id=?",
              (now, p["user_id"], p["task_id"]))
    c.commit()
    uid = p["user_id"]
    if uid not in users or p["deleted_at"] or not collab_on(S[uid]) or not task_visible(c, p["task_id"], uid, full=True):
        return
    from ..notify.taskbell import tbl_level
    if tbl_level(c, uid, p["task_id"], S[uid]) == "mute":  # 2.53.0 C (#1424): muted since
        return
    lg = LG[uid]
    parts = ([trn("{0} more comment", "{0} more comments", p["pending"], lg=lg)] if p["pending"] else []) + \
        ([trn("{0} more change", "{0} more changes", p["events"], lg=lg)] if p["events"] else []) + \
        ([tr("you were mentioned", lg=lg)] if p["mentioned"] else [])
    ex = {}
    if p["pending"] or p["mentioned"]:  # 2.0.8: the summary of a comment burst gets Reply / Done too
        t = c.execute("SELECT id, status, deleted_at FROM tasks WHERE id=?", (p["task_id"],)).fetchone()
        ex = comment_push_extra(t, lg) if t else {}
    ex.setdefault("kind", "comment" if p["pending"] or p["mentioned"] else "other")  # 2.142.0 A (#2145)
    notify(uid, p["title"], " · ".join(parts), push_prio(S[uid]), f"{PUBLIC_URL}/#t/{p['task_id']}", s=S[uid], **ex)
