// kalmido-suite: fresh
// 2.470.0 B (#3596) UI tests: the letter blocks in the list Text blocks. Own container (start.sh), jsdom, invented data only.
// freelancer-matrix: office
// - a block written in the letter dialog shows in the list Text blocks under Letters, with its text, without the English hint
// - its editor: one text, no English field, the kind fixed; a save there reads in the letter dialog (same row)
// - a new text can be a letter block: the English field goes away
// - another kind's editor does not offer Letters
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']}, CK);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'clients,office,docs', workspace: 'private'}, CK);
  const b = await call('POST', '/api/office/letter-blocks', {name: 'Grussformel', body: 'Mit freundlichen Gruessen'}, CK);
  check(b.http === 201, 'setup: a block');

  const w = await boot({user: 'alice', hash: 'office/texts'}), d = w.document;
  const row = await until(() => [...d.querySelectorAll('.ofclist button, .ofclist [data-ofc]')].find(x => /Mit freundlichen Gruessen/.test(x.textContent)));
  check(!!row, 'the block shows in the list Text blocks');
  check(row && !/no English text stored/.test(row.textContent), 'no English hint on a block');
  check([...d.querySelectorAll('.ofcgrp')].some(h => /Letters/.test(h.textContent)), 'under the heading Letters');

  if (row) click(w, row);
  const md = await until(() => d.querySelector('.modal #of-text_de'));
  check(!!md, 'its editor opens');
  if (md) {
    const m = md.closest('.modal');
    check(md.maxLength === 20000, 'a block keeps its long text');
    check(m.querySelector('#of-text_en').type === 'hidden', 'no English field');
    check([...m.querySelectorAll('#of-kind option')].map(o => o.value).join() === 'letter', 'the kind stays letter');
    md.value = 'Herzliche Gruesse';
    click(w, m.querySelector('[data-m="save"]'));
    check(await until(async () => (await call('GET', '/api/office/letter-blocks', null, CK)).blocks?.[0]?.body === 'Herzliche Gruesse'), 'the save reads in the letter dialog');
  }
  await until(() => !d.querySelector('.modal'));
  click(w, await until(() => d.querySelector('[data-ofc="new"][data-kind="texts"]')));
  const nk = await until(() => d.querySelector('.modal #of-kind'));
  check(nk && [...nk.options].some(o => o.value === 'letter'), 'a new text can be a letter block');
  if (nk) {
    nk.value = 'letter'; nk.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(d.querySelector('.modal #of-text_en').closest('[data-ltp]').hidden && d.querySelector('.modal #of-text_de').maxLength === 20000, 'choosing it takes the English field away');
    d.querySelector('.modal #of-key').value = 'Aus der Liste'; d.querySelector('.modal #of-text_de').value = 'Neuer Baustein';
    click(w, d.querySelector('.modal [data-m="save"]'));
    check(await until(async () => (await call('GET', '/api/office/letter-blocks', null, CK)).blocks?.some(x => x.name === 'Aus der Liste')), 'saved as a block');
  }
  const note = await call('POST', '/api/office/texts', {kind: 'note', key: 'x', text_de: 'Notiz'}, CK);
  check(note.http === 201, 'setup: a note');
  await w.eval(`ofcLoad('texts', true)`);
  const nr = await until(() => [...d.querySelectorAll('.ofclist button, .ofclist [data-ofc]')].find(x => /Notiz/.test(x.textContent)));
  if (nr) click(w, nr);
  const ek = await until(() => d.querySelector('.modal #of-kind'));
  check(ek && ![...ek.options].some(o => o.value === 'letter'), 'another kind does not offer Letters');
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
