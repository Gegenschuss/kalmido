#!/usr/bin/env python3
# kalmido-suite: after=launcher_parity nodata
"""2.625.0 part B (#3661, agents #1524): the answer to a permission question travels over the runner's local connection
(PermChannel), never through a file in the state folder. Without a server: a stub API, the real hook as a subprocess.
 - allow / deny of the person reach the hook over its own connection
 - a file an agent writes into the state folder (the old answer / posted files) gives NO allow (regression: the old code
   read <state>/perm/<id>.ans and allowed)
 - an agent process that takes over the socket address and answers allow with the right key: denied (wrong process)
 - a wrong key, an old key of an earlier run: denied, no question in the chat
 - no answer in time, the connection gone: denied
 - the answer must carry the hook's one-time nonce
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import check, until  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "..", "mcp", "agent_run.py")
os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "z" * 30)
for k in [k for k in os.environ if k.startswith("KALMIDO_PERM_")]:
    del os.environ[k]
spec = importlib.util.spec_from_file_location("agent_run", RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
TMP = tempfile.mkdtemp(prefix="kalmido-p2625b-")


class StubApi:
    def __init__(self):
        self.posts, self.perms, self.withdrawn = [], [], []

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None):
        self.posts.append({"uid": uid, "body": body})
        return {"id": 100 + len(self.posts)}

    def perm_question(self, uid, body, timeout_s):
        self.perms.append((uid, body))
        return {"id": 900 + len(self.perms)}

    def withdraw(self, uid, mid, why=""):
        self.withdrawn.append((uid, mid, why))
        return True


def runner(name):
    r = ar.Runner(["claude"], os.path.join(TMP, name))
    r.api = r.usage.api = StubApi()
    r.agent = {"owner_id": 7}
    r.ensure_perm_watch()
    return r


def hook_env(r, **kw):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KALMIDO_PERM_")}
    env.update({k: v for k, v in r.child_env(7, None).items() if k.startswith("KALMIDO_PERM_") or k == "KALMIDO_RUN_LABEL"})
    env.update(KALMIDO_PERM_TIMEOUT="30", **kw)
    return env


def hook(env):
    p = subprocess.Popen([sys.executable, RUNNER, "--perm-hook"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    p.stdin.write('{"tool_name": "Bash", "tool_input": {"command": "make deploy"}}')
    p.stdin.close()
    return p


def result(p):
    out = p.stdout.read()
    p.wait(60)
    return json.loads(out)["hookSpecificOutput"]["decision"]


def asked(r, n):
    return bool(until(lambda: len(r.api.perms) >= n, 30, 0.1))


r = runner("a")
check(r.perm_chan is not None and os.path.exists(r.perm_chan.address), "the runner opened its local connection")
if os.name != "nt":
    check(os.stat(r.perm_chan.dir).st_mode & 0o777 == 0o700, "the socket lives in a 0700 folder")
    check(not r.perm_chan.address.startswith(r.state_dir), "the socket is not in the state folder")
env = hook_env(r)
check(env["KALMIDO_PERM_PID"] == str(os.getpid()) and len(env["KALMIDO_PERM_KEY"]) == 64 and "KALMIDO_PERM_DIR" not in env,
      "the hook gets address, runner process and a 256-bit key, no folder")

# allow and deny over the connection
p = hook(env)
check(asked(r, 1), "the request became a question in the chat")
mid = next(iter(r.state.data["perms"]))
r.intercept([{"event": "chat_choice", "data": {"message_id": int(mid), "permission": True, "approval": "approved", "choice_ids": ["allow"]}}])
check(result(p)["behavior"] == "allow", "allow reaches the hook over its connection")
p = hook(env)
check(asked(r, 2), "second question")
mid = next(iter(r.state.data["perms"]))
r.intercept([{"event": "chat_choice", "data": {"message_id": int(mid), "permission": True, "approval": "rejected", "choice_ids": ["deny"]}}])
d = result(p)
check(d["behavior"] == "deny" and "denied by the person" in d["message"], f"deny reaches the hook: {d}")

# regression (#3661): the agent writes the old answer files into the state folder -> no allow
p = hook(dict(env, KALMIDO_PERM_TIMEOUT="3"))
check(asked(r, 3), "third question (the agent tries to answer it itself)")
pdir = os.path.join(r.state_dir, "perm")
os.makedirs(pdir, exist_ok=True)
names = set(os.listdir(pdir)) | {q["pid"] for q in r.state.data["perms"].values()}
for x in names or {"x"}:
    base = x.split(".")[0]
    for ext, txt in ((".ans", "allow"), (".posted", "901")):
        with open(os.path.join(pdir, base + ext), "w") as f:
            f.write(txt)
d = result(p)
check(d["behavior"] == "deny" and "in time" in d["message"], f"a file of the agent in the state folder gives no allow: {d}")
for q in r.state.data["perms"].values():
    q["at"] = 0
r.perm_expire()

# an agent process takes over the socket address and answers allow with the right key -> denied (wrong process)
r2 = runner("b")
env2 = hook_env(r2)
if os.name != "nt":
    fake = os.path.join(TMP, "fake_runner.py")
    with open(fake, "w") as f:
        f.write(r'''import json, os, sys
from multiprocessing import connection as mpc
addr, key = sys.argv[1], bytes.fromhex(sys.argv[2])
os.unlink(addr)
lst = mpc.Listener(addr, "AF_UNIX")
print("ready", flush=True)
c = lst.accept()
try:
    mpc.deliver_challenge(c, key)
    mpc.answer_challenge(c, key)
    rq = json.loads(c.recv_bytes(1 << 20))
    c.send_bytes(json.dumps({"nonce": rq["nonce"], "decision": "allow"}).encode())
except Exception:
    pass
''')
    fp = subprocess.Popen([sys.executable, fake, env2["KALMIDO_PERM_SOCK"], env2["KALMIDO_PERM_KEY"]], stdout=subprocess.PIPE, text=True)
    check(fp.stdout.readline().strip() == "ready", "the fake runner holds the address")
    d = result(hook(env2))
    check(d["behavior"] == "deny" and "another process" in d["message"], f"another process at the address: denied: {d}")
    fp.kill()
    fp.wait(10)
check(not r2.api.perms, "no question was asked for it")

# a wrong key and an old key of an earlier run -> denied, nobody asked
r3 = runner("c")
env3 = hook_env(r3)
d = result(hook(dict(env3, KALMIDO_PERM_KEY="ab" * 32)))
check(d["behavior"] == "deny", f"a guessed key: denied: {d}")
old = env3["KALMIDO_PERM_KEY"]
env3b = hook_env(r3)  # the next run: a new key
check(env3b["KALMIDO_PERM_KEY"] != old, "a new key per run")
d = result(hook(dict(env3b, KALMIDO_PERM_KEY=old)))
check(d["behavior"] == "deny", f"the key of an earlier run: denied: {d}")
check(not r3.api.perms, "neither became a question in the chat")
d = result(hook(dict(env3b, KALMIDO_PERM_PID=str(os.getpid() + 1))))
check(d["behavior"] == "deny" and "another process" in d["message"], f"the runner process is not the one named: denied: {d}")

# the connection goes before the person answers -> denied
p = hook(env3b)
check(asked(r3, 1), "a question")
q = next(iter(r3.state.data["perms"].values()))
with r3.perm_lk:
    c = r3.perm_conns.pop(q["pid"])
c.close()
d = result(p)
check(d["behavior"] == "deny" and "stopped" in d["message"], f"the connection gone: denied: {d}")

# an answer without the hook's nonce counts as no
p = hook(env3b)
check(asked(r3, 2), "another question")
q = [x for x in r3.state.data["perms"].values() if x["pid"] in r3.perm_conns][0]
with r3.perm_lk:
    c = r3.perm_conns.pop(q["pid"])
c.send_bytes(json.dumps({"nonce": "0" * 32, "decision": "allow"}).encode())
c.close()
d = result(p)
check(d["behavior"] == "deny", f"an allow for another nonce: denied: {d}")

# 2.625 (Fable review of #3661): silent connections (no handshake) must not use up the slots and block later questions;
# regression: before, PERM_MAX_OPEN silent connections kept every slot and each real hook was refused at once
if os.name != "nt":
    import socket as _so
    ar.PERM_HS_S = 1
    r5 = runner("e")
    env5 = hook_env(r5)
    silent = []
    for _ in range(ar.PERM_MAX_OPEN + 2):
        s5 = _so.socket(_so.AF_UNIX, _so.SOCK_STREAM)
        s5.connect(r5.perm_chan.address)
        silent.append(s5)
    check(until(lambda: r5.perm_chan.busy >= ar.PERM_MAX_OPEN, 10, 0.05), "all slots taken by silent connections")
    check(until(lambda: r5.perm_chan.busy == 0, 15, 0.1), f"silent connections give their slot back: {r5.perm_chan.busy}")
    p = hook(env5)
    check(asked(r5, 1), "after silent connections a real hook is asked again")
    mid = next(iter(r5.state.data["perms"]))
    r5.intercept([{"event": "chat_choice", "data": {"message_id": int(mid), "permission": True, "approval": "approved", "choice_ids": ["allow"]}}])
    check(result(p)["behavior"] == "allow", "and gets its answer")
    for s5 in silent:
        s5.close()
    r5.perm_chan.close()
    ar.PERM_HS_S = 10

# no runner at all
env4 = {k: v for k, v in os.environ.items() if not k.startswith("KALMIDO_PERM_")}
d = result(hook(env4))
check(d["behavior"] == "deny" and "not running" in d["message"], f"no channel: denied at once: {d}")
for x in (r, r2, r3):
    x.perm_chan.close()
check(not os.path.exists(r.perm_chan.dir or "/nonexistent"), "closing removes the socket folder")

sys.exit(kt.done("p2625_b_perm"))
