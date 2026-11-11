"""2.958.0 (#5281, stage Q7a of the cross-cutting core): the versions of the shared core -- one table obj_versions for the
numbered whole states of an object (core/migrations.d/5281_a.py, docs/dev/kern.md "Versions").

obj_history keeps field changes, obj_undo a person's steps (30 days), obj_versions the states of an object's content: each a
number per object (no), the object's name at that time (title), the whole content (body: the area seals it, AAD context
OBJV_CTX with the key of the object's space), its bytes (size), who wrote it and when. An area keeps its own rules on top:
when a save makes a new version or merges into the last one (the knowledge pages: the same person within ten minutes), how
many stay (prune), who may read and restore (its own rights check before every call), and a restore = the old state saved
as a new version through the area's own write path. held_at: a row the area holds out of sight (the lock of a knowledge
space, wiki/wkhist.py); NULL = an ordinary row.

The rows go with their object: obj_rows_drop / obj_rows_drop_many (core/objhooks.py) take them with the history, and a kind
whose table rows are deleted by other ways too gets the trigger kalmido_ov_gone('<kind>') on its table (5281_a.py: wiki_pages).

Kinds today: "wiki" (wiki/wkhist.py); 2.977.0 (#5282, stage Q7b): "playbook" (lists/playbook.py: ref_id = a row of playbooks,
the head of a list's or a folder's Playbook) and "procdoc" (office/procdoc.py: ref_id = a row of office_procdocs, the head of an
office area's procedure documentation). source (2.977.0): how a version came, in the area's words (the playbooks: edit, restore,
proposal, import, template); '' = not said (the knowledge pages, the procedure documentation)."""
from datetime import datetime

from .pg import insert_id, ts_canon, write_lock

OBJV_TABLE = "obj_versions"
OBJV_CTX = "obj_versions.body"  # the AAD context of a sealed body (core/orgcrypt.py FIELDS["obj_versions"])
OBJV_COLS = "id, kind, ref_id, no, org_id, owner_id, title, body, size, created_by, created_at, updated_at, held_at, source"  # 2.977.0 (#5282): + source


def obj_version_add(c, kind, ref_id, org_id, owner_id, title, body, size, by, at, held_at=None, source=""):
    """A new version of object kind / ref_id with the next number (under the lock objv-<kind>-<id> until the transaction
    ends). body as it is stored (the area sealed it); source (2.977.0, #5282) how it came. -> its id."""
    write_lock(c, f"objv-{kind}-{int(ref_id)}")
    no = c.execute("SELECT COALESCE(MAX(no), 0) + 1 FROM obj_versions WHERE kind=? AND ref_id=?", (kind, int(ref_id))).fetchone()[0]
    return insert_id(c, "INSERT INTO obj_versions(kind,ref_id,no,org_id,owner_id,title,body,size,created_by,created_at,updated_at,held_at,"
                        "source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (kind, int(ref_id), no, org_id, owner_id, title or "", body or "", int(size or 0), by, at, at, held_at, source or ""))


def obj_version_merge(c, vid, title, body, size, at):
    """A save merged into version vid (the area's rule): its state is the new one, its number and author stay."""
    c.execute("UPDATE obj_versions SET title=?, body=?, size=?, updated_at=? WHERE id=?", (title or "", body or "", int(size or 0), at, int(vid)))


def obj_version_rows(c, kind, ref_id, limit=1, cols=OBJV_COLS):
    """The newest `limit` versions of object kind / ref_id, newest first."""
    return c.execute(f"SELECT {cols} FROM obj_versions WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?",
                     (kind, int(ref_id), int(limit))).fetchall()


def obj_version_get(c, kind, ref_id, vid):
    """Version vid of object kind / ref_id (None: none, or another object's)."""
    if vid is None:
        return None
    return c.execute(f"SELECT {OBJV_COLS} FROM obj_versions WHERE id=? AND kind=? AND ref_id=?", (int(vid), kind, int(ref_id))).fetchone()


def obj_version_no(c, kind, ref_id, no):
    """2.977.0 (#5282): version number `no` of object kind / ref_id (None: no such number) -- the areas whose routes name a
    version by its number (the playbooks, the procedure documentation)."""
    if no is None:
        return None
    return c.execute(f"SELECT {OBJV_COLS} FROM obj_versions WHERE kind=? AND ref_id=? AND no=?", (kind, int(ref_id), int(no))).fetchone()


def obj_version_last(c, kind, ref_id):
    """2.977.0 (#5282): the newest version of object kind / ref_id (the highest number), or None."""
    return c.execute(f"SELECT {OBJV_COLS} FROM obj_versions WHERE kind=? AND ref_id=? ORDER BY no DESC LIMIT 1",
                     (kind, int(ref_id))).fetchone()


def obj_version_prune(c, kind, ref_id, keep):
    """At most `keep` versions of the object: the oldest go (the numbers of the others stay). -> how many went."""
    cut = c.execute("SELECT id FROM obj_versions WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1 OFFSET ?",
                    (kind, int(ref_id), int(keep) - 1)).fetchone()
    if not cut:
        return 0
    return c.execute("DELETE FROM obj_versions WHERE kind=? AND ref_id=? AND id<?", (kind, int(ref_id), cut[0])).rowcount


def obj_version_count(c, kind, ref_ids):
    """How many versions the objects ref_ids of kind have."""
    ids = [int(i) for i in ref_ids]
    if not ids:
        return 0
    return c.execute("SELECT COUNT(*) FROM obj_versions WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (kind, ids)).fetchone()[0]


def obj_version_drop(c, kind, ref_ids):
    """Every version of the objects ref_ids of kind goes (a move into a space that keeps none). One-way. -> how many."""
    ids = [int(i) for i in ref_ids]
    if not ids:
        return 0
    return c.execute("DELETE FROM obj_versions WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))", (kind, ids)).rowcount


def obj_version_old_ts(v, fallback):
    """2.977.0 (#5282): an old TEXT time of an area's table as it goes into obj_versions (TIMESTAMPTZ): canonical, or fallback
    when no cast could read it (the moves of stage Q7: wiki/wkhist.py, lists/playbook.py, office/procdoc.py)."""
    t = ts_canon(v) if v else ""
    try:
        datetime.fromisoformat(t)
        return t
    except ValueError:
        return fallback


def obj_version_free_no(c, kind, ref_id, want):
    """2.977.0 (#5282): the number an old version keeps when it moves into obj_versions -- its own (want) when no version of the
    object has it yet, else the next free one after the highest."""
    if want and not c.execute("SELECT 1 FROM obj_versions WHERE kind=? AND ref_id=? AND no=?", (kind, int(ref_id), int(want))).fetchone():
        return int(want)
    return c.execute("SELECT COALESCE(MAX(no), 0) + 1 FROM obj_versions WHERE kind=? AND ref_id=?", (kind, int(ref_id))).fetchone()[0]
