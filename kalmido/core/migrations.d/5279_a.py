"""2.1002.0 (#5279, stage Q6b of the cross-cutting core, analysis #3563, decided 08.11.2026): one keyed word index for the
sealed texts, obj_search_words (core/objwords.py). One row per (kind, ref_id, h): kind doc (a document's fs_nodes id),
file_text (the recognised text of a file), wiki_page, hub_mail (a filed mail); h = an HMAC-SHA256 prefix hash of a folded
word, keyed per workspace (docs/store.py _index_key), or a mark of the area. No plain word is stored. Real types only.

Derived data: written by the areas (docs/store.py doc_index, files/textscan.py, wiki/wksearch.py wks_index, hub/hubmail.py),
taken along by the delete triggers kalmido_osw_gone on the source tables (core/objwords.py osw_init, no foreign key: kind names
its table), indexed again by the watchdog (osw_tick) for objects without the mark of this version. No export, no import
(rebuilt from the imported rows). No org_id on purpose: every reader hands in the ids it may read (rights stay in the area).

What goes (one-way): the four word indexes of their own -- doc_words (2.48.0), file_words (2.61.0), hub_words (2.84.0) and
wiki_words (2.123.0). Before the drop core/db.py init_db runs core/objwords.py osw_move (core/objhooks.py MOVE, before every
fragment's AFTER): their hashes are copied into obj_search_words (same keys, same hashes: the search finds what it found
before at once) and the back limit is raised to the minor of the image that moves (an older version would make the old tables
again empty and search nothing). A backup restores the old state.
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS obj_search_words (  -- 2.1002.0 (#5279): the shared keyed word index of the sealed texts (core/objwords.py)
  kind TEXT NOT NULL,
  ref_id BIGINT NOT NULL, -- no FK: a row of the kind's table (doc -> fs_nodes, file_text, wiki_page -> wiki_pages, hub_mail -> hub_mails)
  h TEXT NOT NULL,
  PRIMARY KEY (kind, ref_id, h));
CREATE INDEX IF NOT EXISTS ix5279_osw_h ON obj_search_words(kind, h);
"""
# drop-ok doc_words: replaced by obj_search_words kind 'doc', its hashes copied before (core/objwords.py osw_move, stage Q6b, decided 08.11.2026)
# drop-ok file_words: replaced by obj_search_words kind 'file_text', its hashes copied before (osw_move, stage Q6b, decided 08.11.2026)
# drop-ok wiki_words: replaced by obj_search_words kind 'wiki_page', its hashes copied before (osw_move, stage Q6b, decided 08.11.2026)
# drop-ok hub_words: replaced by obj_search_words kind 'hub_mail', its hashes copied before (osw_move, stage Q6b, decided 08.11.2026)
AFTER = [
    "DROP TABLE IF EXISTS doc_words",
    "DROP TABLE IF EXISTS file_words",
    "DROP TABLE IF EXISTS wiki_words",
    "DROP TABLE IF EXISTS hub_words",
]
