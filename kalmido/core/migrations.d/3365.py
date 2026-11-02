"""2.392.2 (#3365): the delivery state of a task (tasks/deliver.py), a field of its own next to the build state of its code:
delivery = '' | in_progress (a job works on it: delivery_job_id) | parked (delivery_note = the reason) | waiting (for task
delivery_task_id or for what delivery_note says); delivery_at / delivery_by = since when, by whom. Ending the job clears
in_progress. Older versions ignore all of them."""
MIGRATIONS = [
    ("tasks", "delivery", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery TEXT NOT NULL DEFAULT ''"),
    ("tasks", "delivery_note", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery_note TEXT NOT NULL DEFAULT ''"),
    ("tasks", "delivery_job_id", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery_job_id BIGINT REFERENCES agent_jobs(id) ON DELETE SET NULL"),
    ("tasks", "delivery_task_id", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery_task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL"),
    ("tasks", "delivery_at", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery_at TEXT"),
    ("tasks", "delivery_by", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS delivery_by BIGINT REFERENCES users(id) ON DELETE SET NULL"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix3365_tasks_delivery ON tasks(list_id, delivery) WHERE delivery<>''",
    "CREATE INDEX IF NOT EXISTS ix3365_tasks_delivery_job_id ON tasks(delivery_job_id) WHERE delivery_job_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix3365_tasks_delivery_task_id ON tasks(delivery_task_id) WHERE delivery_task_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix3365_tasks_delivery_by ON tasks(delivery_by) WHERE delivery_by IS NOT NULL",
]
