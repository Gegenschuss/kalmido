#!/usr/bin/env python3
# kalmido-suite: nodata
"""#4006 (GitHub step 3): tools/pr_lint.py on a temporary repository - a commit without #<task> is red, the release tooling's
own subjects pass, an app change without changelog.d is red, a private spot (pattern from the environment) and a private
commit address are red, a one-way step is a note (red only with --strict). No container, standard library only."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(os.path.dirname(HERE), "tools", "pr_lint.py")
sys.path.insert(0, HERE)
from kt import FAILS, OKS, check as kcheck  # noqa: E402


def sh(repo, *a, env=None):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True, env=env).stdout.strip()


def commit(repo, files, subject, mail="noreply@kalmido.com"):
    for path, text in files.items():
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
    sh(repo, "add", "-A")
    env = dict(os.environ, GIT_AUTHOR_NAME="Kalmido", GIT_AUTHOR_EMAIL=mail, GIT_COMMITTER_NAME="Kalmido",
               GIT_COMMITTER_EMAIL=mail)
    sh(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", subject, env=env)
    return sh(repo, "rev-parse", "HEAD")


def lint(repo, base, *extra, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("KALMIDO_PRIVACY") and k not in ("KALMIDO_ALLOWED_EMAILS", "GITHUB_ACTIONS")}
    e.update(env or {})
    p = subprocess.run([sys.executable, LINT, "--repo", repo, "--base", base, *extra], capture_output=True, text=True, env=e)
    return p.returncode, p.stdout + p.stderr


def ok(name, cond, out=""):
    kcheck(cond, name if cond else f"{name}: {out[-1500:]}")


def main():
    with tempfile.TemporaryDirectory() as repo:
        sh(repo, "init", "-q", "-b", "main")
        base = commit(repo, {"README.md": "x\n"}, "start #1")

        # subjects
        commit(repo, {"tools/a.py": "a = 1\n"}, "#4006: a tool")
        commit(repo, {"tools/b.py": "b = 1\n"}, "2.593.0: version + cache v1 (Live-Zug: 2.593)")
        commit(repo, {"tools/c.py": "c = 1\n"}, "changelog fragment for package 2.593 (job/3079)")
        rc, out = lint(repo, base, "--only", "subject")
        ok("subjects with #id / of the release tooling pass", rc == 0, out)
        commit(repo, {"tools/d.py": "d = 1\n"}, "fix a thing")
        rc, out = lint(repo, base, "--only", "subject")
        ok("a subject without #id is red", rc == 1 and "fix a thing" in out, out)

        # changelog part
        b2 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"kalmido/x.py": "x = 1\n"}, "#4006: app change")
        rc, out = lint(repo, b2, "--only", "changelog")
        ok("app code without changelog.d is red", rc == 1 and "changelog" in out, out)
        commit(repo, {"changelog.d/3079.md": "Package 2.593.0 (x).\n"}, "#4006: fragment")
        rc, out = lint(repo, b2, "--only", "changelog")
        ok("app code with changelog.d passes", rc == 0, out)

        # privacy: the pattern comes from the environment (the CI secret), never from the repo
        b3 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"docs/n.md": "see host secrethost.example.lan\n"}, "#4006: doc")
        rc, out = lint(repo, b3, "--only", "privacy")
        ok("without the secret the line scan is skipped (notice)", rc == 0 and "not set" in out, out)
        rc, out = lint(repo, b3, "--only", "privacy", env={"KALMIDO_PRIVACY_DENY": r"secrethost"})
        ok("a private spot is red, the line is not printed", rc == 1 and "docs/n.md" in out and "secrethost" not in out, out)
        rc, out = lint(repo, b3, "--only", "privacy", env={"KALMIDO_PRIVACY_DENY": r"secrethost", "KALMIDO_PRIVACY_ALLOW": r"secrethost\.example\.lan"})
        ok("an allowed spot passes", rc == 0, out)
        b4 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"docs/m.md": "ok\n"}, "#4006: doc 2", mail="someone@private.example")
        rc, out = lint(repo, b4, "--only", "privacy")
        ok("a private commit address is red", rc == 1 and "address not allowed" in out and "someone@" not in out, out)
        rc, out = lint(repo, b4, "--only", "privacy", env={"KALMIDO_ALLOWED_EMAILS": "someone@private.example"})
        ok("an address of KALMIDO_ALLOWED_EMAILS passes", rc == 0, out)

        # review F8: a file name with an umlaut, an added line that reads "++ b/...", an empty file, a merge commit's address
        b6 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"docs/Übersicht.md": "secrethost\n"}, "#4006: umlaut")
        rc, out = lint(repo, b6, "--only", "privacy", env={"KALMIDO_PRIVACY_DENY": r"secrethost"})
        ok("F8: a file with an umlaut in its name is scanned", rc == 1 and "bersicht.md" in out, out)
        b7 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"docs/a.md": "++ b/docs/elsewhere.md\nsecrethost\n"}, "#4006: tricky line")
        rc, out = lint(repo, b7, "--only", "privacy", env={"KALMIDO_PRIVACY_DENY": r"secrethost"})
        ok("F8: an added line '++ b/x' does not move the next lines to another file", rc == 1 and "docs/a.md: private" in out and "elsewhere" not in out, out)
        b8 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"docs/secrethost-notes.md": ""}, "#4006: empty file")
        rc, out = lint(repo, b8, "--only", "privacy", env={"KALMIDO_PRIVACY_DENY": r"secrethost"})
        ok("F8: an empty file is checked by its name", rc == 1 and "file name" in out, out)
        b9 = sh(repo, "rev-parse", "HEAD")
        sh(repo, "checkout", "-q", "-b", "side")
        commit(repo, {"docs/side.md": "x\n"}, "#4006: side")
        sh(repo, "checkout", "-q", "main")
        commit(repo, {"docs/main2.md": "y\n"}, "#4006: main")
        menv = dict(os.environ, GIT_AUTHOR_NAME="X", GIT_AUTHOR_EMAIL="merger@private.example", GIT_COMMITTER_NAME="X",
                    GIT_COMMITTER_EMAIL="merger@private.example")
        sh(repo, "-c", "core.hooksPath=/dev/null", "merge", "-q", "--no-ff", "-m", "#4006: merge", "side", env=menv)
        rc, out = lint(repo, b9, "--only", "privacy")
        ok("F8: the address of a merge commit is checked", rc == 1 and "address not allowed" in out, out)
        sh(repo, "reset", "-q", "--hard", b9)

        # one-way rules: a note, red only with --strict
        b5 = sh(repo, "rev-parse", "HEAD")
        commit(repo, {"kalmido/core/migrations.d/t.py": 'MIGRATIONS = [\n    ("t", "x", "DELETE FROM t"),\n]\n'}, "#4006: migration")
        rc, out = lint(repo, b5, "--only", "oneway")
        ok("a deleting migration step is a note", rc == 0 and "migration step deletes data" in out, out)
        rc, out = lint(repo, b5, "--only", "oneway", "--strict")
        ok("... and red with --strict", rc == 1, out)
        rc, out = lint(repo, b4, "--only", "oneway", "--head", b5)
        ok("no one-way step: no note", rc == 0 and "one-way step(s)" not in out, out)

        # tests/stages.py: a merge queue entry runs the push stage against the queue's base commit
        import stages  # noqa: E402
        old = {k: os.environ.get(k) for k in ("GITHUB_EVENT_NAME", "CI_BASE_SHA", "CI_MESSAGE")}
        try:
            os.environ.update(GITHUB_EVENT_NAME="merge_group", CI_BASE_SHA="0123abc", CI_MESSAGE="#4006: x")
            st = stages.ci_base()
            ok("stages: merge_group = push stage against CI_BASE_SHA", st[0] is None and st[2] == "0123abc", str(st))
            os.environ["CI_BASE_SHA"] = ""
            st = stages.ci_base()
            ok("stages: merge_group without a base = full run", st[0] == "full", str(st))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        rc, out = lint(repo, "no-such-ref")
        ok("an unknown base is exit 2", rc == 2, out)
    print(f"p2593_l_prlint: {OKS[0]} ok, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
