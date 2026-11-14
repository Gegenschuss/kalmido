"""2.508.0 (#4301): an account's deletion and what it shares privately. The foreign keys of owner_id cascade, so a private
calendar, address book, table or knowledge page used to go with its owner, with everything the others had written into it.

Before the account goes (accounts/users.py _user_purge) every such object passes to the longest-standing person who may
write it: the oldest edit / write share, a share of a folder it is filed in counting like one of its own (a group's share
for each of its members). Never an agent, a child account or a disabled account, nor anybody outside the organisation of an
address book that lies in an organisation's workspace. A table attached to a project that outlives the account falls back
to the project's owner. Without such a person the object goes with the account as before, and the delete dialog says so.

What moves stays private to the new owner. Who could reach it through a folder of the deleted person keeps the role as a
share of the object (the folder itself goes). Knowledge pages move out of the one private space of their owner, so only the
pages somebody may write move, into the heir's space (a taken name gets " (2)"); their read-only shares and public links end,
as on every move of a page (wiki/wkshare.py). A space with the lock cannot move: the server cannot read it.

2.537.0 (#4347): shared branches of the private file store too. A folder or file of the private tree shared with a person
or a group (the topmost such node of a branch; one below it only when nobody above may take it) goes the same way: to the
longest-standing person with an edit share of it or of a folder above it, into the top level of their own tree, with
everything below it -- the contributions of others included (they were the deleted person's nodes) -- every version, the
document data and the recognised text sealed again for the heir's account. The shares of others on the branch and inside
it stay; one of a folder above that goes becomes a share of the branch; the heir's own share rows end (the owner needs
none). What stays behind and goes with the account: locked folders (the server cannot re-wrap their keys), links, agent
folders and the trash. Recognised documents go along (review #4347: what the retention keeps, orgretain.upg_personal took
out of the tree before). A group's share of a folder above becomes the group's share of the branch (never one per member);
an expired row of somebody who keeps a role is replaced. External links and the file requests of others on the branch end
(another owner's workspace, as files/fsmove.py fsm_apply). A file that cannot be sealed again (its key does not open it, a
disk error) stays the deleted person's and goes; the dialog cannot foresee that and counted it as handed on. A branch that
lies in a locked folder, or nobody to take it, goes with the account as before, and the dialog counts it so.

ush_plan is the one place that decides: the dialog counts what the deletion then does. No routes.

2.631.0 (#4584): the dialog says per branch handed on what of it does not go along (locked folders, links, agent folders, the
trash, the copies of mails that go with the account) and how many public links and file requests of others on it end; agents
of other people with a share in it keep it (as built, only said). _branch_walk is the one rule for that and for _folders. The
mail copies (ush_mail_doomed, also for accounts/users.py _up_mail_nodes) are no longer sealed again for the heir only to be deleted right after.

2.644.0 (#4999): the agent shares on a branch handed on follow the rule of a move into the heir's own space (files/fsmove.py
fsm_share_ends): an agent that does not belong there (another person's, an organisation's) loses its share, the dialog
counts it under 'ends'; only an agent of the heir's own space keeps it ('agents')."""
import os

from ..collab.comments import user_names
from ..contacts.ctfolder import CTF_BOOK
from ..contacts.ctkern import bk_node_ensure  # 2.924.0 (#5069)
from ..accounts.orgretain import obj_share_gone  # 2.924.0 (#5069)
from ..core.objects import obj_node_follow, obj_node_person_put, obj_share_locks  # 2.924.0 (#5069); 2.1017.0 (#5645)
from ..contacts.model import book_members_of, book_touch
from ..contacts.orgbooks import obk_hand_on
from ..core.access import Denied, list_role
from ..core.objhooks import OBJ  # 2.566.0 (#4712): the kinds whose reference node is the object's own (counted as itself)
from ..core.db import iso, iso_ms, now_utc
from ..core.dlock import dl_chain_cut  # 2.1160.0 (#5862)
from ..core.i18n import tr
from ..core.pg import insert_id, system_ctx
from ..core.orgcrypt import OrgCryptError
from ..events.model import EV_KIND, cal_members
from ..files.extlinks import xl_space_moved
from ..files.fslock import fsl_map, fsl_of_chain
from ..files.fsmove import fsm_doc, fsm_share_ends, fsm_text, fsm_versions, fsm_walk
from ..files.fstags import dt_move
from ..files.fsref import fs_ref_node
from ..files.store import _free_name, _now, fs_chain, fs_deleted, fs_space, fs_subtree
from ..sheets.core import sh_touch
from ..sheets.shbook import shb_move
from ..sheets.shfolder import SHF_KIND, shf_after_move
from ..sheets.shkinds import shk_move_files
from ..sheets.shshare import SHS_CARD, shs_core_q, shs_drop_cache, shs_put  # 2.937.0 (#5244)
from ..wiki.wikie2e import wke_mode
from ..wiki.wkfolder import WKF_KIND, WKF_SEEN, wkf_node_of, wkf_sync
from ..wiki.wkhist import wkh_drop_unreadable, wsb_body_or
from ..wiki.wkmove import wkm_place


def _accounts(c, ids):
    """{id: row} of the accounts ids (kind, kid, disabled, agent: a row in agents)."""
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r for r in c.execute(f"""SELECT u.id, u.kind, u.kid, u.disabled, EXISTS (SELECT 1 FROM agents a WHERE a.user_id=u.id) AS agent
                                              FROM users u WHERE u.id IN ({q})""", ids).fetchall()}


def _person(r):
    return r is not None and not r["disabled"] and not r["agent"] and (r["kind"] or "user") != "agent"


def _org_ok(c, oid, u):
    return not oid or c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=? AND role IN ('admin', 'member')", (oid, u)).fetchone() is not None


def _folder_shares(c, uid, ref_kind, rid):
    """[(since, person, role)] of the live shares of the folders object rid is filed in, in uid's own tree (a group: each of
    its members). Nothing while the node lies in the trash."""
    n = fs_ref_node(c, ref_kind, rid)
    if n is None or n["org_id"] or n["owner_id"] != uid:
        return []
    chain = fs_chain(c, n["id"])
    if not chain or fs_deleted(chain):
        return []
    ids = [x["id"] for x in chain]
    # 2.1160.0 (#5862, Fable review 1): a share above a folder kept out for that person (a whole knowledge area shared with
    # them, its exclusions) gives them nothing here -- no heir, no share of an object in an excluded folder (core/dlock.py)
    return [r[:3] for r in _node_shares(c, ids, node=True) if r[3] in dl_chain_cut(c, r[1], ids)]


def _item(c, uid, oid, rid, direct, folder, write, fallback=None, fits=None):
    """What happens to one object: {id, heir, others: {person: role through a folder}, shared: anybody else had it}; None when
    no other person has it (and no fallback takes it). fits(person): may this one hold it at all."""
    rows = sorted(list(direct) + list(folder), key=lambda x: (x[0] or "", x[1]))
    who = _accounts(c, [x[1] for x in rows] + [fallback])
    people = [x for x in rows if x[1] != uid and _person(who.get(x[1]))]
    can = lambda u: not who[u]["kid"] and _org_ok(c, oid, u) and (fits is None or fits(u))  # noqa: E731
    heir = next((u for _, u, role in people if role in (write, "edit") and can(u)), None)
    if heir is None and fallback and fallback != uid and _person(who.get(fallback)) and can(fallback):
        heir = fallback
    if heir is None and not people:
        return None
    others = {}
    for _, u, role in folder:
        if u != uid and u != heir and _person(who.get(u)) and _org_ok(c, oid, u) and role in ("view", "edit"):
            others[u] = "edit" if role == "edit" or others.get(u) == "edit" else "view"
    return {"id": rid, "heir": heir, "others": others, "shared": bool(people)}


def _node_shares(c, ids, node=False):
    """[(since, person, role)] of the live shares of nodes ids with people (a group: each of its members); node=True: + the
    share's node id (2.1160.0 #5862)."""
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [tuple(r) if node else tuple(r)[:3] for r in c.execute(f"""SELECT s.created_at, COALESCE(s.user_id, m.user_id), s.role, s.node_id FROM fs_shares s
                                            LEFT JOIN group_members m ON m.group_id=s.group_id
                                            WHERE s.node_id IN ({q}) AND COALESCE(s.user_id, m.user_id) IS NOT NULL
                                            AND (s.expires_at IS NULL OR s.expires_at>?)""", (*ids, iso(now_utc()))).fetchall()]


def _above_rows(c, ids):
    """({person: role}, {group: role}) of the live share rows of nodes ids with a person or a group (edit wins)."""
    direct, groups = {}, {}
    if ids:
        q = ",".join("?" * len(ids))
        for u, g, role in c.execute(f"""SELECT user_id, group_id, role FROM fs_shares WHERE node_id IN ({q})
                                        AND COALESCE(user_id, group_id) IS NOT NULL AND (expires_at IS NULL OR expires_at>?)""",
                                    (*ids, iso(now_utc()))).fetchall():
            d, k = (direct, u) if u else (groups, g)
            if role in ("view", "edit"):
                d[k] = "edit" if role == "edit" or d.get(k) == "edit" else "view"
    return direct, groups


def ush_mail_doomed(c, uid):
    """(roots, ids): the filed copies (fs_nodes marked with hub_mail_id) of the mails that go with account uid (the hub_mails
    DELETE in accounts/users.py _user_purge) -- a folder only when everything in it belongs to those mails --, without
    deleting anything: the roots to purge in node order (users._up_mail_nodes, 2.148.1 H #2488) and every node id in them.
    2.631.0 (#4584): a branch handed on leaves them out (they were sealed again for the heir only to go right after) and the
    delete dialog counts them."""
    roots, ids = [], set()
    with system_ctx(c):  # the nodes may lie in an organisation's tree
        gone = {r[0] for r in c.execute("SELECT id FROM hub_mails WHERE owner_id=? AND (org_id IS NULL OR (client_id IS NULL AND list_id IS NULL))", (uid,))}
        if not gone:
            return roots, ids
        q = ",".join("?" * len(gone))
        for nid, kind in c.execute(f"SELECT id, kind FROM fs_nodes WHERE hub_mail_id IN ({q}) ORDER BY id", list(gone)).fetchall():
            if nid in ids:
                continue
            if kind != "folder":  # 2.631.0 (#4584): a filed mail or attachment holds nothing - no subtree look per mail
                roots.append(nid)
                ids.add(nid)
                continue
            sub = fs_subtree(c, nid)
            marks = c.execute(f"SELECT hub_mail_id FROM fs_nodes WHERE id IN ({','.join('?' * len(sub))})", sub).fetchall()
            if all(m[0] in gone for m in marks):
                roots.append(nid)
                ids.update(sub)
    return roots, ids


def _mail_doomed(c, uid):
    return ush_mail_doomed(c, int(uid))[1]


def _branch_walk(c, uid, root, doomed):
    """(moved rows (fsm_walk, root first), subtree ids) of branch root (_folders): locked folders below it with what lies in
    them, links, agent folders, the trash and the mail copies that go (doomed) stay. 2.631.0 (#4584): one map of the locks
    instead of one look per node; the delete dialog counts with it (_branch_counts)."""
    sub = fs_subtree(c, root["id"])
    locked = set()
    for i in range(0, len(sub), 500):
        locked.update(fsl_map(c, sub[i:i + 500]))
    stays = {i for i in sub if i != root["id"] and (i in locked or i in doomed)}
    moved, _stay = fsm_walk(c, root, only=set(sub) - stays)
    return moved, sub


def _in_parts(c, sql, ids, *args):
    """The rows of sql (with {q} for the ids) over ids in parts of 500."""
    out = []
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        out += c.execute(sql.format(q=",".join("?" * len(part))), (*part, *args)).fetchall()
    return out


def _branch_counts(c, uid, x, doomed):
    """2.631.0 (#4584): {stay, ends, agents} of branch item x handed on (_fs_branches): entries of the deleted person in it
    that do not go along (filed objects count as themselves above), the live public links and the file requests of others
    that end (_folders), the agents of other people with a live share in it: 2.644.0 (#4999) those outside the heir's own
    space end (counted in ends, _heir_agents), the others keep it (agents). Numbers only."""
    root = c.execute("SELECT * FROM fs_nodes WHERE id=?", (x["id"],)).fetchone()
    if root is None:
        return {"stay": 0, "ends": 0, "agents": 0}
    moved, sub = _branch_walk(c, uid, root, doomed)
    own = [r["id"] for r in moved if r["owner_id"] == uid]
    mine = sum(r[0] for r in _in_parts(c, "SELECT COUNT(*) FROM fs_nodes WHERE id IN ({q}) AND owner_id=? AND kind<>'ref'", sub, uid))
    stay = mine - sum(1 for r in moved if r["owner_id"] == uid and r["kind"] != "ref")
    now = iso(now_utc())
    ends = sum(r[0] for r in _in_parts(c, "SELECT COUNT(*) FROM fs_ext_links WHERE node_id IN ({q}) AND revoked_at IS NULL "
                                          "AND (expires_at IS NULL OR expires_at>?)", own, now))
    ends += sum(r[0] for r in _in_parts(c, "SELECT COUNT(*) FROM fs_upload_requests WHERE node_id IN ({q}) AND created_by<>? "
                                           "AND revoked_at IS NULL AND deleted_at IS NULL", own, x["heir"]))
    agents = {r[0] for r in _in_parts(c, "SELECT s.agent_id FROM fs_shares s JOIN agents a ON a.user_id=s.agent_id WHERE s.node_id IN ({q}) "
                                         "AND (a.owner_id IS NULL OR a.owner_id<>?) AND (s.expires_at IS NULL OR s.expires_at>?)", own, uid, now)}
    keep = _heir_agents(c, agents, x["heir"])
    return {"stay": stay, "ends": ends + len(agents - keep), "agents": len(keep)}


def _heir_agents(c, aids, heir):
    """2.644.0 (#4999): the agents of aids that keep their share of a branch handed on to heir: the rule of a move into the
    heir's own space (fsm_share_ends; an organisation's agent or another person's private agent ends)."""
    return {a for a in aids if not fsm_share_ends(c, {"agent_id": a}, None, heir)}


def _fs_branches(c, uid, doomed=frozenset()):
    """(items (_item, heir set), n gone) of the folders and files of uid's private tree shared with a person or a group,
    outside the areas (a table, page or address book in a shared folder counts as itself above). 2.537.0 (#4347): top
    down; a node inside a branch that is handed on goes along with it; the others go with the account (counted). 2.631.0
    (#4584): a mail copy that goes with the account (doomed) is never handed on (it goes, counted)."""
    roots = {r[0] for r in c.execute("SELECT node_id FROM fs_area_roots WHERE node_id IS NOT NULL")}
    found = []
    # 2.566.0 (#4712): the reference node of a calendar / address book on the shared core carries its shares: it counts as the
    # calendar / book above, never as a shared branch of the file store
    own = sorted(k for k, r in OBJ.items() if r.get("node_shares"))  # 2.924.0 (#5069): was members=
    skip = f" AND NOT (n.kind='ref' AND n.ref_kind IN ({','.join('?' * len(own))}))" if own else ""
    for (nid,) in c.execute("""SELECT DISTINCT n.id FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id WHERE n.owner_id=? AND n.org_id IS NULL
                               AND COALESCE(s.user_id, s.group_id) IS NOT NULL AND (s.expires_at IS NULL OR s.expires_at>?)
                               AND NOT (n.kind='ref' AND n.ref_kind='sheet')""" + skip,  # 2.565.0 (#4717): a table's own node carries its shares: the table counts above
                            (uid, iso(now_utc()), *own)).fetchall():
        chain = fs_chain(c, nid)
        if chain and not fs_deleted(chain) and not ({x["id"] for x in chain} & roots):
            found.append(chain)
    found.sort(key=lambda ch: (len(ch), ch[0]["id"]))
    items, taken, gone = [], set(), 0
    for chain in found:
        nid = chain[0]["id"]
        if any(x["id"] in taken for x in chain[1:]):
            continue  # it goes along with the branch above
        # only the person's own tree (never a node of theirs in somebody else's folder), nothing locked
        mine = all(x["owner_id"] == uid and not x["org_id"] for x in chain)
        it = None
        if mine and nid not in doomed and fsl_of_chain(c, chain) is None:
            above = [x["id"] for x in chain[1:]]
            it = _item(c, uid, None, nid, _node_shares(c, [nid]), _node_shares(c, above), "edit")
            if it:  # review #4347: a group's share above stays the group's (a member who leaves it loses it), no row per member
                direct, groups = _above_rows(c, above)
                it["others"] = {u: direct[u] for u in it["others"] if u in direct}
                it["groups"] = groups
        if it and it["heir"]:
            items.append(it)
            taken.add(nid)
        else:
            gone += 1
    return items, gone


def ush_plan(c, uid, doomed=None):
    """{calendars, books, sheets, wiki: [item (_item)]} of account uid. Numbers and ids only (the caller may be an instance
    admin outside it all). doomed: the mail copies that go (_mail_doomed; looked up when None)."""
    return _plan(c, int(uid), _mail_doomed(c, int(uid)) if doomed is None else doomed)[0]


def _plan(c, uid, doomed):
    """(ush_plan, n folders gone) -- 2.631.0 (#4584): one walk of the shared branches for the plan and the dialog."""
    out = {"calendars": [], "books": [], "sheets": [], "wiki": [], "folders": []}
    with system_ctx(c):  # the deleted person's objects, whoever deletes the account
        for (cid,) in c.execute("SELECT id FROM ev_cals WHERE owner_id=? AND org_id IS NULL", (uid,)).fetchall():
            # 2.647.0 (#5046): the live members as the core has them (a share taken back / run out there is no heir)
            direct = [(m["added_at"], m["user_id"], m["role"]) for m in cal_members(c, cid, live=True)]
            out["calendars"].append(_item(c, uid, None, cid, direct, [], "edit"))
        for bid, oid in c.execute("SELECT id, org_id FROM books WHERE owner_id=? AND owner_org_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
            direct = [(m["added_at"], m["user_id"], m["role"]) for m in book_members_of(c, bid, live=True)]  # 2.647.0 (#5046)
            out["books"].append(_item(c, uid, oid, bid, direct, _folder_shares(c, uid, CTF_BOOK, bid), "edit"))
        for sid, lid in c.execute("SELECT id, list_id FROM sheets WHERE owner_id=? AND org_id IS NULL AND book_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
            # 2.937.0 (#5244): the people of the table's node (its core shares; a bound address is its account's share)
            direct = shs_core_q(c, "x.created_at, x.user_id, x.role", "x.ref_id=? AND x.user_id IS NOT NULL", (sid,), trash=False).fetchall()
            lr = c.execute("SELECT owner_id FROM lists WHERE id=? AND org_id IS NULL", (lid,)).fetchone() if lid else None
            out["sheets"].append(_item(c, uid, None, sid, [tuple(x) for x in direct], _folder_shares(c, uid, SHF_KIND, sid), "write", lr[0] if lr else None))
        if not wke_mode(c, None, uid)[0]:
            # 2.937.0 (#5244, stage 7c): a person share of the knowledge dialog is a share of the page's / folder's node --
            # _folder_shares reads the page's node and the folders above it (no card of wiki_shares any more)
            for p in c.execute("SELECT id, path FROM wiki_pages WHERE owner_id=? AND org_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
                out["wiki"].append(_item(c, uid, None, p["id"], [], _folder_shares(c, uid, WKF_KIND, p["id"]), "edit",
                                         fits=lambda u: not wke_mode(c, None, u)[0]))  # review: never into a space with the lock (the text would lie open there)
        out["folders"], gone = _fs_branches(c, uid, doomed)  # 2.537.0 (#4347)
    return {k: [x for x in v if x] for k, v in out.items()}, gone


def ush_info(c, uid):
    """For the delete dialog (orgretain.upg_info): {to: {kind: n}, gone: {kind: n}, names: [who takes them over], branches:
    [{stay, ends, agents}] (2.631.0, #4584: per branch handed on with something to say, _branch_counts)}."""
    uid = int(uid)
    doomed = _mail_doomed(c, uid)
    plan, fgone = _plan(c, uid, doomed)
    to = {k: sum(1 for x in v if x["heir"]) for k, v in plan.items()}
    gone = {k: sum(1 for x in v if not x["heir"]) for k, v in plan.items()}
    gone["folders"] = fgone  # 2.537.0 (#4347): only the branches nobody takes over
    with system_ctx(c):  # numbers only
        branches = [b for b in (_branch_counts(c, uid, x, doomed) for x in plan["folders"]) if any(b.values())]
        heirs = sorted({x["heir"] for v in plan.values() for x in v if x["heir"]})
        names = user_names(c, heirs)
    return {"to": {k: n for k, n in to.items() if n}, "gone": {k: n for k, n in gone.items() if n},
            "names": [names.get(h, "") for h in heirs if names.get(h)], "branches": branches}


def _calendars(c, items):
    for x in sorted(items, key=lambda x: int(x["id"])):  # 2.1017.0 (#5645): in id order (two hand-ons never cross)
        srt = (c.execute("SELECT MAX(sort) FROM ev_cals WHERE owner_id=?", (x["heir"],)).fetchone()[0] or 0) + 1  # its first calendar stays its default
        # 2.1017.0 (#5645): the object's row first, then its share rows -- the order of the members dialog (events/model.py
        # cal_member_set); the other way round the two could deadlock
        c.execute("UPDATE ev_cals SET owner_id=?, sort=?, changed_at=? WHERE id=?", (x["heir"], srt, iso_ms(now_utc()), x["id"]))
        obj_share_gone(c, EV_KIND, x["id"], x["heir"])  # 2.924.0 (#5069): the heir needs no share of its own (was its old member row)
        # 2.924.0 (#5069): its node (with the other members' shares) leaves the deleted person's tree for the heir's -- the old
        # member rows that kept them when the tree went (kalmido_kern_node_gone) are gone
        obj_node_follow(c, EV_KIND, x["id"])


def _books(c, items):
    """2.924.0 (#5069): the book keeps its node (no ctf_dropped any more: the node's shares are its members now): the node
    leaves the deleted person's tree (and its folders) for the heir's, the people who reached it through a folder of that
    tree keep their role as a share of the node (obj_node_person_put; one with a share keeps the one it has)."""
    items = sorted(items, key=lambda x: int(x["id"]))  # 2.1017.0 (#5645): in id order, the people too (two hand-ons never cross)
    # 2.1032.0 (#5788, review F2 of 2.1017): every book's row first, then the share buckets -- one book after the other held
    # the bucket of book 1's share while it asked for book 2's row, and the members dialog of book 2 (contacts/model.py
    # book_member_set: the book's row, then the bucket) the other way round: one of the two got a deadlock
    for x in items:
        obk_hand_on(c, x["id"], x["heir"])
        obj_node_follow(c, CTF_BOOK, x["id"])
        book_touch(c, x["id"])
    puts = []
    for x in items:
        if x["others"]:
            n = bk_node_ensure(c, x["heir"], x["id"])
            have = {m["user_id"] for m in book_members_of(c, x["id"], live=True)}
            puts += [(x["heir"], n, u, role) for u, role in sorted(x["others"].items()) if u not in have]
    obj_share_locks(c, [(n["id"], u) for _h, n, u, _r in puts])  # their buckets in ascending order (two purges never cross)
    for heir, n, u, role in puts:
        obj_node_person_put(c, heir, n, u, role)


def _sheet_put(c, heir, r, who, role, expires_at=None):
    """2.937.0 (#5244): one share of table r on its node in the heir's tree (shshare.py shs_put); a full node keeps the rest."""
    try:
        with c.savepoint():
            shs_put(c, heir, r, who, role, expires_at)
    except Denied:
        print(f"WARNING table {r['id']}: no room for a share after its hand-on (#5244)", flush=True)


def _sheets(c, items, new_paths, old_paths):
    for x in items:
        sid, heir = x["id"], x["heir"]
        lid = c.execute("SELECT list_id FROM sheets WHERE id=?", (sid,)).fetchone()[0]
        c.execute("DELETE FROM sheet_shares WHERE sheet_id=? AND user_id=?", (sid, heir))  # an address bound to the heir
        # 2.937.0 (#5244): the shares are the core shares of the table's node, which goes with the move below: kept here and
        # put on the node in the heir's tree after it (the heir's own goes: the table is theirs)
        n = fs_ref_node(c, "sheet", sid)
        keep = c.execute("SELECT user_id, agent_id, role, expires_at FROM fs_shares WHERE node_id=? AND (user_id IS NOT NULL OR "
                         "agent_id IS NOT NULL) AND COALESCE(user_id, agent_id)<>?", (n["id"], heir)).fetchall() if n else []
        c.execute("UPDATE sheets SET owner_id=?, list_id=? WHERE id=?", (heir, lid if lid and list_role(c, lid, heir) else None, sid))
        shf_after_move(c, sid)
        shk_move_files(c, sid, None, heir, new_paths, old_paths, strict=False)  # 2.528.0 (#4306 B25): a broken file never stops the deletion
        shb_move(c, sid, None, heir, new_paths, old_paths, strict=False)
        r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone()
        have = set()
        for s in keep:
            have.add(s["user_id"] or s["agent_id"])
            _sheet_put(c, heir, r, s["user_id"] or s["agent_id"], SHS_CARD.get(s["role"], "read"), s["expires_at"])
        for u, role in x["others"].items():  # a folder share of the deleted person's tree becomes a share of the table
            if u not in have:
                _sheet_put(c, heir, r, u, "write" if role == "edit" else "read")
        sh_touch(c, sid, heir)
    shs_drop_cache()


def _wiki(c, uid, items, new_paths, old_paths):
    by_heir = {}
    for x in items:
        by_heir.setdefault(x["heir"], []).append(x)
    for heir, group in by_heir.items():
        rows, others = [], {}
        for x in group:
            r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (x["id"],)).fetchone()
            if wsb_body_or(c, r, None) is None:  # a text that cannot be opened (its key is gone) goes with the account
                continue
            rows.append(r)
            others[x["id"]] = x["others"]
        if not rows:
            continue
        wkh_drop_unreadable(c, [r["id"] for r in rows])
        wkm_place(c, None, uid, heir, rows, new_paths, old_paths, strict=False)  # 2.528.0 (#4306 B25)
        WKF_SEEN.pop(f"u{int(heir)}", None)  # a deletion tried before and rolled back left this very state noted, without its nodes
        wkf_sync(c, heir, None)
        for pid, who in others.items():
            n = wkf_node_of(c, pid)
            if n is not None:  # 2.1017.0 (#5645, review F5): the lock of every fs_shares writer, buckets in order
                obj_share_locks(c, [(n["id"], u) for u in who])
            for u, role in who.items() if n is not None else ():
                insert_id(c, "INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (n["id"], u, role, heir, iso(now_utc())))


def _folders(c, uid, items, new_paths, old_paths, doomed=frozenset()):
    """2.537.0 (#4347): each branch of items (_fs_branches) into the top level of its heir's own tree; what is the deleted
    person's in it passes to the heir, its files sealed again for the heir's account (as files/fsmove.py fsm_apply does).
    2.631.0 (#4584): what stays: _branch_walk (the mail copies that go included)."""
    for x in items:
        nid, heir = x["id"], x["heir"]
        root = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if root is None or root["owner_id"] != uid or root["org_id"]:
            continue
        # review #4347: recognised documents go along (the retention took what it keeps out of the tree before, upg_personal)
        moved, _sub = _branch_walk(c, uid, root, doomed)  # a locked folder and what lies in it stays
        ids = sorted(r["id"] for r in moved)  # review #4347: in node order, as fs_purge (#3090), no deadlock with the recognition
        for i in range(0, len(ids), 500):  # as fsm_apply: no recognition starts on the moved files until the commit
            part = ids[i:i + 500]
            pq = ",".join("?" * len(part))
            if any(r[0] == "run" for r in c.execute(f"SELECT state FROM doc_meta WHERE node_id IN ({pq}) ORDER BY node_id FOR UPDATE", part).fetchall() +
                   c.execute(f"SELECT state FROM file_text WHERE kind='fs' AND node_id IN ({pq}) ORDER BY node_id FOR UPDATE", part).fetchall()):
                raise Denied(409, tr("A file is being recognised right now. Please try again in a moment."))
        ts, root_ok, done = _now(), False, []
        for r in moved:  # root first
            if r["owner_id"] != uid:
                continue  # somebody else's node in the branch (sealed for that account) stays theirs
            k, j = len(new_paths), len(old_paths)
            try:
                with c.savepoint():
                    if r["id"] == nid:
                        c.execute("UPDATE fs_nodes SET parent_id=NULL, name=?, owner_id=?, updated_at=? WHERE id=?",
                                  (_free_name(c, None, heir, None, root["name"], skip=nid), heir, ts, nid))
                    else:
                        c.execute("UPDATE fs_nodes SET owner_id=?, updated_at=? WHERE id=?", (heir, ts, r["id"]))
                    dt_move(c, r["id"], f"u{int(heir)}")  # tags by name into the heir's own
                    if r["kind"] == "file":  # review #4347: checked as the heir (lists, agents of the deleted person go)
                        fsm_doc(c, r["id"], None, heir, heir, r["name"], new_paths, old_paths, df_define=True)
                        fsm_versions(c, r["id"], fs_space(None, heir), new_paths, old_paths)
                        fsm_text(c, r["id"], None, heir)
            except (Denied, OSError, OrgCryptError) as e:  # a file that cannot be sealed again: it stays the deleted person's and goes (never stops the deletion)
                if isinstance(e, Denied) and e.code != 409 or r["id"] == nid and r["kind"] == "folder":
                    raise
                for f in new_paths[k:]:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                del new_paths[k:], old_paths[j:]
                print(f"account deletion: file {int(r['id'])} cannot be sealed again for the heir, it goes with the account (#4347): "
                      f"{type(e).__name__}", flush=True)
                continue
            done.append(r["id"])
            root_ok = root_ok or r["id"] == nid
        if not root_ok:
            continue
        stamp = iso(now_utc())
        for i in range(0, len(done), 500):
            part = done[i:i + 500]
            pq = ",".join("?" * len(part))
            c.execute(f"DELETE FROM fs_shares WHERE user_id=? AND node_id IN ({pq})", (heir, *part))  # the owner needs none
            # review #4347: into another owner's workspace, as fsm_apply: external links end, so do the file requests of others
            c.execute(f"""UPDATE fs_upload_requests SET revoked_at=? WHERE node_id IN ({pq}) AND created_by<>?
                          AND revoked_at IS NULL AND deleted_at IS NULL""", (stamp, *part, heir))
            # 2.644.0 (#4999): as a move into the heir's own space, the agents that do not belong there lose their share
            aids = {r[0] for r in c.execute(f"SELECT DISTINCT agent_id FROM fs_shares WHERE agent_id IS NOT NULL AND node_id IN ({pq})", part)}
            ends = sorted(aids - _heir_agents(c, aids, heir))
            if ends:
                c.execute(f"DELETE FROM fs_shares WHERE node_id IN ({pq}) AND agent_id IN ({','.join('?' * len(ends))})", (*part, *ends))
        xl_space_moved(c, done)
        live = "(expires_at IS NULL OR expires_at>?)"
        for col, want in (("user_id", x["others"]), ("group_id", x.get("groups") or {})):
            if not want:
                continue
            obj_share_locks(c, [(nid, k) for k in want])  # 2.1017.0 (#5645, review F5): before the check-then-write below
            # review #4347: an expired row of one who keeps a role is replaced (not raised and left expired)
            c.execute(f"DELETE FROM fs_shares WHERE node_id=? AND {col} IN ({','.join('?' * len(want))}) AND NOT {live}", (nid, *want, stamp))
            have = {r[0]: r[1] for r in c.execute(f"SELECT {col}, role FROM fs_shares WHERE node_id=? AND {col} IS NOT NULL AND {live}", (nid, stamp))}
            for k, role in want.items():  # who reached it through a folder above that goes keeps the role on the branch
                if k not in have:
                    insert_id(c, f"INSERT INTO fs_shares(node_id,{col},role,created_by,created_at) VALUES(?,?,?,?,?)", (nid, k, role, heir, stamp))
                elif role == "edit" and have[k] != "edit":
                    c.execute(f"UPDATE fs_shares SET role='edit' WHERE node_id=? AND {col}=? AND {live}", (nid, k, stamp))


def ush_hand_on(c, uid, new_paths, mail=None):
    """The deletion of account uid (users._user_purge, after the lists are settled, before its file store and its key go):
    everything of ush_plan with a heir passes to it. -> the stored files to remove after the commit. new_paths: the sealed
    copies made here are added, for the caller to remove if the deletion fails later on. The caller commits. mail: the
    (roots, ids) of ush_mail_doomed the caller purges after it (2.631.0 #4584: one look, the same set both times)."""
    uid = int(uid)
    doomed = mail[1] if mail is not None else _mail_doomed(c, uid)  # 2.631.0 (#4584): the mail copies that go right after (users._up_mail_nodes) are not handed on
    plan = {k: [x for x in v if x["heir"]] for k, v in ush_plan(c, uid, doomed).items()}
    old_paths = []
    with system_ctx(c):  # the rows of both people, whoever deletes the account
        _calendars(c, plan["calendars"])
        _books(c, plan["books"])
        _sheets(c, plan["sheets"], new_paths, old_paths)
        _wiki(c, uid, plan["wiki"], new_paths, old_paths)
        _folders(c, uid, plan["folders"], new_paths, old_paths, doomed)  # 2.537.0 (#4347): after the areas (their filed nodes went already)
    n = sum(len(v) for v in plan.values())
    if n:
        print(f"account deletion: {n} shared object(s) handed on (#4301)", flush=True)
    return old_paths
