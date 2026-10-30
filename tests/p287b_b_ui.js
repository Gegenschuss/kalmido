// 2.87.9 UI tests (part B), own container (start.sh). jsdom:
// #1940 the shared question before an import (importTargetConfirm): an organisation as target names it and offers "Rather
//       into private" (resolves 'private'), the private space names it without that button, Cancel starts nothing; a person
//       without an organisation only ever sees the private space
// #1936 Paperless-ngx in Settings > Integrations: a card that jumps to the section, the section names the workspace and
//       switches between them; the documents settings only keep the progress and a jump to the settings
// #1938 the progress of a running import keeps going: the settings opened again load afresh (before: the cached "1 of 5"
//       stayed), a lost answer keeps the last state and asks again, the end is said once
// #1935 the hint under the bar: "Runs on in the background …" while it runs on the server, "Keep the window open …" while
//       the browser uploads an export; the target of the run (#1940) below the bar
// #1934 the search: "Import from Paperless-ngx…" / "Connect Paperless-ngx", the parts of the areas with the area below,
//       the senders / types / tags of the documents and the top folders of the file store as hits
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const erin = await call('POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com'});
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: bob.id});
  check(org.status === 201, 'setup: organisation Alpha with bob as admin');
  const CB = await login('bob'), CE = await login('erin');
  for (const ck of [CB, CE]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'docs,files', workspace: 'all'}, ck);
  const OWS = 'org:' + org.id;

  // ================= #1940 the question before an import
  let w = await boot({user: 'bob'}), d = w.document;
  check(w.eval('typeof importTargetConfirm') === 'function', '#1940: one shared function for every importer');
  w.eval(`window._r = 'x'; importTargetConfirm({what: trn('{0} document', '{0} documents', 182), ws: '${OWS}', privOk: true}).then(v => { window._r = v; })`);
  await until(() => d.querySelector('.itc-dlg'));
  let dl = d.querySelector('.itc-dlg');
  check(dl && /Alpha/.test(dl.querySelector('h3')?.textContent || ''), '#1940: the title names the organisation');
  check(dl && /182 documents/.test(dl.textContent) && /Members of the organisation/.test(dl.textContent), '#1940: the text says how many and who sees them ' + dl?.textContent);
  const priv = dl?.querySelector('[data-itc="private"]');
  check(priv && /Rather into private/.test(priv.textContent), '#1940: "Rather into private" with an organisation as target');
  click(w, priv);
  await until(() => w._r !== 'x');
  check(w._r === 'private' && !d.querySelector('.itc-dlg'), '#1940: "Rather into private" resolves private and closes ' + w._r);
  w.eval(`window._r = 'x'; importTargetConfirm({what: 'the tasks', ws: '${OWS}', place: 'Projects'}).then(v => { window._r = v; })`);
  await until(() => d.querySelector('.itc-dlg'));
  dl = d.querySelector('.itc-dlg');
  check(dl && /“Projects”/.test(dl.textContent) && !dl.querySelector('[data-itc]'), '#1940: a fixed place (list, calendar) is named, no private button without privOk');
  click(w, dl?.querySelector('[data-cd="no"]'));
  await until(() => w._r !== 'x');
  check(w._r === null, '#1940: Cancel starts nothing (null)');
  w.eval(`window._r = 'x'; importTargetConfirm({what: 'the feeds', ws: 'private', privOk: true}).then(v => { window._r = v; })`);
  await until(() => d.querySelector('.itc-dlg'));
  dl = d.querySelector('.itc-dlg');
  check(dl && /your private space/.test(dl.textContent) && !dl.querySelector('[data-itc]'), '#1940: the private space is named, no extra button');
  click(w, dl?.querySelector('[data-cd="yes"]'));
  await until(() => w._r !== 'x');
  check(w._r === 'same', '#1940: Import resolves the shown target');

  // ================= #1934 the search
  check(w.eval(`palAll().some(x => x.id === 'a:plimp')`) && w.eval(`palAll().some(x => x.id === 'a:plset')`), '#1934: the Paperless-ngx actions are there');
  w.eval(`PAL.q = 'paperless'; PAL.mode = null`);
  const hits = w.eval(`palItems().slice(0, 6).map(x => x.id)`);
  check(hits.includes('a:plimp') && hits.includes('a:plset'), '#1934: "paperless" finds the import and the connection ' + hits);
  w.eval(`PAL.q = 'import'`);
  check(w.eval(`palItems().some(x => x.id === 'a:plimp')`), '#1934: "import" finds it too');
  const docsHit = w.eval(`(palAll().find(x => x.id === 'v:docs') || {}).sub`);
  check(docsHit === 'File store', '#1934: a part of an area (Documents) with the area below: ' + docsHit);
  w.eval(`PALX.ws = wsCur(); PALX.at = Date.now(); PALX.docs = {senders: [{name: 'Example Utility', ids: [7]}], types: [{name: 'Invoice', ids: [9]}], tags: [{name: 'Tax', ids: [3]}]}; PALX.folders = [{id: 99, name: 'Contracts', sp: 'private', many: false}]`);
  w.eval(`PAL.q = 'tax'`);
  const tax = w.eval(`palItems().find(x => x.id === 'dcf:tag:3')`);
  check(tax && tax.sub === 'Documents · Tag', '#1934: a tag of the documents with "Documents · Tag" ' + JSON.stringify(tax?.sub));
  w.eval(`PAL.q = 'utility'`);
  check(w.eval(`palItems().some(x => x.id === 'dcf:sender:7')`), '#1934: a sender of the documents');
  w.eval(`PAL.q = 'contracts'`);
  const fol = w.eval(`palItems().find(x => x.id === 'abf:99')`);
  check(fol && fol.sub === 'Files', '#1934: a top folder of the file store ' + JSON.stringify(fol?.sub));
  w.eval(`PAL.q = ''`);
  check(!w.eval(`palItems().some(x => String(x.id).startsWith('dcf:') || x.id === 'a:plimp')`), '#1934: they only show while typing (empty search stays short)');

  // ================= #1936 Settings > Integrations, #1938 / #1935 the progress
  // a stand-in for the server's answer: a run in the organisation, its count set by the test
  w.eval(`window._pl = {state: 'busy', total: 5, done: 1, lost: false, n: 0}; window._raw0 = rawFetch;
    rawFetch = async (m, url, b) => {
      if (m === 'GET' && url.startsWith('/api/paperless?')) {
        _pl.n++;
        if (_pl.lost) throw Object.assign(new Error('down'), {status: 502});
        const ws = decodeURIComponent(url.split('ws=')[1] || 'private');
        const run = {state: _pl.state === 'idle' ? 'idle' : _pl.state, kind: 'all', total: _pl.total, done: _pl.done, new: _pl.done, skipped: 0, failed: 0, error: '', error_text: '', place: null, target: 'ws', mine: true, learn: {}};
        return {available: true, can_manage: true, ws, every_choices: [15, 60], hosted: false, zip: null, zip_max: 1048576,
          conn: ws === 'private' ? null : {url: 'https://paperless.example.com', token_set: true, follow: false, every_min: 15, synced_at: null, error: '', error_text: '', run}};
      }
      return _raw0(m, url, b);
    };`);
  w.eval(`S.settings.workspace = '${OWS}'`);
  w.eval(`settingsModal('integr')`);
  await until(() => d.querySelector('.smodal .icard[data-jump="#s-pl-h"]'));
  check(d.querySelector('.smodal .icard[data-jump="#s-pl-h"]'), '#1936: a card "Documents from Paperless-ngx" in Integrations');
  await until(() => d.querySelector('#s-pl-h'));
  check(d.querySelector('[data-pane="integr"] #s-pl-h'), '#1936: the Paperless-ngx section is in Integrations');
  const sel = d.querySelector('#pl-ws');
  check(sel && sel.value === OWS && [...sel.options].some(o => o.value === 'private'), '#1936: it names the workspace and switches between them');
  await until(() => /1 of 5/.test(d.querySelector('.pl-slot .pl-run')?.textContent || ''));
  check(/1 of 5/.test(d.querySelector('.pl-slot .pl-run')?.textContent || ''), '#1938: the run shows its count');
  check(/Runs on in the background/.test(d.querySelector('.pl-slot .pl-bg')?.textContent || ''), '#1935: the hint that it runs on in the background');
  check(/Into the organisation Alpha/.test(d.querySelector('.pl-slot .pl-to')?.textContent || ''), '#1940: the target below the bar ' + d.querySelector('.pl-slot .pl-to')?.textContent);
  w.eval(`_pl.done = 2`);
  check(await until(() => /2 of 5/.test(d.querySelector('.pl-slot .pl-run')?.textContent || ''), 40), '#1938: polling follows the count');
  d.querySelector('.smodal')?.remove();
  w.eval(`_pl.done = 3`);
  await sleep(2600);  // the poll stopped with no slot on screen: the cached state says "2 of 5"
  w.eval(`settingsModal('paperless')`);
  check(await until(() => /3 of 5/.test(d.querySelector('.pl-slot .pl-run')?.textContent || ''), 30), '#1938: the settings opened again show the current count (not the cached one)');
  w.eval(`_pl.lost = true`);
  const n0 = w.eval('_pl.n');
  await sleep(2600);
  check(/3 of 5/.test(d.querySelector('.pl-slot .pl-run')?.textContent || ''), '#1938: a lost answer keeps the last state on screen');
  w.eval(`_pl.lost = false; _pl.done = 5; _pl.state = 'idle'`);
  check(await until(() => !d.querySelector('.pl-slot .pl-run'), 120) && w.eval('_pl.n') > n0, '#1938: it asks again after a lost answer and ends '
    + JSON.stringify(w.eval(`({n: _pl.n, fail: PL.fail, st: PL.d?.conn?.run?.state, slots: $$('.pl-slot').length, txt: $('.pl-slot .pl-run')?.textContent})`)) + ' n0=' + n0);
  check(await until(() => /Import from Paperless-ngx finished/.test(d.querySelector('#toast, .toast')?.textContent || ''), 20), '#1938: the end is said once');
  // the documents settings: only progress + a way to the settings
  w.eval(`_pl.state = 'busy'; _pl.done = 2`);
  const slot = w.eval(`(PL.d = null, PL.at = 0, pl_slot({ws: '${OWS}'}))`);
  check(/data-plmode="docs"/.test(slot), '#1936: the documents settings get the short slot');
  await sleep(600);
  check(/Into|data-pl="goset"/.test(w.eval(`pl_html('docs')`)) && !/pl-url|Connect by address/.test(w.eval(`pl_html('docs')`)), '#1936: … without the connection form, with the jump to the settings');
  w.eval(`PL.up = {done: 1048576, total: 4194304}`);
  check(/Keep the window open/.test(w.eval(`pl_html('docs')`)), '#1935: while the browser uploads: keep the window open');
  w.eval(`PL.up = null`);
  w.close();

  // ================= P4: a person without an organisation
  w = await boot({user: 'erin'}); d = w.document;
  w.eval(`window._r = 'x'; importTargetConfirm({what: 'the tasks', ws: 'private', privOk: true}).then(v => { window._r = v; })`);
  await until(() => d.querySelector('.itc-dlg'));
  dl = d.querySelector('.itc-dlg');
  check(dl && /your private space/.test(dl.textContent) && !dl.querySelector('[data-itc]') && !/organisation/i.test(dl.textContent), 'P4: without an organisation only the private space');
  click(w, dl?.querySelector('[data-cd="no"]'));
  w.eval(`settingsModal('integr')`);
  await until(() => d.querySelector('#s-pl-h'), 40);
  check(d.querySelector('#s-pl-h') && !d.querySelector('#pl-ws'), 'P4: the Paperless-ngx section without a workspace choice');
  check(d.querySelector('#pl-url') && d.querySelector('[data-pl="connect"]'), 'P4: their own connection can be set up there');
  w.close();

  console.log(`p287b_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
