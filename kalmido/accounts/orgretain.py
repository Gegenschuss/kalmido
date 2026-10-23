"""2.152.0 A (#2164 #2167): what an organisation (or a person's personal office) must keep by law, and what happens to it
when it is deleted.

odl_retention(c, oid) counts the office data under a legal retention period (finalised documents and archive entries:
books, cash book, bank statements: 10 years; booked receipts, receipts of trips taken into DATEV, entertainment receipts, the logbook: 8 years -- core/retention.py
RET_LEGAL_YEARS, from the end of the calendar year) and gives the latest end. An organisation with such data is not
deleted but retired (orgs.retired_at / retain_until): members out, data and key stay, nobody sees it in the app any more
but the instance admins (list "Organisations": kept until ..., export only); the watchdog removes it for good after
retain_until (odl_retired_prune, kind "trash", switch ret_on). Without such data the deletion goes as before, after a
confirmation when wiki pages, tables or office data would go along (409 with the numbers, then ?confirm=1).

The account deletion (users.user_purge) uses the same: the personal office is dismantled with its files (no legal data)
or retired; the rest of the account goes (upg_* helpers).
"""
import os
from datetime import date

from flask import g, has_request_context

from ..core.access import Denied
from ..core.db import iso, now_utc
from ..core.i18n import tr
from ..core.pg import system_ctx
from ..core.retention import RET_LEGAL_YEARS, ret_on, ret_report

# (count key, legal kind, SQL of the years per row: org_id = ?) -- the year a period starts from (its end + N years)
ODL_LEGAL = (
    ("documents", "book", "SELECT substr(COALESCE(NULLIF(date, ''), locked_at), 1, 4) FROM office_docs "
                          "WHERE org_id=? AND locked_at IS NOT NULL"),
    ("archive", "book", "SELECT substr(COALESCE(NULLIF(date, ''), created_at), 1, 4) FROM office_archive WHERE org_id=?"),
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
    ("meals", "receipt", "SELECT substr(date, 1, 4) FROM office_meals WHERE org_id=? AND status<>'draft'"),
    # 2.184.0 A (#2628): sent letters (business letters, 6 years from the year they went out)
    ("letters", "letter", "SELECT substr(COALESCE(NULLIF(sent_at, ''), NULLIF(letter_date, ''), created_at), 1, 4) FROM office_letters "
                          "WHERE org_id=? AND status<>'draft'"),
)
# what goes along with an organisation without legal data: shown before (409), deleted only with ?confirm=1
ODL_CONTENT = (
    ("wiki_pages", "SELECT COUNT(*) FROM wiki_pages WHERE org_id=? AND deleted_at IS NULL"),
    ("tables", "SELECT COUNT(*) FROM sheets WHERE org_id=? AND deleted_at IS NULL"),
    ("office_documents", "SELECT COUNT(*) FROM office_docs WHERE org_id=?"),
    ("office_archive", "SELECT COUNT(*) FROM office_archive WHERE org_id=?"),
    ("trips", "SELECT COUNT(*) FROM office_trips WHERE org_id=?"),
    ("drives", "SELECT COUNT(*) FROM office_drives WHERE org_id=?"),
    ("clients", "SELECT COUNT(*) FROM clients WHERE org_id=?"),
)
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
    end = f"{max(ys) + RET_LEGAL_YEARS[kind]}-12-31" if ys else None
    return end if end and end >= date.today().isoformat() else None


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
    ends = [e for e in ends if e]
    return {"counts": counts, "until": max(ends) if ends else None}


def odl_content(c, oid):
    """{what: n} of the content that disappears with organisation oid (wiki pages, tables, office data); zeros left out."""
    with system_ctx(c):  # numbers only, for the admin's confirmation
        out = {k: c.execute(sql, (int(oid),)).fetchone()[0] for k, sql in ODL_CONTENT}
    return {k: v for k, v in out.items() if v}


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


def odl_admin_export(c, oid):
    """2.152.0 (#2167, review A4): whether any instance admin may export organisation oid: a retired organisation, never
    the retired personal office of a deleted person (private data, the boundary rule)."""
    with system_ctx(c):  # instance structure
        r = c.execute("SELECT retired_at, retired_personal FROM orgs WHERE id=?", (int(oid),)).fetchone()
    return bool(r and r["retired_at"] and not r["retired_personal"])


def odl_retire(c, oid, until, gone=None):
    """Retires organisation oid until `until`: members (people and agents) out, its calendars / address books stay with
    their owners (private, as on a deletion), its agents leave it, the e-mail domains no longer let anybody in, invoice
    series, mailboxes and the newsletter sync stop; the data, the file store and the key stay. The caller commits."""
    oid = int(oid)
    with system_ctx(c):  # the instance admin (or an account deletion) retires an organisation they need not be in
        c.execute("UPDATE agents SET org_id=NULL WHERE org_id=?", (oid,))
        c.execute("UPDATE ev_cals SET org_id=NULL WHERE org_id=?", (oid,))
        c.execute("UPDATE books SET org_id=NULL, owner_org_id=NULL WHERE org_id=?", (oid,))
        c.execute("DELETE FROM org_members WHERE org_id=?", (oid,))
        c.execute("UPDATE office_inv_series SET active=0 WHERE org_id=?", (oid,))
        # 2.152.0 (#2167, review A7): no new data flows in any more (mail polling, newsletter sync)
        c.execute("UPDATE hub_mailboxes SET active=0 WHERE org_id=?", (oid,))
        c.execute("UPDATE nl_conns SET auto=0 WHERE org_id=?", (oid,))
        keeper = odl_custodian(c, gone)  # review F6: only the deleted person is left out, never the acting admin
        if keeper:  # its files must not go with the account of a former member later (fs_nodes.owner_id cascades)
            c.execute("UPDATE fs_nodes SET owner_id=? WHERE org_id=?", (keeper, oid))
        c.execute("UPDATE orgs SET retired_at=?, retain_until=?, domains='' WHERE id=?", (iso(now_utc()), until, oid))
    print(f"organisation {oid} retired: kept until {until} (legal retention, #2167)", flush=True)


def odl_dismantle(c, oid):
    """Deletes organisation (or personal office) oid for good: the trash of its file store, its key, the row (the rest
    cascades). Returns what to remove after the caller committed: file paths (relative to ATT_DIR) and clean-ups
    (callables, see core/serializers.unlink_files) for the office folder and the picture."""
    from ..admin.orgcrypt_cli import before_org_delete
    from ..core.orgcrypt import oc_drop_key
    from ..files.store import fs_org_purge
    oid = int(oid)
    with system_ctx(c):  # the instance admin (or an account deletion) removes an organisation they need not be in
        files = fs_org_purge(c, oid)
        from ..wiki.wikiatt import wka_org_files
        files += wka_org_files(c, oid)  # 2.99.0 A (#2182): files of its knowledge pages (the rows go with the organisation)
        from ..sheets.shkinds import shk_org_files
        files += shk_org_files(c, oid)  # 2.124.0 B (#2110): files of its tables' file cells
        c.execute("UPDATE agents SET org_id=NULL WHERE org_id=?", (oid,))
        c.execute("UPDATE ev_cals SET org_id=NULL WHERE org_id=?", (oid,))  # 2.30.0 (#1036): they stay with their owners, private
        c.execute("UPDATE books SET org_id=NULL, owner_org_id=NULL WHERE org_id=?", (oid,))  # 2.52.0 C (#1438)
        # 2.42.0 (#828): files of lists that left the organisation are sealed with their new organisation's key (or plain),
        # then the organisation's key is destroyed and its office folder (stored invoices, archive) removed
        if before_org_delete(c, oid)[1]:  # 2.64.0 (#1864): a file that lives on could not be resealed: keep the key
            raise Denied(409, tr("Some files could not be encrypted again for their new place. Nothing was deleted; see the server log."))
        oc_drop_key(c, oid)
        icon = (c.execute("SELECT icon FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
        c.execute("DELETE FROM orgs WHERE id=?", (oid,))

    def after():
        from .orgs import oc_drop_office_dir
        from .pictures import org_icon_drop_file
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
    from ..core.serializers import unlink_files
    today = date.today().isoformat()
    with system_ctx(c):  # retention run over every organisation (no person's context, nothing handed out)
        due = [r[0] for r in c.execute("SELECT id FROM orgs WHERE retired_at IS NOT NULL AND retain_until IS NOT NULL "
                                       "AND retain_until!='' AND retain_until<?", (today,)).fetchall()]
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
UPG_BOOKED = ("SELECT r.node_id, substr(COALESCE(NULLIF(m.doc_date, ''), NULLIF(r.paid_at, ''), r.set_at), 1, 4) FROM rc_receipts r "
              "JOIN fs_nodes n ON n.id=r.node_id LEFT JOIN doc_meta m ON m.node_id=r.node_id WHERE n.owner_id=? AND n.org_id IS NULL "
              "AND (r.paid_at IS NOT NULL OR r.vat_pct IS NOT NULL)")  # review F5: the rule of olk_fs_locked


def upg_personal_state(c, uid):
    """(personal office id | None, odl_retention of it incl. the booked receipts of the private file store, their node ids)."""
    with system_ctx(c):  # the deleted person's own office and private receipts (counts / ids, nothing handed out)
        r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (int(uid),)).fetchone()
        from ..admin.hosting import hosted  # 2.152.0 (#2164, review A3): the hosted instance keeps nothing for others (rx_gate first)
        rows = [] if hosted() else c.execute(UPG_BOOKED, (int(uid),)).fetchall()
    poid = r[0] if r else None
    ret = odl_retention(c, poid)
    end = _until("receipt", [x[1] for x in rows])  # review A8: None when their period is over
    if not end:
        return poid, ret, []
    ret["counts"]["receipts"] = ret["counts"].get("receipts", 0) + len(rows)
    ret["until"] = max(e for e in (ret["until"], end) if e)
    return poid, ret, [x[0] for x in rows]


def upg_personal(c, uid):
    """The personal office of the deleted account uid: without legal data dismantled with its files (returned for after
    the commit), with legal data retired (the receipts of the private file store move into it with their files, an
    instance admin keeps them). The caller commits."""
    poid, ret, nodes = upg_personal_state(c, uid)
    if not ret["until"]:
        return odl_dismantle(c, poid) if poid else []
    keeper = odl_custodian(c, uid)
    if not keeper:
        raise Denied(409, tr("This account's office keeps invoices or receipts by law, and no other admin could keep them. Disable the account instead."))
    u = c.execute("SELECT username, display_name FROM users WHERE id=?", (int(uid),)).fetchone()
    with system_ctx(c):  # the deleted person's own office (no organisation admin context involved)
        if not poid:
            from ..core.pg import insert_id
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
    with system_ctx(c):  # membership structure of the organisation
        r = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=?
                         AND COALESCE(u.kind, '')!='agent' AND u.disabled=0 ORDER BY (m.role='admin') DESC, m.user_id LIMIT 1""",
                      (oid, uid)).fetchone()
    return r[0] if r else None


def upg_rest(c, uid):
    """Everything of the account uid that must not vanish with it (or must vanish properly): its own agents (with their
    tokens), the organisations' calendars (to an admin of the organisation, as on leaving it), time entries of
    organisation projects (kept, without the person), direct messages (kept for the partner), mentions and log rows
    (the person's id cleared), the inbox (with its files). Returns what to remove after the commit."""
    from ..agents.admin import agent_delete
    from ..lists.listtrash import otr_drop_files
    from ..tasks.tasks import hard_delete
    from .pictures import avatar_drop_file
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
                c.execute("DELETE FROM ev_cal_members WHERE cal_id=? AND user_id=?", (xid, heir))
                c.execute("UPDATE ev_cals SET owner_id=? WHERE id=?", (heir, xid))
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
        for (lid,) in c.execute("SELECT id FROM lists WHERE owner_id=?", (uid,)).fetchall():  # the inbox (the caller settled the rest)
            files = hard_delete(c, [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))], lists={lid})
            icon, lfiles = list_purge(c, lid, None)
            todo.append(lambda lid=lid, icon=icon, f=lfiles + files: otr_drop_files(lid, icon, f))
    return todo


UPG_MENTION = "<@{0}>"


def upg_mentions(c, uid):
    """Mentions of the deleted person in comments and chat messages (plain text; locked ones the server cannot read stay)
    become the words "@Deleted user"; the id leaves the comments' mention lists."""
    tok, word = UPG_MENTION.format(int(uid)), "@" + tr("Deleted user")
    for table in ("comments", "tchat_msgs"):
        extra = " AND enc IS NULL" if table == "tchat_msgs" else ""
        c.execute(f"UPDATE {table} SET body=replace(body, ?, ?) WHERE body LIKE ?{extra}", (tok, word, f"%{tok}%"))  # pg-ok: the token is <@digits>, case does not matter
    for r in c.execute("SELECT id, mentions FROM comments WHERE ','||mentions||',' LIKE ?", (f"%,{int(uid)},%",)).fetchall():  # pg-ok: digits only, case does not matter
        rest = [x for x in str(r["mentions"]).split(",") if x and x != str(int(uid))]
        c.execute("UPDATE comments SET mentions=? WHERE id=?", (",".join(rest), r["id"]))


def upg_info(c, uid):
    """For the delete dialog (useradmin.ua8_delete_info): what is deleted, handed on and kept by law."""
    poid, ret, _ = upg_personal_state(c, uid)
    with system_ctx(c):  # numbers only, for the deleting admin
        one = lambda sql: c.execute(sql, (int(uid),)).fetchone()[0]  # noqa: E731
        info = {"agents": one("SELECT COUNT(*) FROM agents WHERE owner_id=?"),
                "calendars": one("SELECT COUNT(*) FROM ev_cals WHERE owner_id=? AND org_id IS NOT NULL"),
                "time_kept": one("SELECT COUNT(*) FROM time_entries t JOIN lists l ON l.id=t.list_id WHERE t.user_id=? AND l.org_id IS NOT NULL")}
        info["dms"] = c.execute("SELECT COUNT(*) FROM tchat_rooms WHERE kind='dm' AND (a=? OR b=?) AND a IS NOT NULL AND b IS NOT NULL "
                                "AND a!=b AND last_at IS NOT NULL", (int(uid), int(uid))).fetchone()[0]
    content = odl_content(c, poid) if poid else {}
    info.update(office="keep" if ret["until"] else ("delete" if content else None), office_counts=content,
                kept=ret["counts"], kept_until=ret["until"])
    return info


# ---------------------------------------------------------------- one-shot: foreign keys that must not cascade any more
UPG_FK = (("time_entries", "user_id", "SET NULL"), ("tchat_rooms", "a", "SET NULL"), ("tchat_rooms", "b", "SET NULL"))


def upg_fk_once(c):
    """2.152.0 A (#2164): at the start (core/db.py init, idempotent): an account's deletion keeps the time entries of
    organisation projects (time_entries.user_id may be NULL now) and the direct messages for the partner (tchat_rooms
    a / b ON DELETE SET NULL instead of CASCADE). 2.102 runs on with it (it never writes NULL there)."""
    n = 0
    for table, col, rule in UPG_FK:
        rows = c.execute("SELECT con.conname, con.confdeltype FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid "  # pg-ok: catalog oid (Postgres only)
                         "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(con.conkey) "  # pg-ok: catalog oid (Postgres only)
                         "WHERE con.contype='f' AND t.relname=? AND a.attname=? AND t.relnamespace=to_regnamespace(current_schema())",
                         (table, col)).fetchall()
        if any(r[1] == "n" for r in rows):
            continue
        if table == "time_entries":
            c.execute(f"ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL")
        for r in rows:
            c.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{r[0]}"')
        c.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{col}_fkey FOREIGN KEY ({col}) REFERENCES users(id) ON DELETE {rule}")
        n += 1
    if n:
        print(f"accounts (#2164): {n} foreign key(s) no longer delete along with an account", flush=True)
    return n

