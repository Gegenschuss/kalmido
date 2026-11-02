// kalmido-suite: fresh
// 2.489.0 B (#2664) UI tests: the words of the sidebar and the menus (decisions #2636 #2646 #2647 #2654 of 21.10.2026).
// Own container (start.sh), jsdom, invented data only, a person without an organisation (own office).
// freelancer-matrix: office
// - #2647: the address book is an entry of its own in the office's panel (group book, no heading), not a point of Sell;
//   on a phone's office start page the same, without a heading
// - #2646: the office's point gendocs and the client card block say Letters & contracts
// - #2636: the sidebar group "Conversations" is gone: what stays there is called People (Settings > Appearance > Sidebar);
//   the More menu of the tab bar has no Conversations heading
// - #2654: Settings has no section Assistant of its own; the built-in assistant is a tab of Agents (AI_SUBS)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']}, CK);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'clients,office,contacts,docs', workspace: 'private'}, CK);

  // ================= computer: the office's panel
  let w = await boot({user: 'alice', hash: 'office/offers'}), d = w.document;
  const pts = () => [...d.querySelectorAll('#side .sbbp[data-ofmg]')].map(g => g.dataset.ofmg + ':' + [...g.querySelectorAll('[data-ofm]')].map(b => b.dataset.ofm).join('+')).join(' ');
  check(await until(() => d.querySelector('#side [data-ofmg="book"] [data-ofm="contacts"]') && d.querySelector('#side [data-ofm="gendocs"]')), '#2647: the address book stands in the panel ' + pts());
  const book = d.querySelector('#side [data-ofmg="book"]'), sell = d.querySelector('#side [data-ofmg="sell"]');
  check(book && !book.querySelector('.shead') && book.querySelectorAll('[data-ofm]').length === 1, '#2647: an entry of its own, no heading');
  check(sell && !sell.querySelector('[data-ofm="contacts"]'), '#2647: not a point of Sell any more ' + pts());
  check(/^Address book$/.test(book?.querySelector('[data-ofm="contacts"] .n')?.textContent || ''), '#2647: it says Address book');
  check(/^Letters & contracts$/.test(d.querySelector('#side [data-ofm="gendocs"] .n')?.textContent || ''), '#2646: gendocs says Letters & contracts: ' + d.querySelector('#side [data-ofm="gendocs"]')?.textContent);
  check(w.eval("tr(LY_CL_BLOCKS.find(b => b[0] === 'gendocs')[1])") === 'Letters & contracts', '#2646: the client card block too');
  // the address book page keeps its point lit in the panel
  w.location.hash = '#contacts';
  check(await until(() => d.querySelector('#side [data-ofmg="book"] [data-ofm="contacts"][aria-current="page"]')), '#2647: on its page the entry is the open one');

  // #2636: the sidebar settings name the group People, no Conversations
  w.eval("settingsModal('sidebar')");
  check(await until(() => d.querySelector('#s-sidebar [data-sideg="team"]')), 'the sidebar settings are drawn');
  const tn = d.querySelector('#s-sidebar [data-sideg="team"] > span')?.textContent || '';
  check(tn === 'People' && !/Conversations/.test(d.querySelector('#s-sidebar')?.textContent || ''), '#2636: the group is called People: ' + tn);
  // #2654: no section Assistant, the built-in assistant is a tab of Agents
  check(!d.querySelector('.smodal .snav [data-sec="assistant"]') && w.eval("!SET_SECS.some(s => s[0] === 'assistant') && AI_SUBS.some(s => s[0] === 'assistant')"), '#2654: the assistant is a tab of Agents, no section');
  d.querySelector('.smodal')?.closest('.modal')?.remove(); d.querySelector('.smodal')?.remove();
  // #2636: the More menu of the tab bar has no heading Conversations
  w.eval(`tabsMore(document.querySelector('#top h1') || document.body)`);
  check(await until(() => d.querySelector('#pop [role="menuitem"]')), 'More opens');
  const mh = [...d.querySelectorAll('#pop .mgh')].map(h => h.textContent);
  check(!mh.includes('Conversations') && !mh.includes('People'), '#2636: More without Conversations: ' + mh.join('|'));
  w.eval('closePop()');
  w.close();

  // ================= phone: the office's start page
  w = await boot({user: 'alice', hash: 'office/start', mobile: true}); d = w.document;
  check(await until(() => d.querySelector('#view .ofmstart .oflg[data-ofmg="book"] [data-ofm="contacts"]')), '#2647 phone: the address book on the start page');
  const pb = d.querySelector('#view .oflg[data-ofmg="book"]');
  check(pb && !pb.querySelector('h3') && !d.querySelector('#view .oflg[data-ofmg="sell"] [data-ofm="contacts"]'), '#2647 phone: without a heading, not under Sell');
  check(/Letters & contracts/.test(d.querySelector('#view .oflg [data-ofm="gendocs"]')?.textContent || ''), '#2646 phone: Letters & contracts');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
