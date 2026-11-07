#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.638.0 C (#4294): "Allow public links" per kind (core/instance.py PUB_KINDS), one table row per kind. Invented data
only. Per kind: a link made while everything is on opens; the kind off -> the old link does not open (404 like the
instance switch) and no new link of that kind is made; the other kinds keep opening; the kind on again (with the
password) -> the old link opens again. p2489_c_publinks_test.py checks the switch itself (lists, uploads, the instance
switch, the freelancer); here every kind of PUB_KINDS, read from the server, must have a row.
 - #4294: a portal form while the kind portal is off takes the report as a plain one: no status link (/p/...) on the
   thank-you page that would not open (was: a ticket with a dead status link and a mail with it)
 - tools/check_pubkinds.py: every public_links_on(c, KIND) in the code names a kind of PUB_KINDS (also run in check_layout)
usage: p2638_c_publinks_test.py <datadir>"""
import base64
import os
import re
import secrets
import subprocess
import sys
import time

import requests

from kt import B, check, docker_logs_on_first_fail, done, fresh, setup, until

HERE = os.path.dirname(os.path.abspath(__file__))
fresh(prefix="P2638CL", env={"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
                             "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_ORGCRYPT_DELAY": "0",
                             "KALMIDO_SECRET_KEY": base64.b64encode(secrets.token_bytes(32)).decode()})
docker_logs_on_first_fail()

# ---- the lint first (static, no server needed)
lint = subprocess.run([sys.executable, os.path.join(HERE, "..", "tools", "check_pubkinds.py")], capture_output=True, text=True)
check(lint.returncode == 0 and "0 error(s)" in lint.stdout, "check_pubkinds: every public_links_on() names a kind " + lint.stdout[-600:])

A = setup()
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done",
                                   "features": "comments,collab,files,docs,cal,events,wiki,forms,office,clients"})
A.patch(B + "/api/admin/settings", json={"password": "password123", "public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
S = "/api/admin/settings"
OFF_MSG = "Public links are switched off"


def page(p):
    return requests.get(B + p, allow_redirects=False)


def path_of(url, part):
    return url[url.index(part):]


def kind_off(kind):
    r = A.patch(B + S, json={"public_links_off": [kind]})
    return r.ok and r.json().get("public_links_off") == [kind]


def all_on():
    r = A.patch(B + S, json={"public_links_off": [], "password": "password123"})
    return r.ok and r.json().get("public_links_off") == []


def refused(r):
    """A new link refused because of the switch (409 with the switch's message, not a missing module)."""
    return r.status_code == 409 and OFF_MSG in r.text


# ---- one maker per kind: make() -> the public path of a new link; again() -> True when a new link is refused (kind off)
def lists_make():
    lid = A.post(B + "/api/lists", json={"name": "Example shoot", "org_id": ORG}).json()["id"]
    return path_of(A.put(B + f"/api/lists/{lid}/public-link", json={"mode": "view"}).json()["link"]["url"], "/s/")


def lists_again():
    lid = A.post(B + "/api/lists", json={"name": "Second shoot", "org_id": ORG}).json()["id"]
    return A.put(B + f"/api/lists/{lid}/public-link", json={"mode": "view"}).status_code == 409


def _folder(name):
    return A.post(B + "/api/files/folders", json={"name": name, "space": f"org:{ORG}"}).json()["id"]


def files_make():
    r = A.post(B + f"/api/files/nodes/{_folder('Example share')}/ext-links", json={})
    return path_of(r.json()["links"][-1]["url"], "/s/f/")


def files_again():
    return refused(A.post(B + f"/api/files/nodes/{_folder('Second share')}/ext-links", json={}))


def uploads_make():
    r = A.post(B + f"/api/files/nodes/{_folder('Example uploads')}/requests", json={"title": "Your files", "days": 14})
    return path_of(r.json()["url"], "/u/")


def uploads_again():
    return A.post(B + f"/api/files/nodes/{_folder('Second uploads')}/requests", json={"title": "More", "days": 3}).status_code == 409


def calendar_make():  # the booking page (the poll below is the second door of the same kind)
    r = A.put(B + "/api/appt/page", json={"slug": "alpha-booking", "enabled": True, "title": "Book a call"})
    return path_of(r.json()["page"]["url"], "/s/b/")


def calendar_again():
    return refused(A.put(B + "/api/appt/page", json={"enabled": True}))


def poll_make():
    r = A.post(B + "/api/polls", json={"title": "Team lunch", "duration": 60, "tz": "Europe/Berlin", "space": f"org:{ORG}",
                                       "options": [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]})
    return path_of(r.json()["poll"]["url"], "/s/v/")


def poll_again():  # a poll is made without a link check; the list tells the dialog that its links are off
    return A.get(B + "/api/polls").json().get("public_links") is False


def signoff_make():
    lid = A.post(B + "/api/lists", json={"name": "Image film", "org_id": ORG, "kind": "project"}).json()["id"]
    return path_of(A.post(B + f"/api/lists/{lid}/signoffs", json={}).json()["url"], "/s/q/")


def signoff_again():
    lid = A.post(B + "/api/lists", json={"name": "Second film", "org_id": ORG, "kind": "project"}).json()["id"]
    return refused(A.post(B + f"/api/lists/{lid}/signoffs", json={}))


def wiki_make():
    pid = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Handbook", "body": "for customers"}).json()["id"]
    return "/s/w/" + A.post(B + "/api/wiki/shares", json={"page_id": pid, "kind": "link"}).json()["url"].rsplit("/", 1)[-1]


def wiki_again():
    pid = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Second handbook", "body": "x"}).json()["id"]
    return refused(A.post(B + "/api/wiki/shares", json={"page_id": pid, "kind": "link"}))


FL = A.post(B + "/api/lists", json={"name": "Requests", "org_id": ORG}).json()["id"]


def forms_make():
    return "/f/" + A.post(B + f"/api/lists/{FL}/forms", json={"title": "Classic", "access": "public"}).json()["url"].rsplit("/", 1)[1]


def forms_again():
    return refused(A.post(B + f"/api/lists/{FL}/forms", json={"title": "Second", "access": "public"}))


PORTAL_FORM = None


def portal_send(subject):
    """An anonymous report through the portal form -> the thank-you page's text. Waits for the page's stamp to be old enough
    (forms.py FRM_MIN_S, read from the stamp itself) instead of a fixed time."""
    anon = requests.Session()
    m = re.search(r'name="stamp" value="(\d+)\.([^"]+)"', anon.get(B + PORTAL_FORM).text)
    t0 = int(m.group(1))
    until(lambda: int(time.time()) - t0 >= 4, timeout=15)
    return anon.post(B + PORTAL_FORM, data={"subject": subject, "text": "In the second clip.", "name": "Erika Example",
                                            "email": "erika@example.com", "stamp": f"{m.group(1)}.{m.group(2)}"},
                     headers={"Sec-Fetch-Site": "same-origin"}).text


def portal_make():
    global PORTAL_FORM
    lid = A.post(B + "/api/lists", json={"name": "Support", "org_id": ORG}).json()["id"]
    f = A.post(B + f"/api/lists/{lid}/forms", json={"title": "Report", "access": "public", "portal": True}).json()
    PORTAL_FORM = "/f/" + f["url"].rsplit("/", 1)[1]
    m = re.search(r"/p/[A-Za-z0-9_-]+", portal_send("Sound hisses"))
    return m.group(0) if m else "/p/none"


def portal_again():  # 2.638.0 (#4294): the report is taken, but without a status link that would not open
    t = portal_send("Picture flickers")
    return "/p/" not in t and "Thank you" in t


COMPANY = {"name": "Example Film Ltd", "street": "Sample road 1", "zip": "12345", "city": "Sampletown", "country": "DE",
           "email": "hello@example.com", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Example bank"}
CL = None


def _invoice():
    did = A.post(B + "/api/office/docs", json={"kind": "invoice", "lang": "en", "client_id": CL, "project_title": "Edit",
                                               "service_from": "2026-05-01", "items": [{"title": "Edit", "qty": 2, "rate": 500}]}).json()["id"]
    A.post(B + f"/api/office/docs/{did}/finalize")
    return A.put(B + f"/api/office/docs/{did}/pay-online", json={"on": 1}).json()


def pay_make():
    global CL
    A.put(B + "/api/office/settings", json={"lang": "en", "company_fields": COMPANY})
    A.put(B + "/api/office/payonline", json={"provider": "stripe", "secret_key": "sk_test_good", "webhook_secret": "whsec_alpha_0123456789"})
    A.put(B + "/api/office/payonline", json={"enabled": 1})
    CL = A.post(B + "/api/clients", json={"name": "Example client AG", "street": "Market road 5", "zip": "10115",
                                          "city": "Berlin", "country": "DE"}).json()["id"]
    return "/s/pay/" + (_invoice().get("url") or "none").rsplit("/", 1)[-1]


def pay_again():  # an invoice finalised while pay is off carries no payment link (the switch answers with an empty url)
    return _invoice().get("url") == ""


ROWS = [("lists", lists_make, lists_again), ("files", files_make, files_again), ("uploads", uploads_make, uploads_again),
        ("calendar", calendar_make, calendar_again), ("calendar", poll_make, poll_again), ("signoff", signoff_make, signoff_again),
        ("wiki", wiki_make, wiki_again), ("forms", forms_make, forms_again), ("portal", portal_make, portal_again),
        ("pay", pay_make, pay_again)]

# the table covers every kind of the code (a new kind without a row turns this red)
r = A.patch(B + S, json={"public_links_off": ["no-such-kind"]})
check(r.status_code == 400, "an unknown kind: 400")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import check_pubkinds  # noqa: E402
known = sorted({k for k, _, _ in ROWS})
check(known == sorted(check_pubkinds.pub_kinds()), f"the table has a row for every kind of PUB_KINDS {known}")
for k in known:
    check(A.patch(B + S, json={"public_links_off": [k], "password": "password123"}).ok, f"{k} is a kind the server accepts")
check(all_on(), "every kind on again")

# ---- make every link while everything is on
LINKS = []
for kind, make, again in ROWS:
    p = make()
    check(page(p).status_code == 200, f"{kind}: the link {p[:12]}... opens while everything is on")
    LINKS.append((kind, p, again))

# ---- per kind: off -> its link closed, the others open, no new link; on again -> open again
for kind, p, again in LINKS:
    check(kind_off(kind), f"{kind} off (no password needed)")
    check(page(p).status_code == 404, f"{kind} off: the old link does not open (404 like the instance switch) {page(p).status_code}")
    others = [(k, q) for k, q, _ in LINKS if k != kind and page(q).status_code != 200]
    check(not others, f"{kind} off: the links of the other kinds still open {others}")
    check(again(), f"{kind} off: no new link of this kind")
    check(all_on(), f"{kind} on again (with the password)")
    check(page(p).status_code == 200, f"{kind} on again: the old link opens again (nothing deleted) {page(p).status_code}")

sys.exit(done("p2638_c_publinks"))
