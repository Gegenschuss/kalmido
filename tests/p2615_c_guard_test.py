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
usage: p2615_c_guard_test.py"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys

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
