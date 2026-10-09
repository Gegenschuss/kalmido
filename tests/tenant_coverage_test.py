#!/usr/bin/env python3
"""2.30.0 (#1036) the workspace boundary guard: every route of the server -- the web app's (/api/..., the public pages, CalDAV /
CardDAV) and the REST API's (/api/v1/...) -- is either covered by the cross-tenant matrix (two organisations + a private
person: a stranger and a stranger's agent see and change nothing, per object id) or listed with the reason why the boundary
between organisations does not apply to it. No container needed: reads app.py + kalmido/ like tests/parity_test.py.
 1. every route has an entry in ROUTES (its kind), nothing in ROUTES is stale
 2. every kind is in KINDS: a matrix kind names the suite that tests it, and that suite carries the marker
    "tenant-matrix: <kind>" (so a kind cannot be claimed without a test); an n/a kind carries its reason
A new route fails here until somebody decides: which object kind it serves (and the matrix test of that kind covers it), or
why it needs none. usage: python3 tests/tenant_coverage_test.py"""
import glob
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def norm(p):
    return re.sub(r"<[^>]+>", "{}", p)


src = "\n".join(open(p, encoding="utf-8").read() for p in [os.path.join(ROOT, "app.py")]
                + sorted(glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)))
FOUND = {f"{m.upper()} {norm(p)}" for m, p in re.findall(r'^@app\.(get|post|put|patch|delete)\("([^"]*)"', src, re.M)}
FOUND |= {f"DAV {norm(p)}" for p in re.findall(r'^@app\.route\("([^"]*)"', src, re.M)}  # CalDAV / CardDAV (PROPFIND, REPORT, ...)

# kind -> ("matrix", the suite(s) with its cross-tenant test) | ("n/a", the reason the organisation boundary does not apply)
KINDS = {
    # ---- covered by the matrix (the suites carry "tenant-matrix: <kind>")
    "aggregate": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: state, search, trash, tags, roadmap, day plan, occurrences"),
    "task": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: a task by id (read, change, complete, comment, subtasks, dependencies)"),
    "comment": ("matrix", "p2300_tenant_test.py: a comment by id (change, delete, react)"),
    "attachment": ("matrix", "p2300_tenant_test.py: a task's attachment / a list's file by id"),
    "chatfile": ("matrix", "p2300_tenant_test.py: a file of an agent chat by id"),
    "list": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: a list by id (read, change, members, sections, fields, notes, owner)"),
    "folder": ("matrix", "p2300_tenant_test.py: folder settings / people / groups are the own folders' only"),
    "news": ("matrix", "p2280_api_test.py: News of other workspaces"),
    "team": ("matrix", "p2280_api_test.py: team chat rooms and direct messages"),
    "agent": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: agents, their chat, events and jobs"),
    "people": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: the user list, user changes, invitations / sign-in links by id"),
    "org": ("matrix", "p2280_api_test.py: organisations, their members and admins"),
    "calendar": ("matrix", "p2300_tenant_test.py: calendars by id, sharing (B2), workspace (B3)"),
    "event": ("matrix", "p2300_tenant_test.py: events by id, ranges, invitations"),
    "book": ("matrix", "p2300_tenant_test.py: address books by id, sharing (B2), workspace (B3)"),
    "contact": ("matrix", "p2300_tenant_test.py: contacts by id, links to tasks"),
    "dav": ("matrix", "p2300_tenant_test.py: CalDAV / CardDAV collections of others"),
    "ical": ("matrix", "p2300_tenant_test.py: the calendar feed has only visible tasks"),
    "group": ("matrix", "p2300_tenant_test.py: groups without a visible member stay unknown (B1)"),
    "template": ("matrix", "p2300_tenant_test.py: templates by id, from / into lists of others"),
    "form": ("matrix", "p2300_tenant_test.py: forms by id, the form page for another organisation"),
    "client": ("matrix", "p2300_tenant_test.py: clients by id, workload"),
    "webhook": ("matrix", "p2300_tenant_test.py: webhooks by id, deliveries only of visible tasks"),
    "export": ("matrix", "p2300_tenant_test.py: the export has only the own data"),
    "stats": ("matrix", "p2300_tenant_test.py: statistics count only own / visible tasks"),
    "publiclink": ("matrix", "p2300_tenant_test.py: the public link of another person's list by id"),
    # ---- not relevant for the boundary between organisations (with the reason)
    "auth": ("n/a", "signing in, setting up and securing the own account (before a session or about the session's own person)"),
    "own": ("n/a", "the person's own rows only (settings, devices, tokens, habits, time, filters, imports, Home & life, their own "
                   "connections): read and written as user_id = me, never shared; a task / list named in them is checked with "
                   "need_task / need_list (covered by the task / list matrix)"),
    "admin": ("n/a", "the operator's administration (need_admin): server settings, backups, alerts, agents, integrations; the operator "
                     "is trusted with the whole server (architecture review 2.1 / B4); people in it are filtered by visible_people"),
    "public": ("n/a", "pages and facts without data of a person (app shell, health, version, robots, manifest, QR code of a given text)"),
    "family": ("n/a", "the household of the Family module: private by definition (kid_parents), never an organisation's object"),
    "token": ("n/a", "an inbound hook addressed by the unguessable secret of one list (sealed, looked up by its hash): nothing to "
                     "guess by id"),
}

ROUTES = {
    # ---- admin (40)
    "PUT /api/admin/oidc": "admin", "POST /api/admin/oidc/check": "admin", "GET /api/admin/storage-check": "admin",
    "GET /api/admin/backups": "admin", "PATCH /api/admin/backups": "admin", "POST /api/admin/backups": "admin",
    "GET /api/admin/backups/{}/download": "admin", "DELETE /api/admin/backups/{}": "admin",
    "POST /api/admin/backups/{}/verify": "admin", "POST /api/admin/backups/upload": "admin",
    "POST /api/admin/backups/restore": "admin", "PUT /api/admin/announcement": "admin",
    "PUT /api/v1/admin/announcement": "admin", "GET /api/admin/agents": "admin", "POST /api/admin/agents": "admin",
    "PATCH /api/admin/agents/{}": "admin", "POST /api/admin/agents/{}/reset": "admin",
    "POST /api/admin/agents/{}/avatar": "admin", "POST /api/admin/agents/{}/token": "admin",
    "POST /api/admin/agents/{}/secret": "admin", "POST /api/admin/agents/{}/test": "admin",
    "GET /api/admin/agent-policy": "admin", "PUT /api/admin/agent-policy": "admin", "DELETE /api/admin/agents/{}": "admin",
    "GET /api/admin/agents/audit": "admin", "GET /api/admin/agents/{}/audit": "admin",
    "GET /api/v1/admin/agents/{}/audit": "admin", "GET /api/v1/admin/status": "admin",
    "PATCH /api/admin/settings": "admin", "POST /api/admin/setup": "admin", "POST /api/admin/mail/poll": "admin",
    "GET /api/admin/lists/orphaned": "admin", "GET /api/admin/alerts": "admin",
    "PATCH /api/admin/alerts": "admin", "POST /api/admin/alerts/test": "admin", "DELETE /api/admin/alerts": "admin",
    # ---- agent (44)
    "GET /api/agents/{}/bridges": "agent", "POST /api/v1/agent/chats/{}/messages/{}/withdraw": "agent",  # 2.30.0 (#919 / #1037)
    "GET /api/my/agents": "agent", "POST /api/my/agents": "agent", "PATCH /api/my/agents/{}": "agent",
    "POST /api/my/agents/{}/token": "agent", "DELETE /api/my/agents/{}": "agent", "GET /api/v1/agent": "agent",
    "PUT /api/v1/agent/status": "agent", "GET /api/v1/agent/events": "agent", "GET /api/v1/agent/jobs": "agent",
    "POST /api/v1/agent/jobs": "agent", "PATCH /api/v1/agent/jobs/{}": "agent", "GET /api/agents": "agent",
    "GET /api/agents/jobs": "agent", "POST /api/agents/jobs/{}/action": "agent",
    "POST /api/agents/{}/chat/{}/choice": "agent", "PUT /api/agents/{}/permission-mode": "agent",
    "GET /api/agents/{}/chat": "agent", "POST /api/agents/{}/chat": "agent",
    "POST /api/agents/{}/chat/{}/reactions": "agent", "POST /api/agents/{}/wake": "agent",
    "GET /api/proposals/agents": "agent", "POST /api/proposals": "agent", "GET /api/proposals/{}": "agent",
    "POST /api/proposals/{}/apply": "agent", "POST /api/proposals/{}/discard": "agent",
    "POST /api/proposals/{}/undo": "agent", "POST /api/proposals/{}/redo": "agent", "GET /api/v1/agent/jobs/{}": "agent",
    "POST /api/v1/agent/jobs/{}/proposal": "agent", "GET /api/v1/agent/chats": "agent",
    "POST /api/v1/agent/chats/{}": "agent", "POST /api/v1/agent/chats/{}/messages/{}/reactions": "agent",
    "POST /api/v1/agents/{}/chat/{}/choice": "agent", "POST /api/v1/agents/{}/chat/{}/reactions": "agent",
    "POST /api/v1/agent/typing": "agent", "GET /api/v1/agents": "agent", "POST /api/v1/agent/proposals": "agent",
    "GET /api/agents/jobs/{}/steps": "agent", "POST /api/v1/agent/progress": "agent",  # 2.32.0 (#1081)
    "PUT /api/v1/agent/quota": "agent", "GET /api/v1/agent/quota": "agent", "DELETE /api/v1/agent/quota": "agent",  # 2.33.0 (#1045)
    "POST /api/v1/agent/usage": "agent", "GET /api/v1/agent/usage": "agent", "GET /api/agents/usage": "agent",
    "GET /api/agents/{}/share": "agent", "PUT /api/lists/{}/agent": "agent", "POST /api/agents/{}/share-all": "agent",
    "PUT /api/agents/{}/autoshare": "agent",
    # ---- aggregate (23)
    "GET /api/v1/trash": "aggregate", "DELETE /api/v1/trash": "aggregate", "GET /api/v1/lists": "aggregate",
    "GET /api/v1/roadmap": "aggregate", "GET /api/v1/tasks": "aggregate", "GET /api/tags/count": "aggregate",
    "POST /api/tags/delete": "aggregate", "POST /api/tags/restore": "aggregate", "GET /api/v1/tags": "aggregate",
    "GET /api/v1/search": "aggregate", "GET /api/notes": "aggregate", "GET /api/v1/notes": "aggregate",
    "GET /api/state": "aggregate", "GET /api/tasks": "aggregate", "GET /api/occurrences": "aggregate",
    "GET /api/dayplan": "aggregate", "GET /api/dayplan/review": "aggregate", "GET /api/v1/dayplan": "aggregate",
    "GET /api/v1/dayplan/review": "aggregate", "GET /api/deps": "aggregate", "POST /api/tasks/purge-done": "aggregate",
    "DELETE /api/trash": "aggregate", "GET /api/roadmap": "aggregate",
    # ---- attachment (16)
    "GET /api/v1/tasks/{}/attachments": "attachment", "GET /api/v1/attachments/{}": "attachment",
    "GET /api/v1/lists/{}/files": "attachment", "POST /api/v1/lists/{}/files": "attachment",
    "GET /api/v1/lists/{}/files/{}": "attachment", "DELETE /api/v1/lists/{}/files/{}": "attachment",
    "POST /api/v1/tasks/{}/attachments": "attachment", "POST /api/v1/tasks/{}/attachments/text": "attachment",
    "DELETE /api/v1/attachments/{}": "attachment",
    "POST /api/lists/{}/files": "attachment", "GET /api/list-files/{}": "attachment",
    "DELETE /api/list-files/{}": "attachment", "POST /api/tasks/{}/attachments": "attachment",
    "GET /api/attachments/{}": "attachment", "DELETE /api/attachments/{}": "attachment",
    # ---- auth (28)
    "POST /api/auth/invite/check": "auth", "POST /api/auth/invite/accept": "auth", "GET /api/auth/info": "auth",
    "POST /api/auth/login": "auth", "POST /api/auth/setup": "auth", "POST /api/auth/logout": "auth",
    "POST /api/auth/2fa": "auth", "POST /api/auth/2fa/passkey/options": "auth", "POST /api/auth/2fa/passkey": "auth",
    "POST /api/auth/enrol/totp": "auth", "POST /api/auth/enrol/totp/confirm": "auth",
    "POST /api/auth/enrol/passkey/options": "auth", "POST /api/auth/enrol/passkey": "auth",
    "POST /api/auth/passkey/options": "auth", "POST /api/auth/passkey": "auth", "GET /api/me/2fa": "auth",
    "POST /api/me/2fa/totp": "auth", "POST /api/me/2fa/totp/confirm": "auth", "POST /api/me/2fa/totp/disable": "auth",
    "POST /api/me/2fa/recovery": "auth", "POST /api/me/passkeys/options": "auth", "POST /api/me/passkeys": "auth",
    "PATCH /api/me/passkeys/{}": "auth", "DELETE /api/me/passkeys/{}": "auth", "GET /api/auth/oidc/start": "auth",
    "GET /api/auth/oidc/callback": "auth", "POST /api/auth/signup": "auth", "POST /api/auth/link": "auth",
    # ---- book (16)
    "GET /api/v1/address-books": "book", "POST /api/v1/address-books": "book", "PATCH /api/v1/address-books/{}": "book",
    "DELETE /api/v1/address-books/{}": "book", "PUT /api/v1/address-books/{}/members/{}": "book",
    "DELETE /api/v1/address-books/{}/members/{}": "book", "POST /api/v1/address-books/{}/import": "book",
    "GET /api/v1/address-books/{}/export": "book", "GET /api/books": "book", "POST /api/books": "book",
    "PATCH /api/books/{}": "book", "DELETE /api/books/{}": "book", "PUT /api/books/{}/members": "book",
    "DELETE /api/books/{}/members/{}": "book", "POST /api/books/{}/import": "book", "GET /api/books/{}/export.vcf": "book",
    # ---- calendar (16)
    "POST /api/evcals/{}/import": "calendar", "GET /api/v1/event-calendars": "calendar",
    "POST /api/v1/event-calendars": "calendar", "PATCH /api/v1/event-calendars/{}": "calendar",
    "DELETE /api/v1/event-calendars/{}": "calendar", "PUT /api/v1/event-calendars/{}/members/{}": "calendar",
    "DELETE /api/v1/event-calendars/{}/members/{}": "calendar", "POST /api/v1/event-calendars/{}/import": "calendar",
    "GET /api/v1/event-calendars/{}/export": "calendar", "GET /api/evcals": "calendar", "POST /api/evcals": "calendar",
    "PATCH /api/evcals/{}": "calendar", "DELETE /api/evcals/{}": "calendar", "PUT /api/evcals/{}/members": "calendar",
    "DELETE /api/evcals/{}/members/{}": "calendar", "GET /api/evcals/{}/export.ics": "calendar",
    # ---- chatfile (4)
    "GET /api/chat-files/{}": "chatfile", "DELETE /api/chat-files/{}": "chatfile",
    "GET /api/v1/chat-attachments/{}": "chatfile", "DELETE /api/v1/chat-attachments/{}": "chatfile",
    # ---- client (13)
    "GET /api/clients": "client", "GET /api/clients/{}": "client", "POST /api/clients": "client",
    "PATCH /api/clients/{}": "client", "DELETE /api/clients/{}": "client", "GET /api/v1/clients": "client",
    "POST /api/v1/clients": "client", "GET /api/v1/clients/{}": "client", "PATCH /api/v1/clients/{}": "client",
    "DELETE /api/v1/clients/{}": "client", "GET /api/v1/workload": "client", "GET /api/workload": "client",
    "PUT /api/workload/capacity/{}": "client",
    # ---- comment (9)
    "POST /api/comments/{}/decide": "comment", "POST /api/v1/comments/{}/reactions": "comment",
    "DELETE /api/v1/comments/{}/reactions/{}": "comment", "PATCH /api/v1/comments/{}": "comment",
    "DELETE /api/v1/comments/{}": "comment", "PATCH /api/comments/{}": "comment", "DELETE /api/comments/{}": "comment",
    "POST /api/comments/{}/reactions": "comment", "POST /api/comments/{}/apply": "comment",
    # ---- contact (16)
    "GET /api/v1/contacts": "contact", "POST /api/v1/contacts": "contact", "GET /api/v1/contacts/{}": "contact",
    "PATCH /api/v1/contacts/{}": "contact", "DELETE /api/v1/contacts/{}": "contact",
    "POST /api/v1/tasks/{}/contacts": "contact", "DELETE /api/v1/tasks/{}/contacts/{}": "contact",
    "GET /api/contacts": "contact", "GET /api/contacts/{}": "contact", "POST /api/contacts": "contact",
    "PATCH /api/contacts/{}": "contact", "DELETE /api/contacts/{}": "contact", "POST /api/tasks/{}/contacts": "contact",
    "DELETE /api/tasks/{}/contacts/{}": "contact", "PUT /api/v1/contacts/{}/care": "contact",
    "PUT /api/contacts/{}/care": "contact",
    # ---- dav (8)
    "DAV /": "dav", "DAV /.well-known/caldav": "dav", "DAV /.well-known/caldav/": "dav", "DAV /.well-known/carddav": "dav",
    "DAV /.well-known/carddav/": "dav", "DAV /dav": "dav", "DAV /dav/": "dav", "DAV /dav/{}": "dav",
    # ---- event (19)
    "GET /api/calendars/events": "event", "GET /api/v1/events": "event", "POST /api/v1/events": "event",
    "GET /api/v1/events/{}": "event", "PATCH /api/v1/events/{}": "event", "DELETE /api/v1/events/{}": "event",
    "POST /api/v1/events/{}/restore": "event", "POST /api/v1/events/{}/rsvp": "event",
    "POST /api/v1/events/{}/prep-task": "event", "GET /api/v1/tasks/{}/events": "event", "GET /api/events": "event",
    "GET /api/events/{}": "event", "POST /api/events": "event", "PATCH /api/events/{}": "event",
    "DELETE /api/events/{}": "event", "POST /api/events/{}/restore": "event", "POST /api/events/{}/rsvp": "event",
    "POST /api/events/{}/prep-task": "event", "GET /api/tasks/{}/events": "event",
    # ---- export (2)
    "GET /api/export.json": "export", "GET /api/v1/export": "export",
    # ---- family (32)
    "GET /api/v1/family": "family", "POST /api/v1/family/occasions": "family",
    "GET /api/v1/family/deadline-types": "family", "POST /api/v1/family/deadlines": "family",
    "POST /api/v1/tasks/{}/to-shopping": "family", "POST /api/v1/lists/{}/shop-areas": "family",
    "GET /api/v1/family/packing": "family", "POST /api/v1/family/packing": "family", "GET /api/v1/family/kids": "family",
    "POST /api/v1/family/kids/{}/stars": "family", "POST /api/v1/family/kids/{}/rewards": "family",
    "PATCH /api/v1/family/rewards/{}": "family", "DELETE /api/v1/family/rewards/{}": "family",
    "POST /api/v1/family/rewards/{}/request": "family", "POST /api/v1/family/rewards/{}/decide": "family",
    "POST /api/v1/me/purpose": "family", "GET /api/family": "family", "POST /api/family/occasions": "family",
    "GET /api/family/deadline-types": "family", "POST /api/family/deadlines": "family",
    "POST /api/tasks/{}/to-shopping": "family", "POST /api/lists/{}/shop-areas": "family",
    "GET /api/family/packing": "family", "POST /api/family/packing": "family", "POST /api/me/purpose": "family",
    "GET /api/family/kids": "family", "POST /api/family/kids/{}/stars": "family",
    "POST /api/family/kids/{}/rewards": "family", "PATCH /api/family/rewards/{}": "family",
    "DELETE /api/family/rewards/{}": "family", "POST /api/family/rewards/{}/request": "family",
    "POST /api/family/rewards/{}/decide": "family",
    # ---- folder (13)
    "GET /api/v1/folders": "folder", "POST /api/v1/folders/rename": "folder", "POST /api/v1/folders/delete": "folder",
    "GET /api/folders/props": "folder", "PUT /api/folders/props": "folder", "GET /api/folders/groups": "folder",
    "PUT /api/folders/groups/{}": "folder", "DELETE /api/folders/groups/{}": "folder", "GET /api/folders/people": "folder",
    "PUT /api/folders/people": "folder", "DELETE /api/folders/people": "folder", "POST /api/folders/rename": "folder",
    "POST /api/folders/delete": "folder",
    "GET /api/folders/repos": "folder", "POST /api/folders/repos": "folder", "PUT /api/lists/{}/folder-repo": "list",  # 2.33.0 (#934)
    "GET /api/folders/notify-template": "folder", "PUT /api/folders/notify-template": "folder",  # 2.33.0 (#927)
    "GET /api/lists/{}/notify-template": "list", "PUT /api/lists/{}/notify-template": "list",
    "GET /api/v1/lists/{}/notify-template": "list", "POST /api/notify-templates/asked": "own",
    "GET /api/search/messages": "aggregate",  # 2.33.0 (#1080): only what the person may read (vis_sql, rooms, own agent chats)
    "GET /api/admin/client-ip": "admin",  # 2.33.0 (#834)
    # ---- form (10)
    "GET /api/lists/{}/forms": "form", "POST /api/lists/{}/forms": "form", "PATCH /api/forms/{}": "form",
    "DELETE /api/forms/{}": "form", "GET /f/{}": "form", "POST /f/{}": "form", "GET /api/v1/lists/{}/forms": "form",
    "POST /api/v1/lists/{}/forms": "form", "PATCH /api/v1/forms/{}": "form", "DELETE /api/v1/forms/{}": "form",
    # ---- group (6)
    "GET /api/v1/groups": "group", "GET /api/v1/groups/{}": "group", "GET /api/groups": "group",
    "POST /api/admin/groups": "group", "PATCH /api/admin/groups/{}": "group", "DELETE /api/admin/groups/{}": "group",
    # ---- ical (3)
    "GET /ical/{}.ics": "ical", "GET /api/ical": "ical", "POST /api/ical": "ical",
    # ---- list (100)
    "GET /api/lists/{}/agent-access": "list",  # 2.30.0 (#919): the agents' access log of a list (its members)
    "PUT /api/lists/{}/icon": "list", "POST /api/lists/{}/icon": "list", "DELETE /api/lists/{}/icon": "list",
    "GET /api/list-icon/{}/{}.png": "list", "GET /api/v1/lists/{}/tags": "list", "POST /api/v1/lists/{}/tags": "list",
    "PATCH /api/v1/lists/{}/tags/{}": "list", "DELETE /api/v1/lists/{}/tags/{}": "list",
    "GET /api/v1/lists/{}/overview": "list", "PATCH /api/v1/lists/{}/overview": "list",
    "GET /api/v1/lists/{}/links": "list", "POST /api/v1/lists/{}/links": "list", "PATCH /api/v1/lists/{}/links/{}": "list",
    "DELETE /api/v1/lists/{}/links/{}": "list", "PUT /api/v1/lists/{}/links/order": "list",
    "GET /api/v1/lists/{}/milestones": "list", "POST /api/v1/lists/{}/milestones": "list",
    "PATCH /api/v1/lists/{}/milestones/{}": "list", "DELETE /api/v1/lists/{}/milestones/{}": "list",
    "GET /api/v1/lists/{}/sections": "list", "POST /api/v1/lists/{}/sections": "list", "PATCH /api/v1/sections/{}": "list",
    "PUT /api/v1/lists/{}/sections/order": "list", "DELETE /api/v1/sections/{}": "list",
    "GET /api/v1/lists/{}/fields": "list", "POST /api/v1/lists/{}/fields": "list", "PATCH /api/v1/fields/{}": "list",
    "DELETE /api/v1/fields/{}": "list", "DELETE /api/v1/lists/{}": "list", "GET /api/v1/lists/{}/members": "list",
    "PUT /api/v1/lists/{}/members/{}": "list", "DELETE /api/v1/lists/{}/members/{}": "list",
    "PUT /api/v1/lists/{}/status": "list", "PATCH /api/v1/lists/{}": "list", "GET /api/v1/lists/{}": "list",
    "POST /api/v1/lists/{}/owner": "list", "POST /api/v1/lists/{}/shift": "list", "GET /api/v1/lists/{}/groups": "list",
    "PUT /api/v1/lists/{}/groups/{}": "list", "DELETE /api/v1/lists/{}/groups/{}": "list",
    "GET /api/lists/{}/notes": "list", "POST /api/lists/{}/notes": "list", "GET /api/notes/{}": "list",
    "PATCH /api/notes/{}": "list", "DELETE /api/notes/{}": "list", "GET /api/v1/lists/{}/notes": "list",
    "POST /api/v1/lists/{}/notes": "list", "GET /api/v1/notes/{}": "list", "PATCH /api/v1/notes/{}": "list",
    "DELETE /api/v1/notes/{}": "list", "POST /api/lists/{}/tags": "list", "PATCH /api/list-tags/{}": "list",
    "DELETE /api/list-tags/{}": "list", "POST /api/lists/{}/tags/promote": "list", "GET /api/lists/{}/error-hook": "list",
    "PATCH /api/lists/{}/error-hook": "list", "GET /api/v1/lists/{}/error-hook": "list",
    "PATCH /api/v1/lists/{}/error-hook": "list", "GET /api/v1/lists/{}/repos": "list", "GET /api/lists/{}/repos": "list",
    "POST /api/lists/{}/repos": "list", "PATCH /api/repos/{}": "list", "DELETE /api/repos/{}": "list",
    "POST /api/repos/{}/refresh": "list", "POST /api/lists/{}/fields": "list", "PATCH /api/fields/{}": "list",
    "DELETE /api/fields/{}": "list", "POST /api/lists/{}/folder-reset": "list", "GET /api/lists/{}/groups": "list",
    "PUT /api/lists/{}/groups/{}": "list", "DELETE /api/lists/{}/groups/{}": "list", "POST /api/lists": "list",
    "PATCH /api/lists/{}": "list", "POST /api/lists/reorder": "list", "DELETE /api/lists/{}": "list",
    "PUT /api/lists/{}/members": "list", "DELETE /api/lists/{}/members/{}": "list", "GET /api/lists/{}/owner": "list",
    "POST /api/lists/{}/owner": "list", "PUT /api/lists/{}/bell": "list", "POST /api/lists/{}/status": "list",
    "GET /api/lists/{}/status": "list", "GET /api/lists/{}/overview": "list", "PATCH /api/lists/{}/overview": "list", "GET /api/lists/{}/layout": "list", "PUT /api/lists/{}/layout": "list",
    "POST /api/lists/{}/links": "list", "PATCH /api/lists/{}/links/{}": "list", "DELETE /api/lists/{}/links/{}": "list",
    "PUT /api/lists/{}/links/order": "list", "POST /api/lists/{}/milestones": "list",
    "PATCH /api/lists/{}/milestones/{}": "list", "DELETE /api/lists/{}/milestones/{}": "list",
    "POST /api/lists/{}/checklist": "list", "POST /api/sections": "list", "PATCH /api/sections/{}": "list",
    "POST /api/lists/{}/sections/order": "list", "DELETE /api/sections/{}": "list", "POST /api/lists/{}/shift": "list",
    "POST /api/v1/lists": "list",
    # ---- news (5)
    "GET /api/v1/news": "news", "POST /api/v1/news/read": "news", "GET /api/news": "news",
    "POST /api/news/dismiss": "news", "POST /api/news/read": "news",
    # ---- org (13)
    "GET /api/admin/orgs": "org", "POST /api/admin/orgs": "org", "PATCH /api/admin/orgs/{}": "org",
    "DELETE /api/admin/orgs/{}": "org", "PUT /api/admin/orgs/visibility": "org", "GET /api/orgs": "org",
    "PATCH /api/orgs/{}": "org", "PUT /api/orgs/{}/members": "org", "DELETE /api/orgs/{}/members/{}": "org",
    # 2.35.0 (#1101): an organisation admin's lists of the organisation (p2350_c_api_test.py: other organisation, private list, member 403)
    "GET /api/orgs/{}/lists": "org", "POST /api/orgs/{}/lists/{}/archive": "org", "DELETE /api/orgs/{}/lists/{}": "org",
    "POST /api/orgs/{}/lists/{}/owner": "org",
    # ---- own (119)
    "POST /api/onboarding": "own", "POST /api/sample": "own", "DELETE /api/sample": "own", "PATCH /api/settings": "own",
    "POST /api/ntfy/test": "own", "GET /api/push/vapid": "own", "GET /api/push/subs": "own", "POST /api/push/subs": "own",
    "DELETE /api/push/subs/{}": "own", "POST /api/push/unsubscribe": "own", "POST /api/push/handled": "own",
    "POST /api/push/test": "own", "GET /api/me": "own", "PATCH /api/me": "own", "POST /api/me/drop-token": "own",
    "GET /api/me/share/httpshortcuts.zip": "own", "PUT /api/me/avatar": "own", "POST /api/me/avatar": "own",
    "DELETE /api/me/avatar": "own", "GET /api/me/storage": "own", "GET /api/v1/me/storage": "own",
    "GET /api/v1/filters": "own", "POST /api/v1/filters": "own", "PATCH /api/v1/filters/{}": "own",
    "DELETE /api/v1/filters/{}": "own", "POST /api/v1/habits": "own", "PATCH /api/v1/habits/{}": "own",
    "DELETE /api/v1/habits/{}": "own", "GET /api/v1/time/timer": "own", "POST /api/v1/time/timer": "own",
    "DELETE /api/v1/time/timer": "own", "PATCH /api/v1/time/entries/{}": "own", "DELETE /api/v1/time/entries/{}": "own",
    "GET /api/me/tokens": "own", "POST /api/me/tokens": "own", "PATCH /api/me/tokens/{}": "own",
    "DELETE /api/me/tokens/{}": "own", "GET /api/v1/me": "own", "GET /api/v1/me/app-passwords": "own",
    "POST /api/v1/me/app-passwords": "own", "DELETE /api/v1/me/app-passwords/{}": "own",
    "PATCH /api/v1/me/notifications": "own", "GET /api/v1/time/entries": "own", "POST /api/v1/time/entries": "own",
    "GET /api/v1/habits": "own", "POST /api/v1/habits/{}/checkin": "own", "POST /api/v1/import/{}": "own",
    "POST /api/v1/imports/{}/undo": "own", "GET /api/me/app-passwords": "own", "POST /api/me/app-passwords": "own",
    "DELETE /api/me/app-passwords/{}": "own", "GET /api/calendars": "own", "POST /api/calendars/discover": "own",
    "POST /api/calendars": "own", "PATCH /api/calendars/{}": "own", "DELETE /api/calendars/{}": "own",
    "POST /api/calendars/{}/refresh": "own", "POST /api/import/ticktick": "own", "POST /api/import/{}": "own",
    "POST /api/imports/{}/undo": "own", "GET /api/imports": "own", "GET /api/me/mail": "own",
    "POST /api/me/mail/token": "own", "DELETE /api/me/mail/token": "own", "POST /api/me/mail/test": "own",
    "GET /api/v1/life": "own", "GET /api/v1/life/upkeep-presets": "own",
    "POST /api/v1/life/contracts": "own", "POST /api/v1/life/devices": "own", "POST /api/v1/life/upkeep": "own",
    "POST /api/v1/life/health": "own", "POST /api/v1/life/trips": "own", "GET /api/v1/life/review": "own",
    "PUT /api/v1/life/journal/{}": "own", "POST /api/v1/life/karakeep/sync": "own", "GET /api/life": "own",
    "GET /api/life/upkeep-presets": "own", "POST /api/life/contracts": "own", "POST /api/life/devices": "own",
    "POST /api/life/upkeep": "own", "POST /api/life/health": "own", "POST /api/life/trips": "own",
    "GET /api/life/review": "own", "PUT /api/life/journal/{}": "own", "GET /api/life/karakeep": "own",
    "PUT /api/life/karakeep": "own", "DELETE /api/life/karakeep": "own", "GET /api/life/karakeep/lists": "own",
    "POST /api/life/karakeep/sync": "own", "POST /api/filters": "own", "PATCH /api/filters/{}": "own",
    "DELETE /api/filters/{}": "own", "POST /api/habits": "own", "PATCH /api/habits/{}": "own",
    "DELETE /api/habits/{}": "own", "POST /api/habits/{}/log": "own", "POST /api/pomo/start": "own",
    "POST /api/pomo/{}/{}": "own", "POST /api/time/start": "own", "POST /api/time/stop": "own",
    "POST /api/time/entries": "own", "PATCH /api/time/entries/{}": "own", "DELETE /api/time/entries/{}": "own",
    "GET /api/time/entries": "own", "GET /api/time/report": "own", "GET /api/time/export.csv": "own",
    "GET /api/family/contacts": "own", "POST /api/family/contacts": "own", "PATCH /api/family/contacts/{}": "own",
    "DELETE /api/family/contacts/{}": "own", "POST /api/family/contacts/{}/sync": "own",
    # ---- people (9)
    "POST /api/users/{}/invite": "people", "POST /api/users/{}/approve": "people",
    "POST /api/users/{}/signin-link": "people", "GET /api/v1/admin/users": "people", "GET /api/users": "people",
    "POST /api/users": "people", "PATCH /api/users/{}": "people", "DELETE /api/users/{}": "people",
    "GET /api/avatar/{}/{}.jpg": "people",
    # ---- public (15)
    "GET /api/v1/announcement": "public", "GET /api/v1/openapi.json": "public", "GET /api/about": "public",
    "GET /": "public", "GET /capture": "public", "GET /share": "public", "POST /share": "public", "POST /drop": "public",
    "POST /drop/drop": "public", "GET /robots.txt": "public", "GET /manifest.json": "public", "GET /sw.js": "public",
    "GET /api/health": "public", "GET /api/version": "public", "POST /api/qr": "public",
    # ---- publiclink (7)
    "GET /s/{}": "publiclink", "POST /s/{}/unlock": "publiclink", "POST /s/{}/tick": "publiclink",
    "GET /api/lists/{}/public-link": "publiclink", "PUT /api/lists/{}/public-link": "publiclink",
    "POST /api/lists/{}/public-link/regenerate": "publiclink", "DELETE /api/lists/{}/public-link": "publiclink",
    # ---- stats (2)
    "GET /api/pomo/stats": "stats", "GET /api/stats": "stats",
    # ---- task (52)
    "POST /api/tasks/{}/wake": "task", "POST /api/tasks/{}/typing": "task",
    "POST /api/tasks/{}/editing": "task", "POST /api/v1/tasks/{}/typing": "task", "POST /api/v1/tasks/{}/tidy": "task",
    "POST /api/v1/tasks/{}/move": "task", "POST /api/v1/tasks/batch": "task", "POST /api/v1/tasks/{}/skip": "task",
    "POST /api/v1/tasks/{}/restore": "task", "GET /api/v1/tasks/{}/dependencies": "task",
    "POST /api/v1/tasks/{}/dependencies": "task", "DELETE /api/v1/tasks/{}/dependencies/{}": "task",
    "GET /api/v1/tasks/{}": "task", "PATCH /api/v1/tasks/{}": "task", "DELETE /api/v1/tasks/{}": "task",
    "POST /api/v1/tasks/{}/snippets": "task",  # 2.35.0 (#1095): append a code snippet (p2350_d_api_test.py: other tenant 404)
    "PUT /api/v1/tasks/{}/waiting": "task", "DELETE /api/v1/tasks/{}/waiting": "task",
    "POST /api/v1/tasks/{}/complete": "task", "POST /api/v1/tasks/{}/reopen": "task",
    "GET /api/v1/tasks/{}/milestone": "task", "GET /api/v1/tasks/{}/subtasks": "task",
    "POST /api/v1/tasks/{}/subtasks": "task", "GET /api/v1/tasks/{}/comments": "task",
    "POST /api/v1/tasks/{}/comments": "task", "POST /api/v1/tasks/{}/take": "task", "GET /api/tasks/{}/timeline": "task",
    "POST /api/tasks/{}/seen": "task", "POST /api/tasks/{}/comments": "task", "GET /api/tasks/{}": "task",
    "POST /api/tasks/{}/git-undo": "task", "POST /api/tasks/{}/take": "task",
    "GET /api/tasks/{}/milestone": "task", "POST /api/tasks/reorder": "task", "POST /api/tasks/batch": "task",
    "GET /api/tasks/{}/deps": "task", "DELETE /api/deps/{}/{}": "task", "POST /api/tasks/{}/complete": "task",
    "POST /api/tasks/{}/undo": "task", "POST /api/tasks/{}/skip": "task", "POST /api/tasks/{}/reopen": "task",
    "DELETE /api/tasks/{}": "task", "POST /api/tasks/{}/restore": "task", "PUT /api/tasks/{}/waiting": "task",
    "DELETE /api/tasks/{}/waiting": "task", "PATCH /api/tasks/{}": "task", "POST /api/tasks/{}/approval": "task",
    "POST /api/v1/tasks/{}/approval": "task", "POST /api/v1/tasks": "task", "POST /api/deps": "task",
    "POST /api/tasks": "task",
    # ---- team (16)
    "GET /api/team": "team", "POST /api/team/dm": "team", "GET /api/team/rooms/{}/messages": "team",
    "POST /api/team/rooms/{}/messages": "team", "PATCH /api/team/messages/{}": "team",
    "DELETE /api/team/messages/{}": "team", "POST /api/team/messages/{}/reactions": "team",
    "POST /api/team/rooms/{}/read": "team", "GET /api/v1/team/rooms": "team", "POST /api/v1/team/dm": "team",
    "GET /api/v1/team/rooms/{}/messages": "team", "POST /api/v1/team/rooms/{}/messages": "team",
    "PATCH /api/v1/team/messages/{}": "team", "DELETE /api/v1/team/messages/{}": "team",
    "POST /api/v1/team/messages/{}/reactions": "team", "POST /api/v1/team/rooms/{}/read": "team",
    # ---- template (10)
    "GET /api/v1/templates": "template", "POST /api/v1/templates": "template", "PATCH /api/v1/templates/{}": "template",
    "DELETE /api/v1/templates/{}": "template", "POST /api/v1/templates/{}/apply": "template",
    "GET /api/templates": "template", "POST /api/templates": "template", "PATCH /api/templates/{}": "template",
    "DELETE /api/templates/{}": "template", "POST /api/templates/{}/apply": "template",
    # ---- token (2)
    "POST /api/hooks/issues/{}/{}": "token", "POST /api/hooks/git/{}": "token",
    # ---- webhook (7)
    "GET /api/me/webhooks": "webhook", "POST /api/me/webhooks": "webhook", "PATCH /api/me/webhooks/{}": "webhook",
    "DELETE /api/me/webhooks/{}": "webhook", "POST /api/me/webhooks/{}/secret": "webhook",
    "POST /api/me/webhooks/{}/test": "webhook", "GET /api/me/webhooks/{}/log": "webhook",
    # ---- 2.34.0 (#264 #265): the briefing (a person's own, an agent: of a person it may chat with, only shared lists) and
    # the status report of a list (p2340_a_api_test.py has the cross-tenant cases)
    "GET /api/briefing": "aggregate", "POST /api/briefing/read": "own", "GET /api/v1/briefing": "aggregate",
    "GET /api/lists/{}/status-report": "list", "GET /api/v1/lists/{}/status-report": "list",
    # ---- 2.34.0 (#266 #269 #272 #368): stale tasks, time gaps, planned agent jobs, a file's text (p2300_tenant_test.py has the
    # cross-tenant cases: the other organisation's people and agent get 404 / nothing of the first one); the briefing field's
    # PDF reader reads only the uploaded file of the signed-in person and stores nothing (own)
    "GET /api/stale": "aggregate", "GET /api/v1/stale": "aggregate", "GET /api/time/gaps": "aggregate",
    "GET /api/v1/time/gaps": "aggregate", "GET /api/agents/{}/schedules": "agent", "POST /api/agents/{}/schedules": "agent",
    "PATCH /api/agent-schedules/{}": "agent", "DELETE /api/agent-schedules/{}": "agent", "POST /api/agent-schedules/{}/run": "agent",
    "GET /api/v1/agent/schedules": "agent", "GET /api/v1/attachments/{}/text": "attachment", "POST /api/pdf-text": "own",
}

# ---- 1. every route is classified, nothing stale
for r in sorted(FOUND - set(ROUTES)):
    check(False, f"route {r} is not in ROUTES: add it with its kind (matrix) or an n/a kind with the reason")
for r in sorted(set(ROUTES) - FOUND):
    check(False, f"ROUTES names {r}, which is no route (any more)")
check(len(FOUND) > 600, f"routes found: {len(FOUND)}")

# ---- 2. every kind is known; a matrix kind is really tested (marker in a suite), an n/a kind has a reason
tests = {os.path.basename(p): open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(N, "*.py"))
         if os.path.basename(p) != os.path.basename(__file__)}
# a marker line: "tenant-matrix: kind, kind, ..." (a comment in the suite, next to the checks of these kinds)
MARKED = {k.strip() for t in tests.values() for line in re.findall(r"tenant-matrix:([\w ,-]+)", t) for k in line.split(",") if k.strip()}
for r, k in sorted(ROUTES.items()):
    check(k in KINDS, f"{r}: unknown kind {k!r}")
for k, (what, why) in KINDS.items():
    check(what in ("matrix", "n/a") and len(why) > 20, f"kind {k}: needs matrix / n/a and its reason")
    if what == "matrix":
        check(k in MARKED, f"kind {k}: no suite carries the marker 'tenant-matrix: {k}'")
    check(k in ROUTES.values(), f"kind {k}: no route uses it (stale)")

n_m = sum(1 for k in ROUTES.values() if KINDS.get(k, ("",))[0] == "matrix")
print(f"tenant coverage: {len(FOUND)} routes, {n_m} in the cross-tenant matrix, {len(FOUND) - n_m} not relevant (with reason); "
      f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
