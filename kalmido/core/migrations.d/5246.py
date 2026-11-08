"""2.747.0 (#5246): the old table office_undo (2.111.0 A, #2233: the undo copies of the office editors) goes. Since 2.567.0
(#4711) the steps live in the core's obj_undo; nothing reads or writes office_undo any more, its rows lived one day. A one-way
step: the rows are lost (at most a day of old undo copies nobody reads) and a version before 2.747 fails on its hourly prune
of the table (office/undo.py oun_prune, logged by the watchdog). schema.py no longer creates the table."""
# drop-ok office_undo: read by nothing since 2.567 (#4711, obj_undo); its rows were undo copies of one day, nothing else refers to them
AFTER = ["DROP TABLE IF EXISTS office_undo"]
