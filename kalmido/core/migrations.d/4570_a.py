"""2.555.0 (#4570): the budget warning at 80 % / 100 % of "Budget h" (personal/budgetwarn.py). lists.budget_warn /
tasks.budget_warn = the last threshold the project / the task told its people about (0 = none, 80, 100): each threshold
comes once; when the tracked share falls below it again (budget raised, entries removed), the mark goes down with it and
the notice may come again. New columns with a default only: older versions ignore them."""
MIGRATIONS = [
    ("lists", "budget_warn", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS budget_warn SMALLINT NOT NULL DEFAULT 0"),
    ("tasks", "budget_warn", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS budget_warn SMALLINT NOT NULL DEFAULT 0"),
]
