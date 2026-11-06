"""2.542.0 (#4598): a finalised document (office_docs.locked_at set) is held by the database itself, next to the app's checks
(ledger.ofx_need_editable): an UPDATE that changes anything but the columns in `free`, or a DELETE, is refused -- so no row
drifts silently away from the PDF / XML it was mailed as (a forgotten check, a new write path, a hand-made SQL statement).

What may still change on a finalised row (the app's write paths of 2.542, docs/OFFICE.md "Finalised documents in the database"):
status (payments, sending, cancellation, a quotation's answer; never back to 'draft'), sent_at, paid_at, updated_at,
datev_sent_at, reminder_fee_state / reminder_fee_paid_at, cashflow (planning flag), list_id (project), client_id (client merge / a deleted client),
contract_id (a deleted contract), replaces_id / version_of (the quotation chain), producing_on and pdf_sha256 / xml_sha256
only while still empty (the start's fill, storing the files), the hash chain columns chain_key / chain_seq / chain_prev /
chain_hash while the row has no place yet (office/chain.py hch_append right after the finalising, hch_migrate), and on a trial document source_doc_id / cancels_id emptied
(a trial document it pointed at was deleted). Everything else: the PDF's content, the number, the date, the snapshots.

A DELETE goes through for a trial document (deleted at any time, #2576) and for the database's own reference actions
(pg_trigger_depth() > 1: an organisation that goes for good takes its documents with it, ON DELETE CASCADE).
Deliberate exceptions of the app run inside ledger.ofx_release (the transaction-local switch kalmido.locked_ok = 'on'):
taking a never-sent quotation back to a draft / deleting it, the encryption passes, moving a personal office, the
organisation import and its undo. The suites' own database access (tests/dbx.py) sets the switch for its session.

Additive only, but an older version has no ofx_release: after a rollback of the app its deliberate exceptions (unlock or
delete a finalised quotation never sent, private office into an organisation, organisation import and its undo, the
encryption passes) would fail on the trigger, so the way back of the app includes
DROP TRIGGER kalmido_office_locked ON office_docs (and DROP FUNCTION kalmido_office_locked()). The function reads the rows as
JSON, so a column that does not exist yet (an older database during its first start) breaks nothing."""
SCHEMA = """
CREATE OR REPLACE FUNCTION kalmido_office_locked() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  free TEXT[] := ARRAY['status', 'sent_at', 'paid_at', 'updated_at', 'datev_sent_at', 'reminder_fee_state', 'reminder_fee_paid_at', 'cashflow',
                       'list_id', 'client_id', 'contract_id', 'replaces_id', 'version_of'];
  o JSONB := to_jsonb(OLD);
  n JSONB;
  k TEXT;
  bad TEXT;
BEGIN
  IF COALESCE(o->>'locked_at', '') = '' OR current_setting('kalmido.locked_ok', true) = 'on' THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF COALESCE(o->>'trial', '0') NOT IN ('0', '') OR pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'office document % is finalised and cannot be deleted', OLD.id USING HINT = 'kalmido #4598';
  END IF;
  n := to_jsonb(NEW);
  IF n->>'status' = 'draft' AND COALESCE(o->>'status', '') <> 'draft' THEN
    RAISE EXCEPTION 'office document % is finalised: its status cannot go back to draft', OLD.id USING HINT = 'kalmido #4598';
  END IF;
  FOREACH k IN ARRAY ARRAY['pdf_sha256', 'xml_sha256', 'producing_on'] LOOP
    IF COALESCE(o->>k, '') = '' THEN free := free || k; END IF;
  END LOOP;
  IF o->>'chain_seq' IS NULL THEN
    free := free || ARRAY['chain_key', 'chain_seq', 'chain_prev', 'chain_hash'];
  END IF;
  IF COALESCE(o->>'trial', '0') NOT IN ('0', '') THEN
    FOREACH k IN ARRAY ARRAY['source_doc_id', 'cancels_id'] LOOP
      IF n->>k IS NULL THEN free := free || k; END IF;
    END LOOP;
  END IF;
  o := o - free;
  n := n - free;
  IF o IS DISTINCT FROM n THEN
    SELECT string_agg(e.key, ', ' ORDER BY e.key) INTO bad FROM jsonb_each(o) e WHERE e.value IS DISTINCT FROM n->e.key;
    RAISE EXCEPTION 'office document % is finalised: % cannot change', OLD.id, COALESCE(bad, 'a column') USING HINT = 'kalmido #4598';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER kalmido_office_locked BEFORE DELETE OR UPDATE ON office_docs FOR EACH ROW EXECUTE FUNCTION kalmido_office_locked();
"""
