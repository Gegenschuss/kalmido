"""2.1095.0 (#5306): the old time columns created_at / updated_at / deleted_at as TIMESTAMPTZ instead of ISO text.

Since the move to Postgres (2.37.0, #1150) most tables kept the SQLite habit of points in time as ISO text (tools/check_coltypes.py,
tools/coltypes_baseline.txt). This step moves the three columns every area has - when a row was made, last changed, put into
the trash - in all the tables that still had them as TEXT (CT_TIME). A new database makes them TIMESTAMPTZ at once
(core/schema.py, the fragments of migrations.d); ct_migrate (init_db, after the steps) turns an existing one, column by column,
each in its own savepoint, only when every value is a point in time:

  - ISO text with a zone (Z / +01:00) is that moment; ISO text without a zone is UTC (now_iso always wrote UTC)
  - '' is "none": NULL in a nullable column; in a NOT NULL column the row's created_at when that is a time, else the start's time
    (an updated_at '' meant "never changed since it was made"); a column whose default was '' gets DEFAULT CURRENT_TIMESTAMP
  - any other text (none the app wrote: now_iso, the imports and the agents' API take only ISO times) counts as '' and the log
    names the column, the count and the first ids (`migrations: 5306: ...`). Unlike core/moneycol.py the column moves anyway:
    the three columns are compared and joined across the areas, one column left as TEXT would break those queries
  - a column Postgres refuses to turn (an error in the ALTER) stays TEXT, the log says why, the next start tries again

Reading stays as it was: the driver gives TIMESTAMPTZ to Python as the canonical ISO text (core/pg.py ts_canon: UTC, +00:00,
microseconds only when there are any), the same form now_iso wrote into the TEXT columns. SQL that reads such a column works for
both types (docs/dev/kern.md): never `= ''` / `COALESCE(x, '')` / `substr(x, ...)` on it - `x IS NULL`, `CAST(x AS text)`,
`ct_day(x)` for the day.

One way (the leader's --einbahn): the type does not change back. A version before reads the same text (the loader), but its
few `= ''` comparisons on these columns would fail; a backup restores the old state."""
import sys

from .pg import qi, system_ctx

CT_TIME = {  # column -> the tables that still had it as TEXT (the lines of tools/coltypes_baseline.txt before 2.1095)
    "created_at": (
        'abs_cal_feeds', 'activity', 'admin_alerts', 'agent_chat', 'agent_decisions', 'agent_events', 'agent_jobs',
        'agent_rules', 'agent_schedules', 'agent_setup_codes', 'agent_steps', 'agent_usage', 'agents', 'api_tokens',
        'app_passwords', 'appt_bookings', 'appt_pages', 'appt_types', 'assistant_access', 'attachments', 'bg_jobs', 'bookmarks',
        'books', 'budget_cats', 'budget_entries', 'budget_files', 'budget_recurring', 'cal_subs', 'chat_files', 'chat_saves',
        'clients', 'conn_blocks', 'conn_links', 'conn_requests', 'contact_srcs', 'contacts', 'dav_sync', 'dav_sync2',
        'disc_profiles', 'doc_fetchers', 'doc_fields', 'doc_flow_runs', 'doc_mail', 'doc_meta', 'doc_office_moves', 'doc_rules',
        'doc_senders', 'doc_tags', 'doc_types', 'doc_views', 'e2e_keys', 'ev_cal_feeds', 'ev_cals', 'events', 'file_text',
        'filters', 'folder_agents', 'form_entries', 'forms', 'fs_ext_links', 'fs_lock_keys', 'fs_nodes', 'fs_shares',
        'fs_upload_requests', 'fs_versions', 'git_closes', 'git_conns', 'git_folders', 'git_issue_comments', 'git_issue_gone',
        'git_issue_links', 'git_links', 'groups', 'habits', 'hook_in', 'hub_absences', 'hub_bookings', 'hub_mailbox_rules',
        'hub_mailboxes', 'hub_mails', 'hub_tokens', 'idem_keys', 'imports', 'issue_hooks', 'job_watch', 'kid_rewards',
        'kid_stars', 'kk_conns', 'life_trip_costs', 'list_activity', 'list_envs', 'list_fields', 'list_files',
        'list_folder_skip', 'list_keys', 'list_links', 'list_milestones', 'list_mine_hide', 'list_notepads', 'list_rules',
        'list_status', 'lists', 'mail_tokens', 'merge_runs', 'module_cards', 'msv_links', 'nl_conns', 'nl_segments', 'notes',
        'notifications', 'notify_channels', 'oauth_clients', 'oauth_codes', 'oauth_grants', 'obj_history', 'obj_revoked',
        'obj_undo', 'office_agreements', 'office_archive', 'office_bank_accounts', 'office_bank_balances',
        'office_bank_imports', 'office_bank_rule_nos', 'office_bank_rules', 'office_bank_tx', 'office_bank_vendors',
        'office_bookarch_docs', 'office_bookarch_files', 'office_cash_entries', 'office_cashbooks', 'office_cc_cards',
        'office_cc_statements', 'office_cf_adjust', 'office_client_contacts', 'office_contract_files', 'office_contracts',
        'office_datev_guids', 'office_deals', 'office_doc_parts', 'office_doc_templates', 'office_docs', 'office_drives',
        'office_dunning_marks', 'office_equipment', 'office_fixed_costs', 'office_gen_docs', 'office_import_runs',
        'office_inv_series', 'office_ledger_entries', 'office_letter_blocks', 'office_letters', 'office_meal_choices',
        'office_meal_files', 'office_meals', 'office_opening_balances', 'office_pay_events', 'office_pay_links',
        'office_pay_payouts', 'office_pay_props', 'office_pay_sessions', 'office_payments', 'office_peppol_sends',
        'office_privacy_sheets', 'office_purchases', 'office_rgroup_members', 'office_rgroups', 'office_roles',
        'office_services', 'office_sets', 'office_signoffs', 'office_sub_reminders', 'office_suppliers', 'office_texts',
        'office_trip_items', 'office_trip_purposes', 'office_trips', 'office_vehicles', 'org_fields', 'org_invites',
        'org_joins', 'org_keys', 'org_list_log', 'org_out_requests', 'orgs', 'pl_conns', 'pl_imported', 'pl_rules',
        'pl_sources', 'pl_uploads', 'playbook_proposals', 'portal_logins', 'portal_tickets', 'public_links', 'push_subs',
        'rc_suggest', 'reading_orgs', 'recovery_codes', 'rss_feeds', 'sched_poll_votes', 'sched_polls', 'sessions',
        'sheet_changes', 'sheet_files', 'sheet_links', 'sheets', 'sprints', 'support_grants', 'task_decisions', 'task_deps',
        'task_keys', 'task_links', 'task_mail', 'task_offer_links', 'task_relations', 'tasks', 'tchat_files', 'tchat_msgs',
        'tchat_rooms', 'template_files', 'ticket_types', 'tidy_pending', 'time_entries', 'time_sheets', 'upload_scan',
        'user_invites', 'user_keys', 'user_mine_sections', 'users', 'video_reviews', 'video_versions', 'view_layout_offers',
        'view_layouts', 'wait_hidden', 'webauthn_creds', 'webhook_log', 'webhook_queue', 'webhooks', 'wiki_files', 'wiki_keys',
        'wiki_pages',
    ),
    "updated_at": (
        'agent_chat_prefs', 'agent_jobs', 'agent_rules', 'agent_schedules', 'agent_server', 'appt_pages', 'appt_types',
        'bookmarks', 'books', 'budget_cats', 'budget_entries', 'budget_meta', 'budget_recurring', 'cal_subs', 'clients',
        'contact_care', 'contacts', 'doc_cfg', 'doc_fetch_portals', 'doc_mail', 'doc_meta', 'doc_models', 'doc_rules',
        'doc_views', 'e2e_keys', 'ev_cals', 'events', 'file_text', 'folder_heads', 'folder_props', 'fs_area_roots', 'fs_nodes',
        'git_prs', 'habits', 'hub_bookings', 'hub_leave_quota', 'hub_mailbox_rules', 'hub_mailboxes', 'journal', 'list_layouts',
        'list_notepads', 'list_rules', 'lists', 'module_cards', 'msv_links', 'nl_conns', 'nl_segments', 'notes',
        'notify_channels', 'obj_history', 'office_agreements', 'office_archive', 'office_bank_accounts', 'office_bank_rules',
        'office_bank_vendors', 'office_cash_entries', 'office_cashbooks', 'office_cc_cards', 'office_cc_lines',
        'office_cf_actual', 'office_cf_adjust', 'office_cf_start', 'office_client_contacts', 'office_company',
        'office_contracts', 'office_deals', 'office_doc_parts', 'office_doc_templates', 'office_docs', 'office_drives',
        'office_equipment', 'office_fixed_costs', 'office_gen_docs', 'office_inv_series', 'office_ledger_entries',
        'office_letter_blocks', 'office_letter_profiles', 'office_letters', 'office_meal_choices', 'office_meals',
        'office_pay_sessions', 'office_payonline', 'office_peppol', 'office_peppol_sends', 'office_privacy_sheets',
        'office_rgroups', 'office_roles', 'office_services', 'office_sets', 'office_settings', 'office_suppliers',
        'office_texts', 'office_trip_items', 'office_trip_purposes', 'office_trips', 'office_vehicles', 'pl_sources',
        'pl_tokens', 'pl_uploads', 'sched_poll_votes', 'sched_polls', 'sheet_cells', 'sheets', 'sprints', 'task_enc_notes',
        'task_note_locks', 'task_offer_links', 'task_vectors', 'tasks', 'tchat_rooms', 'time_entries', 'time_sheets',
        'user_mine_sections', 'video_reviews', 'view_layouts', 'webhooks', 'wiki_pages',
    ),
    "deleted_at": (
        'appt_types', 'attachments', 'bookmarks', 'books', 'budget_cats', 'budget_entries', 'budget_recurring', 'clients',
        'conn_links', 'contacts', 'doc_views', 'ev_cals', 'events', 'field_trash', 'fs_nodes', 'fs_upload_requests', 'habits',
        'hook_in', 'hub_absences', 'hub_bookings', 'hub_mails', 'list_envs', 'list_files', 'list_links', 'list_part_trash',
        'list_rules', 'lists', 'member_memos', 'msv_links', 'notes', 'office_bank_rules', 'office_bank_tx', 'office_cc_cards',
        'office_cc_statements', 'office_contract_files', 'office_deals', 'office_drives', 'office_inv_series',
        'office_meal_choices', 'office_meal_files', 'office_meals', 'office_suppliers', 'office_trip_purposes', 'rss_feeds',
        'sched_polls', 'sheet_columns', 'sheet_files', 'sheet_rows', 'sheets', 'tasks', 'tchat_msgs', 'tchat_rooms',
        'time_wipes', 'video_reviews', 'wiki_files', 'wiki_pages',
    ),
}
CT_TABLES = {t for ts in CT_TIME.values() for t in ts}  # the allowlists of qi() (#5296)
CT_NAMES = set(CT_TIME)
CT_SHOW = 5  # ids named in the log per column
CT_ID = "type:{0}.{1}"  # its row in kalmido_migrations
# a point in time as ISO text: a day, optionally the time (T or a space), optionally a zone; pg_input_is_valid checks the rest
# (2026-02-30, 25:00), the pattern keeps out what Postgres reads as a time too ('now', 'today', 'epoch', 'infinity')
CT_ISO = r"^\d{4}-\d\d-\d\d([T ]\d\d:\d\d(:\d\d(\.\d{1,6})?)?)?(Z|[+-]\d\d(:?\d\d)?)?$"
CT_ZONE = r"(Z|[+-]\d\d(:?\d\d)?)$"


def ct_day(expr):
    """SQL: the day (YYYY-MM-DD, UTC) of a time column, for TEXT and TIMESTAMPTZ alike (the text of a TIMESTAMPTZ carries the
    session's zone, which is UTC for the app; substr() of a TIMESTAMPTZ is no function)."""
    return f"substr(CAST({expr} AS text), 1, 10)"


def ct_iso(expr):
    """SQL: a time column as the canonical ISO text the app reads (core/pg.py ts_canon, whole seconds: UTC, +00:00), for TEXT
    and TIMESTAMPTZ alike; NULL for NULL / ''. For keys and marks built in SQL that Python compares with a value it read
    (a TIMESTAMPTZ concatenated or assigned to a TEXT column carries the session's text form '2026-11-13 04:33:00+00')."""
    return f"""to_char(NULLIF(CAST({expr} AS text), '')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')"""


def _valid(q):
    return f"(btrim({q}) ~ '{CT_ISO}' AND pg_input_is_valid(btrim({q}), 'timestamptz'))"


def _as_ts(q):
    """SQL: the value of the text column q as TIMESTAMPTZ (no zone = UTC); only for values _valid() accepts."""
    return f"(CASE WHEN btrim({q}) ~ '{CT_ZONE}' THEN btrim({q})::timestamptz ELSE btrim({q})::timestamp AT TIME ZONE 'UTC' END)"


def ct_types(c):
    """{(table, column): (data_type, nullable, default)} of the CT_TIME columns that exist."""
    out = {}
    for t, col, typ, nul, dflt in c.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND column_name IN ('created_at', 'updated_at', 'deleted_at')").fetchall():
        if t in CT_TIME.get(col, ()):
            out[(t, col)] = (typ, nul == "YES", dflt)
    return out


def ct_misfits(c, table, col):
    """[ids] (or [ctid text] without an id column) of the rows whose col is neither '' / NULL nor a point in time (for the log)."""
    q = qi(col, CT_NAMES)
    has_id = c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? "
                       "AND column_name='id'", (table,)).fetchone()
    key = "id" if has_id else "ctid::text"
    sql = f"SELECT {key} FROM {qi(table, CT_TABLES)} WHERE {q} IS NOT NULL AND btrim({q}) <> '' AND NOT {_valid(q)} ORDER BY 1"
    return [r[0] for r in c.execute(sql).fetchall()]


def ct_migrate(c, at):
    """init_db (2.1095.0, #5306): every CT_TIME column that is still TEXT becomes TIMESTAMPTZ when its values are points in
    time (module text), each in a savepoint of the start's transaction (at = the start's time, ISO)
    -> {"table.col": "done" | "kept" | "present" | "missing"}. System context: the check must see every organisation's rows
    (the ALTER rewrites all of them, row security or not), as core/moneycol.py mc_migrate."""
    with system_ctx(c):
        return _ct_run(c, at)


def _ct_run(c, at):
    out = {}
    types = ct_types(c)
    for col, tables in CT_TIME.items():
        for table in tables:
            k = f"{table}.{col}"
            typ, nullable, dflt = types.get((table, col), (None, True, None))
            if typ != "text":
                out[k] = "present" if typ else "missing"
                continue
            bad = ct_misfits(c, table, col)
            if bad:
                print(f"migrations: 5306: {k}: {len(bad)} value(s) are no point in time and count as empty (ids "
                      f"{', '.join(map(str, bad[:CT_SHOW]))}{', ...' if len(bad) > CT_SHOW else ''})", file=sys.stderr, flush=True)
            q, tq = qi(col, CT_NAMES), qi(table, CT_TABLES)
            if nullable:
                empty = "NULL"
            elif col != "created_at" and (table, "created_at") in types:
                cr = qi("created_at", CT_NAMES)  # its text (TEXT or TIMESTAMPTZ already: the session's zone, UTC), else the start
                empty = (f"(CASE WHEN {_valid(f'CAST({cr} AS text)')} THEN {_as_ts(f'CAST({cr} AS text)')} "
                         f"ELSE '{at}'::timestamptz END)")
            else:
                empty = f"'{at}'::timestamptz"
            had_default = dflt is not None
            sql = (f"ALTER TABLE {tq} ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE TIMESTAMPTZ USING "
                   f"(CASE WHEN {q} IS NULL THEN NULL WHEN {_valid(q)} THEN {_as_ts(q)} ELSE {empty} END)")
            if had_default:  # DEFAULT '' (never changed) -> made now
                sql += f", ALTER COLUMN {q} SET DEFAULT CURRENT_TIMESTAMP"
            try:
                with c.savepoint():
                    c.execute(sql)
            except Exception as e:  # noqa: BLE001 -- the start goes on with the column as it was, the log says why
                out[k] = "kept"
                print(f"migrations: 5306: {k} stays TEXT: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
                continue
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'applied') ON CONFLICT(id) DO UPDATE SET "
                      "applied_at=excluded.applied_at, note=excluded.note", (CT_ID.format(table, col), at))
            out[k] = "done"
    n = sum(1 for v in out.values() if v == "done")
    if n:
        print(f"migrations: 5306: {n} time column(s) are TIMESTAMPTZ now", flush=True)
    return out
