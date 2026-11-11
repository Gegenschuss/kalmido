"""2.981.0 (#5286, stage Q8b of the cross-cutting core, analysis #3563, decided 08.11.2026): the read marks of the feeds' articles
are rows of the core's obj_seen (core/objseen.py, kind 'rss'); rss_reads and rss_items.read_at go.

RSS had two models for the same thing: rss_items.read_at (one mark on the article, for a private feed) and rss_reads (one row
per person and article, for the feeds of an organisation). Now one model in every space: a read article is a row of obj_seen
(kind 'rss', ref_id = the article, seen_id = its id, seen_at = when it was read); marking it unread again deletes the row. Per
article, not a high-water mark per feed: an article can be marked unread on its own and articles arrive out of order. The
trigger kalmido_osn_gone_rss: an article deleted (trimmed, its feed deleted) takes its marks along.

The move: core/db.py init_db calls core/objseen.py osn_move (osn_move_rss) before AFTER -- the rows of rss_reads and the marks of
rss_items.read_at (the feed's owner) go into obj_seen (the first start of 2.981, or what an older version wrote after a rollback),
then the table and the column are dropped. One-way: an older version makes rss_reads again, empty, but finds no column read_at
and fails on the feeds (its start check refuses: the back limit is raised to this release); a backup restores the old state.
"""
SCHEMA = """
CREATE OR REPLACE TRIGGER kalmido_osn_gone_rss AFTER DELETE ON rss_items FOR EACH ROW EXECUTE FUNCTION kalmido_osn_gone('rss');
"""
# drop-ok rss_reads: moved into obj_seen (kind rss) by core/objseen.py osn_move_rss just before (stage Q8b, decided 08.11.2026)
# drop-ok rss_items.read_at: moved into obj_seen (kind rss, the feed owner's mark) by core/objseen.py osn_move_rss just before (stage Q8b)
AFTER = [
    "DROP TABLE IF EXISTS rss_reads",
    "ALTER TABLE rss_items DROP COLUMN IF EXISTS read_at",
]
