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

from .kernretire import kern_retire_floor
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
CT_ZONE = r"[T ]\d\d:\d\d(:\d\d(\.\d{1,6})?)?(Z|[+-]\d\d(:?\d\d)?)$"  # review 2.1095 (F13): a zone only after a time (2026-03-01: -01 is the day)


def ct_day(expr):
    """SQL: the day (YYYY-MM-DD, UTC) of a time column, for TEXT and TIMESTAMPTZ alike (the text of a TIMESTAMPTZ carries the
    session's zone, which is UTC for the app; substr() of a TIMESTAMPTZ is no function)."""
    return f"substr(CAST({expr} AS text), 1, 10)"


def ct_iso(expr):
    """SQL: a time column as the canonical ISO text the app reads (core/pg.py ts_canon, whole seconds: UTC, +00:00), for TEXT
    and TIMESTAMPTZ alike, microseconds only when there are any; NULL for NULL / ''. For keys and marks built in SQL that Python compares with a value it read
    (a TIMESTAMPTZ concatenated or assigned to a TEXT column carries the session's text form '2026-11-13 04:33:00+00')."""
    # review 2.1095 (F8): microseconds when there are any, as ts_canon (iso_ms writes milliseconds into many of these columns)
    t = f"(NULLIF(CAST({expr} AS text), '')::timestamptz AT TIME ZONE 'UTC')"
    return (f"""(to_char({t}, 'YYYY-MM-DD"T"HH24:MI:SS') || CASE WHEN to_char({t}, 'US') <> '000000' THEN '.' || to_char({t}, 'US') """
            f"""ELSE '' END || '+00:00')""")


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
            q = qi(col, CT_NAMES)
            if nullable:
                empty = "NULL"
            elif col != "created_at" and (table, "created_at") in types:
                cr = qi("created_at", CT_NAMES)  # its text (TEXT or TIMESTAMPTZ already: the session's zone, UTC), else the start
                empty = (f"(CASE WHEN {_valid(f'CAST({cr} AS text)')} THEN {_as_ts(f'CAST({cr} AS text)')} "
                         f"ELSE '{at}'::timestamptz END)")
            else:
                empty = f"'{at}'::timestamptz"
            had_default = dflt is not None
            sql = (f"ALTER TABLE {qi(table, CT_TABLES)} ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE TIMESTAMPTZ USING "
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
    # review 2.1095 (F9): the import marks of contacts / events are copies of updated_at as text; a millisecond value reads as
    # microseconds now (ts_canon), so the copy takes the same form, else every contact / event counts as changed here
    for table in ("contacts", "events"):
        if out.get(f"{table}.updated_at") == "done":
            with c.savepoint():
                c.execute(f"UPDATE {qi(table, CT_TABLES)} SET imp_at={ct_iso('imp_at')} WHERE imp_at ~ '\\.[0-9]' "
                          "AND pg_input_is_valid(imp_at, 'timestamptz')")
    n = sum(1 for v in out.values() if v == "done")
    if n:
        print(f"migrations: 5306: {n} time column(s) are TIMESTAMPTZ now", flush=True)
    return out


# ---- 2.1111.0 (#5953, rest 3 of #5306 / #5289): the JSON columns kept as TEXT become JSONB --------------------------------
# A new database makes them JSONB at once (core/schema.py, the fragments of migrations.d); ct_json_migrate (init_db, after
# ct_migrate) turns an existing one, column by column, each in its own savepoint:
#   - a value Postgres reads as JSONB keeps it (an array, an object or a scalar: the readers decide, as before)
#   - '' / no JSON / JSON that JSONB refuses (a "\u0000", NaN) becomes the column's default ('{}' or '[]'); the log names the
#     column, the count and the first ids of the non-empty ones (`migrations: 5953: ...`), as core/tplmove.py does
#   - a column that holds sealed text (kenc1: / e2e1:) outside JSON is not turned (the value would be lost), the log says so
#   - triggers that name the column (UPDATE OF / WHEN, e.g. the search index core/objsearch.py) are taken off and put back
#     unchanged inside the same savepoint (Postgres refuses to change the type of a column a trigger names)
#   - a column Postgres refuses to turn stays TEXT, the log says why, the next start tries again
# Reading stays as it was: the driver gives JSONB to Python as its JSON text (core/pg.py, TextLoader) - json.loads works; the
# text is JSONB's own form (keys by length then bytes, ", " / ": ", no duplicate keys). SQL on these columns works for both
# types (docs/dev/kern.md): never LIKE / ILIKE / || / lower() / position() / COALESCE(x, '') / = '' on the column itself -
# CAST(x AS text) for text matching, CAST(x AS jsonb) -> / @> for its content.
# Kept as TEXT (marked coltype-ok in the schema, the reason there): the columns sealed as a whole (core/orgcrypt.py FIELDS:
# office_bookarch.raw, office_contracts.rates, office_doc_log.detail, office_doc_parts.sheet, office_meals.amounts / guests /
# host, office_roles.costs, office_trips.people), office_docs.totals (the GoBD hash chain office/chain.py hch_canon hashes its
# numbers; JSONB would turn -0.0 into 0.0 and 1e+16 into 10000000000000000) and budget_meta.mappings (its key order is the
# age of an entry, life/budget.py _meta_put drops the oldest).
# One way (the leader's --einbahn): a version before would run its text operators on JSONB (ILIKE on contacts' e-mails, the
# search index trigger): the back limit rises to this minor (core/kernretire.py kern_retire_floor); a backup restores the old state.
CT_JSON = {  # table -> ((column, default), ...): the json lines of tools/coltypes_baseline.txt before 2.1111 that move
    "admin_alerts": (("tmpl", "[]"),),
    "agent_events": (("payload", "{}"),),
    "agent_server": (("flow_models", "{}"), ("flow_web", "{}")),
    "bookmarks": (("tags", "[]"),),
    "budget_meta": (("runs", "[]"),),
    "contacts": (("addresses", "[]"), ("emails", "[]"), ("groups", "[]"), ("phones", "[]"), ("urls", "[]")),
    "doc_cfg": (("data", "{}"),),
    "doc_fields": (("options", "{}"),),
    "doc_mail": (("tags", "[]"),),
    "doc_meta": (("auto", "{}"),),
    "doc_office_moves": (("items", "[]"),),
    "field_trash": (("def", "{}"), ("vals", "[]")),
    "filters": (("rules", "{}"),),
    "folder_props": (("props", "{}"),),
    "form_entries": (("answers", "{}"),),
    "forms": (("questions", "[]"),),
    "git_closes": (("undo", "{}"),),
    "git_conns": (("etags", "{}"),),
    "hub_mailbox_rules": (("tags", "[]"),),
    "hub_mails": (("files", "[]"),),
    "imports": (("created", "{}"), ("report", "{}")),
    "list_activity": (("data", "{}"),),
    "list_fields": (("options", "{}"),),
    "list_part_trash": (("held", "{}"), ("snap", "{}")),
    "list_rules": (("act_val", "{}"),),
    "lists": (("folder_own", "[]"),),
    "member_memos": (("data", "{}"),),
    "merge_runs": (("merged_ids", "[]"), ("snapshot", "{}"), ("summary", "{}")),
    "msv_links": (("remote_me", "{}"),),
    "nl_runs": (("counts", "{}"), ("errors", "[]")),
    "nl_segments": (("rule", "{}"),),
    "oauth_clients": (("redirect_uris", "[]"),),
    "office_contracts": (("trans", "{}"),),
    "office_doc_parts": (("settings", "{}"), ("totals", "{}")),
    "office_docs": (("abs_refs", "[]"), ("fields", "[]"), ("recipient", "{}"), ("rights", "{}")),
    "office_equipment": (("maint", "[]"), ("trans", "{}")),
    "office_fixed_costs": (("seats", "[]"),),
    "office_import_runs": (("counts", "{}"), ("detail", "{}")),
    "office_pack_installs": (("meta", "{}"),),
    "office_rgroups": (("rights", "{}"), ("specials", "[]")),
    "office_roles": (("trans", "{}"),),
    "office_services": (("trans", "{}"),),
    "office_sets": (("items", "[]"),),
    "office_settings": (("data", "{}"),),
    "office_texts": (("trans", "{}"),),
    "office_trips": (("vma_days", "[]"),),
    "org_fields": (("options", "{}"),),
    "retention_log": (("detail", "{}"),),
    "sched_poll_votes": (("answers", "{}"),),
    "sheet_columns": (("options", "[]"),),
    "space_moves": (("detail", "{}"),),
    "support_grants": (("uses", "[]"),),
    "time_sheets": (("log", "[]"),),
    "time_wipes": (("entries", "[]"),),
    "wiki_pages": (("attrs", "{}"),),
    "wiki_spaces": (("wkx_holds", "{}"),),
}
CTJ_NAMES = {*CT_JSON, *(x for cols in CT_JSON.values() for x, _ in cols)}  # the allowlist of qi() (#5296)
CTJ_SEALED = ("kenc1:", "e2e1:")  # core/orgcrypt.py PREFIX, collab/liste2e.py LE2E_PREFIX: sealed text, never JSON
CTJ_HOW = ("the JSON columns of the areas are JSONB (#5953) - an older version would search and write them as text; go back "
           "only with a backup from before")


def ctj_types(c):
    """{(table, column): data_type} of the CT_JSON columns that exist."""
    q = ",".join("?" * len(CT_JSON))
    return {(r[0], r[1]): r[2] for r in c.execute(
        f"SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() "
        f"AND table_name IN ({q})", tuple(CT_JSON)).fetchall() if any(r[1] == x for x, _ in CT_JSON[r[0]])}


def ctj_misfits(c, table, col):
    """([ids] (ctid text without an id column) of the rows whose col is neither '' nor JSON that JSONB takes, sealed: bool)."""
    q = qi(col, CTJ_NAMES)
    has_id = c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? "
                       "AND column_name='id'", (table,)).fetchone()
    key = "id" if has_id else "ctid::text"
    rows = c.execute(f"SELECT {key}, left(btrim({q}), 8) FROM {qi(table, CTJ_NAMES)} WHERE {q} IS NOT NULL AND btrim({q}) <> '' "
                     f"AND NOT pg_input_is_valid({q}, 'jsonb') ORDER BY 1").fetchall()
    return [r[0] for r in rows], any(str(r[1] or "").startswith(CTJ_SEALED) for r in rows)


def ctj_triggers(c, table, col):
    """[(name, CREATE TRIGGER text)] of the user triggers on table that name col (UPDATE OF col, or col in their WHEN)."""
    return [(r[0], r[1]) for r in c.execute(
        "SELECT DISTINCT t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_depend d ON d.classid='pg_trigger'::regclass "
        "AND d.objid=t.oid JOIN pg_attribute a ON a.attrelid=d.refobjid AND a.attnum=d.refobjsubid "
        "WHERE NOT t.tgisinternal AND t.tgrelid=to_regclass(?) AND a.attname=? ORDER BY 1", (table, col)).fetchall()]


def ct_json_migrate(c, at):
    """init_db (2.1111.0, #5953): every CT_JSON column that is still TEXT becomes JSONB (the block above CT_JSON), each in a
    savepoint of the start's transaction (at = the start's time, ISO) -> {"table.col": "done" | "kept" | "present" | "missing"}.
    System context: the check must see every organisation's rows (as ct_migrate)."""
    with system_ctx(c):
        return _ctj_run(c, at)


def _ctj_run(c, at):
    out = {}
    types = ctj_types(c)
    for table, cols in CT_JSON.items():
        for col, dflt in cols:
            k = f"{table}.{col}"
            typ = types.get((table, col))
            if typ != "text":
                out[k] = "present" if typ else "missing"
                continue
            bad, sealed = ctj_misfits(c, table, col)
            if sealed:
                out[k] = "kept"
                print(f"migrations: 5953: {k} stays TEXT: it holds sealed text (ids {', '.join(map(str, bad[:CT_SHOW]))})",
                      file=sys.stderr, flush=True)
                continue
            if bad:
                print(f"migrations: 5953: {k}: {len(bad)} value(s) are no JSON and become {dflt} (ids "
                      f"{', '.join(map(str, bad[:CT_SHOW]))}{', ...' if len(bad) > CT_SHOW else ''})", file=sys.stderr, flush=True)
            q = qi(col, CTJ_NAMES)
            sql = (f"ALTER TABLE {qi(table, CTJ_NAMES)} ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE JSONB USING (CASE WHEN {q} IS NULL "
                   f"THEN NULL WHEN pg_input_is_valid({q}, 'jsonb') THEN {q}::jsonb ELSE '{dflt}'::jsonb END), "
                   f"ALTER COLUMN {q} SET DEFAULT '{dflt}'::jsonb")
            try:
                with c.savepoint():
                    trg = ctj_triggers(c, table, col)
                    for name, _ in trg:
                        c.execute(f"DROP TRIGGER {qi(name, {name})} ON {qi(table, CTJ_NAMES)}")
                    c.execute(sql)
                    for _, ddl in trg:
                        c.execute(ddl)
            except Exception as e:  # noqa: BLE001 -- the start goes on with the column as it was, the log says why
                out[k] = "kept"
                print(f"migrations: 5953: {k} stays TEXT: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
                continue
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'applied') ON CONFLICT(id) DO UPDATE SET "
                      "applied_at=excluded.applied_at, note=excluded.note", (CT_ID.format(table, col), at))
            out[k] = "done"
    n = sum(1 for v in out.values() if v == "done")
    if n:
        print(f"migrations: 5953: {n} JSON column(s) are JSONB now", flush=True)
    if any(v in ("done", "present") for v in out.values()):
        kern_retire_floor(c, how=CTJ_HOW)
    return out
