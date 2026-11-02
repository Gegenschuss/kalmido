"""2.484.0 (#2200): scheduling polls over REST v1 (+ MCP) and their OpenAPI part (scope "calendar").

What a token sees follows calendars/polls.py (tpo_rows / tpo_may): a person their own polls, the private polls of their
personal agents and their organisations' polls by their role. An agent: the polls it created, and someone else's poll of
its workspace only when it hangs on a task / project / client the agent may see (shared projects, data lock); never a
private poll of another account (also not its owner's), never another organisation's. Created polls belong to the token's
account (private or one of its organisations). Read and create only: no change, no "choose this time", no delete, and never
a vote (the public link answers a bearer token with its 404 page). The voters' e-mail addresses never go out here."""
from flask import jsonify

from ..core.config import app
from ..core.db import db
from ..accounts.session import me
from ..core.access import need_feat
from ..core.errors import reject_unknown
from ..api.common import v1_args, v1_json, v1_view
from .polls import tpo_dict, tpo_need, tpo_new, tpo_rows, TPO_OPT_MAX, TPO_OPT_MIN

PV1_IN = ("title", "description", "duration", "location", "tz", "options", "space", "task_id", "client_id", "list_id",
          "expires_at", "show_votes")


@app.get("/api/v1/polls")
@v1_view
def v1_polls():
    a = v1_args(("space", "task_id", "client_id", "list_id"))
    need_feat("events")
    c, uid = db(), me()
    return jsonify(data=[tpo_dict(c, r, uid, full=False, emails=False) for r in tpo_rows(c, uid, a)], next_cursor=None)


@app.get("/api/v1/polls/<int:pid>")
@v1_view
def v1_poll(pid):
    v1_args(())
    need_feat("events")
    c, uid = db(), me()
    return jsonify(tpo_dict(c, tpo_need(c, pid), uid, emails=False))


@app.post("/api/v1/polls")
@v1_view
def v1_poll_new():
    v1_args(())
    need_feat("events")
    b = v1_json()
    reject_unknown(b, PV1_IN)
    c, uid = db(), me()
    return jsonify(tpo_dict(c, tpo_need(c, tpo_new(c, uid, b)), uid, emails=False)), 201


def polls_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    P, S = "Events", "calendar"  # the polls lead to an event: under the Events tag
    opt = {"type": "object", "properties": {
        "id": {"type": "integer"}, "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM, wall clock of the poll's tz"},
        "end": {"type": "string"}, "y": {"type": "integer", "description": "Yes votes"}, "m": {"type": "integer", "description": "Maybe votes"},
        "n": {"type": "integer", "description": "No votes"}}}
    schemas["Poll"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "description": {"type": "string"}, "duration": {"type": "integer", "description": "Minutes"},
        "location": {"type": "string"}, "tz": {"type": "string", "description": "IANA time zone of the proposed times"},
        "space": {"type": "string", "description": "private | org:<id>"}, "org_id": nul("integer"), "user_id": {"type": "integer", "description": "Who created it"},
        "mine": {"type": "boolean"}, "can_edit": {"type": "boolean"}, "link_on": {"type": "boolean"}, "show_votes": {"type": "boolean"},
        "expires_at": nul("string"), "closed_at": nul("string", description="Set once a time was chosen (in the app)"),
        "chosen_id": nul("integer"), "event_id": nul("integer", description="The event made from the chosen time"),
        "task_id": nul("integer"), "client_id": nul("integer"), "list_id": nul("integer"), "votes_n": {"type": "integer"},
        "best_id": nul("integer", description="The option with most yes, then most maybe (null: no yes / maybe yet)"),
        "live": {"type": "boolean", "description": "The public link is open right now"},
        "url": nul("string", description="The public link for the voters (only with can_edit); hand it to people, never vote yourself"),
        "options": {"type": "array", "items": opt},
        "votes": {"type": "array", "description": "Only in GET /polls/{id}: name and answers per voter (never an e-mail address)",
                  "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"},
                                                            "answers": {"type": "object", "description": "option id -> y | m | n"},
                                                            "at": {"type": "string"}}}},
        "created_at": {"type": "string"}, "updated_at": {"type": "string"}}}
    schemas["PollPage"] = page("Poll")
    body = {"type": "object", "additionalProperties": False, "required": ["title", "options"], "properties": {
        "title": {"type": "string", "maxLength": 200}, "description": {"type": "string", "maxLength": 4000},
        "duration": {"type": "integer", "minimum": 5, "maximum": 1440, "description": "Minutes (default 60)"},
        "location": {"type": "string", "maxLength": 500}, "tz": {"type": "string", "description": "IANA zone (default: the server's)"},
        "options": {"type": "array", "minItems": TPO_OPT_MIN, "maxItems": TPO_OPT_MAX, "items": {
            "type": "object", "required": ["start"], "properties": {"start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
                                                                  "end": {"type": "string", "description": "Default: start + duration"}}}},
        "space": {"type": "string", "description": "private (default) | org:<id> (an organisation of yours: its members see the poll)"},
        "task_id": nul("integer"), "client_id": nul("integer"), "list_id": nul("integer"),
        "expires_at": nul("string", description="YYYY-MM-DD (end of that day) or an ISO time: the link closes then"),
        "show_votes": {"type": "boolean", "description": "Voters see the other names and answers (default true)"}}}
    paths["/polls"] = {
        "get": op("2.484.0: the scheduling polls you may see", P, ok(ref("PollPage")) | errs("400", "403", "404"),
                  [q("space", "private | org:<id> | all (default)"), q("task_id", "Only polls about this task", {"type": "integer"}),
                   q("client_id", "Only polls about this client", {"type": "integer"}), q("list_id", "Only polls about this project", {"type": "integer"})],
                  scope=S, desc="Your own polls and those of your organisations (by your role there; an agent: someone else's only when it hangs on a "
                       "task / project / client shared with the agent); without the votes."),
        "post": op("2.484.0: create a scheduling poll (several proposed times, people vote through its public link)", P,
                   ok(ref("Poll"), "Created", "201") | errs("400", "403", "404", "409"), body=body, scope=S,
                   desc="The poll belongs to your account (a personal agent's private poll is also its owner's). Hand the url to the "
                        "people; agents never vote. Choosing the time, changing and deleting happen in the app. 409 = at most 300 polls.")}
    paths["/polls/{id}"] = {
        "get": op("2.484.0: one scheduling poll with its times, the tally and the votes (names, answers)", P, ok(ref("Poll")) | errs("404"),
                  [pid(desc="Poll id")], scope=S)}
