"""dbx.py -- the suites' direct database access (2.37.0, #1150: Postgres instead of the tasks.db file).

Works like the few sqlite3 calls the suites used:
    import dbx
    c = dbx.connect(os.path.join(DATA, "tasks.db"))   # or the data dir itself
    c.execute("UPDATE tasks SET due=? WHERE id=?", ("2026-01-01", tid)); c.commit()
    n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    r = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone(); r["name"]; dict(r); r.keys()
Every statement runs at once in its own transaction inside the database container of that data dir (start.sh writes
<datadir>/.kalmido-db = "<db container> <database>"), through `docker exec ... psql` -- no driver needed on the host.
`?` placeholders are filled in here (strings / numbers as untyped literals, so Postgres reads them as the column's type;
True / False as 1 / 0; None as NULL; bytes as bytea). commit() / close() exist and do nothing.
Rows: index, column name, keys(), dict(row). Values come back as JSON types (int, float, str, None; bytea as "\\x..").

CLI for the JS suites:  python3 dbx.py <datadir|tasks.db> "<sql>" ['<json args>']   prints the rows as JSON.
"""
import json
import os
import re
import subprocess
import sys


def _target(path):
    d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    with open(os.path.join(d, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    return dbc, dbn


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "'1'" if v else "'0'"
    if isinstance(v, (int, float)):
        return "'" + repr(v) + "'"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "'\\x" + bytes(v).hex() + "'::bytea"
    return "'" + str(v).replace("'", "''") + "'"


def fill(sql, args=()):
    """`?` outside quotes / comments -> literal; `? IS NULL` gets a text cast like the app's driver layer."""
    args = list(args or ())
    out, i, n, k = [], 0, len(sql), 0
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(sql[i:j])
            i = j
        elif ch == "?":
            if k >= len(args):
                raise ValueError(f"not enough parameters for: {sql}")
            lit = _lit(args[k])
            k += 1
            if re.match(r"\s+IS\s+(NOT\s+)?NULL\b", sql[i + 1:], re.I):
                lit = f"CAST({lit} AS TEXT)"
            out.append(lit)
            i += 1
        else:
            out.append(ch)
            i += 1
    if k != len(args):
        raise ValueError(f"{len(args)} parameters for {k} placeholders: {sql}")
    return "".join(out)


_ROWS = re.compile(r"^\s*(\(?\s*SELECT|WITH|VALUES|SHOW|TABLE)\b", re.I)
_DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.I)


class Row(tuple):
    def __new__(cls, keys, vals):
        r = super().__new__(cls, vals)
        r._k = list(keys)
        return r

    def __getitem__(self, k):
        if isinstance(k, str):
            try:
                return tuple.__getitem__(self, self._k.index(k))
            except ValueError:
                low = [x.lower() for x in self._k]
                if k.lower() in low:
                    return tuple.__getitem__(self, low.index(k.lower()))
                raise IndexError(f"No item with that key: {k}") from None
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._k)


class Cursor:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount, self._i = rows, rowcount, 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        r, self._i = self._rows[self._i:], len(self._rows)
        return r

    def __iter__(self):
        return iter(self.fetchall())


class DbError(Exception):
    pass


IntegrityError = OperationalError = Error = DbError


def _psql(dbc, dbn, sql, timeout=60):
    p = subprocess.run(["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-d", dbn, "-X", "-q", "-A", "-t",
                        "-v", "ON_ERROR_STOP=1"], input=sql, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise DbError((p.stderr or p.stdout).strip())
    return p.stdout


class Conn:
    def __init__(self, path):
        self.dbc, self.dbn = _target(path)
        self.row_factory = None  # accepted (sqlite3.Row style); rows always answer to names

    def execute(self, sql, args=()):
        q = fill(sql, args).strip().rstrip(";")
        if _ROWS.match(q) or (_DML.match(q) and re.search(r"\bRETURNING\b", q, re.I)):
            if _DML.match(q):
                body = f"WITH _q AS ({q}) SELECT json_agg(row_to_json(_q)) FROM _q"
            else:
                body = f"SELECT json_agg(row_to_json(_q)) FROM ({q}) _q"
            out = _psql(self.dbc, self.dbn, body + ";\n").strip()
            data = json.loads(out) if out else None
            rows = [Row(list(o.keys()), list(o.values())) for o in (data or [])]
            return Cursor(rows, len(rows))
        if _DML.match(q):
            out = _psql(self.dbc, self.dbn, f"WITH _q AS ({q} RETURNING 1) SELECT count(*) FROM _q;\n").strip()
            return Cursor([], int(out or 0))
        _psql(self.dbc, self.dbn, q + ";\n")
        return Cursor([], -1)

    def executemany(self, sql, seq):
        n = 0
        for a in seq:
            n += max(self.execute(sql, a).rowcount, 0)
        return Cursor([], n)

    def executescript(self, sql):
        _psql(self.dbc, self.dbn, sql)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def connect(path, *_a, **_k):
    return Conn(path)


def q(path, sql, args=()):
    """One statement, the rows as a list (shortcut)."""
    return connect(path).execute(sql, args).fetchall()


if __name__ == "__main__":
    rows = connect(sys.argv[1]).execute(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else ()).fetchall()
    print(json.dumps([dict(zip(r.keys(), r)) for r in rows]))
