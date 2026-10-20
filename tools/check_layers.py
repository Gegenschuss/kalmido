#!/usr/bin/env python3
"""Checks the layers of the server package (2.102.0, #1999; see docs/ARCHITECTURE.md).

kalmido/__init__.py sorts every package into one of five layers (LAYERS: core, accounts, domain, integrations, agents;
LAYER_OF moves a single module). A module may import at MODULE LEVEL only from its own or a lower layer. An import of a
higher layer belongs inside the function that needs it (function-local imports are allowed and only counted). The
upward imports the code already had when the check came stand in KNOWN below -- they are not rebuilt, but no new one
may join, and an entry that is gone must leave the list (so it only shrinks).

usage: python3 tools/check_layers.py [-v]     exit code 1 on a new upward import, an unknown package or a stale entry
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (importing module, imported module): upward imports at module level found on 2.96.2. Mostly the API layer (api.v1:
# helpers of the /api/v1 routes, used by the domain modules' v1 routes), agents.core (agent events, emitted from the
# domain) and admin.backup; the core reads the session of accounts. Remove a line once the import moved into a function.
KNOWN = {
    ("core.access", "accounts.session"), ("core.serializers", "accounts.session"), ("core.pages", "accounts.session"),
    ("core.instance", "accounts.session"), ("core.instance", "accounts.oidc"), ("core.state", "accounts.session"),
    ("core.state", "accounts.pictures"), ("core.state", "accounts.colors"),
    ("accounts.settings", "lists.lists"), ("accounts.settings", "tasks.validation"), ("accounts.settings", "collab.news"),
    ("accounts.settings", "personal.timetrack"), ("accounts.layouts", "personal.timetrack"),
    ("accounts.layoutsets", "personal.timetrack"), ("accounts.onboarding", "tasks.validation"),
    ("accounts.onboarding", "tasks.tasks"), ("accounts.users", "personal.timetrack"),
    ("lists.points", "agents"), ("api.scopes", "agents.admin"), ("api.scopes", "agents.api"),
    ("api.scopes", "agents.core"), ("collab.e2e", "agents.core"), ("collab.msgsearch", "agents.core"),
    ("collab.reactions", "agents.core"), ("collab.teamchat", "agents.core"), ("family.family", "agents.core"),
    ("integrations.errorreports", "agents.core"), ("integrations.git", "agents.core"),
    ("integrations.gitfolder", "agents.core"), ("integrations.mail", "agents.core"), ("lists.envs", "agents.core"),
    ("accounts.layouts_more", "agents.lyprop"), ("accounts.signup", "api.v1"), ("collab.cchoice", "api.v1"),
    ("collab.chatpins", "api.v1"), ("collab.msgsearch", "api.v1"), ("collab.notes", "api.v1"),
    ("collab.reactions", "api.v1"), ("collab.teamchat", "api.v1"), ("contacts.bulk", "api.v1"),
    ("contacts.v1", "api.v1"), ("docs.v1", "api.v1"), ("events.v1", "api.v1"), ("family.v1", "api.v1"),
    ("files.v1", "api.v1"), ("hub.absence", "api.v1"), ("hub.agentdispo", "api.v1"), ("life.v1", "api.v1"),
    ("lists.envs", "api.v1"), ("lists.kpis", "api.v1"), ("lists.orgvis", "api.v1"), ("lists.playbook", "api.v1"),
    ("lists.points", "api.v1"), ("lists.public", "api.v1"), ("lists.report", "api.v1"), ("lists.rules", "api.v1"),
    ("lists.sprints", "api.v1"), ("notify.caps", "api.v1"), ("office.agentdocs", "api.v1"), ("office.leads", "api.v1"),
    ("office.signoff", "api.v1"), ("personal.timegaps", "api.v1"), ("receipts.suggest", "api.v1"),
    ("sheets.v1", "api.v1"), ("tasks.attachtext", "api.v1"), ("tasks.briefing", "api.v1"), ("tasks.dayplan", "api.v1"),
    ("tasks.multilist", "api.v1"), ("tasks.related", "api.v1"), ("tasks.review", "api.v1"),
    ("tasks.snippets", "api.v1"), ("tasks.stale", "api.v1"), ("team.forms", "api.v1"), ("team.v1", "api.v1"),
    ("videos.v1", "api.v1"), ("accounts.servers", "calendars.subscriptions"), ("accounts.invite", "integrations.mail"),
    ("accounts.pwreset", "integrations.mail"),
    # from the releases merged after 2.96.2 (2.98.0 scheduling polls)
    ("calendars.polls", "api.v1"),
    # 2.124.1: the sheet routes of API v1 (decorators at module level, as sheets.v1)
    ("sheets.shbook", "api.v1"),
    # the parked releases 2.113.1 / 2.116.0 (#2059 team chat channels, #2067 focus in API v1): v1 route decorators at module level
    ("collab.teamchan", "api.v1"), ("personal.v1focus", "api.v1"),
}


def layers():
    """(layer index of a module name, ORDER) read from kalmido/__init__.py without importing it."""
    with open(os.path.join(ROOT, "kalmido", "__init__.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    val = {}
    for n in tree.body:
        name = getattr(n.targets[0], "id", "") if isinstance(n, ast.Assign) and len(n.targets) == 1 else ""
        if name in ("LAYERS", "LAYER_OF", "ORDER"):
            val[name] = ast.literal_eval(n.value)
    names = [name for name, _ in val["LAYERS"]]
    pkg = {p: i for i, (_, ps) in enumerate(val["LAYERS"]) for p in ps}
    single = {m: names.index(l) for m, l in val.get("LAYER_OF", {}).items()}
    return names, pkg, single, list(val["ORDER"])


def target(mod, node):
    """The kalmido module an ImportFrom names ('tasks.tasks'), or None for a foreign import."""
    if node.level == 0:
        parts = (node.module or "").split(".")
        return (".".join(parts[1:]) or None) if parts[0] == "kalmido" else None
    base = mod.split(".")[:-1]
    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
    parts = base + (node.module.split(".") if node.module else [])
    return ".".join(parts) or None


def scan(mod, tree):
    """(module-level kalmido imports, number of function-local ones) of one module."""
    top, local = [], 0

    def walk(nodes, in_func):
        nonlocal local
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                walk(ast.iter_child_nodes(n), True)
                continue
            if isinstance(n, ast.ImportFrom):
                t = target(mod, n)
                if t:
                    if in_func:
                        local += 1
                    else:
                        top.append((t, n.lineno))
                continue
            walk(ast.iter_child_nodes(n), in_func)

    walk(tree.body, False)
    return top, local


def main():
    names, pkg, single, order = layers()
    err, seen, locals_ = [], set(), 0

    def layer_of(m):
        if m in single:
            return single[m]
        p = m.split(".")[0]
        if p not in pkg:
            err.append(f"kalmido/__init__.py LAYERS: package {p!r} ({m}) has no layer")
            pkg[p] = len(names) - 1
        return pkg[p]

    for mod in order:
        path = os.path.join(ROOT, "kalmido", *mod.split(".")) + ".py"
        with open(path, encoding="utf-8") as f:
            top, local = scan(mod, ast.parse(f.read(), path))
        locals_ += local
        own = layer_of(mod)
        for t, line in top:
            # "from ..core import db" names a package: the layer of its first part decides
            if layer_of(t) > own:
                seen.add((mod, t))
                if (mod, t) not in KNOWN:
                    err.append(f"kalmido/{mod.replace('.', '/')}.py:{line}: module-level import of {t} "
                               f"({names[layer_of(t)]}) from layer {names[own]} -- import it inside the function")
    for k in sorted(KNOWN - seen):
        err.append(f"tools/check_layers.py KNOWN: {k[0]} -> {k[1]} is no upward import any more, remove the entry")
    if "-v" in sys.argv:
        print(f"{len(order)} modules, {len(seen)} known upward imports, {locals_} function-local kalmido imports")
    for e in err:
        print("check_layers:", e)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
