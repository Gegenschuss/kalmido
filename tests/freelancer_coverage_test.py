#!/usr/bin/env python3
"""2.87.9 (#1919) the freelancer parity guard: every route of the server -- the web app's (/api/...), the public pages,
CalDAV / CardDAV and the REST API's (/api/v1/...) -- is either checked for a person WITHOUT an organisation (a freelancer:
the own private space, the own personal office, its own admin there) or listed with the reason why there is nothing to
check without an organisation. Static like tests/tenant_coverage_test.py: reads app.py + kalmido/, no container.
 1. every route has an entry in ROUTES (its area), nothing in ROUTES is stale
 2. every area is in KINDS: a matrix area names the suite that calls it as a person without an organisation, and that
    suite carries the marker "freelancer-matrix: <area>" and runs in tests/run_all.sh (so an area cannot be claimed without
    a test that runs); an n/a area carries its reason
A new route fails here until somebody decides which area it belongs to (and the freelancer suite of that area calls it:
p287b_a_freelancer_api_test.py sweeps every GET of the matrix areas as a freelancer and fails on 403 / 5xx) or why it needs
no check. The fixture "Selbstständige" for new suites: tests/freelancer_fixture.py.
usage: python3 -I tests/freelancer_coverage_test.py      (exit 0 = every route covered; the last line is the summary)"""
import glob
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
SUITE = "p287b_a_freelancer_api_test.py"

# area -> ("matrix", the suite(s) calling it as a person without an organisation) | ("n/a", why there is nothing to check)
KINDS = {
    # ---- checked as a freelancer (the suites carry "freelancer-matrix: <area>")
    "tasks": ("matrix", SUITE + ": tasks, comments, subtasks, attachments, tags, notes, search, trash, day plan, roadmap, export "
                        "and import in the private space; every GET of the area as the freelancer (no 403 / 5xx)"),
    "lists": ("matrix", SUITE + ": private lists and folders, sections, fields, templates, filters, forms, rules, views; every GET"),
    "office": ("matrix", SUITE + ", p2473_a_api_test.py, p288_a_api_test.py, p293_a_api_test.py, p293_b_api_test.py, p294_a_api_test.py, p295_a_api_test.py, p295_b_api_test.py: the personal office (the freelancer is its admin): settings, company "
                         "fields, private clients, quotation, invoice, finalising, PDF, e-invoice; receipts, newsletter, Paperless; document "
                         "templates with signature, logbook (2.93.0); travel expenses with the per diem, its report and import (2.95.0)"),
    "files": ("matrix", SUITE + ": the own file store (folders, upload, content, versions) and documents; every GET"),
    "wiki": ("matrix", SUITE + ": knowledge pages in the private space (create, change, search, export, trash)"),
    "pim": ("matrix", SUITE + ", p294_b_api_test.py: own calendars, events, address books, contacts, the booking page; CalDAV / CardDAV with an app password"),
    "time": ("matrix", SUITE + ": time entries, the timer, habits"),
    "agents": ("matrix", SUITE + ": the freelancer's own agent (my agents, its token, chat, jobs, share of a private list) and "
                         "the agent API with that agent's token"),
    "team": ("matrix", SUITE + ": the people list, direct messages and discovery without an organisation (no team rooms of "
                       "an organisation, nothing of another workspace)"),
    "hub": ("matrix", SUITE + ": absences, bookings and hub mail in the personal area (the freelancer is its own admin)"),
    "personal": ("matrix", SUITE + ": budget, Home & life, family, feeds, other servers, supporter licence -- private by nature"),
    "videos": ("matrix", "p2991_a_api_test.py: video sign-offs (2.99.1) at a private task / list / client of a person without an "
               "organisation: create, comments, versions, customer link, export, delete + restore; p2991_c_api_test.py: the own agent "
               "of such a person reads and comments them through the API v1"),
    "sheets": ("matrix", "p289_b_api_test.py, p289_c_api_test.py, p289_d_api_test.py: tables (2.89.0) in the private space of a "
                         "person without an organisation and with that person's own agent; rows to tasks / quotation drafts"),
    "own": ("matrix", SUITE + ": the own settings, profile, tokens, app passwords, push, account export / import"),
    # ---- nothing to check without an organisation (with the reason)
    "auth": ("n/a", "signing in, setting up and securing the own account: the same for every person, before any workspace"),
    "public": ("n/a", "pages and facts without data of a person (app shell, health, version, manifest, share target, QR code)"),
    "admin": ("n/a", "the server operator's administration (need_admin): no organisation involved -- a freelancer running the "
                     "own server is its operator with exactly these pages (p2473_a_api_test.py sets up a server without any "
                     "organisation)"),
    "orgadmin": ("n/a", "managing an organisation (members, admins, its lists, export, encryption): only for its members and "
                        "admins; without an organisation there is nothing to manage (the personal office is reached under "
                        "office, the private space under every other area)"),
    "link": ("n/a", "pages opened by an unguessable link (public list link, customer status page / portal, approval link, "
                    "calendar feed, the booking page of a person (2.94.0)): the same for the link of a private list or document as for an organisation's"),
    "token": ("n/a", "inbound hooks addressed by the secret of one list / environment / repository: no person, no workspace"),
    "pure": ("n/a", "a pure transformation of the request body (an outline file into a tree): no stored data"),
}

ROUTES = {
    # ---- admin (54)
    "DELETE /api/admin/agents/{}": "admin", "DELETE /api/admin/agents/{}/machines/{}": "admin",
    "DELETE /api/admin/alerts": "admin", "DELETE /api/admin/backups/{}": "admin", "DELETE /api/admin/groups/{}": "admin",
    "DELETE /api/admin/groups/{}/avatar": "admin", "GET /api/admin/agent-policy": "admin", "GET /api/admin/agents": "admin",
    "GET /api/admin/agents/audit": "admin", "GET /api/admin/agents/{}/audit": "admin",
    "GET /api/admin/agents/{}/machines": "admin", "GET /api/admin/alerts": "admin", "GET /api/admin/assistant": "admin",
    "GET /api/admin/backups": "admin", "GET /api/admin/backups/{}/download": "admin", "GET /api/admin/client-ip": "admin",
    "GET /api/admin/health": "admin",  # 2.102.0 D (#1994): the server's capacity numbers
    "GET /api/admin/lists/orphaned": "admin", "GET /api/admin/orgcrypt": "admin", "GET /api/admin/related": "admin",
    "GET /api/admin/storage-check": "admin", "GET /api/admin/upload-scan": "admin",
    "GET /api/v1/admin/agents/{}/audit": "admin", "GET /api/v1/admin/status": "admin", "GET /api/v1/admin/users": "admin",
    "PATCH /api/admin/agents/{}": "admin", "PATCH /api/admin/alerts": "admin", "PATCH /api/admin/backups": "admin",
    "PATCH /api/admin/groups/{}": "admin", "PATCH /api/admin/settings": "admin", "POST /api/admin/agents": "admin",
    "POST /api/admin/agents/{}/avatar": "admin", "POST /api/admin/agents/{}/reset": "admin",
    "POST /api/admin/agents/{}/secret": "admin", "POST /api/admin/agents/{}/setup-code": "admin",
    "POST /api/admin/agents/{}/test": "admin", "POST /api/admin/agents/{}/token": "admin",
    "POST /api/admin/alerts/test": "admin", "POST /api/admin/backups": "admin", "POST /api/admin/backups/restore": "admin",
    "POST /api/admin/backups/upload": "admin", "POST /api/admin/backups/{}/verify": "admin", "POST /api/admin/groups": "admin",
    "POST /api/admin/groups/{}/avatar": "admin", "POST /api/admin/mail/poll": "admin", "POST /api/admin/oidc/check": "admin",
    "POST /api/admin/setup": "admin", "PUT /api/admin/agent-policy": "admin", "PUT /api/admin/announcement": "admin",
    "PUT /api/admin/groups/{}/avatar": "admin", "PUT /api/admin/oidc": "admin", "PUT /api/admin/orgcrypt": "admin",
    "PUT /api/admin/related": "admin", "PUT /api/layouts/std/{}": "admin", "PUT /api/v1/admin/announcement": "admin",
    # ---- agents (72)
    "DELETE /api/agent-schedules/{}": "agents", "DELETE /api/my/agents/{}": "agents",
    "DELETE /api/my/agents/{}/machines/{}": "agents", "DELETE /api/v1/agent/quota": "agents", "GET /api/agents": "agents",
    "GET /api/agents/jobs": "agents", "GET /api/agents/jobs/{}/steps": "agents", "GET /api/agents/usage": "agents",
    "GET /api/agents/{}/bridges": "agents", "GET /api/agents/{}/chat": "agents",
    # 2.96.0 C (#2015): job cards in the agent chat
    "GET /api/agents/{}/meeting-proposals": "agents", "GET /api/agents/{}/schedules": "agents",
    "GET /api/agents/{}/share": "agents", "GET /api/assistant": "agents", "GET /api/assistant/log": "agents",
    "GET /api/my/agents": "agents", "GET /api/my/agents/{}/machines": "agents", "GET /api/proposals/agents": "agents",
    "GET /api/proposals/{}": "agents", "GET /api/v1/agent": "agents", "GET /api/v1/agent/chats": "agents",
    "GET /api/v1/agent/events": "agents", "GET /api/v1/agent/jobs": "agents", "GET /api/v1/agent/jobs/{}": "agents",
    "GET /api/v1/agent/quota": "agents", "GET /api/v1/agent/schedules": "agents", "GET /api/v1/agent/usage": "agents",
    "GET /api/v1/agents": "agents", "PATCH /api/agent-schedules/{}": "agents", "PATCH /api/agents/{}/chat/{}": "agents",
    "PATCH /api/agents/{}/color": "agents", "PATCH /api/my/agents/{}": "agents", "PATCH /api/v1/agent/jobs/{}": "agents",
    "POST /api/agent-schedules/{}/run": "agents", "POST /api/agents/jobs/{}/action": "agents",
    "POST /api/agents/{}/chat": "agents", "POST /api/agents/{}/chat/{}/choice": "agents",
    "POST /api/agents/{}/chat/{}/pin": "agents", "POST /api/agents/{}/chat/{}/reactions": "agents",
    "POST /api/agents/{}/meeting-images": "agents", "POST /api/agents/{}/schedules": "agents",
    "POST /api/agents/{}/share-all": "agents", "POST /api/agents/{}/wake": "agents", "POST /api/assistant/run": "agents",
    "POST /api/my/agents": "agents", "POST /api/my/agents/{}/setup-code": "agents", "POST /api/my/agents/{}/token": "agents",
    "POST /api/proposals": "agents", "POST /api/proposals/{}/apply": "agents", "POST /api/proposals/{}/discard": "agents",
    "POST /api/proposals/{}/redo": "agents", "POST /api/proposals/{}/undo": "agents", "POST /api/v1/agent/chats/{}": "agents",
    "POST /api/v1/agent/chats/{}/messages/{}/pin": "agents", "POST /api/v1/agent/chats/{}/messages/{}/reactions": "agents",
    "POST /api/v1/agent/chats/{}/messages/{}/withdraw": "agents", "POST /api/v1/agent/jobs": "agents",
    "POST /api/v1/agent/jobs/{}/proposal": "agents", "POST /api/v1/agent/progress": "agents",
    "POST /api/v1/agent/proposals": "agents", "POST /api/v1/agent/proposals/import": "agents",
    "POST /api/v1/agent/proposals/shoot": "agents", "POST /api/v1/agent/proposals/time": "agents",
    "POST /api/v1/agent/typing": "agents", "POST /api/v1/agent/usage": "agents",
    "POST /api/v1/agents/{}/chat/{}/choice": "agents", "POST /api/v1/agents/{}/chat/{}/reactions": "agents",
    "PUT /api/agents/{}/autoshare": "agents", "PUT /api/agents/{}/permission-mode": "agents",
    "PUT /api/assistant/lists": "agents", "PUT /api/v1/agent/quota": "agents", "PUT /api/v1/agent/status": "agents",
    # ---- auth (31)
    "DELETE /api/me/passkeys/{}": "auth", "GET /api/auth/info": "auth", "GET /api/auth/oidc/callback": "auth",
    "GET /api/auth/oidc/start": "auth", "GET /api/me/2fa": "auth", "PATCH /api/me/passkeys/{}": "auth",
    "POST /api/agent-setup/redeem": "auth", "POST /api/agent-setup/remove": "auth", "POST /api/auth/2fa": "auth",
    "POST /api/auth/2fa/passkey": "auth", "POST /api/auth/2fa/passkey/options": "auth", "POST /api/auth/enrol/passkey": "auth",
    "POST /api/auth/enrol/passkey/options": "auth", "POST /api/auth/enrol/totp": "auth",
    "POST /api/auth/enrol/totp/confirm": "auth", "POST /api/auth/forgot": "auth", "POST /api/auth/invite/accept": "auth",
    "POST /api/auth/invite/check": "auth", "POST /api/auth/link": "auth", "POST /api/auth/login": "auth",
    "POST /api/auth/logout": "auth", "POST /api/auth/passkey": "auth", "POST /api/auth/passkey/options": "auth",
    "POST /api/auth/setup": "auth", "POST /api/auth/signup": "auth", "POST /api/me/2fa/recovery": "auth",
    "POST /api/me/2fa/totp": "auth", "POST /api/me/2fa/totp/confirm": "auth", "POST /api/me/2fa/totp/disable": "auth",
    "POST /api/me/passkeys": "auth", "POST /api/me/passkeys/options": "auth",
    # ---- files (51)
    "DELETE /api/docs/labels/{}/{}": "files", "DELETE /api/docs/mail": "files", "DELETE /api/docs/rules/{}": "files",
    "DELETE /api/docs/{}/task": "files", "DELETE /api/files/nodes/{}": "files", "DELETE /api/files/shares/{}": "files",
    "GET /api/docs": "files", "GET /api/docs/settings": "files", "GET /api/docs/{}": "files", "GET /api/docs/{}/file": "files",
    "GET /api/docs/{}/receipt": "files", "GET /api/docs/{}/thumb": "files", "GET /api/files": "files",
    "GET /api/files/folders": "files", "GET /api/files/nodes/{}": "files", "GET /api/files/nodes/{}/content": "files",
    "GET /api/files/nodes/{}/share-targets": "files", "GET /api/files/search": "files", "GET /api/v1/documents": "files",
    "GET /api/v1/documents/{}": "files", "GET /api/v1/files": "files", "GET /api/v1/files/search": "files",
    "GET /api/v1/files/{}": "files", "GET /api/v1/files/{}/content": "files", "GET /api/v1/files/{}/text": "files",
    "PATCH /api/docs/labels/{}/{}": "files", "PATCH /api/docs/rules/{}": "files", "PATCH /api/docs/{}": "files",
    "PATCH /api/files/nodes/{}": "files", "PATCH /api/files/shares/{}": "files", "PATCH /api/v1/documents/{}": "files",
    # 2.96.0 A (#1941): files / folders / documents to the other workspace
    "POST /api/files/move-space": "files",
    "POST /api/docs": "files", "POST /api/docs/labels/{}": "files", "POST /api/docs/mail": "files",
    "POST /api/docs/rules": "files", "POST /api/docs/{}/accept": "files", "POST /api/docs/{}/redo": "files",
    "POST /api/docs/{}/review": "files", "POST /api/docs/{}/task": "files", "POST /api/files/folders": "files",
    "POST /api/files/links": "files", "POST /api/files/nodes/{}/restore": "files", "POST /api/files/nodes/{}/shares": "files",
    "POST /api/files/nodes/{}/versions": "files", "POST /api/files/nodes/{}/versions/{}/restore": "files",
    "POST /api/files/upload": "files", "POST /api/v1/documents/{}/receipt-suggestion": "files", "POST /api/v1/files": "files",
    "POST /api/v1/files/{}/versions": "files", "PUT /api/docs/settings": "files", "PUT /api/docs/{}/receipt": "files",
    # ---- hub (27)
    "DELETE /api/hubmail/address": "hub", "DELETE /api/hubmail/mails/{}": "hub", "DELETE /api/team/absences/{}": "hub",
    "DELETE /api/team/dispo/bookings/{}": "hub", "GET /api/hubmail/inbox": "hub", "GET /api/hubmail/mails": "hub",
    "GET /api/hubmail/mails/{}": "hub", "GET /api/hubmail/mails/{}/files/{}": "hub", "GET /api/hubmail/targets": "hub",
    "GET /api/team/absences": "hub", "GET /api/team/absences/check": "hub", "GET /api/team/bookings/mine": "hub",
    "GET /api/team/dispo": "hub", "GET /api/team/dispo/free": "hub", "GET /api/v1/absences": "hub", "GET /api/v1/dispo": "hub",
    "GET /api/v1/dispo/free": "hub", "PATCH /api/team/absences/{}": "hub", "PATCH /api/team/dispo/bookings/{}": "hub",
    "POST /api/hubmail/address": "hub", "POST /api/hubmail/mails/{}/assign": "hub",
    "POST /api/hubmail/mails/{}/restore": "hub", "POST /api/team/absences": "hub", "POST /api/team/absences/{}/restore": "hub",
    "POST /api/team/dispo/bookings": "hub", "POST /api/team/dispo/bookings/restore": "hub",
    "PUT /api/team/absences/holidays": "hub",
    # ---- link (22)
    "GET /f/{}": "link", "GET /ical/{}.ics": "link", "GET /p/{}": "link", "GET /p/{}/stop": "link", "GET /portal": "link",
    "GET /portal/login/{}": "link", "GET /s/q/{}": "link", "GET /s/q/{}/pdf": "link", "POST /s/q/{}/comments": "link", "GET /s/{}": "link",
    "GET /s/{}/file/{}": "link", "GET /s/{}/logo": "link", "POST /f/{}": "link", "POST /p/{}/comment": "link",
    "POST /p/{}/login": "link", "POST /p/{}/notify": "link", "POST /p/{}/stop": "link", "POST /portal/login/{}": "link",
    "POST /portal/logout": "link", "POST /s/q/{}": "link", "POST /s/{}/feedback": "link", "POST /s/{}/tick": "link",
    "POST /s/{}/unlock": "link",
    # ---- lists (254)
    "DELETE /api/fields/{}": "lists", "DELETE /api/filters/{}": "lists", "DELETE /api/folders/agents": "lists",
    "DELETE /api/folders/groups/{}": "lists", "DELETE /api/folders/people": "lists", "DELETE /api/forms/{}": "lists",
    "DELETE /api/layouts/saved/{}": "lists", "DELETE /api/list-files/{}": "lists", "DELETE /api/list-tags/{}": "lists",
    "DELETE /api/lists/{}": "lists", "DELETE /api/lists/{}/favorite": "lists", "DELETE /api/lists/{}/groups/{}": "lists",
    "DELETE /api/lists/{}/icon": "lists", "DELETE /api/lists/{}/links/{}": "lists", "DELETE /api/lists/{}/members/{}": "lists",
    "DELETE /api/lists/{}/milestones/{}": "lists", "DELETE /api/lists/{}/public-link": "lists",
    "DELETE /api/rules/{}": "lists", "DELETE /api/sections/{}": "lists", "DELETE /api/templates/{}": "lists",
    "DELETE /api/v1/fields/{}": "lists", "DELETE /api/v1/filters/{}": "lists", "DELETE /api/v1/forms/{}": "lists",
    "DELETE /api/v1/lists/{}": "lists", "DELETE /api/v1/lists/{}/files/{}": "lists",
    "DELETE /api/v1/lists/{}/groups/{}": "lists", "DELETE /api/v1/lists/{}/links/{}": "lists",
    "DELETE /api/v1/lists/{}/members/{}": "lists", "DELETE /api/v1/lists/{}/milestones/{}": "lists",
    "DELETE /api/v1/lists/{}/tags/{}": "lists", "DELETE /api/v1/sections/{}": "lists", "DELETE /api/v1/templates/{}": "lists",
    "GET /api/fields/{}/count": "lists", "GET /api/folder-heads": "lists", "GET /api/folders/agents": "lists",
    "GET /api/folders/groups": "lists", "GET /api/folders/groups/{}/diff": "lists",
    "GET /api/folders/notify-template": "lists", "GET /api/folders/people": "lists", "GET /api/folders/people/diff": "lists",
    "GET /api/folders/playbook": "lists", "GET /api/folders/playbook/versions": "lists",
    "GET /api/folders/playbook/versions/{}": "lists", "GET /api/folders/props": "lists",
    "GET /api/folders/public-links": "lists", "GET /api/folders/repos": "lists", "GET /api/group-avatar/{}/{}.jpg": "lists",
    "GET /api/groups": "lists", "GET /api/layouts/offers/{}": "lists", "GET /api/layouts/saved": "lists",
    "GET /api/list-files/{}": "lists", "GET /api/list-header/{}/{}.jpg": "lists", "GET /api/list-icon/{}/{}.png": "lists",
    "GET /api/lists/{}/agent-access": "lists", "GET /api/lists/{}/checks": "lists", "GET /api/lists/{}/e2e": "lists",
    "GET /api/lists/{}/e2e/todo": "lists", "GET /api/lists/{}/envs": "lists", "GET /api/lists/{}/error-hook": "lists",
    "GET /api/lists/{}/folder-preview": "lists", "GET /api/lists/{}/forms": "lists", "GET /api/lists/{}/groups": "lists",
    "GET /api/lists/{}/kpis": "lists", "GET /api/lists/{}/layout": "lists", "GET /api/lists/{}/notes": "lists",
    "GET /api/lists/{}/notify-template": "lists", "GET /api/lists/{}/overview": "lists", "GET /api/lists/{}/owner": "lists",
    "GET /api/lists/{}/playbook": "lists", "GET /api/lists/{}/playbook/versions": "lists",
    "GET /api/lists/{}/playbook/versions/{}": "lists", "GET /api/lists/{}/public-link": "lists",
    "GET /api/lists/{}/repos": "lists", "GET /api/lists/{}/rules": "lists", "GET /api/lists/{}/signoffs": "lists",
    "GET /api/lists/{}/sprints": "lists", "GET /api/lists/{}/status": "lists", "GET /api/lists/{}/status-report": "lists",
    "GET /api/lists/{}/time/delete-all": "lists", "GET /api/lists/{}/velocity": "lists", "GET /api/templates": "lists",
    "GET /api/v1/filters": "lists", "GET /api/v1/folders": "lists", "GET /api/v1/groups": "lists",
    "GET /api/v1/groups/{}": "lists", "GET /api/v1/layouts/blocks": "lists", "GET /api/v1/layouts/{}": "lists",
    "GET /api/v1/lists": "lists", "GET /api/v1/lists/{}": "lists", "GET /api/v1/lists/{}/environments": "lists",
    "GET /api/v1/lists/{}/error-hook": "lists", "GET /api/v1/lists/{}/fields": "lists", "GET /api/v1/lists/{}/files": "lists",
    "GET /api/v1/lists/{}/files/{}": "lists", "GET /api/v1/lists/{}/forms": "lists", "GET /api/v1/lists/{}/groups": "lists",
    "GET /api/v1/lists/{}/kpis": "lists", "GET /api/v1/lists/{}/links": "lists", "GET /api/v1/lists/{}/members": "lists",
    "GET /api/v1/lists/{}/milestones": "lists", "GET /api/v1/lists/{}/notepads": "lists",
    "GET /api/v1/lists/{}/notes": "lists", "GET /api/v1/lists/{}/notify-template": "lists",
    "GET /api/v1/lists/{}/overview": "lists", "GET /api/v1/lists/{}/playbook": "lists", "GET /api/v1/lists/{}/repos": "lists",
    "GET /api/v1/lists/{}/rules": "lists", "GET /api/v1/lists/{}/sections": "lists", "GET /api/v1/lists/{}/sprints": "lists",
    "GET /api/v1/lists/{}/status-report": "lists", "GET /api/v1/lists/{}/tags": "lists",
    "GET /api/v1/lists/{}/velocity": "lists", "GET /api/v1/lists/{}/weekly-status": "lists", "GET /api/v1/templates": "lists",
    "PATCH /api/fields/{}": "lists", "PATCH /api/filters/{}": "lists", "PATCH /api/forms/{}": "lists",
    "PATCH /api/layouts/saved/{}": "lists", "PATCH /api/list-tags/{}": "lists", "PATCH /api/lists/{}": "lists",
    "PATCH /api/lists/{}/error-hook": "lists", "PATCH /api/lists/{}/links/{}": "lists",
    "PATCH /api/lists/{}/milestones/{}": "lists", "PATCH /api/lists/{}/overview": "lists", "PATCH /api/rules/{}": "lists",
    "PATCH /api/sections/{}": "lists", "PATCH /api/templates/{}": "lists", "PATCH /api/v1/fields/{}": "lists",
    "PATCH /api/v1/filters/{}": "lists", "PATCH /api/v1/forms/{}": "lists", "PATCH /api/v1/lists/{}": "lists",
    "PATCH /api/v1/lists/{}/error-hook": "lists", "PATCH /api/v1/lists/{}/links/{}": "lists",
    "PATCH /api/v1/lists/{}/milestones/{}": "lists", "PATCH /api/v1/lists/{}/overview": "lists",
    "PATCH /api/v1/lists/{}/tags/{}": "lists", "PATCH /api/v1/sections/{}": "lists", "PATCH /api/v1/templates/{}": "lists",
    "POST /api/filters": "lists", "POST /api/folders/delete": "lists", "POST /api/folders/owner": "lists",
    "POST /api/folders/playbook/restore": "lists", "POST /api/folders/rename": "lists", "POST /api/folders/repos": "lists",
    "POST /api/layouts/offers": "lists", "POST /api/layouts/offers/{}/accept": "lists",
    "POST /api/layouts/offers/{}/decline": "lists", "POST /api/layouts/saved": "lists",
    "POST /api/layouts/saved/standard": "lists", "POST /api/layouts/saved/{}/activate": "lists", "POST /api/lists": "lists",
    "POST /api/lists/reorder": "lists", "POST /api/lists/{}/checklist": "lists", "POST /api/lists/{}/checks": "lists",
    "POST /api/lists/{}/duplicate": "lists", "POST /api/lists/{}/e2e/bulk": "lists",
    "POST /api/lists/{}/e2e/files/{}": "lists", "POST /api/lists/{}/e2e/finish": "lists",
    "POST /api/lists/{}/e2e/keys": "lists", "POST /api/lists/{}/e2e/rotate": "lists", "POST /api/lists/{}/e2e/start": "lists",
    "POST /api/lists/{}/e2e/stop": "lists", "POST /api/lists/{}/envs": "lists", "POST /api/lists/{}/fields": "lists",
    "POST /api/lists/{}/files": "lists", "POST /api/lists/{}/folder-reset": "lists", "POST /api/lists/{}/forms": "lists",
    "POST /api/lists/{}/header": "lists", "POST /api/lists/{}/icon": "lists", "POST /api/lists/{}/join": "lists",
    "POST /api/lists/{}/links": "lists", "POST /api/lists/{}/milestones": "lists", "POST /api/lists/{}/notepads": "lists",
    "POST /api/lists/{}/notes": "lists", "POST /api/lists/{}/owner": "lists",
    "POST /api/lists/{}/playbook/proposals/{}/apply": "lists", "POST /api/lists/{}/playbook/proposals/{}/discard": "lists",
    "POST /api/lists/{}/playbook/restore": "lists", "POST /api/lists/{}/public-link/regenerate": "lists",
    "POST /api/lists/{}/repos": "lists", "POST /api/lists/{}/rules": "lists", "POST /api/lists/{}/sections/order": "lists",
    "POST /api/lists/{}/shift": "lists", "POST /api/lists/{}/shop-areas": "lists", "POST /api/lists/{}/signoffs": "lists",
    "POST /api/lists/{}/signoffs/{}/revoke": "lists", "POST /api/lists/{}/sprints": "lists",
    "POST /api/lists/{}/sprints/assign": "lists", "POST /api/lists/{}/status": "lists", "POST /api/lists/{}/tags": "lists",
    "POST /api/lists/{}/tags/promote": "lists", "POST /api/lists/{}/time/delete-all": "lists",
    "POST /api/lists/{}/time/restore": "lists", "POST /api/rules/{}/restore": "lists", "POST /api/sections": "lists",
    "POST /api/templates": "lists", "POST /api/templates/{}/apply": "lists", "POST /api/v1/filters": "lists",
    "POST /api/v1/folders/delete": "lists", "POST /api/v1/folders/rename": "lists", "POST /api/v1/layouts/proposals": "lists",
    "POST /api/v1/lists": "lists", "POST /api/v1/lists/{}/deployments": "lists", "POST /api/v1/lists/{}/duplicate": "lists",
    "POST /api/v1/lists/{}/fields": "lists", "POST /api/v1/lists/{}/files": "lists", "POST /api/v1/lists/{}/forms": "lists",
    "POST /api/v1/lists/{}/join": "lists", "POST /api/v1/lists/{}/links": "lists", "POST /api/v1/lists/{}/milestones": "lists",
    "POST /api/v1/lists/{}/notepads": "lists", "POST /api/v1/lists/{}/notes": "lists", "POST /api/v1/lists/{}/owner": "lists",
    "POST /api/v1/lists/{}/playbook/proposals": "lists", "POST /api/v1/lists/{}/rules/proposals": "lists",
    "POST /api/v1/lists/{}/sections": "lists", "POST /api/v1/lists/{}/shift": "lists",
    "POST /api/v1/lists/{}/shop-areas": "lists", "POST /api/v1/lists/{}/sprints/assign": "lists",
    "POST /api/v1/lists/{}/tags": "lists", "POST /api/v1/templates": "lists", "POST /api/v1/templates/{}/apply": "lists",
    "PUT /api/folder-heads": "lists", "PUT /api/folders/agents": "lists", "PUT /api/folders/groups/{}": "lists",
    "PUT /api/folders/notify-template": "lists", "PUT /api/folders/people": "lists", "PUT /api/folders/playbook": "lists",
    "PUT /api/folders/props": "lists", "PUT /api/folders/public-links": "lists", "PUT /api/lists/{}/agent": "lists",
    "PUT /api/lists/{}/bell": "lists", "PUT /api/lists/{}/favorite": "lists", "PUT /api/lists/{}/folder-repo": "lists",
    "PUT /api/lists/{}/groups/{}": "lists", "PUT /api/lists/{}/header": "lists", "PUT /api/lists/{}/icon": "lists",
    "PUT /api/lists/{}/in-mine": "lists", "PUT /api/lists/{}/layout": "lists", "PUT /api/lists/{}/links/order": "lists",
    "PUT /api/lists/{}/members": "lists", "PUT /api/lists/{}/notify-template": "lists",
    "PUT /api/lists/{}/page-style": "lists", "PUT /api/lists/{}/playbook": "lists", "PUT /api/lists/{}/public-link": "lists",
    "PUT /api/lists/{}/review": "lists", "PUT /api/lists/{}/sprint-settings": "lists",
    "PUT /api/v1/lists/{}/groups/{}": "lists", "PUT /api/v1/lists/{}/links/order": "lists",
    "PUT /api/v1/lists/{}/members/{}": "lists", "PUT /api/v1/lists/{}/review": "lists",
    "PUT /api/v1/lists/{}/sections/order": "lists", "PUT /api/v1/lists/{}/status": "lists",
    "PUT /api/v1/lists/{}/status-pad": "lists",
    # ---- office (157)
    "DELETE /api/clients/{}": "office", "DELETE /api/newsletter": "office", "DELETE /api/newsletter/segments/{}": "office",
    "DELETE /api/office/deals/{}": "office", "DELETE /api/office/docs/{}": "office",
    "DELETE /api/office/docs/{}/parts/{}": "office", "DELETE /api/office/docs/{}/payments/{}": "office",
    "DELETE /api/office/fixed-costs/{}": "office", "DELETE /api/office/logo": "office",
    "DELETE /api/office/packs/installed/{}/{}": "office", "DELETE /api/office/trips/{}": "office",
    "DELETE /api/office/trips/{}/items/{}": "office", "DELETE /api/office/{}/{}": "office", "DELETE /api/paperless": "office",
    "DELETE /api/paperless/zip": "office", "DELETE /api/v1/clients/{}": "office", "GET /api/clients": "office",
    "GET /api/clients/{}": "office", "GET /api/clients/{}/book-contacts": "office", "GET /api/newsletter": "office",
    "GET /api/newsletter/lists": "office", "GET /api/office/agents/{}": "office", "GET /api/office/cashflow": "office",
    "GET /api/office/cashflow/check": "office", "GET /api/office/catalog": "office", "GET /api/office/datev/extf": "office",
    "GET /api/office/deals": "office", "GET /api/office/deals/summary": "office", "GET /api/office/docs": "office",
    "GET /api/office/docs/{}": "office", "GET /api/office/docs/{}/log": "office", "GET /api/office/docs/{}/payments": "office",
    "GET /api/office/docs/{}/pdf": "office", "GET /api/office/docs/{}/render": "office",
    "GET /api/office/docs/{}/signoffs": "office", "GET /api/office/docs/{}/xml": "office", "GET /api/office/export": "office",
    "GET /api/office/fixed-costs": "office", "GET /api/office/fixed-costs/import/template": "office",
    "GET /api/office/kpi": "office", "GET /api/office/legacy/archive": "office", "GET /api/office/legacy/archive/{}": "office",
    "GET /api/office/legacy/archive/{}/pdf": "office", "GET /api/office/legacy/counter": "office",
    "GET /api/office/legacy/runs": "office", "GET /api/office/log": "office", "GET /api/office/logo": "office",
    "GET /api/office/mail-status": "office", "GET /api/office/number-preview": "office", "GET /api/office/packs": "office",
    "GET /api/office/packs/{}": "office", "GET /api/office/pay-props": "office", "GET /api/office/settings": "office",
    "GET /api/office/trips": "office", "GET /api/office/trips/bill-docs": "office", "GET /api/office/trips/report": "office",
    "GET /api/office/trips/vma": "office", "GET /api/office/trips/vma-rates": "office", "GET /api/office/trips/vma.csv": "office",  # 2.95.0 A (#1932)
    "GET /api/office/trips/vma.pdf": "office", "GET /api/office/trips/vma.xlsx": "office",
    "GET /api/office/{}": "office", "GET /api/office/{}/{}": "office", "GET /api/paperless": "office",
    "GET /api/paperless/preview": "office", "GET /api/paperless/zip/preview": "office", "GET /api/v1/clients": "office",
    "GET /api/v1/clients/{}": "office", "GET /api/v1/office": "office", "GET /api/v1/office/docs": "office",
    "GET /api/v1/office/docs/{}": "office", "GET /api/v1/office/docs/{}/pdf": "office",
    "GET /api/v1/office/payment-suggestions": "office", "GET /api/v1/office/{}": "office",
    "GET /api/v1/receipt-suggestions": "office", "PATCH /api/clients/{}": "office",
    "PATCH /api/newsletter/segments/{}": "office", "PATCH /api/office/agents/{}": "office",
    "PATCH /api/office/deals/{}": "office", "PATCH /api/office/docs/{}": "office",
    "PATCH /api/office/docs/{}/parts/{}": "office", "PATCH /api/office/fixed-costs/{}": "office",
    "PATCH /api/office/legacy/archive/{}": "office", "PATCH /api/office/trips/{}": "office",
    "PATCH /api/office/trips/{}/items/{}": "office", "PATCH /api/office/{}/{}": "office", "PATCH /api/v1/clients/{}": "office",
    "PATCH /api/v1/office/offers/{}": "office", "POST /api/clients": "office", "POST /api/clients/bulk": "office",
    "POST /api/clients/merge": "office", "POST /api/clients/merges/{}/undo": "office",
    "POST /api/newsletter/segments": "office", "POST /api/newsletter/sync": "office",
    "POST /api/office/catalog/refresh": "office", "POST /api/office/deals": "office",
    "POST /api/office/deals/{}/offer": "office", "POST /api/office/deals/{}/project": "office",
    "POST /api/office/deals/{}/restore": "office", "POST /api/office/docs": "office",
    "POST /api/office/docs/from-time": "office", "POST /api/office/docs/reminder": "office",
    "POST /api/office/docs/{}/credit": "office", "POST /api/office/docs/{}/datev": "office",
    "POST /api/office/docs/{}/cashflow": "office", "POST /api/office/docs/{}/duplicate": "office", "POST /api/office/docs/{}/fee": "office",
    "POST /api/office/docs/{}/finalize": "office", "POST /api/office/docs/{}/invoice": "office",
    "POST /api/office/docs/{}/number": "office", "POST /api/office/docs/{}/parts": "office",
    "POST /api/office/docs/{}/payments": "office", "POST /api/office/docs/{}/send": "office",
    "POST /api/office/docs/{}/signoff": "office", "POST /api/office/docs/{}/status": "office",
    "POST /api/office/fixed-costs": "office", "POST /api/office/fixed-costs/delete": "office",
    "POST /api/office/fixed-costs/import": "office", "POST /api/office/fixed-costs/import/preview": "office",
    "POST /api/office/import": "office", "POST /api/office/legacy/archive": "office",
    "POST /api/office/legacy/archive/address": "office", "POST /api/office/legacy/archive/parse": "office",
    "POST /api/office/legacy/archive/run": "office", "POST /api/office/legacy/counter": "office",
    "POST /api/office/legacy/import": "office", "POST /api/office/legacy/preview": "office",
    "POST /api/office/legacy/runs/{}/undo": "office", "POST /api/office/legacy/split": "office",
    "POST /api/office/logo": "office", "POST /api/office/move": "office", "POST /api/office/packs/install": "office",
    "POST /api/office/packs/installed/{}/{}/restore": "office", "POST /api/office/packs/validate": "office",
    "POST /api/office/pay-props/{}": "office", "POST /api/office/signoffs/{}/revoke": "office",
    "POST /api/office/trips": "office", "POST /api/office/trips/bill": "office", "POST /api/office/trips/unbill": "office",
    "POST /api/office/trips/delete": "office", "POST /api/office/trips/import": "office", "POST /api/office/trips/import/preview": "office",  # 2.95.0 B (#1932)
    "POST /api/office/trips/{}/items": "office", "POST /api/office/{}": "office", "POST /api/paperless/import": "office",
    "POST /api/paperless/stop": "office", "POST /api/paperless/zip": "office", "POST /api/paperless/zip/import": "office",
    "POST /api/paperless/zip/part": "office", "POST /api/paperless/zip/stop": "office",
    "POST /api/receipt-suggestions/{}/accept": "office", "POST /api/receipt-suggestions/{}/reject": "office",
    "POST /api/receipt-suggestions/{}/reopen": "office", "POST /api/v1/clients": "office",
    "POST /api/v1/clients/bulk": "office", "POST /api/v1/office/offers": "office",
    "POST /api/v1/office/offers/{}/invoice": "office", "POST /api/v1/office/payment-suggestions": "office",
    "POST /api/v1/office/reminders": "office", "PUT /api/newsletter": "office", "PUT /api/newsletter/consent": "office",
    "PUT /api/office/cashflow/check": "office", "PUT /api/office/docs/{}/items": "office",
    "PUT /api/office/docs/{}/parts/{}/items": "office", "PUT /api/office/settings": "office", "PUT /api/paperless": "office",
    # ---- orgadmin (23)
    "GET /api/org-icon/{}/{}.png": "orgadmin", "POST /api/orgs/{}/icon": "orgadmin", "DELETE /api/orgs/{}/icon": "orgadmin",  # 2.87.9 (#1913)
    "DELETE /api/admin/orgs/{}": "orgadmin", "DELETE /api/orgs/{}/export": "orgadmin",
    "DELETE /api/orgs/{}/lists/{}": "orgadmin", "DELETE /api/orgs/{}/lists/{}/icon": "orgadmin",
    "DELETE /api/orgs/{}/members/{}": "orgadmin", "GET /api/admin/orgs": "orgadmin", "GET /api/orgs/{}/encryption": "orgadmin",
    "GET /api/orgs/{}/export": "orgadmin", "GET /api/orgs/{}/export/file": "orgadmin", "GET /api/orgs/{}/lists": "orgadmin",
    "PATCH /api/admin/orgs/{}": "orgadmin", "PATCH /api/orgs/{}": "orgadmin", "PATCH /api/orgs/{}/lists/{}": "orgadmin",
    "POST /api/admin/orgs": "orgadmin", "POST /api/admin/orgs/boundary/repair": "orgadmin",
    "POST /api/orgs/{}/encryption/recovery": "orgadmin", "POST /api/orgs/{}/export": "orgadmin",
    "POST /api/orgs/{}/lists/{}/archive": "orgadmin", "POST /api/orgs/{}/lists/{}/icon": "orgadmin",
    "POST /api/orgs/{}/lists/{}/owner": "orgadmin", "PUT /api/admin/orgs/visibility": "orgadmin",
    "PUT /api/orgs/{}/lists/{}/icon": "orgadmin", "PUT /api/orgs/{}/members": "orgadmin",
    # ---- own (61)
    "DELETE /api/account/export": "own", "DELETE /api/account/import/{}": "own", "DELETE /api/me/app-passwords/{}": "own",
    "DELETE /api/me/avatar": "own", "DELETE /api/me/mail/token": "own", "DELETE /api/me/tokens/{}": "own",
    "DELETE /api/me/wait-suggestions": "own", "DELETE /api/me/webhooks/{}": "own", "DELETE /api/push/subs/{}": "own",
    "DELETE /api/v1/me/app-passwords/{}": "own", "GET /api/account/export": "own", "GET /api/account/export/file": "own",
    "GET /api/account/import": "own", "GET /api/account/import/{}": "own", "GET /api/me": "own",
    "GET /api/me/app-passwords": "own", "GET /api/me/mail": "own", "GET /api/me/share/httpshortcuts.zip": "own",
    "GET /api/me/storage": "own", "GET /api/me/tokens": "own", "GET /api/me/wait-suggestions": "own",
    "GET /api/me/webhooks": "own", "GET /api/me/webhooks/{}/log": "own", "GET /api/orgs": "own", "GET /api/push/subs": "own",
    "GET /api/push/vapid": "own", "GET /api/v1/me": "own", "GET /api/v1/me/app-passwords": "own",
    "GET /api/v1/me/storage": "own", "PATCH /api/me": "own", "PATCH /api/me/tokens/{}": "own",
    "PATCH /api/me/webhooks/{}": "own", "PATCH /api/settings": "own", "PATCH /api/v1/me/notifications": "own",
    "POST /api/account/export": "own", "POST /api/account/import": "own", "POST /api/account/import/{}/key": "own",
    "POST /api/account/import/{}/run": "own", "POST /api/me/app-passwords": "own", "POST /api/me/avatar": "own",
    # 2.96.0 D (#1941 / #1918): an organisation export into the private space
    "POST /api/me/drop-token": "own", "POST /api/me/mail/test": "own", "POST /api/me/mail/token": "own",
    "POST /api/me/pin/lock": "own", "POST /api/me/pin/unlock": "own", "POST /api/me/purpose": "own",
    "POST /api/me/tokens": "own", "POST /api/me/webhooks": "own", "POST /api/me/webhooks/{}/secret": "own",
    "POST /api/me/webhooks/{}/test": "own", "POST /api/notify-templates/asked": "own", "POST /api/ntfy/test": "own",
    "POST /api/onboarding": "own", "POST /api/push/handled": "own", "POST /api/push/subs": "own", "POST /api/push/test": "own",
    "POST /api/push/unsubscribe": "own", "POST /api/v1/me/app-passwords": "own", "POST /api/v1/me/purpose": "own",
    "PUT /api/account/import/{}": "own", "PUT /api/me/avatar": "own",
    # ---- personal (110)
    "DELETE /api/budget/cats/{}": "personal", "DELETE /api/budget/entries/{}": "personal",
    "DELETE /api/budget/files/{}": "personal", "DELETE /api/budget/recurring/{}": "personal",
    "DELETE /api/family/contacts/{}": "personal", "DELETE /api/family/kids/{}/pin": "personal",
    "DELETE /api/family/rewards/{}": "personal", "DELETE /api/feeds/{}": "personal", "DELETE /api/life/karakeep": "personal",
    "DELETE /api/servers/{}": "personal", "DELETE /api/servers/{}/tasks/{}": "personal",
    "DELETE /api/supporter/{}": "personal", "DELETE /api/v1/family/rewards/{}": "personal", "GET /api/budget": "personal",
    "GET /api/budget/files/{}": "personal", "GET /api/budget/{}": "personal", "GET /api/budget/{}/contracts": "personal",
    "GET /api/budget/{}/recurring": "personal", "GET /api/family": "personal", "GET /api/family/contacts": "personal",
    "GET /api/family/deadline-types": "personal", "GET /api/family/kids": "personal", "GET /api/family/packing": "personal",
    "GET /api/feeds": "personal", "GET /api/feeds/items": "personal", "GET /api/feeds/opml": "personal",
    "GET /api/life": "personal", "GET /api/life/karakeep": "personal", "GET /api/life/karakeep/lists": "personal",
    "GET /api/life/review": "personal", "GET /api/life/upkeep-presets": "personal", "GET /api/servers": "personal",
    "GET /api/servers/{}/data": "personal", "GET /api/servers/{}/events": "personal", "GET /api/servers/{}/news": "personal",
    "GET /api/servers/{}/search": "personal", "GET /api/servers/{}/tasks/{}": "personal", "GET /api/supporter": "personal",
    "GET /api/v1/family": "personal", "GET /api/v1/family/deadline-types": "personal", "GET /api/v1/family/kids": "personal",
    "GET /api/v1/family/packing": "personal", "GET /api/v1/life": "personal", "GET /api/v1/life/review": "personal",
    "GET /api/v1/life/upkeep-presets": "personal", "PATCH /api/budget/cats/{}": "personal",
    "PATCH /api/budget/entries/{}": "personal", "PATCH /api/budget/recurring/{}": "personal",
    "PATCH /api/family/contacts/{}": "personal", "PATCH /api/family/rewards/{}": "personal",
    "PATCH /api/servers/self": "personal", "PATCH /api/servers/{}": "personal", "PATCH /api/servers/{}/tasks/{}": "personal",
    "PATCH /api/supporter/nudge": "personal", "PATCH /api/v1/family/rewards/{}": "personal",
    "POST /api/budget/entries/{}/files": "personal", "POST /api/budget/lists": "personal",
    "POST /api/budget/recurring/{}/book": "personal", "POST /api/budget/{}/cats": "personal",
    "POST /api/budget/{}/contracts": "personal", "POST /api/budget/{}/entries": "personal",
    "POST /api/budget/{}/import/commit": "personal", "POST /api/budget/{}/import/parse": "personal",
    "POST /api/budget/{}/recurring": "personal", "POST /api/family/contacts": "personal",
    "POST /api/family/contacts/{}/sync": "personal", "POST /api/family/deadlines": "personal",
    "POST /api/family/kids/{}/rewards": "personal", "POST /api/family/kids/{}/stars": "personal",
    "POST /api/family/occasions": "personal", "POST /api/family/packing": "personal",
    "POST /api/family/rewards/{}/decide": "personal", "POST /api/family/rewards/{}/request": "personal",
    "POST /api/feeds": "personal", "POST /api/feeds/items/{}/later": "personal", "POST /api/feeds/opml": "personal",
    "POST /api/feeds/read": "personal", "POST /api/feeds/{}/restore": "personal", "POST /api/life/contracts": "personal",
    "POST /api/life/devices": "personal", "POST /api/life/health": "personal", "POST /api/life/karakeep/sync": "personal",
    "POST /api/life/trips": "personal", "POST /api/life/upkeep": "personal", "POST /api/servers": "personal",
    "POST /api/servers/code": "personal", "POST /api/servers/move": "personal", "POST /api/servers/{}/news/read": "personal",
    "POST /api/servers/{}/restore": "personal", "POST /api/servers/{}/tasks": "personal",
    "POST /api/servers/{}/tasks/{}/{}": "personal", "POST /api/supporter/{}/swap": "personal",
    "POST /api/v1/family/deadlines": "personal", "POST /api/v1/family/kids/{}/rewards": "personal",
    "POST /api/v1/family/kids/{}/stars": "personal", "POST /api/v1/family/occasions": "personal",
    "POST /api/v1/family/packing": "personal", "POST /api/v1/family/rewards/{}/decide": "personal",
    "POST /api/v1/family/rewards/{}/request": "personal", "POST /api/v1/life/contracts": "personal",
    "POST /api/v1/life/devices": "personal", "POST /api/v1/life/health": "personal",
    "POST /api/v1/life/karakeep/sync": "personal", "POST /api/v1/life/trips": "personal",
    "POST /api/v1/life/upkeep": "personal", "PUT /api/family/kids/{}/pin": "personal", "PUT /api/life/journal/{}": "personal",
    "PUT /api/life/karakeep": "personal", "PUT /api/supporter/{}": "personal", "PUT /api/v1/life/journal/{}": "personal",
    # ---- pim (88)
    "DAV /": "pim", "DAV /.well-known/caldav": "pim", "DAV /.well-known/caldav/": "pim", "DAV /.well-known/carddav": "pim",
    "DAV /.well-known/carddav/": "pim", "DAV /dav": "pim", "DAV /dav/": "pim", "DAV /dav/{}": "pim",
    "DELETE /api/books/{}": "pim", "DELETE /api/books/{}/members/{}": "pim", "DELETE /api/books/{}/org": "pim",
    "DELETE /api/calendars/{}": "pim", "DELETE /api/calendars/{}/events": "pim", "DELETE /api/contacts/{}": "pim",
    "DELETE /api/evcals/{}": "pim", "DELETE /api/evcals/{}/members/{}": "pim", "DELETE /api/events/{}": "pim",
    "DELETE /api/v1/address-books/{}": "pim", "DELETE /api/v1/address-books/{}/members/{}": "pim",
    "DELETE /api/v1/contacts/{}": "pim", "DELETE /api/v1/event-calendars/{}": "pim",
    "DELETE /api/v1/event-calendars/{}/members/{}": "pim", "DELETE /api/v1/events/{}": "pim", "GET /api/books": "pim",
    "GET /api/books/imports/{}": "pim", "GET /api/books/{}/export.vcf": "pim", "GET /api/calendars": "pim",
    "GET /api/calendars/events": "pim", "GET /api/contacts": "pim", "GET /api/contacts/{}": "pim", "GET /api/evcals": "pim",
    "GET /api/evcals/{}/export.ics": "pim", "GET /api/events": "pim", "GET /api/events/{}": "pim",
    "GET /api/v1/address-books": "pim", "GET /api/v1/address-books/{}/export": "pim", "GET /api/v1/contacts": "pim",
    "GET /api/v1/contacts/{}": "pim", "GET /api/v1/event-calendars": "pim", "GET /api/v1/event-calendars/{}/export": "pim",
    "GET /api/v1/events": "pim", "GET /api/v1/events/{}": "pim", "PATCH /api/books/{}": "pim",
    "PATCH /api/books/{}/org": "pim", "PATCH /api/calendars/{}": "pim", "PATCH /api/calendars/{}/events": "pim",
    "PATCH /api/contacts/{}": "pim", "PATCH /api/evcals/{}": "pim", "PATCH /api/events/{}": "pim",
    "PATCH /api/v1/address-books/{}": "pim", "PATCH /api/v1/contacts/{}": "pim", "PATCH /api/v1/event-calendars/{}": "pim",
    "PATCH /api/v1/events/{}": "pim", "POST /api/books": "pim", "POST /api/books/{}/import": "pim",
    "POST /api/books/{}/org": "pim", "POST /api/calendars": "pim", "POST /api/calendars/discover": "pim",
    "POST /api/calendars/{}/events": "pim", "POST /api/calendars/{}/events/restore": "pim",
    "POST /api/calendars/{}/refresh": "pim", "POST /api/calendars/{}/write": "pim", "POST /api/contacts": "pim",
    "POST /api/contacts/bulk": "pim", "POST /api/contacts/merge": "pim", "POST /api/contacts/merges/{}/undo": "pim",
    "POST /api/evcals": "pim", "POST /api/evcals/{}/import": "pim", "POST /api/events": "pim",
    "POST /api/events/{}/prep-task": "pim", "POST /api/events/{}/restore": "pim", "POST /api/events/{}/rsvp": "pim",
    "POST /api/v1/address-books": "pim", "POST /api/v1/address-books/{}/import": "pim", "POST /api/v1/contacts": "pim",
    "POST /api/v1/contacts/bulk": "pim", "POST /api/v1/event-calendars": "pim",
    "POST /api/v1/event-calendars/{}/import": "pim", "POST /api/v1/events": "pim", "POST /api/v1/events/{}/prep-task": "pim",
    "POST /api/v1/events/{}/restore": "pim", "POST /api/v1/events/{}/rsvp": "pim", "PUT /api/books/{}/members": "pim",
    "PUT /api/contacts/{}/care": "pim", "PUT /api/evcals/{}/members": "pim", "PUT /api/v1/address-books/{}/members/{}": "pim",
    "PUT /api/v1/contacts/{}/care": "pim", "PUT /api/v1/event-calendars/{}/members/{}": "pim",
    # ---- public (19)
    "GET /": "public", "GET /agent-setup.ps1": "public", "GET /agent-setup.sh": "public", "GET /api/about": "public",
    "GET /api/health": "public", "GET /api/layouts/std": "public", "GET /api/related/config": "public",
    "GET /api/v1/announcement": "public", "GET /api/v1/openapi.json": "public", "GET /api/version": "public",
    "GET /capture": "public", "GET /manifest.json": "public", "GET /robots.txt": "public", "GET /share": "public",
    "GET /sw.js": "public", "POST /api/qr": "public", "POST /drop": "public", "POST /drop/drop": "public",
    "POST /share": "public",
    # ---- pure (1)
    "POST /api/outline/parse": "pure",
    # ---- tasks (192)
    "DELETE /api/attachments/{}": "tasks", "DELETE /api/chat-files/{}": "tasks", "DELETE /api/comments/{}": "tasks",
    "DELETE /api/deps/{}/{}": "tasks", "DELETE /api/envs/{}": "tasks", "DELETE /api/envs/{}/deploys/{}": "tasks",
    "DELETE /api/list-checks/{}": "tasks", "DELETE /api/notepads/{}": "tasks", "DELETE /api/notes/{}": "tasks",
    "DELETE /api/repos/{}": "tasks", "DELETE /api/sample": "tasks", "DELETE /api/sprints/{}": "tasks",
    "DELETE /api/tasks/{}": "tasks", "DELETE /api/tasks/{}/contacts/{}": "tasks", "DELETE /api/tasks/{}/enc-note": "tasks",
    "DELETE /api/tasks/{}/links/{}": "tasks", "DELETE /api/tasks/{}/note-lock": "tasks",
    "DELETE /api/tasks/{}/waiting": "tasks", "DELETE /api/trash": "tasks", "DELETE /api/v1/attachments/{}": "tasks",
    "DELETE /api/v1/chat-attachments/{}": "tasks", "DELETE /api/v1/comments/{}": "tasks",
    "DELETE /api/v1/comments/{}/reactions/{}": "tasks", "DELETE /api/v1/notepads/{}": "tasks",
    "DELETE /api/v1/notes/{}": "tasks", "DELETE /api/v1/tasks/{}": "tasks", "DELETE /api/v1/tasks/{}/contacts/{}": "tasks",
    "DELETE /api/v1/tasks/{}/dependencies/{}": "tasks", "DELETE /api/v1/tasks/{}/links/{}": "tasks",
    "DELETE /api/v1/tasks/{}/waiting": "tasks", "DELETE /api/v1/trash": "tasks", "GET /api/attachments/{}": "tasks",
    "GET /api/briefing": "tasks", "GET /api/chat-files/{}": "tasks", "GET /api/comments/{}/choice": "tasks",
    "GET /api/dayplan": "tasks", "GET /api/dayplan/review": "tasks", "GET /api/deps": "tasks", "GET /api/export.json": "tasks",
    "GET /api/ical": "tasks", "GET /api/imports": "tasks", "GET /api/news": "tasks", "GET /api/notes": "tasks",
    "GET /api/notes/{}": "tasks", "GET /api/occurrences": "tasks", "GET /api/pomo/stats": "tasks", "GET /api/roadmap": "tasks",
    "GET /api/search/messages": "tasks", "GET /api/sprints/{}": "tasks", "GET /api/stale": "tasks", "GET /api/state": "tasks",
    "GET /api/state/delta": "tasks", "GET /api/stats": "tasks", "GET /api/tags/count": "tasks", "GET /api/tasks": "tasks",
    "GET /api/tasks/{}": "tasks", "GET /api/tasks/{}/bell": "tasks", "GET /api/tasks/{}/deps": "tasks",
    "GET /api/tasks/{}/enc-note": "tasks", "GET /api/tasks/{}/events": "tasks", "GET /api/tasks/{}/milestone": "tasks",
    "GET /api/tasks/{}/note-lock": "tasks", "GET /api/tasks/{}/related": "tasks", "GET /api/tasks/{}/timeline": "tasks",
    "GET /api/v1/attachments/{}": "tasks", "GET /api/v1/attachments/{}/text": "tasks", "GET /api/v1/briefing": "tasks",
    "GET /api/v1/chat-attachments/{}": "tasks", "GET /api/v1/dayplan": "tasks", "GET /api/v1/dayplan/review": "tasks",
    "GET /api/v1/export": "tasks", "GET /api/v1/news": "tasks", "GET /api/v1/notes": "tasks", "GET /api/v1/notes/{}": "tasks",
    "GET /api/v1/roadmap": "tasks", "GET /api/v1/search": "tasks", "GET /api/v1/sprints/{}": "tasks",
    "GET /api/v1/stale": "tasks", "GET /api/v1/tags": "tasks", "GET /api/v1/tasks": "tasks", "GET /api/v1/tasks/{}": "tasks",
    "GET /api/v1/tasks/{}/attachments": "tasks", "GET /api/v1/tasks/{}/comments": "tasks",
    "GET /api/v1/tasks/{}/dependencies": "tasks", "GET /api/v1/tasks/{}/events": "tasks",
    "GET /api/v1/tasks/{}/milestone": "tasks", "GET /api/v1/tasks/{}/related": "tasks",
    "GET /api/v1/tasks/{}/subtasks": "tasks", "GET /api/v1/trash": "tasks", "GET /api/v1/workload": "tasks",
    "GET /api/workload": "tasks", "PATCH /api/comments/{}": "tasks", "PATCH /api/envs/{}": "tasks",
    "PATCH /api/list-checks/{}": "tasks", "PATCH /api/notepads/{}": "tasks", "PATCH /api/notes/{}": "tasks",
    "PATCH /api/repos/{}": "tasks", "PATCH /api/sprints/{}": "tasks", "PATCH /api/tasks/{}": "tasks",
    "PATCH /api/tasks/{}/links/{}": "tasks", "PATCH /api/tasks/{}/ticket": "tasks", "PATCH /api/v1/comments/{}": "tasks",
    "PATCH /api/v1/notepads/{}": "tasks", "PATCH /api/v1/notes/{}": "tasks", "PATCH /api/v1/tasks/{}": "tasks",
    "POST /api/briefing/read": "tasks", "POST /api/chat-save": "tasks", "POST /api/comments/{}/apply": "tasks",
    "POST /api/comments/{}/choice": "tasks", "POST /api/comments/{}/decide": "tasks",
    "POST /api/comments/{}/reactions": "tasks", "POST /api/deps": "tasks", "POST /api/envs/{}/deploy": "tasks",
    "POST /api/envs/{}/restore": "tasks", "POST /api/favorites/suggestion": "tasks", "POST /api/ical": "tasks",
    "POST /api/import/ticktick": "tasks", "POST /api/import/{}": "tasks", "POST /api/imports/{}/undo": "tasks",
    "POST /api/list-checks/{}/run": "tasks", "POST /api/news/dismiss": "tasks", "POST /api/news/read": "tasks",
    "POST /api/pdf-text": "tasks", "POST /api/pomo/start": "tasks", "POST /api/pomo/{}/{}": "tasks",
    "POST /api/repos/{}/refresh": "tasks", "POST /api/sample": "tasks", "POST /api/sprints/{}/close": "tasks",
    "POST /api/sprints/{}/start": "tasks", "POST /api/tags/delete": "tasks", "POST /api/tags/restore": "tasks",
    "POST /api/tasks": "tasks", "POST /api/tasks/batch": "tasks", "POST /api/tasks/purge-done": "tasks",
    "POST /api/tasks/reorder": "tasks", "POST /api/tasks/similar": "tasks", "POST /api/tasks/{}/approval": "tasks",
    "POST /api/tasks/{}/attachments": "tasks", "POST /api/tasks/{}/bell/undo": "tasks",
    "POST /api/tasks/{}/chain/pull": "tasks", "POST /api/tasks/{}/comments": "tasks", "POST /api/tasks/{}/complete": "tasks",
    "POST /api/tasks/{}/contacts": "tasks", "POST /api/tasks/{}/editing": "tasks",
    "POST /api/tasks/{}/enc-attachments": "tasks", "POST /api/tasks/{}/git-undo": "tasks", "POST /api/tasks/{}/links": "tasks",
    "POST /api/tasks/{}/list-attachments": "tasks", "POST /api/tasks/{}/reopen": "tasks",
    "POST /api/tasks/{}/restore": "tasks", "POST /api/tasks/{}/review": "tasks", "POST /api/tasks/{}/seen": "tasks",
    "POST /api/tasks/{}/skip": "tasks", "POST /api/tasks/{}/take": "tasks", "POST /api/tasks/{}/to-shopping": "tasks",
    "POST /api/tasks/{}/typing": "tasks", "POST /api/tasks/{}/undo": "tasks", "POST /api/tasks/{}/wake": "tasks",
    "POST /api/v1/comments/{}/choice": "tasks", "POST /api/v1/comments/{}/reactions": "tasks",
    "POST /api/v1/comments/{}/withdraw": "tasks", "POST /api/v1/import/{}": "tasks", "POST /api/v1/imports/{}/undo": "tasks",
    "POST /api/v1/news/read": "tasks", "POST /api/v1/tasks": "tasks", "POST /api/v1/tasks/batch": "tasks",
    "POST /api/v1/tasks/{}/approval": "tasks", "POST /api/v1/tasks/{}/attachments": "tasks",
    "POST /api/v1/tasks/{}/attachments/text": "tasks", "POST /api/v1/tasks/{}/comments": "tasks",
    "POST /api/v1/tasks/{}/complete": "tasks", "POST /api/v1/tasks/{}/contacts": "tasks",
    "POST /api/v1/tasks/{}/dependencies": "tasks", "POST /api/v1/tasks/{}/links": "tasks",
    "POST /api/v1/tasks/{}/move": "tasks", "POST /api/v1/tasks/{}/reopen": "tasks", "POST /api/v1/tasks/{}/restore": "tasks",
    "POST /api/v1/tasks/{}/review": "tasks", "POST /api/v1/tasks/{}/skip": "tasks", "POST /api/v1/tasks/{}/snippets": "tasks",
    "POST /api/v1/tasks/{}/subtasks": "tasks", "POST /api/v1/tasks/{}/take": "tasks", "POST /api/v1/tasks/{}/tidy": "tasks",
    "POST /api/v1/tasks/{}/to-shopping": "tasks", "POST /api/v1/tasks/{}/typing": "tasks",
    "PUT /api/tasks/mine-order": "tasks", "PUT /api/tasks/{}/bell": "tasks", "PUT /api/tasks/{}/enc-note": "tasks",
    "PUT /api/tasks/{}/note-lock": "tasks", "PUT /api/tasks/{}/waiting": "tasks", "PUT /api/v1/tasks/{}/waiting": "tasks",
    "PUT /api/workload/capacity/{}": "tasks",
    # ---- team (43)
    "DELETE /api/disc/blocks/{}": "team", "DELETE /api/disc/connections/{}": "team", "DELETE /api/disc/requests/{}": "team",
    "DELETE /api/e2e/keys": "team", "DELETE /api/team/messages/{}": "team", "DELETE /api/users/{}": "team",
    # 2.87.9 after the merge of 2.88.0 (#1980): the instance admin's account administration (an organisation admin only
    # deletes inside the own organisation)
    "GET /api/users/{}/delete-info": "admin", "POST /api/users/bulk": "admin",
    # 2.89.1 after the merge of 2.89.0 (#1916): tables, app and agent routes
    # 2.99.1 A (#1959): video sign-offs
    "GET /api/videos": "videos", "POST /api/videos": "videos", "GET /api/videos/{}": "videos", "PATCH /api/videos/{}": "videos",
    "DELETE /api/videos/{}": "videos", "POST /api/videos/{}/restore": "videos", "POST /api/videos/{}/versions": "videos",
    "DELETE /api/videos/{}/versions/{}": "videos", "POST /api/videos/{}/comments": "videos", "PATCH /api/videos/{}/comments/{}": "videos",
    "DELETE /api/videos/{}/comments/{}": "videos", "POST /api/videos/{}/comments/{}/restore": "videos",
    "GET /api/videos/{}/export": "videos", "POST /api/videos/{}/signoff": "videos", "POST /api/videos/{}/signoffs/{}/revoke": "videos",
    "POST /api/videos/{}/move-space": "videos",
    # 2.99.1 C (#1959): video sign-offs for agents (videos/v1.py; p2991_c_api_test.py)
    "GET /api/v1/videos": "videos", "GET /api/v1/videos/{}": "videos", "POST /api/v1/videos/{}/comments": "videos",
    "PATCH /api/v1/videos/{}/comments/{}": "videos",
    "DELETE /api/sheets/{}": "sheets", "DELETE /api/sheets/{}/columns/{}": "sheets",
    "DELETE /api/sheets/{}/rows/{}": "sheets", "GET /api/sheets": "sheets", "GET /api/sheets/{}": "sheets",
    "GET /api/sheets/{}/export.csv": "sheets", "GET /api/sheets/{}/export.xlsx": "sheets",
    "GET /api/sheets/{}/links": "sheets", "GET /api/sheets/{}/vars": "sheets", "GET /api/v1/sheets": "sheets",
    "GET /api/v1/sheets/{}": "sheets", "GET /api/v1/sheets/{}/vars": "sheets", "PATCH /api/sheets/{}": "sheets",
    # 2.96.0 B (#1941): a table to the other workspace
    "POST /api/sheets/{}/move-space": "sheets",
    "PATCH /api/sheets/{}/columns/{}": "sheets", "PATCH /api/v1/sheets/{}": "sheets", "POST /api/sheets": "sheets",
    "POST /api/sheets/{}/batches/{}/undo": "sheets", "POST /api/sheets/{}/cells/{}/freeze": "sheets",
    "POST /api/sheets/{}/cells/{}/name": "sheets", "POST /api/sheets/{}/columns": "sheets",
    "POST /api/sheets/{}/columns/{}/restore": "sheets", "POST /api/sheets/import": "sheets",
    "POST /api/sheets/{}/links/{}/redo": "sheets", "POST /api/sheets/{}/links/{}/undo": "sheets",
    "POST /api/sheets/{}/presence": "sheets", "POST /api/sheets/{}/restore": "sheets",
    "POST /api/sheets/{}/rows": "sheets", "POST /api/sheets/{}/rows-from-list": "sheets",
    "POST /api/sheets/{}/rows/order": "sheets", "POST /api/sheets/{}/rows/{}/restore": "sheets",
    "POST /api/sheets/{}/to-offer": "sheets", "POST /api/sheets/{}/to-tasks": "sheets", "POST /api/v1/sheets": "sheets",
    "POST /api/v1/sheets/{}/batches/{}/undo": "sheets", "POST /api/v1/sheets/{}/columns": "sheets",
    "POST /api/v1/sheets/{}/rows": "sheets", "PUT /api/sheets/{}/cells": "sheets", "PUT /api/v1/sheets/{}/cells": "sheets",
    "DELETE /api/v1/team/messages/{}": "team", "GET /api/avatar/{}/{}.jpg": "team", "GET /api/disc": "team",
    "GET /api/e2e/keys": "team", "GET /api/e2e/pub/{}": "team", "GET /api/team": "team",
    "GET /api/team/rooms/{}/messages": "team", "GET /api/users": "team", "GET /api/v1/team/rooms": "team",
    "GET /api/v1/team/rooms/{}/messages": "team", "PATCH /api/team/messages/{}": "team", "PATCH /api/users/{}": "team",
    "PATCH /api/v1/team/messages/{}": "team", "POST /api/disc/blocks/{}": "team", "POST /api/disc/check": "team",
    "POST /api/disc/confirm": "team", "POST /api/disc/connections/{}/restore": "team", "POST /api/disc/find": "team",
    "POST /api/disc/requests": "team", "POST /api/disc/requests/{}/{}": "team", "POST /api/team/dm": "team",
    "POST /api/team/messages/{}/pin": "team", "POST /api/team/messages/{}/reactions": "team",
    "POST /api/team/rooms/{}/e2e": "team", "POST /api/team/rooms/{}/messages": "team", "POST /api/team/rooms/{}/read": "team",
    "POST /api/users": "team", "POST /api/users/{}/approve": "team", "POST /api/users/{}/invite": "team",
    "POST /api/users/{}/signin-link": "team", "POST /api/v1/team/dm": "team", "POST /api/v1/team/messages/{}/pin": "team",
    "POST /api/v1/team/messages/{}/reactions": "team", "POST /api/v1/team/rooms/{}/messages": "team",
    "POST /api/v1/team/rooms/{}/read": "team", "PUT /api/disc": "team", "PUT /api/e2e/keys": "team",
    # ---- time (28)
    "DELETE /api/habits/{}": "time", "DELETE /api/time/entries/{}": "time", "DELETE /api/v1/habits/{}": "time",
    "DELETE /api/v1/time/entries/{}": "time", "DELETE /api/v1/time/timer": "time", "GET /api/time/entries": "time",
    "GET /api/time/export.csv": "time", "GET /api/time/gaps": "time", "GET /api/time/report": "time",
    "GET /api/v1/habits": "time", "GET /api/v1/time/check": "time", "GET /api/v1/time/entries": "time",
    "GET /api/v1/time/from-events": "time", "GET /api/v1/time/gaps": "time", "GET /api/v1/time/timer": "time",
    "PATCH /api/habits/{}": "time", "PATCH /api/time/entries/{}": "time", "PATCH /api/v1/habits/{}": "time",
    "PATCH /api/v1/time/entries/{}": "time", "POST /api/habits": "time", "POST /api/habits/{}/log": "time",
    "POST /api/time/entries": "time", "POST /api/time/start": "time", "POST /api/time/stop": "time",
    "POST /api/v1/habits": "time", "POST /api/v1/habits/{}/checkin": "time", "POST /api/v1/time/entries": "time",
    "POST /api/v1/time/timer": "time",
    # ---- token (3)
    "POST /api/hooks/deploy/{}/{}": "token", "POST /api/hooks/git/{}": "token", "POST /api/hooks/issues/{}/{}": "token",
    # ---- wiki (20)
    "DELETE /api/wiki/pages/{}": "wiki", "GET /api/wiki": "wiki", "GET /api/wiki/e2e": "wiki",
    "GET /api/wiki/e2e/todo": "wiki", "GET /api/wiki/export": "wiki", "GET /api/wiki/mentions": "wiki",
    "GET /api/wiki/pages/{}": "wiki", "GET /api/wiki/search": "wiki", "PATCH /api/wiki/pages/{}": "wiki",
    "POST /api/wiki/e2e/bulk": "wiki", "POST /api/wiki/e2e/finish": "wiki", "POST /api/wiki/e2e/keys": "wiki",
    "POST /api/wiki/e2e/rotate": "wiki", "POST /api/wiki/e2e/start": "wiki", "POST /api/wiki/e2e/stop": "wiki",
    "POST /api/wiki/import": "wiki", "POST /api/wiki/move": "wiki", "POST /api/wiki/pages": "wiki",
    # 2.96.0 B (#1941): wiki pages / folders to the other workspace
    "POST /api/wiki/move-space": "wiki",
    "POST /api/wiki/restore": "wiki", "POST /api/wiki/trash": "wiki",
    # 2.90.0 - 2.92.0: bookkeeping, bank, tax dates, invoice series, subscriptions, agreements, equipment, file preview
    "DELETE /api/office/agreements/{}": "office", "DELETE /api/office/series/{}": "office",
    "GET /api/attachments/{}/agents": "tasks", "GET /api/attachments/{}/preview": "tasks",
    "GET /api/files/nodes/{}/preview": "files", "GET /api/list-files/{}/preview": "lists",
    "GET /api/office/agreements": "office", "GET /api/office/agreements/{}": "office",
    "GET /api/office/bank/imports": "office", "GET /api/office/bank/tx": "office",
    "GET /api/office/bank/tx/{}/candidates": "office", "GET /api/office/books": "office",
    "GET /api/office/books/euer": "office", "GET /api/office/books/euer.csv": "office",
    "GET /api/office/books/euer.pdf": "office", "GET /api/office/books/ustva": "office",
    "GET /api/office/equipment/policies": "office", "GET /api/office/equipment/receipts": "office",
    "GET /api/office/equipment/receipts/{}": "office", "GET /api/office/equipment/value": "office",
    "GET /api/office/equipment/value.csv": "office", "GET /api/office/equipment/value.pdf": "office",
    "GET /api/office/series": "office", "GET /api/office/subs": "office", "GET /api/office/subs.csv": "office",
    "GET /api/office/tax-dates": "office", "PATCH /api/office/agreements/{}": "office",
    "PATCH /api/office/series/{}": "office", "POST /api/office/agreements": "office",
    "POST /api/office/agreements/{}/restore": "office", "POST /api/office/bank/import": "office",
    "POST /api/office/bank/import/preview": "office", "POST /api/office/bank/imports/{}/restore": "office",
    "POST /api/office/bank/imports/{}/undo": "office", "POST /api/office/bank/tx/{}/match": "office",
    "POST /api/office/bank/tx/{}/unmatch": "office", "POST /api/office/series": "office",
    "POST /api/office/series/{}/restore": "office", "POST /api/office/series/{}/run": "office",
    "PUT /api/office/tax-dates": "office",
    # 2.93.0 A (#1927): document templates and documents with signature, the personal office of a freelancer in p293_a_api_test.py
    "GET /api/office/doc-templates": "office", "POST /api/office/doc-templates": "office", "PATCH /api/office/doc-templates/{}": "office",
    "DELETE /api/office/doc-templates/{}": "office", "POST /api/office/doc-templates/{}/restore": "office", "GET /api/office/doc-templates/starters": "office",
    "GET /api/office/gen-docs": "office", "POST /api/office/gen-docs": "office", "GET /api/office/gen-docs/{}": "office", "PATCH /api/office/gen-docs/{}": "office",
    "DELETE /api/office/gen-docs/{}": "office", "POST /api/office/gen-docs/{}/restore": "office", "POST /api/office/gen-docs/preview": "office",
    "POST /api/office/gen-docs/{}/final": "office", "GET /api/office/gen-docs/{}/pdf": "office", "POST /api/office/gen-docs/{}/signoff": "office",
    "GET /api/office/gen-docs/{}/signoffs": "office",
    # 2.93.0 B (#1928): the logbook, the personal office of a freelancer in p293_b_api_test.py
    "GET /api/office/vehicles": "office", "POST /api/office/vehicles": "office", "PATCH /api/office/vehicles/{}": "office",
    "GET /api/office/drives": "office", "POST /api/office/drives": "office", "PATCH /api/office/drives/{}": "office", "DELETE /api/office/drives/{}": "office",
    "POST /api/office/drives/{}/restore": "office", "GET /api/office/drives/{}/log": "office", "POST /api/office/drives/{}/trip": "office",
    "GET /api/office/logbook/report": "office", "GET /api/office/logbook.csv": "office", "GET /api/office/logbook.pdf": "office",
    "PUT /api/office/logbook/settings": "office",
    # 2.94.0 (#1930): leads (personal office, p294_a_api_test.py); (#1929): the booking page (own calendar, p294_b_api_test.py),
    # its public pages (a customer without an account, the same for a freelancer's page: p294_b_api_test.py books on one)
    "DELETE /api/appt/types/{}": "pim", "GET /api/appt/bookings": "pim", "GET /api/appt/page": "pim", "GET /api/appt/types": "pim",
    "GET /api/office/deals/{}/convert": "office", "GET /api/v1/office/leads": "office", "GET /s/b/c/{}": "link",
    "GET /s/b/x/{}": "link", "GET /s/b/{}": "link", "GET /s/b/{}/{}": "link", "GET /s/b/{}/{}/{}": "link",
    "PATCH /api/appt/types/{}": "pim", "PATCH /api/v1/office/leads/{}": "office", "POST /api/appt/bookings/{}/cancel": "pim",
    "POST /api/appt/types": "pim", "POST /api/appt/types/{}/restore": "pim", "POST /api/office/deals/{}/convert": "office",
    "POST /api/office/deals/{}/unconvert": "office", "POST /api/office/leads/import": "office",
    "POST /api/office/leads/import/undo": "office", "POST /api/v1/office/leads": "office", "POST /s/b/c/{}": "link",
    "POST /s/b/x/{}": "link", "POST /s/b/{}/{}/{}": "link", "PUT /api/appt/page": "pim",
}


def norm(p):
    return re.sub(r"<[^>]+>", "{}", p)


def found_routes():
    src = "\n".join(open(p, encoding="utf-8").read() for p in [os.path.join(ROOT, "app.py")]
                    + sorted(glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)))
    f = {f"{m.upper()} {norm(p)}" for m, p in re.findall(r'^@app\.(get|post|put|patch|delete)\("([^"]*)"', src, re.M)}
    f |= {f"DAV {norm(p)}" for p in re.findall(r'^@app\.route\("([^"]*)"', src, re.M)}  # CalDAV / CardDAV
    return f


def main():
    fails, oks = [], [0]

    def check(cond, what):
        if cond:
            oks[0] += 1
        else:
            fails.append(what)
            print("FAIL:", what, flush=True)

    found = found_routes()
    # ---- 1. every route is classified, nothing stale
    for r in sorted(found - set(ROUTES)):
        check(False, f"route {r} is not in ROUTES: add it with its area (and call it as a freelancer) or an n/a area with the reason")
    for r in sorted(set(ROUTES) - found):
        check(False, f"ROUTES names {r}, which is no route (any more)")
    check(len(found) > 1000, f"routes found: {len(found)}")

    # ---- 2. every area is known; a matrix area is really tested (marker in a suite that runs), an n/a area has a reason
    tests = {os.path.basename(p): open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(N, "*.py"))
             if os.path.basename(p) != os.path.basename(__file__)}
    run_all = open(os.path.join(N, "run_all.sh"), encoding="utf-8").read()
    # a marker line: "freelancer-matrix: area, area, ..." (a comment in the suite, next to the calls of these areas)
    marked = {}
    for name, t in tests.items():
        for line in re.findall(r"freelancer-matrix:([\w ,-]+)", t):
            for k in line.split(","):
                if k.strip():
                    marked.setdefault(k.strip(), set()).add(name)
    for r, k in sorted(ROUTES.items()):
        check(k in KINDS, f"{r}: unknown area {k!r}")
    for k, (what, why) in KINDS.items():
        check(what in ("matrix", "n/a") and len(why) > 20, f"area {k}: needs matrix / n/a and its reason")
        if what == "matrix":
            check(k in marked, f"area {k}: no suite carries the marker 'freelancer-matrix: {k}'")
            for name in sorted(marked.get(k, ())):
                check(re.search(r"\s" + re.escape(name) + r"\b", run_all) is not None,
                      f"area {k}: the suite {name} with its marker does not run in tests/run_all.sh")
        check(k in ROUTES.values(), f"area {k}: no route uses it (stale)")

    n_m = sum(1 for k in ROUTES.values() if KINDS.get(k, ("",))[0] == "matrix")
    print(f"freelancer_coverage: {oks[0]} ok, {len(fails)} failed -- {len(found)} routes, {n_m} checked without an organisation, "
          f"{len(found) - n_m} not relevant (with reason)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
