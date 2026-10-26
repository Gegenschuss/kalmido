// kalmido-suite: fresh
// 2.353.0 D (#2759) UI tests: file store and documents are ONE area "Ablage". Own container (start.sh), jsdom + Firefox for
// the pictures (computer 1440, phone 390). Invented names and files only.
// - no own entry "Documents" any more: no tabs on the file store, the area has one shown part; below the folders the saved
//   filters "Documents" and "To review" (panel on a computer, the list of spaces on a phone)
// - old links: #docs opens the documents filter inside the file store (its icon lit, the filter marked), #docs/review the
//   filter "To review" (also the button of the view), #docs/<id> the document sheet
// - list / cards per folder: the documents folder as cards = the documents' tiles; another folder stays a list; the choice
//   is kept for the person (a second device shows the cards again)
// - recognition: the line "Recognition on" in the documents folder; a file in a plain folder: "Recognise" in its menu makes
//   it a document; a folder: "Recognition…"; the card's menu has Share… and the link for external people
// freelancer-matrix: files (alice has no organisation: her private space)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2353_d_ablagedocs_ui', check, shots: 'P2353D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2353D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent.trim());
const pick = (d, label) => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.querySelector('.ml')?.textContent.trim().startsWith(label));
const up = async (url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  const DOC = ((await up('api/docs', 'files', 'letter-alpha.txt', 'Letter of an invented insurance', {ws: 'private'})).ids || [])[0];
  check(DOC, 'setup: a document (makes the documents folder)');
  const ROOT = (await call('GET', `/api/files/nodes/${DOC}`)).parent_id;
  const PLAIN = (await call('POST', '/api/files/folders', {space: 'private', name: 'Holiday'})).id;
  const FILE = ((await up('api/files/upload', 'file', 'packing-list.txt', 'Sun cream, hat', {parent_id: String(PLAIN)})).items || [])[0]?.id;
  check(ROOT && PLAIN && FILE, 'setup: a plain folder with a file');
  check((await call('GET', `/api/docs/${FILE}`)).http === 404, 'setup: the plain file is no document');

  // ================= a computer: one area, the saved filters, old links
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  await until(() => d.querySelector('#side .abfilt'));
  check(w.eval(`mg_partsShown(mg_area('ablage')).map(p => p[0]).join()`) === 'ablage', 'the area shows one part (no entry Documents)');
  check(!d.querySelector('#view .mgtabs') && !d.querySelector('#srail [data-sbb="docs"]'), 'no tabs, no own icon for Documents');
  check(d.querySelector('#side .abfilt [data-go="docs"]') && d.querySelector('#side .abfilt [data-go="docs/review"]'), 'the panel: the saved filters Documents and To review');
  check(/Documents/.test(d.querySelector('#side .abfilt [data-go="docs"]')?.textContent || '') && /To review/.test(d.querySelector('#side .abfilt [data-go="docs/review"]')?.textContent || ''), 'the filters are named');
  w.location.hash = '#docs';
  check(await until(() => w.eval('S.route.mod') === 'docs' && d.querySelector('#view .dc-view [data-dco]')), 'old link #docs: the documents');
  check(d.querySelector('#srail [data-sbb="ablage"].on') && d.querySelector('#side .abfilt [data-go="docs"][aria-current="page"]'), 'old link #docs: inside the file store, the filter Documents marked');
  w.location.hash = '#docs/review';
  check(await until(() => d.querySelector('#side .abfilt [data-go="docs/review"][aria-current="page"]') && d.querySelector('[data-dc="review"][aria-selected="true"]')), 'old link #docs/review: the filter To review');
  d.querySelector('[data-dc="all"]')?.click();
  check(await until(() => w.location.hash === '#docs' && d.querySelector('#side .abfilt [data-go="docs"][aria-current="page"]')), 'the button All of the view = the filter Documents');
  w.location.hash = '#docs/' + DOC;
  check(await until(() => d.querySelector('.dc-md')), 'old link #docs/<id>: the document sheet');
  w.eval(`modalClose(document.querySelector('.dc-md'))`);
  w.close();

  // ================= list / cards per folder, recognition
  w = await boot({user: 'alice', hash: 'ablage/' + ROOT}); d = w.document;
  check(await until(() => d.querySelector('.abview .ablist [data-abid="' + DOC + '"]')), 'the documents folder: a list first');
  check(await until(() => /Recognition on/.test(d.querySelector('.abrecog')?.textContent || '')), 'the documents folder: Recognition on');
  check(await until(() => d.querySelector(`[data-abid="${DOC}"] .abdoc`)), 'the list marks the document');
  d.querySelector('[data-abdv="cards"]')?.click();
  check(await until(() => d.querySelector(`.abview .abcards [data-dco="${DOC}"]`)), 'Cards: the document as its tile');
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.ab_cards || '[]').includes('n:' + ROOT)), 'the choice is saved for the person');
  d.querySelector(`.abcards [data-dco="${DOC}"]`)?.closest('li')?.querySelector('[data-ab="menu"]')?.click();
  const cm = await until(() => menuItems(d).length && menuItems(d));
  check(cm && cm.includes('Share…') && cm.some(x => /Link for external people/.test(x)), 'the card\'s menu: Share… and the link for external people ' + JSON.stringify(cm));
  w.eval('closePop()');
  w.location.hash = '#ablage/' + PLAIN;
  check(await until(() => d.querySelector(`.abview .ablist [data-abid="${FILE}"]`) && !d.querySelector('.abview .abcards')), 'another folder: still a list');
  d.querySelector(`[data-abid="${FILE}"] [data-ab="menu"]`)?.click();
  const fm = await until(() => menuItems(d).length && menuItems(d));
  check(fm && fm.includes('Recognise'), 'a plain file: Recognise in its menu ' + JSON.stringify(fm));
  pick(d, 'Recognise')?.click();
  check(await until(async () => (await call('GET', `/api/docs/${FILE}`)).http === 200), 'Recognise: the file became a document');
  check(await until(() => d.querySelector(`[data-abid="${FILE}"] .abdoc`)), 'the list marks it at once');
  w.location.hash = '#ablage';
  await until(() => d.querySelector(`.abview [data-abid="${PLAIN}"] [data-ab="menu"]`));
  d.querySelector(`[data-abid="${PLAIN}"] [data-ab="menu"]`)?.click();
  check(await until(() => menuItems(d).includes('Recognition…')), 'a folder: Recognition… in its menu');
  pick(d, 'Recognition…')?.click();
  check(await until(() => ['As the folder above', 'On', 'Off'].every(l => pick(d, l))), 'Recognition…: As the folder above / On / Off (with their hints)');
  pick(d, 'On')?.click();
  check(await until(async () => (await call('GET', `/api/files?parent=${PLAIN}`)).node?.recog_on === true), 'On: the folder recognises');
  w.close();
  w = await boot({user: 'alice', hash: 'ablage/' + ROOT}); d = w.document;
  check(await until(() => d.querySelector(`.abview .abcards [data-dco="${DOC}"]`)), 'a new start: the documents folder shows its cards again');
  w.close();

  // ================= a phone: the filters below the spaces, no tabs
  w = await boot({user: 'alice', hash: 'ablage', mobile: true}); d = w.document;
  check(await until(() => d.querySelector('.abspaces .abfilt[data-go="docs"]') && d.querySelector('.abspaces .abfilt[data-go="docs/review"]')), 'phone: the saved filters below the spaces');
  check(!d.querySelector('#view .mgtabs'), 'phone: no tabs');
  w.location.hash = '#docs';
  check(await until(() => d.querySelector('.dc-view .abdnav [data-go="ablage"]')), 'phone: the documents filter leads back to the files');
  w.close();

  // ================= pictures: computer and phone
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'Firefox: login');
    const wait = async (js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    for (const [wd, h, tag] of [[1440, 900, '1440'], [390, 844, '390']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: h}});
      await o.nav(B + '#ablage/' + ROOT);
      check(await wait(`!!document.querySelector('.abview .abcards .dc-card')`), `${tag}: the cards of the documents folder`);
      await sleep(500); await shot(`p2353-d-${tag}-cards.png`);
      await o.nav(B + '#ablage/' + PLAIN);
      check(await wait(`!!document.querySelector('.abview .ablist .abrow')`), `${tag}: a plain folder as a list`);
      await sleep(400); await shot(`p2353-d-${tag}-list.png`);
      await o.nav(B + '#docs/review');
      check(await wait(`!!document.querySelector('.dc-view')`), `${tag}: the filter To review`);
      await sleep(400); await shot(`p2353-d-${tag}-review.png`);
    }
  });

  console.log(`p2353_d_ablagedocs_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
