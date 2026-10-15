#!/usr/bin/env python3
"""2.45.1 API tests (part A), own container (start.sh).

 - #1555: a vCard file with a 'ß' (or another letter whose capital is longer, 'ﬁ', or whose small letter is longer, 'İ')
   before the first card and inside many cards is split into every card (the cards were cut at positions found in an
   upper-case copy of the text: from the first ß on almost every card failed with "Exactly one contact per resource")
 - #1555: vCard 2.1 values in QUOTED-PRINTABLE (with CHARSET, soft line breaks) are decoded
"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def names(bid):
    r = A.get(B + f"/api/contacts?book_id={bid}&limit=2000")
    assert r.ok, r.text
    return sorted(x["fn"] for x in r.json()["items"])


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["contacts"]})
A.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== #1555: ß and other letters that change length
fam = ["Grüßmann", "Strauß", "Weiß", "Muster", "Großfeld"]
cards = []
for i in range(20):
    f = fam[i % len(fam)]
    extra = "NOTE:Straße ﬁnal İstanbul ß ß ß" if i % 2 else "NOTE:fictional"
    cards.append("\r\n".join(["BEGIN:VCARD", "VERSION:3.0", f"UID:ss-{i}", f"FN:Anna {f} {i}", f"N:{f} {i};Anna;;;",
                              f"ADR;TYPE=HOME:;;Fußweg {i};Gießen;;35390;Germany", extra, "END:VCARD"]))
text = "X-NOTE: Grüße aus der Straße ﬁ İ\r\n" + "\r\n".join(cards) + "\r\n"
BK = A.post(B + "/api/books", json={"name": "Eszett"}).json()["id"]
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("ss.vcf", text.encode("utf-8"), "text/vcard")})
check(r.ok and r.json().get("created") == 20 and r.json().get("errors") == 0,
      f"#1555: a file with ß / ﬁ / İ imports all 20 cards {r.status_code} {r.text[:200]}")
want = sorted(f"Anna {fam[i % len(fam)]} {i}" for i in range(20))
check(names(BK) == want, f"#1555: every name arrives unchanged {names(BK)[:5]}")
# lower-case markers and LF only
text2 = "\n".join(c.replace("BEGIN:VCARD", "begin:vcard").replace("END:VCARD", "End:VCard").replace("\r\n", "\n") for c in cards)
BK2 = A.post(B + "/api/books", json={"name": "Eszett LF"}).json()["id"]
r = A.post(B + f"/api/books/{BK2}/import", files={"file": ("ss2.vcf", text2.encode("utf-8"), "text/vcard")})
check(r.ok and r.json().get("created") == 20 and r.json().get("errors") == 0,
      f"#1555: lower-case BEGIN / END and LF line ends too {r.status_code} {r.text[:200]}")
# importing the same file again changes nothing
r = A.post(B + f"/api/books/{BK}/import", files={"file": ("ss.vcf", text.encode("utf-8"), "text/vcard")})
check(r.ok and r.json().get("created") == 0 and r.json().get("updated") == 20, f"#1555: importing twice makes no doubles {r.text[:200]}")
# the background path (more than 100 cards) splits the same way
big = "Grüße\r\n" + "\r\n".join(c.replace(f"UID:ss-", "UID:big-").replace("FN:Anna", f"FN:Bea {k}")
                                for k in range(6) for c in cards) + "\r\n"
BK3 = A.post(B + "/api/books", json={"name": "Eszett big"}).json()["id"]
r = A.post(B + f"/api/books/{BK3}/import?background=1", files={"file": ("big.vcf", big.encode("utf-8"), "text/vcard")})
check(r.status_code == 202 and r.json().get("total") == 120, f"#1555: 120 cards with ß -> background import of 120 {r.status_code} {r.text[:200]}")
iid, st = r.json().get("import_id", "x"), {}
for _ in range(120):
    st = A.get(B + f"/api/books/imports/{iid}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.5)
check(st.get("state") == "done" and st.get("errors") == 0, f"#1555: the background import ends without errors {st}")

# ================================================================== #1555: vCard 2.1 QUOTED-PRINTABLE
qp = "\r\n".join([
    "BEGIN:VCARD", "VERSION:2.1",
    "N;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:M=C3=BCller;J=C3=BCrgen;;;",
    "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:J=C3=BCrgen M=C3=",
    "=BCller-Gro=C3=9Fmann",
    "TEL;HOME;VOICE:+49 30 123456",
    "ORG;QUOTED-PRINTABLE;CHARSET=ISO-8859-1:B=E4ckerei Wei=DF",
    "NOTE;ENCODING=QUOTED-PRINTABLE:Zeile eins=0D=0AZeile zwei",
    "END:VCARD",
    "BEGIN:VCARD", "VERSION:2.1", "N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=C3=96zt=C3=BCrk;Ay=C5=9Fe;;;",
    "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Ay=C5=9Fe =C3=96zt=C3=BCrk", "END:VCARD", ""])
BQ = A.post(B + "/api/books", json={"name": "QP"}).json()["id"]
r = A.post(B + f"/api/books/{BQ}/import", files={"file": ("qp.vcf", qp.encode("ascii"), "text/vcard")})
check(r.ok and r.json().get("created") == 2 and r.json().get("errors") == 0, f"#1555: vCard 2.1 QP file imports {r.status_code} {r.text[:200]}")
check(names(BQ) == ["Ayşe Öztürk", "Jürgen Müller-Großmann"], f"#1555: QP names are decoded (soft line break too) {names(BQ)}")
it = [x for x in A.get(B + f"/api/contacts?book_id={BQ}").json()["items"] if x["fn"].startswith("Jürgen")]
c1 = A.get(B + f"/api/contacts/{it[0]['id']}").json() if it else {}
check(c1.get("family") == "Müller" and c1.get("given") == "Jürgen", f"#1555: N in QP is decoded {c1.get('family')!r} {c1.get('given')!r}")
check(c1.get("org") == "Bäckerei Weiß", f"#1555: CHARSET=ISO-8859-1 is respected {c1.get('org')!r}")
check(c1.get("note") == "Zeile eins\nZeile zwei", f"#1555: a QP line break becomes a line break {c1.get('note')!r}")
check([p.get("type") for p in c1.get("phones", [])] == [["home"]], f"#1555: the bare 2.1 types stay {c1.get('phones')}")

print(f"p2451_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
