// @ts-check
/* Kalmido web client: modules loaded on demand (2.53.0, #1410). Rarely opened areas (the settings dialog, the contacts
   view, Office & finance) have no script tag in index.html: their first use loads them (loadModule), then they stay.
   The service worker precaches them (LAZY in sw.js), so they open offline too; tools/check_layout.py compares the lists.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// module -> its files in static/js/, in load order (the same files as LAZY in sw.js)
const LD_MODS = {
  settings: ['acctset', 'sesview', 'supportview', 'oinvview', 'servers', 'selfdelete', 'setreset', 'settings'],  // 2.149.0 F (#2518): servers.js (Settings > Account > other servers); 2.485.0 (#3939): supportview.js; 2.553.0 (#1413): selfdelete.js; 2.593.0 (#4590): setreset.js
   // 2.65.0 (#1823): acctset.js = the settings sections of account.js; 2.115.0 B (#2062): sessions, organisation invitations
  contacts: ['contacts', 'ctfold', 'newsletter'],  // 2.65.0 (#1823): newsletter.js; 2.351.0 B (#2749): ctfold.js (folders)
  office: ['office', 'office_docs', 'office_tree', 'office_import', 'office_sheet', 'office_parts', 'office_travel', 'office_cashflow', 'office_doctpl', 'office_logbook', 'office_cashbook',  // 2.93.0 (#1927, #1928); 2.121.0 B (#2095): office_cashbook; 2.351.0 A (#3312): office_tree
    'office_pipeline', 'office_kpi', 'office_datev', 'office_datevimp', 'office_bookarch', 'office_periods', 'officeagents', 'office_packs',  // 2.148.0 D (#2458): office_datevimp; 2.414.0 A (#3502): office_bookarch
    'office_books', 'office_receipts', 'office_bank', 'office_taxdates',  // 2.90.0 (#1921, #1922); 2.153.0 (#2055): office_receipts
    'office_banknorc',  // 2.299.0 C (#3192): bank bookings without a receipt
    'office_cards',  // 2.444.0 (#3447): credit card statements
    'office_cand',  // 2.778.0 (#5383): the candidate card (credit card positions, bank bookings)
    'office_ledger',  // 2.666.0 (#3461): the balance sheet (double-entry bookkeeping)
    'office_recurring', 'office_subs', 'office_dunning',  // 2.91.0 (#1923, #1924); 2.147.1 B (#2054): office_dunning
    'office_peppol',  // 2.154.0 B (#1960): e-invoices over Peppol
    'office_payonline',  // 2.469.0 (#3459): online payment of invoices
    'office_bankrules',  // 2.299.0 B (#3191): bank rules
    'office_bankacc',  // 2.470.0 (#3596): the bank accounts of the office
    'office_docproject',  // 2.168.0 A (#2665): documents bound to a project
    'office_agreements', 'office_assets',  // 2.92.0 (#1925, #1931)
    'office_meals',  // 2.119.0 A (#2288): entertainment receipts
    'office_leads', 'office_cfiles',  // 2.94.0 A (#1930), 2.117.0 B (#2285)  // 2.76.0 A (#1023): office_packs
    'office_letterhead', 'office_numranges', 'office_terms', 'office_procdoc',  // 2.120.0 E (#2091); 2.138.0 D (#2256): office_numranges; 2.113.2 (#2253): office_terms
    'office_letters', 'office_letterlinks', 'office_lettermail',  // 2.153.0 (#2028-#2030)
    'office_rights'],  // 2.187.0 A (#2476): the page "Rights" of the office's settings
  // 2.65.0 (#1823): more areas load on first use (the start loads about a third less)
  agentchat: ['agentchat', 'agentsetup', 'agentrotate', 'agentwork', 'agentcontrol', 'agentlock', 'agentrules', 'srvagent'],  // 2.557.0 C (#4670): srvagent.js = the setup of a server agent  // 2.236.0 A (#2904-#2911): agentwork.js = the dialog "Work style and notifications"
  pdf: ['pdfview', 'docpreview'],  // 2.92.0 C (#1926): docpreview.js = the Word / Excel preview
  swipenav: ['swipenav'],  // 2.652.0 (#5071 #5073): leafing with a swipe (the full screen of pdfview.js, the image viewer)
  mindmap: ['mindmap'],
  diagram: ['diagram'],  // 2.382.0 (#3153): formulas / Mermaid diagrams of knowledge pages, only when a page has one (wiki.js wk_dgNeed)
  wiki: ['wikie2e', 'wkshare', 'wkhist', 'wkembed', 'wklive', 'wkcm', 'wktags', 'wiki', 'wkimport', 'wikioff'],  // 2.637.0 (#4745): wikioff.js = a space's files offline;  // 2.371 (#3150): wktags.js = tags + the abfrage block; wiki.js after the parts its view draws with (a redraw in between hit wem_cut undefined), before wkimport.js (its wki_resume reports with wka_done);  2.177.0 (#2685): wkimport.js = large ZIP imports with progress; 2.123.0 B (#2104): wkshare.js = shares; A (#2102, #2106): wkhist.js = history + text search; C (#2103, #2107, #2108): wkembed.js = Ablage pictures, links, checkboxes; 2.501.0 (#4198): wikie2e.js FIRST: a failed load stops the chain, so wiki.js never runs (and writes) without the lock of its space  // 2.554.0 (#4052): wkcm.js = the editor (CodeMirror 6, static/vendor/codemirror, loaded by it on the first editing)
  stats: ['stats'],
  calendar: ['calview', 'caldrag', 'apptbook', 'calyear', 'listcal', 'calgest'],  // 2.94.0 B (#1929): apptbook.js = appointment booking settings; 2.155.0 C (#2078): calyear.js = the year view; 2.156.0 C (#2071): listcal.js = a list's calendar view; 2.164.0 (#2625): calgest.js = swipe / pinch
  calrrule: ['calrrule'],  // 2.155.0 C (#2075): the own repeat rule dialog, loaded by the event editor
  calabs: ['calabs'],  // 2.155.0 B (#2076, #2077): holidays / absences in the "Calendars" window, the availability bar
  docviews: ['docviews', 'docfacets'],  // 2.772.0 (#4890): docfacets.js = the filters with numbers below the file store's tree;  2.579.0 (#4802): saved views of the documents search (the list, the sidebar, Today)
  docs: ['docs', 'paperless', 'receipts', 'letterdoc', 'letteragent', 'docsplit', 'docscan', 'docfetch', 'abdocs', 'docview', 'tilesize', 'docflows', 'docnotes', 'docpages'],  // 2.583.0 (#4812): tilesize.js = the card size  // 2.583.0 (#4835): docview.js = the document view (was docread.js, the reading view)  // 2.353.0 D (#2759): abdocs.js; 2.153.0 (#2028, #2031): letterdoc.js, letteragent.js; 2.154.0 A (#1111): docsplit.js; 2.207.0 A (#2763): docscan.js
  life: ['life', 'devlink', 'budget'],  // 2.149.0 F (#2518): budget.js (its view and dialogs used life.js already)
   // 2.140.0 B (#2136): devlink.js = a device <-> office equipment
  integrations: ['integrations'],
  playbook: ['playbook'],
  timeline: ['timeline', 'roadmap'],
  feeds: ['feeds'],  // 2.85.0 B (#1162)
  bookmarks: ['bookmarks', 'readlater'],  // 2.97.0 A (#1950); 2.172.0 B (#2679): readlater.js = the view "Read later"
  cfkinds: ['cfkinds'],  // 2.156.0 B (#2069): editing multiple choice / rating cells, the task link picker, the field dialog's currency / rating part
  mineboard: ['mineboard'],  // 2.156.0 C (#2072): My tasks as a board
  minerules: ['minerules'],  // 2.823.0 (#4773): the dialog of the own rules of My tasks
  sectpl: ['sectpl'],  // 2.156.0 C (#2073): the section templates dialog of a list
  objprop: ['objprop'],  // 2.623.0 (#4718): the card of an agent's change proposal for a core object (agents.js propOpen)
  orgschema: ['orgschema'],  // 2.609.0 (#3373): the fields of the organisation in a project's settings, the required-field question
  asstprop: ['asstprop', 'sheetprop'],  // 2.126.1 A (#2123 #2124): texts worded by an agent (office, documents, status report, the proposal card); B (#2125): sheetprop.js (table rows as tasks)
  sheetpivot: ['sheetpivot'],  // 2.671.0 (#3463 b): the pivot sheet of a table (its view and dialog), when one is shown or made
  sheets: ['sheetfold', 'sheets', 'sheets2', 'sheetsio', 'sheetsize', 'sheetshare', 'sheetchart', 'sheetkinds', 'sheetprint', 'sheetbook', 'sheetfmt', 'sheetfill', 'sheetmove', 'sheetgroup'],  // 2.89.0 (#1916); D: sheets2.js (step 2), C: sheetsio.js (import/export); 2.98.0 C (#2181): sheetsize.js (the frame); 2.124.0 A (#2115): sheetchart.js; C (#2113): sheetshare.js; B (#2110): sheetkinds.js; E (#2116): sheetbook.js; 2.578.0 (#3462): sheetprint.js; 2.199.0 C (#2742): sheetfold.js (folders; 2.200.0 F: first, the overview calls it when sheets.js is in); 2.578.0 (#3462 C): sheetfmt.js (cell format, colour rules), sheetfill.js (the fill handle); 2.631.0 (#4620): sheetmove.js (move rows / columns); 2.671.0 (#3463): sheetgroup.js (groups + subtotals)
  fslock: ['fslock'],  // 2.353.0 A (#2758): locked folders of the file store (loaded by the file store's first view)
  tagsel: ['tagsel'],  // 2.122.0 B (#2099 #2294 #2295): tag picker, tag filter buttons, Shift ranges (file store + documents); 2.124.2: before videos (polls / formq stay last, p2102_c_ui)
  ablage: ['ablage', 'ablinks'],  // 2.501.0 (#4198): the file store (ablage.js) and its external links, on its first view / panel
  family: ['family'],  // 2.501.0 (#4198): the module Family, on its view, a family list, a task panel while it is on
  filereq: ['filereq'],
  fltdlg: ['fltdlg'],  // 2.521.0 (#4479): the dialog of a saved filter (condition rows)  // 2.122.0 A (#2097): file request links of a folder (dialog on demand)
  fints: ['office_fints'],  // 2.616.0 (#2473): the direct bank fetch over FinTS (the office's tab Bank)
  fsshare: ['fsshare'],  // 2.199.0 A (#2742): the one Share dialog of folders / files (file store, office, tables)
  videos: ['videorev'],  // 2.99.1 A (#1959): video sign-offs
  abscan: ['abscan'],  // 2.112.1 (#2058): the phone scan dialog of the file store and the documents
  pubvideo: ['pubvideo'],  // 2.99.1 A (#1959): only the customer page of a video sign-off loads it (/s/q/<token>), the app never
  flow: ['flow'],  // 2.393.2 (#3374): the card "Flow" of a project page (projects.js asks for it when it draws the card)
  hookin: ['hookin'],  // 2.115.0 (#2061): inbound webhooks of a list, loaded when its settings open
  polls: ['polls'],  // 2.102.0 C (#2208): scheduling polls (#1953), on the first "Find a date"
  formq: ['formq'],  // 2.102.0 C (#2208): questionnaires (#1954), with the forms dialog of a list
  navmenu: ['navmenu'],  // 2.418.0 (#3560): the editor of the areas' menus (Customize / the pen, Settings > Navigation)
  tourmods: ['tourmods'],  // 2.466.0 (#3314): the steps of the areas' introductions
  ofundo: ['office_undo'],  // 2.111.0 A (#2233): undo of the office editors, clients and tables (office, sheets and the client dialog load it)
  objsave: ['objsave'],  // 2.558.0 (#4709): the dialogs of the areas on the shared core (saveDialog, merge bar, undo; core/writes.py)
  voice: ['voice'],  // 2.139.0 B (#2128): voice messages of the team chat (the composer's microphone, the audio player)
  hubmailbox: ['hubmailbox', 'mailrules'],  // 2.581.0 (#4804): mailrules.js = the document rules of the mailbox dialog
  listprint: ['listprint'],
  evinvite: ['evinvite'],
  projtime: ['projtime'],
  envs: ['envs'],
  dayplan: ['dpmodal'],
  gitrepo: ['gitrepo'],
  timesheet: ['timesheet'],
  team: ['absence', 'leave', 'dispo'],
  hubmail: ['hubmail'],
  msvview: ['msvview'],
  sprints: ['sprints2'],  // 2.149.0 F (#2518): the sprint dialogs and writes (sprints.js keeps the header, the filter and the clicks)  // 2.149.0 F (#2518): the other servers in one app (its state and stand-ins in render.js)  // 2.149.0 F (#2518): the e-mail filing (its view, the mail sections, the reading view); the links stay in clientpage.js  // 2.149.0 F (#2518): the tabs Absences / Disposition of the workload view, vacation, the working week of the settings  // 2.149.0 F (#2518): the monthly timesheets of the time page, the time zone rows of the settings  // 2.149.0 F (#2518): the repository editor of the list dialog / the folder settings (git.js keeps the rest)  // 2.149.0 F (#2518): the dialog of "Plan my day" (Today's cards stay in dayplan.js)  // 2.149.0 F (#2518): the environments of a project (its page, a milestone's panel); the texts of the rows stay in quickadd.js  // 2.149.0 F (#2518): the tracked time of a project / folder (a click on its "Tracked" figure)  // 2.149.0 F (#2518): invitations by e-mail of an event (the event editor loads it with its people)  // 2.149.0 F (#2518): the print view of a list (its menu's "Print"); the CSV export stays below
   // 2.141.0 A (#2141, #2138): the mailbox of a workspace + writing from the e-mail filing (hubmail.js draws its buttons)
  sideviews: ['sideviews'],  // 2.156.0 D (#2186): saved views of the sidebar (favtiles.js has the stand-ins)
  notetrash: ['notetrash'],  // 2.272.0 E1 (#3038): the notes of a project in the trash (chat.js draws the button)
  trashui: ['trashui'],  // 2.272.0 G (#3038): the trash dialogs / views of 2.272.0 (start budget)
  clientpage: ['clientpage'],  // 2.563.0 (#4742): Office > Clients (the list and the client's card), on its view; the office, the contacts and the trash use its globals (LD_NEED)
  whatsnew: ['whatsnew'],  // 2.556.0 (#4685): the dialog "New for you" after an update (wn_boot below loads it only when there is news)
  offcache: ['offcache'],  // 2.663.0 (#4200): the offline start state in IndexedDB (core.js startSave / startRead)
  shoot: ['shoot'],  // 2.636.0 (#4565): the storyboard of a shoot (picture tiles on the board, the button Shot list)
  splitview: ['splitview'],  // 2.742.0 (#4858): the split view on a wide screen, only while it is on (miniwin.js spl_check)
  codecheck: ['codecheck'],  // 2.766.0 (#5220): Settings > Help > Check code (the hashes of the code this browser holds)
  undolist: ['undolist'],  // 2.773.0 (#5250): the list "Recent steps" (the ← button's right-click / long-press, the page #steps)
  recent: ['recent'],  // 2.769.0 (#5352): "Recently edited" (the overview "All workspaces" of Knowledge / Files / Reading, the start page's block)
  ofwalk: ['office_walk'],  // 2.778.0 (#5383): the walk-through of open card positions / bank bookings (office_cards.js, office_bank.js)
  callsheet: ['callsheet'],  // 2.802.0 (#1956): the call sheet of a shoot day (the disposition's booking dialog, Film & Video only)
};
// 2.65.0 (#1823): modules a module needs before its own files (their globals are used while it draws): the settings dialog
// draws the agent panes (agentchat.js), the calendars (calview.js) and the tokens / webhooks (integrations.js), the agent chat
// uses the token dialogs, a knowledge page embeds mind maps; 2.87.9 (#1936): Paperless-ngx (paperless.js) is in Integrations
const LD_NEED = {pdf: ['swipenav'], settings: ['agentchat', 'calendar', 'integrations', 'playbook', 'docs', 'timesheet', 'team', 'family'], agentchat: ['integrations'], wiki: ['mindmap'], docs: ['ablage', 'tagsel', 'asstprop'], office: ['asstprop', 'ofundo', 'ablage', 'clientpage'], contacts: ['clientpage'], trashui: ['clientpage'], sheets: ['ofundo'], fsshare: ['ablage'], filereq: ['ablage'], tagsel: ['ablage'], fslock: ['ablage']};  // 2.122.0 B: docs -> tagsel; 2.126.1 A (#2123): docs / office -> asstprop; 2.652.0 (#5071): pdf -> swipenav (the swipe of the full screen)
// 2.599.0 (#4907): settings no longer name ablage: their sharing defaults load it themselves (settings.js); docs still needs it
// 2.501.0 (#4198): module ablage: docs (the folder tree, moves, menus), office (FS_REF_ICON, requests) and the parts of the file store use its globals
// functions of a module that code loaded at start calls: a stand-in loads the module and then calls the real one (the
// module's own function declaration replaces the stand-in on window)
const LD_CALL = {settings: ['settingsModal', 'setApply', 'settingsSync', 'modCountsSync', 'setSaved', 'setLocal', 'ojn_open', 'otkOpen'],  // 2.149.0 F (#2519): setLocal (the command bar's "Theme: …"); bundle B: ojn_open (2.148.1 #2480, bell item of an invitation); 2.574.0 (#3376): otkOpen (acctset.js)
  ablage: ['ab_linkFile'],  // 2.501.0 (#4198): the button of a file row in a task / project
  fltdlg: ['filterModal'],  // 2.521.0 (#4479): the filter dialog (sidebar, palette, a filter's menu)
  fints: ['fnt_open'],  // 2.616.0 (#2473): the button "Fetch from bank" (office_bank.js)
  family: ['occModal', 'dlModal', 'famPack', 'shopModeOpen', 'paskOpen', 'kd_pinAsk'],  // 2.501.0 (#4198): the palette, the first start, a child's PIN
  contacts: ['ctRoute', 'ctEditor'], filereq: ['frq_open'], fsshare: ['fs_shareDialog'],  // 2.199.0 A (#2742): fsshare
  // 2.65.0 (#1823)
  agentchat: ['acdDeleteMsg', 'chatOpen', 'ac_modOff', 'chatClose', 'chatPop', 'chatDock', 'chatFloatMin', 'apvJump', 'chatChoice', 'shareDest', 'chatFileRm', 'chatReact',
    'chatModeMenu', 'stepsAlways', 'stepsLive', 'chatEditStart', 'chatOlder', 'chatSend', 'chatBottom', 'chatDraw', 'agModal', 'agDraw', 'aiuLoad', 'ains_setupModal', 'awOpen'],
  pdf: ['pdfView', 'dpvOpen', 'dpvSumMount'], calendar: ['calColorPop', 'cg_commit', 'apbOpen'], docs: ['dc_shareFiles', 'dc_filterGo', 'dc_facetGo', 'dc_settings', 'pl_importActive', 'pl_openSettings'],  // 2.87.9 (#1934); 2.94.0 B (#1929): apbOpen; 2.772.0 (#4890): dc_facetGo, dc_settings (the filters below the file store's tree)
  life: ['contractModal', 'deviceModal', 'upkeepModal', 'healthModal', 'tripModal'], integrations: ['pubWire'],
  playbook: ['pbMount', 'pbOpen', 'pbNewsOpen'], timeline: ['rmSet'],
  bookmarks: ['bm_shareSave', 'bm_confirmSave', 'bm_bookmarkletHelp', 'rdl_shareSave'],  // 2.97.0 A (#1950); 2.172.0 B (#2679): rdl_shareSave
  asstprop: ['ast_rpt'],  // 2.126.1 A (#2124): the status report dialog (projects.js)
  polls: ['tpo_list', 'tpo_edit', 'tpo_forClient'], formq: ['fq_clientLink'],  // 2.102.0 C (#2208)
  abscan: ['abm_scanOpen'],  // 2.112.1 (#2058)
  cfkinds: ['cfkTcEdit', 'cfkPick', 'cfkModalExtra'],  // 2.156.0 B (#2069)
  trashui: ['doneCleanup', 'ms_clTrashAct', 'attRestore', 'attPurge', 'trEmpty', 'trPurgeTask', 'trPurgeList'],  // 2.272.0 G (#3038); 2.530.0 D (#4316): tr*
  hookin: ['whiMount'],  // 2.115.0 (#2061)
  wiki: ['wk_minutes'],  // 2.384.0 (#1958): "Minutes" in an event's popover (calevents.js)
  sectpl: ['sct_open', 'ticketTplModal'],  // 2.156.0 C (#2073); 2.609.0 (#3372): ticketTplModal
  orgschema: ['ofs_mount', 'ofs_manage', 'rqf_ask', 'olb_manage'],  // 2.609.0 (#3373)
  hubmailbox: ['hmb_dialog', 'hmb_compose'],  // 2.141.0 A (#2141, #2138)
  listprint: ['lexPrint'], evinvite: ['evf_modal'], projtime: ['tz_open'], dayplan: ['dayplanModal'], gitrepo: ['repoWire', 'folderRepoModal'], hubmail: ['hbm_open'],
  sprints: ['spr_assign', 'spr_pick', 'spr_cfgModal', 'spr_cfgSet', 'spr_closeModal', 'spr_moreMenu'],  // 2.149.0 F (#2518)
  undolist: ['ul_open'],  // 2.773.0 (#5250): the window of the ← button
  ofwalk: ['wlk_open'],  // 2.778.0 (#5383)
  callsheet: ['cs_open']};  // 2.802.0 (#1956): the button "Call sheet" (dispo.js)
// 2.65.0 (#1823): functions that only update what the module drew: before it is loaded there is nothing to update (no loading)
const LD_NOP = {agentchat: ['chatLoad', 'chatPatch', 'chatFit', 'stepsChanged', 'chatTypers', 'chatStHtml'], timeline: ['tlKbSync', 'tlAfterRender', 'rmAfterRender'],
  timesheet: ['tsl_printNote'],  // 2.149.0 F (#2518): the printed timesheet's month line (nothing before the card loaded the month)
  clientpage: ['ms_clDraw', 'ms_clDirty', 'ms_clLive']};  // 2.563.0 (#4742): the client page redraws / reloads only what it drew
// drawing functions: the stand-in draws "Loading…" (views) or nothing (parts of another view), loads, and redraws the view
// 2.65.0 (#1824): module -> its stylesheets in static/css/ (the same files as LAZY_CSS in sw.js, same order); loadModule loads
// them next to the scripts and resolves only once they apply (no unstyled flash when the area opens)
const LD_CSS = {settings: ['settings'], contacts: ['contacts'], office: ['office'], agentchat: ['agentchat'], pdf: ['pdf'], mindmap: ['mindmap'],
  wiki: ['wiki'], stats: ['stats'], calendar: ['calendar'], docs: ['docs', 'docview'] /* 2.583.0 (#4835) */, docviews: ['docviews'], life: ['life'],
  integrations: ['integrations'], playbook: ['playbook'], timeline: ['timeline'], feeds: ['feeds'], bookmarks: ['bookmarks'], sheets: ['sheets'], videos: ['videorev'], tagsel: ['tagsel'], filereq: ['filereq'], fltdlg: ['fltdlg'], abscan: ['abscan'], ablage: ['ablage'] /* 2.558.0 (#4693) */, calabs: ['calabs'], sideviews: ['sideviews'], navmenu: ['navmenu'], whatsnew: ['whatsnew'], shoot: ['shoot'], splitview: ['splitview'] /* 2.742.0 (#4858) */, undolist: ['undolist'] /* 2.773.0 (#5250) */, evinvite: ['evedit'] /* 2.846.0 (#5465): the event editor */, callsheet: ['callsheet'] /* 2.802.0 (#1956) */};  /* 2.636.0 (#4565) */  // 2.418.0 (#3560): + navmenu  // 2.97.0 A (#1950): + bookmarks  // 2.85.0 B (#1162): + feeds
const LD_VIEW = {viewFamily: ['family', 1], viewAblage: ['ablage', 1], viewContacts: ['contacts', 1], viewOffice: ['office', 1], kp_tile: ['office'], ux_info: ['office'], ofcII: ['office'],
  dpj_projHtml: ['office'],  // 2.168.0 A (#2665): a project page's quotations & invoices (only while the office is on)
  // 2.65.0 (#1823)
  chatViewHtml: ['agentchat', 1], jobStepsHtml: ['agentchat'], aiuCardHtml: ['agentchat'], aiuNewsText: ['agentchat'], chatInner: ['agentchat'],
  chatMsgs: ['agentchat'], chatWinBtns: ['agentchat'], viewWiki: ['wiki', 1], viewMindmap: ['mindmap', 1],
  mm_blockHtml: ['mindmap'], viewStats: ['stats', 1], viewCal: ['calendar', 1], viewDocs: ['docs', 1], viewLife: ['life', 1], viewReview: ['life', 1], viewBudget: ['life', 1], pbNewsText: ['playbook'], viewTimeline: ['timeline', 1], viewRoadmap: ['timeline', 1],
  tlNdBtn: ['timeline'], tlNdOn: ['timeline'],
  viewFeeds: ['feeds', 1], rss_homeCard: ['feeds'],  // 2.85.0 B (#1162)
  viewBookmarks: ['bookmarks', 1],  // 2.97.0 A (#1950)
  viewReading: ['bookmarks', 1],  // 2.172.0 B (#2679)
  viewSheets: ['sheets', 1],  // 2.89.0 (#1916)
  lcal_view: ['calendar', 1], mb_view: ['mineboard', 1],  // 2.156.0 C (#2071, #2072): a list's calendar, the board of My tasks
  hmb_hubSection: ['hubmailbox'], hmb_newBtn: ['hubmailbox'], hmb_replyBtn: ['hubmailbox'],  // 2.141.0 A (#2141, #2138): parts of the e-mail filing
  tvc_micHtml: ['voice'], tvc_playerHtml: ['voice'],  // 2.139.0 B (#2128): the team chat's composer / an audio file load voice.js
  ntTrashHtml: ['notetrash'],  // 2.272.0 E1 (#3038)
  ms_clTrashHtml: ['trashui', 1], povTrashHtml: ['trashui'],  // 2.272.0 G (#3038)
  vtr_html: ['trashui'],  // 2.549.0 (#4536): the video sign-offs in the trash view
  ptr_html: ['trashui'],  // 2.567.0 A (#4707): sections, sprints, links, templates and budget rows in the trash view
  tsl_card: ['timesheet'], hbm_hubView: ['hubmail', 1],  // 2.149.0 F (#2518): the time page's timesheet card (it fetches the month itself)
  sht_pic: ['shoot'], sht_bar: ['shoot'],  // 2.636.0 (#4565): the board of a shoot (calendar.js viewKanban)
  ms_clView: ['clientpage', 1],  // 2.563.0 (#4742): Office > Clients (clients.js viewClients)
  mr_open: ['minerules'],  // 2.823.0 (#4773): My tasks > Rules…
  viewSteps: ['undolist', 1]};  // 2.773.0 (#5250): the page "Recent steps"
// 2.556.0 (#4685) "New for you": once per new version (the version seen last is a user setting, accounts/whatsnew.py) the
// server is asked what is new since then; only when there is something the dialog's module loads (whatsnew.js). Nothing at
// all on a server without the feature (no whatsnew_seen), for agents, in a second window or the capture page.
function wn_boot(tries = 0) {
  const s = S.settings || {};
  if (s.whatsnew_seen == null || !APP_VER || s.whatsnew_seen === APP_VER || S.me?.kind === 'agent' || MW_ON || S.capturePage) return;
  if ((TOUR.on || $('.modal')) && tries < 20) { setTimeout(() => wn_boot(tries + 1), 3000); return; }  // after the tour / an open dialog
  api('GET', '/api/whatsnew').then(j => {
    s.whatsnew_seen = j.seen;
    if (j.on && j.versions?.length) loadModule('whatsnew').then(() => wn_open(j), () => {});
    else if (j.seen !== j.current) api('POST', '/api/whatsnew/seen').then(r => { s.whatsnew_seen = r.seen; }, () => {});
  }, () => { /* offline / an older server: the next start asks again */ });
}
// 2.102.0 C (#2208) scheduling polls (polls.js, module polls): the switch and the start points' clicks stay at start (moved
// here): "Find a date" in the calendar bar and in a task (calevents.js), a client's "…" menu (tpo_forClient, a stand-in)
const tpo_on = () => feat('events') && S.me?.kind !== 'agent';
document.addEventListener('click', e => {
  const el = /** @type {HTMLElement} */ (e.target);
  if (el.closest?.('[data-act="tpo-list"]')) { tpo_list(); return; }
  if (el.closest?.('[data-act="tpo-task"]')) {
    const t = taskById(S.sel); if (!t) return;
    tpo_edit(null, {task_id: t.id, title: t.title, space: wsOf(listById(t.list_id))});
  }
});
// 2.501.0 (#4198) the file store (ablage.js, module ablage): what the start files ask before it is loaded stays here (moved here):
// the module switch, the names of the spaces, the hint of a trashed folder, the "Show in the file store" button of a file row
const ab_on = () => feat('files') && !S.me?.kid;
FEAT_DESC.files = N_('Folders and files, shared with people and agents, versions');
const ab_spaceName = s => s === 'private' ? tr('Private|workspace') : s === 'shared' ? tr('Shared with me') : s === 'trash' ? tr('Trash') : wsName(s);
const ab_spaceIcon = s => s === 'private' ? ic('home', 's') : s === 'shared' ? ic('users', 's') : s === 'trash' ? ic('trash', 's') : wsIcon(s);
const fs_keptText = kept => kept?.length ? trn('{0} entry stays, one level up: {1}', '{0} entries stay, one level up: {1}', kept.length, [...new Set(kept.map(k => k.reason))].join(', ')) : '';
const ab_linkBtn = (kind, id, org, cls) => ab_on() ? `<button type="button" class="${cls} ablink" data-ablink="${kind}:${id}:${org || ''}" title="${esc(tr('Show in the file store'))}" aria-label="${esc(tr('Show in the file store'))}">${ic('folder', 's')}</button>` : '';
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-ablink]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const [k, id, org] = b.dataset.ablink.split(':');
  ab_linkFile(k, +id, +org || null);
}, true);
// 2.501.0 (#4198) the module Family (family.js, module family; off by default): what the rows, the task panel, the start page, the
// palette and a child's PIN ask at start stays here (moved here); its bar and the panel's section load it when one is drawn.
const famOn = () => feat('family');
S.kids = []; S.famWeek = null; S.shop = null;
const famKindOf = lid => listById(lid)?.family || '';
const isOcc = t => !!t?.fam && (t.fam.kind === 'birthday' || t.fam.kind === 'anniversary');
const occAge = t => isOcc(t) && t.fam.year && t.due ? +t.due.slice(0, 4) - t.fam.year : null;
function occWhat(t) {
  const a = occAge(t); if (a == null || a < 0) return '';
  return t.fam.kind === 'birthday' ? tr('turns {0}', a) : trn('{0} year', '{0} years', a);
}
const daysTo = d => Math.round((+pd(d) - +pd(today())) / 864e5);
function daysWord(n) { return n === 0 ? tr('today') : n === 1 ? tr('tomorrow') : n < 0 ? trn('{0} day ago', '{0} days ago', -n) : trn('in {0} day', 'in {0} days', n); }
const isShopItem = t => !!t && !t.parent_id && (t.fam?.kind === 'shop' || (famKindOf(t.list_id) === 'shopping' && !t.fam));
const shopQty = t => t?.fam?.kind === 'shop' && t.fam.qty != null ? fmtNum(t.fam.qty, 3) + (t.fam.unit ? ' ' + t.fam.unit : '') : (t?.fam?.kind === 'shop' && t.fam.unit ? t.fam.unit : '');
const famRowQty = t => famOn() && isShopItem(t) && shopQty(t) ? `<span class="qtym" title="${esc(tr('Quantity'))}">${esc(shopQty(t))}</span>` : '';
const PACK_UI = [['holiday', N_('Holiday'), 'beach'], ['pool', N_('Swimming pool'), 'wave'], ['daycare', N_('Daycare'), 'bag'], ['camping', N_('Camping'), 'tent'], ['business', N_('Business trip'), 'brief']];  // 2.223.0 C (#2820): app icons, not emoji
function rxMore(anchor) {
  const act = anchor.dataset.rxact, mid = +anchor.dataset.mid;
  reactPicker(anchor, null, v => act === 'chat-react' ? chatReact(mid, v) : act === 'tc-react' ? tcReact(mid, v) : null);
  setTimeout(() => $('#pop .rxgrid button')?.focus({preventScroll: true}), 0);
}
document.addEventListener('click', e => { const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-act="rx-more"]'); if (!b) return; e.preventDefault(); e.stopPropagation(); rxMore(b); });
function sideSearchSync() {
  const sc = $('#scrim'); if (!sc) return;
  let b = $('.sidesearch', sc);
  if (!b) {
    b = document.createElement('button'); b.type = 'button'; b.className = 'iconbtn sidesearch';
    b.addEventListener('click', e => { e.stopPropagation(); closeSide(); openPalette(); });
    sc.appendChild(b);
  }
  const lab = tr('Search and commands');
  if (b.getAttribute('aria-label') !== lab) { b.setAttribute('aria-label', lab); b.title = lab; b.innerHTML = ic('search'); }
}
const kd_me = () => (S.me?.kid && (S.kids || [])[0]) || null;
function kd_pinNeed() { const k = kd_me(); return !!(k && k.pin && !(k.pin_open && Date.parse(k.pin_open) > Date.now())); }
function kd_pinClosed() { const k = kd_me(); if (k) { k.pin_open = null; if (!$('.kdpin')) kd_pinAsk(); } }
window.famBar = l => { if (famOn() && l?.family && !l.archived) ld_later('family'); return ''; };
window.famDetailHtml = t => { if (famOn() && t?.id > 0 && !t.context) loadModule('family').then(() => { if (S.sel === t.id) renderDetail(); }, () => {}); return ''; };
// stays at start (core.js modOn, areas, dashboard, the client page ask it before anything of the office is loaded)
const officeOn = () => feat('office') && !S.me?.kid;

const LD_P = {};  // module -> the promise of its loading (each module once)
let ld_n = 0, ld_t = 0;
function ld_bar(d) {  // the thin bar at the top: only when loading takes longer than 300 ms (a slow connection)
  ld_n = Math.max(0, ld_n + d);
  clearTimeout(ld_t);
  let el = document.getElementById('ldbar');
  if (!ld_n) { el?.classList.remove('on'); return; }
  ld_t = setTimeout(() => {
    if (!el) { el = document.createElement('div'); el.id = 'ldbar'; el.className = 'ldbar'; el.setAttribute('aria-hidden', 'true'); document.body.appendChild(el); }
    el.getBoundingClientRect?.(); el.classList.add('on');
  }, 300);
}
// 2.660.0 (#4197): the content hash of each module file (index.html meta kalmido-ldjs / kalmido-ldcss, written by the server,
// core/pages.py ld_hash_metas): asked for with ?v=<hash>, the service worker answers from its precache without the network and a
// new version loads only the files that changed; a file without a hash (an older server) keeps the version of the code
/** @type {Record<string, Record<string, string>>} */
const LD_HASH = {js: ld_hashes('js'), css: ld_hashes('css')};
/** @param {string} k @returns {Record<string, string>} */
function ld_hashes(k) {
  /** @type {Record<string, string>} */
  const o = {};
  const el = /** @type {HTMLMetaElement | null} */ (document.querySelector?.(`meta[name="kalmido-ld${k}"]`));
  for (const p of (el?.content || '').split(' ')) { const [f, h] = p.split('='); if (f && /^[0-9a-f]{12}$/.test(h || '')) o[f] = h; }
  return o;
}
/** @param {string} k @param {string} f */
const ld_q = (k, f) => { const v = LD_HASH[k][f] || APP_VER; return v ? '?v=' + encodeURIComponent(v) : ''; };
const ld_url = f => `/static/js/${f}.js` + ld_q('js', f);
const LD_CSSP = {};  // stylesheet -> the promise of its link (each once)
function loadCss(f) {  // 2.65.0 (#1824): one stylesheet of static/css/; also usable alone (an area that is no module)
  if (LD_CSSP[f]) return LD_CSSP[f];
  return LD_CSSP[f] = new Promise((res, rej) => {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = `/static/css/${f}.css` + ld_q('css', f); l.dataset.ldcss = f;  // 2.660.0 (#4197): its content hash
    l.onload = () => res();
    l.onerror = () => { l.remove(); delete LD_CSSP[f]; rej(new Error('could not load ' + f + '.css')); };
    document.head.appendChild(l);
  });
}
const LD_RAN = new Set();  // files that have run (a retry after a failure loads only the rest: a second run would declare twice)
// 2.599.0 (#4907): a file that threw while it ran (or could not be parsed) fires "load" all the same. It does not count as run:
// the files after it in its module would run on its missing globals (ablinks.js on AB_ACT of a broken ablage.js), and their
// top-level const / let stay locked for good (xl_stdHtml "before initialization" in the settings). Its error rejects the module;
// a second run cannot help (its own names are locked too), so it is kept here and only a reload of the page loads it again.
const LD_BAD = new Map();  // file -> the error of its run
const LD_PEND = new Map();  // file -> the promise of its tag while it loads (two chains never insert the same file twice)
function ld_script(f) {
  if (LD_RAN.has(f)) return Promise.resolve();
  if (LD_BAD.has(f)) return Promise.reject(LD_BAD.get(f));
  if (LD_PEND.has(f)) return LD_PEND.get(f);
  // 2.750.0 (#5307): not before DOMContentLoaded - an inserted script runs as soon as it is there, maybe before the last start
  // scripts (keys.js: kb_on), and a module that failed so stays broken until a reload (LD_BAD). The defer start scripts run
  // while readyState is already 'interactive', so the flag of core.js (domLoaded / domReady), not readyState.
  const parsed = domLoaded ? null : new Promise(r => domReady(() => r(undefined)));
  const p = (parsed || Promise.resolve()).then(() => new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = ld_url(f);
    s.dataset.ld = f;
    let err = null;
    const own = ev => document.currentScript === s || (!!ev.filename && new URL(ev.filename, location.href).pathname === `/static/js/${f}.js`);
    const onErr = ev => { if (!err && own(ev)) err = ev.error || new Error(ev.message); };
    window.addEventListener('error', onErr);
    const done = () => { window.removeEventListener('error', onErr); LD_PEND.delete(f); };
    s.onload = () => {
      done();
      if (err) {
        const e = new Error(`${f}.js failed while it ran: ${err.message || err}`);
        LD_BAD.set(f, e); console.error('loadModule', e); rej(e); return;
      }
      LD_RAN.add(f); res();
    };
    s.onerror = () => { done(); s.remove(); rej(new Error('could not load ' + f)); };
    document.head.appendChild(s);
  }));
  LD_PEND.set(f, p);
  return p;
}
// loadModule('settings') -> a promise that resolves once the module's files have run. A failure (offline without the cached
// copy, a server restart) shows a toast with "Try again" (again: what to repeat) and may be retried.
function loadModule(name, again) {
  if (LD_P[name]) return LD_P[name];
  const files = LD_MODS[name];
  if (!files) return Promise.reject(new Error('unknown module ' + name));
  ld_bar(1);
  const need = Promise.all((LD_NEED[name] || []).map(m => loadModule(m)));  // 2.65.0 (#1823)
  // the files of one module run one after the other (later ones use the first one's globals); the browser fetches them side
  // by side meanwhile (preload)
  for (const f of files.slice(1)) {
    const l = document.createElement('link'); l.rel = 'preload'; l.as = 'script'; l.href = ld_url(f); l.dataset.ld = f; document.head.appendChild(l);
  }
  const css = Promise.all((LD_CSS[name] || []).map(loadCss));
  // 2.191.0 A (#1410 #2518): the module's texts of the active language come beside its files, before they run (i18n.js)
  const tx = typeof i18nPart === 'function' ? i18nPart(name) : Promise.resolve();
  const p = LD_P[name] = Promise.all([css, files.reduce((q, f) => q.then(() => ld_script(f)), Promise.all([need, tx]))]).then(() => { ld_bar(-1); }, e => {
    ld_bar(-1); delete LD_P[name];
    for (const f of files) if (!LD_RAN.has(f)) document.querySelectorAll(`[data-ld="${f}"]`).forEach(x => x.remove());
    if (files.some(f => LD_BAD.has(f))) toast(tr('Could not be loaded'), () => location.reload(), 8000, tr('Reload'));  // 2.599.0 (#4907): only a reload runs a broken file again
    else toast(tr('Could not be loaded'), again || (() => loadModule(name)), 8000, tr('Try again'));
    throw e;
  });
  return p;
}
const LD_DONE = new Set();  // modules that have run
function ld_all() { return Promise.all(Object.keys(LD_MODS).map(m => loadModule(m)).concat(Object.values(LD_CSS).flat().map(loadCss))); }  // the test suites (tests/boot.js: window.ld_all)
let ld_rv = 0;
function ld_later(name) {  // a view part asked for a module: load it, then draw the view again (once per load)
  if (LD_DONE.has(name)) return;  // loaded: a stand-in still asked (should not happen) - no redraw loop
  loadModule(name, () => ld_later(name)).then(() => {
    if (LD_DONE.has(name)) return;
    LD_DONE.add(name);
    if (!ld_rv) ld_rv = setTimeout(() => { ld_rv = 0; renderView(); }, 0);
  }, () => {});
}
for (const [m, ns] of Object.entries(LD_CALL)) for (const n of ns) {
  const stub = function (...a) {
    const again = () => stub.apply(this, a);
    return loadModule(m, again).then(() => {
      const f = window[n];
      if (typeof f !== 'function' || f === stub) throw new Error(n + ' is missing in ' + m);
      return f.apply(this, a);
    }).catch(e => { console.warn('loadModule', m, e); });
  };
  window[n] = stub;
}
for (const ns of Object.values(LD_NOP)) for (const n of ns) window[n] = () => '';  // 2.65.0 (#1823)
// a part of another view (the client page's office hints, the start page's figures) loads the office only when it is on
for (const [n, [m, view]] of Object.entries(LD_VIEW)) window[n] = () => { if (!view && m === 'office' && !officeOn()) return ''; ld_later(m); return view ? `<p class="muted lempty">${tr('Loading…')}</p>` : ''; };
// the office switch of an agent (Settings > Agents, the agent chat's settings): its row is drawn at once, the office part
// only loads when the office is on
window.oa_switchRowHtml = aid => officeOn() ? `<div class="oa_sw" data-oa-aid="${+aid}" hidden></div>` : '';
window.oa_switchLoad = md => !officeOn() ? Promise.resolve() : loadModule('office').then(() => { if (/** @type {any} */ (window.oa_switchLoad).ld) return; return oa_switchLoad(md); }).catch(() => {});
/** @type {any} */ (window.oa_switchLoad).ld = 1;
// 2.65.0 (#1823) knowledge pages: the command bar's pages and a task's "Mentioned in" load the module in the background (the
// first time without them, as before while the pages were fetched); the task panel is drawn again once it is there
window.wk_palAdd = () => { if (feat('wiki')) loadModule('wiki').catch(() => {}); };
// 2.99.1 A (#1959): video sign-offs (videorev.js, module videos): a task's panel, a project's overview and a client's card load
// the module when they are drawn and draw again once it is there
window.vdr_taskHtml = t => { if (t?.id > 0) loadModule('videos').then(() => { if (S.sel === t.id && vdr_rows('task_id', t.id, () => vdr_redrawTask(t.id))) vdr_redrawTask(t.id); }, () => {}); return ''; };  // 2.96.3: one redraw, focus kept
window.vdr_projHtml = window.vdr_clientHtml = () => { ld_later('videos'); return ''; };
// 2.563.0 (#4742) the client page (clientpage.js, module clientpage) loads on demand: the start part of the e-mail filing that
// lived there stays at start (moved here unchanged from clientpage.js, 2.149.0 F #2518): the link to the mail a task / an event
// was made from, its click, the stand-ins of the client's card and the project page
// the mail a task / an event was made from: "E-mail: <subject>" (a tap opens it); only "E-mail" for who may not read the
// mail (the server sends neither subject nor id then). Filled after the answer (cached a minute), the detail is not redrawn
const HBML = {};  // 'task:<id>' | 'event:<id>' -> {at, links}
function hbm_linkHtml(kind, id) {
  if (!(id > 0)) return '';
  const k = `${kind}:${id}`, c = HBML[k];
  if (!c || Date.now() - c.at > 60000) hbm_linkLoad(k);
  return `<div class="hbmlnk" data-hbmlnk="${k}">${c ? hbm_linkInner(c.links) : ''}</div>`;
}
const hbm_linkInner = links => (links || []).map(x => x.mail_id
  ? `<button type="button" class="linkbtn" data-hbmopen="${x.mail_id}" data-hbmk="link">${ic('mail', 's')}<span>${esc(tr('E-mail: {0}', x.subject || tr('(no subject)')))}</span></button>`
  : `<span class="muted">${ic('mail', 's')} ${tr('E-mail')}</span>`).join('');
async function hbm_linkLoad(k) {
  const [kind, id] = k.split(':');
  HBML[k] = {at: Date.now(), links: HBML[k]?.links || []};
  let j; try { j = await rawFetch('GET', `/api/hubmail/links?${kind}_id=${id}`); } catch { return; }
  HBML[k] = {at: Date.now(), links: j.links || []};
  for (const el of document.querySelectorAll(`[data-hbmlnk="${k}"]`)) el.innerHTML = hbm_linkInner(j.links);
}
const hbm_taskLinkHtml = t => t && !t.context ? hbm_linkHtml('task', t.id) : '';
document.addEventListener('click', e => {
  const o = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-hbmopen]')); if (!o) return;
  e.preventDefault(); if (o.closest('#pop') && typeof closePop === 'function') closePop(); hbm_open(+o.dataset.hbmopen, o.dataset.hbmk);
});
window.hbm_clientHtml = c => { if (c) ld_later('hubmail'); return ''; };
window.hbm_projHtml = l => { if (l && !l.is_inbox && !l.e2e && !l.life && !l.family) ld_later('hubmail'); return ''; };
// 2.394.0 C (#3377): the history lines of the issue sync (gitrepo.js): the task panel draws again once the module is there
window.gsy_actText = () => { loadModule('gitrepo').then(() => S.sel && renderDetail(), () => {}); return ''; };
window.wk_mentionHtml = t => { if (feat('wiki') && t?.id > 0) loadModule('wiki').then(() => { if (S.sel === t.id) renderDetail(); }, () => {}); return ''; };
// 2.65.0 (#1823) the PDF preview (pdfview.js, module pdf): its links are drawn at start, a click loads the module (moved here
// from pdfview.js). A link that should open the preview: <a href="…" data-pview='{"url","name","size","dlUrl"}'>; a modifier
// key keeps the browser's own behaviour (Ctrl/Cmd-click = new tab), like the text viewer's links
document.addEventListener('click', e => {
  const l = /** @type {HTMLElement} */ (e.target).closest?.('a[data-pview],button[data-pview]');
  if (!l || e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  let o; try { o = JSON.parse(l.dataset.pview); } catch { return; }
  e.preventDefault(); e.stopPropagation();
  pdfView(o);
}, true);
// 2.65.0 (#1823) Documents (docs.js, module docs): the module switch and the share sheet's question stay at start (moved here)
// its module switch (Settings > Modules), off by default like the other areas
FEATS.push(['docs', N_('Documents')]);
FEAT_DESC.docs = N_('Scanned letters, invoices and contracts: text recognition, full-text search, sorting by rules and by what Kalmido learns from your corrections, due dates as tasks');
const dc_shareOk = () => typeof feat === 'function' && feat('docs') && !S.me?.kid;
// 2.65.0 (#1823) Home & life (life.js, module life): the switch and the money format stay at start (moved here); a life list's
// bar, a life task's details and a contact's care line load the module when one is drawn
const LIFE_MODS = ['contracts', 'home', 'care', 'health', 'travel'];  // 2.172.0 B (#2679): reading moved to the area Reading
const lifeOn = () => LIFE_MODS.some(m => feat(m));
// 2.312.0 B (#3264): the notes on health data (Art. 9 GDPR) of the modules health and review (2.306.0 B #2887, moved here
// from settings.js): the module row, the area switch (areas.js mg_modAreaHtml) and the first-run setup (account.js)
const MOD_PRIV = {health: N_('Health data is specially protected. Only you see it, unless you share a list.'),
  review: N_('Journal and mood entries can be health data and are specially protected. Only you see them; the encryption of your private workspace protects them on the server too.')};
const modPrivHtml = ks => ks.filter(k => MOD_PRIV[k]).map(k => `<small class="modpriv">${ic('info', 's')} ${tr(MOD_PRIV[k])}</small>`).join('');
const fmtMoney = n => curMoney(n, S.settings.time_currency ?? '€');  // 2.368.0 C (#2983): one money format (i18n.js curMoney)
window.lifeBar = l => { if (l?.life && !l.archived && (lifeOn() || (l.life === 'reading' && feat('reading')))) ld_later('life'); return ''; };  // 2.172.0 B (#2679): + a read-later project
window.lifeDetailHtml = t => { if (t?.id > 0 && !t.context && ['contract', 'device', 'upkeep', 'health', 'bookmark'].includes(t.fam?.kind)) loadModule('life').then(() => { if (S.sel === t.id) renderDetail(); }, () => {}); return ''; };
window.lifeCareHtml = c => { if (c && feat('care')) ld_later('life'); return ''; };
// 2.65.0 (#1823) the API docs link (Settings > Agents, the agent chat): integrations.js loads on demand (moved here)
const API_DOCS = 'https://github.com/Gegenschuss/kalmido/blob/main/docs/API.md';
// 2.65.0 (#1823) playbooks (playbook.js, module playbook): the list / folder dialogs ask these at start (moved here); the
// area loads the module when it mounts
// the area: with agents (a folder too), and in a list with a playbook also for members who do not see its agent (they read
// it); the menu entry: with a playbook, or for those who may write one
const pbOn = l => agentsOn() || (collab() && !!l?.playbook);
function pbMenuItem(l) {
  if (!l || !pbOn(l) || l.is_inbox || l.archived) return null;
  if (l.playbook) return {label: tr('Playbook'), icon: 'book', cls: 'mplaybook', fn: () => pbOpen(l.id)};
  return canManage(l) && listAgents(l).length ? {label: tr('Playbook…'), icon: 'book', cls: 'mplaybook', rare: 1, fn: () => pbOpen(l.id)} : null;
}
function pbAreaHtml(kind) {
  return `<h4 id="pb-h-${kind}">${tr('Playbook')}</h4><div class="pbarea" id="pb-area" aria-labelledby="pb-h-${kind}"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
// 2.65.0 (#1823) the timeline and the roadmap (timeline.js, roadmap.js, module timeline): what the lists, the sidebar and the
// drag ask at start (moved here)
const rmEsc = v => String(v).replace(/["\\]/g, '\\$&');  // inside a quoted attribute selector
function rmP() {
  const src = S.rmLocal ?? S.settings.roadmap ?? '';
  if (!S.rmPc || S.rmPc.src !== src) {
    let v = {}; try { v = JSON.parse(src || '{}'); } catch { v = {}; }
    S.rmPc = {src, v: v && typeof v === 'object' && !Array.isArray(v) ? v : {}};
  }
  return S.rmPc.v;
}
const isRoadmap = () => S.route.mod === 'tasks' && S.route.key === 'all' && feat('timeline') && rmP().v === 'timeline';
function tlReaches(from, target) {  // does `from` (transitively) wait on `target`? (open blockers I can see)
  const seen = new Set(), todo = [from];
  while (todo.length) { const x = todo.pop(); if (x === target) return true; if (seen.has(x) || seen.size > 5000) continue; seen.add(x); todo.push(...(S.tasks.get(x)?.blockers || [])); }
  return false;
}
// 2.149.0 F (#2518) environments (envs.js, module envs): the project page's block and a milestone's panel load the module
// (the module's own first draw is the same "Loading…" / nothing; it fetches and draws again)
window.env_ovHtml = (l, can, hasMs = true) => { ld_later('envs'); return hasMs ? `<div class="muted envbox">${esc(tr('Loading…'))}</div>` : ''; };
window.env_msHtml = t => { if (t?.id > 0) loadModule('envs').then(() => { if (S.sel === t.id) renderDetail(); }, () => {}); return ''; };
// 2.149.0 F (#2518): a list's "Export as CSV" (from listprint.js, now loaded on demand): the download starts inside the click
function lexCsv(lid) {
  const l = listById(lid); if (!l) return;
  const a = document.createElement('a');
  a.href = `/api/lists/${lid}/export.csv?done=${LS.get('lexDone', true) ? 1 : 0}`;
  a.download = ''; a.hidden = true;
  document.body.appendChild(a); a.click(); a.remove();
  toast(tr('The CSV counts comments and attachments but does not contain them. For everything, use the account export.'), null, 9000);  // 2.273.0 D (#3051), 2.363.3 (#3134)
}
const pv_attr = o => ` data-pview="${esc(JSON.stringify(o))}"`;
// 2.92.0 C (#1926): a Word / Excel file opens in the document preview (docpreview.js, module pdf) like a PDF:
// <a href="…" data-dview='{"url": preview route, "name", "size", "dlUrl", "aid"?}'>; a modifier key keeps the download
const dv_is = a => !!a && !a.enc && (/\.(docx|xlsx|odt|ods)$/i.test(String(a.name || '')) || /officedocument\.(wordprocessingml\.document|spreadsheetml\.sheet)$|opendocument\.(text|spreadsheet)$/.test(a.mime || ''));  // 2.635.0 (#4807): + odt / ods
const dv_attr = o => ` data-dview="${esc(JSON.stringify(o))}"`;
document.addEventListener('click', e => {
  const l = /** @type {HTMLElement} */ (e.target).closest?.('a[data-dview],button[data-dview]');
  if (!l || e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  let o; try { o = JSON.parse(l.dataset.dview); } catch { return; }
  e.preventDefault(); e.stopPropagation();
  dpvOpen(o);
}, true);
// 2.65.0 (#1823): one per idle moment, the areas this person has switched on (not all modules: no office, contacts,
// statistics, PDF, playbooks), so their first click stays quick without slowing the start
// 2.660.0 (#4197): no longer the settings first (with their dependencies about a third of all modules, on every start): they load
// on their first opening like the other dialogs
/** @type {[string, () => boolean][]} */
const LD_IDLE = [['calendar', () => feat('cal')], ['timeline', () => feat('timeline')], ['wiki', () => feat('wiki')],
  ['docs', () => feat('docs')], ['life', () => lifeOn() || feat('budget')]];  // 2.149.0 F (#2518): + the budget
function ld_idle(i) {
  const m = LD_IDLE[i]; if (!m) return;  // 2.191.0 F2 (#2518): the texts of every module load on their own (i18n.js i18nWarm)
  (window.requestIdleCallback || (f => setTimeout(f, 0)))(() => {
    if (!S.me || document.hidden) return;
    if (netLite()) return;  // data saver / a slow mobile connection: nothing in the background, the areas load on their first click
    (m[1]() ? loadModule(m[0]) : Promise.resolve()).catch(() => {}).then(() => ld_idle(i + 1));
  });
}
setTimeout(() => ld_idle(0), 5000);
