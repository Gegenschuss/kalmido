"""2.972.0 (#5285, stage Q9a of the cross-cutting core, analysis #3563, decided 08.11.2026): one table obj_follow holds who
follows an object and how loud (core/objfollow.py); task_watchers and task_bell go.

One row per person, kind, object and mode family: mode 'watch' = the person watches the object (the old task_watchers), a
mode of the bell ('list' | 'mute' | 'urgent', the old task_bell levels; 'list' = as the project, kept for its one undo step) is
the person's bell of the object. Both can be there at once (a watched task that is muted): the primary key holds the mode, the
partial unique index ofl_bell_one allows one bell row per person and object. until = the last day of an urgency (DATE, local
day, inclusive; NULL = until the task is completed), set_by = who set it, prev / act / act_by = the bell's last change (one
undo step). Times are real points in time (TIMESTAMPTZ, #5305), the defaults CURRENT_TIMESTAMP (a restore refuses now()).

ref_id has no foreign key (kind names its table); kalmido_ofl_gone deletes an object's rows when the task is deleted for good
(what ON DELETE CASCADE did). org_id: a watching row always carries its task's organisation (kalmido_ofl_fill on insert,
kalmido_ofl_carry when the task changes workspace; that trigger comes from core/objfollow.py ofl_setup after the migrations:
tasks.org_id is a step of the fragment 4602_a, a new database has it only then); a bell row keeps the organisation it was set in (the app writes it, a
list's workspace move takes it along: accounts/orgs.py) -- a bell of another workspace is ignored, as before. The functions
read and write as "system" inside the function only (core/orgrows.py).

The move: core/db.py init_db calls core/objfollow.py ofl_move before AFTER runs -- the rows of the old tables go into
obj_follow (the first start of 2.972, or the rows a version before 2.972 wrote after a rollback), then both tables are dropped.
One-way: a version before 2.972 makes the old tables again, empty (its schema.py), and shows no watchers and bells until this
version is back (its next start moves what was written meanwhile); a backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_follow (  -- 2.972.0 (#5285): who follows an object of the core and how loud
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  ref_id BIGINT NOT NULL, -- no FK: a row of the kind's table (task -> tasks); kalmido_ofl_gone deletes with it
  org_id BIGINT REFERENCES orgs(id) ON DELETE SET NULL,
  mode TEXT NOT NULL CHECK (mode IN ('watch', 'list', 'mute', 'urgent')),
  until DATE,
  set_by BIGINT,
  prev JSONB,
  act TEXT,
  act_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, -- no now(): a restore refuses a call in a default (admin/backup.py _calls_ok)
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, kind, ref_id, mode));
CREATE UNIQUE INDEX IF NOT EXISTS ofl_bell_one ON obj_follow(user_id, kind, ref_id) WHERE mode <> 'watch';
CREATE INDEX IF NOT EXISTS ix5285_obj_follow_ref ON obj_follow(kind, ref_id);
CREATE INDEX IF NOT EXISTS ix5285_obj_follow_org ON obj_follow(org_id) WHERE org_id IS NOT NULL;
CREATE OR REPLACE FUNCTION kalmido_ofl_fill() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true); o bigint;
BEGIN
  PERFORM set_config('app.role', 'system', true);
  SELECT l.org_id INTO o FROM tasks t JOIN lists l ON l.id = t.list_id WHERE t.id = NEW.ref_id;
  IF o IS NOT NULL AND NOT EXISTS (SELECT 1 FROM orgs WHERE id = o) THEN
    o := NULL;
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  NEW.org_id := o;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION kalmido_ofl_carry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  UPDATE obj_follow SET org_id = NEW.org_id WHERE kind = 'task' AND ref_id = NEW.id AND mode = 'watch' AND org_id IS DISTINCT FROM NEW.org_id;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION kalmido_ofl_gone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  DELETE FROM obj_follow WHERE kind = TG_ARGV[0] AND ref_id = OLD.id;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION kalmido_ofl_dl() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- the delta state (tasks/delta.py): a task's watchers are part of the task as the app serves it
  IF TG_OP <> 'INSERT' AND OLD.kind = 'task' AND OLD.mode = 'watch' THEN INSERT INTO dl_changes(task_id) VALUES (OLD.ref_id); END IF;
  IF TG_OP <> 'DELETE' AND NEW.kind = 'task' AND NEW.mode = 'watch' AND (TG_OP = 'INSERT' OR NEW.ref_id IS DISTINCT FROM OLD.ref_id) THEN
    INSERT INTO dl_changes(task_id) VALUES (NEW.ref_id);
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_ofl_fill BEFORE INSERT OR UPDATE OF ref_id ON obj_follow FOR EACH ROW
  WHEN (NEW.kind = 'task'::text AND NEW.mode = 'watch'::text) EXECUTE FUNCTION kalmido_ofl_fill();
CREATE OR REPLACE TRIGGER kalmido_ofl_gone_task AFTER DELETE ON tasks FOR EACH ROW EXECUTE FUNCTION kalmido_ofl_gone('task');
CREATE OR REPLACE TRIGGER kalmido_ofl_dl AFTER INSERT OR UPDATE OR DELETE ON obj_follow FOR EACH ROW EXECUTE FUNCTION kalmido_ofl_dl();
"""
# drop-ok task_watchers: moved into obj_follow (mode watch) by core/objfollow.py ofl_move just before (stage Q9a, decided 08.11.2026)
# drop-ok task_bell: moved into obj_follow (the bell's modes) by core/objfollow.py ofl_move just before (stage Q9a, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS task_watchers",
    "DROP TABLE IF EXISTS task_bell",
]
