"""2.1076.0 (#5271, stage Q3 of the cross-cutting core, analysis #3563, decided 08.11.2026): links between objects exist once,
in the shared core -- one table obj_links (migrations.d/5271_a.py). It replaced hub_mail_links, life_device_links,
contact_tasks and office_letter_links (paperless_links went with #5265 already).

    obj_links(id, org_id, owner_id, src_kind, src_id, dst_kind, dst_id, rel, note, extra JSONB, created_by, agent_id,
              created_at, rev, updated_at, updated_by, deleted_at, deleted_by)   UNIQUE (src_kind, src_id, dst_kind, dst_id, rel)

    org_id    the workspace of the link (NULL = private: the app checks both sides); row-level security on it
    owner_id  set = a person's own link: only that person reads it (a private device <-> office equipment)
    rel       what the link means: an area's relation (registered with olnk_rel, written only by that area's routes) or a
              free one of people and agents through the generic routes (default 'related')
    extra     what an area keeps on top (a contact link's kind, a device link's origin and office) -- never a title: titles
              are read live from the objects, a link table carries no plain text of a locked object

The area relations of this stage:
    rel        src -> dst                      area (its routes keep their addresses and answers)
    made       hub_mail -> task | event        hub/mailview.py   (a task / an event made from a filed e-mail)
    device     task -> omd_equipment           life/devlink.py   (a private device <-> office equipment, owner_id = the person)
    contact    contact -> task                 contacts/model.py (extra.kind waiting | responsible | about)
    answers    office_letter -> fs_entry       office/letterlinks.py (the letter answers the document)
    reply      office_letter -> fs_entry       office/letterlinks.py (the document answers the letter)

The rules exist once, here:
- E2E lock: no link to or from an object of an end-to-end locked project (olnk_sealed; 409) -- was in every area.
- "Target deleted": a side whose row is gone or in the trash answers state 'gone' (olnk_state), without a title or an address;
  a side the reader may not see is left out (obj_links_of; hidden=True: a placeholder without kind and id). Review 2.1076: a
  side in the trash counts as gone only for who has a role on it (else it is left out too); one deleted for good names its
  kind and id only to the link's creator (olnk_side).
- The workspace of a side is the one of its real row (olnk_org: the space hook, else the row's org_id; a personal office is
  private) -- a file, a knowledge page or a table of an organisation never links into another one.
- Removing a link puts the row into the trash (deleted_at) and records a step of the person's undo list (obj_undo, kind
  obj_link, core/undoweb.py): the person takes it back with the rights of now (an area relation: its hook, olnk_rel). The
  trash run of the core deletes the rows after the trash period (core/objparts.py part_kind trash_prune).
- A link dies with its object: the trigger kalmido_olnk_gone deletes the links of a row deleted for good (5271_a.py).
- Generic links (obj_link): 'write' on the source and 'view' on the target (obj_need), both in the same workspace (or both
  private), never one side twice; an entry in the history of the source.

Interface (c = the connection; the area functions check their rights themselves, like before):
  olnk_kind(kind, table=, role=, title=, url=, space=, sealed=)  a kind outside the core's register (contact, office letter)
  olnk_rel(rel, may)                       an area relation; may(c, uid, row) raises Denied when uid may not take a step back
  olnk_put(c, by, sk, sid, dk, did, rel, org_id=, owner_id=, note=, extra=, agent_id=) -> id   (a link of the trash comes back)
  olnk_drop(c, by, lid, step=True)         into the trash (+ the undo step of a person in a request)
  olnk_find / olnk_rows / olnk_extra         reading / the area's extra
  olnk_purge_ids(c, ids)                   delete for good with their undo steps (an office that moves)
  obj_link / obj_unlink / obj_links_of    the generic API (core/objlinkweb.py: routes, API v1, MCP)
  olnk_move(c)                             the start (core/objhooks.MOVE): the old tables in, before 5271_a drops them
"""
import json
import re

from .access import Denied, live_sql, trash_sql
from .db import iso, now_utc
from .errors import BadInput
from .i18n import N_, tr
from .kernretire import kern_retire_floor
from .objects import OBJ_RANK, obj_need, obj_role, obj_space, obj_title
from .objhooks import MOVE, OBJ, OLNK_AREA_RELS
from .objparts import part_kind
from .pg import insert_id, qi, system_ctx, table_columns, write_lock
from .undoweb import undo_need_reg
from ..files.fsref import FSR, fs_ref_role
from .writes import OBJ_TRACK, obj_history_add, obj_track, obj_undo_post, obj_undo_pre

OLNK_KIND = "obj_link"  # the tracked kind of a link (undo steps, the trash run)
OLNK_TABLE = "obj_links"
OLNK_KIND_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
OLNK_REL_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
OLNK_NOTE_MAX = 500
OLNK_LIST_MAX = 500  # links of one object read at most
OLNK_GENERIC = "related"  # the default relation of the generic routes
OLNK_ISO = r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
OLNK_SEALED_MSG = N_("Not possible in a locked project")
OLNK_SPACE_MSG = N_("Links stay inside one workspace")
OLNK_AREA_MSG = N_("This link belongs to its area: change it there")
OLNK_UNDO_LABEL = N_("Link removed")
OLNK_FLOOR_HOW = ("the shared core moved the links of filed e-mails, devices, contacts and letters into obj_links (#5271) - an "
                 "older version would make the old tables again, empty; go back only with a backup from before")

OLNK_HOOKS = {}  # kind -> hooks of a kind outside the core's register (olnk_kind)
OLNK_RELS = {}   # rel -> {"may": fn(c, uid, row)} of an area relation (olnk_rel)


def olnk_kind(kind, *, table, role=None, title=None, url=None, space=None, sealed=None):
    """A kind the core's register does not know (yet) that areas link: table = its rows (id, deleted_at if it has a trash).
    Without hooks the file store's reference kind of the same name answers (files/fsref.py: fs_ref_role, its space, title
    and open_url -- 'contact', 'office_letter'); role(c, uid, id) -> None | 'view' | 'edit' | 'manage', title(c, id) -> text,
    url(id) -> the app's address, space(c, id) -> (org_id | None, owner_id) | None, sealed(c, id) -> bool replace them."""
    if not OLNK_KIND_RE.fullmatch(kind):
        raise ValueError(kind)
    OLNK_HOOKS[kind] = {"table": table, "role": role, "title": title, "url": url, "space": space, "sealed": sealed}


def olnk_rel(rel, may):
    """An area relation: written / removed only by the area's routes (the generic ones refuse it with 409);
    may(c, uid, row) raises Denied when uid may not take a removal of it back now (the person's undo list)."""
    if not OLNK_REL_RE.fullmatch(rel) or rel not in OLNK_AREA_RELS:  # review 2.1076: the one list (core/objhooks.py)
        raise ValueError(rel)
    OLNK_RELS[rel] = {"may": may}


def _now():
    return iso(now_utc())


def _kind(kind):
    if not isinstance(kind, str) or not OLNK_KIND_RE.fullmatch(kind):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    return kind


def _id(v, name="id"):
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None
    if not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", name))
    return v


def _table(kind):
    h = OLNK_HOOKS.get(kind)
    if h:
        return h["table"]
    reg = OBJ.get(kind)
    return reg["table"] if reg else None


# ---------------------------------------------------------------- the two sides
def olnk_role(c, uid, kind, rid):
    """The reader's role on one side: the area's hook (olnk_kind) or the core's obj_role; None for an unknown kind."""
    h = OLNK_HOOKS.get(kind)
    if h:
        try:
            r = h["role"](c, uid, int(rid)) if h["role"] else fs_ref_role(c, uid, kind, int(rid)) if kind in FSR else None
        except Denied:
            return None
        return r if r in OBJ_RANK and r else None
    if kind in OBJ:
        return obj_role(c, uid, kind, rid)
    return None


def olnk_state(c, kind, rid):
    """'ok' | 'gone' -- THE answer "target deleted": its row is gone (or the kind unknown) or in the trash. Read as the
    system (row-level security would make an object of another organisation look gone; the reader's role decides after)."""
    t = _table(kind)
    if not t:
        return "gone"
    cols = table_columns(c, t)
    if not cols:
        return "gone"
    with system_ctx(c):  # deleted or not, whichever organisation it belongs to (the reader's role decides after)
        r = c.execute(f"SELECT {'deleted_at' if 'deleted_at' in cols else 'NULL AS deleted_at'} FROM {qi(t, {t})} WHERE id=?", (int(rid),)).fetchone()
    return "gone" if r is None or r[0] else "ok"


def olnk_title(c, kind, rid):
    h = OLNK_HOOKS.get(kind)
    if h:
        f = h["title"] or (FSR.get(kind) or {}).get("title")
        return (f(c, int(rid)) if f else "") or ""
    return obj_title(c, kind, rid) if kind in OBJ else ""


def olnk_url(kind, rid):
    h = OLNK_HOOKS.get(kind)
    if h:
        f = h["url"] or (FSR.get(kind) or {}).get("open_url")
        return f(int(rid)) if f else ""
    reg = OBJ.get(kind)
    return reg["open_url"](int(rid)) if reg and reg.get("open_url") else ""


def olnk_space(c, kind, rid):
    h = OLNK_HOOKS.get(kind)
    if h:
        f = h["space"] or (FSR.get(kind) or {}).get("space")
        return f(c, int(rid)) if f else None
    return obj_space(c, kind, rid) if kind in OBJ else None


def olnk_org(c, kind, rid):
    """Review 2.1076 (#5271): THE workspace of one side for the boundary of the links -> org_id | None (private); Denied(404)
    when the object does not exist. The kind's space hook when it names an organisation; else the organisation column of its
    own row -- the hooks of files, knowledge pages and tables answer (None, None) also for an organisation's row. A personal
    office (orgs.personal_of) counts as private, as its space hook says (office/okern.py, hub/dspkern.py)."""
    sp = olnk_space(c, kind, rid)
    if not sp:
        raise Denied(404)
    if sp[0] or sp[1] is not None:  # an organisation, or a private object with its owner: the hook knows
        return sp[0] or None
    t = _table(kind)
    if not t or "org_id" not in table_columns(c, t):
        return None
    with system_ctx(c):  # the organisation row itself (a person reads orgs only of her memberships); uid's role was checked
        r = c.execute(f"SELECT o.id, o.personal_of FROM {qi(t, {t})} x JOIN orgs o ON o.id=x.org_id WHERE x.id=?", (int(rid),)).fetchone()
    return r["id"] if r is not None and r["personal_of"] is None else None


def olnk_sealed(c, kind, rid):
    """THE E2E lock of links: an object of an end-to-end locked project (a task: its project's lock; another kind: its hook)."""
    h = OLNK_HOOKS.get(kind)
    if h and h["sealed"]:
        return bool(h["sealed"](c, int(rid)))
    if kind == "task":
        with system_ctx(c):  # the lock of the task's project, whoever asks
            r = c.execute("SELECT l.e2e FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (int(rid),)).fetchone()
        return bool(r and r[0])
    return False


def olnk_seal_check(c, *sides):
    for kind, rid in sides:
        if olnk_sealed(c, kind, rid):
            raise Denied(409, tr(OLNK_SEALED_MSG))


# ---------------------------------------------------------------- rows
def olnk_row(c, lid, trash=False):
    if not isinstance(lid, int) or not 0 < lid < 2 ** 62:
        return None
    return c.execute(f"SELECT * FROM obj_links WHERE id=? AND {trash_sql() if trash else live_sql()}", (lid,)).fetchone()


def olnk_find(c, src_kind, src_id, dst_kind=None, dst_id=None, rel=None, owner=None):
    """The live links from (src_kind, src_id), narrowed by target / relation / owner (owner: that person's own links)."""
    where, args = ["src_kind=?", "src_id=?", live_sql()], [src_kind, int(src_id)]
    for col, v in (("dst_kind", dst_kind), ("dst_id", dst_id), ("rel", rel), ("owner_id", owner)):
        if v is not None:
            where.append(f"{col}=?")
            args.append(v)
    return c.execute(f"SELECT * FROM obj_links WHERE {' AND '.join(where)} ORDER BY id", args).fetchall()


def olnk_rows(c, kind, rid, side="both", rel=None, owner=None):
    """The live links of one object: side 'src' (from it), 'dst' (to it) or 'both'; rel: a relation or a tuple of them;
    owner: a person's own links of that person (and every link without an owner), else only links without an owner."""
    sides = {"src": "(src_kind=? AND src_id=?)", "dst": "(dst_kind=? AND dst_id=?)"}
    parts = [sides[s] for s in (("src", "dst") if side == "both" else (side,))]
    args = [x for _ in parts for x in (kind, int(rid))]
    where = f"({' OR '.join(parts)}) AND {live_sql()}"
    if rel is not None:
        rels = (rel,) if isinstance(rel, str) else tuple(rel)
        where += f" AND rel IN ({','.join('?' * len(rels))})"
        args += list(rels)
    where += " AND (owner_id IS NULL OR owner_id=?)" if owner is not None else " AND owner_id IS NULL"
    if owner is not None:
        args.append(int(owner))
    return c.execute(f"SELECT * FROM obj_links WHERE {where} ORDER BY id LIMIT {OLNK_LIST_MAX}", args).fetchall()


def olnk_extra(r):
    """The area's extra of a row as a dict."""
    v = r["extra"] if r is not None and "extra" in r.keys() else None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    return v if isinstance(v, dict) else {}


def olnk_set_extra(c, by, lid, extra):
    c.execute("UPDATE obj_links SET extra=CAST(? AS JSONB), rev=rev+1, updated_at=?, updated_by=? WHERE id=?",
              (json.dumps(extra or {}), _now(), by, int(lid)))


def _hist(c, by, kind, rid, action, other, org_id):
    """An entry in the history of a side that keeps one (a kind of the core or a tracked kind)."""
    if kind not in OBJ and kind not in OBJ_TRACK:
        return
    try:
        obj_history_add(c, by, kind, rid, {}, {"link": other}, action=action, org_id=org_id)
    except Denied:
        pass


def olnk_put(c, by, src_kind, src_id, dst_kind, dst_id, rel, *, org_id=None, owner_id=None, note="", extra=None, agent_id=None,
            created_at=None, history=True):
    """The link (src -> dst, rel) -> its id. The caller checked the rights of both sides (an area: its own rules); the E2E
    lock is checked here. A live one is returned as it is; one in the trash comes back as the new link (one row per key).
    No commit."""
    src_kind, dst_kind = _kind(src_kind), _kind(dst_kind)
    src_id, dst_id = _id(src_id, "src_id"), _id(dst_id, "dst_id")
    if not OLNK_REL_RE.fullmatch(rel or ""):
        raise BadInput(tr("Invalid value: {0}", "rel"))
    if (src_kind, src_id) == (dst_kind, dst_id):
        raise BadInput(tr("Invalid value: {0}", "id"))
    olnk_seal_check(c, (src_kind, src_id), (dst_kind, dst_id))
    write_lock(c, f"olnk-{src_kind}-{src_id}")
    ts = created_at or _now()
    ex = json.dumps(extra or {})
    r = c.execute("SELECT id, deleted_at FROM obj_links WHERE src_kind=? AND src_id=? AND dst_kind=? AND dst_id=? AND rel=?",
                  (src_kind, src_id, dst_kind, dst_id, rel)).fetchone()
    if r is not None and not r["deleted_at"]:
        return r["id"]
    if r is not None:  # the row of the trash is the new link
        c.execute("UPDATE obj_links SET deleted_at=NULL, deleted_by=NULL, rev=rev+1, org_id=?, owner_id=?, note=?, extra=CAST(? AS JSONB), "
                  "created_by=?, agent_id=?, created_at=?, updated_at=NULL, updated_by=NULL WHERE id=?",
                  (org_id, owner_id, note or "", ex, by, agent_id, ts, r["id"]))
        lid = r["id"]
    else:
        lid = insert_id(c, "INSERT INTO obj_links(org_id, owner_id, src_kind, src_id, dst_kind, dst_id, rel, note, extra, created_by, agent_id, "
                           "created_at) VALUES(?,?,?,?,?,?,?,?,CAST(? AS JSONB),?,?,?)",
                        (org_id, owner_id, src_kind, src_id, dst_kind, dst_id, rel, note or "", ex, by, agent_id, ts))
    if history and by:
        _hist(c, by, src_kind, src_id, "link", f"{rel}:{dst_kind}", org_id)  # review 2.1076: no id of the other side
    return lid


def olnk_drop(c, by, lid, step=True, history=True):
    """Link lid into the trash; step: the undo step of a person in a request (core/writes.py obj_undo_pre / _post, kind
    obj_link: taking it back brings the row out of the trash). 404 when it is not live. No commit."""
    r = olnk_row(c, int(lid))
    if r is None:
        raise Denied(404)
    write_lock(c, f"olnk-{r['src_kind']}-{r['src_id']}")
    if step and by:
        obj_undo_pre(c, by, OLNK_KIND, r["id"])
    ts = _now()
    c.execute("UPDATE obj_links SET deleted_at=?, deleted_by=?, rev=rev+1, updated_at=?, updated_by=? WHERE id=?", (ts, by, ts, by, r["id"]))
    if step and by:
        obj_undo_post(c)  # the state after this step at once: several links removed in one request are several steps
    if history and by:
        _hist(c, by, r["src_kind"], r["src_id"], "unlink", f"{r['rel']}:{r['dst_kind']}", r["org_id"])
    return r


def olnk_purge_ids(c, ids):
    """Delete links ids for good with their undo steps and history (an area's own way out: a moving office; its rows of the
    trash too).
    Returns the number of rows deleted."""
    from .undogroups import ug_gc
    ids = sorted({int(x) for x in ids or () if x})
    n = 0
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        gids = [r[0] for r in c.execute("SELECT DISTINCT group_id FROM obj_undo WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[])) "
                                        "AND group_id IS NOT NULL", (OLNK_KIND, part)).fetchall()]
        c.execute("DELETE FROM obj_undo WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (OLNK_KIND, part))
        c.execute("DELETE FROM obj_history WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (OLNK_KIND, part))  # an undo's entry
        ug_gc(c, gids)
        n += c.execute("DELETE FROM obj_links WHERE id = ANY(CAST(? AS BIGINT[]))", (part,)).rowcount
    return n


# ---------------------------------------------------------------- the generic API (people and agents)
def _generic_rel(rel):
    rel = OLNK_GENERIC if rel in (None, "") else rel
    if not isinstance(rel, str) or not OLNK_REL_RE.fullmatch(rel):
        raise BadInput(tr("Invalid value: {0}", "rel"))
    if rel in OLNK_RELS:
        raise Denied(409, tr(OLNK_AREA_MSG))
    return rel


def _note(v):
    if v in (None, ""):
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    v = " ".join(v.split())
    if len(v) > OLNK_NOTE_MAX:
        raise BadInput(tr("Invalid value: {0}", "note"))
    return v


def _pair_need(c, uid, src_kind, src_id, dst_kind, dst_id):
    """'write' on the source, 'view' on the target (the core's roles), the same workspace (or both private)."""
    if src_kind not in OBJ or dst_kind not in OBJ:
        raise Denied(404)
    obj_need(c, uid, src_kind, src_id, "write")
    obj_need(c, uid, dst_kind, dst_id, "view")
    a = olnk_org(c, src_kind, src_id)  # review 2.1076: the workspace of the real row (a file's / a page's org_id)
    if a != olnk_org(c, dst_kind, dst_id):
        raise Denied(409, tr(OLNK_SPACE_MSG))
    return a


def obj_link(c, uid, src_kind, src_id, dst_kind, dst_id, rel=None, note=None, agent_id=None):
    """A generic link of a person or an agent (module docstring) -> its id. No commit."""
    src_kind, dst_kind = _kind(src_kind), _kind(dst_kind)
    src_id, dst_id = _id(src_id, "id"), _id(dst_id, "id")
    rel, note = _generic_rel(rel), _note(note)
    if (src_kind, src_id) == (dst_kind, dst_id):
        raise BadInput(tr("Invalid value: {0}", "id"))
    org = _pair_need(c, uid, src_kind, src_id, dst_kind, dst_id)
    return olnk_put(c, uid, src_kind, src_id, dst_kind, dst_id, rel, org_id=org, note=note, agent_id=agent_id)


def obj_unlink(c, uid, lid, kind=None, rid=None):
    """A generic link into the trash ('write' on its source; an area relation: 409, its area removes it). kind / rid: the
    object the route came through (the link must hang on it). No commit."""
    r = olnk_row(c, lid) if isinstance(lid, int) else None
    if r is None or r["owner_id"] is not None:
        raise Denied(404)
    if kind is not None and (kind, int(rid)) not in ((r["src_kind"], r["src_id"]), (r["dst_kind"], r["dst_id"])):
        raise Denied(404)
    if not olnk_role(c, uid, r["src_kind"], r["src_id"]):  # who does not see its source learns nothing of the link (404)
        raise Denied(404)
    if r["rel"] in OLNK_RELS:
        raise Denied(409, tr(OLNK_AREA_MSG))
    if r["src_kind"] not in OBJ:
        raise Denied(404)
    obj_need(c, uid, r["src_kind"], r["src_id"], "write")
    return olnk_drop(c, uid, r["id"])


def olnk_side(c, uid, kind, rid, hidden=False, by=None):
    """One side as a reader sees it: {kind, id, state: ok, title, open_url} | {kind, id, state: gone} | None (not visible;
    hidden=True: {state: hidden} without kind and id). Review 2.1076: a side in the trash only for who has a role on it
    (else left out like one not visible); a side deleted for good answers {state: gone} -- its kind and id only to the
    link's creator (by), who named it."""
    t = _table(kind)
    cols = table_columns(c, t) if t else ()
    if cols:
        with system_ctx(c):  # does the row exist at all (row-level security would hide another organisation's)
            there = c.execute(f"SELECT 1 FROM {qi(t, {t})} WHERE id=?", (int(rid),)).fetchone() is not None
    else:
        there = False
    if not there:
        mine = by is not None and uid is not None and int(by) == int(uid)
        return {"kind": kind, "id": int(rid), "state": "gone"} if mine else {"state": "gone"}
    if not olnk_role(c, uid, kind, rid):
        return {"state": "hidden"} if hidden else None
    if olnk_state(c, kind, rid) == "gone":  # in the trash, and the reader has a role on it
        return {"kind": kind, "id": int(rid), "state": "gone"}
    return {"kind": kind, "id": int(rid), "state": "ok", "title": olnk_title(c, kind, rid), "open_url": olnk_url(kind, rid)}


def obj_links_of(c, uid, kind, rid, rel=None, hidden=False):
    """The links of object (kind, rid) for reader uid (the caller checked that uid sees the object): [{id, rel, note, dir:
    out | in, other: olnk_side, created_at, created_by, agent}] -- the other side 'ok' with title and address, 'gone' once
    deleted or in the trash, left out when uid may not see it (hidden=True: a placeholder). A person's own link only for
    that person."""
    out = []
    for r in olnk_rows(c, kind, rid, rel=rel, owner=uid):
        mine = r["src_kind"] == kind and r["src_id"] == int(rid)
        ok, oid = (r["dst_kind"], r["dst_id"]) if mine else (r["src_kind"], r["src_id"])
        side = olnk_side(c, uid, ok, oid, hidden=hidden, by=r["created_by"])
        if side is None:
            continue
        out.append({"id": r["id"], "rel": r["rel"], "note": r["note"] or "", "dir": "out" if mine else "in", "other": side,
                    "created_at": r["created_at"], "created_by": r["created_by"], "agent": bool(r["agent_id"])})
    return out


# ---------------------------------------------------------------- undo of a removal (core/undoweb.py) and the trash run
def _undo_label(row):
    return OLNK_UNDO_LABEL, []


obj_track(OLNK_KIND, OLNK_TABLE, area="other", undo_label=_undo_label, undo_free=("deleted_at", "deleted_by"),
          undo_keep={OLNK_TABLE: {"created_by", "agent_id", "created_at", "extra"}})
part_kind(OLNK_KIND, OLNK_TABLE, lock="olnk-link-{id}", live=live_sql(), trash_prune=True)


def _olnk_undo_need(c, uid, rid, oid):
    """Who may take a removal (or its redo) back now: a person's own link only its person; an area relation its area's
    hook; a generic one 'write' on the source and 'view' on the target as for linking."""
    r = c.execute("SELECT * FROM obj_links WHERE id=?", (int(rid),)).fetchone()
    if r is None or (r["owner_id"] is not None and int(r["owner_id"]) != int(uid)):
        raise Denied(404)
    olnk_seal_check(c, (r["src_kind"], r["src_id"]), (r["dst_kind"], r["dst_id"]))
    hook = OLNK_RELS.get(r["rel"])
    if hook:
        hook["may"](c, uid, r)
    else:
        _pair_need(c, uid, r["src_kind"], r["src_id"], r["dst_kind"], r["dst_id"])
    return {"lock": f"olnk-{r['src_kind']}-{r['src_id']}"}


undo_need_reg(OLNK_KIND, _olnk_undo_need)


# ---------------------------------------------------------------- the move of the old tables (start, once per table)
def _ts(cols, col, alias="o", now=False):
    """An old TEXT point in time as TIMESTAMPTZ (NULL / '' / not ISO / column missing -> now when it lands in a NOT NULL
    target (now=True: obj_links.created_at, whatever the old column's name), else NULL). #5916: the fallback follows the
    target column, not the source name -- contact_tasks.added_at '' gave NULL in created_at and the start broke off."""
    fb = "CURRENT_TIMESTAMP" if now else "NULL"
    if col not in cols:
        return fb
    return (f"CASE WHEN CAST({alias}.{col} AS TEXT) ~ '{OLNK_ISO}' THEN CAST(CAST({alias}.{col} AS TEXT) AS TIMESTAMPTZ) "
            f"ELSE {fb} END")


def olnk_move(c):
    """2.1076.0 (#5271): the rows of the four old link tables into obj_links while those tables are there (the first start of
    2.1076, or again after an older version ran and made them anew); the fragment 5271_a drops them right after (one-way).
    Rows whose other side is gone already (a device link without its device or equipment) do not move. The undo copies and
    the history of the office's letter-link kind (oletlink) go: their rows are gone. Returns {table: rows moved}."""
    out = {}
    t = "hub_mail_links"
    if c.execute(f"SELECT to_regclass('{t}')").fetchone()[0]:
        cols = table_columns(c, t)
        out[t] = c.execute(f"""INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by, created_at)
                               SELECT o.org_id, 'hub_mail', o.mail_id, o.kind, o.ref_id, 'made', o.created_by, {_ts(cols, 'created_at', now=True)}
                               FROM {qi(t, {t})} o WHERE o.kind IN ('task', 'event') ORDER BY o.id
                               ON CONFLICT (src_kind, src_id, dst_kind, dst_id, rel) DO NOTHING""").rowcount
    t = "life_device_links"
    if c.execute(f"SELECT to_regclass('{t}')").fetchone()[0]:
        cols = table_columns(c, t)
        out[t] = c.execute(f"""INSERT INTO obj_links(owner_id, src_kind, src_id, dst_kind, dst_id, rel, extra, created_by, created_at,
                                                    updated_at)
                               SELECT o.user_id, 'task', o.task_id, 'omd_equipment', o.equipment_id, 'device',
                                      jsonb_build_object('origin', COALESCE(o.origin, 'device'), 'office_id', o.office_id),
                                      o.user_id, {_ts(cols, 'created_at', now=True)}, {_ts(cols, 'updated_at')}
                               FROM {qi(t, {t})} o WHERE o.task_id IS NOT NULL AND o.equipment_id IS NOT NULL ORDER BY o.id
                               ON CONFLICT (src_kind, src_id, dst_kind, dst_id, rel) DO NOTHING""").rowcount
    t = "contact_tasks"
    if c.execute(f"SELECT to_regclass('{t}')").fetchone()[0]:
        cols = table_columns(c, t)
        out[t] = c.execute(f"""INSERT INTO obj_links(src_kind, src_id, dst_kind, dst_id, rel, extra, created_by, created_at)
                               SELECT 'contact', o.contact_id, 'task', o.task_id, 'contact',
                                      jsonb_build_object('kind', COALESCE(o.kind, 'about')), o.added_by, {_ts(cols, 'added_at', now=True)}
                               FROM {qi(t, {t})} o ORDER BY o.added_at, o.contact_id, o.task_id
                               ON CONFLICT (src_kind, src_id, dst_kind, dst_id, rel) DO NOTHING""").rowcount
    t = "office_letter_links"
    if c.execute(f"SELECT to_regclass('{t}')").fetchone()[0]:
        cols = table_columns(c, t)
        trash = [f"o.{x}" if x in cols else "NULL" for x in ("deleted_at", "deleted_by", "updated_at", "updated_by")]
        out[t] = c.execute(f"""INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by, agent_id, created_at,
                                                    deleted_at, deleted_by, updated_at, updated_by)
                               SELECT o.org_id, 'office_letter', o.letter_id, 'fs_entry', o.node_id, o.kind, o.created_by,
                                      {'o.agent_id' if 'agent_id' in cols else 'NULL'}, {_ts(cols, 'created_at', now=True)}, {', '.join(trash)}
                               FROM {qi(t, {t})} o WHERE o.kind IN ('answers', 'reply') ORDER BY o.id
                               ON CONFLICT (src_kind, src_id, dst_kind, dst_id, rel) DO NOTHING""").rowcount
        from .undogroups import ug_gc
        gids = [r[0] for r in c.execute("SELECT DISTINCT group_id FROM obj_undo WHERE kind='oletlink' AND group_id IS NOT NULL").fetchall()]
        c.execute("DELETE FROM obj_undo WHERE kind='oletlink'")
        ug_gc(c, gids)
        c.execute("DELETE FROM obj_history WHERE kind='oletlink'")
    if out:
        print("obj_links: moved", ", ".join(f"{k} {v}" for k, v in out.items()), flush=True)
        kern_retire_floor(c, how=OLNK_FLOOR_HOW)
    return out


MOVE.append(olnk_move)  # core/db.py init_db, before the fragments' AFTER (core/objhooks.py)
