#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.636.0 C (#4565): the project type Shoot (decided 04.11.2026): every card one shot with the fields Scene, Shot size,
Lens, Location (+ its picture = the first image file), the columns are the shooting days, the board is the storyboard and
GET /api/lists/<id>/shotlist.pdf the shot list (one table per day). Only with the industry Film & Video (#4573).
 - without Film & Video: POST /api/lists {ptype: shoot} 400, PATCH a list to shoot 400
 - with it: the type's view (board), sections Shooting day 1 / 2, the four fields (Shot size a selection of seven sizes,
   Scene + Shot size pinned), the modules Kanban and Custom fields switched on
 - the PDF: application/pdf, the days in their order, the shots with No., Scene, Shot size (the option's name), Lens,
   Location, the picture embedded as an image; done=0 leaves a completed shot out
 - another person's shoot 404, not a shoot 404, Film & Video switched off again: the list stays, its PDF 404
freelancer-matrix: lists (frida has no organisation: her own industry, her shoot in the private workspace, its PDF)
usage: p2636_c_dreh_api_test.py <datadir>"""
import re
import struct
import sys
import zlib

import kt
from kt import B, check
from freelancer_fixture import freelancer

A = kt.setup()
FID, Fr = freelancer(B, A)


def pdf_text(data):
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def hx(s):
    return s.encode("cp1252").hex()


def png(w=32, h=18, rgb=(200, 40, 40)):
    """A small PNG (no library): w x h pixels of one colour."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def state(s):
    return s.get(B + "/api/state").json()


# ================================================================== without Film & Video: no shoot
check((state(Fr).get("industry") or {}).get("code") == "", "frida starts without an industry")
r = Fr.post(B + "/api/lists", json={"name": "Shoot without film", "ptype": "shoot", "sections": True})
check(r.status_code == 400, f"no Film & Video: a shoot is refused ({r.status_code} {r.text[:80]})")
check(not any(l["name"] == "Shoot without film" for l in state(Fr)["lists"]), "... and nothing was made")
r = Fr.post(B + "/api/lists", json={"name": "Plain project", "kind": "project"})
check(r.ok, "a plain project " + r.text[:80])
PLAIN = r.json()["id"]
r = Fr.patch(B + f"/api/lists/{PLAIN}", json={"ptype": "shoot"})
check(r.status_code == 400, f"no Film & Video: a list does not become a shoot ({r.status_code})")
check(Fr.patch(B + f"/api/lists/{PLAIN}", json={"ptype": "agency"}).ok, "another type still works")
r = Fr.get(B + f"/api/lists/{PLAIN}/shotlist.pdf")
check(r.status_code == 404, f"not a shoot: no shot list ({r.status_code})")

# ================================================================== Film & Video: the shoot project
r = Fr.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and (state(Fr).get("industry") or {}).get("code") == "film", "frida chooses Film & Video " + r.text[:80])
Fr.patch(B + "/api/settings", json={"features": "cal,collab,time,progress,deps,comments,files"})  # without kanban / fields
r = Fr.post(B + "/api/lists", json={"name": "Promo shoot", "ptype": "shoot", "sections": True})
check(r.ok, "a shoot " + r.text[:120])
L = r.json()["id"]
S = state(Fr)
lst = next(l for l in S["lists"] if l["id"] == L)
check(lst.get("ptype") == "shoot" and lst.get("view") == "kanban", f"type shoot, the board ({lst.get('ptype')}, {lst.get('view')})")
secs = [s for s in S["sections"] if s["list_id"] == L]
check([s["name"] for s in secs] == ["Shooting day 1", "Shooting day 2"], "the shooting days " + str([s["name"] for s in secs]))
fs = [f for f in S["fields"] if f["list_id"] == L]
check([(f["name"], f["type"]) for f in fs] == [("Scene", "text"), ("Shot size", "select"), ("Lens", "text"), ("Location", "text")],
      "the four fields " + str([(f["name"], f["type"]) for f in fs]))
F = {f["name"]: f for f in fs}
opts = [(o["id"], o["name"]) for o in F["Shot size"]["options"].get("options", [])]
check(opts == [("ws", "Wide shot"), ("mws", "Medium wide shot"), ("ms", "Medium shot"), ("as", "American shot"), ("mcu", "Medium close-up"),
               ("cu", "Close-up"), ("ecu", "Extreme close-up")], "the seven shot sizes " + str(opts))
check([f["name"] for f in fs if f["pinned"]] == ["Scene", "Shot size"], "Scene and Shot size on the cards " + str([f["name"] for f in fs if f["pinned"]]))
feats = (S.get("settings") or {}).get("features") or ""
check("kanban" in feats.split(",") and "fields" in feats.split(","), "Kanban and Custom fields switched on " + feats)

# ================================================================== shots
D1, D2 = secs[0]["id"], secs[1]["id"]


def shot(title, sec, scene, size, lens, loc):
    r = Fr.post(B + "/api/tasks", json={"list_id": L, "title": title, "section_id": sec})
    assert r.ok, r.text
    tid = r.json()["id"]
    r = Fr.patch(B + f"/api/tasks/{tid}", json={"fields": {str(F["Scene"]["id"]): scene, str(F["Shot size"]["id"]): size,
                                                           str(F["Lens"]["id"]): lens, str(F["Location"]["id"]): loc}})
    assert r.ok, r.text
    return tid


T1 = shot("Opening on the roof", D1, "12A", "ws", "24 mm", "Rooftop")
T2 = shot("Hands on the keyboard", D1, "12B", "ecu", "100 mm macro", "Office")
T3 = shot("Interview CEO", D2, "30", "mcu", "50 mm", "Meeting room")
T4 = shot("Drone fly-over", D2, "31", "ws", "", "Harbour")
r = Fr.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("frame.png", png(), "image/png")})
check(r.ok, "a picture for shot 1 " + r.text[:120])
check(Fr.post(B + f"/api/tasks/{T4}/complete", json={}).ok, "shot 4 done")

# ================================================================== the shot list PDF
r = Fr.get(B + f"/api/lists/{L}/shotlist.pdf")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/pdf") and r.content.startswith(b"%PDF"),
      f"the shot list is a PDF ({r.status_code} {r.headers.get('Content-Type')})")
check("shotlist-Promo-shoot.pdf" in r.headers.get("Content-Disposition", ""), "file name " + r.headers.get("Content-Disposition", ""))
P = pdf_text(r.content)
for s in ("Shot list: Promo shoot", "Shooting day 1", "Shooting day 2", "No.", "Picture", "Scene", "Shot size", "Lens", "Location",
          "Opening on the roof", "12A", "Wide shot", "24 mm", "Rooftop", "Hands on the keyboard", "Extreme close-up",
          "Interview CEO", "Medium close-up", "Meeting room", "Drone fly-over", "Harbour", "100 mm", "macro"):
    check(hx(s) in P, f"the PDF names {s!r}")
at = {s: P.find(hx(s)) for s in ("Shooting day 1", "Opening on the roof", "Hands on the keyboard", "Shooting day 2", "Interview CEO", "Drone fly-over")}
check(at["Shooting day 1"] < min(at["Opening on the roof"], at["Hands on the keyboard"]) and max(at["Opening on the roof"], at["Hands on the keyboard"])
      < at["Shooting day 2"] < min(at["Interview CEO"], at["Drone fly-over"]), "the days in their order, each with its shots " + str(at))
check(P.count(hx("Shot size")) == 2, "one table head per day")
check(b"/Sh1" in r.content and b"/Subtype /Image" in r.content, "the picture of shot 1 is in the PDF")
check(b"/Sh2" not in r.content, "only shot 1 has a picture")
check(next(t for t in Fr.get(B + "/api/state").json()["tasks"] if t["id"] == T4)["status"] == 2, "shot 4 is done in the state")
r = Fr.get(B + f"/api/lists/{L}/shotlist.pdf?done=0")
P0 = pdf_text(r.content) if r.ok else ""
check(r.ok and hx("Drone fly-over") not in P0 and hx("Interview CEO") in P0,
      f"done=0: the completed shot is left out ({r.status_code}, drone {hx('Drone fly-over') in P0}, interview {hx('Interview CEO') in P0})")

# ================================================================== who may read it
r = A.get(B + f"/api/lists/{L}/shotlist.pdf")
check(r.status_code == 404, f"another person: 404 ({r.status_code})")
r = Fr.get(B + "/api/lists/999999/shotlist.pdf")
check(r.status_code == 404, f"no such list: 404 ({r.status_code})")

# ================================================================== Film & Video off again
check(Fr.put(B + "/api/industry", json={"industry": ""}).ok, "frida switches the industry off")
check(any(l["id"] == L for l in state(Fr)["lists"]), "the shoot stays (nothing is deleted)")
r = Fr.get(B + f"/api/lists/{L}/shotlist.pdf")
check(r.status_code == 404, f"without Film & Video: no shot list ({r.status_code})")
r = Fr.post(B + "/api/lists", json={"name": "Second shoot", "ptype": "shoot"})
check(r.status_code == 400, f"without Film & Video: no new shoot ({r.status_code})")
check(Fr.patch(B + f"/api/lists/{L}", json={"name": "Promo shoot (old)"}).ok, "the old shoot can still be changed")

sys.exit(kt.done("p2636_c_dreh"))
