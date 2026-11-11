"""2.905.0 (#5284, stage Q8a of the cross-cutting core, analysis #3563, decided 08.11.2026): one table obj_seen holds the read
marks of the core (core/objseen.py); task_seen (the highest comment id a person has seen in a task) goes. seen_at is a real point
in time (TIMESTAMPTZ, #5305: a new core table only with real types).

The object has no foreign key (kind names its table); instead kalmido_osn_gone deletes a task's marks when the task row is
deleted for good -- what ON DELETE CASCADE did on task_seen. user_id has a real key (the account goes, its marks go).

The move: core/db.py init_db calls core/objseen.py osn_move before the change triggers are set up and before AFTER runs -- the
rows of task_seen go into obj_seen (kind 'task'; the first start of 2.905, or the rows a version before 2.905 wrote after a
rollback, the higher mark wins), then task_seen is dropped. One-way: a version before 2.905 makes task_seen again, empty (its
schema.py), and shows every comment of others as unread until this version is back (its next start moves what was written
meanwhile); a backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_seen (  -- 2.905.0 (#5284): the read mark of one person on one object of the core
  kind TEXT NOT NULL,
  ref_id BIGINT NOT NULL, -- no FK: a row of the kind's table (task -> tasks); kalmido_osn_gone deletes with it
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  seen_id BIGINT NOT NULL DEFAULT 0, -- no FK: a high-water mark (task: the highest comment id seen), the row may be gone
  seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, -- no now(): a restore refuses a call in a default (admin/backup.py _calls_ok)
  PRIMARY KEY (kind, ref_id, user_id));
CREATE INDEX IF NOT EXISTS ix5284_obj_seen_user ON obj_seen(user_id);
CREATE OR REPLACE FUNCTION kalmido_osn_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM obj_seen WHERE kind = TG_ARGV[0] AND ref_id = OLD.id;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_osn_gone_task AFTER DELETE ON tasks FOR EACH ROW EXECUTE FUNCTION kalmido_osn_gone('task');
"""
# drop-ok task_seen: moved into obj_seen by core/objseen.py osn_move just before (stage Q8a, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS task_seen",
]
