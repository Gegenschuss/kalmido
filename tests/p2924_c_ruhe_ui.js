// kalmido-suite: fresh
// 2.924.0 UI test (#5224): a redraw keeps the reading place (keepReading, static/js/render.js) - the view moves only when the
// person makes it move. Own container (start.sh), Firefox (real layout) on a phone with a finger (320 and 460 px, touch).
// Alice (no organisation) reads in the middle of a page; then something changes ABOVE what she reads, the way it happens
// live, and the element she looked at must keep its screen position (+-1 px) and its content must still be in sight:
//   1. list with a live delta: an agent adds a task (it goes on top) and makes a title above her long (the row grows)
//   2. detail with comments arriving (the agent writes two comments while she reads an older one)
//   3. search with a live update (a hit above changes its title while the results are scrolled)
//   4. a knowledge page with an image that loads later above what she reads (the browser's own anchoring must not be
//      undone by a pixel value)
//   5. a banner appears: an overdue task makes the "overdue" line appear on top of Today
// The agents page (history open + a step) is the suite of #5223 (tests/p5223_agenten_ruhe_ui.js), not repeated here.
// After each case: back to the top shows what came in (the new task / the banner), and a tap on the read row opens it.
// Invented names only.
// freelancer-matrix: tasks, comments, search, wiki (alice without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2924_c_ruhe_ui', check, shots: 'P2924C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(h.Authorization ? {} : {Cookie: CK})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,wiki'});
  const ME = (await call('GET', '/api/state')).me;
  check(!(ME.workspaces || []).length, 'setup: Alice has no organisation');
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const agPatch = async (id, body) => call('PATCH', `/api/v1/tasks/${id}`, {...body, expect_updated_at: (await call('GET', `/api/v1/tasks/${id}`, null, AGH)).updated_at}, AGH);
  const agc = (id, body) => call('POST', `/api/v1/tasks/${id}/comments`, {body}, AGH);
  // a list of 40 tasks (each new one goes on top: G[0] is the last one created), and the agent may write in it
  const L = (await call('POST', '/api/lists', {name: 'Garden plan'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const G = [];
  for (let i = 0; i < 40; i++) G.unshift((await call('POST', '/api/tasks', {title: `Bed ${String(i).padStart(2, '0')} gets compost`, list_id: L})).id);
  // a task with a long note and many comments (the detail)
  const D = (await call('POST', '/api/tasks', {title: 'Fence along the north side', list_id: L, notes: Array.from({length: 12}, (_, k) => `Post ${k} needs a new coat of paint and a check of its foot.`).join('\n\n')})).id;
  const C = [];
  for (let k = 0; k < 18; k++) C.push((await agc(D, `Post ${k}: painted, the foot is fine. Next one tomorrow morning.`)).id);
  // tasks due today (Today), searchable by "Seedling"
  const L2 = (await call('POST', '/api/lists', {name: 'Greenhouse'})).id;
  await call('PUT', `/api/lists/${L2}/members`, {user_id: ag.id, role: 'edit'});
  const T = [];
  for (let i = 0; i < 30; i++) T.push((await call('POST', '/api/tasks', {title: `Seedling tray ${String(i).padStart(2, '0')} watered`, list_id: L2, due: TC.day(0)})).id);
  // a knowledge page: an image on top, then many paragraphs
  const WP = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Garden notes', body: '# Garden notes\n\n![plan](/static/icon.svg)\n\n' + Array.from({length: 50}, (_, k) => `Paragraph ${k}: the soil in this corner is heavy and needs sand before spring.`).join('\n\n')})).id;
  // its own picture (a small PNG made here), put into the text as the app does it: ![label](/api/wiki/files/<id>/<name>)
  const png = (() => { const zlib = require('zlib'), w = 40, h = 40, crc = b => { let c = ~0; for (const x of b) { c ^= x; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xEDB88320 & -(c & 1)); } return ~c >>> 0; };
    const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]), cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td)); return Buffer.concat([l, td, cr]); };
    const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
    const raw = Buffer.alloc((w * 3 + 1) * h, 0x80); for (let y = 0; y < h; y++) raw[y * (w * 3 + 1)] = 0;
    return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]); })();
  const fd = new FormData(); fd.append('file', new Blob([png], {type: 'image/png'}), 'plan.png');
  const up = await (await fetch(B + `api/wiki/pages/${WP}/files`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
  const WF = (up.files || [])[0];
  check(!!WF?.id, 'setup: the picture of the knowledge page is stored ' + JSON.stringify(up).slice(0, 200));
  const wpg = await call('GET', `/api/wiki/pages/${WP}`);
  await call('PATCH', `/api/wiki/pages/${WP}`, {body: wpg.body.replace('![plan](/static/icon.svg)', `![plan](/api/wiki/files/${WF?.id}/plan.png)`)});
  check(L && D && C.length === 18 && C.every(Boolean) && T.length === 30 && WP > 0, 'setup: lists, tasks, comments, knowledge page');

  const run = (wd, ht) => firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(wd);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, `${tag}: Firefox login`);
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
    // the page took the server's last change (its poll saw the version) and the gathered redraws ran; then two frames
    const settled = async () => {
      await wait(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.v === S.v && !td_polling)`, 150);
      await wait(`!FL.vt && !td_rsT && !td_polling && !lpT`, 60);
      await ev(`new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))`);
    };
    // the scrolling box around the element (as keepReading finds it) and its screen position
    const SC = `(n => { for (; n && n !== document.body; n = n.parentElement) if (n.scrollHeight > n.clientHeight + 1 && /^(auto|scroll)$/.test(getComputedStyle(n).overflowY)) return n; return null; })`;
    const put = (sel, off) => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}), b = e && ${SC}(e.parentElement); if (!b) return false; b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top - ${off}; return b.scrollTop > 0; })()`);
    const at = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {top: r.top, inSight: r.bottom > 0 && r.top < innerHeight && r.height > 0, text: e.textContent.replace(/\\s+/g, ' ').trim().slice(0, 80)}; })()`);
    const toTop = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}), b = e && ${SC}(e.parentElement); if (b) b.scrollTop = 0; return 1; })()`);
    const same = (a, b, what) => check(a && b && Math.abs(a.top - b.top) <= 1 && b.inSight, `${tag}: ${what} stays under the finger (${a && a.top} -> ${b && b.top}, in sight ${b && b.inSight})`);

    // ============ 1. list with a live delta
    await o.nav(B + '#l/' + L);
    check(await wait(`document.querySelectorAll('#view .trow[data-id]').length >= 40`), `${tag}: list: the 41 tasks are drawn`);
    const R1 = `#view .trow[data-id="${G[20]}"]`;
    check(await put(R1, 120), `${tag}: list: scrolled to the middle`);
    await settled();
    const a0 = await at(R1);
    check(a0 && /Bed 19 gets compost/.test(a0.text), `${tag}: list: the row read shows its title (${a0 && a0.text})`);
    const NT = (await call('POST', '/api/v1/tasks', {title: `New bed ${tag} on top`, list_id: L}, AGH)).id;
    check(await wait(`!!document.querySelector('#view .trow[data-id="${NT}"]')`, 100), `${tag}: list: the agent's new task arrives (live)`);
    await settled();
    same(a0, await at(R1), 'list: a task inserted on top - the row read');
    await agPatch(G[5], {title: `Bed 34 gets compost, sand, lime, a layer of leaves and a cover against the frost for the whole of the winter ${tag}`});
    check(await wait(`/whole of the winter ${tag}/.test(document.querySelector('#view .trow[data-id="${G[5]}"]')?.textContent || '')`, 100), `${tag}: list: the longer title above arrives (live)`);
    await settled();
    same(a0, await at(R1), 'list: a row above grows - the row read');
    await shot(`p2924c-${tag}-list.png`);
    await toTop(R1);
    const nt = await at(`#view .trow[data-id="${NT}"]`);
    check(nt && nt.inSight && /New bed/.test(nt.text), `${tag}: list: back at the top the new task is in sight`);

    // ============ 2. detail with comments arriving
    await ev(`(openDetail(${D}), 1)`);
    check(await wait(`document.querySelectorAll('#d-tl-items .cm[data-cid]').length >= 18`, 100), `${tag}: detail: the comments are drawn`);
    const R2 = `#d-tl-items .cm[data-cid="${C[9]}"]`;
    check(await put(R2, 100), `${tag}: detail: scrolled to a comment in the middle`);
    await settled();
    const b0 = await at(R2);
    check(b0 && /Post 9: painted/.test(b0.text), `${tag}: detail: the comment read shows its text`);
    const NC = [(await agc(D, `Post 18 ${tag}: the gate needs a new hinge.`)).id, (await agc(D, `Post 19 ${tag}: the hinge is fitted and oiled.`)).id];
    check(await wait(`!!document.querySelector('#d-tl-items .cm[data-cid="${NC[1]}"]')`, 100), `${tag}: detail: the new comments arrive`);
    await settled();
    same(b0, await at(R2), 'detail: two new comments - the comment read');
    check(await ev(`/hinge is fitted/.test(document.querySelector('#d-tl-items .cm[data-cid="${NC[1]}"]')?.textContent || '')`), `${tag}: detail: the new comment shows its text`);
    await shot(`p2924c-${tag}-detail.png`);
    await ev(`(closeDetail(), 1)`);
    check(await wait(`!S.sel`), `${tag}: detail: closed again`);

    // ============ 3. search with a live update
    await o.nav(B + '#search');
    check(await wait(`!!document.querySelector('#searchq')`), `${tag}: search: the field`);
    await ev(`(doSearch('Seedling'), 1)`);
    check(await wait(`document.querySelectorAll('#sresults .trow[data-id]').length >= 30`, 100), `${tag}: search: the 30 hits are drawn`);
    const ids = await ev(`JSON.stringify([...document.querySelectorAll('#sresults .trow[data-id]')].map(e => +e.dataset.id))`).then(JSON.parse);
    const R3 = `#sresults .trow[data-id="${ids[18]}"]`;
    check(await put(R3, 120), `${tag}: search: scrolled to the middle of the hits`);
    await settled();
    const c0 = await at(R3);
    check(c0 && /Seedling tray/.test(c0.text), `${tag}: search: the hit read shows its title`);
    // 2.965.0 (#5655, CI red of 2.941.0 only, green on the Mac): what moved - the hits' order and the place of each row down to
    // the one read, the scroll box, the parts above the hits and the result the server gives; printed when the check fails
    const SNAP = `(() => { const v = document.getElementById('view'), r = document.querySelector('#sresults'), rows = [...document.querySelectorAll('#sresults .trow[data-id]')];
      const i = rows.findIndex(e => e.matches(${JSON.stringify(R3)}));
      return JSON.stringify({st: Math.round(v.scrollTop), sh: v.scrollHeight, res: Math.round(r.getBoundingClientRect().top), n: rows.length, i, vl: !!r.querySelector('.vlsp, [data-vl]'), ka: (m => m ? (m.sel || m.n?.nodeName) + '@' + Math.round(m.top) : null)(typeof kr_mark === 'function' ? kr_mark(v) : null),
        above: [...v.querySelectorAll('#view > * , #sresults')].slice(0, 6).map(e => (e.id || e.className || e.nodeName).toString().slice(0, 20) + ':' + Math.round(e.getBoundingClientRect().height)),
        rows: rows.slice(0, i + 1).map(e => e.dataset.id + '@' + Math.round(e.getBoundingClientRect().top) + '/' + Math.round(e.getBoundingClientRect().height)).join(' ')}); })()`;
    const s0 = await ev(SNAP);
    // the hits hold what the server answered (no live delta): a hit above changes, the results load again the way the app
    // asks again (the "similar meaning" switch, related.js) - the hit read stays
    await agPatch(ids[3], {title: `Seedling tray moved to the bright shelf by the window and turned so that every plant gets light ${tag}`});
    await settled();
    await ev(`(doSearch(S.searchQ), 1)`);
    check(await wait(`/every plant gets light ${tag}/.test(document.querySelector('#sresults .trow[data-id="${ids[3]}"]')?.textContent || '')`, 100), `${tag}: search: the changed hit above arrives with the results`);
    await settled();
    const c1 = await at(R3);
    same(c0, c1, 'search: a hit above grows - the hit read');
    if (!(c0 && c1 && Math.abs(c0.top - c1.top) <= 1 && c1.inSight)) {
      const srv = await call('GET', '/api/tasks?scope=search&q=Seedling');
      console.log(`DIAG p2924c ${tag} search before ${s0}\nDIAG p2924c ${tag} search after  ${await ev(SNAP)}\nDIAG p2924c ${tag} server order ${(srv.tasks || []).map(t => t.id).join(' ')} (drawn first ${ids.join(' ')}; changed ${ids[3]}, read ${ids[18]})`);
    }
    await shot(`p2924c-${tag}-search.png`);

    // ============ 4. knowledge page, an image above loads later
    await o.nav(B + '#wiki/' + WP);
    check(await wait(`/Paragraph 40:/.test(document.getElementById('view')?.textContent || '')`, 100), `${tag}: wiki: the page is drawn`);
    // the paragraph read, found by its text each time (a redraw of the page may build new nodes)
    const P30 = `[...document.querySelectorAll('#wk-md p')].find(e => /^Paragraph 30:/.test(e.textContent.trim()))`;
    const atP = () => ev(`(() => { const e = ${P30}; if (!e) return null; const r = e.getBoundingClientRect(); return {top: r.top, inSight: r.bottom > 0 && r.top < innerHeight && r.height > 0, text: e.textContent.trim().slice(0, 80)}; })()`);
    check(await wait(`!!document.querySelector('#wk-md img.wkimg')`, 60), `${tag}: wiki: the picture of the page is in its text`);
    check(await ev(`(() => { const e = ${P30}, b = e && ${SC}(e.parentElement); if (!b) return false; b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top - 100; return b.scrollTop > 0; })()`), `${tag}: wiki: scrolled to paragraph 30`);
    await settled();
    const d0 = await atP();
    // the picture above gets a tall one now (it "loads later": the page grows above what is read)
    // 2.965.0 (#5655): the page's own picture (lazy, still on its way) may load first and fire onload: only the tall one counts
    const grown = await ev(`new Promise(res => { const i = document.querySelector('#wk-md img.wkimg'); if (!i) return res(false); const h0 = i.getBoundingClientRect().height; i.removeAttribute('loading'); setTimeout(() => res(i.getBoundingClientRect().height - h0), 15000);
      i.onload = () => { if (!/^data:/.test(i.currentSrc || i.src) || i.naturalHeight < 900) return; requestAnimationFrame(() => requestAnimationFrame(() => res(i.getBoundingClientRect().height - h0))); }; i.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="900"><rect width="300" height="900" fill="#8a6"/></svg>'); })`);
    // 2.941.0 (#5227): the page's picture carries width/height 40 now (its box is reserved), the tall one grows it to 40 x 120
    check(grown > 60, `${tag}: wiki: the picture above grew by ${grown} px`);
    const d1 = await atP();
    same(d0, d1, 'wiki: a picture loads above - the paragraph read');
    check(/^Paragraph 30:/.test(d1?.text || ''), `${tag}: wiki: the paragraph read shows its text`);
    // #5227: a picture holds its place BEFORE its bytes arrive - the page's own picture carries the size the server read on
    // upload (40 x 40 here); one of unknown size (another page's file, the file store) a fixed 4:3 box; a file-store picture
    // still asked for a box of the same size. Measured at once after drawing (no answer can have come yet): without the
    // size an unloaded picture is only its alt text high.
    check(await ev(`(() => { const i = document.querySelector('#wk-md img.wkimg'); return i?.getAttribute('width') === '40' && i?.getAttribute('height') === '40'; })()`),
      `${tag}: wiki: the page's own picture carries its size (width / height 40)`);
    const box = await ev(`(() => { const md = document.getElementById('wk-md'), t = document.createElement('div'), W = '\\u2063WKA0\\u2063';
      const ws = {files: {77: {url: '/api/files/nodes/77/content', image: true, name: 'n.png'}}, links: {}, asked: new Set(['f77', 'f78']), got: new Set(['f77']), qf: new Set(), ql: new Set(), t: 0};
      t.innerHTML = '<div class="k1">' + wka_put(W, [{img: true, id: 987654, name: 'n.png', label: 'known'}], {files: [{id: 987654, w: 400, h: 300}]}) + '</div>'
        + '<div class="k2">' + wka_put(W, [{img: true, id: 987655, name: 'm.png', label: 'unknown'}], {files: []}) + '</div>'
        + '<div class="k3">' + wem_put({id: 0, _emb: true, _wem: ws}, '\u2063WEM0\u2063', [{img: true, id: '77', label: 'store'}]) + '</div>'
        + '<div class="k4">' + wem_put({id: 0, _emb: true, _wem: ws}, '\u2063WEM0\u2063', [{img: true, id: '78', label: 'asked'}]) + '</div>';
      md.prepend(t);
      const h = s => Math.round(t.querySelector(s)?.getBoundingClientRect().height || 0), w = Math.round(t.getBoundingClientRect().width);
      const r = {w, rem: parseFloat(getComputedStyle(document.documentElement).fontSize), known: h('.k1 img'), unknown: h('.k2 img'), store: h('.k3 img'), asked: h('.k4 .wemna')};
      t.remove(); return r; })()`);
    const want = Math.min(400, box?.w || 0) * 0.75, ph = Math.min((box?.w || 0) * 0.75, 24 * (box?.rem || 16));
    check(box && Math.abs(box.known - want) <= 2, `${tag}: wiki: a picture of known size holds its box before it loads (${box?.known} px, want ${want}) ${JSON.stringify(box)}`);
    check(box && Math.abs(box.unknown - ph) <= 2 && Math.abs(box.store - ph) <= 2, `${tag}: wiki: a picture of unknown size holds the 4:3 box (${box?.unknown} / ${box?.store} px, want ${ph})`);
    check(box && Math.abs(box.asked - ph) <= 2, `${tag}: wiki: a file-store picture still asked for holds the same box (${box?.asked} px, want ${ph})`);
    await shot(`p2924c-${tag}-wiki.png`);

    // ============ 5. a banner appears on Today
    await o.nav(B + '#today');
    check(await wait(`document.querySelectorAll('#view .trow[data-id]').length >= 30`, 100), `${tag}: today: the 30 tasks due today are drawn`);
    const R5 = `#view .trow[data-id="${T[15]}"]`;
    check(await put(R5, 120), `${tag}: today: scrolled to the middle`);
    await settled();
    const e0 = await at(R5);
    check(!(await ev(`!!document.querySelector('#view .odban')`)), `${tag}: today: no overdue line yet`);
    const OD = (await call('POST', '/api/v1/tasks', {title: `Overdue cuttings ${tag}`, list_id: L2, due: TC.day(-2)}, AGH)).id;
    check(await wait(`!!document.querySelector('#view .trow[data-id="${OD}"]') || !!document.querySelector('#view .odban')`, 100), `${tag}: today: the overdue task / line arrives (live)`);
    await settled();
    same(e0, await at(R5), 'today: the overdue line appears above - the row read');
    await shot(`p2924c-${tag}-today.png`);
    await toTop(R5);
    check(await ev(`(() => { const b = document.querySelector('#view .odban') || document.querySelector('#view .trow[data-id="${OD}"]'); const r = b && b.getBoundingClientRect(); return !!r && r.top < innerHeight && r.bottom > 0 && /overdue|Overdue cuttings/.test(b.textContent); })()`), `${tag}: today: back at the top the overdue line is in sight`);
    // in and back: a tap on the row read opens it, closing comes back to Today
    await put(R5, 120);
    await ev(`(() => { const e = document.querySelector('${R5} .ttl') || document.querySelector('${R5}'); e.click(); return 1; })()`);
    check(await wait(`S.sel === ${T[15]} && /Seedling tray 15/.test(document.getElementById('detail')?.textContent || '')`), `${tag}: today: a tap on the row read opens it`);
    await ev(`(closeDetail(), 1)`);
    check(await wait(`!S.sel && !!document.querySelector('${R5}')`), `${tag}: today: back on Today`);
    // tidy up for the second width
    await call('DELETE', `/api/tasks/${OD}`);
    await call('DELETE', `/api/tasks/${NT}`);
  }, true);
  await run(320, 640);
  await run(460, 800);
  console.log(`p2924_c_ruhe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
