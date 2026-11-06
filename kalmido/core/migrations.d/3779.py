"""2.574.0 (#3779): sharing through the ntfy app is gone (decided 30.10.2026): the personal share inboxes (table ntfy_inboxes,
2.142.0 #2150) go with their rows (topic, own server, sealed read token). A one-way step: versions before 2.574 still poll it
and fail on the missing table (their inbox loop only logs it). schema.py no longer creates the table."""
# drop-ok ntfy_inboxes: the feature is taken out (decided 30.10.2026); its rows are a topic and a sealed token per person, nothing else uses them
AFTER = ["DROP TABLE IF EXISTS ntfy_inboxes"]
