"""2.662.0 (#4602): the organisation of tasks, comments, events and contacts (column org_id, migrations.d/4602_a.py).

Their rows hang on a parent that carries the organisation: a task on its list, a comment on its task (and so on that task's list),
an event on its calendar (ev_cals), a contact on its address book (books). The denormalised org_id lets row-level security
(core/rls.py, the same rule as every organisation table: "system", NULL = private, or one of app.org_ids) guard these tables as
the second floor under the app's own scope (core/access.py vis_sql, which stays the first and decides as before).

Who writes it: the database, never the app. A BEFORE trigger sets org_id from the parent on every INSERT and on every move to
another parent (list_id, task_id, cal_id, book_id) -- also a value the writer put there itself is replaced. An AFTER trigger on the
parent carries a changed organisation to its children (a list / calendar / address book moved between organisations, or
between private and an organisation; a task moved to a list of another workspace takes its comments along). A trigger and not the
write paths in the app: there are some forty INSERT / move paths of these four tables (imports, mail, git, forms, portal, rules,
templates, the office, the version before ...), one missed path would leave a row without its organisation or with a stale one.

The functions read and write as "system" inside the function only (the caller's value back before they return, like
kalmido_ml_prune): the parent may be outside the writer's row-level scope, and then the row must still get the parent's true
organisation -- the policy's WITH CHECK of the writing statement (evaluated after this, with the caller's context) then refuses a
row of an organisation the writer is not in, instead of the row coming in as "private". The children of a moved parent move with
it whatever the writer's scope (the parent's own change was allowed).

An organisation removed for good (DELETE FROM orgs): the foreign keys of the parents and of these columns both set NULL; whichever
runs first, the BEFORE trigger gives NULL for an organisation that no longer exists (else it would write the deleted id back and
the foreign key would fail).
"""
from .db import trigger_skip_present

ORW_CHILDREN = {"tasks": "list_id", "comments": "task_id", "events": "cal_id", "contacts": "book_id"}

ORW_TRIGGERS = """CREATE OR REPLACE FUNCTION kalmido_orw_fill() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE prev text := current_setting('app.role', true); o bigint;
BEGIN
  PERFORM set_config('app.role', 'system', true);
  IF TG_TABLE_NAME = 'tasks' THEN
    SELECT l.org_id INTO o FROM lists l WHERE l.id = NEW.list_id;
  ELSIF TG_TABLE_NAME = 'comments' THEN
    SELECT l.org_id INTO o FROM tasks t JOIN lists l ON l.id = t.list_id WHERE t.id = NEW.task_id;
  ELSIF TG_TABLE_NAME = 'events' THEN
    SELECT k.org_id INTO o FROM ev_cals k WHERE k.id = NEW.cal_id;
  ELSE
    SELECT b.org_id INTO o FROM books b WHERE b.id = NEW.book_id;
  END IF;
  IF o IS NOT NULL AND NOT EXISTS (SELECT 1 FROM orgs WHERE id = o) THEN
    o := NULL;  -- the organisation is being removed for good: the parent becomes private by its own foreign key
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  NEW.org_id := o;
  RETURN NEW;
END $fn$;
CREATE OR REPLACE FUNCTION kalmido_orw_carry() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  IF TG_TABLE_NAME = 'lists' THEN
    UPDATE tasks SET org_id = NEW.org_id WHERE list_id = NEW.id AND org_id IS DISTINCT FROM NEW.org_id;
  ELSIF TG_TABLE_NAME = 'tasks' THEN
    UPDATE comments SET org_id = NEW.org_id WHERE task_id = NEW.id AND org_id IS DISTINCT FROM NEW.org_id;
  ELSIF TG_TABLE_NAME = 'ev_cals' THEN
    UPDATE events SET org_id = NEW.org_id WHERE cal_id = NEW.id AND org_id IS DISTINCT FROM NEW.org_id;
  ELSE
    UPDATE contacts SET org_id = NEW.org_id WHERE book_id = NEW.id AND org_id IS DISTINCT FROM NEW.org_id;
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $fn$;
CREATE OR REPLACE TRIGGER kalmido_orw_tasks BEFORE INSERT OR UPDATE OF list_id, org_id ON tasks FOR EACH ROW EXECUTE FUNCTION kalmido_orw_fill();
CREATE OR REPLACE TRIGGER kalmido_orw_comments BEFORE INSERT OR UPDATE OF task_id, org_id ON comments FOR EACH ROW EXECUTE FUNCTION kalmido_orw_fill();
CREATE OR REPLACE TRIGGER kalmido_orw_events BEFORE INSERT OR UPDATE OF cal_id, org_id ON events FOR EACH ROW EXECUTE FUNCTION kalmido_orw_fill();
CREATE OR REPLACE TRIGGER kalmido_orw_contacts BEFORE INSERT OR UPDATE OF book_id, org_id ON contacts FOR EACH ROW EXECUTE FUNCTION kalmido_orw_fill();
CREATE OR REPLACE TRIGGER kalmido_orw_carry_lists AFTER UPDATE OF org_id ON lists FOR EACH ROW
  WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_orw_carry();
CREATE OR REPLACE TRIGGER kalmido_orw_carry_tasks AFTER UPDATE OF list_id, org_id ON tasks FOR EACH ROW
  WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_orw_carry();
CREATE OR REPLACE TRIGGER kalmido_orw_carry_cals AFTER UPDATE OF org_id ON ev_cals FOR EACH ROW
  WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_orw_carry();
CREATE OR REPLACE TRIGGER kalmido_orw_carry_books AFTER UPDATE OF org_id ON books FOR EACH ROW
  WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_orw_carry();"""
# (the AFTER trigger on tasks lists list_id too: a move sets org_id in the BEFORE trigger only, and an UPDATE OF column trigger
# fires only for the columns the statement itself names)

# the rows from before: each child gets its parent's organisation (comments straight from the list of their task)
ORW_BACKFILL = (
    "UPDATE tasks t SET org_id=l.org_id FROM lists l WHERE l.id=t.list_id AND t.org_id IS DISTINCT FROM l.org_id",
    "UPDATE comments m SET org_id=l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id "
    "WHERE t.id=m.task_id AND m.org_id IS DISTINCT FROM l.org_id",
    "UPDATE events e SET org_id=k.org_id FROM ev_cals k WHERE k.id=e.cal_id AND e.org_id IS DISTINCT FROM k.org_id",
    "UPDATE contacts p SET org_id=b.org_id FROM books b WHERE b.id=p.book_id AND p.org_id IS DISTINCT FROM b.org_id",
)
ORW_FILL_NAMES = tuple(f"kalmido_orw_{t}" for t in ORW_CHILDREN)


def orw_present(c):
    """The names of the fill triggers in place (of ORW_FILL_NAMES)."""
    return {r[0] for r in c.execute(
        "SELECT t.tgname FROM pg_trigger t JOIN pg_class k ON k.oid=t.tgrelid "  # pg-ok: pg_catalog oid
        "WHERE k.relnamespace=current_schema()::regnamespace AND NOT t.tgisinternal AND t.tgname = ANY(string_to_array(?, ','))",
        (",".join(ORW_FILL_NAMES),)).fetchall()}


def orw_backfill(c):
    """The rows written while the fill triggers were missing (the first start with the column, a way back that dropped
    them) get their parent's organisation. Returns {table: rows changed}."""
    return {s.split()[1]: c.execute(s).rowcount for s in ORW_BACKFILL}


def orw_setup(c):
    """init_db (every start, after the migrations: the four columns exist; inside the start's transaction as "system"): the
    rows from before when a fill trigger was missing, then the functions + triggers (only the missing / changed ones)."""
    if len(orw_present(c)) < len(ORW_FILL_NAMES):
        n = orw_backfill(c)
        if any(n.values()):
            print("organisation of tasks / comments / events / contacts filled: "
                  + ", ".join(f"{k} {v}" for k, v in n.items()), flush=True)
    c.executescript(trigger_skip_present(c, ORW_TRIGGERS))
