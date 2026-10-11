"""2.37.0 (#1150): the move from SQLite (Kalmido up to 2.36) to Postgres -- `python app.py migrate-sqlite [--check]
[--source PATH]`, and automatically on the first start of 2.37 when the Postgres database is empty and the data dir holds
the tasks.db of an older version (core/db.py startup_guard -> mig_startup). An old backup zip (format 1, a tasks.db
inside) is restored through the same code (admin/backup.py bk_restore -> mig_restore).

How (one Postgres transaction for the whole data part, init_db(load=...)):
 1. the SQLite file is opened read-only, its quick check must pass; a copy goes to backups/pre-postgres-<ts>.db
 2. init_db creates the schema; before its one-shot data migrations, triggers, indexes and row-level security, every table
    is copied in foreign-key order with its old ids (COPY), each value normalised to the column's Postgres type
    (a number written as text -> number, '' in a number column -> NULL or the default, a number in a text column -> text,
    invalid JSON -> '{}' / NULL, NUL characters dropped; a decimal comma in a REAL column stops the move: no guessing).
    Rows whose parent is missing are treated like the foreign key says (ON DELETE CASCADE: left out, SET NULL: emptied).
    Special cases: task_tags of the single-user era (no user_id), list_tags names equal under lower() (merged, the tasks
    keep the tag), list_members.id (assigned by Postgres). Columns only one side has are listed in the report.
 3. check before the COMMIT: per table the row count and a checksum over the normalised rows (both sides in Python, the
    same canonical form); any difference -> ROLLBACK, the tasks.db stays untouched, exit code 3.
 4. after the COMMIT: kalmido_meta.sqlite_migrated (the file's SHA-256 ...), tasks.db -> tasks.db.migrated-<ts> (never
    deleted), the report backups/migration-report-<ts>.json, an admin alert. Every log line starts with "migrate-sqlite:".
Way back: the image of 2.36 + the renamed file renamed back (data written in Postgres since then is not in it).
--check reads and normalises in memory and reports what would be corrected; it writes nothing."""
import graphlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.parse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ..core.config import APP_VERSION, DATABASE_URL, DB
from ..core.db import DataDirError, DbError, connect_direct, init_db, iso, now_utc
from ..core.schema import MIGRATIONS, SCHEMA

TAG = "migrate-sqlite:"
_Q4 = Decimal("0.0001")
_NUM_MAX = Decimal(10) ** 10  # NUMERIC(14,4)
_INT_MIN, _INT_MAX = -(2 ** 63), 2 ** 63 - 1
_NODEF = object()
_INT_RE = re.compile(r"[+-]?\d+")
_INTF_RE = re.compile(r"[+-]?\d+\.0*")
_SAMPLE = 20  # row references kept per correction in the report
# a private agent (no workspace) as a member of an organisation's list: row-level security hides the list from it (K2-3)
K23_SQL = ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN agents a ON a.user_id=m.user_id "
           "WHERE a.org_id IS NULL AND l.org_id IS NOT NULL ORDER BY 1, 2")
K23_HINT = ("private agent(s) are members of lists of an organisation; under row-level security they no longer see these "
            "lists. Assign the agent to a workspace: Settings > Agents > the agent > Workspace (or remove it from the list).")


class MigError(Exception):
    pass


def log(*a):
    print(TAG, *a, flush=True)


def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def is_kalmido_sqlite(path):
    """True when path is a SQLite file with Kalmido tables (users + tasks)."""
    try:
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return False
        con = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True)
        try:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}  # pg-ok: the old SQLite file
        finally:
            con.close()
    except (OSError, sqlite3.Error) as e:
        log(f"{os.path.basename(path)} cannot be read as a Kalmido database ({e})")
        return False
    return {"users", "tasks"} <= names


def _pg_default(d, ty):
    """The value of a simple column default ('0', ''::text, '{}'::jsonb, 1.5) or _NODEF (none / an expression)."""
    if d is None or d == "":
        return _NODEF
    d = re.sub(r"::[\w ]+$", "", d.strip())
    if d.startswith("'") and d.endswith("'"):
        s = d[1:-1].replace("''", "'")
    elif re.fullmatch(r"[+-]?\d+(\.\d+)?", d.strip("()")):
        s = d.strip("()")
    else:
        return _NODEF
    try:
        if ty == "bigint":
            return int(s)
        if ty == "double precision":
            return float(s)
        if ty == "numeric":
            return Decimal(s).quantize(_Q4)
    except (ValueError, InvalidOperation):
        return _NODEF
    return s


def _no_const(x):
    raise ValueError(x)  # NaN / Infinity: Python reads them, jsonb does not


def _jsonb_ok(s):
    if "\\u0000" in s:
        return False
    try:
        json.loads(s, parse_constant=_no_const)
    except (ValueError, RecursionError):
        return False
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def canon(ty, v):
    """One cell in the canonical form of the checksum (same on both sides)."""
    if v is None:
        return "\\N"
    if ty == "bigint":
        return str(int(v))
    if ty == "double precision":
        return repr(float(v))
    if ty == "numeric":
        return str(Decimal(str(v)).quantize(_Q4, ROUND_HALF_UP))
    if ty == "jsonb":
        return json.dumps(json.loads(v), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if ty == "bytea":
        return bytes(v).hex()
    return json.dumps(v, ensure_ascii=False)


def row_hash(types, row):
    return int.from_bytes(hashlib.sha256("\t".join(canon(t, v) for t, v in zip(types, row)).encode("utf-8", "surrogatepass")).digest(), "big")


class Mig:
    """One move (or --check) of one SQLite file."""

    def __init__(self, src, check=False, restore=False):
        self.src, self.check, self.restore = os.path.abspath(src), check, restore
        self.ts = stamp()
        self.fixes = {}      # (table, column, what) -> [count, [row refs]]
        self.dropped = {}    # table -> {reason: count}
        self.merged = []     # list_tags merged under lower(name)
        self.notes = []
        self.k23 = []
        self.tables = {}     # table -> {source, written, checksum}
        self.badutf = [0]
        self.sha = ""
        self.con = None
        self.started = time.time()
        self.seconds = 0.0
        self.counts = {}

    # ---- the source
    def open(self):
        if not os.path.isfile(self.src):
            raise MigError(f"no SQLite file at {self.src}")
        self.sha = file_sha256(self.src)
        try:
            con = sqlite3.connect(f"file:{urllib.parse.quote(self.src)}?mode=ro", uri=True)
            bad = self.badutf

            def text(b):
                try:
                    return b.decode("utf-8")
                except UnicodeDecodeError:
                    bad[0] += 1
                    return b.decode("utf-8", "replace")
            con.text_factory = text
            r = con.execute("PRAGMA quick_check").fetchall()
        except sqlite3.Error as e:
            raise MigError(f"the SQLite file cannot be read: {e}") from None
        if [x[0] for x in r] != ["ok"]:
            raise MigError("the SQLite file is damaged (PRAGMA quick_check: " + "; ".join(str(x[0]) for x in r[:5]) + ")")
        self.con = con
        self.src_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")}  # pg-ok: the old SQLite file

    def safety_copy(self, bk_dir):
        """backups/pre-postgres-<ts>.db through the SQLite backup API (a consistent copy, also of a WAL)."""
        os.makedirs(bk_dir, exist_ok=True)
        dst = os.path.join(bk_dir, f"pre-postgres-{self.ts}.db")
        out = sqlite3.connect(dst)
        try:
            self.con.backup(out)
        finally:
            out.close()
        log("copy of the SQLite database:", dst)
        return dst

    def src_cols(self, t):
        return [r[1] for r in self.con.execute(f'PRAGMA table_info("{t}")')]

    # ---- corrections
    def fix(self, t, col, what, ref):
        k = (t, col, what)
        e = self.fixes.setdefault(k, [0, []])
        e[0] += 1
        if len(e[1]) < _SAMPLE:
            e[1].append(ref)

    def drop(self, t, why, n=1):
        d = self.dropped.setdefault(t, {})
        d[why] = d.get(why, 0) + n

    def norm(self, t, col, ty, nullable, dflt, v, ref):
        """v (as SQLite returned it) as a value for the Postgres column; MigError when it cannot be converted safely."""
        def empty(what):
            if nullable:
                self.fix(t, col, what + " -> NULL", ref)
                return None
            if dflt is not _NODEF:
                self.fix(t, col, what + " -> default", ref)
                return dflt
            raise MigError(f"{t}.{col}, row {ref}: {what} in a required column")
        if v is None:
            return empty("NULL") if not nullable else None
        if ty == "bigint":
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, int):
                if not _INT_MIN <= v <= _INT_MAX:
                    raise MigError(f"{t}.{col}, row {ref}: number {v} too large")
                return v
            if isinstance(v, float):
                if v.is_integer():
                    self.fix(t, col, "decimal number -> whole number", ref)
                    return int(v)
                raise MigError(f"{t}.{col}, row {ref}: {v!r} is not a whole number")
            if isinstance(v, bytes):
                raise MigError(f"{t}.{col}, row {ref}: binary data in a number column")
            s = v.strip()
            if s == "":
                return empty("empty text")
            if _INT_RE.fullmatch(s) or _INTF_RE.fullmatch(s):
                self.fix(t, col, "number written as text -> number", ref)
                return self.norm(t, col, ty, nullable, dflt, int(Decimal(s)), ref)
            if s.lower() in ("true", "false"):
                self.fix(t, col, "true/false -> 1/0", ref)
                return 1 if s.lower() == "true" else 0
            raise MigError(f"{t}.{col}, row {ref}: {s[:40]!r} is not a number")
        if ty in ("double precision", "numeric"):
            if isinstance(v, bool):
                v = int(v)
            if isinstance(v, bytes):
                raise MigError(f"{t}.{col}, row {ref}: binary data in a number column")
            if isinstance(v, str):
                s = v.strip()
                if s == "":
                    return empty("empty text")
                if "," in s:
                    raise MigError(f"{t}.{col}, row {ref}: {s[:40]!r} has a decimal comma -- correct the value in the old "
                                   "version (or the SQLite file) and start again")
                try:
                    v = float(s) if ty != "numeric" else Decimal(s)
                except (ValueError, InvalidOperation):
                    raise MigError(f"{t}.{col}, row {ref}: {s[:40]!r} is not a number") from None
                self.fix(t, col, "number written as text -> number", ref)
            if ty == "double precision":
                return float(v)
            try:
                d = (v if isinstance(v, Decimal) else Decimal(repr(v) if isinstance(v, float) else int(v))).quantize(_Q4, ROUND_HALF_UP)
            except InvalidOperation:
                raise MigError(f"{t}.{col}, row {ref}: {v!r} is not a number") from None
            if not d.is_finite() or abs(d) >= _NUM_MAX:
                raise MigError(f"{t}.{col}, row {ref}: {v!r} is out of range for an amount")
            if isinstance(v, float) and d != Decimal(repr(v)):
                self.fix(t, col, "rounded to 4 decimal places", ref)
            return d
        if ty == "text":
            if isinstance(v, bytes):
                self.fix(t, col, "binary data -> text", ref)
                v = v.decode("utf-8", "replace")
            elif not isinstance(v, str):
                self.fix(t, col, "number -> text", ref)
                return str(v)
            if "\x00" in v:
                self.fix(t, col, "NUL character removed", ref)
                v = v.replace("\x00", "")
            return v
        if ty == "bytea":
            if isinstance(v, (bytes, bytearray, memoryview)):
                return bytes(v)
            self.fix(t, col, "text -> binary", ref)
            return str(v).encode("utf-8", "surrogatepass")
        if ty == "jsonb":
            if not isinstance(v, str):
                v = v.decode("utf-8", "replace") if isinstance(v, bytes) else json.dumps(v)
            s = v.strip()
            if s and _jsonb_ok(s):
                return s
            what = "empty JSON" if not s else "invalid JSON"
            if nullable:
                self.fix(t, col, what + " -> NULL", ref)
                return None
            self.fix(t, col, what + " -> {}", ref)
            return "{}"
        return v

    # ---- the target
    def pg_meta(self, c):
        cols = {}
        for t, col, ty, nul, d, ident in c.execute(
                "SELECT table_name, column_name, data_type, is_nullable, column_default, is_identity FROM information_schema.columns "
                "WHERE table_schema=current_schema() ORDER BY table_name, ordinal_position").fetchall():
            cols.setdefault(t, []).append((col, ty, nul == "YES", _pg_default(d, ty), ident == "YES"))
        fks = {}
        for t, ref, col, dt in c.execute(
                "SELECT conrelid::regclass::text, confrelid::regclass::text, a.attname, con.confdeltype FROM pg_constraint con "
                "JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] "
                "WHERE con.contype='f' AND con.connamespace=current_schema()::regnamespace").fetchall():
            fks.setdefault(t.strip('"'), []).append((col, ref.strip('"'), dt))
        self.cols, self.fks = cols, fks
        deps = {t: {r for _c, r, _d in fks.get(t, ()) if r != t} for t in cols}
        self.order = list(graphlib.TopologicalSorter(deps).static_order())

    def plan(self, t):
        """(columns copied, their types) for table t; notes for columns only one side has."""
        pgc = {x[0]: x for x in self.cols[t]}
        have = self.src_cols(t)
        miss = [x for x in pgc if x not in have and not (t == "list_members" and x == "id")]
        extra = [x for x in have if x not in pgc]
        if t == "task_tags" and "user_id" in miss:  # single-user era: (task_id, tag); init_db gives them to the first admin
            miss.remove("user_id")
            self.notes.append("task_tags: from before user accounts (no user_id), the tags go to the first administrator")
        if miss:
            self.notes.append(f"{t}: column(s) {', '.join(miss)} missing in the SQLite file -> default values")
        if extra:
            self.notes.append(f"{t}: column(s) {', '.join(extra)} of the SQLite file not taken over (gone in this version)")
        use = [x for x in have if x in pgc and not (t == "list_members" and x == "id")]  # (list_members.id: Postgres assigns it)
        return use, pgc

    def read_table(self, t, c):
        """Normalised rows of table t (FK rules applied, ids recorded)."""
        use, pgc = self.plan(t)
        old_tt = t == "task_tags" and "user_id" not in self.src_cols(t)
        cols = list(use)
        if not use:
            raise MigError(f"{t}: no column of the SQLite table matches this version")
        sel = ", ".join(f'"{x}"' for x in use)
        rows = []
        idx = {x: i for i, x in enumerate(use)}
        idpos = idx.get("id")
        n = 0
        for raw in self.con.execute(f'SELECT {sel} FROM "{t}"'):
            n += 1
            ref = f"id={raw[idpos]}" if idpos is not None else f"#{n}"
            row = [self.norm(t, x, pgc[x][1], pgc[x][2], pgc[x][3], raw[i], ref) for i, x in enumerate(use)]
            rows.append(row)
        if old_tt:
            cols.append("user_id")
            for r in rows:
                r.append(0)
        self.tables[t] = {"source": n}
        types = [pgc[x][1] for x in cols]
        if t == "list_tags":
            rows = self.merge_list_tags(c, cols, rows)
        if t == "task_list_tags" and self.tag_map:
            ti, gi = cols.index("task_id"), cols.index("tag_id")
            seen, out = set(), []
            for r in rows:
                r[gi] = self.tag_map.get(r[gi], r[gi])
                k = (r[ti], r[gi])
                if k in seen:
                    self.drop(t, "same tag twice after merging list tags")
                    continue
                seen.add(k)
                out.append(r)
            rows = out
        rows = self.apply_fks(t, cols, rows)
        if "id" in cols:
            i = cols.index("id")
            self.ids[t] = {r[i] for r in rows}
        return cols, types, rows

    def merge_list_tags(self, c, cols, rows):
        """2.37: names unique under lower() (SQLite: NOCASE, ASCII only) -> tags equal under lower() in one list are merged
        into the oldest (smallest id); their tasks keep the tag."""
        self.tag_map = {}
        if not rows:
            return rows
        ni, li, ii = cols.index("name"), cols.index("list_id"), cols.index("id")
        names = sorted({r[ni] for r in rows})
        low = dict(c.execute("SELECT n, lower(n) FROM unnest(CAST(? AS text[])) AS n", (names,)).fetchall()) if c is not None \
            else {x: x.lower() for x in names}
        keep, out = {}, []
        for r in sorted(rows, key=lambda r: r[ii]):
            k = (r[li], low.get(r[ni], r[ni].lower()))
            if k in keep:
                self.tag_map[r[ii]] = keep[k][ii]
                self.merged.append({"list_id": r[li], "kept": keep[k][ii], "merged": r[ii]})
                continue
            keep[k] = r
            out.append(r)
        if self.merged:
            log(f"list_tags: {len(self.merged)} tag(s) equal under lower case merged (the tasks keep the tag)")
        return out

    def apply_fks(self, t, cols, rows):
        fks = [(cols.index(col), ref, dt) for col, ref, dt in self.fks.get(t, ()) if col in cols]
        if not fks:
            return rows
        while True:  # a self reference (tasks.parent_id) may cascade over several levels
            mine = {r[cols.index("id")] for r in rows} if "id" in cols else set()
            out, changed = [], False
            for r in rows:
                keep = True
                for i, ref, dt in fks:
                    v = r[i]
                    if v is None:
                        continue
                    have = mine if ref == t else self.ids.get(ref, set())
                    if v in have:
                        continue
                    if dt == "c":
                        self.drop(t, f"{cols[i]} points to a missing {ref} row (ON DELETE CASCADE)")
                        keep, changed = False, True
                        break
                    if dt == "n":
                        self.fix(t, cols[i], f"points to a missing {ref} row -> NULL (ON DELETE SET NULL)", r[cols.index("id")] if "id" in cols else "")
                        r[i] = None
                        continue
                    raise MigError(f"{t}.{cols[i]}: row points to the missing {ref} row {v}")
                if keep:
                    out.append(r)
            rows = out
            if not changed or not any(ref == t for _i, ref, _d in fks):
                return rows

    # ---- the move
    def run_copy(self, c):
        """init_db(load=...): inside init_db's transaction, after the schema; copies, checks, records."""
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise MigError("the Postgres database is not empty")
        self.ids, self.tag_map = {}, {}
        self.pg_meta(c)
        for t in sorted(self.src_tables - set(self.cols)):
            if not t.startswith("msg_fts"):
                self.notes.append(f"table {t} of the SQLite file not taken over (gone in this version)")
        sums = {}
        for t in self.order:
            if t not in self.src_tables or t == "kalmido_meta":
                continue
            cols, types, rows = self.read_table(t, c)
            if rows:
                with c._pg.cursor().copy(f'COPY "{t}" (' + ", ".join(f'"{x}"' for x in cols) + ") FROM STDIN") as cp:  # pg-ok: COPY needs the driver connection
                    for r in rows:
                        cp.write_row(r)
            sums[t] = (cols, types, len(rows), sum(row_hash(types, r) for r in rows) % (1 << 256))
            self.tables[t]["written"] = len(rows)
            del rows
            log(f"{t}: {self.tables[t]['source']} rows")
        for t, cols in self.cols.items():  # identities continue after the old ids
            if any(x[0] == "id" and x[4] for x in cols):
                c.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), GREATEST(MAX(id), 1), MAX(id) IS NOT NULL) FROM \"{t}\"")
        self.verify(c, sums)
        self.k23 = [list(r) for r in c.execute(K23_SQL).fetchall()]
        self.counts = self.biz_counts(c)
        self.seconds = round(time.time() - self.started, 1)
        rec = {"sha256": self.sha, "at": iso(now_utc()), "version": APP_VERSION, "source": os.path.basename(self.src),
               "restore": self.restore, "tables": len(sums), "rows": sum(x[2] for x in sums.values())}
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES('sqlite_migrated',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (json.dumps(rec),))

    def verify(self, c, sums):
        """Row counts and checksums over the rows as Postgres has them now (read back, same canonical form)."""
        bad = []
        for t, (cols, types, n, h) in sums.items():
            got, hp = 0, 0
            cur = c._pg.execute(f'SELECT {", ".join(chr(34) + x + chr(34) for x in cols)} FROM "{t}"')  # pg-ok: read back on the driver connection (rows as stored)
            for r in cur:
                got += 1
                hp += row_hash(types, r)
            cur.close()
            hp %= (1 << 256)
            self.tables[t]["checksum"] = format(h, "064x")[:16]
            if got != n or hp != h:
                bad.append(f"{t} ({n} rows written, {got} read back{'' if got != n else ', checksum differs'})")
        if bad:
            raise MigError("check after copying failed: " + "; ".join(bad[:10]))
        log(f"check: {len(sums)} tables, row counts and checksums equal")

    def biz_counts(self, c):
        def one(sql):
            try:
                return c.execute(sql).fetchone()[0]
            except (DbError, sqlite3.Error):
                return None
        return {"users": one("SELECT COUNT(*) FROM users"), "lists": one("SELECT COUNT(*) FROM lists"),
                "open_tasks": one("SELECT COUNT(*) FROM tasks WHERE status=0"), "attachments": one("SELECT COUNT(*) FROM attachments")}

    # ---- --check (nothing is written)
    def run_check(self):
        c = connect_direct(DATABASE_URL)
        try:
            empty = not c.execute("SELECT to_regclass('users')").fetchone()[0]
            if empty:  # learn the column types from the schema, inside a transaction that is rolled back
                for ext in ("unaccent", "pg_trgm"):
                    with c.savepoint():
                        try:
                            c.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
                        except DbError:
                            pass
                c.executescript(SCHEMA)
                have = {}
                for t, col in c.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema=current_schema()").fetchall():
                    have.setdefault(t, set()).add(col)
                for table, col, ddl in MIGRATIONS:
                    if col not in have.get(table, ()):
                        c.execute(ddl)
            self.pg_meta(c)
            self.ids, self.tag_map = {}, {}
            for t in self.order:
                if t not in self.src_tables or t == "kalmido_meta":
                    continue
                _cols, _types, rows = self.read_table(t, c)
                self.tables[t]["written"] = len(rows)
            self.k23 = [list(r) for r in self.con.execute(K23_SQL).fetchall()] if {"agents", "lists", "list_members"} <= self.src_tables else []
            self.counts = self.biz_counts(self.con)
        finally:
            c.rollback()
            c.close()
        self.seconds = round(time.time() - self.started, 1)

    # ---- the report
    def report(self, status, error=""):
        return {
            "status": status, "error": error, "source": os.path.basename(self.src), "source_sha256": self.sha,
            "version": APP_VERSION, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.started)),
            "seconds": self.seconds, "tables": self.tables,
            "rows": sum(x.get("written", 0) for x in self.tables.values()),
            "corrections": [{"table": t, "column": col, "what": what, "count": e[0], "rows": e[1]}
                            for (t, col, what), e in sorted(self.fixes.items())],
            "left_out": self.dropped, "merged_list_tags": self.merged, "notes": self.notes,
            "invalid_utf8_texts": self.badutf[0], "counts": self.counts,
            "private_agents_in_organisation_lists": {"rows": self.k23, "hint": K23_HINT if self.k23 else ""},
        }

    def log_summary(self, status):
        n = sum(e[0] for e in self.fixes.values())
        log(f"{status}: {len(self.tables)} tables, {sum(x.get('written', 0) for x in self.tables.values())} rows, "
            f"{n} value(s) corrected, {sum(sum(d.values()) for d in self.dropped.values())} row(s) left out, "
            f"{len(self.merged)} list tag(s) merged, {self.seconds} s")
        for (t, col, what), e in sorted(self.fixes.items()):
            log(f"  corrected {t}.{col}: {what} ({e[0]}x, e.g. {', '.join(map(str, e[1][:3]))})")
        for t, d in sorted(self.dropped.items()):
            for why, k in d.items():
                log(f"  left out {t}: {k} row(s), {why}")
        for x in self.notes:
            log("  note:", x)
        if self.badutf[0]:
            log(f"  {self.badutf[0]} text(s) with invalid UTF-8 (unreadable bytes replaced)")
        if self.k23:
            log(f"  K2-3: {len(self.k23)} {K23_HINT} (list id, agent id): {self.k23[:_SAMPLE]}")


def _bk_dir():
    from .backup import BK_DIR
    return BK_DIR


def _write_report(m, rep):
    d = _bk_dir()
    try:
        os.makedirs(d, exist_ok=True)
        # a failed move overwrites one file (review W3-1: no new file per restart)
        p = os.path.join(d, "migration-report-failed.json" if rep.get("status") == "failed" else f"migration-report-{m.ts}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False, default=str)
        log("report:", p)
        return p
    except OSError as e:
        log("could not write the report:", e)
        return ""


def mig_run(src, restore=False):
    """The move of src into the (empty) Postgres database. Returns the Mig; raises MigError / DbError (nothing written)."""
    m = Mig(src, restore=restore)
    log(f"moving {m.src} into Postgres" + (" (restore of an old backup)" if restore else ""))
    try:
        m.open()
        init_db(guard=False, load=m.run_copy)
    except Exception as e:
        m.seconds = round(time.time() - m.started, 1)
        why = str(e).strip() if isinstance(e, MigError) else f"{type(e).__name__}: {str(e).strip()[:500]}"
        log("FAILED, nothing was written to Postgres (rolled back), the SQLite file is unchanged:", why)
        _write_report(m, m.report("failed", why))
        if m.con is not None:
            m.con.close()
        raise MigError(why) from None
    # 2.37.0 (review W3-1): the copy only after a successful move (the source is opened read-only, so it is the same file);
    # before, every failed start under a restart policy left one more full copy in backups/ (disk full loop)
    if not restore:
        try:
            m.safety_copy(_bk_dir())
        except (OSError, sqlite3.Error) as e:
            log("could not copy the SQLite database (the original stays as tasks.db.migrated-*):", e)
    m.con.close()
    m.log_summary("done")
    m.report_path = _write_report(m, m.report("ok"))
    return m


def mig_finish(m):
    """After the COMMIT of a start-up / CLI move: rename the source (never deleted) and tell the admins."""
    dst = f"{m.src}.migrated-{m.ts}"
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(m.src + suf):
            try:
                os.rename(m.src + suf, dst + suf)
            except OSError as e:
                log(f"could not rename {m.src + suf} ({e}); it is ignored from now on (kalmido_meta.sqlite_migrated knows it)")
    if os.path.exists(dst):
        log(f"the old database stays as {dst} (way back: the image of 2.36 with this file renamed back to {os.path.basename(m.src)})")
    _alert(m)


def _alert(m):
    from ..core.i18n import N_
    from ..notify.alerts import aa_now
    rows = sum(x.get("written", 0) for x in m.tables.values())
    aa_now("storage", f"migrated:{m.sha[:16]}", N_("Move to Postgres finished: {0} tables, {1} rows (report in the backups folder)."),
           [len(m.tables), rows])
    if m.k23:
        aa_now("security", f"k23:{m.sha[:16]}", N_("{0} private agent(s) are members of lists of an organisation and no longer see them. Assign each agent to a workspace (Settings > Agents)."),
               [len(m.k23)])


def mig_restore(path):
    """admin/backup.py: an old backup (format 1, its tasks.db at path) into the running database. Every table is dropped
    first (the caller is in maintenance mode and holds a safety backup to go back to on an error), then moved like at
    start-up."""
    c = connect_direct(DATABASE_URL)
    try:
        from ..core.pg import system_ctx
        with system_ctx(c):  # the restore works on the whole database (every organisation)
            c.execute("SET LOCAL statement_timeout = 0")
            for (t,) in c.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()").fetchall():
                c.execute('DROP TABLE IF EXISTS "' + t.replace('"', '""') + '" CASCADE')
        c.commit()
    finally:
        c.close()
    from ..core.pg import pool_refresh
    pool_refresh()
    m = mig_run(path, restore=True)
    _alert(m)
    return m


def _known_file(sha):
    c = connect_direct(DATABASE_URL)
    try:
        r = c.execute("SELECT value FROM kalmido_meta WHERE key='sqlite_migrated'").fetchone() \
            if c.execute("SELECT to_regclass('kalmido_meta')").fetchone()[0] else None
    finally:
        c.close()
    try:
        return bool(r) and json.loads(r[0]).get("sha256") == sha
    except (ValueError, AttributeError):
        return False


def mig_startup(has_tables):
    """core/db.py startup_guard: True when a tasks.db of 2.36 was just moved into the empty database. A tasks.db next to
    a database with data starts only when that very file was moved before (else exit 3: never two truths). The CLI
    (app.py migrate-sqlite) runs here, before init_db touches the database, and ends the process."""
    if os.environ.get("KALMIDO_MIGRATE_CLI"):
        raise SystemExit(mig_cli(json.loads(os.environ["KALMIDO_MIGRATE_CLI"]), has_tables))
    try:
        old = os.path.isfile(DB) and os.path.getsize(DB) > 0
    except OSError:
        old = False
    if not old:
        return False
    if has_tables:
        try:
            sha = file_sha256(DB)
        except OSError:
            sha = ""
        if sha and _known_file(sha):
            log(f"{DB} was moved into Postgres before; ignored (rename or remove it when it is no longer needed)")
            return False
        print(f"FATAL: the Postgres database holds data and the data dir also has a SQLite database ({DB}) that was not moved "
              "into it. Refusing to start: there must not be two versions of the data. If the Postgres database is the right "
              "one, move the old file away (it is not needed any more); if the file is, point DATABASE_URL at an empty "
              "database and start again (it is moved over then).", flush=True)
        raise DataDirError(3)
    if not is_kalmido_sqlite(DB):
        return False  # (startup_guard refuses it as an unknown file next to an empty database)
    try:
        m = mig_run(DB)
    except (MigError, DbError) as e:
        print(f"FATAL: moving the SQLite database into Postgres failed: {e}. Postgres is still empty, {DB} is unchanged. "
              "Correct the cause and start again, or go back to the image of 2.36.", flush=True)
        raise DataDirError(3) from None
    mig_finish(m)
    return True


def mig_cli(args, has_tables):
    """python app.py migrate-sqlite [--check] [--source PATH] -> exit code (0 ok, 2 usage, 3 refused / failed)."""
    check, src, i = False, DB, 0
    while i < len(args):
        if args[i] == "--check":
            check = True
        elif args[i] == "--source" and i + 1 < len(args):
            i += 1
            src = args[i]
        else:
            print("usage: python app.py migrate-sqlite [--check] [--source /data/tasks.db]", flush=True)
            return 2
        i += 1
    if not os.path.isfile(src):
        log(f"no SQLite file at {src}")
        return 3
    if check:
        m = Mig(src, check=True)
        try:
            m.open()
            m.run_check()
        except (MigError, DbError) as e:
            m.seconds = round(time.time() - m.started, 1)
            log("check: the move would FAIL:", e)
            print(json.dumps(m.report("check-failed", str(e).strip()), indent=1, ensure_ascii=False, default=str), flush=True)
            return 3
        m.log_summary("check (nothing written)")
        print(json.dumps(m.report("check"), indent=1, ensure_ascii=False, default=str), flush=True)
        return 0
    if has_tables:
        log("the Postgres database is not empty; a move needs an empty database (nothing done)")
        return 3
    if not is_kalmido_sqlite(src):
        log(f"{src} is no Kalmido database")
        return 3
    try:
        m = mig_run(src)
    except (MigError, DbError):
        return 3
    if os.path.abspath(src) == os.path.abspath(DB):
        mig_finish(m)
    else:
        _alert(m)
    return 0


if __name__ == "__main__":  # (the entry point is app.py migrate-sqlite)
    sys.exit(2)
