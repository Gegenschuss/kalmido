"""2.506.0 (#4299): what the undo of an account import may still take back (Rest of #3027).

The undo treats every table like the tasks: only rows unchanged since the import and without anything new below them go.
 - changed: a work time column (see _work_cols) after the import, or, for a table without such a column, another fingerprint
   than the one the run noted (undo_prints; a run from before 2.506.0 has none: its rows count as unchanged)
 - new below it: a row with a foreign key on it the run did not record, born after the import (also of another person: the
   look goes past row-level security, it only answers yes / no)
 - moved to another space since
What stays pulls along: the recorded rows it points at (nothing kept hangs below something gone) and the rows that cascade on
it (a table with one changed cell stays whole; a folder is only a place, so its unchanged files still go).
File store, knowledge pages and tables go into their trash (undo_trash), with what cascades on them left untouched for a
restore; everything else that goes is deleted as before: the export still holds it. Only stored files of rows that are really
gone are removed (undo_files_left)."""
import hashlib
import json
import os

from ..core.access import Denied
from ..core.db import iso_ms, now_utc
from ..core.merges import mg_fk_refs
from ..core.pg import system_ctx
from ..files.fsref import fs_ref_subtree, fs_ref_trashed
from ..files.store import READ_ACTIONS, fs_log_add
from ..integrations.importers import imp_undo_after
from ..office.periodlock import pl_tree_need_open
from ..sheets.shfolder import SHF_KIND
from ..team.clients import cl_trash
from ..wiki.wkfolder import WKF_KIND
from .acctimport import umz_cols

_CHUNK = 500
# time columns that do not mean somebody worked on the row: its birth, a date in the future, what background runs write
_NOT_WORK = frozenset(("created_at", "added_at", "expires_at", "polled_at", "error_at", "synced_at", "fetched_at", "rchk_at", "redo_at",
                       "taken_at", "done_at", "last_seen_at", "last_mail_at", "last_hit_at", "started_at", "ended_at", "installed_at",
                       "checked_at",
                       "remind_at"))  # 2.516.0 (#4366): habits.remind_at is a time of day (HH:MM), no time stamp (read as "after")
_EDITED = ("updated_at", "changed_at", "edited_at")
_BORN = ("created_at", "added_at", "at")
# append-only: nothing to fingerprint (a new entry shows up as a new row)
_NO_PRINT = frozenset(("activity", "list_activity", "org_list_log", "fs_log", "sheet_hist", "office_doc_log", "office_cash_log", "office_drive_log",
                       "office_meal_log", "office_rights_log", "office_archive_log", "nl_consent_log"))
# a reminder sent, a new order, the poller's last fetch: not a change
_PRINT_SKIP = {"habits": ("reminded_on", "reminded_hm", "sort"), "filters": ("sort",),
               "rss_feeds": ("etag", "last_modified", "last_fetch", "last_ok", "last_error", "fails"),
               # the preview fetch writes these and updated_at at any time, also after the person's edit: the person's columns are compared
               "bookmarks": ("title", "description", "site", "image", "image_mime", "image_url", "text", "preview", "preview_error", "fetched_at", "updated_at")}
# cannot hold a stored file's name, and can be large
_NO_FILES = _NO_PRINT | {"sheet_cells", "sheet_rows", "sheet_columns", "doc_field_values"}
# no foreign key, but new work all the same: (table, column, its time column)
_NO_FK_KIDS = {"sprints": (("tasks", "sprint_id", "sprint_at"),)}
_BASE = ("habits", "filters", "templates", "template_files", "time_entries", "bookmarks")
_PARTS = ("sprints", "list_rules", "portal_tickets")
_ANY = object()  # a row recorded without a space
_TRASH = ("fs_nodes", "wiki_pages", "sheets", "clients")
# the labels of a document, by (table, column): they wait for a document in the trash, its restore brings them back with it
_LABELS = {"doc_tags": ("doc_node_tags", "tag_id"), "doc_senders": ("doc_meta", "sender_id"), "doc_types": ("doc_meta", "type_id"),
           "doc_fields": ("doc_field_values", "field_id")}


def _chunks(ids):
    ids = list(ids)
    return (ids[i:i + _CHUNK] for i in range(0, len(ids), _CHUNK))


def _qs(part):
    return ",".join("?" * len(part))


def _work_cols(c, table):
    return [k for k in umz_cols(c, table)[0] if k.endswith("_at") and k not in _NOT_WORK]


# fingerprinted although they have an edited column: bookmarks (the preview fetch writes updated_at), habits (updated_at of 2.564
# #4701 is only the version of the settings, a day logged since is a change of the habit too: its log is in the fingerprint)
_PRINT_ALWAYS = frozenset(("bookmarks", "habits"))


def _printed(c, table):
    return table in _PRINT_ALWAYS or (table not in _NO_PRINT and not any(k in umz_cols(c, table)[0] for k in _EDITED))


def undo_print(row, skip=()):
    d = {k: bytes(v).hex() if isinstance(v, (bytes, memoryview)) else v for k, v in dict(row).items() if k not in skip}
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


def undo_key(vals):
    return json.dumps(vals, sort_keys=True)


def _print_rows(c, table, ids):
    """{str(id): fingerprint}; a habit's includes its log (no time column there, a day logged since is a change of the habit)."""
    out, skip = {}, _PRINT_SKIP.get(table, ())
    for part in _chunks(ids):
        rows = c.execute(f"SELECT * FROM {table} WHERE id IN ({_qs(part)})", part).fetchall()
        logs = {}
        if table == "habits":
            for x in c.execute(f"SELECT habit_id, day, count FROM habit_logs WHERE habit_id IN ({_qs(part)}) ORDER BY habit_id, day", part):
                logs.setdefault(x["habit_id"], []).append([x["day"], x["count"]])
        for r in rows:
            out[str(r["id"])] = undo_print({**dict(r), "_logs": logs.get(r["id"], [])} if table == "habits" else r, skip)
    return out


def undo_rows(cr):
    """{table: {id: space or _ANY}} of what the run recorded and the plan judges."""
    rows = {}
    for t in _BASE:
        for x in cr.get(t) or []:
            rows.setdefault(t, {})[int(x)] = _ANY
    for x in cr.get("more") or []:  # the account import records its bookmarks there
        if isinstance(x, list) and len(x) == 2 and x[0] == "bookmarks" and isinstance(x[1], int):
            rows.setdefault("bookmarks", {})[x[1]] = _ANY
    for t, key in cr.get("parts") or []:
        if t in _PARTS:
            rows.setdefault(t, {})[int(key)] = _ANY
    for item in cr.get("oi") or []:
        if isinstance(item, list) and len(item) == 3 and isinstance(item[0], str) and isinstance(item[1], int):
            rows.setdefault(item[0], {})[item[1]] = item[2]
    return rows


def undo_prints(c, created, tables, keyed):
    """The fingerprints of a finished run (in its "prints"), of the rows whose table has no column that says it was edited.
    tables = the tables of the engine with an id, keyed = {table: key columns} of those recorded by a key."""
    out = {}
    for t, ids in undo_rows(created).items():
        if (t in tables or t in _BASE or t in _PARTS) and _printed(c, t):
            out[t] = _print_rows(c, t, ids)
    for item in created.get("oi") or []:
        if not (isinstance(item, list) and len(item) == 3 and item[0] in keyed and isinstance(item[1], dict)):
            continue
        if not _printed(c, item[0]):
            continue
        r = _key_row(c, item[0], item[1])
        if r is not None:
            out.setdefault(item[0], {})[undo_key(item[1])] = undo_print(r)
    return out


def _key_row(c, table, vals):
    cols = umz_cols(c, table)[0]
    if not vals or not all(k in cols for k in vals) or not all(v is None or isinstance(v, (int, str)) for v in vals.values()):
        return None
    where = " AND ".join(f"{k} IS NULL" if v is None else f"{k}=?" for k, v in vals.items())
    return c.execute(f"SELECT * FROM {table} WHERE {where}", [v for v in vals.values() if v is not None]).fetchone()


def undo_key_stays(c, table, vals, since, prints):
    """A row recorded by its key (settings of a space, a number counter): changed since? -> its row then, else None."""
    r = _key_row(c, table, vals)
    if r is None:
        return None
    pr = (prints or {}).get(table)
    if any(imp_undo_after(r[k], since) for k in _work_cols(c, table)) or (pr is not None and pr.get(undo_key(vals)) != undo_print(r)):
        return r
    return None


class UndoPlan:
    """exist: {(table, id)} the recorded rows still there. keep: they stay (counted: kept_n, the topmost of what stays). pin: they
    stay because a row in the trash needs them. roots: go into their trash. held: untouched below a root."""

    def __init__(self):
        self.exist, self.keep, self.pin, self.held, self.roots, self.kids, self.ups = set(), set(), set(), set(), set(), {}, {}
        self.in_trash, self.kept_n, self.trashed = set(), 0, 0
        self.final, self.final_with = set(), set()  # 2.593.0 (#4864): the finalised documents, they with what they hang on / hold

    def goes(self, table, rid):
        """Deleted for good by the undo."""
        k = (table, rid)
        return k in self.exist and k not in self.keep and k not in self.pin and k not in self.held and k not in self.roots

    def stays(self, table, rid):
        return (table, rid) in self.exist and not self.goes(table, rid)

    def of(self, table, which):
        return sorted(i for t, i in which if t == table)


def _judge_rows(c, plan, rows, since, prints, space_cols):
    """The first look: the rows themselves."""
    for table, by_id in rows.items():
        cols = umz_cols(c, table)[0]
        if "id" not in cols:
            continue
        work = [w for w in _work_cols(c, table) if not (table == "bookmarks" and w == "updated_at")]
        scol = (space_cols.get(table) or (None,))[0]
        scol = scol if scol in cols else None
        pr = (prints or {}).get(table)
        if pr is not None:
            sel, skip = "*", _PRINT_SKIP.get(table, ())
        else:
            sel, skip = ", ".join(["id", *work, *([scol] if scol else [])]), ()
        for part in _chunks(by_id):
            logs = {}
            if pr is not None and table == "habits":
                for x in c.execute(f"SELECT habit_id, day, count FROM habit_logs WHERE habit_id IN ({_qs(part)}) ORDER BY habit_id, day", part):
                    logs.setdefault(x["habit_id"], []).append([x["day"], x["count"]])
            for r in c.execute(f"SELECT {sel} FROM {table} WHERE id IN ({_qs(part)})", part).fetchall():
                k = (table, r["id"])
                plan.exist.add(k)
                if any(imp_undo_after(r[w], since) for w in work):
                    plan.keep.add(k)
                    if "deleted_at" in work and imp_undo_after(r["deleted_at"], since):
                        plan.in_trash.add(k)  # put into the trash by hand since: it stays there
                elif scol and by_id[r["id"]] is not _ANY and r[scol] != by_id[r["id"]]:
                    plan.keep.add(k)  # moved to another space
                elif pr is not None:
                    full = {**dict(r), "_logs": logs.get(r["id"], [])} if table == "habits" else r
                    if pr.get(str(r["id"])) != undo_print(full, skip):
                        plan.keep.add(k)


def _keep_final(c, plan):
    """2.593.0 (#4864): a document the import brought as finalised (locked_at set, also before the import) never goes: often the
    only GoBD copy once the source is gone. It stays with its import log entries (doc_id without a foreign key: linked here
    as if they cascaded, so they stay with it and count as part of it); what it points at and what cascades on it stay by
    _spread (its client, contract, positions, payments), its stored PDF / XML by undo_files_left / oi_office_files_left."""
    for part in _chunks(plan.of("office_docs", plan.exist)):
        plan.final.update(("office_docs", r[0]) for r in c.execute(
            f"SELECT id FROM office_docs WHERE id IN ({_qs(part)}) AND locked_at IS NOT NULL AND locked_at!=''", part).fetchall())
    if not plan.final:
        return
    plan.keep |= plan.final
    for part in _chunks(plan.of("office_doc_log", plan.exist)):
        for r in c.execute(f"SELECT id, doc_id FROM office_doc_log WHERE id IN ({_qs(part)})", part).fetchall():
            pk, ck = ("office_docs", r["doc_id"]), ("office_doc_log", r["id"])
            if pk in plan.final:
                plan.ups.setdefault(ck, []).append((pk, "c"))
                plan.kids.setdefault(pk, []).append(ck)


def _final_reach(plan):
    """2.593.0 (#4864): the finalised documents with what stays because of them (the same walk as _spread), for the preview."""
    reach, todo = set(plan.final), list(plan.final)
    while todo:
        k = todo.pop()
        nxt = [p for p, _a in plan.ups.get(k, ())] + [ck for ck in plan.kids.get(k, ()) if not (k[0] == "fs_nodes" and ck[0] == "fs_nodes")]
        for x in nxt:
            if x not in reach and x in plan.keep:
                reach.add(x)
                todo.append(x)
    plan.final_with = reach


def _refs(c, table):
    """(child table, column, on delete, time columns or None) of everything that can hang on table."""
    out = [(t, k, d, None) for t, k, d in mg_fk_refs(c, table)]
    out += [(t, k, "x", (w,)) for t, k, w in _NO_FK_KIDS.get(table, ())]
    return out


def _kid_filter(ct):
    if ct != "fs_log":
        return "", ()
    acts = sorted(READ_ACTIONS)
    return f" AND action NOT IN ({_qs(acts)})", tuple(acts)


def _judge_kids(c, plan, since, tracked):
    """The second look: what hangs on the rows, over every space (one person's undo must not take another's rows with it)."""
    with system_ctx(c):
        for table in {t for t, _ in plan.exist}:
            ids = plan.of(table, plan.exist)
            for ct, cc, act, times in _refs(c, table):
                cols = umz_cols(c, ct)[0]
                has_id = "id" in cols
                if times is None:
                    times = [k for k in _BORN if k in cols] or _work_cols(c, ct)
                    if has_id and ct in tracked:  # also what was moved here since (a move changes it, its birth stays)
                        times = sorted({*times, *_work_cols(c, ct)})
                if not has_id and not times:
                    continue  # an index built from the row
                extra, xargs = _kid_filter(ct)
                sel = ", ".join([cc, *(["id"] if has_id else []), *times])
                for part in _chunks(ids):
                    for x in c.execute(f"SELECT {sel} FROM {ct} WHERE {cc} IN ({_qs(part)}){extra}", (*part, *xargs)).fetchall():
                        pk = (table, x[cc])
                        if has_id and (ct, x["id"]) in plan.exist:
                            ck = (ct, x["id"])
                            plan.ups.setdefault(ck, []).append((pk, act))
                            if act == "c":
                                plan.kids.setdefault(pk, []).append(ck)
                        elif any(imp_undo_after(x[t], since) for t in times) if times else (has_id and ct in tracked):
                            plan.keep.add(pk)


def _spread(plan):
    todo = list(plan.keep)
    while todo:
        k = todo.pop()
        for p, _a in plan.ups.get(k, ()):
            if p not in plan.keep:
                plan.keep.add(p)
                todo.append(p)
        for ck in plan.kids.get(k, ()):  # part of it, it stays whole -- a folder is only a place: its unchanged files still go
            if ck not in plan.keep and not (k[0] == "fs_nodes" and ck[0] == "fs_nodes"):
                plan.keep.add(ck)
                todo.append(ck)


def _keep_nodes_of_kept(c, plan):
    """A page or table that stays keeps the folder its reference node lies in (the folder's trash would take it along)."""
    grew = False
    for table, kind in (("wiki_pages", WKF_KIND), ("sheets", SHF_KIND)):
        for part in _chunks(plan.of(table, plan.keep)):
            for n in c.execute(f"SELECT id, parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id IN ({_qs(part)})", (kind, *part)).fetchall():
                for i in (n["id"], n["parent_id"]):
                    k = ("fs_nodes", i)
                    if k in plan.exist and k not in plan.keep:
                        plan.keep.add(k)
                        grew = True
    return grew


def undo_plan(c, cr, since, tracked, space_cols):
    plan = UndoPlan()
    prints = cr.get("prints")
    rows = {t: v for t, v in undo_rows(cr).items() if t in tracked or t in _BASE or t in _PARTS}  # never a name from elsewhere in a statement
    _judge_rows(c, plan, rows, since, prints, space_cols)
    _judge_kids(c, plan, since, tracked)
    _keep_final(c, plan)  # 2.593.0 (#4864): after the kids are known (its log entries are linked to it here)
    _spread(plan)
    while _keep_nodes_of_kept(c, plan):
        _spread(plan)
    _final_reach(plan)
    plan.kept_n = sum(1 for k in plan.keep if k not in plan.in_trash and not any(p in plan.keep and a == "c" for p, a in plan.ups.get(k, ())))
    go = plan.exist - plan.keep
    # the top folder of an area (knowledge, tables ...) never goes into the trash, as in the app (fs_area_root_need_free): it stays,
    # empty, its marker too (the app would otherwise make a second one), and what is in it goes on its own
    nodes = plan.of("fs_nodes", go)
    for part in _chunks(nodes):
        plan.pin.update(("fs_nodes", r[0]) for r in c.execute(f"SELECT node_id FROM fs_area_roots WHERE node_id IN ({_qs(part)})", part).fetchall())
    top = {k for k in go if k[0] in _TRASH and k not in plan.pin}
    todo = list(top)
    while todo:
        for ck in plan.kids.get(todo.pop(), ()):
            if ck in go and ck not in plan.held:
                plan.held.add(ck)
                todo.append(ck)
    plan.roots = top - plan.held
    for k in plan.held | plan.roots:  # a row left for a restore blocks the delete of what it points at without a cascade or set null
        for p, a in plan.ups.get(k, ()):
            if a in ("a", "r") and p in go:
                plan.pin.add(p)
    below = plan.held | plan.roots
    for table, (ct, cc) in _LABELS.items():
        for part in _chunks(plan.of(table, go)):
            for r in c.execute(f"SELECT {cc}, node_id FROM {ct} WHERE {cc} IN ({_qs(part)})", part).fetchall():
                if ("fs_nodes", r["node_id"]) in below:
                    plan.pin.add((table, r[cc]))
    return plan


def _trash_node(c, uid, n, ts):
    """Node n (a row) with its subtree into the file store's trash; its pages and tables into their own, marked for the folder's
    restore. A receipt of a locked month inside: False, it stays where it is."""
    try:
        with c.savepoint():
            pl_tree_need_open(c, n["id"])
            refs = [r for r in fs_ref_subtree(c, n) if r["ref_kind"] in (WKF_KIND, SHF_KIND)]
            c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (ts, uid, n["id"]))
            fs_log_add(c, n["id"], "trash")
            for r in refs:
                fs_ref_trashed(c, uid, r, False)
    except Denied:
        return False
    return True


def undo_trash(c, uid, plan):
    """The roots of the plan into their trash, before the rest is deleted."""
    ts = iso_ms(now_utc())
    for nid in plan.of("fs_nodes", plan.roots):
        n = c.execute("SELECT * FROM fs_nodes WHERE id=? AND deleted_at IS NULL", (nid,)).fetchone()
        if n is None:
            continue
        if n["kind"] == "ref" and n["ref_kind"] not in (WKF_KIND, SHF_KIND):
            c.execute("DELETE FROM fs_nodes WHERE id=?", (nid,))  # a pointer: its object goes its own way
            plan.roots.discard(("fs_nodes", nid))
            plan.exist.discard(("fs_nodes", nid))
            continue
        if _trash_node(c, uid, n, ts):
            plan.trashed += 1
        else:
            plan.keep.add(("fs_nodes", nid))
            plan.kept_n += 1
    for table, kind in (("wiki_pages", WKF_KIND), ("sheets", SHF_KIND)):
        for rid in plan.of(table, plan.roots):
            if not c.execute(f"SELECT 1 FROM {table} WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone():
                continue  # went with its folder, or was in the trash in the export
            plan.trashed += 1
            n = c.execute("SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=? AND deleted_at IS NULL", (kind, rid)).fetchone()
            if n is not None:
                _trash_node(c, uid, n, ts)
            c.execute(f"UPDATE {table} SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, rid))  # no node, or a locked page
    for rid in plan.of("clients", plan.roots):
        if c.execute("SELECT 1 FROM clients WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone():
            cl_trash(c, rid)
            plan.trashed += 1  # 2.611.0 (#4866): a client in its trash counts like a file, page or table (the undo dialog names them)


def undo_final_top(plan):
    """2.593.0 (#4864): [(table, id)] of what stays because of a finalised document, without what is part of a row in that set
    (positions, payments, log entries): the rows the preview names under "stays"."""
    return sorted(k for k in plan.final_with if not any(p in plan.final_with and a == "c" for p, a in plan.ups.get(k, ())))


def undo_files_left(c, plan, paths, extra_rows=(), owners=None):
    """The stored files of paths that may go: not the ones a row that stays names (in the trash or kept). Called before the rows
    go; any text column counts, the names are unique (a random part). 2.516.0 (#4364): owners = {path: [[table, id], ...]}, the
    rows a file belongs to as the import recorded them (a name no column holds, e.g. the PDF of a finalised invoice): such a
    file stays while one of its rows does not go."""
    if not paths:
        return []
    owners = owners if isinstance(owners, dict) else {}

    def owned(p):
        rows = owners.get(p) if isinstance(p, str) else None
        return isinstance(rows, list) and any(isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and isinstance(x[1], int)
                                              and not plan.goes(x[0], x[1]) for x in rows)
    paths = [p for p in paths if not owned(p)]
    left = set()
    for table in {t for t, _ in plan.exist}:
        if table in _NO_FILES or "id" not in umz_cols(c, table)[0]:
            continue
        ids = [i for t, i in plan.exist if t == table and plan.stays(t, i)]
        for part in _chunks(ids):
            for r in c.execute(f"SELECT * FROM {table} WHERE id IN ({_qs(part)})", part).fetchall():
                left.update(v for v in dict(r).values() if isinstance(v, str))
    nodes = [i for t, i in plan.exist if t == "fs_nodes" and plan.stays(t, i)]
    for part in _chunks(nodes):  # the preview of a document: its row has no id of its own
        left.update(r[0] for r in c.execute(f"SELECT thumb FROM doc_meta WHERE node_id IN ({_qs(part)})", part).fetchall() if r[0])
    for r in extra_rows:
        left.update(v for v in dict(r).values() if isinstance(v, str))
    blob = "\0".join(left)
    return [p for p in paths if not (isinstance(p, str) and os.path.basename(p) in blob)]


__all__ = ["UndoPlan", "undo_plan", "undo_final_top", "undo_prints", "undo_trash", "undo_files_left", "undo_key", "undo_key_stays", "undo_rows"]
