"""#5552 (decided 10.11.2026): switching the lock of a project on empties its trash of sections (lists/parttrash.py
lpt_section_purge_list, called by collab/liste2e.py le2a_finish), like its files and the kept texts of deleted comments: a
section deleted before the switch kept its plain name in list_part_trash. Those copies in projects locked already were removed
here at every start with a fixed cut-off (#5565: the day the package was merged).
#5588 (b): the fixed cut-off missed a self-hosted instance that updates later (its copies were deleted after the cut-off). The
clean-up is now a once-run at the start (core/db.py migr_e2etrashsec5588 -> collab/liste2eguard.py le2b_trash_sec_plain); this
fragment stays (empty) so the file name is not given to another step. A one-way step: those sections cannot be restored any
more (an older version just finds fewer sections in the trash)."""
AFTER = []
