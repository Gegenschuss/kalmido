"""2.977.0 (#5282, stage Q7b of the cross-cutting core, analysis #3563, decided 08.11.2026): the playbooks and the procedure
documentation keep their versions in the core's obj_versions (core/objversions.py, docs/dev/kern.md "Versions"); their own
tables keep only the head -- one row per Playbook (playbooks: list_id, or owner_id + folder) and one per office area
(office_procdocs: org_id). A version is a row of obj_versions: kind "playbook" / "procdoc", ref_id = the head's id, no = the
version number the routes show (as before), body = the text (a playbook's Markdown; the procedure documentation's JSON
{own, auto, lang, app_version}, sealed like before with the area's key, now with the context "obj_versions.body"), created_by =
the author (was playbooks.author_id / office_procdocs.created_by), created_at, source = how it came (a playbook's edit |
restore | proposal | import | template; '' for the procedure documentation). A playbook's version has no org_id (the playbooks
had no row-level security: who sees the list reads it, the app checks) and owner_id = the folder's owner (a list's: NULL); a
procedure documentation's version has org_id = the office area (row-level security as before).

The move is no statement of this file (a fragment holds no code, and a sealed text changes its AAD context): at every start while
the old columns are there (core/objhooks.START, inside init_db's one transaction) lists/playbook.py pb_retire and
office/procdoc.py pd_retire copy every old version row into obj_versions (in the order of its number, so the ids grow with the
numbers), keep the newest row of each Playbook / area as its head, delete the other rows and drop the old columns
(kern_retire_rows). Start check: a procedure documentation whose sealed text cannot be opened now (the area's key is missing)
moves nothing of that area; then nothing is dropped, the log names the number and the admins get an alert (kind "storage"); the
next start tries again. After the drop the back limit (kalmido_meta back_floor) rises to this minor: a version before 2.977
refuses to start (its code reads playbooks.version / office_procdocs.data).
What has no way back: the columns playbooks.version / body / source / author_id / created_at and office_procdocs.version /
data / created_by / created_at (every row is in obj_versions first) and the old rows besides the heads. Count beforehand (psql):
  SELECT COUNT(*) FROM playbooks; SELECT COUNT(*) FROM office_procdocs;
SQLite heritage (#5305, decided 08.11.2026): the TEXT times and the JSON text of both tables go with the columns; obj_versions
has only real types. schema.py makes the heads only (a new database), with the indexes playbooks_list_v / playbooks_folder_v
(unique per head now) and office_procdocs_org (org_id)."""
# drop-ok playbooks.version: stage Q7b of the cross-cutting core (#5282, decided 08.11.2026); dropped by lists/playbook.py pb_retire after the move into obj_versions
# drop-ok playbooks.body: as playbooks.version (#5282)
# drop-ok playbooks.source: as playbooks.version (#5282)
# drop-ok playbooks.author_id: as playbooks.version (#5282)
# drop-ok playbooks.created_at: as playbooks.version (#5282)
# drop-ok office_procdocs.version: stage Q7b (#5282); dropped by office/procdoc.py pd_retire after the move into obj_versions and its start check
# drop-ok office_procdocs.data: as office_procdocs.version (#5282)
# drop-ok office_procdocs.created_by: as office_procdocs.version (#5282)
# drop-ok office_procdocs.created_at: as office_procdocs.version (#5282)
SCHEMA = """
CREATE OR REPLACE TRIGGER kalmido_ov_gone_playbook AFTER DELETE ON playbooks FOR EACH ROW EXECUTE FUNCTION kalmido_ov_gone('playbook');
CREATE OR REPLACE TRIGGER kalmido_ov_gone_procdoc AFTER DELETE ON office_procdocs FOR EACH ROW EXECUTE FUNCTION kalmido_ov_gone('procdoc');
"""
MIGRATIONS = [
    ("obj_versions", "source", "ALTER TABLE obj_versions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT ''"),
]
