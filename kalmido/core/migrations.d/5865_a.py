"""2.1073.0 (#5865, rest of #5789, one way; decided by the lead of 2.1005 / #5789): the office trash's table of copies goes.
office_trash (2.272.0 E2, #3038) held a deleted office row as a raw copy (snap). Since 2.1067 (#5789) every office kind is on
the core's trash (office/okern.py ofk_register); the copies' routes, their purge run and every reader are gone, and the start
writes old copies back as rows of the core's trash (okern.ofk_copies_back). schema.py no longer creates the table.

The DROP is no statement of this file: a fragment's AFTER runs in core/db.py init_db, BEFORE kalmido/startup.py writes the
copies back (the office kinds are registered once the app's modules are loaded) -- a database from before 2.1067 (the live
one when 2.1067 and this package go live in the same train, a backup played in, a jump over versions) would lose its copies
before they came back. So at every start, in kalmido/startup.py: ofk_copies_back first, its commit, then okern.ofk_trash_drop
(a no-op once the table is gone; never when the copies' run failed).

Counting beforehand (read-only): SELECT kind, COUNT(*) FROM office_trash GROUP BY kind;
(before the first start of 2.1067 every copy of a kind on the core's trash still comes back; after it only the copies whose row
or key was there again are left, and nothing lists or restores them any more.)

What has no way back: the copies that could not come back (they go with the table; the start's log names their number). An
older version would make the table again, empty, and run on it (nothing of it is read since 2.1067), so the database's back
limit stays as it is."""
# drop-ok office_trash: the office trash's copies are rows of the core's trash since 2.1067 (#5789, #5865); office/okern.py ofk_trash_drop drops it at the start right after ofk_copies_back
