"""2.891.0 (#5270, stage Q2 of the cross-section audit #3563): THE one decision who hears of an object.

Before this stage every area built the set of people of a push / News entry and checked their rights itself (the watchers:
task_visible, the team chat: list_role, the calendar reminders: the live shares of #5046, news_add: acx_task_ok, the task
reminders: their own memo of list roles). #5046 was exactly that kind of fault: an area read the people from an old table and
a person the core had taken a share from still got reminders. Now there is one function, obj_notify, and its first step is
not optional:

  1. rights   every recipient is cut with obj_role(kind, id) >= 'view' of the shared core (core/objects.py; for the light
              kinds task / event the area's own rule as the core knows it, core/objlight.py). An agent is never a recipient
              (it gets agent_emit events); an account without a role on the object gets nothing -- not the News entry, not
              the push. A kind the core does not know is an error (ValueError), there is no fallback. The one object outside
              the core that notifies is a direct message of the team chat: its reader is the pair (collab/teamchat.py
              registers NOTIFY_READERS['tchat_dm'] in core/objhooks.py, the rule of tcxcore's docstring)
  2. account  the person's settings: S[uid] when the caller read them for many (the watchdog, the team chat), else
              collab_user (enabled account, collaboration on)
  3. News     news = {kind, task_id, list_id, comment_id, data, actor}: the entry is written for everyone after step 2 whose
              notification settings want it (collab/news.py news_put: notif_ok 'news', the list bell)
  4. follow   follow(uid, s) -> False = no push (the task's bell muted / urgent, a thread one does not follow; the core's
              obj_follow of stage Q9 takes this place)
  5. notif_ok THE settings check (collab/news.py): the matrix, the list bell (bells = what the caller read already), the
              ceiling of the list owner's template (notify/caps.py cap_ok, own = whose own reminder it is)
  6. gate     gate(uid, s) -> False = no push now (push_reachable, the burst / summary gates, an agent's push switch)
Returns {uid: settings} of the people who get the push; the caller builds the text in their language and queues it (the
texts differ per area; an end-to-end list's push carries no words -- that stays the caller's).

Interface:
  obj_readers(c, kind, rid, uids, memo=None) -> {uid}       step 1 alone (memo: a dict kept for one watchdog tick)
  obj_notify(c, kind, rid, recipients, *, row, lid=None, own=(), S=None, bells=None, news=None, follow=None, gate=None,
             push=True, memo=None) -> {uid: settings}
row: the event of the notification settings (str) or a function uid -> event (a mention among chat messages).
"""
from flask import has_request_context

from .objects import OBJ, OBJ_RANK, obj_role
from .objhooks import NOTIFY_READERS, NOTIFY_TICK
from .pg import st_ids
from ..collab.comments import collab_user
from ..collab.news import news_put, notif_ok


def _agents(c, uids, memo=None):
    """{uid} of the agents among uids (memo: ("agent", uid) -> bool, kept for the tick)."""
    ask = [u for u in uids if memo is None or ("agent", u) not in memo]
    got = {r[0] for r in c.execute("SELECT id FROM users WHERE id = ANY(CAST(? AS BIGINT[])) AND kind='agent'", (st_ids(ask),))} if ask else set()
    if memo is not None:
        memo.update({("agent", u): u in got for u in ask})
        return {u for u in uids if memo[("agent", u)]}
    return got


def obj_readers(c, kind, rid, uids, memo=None):
    """{uid} of uids (people, never agents) who may read object (kind, rid): obj_role >= 'view' (step 1, the module docstring).
    memo: the dict of one watchdog tick (no request cache there): {(uid, kind, rid): bool}, and for a kind with a tick reader
    (objhooks NOTIFY_TICK: the task) its per-project answers -- the same rule as obj_role, read once per project and person."""
    reader = NOTIFY_READERS.get(kind)
    if reader is None and kind not in OBJ:
        raise ValueError(f"obj_notify: unknown kind {kind!r}")
    if reader is not None and kind in OBJ:  # 2.891.0 (#5270, review): a reader never stands in for the core's obj_role
        raise ValueError(f"obj_notify: kind {kind!r} is a core kind - its readers come from obj_role, not NOTIFY_READERS")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return set()
    ids = sorted({int(u) for u in uids or () if u})
    ags = _agents(c, ids, memo)
    ids = [u for u in ids if u not in ags]
    out = set()
    for u in ids:
        k = (u, kind, rid)
        if memo is not None and k in memo:
            ok = memo[k]
        else:
            if reader is not None:
                ok = bool(reader(c, u, rid))
            elif memo is not None and kind in NOTIFY_TICK and not has_request_context():
                ok = bool(NOTIFY_TICK[kind](c, u, rid, memo))
            else:
                ok = OBJ_RANK[obj_role(c, u, kind, rid)] >= OBJ_RANK["view"]
            if memo is not None:
                memo[k] = ok
        if ok:
            out.add(u)
    return out


def obj_notify(c, kind, rid, recipients, *, row, lid=None, own=(), S=None, bells=None, news=None, follow=None, gate=None,
               push=True, memo=None):
    """THE send decision about object (kind, rid) (module docstring, steps 1-6). Writes the News entries (news) and returns
    {uid: settings} of who gets the push (push=False: none, only the News)."""
    if news is not None and news.get("task_id") is not None and (kind != "task" or int(news["task_id"]) != int(rid)):
        raise ValueError("obj_notify: the News entry's task_id must be the object that was checked")  # 2.891.0 (#5270, review)
    out = {}
    for uid in sorted(obj_readers(c, kind, rid, recipients, memo)):
        s = S.get(uid) if S is not None else collab_user(c, uid)
        if not s:
            continue
        ev = row(uid) if callable(row) else row
        if news is not None:
            news_put(c, uid, s=s, row=ev, **news)
        if not push:
            continue
        if follow is not None and not follow(uid, s):
            continue
        if not notif_ok(c, uid, s, ev, "push", lid, own=uid in own, bell=(bells or {}).get(uid)):
            continue
        if gate is not None and not gate(uid, s):
            continue
        out[uid] = s
    return out
