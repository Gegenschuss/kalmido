"""2.763.0 (#5269, stage Q1 of the cross-cutting core, analysis #3563, decided 08.11.2026): one table obj_reactions holds the
reactions of comments, team chat messages and the chat with an agent (core/objreact.py); comment_reactions, tchat_rx and
chat_reactions go. created_at is a real point in time (TIMESTAMPTZ, #5305: a new core table only with real types).

The target has no foreign key (target_kind names its table); instead kalmido_orx_gone deletes a target's reactions when its row
is deleted for good -- what ON DELETE CASCADE did on the old tables (the trash run, a deleted agent chat message, a purged
task's comments, an import undone). A row only moved into the trash keeps them (a restore brings them back).

The move: core/db.py init_db calls core/objreact.py orx_move before AFTER runs -- the rows of the old tables go into
obj_reactions (whatever is there: the first start of 2.763, or the rows a version before 2.763 wrote after a rollback), then the
three tables are dropped. One-way: a version before 2.763 makes the old tables again, empty (its schema.py), and shows no
reactions until this version is back (its next start moves what was written meanwhile); a backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_reactions (  -- 2.763.0 (#5269): one reaction per person, emoji and target of the core
  target_kind TEXT NOT NULL,
  target_id BIGINT NOT NULL, -- no FK: a row of the kind's table (comment -> comments, tchat -> tchat_msgs, agent_chat -> agent_chat); kalmido_orx_gone deletes with it
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (target_kind, target_id, user_id, emoji));
CREATE INDEX IF NOT EXISTS ix5269_obj_reactions_user ON obj_reactions(user_id);
CREATE OR REPLACE FUNCTION kalmido_orx_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM obj_reactions WHERE target_kind = TG_ARGV[0] AND target_id = OLD.id;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_orx_gone_comment AFTER DELETE ON comments FOR EACH ROW EXECUTE FUNCTION kalmido_orx_gone('comment');
CREATE OR REPLACE TRIGGER kalmido_orx_gone_tchat AFTER DELETE ON tchat_msgs FOR EACH ROW EXECUTE FUNCTION kalmido_orx_gone('tchat');
CREATE OR REPLACE TRIGGER kalmido_orx_gone_agent_chat AFTER DELETE ON agent_chat FOR EACH ROW EXECUTE FUNCTION kalmido_orx_gone('agent_chat');
"""
# drop-ok comment_reactions: moved into obj_reactions by core/objreact.py orx_move just before (stage Q1, decided 08.11.2026)
# drop-ok tchat_rx: moved into obj_reactions by core/objreact.py orx_move just before (stage Q1, decided 08.11.2026)
# drop-ok chat_reactions: moved into obj_reactions by core/objreact.py orx_move just before (stage Q1, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS comment_reactions",
    "DROP TABLE IF EXISTS tchat_rx",
    "DROP TABLE IF EXISTS chat_reactions",
]
