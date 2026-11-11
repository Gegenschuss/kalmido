"""2.937.0 (#5244, decided 08.11.2026): the shared core, stage 7c, tables -- a table is shared with people and agents only by
the shares of its reference node (fs_shares; sheets/shshare.py lists, adds, changes and ends them there, the file store's Share
dialog shows the same rows). sheet_shares keeps only the addresses typed in (email_seal / email_key; user_id = the account of
that address once it is bound, its right is that account's core share on the node). The rows of people and the column core_id
(4717_a.py, no step adds it any more) go, created_at / revoked_at become TIMESTAMPTZ (#5305, schema.py makes them so).

Not a plain DROP COLUMN here: it waits for a check, so it runs as code at the start (sheets/shshare.py shs_retire,
core/objhooks.START, every start until core_id is gone, under the lock kalmido-kern5069 inside init_db's one transaction,
core/kernretire.py kern_retire_rows):
1. the last forward copy: every live row bound to an account without a core share gets one on the table's node (a row an older
   version wrote after a rollback comes along; a table in the trash only when its node is there);
2. start check: a live row bound to an account whose account still has no core share there (a full node) -- nothing changes,
   the log says how many and the admins get an alert (kind "storage"); the next start checks again;
3. else the rows of people (email_key '') go, so does an address bound to an account whose core share is gone (it gave
   nothing; open again it would reopen what was taken back), a time no cast can read becomes the start's time / NULL, then
   DROP COLUMN core_id, created_at / revoked_at TYPE TIMESTAMPTZ, the rows of obj_revoked with src 'sheet_shares', and the
   back limit (kalmido_meta back_floor) rises to this minor: a version before 2.937 refuses to start (it would read core_id).
One way: the rows of people are lost (the node's shares hold the same people and roles; a person's row of a table in the
trash without a node gave nothing since 2.647 and goes). An older move's undo brings back its addresses, not those rows. Count
on a live database beforehand (psql), 0 expected for step 2:
  SELECT COUNT(*) FROM sheet_shares s WHERE s.revoked_at IS NULL AND s.user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM fs_shares f
    JOIN fs_nodes n ON n.id=f.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=s.sheet_id
    AND (f.user_id=s.user_id OR f.agent_id=s.user_id))
"""
# drop-ok sheet_shares.core_id: decided 08.11.2026 (#5244): a table's share is the core share of its node; dropped by sheets/shshare.py shs_retire after its check
