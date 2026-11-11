"""2.905.0 (#5288, stage Q10 of the cross-cutting core, analysis #3563, decided 08.11.2026): templates are ONE kind of the
shared core, "template" (lists/templates.py obj_register: kind task | list | sections, org_access view, org_join admin).

The table templates takes the columns of a core kind and real types (#5305), and the section templates (section_templates,
2.156.0 C #2073: a name and the ordered names of a list's sections) become rows of it with kind 'sections' and data
{"sections": [name, ...]}. tpl_move runs at every start (core/db.py init_db, before the fragments' AFTER, where 5288_a drops
section_templates), each part only while there is something to do:

  1. templates.user_id is renamed owner_id (the core's owner column; a new database makes owner_id at once, core/schema.py)
  2. created_at / updated_at / deleted_at TEXT -> TIMESTAMPTZ, data / extra TEXT -> JSONB, each in its own savepoint: a value
     that is no ISO time becomes the start's time (deleted_at: NULL), one that is no JSON object '{}'; a column that cannot
     move stays as it was (the log says why) and the next start tries again
  3. the rows of section_templates move into templates (the same owner, workspace, name, times) -- whatever is there: the
     first start of 2.905, or the rows a version before 2.905 wrote after a rollback; the fragment drops the table right after

One way (the leader's --einbahn): a version before 2.905 finds no templates.user_id and no section_templates rows (it makes the
table anew, empty); a backup restores the old state. Python standard library + the driver layer only (layer core)."""
import json
import re
import sys
from datetime import datetime

from .pg import qi, table_columns

TPM_TIMES = (("created_at", False), ("updated_at", False), ("deleted_at", True))  # (column, nullable)
TPM_JSON = ("data", "extra")
TPM_NAMES = {"templates", "section_templates", *(x for x, _ in TPM_TIMES), *TPM_JSON}  # the allowlist of qi() (#5296)
TPM_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)?$"


def _type(c, table, col):
    r = c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? "
                  "AND column_name=?", (table, col)).fetchone()
    return r[0] if r else None


def _retype(c, col, sql):
    """One column in its own savepoint; False (and a log line) when Postgres refuses it."""
    try:
        with c.savepoint():
            c.execute(sql)
        return True
    except Exception as e:  # noqa: BLE001 -- the start goes on with the column as it was, the log says why
        print(f"migrations: 5288: templates.{col} keeps its type: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
        return False


def tpm_columns(c):
    """Parts 1 + 2 (module docstring) -> [what changed]."""
    out = []
    cols = table_columns(c, "templates")
    if "user_id" in cols and "owner_id" not in cols:
        c.execute("ALTER TABLE templates RENAME COLUMN user_id TO owner_id")
        out.append("owner_id")
    for col, nullable in TPM_TIMES:
        if _type(c, "templates", col) != "text":
            continue
        q = qi(col, TPM_NAMES)
        other = "NULL" if nullable else "CURRENT_TIMESTAMP"
        if _retype(c, col, f"ALTER TABLE templates ALTER COLUMN {q} TYPE TIMESTAMPTZ USING (CASE WHEN {q} ~ '{TPM_ISO}' "
                           f"THEN {q}::timestamptz ELSE {other} END)"):
            out.append(col)
    for col in TPM_JSON:
        if _type(c, "templates", col) != "text":
            continue
        q = qi(col, TPM_NAMES)
        if _retype(c, col, f"ALTER TABLE templates ALTER COLUMN {q} DROP DEFAULT, ALTER COLUMN {q} TYPE JSONB USING (CASE WHEN "
                           f"{q} IS JSON OBJECT THEN {q}::jsonb ELSE '{{}}'::jsonb END), ALTER COLUMN {q} SET DEFAULT '{{}}'::jsonb"):
            out.append(col)
    return out


def _when(v):
    """2.905.0 (#5288, Fable review F3): a time of section_templates Postgres reads, else None (= the start time) -- checked in
    Python, not only by the pattern TPM_ISO: 2026-02-30 matches it, the cast would throw and stop init_db at every start."""
    if not re.match(TPM_ISO, v or ""):
        return None
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return v


def tpm_sections(c):
    """Part 3 (module docstring): the section templates as templates of kind 'sections' -> the number of rows moved."""
    if not c.execute("SELECT to_regclass('section_templates')").fetchone()[0]:
        return 0
    n = 0
    for r in c.execute("SELECT * FROM section_templates ORDER BY id").fetchall():
        try:
            names = json.loads(r["sections"] or "[]")
        except ValueError:
            names = []
        names = [str(x) for x in names if isinstance(x, (str, int, float)) and str(x).strip()] if isinstance(names, list) else []
        if not names:
            continue  # a template without sections could not be used (the app refused to save one)
        made, upd = str(r["created_at"] or ""), str(r["updated_at"] or "")
        c.execute("INSERT INTO templates(owner_id, org_id, kind, name, data, created_at, updated_at, created_by, updated_by) "
                  "VALUES(?, ?, 'sections', ?, ?, COALESCE(?::timestamptz, CURRENT_TIMESTAMP), "
                  "COALESCE(?::timestamptz, CURRENT_TIMESTAMP), ?, ?)",
                  (r["user_id"], r["org_id"], r["name"], json.dumps({"sections": names}, ensure_ascii=False),
                   _when(made), _when(upd), r["user_id"], r["user_id"]))
        n += 1
    c.execute("DELETE FROM section_templates")
    return n


def tpl_move(c):
    """init_db (core/db.py), in the system context: the columns first, then the rows of section_templates -> {what: n}."""
    out = {"columns": tpm_columns(c), "section_templates": tpm_sections(c)}
    if out["columns"] or out["section_templates"]:
        print("templates onto the shared core (#5288):", out, flush=True)
    return out
