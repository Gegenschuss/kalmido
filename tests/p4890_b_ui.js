// kalmido-suite: fresh
// 2.772.0 (#4890) UI tests: the filters with numbers below the file store's tree (static/js/docfacets.js) and in the filter
// sheet of the documents list (phones, docs.js dc_fltHtml). Own container (start.sh), jsdom (computer and phone) + Firefox for
// the pictures and the widths (1440, 390). Invented names and files only.
// - below "All documents" the groups Sender, Archive number and a custom field (selection), folded the first time
// - a group opens, its rows carry name and number; over 15 values the most used 15 and "Show all"
// - a click shows All documents with only this filter, the row is marked; a second click takes it away
// - the fold state stays after a new start (kept per person); Archive number: "140-150" in the field, without / with (n)
// - a phone: archive number and the custom field in the filter sheet, the pills with their numbers
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p4890_b_ui', check, shots: 'P4890B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P4890B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const up = async (ck, name, text) => {
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json().catch(() => ({}));
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  // 19 documents: "Big Sender" on three, 16 more senders on one each (17 senders: over the 15 of a group)
  const ids = [];
  for (let i = 1; i <= 19; i++) ids.push(((await up(CA, `otter-${i}.txt`, `Invented otter letter number ${i}`)).ids || [])[0]);
  check(ids.every(Boolean), 'setup: 19 documents');
  check(await until(async () => { for (const id of ids) { const s = (await call(CA, 'GET', `/api/docs/${id}`)).state; if (!['done', 'failed'].includes(s)) return false; } return true; }, 400), 'setup: recognised');
  const fr = await call(CA, 'POST', '/api/docs/fields', {ws: 'private', name: 'Stage', type: 'select', options: [{name: 'Draft'}, {name: 'Final'}]});
  const stage = (fr.fields || []).find(x => x.name === 'Stage'), opt = Object.fromEntries((stage?.options || []).map(o => [o.name, o.id]));
  check(stage && opt.Final, 'setup: a selection field');
  for (let i = 0; i < 19; i++) {
    const body = {sender: i < 3 ? 'Big Sender' : `Sender ${String(i).padStart(2, '0')}`};
    if (i === 0) Object.assign(body, {asn: 143, custom_fields: {[stage.id]: opt.Final}});
    if (i === 1) Object.assign(body, {asn: 148, custom_fields: {[stage.id]: opt.Draft}});
    if (i === 3) body.asn = 200;
    check((await call(CA, 'PATCH', `/api/docs/${ids[i]}`, body)).http === 200, 'setup: values of document ' + i);
  }

  // ================= a computer: the groups below All documents
  const shared = {store: {}, wins: []};
  let w = await boot({user: 'alice', hash: 'ablage/docs', shared}), d = w.document;
  check(await until(() => d.querySelector('#side .dfc [data-dfcfold="sender"]'), 80), 'the panel: the group Sender below the documents\' rows');
  const grp = [...d.querySelectorAll('#side .dfc [data-dfcgrp]')].map(x => x.dataset.dfcgrp);
  check(grp.indexOf('sender') === 0 && grp.indexOf('asn') > 0 && grp.indexOf('cf:stage') > grp.indexOf('asn'), 'order: Sender ... Archive number, then the custom field ' + JSON.stringify(grp));
  check(d.querySelector('#side .abfilt').compareDocumentPosition(d.querySelector('#side .dfc')) & 4, 'the groups after All documents / To review');
  check(!d.querySelector('#side [data-dfc]'), 'folded the first time: no rows');
  check(d.querySelector('#side [data-dfcgrp="sender"] [data-dfcm="lists"]') && d.querySelector('#side [data-dfcgrp="asn"] [data-dfcm="settings"]'), 'each head has its button to manage it');
  d.querySelector('#side [data-dfcfold="sender"]').click();
  check(await until(() => d.querySelectorAll('#side [data-dfc="sender"]').length === 15), 'open: the 15 most used senders (' + d.querySelectorAll('#side [data-dfc="sender"]').length + ')');
  const first = d.querySelector('#side [data-dfc="sender"]');
  check(/Big Sender/.test(first?.textContent) && first?.querySelector('.c')?.textContent === '3', 'the most used first, with its number: ' + first?.textContent);
  d.querySelector('#side [data-dfcall="sender"]').click();
  check(await until(() => d.querySelectorAll('#side [data-dfc="sender"]').length === 17), 'Show all: all 17 senders');
  // a click filters, the row is marked; a second click takes the filter away
  d.querySelector('#side [data-dfc="sender"]').click();
  check(await until(() => w.eval('!DC.loading && DC.total === 3 && DC.docs && DC.docs.length === 3') && w.location.hash === '#ablage/docs'), 'a click: All documents with only Big Sender (3)');
  check(await until(() => d.querySelector('#side [data-dfc="sender"]')?.classList.contains('on') && d.querySelector('#side [data-dfc="sender"]')?.getAttribute('aria-pressed') === 'true'), 'the row is marked');
  check(d.querySelectorAll('.dc-view .dc-fbar .tsfx').length === 1, 'the list names the filter once');
  d.querySelector('#side [data-dfc="sender"]').click();
  check(await until(() => w.eval('!DC.loading && DC.total === 19 && !DC.f.sender.length') && !d.querySelector('#side [data-dfc="sender"].on')), 'a second click: the filter goes, the row is no longer marked');
  // archive number: a range in the field, without / with
  d.querySelector('#side [data-dfcfold="asn"]').click();
  check(await until(() => d.querySelector('#side .dfcasn input')), 'Archive number: the field "Number or range"');
  const without = d.querySelector('#side [data-dfc="asnhas"][data-dfcv="without"]');
  check(without && /16/.test(without.textContent) && /3/.test(d.querySelector('#side [data-dfc="asnhas"][data-dfcv="with"]')?.textContent || ''), 'without (16) / with archive number (3)');
  d.querySelector('#side .dfcasn input').value = '140-150';
  d.querySelector('#side .dfcasn').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(() => w.eval(`!DC.loading && DC.f.asn === '140-150' && DC.total === 2`)), 'Archive number 140-150: the two documents in that range');
  d.querySelector('#side [data-dfc="asnhas"][data-dfcv="without"]').click();
  check(await until(() => w.eval(`!DC.loading && DC.f.asnHas === 'without' && !DC.f.asn && DC.total === 16`)), 'without archive number: 16, the range is gone');
  // the custom field
  d.querySelector('#side [data-dfcfold="cf:stage"]').click();
  const fin = await until(() => [...d.querySelectorAll('#side [data-dfc="cf"]')].find(x => /Final/.test(x.textContent)));
  check(fin && fin.querySelector('.c')?.textContent === '1', 'the selection field: its values with numbers');
  fin?.click();
  check(await until(() => w.eval('!DC.loading && DC.total === 1 && DC.f.cf.length === 1')), 'a value of the field filters');
  // from a saved view: a row shows All documents with only its filter
  const VID = (await call(CA, 'POST', '/api/obj/docview', {title: 'Otters', query: 'q=otter', ws: 'private'})).id;
  w.location.hash = '#ablage/v/' + VID;
  check(await until(() => w.eval(`DC.dv === ${VID} && !DC.loading`)), 'a saved view open');
  d.querySelector('#side [data-dfc="sender"]').click();
  check(await until(() => w.location.hash === '#ablage/docs' && w.eval('!DC.dv && !DC.q && !DC.loading && DC.total === 3')), 'from a saved view: All documents with only that filter');
  check(JSON.stringify(w.eval(`LS.get('abFacOpen')`).sort()) === JSON.stringify(['asn', 'cf:stage', 'sender']), 'the fold state is kept: ' + JSON.stringify(w.eval(`LS.get('abFacOpen')`)));
  w.close();
  w = await boot({user: 'alice', hash: 'ablage/docs', shared}); d = w.document;
  check(await until(() => d.querySelector('#side [data-dfc="sender"]') && d.querySelector('#side .dfcasn'), 80), 'a new start: the opened groups are open again');
  w.close();

  // ================= a phone: the filter sheet
  w = await boot({user: 'alice', hash: 'ablage/docs', mobile: true}); d = w.document;
  check(await until(() => d.querySelector('.dc-view [data-dc="more"]') && w.eval('!!(DC.facets && DC.facets.fields)'), 80), 'phone: the list with its filters');
  d.querySelector('.dc-view [data-dc="more"]').click();
  check(await until(() => d.querySelector('.dc-fsheet .dc-asnin') && d.querySelector('.dc-fsheet [data-dcfcf]')), 'phone: archive number and the custom field in the filter sheet');
  check(/3/.test(d.querySelector('.dc-fsheet [data-dcfsender="Big Sender"] .tsc')?.textContent || ''), 'phone: the senders with their numbers');
  d.querySelector('.dc-fsheet [data-dcfasn="with"]').click();
  check(await until(() => w.eval(`!DC.loading && DC.f.asnHas === 'with' && DC.total === 3`)), 'phone: with archive number filters');
  w.close();

  // ================= pictures and widths
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.abFacOpen', '["sender","asn","cf:stage"]'); return 1; })()`);
    const s = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(s === 200, 'Firefox: login');
    const wait = async (js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#ablage/docs');
    check(await wait(`!!document.querySelector('#side [data-dfc="sender"]') && !!document.querySelector('.dc-view [data-dco]')`), '1440: the groups below the tree');
    await sleep(500);
    check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1`), '1440: nothing sticks out');
    await shot('p4890-b-1440-groups.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#ablage/docs');
    check(await wait(`!!document.querySelector('.dc-view [data-dc="more"]') && !!document.querySelector('.dc-view [data-dco]')`), '390: the list');
    await ev(`document.querySelector('.dc-view [data-dc="more"]').click()`);
    check(await wait(`!!document.querySelector('.dc-fsheet .dc-asnin')`), '390: the filter sheet with the archive number');
    await sleep(500);
    check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1`), '390: nothing sticks out');
    await shot('p4890-b-390-sheet.png');
  });

  console.log(`p4890_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
