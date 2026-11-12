"""2.1086.0 (#5820, decided 12.11.2026): the help for people in the app -- per area short "How to" sections in everyday words
with the click path, from the same source the agents search (#5819, api/helpdocs.py): one guide that runs with the version.

- Source: a "## How to: ..." section of docs/*.md with <!-- user-help: <area> --> below its heading (helpdocs.py _hlp_mark);
  the text is English, its translations stand in docs/help/<lang>.md (one block per section, named by its key and the
  fingerprint of the English text it was made from; tools/check_userhelp.py turns red on a missing or outdated block and on
  a **label** that is no text of the interface).
- GET /api/help -> {lang, areas: [{area, title, sections: [{key, title, show}]}]} in the person's language (the help view's list)
- GET /api/search?kind=help&q= -> {data: [{key, area, title, snippet}]}: the user's sections only (the search registry's web
  side of the kind help; the API's side, /api/v1/search?kind=help, keeps every public section, the user's first)
- GET /api/help/section?key= -> {key, area, title, text (Markdown), show, lang}: the translation when there is one, else English;
  an unknown key or a section that is no user's section answers 404.
Every signed-in person (the documentation is public), no organisation involved.
"""
import re

from flask import jsonify, request

from ..core.config import app
from ..core.errors import BadInput
from ..core.i18n import lang, md_plain, tr
from ..core.srchreg import srch_q, srch_register
from .helpdocs import HELP_AREAS, hlp_index, hlp_search, hlp_user_text

UH_TITLE = re.compile(r"^How to:\s*", re.I)
# the area's name in the interface (the sidebar's words)
UH_AREA = {"files": "Files", "agents": "Agents", "office": "Office|area", "tasks": "Tasks", "calendar": "Calendar"}
UH_SNIP = 160


def uh_title(s):
    return UH_TITLE.sub("", s["title"])


def uh_entry(s, lg):
    """One user's section in lg: {key, area, title, text, show, lang} (English when lg has no block for it)."""
    idx = hlp_index()
    t = idx["tr"].get(lg, {}).get(s["key"])
    text = t["text"] if t else hlp_user_text(idx["files"][s["fkey"]]["lines"], s)
    return {"key": s["key"], "area": s["user"], "title": t["title"] if t else uh_title(s), "text": text,
            "show": s.get("show") or "", "lang": lg if t else "en"}


def uh_sections():
    """The user's sections in the order of HELP_AREAS, then of the files."""
    idx = hlp_index()
    secs = [s for f in idx["files"].values() if not f["operator"] for s in f["sections"] if s.get("user")]
    rank = {a: i for i, a in enumerate(HELP_AREAS)}
    return sorted(secs, key=lambda s: rank.get(s["user"], len(rank)))


def uh_snippet(text):
    p = re.sub(r"\s+", " ", md_plain(re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M))).strip()
    return p if len(p) <= UH_SNIP else p[:UH_SNIP - 1].rstrip() + "…"


@app.get("/api/help")
def uh_list():
    lg = lang()
    areas = {}
    for s in uh_sections():
        e = uh_entry(s, lg)
        a = areas.setdefault(s["user"], {"area": s["user"], "title": tr(UH_AREA.get(s["user"], s["user"].title()), lg=lg), "sections": []})
        a["sections"].append({"key": e["key"], "title": e["title"], "show": e["show"]})
    return jsonify(lang=lg, areas=list(areas.values()))


@app.get("/api/help/section")
def uh_section():
    key = (request.args.get("key") or "").strip()
    s = hlp_index()["by_key"].get(key) if len(key) <= 200 else None
    if s is None or not s.get("user") or hlp_index()["files"][s["fkey"]]["operator"]:
        return jsonify(error=tr("Not found")), 404
    return jsonify(uh_entry(s, lang()))


def uh_search_web():
    """GET /api/search?kind=help: the user's sections for the words of q (in English or in the person's language)."""
    try:
        n = max(1, min(20, int(request.args.get("limit") or 8)))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit")) from None
    lg, by_key = lang(), hlp_index()["by_key"]
    out = []
    for h in hlp_search(srch_q(request.args), n, user_only=True):
        e = uh_entry(by_key[h["key"]], lg)
        out.append({"key": e["key"], "area": e["area"], "title": e["title"], "snippet": uh_snippet(e["text"]), "show": e["show"]})
    return {"data": out}


srch_register("help", web=uh_search_web)  # 2.1086.0 (#5820): the web side of the kind (helpdocs.py registers the API's side)
