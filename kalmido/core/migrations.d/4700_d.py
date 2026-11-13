"""2.560.0 D (#4700): the version of a credit card position (office_cc_lines.updated_at, ISO time; NULL = a position from
before, saved without the check): its dialog sends it back as expect_updated_at, saved elsewhere meanwhile -> 409 instead
of overwriting. New column only: older versions ignore it."""
MIGRATIONS = [
    ("office_cc_lines", "updated_at", "ALTER TABLE office_cc_lines ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
]
