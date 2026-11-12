"""2.1086.0 (#5860, decided 12.11.2026): "Show me" -- an agent that explains a way through the app (the help of #5819) puts a
button "Show me" under its chat message. A tap opens the view and highlights the control the person presses next (the
spotlight of the welcome tour, static/js/showme.js), step by step with "Next". The agent shows, the person changes: the app
only goes to the view and highlights, it never clicks, switches or saves anything.

The places come only from a fixed list of named places, docs/help-targets.json (key -> route + CSS selector + English
label): never a free selector or address from the model. An agent's message carries show = [{target, text?}] (API v1 POST
/api/v1/agent/chats/<uid>, MCP send_chat): every key is checked against the list (unknown = 400), text is the step's short
line (plain, at most SHOW_TEXT_MAX characters). The row keeps only the keys and texts (agent_chat.show_steps, JSONB); the app
gets each step with its route, selector and label of the list as it is now (a key no longer in the list is left out).
The help names the keys (help_overview show_targets, read_help show: the places a section marks with <!-- show: key -->).
"""
import json
import os
import re
import threading

from ..core.config import APP_DIR
from ..core.errors import BadInput
from ..core.i18n import N_, tr

SHOW_FILE = os.path.join(APP_DIR, "docs", "help-targets.json")  # the image: /app/docs (Dockerfile), a checkout: docs/
SHOW_MAX, SHOW_TEXT_MAX = 8, 300  # steps of one message, characters of one step's text
SHOW_KEY_RE = re.compile(r"[a-z][a-z0-9-]{0,30}(?:\.[a-z0-9][a-z0-9-]{0,40}){1,2}")
SHOW_MARK_RE = re.compile(r"<!--\s*show:\s*([a-z0-9.\-]{3,80})\s*-->")  # a help section's mark (#5820)
# the labels of docs/help-targets.json for the translation files (tests/p21072_c_show_test.py: every label_en is here)
SHOW_LABELS = (N_("Open the settings"), N_("Settings: Integrations"), N_("Settings: Agents"), N_("Documents: inboxes (scan inbox)"),
               N_("Add an agent"), N_("Settings of the agent"), N_("New quotation"), N_("New invoice"), N_("Add a task"),
               N_("New event"), N_("Upload files"))
_SHW = {"t": None}
_SHW_LOCK = threading.Lock()


def shw_targets():
    """The list of named places: {key: {route, sel, label_en}} (read once; a missing or broken file = no places)."""
    if _SHW["t"] is None:
        with _SHW_LOCK:
            if _SHW["t"] is None:
                try:
                    with open(SHOW_FILE, encoding="utf-8") as f:
                        raw = json.load(f).get("targets") or {}
                except (OSError, ValueError, AttributeError):
                    raw = {}
                _SHW["t"] = {k: {"route": v.get("route") or None, "sel": v["sel"], "label_en": v.get("label_en") or k}
                             for k, v in raw.items()
                             if isinstance(k, str) and SHOW_KEY_RE.fullmatch(k) and isinstance(v, dict) and isinstance(v.get("sel"), str)
                             and (v.get("route") is None or (isinstance(v["route"], str) and v["route"].startswith("#")))}
    return _SHW["t"]


def shw_list():
    """For the help overview: [{key, label}] -- what an agent may point at."""
    return [{"key": k, "label": v["label_en"]} for k, v in shw_targets().items()]


def shw_keys_in(text):
    """The places a help section marks (<!-- show: key -->), known keys only, in order, each once."""
    t, out = shw_targets(), []
    for k in SHOW_MARK_RE.findall(text or ""):
        if k in t and k not in out:
            out.append(k)
    return out


def shw_clean(v):
    """The field show of an agent's message -> the stored JSON text, or None. [{target, text?}] (also a list of keys, or the
    JSON text of either: a multipart form); 1..SHOW_MAX steps; every target a key of the list, else 400."""
    if v in (None, "", []):
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "show")) from None
    if not isinstance(v, list) or not 1 <= len(v) <= SHOW_MAX:
        raise BadInput(tr("Invalid value: {0}", "show"))
    t, out = shw_targets(), []
    for i, x in enumerate(v):
        if isinstance(x, str):
            x = {"target": x}
        if not isinstance(x, dict) or set(x) - {"target", "text"}:
            raise BadInput(tr("Invalid value: {0}", f"show[{i}]"))
        k, txt = x.get("target"), x.get("text")
        if not isinstance(k, str) or k not in t:
            raise BadInput(tr("Invalid value: {0}", f"show[{i}].target"))
        if txt is not None and not isinstance(txt, str):
            raise BadInput(tr("Invalid value: {0}", f"show[{i}].text"))
        txt = re.sub(r"\s+", " ", txt or "").strip()
        if len(txt) > SHOW_TEXT_MAX:
            raise BadInput(tr("Invalid value: {0}", f"show[{i}].text"))
        out.append({"target": k, **({"text": txt} if txt else {})})
    return json.dumps(out, ensure_ascii=False)


def shw_out(v, api=False):
    """The stored steps for the answer: the API gets [{target, text?}] back, the app each step with route, sel and label
    of the list as it is now and its label in the person's language (unknown keys left out). None without."""
    try:
        steps = json.loads(v) if isinstance(v, str) and v else v
    except ValueError:
        return None
    if not isinstance(steps, list) or not steps:
        return None
    if api:
        return steps
    t = shw_targets()
    out = [{**s, "route": t[s["target"]]["route"], "sel": t[s["target"]]["sel"], "label": tr(t[s["target"]]["label_en"])}
           for s in steps if isinstance(s, dict) and s.get("target") in t]
    return out or None
