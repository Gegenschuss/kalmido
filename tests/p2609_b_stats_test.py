#!/usr/bin/env python3
# kalmido-suite:
"""2.609.0 B (#4613): what someone read is no work done -- invented names only.
 (S1) a ticked-off "Read later" entry leaves the statistics (done per day / week, total, per project, on time, streak)
 (S2) and the day / week review (done); a ticked-off contract (another area's store list) still counts in both
 (S3) the same for a person without an organisation (freelancer parity)
usage: p2609_b_stats_test.py <datadir>
freelancer-matrix: personal, tasks"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

kt.fresh(prefix="P2609B")
A = kt.setup()
FEAT = "cal,stats,review,reading,contracts,life"
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
FID, Fr = freelancer(B, A, features=FEAT)


def run(s, who):
    rd = s.post(B + "/api/reading", json={"url": f"https://example.com/article-{who.lower()}", "title": f"Long read {who}"})
    check(rd.status_code in (200, 201), f"S1 {who}: a link saved to read later {rd.text[:200]}")
    rd = rd.json()
    ct = s.post(B + "/api/life/contracts", json={"name": f"Insurance {who}", "cost": 10, "per": "month", "ends": testclock.today().isoformat()})
    check(ct.status_code == 201, f"S2 {who}: a contract {ct.text[:200]}")
    ct = ct.json()
    pl = s.post(B + "/api/tasks", json={"title": f"Real work {who}"}).json()
    for t in (rd["task_id"], ct["id"], pl["id"]):
        r = s.post(B + f"/api/tasks/{t}/complete")
        check(r.ok, f"{who}: ticked off {t} {r.text[:120]}")
    st = s.get(B + "/api/stats").json()
    dn = st["done"]
    ids = {x["id"] for x in dn["by_list"]}
    # without the fix: total 3, today 3 and the read-later project in by_list
    check(dn["total"] == 2 and dn["today"] == 2 and dn["this_week"] == 2, f"S1 {who}: the reading does not count {dn}")
    check(rd["list_id"] not in ids and ct["list_id"] in ids, f"S1 {who}: per project without Read later, the contracts count {dn['by_list']}")
    check(sum(dn["per_day"].values()) == 2 and st["streak"]["current"] >= 1, f"S1 {who}: per day and the streak {st['streak']}")
    for period in ("day", "week"):
        rv = s.get(B + "/api/life/review", params={"period": period}).json()
        got = {x["list_id"] for x in rv.get("done", [])}  # the done copy of the (recurring) contract task has its own id
        check(rd["list_id"] not in got and ct["list_id"] in got and pl["list_id"] in got, f"S2 {who}: the {period} review without the reading {rv.get('done')}")


run(A, "Alice")
run(Fr, "Frida")  # S3
sys.exit(kt.done("p2609_b_stats"))
