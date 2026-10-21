#!/usr/bin/env python3
"""2.98.0 API tests, part B (#1954): questionnaires -- own questions in the forms, the answers become a task at the customer.
Own container (start.sh, with KALMIDO_SECRET_KEY: files sealed), invented companies and people only (@example.com).
 - the settings: every kind of question (short, long, choice, multi, date, number, file, yesno), ids kept on a new order,
   refused: an unknown kind, a choice with one option, four file questions, 31 questions, an empty text, a non-boolean
 - the page: a questionnaire shows its questions instead of subject / description (required attributes on one page; the
   step mode: a section per question + the last one, Back / Next links, progress, novalidate), no scripts
 - sending: a missing required answer / a wrong choice / a bad number / a bad date / a wrong file type / a file too large
   = the page again with the typed answers (the step of the problem opens), nothing created; a full send = a task in the
   list with the answers as Markdown (a heading per question, choices as a list), both files as attachments sealed on disk
 - the client: matched by e-mail only in the list's space (another organisation's client with the same address is never
   taken; a private list matches the owner's private clients only), unknown = a note, client_new = a new client there
 - the evaluation: entries + CSV (a column per question, formulas defused) for the people who manage the form; another
   member 403, another organisation 404, without login refused; a task in the trash leaves the list
 - the classic form without questions works exactly as before (subject field, the task's title = the subject, no entry)
 - the list moves into the organisation: its form keeps the questions, a private client is no longer named
 - a person without an organisation (freelancer-matrix: lists): a private questionnaire, its entries and CSV
 - tenant-matrix: form (the submissions of a form of another organisation: 404)
usage: p298_b_api_test.py <datadir>      (a fresh container; P298B_NOSTART=1 = the server already runs)"""
import base64
import csv
import io
import json
import os
import re
import struct
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
KEY = base64.b64encode(os.urandom(32)).decode()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def png(w=4, h=4):
    raw = b"".join(b"\x00" + b"\x10\x80\xf0" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def stamp_of(text):
    m = re.search(r'name="stamp" value="([^"]+)"', text)
    return m.group(1) if m else ""


def tok(f):
    return f["url"].rsplit("/", 1)[1]


def entry_of(fid, email=None):
    rows = dbx("SELECT task_id, client_id, sender, email, answers FROM form_entries WHERE form_id=? ORDER BY task_id", (fid,))
    return [r for r in rows if email is None or r[3] == email]


def task(tid):
    r = dbx("SELECT title, content, list_id FROM tasks WHERE id=?", (tid,))
    return r[0] if r else ("", "", None)


SENDS = [0]


def send(t, data, files=None, s=None):
    """A send; at most 6 per address and minute (FORM_SEND_RATE): every sixth waits for the next minute."""
    if SENDS[0] and SENDS[0] % 6 == 0:
        time.sleep(61)
    SENDS[0] += 1
    return (s or requests).post(B + "/f/" + t, data=data, files=files, headers=H)


if not os.environ.get("P298B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,agents,clients,workload,forms,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/admin/settings", json={"public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
ORG2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other Example','','2026-10-01T00:00:00Z') RETURNING id")[0][0]
dbx("DELETE FROM org_members WHERE user_id=?", (CAROL,))
dbx("INSERT INTO org_members(org_id,user_id) VALUES(?,?)", (ORG2, CAROL))
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
FL = A.post(B + "/api/lists", json={"name": "Requests", "org_id": ORG}).json()["id"]
PL = A.post(B + "/api/lists", json={"name": "Private requests", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
r = A.post(B + "/api/clients", json={"name": "Acme Example", "email": "buyer@example.com", "org_id": ORG})
ACME = r.json().get("id")
check(r.status_code == 201 and ACME, "a client of the organisation " + r.text[:200])
r = Ca.post(B + "/api/clients", json={"name": "Foreign Example", "email": "buyer@example.com"})
FOREIGN = r.json().get("id")
check(r.status_code == 201 and dbx("SELECT org_id FROM clients WHERE id=?", (FOREIGN,))[0][0] == ORG2, "the same address at a client of another organisation")
r = A.post(B + "/api/clients", json={"name": "Solo Example", "email": "solo@example.com", "org_id": None})
SOLO = r.json().get("id")
check(r.status_code == 201 and dbx("SELECT org_id FROM clients WHERE id=?", (SOLO,))[0][0] is None, "a private client of Alice " + r.text[:200])

# ================================================================== the settings
QS = [{"kind": "short", "label": "Company name", "required": True, "help": "As on your invoices"},
      {"kind": "long", "label": "What do you need?"},
      {"kind": "choice", "label": "Budget", "options": ["Small", "Medium", "Large", "Medium", " "], "required": True},
      {"kind": "multi", "label": "Services", "options": ["Design", "Code", "Hosting"]},
      {"kind": "date", "label": "Start"},
      {"kind": "number", "label": "Team size"},
      {"kind": "file", "label": "Brief"},
      {"kind": "file", "label": "Logo"},
      {"kind": "yesno", "label": "Newsletter?", "required": True}]
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Questionnaire", "access": "public", "questions": QS, "client_match": True})
FQ = r.json()
q = FQ.get("questions") or []
check(r.status_code == 201 and [x["kind"] for x in q] == [x["kind"] for x in QS] and all(re.fullmatch(r"[a-z0-9]{6,16}", x["id"]) for x in q)
      and q[2]["options"] == ["Small", "Medium", "Large"] and q[0]["required"] is True and q[1]["required"] is False
      and FQ["one_per_step"] is False and FQ["client_match"] is True and FQ["client_new"] is False,
      "a questionnaire with every kind; options cleaned (no doubles, no empty ones) " + r.text[:400])
QID = {x["label"]: x["id"] for x in q}
bad = [({"questions": [{"kind": "slider", "label": "x"}]}, "an unknown kind"),
       ({"questions": [{"kind": "choice", "label": "x", "options": ["only"]}]}, "a choice with one option"),
       ({"questions": [{"kind": "file", "label": f"f{i}"} for i in range(4)]}, "four file questions"),
       ({"questions": [{"kind": "short", "label": f"q{i}"} for i in range(31)]}, "31 questions"),
       ({"questions": [{"kind": "short", "label": "  "}]}, "a question without text"),
       ({"questions": [{"kind": "short", "label": "x", "required": "yes"}]}, "required: a boolean"),
       ({"questions": "short"}, "questions: a list"),
       ({"one_per_step": "yes"}, "one_per_step: a boolean"), ({"client_new": 1}, "client_new: a boolean")]
for b, what in bad:
    check(A.patch(B + f"/api/forms/{FQ['id']}", json=b).status_code == 400, "refused: " + what)
rev = list(reversed(q))
r = A.patch(B + f"/api/forms/{FQ['id']}", json={"questions": rev})
check(r.ok and [x["id"] for x in r.json()["questions"]] == [x["id"] for x in rev], "a new order keeps the ids")
r = A.patch(B + f"/api/forms/{FQ['id']}", json={"questions": q})
check(r.ok and [x["id"] for x in r.json()["questions"]] == [x["id"] for x in q], "and back")
check(Bo.patch(B + f"/api/forms/{FQ['id']}", json={"questions": []}).status_code == 403, "a member who does not manage the list: 403")
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Steps", "access": "public", "one_per_step": True,
                                               "questions": [{"kind": "short", "label": "Your city", "required": True},
                                                             {"kind": "yesno", "label": "Agree?", "required": True},
                                                             {"kind": "short", "label": "Note"}]})
FS = r.json()
check(r.status_code == 201 and FS["one_per_step"] is True and len(FS["questions"]) == 3, "a questionnaire in steps")
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Classic", "access": "public"})
FC = r.json()
check(r.status_code == 201 and FC["questions"] == [] and FC["one_per_step"] is False and FC["client_match"] is False,
      "a classic form: no questions, the switches off")
SQ = {x["label"]: x["id"] for x in FS["questions"]}

# ================================================================== the page
anon = requests.Session()
anon.headers.update(H)
p = anon.get(B + "/f/" + tok(FQ))
t = p.text
check(p.ok and 'name="subject"' not in t and 'name="text"' not in t and "<script" not in t and 'enctype="multipart/form-data"' in t,
      "the questionnaire: no subject / description, multipart, no scripts")
check(re.search(rf'name="q_{QID["Company name"]}"[^>]*required', t) and f'name="q_{QID["What do you need?"]}"' in t and "As on your invoices" in t
      and t.count(f'type="radio" name="q_{QID["Budget"]}"') == 3 and t.count(f'type="checkbox" name="q_{QID["Services"]}"') == 3
      and re.search(rf'name="q_{QID["Start"]}" type="date"', t) and re.search(rf'name="q_{QID["Team size"]}" inputmode="decimal"', t)
      and re.search(rf'name="q_{QID["Brief"]}" type="file" accept="[^"]*\.pdf', t)
      and ".svg" not in re.search(r'type="file" accept="([^"]*)"', t).group(1)
      and t.count(f'name="q_{QID["Newsletter?"]}"') == 2 and "fq-steps" not in t,
      "every kind on one page: text, long text, radios, checkboxes, date, number, file (accept list), yes / no; required marked")
p = anon.get(B + "/f/" + tok(FS))
t = p.text
check(p.ok and "fq-steps" in t and " novalidate" in t and t.count('class="fqs') == 4 and 'class="fqs cur" id="fqs-1"' in t
      and 'href="#fqs-2"' in t and 'href="#fqs-1"' in t and "<progress" in t and "Step 1 of 4" in t
      and not re.search(rf'name="q_{SQ["Your city"]}"[^>]*required', t) and "<script" not in t,
      "the step mode: a section per question + the last, Back / Next, progress, no required attributes (hidden steps)")
p = anon.get(B + "/f/" + tok(FC))
check(p.ok and 'name="subject"' in p.text and 'name="text"' in p.text and "fq-" not in p.text, "the classic form's page as before")
time.sleep(0.2)
stq = [stamp_of(anon.get(B + "/f/" + tok(FQ)).text) for _ in range(10)]
sts = [stamp_of(anon.get(B + "/f/" + tok(FS)).text) for _ in range(3)]
stc = [stamp_of(anon.get(B + "/f/" + tok(FC)).text) for _ in range(2)]
time.sleep(3.3)


def full(st, **kw):
    d = {f"q_{QID['Company name']}": "=SUM(A1)", f"q_{QID['What do you need?']}": "A new website.\nWith a shop.",
         f"q_{QID['Budget']}": "Medium", f"q_{QID['Start']}": "2026-11-02", f"q_{QID['Team size']}": "4,5",
         f"q_{QID['Newsletter?']}": "yes", "name": "Eve", "email": "buyer@example.com", "stamp": st}
    d.update(kw)
    return d


# ================================================================== refused sends: the page again, nothing created
n0 = dbx("SELECT COUNT(*) FROM tasks")[0][0]
p = send(tok(FS), {f"q_{SQ['Your city']}": "Example Town", "stamp": sts.pop()}, s=anon)
check(p.status_code == 400 and "Please answer “Agree?”." in p.text and 'class="fqs cur" id="fqs-2"' in p.text and 'value="Example Town"' in p.text,
      "steps: a missing required answer opens its step, the typed answers stay " + p.text[-500:])
d = full(stq.pop())
d.pop(f"q_{QID['Company name']}")
p = send(tok(FQ), d, s=anon)
check(p.status_code == 400 and "Please answer “Company name”." in p.text and "A new website." in p.text and 'value="Medium" checked' in p.text,
      "one page: a missing required answer, the answers kept (text, choice)")
p = send(tok(FQ), full(stq.pop(), **{f"q_{QID['Services']}": ["Design", "Mining"]}), s=anon)
check(p.status_code == 400 and "Please check your answer to “Services”." in p.text, "a multiple choice outside the options")
p = send(tok(FQ), full(stq.pop()), files={f"q_{QID['Brief']}": ("page.html", b"<html><script>x</script></html>", "text/html")}, s=anon)
check(p.status_code == 400 and "this file type is not accepted" in p.text, "a web page as a file: refused")
p = send(tok(FQ), full(stq.pop()), files={f"q_{QID['Brief']}": ("big.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf")}, s=anon)
check(p.status_code in (400, 413) and "too large" in p.text, "a file over 10 MB: refused " + str(p.status_code) + " " + p.text[-400:])
p = send(tok(FQ), full(stq.pop(), **{f"q_{QID['Team size']}": "a few"}), s=anon)
check(p.status_code == 400 and "please enter a number" in p.text, "a number that is none")
p = send(tok(FQ), full(stq.pop(), **{f"q_{QID['Start']}": "2026-13-40"}), s=anon)
check(p.status_code == 400 and "please enter a date" in p.text, "a date that is none")
p = send(tok(FQ), full(stq.pop(), **{f"q_{QID['Budget']}": "Huge"}), s=anon)
check(p.status_code == 400 and "Please check your answer to “Budget”." in p.text, "a choice outside the options")
check(dbx("SELECT COUNT(*) FROM tasks")[0][0] == n0 and not entry_of(FQ["id"]), "nothing created by the refused sends")

# ================================================================== a full send
p = send(tok(FQ), full(stq.pop(), **{f"q_{QID['Services']}": ["Hosting", "Design"]}),
         files={f"q_{QID['Brief']}": ("brief.pdf", PDF, "application/octet-stream"), f"q_{QID['Logo']}": ("logo.png", png(), "text/html")}, s=anon)
check(p.ok and "Your request has been sent." in p.text, "sent " + p.text[-300:])
en = entry_of(FQ["id"])
T = en[0][0] if en else 0
title, content, lid = task(T)
check(en and lid == FL and title == "Questionnaire – Eve", "a task in the form's list, titled with the form and the sender " + str((title, lid)))
check("### Company name\n=SUM(A1)" in content and "### What do you need?\nA new website.\nWith a shop." in content
      and "### Budget\n- Medium" in content and "### Services\n- Design\n- Hosting" in content and "### Start\n2026-11-02" in content
      and "### Team size\n4.5" in content and "### Brief\nbrief.pdf (attachment)" in content and "### Newsletter?\nYes" in content
      and "Sent with the form “Questionnaire” by Eve <buyer@example.com>" in content,
      "the answers as Markdown: a heading per question, choices as a list, the number normalised, the files named " + content[:900])
check("Client: Acme Example" in content and en and en[0][1] == ACME, "the client of the list's organisation (never the other organisation's with the same address)")
ans = json.loads(en[0][4]) if en else {}
check(ans.get(QID["Services"]) == ["Design", "Hosting"] and ans.get(QID["Newsletter?"]) == "yes" and QID["What do you need?"] in ans
      and en[0][2] == "Eve" and en[0][3] == "buyer@example.com", "the entry: answers by question id, the sender " + str(en[:1])[:300])
att = dbx("SELECT id, name, mime, path FROM attachments WHERE task_id=? ORDER BY name", (T,))
check([a[1] for a in att] == ["brief.pdf", "logo.png"] and att[1][2] == "image/png", "both files as attachments, the type from the content " + str(att))
for a in att:
    with open(os.path.join(DATA, "attachments", a[3]), "rb") as fh:
        check(fh.read(6) == b"KENC1\n", f"{a[1]}: sealed on disk")
if att:
    check(A.get(B + f"/api/attachments/{att[1][0]}").content == png(), "the list's owner reads the file")
    check(Ca.get(B + f"/api/attachments/{att[1][0]}").status_code in (403, 404), "another organisation: no file")
check(dbx("SELECT count FROM forms WHERE id=?", (FQ["id"],))[0][0] == 1, "the form counts the send")

# ================================================================== the classic form, unchanged
p = send(tok(FC), {"subject": "Printer broken", "text": "Second floor.", "name": "Dan", "email": "dan@example.com", "stamp": stc.pop()}, s=anon)
r = dbx("SELECT id, content FROM tasks WHERE title='Printer broken'")
check(p.ok and r and r[0][1].startswith("Second floor.") and "###" not in r[0][1] and not entry_of(FC["id"]), "the classic form: the task as before, no entry")
# 2.148.1 G (#2496): the sender's name stays plain text in the task's Markdown (F: the escaped ] already breaks the link, ( ) stay)
p = send(tok(FC), {"subject": "Printer two", "text": "Ground floor.", "name": "[Confirm](https://x.example.com)", "email": "dan2@example.com",
                   "stamp": stc.pop()}, s=anon)
r = dbx("SELECT content FROM tasks WHERE title='Printer two'")
check(p.ok and r and "\\[Confirm\\](https://x.example.com)" in r[0][0] and "[Confirm](" not in r[0][0] and "<dan2@example.com>" in r[0][0],
      "the sender's name as plain text " + (r[0][0][-200:] if r else p.text[-200:]))

# ================================================================== the client: only the list's space
p = send(tok(FQ), full(stq.pop(), email="new@example.com", name="Nina"), s=anon)
en = entry_of(FQ["id"], "new@example.com")
check(p.ok and en and en[0][1] is None and "Client unknown: new@example.com" in task(en[0][0])[1]
      and not dbx("SELECT 1 FROM clients WHERE email='new@example.com'"), "unknown address: a note, no new client (switch off)")
check(A.patch(B + f"/api/forms/{FQ['id']}", json={"client_new": True}).json()["client_new"] is True, "the switch for new clients")
p = send(tok(FQ), full(stq.pop(), email="fresh@example.com", name="Finn"), s=anon)
en = entry_of(FQ["id"], "fresh@example.com")
nc = dbx("SELECT id, org_id, name, created_by FROM clients WHERE email='fresh@example.com'")
check(p.ok and en and nc and en[0][1] == nc[0][0] and nc[0][1] == ORG and nc[0][2] == "Finn" and nc[0][3] == 1
      and "New client created: Finn <fresh@example.com>" in task(en[0][0])[1], "client_new: a new client in the list's organisation " + str(nc))
r = A.post(B + f"/api/lists/{PL}/forms", json={"title": "Private questionnaire", "access": "public", "client_match": True,
                                               "questions": [{"kind": "short", "label": "Topic", "required": True}]})
FP = r.json()
check(r.status_code == 201, "a questionnaire of a private list")
stp = [stamp_of(anon.get(B + "/f/" + tok(FP)).text) for _ in range(2)]
time.sleep(3.3)
PQ = FP["questions"][0]["id"]
p = send(tok(FP), {f"q_{PQ}": "Tax", "name": "Sol", "email": "solo@example.com", "stamp": stp.pop()}, s=anon)
en = entry_of(FP["id"], "solo@example.com")
check(p.ok and en and en[0][1] == SOLO and "Client: Solo Example" in task(en[0][0])[1], "a private list: the owner's private client")
p = send(tok(FP), {f"q_{PQ}": "Shop", "name": "Bea", "email": "buyer@example.com", "stamp": stp.pop()}, s=anon)
en = entry_of(FP["id"], "buyer@example.com")
check(p.ok and en and en[0][1] is None and "Client unknown" in task(en[0][0])[1], "a private list never takes an organisation's client")
# a signed-in member of the organisation: no e-mail field, the entry names the person
p = send(tok(FQ), {f"q_{QID['Company name']}": "Inside", f"q_{QID['Budget']}": "Small", f"q_{QID['Newsletter?']}": "no"}, s=Bo)
en = [e for e in entry_of(FQ["id"]) if e[2] == "Bob"]
check(p.ok and en and en[0][3] == "" and task(en[0][0])[0] == "Questionnaire – Bob", "signed in: the person's name, no address")

# ================================================================== the evaluation
r = A.get(B + f"/api/forms/{FQ['id']}/entries")
j = r.json() if r.ok else {}
es = j.get("entries") or []
check(r.ok and len(es) == 4 and [x["id"] for x in j["questions"]] == [x["id"] for x in q] and es[-1]["task_id"] == T
      and es[-1]["client"] == {"id": ACME, "name": "Acme Example"} and es[-1]["answers"][QID["Budget"]] == "Medium",
      "the entries: newest first, the answers, the client " + r.text[:400])
r = A.get(B + f"/api/forms/{FQ['id']}/entries.csv")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")))) if r.ok else []
hdr = rows[0] if rows else []
eve = next((x for x in rows[1:] if "Eve" in x), [])
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "attachment" in r.headers.get("Content-Disposition", "")
      and hdr[:6] == ["Date", "Task", "Name", "E-mail", "Client", "Done"] and hdr[6:] == [x["label"] for x in QS] and len(rows) == 5,
      "the CSV: a row per entry, a column per question " + str(rows[:2])[:400])
check(eve and eve[6] == "'=SUM(A1)" and eve[9] == "Design; Hosting" and eve[14] == "Yes" and eve[4] == "Acme Example" and eve[12] == "brief.pdf",
      "the CSV: formulas defused, several choices joined, yes / no in words " + str(eve))
for who, s, codes in (("a member who does not manage the list", Bo, (403,)), ("another organisation", Ca, (404,)), ("without login", anon, (401, 403, 404))):
    check(s.get(B + f"/api/forms/{FQ['id']}/entries").status_code in codes and s.get(B + f"/api/forms/{FQ['id']}/entries.csv").status_code in codes,
          f"entries / CSV: {who} refused")
check(A.delete(B + f"/api/tasks/{T}").ok, "the first submission into the trash")
check(T not in [x["task_id"] for x in A.get(B + f"/api/forms/{FQ['id']}/entries").json()["entries"]], "a task in the trash leaves the evaluation")

# ================================================================== the private list moves into the organisation
r = A.patch(B + f"/api/lists/{PL}", json={"org_id": ORG})
check(r.ok, "the private list moves into the organisation " + r.text[:200])
fp = [f for f in A.get(B + f"/api/lists/{PL}/forms").json()["forms"] if f["id"] == FP["id"]]
check(fp and fp[0]["questions"] == FP["questions"] and fp[0]["client_match"] is True, "its form keeps the questions")
es = A.get(B + f"/api/forms/{FP['id']}/entries").json()["entries"]
check(es and all(e["client"] is None for e in es), "the private client is no longer named in the organisation")

# ================================================================== a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
FRL = Fr.post(B + "/api/lists", json={"name": "Freelance requests"}).json()["id"]
r = Fr.post(B + f"/api/lists/{FRL}/forms", json={"title": "Brief", "access": "public", "questions": [{"kind": "long", "label": "Your idea", "required": True}]})
FF = r.json()
check(r.status_code == 201, "the freelancer's questionnaire " + r.text[:200])
st = stamp_of(anon.get(B + "/f/" + tok(FF)).text)
time.sleep(3.3)
p = send(tok(FF), {f"q_{FF['questions'][0]['id']}": "A logo", "name": "Ivy", "email": "ivy@example.com", "stamp": st}, s=anon)
r = Fr.get(B + f"/api/forms/{FF['id']}/entries")
check(p.ok and r.ok and len(r.json()["entries"]) == 1 and Fr.get(B + f"/api/forms/{FF['id']}/entries.csv").ok, "the freelancer's entries and CSV")
check(A.get(B + f"/api/forms/{FF['id']}/entries").status_code in (403, 404) and Ca.get(B + f"/api/forms/{FF['id']}/entries").status_code == 404,
      "the freelancer's entries: nobody else")

print(f"p298_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
