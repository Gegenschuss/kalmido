// @ts-check
/* Kalmido web client: the short introductions of the areas (2.466.0, #3314): their steps. When they start and what the
   last card holds: palette.js (TOUR_AREAS, tourModAuto). Loaded on demand (lazyload.js module tourmods). */
'use strict';
const TOUR_TABS = '[data-mgtabs]', tourParts = id => () => mg_parts(mg_area(id)).length > 1;
const TOUR_MODS = {
  cal: [{id: 'cal1', t: N_('Your calendar'), d: N_('Tasks with a date and your appointments, side by side.')}, {id: 'cal2', sel: '.calbar', t: N_('Your view'), d: N_('Switch between day, week and month here and move through time.')}, {id: 'cal3', t: N_('New appointment'), d: N_('Pick a free time to add an appointment.')}],
  office: [{id: 'office1', t: N_('Your office'), d: N_('Clients, quotations, invoices and receipts in one place.')}, {id: 'office2', sel: TOUR_TABS, t: N_('Get around'), d: N_('This bar takes you to each part of the office.')}, {id: 'office3', t: N_('Start with a client'), d: N_('Create a client first: quotations and invoices then fill in the address for you.')}],
  time: [{id: 'time1', t: N_('Track your time'), d: N_('Start the timer on a task or enter the hours afterwards.')}, {id: 'time2', t: N_('See the totals'), d: N_('Your times add up per day and per project.')}],
  review: [{id: 'review1', t: N_('Look back'), d: N_('Write a few lines about your day and see how the week went.')}, {id: 'review2', sel: TOUR_TABS, on: tourParts('review'), t: N_('Statistics'), d: N_('Completed tasks and trends have their own tab.')}],
  life: [{id: 'life1', t: N_('Home and life'), d: N_('Household and everyday things, apart from your work.')}, {id: 'life2', sel: TOUR_TABS, on: tourParts('life'), t: N_('More at home'), d: N_('Family and budget have their own tabs when they are on.')}],
  reading: [{id: 'reading1', t: N_('Read later'), d: N_('Save articles and links, and read them when you have time.')}, {id: 'reading2', sel: TOUR_TABS, on: tourParts('reading'), t: N_('Feeds and bookmarks'), d: N_('Feeds and bookmarks have their own tabs.')}],
  ablage: [{id: 'ablage1', t: N_('Your files'), d: N_('Files and documents in folders, in one place.')}, {id: 'ablage2', t: N_('Share a folder'), d: N_('Share a folder from its menu: the people you add see only that folder.')}],
  wiki: [{id: 'wiki1', t: N_('Your knowledge'), d: N_('Notes and instructions as pages that link to each other.')}, {id: 'wiki2', t: N_('Find it again'), d: N_('Search finds your pages from anywhere in Kalmido.')}],
  sheets: [{id: 'sheets1', t: N_('Your tables'), d: N_('Build your own tables for lists, prices or plans.')}, {id: 'sheets2', t: N_('Share a table'), d: N_('Share a table from its menu, just like a project.')}],
  habits: [{id: 'habits1', t: N_('Your habits'), d: N_('Set what you want to do regularly and tick it off.')}, {id: 'habits2', t: N_('Keep going'), d: N_('Your streak shows how well a habit is going.')}],
  agents: [{id: 'agents1', t: N_('Your agents'), d: N_('Agents are helpers you connect yourself. They see only what you share with them.')}, {id: 'agents2', t: N_('Work with them'), d: N_('Give them tasks in your projects or write to them in the chat.')}],
};
const tourModSteps = id => (TOUR_MODS[id] || []).filter(st => !st.on || st.on()).map(st => ({...st, r: st.sel ? () => { const e = $$(st.sel).find(x => x.offsetWidth || x.offsetHeight); return e ? e.getBoundingClientRect() : null; } : null}));
