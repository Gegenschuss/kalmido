"""2.637.0 (#4768): rules of a list with up to five actions and optional conditions (kalmido/lists/rules.py).

list_rules.more_acts = the actions after the first one, a JSON list [{kind, ...}] ('' = only the first). The first action stays
in act / act_val, so an older version still runs a rule with its first action. list_rules.conds = the conditions "only when"
as JSON {priority?, user_id?, tag_id?, section_id?} ('' = none; all must hold). The due trigger keeps its distance in
trig_val ('' = the due day is today, 'b3' = 3 days before, 'o2' = overdue for 2 days); the run marker of a distance is
due:<due day>:<trig_val> in list_rule_runs (no new column). New columns with defaults only: an older version ignores them."""
MIGRATIONS = [
    ("list_rules", "more_acts", "ALTER TABLE list_rules ADD COLUMN IF NOT EXISTS more_acts TEXT NOT NULL DEFAULT ''"),
    ("list_rules", "conds", "ALTER TABLE list_rules ADD COLUMN IF NOT EXISTS conds TEXT NOT NULL DEFAULT ''"),
]
