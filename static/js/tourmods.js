// @ts-check
/* Kalmido web client: the short introductions of the areas (2.466.0, #3314): their steps. When they start and what the
   last card holds: palette.js (TOUR_AREAS, tourModAuto). Loaded on demand (lazyload.js module tourmods).
   2.670.0 (#4576): about seven steps per area (5-8) that point at the real controls: create, view / filter, folders and
   sharing, search, the link to projects and tasks, the phone's gesture where there is one, where the settings are.
   A step (tourMods): {id, sel, ms, on, opt, t, d, tm, dm}. sel = the target on a computer, ms = the target on a phone ('' = none, missing =
   sel), tm / dm = the phone's own title / text; on() = only when that part is switched on; opt = left out when its target is not on the
   screen as the tour starts (a button that only some pages or workspaces show), else the card stands in the middle.
   The texts stay neutral to the industry (the product rule core / industry pack, 04.11.2026). */
'use strict';
// the parts of an area: the tabs on top (a phone; a computer for an area without a panel) or the rows of the panel
const TOUR_TABS = '[data-mgtabs]', TOUR_PARTS = `${TOUR_TABS}, #side .sbbi[data-sbbpart]`, tourParts = id => () => mg_parts(mg_area(id)).length > 1;
// the last step of every area: its icon in the bar (computer) or the menu with the areas (phone), and how to switch it off
const tourRail = id => ({id: id + 'R', sel: `#srail .srb[data-sbb="${id}"]`, ms: '#top [data-act="side"]', t: tr('This area in the bar'), tm: tr('All areas in the menu'),
  d: tr('Right-click its icon to move it, hide it or open Kalmido on it. Settings > Modules switches the area off.'),
  dm: tr('The menu at the top left lists all areas: a long press on an icon moves or hides it. Settings > Modules switches the area off.')});
const tourWs = id => ({id: id + 'W', sel: '#view .spovr', opt: 1, t: tr('Private or organisation'), d: tr('Each workspace keeps its own list here: open one.')});
const tourNoTouch = () => !isTouch(), tourDesk = () => !isMobile(), tourPhone = () => isMobile();
// 2.670.0 (#4576): the texts are translated here, as the tour starts (tr in this module: its language part loads with it and
// the texts stay out of the language core of the start); the steps carry tx, tourGo shows them as they are
const tourMods = () => ({
  cal: [{id: 'cal1', t: tr('Your calendar'), d: tr('Tasks with a date and your appointments, side by side.')},
    {id: 'cal2', sel: '.calbar', t: tr('Your view'), d: tr('Switch between day, week and month here and move through time.')},
    {id: 'cal3', sel: '[data-act="cal-today"]', t: tr('Back to today'), d: tr('Today brings you back, the arrows next to it turn the page. On a trackpad: swipe with two fingers, pinch to zoom.'),
      dm: tr('Swipe sideways to turn the page. Pinch with two fingers to go between year, month, week and day.')},
    {id: 'cal4', t: tr('New appointment'), d: tr('Select a free time to add an appointment.')},
    {id: 'cal5', sel: '[data-act="ev-cals"]', t: tr('Your calendars'), d: tr('Show or hide calendars, add subscriptions and share a calendar of your own from its menu.')},
    {id: 'cal6', sel: '#view .qadd .box', ms: '#fab', t: tr('Tasks in the calendar'), d: tr('Add a task with a date down here: it shows on its day. Drag a task or an appointment to move it.'),
      dm: tr('The + adds a task: with a date it shows in the calendar. Hold a task or an appointment to drag it to another day.')},
    {id: 'cal7', sel: '[data-act="cal-done"]', opt: 1, t: tr('Completed tasks'), d: tr('Show or hide what is already done.')},
    tourRail('cal')],
  office: [{id: 'office1', t: tr('Your office'), d: tr('Clients, quotations, invoices and receipts in one place.')},
    {id: 'office2', sel: '#side .sbbtn[data-ofm]', ms: `${TOUR_TABS}, #view .oflr`, t: tr('Get around'), d: tr('The panel on the left takes you to each part of the office. Fold the groups you do not need.'),
      dm: tr('From the office overview you reach each of its parts; the arrow at the top leads back.')},
    {id: 'office3', sel: '[data-act="client-new"], #view [data-ofm="clients"], #side [data-ofm="clients"]', ms: '[data-act="client-new"], #view [data-ofm="clients"]', t: tr('Start with a client'), d: tr('Create a client first: quotations and invoices then fill in the address for you.')},
    {id: 'office4', sel: '[data-ofd="new"]', opt: 1, t: tr('New quotation'), d: tr('Add the items, send it as PDF or e-invoice and turn it into an invoice once it is accepted.')},
    {id: 'office5', sel: '#ofd-q, #ct-q', opt: 1, t: tr('Search'), d: tr('Type a name, a number or a word to narrow the list.')},
    {id: 'office6', sel: '#view [data-act="ws-menu"]', opt: 1, t: tr('Which office'), d: tr('Each workspace has its own office: switch between your private one and an organisation here.')},
    {id: 'office7', t: tr('Your company details'), d: tr('Address, bank details, tax and the numbers of your documents: Settings > Company & office.')},
    tourRail('office')],
  time: [{id: 'time1', t: tr('Track your time'), d: tr('Start the timer on a task or enter the hours afterwards.')},
    {id: 'time2', sel: TOUR_PARTS, ms: TOUR_TABS, on: tourParts('time'), t: tr('Time tracking and focus'), d: tr('Time tracking and the focus timer each have their own tab.')},
    {id: 'time3', sel: '[data-act="tv-start"], [data-act="pomo-start"]', t: tr('Start the timer'), d: tr('Start it here or on a task. It keeps running while you work elsewhere.')},
    {id: 'time4', sel: '[data-act="te-add"]', opt: 1, t: tr('Add hours later'), d: tr('Forgot the timer? Enter the time afterwards.')},
    {id: 'time5', sel: '[data-act="tv-lists"]', opt: 1, t: tr('Per project'), d: tr('Show the times of the projects you select; the buttons above set the period.')},
    {id: 'time6', sel: '[data-act="tv-export"]', opt: 1, t: tr('Export'), d: tr('Hand over your times as a report, CSV or timesheet.')},
    {id: 'time7', sel: '[data-act="mod-settings"]', opt: 1, t: tr('Settings'), d: tr('The settings of this part open here.')},
    tourRail('time')],
  review: [{id: 'review1', t: tr('Look back'), d: tr('Write a few lines about your day and see how the week went.')},
    {id: 'review3', sel: '[data-act="rv-period"]', opt: 1, t: tr('Day, week or history'), d: tr('Select what to look back on; the arrows go back and forth.')},
    {id: 'review4', sel: '#rvh-done, #rvh-open', opt: 1, t: tr('Done and open'), d: tr('What you completed, what is still open and what comes next, from all your projects.')},
    {id: 'review5', sel: '#rv-text', opt: 1, t: tr('Your journal'), d: tr('A few lines and a mood for each day. Only you can read it.')},
    {id: 'review6', sel: '[data-act="ly-custom"]', opt: 1, t: tr('Arrange the page'), d: tr('Select which blocks this page shows and in which order.')},
    {id: 'review2', sel: TOUR_PARTS, ms: TOUR_TABS, on: tourParts('review'), t: tr('Statistics'), d: tr('Completed tasks and trends have their own tab.')},
    tourRail('review')],
  life: [{id: 'life1', t: tr('Home and life'), d: tr('Household and everyday things, apart from your work.')},
    {id: 'life2', sel: TOUR_PARTS, ms: TOUR_TABS, on: tourParts('life'), t: tr('More at home'), d: tr('Family and budget have their own tabs when they are on.')},
    tourWs('life'),
    {id: 'life3', sel: '[data-act="life-contract"]', opt: 1, t: tr('Contracts'), d: tr('A contract becomes a task on the last day to cancel, so you do not miss it.')},
    {id: 'life4', sel: '[data-act="life-device"]', opt: 1, t: tr('Devices and upkeep'), d: tr('A device reminds you before its warranty ends, upkeep repeats by itself.')},
    {id: 'life5', sel: '[data-bg="create"]', opt: 1, t: tr('Budget'), d: tr('What comes in, what goes out, and what is left at the end of the month. Shared with the family if you like.')},
    {id: 'life6', t: tr('Reminders as tasks'), d: tr('Contracts, devices and upkeep become tasks with a date: they show in Today and in the calendar.')},
    tourRail('life')],
  reading: [{id: 'reading1', t: tr('Read later'), d: tr('Save articles and links, and read them when you have time.')},
    {id: 'reading2', sel: TOUR_PARTS, ms: TOUR_TABS, on: tourParts('reading'), t: tr('Feeds and bookmarks'), d: tr('Feeds and bookmarks have their own tabs.')},
    tourWs('reading'),
    {id: 'reading3', sel: '#rl-url, #rss-url, #bm-url', opt: 1, t: tr('Save a link'), d: tr('Paste a link here to keep it.'), dm: tr('Paste a link here, or save it with the share button of any app on your phone.')},
    {id: 'reading4', sel: '[data-rl="open-list"]', opt: 1, t: tr('To read and read'), d: tr('What you have read moves to Read, nothing gets lost.')},
    {id: 'reading5', on: () => feat('feeds'), t: tr('From your feeds'), d: tr('An article of a feed goes to Read later with one click.')},
    tourRail('reading')],
  ablage: [{id: 'ablage1', t: tr('Your files'), d: tr('Files and documents in folders, in one place.')},
    {id: 'ablage2', sel: '#side .sbbtn[data-absp], #side .sbbtn[data-go^="ablage"]', ms: '#view .abspace', opt: 1, t: tr('Spaces'), d: tr('Private, shared with you and the trash: each has its own place here.')},
    tourWs('ablage'),
    {id: 'ablage3', sel: '[data-ab="upload"]', opt: 1, t: tr('Upload'), d: tr('Upload files here or drop them onto the page. Scan takes paper in with the camera.')},
    {id: 'ablage4', sel: '[data-ab="new-folder"]', opt: 1, t: tr('Folders and sharing'), d: tr('Create folders here. Share a folder from its menu (right-click or long press): the people you add see only that folder.')},
    {id: 'ablage5', sel: '#ftxt-q, #dc-q', t: tr('Search'), d: tr('Search by name or by the text inside the files.')},
    {id: 'ablage6', t: tr('Files of projects'), d: tr('Files attached in your projects show here too, read-only.')},
    {id: 'ablage7', sel: '#side [data-go="docs"], #view [data-go="docs"]', ms: '#view [data-go="docs"]', on: () => feat('docs'), opt: 1, t: tr('Documents'), d: tr('Letters and receipts with sender, type and date, sorted by your rules.')},
    tourRail('ablage')],
  wiki: [{id: 'wiki1', t: tr('Your knowledge'), d: tr('Notes and instructions as pages that link to each other.')},
    {id: 'wiki3', sel: '[data-wk="new"]', opt: 1, t: tr('New page'), d: tr('Name it with a slash to put it into a folder, e.g. Processes/Checklist.')},
    {id: 'wiki4', sel: '[data-wk="newfolder"]', opt: 1, t: tr('Folders and sharing'), d: tr('Folders group your pages. Share a folder or a page from its menu.')},
    {id: 'wiki5', sel: '[data-wk="today"]', opt: 1, t: tr('Page of the day'), d: tr('Opens a page for today, for notes and minutes.')},
    {id: 'wiki6', t: tr('Link pages and tasks'), d: tr('Write [[Page]] to link a page and [[#123]] to link a task.')},
    {id: 'wiki2', sel: '#wk-q', t: tr('Find it again'), d: tr('Search finds your pages from anywhere in Kalmido.')},
    tourRail('wiki')],
  sheets: [{id: 'sheets1', t: tr('Your tables'), d: tr('Build your own tables for lists, prices or plans.')},
    {id: 'sheets3', sel: '[data-shv="new"]', opt: 1, t: tr('New table'), d: tr('Create a table and give it the columns you need.')},
    {id: 'sheets4', sel: '#side .sbbtn[data-shsp], #side .sbbtn[data-go="sheets"]', ms: '', on: tourDesk, opt: 1, t: tr('Spaces and folders'), d: tr('Your tables by workspace and folder. Right-click a folder for its menu.')},
    {id: 'sheets2', t: tr('Share a table'), d: tr('Share a table from its menu, just like a project.')},
    {id: 'sheets5', t: tr('Attach to a project'), d: tr('From the menu of a table: it then shows in the project as well.')},
    {id: 'sheets6', t: tr('Calculate'), d: tr('Start a cell with = for a formula. The colour of a cell shows where its value comes from.'),
      dm: tr('Start a cell with = for a formula. A long press on a cell shows its formula and where its value comes from.')},
    {id: 'sheets7', sel: '[data-shv="omenu"]', opt: 1, t: tr('More'), d: tr('Import and more for your tables.')},
    tourRail('sheets')],
  habits: [{id: 'habits1', t: tr('Your habits'), d: tr('Set what you want to do regularly and tick it off.')},
    {id: 'habits3', sel: '[data-act="habit-new"]', opt: 1, t: tr('Create habit'), d: tr('Every day, on fixed days or a number of times a week, with a goal and a reminder if you like.')},
    {id: 'habits4', t: tr('Tick it off'), d: tr('Tap a day to mark it done, or write a note for that day.')},
    {id: 'habits2', t: tr('Keep going'), d: tr('Your streak shows how well a habit is going.')},
    tourRail('habits')],
  agents: [{id: 'agents1', t: tr('Your agents'), d: tr('Agents are helpers you connect yourself. They see only what you share with them.')},
    {id: 'agents3', sel: '#view [data-act="ag-setup"]', opt: 1, t: tr('Add agent…'), d: tr('A setup code connects an agent that runs on your own computer or server.')},
    {id: 'agents4', t: tr('Share a project with it'), d: tr('An agent sees only what you share with it. Share as little as needed, and keep private and shared work apart.')},
    {id: 'agents2', t: tr('Work with them'), d: tr('Give them tasks in your projects or write to them in the chat.')},
    {id: 'agents5', sel: '[data-act="jobs-f"]', opt: 1, t: tr('Jobs'), d: tr('What your agents are working on: the open jobs or all of them.')},
    {id: 'agents6', t: tr('Rules for agents'), d: tr('What agents may do: Settings > Agents.')},
    tourRail('agents')],
  notes: [{id: 'notes1', t: tr('Your notes'), d: tr('Meetings, briefings, decisions: written down and found again.')},
    {id: 'notes2', sel: '[data-sb="note-new"], [data-act="nt-new"]', opt: 1, t: tr('New note'), d: tr('New notes stay private: only you see them. To share one, move it into a project.')},
    {id: 'notes3', sel: '#sbn-q', opt: 1, t: tr('Search notes'), d: tr('Finds notes by their title and text.')},
    {id: 'notes4', t: tr('Notes in projects'), d: tr('Every project has its own notes: the people you share the project with read them too.')},
    {id: 'notes5', on: tourNoTouch, t: tr('A note in a moment'), d: tr('Press m anywhere to start a new note.')},
    tourRail('notes')],
  team: [{id: 'team1', t: tr('Chat'), d: tr('Write to someone you work with, or share a project: every shared project gets its own chat.')},
    {id: 'team2', sel: '#view [data-act="tc-new"], #side [data-act="tc-new"]', ms: '#view [data-act="tc-new"]', opt: 1, t: tr('New message'), d: tr('Start a new conversation here.')},
    {id: 'team3', on: tourPhone, t: tr('Reply'), d: tr('Swipe a message to the side to reply to it.')},
    {id: 'team4', on: tourDesk, t: tr('Next to your work'), d: tr('Open a conversation in a split window from its head and keep working.')},
    {id: 'team5', sel: '#kbar .bell, #top .bell', t: tr('News'), d: tr('Mentions and replies from the chat arrive here too.')},
    tourRail('team')],
});
// the target on the screen: the first element of the selector that is laid out and not pushed out to the side (a closed
// drawer); one below the fold (or under the phone's bar at the bottom) is scrolled into view first
const tourModEl = sel => $$(sel).find(x => { if (!(x.offsetWidth || x.offsetHeight)) return false; const r = x.getBoundingClientRect(); return r.right > 0 && r.left < innerWidth; }) || null;
function tourModRect(sel) {
  const e = tourModEl(sel); if (!e) return null;
  let r = e.getBoundingClientRect();
  const bar = isMobile() ? $('#tabs') : null, low = bar && bar.offsetHeight ? bar.getBoundingClientRect().top : innerHeight;
  if (r.bottom > low || r.top < 0) { e.scrollIntoView({block: 'center'}); r = e.getBoundingClientRect(); }
  return r;
}
const tourModSteps = id => { const m = isMobile(); return (tourMods()[id] || []).filter(st => !st.on || st.on()).map(st => { const sel = m && 'ms' in st ? st.ms : st.sel; return {...st, sel, t: m && st.tm ? st.tm : st.t, d: m && st.dm ? st.dm : st.d, tx: true}; })
  .filter(st => !st.opt || !st.sel || tourModEl(st.sel)).map(st => ({...st, r: st.sel ? () => tourModRect(st.sel) : null})); };
