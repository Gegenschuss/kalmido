"""2.152.0 B (#2165): the trash periods of the areas without one. The watchdog (at most hourly) deletes for good what lies in
a trash longer than ret_days("trash") (KALMIDO_TRASH_DAYS, 30): hub mails (the row and its word index; the mail's folder went into the
file store's trash when the mail was deleted -- 2.536.0, #4338 -- and follows there), tables and their deleted rows /
columns, pipeline deals, invoice series, the
emptied rows of deleted comments (2.530.0 A, #4315: with their kept text and
files, collab/cmttrash.py); since 2.223.3 A (#2879) also absences,
disposition bookings, scheduling polls with their votes, appointment types and file requests; since 2.567.0 A (#4707) the
household budget (life/budget.py bud_trash_tick: entries with their receipts, templates, categories); the project / task /
section templates since 2.905.0 (#5288) through the core's run (lists/tplkind.py tk_on_purge, with their file copies).
2.783.0 (#5368): the tombstones of the team chat, deleted custom fields, member memos, the Undo copies of "Delete all times",
the copies of sections / sprints and the inbound webhooks are deleted by the core's run (core/writes.py obj_trash_tick).

Like every retention run it only counts while ret_on("trash") is off (core/retention.py) and reports the numbers per
area (GET /api/admin/retention). 2.809.0 (#5365): file-store nodes (with their versions, previews, text and index; a node a
hook of fs_on_delete refuses -- legal retention of a booked receipt, #2168 -- stays, counted as fs_entry_locked), knowledge
pages and tables are deleted by the core's run (core/writes.py obj_trash_tick: files/fskern.py, wiki/wkkern.py,
sheets/shkern.py). The logbook is never purged here: its entries are locked until the legal
period ends (#2169). Lists, tasks and events have their own runs (lists/listtrash.py, tasks/tasktrash.py, events/model.py)."""
import time

from ..core.db import iso, iso_ms, now_utc
from ..core.access import live_sql  # 2.783.0 (#5368): live_sql
from ..core.retention import ret_on, ret_report, ret_trash_cut
from ..tasks.atttrash import atr_tick  # 2.272.0 E2 (#3038)
from ..life.budget import bud_trash_tick  # 2.567.0 A (#4707)
from ..files.store import fs_purge_files  # 2.369.5 (#2517): pulled up from functions
from ..core.pg import system_ctx  # 2.369.5 (#2517): pulled up from functions
from ..hub.hubmail import hbm_mail_nodes  # 2.536.0 (#4338): the nodes of a mail, shared with deleting it

TP_TICK = {"at": 0.0}
# 2.239.0 D (#2874): nor a client with a signed data protection sheet (clients_bulk.ms_client_in_use), on top of cl_hold_sql()
TP_PRIVACY_HOLD = (" AND NOT EXISTS (SELECT 1 FROM office_privacy_sheets x WHERE x.client_id=clients.id"
                   " AND (x.status='signed' OR x.signed_node_id IS NOT NULL))")
# (count key, table, extra condition): the plain areas, one DELETE each (their child rows go by ON DELETE CASCADE)
TP_PLAIN = (
    # 2.809.0 (#5365): tables in the trash go through the core's run (sheets/shkern.py); their deleted rows / columns stay here
    ("sheet_rows", "sheet_rows", f" AND sheet_id IN (SELECT id FROM sheets WHERE {live_sql()})"),
    ("sheet_columns", "sheet_columns", f" AND sheet_id IN (SELECT id FROM sheets WHERE {live_sql()})"),
    ("deals", "office_deals", ""),  # office_docs.deal_id: ON DELETE SET NULL
    ("series", "office_inv_series", ""),  # the invoices made stay (series_id is a plain number)
    # 2.783.0 (#5368): the tombstones of the team chat moved onto the core's run (collab/cmttrash.py TCX_MSG_KIND)
    # body is empty; reactions (trigger, #5269) and (2.530.0 A, #4315) the kept text go along; its files went through atr_tick above (same deleted_at)
    ("comments", "obj_comments", ""),  # 2.972.0 (#5272): the core's table (the kept text, obj_comment_trash, goes with it: trigger kalmido_oct_gone_comment, #5274)
    # 2.272.0 D (#3029): clients (contact persons, data protection sheets, mail-in addresses cascade -- video reviews go to their
    # own trash first, 2.530.0 D #4316; mails,
    # deals, letters ... set null); never one records (kept by law) point to since -- team/clients.py CL_HOLD
    # 2.223.3 (#2878): the hold rule is team/clients.py cl_hold_sql() (finalised documents only), filled in at the run
    ("clients", "clients", None),
    # 2.272.0 E1 (#3038): contacts (contact_care notes, contact_tasks, contact_occ cascade) and list notes; 2.947.0 (#5367):
    # the address books are the core's trash (core/writes.py obj_trash_tick, their purge hook contacts/ctkern.py bk_purge_prep)
    ("contacts", "contacts", ""),
    ("notes", "notes", ""),
    # 2.223.3 A (#2879): absences, disposition bookings, scheduling polls (their options and votes cascade), appointment types
    # (their bookings keep the time, type_id set null) and file requests (the link goes with the row; files received stay in
    # the folder). None of them is kept by law.
    ("absences", "hub_absences", ""),
    ("bookings", "hub_bookings", ""),
    ("polls", "sched_polls", ""),
    ("appt_types", "appt_types", ""),
    ("file_requests", "fs_upload_requests", ""),
    # 2.530.0 B (#4315): deleted habits (their logs cascade) and the Undo copies of "Delete all times of this project"
    ("habits", "habits", ""),  # 2.783.0 (#5368): the Undo copies of "Delete all times" are the core's (personal/timewipe.py)
    # 2.567.0 A (#4707): the key links of project lists; 2.783.0 (#5368): the copies of deleted sections / planned sprints
    # (lists/parttrash.py) are the core's copy trash, deleted by its run (core/writes.py obj_trash_tick)
    ("list_links", "list_links", ""),
    # 2.550.0 (#4528): deleted custom fields with their values (lists/fields.py field_delete) and what removing a member ended
    # (lists/membermemo.py): rows only, the restore is gone once the period is over
    # 2.783.0 (#5368): field_trash's rows move into the core's copy trash at every start (lists/fields.py ftr_move); the
    # member memos are a side object of the core (lists/membermemo.py MM_KIND): both on the core's run (core/writes.py)
)


def tp_cut():
    return ret_trash_cut()  # 2.272.0 A (#3026): with the floor of 1 day (0 was "everything now")


def tp_hubmail(c, cut, purge):
    """Hub mails in the trash since before cut: the row goes (its words in obj_search_words by the delete trigger, 2.1002.0 #5279), the folder with the .eml and the
    attachments goes into the file store's trash (it is deleted there after the same period)."""
    rows = c.execute("SELECT id, folder_id, eml_id, files FROM hub_mails WHERE deleted_at IS NOT NULL AND deleted_at<?", (cut,)).fetchall()
    if not purge:
        return len(rows)
    ts = iso(now_utc())
    for r in rows:
        # 2.536.0 (#4338): deleting the mail put them into the trash already (hbm_mail_del); this catches the older ones
        for nid in hbm_mail_nodes(c, r):
            c.execute(f"UPDATE fs_nodes SET deleted_at=? WHERE id=? AND {live_sql()}", (ts, nid))
        c.execute("DELETE FROM hub_mails WHERE id=?", (r["id"],))
    return len(rows)


def tp_tick(c, force=False):
    """The watchdog (at most hourly): every area's trash older than the period -- counted, and deleted when the switch is on."""
    if not force and time.time() - TP_TICK["at"] < 3600:
        return {}
    TP_TICK["at"] = time.time()
    purge, cut, counts = ret_on("trash"), tp_cut(), {}
    with system_ctx(c):  # the trash of every organisation and private space (row-level security); nothing is handed to a person
        # 2.809.0 (#5365): file-store nodes go through the core's run (core/writes.py obj_trash_tick, files/fskern.py:
        # fs_entry / fs_entry_locked); paths = the other areas' stored files below
        paths = []
        counts["hub_mails"] = tp_hubmail(c, cut, purge)
        fc, fp = atr_tick(c, cut, purge)  # 2.272.0 E2 (#3038): task / comment / project files (unlinked after the commit)
        counts.update(fc)
        paths += fp
        # 2.1050.0 (#5789): the office's copies (otb_tick) are gone: every office kind is on the core's run (obj_trash_tick)
        try:  # 2.567.0 A (#4707): household budget entries (with their receipts), templates, categories
            with c.savepoint():
                bc, bp = bud_trash_tick(c, cut, purge)
            counts.update(bc)
            paths += bp
        except Exception as e:  # noqa: BLE001 - like the plain areas below: this one waits for the next run
            print("trash purge: budget", type(e).__name__, flush=True)
            counts["budget_err"] = 1
        # 2.905.0 (#5288): project / task / section templates: the core's run (core/writes.py obj_trash_tick, lists/tplkind.py)
        for key, table, extra in TP_PLAIN:
            if extra is None:  # 2.223.3 (#2878): clients -- the same hold rule as deleting a client
                from ..team.clients import cl_hold_sql
                extra = cl_hold_sql() + TP_PRIVACY_HOLD
            kp = []  # 2.272.0 F (#3026, review M3): one savepoint per area, a failing one is counted, the rest goes on
            try:
                with c.savepoint():
                    w = f"FROM {table} WHERE deleted_at IS NOT NULL AND deleted_at<?{extra}"
                    if purge:
                        if table == "contacts":  # 2.351.0 B (#2749): their folder nodes (contacts/ctfolder.py) go with them
                            c.execute(f"DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='contact' AND ref_id IN (SELECT id {w})", (cut,))
                        if table == "clients":  # 2.530.0 D (#4316, audit B18): their video sign-offs go to the video trash, not by cascade
                            from ..videos.vdrescue import vdr_rescue
                            counts["clients_videos"] = vdr_rescue(c, client_ids=[r[0] for r in c.execute(f"SELECT id {w}", (cut,))])
                        counts[key] = c.execute(f"DELETE {w}", (cut,)).rowcount
                        if key in ("sheet_rows", "sheet_columns") and counts[key]:
                            # 2.152.0 (#2165, review C-M2): a file the purged cells held (and no other cell holds) goes to the
                            # files' trash; shk_tick (sheets/shkinds.py) removes it with its scan / text rows after its period
                            c.execute(f"UPDATE sheet_files SET deleted_at=? WHERE {live_sql()} AND NOT EXISTS (SELECT 1 FROM sheet_cells x "
                                      "WHERE x.sheet_id=sheet_files.sheet_id AND trim(x.raw)='file:' || sheet_files.id)", (iso_ms(now_utc()),))
                    else:
                        counts[key] = c.execute(f"SELECT COUNT(*) {w}", (cut,)).fetchone()[0]
            except Exception as e:  # noqa: BLE001 - a future FK / trigger / timeout: this area waits for the next run
                print("trash purge:", key, type(e).__name__, flush=True)
                counts[key + "_err"] = 1
                continue
            paths += kp
        try:  # 2.855.0 (#1956, review F1): a call sheet goes with the last booking of its shoot day (no foreign key: job is text)
            with c.savepoint():  # 2.872.0 (#5532): the core's delete for good (hub/dspkern.py: its history and undo rows with it)
                from ..hub.dspkern import dsk_orphans
                counts["callsheets"] = dsk_orphans(c, purge)
        except Exception as e:  # noqa: BLE001 - like the plain areas above: waits for the next run
            print("trash purge: callsheets", type(e).__name__, flush=True)
            counts["callsheets_err"] = 1
        ret_report(c, "trash", counts, purge)
    c.commit()
    if paths:
        fs_purge_files([], paths)  # after the commit: a failed commit keeps the rows and their files
    return counts
