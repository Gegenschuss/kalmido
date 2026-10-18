"""2.96.0 B (#1941): wiki pages and folders (with their sub-pages) to the other workspace (private <-> organisation).

POST /api/wiki/move-space {pages: [id …] | folder: "<path>", space: <the source space>, to, dest: "<folder in the target>" | "",
dry} -- a page keeps its name, a folder its last part and everything below it: the path in the target = dest + that rest.
The rules of accounts/spacemove.py: agents never (403; they have no wiki access anyway), the target an organisation the person
is a member of (409), out of an organisation only pages the person created, or as that organisation's admin (403). A name
taken in the target = 409 with the names (the dry run: block). [[links]] between pages that move together follow the new
paths; links between a moved page and one that stays are kept as text and named in the dry run. Pages link files of the
file store only by URL: the files stay where they are (named). A space with the lock (wiki/wikie2e.py): the server cannot
re-encrypt for the other space -- refused with a clear message. Every page gets a row in space_moves (its history).
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

WKM_LOCKED = N_("Pages of a space with the lock cannot be moved to another workspace yet. Remove the lock or copy the text.")
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
        if dry:
            return jsonify(smv_answer(block=tr(WKM_LOCKED), count=0))
        raise Denied(409, tr(WKM_LOCKED))
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


def wkm_last(c, pid):
    """The last move of page pid between workspaces (its history line), or None. The caller checked the page is visible."""
    r = c.execute("SELECT from_org, to_org, by_id, at FROM space_moves WHERE kind='wiki' AND obj_id=? ORDER BY id DESC LIMIT 1",
                  (pid,)).fetchone()
    if not r:
        return None
    from ..collab.comments import user_names
    return {"from": wiki_space_key(r["from_org"]), "to": wiki_space_key(r["to_org"]), "at": r["at"],
            "by_name": user_names(c, [r["by_id"]]).get(r["by_id"], "")}
