"""2.1076.0 (#5271, review of 2.1076): the trigger kalmido_olnk_gone (5271_a) deletes the links of a row deleted for good as the
system -- row-level security of the person who deletes would leave the links whose workspace is another organisation's behind
(the same switch as kalmido_org_count, core/rls.py ORG_COUNT_SRC). And the kinds the generic links reach with their own table
get the trigger too: clients, knowledge pages, tables. Every other kind of the core's register loses its links in the core's
delete for good (core/writes.py _purge_rows).
"""
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_olnk_gone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text := current_setting('app.role', true);
BEGIN
  PERFORM set_config('app.role', 'system', true);
  DELETE FROM obj_links WHERE (src_kind = TG_ARGV[0] AND src_id = OLD.id) OR (dst_kind = TG_ARGV[0] AND dst_id = OLD.id);
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_olnk_gone_client AFTER DELETE ON clients FOR EACH ROW EXECUTE FUNCTION kalmido_olnk_gone('client');
CREATE OR REPLACE TRIGGER kalmido_olnk_gone_wiki_page AFTER DELETE ON wiki_pages FOR EACH ROW EXECUTE FUNCTION kalmido_olnk_gone('wiki_page');
CREATE OR REPLACE TRIGGER kalmido_olnk_gone_sheet AFTER DELETE ON sheets FOR EACH ROW EXECUTE FUNCTION kalmido_olnk_gone('sheet_table');
"""
