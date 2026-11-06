"""2.566.0 (#4712): the shared core, stage 3 -- calendars (ev_cals, kind 'evcal') and address books (books, kind 'address_book')
are object kinds of the core (core/objects.py). They get the core's columns they lack: rev, created_by, updated_at, updated_by,
deleted_at (calendars; the books have it since 2.272.0) and deleted_by. ev_cals.deleted_at = the calendar's trash (#4707): a
calendar there is gone for everyone but who may restore it; its events stay as they are. updated_at '' on old rows = no version
check until their next change (core/conflict.py ccf_check compares only a version the client sent).

The core's shares of the two kinds are rows of fs_shares on the object's reference node. The trigger kalmido_kern_mirror keeps
them equal to the old member tables ev_cal_members / book_members (a row added, its role changed, a row deleted -- by whatever
code path, also imports and repairs) as soon as the object HAS a node: the one-shot of the start (flag migr_kern4712,
events/model.py ev_kern_copy) gives every calendar / address book with members its node, a new member gets it first
(cal_member_set / book_member_set). From then on the core's share is what counts (events/model.py ev_role, contacts/model.py
book_role); the old row is read only for an object without a node, one release long (stage 7 removes the tables). So a share
taken back in the core (the file store's share dialog, obj_revoke_person) is not reopened by the old row. The trigger works
in the system context (a member removing themselves need not see the organisation's node) and restores the caller's.
Review F4: a node of the two kinds made by any path (the first member, a share in the core, filing it in a folder, an import)
mirrors ALL member rows the object has at that moment (kalmido_kern_node_made fires the mirror with UPDATE ... SET role=role, as
the one-shot does): rows written past cal_member_set / book_member_set while there was no node (import, repair) keep their access.
Review F3: a node in the file store's trash is still the object's node (its shares count, the old rows are not read again); a
node removed for good (the trash emptied, taken out of every folder, the organisation's tree gone) first writes its shares to
people and agents back into the member rows (kalmido_kern_node_gone: rows without a share go, the others get its role), so the
fallback reader then gives exactly what the node gave -- a share taken back in the core is not reopened.
New columns, functions and triggers only (nullable or with a DEFAULT): an older version ignores the columns -- its calendars
in the trash would show again --, the trigger keeps mirroring for it, nothing breaks; a backup restores them (kalmido_*).
"""
# 2.585.0 (#4841): the WHEN of the two fs_nodes triggers is written as Postgres prints it (pg_get_triggerdef): core/db.py tg_same
# compares the text, so `IN (...)` / an untyped literal counted as changed and every start replaced both under a SHARE ROW EXCLUSIVE
# lock on fs_nodes (tools/check_migrations.py now flags that)
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_kern_mirror() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r JSONB; rid BIGINT; who BIGINT; nid BIGINT; ag BOOLEAN; prev TEXT;
BEGIN
  r := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  IF current_setting('app.kern_sync', true) = '1' THEN
    RETURN NULL;  -- review F3: kalmido_kern_node_gone writes the node's shares back into the rows (nothing to mirror)
  END IF;
  rid := (r->>TG_ARGV[1])::BIGINT;
  who := (r->>'user_id')::BIGINT;
  prev := current_setting('app.role', true);
  PERFORM set_config('app.role', 'system', true);
  SELECT id INTO nid FROM fs_nodes WHERE kind = 'ref' AND ref_kind = TG_ARGV[0] AND ref_id = rid;
  IF nid IS NOT NULL THEN
    IF TG_OP = 'DELETE' THEN
      DELETE FROM fs_shares WHERE node_id = nid AND (user_id = who OR agent_id = who);
    ELSE
      UPDATE fs_shares SET role = r->>'role' WHERE node_id = nid AND (user_id = who OR agent_id = who);
      IF NOT FOUND THEN
        ag := EXISTS (SELECT 1 FROM users WHERE id = who AND kind = 'agent');
        INSERT INTO fs_shares(node_id, user_id, agent_id, role, created_at, by_role)
          VALUES (nid, CASE WHEN ag THEN NULL ELSE who END, CASE WHEN ag THEN who END, r->>'role',
                  to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'), 'mirror');
      END IF;
    END IF;
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_kern_mirror_cal AFTER INSERT OR DELETE OR UPDATE OF role ON ev_cal_members FOR EACH ROW EXECUTE FUNCTION kalmido_kern_mirror('evcal', 'cal_id');
CREATE OR REPLACE TRIGGER kalmido_kern_mirror_book AFTER INSERT OR DELETE OR UPDATE OF role ON book_members FOR EACH ROW EXECUTE FUNCTION kalmido_kern_mirror('address_book', 'book_id');
CREATE OR REPLACE FUNCTION kalmido_kern_node_made() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev TEXT;
BEGIN
  prev := current_setting('app.role', true);
  PERFORM set_config('app.role', 'system', true);
  IF NEW.ref_kind = 'evcal' THEN
    UPDATE ev_cal_members SET role = role WHERE cal_id = NEW.ref_id;
  ELSE
    UPDATE book_members SET role = role WHERE book_id = NEW.ref_id;
  END IF;
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_kern_node_made AFTER INSERT ON fs_nodes FOR EACH ROW WHEN (NEW.kind = 'ref'::text AND (NEW.ref_kind = ANY (ARRAY['evcal'::text, 'address_book'::text]))) EXECUTE FUNCTION kalmido_kern_node_made();
CREATE OR REPLACE FUNCTION kalmido_kern_node_gone() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev TEXT; ts TEXT;
BEGIN
  prev := current_setting('app.role', true);
  PERFORM set_config('app.role', 'system', true);
  PERFORM set_config('app.kern_sync', '1', true);
  ts := to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"');
  IF OLD.ref_kind = 'evcal' THEN
    DELETE FROM ev_cal_members m WHERE m.cal_id = OLD.ref_id AND NOT EXISTS (SELECT 1 FROM fs_shares s WHERE s.node_id = OLD.id
      AND COALESCE(s.user_id, s.agent_id) = m.user_id AND (s.expires_at IS NULL OR s.expires_at > ts));
    UPDATE ev_cal_members m SET role = s.role FROM fs_shares s WHERE s.node_id = OLD.id AND COALESCE(s.user_id, s.agent_id) = m.user_id
      AND m.cal_id = OLD.ref_id AND s.role IN ('view', 'edit') AND m.role <> s.role AND (s.expires_at IS NULL OR s.expires_at > ts);
    INSERT INTO ev_cal_members(cal_id, user_id, role, added_at)
      SELECT DISTINCT ON (u.id) OLD.ref_id, u.id, s.role, COALESCE(NULLIF(s.created_at, ''), ts) FROM fs_shares s
      JOIN users u ON u.id = COALESCE(s.user_id, s.agent_id) JOIN ev_cals k ON k.id = OLD.ref_id AND k.owner_id <> u.id
      WHERE s.node_id = OLD.id AND s.role IN ('view', 'edit') AND (s.expires_at IS NULL OR s.expires_at > ts)
      ORDER BY u.id, (s.role = 'edit') DESC ON CONFLICT DO NOTHING;
  ELSE
    DELETE FROM book_members m WHERE m.book_id = OLD.ref_id AND NOT EXISTS (SELECT 1 FROM fs_shares s WHERE s.node_id = OLD.id
      AND COALESCE(s.user_id, s.agent_id) = m.user_id AND (s.expires_at IS NULL OR s.expires_at > ts));
    UPDATE book_members m SET role = s.role FROM fs_shares s WHERE s.node_id = OLD.id AND COALESCE(s.user_id, s.agent_id) = m.user_id
      AND m.book_id = OLD.ref_id AND s.role IN ('view', 'edit') AND m.role <> s.role AND (s.expires_at IS NULL OR s.expires_at > ts);
    INSERT INTO book_members(book_id, user_id, role, added_at)
      SELECT DISTINCT ON (u.id) OLD.ref_id, u.id, s.role, COALESCE(NULLIF(s.created_at, ''), ts) FROM fs_shares s
      JOIN users u ON u.id = COALESCE(s.user_id, s.agent_id) JOIN books b ON b.id = OLD.ref_id
      WHERE s.node_id = OLD.id AND s.role IN ('view', 'edit') AND (s.expires_at IS NULL OR s.expires_at > ts)
      ORDER BY u.id, (s.role = 'edit') DESC ON CONFLICT DO NOTHING;
  END IF;
  PERFORM set_config('app.kern_sync', '', true);
  PERFORM set_config('app.role', COALESCE(prev, ''), true);
  RETURN OLD;
END $$;
CREATE OR REPLACE TRIGGER kalmido_kern_node_gone BEFORE DELETE ON fs_nodes FOR EACH ROW WHEN (OLD.kind = 'ref'::text AND (OLD.ref_kind = ANY (ARRAY['evcal'::text, 'address_book'::text]))) EXECUTE FUNCTION kalmido_kern_node_gone();
"""
MIGRATIONS = [
    ("ev_cals", "rev", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("ev_cals", "created_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS created_by BIGINT"),  # who: no FK (the history keeps a gone account's id)
    ("ev_cals", "updated_at", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
    ("ev_cals", "updated_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("ev_cals", "deleted_at", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS deleted_at TEXT"),
    ("ev_cals", "deleted_by", "ALTER TABLE ev_cals ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
    ("books", "rev", "ALTER TABLE books ADD COLUMN IF NOT EXISTS rev BIGINT NOT NULL DEFAULT 1"),
    ("books", "created_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS created_by BIGINT"),
    ("books", "updated_at", "ALTER TABLE books ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''"),
    ("books", "updated_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS updated_by BIGINT"),
    ("books", "deleted_by", "ALTER TABLE books ADD COLUMN IF NOT EXISTS deleted_by BIGINT"),
]
AFTER = [
    "CREATE INDEX IF NOT EXISTS ix4712_ev_cals_trash ON ev_cals(deleted_at) WHERE deleted_at IS NOT NULL",
]
