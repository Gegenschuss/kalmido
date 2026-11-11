"""2.955.0 (#5276, stage Q5b of the cross-cutting core, analysis #3563, decided 08.11.2026): the personal tags are rows of the
shared core -- obj_tags scope user (scope_id = the person's id) and obj_tag_links (kind task) replace task_tags. A person's names
equal under lower() are one tag (question 8: Kunde / kunde merged); an agent keeps its own tags (question 12: the scope of the
agent's account); names stay plain text on tasks of end-to-end locked projects (question 10).

The move: core/db.py init_db calls core/objtags.py otg_move_user before AFTER runs (the rows of task_tags into the core), then
the table is dropped. One-way: a version before 2.955 makes task_tags again, empty (its schema.py), and shows no personal tags
until this version is back (its next start moves what was written meanwhile); a backup restores the old state.

An account deleted for good takes its personal tags along (kalmido_otg_gone on users, the trigger function of 5275_a); the
links of a tag go with it (obj_tag_links.tag_id ON DELETE CASCADE)."""
SCHEMA = """
CREATE OR REPLACE TRIGGER kalmido_otg_gone_user AFTER DELETE ON users FOR EACH ROW EXECUTE FUNCTION kalmido_otg_gone('scope', 'user');
"""
# drop-ok task_tags: moved into obj_tags (scope user) / obj_tag_links by core/objtags.py otg_move_user just before (stage Q5b, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS task_tags",
]
