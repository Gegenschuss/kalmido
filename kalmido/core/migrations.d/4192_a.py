"""2.644.0 (#4192): the daily clean-up of old logs (admin/dataretention.py lgc_tick) finds the rows past their day by time:
an index on the time column of each log table that had none, so the count and the deletion in batches do not read the whole
table each time. Indexes only: an older version ignores them."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4192_list_activity_created ON list_activity(created_at)",
    "CREATE INDEX IF NOT EXISTS ix4192_fs_log_at ON fs_log(at)",
    "CREATE INDEX IF NOT EXISTS ix4192_org_list_log_created ON org_list_log(created_at)",
    "CREATE INDEX IF NOT EXISTS ix4192_sheet_changes_created ON sheet_changes(created_at)",
]
