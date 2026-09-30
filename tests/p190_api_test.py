#!/usr/bin/env python3
"""1.9.0 API tests (fresh DB on the TEST container :3048).
- Share from your phone: GET /api/me/share/httpshortcuts.zip (login only, per user: /drop address + own upload token,
  two shortcuts (files: file_picker_multi, text: share-text variable -> field "text"), compatibilityVersion 90, fresh
  UUIDs, the Kalmido icon), both requests really work against /drop; /api/state carries share.drop_url / ios_shortcut.
- Profile pictures: presets (PUT), own photo (POST: resized to 256 px square JPEG, EXIF / GPS gone, upright, junk and
  oversize refused), served only to the user, admins and people sharing a list; a new picture replaces the file;
  DELETE; admins can set a preset for someone else; the avatars map in /api/state; deleting the user removes the file.
- Tags: count, delete (only my own tag rows, trash included, tasks stay), restore (undo), CSRF, bad input.
- News: news_kinds setting (default without "complete"), validation, filter=me, dismiss (only own items).
- Update check: a cached release older than the running version is not reported (admin status + about)."""
import io, json, os, sqlite3, sys, time, uuid, zipfile
import requests
from PIL import Image

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def db():
    return sqlite3.connect(os.path.join(DATA, "tasks.db"))


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("carol", "Carol"), ("dave", "Dave")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bb, C, D = sess("bob"), sess("carol"), sess("dave")
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for u in ("bob", "carol"):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": "edit"}).ok

# ================================================================== share from your phone
st = A.get(B + "/api/state").json()
check(st["share"]["drop_url"] == "https://kalmido.example/drop" and st["share"]["ios_shortcut"] == "", f"state.share {st.get('share')}")
check(sess().get(B + "/api/me/share/httpshortcuts.zip").status_code in (401, 403), "zip needs a login")
r = A.get(B + "/api/me/share/httpshortcuts.zip")
check(r.ok and r.headers["Content-Type"] == "application/zip" and "attachment" in r.headers.get("Content-Disposition", "")
      and r.headers.get("Cache-Control") == "no-store", f"zip headers {r.status_code} {dict(r.headers)}")
z = zipfile.ZipFile(io.BytesIO(r.content))
names = z.namelist()
sj = json.loads(z.read("shortcuts.json"))
tok = A.get(B + "/api/me").json()["drop_token"]
cat = sj["categories"][0]
scs = cat["shortcuts"]
check(sj["compatibilityVersion"] == 90 and sj["version"] >= 1 and len(scs) == 2, f"format {sj.get('compatibilityVersion')} {len(scs)}")
icon = scs[0]["iconName"]
check(icon in names and icon.startswith("custom-icon_") and icon.endswith("_circle.png") and len(names) == 2, f"icon file {names}")
im = Image.open(io.BytesIO(z.read(icon)))
check(im.format == "PNG" and im.size[0] >= 192, "icon is the Kalmido PNG")
for s_ in scs:
    check(s_["method"] == "POST" and s_["url"] == "https://kalmido.example/drop" and s_["requestBodyType"] == "form_data"
          and s_["headers"] == [{"key": "Authorization", "value": "Bearer " + tok}] and s_["iconName"] == icon, f"shortcut {s_['name']}")
fs, ts = scs
check(fs["parameters"] == [{"key": "file", "type": "file", "fileUploadOptions": {"fileUploadType": "file_picker_multi"}}], "file shortcut: file_picker_multi 'file'")
var = sj["variables"][0]
check(ts["parameters"] == [{"key": "text", "type": "string", "value": "{{" + var["id"] + "}}"}] and ts.get("excludeFromFileSharing") is True, "text shortcut: field text = share variable")
check(var["isShareText"] is True and var["type"] == "constant" and var["key"] == "kalmido_shared_text", f"share-text variable {var}")
allids = [cat["id"], fs["id"], ts["id"], var["id"]]
check(all(str(uuid.UUID(x)) == x for x in allids) and len(set(allids)) == 4, "fresh UUIDs")
sj2 = json.loads(zipfile.ZipFile(io.BytesIO(A.get(B + "/api/me/share/httpshortcuts.zip").content)).read("shortcuts.json"))
check(sj2["categories"][0]["shortcuts"][0]["id"] != fs["id"], "a new download has new ids")
btok = Bb.get(B + "/api/me").json()["drop_token"]
bz = json.loads(zipfile.ZipFile(io.BytesIO(Bb.get(B + "/api/me/share/httpshortcuts.zip").content)).read("shortcuts.json"))
check(bz["categories"][0]["shortcuts"][0]["headers"][0]["value"] == "Bearer " + btok and btok != tok, "per user token")
# the two requests as HTTP Shortcuts sends them
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, files=[("file", ("a.txt", b"hi")), ("file", ("b.txt", b"ho"))])
check(r.ok and "2 files" in r.text, f"file shortcut request works {r.status_code} {r.text}")
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + tok}, files={"text": (None, "Read later https://example.org/x")})
check(r.ok and "Read later" in r.text, f"text shortcut request works {r.text}")
inbox = [t for t in A.get(B + "/api/state").json()["tasks"] if t["title"] == "Read later"]
check(len(inbox) == 1 and inbox[0]["url"] == "https://example.org/x", "text share -> inbox task with link")
check(C.get(B + "/api/me").json()["drop_token"], "carol has an own token too")
# German names
A.patch(B + "/api/settings", json={"lang": "de"})
dz = json.loads(zipfile.ZipFile(io.BytesIO(A.get(B + "/api/me/share/httpshortcuts.zip").content)).read("shortcuts.json"))
check(dz["categories"][0]["shortcuts"][1]["name"] == "Kalmido Text", "shortcut names in the user's language")
A.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== profile pictures
check(A.get(B + "/api/me").json()["avatar"] == "", "no picture by default")
r = A.put(B + "/api/me/avatar", json={"preset": "coffee"})
check(r.ok and r.json()["avatar"] == "/static/avatars/coffee.svg", f"preset {r.text}")
check(A.put(B + "/api/me/avatar", json={"preset": "../x"}).status_code == 400, "unknown preset refused")
check(requests.put(B + "/api/me/avatar", json={"preset": "robot"}, cookies=A.cookies).status_code in (400, 403), "CSRF header needed")
check(A.get(B + "/static/avatars/coffee.svg").ok, "preset file served")
for k in ("coffee", "headphones", "camera", "sleepy", "laptop", "plant", "robot", "shades", "party", "glasses"):
    r = requests.get(B + f"/static/avatars/{k}.svg")
    check(r.ok and r.text.startswith("<svg") and "<script" not in r.text, f"preset {k}")
st = Bb.get(B + "/api/state").json()
check(st["avatars"].get("1") == "/static/avatars/coffee.svg", f"bob sees alice's picture (shared list) {st['avatars']}")
check("1" not in D.get(B + "/api/state").json()["avatars"], "dave (no shared list) does not")


def jpeg_with_exif(w=900, h=600, orientation=6):
    im = Image.new("RGB", (w, h), (200, 30, 30))
    im.paste((0, 0, 255), (0, 0, w // 2, h))  # left half blue
    ex = Image.Exif()
    ex[0x0112] = orientation              # rotate 90 cw when shown
    ex[0x010F] = "SecretCam"              # make
    ex[0x8825] = {1: "N", 2: (52.0, 31.0, 12.0)}  # GPS
    out = io.BytesIO()
    im.save(out, "JPEG", exif=ex.tobytes())
    return out.getvalue()


raw = jpeg_with_exif()
check(b"SecretCam" in raw, "test photo carries EXIF")
r = Bb.post(B + "/api/me/avatar", files={"file": ("me.jpg", raw, "image/jpeg")})
check(r.ok and r.json()["avatar"].startswith(f"/api/avatar/{ids['bob']}/"), f"photo upload {r.status_code} {r.text}")
url = r.json()["avatar"]
g = Bb.get(B + url)
check(g.ok and g.headers["Content-Type"] == "image/jpeg" and "private" in g.headers.get("Cache-Control", ""), "photo served to the owner")
out = Image.open(io.BytesIO(g.content))
check(out.size == (256, 256) and out.format == "JPEG", f"resized square {out.size}")
check(b"SecretCam" not in g.content and not out.getexif(), "EXIF / GPS stripped")
px = lambda x, y: out.convert("RGB").getpixel((x, y))
check(px(128, 10)[2] > 150 and px(128, 245)[0] > 150, f"turned upright: the left (blue) half is on top now {px(128, 10)} {px(128, 245)}")
check(A.get(B + url).ok, "admin sees it")
check(C.get(B + url).ok, "carol (shares a list) sees it")
check(D.get(B + url).status_code == 404, "dave (no shared list) gets 404")
check(sess().get(B + url).status_code in (401, 403), "no login: refused")
check(Bb.get(B + url.replace(".jpg", "x.jpg")).status_code == 404, "wrong token: 404")
f1 = [f for f in os.listdir(os.path.join(DATA, "attachments", "avatars"))]
check(len(f1) == 1 and f1[0].startswith(f"u{ids['bob']}-"), f"stored below attachments/avatars {f1}")
png = io.BytesIO()
Image.new("RGBA", (300, 500), (0, 200, 0, 128)).save(png, "PNG")
r = Bb.post(B + "/api/me/avatar", files={"file": ("p.png", png.getvalue(), "image/png")})
url2 = r.json().get("avatar", "")
check(r.ok and url2 != url and Bb.get(B + url).status_code == 404 and Bb.get(B + url2).ok, "a new photo replaces the old one (new URL)")
check(len(os.listdir(os.path.join(DATA, "attachments", "avatars"))) == 1, "old file removed")
check(Bb.post(B + "/api/me/avatar", files={"file": ("x.jpg", b"not an image at all", "image/jpeg")}).status_code == 400, "junk refused")
svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
check(Bb.post(B + "/api/me/avatar", files={"file": ("x.svg", svg, "image/svg+xml")}).status_code == 400, "SVG upload refused")
check(Bb.post(B + "/api/me/avatar").status_code == 400, "no file refused")
big = os.urandom(1024 * 1024 * 5)
r = Bb.post(B + "/api/me/avatar", files={"file": ("big.jpg", big, "image/jpeg")})
check(r.status_code in (400, 413), f"oversize refused ({r.status_code})")
check(Bb.get(B + url2).ok, "the picture is unchanged after refused uploads")
st = C.get(B + "/api/state").json()
check(st["avatars"].get(str(ids["bob"])) == url2, "state map has bob's photo URL")
users = A.get(B + "/api/users").json()["users"]
check(next(u for u in users if u["id"] == ids["bob"])["avatar"] == url2, "admin user list carries the picture")
r = Bb.delete(B + "/api/me/avatar")
check(r.ok and Bb.get(B + "/api/me").json()["avatar"] == "" and not os.listdir(os.path.join(DATA, "attachments", "avatars")), "DELETE: back to initials, file gone")
# admin sets a preset for dave (e.g. a bot user); non-admins cannot
r = A.patch(B + f"/api/users/{ids['dave']}", json={"avatar_preset": "robot"})
check(r.ok and r.json()["avatar"] == "/static/avatars/robot.svg", "admin sets a preset for another user")
check(A.patch(B + f"/api/users/{ids['dave']}", json={"avatar_preset": "nope"}).status_code == 400, "admin: unknown preset refused")
check(Bb.patch(B + f"/api/users/{ids['dave']}", json={"avatar_preset": "coffee"}).status_code == 403, "non-admin cannot")
check(D.get(B + "/api/me").json()["avatar"] == "/static/avatars/robot.svg", "dave sees the preset")
# deleting a user removes the photo
r = C.post(B + "/api/me/avatar", files={"file": ("me.jpg", jpeg_with_exif(200, 200, 1), "image/jpeg")})
check(r.ok and len(os.listdir(os.path.join(DATA, "attachments", "avatars"))) == 1, "carol has a photo")
assert A.delete(B + f"/api/lists/{L}/members/{ids['carol']}").ok or True
check(A.delete(B + f"/api/users/{ids['carol']}").ok and not os.listdir(os.path.join(DATA, "attachments", "avatars")), "user deleted: photo file gone")

# ================================================================== tags
t1 = A.post(B + "/api/tasks", json={"title": "T1", "list_id": L, "tags": ["x", "keep"]}).json()["id"]
t2 = A.post(B + "/api/tasks", json={"title": "T2", "tags": ["x"]}).json()["id"]
t3 = A.post(B + "/api/tasks", json={"title": "T3", "tags": ["x"]}).json()["id"]
A.post(B + f"/api/tasks/{t2}/complete", json={})
A.delete(B + f"/api/tasks/{t3}")  # trash
Bb.patch(B + f"/api/tasks/{t1}", json={"tags": ["x"]})  # bob's own tag x on the same task
r = A.get(B + "/api/tags/count", params={"tag": "#x"})
check(r.json() == {"tasks": 2, "open": 1}, f"count (trash not counted) {r.json()}")
check(A.get(B + "/api/tags/count").status_code == 400, "count: tag missing")
check(requests.post(B + "/api/tags/delete", json={"tag": "x"}, cookies=A.cookies).status_code in (400, 403), "delete: CSRF")
v0 = A.get(B + "/api/version").json()["v"]
r = A.post(B + "/api/tags/delete", json={"tag": "x"})
check(r.ok and sorted(r.json()["ids"]) == sorted([t1, t2, t3]) and r.json()["count"] == 2, f"delete {r.json()}")
check(A.get(B + "/api/version").json()["v"] > v0, "version bumped")
with db() as c:
    rows = c.execute("SELECT task_id, user_id, tag FROM task_tags WHERE tag='x' ORDER BY user_id").fetchall()
check(rows == [(t1, ids["bob"], "x")], f"only alice's rows gone, bob's tag stays {rows}")
st = A.get(B + "/api/state").json()
tt = {t["id"]: t for t in st["tasks"]}
check(tt[t1]["tags"] == ["keep"] and t1 in tt, "task stays with its other tags")
r = A.post(B + "/api/tags/restore", json={"tag": "x", "ids": r.json()["ids"]})
check(r.ok and r.json()["count"] == 3, f"restore (undo) {r.json()}")
check(A.get(B + "/api/tags/count", params={"tag": "x"}).json() == {"tasks": 2, "open": 1}, "all back")
dt = D.post(B + "/api/tasks", json={"title": "Dave's"}).json()["id"]
r = A.post(B + "/api/tags/restore", json={"tag": "x", "ids": [dt]})
check(r.ok and r.json()["count"] == 0, "restore skips tasks I cannot see")
check(A.post(B + "/api/tags/delete", json={"tag": ""}).status_code == 400, "empty tag refused")
check(A.post(B + "/api/tags/restore", json={"tag": "x", "ids": ["a"]}).status_code == 400, "bad ids refused")
r = A.post(B + "/api/tags/delete", json={"tag": "nothing-here"})
check(r.ok and r.json()["ids"] == [] and r.json()["count"] == 0, "unknown tag: nothing to do")

# ================================================================== news
st = Bb.get(B + "/api/state").json()
check(st["settings"]["news_kinds"] == "mention,assign,comment,unblock,share,status", "default news kinds without complete")
check(Bb.patch(B + "/api/settings", json={"news_kinds": "mention,bogus"}).status_code == 400, "unknown kind refused")
tc = Bb.post(B + "/api/tasks", json={"title": "Bob's", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{tc}/complete", json={})
kinds = [x["kind"] for x in Bb.get(B + "/api/news").json()["items"]]
check("complete" not in kinds, f"default: no complete item {kinds}")
Bb.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"})
tc2 = Bb.post(B + "/api/tasks", json={"title": "Bob's 2", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{tc2}/complete", json={})
check([x["kind"] for x in Bb.get(B + "/api/news").json()["items"]][0] == "complete", "complete on: item")
Bb.patch(B + "/api/settings", json={"news_kinds": "assign"})
A.post(B + f"/api/tasks/{t1}/comments", json={"body": f"<@{ids['bob']}> hi"})
check([x["kind"] for x in Bb.get(B + "/api/news").json()["items"]][0] != "mention", "mention off: no item")
A.post(B + "/api/tasks", json={"title": "For Bob", "list_id": L, "assignee_id": ids["bob"]})
Bb.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status"})
A.post(B + f"/api/tasks/{t1}/comments", json={"body": f"<@{ids['bob']}> again"})
nj = Bb.get(B + "/api/news", params={"filter": "me"}).json()
check({x["kind"] for x in nj["items"]} <= {"mention", "assign", "unassign"} and {"mention", "assign"} <= {x["kind"] for x in nj["items"]}, f"filter=me {[x['kind'] for x in nj['items']]}")
check("avatars" in nj, "news answer carries the avatars map")
allitems = Bb.get(B + "/api/news").json()
first = allitems["items"][0]
u0 = allitems["unread"]
r = Bb.post(B + "/api/news/dismiss", json={"ids": first["ids"]})
check(r.ok and r.json()["unread"] == u0 - (0 if first["read"] else 1), "dismiss: unread count follows")
check(all(x["id"] != first["id"] for x in Bb.get(B + "/api/news").json()["items"]), "dismissed item gone")
aitems = A.get(B + "/api/news").json()["items"]
if aitems:
    Bb.post(B + "/api/news/dismiss", json={"ids": [aitems[0]["id"]]})
    check(any(x["id"] == aitems[0]["id"] for x in A.get(B + "/api/news").json()["items"]), "cannot dismiss other people's items")
check(Bb.post(B + "/api/news/dismiss", json={"ids": ["x"]}).status_code == 400, "dismiss: bad ids")

# ================================================================== update check: stale cache
with db() as c:
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('update_info', ?)",
              (json.dumps({"checked_at": "2026-09-27T21:30:00Z", "latest": "1.2.0", "url": "https://github.com/x", "error": ""}),))
tk = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "admin-read"]}).json()["token"]
r = requests.get(B + "/api/v1/admin/status", headers={"Authorization": "Bearer " + tk})
j = r.json()
check(r.ok and j["latest_version"] == j["version"] and j["update_available"] is False and "update_checked_at" in j and "update_error" in j,
      f"stale older release not reported {j}")
ab = A.get(B + "/api/state").json()["about"]
check(ab["latest"] == ab["version"] and ab["url"] == "", f"about: no stale latest {ab.get('latest')}")
with db() as c:
    c.execute("UPDATE settings SET value=? WHERE key='update_info'", (json.dumps({"checked_at": "2026-09-27T21:30:00Z", "latest": "99.0.0", "url": "https://github.com/x"}),))
j = requests.get(B + "/api/v1/admin/status", headers={"Authorization": "Bearer " + tk}).json()
check(j["latest_version"] == "99.0.0" and j["update_available"] is True, "a newer release is still reported")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
