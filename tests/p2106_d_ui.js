// 2.153.0 UI tests of part D (#2031: let an agent draft the answer to a document; own container, start.sh). jsdom:
// - the slot at a document shared with an agent (both office switches on): the button "Let an agent draft the answer"
// - a press: the dialog names the agent, a note; Ask the agent -> the toast, the event letter_draft_requested with the note
// - a document not shared with the agent: no button, the hint to share it first
// The slot is rendered by lta_docBtn (letterdoc.js ltd_slot shows it in the document's detail); here it is put on the page directly.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2106D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined});
  return {...(await r.json().catch(() => ({}))), http: r.status};
};
const until = async (fn, n = 40, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const upload = async (name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const j = await r.json().catch(() => ({}));
  return (j.ids || [])[0];
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,files,docs'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call('POST', '/api/my/agents', {username: 'letterbot', display_name: 'Letterbot', scopes: ['read', 'office', 'files:read']});
  check(ag.http === 201, 'setup: a personal agent ' + ag.http);
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('GET', '/api/office/settings');
  check((await call('PUT', '/api/office/settings', {agents_read: 1})).http === 200, 'setup: the privacy switch of the personal office');
  check((await call('PATCH', `/api/office/agents/${ag.id}`, {office_drafts: true})).http === 200, "setup: the agent's office switch");
  const D1 = await upload('bescheid.txt', 'Beispiel Krankenkasse\nBeitragsbescheid 2027\nWiderspruch binnen eines Monats');
  const D2 = await upload('werbung.txt', 'Beispiel Verlag\nAngebot Zeitschrift');
  check(D1 && D2, 'setup: two documents ' + D1 + ' ' + D2);
  check((await call('POST', `/api/files/nodes/${D1}/shares`, {agent_id: ag.id, role: 'view'})).http === 201, 'setup: the first document shared with the agent');

  const w = await boot({user: 'alice'}), d = w.document;  // every bundle loaded (boot without lazy)
  check(await until(() => w.eval("typeof lta_docBtn === 'function'")), 'the documents bundle brings lta_docBtn');
  await w.eval(`document.body.insertAdjacentHTML('beforeend', '<div id="t-lta">' + lta_docBtn({id: ${D1}}) + '</div>')`);
  const btn = await until(() => d.querySelector('#t-lta [data-lta="ask"]'));
  check(btn && /Let an agent draft the answer/.test(btn.textContent), '#2031: the button at a shared document');
  click(w, btn);
  const md = await until(() => d.querySelector('.cdlg'));
  check(md && /Letterbot drafts an answer to this document/.test(md.textContent) && md.querySelector('#lta-note') && !md.querySelector('#lta-ag'),
    '#2031: the dialog names the one agent, a note field, no choice');
  if (md) {
    md.querySelector('#lta-note').value = 'Bitte sachlich bleiben.';
    click(w, md.querySelector('[data-cd="yes"]'));
  }
  check(await until(() => /Letterbot was asked to draft an answer/.test(d.querySelector('#toast, .toast')?.textContent || ''), 40), '#2031: the toast');
  const ev = await until(async () => { const r = await call('GET', '/api/v1/agent/events?since=0&limit=200', null, null, AGH); return (r.data || []).find(x => x.event === 'letter_draft_requested'); }, 30, 300);
  check(ev && ev.data.node_id === D1 && ev.data.note === 'Bitte sachlich bleiben.', '#2031: the event with the note ' + JSON.stringify(ev?.data || null).slice(0, 200));

  // a document not shared with the agent: the hint, no button
  await w.eval(`document.getElementById('t-lta').remove(); document.body.insertAdjacentHTML('beforeend', '<div id="t-lta">' + lta_docBtn({id: ${D2}}) + '</div>')`);
  const hint = await until(() => d.querySelector('#t-lta .lta-hint'));
  check(hint && /once you share the document/.test(hint.textContent) && !d.querySelector('#t-lta [data-lta="ask"]'), '#2031: not shared: the hint, no button');
  w.close();

  console.log(`p2106_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
