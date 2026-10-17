# Accessibility

Kalmido aims to meet the **Web Content Accessibility Guidelines (WCAG) 2.2, level AA** in the web app (phones,
tablets, desktops, the installed app). This page says what that means today, how it is checked and where the known
limits are. Last review: version 2.16.0 (October 2026).

## Status

**Partly conformant** with WCAG 2.2 AA: the automated checks of the main views pass and the points below are built in;
the app has not yet been tested by people who use a screen reader every day (see *Known limits*).

## What is built in

- **Keyboard everywhere.** Every function works without a mouse. *Skip to content* is the first stop; the sidebar is
  one stop (↑ ↓ inside it); in a list one task is the stop and ↑ ↓ (or j k) move it, Enter opens the task, x completes
  it, Esc closes and puts the focus back on the row. Menus get the focus on their first item, ↑ ↓ move, Esc returns to
  the button that opened them. Dialogs keep Tab inside, close with Esc and give the focus back. `?` lists all shortcuts.
  The favourite tiles on top of the sidebar are part of its stop; each has its name as label, and its menu (context menu
  key, right-click or long press) moves it left or right, so the order can be arranged without dragging.
- **Visible focus.** A 2 px ring in the accent colour on every control; text fields get a ring too.
- **Nothing important behind the focus.** Lists keep the focused row clear of the sticky headers and the docked "Add
  task" box (WCAG 2.4.11).
- **Screen readers.** Controls have names, roles and states: a task's circle is a checkbox named after the task, the
  task title is a button described by its date, priority and other details, the panels and dialogs are named regions
  and modal dialogs, colour swatches say which colour they are and whether they are picked.
- **Announcements.** Messages such as "Moved to Basket · Undo" are read out (a polite live region); new chat messages are
  a log; error lines in dialogs are alerts.
- **Errors in words.** A required field left empty says so next to the field ("Please fill in “Name”"), marks the
  field invalid and connects the message to it.
- **Not only colour.** Overdue dates have an alert icon and the word "Overdue" for screen readers; priorities show `!`,
  `!!` or `!!!` next to the title (also named for screen readers); states of agents have words next to their dots.
- **Contrast.** Text has at least 4.5:1, large text and the edges of fields and controls at least 3:1, in light and
  dark and with every accent colour. Windows high contrast (forced colours) keeps checkboxes, selections and focus
  visible.
- **List and workspace colours (2.53.0).** Lists choose from a fixed palette of 12 tones, each with its own value and
  text colour for light and dark (4.5:1 as text and under text); an older free colour stays stored and is shown as the
  nearest tone. An open list takes its colour as the accent of its view and tasks show it as a thin edge on boards, in
  the calendar and in the collected views (the priority keeps its own marks); *Settings > Appearance > List colours only
  as a dot* turns accent and edges off. An organisation has a colour of its own (8 tones, set by its admins in
  *Settings > Workspaces*): its lists show a stripe in the header and the sidebar and a frame around the input fields,
  and the header's sign names the organisation in words; Private stays without colour. Moving a task or list from
  Private into an organisation says so in the message ("Will be visible to everyone in …", with Undo).
- **Your own workspace colours (2.57.0).** In *Settings > Workspaces > Your colour per workspace* everybody picks a
  colour for Private and for each of their organisations from the same 12 tones, or *No color*; *Default* keeps the
  colour the organisation's admins chose. Only you see your choice, on every device. The shown workspace tints the
  sidebar lightly (also the phone drawer; never under *All workspaces*), the switch and its menu show a dot in front of
  each workspace (a ring when it has no colour), and your tone replaces the organisation's colour in the stripes and
  the header's sign. Text on the tinted sidebar keeps at least 4.5:1 in light and dark; every change is one Undo step.
- **Calmer rows (2.56.1).** *Settings > Appearance > Task rows > Symbols in the row* sets how many small symbols a task
  row shows: *All*, *Important* (the default: due date, reminder, person, approvals and locks), *Calm* (only the title,
  the status circle and the due date) or *Custom* (a box per symbol, in groups). Overdue tasks, an agent waiting for
  your yes and the status circle always show; the task itself still shows everything. *Settings > Appearance > Sidebar*
  can hide the task counts, the status dots of lists and the share marks (person / robot). Per person, on every device.
- **Themes, header strips, small moments (2.83.0).** *Settings > Appearance > Theme* offers *Control room* (the default
  look), *Paper* (warm and light; switches to the light scheme), *Night* (deep blue; switches to the dark scheme) and
  *High contrast* (pure black or white backgrounds, stronger lines, brighter secondary text; in light and dark). A theme
  sets the background tones and the look of cards per device; accent colour, density and font stay as chosen, and every
  accent keeps at least 4.5:1 on every theme. A list can have a slim header strip on top of its view (list settings >
  *Header*: a gradient from the list colour, dots, lines, a grid or an own picture, JPEG / PNG / WebP up to 2 MB; the same
  for everyone in the list; set by the owner and the list admins; a locked list offers no picture), a folder too (its
  menu > *Header…*, only for you). The strip is decorative and hidden from screen readers; *Settings > Appearance >
  Show header pictures* turns it off on a device. *Progress rings in the sidebar* show done / all of a list's tasks
  (with a text label for screen readers) and can be turned off. Ticking a task off makes its circle pop for 0.2 s (none
  with reduced motion); empty lists and an empty Today show a calm line drawing of the K.
- **Dragging is never the only way.** Tasks: *Move up / Move down* in the task menu or Alt+↑ / Alt+↓, *Move to
  section…*, *Move to list* (m), the date picker; the panels and columns that can be resized by dragging have a grip
  that works with ← → and Enter (standard width) or a double-click. The divider between the chats of the split chat
  panel works with ↑ ↓ and Enter (even heights); a chat window's menu moves it up / down, folds and closes it, and Esc
  in its message box closes only that window. *Customize* on the start page, Today, Time
  tracking, the overviews and the project page: ↑ / ↓ buttons, Alt+↑ / Alt+↓ on a row and a switch per block (each move
  is announced); dragging the rows is only an extra on a computer. A block's settings (2.55.0) open from the gear at the
  block in *Customize* or *Settings…* in its … menu: real buttons, switches and selects in a popover (a sheet on the
  phone), each change announced and undoable. Dependencies (Alt + drop onto a task) also via
  *Waiting on a task…* in the task menu; several selected tasks also via *Subtasks of…* / *Out of the parent task* in the
  multi panel and the phone's selection menu. Calendar events (2.52.0): creating by dragging over free time, moving an
  event and dragging its lower edge are extras (on a touch screen after holding 0.4 s); *+ Event*, the quick add's
  *Event* and the event's *Edit* set every date and time with fields. Esc cancels a drag.
- **Touch targets** of 44 × 44 px on touch screens (at least 24 px everywhere, WCAG 2.5.8), also in the compact density.
- **Reduced motion.** With "reduce motion" set in the system, animations and smooth scrolling are off.
- **Zoom and reflow.** The app works at 320 px width and at 200 % zoom without scrolling sideways (wide boards such as
  Kanban, the timeline and the calendar grid scroll inside their own area, which WCAG allows for two-dimensional
  content). The font size can be set from 75 % to 150 % per device (Settings > Appearance), the font *Atkinson
  Hyperlegible* is built in.
- **Language.** The page language follows your setting (English, German, French, Spanish, Italian, Dutch).

## How it is checked

- An automated test (`tests/p2160_a11y.js`) runs [axe-core](https://github.com/dequelabs/axe-core) with the WCAG 2.0,
  2.1 and 2.2 A + AA rules over the sign-in page, every main view, the task panel, the chat, Settings, the command
  palette and the dialogs, on a desktop and a phone, in light and dark and with every accent colour. It also checks
  the 3:1 edge of every field, presses real keys (Tab order, focus ring, focus never covered, Enter / Esc, menus, Tab
  kept inside dialogs) and the reflow at 320 px and 200 % zoom. It runs on every change (continuous integration).
- Keyboard and screen-reader structure are reviewed by hand before releases.

## Known limits

- Not yet tested with real screen readers by their everyday users (VoiceOver on iPhone and Mac, TalkBack, NVDA). The
  structure follows the WAI-ARIA patterns, but details of what is read out may still be rough.
- Some secondary dialogs (for example parts of the import, the time sheet print view and the roadmap's filters) are not
  covered by the automated test yet.
- Lists with a lot of custom columns get dense on narrow screens; the columns that do not fit move into the second line.
- Very long lists (more than 300 rows, 2.65.0) draw only the rows near the visible part. The browser's own search
  (Ctrl+F) finds only those; the app's search (/) finds everything. Keyboard moving (↑ ↓, j k), Ctrl+A and Shift-click
  work over all rows; the address book's rows say their place and the total (aria-posinset / aria-setsize).
- Agents' messages are written by the agents; their Markdown is shown as headings, lists and code, but the content is up
  to them.

## Feedback

Found a barrier? Please open an issue on [GitHub](https://github.com/Gegenschuss/kalmido/issues) with what you tried,
the device, the browser and (if you use one) the screen reader. Accessibility issues are treated like bugs.
