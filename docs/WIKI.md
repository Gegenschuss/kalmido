# Knowledge pages and mind map

## Knowledge pages

*Since 2.49.0.*

A small wiki next to the tasks: processes, checklists and know-how of an organisation, or private notes of one person.
Switch it on in **Settings > Modules > Knowledge pages**; it then has its own row in the sidebar.

- **Spaces.** Every page lives in a space: an organisation (every member reads and writes it) or *Private* (only you).
  The picker on top of the page list chooses the space; with the workspace switch of the sidebar set to one organisation
  the knowledge pages open there.
- **Name = path.** A page called `Processes/Shoot day/Checklist` sits in the folders *Processes* and *Shoot day*; the tree
  on the left comes from the names. On a phone the tree is a list, an open page shows its path as breadcrumbs.
- **Markdown** like notes: headings, lists, check boxes, tables, code. `#123` links task 123 (only people who may see that
  task get a link; nobody else sees its title).
- **Links between pages.** `[[Processes/Shoot day/Checklist]]` (or `[[…|label]]`) links another page of the same space.
  While typing `[[` the app suggests pages. A link to a page that does not exist yet is shown dashed; a tap creates it.
  Below each page, *Linked from* lists the pages that link to it. Renaming a page changes the links to it;
  *Rename folder…* in the menu of a page moves every page of its folder (the links follow as well).
- **Frontmatter.** A leading block of `key: value` lines between `---` lines is shown as small fields above the text.
- **Templates.** Pages under `Templates/` are offered as the start of a new page (and in the `/` menu while writing).
  *2.371:* placeholders are filled in when a page starts from a template: `{{datum}}` (or `{{date}}`) today's date,
  `{{titel}}` (`{{title}}`) the new page's name, `{{ich}}` (`{{me}}`) your name, `{{cursor}}` the place where writing starts.
  Other `{{…}}` stay as they are. This happens in the browser, so it works the same in an encrypted space.
- **Embedding a page (2.371).** `![[Page]]` shows another page of the same space inside this one, `![[Page#Heading]]`
  only its part from that heading to the next heading of the same level. The embedded text is read only, framed, with its
  name as a link. Only pages you may read are shown (otherwise *Page not available*); a page that would show itself,
  embeds deeper than three levels and more than 20 embeds on one page stay a link. `/` > *Embed a page* while writing.
- **Daily notes (2.371).** *Today* next to *New page* opens the page `journal/YYYY-MM-DD` of the space and creates it
  when it is missing, from the template `Templates/Tagesnotiz` (or `Templates/Daily note`) when there is one. A daily
  note shows arrows to the previous and next day that has a note and a date field to jump to any day.
- **Saving** is automatic. When someone else saved the page in between, you choose which version stays.
- **History (2.123.0).** *History* in the menu of a page lists its saved versions with date and person (saves of one
  person within ten minutes are one version, at most 100 per page, the oldest go). A version opens with a line
  comparison to the current text; *Restore* makes its text the current one again (a new version, the name stays) and can
  be undone. Whoever may read the page reads its history, restoring needs the right to change it. The history goes with
  the page (trash, moving into the private space) and is deleted with it. Moving pages into an organisation leaves their
  earlier versions behind (2.360.0: its members would read the old states; the dry run names how many). Encrypted spaces
  (see below) keep no history.
- **Search (2.123.0).** *Find a page* filters the names at once; from two characters the pages whose text has the words
  follow under *Found in the text* (whole words and word beginnings, names first, then the newest), 30 at a time with
  *Show more*. The server searches a word index of keyed hashes, not the text itself.
- **Encrypted at rest (2.123.0).** The text of every page and of its versions is stored encrypted with the key of its
  space (the organisation's key, for private pages your account key), like the office data; names (paths) stay plain
  because links and the tree need them. Nothing changes in use. The server admin switches it on once with
  `orgcrypt_cli encrypt-wiki` (off after the update, so a step back to an older version stays possible); see
  *Encryption at rest* in the self-hosting guide. A sealed text that cannot be opened any more (its key is lost) is never
  shown or saved as the page's text (2.126.2): the page answers `409` (`wiki_unreadable`, "cannot be read") and cannot be
  saved; search, history and the export skip it. Since 2.139.0 the message names the way out: the organisation's
  recovery key (for a private page: the server key of the installation) opens it again, otherwise it can only be
  deleted - the page shows the message with a *Delete page* button (saving, renaming and moving stay refused so the
  sealed text is never lost). The search finds such a page by its name and reads its text again once the key is back
  (a restore with the recovery key, a rotation, another server key). An import over a page of the same name and the
  switch of the browser lock skip it and name it ("1 page skipped: <name> (not readable)") instead of stopping.
- **Undo.** Creating, renaming, deleting and importing are one step each (the arrow on top, Ctrl/Cmd+Z, the toast).
- **Files (2.99.0).** A page can carry PDFs and pictures (PNG, JPEG, GIF, WebP, SVG): *Attach files* below the text,
  at most 100 MB each (2.177.0; `KALMIDO_WIKI_FILE_MAX_MB`). The type is checked by the content, not by the name; an SVG is cleaned (no scripts, no outside
  references). In the text, `![label](/api/wiki/files/<id>/<name>)` shows a picture and `[label](…)` opens a file; the
  link button next to a file copies that line. The files have the rights of their page: whoever may read the page may
  open them. Deleting a file or its page can be undone. An encrypted space (see below) takes no files yet.
- **Formatting bar (2.276.0, #3043).** A page is edited in the normal font (notes keep theirs). The bar above the text
  writes the Markdown for you: heading (`## `), bold, italic, list, checkbox (`- [ ] `) and link wrap the selection or
  prefix the selected lines, a second press removes it; Ctrl/Cmd+B and +I work and the browser's undo takes one step back.
  The bar stays one row on phones and tablets and scrolls sideways. The text itself stays Markdown (links, `[[Page]]`,
  `#123` and embeds are never rewritten); a formatted editing mode is not part of it yet.
- **Pictures and files in the editor (2.123.0).** *Insert picture or file* above the text uploads files to the page (also
  pasting a picture or dropping files into the text) or picks a file of the **file store** of the same space
  (*From the file store…*: browse its folders or search). A file of the file store is referenced, not copied:
  `![label](/api/files/nodes/<id>/content)` shows a picture, `[label](…)` opens the file. A reader sees it only with the
  right to open that file in the file store; everyone else sees *File not available*, without its name. Only files of the
  page's own space are offered and shown (an organisation's page: that organisation's file store; a private page: your own
  private one). After a move to another workspace such references stay as text and show as not available.
- **Links to files and tables (2.123.0).** `[[datei:Folder/Contract.pdf]]` (a path of the file store from its top, or the
  file's number) links a file, `[[tabelle:Budget]]` (its title or number) links a table of the same space; `|label` sets the
  text. Typing `[[datei:` or `[[tabelle:` suggests them. A reader without access sees plain text. The file details in the
  file store list the pages under *Mentioned in*. The export keeps these links as they are.
- **Check boxes as tasks (2.123.0).** In reading mode an open check box line `- [ ] …` has a **+** button; with several
  open lines *Open items as tasks* takes them all. The dialog chooses the list (the basket first); dates, `#tags` and
  priorities in the line are read like in quick add. The line then ends with the task link `#123`, which shows the task's
  state (struck through when done); ticking the box in the page does not change the task. Creating the tasks and changing
  the line are one undo step. In an encrypted space this works as well, but the task titles are stored with the lock of
  the chosen list (a hint says so when that list has none).
- **Export / import.** The "…" menu in the header (section *Space*) exports a space as a ZIP of `.md` files in folders (the format of
  SilverBullet and similar tools) and imports such a ZIP: 1 MB per page, 100 MB per PDF or picture, up to 4 GB and
  10 000 files per ZIP (2.177.0; `KALMIDO_WIKI_IMPORT_MAX_MB`, `KALMIDO_WIKI_IMPORT_MAX_FILES`); pages with an existing
  name are skipped unless you replace them. Paths with `..` are refused. A ZIP above the limit is refused before the
  upload, with the limit in MB. The ZIP goes up in pieces with a progress bar (uploaded x of y MB), then the server
  unpacks it in the background (x of y files); *In the background* closes the window -- keep Kalmido open until the
  upload is done, the unpacking goes on without it. *Cancel* stops both, nothing of a stopped import stays. The result
  comes as a message when it is done, or the next time the knowledge pages open. Files above the limit are skipped
  with the reason "Larger than 100 MB". (The API keeps the single `POST /api/wiki/import` for ZIPs up to 500 MB.)
  PDFs and pictures come along (2.99.0): a file goes to the page that links it (`[[contract.pdf]]`, `![[_attachments/sketch.png]]`,
  `![](../_attachments/sketch.png)`, `[text](contract.pdf)`; relative to the page's folder, the top of the ZIP or `_attachments/`)
  and the links point at it; a file several pages link is stored once; a file nobody links lands on the page *Imported
  files* of its folder. Other files, and files whose content does not match their name, are skipped. After the import a
  report shows how many pages and files came in and what was skipped, with the reason. The export puts the files under
  `_attachments/<page>/` and writes the links as `[[_attachments/…]]`, so importing it again gives the same pages and files.
- **Mind maps in pages.** A fenced block with the language `mindmap` draws its Markdown list as a mind map:

  ````
  ```mindmap
  - Launch
    - Plan
      - Budget
    - Shoot
  ```
  ````
- **Formulas and diagrams** (2.382.0). A block between two `$$` lines (or `$$ … $$` on one line) and a fenced block
  with the language `math` are typeset as formulas (LaTeX syntax, KaTeX); `\( … \)` puts a small formula into the text.
  A single `$` stays a dollar sign, so amounts of money are never read as formulas. A fenced block with the language
  `mermaid` draws a diagram (flowchart, sequence, Gantt, … in Mermaid syntax). Both libraries ship with Kalmido and are
  loaded only when a page has such a block; without a connection, or when a block has an error, its source stays visible
  as a code block with a short hint. The editor's "/" commands *Formula* and *Diagram* insert an example. Pages shared
  through a public link show the source as code.
- **Source / Preview** (2.382.0). The formatting bar of the editor has a button that switches between the live preview
  (the page drawn while writing) and the plain Markdown source; the page's "…" menu has the same entry.

- **Tags (2.371).** `#word` in the text (starting with a letter: `#project`, `#customer/north`; `#123` stays a task) or
  `tags: [a, b]` in the frontmatter tag a page. A tag in the text is a link to its list; the panel has the group *Tags*
  below the folders (on a phone: below the pages), most used first. Case is ignored. The server keeps no tag in plain text:
  the word index holds a keyed hash per tag, the names are read from the texts in memory when the list is shown. Routes:
  `GET /api/wiki/tags?space=` (the tags) and `&tag=` (the pages with it).
- **Live queries (2.371).** A fenced block with the language `abfrage` (or `query`) shows pages of the same space, fresh on
  every change. One `key: value` per line, nothing else:

  ````
  ```abfrage
  tag: project
  eigenschaft: status = open
  sortiere: geändert absteigend
  als: tabelle
  spalten: status, owner
  ```
  ````

  `tag:` every tag named (several lines: all of them) · `ordner:` (folder) that folder and below · `eigenschaft:`
  (property) a frontmatter value, without `= ...` the key is enough · `zeige:` (show) `seiten` | `aufgaben` (pages |
  tasks = the open checkboxes `- [ ] ...` of those pages) · `sortiere:` (sort) `name` | `geändert` | `erstellt` | a key,
  `absteigend` (desc) after it · `grenze:` (limit) default 50, at most 200 · `als:` (as) `liste` | `tabelle` · `spalten:`
  (columns) of the table.

  The page with the block and the templates are never listed; a line that is not understood is named below the result. The
  reader sees only pages they may read (through a share only the shared ones). In an encrypted space the browser runs the
  query over the pages it opened. Route: `GET /api/wiki/query?page=<id>&q=<the block's text>`.

Organisation exports (Settings > Organisation) contain the pages (`wiki/pages.json`) and their files (`wiki/files.json`,
the bytes under `files/wiki/`). Agents have no access to knowledge pages yet.

## Encrypted space

*Since 2.64.3.*

A knowledge space can be encrypted in the browser: page names and texts are then only readable for people whose encryption is
unlocked; the server, its database and backups hold ciphertext only. A space is the whole of one room: *Private* or one
organisation.

- **Switch.** Needs your encryption set up (*Settings > Account*). Private space: you. Organisation space: an admin of the
  organisation. The switch for the space asks for confirmation (passphrase and recovery code lost = content lost)
  and converts all pages with a progress bar; it can be resumed if the page is closed. Switching it off asks for your password and
  converts back.
- **Members.** All members of the organisation read the space. A member who has not set up encryption waits on a list with their name
  until they have and an admin releases the key. A new member of the organisation gets the key from an admin; when a member
  leaves, the key changes and older pages are encrypted again in the background as soon as an admin opens the knowledge pages
  with their encryption unlocked (for a key seen there for the first time, by a button).
- **In use.** Search, backlinks, "mentioned in", page links, templates, and moving a folder (every page is renamed) work in the browser over the decrypted pages. A locked space shows a placeholder until you unlock.
- **Export and import** of such a space are done by the browser: the entry *Export as ZIP* in the header menu gives plain Markdown files;
  import reads a ZIP and encrypts the pages. The server answers its own export and import with an error there.
- **Not available:** access for agents or the API, templates copied by the server, the server's own search, and files on pages
  (2.99.0: the import in the browser skips PDFs and pictures with the reason; a space whose pages have files cannot be
  switched on until they are deleted).
- **Limits.** A changed script delivered by the server could capture the passphrase; page names are encrypted but the number of pages,
  their sizes (in steps of 64 bytes) and who changed them when stay visible. Content a member saw stays with them.

See *Exporting encrypted content* in the self-hosting guide for backups, moving servers and lost keys.

## Trash

*Since 2.143.0.*

- A deleted page goes to the trash of its space (*Undo* brings it back at once). The space menu (*…* > *Trash*) lists
  the pages there with their files: *Restore*, *Delete permanently…* for one page, *Empty trash* for all (with a
  confirmation). The same people who may delete a page may do this (private space: its owner; an organisation's space:
  its members).
- After the trash period of tasks (`KALMIDO_TRASH_DAYS`, default 30 days) the server deletes a page in the trash for good,
  together with its files on disk, their text and scan marks, its history and its word index; the files' space no longer
  counts. A page restored before that keeps everything.

## Moving pages to another workspace

*Since 2.96.0.*

A page, or its folder with everything below it, moves between the private space and an organisation (both ways): page menu
*Move to another workspace…* / *Move folder to another workspace…* (only when there is another workspace: a person without an
organisation never sees it). The dialog names source and target, lets you pick a folder in the target and first shows what
the check found: a name that is already taken there (then nothing moves; `409` with the names), links between a moved page
and one that stays (they stay as text: `[[links]]` only work inside one space), pages that link files of the file store (the
files stay where they are). Links between pages that move together follow their new paths. Out of an organisation only the
person who created the pages or an admin of the organisation may move them. Undo moves them back to the old place in one step;
below the page both sides see the last move (where from, when, who; a workspace you do not belong to shows only as
"Organisation" or "private space", 2.97.0). Agents never move data between workspaces; the person does that in the app.
Route: `POST /api/wiki/move-space {pages: [id] | folder, space, to, dest, dry}`.

**With the lock (2.97.0).** Pages also move when the source, the target or both are encrypted in the browser: your browser
opens name and text with the key of the source, lets the links between the moved pages follow, and encrypts both for the
target (its current key) -- or sends the plain text when the target is open. In that case the check says *The pages are no
longer end-to-end encrypted in the target.* and a second question asks before anything moves. You need your encryption
unlocked and a key of every locked space involved (without the target's key the check stops: an admin of the organisation
releases it). Names in a locked target are compared in the browser. Undo moves the pages back, encrypted again for the old
space. If a key changes between the check and the move, the server refuses it (`409`) and the browser tries once more. The
server never sees a plain name or text of a locked space; the history of such a move keeps no page names.

## Sharing a page or a folder, read only

*Since 2.123.0.*

Page menu *Share…* (this page) or *Share folder…* (the page's folder: its own page, every page below it, also pages you add
later; "Customer A" never includes "Customer AB"). Whoever may write in the space shares; in the private space that is you.

- **People** (private space only): a person with an account reads the pages in the app under *Shared with me* in the side
  bar of the knowledge pages -- only what you shared, never the rest of your space (no index, search, backlinks or mentions).
  Choose the person or type an e-mail address (the answer never tells whether an account has it). Pages of an organisation
  are read by all its members anyway; people outside get a public link (no person shares across the organisation boundary).
  Agents never get a share. The person gets a News item "X shared the page … with you" (2.126.2; it follows the
  *Sharing* row of the notification settings, no push by default) that opens *Shared with me*.
- **Public link**: a secret address `/s/w/<token>` that opens a plain read-only page without an account and without the app
  (no scripts): the page, or the list of the folder's pages. Pictures and files of the shared pages come along; a
  `[[link]]` to a page that is not shared shows as plain text, task numbers stay text. Optional *Valid until*; several links
  per page are possible (one per customer). *Turn off* ends a link at once; Undo brings the same link back. Unknown,
  expired and turned-off links all answer "Link not available". The pages are `noindex`, never cached, rate limited like
  the public list links, and the server switch for public links (*Settings > Users > Whole server*, `KALMIDO_PUBLIC_LINKS=0`)
  turns these off too. Only the SHA-256 of a token is looked up; the token itself is kept sealed so you can copy it again.
- Renaming a page or a folder takes its shares along; a page in the trash is not shared (Undo brings it back), and a share
  of a page belongs to exactly that page (2.360.0): a new page of the same name is not shared by it; moving pages
  to the other workspace ends their shares. A space encrypted in the browser cannot share (the server cannot read its text);
  links of a space that gets locked stop working. Shared pages carry a small people mark in the tree and in the title.
- A public link of an organisation's page works only while the person who made it is an active member; once they leave
  the organisation or their account is deleted or disabled, the dialog shows the link as *Ended* (2.126.2) and it no
  longer counts as a live share (mark, limit). Make a new link if it is still needed.

Routes: `GET /api/wiki/shares?page=<id> | space=&folder=`, `POST /api/wiki/shares {page_id | space + folder, kind: person |
link, user_id | email, expires, images}`, `PATCH /api/wiki/shares/<id> {expires, images}`, `DELETE /api/wiki/shares/<id>` (revoke),
`POST /api/wiki/shares/<id>/restore`; the guest: `GET /api/wiki/shared`, `GET /api/wiki/shared/pages/<id>`,
`GET /api/wiki/shared/files/<id>`; the public page: `GET /s/w/<token>`, `/s/w/<token>/p/<id>`, `/s/w/<token>/file/<id>`.
2.380: `images: true` (the switch *Show embedded pictures*, default off) shows the pictures of the file store embedded in the
page (`![…](/api/files/nodes/<id>/content)`, image types only, never a locked folder, only while the person who made the share
may still see them) through `GET /api/wiki/shared/pages/<id>/img/<node>` and `/s/w/<token>/img/<page>/<node>`; other files stay
placeholders.

## Mind map

*Since 2.49.0.*

Every list (not the inbox) can be shown as a **Mind map**, next to List, Kanban and Timeline (the view switch in the list
header). The list's name is in the middle, its sections and tasks are the branches, subtasks the sub-branches. Every
branch is a task: what you do in the map is done to the tasks, and it can be undone like any other change. In lists you
may only view, the map only shows.

| Key | |
|---|---|
| Enter | new branch next to the selected one |
| Tab | new sub-branch (a subtask) |
| Shift+Tab | one level up |
| Delete / Backspace | delete the branch (with its sub-branches) |
| Space | fold / unfold |
| Arrow keys | move the selection |
| F2, double click | rename |
| O | open the task |

Drag a branch onto another one to hang it there (it becomes a subtask, or moves to that section). On a phone drag the map
with one finger and zoom with two; a tap selects a branch, a second tap opens its actions, a long press lifts the
branch so the finger can hang it somewhere else. The button next to the map
switches to an **outline** (an indented list) of the same tree.

The menu exports the map as a Markdown outline, as SVG or PNG, and imports an outline (Markdown list, OPML or FreeMind
`.mm`) as tasks under the selected branch.
