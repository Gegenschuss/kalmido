"""2.981.0 (#5278, stage Q6a of the cross-cutting core, analysis #3563, decided 08.11.2026): one search index, obj_search
(core/objsearch.py). One row per object of the open texts (tasks, comments of every kind, notes, contacts, the names of
knowledge pages, team chat and agent chat messages): kind, ref_id, the organisation / owner / container, the commented object
(pkind, pid), title, names (folded names and numbers, part-of-a-word match) and tsv (the 'simple' configuration over
kalmido_fold, GIN). Real types only (#5305): updated_at TIMESTAMPTZ (default CURRENT_TIMESTAMP, never now()).

Derived data: the triggers kalmido_osr_<kind> on the source tables keep it (core/objsearch.py osr_init, every start; they also
fill the rows written while they were missing). No foreign keys (kind names its table; the delete trigger takes the row along),
no export, no import. Rights are not in the index: every reader joins the source row (under its row-level security) and
checks the area's rights; the index itself has no org_id column on purpose (org_ref, see below).

What goes (one-way): the side tables task_fts / cmt_fts of the task search (2.281.0, #3113) and the column contacts.search
(contacts/model.py search_text) -- the index replaces both. Before the drop core/db.py init_db runs core/objsearch.py osr_move
(core/objhooks.py MOVE): the triggers that wrote into the side tables, their functions and the trigram indexes (msg_trgm_* on
the message tables, tasks_trgm_* on tasks) go, and the back limit is raised to the minor of the image that moves (an older
version would write contacts into the dropped column). A backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_search (  -- 2.981.0 (#5278): the shared search index (core/objsearch.py), derived from the source tables
  kind TEXT NOT NULL,
  ref_id BIGINT NOT NULL, -- no FK: a row of the kind's table (task -> tasks ...); the delete trigger takes the index row along
  org_ref BIGINT, -- the source's organisation (NULL = private, or messages: the area decides). Not named org_id on purpose: row-level
                  -- security (core/rls.py takes every org_id) would stop the GIN index (@@ is not leakproof, as ILIKE in #5116) -
                  -- every reader joins the source row, which stands under its policy, and checks the area's rights
  owner_id BIGINT,
  node_id BIGINT, -- the container: a task's / note's project, a contact's address book, a message's room, an agent chat's agent
  pkind TEXT, -- a comment: the kind of its object
  pid BIGINT, -- a comment: its object
  title TEXT NOT NULL DEFAULT '',
  names TEXT NOT NULL DEFAULT '', -- folded names and numbers: a query word may stand anywhere in them (question 14)
  tsv tsvector NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (kind, ref_id));
CREATE INDEX IF NOT EXISTS ix5278_obj_search_tsv ON obj_search USING gin (tsv);
CREATE INDEX IF NOT EXISTS ix5278_obj_search_node ON obj_search(kind, node_id) WHERE node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix5278_obj_search_parent ON obj_search(pkind, pid) WHERE pkind IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix5278_obj_search_org ON obj_search(org_ref) WHERE org_ref IS NOT NULL;
"""
# drop-ok task_fts: replaced by obj_search, rebuilt from the tasks at the start (core/objsearch.py, stage Q6a, decided 08.11.2026)
# drop-ok cmt_fts: replaced by obj_search, rebuilt from obj_comments at the start (core/objsearch.py, stage Q6a, decided 08.11.2026)
# drop-ok contacts.search: replaced by obj_search kind 'contact', rebuilt from the contacts at the start (stage Q6a, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS task_fts",
    "DROP TABLE IF EXISTS cmt_fts",
    "ALTER TABLE contacts DROP COLUMN IF EXISTS search",
]
