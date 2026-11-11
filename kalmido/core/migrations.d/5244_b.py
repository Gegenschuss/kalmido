"""2.937.0 (#5244, decided 08.11.2026): the shared core, stage 7c -- knowledge pages. A person share of a knowledge page or
folder is only the share of its reference node (fs_shares 'view'; a folder share: the folder's node + the node of the page of
the same name, its "pair"), the core alone decides who reads (wkfshare.py wkfs_rows, wkfolder.py wkf_role). wiki_shares keeps
the public links (kind 'link', token_hash, WSH_MAKER) only.

wiki_share_cards: the card data of a person share made in the knowledge dialog, on the share itself (fs_share_id, gone with
the share: ON DELETE CASCADE) -- folder (a folder share, also when only the page of its name has a node), pair_id (the share of
a folder share on the page of the same name), images (the switch "show embedded pictures", 2.380 H #2356), email (the address
typed in, sealed for the owner: shown instead of the account's name). A small table of its own instead of columns on
fs_shares: fs_shares is the file store's for every area and needs no knowledge columns. The dialog's id of such a share is
"p<fs_shares id>" (wiki/wkshare.py WSH_PID); revoking keeps the card in the share's obj_revoked row ("wiki_card"), the Undo
puts both shares back under their ids (core/objects.py obj_node_reshare).

The old person rows go at the start (wiki/wkshare.py wsh_retire, core/objhooks.START, every start until done, inside init_db's
one transaction, core/kernretire.py kern_retire_rows under the lock kalmido-kern5069):
1. wsh_carry: the last forward copy (a live person row without a core share gets one when its page / folder has a node) and
   a card for every live person row with a core share; nothing is taken back;
2. start check (wsh_left): a live person row whose core share has no card, or without any core share while its page / folder
   has a node -- not 0: nothing is dropped, the log names the number, the admins get an alert (kind "storage"), the next
   start checks again;
3. else DELETE the person rows of wiki_shares, DROP COLUMN core_id / core_id2 (4717_a.py no longer adds them), expires_at /
   last_used_at / revoked_at / created_at -> TIMESTAMPTZ, is_folder -> BOOLEAN (#5305; core/schema.py makes them so for a new
   database), the rows of obj_revoked with src 'wiki_shares', and the database's back limit rises to this minor.
One way: the person rows of wiki_shares (the shares of the nodes and their cards hold the same people, expiry and switches; a
row that gave nothing -- revoked, expired, ended elsewhere, a page in the trash, a locked space -- is lost). A version before
2.937 would read its person shares from wiki_shares (empty) and no longer list them in the dialog; the back limit stops it.
Count on a live database beforehand (psql; live rows the start check would hold on):
  SELECT COUNT(*) FROM wiki_shares s WHERE s.kind='person' AND s.revoked_at IS NULL AND s.user_id IS NOT NULL
    AND (s.expires_at IS NULL OR s.expires_at > to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'))
    AND s.core_id IS NULL AND s.core_id2 IS NULL;
"""
# drop-ok wiki_shares.core_id: decided 08.11.2026 (#5244): a person share is the share of its node with a card in wiki_share_cards; dropped by wiki/wkshare.py wsh_retire after its check
# drop-ok wiki_shares.core_id2: decided 08.11.2026 (#5244): the pair of a folder share is wiki_share_cards.pair_id; dropped by wiki/wkshare.py wsh_retire after its check
SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_share_cards (
  fs_share_id BIGINT PRIMARY KEY REFERENCES fs_shares(id) ON DELETE CASCADE,
  folder BOOLEAN NOT NULL DEFAULT false,
  pair_id BIGINT REFERENCES fs_shares(id) ON DELETE SET NULL,
  images BOOLEAN NOT NULL DEFAULT false,
  email TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS wiki_share_cards_pair ON wiki_share_cards(pair_id) WHERE pair_id IS NOT NULL;
"""
MIGRATIONS = []
AFTER = []
