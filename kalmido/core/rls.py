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
    "office_numbers", "office_services", "office_sets", "office_settings", "office_texts",
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


def apply(c):
    """Policies + the app role (inside init_db's transaction; the caller commits)."""
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
    # same answer for everybody (SET app.role inside the function only)
    c.execute("CREATE OR REPLACE FUNCTION kalmido_org_count() RETURNS bigint LANGUAGE sql STABLE "
              "SET app.role = 'system' AS $$SELECT COUNT(*) FROM orgs$$")
    _app_role(c)


def _app_role(c):
    """When the login role bypasses row-level security: the role the app's pooled connections switch to."""
    r = c.execute("SELECT rolsuper OR rolbypassrls, rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
    if not r or not r[0]:
        return  # the login role is subject to the policies itself (it owns the tables: FORCE)
    if not r[1] and not c.execute("SELECT 1 FROM pg_roles WHERE rolname=?", (APP_ROLE,)).fetchone():
        print(f"warning: row-level security is NOT enforced: the database user bypasses it and may not create the role "
              f"{APP_ROLE}. Create it (NOLOGIN NOBYPASSRLS) and grant it to the database user.", flush=True)
        return
    # a role belongs to the whole cluster (several Kalmido databases may share one): create it once, race-safe
    c.execute(f"DO $r$BEGIN CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
              f"EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; END$r$")
    c.execute(f"ALTER ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS")
    c.execute(f"GRANT USAGE ON SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    c.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {_schema(c)} TO {APP_ROLE}")
    if not r[1]:  # BYPASSRLS without superuser: SET ROLE needs the membership
        c.execute(f"GRANT {APP_ROLE} TO CURRENT_USER")


def _schema(c):
    return '"' + c.execute("SELECT current_schema()").fetchone()[0].replace('"', '""') + '"'


def enter_sql():
    """For core/pg.py: true when a new pooled connection must switch to the app role (the login role bypasses row-level
    security, the role exists and may be entered)."""
    return (f"SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{APP_ROLE}') "
            f"THEN (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user) "
            f"AND pg_has_role(current_user, '{APP_ROLE}', 'MEMBER') ELSE false END")
