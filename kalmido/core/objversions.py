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

Kinds today: "wiki" (wiki/wkhist.py). The playbooks and the procedure documentation follow (stage Q7b)."""
from .pg import insert_id, write_lock

OBJV_TABLE = "obj_versions"
OBJV_CTX = "obj_versions.body"  # the AAD context of a sealed body (core/orgcrypt.py FIELDS["obj_versions"])
OBJV_COLS = "id, kind, ref_id, no, org_id, owner_id, title, body, size, created_by, created_at, updated_at, held_at"


def obj_version_add(c, kind, ref_id, org_id, owner_id, title, body, size, by, at, held_at=None):
    """A new version of object kind / ref_id with the next number (under the lock objv-<kind>-<id> until the transaction
    ends). body as it is stored (the area sealed it). -> its id."""
    write_lock(c, f"objv-{kind}-{int(ref_id)}")
    no = c.execute("SELECT COALESCE(MAX(no), 0) + 1 FROM obj_versions WHERE kind=? AND ref_id=?", (kind, int(ref_id))).fetchone()[0]
    return insert_id(c, "INSERT INTO obj_versions(kind,ref_id,no,org_id,owner_id,title,body,size,created_by,created_at,updated_at,held_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (kind, int(ref_id), no, org_id, owner_id, title or "", body or "", int(size or 0), by, at, at, held_at))


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
