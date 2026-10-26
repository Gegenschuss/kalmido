#!/usr/bin/env python3
"""2.240.0 D (#2886) API test, own container (start.sh): the public customer page of a video sign-off (/s/q/<token>) never
embeds a player by itself -- a placeholder with the provider's name and a "Load video" button comes first (no <iframe> /
<video> in the HTML, the embed URL only in data-src for static/js/pubvideo.js), in English and German; the setting
video_ext_ok is a plain flag (default 0) and does not change the customer page; the CSP still names exactly the two frame hosts
(media-src https: stays, a direct video file from any host is a feature, #2717). Invented data only.
tenant-matrix: video
freelancer-matrix: videos
usage: p2240_d_videogate_test.py <datadir>      (P2240D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import re
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import check, sess  # shared helpers (tests/kt.py)

if os.environ.get("P2240D_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,clients", "tour": "done"})
FID, Fr = freelancer(B, A)


def page(token, lang):
    return requests.get(B + "/s/q/" + token, allow_redirects=False, headers={"Accept-Language": lang})


def gate_checks(s, link, name_en, name_de, label):
    lst = s.post(B + "/api/lists", json={"name": "Film " + label, "kind": "project"}).json()["id"]
    t = s.post(B + "/api/tasks", json={"title": "Schnitt " + label, "list_id": lst}).json()["id"]
    r = s.post(B + "/api/videos", json={"task_id": t, "title": "Film " + label, "url": link})
    assert r.ok, r.text
    rid = r.json()["id"]
    so = s.post(B + f"/api/videos/{rid}/signoff", json={})
    assert so.ok, so.text
    tok = so.json()["url"].split("/s/q/")[1]
    en, de = page(tok, "en"), page(tok, "de")
    check(en.status_code == 200 and "<iframe" not in en.text and "<video" not in en.text, f"{label}: no player in the page before the click")
    check("data-vdr-load" in en.text and "data-src=" in en.text and f"to {name_en}." in en.text and "Load video" in en.text,
          f"{label}: placeholder with the provider's name and the button")
    check("<iframe" not in de.text and f"an {name_de}." in de.text and "Video laden" in de.text and "IP-Adresse" in de.text,
          f"{label}: the German text")
    check("ytimg" not in en.text and "vumbnail" not in en.text, f"{label}: no thumbnail of the provider")
    # 2.240.0 D2 (#2886): without JavaScript a noscript link opens the video; still no iframe / video element
    ns = re.search(r"<noscript>(.*?)</noscript>", en.text, re.S)
    check(ns and link in ns.group(1) and 'target="_blank"' in ns.group(1) and 'rel="noopener noreferrer"' in ns.group(1) and "Open the video" in ns.group(1),
          f"{label}: noscript link 'Open the video'")
    check("Video öffnen" in re.search(r"<noscript>(.*?)</noscript>", de.text, re.S).group(1), f"{label}: noscript link in German")
    return en


en = gate_checks(A, "https://www.youtube.com/watch?v=AbCdEfGhI-9", "YouTube", "YouTube", "yt")
check("youtube-nocookie.com/embed/AbCdEfGhI-9" in en.text, "the embed URL sits in data-src")
gate_checks(A, "https://vimeo.com/123456789", "Vimeo", "Vimeo", "vi")
gate_checks(A, "https://cdn.example.com/film.mp4", "cdn.example.com", "cdn.example.com", "file")
# a person without an organisation: the private review's customer page asks the same
gate_checks(Fr, "https://vimeo.com/987654321", "Vimeo", "Vimeo", "freelancer")

# the flag: default 0, a plain 0/1, and it does not open the customer page
st = A.get(B + "/api/state").json()["settings"]
check(st.get("video_ext_ok") in (None, "0"), f"default off {st.get('video_ext_ok')}")
check(A.patch(B + "/api/settings", json={"video_ext_ok": "1"}).ok and A.get(B + "/api/state").json()["settings"]["video_ext_ok"] == "1", "the flag saves")
check(A.patch(B + "/api/settings", json={"video_ext_ok": "maybe"}).status_code == 400, "a value other than 0 / 1 is refused")
check(Fr.patch(B + "/api/settings", json={"video_ext_ok": "1"}).ok, "the freelancer can set it too")
en2 = gate_checks(A, "https://youtu.be/ZyXwVuTsR01", "YouTube", "YouTube", "yt-flag-on")
check("data-vdr-load" in en2.text, "with video_ext_ok = 1 the customer page still asks (never remembered)")

# the page's CSP: two frame hosts, scripts only from 'self'; media over https stays for direct files
csp = en.headers.get("Content-Security-Policy", "")
check("frame-src https://player.vimeo.com https://www.youtube-nocookie.com" in csp and "script-src 'self'" in csp, f"customer page CSP {csp}")
sys.exit(1 if __import__("kt").FAILS else 0)
