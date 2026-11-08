"""2.640.0 (#4183): the team chat's change marker per room, kept by the database: tchat_room_sig holds per room the number of its
messages (n), of its pinned ones (pins), its newest message id (max_id) and a counter that moves on every change of a message
(rev: new, edited, deleted, restored, pinned, unpinned, re-encrypted, moved). The 4-second poll (/api/version, collab/teamchat.py
tchat_sig_q) sums these rows over the visible rooms instead of counting all their messages (COUNT / MAX over tchat_msgs, #2507).

The trigger catches every write path (the app's routes, the encryption passes, a hand-made statement, a room's cascade). A room
gets its row on the first change after this version: the trigger counts that room once (index tchat_msgs_room), from then on it
adds and subtracts. A room without a row counts as 0 in the marker, so no full count at the start; the marker also carries the
number and the id sum of the visible rooms (a room that becomes visible moves it).

No foreign key on room_id: a deleted room's cascade deletes its messages after the room row, an upsert there must not fail; the
row of a gone room is never summed again (the poll joins tchat_rooms). Additive only: an older version ignores the table, the
trigger only writes into it. Way back if ever needed: DROP TRIGGER kalmido_tchat_room_sig ON tchat_msgs."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS tchat_room_sig (
  room_id BIGINT PRIMARY KEY, n BIGINT NOT NULL DEFAULT 0, pins BIGINT NOT NULL DEFAULT 0,
  max_id BIGINT NOT NULL DEFAULT 0, -- no FK (2.658.0 #5101): the highest message id of the room as a marker, not a link
  rev BIGINT NOT NULL DEFAULT 0);
CREATE OR REPLACE FUNCTION kalmido_tchat_room_sig() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  r BIGINT;
  dn BIGINT := 0;
  dp BIGINT := 0;
  mx BIGINT := 0;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NULL; END IF;
  IF TG_OP = 'UPDATE' AND NEW.room_id IS DISTINCT FROM OLD.room_id THEN
    UPDATE tchat_room_sig SET n = n - 1, pins = pins - (CASE WHEN OLD.pinned_at IS NULL THEN 0 ELSE 1 END), rev = rev + 1
      WHERE room_id = OLD.room_id;
    dn := 1;
  END IF;
  IF TG_OP = 'DELETE' THEN
    r := OLD.room_id; dn := -1; dp := CASE WHEN OLD.pinned_at IS NULL THEN 0 ELSE -1 END;
  ELSE
    r := NEW.room_id; mx := NEW.id;
    IF TG_OP = 'INSERT' THEN
      dn := 1; dp := CASE WHEN NEW.pinned_at IS NULL THEN 0 ELSE 1 END;
    ELSE
      dp := (CASE WHEN NEW.pinned_at IS NULL THEN 0 ELSE 1 END)
            - (CASE WHEN OLD.pinned_at IS NULL OR NEW.room_id IS DISTINCT FROM OLD.room_id THEN 0 ELSE 1 END);
    END IF;
  END IF;
  UPDATE tchat_room_sig SET n = n + dn, pins = pins + dp, max_id = GREATEST(max_id, mx), rev = rev + 1 WHERE room_id = r;
  IF NOT FOUND THEN
    INSERT INTO tchat_room_sig(room_id, n, pins, max_id, rev)
      SELECT r, COUNT(*), COUNT(m.pinned_at), COALESCE(MAX(m.id), 0), 1 FROM tchat_msgs m WHERE m.room_id = r
      ON CONFLICT (room_id) DO UPDATE SET n = tchat_room_sig.n + dn, pins = tchat_room_sig.pins + dp,
        max_id = GREATEST(tchat_room_sig.max_id, mx), rev = tchat_room_sig.rev + 1;
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER kalmido_tchat_room_sig AFTER INSERT OR DELETE OR UPDATE ON tchat_msgs FOR EACH ROW EXECUTE FUNCTION kalmido_tchat_room_sig();
"""
