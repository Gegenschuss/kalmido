"""2.755.0 (#5263, decided 08.11.2026): deleted comments of video / picture reviews go for good. The comments put
into the trash before this version (deleted_at, their text and the guest's name ext_name stayed) are removed once here;
from now on the regular trash run (videos/review.py vdr_trash_prune, kind "trash" of core/retention.py) deletes them after the
trash period, and the organisation export already leaves them out (admin/orgexport.py ox_live). Answers below a deleted comment
go with it (parent_id ON DELETE CASCADE, as in the trash run; the review page shows no answer without its comment).
AFTER runs at every start: the fixed cut-off makes it a no-op after the first one, and comments deleted later keep their trash
period (and the undo). A one-way step: the rows are lost (no way back; an older version just finds fewer deleted comments)."""
# 2.981.0 (#5273): the table went into obj_comments (migrations.d/5273_a.py); the move (core/objcomments.py ocm_move_q4b) leaves
# these comments out the same way (deleted before the cut-off), so the clean-up stays done and this AFTER has no step any more
AFTER = []
