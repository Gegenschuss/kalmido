"""2.55.0 (#1067): the blocks of the views that came to the builder late (statistics, client card, family) for the agents'
arrangement proposals (agents/lyprop.py)."""
from ..core.i18n import N_
from ..agents.lyprop import lyp_reg

# (key, English name, width in sixths, fixed): the order is the default order
LYX_BLOCKS = {
    "view_stats": [("tiles", "Totals", 6, False), ("done", "Completed tasks", 6, False), ("bylist", "By list", 6, False),
                   ("overdue", "Overdue", 6, False), ("focus", "Focus time", 6, False), ("time", "Tracked time", 6, False),
                   ("habits", "Habits", 6, False)],
    "view_clients": [("details", "Details", 6, False), ("persons", "Contact persons", 6, False), ("invoices", "Open invoices", 6, False),
                     ("month", "Month", 6, False), ("lists", "Lists and projects", 6, False), ("note", "Note", 6, False)],
    "view_family": [("occ", "Birthdays & anniversaries", 3, False), ("rot", "Whose turn", 3, False), ("meals", "Meal plan", 3, False),
                    ("shop", "Shopping", 3, False), ("dl", "Deadlines", 3, False), ("kids", "Kids", 3, False), ("pack", "Packing lists", 3, False)],
}
LYX_NAMES = {"view_stats": N_("Statistics"), "view_clients": N_("Clients"), "view_family": N_("Family")}
for _k, _bs in LYX_BLOCKS.items():
    lyp_reg(_k, _bs, LYX_NAMES[_k])
