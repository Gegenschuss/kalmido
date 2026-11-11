"""2.763.0 (#5269, stage Q1 of the cross-cutting core, analysis #3563): reactions exist once, in the shared core.

One table obj_reactions (migrations.d/5269_a.py) holds every reaction: (target_kind, target_id, user_id, emoji, created_at).
It replaces comment_reactions (comments of tasks), tchat_rx (team chat messages) and chat_reactions (the chat with an agent),
which had exactly these four columns. A target kind names the row the reaction sits on:

    comment     comments.id      (collab/reactions.py: approvals, suggestions, the agent's event stay there)
    tchat       tchat_msgs.id    (collab/teamchat.py)
    agent_chat  agent_chat.id    (agents/chat.py: a person's thumb on the agent's question, the agent's event)

The rule comes once (orx_toggle): no reaction on one's own message (taking an old one back still works), and who may only read
(a guest / read-only person of the organisation, core rule accounts/orgroles.py org_say_refusal, asked through the area's say
hook) does not react either -- taking one back stays. What happens on top of a reaction (an approval, an event) is the area's.

The reactions go with their target: a trigger of the fragment deletes them when the target row is deleted for good (the trash
run, an agent chat message deleted, a task purged with its comments); while a comment / team chat message is only in the trash
they stay, so restoring it brings them back (decided 08.11.2026, question 5). user_id has a real key (the account goes, its
reactions go). No organisation column: the target's area checks the reader before a reaction is read or written.
"""
from .db import now_utc
from .errors import BadInput, Denied
from .i18n import N_, tr
from .pg import qi

ORX_KINDS = ("comment", "tchat", "agent_chat")
ORX_OWN = N_("You cannot react to your own message")


def orx_of(c, kind, ids):
    """{target id: [{emoji, count, users: [{id, name}]}]} of the targets ids of kind, the emojis in the order of their first
    use, the people in the order they reacted."""
    out, ids = {}, [int(x) for x in ids if x]
    if not ids:
        return out
    for r in c.execute(f"""SELECT r.target_id, r.emoji, r.user_id, u.display_name, u.username FROM obj_reactions r
                           JOIN users u ON u.id=r.user_id WHERE r.target_kind=? AND r.target_id IN ({','.join('?' * len(ids))})
                           ORDER BY r.created_at, r.user_id""", (kind, *ids)).fetchall():
        lst = out.setdefault(r["target_id"], [])
        e = next((x for x in lst if x["emoji"] == r["emoji"]), None)
        if not e:
            e = {"emoji": r["emoji"], "count": 0, "users": []}
            lst.append(e)
        e["count"] += 1
        e["users"].append({"id": r["user_id"], "name": r["display_name"] or r["username"]})
    return out


def orx_has(c, kind, tid, uid, emoji):
    return c.execute("SELECT 1 FROM obj_reactions WHERE target_kind=? AND target_id=? AND user_id=? AND emoji=?",
                     (kind, int(tid), int(uid), emoji)).fetchone() is not None


def orx_toggle(c, kind, tid, uid, emoji, on=None, own=False, say=None):
    """The one rule of every reaction. on: True = set, False = take back, None = toggle (what uid has now). own: the target
    is uid's own message -> 400 when setting. say: the area's hook, () -> None or the refusal text of the organisation's say
    rule (a guest / read-only person) -> 403 when setting. Returns on; the caller writes it with orx_set."""
    if on is None:
        on = not orx_has(c, kind, tid, uid, emoji)
    if on and own:  # 2.23.0 (#823): not on one's own message (taking an old one back still works)
        raise BadInput(tr(ORX_OWN))
    if on and say:  # 2.607.0 (#4549): who may only read reacts not (taking one back stays)
        msg = say()
        if msg:
            raise Denied(403, tr(msg))
    return bool(on)


def orx_set(c, kind, tid, uid, emoji, on, at=None):
    """Sets (on) / takes back uid's reaction emoji on target tid of kind. True when something changed (a new reaction, one
    taken back), False when it was so already. The caller commits."""
    if kind not in ORX_KINDS:
        raise ValueError(kind)
    if not on:
        return bool(c.execute("DELETE FROM obj_reactions WHERE target_kind=? AND target_id=? AND user_id=? AND emoji=?",
                              (kind, int(tid), int(uid), emoji)).rowcount)
    return bool(c.execute("INSERT INTO obj_reactions(target_kind, target_id, user_id, emoji, created_at) VALUES(?,?,?,?,?) "
                          "ON CONFLICT DO NOTHING", (kind, int(tid), int(uid), emoji, at or now_utc())).rowcount)


# ---- the move of the three old tables (once; core/db.py init_db calls it before the fragments' AFTER drops them)
ORX_OLD = (("comment_reactions", "comment", "comment_id", "obj_comments"),  # 2.972.0 (#5272): comments -> obj_comments
           ("tchat_rx", "tchat", "message_id", "tchat_msgs"),  # review 2.972: the tuple had slid behind the comment above
           ("chat_reactions", "agent_chat", "message_id", "agent_chat"))
ORX_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)$"
ORX_NAMES = {x for t, _k, col, parent in ORX_OLD for x in (t, col, parent)}  # the allowlist of qi() (#5296)


def orx_move(c):
    """2.763.0 (#5269): the rows of the old reaction tables into obj_reactions, while those tables are there (the first start
    of 2.763, or again after a version before 2.763 ran and made them anew). Only rows whose target and person still exist;
    a reaction there already stays. The fragment 5269_a drops the old tables right after (one-way). Returns the rows moved."""
    n = 0
    for table, kind, col, parent in ORX_OLD:
        if not c.execute("SELECT to_regclass(?)", (table,)).fetchone()[0]:
            continue
        cq = qi(col, ORX_NAMES)
        # review 2.763: one statement per table (not a round trip per row) inside the start transaction; an old time that is
        # not in the app's ISO form (iso_ms) becomes now instead of failing the cast
        n += c.execute(f"""INSERT INTO obj_reactions(target_kind, target_id, user_id, emoji, created_at)
                           SELECT ?, x.{cq}, x.user_id, x.emoji,
                                  CASE WHEN x.created_at ~ ? THEN x.created_at::timestamptz ELSE now() END
                           FROM {qi(table, ORX_NAMES)} x JOIN {qi(parent, ORX_NAMES)} p ON p.id=x.{cq} JOIN users u ON u.id=x.user_id
                           ON CONFLICT DO NOTHING""", (kind, ORX_ISO)).rowcount
    return n
