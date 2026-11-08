"""2.755.0 (#5299, decided 08.11.2026): three indexes the reads ask for. lists(deleted_at): the list trash and every "not in
the trash" filter over the lists; fs_nodes(parent_id, deleted_at): the content of a folder without the trash (fs_nodes_parent
holds only parent_id); list_activity(list_id, created_at): the history of a list, newest first (list_activity_list holds only
list_id). No equivalent index existed (schema.py and the fragments looked through); the old single-column ones stay.
Plain CREATE INDEX, not CONCURRENTLY: the start runs schema and fragments in one transaction (core/db.py init_db), where
CONCURRENTLY is not allowed; the index build locks writes on the table for its time, once. Indexes only: an older version
ignores them."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix5299_lists_deleted ON lists(deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix5299_fs_nodes_parent_deleted ON fs_nodes(parent_id, deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix5299_list_activity_list_created ON list_activity(list_id, created_at)",
]
