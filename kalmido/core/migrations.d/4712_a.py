"""2.566.0 (#4712): the shared core, stage 3 -- calendars (ev_cals, kind 'evcal') and address books (books, kind 'address_book')
are object kinds of the core (core/objects.py). They get the core's columns they lack: rev, created_by, updated_at, updated_by,
deleted_at (calendars; the books have it since 2.272.0) and deleted_by. ev_cals.deleted_at = the calendar's trash (#4707): a
calendar there is gone for everyone but who may restore it; its events stay as they are. updated_at '' on old rows = no version
check until their next change (core/conflict.py ccf_check compares only a version the client sent).

The core's shares of the two kinds are rows of fs_shares on the object's reference node. The trigger kalmido_kern_mirror keeps
them equal to the old member tables ev_cal_members / book_members (a row added, its role changed, a row deleted -- by whatever
code path, also imports and repairs) as soon as the object HAS a node: the one-shot of the start (flag migr_kern4712,
events/model.py ev_kern_copy) gives every calendar / address book with members its node, a new member gets it first
(cal_member_set / book_member_set). From then on the core's share is what counts (events/model.py ev_role, contacts/model.py
book_role); the old row is read only for an object without a node, one release long (stage 7 removes the tables). So a share
taken back in the core (the file store's share dialog, obj_revoke_person) is not reopened by the old row. The trigger works
in the system context (a member removing themselves need not see the organisation's node) and restores the caller's.
Review F4: a node of the two kinds made by any path (the first member, a share in the core, filing it in a folder, an import)
mirrors ALL member rows the object has at that moment (kalmido_kern_node_made fires the mirror with UPDATE ... SET role=role, as
the one-shot does): rows written past cal_member_set / book_member_set while there was no node (import, repair) keep their access.
Review F3: a node in the file store's trash is still the object's node (its shares count, the old rows are not read again); a
node removed for good (the trash emptied, taken out of every folder, the organisation's tree gone) first writes its shares to
people and agents back into the member rows (kalmido_kern_node_gone: rows without a share go, the others get its role), so the
fallback reader then gives exactly what the node gave -- a share taken back in the core is not reopened.
New columns, functions and triggers only (nullable or with a DEFAULT): an older version ignores the columns -- its calendars
in the trash would show again --, the trigger keeps mirroring for it, nothing breaks; a backup restores them (kalmido_*).
"""
# 2.924.0 (#5069, stage 7b): the functions and triggers that were here (kalmido_kern_mirror and its triggers on ev_cal_members /
# book_members, kalmido_kern_node_made, kalmido_kern_node_gone) are gone with the old member tables: events/evkern.py
# ev_kern_drop drops them at the start (core/migrations.d/5069_b.py); the columns below stay
MIGRATIONS = [
    ("ev_cals", "rev", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("ev_cals", "created_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS created_by BIGINT"),  # who: no FK (the history keeps a gone account's id)
    ("ev_cals", "updated_at", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
    ("ev_cals", "updated_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("ev_cals", "deleted_at", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS deleted_at TEXT"),
    ("ev_cals", "deleted_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("books", "rev", "ALTER TABLE books ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("books", "created_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS created_by BIGINT"),
    ("books", "updated_at", "ALTER TABLE books ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
    ("books", "updated_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("books", "deleted_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4712_ev_cals_trash ON ev_cals(deleted_at) WHERE deleted_at IS NOT NULL",
]
