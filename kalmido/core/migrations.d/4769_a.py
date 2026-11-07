"""2.641.0 (#4769): the sign-off (videos/review.py) also takes images (JPG, PNG, WebP) and PDFs of the file store
(videos/vdmedia.py). A version says its medium: kind video | image | pdf; an image / PDF points at a file of the file store
(file_id, the file stays there; file_no = the file's version shown, the newest one when it was added) with its name and type
at that time. A comment sits at a point of its version: pos_x / pos_y (0..1 of the width / height of the image or page) and
page (1 = the first page of a PDF); a video comment keeps at_sec. New columns only: an older version ignores them (it shows
an image / PDF version as a link without time control)."""
MIGRATIONS = [
    ("video_versions", "kind", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'video'"),
    ("video_versions", "file_id", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS file_id BIGINT REFERENCES fs_nodes(id) ON DELETE SET NULL"),
    ("video_versions", "file_no", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS file_no BIGINT"),
    ("video_versions", "file_name", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS file_name TEXT NOT NULL DEFAULT ''"),
    ("video_versions", "mime", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS mime TEXT NOT NULL DEFAULT ''"),
    ("video_comments", "page", "ALTER TABLE video_comments ADD COLUMN IF NOT EXISTS page BIGINT"),
    ("video_comments", "pos_x", "ALTER TABLE video_comments ADD COLUMN IF NOT EXISTS pos_x REAL"),
    ("video_comments", "pos_y", "ALTER TABLE video_comments ADD COLUMN IF NOT EXISTS pos_y REAL"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4769_video_versions_file_id ON video_versions(file_id) WHERE file_id IS NOT NULL",
]
