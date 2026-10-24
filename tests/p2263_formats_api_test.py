#!/usr/bin/env python3
"""2.263.0 (#2976) API tests, own container (kt.fresh): typed numbers keep their value in every language.
 - core/numtext.py on its own: "1,5", "1,500", "1.500", "1.234,50", "0.856" per decimal sign (de / en / neutral), wrong order
   = no number, a rate (frac) never as thousands
 - task fields: "1,500" from an English user = 1500 (was 1.5), "1,5" from a German user = 1.5; a point alone is always the
   decimal sign (the app sends plain "123.456": stored values, undo, templates must not change with the language)
 - clients: an hourly rate "1,500" in English = 1500
 - tables: a number column stores "1,500" (English) and "1.500" (German) plainly as 1500 - every viewer reads the writer's
   number; "1,5" in German stays as typed (= 1.5); a text column keeps any text
Both people have no organisation (the readers do not ask for one).
"""
import importlib.util
import os
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("numtext", os.path.join(SRC, "kalmido", "core", "numtext.py"))
nt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nt)

# ---- the reader on its own: [input, German, English, neutral]
CASES = [("1,5", 1.5, 1.5, 1.5), ("1,500", 1.5, 1500, 1.5), ("1.500", 1500, 1.5, 1.5), ("1.234,50", 1234.5, None, 1234.5),
         ("1,234.50", None, 1234.5, 1234.5), ("0.856", 0.856, 0.856, 0.856), ("0,856", 0.856, 0.856, 0.856),
         ("15,000", 15, 15000, 15), ("1.234.567", 1234567, None, 1234567), ("1,2,3", None, None, None), ("-3", -3, -3, -3),
         ("1 500,25", 1500.25, 1500.25, 1500.25), ("abc", None, None, None), ("", None, None, None)]
bad = [f"{s}: {nt.parse_num(s, d)} want {w} ({d})" for s, *ws in CASES for d, w in zip((",", ".", None), ws) if nt.parse_num(s, d) != w]
check(not bad, "#2976: core/numtext.py reads every case " + "; ".join(bad))
check(nt.parse_num("1.234", ",", True) == 1.234 and nt.parse_num("1,234", ".", True) == 1.234, "#2976: a rate (frac) is never thousands")
check(nt.dec_char("en") == "." and all(nt.dec_char(x) == "," for x in ("de", "fr", "es", "it", "nl")), "#2976: the decimal sign per language")

kt.fresh()
A = kt.setup(lang="en")
check(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).ok, "bob")
Bo = sess("bob")
for s, lg in ((A, "en"), (Bo, "de")):
    s.patch(B + "/api/settings", json={"lang": lg, "tour": "done", "features": "fields,clients,sheets,comments"})


def task_field(s, tid, fid):
    j = s.get(B + f"/api/tasks/{tid}").json()
    return ((j.get("task") or j).get("fields") or {}).get(str(fid))


# ---- task fields (#2976)
for s, who in ((A, "alice"), (Bo, "bob")):
    lid = s.post(B + "/api/lists", json={"name": f"Budget {who}"}).json()["id"]
    fid = s.post(B + f"/api/lists/{lid}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
    tid = s.post(B + "/api/tasks", json={"title": "Film", "list_id": lid}).json()["id"]
    want = {"alice": [("1,500", "1500"), ("12,5", "12.5"), ("123.456", "123.456"), ("1,234.50", "1234.5")],
            "bob": [("1,5", "1.5"), ("1.234,50", "1234.5"), ("123.456", "123.456"), ("1500", "1500")]}[who]
    for v, w in want:
        r = s.patch(B + f"/api/tasks/{tid}", json={"fields": {str(fid): v}})
        got = task_field(s, tid, fid)
        check(r.ok and got == w, f"#2976: {who} field {v!r} = {w} (got {got!r}, {r.status_code} {r.text[:120] if not r.ok else ''})")
    r = s.patch(B + f"/api/tasks/{tid}", json={"fields": {str(fid): 2500.5}})
    check(r.ok and task_field(s, tid, fid) == "2500.5", f"#2976: {who} a number as a number")
    check(s.patch(B + f"/api/tasks/{tid}", json={"fields": {str(fid): "zwölf"}}).status_code == 400, f"#2976: {who} no number = 400")

# ---- clients: the hourly rate (#2976)
r = A.post(B + "/api/clients", json={"name": "Example Ltd", "rate": "1,500"})
cid = (r.json().get("client") or r.json()).get("id") if r.ok else None
rate = next((x.get("rate") for x in A.get(B + "/api/clients").json().get("clients", []) if x.get("id") == cid), None) if cid else None
check(r.ok and rate is not None and float(rate) == 1500, f"#2976: a client's rate '1,500' in English = 1500 ({r.status_code} {rate} {r.text[:160]})")

# ---- tables: number columns store the writer's number plainly (#2976)
for s, who, rows in ((A, "alice", [("1,500", "1500", 1500), ("12,5", "12,5", 12.5), ("2.5", "2.5", 2.5)]),
                     (Bo, "bob", [("1.500", "1500", 1500), ("1,5", "1,5", 1.5), ("1.234,50", "1.234,50", 1234.5)])):
    r = s.post(B + "/api/sheets", json={"title": f"Zahlen {who}"})
    check(r.status_code == 201, f"{who}: a table {r.status_code} {r.text[:160]}")
    if r.status_code != 201:
        continue
    sid = r.json()["id"]
    col = s.post(B + f"/api/sheets/{sid}/columns", json={"title": "Betrag", "kind": "number"}).json()["column"]["letter"]
    cells = [{"cell": f"{col}{i + 1}", "raw": raw} for i, (raw, _st, _v) in enumerate(rows)] + [{"cell": f"A{len(rows) + 1}", "raw": "1,500"}]
    r = s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})
    check(r.ok, f"{who}: cells {r.status_code} {r.text[:200]}")
    d = s.get(B + f"/api/sheets/{sid}").json()
    at = {x["addr"]: x for x in d.get("cells", [])}
    for i, (raw, stored, val) in enumerate(rows):
        x = at.get(f"{col}{i + 1}") or {}
        check(x.get("raw") == stored and x.get("value") == val, f"#2976: {who} table {raw!r} -> raw {stored!r} value {val} (got {x.get('raw')!r} {x.get('value')!r})")
    check((at.get(f"A{len(rows) + 1}") or {}).get("raw") == "1,500", f"#2976: {who} a text column keeps the text as typed")

sys.exit(kt.done("p2263_formats_api"))
