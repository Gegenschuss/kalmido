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
- **Visible focus.** A 2 px ring in the accent colour on every control; text fields get a ring too.
- **Nothing important behind the focus.** Lists keep the focused row clear of the sticky headers and the docked "Add
  task" box (WCAG 2.4.11).
- **Screen readers.** Controls have names, roles and states: a task's circle is a checkbox named after the task, the
  task title is a button described by its date, priority and other details, the panels and dialogs are named regions
  and modal dialogs, colour swatches say which colour they are and whether they are picked.
- **Announcements.** Messages such as "Moved to Inbox · Undo" are read out (a polite live region); new chat messages are
  a log; error lines in dialogs are alerts.
- **Errors in words.** A required field left empty says so next to the field ("Please fill in “Name”"), marks the
  field invalid and connects the message to it.
- **Not only colour.** Overdue dates have an alert icon and the word "Overdue" for screen readers; priorities show `!`,
  `!!` or `!!!` next to the title (also named for screen readers); states of agents have words next to their dots.
- **Contrast.** Text has at least 4.5:1, large text and the edges of fields and controls at least 3:1, in light and
  dark and with every accent colour. Windows high contrast (forced colours) keeps checkboxes, selections and focus
  visible.
- **Dragging is never the only way.** Tasks: *Move up / Move down* in the task menu or Alt+↑ / Alt+↓, *Move to
  section…*, *Move to list* (m), the date picker; the panels and columns that can be resized by dragging have a grip
  that works with ← → and Enter (standard width) or a double-click.
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
- Agents' messages are written by the agents; their Markdown is shown as headings, lists and code, but the content is up
  to them.

## Feedback

Found a barrier? Please open an issue on [GitHub](https://github.com/Gegenschuss/kalmido/issues) with what you tried,
the device, the browser and (if you use one) the screen reader. Accessibility issues are treated like bugs.
