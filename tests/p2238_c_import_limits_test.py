#!/usr/bin/env python3
"""2.238.0 C (#2873): the importers stop at the task limit WHILE parsing (Markdown lines, ClickUp checklists), one byte
budget covers a Notion ZIP and the ZIPs inside it, and zipread neither unpacks an entry whose header is already too
large nor reads unlimited bytes only to throw them away. Own container (30 tasks, 1 MB); the zipread unit part needs no
server. Everything is generated here.
freelancer-matrix: import
usage: p2238_c_import_limits_test.py <datadir>"""
import importlib.util
import io
import json
import os
import sys
import types
import zipfile


N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")


# ---------------------------------------------------------------- zipread, unit (a stub package gives it its tr())
def load_zipread():
    pkg = types.ModuleType("zrpkg")
    pkg.__path__ = []
    sys.modules["zrpkg"] = pkg
    i18n = types.ModuleType("zrpkg.i18n")
    i18n.tr = lambda k, *a, **kw: k.format(*a) if a else k
    sys.modules["zrpkg.i18n"] = i18n
    spec = importlib.util.spec_from_file_location("zrpkg.zipread", os.path.join(SRC, "kalmido", "core", "zipread.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_zip(members):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as f:
        for n, d in members:
            f.writestr(n, d)
    return b.getvalue()


zr = load_zipread()
MB = 1024 * 1024
z = zr.zip_read(make_zip([("ok.txt", b"hello"), ("big.txt", b"y" * 5000)]), (".txt",), 1000, 10 * MB)
check([n for n, _ in z.files] == ["ok.txt"] and len(z.errors) == 1 and z.errors[0]["file"] == "big.txt",
      "zipread: a valid file is read, the too large one is an error entry")
# an entry whose header says "too large" is an error entry, never unpacked; a lying small header gives at most that many bytes
raw = bytearray(make_zip([("a.txt", b"z" * 3000), ("b.txt", b"z" * 3000)]))
for sig, off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):  # local + central header: uncompressed size -> 10
    i = 0
    while True:
        i = raw.find(sig, i)
        if i < 0:
            break
        raw[i + off:i + off + 4] = (10).to_bytes(4, "little")
        i += 4
z = zr.zip_read(bytes(raw), (".txt",), 1000, 10 * MB)
check(all(len(d) <= 10 for _, d in z.files), "zipread: a lying small header never yields more than its size")
z = zr.zip_read(make_zip([("h.txt", b"y" * 5000)] * 1), (".txt",), 1000, 10 * MB)
check(z.errors and not z.files and z.size == 0, "zipread: an entry too large by its header adds nothing to the size")

# ---------------------------------------------------------------- importers, server
kt.fresh(env={"KALMIDO_IMPORT_MAX_TASKS": "30", "KALMIDO_IMPORT_RATE": "1000"})
A = kt.setup()


def imp(s, src, name, data):
    r = s.post(f"{B}/api/import/{src}", files={"file": (name, data)}, data={"dry_run": "1"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def many_md(n):
    return ("# List\n" + "".join(f"- [ ] task {i}\n" for i in range(n))).encode()


def notion_zip(inner_files, nested=()):
    members = [(n, d) for n, d in inner_files]
    for n, items in nested:
        members.append((n, make_zip(items)))
    return make_zip(members)


for who, S in (("admin", A), ("freelancer", freelancer(B, A)[1])):
    st, j = imp(S, "markdown", "ok.md", many_md(5))
    check(st == 200, f"{who}: a small Markdown import goes on ({st})")
    st, j = imp(S, "markdown", "many.md", many_md(31))
    check(st == 400 and "Too many tasks" in j.get("error", ""), f"{who}: Markdown over the limit is refused ({st} {str(j)[:80]})")
    # ClickUp: one row, a checklist cell with far more items than the limit
    cl = json.dumps([{"name": "c", "items": [f"i{k}" for k in range(40)]}])
    head = "Task ID,Task Name,Checklists\n"
    row = '1,"Big","' + cl.replace('"', '""') + '"\n'
    st, j = imp(S, "clickup", "cu.csv", (head + row).encode())
    check(st == 400 and "Too many tasks" in j.get("error", ""), f"{who}: ClickUp checklist over the limit is refused ({st} {str(j)[:80]})")
    # Notion: pages count too, also inside a ZIP inside the ZIP
    z1 = notion_zip([], nested=[("part1.zip", [("Page abc123.md", many_md(31))])])
    st, j = imp(S, "notion", "n.zip", z1)
    check(st == 400 and "Too many tasks" in j.get("error", ""), f"{who}: Notion with an inner ZIP over the limit is refused ({st} {str(j)[:80]})")
    z2 = notion_zip([], nested=[("part1.zip", [("Page abc123.md", many_md(5))])])
    st, j = imp(S, "notion", "n.zip", z2)
    check(st == 200, f"{who}: a small Notion ZIP with an inner ZIP goes on ({st} {str(j)[:80]})")
    # 2.238.0 (#2873, review): the checkboxes of database row pages count against the same limit at once (31, not the sum 42)
    box = lambda n: ("# Row\n\n" + "".join(f"- [ ] s{i}\n" for i in range(n))).encode()  # noqa: E731
    z3 = notion_zip([("Tasks.csv", b"Name\nRow A\nRow B\n"), ("Tasks/Row A.md", box(20)), ("Tasks/Row B.md", box(20))])
    st, j = imp(S, "notion", "n.zip", z3)
    check(st == 400 and "Too many tasks: 31" in j.get("error", ""), f"{who}: Notion row pages stop at the limit ({st} {str(j)[:80]})")

sys.exit(kt.done("p2238_c_import_limits"))
