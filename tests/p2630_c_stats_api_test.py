#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.630.0 (#4617): the statistics count contracts, health and travel (freelancer-matrix: personal). Invented data only.
 - GET /api/stats has the keys contracts / health / travel, each only while its module is on (module off = the key is missing)
 - contracts: running ones (a term that is over and does not renew is not), cost per month / year from cost / per, the
   deadlines to cancel of the next 90 days, by provider (spellings together, "" = without a provider, by cost descending)
 - health per person (fam.who, "" = me, spellings together): done appointments in the last 12 weeks per week, the next
   due one, the overdue ones; medication apart as intakes done x of y; never in an organisation's view
 - travel: trips and travel days of the last 12 months and of this year, the travel expenses made from a trip, the next trip;
   ?space= narrows (an organisation's trip only there)
 - GET /api/v1/stats: a token without the scope private gets no health block (names included), with it the same as the app
 - a person without an organisation: the same blocks, ?space=private the same numbers
usage: p2630_c_stats_api_test.py <datadir>      (P2630C_NOSTART=1: a running server)"""
import sys
from datetime import date, timedelta

import requests
from freelancer_fixture import FEATURES, freelancer
from kt import B, check, done, fresh, setup

fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2630C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
st = A.get(B + "/api/stats")
check(st.ok, f"setup: the statistics answer {st.status_code}")
T = date.fromisoformat(st.json()["today"])
D = lambda n: (T + timedelta(days=n)).isoformat()  # noqa: E731


def post(s, url, body, what):
    r = s.post(B + url, json=body)
    check(r.ok, f"setup: {what} {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


# ================================================================ contracts
post(A, "/api/life/contracts", {"name": "Strom", "provider": "Stadtwerke", "cost": 60, "per": "month", "ends": D(40), "notice": 1,
                                "notice_unit": "m"}, "a contract (power)")
post(A, "/api/life/contracts", {"name": "Gas", "provider": "  stadtwerke ", "cost": 120, "per": "quarter", "ends": D(300)}, "a contract (gas)")
post(A, "/api/life/contracts", {"name": "Wasser", "provider": "STADTWERKE", "ends": D(200)}, "a contract without a cost")
post(A, "/api/life/contracts", {"name": "Zeitung", "cost": 120, "per": "year", "ends": D(150)}, "a contract without a provider")
post(A, "/api/life/contracts", {"name": "Altvertrag", "provider": "Alt", "cost": 999, "ends": D(-10), "renew_months": 0}, "a contract whose term is over")
j = A.get(B + "/api/stats").json()
c = j.get("contracts") or {}
check(c.get("count") == 4, f"#4617: four running contracts (the ended one not): {c.get('count')}")
check(c.get("monthly") == 110 and c.get("yearly") == 1320, f"#4617: cost per month 60 + 40 + 10, per year x12: {c.get('monthly')} {c.get('yearly')}")
check([x["name"] for x in c.get("notice", [])] == ["Strom"] and c.get("notice_days") == 90 and 0 <= c["notice"][0]["days"] <= 90,
      f"#4617: the deadline to cancel of the next 90 days: power only {c.get('notice')}")
bp = c.get("by_provider") or []
check([(x["name"], x["n"], x["monthly"]) for x in bp] == [("Stadtwerke", 3, 100), ("", 1, 10)],
      f"#4617: by provider, spellings together, without a provider last, by cost: {bp}")
check(all(k in j for k in ("done", "ontime", "streak", "overdue", "focus")), "the other statistics stay")

# ================================================================ health
post(A, "/api/life/health", {"type": "appointment", "title": "Kinderarzt", "who": "Anna", "date": D(-3)}, "a past appointment")
past = A.get(B + "/api/life").json()["health"]["items"]
pid = next((x["task_id"] for x in past if x["title"] == "Kinderarzt"), None)
check(pid and A.post(B + f"/api/tasks/{pid}/complete", json={}).ok, "setup: the appointment done")
post(A, "/api/life/health", {"type": "checkup", "title": "Zahnarzt", "who": " anna ", "date": D(5)}, "a coming check-up (another spelling)")
post(A, "/api/life/health", {"type": "vaccination", "title": "Tetanus", "date": D(-2)}, "an overdue vaccination of me")
med = post(A, "/api/life/health", {"type": "medication", "title": "Vitamin D", "who": "Anna", "date": D(-2), "times": ["00:00"]}, "a medication")
mid = (med.get("tasks") or [{}])[0].get("id")
check(mid and A.post(B + f"/api/tasks/{mid}/complete", json={}).ok, "setup: one intake taken")
j = A.get(B + "/api/stats").json()
h = j.get("health") or {}
ppl = {p["name"]: p for p in h.get("people", [])}
check(set(ppl) == {"", "Anna"}, f"#4617: per person, '' = me, the spellings of Anna together: {sorted(ppl)}")
an, mine = ppl.get("Anna", {}), ppl.get("", {})
check(an.get("done") == 1 and an.get("per_week", [0])[-1] == 1 and h.get("done") == 1 and h.get("per_week", [0])[-1] == 1,
      f"#4617: Anna: one appointment done this week {an.get('done')} {an.get('per_week')}")
check((an.get("next") or {}).get("title") == "Zahnarzt" and an["next"]["due"] == D(5) and an.get("overdue") == 0, f"#4617: Anna's next one {an.get('next')}")
check(mine.get("overdue") == 1 and mine.get("done") == 0 and mine.get("next") is None, f"#4617: me: one overdue {mine}")
check((an.get("med_done"), an.get("med_due")) == (1, 3), f"#4617: medication apart: intakes done 1 of 3 (two days ago taken, yesterday and today open) "
      f"{an.get('med_done')} {an.get('med_due')}")
check(sum(len(w) == 12 for w in [h.get("per_week", [])] + [p["per_week"] for p in ppl.values()]) == 3, "12 weeks per person")
check([x["title"] for x in h.get("next", [])] == ["Zahnarzt"], f"the next due ones {h.get('next')}")
check("health" not in A.get(B + f"/api/stats?space=org:{ORG}").json(), "#4617: health never in an organisation's view")

# ================================================================ travel
berlin = post(A, "/api/life/trips", {"name": "Berlin", "from": D(-30), "to": D(-28), "packing": ""}, "a past trip").get("list_id")
post(A, "/api/life/trips", {"name": "Rom", "from": D(20), "to": D(24), "where": "Roma", "packing": ""}, "a coming trip")
post(A, "/api/life/trips", {"name": "Messe", "from": D(-10), "to": D(-9), "packing": "", "space": f"org:{ORG}"}, "an organisation's trip")
r = A.post(B + f"/api/life/trips/{berlin}/expenses")
check(r.status_code == 201, f"setup: travel expenses of Berlin {r.status_code} {r.text[:200]}")
otid = r.json().get("trip_id") if r.ok else None
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + f"/api/office/trips/{otid}/items", json={"date": D(-29), "category": "other", "text": "Hotel", "amount": 84.5})
check(r.ok, f"setup: a receipt of 84.50 {r.status_code} {r.text[:200]}")
A.patch(B + "/api/settings", json={"workspace": "all"})
y0, y1 = date(T.year, 1, 1), date(T.year, 12, 31)


def span(a, z, lo, hi):
    a, z = max(date.fromisoformat(a), lo), min(date.fromisoformat(z), hi)
    return (z - a).days + 1 if z >= a else 0


TRIPS = {"Berlin": (D(-30), D(-28)), "Rom": (D(20), D(24)), "Messe": (D(-10), D(-9))}


def want(names, lo, hi):
    ds = [span(*TRIPS[n], lo, hi) for n in names]
    return sum(1 for d in ds if d), sum(ds)


j = A.get(B + "/api/stats").json()
tv = j.get("travel") or {}
l12 = tv.get("last12") or {}
check((l12.get("trips"), l12.get("days")) == (2, 5), f"#4617: last 12 months: Berlin + the fair, 3 + 2 days {l12}")
check((tv["year"]["trips"], tv["year"]["days"]) == want(TRIPS, y0, y1) and tv["year"]["year"] == T.year, f"#4617: this year {tv.get('year')}")
check([x["amount"] for x in l12.get("costs", [])] == [84.5] and l12["costs"][0]["currency"], f"#4617: the travel expenses of Berlin {l12.get('costs')}")
nx = tv.get("next") or {}
check(nx.get("name") == "Rom" and nx.get("where") == "Roma" and nx.get("days") == 20, f"#4617: the next trip {nx}")
tp = A.get(B + "/api/stats?space=private").json()["travel"]
to = A.get(B + f"/api/stats?space=org:{ORG}").json()["travel"]
check((tp["last12"]["trips"], tp["last12"]["days"]) == (1, 3) and tp["next"]["name"] == "Rom", f"#4617: Private: Berlin only {tp['last12']}")
check((to["last12"]["trips"], to["last12"]["days"]) == (1, 2) and to["next"] is None and to["last12"]["costs"] == [],
      f"#4617: the organisation: its fair only {to}")
co = A.get(B + f"/api/stats?space=org:{ORG}").json()["contracts"]
check(co["count"] == 0 and co["by_provider"] == [], f"#4617: the organisation has none of the private contracts {co['count']}")

# ================================================================ a module off = its key is missing
off = ",".join(f for f in FEATURES.split(",") if f not in ("contracts", "health", "travel"))
A.patch(B + "/api/settings", json={"features": off})
j = A.get(B + "/api/stats").json()
check(not ({"contracts", "health", "travel"} & set(j)) and "done" in j, f"#4617: modules off: no blocks {sorted(j)}")
A.patch(B + "/api/settings", json={"features": off + ",health"})
check(set(A.get(B + "/api/stats").json()) & {"contracts", "health", "travel"} == {"health"}, "#4617: one module on: only its block")
A.patch(B + "/api/settings", json={"features": FEATURES})

# ================================================================ the REST API: health only with the scope private
for scopes, sees in ((["read"], False), (["read", "private"], True)):
    tok = A.post(B + "/api/me/tokens", json={"name": "stats " + "+".join(scopes), "scopes": scopes}).json().get("token")
    r = requests.get(B + "/api/v1/stats", headers={"Authorization": "Bearer " + (tok or "x")})
    jv = r.json() if r.ok else {}
    check(r.ok and "contracts" in jv and jv["contracts"]["count"] == 4, f"/api/v1/stats with {scopes}: {r.status_code} {r.text[:150]}")
    check(("health" in jv) == sees, f"#4617: a token with {scopes} {'sees' if sees else 'never sees'} health")
    if not sees:
        check("Anna" not in r.text and "Zahnarzt" not in r.text, "#4617: no name of a person, no appointment in the answer")
        check(jv["travel"]["last12"]["trips"] == 1 and jv["travel"]["last12"]["costs"] == [],
              f"a token: no organisation's trip, no travel expenses {jv['travel']['last12']}")
    else:
        check({p["name"] for p in jv["health"]["people"]} == {"", "Anna"}, "with private: the same as the app")

# ================================================================ a person without an organisation
FR, Fr = freelancer(B, A, "frida")
post(Fr, "/api/life/contracts", {"name": "Handy", "provider": "Funk AG", "cost": 20, "per": "month", "ends": D(60)}, "freelancer: a contract")
post(Fr, "/api/life/trips", {"name": "Lissabon", "from": D(-5), "to": D(-3), "packing": ""}, "freelancer: a trip")
post(Fr, "/api/life/health", {"type": "appointment", "title": "Hausarzt", "date": D(3)}, "freelancer: an appointment")
for q in ("", "?space=private"):
    r = Fr.get(B + "/api/stats" + q)
    jf = r.json() if r.ok else {}
    check(r.ok and jf.get("contracts", {}).get("count") == 1 and jf["contracts"]["by_provider"] == [{"name": "Funk AG", "n": 1, "monthly": 20}],
          f"freelancer{q}: the contract {r.status_code} {jf.get('contracts')}")
    check(jf.get("travel", {}).get("last12", {}).get("days") == 3, f"freelancer{q}: three travel days {jf.get('travel')}")
    check([p["next"]["title"] for p in jf.get("health", {}).get("people", [])] == ["Hausarzt"], f"freelancer{q}: the next appointment")
    check("Strom" not in r.text and "Anna" not in r.text, f"freelancer{q}: only the own numbers")

sys.exit(done("p2630_c_stats_api"))
