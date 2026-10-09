"""Kalmido server package. app.py is the entry point; docs/ARCHITECTURE.md explains the layout.

The modules are loaded in the fixed ORDER below (it is the order the code had in the former single app.py): routes, request
hooks and error handlers register in that order, and each module may use names of EARLIER modules at import time
(`from ..core.db import connect` at the top). A name of a LATER module is imported inside the function that needs it
(at call time, when every module is loaded) -- that keeps the import graph free of cycles.
"""
import importlib

ORDER = (
    "core.config",
    "core.schema",
    "core.i18n",
    "core.db",
    "accounts.session",
    "accounts.pictures",
    "accounts.login",
    "accounts.oidc",
    "core.access",
    "core.serializers",
    "core.pages",
    "core.instance",
    "core.state",
    "lists.lists",
    "lists.groups",
    "lists.ownership",
    "lists.sections",
    "lists.folders",
    "tasks.validation",
    "tasks.tasks",
    "tasks.roadmap",
    "tasks.lifecycle",
    "tasks.attachments",
    "integrations.paperless",
    "tasks.batch",
    "collab.replies",  # 2.33.0 (#1076): before comments / teamchat / agents.chat (they import it)
    "collab.comments",
    "collab.news",
    "personal.habits",
    "personal.timetrack",
    "accounts.settings",
    "accounts.layouts",  # 2.32.0 (#1063, #983)
    "accounts.onboarding",
    "accounts.users",
    "accounts.orgs",
    "accounts.tenancy",
    "lists.templates",
    "tasks.dependencies",
    "lists.projects",
    "lists.fields",
    "personal.stats",
    "calendars.icalfeed",
    "calendars.caldav",
    "integrations.importers",
    "notify.push",
    "notify.alerts",
    "calendars.subscriptions",
    "admin.backup",
    "api.v1",
    "notify.caps",  # 2.33.0 (#927)
    "tasks.dayplan",
    "api.openapi",
    "integrations.webhooks",
    "agents.core",
    "collab.reactions",
    "agents.chat",
    "agents.steps",  # 2.32.0 (#1081 / #1079)
    "agents.quota",  # 2.33.0 (#1045)
    "agents.admin",
    "agents.api",
    "agents.proposals",
    "agents.gates",  # 2.26.0 (#949)
    "agents.safety",  # 2.30.0 (#919)
    "agents.usage",
    "lists.public",
    "integrations.git",
    "integrations.gitfolder",  # 2.33.0 (#934)
    "integrations.errorreports",
    "api.projects",
    "api.scopes",
    "collab.notes",
    "collab.teamchat",
    "collab.msgsearch",  # 2.33.0 (#1080)
    "integrations.mail",
    "accounts.invite",
    "family.family",
    "family.web",
    "family.carddav",
    "family.v1",
    "events.model",
    "events.ics",
    "events.web",
    "events.dav",
    "events.v1",
    "contacts.model",
    "contacts.carddav",
    "contacts.web",
    "contacts.v1",
    "life.model",
    "life.karakeep",
    "life.web",
    "life.v1",
    "team.clients",
    "team.workload",
    "team.approvals",
    "team.forms",
    "team.v1",
    "accounts.signup",
    "admin.hosting",
    "admin.clientip",  # 2.33.0 (#834)
    "startup",
)
MODULES = [importlib.import_module(f"{__name__}.{m}") for m in ORDER]
