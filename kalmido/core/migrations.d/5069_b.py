"""2.924.0 (#5069, decided 07.11.2026): the shared core, stage 7b -- calendars and address books are shared only by the shares of
their reference node (fs_shares, obj_role / obj_share_rows_sql). The old member tables ev_cal_members and book_members of stage 3
(#4712) go, with the sync triggers kalmido_kern_mirror_cal / _book, kalmido_kern_node_made, kalmido_kern_node_gone (4712_a.py),
kalmido_kern_back (5046_a.py) and their functions. schema.py no longer creates the two tables, 4712_a.py / 5046_a.py / 5089_a.py
no longer the functions and triggers.

The drop is not a plain DROP TABLE here: it waits for a check, so it runs as code at the start (events/evkern.py ev_kern_drop,
core/objhooks.START, every start until it is done, under the lock kalmido-kern5069 inside init_db's one transaction):
1. every calendar / address book with an old row and no node gets its node, every such row its share on it (a row an older
   version wrote after a rollback comes along);
2. a row of an object WITH a node and no share of that person is stale (the core said no) and is deleted, the log names the
   number (fable F1 / #5117, decided 08.11.2026, one way);
3. start check (core/kernretire.py kern_retire, the helper of stage 7 shared with the team chat's 7a): is an old row left the
   core does not hold (no node: events/evkern.py ev_kern_left), the tables AND the triggers stay (no half state), the log
   says how many and the admins get an alert (kind "storage"); nothing is dropped, the next start checks again;
4. else the triggers and functions go, then DROP TABLE IF EXISTS ev_cal_members, book_members, and their rows in obj_revoked
   (src = the old table).
One way: the rows of the two tables are lost (the shares of the nodes hold the same people and roles). A version before 2.924
started afterwards makes the two tables again, empty, with its triggers, and reads the nodes' shares (it runs); the next start
of 2.924 drops them again. Count on a live database beforehand (psql):
  SELECT 'ev_cal_members', COUNT(*) FROM ev_cal_members m WHERE NOT EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref'
    AND n.ref_kind='evcal' AND n.ref_id=m.cal_id)
  (rows without a node: step 1 gives them one; the same for book_members with ref_kind 'address_book' and book_id), and the
  stale rows step 2 deletes:
  SELECT 'ev_cal_members', COUNT(*) FROM ev_cal_members m WHERE EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref'
    AND n.ref_kind='evcal' AND n.ref_id=m.cal_id) AND NOT EXISTS (SELECT 1 FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id
    WHERE n.kind='ref' AND n.ref_kind='evcal' AND n.ref_id=m.cal_id AND (s.user_id=m.user_id OR s.agent_id=m.user_id))
"""
# drop-ok ev_cal_members: decided 07.11.2026 (#5069): a calendar's members are the shares of its node; dropped by events/evkern.py ev_kern_drop after its check
# drop-ok book_members: decided 07.11.2026 (#5069): an address book's members are the shares of its node; dropped by events/evkern.py ev_kern_drop after its check
