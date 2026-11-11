"""2.958.0 (#5245, stage 7d of the shared core, one-way, decided 08.11.2026 21:26): the projects' old share tables go.

- folder_people: a folder of an owner shared with a person / an agent (2.22.0). Since 2.352.0 only a mirror of the shares of the
  folder's nodes in the projects tree (lists/lffolder.py lf_migrate copied it forward once); the readers read those shares now
  (lffolder.lf_people_rows / lf_people), the mirror is gone.
- group_shares: a project (list_id) or a folder of its owner (owner_id + folder) shared with a group (2.10.0). A project's own
  group share is a core share on the project's node (fs_shares.group_id, list_own 1, list_role = the project role; written by
  lists/groups.py grp_own_put through core/objects.py obj_share), a folder's group share a share of the folder's nodes
  (lffolder.lf_folder_share group=True), which reaches the projects below at runtime (lffolder.lf_want -> list_members.frole).
schema.py no longer creates either table, nor the trigger quicknote_groups.

The DROP is no statement of this file (a fragment's AFTER runs before the areas' start hooks and cannot hold the start check):
at a start, inside core/db.py init_db's one transaction (core/objhooks.START, lists/lkretire.py):
1. lk_grp_copy once (flag migr_grp5245): every group_shares row without its share gets one (a project's node placed where its
   path says, a folder's nodes made where missing), then grp_sync of every project;
2. lk_retire at every start while a table exists (core/kernretire.py kern_retire, lock kalmido-kern5069), each table alone:
   the start check counts old rows the core does not hold -- not 0: the table stays, a line in the log, the admins' alert;
   0: DROP TABLE, its rows of obj_revoked, the database's back limit rises to this minor (an older image would rebuild the
   tables empty: no group share of any project, no folder shown as shared).

Counting beforehand (read-only, the same rules as the start check; before the first start of 2.958 the copy has not run, so
the group count is the number of rows the copy will make):
  SELECT COUNT(*) FROM folder_people p JOIN users u ON u.id=p.user_id WHERE p.folder<>'' AND p.user_id<>p.owner_id AND NOT EXISTS
    (SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='folder' AND n.owner_id=p.owner_id
     AND COALESCE(s.user_id, s.agent_id)=p.user_id);

What has no way back: the rows of folder_people (the folder nodes' shares hold the same people and roles) and of group_shares
(copied forward first; a row of the basket or of a folder path without a node gave nothing and is lost). A folder's group
share now gives a folder role (frole: a person removed from one project by hand stays out, list_folder_skip) instead of grole."""
# drop-ok folder_people: stage 7d of the shared core (#5245, decided 08.11.2026), a mirror of the folder nodes' shares; lists/lkretire.py lk_retire drops it after the start check
# drop-ok group_shares: stage 7d of the shared core (#5245, decided 08.11.2026), group shares are fs_shares rows of the nodes; lists/lkretire.py lk_retire drops it after the start check
