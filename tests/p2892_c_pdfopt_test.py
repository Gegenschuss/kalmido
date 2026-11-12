#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.892.0 (#4873, includes #4806): "Optimise PDF" as a new version. Own container (start.sh). Invented names only; the scans
(Pillow pictures as PDFs without a text layer) are drawn in the test container.
freelancer-matrix: files
tenant-matrix: document
 - unit (docs/pdfopt.py loaded as a single file in the container, its real tools): a page of text -> black and white, a page
   with a coloured photo -> colour, a grey gradient -> grey, an almost white page -> blank (ink + no text); never every page
   blank; Otsu threshold, "not smaller", the level bw / gray; the optimised PDF is smaller, has the pages without the blank
   one and a text layer with the page's words
 - API as a person without organisation: GET .../pdfopt says it can; the check measures the pages (state ready, the blank
   page listed); the run makes a NEW VERSION (2 versions, the original = version 1 byte for byte, "orig" names it, the new
   one smaller, one page less), the document is recognised again from its text layer (method pdf, its words in the text)
 - not smaller -> no new version (state same, both sizes)
 - a PDF with its own text (not scanned) -> 409; another account -> 404 (GET and POST)
 - the selection: POST /api/docs/pdfopt with a scan, a text PDF and another person's document -> 1 queued, 2 skipped; review
   F5: "blank" without the list of the pages seen first removes no page (the blank page of the scan stays)
 - "Optimise new scans automatically": a new scan of the private space is optimised by itself (auto, no page removed); a
   receipt upload of the office (area office) never (GoBD), it keeps one version
 - 2.1069.0 (#5412): a queued run counts in its own workspace only, the workspace's limit (PO_WS_MAX) and the person's
   (PO_WAIT_MAX) both hold; the recognition's step (docs_run_once) never runs an "Optimise PDF", its own thread does
   (po_run_once: the cut-off runs taken up at its first step, then a run)
 - 2.1073.0 (#5570): a run of six pages goes page by page (GET shows its steps), a scan uploaded meanwhile is recognised
   before the run ends, the run's folder goes afterwards
usage: p2892_c_pdfopt_test.py <datadir>   (P2892C_NOSTART=1: the container runs already)"""
import base64
import json
import subprocess
import sys

import kt
from kt import B, CT, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P2892C", env={"KALMIDO_DOCS_SCAN_S": "2"})
A = kt.setup()
FEAT = "docs,files,office"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, features=FEAT)
GID, Go = freelancer(B, A, "fiona", features=FEAT)

# a scan: every page a picture (300 dpi, a light paper grain so the JPEG of the scan is as big as a real one), no text layer
SCAN = r"""
import base64, io, json, random, sys
from PIL import Image, ImageDraw, ImageFont
random.seed(7)
f = ImageFont.load_default(size=56)
W, H = 2480, 3508
grain = Image.effect_noise((W, H), 6).point(lambda x: 236 + (x - 128) // 12)
pages = []
for spec in json.loads(sys.argv[1]):
    kind, text = spec.split(':', 1) if ':' in spec else (spec, '')
    if kind == 'blank':
        im = Image.merge('RGB', [grain] * 3)
    else:
        im = Image.merge('RGB', [grain] * 3)
        d = ImageDraw.Draw(im)
        for i, ln in enumerate(text.split('|')):
            d.text((260, 400 + i * 110), ln, fill=(20, 20, 20), font=f)
        if kind == 'color':
            d.rectangle((300, 1600, 2100, 2900), fill=(200, 40, 40))
            d.ellipse((700, 1900, 1600, 2700), fill=(40, 90, 200))
        if kind == 'photo':
            g = Image.linear_gradient('L').resize((2000, 2400))
            im.paste(Image.merge('RGB', [g] * 3), (240, 800))
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=300, save_all=True, append_images=pages[1:], quality=85)
print(base64.b64encode(o.getvalue()).decode())
"""


def text_pdf(s):
    """A one-page PDF with its own text (Helvetica), written by hand: no tool needed."""
    stream = b"BT /F1 18 Tf 72 760 Td (" + s.encode() + b") Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


TINY = r"""
import base64, io
from PIL import Image
im = Image.new('1', (60, 80), 1)
o = io.BytesIO()
im.save(o, 'PDF', resolution=72)
print(base64.b64encode(o.getvalue()).decode())
"""


def py(code, *args, timeout=600):
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code, *args], capture_output=True, text=True, timeout=timeout)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def scan(pages):
    return base64.b64decode(py(SCAN, json.dumps(pages)))


def up(s, name, data, ws="private", **form):
    r = s.post(B + "/api/docs", data={"ws": ws, **form}, files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid, secs=300):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def po(s, nid):
    r = s.get(B + f"/api/docs/{nid}/pdfopt")
    return r.json() if r.ok else {"http": r.status_code}


def po_until(s, nid, states, secs=600):
    return until(lambda: (lambda j: j if j.get("state") in states else None)(po(s, nid)), secs, step=1)


def versions(s, nid):
    return s.get(B + f"/api/files/nodes/{nid}").json().get("versions") or []


# ================================================================ unit: the tools in the container (a single-file load)
UNIT = r"""
import base64, importlib.util, io, json, sys
s = importlib.util.spec_from_file_location('po', '/app/kalmido/docs/pdfopt.py'); P = importlib.util.module_from_spec(s); s.loader.exec_module(P)
data = base64.b64decode(sys.stdin.read())
out = {"kind": [P.po_kind('auto', 0.05, 0.2, 0.1), P.po_kind('auto', 0.05, 0.0, 0.4), P.po_kind('auto', 0.05, 0.0, 0.02),
                P.po_kind('bw', 0.05, 0.5, 0.5), P.po_kind('gray', 0.05, 0.5, 0.0)],
       "blank": [P.po_blank(0.001, ' \n '), P.po_blank(0.001, 'Rechnung Nummer 12'), P.po_blank(0.05, ''), P.po_blank(0.001, None)],
       "pdrop": [P.po_drop([{'b': 0}, {'b': 1}], True), P.po_drop([{'b': 0}, {'b': 1}], False), P.po_drop([{'b': 1}, {'b': 1}], True)],
       "otsu": [P.po_otsu([0] * 40 + [100] + [0] * 179 + [900] + [0] * 35), P.po_otsu([0] * 256)],
       "smaller": [P.po_smaller(100, 99), P.po_smaller(100, 100), P.po_smaller(100, 0)]}
pages = P.po_analyse(data)
out["pages"] = [{"k": p["k"], "b": p["b"]} for p in pages]
r = P.po_optimise(data, 'auto', True, None, pages)
from pypdf import PdfReader
rd = PdfReader(io.BytesIO(r["pdf"]))
out.update(before=len(data), after=len(r["pdf"]), drop=r["drop"], kinds=r["kinds"], n=len(rd.pages),
           text=" ".join((p.extract_text() or "") for p in rd.pages)[:3000])
bw = P.po_optimise(data, 'bw', False)
out.update(bw_kinds=bw["kinds"], bw_n=len(PdfReader(io.BytesIO(bw["pdf"])).pages))
print(json.dumps(out))
"""
U4 = scan(["text:Rechnung Nummer 4711|Beispiel Reiher GmbH|Summe 12,00 EUR", "color:Farbseite Prospekt", "photo:Fotoseite Garten", "blank"])
u = json.loads(subprocess.run(["docker", "exec", "-i", CT, "python", "-c", UNIT], input=base64.b64encode(U4).decode(),
                              capture_output=True, text=True, timeout=900).stdout or "{}")
check(u.get("kind") == ["color", "gray", "bw", "bw", "gray"], f"unit: the kind of a page per level {u.get('kind')}")
check(u.get("blank") == [True, False, False, False], f"unit: blank = little ink AND no text, unread = never {u.get('blank')}")
check(u.get("pdrop") == [[2], [], []], f"unit: the blank pages go only with the switch, never every page {u.get('pdrop')}")
check(u.get("otsu", [0])[0] in range(90, 211) and 40 <= u["otsu"][0] < 220 and u["otsu"][1] == 160, f"unit: Otsu threshold between the two peaks, held in its bounds {u.get('otsu')}")
check(u.get("smaller") == [True, False, False], f"unit: only a smaller file counts {u.get('smaller')}")
check(u.get("pages") == [{"k": "bw", "b": 0}, {"k": "color", "b": 0}, {"k": "gray", "b": 0}, {"k": "bw", "b": 1}],
      f"unit: measured pages: text bw, colour photo colour, grey gradient grey, white page blank {u.get('pages')}")
check(u.get("drop") == [4] and u.get("n") == 3, f"unit: the optimised PDF has 3 pages (the blank page 4 left out) {u.get('drop')} {u.get('n')}")
check(0 < u.get("after", 0) < u.get("before", 0), f"unit: smaller {u.get('before')} -> {u.get('after')}")
check(u.get("kinds") == {"bw": 1, "gray": 1, "color": 1}, f"unit: one page of each kind {u.get('kinds')}")
check("4711" in u.get("text", "") or "Rechnung" in u.get("text", ""), f"unit: the text layer carries the page's words {u.get('text', '')[:200]!r}")
check(u.get("bw_kinds") == {"bw": 4, "gray": 0, "color": 0} and u.get("bw_n") == 4, f"unit: level bw = every page bw, switch off keeps every page {u.get('bw_kinds')} {u.get('bw_n')}")

# ================================================================ API as a person without organisation
D = scan(["text:Mietvertrag Wohnung 17|Beispiel Hausverwaltung|Miete 800 EUR", "blank"])
DID = up(Fr, "mietvertrag-scan.pdf", D)
d = done(Fr, DID)
check(d and d["state"] == "done" and d["method"] == "ocr", f"the scan was recognised by text recognition {d and (d['state'], d['method'])}")
check((d or {}).get("pdfopt", {}).get("can") is True and not d["pdfopt"].get("orig"), f"the document says it can be optimised {(d or {}).get('pdfopt')}")
j = po(Fr, DID)
check(j.get("can") is True and j.get("state") == "" and j.get("office") is False, f"GET .../pdfopt: can, nothing yet {j}")
r = Fr.post(B + f"/api/docs/{DID}/pdfopt", json={"mode": "auto", "check": 1})
check(r.status_code == 202, f"check: queued {r.status_code} {r.text[:200]}")
j = po_until(Fr, DID, ("ready", "failed"))
check(j and j.get("state") == "ready" and j.get("pages") == [{"k": "bw", "b": 0}, {"k": "bw", "b": 1}] and j.get("drop") == [2] and j.get("fresh"),
      f"check: the pages measured, page 2 would go {j}")
r = Fr.post(B + f"/api/docs/{DID}/pdfopt", json={"mode": "auto"})
# 2.1069.0 (#5412): its own thread may have taken it up already when the answer reads the state again
check(r.status_code == 202 and r.json().get("state") in ("wait", "run"), f"run: queued {r.status_code} {r.text[:200]}")
check(Fr.post(B + f"/api/docs/{DID}/pdfopt", json={"mode": "auto"}).status_code == 409, "run: a second start while it runs -> 409")
j = po_until(Fr, DID, ("done", "same", "failed"))
check(j and j.get("state") == "done" and j.get("before") == len(D) and 0 < j.get("after", 0) < len(D), f"run: done, smaller {j}")
check(j and j.get("from") == 1 and j.get("to") == 2 and j.get("orig") == 1 and j.get("drop") == [2], f"run: a new version 2 from 1, the original named {j}")
vs = versions(Fr, DID)
check([v["no"] for v in vs] == [2, 1] and vs[0]["size"] == j.get("after"), f"the file has two versions, the new one current {vs}")
orig = Fr.get(B + f"/api/files/nodes/{DID}/content", params={"v": 1, "dl": 1})
check(orig.ok and orig.content == D, "the original (version 1) is unchanged, byte for byte")
# 2.892.0 review F3: the queue writes the history entry of the new version for the person who asked, not for nobody
lg = kt.dbx("SELECT user_id FROM fs_log WHERE node_id=? AND action='version' ORDER BY id DESC LIMIT 1", (DID,))
check(lg and lg[0][0] == FID, f"the history names the person who optimised {lg}")
cur = Fr.get(B + f"/api/docs/{DID}/file", params={"dl": 1})
check(cur.ok and len(cur.content) == j.get("after") and cur.content[:4] == b"%PDF", "the document's file is the optimised one")
d = until(lambda: (lambda x: x if x and x["state"] == "done" and x["method"] == "pdf" else None)(doc(Fr, DID)), 300)
check(d and d["pages"] == 1 and ("Mietvertrag" in (d.get("text") or "") or "800" in (d.get("text") or "")),
      f"recognised again from the text layer: one page, its words {d and (d['method'], d['pages'], (d.get('text') or '')[:120])}")
check(d and d.get("pdfopt", {}).get("orig") == 1, f"the view offers the original (#4806: original + searchable PDF) {d and d.get('pdfopt')}")

# not smaller -> no new version
T = base64.b64decode(py(TINY))
TID = up(Fr, "kleiner-zettel.pdf", T)
t = done(Fr, TID)
check(t and t["method"] == "ocr" and t["pdfopt"]["can"], f"a tiny scan can be optimised {t and (t['method'], t.get('pdfopt'))}")
check(Fr.post(B + f"/api/docs/{TID}/pdfopt", json={"mode": "bw"}).status_code == 202, "tiny: run queued")
j = po_until(Fr, TID, ("done", "same", "failed"))
check(j and j.get("state") == "same" and j.get("before") == len(T) and j.get("after", 0) >= len(T), f"not smaller: state same, both sizes {j}")
check([v["no"] for v in versions(Fr, TID)] == [1], "not smaller: no new version")

# a PDF with its own text; another person
X = text_pdf("Invented contract of the Example Heron Club")
XID = up(Fr, "vertrag-digital.pdf", X)
x = done(Fr, XID)
check(x and x["method"] == "pdf" and x["pdfopt"]["can"] is False, f"a PDF with its own text cannot be optimised {x and x.get('pdfopt')}")
r = Fr.post(B + f"/api/docs/{XID}/pdfopt", json={"mode": "auto"})
check(r.status_code == 409, f"... POST -> 409 {r.status_code}")
check(Go.get(B + f"/api/docs/{DID}/pdfopt").status_code == 404, "another account: GET -> 404")
check(Go.post(B + f"/api/docs/{DID}/pdfopt", json={"mode": "bw"}).status_code == 404, "another account: POST -> 404")
check(Fr.post(B + f"/api/docs/{DID}/pdfopt", json={"mode": "colour"}).status_code == 400, "an unknown level -> 400")

# the selection: one scan queued, a text PDF and somebody else's document skipped
S2 = scan(["text:Versicherung Police 99|Beispiel Versicherung AG", "blank"])
SID = up(Fr, "police-scan.pdf", S2)
check(done(Fr, SID) is not None, "selection: the scan recognised")
GSID = up(Go, "fiona-scan.pdf", scan(["text:Fiona Brief 5|Beispiel Verein"]))
r = Fr.post(B + "/api/docs/pdfopt", json={"ids": [SID, XID, GSID], "mode": "bw", "blank": True})
# tenant: POST /api/docs/pdfopt
check(r.status_code == 202 and r.json() == {"queued": [SID], "skipped": 2}, f"selection: 1 queued, 2 skipped {r.status_code} {r.text[:200]}")
j = po_until(Fr, SID, ("done", "same", "failed"))
check(j and j.get("state") == "done" and j.get("mode") == "bw", f"selection: optimised {j}")
# 2.892.0 review F5: nobody saw a list of its pages -> "blank" is ignored, no page goes
check(j and not j.get("drop") and j.get("kinds") == {"bw": 2, "gray": 0, "color": 0}, f"selection: no page removed without the list seen first {j}")
check([v["no"] for v in versions(Go, GSID)] == [1], "selection: the other person's document untouched")

# ================================================================ 2.1073.0 (#5570): a run goes page by page
# a run of many pages held the documents queue until it was done: a new scan waited for its recognition (and a restore for
# GATE). Now each page is one queue step: GET .../pdfopt shows how far it got ("step"), and a scan uploaded while the run is
# under way is recognised before the run ends (the times in the database, no fixed wait).
LONG = scan([f"text:Langer Bericht Seite {i}|Beispiel Archiv Verein|Zeile {i * 7}" for i in range(1, 7)])
LID = up(Fr, "langer-bericht-scan.pdf", LONG)
check(done(Fr, LID) is not None, "#5570: the long scan recognised")
check(Fr.post(B + f"/api/docs/{LID}/pdfopt", json={"mode": "bw"}).status_code == 202, "#5570: the run of six pages queued")
mid = until(lambda: (lambda j: j if (j.get("step") and 0 < j["step"][0] < j["step"][1]) or j.get("state") in ("done", "same", "failed")
                     else None)(po(Fr, LID)), 600, step=0.3)
check(mid and mid.get("state") == "run" and mid.get("step") and 0 < mid["step"][0] < mid["step"][1],
      f"#5570: the run shows its steps while it goes (page by page, not in one go) {mid}")
NID = up(Fr, "neuer-brief-scan.pdf", scan(["text:Neuer Brief Mitte|Beispiel Absender"]))
j = po_until(Fr, LID, ("done", "same", "failed"))
check(j and j.get("state") == "done" and j.get("kinds") == {"bw": 6, "gray": 0, "color": 0} and not j.get("drop"),
      f"#5570: the run page by page ends as one: six bw pages, a new version {j}")
check([v["no"] for v in versions(Fr, LID)] == [2, 1], "#5570: the long scan has its new version")
nd = done(Fr, NID)
check(nd and nd["state"] == "done", f"#5570: the scan uploaded meanwhile recognised {nd and nd['state']}")
ta = kt.dbx("SELECT done_at FROM doc_meta WHERE node_id=?", (NID,))
check(ta and ta[0][0] and j and str(ta[0][0]) < str(j.get("at")),
      f"#5570: the new scan was recognised between two pages, before the run ended {ta} < {j and j.get('at')}")
check(not py("import glob, tempfile; print(glob.glob(tempfile.gettempdir() + '/kpdo-r*'))").strip("[]\n "),
      "#5570: the run's folder is gone after the run")

# ================================================================ "Optimise new scans automatically", never the office's receipts
r = Fr.put(B + "/api/docs/settings", json={"ws": "private", "pdf_opt_auto": True})
check(r.ok and r.json().get("pdf_opt_auto") is True, f"setting on {r.status_code} {r.text[:200]}")
check(Fr.get(B + "/api/docs/settings", params={"ws": "private"}).json().get("pdf_opt_auto") is True, "setting kept")
AID = up(Fr, "neuer-scan.pdf", scan(["text:Stromabrechnung 2026|Beispiel Stadtwerke", "blank"]))
RID = up(Fr, "beleg-scan.pdf", scan(["text:Quittung Tankstelle|Beispiel Tank 45,10 EUR"]), area="office")
j = po_until(Fr, AID, ("done", "same", "failed"))
check(j and j.get("state") == "done" and j.get("auto") == 1 and not j.get("drop"), f"a new scan optimised by itself, no page removed {j}")
check(done(Fr, RID) is not None, "the office receipt recognised")
rj = po(Fr, RID)
check(rj.get("office") is True and rj.get("state") in ("", "skipped") and [v["no"] for v in versions(Fr, RID)] == [1],
      f"the office receipt is never optimised automatically, one version {rj}")
check(rj.get("can") is True, f"... but the button is there (with the hint) {rj}")
# 2.892.0 (review of the rebuild): the button at an office receipt makes the new version - the docs queue runs outside the
# app, the period lock of an office receipt keeps its cache in flask.g (was: RuntimeError -> always "failed")
check(Fr.put(B + "/api/office/settings", json={"pack": "DE"}).status_code == 200, "frida's office has its country")
r = Fr.put(B + f"/api/docs/{RID}/receipt", json={"category": "Travel", "vat_pct": "19", "keep": True})
check(r.status_code == 200, f"the scan is a receipt of the office {r.status_code} {r.text[:200]}")
check(Fr.post(B + f"/api/docs/{RID}/pdfopt", json={"mode": "bw"}).status_code == 202, "office receipt: run by the button queued")
j = po_until(Fr, RID, ("done", "same", "failed"))
check(j and j.get("state") in ("done", "same") and j.get("error") != "failed", f"office receipt by the button: not failed {j}")
if j and j.get("state") == "done":
    check([v["no"] for v in versions(Fr, RID)] == [2, 1], "office receipt: a new version, the original kept")

# ================================================================ 2.1069.0 (#5412, review 2.781 F2): fair queue, limits, own thread
# in the container, outside the server: the queue marks written in a transaction that is rolled back (the server never
# sees them); the steps with recording stand-ins for po_queued / po_take_up
FAIR = r"""
import json, sys
import app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.docs import ingest as I, pdfoptq as Q
mine, other = int(sys.argv[1]), int(sys.argv[2])
c = connect()
out = {}
with system_ctx(c):
    ws = {n: c.execute("SELECT ws, created_by FROM doc_meta WHERE node_id=?", (n,)).fetchone() for n in (mine, other)}
    wa, ua = ws[mine][0], ws[mine][1]
    wb, ub = ws[other][0], ws[other][1]
    base = Q.po_waiting_ws(c, wa)
    Q.po_put(c, mine, {"state": "wait", "mode": "auto", "blank": 0, "by": ua, "v": 1, "at": Q._now(), "tries": 0})
    out["ws_count"] = Q.po_waiting_ws(c, wa) - base
    out["other_count"] = Q.po_waiting_ws(c, wb)
    Q.PO_WS_MAX = base + 1
    out["room_full"] = Q.po_room(c, ub, wa)
    out["room_other"] = Q.po_room(c, ub, wb)
    Q.PO_WS_MAX, Q.PO_WAIT_MAX = 10000, 5
    out["room_person"] = Q.po_room(c, ua, wa)
c.rollback()
c.close()
I._Q["first"] = False  # review: no take-up of the server's running rows from this process
with system_ctx(c := connect()):
    out["waiting"] = c.execute("SELECT COUNT(*) FROM doc_meta WHERE state IN ('wait', 'run')").fetchone()[0]
c.close()
calls = []
Q.po_queued = lambda c: calls.append("queued") or 1
Q.po_take_up = lambda c: calls.append("take_up")
I.docs_run_once()
out["docs_step"] = list(calls)
out["po_step"] = I.po_run_once()
out["po_calls"] = list(calls)
print(json.dumps(out))
"""
f = json.loads(py(FAIR, str(SID), str(GSID)).strip().splitlines()[-1])
check(f.get("ws_count") == 1 and f.get("other_count") == 0, f"a queued run counts in its workspace, not in the other {f}")
check(f.get("room_full") == 0 and f.get("room_other", 0) > 0, f"the workspace's limit: full there, room in the other workspace {f}")
check(f.get("room_person") == 4, f"the person's limit still counts (5 - the one waiting) {f}")
check(f.get("waiting") == 0 and f.get("docs_step") == [], f"the recognition's step never runs an Optimise PDF (it waited up to 30 min behind one) {f}")
check(f.get("po_step") == 1 and f.get("po_calls") == ["take_up", "queued"],
      f"the own thread's step: the cut-off runs first (once), then a run {f}")

sys.exit(kt.done("p2892_c_pdfopt"))
