// 2.560.0 C (#4700) UI tests, own container (start.sh), jsdom, invented data only:
// kalmido-suite: fresh
// - a generated document's autosave takes the answer's updated_at: the own next autosave passes (no 409 against itself);
//   another tab saved meanwhile -> the editor shows "Changed in the meantime" with "Reload", the other tab's text stays,
//   "Reload" shows the saved text
// - the deal dialog: saved elsewhere meanwhile -> the bar with "Reload" (the dialog stays, nothing overwritten); "Reload"
//   opens the dialog with the saved state
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Object.assign(j, {http: r.status}); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,office,clients,docs';
// another tab saves (without a version, like an old client) until its save has a later updated_at than `was` (whole seconds)
async function otherSave(url, body, was, method = 'PATCH') {
  let j = null;
  await until(async () => { j = await call(method, url, body); return j.http === 200 && j.updated_at && j.updated_at !== was; }, 60);
  return j;
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  // ================= a generated document: autosave from this tab, then a second tab
  const CL = (await call('POST', '/api/clients', {name: 'Example Media GmbH'})).id;
  const G = await call('POST', '/api/office/gen-docs', {title: 'Note', body: 'First text', client_id: CL});
  check(G.http === 201 && G.updated_at, 'a document draft ' + G.http);
  let w = await boot({hash: `office/gendocs/${G.id}`}); let d = w.document;
  await until(() => d.querySelector('#dt-body'), 60);
  const ta = d.querySelector('#dt-body');
  check(!!ta, 'the document editor is open');
  if (ta) {
    type(w, ta, 'Tab A one');
    check(await until(async () => (await call('GET', `/api/office/gen-docs/${G.id}`)).body === 'Tab A one', 60), 'the first autosave arrived');
    type(w, ta, 'Tab A two');
    check(await until(async () => (await call('GET', `/api/office/gen-docs/${G.id}`)).body === 'Tab A two', 60), 'the own next autosave passes (it took the new updated_at)');
    check(!d.querySelector('[data-dt-reload]'), 'no conflict bar against the own saves');
    const now = await call('GET', `/api/office/gen-docs/${G.id}`);
    const o = await otherSave(`/api/office/gen-docs/${G.id}`, {body: 'Other tab text'}, now.updated_at);
    check(o && o.body === 'Other tab text', 'the other tab saved');
    type(w, ta, 'Tab A three');
    await until(() => d.querySelector('[data-dt-reload]'), 60);
    check(/Changed in the meantime/.test(d.querySelector('#dt-err')?.textContent || '') && d.querySelector('[data-dt-reload]'),
      'conflict: the editor shows "Changed in the meantime" with "Reload": ' + (d.querySelector('#dt-err')?.textContent || ''));
    check((await call('GET', `/api/office/gen-docs/${G.id}`)).body === 'Other tab text', 'conflict: the other tab\'s text was not overwritten');
    const rl = d.querySelector('[data-dt-reload]');
    if (rl) {
      click(w, rl);
      check(await until(() => d.querySelector('#dt-body')?.value === 'Other tab text', 60), 'reload: the editor shows the saved text ' + (d.querySelector('#dt-body')?.value || ''));
    }
  }
  w.close();

  // ================= the deal dialog
  const D = await call('POST', '/api/office/deals', {title: 'Image film'});
  check(D.http === 201 && D.updated_at, 'a deal ' + D.http);
  w = await boot({hash: 'office/pipeline'}); d = w.document;
  await until(() => d.querySelector(`[data-pp="open"][data-id="${D.id}"]`), 60);
  const card = d.querySelector(`[data-pp="open"][data-id="${D.id}"]`);
  check(!!card, 'the deal card');
  if (card) {
    click(w, card);
    await until(() => d.querySelector('.modal #pp-title'), 30);
    let md = d.querySelector('.modal #pp-title')?.closest('.modal');
    const o = await otherSave(`/api/office/deals/${D.id}`, {title: 'Other title'}, D.updated_at);
    check(o && o.title === 'Other title', 'the other tab renamed the deal');
    md.querySelector('#pp-note').value = 'this tab';
    click(w, md.querySelector('[data-m="save"]'));
    // 2.559.0 (#4660): the dialog closes at once; the 409 opens it again with this tab's input and the bar (a new element)
    await until(() => d.querySelector('.modal [data-pp-reload]'), 40);
    md = d.querySelector('.modal [data-pp-reload]')?.closest('.modal') || md;
    check(md.isConnected && /Changed in the meantime/.test(md.querySelector('.aerr')?.textContent || '') && md.querySelector('[data-pp-reload]') && md.querySelector('#pp-note')?.value === 'this tab',
      'conflict: the dialog is open again with this tab\'s input, "Changed in the meantime" and "Reload": ' + (md.querySelector('.aerr')?.textContent || ''));
    const dj = (await call('GET', '/api/office/deals')).items.find(x => x.id === D.id);
    check(dj && dj.title === 'Other title' && dj.note !== 'this tab', 'conflict: nothing was overwritten ' + JSON.stringify(dj && [dj.title, dj.note]));
    const rl = md.querySelector('[data-pp-reload]');
    if (rl) {
      click(w, rl);
      await until(() => d.querySelector('.modal #pp-title') && d.querySelector('.modal #pp-title').closest('.modal') !== md, 30);
      md = d.querySelector('.modal #pp-title')?.closest('.modal');
      check(md && md.querySelector('#pp-title').value === 'Other title', 'reload: the dialog shows the saved state');
    }
  }
  w.close();

  console.log(`p2560_c_conflict_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
