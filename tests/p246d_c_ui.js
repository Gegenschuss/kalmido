// 2.46.4 part C UI tests (#1737 #1755), own container (start.sh). jsdom, invented data only:
// - #1737 the Share dialogs of a list, an address book, a calendar and a folder say "Belongs to: <organisation> (organisation)" /
//   "Private" with the sentence below, people outside the organisation are greyed out with the reason, a mirrored address book is
//   private even when it carries an organisation, the "Change workspace" link only where there is a way (not for a mirrored book)
// - #1755 the Undo message is one line (class one, cut with an ellipsis), sits above the keyboard / the lowest input field,
//   never at the top, also over a tall sheet
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,events,comments,collab,contacts';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol Carter', password: 'password123'})).id;
  const BCK = await login('bob');  // Bob shares a private list with Alice: a connection, so Alice sees him (outside the organisation)
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const LB = (await call('POST', '/api/lists', {name: 'Bob list', org_id: null}, BCK)).id;
  const PM = await call('PUT', `/api/lists/${LB}/members`, {user_id: ME, role: 'edit'}, BCK); check(PM.status === 200, 'Bob shares a list with Alice ' + JSON.stringify(PM).slice(0, 200));
  // the organisation comes after the connection (before the first organisation everybody sees everybody)
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Acme Works'})).id;
  await call('PATCH', `/api/admin/orgs/${ORG}`, {members: [ME, CAR]});
  const LO = (await call('POST', '/api/lists', {name: 'Org plan', org_id: ORG})).id;
  const LP = (await call('POST', '/api/lists', {name: 'Own plan', org_id: null})).id;
  const BO = (await call('POST', '/api/books', {name: 'Org book', org_id: ORG})).id;
  const BP = (await call('POST', '/api/books', {name: 'Own book', org_id: null})).id;
  const COR = await call('POST', '/api/evcals', {name: 'Org cal', org_id: ORG}), CO = COR.id;
  check(ORG && LO && BO && CO, 'the objects were created ' + JSON.stringify({ORG, LO, BO, COR}));

  const w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side'));
  check(w.eval('wsOn()') === true, 'the person has a workspace (wsOn)');
  const vis = () => [...d.querySelectorAll('.modal')].filter(m => m.style.display !== 'none');
  const closeAll = () => { d.querySelectorAll('.modal').forEach(m => m.remove()); };
  const line = m => m?.querySelector('.shws .shwsn')?.textContent || '';
  const hint = m => m?.querySelector('.shws .shwsh')?.textContent || '';

  // ================= list
  w.eval(`shareModal(${LO})`);
  let md = await until(() => d.querySelector('.modal .shws .shwsn')?.closest('.modal'));
  check(line(md) === 'Belongs to: Acme Works (organisation)', '#1737 list (organisation): the line: ' + line(md));
  check(/Only members of the organisation can be invited/.test(hint(md)), '#1737 list (organisation): the sentence');
  check(!!md.querySelector('.shws [data-shws]'), '#1737 list (organisation): the "Change workspace" link is there for the owner');
  const sel = await until(() => md.querySelector('#l-adduser'));
  const opt = n => [...sel.options].find(o => o.textContent.startsWith(n));
  check(opt('Bob') && opt('Bob').disabled && /Not in the organisation/.test(opt('Bob').textContent), '#1737 list: a person outside the organisation is greyed out with the reason ' + [...sel.options].map(o => o.textContent + (o.disabled ? '(d)' : '')).join('|'));
  check(opt('Carol') && !opt('Carol').disabled && !/Not in/.test(opt('Carol').textContent), '#1737 list: a member is selectable');
  closeAll();
  w.eval(`shareModal(${LP})`);
  md = await until(() => d.querySelector('.modal .shws .shwsn')?.closest('.modal'));
  check(line(md) === 'Belongs to: Private', '#1737 list (private): the line: ' + line(md));
  check(hint(md) === 'Only people you explicitly invite see it.', '#1737 list (private): the sentence');
  const sel2 = await until(() => md.querySelector('#l-adduser'));
  check([...sel2.options].filter(o => o.value).every(o => !o.disabled), '#1737 list (private): nobody is greyed out');
  closeAll();

  // ================= address book
  w.eval(`S.books = (S.books || []); ctShareModal(S.books.find(b => b.id === ${BO}), [{id: ${BOB}, display_name: 'Bob Baker', orgs: []}, {id: ${CAR}, display_name: 'Carol Carter', orgs: [${ORG}]}], new Map(), () => {})`);
  md = await until(() => d.querySelector('.modal .shws .shwsn')?.closest('.modal'));
  check(line(md) === 'Belongs to: Acme Works (organisation)', '#1737 book (organisation): the line: ' + line(md));
  const bs = md.querySelector('#cbs-user');
  check([...bs.options].find(o => /Bob/.test(o.textContent)).disabled && /Not in the organisation/.test(bs.textContent), '#1737 book: Bob is greyed out with the reason');
  check(bs.selectedOptions[0] && !bs.selectedOptions[0].disabled && /Carol/.test(bs.selectedOptions[0].textContent), '#1737 book: the preselected person is a selectable one');
  check(!!md.querySelector('.shws [data-shws]'), '#1737 book: the link is there');
  closeAll();
  // a mirrored book is private even when it carries an organisation
  w.eval(`ctShareModal({id: 99999, name: 'Mirror', org_id: ${ORG}, imported: true, members: []}, [{id: ${BOB}, display_name: 'Bob Baker', orgs: []}], new Map(), () => {})`);
  md = await until(() => d.querySelector('.modal .shws .shwsn')?.closest('.modal'));
  check(line(md) === 'Belongs to: Private', '#1737 book (mirrored): shows Private: ' + line(md));
  check(!md.querySelector('.shws [data-shws]') && !md.querySelector('#cbs-user option:disabled'), '#1737 book (mirrored): no link, nobody greyed out');
  closeAll();

  // ================= calendar
  w.eval(`evShareModal({id: ${CO}, name: 'Org cal', org_id: ${ORG}, members: []}, [{id: ${BOB}, display_name: 'Bob Baker', orgs: []}, {id: ${CAR}, display_name: 'Carol Carter', orgs: [${ORG}]}], () => {})`);
  md = await until(() => d.querySelector('.modal .shws .shwsn')?.closest('.modal'));
  check(line(md) === 'Belongs to: Acme Works (organisation)', '#1737 calendar: the line: ' + line(md));
  check([...md.querySelectorAll('#evs-user option')].find(o => /Bob/.test(o.textContent)).disabled, '#1737 calendar: Bob greyed out');
  closeAll();

  // ================= folder
  await call('PATCH', `/api/lists/${LO}`, {folder: 'Team'});
  await w.eval('load()'); w.eval('render()');
  w.eval(`folderShareModal('Team')`);
  md = await until(() => d.querySelector('.modal.fshmodal #fsh-ws .shwsn')?.closest('.modal'));
  check(md && line(md) === 'Belongs to: Acme Works (organisation)', '#1737 folder: the line: ' + line(md));
  const fs = await until(() => md.querySelector('#fp-user'));
  check(fs && [...fs.options].find(o => /Bob/.test(o.textContent))?.disabled, '#1737 folder: Bob greyed out ' + (fs ? [...fs.options].map(o => o.textContent + (o.disabled ? '(d)' : '')).join('|') : 'no select'));
  closeAll();

  // ================= #1755 the toast
  w.eval(`toast('A very long task name that does not fit into one line on a small phone screen at all', () => {})`);
  const t = d.querySelector('#toast');
  check(t.classList.contains('one') && !t.classList.contains('hidden'), '#1755: the Undo message is a one-line toast');
  check(t.querySelector('button')?.textContent === 'Undo' && /does not fit/.test(t.title), '#1755: the button stays, the full text is the title');
  w.eval(`toast('Plain note')`);
  check(!t.classList.contains('one') && t.title === '', '#1755: a plain message is not cut');
  // geometry stubs: a 360x520 window, keyboard up to 300, a comment field at 240-280
  w.eval(`(() => {
    Object.defineProperty(window, 'innerHeight', {value: 520, configurable: true});
    window.__vv = {offsetTop: 0, height: 520};
    Object.defineProperty(window, 'visualViewport', {value: window.__vv, configurable: true});
    window.kbReal = () => window.__vv.height < 520 - 120;
    const rect = (top, h) => ({top, bottom: top + h, left: 0, right: 300, width: 300, height: h});
    window.__ci = document.createElement('textarea'); window.__ci.id = 'zz-comment'; document.body.appendChild(window.__ci);
    Object.defineProperty(window.__ci, 'offsetWidth', {value: 300});
    window.__ci.getBoundingClientRect = () => rect(240, 40);
  })()`);
  const bottom = () => parseInt(t.style.bottom || '-1', 10);
  w.eval(`__vv.height = 300; toast('Done', () => {})`);
  check(bottom() === 520 - 240 + 12 && !t.classList.contains('totop'), '#1755: keyboard open: above the comment field, not at the top: bottom ' + t.style.bottom);
  w.eval(`__ci.getBoundingClientRect = () => ({top: 100, bottom: 140, left: 0, right: 300, width: 300, height: 40}); toast('Done', () => {})`);
  check(bottom() === 520 - 300 + 12, '#1755: keyboard open, only a field in the upper part: right above the keyboard: bottom ' + t.style.bottom);
  w.eval(`__vv.height = 520; toast('Done', () => {})`);
  check(!t.classList.contains('totop') && bottom() !== 0, '#1755: no keyboard: still never at the top');
  w.eval(`window.__ci.remove()`);

  w.close();
  console.log(`p246d_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(2); });
