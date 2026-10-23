"""2.37.0 (#1150): row-level security, stage 1 -- the second floor under the app's own organisation checks (core/access.py).

Every table with an org_id gets ENABLE + FORCE ROW LEVEL SECURITY and one policy (reading AND writing):

    app.role = 'system'  OR  org_id IS NULL (only where the column is nullable: private rows, the app decides)
                         OR  org_id = ANY (app.org_ids)

orgs and org_members have their own policies (an organisation: only its members see it; a membership row: the person's own
rows and the rows of their organisations). The values come from the transaction's context (core/pg.py: app.user_id,
app.org_ids, app.role, set per transaction from the request -- "user" / "agent" / "anon" -- or "system" for background
work, start-up and system_ctx()). An empty context (outside every transaction) is "no organisation": only rows without one.

A login role that is a superuser or has BYPASSRLS ignores every policy (the official postgres image makes POSTGRES_USER a
superuser). Then the app works through the role kalmido_app (NOLOGIN, no bypass; created and granted here, entered with SET
ROLE on every pooled connection, core/pg.py) -- start-up, migrations and the backup keep the login role.

apply() runs inside init_db's transaction on every start and is idempotent. TABLES is the reviewed list: a new table with an
org_id that is missing here still gets the policy at start-up (with a warning), and tests/rls_static_test.py fails.
"""

APP_ROLE = "kalmido_app"

# tables whose rows belong to an organisation (column org_id); orgs / org_members have their own policies below
TABLES = (
    "agents", "books", "clients", "ev_cals", "lists", "org_list_log",
    "office_company", "office_contracts", "office_doc_items", "office_doc_log", "office_docs", "office_equipment",
    "office_numbers", "office_payments", "office_services", "office_sets", "office_settings", "office_texts",
    "office_import_runs", "office_archive",  # 2.39.1 (#1182)
    "office_client_contacts",  # 2.40.0 (#1380): contact persons of a client (org_id like the client)
    "office_roles", "office_doc_parts", "office_purchases",  # 2.47.0 (#1649, #1215, #1216)
    "office_trips", "office_trip_items", "office_fixed_costs",  # 2.47.3 (#1022, #1652, part B)
    "office_cf_start", "office_cf_adjust", "office_cf_actual",  # 2.123.0 D (#2341): account balance of the cash flow
    "office_trip_purposes",  # 2.117.0 A (#2292): own purposes of trips
    "office_meals", "office_meal_files", "office_meal_choices", "office_meal_log",  # 2.119.0 A (#2288): entertainment receipts
    "office_bank_imports", "office_bank_tx",  # 2.90.0 B (#1921): bank reconciliation
    "office_bank_balances",  # 2.124.0 D (#2342): balances of the imported statements
    "office_inv_series", "office_sub_reminders",  # 2.91.0 A (#1923), B (#1924)
    "office_dunning_marks",  # 2.147.1 B (#2054): suggested payment reminders
    "office_doc_templates", "office_gen_docs",  # 2.93.0 A (#1927): document templates and the documents made from them
    "office_privacy_sheets",  # 2.154.0 C (#2192): data protection sheets of a client
    "office_vehicles", "office_drives", "office_drive_log",  # 2.93.0 B (#1928): the logbook
    "office_cashbooks", "office_cash_entries", "office_cash_closings", "office_cash_log",  # 2.121.0 B (#2095): the cash book
    "office_period_locks",  # 2.148.0 A (#2471): locked accounting periods
    "office_procdocs",  # 2.148.0 C (#2472): versions of the procedure documentation (GoBD)
    "office_suppliers", "office_opening_balances",  # 2.148.0 D (#2458): the DATEV import (creditors, opening balances)
    "office_letters", "office_letter_links", "office_letter_blocks", "office_letter_profiles",  # 2.153.0 (#2028, #2030): correspondence
    "office_drive_closed",  # 2.152.0 C (#2169): closed months of the logbook
    "org_keys",  # 2.42.0 (#828): the wrapped key of an organisation (read and written by core/orgcrypt.py as "system")
    "wiki_pages",  # 2.49.0 C (#1199): knowledge pages (NULL = private, the app checks owner_id)
    "wiki_spaces",  # 2.64.3 A (#1817): the lock per knowledge space (NULL = a private space, the app checks owner_id)
    "wiki_files",  # 2.99.0 A (#2182): files of knowledge pages (NULL = private, the app checks owner_id like the page)
    "wiki_shares",  # 2.123.0 B (#2104): shares of knowledge pages / folders (NULL = private, the app checks owner_id)
    "wiki_versions",  # 2.123.0 A (#2102): the history of knowledge pages (NULL = private, the app checks the page)
    "fs_nodes",  # 2.48.0 (#1207): the file store (org_id NULL = a person's own tree)
    "fs_upload_requests",  # 2.122.0 A (#2097): file requests of a folder (NULL = private, the app checks the folder)
    "doc_meta", "doc_senders", "doc_types", "doc_tags", "doc_rules", "doc_models", "doc_cfg", "doc_mail",  # 2.48.0 (#1111): documents
    "doc_fields", "doc_field_values",  # 2.153.0 (#2179): custom fields of documents (NULL = a person's own workspace)
    "pl_sources", "pl_imported",  # 2.48.0 (#1152): the Paperless-ngx connection + what came in
    "pl_rules",  # 2.69.0 B (#1847): where a document rule from Paperless-ngx came from
    "rc_receipts", "rc_suggest",  # 2.48.0 (#1356): receipts: project / category, the agents' suggestions
    "office_deals",  # 2.50.0 B (#1196): the sales pipeline
    "hub_absences",  # 2.50.0 A (#1195): absences (the area they were entered in; the app hides the kind)
    "hub_leave_quota",  # 2.125.0 A (#2117): vacation accounts (the area like hub_absences)
    "hub_bookings",  # 2.50.0 A (#1194): bookings of the disposition
    "office_signoffs",  # 2.50.0 C (#1200): approval links (NULL = a private list's acceptance, the app checks the list)
    "video_reviews", "video_versions", "video_comments",  # 2.99.1 A (#1959): video sign-offs (NULL = private, the app checks owner / task / list / client)
    "office_pay_props",  # 2.51.0 A (#1350): payment suggestions of agents
    "task_bell",  # 2.53.0 C (#1424): the bell of one task per person (NULL = a private list's task)
    "time_sheets",  # 2.125.0 B (#2119): monthly timesheets (NULL = a person without organisation, the app checks user_id)
    "nl_conns", "nl_segments", "nl_members", "nl_runs",  # 2.55.0 E (#1455): the newsletter connection (NULL = a person's own)
    "nl_suppress", "nl_consent_log",  # 2.152.0 D (#2170): suppression list + consent log (hash only)
    "task_vectors",  # 2.59.0 B (#1375): the text vectors of related tasks (NULL = a private list's task)
    "upload_scan",  # 2.61.0 A (#1818): unchecked / infected uploads (NULL = a private file; files/scan.py)
    "file_text",  # 2.61.0 C (#1820): recognised text of stored files (NULL = a private file, the app checks the file)
    "portal_tickets", "portal_logins",  # 2.63.0 (#1513): customer reports + portal sign-ins (NULL = a private list, the app checks owner_id)
    "merge_runs",  # 2.66.0 (#1835): merges of contacts / clients (NULL = a person's own book / office, the app checks)
    "pl_uploads",  # 2.69.0 A (#1846): an uploaded Paperless-ngx export (NULL = a person's own space)
    "task_links",  # 2.71.0 B (#1459): a task shown in a further list (NULL = private lists, the app checks both lists)
    "list_rules",  # 2.71.0 A (#1457): rules of a list (org_id follows the list, NULL = a private list)
    "office_pack_installs",  # 2.76.0 A (#1023): packs installed from the catalogue per office area
    "hub_tokens", "hub_mails",  # 2.84.0 A (#1198): hub mail addresses + filed mails (NULL = private, the app checks owner / client / list)
    "hub_mail_links",  # 2.141.0 B (#2139): tasks / events made from a filed mail (org_id like the mail, NULL = private, the app checks)
    "hub_mailboxes",  # 2.141.0 A (#2141): the own mailbox of a workspace (NULL = a person's private space, the app checks owner_id)
    "office_archive_log",  # 2.81.0 B (#1834): the history of an archived document (org_id like the entry)
    "tchat_rooms", "tchat_files",  # 2.113.1 B (#2059): team chat channels of an organisation + their files (NULL = DMs, list channels, own space; the app checks members)
    "sheets",  # 2.89.0 (#1916): tables (NULL = private, the app checks owner_id; parts hang on sheet_id)
    "sheet_shares",  # 2.124.0 C (#2113): a table shared with one person / agent (org_id like the table, NULL = a private table)
    "sched_polls",  # 2.98.0 A (#1953): scheduling polls (NULL = private, the app checks user_id; options / votes hang on poll_id)
    "office_agreements",  # 2.92.0 A (#1925): business contracts and insurances of an office area
    "bookmarks",  # 2.97.0 A (#1950): bookmarks (NULL = private, the app checks user_id)
    "office_contract_files",  # 2.117.0 B (#2285): PDF files of a framework contract
    "sheet_files",  # 2.124.0 B (#2110): files of file cells of a table (NULL = private, the app checks the sheet)
    "office_undo",  # 2.111.0 A (#2233): undo copies of office editors (NULL = a private client, the app checks user_id)
    "fs_ext_links",  # 2.112.1 B (#2058): external share links of the file store (org_id = the node's, NULL = private)
    "org_invites",  # 2.115.0 B (#2062): accounts an organisation invited by e-mail (always an organisation's)
    "webhooks",  # 2.115.0 A (#2061): outgoing webhooks (NULL = a person's own / an agent's, else its organisation's admins)
    "notify_channels",  # 2.142.0 A (#2145): notification channels (NULL = a person's own, else its organisation's admins)
    "org_joins",  # 2.148.1 A (#2480): invitations of existing accounts (the invited person reads its own rows in system_ctx)
    "office_peppol", "office_peppol_sends",  # 2.154.0 B (#1960): the Peppol connection of an office area + its sends
    "section_templates",  # 2.156.0 C (#2073): section templates (NULL = a person's own, the app checks user_id)
    "rss_feeds",  # 2.172.0 B (#2677): feeds (NULL = private, the app checks user_id; articles / read marks hang on feed_id)
    "reading_orgs",  # 2.172.0 B (#2677): the read-later project of an organisation
    "life_trip_costs",  # 2.173.0 A (#2680): the office trip of a trip project (org_id = the office area)
)
OWN_POLICY = ("orgs", "org_members")
POLICY = "kalmido_org"

SYS = "NULLIF(current_setting('app.role', true), '') = 'system'"
ORG_IDS = "string_to_array(NULLIF(current_setting('app.org_ids', true), ''), ',')::bigint[]"
UID = "NULLIF(current_setting('app.user_id', true), '')::bigint"


def rule(nullable, col="org_id"):
    """The USING / WITH CHECK expression of an organisation table."""
    return f"{SYS}" + (f" OR {col} IS NULL" if nullable else "") + f" OR {col} = ANY ({ORG_IDS})"


OWN_RULES = {
    "orgs": f"{SYS} OR id = ANY ({ORG_IDS})",
    "org_members": f"{SYS} OR user_id = {UID} OR org_id = ANY ({ORG_IDS})",
    # 2.125.0 R (#2119): a person keeps their own timesheets after leaving the organisation (the lock of an approved month)
    "time_sheets": f"{rule(True)} OR user_id = {UID}",
}


def org_tables(c):
    """{table: nullable} of every base table of the schema with a column org_id (from the database itself)."""
    return {r[0]: r[1] == "YES" for r in c.execute(
        "SELECT c.table_name, c.is_nullable FROM information_schema.columns c JOIN information_schema.tables t "
        "ON t.table_schema=c.table_schema AND t.table_name=c.table_name "
        "WHERE c.table_schema=current_schema() AND c.column_name='org_id' AND t.table_type='BASE TABLE'")}


def _policy(c, table, expr):
    c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # also for the owner
    c.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    c.execute(f"CREATE POLICY {POLICY} ON {table} USING ({expr}) WITH CHECK ({expr})")


# 2.37.0 (review W2-2): the result of the last apply() -- False when the login role bypasses row-level security and the
# app role cannot be used (core/db.py init_db: exit 3 in the modes with several organisations, else a security alert at
# every start and a line in the admin alerts settings)
STATE = {"enforced": True, "policies": ""}  # 2.183.0 B (#2666): policies "applied" / "skipped"

OFF_HELP = ("row-level security is NOT enforced: the database user is a superuser or has BYPASSRLS, and the role "
            f"{APP_ROLE} does not exist or cannot be entered (the database user may not create roles). Either allow the "
            "database user to create roles (ALTER ROLE <user> CREATEROLE; Kalmido creates and enters the role itself at the "
            f"next start), or create it once as a superuser: CREATE ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS; GRANT {APP_ROLE} TO "
            "<user>; -- or connect with a database user without BYPASSRLS that owns the database.")


# 2.183.0 B (#2666): the body of kalmido_org_count (compared with pg_proc.prosrc before it is replaced)
ORG_COUNT_SRC = ("DECLARE prev text := current_setting('app.role', true); n bigint; "
                 "BEGIN PERFORM set_config('app.role', 'system', true); SELECT COUNT(*) INTO n FROM orgs WHERE personal_of IS NULL AND retired_at IS NULL; "
                 "PERFORM set_config('app.role', COALESCE(prev, ''), true); RETURN n; END")
# how _policy() makes a policy: change it together with _policy() (part of the hash, so every database gets it again)
POLICY_FORM = "1: ENABLE + FORCE, DROP + CREATE POLICY USING / WITH CHECK"
SIG_KEY = "rls_sig"  # kalmido_meta: "<rules hash>:<catalog hash>" of the last apply()


def _sig_code(want):
    """2.183.0 B (#2666): hash of what apply() would create (tables, rules, policy name, how a policy is made)."""
    import hashlib
    body = "\n".join(f"{t}\t{want[t]}" for t in sorted(want))
    return hashlib.sha256(f"{POLICY_FORM}\n{POLICY}\n{body}".encode()).hexdigest()


def _sig_catalog(c, want):
    """2.183.0 B (#2666): hash of the catalog state of the policies -- None when a table lacks ENABLE or FORCE, or its policy."""
    import hashlib
    rows = c.execute(
        "SELECT r.relname, r.relrowsecurity, r.relforcerowsecurity, p.polcmd, p.polpermissive, p.polroles::text, "
        "pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid) "
        "FROM pg_class r LEFT JOIN pg_policy p ON p.polrelid=r.oid AND p.polname=? "
        "WHERE r.relnamespace=current_schema()::regnamespace AND r.relkind IN ('r','p') AND r.relname::text = ANY(string_to_array(?, ',')) "
        "ORDER BY r.relname", (POLICY, ",".join(sorted(want)))).fetchall()
    if len(rows) != len(want) or any(not (r[1] and r[2]) or r[3] is None or r[6] is None or r[7] is None for r in rows):
        return None
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def _sig_get(c):
    r = c.execute("SELECT value FROM kalmido_meta WHERE key=?", (SIG_KEY,)).fetchone()
    return r[0] if r else None


def apply(c):
    """Policies + the app role (inside init_db's transaction; the caller commits). Returns True when row-level security
    holds for the app's requests (STATE["enforced"])."""
    have = org_tables(c)
    extra = sorted(set(have) - set(TABLES) - set(OWN_POLICY))
    if extra:
        print("warning: row-level security: table(s) with org_id missing in core/rls.py TABLES:", ", ".join(extra), flush=True)
    want = {t: rule(nullable) for t, nullable in have.items() if t not in OWN_POLICY}
    want.update(OWN_RULES)
    # 2.183.0 B (#2666): ALTER TABLE / CREATE POLICY lock the table exclusively; a second process that starts next to the
    # running server (CLI, a helper importing the app) skips them when nothing would change -- the code's rules AND the
    # catalog state recorded after the last apply must both match (kalmido_meta may come back older with a backup)
    sig, cat = _sig_code(want), _sig_catalog(c, want)
    if cat and _sig_get(c) == f"{sig}:{cat}":
        STATE["policies"] = "skipped"
    else:
        for t, nullable in sorted(have.items()):
            if t not in OWN_POLICY:
                _policy(c, t, rule(nullable))
        for t, expr in OWN_RULES.items():
            _policy(c, t, expr)
        cat = _sig_catalog(c, want)
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (SIG_KEY, f"{sig}:{cat or '-'}"))  # "-" never matches: the next start applies again
        STATE["policies"] = "applied"
    # the organisation count of the boundary rule (core/access.py _boundary_sql) is instance structure, not content: the
    # same answer for everybody ("system" inside the function only, the caller's value back before it returns). 2.37.0
    # (review W2-4): not as "SET app.role" clause of the function -- only a superuser may store a custom setting there, so
    # a database owner without superuser could not start
    if not c.execute("SELECT 1 FROM pg_proc WHERE proname='kalmido_org_count' AND pronamespace=current_schema()::regnamespace "
                     "AND prosrc=? AND provolatile='s'", (ORG_COUNT_SRC,)).fetchone():  # 2.183.0 B (#2666): only when changed
        c.execute("CREATE OR REPLACE FUNCTION kalmido_org_count() RETURNS bigint LANGUAGE plpgsql STABLE AS $f$" + ORG_COUNT_SRC + "$f$")
    STATE["enforced"] = _app_role(c)
    if not STATE["enforced"]:
        print("warning: " + OFF_HELP, flush=True)
    return STATE["enforced"]


def _app_role(c):
    """When the login role bypasses row-level security: the role the app's pooled connections switch to. Returns False
    when that is needed but impossible."""
    r = c.execute("SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
    if not r or not (r[0] or r[1]):
        return True  # the login role is subject to the policies itself (it owns the tables: FORCE)
    exists = bool(c.execute("SELECT 1 FROM pg_roles WHERE rolname=?", (APP_ROLE,)).fetchone())
    if r[0] or r[2]:
        # a role belongs to the whole cluster (several Kalmido databases may share one): create it once, race-safe
        c.execute(f"DO $r$BEGIN CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
                  f"EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; END$r$")
        c.execute(f"ALTER ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS")
    elif not exists:
        return False
    c.execute(f"GRANT USAGE ON SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    if r[0]:
        return True  # a superuser may SET ROLE to any role
    # without superuser SET ROLE needs a membership with the SET option (the creator's own automatic one has none)
    if not _can_set(c) and r[2]:
        c.execute(f"GRANT {APP_ROLE} TO CURRENT_USER")
    return _can_set(c)


def _can_set(c):
    return bool(c.execute(f"SELECT pg_has_role(current_user, '{APP_ROLE}', 'SET')").fetchone()[0])


def _schema(c):
    return '"' + c.execute("SELECT current_schema()").fetchone()[0].replace('"', '""') + '"'


def enter_sql():
    """For core/pg.py: true when a new pooled connection must switch to the app role (the login role bypasses row-level
    security, the role exists and may be entered)."""
    return (f"SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{APP_ROLE}') "
            f"THEN (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user) "
            f"AND pg_has_role(current_user, '{APP_ROLE}', 'SET') ELSE false END")
