#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.581.0 part D (#4804): documents from the own mailbox of a workspace -- the mail rules (hub/mailrules.py). Own container
(start.sh + tests/stub_imap_folders.py: an IMAP server with folders, flags, MOVE, UID EXPUNGE). Invented names, addresses
(@example.com / example.org) and files only.
 - the rules (GET / POST / PUT / DELETE /api/hubmail/mailbox/rules): only who may set up the mailbox (an admin of the
   organisation, a person for the own private space); a member 403, another organisation 404, agents refused; bad values
   400 (after, move without a folder, nothing to take, an unknown field, a target folder of another workspace); a stale
   expect_updated_at 409 with the current rule (tenant-matrix: hubmail)
 - the run (POST .../rules/fetch, the mailbox round): a rule that fits -> the PDF attachment becomes a document of the
   mailbox's workspace with source 'mailbox' (+ the mail itself as .eml when asked), the mail moved / marked seen / flagged;
   sender, subject, "has an attachment" and the age decide; a second run takes nothing twice (each Message-ID once per
   mailbox); without the delete switch no mail is ever marked deleted or expunged, with it exactly that mail goes
 - a person without an organisation: her private mailbox and a rule into her own folder (freelancer-matrix: hub)
 - 2.636.0 (#4853): a mail whose documents are all refused (the target folder in the trash) is not remembered, the rule shows
   the error; a target folder the holder cannot file into is refused on saving; the next run (folder back) takes the mail
usage: p2581_d_mailrules_test.py <datadir>"""
import email.message
import email.utils
import json
import os
import shutil
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, dbx, docker_logs_on_first_fail, done, fresh, sess, setup, until  # noqa: E402

ENV = {"KALMIDO_IMAP_INTERVAL": "600", "KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1:1145",
       "KALMIDO_SECRET_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="}
FEAT = "cal,collab,comments,events,contacts,clients,files,docs"
MB = os.path.join(DATA, "mbr")


def pdf(text):
    """A tiny one-page PDF (hand-written)."""
    stream = f"BT /F1 12 Tf 60 740 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


NEXT = [0]


def drop(folder, frm, subject, att=None, days_old=0):
    """One mail into a folder of the stub; -> its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "office@example.com", subject
    m["Message-ID"] = f"<p2581d-{NEXT[0]}@example.org>"
    m["Date"] = email.utils.formatdate(time.time() - days_old * 86400, localtime=False)
    m.set_content(f"Mail {NEXT[0]}: {subject}")
    if att:
        m.add_attachment(pdf(att), maintype="application", subtype="pdf", filename=f"{att}.pdf")
    os.makedirs(os.path.join(MB, folder), exist_ok=True)
    have = [int(x[:-4]) for x in os.listdir(os.path.join(MB, folder)) if x.endswith(".eml")]
    open(os.path.join(MB, folder, f"{max(have, default=0) + 1}.eml"), "wb").write(bytes(m))
    return m["Message-ID"]


def flags():
    try:
        return json.load(open(os.path.join(MB, "flags.json")))
    except (FileNotFoundError, ValueError):
        return {}


def files(folder):
    p = os.path.join(MB, folder)
    return sorted(x for x in os.listdir(p) if x.endswith(".eml")) if os.path.isdir(p) else []


def imap_log():
    try:
        return open(os.path.join(MB, "imap.log")).read()
    except FileNotFoundError:
        return ""


def docs(ws):
    return dbx("SELECT d.node_id, n.name, d.source, n.parent_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.ws=? ORDER BY d.node_id", (ws,))


def run(s, ws):
    """Fetch now and wait for that run to be over: the route sets docs_due (committed before it answers), the run sets it back
    to 0 and stores docs_polled_at (whole seconds: two runs in one second keep the same value, so the flag is the signal)."""
    r = s.post(B + "/api/hubmail/mailbox/rules/fetch", json={"ws": "private" if ws.startswith("u") else f"org:{ws[1:]}"})
    check(r.ok, f"fetch now {ws}: {r.status_code} {r.text[:200]}")
    return r.ok and until(lambda: (lambda x: x and x[0][1] and not x[0][0])(dbx("SELECT docs_due, docs_polled_at FROM hub_mailboxes WHERE ws=?", (ws,))), 60)


docker_logs_on_first_fail()
# ---- setup: alice (instance admin), Alpha = bob (admin) + carol, Beta = dave, erin without an organisation
fresh(ENV)
for d in ("INBOX", "Rechnungen", "Archiv", "Belege", "Markiert", "Weg", "Erin", "Ziel"):  # 2.636.0 (#4853): + Ziel
    os.makedirs(os.path.join(MB, d), exist_ok=True)
shutil.copy(os.path.join(N, "stub_imap_folders.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_imap_folders.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1145), 1)"],
                             capture_output=True).returncode == 0, 20)
A = setup()
U = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    U[u] = r.json()["id"]
BOB, CAROL, DAVE = U["bob"], U["carol"], U["dave"]
ERIN, Er = freelancer(B, A, "erin")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE}).json()["id"]
A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [BOB, CAROL], "admins": [BOB]})
A.patch(B + f"/api/admin/orgs/{ORG2}", json={"members": [DAVE], "admins": [DAVE]})
r = A.post(B + "/api/admin/agents", json={"username": "bobbot", "display_name": "Bobbot"})
AG = sess(headers={"Authorization": "Bearer " + (r.json().get("token") or "")})
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
WS, WSE = f"o{ORG}", f"u{ERIN}"
tabs = {x[0] for x in dbx("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name LIKE 'hub_mailbox_%'")}
check({"hub_mailbox_rules", "hub_mailbox_docs"} <= tabs, f"the new tables ({tabs})")

BOX = {"imap_host": "127.0.0.1", "imap_port": 1145, "imap_ssl": False, "imap_user": "kalmido", "imap_password": "secret", "imap_folder": "INBOX"}
r = Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": f"org:{ORG}", "check": True})
check(r.ok and (r.json().get("check") or {}).get("imap", {}).get("ok"), f"Alpha's mailbox set up and logged in ({r.status_code} {r.text[:300]})")

# ---- the rules: rights and values (tenant-matrix: hubmail)
RULE = {"ws": f"org:{ORG}", "name": "Shop invoices", "folder": "Rechnungen", "from_has": "billing@shop.example.com", "need_att": True,
        "max_age": 30, "tags": ["Invoice", "Shop"], "after": "move", "after_folder": "Archiv"}
check(Ca.post(B + "/api/hubmail/mailbox/rules", json=RULE).status_code == 403, "a member of Alpha (no admin): 403")
check(Da.post(B + "/api/hubmail/mailbox/rules", json=RULE).status_code == 404, "an admin of another organisation: 404")
check(Da.get(B + f"/api/hubmail/mailbox/rules?ws=org:{ORG}").status_code == 404, "another organisation cannot read the rules: 404")
check(AG.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "ws": "private"}).status_code in (401, 403), "agents: no rules")
check(Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "after": "burn"}).status_code == 400, "an unknown action afterwards: 400")
check(Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "after_folder": ""}).status_code == 400, "move without a folder: 400")
check(Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "take_files": False, "take_mail": False}).status_code == 400, "nothing becomes a document: 400")
check(Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "evil": 1}).status_code == 400, "an unknown field: 400")
check(Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "folder": 'a"b'}).status_code == 400, "a folder name with a quote: 400")
BETA_F = Da.post(B + "/api/files/folders", json={"name": "Beta docs", "space": f"org:{ORG2}"}).json().get("id")
check(BETA_F and Bo.post(B + "/api/hubmail/mailbox/rules", json={**RULE, "target_id": BETA_F}).status_code == 400, "a target folder of another organisation: 400")
r = Bo.post(B + "/api/hubmail/mailbox/rules", json=RULE)
check(r.status_code == 201, f"Alpha's first rule ({r.status_code} {r.text[:200]})")
RA = r.json().get("rule") or {}
RB = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Receipts", "folder": "Belege", "subject_has": "receipt", "need_att": True,
                          "take_mail": True, "after": "seen"}).json().get("rule") or {}
RC = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Flagged", "folder": "Markiert", "need_att": True, "after": "flag"}).json().get("rule") or {}
check(RB.get("id") and RC.get("id"), "two more rules")
r = Ca.put(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}", json={"name": "x"})
check(r.status_code == 403, f"a member cannot change a rule: {r.status_code}")
check(Da.put(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}", json={"name": "x"}).status_code == 404, "another organisation cannot change it: 404")
check(Da.delete(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}").status_code == 404, "another organisation cannot delete it: 404")
check(Er.delete(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}").status_code == 404, "a person without an organisation cannot delete it: 404")
r = Bo.put(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}", json={"name": "Shop invoices", "expect_updated_at": "2000-01-01T00:00:00+00:00"})
check(r.status_code == 409 and (r.json().get("rule") or {}).get("id") == RA.get("id"), f"a stale version: 409 with the current rule ({r.status_code})")
r = Bo.put(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}", json={"name": "Shop invoices (PDF)", "expect_updated_at": RA.get("updated_at")})
check(r.ok and r.json()["rule"]["name"] == "Shop invoices (PDF)", f"a change with the right version ({r.status_code} {r.text[:200]})")
j = Bo.get(B + f"/api/hubmail/mailbox/rules?ws=org:{ORG}").json()
check([x["id"] for x in j.get("rules", [])] == [RA.get("id"), RB.get("id"), RC.get("id")] and "status" in j
      and "imap_password" not in json.dumps(j) and "secret" not in json.dumps(j), "GET: the rules in their order, the state, never the password")

# ---- the run
M1 = drop("Rechnungen", "Shop <billing@shop.example.com>", "Your invoice 1001", att="Invoice-1001")
M2 = drop("Rechnungen", "Shop <billing@shop.example.com>", "Your order", att=None)          # no attachment: not taken
M3 = drop("Rechnungen", "Other <hello@other.example.org>", "Invoice 77", att="Other-77")    # another sender: not taken
M4 = drop("Rechnungen", "Shop <billing@shop.example.com>", "Old invoice", att="Old-900", days_old=90)  # too old: not taken
M5 = drop("Belege", "Cafe <till@cafe.example.org>", "Your receipt", att="Receipt-5")
M6 = drop("Markiert", "Tool <no-reply@tool.example.org>", "Plan", att="Plan-6")
check(run(Bo, WS), "the rules ran (docs_polled_at set, docs_due back to 0)")
d = until(lambda: (lambda x: x if len(x) >= 4 else None)(docs(WS)), 30) or docs(WS)
names = sorted(x[1] for x in d)
check(names == sorted(["Invoice-1001.pdf", "Receipt-5.pdf", "Your receipt.eml", "Plan-6.pdf"]),
      f"the fitting mails became documents of Alpha (+ the receipt mail itself) ({names})")
check(all(x[2] == "mailbox" for x in d), f"source 'mailbox' ({[x[2] for x in d]})")
check(not docs(WSE), "nothing in another workspace")
check(files("Archiv") == ["1.eml"] and files("Rechnungen") == ["2.eml", "3.eml", "4.eml"], f"the invoice mail moved to Archiv ({files('Archiv')} / {files('Rechnungen')})")
f = flags()
check("\\Seen" in f.get("Belege/1", []), f"the receipt mail marked seen ({f.get('Belege/1')})")
check("\\Flagged" in f.get("Markiert/1", []) and "\\Seen" not in f.get("Markiert/1", []), f"the plan mail flagged, still unread ({f.get('Markiert/1')})")
check(not any("\\Seen" in f.get(f"Rechnungen/{u}", []) for u in (2, 3, 4)), "the mails no rule took stay unread (fetched with BODY.PEEK)")
check(not any("\\Deleted" in v for v in f.values()) and "EXPUNGE" not in imap_log(), "without the delete switch: nothing marked deleted, no EXPUNGE")
tagged = dbx("SELECT hits FROM hub_mailbox_rules WHERE id=?", (RA.get("id"),))
check(tagged and tagged[0][0] == 1, f"the rule counts its hit ({tagged})")
inv = next((x[0] for x in d if x[1] == "Invoice-1001.pdf"), None)
dj = until(lambda: (lambda r: r.json() if r.ok and r.json().get("state") in ("done", "failed") else None)(Bo.get(B + f"/api/docs/{inv}")), 90) if inv else None
check(dj and sorted(t["name"] for t in dj.get("tags") or []) == ["Invoice", "Shop"] and (dj.get("sender") or {}).get("name") == "Shop",
      f"the rule's tags and the mail's sender on the document ({dj and (dj.get('tags'), dj.get('sender'))})")

# a second run: nothing twice (each Message-ID once per mailbox), also a copy of a taken mail in another folder
shutil.copy(os.path.join(MB, "Belege", "1.eml"), os.path.join(MB, "Belege", "2.eml"))
before = len(docs(WS))
check(run(Bo, WS), "the second run")
check(len(docs(WS)) == before, f"the second run takes nothing twice ({before} -> {len(docs(WS))})")
check("\\Seen" not in flags().get("Belege/2", []), "the copy with the same Message-ID is not touched")
check(dbx("SELECT count(*) FROM hub_mailbox_docs WHERE box_id=(SELECT id FROM hub_mailboxes WHERE ws=?)", (WS,))[0][0] >= 3,
      "the taken mails are remembered per mailbox")

# with the delete switch: exactly that mail goes
RD = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Gone", "folder": "Weg", "need_att": True, "delete_mail": True}).json().get("rule") or {}
drop("Weg", "Shop <billing@shop.example.com>", "Delete me", att="Weg-1")
drop("Weg", "Shop <billing@shop.example.com>", "No attachment here")
check(RD.get("delete_mail") is True and run(Bo, WS), "a rule with the delete switch ran")
check(files("Weg") == ["2.eml"] and "UID EXPUNGE 1" in imap_log(), f"with the switch: only the taken mail deleted (UID EXPUNGE) ({files('Weg')})")
check(Bo.delete(B + f"/api/hubmail/mailbox/rules/{RD.get('id')}").ok and not dbx("SELECT id FROM hub_mailbox_rules WHERE id=?", (RD.get("id"),)), "a rule deleted")

# ---- a person without an organisation: her private mailbox (freelancer-matrix: hub)
r = Er.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": "private"})
check(r.ok, f"erin: her private mailbox ({r.status_code} {r.text[:200]})")
EF = Er.post(B + "/api/files/folders", json={"name": "Mail documents", "space": "private"}).json().get("id")
check(Er.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "folder": "Erin"}).status_code == 404, "erin: Alpha's rules 404")
r = Er.post(B + "/api/hubmail/mailbox/rules", json={"ws": "private", "name": "Mine", "folder": "Erin", "need_att": False, "target_id": EF, "after": "none"})
check(r.status_code == 201, f"erin: a rule into her own folder ({r.status_code} {r.text[:200]})")
ER = (r.json() or {}).get("rule") or {}
r = Er.put(B + f"/api/hubmail/mailbox/rules/{ER.get('id')}", json={"subject_has": "letter", "expect_updated_at": ER.get("updated_at")})
check(r.ok, f"erin: changes her rule ({r.status_code})")
drop("Erin", "Tax office <post@tax.example.org>", "Your letter", att="Letter-1")
check(run(Er, WSE), "erin's rules ran")
de = until(lambda: docs(WSE), 30) or []
check([x[1] for x in de] == ["Letter-1.pdf"] and de[0][2] == "mailbox" and de[0][3] == EF,
      f"erin: the document in her own folder, source 'mailbox' ({de})")
check(not flags().get("Erin/1"), "after 'none': the mail stays as it was")
check(len(docs(WS)) == before + 1, "Alpha got nothing of erin's mails (only its own delete rule's document)")
j = Er.get(B + "/api/hubmail/mailbox/rules?ws=private").json()
check(j.get("status", {}).get("polled_at") and not j["status"].get("error"), f"erin: the last run without an error ({j.get('status')})")

# ---- review (#4804): a server answer without RFC822.SIZE counts as too big - the mail is passed over, the next one still comes
open(os.path.join(MB, "nosize"), "w").write("Erin/2\n")
drop("Erin", "Tax office <post@tax.example.org>", "Your letter", att="Letter-2")
drop("Erin", "Tax office <post@tax.example.org>", "Your letter", att="Letter-3")
check(run(Er, WSE), "erin's rules ran again")
de = until(lambda: docs(WSE) if len(docs(WSE)) >= 2 else None, 30) or docs(WSE)
check(sorted(x[1] for x in de) == ["Letter-1.pdf", "Letter-3.pdf"], f"no size: that mail skipped, the next one taken ({de})")

# ---- 2.638.0 (#4852): folder names with IMAP specials - '{5}' (unquoted = a literal) and 'a%*' (unquoted = wildcards) are always
# sent as quoted strings; the stub answers BAD to an unquoted one like a real server would not read it as that name
for x in ("{5}", "a%*"):
    os.makedirs(os.path.join(MB, x), exist_ok=True)
r = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Specials", "folder": "{5}", "need_att": True,
                                                    "after": "move", "after_folder": "a%*"})
check(r.status_code == 201, f"a rule on folder '{{5}}' moving into 'a%*' ({r.status_code} {r.text[:200]})")
drop("{5}", "Shop <billing@shop.example.com>", "Special folder", att="Special-1")
n0 = len(docs(WS))
check(run(Bo, WS), "the rules ran with the special folders")
check(until(lambda: len(docs(WS)) == n0 + 1, 30) and "Special-1.pdf" in [x[1] for x in docs(WS)],
      f"the mail in '{{5}}' became a document ({[x[1] for x in docs(WS)][-3:]})")
check(files("{5}") == [] and files("a%*") == ["1.eml"], f"moved from '{{5}}' into 'a%*' ({files('{5}')} / {files('a%*')})")
lg = imap_log()
check('SELECT "{5}"' in lg and '"a%*"' in lg and "SELECT {5}" not in lg, "both names went out as quoted strings")

# ---- 2.651.0 (#5033): folder names with umlauts (and '&') go out in modified UTF-7 (RFC 3501 5.1.3), still quoted; the rule
# keeps and shows the plain name. Before: imaplib refused the non-ASCII name (nothing selected, nothing moved).
for x in ("Entwürfe", "Büro & Ablage"):
    os.makedirs(os.path.join(MB, x), exist_ok=True)
r = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Umlaut", "folder": "Entwürfe", "need_att": True,
                                                    "after": "move", "after_folder": "Büro & Ablage"})
check(r.status_code == 201 and r.json()["rule"]["folder"] == "Entwürfe" and r.json()["rule"]["after_folder"] == "Büro & Ablage",
      f"#5033: a rule on 'Entwürfe' moving into 'Büro & Ablage', stored in plain text ({r.status_code} {r.text[:200]})")
drop("Entwürfe", "Shop <billing@shop.example.com>", "Umlaut folder", att="Umlaut-1")
n0 = len(docs(WS))
check(run(Bo, WS), "#5033: the rules ran with the umlaut folders")
check(until(lambda: len(docs(WS)) == n0 + 1, 30) and "Umlaut-1.pdf" in [x[1] for x in docs(WS)],
      f"#5033: the mail in 'Entwürfe' became a document ({[x[1] for x in docs(WS)][-3:]})")
check(files("Entwürfe") == [] and files("Büro & Ablage") == ["1.eml"],
      f"#5033: moved from 'Entwürfe' into 'Büro & Ablage' ({files('Entwürfe')} / {files('Büro & Ablage')})")
lg = imap_log()
check('SELECT "Entw&APw-rfe"' in lg and '"B&APw-ro &- Ablage"' in lg, "#5033: both names went out in modified UTF-7, quoted")

# ---- 2.636.0 (#4853): a mail that became no document is not remembered; the rule shows why; the next run takes it
import hashlib  # noqa: E402
ZF = Bo.post(B + "/api/files/folders", json={"name": "Mail target", "space": f"org:{ORG}"}).json().get("id")
r = Bo.post(B + "/api/hubmail/mailbox/rules", json={"ws": f"org:{ORG}", "name": "Into a folder", "folder": "Ziel", "need_att": True,
                                                    "target_id": ZF, "after": "seen"})
check(ZF and r.status_code == 201, f"#4853: a rule into an organisation folder ({r.status_code} {r.text[:200]})")
RZ = (r.json() or {}).get("rule") or {}
check(RZ.get("error") == "" and RZ.get("error_text") == "", f"#4853: a new rule has no error ({RZ.get('error')!r})")
check(Bo.post(B + "/api/files/trash", json={"ids": [ZF]}).ok, "#4853: the target folder into the trash")
r = Bo.put(B + f"/api/hubmail/mailbox/rules/{RA.get('id')}", json={"target_id": ZF})
check(r.status_code == 400, f"#4853: a folder the holder cannot file into is refused when the rule is saved ({r.status_code})")
MZ = drop("Ziel", "Shop <billing@shop.example.com>", "Invoice into a folder", att="Ziel-1")
KZ = hashlib.sha256(MZ.encode()).hexdigest()
nz = len(docs(WS))
check(run(Bo, WS), "#4853: the run while the holder cannot file into the folder")
check(not dbx("SELECT 1 FROM hub_mailbox_docs WHERE mid=?", (KZ,)), "#4853: no document -> the mail is not remembered")
check(len(docs(WS)) == nz and "\\Seen" not in flags().get("Ziel/1", []), f"#4853: no document, the mail stays unread ({flags().get('Ziel/1')})")
rz = next((x for x in Bo.get(B + f"/api/hubmail/mailbox/rules?ws=org:{ORG}").json().get("rules", []) if x["id"] == RZ.get("id")), {})
check(rz.get("error") == "target" and rz.get("error_text"), f"#4853: the rule shows the error ({rz.get('error')!r} {rz.get('error_text')!r})")
check(Bo.post(B + "/api/files/restore", json={"ids": [ZF]}).ok, "#4853: the target folder back out of the trash")
check(run(Bo, WS), "#4853: the next run")
dz = until(lambda: [x for x in docs(WS) if x[1] == "Ziel-1.pdf"], 30) or []
check(len(dz) == 1 and dz[0][3] == ZF, f"#4853: now the mail became a document in the folder ({dz})")
check(dbx("SELECT 1 FROM hub_mailbox_docs WHERE mid=?", (KZ,)) and "\\Seen" in flags().get("Ziel/1", []), "#4853: remembered and marked seen now")
rz = next((x for x in Bo.get(B + f"/api/hubmail/mailbox/rules?ws=org:{ORG}").json().get("rules", []) if x["id"] == RZ.get("id")), {})
check(rz.get("error") == "" and rz.get("hits") == 1, f"#4853: the error is gone after a document ({rz.get('error')!r}, hits {rz.get('hits')})")

# ---- 2.636.0 (#4853, review): a mail whose files are refused for what they are (a ZIP with an empty PDF) stays remembered - it is
# not fetched again every round - and the rule says so
m = email.message.EmailMessage()
m["From"], m["To"], m["Subject"] = "Shop <billing@shop.example.com>", "office@example.com", "Invoice with an empty file"
m["Message-ID"] = "<p2581d-empty@example.org>"
m["Date"] = email.utils.formatdate(time.time(), localtime=False)
m.set_content("Mail with an empty attachment")
import io  # noqa: E402
import zipfile  # noqa: E402
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w") as z:  # an attachment that unpacks to one empty PDF: the store refuses it (ValueError)
    z.writestr("Leer.pdf", b"")
m.add_attachment(zb.getvalue(), maintype="application", subtype="zip", filename="Belege.zip")
open(os.path.join(MB, "Ziel", "2.eml"), "wb").write(bytes(m))
KE = hashlib.sha256(m["Message-ID"].encode()).hexdigest()
ne = len(docs(WS))
check(run(Bo, WS), "#4853: the run with a mail whose only file is refused")
check(dbx("SELECT 1 FROM hub_mailbox_docs WHERE mid=?", (KE,)), "#4853: a refused file -> the mail stays remembered (not tried every round)")
check(len(docs(WS)) == ne, f"#4853: no document from the empty file ({len(docs(WS))} vs {ne})")
rz = next((x for x in Bo.get(B + f"/api/hubmail/mailbox/rules?ws=org:{ORG}").json().get("rules", []) if x["id"] == RZ.get("id")), {})
check(rz.get("error") == "refused" and rz.get("error_text"), f"#4853: the rule shows the refusal ({rz.get('error')!r} {rz.get('error_text')!r})")

sys.exit(done("p2581_d_mailrules"))
