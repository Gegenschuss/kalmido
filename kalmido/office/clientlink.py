"""2.59.0 (#1735): the address book search of the client dialog -- the contacts a person may link to a client's contact
persons (office/contacts_cl.py ckl_*: the organisation's address books, a freelancer's own ones). The link itself is saved
with the client (PATCH /api/clients/<id> {contacts: [{..., contact_id}]})."""
from flask import jsonify, request

from ..core.config import app
from ..core.db import db
from ..accounts.session import me
from ..office.contacts_cl import ckl_candidates
from ..team.clients import _gate, need_client


@app.get("/api/clients/<int:cid>/book-contacts")
def ckl_book_contacts(cid):
    """?q= -> {contacts: [{id, fn, org, title, email, phone, book}]} (at most 20) a person who sees client cid may link."""
    c = db()
    uid = me()
    _gate(c)
    cl = need_client(c, cid, uid)
    return jsonify(contacts=ckl_candidates(c, uid, cl, request.args.get("q", "")))
