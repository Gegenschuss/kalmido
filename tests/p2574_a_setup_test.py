#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.574.0 (#3759): the agent setup scripts speak de, en, es, fr, it, nl. Purely static (no server): reads static/agent/setup.sh
and static/agent/setup.ps1 and checks per language against English
 1. every key of English is there and not empty (a missing text would fall back to English at run time, but the table is complete)
 2. the placeholders (%s %b / {0} {1}) are the same, in the same order, as in English
 3. the escapes (\\n) are the same; no double quote / dollar sign / backtick in a sh text (it sits in echo "...")
 4. an option name (--dir ... / -Dir ...) quoted in English stays unchanged in the translation
 5. the language switch: sh and ps1 know all six; ains_lang in agentsetup.js passes all six
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import check  # noqa: E402  shared helpers (tests/kt.py)
R = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
def rd(*p): return open(os.path.join(R, *p), encoding="utf8").read()
LANGS = ["de", "en", "es", "fr", "it", "nl"]

sh = rd("static", "agent", "setup.sh"); ps = rd("static", "agent", "setup.ps1"); js = rd("static", "js", "agentsetup.js")
SH = {}
for l in LANGS:
    m = re.search(r'msg_%s\(\) \{\n  case "\$1" in\n(.*?)\n    \*\) ' % l, sh, re.S)
    check(m is not None, f"setup.sh has msg_{l}")
    SH[l] = {}
    if m:
        for line in m.group(1).split("\n"):
            mm = re.match(r'    (\w+)\) echo "(.*)" ;;$', line)
            check(mm is not None, f"setup.sh msg_{l}: line parses: {line[:50]}")
            if mm: SH[l][mm.group(1)] = mm.group(2)
PS = {}
for l in LANGS:
    m = re.search(r"\$Msg%s = @\{\n(.*?)\n\}" % l.capitalize(), ps, re.S)
    check(m is not None, f"setup.ps1 has $Msg{l.capitalize()}")
    PS[l] = {}
    if m:
        for line in m.group(1).split("\n"):
            mm = re.match(r"  (\w+) = '(.*)'$", line)
            check(mm is not None, f"setup.ps1 Msg{l}: line parses: {line[:50]}")
            if mm: PS[l][mm.group(1)] = mm.group(2).replace("''", "'")

def ph_sh(t): return re.findall(r"%[sb]", t)
def ph_ps(t): return re.findall(r"\{\d+\}", t)
def opts(t, prefix): return sorted(set(re.findall(r"(?<![\w-])" + prefix + r"[A-Za-z][\w-]*", t)))
def esc(t): return t.count("\\n")

for name, T, ph, pre in (("setup.sh", SH, ph_sh, "--"), ("setup.ps1", PS, ph_ps, "-")):
    en = T["en"]
    check(len(en) >= 50, f"{name}: English has its texts ({len(en)})")
    for l in LANGS:
        if l == "en": continue
        check(set(T[l]) == set(en), f"{name} {l}: same keys as English (missing {sorted(set(en) - set(T[l]))}, extra {sorted(set(T[l]) - set(en))})")
        for k, e in en.items():
            t = T[l].get(k)
            if t is None: continue
            check(t.strip() != "", f"{name} {l}.{k}: not empty")
            check(ph(t) == ph(e), f"{name} {l}.{k}: placeholders {ph(t)} vs English {ph(e)}")
            check(esc(t) == esc(e), f"{name} {l}.{k}: line breaks {esc(t)} vs English {esc(e)}")
            if name == "setup.sh": check(not re.search(r'["$`]', t.replace('\\"', "")), f"{name} {l}.{k}: no quote / dollar / backtick in an echo text")
            else: check("{" not in re.sub(r"\{\d+\}", "", t) and "}" not in re.sub(r"\{\d+\}", "", t), f"{name} {l}.{k}: no stray braces (-f format)")
        # an option named in English is named in the translation too (same spelling), the folder word may be translated
        for k, e in en.items():
            t = T[l].get(k)
            if t is None: continue
            eo = set(re.findall(r"(?<![\w-])--(?:dir|url|code|from|tool|no-autostart|allow-http|uninstall)\b", e)) if name == "setup.sh" else set(re.findall(r"(?<![\w-])-(?:Dir|Url|Code|From|Tool|NoAutostart|AllowHttp|Uninstall)\b", e))
            for o in eo:
                check(o in t, f"{name} {l}.{k}: names {o} like English")
    # shell/PowerShell commands in a text stay literal
    for l in LANGS:
        for k in ("claude", "codex"):
            for cmd in ("npm install -g @openai/codex", "codex login", "curl -fsSL https://claude.ai/install.sh | bash", "irm https://claude.ai/install.ps1 | iex"):
                if cmd in en.get(k, ""):
                    check(cmd in T[l].get(k, ""), f"{name} {l}.{k}: command '{cmd}' is kept")

# the language switch
check(re.search(r"case \"\$LANGC\" in de\|es\|fr\|it\|nl\) ;; \*\) LANGC=en ;; esac", sh) is not None, "setup.sh: the six languages are known, anything else = en")
check(re.search(r"msg\(\) \{ case \"\$LANGC\" in de\|es\|fr\|it\|nl\) \"msg_\$LANGC\" \"\$1\" && return 0 ;; esac; msg_en \"\$1\"; \}", sh) is not None, "setup.sh: msg() falls back to English")
check(all(f"'{l}' {{ $script:LangTab = $Msg{l.capitalize()} }}" in ps for l in ("de", "es", "fr", "it", "nl")), "setup.ps1: a table per language")
check("$MsgEn[$k]" in ps, "setup.ps1: M() falls back to English")
check("['de', 'es', 'fr', 'it', 'nl'].includes(l) ? l : 'en'" in js, "agentsetup.js: ains_lang passes the six languages")
sys.exit(kt.done("p2574_a_setup"))
