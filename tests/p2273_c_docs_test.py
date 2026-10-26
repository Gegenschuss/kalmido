#!/usr/bin/env python3
"""2.273.0 C (#3047): documents -- values set by hand survive a new recognition run, archive numbers without a race.
Invented texts and figures only (every file is written here). freelancer-matrix: documents
 - due date, amount and currency set by hand stay after "Recognise again" (the answer names them in "kept") and after a
   new version of the file; "hand" lists them; emptied by hand = free again for the recognition
 - two saves with asn "next" at the same time (threads, several rounds): both 200, two different numbers, the date /
   amount / name of both saves are stored
 - 2.273.0 F2 (#3047): a value set back to the recognised one (the undo of a save, "restore") is no hand value: "hand"
   drops it and "Recognise again" may change it again
 - 2.273.0 F2 (#3047): a recognition run that finds an archive number code does not hold the workspace's archive number
   lock while it classifies (a probe from a second connection inside classify gets the lock); the number is still stored
 - 2.273.0 (#3047): the recognised value behind a hand value is stored only as a keyed digest (no plain amount in auto)
 - the same for a person without an organisation (private space)
usage: p2273_c_docs_test.py <datadir>   (P2273C_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import threading

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

TEXT = "Beispiel Handel GmbH\nRechnung 2026-117\nRechnungsdatum 05.03.2026\nZahlbar bis 20.03.2026\nGesamt 119,00 EUR\n"


def upload(s, ws, name, data=TEXT):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, data.encode(), "text/plain"))])
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def hand_values(s, who, ws):
    nid = upload(s, ws, f"rechnung-{who}.txt")
    check(done(s, nid), f"{who}: first recognition run done")
    r = s.patch(B + f"/api/docs/{nid}", json={"due": "2027-01-15", "amount": "99.99", "currency": "CHF"})
    check(r.ok, f"{who}: due / amount / currency set by hand " + r.text[:200])
    check(sorted(r.json().get("hand") or []) == ["amount", "currency", "due"], f"{who}: hand lists the three ({r.json().get('hand')})")
    r = s.post(B + f"/api/docs/{nid}/redo")
    check(r.ok and sorted(r.json().get("kept") or []) == ["amount", "currency", "due"], f"{who}: redo names the kept values " + r.text[:200])
    d = until(lambda: (lambda j: j if j["state"] == "done" else None)(s.get(B + f"/api/docs/{nid}").json()), 90)
    check(d and d["due"] == "2027-01-15" and str(d["amount"]) == "99.99" and d["currency"] == "CHF",
          f"{who}: hand values stay after Recognise again ({d and (d['due'], d['amount'], d['currency'])})")
    v0 = kt.dbx("SELECT version FROM doc_meta WHERE node_id=?", (nid,))[0][0]
    r = s.post(B + f"/api/files/nodes/{nid}/versions", files={"file": (f"rechnung-{who}.txt", (TEXT + "Gesamt 500,00 USD\n").encode(), "text/plain")})
    check(r.status_code == 201, f"{who}: new version uploaded " + r.text[:200])
    ok = until(lambda: (lambda x: x and x[0][0] != v0 and x[0][1] == "done")(kt.dbx("SELECT version, state FROM doc_meta WHERE node_id=?", (nid,))), 120)
    check(ok, f"{who}: the new version was recognised")
    d = s.get(B + f"/api/docs/{nid}").json()
    check(d["due"] == "2027-01-15" and str(d["amount"]) == "99.99" and d["currency"] == "CHF",
          f"{who}: hand values stay after a new version ({d['due']}, {d['amount']}, {d['currency']})")
    r = s.patch(B + f"/api/docs/{nid}", json={"currency": ""})
    check(r.ok and sorted(r.json().get("hand") or []) == ["amount", "due"], f"{who}: an emptied currency is free again ({r.json().get('hand')})")


def undo_hand(s, who, ws):
    nid = upload(s, ws, f"undo-{who}.txt", TEXT + f"Kunde {who} Rückgängig\n")  # own content (the same file is a duplicate)
    d0 = done(s, nid)
    check(d0 and d0["amount"] and d0["due"], f"{who}: amount and due recognised ({d0 and (d0['amount'], d0['due'])})")
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": "55.55", "due": "2027-03-01"})
    check(r.ok and sorted(r.json().get("hand") or []) == ["amount", "due"], f"{who}: two hand values ({r.json().get('hand')})")
    auto = str(kt.dbx("SELECT auto FROM doc_meta WHERE node_id=?", (nid,))[0][0] or "")
    rec = str(d0["amount"])  # 2.273.0 (#3047, Fable review): the recognised amount behind a hand value never in plain text
    check(rec not in auto and rec.replace(".", ",") not in auto and "_was" in auto, f"{who}: no plain recognised amount in auto ({auto[:160]})")
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": "66.66"})
    check(r.ok and sorted(r.json().get("hand") or []) == ["amount", "due"], f"{who}: a second hand value stays hand ({r.json().get('hand')})")
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": d0["amount"], "due": d0["due"]})  # the undo sends the values before
    check(r.ok and not r.json().get("hand"), f"{who}: back to the recognised values = no hand value ({r.json().get('hand')})")
    r = s.post(B + f"/api/docs/{nid}/redo")
    check(r.ok and not r.json().get("kept"), f"{who}: redo keeps nothing by hand " + r.text[:200])


LOCK_PROBE = '''
import sys
sys.path.insert(0, "/app")
from kalmido.docs import store as S
from kalmido.core.db import connect
c = connect()
ws = S.meta_row(c, %d)["ws"]
probe, orig = [], S.classify
def slow(*a, **k):
    c2 = connect()
    probe.append(c2.execute("SELECT pg_try_advisory_xact_lock(hashtext(?))", (f"doc-asn:{ws}",)).fetchone()[0])
    c2.rollback()
    c2.close()
    return orig(*a, **k)
S.classify = slow
st = S.process(c, %d)
c.commit()
m = S.meta_row(c, %d)
print(st, probe, m["asn"], S.meta_json(c, m, "auto", {}).get("asn"))
'''


def asn_lock_short(s, who, ws, n):
    nid = upload(s, ws, f"code-{who}.txt", f"Brief mit Code\nASN{n:05d}\n")
    d = done(s, nid)
    check(d and d["asn"] == n, f"{who}: the archive number code is read ({d and d['asn']})")
    r = s.patch(B + f"/api/docs/{nid}", json={"asn": None})
    check(r.ok and not r.json()["asn"], f"{who}: number cleared " + r.text[:200])
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", kt.CT, "python", "-"], input=LOCK_PROBE % (nid, nid, nid),
                       capture_output=True, text=True)
    check(p.stdout.strip() == f"done [True] {n} code", f"{who}: lock free while classifying, number stored ({p.stdout.strip()!r} {p.stderr[-300:]})")


def asn_race(s, who, ws, rounds=4):
    for i in range(rounds):
        ids = [upload(s, ws, f"brief-{who}-{i}-{k}.txt", f"Brief {i} {k}\n") for k in (0, 1)]
        for nid in ids:
            done(s, nid)
        res, bar = {}, threading.Barrier(2)

        def save(k, nid):
            bar.wait()
            res[k] = s.patch(B + f"/api/docs/{nid}", json={"asn": "next", "date": f"2026-02-1{k}", "amount": f"1{k}.50", "name": f"brief-{who}-{i}-{k}-neu.txt"})

        th = [threading.Thread(target=save, args=(k, nid)) for k, nid in enumerate(ids)]
        for t in th:
            t.start()
        for t in th:
            t.join()
        check(all(res[k].status_code == 200 for k in (0, 1)), f"{who} round {i}: both saves with asn next 200 ({[res[k].status_code for k in (0, 1)]} {res[0].text[:120]} {res[1].text[:120]})")
        ds = [s.get(B + f"/api/docs/{nid}").json() for nid in ids]
        check(ds[0]["asn"] and ds[1]["asn"] and ds[0]["asn"] != ds[1]["asn"], f"{who} round {i}: two different archive numbers ({ds[0]['asn']}, {ds[1]['asn']})")
        check(all(ds[k]["date"] == f"2026-02-1{k}" and str(ds[k]["amount"]) == f"1{k}.50" and ds[k]["name"] == f"brief-{who}-{i}-{k}-neu.txt" for k in (0, 1)),
              f"{who} round {i}: date / amount / name of both saves stored ({[(d['date'], d['amount'], d['name']) for d in ds]})")


kt.fresh(env={"KALMIDO_DOCS_SCAN_S": "2"}, prefix="P2273C")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files,office", "tour": "done", "workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)

hand_values(A, "alice", f"org:{ORG}")
hand_values(Fr, "frida", "private")
undo_hand(A, "alice", f"org:{ORG}")
undo_hand(Fr, "frida", "private")
asn_lock_short(A, "alice", f"org:{ORG}", 4711)
asn_lock_short(Fr, "frida", "private", 4712)
asn_race(A, "alice", f"org:{ORG}")
asn_race(Fr, "frida", "private")
sys.exit(kt.done("p2273_c_docs"))
