#!/usr/bin/env python3
"""Menu paths in the docs and the app's own texts name the settings that really exist (2.512.0, #4175): the menu was rebuilt
in 2.364 and about 85 lines of docs and several hints in the app kept the old one for months, because nothing compared them.

    python3 tools/check_menupaths.py [-v] [FILE ...]      exit 1 on a path to a menu that does not exist

The sections come from SET_SECS (static/js/setcore.js), the sub-tabs of Organisation and Server from ADM_SUBS
(static/js/settings.js). A path "Settings > X > Y" must start with a section; under Organisation and Server the next step must
be one of its sub-tabs. Translations follow from the English key: its section must appear under the translated section name.
Default files: top-level *.md, docs/*.md, mcp/*.md, examples/**/*.md, .env.example, install scripts, docker-compose.yml, the texts
in static/js and the tr() / N_() texts of kalmido/. Changelogs keep their old names (they tell what was true then), code comments
are not read. Other apps have their own "Settings > ..." (iOS, Outlook, Todoist): FOREIGN names them.
Standard library only (the CI lint job runs plain Python).
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# README.md joins the check since 2.545.0 (#4384): package 2.512 brought its menu paths in; CHANGELOG.md keeps the old names as history
SKIP = {"CHANGELOG.md"}
SEP = r"\s*(?:>|›|→|->)\s*"
DECOR = r"[*_`\"“”„]*"
PATH = re.compile(r"\bSettings" + DECOR + SEP + DECOR + r"(?=(?P<tail>[^\n]*(?:\n[^\n]*)?))")
BARE = re.compile(r"\b(?:Administration|Workspaces)" + DECOR + SEP + DECOR + r"[A-Z]")
# Words of the old menu that are no path, but were copied from it
OLD_WORDS = ("Users may create their own agents",)
# Paths of other apps, as they appear in the guides (whole-line patterns; what they match is not read)
FOREIGN = [re.compile(p) for p in (
    r"System" + DECOR + r"\s+Settings" + DECOR + SEP + r"[^\n]*",
    r"(?:Office|finance|Documents)" + DECOR + SEP + DECOR + r"Settings" + DECOR + SEP + r"[^\n]*",  # the settings tab of an area
    r"(?:Karakeep|calendar\.google\.com|Gmail|Google Calendar|Outlook|Notion|Obsidian|Thunderbird|Trello|Asana|Nextcloud|Jira|Linear|GitHub|GitLab|Forgejo|Gitea|Paperless(?:-ngx)?|Authentik|authentik|Keycloak|Bitwarden|Hetzner|Apple|Docker Desktop)\b[^\n.;|]*?Settings" + DECOR + SEP + r"[^\n]*",
    r"Settings" + SEP + DECOR + r"(?:Apps|Internet Accounts|your calendar|See all settings|Privacy & Security|Synchronization|Calendar" + SEP + r"Shared calendars|Workspace" + SEP + r"Export all workspace|Security & access" + SEP + r"Personal API keys|API keys|Backups" + DECOR + r"\s*(?:\(a ZIP|" + SEP + r"download a backup)|Export" + SEP + r"Markdown & CSV)[^\n]*",
    r"Administration › OIDC Clients[^\n]*",
)]


def source(name):
    with open(os.path.join(ROOT, *name.split("/")), encoding="utf-8") as f:
        return f.read()


def menu():
    """-> ({section label: section key}, {section key: [sub-tab labels]}) from the app's own tables."""
    sets = re.search(r"const SET_SECS = (\[.*?\]\]);", source("static/js/setcore.js"), re.S)
    subs = re.search(r"const ADM_SUBS = (\[.*?\]\]);", source("static/js/settings.js"), re.S)
    if not sets or not subs:
        raise SystemExit("check_menupaths: SET_SECS or ADM_SUBS not found: this check must follow them")
    secs = {lab.split("|")[0]: key for key, lab in re.findall(r"\['(\w+)', '[\w-]+', N_\('([^']+)'\)\]", sets.group(1))}
    tabs = {}
    for lab, area in re.findall(r"N_\('([^']+)'\), '(\w+)'\]", subs.group(1)):
        tabs.setdefault(area, []).append(lab.split("|")[0])
    return secs, tabs


COMMENT = re.compile(r"/\*.*?\*/", re.S)


def blank(text, pat):
    return pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def check_text(text, secs, tabs):
    """-> [(line, the wrong path)] in a text."""
    for pat in FOREIGN:
        text = blank(text, pat)
    bad = []
    for m in PATH.finditer(text):
        tail = re.sub(r"\s+", " ", m.group("tail"))
        sec = next((s for s in sorted(secs, key=len, reverse=True) if tail.startswith(s)), None)
        short = re.split(r"[*`\"”)(;,:.|]", tail)[0].strip()[:60]
        line = text.count("\n", 0, m.start()) + 1
        if sec is None:
            bad.append((line, "Settings > " + short))
            continue
        rest = re.match(DECOR + SEP + DECOR + r"(.*)", tail[len(sec):])
        allowed = tabs.get(secs[sec])
        # 2.616.0 (#4933): a sub-tab counts as a whole word - the tab Backup (#4827) let the old plural Backups pass as a prefix
        if rest and allowed and not any(re.match(re.escape(t) + r"(?!\w)", rest.group(1)) for t in allowed):
            bad.append((line, "Settings > " + short))
    bad += [(text.count("\n", 0, m.start()) + 1, " ".join(m.group(0).split())) for m in BARE.finditer(text)]
    for w in OLD_WORDS:
        bad += [(text.count("\n", 0, m.start()) + 1, w) for m in re.finditer(re.escape(w), text)]
    return bad


def no_comment(line, py):
    """The line without a comment of its own (a line that is a comment, or one after the code)."""
    s = line.lstrip()
    if s.startswith("#" if py else ("//", "/*", "*")):
        return ""
    return re.sub(r"\s+#\s[^\"']*$" if py else r"\s//\s.*$", "", line)


def app_text(path):
    """What a person can read of a code file: JS without comments, Python only the lines with tr() / N_()."""
    py = path.endswith(".py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not py:
        text = blank(text, COMMENT)
    lines = [no_comment(x, py) for x in text.split("\n")]
    if py:
        lines = [x if re.search(r"\b(?:tr|N_|trn|Nn_)\(", x) else "" for x in lines]
    return "\n".join(lines)


def files():
    docs = [os.path.join(ROOT, x) for x in (".env.example", "install.sh", "install.ps1", "docker-compose.yml")]
    for pat in ("*.md", "docs/*.md", "mcp/*.md", "examples/**/*.md"):
        docs += [p for p in glob.glob(os.path.join(ROOT, pat), recursive=True) if os.path.basename(p) not in SKIP]
    code = glob.glob(os.path.join(ROOT, "static", "js", "*.js")) + glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)
    return [p for p in docs if os.path.exists(p)], code


def check_i18n(secs, tabs):
    """Translations: the section of an English key under the translated name of that section. -> [(file, key, why)]"""
    bad = []
    for path in sorted(glob.glob(os.path.join(ROOT, "static", "i18n", "*.json"))):
        with open(path, encoding="utf-8") as f:
            tr = json.load(f)
        word = tr.get("Settings") or "Settings"
        for key, val in tr.items():
            if not isinstance(val, (str, list)) or "Settings" not in key:
                continue
            if check_text(key, secs, tabs):
                bad.append((path, key, "the English path is wrong"))
                continue
            clean = key
            for pat in FOREIGN:
                clean = blank(clean, pat)
            vals = val if isinstance(val, list) else [val]
            for m in PATH.finditer(clean):
                tail = re.sub(r"\s+", " ", m.group("tail"))
                sec = next((s for s in sorted(secs, key=len, reverse=True) if tail.startswith(s)), None)
                want = re.sub(r"\|.*", "", tr.get(sec + "|settings") or tr.get(sec) or sec) if sec else None
                if want and not any(re.search(re.escape(word) + DECOR + SEP + DECOR + re.escape(want), v) for v in vals if isinstance(v, str)):
                    bad.append((path, key, f"expected {word} > {want}"))
    return bad


def main(argv):
    verbose = "-v" in argv
    args = [a for a in argv if a != "-v"]
    secs, tabs = menu()
    bad = []
    if args:
        docs, code = args, []
    else:
        docs, code = files()
    for p in docs:
        with open(p, encoding="utf-8") as f:
            bad += [(p, n, w) for n, w in check_text(f.read(), secs, tabs)]
    for p in code:
        bad += [(p, n, w) for n, w in check_text(app_text(p), secs, tabs)]
    n_i18n = 0
    if not args:
        for p, k, why in check_i18n(secs, tabs):
            bad.append((p, 0, f"{k[:90]!r}: {why}"))
            n_i18n += 1
    for p, n, w in bad:
        print(f"{os.path.relpath(p, ROOT)}:{n}: {w}")
    if verbose or bad:
        print(f"check_menupaths: {len(docs) + len(code)} files, {len(secs)} sections, {len(bad)} wrong path(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
