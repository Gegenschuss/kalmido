"""2.981.0 (#5273, stage Q4b of the cross-cutting core, analysis #3563, decided 08.11.2026): the comments of video / picture
reviews and the notes on documents are rows of the comments' core (obj_comments, migrations.d/5272_a.py) -- kind 'video'
(ref_id = the review, video_reviews) and kind 'doc_note' (ref_id = the document's node, fs_nodes). They get the core's trash
with its period (files/trashpurge.py, obj_comment_trash keeps the text), the edit with version and lock (core/objcomments.py
ocm_edit) and the one delete rule (the author or 'manage' on the object).

Two new columns of obj_comments (real types, #5305): anchor JSONB = where a comment sits on its object (a review: {version_id,
t} | {version_id, x, y} | {version_id, page, x?, y?}; NULL = nowhere), state TEXT = its state (a review: 'done' or NULL = open).

ref_id has no foreign key: the triggers kalmido_ocm_video_gone / kalmido_ocm_doc_gone delete the comments of a review / a
node when it is deleted for good (what ON DELETE CASCADE did on video_comments / doc_notes); the reactions go with them
(kalmido_orx_gone of 5272_a). org_id is what the area brings (the review's / the node's organisation, core/orgrows.py keeps it).

The move: core/db.py init_db calls core/objcomments.py ocm_move_q4b (core/objhooks.py MOVE) before AFTER runs -- the rows of
video_comments and doc_notes go into obj_comments with NEW ids (the ids of obj_comments are the task comments' already; nothing
outside the two tables pointed at them), an answer keeps its comment (parent_id mapped), a comment / note in the trash keeps its
text in obj_comment_trash; then the two tables are dropped. The notes' texts stay sealed as they are (docs/store.py doc_seal,
context "doc_notes.text"). One-way: an older version would make the tables again, empty; a backup restores the old state.
"""
MIGRATIONS = [
    ("obj_comments", "anchor", "ALTER TABLE obj_comments ADD COLUMN anchor JSONB"),
    ("obj_comments", "state", "ALTER TABLE obj_comments ADD COLUMN state TEXT"),
]
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_ocm_video_gone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  DELETE FROM obj_comments WHERE kind = 'video' AND ref_id = OLD.id;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_ocm_video_gone AFTER DELETE ON video_reviews FOR EACH ROW EXECUTE FUNCTION kalmido_ocm_video_gone();
CREATE OR REPLACE FUNCTION kalmido_ocm_doc_gone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  DELETE FROM obj_comments WHERE kind = 'doc_note' AND ref_id = OLD.id;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_ocm_doc_gone AFTER DELETE ON fs_nodes FOR EACH ROW EXECUTE FUNCTION kalmido_ocm_doc_gone();
"""
# drop-ok video_comments: moved into obj_comments (kind video) by core/objcomments.py ocm_move_q4b just before (stage Q4b, decided 08.11.2026)
# drop-ok doc_notes: moved into obj_comments (kind doc_note) by core/objcomments.py ocm_move_q4b just before (stage Q4b, decided 08.11.2026)
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5273_obj_comments_anchor_version ON obj_comments(((anchor->>'version_id')::bigint)) WHERE kind = 'video'",
    "DROP TABLE IF EXISTS video_comments",
    "DROP TABLE IF EXISTS doc_notes",
]
