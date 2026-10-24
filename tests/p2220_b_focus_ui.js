// 2.220.0 B UI tests (jsdom, own container via start.sh), computer and phone width:
// - #2809: Tab in an open menu closes it and puts the focus back on the button that opened it (the Tab goes on from there,
//   not to the page's end); "New project" focuses its first entry like the other menus; the News window keeps the focus
//   inside when its list arrives (it fell to the page); "Load older messages" in the agent chat keeps the focus in the chat
//   (on the button while there is more, then on the oldest new message)
// - #2811 (menus): every menu has a name (aria-label from the title / the button that opened it)
// - #2813: with 300 messages loaded a new message only adds its row: the old nodes stay (no compare, no parse), an edited
//   message still changes
// freelancer-matrix: n/a (no new route; alice has no organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ALL = 'cal,collab,agents,comments,progress';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  await call('POST', '/api/tasks', {title: 'A task', list_id: P});
  // paced: the API answers 429 to a burst; one more try after a pause
  const post1 = i => i % 2 ? call('POST', `/api/agents/${AG}/chat`, {body: `Question ${i}`}) : tcall('POST', `/agent/chats/${ME}`, TOK, {body: `Answer ${i}`});
  const post = async i => { for (let k = 0; k < 6; k++) { const r = await post1(i); if (r.status !== 429) return r; await sleep(2000); } };
  for (let i = 1; i <= 75; i++) await post(i);

  for (const mobile of [true, false]) {  // the phone first: the computer then adds messages up to 300
    const tag = mobile ? 'phone' : 'computer';
    const w = await boot({user: 'alice', mobile, hash: 'l/' + P}), d = w.document;
    await sleep(300);

    // ---- #2809 / #2811: menus
    if (mobile) w.eval('sideDrawerOpen()');
    const nb = d.querySelector('#side [data-act="list-new"]');
    check(!!nb, `${tag}: the "New project" button`);
    nb.focus(); click(w, nb); await sleep(60);
    let m = d.querySelector('#pop:not(.hidden) [role="menu"]');
    check(m && d.activeElement === m.querySelector('[role="menuitem"]'), `${tag}: #2809 "New project" focuses its first entry (${d.activeElement?.textContent?.trim()})`);
    check(m && (m.getAttribute('aria-label') || m.getAttribute('aria-labelledby')), `${tag}: #2811 the menu has a name (${m?.getAttribute('aria-label')})`);
    key(w, d.activeElement, 'Tab'); await sleep(30);
    check(d.querySelector('#pop').classList.contains('hidden') && d.activeElement === nb, `${tag}: #2809 Tab closes the menu, the focus is on its button again (${d.activeElement?.outerHTML?.slice(0, 80)})`);
    // any menu: its name comes from the button (aria-label), Shift+Tab the same
    const t = d.createElement('button'); t.setAttribute('aria-label', 'More actions'); t.id = 'p2220b-trg'; d.querySelector('#main').appendChild(t);
    t.focus(); w.eval(`menu(document.getElementById('p2220b-trg'), [{label: 'One', fn: () => {}}, {label: 'Two', fn: () => {}}])`); await sleep(30);
    m = d.querySelector('#pop:not(.hidden) [role="menu"]');
    check(m && m.getAttribute('aria-label') === 'More actions' && d.activeElement?.textContent.includes('One'), `${tag}: #2811 the name of the button, the first entry has the focus`);
    key(w, d.activeElement, 'Tab', {shiftKey: true}); await sleep(30);
    check(d.querySelector('#pop').classList.contains('hidden') && d.activeElement === t, `${tag}: #2809 Shift+Tab: closed, back on its button`);
    w.eval(`menu(document.getElementById('p2220b-trg'), [{label: 'One', fn: () => {}}])`); await sleep(30);
    key(w, d.activeElement, 'Escape'); await sleep(30);
    check(d.querySelector('#pop').classList.contains('hidden') && d.activeElement === t, `${tag}: Esc as before: closed, back on its button`);
    t.remove();
    if (mobile) w.eval('closeSide()');

    // ---- #2809: the News window keeps the focus inside when its list arrives
    const bell = d.querySelector('#kbar .bell, #top .bell');
    if (bell) {
      bell.focus(); w.eval('S.nf.items = null; S.nf.sig = "x"'); click(w, bell);
      await sleep(80);
      const in0 = !!d.activeElement?.closest?.('#pop .bpop');
      await until(() => !!d.querySelector('#pop .bpop') && w.eval('!!S.nf.items')); await sleep(200);
      check(in0 && d.activeElement?.closest?.('#pop .bpop') && d.activeElement !== d.body, `${tag}: #2809 the News window has the focus and keeps it when its list arrives (${in0}, ${d.activeElement?.outerHTML?.slice(0, 80)})`);
      key(w, d.activeElement, 'Escape'); await sleep(30);
      if (!d.querySelector('#pop').classList.contains('hidden')) w.eval('closePop()');
    } else check(mobile, `${tag}: the bell`);

    // ---- #2809: "Load older messages" keeps the focus in the chat
    if (mobile) { w.location.hash = 'agents/' + AG; await sleep(400); } else w.eval(`chatOpen(${AG})`);
    await until(() => d.querySelectorAll('#chat-msgs .cmsg').length >= 30);
    let older = d.querySelector('#chat-msgs [data-act="chat-older"]');
    check(older && d.querySelectorAll('#chat-msgs .cmsg').length === 30, `${tag}: 30 messages, "Load older messages"`);
    older.focus(); click(w, older);
    await until(() => d.querySelectorAll('#chat-msgs .cmsg').length === 60); await sleep(100);
    older = d.querySelector('#chat-msgs [data-act="chat-older"]');
    check(older && d.activeElement === older, `${tag}: #2809 more to load: the focus is on the button again (${d.activeElement?.outerHTML?.slice(0, 80)})`);
    click(w, older);
    await until(() => d.querySelectorAll('#chat-msgs .cmsg').length === 75); await sleep(100);
    const first = d.querySelector('#chat-msgs .cmsg');
    check(!d.querySelector('#chat-msgs [data-act="chat-older"]') && d.activeElement === first && first.querySelector('.cbub')?.textContent.trim() === 'Question 1', `${tag}: #2809 all loaded: the focus is on the oldest new message (${d.activeElement?.outerHTML?.slice(0, 80)} / ${d.activeElement === first} / ${first?.textContent?.slice(0, 40)})`);
    d.querySelector('#chat-in')?.focus();
    check(!first.hasAttribute('tabindex'), `${tag}: the message is not a tab stop afterwards`);

    if (!mobile) {
      // ---- #2813: 300 messages loaded, a new one only adds its row
      for (let i = 76; i <= 300; i++) { await post(i); if (i % 40 === 0) await sleep(1500); }  // paced (the API's rate limit)
      await w.eval('chatLoad()'); await sleep(300);
      for (let i = 0; i < 12 && d.querySelector('#chat-msgs [data-act="chat-older"]'); i++) {
        const n0 = d.querySelectorAll('#chat-msgs .cmsg').length; click(w, d.querySelector('#chat-msgs [data-act="chat-older"]'));
        await until(() => d.querySelectorAll('#chat-msgs .cmsg').length > n0); await sleep(50);
      }
      const box = d.querySelector('#chat-msgs'), rows0 = [...box.querySelectorAll('.cmsg')];
      check(rows0.length >= 250 && !d.querySelector('#chat-msgs [data-act="chat-older"]'), `${tag}: #2813 all (about 300) messages loaded (${rows0.length})`);
      const seg0 = new Set(box._rows.keys());
      let cmp = 0; const orig = w.Node.prototype.isEqualNode;
      w.Node.prototype.isEqualNode = function (n) { if (this.parentNode === box) cmp++; return orig.call(this, n); };
      for (let k = 0; k < 6 && (await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'The newest answer'})).status === 429; k++) await sleep(2000);
      await w.eval('chatLoad()'); await until(() => box.querySelectorAll('.cmsg').length > rows0.length);
      await sleep(200);
      const rows1 = [...box.querySelectorAll('.cmsg')];
      check(rows1.length === rows0.length + 1 && rows0.every(n => n.isConnected) && rows0.every((n, i) => rows1[i] === n), `${tag}: #2813 a new message keeps the 300 old nodes (${rows1.length})`);
      const seg1 = [...box._rows.keys()].filter(h => !seg0.has(h));
      if (cmp >= 20) console.log('changed rows:', seg1.length, JSON.stringify(seg1.slice(0, 2)), JSON.stringify([...seg0].slice(1, 3)));
      check(cmp < 20, `${tag}: #2813 the unchanged rows are not compared again (${cmp} compares)`);
      w.Node.prototype.isEqualNode = orig;
      // an edited message still changes (my message 299 -> the text)
      const mine = rows0.find(n => n.querySelector('.cbub')?.textContent.trim() === 'Question 299'), mid = +mine.dataset.mid.split(':')[1];
      check((await call('PATCH', `/api/agents/${AG}/chat/${mid}`, {body: 'Question 299 changed'})).status === 200, 'edit my message');
      await w.eval('load().then(() => { render(); return chatLoad(); })'); await sleep(400);
      check(/Question 299 changed/.test(box.textContent) && rows0[0].isConnected, `${tag}: #2813 an edited message shows its new text, the others stay`);
    }
  }

  console.log(`p2220_b_focus_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
