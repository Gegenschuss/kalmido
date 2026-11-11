# 2.530.0 A (#4315): the trash of comments and team chat messages. A deleted comment / message keeps its row as today (body '',
# deleted_at set: every read path shows it as deleted); its text waits here until the trash run (files/trashpurge.py, the
# row goes with the comment / message) or a restore puts it back. The files stay as rows (attachments.deleted_at = the
# comment's deleted_at; tchat_files unchanged, hidden with their deleted message). New tables only: older versions ignore them.
# 2.972.0 (#5272): comment_trash_text became obj_comment_trash of the comments' core (migrations.d/5272_a.py, dropped there).
# 2.981.0 (#5274): tchat_trash_text became kind 'tchat' of obj_comment_trash (migrations.d/5274_a.py, dropped there).
SCHEMA = ""
