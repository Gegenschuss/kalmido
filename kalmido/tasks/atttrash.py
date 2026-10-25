"""2.272.0 E2 (#3038): the trash of task / comment files (attachments) and project files (list_files).

Deleting a file sets deleted_at (the row and the file on disk stay, "Undo" in the app and the trash of the task / project
restore it). After the trash period (ret_days("trash"), at least one day) files/trashpurge.py tp_tick calls atr_tick: it
counts, and while ret_on("trash") is on it deletes the rows for good; the files leave the disk after the commit (the caller
unlinks the returned paths). A path another row still uses stays on disk (as tasks/tasktrash.py ttp_purge)."""

ATR_TABLES = (("attachments", "attachments"), ("list_files", "list_files"))  # (count key, table)


def atr_used(c, paths):
    """The paths of paths another attachment / list file row still uses (they stay on disk)."""
    if not paths:
        return set()
    f = ",".join("?" * len(paths))
    return {r[0] for r in c.execute(f"SELECT path FROM attachments WHERE path IN ({f}) UNION SELECT path FROM list_files "
                                    f"WHERE path IN ({f})", (*paths, *paths))}


def atr_tick(c, cut, purge):
    """Files in the trash since before cut: -> (counts, paths to unlink after the commit). Only counts while purge is off."""
    counts, paths = {}, []
    for key, table in ATR_TABLES:
        w = f"FROM {table} WHERE deleted_at IS NOT NULL AND deleted_at<?"
        if not purge:
            counts[key] = c.execute(f"SELECT COUNT(*) {w}", (cut,)).fetchone()[0]
            continue
        rows = c.execute(f"SELECT id, path {w} ORDER BY id FOR UPDATE", (cut,)).fetchall()
        for i in range(0, len(rows), 500):
            ids = [r["id"] for r in rows[i:i + 500]]
            q = ",".join("?" * len(ids))
            kind = "att" if table == "attachments" else "list"
            c.execute(f"DELETE FROM upload_scan WHERE kind=? AND ref_id IN ({q})", (kind, *ids))  # no FK (file_text cascades)
            c.execute(f"DELETE FROM {table} WHERE id IN ({q})", ids)
        counts[key] = len(rows)
        paths += [r["path"] for r in rows]
    used = atr_used(c, sorted(set(paths)))
    return counts, [p for p in dict.fromkeys(paths) if p not in used]


def atr_purge_list(c, lid):
    """2.272.0 F (#3038, review E2-H1): the task / comment files of list lid lying in the trash go for good now (the end of an
    encryption switch: they were not converted, a restore would bring a file of the old format back). -> paths to unlink
    after the commit (the caller commits)."""
    rows = c.execute("SELECT a.id, a.path FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.deleted_at IS NOT NULL "
                     "ORDER BY a.id FOR UPDATE OF a", (lid,)).fetchall()
    for i in range(0, len(rows), 500):
        ids = [r["id"] for r in rows[i:i + 500]]
        q = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='att' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM attachments WHERE id IN ({q})", ids)
    paths = [r["path"] for r in rows]
    used = atr_used(c, sorted(set(paths)))
    return [p for p in dict.fromkeys(paths) if p not in used]


def atr_purge_one(c, table, rid):
    """2.272.0 F (#3038, review E2-H2): one file in the trash deleted for good by a person now ("Delete for good" in the trash
    of the task / project; rights checked by the caller). -> paths to unlink after the commit."""
    r = c.execute(f"SELECT id, path FROM {table} WHERE id=? AND deleted_at IS NOT NULL FOR UPDATE", (rid,)).fetchone()
    if not r:
        return []
    c.execute("DELETE FROM upload_scan WHERE kind=? AND ref_id=?", ("att" if table == "attachments" else "list", rid))
    c.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
    return [] if r["path"] in atr_used(c, [r["path"]]) else [r["path"]]
