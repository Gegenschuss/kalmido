"""2.747.0 (#5249): undo across devices, stage 1 -- the core's undo steps grouped per account (no visible change yet).

Every write of a person that records an undo step (core/writes.py obj_undo_pre: obj_write, office/owrite.py ow_write, the
adapters) adds its copy as a PART of the request's GROUP (table undo_groups, migrations.d/5249_a.py): the first part of a
request opens the group (kept in flask.g), every further part joins it. The header X-Kalmido-Undo-Group: <token> bundles the
parts of several requests: a group of the same person with that token, last touched within UNDO_BUNDLE_S seconds, takes the
next part as well. A group carries its time, area (the request's), device (header X-Kalmido-Device, as sent), label (an i18n
key + its values, undo_label; translated for the reader), state, number of parts and bytes. The editor sessions (header
X-Kalmido-Undo, obj_undo_run) stay as they are: a part of a session is the same obj_undo row, sess set.

States: done (can be undone) | undone (its way forward = redo) | partial (some parts back, some stayed) | noaccess (nothing
of it may be changed by the person now) | barrier (finalised, sent, paid ...: undo_barrier, holds the way back) | toobig
(over UNDO_PART_MAX for one part or UNDO_GROUP_BYTES / UNDO_GROUP_PARTS for the group: listed, no copy, holds the way back).
A new group or barrier ends the way forward of the person's undone groups (as an editor does).

Limits: UNDO_KEEP_D days, UNDO_GROUPS_MAX groups per person (the oldest go when a new one comes, ug_cap), the parts / bytes
above. undo_prune (the watchdog, notify/push.py) takes what is older, over the cap, or a part without its group. Agents never
record steps (obj_is_agent in obj_undo_pre); a barrier of an agent is not written either.

Interface:
  ug_current(c, uid, area, org_id, label) -> the request's group {id, state, parts, bytes} (opened on first use) or None
  ug_fits(c, grp, n) -> bool        may a copy of n bytes join (False: the group became / is toobig, the part counted)
  ug_added(c, grp, n)               a part of n bytes joined
  ug_gids(c, where, args) -> [group ids] of the obj_undo rows matching where (before deleting them)
  ug_gc(c, gids)                    recount those groups, drop the ones left without parts
  ug_drop(c, where, args)           the groups matching where go, with their parts (a session's part stays, unlinked)
  undo_label(c, key, *args)         the label of the request's group (also before its first part)
  undo_barrier(c, uid, area, label_key, args=(), org_id=None) -> id   a barrier row (None for an agent / outside a request)
  undo_prune(c, force=False)        the watchdog's run (hourly)
  undo_count(c) -> {groups, bytes, oldest}   the numbers of GET /api/admin/retention"""
import json
import os
import re
import time
from datetime import timedelta

from flask import g, has_request_context, request

from .access import acx_of
from .db import bump, iso, lv_area, now_utc
from .i18n import N_
from .pg import insert_id, system_ctx

UNDO_KEEP_D = 30  # 30 days, like the trash (#5249)
UNDO_GROUPS_MAX = 300  # groups kept per person
UNDO_PART_MAX = 256 * 1024  # bytes of one part's copy
UNDO_GROUP_BYTES = 2 * 1024 * 1024  # bytes of a group's copies
UNDO_GROUP_PARTS = 1000  # parts of a group (tasks/batch.py BATCH_MAX)
UNDO_BUNDLE_S = 10  # seconds the token of X-Kalmido-Undo-Group keeps a group open
UNDO_GROUP_HDR = "X-Kalmido-Undo-Group"
UNDO_DEVICE_HDR = "X-Kalmido-Device"
UG_STATES = ("done", "undone", "partial", "barrier", "toobig", "noaccess")
UG_HOLD = ("barrier", "toobig")  # rows without copies: never empty, they hold the way back
UG_LABEL = N_("Changed: {0}")
UG_LABEL_PLAIN = N_("Change")
UG_PRUNE = {"at": 0.0}
UG_PRUNE_S = 3600


def _now():
    return iso(now_utc())


def ug_token():
    """The bundling token of the request (X-Kalmido-Undo-Group: 16-64 hex characters) or ""."""
    if not has_request_context():
        return ""
    tok = (request.headers.get(UNDO_GROUP_HDR) or "").strip().lower()
    return tok if re.fullmatch(r"[a-f0-9]{16,64}", tok) else ""


def ug_device():
    """The device name the app sends (X-Kalmido-Device), printable, at most 80 characters; "" without."""
    if not has_request_context():
        return ""
    v = re.sub(r"[\x00-\x1f\x7f]+", " ", request.headers.get(UNDO_DEVICE_HDR) or "").strip()
    return v[:80]


def _agent(c, uid):
    return acx_of(c, uid).role == "agent"


def _q(ids):
    return ",".join("?" * len(ids))


def ug_new_step(c, uid):
    """A new step of uid: the way forward of the undone groups ends (an undone group goes, a partial one keeps the parts
    that stayed). A part that belongs to an editor session too stays there (unlinked)."""
    gids = [r[0] for r in c.execute("SELECT id FROM undo_groups WHERE user_id=? AND state IN ('undone','partial')", (int(uid),)).fetchall()]
    if not gids:
        return
    q = _q(gids)
    c.execute(f"DELETE FROM obj_undo WHERE group_id IN ({q}) AND state='undone' AND sess=''", gids)
    c.execute(f"UPDATE obj_undo SET group_id=NULL WHERE group_id IN ({q}) AND state='undone'", gids)
    c.execute(f"DELETE FROM undo_groups WHERE id IN ({q}) AND state='undone'", gids)
    ug_gc(c, gids)


def ug_drop_ids(c, ids):
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        q = _q(part)
        c.execute(f"DELETE FROM obj_undo WHERE group_id IN ({q}) AND sess=''", part)
        c.execute(f"UPDATE obj_undo SET group_id=NULL WHERE group_id IN ({q})", part)
        c.execute(f"DELETE FROM undo_groups WHERE id IN ({q})", part)


def ug_drop(c, where, args=()):
    """The groups matching where (on undo_groups) go with their parts; a part of an editor session stays there (unlinked)."""
    ug_drop_ids(c, [r[0] for r in c.execute(f"SELECT id FROM undo_groups WHERE {where}", tuple(args)).fetchall()])


def ug_cap(c, uid):
    """At most UNDO_GROUPS_MAX groups per person: the oldest go."""
    old = [r[0] for r in c.execute("SELECT id FROM undo_groups WHERE user_id=? ORDER BY id DESC OFFSET ?", (int(uid), UNDO_GROUPS_MAX)).fetchall()]
    if old:
        ug_drop_ids(c, old)


def _open(c, uid, area, org_id, label, state="done", token=""):
    ug_new_step(c, uid)
    lk, la = label
    ts = _now()
    gid = insert_id(c, "INSERT INTO undo_groups(user_id, org_id, area, label_key, label_args, device, token, state, parts, bytes, "
                       "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,0,0,?,?)",
                    (int(uid), org_id, area or "other", lk, json.dumps(list(la), ensure_ascii=False, default=str), ug_device(), token,
                     state, ts, ts))
    ug_cap(c, uid)
    bump(c, "self")  # the other devices of the person see the list move (GET /api/version, the own "self" counter)
    return gid


def ug_current(c, uid, area, org_id, label):
    """The group of this request for uid: the one already open in g, a bundled one (token within UNDO_BUNDLE_S seconds), or a
    new one. label = (key, [values]) unless undo_label set one. None outside a request."""
    if not has_request_context():
        return None
    cur = g.get("undo_group")
    if cur and cur["uid"] == int(uid):
        return cur
    tok = ug_token()
    row = None
    if tok:
        row = c.execute("SELECT id, state, parts, bytes FROM undo_groups WHERE user_id=? AND token=? AND updated_at>=? ORDER BY id DESC LIMIT 1",
                        (int(uid), tok, iso(now_utc() - timedelta(seconds=UNDO_BUNDLE_S)))).fetchone()
        if row is not None and row["state"] not in ("done", "toobig"):
            row = None  # undone meanwhile: a new step
    if row is None:
        gid = _open(c, uid, area or lv_area(), org_id, g.get("undo_label") or label, token=tok)
        row = {"id": gid, "state": "done", "parts": 0, "bytes": 0}
    cur = {"uid": int(uid), "id": row["id"], "state": row["state"], "parts": int(row["parts"]), "bytes": int(row["bytes"])}
    g.undo_group = cur
    return cur


def _save(c, grp):
    c.execute("UPDATE undo_groups SET state=?, parts=?, bytes=?, updated_at=? WHERE id=?",
              (grp["state"], grp["parts"], grp["bytes"], _now(), grp["id"]))


def ug_fits(c, grp, n):
    """May a copy of n bytes join grp? Over a limit the group becomes toobig: its copies go (a session's part stays, unlinked),
    the row stays with its numbers. A toobig group counts the part and takes no copy."""
    if grp["state"] != "toobig" and n <= UNDO_PART_MAX and grp["bytes"] + n <= UNDO_GROUP_BYTES and grp["parts"] < UNDO_GROUP_PARTS:
        return True
    if grp["state"] != "toobig":
        c.execute("DELETE FROM obj_undo WHERE group_id=? AND sess=''", (grp["id"],))
        c.execute("UPDATE obj_undo SET group_id=NULL WHERE group_id=?", (grp["id"],))
        grp["state"] = "toobig"
    grp["parts"] += 1
    grp["bytes"] += n
    _save(c, grp)
    return False


def ug_added(c, grp, n):
    grp["parts"] += 1
    grp["bytes"] += n
    _save(c, grp)


def ug_gids(c, where, args=()):
    """The groups of the obj_undo rows matching where (read before deleting those rows, then ug_gc)."""
    return [r[0] for r in c.execute(f"SELECT DISTINCT group_id FROM obj_undo WHERE group_id IS NOT NULL AND ({where})", tuple(args)).fetchall()]


def ug_gc(c, gids):
    """Recount the groups gids after parts went; a group left without parts goes (not a barrier / toobig row)."""
    gids = sorted({int(x) for x in gids if x})
    for at in range(0, len(gids), 500):
        part = gids[at:at + 500]
        q = _q(part)
        c.execute(f"UPDATE undo_groups SET parts=(SELECT COUNT(*) FROM obj_undo u WHERE u.group_id=undo_groups.id), "
                  f"bytes=(SELECT COALESCE(SUM(u.bytes), 0) FROM obj_undo u WHERE u.group_id=undo_groups.id) "
                  f"WHERE id IN ({q}) AND state NOT IN ('barrier','toobig')", part)
        c.execute(f"DELETE FROM undo_groups WHERE id IN ({q}) AND parts=0 AND state NOT IN ('barrier','toobig')", part)


def undo_label(c, key, *args):
    """The label of this request's group: an i18n key (N_) and its values (a value that is a list [key, *values] is
    translated too, core/i18n.py tr_stored). Before the first part it waits in g; after it, the open group gets it."""
    if not has_request_context():
        return
    g.undo_label = (key, list(args))
    cur = g.get("undo_group")
    if cur:
        c.execute("UPDATE undo_groups SET label_key=?, label_args=? WHERE id=?",
                  (key, json.dumps(list(args), ensure_ascii=False, default=str), cur["id"]))


def undo_barrier(c, uid, area, label_key, args=(), org_id=None):
    """A barrier of uid (finalised, sent, paid, DATEV, locked ...): a listed row without copies that holds a way back over it
    ("bis hierher" stops there). Ends the way forward like any new step. Returns its id; None for an agent or outside a
    request (nobody to list it for). A write after it in the same request opens a new group."""
    if not has_request_context() or not uid or _agent(c, uid):
        return None
    gid = _open(c, uid, area, org_id, (label_key, list(args)), state="barrier")
    g.undo_group = None
    g.pop("undo_label", None)
    return gid


def undo_prune(c, force=False):
    """The watchdog (system context, at most hourly): groups older than UNDO_KEEP_D days go with their parts, every part
    older too (the editor sessions' as well), the oldest groups of a person over UNDO_GROUPS_MAX, parts whose group is gone,
    groups left without parts. Returns the number of groups removed."""
    every = 20 if os.environ.get("KALMIDO_TEST") == "1" else UG_PRUNE_S  # the test containers: a suite waits for a run
    if not force and time.time() - UG_PRUNE["at"] < every:
        return 0
    UG_PRUNE["at"] = time.time()
    lim = iso(now_utc() - timedelta(days=UNDO_KEEP_D))
    with system_ctx(c):
        c.execute("DELETE FROM obj_undo WHERE group_id IN (SELECT id FROM undo_groups WHERE created_at<?)", (lim,))
        n = c.execute("DELETE FROM undo_groups WHERE created_at<?", (lim,)).rowcount
        c.execute("DELETE FROM obj_undo WHERE created_at<?", (lim,))
        for (uid,) in c.execute("SELECT user_id FROM undo_groups GROUP BY user_id HAVING COUNT(*)>?", (UNDO_GROUPS_MAX,)).fetchall():
            ug_cap(c, uid)
        gone = "group_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM undo_groups x WHERE x.id=obj_undo.group_id)"
        c.execute(f"DELETE FROM obj_undo WHERE {gone} AND sess=''")
        c.execute(f"UPDATE obj_undo SET group_id=NULL WHERE {gone}")
        n += c.execute("DELETE FROM undo_groups WHERE state NOT IN ('barrier','toobig') AND NOT EXISTS "
                       "(SELECT 1 FROM obj_undo u WHERE u.group_id=undo_groups.id)").rowcount
    c.commit()
    return n


def undo_count(c):
    """{groups, bytes (the copies of every undo step, the editor sessions' too), oldest} -- numbers only, no content."""
    with system_ctx(c):
        r = c.execute("SELECT COUNT(*), MIN(created_at) FROM undo_groups").fetchone()
        b = c.execute("SELECT COALESCE(SUM(bytes), 0) FROM obj_undo").fetchone()[0]
    return {"groups": int(r[0] or 0), "bytes": int(b or 0), "oldest": r[1], "keep_days": UNDO_KEEP_D, "max_groups": UNDO_GROUPS_MAX}
