"""2.137.0 (#2344): organisation import -- the tables of this area (admin/orgimport.py OiT). Filled by the area's part.

2.137.0 C (#2344): the team areas -- chat channels of the lists, absences, bookings, vacation accounts, filed e-mails,
newsletter, customer reports, forms, playbooks, project notes, notepads, rules, histories, time entries, notes encrypted
in the browser, people on tasks, comment reactions, calendar / address book shares and the harmless settings of the
organisation (only into an empty organisation).
Rows of a person (absences, vacation accounts, time entries, notes encrypted in the browser ...) only for people ticked in
the preview (others: left out with a warning); into the private space only the importing person's own rows (private stays
private). Browser ciphertexts (chat messages of locked channels, encrypted / locked notes) are taken over as they are.
Secrets never come with an export: forms and customer reports get new links, a newsletter connection must be connected again."""
import json
import os
import secrets

from ..core.i18n import N_
from .orgimport import OiFix, OiT, _oid, _txt, tr  # noqa: F401
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from ..core.db import iso, now_utc  # 2.278.0 B (#3094)
from .acctimport import umz_billed  # 2.278.0 B (#3094)
from ..accounts.login import seal  # 2.380 H (#2398)
from ..accounts.session import _token_hash  # 2.380 H (#2398)
from .orgexport import _safe_part  # 2.380 H (#2398)

# the person columns of the rows of one person (the row is left out when the person does not map)
_W_PEOPLE = N_("Entries of people who were not chosen were not taken over: {0}")


def _who(ctx, v, own=False):
    """The new account of person v (ticked in the preview, or the importing person); own: into the private space only the
    importing person (rows that belong to one person stay theirs)."""
    if v is None:
        return None
    n = ctx.who(v)
    if n and own and not ctx.run.org and n != ctx.uid:
        return None
    return n


_W_OTHERS = N_("Entries that belong to other people were not taken over: {0}")


def _person(col, own=True, member=False):
    """prep part: the row belongs to the person in col -- left out (with a warning) when that person does not map.
    2.237.0 D (#2870): only the importing person, unless member (rows an admin of the area enters for others in the app too)."""
    def fn(c, run, src, d, ctx):
        n = _who(ctx, src.get(col), own)
        if n and n != ctx.uid and not member:
            run.warning(_W_OTHERS, tr(ctx.spec.label) if ctx.spec.label else ctx.spec.path)
            return False
        if not n:
            run.warning(_W_PEOPLE, tr(ctx.spec.label) if ctx.spec.label else ctx.spec.path)
            return False
        d[col] = n
        return d
    return fn


def _time_person(c, run, src, d, ctx):
    """2.237.0 D (#2870): a time entry of another ticked person goes to the importing person, the name in front of the note."""
    n = _who(ctx, src.get("user_id"), True)
    if n and n != ctx.uid:
        name = next((_txt(p.get("name"), 100) for p in ctx.data.get("people") or []
                     if isinstance(p, dict) and _oid(p.get("user_id")) == _oid(src.get("user_id"))), "") or tr("Unknown")
        d["note"] = f"{name}: {_txt(src.get('note'), 500)}".strip().rstrip(":")[:600]
        d["user_id"] = ctx.uid
        return d
    return _person("user_id")(c, run, src, d, ctx)


def _chain(*fns):
    def fn(c, run, src, d, ctx):
        for f in fns:
            d = f(c, run, src, d, ctx)
            if not d:
                return d
        return d
    return fn


# ---------------------------------------------------------------- chat
def _room(c, run, src, d, ctx):
    """A list's channel: one per list (the app makes it on first use; a channel already there is used)."""
    lid = d.get("list_id")
    r = c.execute("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()
    if r:
        run.put("tchat_rooms", src.get("id"), r[0])
        return False
    d["kind"] = "list"
    return d


def _msg(c, run, src, d, ctx):
    if _txt(src.get("enc"), 10):
        run.warning(N_("Chat messages encrypted in the browser were taken over as they are: they open with the keys of their channel."))
    return d


# ---------------------------------------------------------------- absences, bookings, e-mails
def _booking(c, run, src, d, ctx):
    kind, rid = _txt(src.get("resource_kind"), 20), src.get("resource_id")
    if kind == "user":
        new = _who(ctx, rid, own=True)
    else:
        new = run.m({"contact": "contacts", "equipment": "office_equipment", "set": "office_sets"}.get(kind, ""), rid)
    if not new:
        run.warning(N_("A booking of a resource that was not taken over was left out: {0}"), _txt(src.get("res_label"), 80))
        return False
    d["resource_id"] = new
    return d


def _mail(c, run, src, d, ctx):
    """A filed e-mail: the owner (the importing person); one without client and project was the owner's
    alone and only comes with them. The workspace and the filed files follow the target."""
    from ..docs.store import doc_ws
    own = _who(ctx, src.get("owner_id"), own=True)
    other = bool(own and own != ctx.uid)
    own = None if other else own  # 2.237.0 D (#2870): the owner only the importing person
    if not own and not (d.get("client_id") or d.get("list_id")):
        run.warning(_W_OTHERS if other else _W_PEOPLE, tr(ctx.spec.label))
        return False
    d["owner_id"] = own or ctx.uid
    d["message_id"] = _txt(src.get("message_id"), 1000) or f"<{secrets.token_hex(12)}@import.invalid>"
    d["org_id"] = run.org
    d["ws"] = doc_ws(run.org, d["owner_id"])
    try:
        files = json.loads(src.get("files") or "[]") if isinstance(src.get("files"), str) else (src.get("files") or [])
    except ValueError:
        files = []
    d["files"] = json.dumps([n for n in (run.m("fs_nodes", x) for x in files if isinstance(x, int)) if n])
    return d


def _mail_index(c, run, src, nid, ctx):
    """The keyed word index of the search (never in the archive: rebuilt like on filing)."""
    from ..hub.hubmail import _index
    r = c.execute("SELECT ws FROM hub_mails WHERE id=?", (nid,)).fetchone()
    if r:
        _index(c, nid, r[0], {k: _txt(src.get(k), 100000) for k in ("subject", "from_name", "from_addr", "body")})


# ---------------------------------------------------------------- newsletter
def _nl_conn(c, run, src, d, ctx):
    """The connection without its access data (never exported): to be connected again, no automatic sync until then."""
    from ..docs.store import doc_ws
    d["owner_id"] = None if run.org else ctx.uid
    d["ws"] = doc_ws(run.org, ctx.uid)
    d.update(secret="", hint="", auto=0, error=tr("The access data does not come with an export: connect the newsletter service again."))
    run.warning(N_("Newsletter connection taken over without its access data: connect it again."))
    return d


def _poll(c, run, src, d, ctx):
    """2.380 H (#2398): a poll gets its link after the insert (_poll_link: sealed with the new id); a unique stand-in till then."""
    d.update(token="", token_hash="import:" + secrets.token_hex(16))
    return d


def _poll_link(c, run, src, nid, ctx):
    """2.380 H (#2398): the new link of an imported poll (the old one stays dead); the report says so."""
    tok = secrets.token_urlsafe(18)  # the shape of calendars/polls.py
    c.execute("UPDATE sched_polls SET token=?, token_hash=? WHERE id=?", (seal(c, f"poll:{nid}", tok), _token_hash(tok), nid))
    run.warning(N_("Scheduling polls got new links: the old links no longer work."))


def _vote(c, run, src, d, ctx):
    """2.380 H (#2398): the answers name the options by their new ids (an option that did not come along is left out); the
    voter's own edit link stays dead with the old poll link, the address hash of the old server means nothing here."""
    try:
        a = json.loads(src.get("answers") or "{}")
    except (TypeError, ValueError):
        a = {}
    m = {str(run.m("sched_poll_options", k)): v for k, v in (a.items() if isinstance(a, dict) else ()) if run.m("sched_poll_options", k)}
    d.update(answers=json.dumps(m), ip_hash="", edit_hash=_txt(src.get("edit_hash"), 100) or _token_hash(secrets.token_urlsafe(18)))
    return d


def _bookmark(c, run, src, d, ctx):
    """2.380 H (#2398): a bookmark with its picture (sealed for the target space like bookmarks.bm_store_image)."""
    img = str(src.get("image") or "")
    d["image"] = ""
    if img:
        got = ctx.file(f"files/bookmarks/{_oid(src.get('id')) or 0}-{_safe_part(os.path.basename(img))}", "bookmarks",
                       os.path.basename(img), mime=str(src.get("image_mime") or ""))
        if got:
            d["image"] = got[0]
    return d


def _mbx(c, run, src, d, ctx):
    """2.144.5 B (#2410): the workspace mailbox without its passwords (hub/mailbox.py mbx_take_values); a workspace that has a
    mailbox keeps its own."""
    from ..docs.store import doc_ws
    from ..hub.mailbox import mbx_take_values
    d["owner_id"] = None if run.org else ctx.uid
    d["ws"] = doc_ws(run.org, ctx.uid)
    if c.execute("SELECT 1 FROM hub_mailboxes WHERE ws=?", (d["ws"],)).fetchone():
        run.warning(N_("The workspace already has a mailbox: the one of the export was not taken over."))
        return False
    v = mbx_take_values(src)
    if not v:
        return False
    d.update(v)
    run.warning(N_("Mailbox taken over without its passwords and switched off: enter them in the settings and switch it on."))
    return d


def _nl_seg(c, run, src, d, ctx):
    try:
        rule = json.loads(src.get("rule") or "{}") if isinstance(src.get("rule"), str) else (src.get("rule") or {})
    except ValueError:
        rule = {}
    if isinstance(rule, dict) and isinstance(rule.get("books"), list):
        rule["books"] = sorted({n for n in (run.m("books", b) for b in rule["books"]) if n})
    d["remote_id"] = _txt(src.get("remote_id"), 300)  # the list at the newsletter service (umz_row leaves *_id out)
    d["rule"] = json.dumps(rule if isinstance(rule, dict) else {}, ensure_ascii=False)
    return d


# ---------------------------------------------------------------- forms, customer reports
def _form(c, run, src, d, ctx):
    """A form gets a new link (the old token never comes with an export)."""
    from ..accounts.login import seal
    from ..accounts.session import _token_hash
    tok = secrets.token_urlsafe(24)
    d.update(token=seal(c, f"form:{d['list_id']}", tok), token_hash=_token_hash(tok))
    return d


def _ticket(c, run, src, d, ctx):
    """A customer report: the address sealed again with this server's key, a new status link (the old one is not exported)."""
    from ..accounts.login import seal
    from ..accounts.session import _token_hash
    from ..team.portal import pt_email_hash, pt_email_norm
    e = pt_email_norm(src.get("email"))
    tok = secrets.token_urlsafe(24)
    d.update(owner_id=None if run.org else ctx.uid, email=seal(c, "portal-email", e) if e else "", email_hash=pt_email_hash(c, e) if e else "",
             token=seal(c, "portal-token", tok), token_hash=_token_hash(tok), notify=d.get("notify", 1) if e else 0)
    run.warning(N_("Customer reports got new status links: the old links no longer open."))
    return d


# ---------------------------------------------------------------- rules, histories
def _rule(c, run, src, d, ctx):
    """Trigger and action point at columns, tags, people and lists of the list: mapped; what does not map pauses the rule
    (the settings name why), like the app does when a column / person goes."""
    pause = ""
    tv = _txt(src.get("trig_val"), 40)
    if d.get("trig") in ("section", "ltag") and tv:
        new = run.m("sections" if d["trig"] == "section" else "list_tags", tv)
        d["trig_val"] = str(new) if new else ""
        pause = pause or ("" if new else "section")
    try:
        a = json.loads(src.get("act_val") or "{}") if isinstance(src.get("act_val"), str) else (src.get("act_val") or {})
    except ValueError:
        a = {}
    a = a if isinstance(a, dict) else {}
    if d.get("act") == "assign":
        a["user_id"] = _who(ctx, a.get("user_id"))
        pause = pause or ("" if a["user_id"] else "assignee")
    elif d.get("act") == "move":
        if a.get("list_id") is not None:
            a["list_id"] = run.m("lists", a.get("list_id"))
            pause = pause or ("" if a["list_id"] else "target")
        if a.get("section_id") is not None:
            a["section_id"] = run.m("sections", a.get("section_id"))
            pause = pause or ("" if a["section_id"] else "section")
    d["act_val"] = json.dumps(a, separators=(",", ":"))
    if pause:
        d.update(active=0, paused_reason=pause)
    return d


# 2.137.1 (#2399): ids inside the history data (activity / list_activity .data) -> the target's ids; an id that did not come
# along (or a key not known here ending in _id) is dropped, never left pointing at a row of this server
_ACT_IDS = {"list_id": "lists", "section_id": "sections", "task_id": "tasks", "parent_id": "tasks", "milestone_id": "tasks",
            "comment": "comments", "sheet": "sheets", "signoff": "office_signoffs"}
_ACT_KIND_IDS = {"field": {"id": "list_fields"}, "subtask": {"id": "tasks"}, "milestone": {"id": "tasks"}, "dep_add": {"id": "tasks"},
                 "dep_rm": {"id": "tasks"}, "blocks_add": {"id": "tasks"}, "blocks_rm": {"id": "tasks"}, "unblocked": {"id": "tasks"}}
_ACT_PEOPLE = ("user_id", "assignee_id", "agent_id", "agent", "approver", "reviewer", "by")  # by: tidy (comments.py names it)
_ACT_DROP = ("hook",)  # the inbound webhook of the old server (log_act "via": "webhook")
_ACT_KIND_PEOPLE = {"assign": ("to", "from"), "owner": ("from", "to")}


def _act_data(run, who, kind, v):
    v = dict(v)
    ids = {**_ACT_IDS, **_ACT_KIND_IDS.get(kind, {})}
    people = (*_ACT_PEOPLE, *_ACT_KIND_PEOPLE.get(kind, ()))
    for k in list(v):
        if k in people:
            if _oid(v[k]) is None:  # a name (agentjoin), empty, or not an id
                continue
            new = who(v[k])
        elif k in ids:
            if _oid(v[k]) is None:
                continue
            new = run.m(ids[k], v[k])
        elif (k.endswith("_id") or k in _ACT_DROP) and _oid(v[k]) is not None:
            new = None
        else:
            continue
        if new:
            v[k] = new
        elif kind == "assign" and k == "to":
            v[k] = -1  # still "assigned to" (the history shows "Deleted user"), not "removed the assignee"
        else:
            del v[k]
    return v


def _activity(c, run, src, d, ctx):
    v = src.get("data")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = {}
    v = _act_data(run, ctx.who, str(src.get("kind") or ""), v) if isinstance(v, dict) else {}
    d["data"] = json.dumps(v, ensure_ascii=False)
    return d


# ---------------------------------------------------------------- time, notes, shares
def _time(c, run, src, d, ctx):
    if not src.get("end"):  # a running timer stays where it runs
        return False
    return d


def _billed(c, run, src, d, ctx):
    """2.278.0 B (#3094): a billed entry stays on its invoice (refs: the new document) or, without it, not billable."""
    return umz_billed(run, src, d, iso(now_utc()))


def _not_me(c, run, src, d, ctx):
    """A share with a person, never with the owner of the calendar / address book (the importing person)."""
    if d.get("user_id") == ctx.uid:
        return False
    if d.get("role") not in ("view", "edit"):  # events/model.py EV_ROLES, contacts/model.py BOOK_ROLES
        d["role"] = "view"
    return d


# ---------------------------------------------------------------- the organisation's own settings
_ORG_KEEP = ("color", "hub_holiday_state", "hub_leave_approval")  # harmless: nothing about sign-in, security, joining or privacy


def _org(c, run, src, d, ctx):
    """Only into an empty organisation (no lists but the imported ones) and only harmless settings; never a row."""
    from ..accounts.orgs import is_org_admin
    from ..hub.absence import ABS_STATES
    from ..lists.lists import LIST_COLOR_RE
    if not run.org or not is_org_admin(c, ctx.uid, run.org):
        return False
    n = c.execute("SELECT COUNT(*) FROM lists WHERE org_id=?", (run.org,)).fetchone()[0]
    if n > len([x for x in run.created.get("lists") or [] if run.list_org.get(x) == run.org]):
        return False
    sets = {}
    if isinstance(src.get("color"), str) and (src["color"] == "" or LIST_COLOR_RE.fullmatch(src["color"])):
        sets["color"] = src["color"]
    if src.get("hub_holiday_state") in ("", *ABS_STATES):
        sets["hub_holiday_state"] = src["hub_holiday_state"]
    if src.get("hub_leave_approval") in (0, 1):
        sets["hub_leave_approval"] = src["hub_leave_approval"]
    sets = {k: v for k, v in sets.items() if k in _ORG_KEEP}
    if sets:
        with system_ctx(c):  # the organisation's own row (orgs is structure); the admin right is checked above
            c.execute(f"UPDATE orgs SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), run.org))
        run.count("org_settings")
    return False


# required columns the archive never has (secrets, *_id): placeholders umz_row keeps, prep sets the real value
_NEW_TOKEN = {"token": "", "token_hash": ""}

SPECS = [
    OiT("organisation.json", "orgs", space=(), rid=False, enc=False, prep=_org),
    # lists
    OiT("lists/notes.json", "notes", refs={"list_id": "lists"}, need=("list_id",), people={"created_by": "null", "updated_by": "null"},
        space=(), label=N_("Project notes")),
    OiT("lists/notepads.json", "list_notepads", refs={"list_id": "lists"}, need=("list_id",),
        people={"created_by": "null", "updated_by": "null"}, space=(), label=N_("Notepads")),
    OiT("lists/forms.json", "forms", refs={"list_id": "lists", "section_id": "sections"}, need=("list_id",), people={"created_by": "null"},
        space=(), fixed=_NEW_TOKEN, label=N_("Forms"), prep=_form),
    OiT("lists/form_entries.json", "form_entries", refs={"task_id": "tasks", "form_id": "forms", "client_id": "clients"},
        need=("task_id", "form_id"), space=(), rid=False, label=N_("Forms")),
    OiT("lists/playbooks.json", "playbooks", refs={"list_id": "lists"}, need=("list_id",), people={"author_id": "null"}, space=(),
        label=N_("Playbooks")),
    OiT("lists/sprints.json", "sprints", refs={"list_id": "lists"}, need=("list_id",), people={"created_by": "null"}, space=(),
        label=N_("Sprints")),
    OiT("lists/rules.json", "list_rules", refs={"list_id": "lists", "target_list_id": "lists"}, need=("list_id",),
        people={"created_by": "null"}, label=N_("Rules"), prep=_rule),
    OiT("lists/history.json", "list_activity", refs={"list_id": "lists"}, need=("list_id",), people={"user_id": "null"}, space=(),
        label=N_("History"), prep=_activity),
    OiT("lists/admin_log.json", "org_list_log", refs={"list_id": "lists"},
        people={"by_id": "null", "owner_id": "null", "to_id": "null"}, private=False, label=N_("History")),
    OiT("portal/tickets.json", "portal_tickets", refs={"task_id": "tasks", "list_id": "lists", "form_id": "forms", "client_id": "clients"},
        need=("task_id", "list_id"), fixed=_NEW_TOKEN, label=N_("Customer reports"), prep=_ticket),
    # tasks
    OiT("tasks/people.json", "task_people", refs={"task_id": "tasks"}, need=("task_id",), people={"user_id": "member"}, space=(), rid=False,
        label=N_("People")),
    OiT("tasks/links.json", "task_links", refs={"task_id": "tasks", "list_id": "lists", "section_id": "sections"},
        need=("task_id", "list_id"), people={"added_by": "null"}, rid=False, label=N_("Tasks")),
    OiT("tasks/history.json", "activity", refs={"task_id": "tasks"}, need=("task_id",), people={"user_id": "null"}, space=(),
        label=N_("History"), prep=_activity),
    OiT("tasks/encrypted_notes.json", "task_enc_notes", refs={"task_id": "tasks"}, need=("task_id",), space=(), rid=False, enc=False,
        people={"user_id": "null"}, label=N_("Encrypted notes"), prep=_person("user_id")),
    OiT("tasks/locked_notes.json", "task_note_locks", refs={"task_id": "tasks"}, need=("task_id",), space=(), rid=False, enc=False,
        people={"user_id": "null"}, label=N_("Encrypted notes"), prep=_person("user_id")),
    # 2.278.0 B (#3094): billed_doc_id -> the new invoice (office_docs come first, oi_office); billed_at kept
    OiT("time_entries.json", "time_entries", refs={"task_id": "tasks", "list_id": "lists", "billed_doc_id": "office_docs"}, people={"user_id": "null"},
        space=(), label=N_("Time entries"), prep=_chain(_time, _time_person, _billed)),
    OiT("time_sheets.json", "time_sheets", people={"user_id": "null", "decided_by": "null"}, label=N_("Time entries"),
        prep=_person("user_id")),
    OiT("comments/reactions.json", "comment_reactions", refs={"comment_id": "comments"}, need=("comment_id",),
        people={"user_id": "need"}, space=(), rid=False, label=N_("Reactions")),
    # chat
    OiT("chat/channels.json", "tchat_rooms", refs={"list_id": "lists"}, need=("list_id",), space=(), prep=_room),
    # 2.278.0 B (#3094): thread_of (the thread's first message) mapped like reply_to, never the old id
    OiT("chat/messages.json", "tchat_msgs", refs={"room_id": "tchat_rooms", "task_id": "tasks"}, need=("room_id",),
        people={"user_id": "null", "pinned_by": "null"}, late={"reply_to": "tchat_msgs", "thread_of": "tchat_msgs"}, space=(), enc=False, label=N_("Team chat"),
        prep=_msg),
    OiT("chat/reactions.json", "tchat_rx", refs={"message_id": "tchat_msgs"}, need=("message_id",), people={"user_id": "need"},
        space=(), rid=False, label=N_("Team chat")),
    # shares of calendars and address books (only with ticked people)
    OiT("calendars/members.json", "ev_cal_members", refs={"cal_id": "ev_cals"}, need=("cal_id",), people={"user_id": "member"}, space=(),
        rid=False, prep=_not_me),
    OiT("books/members.json", "book_members", refs={"book_id": "books"}, need=("book_id",), people={"user_id": "member"}, space=(),
        rid=False, prep=_not_me),
    # newsletter
    OiT("newsletter/connection.json", "nl_conns", people={"created_by": "null"}, label=N_("Newsletter"), prep=_nl_conn),
    OiT("newsletter/segments.json", "nl_segments", refs={"conn_id": "nl_conns"}, need=("conn_id",), label=N_("Newsletter"), prep=_nl_seg),
    OiT("newsletter/members.json", "nl_members", refs={"seg_id": "nl_segments"}, need=("seg_id",), rid=False, label=N_("Newsletter")),
    OiT("newsletter/runs.json", "nl_runs", refs={"conn_id": "nl_conns"}, need=("conn_id",), people={"by_id": "null"}, label=N_("Newsletter")),
    # absences, bookings, vacation accounts, filed e-mails
    OiT("hub/absences.json", "hub_absences", people={"user_id": "null", "created_by": "null", "decided_by": "null"}, private="office",
        label=N_("Absences and bookings"), prep=_person("user_id", member=True)),
    OiT("hub/bookings.json", "hub_bookings", refs={"list_id": "lists", "event_id": "events"}, people={"created_by": "null"},
        fixed={"resource_id": 0}, private="office", label=N_("Absences and bookings"), prep=_booking),
    OiT("hub/leave_quota.json", "hub_leave_quota", people={"user_id": "null", "updated_by": "null"}, private="office", label=N_("Absences and bookings"),
        prep=_person("user_id", member=True)),
    OiT("hub/mails.json", "hub_mails", refs={"client_id": "clients", "list_id": "lists", "eml_id": "fs_nodes", "folder_id": "fs_nodes"},
        people={"deleted_by": "null"}, fixed={"message_id": ""}, label=N_("Absences and bookings"), prep=_mail, after=_mail_index),
    # 2.144.5 B (#2410): the workspace mailbox (into the private space: the importing person's own)
    OiT("hub/mailbox.json", "hub_mailboxes", people={"created_by": "null"}, label=N_("Mailbox"), prep=_mbx),
    # 2.380 H (#2398): scheduling polls with their options and votes (a new link), bookmarks with their pictures
    OiT("polls.json", "sched_polls", refs={"event_id": "events", "task_id": "tasks", "client_id": "clients", "list_id": "lists"},
        late={"chosen_id": "sched_poll_options"}, people={"user_id": "me"}, fixed=_NEW_TOKEN, label=N_("Scheduling polls"), prep=_poll,
        after=_poll_link),
    OiT("polls/options.json", "sched_poll_options", refs={"poll_id": "sched_polls"}, need=("poll_id",), space=(), label=N_("Scheduling polls")),
    OiT("polls/votes.json", "sched_poll_votes", refs={"poll_id": "sched_polls"}, need=("poll_id",), space=(), label=N_("Scheduling polls"),
        prep=_vote),
    OiT("bookmarks.json", "bookmarks", people={"user_id": "me"}, label=N_("Bookmarks"), prep=_bookmark),
]
FIXES = [OiFix("tasks", "tasks", "sprint_id", "sprints")]  # the sprint of a task
