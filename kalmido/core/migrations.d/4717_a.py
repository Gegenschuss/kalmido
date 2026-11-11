"""2.565.0 (#4717): the shared core, stage 4 -- shares of tables and of knowledge pages / folders with people are core shares
(rows of fs_shares on the table's / page's / folder's reference node, kalmido/core/objects.py obj_node_share). The old rows
stay as the share's card (an address typed in, the switch "show pictures", the dialog's id) and point to their core share:
sheet_shares.core_id, wiki_shares.core_id (+ core_id2: a folder share's page of the same name). A row with core_id NULL is
read as before for one release (fallback, rows not moved yet); the one-shot migr_core4717 (core/db.py init_db) copies them
forward. Nullable columns only: older versions ignore them (and keep reading the rows as before).
2.937.0 (#5244, stage 7c): sheet_shares.core_id (5244_a.py) and wiki_shares.core_id / core_id2 (5244_b.py) are gone again:
the start drops them after its check, no step adds them any more."""
SCHEMA = ""
MIGRATIONS = [
]
AFTER = []
