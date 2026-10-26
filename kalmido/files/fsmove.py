"""2.96.0 A (#1941): files, folders (with everything in them) and documents to the other workspace (private <-> organisation).

POST /api/files/move-space {ids: [node ids], to, parent, dry} -- or {items: [{id, parent, name}], to} (the undo: every item
back to its old folder under its old name). parent: a folder of the target workspace, null = its top level, "docs" = its
documents folder (made when missing). The shared rules (target, agents, dry run) are in accounts/spacemove.py.

Rights: write on every chosen node; a private node only by its owner (a share does not let anybody carry someone else's
private files away); out of an organisation only what the person owns or uploaded, or everything as an admin of it; the
target folder needs the right to add there (files/store.py _place). What stays where it is: links to task / project files,
agent result folders and what lies in the trash -- inside a moved folder they move up to the top of the source workspace.
In ONE transaction: org_id / owner_id of the branch, every version sealed again with the target's key (new files, the old
ones are removed after the commit), shares and the opening to the whole organisation that do not hold in the target end,
the document data goes along into the target's workspace (senders / types / tags found or made there by name, text and
amount sealed again, the word index made again, the models of the source unlearn it, the preview sealed again), the
recognised text of plain files, the scan state, receipts (a project of the source workspace is dropped; open suggestions of
agents outside the target are dropped) and the Paperless origin (the source keeps a row without node: nothing comes in
twice there). The storage quota counts per uploader (admin/hosting.py): a move changes nothing there.
"""
import json
import os
import uuid
from datetime import date, timedelta

from flask import jsonify

from ..core.config import app, ATT_DIR
from ..core.db import body, bump, db, now_utc, parse_iso
from ..core.retention import ret_days, ret_on, ret_report  # 2.272.0 A (#3026)
from ..core.i18n import N_, short_day, tr, trn
from ..core.access import Denied
from ..core.orgcrypt import OrgCryptError, oc_active_for, oc_copy_file, oc_is_sealed_file, oc_write_file
from ..accounts.session import me
from ..accounts.spacemove import SMV_MAX, smv_answer, smv_refuse_agent, smv_same, smv_target
from .fstags import dt_move
from .store import FS_DIR, DEPTH_MAX, fs_chain, fs_height, fs_log_add, fs_space, fs_visible_sql_c, need_node, safe_fs_name, _free_name, _now, _place
from .fsroots import fs_area_need_stay, fs_area_root_need_free  # 2.199.0 (#2742, Fable review); 2.200.0 A (#2747)
from .fslock import fsl_space_guard  # 2.353.0 A (#2758)
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

_KEEP = object()   # an item without its own parent: the request's parent
_BAD = object()    # a sealed value that cannot be opened


def fsm_ws(org):
    return f"org:{int(org)}" if org else "private"


def fsm_items(b):
    """[(id, parent, name)] of the request: {ids, parent} or {items: [{id, parent, name}]} (the undo)."""
    out = []
    if isinstance(b.get("items"), list):
        for x in b["items"][:SMV_MAX]:
            if not isinstance(x, dict):
                raise Denied(400, tr("Invalid value: {0}", "items"))
            out.append((x.get("id"), x.get("parent") if "parent" in x else _KEEP, x.get("name")))
    else:
        ids = b.get("ids")
        if not isinstance(ids, list):
            raise Denied(400, tr("Invalid value: {0}", "ids"))
        out = [(x, _KEEP, None) for x in ids[:SMV_MAX]]
    try:
        out = [(int(i), p, safe_fs_name(str(n)) if n and str(n).strip() else None) for i, p, n in out]
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "ids")) from None
    if not out:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    return list({i: (i, p, n) for i, p, n in out}.values())


def fsm_parent(v):
    if v in (None, "", 0, "0"):
        return None
    if v == "docs":
        return "docs"
    try:
        return int(v)
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "parent")) from None


def fsm_walk(c, root):
    """(moved rows, staying rows) below root (root itself first in moved): links, agent folders and what is in the trash
    stay (with what lies below them)."""
    moved, stay, front = [root], [], [root["id"]]
    for _ in range(DEPTH_MAX + 1):
        if not front:
            break
        q = ",".join("?" * len(front))
        nxt = []
        for r in c.execute(f"SELECT * FROM fs_nodes WHERE parent_id IN ({q}) ORDER BY id", front).fetchall():
            if r["deleted_at"] or r["kind"] in ("link", "ref") or r["agent_id"]:  # 2.199.0 A (#2742): a filed object stays in its workspace
                stay.append(r)
            else:
                moved.append(r)
                if r["kind"] == "folder":
                    nxt.append(r["id"])
        front = nxt
    return moved, stay


def fsm_dest(c, uid, to, parent, is_file, dry):
    """(parent id | None, owner id) in the target workspace for one root (raises Denied when uid may not add there)."""
    if parent == "docs":
        from ..docs.store import doc_ws, root_folder, root_id
        parent = root_id(c, doc_ws(to, uid)) if dry else root_folder(c, uid, to)
    owner, org = _place(c, uid, parent, to, add_file=is_file)
    if (org or None) != (to or None) or (not to and owner != uid):
        raise Denied(409, tr("The folder is not in the target workspace"))
    return parent, owner


def fsm_agent_in(c, aid, to, uid):
    """Does agent aid belong to the target workspace (an organisation's agent / a private agent of uid or of nobody)?"""
    with system_ctx(c):  # the agent's workspace (structure: which accounts belong to the target workspace)
        a = c.execute("SELECT org_id, owner_id FROM agents WHERE user_id=?", (int(aid),)).fetchone()
    if not a:
        return False
    return a["org_id"] == to if to else (a["org_id"] is None and a["owner_id"] in (None, uid))


def fsm_share_ends(c, s, to, uid):
    """Does share row s end when its node moves into workspace `to`?"""
    if s["agent_id"]:
        return not fsm_agent_in(c, s["agent_id"], to, uid)
    if not to:
        return True  # the private space is the person's own: shares with people / groups end
    with system_ctx(c):  # membership of the target organisation (structure; ids only)
        if s["user_id"]:
            r = c.execute("""SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id=?
                             AND COALESCE(u.kind, '')!='agent'""", (to, s["user_id"])).fetchone()
            return r is None
        r = c.execute("""SELECT 1 FROM group_members g WHERE g.group_id=? AND NOT EXISTS
                         (SELECT 1 FROM org_members m WHERE m.org_id=? AND m.user_id=g.user_id) LIMIT 1""", (s["group_id"], to)).fetchone()
        return r is not None  # a group with someone outside the organisation
    return True


def fsm_share_gone(c, s):
    """2.273.0 F1 (#3042): memo share s cannot / need not come back: its group, person or agent no longer exists, or the node
    has that share already (fs_shares has no unique index)."""
    with system_ctx(c):
        for k, t in (("group_id", "groups"), ("user_id", "users"), ("agent_id", "users")):
            if s[k] and not c.execute(f"SELECT 1 FROM {t} WHERE id=?", (s[k],)).fetchone():
                return True
    return c.execute("""SELECT 1 FROM fs_shares WHERE node_id=? AND user_id IS NOT DISTINCT FROM ? AND group_id IS NOT DISTINCT FROM ?
                        AND agent_id IS NOT DISTINCT FROM ?""", (s["node_id"], s["user_id"], s["group_id"], s["agent_id"])).fetchone() is not None


def fsm_list_ok(c, lid, to, uid):
    """Is list lid (a receipt's project) one of the target workspace?"""
    if not lid:
        return False
    r = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    return bool(r) and (r["org_id"] == to if to else (r["org_id"] is None and r["owner_id"] == uid))


FSM_RECEIPT_STAYS = N_("Receipts of the cash book or of the equipment list stay in their workspace.")
FSM_BOOKED_STAYS = N_("A booked receipt stays in the books of its workspace: it is kept there by law until {0}.")


def fsm_plan(c, uid, b, to, dry):
    """Everything the move would do (no change): {roots: [(row, parent, owner, name)], moved, stay, notes, block, code}."""
    from ..accounts.orgs import is_org_admin
    from ..accounts.orgout import OO_ADMIN_ONLY, org_out_ok
    items = fsm_items(b)
    base = fsm_parent(b.get("parent"))
    chosen = {i for i, _, _ in items}
    roots, skipped, src = [], 0, _KEEP
    for nid, parent, name in items:
        n = need_node(c, nid, write=True)  # 404: not visible / in the trash, 403: no write right
        fs_area_root_need_free(c, nid)  # 2.199.0 (#2742, Fable review): an area's root folder stays in its workspace
        fs_area_need_stay(c, nid)  # 2.200.0 A (#2747): a closed area's folders move with the area only (knowledge: wkmove.py)
        fsl_space_guard(c, [nid])  # 2.353.0 A (#2758): the folder key belongs to its people: a locked folder stays in its space
        if src is not _KEEP and (src or None) != (n["org_id"] or None):
            raise Denied(400, tr("Choose items of one workspace"))
        src = n["org_id"] or None
        if any(r["id"] in chosen for r in fs_chain(c, nid)[1:]):
            continue  # inside a chosen folder: goes along with it
        if n["kind"] in ("link", "ref") or n["agent_id"]:  # 2.199.0 A (#2742)
            skipped += 1
            continue
        roots.append((n, base if parent is _KEEP else fsm_parent(parent), name))
    smv_same(src, to)
    admin = bool(src) and is_org_admin(c, uid, src)
    plan = {"roots": [], "moved": [], "stay": [], "src": src, "block": None, "code": 409}
    files = folders = size = shares = opened = 0
    for n, parent, name in roots:
        moved, stay = fsm_walk(c, c.execute("SELECT * FROM fs_nodes WHERE id=?", (n["id"],)).fetchone())
        plan.setdefault("root_of", {}).update({r["id"]: n["id"] for r in moved + stay})  # 2.273.0 B (#3042): for the memo
        if not plan["block"] and src and not org_out_ok(c, src, to):  # 2.148.1 B (#2483): out of an organisation only by its admin
            plan["block"], plan["code"] = tr(OO_ADMIN_ONLY), 403
        if not plan["block"] and not admin and any(r["owner_id"] != uid and not (src and r["created_by"] == uid)
                                                    for r in moved + stay):  # review 2.96 (L5): also what stays behind
            plan["block"], plan["code"] = (tr("Only the owner or an admin of the organisation can move this out of it") if src
                                           else tr("Only your own files can be moved to another workspace")), 403
        pid, owner = fsm_dest(c, uid, to, parent, n["kind"] == "file", dry)
        if pid and len(fs_chain(c, pid)) + 1 + fs_height(c, n["id"]) > DEPTH_MAX:
            raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
        plan["roots"].append((n, pid, owner, name))
        plan["moved"] += [(r, owner) for r in moved]
        plan["stay"] += stay
    ids = [r["id"] for r, _ in plan["moved"]]
    from ..office.periodlock import pl_receipt_need_open
    for r, _ in plan["moved"][:SMV_MAX]:
        if r["kind"] == "file":
            pl_receipt_need_open(c, r["id"])  # 2.148.0 A (#2471): a receipt of a locked month stays in its office's books
    for r, _ in plan["moved"]:
        if r["kind"] == "folder":
            folders += 1
        else:
            files += 1
            size += r["size"] or 0
        opened += 1 if r["org_access"] else 0
    if len(ids) > SMV_MAX:
        plan["block"] = plan["block"] or tr("Too many at once: at most {0}", SMV_MAX)
    if not ids:
        plan["block"] = plan["block"] or tr("Agent folders and links stay where they are")
    notes = []
    if ids:
        from ..admin.hosting import fmt_bytes
        notes.append(trn("{0} file, {1}", "{0} files, {1}", files, fmt_bytes(size)))
        if folders:
            notes.append(trn("{0} folder with everything in it", "{0} folders with everything in them", folders))
    big = ids[:SMV_MAX]
    q = ",".join("?" * len(big))
    if big and not plan["block"] and c.execute(f"""SELECT 1 FROM office_cash_entries WHERE node_id IN ({q}) UNION ALL
                            SELECT 1 FROM office_equipment WHERE receipt_node_id IN ({q}) LIMIT 1""", big + big).fetchone():
        # 2.148.1 B (#2483): receipts the cash book or the equipment list points to stay in their workspace
        plan["block"], plan["code"] = tr(FSM_RECEIPT_STAYS), 409
    if big and not plan["block"]:
        from ..receipts.suggest import olk_fs_locked
        for i in big:  # 2.186.0 B (#2600): a booked receipt stays in the books of its workspace for the legal period
            until = olk_fs_locked(c, i)
            if until:
                plan["block"], plan["code"] = tr(FSM_BOOKED_STAYS, short_day(date.fromisoformat(until), year=True)), 409
                break
    if big:
        docs = c.execute(f"SELECT COUNT(*) FROM doc_meta WHERE node_id IN ({q})", big).fetchone()[0]
        if c.execute(f"""SELECT 1 FROM doc_meta WHERE node_id IN ({q}) AND state='run' UNION ALL
                         SELECT 1 FROM file_text WHERE kind='fs' AND node_id IN ({q}) AND state='run' LIMIT 1""", big + big).fetchone():
            # the recognition seals its result with the workspace it started in: wait until it is through
            plan["block"] = plan["block"] or tr("A file is being recognised right now. Please try again in a moment.")
        if docs:
            notes.append(trn("{0} document: sender, type and tags go along", "{0} documents: sender, type and tags go along", docs))
        if src and not to and oc_active_for(c, src) and not oc_active_for(c, fs_space(None, uid)):
            # review 2.96 (L3): the organisation seals its files, the private space does not (private encryption is off)
            notes.append(tr("In your private space the files are stored without the organisation's encryption"))
        shas = [r[0] for r in c.execute(f"""SELECT v.sha256 FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND v.no=n.cur_version
                                             WHERE n.id IN ({q}) AND v.sha256<>''""", big)]
        if shas:
            sq = ",".join("?" * len(shas))
            where, args = ("n.org_id=?", [to]) if to else ("n.org_id IS NULL AND n.owner_id=?", [uid])
            dup = c.execute(f"""SELECT COUNT(DISTINCT v.sha256) FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND v.no=n.cur_version
                                WHERE v.sha256 IN ({sq}) AND n.deleted_at IS NULL AND {where}
                                AND n.id IN {fs_visible_sql_c(c, uid)}""", [*shas, *args]).fetchone()[0]  # only what the person can see (review 2.96)
            if dup:
                notes.append(trn("{0} file with the same content is already there", "{0} files with the same content are already there", dup))
        plan["ends"] = [s["id"] for s in c.execute(f"SELECT * FROM fs_shares WHERE node_id IN ({q})", big).fetchall()
                        if fsm_share_ends(c, s, to, uid)]
        shares = len(plan["ends"])
        if shares:
            notes.append(trn("{0} share ends (people, groups or agents outside the target)",
                             "{0} shares end (people, groups or agents outside the target)", shares))
        if opened:
            notes.append(trn("{0} opening to the whole organisation ends", "{0} openings to the whole organisation end", opened))
        lost = sum(1 for r in c.execute(f"SELECT list_id FROM rc_receipts WHERE node_id IN ({q}) AND list_id IS NOT NULL", big)
                   if not fsm_list_ok(c, r[0], to, uid))
        if lost:
            notes.append(trn("{0} receipt loses its project (projects stay in their workspace)",
                             "{0} receipts lose their project (projects stay in their workspace)", lost))
        from ..docs.store import doc_ws
        tws = doc_ws(to, uid)
        asn = c.execute(f"""SELECT COUNT(*) FROM doc_meta d WHERE d.node_id IN ({q}) AND d.asn IS NOT NULL AND EXISTS
                            (SELECT 1 FROM doc_meta x WHERE x.ws=? AND x.asn=d.asn)""", [*big, tws]).fetchone()[0]
        if asn:
            notes.append(trn("{0} archive number is taken there and is cleared", "{0} archive numbers are taken there and are cleared", asn))
    stays = skipped + len(plan["stay"])
    if stays:
        notes.append(trn("{0} item stays here (links, agent folders, the trash)", "{0} items stay here (links, agent folders, the trash)", stays))
    plan.update(notes=notes, files=files, folders=folders, size=size, shares=shares)
    return plan


def fsm_open(c, ws, ctx, value):
    from ..docs.store import doc_open
    v = doc_open(c, ws, ctx, value, default=_BAD)
    if v is _BAD:
        raise Denied(409, tr("A document cannot be opened with its key; nothing was moved"))
    return v


def fsm_versions(c, nid, sid, new_paths, old_paths):
    """Every version of file nid sealed for space sid as a new stored file (the old one is removed after the commit)."""
    for v in c.execute("SELECT id, path FROM fs_versions WHERE node_id=?", (nid,)).fetchall():
        src = os.path.join(ATT_DIR, v["path"])
        if not os.path.isfile(src) or (not oc_is_sealed_file(src) and not oc_active_for(c, sid)):
            continue  # missing, or plain and plain it stays
        rel = os.path.join(FS_DIR, str(int(nid)), uuid.uuid4().hex[:16])
        dst = os.path.join(ATT_DIR, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        new_paths.append(dst)
        try:
            oc_copy_file(c, src, dst, sid)
        except OrgCryptError:
            raise Denied(409, tr("A file cannot be opened with its key; nothing was moved")) from None
        c.execute("UPDATE fs_versions SET path=? WHERE id=?", (rel, v["id"]))
        old_paths.append(src)


def fsm_doc(c, nid, to, owner, uid, name, new_paths, old_paths, df_define=None):
    """The document data of node nid into the workspace of (to, owner). df_define: 2.184.0 B (#2580) docs/fields.py df_move."""
    from ..docs import store as S
    m = S.meta_row(c, nid)
    if not m:
        return
    old, new = m["ws"], S.doc_ws(to, owner)
    if old == new:
        return
    text = fsm_open(c, old, "doc_meta.text", m["text"]) or ""
    amount = fsm_open(c, old, "doc_meta.amount", m["amount"]) or ""
    summary = fsm_open(c, old, "doc_meta.summary", m["summary"]) or "" if "summary" in m.keys() else ""  # 2.126.1 A review (#2123)
    S.untrain(c, nid)  # the source's models forget it
    sender = S.label_name(c, old, "sender", m["sender_id"])
    typ = S.label_name(c, old, "type", m["type_id"])
    tags = S.node_tags(c, nid)
    asn = m["asn"] if m["asn"] and not S.asn_taken(c, new, m["asn"], nid) else None
    c.execute("""UPDATE doc_meta SET ws=?, org_id=?, text=?, amount=?, summary=?, sender_id=?, type_id=?, suggest='', trained='', asn=?, updated_at=?
                 WHERE node_id=?""",
              (new, to, S.doc_seal(c, new, "doc_meta.text", text), S.doc_seal(c, new, "doc_meta.amount", amount),
               S.doc_seal(c, new, "doc_meta.summary", summary) if summary else "",
               S.label_id(c, new, "sender", sender) if sender else None, S.label_id(c, new, "type", typ) if typ else None,
               asn, _now(), nid))
    if m["extracted"]:  # 2.121.0 A (#2092): the recognised receipt values move along, sealed for the new workspace
        S.meta_set_json(c, nid, new, "extracted", S.meta_json(c, m, "extracted", {}))
    # 2.153.0 (#2179): the custom field values go along (fields found / made by name and type in the target); the marks
    # "automatic" of the fields follow their new ids
    from ..docs.fields import df_move
    cf = df_move(c, nid, old, new, uid, define=df_define)
    auto = S.meta_json(c, m, "auto", {})
    if any(k.startswith("cf") for k in auto):
        S.meta_set_json(c, nid, new, "auto", {cf.get(k, k) if k.startswith("cf") else k: v for k, v in auto.items()
                                              if not k.startswith("cf") or k in cf})
    new_tags = {t["id"]: S.label_id(c, new, "tag", t["name"]) for t in tags}
    S.set_tags(c, nid, [x for x in new_tags.values() if x], {new_tags[t["id"]]: t["auto"] for t in tags if new_tags[t["id"]]})
    # 2.96.0 (#1941): the target's models learn the document at once (sender, type, folder, tags as
    # they are now); train() writes `trained` for the new ws, so a later correction or move takes exactly this out again
    S.train(c, nid)
    if m["thumb"]:
        c.execute("UPDATE doc_meta SET thumb=NULL WHERE node_id=?", (nid,))
        src = os.path.join(ATT_DIR, m["thumb"])
        try:
            jpg = S.thumb_read(c, old, src)
            rel = os.path.join(S.THUMB_DIR, f"{int(nid)}-{uuid.uuid4().hex[:10]}.jpg")
            dst = os.path.join(ATT_DIR, rel)
            new_paths.append(dst)
            if to:
                oc_write_file(c, to, dst, jpg)
            else:
                from ..core.orgcrypt import _write_atomic
                _write_atomic(dst, S.thumb_seal(c, new, jpg))
            c.execute("UPDATE doc_meta SET thumb=? WHERE node_id=?", (rel, nid))
            old_paths.append(src)  # 2.273.0 B (#3051): the old preview goes only once the new one is written
        except (OSError, OrgCryptError):
            pass  # no preview: the documents view shows the placeholder (docs/thumbfill.py makes it again)
    S.doc_index(c, nid, new, S.index_text(c, dict(S.meta_row(c, nid)), name, text))
    for r in c.execute("SELECT * FROM rc_receipts WHERE node_id=?", (nid,)).fetchall():
        c.execute("UPDATE rc_receipts SET ws=?, org_id=?, list_id=? WHERE node_id=?",
                  (new, to, r["list_id"] if fsm_list_ok(c, r["list_id"], to, uid) else None, nid))
    for r in c.execute("SELECT * FROM rc_suggest WHERE node_id=?", (nid,)).fetchall():
        if r["state"] == "open" and not fsm_agent_in(c, r["agent_id"], to, uid):
            c.execute("DELETE FROM rc_suggest WHERE id=?", (r["id"],))  # an agent outside the target never sees it again
            continue
        note = fsm_open(c, old, "rc_suggest.note", r["note"]) or ""
        amt = fsm_open(c, old, "rc_suggest.amount", r["amount"]) or ""  # 2.121.0 C (#2096)
        pamt = fsm_open(c, old, "rc_suggest.prev_amount", r["prev_amount"])
        c.execute("UPDATE rc_suggest SET amount=?, prev_amount=? WHERE id=?",
                  (S.doc_seal(c, new, "rc_suggest.amount", amt), S.doc_seal(c, new, "rc_suggest.prev_amount", pamt), r["id"]))
        c.execute("UPDATE rc_suggest SET ws=?, org_id=?, note=?, list_id=?, prev_list_id=? WHERE id=?",
                  (new, to, S.doc_seal(c, new, "rc_suggest.note", note),
                   r["list_id"] if fsm_list_ok(c, r["list_id"], to, uid) else None,
                   r["prev_list_id"] if fsm_list_ok(c, r["prev_list_id"], to, uid) else None, r["id"]))
    for r in c.execute("SELECT * FROM pl_imported WHERE node_id=?", (nid,)).fetchall():
        # the Paperless origin goes along; the source keeps its row without the node, so a later import there skips it
        c.execute("""INSERT INTO pl_imported(ws,src,pl_id,org_id,node_id,sha256,asn,dup,created_at) VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT (ws, src, pl_id) DO UPDATE SET node_id=excluded.node_id, org_id=excluded.org_id
                     WHERE pl_imported.node_id IS NULL""",
                  (new, r["src"], r["pl_id"], to, nid, r["sha256"], r["asn"], r["dup"], r["created_at"]))
        c.execute("UPDATE pl_imported SET node_id=NULL WHERE ws=? AND src=? AND pl_id=?", (r["ws"], r["src"], r["pl_id"]))
    from ..office.einvoice_in import ei_receipt_late
    ei_receipt_late(c, nid)  # 2.185.0 A (#2583): an e-invoice moved into the documents of an office becomes a receipt there


def fsm_text(c, nid, to, owner):
    """The recognised text of a plain file (files/textscan.py) into the new workspace: sealed again, index made again
    (a text that cannot be opened is recognised again by the queue)."""
    from ..docs import store as S
    from .textscan import _index
    new = S.doc_ws(to, owner)
    for r in c.execute("SELECT id, ws, text FROM file_text WHERE kind='fs' AND node_id=?", (nid,)).fetchall():
        if r["ws"] == new:
            continue
        v = S.doc_open(c, r["ws"], "file_text.text", r["text"], default=_BAD)
        if v is _BAD:
            c.execute("""UPDATE file_text SET state='wait', tries=0, error='', method='', text='', pages=0, truncated=0, sha256='',
                         org_id=?, ws=?, updated_at=? WHERE id=?""", (to, new, _now(), r["id"]))
            c.execute("DELETE FROM file_words WHERE ft_id=?", (r["id"],))
            continue
        c.execute("UPDATE file_text SET ws=?, org_id=?, text=?, updated_at=? WHERE id=?",
                  (new, to, S.doc_seal(c, new, "file_text.text", v or ""), _now(), r["id"]))
        _index(c, r["id"], new, v or "")


# 2.273.0 B (#3042): what a move into another workspace ends (shares, openings to the organisation, the project of a receipt)
# and where the items that stay behind lay (the trash below a moved folder goes to the top of the source) are kept per moved
# item (space_moves kind 'files', obj_id = the item); moving it back (the undo step) within FSM_KEEP_H hours brings that back
# where it still fits the workspace.
FSM_KEEP_H = 24


def fsm_memo(c, plan, to, uid):
    """Notes the memo of each moved item before the move writes (one space_moves row per item that loses something)."""
    ends, src, per = set(plan.get("ends") or []), plan["src"], {}
    rof = plan.get("root_of") or {}
    ids = [r["id"] for r, _ in plan["moved"]]

    def at(nid):
        return per.setdefault(rof.get(nid, nid), {"access": {}, "shares": [], "receipts": {}, "under": []})
    for r, _ in plan["moved"]:
        if r["org_access"]:
            at(r["id"])["access"][str(r["id"])] = r["org_access"]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for x in c.execute(f"SELECT * FROM fs_shares WHERE node_id IN ({q})", part).fetchall():
            if x["id"] in ends:
                at(x["node_id"])["shares"].append({k: x[k] for k in ("node_id", "user_id", "group_id", "agent_id", "role", "expires_at",
                                                                      "created_by", "created_at")})
        for x in c.execute(f"SELECT node_id, list_id FROM rc_receipts WHERE node_id IN ({q}) AND list_id IS NOT NULL", part).fetchall():
            if not fsm_list_ok(c, x["list_id"], to, uid):
                at(x["node_id"])["receipts"][str(x["node_id"])] = x["list_id"]
    for r in plan["stay"]:
        at(r["id"])["under"].append([r["id"], r["parent_id"], r["name"]])
    for rid, d in per.items():
        if any(d.values()):
            c.execute("INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('files',?,?,?,?,?,?)",
                      (rid, src, to, uid, _now(), json.dumps(d, separators=(",", ":"), default=str)))


def fsm_memo_back(c, plan, to, uid):
    """The memos of the items of this move that went from `to` to the source within FSM_KEEP_H hours: [(id, detail)]."""
    out = []
    for n, _, _, _ in plan["roots"]:
        m = c.execute("SELECT id, at, from_org, to_org, detail FROM space_moves WHERE kind='files' AND obj_id=? ORDER BY id DESC LIMIT 1",
                      (n["id"],)).fetchone()
        if not m or (m["from_org"] or None) != (to or None) or (m["to_org"] or None) != (plan["src"] or None):
            continue
        try:
            d = json.loads(m["detail"])
            if d.get("restored") or parse_iso(m["at"]) < now_utc() - timedelta(hours=FSM_KEEP_H):
                continue
        except (TypeError, ValueError):
            continue
        out.append((m["id"], d))
    return out


def fsm_memo_apply(c, back, to, uid):
    """After the move back: the memos' shares (that fit `to`), openings, receipt projects and items under the folders again.
    -> how many came back."""
    n = 0
    for mid, d in back:
        for nid, oa in (d.get("access") or {}).items():
            if to:
                n += c.execute("UPDATE fs_nodes SET org_access=? WHERE id=? AND org_id=? AND org_access=''", (oa, int(nid), to)).rowcount
        for x in d.get("shares") or []:
            node = c.execute("SELECT org_id FROM fs_nodes WHERE id=?", (x["node_id"],)).fetchone()
            if node and (node["org_id"] or None) == (to or None) and not fsm_share_ends(c, x, to, uid):
                if fsm_share_gone(c, x):  # 2.273.0 F1 (#3042): its group / person deleted since, or the same share is there again
                    continue
                c.execute("INSERT INTO fs_shares(node_id,user_id,group_id,agent_id,role,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          (x["node_id"], x["user_id"], x["group_id"], x["agent_id"], x["role"], x["expires_at"], x["created_by"], x["created_at"]))
                n += 1
        for nid, lid in (d.get("receipts") or {}).items():
            if fsm_list_ok(c, lid, to, uid):
                n += c.execute("UPDATE rc_receipts SET list_id=? WHERE node_id=? AND list_id IS NULL", (lid, int(nid))).rowcount
        for nid, pid, name in d.get("under") or []:  # still at the top of the folder's workspace (and owner when private)
            p = c.execute("SELECT org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (pid,)).fetchone() if pid else None
            r = c.execute("SELECT parent_id, org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (nid,)).fetchone()
            if p and r and not p["deleted_at"] and r["parent_id"] is None and (r["org_id"] or None) == (p["org_id"] or None) \
                    and (p["org_id"] or r["owner_id"] == p["owner_id"]):
                nm = name if r["deleted_at"] else _free_name(c, pid, r["owner_id"], p["org_id"], name, skip=nid)
                c.execute("UPDATE fs_nodes SET parent_id=?, name=? WHERE id=?", (pid, nm, nid))
                n += 1
        d["restored"] = _now()
        c.execute("UPDATE space_moves SET detail=? WHERE id=?", (json.dumps(d, separators=(",", ":"), default=str), mid))
    return n


def _rm(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


@app.post("/api/files/move-space")
def files_move_space():
    """{ids, to: private | org:<id>, parent?: folder id | null (top level) | "docs", dry?} or {items: [{id, parent, name}], to}:
    move files and folders (with everything in them) and documents into the other workspace. dry = only the check."""
    smv_refuse_agent()
    c = db()
    uid = me()
    b = body()
    dry = b.get("dry") in (1, True, "1", "true")
    to = smv_target(c, uid, b.get("to"))
    plan = fsm_plan(c, uid, b, to, dry)
    if dry:
        return jsonify(smv_answer(plan["notes"], plan["block"], files=plan["files"], folders=plan["folders"], size=plan["size"],
                                  shares=plan["shares"]))
    if plan["block"]:
        c.rollback()  # a documents folder the plan made
        raise Denied(plan["code"], plan["block"])
    src, ts = plan["src"], _now()
    new_paths, old_paths, out = [], [], []
    try:
        from ..accounts.orgout import org_out  # 2.148.1 B (#2483): logged, the organisation's other admins told
        org_out(c, src, to, "file", ", ".join(n["name"] for n, _, _, _ in plan["roots"]))
        ids = [r["id"] for r, _ in plan["moved"]]
        for i in range(0, len(ids), 500):  # the recognition queues skip locked rows: none starts until the commit
            part = ids[i:i + 500]
            q = ",".join("?" * len(part))
            if any(r[0] == "run" for r in c.execute(f"SELECT state FROM doc_meta WHERE node_id IN ({q}) FOR UPDATE", part).fetchall() +
                   c.execute(f"SELECT state FROM file_text WHERE kind='fs' AND node_id IN ({q}) FOR UPDATE", part).fetchall()):
                raise Denied(409, tr("A file is being recognised right now. Please try again in a moment."))
        back = fsm_memo_back(c, plan, to, uid)  # 2.273.0 B (#3042): a move back first takes the memo of the move out
        fsm_memo(c, plan, to, uid)
        for s in plan.get("ends") or []:
            c.execute("DELETE FROM fs_shares WHERE id=?", (s,))
        for r in plan["stay"]:  # up to the top of the source workspace (in the trash: restored there)
            nm = r["name"] if r["deleted_at"] else _free_name(c, None, r["owner_id"], src, r["name"], skip=r["id"])
            c.execute("UPDATE fs_nodes SET parent_id=NULL, name=? WHERE id=?", (nm, r["id"]))
        names = {}
        for n, pid, owner, name in plan["roots"]:
            out.append({"id": n["id"], "parent_was": n["parent_id"], "org_was": src, "name_was": n["name"]})
            names[n["id"]] = _free_name(c, pid, owner, to, name or n["name"], skip=n["id"])
            c.execute("UPDATE fs_nodes SET parent_id=?, name=?, org_id=?, owner_id=?, org_access='', updated_at=? WHERE id=?",
                      (pid, names[n["id"]], to, owner, ts, n["id"]))
        for r, owner in plan["moved"]:
            nm = names.get(r["id"], r["name"])
            if r["id"] not in names:
                c.execute("UPDATE fs_nodes SET org_id=?, owner_id=?, org_access='', updated_at=? WHERE id=?", (to, owner, ts, r["id"]))
            dt_move(c, r["id"], f"o{to}" if to else f"u{owner}")  # 2.122.0 B (#2099): tags of files / folders go along by name
            if r["kind"] == "file":
                fsm_doc(c, r["id"], to, owner, uid, nm, new_paths, old_paths)
                fsm_versions(c, r["id"], fs_space(to, owner), new_paths, old_paths)
                fsm_text(c, r["id"], to, owner)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            c.execute(f"UPDATE upload_scan SET org_id=? WHERE kind='fs' AND ref_id IN ({','.join('?' * len(part))})", [to, *part])
            # 2.353.0 F (#2758, review M5): the row of an earlier (now open) lock goes along (a locked one never moves: fsl_space_guard)
            c.execute(f"UPDATE fs_locks SET org_id=? WHERE node_id IN ({','.join('?' * len(part))})", [to, *part])
        for n, _, _, _ in plan["roots"]:
            fs_log_add(c, n["id"], "moved_space", f"{fsm_ws(src)}->{fsm_ws(to)}")
        from .extlinks import xl_space_moved
        xl_space_moved(c, ids)  # 2.112.1 B (#2058): external links end with the move into another workspace
        restored = fsm_memo_apply(c, back, to, uid)
        bump(c)
        c.commit()
    except BaseException:
        c.rollback()
        _rm(new_paths)
        raise
    _rm(old_paths)
    return jsonify(moved=out, org_was=src, to=fsm_ws(to), count=len(plan["moved"]), shares=plan["shares"], restored=restored)


# 2.97.0 D (#2051): a move removes the old sealed versions only after its commit; a crash in between leaves files without a
# row in fs_versions. The watchdog compares <ATT_DIR>/files/<node>/ with fs_versions once a night (a round of at most
# FSM_GC_BATCH node folders per tick until every folder was seen) and removes what no row names and is older than a day
# (an upload writes its file before its row). Only regular files directly inside such a folder below the data directory.
FSM_GC_BATCH = 200
FSM_GC_AGE = 86400
FSM_GC = {"at": 0.0, "after": -1, "n": 0}


def fsm_orphans_gc(c):
    """2.272.0 A (#3026): like every retention run only with ret_on("files") (off = count), files older than
    max(1 day, ret_days("files")); the round's number goes to ret_report(run="fs_orphans") when the round is done."""
    import time
    purge = ret_on("files")
    every = float(os.environ.get("KALMIDO_FS_GC_EVERY") or 86400)
    if FSM_GC["after"] < 0:
        if time.time() - FSM_GC["at"] < every:
            return 0
        FSM_GC["at"], FSM_GC["after"], FSM_GC["n"] = time.time(), 0, 0
    root = os.path.realpath(os.path.join(ATT_DIR, FS_DIR))
    if not os.path.isdir(root):
        FSM_GC["after"] = -1
        return 0
    nids = sorted(int(d) for d in os.listdir(root) if d.isdigit() and int(d) > FSM_GC["after"])[:FSM_GC_BATCH]
    FSM_GC["after"] = nids[-1] if len(nids) == FSM_GC_BATCH else -1  # -1: the round is done
    n, old = 0, time.time() - max(FSM_GC_AGE, ret_days("files") * 86400)
    for nid in nids:
        d = os.path.join(root, str(nid))
        if os.path.islink(d) or not os.path.isdir(d):
            continue
        with system_ctx(c):  # the stored paths of a node of any workspace (paths only, no content is read)
            known = {r[0] for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (nid,))}
        for fn in os.listdir(d):
            full = os.path.join(d, fn)
            rel = os.path.join(FS_DIR, str(nid), fn)
            if (rel in known or os.path.islink(full) or not os.path.isfile(full) or os.path.getmtime(full) > old
                    or os.path.dirname(os.path.realpath(full)) != d):
                continue
            with system_ctx(c):  # another table naming the same stored file (paths only)
                if c.execute("SELECT 1 FROM attachments WHERE path=? UNION ALL SELECT 1 FROM list_files WHERE path=? "
                             "UNION ALL SELECT 1 FROM fs_versions WHERE path=? LIMIT 1", (rel, rel, rel)).fetchone():
                    continue
            if not purge:  # 2.272.0 A (#3026): dry run
                n += 1
                continue
            try:
                os.remove(full)
                n += 1
            except OSError:
                pass
    c.rollback()
    if n and purge:
        print(f"files cleanup: {n} stored file(s) without a version removed", flush=True)
    FSM_GC["n"] += n
    if FSM_GC["after"] < 0:  # the round is done: its number once
        ret_report(c, "files", {"fs_orphans": FSM_GC["n"]}, purge, run="fs_orphans")
        c.commit()
    return n
