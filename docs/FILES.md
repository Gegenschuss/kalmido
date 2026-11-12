# Files and knowledge

Files and documents, offline knowledge, office projects and pictures.

## Files and documents

Since 2.48.0.

**Files** (#1207) keeps folders and files for you and for each organisation, with versions (upload the same name again),
a trash with undo and links to task and project files that keep the original's rights. Share a folder or file with
people, groups or agents to view or edit, optionally until a date; shares are inherited by everything below and never
leave the workspace. Agents see only what is shared with them, write their results into their own folder, and every
agent access shows up in the file's history. Who a folder or file is shared with stands in plain sight (2.558.0, #4693): the open folder has
"Share" on top and below it "Shared with Anna, Ben · agent X" (the shares of the folders above included) or "Only you";
each row and card names its shares (from three on "Anna +2", a click opens the Share dialog), and the end of a scan says who
sees the new file. Only who may share a node sees these names; whoever it is shared with sees "Shared by <name>".

**Documents** (#1111) is the place for letters, invoices and contracts: drop PDFs, scans or photos, share them from the
phone, forward them by mail or put them into *Documents/Inbox*. A **folder watcher** (Mac, Windows, Linux; upload-only key) scans from a desktop folder straight into Kalmido. Kalmido reads scans locally (German and English),
finds date, due date and amount, and sorts in sender, type, tags and folder by your rules or by learning from your
corrections; what it is unsure about waits in *To review*. Search finds words from the content. Text and amounts are
stored encrypted. Self-hosters can import an existing Paperless-ngx instance (#1152).

**Leafing through documents** (2.476.0): an open document shows "3 of 48" and two arrow buttons above the preview, and the arrow keys step through the list as it is shown (filtered and sorted). On a phone or tablet a swipe sideways anywhere on the document (preview, head or fields; 2.882, the same swipe as in the task panel) turns to the next or previous document; at the end of the loaded part the next page loads, at the real end the page springs back. Typing or marking text in a field, parts that scroll sideways and the screen's edge (the phone's Back gesture) do not swipe. A preview enlarged with two fingers moves with one finger instead; at normal size it swipes again. The preview stands at its final size from the first picture, it does not jump while the file loads.

**Receipt fetcher** (2.425.0): a helper program on your own computer fetches invoices from web portals (an online shop, a phone company) and hands them to the documents. You sign in to the portals only in the helper: Kalmido never stores passwords, cookies or logins. Connect one in *Settings > Integrations > Receipt fetcher* with a setup code (for people with the office); switch each portal on or off in Kalmido. The documents arrive like an upload and are recognised the same way; a new error ("please sign in again") tells you once. Details: [API.md](API.md#receipt-fetcher).

**PDF preview** (#1367): PDFs open inside Kalmido (pages, zoom, swipe), also in the Android app. **Lock a note**
(#1642): the lock in a task's note encrypts it with your own password in your own, unshared projects; without the
password and the recovery code it cannot be recovered, not even by the operator.

**Word and Excel preview** (2.92.0, #1926): a .docx or .xlsx file at a task, a comment, in the project files or the file
store opens like a PDF - Word with headings, bold / italic, lists and tables, Excel one tab per sheet with column letters and
row numbers (at most 5 sheets x 500 rows x 50 columns). The server reads the file in a sandboxed process; no macros run,
formulas show their stored result; old .doc / .xls and password-protected files: download only. Their text is searchable
and readable for agents. **Summarize**: in the preview of a task's file, when a connected agent may see the task, the button
(with a confirmation naming the agent) posts a comment in your name that mentions the agent; the agent reads the file and
answers with the summary. Kalmido calls no language model itself; undo removes the comment.

**Knowledge folders** (2.200.0, #2747): knowledge pages live in the same folder tree as the file store (empty folders, drag to move or sort, a "…" menu). Share a folder or a page with people, groups or agents (read / edit, inherited). Agents reach pages through API v1 / MCP (`wiki_list`, `wiki_read`, `wiki_write`, `wiki_append`, `wiki_replace_section`, `wiki_create`, scopes `wiki:read` / `wiki:write`), only those shared with them.

## Offline knowledge, office projects, pictures

- **Knowledge pages offline**: every space you can read is kept on the device, opens and can be searched without a
  connection; pages edited offline are sent once you are online again (a change made elsewhere meanwhile waits at the
  page: keep yours or take theirs). Encrypted spaces stay encrypted on the device, logging out deletes the copy (#2671).
- **Knowledge in folders**: pages and folders live in a shared folder tree like the file store (drag, sort, empty folders); share a folder or a page with people, groups and agents, read or edit, inherited by subfolders.
- **Agents and knowledge**: pages through API v1 / MCP (`wiki_list`, `wiki_read`, `wiki_write`, `wiki_append`, `wiki_replace_section`, `wiki_create`) with the scopes `wiki:read` / `wiki:write`, only pages shared with that agent.
- **Office documents belong to a project**: quotations, invoices and credit notes can be bound to a project (the client's
  projects on top, or *Create new project*), also later on finalised or sent documents; the project page lists
  *Quotations & invoices* for people with office rights only (#2665).
- **Office rights**: a client's invoicing fields belong to *Quotes & invoices*, sets / roles / crew to *Equipment*; "own entries only" covers times to bill and own reports; agents need the area *Receipts* for an organisation's receipts (#2735).
- **Pictures**: the bot figure's antenna sways gently at rest; profile pictures come as ten people for users and ten bots
  for agents (#2673 #2674 #2675).
