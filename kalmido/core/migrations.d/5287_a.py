"""2.981.0 (#5287, stage Q9b of the cross-cutting core, analysis #3563, decided 08.11.2026): the bell of a project is a row of
obj_follow (kind 'list', core/objfollow.py), the owner's notification templates of projects and folders are rows of one table
obj_notif_cap (core/objnotifcap.py); list_bell, list_notif and folder_notif go.

obj_follow gets the column custom (JSONB: a project bell's own choice per event, kept while another mode is set); its CHECK of
mode takes the project bell's modes (default | all | mute | custom) -- core/objfollow.py ofl_modes replaces it at the start (a
constraint is no step a fragment may change). The trigger kalmido_ofl_gone_list: a project deleted for good takes its bells
(what ON DELETE CASCADE of list_bell did).

obj_notif_cap: one row per kind ('list' = a project, ref_id = lists.id, path ''; 'folder' = a folder of the owner, ref_id = the
owner's account, path = the folder's path), person (user_id 0 = everyone) and the template (tpl read | work | all | custom,
custom = JSONB {event: 0|1}). Times are real points in time (TIMESTAMPTZ, #5305), the default CURRENT_TIMESTAMP (a restore
refuses now()). ref_id and user_id have no foreign key (kind names the table; 0 is no account): kalmido_ncap_gone deletes a
project's rows when it is deleted for good, an account's folder rows and the rows naming it as the person when it goes.
No org_id: a ceiling belongs to its project / owner like before (no row-level security of its own, the app checks the owner).

The move: core/db.py init_db runs core/objhooks.MOVE (core/objnotifcap.py ncap_move) and core/objfollow.py ofl_setup (ofl_move:
list_bell) before AFTER -- the old rows go into the core (the first start of 2.981, or the rows an older version wrote after a
rollback), then the old tables are dropped. One-way: an older version makes the tables again, empty (its schema.py), and shows no
project bells and no templates (every share falls back to the default "read") until this version is back (its next start moves
what was written meanwhile); a backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_notif_cap (  -- 2.981.0 (#5287): the owner's ceiling of the notifications of a project / folder
  kind TEXT NOT NULL CHECK (kind IN ('list', 'folder')),
  ref_id BIGINT NOT NULL, -- no FK: a project (lists.id) or the folder owner's account (users.id); kalmido_ncap_gone deletes with it
  path TEXT NOT NULL DEFAULT '',
  user_id BIGINT NOT NULL DEFAULT 0, -- no FK: 0 = everyone of the project / folder; kalmido_ncap_gone deletes a person's rows
  tpl TEXT NOT NULL CHECK (tpl IN ('read', 'work', 'all', 'custom')),
  custom JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, -- no now(): a restore refuses a call in a default (admin/backup.py _calls_ok)
  PRIMARY KEY (kind, ref_id, path, user_id));
CREATE INDEX IF NOT EXISTS ix5287_obj_notif_cap_user ON obj_notif_cap(user_id) WHERE user_id <> 0;
CREATE OR REPLACE FUNCTION kalmido_ncap_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_ARGV[0] = 'list' THEN
    DELETE FROM obj_notif_cap WHERE kind = 'list' AND ref_id = OLD.id;
  ELSE
    DELETE FROM obj_notif_cap WHERE (kind = 'folder' AND ref_id = OLD.id) OR user_id = OLD.id;
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_ncap_gone_list AFTER DELETE ON lists FOR EACH ROW EXECUTE FUNCTION kalmido_ncap_gone('list');
CREATE OR REPLACE TRIGGER kalmido_ncap_gone_user AFTER DELETE ON users FOR EACH ROW EXECUTE FUNCTION kalmido_ncap_gone('user');
CREATE OR REPLACE TRIGGER kalmido_ofl_gone_list AFTER DELETE ON lists FOR EACH ROW EXECUTE FUNCTION kalmido_ofl_gone('list');
"""
MIGRATIONS = [
    ("obj_follow", "custom", "ALTER TABLE obj_follow ADD COLUMN IF NOT EXISTS custom JSONB"),
]
# drop-ok list_bell: moved into obj_follow (kind list) by core/objfollow.py ofl_move just before (stage Q9b, decided 08.11.2026)
# drop-ok list_notif: moved into obj_notif_cap (kind list) by core/objnotifcap.py ncap_move just before (stage Q9b, decided 08.11.2026)
# drop-ok folder_notif: moved into obj_notif_cap (kind folder) by core/objnotifcap.py ncap_move just before (stage Q9b, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS list_bell",
    "DROP TABLE IF EXISTS list_notif",
    "DROP TABLE IF EXISTS folder_notif",
]
