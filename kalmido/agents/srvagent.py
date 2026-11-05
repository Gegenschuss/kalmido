"""2.557.0 B (#4670): the server agent ("Kalmido-KI") - a third kind of agent next to the starter on an own computer and an own
service (REST / webhook / MCP): the person (for a team agent: an admin of its organisation or the instance) stores an API key of a
model provider, and Kalmido calls the model itself when an event for the agent comes (assigned, @mention, chat, listening in, a
planned job). No computer of one's own needed.

A server agent is an ordinary agent (agents.provider = SRV_PROVIDER) with a row in agent_server (core/migrations.d/4670_a.py):
provider, model, instructions, the key sealed with the server key (accounts/login.py seal, purpose srvagent:<agent id>). The key
is never served (only its last four characters as key_hint), never logged and never part of an error text; it can only be
replaced or deleted.

Routes (people only; who may: the owner of a personal agent, for a team agent an admin of its organisation or an instance admin,
as editing the agent - srv_need):
  GET  /api/agents/<id>/server          {provider, model, instructions, has_key, key_hint, enabled_instance, default_model,
                                         default_instructions, server}
  PUT  /api/agents/<id>/server          {provider?, model?, instructions?, api_key?, delete_key?: true, flow_models?} -> as GET;
                                         makes the row and turns the agent into a server agent; 403 {error: server_agents_off}
                                         while the instance switch is on. 2.565.0 D (#4674): flow_models {routine: model}
                                         (routines: srvstarter.SRV_FLOWS) = a model of its own per starter routine, '' = the
                                         agent's model; a model the provider does not list (GET …/models) -> 400, the entries
                                         not named stay; GET gives flow_models with every routine ('' = the agent's).
                                         2.571.0 D (#4676): flow_web {key: bool} (keys: srvweb.SRV_WEB_KEYS = the routines +
                                         "other" for runs without one) = read-only web research per routine, default off;
                                         the keys not named stay; GET gives flow_web with every key
  GET  /api/agents/<id>/server/models   {models: [{id, name}], default, fallback_note?} live from the provider (cached
                                         SRV_MODELS_TTL s); 409 {error: no_key} without a key
  GET  /api/agents/<id>/server/runs     ?limit=20 -> {runs: [{id, trigger, state, started, ended, steps, tokens_in, tokens_out,
                                         error, model, flow, web, web_searches, web_fetches, vat_checks}]} (flow: the starter
                                         routine, 2.565.0; web: the run had web access, 2.571.0)
The instance switch server_agents_off ("1" = off, set through the instance settings route): no PUT, no runs.
The runs themselves: agents/srvagent_run.py (a queue row of the worker, never the web process).

Providers: a small class per provider (PROVIDERS); Anthropic first (Messages API with tool use, standard library only). The base
URL comes from KALMIDO_SRVAGENT_ANTHROPIC_URL (tests point it at a local stub). Redirects are never followed (the key would go
along to another host)."""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, db, err, gsetting, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from ..core.env import env_int
from ..accounts.session import me
from ..accounts.supportgrant import sga_is_support  # 2.557.0 (2nd review)
from .srvstarter import SRV_DEFAULT_INSTRUCTIONS, SRV_DEFAULT_MODEL, SRV_FLOWS  # 2.557.0: the bridge of the parts is gone
from ..accounts.login import seal, unseal
from ..accounts.orgs import is_org_admin
from ..agents.core import agent_row, need_person, RUNTIME_MODEL_MAX, RUNTIME_MODEL_RE
from ..agents.admin import need_agent_admin
from .srvweb import srv_flow_web, srv_flow_web_in  # 2.571.0 D (#4676)

SRV_PROVIDER = "kalmido-server"     # agents.provider of a server agent
SRV_SWITCH = "server_agents_off"    # instance setting: "1" = server agents are off on this server
SRV_INSTR_MAX = 20000               # characters of the instructions
SRV_KEY_MIN, SRV_KEY_MAX = 8, 400   # characters of an API key
SRV_MODELS_TTL = 600                # s the model list of one key is kept
SRV_ANSWER_MAX = 8 * 1024 * 1024    # bytes of one provider answer
SRV_ANTHROPIC_URL = (os.environ.get("KALMIDO_SRVAGENT_ANTHROPIC_URL") or "https://api.anthropic.com").rstrip("/")
SRV_MODELS_S = env_int("KALMIDO_SRVAGENT_MODELS_S", 15, lo=2, hi=60)  # s for the model list
KEY_RE = re.compile(r"[\x21-\x7e]+")  # printable ASCII without spaces (it goes into a header)


def srv_defaults():
    """(default model, default instructions): kept in agents/srvstarter.py (SRV_DEFAULT_MODEL, SRV_DEFAULT_INSTRUCTIONS)."""
    return SRV_DEFAULT_MODEL, SRV_DEFAULT_INSTRUCTIONS


def srv_off(c):
    return gsetting(c, SRV_SWITCH) == "1"


# ---------------------------------------------------------------- providers

class ProviderError(Exception):
    """A provider call that failed. text is an i18n key with a neutral wording: never the provider's answer, never the key."""
    def __init__(self, text, status=0, retry=None):
        super().__init__(text)
        self.text, self.status, self.retry = text, status, retry


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # the key must never go along to another address
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class AnthropicProvider:
    """The Anthropic Messages API (https://docs.anthropic.com): POST /v1/messages with tools, GET /v1/models."""
    name = "anthropic"
    VERSION = "2023-06-01"

    def __init__(self, key, base=None):
        self.key = key
        self.base = (base or SRV_ANTHROPIC_URL).rstrip("/")

    def _req(self, method, path, payload=None, timeout=30):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "x-api-key": self.key, "anthropic-version": self.VERSION, "content-type": "application/json",
            "accept": "application/json", "user-agent": "kalmido-server-agent"})
        try:
            with _OPENER.open(req, timeout=max(1, timeout)) as r:
                raw = r.read(SRV_ANSWER_MAX + 1)
        except urllib.error.HTTPError as e:
            raise ProviderError(_status_text(e.code), e.code, _retry_of(e.headers)) from None
        except TimeoutError:
            raise ProviderError(N_("The provider did not answer in time"), 504) from None
        except (urllib.error.URLError, OSError) as e:
            if "timed out" in str(getattr(e, "reason", e)):
                raise ProviderError(N_("The provider did not answer in time"), 504) from None
            raise ProviderError(N_("The provider is not reachable"), 0) from None
        if len(raw) > SRV_ANSWER_MAX:
            raise ProviderError(N_("The provider's answer could not be read"), 502)
        try:
            out = json.loads(raw)
        except ValueError:
            raise ProviderError(N_("The provider's answer could not be read"), 502) from None
        if not isinstance(out, dict):
            raise ProviderError(N_("The provider's answer could not be read"), 502)
        return out

    def models(self):
        """[{id, name}] the key may use, newest first (as the provider lists them)."""
        out = self._req("GET", "/v1/models?limit=100", timeout=SRV_MODELS_S)
        rows = out.get("data") if isinstance(out.get("data"), list) else []
        return [{"id": str(m["id"])[:RUNTIME_MODEL_MAX], "name": str(m.get("display_name") or m["id"])[:200]}
                for m in rows if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]]

    def step(self, model, system, messages, tools, max_tokens, timeout):
        """One model call -> {content: [blocks as the provider sent them], stop, usage: {input, output, cache_read, cache_write}}."""
        sysb = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        tl = [dict(t) for t in tools]
        if tl:
            tl[-1]["cache_control"] = {"type": "ephemeral"}
        msgs = [dict(m) for m in messages]
        # the conversation so far is cached too (2.571.0 D: not on an assistant turn the provider resumes after pause_turn)
        if msgs and msgs[-1].get("role") != "assistant" and isinstance(msgs[-1].get("content"), list) and msgs[-1]["content"]:
            last = [dict(b) for b in msgs[-1]["content"]]
            last[-1]["cache_control"] = {"type": "ephemeral"}
            msgs[-1] = {**msgs[-1], "content": last}
        out = self._req("POST", "/v1/messages", {"model": model, "max_tokens": max_tokens, "system": sysb, "messages": msgs,
                                                 **({"tools": tl} if tl else {})}, timeout=timeout)
        content = out.get("content") if isinstance(out.get("content"), list) else []
        u = out.get("usage") if isinstance(out.get("usage"), dict) else {}
        num = lambda k, d=u: int(d.get(k) or 0) if isinstance(d.get(k), int) and d.get(k) >= 0 else 0  # noqa: E731
        st = u.get("server_tool_use") if isinstance(u.get("server_tool_use"), dict) else {}
        # 2.571.0 D (#4676): the blocks of the provider's own web tools stay in the conversation as they came (server_tool_use and
        # its *_tool_result: the provider needs them back unchanged); usage.server_tool_use counts searches and fetched pages
        return {"content": [b for b in content if isinstance(b, dict) and (b.get("type") in ("text", "tool_use", "server_tool_use")
                                                                          or str(b.get("type") or "").endswith("_tool_result"))],
                "stop": str(out.get("stop_reason") or ""),
                "usage": {"input": num("input_tokens"), "output": num("output_tokens"),
                          "cache_read": num("cache_read_input_tokens"), "cache_write": num("cache_creation_input_tokens"),
                          "web_searches": num("web_search_requests", st), "web_fetches": num("web_fetch_requests", st)}}


def _status_text(code):
    if code in (401, 403):
        return N_("The provider refused the key")
    if code == 404:
        return N_("The model is not offered by the provider")
    if code == 429 or code == 529:
        return N_("Too many requests at the provider, try again later")
    if code in (408, 504):
        return N_("The provider did not answer in time")
    return N_("The provider answered with an error")


def _retry_of(headers):
    try:
        return min(3600.0, max(0.0, float((headers or {}).get("retry-after") or "")))
    except (TypeError, ValueError):
        return None


PROVIDERS = {"anthropic": AnthropicProvider}  # an OpenAI compatible one can follow with the same three methods


def srv_provider(name, key):
    cls = PROVIDERS.get(name or "anthropic")
    if cls is None:
        raise ProviderError(N_("The provider answered with an error"), 400)
    return cls(key)


# ---------------------------------------------------------------- settings

def srv_row(c, aid):
    with system_ctx(c):  # the agent's own row; the caller checked who asks
        return c.execute("SELECT * FROM agent_server WHERE agent_id=?", (aid,)).fetchone()


def srv_key(c, aid, row=None):
    """The opened key of agent aid, '' without one. Only for the provider call: never into an answer, a log or an error."""
    row = row if row is not None else srv_row(c, aid)
    if not row or not row["key_sealed"]:
        return ""
    try:
        return unseal(c, f"srvagent:{aid}", row["key_sealed"])
    except Exception:  # noqa: BLE001 -- another server key: as if there were none (the person stores it again)
        return ""


def srv_need(c, aid):
    """The agent row of aid when the current person may set it up: the owner of a personal agent; for a team agent an admin of
    its organisation or an instance admin (need_agent_admin with cred: never through a support access). 404 otherwise."""
    need_person(404)
    with system_ctx(c):  # who may is decided right here (the instance admin reaches agents of every organisation)
        a = agent_row(c, aid)
    if not a:
        raise Denied(404)
    uid = me()
    if a["owner_id"]:
        if a["owner_id"] != uid:
            raise Denied(404)
        return a
    if a["org_id"] and is_org_admin(c, uid, a["org_id"]):
        return a
    if g.user["is_admin"]:
        try:
            with system_ctx(c):  # the instance admin reaches team agents of every organisation (need_agent_admin decides)
                return need_agent_admin(c, aid, cred=True)
        except Denied:  # review 2.557.0: a support access learns nothing about the agent either (404, not 403)
            raise Denied(404) from None
    raise Denied(404)


def srv_flow_models(row):
    """2.565.0 D (#4674): {routine: model} of every routine in SRV_FLOWS ('' = the agent's model) from agent_server.flow_models."""
    try:
        d = json.loads(row["flow_models"] or "{}") if row and "flow_models" in row.keys() else {}
    except (TypeError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {k: d[k] if isinstance(d.get(k), str) else "" for k in SRV_FLOWS}


def srv_flow_models_in(c, aid, v, row):
    """PUT flow_models {routine: model | '' | null} -> the stored json; BadInput for an unknown routine or a model the provider does
    not list for the agent's key (400), ProviderError when the list cannot be read (502 at the caller)."""
    if not isinstance(v, dict) or any(k not in SRV_FLOWS for k in v):
        raise BadInput(tr("Invalid value: {0}", "flow_models"))
    new = {k: (m if m is not None else "") for k, m in v.items()}
    if any(not isinstance(m, str) or len(m.strip()) > RUNTIME_MODEL_MAX or (m.strip() and not RUNTIME_MODEL_RE.fullmatch(m.strip()))
           for m in new.values()):
        raise BadInput(tr("Invalid value: {0}", "flow_models"))
    new = {k: m.strip() for k, m in new.items()}
    if any(new.values()):
        ms = srv_models(c, aid, row) if row else None
        if ms is None:
            raise BadInput(tr("Save an API key first; then the provider’s models are listed here."))
        ids = {m["id"] for m in ms}
        bad = sorted(k for k, m in new.items() if m and m not in ids)
        if bad:
            raise BadInput(tr("The model is not offered by the provider") + ": " + ", ".join(bad))
    return json.dumps({k: m for k, m in {**srv_flow_models(row), **new}.items() if m}, ensure_ascii=False)


def srv_dict(c, a, row=None):
    row = row if row is not None else srv_row(c, a["user_id"])
    dm, di = srv_defaults()
    return {"provider": (row["provider"] if row else "") or "anthropic", "model": (row["model"] if row else "") or dm,
            "instructions": row["instructions"] if row else "", "has_key": bool(row and row["key_sealed"]),
            "key_hint": ("…" + row["key_hint"]) if row and row["key_sealed"] and row["key_hint"] else "",
            "enabled_instance": not srv_off(c), "default_model": dm, "default_instructions": tr(di),  # 2.557.0: in the person's language
            "server": bool(row) and (a["provider"] or "") == SRV_PROVIDER,
            "flow_models": srv_flow_models(row),  # 2.565.0 D (#4674)
            "flow_web": srv_flow_web(row)}  # 2.571.0 D (#4676)


@app.get("/api/agents/<int:aid>/server")
def srv_get(aid):
    c = db()
    a = srv_need(c, aid)
    return jsonify(srv_dict(c, a))


@app.put("/api/agents/<int:aid>/server")
def srv_put(aid):
    c = db()
    a = srv_need(c, aid)
    if srv_off(c):
        return jsonify(error="server_agents_off", message=tr("Server agents are switched off on this server")), 403
    b = body()
    if not isinstance(b, dict):
        return err(tr("The body must be a JSON object"))
    unknown = sorted(k for k in b if k not in ("provider", "model", "instructions", "api_key", "delete_key", "flow_models", "flow_web"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    sets = {}
    if "provider" in b:
        if b["provider"] not in PROVIDERS:
            return err(tr("Invalid value: {0}", "provider"))
        sets["provider"] = b["provider"]
    if "model" in b:
        m = b["model"] if b["model"] is not None else ""
        if not isinstance(m, str) or len(m.strip()) > RUNTIME_MODEL_MAX or (m.strip() and not RUNTIME_MODEL_RE.fullmatch(m.strip())):
            return err(tr("Invalid value: {0}", "model"))
        sets["model"] = m.strip()
    if "instructions" in b:
        t = b["instructions"] if b["instructions"] is not None else ""
        if not isinstance(t, str) or len(t) > SRV_INSTR_MAX:
            return err(tr("Invalid value: {0}", "instructions"))
        sets["instructions"] = t.replace("\x00", "")
    if "delete_key" in b and b["delete_key"] is not True:
        return err(tr("Invalid value: {0}", "delete_key"))
    key = None
    if "api_key" in b:
        if b.get("delete_key") is True:
            return err(tr("Invalid value: {0}", "delete_key"))
        k = b["api_key"]
        if not isinstance(k, str) or not (SRV_KEY_MIN <= len(k.strip()) <= SRV_KEY_MAX) or not KEY_RE.fullmatch(k.strip()):
            return err(tr("Invalid value: {0}", "api_key"))  # never the value itself
        key = k.strip()
    if b.get("flow_models") is not None:  # 2.565.0 D (#4674): checked against the live list of the key stored now
        try:
            sets["flow_models"] = srv_flow_models_in(c, aid, b["flow_models"], srv_row(c, aid))
        except BadInput as e:
            return err(str(e))
        except ProviderError as e:
            return jsonify(error=tr(e.text)), 502
    if b.get("flow_web") is not None:  # 2.571.0 D (#4676): read-only web research per routine, default off
        try:
            sets["flow_web"] = srv_flow_web_in(b["flow_web"], srv_row(c, aid))
        except BadInput as e:
            return err(str(e))
    with system_ctx(c):  # the agent's own row; srv_need decided who may
        c.execute("""INSERT INTO agent_server(agent_id, cursor, updated_at, updated_by)
                     VALUES(?, (SELECT COALESCE(MAX(id), 0) FROM agent_events WHERE agent_id=?), ?, ?)
                     ON CONFLICT (agent_id) DO NOTHING""", (aid, aid, iso(now_utc()), me()))  # older events are not worked off
        for k, v in sets.items():
            c.execute(f"UPDATE agent_server SET {k}=? WHERE agent_id=?", (v, aid))  # k from the fixed names above
        if key is not None:
            c.execute("UPDATE agent_server SET key_sealed=?, key_hint=? WHERE agent_id=?", (seal(c, f"srvagent:{aid}", key), key[-4:], aid))
        elif b.get("delete_key") is True:
            c.execute("UPDATE agent_server SET key_sealed='', key_hint='' WHERE agent_id=?", (aid,))
        c.execute("UPDATE agent_server SET updated_at=?, updated_by=? WHERE agent_id=?", (iso(now_utc()), me(), aid))
        c.execute("UPDATE agents SET provider=?, ai=1 WHERE user_id=?", (SRV_PROVIDER, aid))
    if key is not None or b.get("delete_key") is True:
        _MODELS.pop(aid, None)
    c.commit()
    print("server agent", aid, "settings", ",".join(sorted(sets)) or "-",
          "key replaced" if key is not None else "key deleted" if b.get("delete_key") is True else "", "by user", me(), flush=True)
    with system_ctx(c):  # the agent's own row after the change (srv_need decided who may)
        return jsonify(srv_dict(c, agent_row(c, aid)))


def srv_run_web(r):
    """2.571.0 D (#4676): {web, web_searches, web_fetches, vat_checks} of a run row (agent_runs.web = its web state json)."""
    try:
        st = json.loads(r["web"]) if "web" in r.keys() and r["web"] else None
    except (TypeError, ValueError):
        st = None
    st = st if isinstance(st, dict) else None
    n = lambda k: int(st.get(k) or 0) if st and isinstance(st.get(k), int) else 0  # noqa: E731
    return {"web": st is not None, "web_searches": n("searches"), "web_fetches": n("fetches"), "vat_checks": n("vies")}


# ---------------------------------------------------------------- the models of the provider

_MODELS, _MODELS_LOCK = {}, threading.Lock()  # agent id -> (key fingerprint, time, [models])


def srv_models(c, aid, row=None):
    """[{id, name}] of the provider for agent aid's key (cached SRV_MODELS_TTL s per agent and key). ProviderError; None without a key."""
    row = row if row is not None else srv_row(c, aid)
    key = srv_key(c, aid, row)
    if not key:
        return None
    fp = hashlib.sha256(key.encode()).hexdigest()
    with _MODELS_LOCK:
        hit = _MODELS.get(aid)
        if hit and hit[0] == fp and time.monotonic() - hit[1] < SRV_MODELS_TTL:
            return hit[2]
    ms = srv_provider(row["provider"], key).models()
    with _MODELS_LOCK:
        _MODELS[aid] = (fp, time.monotonic(), ms)
    return ms


def srv_pick_default(ms):
    """(the model to use when none is chosen, fallback note or None): the default when the provider offers it, else the first
    Sonnet of the list (else the first model) with a note."""
    dm = srv_defaults()[0]
    ids = [m["id"] for m in ms]
    if not ids or dm in ids:
        return dm, None
    alt = next((i for i in ids if "sonnet" in i.lower()), ids[0])
    return alt, tr("The default model {0} is not offered by the provider; {1} is used instead.", dm, alt)


@app.get("/api/agents/<int:aid>/server/models")
def srv_models_get(aid):
    c = db()
    srv_need(c, aid)
    if sga_is_support(c):  # 2nd review 2.557.0: a support session never spends the customer's key at the provider
        raise Denied(404)
    if srv_off(c):  # review 2.557.0: switched off = no call to the provider with the owner's key either
        return jsonify(error="server_agents_off", message=tr("Server agents are switched off on this server")), 403
    try:
        ms = srv_models(c, aid)
    except ProviderError as e:
        return jsonify(error=tr(e.text)), 502
    if ms is None:
        return jsonify(error="no_key", message=tr("No API key is stored for this agent")), 409
    d, note = srv_pick_default(ms)
    out = {"models": ms, "default": d}
    if note:
        out["fallback_note"] = note
    return jsonify(out)


@app.get("/api/agents/<int:aid>/server/runs")
def srv_runs_get(aid):
    c = db()
    srv_need(c, aid)
    try:
        limit = max(1, min(100, int(request.args.get("limit") or 20)))
    except ValueError:
        return err(tr("Invalid value: {0}", "limit"))
    with system_ctx(c):  # the agent's own rows (srv_need decided)
        rows = c.execute("SELECT * FROM agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT ?", (aid, limit)).fetchall()
    return jsonify(runs=[{"id": r["id"], "trigger": r["cause"], "state": r["state"], "started": r["started"], "ended": r["ended"],
                          "steps": r["steps"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                          "error": tr(r["error"]) if r["error"] else "", "model": r["model"],
                          "flow": r["flow"] if "flow" in r.keys() else "", **srv_run_web(r)} for r in rows])  # 2.565.0 D (#4674): its starter routine


# ---------------------------------------------------------------- the hook in agents/core.py agent_emit

def srv_event(c, a, event, actor=None):
    """agent_emit recorded an event for server agent a (the caller commits): Stop marks its running run, an event that asks for
    work queues a run (agents/srvagent_run.py). An event made by another agent never starts a run (two server agents must not
    keep each other busy: an agent gives no orders to another one, #928); the next run reads it as data."""
    from .srvagent_run import srv_abort, srv_kick, SRV_TRIGGERS
    from .srvteam import srv_kick_ok  # 2.569.0 B (#4675): another person's event never starts a personal agent's run
    if event == "abort":
        srv_abort(c, a["user_id"])
    elif event in SRV_TRIGGERS and not (isinstance(actor, dict) and actor.get("kind") == "agent") and srv_kick_ok(a, actor):
        srv_kick(a["user_id"])
