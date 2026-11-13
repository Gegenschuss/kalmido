"""2.1093.0 (#5289, stage Q11 of the cross-cutting core, analysis #3563 section 6): the export register of the core. A table of the
core says ONCE where its rows go in the exports -- the organisation export (admin/orgexport.py), the account export's lists of
what stays out (admin/exportleft.py), the retention export (admin/retexport.py) and the imports (admin/acctimport.py UMZ_READ /
UMZ_ORG_MAP) -- instead of a hand entry in up to six lists. The hand lists keep only the old tables (decision of the product owner, 08.11.2026).

Two ways in, never both for one table (tools/check_export_tables.py fails on a table registered twice or registered and named by
hand as well):
  - obj_register(kind, table, ..., export={...}) (core/objects.py): the own table of a kind of the core
  - obj_export(table, ...) below: the cross-cutting tables of the core (obj_comments, obj_links, obj_tags ...) whose rows belong
    to many kinds (task, video, doc_note, playbook ...), most of them no registered kind; their calls stand in this file
The keywords (plain literals: tools/check_export_tables.py reads them without the app, the CI lint step):
  org        ((archive, where[, part]), ...): files of the organisation export. where = the rows (every "?" is the organisation
             id) with the placeholders of OEX_FMT ({LSQ} the organisation's lists, {TSQ} their tasks, {RSQ} its team chat rooms,
             {LIVE} not in the trash, {LETTER_LINKS} a letter's links); part = the account import's part the file is read as
             (acctimport.py UMZ_ORG_MAP), which the account import reads (UMZ_READ) as well
  org_left   the reason why the table stays out of the organisation export (OX_LEFT)
  acct_left  the reason why it stays out of the account export (UMZ_LEFT_TABLES)
  acct_later the readable name of a table not yet in the account export (UMZ_LATER_NAMES; acct_left is then OEX_LATER)
  rx         ((archive, where), ...): CSV files of the retention export (RX_TABLES with their own rows)
  read       the parts of the account export made of the table that the account import reads (UMZ_READ)
The archive files keep their names and columns (the areas' row hooks in admin/orgexport.py _clean stay). The reasons are i18n
keys without N_ (core/i18nkeys.py reason_keys reads this file)."""

OEX_KEYS = ("org", "org_left", "acct_left", "acct_later", "rx", "read")
OEX_LATER = "not yet in the account export"  # = admin/exportleft.py _LATER
OEX = {}  # table -> {keyword: value, "by": "kind <k>" | "core"}

_DERIVED = "derived or working data, rebuilt on the target"
_SHARE = "who shares what with whom (a share is made anew on the target)"
_VIEW = "what a person has seen or hidden, the order of their rows"


def obj_export(table, *, org=(), org_left=None, acct_left=None, acct_later=None, rx=(), read=(), by="core"):
    """Register where the rows of a table of the core go in the exports (module docstring). Registering a table again from the
    same place replaces it (a module reload); from another place it is refused (one way per table)."""
    old = OEX.get(table)
    if old and old["by"] != by:
        raise ValueError(f"obj_export {table}: registered already ({old['by']})")
    org = tuple(tuple(e) for e in org)
    rx = tuple(tuple(e) for e in rx)
    if any(len(e) not in (2, 3) or not all(isinstance(x, str) and x for x in e) for e in org) \
            or any(len(e) != 2 or not all(isinstance(x, str) and x for x in e) for e in rx):
        raise ValueError(f"obj_export {table}: org = ((archive, where[, part]), ...), rx = ((archive, where), ...)")
    if acct_later and acct_left not in (None, OEX_LATER):
        raise ValueError(f"obj_export {table}: a table not yet in the account export has no other reason")
    OEX[table] = {"org": org, "org_left": org_left, "acct_left": OEX_LATER if acct_later else acct_left,
                  "acct_later": acct_later, "rx": rx, "read": tuple(read), "by": by}
    return OEX[table]


def oex_org(fmt):
    """-> ((archive, table, where), ...) of the organisation export, the placeholders filled from fmt (admin/orgexport.py)."""
    return tuple((e[0], t, e[1].format(**fmt)) for t, r in OEX.items() for e in r["org"])


def oex_rx(fmt):
    """-> ((archive, table, where), ...) of the retention export."""
    return tuple((a, t, w.format(**fmt)) for t, r in OEX.items() for a, w in r["rx"])


def oex_left(key):
    """-> {table: reason} of org_left | acct_left; or {table: name} of acct_later."""
    return {t: r[key] for t, r in OEX.items() if r[key]}


def oex_org_map():
    """-> {archive: part} the account import reads from an organisation export."""
    return {e[0]: e[2] for r in OEX.values() for e in r["org"] if len(e) == 3}


def oex_read():
    """-> the parts of an account export made of the core's tables that the import reads."""
    return frozenset(p for r in OEX.values() for p in (*r["read"], *(e[2] for e in r["org"] if len(e) == 3)))


# ---- the cross-cutting tables of the core (moved here from the hand lists, 2.1093.0 #5289; where clauses unchanged)
obj_export("obj_addr_shares", org_left="invitations (not_included)", acct_left=_SHARE)  # 2.1071.0 (#5658)
# 2.558.0 (#4709): the core's change history / undo steps (the areas export their objects), revoked shares; 2.747.0 (#5249): 30 days
obj_export("obj_history", org_left=_DERIVED, acct_left=_DERIVED)
obj_export("obj_undo", org_left="undo steps of 30 days", acct_left=_DERIVED)
obj_export("obj_revoked", org_left="shares removed (not_included)", acct_left=_SHARE)
obj_export("obj_comment_trash", acct_left=_DERIVED)  # 2.972.0 (#5272), 2.981.0 (#5274): the comments' and the team chat's trash texts
obj_export("obj_search", acct_left=_DERIVED)  # 2.981.0 (#5278): the shared search index, rebuilt from the imported rows by its triggers
obj_export("obj_search_words", acct_left=_DERIVED)  # 2.1002.0 (#5279): the shared word index
obj_export("obj_seen", acct_left=_VIEW)  # 2.905.0 (#5284): the core's read marks (was task_seen), a personal view state
# 2.972.0 (#5285): only the account export's parts list_notif / folder_notif (its queries), which the import leaves behind (UMZ_LEFT)
obj_export("obj_notif_cap")
# 2.947.0 (#5275): project tags (scope list, the file keeps list_id) and the organisation's labels
obj_export("obj_tags", org=(("lists/tags.json", "scope_kind='list' AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)", "list_tags"),
                            ("org/labels.json", "scope_kind='org' AND org_id=?", "org_tags")))
obj_export("obj_tag_links", org=(("tasks/tags.json", """kind='task' AND obj_id IN ({TSQ}) AND tag_id IN (SELECT id FROM obj_tags WHERE (scope_kind='list'
     AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)) OR (scope_kind='org' AND org_id=?))""", "task_list_tags"),),
           read=("task_tags",))
# 2.473.0 (#3357); 2.972.0 (#5285): mode watch, tasks/watchers.json keeps its columns
obj_export("obj_follow", org=(("tasks/watchers.json", "kind='task' AND mode='watch' AND ref_id IN ({TSQ})"),), read=("task_bell", "task_watchers"))
# 2.972.0 (#5272) / 2.981.0 (#5273): the old files and columns (admin/orgexport.py OX_COLS / OX_KIND_COLS)
obj_export("obj_comments", org=(("comments.json", "kind='task' AND ref_id IN ({TSQ})", "comments"),
                                ("videos/comments.json", "kind='video' AND org_id=? AND {LIVE} AND ref_id NOT IN (SELECT id FROM video_reviews WHERE deleted_at IS NOT NULL)"),
                                ("documents/notes.json", "kind='doc_note' AND org_id=? AND {LIVE}")),  # review 2.981 (Fable F6): not the notes in the trash
           read=("video_comments",))
# 2.763.0 (#5269): the files keep their columns (comment_id / message_id)
obj_export("obj_reactions", org=(("comments/reactions.json", "target_kind='comment' AND target_id IN (SELECT id FROM obj_comments WHERE kind='task' AND ref_id IN ({TSQ}) AND {LIVE})"),
                                 ("chat/reactions.json", "target_kind='tchat' AND target_id IN (SELECT id FROM tchat_msgs WHERE room_id IN ({RSQ}) AND {LIVE})")))
# 2.1076.0 (#5271): the old files and columns (admin/orgexport.py ox_link_row); the links of a draft letter stay out of the retention export
obj_export("obj_links", org=(("books/contact_tasks.json", "src_kind='contact' AND dst_kind='task' AND rel='contact' AND src_id IN (SELECT id FROM contacts WHERE book_id IN (SELECT id FROM books WHERE org_id=?)) AND dst_id IN ({TSQ})"),
                             ("office/letter_links.json", "org_id=? AND {LETTER_LINKS}"),
                             ("hub/mail_links.json", "org_id=? AND src_kind='hub_mail' AND rel='made' AND src_id NOT IN (SELECT id FROM hub_mails WHERE deleted_at IS NOT NULL)")),
           rx=(("letters/letter-links.csv", "org_id=? AND {LETTER_LINKS} AND src_id IN (SELECT id FROM office_letters WHERE org_id=? AND status<>'draft')"),))
# 2.958.0 (#5281) / 2.977.0 (#5282): the versions of knowledge pages, Playbooks and the procedure documentation (old columns: ox_objv_row)
obj_export("obj_versions", org=(("lists/playbooks.json", "kind='playbook' AND ref_id IN (SELECT id FROM playbooks WHERE list_id IN ({LSQ}))"),
                                ("office/procdocs.json", "kind='procdoc' AND org_id=?"),
                                ("wiki/versions.json", "kind='wiki' AND org_id=? AND ref_id NOT IN (SELECT id FROM wiki_pages WHERE deleted_at IS NOT NULL)")),
           acct_later="history of knowledge pages", rx=(("books/procedure-documentation.csv", "kind='procdoc' AND org_id=?"),))
