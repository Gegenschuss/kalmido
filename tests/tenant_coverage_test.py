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
    "chatsave": ("matrix", "p2370_u_api_test.py: saving a chat message of another conversation / into a list of another person (#1159)"),
    "list": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: a list by id (read, change, members, sections, fields, notes, owner)"),
    "folder": ("matrix", "p2300_tenant_test.py: folder settings / people / groups are the own folders' only"),
    "news": ("matrix", "p2280_api_test.py: News of other workspaces"),
    "lytpl": ("matrix", "p255_a_api_test.py: arrangement templates only to people of the own organisations, never to agents, a project page only with access (#1068)"),
    "team": ("matrix", "p2280_api_test.py: team chat rooms and direct messages"),
    "agent": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: agents, their chat, events and jobs"),
    "people": ("matrix", "p2280_api_test.py, p2300_tenant_test.py: the user list, user changes, invitations / sign-in links by id"),
    "org": ("matrix", "p2280_api_test.py: organisations, their members and admins; p2115_b_api_test.py: invitations by e-mail (2.115.0); "
                   "p2146_d_api_test.py: the retention export of another organisation 404 (2.146.0)"),
    "calendar": ("matrix", "p2300_tenant_test.py: calendars by id, sharing (B2), workspace (B3); p294_b_api_test.py (the booking page: types / bookings of another person 404, the public pages); "
                 "p2111_b_api_test.py (invitation marks and subscription links of another person's calendar 404, a link ends with the sharing)"),
    "event": ("matrix", "p2300_tenant_test.py: events by id, ranges, invitations"),
    "book": ("matrix", "p2300_tenant_test.py: address books by id, sharing (B2), workspace (B3)"),
    "contact": ("matrix", "p2300_tenant_test.py: contacts by id, links to tasks"),
    "dav": ("matrix", "p2300_tenant_test.py: CalDAV / CardDAV collections of others"),
    "ical": ("matrix", "p2300_tenant_test.py: the calendar feed has only visible tasks; p2111_b_api_test.py: the event calendar feed only while its person sees the calendar"),
    "group": ("matrix", "p2300_tenant_test.py: groups without a visible member stay unknown (B1)"),
    "template": ("matrix", "p2300_tenant_test.py: templates by id, from / into lists of others"),
    "form": ("matrix", "p2300_tenant_test.py: forms by id, the form page for another organisation"),
    # 2.63.0 B (#1513): customer reports: the status page / the portal never across organisations, a task's ticket by id
    "portal": ("matrix", "p263_b_api_test.py: status links and the portal show one space's tickets only, a task's ticket by id"),
    "client": ("matrix", "p2300_tenant_test.py: clients by id, workload"),
    # 2.36.1 (#1021): office & finance -- every row belongs to an organisation (org_id), read through office_org (the workspace
    # one works in); foreign ids 404; agents and kids 403 before any query; 2.47.3 (#1360): a private person works in the own
    # personal office (a hidden area only its owner reaches). No /api/v1, no MCP in stage 1
    "office": ("matrix", "p2361_b_api_test.py (settings, master data, import / export), p2361_c_api_test.py (documents), p2361_d_api_test.py (logo, PDF), p2362_e_api_test.py (finalising, company fields, office log), p2380_a_api_test.py (invoices, payments, reminders), p2391_f_api_test.py (legacy import, archive), p2473_a_api_test.py (the personal office: a second person, row-level security, Private vs. organisation), p2473_b_api_test.py (travel expenses, cash flow), p2473_e_api_test.py (DATEV booking batch), p250_b_api_test.py (sales pipeline, business figures), p251_a_api_test.py (agents in the office: drafts, payment suggestions), p290_a_api_test.py (bookkeeping light), p290_b_api_test.py (bank reconciliation), p290_c_api_test.py (tax dates), p291_a_api_test.py (invoice series), p291_b_api_test.py (subscriptions and tools), p292_a_api_test.py (business contracts and insurances), p292_b_api_test.py (equipment value, insurance list), p293_a_api_test.py (document templates, signature), p293_b_api_test.py (logbook), p294_a_api_test.py (leads), p295_a_api_test.py (per diem, its report), p295_b_api_test.py (per diem spreadsheet import), p2113c_a_api_test.py (terms and conditions as PDF)"),
    # 2.48.0 (#1111): documents = files of the file store (fs_visible_sql / need_node) + their recognition rows; labels, rules,
    # models, settings and the mail address belong to one workspace (private or an organisation, admins change it)
    "document": ("matrix", "p248_b_api_test.py: another organisation / person: 404 on a document, nothing in list, search, filter labels; settings and upload only for the own workspace; agents only with a share; "
                           "p2122_b_api_test.py (2.122.0): bulk change, ZIP and the new filters / search syntax never reach another workspace"),
    # 2.48.0 (#1207 / #1152 / #1356): the file store (fs_role / need_node / fs_visible_sql, org boundary before shares), the
    # Paperless-ngx connection of one workspace, receipt data / agent suggestions on a visible document
    "file_request": ("matrix", "p2122_a_api_test.py: a file request of another organisation's folder (list, create, change, remove): 404; the link writes only into its own folder as its creator, the page shows nothing of the folder (2.122.0 A, #2097)"),
    "file": ("matrix", "p248_a_api_test.py: a node of another organisation / person: 404 (read, list, content, versions, share, move); shares only to people and agents of the node's workspace; "
                       "p2122_b_api_test.py (2.122.0): tags of a node and the tag filter of a space"),
    "paperless": ("matrix", "p248_d_paperless_api_test.py: the connection of another workspace: 404; organisation admins only change it; agents never"),
    # 2.55.0 (#1455): the newsletter connection of one workspace (segments, log, sync) + the consent of a contact
    "newsletter": ("matrix", "p255_e_api_test.py: the connection, segments, log and sync of another workspace: 404 / 403; organisation admins only; agents never; consent only on writable contacts; address books of other workspaces refused in a segment"),
    # 2.75.0 (#1411): the built-in assistant: a person's shares of visible lists, tasks only of shared lists / the own basket
    "assistant": ("matrix", "p275_a_api_test.py: another person's task / basket item / list 404 or left out; shares of lists the person no longer sees dropped; the log only own rows; agents never"),
    "receipt": ("matrix", "p248_d_receipts_api_test.py: receipt data and suggestions only on a visible document; projects of another workspace refused; outsiders 404"),
    "webhook": ("matrix", "p2300_tenant_test.py: webhooks by id, deliveries only of visible tasks; p2115_a_api_test.py: an organisation's webhooks only for its admins, never events of a member's private list"),
    "channel": ("matrix", "p2142_a_api_test.py (2.142.0): a channel of another person / organisation by id: 404; an organisation's channels only for its admins; "
                          "its messages never of a private list, a list shared only with some, another organisation or the words of a locked list"),
    "export": ("matrix", "p2300_tenant_test.py: the export has only the own data"),
    "stats": ("matrix", "p2300_tenant_test.py: statistics count only own / visible tasks"),
    "publiclink": ("matrix", "p2300_tenant_test.py: the public link of another person's list by id"),
    # 2.50.0 (#329, #1200): files / logo of a customer view, approval links of quotations and lists (and their customer pages)
    "video": ("matrix", "p2991_a_api_test.py: a video sign-off of another organisation / person / task / client by id: 404 (read, change, versions, "
              "comments, export, customer link, move); 2.99.1 A (#1959); p2991_c_api_test.py: the API v1 for agents -- "
              "only reviews at a task / list shared with the agent, never another workspace, a client's review or a health list"),
    "signoff": ("matrix", "p250_c_api_test.py: approval links of another organisation's quotation / another person's list by id, "
                          "files of other lists through a link"),
    # 2.89.0 C (#1916): tables through the REST API and as files: an agent sees only tables attached to a list shared with it
    # and its own; values of Kalmido variables with its visibility; export / import only of / into a table one may read / write
    "sheet_v1": ("matrix", "p289_c_api_test.py: a table of another organisation / person 404 for the stranger and the stranger's agent "
                           "(list, read, export, cells, rows, columns, undo), an agent without a shared list sees nothing, a variable "
                           "of a list not shared with the agent is denied, an import into another workspace 404"),
    # 2.49.0 (#1199 / #1201): knowledge pages belong to one organisation (every member) or one person (org_id NULL, owner_id)
    "wiki": ("matrix", "p249_c_api_test.py: a page of another organisation / person: 404 (read, change, delete, move, trash, search, export, mentions); "
                       "p299_a_api_test.py: page files (read, upload, delete, trash); p2123_b_api_test.py: shares of pages / folders (list, "
                       "create, change, revoke, restore, the guest routes; the public page only through its token); p2123_a_api_test.py: page history (list, read, restore)"),
    # 2.89.0 (#1916): tables belong to one organisation (every member) or one person (org_id NULL, owner_id); attached to a list
    # the list decides; Kalmido variables in formulas are evaluated per viewer (a source they may not see: "denied", no name / value)
    "sheet": ("matrix", "p289_a_api_test.py: a table of another organisation / person / list: 404 (read, change, cells, columns, rows, "
                        "trash, presence, completion); a formula's source of another workspace cannot be chosen and shows no value"),
    # 2.124.0 C (#2113): one table shared with single people / agents (sheets/shshare.py): only people / agents of the table's
    # workspace, a stranger and a stranger's agent 404, an agent of another organisation never, leaving / moving ends the share
    "sheet_share": ("matrix", "p2124_c_api_test.py: shares of a table of another organisation / person: 404 for the stranger "
                              "(list, add, change, stop), a person / agent of another workspace cannot get a share (409), a recipient "
                              "sees only the shared table, not the rest of the workspace"),
    # 2.125.0 B (#2119): monthly timesheets: the person's own month, the admins of the sheet's organisation decide
    "timesheet": ("matrix", "p2125_b_api_test.py: a timesheet of another organisation's member: 404 for its admin, 403 for a "
                            "member of the same organisation, a person without organisation: no decision by anyone (404)"),
    # 2.97.0 A (#1950): bookmarks belong to one organisation (every member reads, the owner / its admins change) or one person
    "bookmark": ("matrix", "p297_a_api_test.py: a bookmark of another organisation / person: 404 (read, change, delete, picture, move)"),
    # 2.98.0 A (#1953): scheduling polls belong to one organisation (every member reads, the owner / its admins change) or one person
    "poll": ("matrix", "p298_a_api_test.py: a poll of another organisation / person: 404 (read, change, delete, choose, move, list); "
                       "the public link reads inside the poll's organisation only"),
    # ---- not relevant for the boundary between organisations (with the reason)
    "auth": ("n/a", "signing in, setting up and securing the own account (before a session or about the session's own person)"),
    "own": ("n/a", "the person's own rows only (settings, devices, tokens, habits, time, filters, imports, Home & life, their own "
                   "connections): read and written as user_id = me, never shared; a task / list named in them is checked with "
                   "need_task / need_list (covered by the task / list matrix)"),
    # 2.102.0 (#1999)
    "clienterr": ("n/a", "the web app's own unexpected error (message cut of data, place in the code, version, area): written as "
                         "nobody into the one project list the server operator chose, nothing is read back or answered"),
    "admin": ("n/a", "the operator's administration (need_admin): server settings, backups, alerts, agents, integrations; the operator "
                     "is trusted with the whole server (architecture review 2.1 / B4); people in it are filtered by visible_people"),
    # 2.144.0 D (#797)
    "operator": ("n/a", "the hosting operator's interface (a token from a file, off by default, never a person or a session): "
                        "instance-wide numbers and operating actions only, no content of any person or organisation (p2144_d_api_test.py)"),
    "public": ("n/a", "pages and facts without data of a person (app shell, health, version, robots, manifest, QR code of a given text)"),
    "family": ("n/a", "the household of the Family module: private by definition (kid_parents), never an organisation's object"),
    "pure": ("n/a", "a pure transformation of the request body (an outline file into a tree): no stored data is read or written"),
    "token": ("n/a", "an inbound hook addressed by the unguessable secret of one list (sealed, looked up by its hash): nothing to "
                     "guess by id"),
    # 2.49.0 (#1106): finding people by e-mail (accounts/discover.py) -- its own kind (a second "people" key here silently
    # replaced the matrix kind of the user list above)
    "discover": ("n/a", "finding people by e-mail and connection requests: person to person, outside every workspace; the "
                      "person's own requests / connections / blocks only, a hit only through an exact confirmed address "
                      "(p249_e_api_test.py: no account disclosure, no probing by id, organisations unchanged)"),
    # 2.50.0 A (#1195, #1194): absences and bookings of an organisation / a personal area (row-level security + the app)
    "hub": ("matrix", "p250_a_api_test.py: absences and bookings by id of another organisation 404 (read, change, delete, restore), "
                      "the kind of an absence only for the person and the admins, resources of another organisation cannot be booked; "
                      "p2125_a_api_test.py (2.125.0): vacation accounts, requests, decisions and the working week of another "
                      "organisation's people 404, requests never seen by the team or agents"),
    # 2.59.0 B (#1375): related tasks -- candidates only among the tasks the asker sees
    "related": ("matrix", "p259_b_api_test.py: related tasks, the hint while adding, search semantic=1, API v1 and agent events never "
                          "name a task of another organisation, an unshared list or a private list; another organisation's task 404"),
    # 2.71.0 B (#1459): a task shown in further lists (task_links); rights stay with the task's own list
    "tasklink": ("matrix", "p271_b_api_test.py: linking into a list of another organisation / private <-> organisation refused, "
                           "a reader of only the further list gets the task nowhere (state, search, feed, public link, agent), "
                           "\"also\" names only visible lists"),
    # 2.72.0 (#1333): the household budget
    # 2.140.0 B (#2136): a private device linked with office equipment (life/devlink.py)
    "devlink": ("matrix", "p2140_b_api_test.py: another person's device, link or equipment of another office area 404; taking over "
                          "into an organisation only as its admin (403); a link of another person never shows on the equipment"),
    "budget": ("matrix", "p272_a_budget_api_test.py: categories, entries, templates, contracts, import and receipts by id of another "
                         "person's budget 404, read-only shared = no change, agents / tokens without the scope private never"),
    # 2.73.0 A (#661): the accounts of one person on other Kalmido servers (accounts/servers.py) -- private per person
    "servers": ("matrix", "p273_a_api_test.py: the server accounts of another person 404 (read, change, delete, restore, data, tasks, move); agents 403; nothing of another person's tasks moves"),
    # 2.84.0 A (#1198): mails filed with a client / project (hub/hubmail.py hbm_can: the client / list / recipient, always in the mail's workspace)
    "hubmail": ("matrix", "p284_a_api_test.py: a mail / attachment / address of another organisation or a private client of another person 404, a forged sender finds only the recipient's workspace, after leaving nothing, assigning across workspaces refused, agents 403; "
                "p2141_a_api_test.py (2.141.0): another organisation's mailbox 404, a member 403, a workspace mailbox files into its own workspace only (a foreign token counts as none), compose / send for another organisation's mail or client 404, agents 403; "
                "2.141.0 B: p2141_b_api_test.py the HTML view / task / event from a mail of another organisation 404, into a list / calendar of another workspace 409, the mail of a task only with the mail's rights"),
    # 2.112.1 B (#2058): external share links of the file store (files/extlinks.py)
    "fileextlink": ("matrix", "p21121_b_api_test.py: the links of another organisation's / person's node 404 (list, create, renew, revoke, "
                              "restore); a link serves only its own tree (other ids 404); dead when the creator leaves / loses the right"),
}

ROUTES = {
    # ---- admin (40)
    "PUT /api/admin/oidc": "admin", "POST /api/admin/oidc/check": "admin", "GET /api/admin/storage-check": "admin",
    "GET /api/admin/backups": "admin", "PATCH /api/admin/backups": "admin", "POST /api/admin/backups": "admin",
    "GET /api/admin/backups/{}/download": "admin", "DELETE /api/admin/backups/{}": "admin",
    "POST /api/admin/backups/{}/verify": "admin", "POST /api/admin/backups/upload": "admin",
    "POST /api/admin/backups/restore": "admin",
    # 2.143.0 B (#2152): the off-site target of the backups (instance admins, p2143_b_api_test.py)
    "GET /api/admin/backups/offsite": "admin", "PATCH /api/admin/backups/offsite": "admin",
    "POST /api/admin/backups/offsite/test": "admin", "POST /api/admin/backups/offsite/upload": "admin",
    "PUT /api/admin/announcement": "admin",
    # 2.144.0 D (#797): the hosting operator's interface (a token from a file, off by default)
    "GET /api/operator/status": "operator", "POST /api/operator/setup-code": "operator", "PUT /api/operator/notice": "operator",
    "PUT /api/v1/admin/announcement": "admin", "GET /api/admin/agents": "admin", "POST /api/admin/agents": "admin",
    "PATCH /api/admin/agents/{}": "admin", "POST /api/admin/agents/{}/reset": "admin",
    "POST /api/admin/agents/{}/avatar": "admin", "POST /api/admin/agents/{}/token": "admin",
    "POST /api/admin/agents/{}/secret": "admin", "POST /api/admin/agents/{}/test": "admin",
    "GET /api/admin/agent-policy": "admin", "PUT /api/admin/agent-policy": "admin", "DELETE /api/admin/agents/{}": "admin",
    "GET /api/admin/agents/audit": "admin", "GET /api/admin/agents/{}/audit": "admin",
    "GET /api/v1/admin/agents/{}/audit": "admin", "GET /api/v1/admin/status": "admin", "GET /api/v1/admin/orgs/activity": "admin", "GET /api/admin/orgs/activity": "admin",
    "PATCH /api/admin/settings": "admin", "POST /api/admin/setup": "admin", "POST /api/admin/mail/poll": "admin",
    "GET /api/admin/lists/orphaned": "admin", "GET /api/admin/alerts": "admin",
    "PATCH /api/admin/alerts": "admin", "POST /api/admin/alerts/test": "admin", "DELETE /api/admin/alerts": "admin",
    # ---- agent (44)
    "GET /api/agents/{}/bridges": "agent", "POST /api/v1/agent/chats/{}/messages/{}/withdraw": "agent",  # 2.30.0 (#919 / #1037)
    "GET /api/my/agents": "agent", "POST /api/my/agents": "agent", "PATCH /api/my/agents/{}": "agent",
    "PATCH /api/agents/{}/color": "agent",  # 2.47.1 (#1721): also p247c_b_api_test.py
    "POST /api/agents/{}/chat/{}/pin": "agent", "POST /api/v1/agent/chats/{}/messages/{}/pin": "agent",  # 2.62.0 (#1848): also p262_a_api_test.py
    "POST /api/my/agents/{}/token": "agent", "DELETE /api/my/agents/{}": "agent", "GET /api/v1/agent": "agent",
    "PUT /api/v1/agent/status": "agent", "GET /api/v1/agent/events": "agent", "GET /api/v1/agent/jobs": "agent",
    "POST /api/v1/agent/jobs": "agent", "PATCH /api/v1/agent/jobs/{}": "agent", "GET /api/agents": "agent",
    "GET /api/agents/jobs": "agent", "POST /api/agents/jobs/{}/action": "agent",
    "POST /api/agents/{}/chat/{}/choice": "agent", "PUT /api/agents/{}/permission-mode": "agent",
    "GET /api/agents/{}/chat": "agent", "POST /api/agents/{}/chat": "agent",
    # 2.98.0 A (#1953): scheduling polls (p298_a_api_test.py) - routes below this line
    "GET /api/polls": "poll", "POST /api/polls": "poll", "GET /api/polls/{}": "poll", "PATCH /api/polls/{}": "poll",
    "DELETE /api/polls/{}": "poll", "POST /api/polls/{}/restore": "poll", "POST /api/polls/{}/decide": "poll",
    "POST /api/polls/{}/reopen": "poll", "POST /api/polls/{}/move-space": "poll", "GET /s/v/{}": "poll", "POST /s/v/{}": "poll",
    "GET /s/v/time.js": "public",
    # (2.98.0 spacer A)
    # 2.98.0 B (#1954): questionnaires (p298_b_api_test.py) - routes below this line
    "GET /api/forms/{}/entries": "form", "GET /api/forms/{}/entries.csv": "form",
    # 2.102.0 C (#2201): the client link of a questionnaire (p2102_c_api_test.py)
    "GET /api/forms/{}/client-link": "form", "GET /api/clients/{}/forms": "client",
    # (2.98.0 spacer B)
    # 2.98.0 C (#2180 #2181): office menu, tables (p298_c_ui.js) - routes below this line
    # (2.98.0 spacer C)
    # 2.98.0 D (#2163 #2178 #2184): polish (p298_d_api_test.py) - routes below this line
    # (2.98.0 spacer D)
    # 2.111.0 A (#2233): undo of the office editors (p2111_a_api_test.py) - routes below this line
    "POST /api/office/undo/{}/{}": "office",
    # (2.111.0 spacer A)
    "DELETE /api/agents/{}/chat": "agent", "DELETE /api/agents/{}/chat/{}": "agent",  # 2.103.0 D (#2175): p2103_d_api_test.py
    # 2.97.0 A (#1950): bookmarks (p297_a_api_test.py) - routes below this line
    "GET /api/bookmarks": "bookmark", "POST /api/bookmarks": "bookmark", "GET /api/bookmarks/{}": "bookmark",
    "PATCH /api/bookmarks/{}": "bookmark", "DELETE /api/bookmarks/{}": "bookmark", "POST /api/bookmarks/{}/restore": "bookmark",
    "POST /api/bookmarks/{}/refresh": "bookmark", "GET /api/bookmarks/{}/image": "bookmark",
    "POST /api/bookmarks/move-space": "bookmark",
    # 2.96.0 C (#2015): job cards in the agent chat (p296_c_api_test.py)
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
    "GET /api/state/delta": "aggregate",  # 2.42.0 (#1376): the changed tasks of /api/state (same query; gone only of seen lists)
    "GET /api/dayplan": "aggregate", "GET /api/dayplan/review": "aggregate", "GET /api/v1/dayplan": "aggregate",
    "GET /api/v1/dayplan/review": "aggregate", "GET /api/deps": "aggregate", "POST /api/tasks/purge-done": "aggregate",
    "DELETE /api/trash": "aggregate", "GET /api/roadmap": "aggregate",
    # 2.102.0 A (#1988): the list trash -- only lists the person may restore (otr_can: owner / list admin / the org's admins,
    # members only), by id the same 404 for every other list (p2102_a_api_test.py)
    "GET /api/trash/lists": "aggregate", "POST /api/trash/lists/{}/restore": "list", "DELETE /api/trash/lists/{}": "list",
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
    # 2.115.0 B (#2062): the own sessions (user_id = me; p2115_b_api_test.py: a foreign session id is 404)
    "GET /api/me/sessions": "auth", "DELETE /api/me/sessions/{}": "auth", "POST /api/me/sessions/others": "auth",
    "GET /api/auth/oidc/callback": "auth", "POST /api/auth/signup": "auth", "POST /api/auth/link": "auth",
    # ---- book (16)
    "GET /api/v1/address-books": "book", "POST /api/v1/address-books": "book", "PATCH /api/v1/address-books/{}": "book",
    "DELETE /api/v1/address-books/{}": "book", "PUT /api/v1/address-books/{}/members/{}": "book",
    "DELETE /api/v1/address-books/{}/members/{}": "book", "POST /api/v1/address-books/{}/import": "book",
    "GET /api/v1/address-books/{}/export": "book", "GET /api/books": "book", "POST /api/books": "book",
    "PATCH /api/books/{}": "book", "DELETE /api/books/{}": "book", "PUT /api/books/{}/members": "book",
    "DELETE /api/books/{}/members/{}": "book", "POST /api/books/{}/import": "book", "GET /api/books/imports/{}": "own",  # 2.41.0 (#1437): only the starter's own import
    "GET /api/books/{}/export.vcf": "book",
    "GET /api/books/{}/export.csv": "book",  # 2.119.1 A (#2080): like the vCard export (p21191_a_api_test.py)
    "POST /api/books/{}/org": "book", "PATCH /api/books/{}/org": "book", "DELETE /api/books/{}/org": "book",  # 2.52.0 (#1438)
    # ---- calendar (16)
    "POST /api/evcals/{}/import": "calendar", "GET /api/v1/event-calendars": "calendar",
    "POST /api/v1/event-calendars": "calendar", "PATCH /api/v1/event-calendars/{}": "calendar",
    "DELETE /api/v1/event-calendars/{}": "calendar", "PUT /api/v1/event-calendars/{}/members/{}": "calendar",
    "DELETE /api/v1/event-calendars/{}/members/{}": "calendar", "POST /api/v1/event-calendars/{}/import": "calendar",
    "GET /api/v1/event-calendars/{}/export": "calendar", "GET /api/evcals": "calendar", "POST /api/evcals": "calendar",
    "PATCH /api/evcals/{}": "calendar", "DELETE /api/evcals/{}": "calendar", "PUT /api/evcals/{}/members": "calendar",
    "DELETE /api/evcals/{}/members/{}": "calendar", "GET /api/evcals/{}/export.ics": "calendar",
    "GET /api/evinvite": "calendar", "GET /api/evcals/{}/feed": "calendar", "POST /api/evcals/{}/feed": "calendar",  # 2.111.0 B (#2056)
    # ---- chatfile (4)
    "GET /api/chat-files/{}": "chatfile", "DELETE /api/chat-files/{}": "chatfile",
    "POST /api/chat-save": "chatsave",  # 2.37.0 (#1159)
    "GET /api/v1/chat-attachments/{}": "chatfile", "DELETE /api/v1/chat-attachments/{}": "chatfile",
    # ---- client (13)
    "GET /api/clients": "client", "GET /api/clients/{}": "client", "POST /api/clients": "client",
    "PATCH /api/clients/{}": "client", "DELETE /api/clients/{}": "client", "GET /api/v1/clients": "client",
    "POST /api/clients/bulk": "client", "POST /api/v1/clients/bulk": "client",  # 2.47.3 (#1733): every id checked first (p2473_c_api_test.py)
    "GET /api/clients/{}/book-contacts": "client",  # 2.59.0 (#1735): only the client's own address books (p259_a_api_test.py)
    "POST /api/clients/merge": "client", "POST /api/clients/merges/{}/undo": "client",  # 2.66.0 (#1835): every client checked, one workspace, undo by its scope (p266_b_api_test.py)
    "POST /api/v1/clients": "client", "GET /api/v1/clients/{}": "client", "PATCH /api/v1/clients/{}": "client",
    "DELETE /api/v1/clients/{}": "client", "GET /api/v1/workload": "client", "GET /api/workload": "client", "GET /api/workload/export.xlsx": "client",
    "PUT /api/workload/capacity/{}": "client",
    # ---- office (B: settings, packs, master data, import / export)
    "GET /api/office/settings": "office", "PUT /api/office/settings": "office", "GET /api/office/number-preview": "office",
    "GET /api/office/packs": "office", "GET /api/office/packs/{}": "office", "POST /api/office/packs/validate": "office",
    "GET /api/office/pack-switch": "office",  # 2.147.0 (#2462): the warning before a country pack change, admin (p2147_a_api_test.py)
    # 2.76.0 (#1023): the pack catalogue (p276_a_packs_api_test.py carries the office marker)
    "GET /api/office/catalog": "office", "POST /api/office/catalog/refresh": "office", "POST /api/office/packs/install": "office",
    "DELETE /api/office/packs/installed/{}/{}": "office", "POST /api/office/packs/installed/{}/{}/restore": "office",
    "GET /api/office/{}": "office", "POST /api/office/{}": "office", "GET /api/office/{}/{}": "office", "PATCH /api/office/{}/{}": "office",
    "DELETE /api/office/{}/{}": "office", "GET /api/office/export": "office", "POST /api/office/import": "office",
    "POST /api/office/move": "office",  # 2.47.3 (#1360): the personal office becomes an organisation (p2473_a_api_test.py)
    # 2.90.0 B (#1921): bank reconciliation, office admins (p290_b_api_test.py)
    "POST /api/office/bank/import/preview": "office", "POST /api/office/bank/import": "office", "GET /api/office/bank/imports": "office",
    "POST /api/office/bank/imports/{}/undo": "office", "POST /api/office/bank/imports/{}/restore": "office", "GET /api/office/bank/tx": "office",
    "GET /api/office/bank/tx/{}/candidates": "office", "POST /api/office/bank/tx/{}/match": "office", "POST /api/office/bank/tx/{}/unmatch": "office",
    # 2.47.3 (#1022, #1652): travel expenses and the cash flow, admins of the office area only (p2473_b_api_test.py: other org 404, member 403)
    "GET /api/office/trips": "office", "POST /api/office/trips": "office", "PATCH /api/office/trips/{}": "office", "DELETE /api/office/trips/{}": "office",
    "POST /api/office/trips/{}/items": "office", "PATCH /api/office/trips/{}/items/{}": "office", "DELETE /api/office/trips/{}/items/{}": "office",
    "GET /api/office/trips/report": "office", "GET /api/office/trips/bill-docs": "office", "POST /api/office/trips/bill": "office", "GET /api/office/receipts/billed": "office", "POST /api/office/receipts/bill": "office",
    "POST /api/office/receipts/unbill": "office",
    "POST /api/office/trips/unbill": "office", "GET /api/office/cashflow": "office", "GET /api/office/fixed-costs": "office",
    # 2.95.0 A (#1932): the per diem report and the rates, office admins (p295_a_api_test.py)
    "GET /api/office/trips/vma-rates": "office", "GET /api/office/trips/vma": "office", "GET /api/office/trips/vma.pdf": "office",
    "GET /api/office/trips/vma.xlsx": "office", "GET /api/office/trips/vma.csv": "office",
    # 2.95.0 B (#1932): the import of a per diem spreadsheet, office admins (p295_b_api_test.py)
    "POST /api/office/trips/import/preview": "office", "POST /api/office/trips/import": "office", "POST /api/office/trips/delete": "office",
    # 2.117.0 A (#2292): own purposes of trips, office admins (p2117_a_api_test.py)
    "GET /api/office/trips/purposes": "office", "POST /api/office/trips/purposes": "office", "PATCH /api/office/trips/purposes/{}": "office",
    "DELETE /api/office/trips/purposes/{}": "office",
    "GET /api/office/meals": "office", "POST /api/office/meals": "office", "GET /api/office/meals/{}": "office",  # 2.119.0 A (#2288): entertainment receipts
    "PATCH /api/office/meals/{}": "office", "DELETE /api/office/meals/{}": "office", "POST /api/office/meals/{}/restore": "office",
    "POST /api/office/meals/{}/approve": "office", "POST /api/office/meals/{}/unlock": "office", "POST /api/office/meals/{}/file": "office",
    "GET /api/office/meals/{}/file/{}": "office", "DELETE /api/office/meals/{}/file/{}": "office",
    "POST /api/office/meals/{}/file/{}/restore": "office", "GET /api/office/meals/{}/pdf": "office", "GET /api/office/meals/report": "office",
    "GET /api/office/meals/choices": "office", "POST /api/office/meals/choices": "office", "PATCH /api/office/meals/choices/{}": "office",
    "DELETE /api/office/meals/choices/{}": "office",
    "POST /api/office/fixed-costs": "office", "PATCH /api/office/fixed-costs/{}": "office", "DELETE /api/office/fixed-costs/{}": "office",
    # 2.67.0 (#1838): the import of fixed costs, its template, the undo of an import, the monthly check task (office admins)
    "POST /api/office/fixed-costs/import/preview": "office", "POST /api/office/fixed-costs/import": "office", "GET /api/office/fixed-costs/import/template": "office",
    "POST /api/office/fixed-costs/delete": "office", "GET /api/office/cashflow/check": "office", "PUT /api/office/cashflow/check": "office",
    # 2.91.0 A (#1923): invoice series, office admins (p291_a_api_test.py)
    "GET /api/office/series": "office", "POST /api/office/series": "office", "PATCH /api/office/series/{}": "office",
    "DELETE /api/office/series/{}": "office", "POST /api/office/series/{}/restore": "office", "POST /api/office/series/{}/run": "office",
    # 2.91.0 B (#1924): subscriptions and tools, office admins (p291_b_api_test.py)
    "GET /api/office/subs": "office", "GET /api/office/subs.csv": "office",
    "POST /api/office/docs/{}/cashflow": "office",  # 2.88.0 (#1915)
    # 2.90.0 C (#1922): tax dates as tasks, office admins (p290_c_api_test.py)
    "GET /api/office/tax-dates": "office", "PUT /api/office/tax-dates": "office",
    # 2.92.0 A (#1925): business contracts and insurances (office admins; p292_a_api_test.py)
    "GET /api/office/agreements": "office", "POST /api/office/agreements": "office", "GET /api/office/agreements/{}": "office",
    "PATCH /api/office/agreements/{}": "office", "DELETE /api/office/agreements/{}": "office", "POST /api/office/agreements/{}/restore": "office",
    # 2.92.0 B (#1931): equipment value, depreciation, insurance list (office admins; p292_b_api_test.py)
    "GET /api/office/equipment/value": "office", "GET /api/office/equipment/value.csv": "office", "GET /api/office/equipment/value.pdf": "office",
    "GET /api/office/equipment/policies": "office", "GET /api/office/equipment/receipts": "office", "GET /api/office/equipment/receipts/{}": "office",
    # 2.92.0 C (#1926): file preview / text of docx and xlsx, summarise by an agent (p292_c_api_test.py)
    "GET /api/attachments/{}/preview": "attachment", "GET /api/attachments/{}/agents": "attachment",
    "GET /api/list-files/{}/preview": "attachment", "GET /api/files/nodes/{}/preview": "file",
    # 2.122.0 A (#2097): file requests of a folder and their public page
    "GET /api/files/nodes/{}/requests": "file_request", "POST /api/files/nodes/{}/requests": "file_request",
    "PATCH /api/files/requests/{}": "file_request", "DELETE /api/files/requests/{}": "file_request",
    "POST /api/files/requests/{}/restore": "file_request", "GET /u/{}": "file_request", "POST /u/{}": "file_request", "GET /u/v/up.js": "public",
    # 2.93.0 A (#1927): document templates and documents with signature, office admins (p293_a_api_test.py)
    "GET /api/office/doc-templates": "office", "POST /api/office/doc-templates": "office", "PATCH /api/office/doc-templates/{}": "office",
    "DELETE /api/office/doc-templates/{}": "office", "POST /api/office/doc-templates/{}/restore": "office", "GET /api/office/doc-templates/starters": "office",
    "GET /api/office/gen-docs": "office", "POST /api/office/gen-docs": "office", "GET /api/office/gen-docs/{}": "office", "PATCH /api/office/gen-docs/{}": "office",
    "DELETE /api/office/gen-docs/{}": "office", "POST /api/office/gen-docs/{}/restore": "office", "POST /api/office/gen-docs/preview": "office",
    "POST /api/office/gen-docs/{}/final": "office", "GET /api/office/gen-docs/{}/pdf": "office", "POST /api/office/gen-docs/{}/signoff": "office",
    "GET /api/office/gen-docs/{}/signoffs": "office",

    # 2.93.0 B (#1928): the logbook, office admins (p293_b_api_test.py)
    "GET /api/office/vehicles": "office", "POST /api/office/vehicles": "office", "PATCH /api/office/vehicles/{}": "office",
    "GET /api/office/drives": "office", "POST /api/office/drives": "office", "PATCH /api/office/drives/{}": "office", "DELETE /api/office/drives/{}": "office",
    "POST /api/office/drives/{}/restore": "office", "GET /api/office/drives/{}/log": "office", "POST /api/office/drives/{}/trip": "office",
    "GET /api/office/logbook/report": "office", "GET /api/office/logbook.csv": "office", "GET /api/office/logbook.pdf": "office",
    "PUT /api/office/logbook/settings": "office",
    # 2.123.0 D (#2341): the account balance of the cash flow, office admins; the personal office of a freelancer in p2123_d_api_test.py
    "GET /api/office/cashflow/start": "office", "PUT /api/office/cashflow/start": "office", "DELETE /api/office/cashflow/start": "office",
    "POST /api/office/cashflow/adjust": "office", "PATCH /api/office/cashflow/adjust/{}": "office", "DELETE /api/office/cashflow/adjust/{}": "office",
    "PUT /api/office/cashflow/actual": "office",
    # 2.121.0 B (#2095): the cash book, the personal office of a freelancer in p2121_b_api_test.py
    "GET /api/office/cashbooks": "office", "POST /api/office/cashbooks": "office", "GET /api/office/cashbooks/links": "office",
    "PATCH /api/office/cashbooks/{}": "office", "GET /api/office/cashbooks/{}/entries": "office", "POST /api/office/cashbooks/{}/entries": "office",
    "PATCH /api/office/cash-entries/{}": "office", "POST /api/office/cash-entries/{}/cancel": "office", "GET /api/office/cash-entries/{}/log": "office",
    "GET /api/office/cashbooks/{}/closing": "office", "POST /api/office/cashbooks/{}/closing": "office", "GET /api/office/cashbooks/{}/log": "office",
    "GET /api/docs/{}/cashbook": "office", "GET /api/office/cashbook.csv": "office", "GET /api/office/cashbook.pdf": "office",
    # 2.50.0 (#1196, #1197): the sales pipeline and the business figures, admins of the office area only (p250_b_api_test.py: other org 404, member 403)
    "GET /api/office/deals": "office", "POST /api/office/deals": "office", "PATCH /api/office/deals/{}": "office", "DELETE /api/office/deals/{}": "office",
    "POST /api/office/deals/{}/restore": "office", "POST /api/office/deals/{}/offer": "office", "POST /api/office/deals/{}/project": "office",
    "GET /api/office/deals/summary": "office", "GET /api/office/kpi": "office",
    # 2.94.0 A (#1930): leads before the pipeline (office admins; agents with the office switch via v1; p294_a_api_test.py)
    "GET /api/office/deals/{}/convert": "office", "POST /api/office/deals/{}/convert": "office", "POST /api/office/deals/{}/unconvert": "office",
    "POST /api/office/leads/import": "office", "POST /api/office/leads/import/undo": "office",
    "GET /api/v1/office/leads": "office", "POST /api/v1/office/leads": "office", "PATCH /api/v1/office/leads/{}": "office",
    # 2.94.0 B (#1929): appointment booking settings and bookings of the person (p294_b_api_test.py)
    "GET /api/appt/page": "calendar", "PUT /api/appt/page": "calendar", "GET /api/appt/types": "calendar", "POST /api/appt/types": "calendar",
    "PATCH /api/appt/types/{}": "calendar", "DELETE /api/appt/types/{}": "calendar", "POST /api/appt/types/{}/restore": "calendar",
    "GET /api/appt/bookings": "calendar", "POST /api/appt/bookings/{}/cancel": "calendar",
    "GET /s/b/{}": "calendar", "GET /s/b/{}/{}": "calendar", "GET /s/b/{}/{}/{}": "calendar", "POST /s/b/{}/{}/{}": "calendar",
    "GET /s/b/c/{}": "calendar", "POST /s/b/c/{}": "calendar", "GET /s/b/x/{}": "calendar", "POST /s/b/x/{}": "calendar",
    # 2.51.0 (#1348, #1350): agents in the office (drafts only) and the switches / payment suggestions of people (p251_a_api_test.py)
    "GET /api/office/agents/{}": "office", "PATCH /api/office/agents/{}": "office", "GET /api/office/pay-props": "office",
    "POST /api/office/pay-props/{}": "office", "GET /api/v1/office": "office", "GET /api/v1/office/{}": "office",
    "GET /api/v1/office/docs": "office", "GET /api/v1/office/docs/{}": "office", "GET /api/v1/office/docs/{}/pdf": "office",
    "POST /api/v1/office/offers": "office", "PATCH /api/v1/office/offers/{}": "office", "POST /api/v1/office/offers/{}/invoice": "office",
    "POST /api/v1/office/reminders": "office", "GET /api/v1/office/payment-suggestions": "office", "POST /api/v1/office/payment-suggestions": "office",
    "GET /api/office/datev/extf": "office",  # 2.47.3 (#1460): DATEV booking batch, admin only (p2473_e_api_test.py)
    "GET /api/office/datev/accounts": "office",  # 2.120.0 C (#2090): input side accounts, admin only (p2120_c_api_test.py)
    # 2.90.0 A (#1921): bookkeeping light, office admins (p290_a_api_test.py)
    "GET /api/office/books": "office", "GET /api/office/books/euer": "office", "GET /api/office/books/ustva": "office",
    "GET /api/office/books/euer.csv": "office", "GET /api/office/books/euer.pdf": "office", "GET /api/office/books/export": "office",  # 2.147.0 (#2461): neutral export, admin only (p2147_a_api_test.py)
    # ---- office (C, 2.36.1 #1021): quotations of an organisation (10)
    "GET /api/office/docs": "office", "POST /api/office/docs": "office", "GET /api/office/docs/{}": "office",
    "PATCH /api/office/docs/{}": "office", "DELETE /api/office/docs/{}": "office", "PUT /api/office/docs/{}/items": "office",
    "POST /api/office/docs/{}/number": "office", "POST /api/office/docs/{}/status": "office",
    "POST /api/office/docs/{}/duplicate": "office", "GET /api/office/docs/{}/render": "office",
    # ---- office (D, 2.36.1 #1021): the quotation PDF and the organisation's logo (4)
    "GET /api/office/docs/{}/pdf": "office", "GET /api/office/logo": "office", "POST /api/office/logo": "office",
    "DELETE /api/office/logo": "office",
    # 2.120.0 E (#2091): the own letterhead PDF (6)
    "GET /api/office/letterhead": "office", "POST /api/office/letterhead": "office", "PUT /api/office/letterhead": "office",
    "DELETE /api/office/letterhead": "office", "POST /api/office/letterhead/restore": "office", "GET /api/office/letterhead/preview": "office",
    # 2.113.2 (#2253): terms and conditions as PDF per language (p2113c_a_api_test.py)
    "GET /api/office/terms": "office", "POST /api/office/terms/{}": "office", "GET /api/office/terms/{}/file": "office",
    "DELETE /api/office/terms/{}": "office", "POST /api/office/terms/{}/restore": "office", "GET /api/office/docs/{}/terms": "office",
    # ---- office (E, 2.36.2 #1021 / #1142): finalising a document, its history and the organisation's office log (3)
    "POST /api/office/docs/{}/finalize": "office", "POST /api/office/docs/{}/unlock": "office",  # 2.114.2 (#2263)
    "GET /api/office/docs/{}/log": "office", "GET /api/office/log": "office",
    # ---- office (F1, 2.38.0 #1021): invoices, credit notes, reminders, payments, sending, DATEV inbox (11)
    "POST /api/office/docs/{}/invoice": "office", "POST /api/office/docs/{}/credit": "office", "POST /api/office/docs/from-time": "office",
    "POST /api/office/docs/{}/delivery": "office", "GET /api/office/docs/{}/timesheet.pdf": "office",  # 2.120.0 D (#2089)
    "GET /api/office/docs/{}/progress": "office",  # 2.120.0 A (#2087): progress invoices of a quotation (p2120_a_api_test.py)
    "POST /api/office/docs/reminder": "office", "GET /api/office/docs/{}/payments": "office", "POST /api/office/docs/{}/payments": "office",
    "DELETE /api/office/docs/{}/payments/{}": "office", "POST /api/office/docs/{}/send": "office", "POST /api/office/docs/{}/fee": "office", "POST /api/office/docs/{}/datev": "office",
    "GET /api/office/mail-status": "office", "GET /api/office/docs/{}/xml": "office",  # F2: the e-invoice XML of a finalised document
    # 2.47.0 (#1215): the parts of a quotation
    "POST /api/office/docs/{}/parts": "office", "PATCH /api/office/docs/{}/parts/{}": "office", "DELETE /api/office/docs/{}/parts/{}": "office",
    "PUT /api/office/docs/{}/parts/{}/items": "office",
    # ---- office (2.39.1 #1182): legacy import (preview, split, import, runs + undo, archive of old PDFs, counter) (13)
    "POST /api/office/legacy/preview": "office", "POST /api/office/legacy/split": "office", "POST /api/office/legacy/import": "office",
    "GET /api/office/legacy/runs": "office", "POST /api/office/legacy/runs/{}/undo": "office", "POST /api/office/legacy/archive/parse": "office",
    "POST /api/office/legacy/archive/run": "office", "POST /api/office/legacy/archive": "office", "GET /api/office/legacy/archive": "office",
    "PATCH /api/office/legacy/archive/{}": "office", "GET /api/office/legacy/archive/{}/pdf": "office", "GET /api/office/legacy/counter": "office",
    "POST /api/office/legacy/counter": "office",
    "POST /api/office/legacy/archive/address": "office",  # 2.40.0 (#1421): the address of an archived PDF (p2400_k_api_test.py)
    "GET /api/office/legacy/archive/{}": "office",  # 2.81.0 B (#1834): one archived document + its history (p281_b_api_test.py)
    "POST /api/office/legacy/runs/{}/tidy": "office", "POST /api/office/services/renumber": "office",  # 2.138.0 E (#2241, #2237): p2138_e_api_test.py
    # ---- comment (9)
    "POST /api/comments/{}/decide": "comment", "POST /api/v1/comments/{}/reactions": "comment",
    "DELETE /api/v1/comments/{}/reactions/{}": "comment", "PATCH /api/v1/comments/{}": "comment",
    "DELETE /api/v1/comments/{}": "comment", "PATCH /api/comments/{}": "comment", "DELETE /api/comments/{}": "comment",
    "POST /api/comments/{}/reactions": "comment", "POST /api/comments/{}/apply": "comment",
    "POST /api/comments/{}/choice": "comment", "GET /api/comments/{}/choice": "comment",  # 2.41.0 (#1383)
    "POST /api/v1/comments/{}/choice": "comment", "POST /api/v1/comments/{}/withdraw": "comment",
    # ---- contact (16)
    "GET /api/v1/contacts": "contact", "POST /api/v1/contacts": "contact", "GET /api/v1/contacts/{}": "contact",
    "PATCH /api/v1/contacts/{}": "contact", "DELETE /api/v1/contacts/{}": "contact",
    "POST /api/v1/tasks/{}/contacts": "contact", "DELETE /api/v1/tasks/{}/contacts/{}": "contact",
    "GET /api/contacts": "contact", "GET /api/contacts/{}": "contact", "POST /api/contacts": "contact",
    "PATCH /api/contacts/{}": "contact", "DELETE /api/contacts/{}": "contact", "POST /api/tasks/{}/contacts": "contact",
    "DELETE /api/tasks/{}/contacts/{}": "contact", "PUT /api/v1/contacts/{}/care": "contact",
    # 2.119.1 A (#2084 #2085): only the address books one sees (p21191_a_api_test.py)
    "POST /api/contacts/dupcheck": "contact", "GET /api/contacts/groups": "contact", "POST /api/contacts/groups": "contact",
    "PUT /api/contacts/{}/care": "contact",
    "GET /api/contacts/{}/history": "contact",  # 2.119.1 B (#2083): contact_visible, then each source checked (p21191_b_api_test.py)
    "POST /api/contacts/bulk": "contact", "POST /api/v1/contacts/bulk": "contact",  # 2.46.1 (#1554): every id checked first (p2461_c_api_test.py)
    # 2.66.0 (#1835): every id checked (write), one scope only, undo checks the target + every book (p266_a_api_test.py)
    "POST /api/contacts/merge": "contact", "POST /api/contacts/merges/{}/undo": "contact",
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
    "GET /api/export.json": "export", "GET /api/export/todoist.zip": "export", "GET /api/export/markdown.zip": "export",  "GET /api/v1/export": "export",
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
    # 2.97.0 B (#1951): customers (p297_b_api_test.py) - routes below this line
    # 2.49.0 (#1551): the parents' PIN of a child account (set / removed by its parents, opened by the child for its session)
    "PUT /api/family/kids/{}/pin": "family", "DELETE /api/family/kids/{}/pin": "family",
    "POST /api/me/pin/unlock": "family", "POST /api/me/pin/lock": "family",
    # ---- folder (13)
    "GET /api/v1/folders": "folder", "POST /api/v1/folders/rename": "folder", "POST /api/v1/folders/delete": "folder",
    "GET /api/folders/props": "folder", "PUT /api/folders/props": "folder", "GET /api/folders/groups": "folder",
    "PUT /api/folders/groups/{}": "folder", "DELETE /api/folders/groups/{}": "folder", "GET /api/folders/people": "folder",
    "PUT /api/folders/people": "folder", "DELETE /api/folders/people": "folder", "POST /api/folders/rename": "folder",
    "POST /api/folders/delete": "folder",
    "GET /api/folders/agents": "folder", "PUT /api/folders/agents": "folder", "DELETE /api/folders/agents": "folder",  # 2.41.0 (#1420)
    "GET /api/folders/public-links": "folder", "PUT /api/folders/public-links": "folder", "POST /api/folders/owner": "folder",
    "GET /api/folders/repos": "folder", "POST /api/folders/repos": "folder", "PUT /api/lists/{}/folder-repo": "list",  # 2.33.0 (#934)
    "GET /api/folders/notify-template": "folder", "PUT /api/folders/notify-template": "folder",  # 2.33.0 (#927)
    "GET /api/lists/{}/notify-template": "list", "PUT /api/lists/{}/notify-template": "list",
    "GET /api/folders/people/diff": "folder", "GET /api/folders/groups/{}/diff": "folder",  # 2.46.0 (#1606): roles set per list
    "GET /api/v1/lists/{}/notify-template": "list", "POST /api/notify-templates/asked": "own",
    "GET /api/search": "aggregate",  # 2.116.0 B (#2065): full-text search, the visibility of the task search (p2116_b_api_test.py)
    "GET /api/search/messages": "aggregate",  # 2.33.0 (#1080): only what the person may read (vis_sql, rooms, own agent chats)
    "GET /api/admin/client-ip": "admin",  # 2.33.0 (#834)
    "GET /api/admin/health": "admin",  # 2.102.0 D (#1994): numbers only (pool, threads, role, loops), no user data
    "GET /api/admin/retention": "admin",  # 2.103.0 (#2165): the retention runs in numbers (switch, period, last result)
    # ---- form (10)
    "GET /api/lists/{}/forms": "form", "POST /api/lists/{}/forms": "form", "PATCH /api/forms/{}": "form",
    "DELETE /api/forms/{}": "form", "GET /f/{}": "form", "POST /f/{}": "form", "GET /api/v1/lists/{}/forms": "form",
    "POST /api/v1/lists/{}/forms": "form", "PATCH /api/v1/forms/{}": "form", "DELETE /api/v1/forms/{}": "form",
    # 2.63.0 B (#1513): the customer portal
    "GET /p/{}": "portal", "POST /p/{}/comment": "portal", "GET /p/{}/stop": "portal", "POST /p/{}/stop": "portal", "POST /p/{}/notify": "portal",
    "POST /p/{}/login": "portal", "GET /portal/login/{}": "portal", "POST /portal/login/{}": "portal", "GET /portal": "portal",
    "POST /portal/logout": "portal", "PATCH /api/tasks/{}/ticket": "portal",
    # ---- group (6)
    "GET /api/v1/groups": "group", "GET /api/v1/groups/{}": "group", "GET /api/groups": "group",
    "POST /api/admin/groups": "group", "PATCH /api/admin/groups/{}": "group", "DELETE /api/admin/groups/{}": "group",
    "PUT /api/admin/groups/{}/avatar": "group", "POST /api/admin/groups/{}/avatar": "group",  # 2.46.0 (#1605): group pictures
    "DELETE /api/admin/groups/{}/avatar": "group", "GET /api/group-avatar/{}/{}.jpg": "group",  # (p2460_c_api_test.py: outside 404)
    # ---- ical (3)
    "GET /ical/{}.ics": "ical", "GET /ical/ev/{}.ics": "ical", "GET /api/ical": "ical", "POST /api/ical": "ical",
    # ---- list (100)
    "GET /api/lists/{}/export.csv": "list",  # 2.116.0 C (#2064): the list CSV, role of the list + tvis
    "GET /api/lists/{}/agent-access": "list",  # 2.30.0 (#919): the agents' access log of a list (its members)
    "PUT /api/lists/{}/favorite": "list", "DELETE /api/lists/{}/favorite": "list", "PUT /api/lists/{}/in-mine": "list",  # 2.41.0 (#1365)
    "PUT /api/lists/{}/icon": "list", "POST /api/lists/{}/icon": "list", "DELETE /api/lists/{}/icon": "list",
    "GET /api/list-icon/{}/{}.png": "list", "GET /api/v1/lists/{}/tags": "list", "POST /api/v1/lists/{}/tags": "list",
    "PATCH /api/v1/lists/{}/tags/{}": "list", "DELETE /api/v1/lists/{}/tags/{}": "list",
    "GET /api/v1/lists/{}/overview": "list", "PATCH /api/v1/lists/{}/overview": "list",
    "GET /api/v1/lists/{}/links": "list", "POST /api/v1/lists/{}/links": "list", "PATCH /api/v1/lists/{}/links/{}": "list",
    "DELETE /api/v1/lists/{}/links/{}": "list", "PUT /api/v1/lists/{}/links/order": "list",
    "GET /api/v1/lists/{}/milestones": "list", "POST /api/v1/lists/{}/milestones": "list",
    "PATCH /api/v1/lists/{}/milestones/{}": "list", "DELETE /api/v1/lists/{}/milestones/{}": "list",
    # 2.60.0 (#343): sprints belong to their list (need_list on the sprint's list: visibility to read, edit rights to change)
    "GET /api/v1/lists/{}/sprints": "list", "GET /api/v1/sprints/{}": "list", "POST /api/v1/lists/{}/sprints/assign": "list",
    "GET /api/lists/{}/sprints": "list", "POST /api/lists/{}/sprints": "list", "PUT /api/lists/{}/sprint-settings": "list",
    "POST /api/lists/{}/sprints/assign": "list", "GET /api/sprints/{}": "list", "PATCH /api/sprints/{}": "list",
    "DELETE /api/sprints/{}": "list", "POST /api/sprints/{}/start": "list", "POST /api/sprints/{}/close": "list",
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
    "DELETE /api/fields/{}": "list", "GET /api/fields/{}/count": "list", "POST /api/lists/{}/folder-reset": "list", "GET /api/lists/{}/folder-preview": "list", "GET /api/lists/{}/groups": "list",
    "PUT /api/lists/{}/groups/{}": "list", "DELETE /api/lists/{}/groups/{}": "list", "POST /api/lists": "list",
    "PATCH /api/lists/{}": "list", "POST /api/lists/reorder": "list", "DELETE /api/lists/{}": "list",
    "PUT /api/lists/{}/members": "list", "DELETE /api/lists/{}/members/{}": "list", "GET /api/lists/{}/owner": "list",
    "POST /api/lists/{}/owner": "list", "PUT /api/lists/{}/bell": "list", "POST /api/lists/{}/status": "list",
    "GET /api/lists/{}/status": "list", "GET /api/lists/{}/overview": "list", "PATCH /api/lists/{}/overview": "list", "GET /api/lists/{}/layout": "list", "PUT /api/lists/{}/layout": "list",
    "POST /api/lists/{}/links": "list", "PATCH /api/lists/{}/links/{}": "list", "DELETE /api/lists/{}/links/{}": "list",
    "PUT /api/lists/{}/links/order": "list", "POST /api/lists/{}/milestones": "list",
    "POST /api/lists/{}/join": "list", "POST /api/v1/lists/{}/join": "list",  # 2.46.0 (#1603): p2460_b_api checks the boundary
    # 2.43.0: key figures (#1328), notepads + block colours (#1346), all times of a project (#1434): need_list / need_note
    # on the list, foreign ids 404 (p2430_a_api_test.py, p2430_c_api_test.py, p2430_d_api_test.py)
    "GET /api/lists/{}/kpis": "list", "GET /api/v1/lists/{}/kpis": "list", "PUT /api/lists/{}/page-style": "list",
    "POST /api/lists/{}/notepads": "list", "PATCH /api/notepads/{}": "list", "DELETE /api/notepads/{}": "list",
    "GET /api/lists/{}/time/delete-all": "list", "POST /api/lists/{}/time/delete-all": "list", "POST /api/lists/{}/time/restore": "list",
    # 2.43.0 (#1452): the default arrangement of the views: a layout without data of a person, set by the operator
    "GET /api/layouts/std": "public", "PUT /api/layouts/std/{}": "admin",
    # 2.55.0 (#1069): the person's own saved arrangements; (#1068) templates between people who see each other
    "GET /api/layouts/saved": "own", "POST /api/layouts/saved": "own", "PATCH /api/layouts/saved/{}": "own",
    "DELETE /api/layouts/saved/{}": "own", "POST /api/layouts/saved/{}/activate": "own", "POST /api/layouts/saved/standard": "own",
    "POST /api/layouts/offers": "lytpl", "GET /api/layouts/offers/{}": "lytpl", "POST /api/layouts/offers/{}/accept": "lytpl",
    "POST /api/layouts/offers/{}/decline": "lytpl",
    "PATCH /api/lists/{}/milestones/{}": "list", "DELETE /api/lists/{}/milestones/{}": "list",
    "POST /api/lists/{}/checklist": "list", "POST /api/sections": "list", "PATCH /api/sections/{}": "list",
    "POST /api/lists/{}/sections/order": "list", "DELETE /api/sections/{}": "list", "POST /api/lists/{}/shift": "list",
    "POST /api/v1/lists": "list",
    # ---- news (5)
    "GET /api/v1/news": "news", "POST /api/v1/news/read": "news", "GET /api/news": "news",
    "POST /api/news/dismiss": "news", "POST /api/news/read": "news",
    # ---- org (13)
    "GET /api/admin/orgs": "org", "POST /api/admin/orgs/boundary/repair": "org",  # 2.46.0 (#1563)
     "POST /api/admin/orgs": "org", "PATCH /api/admin/orgs/{}": "org",
    "DELETE /api/admin/orgs/{}": "org", "PUT /api/admin/orgs/visibility": "org", "GET /api/orgs": "org",
    "GET /api/admin/orgs/{}/delete-info": "org",  # 2.103.0 A (#2167): numbers for the delete dialog (instance admin)
    "PATCH /api/orgs/{}": "org", "PUT /api/orgs/{}/members": "org", "DELETE /api/orgs/{}/members/{}": "org",
    # 2.115.0 B (#2062): an organisation's invitations by e-mail (p2115_b_api_test.py: other organisation 404, member 403)
    "GET /api/orgs/{}/invites": "org", "POST /api/orgs/{}/invites": "org", "POST /api/orgs/{}/invites/{}/resend": "org",
    "DELETE /api/orgs/{}/invites/{}": "org",
    # 2.35.0 (#1101): an organisation admin's lists of the organisation (p2350_c_api_test.py: other organisation, private list, member 403)
    "GET /api/orgs/{}/lists": "org", "POST /api/orgs/{}/lists/{}/archive": "org", "DELETE /api/orgs/{}/lists/{}": "org",
    "POST /api/orgs/{}/lists/{}/owner": "org",
    # 2.56.0 (#1795): an organisation admin changes name, icon and colour of a list of the organisation (p256_b_api_test.py)
    "PATCH /api/orgs/{}/lists/{}": "org", "PUT /api/orgs/{}/lists/{}/icon": "org", "POST /api/orgs/{}/lists/{}/icon": "org",
    "DELETE /api/orgs/{}/lists/{}/icon": "org",
    # 2.42.0 (#828): an organisation's encryption state + recovery key (its admins only; p2420_b_api_test.py: member 403, other
    # organisation 404, agent refused); the instance switch org_encrypt is the operator's
    "GET /api/orgs/{}/encryption": "org", "POST /api/orgs/{}/encryption/recovery": "org",
    "POST /api/orgs/{}/encryption/recovery/passkey": "org",  # 2.138.0 (#1972): the passkey challenge of the step-up (p2138_c_api_test.py)
    "GET /api/admin/orgcrypt": "admin", "PUT /api/admin/orgcrypt": "admin",
    # 2.42.0 (#833): the organisation export (its admins only; p2420_c_api_test.py: member 403, other organisation 404, agent refused)
    "GET /api/orgs/{}/export": "org", "GET /api/retention/org/{}": "org", "GET /api/retention/org/{}/export.zip": "org",
    "GET /api/retention/me": "own", "GET /api/retention/me/export.zip": "own",
    "POST /api/orgs/{}/export": "org", "DELETE /api/orgs/{}/export": "org", "GET /api/orgs/{}/export/file": "org",
    # ---- own (119)
    "POST /api/favorites/suggestion": "own",  # 2.46.1 (#1361): a favourite suggestion from the person's own activity
    "PUT /api/tasks/mine-order": "own", "GET /api/me/wait-suggestions": "own", "DELETE /api/me/wait-suggestions": "own",  # 2.41.0 (#1205)
    "POST /api/onboarding": "own", "POST /api/sample": "own", "DELETE /api/sample": "own", "PATCH /api/settings": "own",
    "POST /api/ntfy/test": "own", "GET /api/me/ntfy-inbox": "own", "PUT /api/me/ntfy-inbox": "own",  # 2.142.0 C (#2150)
     "GET /api/push/vapid": "own", "GET /api/push/subs": "own", "POST /api/push/subs": "own",
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
    "GET /api/v1/habits/{}/stats": "own", "GET /api/v1/focus": "own", "GET /api/v1/focus/stats": "own",  # 2.116.0 D (#2067)
    "POST /api/v1/focus/start": "own", "POST /api/v1/focus/{}/stop": "own", "POST /api/v1/focus/{}/pause": "own",
    "POST /api/v1/focus/{}/resume": "own",
    "GET /api/v1/habits": "own", "POST /api/v1/habits/{}/checkin": "own", "POST /api/v1/import/{}": "own",
    "POST /api/v1/imports/{}/undo": "own", "GET /api/me/app-passwords": "own", "POST /api/me/app-passwords": "own",
    "DELETE /api/me/app-passwords/{}": "own", "GET /api/calendars": "own", "POST /api/calendars/discover": "own",
    "POST /api/calendars": "own", "PATCH /api/calendars/{}": "own", "DELETE /api/calendars/{}": "own",
    "POST /api/calendars/{}/refresh": "own",
    # 2.52.0 (#1128): writing into the person's own CalDAV subscription (need_calsub: the subscription's owner only)
    "POST /api/calendars/{}/events": "own", "PATCH /api/calendars/{}/events": "own", "DELETE /api/calendars/{}/events": "own",
    "POST /api/calendars/{}/events/restore": "own", "POST /api/calendars/{}/write": "own", "POST /api/import/ticktick": "own", "POST /api/import/{}": "own",
    "POST /api/imports/{}/undo": "own", "GET /api/imports": "own", "GET /api/me/mail": "own",
    # 2.73.0 B (#1473): the account export / import: the person's own files (a folder per person, another person's id = 404);
    # the import's target organisation needs its admin (p273_b_api_test.py)
    "GET /api/account/export": "own", "POST /api/account/export": "own", "DELETE /api/account/export": "own",
    "GET /api/account/export/file": "own", "GET /api/account/import": "own", "POST /api/account/import": "own",
    "GET /api/account/import/{}": "own", "PUT /api/account/import/{}": "own", "DELETE /api/account/import/{}": "own",
    "POST /api/account/import/{}/run": "own", "POST /api/account/import/{}/key": "own",
    # 2.96.0 D (#1941 / #1918): an organisation export into the private space (p296_d_api_test.py)
    "POST /api/me/mail/token": "own", "DELETE /api/me/mail/token": "own", "POST /api/me/mail/test": "own",
    "GET /api/v1/life": "own", "GET /api/v1/life/upkeep-presets": "own",
    "POST /api/v1/life/contracts": "own", "POST /api/v1/life/devices": "own", "POST /api/v1/life/upkeep": "own",
    "POST /api/v1/life/health": "own", "POST /api/v1/life/trips": "own", "GET /api/v1/life/review": "own",
    "PUT /api/v1/life/journal/{}": "own", "POST /api/v1/life/karakeep/sync": "own", "GET /api/life": "own",
    "GET /api/life/upkeep-presets": "own", "POST /api/life/contracts": "own", "POST /api/life/devices": "own",
    "POST /api/life/upkeep": "own", "POST /api/life/health": "own", "POST /api/life/trips": "own",
    "GET /api/life/review": "own", "GET /api/life/journal": "own", "GET /api/life/journal/stats": "own", "GET /api/life/journal/export": "own",  # 2.140.0 C (#2133)
     "PUT /api/life/journal/{}": "own", "GET /api/life/karakeep": "own",
    "PUT /api/life/karakeep": "own", "DELETE /api/life/karakeep": "own", "GET /api/life/karakeep/lists": "own",
    "POST /api/life/karakeep/sync": "own", "POST /api/filters": "own", "PATCH /api/filters/{}": "own",
    "DELETE /api/filters/{}": "own", "POST /api/habits": "own", "PATCH /api/habits/{}": "own",
    "DELETE /api/habits/{}": "own", "POST /api/habits/{}/log": "own", "POST /api/pomo/start": "own",
    "POST /api/pomo/{}/{}": "own", "POST /api/time/start": "own", "POST /api/time/stop": "own",
    "POST /api/time/entries": "own", "PATCH /api/time/entries/{}": "own", "DELETE /api/time/entries/{}": "own",
    "GET /api/time/entries": "own", "GET /api/time/report": "own", "GET /api/time/export.csv": "own", "GET /api/time/export.xlsx": "own",
    "GET /api/family/contacts": "own", "POST /api/family/contacts": "own", "PATCH /api/family/contacts/{}": "own",
    "DELETE /api/family/contacts/{}": "own", "POST /api/family/contacts/{}/sync": "own",
    # ---- people (9)
    "POST /api/users/{}/invite": "people", "POST /api/users/{}/approve": "people",
    "POST /api/users/{}/signin-link": "people", "GET /api/v1/admin/users": "people", "GET /api/users": "people",
    "POST /api/users": "people", "PATCH /api/users/{}": "people", "DELETE /api/users/{}": "people",
    # 2.88.0 (#1980): the delete dialog's lists + candidates, several accounts at once (p288_b_api_test.py)
    "GET /api/users/{}/delete-info": "people", "POST /api/users/bulk": "people",
    "GET /api/avatar/{}/{}.jpg": "people",
    # ---- public (15)
    "GET /api/v1/announcement": "public", "GET /api/v1/openapi.json": "public", "GET /api/about": "public", "POST /api/client-errors": "clienterr",
    "GET /": "public", "GET /capture": "public", "GET /share": "public", "POST /share": "public", "POST /drop": "public",
    "POST /drop/drop": "public", "GET /robots.txt": "public", "GET /manifest.json": "public", "GET /sw.js": "public",
    "GET /api/health": "public", "GET /api/version": "public", "POST /api/qr": "public",
    # ---- publiclink (7)
    "GET /s/{}": "publiclink", "POST /s/{}/unlock": "publiclink", "POST /s/{}/tick": "publiclink",
    "GET /api/lists/{}/public-link": "publiclink", "PUT /api/lists/{}/public-link": "publiclink",
    "POST /api/lists/{}/public-link/regenerate": "publiclink", "DELETE /api/lists/{}/public-link": "publiclink",
    # 2.50.0 (#329, #1200)
    "GET /s/{}/file/{}": "signoff", "GET /s/{}/logo": "signoff", "POST /s/{}/feedback": "signoff", "GET /s/q/{}": "signoff", "GET /s/q/{}/pdf": "signoff", "POST /s/q/{}": "signoff",
    "POST /s/q/{}/comments": "signoff",  # 2.99.1 A (#1959): a customer's comment on a video sign-off
    "GET /s/q/{}/terms": "signoff",  # 2.113.2 (#2253): the terms frozen with the quotation of the link
    # 2.99.1 A (#1959): video sign-offs (videos/review.py; p2991_a_api_test.py)
    "GET /api/videos": "video", "POST /api/videos": "video", "GET /api/videos/{}": "video", "PATCH /api/videos/{}": "video",
    "DELETE /api/videos/{}": "video", "POST /api/videos/{}/restore": "video", "POST /api/videos/{}/versions": "video",
    "DELETE /api/videos/{}/versions/{}": "video", "POST /api/videos/{}/comments": "video", "PATCH /api/videos/{}/comments/{}": "video",
    "DELETE /api/videos/{}/comments/{}": "video", "POST /api/videos/{}/comments/{}/restore": "video", "GET /api/videos/{}/export": "video",
    "POST /api/videos/{}/signoff": "video", "POST /api/videos/{}/signoffs/{}/revoke": "video", "POST /api/videos/{}/move-space": "video",
    # 2.99.1 C (#1959): video sign-offs for agents (videos/v1.py; p2991_c_api_test.py)
    "GET /api/v1/videos": "video", "GET /api/v1/videos/{}": "video", "POST /api/v1/videos/{}/comments": "video",
    "PATCH /api/v1/videos/{}/comments/{}": "video",
    "GET /api/lists/{}/signoffs": "signoff", "POST /api/lists/{}/signoffs": "signoff", "POST /api/lists/{}/signoffs/{}/revoke": "signoff",
    "GET /api/office/docs/{}/signoffs": "signoff", "POST /api/office/docs/{}/signoff": "signoff", "POST /api/office/signoffs/{}/revoke": "signoff",
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
    "POST /api/team/rooms/{}/read": "team",
    # 2.42.0 (#828, #909): end-to-end encryption -- the person's own keys; a DM partner's public key / the DM switch (need_room,
    # tchat_coworkers); the encrypted note (need_task) and an encrypted file (need_task + attachment rules) of a task
    "GET /api/e2e/keys": "own", "PUT /api/e2e/keys": "own", "DELETE /api/e2e/keys": "own", "GET /api/e2e/pub/{}": "team",
    "POST /api/team/rooms/{}/e2e": "team", "GET /api/tasks/{}/enc-note": "task", "PUT /api/tasks/{}/enc-note": "task",
    "DELETE /api/tasks/{}/enc-note": "task", "POST /api/tasks/{}/enc-attachments": "attachment",
    # 2.48.0 (#1642): the locked note of a task (need_task; only the person who locked it)
    "GET /api/tasks/{}/bell": "task", "PUT /api/tasks/{}/bell": "task", "POST /api/tasks/{}/bell/undo": "task",  # 2.53.0 C (#1424): need_task + people of the list (p253_c_api_test.py)
    # 2.64.1 A (#1817): the lock per list -- need_list + people only (p264a_a_api_test.py: outside the list 404, agents / tokens 403)
    "GET /api/lists/{}/e2e": "list", "POST /api/lists/{}/e2e/start": "list", "GET /api/lists/{}/e2e/todo": "list",
    "POST /api/lists/{}/e2e/bulk": "list", "POST /api/lists/{}/e2e/finish": "list", "POST /api/lists/{}/e2e/stop": "list",
    "POST /api/lists/{}/e2e/keys": "list",
    "POST /api/lists/{}/e2e/rotate": "list",  # 2.64.2 A (#1817): key change of a list with the lock
    # 2.97.0 C (#2049): office moves (p297_c_api_test.py) - routes below this line
    "POST /api/office/move-space": "office",
    # 2.137.0 D (#1981): the personal office into an organisation the person is an admin of (p2137_d_api_test.py)
    "GET /api/office/move/check": "office", "POST /api/office/move/org": "office",
    # 2.64.2 B (#1817): list files -- need_task (+ own comment) / need_list, people in the app only (p264b_b_api_test.py)
    "POST /api/tasks/{}/list-attachments": "attachment", "POST /api/lists/{}/e2e/files/{}": "list",
    "GET /api/tasks/{}/note-lock": "task", "PUT /api/tasks/{}/note-lock": "task", "DELETE /api/tasks/{}/note-lock": "task", "GET /api/v1/team/rooms": "team", "POST /api/v1/team/dm": "team",
    "GET /api/v1/team/rooms/{}/messages": "team", "POST /api/v1/team/rooms/{}/messages": "team",
    "PATCH /api/v1/team/messages/{}": "team", "DELETE /api/v1/team/messages/{}": "team",
    "POST /api/v1/team/messages/{}/reactions": "team", "POST /api/v1/team/rooms/{}/read": "team",
    "POST /api/team/messages/{}/pin": "team", "POST /api/v1/team/messages/{}/pin": "team",  # 2.62.0 (#1848): also p262_a_api_test.py
    # 2.113.1 B (#2059): channels, groups, files: p2113b_b_api_test.py (another organisation's person / agent 404 / 400)
    "GET /api/team/channels": "team", "POST /api/team/channels": "team", "POST /api/team/groups": "team",
    "PATCH /api/team/rooms/{}": "team", "POST /api/team/rooms/{}/members": "team", "DELETE /api/team/rooms/{}/members/{}": "team",
    "GET /api/team/files/{}": "team", "GET /api/v1/team/channels": "team", "POST /api/v1/team/channels": "team",
    "POST /api/v1/team/groups": "team", "PATCH /api/v1/team/rooms/{}": "team", "POST /api/v1/team/rooms/{}/members": "team",
    "DELETE /api/v1/team/rooms/{}/members/{}": "team", "GET /api/v1/team/files/{}": "team",
    # ---- template (12)
    "GET /api/v1/templates": "template", "POST /api/v1/templates": "template", "PATCH /api/v1/templates/{}": "template",
    "DELETE /api/v1/templates/{}": "template", "POST /api/v1/templates/{}/apply": "template",
    "GET /api/templates": "template", "POST /api/templates": "template", "PATCH /api/templates/{}": "template",
    "DELETE /api/templates/{}": "template", "POST /api/templates/{}/apply": "template",
    "POST /api/lists/{}/duplicate": "template", "POST /api/v1/lists/{}/duplicate": "template",  # 2.78.0 (#1881): also p278_dup_api_test.py
    # ---- token (2)
    "POST /api/hooks/issues/{}/{}": "token", "POST /api/hooks/issues/{}": "token", "POST /api/hooks/git/{}": "token",
    # ---- 2.60.0 (#1514): environments of a project list (they belong to their list; the deploy hook is a secret token)
    "POST /api/hooks/deploy/{}/{}": "token", "GET /api/lists/{}/envs": "list", "POST /api/lists/{}/envs": "list",
    "PATCH /api/envs/{}": "list", "DELETE /api/envs/{}": "list", "POST /api/envs/{}/restore": "list", "POST /api/envs/{}/deploy": "list",
    "DELETE /api/envs/{}/deploys/{}": "list", "GET /api/v1/lists/{}/environments": "list", "POST /api/v1/lists/{}/deployments": "list",
    # ---- webhook (7)
    "GET /api/me/webhooks": "webhook", "POST /api/me/webhooks": "webhook", "PATCH /api/me/webhooks/{}": "webhook",
    "DELETE /api/me/webhooks/{}": "webhook", "POST /api/me/webhooks/{}/secret": "webhook",
    "POST /api/me/webhooks/{}/test": "webhook", "GET /api/me/webhooks/{}/log": "webhook",
    # 2.115.0 A (#2061): webhooks of an organisation (its admins only; deliveries only of what the organisation owns) and the
    # inbound webhooks of a list (owner / list admins; the URL creates tasks only in its own list) -- p2115_a_api_test.py
    "GET /api/orgs/{}/webhooks": "webhook", "POST /api/orgs/{}/webhooks": "webhook", "PATCH /api/orgs/{}/webhooks/{}": "webhook",
    "DELETE /api/orgs/{}/webhooks/{}": "webhook", "POST /api/orgs/{}/webhooks/{}/secret": "webhook",
    "POST /api/orgs/{}/webhooks/{}/test": "webhook", "GET /api/orgs/{}/webhooks/{}/log": "webhook",
    # 2.142.0 A (#2145): notification channels of a person / of an organisation (its admins; messages only of lists open to every
    # member) -- p2142_a_api_test.py
    "GET /api/me/channels": "channel", "POST /api/me/channels": "channel", "PATCH /api/me/channels/{}": "channel",
    "DELETE /api/me/channels/{}": "channel", "POST /api/me/channels/{}/test": "channel",
    "GET /api/orgs/{}/channels": "channel", "POST /api/orgs/{}/channels": "channel", "PATCH /api/orgs/{}/channels/{}": "channel",
    "DELETE /api/orgs/{}/channels/{}": "channel", "POST /api/orgs/{}/channels/{}/test": "channel",
    "POST /api/hooks/in/{}": "token", "GET /api/lists/{}/hooks-in": "list", "POST /api/lists/{}/hooks-in": "list",
    "PATCH /api/hooks-in/{}": "list", "DELETE /api/hooks-in/{}": "list", "POST /api/hooks-in/{}/rotate": "list",
    "POST /api/hooks-in/{}/restore": "list",
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
    # 2.39.0 (#1168): the Playbook of a list (need_list: people who do not see the list 404, p2390_a_api_test.py) and of a
    # folder (the own folders only), agent proposals, the scheduled list checks (an agent of the list); #1179: editing an own
    # message in an agent chat (only the sender, only an agent one may use)
    "GET /api/lists/{}/playbook": "list", "PUT /api/lists/{}/playbook": "list", "GET /api/lists/{}/playbook/versions": "list",
    "GET /api/lists/{}/playbook/versions/{}": "list", "POST /api/lists/{}/playbook/restore": "list",
    "POST /api/lists/{}/playbook/proposals/{}/apply": "list", "POST /api/lists/{}/playbook/proposals/{}/discard": "list",
    "GET /api/v1/lists/{}/playbook": "list", "POST /api/v1/lists/{}/playbook/proposals": "list",
    "GET /api/folders/playbook": "folder", "PUT /api/folders/playbook": "folder", "GET /api/folders/playbook/versions": "folder",
    "GET /api/folders/playbook/versions/{}": "folder", "POST /api/folders/playbook/restore": "folder",
    "GET /api/lists/{}/checks": "agent", "POST /api/lists/{}/checks": "agent", "PATCH /api/list-checks/{}": "agent",
    "DELETE /api/list-checks/{}": "agent", "POST /api/list-checks/{}/run": "agent",
    "PATCH /api/agents/{}/chat/{}": "agent",
    # 2.44.0 (#1517): one-command setup of an agent on a computer (one-time code, the computers = the agent's tokens)
    "POST /api/my/agents/{}/setup-code": "agent", "GET /api/my/agents/{}/machines": "agent",
    "DELETE /api/my/agents/{}/machines/{}": "agent", "POST /api/admin/agents/{}/setup-code": "admin",
    "GET /api/admin/agents/{}/machines": "admin", "DELETE /api/admin/agents/{}/machines/{}": "admin",
    "POST /api/agent-setup/redeem": "auth", "POST /api/agent-setup/remove": "auth",
    "GET /agent-setup.sh": "public", "GET /agent-setup.ps1": "public",
    # 2.49.0 (#1531, #1199, #1201): Forgot your password?, knowledge pages, outline import
    "POST /api/auth/forgot": "auth", "POST /api/outline/parse": "pure",
    # 2.89.0 C (#1916): tables as files and for agents
    "GET /api/sheets/{}/export.csv": "sheet_v1", "GET /api/sheets/{}/export.xlsx": "sheet_v1", "POST /api/sheets/import": "sheet_v1",
    "GET /api/v1/sheets": "sheet_v1", "POST /api/v1/sheets": "sheet_v1", "GET /api/v1/sheets/{}": "sheet_v1",
    "PATCH /api/v1/sheets/{}": "sheet_v1", "PUT /api/v1/sheets/{}/cells": "sheet_v1", "POST /api/v1/sheets/{}/rows": "sheet_v1",
    "POST /api/v1/sheets/{}/columns": "sheet_v1", "GET /api/v1/sheets/{}/vars": "sheet_v1",
    "POST /api/v1/sheets/{}/batches/{}/undo": "sheet_v1",
    "GET /api/wiki": "wiki", "GET /api/wiki/export": "wiki", "GET /api/wiki/mentions": "wiki", "GET /api/wiki/search": "wiki",
    "GET /api/wiki/pages/{}": "wiki", "PATCH /api/wiki/pages/{}": "wiki", "DELETE /api/wiki/pages/{}": "wiki",
    "POST /api/wiki/pages": "wiki", "POST /api/wiki/import": "wiki", "POST /api/wiki/move": "wiki",
    # 2.96.0 B (#1941): wiki pages / folders to the other workspace (p296_b_api_test.py)
    "POST /api/wiki/move-space": "wiki",
    "POST /api/wiki/restore": "wiki", "POST /api/wiki/trash": "wiki",
    # 2.143.0 B (#2211): the trash of a space -- list, delete for good / empty (p2143_b_api_test.py: another space 404 / skipped)
    "GET /api/wiki/trash": "wiki", "POST /api/wiki/purge": "wiki",
    # 2.123.0 C (#2103, #2107): files of the file store / tables in pages (another organisation 404, p2123_c_api_test.py)
    "POST /api/wiki/pages/{}/refs": "wiki", "GET /api/wiki/refs": "wiki",
    # 2.99.0 A (#2182): files of knowledge pages (a file of another organisation / person: 404, p299_a_api_test.py)
    "GET /api/wiki/files/{}": "wiki", "GET /api/wiki/files/{}/{}": "wiki", "DELETE /api/wiki/files/{}": "wiki",
    "POST /api/wiki/pages/{}/files": "wiki",
    # 2.123.0 B (#2104): shares of knowledge pages / folders (another organisation / person: 404, p2123_b_api_test.py)
    "GET /api/wiki/shares": "wiki", "POST /api/wiki/shares": "wiki", "PATCH /api/wiki/shares/{}": "wiki", "DELETE /api/wiki/shares/{}": "wiki",
    "POST /api/wiki/shares/{}/restore": "wiki", "GET /api/wiki/shared": "wiki", "GET /api/wiki/shared/pages/{}": "wiki",
    "GET /api/wiki/shared/files/{}": "wiki", "GET /api/wiki/shared/files/{}/{}": "wiki",
    "GET /s/w/{}": "wiki", "GET /s/w/{}/p/{}": "wiki", "GET /s/w/{}/file/{}": "wiki",
    # 2.123.0 A (#2102): the history of a page (a page of another organisation / person: 404, p2123_a_api_test.py)
    "GET /api/wiki/pages/{}/versions": "wiki", "GET /api/wiki/pages/{}/versions/{}": "wiki",
    "POST /api/wiki/pages/{}/versions/{}/restore": "wiki",
    # 2.64.3 A (#1817): the lock per knowledge space (wiki_space: a space of another organisation 404, p264c_a_api_test.py)
    "GET /api/wiki/e2e": "wiki", "POST /api/wiki/e2e/start": "wiki", "GET /api/wiki/e2e/todo": "wiki",
    "POST /api/wiki/e2e/bulk": "wiki", "POST /api/wiki/e2e/finish": "wiki", "POST /api/wiki/e2e/stop": "wiki",
    "POST /api/wiki/e2e/keys": "wiki", "POST /api/wiki/e2e/rotate": "wiki",
    # 2.89.0 (#1916): tables (sheets/web.py; p289_a_api_test.py)
    "GET /api/sheets": "sheet", "POST /api/sheets": "sheet", "GET /api/sheets/{}": "sheet", "PATCH /api/sheets/{}": "sheet",
    # 2.96.0 B (#1941): a table to the other workspace (p296_b_api_test.py)
    "POST /api/sheets/{}/move-space": "sheet",
    # 2.124.0 C (#2113): shares of one table (p2124_c_api_test.py)
    "GET /api/sheets/{}/shares": "sheet_share", "POST /api/sheets/{}/shares": "sheet_share",
    "PATCH /api/sheets/{}/shares/{}": "sheet_share", "DELETE /api/sheets/{}/shares/{}": "sheet_share",
    # 2.125.0 B (#2119): monthly timesheets (p2125_b_api_test.py)
    "GET /api/time/sheets": "timesheet", "POST /api/time/sheets": "own", "POST /api/time/sheets/decide": "timesheet",
    "PUT /api/sheets/{}/chart": "sheet",  # 2.124.0 A (#2115): the chart of a table (p2124_a_api_test.py)
    # 2.124.0 E (#2116): the sheets of a table (p2124_e_api_test.py: a stranger 404 on every route, another organisation's agent 404)
    "GET /api/sheets/{}/tabs": "sheet", "POST /api/sheets/{}/tabs": "sheet", "PATCH /api/sheets/{}/tabs/{}": "sheet",
    "DELETE /api/sheets/{}/tabs/{}": "sheet", "POST /api/sheets/{}/tabs/{}/restore": "sheet",
    "GET /api/v1/sheets/{}/tabs": "sheet_v1", "POST /api/v1/sheets/{}/tabs": "sheet_v1",
    "DELETE /api/sheets/{}": "sheet", "POST /api/sheets/{}/restore": "sheet", "PUT /api/sheets/{}/cells": "sheet",
    "POST /api/sheets/{}/cells/{}/freeze": "sheet", "POST /api/sheets/{}/cells/{}/name": "sheet",
    "POST /api/sheets/{}/columns": "sheet", "PATCH /api/sheets/{}/columns/{}": "sheet", "DELETE /api/sheets/{}/columns/{}": "sheet",
    "POST /api/sheets/{}/columns/{}/restore": "sheet", "POST /api/sheets/{}/rows": "sheet", "DELETE /api/sheets/{}/rows/{}": "sheet",
    "POST /api/sheets/{}/rows/{}/restore": "sheet", "POST /api/sheets/{}/rows/order": "sheet", "POST /api/sheets/{}/presence": "sheet",
    "GET /api/sheets/{}/vars": "sheet", "POST /api/sheets/{}/batches/{}/undo": "sheet",
    # 2.124.0 B (#2110 #2111 #2112): people of a person cell, files of file cells, rows / columns kept in view, the history (p2124_b_api_test.py)
    "GET /api/sheets/{}/people": "sheet", "POST /api/sheets/{}/files": "sheet", "GET /api/sheets/{}/files/{}": "sheet", "GET /api/sheets/{}/files/{}/{}": "sheet",
    "POST /api/sheets/{}/fixed": "sheet", "GET /api/sheets/{}/history": "sheet", "GET /api/sheets/{}/cells/{}/history": "sheet",
    # 2.49.0 (#1106): find people by e-mail, connection requests, blocks
    "GET /api/disc": "discover", "PUT /api/disc": "discover", "POST /api/disc/confirm": "discover", "POST /api/disc/find": "discover",
    "POST /api/disc/check": "discover", "POST /api/disc/requests": "discover", "POST /api/disc/requests/{}/{}": "discover",
    "DELETE /api/disc/requests/{}": "discover", "DELETE /api/disc/connections/{}": "discover",
    "POST /api/disc/connections/{}/restore": "discover", "POST /api/disc/blocks/{}": "discover", "DELETE /api/disc/blocks/{}": "discover",
    # 2.48.0 (#1111): documents
    "GET /api/docs": "document", "POST /api/docs": "document", "GET /api/docs/{}": "document", "PATCH /api/docs/{}": "document",
    "POST /api/docs/{}/accept": "document", "POST /api/docs/{}/review": "document", "POST /api/docs/{}/redo": "document",
    "GET /api/docs/{}/thumb": "document", "GET /api/docs/{}/file": "document", "POST /api/docs/{}/task": "document",
    "DELETE /api/docs/{}/task": "document", "GET /api/docs/settings": "document", "PUT /api/docs/settings": "document",
    "POST /api/docs/rules": "document", "PATCH /api/docs/rules/{}": "document", "DELETE /api/docs/rules/{}": "document",
    "PATCH /api/docs/labels/{}/{}": "document", "DELETE /api/docs/labels/{}/{}": "document", "POST /api/docs/labels/{}": "document", "POST /api/docs/mail": "document",
    "DELETE /api/docs/mail": "document", "GET /api/v1/documents": "document", "GET /api/v1/documents/{}": "document",
    "PATCH /api/v1/documents/{}": "document", "POST /api/v1/documents": "document", "POST /api/docs/export.csv": "document",  # 2.122.0 (#2098)
    # 2.122.0 B (#2294 #2099): the chosen documents at once / as a ZIP; tags of files and folders (p2122_b_api_test.py: another
    # organisation / person: nothing changed, nothing in the ZIP, 404 on the tags of a node, no hit in the tag filter)
    "POST /api/docs/bulk": "document", "POST /api/docs/zip": "document", "GET /api/docs/zip/{}": "document",
    "GET /api/files/nodes/{}/tags": "file", "PUT /api/files/nodes/{}/tags": "file", "GET /api/files/tags": "file", "GET /api/files/tagged": "file",
    # 2.48.0 (#1207 / #1152 / #1356)
    "DELETE /api/files/nodes/{}": "file", "DELETE /api/files/shares/{}": "file", "DELETE /api/paperless": "paperless",
    "GET /api/docs/{}/receipt": "receipt", "POST /api/docs/{}/extracted": "document",  # 2.121.0 A (#2092)
    "GET /api/docs/{}/einvoice": "document",  # 2.146.0 A (#2451): the readable view of an e-invoice
    "GET /api/files": "file", "GET /api/files/folders": "file",
    "GET /api/files/search": "file", "GET /api/v1/files/search": "file",  # 2.61.0 (#1820): names + recognised text, the boundary tested in p261_c_api_test.py
    "GET /api/files/nodes/{}": "file", "GET /api/files/nodes/{}/content": "file",
    "GET /api/files/nodes/{}/share-targets": "file", "GET /api/paperless": "paperless",
    "GET /api/paperless/preview": "paperless", "GET /api/v1/files": "file", "GET /api/v1/files/{}": "file",
    "GET /api/v1/files/{}/content": "file", "GET /api/v1/files/{}/text": "file", "GET /api/v1/receipt-suggestions": "receipt",
    "PATCH /api/files/nodes/{}": "file", "PATCH /api/files/shares/{}": "file", "POST /api/files/folders": "file",
    # 2.96.0 A (#1941): files / folders / documents to the other workspace (p296_a_api_test.py)
    "POST /api/files/move-space": "file",
    # 2.112.1 A (#2058): several nodes into the trash / back, the ZIP download, the phone scan (p21121_a_api_test.py)
    "POST /api/files/trash": "file", "POST /api/files/restore": "file", "GET /api/files/zip": "file", "POST /api/files/scan": "file",
    "POST /api/files/links": "file", "POST /api/files/nodes/{}/restore": "file", "POST /api/files/nodes/{}/shares": "file",
    "POST /api/files/nodes/{}/versions": "file", "POST /api/files/nodes/{}/versions/{}/restore": "file",
    "POST /api/files/upload": "file", "POST /api/paperless/import": "paperless", "POST /api/paperless/stop": "paperless",
    "POST /api/receipt-suggestions/{}/accept": "receipt", "POST /api/receipt-suggestions/{}/reject": "receipt",
    "POST /api/receipt-suggestions/{}/reopen": "receipt", "POST /api/v1/documents/{}/receipt-suggestion": "receipt",
    "POST /api/v1/files": "file", "POST /api/v1/files/{}/versions": "file", "PUT /api/docs/{}/receipt": "receipt",
    "PUT /api/paperless": "paperless",
    # 2.50.0 A (#1195): absences; (#1194): resources and disposition
    "GET /api/team/absences": "hub", "POST /api/team/absences": "hub", "PATCH /api/team/absences/{}": "hub",
    "DELETE /api/team/absences/{}": "hub", "POST /api/team/absences/{}/restore": "hub", "PUT /api/team/absences/holidays": "hub",
    "GET /api/team/absences/check": "hub", "GET /api/team/leave": "hub", "PUT /api/team/leave/quota": "hub",  # 2.125.0 A (#2117)
    "PUT /api/team/leave/approval": "hub", "PUT /api/team/leave/worktime/{}": "hub", "POST /api/team/absences/{}/decide": "hub",
    "GET /api/team/dispo": "hub", "GET /api/team/dispo/free": "hub", "GET /api/team/dispo/export": "hub",
    "POST /api/team/dispo/bookings": "hub", "PATCH /api/team/dispo/bookings/{}": "hub", "DELETE /api/team/dispo/bookings/{}": "hub",
    "POST /api/team/dispo/bookings/restore": "hub", "GET /api/team/bookings/mine": "hub", "GET /api/v1/absences": "hub",
    # 2.51.0 C (#1352 #1353 #1355): agents on the pin board, time check / proposals, the disposition + shoot proposals (p251_c_api_test.py)
    "GET /api/v1/lists/{}/notepads": "list", "POST /api/v1/lists/{}/notepads": "list", "PATCH /api/v1/notepads/{}": "list",
    "DELETE /api/v1/notepads/{}": "list", "PUT /api/v1/lists/{}/status-pad": "list", "GET /api/v1/lists/{}/weekly-status": "list",
    "GET /api/v1/time/check": "aggregate", "GET /api/v1/time/from-events": "aggregate", "POST /api/v1/agent/proposals/time": "agent",
    # 2.55.0 (#1066): an agent reads / proposes arrangements of its person's views (p255_b_api_test.py: other person / org 404)
    "GET /api/v1/layouts/blocks": "agent", "GET /api/v1/layouts/{}": "agent", "POST /api/v1/layouts/proposals": "agent",
    "GET /api/v1/dispo": "hub", "GET /api/v1/dispo/free": "hub", "POST /api/v1/agent/proposals/shoot": "hub",
    # 2.55.0 (#1455): the newsletter connection of one workspace (its admins / the person), consent on writable contacts
    "GET /api/newsletter": "newsletter", "PUT /api/newsletter": "newsletter", "DELETE /api/newsletter": "newsletter",
    "GET /api/newsletter/lists": "newsletter", "POST /api/newsletter/segments": "newsletter", "PATCH /api/newsletter/segments/{}": "newsletter",
    "DELETE /api/newsletter/segments/{}": "newsletter", "POST /api/newsletter/sync": "newsletter", "PUT /api/newsletter/consent": "newsletter", "POST /api/newsletter/consent/import": "newsletter",
    # 2.59.0 B (#1375): related tasks (tasks/related.py)
    "GET /api/tasks/{}/related": "related", "GET /api/v1/tasks/{}/related": "related", "POST /api/tasks/similar": "related",
    "GET /api/related/config": "public", "GET /api/admin/related": "admin", "PUT /api/admin/related": "admin",
    # 2.97.0 D (#2050 #2051): locked spaces / clean-up (p297_d_api_test.py) - routes below this line
    # 2.60.0 B (#1511): the velocity of a list (need_list read; p260_b_api_test.py: a stranger / another organisation's agent 404)
    "GET /api/lists/{}/velocity": "list", "GET /api/v1/lists/{}/velocity": "list",
    # 2.60.0 C (#1512): the review step (need_task / need_list of the task's list; p260_c_api_test.py: a stranger 404, a viewer 403)
    "POST /api/tasks/{}/review": "task", "POST /api/v1/tasks/{}/review": "task",
    "PUT /api/lists/{}/review": "list", "PUT /api/v1/lists/{}/review": "list",
    # 2.61.0 (#1818): the virus scanner's state + counts for the server admin (no file, no content; p261_a_api_test.py: 403 for others)
    "GET /api/admin/upload-scan": "admin",
    # 2.67.0 (#1865): Pull the chain in: the task must be visible, each waiting task that moves needs write access
    "POST /api/tasks/{}/chain/pull": "task",
    # 2.68.0 (#1839): an agent proposes old data for its person's office (only a card; p268_a_api_test.py: other person / org 404)
    "POST /api/v1/agent/proposals/import": "agent",
    # 2.126.1 B (#2125): an agent proposes table rows as tasks (a card; p21261_b_api_test.py: not shared table / list, other org 404)
    "POST /api/v1/agent/proposals/sheet-tasks": "agent",
    # 2.69.0 A (#1846): the uploaded Paperless-ngx export of one workspace (p269_a_api_test.py: member 403, outsider 404, agent refused)
    "POST /api/paperless/zip": "paperless", "POST /api/paperless/zip/part": "paperless", "GET /api/paperless/zip/preview": "paperless",
    "POST /api/paperless/zip/import": "paperless", "POST /api/paperless/zip/stop": "paperless", "DELETE /api/paperless/zip": "paperless",
    # 2.70.0 A (#1354): meeting photos into my own chat with an agent I may ask, the chat's cards = my own proposals (p270_a_api_test.py)
    "POST /api/agents/{}/meeting-images": "agent", "GET /api/agents/{}/meeting-proposals": "agent",
    # 2.71.0 B (#1459)
    "POST /api/tasks/{}/links": "tasklink", "DELETE /api/tasks/{}/links/{}": "tasklink", "PATCH /api/tasks/{}/links/{}": "tasklink",
    "POST /api/v1/tasks/{}/links": "tasklink", "DELETE /api/v1/tasks/{}/links/{}": "tasklink",
    # 2.71.0 A (#1457): rules of a list (owner / list admins; agents read + propose) -- p271_a_api_test.py: other org 404
    "GET /api/lists/{}/rules": "list", "POST /api/lists/{}/rules": "list", "PATCH /api/rules/{}": "list", "DELETE /api/rules/{}": "list",
    "POST /api/rules/{}/restore": "list", "GET /api/v1/lists/{}/rules": "list", "POST /api/v1/lists/{}/rules/proposals": "list",
    # 2.72.0 (#1333): the household budget (a list of kind budget; p272_a_budget_api_test.py)
    "GET /api/budget": "budget", "POST /api/budget/lists": "budget", "GET /api/budget/{}": "budget",
    "GET /api/budget/{}/compare": "budget",  # 2.140.0 B (#2134): the month comparison (p2140_b_api_test.py)
    # 2.140.0 B (#2136): a private device <-> office equipment (p2140_b_api_test.py)
    "GET /api/life/devices/{}/link": "devlink", "POST /api/life/devices/{}/to-office": "devlink", "POST /api/life/device-links/{}/pull": "devlink",
    "DELETE /api/life/device-links/{}": "devlink", "GET /api/office/equipment/{}/link": "devlink", "POST /api/office/equipment/{}/to-device": "devlink",
    "POST /api/budget/{}/cats": "budget", "PATCH /api/budget/cats/{}": "budget", "DELETE /api/budget/cats/{}": "budget",
    "POST /api/budget/{}/entries": "budget", "PATCH /api/budget/entries/{}": "budget", "DELETE /api/budget/entries/{}": "budget",
    "GET /api/budget/{}/recurring": "budget", "POST /api/budget/{}/recurring": "budget", "PATCH /api/budget/recurring/{}": "budget",
    "DELETE /api/budget/recurring/{}": "budget", "POST /api/budget/recurring/{}/book": "budget",
    "GET /api/budget/{}/contracts": "budget", "POST /api/budget/{}/contracts": "budget",
    "POST /api/budget/{}/import/parse": "budget", "POST /api/budget/{}/import/commit": "budget",
    # 2.146.0 C (#2455): the import runs of a budget (p2146_c_api_test.py: another person 404)
    "GET /api/budget/{}/import/runs": "budget", "POST /api/budget/{}/import/runs/{}/undo": "budget",
    "POST /api/budget/entries/{}/files": "budget", "GET /api/budget/files/{}": "budget", "DELETE /api/budget/files/{}": "budget",
    # 2.73.0 A (#661): several servers in one app (the person's own server accounts; p273_a_api_test.py)
    "GET /api/servers": "servers", "POST /api/servers": "servers", "PATCH /api/servers/{}": "servers", "DELETE /api/servers/{}": "servers",
    "POST /api/servers/{}/restore": "servers", "PATCH /api/servers/self": "servers", "POST /api/servers/code": "servers", "GET /api/servers/{}/data": "servers",
    "GET /api/servers/{}/tasks/{}": "servers", "POST /api/servers/{}/tasks": "servers", "PATCH /api/servers/{}/tasks/{}": "servers", "POST /api/servers/{}/tasks/{}/{}": "servers",
    "DELETE /api/servers/{}/tasks/{}": "servers", "GET /api/servers/{}/search": "servers", "GET /api/servers/{}/events": "servers", "GET /api/servers/{}/news": "servers",
    "POST /api/servers/{}/news/read": "servers", "POST /api/servers/move": "servers",
    # 2.74.0 (#338): the supporter licence -- the person's own licence + the yearly hint (user_id = me), the server licence
    # (need_admin, the instance settings); no organisation data at all
    "GET /api/supporter": "own", "PUT /api/supporter/{}": "own", "DELETE /api/supporter/{}": "own", "POST /api/supporter/{}/swap": "own",
    "PATCH /api/supporter/nudge": "own",
    # 2.75.0 (#1411): the built-in assistant (session only; p275_a_api_test.py)
    "GET /api/assistant": "assistant", "PUT /api/assistant/lists": "assistant", "GET /api/assistant/log": "assistant",
    "POST /api/assistant/run": "assistant", "GET /api/admin/assistant": "assistant",
    # 2.83.0 (#1427): the header strip of a list (need_list like the list icon; p283_c_api_test.py) and of an owner's folder
    "PUT /api/lists/{}/header": "list", "POST /api/lists/{}/header": "list", "GET /api/list-header/{}/{}.jpg": "list",
    "GET /api/folder-heads": "folder", "PUT /api/folder-heads": "folder",
    # 2.84.0 A (#1198): e-mail as an input of the hub (p284_a_api_test.py)
    "POST /api/hubmail/address": "hubmail", "DELETE /api/hubmail/address": "hubmail", "GET /api/hubmail/mails": "hubmail",
    "GET /api/hubmail/inbox": "hubmail", "GET /api/hubmail/mails/{}": "hubmail", "GET /api/hubmail/mails/{}/files/{}": "hubmail",
    "GET /api/hubmail/targets": "hubmail", "POST /api/hubmail/mails/{}/assign": "hubmail", "DELETE /api/hubmail/mails/{}": "hubmail",
    "POST /api/hubmail/mails/{}/restore": "hubmail",
    # 2.141.0 B (#2140, #2139): the HTML view, a task / an event from a mail (only into lists / calendars of the mail's workspace), the mail of a task / event
    "GET /api/hubmail/mails/{}/html": "hubmail", "GET /api/hubmail/mails/{}/make": "hubmail", "POST /api/hubmail/mails/{}/task": "hubmail",
    "POST /api/hubmail/mails/{}/event": "hubmail", "GET /api/hubmail/links": "hubmail",
    # 2.141.0 A (#2141, #2138): the mailbox of a workspace (its admins / the own private space), compose + send (hbm_can write)
    "GET /api/hubmail/mailboxes": "hubmail", "GET /api/hubmail/mailbox": "hubmail", "PUT /api/hubmail/mailbox": "hubmail", "DELETE /api/hubmail/mailbox": "hubmail",
    "POST /api/hubmail/mailbox/check": "hubmail", "POST /api/hubmail/mailbox/poll": "hubmail", "GET /api/hubmail/compose": "hubmail", "POST /api/hubmail/send": "hubmail",
    # 2.85.0 B (#1162): feeds, a person's own (no organisation, never an agent's; p285_b_api_test.py: another person gets 404)
    "GET /api/feeds": "own", "POST /api/feeds": "own", "DELETE /api/feeds/{}": "own", "POST /api/feeds/{}/restore": "own",
    "GET /api/feeds/items": "own", "POST /api/feeds/read": "own", "POST /api/feeds/items/{}/later": "own",
    "GET /api/feeds/opml": "own", "POST /api/feeds/opml": "own",
    # 2.87.9 (#1913): an organisation's own symbol picture (its admins set / remove it, only its members get it; p287b_a_api_test.py)
    "POST /api/orgs/{}/icon": "org", "DELETE /api/orgs/{}/icon": "org", "GET /api/org-icon/{}/{}.png": "org",
    # 2.89.0 (#1916, D): tables step 2 -- carrying rows over by button (sheets/step2.py: the sheet writable, the target list / office
    # of the same space, people only; p289_d_api_test.py)
    "GET /api/sheets/{}/links": "sheet", "POST /api/sheets/{}/to-tasks": "sheet", "POST /api/sheets/{}/to-offer": "sheet",
    "POST /api/sheets/{}/rows-from-list": "sheet", "POST /api/sheets/{}/links/{}/undo": "sheet", "POST /api/sheets/{}/links/{}/redo": "sheet",
    # 2.117.0 B (#2285): PDF files of a framework contract (office area: members read, admins write, another area 404; p2117_b_api_test.py)
    "GET /api/office/contracts/{}/files": "office", "POST /api/office/contracts/{}/files": "office",
    "GET /api/office/contracts/{}/files/{}": "office", "PATCH /api/office/contracts/{}/files/{}": "office",
    "DELETE /api/office/contracts/{}/files/{}": "office", "POST /api/office/contracts/{}/files/{}/restore": "office",
    # 2.120.0 B (#2088): the customer's documents in the portal (cookie address + space + client, another client / space /
    # a draft 404) and the office's "Send portal link" (a client of the office area only; p2120_b_api_test.py)
    "GET /portal/docs/{}/pdf": "portal", "POST /api/office/clients/{}/portal-link": "office",
    # 2.112.1 B (#2058): external share links (p21121_b_api_test.py)
    "GET /api/files/nodes/{}/ext-links": "fileextlink", "POST /api/files/nodes/{}/ext-links": "fileextlink",
    "POST /api/files/ext-links/{}/regenerate": "fileextlink", "DELETE /api/files/ext-links/{}": "fileextlink",
    "POST /api/files/ext-links/{}/restore": "fileextlink", "GET /s/f/{}": "fileextlink", "POST /s/f/{}/unlock": "fileextlink",
    "GET /s/f/{}/d/{}": "fileextlink", "GET /s/f/{}/v/{}": "fileextlink", "GET /s/f/{}/zip": "fileextlink",
    # 2.138.0 D (#2256): number ranges of the office area one works in, admins write (p2138_d_api_test.py)
    "GET /api/office/number-ranges": "office", "POST /api/office/number-ranges/{}": "office",
    # 2.144.0 A (#2412): Stop in the agent chat (who may write the agent) and the agent's confirmation (p2144_a_api_test.py)
    "POST /api/agents/{}/abort": "agent", "POST /api/v1/agent/aborted": "agent",
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
