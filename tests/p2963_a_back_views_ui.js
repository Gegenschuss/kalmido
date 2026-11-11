// 2.963.0 UI test (#5233: Back on a page goes one view back in views without an address of their own), own container
// kalmido-suite: fresh
// Firefox as a touch screen (Android Back = history.back()) in phone width 390 px, mode workspaces with one organisation.
// Each place: the page, its view opened (a step of #view, backclose.js f8d_viewStep), Back once = the view before with its
// content, the page and its address stay, the next Back leaves the page (no dead entry); the view's own ‹ goes the same way.
// - team chat: a room > its thread (Back = the room, not out of it)
// - contacts > ⋯ > Trash
// - office > credit cards > a card > its statement (two steps: the statement, then the card)
// - office > travel expenses > a trip
// - notes > the trash button
// - a task's panel: a subtask opened from it - Back and the panel's ‹ show the task again, the next one closes the panel
// Invented data only.
// freelancer-matrix: n/a - no route of its own, the Back key in the browser
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const DAY = require('./testclock').today();  // the travel tab lists the trips of this year
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2963_a_back_views_ui', check, shots: 'P2963A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2963A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,contacts';
const pdf = lines => {  // a PDF with a text layer, hand-written (as p2444_a_cards_ui)
  const stream = `BT /F1 10 Tf 12 TL 40 760 Td\n${lines.map(x => `(${x}) Tj T*`).join('\n')}\nET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
};
const upload = async (ck, url, name, text) => { const fd = new FormData(); fd.append('file', new Blob([text], {type: 'application/pdf'}), name);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  const bob = (await call(CB, 'GET', '/api/state')).me;
  // the team chat: a room with a first message, its thread (one answer) and a later message
  const room = await call(CA, 'POST', '/api/team/channels', {name: 'Garden crew', org_id: org.id, open: false, members: [bob.id]});
  check(room.id > 0, 'a room ' + JSON.stringify(room).slice(0, 200));
  const root = await call(CA, 'POST', `/api/team/rooms/${room.id}/messages`, {body: 'Plant the beans on Monday?'});
  await call(CB, 'POST', `/api/team/rooms/${room.id}/messages`, {body: 'Monday works for me', thread_of: root.id});
  await call(CA, 'POST', `/api/team/rooms/${room.id}/messages`, {body: 'Tools are in the shed'});
  // contacts: one kept, one in the trash
  const bk = await call(CA, 'POST', '/api/books', {name: 'Neighbours'});
  await call(CA, 'POST', '/api/contacts', {book_id: bk.id, given: 'Petra', family: 'Pond'});
  const gone = await call(CA, 'POST', '/api/contacts', {book_id: bk.id, given: 'Otto', family: 'Oldfield'});
  check((await call(CA, 'DELETE', `/api/contacts/${gone.id}`)).http < 300, 'a contact into the trash');
  // office: a card with one statement, a trip
  const card = await call(CA, 'POST', '/api/office/cards', {holder_id: bob.id, last4: '4711'});
  const st = await upload(CA, `/api/office/cards/${card.id}/statements`, 'abrechnung.pdf', pdf(['Abrechnung vom 15.01.2025', 'Karte 5232 12XX XXXX 4711', '03.01. 04.01. Cafe Beispiel Berlin 12,50-', 'Neuer Saldo 12,50-']));
  check(st.http === 201, 'a card with a statement ' + st.http);
  const trip = await call(CA, 'POST', '/api/office/trips', {date_from: DAY, dest: 'Kiel', people: [], items: [{date: DAY, category: 'train', amount: 40}]});
  check(trip.http === 201, 'a trip ' + trip.http);
  // notes: a list with a note and one in the trash; a task with a subtask
  const lst = await call(CA, 'POST', '/api/lists', {name: 'Garden plans'});
  await call(CA, 'POST', `/api/lists/${lst.id}/notes`, {title: 'Seed order', body: 'Beans, peas'});
  const n2 = await call(CA, 'POST', `/api/lists/${lst.id}/notes`, {title: 'Old fence idea', body: 'never mind'});
  check((await call(CA, 'DELETE', `/api/notes/${n2.id}`)).http < 300, 'a note into the trash');
  const ta = await call(CA, 'POST', '/api/tasks', {title: 'Plan the beds', list_id: lst.id});
  const tb = await call(CA, 'POST', '/api/tasks', {title: 'Buy the seeds', list_id: lst.id, parent_id: ta.id});
  check(ta.id > 0 && tb.id > 0, 'a task with a subtask');

  await firefox(async ({cmd, ev, nav: go, ctx, shot, until: wait}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 780}});
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    // a Back too many may leave the app (a red run): the state says so instead of ending the whole run
    const STATE = `(() => { try { return JSON.stringify({open: f8d_open(), depth: f8d_depth(), st: history.state, p: f8d_bk.pushed, skip: f8d_bk.skip, hash: location.hash, sel: S.sel}); } catch (e) { return 'not in the app: ' + location.pathname; } })()`;
    const back = () => ev(`(history.back(), 1)`);
    const tap = sel => ev(`(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`);
    const txt = sel => `(document.querySelector('${sel}')?.textContent || '')`;
    // n views of the page open, one entry each, the history on the top one
    const at = (n, more = 'true') => wait(`!f8d_bk.skip && f8d_depth() === ${n} && f8d_bk.pushed === ${n} && (history.state?.f8d || 0) === ${n} && (${more})`, {timeout: 8000});
    // the page itself: #today below it, the page's own entry marked (a Back too many lands on #today, visibly)
    const page = async (hash, ready) => {
      await go(B + 'static/icon.svg');  // a new load each time (a navigate to the same address with #today only changes the hash)
      await go(B + '#today');
      check(await wait(`typeof f8d_viewStep === 'function' && S.route?.key === 'today'`, {timeout: 20000}), `${hash}: the app is there`);
      await ev(`(location.hash = '${hash}', 1)`);
      const okp = await wait(`location.hash === '${hash}' && (${ready})`, {timeout: 20000});
      check(okp, `${hash}: the page shows its content ` + await ev(STATE));
      await ev(`(history.replaceState({p63: 1}, '', location.href), 1)`);
    };
    const onPage = hash => `location.hash === '${hash}' && history.state?.p63 === 1 && f8d_bk.pushed === 0 && !f8d_bk.skip && !(document.querySelector('#view')._stk || []).length`;
    const leaves = async (hash, tag) => { await back(); check(await wait(`location.hash === '#today' && S.route?.key === 'today'`, {timeout: 8000}), `${tag}: the next Back leaves the page (no dead entry) ` + await ev(STATE)); };

    // 1. team chat: room > thread
    {
      const h = `#team/${room.id}`, roomOk = `/Tools are in the shed/.test(${txt('#tc-msgs')}) && !document.querySelector('.tthview')`;
      const open = async how => {
        check(await tap(`document.querySelector('#tc-msgs .tthline[data-act="tth-open"]')`), `thread ${how}: the line under the first message`);
        check(await at(1, `/Monday works for me/.test(${txt('.tthview')}) && /Plant the beans/.test(${txt('.tthview')})`), `thread ${how}: the thread with its first message and answer, one step ` + await ev(STATE));
      };
      await page(h, roomOk);
      check(await ev(`isTouch() && isMobile()`), 'a touch screen in phone width');
      await open('Back');
      await shot('p2963a-thread.png');
      await back();
      check(await wait(`${onPage(h)} && ${roomOk}`, {timeout: 8000}), 'thread: Back = the room with its messages, still in the room ' + await ev(STATE));
      await open('‹');
      check(await tap(`document.querySelector('.tthview [data-act="tth-close"]')`), 'thread: its ‹');
      check(await wait(`${onPage(h)} && ${roomOk}`, {timeout: 8000}), 'thread: the ‹ = the room, its entry gone too ' + await ev(STATE));
      await leaves(h, 'thread');
    }

    // 2. contacts > ⋯ > Trash
    {
      const h = '#contacts', listOk = `/Petra/.test(${txt('#view')}) && !/Oldfield/.test(${txt('#view')})`;
      const open = async how => {
        check(await tap(`document.querySelector('#view [data-ct="menu"]')`), `contacts ${how}: the ⋯ menu`);
        await wait(`[...document.querySelectorAll('#pop:not(.hidden) button, #pop:not(.hidden) [role="menuitem"]')].some(b => b.textContent.trim() === 'Trash')`, {timeout: 6000});
        check(await tap(`[...document.querySelectorAll('#pop:not(.hidden) button, #pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim() === 'Trash')`), `contacts ${how}: Trash in the menu`);
        check(await at(1, `/Oldfield/.test(${txt('#view .ctlist')}) && !!document.querySelector('#view [data-ct="tback"]')`), `contacts ${how}: the trash with the deleted contact, one step ` + await ev(STATE));
      };
      await page(h, listOk);
      await open('Back');
      await back();
      check(await wait(`${onPage(h)} && ${listOk}`, {timeout: 8000}), 'contacts: Back = the contacts again, the page stays ' + await ev(STATE));
      await open('‹');
      check(await tap(`document.querySelector('#view [data-ct="tback"]')`), 'contacts: the trash\'s ‹');
      check(await wait(`${onPage(h)} && ${listOk}`, {timeout: 8000}), 'contacts: the ‹ = the contacts, its entry gone too ' + await ev(STATE));
      await leaves(h, 'contacts');
    }

    // 3. office > cards > card > statement: two steps
    {
      const h = '#office/cards', listOk = `!!document.querySelector('.ccopen[data-cc="card"]') && !document.querySelector('[data-cc="back"]')`;
      const cardOk = `!!document.querySelector('[data-cc="stmt"]') && /4711/.test(${txt('h3.ofcgrp')}) && !document.querySelector('[data-cc="tocard"]')`;
      const stmtOk = `!!document.querySelector('[data-cc="tocard"]') && /2025/.test(${txt('h3.ofcgrp')})`;
      await page(h, listOk);
      for (const how of ['Back', '‹']) {
        check(await tap(`document.querySelector('.ccopen[data-cc="card"]')`), `cards ${how}: a card tapped`);
        check(await at(1, cardOk), `cards ${how}: the card with its statement, one step ` + await ev(STATE));
        check(await tap(`document.querySelector('[data-cc="stmt"]')`), `cards ${how}: its statement tapped`);
        check(await at(2, stmtOk), `cards ${how}: the statement, two steps ` + await ev(STATE));
        if (how === 'Back') { await shot('p2963a-statement.png'); await back(); } else check(await tap(`document.querySelector('[data-cc="tocard"]')`), 'cards: the statement\'s ‹');
        check(await at(1, cardOk), `cards ${how}: = the card again, not the cards or out of the office ` + await ev(STATE));
        if (how === 'Back') await back(); else check(await tap(`document.querySelector('[data-cc="back"]')`), 'cards: the card\'s ‹');
        check(await wait(`${onPage(h)} && ${listOk}`, {timeout: 8000}), `cards ${how}: = the cards, the page stays ` + await ev(STATE));
      }
      await leaves(h, 'cards');
    }

    // 4. office > travel expenses > a trip
    {
      const h = '#office/travel', listOk = `!!document.querySelector('.rklist [data-rk="open"]') && /Kiel/.test(${txt('.rklist')})`;
      await page(h, listOk);
      for (const how of ['Back', '‹']) {
        check(await tap(`[...document.querySelectorAll('.rklist [data-rk="open"]')].find(b => /Kiel/.test(b.textContent))`), `trip ${how}: the trip tapped`);
        check(await at(1, `/Kiel/.test(${txt('.rkhead h3')}) && !!document.querySelector('[data-rk="back"]')`), `trip ${how}: the trip, one step ` + await ev(STATE));
        if (how === 'Back') await back(); else check(await tap(`document.querySelector('[data-rk="back"]')`), 'trip: "All trips"');
        check(await wait(`${onPage(h)} && ${listOk} && !document.querySelector('.rkhead')`, {timeout: 8000}), `trip ${how}: = all trips, the page stays ` + await ev(STATE));
      }
      await leaves(h, 'trip');
    }

    // 5. notes > the trash button
    {
      const h = `#notes/${lst.id}`, listOk = `/Seed order/.test(${txt('#nt-res')}) && !/Old fence idea/.test(${txt('#nt-res')})`;
      await page(h, listOk);
      for (const how of ['Back', 'button']) {
        check(await tap(`document.querySelector('#view [data-act="nt-trash"]')`), `notes ${how}: the trash button`);
        check(await at(1, `/Old fence idea/.test(${txt('#nt-res')}) && !/Seed order/.test(${txt('#nt-res')})`), `notes ${how}: the trash with the deleted note, one step ` + await ev(STATE));
        if (how === 'Back') await back(); else check(await tap(`document.querySelector('#view [data-act="nt-trash"]')`), 'notes: the trash button again');
        check(await wait(`${onPage(h)} && ${listOk}`, {timeout: 8000}), `notes ${how}: = the notes again, the page stays ` + await ev(STATE));
      }
      await leaves(h, 'notes');
    }

    // 6. a task's panel: a subtask opened from it
    {
      const h = `#l/${lst.id}`, listOk = `[...document.querySelectorAll('#view .trow')].some(r => /Plan the beds/.test(r.textContent))`;
      const title = `(document.querySelector('#detail.open #d-title')?.value || '')`;
      const shows = id => `S.sel === ${id} && history.state?.detail === ${id} && ${title} === ${JSON.stringify(id === ta.id ? 'Plan the beds' : 'Buy the seeds')}`;
      const closed = `!S.sel && !document.querySelector('#detail.open') && location.hash === '${h}' && history.state?.p63 === 1 && ${listOk}`;
      await page(h, listOk);
      for (const how of ['Back', '‹']) {
        check(await tap(`document.querySelector('#view .trow[data-id="${ta.id}"] .tmain[data-act="open"]')`), `panel ${how}: the task tapped`);
        check(await wait(`${shows(ta.id)} && !!document.querySelector('#detail .trow.subrow[data-id="${tb.id}"]')`, {timeout: 8000}), `panel ${how}: the task with its subtask ` + await ev(STATE));
        check(await tap(`document.querySelector('#detail .trow.subrow[data-id="${tb.id}"] [data-act="open"]')`), `panel ${how}: the subtask tapped in the panel`);
        check(await wait(shows(tb.id), {timeout: 8000}), `panel ${how}: the subtask in the panel ` + await ev(STATE));
        if (how === 'Back') { await shot('p2963a-subtask.png'); await back(); } else check(await tap(`document.querySelector('#detail button.back[data-act="close-detail"]')`), 'panel: its ‹');
        check(await wait(`${shows(ta.id)} && !!document.querySelector('#detail.open')`, {timeout: 8000}), `panel ${how}: = the task above it again, not closed ` + await ev(STATE));
        if (how === 'Back') await back(); else check(await tap(`document.querySelector('#detail button.back[data-act="close-detail"]')`), 'panel: its ‹ once more');
        check(await wait(closed, {timeout: 8000}), `panel ${how}: the next one closes the panel, the list stays ` + await ev(STATE));
      }
      await leaves(h, 'panel');
    }
  }, true);

  console.log(`p2963_a_back_views_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
