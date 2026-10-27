#!/usr/bin/env python3
# kalmido-suite: after=p2235_b2_jobs nodata
"""2.235.0 B2 (#2902): the data lock check stays cheap in loops (review finding 2) - core/dlock.py on its own, no server.
 - dl_task_hidden in a write / without a request (cleanup, batch, the burst guard, events of a person's write) asks for the
   one task and its parents: no query over all the agent's lists (list_members) per task, the task id as the parameter
 - in a GET the set is computed once and reused for every further check
 - dl_task_sql: up to DL_INLINE_MAX ids inline, more = one array constant (no SQL with thousands of numbers)
usage: p2235_b2_perf_test.py"""
import importlib.util
import os
import sys
import types

from kt import check, done

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kalmido", "core", "dlock.py")
CTX = {"on": False}
fl = types.ModuleType("flask")  # the three names dlock.py takes from flask, the request switched by ctx()
fl.g, fl.request, fl.has_request_context = {}, types.SimpleNamespace(method="GET"), lambda: CTX["on"]
sys.modules["flask"] = fl
for name in ("kalmido", "kalmido.core"):
    m = types.ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m
acc = types.ModuleType("kalmido.core.access")
acc.acx_lists_sql = lambda write=False, req=True, ov=True: "(SELECT l.id FROM lists l WHERE l.owner_id=? OR l.id IN (SELECT list_id FROM list_members WHERE user_id=?))"
sys.modules["kalmido.core.access"] = acc
spec = importlib.util.spec_from_file_location("kalmido.core.dlock", SRC)
dl = importlib.util.module_from_spec(spec)
sys.modules["kalmido.core.dlock"] = dl
spec.loader.exec_module(dl)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Conn:
    """Records every statement; the agent (id 7) has the default lock (private e-mails), tasks 1..N are locked."""
    def __init__(self, locked):
        self.sql, self.locked = [], locked

    def execute(self, sql, args=()):
        self.sql.append((sql, tuple(args)))
        if "FROM users u" in sql:
            return Rows([("agent", "")])
        if "WITH RECURSIVE" in sql and "list_members" in sql:
            return Rows([(x,) for x in self.locked])
        if "WITH RECURSIVE" in sql:
            return Rows([(x,) for x in args if x in self.locked])
        return Rows([])


def scans(c):
    return [s for s, _ in c.sql if "list_members" in s]


def ctx(method):
    """A new request (empty caches) with this method."""
    fl.g.clear()
    CTX["on"], fl.request.method = True, method


# without a request (the burst guard) and in a write request: one small query per task, never the whole scope
c = Conn({1, 2})
check(dl.dl_task_hidden(c, 1, 7) and not dl.dl_task_hidden(c, 5, 7), "no request: the locked / the plain task")
check(not scans(c), f"no request: no query over all lists per task {scans(c)[:1]}")
ctx("POST")
c = Conn({1, 2})
hits = [t for t in range(1, 301) if dl.dl_task_hidden(c, t, 7)]
check(hits == [1, 2], f"write: the right tasks {hits}")
check(not scans(c), f"write: 300 checks, no query over all lists ({len(scans(c))})")
per = [a for s, a in c.sql if "WITH RECURSIVE" in s]
check(len(per) == 300 and all(len(a) == 1 for a in per), "write: one query per task with its id only")
# a GET: the set once, then from the cache
ctx("GET")
c = Conn({1, 2})
hits = [t for t in range(1, 301) if dl.dl_task_hidden(c, t, 7)]
check(hits == [1, 2] and len(scans(c)) == 1, f"GET: one query for 300 checks ({len(scans(c))})")
# many locked ids: one array constant
ctx("GET")
c = Conn(set(range(1, 2001)))
sql = dl.dl_task_sql(c, 7, "t.")
check("ANY(CAST('{1,2,3," in sql and "NOT IN" not in sql, f"2000 ids: an array constant ({sql[:80]})")
ctx("GET")
c = Conn({4, 9})
check(dl.dl_task_sql(c, 7, "t.") == " AND t.id NOT IN (4,9)", "a few ids stay inline")
sys.exit(done("p2235_b2_perf"))
