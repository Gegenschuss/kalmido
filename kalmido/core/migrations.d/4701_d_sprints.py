"""2.564.0 D (#4701): sprints.updated_at = the version of a sprint's name / goal / dates; the edit dialog sends it back as
expect_updated_at (saved meantime elsewhere -> 409). A nullable column only: older versions ignore it; a sprint without
one counts with its created_at. (The sprint settings of a list carry their version inside lists.sprint_cfg.)"""
MIGRATIONS = [
    ("sprints", "updated_at", "ALTER TABLE sprints ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
]
