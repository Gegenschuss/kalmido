"""2.96.0 B (#1941): wiki pages and folders (with their sub-pages) to the other workspace (private <-> organisation).

POST /api/wiki/move-space {pages: [id …] | folder: "<path>", space: <the source space>, to, dest: "<folder in the target>" | "",
dry} -- a page keeps its name, a folder its last part and everything below it: the path in the target = dest + that rest.
The rules of accounts/spacemove.py: agents never (403; they have no wiki access anyway), the target an organisation the person
is a member of (409), out of an organisation only pages the person created, or as that organisation's admin (403). A name
taken in the target = 409 with the names (the dry run: block). [[links]] between pages that move together follow the new
paths; links between a moved page and one that stays are kept as text and named in the dry run. Pages link files of the
file store only by URL: the files stay where they are (named). A space with the lock (wiki/wikie2e.py): the server cannot
re-encrypt for the other space -- 2.97.0 D (#2050): the browser does it (wkr_move below). Every page gets a row in
space_moves (its history).
"""
import json
import re

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso_ms, now_utc
from ..core.i18n import N_, tr, trn
from ..core.pg import IntegrityError
from ..core.access import Denied
from ..accounts.session import me
from ..accounts.orgs import is_org_admin
from ..accounts.spacemove import SMV_MAX, smv_answer, smv_refuse_agent, smv_same, smv_target
from ..personal.timetrack import BadInput
from .pages import wiki_clean_path, wiki_need, wiki_set_links, wiki_space, wiki_space_key, wiki_space_sql

WKM_FILE_RE = re.compile(r"/api/files/|/f/[A-Za-z0-9_-]{8,}|/s/[A-Za-z0-9_-]{8,}")


def wkm_like(p):
    return p.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"


def wkm_rows(c, uid, src, b):
    """[(row, rest)] of the pages that move: rest = the part of the path kept below dest."""
    w, a = wiki_space_sql(src, uid)
    if b.get("folder") not in (None, ""):
        f = wiki_clean_path(b.get("folder"))
        rows = c.execute(f"SELECT * FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND (lower(path)=? OR lower(path) ILIKE ? ESCAPE '\\') "
                         f"ORDER BY lower(path) LIMIT {SMV_MAX + 1}", [*a, f.lower(), wkm_like(f)]).fetchall()
        cut = len(f) - len(f.split("/")[-1])  # the folder keeps its own name
        out = [(r, r["path"][cut:]) for r in rows]
    else:
        ids = b.get("pages")
        if not isinstance(ids, list) or not ids or any(isinstance(x, bool) or not isinstance(x, int) for x in ids):
            raise BadInput(tr("Invalid value: {0}", "pages"))
        if len(ids) > SMV_MAX:
            raise BadInput(tr("Too many pages (at most {0})", SMV_MAX))
        out = []
        for pid in dict.fromkeys(ids):
            r = wiki_need(c, pid, write=True)
            if (r["org_id"] or None) != (src or None) or (not src and r["owner_id"] != uid):
                raise Denied(404)
            out.append((r, r["path"].split("/")[-1]))
    if not out:
        raise Denied(404)
    if len(out) > SMV_MAX:
        raise BadInput(tr("Too many pages (at most {0})", SMV_MAX))
    return out


def wkm_relink(text, ren):
    """[[old]] -> [[new]] for the paths of ren {old lower: new} (also [[old|label]] and [[old#part]])."""
    if not ren or not text:
        return text
    rx = re.compile(r"\[\[\s*(" + "|".join(re.escape(k) for k in sorted(ren, key=len, reverse=True)) + r")\s*(?=[\]|#])", re.I)
    return rx.sub(lambda m: "[[" + ren[m.group(1).lower()], text)


@app.post("/api/wiki/move-space")
def wiki_move_space():
    smv_refuse_agent()
    c = db()
    uid = me()
    b = body()
    src = wiki_space(c, uid, b.get("space"), write=True)
    to = smv_target(c, uid, b.get("to"))
    smv_same(src, to)
    dry = bool(b.get("dry"))
    from .wikie2e import wke_mode
    if wke_mode(c, src, uid)[0] or wke_mode(c, to, uid)[0]:
        return wkr_move(c, uid, src, to, b, dry)  # 2.97.0 D (#2050): a space with the lock -- the browser re-encrypts
    rows = wkm_rows(c, uid, src, b)
    if src and not is_org_admin(c, uid, src) and any(r["created_by"] != uid for r, _ in rows):
        raise Denied(403, tr("Only who created these pages or an admin of the organisation can move them out of it"))
    dest = b.get("dest") or ""
    dest = wiki_clean_path(dest) if dest else ""
    moves = [(r, wiki_clean_path(dest + "/" + rest if dest else rest)) for r, rest in rows]
    tw, ta = wiki_space_sql(to, uid)
    seen, taken = set(), []
    for _, n in moves:
        k = n.lower()
        if k in seen or c.execute(f"SELECT 1 FROM wiki_pages WHERE deleted_at IS NULL AND {tw} AND lower(path)=?", [*ta, k]).fetchone():
            taken.append(n)
        seen.add(k)
    ids = [r["id"] for r, _ in moves]
    ren = {r["path"].lower(): n for r, n in moves}
    q = ",".join("?" * len(ids))
    qp = ",".join("?" * len(ren))
    out_links = c.execute(f"SELECT COUNT(*) FROM wiki_links WHERE from_id IN ({q}) AND to_path IS NOT NULL AND to_path NOT IN ({qp})",
                          [*ids, *ren]).fetchone()[0]
    sw, sa = wiki_space_sql(src, uid)
    in_links = c.execute(f"SELECT COUNT(*) FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_path IN ({qp}) "
                         f"AND p.deleted_at IS NULL AND p.id NOT IN ({q}) AND p.{sw.replace(' AND ', ' AND p.')}",
                         [*ren, *ids, *sa]).fetchone()[0]
    files = sum(1 for r, _ in moves if WKM_FILE_RE.search(r["body"] or ""))
    notes = [trn("{0} page moves", "{0} pages move", len(moves)),
             trn("{0} link points to the other workspace (it stays as text)", "{0} links point to the other workspace (they stay as text)",
                 out_links + in_links) if out_links + in_links else "",
             trn("{0} page links files of the file store: the files stay in the old workspace",
                 "{0} pages link files of the file store: the files stay in the old workspace", files) if files else ""]
    block = tr("A page with this name already exists") + ": " + ", ".join(taken[:5]) if taken else None
    if dry:
        return jsonify(smv_answer(notes, block, count=len(moves), taken=taken[:20]))
    if taken:
        return jsonify(error=tr("A page with this name already exists"), taken=taken[:20]), 409
    ts = iso_ms(now_utc())
    try:
        with c.savepoint():
            for r, n in moves:
                c.execute("UPDATE wiki_pages SET org_id=?, owner_id=?, path=?, updated_by=?, updated_at=? WHERE id=?",
                          (to, None if to else uid, n, uid, ts, r["id"]))
    except IntegrityError:
        return jsonify(error=tr("A page with this name already exists"), taken=[]), 409
    relinked = 0
    for r, n in moves:
        nb = wkm_relink(r["body"], {k: v for k, v in ren.items() if k != v})
        if nb != r["body"]:
            c.execute("UPDATE wiki_pages SET body=? WHERE id=?", (nb, r["id"]))
            relinked += 1
        wiki_set_links(c, r["id"], nb)
        c.execute("INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('wiki',?,?,?,?,?,?)",
                  (r["id"], src, to, uid, ts, json.dumps({"from": r["path"], "to": n}, ensure_ascii=False)))
    bump(c)
    c.commit()
    return jsonify(smv_answer(notes, None, ok=True, space=wiki_space_key(to), from_space=wiki_space_key(src), relinked=relinked,
                              moved=[{"id": r["id"], "from": r["path"], "to": n} for r, n in moves]))



# ---------------------------------------------------------------- 2.97.0 D (#2050): moves with a space with the lock
# The browser holds the keys: it opens path and text of every page with the key of the source (or takes the plain text of an
# open space), links between the moved pages follow there, and it encrypts both for the target (its current generation, the
# AAD names the target space) or sends the plain text when the target is open. The server checks the shape: target locked =
# ciphertexts of exactly its current generation (none taken over unchanged from the source), target open = plain texts;
# exactly the pages named, each with path and text; both generations as seen by the dry run (else 409, the browser tries
# again). Names in a locked target are compared in the browser. No links are kept for a locked target, its history line
# keeps no names. Only a person in the web app (agents, API tokens: 403).
WKR_BUSY = N_("This space is being encrypted. Try again in a moment.")
WKR_NOKEY = N_("You cannot unlock the target space: you have no key for it yet. An admin of the organisation can give it to you.")
WKR_NOKEY_SRC = N_("You have no key for this space yet.")
WKR_PLAIN = N_("The pages are no longer end-to-end encrypted in the target.")
WKR_GEN = N_("The key of a space was changed meanwhile. Please try again.")


def wkr_state(c, oid, uid, lock=False):
    """{space_id, mode, gen} of a space (open: mode None, gen 0); lock = hold its row until the commit."""
    from .wikie2e import wke_space_sql
    w, a = wke_space_sql(oid, uid)
    r = c.execute(f"SELECT id, e2e, e2e_gen FROM wiki_spaces WHERE {w}" + (" FOR UPDATE" if lock else ""), a).fetchone()
    if not r or not r["e2e"]:
        return {"space_id": r["id"] if r else None, "mode": None, "gen": 0}
    return {"space_id": r["id"], "mode": r["e2e"], "gen": int(r["e2e_gen"] or 0)}


def wkr_has_key(c, st, uid):
    return c.execute("SELECT 1 FROM wiki_keys WHERE space_id=? AND user_id=? AND gen=?", (st["space_id"], uid, st["gen"])).fetchone() is not None


def wkr_block(c, uid, sst, tst):
    """The reason this move cannot run now, or None."""
    if any(s["mode"] not in (None, "on") for s in (sst, tst)):
        return tr(WKR_BUSY)
    if tst["mode"] and not wkr_has_key(c, tst, uid):
        return tr(WKR_NOKEY)
    if sst["mode"] and not wkr_has_key(c, sst, uid):
        return tr(WKR_NOKEY_SRC)
    return None


def wkr_ids(v):
    """The page ids of pages = [id …] or [{id, …} …] (400 otherwise, none twice)."""
    if not isinstance(v, list) or not v or len(v) > SMV_MAX:
        raise BadInput(tr("Invalid value: {0}", "pages"))
    ids = [x.get("id") if isinstance(x, dict) else x for x in v]
    if any(isinstance(x, bool) or not isinstance(x, int) for x in ids) or len(set(ids)) != len(ids):
        raise BadInput(tr("Invalid value: {0}", "pages"))
    return ids


def wkr_value(v, field, tst, old):
    """A path / text as sent for the target: a ciphertext of its current generation (locked) or a plain text (open)."""
    from .pages import WIKI_BODY_MAX
    from .wikie2e import WKE_PATH_MAX, wke_body_max, wke_cipher_ok
    from ..collab.liste2e import le2e_is_cipher, le2e_parse
    bad = BadInput(tr("Invalid value: {0}", field))
    if not isinstance(v, str):
        raise bad
    if tst["mode"]:
        if v == "" and field == "body":
            return v
        if (not wke_cipher_ok(v, tst["gen"], field) or v in old
                or le2e_parse(v, max_ct=WKE_PATH_MAX if field == "path" else wke_body_max())["g"] != tst["gen"]):
            raise bad
        return v
    if le2e_is_cipher(v):
        raise bad
    if field == "path":
        return wiki_clean_path(v)
    if len(v) > WIKI_BODY_MAX:
        raise bad
    return v


def wkr_move(c, uid, src, to, b, dry):
    """POST /api/wiki/move-space when the source or the target has the lock: {pages: [id …], space, to, dry: 1} = the check
    (answers e2e {from, to}: space_id / mode / gen of both); {pages: [{id, path, body} …], space, to, gens: {from, to}} = the
    move with the content the browser made for the target (gens = the generations of the check)."""
    from ..collab.liste2e import le2e_writer_ok
    from .pages import wiki_frontmatter
    if not le2e_writer_ok():
        raise Denied(403)
    if b.get("folder") not in (None, ""):
        raise BadInput(tr("Invalid value: {0}", "folder"))  # the browser names the pages (it reads the folder names)
    items = b.get("pages")
    ids = wkr_ids(items)
    rows = [r for r, _ in wkm_rows(c, uid, src, {"pages": ids})]
    if src and not is_org_admin(c, uid, src) and any(r["created_by"] != uid for r in rows):
        raise Denied(403, tr("Only who created these pages or an admin of the organisation can move them out of it"))
    sst, tst = wkr_state(c, src, uid, lock=not dry), wkr_state(c, to, uid, lock=not dry)
    block = wkr_block(c, uid, sst, tst)
    e2e = {"from": sst, "to": tst}
    notes = [trn("{0} page moves", "{0} pages move", len(rows)), tr(WKR_PLAIN) if sst["mode"] and not tst["mode"] else ""]
    if dry:
        return jsonify(smv_answer(notes, block, count=len(rows), e2e=e2e, taken=[]))
    if block:
        raise Denied(409, block)
    gens = b.get("gens") if isinstance(b.get("gens"), dict) else {}
    if gens.get("from") != sst["gen"] or gens.get("to") != tst["gen"]:
        return jsonify(error=tr(WKR_GEN), code="wiki_e2e_gen", e2e=e2e), 409
    if any(not isinstance(x, dict) or "path" not in x or "body" not in x for x in items):
        raise BadInput(tr("Invalid value: {0}", "pages"))
    old = {v for r in rows for v in (r["path"], r["body"]) if v}
    got = {x["id"]: (wkr_value(x["path"], "path", tst, old), wkr_value(x["body"], "body", tst, old)) for x in items}
    if not tst["mode"]:  # an open target: its names are compared here
        tw, ta = wiki_space_sql(to, uid)
        seen, taken = set(), []
        for p, _ in got.values():
            k = p.lower()
            if k in seen or c.execute(f"SELECT 1 FROM wiki_pages WHERE deleted_at IS NULL AND {tw} AND lower(path)=?", [*ta, k]).fetchone():
                taken.append(p)
            seen.add(k)
        if taken:
            c.rollback()
            return jsonify(error=tr("A page with this name already exists"), taken=taken[:20]), 409
    ts = iso_ms(now_utc())
    try:
        with c.savepoint():
            for r in rows:
                p, t = got[r["id"]]
                attrs = "{}" if tst["mode"] else json.dumps(wiki_frontmatter(t), ensure_ascii=False)
                c.execute("UPDATE wiki_pages SET org_id=?, owner_id=?, path=?, body=?, attrs=?, updated_by=?, updated_at=? WHERE id=?",
                          (to, None if to else uid, p, t, attrs, uid, ts, r["id"]))
    except IntegrityError:
        c.rollback()
        return jsonify(error=tr("A page with this name already exists"), taken=[]), 409
    for r in rows:
        p, t = got[r["id"]]
        if tst["mode"]:
            c.execute("DELETE FROM wiki_links WHERE from_id=?", (r["id"],))
        else:
            wiki_set_links(c, r["id"], t)
        detail = {"e2e": 1, **({"to": p} if not tst["mode"] else {})}  # no names of a locked space in the history
        c.execute("INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('wiki',?,?,?,?,?,?)",
                  (r["id"], src, to, uid, ts, json.dumps(detail, ensure_ascii=False)))
    bump(c)
    c.commit()
    return jsonify(smv_answer(notes, None, ok=True, space=wiki_space_key(to), from_space=wiki_space_key(src), relinked=0, e2e=e2e,
                              moved=[{"id": r["id"], **({"to": got[r["id"]][0]} if not tst["mode"] else {})} for r in rows]))


def wkr_place(c, oid, by_id, viewer):
    """2.97.0 D (#2051): a workspace of a history line as the viewer may see it -> (key or None, name): an organisation of
    the viewer by name, another one only as "Organisation"; the own private space "Private", another person's "private
    space" (a move out of a private space is always made by its owner, by_id)."""
    from ..accounts.orgs import user_orgs
    if oid:
        if oid in user_orgs(c, viewer):
            r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            return wiki_space_key(oid), (r["name"] if r else "") or tr("Organisation")
        return None, tr("Organisation")
    if by_id == viewer:
        return "private", tr("Private")
    return None, tr("private space")

def wkm_last(c, pid):
    """The last move of page pid between workspaces (its history line), or None. The caller checked the page is visible."""
    r = c.execute("SELECT from_org, to_org, by_id, at FROM space_moves WHERE kind='wiki' AND obj_id=? ORDER BY id DESC LIMIT 1",
                  (pid,)).fetchone()
    if not r:
        return None
    from ..collab.comments import user_names
    return wkr_line(c, r, user_names(c, [r["by_id"]]).get(r["by_id"], ""))


def wkr_line(c, r, by_name):
    """2.97.0 D (#2051): a history line {from, from_name, to, to_name, at, by_name} (row r of space_moves) for the signed-in
    person: keys and names only of workspaces they belong to (wkr_place)."""
    uid = me()
    fk, fn = wkr_place(c, r["from_org"], r["by_id"], uid)
    tk, tn = wkr_place(c, r["to_org"], r["by_id"], uid)
    return {"from": fk, "from_name": fn, "to": tk, "to_name": tn, "at": r["at"], "by_name": by_name}
