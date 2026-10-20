# Knowledge pages and mind map

## Knowledge pages (2.49.0)

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
- **Templates.** Pages under `Templates/` are offered as the start of a new page.
- **Saving** is automatic. When someone else saved the page in between, you choose which version stays.
- **History (2.123.0).** *History* in the menu of a page lists its saved versions with date and person (saves of one
  person within ten minutes are one version, at most 100 per page, the oldest go). A version opens with a line
  comparison to the current text; *Restore* makes its text the current one again (a new version, the name stays) and can
  be undone. Whoever may read the page reads its history, restoring needs the right to change it. The history goes with
  the page (trash, moving to another workspace) and is deleted with it. Encrypted spaces (see below) keep no history.
- **Search (2.123.0).** *Find a page* filters the names at once; from two characters the pages whose text has the words
  follow under *Found in the text* (whole words and word beginnings, names first, then the newest), 30 at a time with
  *Show more*. The server searches a word index of keyed hashes, not the text itself.
- **Encrypted at rest (2.123.0).** The text of every page and of its versions is stored encrypted with the key of its
  space (the organisation's key, for private pages your account key), like the office data; names (paths) stay plain
  because links and the tree need them. Nothing changes in use. The server admin switches it on once with
  `orgcrypt_cli encrypt-wiki` (off after the update, so a step back to an older version stays possible); see
  *Encryption at rest* in the self-hosting guide.
- **Undo.** Creating, renaming, deleting and importing are one step each (the arrow on top, Ctrl/Cmd+Z, the toast).
- **Files (2.99.0).** A page can carry PDFs and pictures (PNG, JPEG, GIF, WebP, SVG): *Attach files* below the text,
  at most 25 MB each. The type is checked by the content, not by the name; an SVG is cleaned (no scripts, no outside
  references). In the text, `![label](/api/wiki/files/<id>/<name>)` shows a picture and `[label](…)` opens a file; the
  link button next to a file copies that line. The files have the rights of their page: whoever may read the page may
  open them. Deleting a file or its page can be undone. An encrypted space (see below) takes no files yet.
- **Export / import.** The "…" menu in the header (section *Space*) exports a space as a ZIP of `.md` files in folders (the format of
  SilverBullet and similar tools) and imports such a ZIP: at most 2000 files, 1 MB per page, 25 MB per PDF or picture and
  500 MB in total; pages with an existing name are skipped unless you replace them. Paths with `..` are refused.
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

Organisation exports (Settings > Organisation) contain the pages (`wiki/pages.json`) and their files (`wiki/files.json`,
the bytes under `files/wiki/`). Agents have no access to knowledge pages yet.

## Encrypted space (2.64.3)

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

## Moving pages to another workspace (2.96.0)

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

## Sharing a page or a folder, read only (2.123.0)

Page menu *Share…* (this page) or *Share folder…* (the page's folder: its own page, every page below it, also pages you add
later; "Customer A" never includes "Customer AB"). Whoever may write in the space shares; in the private space that is you.

- **People** (private space only): a person with an account reads the pages in the app under *Shared with me* in the side
  bar of the knowledge pages -- only what you shared, never the rest of your space (no index, search, backlinks or mentions).
  Choose the person or type an e-mail address (the answer never tells whether an account has it). Pages of an organisation
  are read by all its members anyway; people outside get a public link (no person shares across the organisation boundary).
  Agents never get a share.
- **Public link**: a secret address `/s/w/<token>` that opens a plain read-only page without an account and without the app
  (no scripts): the page, or the list of the folder's pages. Pictures and files of the shared pages come along; a
  `[[link]]` to a page that is not shared shows as plain text, task numbers stay text. Optional *Valid until*; several links
  per page are possible (one per customer). *Turn off* ends a link at once; Undo brings the same link back. Unknown,
  expired and turned-off links all answer "Link not available". The pages are `noindex`, never cached, rate limited like
  the public list links, and the server switch for public links (*Settings > Users > Whole server*, `KALMIDO_PUBLIC_LINKS=0`)
  turns these off too. Only the SHA-256 of a token is looked up; the token itself is kept sealed so you can copy it again.
- Renaming a page or a folder takes its shares along; a page in the trash is not shared (Undo brings it back); moving pages
  to the other workspace ends their shares. A space encrypted in the browser cannot share (the server cannot read its text);
  links of a space that gets locked stop working. Shared pages carry a small people mark in the tree and in the title.

Routes: `GET /api/wiki/shares?page=<id> | space=&folder=`, `POST /api/wiki/shares {page_id | space + folder, kind: person |
link, user_id | email, expires}`, `PATCH /api/wiki/shares/<id> {expires}`, `DELETE /api/wiki/shares/<id>` (revoke),
`POST /api/wiki/shares/<id>/restore`; the guest: `GET /api/wiki/shared`, `GET /api/wiki/shared/pages/<id>`,
`GET /api/wiki/shared/files/<id>`; the public page: `GET /s/w/<token>`, `/s/w/<token>/p/<id>`, `/s/w/<token>/file/<id>`.

## Mind map (2.49.0)

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
