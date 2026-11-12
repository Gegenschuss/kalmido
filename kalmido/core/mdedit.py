"""2.1082.0 (#5830): change a Markdown text in a targeted way -- the shared building block of the agents' "send only the change".

Agents add to or rework one part of a long text (a knowledge page, a task's notes, a project's description) without reading
and sending the whole text. Two kinds, one function each, for every target (no copy per area):

  append            md_append(cur, text, under=None): the text at the end, or at the end of the section under a heading
                    (the first heading of that name); exactly one empty line before it (none in an empty text), an empty
                    line before the next heading; the text's trailing line break stays.
  replace_section   md_replace_section(cur, heading, text): everything below the heading up to the next heading of the same
                    or a higher level is replaced by text (the heading line itself stays); the heading must be there exactly
                    once, else nothing changes (MdHeadingError: heading_not_found | heading_ambiguous, with the headings).

Headings are ATX headings (# .. ######) outside code fences and outside a frontmatter block on top (as static/js/wkembed.js
wem_pgPart reads them); a heading is named by its text, case ignored, a leading "## " of the caller is ignored too.

The areas keep their own save (rights, the task's lock, a password-locked note, encryption, the version check, history /
undo): the routes read the text under the area's write lock, reckon the new text here and save it through the same function
as a whole write (wiki/wkv1.py wkv_append / wkv_replace_section, api/v1.py v1_task_notes_*, api/projects.py
v1_overview_*). md_edit_input checks a request's fields, md_heading_answer is the error answer of the token API.
"""
import re

from .errors import BadInput
from .i18n import tr

MDE_APPEND_MAX = 20000  # one added piece (a link, a paragraph); the whole text stays bound by its area's own limit
MDE_SECTION_MAX = 100000  # the new text of one section
MDE_HEAD_MAX = 300
MDE_HEADS_SHOWN = 100  # headings named in the error answer
MDE_HEAD_RX = re.compile(r"^\s{0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")  # "# C#" is "C#"; closing hashes go
MDE_FENCE_RX = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


class MdHeadingError(Exception):
    """The heading of a targeted change is not there (heading_not_found) or there more than once (heading_ambiguous)."""

    def __init__(self, code, heading, headings):
        super().__init__(code)
        self.code, self.heading, self.headings = code, heading, headings


def md_headings(lines):
    """[(line index, level, text)] of the Markdown headings of lines, code fences and a frontmatter block on top skipped."""
    out, fence = [], ""
    skip = 0
    if lines and lines[0].strip() == "---":  # the frontmatter block on top is no section (a "# comment" there)
        skip = next((k + 1 for k in range(1, len(lines)) if lines[k].strip() in ("---", "...")), 0)
    for i, x in enumerate(lines):
        if i < skip:
            continue
        f = MDE_FENCE_RX.match(x)
        if f:  # a fence closes only with its own character, at least as long, nothing after it
            if not fence:
                fence = f.group(1)
            elif f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not x.strip()[len(f.group(1)):].strip():
                fence = ""
            continue
        m = None if fence else MDE_HEAD_RX.match(x)
        if m:
            out.append((i, len(m.group(1)), (m.group(2) or "").strip()))
    return out


def md_heading_names(cur):
    """The headings' texts of cur (for an error answer: which headings there are)."""
    return [h[2] for h in md_headings((cur or "").split("\n"))][:MDE_HEADS_SHOWN]


def _want(name):
    """A heading as the caller names it -> the compared form ("## Plan" and "plan" name the same heading)."""
    m = MDE_HEAD_RX.match(name.strip())
    return ((m.group(2) or "") if m else name).strip().casefold()


def _hits(hs, name):
    want = _want(name)
    return [k for k, h in enumerate(hs) if h[2].casefold() == want]


def _piece(text):
    return text.replace("\r\n", "\n").strip("\n")


def md_append(cur, text, under=None):
    """cur with text added -> the new text, or None when the heading under is not there (module docstring)."""
    cur = cur or ""
    piece = _piece(text)
    if under is None:
        body = cur.rstrip("\r\n")
        return (body + "\n\n" + piece if body else piece) + ("\n" if cur.endswith("\n") else "")
    lines = cur.split("\n")
    hs = md_headings(lines)
    hit = _hits(hs, under)
    if not hit:
        return None
    at, lvl = hs[hit[0]][0], hs[hit[0]][1]
    end = next((h[0] for h in hs[hit[0] + 1:] if h[1] <= lvl), len(lines))
    last = end - 1
    while last > at and not lines[last].strip():
        last -= 1
    rest = lines[end:]
    tail = ([""] + rest) if rest else ([""] if end == len(lines) and cur.endswith("\n") else [])
    return "\n".join(lines[:last + 1] + ["", *piece.split("\n")] + tail)


def md_replace_section(cur, heading, text):
    """cur with the section below heading replaced by text -> the new text; MdHeadingError when the heading is not there
    or there more than once (nothing changes). An empty text empties the section (its heading stays)."""
    cur = cur or ""
    lines = cur.split("\n")
    hs = md_headings(lines)
    hit = _hits(hs, heading)
    if len(hit) != 1:
        raise MdHeadingError("heading_ambiguous" if hit else "heading_not_found", heading.strip(), [h[2] for h in hs][:MDE_HEADS_SHOWN])
    at, lvl = hs[hit[0]][0], hs[hit[0]][1]
    end = next((h[0] for h in hs[hit[0] + 1:] if h[1] <= lvl), len(lines))
    piece = _piece(text)
    out = lines[:at + 1] + (["", *piece.split("\n")] if piece.strip() else [])
    rest = lines[end:]
    if rest:
        out += [""] + rest
    elif cur.endswith("\n"):
        out.append("")
    return "\n".join(out)


def md_edit_input(b, mode):
    """The fields of a targeted change from request body b (checked) -> (text, heading or None).
    mode append: text (not empty, at most MDE_APPEND_MAX), under? (a heading); mode replace: heading, text (may be empty =
    the section emptied, at most MDE_SECTION_MAX)."""
    text = b.get("text")
    if not isinstance(text, str) or (mode == "append" and not text.strip()):
        raise BadInput(tr("Invalid value: {0}", "text"))
    cap = MDE_APPEND_MAX if mode == "append" else MDE_SECTION_MAX
    if len(text) > cap:
        raise BadInput(tr("Too long: {0} (at most {1} characters)", "text", cap))
    key = "under" if mode == "append" else "heading"
    head = b.get(key)
    if (head is not None or mode != "append") and (not isinstance(head, str) or not _want(head) or len(head) > MDE_HEAD_MAX):
        raise BadInput(tr("Invalid value: {0}", key))
    return text, head


def md_edit(cur, mode, text, heading):
    """The new text of a targeted change of cur (mode append / replace); MdHeadingError when the heading does not fit."""
    if mode == "append":
        new = md_append(cur, text, heading)
        if new is None:
            raise MdHeadingError("heading_not_found", heading.strip(), md_heading_names(cur))
        return new
    return md_replace_section(cur, heading, text)


def md_need_version(b):
    """Replacing a section needs the version the caller read, from everyone (not only agents as core/conflict.py
    need_version): expect_updated_at in the body or the header If-Match, else 400 version_required."""
    from flask import request
    from .conflict import VersionRequired
    if b.get("expect_updated_at") in (None, "") and not (request.headers.get("If-Match") or "").strip():
        raise VersionRequired(("expect_updated_at", "If-Match"))


def md_heading_answer(e, show=True):
    """The token API's answer to MdHeadingError e: 404 heading_not_found / 409 heading_ambiguous with the headings (show
    False = a caller that may not read the text: no headings)."""
    from ..api.common import v1_err
    msg = tr("No heading {0} in this text", e.heading) if e.code == "heading_not_found" else \
        tr("The heading {0} is there more than once: rename one or change the whole text", e.heading)
    return v1_err(404 if e.code == "heading_not_found" else 409, msg, name=e.code, headings=e.headings if show else [])


def md_spec_body(mode, version):
    """The OpenAPI body of a targeted change (mode append | replace); version = what expect_updated_at is."""
    if mode == "append":
        return {"type": "object", "required": ["text"], "additionalProperties": False, "properties": {
            "text": {"type": "string", "maxLength": MDE_APPEND_MAX, "description": "Markdown added with exactly one empty line before it"},
            "under": {"type": "string", "maxLength": MDE_HEAD_MAX, "description": "A heading (case ignored): the text goes to the end of "
                      "its section; not there = 404 heading_not_found with error.headings, nothing written"},
            "expect_updated_at": {"type": "string", "description": f"Optional: {version} you read; changed since = 409 with the current state"}}}
    return {"type": "object", "required": ["heading", "text", "expect_updated_at"], "additionalProperties": False, "properties": {
        "heading": {"type": "string", "maxLength": MDE_HEAD_MAX, "description": "The heading whose section is replaced (case ignored): "
                    "not there = 404 heading_not_found, more than once = 409 heading_ambiguous (both with error.headings)"},
        "text": {"type": "string", "maxLength": MDE_SECTION_MAX, "description": "The section's new Markdown (up to the next heading of "
                 "the same or a higher level; the heading line stays; empty = the section emptied)"},
        "expect_updated_at": {"type": "string", "description": f"Required ({version} you read, or the header If-Match): changed since "
                              "= 409 with the current state"}}}


def mdedit_spec(paths, op, ok, errs, ref, pid):
    """2.1082.0 (#5830): the OpenAPI entries of the targeted changes of a task's notes and a project's description (the
    knowledge page's are in wiki/wkv1.py). Scope "write" = tasks:write / structure by path (api/scopes.py SCOPE_RULES)."""
    tp, lp = pid(), pid("id", "List id (a project list)")
    same_t = "The same rights, lock (409), password-locked note (409) and history as PATCH /tasks/{id} notes; an encrypted list: 409 encrypted."
    same_l = "The same rights and history as PATCH /lists/{id}/overview."
    paths["/tasks/{id}/notes/append"] = {"post": op(
        "Add text to a task's notes without sending the whole notes (2.1082.0)", "Tasks", ok(ref("Task")) | errs("400", "403", "404", "409"),
        [tp], body=md_spec_body("append", "the task's updated_at"), scope="write", desc=same_t)}
    paths["/tasks/{id}/notes/replace-section"] = {"post": op(
        "Replace the part of a task's notes below one heading (2.1082.0)", "Tasks", ok(ref("Task")) | errs("400", "403", "404", "409"),
        [tp], body=md_spec_body("replace", "the task's updated_at"), scope="write", desc=same_t)}
    paths["/lists/{id}/overview/append"] = {"post": op(
        "Add text to a project's description without sending the whole description (2.1082.0)", "Lists",
        ok(ref("ProjectOverview")) | errs("400", "403", "404", "409"), [lp], body=md_spec_body("append", "description_at"),
        scope="write", desc=same_l)}
    paths["/lists/{id}/overview/replace-section"] = {"post": op(
        "Replace the part of a project's description below one heading (2.1082.0)", "Lists",
        ok(ref("ProjectOverview")) | errs("400", "403", "404", "409"), [lp], body=md_spec_body("replace", "description_at (\"\" when null)"),
        scope="write", desc=same_l)}
