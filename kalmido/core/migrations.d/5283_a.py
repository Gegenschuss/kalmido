"""2.800.0 (#5283, stage Q7c): a table's cell history (sheet_hist) goes past the logs' day in the daily clean-up
(admin/dataretention.py lgc_tick): an index on its time column, so the count and the batches do not read the whole table.
Index only: an older version ignores it."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5283_sheet_hist_at ON sheet_hist(at)",
]
