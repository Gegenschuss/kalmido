"""2.620.0 (#4586, review C M1): task_offer_links.list_id is no longer read (office/offertasks.py joins tasks.list_id), but the
column still has its key to lists with ON DELETE CASCADE: a task moved from project P1 to P2 lost its link when P1 was deleted for
good, and the next version of the quotation offered its position again as new. The trigger kalmido_offer_link_list keeps the
column equal to the task's list on every way a task changes its list (move, its subtasks, import, repair), so only the deletion
of the list the task is in takes the link along (with the task itself); the links of tasks moved before 2.620 follow once at
the start (core/db.py, flag migr_offerlist4586). The index on root_id serves the joins of the chain.
New function, trigger and index only: an older version keeps writing the start value and ignores the rest, nothing breaks."""
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_offer_link_list() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE task_offer_links SET list_id = NEW.list_id WHERE task_id = NEW.id AND list_id IS DISTINCT FROM NEW.list_id;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_offer_link_list AFTER UPDATE OF list_id ON tasks FOR EACH ROW WHEN (old.list_id IS DISTINCT FROM new.list_id) EXECUTE FUNCTION kalmido_offer_link_list();
"""
AFTER = [
    "CREATE INDEX IF NOT EXISTS task_offer_links_root ON task_offer_links(root_id)",
]
