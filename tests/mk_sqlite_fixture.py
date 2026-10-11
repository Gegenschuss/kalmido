#!/usr/bin/env python3
"""2.37.0 (#1150): a synthetic SQLite database in the schema of Kalmido 2.36.2 (fixtures/sqlite-2.36.2.sql), for the move to
Postgres (p2370_m_api_test.py). Invented data only. Every table of the schema gets rows: the main ones in quantity
(people, two organisations, lists, sections, tasks with subtasks, comments, activity, notifications, list tags, office
documents with amounts, attachment rows, agents, agent chat), every other table a few generic rows.
usage: mk_sqlite_fixture.py OUT.db [--tasks N] [--comments N] [--activity N] [--broken text,json,comma,orphan] [--k23]
  --broken text    values SQLite stored as text in number columns ('' / 'true')
  --broken json    invalid / empty JSON in the jsonb columns of 2.37
  --broken comma   a decimal comma in an office amount (the move must stop)
  --broken orphan  a comment whose task is gone (SQLite with foreign keys off)
  --k23            a private agent (no workspace) as a member of an organisation's list
Prints a JSON summary (row counts per table, ids the test uses)."""
import argparse
import graphlib
import hashlib
import json
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "fixtures", "sqlite-2.36.2.sql")
PW = "password123"
TS = "2026-09-01T08:00:00+00:00"


def pw_hash(pw):
    """werkzeug's pbkdf2 format (few iterations: a test fixture)."""
    salt = "fixturesalt0001"
    return f"pbkdf2:sha256:1000${salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 1000).hex()}"


def ts(i):
    return f"2026-{1 + i % 9:02d}-{1 + i % 28:02d}T{i % 24:02d}:{i % 60:02d}:{(i * 7) % 60:02d}+00:00"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--tasks", type=int, default=20000)
    ap.add_argument("--comments", type=int, default=50000)
    ap.add_argument("--activity", type=int, default=50000)
    ap.add_argument("--broken", default="")
    ap.add_argument("--k23", action="store_true")
    a = ap.parse_args()
    broken = {x for x in a.broken.split(",") if x}
    rnd = random.Random(1150)
    if os.path.exists(a.out):
        os.remove(a.out)
    c = sqlite3.connect(a.out)
    fts = True
    try:
        c.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(x)")
        c.execute("DROP TABLE fts_probe")
    except sqlite3.Error:
        fts = False  # (a Python without FTS5: the message search table of 2.36 is left out, the move skips it anyway)
    stmt = ""
    for line in open(SCHEMA, encoding="utf-8"):
        if line.startswith("--") and not stmt:
            continue
        stmt += line
        if sqlite3.complete_statement(stmt):
            if fts or "msg_fts" not in stmt:
                c.execute(stmt)
            stmt = ""
    c.execute("PRAGMA foreign_keys=OFF")
    ins = lambda t, d: c.execute(f"INSERT INTO {t}({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values())).lastrowid  # noqa: E731

    # people, two organisations, two agents (one of organisation 1, one private)
    people = ["alice", "bob", "carol", "dave"]
    uid = {}
    for i, u in enumerate(people):
        uid[u] = ins("users", {"username": u, "display_name": u.title(), "password_hash": pw_hash(PW), "is_admin": int(u == "alice"),
                               "created_at": TS, "email": f"{u}@example.com"})
    for name in ("bot", "pbot"):
        uid[name] = ins("users", {"username": name, "display_name": name.title(), "kind": "agent", "created_at": TS})
    org1 = ins("orgs", {"name": "Alpha", "created_at": TS})
    org2 = ins("orgs", {"name": "Beta", "created_at": TS})
    for u, o in (("alice", org1), ("bob", org1), ("carol", org2), ("dave", org2), ("alice", org2)):
        ins("org_members", {"org_id": o, "user_id": uid[u], "role": "admin" if u == "alice" else "member"})
    ins("agents", {"user_id": uid["bot"], "created_at": TS, "owner_id": uid["alice"], "org_id": org1, "scopes": "read,write"})
    ins("agents", {"user_id": uid["pbot"], "created_at": TS, "owner_id": uid["alice"], "org_id": None, "scopes": "read,write"})
    org_of = {"alice": org1, "bob": org1, "carol": org2, "dave": org2}

    # lists (an inbox each + 8 more), sections, members
    lists, sec = [], {}
    for u in people:
        ins("lists", {"name": "Inbox", "is_inbox": 1, "created_at": TS, "owner_id": uid[u], "org_id": org_of[u]})
        for k in range(8):
            lid = ins("lists", {"name": f"{u.title()} {k}", "created_at": TS, "owner_id": uid[u], "org_id": org_of[u], "sort": k,
                                "rate": 85.5 if k == 0 else None, "kind": "project" if k == 1 else "list"})
            lists.append((lid, u))
            sec[lid] = [ins("sections", {"list_id": lid, "name": f"S{j}", "sort": j}) for j in range(3)]
    shared = next(l for l, u in lists if u == "alice")
    ins("list_members", {"list_id": shared, "user_id": uid["bob"], "role": "edit", "own_role": "edit", "added_at": TS})
    ins("list_members", {"list_id": shared, "user_id": uid["bot"], "role": "edit", "own_role": "edit", "added_at": TS})
    if a.k23:
        ins("list_members", {"list_id": shared, "user_id": uid["pbot"], "role": "edit", "own_role": "edit", "added_at": TS})
    # list tags; "Ärger" and "ärger" are two tags in SQLite (NOCASE folds ASCII only) and one under Postgres' lower()
    tags = {}
    for lid, _u in lists:
        tags[lid] = [ins("list_tags", {"list_id": lid, "name": n, "created_at": TS}) for n in ("Work", "home", "Urgent")]
    t_a = ins("list_tags", {"list_id": shared, "name": "Ärger", "created_at": TS})
    t_b = ins("list_tags", {"list_id": shared, "name": "ärger", "created_at": TS})

    # tasks (subtasks point to earlier AND later tasks), tags, comments, activity, notifications
    n_tasks = a.tasks
    tids = []
    for i in range(1, n_tasks + 1):
        lid, u = lists[i % len(lists)]
        tids.append(ins("tasks", {"id": i, "list_id": lid, "section_id": sec[lid][i % 3], "title": f"Task {i} " + ("Ärger" if i % 50 == 0 else "Arbeit"),
                                  "content": "Notiz\nmit Zeilen" if i % 7 == 0 else "", "priority": i % 4, "status": 1 if i % 5 == 0 else 0,
                                  "due": f"2026-10-{1 + i % 28:02d}" if i % 3 == 0 else None, "sort": i * 1.5, "created_at": ts(i),
                                  "updated_at": ts(i), "completed_at": ts(i) if i % 5 == 0 else None, "created_by": uid[u],
                                  "duration": 30 if i % 11 == 0 else None}))
    for i in range(2, n_tasks + 1, 97):  # subtasks: parent before and after the child
        par = i - 1 if (i // 97) % 2 else min(n_tasks, i + 3)
        if par != i and tids[par - 1]:
            c.execute("UPDATE tasks SET parent_id=?, list_id=(SELECT list_id FROM tasks WHERE id=?) WHERE id=?", (par, par, i))
    for i in range(1, n_tasks + 1, 3):
        lid = c.execute("SELECT list_id FROM tasks WHERE id=?", (i,)).fetchone()[0]
        c.execute("INSERT OR IGNORE INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (i, tags[lid][i % 3]))
        c.execute("INSERT OR IGNORE INTO task_tags(task_id,user_id,tag) VALUES(?,?,?)", (i, uid["alice"], "t%d" % (i % 9)))
    in_shared = [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=? ORDER BY id LIMIT 2", (shared,))]
    c.execute("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (in_shared[0], t_a))
    c.execute("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (in_shared[0], t_b))  # both: one row after merging
    c.execute("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (in_shared[1], t_b))
    words = ["Ärger mit dem Drucker", "Besprechung morgen", "Größe passt", "Rechnung geprüft", "Ein Kommentar"]
    for i in range(1, a.comments + 1):
        ins("comments", {"task_id": 1 + (i * 7) % n_tasks, "user_id": uid[people[i % 4]], "body": f"{words[i % 5]} {i}", "created_at": ts(i)})
    for i in range(1, a.activity + 1):
        ins("activity", {"task_id": 1 + (i * 13) % n_tasks, "user_id": uid[people[i % 4]], "kind": "edit",
                         "data": json.dumps({"field": "title", "n": i}), "created_at": ts(i)})
    for i in range(1, 2001):
        ins("notifications", {"user_id": uid[people[i % 4]], "kind": "comment", "task_id": 1 + i % n_tasks, "actor_id": uid["bob"],
                              "data": json.dumps({"i": i}), "created_at": ts(i), "read_at": ts(i) if i % 2 else None})
    for i in range(1, 501):
        ins("attachments", {"task_id": 1 + (i * 31) % n_tasks, "name": f"file{i}.txt", "mime": "text/plain", "size": 100 + i,
                            "path": f"{1 + (i * 31) % n_tasks}/file{i}.txt", "created_at": ts(i), "user_id": uid["alice"]})
    for i in range(1, 201):
        ins("agent_chat", {"agent_id": uid["bot"], "user_id": uid["alice"], "sender": "agent" if i % 2 else "user", "body": f"Hallo {i}",
                           "created_at": ts(i), "choices": json.dumps(["Ja", "Nein"]) if i % 10 == 0 else None})
    for i in range(1, min(300, n_tasks) + 1):
        ins("time_entries", {"user_id": uid["alice"], "task_id": i, "list_id": c.execute("SELECT list_id FROM tasks WHERE id=?", (i,)).fetchone()[0],
                             "start": ts(i), "end": ts(i + 1), "seconds": 600 + i, "created_at": ts(i), "updated_at": ts(i)})
    # office: documents with amounts (REAL in 2.36, NUMERIC(14,4) in 2.37)
    docs = []
    for i in range(1, 41):
        o = org1 if i % 2 else org2
        d = ins("office_docs", {"org_id": o, "number": f"A-{i:04d}", "fx_rate": 1.0 if i % 3 else 1.0825, "discount_pct": 5.5 if i % 4 == 0 else None,
                                "created_at": ts(i), "updated_at": ts(i), "created_by": uid["alice"]})
        docs.append(d)
        for j in range(5):
            ins("office_doc_items", {"doc_id": d, "sort": j, "title": f"Leistung {j}", "qty": 0.5 + j, "rate": 1234.5678 + j,
                                     "cost": 99.99, "org_id": o})

    # every other table: a few generic rows (defaults where the schema has one)
    done = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'") if c.execute(f'SELECT 1 FROM "{r[0]}" LIMIT 1').fetchone()}
    # (generic rows -- passkeys, recovery codes, sessions ... -- only for dave: the test signs in as alice)
    ids = {"users": [uid["dave"]], "tasks": tids[:50], "lists": [l for l, _u in lists], "orgs": [org1, org2]}
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'msg_fts%'")]
    deps = {t: {r[2] for r in c.execute(f'PRAGMA foreign_key_list("{t}")')} - {t} for t in names}
    for t in graphlib.TopologicalSorter(deps).static_order():  # parents first
        if t in done or t not in names:
            continue
        cols = c.execute(f'PRAGMA table_info("{t}")').fetchall()
        fks = {r[3]: r[2] for r in c.execute(f'PRAGMA foreign_key_list("{t}")')}
        for n in range(1, 4):
            row = {}
            for _cid, col, ty, notnull, dflt, pk in cols:
                if pk and col == "id":
                    continue
                if col in fks:
                    pool = ids.get(fks[col]) or [r[0] for r in c.execute(f'SELECT id FROM "{fks[col]}" LIMIT 20')]
                    if not pool:
                        if notnull:
                            row = None
                            break
                        continue
                    row[col] = pool[(n * 3) % len(pool)]
                elif dflt is not None or not notnull and not pk:
                    continue
                elif ty.upper() == "INTEGER":
                    row[col] = n
                elif ty.upper() == "REAL":
                    row[col] = n + 0.25
                elif ty.upper() == "BLOB":
                    row[col] = bytes([n, 0, 255, 10, 9])
                elif col.endswith("_at") or col in ("day", "date", "start", "end"):
                    row[col] = ts(n)
                else:
                    row[col] = f"{t}-{col}-{n}"
            if row is None:
                break
            try:
                ins(t, row)
            except sqlite3.Error:
                pass

    # damaged values (what a long-lived SQLite database may hold)
    if "text" in broken:
        c.execute("UPDATE tasks SET priority='' WHERE id=3")         # NOT NULL with default -> default
        c.execute("UPDATE tasks SET duration='' WHERE id=4")         # nullable -> NULL
        c.execute("UPDATE tasks SET pinned='true' WHERE id=6")       # -> 1
        c.execute("UPDATE lists SET sort='  7 ' WHERE id=2")          # number with blanks -> 7
    if "json" in broken:
        c.execute("UPDATE activity SET data='kaputt{' WHERE id=1")
        c.execute("UPDATE notifications SET data='' WHERE id=1")
        c.execute("UPDATE agent_chat SET choices='[' WHERE id=10")
    if "comma" in broken:
        c.execute("UPDATE office_doc_items SET rate='12,50' WHERE id=3")
    if "orphan" in broken:
        ins("comments", {"task_id": n_tasks + 999, "user_id": uid["alice"], "body": "orphan", "created_at": TS})
    c.commit()
    out = {"tables": {r[0]: c.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0]
                      for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'msg_fts%' AND name NOT LIKE 'sqlite_%'").fetchall()},
           "users": uid, "orgs": [org1, org2], "shared_list": shared, "tags": [t_a, t_b], "fts": fts}
    c.close()
    print(json.dumps(out))


if __name__ == "__main__":
    sys.exit(main())
