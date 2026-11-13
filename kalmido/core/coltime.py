"""2.1115.0 (#5951): the other old time columns (*_at / *_on / *_until) onto TIMESTAMPTZ / DATE, area by area.

2.1095.0 (#5306, core/coltype.py) moved created_at / updated_at / deleted_at. The rest of the "time" lines of
tools/coltypes_baseline.txt is listed here, one dict per area, {(table, column): kind}:

  "ts"    a point in time -> TIMESTAMPTZ (ISO text without a zone is UTC: now_iso / iso_ms always wrote UTC)
  "date"  a day (YYYY-MM-DD)  -> DATE (the driver reads it back as 'YYYY-MM-DD' text, core/pg.py _DateLoader)

A column that is no point in time (a clock time 'HH:MM', a local wall time without a zone that must not be read as UTC) is
not listed: its line in core/schema.py (or the fragment) gets the marker `coltype-ok: <why>` and leaves the baseline.

core/coltype.py ct_migrate turns an existing database at the start, column by column, each in its own savepoint:
  - '' is "none": NULL - the column becomes nullable when it was nullable or had DEFAULT '' (that '' meant "never");
    a NOT NULL column without that default takes the row's created_at (else the start's time); the DEFAULT '' goes
  - a text that is no point in time is set all the same (review, #5951): it takes the row's created_at (else the start's
    time; a DATE its day) in every column, never NULL; the log names the column, the count and the first ids
  - a column Postgres refuses to turn stays TEXT, the log says why, the next start tries again; its DEFAULT goes, a column
    that knows "none" loses NOT NULL and its '' becomes NULL, so the code (writes None, asks IS NULL) keeps running
A new database makes them so at once (core/schema.py, the fragments).

SQL on such a column works for both types (docs/dev/kern.md section 1): `x IS NULL` instead of `x = ''`, never
`COALESCE(x, '')` / `substr(x, ...)` (ct_day / ct_iso of core/coltype.py), and the app writes None, never '', for "none".

One way (the leader's --einbahn): a version before reads the same text, but would write '' into these columns.

Each part of the package edits only its own dict (the parts are built side by side); the merged map is CT_MORE.
"""

# ---------------------------------------------------------------------------------------------------------------------------
# Part B: office (office_*), receipts (rc_*), books, budget, time, documents (doc_*), imports, merges, bookmarks
# ---------------------------------------------------------------------------------------------------------------------------
CT_B = {
    ("bookmarks", "fetched_at"): "ts",
    ("imports", "undone_at"): "ts",
    ("merge_runs", "undone_at"): "ts",
    ("rc_receipts", "billed_at"): "ts",
    ("rc_receipts", "checked_at"): "ts",
    ("rc_receipts", "paid_at"): "date",
    ("rc_receipts", "set_at"): "ts",
    ("rc_receipts", "submitted_at"): "ts",
    ("rc_suggest", "decided_at"): "ts",
    ("time_entries", "billed_at"): "ts",
    ("time_sheets", "closed_at"): "ts",
    ("time_sheets", "decided_at"): "ts",
    ("office_docs", "datev_sent_at"): "ts",
    ("office_docs", "locked_at"): "ts",
    ("office_docs", "paid_at"): "ts",
    ("office_docs", "reminder_fee_paid_at"): "date",
    ("office_docs", "sent_at"): "ts",
    ("office_docs", "valid_until"): "date",
    ("office_gen_docs", "final_at"): "ts",
    ("office_letters", "delivered_at"): "ts",
    ("office_letters", "sent_at"): "ts",
    ("office_pay_props", "decided_at"): "ts",
    ("office_peppol", "checked_at"): "ts",
    ("office_peppol_sends", "checked_at"): "ts",
    ("office_privacy_sheets", "sent_at"): "ts",
    ("office_privacy_sheets", "signed_at"): "ts",
    ("office_signoffs", "expires_at"): "ts",
    ("office_signoffs", "revoked_at"): "ts",
    ("office_signoffs", "signed_at"): "ts",
    ("doc_fetch_portals", "error_at"): "ts",
    ("doc_fetch_portals", "uploaded_at"): "ts",
    ("doc_fetchers", "expires_at"): "ts",
    ("doc_fetchers", "last_seen_at"): "ts",
    ("doc_flow_runs", "undone_at"): "ts",
    ("doc_meta", "done_at"): "ts",
    ("doc_meta", "edited_at"): "ts",
    ("doc_meta", "kept_until"): "date",
    ("doc_meta", "learn_at"): "ts",
    ("doc_meta", "redo_at"): "ts",
    ("doc_office_moves", "undone_at"): "ts",
    ("books", "changed_at"): "ts",
    ("office_bank_accounts", "fints_server_at"): "ts",
    ("office_bank_imports", "undone_at"): "ts",
    ("office_bank_rules", "last_hit_at"): "ts",
    ("office_bank_tx", "matched_at"): "ts",
    ("office_cash_closings", "closed_at"): "ts",
    ("office_cc_lines", "matched_at"): "ts",
    ("office_cc_statements", "confirmed_at"): "ts",
    ("office_drive_closed", "closed_at"): "ts",
    ("office_equipment", "warranty_until"): "date",
    ("office_import_runs", "undone_at"): "ts",
    ("office_meals", "approved_at"): "ts",
    ("office_pack_installs", "installed_at"): "ts",
    ("office_pack_installs", "removed_at"): "ts",
    ("office_period_locks", "locked_at"): "ts",
    ("office_purchases", "accepted_at"): "date",
    ("office_trip_items", "billed_at"): "ts",
}
# (end of part B)
#
#
#
# ---------------------------------------------------------------------------------------------------------------------------
# Part C: tasks, lists, team chat, wiki, files, sheets, sprints, habits, kids, pomodoro, calendar, contacts, polls, git,
#         issues, hub, forms, groups
# ---------------------------------------------------------------------------------------------------------------------------
CT_C = {
    ("appt_bookings", "cancelled_at"): "ts",
    ("appt_bookings", "confirmed_at"): "ts",
    ("cal_subs", "changed_at"): "ts",
    ("cal_subs", "fetched_at"): "ts",
    ("cal_subs", "synced_at"): "ts",
    ("cal_subs", "tried_at"): "ts",
    ("contact_srcs", "synced_at"): "ts",
    ("contact_srcs", "tried_at"): "ts",
    ("contacts", "imp_at"): "ts",
    ("contacts", "nl_at"): "ts",
    ("ev_cals", "changed_at"): "ts",
    ("event_attendees", "invited_at"): "ts",
    ("events", "imp_at"): "ts",
    ("forms", "last_at"): "ts",
    ("fs_ext_links", "expires_at"): "ts",
    ("fs_ext_links", "last_seen_at"): "ts",
    ("fs_ext_links", "revoked_at"): "ts",
    ("fs_locks", "e2e_at"): "ts",
    ("fs_shares", "expires_at"): "ts",
    ("fs_upload_requests", "expires_at"): "ts",
    ("fs_upload_requests", "last_at"): "ts",
    ("fs_upload_requests", "notified_at"): "ts",
    ("fs_upload_requests", "revoked_at"): "ts",
    ("git_branches", "seen_at"): "ts",
    ("git_closes", "undone_at"): "ts",
    ("git_conns", "issue_on_at"): "ts",
    ("git_conns", "issue_synced_at"): "ts",
    ("git_conns", "polled_at"): "ts",
    ("git_conns", "tags_at"): "ts",
    ("git_issue_comments", "send_at"): "ts",
    ("git_issue_links", "local_updated_at"): "ts",
    ("git_issue_links", "remote_updated_at"): "ts",
    ("git_prs", "merged_at"): "ts",
    ("git_tags", "seen_at"): "ts",
    ("group_members", "added_at"): "ts",
    ("habits", "reminded_on"): "date",
    ("hub_absences", "decided_at"): "ts",
    ("hub_mailbox_rules", "last_hit_at"): "ts",
    ("hub_mailboxes", "docs_polled_at"): "ts",
    ("hub_mailboxes", "error_at"): "ts",
    ("hub_mailboxes", "polled_at"): "ts",
    ("hub_mails", "sent_at"): "ts",
    ("issue_hooks", "last_at"): "ts",
    ("issue_reports", "first_at"): "ts",
    ("issue_reports", "last_at"): "ts",
    ("kid_pins", "lock_until"): "ts",
    ("kid_pins", "set_at"): "ts",
    ("kid_rewards", "decided_at"): "ts",
    ("kid_rewards", "requested_at"): "ts",
    ("list_members", "added_at"): "ts",
    ("list_paperless", "added_at"): "ts",
    ("lists", "archived_at"): "ts",
    ("lists", "description_at"): "ts",
    ("lists", "e2e_at"): "ts",
    ("lists", "page_layout_at"): "ts",
    ("lists", "retain_until"): "date",
    ("lists", "status_at"): "ts",
    ("pomos", "paused_at"): "ts",
    ("sched_polls", "closed_at"): "ts",
    ("sched_polls", "expires_at"): "ts",
    ("sheet_changes", "undone_at"): "ts",
    ("sheet_links", "undone_at"): "ts",
    ("sprints", "closed_at"): "ts",
    ("task_field_values", "set_at"): "ts",
    ("task_links", "section_at"): "ts",
    ("tasks", "completed_at"): "ts",
    ("tasks", "delivery_at"): "ts",
    ("tasks", "irreversible_yes_at"): "ts",
    ("tasks", "review_at"): "ts",
    ("tasks", "section_at"): "ts",
    ("tasks", "sprint_at"): "ts",
    ("tasks", "wait_until"): "date",
    ("tasks", "waiting_at"): "ts",
    ("tchat_msgs", "edited_at"): "ts",
    ("tchat_msgs", "pinned_at"): "ts",
    ("tchat_rooms", "archived_at"): "ts",
    ("tchat_rooms", "last_at"): "ts",
    ("wiki_files", "wkx_held_at"): "ts",
    ("wiki_spaces", "e2e_at"): "ts",
}
# (end of part C)
#
#
#
# ---------------------------------------------------------------------------------------------------------------------------
# Part D1: agents and the machinery (agent_*, agents, bg_jobs, notifications, newsletters, feeds, scans, migrations, ...)
# ---------------------------------------------------------------------------------------------------------------------------
CT_D1 = {  # agents.status_key_at stays TEXT (coltype-ok: the agent's own text, echoed as sent)
    ("agent_burst_held", "held_at"): "ts", ("agent_chat", "delivered_at"): "ts", ("agent_chat", "edited_at"): "ts",
    ("agent_chat", "pinned_at"): "ts", ("agent_chat", "read_at"): "ts", ("agent_decisions", "undone_at"): "ts",
    ("agent_jobs", "action_at"): "ts", ("agent_push_held", "first_at"): "ts", ("agent_push_held", "last_at"): "ts",
    ("agent_runs", "abort_at"): "ts", ("agent_runs", "beat_at"): "ts", ("agent_schedules", "last_at"): "ts",
    ("agent_schedules", "next_at"): "ts", ("agent_setup_codes", "expires_at"): "ts", ("agent_setup_codes", "used_at"): "ts",
    ("agents", "last_poll_at"): "ts", ("agents", "status_at"): "ts", ("bg_jobs", "beat_at"): "ts",
    ("bg_jobs", "finished_at"): "ts", ("bg_jobs", "started_at"): "ts", ("ctr_notices", "sent_at"): "ts",
    ("hook_in", "last_used_at"): "ts", ("job_watch", "cleared_at"): "ts", ("kalmido_migrations", "applied_at"): "ts",
    ("kk_conns", "synced_at"): "ts", ("mail_in_seen", "seen_at"): "ts", ("nl_conns", "synced_at"): "ts",
    ("nl_members", "synced_at"): "ts", ("nl_runs", "ended_at"): "ts", ("nl_runs", "started_at"): "ts",
    ("notifications", "read_at"): "ts", ("notify_channels", "last_at"): "ts", ("pl_sources", "synced_at"): "ts",
    ("playbook_proposals", "decided_at"): "ts", ("quiet_push_held", "first_at"): "ts", ("quiet_push_held", "last_at"): "ts",
    ("rss_items", "fetched_at"): "ts", ("tidy_pending", "sent_at"): "ts", ("upload_scan", "checked_at"): "ts",
    ("upload_scan", "next_at"): "ts",
}
# (end of part D1)
#
#
#
# ---------------------------------------------------------------------------------------------------------------------------
# Part D2: accounts and access (sessions, users, oauth, tokens, portal, public links, organisations, admin, webhooks, ...)
# ---------------------------------------------------------------------------------------------------------------------------
CT_D2 = {  # orgs.retain_until / webhooks.org_grace_until are days (the last day kept / of the grace period, compared with today)
    ("admin_alerts", "sent_at"): "ts", ("admin_login_ips", "first_at"): "ts", ("admin_login_ips", "last_at"): "ts",
    ("api_tokens", "expires_at"): "ts", ("api_tokens", "last_used_at"): "ts", ("app_passwords", "last_used_at"): "ts",
    ("conn_requests", "decided_at"): "ts", ("disc_profiles", "confirmed_at"): "ts", ("disc_tokens", "expires_at"): "ts",
    ("oauth_codes", "expires_at"): "ts", ("oauth_codes", "used_at"): "ts", ("oauth_grants", "last_used_at"): "ts",
    ("oauth_grants", "refresh_expires_at"): "ts", ("oauth_grants", "revoked_at"): "ts", ("org_keys", "migrated_at"): "ts",
    ("org_keys", "recovery_shown_at"): "ts", ("org_keys", "rot_started_at"): "ts", ("org_keys", "rotated_at"): "ts",
    ("org_out_requests", "decided_at"): "ts", ("orgs", "ret_hold_at"): "ts", ("orgs", "retain_until"): "date",
    ("orgs", "retired_at"): "ts", ("portal_logins", "expires_at"): "ts", ("portal_logins", "revoked_at"): "ts",
    ("portal_logins", "used_at"): "ts", ("portal_tickets", "last_mail_at"): "ts", ("portal_tickets", "last_seen_at"): "ts",
    ("public_links", "expires_at"): "ts", ("public_links", "last_used_at"): "ts", ("recovery_codes", "used_at"): "ts",
    ("sessions", "expires_at"): "ts", ("sessions", "last_seen_at"): "ts", ("sessions", "stepup_at"): "ts",
    ("support_grants", "ended_at"): "ts", ("support_grants", "ends_at"): "ts", ("user_invites", "expires_at"): "ts",
    ("user_invites", "sent_at"): "ts", ("user_invites", "used_at"): "ts", ("user_keys", "migrated_at"): "ts",
    ("users", "delete_at"): "ts", ("users", "drop_token_at"): "ts", ("users", "ical_token_at"): "ts",
    ("view_layout_offers", "decided_at"): "ts", ("webauthn_creds", "last_used_at"): "ts",
    ("webhooks", "org_grace_until"): "date",
}
# 2.1115.0 (#5951) part D2: the sign-in and access rows fail closed when an old database turns (core/coltype.py _ct_more).
# "all": a mark that ends something - a one-time code or link used, an access revoked or ended, a deletion asked for. NULL
# there means "still open", so neither '' nor a text that is no point in time may become NULL (a used code would count again):
# both take the fill of a NOT NULL column (the row's created_at, else the start's time).
# "misfit": an end where NULL means "never" and '' meant "never" too (api/v1.py, lists/public.py), but a text that is no point
# in time ended in an error: it takes the fill (= ended), '' stays "never".
CT_D2_CLOSED = {("oauth_codes", "used_at"): "all", ("oauth_grants", "revoked_at"): "all", ("portal_logins", "revoked_at"): "all",
                ("portal_logins", "used_at"): "all", ("recovery_codes", "used_at"): "all", ("user_invites", "used_at"): "all",
                ("support_grants", "ended_at"): "all", ("users", "delete_at"): "all",
                ("orgs", "ret_hold_at"): "all", ("orgs", "retired_at"): "all",  # review (#5951): held / retired, '' set too
                ("api_tokens", "expires_at"): "misfit", ("public_links", "expires_at"): "misfit"}
CT_CLOSED = CT_D2_CLOSED  # read by core/coltype.py _ct_more (only part D2 has such columns)
# (end of part D2)
#
#
#
CT_MORE = {**CT_B, **CT_C, **CT_D1, **CT_D2}
