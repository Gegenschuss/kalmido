// 2.940.0 UI test, part A: a calm view without jumps (rule 08.11.2026) - #5225, #5226, #5601. Own container (start.sh),
// kalmido-suite: fresh
// Firefox (real layout). Alice works without an organisation (freelancer-matrix: search, agents, docs). Invented data only.
//  #5225 Search on the desktop: opening Search puts the caret into its field; after that a redraw (live) never takes the focus
//        back to the field, and the hit read stays under the eye. Chat windows in the panel: a third window rebuilds the
//        panel - the window read higher up keeps its place (the message read stays at its height), the one at its end stays
//        at its end, the new one opens at its end.
//  #5226 A notice bar that the server sends while Alice reads in the middle of a list does not push the list: the row read
//        keeps its screen position (+-1 px), the bar's text is in sight above; hiding it by hand works. On the desktop and on
//        a phone (#view is the scrolling box there too).
//  #5601 Document view with 40 documents: a click on a small picture in sight in the left strip moves only the mark - the
//        strip's scroll and the clicked picture's place stay; leafing with the arrow key past the strip's edge brings the
//        open document into sight, a step inside the visible part does not scroll the strip.
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2940_a_ruhe', check, shots: 'P2940A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(h.Authorization ? {} : {Cookie: CK})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
// a small picture of its own per document (the server keeps one copy of equal bytes)
function png(w, h, shade) {
  const crcT = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = b => { let c = 0xFFFFFFFF; for (const x of b) c = crcT[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t, 'latin1'), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.alloc((w * 3 + 1) * h, shade); for (let y = 0; y < h; y++) raw[y * (w * 3 + 1)] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,agents,files,docs'});
  const ME = (await call('GET', '/api/state')).me;
  check(ME && !(ME.workspaces || []).length, 'setup: Alice has no organisation');
  // a list of 40 tasks and 30 search hits
  const L = (await call('POST', '/api/lists', {name: 'Garden plan'})).id;
  const G = [];
  for (let i = 0; i < 40; i++) G.unshift((await call('POST', '/api/tasks', {title: `Bed ${String(i).padStart(2, '0')} gets compost`, list_id: L})).id);
  for (let i = 0; i < 30; i++) await call('POST', '/api/tasks', {title: `Seedling tray ${String(i).padStart(2, '0')} watered`, list_id: L});
  // three agents, two of them with a long chat
  const AG = [];
  for (const n of ['Fern', 'Moss', 'Ivy']) AG.push(await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: n.toLowerCase(), display_name: n}));
  for (const a of AG) { const l = (await call('POST', '/api/lists', {name: `Work of ${a.username || a.id}`})).id; await call('PUT', `/api/lists/${l}/members`, {user_id: a.id, role: 'edit'}); }  // one agent per list: the agents Alice works with
  check(AG.every(a => a.id && a.token), 'setup: three agents ' + JSON.stringify(AG.map(a => [a.id, !!a.token, a.error])));
  const say = (a, body) => fetch(B + `api/v1/agent/chats/${ME.id}`, {method: 'POST', headers: {...H, Authorization: 'Bearer ' + a.token}, body: JSON.stringify({body})}).then(x => x.json());
  for (let k = 0; k < 30; k++) { await say(AG[0], `Fern line ${String(k).padStart(2, '0')}: the hedge along the path is cut.`); await say(AG[1], `Moss line ${String(k).padStart(2, '0')}: the lawn is raked.`); }
  await say(AG[2], 'Ivy says hello');
  // 40 documents (each its own picture)
  const fd = new FormData();
  for (let i = 0; i < 40; i++) fd.append('files', new Blob([png(60 + i, 80, 40 + i * 4)], {type: 'image/png'}), `receipt-${String(i).padStart(2, '0')}.png`);
  fd.append('ws', 'private');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
  const DOCS = up.ids || [];
  check(DOCS.length === 40, 'setup: 40 documents uploaded ' + JSON.stringify(up).slice(0, 200));
  for (let i = 0; i < 200; i++) { const j = await call('GET', '/api/docs?ws=private&facets=0&limit=200'); if ((j.docs || j.items || []).filter(x => ['done', 'failed'].includes(x.state)).length >= 40) break; await sleep(300); }

  const run = (wd, ht, touch) => firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(wd);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, `${tag}: Firefox login`);
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
    const frames = () => ev(`new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))`);
    const settled = async () => { await wait(`!FL.vt && !td_rsT && !td_polling && !lpT`, 60); await frames(); };
    const SC = `(n => { for (; n && n !== document.body; n = n.parentElement) if (n.scrollHeight > n.clientHeight + 1 && /^(auto|scroll)$/.test(getComputedStyle(n).overflowY)) return n; return null; })`;
    const put = (sel, off) => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}), b = e && ${SC}(e.parentElement); if (!b) return false; b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top - ${off}; return b.scrollTop > 0; })()`);
    const at = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {top: r.top, inSight: r.bottom > 0 && r.top < innerHeight && r.height > 0, text: e.textContent.replace(/\\s+/g, ' ').trim().slice(0, 80)}; })()`);
    const same = (a, b, what) => check(a && b && Math.abs(a.top - b.top) <= 1 && b.inSight, `${tag}: ${what} stays in place (${a && a.top} -> ${b && b.top}, in sight ${b && b.inSight})`);

    // ============ #5226 a notice bar arrives while Alice reads in the middle of the list
    await o.nav(B + '#l/' + L);
    check(await wait(`S.booted && document.querySelectorAll('#view .trow[data-id]').length >= 40`), `${tag}: list: the tasks are drawn`);
    const R1 = `#view .trow[data-id="${G[20]}"]`;
    check(await put(R1, 140), `${tag}: list: scrolled to the middle (#view scrolls: ${await ev(`${SC}(document.querySelector('${R1}'))?.id`)})`);
    await settled();
    const a0 = await at(R1);
    check(a0 && /Bed 19 gets compost/.test(a0.text), `${tag}: list: the row read shows its title (${a0 && a0.text})`);
    await call('PUT', '/api/admin/announcement', {text: `Backup tonight ${tag}`, minutes: 60});
    await ev(`load().then(() => (render(), 1))`);  // what the app's reload does when the server's state changed
    check(await wait(`/Backup tonight ${tag}/.test(document.querySelector('#main #annbar')?.textContent || '')`, 60), `${tag}: the notice bar arrives`);
    await settled();
    same(a0, await at(R1), '#5226: a notice bar appears above - the row read');
    const bar = await at('#annbar');
    check(bar && bar.inSight && /Notice: Backup tonight/.test(bar.text), `${tag}: #5226: the bar's text is in sight (${bar && bar.text})`);
    await shot(`p2940a-${tag}-annbar.png`);
    await ev(`(document.querySelector('#annbar [data-act="ann-hide"]').click(), 1)`);
    check(await wait(`!document.querySelector('#annbar')`), `${tag}: #5226: hiding it by hand removes the bar`);
    const a1 = await at(R1);
    check(a1 && a1.inSight && /Bed 19/.test(a1.text), `${tag}: #5226: after hiding the row read is still in sight`);
    await call('PUT', '/api/admin/announcement', {text: ''});
    await ev(`(() => { const e = document.querySelector('${R1} .ttl') || document.querySelector('${R1}'); e.click(); return 1; })()`);
    check(await wait(`S.sel === ${G[20]} && /Bed 19 gets compost/.test(document.getElementById('detail')?.textContent || '')`), `${tag}: a tap on the row read opens it`);
    await ev(`(closeDetail(), 1)`);
    check(await wait(`!S.sel`), `${tag}: closed again`);
    if (touch) return;

    // ============ #5225 Search: the caret on opening, never back after a redraw
    await o.nav(B + '#search');
    check(await wait(`document.activeElement?.id === 'searchq'`), `${tag}: #5225: opening Search puts the caret into its field`);
    await ev(`(doSearch('Seedling'), 1)`);
    check(await wait(`document.querySelectorAll('#sresults .trow[data-id]').length >= 30`, 100), `${tag}: search: the 30 hits are drawn`);
    const ids = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#sresults .trow[data-id]')].map(e => +e.dataset.id))`));
    const R3 = `#sresults .trow[data-id="${ids[18]}"]`;
    await ev(`(document.activeElement.blur(), 1)`);  // Alice reads the hits (the field has no focus any more)
    check(await put(R3, 140), `${tag}: search: scrolled to the middle of the hits`);
    await settled();
    const c0 = await at(R3);
    await ev(`(render(), 1)`);  // a live redraw
    await settled();
    check(await ev(`document.activeElement?.id !== 'searchq'`), `${tag}: #5225: a redraw does not take the focus back to the search field (${await ev('document.activeElement?.id || document.activeElement?.tagName')})`);
    same(c0, await at(R3), '#5225: search redraw - the hit read');
    await ev(`(document.querySelector('#searchq').focus(), 1)`);
    check(await ev(`document.activeElement?.id === 'searchq'`), `${tag}: search: a click into the field still gives the caret`);

    // ============ #5225 chat windows: a third window rebuilds the panel
    await o.nav(B + '#l/' + L);
    check(await wait(`S.booted && (S.agents || []).length >= 3`), `${tag}: chat: the agents are known (${await ev('JSON.stringify([S.booted, (S.agents || []).map(a => a.name)])')})`);
    await ev(`(chatOpen(${AG[0].id}), 1)`);
    check(await wait(`/Fern line 29/.test(document.getElementById('achat')?.textContent || '')`, 80), `${tag}: chat: Fern's chat is open`);
    await ev(`(cw_split('a:${AG[1].id}'), 1)`);
    const sec = k => `#achat .cwin[data-cw="${k}"]`, kF = `a:${AG[0].id}`, kM = `a:${AG[1].id}`, kI = `a:${AG[2].id}`;
    check(await wait(`document.querySelectorAll('#achat.cwsplit .cwin').length === 2 && /Moss line 29/.test(document.querySelector('${sec(kM)}')?.textContent || '') && /Fern line 29/.test(document.querySelector('${sec(kF)}')?.textContent || '')`, 80), `${tag}: chat: two windows, both with their messages`);
    await settled();
    // Fern's window: Alice reads line 10 higher up; Moss's window stays at its end
    const LINE = (k, t) => `[...document.querySelectorAll('${sec(k)} .chmsgs .cmsg')].find(e => /${t}/.test(e.textContent))`;
    const lineAt = (k, t) => ev(`(() => { const e = ${LINE(k, t)}, b = document.querySelector('${sec(k)} .chmsgs'); if (!e || !b) return null; const r = e.getBoundingClientRect(), q = b.getBoundingClientRect(); return {top: r.top - q.top, inSight: r.bottom > q.top && r.top < q.bottom, end: b.scrollHeight - b.scrollTop - b.clientHeight < 8}; })()`);
    check(await ev(`(() => { const e = ${LINE(kF, 'Fern line 10')}, b = document.querySelector('${sec(kF)} .chmsgs'); if (!e || !b) return false; b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top - 20; return b.scrollHeight - b.scrollTop - b.clientHeight > 100; })()`), `${tag}: chat: Fern's window scrolled up to line 10`);
    await frames();
    const f0 = await lineAt(kF, 'Fern line 10'), m0 = await lineAt(kM, 'Moss line 29');
    check(f0 && f0.inSight && m0 && m0.end, `${tag}: chat: line 10 read in Fern's window, Moss's window at its end ${JSON.stringify([f0, m0])}`);
    await ev(`(cw_split('${kI}'), 1)`);
    check(await wait(`document.querySelectorAll('#achat.cwsplit .cwin').length === 3 && /Ivy says hello/.test(document.querySelector('${sec(kI)}')?.textContent || '')`, 80), `${tag}: chat: a third window (the panel is built anew)`);
    await settled();
    const f1 = await lineAt(kF, 'Fern line 10'), m1 = await lineAt(kM, 'Moss line 29');
    check(f1 && f1.inSight && Math.abs(f1.top - f0.top) <= 1 && !f1.end, `${tag}: #5225: Fern's window keeps the place read (line 10 ${f0 && f0.top} -> ${f1 && f1.top}, in sight ${f1 && f1.inSight})`);
    check(m1 && m1.end && m1.inSight, `${tag}: #5225: Moss's window stays at its end, its last line in sight ${JSON.stringify(m1)}`);
    check(await ev(`(() => { const b = document.querySelector('${sec(kI)} .chmsgs'); return !!b && b.scrollHeight - b.scrollTop - b.clientHeight < 8; })()`), `${tag}: #5225: the new window opens at its end`);
    await shot(`p2940a-${tag}-chatwins.png`);
    await ev(`(typeof chatClose === 'function' && chatClose(), 1)`).catch(() => 0);

    // ============ #5601 document view: the strip with 40 documents
    await o.nav(B + '#docs');
    check(await wait(`(DC.docs || []).length >= 40`, 100), `${tag}: docs: the 40 documents are listed`);
    const order = JSON.parse(await ev('JSON.stringify(DC.docs.map(x => x.id))'));
    await ev(`(() => { const c = document.querySelector('.dc-view [data-dco="${order[20]}"]'); c.scrollIntoView({block: 'center'}); c.click(); return 1; })()`);
    check(await wait(`document.querySelector('.dv-view .dc-body')?.dataset.id === '${order[20]}' && !!document.querySelector('.dv-view .dv-strip .dv-th.on')`, 80), `${tag}: docs: the 21st document is open with its strip`);
    await settled();
    const STRIP = `document.querySelector('.dv-view .dv-strip')`;
    const thAt = id => ev(`(() => { const s = ${STRIP}, b = s && s.querySelector('[data-dvgo="${id}"]'); if (!b) return null; const r = b.getBoundingClientRect(), q = s.getBoundingClientRect(); return {top: r.top, st: s.scrollTop, on: b.classList.contains('on'), inSight: r.top >= q.top - 1 && r.bottom <= q.bottom + 1}; })()`);
    const cur0 = await thAt(order[20]);
    check(cur0 && cur0.on && cur0.inSight, `${tag}: docs: the open one is marked and in sight in the strip ${JSON.stringify(cur0)}`);
    // a picture in sight a few entries further down (the strip shows several)
    const pick = JSON.parse(await ev(`JSON.stringify((() => { const s = ${STRIP}, q = s.getBoundingClientRect(); return [...s.querySelectorAll('[data-dvgo]')].map(b => [+b.dataset.dvgo, b.getBoundingClientRect()]).filter(([id, r]) => id !== ${order[20]} && r.top >= q.top && r.bottom <= q.bottom).map(x => x[0]); })())`));
    check(pick.length >= 2, `${tag}: docs: other pictures are in sight in the strip (${pick.length})`);
    const T = pick.find(id => order.indexOf(id) > 20) || pick[pick.length - 1];
    const t0 = await thAt(T);
    await ev(`(${STRIP}.querySelector('[data-dvgo="${T}"]').click(), 1)`);
    check(await wait(`document.querySelector('.dv-view .dc-body')?.dataset.id === '${T}'`, 80), `${tag}: docs: the clicked document opens`);
    await settled();
    const t1 = await thAt(T);
    check(t1 && t1.on, `${tag}: #5601: the mark moved to the clicked picture`);
    check(t0 && t1 && Math.abs(t1.st - t0.st) <= 1 && Math.abs(t1.top - t0.top) <= 1, `${tag}: #5601: the strip does not move on a click (scroll ${t0 && t0.st} -> ${t1 && t1.st}, picture ${t0 && t0.top} -> ${t1 && t1.top})`);
    await shot(`p2940a-${tag}-strip.png`);
    // leafing with the arrow key: inside the visible part the strip stays, past its edge the open one comes into sight
    const key = () => ev(`(document.activeElement && document.activeElement.blur(), document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true})), 1)`);
    let i = order.indexOf(T), moved = false, still = null;
    for (let n = 0; n < 18 && i < order.length - 1; n++) {
      const before = await thAt(order[i + 1]);
      await key(); i++;
      check(await wait(`document.querySelector('.dv-view .dc-body')?.dataset.id === '${order[i]}'`, 80), `${tag}: docs: arrow right leafs to ${i}`);
      await settled();
      const now = await thAt(order[i]);
      check(now && now.on && now.inSight, `${tag}: #5601: after leafing to ${i} the open one is in sight in the strip ${JSON.stringify(now)}`);
      if (before && before.inSight && still === null) still = Math.abs(now.st - before.st) <= 1;
      if (before && now && now.st !== before.st) moved = true;
    }
    check(still === true, `${tag}: #5601: a step to a picture already in sight does not scroll the strip`);
    check(moved, `${tag}: #5601: leafing past the edge scrolled the strip (just so far)`);
    await shot(`p2940a-${tag}-strip-leafed.png`);
  }, touch);
  await run(1440, 900, false);
  await run(390, 800, true);
  console.log(`p2940_a_ruhe: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
