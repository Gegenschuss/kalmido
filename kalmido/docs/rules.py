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


def clean_rule(r):
    """A rule dict from user input (raises RuleError with a reason)."""
    kind = r.get("kind") or "any"
    if kind not in KINDS:
        raise RuleError("kind")
    match = str(r.get("match") or "").strip()[:PATTERN_MAX]
    if not match:
        raise RuleError("empty")
    if kind == "regex":
        why = check_pattern(match)
        if why:
            raise RuleError(why)
    out = {"kind": kind, "match": match}
    for k in ("sender", "type", "folder"):
        v = str(r.get(k) or "").strip()[:120]
        if v:
            out[k] = v
    tags = r.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in tags.split(",")]
    tags = [str(t).strip()[:60] for t in tags if str(t).strip()][:10]
    if tags:
        out["tags"] = tags
    if not any(k in out for k in ("sender", "type", "folder", "tags")):
        raise RuleError("nothing")
    return out


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
print(json.dumps([bool(re.search(p, d["t"], re.I)) for p in d["p"]]))
"""


def regex_hits(patterns, text):
    """[bool] per pattern, run in a limited child process; a timeout = no hit for any of them."""
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
    wset = None
    regex = [r for r in rules if r.get("kind") == "regex" and not check_pattern(r.get("match"))]
    rhits = dict(zip((id(r) for r in regex), regex_hits([r["match"] for r in regex], text)))
    out = []
    for r in rules:
        kind, m = r.get("kind"), r.get("match") or ""
        if kind == "regex":
            ok = rhits.get(id(r), False)
        elif kind == "exact":
            ok = bool(fold(m).strip()) and re.search(r"(?<!\w)" + re.escape(fold(m).strip()) + r"(?!\w)", ftext) is not None
        elif kind == "fuzzy":
            fwords = fwords if fwords is not None else words(text)
            ok = _fuzzy_in(m, fwords)
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
