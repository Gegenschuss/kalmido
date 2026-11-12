// 2.1045.0 C (#5822) the dialog "Edit agent": "Sees now" + "Share…" + the hint at a permission without a share. Own container, jsdom.
// kalmido-suite: fresh
// Acceptance of the task: an agent with "Read knowledge pages" and nothing shared -> the hint is visible under the permissions;
// "Share…" there -> knowledge folder with Edit -> a row with the folder's name appears under "Sees now", the hint is gone, and
// the agent reads the page through its API. Ending the share in the row (confirmed) takes the row away, the hint comes back
// and the agent reads nothing any more. The sentence above the permissions is there; the office gets no hint.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 8000) => { for (let t = 0; t < ms; t += 100) { const v = await f(); if (v) return v; await sleep(100); } return f(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const visible = el => !!el && !el.hidden && !el.closest('[hidden]');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'wiki,files,collab,comments,agents'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  // her own personal agent (private) with "Read / Write knowledge pages", nothing shared
  const ag = await call(CA, 'POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper', owner_id: me.id, org_id: null,
    scopes: ['read', 'tasks:write', 'wiki:read', 'wiki:write', 'files:read', 'files:write']});
  check(ag.http === 201 && ag.token, 'setup: the personal agent ' + ag.http);
  const pg = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: 'Manual/Start', body: 'Press the green button'});
  check(pg.http === 201, 'setup: a private knowledge page ' + pg.http);
  const folder = ((await call(CA, 'GET', '/api/wiki?space=private')).folders || []).find(f => f.path === 'Manual');
  check(folder, 'setup: the folder "Manual"');
  const agentRead = async () => (await fetch(B + `api/v1/wiki/pages/${pg.id}`, {headers: {Authorization: 'Bearer ' + ag.token}})).status;
  check(await agentRead() === 404, 'the agent reads nothing before a share');

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(typeof w.ags_mount === 'function', 'agentsees.js is loaded with the agent dialog');
  await w.eval(`api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; agModal(j.agents.find(a => a.id === ${ag.id}), () => {}); })`);
  let md = await until(() => lastModal(d)?.querySelector('#ag-sees h4') && lastModal(d));
  check(md, 'the dialog "Edit agent" shows the section');
  check(/Sees now/.test(md?.querySelector('#ag-sees h4')?.textContent || ''), 'heading "Sees now"');
  check(/Permissions decide what the agent may do, shares decide where\./.test(md?.querySelector('.agsintro')?.textContent || '') &&
    md.querySelector('.agsintro').compareDocumentPosition(md.querySelector('.scopes')) & 4, 'the sentence stands above the permissions');
  check(/Nothing shared yet/.test(md?.querySelector('#ag-sees')?.textContent || ''), 'the empty list says so');
  const hint = () => md.querySelector('#ag-seeshint [data-ags-hint="wiki"]');
  check(visible(hint()) && /Knowledge pages: nothing shared yet/.test(hint().textContent), 'the hint at "Read knowledge pages" is visible');
  check(!md.querySelector('#ag-seeshint [data-ags-hint="office"]'), 'no hint for the office');
  // the hint follows the switches: wiki off -> gone, on again -> back
  const sw = s => md.querySelector(`.scopes [data-scope="${s}"]`);
  for (const s of ['wiki:read', 'wiki:write']) { sw(s).checked = false; sw(s).dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(!hint(), 'without the knowledge permissions no hint');
  for (const s of ['wiki:read', 'wiki:write']) { sw(s).checked = true; sw(s).dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(hint(), 'the hint is back with the permission');

  // "Share…" in the hint -> the picker, knowledge folder preselected, the entire area first
  click(w, hint().querySelector('[data-ags="share"]'));
  const pk = await until(() => lastModal(d)?.querySelector('#ags-t') && lastModal(d));
  check(pk && pk.querySelector('#ags-k').value === 'wiki', 'the picker opens with "Knowledge folder"');
  const opts = [...(pk?.querySelectorAll('#ags-t option') || [])];
  check(opts[0] && /Entire knowledge area/.test(opts[0].textContent), 'first choice: "Entire knowledge area" ' + opts.map(o => o.textContent).join('|'));
  const fo = opts.find(o => o.value === `n:${folder?.id}`);
  check(fo && fo.textContent === 'Manual', 'the folder "Manual" is offered');
  pk.querySelector('#ags-t').value = `n:${folder?.id}`;
  pk.querySelector('#ags-r').value = 'edit';
  click(w, pk.querySelector('[data-agsm="ok"]'));
  const row = await until(() => [...md.querySelectorAll('#ag-sees .ags-i')].find(x => /Manual/.test(x.textContent)));
  check(row && /can edit/.test(row.textContent), 'a row "Manual · can edit" under "Sees now" ' + (row?.textContent || md.querySelector('#ag-sees')?.textContent));
  check(!d.querySelector('#ags-t'), 'the picker closed');
  check(await until(() => !hint()), 'the hint is gone');
  check(await agentRead() === 200, 'the agent reads the page through its API');

  // ending the share in the row
  click(w, row.querySelector('[data-ags="rm"]'));
  const cf = await until(() => lastModal(d)?.querySelector('[data-cd="yes"]') && lastModal(d));
  check(cf && /End the share of Manual\?/.test(cf.textContent), 'asked before the share ends');
  click(w, cf.querySelector('[data-cd="yes"]'));
  check(await until(() => ![...md.querySelectorAll('#ag-sees .ags-i')].some(x => /Manual/.test(x.textContent))), 'the row is gone');
  check(await until(() => hint()), 'the hint is back');
  check(await agentRead() === 404, 'the agent reads the page no more');

  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
