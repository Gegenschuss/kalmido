"""2.49.0 (#1201): the import of the mind map -- an outline (Markdown list, OPML, FreeMind / Freeplane .mm) as a tree of
titles. The app creates the tasks from it with its own routes (one Undo step), so the rights are the list's as always.
XML: no DOCTYPE / ENTITY at all (no external entities, no entity expansion), size and node limits.
"""
import re
import xml.etree.ElementTree as ET

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body
from ..personal.timetrack import BadInput

MM_TEXT_MAX, MM_NODES_MAX, MM_DEPTH_MAX, MM_TITLE_MAX = 500_000, 500, 12, 500


def mm_node(title, kids=None):
    return {"title": re.sub(r"\s+", " ", str(title or "")).strip()[:MM_TITLE_MAX], "children": kids or []}


def mm_parse_md(text):
    """A Markdown list (- / * / + / 1.) by its indentation; headings (#, ##) become levels above the list items."""
    root, stack = mm_node(""), []  # stack: (level, node)
    for ln in text.splitlines():
        if not ln.strip() or re.match(r"^\s*```", ln):
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", ln)
        m = re.match(r"^(\s*)(?:[-*+•]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.*)", ln)
        if h:
            lvl, title = len(h.group(1)) - 7, h.group(2)  # headings above every list level
        elif m:
            lvl, title = len(m.group(1).replace("\t", "    ")), m.group(2)
        else:
            continue
        n = mm_node(title)
        if not n["title"]:
            continue
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        (stack[-1][1]["children"] if stack else root["children"]).append(n)
        stack.append((lvl, n))
    return root


def mm_xml(text):
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise BadInput(tr("This file is not allowed (DOCTYPE / ENTITY)"))
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        raise BadInput(tr("The file could not be read"))


MM_XML_DEPTH = 40  # 2.49.0 review L5: deeper branches of an imported file are cut (no recursion error on hostile files)


def mm_parse_opml(text):
    def walk(el, d=0):
        if d >= MM_XML_DEPTH:
            return []
        return [mm_node(o.get("text") or o.get("title") or "", walk(o, d + 1)) for o in el.findall("outline")]
    x = mm_xml(text)
    b = x.find("body")
    t = x.find("head/title")
    return mm_node(t.text if t is not None else "", walk(b if b is not None else x))


def mm_parse_freemind(text):
    def walk(el, d=0):
        if d >= MM_XML_DEPTH:
            return []
        return [mm_node(n.get("TEXT") or (n.findtext("richcontent") or ""), walk(n, d + 1)) for n in el.findall("node")]
    x = mm_xml(text)
    top = x.find("node")
    if top is None:
        return mm_node("")
    return mm_node(top.get("TEXT") or "", walk(top))


def mm_prune(n, depth=0, count=None):
    """Empty titles out, depth and number of nodes capped."""
    count = count if count is not None else [0]
    out = []
    for k in n["children"]:
        if count[0] >= MM_NODES_MAX:
            break
        if not k["title"]:
            out.extend(mm_prune(k, depth, count)["children"])
            continue
        count[0] += 1
        out.append(mm_prune(k, depth + 1, count) if depth + 1 < MM_DEPTH_MAX else mm_node(k["title"]))
    return {"title": n["title"], "children": out}


@app.post("/api/outline/parse")
def mm_outline_parse():
    """{text, format: md | opml | mm (absent: guessed)} -> {title, children: [{title, children}]} (nothing is stored)."""
    b = body()
    text, fmt = b.get("text"), b.get("format") or ""
    if not isinstance(text, str) or not text.strip():
        raise BadInput(tr("Nothing to import"))
    if len(text) > MM_TEXT_MAX:
        raise BadInput(tr("The file is too large"))
    if fmt not in ("", "md", "opml", "mm"):
        raise BadInput(tr("Invalid value: {0}", "format"))
    head = text.lstrip()[:400].lower()
    if not fmt:
        fmt = "opml" if "<opml" in head else "mm" if "<map" in head else "md"
    tree = mm_parse_opml(text) if fmt == "opml" else mm_parse_freemind(text) if fmt == "mm" else mm_parse_md(text)
    tree = mm_prune(tree)
    if not tree["children"]:
        raise BadInput(tr("Nothing to import"))
    return jsonify(format=fmt, **tree)
