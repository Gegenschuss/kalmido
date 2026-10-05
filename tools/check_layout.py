#!/usr/bin/env python3
"""Checks that the module lists agree (2.20.0, #646; see docs/ARCHITECTURE.md):

  * web client: every static/js/*.js is loaded by a <script> tag in static/index.html, main.js last, and the service
    worker (static/sw.js, SHELL) precaches exactly these files in the same order
  * server: kalmido/__init__.py ORDER names every module of the package exactly once (and nothing else)

usage: python3 tools/check_layout.py      exit code 1 on a mismatch
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERR = []


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "static", "js", "*.js")))
tags = re.findall(r'<script src="/static/js/([\w-]+\.js)"></script>', read("static", "index.html"))
shell = re.findall(r"'/static/js/([\w-]+\.js)'", read("static", "sw.js"))
if sorted(tags) != files:
    ERR.append(f"index.html script tags vs static/js/: missing {sorted(set(files) - set(tags))}, unknown {sorted(set(tags) - set(files))}")
if len(set(tags)) != len(tags):
    ERR.append("index.html loads a module twice")
if tags and tags[-1] != "main.js":
    ERR.append("index.html: main.js (the start-up) must be the last script")
if shell != tags:
    ERR.append("sw.js SHELL: the static/js/ files differ from index.html (same files, same order)")

init = read("kalmido", "__init__.py")
m = re.search(r"ORDER = \((.*?)\n\)", init, re.S)
order = re.findall(r'"([\w.]+)"', m.group(1)) if m else []
mods = sorted(os.path.relpath(p, os.path.join(ROOT, "kalmido"))[:-3].replace(os.sep, ".")
              for p in glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)
              if not p.endswith("__init__.py"))
if sorted(order) != mods or len(set(order)) != len(order):
    ERR.append(f"kalmido/__init__.py ORDER vs the package: missing {sorted(set(mods) - set(order))}, unknown {sorted(set(order) - set(mods))}")
for p in glob.glob(os.path.join(ROOT, "kalmido", "*", "__init__.py")):
    body = re.sub(r'^""".*?"""\s*', "", read(p), flags=re.S).strip()
    if body:
        ERR.append(f"{os.path.relpath(p, ROOT)} must stay empty (only a docstring): the load order is kalmido/__init__.py's job")

for e in ERR:
    print("ERROR:", e)
print(f"check_layout: {len(tags)} client modules, {len(order)} server modules, {len(ERR)} error(s)")
sys.exit(1 if ERR else 0)
