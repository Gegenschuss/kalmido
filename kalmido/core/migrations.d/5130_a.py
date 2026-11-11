"""2.673.0 (#5130): an index on doc_notes(user_id). The key doc_notes.user_id -> users (ON DELETE SET NULL, #4807) had none:
every person that goes made the database scan all document notes for that key. New index only: older versions ignore it."""
# 2.981.0 (#5273): doc_notes went into obj_comments (kind doc_note, migrations.d/5273_a.py; its index on user_id: ix5272_obj_comments_user)
AFTER = []
