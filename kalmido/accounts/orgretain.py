"""2.152.0 A (#2164 #2167): what an organisation (or a person's personal office) must keep by law, and what happens to it
when it is deleted.

odl_retention(c, oid) counts the office data under a legal retention period (finalised documents and archive entries:
books, cash book, bank statements: 10 years; booked receipts, receipts of trips taken into DATEV, entertainment receipts, the logbook: 8 years -- core/retention.py
RET_LEGAL_YEARS, 2.545.0 (#4595): + the buffer, ret_keep_years, from the end of the calendar year) and gives the latest end. An organisation with such data is not
deleted but retired (orgs.retired_at / retain_until): members out, data and key stay, nobody sees it in the app any more
but the instance admins (list "Organisations": kept until ..., export only); the watchdog removes it for good after
retain_until (odl_retired_prune, kind "trash", switch ret_on). Without such data the deletion goes as before, after a
confirmation when wiki pages, tables or office data would go along (409 with the numbers, then ?confirm=1).

The account deletion (users.user_purge) uses the same: the personal office is dismantled with its files (no legal data)
or retired; the rest of the account goes (upg_* helpers).
"""
import json
import os
import re

from flask import g, has_request_context

from ..core.objhooks import FOLLOW, KIDS_FIRST, OBJ, person_revoked  # 2.1032.0 (#5788): KIDS_FIRST; 2.558.0 (#4709): the shared core without importing the domain layer
from ..core.access import Denied, live_sql
from ..core.objhooks import obj_rows_drop_many  # 2.1004.0 (#5494)
from ..core.db import iso, local_now, now_utc  # 2.488.0 (#4004): local_now knows the test clock
from ..core.i18n import N_, tr, trn
from ..core.merges import mg_fk_refs
from ..core.pg import system_ctx
from .layouts import WG_STD_KEYS, wg_org_k  # 2.627.0 (#4504, review F2)
from ..core.env import env_bool  # 2.399.0 (#2687): the hosting switch (KALMIDO_HOSTED)
from ..core.retention import ret_keep_years, ret_need_unheld, ret_on, ret_person_office, ret_report
from ..core.orgcrypt import oc_drop_key  # 2.369.5 (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.369.5 (#2517): pulled up from functions
from .pictures import avatar_drop_file, org_icon_drop_file  # 2.369.5 (#2517): pulled up from functions
from ..core.pg import insert_id  # 2.369.5 (#2517): pulled up from functions

# (count key, legal kind, SQL of the years per row: org_id = ?) -- the year a period starts from (its end + N years)
ODL_LEGAL = (
    ("documents", "book", "SELECT substr(COALESCE(NULLIF(date, ''), locked_at), 1, 4) FROM office_docs "
                          "WHERE org_id=? AND locked_at IS NOT NULL"),
    ("archive", "book", "SELECT substr(COALESCE(NULLIF(date, ''), created_at), 1, 4) FROM office_archive WHERE org_id=?"),
    ("bookarch", "book", "SELECT CAST(year AS TEXT) FROM office_bookarch WHERE org_id=?"),  # 2.414.0 (#3502): the booking archive
    # 2.152.0 review F5: the same rule as the purge hook (receipts/suggest.py olk_fs_locked): booked = paid_at or vat_pct
    # set at all, the year from the document date, else the paid / assigned day
    ("receipts", "receipt", "SELECT substr(COALESCE(NULLIF(m.doc_date, ''), NULLIF(r.paid_at, ''), r.set_at), 1, 4) FROM rc_receipts r "
                            "LEFT JOIN doc_meta m ON m.node_id=r.node_id WHERE r.org_id=? AND (r.paid_at IS NOT NULL OR r.vat_pct IS NOT NULL)"),
    ("trip_receipts", "receipt", "SELECT substr(COALESCE(NULLIF(i.date, ''), t.date_from, i.created_at), 1, 4) FROM office_trip_items i "
                                 "JOIN office_trips t ON t.id=i.trip_id WHERE i.org_id=? AND i.datev=1"),
    ("drives", "logbook", "SELECT substr(COALESCE(NULLIF(day, ''), created_at), 1, 4) FROM office_drives WHERE org_id=?"),
    # 2.152.0 (#2167, review A6): the cash book and the bank statements are books (10 years), approved entertainment receipts receipts
    ("cash", "book", "SELECT substr(day, 1, 4) FROM office_cash_entries WHERE org_id=?"),
    ("bank", "book", "SELECT substr(day, 1, 4) FROM office_bank_tx WHERE org_id=?"),
    ("cards", "book", "SELECT substr(day, 1, 4) FROM office_cc_lines WHERE org_id=?"),  # 2.444.0 (#3447): statements and their positions, as the bank
    ("meals", "receipt", "SELECT substr(date, 1, 4) FROM office_meals WHERE org_id=? AND status<>'draft'"),
    # 2.184.0 A (#2628): sent letters (business letters, 6 years from the year they went out)
    ("letters", "letter", "SELECT substr(COALESCE(NULLIF(sent_at, ''), NULLIF(letter_date, ''), created_at), 1, 4) FROM office_letters "
                          "WHERE org_id=? AND status<>'draft'"),
    # 2.239.0 C (#2874): the careful side -- received receipts not booked yet (an invoice received is kept, booked or not),
    # payments of documents (books), the procedure documentation (organisation records, 10 years), confirmed sign-offs
    # (business letters); e-invoices of the documents that are no receipt yet: odl_einvoice_years
    ("open_receipts", "receipt", "SELECT substr(COALESCE(NULLIF(m.doc_date, ''), r.set_at), 1, 4) FROM rc_receipts r "
                                 "LEFT JOIN doc_meta m ON m.node_id=r.node_id WHERE r.org_id=? AND r.paid_at IS NULL AND r.vat_pct IS NULL"),
    ("payments", "book", "SELECT substr(COALESCE(NULLIF(date, ''), created_at), 1, 4) FROM office_payments WHERE org_id=?"),
    # 2.977.0 (#5282): its versions are rows of the core's obj_versions (kind procdoc, TIMESTAMPTZ)
    ("procdocs", "book", "SELECT CAST(EXTRACT(YEAR FROM created_at) AS TEXT) FROM obj_versions WHERE kind='procdoc' AND org_id=?"),
    ("signoffs", "letter", "SELECT substr(COALESCE(NULLIF(signed_at, ''), created_at), 1, 4) FROM office_signoffs "
                           "WHERE org_id=? AND (state='accepted' OR signed_at IS NOT NULL)"),
    # 2.355.0 B (#2845): the asset register (a book) from the year of a device's last depreciation: purchase month + useful
    # life (without one the longest of the table, office/assets.py AST_LIFE: the careful side)
    ("assets", "book", "SELECT CAST(CAST(substr(purchase_date, 1, 4) AS INTEGER) + (CAST(substr(purchase_date, 6, 2) AS INTEGER) - 1 "
                       "+ COALESCE(life_months, 156)) / 12 AS TEXT) FROM office_equipment WHERE org_id=? AND purchase_date ~ '^[0-9]{4}-[0-9]{2}'"),
)
# what goes along with an organisation without legal data: shown before (409), deleted only with ?confirm=1
ODL_CONTENT = (
    ("wiki_pages", f"SELECT COUNT(*) FROM wiki_pages WHERE org_id=? AND {live_sql()}"),
    ("tables", f"SELECT COUNT(*) FROM sheets WHERE org_id=? AND {live_sql()}"),
    ("office_documents", f"SELECT COUNT(*) FROM office_docs WHERE org_id=? AND {live_sql()}"),  # 2.1005.0 (#5415): not the trash (like the pages / tables)
    ("office_archive", "SELECT COUNT(*) FROM office_archive WHERE org_id=?"),
    ("trips", "SELECT COUNT(*) FROM office_trips WHERE org_id=?"),
    ("drives", "SELECT COUNT(*) FROM office_drives WHERE org_id=?"),
    ("clients", "SELECT COUNT(*) FROM clients WHERE org_id=?"),
)
# 2.272.0 D (#3029): the rest of what goes along (ON DELETE CASCADE on orgs, read from the foreign-key catalogue): the named
# areas below, every other table not in ODL_MORE_SKIP (parts of another row, settings, logs, indexes) as other entries
# -- a new table shows up there without a change here. Shown in the delete dialog only, the confirmation stays as it was.
def Nn_(one, other):  # a plural pair for trn (marked for tools/i18n_check.py, like notify/alerts.py)
    return one, other


ODL_MORE = (
    ("mails", Nn_("{0} e-mail", "{0} e-mails"), "hub_mails"),
    ("mailboxes", Nn_("{0} mailbox", "{0} mailboxes"), "hub_mailboxes"),
    ("mail_addresses", Nn_("{0} mail-in address", "{0} mail-in addresses"), "hub_tokens"),
    ("deals", Nn_("{0} deal", "{0} deals"), "office_deals"),
    ("all_letters", Nn_("{0} letter", "{0} letters"), "office_letters"),
    ("contracts", Nn_("{0} contract", "{0} contracts"), "office_contracts"),
    ("gen_docs", Nn_("{0} other document", "{0} other documents"), "office_gen_docs"),
    ("privacy", Nn_("{0} data protection sheet", "{0} data protection sheets"), "office_privacy_sheets"),
    ("videos", Nn_("{0} video review", "{0} video reviews"), "video_reviews"),
    ("chats", Nn_("{0} chat room", "{0} chat rooms"), "tchat_rooms"),
    ("newsletter", Nn_("{0} newsletter recipient", "{0} newsletter recipients"), "nl_members"),
    ("polls", Nn_("{0} poll", "{0} polls"), "sched_polls"),
    ("reports", Nn_("{0} report", "{0} reports"), "portal_tickets"),
    ("all_receipts", Nn_("{0} receipt", "{0} receipts"), "rc_receipts"),
    ("suppliers", Nn_("{0} supplier", "{0} suppliers"), "office_suppliers"),
    ("bookmarks", Nn_("{0} bookmark", "{0} bookmarks"), "bookmarks"),
    ("templates", Nn_("{0} template", "{0} templates"), "templates"),  # 2.905.0 (#5288): task, project and section templates (was section_templates)
    # 2.533.0 (#4318) B44: named in the delete dialog instead of only "other entries"
    ("absences", Nn_("{0} absence", "{0} absences"), "hub_absences"),
    ("bookings", Nn_("{0} resource booking", "{0} resource bookings"), "hub_bookings"),
    ("equipment", Nn_("{0} piece of equipment", "{0} pieces of equipment"), "office_equipment"),
    ("fixed_costs", Nn_("{0} fixed cost", "{0} fixed costs"), "office_fixed_costs"),
    ("doc_templates", Nn_("{0} document template", "{0} document templates"), "office_doc_templates"),
    ("text_blocks", Nn_("{0} text block", "{0} text blocks"), "office_texts"),
    ("vehicles", Nn_("{0} vehicle", "{0} vehicles"), "office_vehicles"),
    ("meals", Nn_("{0} hospitality receipt", "{0} hospitality receipts"), "office_meals"),
    ("trip_costs", Nn_("{0} trip cost", "{0} trip costs"), "life_trip_costs"),
)
ODL_MORE_OTHER = Nn_("{0} other entry", "{0} other entries")
ODL_MORE_SKIP = frozenset((
    # counted in ODL_CONTENT / checked by the delete itself (projects, files)
    "wiki_pages", "sheets", "office_docs", "office_archive", "office_trips", "office_drives", "clients", "lists", "fs_nodes",
    # the organisation itself: members, keys, invitations, settings, numbering, logs, jobs, search indexes
    "org_members", "org_list_log", "org_keys", "org_invites", "org_joins", "office_settings", "office_company", "office_bank_accounts", "office_numbers",
    "office_import_runs", "office_rights_log", "office_period_locks", "office_pack_installs", "office_rgroups",
    "office_rgroup_members", "office_inv_series", "office_datev_guids", "office_peppol", "office_pay_props", "bg_jobs",
    "office_payonline", "office_pay_links", "office_pay_sessions", "office_pay_events", "office_pay_payouts",  # 2.469.0 (#3459)
    "notify_channels", "reading_orgs", "task_vectors", "upload_scan", "file_text", "merge_runs", "obj_follow", "task_links",
    "hub_leave_quota", "fs_area_roots", "fs_upload_requests", "fs_ext_links", "wiki_spaces", "doc_cfg", "doc_models",
    "doc_types", "doc_tags", "doc_rules", "doc_fields", "doc_senders", "pl_sources", "pl_rules", "nl_conns", "nl_segments",
    "nl_suppress", "nl_consent_log", "portal_logins", "office_letter_profiles", "office_letter_blocks", "office_cashbooks",
    # parts of another row (they go with it): items, versions, files, logs, closings
    "doc_flow_runs",  # 2.581.0 (#4803): the runs of document flows go with their documents
    "undo_groups",  # 2.747.0 (#5249): the heads of the undo steps (working data, 30 days)
    "hub_callsheets",  # 2.855.0 (#1956): the call sheets go with the bookings of their shoot day
    "office_doc_items", "office_doc_parts", "office_doc_log", "office_payments", "office_signoffs", "office_dunning_marks",
    "office_sub_reminders", "office_contract_files", "office_trip_items", "office_trip_purposes", "office_meal_files",
    "office_meal_choices", "office_meal_log", "office_letter_links", "office_drive_log", "office_drive_closed",
    "office_archive_log", "office_cash_closings", "office_cash_log", "office_bank_imports", "office_bank_balances",
    "office_cc_cards", "office_cc_statements",  # 2.444.0 (#3447): their positions carry the years
    "office_cf_start", "office_cf_adjust", "office_cf_actual", "office_peppol_sends", "office_procdocs", "video_versions",
    "sheet_shares", "sheet_files", "wiki_files", "wiki_shares", "obj_versions", "tchat_files",
    "hub_mail_links", "rc_suggest", "pl_imported", "pl_uploads", "doc_meta", "doc_field_values", "doc_mail", "nl_runs",
    "doc_fetchers", "doc_fetch_portals",  # 2.425.0 C (#3453): a person's receipt fetchers (connections, not content)
))
ODL_PRUNE = {"at": 0.0}


def _year(v):
    try:
        y = int(str(v or "")[:4])
    except ValueError:
        return None
    return y if 1900 < y < 3000 else None


def _until(kind, years):
    """The latest end of the periods of rows from `years`; None when there is none or it is over already (2.152.0 #2167,
    review A8: an expired period keeps nothing, it neither retires an organisation nor a personal office)."""
    ys = [y for y in (_year(v) for v in years) if y]
    end = f"{max(ys) + ret_keep_years(kind)}-12-31" if ys else None  # 2.545.0 (#4595): the law + the buffer
    return end if end and end >= local_now().date().isoformat() else None


# 2.186.0 review M1: the file-store nodes a lock can sit on; olk_fs_locked (receipts/suggest.py) decides which are kept
# (paid / VAT, cash book, equipment, billed, doc_meta.kept_until, #2600; 2.360.4, #3243: open receipts and e-invoices too)
UPG_DOCS = ("(EXISTS(SELECT 1 FROM rc_receipts r WHERE r.node_id=n.id) "
            "OR EXISTS(SELECT 1 FROM doc_meta m WHERE m.node_id=n.id AND (m.kept_until IS NOT NULL OR m.extracted<>'')) "
            "OR EXISTS(SELECT 1 FROM office_cash_entries e WHERE e.node_id=n.id) "
            "OR EXISTS(SELECT 1 FROM office_equipment a WHERE a.receipt_node_id=n.id))")


def odl_file_locks(c, where, arg):
    """[(node id, last day)] of the file-store nodes matching where that deleting for good would refuse now."""
    from ..receipts.suggest import olk_fs_locked
    rows = [(x[0], olk_fs_locked(c, x[0], arrival=True)) for x in c.execute(f"SELECT n.id FROM fs_nodes n WHERE {where}", (arg,)).fetchall()]
    return [x for x in rows if x[1]]


def odl_retention(c, oid):
    """{"counts": {what: n}, "until": "YYYY-12-31" | None}: the office data of organisation (or personal office) oid that
    the law keeps, and the latest end of its periods (None = nothing to keep)."""
    counts, ends = {}, []
    from ..admin.hosting import hosted
    if not oid or hosted():  # 2.152.0 (#2167, decision of 20.10.2026 on #1969): the hosted instance keeps nothing for others (retention export first)
        return {"counts": {}, "until": None}
    with system_ctx(c):  # counts and years only, no content: the deleting admin need not be a member
        for key, kind, sql in ODL_LEGAL:
            years = [r[0] for r in c.execute(sql, (int(oid),)).fetchall()]
            end = _until(kind, years)
            if end:  # review A8: only what is still kept
                counts[key] = len(years)
                ends.append(end)
        years = odl_einvoice_years(c, int(oid))  # 2.239.0 C (#2874)
        end = _until("receipt", years)
        if end:
            counts["einvoices"] = len(years)
            ends.append(end)
        # 2.360.4 (#3243): a file locked on its own (a booking taken back, doc_meta.kept_until) keeps the organisation as well:
        # fs_nodes cascades with it, so a lock met only in the purge could not stay; it is retired instead of failing with a 409.
        # Only these: the rest of what olk_fs_locked asks ODL_LEGAL has counted above
        locked = odl_file_locks(c, "n.org_id=? AND EXISTS(SELECT 1 FROM doc_meta m WHERE m.node_id=n.id AND m.kept_until IS NOT NULL)", int(oid))
        if locked:
            counts.setdefault("receipts", len(locked))
            ends.append(max(x[1] for x in locked))
    ends = [e for e in ends if e]
    return {"counts": counts, "until": max(ends) if ends else None}


def odl_einvoice_years(c, oid):
    """2.239.0 C (#2874): the years of the e-invoices in the documents of office oid that are no receipt (yet): received or
    filed invoices are kept by law, also when nobody took them over as a receipt. The invoice data is sealed per space
    (doc_meta.extracted), so it is opened here; one that cannot be opened counts (the careful side). The caller runs as system."""
    from ..docs.store import doc_open_as
    out = []
    for m in c.execute("SELECT m.node_id, m.ws, m.extracted, m.doc_date, m.created_at FROM doc_meta m WHERE m.org_id=? AND m.extracted<>'' "
                       "AND NOT EXISTS (SELECT 1 FROM rc_receipts r WHERE r.node_id=m.node_id)", (oid,)).fetchall():
        try:
            v = json.loads(doc_open_as(c, m["ws"], "doc_meta.extracted", m["extracted"])[0] or "null")  # as docs/store.meta_json
            hit = isinstance(v, dict) and v.get("_einv") is not None
        except Exception:  # noqa: BLE001 -- not readable: kept
            hit = True
        if hit:
            out.append(m["doc_date"] or m["created_at"])
    return out


def odl_content(c, oid):
    """{what: n} of the content that disappears with organisation oid (wiki pages, tables, office data); zeros left out."""
    with system_ctx(c):  # numbers only, for the admin's confirmation
        out = {k: c.execute(sql, (int(oid),)).fetchone()[0] for k, sql in ODL_CONTENT}
    return {k: v for k, v in out.items() if v}


def odl_more(c, oid):
    """2.272.0 D (#3029): {key: n} of the rest that goes with organisation oid (ODL_MORE, the other tables of the catalogue as
    "other"); zeros left out. Numbers only."""
    named = {t: k for k, _w, t in ODL_MORE}
    out = {}
    with system_ctx(c):  # numbers only, for the admin's confirmation
        refs = [(t, col) for t, col, d in mg_fk_refs(c, "orgs") if d == "c" and t not in ODL_MORE_SKIP]
        if not refs:
            return out
        # 2.370.4 (#3089) N11: one statement (a COUNT per table, UNION ALL) instead of one per table
        sel = " UNION ALL ".join(f"SELECT {n} AS k, COUNT(*) AS n FROM {t} WHERE {col}=?" for n, (t, col) in enumerate(refs))
        for r in c.execute(sel, [int(oid)] * len(refs)).fetchall():
            if r[1]:
                k = named.get(refs[r[0]][0], "other")
                out[k] = out.get(k, 0) + r[1]
    return out


def odl_more_text(counts):
    """"12 mails, 3 deals, 40 other entries" (translated) of odl_more, in the order of ODL_MORE."""
    words = {k: w for k, w, _t in ODL_MORE}
    return ", ".join([trn(*words[k], counts[k]) for k, _w, _t in ODL_MORE if counts.get(k)]
                     + ([trn(*ODL_MORE_OTHER, counts["other"])] if counts.get("other") else []))


def odl_custodian(c, not_uid=None):
    """An instance admin who keeps the files of a retired office (fs_nodes.owner_id must name a person): the acting admin,
    else the first active one. None when there is nobody."""
    mine = g.user["id"] if has_request_context() and g.get("user") is not None else 0
    with system_ctx(c):  # instance structure: who the admins are
        r = c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND COALESCE(kind, 'user')!='agent' AND id!=? "
                      "ORDER BY (id=?) DESC, id LIMIT 1", (int(not_uid or 0), mine)).fetchone()
    return r[0] if r else None


def odl_retired(c, oid):
    """retain_until of a retired organisation, else None."""
    with system_ctx(c):  # instance structure
        r = c.execute("SELECT retired_at, retain_until FROM orgs WHERE id=?", (int(oid),)).fetchone()
    return (r["retain_until"] or "") if r and r["retired_at"] else None


def odl_admin_export(c, oid, retention=False):
    """2.152.0 (#2167, review A4): whether the signed-in person may export the retired organisation oid, never the retired
    personal office of a deleted person (private data, the boundary rule). 2.186.0 A (#2599): only its former admins
    (orgs.retired_admins, noted by odl_retire); an organisation retired before 2.186 (NULL) keeps the old rule: the
    instance admins. 2.239.0 C (#2943): the instance admins (no former admin left) only get the retention export
    (retention=True: the records kept by law), never the whole organisation's export (the operator is no admin of it)."""
    with system_ctx(c):  # instance structure
        r = c.execute("SELECT retired_at, retired_personal, retired_admins FROM orgs WHERE id=?", (int(oid),)).fetchone()
    if not (r and r["retired_at"] and not r["retired_personal"]) or not has_request_context() or g.get("user") is None:
        return False
    ids, alive = odl_ids(r["retired_admins"]), None
    if ids:  # 2.186.0 review M3: none of them left (deleted / disabled, or no person was its admin) = the instance admins
        with system_ctx(c):  # instance structure
            # 2.399.0 (#2687, review F3): hosted, a locked former admin still counts (the operator may lock accounts, so locking
            # them all must not hand it the client's records); only deleted ones are gone
            q = f"SELECT 1 FROM users WHERE id IN ({','.join('?' * len(ids))}){'' if env_bool('KALMIDO_HOSTED', False) else ' AND disabled=0'} LIMIT 1"
            alive = c.execute(q, sorted(ids)).fetchone()
    if r["retired_admins"] is None or not ids or not alive:
        return bool(retention and g.user["is_admin"])
    return g.user["id"] in ids


def odl_ids(v):
    """2.186.0 A (#2599): the ids of orgs.retired_admins ("3,7")."""
    return {int(x) for x in str(v or "").split(",") if x.strip().isdigit()}


def odl_former(c, uid):
    """2.186.0 A (#2599): the retired organisations uid was an admin of -> [{id, name, retain_until}] (their export stays
    with them; they are no members any more)."""
    with system_ctx(c):  # instance structure: the retired organisations naming uid (no content)
        rows = c.execute("SELECT id, name, retain_until, retired_admins FROM orgs WHERE retired_at IS NOT NULL AND retired_personal=0 "
                         "AND retired_admins IS NOT NULL AND retired_admins<>'' ORDER BY id").fetchall()
    return [{"id": r["id"], "name": r["name"], "retain_until": r["retain_until"] or ""} for r in rows if int(uid) in odl_ids(r["retired_admins"])]


def odl_public_off(c, oid):
    """2.360.4 (#3243): before organisation oid's calendars become private (odl_retire): their subscription links go and the
    booking pages that work for it (its office, or one of these calendars) switch off. The task and absence feeds follow the
    membership by themselves; a new link for the calendar, now private, is the owner's own step."""
    c.execute("DELETE FROM ev_cal_feeds WHERE cal_id IN (SELECT id FROM ev_cals WHERE org_id=?)", (oid,))
    c.execute("UPDATE appt_pages SET enabled=0 WHERE office_org_id=? OR cal_id IN (SELECT id FROM ev_cals WHERE org_id=?)", (oid, oid))


def obj_share_gone(c, kind, rid, who):
    """2.924.0 (#5069): every share row of person / agent who on the reference node of core object (kind, rid) goes, deleted
    (the new owner of a calendar / address book needs none; a member leaving it in its own dialog): what deleting the old
    member row did through the mirror trigger of stage 3. Returns the number of rows; the caller commits."""
    with system_ctx(c):  # the node may lie in an organisation's tree; the caller checked
        return c.execute("DELETE FROM fs_shares WHERE node_id IN (SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?) "
                         "AND (user_id=? OR agent_id=?)", (kind, int(rid), int(who), int(who))).rowcount


def obj_nodes_follow(c, oid):
    """2.566.0 (#4712, review F1): the reference nodes of the calendars / address books (the kinds of the shared core whose
    own dialog shares the node, core/objhooks.OBJ node_shares -- 2.924.0, #5069: was members=) that still lie in organisation oid's tree while their object left it (it
    became private: org_leave without an heir, odl_retire, odl_dismantle) follow it into its owner's private tree with their
    shares (core/objects.obj_node_follow). The node stays the object's truth: a share taken back in the core stays taken
    back (its old member row is not read again), a share that lives only in the core stays (was: the node was deleted).
    Call after the object's org_id changed; the caller is in system_ctx."""
    for reg in OBJ.values():
        if reg.get("node_shares"):
            for (rid,) in c.execute(f"SELECT n.ref_id FROM fs_nodes n JOIN {reg['table']} o ON o.id=n.ref_id WHERE n.kind='ref' AND n.ref_kind=? "
                                    "AND n.org_id=? AND o.org_id IS DISTINCT FROM n.org_id ORDER BY n.ref_id", (reg["kind"], int(oid))).fetchall():
                for f in FOLLOW:
                    f(c, reg["kind"], rid)


def odl_members_off(c, oid):
    """2.560.0 (#4697): before organisation oid's calendars and address books become private (odl_retire, odl_dismantle):
    every member row of somebody else than the owner (former colleagues, the organisation's agents, other people's agents)
    ends, and so do the invitations of people to the events of these calendars (as org_leave does for one person). The
    owner keeps the object; their own personal agents stay with it (the owner's delegates). The caller is in system_ctx.
    2.566.0 (#4712): the member rows and the shares of the calendars' / books' nodes are the shared core's revocation
    (person_revoked 'retire', core/objects.py obj_revoke_person: members= of the kinds, restorable rows), which both callers
    run first; only the invitations stay here (they are the events' own data, not a share). Their reference nodes follow the
    objects into their owners' private trees once they are private (obj_nodes_follow, review F1)."""
    c.execute("DELETE FROM event_attendees WHERE user_id IS NOT NULL AND event_id IN (SELECT e.id FROM events e JOIN ev_cals k ON k.id=e.cal_id "
              "WHERE k.org_id=? AND k.owner_id!=event_attendees.user_id AND NOT EXISTS (SELECT 1 FROM agents a WHERE "
              "a.user_id=event_attendees.user_id AND a.owner_id=k.owner_id))", (oid,))


def odl_retire(c, oid, until, gone=None):
    """Retires organisation oid until `until`: members (people and agents) out, its calendars / address books stay with
    their owners (private, as on a deletion) without public ways in, its agents leave it, the e-mail domains no longer let
    anybody in, invoice series, mailboxes and the newsletter sync stop; the data, the file store and the key stay. The
    caller commits."""
    oid = int(oid)
    with system_ctx(c):  # the instance admin (or an account deletion) retires an organisation they need not be in
        # 2.186.0 A (#2599): who was its admin keeps its export (people only; never the deleted person of a personal office)
        adm = [str(r[0]) for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                            "AND m.role='admin' AND COALESCE(u.kind, 'user')!='agent' AND m.user_id!=? ORDER BY m.user_id",
                                            (oid, int(gone or 0))).fetchall()]
        person_revoked(c, None, oid, "retire")  # 2.558.0 (#4709): every share on its nodes, every membership of its rooms (restorable rows)
        c.execute("UPDATE agents SET org_id=NULL WHERE org_id=?", (oid,))
        odl_public_off(c, oid)  # 2.360.4 (#3243)
        odl_members_off(c, oid)  # 2.560.0 (#4697): before org_id=NULL (then the organisation's boundary no longer holds)
        _kids_first(c, oid)  # 2.1032.0 (#5788, review F4): the calendars' / books' children locked before the UPDATEs below
        c.execute("UPDATE ev_cals SET org_id=NULL WHERE org_id=?", (oid,))
        c.execute("UPDATE books SET org_id=NULL, owner_org_id=NULL WHERE org_id=?", (oid,))
        obj_nodes_follow(c, oid)  # 2.566.0 (#4712, review F1): their nodes follow them into the owners' private trees
        c.execute("DELETE FROM org_members WHERE org_id=?", (oid,))
        c.execute("DELETE FROM org_joins WHERE org_id=?", (oid,))  # 2.223.2 A (#2859): no way back in by an open invitation
        c.execute("DELETE FROM org_invites WHERE org_id=?", (oid,))
        c.execute("UPDATE office_inv_series SET active=0 WHERE org_id=?", (oid,))
        # 2.152.0 (#2167, review A7): no new data flows in any more (mail polling, newsletter sync)
        c.execute("UPDATE hub_mailboxes SET active=0 WHERE org_id=?", (oid,))
        c.execute("UPDATE nl_conns SET auto=0 WHERE org_id=?", (oid,))
        keeper = odl_custodian(c, gone)  # review F6: only the deleted person is left out, never the acting admin
        if keeper:  # its files must not go with the account of a former member later (fs_nodes.owner_id cascades)
            c.execute("UPDATE fs_nodes SET owner_id=? WHERE org_id=?", (keeper, oid))
        c.execute("UPDATE orgs SET retired_at=?, retain_until=?, domains='', retired_admins=? WHERE id=?", (iso(now_utc()), until, ",".join(adm), oid))
    print(f"organisation {oid} retired: kept until {until} (legal retention, #2167)", flush=True)


def _kids_first(c, oid):
    """2.1032.0 (#5788, review F4 of 2.1017): the UPDATE of the calendars / address books of the given organisation carries org_id
    into their events / contacts (trigger core/orgrows.py kalmido_orw_carry): the object's row, then its children -- the
    trash (core/writes.py obj_trash) and a child's own save (an event: its row, then cal_touch on the calendar; a contact:
    its row, then book_touch on the book) take the children first, so one of two could get a deadlock. Now the calendars'
    locks and their events (obj_kids_first), then the books' contacts, all before the UPDATEs."""
    ids = [r[0] for r in c.execute("SELECT id FROM ev_cals WHERE org_id=? ORDER BY id", (int(oid),)).fetchall()]
    for reg in OBJ.values():  # the calendar's kind as the core registered it (events/evkern.py; no import of the events layer)
        if reg.get("table") == "ev_cals" and ids:
            for f in KIDS_FIRST:  # core/writes.obj_kids_first (the hook: core.writes stands above the accounts layer)
                f(c, reg["kind"], ids)
    # address books have no children in the core (obj_register): their contacts locked here the same way (book id order)
    for (bid,) in c.execute("SELECT id FROM books WHERE org_id=? ORDER BY id", (int(oid),)).fetchall():
        c.execute("SELECT id FROM contacts WHERE book_id=? ORDER BY id FOR NO KEY UPDATE", (bid,)).fetchall()


def odl_tchat_files(c, oid):
    """2.190.0 B (#2561): the stored team chat files sealed with organisation oid's key, for odl_dismantle to unlink after the
    commit (the rows go with the organisation); their recognised texts go now (as files/textscan.py ts_forget)."""
    rows = c.execute("SELECT id, path FROM tchat_files WHERE org_id=?", (int(oid),)).fetchall()
    if rows:
        c.execute(f"DELETE FROM file_text WHERE kind='tchat' AND ref_id IN ({','.join('?' * len(rows))})", [x["id"] for x in rows])
    return [x["path"] for x in rows if x["path"]]


odl_before_delete = []  # 2.209.0 D (#1856): fn(c, oid) of higher packages, called right before the organisation's row goes


def odl_dismantle(c, oid):
    """Deletes organisation (or personal office) oid for good: the trash of its file store, its key, the row (the rest
    cascades). Returns what to remove after the caller committed: file paths (relative to ATT_DIR) and clean-ups
    (callables, see core/serializers.unlink_files) for the office folder and the picture."""
    from ..admin.orgcrypt_cli import before_org_delete
    from ..files.store import fs_org_purge
    oid = int(oid)
    with system_ctx(c):  # the instance admin (or an account deletion) removes an organisation they need not be in
        files = fs_org_purge(c, oid)
        from ..wiki.wikiatt import wka_org_files
        files += wka_org_files(c, oid)  # 2.99.0 A (#2182): files of its knowledge pages (the rows go with the organisation)
        from ..sheets.shkinds import shk_org_files
        files += shk_org_files(c, oid)  # 2.124.0 B (#2110): files of its tables' file cells
        files += odl_tchat_files(c, oid)  # 2.190.0 B (#2561): team chat files sealed with its key
        c.execute("UPDATE agents SET org_id=NULL WHERE org_id=?", (oid,))
        person_revoked(c, None, oid, "retire")  # 2.566.0 (#4712): the core closes the calendars' and books' shares (as odl_retire)
        odl_members_off(c, oid)  # 2.560.0 (#4697): as odl_retire
        _kids_first(c, oid)  # 2.1032.0 (#5788, review F4): as odl_retire
        c.execute("UPDATE ev_cals SET org_id=NULL WHERE org_id=?", (oid,))  # 2.30.0 (#1036): they stay with their owners, private
        c.execute("UPDATE books SET org_id=NULL, owner_org_id=NULL WHERE org_id=?", (oid,))  # 2.52.0 C (#1438)
        obj_nodes_follow(c, oid)  # 2.566.0 (#4712, review F1): as odl_retire (fs_org_purge removed the top nodes already)
        # 2.42.0 (#828): files of lists that left the organisation are sealed with their new organisation's key (or plain),
        # then the organisation's key is destroyed and its office folder (stored invoices, archive) removed
        if before_org_delete(c, oid)[1]:  # 2.64.0 (#1864): a file that lives on could not be resealed: keep the key
            raise Denied(409, tr("Some files could not be encrypted again for their new place. Nothing was deleted; see the server log."))
        oc_drop_key(c, oid)
        for fn in odl_before_delete:  # 2.209.0 D (#1856): e.g. texts of files that left it move along (files/textscan.py)
            fn(c, oid)
        icon = (c.execute("SELECT icon FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
        # 2.223.3 B (#2878): its clients go with it (contact persons cascade), never to the person who created them (org_id
        # SET NULL would make them that person's private clients); one kept by another workspace's records moves there
        from ..team.clients import cl_org_purge
        cl_org_purge(c, oid)
        c.execute("DELETE FROM time_sheets WHERE org_id=? AND user_id IS NULL", (oid,))  # 2.360.2 D (#2561): a deleted person's months end here
        # 2.627.0 (#4504, review F2): the organisation's standard arrangements of the views (global settings) go with it
        for k in WG_STD_KEYS:
            c.execute("DELETE FROM settings WHERE key IN (?,?)", (wg_org_k(oid, k), wg_org_k(oid, k, True)))
        c.execute("DELETE FROM orgs WHERE id=?", (oid,))

    def after():
        from .orgs import oc_drop_office_dir
        oc_drop_office_dir(oid)
        org_icon_drop_file(oid, icon)  # 2.87.9 (#1913)
    return files + [after]


def odl_retired_prune(c, force=False):
    """The watchdog (at most every six hours): retired organisations past retain_until go for good -- only with the switch
    (ret_on("trash")), else they are counted (GET /api/admin/retention)."""
    import time
    if not force and time.time() - ODL_PRUNE["at"] < 6 * 3600:
        return 0
    ODL_PRUNE["at"] = time.time()
    today = local_now().date().isoformat()
    with system_ctx(c):  # retention run over every organisation (no person's context, nothing handed out)
        due = [r[0] for r in c.execute("SELECT id FROM orgs WHERE retired_at IS NOT NULL AND retain_until IS NOT NULL "
                                       "AND retain_until!='' AND retain_until<? AND ret_hold_at IS NULL", (today,)).fetchall()]  # 2.545.0 (#4595): not while held
    on, n = ret_on("trash"), 0
    for oid in due if on else ():
        until = odl_retention(c, oid)["until"]
        if until and until >= today:  # newer data meanwhile (an export / import): kept longer
            with system_ctx(c):  # see above
                c.execute("UPDATE orgs SET retain_until=? WHERE id=?", (until, oid))
            c.commit()
            continue
        try:
            with c.savepoint():
                todo = odl_dismantle(c, oid)
        except Denied:  # a file that could not be resealed keeps it (tried again next time)
            continue
        c.commit()
        unlink_files(todo)
        n += 1
        print(f"organisation {oid}: retention period over, deleted for good (#2167)", flush=True)
    ret_report(c, "trash", {"retired_orgs": n if on else len(due)}, on, run="retired_orgs")  # own slot (core/retention.py)
    c.commit()
    return n


# ---------------------------------------------------------------- #2164: the account deletion (users.user_purge)
def upg_personal_state(c, uid):
    """(personal office id | None, odl_retention of it incl. the booked receipts of the private file store, their node ids)."""
    with system_ctx(c):  # the deleted person's own office and private receipts (counts / ids, nothing handed out)
        r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (int(uid),)).fetchone()
        from ..admin.hosting import hosted  # 2.152.0 (#2164, review A3): the hosted instance keeps nothing for others (rx_gate first)
        # review A8: only while their period runs; 2.360.4 (#3243): all the purge would refuse, so no lock stops the deletion
        rows = [] if hosted() else odl_file_locks(c, f"n.owner_id=? AND n.org_id IS NULL AND {UPG_DOCS}", int(uid))
    poid = r[0] if r else None
    ret = odl_retention(c, poid)
    end = max((x[1] for x in rows), default=None)
    if not end:
        return poid, ret, []
    ret["counts"]["receipts"] = ret["counts"].get("receipts", 0) + len(rows)
    ret["until"] = max(e for e in (ret["until"], end) if e)
    return poid, ret, [x[0] for x in rows]


def upg_personal(c, uid):
    """The personal office of the deleted account uid: without legal data dismantled with its files (returned for after
    the commit), with legal data retired (the receipts of the private file store move into it with their files, an
    instance admin keeps them). The caller commits."""
    if upg_heirless(c, uid):  # 2.239.0 C (#2866): before anything changes (files are copied below)
        raise Denied(409, tr(UPG_NO_HEIR))
    ret_need_unheld(c, ret_person_office(c, uid))  # 2.545.0 (#4595): the extended lock of the personal office stops it
    poid, ret, nodes = upg_personal_state(c, uid)
    if not ret["until"]:
        return odl_dismantle(c, poid) if poid else []
    keeper = odl_custodian(c, uid)
    if not keeper:
        raise Denied(409, tr("This account's office keeps invoices or receipts by law, and no other admin could keep them. Disable the account instead."))
    u = c.execute("SELECT username, display_name FROM users WHERE id=?", (int(uid),)).fetchone()
    with system_ctx(c):  # the deleted person's own office (no organisation admin context involved)
        if not poid:
            poid = insert_id(c, "INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (f"private-{int(uid)}", "", iso(now_utc())))
        from ..files.fsmove import fsm_doc, fsm_text, fsm_versions
        new_paths, old_paths = [], []
        for nid in nodes:  # out of its private folder (that goes) into the retired office, sealed for it before the key goes
            c.execute("UPDATE fs_nodes SET parent_id=NULL, org_id=?, owner_id=? WHERE id=?", (poid, keeper, nid))
            c.execute("UPDATE rc_receipts SET org_id=? WHERE node_id=?", (poid, nid))
            # 2.152.0 review F1: re-seal every version (and the document data) for the office: the account key goes below
            nm = (c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone() or [""])[0]
            try:
                fsm_doc(c, nid, poid, keeper, uid, nm, new_paths, old_paths, df_define=True)  # 2.184.0 B (#2580)
                fsm_versions(c, nid, poid, new_paths, old_paths)
                fsm_text(c, nid, poid, keeper)
            except BaseException:
                for f in new_paths:  # the copies made so far (the caller rolls back)
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                raise
        c.execute("UPDATE fs_nodes SET owner_id=? WHERE org_id=? AND owner_id=?", (keeper, poid, int(uid)))
        name = (u["display_name"] or u["username"]) if u else f"private-{int(uid)}"
        c.execute("UPDATE orgs SET personal_of=NULL, retired_personal=1, name=? WHERE id=?", (name[:80], poid))
    odl_retire(c, poid, ret["until"], gone=uid)
    return old_paths  # the versions sealed with the account key, removed after the commit


def upg_heir(c, oid, uid):
    """An active person of organisation oid (not uid) who takes over its projects / calendars from the deleted account:
    an admin first. 2.239.0 C (#2866): only an admin or a member -- a guest, read-only or accounting person never becomes
    the owner. None when there is none."""
    with system_ctx(c):  # membership structure of the organisation
        r = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=?
                         AND COALESCE(u.kind, '')!='agent' AND u.disabled=0 AND m.role IN ('admin', 'member')
                         ORDER BY (m.role='admin') DESC, m.user_id LIMIT 1""",
                      (oid, uid)).fetchone()
    return r[0] if r else None


UPG_NO_HEIR = N_("The organisation needs another admin or member first: nobody could take over this account's projects or calendars of the organisation. Disable the account instead.")


def upg_heirless(c, uid):
    """2.239.0 C (#2866): the organisations whose projects (of the account's agents) or calendars nobody may take over from
    account uid -- no other active admin or member (a calendar of an organisation without any other person goes as before).
    Asked before anything is changed (upg_personal), so the refusal leaves no half-done deletion."""
    uid, out = int(uid), set()
    with system_ctx(c):  # membership structure of every organisation of the account (numbers only)
        need = {r[0] for r in c.execute("SELECT DISTINCT l.org_id FROM lists l JOIN agents a ON a.user_id=l.owner_id WHERE a.owner_id=? "
                                        "AND l.is_inbox=0 AND l.org_id IS NOT NULL", (uid,))}
        for (oid,) in c.execute("SELECT DISTINCT org_id FROM ev_cals WHERE owner_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
            if c.execute("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=? "
                         "AND COALESCE(u.kind, '')!='agent' AND u.disabled=0 LIMIT 1", (oid, uid)).fetchone():
                need.add(oid)
        for reg in OBJ.values():  # 2.558.0 (#4709, review F1): the organisations' objects of the shared core go to the heir too
            if reg["base_role"] is None:
                for (oid,) in c.execute(f"SELECT DISTINCT org_id FROM {reg['table']} WHERE owner_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
                    if c.execute("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=? "
                                 "AND COALESCE(u.kind, '')!='agent' AND u.disabled=0 LIMIT 1", (oid, uid)).fetchone():
                        need.add(oid)
    for oid in need:
        if not upg_heir(c, oid, uid):
            out.add(oid)
    return sorted(out)


def upg_rest(c, uid):
    """Everything of the account uid that must not vanish with it (or must vanish properly): its own agents (with their
    tokens), the organisations' calendars (to an admin of the organisation, as on leaving it), time entries of
    organisation projects (kept, without the person), direct messages (kept for the partner), mentions and log rows
    (the person's id cleared), the inbox (with its files). Returns what to remove after the commit."""
    from ..agents.admin import agent_delete
    from ..lists.listtrash import otr_drop_files
    from ..tasks.tasks import hard_delete
    from ..lists.lists import list_purge
    uid, todo = int(uid), []
    with system_ctx(c):  # the deleted person's rows in every organisation (an instance admin deletes accounts of organisations they are not in)
        from ..lists.ownership import owner_transfer
        for (aid, av) in c.execute("SELECT a.user_id, u.avatar FROM agents a JOIN users u ON u.id=a.user_id WHERE a.owner_id=?", (uid,)).fetchall():
            # 2.152.0 (#2164, review A5): the agent's lists never cross the boundary: an organisation's list goes to a person
            # of that organisation, a private one goes like the inbox
            for lr in c.execute("SELECT * FROM lists WHERE owner_id=? AND is_inbox=0", (aid,)).fetchall():
                if lr["org_id"]:
                    heir = upg_heir(c, lr["org_id"], uid)
                    if not heir:
                        raise Denied(409, tr("Nobody could take over the projects of this account's agents. Disable the account instead."))
                    owner_transfer(c, lr, heir, force=True)  # must happen, as on leaving an organisation
                    continue
                lid = lr["id"]
                files = hard_delete(c, [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))], lists={lid})
                icon, lfiles = list_purge(c, lid, None)
                todo.append(lambda lid=lid, icon=icon, f=lfiles + files: otr_drop_files(lid, icon, f))
            todo += agent_delete(c, aid, None)  # no lists left to hand on; its token goes with it (api_tokens cascade)
            todo.append(lambda aid=aid, av=av: avatar_drop_file(aid, av))
        for (xid, oid) in c.execute("SELECT id, org_id FROM ev_cals WHERE owner_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
            heir = upg_heir(c, oid, uid)
            if heir:
                obj_share_gone(c, "evcal", xid, heir)  # 2.924.0 (#5069): the new owner needs no share (was its old member row)
                c.execute("UPDATE ev_cals SET owner_id=? WHERE id=?", (heir, xid))
        from ..personal.timesheet import tsl_user_gone
        tsl_user_gone(c, uid)  # 2.360.2 D (#2561): before the entries lose the person (its hours are noted on the month)
        # 2.360.2 D (#2561): private approval records have nobody else: the left-overs of deleted reviews, those of its own reviews (cascade below)
        gone = [r[0] for r in c.execute("""DELETE FROM office_signoffs WHERE kind='video' AND org_id IS NULL AND ((video_id IS NULL AND created_by=?)
                     OR video_id IN (SELECT id FROM video_reviews WHERE owner_id=? AND org_id IS NULL)) RETURNING id""", (uid, uid)).fetchall()]
        # 2.1004.0 (#5494): a record of the core's trash (kind osignoff, office/signoff.py) leaves no core history behind
        obj_rows_drop_many(c, "osignoff", gone)
        c.execute("UPDATE time_entries SET user_id=NULL WHERE user_id=? AND list_id IN (SELECT id FROM lists WHERE org_id IS NOT NULL)", (uid,))
        # 2.152.0 review F4: a direct room whose partner is gone already (or a note to oneself) goes with its messages
        c.execute("DELETE FROM tchat_rooms WHERE kind='dm' AND ((a=? AND (b IS NULL OR b=?)) OR (b=? AND a IS NULL))", (uid, uid, uid))
        c.execute("UPDATE tchat_rooms SET a=NULL WHERE kind='dm' AND a=? AND b IS NOT NULL AND b!=?", (uid, uid))
        c.execute("UPDATE tchat_rooms SET b=NULL WHERE kind='dm' AND b=? AND a IS NOT NULL AND a!=?", (uid, uid))
        upg_mentions(c, uid)
        for sql in ("UPDATE activity SET user_id=NULL WHERE user_id=?", "UPDATE list_activity SET user_id=NULL WHERE user_id=?",
                    "UPDATE fs_log SET user_id=NULL WHERE user_id=?", "UPDATE org_list_log SET by_id=NULL WHERE by_id=?",
                    "UPDATE org_list_log SET owner_id=NULL WHERE owner_id=?", "UPDATE org_list_log SET to_id=NULL WHERE to_id=?",
                    "UPDATE sheet_changes SET agent_id=NULL WHERE agent_id=?"):
            c.execute(sql, (uid,))
        upg_alerts(c, uid)  # 2.239.0 C (#2866 / #2888): the admin alerts name the account by its number only
        # the inbox (the caller settled the rest); 2.186.0 A (#2566): not a project with receipts kept in the trash by law
        for (lid,) in c.execute("SELECT id FROM lists WHERE owner_id=? AND COALESCE(retain_until, '')=''", (uid,)).fetchall():
            files = hard_delete(c, [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))], lists={lid})
            icon, lfiles = list_purge(c, lid, None)
            todo.append(lambda lid=lid, icon=icon, f=lfiles + files: otr_drop_files(lid, icon, f))
    return todo


def upg_alerts(c, uid):
    """2.239.0 C (#2866 / #2888): the stored admin alerts that name the deleted account uid (user name, e-mail address or
    display name as a whole word, in the text, the arguments of its template and its key) name "#<id>" instead."""
    u = c.execute("SELECT username, email, display_name FROM users WHERE id=?", (int(uid),)).fetchone()
    if not u:
        return
    dn = (u["display_name"] or "").strip()  # a lone first name ("Max") is too common a word: only a full name counts
    names = sorted({x.strip() for x in (u["username"], u["email"], dn if " " in dn else "") if x and len(x.strip()) >= 3}, key=len, reverse=True)
    if not names:
        return
    rx = re.compile(r"(?<![\w.@-])(?:" + "|".join(re.escape(x) for x in names) + r")(?![\w.@-])", re.I)
    sub = lambda v: rx.sub(f"#{int(uid)}", v) if isinstance(v, str) else v  # noqa: E731
    like = " OR ".join(["message ILIKE ? OR tmpl ILIKE ? OR key ILIKE ?"] * len(names))
    pat = [f"%{x}%" for x in names for _ in range(3)]
    for r in c.execute(f"SELECT id, key, message, tmpl FROM admin_alerts WHERE {like}", pat).fetchall():
        try:
            t = json.loads(r["tmpl"] or "[]")  # [text, n, args, click] (notify/alerts.aa_emit): every value after the text
            deep = lambda v: [deep(x) for x in v] if isinstance(v, list) else sub(v)  # noqa: E731
            tmpl = json.dumps(t[:1] + [deep(x) for x in t[1:]] if isinstance(t, list) else t, ensure_ascii=False)
        except ValueError:
            tmpl = sub(r["tmpl"] or "")
        c.execute("UPDATE admin_alerts SET key=?, message=?, tmpl=? WHERE id=?", (sub(r["key"])[:200], sub(r["message"]), tmpl, r["id"]))


UPG_MENTION = "<@{0}>"


def upg_mentions(c, uid):
    """Mentions of the deleted person in comments and chat messages (plain text; locked ones the server cannot read stay)
    become the words "@Deleted user"; the id leaves the comments' mention lists."""
    tok, word = UPG_MENTION.format(int(uid)), "@" + tr("Deleted person")
    for table in ("obj_comments", "tchat_msgs"):  # 2.972.0 (#5272): the task comments live in obj_comments
        extra = " AND enc IS NULL" if table == "tchat_msgs" else ""
        c.execute(f"UPDATE {table} SET body=replace(body, ?, ?) WHERE body LIKE ?{extra}", (tok, word, f"%{tok}%"))  # pg-ok: the token is <@digits>, case does not matter
    c.execute("UPDATE obj_comments SET mentions=array_remove(mentions, ?::bigint) WHERE ?::bigint = ANY(mentions)", (int(uid), int(uid)))


def upg_info(c, uid):
    """For the delete dialog (useradmin.ua8_delete_info): what is deleted, handed on and kept by law."""
    poid, ret, _ = upg_personal_state(c, uid)
    with system_ctx(c):  # numbers only, for the deleting admin
        one = lambda sql: c.execute(sql, (int(uid),)).fetchone()[0]  # noqa: E731
        info = {"agents": one("SELECT COUNT(*) FROM agents WHERE owner_id=?"),
                "calendars": one("SELECT COUNT(*) FROM ev_cals WHERE owner_id=? AND org_id IS NOT NULL"),
                "time_kept": one("SELECT COUNT(*) FROM time_entries t JOIN lists l ON l.id=t.list_id WHERE t.user_id=? AND l.org_id IS NOT NULL"),
                "sheets_kept": one("SELECT COUNT(*) FROM time_sheets t JOIN orgs o ON o.id=t.org_id WHERE t.user_id=? AND o.personal_of IS NULL")}  # 2.360.2 D (#2561)
        info["dms"] = c.execute("SELECT COUNT(*) FROM tchat_rooms WHERE kind='dm' AND (a=? OR b=?) AND a IS NOT NULL AND b IS NOT NULL "
                                "AND a!=b AND last_at IS NOT NULL", (int(uid), int(uid))).fetchone()[0]
        # 2.533.0 (#4318) B42: the files the person sent in direct messages / groups are sealed with their key and go for good
        # (collab/teamchan.tcx_user_purge, same rows): the dialog says so instead of only the number of conversations
        info["chat_files"] = c.execute("SELECT COUNT(*) FROM tchat_files f JOIN tchat_rooms r ON r.id=f.room_id "
                                       "WHERE f.user_id=? AND f.org_id IS NULL AND r.kind!='list'", (int(uid),)).fetchone()[0]
    content = odl_content(c, poid) if poid else {}
    info["no_heir"] = tr(UPG_NO_HEIR) if upg_heirless(c, uid) else ""  # 2.360.4 (#3243): said in the dialog, not by the 409 afterwards
    from ..admin.purgeshare import ush_info
    info["shared"] = ush_info(c, uid)  # 2.508.0 (#4301): private shared calendars, address books, tables, knowledge pages
    info.update(office="keep" if ret["until"] else ("delete" if content else None), office_counts=content,
                kept=ret["counts"], kept_until=ret["until"])
    return info


# ---------------------------------------------------------------- one-shot: foreign keys that must not cascade any more
UPG_FK = (("time_entries", "user_id", "SET NULL"), ("tchat_rooms", "a", "SET NULL"), ("tchat_rooms", "b", "SET NULL"),
          ("time_sheets", "user_id", "SET NULL"))  # 2.360.2 D (#2561)


def upg_fk_once(c):
    """2.152.0 A (#2164): at the start (core/db.py init, idempotent): an account's deletion keeps the time entries of
    organisation projects (time_entries.user_id may be NULL now) and the direct messages for the partner (tchat_rooms
    a / b ON DELETE SET NULL instead of CASCADE). 2.102 runs on with it (it never writes NULL there). 2.360.2 D (#2561): the
    organisations' monthly timesheets too (flag migr_upg2360; an older program skips those rows in its review)."""
    n = 0
    for table, col, rule in UPG_FK:
        rows = c.execute("SELECT con.conname, con.confdeltype FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid "  # pg-ok: catalog oid (Postgres only)
                         "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(con.conkey) "  # pg-ok: catalog oid (Postgres only)
                         "WHERE con.contype='f' AND t.relname=? AND a.attname=? AND t.relnamespace=to_regnamespace(current_schema())",
                         (table, col)).fetchall()
        if any(r[1] == "n" for r in rows):
            continue
        if table in ("time_entries", "time_sheets"):
            c.execute(f"ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL")
        for r in rows:
            c.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{r[0]}"')
        c.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{col}_fkey FOREIGN KEY ({col}) REFERENCES users(id) ON DELETE {rule}")
        n += 1
    if n:
        print(f"accounts (#2164): {n} foreign key(s) no longer delete along with an account", flush=True)
    return n

