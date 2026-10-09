"""2.32.0 (#1081 / #1079): what an agent says between its tool calls, and what its host really runs with.

STEPS ("Zwischenstände"): the short prose an agent writes between its tool calls ("I look at the tests first"). The host sends
each one with POST /api/v1/agent/progress, either for a chat run (chat_user_id = the person it answers) or for a job (job_id,
the job must be for a person: user_id). Rules (owner decisions 08.10.2026):
 - only the agent's prose, never tool output (file contents, logs, rows); the server keeps one line per step, cuts it to
   STEP_KEEP_CHARS (the live view shows STEP_LIVE_CHARS) and replaces recognisable secrets with "[entfernt]" BEFORE storing
 - stored for good with the answer / the job (no expiry; they go with the message / the job / the person)
 - visible ONLY to the person the agent chats with / the job is for -- never to other members, admins, other agents or in
   shared tasks / lists (there only the result; others see the job's title and progress line as before)
 - a chat run: the newest STEP_LIVE_N show live under the typing dots; the agent's next chat answer to that person takes
   them along (message_id); a status idle / error / paused ends a run without an answer (state done, not shown)
 - a job: the history ("Verlauf") under the job and under the chat message that carries its result (chat job_id),
   grouped by the job's progress lines (append_log, state log); at most JOB_STEPS_SHOWN lines, the full text as a file
Rate limit: STEP_RATE per minute and agent (429). Text is always shown as text (the client escapes it).

HOST INFO (#1079): PUT /api/v1/agent/status may carry model (as resolved by the host, e.g. "Opus 5.5"), permission_mode (the
mode the current run really uses: ask | auto) and host_permission_mode (the host's own default). Stored in agents.host_info,
shown in the chat header ("Host default (Auto)", "Opus 5.5", "set: sonnet · runs: Opus 5.5")."""
import json
import re
from datetime import timedelta

from flask import g, jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied
from ..personal.timetrack import BadInput, UnknownFields
from ..api.v1 import hit_limit, v1_args, v1_err, v1_json, v1_view
from ..agents.core import agent_shares, is_agent, need_agent

STEP_KEEP_CHARS = 500      # stored per step
STEP_LIVE_CHARS = 200      # shown live under the typing dots
STEP_IN_MAX = 4000         # a longer text is refused (400): that is no step, that is output
STEP_LIVE_N = 3            # live lines in the chat
STEP_LIVE_MAX_AGE_S = 1800  # older pending steps are no longer "live"
STEP_RATE = 60             # steps per minute and agent
JOB_STEPS_SHOWN = 300      # lines of a job's history in the app (the file has all)
REDACTED = "[entfernt]"
HOST_MODEL_MAX = 80

# ---- the secret filter: recognisable tokens / keys -> [entfernt] (before anything is stored)
_SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|KEY|CERTIFICATE)-----.*?(?:-----END [A-Z0-9 ]*-----|\Z)", re.S),
    re.compile(r"\bsk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),   # a JWT
    re.compile(r"\b(?:Bearer|Basic|Token)\s+(?=[A-Za-z0-9._~+/=-]{0,200}\d)[A-Za-z0-9._~+/=-]{12,}"),  # a value with a digit
    re.compile(r"(?i)(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),                            # user:password@ in a URL
]
# key / token / secret / password (as a word or part of a name, e.g. API_KEY=, "token": ) followed by a long value
# (2.32 review: bounded name parts and a required ":" / "=" -- linear time, and German prose with long words stays intact)
_SECRET_KV = re.compile(r"(?i)\b([A-Za-z0-9_.-]{0,24}?(?:key|token|secret|passw(?:or)?d|pwd|credential|auth)[A-Za-z0-9_-]{0,24}"
                        r"[\"']?\s{0,3}[:=]\s{0,3}[\"']?)([A-Za-z0-9+/_=.~-]{16,})")
_LONG_RUN = re.compile(r"[A-Za-z0-9+/_-]{48,}={0,2}")


def _long_secretish(m):
    s = m.group(0)  # very long mixed strings (hashes, keys) are never prose
    return REDACTED if re.search(r"\d", s) and re.search(r"[A-Za-z]", s) else s


def redact(text):
    """The text with recognisable secrets replaced by [entfernt]; (text, True when something was replaced)."""
    out = text
    for rx in _SECRET_RES:
        out = rx.sub(REDACTED, out)
    out = _SECRET_KV.sub(lambda m: m.group(1) + REDACTED, out)
    out = _LONG_RUN.sub(_long_secretish, out)
    return out, out != text


def step_clean(text):
    """One line of prose: secrets out, whitespace folded, cut to STEP_KEEP_CHARS. BadInput when empty / not text."""
    if not isinstance(text, str) or not text.strip():
        raise BadInput(tr("Invalid value: {0}", "text"))
    if len(text) > STEP_IN_MAX:
        raise BadInput(tr("Invalid value: {0}", "text"))
    t, hit = redact(text)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > STEP_KEEP_CHARS:
        t = t[:STEP_KEEP_CHARS - 1].rstrip() + "…"
    return t, hit


def _live_text(t):
    return t if len(t) <= STEP_LIVE_CHARS else t[:STEP_LIVE_CHARS - 1].rstrip() + "…"


# ---- the agent's side
@app.post("/api/v1/agent/progress")
@v1_view
def v1_agent_progress():
    """{text, chat_user_id | job_id} -- one step (prose between tool calls) of a chat run with person chat_user_id or of a job
    of the agent (the job must be for a person: user_id). Only that person sees it. 201 {id, text, redacted}."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("text", "chat_user_id", "job_id"))
    if unknown:
        raise UnknownFields(unknown)
    uid, jid = b.get("chat_user_id"), b.get("job_id")
    if (uid is None) == (jid is None):
        raise BadInput(tr("Invalid value: {0}", "chat_user_id / job_id"))
    for k, v in (("chat_user_id", uid), ("job_id", jid)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
            raise BadInput(tr("Invalid value: {0}", k))
    if hit_limit(f"steps:{aid}", STEP_RATE):
        return v1_err(429, tr("Too many requests, please slow down"), {"Retry-After": "5"})
    text, hit = step_clean(b.get("text"))
    c = db()
    if jid is not None:
        j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
        if not j:
            raise Denied(404)
        if not j["user_id"]:
            raise Denied(409, tr("This job is for nobody: steps need the person it is for (user_id)"))
        if j["state"] not in ("running", "waiting"):
            raise Denied(409, tr("This job has already ended"))
        uid = j["user_id"]
    else:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u or is_agent(u) or not agent_shares(c, aid, uid):
            raise Denied(404)
    sid = c.execute("INSERT INTO agent_steps(agent_id,user_id,job_id,state,text,created_at) VALUES(?,?,?,?,?,?)",
                    (aid, uid, jid, "live" if jid is None else "done", text, iso_ms(now_utc()))).lastrowid
    c.commit()
    return jsonify(id=sid, text=text, redacted=hit), 201


def steps_job_log(c, j, line):
    """A job's progress line (append_log / log on create) also goes into its history as a heading -- only for a job that is
    for a person (the log itself is what everyone who sees the job sees anyway)."""
    if not j or not j["user_id"]:
        return
    for ln in [x for x in str(line or "").split("\n") if x.strip()][-20:]:
        t, _ = step_clean(ln[:STEP_KEEP_CHARS * 2])
        c.execute("INSERT INTO agent_steps(agent_id,user_id,job_id,state,text,created_at) VALUES(?,?,?,?,?,?)",
                  (j["agent_id"], j["user_id"], j["id"], "log", t, iso_ms(now_utc())))


def steps_take(c, aid, uid, mid):
    """The agent answered person uid in the chat (message mid): the live steps of the run belong to that answer now."""
    c.execute("UPDATE agent_steps SET message_id=?, state='done' WHERE agent_id=? AND user_id=? AND job_id IS NULL AND state='live'",
              (mid, aid, uid))


def steps_end(c, aid):
    """The agent reported idle / error / paused: the steps of a run that ended without a chat answer (a task event, an error)
    would never be shown again -- they are dropped instead of kept for good (2.32 review)."""
    c.execute("DELETE FROM agent_steps WHERE agent_id=? AND job_id IS NULL AND state='live'", (aid,))


# ---- host info (#1079)
HOST_MODES = ("ask", "auto")


def host_info_in(b):
    """The host fields of PUT /agent/status (model, permission_mode, host_permission_mode) -> dict of what was sent."""
    out = {}
    if "model" in b:
        m = b["model"]
        if m is not None and (not isinstance(m, str) or len(m.strip()) > HOST_MODEL_MAX or re.search(r"[<>\x00-\x1f]", m)):
            raise BadInput(tr("Invalid value: {0}", "model"))
        out["model"] = (m or "").strip()
    for k in ("permission_mode", "host_permission_mode"):
        if k in b:
            v = b[k] if b[k] is not None else ""
            if v not in ("", *HOST_MODES):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
    return out


def host_info(a):
    try:
        d = json.loads(a["host_info"] or "{}") if "host_info" in a.keys() else {}
    except (ValueError, TypeError):
        d = {}
    return {"model": d.get("model") or "", "permission_mode": d.get("permission_mode") or "",
            "host_permission_mode": d.get("host_permission_mode") or "", "at": d.get("at")}


def host_info_set(c, a, new):
    """Merges new into the stored host info; True when something visible changed."""
    if not new:
        return False
    cur = host_info(a)
    nxt = {**cur, **new, "at": iso(now_utc())}
    c.execute("UPDATE agents SET host_info=? WHERE user_id=?", (json.dumps(nxt, ensure_ascii=False), a["user_id"]))
    return any(cur.get(k) != nxt.get(k) for k in ("model", "permission_mode", "host_permission_mode"))


# ---- the person's side (session; never an agent, never anyone but the person the steps are for)
def steps_sig(c, uid):
    """For /api/version: changes when a step for uid arrives (the open chat then fetches)."""
    r = c.execute("SELECT MAX(id) FROM agent_steps WHERE user_id=?", (uid,)).fetchone()
    return (r[0] or 0) if r else 0


def steps_live(c, aid, uid):
    """The newest STEP_LIVE_N live steps of agent aid's run for uid, newest first ([] when none / too old)."""
    cut = iso_ms(now_utc() - timedelta(seconds=STEP_LIVE_MAX_AGE_S))
    rows = c.execute("""SELECT id, text, created_at FROM agent_steps WHERE agent_id=? AND user_id=? AND job_id IS NULL AND state='live'
                        AND created_at>=? ORDER BY id DESC LIMIT ?""", (aid, uid, cut, STEP_LIVE_N)).fetchall()
    return [{"id": r["id"], "text": _live_text(r["text"]), "at": r["created_at"]} for r in rows]


def steps_of_messages(c, uid, mids):
    """{message id: [{text, at}]} of the stored steps of uid's chat answers."""
    out, mids = {}, [x for x in mids if x]
    if not mids:
        return out
    for r in c.execute(f"""SELECT message_id, text, created_at FROM agent_steps WHERE user_id=? AND message_id IN ({','.join('?' * len(mids))})
                           ORDER BY id""", (uid, *mids)):
        out.setdefault(r["message_id"], []).append({"text": r["text"], "at": r["created_at"]})
    return out


def job_steps_count(c, uid, jids):
    jids = [x for x in jids if x]
    if not jids:
        return {}
    return {r[0]: r[1] for r in c.execute(f"""SELECT job_id, COUNT(*) FROM agent_steps WHERE user_id=? AND job_id IN ({','.join('?' * len(jids))})
                                               GROUP BY job_id""", (uid, *jids))}


def need_own_job(c, jid):
    """The job when it is for the signed-in person (else 404 -- also for admins, other members and agents)."""
    if is_agent(g.user):
        raise Denied(404)
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    if not j or j["user_id"] != me():
        raise Denied(404)
    return j


def _job_rows(c, j):
    return c.execute("SELECT text, state, created_at FROM agent_steps WHERE job_id=? AND user_id=? ORDER BY id",
                     (j["id"], j["user_id"])).fetchall()


@app.get("/api/agents/jobs/<int:jid>/steps")
def agent_job_steps(jid):
    """2.32.0 (#1081): the history of a job of mine: [{text, at, heading}] (heading = a progress line of the job), the newest
    JOB_STEPS_SHOWN; total = all of them. ?format=txt: everything as a text file (download)."""
    c = db()
    j = need_own_job(c, jid)
    rows = _job_rows(c, j)
    if request.args.get("format") == "txt":
        lines = [f"{j['title']}", ""]
        for r in rows:
            at = r["created_at"][:16].replace("T", " ")
            lines.append(("\n## " if r["state"] == "log" else "") + f"{at}  {r['text']}")
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", f"job-{j['id']}-verlauf").strip("-") + ".txt"
        return Response("\n".join(lines) + "\n", mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
    shown = rows[-JOB_STEPS_SHOWN:]
    return jsonify(job_id=j["id"], title=j["title"], total=len(rows),
                   steps=[{"text": r["text"], "at": r["created_at"], "heading": r["state"] == "log"} for r in shown])
