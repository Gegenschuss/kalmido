"""#5564 (review): obj_undo by object (kind, ref_id) -- the lock's sweep of the history of deleted time entries / notepads
(collab/liste2eguard.py le2b_hist_gone) asks per history row whether an undo part of the entry is left, and the scrubs
match kind=... AND ref_id IN (...). An index only: older versions ignore it."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS obj_undo_ref ON obj_undo(kind, ref_id)",
]
