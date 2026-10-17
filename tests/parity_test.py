#!/usr/bin/env python3
"""2.15.0 (#479) parity: what people can do in the app, agents can do through the API and the MCP server.
No container needed. Reads the server (app.py + kalmido/) and mcp/kalmido_mcp.py:
 1. every route the web client has (/api/..., not /api/v1) is either mapped to the REST API route(s) that do the same
    (APP_TO_API) or listed with a reason in APP_ONLY (sign-in, credentials, admin, devices, people's side of approvals ...)
 2. every mapped REST route exists
 3. every REST route is reached by at least one MCP tool (each tool is run against a recording fake API with arguments
    made from its input schema, plus the variants in TOOL_VARIANTS) or listed with a reason in API_ONLY
 4. nothing in the tables is stale (a mapped / listed route that no longer exists, a variant of an unknown tool)
A new app feature without an API route, or a new API route without an MCP tool, fails here until it gets one (or a
documented exception). usage: python3 tests/parity_test.py"""
import glob
import importlib.util
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


# 2.20.0 (#646): the server is app.py + the package kalmido/ (one text, the routes are found the same way)
src = "\n".join(open(p, encoding="utf-8").read() for p in [os.path.join(ROOT, "app.py")]
                + sorted(glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)))
routes = re.findall(r'^@app\.(get|post|put|patch|delete)\("(/api/[^"]*)"', src, re.M)
APP = {f"{m.upper()} {norm(p)}" for m, p in routes if not p.startswith("/api/v1/")}
API = {f"{m.upper()} {norm(p)[len('/api/v1'):]}" for m, p in routes if p.startswith("/api/v1/")}

# ---- 1. the web client's routes -> the REST API
APP_TO_API = {
    "GET /api/state": ["GET /lists", "GET /tasks", "GET /habits", "GET /filters", "GET /me"],
    "GET /api/me/storage": ["GET /me/storage"],  # 2.24.0 (#910)
    "GET /api/tasks": ["GET /tasks", "GET /search", "GET /trash"],
    "GET /api/search/messages": ["GET /search"],  # 2.33.0 (#1080): ?scope=messages
    "GET /api/tasks/{}": ["GET /tasks/{}"],
    "POST /api/tasks": ["POST /tasks", "POST /tasks/{}/subtasks"],
    "PATCH /api/tasks/{}": ["PATCH /tasks/{}"],
    "DELETE /api/tasks/{}": ["DELETE /tasks/{}"],
    "POST /api/tasks/{}/complete": ["POST /tasks/{}/complete"],
    "POST /api/tasks/{}/reopen": ["POST /tasks/{}/reopen"],
    "POST /api/tasks/{}/restore": ["POST /tasks/{}/restore"],
    "POST /api/tasks/{}/skip": ["POST /tasks/{}/skip"],
    "POST /api/tasks/{}/take": ["POST /tasks/{}/take"],
    "PUT /api/tasks/{}/waiting": ["PUT /tasks/{}/waiting"],
    "DELETE /api/tasks/{}/waiting": ["DELETE /tasks/{}/waiting"],
    "POST /api/tasks/{}/attachments": ["POST /tasks/{}/attachments"],
    "POST /api/tasks/{}/comments": ["POST /tasks/{}/comments"],
    "GET /api/tasks/{}/timeline": ["GET /tasks/{}/comments"],
    "GET /api/tasks/{}/deps": ["GET /tasks/{}/dependencies"],
    "GET /api/tasks/{}/milestone": ["GET /tasks/{}/milestone"],  # 2.18.0 (#430)
    "GET /api/lists/{}/velocity": ["GET /lists/{}/velocity"],  # 2.60.0 (#1511)
    "POST /api/tasks/reorder": ["POST /tasks/{}/move"],
    "POST /api/tasks/batch": ["POST /tasks/batch"],
    "POST /api/tasks/purge-done": ["POST /tasks/batch"],
    "DELETE /api/trash": ["DELETE /trash"],
    "GET /api/attachments/{}": ["GET /attachments/{}"],
    "DELETE /api/attachments/{}": ["DELETE /attachments/{}"],
    "PATCH /api/comments/{}": ["PATCH /comments/{}"],
    "DELETE /api/comments/{}": ["DELETE /comments/{}"],
    "POST /api/comments/{}/reactions": ["POST /comments/{}/reactions", "DELETE /comments/{}/reactions/{}"],
    "POST /api/deps": ["POST /tasks/{}/dependencies"],
    "DELETE /api/deps/{}/{}": ["DELETE /tasks/{}/dependencies/{}"],
    "POST /api/lists": ["POST /lists"],
    "PATCH /api/lists/{}": ["PATCH /lists/{}"],
    "DELETE /api/lists/{}": ["DELETE /lists/{}"],
    "POST /api/lists/{}/checklist": ["POST /tasks/batch"],
    "POST /api/lists/{}/shift": ["POST /lists/{}/shift"],
    "PUT /api/lists/{}/members": ["PUT /lists/{}/members/{}"],
    "DELETE /api/lists/{}/members/{}": ["DELETE /lists/{}/members/{}"],
    "GET /api/lists/{}/groups": ["GET /lists/{}/groups"],
    "PUT /api/lists/{}/groups/{}": ["PUT /lists/{}/groups/{}"],
    "DELETE /api/lists/{}/groups/{}": ["DELETE /lists/{}/groups/{}"],
    "GET /api/groups": ["GET /groups"],
    "POST /api/lists/{}/owner": ["POST /lists/{}/owner"],
    "PUT /api/lists/{}/bell": ["PATCH /me/notifications"],
    "POST /api/lists/{}/fields": ["POST /lists/{}/fields"],
    "PATCH /api/fields/{}": ["PATCH /fields/{}"],
    "DELETE /api/fields/{}": ["DELETE /fields/{}"],
    "POST /api/lists/{}/tags": ["POST /lists/{}/tags"],
    "PATCH /api/list-tags/{}": ["PATCH /lists/{}/tags/{}"],
    "DELETE /api/list-tags/{}": ["DELETE /lists/{}/tags/{}"],
    "POST /api/sections": ["POST /lists/{}/sections"],
    "PATCH /api/sections/{}": ["PATCH /sections/{}"],
    "DELETE /api/sections/{}": ["DELETE /sections/{}"],
    "POST /api/lists/{}/sections/order": ["PUT /lists/{}/sections/order"],
    "GET /api/lists/{}/overview": ["GET /lists/{}/overview"],
    "GET /api/lists/{}/kpis": ["GET /lists/{}/kpis"],  # 2.43.0 (#1328): key figures
    "GET /api/tasks/{}/related": ["GET /tasks/{}/related"],  # 2.59.0 (#1375): related tasks
    "POST /api/lists/{}/join": ["POST /lists/{}/join"],  # 2.46.0 (#1603): join a list visible to the organisation
    "PATCH /api/lists/{}/overview": ["PATCH /lists/{}/overview"],
    "POST /api/lists/{}/links": ["POST /lists/{}/links"],
    "PATCH /api/lists/{}/links/{}": ["PATCH /lists/{}/links/{}"],
    "DELETE /api/lists/{}/links/{}": ["DELETE /lists/{}/links/{}"],
    "PUT /api/lists/{}/links/order": ["PUT /lists/{}/links/order"],
    "POST /api/lists/{}/milestones": ["POST /lists/{}/milestones"],
    "PATCH /api/lists/{}/milestones/{}": ["PATCH /lists/{}/milestones/{}"],
    "DELETE /api/lists/{}/milestones/{}": ["DELETE /lists/{}/milestones/{}"],
    "POST /api/lists/{}/files": ["POST /lists/{}/files"],
    "GET /api/list-files/{}": ["GET /lists/{}/files/{}"],
    "DELETE /api/list-files/{}": ["DELETE /lists/{}/files/{}"],
    "GET /api/lists/{}/status": ["GET /lists/{}/overview"],
    "POST /api/lists/{}/status": ["PUT /lists/{}/status"],
    "GET /api/lists/{}/repos": ["GET /lists/{}/repos"],
    "GET /api/lists/{}/notify-template": ["GET /lists/{}/notify-template"],  # 2.33.0 (#927): agents read it, never change it
    "POST /api/filters": ["POST /filters"],
    "PATCH /api/filters/{}": ["PATCH /filters/{}"],
    "DELETE /api/filters/{}": ["DELETE /filters/{}"],
    "POST /api/folders/rename": ["POST /folders/rename"],
    "POST /api/folders/delete": ["POST /folders/delete"],
    "GET /api/templates": ["GET /templates"],
    "POST /api/templates": ["POST /templates"],
    "PATCH /api/templates/{}": ["PATCH /templates/{}"],
    "DELETE /api/templates/{}": ["DELETE /templates/{}"],
    "POST /api/templates/{}/apply": ["POST /templates/{}/apply"],
    "POST /api/habits": ["POST /habits"],
    "PATCH /api/habits/{}": ["PATCH /habits/{}"],
    "DELETE /api/habits/{}": ["DELETE /habits/{}"],
    "POST /api/habits/{}/log": ["POST /habits/{}/checkin"],
    "POST /api/time/start": ["POST /time/timer"],
    "POST /api/time/stop": ["DELETE /time/timer"],
    "GET /api/time/entries": ["GET /time/entries"],
    "POST /api/time/entries": ["POST /time/entries"],
    "PATCH /api/time/entries/{}": ["PATCH /time/entries/{}"],
    "DELETE /api/time/entries/{}": ["DELETE /time/entries/{}"],
    "GET /api/time/report": ["GET /time/entries"],
    "GET /api/time/export.csv": ["GET /time/entries"],
    "GET /api/time/gaps": ["GET /time/gaps"],  # 2.34.0 (#269)
    "GET /api/stale": ["GET /stale"],  # 2.34.0 (#266)
    "GET /api/news": ["GET /news"],
    "POST /api/news/read": ["POST /news/read"],
    "GET /api/roadmap": ["GET /roadmap"],
    "GET /api/dayplan": ["GET /dayplan"],
    "GET /api/dayplan/review": ["GET /dayplan/review"],
    "GET /api/briefing": ["GET /briefing"],  # 2.34.0 (#264)
    "GET /api/lists/{}/status-report": ["GET /lists/{}/status-report"],  # 2.34.0 (#265)
    "GET /api/export.json": ["GET /export"],
    "POST /api/import/{}": ["POST /import/{}"],
    "POST /api/import/ticktick": ["POST /import/{}"],
    "POST /api/imports/{}/undo": ["POST /imports/{}/undo"],
    "GET /api/me/app-passwords": ["GET /me/app-passwords"],
    "POST /api/me/app-passwords": ["POST /me/app-passwords"],
    "DELETE /api/me/app-passwords/{}": ["DELETE /me/app-passwords/{}"],
    "GET /api/chat-files/{}": ["GET /chat-attachments/{}"],
    "DELETE /api/chat-files/{}": ["DELETE /chat-attachments/{}"],
    "POST /api/agents/{}/chat/{}/reactions": ["POST /agents/{}/chat/{}/reactions"],
    "GET /api/agents": ["GET /agents"],
    # 2.17.0 (#442): notes
    "GET /api/lists/{}/notes": ["GET /lists/{}/notes"], "POST /api/lists/{}/notes": ["POST /lists/{}/notes"],
    "GET /api/notes": ["GET /notes"], "GET /api/notes/{}": ["GET /notes/{}"], "PATCH /api/notes/{}": ["PATCH /notes/{}"],
    "DELETE /api/notes/{}": ["DELETE /notes/{}"],
    # 2.17.0 (#419): team chat
    "GET /api/team": ["GET /team/rooms"], "POST /api/team/dm": ["POST /team/dm"],
    "GET /api/team/rooms/{}/messages": ["GET /team/rooms/{}/messages"], "POST /api/team/rooms/{}/messages": ["POST /team/rooms/{}/messages"],
    "POST /api/team/rooms/{}/read": ["POST /team/rooms/{}/read"], "PATCH /api/team/messages/{}": ["PATCH /team/messages/{}"],
    "DELETE /api/team/messages/{}": ["DELETE /team/messages/{}"], "POST /api/team/messages/{}/reactions": ["POST /team/messages/{}/reactions"],
    "POST /api/team/messages/{}/pin": ["POST /team/messages/{}/pin"],  # 2.62.0 (#1848)
    # 2.19.0 (#653): the module Family
    "GET /api/family": ["GET /family"], "POST /api/family/occasions": ["POST /family/occasions"],
    "GET /api/family/deadline-types": ["GET /family/deadline-types"], "POST /api/family/deadlines": ["POST /family/deadlines"],
    "POST /api/tasks/{}/to-shopping": ["POST /tasks/{}/to-shopping"], "POST /api/lists/{}/shop-areas": ["POST /lists/{}/shop-areas"],
    "GET /api/family/packing": ["GET /family/packing"], "POST /api/family/packing": ["POST /family/packing"],
    "POST /api/me/purpose": ["POST /me/purpose"], "GET /api/family/kids": ["GET /family/kids"],
    "POST /api/family/kids/{}/stars": ["POST /family/kids/{}/stars"], "POST /api/family/kids/{}/rewards": ["POST /family/kids/{}/rewards"],
    "PATCH /api/family/rewards/{}": ["PATCH /family/rewards/{}"], "DELETE /api/family/rewards/{}": ["DELETE /family/rewards/{}"],
    "POST /api/family/rewards/{}/request": ["POST /family/rewards/{}/request"], "POST /api/family/rewards/{}/decide": ["POST /family/rewards/{}/decide"],
    # 2.21.0 (#659): events
    "GET /api/evcals": ["GET /event-calendars"], "POST /api/evcals": ["POST /event-calendars"], "PATCH /api/evcals/{}": ["PATCH /event-calendars/{}"],
    "DELETE /api/evcals/{}": ["DELETE /event-calendars/{}"], "PUT /api/evcals/{}/members": ["PUT /event-calendars/{}/members/{}"],
    "DELETE /api/evcals/{}/members/{}": ["DELETE /event-calendars/{}/members/{}"], "POST /api/evcals/{}/import": ["POST /event-calendars/{}/import"],
    "GET /api/evcals/{}/export.ics": ["GET /event-calendars/{}/export"], "GET /api/events": ["GET /events"], "POST /api/events": ["POST /events"],
    "GET /api/events/{}": ["GET /events/{}"], "PATCH /api/events/{}": ["PATCH /events/{}"], "DELETE /api/events/{}": ["DELETE /events/{}"],
    "POST /api/events/{}/restore": ["POST /events/{}/restore"], "POST /api/events/{}/rsvp": ["POST /events/{}/rsvp"],
    "POST /api/events/{}/prep-task": ["POST /events/{}/prep-task"], "GET /api/tasks/{}/events": ["GET /tasks/{}/events"],
    # 2.21.0 (#658): contacts
    "GET /api/books": ["GET /address-books"], "POST /api/books": ["POST /address-books"], "PATCH /api/books/{}": ["PATCH /address-books/{}"],
    "DELETE /api/books/{}": ["DELETE /address-books/{}"], "PUT /api/books/{}/members": ["PUT /address-books/{}/members/{}"],
    "DELETE /api/books/{}/members/{}": ["DELETE /address-books/{}/members/{}"], "POST /api/books/{}/import": ["POST /address-books/{}/import"],
    "GET /api/books/{}/export.vcf": ["GET /address-books/{}/export"], "GET /api/contacts": ["GET /contacts"], "POST /api/contacts": ["POST /contacts"],
    "GET /api/contacts/{}": ["GET /contacts/{}"], "PATCH /api/contacts/{}": ["PATCH /contacts/{}"], "DELETE /api/contacts/{}": ["DELETE /contacts/{}"],
    "POST /api/contacts/bulk": ["POST /contacts/bulk"],  # 2.46.1 (#1554)
    "POST /api/tasks/{}/contacts": ["POST /tasks/{}/contacts"], "DELETE /api/tasks/{}/contacts/{}": ["DELETE /tasks/{}/contacts/{}"],
    # 2.22.0 (#663): Home & life
    "GET /api/life": ["GET /life"], "GET /api/life/upkeep-presets": ["GET /life/upkeep-presets"], "POST /api/life/contracts": ["POST /life/contracts"],
    "POST /api/life/devices": ["POST /life/devices"], "POST /api/life/upkeep": ["POST /life/upkeep"], "POST /api/life/health": ["POST /life/health"],
    "POST /api/life/trips": ["POST /life/trips"], "GET /api/life/review": ["GET /life/review"], "PUT /api/life/journal/{}": ["PUT /life/journal/{}"],
    "PUT /api/contacts/{}/care": ["PUT /contacts/{}/care"], "POST /api/life/karakeep/sync": ["POST /life/karakeep/sync"],
    "POST /api/tasks/{}/typing": ["POST /tasks/{}/typing"],  # 2.22.0 (#693)
    # 2.23.0 (#463): clients, workload, approvals, forms
    "GET /api/clients": ["GET /clients"], "POST /api/clients": ["POST /clients"], "GET /api/clients/{}": ["GET /clients/{}"],
    "PATCH /api/clients/{}": ["PATCH /clients/{}"], "DELETE /api/clients/{}": ["DELETE /clients/{}"], "GET /api/workload": ["GET /workload"],
    "GET /api/team/absences": ["GET /absences"],  # 2.50.0 (#1195): "away" only
    "POST /api/clients/bulk": ["POST /clients/bulk"],  # 2.47.3 (#1733)
    "POST /api/tasks/{}/approval": ["POST /tasks/{}/approval"], "GET /api/lists/{}/forms": ["GET /lists/{}/forms"],
    "POST /api/tasks/{}/review": ["POST /tasks/{}/review"], "PUT /api/lists/{}/review": ["PUT /lists/{}/review"],  # 2.60.0 (#1512)
    "POST /api/lists/{}/forms": ["POST /lists/{}/forms"], "PATCH /api/forms/{}": ["PATCH /forms/{}"], "DELETE /api/forms/{}": ["DELETE /forms/{}"],
    # 2.48.0 (#1207): the file store -- list, read, add files / folders, new versions
    "GET /api/files": ["GET /files"], "GET /api/files/nodes/{}": ["GET /files/{}"], "GET /api/files/nodes/{}/content": ["GET /files/{}/content"],
    "POST /api/files/folders": ["POST /files"], "POST /api/files/upload": ["POST /files"], "POST /api/files/nodes/{}/versions": ["POST /files/{}/versions"],
    "GET /api/files/search": ["GET /files/search"],  # 2.61.0 (#1820): names + recognised text
    # 2.48.0 (#1111): documents (agents read / set the fields of documents shared with them)
    "GET /api/docs": ["GET /documents"], "GET /api/docs/{}": ["GET /documents/{}"], "PATCH /api/docs/{}": ["PATCH /documents/{}"],
    # 2.60.0 (#343): sprints -- agents read the sprints of a shared list and put tasks into one (or back to the backlog)
    "GET /api/lists/{}/sprints": ["GET /lists/{}/sprints"], "GET /api/sprints/{}": ["GET /sprints/{}"],
    "POST /api/lists/{}/sprints/assign": ["POST /lists/{}/sprints/assign"],
}
# app routes with no API counterpart on purpose (prefix match on "METHOD /api/path"; reason first)
APP_ONLY = [
    ("2.59.0 (#1375): the hint while a person types a new task's title and the client's on / off of the related tasks; agents "
     "use related_tasks and search_tasks with semantic", ("=POST /api/tasks/similar", "=GET /api/related/config")),
    ("2.60.0 (#343): planning sprints stays with the people of a list -- switching sprints on, planning, editing, starting, closing "
     "and removing a sprint; agents read sprints (list_sprints / get_sprint), put tasks into one (set_task_sprint) and hear "
     "sprint_started / sprint_closed", ("=PUT /api/lists/{}/sprint-settings", "=POST /api/lists/{}/sprints", "=PATCH /api/sprints/{}",
                                        "=DELETE /api/sprints/{}", "=POST /api/sprints/{}/start", "=POST /api/sprints/{}/close")),
    ("2.62.0 (#1848): a person pins a message of their own agent chat in the app; the agent pins with POST /agent/chats/{}/messages/{}/pin "
     "(MCP pin_chat_message)", ("=POST /api/agents/{}/chat/{}/pin",)),
    ("2.48.0 (#1207): managing the file store stays with people -- rename, move, trash, restore a version, shares, organisation-wide "
     "access, links to task / project files, the move targets; agents list, read and write files where they may edit",
     ("=PATCH /api/files/nodes/{}", "=DELETE /api/files/nodes/{}", "=POST /api/files/nodes/{}/restore", "=POST /api/files/nodes/{}/versions/{}/restore",
      "=GET /api/files/nodes/{}/share-targets", "=POST /api/files/nodes/{}/shares", "* /api/files/shares/", "=POST /api/files/links",
      "=GET /api/files/folders")),
    ("2.48.0 (#1111): documents -- a person's own steps (upload by hand / share sheet, review and accept, recognise again, the "
     "preview image, a task for the due date, the workspace's levels / rules / labels / mail address); agents read and set fields "
     "with /documents and add files with /files", ("=POST /api/docs", "=POST /api/docs/{}/accept", "=POST /api/docs/{}/review",
                                                   "=POST /api/docs/{}/redo", "=GET /api/docs/{}/thumb", "=GET /api/docs/{}/file",
                                                   "* /api/docs/{}/task", "* /api/docs/settings", "* /api/docs/rules", "* /api/docs/labels/",
                                                   "* /api/docs/mail")),
    # 2.51.0 (#1348, #1350): agents get drafts only, through /office (v1 + MCP); the rest of the office stays with people
    ("2.36.1 (#1021) / 2.51.0 (#1348): Office & finance -- people finalise, number, send, delete, book payments and keep master data and "
     "settings; agents (two switches) read and draft through /api/v1/office (quotation / invoice / reminder drafts, payment suggestions); "
     "the agent's office switch and the decision on suggested payments are the people's side",
     ("* /api/office/",)),
    ("2.49.0 (#1199, #1201): knowledge pages, stage 1 -- no agent access yet (shares of pages / folders for organisation agents with "
     "scopes wiki:read / wiki:write come as their own step); the outline parser only serves the mind map import of the web app",
     ("* /api/wiki", "=POST /api/outline/parse")),
    ("2.50.0 (#1195, #1194): entering absences (the kind is health data), the public holiday state, the assign check and the "
     "disposition (booking crew and equipment): people only; agents read GET /absences (\"away\" only)",
     ("POST /api/team/absences", "PATCH /api/team/absences/", "DELETE /api/team/absences/", "PUT /api/team/absences/",
      "=GET /api/team/absences/check", "* /api/team/dispo", "=GET /api/team/bookings/mine")),
    ("2.27.0 (#999): the web panel says a person edits a task (tidy-up waits); agents never edit in a panel", ("=POST /api/tasks/{}/editing",)),
    ("2.42.0 (#1376): the web app's live updates (only the tasks changed since its state); agents follow their events and GET /tasks",
     ("=GET /api/state/delta",)),
    ("2.34.0 (#368): the briefing field reads a PDF the person picks (nothing stored); agents read stored files with GET /attachments/{id}/text",
     ("=POST /api/pdf-text",)),
    ("sign-in, sessions, two-factor, passkeys, OIDC: a person in a browser", ("* /api/auth/", "* /api/me/2fa", "* /api/me/passkeys", "=PATCH /api/me", "=GET /api/me")),
    ("credentials and keys of the account: tokens, webhooks, upload token, avatar, phone shortcut", (
        "* /api/me/tokens", "* /api/me/webhooks", "POST /api/me/drop-token", "* /api/me/avatar", "GET /api/me/share/")),
    ("administration: never through a token (agents are never admins); admins read users / status with admin-read", (
        "* /api/admin/", "* /api/users", "GET /api/version", "GET /api/about", "GET /api/health")),
    ("agents are managed by people (admins / owners), not by tokens", ("* /api/my/agents",
                                                                       "PATCH /api/agents/{}/color")),  # 2.47.1 (#1721)
    ("approvals and proposals come only from people (the agent's side: /agent/jobs, POST /agent/jobs/{id}/proposal)", (
        "* /api/agents/jobs", "* /api/proposals", "POST /api/comments/{}/apply", "POST /api/comments/{}/decide")),
    ("people's side of the agent chat (2.39.0: also editing one's own message), waking and sharing with agents (the agent uses /agent/*)", (
        "=GET /api/agents/{}/chat", "=POST /api/agents/{}/chat", "=PATCH /api/agents/{}/chat/{}", "POST /api/agents/{}/wake", "POST /api/tasks/{}/wake", "* /api/agents/{}/share", "PUT /api/lists/{}/agent",
        "* /api/agents/{}/autoshare", "GET /api/agents/usage")),
    ("devices and pushes of a person", ("* /api/push/", "POST /api/ntfy/test")),
    ("2.17.0 (#443): a person's e-mail addresses for new tasks and the summary by mail (secrets of the account)", ("* /api/me/mail",)),
    ("public links: sharing outside the instance, people only", ("* /api/lists/{}/public-link",
                                                                  "* /api/lists/{}/signoffs")),  # 2.50.0 (#1200): acceptance links of a list
    ("2.33.0 (#927): notification templates are set by the owner in the app; agents only read a list's template",
     ("PUT /api/lists/{}/notify-template", "* /api/folders/notify-template", "POST /api/notify-templates/asked")),
    # 2.53.0 (#1424): agents get no pushes, and they never mark people urgent (only people do, in the app)
    ("2.53.0 (#1424): the bell of one task (as the list / muted / urgent) is a person's own push setting, set in the app",
     ("* /api/tasks/{}/bell",)),
    ("repositories: their secrets are entered by people; the API reads them (GET /lists/{id}/repos)", (
        "POST /api/lists/{}/repos", "* /api/repos/", "POST /api/hooks/git/", "POST /api/tasks/{}/git-undo",
        "* /api/folders/repos", "PUT /api/lists/{}/folder-repo")),  # 2.33.0 (#934): folder repositories, read through /lists/{id}/repos
    ("2.18.0: the error-report webhook of a list: its secret URL is shown once to people (owner / list admins); the inbound hook "
     "is called by the error service, not by a client", ("* /api/lists/{}/error-hook", "POST /api/hooks/issues/")),
    ("2.60.0 (#1514): environments (Staging, Live) are created, renamed and removed by people in the app, their deploy-webhook token is "
     "shown once to people; agents read them (list_environments) and record deployments (set_deployment)",
     ("* /api/lists/{}/envs", "* /api/envs/", "POST /api/hooks/deploy/")),
    ("external calendar subscriptions and the calendar feed link: personal settings", ("* /api/calendars", "* /api/ical")),
    ("2.19.0: address books (CardDAV) for birthdays: their passwords are entered by people, like calendar subscriptions", ("* /api/family/contacts",)),
    ("2.49.0 (#1551): the parents' PIN of a child account: a secret people type in the app (the parent sets it, the child opens "
     "its settings with it), never an agent", ("* /api/family/kids/{}/pin", "* /api/me/pin/")),
    ("the app's personal settings, onboarding and sample data", ("PATCH /api/settings", "POST /api/briefing/read", "POST /api/onboarding", "* /api/sample")),
    ("2.32.0 (#1063, #983): how a person arranges their views and the project page: people only, never agents", ("* /api/lists/{}/layout",)),
    ("the focus timer is a personal on-screen timer; time is tracked with /time/timer", ("* /api/pomo/",)),
    ("views computed for the screen (the data is in /tasks, /tasks/{id}/dependencies, /time/entries)", (
        "GET /api/stats", "GET /api/occurrences", "GET /api/deps", "GET /api/imports")),
    ("app conveniences: undo of a completion (= reopen), read markers, News removal, sidebar order, folder of a person's "
     "tag (personal tags change with the task's tags), list owner lookup, icon pictures", (
        "POST /api/tasks/{}/undo", "POST /api/tasks/{}/seen", "POST /api/news/dismiss", "POST /api/lists/reorder", "* /api/tags/",
        "POST /api/lists/{}/tags/promote", "GET /api/lists/{}/owner", "* /api/lists/{}/icon", "GET /api/list-icon/", "GET /api/avatar/",
        "GET /api/group-avatar/",  # 2.46.0 (#1605): group pictures, shown in the app
        "GET /api/admin/lists/orphaned", "GET /api/lists/{}/owner")),
    ("folder shares with groups: people only (sharing of a list with a group: /lists/{id}/groups)", ("* /api/folders/groups",)),
    ("2.22.0 (#740): sharing a whole folder with a person (and its future lists): people only; single lists: /lists/{id}/members",
     ("* /api/folders/people",)),
    ("2.41.0 (#1420): a folder's agents, the public links of its lists together and handing all its lists over: people only "
     "(per list: /lists/{id}/members, /lists/{id}/public-link, /lists/{id}/owner)",
     ("* /api/folders/agents", "* /api/folders/public-links", "POST /api/folders/owner")),
    ("2.22.0 (#663): the Karakeep connection: its API key is entered by the person; the sync is in the API",
     ("=GET /api/life/karakeep", "=PUT /api/life/karakeep", "=DELETE /api/life/karakeep", "GET /api/life/karakeep/lists")),
    ("2.23.0 (#463): a person's hours per week (their own setting / an admin's) and a QR code image for the screen",
     ("PUT /api/workload/capacity/", "POST /api/qr")),
    ("2.28.0 (#935): a person's organisations (workspaces) and their admins' member management: people only (agents 403)",
     ("* /api/orgs",)),
    ("2.42.0 (#828, #909): end-to-end encryption happens in a person's browser (keys, encrypted note / files, the switch of an encrypted DM); "
     "agents see only placeholders (encrypted_note, encrypted files) and never take part in DMs", (
        "* /api/e2e/", "* /api/tasks/{}/enc-note", "=POST /api/tasks/{}/enc-attachments", "=POST /api/team/rooms/{}/e2e")),
    # 2.48.0 (#1642): a task's note locked with its owner's password, encrypted in the browser; agents see note_locked only
    ("2.48.0 (#1642): locking a task's note with one's own password happens in that person's browser (end-to-end); agents see only "
     "note_locked and get 409 when they write the notes", ("* /api/tasks/{}/note-lock",)),
    ("2.37.0 (#1159): a person saves a chat message as a task with a click; agents only offer it (send_chat offer_save), never save",
     ("=POST /api/chat-save",)),
    ("2.28.0 (#1005): a person answers an agent's question with a button: in the API as POST /agents/{id}/chat/{mid}/choice (a person's token); agents never answer",
     ("POST /api/agents/{}/chat/{}/choice",)),
    ("2.41.0 (#1383): a person answers an agent's comment with a button: in the API as POST /comments/{id}/choice (a person's token); agents "
     "never answer; the state comes with GET /tasks/{id}/comments", ("POST /api/comments/{}/choice", "GET /api/comments/{}/choice")),
    ("2.41.0 (#1437): the app's progress of a vCard import in the background; the REST import answers when it is done",
     ("GET /api/books/imports/{}",)),
    ("2.52.0 (#1438): handing an address book over to its organisation (and back), the members' role: organisation admins "
     "only, and agents are never organisation admins; agents see an organisation's address book only through a share",
     ("* /api/books/{}/org",)),
    ("2.29.0 (#1030 / #929): folder settings are per person (their own folders, like the sidebar order); people only, the "
     "lists' own values stay in /lists/{id}", ("* /api/folders/props", "POST /api/lists/{}/folder-reset")),
    ("2.39.1 (#1188): the app asks before a moved list takes its folder's workspace / agent; the API sends folder_adopt "
     "with PATCH /lists/{id} itself", ("GET /api/lists/{}/folder-preview",)),
    ("2.40.0 (#1192): the app counts the tasks with a value of a field for its delete confirmation; the API answers the "
     "count with DELETE /fields/{id} itself (values)", ("GET /api/fields/{}/count",)),
    ("2.40.0 (#1344 / #1361): the own order of My tasks and the favourite star are personal app settings of a person; "
     "agents never set them; 2.46.1: the favourite suggestion asks the person", ("PUT /api/tasks/mine-order", "* /api/lists/{}/favorite",
                                                                                   "POST /api/favorites/suggestion")),
    ("2.41.0 (#1365 / #1205): \"Show in My tasks\" per list and the person's Waiting-on suggestions are personal app "
     "settings of a person; agents never set them (an agent writes the waiting text itself with PUT /tasks/{id}/waiting)",
     ("PUT /api/lists/{}/in-mine", "* /api/me/wait-suggestions")),
    ("2.29.0 (#1029): the permission mode switch in the chat header; in the API it is the agent's runtime (admins: "
     "PATCH /api/admin/agents/{id}, owners: PATCH /api/my/agents/{id}), the agent reads it in GET /agent",
     ("PUT /api/agents/{}/permission-mode",)),
    ("2.32.0 (#1081): an agent's steps are read only by the person they are for, in the app (the agent sends them with "
     "POST /agent/progress; no token reads them back)", ("GET /api/agents/jobs/{}/steps",)),
    ("2.34.0 (#272): people plan jobs for an agent in the app (for themselves; admins / owners manage them); the agent only "
     "reads its plans (GET /agent/schedules, MCP list_schedules) and gets the event scheduled_job",
     ("* /api/agents/{}/schedules", "* /api/agent-schedules/")),
    ("2.39.0 (#1168): people write the Playbook of a list / folder (versions, restore, applying an agent's proposal) and plan "
     "the scheduled checks of a list in the app; agents read it (GET /lists/{id}/playbook, MCP get_playbook, every event of the "
     "list) and only propose changes (POST /lists/{id}/playbook/proposals, MCP propose_playbook)",
     ("* /api/lists/{}/playbook", "* /api/folders/playbook", "* /api/lists/{}/checks", "* /api/list-checks/")),
    ("2.30.0 (#919): what people see about agents in their lists: the access log of a list (list menu > Agent access) and the "
     "lists an agent connects although their people differ; an agent's own token reads neither (GET /me shows its list_ids)",
     ("GET /api/lists/{}/agent-access", "GET /api/agents/{}/bridges")),
    # 2.43.0 (#1452, #1346, #1434): page layout, notepads and wiping a project's time are things people do in the web app
    ("2.43.0 (#1452): the default arrangement of a view for everyone (instance admins); layout only, nothing for an agent",
     ("=GET /api/layouts/std", "=PUT /api/layouts/std/{}")),
    ("2.55.0 (#1069, #1068): a person's saved arrangements of a view and templates sent between people; agents get 403 (their "
     "own way is proposing an arrangement, #1066)",
     ("* /api/layouts/saved", "* /api/layouts/offers")),
    ("2.43.0 (#1346): project page colours and notepads; not shared with agents in 2.43 (open decision)",
     ("=PUT /api/lists/{}/page-style", "=POST /api/lists/{}/notepads", "=PATCH /api/notepads/{}", "=DELETE /api/notepads/{}")),
    ("2.43.0 (#1434): delete all times of a project (typed confirmation, restore); agents get 403 by design",
     ("=GET /api/lists/{}/time/delete-all", "=POST /api/lists/{}/time/delete-all", "=POST /api/lists/{}/time/restore")),
    # 2.44.0 (#1517): the setup script trades the one-time code for the token and signs a computer off with its own token
    ("2.44.0 (#1517): one-command agent setup on a computer (setup script, no session); not an agent tool",
     ("=POST /api/agent-setup/redeem", "=POST /api/agent-setup/remove")),
    # 2.49.0 (#1106): finding people by e-mail is for people only -- agents must not look accounts up
    ("2.49.0 (#1106): find people by e-mail, address book check, connection requests, blocks; not for agents", ("* /api/disc",)),
    ("2.48.0 (#1152): the Paperless-ngx connection of a workspace (self-hosted only): its API token is entered by an admin / the "
     "person, the import runs in the background; agents read the imported documents through the documents API",
     ("* /api/paperless",)),
    ("2.48.0 (#1356): a receipt's project / category is set and agents' suggestions are accepted / rejected / reopened by people "
     "only; agents suggest with POST /documents/{id}/receipt-suggestion",
     ("* /api/docs/{}/receipt", "* /api/receipt-suggestions/")),
    # 2.55.0 (#1455): the newsletter connection holds access data of an outside service and decides who gets mail: people only
    ("2.55.0 (#1455): the newsletter connection, segments, sync and the consent of contacts are set by people (admins / the "
     "person); agents read the consent with the contact (field newsletter), no new agent rights", ("* /api/newsletter",)),
    # 2.59.0 (#1735): the search of the client dialog; the API sets contact_id with PATCH /clients/{id} and finds contacts with GET /contacts
    ("2.59.0 (#1735): the address book search of the client dialog (contacts a person may link to a client's contact persons); "
     "the API links with PATCH /clients/{id} contacts[].contact_id and searches with GET /contacts", ("=GET /api/clients/{}/book-contacts",)),
]


def app_only(r):
    m, p = r.split(" ", 1)
    for _, pats in APP_ONLY:
        for pat in pats:
            if pat.startswith("="):  # exact: "=GET /api/me"
                if pat[1:] == r:
                    return True
                continue
            pm, pp = pat.split(" ", 1)
            if (pm in ("*", m)) and (p == pp or p.startswith(pp.rstrip("/") + "/") or (pp.endswith("/") and p.startswith(pp))
                                     or (pm == "*" and p.startswith(pp))):
                return True
    return False


missing = sorted(r for r in APP if r not in APP_TO_API and not app_only(r))
check(not missing, f"app routes without an API route or a documented exception: {missing}")
stale = sorted(r for r in APP_TO_API if r not in APP)
check(not stale, f"APP_TO_API lists routes the app no longer has: {stale}")
both = sorted(r for r in APP_TO_API if app_only(r))
check(not both, f"routes both mapped and excepted: {both}")
# ---- 2. the mapped API routes exist
gone = sorted({x for v in APP_TO_API.values() for x in v if x not in API})
check(not gone, f"mapped API routes that do not exist: {gone}")
for pats in (x[1] for x in APP_ONLY):
    for pat in pats:
        if pat.startswith("="):
            check(pat[1:] in APP, f"APP_ONLY entry matches nothing: {pat}")
            continue
        pm, pp = pat.split(" ", 1)
        check(any((pm in ("*", r.split(" ", 1)[0])) and r.split(" ", 1)[1].startswith(pp) for r in APP), f"APP_ONLY entry matches nothing: {pat}")

# ---- 3. every API route has an MCP tool
spec = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(ROOT, "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)
CALLS = {}


PATS = sorted(((r, re.compile("^" + re.escape(r).replace(re.escape("{}"), "[^/]+") + "$")) for r in API), key=lambda x: x[0].count("{}"))


def route_of(method, path):
    """The API route a concrete call hits (literal segments before placeholders, as Flask matches them)."""
    return next((r for r, rx in PATS if rx.match(f"{method} {path}")), f"{method} {path}")


class Rec:
    def call(self, method, path, query=None, body=None, timeout=None, multipart=None, binary_cap=None):
        CALLS.setdefault(self.tool, set()).add(route_of(method, path))
        if binary_cap:
            return {"bytes": b"x", "mime": "text/plain", "name": "x"}
        return {"data": [], "ok": True}


def sample(schema):
    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t
    if "enum" in schema:
        return schema["enum"][0]
    return {"integer": 1, "number": 1, "string": "x", "boolean": True, "array": [], "object": {}}.get(t, 1)


TOOL_VARIANTS = {  # extra arguments that reach other routes of the same tool
    "list_files": [{"folder_id": 1}], "read_file": [{"as": "base64"}], "write_file": [{"file_id": 1}],  # 2.48.0 (#1207)
    "get_attachment": [{"source": "chat"}, {"source": "project", "list_id": 1}],
    "react": [{"remove": True}],
    "upload_attachment": [],
}
rec = Rec()
for name, _, schema, fn in mcp.TOOLS:
    props = schema.get("properties", {})
    base = {k: sample(props[k]) for k in schema.get("required", [])}
    if name == "upload_attachment":
        base["files"] = [{"name": "a.txt", "base64": "eA=="}]
    if name == "upload_project_file":
        base["base64"] = "eA=="
    if name == "send_chat":
        base["body"] = "x"
    for extra in [{}] + TOOL_VARIANTS.get(name, []):
        rec.tool = name
        try:
            fn(rec, {**base, **extra})
        except mcp.ApiError as e:
            check(False, f"tool {name} {extra}: {e.message}")
reached = {c for s in CALLS.values() for c in s}
API_ONLY = {  # REST routes on purpose without an MCP tool (reason)
    "GET /office/docs/{}/pdf": "2.51.0 (#1348): the PDF preview of a draft is binary; the chat card (notify) links it for the person",
    "GET /openapi.json": "the API description itself",
    "GET /lists/{}/notify-template": "2.33.0 (#927): the owner's notification ceiling of a list; agents get no pushes, it is read by scripts",
    "POST /import/{}": "imports of other apps' files: people upload them (multipart) in the app or with the REST API",
    "POST /imports/{}/undo": "belongs to the import",
    "POST /lists/{}/owner": "transferring a list: never agents (403)",
    "POST /lists/{}/join": "2.46.0 (#1603): joining a list seen through the organisation: people only (an agent never sees a list that way, 404)",
    "GET /admin/users": "admin-read: never for agents",
    "GET /admin/status": "admin-read: never for agents",
    "PUT /admin/announcement": "2.24.0: the server's notice: admins and operator scripts (account + admin-read, never agents)",
    "GET /admin/agents/{}/audit": "admin-read: never for agents",
    "GET /me/app-passwords": "account: never for agents",
    "POST /me/app-passwords": "account: never for agents",
    "DELETE /me/app-passwords/{}": "account: never for agents",
    "PATCH /me/notifications": "account: never for agents",
    "POST /agents/{}/chat/{}/reactions": "a person's reaction in an agent chat (the agent: react_to_chat)",
    "POST /agents/{}/chat/{}/choice": "2.28.0 (#1005): a person's answer to an agent's buttons; agents never answer (the agent asks with send_chat choices)",
    "POST /comments/{}/choice": "2.41.0 (#1383): a person's answer to an agent's comment buttons; agents never answer (the agent asks with add_comment choices)",
    "GET /lists/{}/links": "in get_project_overview",
    "GET /lists/{}/milestones": "in get_project_overview",
    "GET /lists/{}/error-hook": "2.18.0: the error-report webhook carries a secret URL; agents are refused (403), people manage it",
    "PATCH /lists/{}/error-hook": "2.18.0: the error-report webhook carries a secret URL; agents are refused (403), people manage it",
    "POST /team/dm": "direct messages are between people; agents cannot open them (403), people talk to an agent in its own chat",
    "POST /me/purpose": "2.19.0: the modules of the account (scope account): never for agents",
}
none = sorted(r for r in API if r not in reached and r not in API_ONLY)
check(not none, f"API routes without an MCP tool or a documented exception: {none}")
stale = sorted(r for r in API_ONLY if r not in API)
check(not stale, f"API_ONLY lists routes that no longer exist: {stale}")
both = sorted(r for r in API_ONLY if r in reached)
check(not both, f"API_ONLY routes that do have a tool now (drop them from the list): {both}")
unknown = sorted({c for c in reached if c not in API})
check(not unknown, f"MCP tools call routes the API does not have: {unknown}")
check(set(TOOL_VARIANTS) <= {t[0] for t in mcp.TOOLS}, "TOOL_VARIANTS: known tools only")
# every tool has a scope rule that matches the scope of its route(s) in the OpenAPI document is checked against the live
# server in p2150_api_test.py; here: every tool name in TOOL_SCOPES exists
check(set(mcp.TOOL_SCOPE) <= {t[0] for t in mcp.TOOLS}, f"TOOL_SCOPES: unknown tools {sorted(set(mcp.TOOL_SCOPE) - {t[0] for t in mcp.TOOLS})}")
print(f"app routes: {len(APP)} ({len(APP_TO_API)} mapped), API routes: {len(API)} ({len(API) - len(API_ONLY)} with MCP tools), MCP tools: {len(mcp.TOOLS)}")
print(f"parity: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
