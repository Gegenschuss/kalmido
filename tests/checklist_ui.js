// Package B UI tests (jsdom): checklist mode (compact rows, "Done" section with "back on the list", Uncheck all, Clear done,
// list dialog switch), the public link section of the list dialog (owner only, create / settings / new link / off, the
// admin switch), Settings > Account > API tokens (created once, shown once, revoke), Settings > Integrations > Webhooks
// (add with validation, secret shown once, edit, log, remove), history lines "via API" / "via the public link", German.
// Starts its own container (start.sh) and sets up users and lists over the API.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DATA = process.argv[2];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (cookie, method, url, body) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cookie}, body: body === undefined ? undefined : JSON.stringify(body)});
  const t = await r.text(); try { return JSON.parse(t); } catch { return t; }
};
const set = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); el.dispatchEvent(new w.Event('change', {bubbles: true})); };
(async () => {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA]);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const {login} = require('./boot');
  const ca = await login('alice');
  await call(ca, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  const cb = await login('bob');
  const L = await call(ca, 'POST', '/api/lists', {name: 'Groceries', checklist: true});
  await call(ca, 'PUT', `/api/lists/${L.id}/members`, {user_id: 2, role: 'edit'});
  const mk = t => call(ca, 'POST', '/api/tasks', {list_id: L.id, ...t});
  const milk = await mk({title: 'Milk', due: new Date().toISOString().slice(0, 10), priority: 5});
  const bread = await mk({title: 'Bread'});
  const eggs = await mk({title: 'Eggs'});
  await call(ca, 'POST', `/api/tasks/${eggs.id}/complete`, {});

  // ---- checklist view
  let w = await boot({user: 'alice', hash: 'l/' + L.id}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  // 2.7.2 (#414): "Show completed at the bottom" is a list option; the rows are full tasks (date, priority)
  check(row(milk.id) && !row(milk.id).classList.contains('ck') && row(milk.id).querySelector('.dt') && row(milk.id).classList.contains('pr5'), 'rows are full tasks (2.7.2)');
  const done = () => d.querySelector('#view .ckdone');
  check(done() && /Done/.test(done().querySelector('.ghead').textContent) && done().querySelector('.ghead .c').textContent === '1', 'Done section with count');
  check(done().contains(row(eggs.id)) && row(eggs.id).querySelector('.ckback') && done().querySelector('[data-act="ck-uncheck"]') && done().querySelector('[data-act="ck-clear"]'),
    'done item with "back on the list" + header actions');
  click(w, row(milk.id).querySelector('[data-act="toggle"]')); await sleep(900);
  check(done().contains(row(milk.id)) && done().querySelector('.ghead .c').textContent === '2', 'ticking moves the item into Done');
  click(w, row(eggs.id).querySelector('.ckback')); await sleep(900);
  check(!done().contains(row(eggs.id)) && w.eval(`S.tasks.get(${eggs.id}).status`) === 0, 'back on the list');
  click(w, done().querySelector('[data-act="ck-uncheck"]')); await sleep(900);
  check(w.eval(`[...S.tasks.values()].filter(t => t.list_id === ${L.id} && t.status !== 0).length`) === 0 && /land here/.test(done().querySelector('.ghead').title), 'Uncheck all');  // 1.5.3: the hint is the heading's tooltip
  for (const id of [milk.id, bread.id]) { click(w, row(id).querySelector('[data-act="toggle"]')); await sleep(700); }
  click(w, done().querySelector('.ghead')); await sleep(200);
  check(!done().querySelector('.trow'), 'Done section collapses');
  click(w, done().querySelector('.ghead')); await sleep(200);
  click(w, done().querySelector('[data-act="ck-clear"]')); await sleep(900);
  check(!row(milk.id) && !row(bread.id) && row(eggs.id), 'Clear done: done items gone (trash)');
  check((await call(ca, 'GET', '/api/tasks?scope=trash')).tasks.filter(t => t.list_id !== L.id || true).some(t => t.title === 'Milk'), 'they are in the trash');
  // list dialog: switch + public link
  w.eval(`listModal(${L.id})`); await sleep(400);
  let md = d.querySelector('.modal');
  check(md.querySelector('#l-kind')?.value === 'list' && md.querySelector('#l-dab')?.checked && !md.querySelector('#l-dab').disabled, 'list dialog: List + "Show completed at the bottom" on (owner, 2.7.2)');
  // 2.6.0 (K12): the public link lives in the Share dialog
  md.remove(); w.eval(`shareModal(${L.id})`); await sleep(500);
  md = d.querySelector('.modal.shmodal');
  check(md && md.querySelector('#l-pub') && /Public link/.test(md.textContent), 'Share dialog: public link section');
  click(w, md.querySelector('[data-lp="save"]')); await sleep(700);
  const url = md.querySelector('#lp-url')?.value || '';
  check(/\/s\/[A-Za-z0-9_-]{32,}$/.test(url), 'create public link: URL shown ' + url);
  md.querySelector('#lp-mode').value = 'tick';
  click(w, md.querySelector('[data-lp="save"]')); await sleep(600);
  const k = (await call(ca, 'GET', `/api/lists/${L.id}/public-link`)).link;
  check(k.mode === 'tick' && k.url === url, 'link settings saved, same link');
  click(w, md.querySelector('[data-lp="regen"]')); await sleep(600);
  const url2 = md.querySelector('#lp-url').value;
  check(url2 !== url && /\/s\//.test(url2), 'new link');
  // tick one item through the public page -> history "Someone via the public link"
  const tp = url2.slice(url2.indexOf('/s/') + 1);
  await fetch(B + tp + '/tick', {method: 'POST', body: new URLSearchParams({task: String(eggs.id), to: 'done'}), redirect: 'manual'});
  click(w, md.querySelector('[data-lp="off"]')); await sleep(600);
  check(!md.querySelector('#lp-url') && md.querySelector('[data-lp="save"]') && (await call(ca, 'GET', `/api/lists/${L.id}/public-link`)).link === null, 'turn off');
  md.remove(); w.eval(`listModal(${L.id})`); await sleep(400); md = d.querySelector('.modal');
  md.querySelector('#l-dab').checked = false;
  md.querySelector('#l-dab').dispatchEvent(new w.Event('change', {bubbles: true}));  // 1.5.1: the dialog saves itself
  click(w, md.querySelector('[data-m="close"]')); await sleep(900);
  check(w.eval(`listById(${L.id}).checklist`) === 0 && !d.querySelector('#view .ckdone'), 'checklist mode off: normal list');
  w.eval(`openDetail(${eggs.id})`); await sleep(900);
  check(/Someone via the public link/.test(d.querySelector('#detail')?.textContent || ''), 'history: someone via the public link');
  w.eval('closeDetail()');
  // ---- API tokens (Settings > Account)
  w.eval(`settingsModal('account')`); await sleep(600);
  md = d.querySelector('.smodal');
  check(md.querySelector('#s-api-h') && /No tokens yet/.test(md.querySelector('#s-toks').textContent), 'account: API tokens section');
  click(w, md.querySelector('[data-tok="new"]')); await sleep(200);
  let tm = [...d.querySelectorAll('.modal')].pop();
  check(tm.querySelector('#tk-admin'), 'admin: admin-read option');
  set(w, tm.querySelector('#tk-name'), 'Home Assistant'); tm.querySelector('#tk-write').checked = true;
  click(w, tm.querySelector('[data-m="ok"]')); await sleep(800);
  const sm = [...d.querySelectorAll('.modal')].pop();
  const token = sm.querySelector('#sec-val')?.value || '';
  check(/^abk_[A-Za-z0-9_-]{43}$/.test(token) && /only this once/.test(sm.textContent), 'token shown once');
  const me = await (await fetch(B + 'api/v1/me', {headers: {Authorization: 'Bearer ' + token}})).json();
  check(me.username === 'alice' && me.token.scopes.join() === 'read,write', 'the shown token works');
  click(w, sm.querySelector('[data-m="close"]')); await sleep(300);
  check(/Home Assistant/.test(md.querySelector('#s-toks').textContent) && !md.querySelector('#s-toks').textContent.includes(token), 'token listed without the secret');
  await fetch(B + 'api/v1/tasks', {method: 'POST', headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/json'}, body: JSON.stringify({title: 'From HA'})});
  click(w, md.querySelector('[data-tok="del"]')); await sleep(700);
  check(/No tokens yet/.test(md.querySelector('#s-toks').textContent) && (await fetch(B + 'api/v1/me', {headers: {Authorization: 'Bearer ' + token}})).status === 401, 'revoke');
  // ---- webhooks (Settings > Integrations)
  click(w, md.querySelector('.snav [data-sec="integr"]')); await sleep(600);
  check(md.querySelector('#s-wh-h') && /No webhooks yet/.test(md.querySelector('#s-whs').textContent), 'integrations: webhooks section');
  click(w, md.querySelector('[data-wh="new"]')); await sleep(200);
  let wm = [...d.querySelectorAll('.modal')].pop();
  set(w, wm.querySelector('#wh-url'), 'http://example.com/hook');
  click(w, wm.querySelector('[data-m="ok"]')); await sleep(600);
  check(!wm.querySelector('#wh-err').hidden && /https/.test(wm.querySelector('#wh-err').textContent), 'http:// refused with a message');
  set(w, wm.querySelector('#wh-url'), 'https://hooks.example.com/kalmido'); set(w, wm.querySelector('#wh-name'), 'n8n');
  click(w, wm.querySelector('[data-m="ok"]')); await sleep(800);
  const ws = [...d.querySelectorAll('.modal')].pop();
  check(/^whsec_/.test(ws.querySelector('#sec-val')?.value || ''), 'signing secret shown once');
  click(w, ws.querySelector('[data-m="close"]')); await sleep(300);
  check(/n8n/.test(md.querySelector('#s-whs').textContent) && /2 events/.test(md.querySelector('#s-whs').textContent), 'webhook listed (default events)');
  click(w, md.querySelector('[data-wh="edit"]')); await sleep(200);
  wm = [...d.querySelectorAll('.modal')].pop();
  wm.querySelector('[data-whev="task.updated"]').checked = true;
  click(w, wm.querySelector('[data-m="ok"]')); await sleep(700);
  check(/3 events/.test(md.querySelector('#s-whs').textContent), 'edit events');
  click(w, md.querySelector('[data-wh="log"]')); await sleep(500);
  const lm = [...d.querySelectorAll('.modal')].pop();
  check(/Delivery log/.test(lm.textContent), 'delivery log dialog');
  lm.remove();
  click(w, md.querySelector('[data-wh="del"]')); await sleep(700);
  check(/No webhooks yet/.test(md.querySelector('#s-whs').textContent), 'remove webhook');
  // ---- admin switch: public links off -> no section in the list dialog
  click(w, md.querySelector('.snav [data-sec="users"]')); await sleep(400);
  const pls = md.querySelector('#s-publinks');
  check(pls && pls.checked && /Allowed internal hosts/.test(md.textContent), 'whole server: public links switch + internal hosts');
  pls.checked = false; pls.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  check(w.eval('S.publicLinks') === false && (await call(ca, 'GET', '/api/about')).public_links === false, 'switch off');
  md.remove();
  w.eval(`shareModal(${L.id})`); await sleep(300);
  check(d.querySelector('.modal.shmodal') && !d.querySelector('.modal #l-pub'), 'switched off: no public link section');
  d.querySelector('.modal').remove();
  await call(ca, 'PATCH', '/api/admin/settings', {public_links: true});
  // "via API" in the history
  const ha = (await call(ca, 'GET', '/api/state')).tasks.find(t => t.title === 'From HA');
  w.close();
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`openDetail(${ha.id})`); await sleep(900);
  check(d.querySelector('#detail .via') && /via API/.test(d.querySelector('#detail').textContent), 'history: "via API"');
  w.close();
  // ---- bob (member): no public link section, switch read-only
  w = await boot({user: 'bob', hash: 'l/' + L.id}); d = w.document;
  w.eval(`listModal(${L.id})`); await sleep(400);
  md = d.querySelector('.modal');
  check(md.querySelector('#l-kind')?.disabled && !md.querySelector('#l-pub'), 'member: type selector disabled, no public link section');
  md.remove(); w.close();
  // ---- German
  await call(ca, 'PATCH', '/api/lists/' + L.id, {checklist: true});
  await call(ca, 'PATCH', '/api/settings', {lang: 'de'});
  await call(ca, 'POST', `/api/tasks/${eggs.id}/complete`, {});
  w = await boot({user: 'alice', hash: 'l/' + L.id}); d = w.document;
  check(/Erledigt/.test(d.querySelector('#view .ckdone .ghead')?.textContent || '') && d.querySelector('[data-act="ck-uncheck"]')?.textContent.includes('Alle zurücksetzen'), 'German: Done section');
  w.eval(`listModal(${L.id})`); await sleep(400);
  check(/Liste/.test(d.querySelector('.modal #l-kind').textContent) && /Projekt/.test(d.querySelector('.modal #l-kind').textContent) && /Erledigte unten zeigen/.test(d.querySelector('.modal').textContent) && /Teilen…/.test(d.querySelector('.modal').textContent), 'German: list dialog');
  d.querySelector('.modal').remove();
  w.eval(`shareModal(${L.id})`); await sleep(400);
  check(/Öffentlicher Link/.test(d.querySelector('.modal.shmodal')?.textContent || ''), 'German: Share dialog');
  d.querySelector('.modal').remove();
  w.eval(`settingsModal('account')`); await sleep(500);
  check(/API-Tokens/.test(d.querySelector('.smodal').textContent), 'German: API tokens');
  w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
