"""2.528.0 D (#4306, B26): switching the lock of a knowledge space on no longer deletes the history and the files in the trash at
once (wiki/wikie2e.py wke_start). wkx_held_at = the time the lock was switched on over this row (NULL = an ordinary row): while
the space is locked nobody sees it, wiki/wkhist.py wkx_tick deletes held versions after the trash period (ret_on("trash")),
held files in the trash go with the ordinary trash runs. wiki_spaces.wkx_holds = JSON {held_at: [user ids]}, the people who
could read the space then: only they see a held row again once the lock is off. Older versions ignore the columns (they see
the held rows as ordinary ones). 2.958.0 (#5281): the versions' column is obj_versions.held_at now (5281_a.py)."""
MIGRATIONS = [
    ("wiki_files", "wkx_held_at", "ALTER TABLE wiki_files ADD COLUMN IF NOT EXISTS wkx_held_at TIMESTAMPTZ"),
    ("wiki_spaces", "wkx_holds", "ALTER TABLE wiki_spaces ADD COLUMN IF NOT EXISTS wkx_holds JSONB NOT NULL DEFAULT '{}'"),
]
# 2.958.0 (#5281): the step wiki_versions.wkx_held_at and its index ix4306_wiki_versions_held were here: the versions are rows of
# obj_versions (held_at), core/migrations.d/5281_a.py
