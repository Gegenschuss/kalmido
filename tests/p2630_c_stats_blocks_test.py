#!/usr/bin/env python3
# kalmido-suite: after=parity nodata
"""2.630.0 (#4617) the product rule of the statistics (decided 04.11.2026): every module of Home & life (LIFE_MODS in
kalmido/life/model.py) brings its statistics block -- a key of GET /api/stats (stl_blocks in kalmido/personal/statslife.py)
AND a block of LY.stats (static/js/dashboard.js) -- or stands in STL_NO_BLOCK (statslife.py) with the reason why not.
A new module with neither makes this red. Static (reads the sources, no container); the numbers behind the keys are checked
by p2630_c_stats_api_test.py.
usage: python3 -I tests/p2630_c_stats_blocks_test.py"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import check, done  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def assigned(src, name):
    """The literal value of the module-level assignment `name = ...` in Python source src."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def api_keys(src):
    """The keys stl_blocks puts into the answer (out["x"] = ...)."""
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "stl_blocks")
    return {n.targets[0].slice.value for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript)
            and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id == "out" and isinstance(n.targets[0].slice, ast.Constant)}


def ly_keys(js):
    """The block keys of LY.stats (its definition up to the closing "]};")."""
    m = re.search(r"^LY\.stats = \{(.*?)\]\};", js, re.S | re.M)
    return set(re.findall(r"\['([a-z_]+)', N_\(", m.group(1))) if m else set()


def missing(mods, api, ly, no_block):
    """-> [(module, what is wrong)]: neither a block (both halves) nor a reason; a reason for a module that has a block; a
    reason without text; a reason for something that is no module."""
    out = []
    for m in mods:
        has = m in api and m in ly
        if m in no_block:
            if has:
                out.append((m, "has a block and still a reason in STL_NO_BLOCK"))
            elif not str(no_block[m]).strip():
                out.append((m, "an empty reason"))
        elif not has:
            out.append((m, f"no statistics block (key in /api/stats: {m in api}, block in LY.stats: {m in ly}) and no reason"))
    out += [(m, "in STL_NO_BLOCK but no module of Home & life") for m in no_block if m not in mods]
    return out


mods = assigned(read("kalmido", "life", "model.py"), "LIFE_MODS")
sl = read("kalmido", "personal", "statslife.py")
no_block = assigned(sl, "STL_NO_BLOCK")
api, ly = api_keys(sl), ly_keys(read("static", "js", "dashboard.js"))
check(len(mods) >= 8 and {"contracts", "health", "travel"} <= set(mods), f"LIFE_MODS read: {mods}")
check({"contracts", "health", "travel"} <= api, f"#4617: /api/stats has the keys contracts / health / travel: {sorted(api)}")
check({"contracts", "health", "travel", "tiles", "done"} <= ly, f"#4617: LY.stats has the blocks contracts / health / travel: {sorted(ly)}")
check(set(no_block) == {"home", "care", "review", "reading", "budget"}, f"#4617: the exceptions with a reason: {sorted(no_block)}")
bad = missing(mods, api, ly, no_block)
check(not bad, f"#4617 product rule: every module of Home & life has a statistics block or a reason: {bad}")
# the rule itself: a new module with neither is red, a half block (only the API key) too, a stale reason too
check(missing(tuple(mods) + ("garden",), api, ly, no_block) == [("garden", "no statistics block (key in /api/stats: False, block in LY.stats: False) and no reason")],
      "#4617: a new module without a block and without a reason fails")
check([m for m, _ in missing(tuple(mods) + ("garden",), api | {"garden"}, ly, no_block)] == ["garden"], "#4617: only the API key is not enough")
check([m for m, _ in missing(mods, api, ly, {**no_block, "contracts": "x"})] == ["contracts"], "#4617: a reason next to a block fails")
check([m for m, _ in missing(mods, api, ly, {**no_block, "garden": "x"})] == ["garden"], "#4617: a reason for no module fails")
sys.exit(done("p2630_c_stats_blocks"))
