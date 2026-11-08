"""2.662.0 (#5041): an image / PDF uploaded through the sign-off (videos/vdmedia.py vdm_upload) follows the review's rights
(task / list / client, videos/review.py vdr_may), not the file store's: video_versions.uploaded marks such a version (1 =
this file came in as an upload for exactly this version). vdm_files_ok and the bytes route (vdm_send) then ask the review alone
for that file of that version; a file chosen from the file store (uploaded 0, the default) stays strict (the file right).
The folder "Approvals" is not opened to the whole organisation.
Versions from before this step stay 0 (no backfill: the fragments run no data step; such a review is seen as before, by
who sees its files). New column with a DEFAULT only: an older version ignores it."""
MIGRATIONS = [
    ("video_versions", "uploaded", "ALTER TABLE video_versions ADD COLUMN IF NOT EXISTS uploaded INTEGER NOT NULL DEFAULT 0"),
]
