#!/usr/bin/env python3
"""2.87.9 (#1919) the freelancer parity guard: every route of the server -- the web app's (/api/...), the public pages,
CalDAV / CardDAV and the REST API's (/api/v1/...) -- is either checked for a person WITHOUT an organisation (a freelancer:
the own private workspace, the own personal office, its own admin there) or listed with the reason why there is nothing to
check without an organisation. Static like tests/tenant_coverage_test.py: reads app.py + kalmido/, no container.
 1. every route has an entry in ROUTES (its area), nothing in ROUTES is stale
 2. every area is in KINDS: a matrix area names the suite that calls it as a person without an organisation, and that
    suite carries the marker "freelancer-matrix: <area>" and runs in tests/run_all.sh (so an area cannot be claimed without
    a test that runs); an n/a area carries its reason
 3. 2.421.0 A (#2936): every write route (POST / PUT / PATCH / DELETE) of a matrix area is called by a suite of its area
    (write_proven: the path with its ids and the method on the line); the old ones without a call stand in WRITE_UNPROVEN,
    which may only shrink
A new route fails here until somebody decides which area it belongs to (and the freelancer suite of that area calls it:
p287b_a_freelancer_api_test.py sweeps every GET of the matrix areas as a freelancer and fails on 403 / 5xx) or why it needs
no check. The fixture "Selbstständige" for new suites: tests/freelancer_fixture.py.
usage: python3 -I tests/freelancer_coverage_test.py      (exit 0 = every route covered; the last line is the summary)"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes_ast import app_routes  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
SUITE = "p287b_a_freelancer_api_test.py"

# area -> ("matrix", the suite(s) calling it as a person without an organisation) | ("n/a", why there is nothing to check)
KINDS = {
    # ---- checked as a freelancer (the suites carry "freelancer-matrix: <area>")
    "tasks": ("matrix", SUITE + ": tasks, comments, subtasks, attachments, tags, notes, search, trash, day plan, roadmap, export "
                        "and import in the private workspace; every GET of the area as the freelancer (no 403 / 5xx); "
                        "p2477_quicknote_api_test.py: her private list Notes of the quick note, sharing refused, an empty note gone for good (2.477.0)"),
    "lists": ("matrix", SUITE + ": private lists and folders, sections, fields, templates, filters, forms, rules, views; every GET; "
                        "p2577_a_views_api_test.py: shared views of the own project (2.577.0)"),
    "office": ("matrix", SUITE + ", p2666_c_bilanz_test.py, p2199_b_office_test.py (2.199.0: a quotation of the personal office in a private folder, the folder routes, her agent), p2473_a_api_test.py, p288_a_api_test.py, p293_a_api_test.py, p293_b_api_test.py, p294_a_api_test.py, p295_a_api_test.py, p295_b_api_test.py, p2111_a_api_test.py, p2113c_a_api_test.py, p2110_b_api_test.py: the personal office (the freelancer is its admin): settings, company "
                         "fields, private clients, quotation, invoice, finalising, PDF, e-invoice; receipts, newsletter, Paperless; document "
                         "templates with signature, logbook (2.93.0); travel expenses with the per diem, its report and import (2.95.0); undo of the editors (2.111.0); "
                         "p2137_a_api_test.py: the owner exports the personal office (export, recovery key) and imports an organisation's office into it (2.137.0); p2146_d_api_test.py: the retention export of the own records before a deletion (2.146.0); p2483_a_series_api_test.py: her agent reads her invoice series, subscriptions and the series fields of her invoices (2.483.0); p2616_c_fints_test.py: her bank fetch over FinTS (2.616.0)"),
    "files": ("matrix", SUITE + ", p2353_a_lockfolder_test.py, p2353_a_scanlock_test.py (2.353.0: a locked private folder, scans refused there), p2199_a_fsref_test.py (2.199.0: reference nodes, sorting by hand, protected nodes in the private tree), p21121_a_api_test.py, p2122_a_api_test.py, p2122_b_api_test.py, p2122_c_api_test.py: the own file store (folders, upload, content, versions) and documents; every GET; "
                         "file requests of a private folder, tags of files / folders, the tag filter, the documents' filters, bulk change, ZIP, CSV, documents via the API (2.122.0); "
                         "p2154_a_api_test.py: a stack split in the private workspace, its undo, a private document linked with a private task (2.154.0); "
                         "p2207_a_scan_keys_test.py: a scan inbox of the own documents, its upload key and the folder watcher downloads (2.207.0); "
                         "p2429_a_ablage_view_test.py: only the file store's own folders, the collections \"From <area>\" of the private workspace (2.429.0)"),
    "wiki": ("matrix", SUITE + ", p299_a_api_test.py: knowledge pages in the private workspace (create, change, search, export, trash; "
                       "2.99.0: page files, ZIP import with PDFs / pictures; 2.123.0: p2123_b_api_test.py shares of pages / folders, p2123_a_api_test.py page history, text search; 2.143.0: p2143_b_api_test.py the trash, delete for good, empty; "
                       "2.177.0: p2177_a_api_test.py the large ZIP import in pieces into the private workspace; "
                       "2.200.0: p2200_c_wiki_agent_test.py her own agent on pages / folders she shared with it, API v1; "
                       "2.488.0: p2488_wiki_files_v1_test.py her agent reads the files of her shared pages)"),
    "pim": ("matrix", SUITE + ", p294_b_api_test.py, p21191_a_api_test.py, p2111_b_api_test.py, p2155_b_absence_cal_test.py, p2351_b_contacts_tree_test.py: own calendars, events, address books, contacts (2.351.0: in folders, her agent), the booking page; CalDAV / CardDAV with an app password; "
                    "invitation mails and the subscription link of an own calendar (2.111.0)"),
    "time": ("matrix", SUITE + ", p2116_d_api_test.py: time entries, the timer, habits; focus sessions and habit statistics over the API v1 (2.116.0)"),
    "agents": ("matrix", SUITE + ": the freelancer's own agent (my agents, its token, chat, jobs, share of a private list) and "
                         "the agent API with that agent's token; p2491_a_replystyle_test.py: her wishes for her agent's replies (2.491.0)"),
    "team": ("matrix", SUITE + ": the people list, direct messages and discovery without an organisation (no team rooms of "
                       "an organisation, nothing of another workspace); p2113b_b_api_test.py: a private channel with files, "
                       "rename / archive / restore as its own admin, groups only with people one works with (2.113.1)"),
    "hub": ("matrix", SUITE + ", p2125_a_api_test.py, p2361_a_texts_test.py, p2141_a_api_test.py, p2141_b_api_test.py, p2352_d_mailtrim_test.py, p2155_b_absence_cal_test.py: absences, bookings and hub mail in the personal area (the freelancer is its own admin); "
                      "2.125.0: the own vacation account and working week, never a vacation request; 2.141.0 A: the own mailbox, reply / new e-mail; 2.141.0 B: HTML view, task / event from a private mail; 2.352.0 D: the shortened view of a private mail; p2483_a_mail_api_test.py (2.483.0): her private client's mails through the API v1 with her token and her own agent"),
    "modcards": ("matrix", "p2575_a_api_test.py: her own module cards in the private workspace (create, change, apply, delete; 2.575.0)"),
    "personal": ("matrix", SUITE + ": budget, Home & life, family, feeds, other servers, supporter licence -- private by nature; "
                           "p2140_a_api_test.py: shopping amounts, recipes, the meal plan beyond a week (2.140.0)"),
    "videos": ("matrix", "p2991_a_api_test.py: video sign-offs (2.99.1) at a private task / list / client of a person without an "
               "organisation: create, comments, versions, customer link, export, delete + restore; p2991_c_api_test.py: the own agent "
               "of such a person reads and comments them through the API v1; p2549_c_vtrash_test.py (2.549.0): her video trash, a review "
               "without a place restored into her project"),
    "obj": ("matrix", "obj_core_test.py, obj_write_test.py, p2579_c_api_test.py (2.579.0: saved document views, their counts / hits / sharing): core objects (2.558.0) in the private workspace of a person without an organisation: create, change with the version, history, undo, trash, restore, delete, shares with her own agent, her agent reads and writes"),
    "undo": ("matrix", "p2747_b_undo_core_test.py (2.747.0, #5249): the own undo step groups of a person without an organisation: listed, taken back up to a step, redone"),
    "sheets": ("matrix", "p289_b_api_test.py, p289_c_api_test.py, p289_d_api_test.py: tables (2.89.0) in the private workspace of a "
                         "person without an organisation and with that person's own agent; rows to tasks / quotation drafts; "
                         "p2124_c_api_test.py: sharing a private table (2.124.0); p2199_c_sheets_test.py: tables in her "
                         "private folders, shared with her own agent (2.199.0); p2578_c_fmt_test.py: cell formats and colour rules "
                         "of her private table, her agent's formats taken back (2.578.0)"),
    "bookmarks": ("matrix", "p297_a_api_test.py: bookmarks (2.97.0) in the private workspace of a person without an organisation"),  # 2.97.0 A (#1950)
    "life_org": ("matrix", "p2173_a_travel_care_scope_test.py: trips, staying in touch and travel expenses from a trip (2.173.0) in the "
                 "private workspace and the personal office of a person without an organisation"),  # 2.173.0 A (#2680)
    "reading": ("matrix", "p2172_b_reading_scope_test.py: feeds and read later (2.172.0) in the private workspace of a person without an organisation"),  # 2.172.0 B (#2677 #2679)
    "sectpl": ("matrix", "p2156_c_api_test.py: own section templates (save from a list, add to another, change, delete) of a person without an organisation"),  # 2.156.0 C (#2073)
    "orgschema": ("matrix", "p2609_c_schema_api_test.py: own field templates linked into her projects, the key filter, required fields, own "
                  "templates of a person without an organisation; no organisation space, no organisation labels"),  # 2.609.0 (#3373)
    "polls": ("matrix", "p298_a_api_test.py, p2484_a_polls_v1_test.py: scheduling polls (2.98.0) in the private workspace of a person without an organisation; 2.484.0: her personal agent over REST v1"),  # 2.98.0 A (#1953)
    # 2.138.0 (#1972): the recovery key of the own personal office (organisation id 0 in the route)
    "orgcrypt": ("matrix", "p2138_c_api_test.py: the encryption state and the recovery key (step-up) of the personal office of a "
                           "person without an organisation"),
    "own": ("matrix", SUITE + ": the own settings, profile, tokens, app passwords, push, account export / import"),
    "industry": ("matrix", "p2578_b_industry_test.py: the app's industry (2.578.0) of a person without an organisation: chosen for her own area, the sample follows it"),  # 2.578.0 (#4573)
    # ---- nothing to check without an organisation (with the reason)
    "auth": ("n/a", "signing in, setting up and securing the own account: the same for every person, before any workspace"),
    "public": ("n/a", "pages and facts without data of a person (app shell, health, version, manifest, share target, QR code)"),
    "test": ("n/a", "test containers only (KALMIDO_TEST=1): an uncaught error on purpose (2.359.0 #3023), not in the product"),  # 2.359.0 (#3023)
    # 2.102.0 (#1999)
    "clienterr": ("n/a", "the web app's own unexpected error (message cut of data, place in the code, version, area): written as "
                         "nobody into the one project list the server operator chose, nothing is read back or answered"),
    # 2.421.0 A (#2936): judged apart for both kinds of server
    "admin": ("n/a", "the server operator's administration (need_admin). Self-hosted: a freelancer running the own server is its "
                     "operator with exactly these pages (p2473_a_api_test.py sets up a server without any organisation). Hosted: "
                     "the operator's pages are not the freelancer's -- the own area is own / office / agents (p2421_a_api_test.py: "
                     "a person on a server the admin only created the account on, without any admin switch)"),
    # 2.144.0 D (#797)
    "operator": ("n/a", "the hosting operator's interface (a token from a file, off by default, never a person or a session): "
                        "instance-wide numbers and operating actions only, no content of any person or organisation (p2144_d_api_test.py; accounts by number: p2485_b_api_test.py)"),
    "orgadmin": ("n/a", "managing an organisation (members, admins, its lists, export, encryption): only for its members and "
                        "admins; without an organisation there is nothing to manage (the personal office is reached under "
                        "office, the private workspace under every other area)"),
    "link": ("n/a", "pages opened by an unguessable link (public list link, customer status page / portal, approval link, "
                    "calendar feed, the booking page of a person (2.94.0)): the same for the link of a private list or document as for an organisation's"),
    "token": ("n/a", "inbound hooks addressed by the secret of one list / environment / repository: no person, no workspace"),
    "pure": ("n/a", "a pure transformation of the request body (an outline file into a tree): no stored data"),
}

ROUTES = {
    # 2.593.0 (#4590): reset the look and comfort settings, with preview and one undo (p2593_d_reset_test.py, freelancer-matrix: own)
    "POST /api/settings/reset": "own",
    # 2.747.0 (#5246): the session undo of a master data / client dialog under its save url (objsave.js objUndo; p2747_a_buero_test.py, freelancer-matrix: office)
    "POST /api/office/{}/{}/undo": "office", "POST /api/clients/{}/undo": "office",
    # 2.585.0 (#4350): what the undo of an account import would take back, before the confirm (p2585_d_api_test.py)
    "GET /api/imports/{}/undo-plan": "tasks",
    # 2.575.0 (#3778): own module cards of the private workspace (p2575_a_api_test.py, freelancer-matrix: modcards)
    "GET /api/modcards": "modcards", "POST /api/modcards": "modcards", "PATCH /api/modcards/{}": "modcards", "DELETE /api/modcards/{}": "modcards",
    "GET /api/industry": "industry", "PUT /api/industry": "industry",  # 2.578.0 (#4573): p2578_b_industry_test.py
    # 2.570.0 (#4783): the history of an office row / a client (office/owrite.py ow_history, the rights of the save route): p2570_a_office_test.py
    "GET /api/office/trips/{}/history": "office", "GET /api/office/trips/{}/items/{}/history": "office", "GET /api/office/trips/purposes/{}/history": "office", "GET /api/office/fixed-costs/{}/history": "office",
    "GET /api/office/cashflow/adjust/{}/history": "office", "GET /api/office/cards/{}/history": "office", "GET /api/office/cards/lines/{}/history": "office", "GET /api/office/bank/rules/{}/history": "office",
    "GET /api/office/series/{}/history": "office", "GET /api/office/meals/{}/history": "office", "GET /api/office/meals/choices/{}/history": "office", "GET /api/office/letters/{}/history": "office",
    "GET /api/office/agreements/{}/history": "office", "GET /api/office/doc-templates/{}/history": "office", "GET /api/office/gen-docs/{}/history": "office", "GET /api/office/deals/{}/history": "office",
    "GET /api/office/letter-blocks/{}/history": "office", "GET /api/office/vehicles/{}/history": "office", "GET /api/office/drives/{}/history": "office", "GET /api/clients/{}/history": "office",
    # 2.556.0 (#4685): "New for you" after an update (p2556_b_whatsnew_api_test.py as the freelancer)
    "GET /api/whatsnew": "own", "POST /api/whatsnew/seen": "own",
    # 2.545.0 (#4595): the switch "Extend the lock" of the own office (p2545_b_rethold_test.py as the freelancer)
    "GET /api/office/settings/retention-hold": "office", "PUT /api/office/settings/retention-hold": "office",
    # 2.394.0 B (#3377): the issue import of a project's own repository (p2394_b_git_issues_test.py as the freelancer)
    "POST /api/repos/{}/issues/import": "tasks",
    # 2.530.0 C (#4315): the undo of deleting a trip / a travel receipt from the office trash (p2530_c_office_trash_test.py)
    "POST /api/office/trips/trash/{}/restore": "office",
    # 2.552.0 (#4561 B21): the undo of deleting a credit card position from the office trash (p2552_b_dataloss_test.py as the freelancer)
    "POST /api/office/cards/trash/{}/restore": "office",
    "POST /api/office/trash/undo/{}/{}": "office",  # 2.567.0 (#4707): p2567_c_office_trash_test.py (other office 403 / 404, member 403)
    # 2.905.0 (#5414): the office trash's rows in the core's trash (p2905_d_office_trash_4c_test.py as the freelancer)
    "POST /api/office/trash/core/{}/{}/restore": "office", "DELETE /api/office/trash/core/{}/{}": "office",
    # 2.488.0 (#3363): the hosted MCP access (p2488_mcp_oauth_test.py: the person without an organisation connects her own agent)
    "GET /.well-known/oauth-protected-resource": "public", "GET /.well-known/oauth-protected-resource/mcp": "public",
    "GET /.well-known/oauth-authorization-server": "public", "GET /.well-known/oauth-authorization-server/mcp": "public",
    "POST /oauth/register": "agents", "GET /oauth/authorize": "agents", "POST /oauth/authorize": "agents", "POST /oauth/token": "agents",
    "POST /oauth/revoke": "agents", "GET /mcp": "agents", "POST /mcp": "agents", "DELETE /mcp": "agents",
    "GET /api/my/mcp-grants": "agents", "DELETE /api/my/mcp-grants/{}": "agents",
    # 2.557.0 B (#4670): the server agent (p2557_b_srvagent_test.py: the person without an organisation sets up her own one)
    "GET /api/agents/{}/server": "agents", "PUT /api/agents/{}/server": "agents", "GET /api/agents/{}/server/models": "agents",
    "GET /api/agents/{}/server/runs": "agents",
    # 2.569.0 B (#4675): team projects (p2569_b_srvteam_test.py: her personal one has no limits per member, no team agent of her own)
    "GET /api/agents/{}/server/team": "agents", "PUT /api/agents/{}/server/team": "agents", "GET /api/lists/{}/agent-proposals": "agents",
    "POST /api/orgs/{}/server-agents": "orgadmin",
    # 2.391.0 C (#3362): setting up integrations through /api/v1 (p2391_c_setup_api_test.py as the freelancer; an organisation's webhooks: its admins)
    "GET /api/v1/me/tokens": "own", "POST /api/v1/me/tokens": "own", "DELETE /api/v1/me/tokens/{}": "own",
    "GET /api/v1/me/webhooks": "own", "POST /api/v1/me/webhooks": "own", "PATCH /api/v1/me/webhooks/{}": "own",
    "DELETE /api/v1/me/webhooks/{}": "own", "POST /api/v1/me/webhooks/{}/secret": "own", "POST /api/v1/me/webhooks/{}/test": "own",
    "GET /api/v1/me/webhooks/{}/log": "own",
    "GET /api/v1/orgs/{}/webhooks": "orgadmin", "POST /api/v1/orgs/{}/webhooks": "orgadmin", "PATCH /api/v1/orgs/{}/webhooks/{}": "orgadmin",
    "DELETE /api/v1/orgs/{}/webhooks/{}": "orgadmin", "POST /api/v1/orgs/{}/webhooks/{}/secret": "orgadmin",
    "POST /api/v1/orgs/{}/webhooks/{}/test": "orgadmin", "GET /api/v1/orgs/{}/webhooks/{}/log": "orgadmin",
    "POST /api/v1/lists/{}/repos": "lists", "PUT /api/v1/lists/{}/repos/version-field": "lists",
    "PATCH /api/v1/repos/{}": "tasks", "DELETE /api/v1/repos/{}": "tasks",
    # 2.353.0 A (#2758): locked folders of the file store (files/fslock.py, p2353_a_lockfolder_test.py)
    "GET /api/files/lock/{}": "files", "POST /api/files/lock/{}/start": "files", "GET /api/files/lock/{}/todo": "files", "GET /api/files/lock/{}/raw/{}": "files", "POST /api/files/lock/{}/convert/{}": "files", "POST /api/files/lock/{}/finish": "files", "POST /api/files/lock/{}/stop": "files", "POST /api/files/lock/{}/keys": "files", "POST /api/files/lock/upload": "files", "POST /api/files/lock/folder": "files", "POST /api/files/lock/rename/{}": "files", "POST /api/files/lock/version/{}": "files", "POST /api/files/lock/move/{}": "files", "POST /api/files/lock/{}/rotate": "files", "GET /api/files/lock/movecheck/{}": "files",
    # 2.393.2 A (#3374): flow figures of a project (p2393_2_a_api_test.py as the freelancer)
    "GET /api/lists/{}/flow": "lists", "GET /api/v1/lists/{}/flow": "lists",
    # ---- admin (54)
    "DELETE /api/admin/agents/{}": "admin", "DELETE /api/admin/agents/{}/machines/{}": "admin",
    "DELETE /api/admin/alerts": "admin", "DELETE /api/admin/backups/{}": "admin", "DELETE /api/admin/groups/{}": "admin",
    "DELETE /api/admin/groups/{}/avatar": "admin", "GET /api/admin/agent-policy": "admin", "GET /api/admin/agents": "admin",
    "GET /api/admin/agents/audit": "admin", "GET /api/admin/agents/{}/audit": "admin", "GET /api/admin/agents/{}/model-usage": "admin",  # 2.992.0 (#5684)
    "GET /api/admin/mcp-grants": "admin", "DELETE /api/admin/mcp-grants/{}": "admin",  # 2.674.0 (#4028): the apps of team agents
    "GET /api/admin/agents/{}/machines": "admin", "GET /api/admin/alerts": "admin", "GET /api/admin/assistant": "admin",
    "GET /api/admin/backups": "admin", "GET /api/admin/backups/{}/download": "admin", "POST /api/admin/backups/{}/download": "admin", "GET /api/admin/client-ip": "admin",
    "GET /api/admin/health": "admin",  # 2.102.0 D (#1994): the server's capacity numbers
    "GET /api/admin/retention": "admin",  # 2.152.0 (#2165): the retention runs in numbers
    "GET /api/admin/lists/orphaned": "admin", "GET /api/admin/orgcrypt": "admin", "GET /api/admin/related": "admin",
    "GET /api/admin/storage-check": "admin", "GET /api/admin/upload-scan": "admin",
    "GET /api/v1/admin/agents/{}/audit": "admin", "GET /api/v1/admin/status": "admin", "GET /api/v1/admin/orgs/activity": "admin", "GET /api/admin/orgs/activity": "admin", "GET /api/v1/admin/users": "admin",
    "PATCH /api/admin/agents/{}": "admin", "PATCH /api/admin/alerts": "admin", "PATCH /api/admin/backups": "admin",
    "PATCH /api/admin/groups/{}": "admin", "PATCH /api/admin/settings": "admin", "POST /api/admin/agents": "admin",
    "POST /api/admin/agents/{}/avatar": "admin", "POST /api/admin/agents/{}/reset": "admin",
    "POST /api/admin/agents/{}/secret": "admin", "POST /api/admin/agents/{}/setup-code": "admin",
    "POST /api/admin/agents/{}/test": "admin", "POST /api/admin/agents/{}/token": "admin",
    "POST /api/admin/alerts/test": "admin", "POST /api/admin/backups": "admin", "POST /api/admin/backups/restore": "admin",
    "POST /api/admin/backups/upload": "admin", "POST /api/admin/backups/passphrase-check": "admin",  # 2.581.0 (#4826)
    # 2.143.0 B (#2152): the off-site target is a setting of the server (its operator), not of a workspace
    "GET /api/admin/backups/offsite": "admin", "PATCH /api/admin/backups/offsite": "admin",
    "POST /api/admin/backups/offsite/test": "admin", "POST /api/admin/backups/offsite/upload": "admin",
    "POST /api/admin/backups/{}/verify": "admin", "GET /api/admin/backups/purged-preview": "admin", "POST /api/admin/groups": "admin",
    "POST /api/admin/groups/{}/avatar": "admin", "POST /api/admin/mail/poll": "admin", "POST /api/admin/oidc/check": "admin", "PUT /api/admin/oidc/draft": "admin", "DELETE /api/admin/oidc/draft": "admin", "POST /api/admin/oidc/draft/apply": "admin",  # 2.166.0 (#2633)
    "POST /api/admin/setup": "admin", "PUT /api/admin/agent-policy": "admin", "PUT /api/admin/announcement": "admin",
    # 2.144.0 D (#797): the hosting operator's interface (a token from a file, off by default)
    "GET /api/operator/status": "operator", "POST /api/operator/setup-code": "operator", "PUT /api/operator/notice": "operator",
    # 2.485.0 (#3939): one customer's account by number (lock, unlock, quota, delete) and the default quota
    "POST /api/operator/accounts/find": "operator", "GET /api/operator/accounts/{}": "operator",
    "PUT /api/operator/accounts/{}": "operator", "DELETE /api/operator/accounts/{}": "operator",
    "PUT /api/operator/quota-default": "operator",
    "PUT /api/admin/groups/{}/avatar": "admin", "PUT /api/admin/oidc": "admin", "PUT /api/admin/orgcrypt": "admin",
    "PUT /api/admin/related": "admin", "PUT /api/layouts/std/{}": "admin", "PUT /api/v1/admin/announcement": "admin",
    # ---- agents (72)
    "DELETE /api/agent-schedules/{}": "agents", "DELETE /api/my/agents/{}": "agents",
    "GET /api/lists/{}/ideas": "agents", "POST /api/proposals/{}/ideas": "agents",  # 2.156.0 A (#1201): ideas of the mind map
    "DELETE /api/my/agents/{}/machines/{}": "agents", "DELETE /api/v1/agent/quota": "agents", "GET /api/agents": "agents",
    "GET /api/agents/jobs": "agents", "GET /api/agents/jobs/{}/steps": "agents", "GET /api/agents/usage": "agents",
    "GET /api/agents/{}/bridges": "agents", "GET /api/agents/{}/chat": "agents",
    # 2.98.0 A (#1953): scheduling polls (p298_a_api_test.py) - routes below this line
    "GET /api/polls": "polls", "POST /api/polls": "polls", "GET /api/polls/{}": "polls", "PATCH /api/polls/{}": "polls",
    "DELETE /api/polls/{}": "polls", "POST /api/polls/{}/restore": "polls", "POST /api/polls/{}/decide": "polls",
    "POST /api/polls/{}/reopen": "polls", "POST /api/polls/{}/move-space": "polls", "GET /s/v/{}": "link", "POST /s/v/{}": "link",
    "GET /api/v1/polls": "polls", "POST /api/v1/polls": "polls", "GET /api/v1/polls/{}": "polls",  # 2.484.0 (#2200)
    "GET /s/v/time.js": "public",
    # (2.98.0 spacer A)
    # 2.98.0 B (#1954): questionnaires (p298_b_api_test.py) - routes below this line
    "GET /api/forms/{}/entries": "lists", "GET /api/forms/{}/entries.csv": "lists",
    "GET /api/forms/{}/client-link": "lists", "GET /api/clients/{}/forms": "office",  # 2.102.0 C (#2201)
    # (2.98.0 spacer B)
    # 2.98.0 C (#2180 #2181): office menu, tables (p298_c_ui.js) - routes below this line
    # (2.98.0 spacer C)
    # 2.98.0 D (#2163 #2178 #2184): polish (p298_d_api_test.py) - routes below this line
    # (2.98.0 spacer D)
    # 2.111.0 A (#2233): undo of the office editors (p2111_a_api_test.py) - routes below this line
    "POST /api/office/undo/{}/{}": "office",
    # (2.111.0 spacer A)
    # 2.272.0 E2 (#3038): the trash of task / project files and of the office (p2272_e2_attach_trash_test.py) - routes below this line
    "POST /api/attachments/{}/restore": "tasks", "POST /api/list-files/{}/restore": "lists",
    "DELETE /api/attachments/{}/purge": "tasks", "DELETE /api/list-files/{}/purge": "lists",  # 2.272.0 F (#3038, E2-H2)
    "GET /api/office/trash": "office", "POST /api/office/trash/{}/restore": "office", "DELETE /api/office/trash/{}": "office",
    # (2.272.0 spacer E2)
    # 2.153.0 (#2028): letters (p2106_a_api_test.py) - routes below this line
    "GET /api/office/letters": "office", "POST /api/office/letters": "office", "GET /api/office/letters/recipients": "office",
    "GET /api/office/letters/profile": "office", "PUT /api/office/letters/profile": "office",
    "DELETE /api/office/letters/profile/image": "office", "GET /api/office/letters/{}": "office", "PATCH /api/office/letters/{}": "office",
    "DELETE /api/office/letters/{}": "office", "POST /api/office/letters/{}/restore": "office", "GET /api/office/letters/{}/pdf": "office",
    "POST /api/office/letters/{}/sent": "office", "POST /api/office/letters/{}/delivered": "office",
    "DELETE /api/office/letters/{}/delivered": "office", "POST /api/office/letters/{}/template": "office",
    # 2.153.0 (#2028): letter links (p2106_b_api_test.py) - routes below this line
    "GET /api/office/letters/{}/links": "office", "POST /api/office/letters/{}/links": "office", "DELETE /api/office/letters/{}/links/{}": "office",
    "GET /api/office/letters/{}/thread": "office", "GET /api/office/letters/threads": "office", "GET /api/office/letters/doc/{}": "office",
    "POST /api/office/letters/doc/{}/deadline-task": "office",
    # 2.153.0 (#2029 #2030): letter mail, text blocks (p2106_c_api_test.py) - routes below this line
    "GET /api/office/receipt-mail": "office", "POST /api/office/receipt-mail": "office",  # 2.424.0 B (#3450)
    "GET /api/office/mail-profile": "office", "PUT /api/office/mail-profile": "office",  # 2.439.0 (#3617): p2439_a_mailsig_test.py
    "GET /api/office/letters/mail-info": "office", "GET /api/office/letters/{}/mail-draft": "office", "POST /api/office/letters/{}/send-mail": "office",
    "GET /api/office/letter-blocks": "office", "GET /api/office/letter-blocks/starters": "office", "POST /api/office/letter-blocks": "office",
    "PATCH /api/office/letter-blocks/{}": "office", "DELETE /api/office/letter-blocks/{}": "office", "POST /api/office/letter-blocks/{}/restore": "office",
    # 2.153.0 (#2031): agents and letters (p2106_d_api_test.py) - routes below this line
    "GET /api/v1/office/letters": "office", "POST /api/v1/office/letters": "office", "GET /api/v1/office/letters/{}": "office",
    "PATCH /api/v1/office/letters/{}": "office", "POST /api/v1/office/letters/{}/links": "office",
    "GET /api/office/letters/doc/{}/agents": "office", "POST /api/office/letters/doc/{}/ask-agent": "office",
    # 2.97.0 A (#1950): bookmarks (p297_a_api_test.py) - routes below this line
    "GET /api/bookmarks": "bookmarks", "POST /api/bookmarks": "bookmarks", "GET /api/bookmarks/{}": "bookmarks",
    "PATCH /api/bookmarks/{}": "bookmarks", "DELETE /api/bookmarks/{}": "bookmarks",
    "POST /api/bookmarks/{}/restore": "bookmarks", "POST /api/bookmarks/{}/refresh": "bookmarks",
    "GET /api/bookmarks/{}/image": "bookmarks", "POST /api/bookmarks/move-space": "bookmarks",
    # 2.156.0 C (#2073): section templates (p2156_c_api_test.py)
    "GET /api/section-templates": "sectpl", "POST /api/section-templates": "sectpl", "PATCH /api/section-templates/{}": "sectpl",
    "DELETE /api/section-templates/{}": "sectpl", "POST /api/lists/{}/sections/from-template": "sectpl",
    # 2.609.0 (#3372): own ticket types of the private workspace (p2609_c_ttypes_api_test.py, freelancer-matrix: tasks)
    "GET /api/ticket-types": "tasks", "POST /api/ticket-types": "tasks", "PATCH /api/ticket-types/{}": "tasks",
    "DELETE /api/ticket-types/{}": "tasks", "GET /api/lists/{}/ticket-types": "tasks",
    "GET /api/v1/ticket-types": "tasks", "POST /api/v1/ticket-types": "tasks", "PATCH /api/v1/ticket-types/{}": "tasks",
    "DELETE /api/v1/ticket-types/{}": "tasks", "GET /api/v1/lists/{}/ticket-types": "tasks",
    # 2.609.0 (#3373): fields, labels of an organisation / a person's own field templates (p2609_c_schema_api_test.py)
    "GET /api/org-fields": "orgschema", "POST /api/org-fields": "orgschema", "PATCH /api/org-fields/{}": "orgschema",
    "DELETE /api/org-fields/{}": "orgschema", "GET /api/lists/{}/org-fields": "orgschema", "PUT /api/lists/{}/org-fields/{}": "orgschema",
    "GET /api/org-labels": "orgschema", "POST /api/org-labels": "orgschema", "PATCH /api/org-labels/{}": "orgschema",
    "DELETE /api/org-labels/{}": "orgschema",
    # 2.96.0 C (#2015): job cards in the agent chat
    "GET /api/agents/{}/meeting-proposals": "agents", "GET /api/agents/{}/schedules": "agents",
    "GET /api/agents/{}/share": "agents", "GET /api/assistant": "agents", "GET /api/assistant/log": "agents",
    "GET /api/my/agents": "agents", "GET /api/my/agents/{}/audit": "agents", "GET /api/my/agents/{}/model-usage": "agents",  # 2.992.0 (#5684)
    "GET /api/my/agents/{}/machines": "agents", "GET /api/proposals/agents": "agents",
    "GET /api/proposals/{}": "agents", "GET /api/v1/agent": "agents", "GET /api/v1/agent/chats": "agents",
    "GET /api/v1/agent/events": "agents", "GET /api/v1/agent/jobs": "agents", "GET /api/v1/agent/jobs/{}": "agents",
    "GET /api/v1/agent/quota": "agents", "GET /api/v1/agent/schedules": "agents", "GET /api/v1/agent/usage": "agents",
    "GET /api/v1/agents": "agents", "PATCH /api/agent-schedules/{}": "agents", "PATCH /api/agents/{}/schedules": "agents", "PATCH /api/agents/{}/chat/{}": "agents",
    "PATCH /api/agents/{}/color": "agents", "PATCH /api/my/agents/{}": "agents", "PATCH /api/v1/agent/jobs/{}": "agents",
    "POST /api/agent-schedules/{}/run": "agents", "POST /api/agents/jobs/{}/action": "agents",
    "POST /api/agents/{}/chat": "agents", "POST /api/agents/{}/chat/{}/choice": "agents",
    "GET /api/agents/{}/chat-prefs": "agents", "PUT /api/agents/{}/chat-prefs": "agents", "POST /api/agents/{}/chat/{}/dismiss": "agents",  # 2.233.0 A (#2848)
    "GET /api/v1/agent/chats/{}/reply-style": "agents",  # 2.491.0 (#2849): the reply style wishes (p2491_a_replystyle_test.py)
    "DELETE /api/agents/{}/chat": "agents", "DELETE /api/agents/{}/chat/{}": "agents",  # 2.152.0 D (#2175): p2103_d_api_test.py
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
    "POST /api/v1/agent/proposals/sheet-tasks": "agents",  # 2.126.1 B (#2125): p21261_b_api_test.py, the freelancer's own agent
    "POST /api/v1/agent/proposals/shoot": "agents", "POST /api/v1/agent/proposals/time": "agents",
    "POST /api/v1/agent/typing": "agents", "POST /api/v1/agent/usage": "agents",
    "POST /api/v1/agents/{}/chat/{}/choice": "agents", "POST /api/v1/agents/{}/chat/{}/reactions": "agents",
    "PUT /api/agents/{}/autoshare": "agents", "PUT /api/agents/{}/permission-mode": "agents",
    "GET /api/agents/{}/perm-users": "agents",  # 2.312.0 D (#3266): p2312_d_perm_user_test.py
    "PUT /api/assistant/lists": "agents", "PUT /api/v1/agent/quota": "agents", "PUT /api/v1/agent/status": "agents",
    # ---- auth (31)
    "DELETE /api/me/passkeys/{}": "auth", "GET /api/auth/info": "auth", "GET /api/auth/oidc/callback": "auth",
    "GET /api/auth/oidc/start": "auth", "GET /api/me/2fa": "auth", "PATCH /api/me/passkeys/{}": "auth",
    "POST /api/agent-setup/redeem": "auth", "POST /api/agent-setup/remove": "auth", "POST /api/auth/2fa": "auth",
    "POST /api/auth/2fa/passkey": "auth", "POST /api/auth/2fa/passkey/options": "auth", "POST /api/auth/enrol/passkey": "auth",
    "POST /api/auth/enrol/passkey/options": "auth", "POST /api/auth/enrol/totp": "auth",
    "POST /api/auth/enrol/totp/confirm": "auth", "POST /api/auth/forgot": "auth", "POST /api/auth/delete-cancel": "auth", "POST /api/auth/invite/accept": "auth",
    "POST /api/auth/invite/check": "auth", "POST /api/auth/link": "auth", "POST /api/auth/login": "auth",
    "POST /api/auth/logout": "auth", "POST /api/auth/passkey": "auth", "POST /api/auth/passkey/options": "auth",
    "POST /api/stepup/passkey": "auth",  # 2.223.2 C (#2871): the passkey challenge of the step-up (stepup_need)
    "POST /api/auth/setup": "auth", "POST /api/auth/signup": "auth", "POST /api/me/2fa/recovery": "auth",
    "POST /api/me/2fa/totp": "auth", "POST /api/me/2fa/totp/confirm": "auth", "POST /api/me/2fa/totp/disable": "auth",
    "POST /api/me/passkeys": "auth", "POST /api/me/passkeys/options": "auth",
    # 2.115.0 B (#2062): active sessions (p2115_b_api_test.py as a person without an organisation)
    "GET /api/me/sessions": "own", "DELETE /api/me/sessions/{}": "own", "POST /api/me/sessions/others": "own",
    # 2.485.0 (#3939): support access the client grants (p2485_a_support_test.py as a person without an organisation)
    "GET /api/support-access": "own", "POST /api/support-access": "own", "DELETE /api/support-access/{}": "own",
    # ---- files (51)
    "DELETE /api/docs/labels/{}/{}": "files", "DELETE /api/docs/mail": "files", "DELETE /api/docs/rules/{}": "files",
    "DELETE /api/docs/{}/task": "files", "DELETE /api/files/nodes/{}": "files", "DELETE /api/files/shares/{}": "files",
    "GET /api/docs/{}/split": "files", "GET /api/docs/{}/split/thumbs": "files", "POST /api/docs/{}/split": "files",  # 2.154.0 A (#1111)
    "POST /api/docs/{}/unsplit": "files", "POST /api/docs/{}/split/dismiss": "files", "POST /api/docs/{}/task/link": "files",
    "GET /api/tasks/{}/docs": "files", "GET /api/docs/split-sheet.pdf": "files",
    "GET /api/docs/{}/pages": "files", "POST /api/docs/{}/pages": "files",  # 2.777.0 B (#4874): p2777_b_docpages_test.py, freelancer-matrix: files
    "POST /api/docs/merge": "files",  # 2.959.0 (#4805): p2959_a_docpages_api_test.py, freelancer-matrix: files
    # 2.892.0 (#4873, #4806): "Optimise PDF" as a new version (p2892_c_pdfopt_test.py, freelancer-matrix: files)
    "GET /api/docs/{}/pdfopt": "files", "POST /api/docs/{}/pdfopt": "files", "POST /api/docs/pdfopt": "files",
    "GET /api/docs": "files", "GET /api/docs/facets": "files", "GET /api/docs/settings": "files",  # 2.772.0 (#4890): facets = p4890_a_api_test.py
    "GET /api/docs/{}": "files", "GET /api/docs/{}/file": "files",
    "GET /api/docs/{}/title-suggest": "files",  # 2.783.0 (#4882): p2783_b_doctitle_test.py as a person without an organisation
    "GET /api/docs/{}/receipt": "files", "GET /api/docs/{}/thumb": "files", "GET /api/files": "files",
    "GET /api/files/collections/{}": "files",  # 2.429.0 (#3580)
    "GET /api/files/folders": "files", "GET /api/files/nodes/{}": "files", "GET /api/files/nodes/{}/content": "files",
    "GET /api/files/nodes/{}/thumb": "files",  # 2.477.0 (#3936): p2477_ablagethumb_test.py without an organisation
    "GET /api/files/nodes/{}/share-targets": "files", "GET /api/files/search": "files", "GET /api/v1/documents": "files",
    "GET /api/v1/documents/{}": "files", "GET /api/v1/files": "files", "GET /api/v1/files/search": "files",
    "GET /api/v1/files/{}": "files", "GET /api/v1/files/{}/content": "files", "GET /api/v1/files/{}/text": "files",
    "POST /api/docs/fields": "files", "PATCH /api/docs/fields/{}": "files", "DELETE /api/docs/fields/{}": "files",  # 2.153.0 (#2179)
    "PATCH /api/docs/labels/{}/{}": "files", "PATCH /api/docs/rules/{}": "files", "PATCH /api/docs/{}": "files",
    "PATCH /api/files/nodes/{}": "files", "PATCH /api/files/shares/{}": "files", "PATCH /api/v1/documents/{}": "files",
    # 2.122.0 A (#2097): file requests of a folder (p2122_a_api_test.py as a freelancer: the private folder's requests)
    "GET /api/files/nodes/{}/requests": "files", "POST /api/files/nodes/{}/requests": "files", "PATCH /api/files/requests/{}": "files",
    "DELETE /api/files/requests/{}": "files", "POST /api/files/requests/{}/restore": "files",
    "GET /u/{}": "link", "POST /u/{}": "link", "GET /u/v/up.js": "public",
    # 2.96.0 A (#1941): files / folders / documents to the other workspace
    "POST /api/files/move-space": "files",
    # 2.112.1 A (#2058): several nodes into the trash / back, the ZIP download, the phone scan (p21121_a_api_test.py)
    "POST /api/files/trash": "files", "POST /api/files/restore": "files", "POST /api/files/trash/purge": "files",  # 2.589.0 (#4875)
    "GET /api/files/zip": "files", "POST /api/files/scan": "files",
    "POST /api/docs": "files", "POST /api/docs/labels/{}": "files", "POST /api/docs/mail": "files",
    "GET /api/docs/{}/flowruns": "files", "POST /api/docs/flowruns/{}/undo": "files",  # 2.581.0 (#4803): p2581_c_flows_test.py
    "POST /api/docs/rules": "files", "POST /api/docs/{}/accept": "files", "POST /api/docs/{}/redo": "files", "POST /api/docs/{}/redo/undo": "files",
    "POST /api/docs/{}/review": "files", "POST /api/docs/{}/task": "files", "POST /api/files/folders": "files",
    "POST /api/files/links": "files", "POST /api/files/nodes/{}/restore": "files", "POST /api/files/nodes/{}/shares": "files",
    "POST /api/files/nodes/{}/order": "files", "POST /api/files/refs": "files", "GET /api/files/refs/{}/{}": "files",  # 2.199.0 A (#2742): p2199_a_fsref_test.py
    "GET /api/fsref/office_doc/{}": "office", "GET /api/fsref/office_doc/{}/pdf": "office", "PATCH /api/fsref/office_doc/{}": "office",
    "PUT /api/fsref/office_doc/{}/items": "office", "GET /api/office/docs/groups": "office",  # 2.199.0 B (#2742): p2199_b_office_test.py (f)
    "GET /api/office/docs/tree": "office", "POST /api/office/docs/tree/folders": "office", "GET /api/office/gen-docs/tree": "office", "POST /api/office/gen-docs/tree/folders": "office",
    "GET /api/office/letters/tree": "office", "POST /api/office/letters/tree/folders": "office", "GET /api/office/receipts/tree": "office", "POST /api/office/receipts/tree/folders": "office",  # 2.351.0 A (#3312): p2351_a_officetree_test.py (f)
    "POST /api/files/nodes/{}/versions": "files", "POST /api/files/nodes/{}/versions/{}/restore": "files",
    "POST /api/files/upload": "files", "POST /api/v1/documents/{}/receipt-suggestion": "files", "POST /api/v1/files": "files",
    "POST /api/v1/documents": "files", "POST /api/docs/export.csv": "files",  # 2.122.0 (#2098)
    # 2.122.0 B (#2099 #2294)
    "GET /api/files/nodes/{}/tags": "files", "PUT /api/files/nodes/{}/tags": "files", "GET /api/files/tags": "files", "GET /api/files/tagged": "files",
    "PUT /api/files/nodes/{}/recognition": "files",  # 2.353.0 D (#2759): p2353_d_ablagedocs_test.py (a, b) without an organisation
    "POST /api/docs/bulk": "files", "POST /api/docs/zip": "files", "GET /api/docs/zip/{}": "files",
    "POST /api/docs/apply-learned": "files",  # 2.607.0 (#4872): p2607_c_learn_api_test.py as a person without an organisation
    "GET /api/docs/{}/notes": "files", "POST /api/docs/{}/notes": "files", "DELETE /api/docs/{}/notes/{}": "files",  # 2.635.0 (#4807 d): p2635_c_docs_test.py
    "POST /api/docs/{}/notes/{}/restore": "files",  # 2.981.0 (#5273): p2981_a_comments_test.py
    # 2.981.0 (#5273): the generic routes of the comments' core (kinds video, doc_note; p2981_a_comments_test.py)
    "GET /api/obj/{}/{}/comments": "videos", "POST /api/obj/{}/{}/comments": "videos", "PATCH /api/obj/comments/{}": "videos",
    "DELETE /api/obj/comments/{}": "videos", "POST /api/obj/comments/{}/restore": "videos",
    "POST /api/docs/{}/extracted": "files",  # 2.121.0 A (#2092): take over / discard the recognised receipt values
    "GET /api/docs/{}/einvoice": "files",  # 2.146.0 A (#2451): the readable view of an e-invoice
    "POST /api/v1/files/{}/versions": "files", "PUT /api/docs/settings": "files", "PUT /api/docs/{}/receipt": "files",
    # 2.207.0 A (#2763): scan inboxes of the own documents, the upload key, the mail note, the folder watcher downloads
    "GET /api/docs/scan-keys": "files", "POST /api/docs/scan-keys": "files", "DELETE /api/docs/scan-keys/{}": "files", "PATCH /api/docs/scan-keys/{}": "files",  # 2.591.0 (#4886)
    "GET /api/v1/documents/upload-target": "files", "POST /api/docs/mail-notice": "files", "GET /api/docs/folder-watcher/{}": "files",
    # 2.577.0 C (#4466): named document addresses (p2577_c_docmail_test.py as the person without an organisation)
    "GET /api/docs/mail-addresses": "files", "POST /api/docs/mail-addresses": "files", "PATCH /api/docs/mail-addresses/{}": "files",
    "POST /api/docs/mail-addresses/{}/renew": "files", "DELETE /api/docs/mail-addresses/{}": "files",
    # 2.425.0 C (#3453): receipt fetchers of the personal office (p2425_c_api_test.py, freelancer-matrix: files)
    "GET /api/docs/fetchers": "files", "POST /api/docs/fetchers": "files", "DELETE /api/docs/fetchers/{}": "files",
    "PATCH /api/docs/fetchers/{}/portals/{}": "files", "GET /api/v1/fetcher": "files",
    "PUT /api/v1/fetcher/status": "files",
    "PATCH /api/docs/fetchers/{}": "files",  # 2.705.0 (#5151): the address rule of a fetcher key (p2705_a_harden_test.py)
    "POST /api/v1/fetcher/documents": "files",
    "POST /api/docs/{}/receipt/einvoice": "files",  # 2.185.0 A (#2583)
    "POST /api/docs/{}/area": "files",  # 2.522.0 (#4433): "Move to office" / "Wrong area" in the personal office (p4433_a_area_test.py)
    # 2.547.0 (#4434): the old receipts into the personal office once, with its undo (p4434_a_umzug_test.py)
    "GET /api/docs/office-move": "files", "POST /api/docs/office-move": "files", "POST /api/docs/office-move/hide": "files", "POST /api/docs/office-move/{}/undo": "files",
    # ---- hub (27)
    "DELETE /api/hubmail/address": "hub", "DELETE /api/hubmail/mails/{}": "hub", "DELETE /api/team/absences/{}": "hub",
    "DELETE /api/team/dispo/bookings/{}": "hub", "GET /api/hubmail/inbox": "hub", "GET /api/hubmail/mails": "hub",
    "GET /api/hubmail/mails/{}": "hub", "GET /api/hubmail/mails/{}/files/{}": "hub", "GET /api/hubmail/targets": "hub",
    "GET /api/team/absences": "hub", "GET /api/team/absences/check": "hub", "GET /api/team/bookings/mine": "hub",
    "GET /api/team/absences/feed": "hub", "POST /api/team/absences/feed": "hub",  # 2.155.0 B (#2076)
    "GET /api/team/dispo": "hub", "GET /api/team/dispo/export": "hub", "GET /api/team/dispo/free": "hub", "GET /api/v1/absences": "hub", "GET /api/v1/dispo": "hub",
    "GET /api/v1/dispo/free": "hub", "PATCH /api/team/absences/{}": "hub", "PATCH /api/team/dispo/bookings/{}": "hub",
    "POST /api/hubmail/address": "hub", "POST /api/hubmail/mails/{}/assign": "hub",
    # 2.141.0 A (#2141, #2138): the own mailbox of the private workspace, Reply / New e-mail (p2141_a_api_test.py, freelancer-matrix: hub)
    "GET /api/hubmail/mailboxes": "hub", "GET /api/hubmail/mailbox": "hub", "PUT /api/hubmail/mailbox": "hub", "DELETE /api/hubmail/mailbox": "hub",
    "POST /api/hubmail/mailbox/check": "hub", "POST /api/hubmail/mailbox/poll": "hub", "GET /api/hubmail/compose": "hub", "POST /api/hubmail/send": "hub",
    # 2.581.0 (#4804): the document rules of the private mailbox (p2581_d_mailrules_test.py, freelancer-matrix: hub)
    "GET /api/hubmail/mailbox/rules": "hub", "POST /api/hubmail/mailbox/rules": "hub", "PUT /api/hubmail/mailbox/rules/{}": "hub",
    "DELETE /api/hubmail/mailbox/rules/{}": "hub", "POST /api/hubmail/mailbox/rules/fetch": "hub",
    "POST /api/hubmail/mails/{}/restore": "hub",
    "GET /api/v1/mails": "hub", "GET /api/v1/mails/{}": "hub",  # 2.483.0 (#1902): p2483_a_mail_api_test.py
    "GET /api/hubmail/mails/{}/html": "hub", "GET /api/hubmail/mails/{}/make": "hub", "POST /api/hubmail/mails/{}/task": "hub",  # 2.141.0 B (#2140, #2139)
    "POST /api/hubmail/mails/{}/event": "hub", "GET /api/hubmail/links": "hub", "POST /api/team/absences": "hub", "POST /api/team/absences/{}/restore": "hub",
    "POST /api/team/dispo/bookings": "hub", "POST /api/team/dispo/bookings/restore": "hub",
    "POST /api/team/dispo/bookings/{}/fill": "hub",  # 2.589.0 (#4571): open places of a shoot day from a quotation (p2589_b_dispo_test.py, freelancer-matrix: hub)
    "GET /api/team/dispo/callsheet/{}": "hub", "PUT /api/team/dispo/callsheet/{}": "hub", "GET /api/team/dispo/callsheet/{}/pdf": "hub",
    "GET /api/team/dispo/callsheet/{}/sketch": "hub",  # 2.855.0 (#1956): the call sheet of a shoot day (p2802_a_callsheet_test.py, freelancer-matrix: hub)
    "GET /api/team/dispo/callsheet/{}/history": "hub",  # 2.872.0 (#5532): its history of the core (p5532_a_dispokern_test.py, freelancer-matrix: hub)
    "GET /api/team/dispo/callsheets": "hub", "POST /api/team/dispo/callsheets": "hub",  # 2.988.0 (#5651): a project's tab "Call sheets" (p2988_a_callsheets_test.py, freelancer-matrix: hub)
    "PUT /api/team/absences/holidays": "hub",
    # 2.125.0 A (#2117, #2118): vacation account, requests, the working week
    "GET /api/team/leave": "hub", "PUT /api/team/leave/quota": "hub", "PUT /api/team/leave/approval": "hub",
    "PUT /api/team/leave/worktime/{}": "hub", "POST /api/team/absences/{}/decide": "hub",
    # ---- link (22)
    "GET /ical/abs/{}.ics": "link",  # 2.155.0 B (#2076)
    "GET /mail/off/{}": "link", "POST /mail/off/{}": "link",  # 2.367.5 (#2975): the one-click off link of a notification mail
    "GET /f/{}": "link", "GET /ical/{}.ics": "link", "GET /ical/ev/{}.ics": "link", "GET /p/{}": "link", "GET /p/{}/stop": "link", "GET /portal": "link",
    "GET /portal/login/{}": "link", "GET /s/q/{}": "link", "GET /s/q/{}/pdf": "link", "GET /s/q/{}/terms": "link", "POST /s/q/{}/comments": "link", "GET /s/{}": "link",
    "GET /s/{}/file/{}": "link", "GET /s/{}/logo": "link", "POST /f/{}": "link", "POST /p/{}/comment": "link",
    "POST /p/{}/login": "link", "POST /p/{}/notify": "link", "POST /p/{}/stop": "link", "POST /portal/login/{}": "link",
    "POST /portal/logout": "link", "GET /s/pay/{}": "link", "POST /s/pay/{}/go": "link", "POST /s/q/{}": "link", "POST /s/{}/feedback": "link", "POST /s/{}/tick": "link",
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
    "GET /api/fields/{}/count": "lists", "GET /api/fields/task-refs": "lists", "GET /api/folder-heads": "lists", "GET /api/folders/agents": "lists",
    "GET /api/folders/groups": "lists", "GET /api/folders/groups/{}/diff": "lists",
    "GET /api/folders/notify-template": "lists", "GET /api/folders/people": "lists", "GET /api/folders/people/diff": "lists",
    "GET /api/folders/playbook": "lists", "GET /api/folders/playbook/versions": "lists",
    "GET /api/folders/playbook/versions/{}": "lists", "GET /api/folders/props": "lists",
    "GET /api/folders/public-links": "lists", "GET /api/folders/repos": "lists", "GET /api/group-avatar/{}/{}.jpg": "lists",
    "GET /api/groups": "lists", "GET /api/layouts/offers/{}": "lists", "GET /api/layouts/saved": "lists",
    "GET /api/list-files/{}": "lists", "GET /api/list-header/{}/{}.jpg": "lists", "GET /api/list-icon/{}/{}.png": "lists",
    "GET /api/lists/{}/export.csv": "lists",  # 2.116.0 C (#2064): p2116_c_api_test.py
    "GET /api/lists/{}/shotlist.pdf": "lists",  # 2.636.0 (#4565): p2636_c_dreh_api_test.py (a shoot of the freelancer with Film & Video)
    "GET /api/lists/{}/agent-access": "lists", "GET /api/lists/{}/checks": "lists", "GET /api/lists/{}/e2e": "lists",
    "GET /api/lists/{}/e2e/todo": "lists", "GET /api/lists/{}/envs": "lists", "GET /api/lists/{}/error-hook": "lists",
    "GET /api/lists/{}/folder-preview": "lists", "GET /api/lists/{}/forms": "lists", "GET /api/lists/{}/groups": "lists",
    "GET /api/lists/{}/kpis": "lists", "GET /api/lists/{}/layout": "lists", "GET /api/lists/{}/notes": "lists",
    "GET /api/lists/{}/notify-template": "lists", "GET /api/lists/{}/overview": "lists", "GET /api/lists/{}/overview/history": "lists",  # 2.270.0 A (#3019)
    "GET /api/lists/{}/owner": "lists",
    "GET /api/lists/{}/playbook": "lists", "GET /api/lists/{}/playbook/versions": "lists",
    "GET /api/lists/{}/playbook/versions/{}": "lists", "GET /api/lists/{}/public-link": "lists",
    "GET /api/lists/{}/repos": "lists", "GET /api/lists/{}/build-status": "lists", "GET /api/v1/lists/{}/build-status": "lists",
    "PUT /api/lists/{}/repos/version-field": "lists",  # 2.151.0 A (#2558)
    "PUT /api/lists/{}/repos/close-release": "lists", "POST /api/tasks/{}/partial": "tasks", "POST /api/v1/tasks/{}/partial": "tasks",  # 2.392.0 B (#3364)
    "GET /api/lists/{}/rules": "lists", "GET /api/lists/{}/signoffs": "lists",
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
    "GET /api/v1/lists/{}/rules": "lists", "GET /api/v1/lists/{}/sections": "lists", "GET /api/v1/lists/{}/views": "lists", "GET /api/v1/lists/{}/sprints": "lists",
    "GET /api/v1/lists/{}/status-report": "lists", "GET /api/v1/lists/{}/tags": "lists",
    "GET /api/v1/lists/{}/delivery-report": "lists",  # 2.392.0 D (#3369)
    "POST /api/tasks/brief": "tasks", "POST /api/v1/tasks/brief": "tasks",  # 2.392.3 (#3368)
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
    "PUT /api/tasks/{}/irreversible": "tasks", "DELETE /api/tasks/{}/irreversible": "tasks", "POST /api/tasks/{}/irreversible-yes": "tasks",  # 2.392.0 C (#3370)
    "PUT /api/tasks/{}/delivery": "tasks", "DELETE /api/tasks/{}/delivery": "tasks",  # 2.392.2 (#3365)
    "GET /api/tasks/{}/decisions": "tasks", "POST /api/tasks/{}/decisions": "tasks", "GET /api/v1/tasks/{}/decisions": "tasks", "POST /api/v1/tasks/{}/decisions": "tasks",
    "POST /api/v1/lists": "lists", "POST /api/v1/lists/{}/deployments": "lists", "POST /api/v1/lists/{}/duplicate": "lists",
    "POST /api/v1/tasks/{}/duplicate": "tasks",  # 2.574.0 (#3376): p2574_d_api_test.py (a person without an organisation)
    "POST /api/v1/lists/{}/fields": "lists", "POST /api/v1/lists/{}/files": "lists", "POST /api/v1/lists/{}/forms": "lists",
    "POST /api/v1/lists/{}/join": "lists", "POST /api/v1/lists/{}/links": "lists", "POST /api/v1/lists/{}/milestones": "lists",
    "POST /api/v1/lists/{}/notepads": "lists", "POST /api/v1/lists/{}/notes": "lists", "POST /api/v1/lists/{}/owner": "lists",
    "POST /api/v1/lists/{}/playbook/proposals": "lists", "POST /api/v1/lists/{}/rules/proposals": "lists",
    "POST /api/v1/lists/{}/sections": "lists", "POST /api/v1/lists/{}/shift": "lists", "POST /api/v1/lists/{}/views": "lists",
    "POST /api/v1/lists/{}/shop-areas": "lists", "POST /api/v1/lists/{}/sprints/assign": "lists",
    "POST /api/v1/lists/{}/tags": "lists", "POST /api/v1/templates": "lists", "POST /api/v1/templates/{}/apply": "lists",
    "PUT /api/folder-heads": "lists", "PUT /api/folders/agents": "lists", "PUT /api/folders/groups/{}": "lists",
    "GET /api/lists/tree": "lists", "POST /api/lists/folders": "lists", "POST /api/lists/tree/move": "lists",  # 2.352.0 A (#2748)
    "PUT /api/folders/notify-template": "lists", "PUT /api/folders/people": "lists", "PUT /api/folders/playbook": "lists",
    "PUT /api/folders/props": "lists", "PUT /api/folders/public-links": "lists", "PUT /api/lists/{}/agent": "lists",
    "PUT /api/lists/{}/bell": "lists", "PUT /api/lists/{}/favorite": "lists", "PUT /api/lists/{}/folder-repo": "lists",
    "PUT /api/lists/{}/groups/{}": "lists", "PUT /api/lists/{}/header": "lists", "PUT /api/lists/{}/icon": "lists",
    "PUT /api/lists/{}/in-mine": "lists", "PUT /api/lists/{}/layout": "lists", "PUT /api/lists/{}/links/order": "lists",
    "PUT /api/lists/{}/members": "lists", "PUT /api/lists/{}/notify-template": "lists",
    "GET /api/lists/{}/shares": "lists", "POST /api/lists/{}/shares/{}/restore": "lists", "GET /api/lists/{}/history": "lists",  # 2.568.0 (#4739)
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
    # 2.120.0 E (#2091): the own letterhead PDF
    "GET /api/office/letterhead": "office", "POST /api/office/letterhead": "office", "PUT /api/office/letterhead": "office",
    "DELETE /api/office/letterhead": "office", "POST /api/office/letterhead/restore": "office", "GET /api/office/letterhead/preview": "office",
    # 2.272.0 D (#3029): the clients' trash and the numbers of the delete dialog (p2272_d_client_delete_test.py, freelancer-matrix: office)
    "GET /api/clients/trash": "office", "GET /api/clients/usage": "office", "POST /api/clients/{}/restore": "office", "DELETE /api/clients/{}/purge": "office",
    "POST /api/clients/{}/anonymize": "office",  # 2.223.3 B (#2878): p22233_b_privacy_test.py (a person without organisation)
    # 2.113.2 (#2253): terms and conditions as PDF (p2113c_a_api_test.py, freelancer-matrix: office)
    "GET /api/office/terms": "office", "POST /api/office/terms/{}": "office", "GET /api/office/terms/{}/file": "office",
    "DELETE /api/office/terms/{}": "office", "POST /api/office/terms/{}/restore": "office", "GET /api/office/docs/{}/terms": "office", "GET /api/office/docs/{}/recipients": "office",  # 2.433.0 (#3599)
    "DELETE /api/office/packs/installed/{}/{}": "office", "DELETE /api/office/trips/{}": "office",
    "DELETE /api/office/trips/{}/items/{}": "office", "DELETE /api/office/{}/{}": "office", "DELETE /api/paperless": "office",
    "DELETE /api/paperless/zip": "office", "DELETE /api/v1/clients/{}": "office", "GET /api/clients": "office",
    "GET /api/clients/{}": "office", "GET /api/clients/{}/book-contacts": "office", "GET /api/newsletter": "office",
    "GET /api/newsletter/lists": "office", "GET /api/office/agents/{}": "office", "GET /api/office/cashflow": "office",
    "GET /api/office/cashflow/check": "office", "GET /api/office/catalog": "office", "GET /api/office/datev/extf": "office", "GET /api/office/datev/accounts": "office",  # 2.120.0 C (#2090)
    "POST /api/office/datev/import/check": "office", "POST /api/office/datev/import": "office", "POST /api/office/datev/import/{}/undo": "office",  # 2.148.0 D (#2458)
    "GET /api/office/books/archive": "office", "GET /api/office/books/archive/bookings": "office", "GET /api/office/books/archive/bookings/{}": "office",  # 2.414.0 (#3502)
    "GET /api/office/books/archive/accounts": "office", "GET /api/office/books/archive/docs/{}": "office", "GET /api/office/books/archive/files/{}": "office",
    "POST /api/office/books/archive/check": "office", "POST /api/office/books/archive/import": "office", "POST /api/office/books/archive/runs/{}/undo": "office",
    "GET /api/office/books/ledger": "office", "GET /api/office/books/ledger/settings": "office", "PUT /api/office/books/ledger/settings": "office",  # 2.666.0 (#3461)
    "GET /api/office/books/ledger/{}.csv": "office", "POST /api/office/books/ledger/entries": "office", "PUT /api/office/books/ledger/entries/{}": "office",
    "DELETE /api/office/books/ledger/entries/{}": "office", "POST /api/office/books/ledger/close": "office",
    "GET /api/office/books/ledger/{}.pdf": "office",  # 2.685.0 (#5128)
    "GET /api/office/datev/suppliers": "office", "PUT /api/office/datev/suppliers/{}": "office", "DELETE /api/office/datev/suppliers/{}": "office",
    "POST /api/office/datev/suppliers/{}/restore": "office", "GET /api/office/datev/opening": "office",
    "GET /api/office/deals": "office", "GET /api/office/deals/summary": "office", "GET /api/office/docs": "office",
    "GET /api/office/docs/{}": "office", "GET /api/office/docs/{}/log": "office", "GET /api/office/docs/{}/payments": "office",
    "GET /api/office/docs/{}/pdf": "office", "GET /api/office/docs/{}/render": "office",
    "GET /api/office/docs/{}/signoffs": "office", "GET /api/office/docs/{}/xml": "office", "GET /api/office/export": "office",
    "GET /api/office/fixed-costs": "office", "GET /api/office/fixed-costs/import/template": "office",
    "GET /api/office/kpi": "office", "GET /api/office/legacy/archive": "office", "GET /api/office/legacy/archive/{}": "office",
    "GET /api/office/legacy/archive/{}/pdf": "office", "GET /api/office/legacy/counter": "office",
    "GET /api/office/legacy/runs": "office", "GET /api/office/log": "office", "GET /api/office/log/chain": "office",  # 2.531.0 (#4497)
    "GET /api/office/logo": "office",
    "GET /api/office/mail-status": "office", "GET /api/office/number-preview": "office", "GET /api/office/packs": "office",
    "GET /api/office/packs/{}": "office", "GET /api/office/pack-switch": "office",  # 2.147.0 (#2462)
    "GET /api/office/pay-props": "office", "GET /api/office/settings": "office",
    "GET /api/office/trips": "office", "GET /api/office/trips/bill-docs": "office", "GET /api/office/receipts/billed": "office", "GET /api/office/trips/report": "office",
    "GET /api/office/trips/vma": "office", "GET /api/office/trips/vma-rates": "office", "GET /api/office/trips/vma.csv": "office",  # 2.95.0 A (#1932)
    "GET /api/office/trips/vma.pdf": "office", "GET /api/office/trips/vma.xlsx": "office",
    "GET /api/office/trips/purposes": "office", "POST /api/office/trips/purposes": "office",  # 2.117.0 A (#2292)
    "PATCH /api/office/trips/purposes/{}": "office", "DELETE /api/office/trips/purposes/{}": "office",
    "GET /api/office/meals": "office", "POST /api/office/meals": "office", "GET /api/office/meals/{}": "office",  # 2.119.0 A (#2288): entertainment receipts
    "GET /api/office/meals/signature": "office", "PUT /api/office/meals/signature": "office", "DELETE /api/office/meals/signature": "office",  # 2.372.0 (#3316)
    "PATCH /api/office/meals/{}": "office", "DELETE /api/office/meals/{}": "office", "POST /api/office/meals/{}/restore": "office",
    "POST /api/office/meals/{}/approve": "office", "POST /api/office/meals/{}/unlock": "office", "POST /api/office/meals/{}/file": "office",
    "GET /api/office/meals/{}/file/{}": "office", "DELETE /api/office/meals/{}/file/{}": "office",
    "POST /api/office/meals/{}/file/{}/restore": "office", "GET /api/office/meals/{}/pdf": "office", "GET /api/office/meals/report": "office",
    "GET /api/office/meals/choices": "office", "POST /api/office/meals/choices": "office", "PATCH /api/office/meals/choices/{}": "office",
    "DELETE /api/office/meals/choices/{}": "office",
    "GET /api/office/{}": "office", "GET /api/office/{}/{}": "office", "GET /api/paperless": "office",
    "GET /api/paperless/preview": "office", "GET /api/paperless/zip/preview": "office", "GET /api/v1/clients": "office",
    "GET /api/v1/clients/{}": "office", "GET /api/v1/office": "office", "GET /api/v1/office/docs": "office",
    "GET /api/v1/office/docs/{}": "office", "GET /api/v1/office/docs/{}/pdf": "office",
    "GET /api/v1/office/payment-suggestions": "office", "GET /api/v1/office/{}": "office",
    "GET /api/v1/office/series": "office", "GET /api/v1/office/subs": "office",  # 2.483.0 (#2007): p2483_a_series_api_test.py
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
    "POST /api/office/docs/{}/delivery": "office", "GET /api/office/docs/{}/timesheet.pdf": "office",  # 2.120.0 D (#2089)
    "POST /api/office/docs/{}/credit": "office", "POST /api/office/docs/{}/datev": "office",
    # 2.154.0 B (#1960): e-invoices over Peppol (p2154_b_peppol_test.py: the freelancer sets up and sends in the personal office)
    "GET /api/office/peppol": "office", "PUT /api/office/peppol": "office", "POST /api/office/peppol/check": "office",
    "GET /api/office/payonline": "office", "PUT /api/office/payonline": "office", "POST /api/office/payonline/check": "office",  # 2.469.0 (#3459)
    "POST /api/office/payonline/rotate": "office", "POST /api/office/payonline/events/{}/retry": "office", "POST /api/office/payonline/events/{}/done": "office",
    "PUT /api/office/docs/{}/pay-online": "office",
    "GET /api/office/docs/{}/ubl": "office", "GET /api/office/docs/{}/peppol": "office", "POST /api/office/docs/{}/peppol": "office",
    "POST /api/office/docs/{}/peppol/lookup": "office",
    "POST /api/office/docs/{}/peppol/undelivered": "office",  # 2.370.0 (#2778)
    "POST /api/office/docs/{}/peppol/refresh": "office",  # 2.306.0 D2 (#2875)
    "POST /api/office/docs/{}/cashflow": "office", "POST /api/office/docs/{}/duplicate": "office", "POST /api/office/docs/{}/fee": "office",
    "POST /api/office/docs/{}/finalize": "office", "POST /api/office/docs/{}/unlock": "office",  # 2.114.2 (#2263)
    "GET /api/office/docs/{}/number-preview": "office",  # 2.431.0 B (#3605): the number of the finalise dialog
    "POST /api/office/docs/{}/invoice": "office",
    "GET /api/office/docs/{}/progress": "office",  # 2.120.0 A (#2087): progress invoices of a quotation (p2120_a_api_test.py)
    "POST /api/office/docs/{}/number": "office", "POST /api/office/docs/{}/parts": "office",
    "POST /api/office/docs/{}/payments": "office", "POST /api/office/docs/{}/send": "office",
    "POST /api/office/docs/{}/signoff": "office", "POST /api/office/docs/{}/status": "office",
    "POST /api/office/fixed-costs": "office", "POST /api/office/fixed-costs/delete": "office",
    "POST /api/office/fixed-costs/category-rename": "office",  # 2.581.0 (#4820)
    "POST /api/office/fixed-costs/import": "office", "POST /api/office/fixed-costs/import/preview": "office",
    "POST /api/office/import": "office", "POST /api/office/legacy/archive": "office",
    "POST /api/office/legacy/archive/address": "office", "POST /api/office/legacy/archive/parse": "office",
    "GET /api/office/legacy/archive/templates": "office",  # 2.621.0 (#4600): p2621_a_fntpl_test.py
    "POST /api/office/legacy/archive/run": "office", "POST /api/office/legacy/counter": "office",
    "POST /api/office/legacy/import": "office", "POST /api/office/legacy/preview": "office",
    "POST /api/office/legacy/runs/{}/undo": "office", "POST /api/office/legacy/split": "office",
    "POST /api/office/legacy/runs/{}/tidy": "office", "POST /api/office/services/renumber": "office",  # 2.138.0 E (#2241, #2237): p2138_e_api_test.py
    "POST /api/office/logo": "office", "POST /api/office/move": "office", "POST /api/office/packs/install": "office",
    "POST /api/office/packs/installed/{}/{}/restore": "office", "POST /api/office/packs/validate": "office",
    "POST /api/office/pay-props/{}": "office", "POST /api/office/signoffs/{}/revoke": "office",
    "POST /api/office/trips": "office", "POST /api/office/trips/bill": "office", "POST /api/office/trips/unbill": "office", "POST /api/office/receipts/bill": "office", "POST /api/office/receipts/unbill": "office",
    "POST /api/office/trips/delete": "office", "POST /api/office/trips/import": "office", "POST /api/office/trips/import/preview": "office",  # 2.95.0 B (#1932)
    "POST /api/office/trips/{}/items": "office", "POST /api/office/{}": "office", "POST /api/paperless/import": "office",
    "POST /api/paperless/stop": "office", "POST /api/paperless/zip": "office", "POST /api/paperless/zip/import": "office",
    "POST /api/paperless/zip/part": "office", "POST /api/paperless/zip/stop": "office",
    "POST /api/receipt-suggestions/{}/accept": "office", "POST /api/receipt-suggestions/{}/reject": "office",
    "POST /api/receipt-suggestions/{}/reopen": "office", "POST /api/v1/clients": "office",
    "POST /api/v1/clients/bulk": "office", "POST /api/v1/office/offers": "office",
    "POST /api/v1/office/offers/{}/invoice": "office", "POST /api/v1/office/payment-suggestions": "office",
    "POST /api/v1/office/invoices": "office",  # 2.568.0 (#4673): p2568_b_ai_office_test.py
    "POST /api/v1/office/reminders": "office", "PUT /api/newsletter": "office", "PUT /api/newsletter/consent": "office", "POST /api/newsletter/consent/import": "office",
    "PUT /api/office/cashflow/check": "office", "PUT /api/office/docs/{}/items": "office",
    "PUT /api/office/docs/{}/parts/{}/items": "office", "PUT /api/office/settings": "office", "PUT /api/paperless": "office",
    # ---- orgadmin (23; 2.137.0 A (#2344): export of the own personal office -> "office")
    "GET /api/org-icon/{}/{}.png": "orgadmin", "POST /api/orgs/{}/icon": "orgadmin", "DELETE /api/orgs/{}/icon": "orgadmin",  # 2.87.9 (#1913)
    "DELETE /api/admin/orgs/{}": "orgadmin",
    "GET /api/admin/orgs/{}/delete-info": "orgadmin",  # 2.152.0 A (#2167)
    "GET /api/orgs/{}/leave-info": "orgadmin", "POST /api/admin/orgs/{}/delete-notice": "orgadmin",  # 2.361.0 (#2920 / #2922)
    "DELETE /api/admin/orgs/{}/delete-notice": "orgadmin",
    "DELETE /api/orgs/{}/export": "office",
    "DELETE /api/orgs/{}/lists/{}": "orgadmin", "DELETE /api/orgs/{}/lists/{}/icon": "orgadmin",
    "DELETE /api/orgs/{}/members/{}": "orgadmin", "GET /api/admin/orgs": "orgadmin", "GET /api/orgs/{}/encryption": "orgcrypt",
    "GET /api/orgs/{}/export": "office", "GET /api/retention/me": "office", "GET /api/retention/me/export.zip": "office", "GET /api/retention/org/{}": "orgadmin", "GET /api/retention/org/{}/export.zip": "orgadmin",
    "GET /api/orgs/{}/export/file": "office", "GET /api/orgs/{}/lists": "orgadmin",
    "GET /api/orgs/{}/tasks": "orgadmin",  # 2.574.0 (#3376): an organisation admin's read-only task view (404 without one, p2574_d_api_test.py)
    "GET /api/orgs/{}/out-requests": "orgadmin", "POST /api/orgs/{}/out-requests": "orgadmin",  # 2.361.2 (#2923)
    "POST /api/orgs/{}/out-requests/{}": "orgadmin",
    # 2.223.2 C (#2871): the step-up before a download (POST -> a one-time ticket; p22232_c_offsite_test.py, freelancer too)
    "POST /api/orgs/{}/export/file": "office", "POST /api/retention/me/export.zip": "office", "POST /api/retention/org/{}/export.zip": "orgadmin",
    "PATCH /api/admin/orgs/{}": "orgadmin", "PATCH /api/orgs/{}": "orgadmin", "PATCH /api/orgs/{}/lists/{}": "orgadmin",
    "POST /api/admin/orgs": "orgadmin", "POST /api/admin/orgs/boundary/repair": "orgadmin",
    "POST /api/orgs/{}/encryption/recovery": "orgcrypt", "POST /api/orgs/{}/encryption/recovery/passkey": "orgcrypt",  # 2.138.0 (#1972)
    "POST /api/orgs/{}/export": "office",
    "POST /api/orgs/{}/lists/{}/archive": "orgadmin", "POST /api/orgs/{}/lists/{}/icon": "orgadmin",
    "POST /api/orgs/{}/lists/{}/owner": "orgadmin", "PUT /api/admin/orgs/visibility": "orgadmin",
    "PUT /api/orgs/{}/lists/{}/icon": "orgadmin", "PUT /api/orgs/{}/members": "orgadmin",
    # 2.115.0 B (#2062): inviting into an organisation needs one (a person without one has no members)
    "GET /api/orgs/{}/invites": "orgadmin", "POST /api/orgs/{}/invites": "orgadmin", "POST /api/orgs/{}/invites/{}/resend": "orgadmin",
    "DELETE /api/orgs/{}/invites/{}": "orgadmin",
    # 2.148.1 A (#2480): the invited person (also one without an organisation) accepts / declines (p21481_a_api_test.py)
    "POST /api/orgs/{}/join": "own", "DELETE /api/orgs/{}/join": "own",
    # ---- own (61)
    "DELETE /api/account/export": "own", "DELETE /api/account/import/{}": "own", "DELETE /api/me/app-passwords/{}": "own",
    "DELETE /api/me/avatar": "own",  # 2.574.0 (#3779): GET / PUT /api/me/ntfy-inbox are gone
    "DELETE /api/me/mail/token": "own", "DELETE /api/me/tokens/{}": "own",
    "DELETE /api/me/wait-suggestions": "own", "DELETE /api/me/webhooks/{}": "own", "DELETE /api/push/subs/{}": "own",
    "DELETE /api/v1/me/app-passwords/{}": "own", "GET /api/account/export": "own", "GET /api/account/delete": "own", "POST /api/account/delete": "own", "GET /api/account/export/file": "own", "POST /api/account/export/file": "own",
    "GET /api/account/import": "own", "GET /api/account/import/{}": "own", "GET /api/me": "own",
    "GET /api/me/app-passwords": "own", "GET /api/me/mail": "own", "GET /api/me/share/httpshortcuts.zip": "own",
    "GET /api/me/storage": "own", "GET /api/me/tokens": "own", "GET /api/me/wait-suggestions": "own",
    "GET /api/me/webhooks": "own", "GET /api/me/webhooks/{}/log": "own", "GET /api/orgs": "own", "POST /api/orgs": "own",  # 2.422.0 (#2937): p2422_orgself_test.py (a)
    "GET /api/push/subs": "own",
    "GET /api/settings/defaults": "own",  # 2.583.0 (#4833)
    "GET /api/push/vapid": "own", "GET /api/v1/me": "own", "GET /api/v1/me/app-passwords": "own",
    "GET /api/v1/me/storage": "own", "PATCH /api/me": "own", "PATCH /api/me/tokens/{}": "own",
    "PATCH /api/me/webhooks/{}": "own", "PATCH /api/settings": "own", "PATCH /api/v1/me/notifications": "own",
    "POST /api/account/export": "own", "POST /api/account/import": "own", "POST /api/account/import/{}/key": "own",
    "POST /api/account/import/{}/run": "own", "POST /api/me/app-passwords": "own", "POST /api/me/avatar": "own",
    # 2.97.0 B (#1951): customers (p297_b_api_test.py) - routes below this line
    # 2.96.0 D (#1941 / #1918): an organisation export into the private workspace
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
    "DELETE /api/family/rewards/{}": "personal", "DELETE /api/feeds/{}": "reading", "DELETE /api/life/karakeep": "personal",
    "DELETE /api/servers/{}": "personal", "DELETE /api/servers/{}/tasks/{}": "personal",
    "DELETE /api/supporter/{}": "personal", "DELETE /api/v1/family/rewards/{}": "personal", "GET /api/budget": "personal",
    "GET /api/budget/files/{}": "personal", "GET /api/budget/entries/{}": "personal", "GET /api/budget/recurring/{}": "personal",  # 2.576.0 (#4764)
    "GET /api/budget/{}": "personal", "GET /api/budget/{}/contracts": "personal",
    "GET /api/budget/{}/recurring": "personal", "GET /api/family": "personal", "GET /api/family/contacts": "personal",
    "GET /api/family/deadline-types": "personal", "GET /api/family/kids": "personal", "GET /api/family/packing": "personal",
    "GET /api/feeds": "reading", "GET /api/feeds/items": "reading", "GET /api/feeds/opml": "reading",
    "GET /api/life": "life_org", "GET /api/life/karakeep": "personal", "GET /api/life/karakeep/lists": "personal",
    "GET /api/life/review": "personal", "GET /api/life/journal": "personal", "GET /api/life/journal/stats": "personal", "GET /api/life/journal/export": "personal",  # 2.140.0 C (#2133)
     "GET /api/life/upkeep-presets": "personal", "GET /api/servers": "personal",
    "GET /api/servers/{}/data": "personal", "GET /api/servers/{}/events": "personal", "GET /api/servers/{}/news": "personal",
    "GET /api/servers/{}/search": "personal", "GET /api/servers/{}/tasks/{}": "personal", "GET /api/supporter": "personal",
    "GET /api/v1/family": "personal", "GET /api/v1/family/deadline-types": "personal", "GET /api/v1/family/kids": "personal",
    "GET /api/v1/family/packing": "personal", "GET /api/v1/life": "personal", "GET /api/v1/stats": "personal",  # 2.630.0 (#4617)
    "GET /api/v1/life/review": "personal",
    "GET /api/v1/life/upkeep-presets": "personal", "PATCH /api/budget/cats/{}": "personal",
    "PATCH /api/budget/entries/{}": "personal", "PATCH /api/budget/recurring/{}": "personal",
    "PATCH /api/family/contacts/{}": "personal", "PATCH /api/family/rewards/{}": "personal",
    "PATCH /api/servers/self": "personal", "PATCH /api/servers/{}": "personal", "PATCH /api/servers/{}/tasks/{}": "personal",
    "PATCH /api/supporter/nudge": "personal", "PATCH /api/v1/family/rewards/{}": "personal",
    "POST /api/budget/entries/{}/files": "personal", "POST /api/budget/lists": "personal",
    "POST /api/budget/recurring/{}/book": "personal", "POST /api/budget/{}/cats": "personal",
    "POST /api/budget/cats/{}/restore": "personal", "POST /api/budget/entries/{}/restore": "personal",  # 2.567.0 A (#4707)
    "POST /api/budget/recurring/{}/restore": "personal",
    "POST /api/budget/{}/contracts": "personal", "POST /api/budget/{}/entries": "personal",
    "POST /api/budget/{}/import/commit": "personal", "POST /api/budget/{}/import/parse": "personal",
    # 2.146.0 C (#2455): an import run listed / taken back (p2146_c_api_test.py)
    "GET /api/budget/{}/import/runs": "personal", "POST /api/budget/{}/import/runs/{}/undo": "personal",
    "POST /api/budget/{}/recurring": "personal", "POST /api/family/contacts": "personal",
    "POST /api/family/contacts/{}/sync": "personal", "POST /api/family/deadlines": "personal",
    "POST /api/family/kids/{}/rewards": "personal", "POST /api/family/kids/{}/stars": "personal",
    "POST /api/family/occasions": "personal", "POST /api/family/packing": "personal",
    "POST /api/family/rewards/{}/decide": "personal", "POST /api/family/rewards/{}/request": "personal",
    "POST /api/feeds": "reading", "POST /api/feeds/items/{}/later": "reading", "POST /api/feeds/opml": "reading",
    "POST /api/feeds/read": "reading", "GET /api/reading": "reading", "POST /api/reading": "reading",  # 2.172.0 B (#2677 #2679): feeds were "personal"
    "POST /api/feeds/{}/restore": "reading", "POST /api/life/contracts": "personal",
    "POST /api/life/devices": "personal",
    # 2.140.0 B (#2134, #2136): the budget's month comparison, a device <-> the own office (p2140_b_api_test.py)
    "GET /api/budget/{}/compare": "personal", "GET /api/life/devices/{}/link": "personal", "POST /api/life/devices/{}/to-office": "personal",
    "POST /api/life/device-links/{}/pull": "personal", "DELETE /api/life/device-links/{}": "personal",
    "GET /api/office/equipment/{}/link": "office", "POST /api/office/equipment/{}/to-device": "office", "POST /api/life/health": "personal", "POST /api/life/karakeep/sync": "personal",
    "POST /api/life/trips": "life_org", "POST /api/life/trips/{}/expenses": "life_org", "GET /api/life/trips/{}/expenses": "life_org", "POST /api/life/upkeep": "personal", "POST /api/servers": "personal",
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
    "DAV /api/test/boom": "test",  # 2.359.0 (#3023): tests/p2359_a_api_test.py
    "POST /api/test/fints/age": "test",  # 2.616.0 (#2473): tests/p2616_c_fints_test.py (the dialogs' clock)
    "GET /api/test/fints/open": "test",  # 2.616.0 (#2473, Fable findings): tests/p2616_c_fints_test.py (the open dialogs)
    "GET /api/test/fints/lib": "test",  # 2.616.0 (#2473, Fable findings): tests/p2616_c_fints_test.py (the library's inner parts)
    "POST /api/test/fints/conn": "test",  # 2.616.0 (#2473, Fable findings): tests/p2616_c_fints_test.py (the limits of a step)
    "POST /api/test/fints/hold": "test",  # 2.616.0 (#2473, Fable findings): tests/p2616_c_fints_test.py (a dialog in a running step)
    "POST /api/test/exports/hold": "test",  # 2.674.0 (#4190): tests/p2674_a_exports_test.py (the places of the large exports taken)
    "GET /api/test/objrole/{}/{}": "test",  # 2.754.0 (#5268): tests/p2754_d_kinds_api_test.py (the role of a light kind)
    "DAV /test/boom": "test",  # 2.447.0 (#3761): tests/p2447_a_lang_test.py
    "DELETE /api/books/{}": "pim", "DELETE /api/books/{}/members/{}": "pim", "DELETE /api/books/{}/org": "pim",
    "POST /api/books/{}/restore": "pim", "POST /api/books/{}/purge": "pim", "POST /api/contacts/{}/restore": "pim",  # 2.272.0 E1 (#3038)
    "DELETE /api/calendars/{}": "pim", "DELETE /api/calendars/{}/events": "pim", "DELETE /api/contacts/{}": "pim",
    "DELETE /api/evcals/{}": "pim", "DELETE /api/evcals/{}/members/{}": "pim", "DELETE /api/events/{}": "pim",
    "DELETE /api/v1/address-books/{}": "pim", "DELETE /api/v1/address-books/{}/members/{}": "pim",
    "DELETE /api/v1/contacts/{}": "pim", "DELETE /api/v1/event-calendars/{}": "pim",
    "DELETE /api/v1/event-calendars/{}/members/{}": "pim", "DELETE /api/v1/events/{}": "pim", "GET /api/books": "pim",
    "GET /api/books/imports/{}": "pim", "GET /api/books/{}/export.vcf": "pim",
    "GET /api/books/{}/export.csv": "pim", "POST /api/contacts/dupcheck": "pim", "GET /api/contacts/groups": "pim",  # 2.119.1 A (#2080 #2084 #2085)
    "POST /api/contacts/groups": "pim", "GET /api/calendars": "pim",
    "GET /api/calendars/events": "pim", "GET /api/contacts": "pim", "GET /api/contacts/{}": "pim", "GET /api/contacts/{}/history": "pim",  # 2.119.1 B (#2083)
    "GET /api/evcals": "pim",
    "GET /api/evcals/trash": "pim", "POST /api/evcals/{}/restore": "pim",  # 2.566.0 (#4707): the calendar's trash (p2566_c_kern_cal_test.py)
    "GET /api/evinvite": "pim", "GET /api/evcals/{}/feed": "pim", "POST /api/evcals/{}/feed": "pim",  # 2.111.0 B (#2056)
    "GET /api/events/freebusy": "pim",  # 2.155.0 B (#2077): only the own bar without an organisation
    "GET /api/v1/events/freebusy": "pim",  # 2.467.0 (#2586): the same; a freelancer's agent only about its owner
    "GET /api/evcals/{}/export.ics": "pim", "GET /api/events": "pim", "GET /api/events/{}": "pim",
    "GET /api/v1/address-books": "pim", "GET /api/v1/address-books/{}/export": "pim", "GET /api/v1/contacts": "pim",
    "GET /api/v1/contacts/{}": "pim", "GET /api/v1/event-calendars": "pim", "GET /api/v1/event-calendars/{}/export": "pim",
    "GET /api/v1/events": "pim", "GET /api/v1/events/{}": "pim", "PATCH /api/books/{}": "pim",
    "PATCH /api/books/{}/org": "pim", "PATCH /api/calendars/{}": "pim", "PATCH /api/calendars/{}/events": "pim",
    "PATCH /api/contacts/{}": "pim", "PATCH /api/evcals/{}": "pim", "PATCH /api/events/{}": "pim",
    "PATCH /api/v1/address-books/{}": "pim", "PATCH /api/v1/contacts/{}": "pim", "PATCH /api/v1/event-calendars/{}": "pim",
    "PATCH /api/v1/events/{}": "pim", "POST /api/books": "pim", "POST /api/books/{}/import": "pim",
    "POST /api/books/{}/org": "pim", "POST /api/calendars": "pim", "POST /api/calendars/discover": "pim",
    "POST /api/calendars/{}/events": "pim", "POST /api/calendars/{}/events/restore": "pim", "POST /api/calendars/restore": "pim",  # 2.800.0 (#5466)
    "POST /api/calendars/{}/refresh": "pim", "POST /api/calendars/{}/write": "pim", "POST /api/contacts": "pim",
    "POST /api/contacts/bulk": "pim", "POST /api/contacts/merge": "pim", "POST /api/contacts/merges/{}/undo": "pim",
    "POST /api/evcals": "pim", "POST /api/evcals/{}/import": "pim", "POST /api/events": "pim",
    "POST /api/events/{}/prep-task": "pim", "POST /api/events/{}/restore": "pim", "POST /api/events/{}/rsvp": "pim",
    "POST /api/v1/address-books": "pim", "POST /api/v1/address-books/{}/import": "pim", "POST /api/v1/contacts": "pim",
    "POST /api/v1/contacts/bulk": "pim", "POST /api/v1/event-calendars": "pim",
    "POST /api/v1/event-calendars/{}/import": "pim", "POST /api/v1/events": "pim", "POST /api/v1/events/{}/prep-task": "pim",
    "POST /api/v1/events/{}/restore": "pim", "POST /api/v1/events/{}/rsvp": "pim", "PUT /api/books/{}/members": "pim",
    "PUT /api/contacts/{}/care": "life_org", "PUT /api/evcals/{}/members": "pim", "PUT /api/v1/address-books/{}/members/{}": "pim",
    "PUT /api/v1/contacts/{}/care": "pim", "PUT /api/v1/event-calendars/{}/members/{}": "pim",
    # ---- public (19)
    "GET /": "public", "GET /agent-setup.ps1": "public", "GET /agent-setup.sh": "public", "GET /api/about": "public", "POST /api/client-errors": "clienterr",
    "GET /api/health": "public", "GET /api/layouts/std": "public", "GET /api/related/config": "public",
    "GET /api/v1/announcement": "public", "GET /api/v1/openapi.json": "public", "GET /api/version": "public",
    "GET /capture": "public", "GET /manifest.json": "public", "GET /robots.txt": "public", "GET /share": "public",
    "GET /sw.js": "public", "GET /sw-manifest.json": "public",  # 2.149.0 B (#2506): the service worker's file hashes
    "GET /api/code-manifest": "public",  # 2.742.0 (#5217): the web manifest, only hashes of the code, no data of a person
    "GET /static/i18n/{}.core.json": "public", "GET /static/i18n/{}.mod-{}.json": "public",  # 2.191.0 A (#2518): the split language files
    "POST /api/qr": "public", "POST /drop": "public", "POST /drop/drop": "public",
    "POST /share": "public",
    # ---- pure (1)
    "POST /api/outline/parse": "pure",
    # ---- tasks (192)
    "DELETE /api/attachments/{}": "tasks", "DELETE /api/chat-files/{}": "tasks", "DELETE /api/comments/{}": "tasks",
    "POST /api/comments/{}/restore": "tasks",  # 2.530.0 A (#4315): p4315_a_comment_trash_test.py, freelancer-matrix: tasks
    # 2.550.0 (#4528): the field trash and a removed member's way back (p4528_b_restore_test.py, freelancer-matrix: lists)
    "GET /api/lists/{}/fields/trash": "lists", "POST /api/fields/trash/{}/restore": "lists",
    "GET /api/lists/{}/member-memos": "lists", "POST /api/lists/{}/members/{}/restore": "lists",
    "DELETE /api/deps/{}/{}": "tasks", "DELETE /api/envs/{}": "tasks", "DELETE /api/envs/{}/deploys/{}": "tasks",
    "DELETE /api/list-checks/{}": "tasks", "DELETE /api/notepads/{}": "tasks", "DELETE /api/notes/{}": "tasks",
    "POST /api/notes/{}/restore": "tasks", "POST /api/v1/notes/{}/restore": "tasks",  # 2.272.0 E1 (#3038)
    # 2.576.0 (#3371): saved relations between tasks (p2576_d_links_api_test.py, freelancer-matrix: tasks)
    "GET /api/tasks/{}/relations": "tasks", "POST /api/tasks/{}/relations": "tasks", "DELETE /api/tasks/{}/relations/{}": "tasks",
    "GET /api/v1/tasks/{}/relations": "tasks", "POST /api/v1/tasks/{}/relations": "tasks", "DELETE /api/v1/tasks/{}/relations/{}": "tasks",
    "POST /api/notes/quick-list": "tasks",  # 2.477.0 (#3881): the private list Notes (p2477_quicknote_api_test.py, freelancer-matrix: tasks)
    "DELETE /api/repos/{}": "tasks", "DELETE /api/sample": "tasks", "DELETE /api/sprints/{}": "tasks",
    "DELETE /api/tasks/{}": "tasks", "DELETE /api/tasks/{}/contacts/{}": "tasks", "DELETE /api/tasks/{}/enc-note": "tasks",
    "DELETE /api/tasks/{}/links/{}": "tasks", "DELETE /api/tasks/{}/note-lock": "tasks",
    "DELETE /api/tasks/{}/waiting": "tasks", "DELETE /api/trash": "tasks",
    "GET /api/trash/purge-info": "tasks",  # 2.530.0 D (#4316): the numbers before deleting for good (p2530_d_cascade_test.py, freelancer-matrix: tasks)
    # 2.102.0 A (#1988): the list trash (p2102_a_api_test.py: a person without an organisation deletes / restores / purges)
    "GET /api/trash/lists": "lists", "POST /api/trash/lists/{}/restore": "lists", "DELETE /api/trash/lists/{}": "lists",
    # 2.567.0 A (#4707): the trash of sections, sprints, key links, templates (p2567_a_trash_test.py)
    "GET /api/trash/parts": "lists", "POST /api/sections/{}/restore": "lists", "POST /api/sprints/{}/restore": "tasks",
    "POST /api/lists/{}/links/{}/restore": "lists", "POST /api/templates/{}/restore": "lists",
    "GET /api/trash/lists/{}/export.zip": "office",  # 2.186.1 (#2732): a kept project for its custodian (p2146_d_api)
    "POST /api/trash/lists/{}/export.zip": "office",  # 2.223.2 C (#2871): its step-up (a one-time ticket)
    "DELETE /api/v1/attachments/{}": "tasks",
    "POST /api/v1/attachments/{}/restore": "tasks", "POST /api/v1/list-files/{}/restore": "lists",  # 2.610.0 (#4010): p2610_c_v1restore_test.py
    "DELETE /api/v1/chat-attachments/{}": "tasks", "DELETE /api/v1/comments/{}": "tasks",
    "DELETE /api/v1/comments/{}/reactions/{}": "tasks", "DELETE /api/v1/notepads/{}": "tasks",
    "DELETE /api/v1/notes/{}": "tasks", "DELETE /api/v1/tasks/{}": "tasks", "DELETE /api/v1/tasks/{}/contacts/{}": "tasks",
    "DELETE /api/v1/tasks/{}/dependencies/{}": "tasks", "DELETE /api/v1/tasks/{}/links/{}": "tasks",
    "DELETE /api/v1/tasks/{}/waiting": "tasks", "DELETE /api/v1/trash": "tasks", "GET /api/attachments/{}": "tasks",
    "GET /api/inbox": "tasks", "GET /api/v1/me/waiting": "tasks",  # 2.392.0 D (#3369)
    "GET /api/briefing": "tasks", "GET /api/chat-files/{}": "tasks", "GET /api/comments/{}/choice": "tasks",
    "GET /api/dayplan": "tasks", "GET /api/dayplan/review": "tasks", "GET /api/deps": "tasks", "GET /api/export.json": "tasks", "GET /api/export/todoist.zip": "tasks", "GET /api/export/markdown.zip": "tasks", 
    "GET /api/ical": "tasks", "GET /api/imports": "tasks", "GET /api/news": "tasks", "GET /api/notes": "tasks",
    "GET /api/notes/{}": "tasks", "GET /api/occurrences": "tasks", "GET /api/pomo/stats": "tasks", "GET /api/roadmap": "tasks",
    "GET /api/search": "tasks", "GET /api/search/messages": "tasks", "GET /api/sprints/{}": "tasks", "GET /api/stale": "tasks", "GET /api/state": "tasks",
    "GET /api/state/delta": "tasks", "GET /api/state/lists": "tasks", "GET /api/stats": "tasks", "GET /api/tags/count": "tasks", "GET /api/tasks": "tasks",
    "GET /api/tasks/{}/watchers": "tasks", "POST /api/tasks/{}/watchers": "tasks", "DELETE /api/tasks/{}/watchers/{}": "tasks",  # 2.473.0 (#3357)
    "GET /api/v1/tasks/{}/watchers": "tasks", "POST /api/v1/tasks/{}/watchers": "tasks", "DELETE /api/v1/tasks/{}/watchers/{}": "tasks",
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
    "POST /api/envs/{}/restore": "tasks", "POST /api/favorites/suggestion": "tasks", "GET /api/favorites/targets": "tasks", "POST /api/ical": "tasks",
    "POST /api/import/{}": "tasks", "POST /api/imports/{}/undo": "tasks",
    "POST /api/list-checks/{}/run": "tasks", "POST /api/news/dismiss": "tasks", "POST /api/news/read": "tasks",
    "POST /api/pdf-text": "tasks", "POST /api/pomo/start": "tasks", "POST /api/pomo/{}/{}": "tasks",
    "POST /api/repos/{}/refresh": "tasks", "POST /api/sample": "tasks", "POST /api/sprints/{}/close": "tasks",
    "POST /api/sprints/{}/start": "tasks", "POST /api/tags/delete": "tasks", "POST /api/tags/restore": "tasks",
    "POST /api/tasks": "tasks", "POST /api/tasks/batch": "tasks", "POST /api/tasks/purge-done": "tasks",
    "POST /api/tasks/reorder": "tasks", "POST /api/tasks/similar": "tasks", "POST /api/tasks/{}/approval": "tasks",
    "POST /api/tasks/{}/attachments": "tasks", "POST /api/tasks/{}/bell/undo": "tasks",
    "POST /api/tasks/{}/chain/pull": "tasks", "POST /api/tasks/{}/comments": "tasks", "POST /api/tasks/{}/complete": "tasks",
    "POST /api/tasks/{}/contacts": "tasks", "POST /api/tasks/{}/editing": "tasks",
    "POST /api/tasks/{}/duplicate": "tasks", "POST /api/tasks/{}/enc-attachments": "tasks", "POST /api/tasks/{}/git-undo": "tasks", "POST /api/tasks/{}/links": "tasks",
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
    "POST /api/v1/tasks/{}/move": "tasks", "POST /api/v1/tasks/{}/reopen": "tasks", "POST /api/v1/tasks/{}/restore": "tasks", "POST /api/v1/tasks/{}/state": "tasks",
    "POST /api/v1/tasks/{}/review": "tasks", "POST /api/v1/tasks/{}/skip": "tasks", "POST /api/v1/tasks/{}/snippets": "tasks",
    "POST /api/v1/tasks/{}/subtasks": "tasks", "POST /api/v1/tasks/{}/take": "tasks", "POST /api/v1/tasks/{}/tidy": "tasks",
    "POST /api/v1/tasks/{}/to-shopping": "tasks", "POST /api/v1/tasks/{}/typing": "tasks",
    "PUT /api/tasks/mine-order": "tasks", "PUT /api/tasks/{}/bell": "tasks", "PUT /api/tasks/{}/enc-note": "tasks",
    "POST /api/mine-sections": "tasks", "POST /api/mine-sections/init": "tasks", "PATCH /api/mine-sections/{}": "tasks", "DELETE /api/mine-sections/{}": "tasks", "PUT /api/mine-sections/order": "tasks",  # 2.569.0 (#4395): p2569_a_mine_sections_test.py
    "GET /api/mine-rules": "tasks", "POST /api/mine-rules": "tasks", "PATCH /api/mine-rules/{}": "tasks", "DELETE /api/mine-rules/{}": "tasks", "POST /api/mine-rules/{}/restore": "tasks", "PUT /api/mine-rules/order": "tasks", "POST /api/mine-rules/apply": "tasks",  # 2.823.0 (#4773): p2823_a_mine_rules_test.py
    "PUT /api/tasks/{}/note-lock": "tasks", "PUT /api/tasks/{}/waiting": "tasks", "PUT /api/v1/tasks/{}/waiting": "tasks",
    "PUT /api/workload/capacity/{}": "tasks",
    # ---- team (43)
    "DELETE /api/disc/blocks/{}": "team", "DELETE /api/disc/connections/{}": "team", "DELETE /api/disc/requests/{}": "team",
    "DELETE /api/e2e/keys": "team", "DELETE /api/team/messages/{}": "team", "DELETE /api/users/{}": "team",
    "POST /api/team/messages/{}/restore": "team",  # 2.530.0 A (#4315): p4315_a_comment_trash_test.py, freelancer-matrix: team
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
    "GET /api/videos/{}/versions/{}/file": "videos", "GET /api/v1/videos/{}/versions/{}/file": "videos",  # 2.641.0 (#4769): p2641_b_media_test.py
    "GET /api/videos/trash": "videos",  # 2.549.0 (#4536): the video trash of the app (p2549_c_vtrash_test.py)
    # 2.99.1 C (#1959): video sign-offs for agents (videos/v1.py; p2991_c_api_test.py)
    "GET /api/v1/videos": "videos", "GET /api/v1/videos/{}": "videos", "POST /api/v1/videos/{}/comments": "videos",
    "PATCH /api/v1/videos/{}/comments/{}": "videos",
    "DELETE /api/sheets/{}": "sheets", "DELETE /api/sheets/{}/columns/{}": "sheets",
    "DELETE /api/sheets/{}/rows/{}": "sheets", "GET /api/sheets": "sheets", "GET /api/sheets/{}": "sheets",
    # 2.558.0 (#4709): the core objects (core/objweb.py)
    "GET /api/obj/{}": "obj", "POST /api/obj/{}": "obj", "GET /api/obj/{}/{}": "obj", "PATCH /api/obj/{}/{}": "obj",
    "GET /api/docs/views": "obj", "GET /api/docs/views/{}/hits": "obj", "POST /api/docs/views/{}/share": "obj",  # 2.579.0 (#4802): saved document views (p2579_c_api_test.py)
    "POST /api/docs/views/count": "obj",  # 2.857.0 (#5518): the live count of the documents filter dialog (p2857_a_docfilter_test.py)
    "POST /api/obj/{}/{}/trash": "obj", "POST /api/obj/{}/{}/restore": "obj", "DELETE /api/obj/{}/{}": "obj",
    "GET /api/obj/{}/{}/history": "obj", "POST /api/obj/{}/{}/undo": "obj", "GET /api/obj/{}/{}/shares": "obj",
    "POST /api/obj/{}/{}/shares": "obj", "DELETE /api/obj/{}/{}/shares/{}": "obj", "POST /api/obj/{}/{}/shares/{}/restore": "obj",
    "GET /api/v1/agent/objects/{}": "obj", "GET /api/v1/agent/objects/{}/{}": "obj", "PATCH /api/v1/agent/objects/{}/{}": "obj",
    "POST /api/v1/agent/objects/{}/{}/proposals": "obj",  # 2.623.0 (#4718): an agent's change proposal (p2623_c_objprop_test.py)
    "GET /api/undo": "undo", "POST /api/undo/to/{}": "undo", "POST /api/undo/{}/redo": "undo",  # 2.747.0 (#5249): the own step groups (p2747_b_undo_core_test.py, freelancer-matrix: undo)
    "GET /api/sheets/{}/export.csv": "sheets", "GET /api/sheets/{}/export.xlsx": "sheets",
    "GET /api/sheets/{}/links": "sheets", "GET /api/sheets/{}/vars": "sheets", "GET /api/v1/sheets": "sheets",
    "GET /api/v1/sheets/{}": "sheets", "GET /api/v1/sheets/{}/vars": "sheets", "PATCH /api/sheets/{}": "sheets",
    # 2.97.0 C (#2049): office moves (p297_c_api_test.py) - routes below this line
    "POST /api/office/move-space": "office",
    # 2.137.0 D (#1981): the personal office into an organisation the person is an admin of (p2137_d_api_test.py)
    "GET /api/office/move/check": "office", "POST /api/office/move/org": "office",
    # 2.96.0 B (#1941): a table to the other workspace
    "POST /api/sheets/{}/move-space": "sheets",
    "POST /api/sheets/{}/print.pdf": "sheets",  # 2.578.0 (#3462): the print view as PDF (p2578_d_api_test.py: a private table)
    "POST /api/lists/{}/move-space": "lists",  # 2.401.0 (#2924): p2401_a_api_test.py (409 without an organisation: no other workspace)
    # 2.407.0 A (#3513): "agent is working" on a task (p2407_a_api_test.py: the own agent of a person without an organisation)
    "GET /api/v1/tasks/{}/working": "agents", "POST /api/v1/tasks/{}/working": "agents",
    "PATCH /api/v1/tasks/{}/working": "agents", "DELETE /api/v1/tasks/{}/working": "agents",
    # 2.124.0 C (#2113): shares of one table (p2124_c_api_test.py)
    "GET /api/sheets/{}/shares": "sheets", "POST /api/sheets/{}/shares": "sheets",
    "PATCH /api/sheets/{}/shares/{}": "sheets", "DELETE /api/sheets/{}/shares/{}": "sheets",
    "PUT /api/sheets/{}/chart": "sheets",  # 2.124.0 A (#2115): the chart of a table (p2124_a_api_test.py)
    "PUT /api/sheets/{}/rules": "sheets", "PUT /api/v1/sheets/{}/rules": "sheets",  # 2.578.0 (#3462 C): colour rules (p2578_c_fmt_test.py)
    "GET /api/sheets/folders": "sheets", "POST /api/sheets/folders": "sheets",  # 2.199.0 C (#2742): p2199_c_sheets_test.py
    "GET /api/sheets/trash": "sheets", "GET /api/sheets/{}/trash": "sheets", "POST /api/sheets/purge": "sheets",  # 2.528.0 (#4306 B22): p2528_c_sheets_test.py
    "GET /api/contacts/folders": "pim", "POST /api/contacts/folders": "pim",  # 2.351.0 B (#2749): p2351_b_contacts_tree_test.py
    # 2.124.0 E (#2116): the sheets of a table (p2124_e_api_test.py: a person without an organisation adds, renames, moves,
    # deletes and restores sheets of her private table; API v1 through the agents of the same test)
    "GET /api/sheets/{}/tabs": "sheets", "POST /api/sheets/{}/tabs": "sheets", "PATCH /api/sheets/{}/tabs/{}": "sheets",
    "DELETE /api/sheets/{}/tabs/{}": "sheets", "POST /api/sheets/{}/tabs/{}/restore": "sheets",
    "PUT /api/sheets/{}/tabs/{}/pivot": "sheets",  # 2.671.0 (#3463 b): the setting of a pivot sheet (p2671_c_pivot_test.py)
    "GET /api/v1/sheets/{}/tabs": "sheets", "POST /api/v1/sheets/{}/tabs": "sheets",
    "PATCH /api/sheets/{}/columns/{}": "sheets", "PATCH /api/v1/sheets/{}": "sheets", "POST /api/sheets": "sheets",
    "POST /api/sheets/{}/batches/{}/undo": "sheets", "POST /api/sheets/{}/cells/{}/freeze": "sheets",
    "POST /api/sheets/{}/cells/{}/name": "sheets", "POST /api/sheets/{}/columns": "sheets",
    "POST /api/sheets/{}/columns/{}/restore": "sheets", "POST /api/sheets/import": "sheets",
    "POST /api/sheets/{}/links/{}/redo": "sheets", "POST /api/sheets/{}/links/{}/undo": "sheets",
    "POST /api/sheets/{}/presence": "sheets", "POST /api/sheets/{}/restore": "sheets",
    "POST /api/sheets/{}/rows": "sheets", "POST /api/sheets/{}/rows-from-list": "sheets",
    "POST /api/sheets/{}/rows/order": "sheets", "POST /api/sheets/{}/rows/{}/restore": "sheets",
    "POST /api/sheets/{}/columns/order": "sheets",  # 2.631.0 (#4620): p2631_b_sheet_move_test.py
    "POST /api/sheets/{}/to-offer": "sheets", "POST /api/sheets/{}/to-tasks": "sheets", "POST /api/v1/sheets": "sheets",
    "POST /api/v1/sheets/{}/batches/{}/undo": "sheets", "POST /api/v1/sheets/{}/columns": "sheets",
    "POST /api/v1/sheets/{}/rows": "sheets", "PUT /api/sheets/{}/cells": "sheets", "PUT /api/v1/sheets/{}/cells": "sheets",
    # 2.124.0 B (#2110 #2111 #2112): p2124_b_api_test.py (a person without an organisation in her private table)
    "GET /api/sheets/{}/people": "sheets", "POST /api/sheets/{}/files": "sheets", "GET /api/sheets/{}/files/{}": "sheets", "GET /api/sheets/{}/files/{}/{}": "sheets",
    "POST /api/sheets/{}/fixed": "sheets", "GET /api/sheets/{}/history": "sheets", "GET /api/sheets/{}/cells/{}/history": "sheets",
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
    # 2.113.1 B (#2059): channels, groups, files of the team chat (p2113b_b_api_test.py, a private channel of a freelancer)
    "GET /api/team/channels": "team", "POST /api/team/channels": "team", "POST /api/team/groups": "team",
    "PATCH /api/team/rooms/{}": "team", "POST /api/team/rooms/{}/members": "team", "DELETE /api/team/rooms/{}/members/{}": "team",
    "GET /api/team/files/{}": "team", "GET /api/v1/team/channels": "team", "POST /api/v1/team/channels": "team",
    "POST /api/v1/team/groups": "team", "PATCH /api/v1/team/rooms/{}": "team", "POST /api/v1/team/rooms/{}/members": "team",
    "DELETE /api/v1/team/rooms/{}/members/{}": "team", "GET /api/v1/team/files/{}": "team",
    # 2.565.0 (#4719): a channel shared with a group (p2565_c_kern_teamchat_test.py, a private channel of a freelancer on the core)
    "DELETE /api/team/rooms/{}/groups/{}": "team", "DELETE /api/v1/team/rooms/{}/groups/{}": "team",  # p2565_c_kern_teamchat_test.py
    # ---- time (28)
    "DELETE /api/habits/{}": "time", "POST /api/habits/{}/restore": "time", "DELETE /api/time/entries/{}": "time", "DELETE /api/v1/habits/{}": "time",  # 2.530.0 B (#4315): restore
    "DELETE /api/v1/time/entries/{}": "time", "DELETE /api/v1/time/timer": "time", "GET /api/time/entries": "time",
    "GET /api/time/export.csv": "time", "GET /api/time/export.xlsx": "time", "GET /api/workload/export.xlsx": "tasks",  # 2.125.0 C (#2122)
    "GET /api/time/gaps": "time", "GET /api/time/report": "time",
    "GET /api/v1/habits/{}/stats": "time", "GET /api/v1/focus": "time", "GET /api/v1/focus/stats": "time",  # 2.116.0 D (#2067)
    "POST /api/v1/focus/start": "time", "POST /api/v1/focus/{}/stop": "time", "POST /api/v1/focus/{}/pause": "time",
    "POST /api/v1/focus/{}/resume": "time",
    "GET /api/v1/habits": "time", "GET /api/v1/time/check": "time", "GET /api/v1/time/entries": "time",
    "GET /api/v1/time/from-events": "time", "GET /api/v1/time/gaps": "time", "GET /api/v1/time/timer": "time",
    "PATCH /api/habits/{}": "time", "PATCH /api/time/entries/{}": "time", "GET /api/time/entries/{}": "time",  # 2.576.0 (#4764)
    "PATCH /api/v1/habits/{}": "time",
    "PATCH /api/v1/time/entries/{}": "time", "POST /api/habits": "time", "POST /api/habits/{}/log": "time",
    "POST /api/time/entries": "time", "POST /api/time/start": "time", "POST /api/time/stop": "time",
    "POST /api/v1/habits": "time", "POST /api/v1/habits/{}/checkin": "time", "POST /api/v1/time/entries": "time",
    "POST /api/v1/time/timer": "time",
    "GET /api/videos/signoffs/orphaned": "own", "DELETE /api/videos/signoffs/orphaned/{}": "own",  # 2.360.2 D (#2561)
    "GET /api/time/sheets": "time", "POST /api/time/sheets": "time", "POST /api/time/sheets/decide": "time",  # 2.125.0 B (#2119)
    # ---- token (3)
    "POST /api/hooks/deploy/{}/{}": "token", "POST /api/hooks/git/{}": "token", "POST /api/hooks/issues/{}/{}": "token", "POST /api/hooks/issues/{}": "token",
    # 2.115.0 A (#2061): inbound webhooks of a list (p2115_a_api_test.py calls them as a person without an organisation);
    # the hook URL itself is a secret token; the webhooks of an organisation are managed by its admins
    "POST /api/hooks/pay/{}": "token",  # 2.469.0 (#3459)
    "POST /api/hooks/in/{}": "token", "POST /api/hooks/in": "token", "GET /api/lists/{}/hooks-in": "lists",  # 2.380 G (#2289): header variant
    "POST /api/lists/{}/hooks-in": "lists",
    "PATCH /api/hooks-in/{}": "lists", "DELETE /api/hooks-in/{}": "lists", "POST /api/hooks-in/{}/rotate": "lists",
    "POST /api/hooks-in/{}/restore": "lists",
    "GET /api/orgs/{}/webhooks": "orgadmin", "POST /api/orgs/{}/webhooks": "orgadmin", "PATCH /api/orgs/{}/webhooks/{}": "orgadmin",
    "DELETE /api/orgs/{}/webhooks/{}": "orgadmin", "POST /api/orgs/{}/webhooks/{}/secret": "orgadmin",
    "POST /api/orgs/{}/webhooks/{}/test": "orgadmin", "GET /api/orgs/{}/webhooks/{}/log": "orgadmin",
    # 2.142.0 A (#2145): a person's notification channels (p2142_a_api_test.py as a person without an organisation, with the
    # private area's own list events); an organisation's channels are managed by its admins
    "GET /api/me/channels": "own", "POST /api/me/channels": "own", "PATCH /api/me/channels/{}": "own",
    "DELETE /api/me/channels/{}": "own", "POST /api/me/channels/{}/test": "own",
    "GET /api/orgs/{}/channels": "orgadmin", "POST /api/orgs/{}/channels": "orgadmin", "PATCH /api/orgs/{}/channels/{}": "orgadmin",
    "DELETE /api/orgs/{}/channels/{}": "orgadmin", "POST /api/orgs/{}/channels/{}/test": "orgadmin",
    # ---- wiki (24)
    "GET /api/recent": "wiki",  # 2.769.0 (#5352): "Recently edited" over Knowledge, Files and Reading (p2769_d_recent_api_test.py)
    "DELETE /api/wiki/pages/{}": "wiki", "GET /api/wiki": "wiki", "GET /api/wiki/e2e": "wiki",
    "GET /api/wiki/e2e/todo": "wiki", "GET /api/wiki/export": "wiki", "GET /api/wiki/mentions": "wiki",
    "GET /api/wiki/pages/{}": "wiki", "GET /api/wiki/search": "wiki", "PATCH /api/wiki/pages/{}": "wiki",
    "POST /api/wiki/e2e/bulk": "wiki", "POST /api/wiki/e2e/finish": "wiki", "POST /api/wiki/e2e/keys": "wiki",
    "POST /api/wiki/e2e/rotate": "wiki", "POST /api/wiki/e2e/start": "wiki", "POST /api/wiki/e2e/stop": "wiki",
    "POST /api/wiki/import": "wiki", "POST /api/wiki/move": "wiki", "POST /api/wiki/pages": "wiki",
    "POST /api/wiki/e2e/newid": "wiki", "POST /api/team/rooms/{}/msgid": "team",  # 2.640.0 (#3388): AAD v2 ids (p2640_b_aad_test.py)
    "POST /api/wiki/folders": "wiki",  # 2.200.0 A (#2747): an empty knowledge folder (p2200_a_wiki_folder_test.py)
    "GET /api/wiki/tags": "wiki", "GET /api/wiki/query": "wiki",  # 2.371 (#3150): tags + the abfrage block (p2371_wiki_tags_test.py)
    # 2.200.0 C (#1781): API v1 (p2200_c_wiki_agent_test.py: her token and her own agent in the private workspace)
    "GET /api/v1/wiki/pages": "wiki", "GET /api/v1/wiki/pages/{}": "wiki", "POST /api/v1/wiki/pages": "wiki", "PATCH /api/v1/wiki/pages/{}": "wiki",
    "GET /api/v1/wiki/pages/{}/files": "wiki", "GET /api/v1/wiki/files/{}": "wiki", "GET /api/v1/wiki/files/{}/text": "wiki",  # 2.488.0 (#2209)
    # 2.200.0 B (#2747): a page / folder in a folder shared with me (p2200_b_wiki_share_test.py)
    "POST /api/wiki/shared/pages": "wiki", "POST /api/wiki/shared/folders": "wiki",
    # 2.177.0 (#2685): large knowledge ZIP imports in pieces, unpacked in the background (p2177_a_api_test.py)
    "POST /api/wiki/import/upload": "wiki", "PUT /api/wiki/import/upload/{}": "wiki", "GET /api/wiki/import/upload": "wiki",
    "GET /api/wiki/import/upload/{}": "wiki", "DELETE /api/wiki/import/upload/{}": "wiki",
    # 2.96.0 B (#1941): wiki pages / folders to the other workspace
    "POST /api/wiki/move-space": "wiki",
    "PUT /api/wiki/style": "wiki",  # 2.371.3 (#3152): the space's reading style (p2371_3_wiki_ui.js: frida sets her private workspace's)
    "POST /api/wiki/restore": "wiki", "POST /api/wiki/trash": "wiki",
    # 2.143.0 B (#2211): the trash of the private workspace (p2143_b_api_test.py)
    "GET /api/wiki/trash": "wiki", "POST /api/wiki/purge": "wiki",
    # 2.123.0 C (#2103, #2107): files of the file store / tables in pages (p2123_c_api_test.py: own private file store and tables)
    "POST /api/wiki/pages/{}/refs": "wiki", "GET /api/wiki/refs": "wiki",
    # 2.97.0 D (#2050 #2051): locked spaces / clean-up (p297_d_api_test.py) - routes below this line
    # 2.99.0 A (#2182): files of knowledge pages (p299_a_api_test.py: import, upload, read, delete in the private workspace)
    "GET /api/wiki/files/{}": "wiki", "GET /api/wiki/space-files": "wiki",  # 2.637.0 (#4745)
    "GET /api/wiki/files/{}/{}": "wiki", "DELETE /api/wiki/files/{}": "wiki",
    "POST /api/wiki/pages/{}/files": "wiki",
    # 2.123.0 B (#2104): shares of knowledge pages / folders (p2123_b_api_test.py: person + link in the private workspace); the public page = link
    "GET /api/wiki/shares": "wiki", "POST /api/wiki/shares": "wiki", "PATCH /api/wiki/shares/{}": "wiki", "DELETE /api/wiki/shares/{}": "wiki",
    "POST /api/wiki/shares/{}/restore": "wiki", "GET /api/wiki/shared": "wiki", "GET /api/wiki/shared/pages/{}": "wiki",
    "GET /api/wiki/shared/files/{}": "wiki", "GET /api/wiki/shared/files/{}/{}": "wiki",
    "GET /api/wiki/shared/pages/{}/img/{}": "wiki",  # 2.380 H (#2356): p2380r_h_api_test.py (a person without an organisation)
    "GET /s/w/{}": "link", "GET /s/w/{}/p/{}": "link", "GET /s/w/{}/file/{}": "link",
    "GET /s/w/{}/img/{}/{}": "link",  # 2.380 H (#2356)
    # 2.123.0 A (#2102): the history of a page (p2123_a_api_test.py: list, read, restore in the private workspace)
    "GET /api/wiki/pages/{}/versions": "wiki", "GET /api/wiki/pages/{}/versions/{}": "wiki",
    "POST /api/wiki/pages/{}/versions/{}/restore": "wiki",
    # 2.90.0 - 2.92.0: bookkeeping, bank, tax dates, invoice series, subscriptions, agreements, equipment, file preview
    "DELETE /api/office/agreements/{}": "office", "DELETE /api/office/series/{}": "office",
    "GET /api/attachments/{}/agents": "tasks", "GET /api/attachments/{}/preview": "tasks",
    "GET /api/files/nodes/{}/preview": "files", "GET /api/list-files/{}/preview": "lists",
    "GET /api/office/agreements": "office", "GET /api/office/agreements/{}": "office",
    "GET /api/office/bank/imports": "office", "GET /api/office/bank/tx": "office",
    "GET /api/office/bank/tx/{}/candidates": "office", "GET /api/office/books": "office",
    "GET /api/office/books/euer": "office", "GET /api/office/books/euer.csv": "office", "GET /api/office/books/export": "office",  # 2.147.0 (#2461)
    "GET /api/office/books/euer.pdf": "office", "GET /api/office/books/ustva": "office",
    "GET /api/office/books/euer/compare": "office",  # 2.603.0 (#4921): the EUeR next to the year before
    "GET /api/office/books/taxform/euer": "office", "GET /api/office/books/taxform/euer.csv": "office", "GET /api/office/books/taxform/euer.pdf": "office",  # 2.467.0 (#3456)
    "GET /api/office/books/taxform/ust": "office", "GET /api/office/books/taxform/ust.csv": "office", "GET /api/office/books/taxform/ust.pdf": "office",
    "PUT /api/office/books/taxform/vat": "office",
    "GET /api/office/books/basis": "office", "PUT /api/office/books/basis": "office",  # 2.603.0 (#4927): p2603_c_euer_basis_test.py
    "GET /api/office/meals/{}/payment": "office", "PUT /api/office/meals/{}/payment": "office",  # 2.603.0 (#4927): p2603_c_euer_basis_test.py
    "GET /api/office/books/taxcheck": "office",  # 2.589.0 (#3458): the tax check (p2589_c_taxcheck_test.py)
    "GET /api/office/books/receipts": "office", "GET /api/office/books/receipts.csv": "office", "GET /api/office/books/receipts.zip": "office",  # 2.153.0 (#2055)
    "POST /api/office/books/receipts/checked": "office",  # 2.420.0 C (#3448): p24200_c_api_test.py
    "POST /api/office/receipts/submit": "office", "GET /api/office/receipts/mine": "office", "GET /api/office/receipts/submitted": "office",  # 2.356.0 D (#3129)
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
    # 2.616.0 (#2473): the direct bank fetch over FinTS (p2616_c_fints_test.py, freelancer-matrix: office)
    "GET /api/office/bank/fints": "office", "POST /api/office/bank/fints/start": "office", "POST /api/office/bank/fints/{}/mechanism": "office",
    "POST /api/office/bank/fints/{}/tan": "office", "POST /api/office/bank/fints/{}/poll": "office", "POST /api/office/bank/fints/{}/import": "office",
    "DELETE /api/office/bank/fints/{}": "office",
    # 2.299.0 B (#3191): bank rules (p2299_b_bankrules_test.py, also as a person without an organisation)
    "GET /api/office/bank/rules": "office", "POST /api/office/bank/rules": "office", "PUT /api/office/bank/rules/{}": "office",
    "DELETE /api/office/bank/rules/{}": "office", "POST /api/office/bank/rules/{}/restore": "office", "POST /api/office/bank/rules/{}/apply": "office",
    "POST /api/office/bank/rules/{}/revert": "office", "POST /api/office/bank/rules/decline": "office",
    "POST /api/office/series/{}/restore": "office", "POST /api/office/series/{}/run": "office",
    "PUT /api/office/tax-dates": "office",
    # 2.93.0 A (#1927): document templates and documents with signature, the personal office of a freelancer in p293_a_api_test.py
    "GET /api/office/doc-templates": "office", "POST /api/office/doc-templates": "office", "PATCH /api/office/doc-templates/{}": "office",
    "DELETE /api/office/doc-templates/{}": "office", "POST /api/office/doc-templates/{}/restore": "office", "GET /api/office/doc-templates/starters": "office",
    "GET /api/office/gen-docs": "office", "POST /api/office/gen-docs": "office", "GET /api/office/gen-docs/{}": "office", "PATCH /api/office/gen-docs/{}": "office",
    "DELETE /api/office/gen-docs/{}": "office", "POST /api/office/gen-docs/{}/restore": "office", "POST /api/office/gen-docs/preview": "office",
    "POST /api/office/gen-docs/{}/final": "office", "GET /api/office/gen-docs/{}/pdf": "office", "POST /api/office/gen-docs/{}/signoff": "office",
    "GET /api/office/gen-docs/{}/signoffs": "office",
    # 2.154.0 C (#2192): data protection sheets of a client (p2154_c_api_test.py)
    "GET /api/office/privacy-sheets": "office", "POST /api/office/privacy-sheets": "office", "PATCH /api/office/privacy-sheets/{}": "office",
    "DELETE /api/office/privacy-sheets/{}": "office", "POST /api/office/privacy-sheets/{}/restore": "office",
    "POST /api/office/privacy-sheets/{}/confirm": "office", "GET /api/office/privacy-sheets/{}/mail": "office",
    "POST /api/office/privacy-sheets/{}/send": "office", "POST /api/office/privacy-sheets/{}/signed": "office",
    "GET /api/office/privacy-sheets/{}/pdf": "office",
    # 2.93.0 B (#1928): the logbook, the personal office of a freelancer in p293_b_api_test.py
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
    "POST /api/office/logbook/close": "office",  # 2.152.0 (#2169): close a month of the logbook, the personal office of a freelancer in p2103_c_api_test.py
    # 2.94.0 (#1930): leads (personal office, p294_a_api_test.py); (#1929): the booking page (own calendar, p294_b_api_test.py),
    # its public pages (a customer without an account, the same for a freelancer's page: p294_b_api_test.py books on one)
    "DELETE /api/appt/types/{}": "pim", "GET /api/appt/bookings": "pim", "GET /api/appt/page": "pim", "GET /api/appt/types": "pim",
    "GET /api/office/deals/{}/convert": "office", "GET /api/v1/office/leads": "office", "GET /s/b/c/{}": "link",
    "GET /s/b/x/{}": "link", "GET /s/b/{}": "link", "GET /s/b/{}/{}": "link", "GET /s/b/{}/{}/{}": "link",
    "PATCH /api/appt/types/{}": "pim", "PATCH /api/v1/office/leads/{}": "office", "POST /api/appt/bookings/{}/cancel": "pim", "DELETE /api/appt/bookings/{}": "pim",
    "POST /api/appt/types": "pim", "POST /api/appt/types/{}/restore": "pim", "POST /api/office/deals/{}/convert": "office",
    "POST /api/office/deals/{}/unconvert": "office", "POST /api/office/leads/import": "office",
    "POST /api/office/leads/import/undo": "office", "POST /api/v1/office/leads": "office", "POST /s/b/c/{}": "link",
    "POST /s/b/x/{}": "link", "POST /s/b/{}/{}/{}": "link", "PUT /api/appt/page": "pim",
    # 2.644.0 (#3663): inquiries and deals for agents (personal office, p2644_b_pipeline_agent_test.py)
    "GET /api/v1/office/deals": "office", "POST /api/v1/office/deals": "office", "PATCH /api/v1/office/deals/{}": "office",
    # 2.117.0 B (#2285): PDF files of a framework contract (personal office of a freelancer in p2117_b_api_test.py)
    "GET /api/office/contracts/{}/files": "office", "POST /api/office/contracts/{}/files": "office",
    "GET /api/office/contracts/{}/files/{}": "office", "PATCH /api/office/contracts/{}/files/{}": "office",
    "DELETE /api/office/contracts/{}/files/{}": "office", "POST /api/office/contracts/{}/files/{}/restore": "office",
    # 2.120.0 B (#2088): documents in the customer portal of a freelancer's personal office (p2120_b_api_test.py)
    "GET /portal/docs/{}/pdf": "link", "POST /api/office/clients/{}/portal-link": "office",
    # 2.112.1 B (#2058): external share links of the file store (p21121_b_api_test.py calls them as a freelancer too)
    "GET /api/share-defaults": "files",  # 2.470.0 (#3596)
    "GET /api/files/nodes/{}/ext-links": "files", "POST /api/files/nodes/{}/ext-links": "files",
    "POST /api/files/ext-links/{}/regenerate": "files", "DELETE /api/files/ext-links/{}": "files",
    "POST /api/files/ext-links/{}/restore": "files", "GET /s/f/{}": "link", "POST /s/f/{}/unlock": "link",
    "GET /s/f/{}/d/{}": "link", "GET /s/f/{}/v/{}": "link", "GET /s/f/{}/zip": "link",
    # 2.138.0 D (#2256): number ranges of the office (p2138_d_api_test.py)
    "GET /api/office/number-ranges": "office", "POST /api/office/number-ranges/{}": "office",
    # 2.144.0 A (#2412): Stop in the agent chat and the agent's confirmation (p2144_a_api_test.py)
    "POST /api/agents/{}/abort": "agents", "POST /api/v1/agent/aborted": "agents",
    # 2.236.0 (#2904-#2911): the work style of an agent (owner / instance admin, else 404); C (#2906): its queue (p2236_c_queue_test.py)
    "GET /api/agents/{}/work-style": "agents", "PATCH /api/agents/{}/work-style": "agents", "GET /api/agents/{}/queue": "agents",
    "GET /api/v1/agent/queue": "agents", "PUT /api/v1/agent/queue": "agents",
    # 2.235.0 C (#2903): the standing rules of an agent (the agent itself; owner / instance admin, else 404; p2235_c_rules_api_test.py)
    "GET /api/v1/agent/rules": "agents", "POST /api/v1/agent/rules": "agents", "GET /api/agents/{}/rules": "agents",
    "POST /api/agents/{}/rules": "agents", "PATCH /api/agents/{}/rules/{}": "agents", "DELETE /api/agents/{}/rules/{}": "agents",
    # 2.235.0 B (#2902): the data lock of an agent (owner / instance admin, else 404; p2235_b_datalock_test.py)
    "GET /api/agents/{}/data-lock": "agents", "PATCH /api/agents/{}/data-lock": "agents",
    # 2.235.0 A (#2891 #2901): the control of an agent and the undo of its decisions (owner / instance admin, else 404; p2235_a_control_test.py)
    "GET /api/agents/{}/control": "agents", "PATCH /api/agents/{}/control": "agents", "POST /api/agents/{}/control/history/{}/undo": "agents",
    # 2.653.0 (#5079): the whole history page by page and the agent's own decision line (p2653_a_agentlog_test.py, freelancer-matrix: agents)
    "GET /api/agents/{}/control/history": "agents", "POST /api/v1/agent/decisions": "agents",
    # 2.557.0 C (#4670): the setup of a server agent -- its defaults and the starter pack (owner / instance admin, else 404; p2557_c_srvstarter_test.py)
    "GET /api/agents/server/defaults": "agents", "POST /api/agents/{}/server/starter": "agents",
    # 2.777.0 C (#5378): what of the starter pack is there / waits / is missing (as the POST; p2777_c_srvagent_test.py)
    "GET /api/agents/{}/server/starter": "agents",
    # 2.144.6 A (#2053): time entries to an invoice (office/timebill.py: the office area's client lists, release = office admin;
    # p21446_a_api_test.py)
    "GET /api/office/time-open": "office", "POST /api/office/docs/{}/time-release": "office",
    # 2.144.10 A (#2576): delete every trial document of the area, admin; a person without an organisation is their own admin (p214410_a_api_test.py)
    "POST /api/office/trial/delete-all": "office",
    "GET /api/office/trial": "office",  # 2.417.0 C (#3445): the count for the test mode section of the settings
    # 2.148.0 C (#2472): the procedure documentation (GoBD) of the office (p2148_c_api_test.py as a person without an organisation)
    "GET /api/office/procdoc": "office", "PUT /api/office/procdoc": "office", "GET /api/office/procdoc/versions": "office",
    "GET /api/office/procdoc.md": "office", "GET /api/office/procdoc.pdf": "office",
    # 2.148.0 A (#2471): locked periods + the export for the tax auditor; B (#2470): DATEV batch with receipt images (p2148_a_api_test.py / p2148_b_api_test.py as a person without an organisation)
    "GET /api/office/periods": "office", "POST /api/office/periods/lock": "office", "GET /api/office/gobd/export": "office",
    # 2.187.0 B (#2476): the office rights page (groups, memberships, log)
    "GET /api/office/rights": "office", "POST /api/office/rights/groups": "office", "PATCH /api/office/rights/groups/{}": "office",
    "DELETE /api/office/rights/groups/{}": "office", "PUT /api/office/rights/people/{}": "office", "GET /api/office/rights/log": "office",
    "GET /api/office/datev/zip": "office",
    # 2.168.0 A (#2665): a document's project, a project's documents (p2168_a_docproject_test.py as a person without an organisation)
    "POST /api/office/docs/{}/project": "office", "GET /api/lists/{}/office-docs": "office",
    # 2.537.0 C (#3433): tasks with a time budget from a quotation (p3433_c_offer_tasks_test.py as a person without an organisation)
    "GET /api/office/docs/{}/tasks": "office", "POST /api/office/docs/{}/tasks": "office",
    # 2.299.0 D (#3193): hide / show the hints of the receipt check (p2299_d_api_test.py as a person without an organisation)
    "POST /api/docs/{}/checks": "files",
    # 2.299.0 C (#3192): bank bookings without a receipt, their counter and the reminder (p2299_c_norc_test.py as a person without an organisation)
    "GET /api/office/bank/noreceipt": "office", "GET /api/office/bank/noreceipt/count": "office",
    "GET /api/office/bank/noreceipt/reminder": "office", "PUT /api/office/bank/noreceipt/reminder": "office",
    # 2.470.0 (#3596): the bank accounts of an office (pr2470_a_bankacc_test.py: another organisation 404, a person without an organisation the same)
    "GET /api/office/settings/bank-accounts": "office", "POST /api/office/settings/bank-accounts": "office", "PUT /api/office/settings/bank-accounts/{}": "office",
    "POST /api/office/settings/bank-accounts/{}/default": "office", "POST /api/office/settings/bank-accounts/{}/archive": "office",
    "POST /api/office/settings/bank-accounts/{}/restore": "office",
    # 2.444.0 (#3447): credit card statements (p2444_a_cards_test.py: another organisation 404, a person without an organisation the same)
    "GET /api/office/cards": "office", "POST /api/office/cards": "office", "PATCH /api/office/cards/{}": "office", "DELETE /api/office/cards/{}": "office",
    "POST /api/office/cards/{}/restore": "office", "GET /api/office/cards/{}/statements": "office", "POST /api/office/cards/{}/statements": "office",
    "GET /api/office/cards/statements/{}": "office", "GET /api/office/cards/statements/{}/file": "office", "PATCH /api/office/cards/statements/{}": "office",
    "DELETE /api/office/cards/statements/{}": "office", "POST /api/office/cards/statements/{}/restore": "office",
    "POST /api/office/cards/statements/{}/confirm": "office", "POST /api/office/cards/statements/{}/reopen": "office",
    "GET /api/office/cards/statements/{}/bank": "office", "POST /api/office/cards/statements/{}/lines": "office",
    "PATCH /api/office/cards/lines/{}": "office", "DELETE /api/office/cards/lines/{}": "office", "GET /api/office/cards/lines/{}/candidates": "office",
    "POST /api/office/cards/lines/{}/match": "office", "POST /api/office/cards/lines/{}/unmatch": "office", "POST /api/office/cards/lines/{}/upload": "office",
    "GET /api/office/cards/reminder": "office", "PUT /api/office/cards/reminder": "office",
    # 2.425.0 B (#3451): recurring providers of the bank bookings (p2425_b_api_test.py as a person without an organisation)
    "GET /api/office/bank/vendors": "office", "PUT /api/office/bank/vendors": "office", "PUT /api/office/bank/vendors/settings": "office",
    # 2.553.0 B (#3460): requests by e-mail of a project (p2553_b_reqmail_test.py, freelancer-matrix: hub: her own project's request address)
    "GET /api/lists/{}/request-mail": "hub", "PATCH /api/lists/{}/request-mail": "hub",
    # 2.658.0 (#5015): the audio file of the file store on the customer page of a sign-off (p2658_c_audiofile_test.py, also frida)
    "GET /s/q/{}/media": "link",
}


# 2.421.0 A (#2936): the proof of a write route (POST / PUT / PATCH / DELETE of a matrix area): a suite with the marker of its
# area (and in the run) calls the path -- "{}" = an f-string field, an id, or a "+ str(x) +" piece -- on a line naming the
# method (or the line before). Constants of a suite (O = "/api/office", V = B + "/api/v1") are put into the paths first; an
# /api/v1 route may stand without its prefix right after a quote (a client with the base /api/v1).
WRITES = ("POST", "PUT", "PATCH", "DELETE")
CONST_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(?:(?:B|\w*[a-z]\w*)\s*\+\s*)?(?:([A-Z_][A-Z0-9_]*)\s*\+\s*)?f?[\"'](/[\w/{}.-]*)[\"']\s*(?:#.*)?$", re.M)
HOLE = r"(?:\{[^{}\n]{1,80}\}|[\w.%-]{1,40}|[\"']\s*\+\s*[^\n+]{1,60}?\s*\+\s*f?[\"']|[\"']\s*\+\s*str\([^\n]{1,60}?\)(?=[\s,)]))"


def expand_consts(src):
    consts = {}
    for n, base, v in CONST_RE.findall(src):
        consts[n] = consts.get(base, "") + v if base else v
    for n in sorted(consts, key=len, reverse=True):
        v = consts[n]
        src = re.sub(r"\b" + n + r"\s*\+\s*f?([\"'])", lambda m: m.group(1) + v, src)
        src = src.replace("{" + n + "}", v)
    return src


def path_rx(path):
    piece = lambda a: "".join(HOLE if x == "{}" else re.escape(x) for x in re.split(r"(\{\})", a))  # noqa: E731
    body = piece(path)
    if path.startswith("/api/v1/"):
        body += r"|(?<=[\"'])" + piece(path[len("/api/v1"):])
    return re.compile(r"(?:" + body + r")(?![\w/.-])")


def open_call(prev, mw):
    """2.449.0 (#3800): the line above counts only as an open multi-line call: the method on it, no path of its own, brackets open"""
    return bool(mw.search(prev)) and "/api/" not in prev and prev.count("(") > prev.count(")")


def write_proven(route, texts):
    """route "METHOD /path": called in one of texts (expanded suite sources)?"""
    m, path = route.split(" ", 1)
    rx, mw = path_rx(path), re.compile(r"\b" + m + r"\b", re.I)
    anchor = max((path[len("/api/v1"):] if path.startswith("/api/v1/") else path).split("{}"), key=len)  # cheap pre-filter
    for t in texts:
        i = t.find(anchor)
        while i >= 0:
            a, b = t.rfind("\n", 0, i) + 1, t.find("\n", i)
            b = len(t) if b < 0 else b
            if rx.search(t[a:b]) and (mw.search(t[a:b]) or open_call(t[t.rfind("\n", 0, max(0, a - 1)) + 1:a], mw)):
                return True
            i = t.find(anchor, b + 1) if b < len(t) else -1
    return False


# 2.421.0 A (#2936): the write routes of matrix areas that no suite of their area called on 29.10.2026 (frozen: may only
# shrink; a new write route needs its call, a route called now must leave the list)
WRITE_UNPROVEN = set(x.strip() for x in """
DELETE /api/account/export
DELETE /api/books/{}/org
DELETE /api/budget/files/{}
DELETE /api/calendars/{}/events
DELETE /api/chat-files/{}
DELETE /api/deps/{}/{}
DELETE /api/disc/blocks/{}
DELETE /api/disc/connections/{}
DELETE /api/disc/requests/{}
DELETE /api/e2e/keys
DELETE /api/envs/{}
DELETE /api/family/contacts/{}
DELETE /api/family/kids/{}/pin
DELETE /api/family/rewards/{}
DELETE /api/folders/agents
DELETE /api/forms/{}
DELETE /api/hubmail/address
DELETE /api/layouts/saved/{}
DELETE /api/life/karakeep
DELETE /api/list-checks/{}
DELETE /api/lists/{}/favorite
DELETE /api/lists/{}/icon
DELETE /api/lists/{}/milestones/{}
DELETE /api/lists/{}/public-link
DELETE /api/me/avatar
DELETE /api/me/mail/token
DELETE /api/me/wait-suggestions
DELETE /api/me/webhooks/{}
DELETE /api/my/agents/{}/machines/{}
DELETE /api/newsletter
DELETE /api/newsletter/segments/{}
DELETE /api/notepads/{}
DELETE /api/office/logo
DELETE /api/office/meals/choices/{}
DELETE /api/office/meals/{}/file/{}
DELETE /api/office/packs/installed/{}/{}
DELETE /api/office/trash/{}
DELETE /api/office/trips/purposes/{}
DELETE /api/paperless
DELETE /api/paperless/zip
DELETE /api/push/subs/{}
DELETE /api/repos/{}
DELETE /api/rules/{}
DELETE /api/servers/{}
DELETE /api/servers/{}/tasks/{}
DELETE /api/supporter/{}
DELETE /api/tasks/{}/contacts/{}
DELETE /api/tasks/{}/enc-note
DELETE /api/tasks/{}/links/{}
DELETE /api/tasks/{}/note-lock
DELETE /api/v1/address-books/{}
DELETE /api/v1/address-books/{}/members/{}
DELETE /api/v1/chat-attachments/{}
DELETE /api/v1/clients/{}
DELETE /api/v1/comments/{}/reactions/{}
DELETE /api/v1/contacts/{}
DELETE /api/v1/event-calendars/{}
DELETE /api/v1/event-calendars/{}/members/{}
DELETE /api/v1/events/{}
DELETE /api/v1/family/rewards/{}
DELETE /api/v1/forms/{}
DELETE /api/v1/lists/{}
DELETE /api/v1/lists/{}/groups/{}
DELETE /api/v1/lists/{}/links/{}
DELETE /api/v1/lists/{}/members/{}
DELETE /api/v1/lists/{}/milestones/{}
DELETE /api/v1/lists/{}/tags/{}
DELETE /api/v1/notepads/{}
DELETE /api/v1/notes/{}
DELETE /api/v1/sections/{}
DELETE /api/v1/tasks/{}/contacts/{}
DELETE /api/v1/tasks/{}/dependencies/{}
DELETE /api/v1/tasks/{}/links/{}
DELETE /api/v1/tasks/{}/waiting
DELETE /api/v1/team/messages/{}
DELETE /api/v1/templates/{}
DELETE /api/v1/time/timer
DELETE /api/v1/trash
PATCH /api/books/{}/org
PATCH /api/calendars/{}/events
PATCH /api/docs/labels/{}/{}
PATCH /api/family/rewards/{}
PATCH /api/layouts/saved/{}
PATCH /api/list-checks/{}
PATCH /api/list-tags/{}
PATCH /api/lists/{}/error-hook
PATCH /api/lists/{}/links/{}
PATCH /api/lists/{}/milestones/{}
PATCH /api/me/tokens/{}
PATCH /api/me/webhooks/{}
PATCH /api/newsletter/segments/{}
PATCH /api/notepads/{}
PATCH /api/servers/self
PATCH /api/servers/{}
PATCH /api/servers/{}/tasks/{}
PATCH /api/supporter/nudge
PATCH /api/tasks/{}/links/{}
PATCH /api/tasks/{}/ticket
PATCH /api/v1/clients/{}
PATCH /api/v1/comments/{}
PATCH /api/v1/family/rewards/{}
PATCH /api/v1/fields/{}
PATCH /api/v1/forms/{}
PATCH /api/v1/lists/{}/error-hook
PATCH /api/v1/lists/{}/links/{}
PATCH /api/v1/lists/{}/milestones/{}
PATCH /api/v1/lists/{}/tags/{}
PATCH /api/v1/me/notifications
PATCH /api/v1/notepads/{}
PATCH /api/v1/sections/{}
PATCH /api/v1/team/messages/{}
PATCH /api/v1/templates/{}
POST /api/account/export/file
POST /api/agents/{}/chat/{}/reactions
POST /api/agents/{}/meeting-images
POST /api/agents/{}/share-all
POST /api/agents/{}/wake
POST /api/assistant/run
POST /api/briefing/read
POST /api/budget/{}/contracts
POST /api/calendars
POST /api/calendars/discover
POST /api/calendars/{}/events
POST /api/calendars/{}/events/restore
POST /api/calendars/{}/refresh
POST /api/calendars/{}/write
POST /api/clients/merge
POST /api/clients/merges/{}/undo
POST /api/comments/{}/apply
POST /api/comments/{}/choice
POST /api/disc/blocks/{}
POST /api/disc/check
POST /api/disc/confirm
POST /api/disc/connections/{}/restore
POST /api/disc/find
POST /api/disc/requests
POST /api/disc/requests/{}/{}
POST /api/docs/{}/accept
POST /api/envs/{}/restore
POST /api/events/{}/prep-task
POST /api/events/{}/rsvp
POST /api/family/deadlines
POST /api/family/kids/{}/rewards
POST /api/family/kids/{}/stars
POST /api/family/occasions
POST /api/family/packing
POST /api/family/rewards/{}/decide
POST /api/family/rewards/{}/request
POST /api/favorites/suggestion
POST /api/folders/delete
POST /api/folders/playbook/restore
POST /api/folders/repos
POST /api/hubmail/mailbox/check
POST /api/hubmail/mails/{}/assign
POST /api/layouts/offers
POST /api/layouts/offers/{}/accept
POST /api/layouts/offers/{}/decline
POST /api/layouts/saved
POST /api/layouts/saved/standard
POST /api/layouts/saved/{}/activate
POST /api/life/karakeep/sync
POST /api/life/upkeep
POST /api/list-checks/{}/run
POST /api/lists/reorder
POST /api/lists/{}/checks
POST /api/lists/{}/e2e/files/{}
POST /api/lists/{}/e2e/keys
POST /api/lists/{}/e2e/rotate
POST /api/lists/{}/e2e/stop
POST /api/lists/{}/header
POST /api/lists/{}/icon
POST /api/lists/{}/milestones
POST /api/lists/{}/notepads
POST /api/lists/{}/playbook/proposals/{}/apply
POST /api/lists/{}/playbook/proposals/{}/discard
POST /api/lists/{}/playbook/restore
POST /api/lists/{}/public-link/regenerate
POST /api/lists/{}/sections/order
POST /api/lists/{}/shift
POST /api/lists/{}/shop-areas
POST /api/lists/{}/signoffs/{}/revoke
POST /api/lists/{}/tags/promote
POST /api/me/drop-token
POST /api/me/mail/token
POST /api/me/pin/lock
POST /api/me/pin/unlock
POST /api/me/purpose
POST /api/me/webhooks/{}/secret
POST /api/me/webhooks/{}/test
POST /api/my/agents/{}/setup-code
POST /api/news/dismiss
POST /api/newsletter/consent/import
POST /api/newsletter/segments
POST /api/newsletter/sync
POST /api/notes/{}/restore
POST /api/notify-templates/asked
POST /api/office/catalog/refresh
POST /api/office/datev/import
POST /api/office/datev/import/check
POST /api/office/deals/{}/project
POST /api/office/deals/{}/restore
POST /api/office/drives/{}/restore
POST /api/office/drives/{}/trip
POST /api/office/gen-docs/tree/folders
POST /api/office/import
POST /api/office/legacy/counter
POST /api/office/legacy/runs/{}/tidy
POST /api/office/legacy/split
POST /api/office/letters/tree/folders
POST /api/office/logbook/close
POST /api/office/meals/{}/file/{}/restore
POST /api/office/meals/{}/restore
POST /api/office/packs/install
POST /api/office/packs/installed/{}/{}/restore
POST /api/office/packs/validate
POST /api/office/receipts/tree/folders
POST /api/onboarding
POST /api/orgs/{}/export/file
POST /api/paperless/import
POST /api/paperless/stop
POST /api/paperless/zip
POST /api/paperless/zip/import
POST /api/paperless/zip/part
POST /api/paperless/zip/stop
POST /api/pdf-text
POST /api/pomo/start
POST /api/pomo/{}/{}
POST /api/push/handled
POST /api/push/test
POST /api/push/unsubscribe
POST /api/rules/{}/restore
POST /api/servers
POST /api/servers/code
POST /api/servers/move
POST /api/servers/{}/news/read
POST /api/servers/{}/restore
POST /api/servers/{}/tasks
POST /api/servers/{}/tasks/{}/{}
POST /api/sheets/{}/links/{}/redo
POST /api/sheets/{}/links/{}/undo
POST /api/sheets/{}/rows-from-list
POST /api/sheets/{}/to-offer
POST /api/sprints/{}/close
POST /api/sprints/{}/start
POST /api/supporter/{}/swap
POST /api/tasks/similar
POST /api/tasks/{}/chain/pull
POST /api/tasks/{}/editing
POST /api/tasks/{}/enc-attachments
POST /api/tasks/{}/list-attachments
POST /api/tasks/{}/take
POST /api/tasks/{}/to-shopping
POST /api/tasks/{}/typing
POST /api/tasks/{}/wake
POST /api/team/absences/{}/restore
POST /api/team/messages/{}/pin
POST /api/trash/lists/{}/export.zip
POST /api/users/{}/approve
POST /api/users/{}/invite
POST /api/users/{}/signin-link
POST /api/v1/agent/chats/{}/messages/{}/pin
POST /api/v1/agent/chats/{}/messages/{}/reactions
POST /api/v1/agent/chats/{}/messages/{}/withdraw
POST /api/v1/agents/{}/chat/{}/choice
POST /api/v1/agents/{}/chat/{}/reactions
POST /api/v1/clients
POST /api/v1/clients/bulk
POST /api/v1/comments/{}/choice
POST /api/v1/comments/{}/reactions
POST /api/v1/comments/{}/withdraw
POST /api/v1/contacts/bulk
POST /api/v1/event-calendars/{}/import
POST /api/v1/events/{}/prep-task
POST /api/v1/events/{}/restore
POST /api/v1/events/{}/rsvp
POST /api/v1/family/deadlines
POST /api/v1/family/kids/{}/rewards
POST /api/v1/family/kids/{}/stars
POST /api/v1/family/occasions
POST /api/v1/family/packing
POST /api/v1/family/rewards/{}/decide
POST /api/v1/family/rewards/{}/request
POST /api/v1/folders/delete
POST /api/v1/folders/rename
POST /api/v1/imports/{}/undo
POST /api/v1/layouts/proposals
POST /api/v1/life/contracts
POST /api/v1/life/devices
POST /api/v1/life/health
POST /api/v1/life/karakeep/sync
POST /api/v1/life/trips
POST /api/v1/life/upkeep
POST /api/v1/lists/{}/deployments
POST /api/v1/lists/{}/duplicate
POST /api/v1/lists/{}/fields
POST /api/v1/lists/{}/files
POST /api/v1/lists/{}/forms
POST /api/v1/lists/{}/join
POST /api/v1/lists/{}/links
POST /api/v1/lists/{}/milestones
POST /api/v1/lists/{}/notepads
POST /api/v1/lists/{}/notes
POST /api/v1/lists/{}/owner
POST /api/v1/lists/{}/playbook/proposals
POST /api/v1/lists/{}/sections
POST /api/v1/lists/{}/shift
POST /api/v1/lists/{}/shop-areas
POST /api/v1/lists/{}/sprints/assign
POST /api/v1/lists/{}/tags
POST /api/v1/me/purpose
POST /api/v1/news/read
POST /api/v1/notes/{}/restore
POST /api/v1/tasks/{}/approval
POST /api/v1/tasks/{}/attachments
POST /api/v1/tasks/{}/attachments/text
POST /api/v1/tasks/{}/contacts
POST /api/v1/tasks/{}/dependencies
POST /api/v1/tasks/{}/links
POST /api/v1/tasks/{}/move
POST /api/v1/tasks/{}/restore
POST /api/v1/tasks/{}/review
POST /api/v1/tasks/{}/skip
POST /api/v1/tasks/{}/snippets
POST /api/v1/tasks/{}/take
POST /api/v1/tasks/{}/tidy
POST /api/v1/tasks/{}/to-shopping
POST /api/v1/tasks/{}/typing
POST /api/v1/team/dm
POST /api/v1/team/messages/{}/pin
POST /api/v1/team/messages/{}/reactions
POST /api/v1/team/rooms/{}/members
POST /api/v1/templates
POST /api/v1/templates/{}/apply
POST /api/v1/time/timer
POST /api/wiki/e2e/keys
POST /api/wiki/e2e/stop
POST /api/wiki/import/upload
PUT /api/agents/{}/autoshare
PUT /api/agents/{}/permission-mode
PUT /api/assistant/lists
PUT /api/disc
PUT /api/family/kids/{}/pin
PUT /api/folder-heads
PUT /api/folders/agents
PUT /api/folders/playbook
PUT /api/folders/public-links
PUT /api/life/karakeep
PUT /api/lists/{}/folder-repo
PUT /api/lists/{}/header
PUT /api/lists/{}/icon
PUT /api/lists/{}/in-mine
PUT /api/lists/{}/layout
PUT /api/lists/{}/links/order
PUT /api/lists/{}/page-style
PUT /api/me/avatar
PUT /api/newsletter
PUT /api/newsletter/consent
PUT /api/office/cashflow/actual
PUT /api/office/cashflow/check
PUT /api/office/logbook/settings
PUT /api/supporter/{}
PUT /api/tasks/{}/enc-note
PUT /api/tasks/{}/note-lock
PUT /api/v1/address-books/{}/members/{}
PUT /api/v1/contacts/{}/care
PUT /api/v1/event-calendars/{}/members/{}
PUT /api/v1/life/journal/{}
PUT /api/v1/lists/{}/groups/{}
PUT /api/v1/lists/{}/links/order
PUT /api/v1/lists/{}/members/{}
PUT /api/v1/lists/{}/review
PUT /api/v1/lists/{}/sections/order
PUT /api/v1/lists/{}/status
PUT /api/v1/lists/{}/status-pad
PUT /api/v1/tasks/{}/waiting
PUT /api/wiki/style
PUT /api/workload/capacity/{}
""".strip().split("\n") if x.strip())


def found_routes():
    # 2.182.0 (#2718): via the Python parser (routes_ast.py, shared with tenant_coverage_test.py, which fails on its problems)
    return app_routes(ROOT)[0]


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
    sys.path.insert(0, N)
    import suites as _suites  # 2.321 (#1368): the suite list (suites.txt + marker files)
    run_all = " " + " ".join(f or "" for _, _, f in _suites.rows(N)) + " "
    # a marker line: "freelancer-matrix: area, area, ..." (a comment in the suite, next to the calls of these areas)
    marked = {}
    for name, t in tests.items():
        for line in re.findall(r"freelancer-matrix:([\w ,-]+)", t):
            for k in re.sub(r"\S+-matrix\s*$", "", line).split(","):  # 2.421.0 (#2936): "... own  tenant-matrix: org" names the area own
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
                      f"area {k}: the suite {name} with its marker does not run (tests/suites.txt / kalmido-suite marker)")
        check(k in ROUTES.values(), f"area {k}: no route uses it (stale)")

    # ---- 3. 2.421.0 A (#2936): every write route of a matrix area is called by a suite of its area (WRITE_UNPROVEN = the old rest)
    runs = {name for name in tests if re.search(r"\s" + re.escape(name) + r"\b", run_all)}
    NOT_ON_TRAIN = {"POST /api/imports/{}/undo"}  # #3104: p2363_2_runs calls it, in main, not on the live train yet: drop this once it is live
    texts = {}
    n_w = 0
    for r, k in sorted(ROUTES.items()):
        if r.split(" ", 1)[0] not in WRITES or KINDS.get(k, ("",))[0] != "matrix":
            check(r not in WRITE_UNPROVEN, f"WRITE_UNPROVEN names {r}, no write route of a matrix area: remove it")
            continue
        n_w += 1
        if k not in texts:
            texts[k] = [expand_consts(tests[n]) for n in sorted(marked.get(k, ())) if n in runs]
        proven = write_proven(r, texts[k])
        if r in WRITE_UNPROVEN:
            check(not proven, f"{r}: a suite of the area {k} calls it now: take it out of WRITE_UNPROVEN")
        else:
            check(proven or r in NOT_ON_TRAIN, f"{r}: no suite with the marker 'freelancer-matrix: {k}' calls it (method on the line, the path "
                          f"with its ids): call it there as the person without an organisation")
    for r in sorted(WRITE_UNPROVEN - set(ROUTES)):
        check(False, f"WRITE_UNPROVEN names {r}, which is no route of ROUTES: remove it")

    # 2.449.0 (#3800) self-test of the rule: a method on the line above counts only for an open call without a path of its own
    check(not write_proven("PATCH /api/me", ['A.patch(B + "/api/settings")\nA.get(B + "/api/me")']),
          "write_proven: a method on a line above with its own path must not count")
    check(write_proven("PATCH /api/me", ['A.patch(\n    B + "/api/me", json={})']),
          "write_proven: an open multi-line call must count")

    n_m = sum(1 for k in ROUTES.values() if KINDS.get(k, ("",))[0] == "matrix")
    print(f"freelancer_coverage: {oks[0]} ok, {len(fails)} failed -- {len(found)} routes, {n_m} checked without an organisation, "
          f"{len(found) - n_m} not relevant (with reason); {n_w} write routes, {n_w - len(WRITE_UNPROVEN)} called by a suite of "
          f"their area, {len(WRITE_UNPROVEN)} old ones without (WRITE_UNPROVEN, may only shrink)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
