"""2.362.4 (#3107): what stays out of the exports on purpose, with the reason. Plain assignments only: tools/check_export_tables.py
reads this file without the app (the CI lint step), and a table with people's data that is in no export and not here fails it. The
manifests name these lines in not_included (left_lines), so "not in the file" comes from one list. The organisation export keeps its
list in admin/orgexport.py OX_LEFT."""

from ..core.i18n import tr

_SECRET = "credentials, keys and link secrets"
_SERVER = "state of this server (queues, limits, sign-in records, import records)"
_DERIVED = "derived or working data, rebuilt on the target"
_VIEW = "what a person has seen or hidden, the order of their rows"
_AGENT = "agents and their logs (agents are connected anew)"
_ORG = "data of an organisation or an office: the organisation export, a person's own office the retention export"
_SHARE = "who shares what with whom (a share is made anew on the target)"
_FILES = "the receipt files of household budgets (their entries are included)"
_LATER = "not yet in the account export"
_RX_SECRET = "credentials"
_RX_WORK = "working data of the office (balances, plans, locks, undo steps, the trash), no record of its own"
_RX_FILES = "costs and choices behind documents and receipts: the documents and receipts themselves are in the export"
_RX_MASTER = "settings and master data of the office, no record with a duty to keep"

# the tables umz_build reads beyond its queries: the budgets (life/budget.py bud_export), the current version of my files
UMZ_BUILD_TABLES = ('budget_cats', 'budget_entries', 'budget_recurring', 'fs_versions')

# every table with a person, organisation, list or task column that is not in the account export
UMZ_LEFT_TABLES = {
    "agent_audit": _AGENT, "agent_burst_held": _SERVER, "agent_decisions": _AGENT, "agent_jobs": _AGENT, "agent_job_tasks": _AGENT, "job_watch": _AGENT, "agent_list_access": _AGENT, "agent_rules": _AGENT, "agent_usage": _AGENT,
    "agents": _AGENT, "folder_agents": _AGENT,
    "budget_meta": _DERIVED, "contact_occ": _DERIVED, "dav_meta": _DERIVED, "dav_sync": _DERIVED, "dav_sync2": _DERIVED, "dl_changes": _DERIVED,
    "doc_models": _DERIVED, "file_text": _DERIVED, "git_closes": _DERIVED, "git_links": _DERIVED, "list_activity": _DERIVED, "list_ticket_seq": _DERIVED,
    "rc_suggest": _DERIVED, "rss_items": _DERIVED, "sheet_lastvals": _DERIVED, "task_vectors": _DERIVED,
    "budget_files": _FILES,
    "chat_saves": _LATER, "contact_links": _LATER, "contact_tasks": _LATER, "ctr_notices": _LATER, "folder_heads": _LATER, "folder_props": _LATER,
    "fs_log": _LATER, "git_branches": _LATER, "git_folders": _LATER, "issue_reports": _LATER, "kid_rewards": _LATER, "life_trip_costs": _LATER,
    "list_rule_runs": _LATER, "section_templates": _LATER, "sheet_links": _LATER, "shop_memory": _LATER,
    "wiki_spaces": _LATER, "wiki_versions": _LATER,
    "clients": _ORG, "doc_cfg": _ORG, "doc_fetch_portals": _ORG, "doc_field_values": _ORG, "doc_fields": _ORG, "doc_meta": _ORG, "doc_rules": _ORG,
    "doc_senders": _ORG, "doc_tags": _ORG, "doc_types": _ORG, "hub_bookings": _ORG, "hub_mail_links": _ORG, "nl_consent_log": _ORG,
    "nl_members": _ORG, "nl_suppress": _ORG, "office_agreements": _ORG, "office_archive": _ORG, "office_archive_log": _ORG, "office_bank_balances": _ORG,
    "office_bank_accounts": _ORG, "office_bank_imports": _ORG, "office_bank_rule_nos": _ORG, "office_bank_rules": _ORG, "office_bank_tx": _ORG, "office_bank_vendors": _ORG,
    "office_bookarch": _ORG, "office_bookarch_accts": _ORG, "office_bookarch_docs": _ORG, "office_bookarch_files": _ORG, "office_cash_closings": _ORG,
    "office_cash_entries": _ORG, "office_cash_log": _ORG, "office_cashbooks": _ORG, "office_cc_cards": _ORG, "office_cc_lines": _ORG,
    "office_cc_statements": _ORG, "office_cf_actual": _ORG, "office_cf_adjust": _ORG, "office_cf_start": _ORG, "office_client_contacts": _ORG,
    "office_company": _ORG, "office_contract_files": _ORG, "office_contracts": _ORG, "office_datev_guids": _ORG, "office_deals": _ORG, "office_doc_items":
    _ORG, "office_doc_log": _ORG, "office_doc_parts": _ORG, "office_doc_templates": _ORG, "office_docs": _ORG, "office_drive_closed": _ORG,
    "office_drive_log": _ORG, "office_drives": _ORG, "office_dunning_marks": _ORG, "office_equipment": _ORG, "office_fixed_costs": _ORG,
    "office_gen_docs": _ORG, "office_import_runs": _ORG, "office_inv_series": _ORG, "office_letter_blocks": _ORG, "office_letter_links": _ORG,
    "office_letter_profiles": _ORG, "office_letters": _ORG, "office_meal_choices": _ORG, "office_meal_files": _ORG, "office_meal_log": _ORG,
    "office_meals": _ORG, "office_numbers": _ORG, "office_opening_balances": _ORG, "office_pack_installs": _ORG, "office_pay_props": _ORG,
    "office_payonline": _ORG, "office_pay_links": _ORG, "office_pay_sessions": _ORG, "office_pay_events": _ORG, "office_pay_payouts": _ORG,
    "office_payments": _ORG, "office_peppol": _ORG, "office_peppol_sends": _ORG, "office_period_locks": _ORG, "office_privacy_sheets": _ORG,
    "office_procdocs": _ORG, "office_purchases": _ORG, "office_rgroup_members": _ORG, "office_rgroups": _ORG, "office_rights_log": _ORG, "office_roles":
    _ORG, "office_services": _ORG, "office_sets": _ORG, "office_settings": _ORG, "office_signoffs": _ORG, "office_sub_reminders": _ORG,
    "office_suppliers": _ORG, "office_texts": _ORG, "office_trash": _ORG, "office_trip_items": _ORG, "office_trip_purposes": _ORG, "office_trips": _ORG,
    "office_undo": _ORG, "office_vehicles": _ORG, "org_joins": _ORG, "support_grants": _SERVER, "org_members": _ORG, "rc_receipts": _ORG, "reading_orgs": _ORG, "tchat_files": _ORG,
    "tchat_rooms": _ORG,
    "abs_cal_feeds": _SECRET, "agent_setup_codes": _SECRET, "app_passwords": _SECRET, "contact_srcs": _SECRET, "disc_profiles": _SECRET, "disc_tokens":
    _SECRET, "doc_fetchers": _SECRET, "doc_mail": _SECRET, "ev_cal_feeds": _SECRET, "fs_ext_links": _SECRET, "fs_lock_keys": _SECRET, "fs_locks": _SECRET,
    "fs_upload_requests": _SECRET, "git_conns": _SECRET, "hook_in": _SECRET, "hub_tokens": _SECRET, "issue_hooks": _SECRET, "list_key_pending": _SECRET,
    "list_keys": _SECRET, "list_paperless": _SECRET, "mail_tokens": _SECRET, "notify_channels": _SECRET, "ntfy_inboxes": _SECRET, "org_invites": _SECRET,
    "paperless_links": _SECRET, "pl_conn_users": _SECRET, "pl_conns": _SECRET, "pl_imported": _SECRET, "pl_rules": _SECRET, "pl_sources": _SECRET,
    "pl_tokens": _SECRET, "pl_uploads": _SECRET, "portal_logins": _SECRET, "recovery_codes": _SECRET, "task_keys": _SECRET, "user_invites": _SECRET,
    "user_keys": _SECRET, "webauthn_creds": _SECRET, "wiki_key_pending": _SECRET, "wiki_keys": _SECRET, "wiki_shares": _SECRET,
    "admin_login_ips": _SERVER, "agent_push_held": _SERVER, "bg_jobs": _SERVER, "conn_blocks": _SERVER, "deleted_accounts": _SERVER, "disc_quota":
    _SERVER, "ev_invite_day": _SERVER, "ev_reminded": _SERVER, "idem_keys": _SERVER, "imports": _SERVER, "login_ips": _SERVER, "notify_mail_queue":
    _SERVER, "org_keys": _SERVER, "org_out_requests": _SERVER, "push_gate": _SERVER, "quiet_push_held": _SERVER, "sample_items": _SERVER, "task_push": _SERVER, "tidy_pending": _SERVER, "upload_scan":
    _SERVER,
    "book_members": _SHARE, "ev_cal_members": _SHARE, "folder_people": _SHARE, "fs_shares": _SHARE, "group_members": _SHARE, "group_shares": _SHARE,
    "groups": _SHARE, "sheet_shares": _SHARE, "tchat_members": _SHARE,
    "list_bell": _VIEW, "list_folder_skip": _VIEW, "list_mine_hide": _VIEW, "rss_reads": _VIEW, "task_seen": _VIEW, "tchat_reads": _VIEW,
    "tchat_thread_reads": _VIEW, "user_task_order": _VIEW, "wait_hidden": _VIEW,
}

# the office tables that are not in the retention export (admin/retexport.py RX_TABLES)
RX_LEFT_TABLES = {
    "office_meal_choices": _RX_FILES,
    "office_bank_rule_nos": _RX_MASTER, "office_bank_rules": _RX_MASTER, "office_bank_vendors": _RX_MASTER,
    "office_deals": _RX_MASTER, "office_doc_templates": _RX_MASTER, "office_fixed_costs": _RX_MASTER, "office_inv_series":
    _RX_MASTER, "office_letter_blocks": _RX_MASTER, "office_letter_profiles": _RX_MASTER,
    "office_pack_installs": _RX_MASTER, "office_pay_props": _RX_MASTER,
    "office_rgroup_members": _RX_MASTER, "office_rgroups": _RX_MASTER, "office_roles":
    _RX_MASTER, "office_services": _RX_MASTER, "office_sets": _RX_MASTER, "office_settings": _RX_MASTER, "office_sub_reminders": _RX_MASTER,
    "office_texts": _RX_MASTER, "office_trip_purposes": _RX_MASTER,
    "office_peppol": _RX_SECRET, "office_payonline": _RX_SECRET, "office_pay_links": _RX_SECRET,
    "office_pay_sessions": _RX_WORK, "office_pay_events": _RX_WORK, "office_pay_payouts": _RX_WORK,
    "office_cf_actual": _RX_WORK, "office_cf_adjust": _RX_WORK, "office_cf_start": _RX_WORK, "office_trash": _RX_WORK, "office_undo":
    _RX_WORK,
}


def left_lines(left, lg="en"):
    """{table: reason} -> the lines of a manifest's not_included: one per reason, with its tables. 2.464.0 (#3841): the reason in the
    language lg, the table names stay technical. The reasons are keys without N_ (core/i18nkeys.py reason_keys reads them)."""
    why = {}
    for t, r in sorted(left.items()):
        why.setdefault(r.replace(" (not_included)", ""), []).append(t)
    return [f"{tr(r, lg=lg)}: {', '.join(ts)}" for r, ts in why.items()]
