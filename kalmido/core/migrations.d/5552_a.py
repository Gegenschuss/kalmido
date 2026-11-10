"""#5552 (decided 10.11.2026): switching the lock of a project on empties its trash of sections (lists/parttrash.py
lpt_section_purge_list, called by collab/liste2e.py le2a_finish), like its files and the kept texts of deleted comments: a
section deleted before the switch kept its plain name in list_part_trash. The copies with a plain name in projects that are
locked already are removed once here (a ciphertext name "e2e1:..." stays; the snapshot is json.dumps text, core/objparts.py part_copy, read as text so that
no cast can fail a start). AFTER runs at every start: the fixed cut-off makes it
a no-op after the first one; copies made later in a locked project carry a ciphertext name. A one-way step: those sections
cannot be restored any more (an older version just finds fewer sections in the trash)."""
# purge-ok list_part_trash: sections deleted before the lock kept their plain names in a locked project (finding of job #3886)
AFTER = ["DELETE FROM list_part_trash WHERE kind='section' AND deleted_at < '2026-11-10' "
         """AND list_id IN (SELECT id FROM lists WHERE COALESCE(e2e, '')<>'') AND position('"name": "e2e1:' in snap)=0"""]
