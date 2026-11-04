"""#4300: locked folders of the file store (files/fslock.py) in an account or organisation import. What moves: the lock, the
importing person's own wrapped folder key (protected like the key bundle: only the person's private key opens it) and the old ids
the ciphertexts are bound to (fs_locks.aad_folder, fs_lock_keys.aad_r / aad_w). A folder opens on the target only when that copy
was wrapped for the key pair the person has there. Without it nobody could ever read the ciphertexts, so they stay out -- never as
nodes with cipher names -- and the preview and the result say which folders. Plain rows of a folder in mid-switch are ordinary files."""

from ..collab.e2e import _pub
from ..core.i18n import N_

OIL_NODES, OIL_LOCKS, OIL_KEYS = "store/nodes.json", "store/locks.json", "store/lock_keys.json"
OIL_MODES = ("encrypting", "on", "decrypting")
OIL_NAMES_MAX, OIL_NAME_LEN, OIL_DEPTH_MAX = 5, 100, 200


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def oil_plan(nodes, locks, keys, pub):
    """nodes / locks / keys = the archive's rows, pub = the key pair (JSON, core of e2e._pub) the person has on the target or None.
    -> {keep: lock folder ids that open, gone: lock folder ids that do not, drop: node ids that stay out}."""
    rows = {_int(n.get("id")): n for n in nodes if isinstance(n, dict) and _int(n.get("id"))}
    locked = {_int(r.get("node_id")): r for r in locks if isinstance(r, dict) and r.get("e2e") in OIL_MODES}
    fits = set()
    for k in keys:
        if not isinstance(k, dict) or not pub or _pub(k.get("recipient_pub")) != pub:
            continue
        r = locked.get(_int(k.get("node_id")))
        if r is not None and k.get("gen") == r.get("e2e_gen"):
            fits.add(_int(k.get("node_id")))
    keep = {i for i in fits if i in rows and rows[i].get("kind") == "folder"}
    gone, drop = {i for i in locked if i in rows and i not in keep}, set()

    def gen(n):
        return n.get("e2e_gen") if _int(n.get("e2e_gen")) else 0

    for i, n in rows.items():
        if not gen(n):
            continue
        top, at, seen = None, i, {i}  # the lock above; an older archive has no lock rows: the nearest plain folder stands for it
        while at not in locked and len(seen) < OIL_DEPTH_MAX:  # a file's rows: no loop, no chain of any length
            up = _int(rows[at].get("parent_id"))
            if up not in rows or up in seen:
                break
            at = up
            seen.add(up)
            if top is None and not gen(rows[up]):
                top = up
        top = at if at in locked else top if top is not None else at
        if top not in keep:
            drop.add(i)
            gone.add(top)
    return {"keep": keep, "gone": gone, "drop": drop, "names": [rows[i]["name"][:OIL_NAME_LEN] for i in sorted(gone)
                                                                if isinstance(rows[i].get("name"), str) and not rows[i]["name"].startswith("e2e1:")]}


def oil_own_pub(c, uid):
    r = c.execute("SELECT pub FROM e2e_keys WHERE user_id=?", (uid,)).fetchone()
    return _pub(r[0]) if r else None


def oil_preview(c, uid, nodes, locks, keys, pub=None):
    """The preview's numbers. pub: the pair the person will have after this import (the file's, when it is taken over)."""
    p = oil_plan(nodes or [], locks or [], keys or [], pub or oil_own_pub(c, uid))
    return {"locked_folders": len(p["keep"]), "locked_folders_lost": len(p["gone"]), "locked_folders_lost_names": p["names"][:OIL_NAMES_MAX]}


def oil_prepare(c, run, uid, oi):
    """oi_write, before the areas: what stays out leaves the archive's rows here, named once in one warning (the areas would
    count the versions of a left-out file as "missing"). -> the plan (run.oil), read by the areas' prep."""
    nodes = oi.get(OIL_NODES) or []
    locks, keys = oi.get(OIL_LOCKS) or [], oi.get(OIL_KEYS) or []
    run.oil = None
    if not locks and not any(isinstance(n, dict) and _int(n.get("e2e_gen")) for n in nodes):
        return None
    p = run.oil = oil_plan(nodes, locks, keys, oil_own_pub(c, uid))
    if p["drop"]:
        oi[OIL_NODES] = [n for n in nodes if not (isinstance(n, dict) and _int(n.get("id")) in p["drop"])]
        for path in ("store/versions.json", "store/shares.json", "store/history.json"):
            if oi.get(path):
                oi[path] = [r for r in oi[path] if not (isinstance(r, dict) and _int(r.get("node_id")) in p["drop"])]
    oi[OIL_LOCKS] = [r for r in locks if isinstance(r, dict) and _int(r.get("node_id")) in p["keep"]]
    oi[OIL_KEYS] = [r for r in keys if isinstance(r, dict) and _int(r.get("node_id")) in p["keep"]]
    if p["gone"]:
        run.warning(N_("Locked folders that stay out, the folder key in the export does not fit your encryption keys here: {0}. Unlock them on the old server and export again, or import into an account with the same keys."),
                    ", ".join(p["names"][:OIL_NAMES_MAX]) or str(len(p["gone"])))
    if p["keep"]:
        run.warning(N_("Locked folders taken over: {0}. They open with your passphrase from before."), str(len(p["keep"])))
    return p


def oil_lock(run, src, d, uid):
    """prep of a fs_locks row: only a folder of the plan, the old folder id stays in its bindings."""
    p, sid = getattr(run, "oil", None), _int(src.get("node_id"))
    if not p or sid not in p["keep"] or not _int(src.get("e2e_gen")) or src.get("e2e") not in OIL_MODES:
        return False
    d["aad_folder"] = _int(src.get("aad_folder")) or sid
    d["e2e_by"] = uid
    return d


def oil_key(c, run, src, d, uid):
    """prep of a fs_lock_keys row: the copy for the person's key pair, for the person, with the ids of its bindings. A copy another
    person wrapped has no wrapper on the target (wrapped_by NULL), the browser reads wrapper_pub and aad_w."""
    from ..collab.e2e import e2e_blob
    from ..files.fslock import FSL_WRAP_MAX
    p, sid = getattr(run, "oil", None), _int(src.get("node_id"))
    if not p or sid not in p["keep"] or _pub(src.get("recipient_pub")) != oil_own_pub(c, uid):
        return False
    wrapped, wpub = e2e_blob(src.get("wrapped"), FSL_WRAP_MAX), _pub(src.get("wrapper_pub"))
    r, w = _int(src.get("aad_r")), _int(src.get("aad_w"))
    if not wrapped or not wpub or not r or not w:
        return None
    d.update(user_id=uid, wrapped=wrapped, wrapper_pub=wpub, aad_r=r, aad_w=w, wrapped_by=uid if r == w else None)
    return d


def oil_export_keys(c, where, args):
    """The rows of the person's own folder keys for an export (where: on fs_lock_keys k joined with fs_locks l), with what the
    import needs: the ids of the bindings, the key pair they were wrapped for."""
    return [dict(r) for r in c.execute(
        f"""SELECT k.node_id, k.gen, k.wrapped, k.wrapper_pub, k.created_at, COALESCE(k.aad_r, k.user_id) AS aad_r,
                   COALESCE(k.aad_w, k.wrapped_by) AS aad_w, (SELECT e.pub FROM e2e_keys e WHERE e.user_id=k.user_id) AS recipient_pub
            FROM fs_lock_keys k JOIN fs_locks l ON l.node_id=k.node_id WHERE l.e2e IS NOT NULL AND {where} ORDER BY k.node_id, k.gen""", args)]


