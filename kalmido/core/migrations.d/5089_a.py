"""2.652.0 (#5089): sharing anew in the calendar / address book dialog brings a person back whose share in the core ran out.
kalmido_kern_mirror (4712_a.py) mirrored a member row added or changed in ev_cal_members / book_members into the shares of the
object's reference node by setting only the role: a share there with an expiry date in the past kept it, and the person stayed
out although the owner had just shared again (events/model.py cal_member_set / contacts/model.py book_member_set always write
the row, which fires the trigger, also with the same role). Now an added or changed old row also sets expires_at = NULL on the
person's / agent's shares of that node: sharing in those dialogs is without end date, as the dialog shows it. A share given an
end date in the file store's share dialog keeps it until the old row is written again (the owner shares in the old dialog, an
import or a repair writes the row); its expiry alone changes nothing (kalmido_kern_back, 5046_a.py: no UPDATE OF expires_at).
The mirror's own UPDATE still fires kalmido_kern_back (UPDATE OF role); that one finds the old row as the share has it: a no-op.

The same function as 4712_a.py with that one column more, replaced here: the fragments run sorted by file name, so this body
wins on every start (4712_a.py's CREATE OR REPLACE runs first). The triggers stay as 4712_a.py made them. The way back: an
older version's start writes 4712_a.py's body again (shares then keep their expiry when shared anew, the error of before).
fs_shares.expires_at exists since 2.48.
"""
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
      -- 2.652.0 (#5089): sharing anew = without end date (a share run out in the core lets the person in again)
      UPDATE fs_shares SET role = r->>'role', expires_at = NULL WHERE node_id = nid AND (user_id = who OR agent_id = who);
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
"""
