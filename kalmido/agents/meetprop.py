"""2.70.0 A (#1354): a meeting becomes tasks -- the guided flow of the proposal kind "extract" (Tasks from notes).

A person turns meeting notes and / or photos of a whiteboard into tasks: the chat with an agent offers "Turn a meeting into
tasks" (only when that agent takes proposal requests from the person, prop_agent_ok), the dialog asks for a list (one the
person may write in, never a health list), the notes and up to MTG_IMG_MAX images. The images are stored as the person's
files in the chat between the person and THIS agent (agents/chat.py chat_post: same limits, same storage as any chat
file; no 'chat' event -- the agent gets them with the job) and the request carries their ids (image_ids). The job input
then holds images: [{id, name, mime, size, url}] (url = /api/v1/chat-attachments/{id}; the agent reads only files of its
own chats, chat_file_access). Text OR an image is required.

When the agent's proposal is ready, the chat shows ONE card per proposal ("N tasks from the meeting": title, assignee,
due date, a tick per line, "Create selected" / "Discard"); it uses the same endpoints as the review dialog
(/api/proposals/<id>/apply | discard), so the tasks are created as the person (one undo step) exactly as before.
Kalmido never runs a model itself."""
import json

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, err
from ..core.access import Denied, list_people, need_collab, need_list
from ..accounts.session import me
from ..collab.comments import user_names
from ..core.errors import BadInput, UnknownFields
from ..agents.core import agent_ids, agent_row, is_agent, list_sections, need_chat_agent
from ..agents.chat import chat_post, chat_unlink_trimmed
from ..agents.proposals import (
    _p_int, _p_keys, _p_list, _p_str, prop_agent_ok, PROP_TEXT_MAX, PROP_TITLES,
)

MTG_IMG_MAX = 4        # images per request
MTG_CARDS_MAX = 5      # ready proposals shown as cards in one chat
MTG_IMG_URL = "/api/v1/chat-attachments/{0}"


def mtg_images(c, uid, aid, ids):
    """The image files ids of the person's own messages in their chat with agent aid -> [{id, name, mime, size, url}].
    Anything else (another chat, another person, the agent's own files, not an image) = 400."""
    ids = [_p_int(x, "image_ids") for x in _p_list(ids, "image_ids", MTG_IMG_MAX)]
    if len(set(ids)) != len(ids):
        raise BadInput(tr("Invalid value: {0}", "image_ids"))
    if not ids:
        return []
    rows = {r["id"]: r for r in c.execute(
        f"""SELECT f.id, f.name, f.mime, f.size FROM chat_files f JOIN agent_chat m ON m.id=f.message_id
            WHERE f.id IN ({','.join('?' * len(ids))}) AND m.agent_id=? AND m.user_id=? AND m.sender='user'""", (*ids, aid, uid))}
    if len(rows) != len(ids) or any(not (rows[i]["mime"] or "").startswith("image/") for i in ids):
        raise BadInput(tr("Invalid value: {0}", "image_ids"))
    return [{"id": i, "name": rows[i]["name"], "mime": rows[i]["mime"], "size": rows[i]["size"], "url": MTG_IMG_URL.format(i)}
            for i in ids]


def mtg_input(c, uid, b):
    """The job input of an "extract" request (proposals.py prop_input): list, members, notes and the meeting's images."""
    _p_keys(b, "", ("agent_id", "kind", "list_id", "text", "image_ids"))
    lid = _p_int(b.get("list_id"), "list_id")
    need_list(c, lid)
    lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if (lst["life"] or "") == "health":  # agents never see a health list (agent_emit would drop the request)
        raise BadInput(tr("Agents never see health projects"))
    if (lst["life"] or "") == "budget":  # 2.72.0 (#1333): nor a budget
        raise BadInput(tr("Health projects and budgets never reach an agent"))
    if lst["e2e"]:  # 2.64.1 (#1817): agents never get the texts of a list with the lock (names and sections are ciphertexts)
        from ..collab.liste2eguard import LE2B_OFF_MSG
        raise BadInput(tr(LE2B_OFF_MSG))
    imgs = mtg_images(c, uid, _p_int(b.get("agent_id"), "agent_id"), b.get("image_ids"))
    text = _p_str(b.get("text"), "text", PROP_TEXT_MAX, not imgs, line=False)
    ag = agent_ids(c)
    ppl = [p for p in sorted(list_people(c, lid)) if p not in ag]
    names = user_names(c, ppl)
    inp = {"list": {"id": lid, "name": "Inbox" if lst["is_inbox"] else lst["name"], "sections": [s["name"] for s in list_sections(c, uid, lid)]},
           "members": [{"id": p, "name": names.get(p, "")} for p in ppl],
           "text": text}
    if imgs:
        inp["images"] = imgs
    return inp, tr(PROP_TITLES["extract"], inp["list"]["name"][:80]), None, lid


def mtg_agent(c, aid):
    """The agent row the current person may ask for proposals AND chat with (else 404)."""
    if is_agent(g.user):
        raise Denied(403)
    need_collab()
    a = need_chat_agent(c, aid)
    if not prop_agent_ok(c, a, me()):
        raise Denied(404, tr("This agent cannot make proposals for you"))
    return a


@app.post("/api/agents/<int:aid>/meeting-images")
def mtg_upload(aid):
    """Multipart file (1..MTG_IMG_MAX images) -> stored as my message in my chat with agent aid (no 'chat' event: the agent
    gets them with the proposal request) -> {images: [{id, name, mime, size}], message_id}."""
    c = db()
    mtg_agent(c, aid)
    unknown = sorted(k for k in [*request.form, *request.files] if k != "file")
    if unknown:
        return err(str(UnknownFields(unknown)))
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        return err(tr("Missing field: {0}", "file"))
    if len(files) > MTG_IMG_MAX:
        return err(tr("At most {0} images", MTG_IMG_MAX))
    if any(not (f.mimetype or "").startswith("image/") for f in files):
        return err(tr("Only images"))
    try:
        r = chat_post(c, aid, me(), "user", {"body": ""}, files)
    except BadInput as e:
        return err(str(e))
    out = [{"id": x["id"], "name": x["name"], "mime": x["mime"], "size": x["size"]}
           for x in c.execute("SELECT id, name, mime, size FROM chat_files WHERE message_id=? ORDER BY id", (r["id"],))]
    c.commit()
    chat_unlink_trimmed()
    return jsonify(images=out, message_id=r["id"]), 201


@app.get("/api/agents/<int:aid>/meeting-proposals")
def mtg_cards(aid):
    """The ready "extract" proposals agent aid made for me (newest first, at most MTG_CARDS_MAX): the chat's cards.
    Only my own requests (need_prop's rule: the input is mine); proposals for other topics (cross) open in their dialog."""
    c = db()
    if is_agent(g.user) or not agent_row(c, aid):
        raise Denied(404)
    rows = c.execute("""SELECT * FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind='extract' AND prop_state='ready'
                        ORDER BY updated_at DESC, id DESC LIMIT ?""", (aid, me(), MTG_CARDS_MAX * 2)).fetchall()
    out = []
    for j in rows:
        inp = json.loads(j["input"] or "{}")
        p = json.loads(j["proposal"] or "null")
        if inp.get("cross") or not p:
            continue
        names = {m["id"]: m["name"] for m in inp.get("members", [])}
        out.append({"id": j["id"], "title": j["title"], "updated_at": j["updated_at"],
                    "list": {"id": (inp.get("list") or {}).get("id"), "name": (inp.get("list") or {}).get("name", "")},
                    "images": len(inp.get("images") or []), "summary": p.get("summary"),
                    "tasks": [{"title": t["title"], "due": t.get("due"), "assignee_id": t.get("assignee_id"),
                               "assignee": names.get(t.get("assignee_id"), "") if t.get("assignee_id") else ""}
                              for t in p.get("tasks", [])]})
        if len(out) >= MTG_CARDS_MAX:
            break
    return jsonify(proposals=out)
