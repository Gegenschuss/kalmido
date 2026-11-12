#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1002.0 A (#5695): the core's delete for good (core/writes.py _purge_rows: obj_purge, obj_trash_prune, office/okern.py
ofk_purge) takes the history and the undo steps of an office row along -- also the ones its saves wrote under the TRACKED
kind of its table (office/owrite.py ow_kind: office_meal, office_fixed_cost), not only under its trash kind (omeal, ofixed).
Before, the obj_history / obj_undo rows of a purged entertainment receipt or fixed cost stayed behind. Invented names only.
 - an entertainment receipt of a person without an organisation: saved twice (history + undo steps), into the trash, deleted
   for good from her office trash -> no obj_history / obj_undo row of it under any kind
 - a fixed cost of hers: saved, into the trash, past the trash period -> the core's retention run (obj_trash_prune) purges it
   and its rows the same way
 - every office row in the core's trash: no history / undo row of a tracked kind on its table points at a row that is gone
freelancer-matrix: office (a person without an organisation: her receipt and fixed cost purged with their history)
usage: p21002_a_purge_history_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21002A")
OFF = B + "/api/office"
OLD = "2020-01-02T03:04:05.000Z"
U = {"X-Kalmido-Undo": "a1b2c3d4e5f60718293a4b5c"}  # an editor session: each save is also one step of it

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["office", "clients"]})
FID, Fr = freelancer(B, A)


def rows(kinds, rid):
    """(history rows, undo rows) of ref_id rid under kinds."""
    q = ",".join("?" * len(kinds))
    h = dbx(f"SELECT COUNT(*) FROM obj_history WHERE kind IN ({q}) AND ref_id=?", (*kinds, rid))[0][0]
    u = dbx(f"SELECT COUNT(*) FROM obj_undo WHERE kind IN ({q}) AND ref_id=?", (*kinds, rid))[0][0]
    return h, u


def tick():
    """The core's retention run as the watchdog runs it, switch on (force: no hourly wait) -> its counts."""
    out = in_app("import json, os\nos.environ['KALMIDO_PURGE_TRASH'] = '1'\nfrom kalmido.core.writes import obj_trash_tick\n"
                 "print('TICK', json.dumps(obj_trash_tick(c, force=True)))")
    try:
        return json.loads(out.rsplit("TICK ", 1)[1].splitlines()[0])
    except (IndexError, ValueError):
        print(out[-800:])
        return {}


# ---------------------------------------------------------------- an entertainment receipt: purged from the office trash
r = Fr.post(OFF + "/meals", json={"date": "2025-05-14", "place_name": "Example Bistro", "occasion": "Kick-off of the example"})
check(r.status_code == 201, f"setup: her receipt {r.status_code} {r.text[:200]}")
MID = r.json().get("id")
for occ in ("Second example meeting", "Third example meeting"):
    r = Fr.patch(OFF + f"/meals/{MID}", json={"occasion": occ}, headers=U)
    check(r.ok, f"saved: {occ} {r.status_code} {r.text[:200]}")
hist = Fr.get(OFF + f"/meals/{MID}/history")
check(hist.ok and len(hist.json().get("items") or []) >= 1, f"her receipt has a history she can read {hist.text[:200]}")
h, u = rows(("omeal", "office_meal"), MID)
check(h >= 1 and u >= 1, f"before: history {h} and undo steps {u} of her receipt")
r = Fr.delete(OFF + f"/meals/{MID}")
check(r.ok and (r.json().get("trash") or {}).get("kind") == "omeal", f"into the trash {r.text[:200]}")
check(any(x.get("core") == "omeal" and x["id"] == MID for x in Fr.get(OFF + "/trash").json().get("items", [])),
      "it lies in her office trash")
r = Fr.delete(OFF + f"/trash/core/omeal/{MID}")
check(r.ok and not dbx("SELECT 1 FROM office_meals WHERE id=?", (MID,)), f"deleted for good from her office trash {r.text[:200]}")
h, u = rows(("omeal", "office_meal"), MID)
check((h, u) == (0, 0), f"#5695: no history ({h}) and no undo step ({u}) of the purged receipt left")
check(not any(x.get("core") == "omeal" and x["id"] == MID for x in Fr.get(OFF + "/trash").json().get("items", [])),
      "gone from her office trash")

# ---------------------------------------------------------------- a fixed cost: purged by the core's retention run
r = Fr.post(OFF + "/fixed-costs", json={"label": "Example Rent", "amount": "700", "start": "2026-01-01", "repeat": "monthly"})
check(r.status_code == 201, f"setup: her fixed cost {r.status_code} {r.text[:200]}")
FC = r.json().get("id")
r = Fr.patch(OFF + f"/fixed-costs/{FC}", json={"label": "Example Rent, new"}, headers=U)
check(r.ok and r.json().get("label") == "Example Rent, new", f"saved {r.status_code} {r.text[:200]}")
h, u = rows(("ofixed", "office_fixed_cost"), FC)
check(h >= 1 and u >= 1, f"before: history {h} and undo steps {u} of her fixed cost")
r = Fr.delete(OFF + f"/fixed-costs/{FC}")
check(r.ok and (r.json().get("trash") or {}).get("kind") == "ofixed", f"into the trash {r.text[:200]}")
dbx("UPDATE office_fixed_costs SET deleted_at=? WHERE id=?", (OLD, FC))
n = tick()
check(not dbx("SELECT 1 FROM office_fixed_costs WHERE id=?", (FC,)) and n.get("ofixed", 0) >= 1,
      f"the retention run purged it after the trash period {n}")
h, u = rows(("ofixed", "office_fixed_cost"), FC)
check((h, u) == (0, 0), f"#5695: no history ({h}) and no undo step ({u}) of the purged fixed cost left")
check([x["id"] for x in Fr.get(OFF + "/fixed-costs").json().get("items") or []] == [], "her fixed costs list is empty")

# ---------------------------------------------------------------- every office kind of the core's trash: nothing orphaned
out = in_app("import json\nfrom kalmido.office.okern import OFK\nfrom kalmido.core.writes import OBJ_TRACK, _purge_kinds\n"
             "from kalmido.core.objects import OBJ\nres = {}\n"
             "for k, v in sorted(OFK.items()):\n"
             "    kinds = _purge_kinds(k, OBJ[k])\n"
             "    tracked = sorted(t for t, x in OBJ_TRACK.items() if x['table'] == v['table'])\n"
             "    left = c.execute(f\"SELECT COUNT(*) FROM obj_history h WHERE h.kind = ANY(CAST(? AS TEXT[])) AND NOT EXISTS \"\n"
             "                     f\"(SELECT 1 FROM {v['table']} t WHERE t.id = h.ref_id)\", (kinds,)).fetchone()[0]\n"
             "    res[k] = [all(t in kinds for t in tracked), left]\n"
             "print('OFK', json.dumps(res))")
try:
    res = json.loads(out.rsplit("OFK ", 1)[1].splitlines()[0])
except (IndexError, ValueError):
    print(out[-800:])
    res = {}
check("omeal" in res and "ofixed" in res, f"the office kinds of the core's trash are read {sorted(res)}")
bad = {k: v for k, v in res.items() if v != [True, 0]}
check(not bad, f"#5695: every office kind purges the tracked kinds of its table, no orphaned history: {bad}")

sys.exit(done("p21002_a_purge_history"))
