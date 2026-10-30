// 2.75.0 UI tests of part B (#1411, the built-in assistant; own container, start.sh, twice). jsdom:
// - without a configuration: no "assistant" in /api/state, /api/assistant 404, no settings section, no entry points
// - with a configuration (fake OpenAI-compatible endpoint tests/fake_ai.py in the container): Settings > Assistant shows
//   the provider, the switch turns it on (PATCH /api/settings), a ticked list is shared (PUT /api/assistant/lists)
// - entry points only while it is on: task detail "Assistant" > "Summarize" = the text dialog (Copy, Add as comment);
//   basket "Sort with the assistant" = the proposal dialog named "Assistant"; Today's "…" menu has "Assistant plan"
// - the log in the settings lists the calls; a child account sees no entry point
const {execFileSync, spawnSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
// EXTRA is word-split by start.sh: the provider name has no space
const AI = ' -e KALMIDO_AI_BASE_URL=http://127.0.0.1:8089/v1 -e KALMIDO_AI_MODEL=fake-1 -e KALMIDO_AI_KEY=test-key -e KALMIDO_AI_NAME=Fake-AI';
const start = extra => execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + extra}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const tick = (w, el, on = true) => { if (!el) return; el.checked = on; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const setup = async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
};
const menuItem = (d, re) => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => re.test(b.textContent));

(async () => {
  // ================= without a configuration
  if (!process.env.P275B_NOSTART) start('');
  await setup();
  let st = await call('GET', '/api/state');
  check(!('assistant' in st), 'off: /api/state has no assistant');
  check((await call('GET', '/api/assistant')).status === 404, 'off: /api/assistant is 404');
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const topMenu = async () => { click(w, await until(() => d.querySelector('#top [data-act="top-more"]'))); await sleep(150); const r = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); w.eval('closePop()'); return r; };
  check(!d.querySelector('[data-asst]') && !(await topMenu()).some(x => /Assistant plan/.test(x)), 'off: Today has no assistant entry');
  w.eval(`settingsModal()`); await sleep(400);
  check(d.querySelector('.smodal') && !d.querySelector('.smodal .snav [data-sec="assistant"]'), 'off: no settings section');
  w.close();

  // ================= with a configuration
  if (!process.env.P275B_NOSTART) start(AI);
  try { fs.copyFileSync(path.join(__dirname, 'fake_ai.py'), path.join(DATA, 'fake_ai.py')); } catch (e) { check(false, 'tests/fake_ai.py is there (part A)'); }
  spawnSync('docker', ['exec', '-d', CT, 'python', '/data/fake_ai.py']);
  await setup();
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces?.[0]?.id;
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  const P = (await call('POST', '/api/lists', {name: 'Private notes'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Offer for the new office', list_id: W, content: 'The landlord asks for a reply by Friday. Call the bank, then send the signed offer.'})).id;
  await call('POST', '/api/tasks', {title: 'Buy printer paper'});
  await call('POST', '/api/tasks', {title: 'Reply to the tax office'});
  const LINA = (await call('POST', '/api/users', {username: 'lina', display_name: 'Lina', password: 'password123', kid: true, parents: [me.id]})).id;
  st = await call('GET', '/api/state');
  check(st.assistant && st.assistant.enabled && st.assistant.provider === 'Fake-AI' && st.assistant.on === false, 'on: /api/state has the assistant, off for the person ' + JSON.stringify(st.assistant || null));

  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await sleep(600);
  check(!d.querySelector('[data-asst]') && !(await topMenu()).some(x => /Assistant plan/.test(x)), 'configured but not switched on: no entry point');
  w.eval(`settingsModal('assistant')`);
  const pane = await until(() => d.querySelector('.smodal [data-pane="assistant"]'));
  check(pane && !pane.classList.contains('hidden'), "settingsModal('assistant') opens the section");
  check(/Fake-AI/.test(pane?.querySelector('.asstprov')?.textContent || ''), 'the hint names the provider ' + (pane?.querySelector('.asstprov')?.textContent || ''));
  check(pane?.querySelector(`[data-asstl="${W}"]`) && pane?.querySelector(`[data-asstl="${P}"]`) && !pane?.querySelector(`[data-asstl="${st.lists.find(l => l.is_inbox)?.id}"]`), 'the list choice has the lists, not the basket');
  tick(w, pane?.querySelector('#s-asst-on'));
  check(await until(async () => (await call('GET', '/api/assistant')).on === true), 'the switch turns it on');
  tick(w, pane?.querySelector(`[data-asstl="${W}"]`));
  check(await until(async () => ((await call('GET', '/api/assistant')).lists || []).some(l => l.id === W)), 'a ticked list is shared');
  check(await until(() => w.eval('S.assistant.on') && w.eval(`S.assistant.list_ids.includes(${W})`)), 'the client knows it');
  w.eval(`document.querySelector('.smodal [data-m="close"]').click()`); await sleep(300);
  check((await topMenu()).some(x => /Assistant plan/.test(x)), 'Today: "Assistant plan" in the "…" menu');

  // the task detail: Summarize -> the text dialog
  w.eval(`openDetail(${T})`);
  const ab = await until(() => d.querySelector(`#detail [data-asst="task"][data-id="${T}"]`));
  check(ab, 'the task detail has the assistant button');
  click(w, ab);
  const sm = await until(() => menuItem(d, /Summarize/));
  check(sm && menuItem(d, /Extract tasks/) && menuItem(d, /Suggest tags and due date/) && menuItem(d, /Draft a reply/), 'its menu has the four kinds');
  click(w, sm);
  const tm = await until(() => { const m = d.querySelector('.modal.asstmd'); return m && m.querySelector('.assttext')?.textContent.trim() && m; }, 150);
  check(tm, 'Summarize opens the text dialog with a text');
  check(tm?.querySelector('[data-asstm="copy"]') && tm?.querySelector('[data-asstm="comment"]'), 'the dialog has Copy and Add as comment');
  if (tm) {
    click(w, tm.querySelector('[data-asstm="comment"]'));
    check(await until(async () => { const r = await call('GET', `/api/tasks/${T}/timeline`); return JSON.stringify(r).includes((tm.querySelector('.assttext').textContent || '').trim().slice(0, 20)); }, 40), 'Add as comment posts it');
  }
  w.close();

  // the basket: Sort with the assistant -> the proposal dialog named "Assistant"
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  const sb = await until(() => d.querySelector('[data-asst="triage"]'));
  check(sb && /Sort with the assistant/.test(sb.textContent), 'the basket has "Sort with the assistant"');
  click(w, sb);
  const pm = await until(() => d.querySelector('.modal.ppm'), 150);
  check(pm && /Assistant/.test(pm.textContent), 'the basket sort opens the proposal named Assistant ' + (pm?.textContent || '').slice(0, 160));
  w.close();

  // the log
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('assistant')`);
  const lg = await until(() => d.querySelector('.smodal #s-asst-log table'));
  check(lg && lg.querySelectorAll('tbody tr').length >= 2 && /Summary/.test(lg.textContent), 'the log lists the calls ' + (d.querySelector('.smodal #s-asst-log')?.textContent || '').slice(0, 160));
  check(!/Offer for the new office/.test(d.querySelector('.smodal #s-asst-log')?.textContent || ''), 'the log holds no task text');
  w.close();

  // a child account: no entry point
  const kst = await call('GET', '/api/state', null, await login('lina'));
  check(!kst.assistant || kst.assistant.on === false, 'child: the assistant is off');
  w = await boot({user: 'lina', hash: 'today'}); d = w.document;
  await sleep(800);
  check(!d.querySelector('[data-asst]'), 'child: no entry point');
  w.close();
  void LINA;

  console.log(`p275_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
