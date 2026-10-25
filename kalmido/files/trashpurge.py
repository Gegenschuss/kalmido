"""2.152.0 B (#2165): the trash periods of the areas without one. The watchdog (at most hourly) deletes for good what lies in
a trash longer than ret_days("trash") (KALMIDO_TRASH_DAYS, 30): file-store nodes (with their versions, previews, text and
index through fs_purge and its hooks), hub mails (the row and its word index; the mail's folder goes into the
file store's trash and follows there), tables and their deleted rows / columns, pipeline deals, invoice series, the
tombstones of deleted team chat messages and the emptied rows of deleted comments; since 2.223.3 A (#2879) also absences,
disposition bookings, scheduling polls with their votes, appointment types and file requests.

Like every retention run it only counts while ret_on("trash") is off (core/retention.py) and reports the numbers per
area (GET /api/admin/retention). A node a hook of fs_on_delete refuses (Denied: legal retention of a booked receipt,
#2168) stays and is counted as files_locked. The logbook is never purged here: its entries are locked until the legal
period ends (#2169). Lists, tasks, wiki pages and events have their own runs (lists/listtrash.py, tasks/tasktrash.py,
wiki/pages.py wiki_trash_tick with the pages' files, events/model.py)."""
import time

from ..core.db import iso, iso_ms, now_utc
from ..core.access import Denied
from ..core.retention import ret_on, ret_report, ret_trash_cut
from ..tasks.atttrash import atr_tick  # 2.272.0 E2 (#3038)
from ..office.otrash import otb_tick  # 2.272.0 E2 (#3038)

TP_TICK = {"at": 0.0}
# (count key, table, extra condition): the plain areas, one DELETE each (their child rows go by ON DELETE CASCADE)
TP_PLAIN = (
    ("sheets", "sheets", ""),  # columns, rows, cells, changes, links cascade
    ("sheet_rows", "sheet_rows", " AND sheet_id IN (SELECT id FROM sheets WHERE deleted_at IS NULL)"),
    ("sheet_columns", "sheet_columns", " AND sheet_id IN (SELECT id FROM sheets WHERE deleted_at IS NULL)"),
    ("deals", "office_deals", ""),  # office_docs.deal_id: ON DELETE SET NULL
    ("series", "office_inv_series", ""),  # the invoices made stay (series_id is a plain number)
    # body is empty already; tchat_rx cascade. 2.152.0 (#2165, review C-H2): a thread's first message stays while replies point
    # at it (thread_of has no FK; without the root the replies can no longer be reached) -- it goes once its replies went
    ("chat_tombstones", "tchat_msgs", " AND NOT EXISTS (SELECT 1 FROM tchat_msgs r WHERE r.thread_of=tchat_msgs.id)"),
    ("comments", "comments", ""),  # body is empty, the files went at the delete; reactions cascade
    # 2.272.0 D (#3029): clients (contact persons, data protection sheets, video reviews, mail-in addresses cascade; mails,
    # deals, letters ... set null); never one records (kept by law) point to since -- team/clients.py CL_HOLD
    # 2.223.3 (#2878): the hold rule is team/clients.py cl_hold_sql() (finalised documents only), filled in at the run
    ("clients", "clients", None),
    # 2.272.0 E1 (#3038): contacts (contact_care notes, contact_tasks, contact_occ cascade), address books (their contacts
    # cascade; merge undo data expires with mg_prune) and list notes
    ("contacts", "contacts", ""),
    ("books", "books", ""),
    ("notes", "notes", ""),
    # 2.223.3 A (#2879): absences, disposition bookings, scheduling polls (their options and votes cascade), appointment types
    # (their bookings keep the time, type_id set null) and file requests (the link goes with the row; files received stay in
    # the folder). None of them is kept by law.
    ("absences", "hub_absences", ""),
    ("bookings", "hub_bookings", ""),
    ("polls", "sched_polls", ""),
    ("appt_types", "appt_types", ""),
    ("file_requests", "fs_upload_requests", ""),
)


def tp_cut():
    return ret_trash_cut()  # 2.272.0 A (#3026): with the floor of 1 day (0 was "everything now")


def tp_files(c, cut, purge):
    """File-store nodes in the trash since before cut. -> (purged or due, locked, paths, ids) -- files after the commit."""
    from ..files.store import fs_purge
    due = locked = 0
    paths, ids = [], []
    for (nid,) in c.execute("SELECT id FROM fs_nodes WHERE deleted_at IS NOT NULL AND deleted_at<? ORDER BY deleted_at, id",
                            (cut,)).fetchall():
        if not purge:
            due += 1
            continue
        if not c.execute("SELECT 1 FROM fs_nodes WHERE id=?", (nid,)).fetchone():
            continue  # went with a folder above it
        try:
            with c.savepoint():
                i, p = fs_purge(c, nid)
        except Denied:  # a hook keeps it (legal retention, #2168): the node stays in the trash
            locked += 1
            continue
        due += 1
        ids += i
        paths += p
    return due, locked, paths, ids


def tp_hubmail(c, cut, purge):
    """Hub mails in the trash since before cut: the row goes (hub_words cascade), the folder with the .eml and the
    attachments goes into the file store's trash (it is deleted there after the same period)."""
    rows = c.execute("SELECT id, folder_id, eml_id, files FROM hub_mails WHERE deleted_at IS NOT NULL AND deleted_at<?", (cut,)).fetchall()
    if not purge:
        return len(rows)
    import json
    ts = iso(now_utc())
    for r in rows:
        try:
            nodes = [r["folder_id"]] if r["folder_id"] else [r["eml_id"], *json.loads(r["files"] or "[]")]
        except ValueError:
            nodes = [r["eml_id"]]
        for nid in [x for x in nodes if isinstance(x, int)]:
            c.execute("UPDATE fs_nodes SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, nid))
        c.execute("DELETE FROM hub_mails WHERE id=?", (r["id"],))
    return len(rows)


def tp_tick(c, force=False):
    """The watchdog (at most hourly): every area's trash older than the period -- counted, and deleted when the switch is on."""
    if not force and time.time() - TP_TICK["at"] < 3600:
        return {}
    TP_TICK["at"] = time.time()
    from ..core.pg import system_ctx
    from ..files.store import fs_purge_files
    purge, cut, counts = ret_on("trash"), tp_cut(), {}
    with system_ctx(c):  # the trash of every organisation and private space (row-level security); nothing is handed to a person
        counts["files"], counts["files_locked"], paths, ids = tp_files(c, cut, purge)
        counts["hub_mails"] = tp_hubmail(c, cut, purge)
        fc, fp = atr_tick(c, cut, purge)  # 2.272.0 E2 (#3038): task / comment / project files (unlinked after the commit)
        counts.update(fc)
        paths += fp
        counts["office"] = otb_tick(c, cut, purge)  # 2.272.0 E2 (#3038): document drafts and master data (rows only)
        for key, table, extra in TP_PLAIN:
            if extra is None:  # 2.223.3 (#2878): clients -- the same hold rule as deleting a client
                from ..team.clients import cl_hold_sql
                extra = cl_hold_sql()
            kp = []  # 2.272.0 F (#3026, review M3): one savepoint per area, a failing one is counted, the rest goes on
            try:
                with c.savepoint():
                    w = f"FROM {table} WHERE deleted_at IS NOT NULL AND deleted_at<?{extra}"
                    if purge:
                        if table == "sheets":  # 2.152.0 (#2165): the stored files of their file cells go too (sheet_files cascade)
                            # 2.152.0 (#2165, review C-M1): also those of the further sheets of the table (book_id, they cascade with
                            # it), and the scan / text rows of all these files (kind 'sheet', no FK) before the rows go
                            fr = c.execute("SELECT f.id, f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id "
                                           "WHERE (s.deleted_at IS NOT NULL AND s.deleted_at<?) OR s.book_id IN "
                                           "(SELECT id FROM sheets WHERE deleted_at IS NOT NULL AND deleted_at<?)", (cut, cut)).fetchall()
                            kp += [r["path"] for r in fr]
                            for i in range(0, len(fr), 500):
                                fids = [r["id"] for r in fr[i:i + 500]]
                                q = ",".join("?" * len(fids))
                                c.execute(f"DELETE FROM upload_scan WHERE kind='sheet' AND ref_id IN ({q})", fids)
                                c.execute(f"DELETE FROM file_text WHERE kind='sheet' AND ref_id IN ({q})", fids)
                            # 2.199.0 C (#2742): their folder nodes (files/fsref.py) go with them
                            c.execute("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id IN "
                                      "(SELECT id FROM sheets WHERE deleted_at IS NOT NULL AND deleted_at<?)", (cut,))
                        if table == "books":  # 2.272.0 F (#3038, review N7): the merge undo data goes with it, like op_book_purge
                            c.execute("UPDATE merge_runs SET snapshot='{}' WHERE kind='contact' AND book_id IN "
                                      f"(SELECT id {w})", (cut,))
                        counts[key] = c.execute(f"DELETE {w}", (cut,)).rowcount
                        if key in ("sheet_rows", "sheet_columns") and counts[key]:
                            # 2.152.0 (#2165, review C-M2): a file the purged cells held (and no other cell holds) goes to the
                            # files' trash; shk_tick (sheets/shkinds.py) removes it with its scan / text rows after its period
                            c.execute("UPDATE sheet_files SET deleted_at=? WHERE deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM sheet_cells x "
                                      "WHERE x.sheet_id=sheet_files.sheet_id AND trim(x.raw)='file:' || sheet_files.id)", (iso_ms(now_utc()),))
                    else:
                        counts[key] = c.execute(f"SELECT COUNT(*) {w}", (cut,)).fetchone()[0]
            except Exception as e:  # noqa: BLE001 - a future FK / trigger / timeout: this area waits for the next run
                print("trash purge:", key, type(e).__name__, flush=True)
                counts[key + "_err"] = 1
                continue
            paths += kp
        ret_report(c, "trash", counts, purge)
    c.commit()
    if paths or ids:
        fs_purge_files(ids, paths)  # after the commit: a failed commit keeps the rows and their files
    return counts
