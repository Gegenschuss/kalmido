#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.633.0 D (#4777) API test, own container (start.sh): the sign-off takes audio too -- a direct https link to an MP3, M4A /
AAC, WAV, OGG / Opus or FLAC file is the provider "audio" (recognised by the file name only, nothing is fetched), its player
URL is the link itself, it is timed: a comment at 00:42 keeps its second, a new link is v2 with the comments staying at v1;
http and other schemes are refused, a link that is not an audio (or video) file stays a "link without time control". The
customer page (#4772 approval link) shows the audio placeholder ("Load audio", noscript "Open the audio", no <audio> before
the click), its time line and the timecode field; the page's CSP keeps media-src https: (no new rule). A person without an
organisation does the same with a private review. Invented data only.
freelancer-matrix: videos
usage: p2633_d_audiorev_test.py <datadir>      (P2633D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
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
from kt import FAILS, check, sess  # shared helpers (tests/kt.py)

if os.environ.get("P2633D_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,clients,videos", "tour": "done"})
FID, Fr = freelancer(B, A)
V = "/api/videos"


def audio_flow(s, who):
    """A task with an audio review: v1 = MP3, a comment at 00:42, v2 = M4A, the customer page shows the audio player."""
    lst = s.post(B + "/api/lists", json={"name": "Podcast " + who, "kind": "project"}).json()["id"]
    t = s.post(B + "/api/tasks", json={"title": "Mischung " + who, "list_id": lst}).json()["id"]
    mp3 = "https://media.example.com/folge-12/mix_v1.mp3"
    r = s.post(B + V, json={"task_id": t, "title": "Folge 12 " + who, "url": mp3})
    check(r.ok, f"{who}: an MP3 link makes a review ({r.status_code} {r.text[:200]})")
    if not r.ok:
        return None, lst
    R = r.json()
    rid, v1 = R["id"], R["versions"][0]
    check(v1["provider"] == "audio" and v1["embed"] == mp3 and v1["timed"] and v1["url"] == mp3, f"{who}: v1 is audio, the player plays the link itself {v1}")
    c = s.post(B + f"{V}/{rid}/comments", json={"version_id": v1["id"], "at_sec": "00:42", "body": "Hier knackt es"})
    cm = next((x for x in c.json().get("comments", []) if x["id"] == c.json().get("comment_id")), {}) if c.ok else {}
    check(c.ok and cm.get("at_sec") == 42.0 and cm.get("version_id", v1["id"]) == v1["id"], f"{who}: a comment at 00:42 keeps its second {cm}")
    m4a = "https://media.example.com/folge-12/mix_v2.m4a"
    r2 = s.post(B + f"{V}/{rid}/versions", json={"url": m4a})
    vs = r2.json().get("versions", []) if r2.ok else []
    check(r2.ok and [x["n"] for x in vs] == [1, 2] and vs[-1]["provider"] == "audio" and vs[-1]["embed"] == m4a, f"{who}: a new link = v2 (audio) {vs}")
    full = s.get(B + f"{V}/{rid}").json()
    at1 = [x for x in full.get("comments", []) if x["body"] == "Hier knackt es"]
    check(at1 and at1[0]["version_id"] == v1["id"] and at1[0]["at_sec"] == 42.0, f"{who}: the comment stays at v1 {at1}")
    # the customer link: the newest version (v2) as audio behind the placeholder
    so = s.post(B + f"{V}/{rid}/signoff", json={})
    check(so.ok, f"{who}: a customer link ({so.status_code})")
    if not so.ok:
        return rid, lst
    tok = so.json()["url"].split("/s/q/")[1]
    en = requests.get(B + "/s/q/" + tok, allow_redirects=False, headers={"Accept-Language": "en"})
    de = requests.get(B + "/s/q/" + tok, allow_redirects=False, headers={"Accept-Language": "de"})
    check(en.status_code == 200 and 'class="vdr-player vdr-aud" data-prov="audio"' in en.text and f'data-src="{m4a}"' in en.text,
          f"{who}: the customer page has the audio player box of v2")
    check("<audio" not in en.text and "<video" not in en.text and "<iframe" not in en.text and "Load audio" in en.text
          and "Loading the audio sends data (such as your IP address) to media.example.com." in en.text,
          f"{who}: before the click only the placeholder with the host's name")
    ns = re.search(r"<noscript>(.*?)</noscript>", en.text, re.S)
    check(ns and m4a in ns.group(1) and "Open the audio" in ns.group(1), f"{who}: without JavaScript the link 'Open the audio'")
    check("Audio laden" in de.text and "Beim Laden des Audios" in de.text, f"{who}: the German texts")
    check('id="vd-at"' in en.text and "/static/js/pubvideo.js" in en.text, f"{who}: the customer comments with a timecode (pubvideo.js drives the player)")
    csp = en.headers.get("Content-Security-Policy", "")
    check("media-src https:" in csp and "frame-src https://player.vimeo.com https://www.youtube-nocookie.com" in csp,
          f"{who}: the CSP plays https media as before, no new frame host {csp}")
    # a customer comment at 00:42 through the page arrives with its second
    fk, vk = re.search(r'name="f" value="([^"]+)"', en.text), re.search(r'name="v" value="([^"]+)"', en.text)
    pc = requests.post(B + f"/s/q/{tok}/comments", data={"f": fk.group(1) if fk else "", "v": vk.group(1) if vk else "",
                       "name": "Kundin Example", "text": "Bitte leiser", "at": "00:42"}, allow_redirects=False, headers={"Accept-Language": "en"})
    full = s.get(B + f"{V}/{rid}").json()
    got = [x for x in full.get("comments", []) if x["body"] == "Bitte leiser"]
    check(pc.status_code in (302, 303) and got and got[0]["at_sec"] == 42.0 and got[0]["version_id"] == vs[-1]["id"],
          f"{who}: the customer's comment at 00:42 on v2 ({pc.status_code} {got})")
    page2 = requests.get(B + "/s/q/" + tok, headers={"Accept-Language": "en"}).text
    check('class="vdr-tl"' in page2 and 'class="vdr-mk" data-at="42.0"' in page2, f"{who}: the customer page's time line has the mark at 00:42")
    return rid, lst


RID, LST = audio_flow(A, "org")
audio_flow(Fr, "freelancer")

# every audio ending; capital letters; a Dropbox share page -> the file (raw=1) like a video file
if RID:
    for url in ("https://a.example.com/x.mp3", "https://a.example.com/x.M4A", "https://a.example.com/x.aac", "https://a.example.com/x.wav",
                "https://a.example.com/x.ogg", "https://a.example.com/x.oga", "https://a.example.com/x.opus", "https://a.example.com/x.FLAC",
                "https://a.example.com/x.mp3?token=abc"):
        r = A.post(B + f"{V}/{RID}/versions", json={"url": url})
        vv = r.json()["versions"][-1] if r.ok else {}
        check(r.ok and vv.get("provider") == "audio" and vv.get("embed") == url and vv.get("timed"), f"{url} -> audio ({r.status_code} {vv})")
    r = A.post(B + f"{V}/{RID}/versions", json={"url": "https://www.dropbox.com/scl/fi/xyz/mix.wav?rlkey=k1&dl=0"})
    vv = r.json()["versions"][-1] if r.ok else {}
    check(vv.get("provider") == "audio" and vv.get("embed") == "https://www.dropbox.com/scl/fi/xyz/mix.wav?rlkey=k1&raw=1", f"a Dropbox audio share page -> the file {vv}")
    # not an audio file: no time control (as before for any other link); the name only in the query does not count
    for url in ("https://a.example.com/song.txt", "https://a.example.com/play?f=song.mp3", "https://a.example.com/mp3", "https://a.example.com/x.mp3/"):
        r = A.post(B + f"{V}/{RID}/versions", json={"url": url})
        vv = r.json()["versions"][-1] if r.ok else {}
        check(r.ok and vv.get("provider") == "link" and vv.get("embed") is None and not vv.get("timed"), f"{url} -> no audio, a link without time {vv}")
    # not https: refused
    for bad in ("http://a.example.com/x.mp3", "ftp://a.example.com/x.mp3", "data:audio/mpeg;base64,AAAA", "javascript:alert(1)//x.mp3",
                "https://user:pw@a.example.com/x.mp3"):
        check(A.post(B + f"{V}/{RID}/versions", json={"url": bad}).status_code == 400, f"refused: {bad}")
    # the agents' API names the provider audio as well
    ag = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "helper", "display_name": "Helper"}).json()
    check(bool(ag.get("token")), "setup: an agent")
    if ag.get("token"):
        A.put(B + f"/api/lists/{LST}/members", json={"user_id": ag["id"], "role": "view"})
        r = requests.get(B + f"/api/v1/videos/{RID}", headers={"Authorization": "Bearer " + ag["token"]})
        check(r.ok and r.json().get("versions", [{}])[0].get("provider") == "audio", f"API v1: provider audio ({r.status_code} {r.text[:160]})")

print(f"p2633_d_audiorev: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
