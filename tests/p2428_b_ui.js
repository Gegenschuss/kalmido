// kalmido-suite: fresh
// 2.428.0 UI tests of part B (#3579, own container, start.sh; P2428B_NOSTART=1: the container runs already). jsdom:
// - documents: the sort button next to Filter shows the current sort (document date, newest first); its menu picks another
//   one (the list follows, the button names it), the chosen one again turns the direction round; the choice is remembered on
//   this device (a new window keeps it); phones (390 px): the sort sits at the top of the filter sheet
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2428B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const docNew = async (name, text, fields) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 300);
  if (fields) await call('PATCH', `/api/docs/${id}`, fields);
  return id;
};
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const cards = d => [...d.querySelectorAll('.dc-view [data-dco]')].map(x => +x.dataset.dco).filter((x, i, a) => a.indexOf(x) === i);
const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs'});
  const D1 = await docNew('a-brief.txt', 'Ein Brief', {date: '2025-03-01', amount: '120.00'});
  const D2 = await docNew('b-rechnung.txt', 'Eine Rechnung', {date: '2025-01-15', amount: '9.50'});
  const D3 = await docNew('c-vertrag.txt', 'Ein Vertrag', {date: '2025-06-20', amount: '1000'});

  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  const btn = () => d.querySelector('.dc-bar [data-dc="sort"]');
  check(await until(() => btn() && same(cards(d), [D3, D1, D2])), `default: newest document date first ${cards(d)}`);
  check(btn() && /Document date/.test(btn().textContent) && /↓/.test(btn().textContent) && !btn().classList.contains('on'), 'the button names the default sort');
  click(w, btn());
  const mi = await until(() => [...d.querySelectorAll('[role="menuitem"].dc-sorti')].find(b => /Amount/.test(b.textContent)));
  check(mi, 'the menu offers the amount');
  if (mi) click(w, mi);
  check(await until(() => same(cards(d), [D3, D1, D2])) && /Amount/.test(btn()?.textContent || '') && btn().classList.contains('on'), 'amount, highest first; the button names it');
  click(w, btn());
  const mi2 = await until(() => [...d.querySelectorAll('[role="menuitem"].dc-sorti.on')].find(b => /Amount/.test(b.textContent)));
  check(mi2, 'the chosen sort is marked');
  if (mi2) click(w, mi2);
  check(await until(() => same(cards(d), [D2, D1, D3])) && /↑/.test(btn()?.textContent || ''), `the chosen one again: lowest first ${cards(d)}`);
  w.close();
  // remembered on this device: a new window of the same browser storage starts with it
  const w2 = await boot({user: 'alice', hash: 'docs', ls: {'tasks.dc.sort': JSON.stringify({k: 'title', d: 'desc'})}}), d2 = w2.document;
  check(await until(() => same(cards(d2), [D3, D2, D1])) && /Title/.test(d2.querySelector('.dc-bar [data-dc="sort"]')?.textContent || ''), `the stored sort is used ${cards(d2)}`);
  w2.close();

  // phones: the sort at the top of the filter sheet
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), md = m.document;
  const fb = await until(() => md.querySelector('.dc-bar [data-dc="more"]'));
  if (fb) click(m, fb);
  const sh = await until(() => md.querySelector('.modal.dc-fsheet [data-dcsort="amount"]') && md.querySelector('.modal.dc-fsheet'));
  check(sh, 'phones: the sheet has the sort');
  if (sh) {
    click(m, sh.querySelector('[data-dcsort="amount"]'));
    check(await until(() => same(cards(md), [D3, D1, D2])), 'phones: amount, highest first');
    click(m, await until(() => md.querySelector('.modal.dc-fsheet [data-dcsortd="asc"]')));
    check(await until(() => same(cards(md), [D2, D1, D3]) && md.querySelector('.modal.dc-fsheet [data-dcsortd="asc"][aria-checked="true"]')), 'phones: the direction');
  }
  m.close();

  console.log(`p2428_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
