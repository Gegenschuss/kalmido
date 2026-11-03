#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.498.0 (#3884): a list's own icon and header picture count as used storage. Invented names only.
 - uploading adds the bytes, replacing swaps them, a preset / no icon / no header strip / a list in the trash takes them off
   (for a person without an organisation, tests/freelancer_fixture.py)
 - they count for who uploaded them, not the list's owner, also after that person left the list; else for the owner
 - a picture from before this version is measured by the watchdog and counts for the owner
 - the upload is refused when the storage is full; replacing a picture that counts for the person still fits
 - the organisation pool sums what its members uploaded"""
import os
import struct
import subprocess
import sys
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess, setup  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
MB = 1024 * 1024


def png(w=64, h=64, rgb=(120, 80, 200)):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"".join(bytes((rgb[0], (rgb[1] + y) % 256, (rgb[2] + x) % 256)) for x in range(w)) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def used(s):
    return s.get(B + "/api/me/storage").json()["used"]


def head(s, lid, **kw):
    return s.post(B + f"/api/lists/{lid}/header", files={"file": ("h.png", png(**kw), "image/png")})


def icon(s, lid, **kw):
    return s.post(B + f"/api/lists/{lid}/icon", files={"file": ("i.png", png(**kw), "image/png")})


def sizes(lid):
    return dbx("SELECT icon_size, icon_by, header_size, header_by FROM lists WHERE id=?", (lid,))[0]


def tick():
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", "import app\nfrom kalmido.core.db import connect\nfrom kalmido.lists.listhead import o3c_pic_tick\n"
                        "c = connect()\no3c_pic_tick(c)\nc.close()\n"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


fresh()
A = setup()
FID, Fr = freelancer(B, A)

# ================================================================ a person without an organisation
S0 = used(Fr)
L = Fr.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
r = head(Fr, L)
check(r.ok, "a header picture " + r.text[:200])
_, _, hs, hb = sizes(L)
check(hs and hs > 0 and hb == FID, f"size and uploader are kept {hs} {hb}")
check(used(Fr) == S0 + hs, f"#3884: the header picture counts {used(Fr)} {S0} {hs}")
r = icon(Fr, L)
check(r.ok, "an icon " + r.text[:200])
ics, ib, _, _ = sizes(L)
check(ics and ics > 0 and ib == FID, f"size and uploader of the icon {ics} {ib}")
check(used(Fr) == S0 + hs + ics, "#3884: the icon counts")
check(head(Fr, L, w=32, h=32, rgb=(10, 160, 90)).ok, "the picture replaced")
hs2 = sizes(L)[2]
check(used(Fr) == S0 + hs2 + ics, "#3884: replacing swaps the bytes")
check(Fr.put(B + f"/api/lists/{L}/header", json={"style": "dots"}).ok, "another strip")
check(used(Fr) == S0 + ics, "#3884: a picture taken off counts no more (its file stays for undo)")
check(Fr.put(B + f"/api/lists/{L}/header", json={"style": "image"}).ok and used(Fr) == S0 + hs2 + ics, "the picture again, it counts again")
check(Fr.put(B + f"/api/lists/{L}/icon", json={"preset": "coffee"}).ok, "a preset icon")
check(sizes(L)[:2] == (None, None) and used(Fr) == S0 + hs2, "#3884: a preset holds no bytes")
check(icon(Fr, L).ok and Fr.delete(B + f"/api/lists/{L}/icon").ok and used(Fr) == S0 + hs2, "#3884: no icon takes the bytes off")

# ================================================================ a picture from before: measured, for the owner
check(icon(Fr, L).ok, "an icon again")
hs_up, ics_up = sizes(L)[2], sizes(L)[0]
dbx("UPDATE lists SET icon_size=NULL, icon_by=NULL, header_size=NULL, header_by=NULL WHERE id=?", (L,))
check(used(Fr) == S0, "not measured yet: nothing counts")
tick()
ics, ib, hs, hb = sizes(L)
check(ics and hs and ib is None and hb is None, f"#3884: the watchdog measures the old pictures {sizes(L)}")
check(used(Fr) == S0 + ics + hs, "#3884: they count for the owner")
check((ics, hs) == (ics_up, hs_up), f"#3884: upload and watchdog measure the same (plain) size {ics} {ics_up} {hs} {hs_up}")

# ================================================================ a full storage
check(A.patch(B + f"/api/users/{FID}", json={"storage_quota_mb": 1}).ok, "1 MB")
L2 = Fr.post(B + "/api/lists", json={"name": "Shed"}).json()["id"]
check(head(Fr, L2).ok, "there is room")
dbx("UPDATE lists SET icon_size=? WHERE id=?", (MB - used(Fr), L2))  # the rest of the 1 MB as a measured picture
check(used(Fr) == MB, "the storage is exactly full")
r = icon(Fr, L)
check(r.ok, f"#3884: replacing a picture that counts here still fits {r.status_code} {r.text[:200]}")
dbx("UPDATE lists SET icon_size=icon_size+? WHERE id=?", (MB - used(Fr), L2))  # sealed files measure a little more than the picture
L3 = Fr.post(B + "/api/lists", json={"name": "Attic"}).json()["id"]
before = sizes(L3)
r = head(Fr, L3)
check(r.status_code == 413 and r.json().get("code") == "quota_exceeded", f"#3884: a full storage refuses the header picture {r.status_code} {r.text[:200]}")
r = icon(Fr, L3)
check(r.status_code == 413, f"#3884: a full storage refuses the icon {r.status_code} {r.text[:200]}")
check(sizes(L3) == before, "a refused picture leaves nothing behind")
# 2.498.0 (#3884, review): a header switched off is not counted, so its bytes are no room for a new one
check(Fr.put(B + f"/api/lists/{L}/header", json={"style": "dots"}).ok, "the header off")
dbx("UPDATE lists SET icon_size=icon_size+? WHERE id=?", (MB - used(Fr), L2))
r = head(Fr, L, w=32, h=32, rgb=(10, 160, 90))  # the same picture: only the wrong credit would make it fit
check(r.status_code == 413, f"#3884: the old picture that does not count frees nothing {r.status_code} {r.text[:200]}")
check(Fr.put(B + f"/api/lists/{L}/header", json={"style": "image"}).ok, "the header on again")
# 2.498.0 (#3884, review): a stale size next to a preset frees no room either: only a picture that counts does
ic_old, ics_old = dbx("SELECT icon, icon_size FROM lists WHERE id=?", (L,))[0]
dbx("UPDATE lists SET icon='coffee', icon_size=? WHERE id=?", (MB, L))
dbx("UPDATE lists SET icon_size=icon_size+? WHERE id=?", (MB - used(Fr), L2))
check(used(Fr) == MB, "full again")
r = icon(Fr, L)
check(r.status_code == 413, f"#3884: a preset with an old size column frees nothing {r.status_code} {r.text[:200]}")
dbx("UPDATE lists SET icon=?, icon_size=? WHERE id=?", (ic_old, ics_old, L))
# 2.498.0 (#3884, review): the storage away for a moment leaves no lasting 0, only a file that is gone counts as 0
r = subprocess.run(["docker", "exec", CT, "python3", "-c", "import app\nimport kalmido.lists.listhead as h\n"
                    "print(h._pic_size('/nonexistent/x'))\n"
                    "def boom(p): raise PermissionError(p)\n"
                    "h.oc_plain_size = boom\nprint(h._pic_size('/x'))\n"], capture_output=True, text=True, timeout=120)
check(r.stdout.split()[-2:] == ["0", "None"], f"#3884: gone = 0, not readable right now = not measured {r.stdout} {r.stderr[:300]}")
check(A.patch(B + f"/api/users/{FID}", json={"storage_quota_mb": None}).ok, "no limit again")

# ================================================================ a shared list: who uploaded it, and the organisation pool
check(A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]}).ok, "an organisation")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
check(r.ok, "a member " + r.text[:200])
BOB, Bo = r.json()["id"], sess("bob")
W = A.post(B + "/api/lists", json={"name": "Yard", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "admin"}).ok, "bob is a list admin")
SA, SB = used(A), used(Bo)
check(head(Bo, W).ok, "bob uploads into alice's list")
hs = sizes(W)[2]
check(used(Bo) == SB + hs and used(A) == SA, f"#3884: it counts for who uploaded it, not the owner {used(Bo)} {used(A)}")
check(A.delete(B + f"/api/lists/{W}/members/{BOB}").ok, "bob leaves the list")
check(used(Bo) == SB + hs, "#3884: still counted after leaving the list")
check(A.patch(B + "/api/admin/settings", json={"storage_pool": "org"}).ok, "the organisation pool")
check(used(A) == SA + SB + hs, f"#3884: the pool sums its members {used(A)} {SA} {SB} {hs}")
check(A.patch(B + "/api/admin/settings", json={"storage_pool": "user"}).ok, "pool per person again")
dbx("UPDATE lists SET header_by=NULL WHERE id=?", (W,))  # the uploader's account is gone
check(used(Bo) == SB and used(A) == SA + hs, "#3884: without an uploader it counts for the owner")

# ================================================================ the undo of an organisation import takes the picture off, the size column stays
ic0 = used(Fr)
r = sizes(L)[0]
check(r and dbx("SELECT icon FROM lists WHERE id=?", (L,))[0][0].startswith("u:"), "the list has its own icon")
old_icon = dbx("SELECT icon FROM lists WHERE id=?", (L,))[0][0]
dbx("UPDATE lists SET icon=NULL WHERE id=?", (L,))  # as admin/orgimport.py on undo: only the value, the column of the size stays
check(used(Fr) == ic0 - r, f"#3884: an icon that is gone counts no more, whatever its size column says {used(Fr)} {ic0} {r}")
dbx("UPDATE lists SET icon=? WHERE id=?", (old_icon, L))

# ================================================================ a deleted list takes the bytes along
check(Fr.patch(B + f"/api/lists/{L2}", json={"archived": 1}).ok, "the list archived")
check(Fr.delete(B + f"/api/lists/{L2}").ok, "the list goes")
check(dbx("SELECT deleted_at FROM lists WHERE id=?", (L2,))[0][0], "it lies in the trash")
check(used(Fr) == sizes(L)[0] + sizes(L)[2] + S0, f"#3884: a list in the trash counts no more {used(Fr)} {sizes(L)}")
sys.exit(done("p2498_b_quota"))
