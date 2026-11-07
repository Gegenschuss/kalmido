#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.615.0 C (#3758): the reference starter refuses dangerous commands with a PreToolUse hook (mcp/agent_run.py
--guard-hook), whatever the allow list and the permission mode say. Pure Python, no container, no server:
 - a table of refused command lines (force-push in every spelling, deleting / moving tags, docker ... prune, reboot /
   shutdown) and of allowed ones (an ordinary git push, git tag without -d, docker ps, the words in a commit message or an
   echo text)
 - the per-run settings carry the hook as PreToolUse / Bash, also without the permission relay; KALMIDO_BLOCK_DANGEROUS=0
   leaves it out
 - the hook's answer is Claude Code's PreToolUse format (deny + reason); an allowed command or another tool: no output
 - the hook's own failure refuses only a command that names a guarded command (fail closed for those, open for the rest)
 - 2.615.0 E (#3758, Fable review): each confirmed finding as a case (substitutions inside the words, jobs get the hook,
   quoted search text, git commit -am, wrapper options with values, git -c aliases / remote.*.push, very long input)
usage: p2615_c_guard_test.py"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time

from kt import check, done  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "..", "mcp", "agent_run.py")
spec = importlib.util.spec_from_file_location("agent_run_guard", RUN)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)

REFUSED = [
    "git push -f",
    "git push --force origin main",
    "git push origin main --force",
    "git push --force-with-lease",
    "git push --force-with-lease=main:abc123 origin main",
    "git push -uf origin main",
    "git push origin +main",
    "git push origin +refs/heads/main:refs/heads/main",
    "git push --mirror backup",
    "git push origin --delete v1.0",
    "git push origin -d feature",
    "git push origin :refs/tags/v1.0",
    "git push origin :v1.0",
    "git -C /tmp/repo push -f",
    "git -c user.name=x push --force",
    "/usr/bin/git push -f",
    "git tag -d v1.0",
    "git tag --delete v1.0",
    "git tag -f v1.0 HEAD",
    "git tag -fa v1.0 -m moved",
    "git update-ref -d refs/tags/v1.0",
    "docker system prune -af",
    "docker image prune",
    "docker volume prune -f",
    "docker container prune",
    "docker builder prune --all",
    "docker buildx prune",
    "podman system prune",
    "reboot",
    "sudo reboot",
    "shutdown -r now",
    "shutdown -h +5",
    "systemctl reboot",
    "systemctl poweroff",
    "systemctl start reboot.target",
    "poweroff",
    "init 6",
    # chains, substitutions, wrappers, shells
    "cd repo && git push -f",
    "make test; reboot",
    "false || git push --force",
    "git status | git push -f",
    "true & git tag -d v1",
    "echo ok\ngit push -f",
    "x=$(git push -f)",
    "echo \"$(git push -f)\"",
    "echo `git push -f`",
    "(cd repo; git push -f)",
    "{ git push -f; }",
    "if true; then git push -f; fi",
    "sh -c \"git push -f\"",
    "bash -c 'cd x && docker system prune -f'",
    "bash -c reboot",
    "eval \"git push -f\"",
    "ssh build-host reboot",
    "ssh build-host 'sudo reboot'",
    "ssh build-host git push -f",
    "sudo -u root reboot",
    "env GIT_TRACE=1 git push -f",
    "env -u HOME git push --force",
    "FOO=1 git push -f",
    "timeout 60 git push -f",
    "nice -n 5 docker system prune",
    "nohup reboot &",
    "xargs git push -f",
    "echo 'git push -f' | sh",
    "bash <<EOF\ngit push -f\nEOF",
    "ssh host <<'EOF'\nreboot\nEOF",
    "cat <<EOF | sh\ngit tag -d v1\nEOF",
    "g\\it push -f",
    "\"git\" \"push\" \"-f\"",
    "python3 -c \"import os; os.system('git push -f')\"",
    "git push -f \"unbalanced",
    "alias gp='git push -f'",
    "C:/Windows/System32/shutdown.exe /r /t 0",
    "Restart-Computer",
]

ALLOWED = [
    "git push",
    "git push origin main",
    "git push -u origin feature",
    "git push --tags",
    "git push origin v1.0",
    "git push --dry-run origin main",
    "git push -o ci.skip origin main",
    "git tag v1.0",
    "git tag -a v1.0 -m release",
    "git tag -l",
    "git tag --list 'v1.*'",
    "git status",
    "git log --oneline -5",
    "git fetch --prune",
    "git remote prune origin",
    "git branch -d done-feature",
    "git commit -m \"docs: explain why reboot and git push -f are refused\"",
    "git commit -m \"$(cat <<'EOF'\nRefuse docker system prune and reboot\n\ngit push --force is refused too\nEOF\n)\"",
    "git commit -F - <<EOF\nmention git push -f\nEOF",
    "docker ps",
    "docker compose up -d",
    "docker images",
    "docker run --rm alpine echo prune",
    "echo reboot",
    "echo \"please reboot later\"",
    "printf 'git push -f is refused\\n'",
    "echo 'git push -f' > notes.txt",
    "grep -n reboot docs/AGENT-SECURITY.md",
    "systemctl status kalmido",
    "systemctl --user restart kalmido-agent",
    "ls -la",
    "python3 tools/i18n_check.py",
    "npm test",
    "",
]

for c in REFUSED:
    why = ar.guard_reason(c)
    check(bool(why) and why.startswith(ar.GUARD_NO), f"refused: {c!r} -> {why!r}")
for c in ALLOWED:
    why = ar.guard_reason(c)
    check(why is None, f"allowed: {c!r} -> {why!r}")
check("force" in ar.guard_reason("git push -f") and "tag" in ar.guard_reason("git tag -d v1")
      and "prune" in ar.guard_reason("docker image prune") and "shutting down" in ar.guard_reason("reboot"),
      "each refusal names what was refused")

# ---- 2.615.0 E (#3758): the findings of the Fable review, each with its case (without the fix every one of them is wrong)
REFUSED_E = [
    # 1: $( ) / backticks in the middle of the words: one word of the outer command, its text checked on its own
    "git push origin $(git branch --show-current) --force",
    "git push origin `git branch --show-current` --force",
    "git push origin $(cat .b) -f",
    "git push origin HEAD:$(git branch --show-current) --force-with-lease",
    "git -C $(pwd) push -f",
    "git tag $(cat v) -d",
    "docker $(echo system) prune",
    "$(which git) push -f",
    "$(echo reboot)",
    "diff <(git push -f) x",
    "git commit -am \"$(git push -f)\"",
    "echo \"$(echo git push -f)\" | sh",
    "sh -c \"$(cat <<EOF\ngit push -f\nEOF\n)\"",
    # 3: code that runs a command stays refused (awk system(), sed e flag, interpreters)
    "awk 'BEGIN{system(\"reboot\")}'",
    "awk 'BEGIN{print \"reboot\" | \"sh\"}'",
    "sed 's/x/reboot/e' f",
    "perl -e 'system(\"reboot\")'",
    "python3 -c \"import subprocess; subprocess.run(['git', 'push', '-f'])\"",
    "echo git push -f | sh",
    # 5: the program after a wrapper's options (with values), command lines of wrappers
    "sudo -u root -g wheel git push -f",
    "timeout -s KILL 60 git push -f",
    "ssh -p 22 -i key host git push -f",
    "xargs -n 1 -I {} git push -f",
    "su -c reboot",
    "su root -c 'git push -f'",
    "env -S 'git push -f'",
    "watch -n 5 git push -f",
    "eval git push -f",
    "bash -lc reboot",
    "sudo -E bash -c 'docker system prune -af'",
    "nice -n 5 timeout 9 sudo git push -f",
    "busybox reboot",
    "cmd /c shutdown /r",
    "pwsh -NoProfile -Command Restart-Computer",
    "powershell -ExecutionPolicy Bypass Restart-Computer",
    "systemctl -H host reboot",
    "sudo systemctl start reboot.target",
    "sudo systemctl isolate poweroff.target",
    # 6: git settings that turn into a force-push / tag change
    "git -c alias.p='push -f' p",
    "git -c remote.origin.push=+main:main push",
    "git -c alias.x='!reboot' x",
    "git config alias.p 'push -f'",
    "git config --global alias.t 'tag -d'",
    "git config remote.origin.push +main:main",
    # 8: very long input with unbalanced quotes: not taken apart, refused because it names a guarded command
    "git push -f \"" + "a " * 200000,
    # 2.615.0 (#3758, Fable re-check): su USER -c ONEWORD, sed address + e, git search followed by a real command
    "su root -c reboot", "su - root -c 'reboot'", "su -l root -c reboot", "runuser root -c reboot", "su root --command=reboot",
    "sed '1e reboot' f", "sed -e '1e reboot' f", "git grep x; git push -f", "git log -S x && reboot",
]
ALLOWED_E = [
    # 3: search / text tools: their quoted words are text
    "grep -rn 'git push -f' docs/",
    "grep -n \"git push --force\" mcp/agent_run.py",
    "rg 'docker system prune' docs/",
    "sed -n '/reboot/p' log",
    "awk 'BEGIN{system(\"echo hi\")}'",
    "jq '.reboot' x.json",
    "test -f reboot",
    "python3 -c \"import subprocess; subprocess.run(['git', 'status'])\"",
    # 4: git commit -am / -qm / -sm / -anm, git tag -am: the next word is the message
    "git commit -am 'reboot handling'",
    "git commit -qm 'reboot'",
    "git commit -sm \"git push -f is refused\"",
    "git commit -anm 'x reboot y'",
    "git tag -am 'reboot release' v2",
    "git commit -m \"$(cat <<'EOF'\nDon't reboot\nEOF\n)\"",
    # 5: words after a wrapper are no programs, a pattern / path is no program
    "find . -name '*.sh' | xargs grep -l reboot",
    "ssh host grep reboot /var/log/syslog",
    "sudo systemctl status halt",
    "sudo cat /sbin/reboot",
    "awk '/reboot/ {print}' file",
    "sudo ls /etc/init 0",
    "sudo -u www systemctl restart nginx",
    "bash -c 'git status'",
    "cmd /c dir",
    # 1: an ordinary substitution
    "git push origin $(git branch --show-current)",
    "head -n 5 <(git log)",
    "$(which python3) script.py 0",
    # 6: harmless git settings
    "git -c alias.co=checkout co main",
    "git config alias.st status",
    "git -c remote.origin.push=refs/heads/main:refs/heads/main push",
    # 2.615.0 (#3758, Fable re-check): searching with git is text
    "git grep 'git push -f'", "git grep -n 'systemctl reboot' -- docs", "git log -S 'docker system prune'",
    "git log --grep 'git push -f'", "git -C x log --grep 'reboot now'", "su root -c 'ls'", "sed 's/a/e/' f",
]
for c in REFUSED_E:
    t0 = time.time()
    why = ar.guard_reason(c)
    check(bool(why) and why.startswith(ar.GUARD_NO), f"E refused: {c[:100]!r} -> {why!r}")
    check(time.time() - t0 < 10, f"E in time: {c[:60]!r} {time.time() - t0:.1f} s")
for c in ALLOWED_E:
    why = ar.guard_reason(c)
    check(why is None, f"E allowed: {c!r} -> {why!r}")
# 8: a long line (over GUARD_MAX) with unbalanced quotes is answered at once, also when it names nothing guarded
for c, refused in (("git push \"" + "x " * 420000, True), ("echo \"" + "x " * 420000, False)):
    t0 = time.time()
    why = ar.guard_reason(c)
    check(bool(why) == refused and time.time() - t0 < 5, f"long input ({len(c)} bytes): refused {refused} in {time.time() - t0:.1f} s")
# Fable re-check: deeply nested substitutions are answered in time (past GUARD_MAX_SUBST only guard_suspicious)
for c, refused in (("$(" * 90000 + "reboot" + ")" * 90000, True), ("$(" * 90000 + "ls" + ")" * 90000, False)):
    t0 = time.time()
    why = ar.guard_reason(c)
    check(bool(why) == refused and time.time() - t0 < 5, f"deep substitutions: refused {refused} in {time.time() - t0:.1f} s")
# the whole table of C again: no form refused before passes now (REFUSED above runs on the fixed code too)
check(all(ar.guard_reason(c) for c in REFUSED), "every command line of the C table stays refused")

# 2: a job (agent_job.py) gets the guard as its own settings file; KALMIDO_BLOCK_DANGEROUS=0: none; never with its own --settings
JOB = os.path.join(HERE, "..", "mcp", "agent_job.py")
jspec = importlib.util.spec_from_file_location("agent_job_guard", JOB)
aj = importlib.util.module_from_spec(jspec)
jspec.loader.exec_module(aj)
jtmp = tempfile.mkdtemp(prefix="kalmido-p2615e-")
os.environ.pop("KALMIDO_BLOCK_DANGEROUS", None)
os.environ.pop("KALMIDO_AGENT_PROFILE", None)
base = ar.profile_args("claude", ["claude"])
extra = aj.job_settings(ar, {"cmd": ["claude"]}, base, jtmp)
jhs = json.load(open(extra[1], encoding="utf-8")) if extra[:1] == ["--settings"] else {}
check(extra[:1] == ["--settings"] and extra[1].startswith(jtmp) and "--guard-hook" in json.dumps(jhs.get("hooks", {}).get("PreToolUse"))
      and "PermissionRequest" not in jhs.get("hooks", {}), f"job: settings file in the job folder with the PreToolUse guard {extra} {jhs}")
check(aj.job_settings(ar, {"cmd": ["claude", "--settings", "x.json"]}, base + ["--settings", "x.json"], jtmp) == [],
      "job with its own --settings: none added")
check(aj.job_settings(ar, {"cmd": ["codex"]}, ["codex", "exec"], jtmp) == [], "job of another profile: none")
os.environ["KALMIDO_BLOCK_DANGEROUS"] = "0"
check(aj.job_settings(ar, {"cmd": ["claude"]}, base, jtmp) == [], "job with KALMIDO_BLOCK_DANGEROUS=0: no settings")
os.environ.pop("KALMIDO_BLOCK_DANGEROUS", None)
check(ar.hook_settings(True, usage=False)["hooks"].keys() >= {"PermissionRequest", "PreToolUse"}
      and ar.Runner.hook_settings(None)["hooks"].get("PreToolUse") == ar.hook_settings(False)["hooks"]["PreToolUse"],
      "hook_settings is a free function; the chat runs use the same one")


# the start command of a real job run: a fake claude records its arguments (no API: the calls fail quietly)
def job_run(block):
    sd = tempfile.mkdtemp(prefix="kalmido-p2615e-job-")
    binp = os.path.join(sd, "bin")
    os.makedirs(binp)
    fake = os.path.join(binp, "claude")
    rec = os.path.join(sd, "args.json")
    with open(fake, "w") as f:
        f.write("#!" + sys.executable + "\n" + "import json, sys\n"
                f"json.dump(sys.argv[1:], open({rec!r}, 'w'))\n"
                "sys.stdin.readline()\n"
                "print(json.dumps({'type': 'result', 'result': 'done', 'session_id': 's1'}), flush=True)\n")
    os.chmod(fake, 0o755)
    jd = os.path.join(sd, "jobs", "1")
    os.makedirs(jd)
    with open(os.path.join(jd, "brief.txt"), "w") as f:
        f.write("Do nothing.")
    with open(os.path.join(jd, "job.json"), "w") as f:
        json.dump({"id": 1, "title": "t", "cmd": [fake], "cwd": sd, "state": "queued", "timeout_s": 120}, f)
    env = dict(os.environ, KALMIDO_STATE_DIR=sd, KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "z" * 30,
               KALMIDO_BLOCK_DANGEROUS=block)
    env.pop("KALMIDO_AGENT_PROFILE", None)
    subprocess.run([sys.executable, JOB, "_run", "1"], env=env, capture_output=True, text=True, timeout=120)
    args = json.load(open(rec)) if os.path.exists(rec) else None
    hs = {}
    if args and "--settings" in args:
        hs = json.load(open(args[args.index("--settings") + 1], encoding="utf-8"))
    return args, hs


args, hs = job_run("1")
check(args is not None and "--settings" in args and "--guard-hook" in json.dumps((hs.get("hooks") or {}).get("PreToolUse")),
      f"a job's start command carries the settings with the PreToolUse guard: {args} {hs}")
args, hs = job_run("0")
check(args is not None and "--settings" not in args, f"KALMIDO_BLOCK_DANGEROUS=0: a job starts without the settings: {args}")


# ---- the per-run settings: PreToolUse / Bash, also without the permission relay; switched off with the variable
for relay in (True, False):
    os.environ.pop("KALMIDO_BLOCK_DANGEROUS", None)
    ar.PERM_RELAY = relay
    hs = ar.Runner.hook_settings(None)
    pre = hs["hooks"].get("PreToolUse") or []
    check(len(pre) == 1 and pre[0].get("matcher") == "Bash" and "--guard-hook" in pre[0]["hooks"][0]["command"]
          and pre[0]["hooks"][0]["type"] == "command", f"per-run settings carry the guard (relay {relay}): {pre}")
for off in ("0", " 0 "):
    os.environ["KALMIDO_BLOCK_DANGEROUS"] = off
    check("PreToolUse" not in ar.Runner.hook_settings(None)["hooks"], f"KALMIDO_BLOCK_DANGEROUS={off!r}: no guard")
os.environ["KALMIDO_BLOCK_DANGEROUS"] = "1"
check("PreToolUse" in ar.Runner.hook_settings(None)["hooks"], "KALMIDO_BLOCK_DANGEROUS=1: guard on")
os.environ.pop("KALMIDO_BLOCK_DANGEROUS", None)


# ---- the hook itself, as Claude Code starts it (stdin JSON -> stdout JSON)
def hook(payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    cp = subprocess.run([sys.executable, RUN, "--guard-hook"], input=data, capture_output=True, text=True, timeout=60)
    return cp.returncode, cp.stdout.strip()


rc, out = hook({"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}, "hook_event_name": "PreToolUse"})
ans = json.loads(out) if out else {}
hso = ans.get("hookSpecificOutput") or {}
check(rc == 0 and hso.get("hookEventName") == "PreToolUse" and hso.get("permissionDecision") == "deny"
      and "force" in hso.get("permissionDecisionReason", "") and "Do not try another way" in hso.get("permissionDecisionReason", ""),
      f"refused command: PreToolUse deny with the reason the agent reads {rc} {out[:300]}")
rc, out = hook({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
check(rc == 0 and out == "", f"allowed command: no output, the normal rules decide {rc} {out!r}")
rc, out = hook({"tool_name": "Write", "tool_input": {"file_path": "x", "content": "git push -f"}})
check(rc == 0 and out == "", f"another tool: no output {rc} {out!r}")
rc, out = hook('{"tool_name": "Bash", "tool_input": {"command": "git push -f"')  # broken JSON naming a guarded command
check(rc == 0 and json.loads(out or "{}").get("hookSpecificOutput", {}).get("permissionDecision") == "deny",
      f"unreadable input naming git: refused (fail closed) {rc} {out!r}")
rc, out = hook('{"tool_name": "Bash", "tool_input": {"command": "ls -la"')
check(rc == 0 and out == "", f"unreadable input naming nothing guarded: no output (fail open) {rc} {out!r}")


# ---- a failure inside the check: refuse only what looks dangerous
def boom(cmd, depth=0):
    raise RuntimeError("bug")


orig = ar.guard_reason
ar.guard_reason = boom
try:
    for cmd, refused in (("docker system prune -f", True), ("ls -la", False)):
        buf = io.StringIO()
        sys_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}))
        try:
            with contextlib.redirect_stdout(buf):
                rc = ar.guard_hook([])
        finally:
            sys.stdin = sys_stdin
        out = buf.getvalue().strip()
        dec = (json.loads(out).get("hookSpecificOutput") or {}).get("permissionDecision") if out else None
        check(rc == 0 and (dec == "deny") == refused, f"check failed on {cmd!r}: refused {refused} ({out[:200]!r})")
finally:
    ar.guard_reason = orig

sys.exit(done("p2615_c_guard"))
