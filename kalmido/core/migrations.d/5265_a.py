"""2.755.0 (#5265, decided 08.11.2026): the table paperless_links goes. It held the Paperless documents linked to tasks; the
connection was taken out in 2.36.0 (#1116), since then nothing reads or writes it (no route, no export, no import). A one-way
step: its rows are lost (titles, correspondents and ids of documents in a Paperless server, that server keeps the documents);
a version before 2.755 makes the table again, empty (its schema.py), and the next start of this one drops it. schema.py no longer creates the table
nor its column steps (conn_id, added_by). The other old Paperless tables (pl_conns, pl_conn_users, pl_tokens, list_paperless)
stay as they are."""
# drop-ok paperless_links: dead since 2.36.0 (#1116), no code reads or writes it; decided 08.11.2026
AFTER = ["DROP TABLE IF EXISTS paperless_links"]
