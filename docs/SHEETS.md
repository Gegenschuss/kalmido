# Tables

## Using tables

*Since 2.89.0.*

Simple tables with formulas, like a small spreadsheet, where every cell can also fetch figures from Kalmido: the hours
booked on a project, its budget, open tasks, a client's rate. Good for a quotation (hours x rate + material), a project
budget against the time booked, or plain lists (equipment, shooting plan, contacts). Switch it on in
**Settings > Modules > Tables**; it then has its own row in the sidebar.

- **Spaces.** A table belongs to an organisation (every member reads and writes it) or is *Private* (only you). The
  workspace switch of the sidebar decides which tables the overview shows and where a new one goes. A table can be attached
  to a project (menu *Attach to a project…*, or *Tables* in the project's menu: a new table there is attached
  at once). Then only people who see that list read it, and only those who may change the list change the table.
- **Keys like a spreadsheet.** Arrows move, Shift + arrows or dragging select a range, Tab / Enter go on, typing replaces the
  cell, Enter or F2 edits it, Esc cancels, Delete empties the selection. Ctrl/Cmd+C / X / V copy, cut and paste ranges, also
  from and to other spreadsheets; pasting below the last row adds rows. Enter in the last row adds a row. The bar above the
  grid shows and edits the content of the chosen cell. On a phone a tap chooses a cell, a second tap edits it.
- **Columns** have a kind: text, number, currency, percent, date, selection, checkbox, person, link or file (2.124.0, see
  below). A selection has its own options, each with a
  colour of the app palette; the colour goes to the cell or, if you choose so, to the whole row. The menu of a column title
  sorts (saved for everyone), filters (only your view) and inserts or deletes columns; its right edge changes the width.
- **Formulas** start with `=`: `+ - * /`, brackets, comparisons, text in quotes, `&` joins text, `19%` is 0.19. Arguments
  are separated by `;` (a `,` works too). Functions: `SUMME/SUM`, `MITTELWERT/AVERAGE`, `MIN`, `MAX`, `ANZAHL/COUNT`,
  `WENN/IF`, `RUNDEN/ROUND`, `HEUTE/TODAY`, `TAGE/DAYS`, `SUMMEWENN/SUMIF`, `ZÄHLENWENN/COUNTIF`, `SVERWEIS/VLOOKUP`,
  `XVERWEIS/XLOOKUP`, text functions (`LINKS`, `RECHTS`, `TEIL`, `LÄNGE`, `VERKETTEN`, `GLÄTTEN`, `GROSS`, `KLEIN`) and date
  functions (`DATUM`, `JAHR`, `MONAT`, `TAG`, `EDATUM`). References: `A1`, `A1:B5`, a cell's own name (`day_rate`) or a column's
  title (all its cells). After `=` the app suggests names, columns, functions and Kalmido values; a click on another cell
  while writing a formula inserts its address.
- **Kalmido values:** `projekt.<name>.zeit_gesamt` (hours), `.aufgaben`, `.offen`, `.erledigt`, `.budget_h`, the same with
  `liste.`, `kunde.<name>.satz` / `.budget_h` / `.budget_betrag` / `.zeit_gesamt`, and `hier.<field>` for the project
  the table is attached to. Formulas are stored with ids, so renaming a project, a column or a cell, or sorting, never
  breaks them.
- **Where a value comes from.** Own values look normal, results of formulas a little quieter, values from Kalmido in the
  accent colour, frozen values grey. Hover a cell (or press it long on a phone) to see its name and formula. The panel next
  to the grid (below it on a phone) shows the chosen cell's name, formula, *Comes from* and *Goes into*, and the button
  *Freeze value* (keeps the current value as a copy until *Live again*). *Dependencies* draws arrows for the chosen cell or
  the whole table. Each person sees Kalmido values with their own rights: a source you may not see shows *No access*, a
  deleted source *Source deleted* with the last value you saw.
- **Team.** Changes of others appear within seconds; the cell you are editing is never overwritten, and *Anna is editing B4*
  shows who works where. Changes made by an agent are marked and can be taken back per call in the panel.
- **The frame (2.98.0).** On a computer the grip at the bottom right corner of the grid makes the frame wider / narrower
  and higher / lower, also while the table is empty (or focus the grip and use the arrow keys, Shift for bigger steps);
  the size is kept per table on this device, a double click on the grip (or Home) goes back to the automatic size. Empty
  columns and rows fill the frame; they are only shown, nothing is created until you type into one of them: then the
  missing rows and columns are added and the value written, one undo step. *Open in its own window* (next to
  *Dependencies*) opens the table alone in a window of its own (no sidebar), for working next to the app or on a second
  screen; changes show in both windows within seconds. The button next to it switches full screen on and off (Esc leaves
  it). A phone shows the grid as before, without these buttons.
- **Undo.** Every action (a cell, a paste, sorting, a column, a row, creating, renaming, deleting) is one step back (the
  arrow on top, Ctrl/Cmd+Z, the toast). Deleted tables, columns and rows can be restored.

## More column kinds, rows kept in view, printing and history

*Since 2.124.0.*

- **Checkbox.** A tap on the box ticks it (or choose the cell and press Space or Enter). In formulas a tick counts as 1,
  an empty box as 0: `=SUMME(D2:D20)` counts the ticks.
- **Person.** Choose one of the people who may see the table: the members of the attached project, of the
  organisation, or in a private table only you. The cell shows the picture and the name; someone who can no longer see the
  table (or whose account is gone) reads *Unknown*.
- **Link.** Type a web address (`https://…`, `www.example.com` gets `https://`) or an e-mail address (becomes `mailto:`).
  Anything else is refused. The cell shows the address shortened; the arrow at its end opens it in a new tab.
- **File.** Enter (or a second tap) on a file cell opens *Upload file…*, *Open*, *Download* and *Remove file*; on a computer a
  file can also be dropped on the cell. The file lies encrypted at rest like task attachments and as large as they may be;
  only people who may read the table open it. A removed or replaced file can be brought back with Undo; after 30 days it is
  deleted for good. Changing a column's kind keeps every input as it was.
- **Keep rows / columns in view.** In the menu of a row number or a column title: *Keep rows in view up to here* /
  *Keep columns in view up to here*. Those rows / columns stay put while you scroll (also on a phone), for everyone who
  opens the table; *Release the kept rows* / *columns* (or the table's menu) ends it. Not the same as *Freeze value*,
  which keeps one cell's value as a copy.
- **Print / PDF.** The table's menu has *Print / PDF…*: a plain view of the rows shown (filters apply) with the column
  titles repeated on every page. In the print dialog choose *Save as PDF* for a PDF file (on phones too).
- **History.** The panel has *History of the cell* (who changed the chosen cell when, before -> after) and *Recent changes*
  (also in the table's menu): the latest 200 changes of the table within 90 days, people and agents. Whoever may read the
  table sees its history; it moves along when the table moves to another workspace.

## Formulas, functions and Kalmido variables

A cell holds text, a number, a date - or a formula. A formula starts with `=`.

**Arithmetic:** `+ - * /`, brackets, `19%` (= 0.19), text in `"quotes"` joined with `&`, comparisons `= <> < > <= >=`
(for `WENN`). Numbers may be typed as `1,5` or `1.5`, dates as `31.12.2026` or `2026-12-31`. A date plus a number is a date
that many days later; a date minus a date is the number of days.

**Functions** (German names as in German Excel, the English names work too; arguments are split by `;`, a `,` is accepted):

| Function | English | What it does |
|---|---|---|
| `SUMME(...)` | `SUM` | sum of the numbers (text and empty cells in a range are left out) |
| `MITTELWERT(...)` | `AVERAGE` | average |
| `MIN(...)`, `MAX(...)` | | smallest / largest number |
| `ANZAHL(...)` | `COUNT` | how many numbers / dates |
| `WENN(condition; then; else)` | `IF` | e.g. `=WENN(B2="Agreed"; C2; 0)` |
| `RUNDEN(value; digits)` | `ROUND` | rounds half up |
| `HEUTE()` | `TODAY` | today's date |
| `TAGE(end; start)` | `DAYS` | days between two dates |
| `SUMMEWENN(range; criterion; [sum range])` | `SUMIF` | sum of the cells whose cell in the range meets the criterion, e.g. `=SUMMEWENN(B2:B9; "Paid"; C2:C9)` |
| `ZÄHLENWENN(range; criterion)` | `COUNTIF` | how many cells meet the criterion, e.g. `=ZÄHLENWENN(status; "open")` |
| `SVERWEIS(value; range; column; [approximate])` | `VLOOKUP` | finds the value in the first column of the range and returns the cell of that row in the given column; exact unless the fourth argument is `WAHR` (then the largest value not above it, first column sorted) |
| `XVERWEIS(value; search range; result range; [if not found])` | `XLOOKUP` | finds the value in a row or column and returns the cell at the same place of the result range |
| `LINKS(text; [n])`, `RECHTS(text; [n])` | `LEFT`, `RIGHT` | the first / last n characters (default 1) |
| `TEIL(text; start; n)` | `MID` | n characters from position start (1 = the first) |
| `LÄNGE(text)` | `LEN` | number of characters |
| `VERKETTEN(text; ...)` | `CONCAT`, `CONCATENATE` | joins texts and ranges (like `&`) |
| `GLÄTTEN(text)` | `TRIM` | removes spaces at both ends and double spaces |
| `GROSS(text)`, `KLEIN(text)` | `UPPER`, `LOWER` | capital / small letters |
| `DATUM(year; month; day)` | `DATE` | a date; months and days may run over (`DATUM(2026;13;1)` = 1 January 2027) |
| `JAHR(date)`, `MONAT(date)`, `TAG(date)` | `YEAR`, `MONTH`, `DAY` | the parts of a date |
| `EDATUM(date; months)` | `EDATE` | the same day some months later (or earlier with a minus), at most the month's last day |

**Criteria** of `SUMMEWENN` / `ZÄHLENWENN`: a number, a date or a text (upper / lower case does not matter, `*` stands for any
characters, `?` for one, `~*` for a real star), or a comparison in quotes: `">5"`, `"<>done"`, `"<=2026-01-01"`, `"="` (empty
cells), `"<>"` (cells that are not empty). A lookup that finds nothing shows **Not found** (`#N/A` in Excel); `HEUTE()` is
computed anew each time the table is shown, so it is tomorrow's date tomorrow. Very large lookups over thousands of rows are
capped per table: a cell then shows "Wrong type of value" with the hint to use smaller ranges.

**References:** `A1`, a range `A1:B5`, a cell's own name (give a cell a name such as `dayrate` and write `=dayrate*8`), and a
column's name: `=SUMME(amount)` adds every cell of the column "Amount" except the formula's own cell. Formulas are stored
with internal ids, not with names or addresses: renaming a cell name, a column, a project or a client, or sorting the rows,
never breaks a formula - it simply shows the new name or address.

**Kalmido variables** bring live numbers from Kalmido into a cell:

| Variable | Fields |
|---|---|
| `projekt.<name>.<field>` | `zeit_gesamt` (tracked hours), `aufgaben` (tasks), `offen` (open), `erledigt` (done), `budget_h` (the "Budget h" field) |
| `liste.<name>.<field>` | the same fields for any list |
| `kunde.<name>.<field>` | `satz` (hourly rate), `budget_h`, `budget_betrag` (budget amount), `zeit_gesamt` (hours of the client's lists) |
| `hier.<field>` | the project / list the table is attached to |

`<name>` is the name in lower case with `_` for spaces (`Shoot Berlin` -> `projekt.shoot_berlin`); two equal names get `_2`,
`_3`. Typing `=` offers every cell name, column, project, client and function you may use here, with its current value.
A cell with a Kalmido variable is marked as such; "Freeze value" keeps the current value as a fixed number (a deliberate
copy) until you thaw it.

**Who sees what (workspace boundary):** a table lives in an organisation (every member reads and writes it) or in your
private space (only you). A table attached to a project follows that project: whoever sees the project reads the table,
whoever may change the list edits it. Kalmido variables are calculated **for each viewer**: a colleague who does not see
the project gets "No access" in that cell - without the project's name and without its value. When you write a formula
you can only pick sources you see yourself and that belong to the table's workspace (an organisation's table: only that
organisation's projects, projects and clients). If a source is deleted, the cell shows "Source deleted" and the last value
*you* saw. Agents see a table only when it is shared with them through a project they are in.

Errors in a cell: "Circular reference" (cells that depend on each other), "Division by zero", "Reference not found" (a
deleted row / column - Undo brings it back), "Wrong type of value", "Formula error" (a typo; the formula is not saved).

## Several sheets in one table

*Since 2.124.0.*

A table can have several sheets, like a spreadsheet file. Under the grid sits the sheet bar: with one sheet only a quiet
*+* (the table looks as before), with more the sheets as tabs, the open one in the accent colour; on a phone the bar
scrolls sideways. *+* adds a sheet after the open one and opens it. Tap another sheet to open it; tap the open sheet for
its menu: *Rename…*, *Duplicate* (columns, rows, inputs and formulas; file cells stay empty), *Move left* / *Move right*
(on a computer you can also drag a sheet) and *Delete sheet* (to the trash - Undo brings it back). Every step is one Undo
step. The first sheet carries the table and is not deleted on its own (delete the table in its menu instead).

- **One table, one set of rights.** The title, the space, the attached project, the shares of single people and a move to
  another workspace belong to the whole table: whoever may read the table reads all its sheets, whoever may change it
  changes all of them. The overview, the search (Mod+K) and agents show the table once, with its number of sheets.
- **Formulas across sheets** as in Excel: `=Kosten!B4`, `=SUMME('Kosten 2027'!B2:B9)`, also in `SUMMEWENN`, `SVERWEIS` ...
  (a sheet name with spaces in `'…'`). A renamed sheet keeps its formulas; a change in one sheet shows in the other the next
  time it loads; a deleted sheet gives "Reference not found" until Undo brings it back; sheets reading each other in a
  circle give "Circular reference". The chart, the rows / columns kept in view and the history belong to each sheet.
- **Files.** An Excel import takes every visible sheet (at most 30, the limits count for the whole file), formulas into
  another sheet included; the Excel export writes every sheet (formulas into another sheet included). CSV stays one sheet:
  the one open.
- An older Kalmido (before 2.124) on the same database shows the further sheets as tables of their own - nothing is lost.

## A chart from columns

*Since 2.124.0.*

A table's menu (the three dots at the top right) has *Chart…*: choose bars or a line, the column with the labels (or the row
numbers) and one to six columns with numbers. The chart sits above the formula bar and shows the calculated values (formulas
included, the rows of your filters only) and follows every change at once. One series is drawn in the accent colour, more
series in shades of it and grey (a line also dashed) with a legend. Tap a column of the chart (or point at it with the
mouse) to read its values. The pencil changes the chart, the cross hides it for now (*Show chart* in the menu brings it
back). The chart is saved with the table: everyone who sees the table sees it, only who may change the table changes it,
and Undo takes a change back. A table without a chart looks exactly as before. Agents read the setting with the table
(`chart`), they do not change it.

<a id="carrying-a-table-over-tasks-quotation-list-as-rows-2890"></a>

## Carrying a table over: tasks, quotation, project as rows

*Since 2.89.0.*

A table is never linked silently to the rest of Kalmido. Everything below happens only when you press the button in the
table's menu (the "…" at the top right), and every press is **one undo step**.

**Create tasks from rows.** Choose several rows first (drag over them or Shift + arrow keys) or take all rows. In the dialog
pick the project (only projects of the table's space you may add tasks to), the column for the title and, if you like, a column
for the due date (a date column or text like `20.11.2026`) and one for the notes. Rows without a title and rows carried over
before are skipped. Each task's history says "carried over the task from a table" with a link to the table (without the
table's name: the project may be shared with people who cannot open the table). The row gets a small mark in its row head; the
side panel shows "Carried over" with a link to the task. Undo moves the tasks to the trash and removes the marks.

**Take over as a quotation.** Only when Office & finance is on for the table's space (an organisation's table: that
organisation's office; a private table: your own personal office). Map the columns for description, quantity, unit and unit
price and choose a client of that office. Units are recognised from the usual words (`Tag`, `Std`, `Stk`, `pauschal`, `day`,
`hour`, `piece`, `flat` ...). Kalmido creates a **draft** in the office - nothing is finalised, numbered or sent beyond what the
office itself does for a new quotation. The office history of the quotation says "created from a table", the table shows the
quotation in the side panel. Undo deletes the draft when you are the office's admin and it is still a draft; otherwise the
draft stays and you delete it in the office.

**Project as rows.** Pick a project of the table's space: Kalmido adds one row per task with the columns Title, Status,
Due, Time (booked hours) and Assignee. The cells are **live Kalmido values** (`=aufgabe.<id>.titel`, `.status`, `.faellig`,
`.zeit`, `.zustaendig`): renaming or completing the task shows up in the table. A new, empty table makes room for the five
columns (its blank start columns step aside). New tasks of the project come in only when you press **Fetch new tasks of <project>**
in the menu - only the missing rows are appended, into the same columns. Rows of a second list use the same columns.

Like every Kalmido variable, `aufgabe.<id>.<field>` is evaluated for the person looking: someone who does not see the task
(another project, a participant who sees only their own tasks) gets "No access" without a value; a task in the trash shows
"Source deleted" with the last value that person saw. You may also type `=aufgabe.<id>.zeit` yourself, for a task you see.

These buttons are for people only; agents work inside a table with the table tools and create tasks or office drafts in
their own ways.

**An agent proposes rows as tasks (2.126.1).** An agent that a table and a project are shared with may propose rows as tasks
instead of pressing the button. You get a card (News, and a push if you want it): the table, the project and one line per row
as you see it, with the agent's title above the cell's. Untick rows, change titles or dates, then **Apply**: the same as the
button, as you, and the history names the agent. Rows carried over before are greyed out. Undo takes the tasks back.

## Tables as files: export and import

**Export.** A table's menu (the three dots at the top right) has *Export as CSV* and *Export as Excel (.xlsx)*.

- **CSV** holds the values only (a formula as its result), the column titles in the first row. In German, French, Spanish,
  Italian and Dutch with `;` and the decimal comma, otherwise with `,` and the point - the way Excel opens it directly.
  Text a spreadsheet would run as a formula (starting with `+`, `-`, `@` ...) gets a `'` in front.
- **Excel (.xlsx)** holds values AND formulas where Excel has the same thing: addresses, ranges, column names, `SUMME`,
  `MITTELWERT`, `MIN`, `MAX`, `ANZAHL`, `WENN`, `RUNDEN`, `HEUTE`, `TAGE`, `SUMMEWENN`, `ZÄHLENWENN`, `SVERWEIS`, `XVERWEIS`
  and the text and date functions (as SUM, AVERAGE, SUMIF, VLOOKUP ...; a `SVERWEIS` with three arguments gets `FALSE` as the
  fourth, because Excel would look up approximately without it). A formula with a Kalmido
  variable (`projekt.…`, `liste.…`, `kunde.…`, `hier.…`) goes in as its value, with a note on the cell showing the Kalmido
  formula. Column kinds become number formats (currency, percent, date), a selection column a drop-down list with the colour
  of each option (the cell or the whole row), cell names Excel names. The file opens in Excel, LibreOffice and Numbers.
- Values are calculated with what you may see: the file never holds a value you could not see in Kalmido.
- 2.124.0: a checkbox goes out as a truth value (CSV: `WAHR` / `FALSCH` in German, `TRUE` / `FALSE` otherwise), a person as
  the name, a link as its address, a file as its file name (the file itself stays in Kalmido).

**Import.** In the tables overview (the three dots next to *New table*) choose *Import CSV or Excel…*: the file becomes a
new table in the space shown (in the tables of a project: attached to it) and opens at once.

- A first row of text becomes the column titles; Kalmido recognises the column kind (number, currency, percent, date,
  text) from the values and number formats, and an Excel drop-down list becomes a selection column (with its colours).
  A column of truth values only (`WAHR` / `FALSCH`, `TRUE` / `FALSE`, Excel's checkboxes) becomes a checkbox column (2.124.0).
- Simple Excel formulas are taken over (with the German names, also `SUMIF`, `COUNTIF`, `VLOOKUP`, `XLOOKUP` and the text
  and date functions; a `VLOOKUP` without its fourth argument gets `WAHR`, as Excel looks up approximately then); what Kalmido cannot calculate (since 2.124.0 not other sheets of the file any more, whole
  columns like `A:A`, unknown functions) comes in as its value - the message says how many.
- A `=` at the start of a CSV value stays text, never a formula. At most 10 MB, 5000 rows, 200 columns.
- Undo takes back the whole import (the table goes to the trash).

**Agents.** With the permissions *Read tables* / *Write tables* (off for new agents) an agent reads and fills tables,
for example "put everyone with a birthday in the next 4 weeks into a table". It sees only tables attached to a list
shared with it and the ones it created (a personal agent creates them in your private space). Each of its calls is one
step you can take back with one click; a cell using a project it does not see shows it "No access"
([AGENTS.md](AGENTS.md#tables)).

## Moving a table to another workspace

*Since 2.96.0.*

Table menu (the open table or the overview) *Move to another workspace…*: between the private space and an organisation, both
ways, only when there is another workspace. The check first names what does not come along: the attachment to a list of the
old workspace ends (the table would otherwise open to the whole target space), rows carried over to tasks of the old workspace
lose their link, quotations made from the table stay where they are, and formulas that use lists or clients of the old
workspace show "No access" there. Out of an organisation only the person who created the table or an admin of the organisation
may move it; a private table only its owner. Undo moves it back in one step and brings back the project attachment and the
carried-over links that fit again. The last move shows in the side panel. Shares of single people / agents end with the move (2.124.0). Agents never move tables between workspaces.
Route: `POST /api/sheets/{id}/move-space {to, dry, undo}`.

## Sharing one table

*Since 2.124.0.*

Table menu *Share…*: give single people or agents access to just this table, without the rest of the workspace and
without the attached project. Each share has a role: *Can view* (read and export, never change) or *Can edit* (cells, rows,
columns, the title). Deleting, attaching to a project, moving to another workspace, carrying rows over and managing the shares
stay with the people who may change the table through its workspace (the owner of a private table, the members of the
organisation or of the attached project); a person who only got a share never passes it on.

You can share with the people you know (an organisation's table: only its members; a private table: the people you share
lists with, or by e-mail address - the answer never tells whether the address has an account, and no mail goes out) and
with the agents of the table's workspace (a private table: your own agent). The overview marks a table with shares as
*Shared*; the recipients find it under *Shared with me*. Stopping a share works at once; every add, stop and role change
is one Undo step. Moving the table to another workspace ends its shares (the check names them); leaving an organisation
ends the shares of its tables; a table in the trash is hidden from the recipients until it is restored. Agents see a table
shared with them in `sheets_list` (`shared_in`, `share_role`) like the tables of their projects.
Routes: `GET|POST /api/sheets/{id}/shares`, `PATCH|DELETE /api/sheets/{id}/shares/{share}`.

The search (Mod+K) finds tables by their title (only the ones you may open) and opens them.
