# 2.530.0 A (#4315): the trash of comments and team chat messages. A deleted comment / message keeps its row as today (body '',
# deleted_at set: every read path shows it as deleted); its text waits here until the trash run (files/trashpurge.py, the
# row goes with the comment / message) or a restore puts it back. The files stay as rows (attachments.deleted_at = the
# comment's deleted_at; tchat_files unchanged, hidden with their deleted message). New tables only: older versions ignore them.
SCHEMA = """
CREATE TABLE IF NOT EXISTS comment_trash_text (
  comment_id BIGINT PRIMARY KEY REFERENCES comments(id) ON DELETE CASCADE, body TEXT NOT NULL DEFAULT '',
  mentions TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS tchat_trash_text (
  message_id BIGINT PRIMARY KEY REFERENCES tchat_msgs(id) ON DELETE CASCADE, body TEXT NOT NULL DEFAULT '', enc TEXT);
"""
