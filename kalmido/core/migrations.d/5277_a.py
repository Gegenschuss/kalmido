"""2.1119.0 (#5277, stage Q5c of the cross-cutting core, analysis #3563, decided 08.11.2026): the tags of the file store
("Ablage": files, folders, documents) are rows of the shared core -- obj_tags scope ws (scope_id = the workspace key 'o<org>' |
'u<owner>', org_id set for an organisation's workspace: row-level security as doc_tags had it) and obj_tag_links (kind
fs_entry) replace doc_tags / doc_node_tags. A name is unique per workspace under lower() (the index of 5275_a, was a Python
compare with a race); names equal so are merged at the move. The old doc_node_tags.auto ('' by hand, 'rule', 'learn',
'agent', ...) is the link's new column how; src is 'auto' for the recognition's marks (decided: auto becomes src=auto).

The move: core/db.py init_db runs docs/dtags.py dtg_move (core/objhooks.MOVE) before AFTER: core/objtags.py otg_move_ws moves
the rows (a tag keeps its id where it is free in obj_tags; one that is not gets a new id, and the places that keep a tag's id
-- the models, the suggestions, the saved views, the undo of runs -- are rewritten), then the two tables are dropped. One-way:
a version before 2.1119 makes doc_tags / doc_node_tags again, empty (its schema.py), and shows no tags in the file store until
this version is back (its next start moves what was written meanwhile); a backup restores the old state.

A node deleted for good takes its links along (kalmido_otg_gone on fs_nodes, the trigger function of 5275_a, as the old
ON DELETE CASCADE); an organisation its workspace's tags (obj_tags.org_id ON DELETE CASCADE)."""
MIGRATIONS = [
    # the detail of a link's src (the file store's old doc_node_tags.auto); '' for the other kinds -- older versions ignore it
    ("obj_tag_links", "how", "ALTER TABLE obj_tag_links ADD COLUMN IF NOT EXISTS how TEXT NOT NULL DEFAULT ''"),
]
SCHEMA = """
CREATE OR REPLACE TRIGGER kalmido_otg_gone_fs AFTER DELETE ON fs_nodes FOR EACH ROW EXECUTE FUNCTION kalmido_otg_gone('link', 'fs_entry');
"""
# drop-ok doc_node_tags: moved into obj_tag_links (kind fs_entry) by docs/dtags.py dtg_move just before (stage Q5c, decided 08.11.2026)
# drop-ok doc_tags: moved into obj_tags (scope ws) by docs/dtags.py dtg_move just before (stage Q5c, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS doc_node_tags",
    "DROP TABLE IF EXISTS doc_tags",
]
