// 1.1 UI tests (jsdom): onboarding list + welcome tour (flow, finish, restart), command palette (Ctrl/Cmd+K),
// shortcuts overlay (?), list keyboard navigation, density setting, completion celebration (Today emptied,
// list completed, project status complete, reduced motion, setting off, quips).
// Starts its own container with KALMIDO_ONBOARDING=1 (start.sh).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, k, o = {}, target) => (target || w).dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const DATA = process.argv[2] || path.join(__dirname, '.data');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
async function api(cookie, method, url, body) {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cookie}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  // ---- first start: sample list + tour
  let w = await boot({user: 'alice', wait: 3500}), d = w.document;
  const ck = w.__cookie;
  const gs = () => w.eval('S.lists').find(l => l.name === 'Getting started');
  check(gs(), 'first start: "Getting started" list created');
  check(d.querySelector('#view .trow') && /Tick me off/.test(d.querySelector('#view').textContent), 'Today shows the sample tasks');
  check(d.querySelector('#view .trow.pr5') && d.querySelector('#view .trow .chk'), 'row: priority bar class + square checkbox');
  check(d.querySelector('#view .trow.hascols .tcols .c-date') && d.querySelector('#view .trow .meta .dt.m-col'), 'desktop: date column + mobile meta copy');
  check(/\d/.test(d.querySelector('#top h1 .hn')?.textContent || ''), 'title: open count (mono)');
  const tour = () => d.querySelector('.tour');
  check(tour() && tour().dataset.step === 'side' && /Smart lists/.test(d.querySelector('.tcard').textContent), 'tour: step 1 smart lists');
  check(/1\/6/.test(d.querySelector('.tstep').textContent), 'tour: 6 steps on desktop with collaboration');
  click(w, d.querySelector('[data-tour="next"]')); await sleep(50);
  check(tour().dataset.step === 'add', 'tour: next -> quick add');
  key(w, 'ArrowRight'); await sleep(50);
  check(tour().dataset.step === 'detail', 'tour: arrow key -> details');
  click(w, d.querySelector('[data-tour="back"]')); await sleep(50);
  check(tour().dataset.step === 'add', 'tour: back');
  for (const want of ['detail', 'keys', 'settings', 'news']) { click(w, d.querySelector('[data-tour="next"]')); await sleep(40); check(tour()?.dataset.step === want, 'tour step ' + want); }
  check(/Done/.test(d.querySelector('[data-tour="next"]').textContent), 'tour: last step says Done');
  click(w, d.querySelector('[data-tour="next"]')); await sleep(600);
  check(!tour(), 'tour: closed after the last step');
  let st = await api(ck, 'GET', '/api/state');
  check(st.settings.tour === 'done', 'tour: stored as done');
  w.close();
  w = await boot({user: 'alice'}); d = w.document;
  check(!d.querySelector('.tour'), 'second start: no tour');
  check(w.eval('S.lists').filter(l => l.name === 'Getting started').length === 1, 'second start: no second sample list');
  // restart from Settings > Help, Escape skips
  w.eval(`settingsModal('help')`); await sleep(200);
  click(w, d.querySelector('.smodal [data-m="tour"]')); await sleep(200);
  check(d.querySelector('.tour') && !d.querySelector('.smodal'), 'restart from Settings > Help');
  key(w, 'Escape'); await sleep(200);
  check(!d.querySelector('.tour'), 'Escape skips the tour');

  // ---- command palette
  key(w, 'k', {ctrlKey: true}); await sleep(80);
  let pal = d.querySelector('.palette');
  check(pal && pal.querySelector('.pqin') && pal.querySelectorAll('.pitem').length > 5, 'Ctrl+K opens the palette with items');
  check(pal && /Actions|Recent/.test(pal.textContent) && pal.querySelector('.pitem kbd'), 'palette: groups + shortcut hints');
  const type = (txt) => { const i = d.querySelector('.palette .pqin'); i.value = txt; i.dispatchEvent(new w.Event('input', {bubbles: true})); };
  type('tick me'); await sleep(30);
  check(/Tick me off/.test(d.querySelector('.palette .pitem.on')?.textContent || ''), 'fuzzy: "tick me" -> Tick me off first');
  type('gtstrd'); await sleep(30);
  check(/Getting started/.test(d.querySelector('.palette .pitem.on')?.textContent || ''), 'fuzzy subsequence: "gtstrd" -> Getting started list');
  key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(300);
  check(!d.querySelector('.palette') && w.eval('S.route.key') === 'l:' + gs().id, 'Enter runs the item (go to the list)');
  check(w.eval('LS.get("palRecent", [])')[0] === 'l:' + gs().id, 'palette: recent item stored');
  key(w, 'k', {metaKey: true}); await sleep(50);
  type('tick me'); await sleep(20);
  key(w, 'ArrowDown', {}, d.querySelector('.palette .pqin')); key(w, 'ArrowUp', {}, d.querySelector('.palette .pqin'));
  key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(300);
  const tick = [...w.eval('S.tasks').values()].find(t => t.title === 'Tick me off');
  check(w.eval('S.sel') === tick.id, 'Cmd+K, task item -> detail opens');
  // actions on the selected task: move to another list via the sub mode
  key(w, 'k', {ctrlKey: true}); await sleep(50);
  type('another list'); await sleep(20);
  key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(80);
  check(d.querySelector('.palette .pmode') && /Inbox/.test(d.querySelector('.palette .plist').textContent), 'move mode: lists offered');
  type('inb'); await sleep(20);
  key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(700);
  check(w.eval(`taskById(${tick.id}).list_id`) === w.eval('inbox().id'), 'move mode: task moved to the inbox');
  // no match + Enter = new task (quick add syntax)
  key(w, 'k', {ctrlKey: true}); await sleep(50);
  type('Water plants zz tomorrow'); await sleep(20);
  check(/Nothing found/.test(d.querySelector('.palette .plist').textContent), 'no match: hint');
  key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(700);
  const nt = [...w.eval('S.tasks').values()].find(t => t.title === 'Water plants zz');
  check(nt && nt.due, 'no match + Enter: new task with a parsed date');
  key(w, 'k', {ctrlKey: true}); await sleep(50);
  key(w, 'Escape', {}, d.querySelector('.palette .pqin')); await sleep(50);
  check(!d.querySelector('.palette'), 'Escape closes the palette');
  w.eval('closeDetail()');

  // ---- shortcuts overlay, list navigation, go-to sequences
  key(w, '?', {}, d.body); await sleep(80);
  const km = d.querySelector('.kbmodal');
  const kh = km ? [...km.querySelectorAll('section h4')].map(h => h.textContent) : [];  // 2.0.6 (#191): + Multi-select, Calendar
  check(km && kh.includes('Multi-select') && kh.includes('Calendar') && kh.length >= 6 && km.querySelectorAll('kbd').length >= 15, '? opens the shortcuts overlay: ' + kh);
  key(w, 'Escape', {}, d.body); await sleep(50);
  check(!d.querySelector('.kbmodal'), 'Escape closes the overlay');
  w.eval(`go('today')`); await sleep(300);
  key(w, 'j', {}, d.body); await sleep(30);
  const first = d.querySelector('#view .trow.kfocus');
  check(first && first === d.querySelector('#view .trow'), 'j focuses the first task');
  key(w, 'j', {}, d.body); await sleep(30);
  check(d.querySelector('#view .trow.kfocus') !== first, 'j moves down');
  key(w, 'k', {}, d.body); await sleep(30);
  check(d.querySelector('#view .trow.kfocus') === first, 'k moves up');
  const fid = +first.dataset.id;
  key(w, 'x', {}, d.body); await sleep(800);
  check(w.eval(`taskById(${fid})?.status`) === 2, 'x completes the focused task');
  key(w, 'g', {}, d.body); key(w, 'i', {}, d.body); await sleep(200);
  check(w.eval('S.route.key') === 'inbox', 'g i -> Inbox');
  key(w, 'g', {}, d.body); key(w, 't', {}, d.body); await sleep(200);
  check(w.eval('S.route.key') === 'today', 'g t -> Today');
  key(w, 'n', {}, d.body); await sleep(50);
  check(d.activeElement?.id === 'qinput', 'n still focuses quick add');
  d.activeElement.blur();

  // ---- density
  check(d.documentElement.dataset.density === 'compact', 'desktop default density: compact');
  w.eval(`settingsModal('general')`); await sleep(150);
  check(d.querySelector('.smodal [data-pane="look"] #s-density') && d.querySelector('.smodal [data-pane="general"] #s-celebrate')?.checked, 'Appearance: density, General: celebrate (on)');
  click(w, d.querySelector('.smodal [data-look="density"][data-v="comfortable"]')); await sleep(30);
  check(d.documentElement.dataset.density === 'comfortable' && w.eval('LS.get("density")') === 'comfortable', 'density -> comfortable (per device)');
  d.querySelector('.smodal').remove();
  w.close();
  const wm = await boot({user: 'alice', mobile: true});
  check(wm.document.documentElement.dataset.density === 'comfortable', 'phone default density: comfortable');
  wm.close();

  // ---- celebration: Today emptied
  w = await boot({user: 'alice'}); d = w.document;
  st = await api(ck, 'GET', '/api/state');
  const t0 = st.tasks.filter(t => t.status === 0 && t.due && t.due <= w.eval('today()') && !t.parent_id);
  for (const t of t0.slice(1)) await api(ck, 'POST', `/api/tasks/${t.id}/complete`);
  await w.eval('load()'); w.eval('render()'); await sleep(100);
  check(w.eval('counts().today') === 1, 'one task left for today');
  const quips = await (await fetch(B + 'static/sloth-quips.json')).json();
  await w.eval('quipsLoad()');
  await w.eval(`toggleTask(${t0[0].id})`); await sleep(100);
  let ce = d.querySelector('.cele');
  check(ce && ce.dataset.kind === 'today' && ce.querySelector('.csloth') && ce.querySelectorAll('.cconf').length > 10, 'Today emptied: sloth + checkmark confetti');
  const q1 = d.querySelector('.cele-quip span')?.textContent;
  check(quips.en.includes(q1), 'quip from sloth-quips.json (en): ' + q1);
  // list completed (not Today): a list with one open task
  const L = await api(ck, 'POST', '/api/lists', {name: 'Errands', kind: 'project'});
  const T = await api(ck, 'POST', '/api/tasks', {title: 'Post office', list_id: L.id});
  await w.eval('load()'); w.eval('render()');
  await w.eval(`toggleTask(${T.id})`); await sleep(100);
  ce = d.querySelector('.cele');
  check(ce && ce.dataset.kind === 'list' && /Errands/.test(d.querySelector('.cele-quip b').textContent), 'list completed: celebration names the list');
  check(d.querySelector('.cele-quip span')?.textContent !== q1, 'no immediate repeat of the quip');
  // not the last one: nothing
  const T2 = await api(ck, 'POST', '/api/tasks', {title: 'Bank', list_id: L.id}), T3 = await api(ck, 'POST', '/api/tasks', {title: 'Pharmacy', list_id: L.id});
  d.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove());
  await w.eval('load()'); w.eval('render()');
  await w.eval(`toggleTask(${T2.id})`); await sleep(100);
  check(!d.querySelector('.cele'), 'not the last open task: no celebration');
  // project status complete
  w.eval(`statusModal(${L.id})`); await sleep(200);
  click(w, d.querySelector('.stmodal [data-st="complete"]'));
  click(w, d.querySelector('.stmodal [data-m="save"]')); await sleep(900);
  ce = d.querySelector('.cele');
  check(ce && ce.dataset.kind === 'project', 'project status complete: celebration');
  // still frame (screenshots): progress 0.5 puts the arm vertical
  d.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove());
  w.eval(`celebrate('today', {frame: 0.5, force: true})`);
  check(Math.abs(parseFloat((d.querySelector('.cele .carm').style.transform.match(/rotate\(([-\d.]+)deg/) || [])[1])) < 0.5, 'frame 0.5: vine straight down');
  // multi-select batch completing the rest of a list
  d.querySelectorAll('.cele,.cele-quip').forEach(x => x.remove());
  w.eval(`S.multi = new Set([${T3.id}])`); await w.eval(`batch('complete', {}, true)`); await sleep(100);
  check(d.querySelector('.cele')?.dataset.kind === 'list', 'batch complete of the last task: celebration');
  w.close();
  // reduced motion: calm variant (small sloth + line, no swing, no confetti)
  w = await boot({user: 'alice', media: {'(prefers-reduced-motion: reduce)': true}}); d = w.document;
  const T4 = await api(ck, 'POST', '/api/tasks', {title: 'Only one', list_id: L.id});
  await w.eval('load()'); w.eval('render()'); await w.eval('quipsLoad()');
  await w.eval(`toggleTask(${T4.id})`); await sleep(100);
  check(!d.querySelector('.cele') && d.querySelector('.cele-quip.calm .csloth'), 'reduced motion: calm variant only');
  w.close();
  // setting off: nothing; German quips
  await api(ck, 'PATCH', '/api/settings', {celebrate: '0', lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  const T5 = await api(ck, 'POST', '/api/tasks', {title: 'Only two', list_id: L.id});
  await w.eval('load()'); w.eval('render()');
  await w.eval(`toggleTask(${T5.id})`); await sleep(100);
  check(!d.querySelector('.cele') && !d.querySelector('.cele-quip'), 'setting off: no celebration');
  await w.eval('quipsLoad()');
  const qs = [...Array(30)].map(() => w.eval('nextQuip()'));
  check(qs.every(q => quips.de.includes(q)) && qs.every((q, i) => !i || q !== qs[i - 1]), 'German quips, never the same twice in a row');
  check(/Tastenkürzel/.test(w.eval(`(() => { shortcutsModal(); return document.querySelector('.kbmodal').textContent; })()`)), 'German shortcuts overlay');
  await api(ck, 'PATCH', '/api/settings', {celebrate: '1', lang: 'en'});
  w.close();
  check(!errs.length, 'no js errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed, js errors: ${errs.length}`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
