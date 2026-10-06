// 2.22.0 UI tests: package "Home & life" (#663 / #662) and the ride-alongs #678 #679 #680 #681 #682 #683 #685 #686 #688,
// own container (start.sh, isolated test database).
// jsdom: switched off nothing shows; on: the sidebar rows, the view "Home & life" (contracts with the sums, devices +
// upkeep, staying in touch, health, trips, read later), the dialogs (contract new + edit + "Cancelled", device, upkeep with a
// suggestion, health medication with two times, trip -> its list with the trip bar), the task panel's section, staying in
// touch on a contact's card, the review (day / week, the journal saves itself, the mood), Karakeep's dialog; the
// ride-alongs: the quick add @ picker + a pasted image (#678), "Show the inbox in Today" (#681), the auto emoji of a new list
// (#682), the "Waiting on…" picker grouped by list (#685), "Waiting on external" as a button, in the row's right-click menu,
// the palette and as wartet:Kunde in quick add (#686), the flying heron (#688).
// Firefox: a phone (390 touch), the Fold unfolded upright (690 x 829, touch), a desktop (1440, mouse): nothing sideways,
// 44 px targets on touch, axe (WCAG 2.2 A + AA) over the view, the review and the contract dialog; the sidebar folders as a
// tree (#680), one focus ring while a title is edited in the list (#683), the settings dialog on a computer (#679), the
// heron mid-flight. Screenshots with P2220_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2220_ui', check, shots: 'P2220_SHOTS'});
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const LIFE = 'contracts,home,care,health,review,travel,reading';
const BASE = 'cal,comments,collab,deps,progress,contacts,events';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;

  // ================= jsdom: off = no trace
  let w = await boot({user: 'alice', hash: 'life'}), d = w.document;
  await sleep(300);
  check(w.eval('S.route.mod') === 'tasks' && !d.querySelector('#side [data-go="life"]') && !d.querySelector('#side [data-go="review"]'), 'off: #life goes to the tasks, no sidebar rows');
  w.eval(`settingsModal('modules')`); await sleep(400);
  const sw = LIFE.split(',').map(k => d.querySelector(`.smodal [data-feat="${k}"]`));
  check(sw.every(x => x && !x.checked), 'Settings > Modules: seven switches under "At home", all off');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove()); w.close();
  await call('PATCH', '/api/settings', {features: BASE + ',' + LIFE});

  // ================= the view
  w = await boot({user: 'alice', hash: 'life'}); d = w.document;
  await until(() => d.querySelector('#view .life .lc-contracts'));
  check(d.querySelector('#side [data-go="life"]') && d.querySelector('#side [data-go="review"]'), 'on: the sidebar rows "Home & life" and "Review & journal"');
  check(['contracts', 'home', 'care', 'health', 'travel', 'reading'].every(k => d.querySelector(`#view .lc-${k}`)), 'the view: a card per module');
  // contract dialog
  click(w, d.querySelector('#view [data-act="life-contract"]')); await sleep(200);
  let md = d.querySelector('.modal.lifedlg');
  check(md && md.querySelector('#lf-name') && md.querySelector('#lf-ends') && md.querySelector('.lhint.keep'), 'the contract dialog (hint stays visible)');
  click(w, md.querySelector('[data-m="save"]')); await sleep(200);
  check(/name/i.test(md.querySelector('.aerr').textContent), 'no name: an error in the dialog');
  input(w, md.querySelector('#lf-name'), 'Mobile phone'); md.querySelector('#lf-prov').value = 'Telco'; md.querySelector('#lf-cost').value = '19,99';
  md.querySelector('#lf-ends').value = day(120); md.querySelector('#lf-notice').value = '1'; md.querySelector('#lf-nu').value = 'm'; md.querySelector('#lf-renew').value = '12';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => !md.isConnected);
  let st = await call('GET', '/api/state');
  const C = st.tasks.find(t => t.fam?.kind === 'contract');
  check(C && C.fam.cost === 19.99 && C.repeat === 'FREQ=YEARLY' && C.title === 'Cancel or renew the contract: Mobile phone', 'saved: a contract task ' + JSON.stringify(C?.fam));
  await until(() => d.querySelector('#view .lc-contracts .lsum'));
  check(/19[.,]99/.test(d.querySelector('#view .lc-contracts .lsum').textContent) && /Mobile phone/.test(d.querySelector('#view .lc-contracts').textContent), 'the card: the sum per month and the contract');
  // the task panel: the contract section, edit
  w.eval(`openDetail(${C.id})`); await sleep(400);
  check(d.querySelector('#detail .lifesec') && /Telco/.test(d.querySelector('#detail .lifesec').textContent), 'the task panel: the contract section');
  click(w, d.querySelector('#detail [data-act="life-cedit"]')); await sleep(200);
  md = d.querySelector('.modal.lifedlg');
  check(md && md.querySelector('#lf-name').value === 'Mobile phone' && md.querySelector('#lf-ends').value === day(120), 'edit: the dialog filled (the end = due + notice)');
  md.querySelector('#lf-cost').value = '24,50';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${C.id}`)).fam?.cost === 24.5), 'edit: the cost saved');
  w.eval('closeDetail()');
  // device, upkeep (a suggestion), health (medication), trip
  w.eval('deviceModal()'); await sleep(150); md = d.querySelector('.modal.lifedlg');
  input(w, md.querySelector('#lf-name'), 'Washing machine'); click(w, md.querySelector('[data-m="save"]'));
  await until(() => !md.isConnected);
  await w.eval('upkeepModal()'); await sleep(300); md = d.querySelector('.modal.lifedlg');
  const pre = md.querySelector('.lpre [data-pre="smoke"]');
  click(w, pre);
  check(md.querySelector('#lf-title').value === 'Test the smoke detectors' && md.querySelector('#lf-every').value === '12' && pre.getAttribute('aria-pressed') === 'true', 'upkeep: a suggestion fills the dialog');
  click(w, md.querySelector('[data-m="save"]')); await until(() => !md.isConnected);
  w.eval('healthModal()'); await sleep(150); md = d.querySelector('.modal.lifedlg');
  click(w, md.querySelector('[data-ht="medication"]'));
  check(!md.querySelector('.lh-times').hidden && md.querySelector('.lh-time').hidden, 'health: medication shows the times');
  input(w, md.querySelector('#lf-title'), 'Vitamin D'); md.querySelector('#lf-times').value = '8:00, 20:00';
  click(w, md.querySelector('[data-m="save"]')); await until(() => !md.isConnected);
  st = await call('GET', '/api/state');
  check(st.tasks.filter(t => t.fam?.kind === 'health').map(t => t.due_time).sort().join() === '08:00,20:00', 'health: two daily tasks (8:00 normalized)');
  check(st.lists.some(l => l.life === 'health'), '… in a health list');
  w.eval('tripModal()'); await sleep(150); md = d.querySelector('.modal.lifedlg');
  input(w, md.querySelector('#lf-name'), 'Summer in Italy'); md.querySelector('#lf-where').value = 'Rome';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => w.eval('S.route.key').startsWith('l:'));
  await until(() => d.querySelector('#view .lifebar'));
  check(/Rome/.test(d.querySelector('#view .lifebar')?.textContent || '') && d.querySelector('#view [data-act="life-tripedit"]'), 'trip: its list opens with the trip bar');
  // Karakeep dialog
  w.location.hash = '#life'; await until(() => d.querySelector('#view .lc-reading'));
  await w.eval('kkModal()'); await sleep(300); md = d.querySelector('.modal.lifedlg');
  check(md && md.querySelector('#kk-url') && md.querySelector('#kk-tok').type === 'password', 'Karakeep: address + API key (password field)');
  md.remove();
  // health list bar
  const HL = st.lists.find(l => l.life === 'health').id;
  w.location.hash = '#l/' + HL; await until(() => d.querySelector('#view .lifebar'));
  check(/never visible to agents/.test(d.querySelector('#view .lifebar').textContent), 'the health list says it is private');
  w.close();

  // ================= staying in touch on a contact's card
  const ct = await call('POST', '/api/contacts', {fn: 'Erika Mustermann'});
  w = await boot({user: 'alice', hash: 'contacts/' + ct.id}); d = w.document;
  await until(() => d.querySelector('.ctcare'));
  check(d.querySelector('#ct-care')?.value === '0', 'the card: "Stay in touch" off');
  change(w, d.querySelector('#ct-care'), '30');
  check(await until(async () => (await call('GET', `/api/contacts/${ct.id}`)).care?.every_days === 30), 'how often: saved');
  click(w, d.querySelector('.ctcare [data-act="life-touch"]'));
  check(await until(async () => (await call('GET', `/api/contacts/${ct.id}`)).care?.last === day(0)), '"In touch today" saved');
  w.close();

  // ================= the review + journal
  const t1 = await call('POST', '/api/tasks', {title: 'Done today'}); await call('POST', `/api/tasks/${t1.id}/complete`);
  w = await boot({user: 'alice', hash: 'review'}); d = w.document;
  await until(() => d.querySelector('#view .review .rv-done'));
  check(/Done today/.test(d.querySelector('#view .rv-done').textContent) && d.querySelector('#rv-text'), 'the day: done + the journal');
  input(w, d.querySelector('#rv-text'), 'A calm day.');
  check(await until(async () => (await call('GET', '/api/life/review')).journal?.[0]?.text === 'A calm day.', 60), 'the journal saves itself');
  click(w, d.querySelector('[data-act="rv-mood"][data-v="4"]'));
  check(await until(async () => (await call('GET', '/api/life/review')).journal?.[0]?.mood === 4, 40), 'the mood');
  click(w, d.querySelector('[data-act="rv-period"][data-p="week"]'));
  await until(() => d.querySelector('#view .rvjdays'));
  check(d.querySelectorAll('#view .rvjdays button').length === 7 && d.querySelector('#view .rvjdays button.has'), 'the week: seven days, the day with an entry marked');
  w.close();

  // ================= #682: the emoji of a new list
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval('listModal()'); await sleep(200);
  md = [...d.querySelectorAll('.modal')].pop();
  input(w, md.querySelector('#l-name'), 'Einkaufsliste');
  check(md.querySelector('#l-emo').textContent.includes('🛒') && md.querySelector('#l-emo').classList.contains('sugg'), '#682: "Einkaufsliste" -> 🛒 suggested');
  input(w, md.querySelector('#l-name'), 'Kalmido');
  check(!/\p{Extended_Pictographic}/u.test(md.querySelector('#l-emo').textContent), '#682: nothing fitting -> no emoji');
  input(w, md.querySelector('#l-name'), 'Urlaub Italien');
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await call('GET', '/api/state')).lists.some(l => l.name === '🏖️Urlaub Italien')), '#682: saved with the emoji');
  w.eval('listModal()'); await sleep(200);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('#l-emogrid [data-emo=""]'));
  input(w, md.querySelector('#l-name'), 'Arbeit');
  check(!md.querySelector('#l-emo').textContent.includes('💼'), '#682: once chosen by hand (no icon), no suggestion any more');
  md.remove(); w.close();

  // ================= #681: the inbox in Today
  const ib = (await call('GET', '/api/state')).lists.find(l => l.is_inbox).id;
  const i1 = await call('POST', '/api/tasks', {title: 'Unsorted idea', list_id: ib});
  await call('POST', '/api/tasks', {title: 'Due today thing', due: day(0)});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await sleep(300);
  const n0 = w.eval('counts().today');
  check(!d.querySelector('#view .tinbox'), '#681: off by default: no inbox in Today');
  await call('PATCH', '/api/settings', {today_inbox: '1'}); await w.eval('load()'); w.eval('render()'); await sleep(200);
  check(d.querySelector('#view .tinbox') && /Unsorted idea/.test(d.querySelector('#view .tinbox').textContent) && w.eval('counts().today') === n0 + 1, '#681: on: its own section, counted in Today');
  click(w, d.querySelector(`#view .tinbox [data-act="tin-due"][data-d="1"][data-id="${i1.id}"]`));
  check(await until(async () => (await call('GET', `/api/tasks/${i1.id}`)).due === day(1)), '#681: "Tomorrow" sorts it');
  await call('PATCH', '/api/settings', {today_inbox: '0'});
  w.close();

  // ================= #685 the picker, #686 waiting on external
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id, P2 = (await call('POST', '/api/lists', {name: 'Shop', kind: 'project'})).id;
  const a1 = await call('POST', '/api/tasks', {title: 'Design', list_id: P}), a2 = await call('POST', '/api/tasks', {title: 'A very long title that goes on and on so that it needs two lines in the picker row', list_id: P});
  await call('POST', '/api/tasks', {title: 'Checkout', list_id: P2});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await sleep(300);
  w.eval(`openDetail(${a1.id})`); await sleep(500);
  check(d.querySelector('#detail .depsec [data-act="wait-on"]'), '#686 / 2.25.0 (UX-43): ONE button "Waiting on…" in the dependencies');
  w.eval(`depPicker(${a1.id}, 'by')`); await sleep(200);
  const grp = [...d.querySelectorAll('.dpmodal .tpkg')];
  check(grp.length === 2 && /This list/.test(grp[0].querySelector('.tpkh').textContent) && /Shop/.test(grp[1].querySelector('.tpkh').textContent)
    && grp[0].querySelector('.tpkrow .tpkt') && grp[0].querySelector('.tpkrow .tpkm'), '#685: grouped (this list first, then the others under their name), title + list in their own lines');
  d.querySelector('.dpmodal').remove();
  click(w, d.querySelector('#detail [data-act="wait-on"]')); await sleep(150);
  [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Someone outside/.test(b.textContent)).click(); await sleep(200);
  md = d.querySelector('.waitmodal');
  md.querySelector('#w-note').value = 'Client approval'; click(w, md.querySelector('[data-m="ok"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${a1.id}`)).wait_note === 'Client approval'), '#686: "Waiting on…" > "Someone outside…" sets it');
  w.eval('closeDetail()'); await sleep(200);
  // the row's right-click menu
  const row = d.querySelector(`#view .trow[data-id="${a2.id}"]`);
  row.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await sleep(200);
  check(/Waiting on someone…/.test(d.querySelector('#pop')?.textContent || ''), '#686: right-click on a row: the task menu with "Waiting on someone…"');
  w.eval('closePop()');
  // quick add wartet:Kunde
  const qi = d.querySelector('#qinput');
  input(w, qi, 'Send the offer wartet:Kunde');
  check(/Kunde/.test(d.querySelector('#qdchips, .qadd .chips')?.textContent || '') || /⏳/.test(d.body.textContent), '#686: the chip ⏳ Kunde');
  key(w, qi, 'Enter');
  check(await until(async () => (await call('GET', '/api/state')).tasks.some(t => t.title === 'Send the offer' && t.wait_note === 'Kunde')), '#686: wartet:Kunde = waiting on external "Kunde"');
  // the palette offers it for the current task
  w.eval(`openDetail(${a2.id})`); await sleep(300);
  check(w.eval(`palAll().some(x => x.id === 'a:wait' && /waiting on someone/i.test(x.label))`), '#686: the palette offers "waiting on external" for the open task');
  w.close();

  // ================= #678 the quick add @ picker and a pasted image
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await sleep(300);
  const q2 = d.querySelector('#qinput');
  q2.focus(); input(w, q2, 'Ask @B'); q2.setSelectionRange(6, 6); input(w, q2, 'Ask @B');
  let pk = d.querySelector('.qadd .qmpick:not(.hidden)');
  check(pk && /Bob/.test(pk.textContent) && q2.getAttribute('aria-activedescendant'), '#678: @ shows the people of the list');
  key(w, q2, 'Enter');
  check(q2.value === 'Ask @Bob ' && !d.querySelector('.qadd .qmpick:not(.hidden)'), '#678: Enter picks the person (no task yet) ' + JSON.stringify(q2.value));
  input(w, q2, 'Ask @Bob about the logo');
  const file = new w.File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], 'image.png', {type: 'image/png'});
  const pe = new w.Event('paste', {bubbles: true, cancelable: true});
  Object.defineProperty(pe, 'clipboardData', {value: {files: [file]}});
  q2.focus(); q2.dispatchEvent(pe);
  check(d.querySelector('.qadd .qfiles .qfile') && pe.defaultPrevented, '#678: a pasted image shows as a file chip');
  key(w, q2, 'Enter');
  const tk = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.title === 'Ask @Bob about the logo'), 60);
  check(tk && await until(async () => ((await call('GET', `/api/tasks/${tk.id}`)).attachments || []).length === 1, 60), '#678: the task is created with the image attached');
  w.close();

  // ================= #693 "Bob is writing …" in the comments
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await sleep(300);
  w.eval(`openDetail(${a2.id})`); await sleep(500);
  const CB = await login('bob');
  await fetch(B + `api/tasks/${a2.id}/typing`, {method: 'POST', headers: {...H, Cookie: CB}});
  check(await until(() => /Bob is writing/.test(d.querySelector('#d-typing')?.textContent || ''), 60), '#693: "Bob is writing …" in the task panel with the next sync');
  const sent = [];
  const f0 = w.fetch; w.fetch = (u, o) => { if (/\/typing$/.test(String(u))) sent.push(String(u)); return f0(u, o); };
  const ci = d.querySelector('#c-input'); input(w, ci, 'Hi'); input(w, ci, 'Hi Bob');
  check(sent.length === 1 && sent[0].includes(`/api/tasks/${a2.id}/typing`), '#693: typing a comment sends one signal ' + JSON.stringify(sent));
  w.close();

  // ================= #697 the page "Set up your account"
  const inv = await call('POST', '/api/users', {username: 'newbie', display_name: 'Newbie', invite: true});
  const itok = inv.invitation.link.split('#invite/')[1];
  w = await boot({user: 'alice', hash: 'invite/' + itok}); d = w.document;
  await until(() => d.querySelector('.authscreen #inv-form'));
  check(/Welcome, Newbie/.test(d.querySelector('.authscreen').textContent) && d.querySelector('#inv-user').value === 'newbie' && !w.location.hash.includes(itok), '#697: the page greets the person, the token left the address bar');
  d.querySelector('#inv-pw').value = 'newbie-pass-1'; d.querySelector('#inv-pw2').value = 'other';
  d.querySelector('#inv-form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await sleep(200);
  check(/not the same/.test(d.querySelector('#inv-err').textContent), '#697: the two passwords must match');
  w.close();
  check((await call('GET', '/api/users')).users.find(u => u.username === 'newbie')?.invite === 'invited', '#697: still invited');

  // ================= #688 the heron flies
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`celebrate('today', {frame: 0.5, force: true})`);
  check(d.querySelector('.cele .cbird .cfly .cwing') && !d.querySelector('.cele .cvine'), '#688: a flying heron with a wing, no vine');
  const xs = [0.1, 0.5, 0.9].map(p => { d.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove()); w.eval(`celebrate('today', {frame: ${p}, force: true})`); return parseFloat(d.querySelector('.cele .cbird').style.transform.match(/translate\(([-\d.]+)px/)[1]); });
  check(xs[0] < xs[1] && xs[1] < xs[2], '#688: it flies from left to right ' + xs.join(' '));
  const conf = [...d.querySelectorAll('.cele .cconf')].filter(c => +c.style.opacity > 0).length;
  check(conf > 0, '#688: checkmark confetti falls behind it');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#top h1', n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const SMALL = sel => `(() => { const coarse = matchMedia('(pointer: coarse)').matches, min = coarse ? 43.5 : 23.5; return [...document.querySelectorAll('${sel}')].filter(b => { const r = b.getBoundingClientRect(), cs = getComputedStyle(b); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !b.closest('[hidden]'); })
    .filter(b => { const r = b.getBoundingClientRect(); return r.width < min || r.height < min; }).map(b => (b.dataset.act || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)).slice(0, 8); })()`;
  const axe = async (ev, where) => {
    if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(document, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => ({id: v.id, n: v.nodes.length, nodes: v.nodes.slice(0, 2).map(x => x.target.join(' ') + ' ' + (x.failureSummary || '').slice(0, 120))})))`);
    check(!r.length, `${where}: no axe violations: ` + r.map(v => `${v.id}(${v.n}) ${v.nodes[0]}`).join(' | ').slice(0, 700));
  };
  const sideways = ev => ev(`document.documentElement.scrollWidth - innerWidth`);
  // a folder with two lists for the sidebar tree (#680)
  await call('POST', '/api/lists', {name: 'Taxes', folder: 'Private'}); await call('POST', '/api/lists', {name: 'Garden', folder: 'Private'});
  for (const [vw, vh, th, touch] of [[390, 844, 'dark', true], [690, 829, 'light', true], [1440, 900, 'light', false]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw}x${vh} ${th}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, 'alice', th) === 200, tag + ': login');
    await o.nav(B + '#life'); await ready(ev, '#view .life .lc-contracts');
    check(await sideways(ev) <= 0, `${tag}: Home & life: nothing sideways`);
    const sm = await ev(SMALL('#view .life button, #view .life a.btn, #view .life a.frow'));
    check(!sm.length, `${tag}: Home & life: targets ` + JSON.stringify(sm));
    if (vw !== 690) await axe(ev, `${tag} Home & life`);
    await shot(`p2220-${vw}-${th}-life.png`);
    await ev(`(() => { contractModal(); return 1; })()`); await sleep(500);
    check(await sideways(ev) <= 0, `${tag}: the contract dialog: nothing sideways`);
    const smd = await ev(SMALL('.lifedlg button, .lifedlg input, .lifedlg select'));
    check(!touch || !smd.length, `${tag}: the contract dialog: 44 px on touch ` + JSON.stringify(smd));
    if (vw === 390) await axe(ev, `${tag} contract dialog`);
    await shot(`p2220-${vw}-${th}-contract.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); location.hash = '#review'; return 1; })()`); await ready(ev, '#view .review .rv-done');
    check(await sideways(ev) <= 0, `${tag}: the review: nothing sideways`);
    if (vw !== 690) await axe(ev, `${tag} review`);
    await shot(`p2220-${vw}-${th}-review.png`);
    if (vw === 390) {  // #692: the sidebar's sort mode on a phone: the buttons in one column on the right
      await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); S.listReorder = true; render(); document.querySelector('#side').classList.add('open'); return 1; })()`); await sleep(600);
      const rc = await ev(`(() => { const rs = [...document.querySelectorAll('#side .srow.reorder')]; const xs = rs.map(r => Math.round(r.querySelector('.rctl').getBoundingClientRect().right));
        return {n: rs.length, xs: [...new Set(xs)], grip: rs.every(r => r.querySelector('.sgrip')), side: document.querySelector('#side').scrollWidth - document.querySelector('#side').clientWidth}; })()`);
      check(rc.n >= 5 && rc.xs.length === 1 && rc.grip && rc.side <= 0, '#692: sort mode: every row has a grip, the buttons end in one column ' + JSON.stringify(rc));
      await shot(`p2220-${vw}-${th}-sortmode.png`);
      await ev(`(() => { S.listReorder = false; render(); return 1; })()`);
    }
    if (vw === 1440) {
      // #680: the sidebar tree: the folder starts where the lists start, its lists one step in
      await ev(`(() => { location.hash = '#inbox'; return 1; })()`); await ready(ev, '#side .fhead');
      const g = await ev(`(() => { const f = [...document.querySelectorAll('#side .fhead')].find(x => /Private/.test(x.textContent)); const top = [...document.querySelectorAll('#side .sg-lists .srow[data-list]')].find(r => !r.closest('.fbody'));
        const kid = [...document.querySelectorAll('#side .fbody .srow[data-list]')].find(r => /Taxes/.test(r.textContent));
        const x = el => el.querySelector('.n').getBoundingClientRect().left; return f && top && kid ? {fold: Math.round(f.getBoundingClientRect().left), top: Math.round(top.getBoundingClientRect().left), kid: Math.round(kid.getBoundingClientRect().left), fn: Math.round(x(f)), kn: Math.round(x(kid)), cnt: f.querySelector('.c')?.textContent} : null; })()`);
      check(g && Math.abs(g.fold - g.top) <= 1 && g.kid > g.fold + 8 && g.kn > g.fn, '#680: the folder row flush with the lists, its lists indented ' + JSON.stringify(g));
      // #683: one focus ring while editing a title in the list
      const T = (await call('POST', '/api/tasks', {title: 'Edit me'})).id;
      await ev(`(() => { location.hash = '#inbox'; return 1; })()`); await ready(ev, `#view .trow[data-id="${T}"]`);
      await ev(`(() => { kfocus(${T}); inlineEditStart(${T}); return 1; })()`); await sleep(300);
      const rings = await ev(`(() => { const a = document.activeElement; if (!a || !a.matches('.ttlin')) return {err: 'no field'};
        const sheets = [...document.styleSheets].filter(x => !x.disabled); let txt = '';
        for (const sh of sheets) { try { txt += [...sh.cssRules].map(r => r.cssText).join('\\n') + '\\n'; } catch { } }
        txt = txt.replace(/:focus-visible/g, '.__fv').replace(/:focus-within/g, '.__fw').replace(/:focus(?![-\\w])/g, '.__fv').replace(/:has\\(\\.ttlin\\.__fv\\)/g, '.__hasf');
        const st = document.createElement('style'); st.textContent = txt; document.head.appendChild(st); sheets.forEach(x => { x.disabled = true; });
        a.classList.add('__fv'); const anc = []; for (let e = a.parentElement; e && e.classList; e = e.parentElement) { e.classList.add('__fw'); anc.push(e); } a.closest('.trow')?.classList.add('__hasf');
        const ring = el => { const s = getComputedStyle(el); return s.outlineStyle !== 'none' || (s.boxShadow && s.boxShadow !== 'none'); };  // headless Firefox reports 0px widths here
        const n = [a, ...anc.slice(0, 4)].filter(ring).map(e => e.className.replace(/__\\w+/g, '').trim().slice(0, 30));
        a.classList.remove('__fv'); anc.forEach(e => e.classList.remove('__fw')); a.closest('.trow')?.classList.remove('__hasf'); sheets.forEach(x => { x.disabled = false; }); st.remove();
        return {n}; })()`);
      check(rings && rings.n && rings.n.length === 1 && /ttlin/.test(rings.n[0]), '#683: editing a title in the list: exactly one ring (the field) ' + JSON.stringify(rings));
      await ev(`(() => { inlineEditCancel(); return 1; })()`);
      // #679: the settings dialog on a computer
      await ev(`(() => { settingsModal('look'); return 1; })()`); await sleep(700);
      const sd = await ev(`(() => { const c = document.querySelector('.smodal .card').getBoundingClientRect(), bg = getComputedStyle(document.querySelector('.smodal')).backgroundColor;
        const a = [...document.querySelectorAll('.smodal a:not(.btn):not(.linkbtn)')].filter(x => x.offsetParent).map(x => getComputedStyle(x).textDecorationLine);
        const ib = document.querySelector('.smodal .lkfs')?.previousElementSibling?.querySelector('.ib') || null;
        return {h: Math.round(c.height), w: Math.round(c.width), bg, under: a.filter(x => x.includes('underline')).length, fsInfo: !!ib, prio: !!document.querySelector('.lookpv .lpv-prio.flag-5 svg'),
          link: getComputedStyle(document.querySelector('.lookpv .lpv-link')).textDecorationLine, dev: getComputedStyle(document.querySelector('.smodal .devtag')).fontFamily}; })()`);
      check(sd.h >= 0.8 * vh && sd.w >= 900, '#679: the dialog is tall and wide (~85 % of the height) ' + JSON.stringify(sd));
      check(+(sd.bg.match(/[\d.]+(?=\))/) || [0])[0] >= 0.5 && !sd.under && sd.link === 'none', '#679: a darker backdrop, links without an underline ' + JSON.stringify(sd));
      check(sd.fsInfo && sd.prio && !/mono/i.test(sd.dev), '#679: (i) at the "Font size" heading, "!high" as a flag, no monospace for words ' + JSON.stringify(sd));
      await shot(`p2220-${vw}-${th}-settings.png`);
      // #696: the child-account options only once "Child account" is ticked
      await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); userModal(null, () => {}); return 1; })()`); await sleep(500);
      const k0 = await ev(`(() => { const c = document.querySelector('#u-kid'), r = document.querySelector('#u-parrow'); return {disp: getComputedStyle(r).display, exp: c.getAttribute('aria-expanded')}; })()`);
      await ev(`(() => { const c = document.querySelector('#u-kid'); c.click(); return 1; })()`); await sleep(300);
      const k1 = await ev(`(() => { const c = document.querySelector('#u-kid'), r = document.querySelector('#u-parrow'); return {disp: getComputedStyle(r).display, exp: c.getAttribute('aria-expanded')}; })()`);
      check(k0.disp === 'none' && k0.exp === 'false' && k1.disp !== 'none' && k1.exp === 'true', '#696: child options hidden until ticked, aria-expanded ' + JSON.stringify([k0, k1]));
      // #688: the heron mid-flight (the suite's Firefox prefers reduced motion: the motion version is forced for the picture)
      await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); window.matchMedia = q => ({matches: false, addEventListener() {}, addListener() {}}); celebrate('today', {frame: 0.5, force: true}); return 1; })()`); await sleep(200);
      const b = await ev(`(() => { const r = document.querySelector('.cele .cbird').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top), w: Math.round(r.width)}; })()`);
      check(Math.abs(b.x - vw / 2) < 120 && b.y > 0 && b.y < vh / 2 && b.w >= 100, '#688: mid-flight the heron is in the upper middle ' + JSON.stringify(b));
      await shot(`p2220-${vw}-${th}-heron.png`);
    }
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
