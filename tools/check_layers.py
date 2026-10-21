#!/usr/bin/env python3
"""Checks the layers of the server package (2.102.0, #1999; see docs/ARCHITECTURE.md).

kalmido/__init__.py sorts every package into one of five layers (LAYERS: core, accounts, domain, integrations, agents;
LAYER_OF moves a single module). A module may import at MODULE LEVEL only from its own or a lower layer. An import of a
higher layer belongs inside the function that needs it (function-local imports are allowed and counted, see BUDGET). The
upward imports the code already had when the check came stand in KNOWN below -- they are not rebuilt, but no new one
may join, and an entry that is gone must leave the list (so it only shrinks).

2.149.0 G (#2517): the function-local imports are counted per kind against tools/layers_budget.json (only sinks).

usage: python3 tools/check_layers.py [-v] [--update]     exit code 1 on a new upward import, an unknown package, a stale
       entry or a count above its budget; --update lowers the budget to the counts of today
"""
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (importing module, imported module): upward imports at module level found on 2.96.2. Mostly the API layer (api.v1:
# helpers of the /api/v1 routes, used by the domain modules' v1 routes), agents.core (agent events, emitted from the
# domain) and admin.backup; the core reads the session of accounts. Remove a line once the import moved into a function.
# 2.149.0 G (#2517): BadInput & co. (core.errors), me() (core.ctx) and the v1 route helpers (api.common, core layer) moved
# down: 36 entries left the list.
KNOWN = {
    ("core.pages", "accounts.session"), ("core.instance", "accounts.session"), ("core.instance", "accounts.oidc"),
    ("core.state", "accounts.session"), ("core.state", "accounts.pictures"), ("core.state", "accounts.colors"),
    ("accounts.settings", "lists.lists"), ("accounts.settings", "tasks.validation"),
    ("accounts.settings", "collab.news"), ("accounts.onboarding", "tasks.validation"),
    ("accounts.onboarding", "tasks.tasks"), ("lists.points", "agents"), ("api.scopes", "agents.admin"),
    ("api.scopes", "agents.api"), ("api.scopes", "agents.core"), ("collab.e2e", "agents.core"),
    ("collab.msgsearch", "agents.core"), ("collab.reactions", "agents.core"), ("collab.teamchat", "agents.core"),
    ("family.family", "agents.core"), ("integrations.errorreports", "agents.core"), ("integrations.git", "agents.core"),
    ("integrations.gitfolder", "agents.core"), ("integrations.mail", "agents.core"), ("lists.envs", "agents.core"),
    ("accounts.layouts_more", "agents.lyprop"), ("collab.msgsearch", "api.v1"), ("collab.notes", "api.v1"),
    ("collab.reactions", "api.v1"), ("contacts.v1", "api.v1"), ("docs.v1", "api.v1"), ("family.v1", "api.v1"),
    ("files.v1", "api.v1"), ("life.v1", "api.v1"), ("lists.public", "api.v1"), ("office.agentdocs", "api.v1"),
    ("receipts.suggest", "api.v1"), ("sheets.v1", "api.v1"), ("tasks.dayplan", "api.v1"), ("tasks.multilist", "api.v1"),
    ("tasks.snippets", "api.v1"), ("videos.v1", "api.v1"), ("accounts.servers", "calendars.subscriptions"),
    ("accounts.invite", "integrations.mail"), ("accounts.pwreset", "integrations.mail"),
    # the parked releases 2.113.1 / 2.116.0 (#2059 team chat channels, #2067 focus in API v1): v1 route decorators at module level
    ("personal.v1focus", "api.v1"),
    # 2.153.0 (#2031, built on 2.106.0 before the check): the letter draft routes of API v1 (decorators at module level)
    ("office.letteragent", "api.v1"),
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
    """(module-level kalmido imports, function-local kalmido imports as (target, line, names)) of one module."""
    top, local = [], []

    def walk(nodes, in_func):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                walk(ast.iter_child_nodes(n), True)
                continue
            if isinstance(n, ast.ImportFrom):
                t = target(mod, n)
                if t:
                    if in_func:
                        local.append((t, n.lineno, [a.name for a in n.names]))
                    else:
                        top.append((t, n.lineno))
                continue
            walk(ast.iter_child_nodes(n), in_func)

    walk(tree.body, False)
    return top, local


# 2.149.0 G (#2517): the function-local imports are counted per kind against tools/layers_budget.json; a count may only
# sink (CI fails when one grows; -v names the modules, --update writes a lower count into the budget, never a higher one).
#   local_upward:  a function imports from a HIGHER layer (allowed, but every new one is a new upward dependency)
#   local_needless: the target comes EARLIER in ORDER and sits in the same or a lower layer -- the import could stand at
#                  module level (it only hides the real cycle-avoiding imports)
#   clock:         (warning only) datetime.now() / date.today() / datetime.utcnow() outside core/db.py (now_utc / local_now know the test
#                  clock, 2.149.0 E #2512); CLOCK_OK are the places that need the real wall clock
BUDGET = os.path.join(ROOT, "tools", "layers_budget.json")
CLOCK_OK = {"core.db", "admin.offsite", "office.terms", "docs.extract", "office.pdf"}
WARN_ONLY = {"clock"}  # a warning only for now (the CI log shows it, the step stays green)


def clock_calls(tree):
    """Lines of datetime.now() / datetime.today() / datetime.utcnow() / date.today() calls."""
    out = []
    for n in ast.walk(tree):
        f = getattr(n, "func", None) if isinstance(n, ast.Call) else None
        if isinstance(f, ast.Attribute) and f.attr in ("now", "today", "utcnow"):
            v = f.value
            name = v.id if isinstance(v, ast.Name) else v.attr if isinstance(v, ast.Attribute) else ""
            if name in ("datetime", "date"):
                out.append(n.lineno)
    return out


def module_of(t, names, pos):
    """The module a function-local import loads: 'from ..core import db' names the module core.db."""
    if t in pos:
        return t
    subs = [f"{t}.{x}" for x in names if f"{t}.{x}" in pos]
    return subs[0] if subs else t


def main():
    names, pkg, single, order = layers()
    err, warn, seen = [], [], set()
    pos = {m: i for i, m in enumerate(order)}
    counts = {"local": 0, "local_upward": 0, "local_needless": 0, "clock": 0}
    where = {k: {} for k in counts}

    def layer_of(m):
        if m in single:
            return single[m]
        p = m.split(".")[0]
        if p not in pkg:
            err.append(f"kalmido/__init__.py LAYERS: package {p!r} ({m}) has no layer")
            pkg[p] = len(names) - 1
        return pkg[p]

    def count(kind, mod, n=1):
        counts[kind] += n
        where[kind][mod] = where[kind].get(mod, 0) + n

    for mod in order:
        path = os.path.join(ROOT, "kalmido", *mod.split(".")) + ".py"
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        top, local = scan(mod, tree)
        own = layer_of(mod)
        for t, line in top:
            # "from ..core import db" names a package: the layer of its first part decides
            if layer_of(t) > own:
                seen.add((mod, t))
                if (mod, t) not in KNOWN:
                    err.append(f"kalmido/{mod.replace('.', '/')}.py:{line}: module-level import of {t} "
                               f"({names[layer_of(t)]}) from layer {names[own]} -- import it inside the function")
        for t, line, nm in local:
            count("local", mod)
            t = module_of(t, nm, pos)
            if layer_of(t) > own:
                count("local_upward", mod)
            elif t != mod and pos.get(t, len(order)) < pos[mod]:
                count("local_needless", mod)
        if mod not in CLOCK_OK:
            n = len(clock_calls(tree))
            if n:
                count("clock", mod, n)
    for k in sorted(KNOWN - seen):
        err.append(f"tools/check_layers.py KNOWN: {k[0]} -> {k[1]} is no upward import any more, remove the entry")
    budget = {}
    if os.path.exists(BUDGET):
        with open(BUDGET, encoding="utf-8") as f:
            budget = json.load(f)
    for k in ("local_upward", "local_needless", "clock"):
        if k not in budget:
            err.append(f"tools/layers_budget.json: no budget for {k!r} (now {counts[k]})")
        elif counts[k] > budget[k]:
            top5 = ", ".join(f"{m} {n}" for m, n in sorted(where[k].items(), key=lambda x: -x[1])[:5])
            (warn if k in WARN_ONLY else err).append(f"{k}: {counts[k]} > budget {budget[k]} (tools/layers_budget.json) -- a new function-local "
                       f"import of this kind; most in: {top5}")
    if "--update" in sys.argv and not err:
        new = {**budget, **{k: min(counts[k], budget.get(k, counts[k])) for k in ("local_upward", "local_needless", "clock")}}
        with open(BUDGET + ".new", "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2)
            f.write("\n")
        os.replace(BUDGET + ".new", BUDGET)
    if "-v" in sys.argv:
        print(f"{len(order)} modules, {len(seen)} known upward imports, {counts['local']} function-local kalmido imports: "
              f"{counts['local_upward']} upward, {counts['local_needless']} could stand at module level; "
              f"{counts['clock']} wall-clock calls outside core/db.py")
        for k in ("local_upward", "local_needless", "clock"):
            if budget.get(k, 0) > counts[k]:
                print(f"  {k}: {counts[k]} < budget {budget[k]} -- lower it: python3 tools/check_layers.py --update")
    for e in warn:
        print("check_layers: warning:", e)
    for e in err:
        print("check_layers:", e)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
