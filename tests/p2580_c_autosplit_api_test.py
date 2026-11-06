#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.580.0 C (#4401): a clear stack is split without a person. Own container (start.sh). Invented names only; the stack PDFs
(QR codes with segno + Pillow) are drawn in the test container like in p2154_a_api_test.py.
freelancer-matrix: files
 - clear (every document starts with an archive number code, a separator sheet before a code): split by the queue without a
   click -- the stack in the trash (deleted_by = its owner), the parts with the numbers of their codes, the separator sheet
   left out, each part with the hint "auto" + where it came from; the parts in the stack's folder
 - not clear -> stays "Stack - split?" (open, To review): a page before the first code, a number twice in the stack, a number
   already taken in the workspace (checked after a later document went through the queue, so the queue had its turn)
 - undo of an automatic split: the parts into the trash, the stack back with its mark; a new recognition run does not split
   it again ("hand"); GET .../split offers the clear cuts, a split by hand with them works
 - an agent's upload into its own folder: split there (never into another folder), as the folder's owner
 - all of it as a person without organisation, the clear case also in an organisation
Red without the fix: the clear stacks stay "open" (no part, no trash).
usage: p2580_c_autosplit_api_test.py <datadir>   (P2580C_NOSTART=1: the container runs already)"""
import base64
import json
import subprocess
import sys

import requests

import kt
from kt import B, CT, check, until
from freelancer_fixture import freelancer

V = B + "/api/v1"
kt.fresh(prefix="P2580C")
A = kt.setup()
FEAT = "docs,files,office"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A, features=FEAT)

STACK_CODE = r"""
import base64, io, json, sys, segno
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=44)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    lines = spec.split('\n') if spec else []
    if lines and lines[0].startswith('qr:'):
        q = segno.make(lines.pop(0)[3:], micro=False)
        b = io.BytesIO()
        q.save(b, kind='png', scale=8, border=4)
        im.paste(Image.open(b).convert('L'), (1200, 100))
    for i, ln in enumerate(lines):
        d.text((150, 400 + i * 90), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
"""


def stack_pdf(pages):
    out = subprocess.run(["docker", "exec", CT, "python", "-c", STACK_CODE, json.dumps(pages)], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


def up(s, name, data, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid, secs=180):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def scan(nid):
    r = kt.dbx("SELECT split_scan FROM doc_meta WHERE node_id=?", (nid,))
    return json.loads(r[0][0] or "{}") if r else {}


def node(nid):
    r = kt.dbx("SELECT parent_id, owner_id, deleted_at, deleted_by FROM fs_nodes WHERE id=?", (nid,))
    return tuple(r[0]) if r else None


def split_done(nid, secs=180):
    """The stack's parts once the queue split it (its scan says done), else None."""
    return until(lambda: (lambda v: v.get("parts") if v.get("state") == "done" else None)(scan(nid)), secs)


def queue_passed(s, tag):
    """A one-page document after the stacks went through the queue: the automatic split (before the next document) had its turn."""
    return done(s, up(s, f"{tag}.pdf", stack_pdf([f"Nachzuegler {tag}"])))


def asns(ids):
    return [kt.dbx("SELECT asn FROM doc_meta WHERE node_id=?", (i,))[0][0] for i in ids]


CLEAR = ["qr:ASN00501\nRechnung Eins\nBeispiel Strom GmbH", "Seite zwei der Rechnung\nSumme 12,00 EUR",
         "qr:ASN00502\nVertrag Zwei\nBeispiel Versicherung AG", "qr:KALMIDO-SPLIT\nTrennblatt", "qr:ASN00503\nBrief Drei\nBeispiel Verein e.V."]

# ================================================================ clear: split without a click (person without organisation)
SID = up(Fr, "stapel-klar.pdf", stack_pdf(CLEAR))
P = split_done(SID)
check(P and len(P) == 3, f"clear stack: split by the queue without a click ({scan(SID).get('state')} {P})")
P = P or []
st = node(SID)
check(st and st[2] is not None and st[3] == FID, f"clear stack: in the trash, moved there as its owner ({st})")
check(scan(SID).get("auto") == 1, "clear stack: marked as split automatically")
check(asns(P) == [501, 502, 503], f"parts: the numbers of their codes {asns(P)}")
ds = [done(Fr, p) for p in P]
check(all(d and (d.get("split") or {}).get("auto") is True and (d.get("split") or {}).get("from") == SID for d in ds),
      f"parts: the hint 'split automatically' + the stack ({[d and d.get('split') for d in ds]})")
check(all(d and not (d.get("split") or {}).get("stack") and not (d.get("split") or {}).get("no_asn") for d in ds), "parts: no stack mark, no 'before the first code'")
check([d and d["pages"] for d in ds] == [2, 1, 1], f"parts: the separator sheet left out ({[d and d['pages'] for d in ds]})")
check(all(node(p)[0] == st[0] for p in P), "parts: in the stack's folder")

# ================================================================ not clear: stays "Stack - split?"
OTHER = up(Fr, "vergeben.pdf", stack_pdf(["Ein Brief mit Nummer"]))
done(Fr, OTHER)
check(Fr.patch(B + f"/api/docs/{OTHER}", json={"asn": 701}).ok, "setup: number 701 taken in the workspace")
UNCLEAR = {
    "a page before the first code": ["Deckblatt ohne Code", "qr:ASN00601\nRechnung", "qr:ASN00602\nVertrag"],
    "a number twice in the stack": ["qr:ASN00611\nRechnung", "qr:ASN00612\nVertrag", "qr:ASN00611\nNoch einmal"],
    "a number already taken": ["qr:ASN00701\nRechnung", "qr:ASN00702\nVertrag"],
    "a separator sheet followed by a page without a code": ["qr:ASN00621\nRechnung", "qr:KALMIDO-SPLIT\nTrennblatt", "Brief ohne Code"],
}
U = {why: up(Fr, f"stapel-{i}.pdf", stack_pdf(pages)) for i, (why, pages) in enumerate(UNCLEAR.items())}
for why, nid in U.items():
    done(Fr, nid)
queue_passed(Fr, "nach-unklar")
for why, nid in U.items():
    d = doc(Fr, nid)
    check(scan(nid).get("state") == "open" and d and (d.get("split") or {}).get("stack") is True and d["review"] and node(nid)[2] is None,
          f"{why}: stays 'Stack - split?' in To review ({scan(nid).get('state')} {d and d.get('split')})")

# ================================================================ undo of an automatic split
r = Fr.post(B + f"/api/docs/{SID}/unsplit")
check(r.ok, f"undo of the automatic split ({r.status_code} {r.text[:160]})")
check(all(node(p)[2] is not None for p in P) and node(SID)[2] is None, "undo: the parts in the trash, the stack back")
check(scan(SID).get("state") == "open" and scan(SID).get("hand") == 1 and not scan(SID).get("auto"), f"undo: the stack waits for a person ({scan(SID)})")
d = doc(Fr, SID)
check(d and (d.get("split") or {}).get("stack") is True and d["review"] and d["asn"] == 501, f"undo: 'Stack - split?' again with its number ({d and d.get('split')} {d and d['asn']})")
kt.dbx("UPDATE doc_meta SET state='wait', tries=0 WHERE node_id=?", (SID,))  # a new recognition run ("Recognise again")
done(Fr, SID)
queue_passed(Fr, "nach-rueckgaengig")
check(scan(SID).get("state") == "open" and node(SID)[2] is None, f"a new recognition run does not split it again ({scan(SID).get('state')})")
j = Fr.get(B + f"/api/docs/{SID}/split").json()
check(j.get("clear") == [[1, 2], [3], [5]] and j.get("name") == "stapel-klar.pdf", f"GET split: the clear cuts for the redo ({j.get('clear')} {j.get('name')})")
r = Fr.post(B + f"/api/docs/{SID}/split", json={"parts": j.get("clear") or [[1], [2]]})
check(r.status_code == 201 and len(r.json().get("ids") or []) == 3, f"redo: split by hand with the clear cuts ({r.status_code} {r.text[:120]})")
P2 = (r.json().get("ids") or []) if r.ok else []
check(P2 and not any((doc(Fr, p).get("split") or {}).get("auto") for p in P2), "a split by hand: no 'automatically' hint")
check(Fr.post(B + f"/api/docs/{SID}/unsplit").ok, "undo of the split by hand")

# ================================================================ an agent's upload: split in its own folder, never another
r = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot"})
assert r.status_code == 201, r.text
AID, AT = r.json()["id"], r.json().get("token") or ""
kt.dbx("DELETE FROM org_members WHERE user_id=?", (AID,))
kt.dbx("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FID, AID))
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + AT})
r = AG.post(V + "/documents", files=[("file", ("agent-stapel.pdf", stack_pdf(["qr:ASN00801\nRechnung", "qr:ASN00802\nVertrag"]), "application/pdf"))])
check(r.status_code == 201, f"the agent uploads a clear stack ({r.status_code} {r.text[:160]})")
AS = (r.json().get("data") or r.json()).get("id") if r.ok else None
PA = split_done(AS) if AS else None
check(PA and len(PA) == 2, f"agent's stack: split by the queue ({AS and scan(AS).get('state')})")
if PA:
    sa = node(AS)
    check(all(node(p)[0] == sa[0] for p in PA), f"agent's stack: the parts stay in its folder ({sa[0]} {[node(p)[0] for p in PA]})")
    check(sa[3] == sa[1] and all(node(p)[1] == sa[1] for p in PA), f"agent's stack: split as the folder's owner ({sa} {[node(p) for p in PA]})")
    check(asns(PA) == [801, 802], f"agent's stack: the numbers {asns(PA)}")
    check(AG.post(B + f"/api/docs/{AS}/unsplit").status_code in (401, 403, 404), "the agent cannot undo it")

# ================================================================ in an organisation
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
OS = up(A, "org-stapel.pdf", stack_pdf(["qr:ASN00901\nRechnung", "qr:ASN00902\nVertrag"]), f"org:{ORG}")
PO = split_done(OS)
check(PO and len(PO) == 2 and asns(PO) == [901, 902], f"organisation: a clear stack split by the queue ({scan(OS).get('state')} {PO and asns(PO)})")
check(Fr.post(B + f"/api/docs/{OS}/unsplit").status_code == 404, "another person: no undo of the organisation's stack (404)")
check(A.post(B + f"/api/docs/{OS}/unsplit").ok, "organisation: the undo works")

sys.exit(kt.done("p2580_c_autosplit_api"))
