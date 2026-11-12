// 2.1026.0 C (#5280, Q6c) UI test, own container (start.sh), jsdom: the one search registry (ftsearch.js SEARCH_SOURCES).
// kalmido-suite: fresh
// Per area one object with a word ONLY in its content (an event's description, a contact's note, a note's text, a knowledge
// page's text, a task comment = a message); then:
// - the area's search (GET /api/search?kind=<area>) finds it, and the one request without a kind has it in its group
// - the command palette: typing the word shows each object in its group ("Events", "Contacts", "Notes", "Knowledge pages",
//   "Messages") with its title; a click opens the target with its content visible; Back leads to where it started
// - msgSearch (the chat's search field, the search page) runs through the registry (kind messages): the comment is a hit
// - a browser source registered in SEARCH_SOURCES (like liste2e.js / wikie2e.js for the locked areas) adds its hits to the
//   palette's group; one that fails does not stop the server's hits
// The account has no organisation (a person on her own, like the freelancer fixture).
// P21026C_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21026C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const W = 'zinnoberwal';  // the word, only in the contents

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,events,contacts,wiki', workspace: 'private'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Plant the hedge', list_id: L})).id;
  const C = (await call('POST', `/api/tasks/${T}/comments`, {body: `The ${W} came by the pond`})).id;
  const EV = await call('POST', '/api/events', {title: 'Board meeting', start: '2030-03-04T10:00', end: '2030-03-04T11:00', description: `Talk about the ${W} report`});
  const CT = await call('POST', '/api/contacts', {fn: 'Zora Quill', note: `Met her at the ${W} fair`});
  const NT = await call('POST', `/api/lists/${L}/notes`, {title: 'Shopping', body: `Seeds for the ${W} bed`});
  const WK = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Guides/Setup', body: `# Setup\n\nFeed the ${W} twice a day.`});
  check(T && C && EV.id && CT.id && NT.id && WK.id, 'setup: task, comment, event, contact, note, page ' + JSON.stringify([C, EV.id, CT.id, NT.id, WK.id]));

  // ---- the server: each area's search and the one request without a kind
  const area = {
    events: async () => ((await call('GET', `/api/search?kind=events&q=${W}`)).events || []).some(e => e.id === EV.id),
    contacts: async () => ((await call('GET', `/api/search?kind=contacts&q=${W}`)).contacts || []).some(c => c.id === CT.id),
    notes: async () => ((await call('GET', `/api/search?kind=notes&q=${W}`)).notes || []).some(n => n.id === NT.id),
    wiki: async () => ((await call('GET', `/api/search?kind=wiki&q=${W}`)).pages || []).some(p => p.id === WK.id),
    messages: async () => ((await call('GET', `/api/search?kind=messages&q=${W}`)).hits || []).some(h => h.art === 'c' && h.id === C),
  };
  for (const [k, fn] of Object.entries(area)) check(await fn(), `the area search kind=${k} finds the word in the content`);
  const all = await call('GET', `/api/search?q=${W}`);
  const g = all.groups || {};
  check(!('office' in all) && !('wiki' in all) && !('comments' in all), 'no old top keys (office / wiki / comments are groups) ' + Object.keys(all).join(','));
  check((g.events || []).some(e => e.id === EV.id), 'one request: group events has the event ' + JSON.stringify(Object.keys(g)));
  check((g.contacts || []).some(c => c.id === CT.id), 'one request: group contacts has the contact');
  check((g.notes || []).some(n => n.id === NT.id), 'one request: group notes has the note');
  check((g.wiki || []).some(p => p.id === WK.id), 'one request: group wiki has the page (found in its text)');
  check((g.messages || []).some(h => h.art === 'c' && h.id === C), 'one request: group messages has the comment');
  check((await call('GET', `/api/search?q=${W}&kind=nonsense`)).status === 400, 'an unknown kind: 400');

  // ---- the browser
  const w = await boot({user: 'alice', hash: `l/${L}`}), d = w.document;
  const startHash = w.location.hash;
  const items = () => [...d.querySelectorAll('.palette .pitem')];
  const groupOf = name => [...d.querySelectorAll('.palette .pgroup')].find(x => x.textContent === name);
  const inGroup = (name, label) => {  // the item with that title below the heading of the group (before the next heading)
    const gh = groupOf(name); if (!gh) return null;
    for (let el = gh.nextElementSibling; el && !el.classList.contains('pgroup'); el = el.nextElementSibling) if (el.querySelector('.plt')?.textContent === label) return el;
    return null;
  };
  const visible = el => !!el && !el.closest('.hidden,[hidden]');
  const viewHas = s => (d.querySelector('#view')?.textContent || '').includes(s);
  const back = async what => {
    w.history.back();
    check(await until(() => w.location.hash === startHash && w.eval(`S.route.mod === 'tasks' && S.route.key === 'l:${L}'`)), `${what}: Back leads to the project again (${w.location.hash})`);
  };
  const pal = async () => {
    w.eval('closePop(); closePalette()'); await sleep(50);
    w.eval('openPalette()'); await until(() => d.querySelector('.palette .pqin'));
    input(w, d.querySelector('.palette .pqin'), W);
  };
  const cases = [
    ['Knowledge pages', 'Setup', async () => await until(() => w.eval(`S.route.mod === 'wiki' && S.route.wid === ${WK.id}`) && viewHas(`Feed the ${W}`)), 'the page with its text'],
    ['Contacts', 'Zora Quill', async () => await until(() => w.eval(`S.route.mod === 'contacts'`) && viewHas('Zora Quill')), 'the contact'],
    ['Events', 'Board meeting', async () => await until(() => /Board meeting/.test(d.querySelector('#pop .cevpop')?.textContent || '')), 'the event in the calendar (its popover)'],
    ['Notes', 'Shopping', async () => await until(() => w.eval(`S.route.mod === 'notes' && S.nt.id === ${NT.id}`) && viewHas(`Seeds for the ${W}`)), 'the note with its text'],
    ['Messages', 'Alice · Plant the hedge', async () => await until(() => w.eval(`S.sel === ${T}`) && d.querySelector(`#detail [data-mid="c:${C}"]`)), 'the task with the comment'],
  ];
  for (const [grp, label, opened, what] of cases) {
    await pal();
    const it = await until(() => inGroup(grp, label));
    check(it && visible(it), `palette: "${label}" visible in the group "${grp}"`);
    if (grp === 'Knowledge pages' || grp === 'Messages') check(it?.querySelector('.pls mark')?.textContent.toLowerCase() === W,
      `palette: "${label}" shows where the word is (its snippet with the word marked): ${it?.querySelector('.pls')?.innerHTML || ''}`);
    if (!it) continue;
    click(w, it);
    check(!!(await opened()), `a click on "${label}" opens ${what} (${w.location.hash})`);
    if (grp === 'Events') { w.eval('closePop()'); await sleep(50); }
    if (grp === 'Messages') { w.eval('closeDetail()'); await sleep(50); }
    await back(label);
  }

  // ---- msgSearch through the registry (kind messages)
  const ms = JSON.parse(await w.eval(`msgSearch('${W}', {limit: 20}).then(r => JSON.stringify(r))`));
  check((ms.hits || []).some(h => h.art === 'c' && h.id === C) && ms.total >= 1, 'msgSearch (chat search field, search page): the comment through the registry ' + JSON.stringify(ms).slice(0, 200));

  // ---- a browser source (the shape the locked areas register with): its hits join the group, a failing one does not stop the rest
  w.eval(`SEARCH_SOURCES.push({id: 'test-device', kinds: ['wiki'], search: async q => ({wiki: [{id: 987654, path: 'Locked/Diary', space: 'private', e2e: true}]})},
    {id: 'test-broken', search: async () => { throw new Error('boom'); }}); FTSP.q = ''`);  // the same word again: the palette keeps the last answer per word, so ask anew
  await pal();
  const loc = await until(() => inGroup('Knowledge pages', 'Diary'));
  check(loc && visible(loc), 'a browser source of the registry: its page in the group "Knowledge pages"');
  check(!!inGroup('Knowledge pages', 'Setup'), 'a failing source does not stop the server\'s hits');
  const wks = JSON.parse(await w.eval(`srchRun('${W}', {kind: 'wiki'}).then(r => JSON.stringify((r.wiki || []).map(p => p.id)))`));
  check(wks.includes(987654) && wks.includes(WK.id), 'srchRun kind wiki: server + browser source ' + JSON.stringify(wks));
  const mOnly = JSON.parse(await w.eval(`srchRun('${W}', {kind: 'messages'}).then(r => JSON.stringify({w: (r.wiki || []).length, m: (r.messages || []).length}))`));
  check(mOnly.w === 0 && mOnly.m >= 1, 'a source of another kind is not asked for kind messages ' + JSON.stringify(mOnly));
  w.eval(`SEARCH_SOURCES.splice(SEARCH_SOURCES.findIndex(s => s.id === 'test-device'), 2); closePalette()`);

  check(!errs.filter(e => !/boom/.test(e)).length, 'jsdom: no JS errors ' + errs.join(' | '));
  w.close();
  console.log(`p21026_c_search_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
