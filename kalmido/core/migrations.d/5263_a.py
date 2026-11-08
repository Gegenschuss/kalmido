"""2.755.0 (#5263, decided 08.11.2026): deleted comments of video / picture reviews go for good. The comments put
into the trash before this version (deleted_at, their text and the guest's name ext_name stayed) are removed once here;
from now on the regular trash run (videos/review.py vdr_trash_prune, kind "trash" of core/retention.py) deletes them after the
trash period, and the organisation export already leaves them out (admin/orgexport.py ox_live). Answers below a deleted comment
go with it (parent_id ON DELETE CASCADE, as in the trash run; the review page shows no answer without its comment).
AFTER runs at every start: the fixed cut-off makes it a no-op after the first one, and comments deleted later keep their trash
period (and the undo). A one-way step: the rows are lost (no way back; an older version just finds fewer deleted comments)."""
# purge-ok video_comments: deleted review comments kept their text and the guest's name without any end (deletion rule #4315)
AFTER = ["DELETE FROM video_comments WHERE deleted_at IS NOT NULL AND deleted_at < '2026-11-08'"]
