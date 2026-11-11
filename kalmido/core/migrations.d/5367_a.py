"""2.947.0 (#5367, stage 5 of the core's trash): the columns the core's trash writes (core/writes.py obj_trash / obj_restore:
rev, updated_at, updated_by, deleted_by) on the tables of the kinds that move onto it -- bookmarks (life/lfkern.py), feeds
(rss_feeds) and video reviews (video_reviews); the calendars and address books have them since 2.566.0 (#4712). New columns,
nullable or with a default: older versions ignore them. The rows already in the trash keep their deleted_at and are the core's
trash as they are (deleted_by NULL: only who may manage them restores them)."""
MIGRATIONS = [
    ("bookmarks", "rev", "ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("bookmarks", "updated_by", "ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("bookmarks", "deleted_by", "ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("rss_feeds", "rev", "ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("rss_feeds", "updated_at", "ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
    ("rss_feeds", "updated_by", "ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("rss_feeds", "deleted_by", "ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("video_reviews", "rev", "ALTER TABLE video_reviews ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("video_reviews", "updated_by", "ALTER TABLE video_reviews ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("video_reviews", "deleted_by", "ALTER TABLE video_reviews ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
