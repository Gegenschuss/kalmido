"""2.657.0 (#5052): the version of a project's settings (lists.updated_at). PATCH /api/lists/<id> and /api/v1/lists/<id> check it
under the project's write_lock (core/conflict.py ccf_check: expect_updated_at / If-Match differs = 409 with "current"; an agent
must send it or _prev, else 400 version_required) and set it when the project's row changed. '' on old rows = the read shows
created_at, the next change gives the row that version first (core/conflict.py kern_version_seed). Additive only: the version
before neither reads nor writes the column.
"""
MIGRATIONS = [
    ("lists", "updated_at", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"),
]
