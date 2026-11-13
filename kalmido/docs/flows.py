"""2.581.0 (#4803): document flows ("Abläufe") -- the document rules with a trigger, filters and actions (like Paperless-ngx'
workflows). No second engine: a flow is a row of doc_rules (sealed JSON, docs/rules.py clean_rule), an old rule reads as a flow
with the trigger "received" and runs where it ran before (docs/store.py classify, the recognition run).

Triggers
  received   the first recognition run of a document (docs/ingest.py doc_on_done, first=True): the sorting actions go through
             classify as before (the levels per feature apply), the other actions run here afterwards
  changed    a change of the document's tags / type / sender / custom fields (docs/web.py doc_update: the app, API v1, batch,
             receipts), optionally only for some of them ("on")
  scheduled  X days after the document's date / due date / the day it came in; at most one run per flow, document and stamp
             (the base date: changing it gives a new stamp), only for stamps from the day the flow was saved on (a new flow
             does not run over the whole archive). The tick: integrations/docflowhook.py (the background worker).
Filters: the words (any / all / exact / regex / fuzzy, now optional), source (upload, mail, scan, fetcher, import), file name (a
pattern with * and ?), has one of the tags, type, sender (docs/rules.py flow_pass).
Actions: sender / type / folder / tags (as before), remove tags, set custom fields, make a task (in the inbox of the flow's
author or a chosen person who sees the document), notify people (News "docflow", their switch "docflow"; only people who
see the document), webhook (the same check as the other webhooks: integrations/webhooks.py wh_url_check when saved and again
when sent, no internal host; signed with the flow's own secret, shown once).
Share (2.635.0, #4856): give people / groups of the workspace a share of the document (view | edit) -- only through the shared
core (#4709): the targets are the ones the file store's share dialog offers (files/web.py _share_targets), the row is written by
core/objects.py obj_node_share. Who saved the share action (share_by) must be allowed to share the document: checked when the
flow is saved (the targets) and again on every run (manage on the document, organisation boundary, the target still in the
pool); a target that already has a share keeps it as it is, so the undo takes back only the shares the run made.

Every run that did something is a row of doc_flow_runs (sealed values before / after) with an entry "flow" in the document's
history (fs_log); a person who may edit the document takes it back (POST /api/docs/flowruns/<id>/undo): the values the run set
and that are still as it left them go back, a task it made goes to the trash, a webhook call not sent yet is dropped. A
notification already shown and a webhook already sent cannot be taken back.
No loops: the actions of a flow never go through doc_update, so they trigger no "changed" flow (depth 1); a thread-local mark
guards it besides."""
import json
import secrets
import threading
from datetime import date, datetime, time as dtime, timedelta

from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL, TZ
from ..core.db import bump, db, err, insert_id, iso, local_day, local_now, now_utc
from ..core.i18n import tr
from ..core.objtags import otg_ws_drop, otg_ws_link  # 2.1119.0 (#5277): the file store's tags are the core's
from ..core.access import Denied, acx_of, acx_org_ok, task_visible
from ..core.pages import new_inbox_task
from ..tasks.validation import log_act
from ..accounts.session import me
from ..collab.comments import collab_user
from ..collab.news import notif_ok
from ..files.store import fs_log_add, fs_role
from ..files.fsroots import fs_area_share  # 2.635.0 (#4856)
from ..files.web import _share_targets  # 2.635.0 (#4856): the file store's share pool
from . import rules as RU
from . import store as S
from .ingest import doc_on_done
from .fields import df_rows, df_set, df_values
from .web import _doc, _no_agent, _reindex

CTX = "doc_flow_runs.data"
FL_URL_CHECK = []      # f(c, url) -> normalized url, raises BadInput (integrations/docflowhook.py; empty = webhooks off)
FL_RUNS_SHOWN = 20     # runs of a document the sheet lists
FL_TICK_DOCS = 100     # documents one scheduled flow looks at per tick
SCHED_COL = {"date": "d.doc_date", "due": "d.due_date", "added": "substr(CAST(d.created_at AS text), 1, 10)"}
_IN = threading.local()  # set while the actions of a flow run: a change they make starts no "changed" flow (depth 1)


def _ts():
    return iso(now_utc())


# ---- saving a flow (docs/web.py _rule_save) ------------------------------------------------------------------------------
def _ws_people(c, ws):
    """The ids of the people a flow of ws may name (notify / task): the person of a private workspace, the organisation's members."""
    oid = S.ws_org(ws)
    if not oid:
        return {S.ws_user(ws)}
    return {r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND NOT u.disabled", (oid,))}


def fl_people(c, ws):
    """[{id, name}] of the people a flow of ws may notify or give a task (the settings' form)."""
    ids = sorted(x for x in _ws_people(c, ws) if x)
    if not ids:
        return []
    rows = c.execute(f"SELECT id, COALESCE(NULLIF(display_name, ''), username) AS n FROM users WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return sorted(({"id": r["id"], "name": r["n"]} for r in rows), key=lambda x: str(x["name"]).lower())


def _share_node(c, ws):
    """2.635.0 (#4856): the node the pool of a workspace is asked for: its documents folder, else a stand-in of the workspace."""
    rid = S.root_id(c, ws)
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (rid,)).fetchone() if rid else None
    return n or {"id": 0, "org_id": S.ws_org(ws), "owner_id": S.ws_user(ws), "kind": "folder", "name": ""}


def fl_share_pool(c, ws, uid, n=None):
    """2.635.0 (#4856): {"user_id": {id: name}, "group_id": {id: name}} -- the people and groups uid may share a document of
    ws (or node n) with: the file store's own rule (files/web.py _share_targets: the same workspace, visible people, groups),
    nothing for an agent account."""
    if not uid or acx_of(c, uid).role == "agent":
        return {"user_id": {}, "group_id": {}}
    t = _share_targets(c, n if n is not None else _share_node(c, ws), uid)
    return {"user_id": {x["id"]: x["name"] for x in t["people"]}, "group_id": {x["id"]: x["name"] for x in t["groups"]}}


def fl_share_list(c, ws, uid):
    """2.635.0 (#4856): the pool for the settings' form: [{key, id, name}] (people first, then groups)."""
    p = fl_share_pool(c, ws, uid)
    return [{"key": k, "id": i, "name": nm} for k in ("user_id", "group_id") for i, nm in sorted(p[k].items(), key=lambda x: str(x[1]).lower())]


def fl_clean(c, ws, d, old=None):
    """The flow to store from user input d (old = the stored one when it is edited). Raises RU.RuleError (a reason of
    docs/web.py _rule_save) or returns (flow, secret shown once or None)."""
    r = RU.clean_rule(d, extra=True)
    if r.get("share"):  # 2.635.0 (#4856): only targets the person who saves may share with; an unchanged share keeps its author
        o = old if isinstance(old, dict) else {}
        if o.get("share") == r["share"] and o.get("share_by"):
            r["share_by"] = o["share_by"]
        else:
            pool = fl_share_pool(c, ws, me())
            if any(x.get("user_id", x.get("group_id")) not in pool["user_id" if "user_id" in x else "group_id"] for x in r["share"]):
                raise RU.RuleError("share_target")
            r["share_by"] = me()
    people = None
    for uid in [*(r.get("notify") or []), *([r["task"]["to"]] if r.get("task", {}).get("to") else [])]:
        people = people if people is not None else _ws_people(c, ws)
        if uid not in people:
            raise RU.RuleError("person")
    if r.get("fields"):
        names = {x["name"].lower() for x in df_rows(c, ws)}
        if any(k.lower() not in names for k in r["fields"]):
            raise RU.RuleError("field")
    shown = None
    if r.get("webhook"):
        if not FL_URL_CHECK:
            raise RU.RuleError("hooks_off")
        r["webhook"] = FL_URL_CHECK[0](c, r["webhook"])  # BadInput with the reason (an internal host, http://, ...)
        keep = old if isinstance(old, dict) and old.get("webhook") == r["webhook"] and old.get("hook_secret") else None
        r["hook_secret"] = keep["hook_secret"] if keep else secrets.token_urlsafe(24)
        shown = None if keep else r["hook_secret"]
    else:
        r.pop("hook_secret", None)
    if RU.trigger_of(r) == "scheduled":  # 2.581.0 (#4803 review): stamps count from the day the timing was set (since), not
        # from the day the row was made: an old flow turned into a scheduled one does not run over the whole archive
        o = old if isinstance(old, dict) else {}
        same = RU.trigger_of(o) == "scheduled" and o.get("days") == r.get("days") and o.get("from") == r.get("from")
        if not same:
            r["since"] = local_now().date().isoformat()
        elif o.get("since"):
            r["since"] = o["since"]  # unchanged timing keeps its day (a flow saved before has none: its created_at, fl_tick)
    return r, shown


def fl_rule_old(c, rid, ws):
    r = c.execute("SELECT data FROM doc_rules WHERE id=? AND ws=?", (rid, ws)).fetchone()
    return S._jopen(c, ws, "doc_rules.data", r[0], {}) if r else {}


# ---- the values of a document (before / after a run) --------------------------------------------------------------------
def _snap(c, nid):
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    return {"sender": m["sender_id"], "type": m["type_id"], "folder": S.folder_label(c, node) or "",
            "tags": sorted(t["id"] for t in S.node_tags(c, nid)), "fields": {str(k): v for k, v in df_values(c, nid, m["ws"]).items()}}


def _did(b, a):
    """The keys a run changed (sender, type, folder, tags, fields)."""
    return [k for k in ("sender", "type", "folder", "tags", "fields") if b.get(k) != a.get(k)]


def _fl_rules(c, ws):
    """The flows of ws with their author and the day they were saved (_by, _day)."""
    meta = {r[0]: (r[1], str(local_day(str(r[2] or "")) or "")) for r in c.execute("SELECT id, created_by, created_at FROM doc_rules WHERE ws=?", (ws,))}  # 2.658.0 (#5099): the local day
    return [{**r, "_by": meta.get(r["id"], (None, ""))[0], "_day": meta.get(r["id"], (None, ""))[1]} for r in S.rules_get(c, ws)]


def _text(c, m, node):
    return f"{node['name']}\n{S.meta_text(c, m)}"


# ---- the actions ----------------------------------------------------------------------------------------------------------
def _sort(c, nid, r):
    """sender / type / folder / tags of flow r set directly (the triggers changed / scheduled)."""
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    ws = m["ws"]
    for f, col in (("sender", "sender_id"), ("type", "type_id")):
        if r.get(f):
            lid = S.label_id(c, ws, f, r[f])
            if lid and lid != m[col]:
                c.execute(f"UPDATE doc_meta SET {col}=? WHERE node_id=?", (lid, nid))
    if r.get("folder"):
        uid = m["created_by"] or node["owner_id"]
        fid = S.folder_by_name(c, node, uid, r["folder"], path=True, check=True)
        # like a rule at the recognition (store.py classify): only into a folder the document's person may edit
        if fid and fs_role(c, fid, uid) in ("owner", "edit") and str(fid) != str(S.folder_label(c, node) or ""):
            S.move_to_folder(c, node, fid)
    if r.get("tags"):
        have = {t["id"]: t["auto"] for t in S.node_tags(c, nid)}
        add = [t for t in (S.label_id(c, ws, "tag", x) for x in r["tags"]) if t and t not in have]
        for t in add:
            otg_ws_link(c, nid, t, "rule")  # 2.1119.0 (#5277): the core's link, marked as a rule's


def _extra(c, nid, r, levels=None):
    """The actions besides the sorting: remove tags, custom fields, task, notifications, webhook. -> (task id, notified, hook)."""
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    ws = m["ws"]
    if r.get("untag") and not (levels and levels.get("tags") in ("agent", "off")):
        for x in r["untag"]:
            t = S.label_id(c, ws, "tag", x, create=False)
            if t:
                otg_ws_drop(c, nid, t)  # 2.1119.0 (#5277)
    for k, v in (r.get("fields") or {}).items():
        df_set(c, S.meta_row(c, nid), {k: v if v not in ("",) else None}, by="flow")  # a value the field does not take: left out
    tid = None
    if r.get("task"):
        t = r["task"]
        to = t.get("to") or r.get("_by")
        if to and fs_role(c, nid, to) and c.execute("SELECT 1 FROM users WHERE id=? AND NOT disabled AND kind<>'agent'", (to,)).fetchone():
            sender = S.label_name(c, ws, "sender", m["sender_id"])
            typ = S.label_name(c, ws, "type", m["type_id"])
            title = (t.get("title") or " ".join(x for x in (typ or "", sender or "") if x).strip() or node["name"])
            title = title.replace("{name}", node["name"]).replace("{sender}", sender or "").replace("{type}", typ or "").strip() or node["name"]
            tid = new_inbox_task(c, to, title[:300], f"[{node['name']}](#docs/{nid})", None, None)
            if t.get("due") and m["due_date"]:
                c.execute("UPDATE tasks SET due=? WHERE id=?", (m["due_date"], tid))
            if not m["task_id"]:
                c.execute("UPDATE doc_meta SET task_id=? WHERE node_id=?", (tid, nid))
    told = 0
    for uid in r.get("notify") or []:
        if not fs_role(c, nid, uid):
            continue  # only who sees the document (an organisation's member may not see a private folder's file)
        s = collab_user(c, uid, None)
        if s and notif_ok(c, uid, s, "docflow", "news"):
            c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (uid, "docflow", None, None, None, None, json.dumps({"doc": nid, "name": node["name"][:200], "flow": (r.get("name") or "")[:120]},
                                                                           ensure_ascii=False), _ts()))
            told += 1
    hook = bool(r.get("webhook")) and bool(FL_URL_CHECK)
    return tid, told, hook, _share(c, node, r)


def _share(c, node, r):
    """2.635.0 (#4856): the action share through the shared core. -> the ids of the shares this run made. Checked again now:
    the flow's share author (share_by, else its author) may still share the document (manage, or the area lets them), is no
    agent, stays inside the document's organisation, and each target is still in their pool; a target with a share already
    keeps it (role / expiry as they are)."""
    want = r.get("share") or []
    uid = r.get("share_by") or r.get("_by")
    if not want or not uid:
        return []
    from ..core.objects import obj_node_share
    if acx_of(c, uid).role == "agent" or not acx_org_ok(c, uid, node["org_id"]):
        return []
    if not c.execute("SELECT 1 FROM users WHERE id=? AND NOT disabled", (uid,)).fetchone():
        return []
    if fs_role(c, node["id"], uid) != "owner" and not fs_area_share(c, uid, node):
        return []
    pool = fl_share_pool(c, None, uid, node)
    made = []
    for x in want:
        key = "user_id" if "user_id" in x else "group_id"
        t = x[key]
        if t not in pool[key] or c.execute(f"SELECT 1 FROM fs_shares WHERE node_id=? AND {key}=?", (node["id"], t)).fetchone():
            continue
        try:
            made.append(obj_node_share(c, uid, node, key, t, x.get("role") or "view", None, node["org_id"] or None))
        except Denied:
            continue  # too many shares on the document: the others still go
    return made


def _record(c, nid, r, trig, before, tid, told, hook, stamp="", run_id=None, shared=()):
    """The run's row (+ the history entry); None when the run did nothing. shared = the ids of the shares it made (#4856)."""
    after = _snap(c, nid)
    did = _did(before, after)
    if not did and not tid and not told and not hook and not shared:
        if run_id:
            c.execute("UPDATE doc_flow_runs SET state='skip' WHERE id=?", (run_id,))
        return None
    m = S.meta_row(c, nid)
    ws = m["ws"]
    data = S._jseal(c, ws, CTX, {"b": before, "a": after, "did": did, "told": told, "name": (r.get("name") or "")[:120],
                                  **({"shared": list(shared)} if shared else {})})
    who = me() if has_request_context() and getattr(g, "user", None) else None
    if run_id:
        c.execute("UPDATE doc_flow_runs SET state='done', data=?, task_id=?, by_user=?, hook=? WHERE id=?",
                  (data, tid, who, "wait" if hook else "", run_id))
    else:
        run_id = insert_id(c, """INSERT INTO doc_flow_runs(org_id, ws, node_id, rule_id, trig, stamp, state, data, task_id, by_user, hook, created_at)
                                 VALUES(?,?,?,?,?,?,'done',?,?,?,?,?)""",
                           (S.ws_org(ws), ws, nid, r.get("id"), trig, stamp, data, tid, who, "wait" if hook else "", _ts()))
    fs_log_add(c, nid, "flow", (r.get("name") or f"#{r.get('id')}")[:120])
    if did:
        c.execute("UPDATE doc_meta SET updated_at=? WHERE node_id=?", (_ts(), nid))
        _reindex(c, nid)
    return run_id


def fl_run(c, nid, r, trig, stamp="", run_id=None):
    """Run flow r on document nid now (trigger changed / scheduled: every action directly). -> the run's id or None."""
    before = _snap(c, nid)
    _IN.on = True
    try:
        _sort(c, nid, r)
        S.title_auto(c, nid)  # 2.783.0 (#4882): a rule's sender / type -> the pattern's title (never one set by hand)
        tid, told, hook, shared = _extra(c, nid, r)
    finally:
        _IN.on = False
    return _record(c, nid, r, trig, before, tid, told, hook, stamp, run_id, shared)


def _hits(c, m, node, rules):
    """The flows of rules whose filters and words hold for the document (in their order)."""
    facts = S.flow_facts(c, m, node)
    cand = [r for r in rules if RU.flow_pass(r, facts)]
    return RU.matches(cand, _text(c, m, node)) if cand else []


# ---- trigger "received": after the first recognition run ------------------------------------------------------------------
def fl_on_done(c, nid, first):
    """doc_on_done hook. The sorting of the matching flows was done by classify (levels apply); here each matching flow gets its
    other actions and a run row: before = the values without what this flow set (the first flow that names a feature set it,
    tags of every flow add up -- the same order as docs/rules.py apply_rules)."""
    if not first:
        return
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node or m["state"] != "done":
        return
    rules = [r for r in _fl_rules(c, m["ws"]) if RU.trigger_of(r) == "received"]
    if not rules:
        return
    hits = _hits(c, m, node, rules)
    if not hits:
        return
    auto = S.meta_json(c, m, "auto", {})
    lv = S.cfg_get(c, m["ws"])["levels"]
    taken = set()
    tags_rule = {t["id"]: t for t in S.node_tags(c, nid) if t["auto"] == "rule"}
    for r in hits:
        cur = _snap(c, nid)
        before = json.loads(json.dumps(cur))
        for f in ("sender", "type", "folder"):
            if r.get(f) and f not in taken:
                taken.add(f)
                if auto.get(f) == "rule":
                    before[f] = None if f != "folder" else str(S.docs_root(c, node) or "")
        mine = {RU.fold(x) for x in r.get("tags") or []}
        before["tags"] = sorted(t for t in cur["tags"] if not (t in tags_rule and RU.fold(tags_rule[t]["name"]) in mine))
        _IN.on = True
        try:
            tid, told, hook, shared = _extra(c, nid, r, lv)
        finally:
            _IN.on = False
        _record(c, nid, r, "received", before, tid, told, hook, shared=shared)


if fl_on_done not in doc_on_done:
    doc_on_done.append(fl_on_done)


# ---- trigger "changed": docs/web.py doc_update ------------------------------------------------------------------------------
def _has_changed_flows(c, ws):
    """Does ws have a flow with the trigger changed? (read once per request: a batch of documents asks once)"""
    cache = g.setdefault("fl_changed", {}) if has_request_context() else {}
    if ws not in cache:
        cache[ws] = any(RU.trigger_of(r) == "changed" and not r.get("off") for r in S.rules_get(c, ws))
    return cache[ws]


def fl_before(c, nid):
    """The values doc_update compares with afterwards; None (nothing to compare) while a flow's own actions run (depth 1) or
    when the workspace has no "changed" flow (no extra reads for every save)."""
    if getattr(_IN, "on", False):
        return None
    m = S.meta_row(c, nid)
    if not m or not _has_changed_flows(c, m["ws"]):
        return None
    return _snap(c, nid)


def fl_changed(c, nid, before):
    """After a saved change: the flows with the trigger changed whose "on" covers what changed run once."""
    if before is None or getattr(_IN, "on", False):
        return []
    after = _snap(c, nid)
    kinds = {"tags": "tags", "type": "type", "sender": "sender", "fields": "field"}
    what = {kinds[k] for k in _did(before, after) if k in kinds}
    if not what:
        return []
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    rules = [r for r in _fl_rules(c, m["ws"]) if RU.trigger_of(r) == "changed" and (not r.get("on") or what & set(r["on"]))]
    out = []
    for r in _hits(c, m, node, rules) if rules else []:
        rid = fl_run(c, nid, r, "changed")
        if rid:
            out.append(rid)
    return out


# ---- trigger "scheduled": the background tick ---------------------------------------------------------------------------------
def _midnight_utc(day):
    """2.658.0 (#5099): the start of local day `day` (server time zone) as a stored UTC timestamp (iso), for created_at bounds."""
    return iso(datetime.combine(day, dtime(0), tzinfo=TZ))


def fl_tick(c):
    """One look at every scheduled flow (caller: system_ctx, commits). -> the number of runs made."""
    today = local_now().date()
    n = 0
    for (ws,) in c.execute("SELECT DISTINCT ws FROM doc_rules").fetchall():
        for r in _fl_rules(c, ws):
            if RU.trigger_of(r) != "scheduled" or r.get("off") or r.get("from") not in SCHED_COL:
                continue
            days = int(r.get("days") or 0)
            col = SCHED_COL[r["from"]]
            try:
                day = r.get("since") or r["_day"]  # 2.581.0 (#4803 review): the day the timing was set (fl_clean)
                since = date.fromisoformat(str(day)[:10]) if day else today
            except ValueError:
                since = today
            last, first = today - timedelta(days=days), since - timedelta(days=days)
            if r["from"] == "added":  # 2.658.0 (#5099): created_at is a UTC timestamp, its first 10 characters are the UTC day;
                # the window is local days (local_now), so the bounds are the local midnights as UTC timestamps and the stamp is
                # the local day of the row (a document that came in between 0:00 and 1:00 Berlin time was found only a day late)
                rows = c.execute("""SELECT d.node_id, d.created_at AS base FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                                    WHERE d.ws=? AND n.deleted_at IS NULL AND d.state IN ('done', 'failed') AND d.created_at IS NOT NULL
                                      AND d.created_at<? AND d.created_at>=? AND NOT EXISTS (SELECT 1 FROM doc_flow_runs x
                                      WHERE x.trig='scheduled' AND x.rule_id=? AND x.node_id=d.node_id) ORDER BY d.created_at, d.node_id LIMIT ?""",
                                 (ws, _midnight_utc(last + timedelta(days=1)), _midnight_utc(first), r["id"], FL_TICK_DOCS)).fetchall()
            else:
                rows = c.execute(f"""SELECT d.node_id, {col} AS base FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                                     WHERE d.ws=? AND n.deleted_at IS NULL AND d.state IN ('done', 'failed') AND {col} IS NOT NULL AND {col}<>''
                                       AND {col}<=? AND {col}>=? AND NOT EXISTS (SELECT 1 FROM doc_flow_runs x WHERE x.trig='scheduled'
                                       AND x.rule_id=? AND x.node_id=d.node_id AND x.stamp={col}) ORDER BY {col}, d.node_id LIMIT ?""",
                                 (ws, last.isoformat(), first.isoformat(), r["id"], FL_TICK_DOCS)).fetchall()
            for row in rows:
                nid = row["node_id"]
                stamp = (local_day(str(row["base"])) or today).isoformat() if r["from"] == "added" else str(row["base"])[:10]
                claim = c.execute("""INSERT INTO doc_flow_runs(org_id, ws, node_id, rule_id, trig, stamp, state, created_at)
                                     VALUES(?,?,?,?,'scheduled',?,'skip',?) ON CONFLICT DO NOTHING RETURNING id""",
                                  (S.ws_org(ws), ws, nid, r["id"], stamp, _ts())).fetchone()
                if not claim:
                    continue  # another process took it
                m = S.meta_row(c, nid)
                node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                if _hits(c, m, node, [r]) and fl_run(c, nid, r, "scheduled", stamp, claim[0]):
                    n += 1
            c.commit()
    return n


# ---- the webhook call (integrations/docflowhook.py sends it) ------------------------------------------------------------------
def fl_hook_payload(c, run):
    """(url, secret, body) of a waiting webhook call, or None when its flow / document is gone or the flow has no webhook any more."""
    ws = run["ws"]
    rr = c.execute("SELECT data FROM doc_rules WHERE id=? AND ws=?", (run["rule_id"], ws)).fetchone()
    r = S._jopen(c, ws, "doc_rules.data", rr[0], {}) if rr else {}
    m = S.meta_row(c, run["node_id"])
    node = c.execute("SELECT * FROM fs_nodes WHERE id=? AND deleted_at IS NULL", (run["node_id"],)).fetchone()
    if not r.get("webhook") or not r.get("hook_secret") or not m or not node:
        return None
    oid = S.ws_org(ws)
    doc = {"id": node["id"], "name": node["name"], "workspace": f"org:{oid}" if oid else "private", "source": m["source"],
           "sender": S.label_name(c, ws, "sender", m["sender_id"]), "type": S.label_name(c, ws, "type", m["type_id"]),
           "tags": [t["name"] for t in S.node_tags(c, node["id"])], "date": m["doc_date"], "due": m["due_date"],
           "url": f"{PUBLIC_URL}/#docs/{node['id']}"}
    body = {"event": "document.flow", "run": run["id"], "trigger": run["trig"], "at": run["created_at"],
            "flow": {"id": run["rule_id"], "name": r.get("name") or ""}, "document": doc}
    return r["webhook"], r["hook_secret"], json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


# ---- the routes: runs of a document, undo ---------------------------------------------------------------------------------------
def _run_json(c, row):
    d = S._jopen(c, row["ws"], CTX, row["data"], {})
    return {"id": row["id"], "flow_id": row["rule_id"], "name": d.get("name") or "", "trigger": row["trig"], "at": row["created_at"],
            "did": d.get("did") or [], "told": d.get("told") or 0, "task_id": row["task_id"], "hook": row["hook"],
            "shared": len(d.get("shared") or []),  # 2.635.0 (#4856)
            "undone": bool(row["undone_at"])}


@app.get("/api/docs/<int:nid>/flowruns")
def docs_flow_runs(nid):
    """The last runs of flows on a document (who may see it): [{id, flow_id, name, trigger, at, did, told, task_id, hook, undone}]."""
    _no_agent()
    c = db()
    m, n = _doc(c, nid)
    rows = c.execute("SELECT * FROM doc_flow_runs WHERE node_id=? AND state='done' ORDER BY id DESC LIMIT ?", (nid, FL_RUNS_SHOWN)).fetchall()
    return jsonify(runs=[_run_json(c, r) for r in rows], can_undo=n["role"] in ("owner", "edit"))


def _undo_vals(c, nid, b, a):
    """Put back what the run changed, where it is still as the run left it."""
    cur = _snap(c, nid)
    for f, col in (("sender", "sender_id"), ("type", "type_id")):
        if a.get(f) != b.get(f) and cur[f] == a.get(f):
            c.execute(f"UPDATE doc_meta SET {col}=? WHERE node_id=?", (b.get(f), nid))
    # 2.581.0 (#4803 review): back into the old folder only when the person who takes the run back may edit it there
    if (a.get("folder") != b.get("folder") and str(cur["folder"]) == str(a.get("folder")) and b.get("folder")
            and fs_role(c, int(b["folder"]), me()) in ("owner", "edit")):
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        S.move_to_folder(c, node, int(b["folder"]))
    added, gone = set(a.get("tags") or []) - set(b.get("tags") or []), set(b.get("tags") or []) - set(a.get("tags") or [])
    ws = S.meta_row(c, nid)["ws"]
    for t in added:
        otg_ws_drop(c, nid, t)  # 2.1119.0 (#5277): the core's links
    for t in gone:
        if S.label_ok(c, ws, "tag", t):
            otg_ws_link(c, nid, t, "")
    fa, fb, fc = a.get("fields") or {}, b.get("fields") or {}, cur["fields"]
    back = {k: fb.get(k) for k in set(fa) | set(fb) if fa.get(k) != fb.get(k) and fc.get(k) == fa.get(k)}
    if back:
        df_set(c, S.meta_row(c, nid), {k: v for k, v in back.items()}, by="flow")


def _undo_shares(c, nid, sids):
    """2.635.0 (#4856): the shares the run made go again (into obj_revoked, restorable) -- only when the person who takes the
    run back may manage the document's shares (an editor leaves them, like the folder above)."""
    if not sids:
        return
    from ..core.objects import obj_node_unshare
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not node or (fs_role(c, nid, me()) != "owner" and not fs_area_share(c, me(), node)):
        return
    for sid in sids:
        obj_node_unshare(c, me(), node, sid, reason="flow-undo")


@app.post("/api/docs/flowruns/<int:rid>/undo")
def docs_flow_undo(rid):
    """Take a run back (who may edit the document): values as before where nothing changed them since, the task it made into
    the trash (when I see it), a webhook call not sent yet dropped. -> {run, doc_id}."""
    _no_agent()
    c = db()
    row = c.execute("SELECT * FROM doc_flow_runs WHERE id=? AND state='done'", (rid,)).fetchone()
    if not row:
        raise Denied(404)
    _doc(c, row["node_id"], write=True)
    row = c.execute("SELECT * FROM doc_flow_runs WHERE id=? FOR UPDATE", (rid,)).fetchone()
    if row["undone_at"]:
        return err(tr("This run was undone already"), 409)
    d = S._jopen(c, row["ws"], CTX, row["data"], {})
    nid = row["node_id"]
    _IN.on = True
    try:
        _undo_vals(c, nid, d.get("b") or {}, d.get("a") or {})
    finally:
        _IN.on = False
    _undo_shares(c, nid, d.get("shared") or [])  # 2.635.0 (#4856)
    tid = row["task_id"]
    if tid and task_visible(c, tid, me(), write=True):
        if c.execute("UPDATE tasks SET deleted_at=? WHERE id=? AND deleted_at IS NULL RETURNING id", (_ts(), tid)).fetchone():
            log_act(c, tid, "delete")
        c.execute("UPDATE doc_meta SET task_id=NULL WHERE node_id=? AND task_id=?", (nid, tid))
    c.execute("UPDATE doc_flow_runs SET undone_at=?, hook=CASE WHEN hook='wait' THEN 'cancel' ELSE hook END WHERE id=?", (_ts(), rid))
    c.execute("UPDATE doc_meta SET updated_at=? WHERE node_id=?", (_ts(), nid))
    fs_log_add(c, nid, "flow-undo", (d.get("name") or f"#{row['rule_id']}")[:120])
    _reindex(c, nid)
    bump(c)
    c.commit()
    row = c.execute("SELECT * FROM doc_flow_runs WHERE id=?", (rid,)).fetchone()
    return jsonify(run=_run_json(c, row), doc_id=nid)

