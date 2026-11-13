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

apply() runs inside init_db's transaction on every start and is idempotent. The tables come from the database itself (every
base table with a column org_id, org_tables), not from a hand-kept list (#4314): a new table with an org_id gets the policy at
the next start without an entry anywhere.
"""

import time

from .pg import qi, table_names  # 2.1079.0 (#5654): _lock_all

APP_ROLE = "kalmido_app"
# 2.1090.0 (#5941): no hand list of tables here (TABLES / DROPPED went) - apply() takes every org_id table from the database.

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


# 2.1079.0 (#5654): a start that applies the policies next to the running server (a CLI, a helper importing the app) locked
# its ~300 tables one after the other with ALTER TABLE; a background transaction of the server holding one table and reading
# the next deadlocked with it (CI v2.941.0: four starts in a row). Now every table is locked in ONE statement first, each wait
# shorter than Postgres' deadlock_timeout (1 s): the start gives way (back to a savepoint, nothing held) and tries again
RLS_LOCK_WAIT_MS = 400
RLS_LOCK_TRIES = 50  # then the ALTER TABLEs wait as before


def _lock_all(c, tables):
    """2.1079.0 (#5654): ACCESS EXCLUSIVE on all tables inside init_db's transaction, or nothing (the caller's ALTERs then
    lock one by one as before). True when locked."""
    if not tables:
        return True
    ok = table_names(c)  # the allowlist of qi(): the names come from the catalog (org_tables) and OWN_RULES
    prev = c.execute("SELECT current_setting('lock_timeout')").fetchone()[0]
    done = False
    for i in range(RLS_LOCK_TRIES):
        try:
            with c.savepoint():
                c.execute(f"SET LOCAL lock_timeout = '{RLS_LOCK_WAIT_MS}ms'")
                c.execute(f"LOCK TABLE {', '.join(qi(t, ok) for t in sorted(tables))} IN ACCESS EXCLUSIVE MODE")
            done = True
            break
        except Exception as e:  # noqa: BLE001 - only a lock wait over the limit (or a deadlock) is retried
            if getattr(e, "sqlstate", None) not in ("55P03", "40P01"):
                raise
            time.sleep(0.05 * (1 + i % 4))
    c.execute("SELECT set_config('lock_timeout', ?, true)", (prev,))  # SET LOCAL outlives RELEASE SAVEPOINT
    if not done:
        print(f"row-level security: the tables stayed busy ({RLS_LOCK_TRIES} tries), locking one by one", flush=True)
    return done


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
    """2.183.0 B (#2666): hash of the catalog state of the policies -- None when a table lacks ENABLE or FORCE, or its policy,
    or has any other policy (only kalmido_org belongs there; then every start applies and warns)."""
    import hashlib
    rows = c.execute(
        "SELECT r.relname, r.relrowsecurity, r.relforcerowsecurity, p.polcmd, p.polpermissive, p.polroles::text, "
        "pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid), "
        "(SELECT COUNT(*) FROM pg_policy o WHERE o.polrelid=r.oid AND o.polname<>?) "  # pg-ok: pg_catalog oid, not SQLite rowid
        "FROM pg_class r LEFT JOIN pg_policy p ON p.polrelid=r.oid AND p.polname=? "  # pg-ok: pg_catalog oid, not SQLite rowid
        "WHERE r.relnamespace=current_schema()::regnamespace AND r.relkind IN ('r','p') AND r.relname::text = ANY(string_to_array(?, ',')) "
        "ORDER BY r.relname", (POLICY, POLICY, ",".join(sorted(want)))).fetchall()
    other = [r[0] for r in rows if r[8]]
    if other:
        print("warning: row-level security: other policies than", POLICY, "on:", ", ".join(other), flush=True)
    if other or len(rows) != len(want) or any(not (r[1] and r[2]) or r[3] is None or r[6] is None or r[7] is None for r in rows):
        return None
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def _sig_get(c):
    r = c.execute("SELECT value FROM kalmido_meta WHERE key=?", (SIG_KEY,)).fetchone()
    return r[0] if r else None


def apply(c):
    """Policies + the app role (inside init_db's transaction; the caller commits). Returns True when row-level security
    holds for the app's requests (STATE["enforced"])."""
    have = org_tables(c)  # #4314: every base table with an org_id, no hand list
    want = {t: rule(nullable) for t, nullable in have.items() if t not in OWN_POLICY}
    want.update(OWN_RULES)
    # 2.183.0 B (#2666): ALTER TABLE / CREATE POLICY lock the table exclusively; a second process that starts next to the
    # running server (CLI, a helper importing the app) skips them when nothing would change -- the code's rules AND the
    # catalog state recorded after the last apply must both match (kalmido_meta may come back older with a backup)
    sig, cat = _sig_code(want), _sig_catalog(c, want)
    if cat and _sig_get(c) == f"{sig}:{cat}":
        STATE["policies"] = "skipped"
    else:
        _lock_all(c, set(have) | set(OWN_RULES))  # 2.1079.0 (#5654): every table at once, giving way to the running server
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


# 2.281.0 E (#3117): the answer of enter_sql() for this process, for ENTER_TTL_S -- the same for every pooled connection (one
# login role, one database); only a database admin changes it (and init_db, which drops it via enter_forget / pool_refresh).
ENTER_TTL_S = 600
_ENTER = {"v": None, "at": 0.0}


def enter_cached():
    """True / False while the remembered answer is fresh, else None (then ask the database and enter_store it)."""
    v = _ENTER["v"]
    return v if v is not None and time.monotonic() - _ENTER["at"] < ENTER_TTL_S else None


def enter_store(v):
    _ENTER["v"], _ENTER["at"] = bool(v), time.monotonic()


def enter_forget():
    _ENTER["v"] = None


def rls_org_open(c, oid):
    """2.602.0 (#4729): True when the policy above already lets the request's context read the rows of organisation oid
    (org_id = ANY (app.org_ids), orgs: id = ANY (app.org_ids)) - then a read of them needs no switch to "system" (two
    set_config in a transaction, audit Q budget of /api/state). The rows read are the same either way; outside a request,
    or for an organisation the context does not hold (the own hidden area, one made in this transaction), False: the caller
    keeps its system_ctx() block."""
    if not oid:
        return False
    from .access import acx_conn_hook  # core/access imports this module's neighbours; late, no cycle
    ctx = acx_conn_hook(c)
    return ctx is not None and int(oid) in (ctx[1] or ())
