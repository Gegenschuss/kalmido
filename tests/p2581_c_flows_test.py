#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.581.0 C API tests (#4803): document flows ("Abläufe") -- the document rules with a trigger, filters and actions
(kalmido/docs/flows.py). Invented names only, generated PDFs with a text layer.
 - received: an old rule (words -> type) runs unchanged on a new document, its run is listed with what it did and can be
   taken back (the type goes); a flow with the source filter "mail" leaves an upload alone; a flow with "Create task" makes the
   task in its author's inbox, the undo moves it to the trash
 - changed: a flow "tag Bezahlt set -> remove tag Offen" runs after a person's change, its undo brings "Offen" back
 - no loop: flow A (type changed -> tag) and flow B (tags changed -> type): a change of the type runs A, A's tag does not
   start B (depth 1), the type stays the person's
 - scheduled: "0 days after Added -> tag Frist" tags a new document once; the tag taken off by hand does not come back on the
   next ticks (one run per flow, document and day)
 - webhook: an internal address (127.0.0.1, localhost, 10.x, http://) is refused like for every other webhook; an allowed one
   is stored, its secret comes back once and never in the settings
 - notify: only people of the workspace (another person 400); a member who sees the document gets the News "docflow"
 - rights: runs and undo of an organisation's document only for its people (another person 404), members who only read
   cannot undo (403 / 404); a person without an organisation (frida) uses all of it in her own documents
freelancer-matrix: files
tenant-matrix: document
usage: p2581_c_flows_test.py <datadir>      (a fresh container; P2581C_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, sess, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

kt.fresh(env={"KALMIDO_DOCFLOW_TICK_S": "1"}, prefix="P2581C")
A = kt.setup()


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, name, lines, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(lines), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), 90)


def runs(s, nid):
    r = s.get(B + f"/api/docs/{nid}/flowruns")
    return r.json()["runs"] if r.ok else None


def tags(d):
    return sorted(t["name"] for t in (d or {}).get("tags") or [])


def flow(s, ws, **kw):
    return s.post(B + "/api/docs/rules", json={"ws": ws, **kw})


# ---- setup: frida without an organisation; Alpha = bob (admin) + carol (member); gina a stranger
FR, Fr = freelancer(B, A, "frida")
ids = {}
for u in ("bob", "carol", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
OWS = f"org:{ORG}"
Bo, Ca, Gi = sess("bob"), None, sess("gina")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
Ca = sess("carol")
for s in (Bo, Ca, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

# ---- received: an old rule unchanged + its run + undo (frida, no organisation)
r = flow(Fr, "private", kind="any", match="Stadtwerke", type="Abschlag")
check(r.status_code == 201, f"an old rule is still saved as before {r.status_code} {r.text[:200]}")
r = flow(Fr, "private", sources=["mail"], tags=["NurMail"])
check(r.status_code == 201, f"a flow with only a source filter (no words) is saved {r.status_code} {r.text[:200]}")
r = flow(Fr, "private", name="Aufgabe Vertrag", kind="any", match="Vertragsende", task={"title": "Kuendigen: {name}"})
check(r.status_code == 201, f"a flow with a task {r.status_code} {r.text[:200]}")
rs = Fr.get(B + "/api/docs/settings?ws=private").json()["rules"]
check(any(x.get("type") == "Abschlag" and x.get("match") == "Stadtwerke" and "trigger" not in x for x in rs),
      f"the old rule reads as before (no trigger key = received) {rs}")
d1 = upload(Fr, "abschlag.pdf", ["Stadtwerke Musterstadt", "Abschlag Strom 2026"])
d = done(Fr, d1)
check(d and (d.get("type") or {}).get("name") == "Abschlag", f"received: the old rule set the type {d and d.get('type')}")
check("NurMail" not in tags(d), f"received: the source filter mail leaves an upload alone {tags(d)}")
rr = runs(Fr, d1)
check(rr and len(rr) == 1 and rr[0]["trigger"] == "received" and rr[0]["did"] == ["type"], f"received: one run, it set the type {rr}")
check(any(x["action"] == "flow" for x in Fr.get(B + f"/api/files/nodes/{d1}").json().get("log") or []), "received: the run is in the document's history")
r = Fr.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo")
check(r.ok and r.json()["run"]["undone"], f"received: undo {r.status_code} {r.text[:200]}")
check(doc(Fr, d1).get("type") is None, "received: after the undo the type is gone")
check(Fr.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo").status_code == 409, "a run is taken back once")
d2 = upload(Fr, "vertrag.pdf", ["Mobilfunk", "Vertragsende 31.12.2026"])
done(Fr, d2)
rr = until(lambda: [x for x in runs(Fr, d2) or [] if x["task_id"]], 30)
tid = rr[0]["task_id"] if rr else None
t = Fr.get(B + f"/api/tasks/{tid}").json() if tid else {}
check(tid and t.get("title") == "Kuendigen: vertrag.pdf", f"received: the flow made the task in frida's inbox {t.get('title')}")
r = Fr.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo") if rr else None
check(r is not None and r.ok and Fr.get(B + f"/api/tasks/{tid}").status_code == 404 and dbx("SELECT deleted_at FROM tasks WHERE id=?", (tid,))[0][0],
      "received: the undo moves the task to the trash")

# ---- changed: tag Bezahlt set -> remove tag Offen; undo brings it back
r = flow(Fr, "private", name="Bezahlt", trigger="changed", on=["tags"], has_tags=["Bezahlt"], untag=["Offen"])
check(r.status_code == 201, f"a changed flow is saved {r.status_code} {r.text[:200]}")
d3 = upload(Fr, "rechnung.pdf", ["Rechnung 4711", "Malerbetrieb"])
done(Fr, d3)
check(Fr.patch(B + f"/api/docs/{d3}", json={"tags": ["Offen"]}).ok, "setup: tag Offen")
check(tags(doc(Fr, d3)) == ["Offen"] and not runs(Fr, d3), "changed: the filter (has tag Bezahlt) holds the flow back")
r = Fr.patch(B + f"/api/docs/{d3}", json={"tags": ["Offen", "Bezahlt"]})
check(r.ok and tags(r.json()) == ["Bezahlt"], f"changed: setting Bezahlt removed Offen {r.ok and tags(r.json())}")
rr = runs(Fr, d3)
check(rr and rr[0]["trigger"] == "changed" and rr[0]["did"] == ["tags"], f"changed: one run {rr}")
check(Fr.post(B + f"/api/docs/flowruns/{rr[0]['id']}/undo").ok and tags(doc(Fr, d3)) == ["Bezahlt", "Offen"], "changed: undo brings Offen back")

# ---- scheduled: 0 days after Added -> tag Frist, once per document and day
r = flow(Fr, "private", name="Frist", trigger="scheduled", days=0, **{"from": "added"}, tags=["Frist"])
check(r.status_code == 201, f"a scheduled flow is saved {r.status_code} {r.text[:200]}")
check(flow(Fr, "private", trigger="scheduled", days=-1, tags=["x"]).status_code == 400, "scheduled: negative days refused")
d4 = upload(Fr, "frist.pdf", ["Mahnung", "Zahlungsfrist"])
done(Fr, d4)
check(until(lambda: "Frist" in tags(doc(Fr, d4)), 30), "scheduled: the tick tagged the new document")
check(Fr.patch(B + f"/api/docs/{d4}", json={"tags": []}).ok, "the tag taken off by hand")
d5 = upload(Fr, "frist2.pdf", ["Erinnerung", "Zahlungsfrist"])
done(Fr, d5)
check(until(lambda: "Frist" in tags(doc(Fr, d5)), 30), "scheduled: the next tick tagged the second document")
check("Frist" not in tags(doc(Fr, d4)), "scheduled: the first document is not tagged a second time (one run per day)")
fid = [x["id"] for x in Fr.get(B + "/api/docs/settings?ws=private").json()["rules"] if x.get("name") == "Frist"][0]
check(len(dbx("SELECT id FROM doc_flow_runs WHERE rule_id=? AND node_id=?", (fid, d4))) == 1, "scheduled: one run row per flow, document and day")

# ---- webhook: internal targets refused like every webhook, the secret once
for bad in ("https://127.0.0.1/hook", "https://localhost/hook", "https://10.1.2.3/hook", "http://hooks.example.com/hook", "ftp://hooks.example.com/"):
    check(flow(Fr, "private", kind="any", match="Webhooktest", webhook=bad).status_code == 400, f"webhook: {bad} refused")
r = flow(Fr, "private", name="Hook", kind="any", match="Webhooktest", webhook="https://hooks.example.com/kalmido")
check(r.status_code == 201 and len(r.json().get("hook_secret") or "") >= 20, f"webhook: an allowed target is stored, the secret once {r.status_code} {r.text[:200]}")
rs = Fr.get(B + "/api/docs/settings?ws=private").json()["rules"]
check(all("hook_secret" not in x for x in rs) and any(x.get("webhook") == "https://hooks.example.com/kalmido" for x in rs), "webhook: the secret never in the settings")

# ---- notify + rights in an organisation
check(flow(Fr, "private", kind="any", match="x", notify=[ids["bob"]]).status_code == 400, "notify: a person outside frida's workspace refused")
check(flow(Bo, OWS, kind="any", match="x", notify=[FR]).status_code == 400, "notify: a person outside the organisation refused")
check(flow(Ca, OWS, kind="any", match="x", tags=["t"]).status_code in (403, 404), "a member who is no admin makes no flow")
r = flow(Bo, OWS, name="Melden", kind="any", match="Gutachten", notify=[ids["carol"]])
check(r.status_code == 201, f"notify: a flow of the organisation {r.status_code} {r.text[:200]}")
# no loop: A (type changed -> tag Geprueft), B (tags changed -> type Sonstiges)
check(flow(Bo, OWS, name="A", trigger="changed", on=["type"], tags=["Geprueft"]).status_code == 201, "loop: flow A saved")
check(flow(Bo, OWS, name="B", trigger="changed", on=["tags"], type="Sonstiges").status_code == 201, "loop: flow B saved")
o2 = upload(Bo, "gutachten-garage.pdf", ["Gutachten Garage", "Seite 1"], ws=OWS)  # bob's own: carol does not see it
done(Bo, o2)
o1 = upload(Ca, "gutachten.pdf", ["Gutachten Haus", "Seite 1"], ws=OWS)  # carol's: she sees it
done(Ca, o1)
news = until(lambda: [x for x in Ca.get(B + "/api/news").json()["items"] if x["kind"] == "docflow"], 30)
check(news and [x["data"].get("doc") for x in news] == [o1], f"notify: carol got the News docflow for the document she sees only {news}")
check(not [x for x in Gi.get(B + "/api/news").json()["items"] if x["kind"] == "docflow"], "notify: nobody else")
r = Bo.patch(B + f"/api/docs/{o1}", json={"type": "Gutachten"})
check(r.ok and (r.json().get("type") or {}).get("name") == "Gutachten" and "Geprueft" in tags(r.json()),
      f"loop: A ran, B did not (type stays Gutachten) {r.ok and (r.json().get('type'), tags(r.json()))}")
names = [x["name"] for x in runs(Bo, o1)]
check("A" in names and "B" not in names, f"loop: only A has a run {names}")
check(Gi.get(B + f"/api/docs/{o1}/flowruns").status_code == 404, "rights: a stranger does not see the runs")
rid = runs(Bo, o1)[0]["id"]
check(Gi.post(B + f"/api/docs/flowruns/{rid}/undo").status_code == 404, "rights: a stranger cannot undo")
check(Fr.post(B + f"/api/docs/flowruns/{rid}/undo").status_code == 404, "rights: frida cannot undo the organisation's run")
check(Bo.post(B + f"/api/docs/flowruns/{rid}/undo").ok and "Geprueft" not in tags(doc(Bo, o1)), "rights: the admin takes A's run back")

sys.exit(kt.done("p2581_c_flows"))
