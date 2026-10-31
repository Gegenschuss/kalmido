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
import re
import secrets

from ..core.i18n import N_
from .orgimport import OiFix, OiT, _oid, _txt, tr  # noqa: F401
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from ..core.db import iso, now_utc  # 2.278.0 B (#3094)
from .acctimport import umz_billed  # 2.278.0 B (#3094)
from ..accounts.login import seal  # 2.380 H (#2398)
from ..accounts.session import _token_hash  # 2.380 H (#2398)
from .orgexport import _safe_part  # 2.380 H (#2398)
from .acctimport import umz_legacy_aad  # 2.362.0 (#3090)
from ..life.rss import _norm, RSS_MAX_FEEDS  # 2.455.0 (#3469)
from ..lists.rules import RUL_ACTIONS, RUL_DAYS_MAX, RUL_LIST_MAX, RUL_NAME_MAX, RUL_PRIO, RUL_TEXT_MAX, RUL_TRIGGERS  # 2.455.0 (#3469)
from .acctimport import umz_mentions  # 2.362.4 (#3100)

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


def _legacy(prefix):
    """2.362.0 (#3090): prep part of a browser ciphertext bound to the old task / person ids: their AAD as legacy_aad, so its
    author opens it again on this server (sealed anew on the next save)."""
    def fn(c, run, src, d, ctx):
        d["legacy_aad"] = umz_legacy_aad(prefix, None, src.get("task_id"), src.get("user_id"))
        return d
    return fn


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
    """A list's channel: one per list (the app makes it on first use; a channel already there is used). 2.362.0 (#3092): a
    channel of the organisation becomes one of the target (into the private space: one of the own space, invited only), the
    importing person its first member; no other kind comes with an export."""
    if src.get("kind") == "channel":
        d.update(kind="channel", list_id=None, org_id=run.org, is_open=1 if run.org and src.get("is_open") else 0,
                 name=_txt(src.get("name"), 80).strip() or tr("Channel"), created_by=ctx.uid)
        return d
    lid = d.get("list_id")
    if src.get("kind") != "list" or not lid:
        if src.get("kind") == "list":
            run.warning(N_("Not taken over because the entry it belongs to is missing: {0}"), tr("Team chat"))
        return False
    r = c.execute("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,)).fetchone()
    if r:
        run.put("tchat_rooms", src.get("id"), r[0])
        return False
    d["kind"] = "list"
    return d


def _room_after(c, run, src, nid, ctx):
    """2.362.0 (#3092): the importing person is the first member of an imported channel (it would be invisible to them)."""
    if src.get("kind") == "channel":
        c.execute("INSERT INTO tchat_members(room_id,user_id,added_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                  (nid, ctx.uid, ctx.uid, iso(now_utc())))


def _room_member(c, run, src, d, ctx):
    """2.362.0 (#3092): a member of a channel (the importing person is one already: _room_after)."""
    return False if d.get("user_id") == ctx.uid else d


def _chat_file(c, run, src, d, ctx):
    """2.362.0 (#3092): a file / voice message of a team chat message, sealed with the key of its conversation's space (the
    target: collab/teamchan.py tcx_space), a list channel's file row without organisation like in the app."""
    import os
    from .orgexport import _safe_part
    rk = c.execute("SELECT kind FROM tchat_rooms WHERE id=?", (d["room_id"],)).fetchone()
    name = str(src.get("name") or "file")
    got = ctx.file(f"files/tchat/{_oid(src.get('id')) or 0}-{_safe_part(src.get('name'))}", os.path.join("tchat", str(d["room_id"])), name,
                   mime=str(src.get("mime") or ""))
    if not got or not rk:
        return None
    d["path"], d["size"] = got
    d["org_id"] = None if rk[0] == "list" else run.org
    return d


def _msg(c, run, src, d, ctx):
    if _txt(src.get("enc"), 10):
        run.warning(N_("Chat messages encrypted in the browser were taken over as they are: they open with the keys of their channel."))
    elif d.get("body"):  # 2.362.4 (#3100)
        d["body"] = umz_mentions(d["body"], run.names, ctx.who)
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
    d.update(answers=json.dumps(m), ip_hash="", edit_hash=_token_hash(secrets.token_urlsafe(18)))  # never the old hash (review)
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


def _nl_hash(c, run, src, d, ctx):
    """2.362.0 (#3096): a row of the suppression list / consent log in the target's workspace (an address already suppressed
    there stays as it is)."""
    h = _txt(src.get("email_hash"), 64).lower()
    if len(h) != 64 or any(x not in "0123456789abcdef" for x in h):
        return False
    d["ws"], d["email_hash"] = (f"o{run.org}" if run.org else f"u{ctx.uid}"), h
    if ctx.spec.table == "nl_suppress" and c.execute("SELECT 1 FROM nl_suppress WHERE ws=? AND email_hash=?", (d["ws"], h)).fetchone():
        return False
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


def ticket_seal(c, run, uid, src, d):
    """A customer report: the address sealed again with this server's key, a new status link (the old one is not exported).
    2.455.0 (#3469): in the space of its list (an account import keeps a home project private), for both imports."""
    from ..accounts.login import seal
    from ..accounts.session import _token_hash
    from ..team.portal import pt_email_hash, pt_email_norm
    e = pt_email_norm(src.get("email"))
    tok = secrets.token_urlsafe(24)
    org = run.list_org.get(d["list_id"], run.org)
    d.update(org_id=org, owner_id=None if org else uid, email=seal(c, "portal-email", e) if e else "", email_hash=pt_email_hash(c, e) if e else "",
             token=seal(c, "portal-token", tok), token_hash=_token_hash(tok), notify=d.get("notify", 1) if e else 0)
    run.warning(N_("Client reports got new status links: the old links no longer open."))
    return d


def _ticket(c, run, src, d, ctx):
    return ticket_seal(c, run, ctx.uid, src, d)


# ---------------------------------------------------------------- rules, histories
_RULE_AT = re.compile(r"<@(\d{1,18})>")  # as in collab/comments.py


_W_RULE_PAUSED = N_("A rule was paused because something it refers to did not come along: {0}")
_W_RULE_LEFT = N_("A rule was left out because this version cannot read it or the project has too many: {0}")


def rule_fields(data):
    """2.455.0 (#3469): {old field id: type} of the file (a rule's field value can be a person)."""
    return {_oid(f.get("id")): f.get("type") for f in data.get("list_fields") or [] if isinstance(f, dict)}


def rule_ids(c, run, who, types, src, d):
    """2.455.0 (#3469): the row d of rule src with every id inside it mapped, for the account and the organisation import. Trigger
    and action point at columns, tags, fields, people and lists of the list; what did not come along pauses the rule (the settings
    name why, like the app does when a column / person goes) with a word in the report, never an old id: it would name a row of
    this server. What the app itself would refuse (rules.py) leaves the rule out. -> d or None."""
    name, lid = _txt(src.get("name"), RUL_NAME_MAX).strip() or tr("Rules"), d["list_id"]
    n = c.execute("SELECT COUNT(*) FROM list_rules WHERE list_id=? AND deleted_at IS NULL", (lid,)).fetchone()[0]
    trig, act = src.get("trig"), src.get("act")
    if n >= RUL_LIST_MAX or trig not in RUL_TRIGGERS or act not in RUL_ACTIONS:
        run.warning(_W_RULE_LEFT, name)
        return None
    pause, tv = "", _txt(src.get("trig_val"), 300)
    if trig in ("section", "ltag"):
        new = run.m("sections" if trig == "section" else "list_tags", tv)
        tv, pause = str(new or ""), "" if new else "section" if trig == "section" else "tag"
    elif trig == "assigned":
        new = who(tv) if tv else None
        tv, pause = str(new or ""), "assignee" if tv and not new else ""
    elif trig == "field":  # "<field id>" or "<field id>=<value>": an option's id is the field's own, it moves with the field
        fid, eq, val = tv.partition("=")
        new = run.m("list_fields", fid)
        tv, pause = f"{new}{eq}{val}" if new else "", "" if new else "field"
    else:
        tv = ""
    try:
        a = json.loads(src.get("act_val") or "{}") if isinstance(src.get("act_val"), str) else (src.get("act_val") or {})
    except (ValueError, RecursionError):
        a = {}
    a, v, target = a if isinstance(a, dict) else {}, {}, None
    if act == "assign":
        v = {"user_id": who(a.get("user_id"))}
        pause = pause or ("" if v["user_id"] else "assignee")
    elif act == "move":
        dst = run.m("lists", a.get("list_id")) if a.get("list_id") else lid if not src.get("target_list_id") and a else None
        sid = run.m("sections", a.get("section_id")) if a.get("section_id") else None
        v, target = {"list_id": dst, "section_id": sid}, dst if dst != lid else None
        pause = pause or ("target" if not dst else "section" if a.get("section_id") and not sid else "")
    elif act == "due":
        days = a.get("days")
        if days is not None and not (isinstance(days, int) and not isinstance(days, bool) and 0 <= days <= RUL_DAYS_MAX):
            run.warning(_W_RULE_LEFT, name)
            return None
        v = {"days": days}
    elif act == "comment":
        text = a.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > RUL_TEXT_MAX:
            run.warning(_W_RULE_LEFT, name)
            return None
        v = {"text": _RULE_AT.sub(lambda m: f"<@{who(m.group(1))}>" if who(m.group(1)) else "@?", text.strip())}  # a mention by id
    elif act == "priority":
        if a.get("priority") not in RUL_PRIO:
            run.warning(_W_RULE_LEFT, name)
            return None
        v = {"priority": a["priority"]}
    elif act == "tag":
        v = {"tag_id": run.m("list_tags", a.get("tag_id"))}
        pause = pause or ("" if v["tag_id"] else "tag")
    else:  # field: a person's value is an id too; a value of other types has none
        fid, val = run.m("list_fields", a.get("field_id")), a.get("value")
        if types.get(_oid(a.get("field_id"))) == "person" and val is not None:
            val = who(val)
            pause = pause or ("" if val else "field")
        v = {"field_id": fid, "value": val}
        pause = pause or ("" if fid else "field")
    d.update(name=name, trig=trig, trig_val=tv, act=act, act_val=json.dumps(v, separators=(",", ":")), target_list_id=target)
    if pause:
        d.update(active=0, paused_reason=pause)
        run.warning(_W_RULE_PAUSED, name)
    return d


def _rule(c, run, src, d, ctx):
    return rule_ids(c, run, ctx.who, rule_fields(ctx.data), src, d)


def sprint_finish(c, run, rows):
    """2.455.0 (#3469): after the tasks: the close-out of an imported sprint names the new tasks (an old id would count a task of
    this server); at most one running sprint per list, also with one already there, the app keeps that (a state it does not know:
    planned)."""
    for r in rows:
        nid = run.m("sprints", r.get("id"))
        if not nid:
            continue
        try:
            rv = json.loads(r["review"]) if isinstance(r.get("review"), str) else None
        except (ValueError, RecursionError):
            rv = None
        if isinstance(rv, dict):
            rv.update({k: [n for n in (run.m("tasks", x) for x in rv.get(k) or [] if not isinstance(x, (list, dict))) if n]
                       for k in ("done", "moved", "added") if isinstance(rv.get(k) or [], list)})
            rv["next_id"] = run.m("sprints", rv.get("next_id"))
        state = r.get("state")
        if state not in ("planned", "active", "closed") or (state == "active" and c.execute(
                "SELECT 1 FROM sprints WHERE state='active' AND id<>? AND list_id=(SELECT list_id FROM sprints WHERE id=?)", (nid, nid)).fetchone()):
            state = "planned"
        c.execute("UPDATE sprints SET state=?, review=? WHERE id=?", (state, json.dumps(rv) if isinstance(rv, dict) else None, nid))


def _sprint(c, run, src, d, ctx):
    """2.455.0 (#3469): state and close-out only from sprint_finish: a stop before it keeps no old id."""
    d.update(review=None, state="planned")
    return d


def _sprints(c, run, uid, data, who):
    sprint_finish(c, run, (data.get("oi") or {}).get("lists/sprints.json") or [])


# ---------------------------------------------------------------- feeds
def _feed(c, run, src, d, ctx):
    """2.455.0 (#3469): a feed of the file comes in like a new one: its address checked as in the app (the fetch has its own guard),
    the limit of a space, none twice; the articles are fetched again."""
    url = _norm(src.get("url"))
    if not url:
        run.warning(N_("A feed without its address was not taken over: {0}"), _txt(src.get("title"), 80))
        return False
    w = ("org_id=?", run.org) if run.org else ("org_id IS NULL AND user_id=?", ctx.uid)
    if c.execute(f"SELECT 1 FROM rss_feeds WHERE {w[0]} AND url=? AND deleted_at IS NULL", (w[1], url)).fetchone():
        return False
    if c.execute(f"SELECT COUNT(*) FROM rss_feeds WHERE {w[0]} AND deleted_at IS NULL", (w[1],)).fetchone()[0] >= RSS_MAX_FEEDS:
        run.warning(N_("A feed was not taken over, the limit is reached: {0}"), _txt(src.get("title"), 80))
        return False
    d["url"] = url
    return d


def _reading(c, run, src, d, ctx):
    """2.455.0 (#3469): the read-later project of the organisation; a target that has one keeps its own."""
    if c.execute("SELECT 1 FROM reading_orgs WHERE org_id=? AND list_id IS NOT NULL", (run.org,)).fetchone():
        return False
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
            v[k] = -1  # still "assigned to" (the history shows "Deleted person"), not "removed the assignee"
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


def _mail_link(c, run, src, d, ctx):
    """2.362.0 (#3096): a task / event made from a filed e-mail (both must have come along)."""
    kind = _txt(src.get("kind"), 20)
    new = run.m({"task": "tasks", "event": "events"}.get(kind, ""), src.get("ref_id")) if kind in ("task", "event") else None
    if not new:
        return False
    d["kind"], d["ref_id"] = kind, new
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
    # 2.362.0 (#3096): section templates of the organisation (into the private space: the importing person's own)
    OiT("lists/section_templates.json", "section_templates", people={"user_id": "me"}, enc=False, label=N_("Section templates")),
    OiT("lists/sprints.json", "sprints", refs={"list_id": "lists"}, need=("list_id",), people={"created_by": "null"}, space=(),
        label=N_("Sprints"), prep=_sprint),
    OiT("lists/rules.json", "list_rules", refs={"list_id": "lists", "target_list_id": "lists"}, need=("list_id",),
        people={"created_by": "null"}, label=N_("Rules"), prep=_rule),
    OiT("lists/history.json", "list_activity", refs={"list_id": "lists"}, need=("list_id",), people={"user_id": "null"}, space=(),
        label=N_("History"), prep=_activity),
    OiT("lists/admin_log.json", "org_list_log", refs={"list_id": "lists"},
        people={"by_id": "null", "owner_id": "null", "to_id": "null"}, private=False, label=N_("History")),
    OiT("portal/tickets.json", "portal_tickets", refs={"task_id": "tasks", "list_id": "lists", "form_id": "forms", "client_id": "clients"},
        need=("task_id", "list_id"), fixed=_NEW_TOKEN, label=N_("Client reports"), prep=_ticket),
    # tasks
    OiT("tasks/people.json", "task_people", refs={"task_id": "tasks"}, need=("task_id",), people={"user_id": "member"}, space=(), rid=False,
        label=N_("People")),
    OiT("tasks/links.json", "task_links", refs={"task_id": "tasks", "list_id": "lists", "section_id": "sections"},
        need=("task_id", "list_id"), people={"added_by": "null"}, rid=False, label=N_("Tasks")),
    OiT("tasks/history.json", "activity", refs={"task_id": "tasks"}, need=("task_id",), people={"user_id": "null"}, space=(),
        label=N_("History"), prep=_activity),
    OiT("tasks/encrypted_notes.json", "task_enc_notes", refs={"task_id": "tasks"}, need=("task_id",), space=(), rid=False, enc=False,
        people={"user_id": "null"}, label=N_("Encrypted notes"), prep=_chain(_person("user_id"), _legacy("kalmido-note:v1"))),  # 2.362.0 (#3090)
    OiT("tasks/locked_notes.json", "task_note_locks", refs={"task_id": "tasks"}, need=("task_id",), space=(), rid=False, enc=False,
        people={"user_id": "null"}, label=N_("Encrypted notes"), prep=_chain(_person("user_id"), _legacy("kalmido-locknote:v1"))),
    # 2.278.0 B (#3094): billed_doc_id -> the new invoice (office_docs come first, oi_office); billed_at kept
    OiT("time_entries.json", "time_entries", refs={"task_id": "tasks", "list_id": "lists", "billed_doc_id": "office_docs"}, people={"user_id": "null"},
        space=(), label=N_("Time entries"), prep=_chain(_time, _time_person, _billed)),
    OiT("time_sheets.json", "time_sheets", people={"user_id": "null", "decided_by": "null"}, label=N_("Time entries"),
        prep=_person("user_id")),
    OiT("comments/reactions.json", "comment_reactions", refs={"comment_id": "comments"}, need=("comment_id",),
        people={"user_id": "need"}, space=(), rid=False, label=N_("Reactions")),
    # chat
    # 2.362.0 (#3092): + the organisation's channels with their members and the files of the messages
    OiT("chat/channels.json", "tchat_rooms", refs={"list_id": "lists"}, people={"created_by": "null"}, space=(), label=N_("Team chat"),
        prep=_room, after=_room_after),
    OiT("chat/members.json", "tchat_members", refs={"room_id": "tchat_rooms"}, need=("room_id",), people={"user_id": "member", "added_by": "null"},
        space=(), rid=False, label=N_("Team chat"), prep=_room_member),
    # 2.278.0 B (#3094): thread_of (the thread's first message) mapped like reply_to, never the old id
    OiT("chat/messages.json", "tchat_msgs", refs={"room_id": "tchat_rooms", "task_id": "tasks"}, need=("room_id",),
        people={"user_id": "null", "pinned_by": "null"}, late={"reply_to": "tchat_msgs", "thread_of": "tchat_msgs"}, space=(), enc=False, label=N_("Team chat"),
        prep=_msg),
    OiT("chat/reactions.json", "tchat_rx", refs={"message_id": "tchat_msgs"}, need=("message_id",), people={"user_id": "need"},
        space=(), rid=False, label=N_("Team chat")),
    OiT("chat/files.json", "tchat_files", refs={"message_id": "tchat_msgs", "room_id": "tchat_rooms"}, need=("message_id", "room_id"),
        people={"user_id": "null"}, space=(), enc=False, label=N_("Team chat"), prep=_chat_file),
    # shares of calendars and address books (only with ticked people)
    OiT("calendars/members.json", "ev_cal_members", refs={"cal_id": "ev_cals"}, need=("cal_id",), people={"user_id": "member"}, space=(),
        rid=False, prep=_not_me),
    OiT("books/contact_tasks.json", "contact_tasks", refs={"contact_id": "contacts", "task_id": "tasks"}, need=("contact_id", "task_id"),
        people={"added_by": "null"}, space=(), rid=False, label=N_("Contacts")),  # 2.362.0 (#3096)
    OiT("books/members.json", "book_members", refs={"book_id": "books"}, need=("book_id",), people={"user_id": "member"}, space=(),
        rid=False, prep=_not_me),
    # newsletter
    OiT("newsletter/connection.json", "nl_conns", people={"created_by": "null"}, label=N_("Newsletter"), prep=_nl_conn),
    OiT("newsletter/segments.json", "nl_segments", refs={"conn_id": "nl_conns"}, need=("conn_id",), label=N_("Newsletter"), prep=_nl_seg),
    OiT("newsletter/members.json", "nl_members", refs={"seg_id": "nl_segments"}, need=("seg_id",), rid=False, label=N_("Newsletter")),
    OiT("newsletter/runs.json", "nl_runs", refs={"conn_id": "nl_conns"}, need=("conn_id",), people={"by_id": "null"}, label=N_("Newsletter")),
    OiT("newsletter/suppressed.json", "nl_suppress", fixed={"ws": ""}, enc=False, label=N_("Newsletter"), prep=_nl_hash),  # 2.362.0 (#3096)
    OiT("newsletter/consent_log.json", "nl_consent_log", fixed={"ws": ""}, enc=False, label=N_("Newsletter"), prep=_nl_hash),
    # absences, bookings, vacation accounts, filed e-mails
    OiT("hub/absences.json", "hub_absences", people={"user_id": "null", "created_by": "null", "decided_by": "null"}, private="office",
        label=N_("Absences and bookings"), prep=_person("user_id", member=True)),
    OiT("hub/bookings.json", "hub_bookings", refs={"list_id": "lists", "event_id": "events"}, people={"created_by": "null"},
        fixed={"resource_id": 0}, private="office", label=N_("Absences and bookings"), prep=_booking),
    OiT("hub/leave_quota.json", "hub_leave_quota", people={"user_id": "null", "updated_by": "null"}, private="office", label=N_("Absences and bookings"),
        prep=_person("user_id", member=True)),
    OiT("hub/mails.json", "hub_mails", refs={"client_id": "clients", "list_id": "lists", "eml_id": "fs_nodes", "folder_id": "fs_nodes"},
        people={"deleted_by": "null"}, fixed={"message_id": ""}, label=N_("Absences and bookings"), prep=_mail, after=_mail_index),
    OiT("hub/mail_links.json", "hub_mail_links", refs={"mail_id": "hub_mails"}, need=("mail_id",), people={"created_by": "null"},
        fixed={"ref_id": 0}, label=N_("E-mails"), prep=_mail_link),  # 2.362.0 (#3096)
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
    # 2.455.0 (#3469): the feeds of the organisation (into the private space: the importing person's own) and its read-later project
    OiT("feeds/feeds.json", "rss_feeds", people={"user_id": "me"}, enc=False, label=N_("Feeds"), prep=_feed),
    OiT("feeds/reading.json", "reading_orgs", refs={"list_id": "lists"}, need=("list_id",), rid=False, key=("list_id",), private=False,
        enc=False, label=N_("Read later"), prep=_reading),
]
FIXES = [OiFix("tasks", "tasks", "sprint_id", "sprints")]  # the sprint of a task
FINISH = [_sprints]  # 2.455.0 (#3469)
