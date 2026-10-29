#!/usr/bin/env python3
"""2.235.0 A (#2891 #2900): every write route of the REST API an agent token reaches has a decided class of the control gate
(kalmido/agents/control.py ctl_class): meta (the agent's own channel, always allowed), routine (small reversible steps),
change (everything else) or one_way (deleting: always an approval card). A new route fails here until somebody decides its
class -- either by a line in CTL_ROUTES or by naming it below with the class it falls into by default (change; DELETE =
one_way). Nothing in ROUTES may be stale. No container needed: reads kalmido/ like tests/tenant_coverage_test.py.
freelancer-matrix: agents
usage: python3 tests/p2235_a_control_routes_test.py"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes_ast import app_routes  # noqa: E402
from kt import check, done  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = open(os.path.join(ROOT, "kalmido", "agents", "control.py"), encoding="utf-8").read()
NS = {"re": re}
for node in ast.parse(SRC).body:  # the table and the classifier, as the server has them (no app start)
    names = {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)} | ({node.name} if isinstance(node, ast.FunctionDef) else set())
    if names & {"CTL_WRITE", "CTL_PLAN_KEYS", "CTL_PLAN_EXTRA", "CTL_ROUTES", "ctl_class"}:
        exec(ast.get_source_segment(SRC, node), NS)  # noqa: S102  our own source file
ctl_class = NS["ctl_class"]

# route -> its class with an empty body (decided 2.235.0; PATCH /tasks/{} and POST /tasks/batch depend on the body, below)
ROUTES = {
    # ---- meta
    "DELETE /api/v1/agent/quota": "meta", "PATCH /api/v1/agent/jobs/{}": "meta", "POST /api/v1/agent/aborted": "meta",
    "POST /api/v1/agent/chats/{}": "meta", "POST /api/v1/agent/chats/{}/messages/{}/pin": "meta",
    "POST /api/v1/agent/chats/{}/messages/{}/reactions": "meta", "POST /api/v1/agent/chats/{}/messages/{}/withdraw": "meta",
    "POST /api/v1/agent/jobs": "meta", "POST /api/v1/agent/jobs/{}/proposal": "meta", "POST /api/v1/agent/progress": "meta",
    "POST /api/v1/agent/proposals": "meta", "POST /api/v1/agent/proposals/import": "meta",
    "POST /api/v1/agent/proposals/sheet-tasks": "meta", "POST /api/v1/agent/proposals/shoot": "meta",
    "POST /api/v1/agent/proposals/time": "meta", "POST /api/v1/agent/typing": "meta", "POST /api/v1/agent/usage": "meta",
    "POST /api/v1/agent/rules": "meta",  # 2.235.0 A2: C (#2903) its own standing rules, taken from a person's message
    "POST /api/v1/agents/{}/chat/{}/choice": "meta", "POST /api/v1/agents/{}/chat/{}/reactions": "meta",
    "POST /api/v1/comments/{}/withdraw": "meta", "POST /api/v1/documents/{}/receipt-suggestion": "meta",
    "POST /api/v1/layouts/proposals": "meta", "POST /api/v1/lists/{}/playbook/proposals": "meta",
    "POST /api/v1/lists/{}/rules/proposals": "meta", "POST /api/v1/news/read": "meta",
    "POST /api/v1/office/payment-suggestions": "meta", "POST /api/v1/tasks/{}/typing": "meta",
    "POST /api/v1/team/rooms/{}/read": "meta", "PUT /api/v1/agent/queue": "meta", "PUT /api/v1/agent/quota": "meta",
    "PUT /api/v1/agent/status": "meta",
    # ---- routine
    "DELETE /api/v1/comments/{}/reactions/{}": "routine", "POST /api/v1/comments/{}/choice": "routine",
    "POST /api/v1/comments/{}/reactions": "routine", "POST /api/v1/tasks": "routine", "POST /api/v1/tasks/{}/comments": "routine",
    "POST /api/v1/tasks/{}/complete": "routine", "POST /api/v1/tasks/{}/reopen": "routine",
    "POST /api/v1/tasks/{}/skip": "routine", "POST /api/v1/tasks/{}/subtasks": "routine",
    "POST /api/v1/team/messages/{}/reactions": "routine", "POST /api/v1/team/rooms/{}/messages": "routine",
    "POST /api/v1/videos/{}/comments": "routine",
    # ---- one_way
    "DELETE /api/v1/address-books/{}": "one_way", "DELETE /api/v1/address-books/{}/members/{}": "one_way",
    "DELETE /api/v1/attachments/{}": "one_way", "DELETE /api/v1/chat-attachments/{}": "one_way",
    "DELETE /api/v1/clients/{}": "one_way", "DELETE /api/v1/comments/{}": "one_way", "DELETE /api/v1/contacts/{}": "one_way",
    "DELETE /api/v1/event-calendars/{}": "one_way", "DELETE /api/v1/event-calendars/{}/members/{}": "one_way",
    "DELETE /api/v1/events/{}": "one_way", "DELETE /api/v1/family/rewards/{}": "one_way", "DELETE /api/v1/fields/{}": "one_way",
    "DELETE /api/v1/filters/{}": "one_way", "DELETE /api/v1/forms/{}": "one_way", "DELETE /api/v1/habits/{}": "one_way",
    "DELETE /api/v1/lists/{}": "one_way", "DELETE /api/v1/lists/{}/files/{}": "one_way",
    "DELETE /api/v1/lists/{}/groups/{}": "one_way", "DELETE /api/v1/lists/{}/links/{}": "one_way",
    "DELETE /api/v1/lists/{}/members/{}": "one_way", "DELETE /api/v1/lists/{}/milestones/{}": "one_way",
    "DELETE /api/v1/lists/{}/tags/{}": "one_way", "DELETE /api/v1/me/app-passwords/{}": "one_way",
    "DELETE /api/v1/notepads/{}": "one_way", "DELETE /api/v1/notes/{}": "one_way", "DELETE /api/v1/sections/{}": "one_way",
    "DELETE /api/v1/tasks/{}": "one_way", "DELETE /api/v1/tasks/{}/contacts/{}": "one_way",
    "DELETE /api/v1/tasks/{}/dependencies/{}": "one_way", "DELETE /api/v1/tasks/{}/links/{}": "one_way",
    "DELETE /api/v1/team/messages/{}": "one_way", "DELETE /api/v1/team/rooms/{}/members/{}": "one_way",
    "DELETE /api/v1/templates/{}": "one_way", "DELETE /api/v1/time/entries/{}": "one_way", "DELETE /api/v1/trash": "one_way",
    "POST /api/v1/folders/delete": "one_way", "POST /api/v1/imports/{}/undo": "one_way",
    # ---- change
    "DELETE /api/v1/tasks/{}/waiting": "change", "DELETE /api/v1/time/timer": "change",
    "PATCH /api/v1/address-books/{}": "change", "PATCH /api/v1/clients/{}": "change", "PATCH /api/v1/comments/{}": "change",
    "PATCH /api/v1/contacts/{}": "change", "PATCH /api/v1/documents/{}": "change", "PATCH /api/v1/event-calendars/{}": "change",
    "PATCH /api/v1/events/{}": "change", "PATCH /api/v1/family/rewards/{}": "change", "PATCH /api/v1/fields/{}": "change",
    "PATCH /api/v1/filters/{}": "change", "PATCH /api/v1/forms/{}": "change", "PATCH /api/v1/habits/{}": "change",
    "PATCH /api/v1/lists/{}": "change", "PATCH /api/v1/lists/{}/error-hook": "change",
    "PATCH /api/v1/lists/{}/links/{}": "change", "PATCH /api/v1/lists/{}/milestones/{}": "change",
    "PATCH /api/v1/lists/{}/overview": "change", "PATCH /api/v1/lists/{}/tags/{}": "change",
    "PATCH /api/v1/me/notifications": "change", "PATCH /api/v1/notepads/{}": "change", "PATCH /api/v1/notes/{}": "change",
    "PATCH /api/v1/office/leads/{}": "change", "PATCH /api/v1/office/letters/{}": "change",
    "PATCH /api/v1/office/offers/{}": "change", "PATCH /api/v1/sections/{}": "change", "PATCH /api/v1/sheets/{}": "change",
    "PATCH /api/v1/tasks/{}": "change", "PATCH /api/v1/team/messages/{}": "change", "PATCH /api/v1/team/rooms/{}": "change",
    "PATCH /api/v1/templates/{}": "change", "PATCH /api/v1/time/entries/{}": "change",
    "PATCH /api/v1/videos/{}/comments/{}": "change", "PATCH /api/v1/wiki/pages/{}": "change",
    "POST /api/v1/address-books": "change", "POST /api/v1/address-books/{}/import": "change", "POST /api/v1/clients": "change",
    "POST /api/v1/clients/bulk": "change", "POST /api/v1/contacts": "change", "POST /api/v1/contacts/bulk": "change",
    "POST /api/v1/documents": "change", "POST /api/v1/event-calendars": "change",
    "POST /api/v1/event-calendars/{}/import": "change", "POST /api/v1/events": "change",
    "POST /api/v1/events/{}/prep-task": "change", "POST /api/v1/events/{}/restore": "change",
    "POST /api/v1/events/{}/rsvp": "change", "POST /api/v1/family/deadlines": "change",
    "POST /api/v1/family/kids/{}/rewards": "change", "POST /api/v1/family/kids/{}/stars": "change",
    "POST /api/v1/family/occasions": "change", "POST /api/v1/family/packing": "change",
    "POST /api/v1/family/rewards/{}/decide": "change", "POST /api/v1/family/rewards/{}/request": "change",
    "POST /api/v1/files": "change", "POST /api/v1/files/{}/versions": "change", "POST /api/v1/filters": "change",
    "POST /api/v1/focus/start": "change", "POST /api/v1/focus/{}/pause": "change", "POST /api/v1/focus/{}/resume": "change",
    "POST /api/v1/focus/{}/stop": "change", "POST /api/v1/folders/rename": "change", "POST /api/v1/habits": "change",
    "POST /api/v1/habits/{}/checkin": "change", "POST /api/v1/import/{}": "change", "POST /api/v1/life/contracts": "change",
    "POST /api/v1/life/devices": "change", "POST /api/v1/life/health": "change", "POST /api/v1/life/karakeep/sync": "change",
    "POST /api/v1/life/trips": "change", "POST /api/v1/life/upkeep": "change", "POST /api/v1/lists": "change",
    "POST /api/v1/lists/{}/deployments": "change", "POST /api/v1/lists/{}/duplicate": "change",
    "POST /api/v1/lists/{}/fields": "change", "POST /api/v1/lists/{}/files": "change", "POST /api/v1/lists/{}/forms": "change",
    "POST /api/v1/lists/{}/join": "change", "POST /api/v1/lists/{}/links": "change", "POST /api/v1/lists/{}/milestones": "change",
    "POST /api/v1/lists/{}/notepads": "change", "POST /api/v1/lists/{}/notes": "change", "POST /api/v1/lists/{}/owner": "change",
    "POST /api/v1/lists/{}/sections": "change", "POST /api/v1/lists/{}/shift": "change",
    "POST /api/v1/lists/{}/shop-areas": "change", "POST /api/v1/lists/{}/sprints/assign": "change",
    "POST /api/v1/lists/{}/tags": "change", "POST /api/v1/me/app-passwords": "change", "POST /api/v1/me/purpose": "change",
    "POST /api/v1/notes/{}/restore": "change", "POST /api/v1/office/leads": "change", "POST /api/v1/office/letters": "change",
    "POST /api/v1/office/letters/{}/links": "change", "POST /api/v1/office/offers": "change",
    "POST /api/v1/office/offers/{}/invoice": "change", "POST /api/v1/office/reminders": "change", "POST /api/v1/sheets": "change",
    "POST /api/v1/sheets/{}/batches/{}/undo": "change", "POST /api/v1/sheets/{}/columns": "change",
    "POST /api/v1/sheets/{}/rows": "change", "POST /api/v1/sheets/{}/tabs": "change", "POST /api/v1/tasks/batch": "change",
    "POST /api/v1/tasks/{}/approval": "change", "POST /api/v1/tasks/{}/attachments": "change",
    "POST /api/v1/tasks/{}/attachments/text": "change", "POST /api/v1/tasks/{}/contacts": "change",
    "POST /api/v1/tasks/{}/dependencies": "change", "POST /api/v1/tasks/{}/links": "change",
    "POST /api/v1/tasks/{}/move": "change", "POST /api/v1/tasks/{}/restore": "change", "POST /api/v1/tasks/{}/review": "change",
    "POST /api/v1/tasks/{}/snippets": "change", "POST /api/v1/tasks/{}/take": "change", "POST /api/v1/tasks/{}/tidy": "change",
    "POST /api/v1/tasks/{}/to-shopping": "change", "POST /api/v1/team/channels": "change", "POST /api/v1/team/dm": "change",
    "POST /api/v1/team/groups": "change", "POST /api/v1/team/messages/{}/pin": "change",
    "POST /api/v1/team/rooms/{}/members": "change", "POST /api/v1/templates": "change",
    "POST /api/v1/templates/{}/apply": "change", "POST /api/v1/time/entries": "change", "POST /api/v1/time/timer": "change",
    "POST /api/v1/wiki/pages": "change", "PUT /api/v1/address-books/{}/members/{}": "change",
    "PUT /api/v1/admin/announcement": "change", "PUT /api/v1/contacts/{}/care": "change",
    "PUT /api/v1/event-calendars/{}/members/{}": "change", "PUT /api/v1/life/journal/{}": "change",
    "PUT /api/v1/lists/{}/groups/{}": "change", "PUT /api/v1/lists/{}/links/order": "change",
    "PUT /api/v1/lists/{}/members/{}": "change", "PUT /api/v1/lists/{}/review": "change",
    "PUT /api/v1/lists/{}/sections/order": "change", "PUT /api/v1/lists/{}/status": "change",
    "PUT /api/v1/lists/{}/status-pad": "change", "PUT /api/v1/sheets/{}/cells": "change",
    "PUT /api/v1/tasks/{}/waiting": "change",
    # 2.425.0 (#3453): only a receipt fetcher's own key reaches these (an agent token gets 403); the default class stays
    "POST /api/v1/fetcher/documents": "change", "PUT /api/v1/fetcher/status": "change",
}

FOUND, PROBLEMS = app_routes(ROOT)
for p in PROBLEMS:
    check(False, f"route the guard cannot read: {p}")
writes = {r for r in FOUND if r.split(" ", 1)[0] in ("POST", "PUT", "PATCH", "DELETE") and r.split(" ", 1)[1].startswith("/api/v1/")}
for r in sorted(writes):
    m, p = r.split(" ", 1)
    got = ctl_class(m, p[len("/api/v1"):], {})
    if r not in ROUTES:
        check(False, f"{r}: a new write route an agent reaches -- decide its control class (now {got}) in CTL_ROUTES or ROUTES here")
    else:
        check(got == ROUTES[r], f"{r}: class {got}, decided {ROUTES[r]}")
for r in sorted(set(ROUTES) - writes):
    check(False, f"ROUTES names {r}, which is no route (any more)")

# the body decides: plan = only the dates, batch by its action
check(ctl_class("PATCH", "/tasks/{}", {"due": "2026-11-01"}) == "routine", "PATCH a task's due date = routine (plan)")
check(ctl_class("PATCH", "/tasks/{}", {"due": "2026-11-01", "start": None, "due_time": "09:00", "expect_updated_at": "x"}) == "routine",
      "plan + the conflict helper = routine")
check(ctl_class("PATCH", "/tasks/{}", {"due": "2026-11-01", "title": "x"}) == "change", "a title with the date = change")
check(ctl_class("PATCH", "/tasks/{}", {"priority": "high"}) == "change", "other fields = change")
check(ctl_class("POST", "/tasks/batch", {"action": "delete", "ids": [1]}) == "one_way", "a batch that deletes = one_way")
check(ctl_class("POST", "/tasks/batch", {"action": "complete", "ids": [1]}) == "routine", "a batch that ticks off = routine")
check(ctl_class("POST", "/tasks/batch", {"action": "update", "changes": {"due": "2026-11-01"}, "ids": [1]}) == "routine", "a batch plan = routine")
check(ctl_class("POST", "/tasks/batch", {"action": "update", "changes": {"title": "x"}, "ids": [1]}) == "change", "a batch change = change")
check(ctl_class("POST", "/tasks/batch", {"action": "wont_do", "ids": [1]}) == "change", "a batch won't do = change")
check(ctl_class("DELETE", "/no/such/route", {}) == "one_way", "an unknown DELETE = one_way (careful)")
check(ctl_class("POST", "/no/such/route", {}) == "change", "an unknown POST = change (careful)")
sys.exit(done("p2235_a_control_routes"))
