"""2.537.0 C (#3433): tasks made from a quotation ("Create tasks" on the quotation, office/offertasks.py).
office_doc_items.origin_id / office_doc_parts.origin_id = the position / part of the chain's first quotation a copy descends from
(set by duplicating a quotation, NULL = the row is its own origin): a new version finds its tasks again by the same key.
task_offer_links = where a task came from: the list, the quotation it was last brought up to date from (doc_id), its chain
(root_id = version_of or the id), the key of the position (i:<origin item> | s:<origin part>:<crew row uid>), the budget the
quotation gave (auto_h) and the one written into the field "Budget h" (set_h; a different value in the field = changed by
hand, kept), gone = no longer in the quotation (only marked, the task stays). New columns / tables only: older versions ignore them.
2.552.0 (#4647): doc_id has its key (a deleted quotation empties it); a database made by 2.537-2.551 gets it from core/fkeys.py."""
MIGRATIONS = [
    ("office_doc_items", "origin_id", "ALTER TABLE office_doc_items ADD COLUMN IF NOT EXISTS origin_id BIGINT"),
    ("office_doc_parts", "origin_id", "ALTER TABLE office_doc_parts ADD COLUMN IF NOT EXISTS origin_id BIGINT"),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS task_offer_links (
  task_id BIGINT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  doc_id BIGINT REFERENCES office_docs(id) ON DELETE SET NULL,
  root_id BIGINT, -- no FK (2.552.0 #4647): the chain's id, its first version can be deleted
  item_key TEXT NOT NULL DEFAULT '', auto_h DOUBLE PRECISION, set_h DOUBLE PRECISION,
  gone BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS task_offer_links_list ON task_offer_links(list_id, root_id);
"""
