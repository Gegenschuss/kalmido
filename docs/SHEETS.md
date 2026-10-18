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
