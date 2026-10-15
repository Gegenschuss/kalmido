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
- **Undo.** Creating, renaming, deleting and importing are one step each (the arrow on top, Ctrl/Cmd+Z, the toast).
- **Export / import.** The menu of the page list exports a space as a ZIP of `.md` files in folders (the format of
  SilverBullet and similar tools) and imports such a ZIP: only Markdown files, at most 2000 files, 1 MB each and 30 MB
  in total; pages with an existing name are skipped unless you replace them. Paths with `..` are refused.
- **Mind maps in pages.** A fenced block with the language `mindmap` draws its Markdown list as a mind map:

  ````
  ```mindmap
  - Launch
    - Plan
      - Budget
    - Shoot
  ```
  ````

Organisation exports (Settings > Organisation) contain the pages (`wiki/pages.json`). Agents have no access to knowledge
pages yet.

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
