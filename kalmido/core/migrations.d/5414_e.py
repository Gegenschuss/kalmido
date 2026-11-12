"""2.905.0 (#5414, stage 4c of the core's trash): a letter's link to a document (office_letter_links) is removed into the
core's trash (office/letterlinks.py, office/okern.py ofk_register) instead of a copy in office_trash and the row deleted:
the columns the core writes and a partial index for the trash list and the retention run. New nullable / defaulted columns
only: an older version ignores them (it would show a link of the trash again). Linking the same document again takes the
row of the trash back as a new link (office_letter_links_one stays unique).
2.1076.0 (#5271): the table went into obj_links (migrations.d/5271_a.py drops it); its steps and the index here are gone (they would
fail on a database without the table)."""
MIGRATIONS = []
AFTER = []
