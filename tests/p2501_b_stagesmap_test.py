#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.501.0 (#4016): tests/stages.py --touched gives core files, start files, translations and server files without a route a
small fixed set of suites instead of leaving them unmapped (330 einreihen checks ran only a sample because of them). Static, no
container. Invented texts only.
 - every suite of TOUCHED_FIXED exists and no group is bigger than about 10
 - schema.py, db.py, a migration fragment, app.css, a start style file, core.js, index.html, app.py and a translation map, without an
   UNMAPPED line, and without the whole run: only the set + the guards + what the set's suites need
 - a changed translation adds the suites that name the changed text; a text many suites name does not
 - a server module without a route takes the suites that name it, at most TOUCHED_HITS_MAX
 - a name only in a helper (nearly) every suite loads (tests/boot.js ...) does not pick the suites
 - 2.533.0 (#4332): a file that maps to too many suites takes the rarest-named ones (at most 10) instead of UNMAPPED
 - the CI basics and test helpers stay UNMAPPED (the CI's full run), the push stage still says full for all of them
 - a suite on tests/skip.txt stays out of the set"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(N, "..", "tools"))
from kt import FAILS, OKS, check  # noqa: E402
import stages  # noqa: E402

ROOT = os.path.dirname(N)
repo = stages.Repo(ROOT, os.path.join(N, "run_all.sh"))
KNOWN = set(repo.group_of)
for g, ss in stages.TOUCHED_FIXED.items():
    check(not (set(ss) - KNOWN), f"{g}: every suite exists: {sorted(set(ss) - KNOWN)}")
    check(len(ss) <= 11, f"{g}: a small set ({len(ss)})")

CORE = {"kalmido/core/schema.py": "db", "kalmido/core/db.py": "db", "kalmido/core/migrations.d/x4016.py": "db",
        "kalmido/core/i18nkeys.py": "i18n", "kalmido/core/config.py": "server_start", "kalmido/__init__.py": "server_start",
        "app.py": "server_start", "static/app.css": "css", "static/js/core.js": "client_start", "static/js/render.js": "client_start",
        "static/index.html": "client_start", "static/sw.js": "client_start", "static/i18n/de.json": "i18n"}
skip = repo.skipped()
for f, g in CORE.items():
    order, why, unm = stages.touched(repo, [f])
    check(unm == [], f"{f}: not unmapped: {unm}")
    want = {s for s in stages.TOUCHED_FIXED[g] if s not in skip}
    check(want <= set(order), f"{f}: its set {g}: missing {sorted(want - set(order))}")
    check(len(order) < 60, f"{f}: not the whole run: {len(order)} suites")
    check(any("(#4016)" in why[s] for s in want), f"{f}: --why names the set")

# what the push stage and the CI do stays: a core file means the full run there
for f in ("kalmido/core/schema.py", "static/app.css", "static/js/core.js", "kalmido/__init__.py"):
    check(stages.select(repo, [f])[0] == "full", f"{f}: the push stage still runs everything")
for f in ("Dockerfile", "tests/ff.js", "tests/kt.py", "tests/run_all.sh", "VERSION"):
    _, _, unm = stages.touched(repo, [f])
    check(len(unm) == 1 and unm[0].startswith(f + " ("), f"{f}: stays unmapped: {unm}")

# 2.533.0 (#4332): a file that is too broad takes the (at most TOUCHED_HITS_MAX) suites with the rarest hits instead of UNMAPPED
for f in ("kalmido/lists/projects.py", "kalmido/collab/comments.py", "kalmido/accounts/session.py", "static/js/settings.js"):
    if not os.path.exists(os.path.join(ROOT, f)):
        continue
    order, why, unm = stages.touched(repo, [f])
    own = {s for s, w in why.items() if "(#4332)" in w}
    check(unm == [], f"{f}: too broad but not unmapped any more: {unm}")
    check(1 <= len(own) <= stages.TOUCHED_HITS_MAX, f"{f}: the rarest-named suites, at most {stages.TOUCHED_HITS_MAX}: {len(own)}")
    check(own <= set(order), f"{f}: they run")

# the group of a stylesheet / module is only taken for the reason classify() gives
check(stages.touched_group("static/js/somemodule.js", "too broad: 80 suites") is None, "a client module that is too broad stays unmapped")
check(stages.touched_group("static/js/somemodule.js", "client module no suite names") == "client_start", "a client module no suite names")
check(stages.touched_group("kalmido/office/x.py", "server module without a route a suite names") == "server_start", "a server file without a route")
check(stages.touched_group("kalmido/office/x.py", "not mapped (inside the image or unknown)") is None, "other reasons stay unmapped")


def git(root, *a):
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com", *a], check=True, capture_output=True)


# a small tree: suites + a translation file in git, so the diff of a real commit is read
with tempfile.TemporaryDirectory() as tmp:
    for d in ("tests", "static/i18n", "kalmido/office", "tools"):
        os.makedirs(os.path.join(tmp, d))
    names = ["api", "i18n", "named_ui", "other_ui"] + [f"many{i}_ui" for i in range(20)]
    lines = []
    for i, n in enumerate(names):
        lines.append(("fresh; " if i == 0 else "       ") + f"run {n} node {n}.js")
    open(os.path.join(tmp, "tests", "suites.txt"), "w").write("\n".join(lines) + "\n")
    body = {"named_ui": "'Rechnung vierzehn'\n", "other_ui": "nothing\n"}
    for n in names:
        open(os.path.join(tmp, "tests", n + ".js"), "w").write(body.get(n, "'Breit gekannt'\n" if n.startswith("many") else "x\n"))
    open(os.path.join(tmp, "tests", "skip.txt"), "w").write("#\nother_ui 2999-01-01 #1 reason\n")
    open(os.path.join(tmp, "tests", "run_all.sh"), "w").write('eval "$LIST"\n')
    shutil.copy(os.path.join(N, "suites.py"), os.path.join(tmp, "tests", "suites.py"))
    de = os.path.join(tmp, "static", "i18n", "de.json")
    src = {"Invoice": "Rechnung vierzehn", "Wide": "Breit gekannt", "Gone": "Weg damit", "Same": "Gleich",
           "{0} match": ["Eine passt alt", "{0} passen alt"]}  # 2.521.0 (#4479): a plural text is a list of forms
    wr = lambda o: open(de, "w", encoding="utf-8").write("{\n" + ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in o.items()) + "\n}\n")  # noqa: E731
    wr(src)
    open(os.path.join(tmp, "kalmido", "office", "quiet.py"), "w").write("def quiet_helper_name():\n    return 1\n")
    open(os.path.join(tmp, "tests", "other_ui.js"), "w").write("quiet_helper_name\n")
    open(os.path.join(tmp, "tests", "named_ui.js"), "a").write("quiet_helper_name\n")
    # a module only tests/boot.js names: every suite loads boot.js, so that says nothing about any of them
    open(os.path.join(tmp, "tests", "boot.js"), "w").write("'widgetmod.js'\n")
    os.makedirs(os.path.join(tmp, "static", "js"))
    open(os.path.join(tmp, "static", "js", "widgetmod.js"), "w").write("// nothing else\n")
    for n in names:
        open(os.path.join(tmp, "tests", n + ".js"), "a").write("require('./boot')\n")
    git(tmp, "init", "-q")
    git(tmp, "add", ".")
    git(tmp, "commit", "-qm", "base")
    wr({**{k: v for k, v in src.items() if k != "Gone"}, "Invoice": "Rechnung fünfzehn", "Wide": "Breit bekannt", "{0} match": ["Eine passt neu", "{0} passen neu"]})
    git(tmp, "add", ".")
    git(tmp, "commit", "-qm", "change")
    r = stages.Repo(tmp, os.path.join(tmp, "tests", "run_all.sh"))
    t = stages.i18n_changed_texts("HEAD^", "HEAD", "static/i18n/de.json", tmp)
    check("Rechnung vierzehn" in t and "Rechnung fünfzehn" in t and "Gone" in t and "Gleich" not in t, f"the changed texts of a translation: {t}")
    check("{0} passen alt" in t and "{0} passen neu" in t, f"2.521.0 (#4479): a changed plural text counts with its forms, no crash: {t}")
    fixed = stages.touched_fixed(r, "static/i18n/de.json", "translations changed (not only added)", "HEAD^", "HEAD")
    check("named_ui" in fixed and "Rechnung" in fixed["named_ui"], f"the suite that names the changed text comes along: {fixed}")
    check(not any(s.startswith("many") for s in fixed), "a text more than TOUCHED_HITS_BROAD suites name brings none of them")
    check("i18n" in fixed and "fixed set" in fixed["i18n"], "and the fixed set of the translations")
    check("other_ui" not in fixed, "unrelated suite stays out")
    srv = stages.touched_fixed(r, "kalmido/office/quiet.py", "server module without a route a suite names")
    check("named_ui" in srv and "quiet_helper_name" in srv["named_ui"], f"a server module takes the suites naming its function: {srv}")
    check("other_ui" not in srv, f"a suite on skip.txt stays out even when it names it: {srv}")
    check("api" in srv, "and its fixed set")
    fx = stages.TOUCHED_FIXED["client_start"]
    stages.TOUCHED_FIXED["client_start"] = ("i18n",)
    order, why, unm = stages.touched(r, ["static/js/widgetmod.js"])
    stages.TOUCHED_FIXED["client_start"] = fx
    check(unm == [] and order == ["i18n"], f"named only by a helper every suite loads: the fixed set, not all suites: {order} {unm}")
    check(r.skipped() == {"other_ui"}, f"skip.txt read as run_all.sh does: {r.skipped()}")

# 2.553.0 (#4657): a too-broad file of tests/stages_areas.json takes the suites of its area instead of UNMAPPED
areas = json.load(open(os.path.join(N, "stages_areas.json"), encoding="utf-8"))
check(len(areas) >= 6, f"the area table is read: {len(areas)}")
for pat, ss in areas:
    check(not (set(ss) - KNOWN), f"area {pat}: every suite exists: {sorted(set(ss) - KNOWN)}")
for f in ("kalmido/sheets/core.py", "static/css/docs.css", "static/css/office.css", "static/css/settings.css",
          "kalmido/accounts/supportgrant.py", "kalmido/accounts/orginvite.py"):
    if not os.path.exists(os.path.join(ROOT, f)):
        continue
    order, why, unm = stages.touched(repo, [f])
    want = {s for pat, ss in areas if __import__("fnmatch").fnmatchcase(f, pat) for s in ss if s not in skip}
    check(unm == [], f"{f}: not unmapped: {unm}")
    check(want and want <= set(order), f"{f}: its area suites run: {sorted(want - set(order))}")
    check(any("(#4657)" in w for w in why.values()), f"{f}: --why names the area")
    check(len(order) < 40, f"{f}: not the whole run: {len(order)}")

p = subprocess.run([sys.executable, os.path.join(N, "stages.py"), "--touched", "kalmido/core/schema.py", "static/app.css", "static/i18n/de.json"],
                   capture_output=True, text=True, cwd=ROOT)
check(p.returncode == 0 and "UNMAPPED" not in p.stderr and " api" in " " + p.stdout, f"the command line: no UNMAPPED line: {p.stderr[-300:]}")

print(f"p2501_b_stagesmap: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
