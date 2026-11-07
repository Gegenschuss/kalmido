"""2.640.0 (#4185): indexes of the /api/state helpers. attachments / list_files by their uploader (the storage sum of
admin/hosting.py _user_bytes read both tables whole), tasks by list, created_at, id (lists/projects.py list_progress: the
check whether a done task is a copy of a recurring task looks for an older task of the list with the same created_at and title).
Indexes only: an older version ignores them."""
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4185_attachments_user ON attachments(user_id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix4185_list_files_user ON list_files(user_id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix4185_tasks_copy ON tasks(list_id, created_at, id)",
]
