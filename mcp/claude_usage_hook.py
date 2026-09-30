#!/usr/bin/env python3
"""Claude Code Stop hook: reports the model usage of a Claude Code session to Kalmido (POST /api/v1/agent/usage).

Python 3 standard library only. Claude Code runs it after every turn ("Stop" hook) and passes a JSON object on stdin with
`session_id` and `transcript_path` (the session's JSONL transcript). The hook sums the usage of the assistant messages that
were added since its last run in this session (a small state file per session remembers how far it got), one report per
model, and POSTs the numbers to Kalmido with the agent's token. Only numbers and ids leave the machine: model, input /
output / cache tokens, the optional cost, the task the agent works on and a short note ("claude-code <session>") -- never
prompt or answer text.

Configuration (environment, or an env file given as the first argument / with --env FILE, lines KEY=VALUE):
  KALMIDO_URL               base address of the instance, e.g. https://tasks.example.com
  KALMIDO_TOKEN             the agent's API token (abk_...)
  KALMIDO_USAGE_STATE_DIR   where the per-session state files go (default ~/.cache/kalmido-usage)
  KALMIDO_USAGE_PRICES      optional cost calculation: JSON {"<model prefix>": [input, output, cache_write, cache_read]}
                           in USD per million tokens, e.g. {"claude-sonnet-4": [3, 15, 3.75, 0.3]}. Without it no cost
                           is sent (Kalmido then shows tokens only). The longest matching prefix wins.
  KALMIDO_USAGE_TASK        optional fixed task id; otherwise the task of the agent's status (PUT /agent/status task_id)
                           is used while the agent is "working" or "waiting".

Wire it in .claude/settings.json (project) or ~/.claude/settings.json (user):
  {"hooks": {"Stop": [{"hooks": [{"type": "command",
     "command": "python3 /path/to/kalmido/mcp/claude_usage_hook.py /path/to/kalmido-agent.env", "timeout": 30}]}]}}

The hook never blocks Claude Code: it always exits 0 and only writes problems to stderr. When Kalmido cannot be reached the
state does not move on, so the next run reports the missed turns too. --dry-run prints the reports instead of sending them.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

VERSION = "2.1.1"
NOTE_MAX = 200
KEEP_IDS = 200  # message ids remembered per session (Claude Code writes one line per content block of a message)


def load_env(path):
    """KEY=VALUE lines (optional quotes, # comments) -> dict."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k] = v
    return out


def state_path(state_dir, session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")[:120]
    return os.path.join(state_dir, safe + ".json")


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict):
            return {"offset": int(s.get("offset", 0)), "ids": list(s.get("ids", []))[-KEEP_IDS:]}
    except (OSError, ValueError, TypeError):
        pass
    return {"offset": 0, "ids": []}


def save_state(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"offset": st["offset"], "ids": st["ids"][-KEEP_IDS:]}, f)
    os.replace(tmp, path)


def read_new(transcript, st):
    """Usage of the assistant messages after st["offset"] -> ({model: sums}, new offset, message ids seen).
    Only complete lines count (a line still being written is read next time). One message may appear on several lines
    (one per content block) with the same usage: counted once, by message id (its last line wins)."""
    per_msg, order = {}, []
    with open(transcript, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        off = st["offset"] if 0 <= st["offset"] <= size else 0  # a shorter file (rewritten): start over, ids still dedupe
        f.seek(off)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return {}, off, []
    for raw in data[:end].split(b"\n"):
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        if not mid or mid in st["ids"]:
            continue
        model = str(msg.get("model") or "unknown")
        if model == "<synthetic>":
            continue
        if mid not in per_msg:
            order.append(mid)
        per_msg[mid] = (model, u)
    sums = {}
    for mid in order:
        model, u = per_msg[mid]
        s = sums.setdefault(model, {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "messages": 0})
        s["input_tokens"] += _int(u.get("input_tokens"))
        s["output_tokens"] += _int(u.get("output_tokens"))
        s["cache_read_tokens"] += _int(u.get("cache_read_input_tokens"))
        s["cache_write_tokens"] += _int(u.get("cache_creation_input_tokens"))
        s["messages"] += 1
    return sums, off + end + 1, order


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def cost_of(model, s, prices):
    """USD from a price table {prefix: [input, output, cache_write, cache_read] per million tokens}, or None."""
    best = max((p for p in prices if model.startswith(p)), key=len, default=None) if prices else None
    if best is None:
        return None
    pin, pout, pcw, pcr = (list(prices[best]) + [0, 0, 0, 0])[:4]
    return round((s["input_tokens"] * pin + s["output_tokens"] * pout + s["cache_write_tokens"] * pcw
                  + s["cache_read_tokens"] * pcr) / 1e6, 6)


def api(base, token, method, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + "/api/v1" + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": "kalmido-claude-usage-hook/" + VERSION,
        **({"Content-Type": "application/json"} if data is not None else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def current_task(base, token):
    """The task of the agent's status while it is working / waiting, else None."""
    try:
        a = api(base, token, "GET", "/agent")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return a.get("status_task") if a.get("status") in ("working", "waiting") else None


def reports(sums, session_id, task_id, prices):
    out = []
    for model, s in sums.items():
        if not (s["input_tokens"] or s["output_tokens"] or s["cache_read_tokens"] or s["cache_write_tokens"]):
            continue
        r = {"model": model[:100], **{k: s[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
             "note": f"claude-code {str(session_id or '')[:8]} · {s['messages']} messages"[:NOTE_MAX]}
        c = cost_of(model, s, prices)
        if c is not None:
            r["cost_usd"] = c
        if task_id:
            r["task_id"] = task_id
        out.append(r)
    return out


def run(hook, env, dry_run=False, out=sys.stdout):
    """One hook run; returns the reports it sent (or would send). Raises nothing the caller must handle."""
    transcript, session_id = hook.get("transcript_path"), hook.get("session_id") or ""
    if not transcript or not os.path.isfile(transcript):
        print("kalmido usage hook: no transcript_path in the hook input", file=sys.stderr)
        return []
    base, token = env.get("KALMIDO_URL", ""), env.get("KALMIDO_TOKEN", "")
    if not dry_run and (not base or not token):
        print("kalmido usage hook: KALMIDO_URL and KALMIDO_TOKEN must be set", file=sys.stderr)
        return []
    sdir = env.get("KALMIDO_USAGE_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "kalmido-usage")
    sp = state_path(sdir, session_id)
    st = load_state(sp)
    sums, off, ids = read_new(transcript, st)
    prices = {}
    if env.get("KALMIDO_USAGE_PRICES"):
        try:
            prices = json.loads(env["KALMIDO_USAGE_PRICES"])
            prices = prices if isinstance(prices, dict) else {}
        except ValueError:
            print("kalmido usage hook: KALMIDO_USAGE_PRICES is not valid JSON (no cost sent)", file=sys.stderr)
    task = None
    if env.get("KALMIDO_USAGE_TASK", "").isdigit():
        task = int(env["KALMIDO_USAGE_TASK"])
    elif sums and not dry_run:
        task = current_task(base, token)
    reps = reports(sums, session_id, task, prices)
    if dry_run:
        for r in reps:
            print(json.dumps(r), file=out)
        return reps
    for r in reps:
        try:
            api(base, token, "POST", "/agent/usage", r)
        except urllib.error.HTTPError as e:
            if e.code == 400 and "task_id" in r:  # the task is gone or no longer visible: report without it
                r.pop("task_id")
                try:
                    api(base, token, "POST", "/agent/usage", r)
                    continue
                except (urllib.error.URLError, OSError) as e2:
                    e = e2
            print(f"kalmido usage hook: report failed ({getattr(e, 'code', e)}), retried next time", file=sys.stderr)
            return []  # the state stays: the next run sends these turns again
        except (urllib.error.URLError, OSError) as e:
            print(f"kalmido usage hook: Kalmido not reachable ({getattr(e, 'reason', e)}), retried next time", file=sys.stderr)
            return []
    save_state(sp, {"offset": off, "ids": st["ids"] + ids})
    return reps


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code Stop hook: report model usage to Kalmido")
    ap.add_argument("env_file", nargs="?", help="env file with KALMIDO_URL / KALMIDO_TOKEN (optional)")
    ap.add_argument("--env", dest="env_opt", help="env file (same as the positional argument)")
    ap.add_argument("--dry-run", action="store_true", help="print the reports instead of sending them (state unchanged)")
    a = ap.parse_args(argv)
    try:
        env = dict(os.environ)
        path = a.env_opt or a.env_file
        if path:
            env.update(load_env(path))
        raw = sys.stdin.read()
        hook = json.loads(raw) if raw.strip() else {}
        run(hook if isinstance(hook, dict) else {}, env, a.dry_run)
    except Exception as e:  # noqa: BLE001 -- a hook must never break the session
        print(f"kalmido usage hook: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
