"""2.566.0 (#4712): address books on the shared core, stage 3 (docs/dev/kern.md, audit #2822 "Stufe 3").

The address book (books) is the object kind 'address_book' of core/objects.py -- the same name as its reference kind of the
file store since 2.351.0 (contacts/ctfolder.py), so its folder shares ARE the core's shares and nothing moves:
- its role stays book_role (contacts/model.py): the book's own role (owner / an organisation's roles / its own node's share
  of the person, bk_member_role) and the role its node gives (ctf_node_role = fs_ref_node_role, the core's share role), the higher one;
  the agents' data lock "contacts" (#4699) is the kind's dl_area for obj_role as well.
- 2.924.0 (#5069, stage 7b): a book is shared only by the shares of its node; its own dialog writes them (book_member_set ->
  obj_node_person_put), the old table book_members goes at the start (events/evkern.py ev_kern_drop).
- losing access is the core's: obj_revoke_person takes the node's shares when a person leaves the organisation and when it
  retires (#4697), restorable 30 days (GET /api/obj/address_book/<id>/shares, POST .../shares/<rid>/restore).
- the file store keeps the folder rules of 2.351.0 (fs_hooks): filing the book and sharing its folder stay with who manages it,
  the token scope "contacts", the module switch and the vCard content as before (on_trash None: a node coming back never
  restores a book in its trash -- contacts/web.py does, with its contacts).
- 2.947.0 (#5367, stage 5 of the core's trash): the book goes into the core's trash (contacts/web.py op_book_delete: obj_trash,
  its node with it) and comes back the core's way (obj_restore) -- without a step of the undo list (step=False): the restore
  route makes its birthday tasks again and links its clients' contact persons, which the core's undo would not. Its contacts
  stay as they are (hidden with the book, no children). Deleting it for good is the core's (obj_purge, and the core's hourly
  run with trash_prune=True instead of the file store's run files/trashpurge.py): its purge hook bk_purge_prep
  (obj_on_purge, #5365) takes what the core does not know first -- the folder nodes and core rows of its contacts and the
  undo data of merges into it.
No generic routes (routes=False): the address book's own routes (contacts/web.py, contacts/v1.py, CardDAV) stay."""
from ..core.i18n import N_
from ..collab.news import news_add  # 2.924.0 (#5069): _share_back
from ..core.objects import obj_node, obj_node_follow, obj_node_person_drop, obj_node_person_put, obj_register
from ..core.objhooks import obj_rows_drop_many  # 2.947.0 (#5367)
from ..core.pg import system_ctx
from ..core.writes import obj_on_purge  # 2.947.0 (#5367)
from .ctfolder import CTF_BOOK, CTF_CONTACT, _book, _book_base, _book_content, _book_space, _book_title, _cap, _gate, _hidden, ctf_root
from .model import BK_KERN, book_role, book_touch


def _base(c, uid, bid):
    """The core's base role: the book's own role without its folder (owner -> 'manage'); a book in the trash only for its
    owner (the core's trash rule)."""
    b = _book(c, bid)
    r = book_role(c, uid, b, trash=True, fold=False) if b is not None else None
    return {"owner": "manage", "edit": "edit", "view": "view"}.get(r)


def _visible(c, uid):
    return f"(SELECT id FROM books WHERE owner_id = {int(uid)})"  # 2.924.0 (#5069): the members are the core's shares only


def bk_node_ensure(c, uid, bid):
    """The book's reference node (made in its workspace's "Address book" folder when that exists, else at the top of the
    tree, like a core object's first share): the node its shares hang on. Returns the node row."""
    b = _book(c, bid)
    if b is None:
        return None
    with system_ctx(c):  # structure: the area folder of the book's own workspace
        root = ctf_root(c, b["owner_id"], b["org_id"], create=False)
        return obj_node(c, uid or b["owner_id"], CTF_BOOK, bid, make=True, parent=root)


def _share_back(c, uid, bid, share):
    """2.924.0 (#5069, fable F3): a share of the book came back through the core's restore (GET /api/obj/address_book/<id>/shares,
    POST .../restore): what book_member_set does on a new member -- the person's News and the book's signature (CardDAV)."""
    who = share.get("user_id") or share.get("agent_id")
    b = _book(c, bid)
    if who and b is not None:
        news_add(c, int(who), "abshare", data={"book_id": int(bid), "name": b["name"], "role": share.get("role") or "view"}, row="share")
    book_touch(c, bid)


BK_KERN.update(node=bk_node_ensure, follow=obj_node_follow, put=obj_node_person_put, drop=obj_node_person_drop)  # #5069: put / drop
obj_register(CTF_BOOK, "books", label=N_("Address book"), fields={}, title=_book_title, base_role=_base, visible=_visible,
             hidden=_hidden(CTF_BOOK), cap=_cap, content=_book_content, dl_area="contacts", scopes=("contacts", "contacts"),
             routes=False, node_shares=True, on_share_back=_share_back, open_url=lambda bid: f"contacts/b/{int(bid)}",
             fs_hooks={"base_role": _book_base, "space": lambda c, bid: _book_space(c, _book(c, bid)), "title": _book_title,
                       "content_gate": _gate, "on_trash": None},
             trash_prune=True)  # 2.947.0 (#5367): the core's hourly run deletes it after the trash period (bk_purge_prep first)


# ---------------------------------------------------------------- the trash (2.947.0, #5367)
def bk_purge_prep(c, bid):
    """The address books' part of the delete for good of book bid (core/writes.py obj_on_purge: obj_purge and the core's
    retention run; then the core takes its node, its own core rows and the row -- its contacts follow by FK cascade): the
    folder nodes and core rows (history, undo, revoked shares) of its contacts and the undo data of merges into it (the
    history line of the merge stays). One-way. Nothing to do after the commit."""
    cts = [r[0] for r in c.execute("SELECT id FROM contacts WHERE book_id=?", (int(bid),)).fetchall()]
    if cts:
        c.execute("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (CTF_CONTACT, cts))
        obj_rows_drop_many(c, CTF_CONTACT, cts)
    c.execute("UPDATE merge_runs SET snapshot='{}' WHERE kind='contact' AND book_id=?", (int(bid),))
    return None


obj_on_purge(CTF_BOOK, bk_purge_prep)
