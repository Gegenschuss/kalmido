"""2.182.0 (#2718): the routes of the server, read with the Python parser instead of a line pattern -- for the coverage guards
(tenant_coverage_test.py, freelancer_coverage_test.py). A route in another form (indented, single quotes, over several lines,
methods=..., app.add_url_rule) is found all the same; a route the guards cannot read (registered on another object than
`app`, a blueprint, a path that is no plain string) comes back as a problem, so it cannot slip past the boundary checks.
No container needed: reads app.py + kalmido/."""
import ast
import glob
import os
import re

VERBS = ("get", "post", "put", "patch", "delete")


def norm(p):
    return re.sub(r"<[^>]+>", "{}", p)


def _path(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _methods(call):
    for kw in call.keywords:
        if kw.arg == "methods":
            if isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)) and all(_path(e) for e in kw.value.elts):
                return [_path(e).upper() for e in kw.value.elts]
            return None
    return ["GET"]


def app_routes(root):
    """-> (routes, problems): routes = {"GET /api/x/{}", ..., "DAV /dav/{}"} (as the old pattern named them: @app.route = DAV,
    CalDAV / CardDAV with PROPFIND, REPORT, ...); problems = texts "file:line what" of registrations the guards cannot check."""
    found, problems = set(), []
    files = [os.path.join(root, "app.py")] + sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True))
    for fn in files:
        rel = os.path.relpath(fn, root)
        tree = ast.parse(open(fn, encoding="utf-8").read(), fn)
        decos = {id(d) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for d in n.decorator_list}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Blueprint":
                problems.append(f"{rel}:{node.lineno} a Blueprint: register routes on app only")
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            attr, owner = node.func.attr, node.func.value
            if attr not in VERBS + ("route", "add_url_rule"):
                continue
            on_app = isinstance(owner, ast.Name) and owner.id == "app"
            arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "rule"), None)
            p = _path(arg) if arg is not None else None
            if not on_app:
                # requests.get(...), s.post(...) etc. are no routes: a decorator (or route / add_url_rule) on another object is a problem
                if attr in ("route", "add_url_rule") or id(node) in decos:
                    problems.append(f"{rel}:{node.lineno} route {p or '?'} registered on another object than app")
                continue
            if p is None:
                problems.append(f"{rel}:{node.lineno} app.{attr} with a path that is no plain string")
                continue
            if attr in VERBS:
                found.add(f"{attr.upper()} {norm(p)}")
            elif attr == "route":
                found.add(f"DAV {norm(p)}")
            else:  # app.add_url_rule(rule, endpoint, view, methods=[...])
                ms = _methods(node)
                if ms is None:
                    problems.append(f"{rel}:{node.lineno} app.add_url_rule {p} with methods that are no plain list")
                    continue
                found |= {f"{m if m.lower() in VERBS else 'DAV'} {norm(p)}" for m in ms}
    return found, problems

