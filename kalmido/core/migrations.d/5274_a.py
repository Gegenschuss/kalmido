"""2.981.0 (#5274, stage Q4c of the cross-cutting core, analysis #3563, decided 08.11.2026): the team chat keeps its message
stream (tchat_msgs) but its trash is the comments' core: the kept text of a deleted message waits in obj_comment_trash
(migrations.d/5272_a.py) under kind 'tchat' -- tchat_trash_text goes.

obj_comment_trash gets the column kind ('comment' = a row of obj_comments, the default: every row so far; 'tchat' = a row of
tchat_msgs) and the key (kind, comment_id): a message and a comment may share an id, every query names the kind. The foreign
key on obj_comments goes (core/objcomments.py ocm_trash_key, at the start: a key cannot be changed by a fragment); the triggers
kalmido_oct_gone_* delete a kept text with its row, per kind -- what ON DELETE CASCADE did on both tables.

The move: core/db.py init_db calls core/objcomments.py ocm_move_q4c (core/objhooks.py MOVE) before AFTER runs -- the key is
changed, the rows of tchat_trash_text go into obj_comment_trash (kind 'tchat', the message's id); then the old table is dropped.
One-way: an older version would make tchat_trash_text again, empty, and could not write its comments' trash with the new key;
the back limit is raised to this minor (core/kernretire.py), a backup restores the old state.
"""
MIGRATIONS = [
    ("obj_comment_trash", "kind", "ALTER TABLE obj_comment_trash ADD COLUMN kind TEXT NOT NULL DEFAULT 'comment'"),
]
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_oct_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM obj_comment_trash WHERE kind = TG_ARGV[0] AND comment_id = OLD.id;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_oct_gone_comment AFTER DELETE ON obj_comments FOR EACH ROW EXECUTE FUNCTION kalmido_oct_gone('comment');
CREATE OR REPLACE TRIGGER kalmido_oct_gone_tchat AFTER DELETE ON tchat_msgs FOR EACH ROW EXECUTE FUNCTION kalmido_oct_gone('tchat');
"""
# drop-ok tchat_trash_text: moved into obj_comment_trash (kind tchat) by core/objcomments.py ocm_move_q4c just before (stage Q4c, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS tchat_trash_text",
]
