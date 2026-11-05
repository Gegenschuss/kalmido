"""2.566.0 (#4712): address books on the shared core, stage 3 (docs/dev/kern.md, audit #2822 "Stufe 3").

The address book (books) is the object kind 'address_book' of core/objects.py -- the same name as its reference kind of the
file store since 2.351.0 (contacts/ctfolder.py), so its folder shares ARE the core's shares and nothing moves:
- its role stays book_role (contacts/model.py): the book's own role (owner / an organisation's roles / a member row of a book
  without a live node) and the role its node gives (ctf_node_role = fs_ref_node_role, the core's share role), the higher one;
  the agents' data lock "contacts" (#4699) is the kind's dl_area for obj_role as well.
- book_members is mirrored into the shares of the book's node by the trigger kalmido_kern_mirror (core/migrations.d/4712_a.py);
  a book with a live node is shared only by its node, the old rows are the fallback reader of one release (stage 7 removes them).
- losing access is the core's: obj_revoke_person takes the node's shares and the rows of book_members (members= of
  obj_register) when a person leaves the organisation and when it retires (#4697).
- the file store keeps the folder rules of 2.351.0 (fs_hooks): filing the book and sharing its folder stay with who manages it,
  the token scope "contacts", the module switch and the vCard content as before; its own trash (2.272.0 E1) stays the book's
  (on_trash None: a node coming back never restores a book in its trash -- contacts/web.py does, with its contacts).
No generic routes (routes=False): the address book's own routes (contacts/web.py, contacts/v1.py, CardDAV) stay."""
from ..core.i18n import N_
from ..core.objects import obj_node, obj_node_follow, obj_register
from ..core.pg import system_ctx
from .ctfolder import CTF_BOOK, _book, _book_base, _book_content, _book_space, _book_title, _cap, _gate, _hidden, ctf_root
from .model import BK_KERN, BK_NODE_SQL, book_role


def _base(c, uid, bid):
    """The core's base role: the book's own role without its folder (owner -> 'manage'); a book in the trash only for its
    owner (the core's trash rule)."""
    b = _book(c, bid)
    r = book_role(c, uid, b, trash=True, fold=False) if b is not None else None
    return {"owner": "manage", "edit": "edit", "view": "view"}.get(r)


def _visible(c, uid):
    u = int(uid)
    return (f"(SELECT id FROM books WHERE owner_id = {u} UNION SELECT m.book_id FROM book_members m WHERE m.user_id = {u} "
            f"AND NOT EXISTS ({BK_NODE_SQL.format('m.book_id')}))")


def bk_node_ensure(c, uid, bid):
    """The book's reference node (made in its workspace's "Address book" folder when that exists, else at the top of the
    tree, like a core object's first share): the node its shares (book_members, mirrored) hang on. Returns the node row."""
    b = _book(c, bid)
    if b is None:
        return None
    with system_ctx(c):  # structure: the area folder of the book's own workspace
        root = ctf_root(c, b["owner_id"], b["org_id"], create=False)
        return obj_node(c, uid or b["owner_id"], CTF_BOOK, bid, make=True, parent=root)


BK_KERN.update(node=bk_node_ensure, follow=obj_node_follow)
obj_register(CTF_BOOK, "books", label=N_("Address book"), fields={}, title=_book_title, base_role=_base, visible=_visible,
             hidden=_hidden(CTF_BOOK), cap=_cap, content=_book_content, dl_area="contacts", scopes=("contacts", "contacts"),
             routes=False, members=("book_members", "book_id"), open_url=lambda bid: f"contacts/b/{int(bid)}",
             fs_hooks={"base_role": _book_base, "space": lambda c, bid: _book_space(c, _book(c, bid)), "title": _book_title,
                       "content_gate": _gate, "on_trash": None})
