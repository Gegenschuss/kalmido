"""Contacts: the REST API v1 (+ MCP) and its OpenAPI part (scope "contacts": personal data, never a default)."""
from flask import jsonify, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db
from ..accounts.session import me
from ..core.access import need_feat
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, reject_unknown
from ..api.v1 import cursor_dec, cursor_enc, v1_args, v1_json, v1_limit, v1_view
from ..contacts.model import BOOK_ROLES, CT_KINDS, CT_LINKS
from ..contacts.web import (
    op_book_delete, op_book_edit, op_book_member, op_book_member_rm, op_book_new, op_books, op_contact, op_contact_delete,
    op_contact_edit, op_contact_new, op_contacts, op_export, op_import, op_link, op_unlink, VCF_MAX,
)


@app.get("/api/v1/address-books")
@v1_view
def v1_books():
    v1_args(())
    need_feat("contacts")
    return jsonify(data=op_books(db(), me()), next_cursor=None)


@app.post("/api/v1/address-books")
@v1_view
def v1_book_new():
    v1_args(())
    need_feat("contacts")
    return jsonify(op_book_new(db(), me(), v1_json())), 201


@app.patch("/api/v1/address-books/<int:bid>")
@v1_view
def v1_book_edit(bid):
    v1_args(())
    need_feat("contacts")
    return jsonify(op_book_edit(db(), me(), bid, v1_json()))


@app.delete("/api/v1/address-books/<int:bid>")
@v1_view
def v1_book_delete(bid):
    v1_args(())
    need_feat("contacts")
    op_book_delete(db(), me(), bid)
    return Response(status=204)


@app.put("/api/v1/address-books/<int:bid>/members/<user_id>")
@v1_view
def v1_book_member(bid, user_id):
    v1_args(())
    uid = as_int(user_id, "user_id", 1)
    need_feat("contacts")
    b = v1_json()
    reject_unknown(b, ("role",))
    return jsonify(op_book_member(db(), me(), bid, {"user_id": uid, "role": b.get("role") or "view"}))


@app.delete("/api/v1/address-books/<int:bid>/members/<user_id>")
@v1_view
def v1_book_member_rm(bid, user_id):
    v1_args(())
    uid = as_int(user_id, "user_id", 1)
    need_feat("contacts")
    op_book_member_rm(db(), me(), bid, uid)
    return Response(status=204)


@app.post("/api/v1/address-books/<int:bid>/import")
@v1_view
def v1_book_import(bid):
    """{vcf: "<the text of a .vcf file>"}"""
    v1_args(())
    need_feat("contacts")
    b = v1_json()
    reject_unknown(b, ("vcf",))
    if not isinstance(b.get("vcf"), str) or not b["vcf"].strip():
        raise BadInput(tr("Invalid value: {0}", "vcf"))
    raw = b["vcf"].encode("utf-8")
    if len(raw) > VCF_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
    return jsonify(op_import(db(), me(), bid, raw))


@app.get("/api/v1/address-books/<int:bid>/export")
@v1_view
def v1_book_export(bid):
    v1_args(())
    need_feat("contacts")
    return jsonify(vcf=op_export(db(), me(), bid))


@app.get("/api/v1/contacts")
@v1_view
def v1_contacts():
    a = v1_args(("q", "book_id", "group", "limit", "cursor"))
    need_feat("contacts")
    lim, off = v1_limit(a), cursor_dec("c", a.get("cursor"))
    res = op_contacts(db(), me(), {"q": a.get("q"), "book_id": a.get("book_id"), "group": a.get("group"), "limit": lim, "offset": off})
    nxt = cursor_enc("c", off + lim) if res["total"] > off + lim else None
    return jsonify(data=res["items"], next_cursor=nxt, total=res["total"], groups=res["groups"])


@app.post("/api/v1/contacts")
@v1_view
def v1_contact_new():
    v1_args(())
    need_feat("contacts")
    return jsonify(op_contact_new(db(), me(), v1_json())), 201


@app.get("/api/v1/contacts/<int:cid>")
@v1_view
def v1_contact(cid):
    v1_args(())
    need_feat("contacts")
    return jsonify(op_contact(db(), me(), cid))


@app.patch("/api/v1/contacts/<int:cid>")
@v1_view
def v1_contact_edit(cid):
    v1_args(())
    need_feat("contacts")
    return jsonify(op_contact_edit(db(), me(), cid, v1_json()))


@app.delete("/api/v1/contacts/<int:cid>")
@v1_view
def v1_contact_delete(cid):
    v1_args(())
    need_feat("contacts")
    op_contact_delete(db(), me(), cid)
    return Response(status=204)


@app.post("/api/v1/tasks/<int:tid>/contacts")
@v1_view
def v1_task_contact(tid):
    from ..api.scopes import need_scope
    v1_args(())
    need_feat("contacts")
    need_scope("tasks:write")
    return jsonify(op_link(db(), me(), tid, v1_json()))


@app.delete("/api/v1/tasks/<int:tid>/contacts/<contact_id>")
@v1_view
def v1_task_contact_rm(tid, contact_id):
    from ..api.scopes import need_scope
    v1_args(())
    need_feat("contacts")
    need_scope("tasks:write")
    op_unlink(db(), me(), tid, as_int(contact_id, "contact_id", 1))
    return Response(status=204)


def contacts_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    K, S = "Contacts", "contacts"
    schemas["AddressBook"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"}, "owner_id": {"type": "integer"},
        "owner_name": {"type": "string"}, "role": {"type": "string", "enum": ["owner", *BOOK_ROLES]}, "count": {"type": "integer"},
        "imported": {"type": "boolean", "description": "Mirrors an external CardDAV account (module Family)"},
        "birthdays_list_id": nul("integer", description="Birthdays + anniversaries of its contacts become tasks of this list (owner)"),
        "members": {"type": "array", "items": {"type": "object"}}}}
    schemas["AddressBookPage"] = page("AddressBook")
    item = {"type": "object", "properties": {"value": {"type": "string"}, "type": {"type": "array", "items": {"type": "string"}},
                                             "pref": {"type": "boolean"}, "label": {"type": "string"}}}
    adr = {"type": "object", "properties": {k: {"type": "string"} for k in ("street", "city", "region", "code", "country", "pobox", "ext", "label")}
           | {"type": {"type": "array", "items": {"type": "string"}}, "pref": {"type": "boolean"}}}
    props = {"book_id": {"type": "integer"}, "kind": {"type": "string", "enum": list(CT_KINDS)},
             **{k: {"type": "string"} for k in ("fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "note")},
             "emails": {"type": "array", "items": item}, "phones": {"type": "array", "items": item}, "urls": {"type": "array", "items": item},
             "addresses": {"type": "array", "items": adr},
             "bday": {"type": "string", "description": "YYYY-MM-DD, or --MM-DD without the year"}, "anniversary": {"type": "string"},
             "groups": {"type": "array", "items": {"type": "string"}},
             "photo": {"type": "string", "description": "data:image/jpeg;base64,... (JPEG, PNG, GIF, WebP) or empty"}}
    schemas["Contact"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "uid": {"type": "string"}, **props, "role": {"type": "string"},
        "tasks": {"type": "array", "items": {"type": "object", "properties": {"task_id": {"type": "integer"}, "kind": {"type": "string", "enum": list(CT_LINKS)},
                                                                              "title": {"type": "string"}, "status": {"type": "integer"}}}},
        "events": {"type": "array", "items": {"type": "object"}}, "created_at": {"type": "string"}, "updated_at": {"type": "string"}}}
    schemas["ContactBrief"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "book_id": {"type": "integer"}, "fn": {"type": "string"}, "org": {"type": "string"}, "kind": {"type": "string"},
        "email": {"type": "string"}, "phone": {"type": "string"}, "photo": {"type": "boolean"}, "bday": {"type": "string"},
        "groups": {"type": "array", "items": {"type": "string"}}}}
    schemas["ContactPage"] = {**page("ContactBrief"), "properties": {**page("ContactBrief")["properties"], "total": {"type": "integer"},
                                                                     "groups": {"type": "array", "items": {"type": "string"}}}}
    bid_p, cid_p, uid_p = pid("id", "Address book id"), pid("id", "Contact id"), pid("user_id", "User id")
    book_in = {"type": "object", "properties": {"name": {"type": "string"}, "color": {"type": "string"}}}
    paths["/address-books"] = {
        "get": op("2.21.0 (module Contacts): the address books the token's user sees (own + shared)", K, ok(ref("AddressBookPage")) | errs("409"), scope=S),
        "post": op("A new own address book", K, ok(ref("AddressBook"), "Created", "201") | errs("400", "409"), body={**book_in, "required": ["name"]}, scope=S)}
    paths["/address-books/{id}"] = {
        "patch": op("Rename / recolour an address book, choose the list for its birthdays (owner)", K, ok(ref("AddressBook")) | errs("400", "403", "404"),
                    [bid_p], body={**book_in, "properties": {**book_in["properties"], "birthdays_list_id": nul("integer")}}, scope=S),
        "delete": op("Delete an address book with its contacts (owner)", K, {"204": {"description": "Deleted"}} | errs("403", "404"), [bid_p], scope=S)}
    paths["/address-books/{id}/members/{user_id}"] = {
        "put": op("Share an address book: view or edit (owner)", K, ok(ref("AddressBook")) | errs("400", "403", "404", "409"), [bid_p, uid_p],
                  body={"type": "object", "properties": {"role": {"type": "string", "enum": list(BOOK_ROLES)}}}, scope=S),
        "delete": op("Stop sharing (owner) or leave a shared address book", K, {"204": {"description": "Removed"}} | errs("403", "404"), [bid_p, uid_p], scope=S)}
    paths["/address-books/{id}/import"] = {"post": op("Import a vCard file (3.0 / 4.0): the same UID is updated", K,
                                                      ok({"type": "object", "properties": {k: {"type": "integer"} for k in ("created", "updated", "unchanged", "errors")}})
                                                      | errs("400", "403", "404"), [bid_p],
                                                      body={"type": "object", "required": ["vcf"], "properties": {"vcf": {"type": "string"}}}, scope=S)}
    paths["/address-books/{id}/export"] = {"get": op("The address book as a vCard text", K, ok({"type": "object", "properties": {"vcf": {"type": "string"}}})
                                                     | errs("404"), [bid_p], scope=S)}
    paths["/contacts"] = {
        "get": op("Search the contacts (name, company, e-mail, phone, address, group); groups = every group name", K, ok(ref("ContactPage")) | errs("400", "404"),
                  [q("q", "Search words"), q("book_id", "Only this address book", {"type": "integer"}), q("group", "Only this group"),
                   q("limit", "Page size (1-500, default 100)", {"type": "integer"}), q("cursor", "next_cursor of the previous page")], scope=S),
        "post": op("Create a contact", K, ok(ref("Contact"), "Created", "201") | errs("400", "403", "404", "409"), body={"type": "object", "properties": props}, scope=S)}
    paths["/contacts/{id}"] = {
        "get": op("One contact with its linked tasks and events", K, ok(ref("Contact")) | errs("404"), [cid_p], scope=S),
        "patch": op("Change a contact (only the fields given)", K, ok(ref("Contact")) | errs("400", "403", "404", "409"), [cid_p],
                    body={"type": "object", "properties": {**props, "expect": {"type": "string"}}}, scope=S),
        "delete": op("Delete a contact", K, {"204": {"description": "Deleted"}} | errs("403", "404"), [cid_p], scope=S)}
    paths["/tasks/{id}/contacts"] = {"post": op(
        "Link a contact to a task: waiting (the task waits on them), responsible (they do it, outside Kalmido) or about (needs tasks:write too)", K,
        ok({"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object"}}}}) | errs("400", "403", "404"), [pid()],
        body={"type": "object", "required": ["contact_id"], "properties": {"contact_id": {"type": "integer"},
                                                                            "kind": {"type": "string", "enum": list(CT_LINKS)}}}, scope=S)}
    paths["/tasks/{id}/contacts/{contact_id}"] = {"delete": op("Remove the link (needs tasks:write too)", K, {"204": {"description": "Removed"}} | errs("403", "404"),
                                                              [pid(), pid("contact_id", "Contact id")], scope=S)}
