"""2.545.0 (#4387): the day a reminder's fee was marked as paid (office_docs.reminder_fee_paid_at, ISO day; '' / NULL = not
paid or marked before 2.545, then the reminder's own date counts). The income statement, the key figures and the cash flow
count paid fees on this day (office/books.py bk_fees_paid). New column only: older versions ignore it."""
MIGRATIONS = [
    ("office_docs", "reminder_fee_paid_at", "ALTER TABLE office_docs ADD COLUMN IF NOT EXISTS reminder_fee_paid_at DATE"),
]
