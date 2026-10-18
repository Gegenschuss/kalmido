# Tables

## Using tables (2.89.0)

Simple tables with formulas, like a small spreadsheet, where every cell can also fetch figures from Kalmido: the hours
booked on a project, its budget, open tasks, a client's rate. Good for a quotation (hours x rate + material), a project
budget against the time booked, or plain lists (equipment, shooting plan, contacts). Switch it on in
**Settings > Modules > Tables**; it then has its own row in the sidebar.

- **Spaces.** A table belongs to an organisation (every member reads and writes it) or is *Private* (only you). The
  workspace switch of the sidebar decides which tables the overview shows and where a new one goes. A table can be attached
  to a project or list (menu *Attach to a project or list…*, or *Tables* in the list's menu: a new table there is attached
  at once). Then only people who see that list read it, and only those who may change the list change the table.
- **Keys like a spreadsheet.** Arrows move, Shift + arrows or dragging select a range, Tab / Enter go on, typing replaces the
  cell, Enter or F2 edits it, Esc cancels, Delete empties the selection. Ctrl/Cmd+C / X / V copy, cut and paste ranges, also
  from and to other spreadsheets; pasting below the last row adds rows. Enter in the last row adds a row. The bar above the
  grid shows and edits the content of the chosen cell. On a phone a tap chooses a cell, a second tap edits it.
- **Columns** have a kind: text, number, currency, percent, date or selection. A selection has its own options, each with a
  colour of the app palette; the colour goes to the cell or, if you choose so, to the whole row. The menu of a column title
  sorts (saved for everyone), filters (only your view) and inserts or deletes columns; its right edge changes the width.
- **Formulas** start with `=`: `+ - * /`, brackets, comparisons, text in quotes, `&` joins text, `19%` is 0.19. Arguments
  are separated by `;` (a `,` works too). Functions: `SUMME/SUM`, `MITTELWERT/AVERAGE`, `MIN`, `MAX`, `ANZAHL/COUNT`,
  `WENN/IF`, `RUNDEN/ROUND`, `HEUTE/TODAY`, `TAGE/DAYS`. References: `A1`, `A1:B5`, a cell's own name (`day_rate`) or a column's
  title (all its cells). After `=` the app suggests names, columns, functions and Kalmido values; a click on another cell
  while writing a formula inserts its address.
- **Kalmido values:** `projekt.<name>.zeit_gesamt` (hours), `.aufgaben`, `.offen`, `.erledigt`, `.budget_h`, the same with
  `liste.`, `kunde.<name>.satz` / `.budget_h` / `.budget_betrag` / `.zeit_gesamt`, and `hier.<field>` for the project or list
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
- **Undo.** Every action (a cell, a paste, sorting, a column, a row, creating, renaming, deleting) is one step back (the
  arrow on top, Ctrl/Cmd+Z, the toast). Deleted tables, columns and rows can be restored.

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
`_3`. Typing `=` offers every cell name, column, project, list, client and function you may use here, with its current value.
A cell with a Kalmido variable is marked as such; "Freeze value" keeps the current value as a fixed number (a deliberate
copy) until you thaw it.

**Who sees what (workspace boundary):** a table lives in an organisation (every member reads and writes it) or in your
private space (only you). A table attached to a project or list follows that list: whoever sees the list reads the table,
whoever may change the list edits it. Kalmido variables are calculated **for each viewer**: a colleague who does not see
the project gets "No access" in that cell - without the project's name and without its value. When you write a formula
you can only pick sources you see yourself and that belong to the table's workspace (an organisation's table: only that
organisation's projects, lists and clients). If a source is deleted, the cell shows "Source deleted" and the last value
*you* saw. Agents see a table only when it is shared with them through a list they are in.

Errors in a cell: "Circular reference" (cells that depend on each other), "Division by zero", "Reference not found" (a
deleted row / column - Undo brings it back), "Wrong type of value", "Formula error" (a typo; the formula is not saved).

## Carrying a table over: tasks, quotation, list as rows (2.89.0)

A table is never linked silently to the rest of Kalmido. Everything below happens only when you press the button in the
table's menu (the "…" at the top right), and every press is **one undo step**.

**Create tasks from rows.** Choose several rows first (drag over them or Shift + arrow keys) or take all rows. In the dialog
pick the list (only lists of the table's space you may add tasks to), the column for the title and, if you like, a column
for the due date (a date column or text like `20.11.2026`) and one for the notes. Rows without a title and rows carried over
before are skipped. Each task's history says "carried over the task from a table" with a link to the table (without the
table's name: the list may be shared with people who cannot open the table). The row gets a small mark in its row head; the
side panel shows "Carried over" with a link to the task. Undo moves the tasks to the trash and removes the marks.

**Take over as a quotation.** Only when Office & finance is on for the table's space (an organisation's table: that
organisation's office; a private table: your own personal office). Map the columns for description, quantity, unit and unit
price and choose a client of that office. Units are recognised from the usual words (`Tag`, `Std`, `Stk`, `pauschal`, `day`,
`hour`, `piece`, `flat` ...). Kalmido creates a **draft** in the office - nothing is finalised, numbered or sent beyond what the
office itself does for a new quotation. The office history of the quotation says "created from a table", the table shows the
quotation in the side panel. Undo deletes the draft when you are the office's admin and it is still a draft; otherwise the
draft stays and you delete it in the office.

**List as rows.** Pick a project or list of the table's space: Kalmido adds one row per task with the columns Title, Status,
Due, Time (booked hours) and Assignee. The cells are **live Kalmido values** (`=aufgabe.<id>.titel`, `.status`, `.faellig`,
`.zeit`, `.zustaendig`): renaming or completing the task shows up in the table. A new, empty table makes room for the five
columns (its blank start columns step aside). New tasks of the list come in only when you press **Fetch new tasks of <list>**
in the menu - only the missing rows are appended, into the same columns. Rows of a second list use the same columns.

Like every Kalmido variable, `aufgabe.<id>.<field>` is evaluated for the person looking: someone who does not see the task
(another list, a participant who sees only their own tasks) gets "No access" without a value; a task in the trash shows
"Source deleted" with the last value that person saw. You may also type `=aufgabe.<id>.zeit` yourself, for a task you see.

These buttons are for people only; agents work inside a table with the table tools and create tasks or office drafts in
their own ways.
