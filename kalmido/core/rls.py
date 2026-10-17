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
    "org_keys",  # 2.42.0 (#828): the wrapped key of an organisation (read and written by core/orgcrypt.py as "system")
    "wiki_pages",  # 2.49.0 C (#1199): knowledge pages (NULL = private, the app checks owner_id)
    "fs_nodes",  # 2.48.0 (#1207): the file store (org_id NULL = a person's own tree)
    "doc_meta", "doc_senders", "doc_types", "doc_tags", "doc_rules", "doc_models", "doc_cfg", "doc_mail",  # 2.48.0 (#1111): documents
    "pl_sources", "pl_imported",  # 2.48.0 (#1152): the Paperless-ngx connection + what came in
    "rc_receipts", "rc_suggest",  # 2.48.0 (#1356): receipts: project / category, the agents' suggestions
    "office_deals",  # 2.50.0 B (#1196): the sales pipeline
    "hub_absences",  # 2.50.0 A (#1195): absences (the area they were entered in; the app hides the kind)
    "hub_bookings",  # 2.50.0 A (#1194): bookings of the disposition
    "office_signoffs",  # 2.50.0 C (#1200): approval links (NULL = a private list's acceptance, the app checks the list)
    "office_pay_props",  # 2.51.0 A (#1350): payment suggestions of agents
    "task_bell",  # 2.53.0 C (#1424): the bell of one task per person (NULL = a private list's task)
    "nl_conns", "nl_segments", "nl_members", "nl_runs",  # 2.55.0 E (#1455): the newsletter connection (NULL = a person's own)
    "list_rules",  # 2.71.0 A (#1457): rules of a list (org_id follows the list, NULL = a private list)
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
STATE = {"enforced": True}

OFF_HELP = ("row-level security is NOT enforced: the database user is a superuser or has BYPASSRLS, and the role "
            f"{APP_ROLE} does not exist or cannot be entered (the database user may not create roles). Either allow the "
            "database user to create roles (ALTER ROLE <user> CREATEROLE; Kalmido creates and enters the role itself at the "
            f"next start), or create it once as a superuser: CREATE ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS; GRANT {APP_ROLE} TO "
            "<user>; -- or connect with a database user without BYPASSRLS that owns the database.")


def apply(c):
    """Policies + the app role (inside init_db's transaction; the caller commits). Returns True when row-level security
    holds for the app's requests (STATE["enforced"])."""
    have = org_tables(c)
    extra = sorted(set(have) - set(TABLES) - set(OWN_POLICY))
    if extra:
        print("warning: row-level security: table(s) with org_id missing in core/rls.py TABLES:", ", ".join(extra), flush=True)
    for t, nullable in sorted(have.items()):
        if t not in OWN_POLICY:
            _policy(c, t, rule(nullable))
    for t, expr in OWN_RULES.items():
        _policy(c, t, expr)
    # the organisation count of the boundary rule (core/access.py _boundary_sql) is instance structure, not content: the
    # same answer for everybody ("system" inside the function only, the caller's value back before it returns). 2.37.0
    # (review W2-4): not as "SET app.role" clause of the function -- only a superuser may store a custom setting there, so
    # a database owner without superuser could not start
    c.execute("CREATE OR REPLACE FUNCTION kalmido_org_count() RETURNS bigint LANGUAGE plpgsql STABLE AS $f$"
              "DECLARE prev text := current_setting('app.role', true); n bigint; "
              "BEGIN PERFORM set_config('app.role', 'system', true); SELECT COUNT(*) INTO n FROM orgs WHERE personal_of IS NULL; "
              "PERFORM set_config('app.role', COALESCE(prev, ''), true); RETURN n; END$f$")
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
