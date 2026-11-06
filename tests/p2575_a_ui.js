// 2.575.0 A (#3778) UI tests, own container (start.sh), jsdom on a phone (390 px: mobile), invented data only:
// kalmido-suite: fresh
// - Settings > Modules shows "Own cards": my cards (Private) and the cards of my organisation
// - a private card is made in its editor (modules grouped by area) and applied with one tap: Private shows exactly its
//   modules, the organisation keeps the modules it showed (the main switches turn on, the rest is hidden per workspace)
// - the admin makes the organisation's default card; a member sees it as the upper limit (no "New card", no edit button,
//   own switches only inside it) and a module outside it is gone in the organisation's view, still there in Private
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {http: r.status, ...(Array.isArray(j) ? {list: j} : j)}; };
const until = (fn, n = 60) => require('./boot').until(fn, {timeout: n * 150, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,files,docs,wiki,sheets,habits,time,pomo';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Northwind', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call('GET', '/api/state');
  const K = ((st.me || {}).workspaces || [])[0]?.id;
  check(!!K, 'the organisation of the setup');
  const WS = 'org:' + K;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [K]})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);

  // ================= the admin on a phone: a private card, applied with one tap
  let w = await boot({user: 'alice', mobile: true}); let d = w.document;
  w.eval("settingsModal('modules')");
  check(await until(() => d.querySelector('.smodal #s-mcards [data-mcnew="private"]')), 'Settings > Modules: "Own cards" with "New card" in Private');
  check(!!d.querySelector(`.smodal #s-mcards [data-mcnew="${WS}"]`), 'the admin can make a card of the organisation');
  click(w, d.querySelector('.smodal [data-mcnew="private"]'));
  check(await until(() => d.querySelector('.modal.mcedit #mced-n')), 'the card editor opens');
  let md = d.querySelector('.modal.mcedit');
  check(md.querySelectorAll('fieldset.mcedg').length >= 3 && [...md.querySelectorAll('legend')].some(x => /Time/.test(x.textContent)), 'the modules are grouped by area');
  check(!md.querySelector('#mced-d') && !md.querySelector('[data-mcp]'), 'a private card has no default switch and no people');
  md.querySelector('#mced-n').value = 'Evenings';
  for (const k of ['cal', 'habits']) md.querySelector(`input[data-mcmod="${k}"]`).checked = true;
  click(w, md.querySelector('button[type="submit"]'));
  let cards = [];
  check(await until(async () => (cards = (await call('GET', '/api/modcards')).cards || []).length === 1), 'the card is saved');
  check(cards[0] && cards[0].name === 'Evenings' && cards[0].mods.join() === 'cal,habits', 'name and modules ' + JSON.stringify(cards[0] || {}));
  const btn = await until(() => d.querySelector(`.smodal [data-mcapply="${cards[0]?.id}"]`));
  check(!!btn, 'the card stands in "My cards"');
  if (btn) {
    click(w, btn);
    check(await until(() => w.eval('mc_privNow().join()') === 'cal,habits'), 'applied: Private shows exactly the card\'s modules ' + w.eval('mc_privNow().join()'));
    check(await until(() => d.querySelector(`.smodal [data-mcapply="${cards[0].id}"].on`)), 'the applied card is marked');
    const off = JSON.parse(w.eval('S.settings.ws_mods_off') || '{}');
    check(!(off[WS] || []).length, 'the organisation keeps what it showed (nothing hidden there, no module newly on)');
    check(w.eval(`mc_wsOn('${WS}', 'wiki')`) === true && w.eval("mc_wsOn('private', 'wiki')") === false, 'wiki: still in the organisation, hidden in Private');
  }

  // ================= the organisation's default card
  click(w, d.querySelector(`.smodal [data-mcnew="${WS}"]`));
  check(await until(() => d.querySelector('.modal.mcedit #mced-d')), 'the organisation\'s editor has the default switch and the people');
  md = d.querySelector('.modal.mcedit');
  md.querySelector('#mced-n').value = 'Team';
  for (const k of ['cal', 'wiki', 'comments', 'collab']) md.querySelector(`input[data-mcmod="${k}"]`).checked = true;
  md.querySelector('#mced-d').checked = true;
  check(!!md.querySelector(`input[data-mcp="${BOB}"]`), 'Bob can be assigned');
  click(w, md.querySelector('button[type="submit"]'));
  check(await until(async () => ((await call('GET', '/api/modcards?space=' + WS)).cards || []).some(c => c.name === 'Team' && c.dflt)), 'the default card is saved');
  check(await until(() => /Default card/.test(d.querySelector(`.smodal [data-mcgrp="${WS}"]`)?.textContent || '')), 'the card says "Default card"');
  check(!!d.querySelector(`.smodal [data-mcgrp="${WS}"] [data-mcedit]`), 'the admin can edit it');
  w.close();

  // ================= the member on a phone: the cap
  w = await boot({user: 'bob', mobile: true}); d = w.document;
  await until(() => w.eval('!!S.me?.workspaces?.length'));
  check(JSON.stringify(w.eval(`wsOrg(${K}).mods_cap`)) === JSON.stringify(['cal', 'collab', 'comments', 'wiki']), 'Bob: the cap from the state ' + JSON.stringify(w.eval(`wsOrg(${K})?.mods_cap`)));
  await w.eval(`wsSet('${WS}')`); await sleep(200);
  check(w.eval("feat('sheets')") === false && w.eval("feat('wiki')") === true, 'in the organisation: tables gone (not on the card), knowledge there');
  await w.eval("wsSet('private')"); await sleep(200);
  check(w.eval("feat('sheets')") === true, 'in Private: tables there');
  w.eval("settingsModal('modules')");
  check(await until(() => d.querySelector(`.smodal [data-mcgrp="${WS}"]`)), 'Bob sees the cards of the organisation');
  const g = d.querySelector(`.smodal [data-mcgrp="${WS}"]`);
  check(g && !g.querySelector('[data-mcnew]') && !g.querySelector('[data-mcedit]'), 'Bob: no "New card", no edit button');
  check(g && /Team/.test(g.textContent) && g.querySelectorAll('input[data-mchide]').length === 4, 'Bob: the card and his own switches inside the cap');
  const hw = g?.querySelector('input[data-mchide="wiki"]');
  if (hw) {
    hw.checked = false; hw.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(async () => JSON.parse((await call('GET', '/api/state', null, CKB)).settings?.ws_mods_off || '{}')[WS]?.includes('wiki')), 'Bob hides knowledge inside the cap');
  }
  w.close();

  console.log(`p2575_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
