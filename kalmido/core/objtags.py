"""2.925.0 (#5275, stage Q5a of the cross-cutting core, analysis #3563, decided 08.11.2026): tags exist once, in the shared core.

obj_tags (migrations.d/5275_a.py) is one tag of a scope, obj_tag_links puts it on an object:

    scope_kind  scope_id                 who sees / manages it
    list        the project's id         a project tag: everyone in the project sees it, editors manage it (collab/reactions.py)
    org         the organisation's id    a label of the organisation: the same in every project of it, its admins manage it
                                         (lists/orglabels.py); org_id is set, so row-level security shows it to members only
    user        the person's id          stage Q5b (task_tags), not moved yet
    ws          the workspace key        stage Q5c (doc_tags), not moved yet

A task carries the tags of its project's scopes: the project's own tags and the labels of the project's organisation, each
linked to the task itself (decided 08.11.2026, question 9: a label is put on the task directly, no copy per project any more).
A link to a tag of another scope (the task moved, the project left its organisation) is not shown and not counted
(otg_scope_sql), as the old join on the task's list did.

Rights stay with the areas, as before: the project (need_list / need_task, WRITE_ROLES for a new project tag) and the
organisation's admins for labels (orglabels.olb_admin); the core functions here check nothing themselves -- their callers
did. An agent only reaches tags through a project shared with it (the area's checks), a label only as a member (row-level
security) and never manages labels (orglabels.olb_need_person).

End-to-end locked projects (decided 08.11.2026, question 10): the names of project tags and labels stay plain text in the
database, also on a task of a locked project -- the server filters, counts and renames them. This is deliberate and differs
from the knowledge pages (wiki/wktags.py keeps only a hash of a #word): a tag name is a word of the project's vocabulary, not
the content of a task. tests/p2925_c_tags_core_test.py holds this.
"""
import re

from .db import now_utc
from .pg import insert_id

OTG_SCOPES = ("user", "list", "org", "ws")
OTG_PROJECT = ("list", "org")  # the scopes a task's project gives it (this stage)
OTG_SRC = ("person", "agent", "auto")
OTG_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)$"


def otg_scope_sql(tag="ot", task="t", lst="l"):
    """SQL: tag alias `tag` belongs to the project of task alias `task` (list alias `lst` = that task's list): a tag of the
    project itself or a label of the project's organisation."""
    return (f"(({tag}.scope_kind='list' AND {tag}.scope_id=CAST({task}.list_id AS TEXT)) OR "
            f"({tag}.scope_kind='org' AND {tag}.scope_id=CAST({lst}.org_id AS TEXT)))")


def otg_list_sql(tag="ot", lst="l", full=True):
    """SQL: tag alias `tag` is one a task of list alias `lst` may carry (the list's own tags, its organisation's labels).
    full: True = every label of the organisation (the server's own work, a person with the organisation's full view); else the
    ids of the organisations the reader fully sees (lists/orglabels.py olb_full) -- a label of another organisation of a list
    (a guest / accounting person in a shared project) only when a task of that list carries it already (review F4, as
    olb_match since #3373 review F3: the labels' names are no oracle)."""
    lab = f"{tag}.scope_kind='org' AND {tag}.scope_id=CAST({lst}.org_id AS TEXT)"
    if full is not True:
        ids = ",".join(str(int(x)) for x in full or ()) or "NULL"
        lab += (f" AND ({lst}.org_id IN ({ids}) OR EXISTS (SELECT 1 FROM obj_tag_links kv JOIN tasks tv ON tv.id=kv.obj_id AND kv.kind='task' "
                f"WHERE kv.tag_id={tag}.id AND tv.list_id={lst}.id))")
    return f"(({tag}.scope_kind='list' AND {tag}.scope_id=CAST({lst}.id AS TEXT)) OR ({lab}))"


# the FROM part: the project tags on tasks (k = link, ot = tag, t = task, l = its list); WHERE part: otg_scope_sql()
OTG_TASK_FROM = ("FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id JOIN tasks t ON t.id=k.obj_id AND k.kind='task' "
                 "JOIN lists l ON l.id=t.list_id")
OTG_ORDER = "(ot.scope_kind<>'list'), ot.sort, lower(ot.name), ot.id"


def obj_tag_sql(col="tasks.id", by="name"):
    """The filter part of the core: SQL that holds when the task in column `col` carries a project tag (one `?` argument):
    by='name' (any case), 'names' (a lower-case text array), 'id' (the tag's id); by='any': any project tag (no argument).
    Used by the filters, the data lock, the shared views and API v1."""
    cond = {"name": "AND lower(ot.name)=lower(?)", "names": "AND lower(ot.name) = ANY(CAST(? AS TEXT[]))",
            "id": "AND ot.id=?", "any": ""}[by]
    return (f"EXISTS (SELECT 1 FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id JOIN tasks tt ON tt.id=k.obj_id "
            f"JOIN lists ll ON ll.id=tt.list_id WHERE k.kind='task' AND k.obj_id={col} AND {otg_scope_sql('ot', 'tt', 'll')} {cond})")


def obj_tags_of(c, ids):
    """{task id: [{id, name, color, scope_kind, org_tag_id}]} -- the project tags of the tasks ids (their project's own tags
    and its organisation's labels), in the order of the project; org_tag_id = the label's id for a label (the app's mark)."""
    out, ids = {}, sorted({int(x) for x in ids if x})
    if not ids:
        return out
    for r in c.execute(f"""SELECT k.obj_id, ot.id, ot.name, ot.color, ot.scope_kind {OTG_TASK_FROM}
                           WHERE k.obj_id = ANY(CAST(? AS BIGINT[])) AND {otg_scope_sql()} ORDER BY {OTG_ORDER}""", (ids,)):
        out.setdefault(r[0], []).append({"id": r[1], "name": r[2], "color": r[3], "scope_kind": r[4],
                                         "org_tag_id": r[1] if r[4] == "org" else None})
    return out


def otg_task_ids(c, tid):
    """The ids of the project tags task tid carries now."""
    return {r[0] for r in c.execute(f"SELECT ot.id {OTG_TASK_FROM} WHERE k.obj_id=? AND {otg_scope_sql()}", (tid,))}


def otg_of_list(c, lid):
    """(project scope, organisation scope) of list lid: [('list', '5'), ('org', '3')] (no organisation: the first only)."""
    r = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
    out = [("list", str(int(lid)))]
    if r and r[0]:
        out.append(("org", str(int(r[0]))))
    return out


def otg_in_list(c, tag_id, lid, full=True):
    """The tag row when tag tag_id is one the tasks of list lid may carry (the list's own or its organisation's), else None.
    full: as otg_list_sql (a reader's check: the organisations they fully see)."""
    try:
        tag_id = int(tag_id)
    except (TypeError, ValueError):
        return None
    return c.execute(f"SELECT ot.* FROM obj_tags ot JOIN lists l ON l.id=? WHERE ot.id=? AND {otg_list_sql(full=full)}",
                     (lid, tag_id)).fetchone()


def otg_find(c, scope_kind, scope_id, name):
    return c.execute("SELECT * FROM obj_tags WHERE scope_kind=? AND scope_id=? AND lower(name)=lower(?)",
                     (scope_kind, str(scope_id), name)).fetchone()


def otg_count(c, scope_kind, scope_id):
    return c.execute("SELECT COUNT(*) FROM obj_tags WHERE scope_kind=? AND scope_id=?", (scope_kind, str(scope_id))).fetchone()[0]


def otg_add(c, scope_kind, scope_id, name, color="", by=None, sort=None):
    """A new tag of the scope (the caller checked the name, the rights and that the name is free); its sort = after the
    scope's last one. The id. An organisation's label carries org_id (row-level security)."""
    if scope_kind not in OTG_SCOPES:
        raise ValueError(f"otg_add: unknown scope {scope_kind!r}")
    if sort is None:
        sort = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM obj_tags WHERE scope_kind=? AND scope_id=?",
                         (scope_kind, str(scope_id))).fetchone()[0]
    return insert_id(c, "INSERT INTO obj_tags(scope_kind,scope_id,org_id,name,color,sort,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (scope_kind, str(scope_id), int(scope_id) if scope_kind == "org" else None, name, color or "", sort, by, now_utc()))


def otg_link(c, tag_id, oid, kind="task", src="person", by=None):
    c.execute("INSERT INTO obj_tag_links(tag_id,kind,obj_id,src,created_by,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
              (tag_id, kind, oid, src if src in OTG_SRC else "person", by, now_utc()))


def obj_tags_set(c, oid, tag_ids, kind="task", scopes=OTG_PROJECT, src="person", by=None):
    """The tags of object oid among the scope kinds `scopes` become exactly tag_ids (a link already there keeps its time and
    who set it). Links to tags of other scope kinds stay; a tag the reader cannot see (another organisation's label: row-level
    security) is neither read nor removed."""
    want = list(dict.fromkeys(int(x) for x in tag_ids))
    c.execute("""DELETE FROM obj_tag_links WHERE kind=? AND obj_id=? AND NOT (tag_id = ANY(CAST(? AS BIGINT[])))
                 AND EXISTS (SELECT 1 FROM obj_tags ot WHERE ot.id=obj_tag_links.tag_id AND ot.scope_kind = ANY(CAST(? AS TEXT[])))""",
              (kind, oid, want, list(scopes)))
    for i in want:
        otg_link(c, i, oid, kind, src, by)


def otg_merge(c, from_id, into_id):
    """Tag from_id becomes tag into_id: its links move over (an object that has both keeps one), the rules / shared views that
    named it name into_id, then it goes. from_id is a project tag: only its project's rules / shared views can name it."""
    r = c.execute("SELECT scope_kind, scope_id FROM obj_tags WHERE id=?", (from_id,)).fetchone()
    if r and r["scope_kind"] == "list":
        otg_rekey_refs(c, {int(from_id): int(into_id)}, int(r["scope_id"]))
    c.execute("""INSERT INTO obj_tag_links(tag_id,kind,obj_id,src,created_by,created_at)
                 SELECT ?, kind, obj_id, src, created_by, created_at FROM obj_tag_links WHERE tag_id=? ON CONFLICT DO NOTHING""",
              (into_id, from_id))
    c.execute("DELETE FROM obj_tags WHERE id=?", (from_id,))


# A project that leaves its organisation (any way lists.org_id changes, or the organisation is deleted) keeps the labels on its
# tasks as project tags, and one that joins an organisation gives a project tag named like a label to that label: the trigger
# kalmido_otg_org_moved of migrations.d/5275_a.py (review F1 / F6), so no caller can forget it.


# the triggers of the functions in migrations.d/5275_a.py; core/db.py init_db makes them after mig_apply (lists.org_id is a
# MIGRATIONS step: a fresh database has no such column while the fragments' SCHEMA runs, review N1)
OTG_ORG_TRIGGERS = """
CREATE OR REPLACE TRIGGER kalmido_otg_org_list AFTER UPDATE OF org_id ON lists FOR EACH ROW EXECUTE FUNCTION kalmido_otg_org_moved();
CREATE OR REPLACE TRIGGER kalmido_otg_org_gone BEFORE DELETE ON orgs FOR EACH ROW EXECUTE FUNCTION kalmido_otg_org_moved();
"""


# ---------------------------------------------------------------- the move (init_db, every start while the old tables exist)
OTG_OLD = ("list_tags", "task_list_tags", "org_tags")
# 2.36 SQLite files have project tags: admin/migrate.py makes these two tables for the copy, otg_move takes them over after it
OTG_LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS list_tags (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS list_tags_name ON list_tags(list_id, lower(name));
CREATE TABLE IF NOT EXISTS task_list_tags (
  task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  tag_id BIGINT NOT NULL REFERENCES list_tags(id) ON DELETE CASCADE, PRIMARY KEY (task_id, tag_id));
"""


def _otg_has(c, table, col=None):
    if col is None:
        return bool(c.execute("SELECT to_regclass(?)", (table,)).fetchone()[0])
    return c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?",
                     (table, col)).fetchone() is not None


OTG_ISO_SPACE = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])[ T]([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?$"  # SQLite's own CURRENT_TIMESTAMP


def _otg_ts(c, v):
    """An old row's time as it can go into TIMESTAMPTZ: ISO with a zone, or the plain 'YYYY-MM-DD HH:MM:SS' of the old SQLite
    files (UTC); anything else is the time of the move."""
    if v and re.match(OTG_ISO_SPACE, str(v)):
        return str(v).replace(" ", "T", 1) + "+00:00"
    return v if v and re.match(OTG_ISO, str(v)) else now_utc()


def otg_move(c):
    """2.925.0 (#5275): the rows of list_tags / task_list_tags / org_tags into obj_tags / obj_tag_links, while those tables are
    there (the first start of 2.925, the copy of an old SQLite file, or again after a version before 2.925 ran and made them
    anew). Lossless: name, colour, order and time of every tag; a project tag keeps its id where that id is free. A label's
    copy in a project (list_tags.org_tag_id) is no tag of its own any more: its tasks get the label itself, and a list rule or a
    shared view that named the copy names the label. The fragment 5275_a drops the old tables right after (one-way). Runs in
    the start transaction as "system" (every organisation's rows). Returns the number of tags moved."""
    if not _otg_has(c, "list_tags") and not _otg_has(c, "org_tags"):
        return 0
    remap, n = {}, 0  # old list_tags id -> obj_tags id
    labels = {}  # old org_tags id -> obj_tags id
    lold = {}  # old list_tags id -> its list
    if _otg_has(c, "list_tags"):
        # the project tags keep their ids: the identity continues after the highest of them -- BEFORE the labels are made
        # (review F2: a label made first took id 1, 2, ... and the project tag with that id lost it)
        c.execute("SELECT setval(pg_get_serial_sequence('obj_tags', 'id'), GREATEST((SELECT COALESCE(MAX(id), 0) FROM obj_tags), "
                  "(SELECT COALESCE(MAX(id), 0) FROM list_tags), 1))")
    if _otg_has(c, "org_tags"):
        for r in c.execute("SELECT * FROM org_tags ORDER BY id").fetchall():
            have = otg_find(c, "org", r["org_id"], r["name"])
            labels[r["id"]] = (have["id"] if have else insert_id(
                c, "INSERT INTO obj_tags(scope_kind,scope_id,org_id,name,color,sort,created_at) VALUES('org',?,?,?,?,?,?)",
                (str(r["org_id"]), r["org_id"], r["name"], r["color"] or "", r["sort"] or 0, _otg_ts(c, r["created_at"]))), r["org_id"])
            n += 0 if have else 1
    if _otg_has(c, "list_tags"):
        copy = _otg_has(c, "list_tags", "org_tag_id")
        lorg = dict(c.execute("SELECT id, org_id FROM lists WHERE id IN (SELECT list_id FROM list_tags)").fetchall())
        for r in c.execute("SELECT * FROM list_tags ORDER BY id").fetchall():
            lold[r["id"]] = r["list_id"]
            lab = labels.get(r["org_tag_id"]) if copy and r["org_tag_id"] else None
            if lab and lab[1] == lorg.get(r["list_id"]):  # a copy of a label of the project's organisation: the label itself
                remap[r["id"]] = lab[0]
                continue
            have = otg_find(c, "list", r["list_id"], r["name"])
            if have:
                remap[r["id"]] = have["id"]
                continue
            free = not c.execute("SELECT 1 FROM obj_tags WHERE id=?", (r["id"],)).fetchone()
            args = ("list", str(r["list_id"]), r["name"], r["color"] or "", r["sort"] or 0, _otg_ts(c, r["created_at"]))
            remap[r["id"]] = insert_id(c, "INSERT INTO obj_tags(id,scope_kind,scope_id,name,color,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                                       (r["id"], *args)) if free else \
                insert_id(c, "INSERT INTO obj_tags(scope_kind,scope_id,name,color,sort,created_at) VALUES(?,?,?,?,?,?)", args)
            n += 1
        c.execute("SELECT setval(pg_get_serial_sequence('obj_tags', 'id'), GREATEST((SELECT COALESCE(MAX(id), 0) FROM obj_tags), 1))")
    if remap and _otg_has(c, "task_list_tags"):
        pairs = sorted(remap.items())
        # only a link whose old tag belonged to the task's own list (review: one left on a task that moved on was not shown
        # before -- through a label's copy it would turn into the label and show up again)
        c.execute("""INSERT INTO obj_tag_links(tag_id, kind, obj_id, src)
                     SELECT m.n, 'task', x.task_id, 'person' FROM task_list_tags x
                     JOIN unnest(CAST(? AS BIGINT[]), CAST(? AS BIGINT[]), CAST(? AS BIGINT[])) AS m(o, n, l) ON m.o=x.tag_id
                     JOIN tasks t ON t.id=x.task_id AND t.list_id=m.l ON CONFLICT DO NOTHING""",
                  ([p[0] for p in pairs], [p[1] for p in pairs], [lold[p[0]] for p in pairs]))
    per = {}  # review F3: a rule / shared view names a tag of its own project only -- rewrite per list
    for o, x in remap.items():
        if o != x:
            per.setdefault(lold[o], {})[o] = x
    for lid, m in sorted(per.items()):
        otg_rekey_refs(c, m, lid)
    # review F6: a project tag named like a label of the project's organisation becomes that label (as a project joining the
    # organisation does, trigger kalmido_otg_org_moved), so the label is not hidden behind it
    for (lid,) in c.execute("""SELECT id FROM lists WHERE org_id IS NOT NULL AND (id = ANY(CAST(? AS BIGINT[]))
                               OR org_id = ANY(CAST(? AS BIGINT[]))) ORDER BY id""",
                            (sorted(set(lold.values())), sorted({x[1] for x in labels.values()}))).fetchall():
        c.execute("SELECT kalmido_otg_joined(l.id, l.org_id) FROM lists l WHERE l.id=?", (lid,))
    return n


def otg_rekey_refs(c, m, lid):
    """The list rules of list lid (trigger "gets the tag", the action "add the tag", the condition "has the tag") and its shared
    views of a public link ("only the tag") that name an old tag id of m {old: new} name the new one. One way for the app and
    the trigger of a project changing its organisation: kalmido_otg_rekey (migrations.d/5275_a.py). Review F3: always per list --
    an id of m may be a valid tag of another project."""
    if not m or not (_otg_has(c, "list_rules", "conds") and _otg_has(c, "list_rules", "more_acts") and _otg_has(c, "public_links", "cv_show")):
        return
    for o, n in sorted(m.items()):
        c.execute("SELECT kalmido_otg_rekey(?, ?, ?)", (int(lid), int(o), int(n)))
