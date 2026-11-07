"""2.48.0 (#1111): rules that sort documents ("contains word X -> sender Y, type Z, tag T, folder F").

Pure Python (standard library only). Kinds of match:
  any    -- one of the words occurs (whole words, case-insensitive)
  all    -- every word occurs
  exact  -- the exact phrase occurs
  regex  -- a regular expression; checked when it is saved (length, no nested repetition, no back references) and run
            in a short-lived child process with a time and memory limit, so a pathological pattern can only kill that
            process (catastrophic backtracking)
  fuzzy  -- the phrase occurs with small typos (OCR errors), similarity >= FUZZY
Per feature (sender / type / tags / folder) the workspace chooses the level: "rules" (only rules), "learn" (rules
first, then the learning classifier), "agent" (nothing automatic: left open for a connected agent) or "off"."""
import difflib
import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata

KINDS = ("any", "all", "exact", "regex", "fuzzy")
LEVELS = ("rules", "learn", "agent", "off")
FEATURES = ("sender", "type", "tags", "folder")
DEFAULT_LEVEL = "learn"
PATTERN_MAX = 200        # characters of a regex
TEXT_MAX = 20_000        # characters of a document a regex looks at
REGEX_SECONDS = 2        # wall clock for all regex rules of one document
FUZZY = 0.85
FUZZY_WORDS = 4000       # words of a document the fuzzy match looks at


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("ß", "ss")


def words(s):
    return re.findall(r"\w+", fold(s))


class RuleError(ValueError):
    pass


def _walk(parsed, in_repeat=False):
    """Refuse nested repetition, repetition of alternatives and back references (the backtracking traps)."""
    import re._parser as sp  # noqa: PLC0415 -- the standard library's own regex parser
    import re._constants as sc  # noqa: PLC0415
    for op, av in parsed:
        if op in (sc.GROUPREF, sc.GROUPREF_EXISTS):
            raise RuleError("backref")
        if op in (sc.MAX_REPEAT, sc.MIN_REPEAT, getattr(sc, "POSSESSIVE_REPEAT", None)):
            lo, hi, sub = av
            if in_repeat and hi > 1:
                raise RuleError("nested")
            _walk(sub, in_repeat or hi > 1)
        elif op == sc.SUBPATTERN:
            _walk(av[-1], in_repeat)
        elif op == sc.BRANCH:
            if in_repeat:
                raise RuleError("nested")
            for b in av[1]:
                _walk(b, in_repeat)
        elif op in (sc.ASSERT, sc.ASSERT_NOT):
            _walk(av[1], in_repeat)
        elif isinstance(av, sp.SubPattern):
            _walk(av, in_repeat)


def check_pattern(pat):
    """None when the regex is acceptable, else a reason: 'long' | 'invalid' | 'nested' | 'backref'."""
    if not pat or len(pat) > PATTERN_MAX:
        return "long"
    try:
        re.compile(pat)
        import re._parser as sp  # noqa: PLC0415
        _walk(sp.parse(pat, re.I))
    except RuleError as e:
        return str(e)
    except (re.error, RecursionError, OverflowError, ValueError):
        return "invalid"
    return None


def clean_rule(r, extra=False, share=False):
    """A rule dict from user input (raises RuleError with a reason).
    2.581.0 (#4803): a rule is a flow ("Ablauf"): a trigger (received = as before, changed, scheduled), filters (the words
    as before, now optional when another filter or trigger is given; source, file name, tag / type / sender) and actions
    (set sender / type / folder / tags as before; remove tags, set custom fields, make a task; with extra=True also notify
    people and call a webhook -- those need the checks of docs/flows.py fl_clean against the database, so an import of
    rules (Paperless, organisation import) never brings them in). Old rules read as flows with trigger received.
    2.635.0 (#4856): the action "share" ([{user_id | group_id, role: view | edit}], the shares of the shared core) only with
    extra=True (fl_clean checks the targets) or share=True (the Paperless import, its targets checked by docs/flows.py
    fl_share_pool)."""
    kind = r.get("kind") or "any"
    if kind not in KINDS:
        raise RuleError("kind")
    match = str(r.get("match") or "").strip()[:PATTERN_MAX]
    trig = r.get("trigger") or "received"
    if trig not in TRIGGERS:
        raise RuleError("trigger")
    out = {}
    flt = _clean_filters(r)
    if not match and trig == "received" and not flt:
        raise RuleError("empty")
    if match:
        if kind == "regex":
            why = check_pattern(match)
            if why:
                raise RuleError(why)
        out = {"kind": kind, "match": match}
        if r.get("case") is True and kind != "fuzzy":  # 2.69.0 B (#1847): case-sensitive (Paperless-ngx "is_insensitive" off)
            out["case"] = True
    for k in ("sender", "type", "folder"):
        v = str(r.get(k) or "").strip()[:120]
        if v:
            out[k] = v
    tags = _names(r.get("tags"))
    if tags:
        out["tags"] = tags
    if trig != "received":
        out["trigger"] = trig
    if trig == "changed":
        on = r.get("on") or []
        on = [x for x in ON_KINDS if x in (on if isinstance(on, list) else [on])]
        if on:
            out["on"] = on
    if trig == "scheduled":
        d = r.get("days")
        if not isinstance(d, int) or isinstance(d, bool):
            d = int(d) if str(d or "").strip().lstrip("-").isdigit() else None
        if d is None or not 0 <= d <= DAYS_MAX:
            raise RuleError("days")
        frm = r.get("from") or "date"
        if frm not in SCHED_FROM:
            raise RuleError("from")
        out["days"], out["from"] = d, frm
    out.update(flt)
    name = str(r.get("name") or "").strip()[:120]
    if name:
        out["name"] = name
    if r.get("off") is True:
        out["off"] = True
    untag = _names(r.get("untag"))
    if untag:
        out["untag"] = untag
    fields = r.get("fields")
    if isinstance(fields, dict):
        fl = {str(k).strip()[:60]: (None if v is None else str(v)[:500]) for k, v in list(fields.items())[:FIELDS_MAX] if str(k).strip()}
        if fl:
            out["fields"] = fl
    task = r.get("task")
    if task:
        t = task if isinstance(task, dict) else {}
        tv = {"title": str(t.get("title") or "").strip()[:200]}
        to = t.get("to")
        if isinstance(to, int) and not isinstance(to, bool) and to > 0:
            tv["to"] = to
        if t.get("due") is True:
            tv["due"] = True
        out["task"] = tv
    if extra:
        ppl = r.get("notify") or []
        ppl = sorted({int(x) for x in (ppl if isinstance(ppl, list) else []) if isinstance(x, int) and not isinstance(x, bool) and x > 0})[:NOTIFY_MAX]
        if ppl:
            out["notify"] = ppl
        url = str(r.get("webhook") or "").strip()
        if url:
            out["webhook"] = url[:2000]
            if r.get("hook_secret"):
                out["hook_secret"] = str(r["hook_secret"])[:100]
    if extra or share:  # 2.635.0 (#4856): the shape only; who may get a share: docs/flows.py fl_clean / fl_share_pool
        sh = _clean_share(r.get("share"))
        if sh:
            out["share"] = sh
    if not any(k in out for k in ACTIONS):
        raise RuleError("nothing")
    return out


TRIGGERS = ("received", "changed", "scheduled")   # 2.581.0 (#4803)
ON_KINDS = ("tags", "type", "sender", "field")   # what a change must touch for a "changed" flow (none chosen = any of them)
SCHED_FROM = ("date", "due", "added")            # X days after the document's date / due date / the day it came in
DAYS_MAX = 3650
FIELDS_MAX = 5
NOTIFY_MAX = 20
ACTIONS = ("sender", "type", "folder", "tags", "untag", "fields", "task", "notify", "webhook", "share")  # 2.635.0 (#4856): + share
SHARE_MAX = 10  # 2.635.0 (#4856): people / groups one flow shares a document with


def _clean_share(v):
    """2.635.0 (#4856): [{user_id | group_id: int, role: view | edit}] -- one entry per target (the higher role wins)."""
    seen = {}
    for x in v if isinstance(v, list) else []:
        if not isinstance(x, dict):
            raise RuleError("share")
        key = next((k for k in ("user_id", "group_id") if k in x), None)
        t, role = x.get(key) if key else None, x.get("role") or "view"
        if key is None or isinstance(t, bool) or not isinstance(t, int) or t <= 0 or role not in ("view", "edit"):
            raise RuleError("share")
        if seen.get((key, t)) != "edit":
            seen[(key, t)] = role
    if len(seen) > SHARE_MAX:
        raise RuleError("share")
    return [{k: t, "role": role} for (k, t), role in sorted(seen.items())]
# the source filter: a group -> the values of doc_meta.source (docs/ingest.py docs_ingest callers); "mailbox" for the own
# mailbox of a workspace (#4804) when it marks its documents apart from the document address
SOURCES = {"upload": ("upload", "share", "api", "folder", "office", "payonline"), "mail": ("mail", "mailbox"), "scan": ("scan",),
           "fetcher": ("abholer",), "import": ("paperless", "import")}


def _names(v):
    if isinstance(v, str):
        v = v.split(",")
    return [str(t).strip()[:60] for t in (v if isinstance(v, list) else []) if str(t).strip()][:10]


def _clean_filters(r):
    """The filters of a flow besides the words: {sources, filename, has_tags, has_type, has_sender} (only those given)."""
    out = {}
    src = r.get("sources") or []
    src = [x for x in SOURCES if x in (src if isinstance(src, list) else [src])]
    if src:
        out["sources"] = src
    fn = str(r.get("filename") or "").strip()[:PATTERN_MAX]
    if fn:
        out["filename"] = fn
    ht = _names(r.get("has_tags"))
    if ht:
        out["has_tags"] = ht
    for k in ("has_type", "has_sender"):
        v = str(r.get(k) or "").strip()[:120]
        if v:
            out[k] = v
    return out


def trigger_of(r):
    return r.get("trigger") if r.get("trigger") in TRIGGERS else "received"


def flow_pass(r, facts):
    """2.581.0 (#4803): do the filters of flow r besides the words hold for a document? facts = {source, name, tags: set of
    folded tag names, type, sender: folded names or ''}. An old rule has none of them: always true. A flow switched off: false."""
    if r.get("off"):
        return False
    if r.get("sources") and not any(facts.get("source") in SOURCES.get(g, ()) for g in r["sources"]):
        return False
    if r.get("filename") and not fnmatch.fnmatchcase(fold(facts.get("name") or ""), fold(r["filename"])):
        return False
    if r.get("has_tags") and not any(fold(t) in facts.get("tags", set()) for t in r["has_tags"]):  # one of them (like Paperless-ngx)
        return False
    for k, f in (("has_type", "type"), ("has_sender", "sender")):
        if r.get(k) and fold(r[k]) != (facts.get(f) or ""):
            return False
    return True


def _fuzzy_in(phrase, text_words):
    p = words(phrase)
    if not p:
        return False
    n = len(p)
    target = " ".join(p)
    tw = text_words[:FUZZY_WORDS]
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(target)
    for i in range(0, max(1, len(tw) - n + 1)):
        cand = " ".join(tw[i:i + n])
        if abs(len(cand) - len(target)) > max(2, len(target) // 4):
            continue
        sm.set_seq1(cand)
        if sm.real_quick_ratio() >= FUZZY and sm.quick_ratio() >= FUZZY and sm.ratio() >= FUZZY:
            return True
    return False


REGEX_WORKER = r"""
import json, re, resource, sys
for k, v in ((resource.RLIMIT_AS, 256 << 20), (resource.RLIMIT_CPU, int(sys.argv[1])), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
d = json.loads(sys.stdin.read())
print(json.dumps([bool(re.search(p[0], d["t"], 0 if p[1] else re.I)) if isinstance(p, list) else bool(re.search(p, d["t"], re.I))
                  for p in d["p"]]))
"""


def regex_hits(patterns, text):
    """[bool] per pattern (a text, or [text, case-sensitive]), run in a limited child process; a timeout = no hit for any of them."""
    if not patterns:
        return []
    try:
        p = subprocess.run([sys.executable, "-I", "-c", REGEX_WORKER, str(REGEX_SECONDS)],
                           input=json.dumps({"p": patterns, "t": (text or "")[:TEXT_MAX]}).encode(), capture_output=True,
                           timeout=REGEX_SECONDS, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        out = json.loads(p.stdout or b"null") if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        out = None
    return out if isinstance(out, list) and len(out) == len(patterns) else [False] * len(patterns)


def matches(rules, text):
    """The rules (in their order) whose condition holds for text."""
    ftext = fold(text)
    fwords = None
    wset = cset = None
    regex = [r for r in rules if r.get("kind") == "regex" and not check_pattern(r.get("match"))]
    rhits = dict(zip((id(r) for r in regex), regex_hits([[r["match"], True] if r.get("case") else r["match"] for r in regex], text)))
    out = []
    for r in rules:
        kind, m = r.get("kind"), r.get("match") or ""
        if not m.strip():  # 2.581.0 (#4803): a flow without words (other filters only) holds for every text
            ok = True
        elif kind == "regex":
            ok = rhits.get(id(r), False)
        elif kind == "exact" and r.get("case"):  # 2.69.0 B (#1847)
            ok = bool(m.strip()) and re.search(r"(?<!\w)" + re.escape(m.strip()) + r"(?!\w)", text or "") is not None
        elif kind == "exact":
            ok = bool(fold(m).strip()) and re.search(r"(?<!\w)" + re.escape(fold(m).strip()) + r"(?!\w)", ftext) is not None
        elif kind == "fuzzy":
            fwords = fwords if fwords is not None else words(text)
            ok = _fuzzy_in(m, fwords)
        elif r.get("case"):  # 2.69.0 B (#1847): any / all with the words as written
            cset = cset if cset is not None else set(re.findall(r"\w+", text or ""))
            want = re.findall(r"\w+", m)
            ok = bool(want) and (all(w in cset for w in want) if kind == "all" else any(w in cset for w in want))
        else:
            if wset is None:
                wset = set(words(text))
            want = words(m)
            ok = bool(want) and (all(w in wset for w in want) if kind == "all" else any(w in wset for w in want))
        if ok:
            out.append(r)
    return out


def apply_rules(rules, text):
    """{'sender': .., 'type': .., 'folder': .., 'tags': [..]} from the matching rules: the first rule that sets a
    single-value feature wins, tags of all matching rules add up."""
    out = {"tags": []}
    for r in matches(rules, text):
        for k in ("sender", "type", "folder"):
            if r.get(k) and k not in out:
                out[k] = r[k]
        for t in r.get("tags") or []:
            if t not in out["tags"]:
                out["tags"].append(t)
    return out


def levels(raw):
    """The level per feature from a stored dict (unknown / missing -> DEFAULT_LEVEL)."""
    raw = raw if isinstance(raw, dict) else {}
    return {f: (raw.get(f) if raw.get(f) in LEVELS else DEFAULT_LEVEL) for f in FEATURES}
