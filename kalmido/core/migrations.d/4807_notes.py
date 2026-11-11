"""2.635.0 (#4807 d): notes on a document (kalmido/docs/notes.py). One row per note: the document (node_id), its workspace (ws,
org_id NULL = a person's own space), who wrote it (user_id; NULL once the person is gone or for an imported note, then author
holds the name it came with), the text sealed with the workspace key like the document's other contents (doc_seal,
"doc_notes.text"), source '' (written here) | 'paperless' (imported) and the time. Rights: the document's (docs/notes.py).
New table only: older versions ignore it (the notes are not shown there)."""
# 2.981.0 (#5273): the notes are rows of the comments' core (obj_comments kind doc_note, migrations.d/5273_a.py drops doc_notes)
SCHEMA = ""
AFTER = []
