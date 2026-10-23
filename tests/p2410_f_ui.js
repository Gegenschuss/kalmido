// 2.41.0 UI tests, part F, own container (start.sh), Firefox (1440 x 900):
// - #1383: an agent's approval card in a task comment (accent edge, "Approval needed", Yes / No), a press answers it and
//   the card says "Yes, go ahead from Alice, <date>"; answer buttons under an agent's comment: the pen puts the text into the
//   comment box (nothing sent), a press sends it as my comment; an older question's buttons are gone once a newer comment
//   came (#1037); the task row shows the open approvals (lock + number); the agent chat still renders its approval card and
//   buttons through the shared component (choicecard.js)
// - #1376: live updates per area: agent comments on an open list cost fewer render() calls and state loads than before
//   (PERF line, the old way = S.lpOff), the sidebar keeps its nodes, a half-filled form (formguard) stays; a tasks change
//   waits while it has unsaved input
// - #1437: the vCard import shows "Import running…" with a bar at once and a result that stays until it is closed
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2410_f_ui', check, shots: 'P2410F_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'contacts']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,contacts'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Agent work'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Release the draft', list_id: L})).id;
  const agc = body => call(null, 'POST', `/api/v1/tasks/${T}/comments`, body, AGH);
  const AP = (await agc({body: 'Ready to publish.', approval: {title: 'Publish the draft', what: 'it goes online'}})).id;
  const Q1 = (await agc({body: 'Which variant?', choices: ['Short', 'Long']})).id;
  check(AP && Q1, 'the agent posts an approval card and a question (setup)');

  await firefox(async o => {
    const {ev, nav, shot, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof ccCommentHtml === 'function' && !!document.querySelector('#view [data-id="${T}"], #view #t-${T}, #view .task')`), 'Firefox: the list');
    // ================= #1383 badge on the row
    check(await ready(`!!document.querySelector('#view .apvc')`, 20), '#1383: the task row shows the open approval (lock)');
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${AP}"] .cccard.apvopen')`), '#1383: the approval card in the comment');
    const card = await ev(`(() => { const e = document.querySelector('#d-tl-items .cm[data-cid="${AP}"] .cccard'); return {head: e.querySelector('.apvh')?.textContent, title: e.querySelector('.apvt')?.textContent, what: e.querySelector('.apvw')?.textContent, n: e.querySelectorAll('.cchb').length, edge: getComputedStyle(e).borderLeftColor}; })()`);
    check(card.head === 'Approval needed' && card.title === 'Publish the draft' && /online/.test(card.what || '') && card.n === 2, '#1383: heading, title, what, Yes / No ' + JSON.stringify(card));
    // the question's buttons with pens: the pen fills the box, nothing is sent
    check(await ev(`document.querySelectorAll('#d-tl-items .cm[data-cid="${Q1}"] .cchoices .cchb').length === 2 && document.querySelectorAll('#d-tl-items .cm[data-cid="${Q1}"] .cchpen').length === 2`), '#1383: the answer buttons with pens');
    await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${Q1}"] .cchpen[data-ch="Long"]').click(); return 1; })()`);
    await sleep(300);
    check(await ev(`document.querySelector('#c-input').value === 'Long' && S.tl.comments.length === 2`), '#1383: the pen puts the text into the comment box, nothing sent');
    await ev(`(() => { const i = document.querySelector('#c-input'); i.value = ''; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    // a press on Yes answers the card
    await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${AP}"] .cccard .cchb[data-ch="yes"]').click(); return 1; })()`);
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${AP}"] .cccard .cpermst.ok')`), '#1383: the card is answered');
    const done = await ev(`document.querySelector('#d-tl-items .cm[data-cid="${AP}"] .cccard .cpermst').textContent`);
    check(/Yes, go ahead from Alice, \d/.test(done || ''), '#1383: "Yes, go ahead from Alice, <date>" ' + done);
    await shot('p2410f-card.png');
    // a press on a suggestion sends it as my comment
    await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${Q1}"] .cchb[data-ch="Short"]').click(); return 1; })()`);
    check(await ready(`S.tl.comments.some(c => c.body === 'Short' && c.user_id === S.me.id && c.reply_to === ${Q1})`), '#1383: a press sends the text as my comment');
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${Q1}"] .cchoices.done .cchb.on')`), '#1383: the pressed button stays marked');
    // a newer question: the old buttons are gone
    const Q2 = (await agc({body: 'And the colour?', choices: ['Blue', 'Green']})).id;
    const Q3 = (await agc({body: 'Or rather?', choices: ['Red']})).id;
    await ev(`(() => { loadTimeline(${T}); return 1; })()`);
    check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${Q3}"] .cchb') && !document.querySelector('#d-tl-items .cm[data-cid="${Q2}"] .cchb')`), '#1383: only the newest question keeps its buttons (#1037)');
    check(await ev(`!document.querySelector('#view .apvc')`), '#1383: the row has no open approval any more');
    check(await ev(`[...document.querySelectorAll('#d-tl-items .actl')].some(e => /approved/.test(e.textContent))`) || await ev(`!showAct()`), '#1383: the history line (when the history is shown)');
    // the agent chat still uses its card through the shared component
    const html = await ev(`apvHtml({id: 9, choices: {choices: [{id: 'yes', label: 'Yes'}, {id: 'no', label: 'No'}], approval: {title: 'X', std: 1}}, choice: {ids: ['yes'], at: new Date().toISOString(), user_id: S.me.id}}, 'answered')`);
    check(/cpermst ok/.test(html) && /Approved by Alice at/.test(html), '#1383: the chat card (shared component) ' + html);
    const btns = await ev(`chatChoicesHtml({id: 7, from: 'agent', choices: {choices: [{id: 'a', label: 'A'}], multi: false}, choice: null, choice_state: 'open'})`);
    check(/data-act="chat-choice" data-mid="7" data-cid="a"/.test(btns) && /data-chpen="7"/.test(btns), '#1383: the chat buttons keep their attributes ' + btns);

    // ================= #1376 live updates per area (measurement: the old way S.lpOff = true vs the new one)
    await ev(`(() => { closeDetail(); go('l/${L}'); return 1; })()`).catch(() => {});
    await nav(B + '#l/' + L);
    check(await ready(`typeof lpLive === 'function' && !!document.querySelector('#view') && !!S.lpA`, 40), '#1376: the poll knows the areas (a)');
    await ev(`(() => { window.__lp = {r: 0, st: 0, b: 0}; const R0 = render; render = function () { window.__lp.r++; return R0.apply(this, arguments); };
      const F0 = window.fetch; window.fetch = async function (u, o) { const r = await F0.call(this, u, o); if (String(u).includes('/api/state')) { window.__lp.st++; try { window.__lp.b += (await r.clone().text()).length; } catch {} } return r; }; return 1; })()`);
    const caught = () => ready(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.v === S.v && !td_polling)`, 120);
    const measure = async (off, tag) => {
      await ev(`(() => { S.lpOff = ${off}; window.__lp.r = 0; window.__lp.st = 0; window.__lp.b = 0; return 1; })()`);
      // 2.206.0 B (#2513): each comment waits until the page took it (its poll saw the version) instead of 4.5 s; the new way's
      // bundled follow-up (LP_DEFER_MS 15 s) runs at once instead of a 17 s wait (still inside the window)
      for (let i = 0; i < 4; i++) { await agc({body: `${tag} note ${i}`}); await caught(); }
      if (!off) await ev(`(async () => { if (lpT) { clearTimeout(lpT); await lpFollow(); } return 1; })()`);
      await caught(); await sleep(600);  // + the bundled redraw after a full load (TD_RS_MS)
      return ev(`({...window.__lp})`);
    };
    const before = await measure(true, 'old');
    // the sidebar keeps its nodes, a half-filled form in the view stays (new way)
    await ev(`(() => { const r = document.querySelector('#side .srow'); if (r) r.__lpKeep = 1; const f = document.createElement('form'); f.dataset.fg = 'lp-test'; f.id = 'lpform'; f.innerHTML = '<input id="lpf" value="">'; document.querySelector('#view').appendChild(f); const i = f.querySelector('input'); i.value = 'half filled'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const after = await measure(false, 'new');
    console.log(`PERF #1376 4 comments of an agent in 20 s, list open: old way ${before.r} render() / ${before.st} state loads / ${Math.round(before.b / 1024)} kB; new way ${after.r} render() / ${after.st} state loads / ${Math.round(after.b / 1024)} kB`);
    check(after.r < before.r && after.st < before.st, `#1376: fewer full redraws and state loads ${JSON.stringify({before, after})}`);
    check(await ev(`document.querySelector('#side .srow')?.__lpKeep === 1`), '#1376: comments arriving: the sidebar keeps its nodes (no flicker)');
    check(await ev(`document.querySelector('#lpf')?.value === 'half filled'`), '#1376: a half-filled form stays while comments arrive');
    // a change of the tasks area while the form has unsaved input: no redraw until it is saved / discarded
    await call(null, 'POST', '/api/v1/tasks', {title: 'Made by the agent', list_id: L}, AGH);
    await ready(`S.viewStale === true`, 120);  // 2.206.0 B (#2513): the poll held the redraw back, instead of a fixed 6 s
    check(await ev(`document.querySelector('#lpf')?.value === 'half filled' && S.viewStale === true`), '#1376: unsaved input holds the full redraw back');
    await ev(`(() => { fgDone('lp-test'); document.querySelector('#lpform')?.remove(); return 1; })()`);
    check(await ready(`!S.viewStale && [...document.querySelectorAll('#view .ttl, #view .title')].some(e => /Made by the agent/.test(e.textContent)) || [...document.querySelectorAll('#view')].some(e => /Made by the agent/.test(e.textContent))`, 30), '#1376: afterwards the view follows');

    // ================= #1437 the import message stays
    const BK = (await call(CA, 'POST', '/api/books', {name: 'Test'})).id;
    await ev(`(() => { const cards = Array.from({length: 150}, (_, i) => 'BEGIN:VCARD\\r\\nVERSION:3.0\\r\\nUID:ui-' + i + '\\r\\nFN:Test Person ' + i + '\\r\\nEND:VCARD').join('\\r\\n'); ctImpRun(${BK}, new File([cards], 'c.vcf', {type: 'text/vcard'})); return 1; })()`);
    check(await ready(`!!document.querySelector('#ctimp .pbar') && /Import running/.test(document.querySelector('#ctimp').textContent)`, 8), '#1437: "Import running…" at once');
    check(await ready(`/Imported: 150 new, 0 updated/.test(document.querySelector('#ctimp')?.textContent || '')`, 60), '#1437: the result (background import)');
    await sleep(7000);
    check(await ev(`!!document.querySelector('#ctimp') && !document.querySelector('#ctimp [data-ctimp="close"]').hidden`), '#1437: the result stays (no 6-second toast) with a close button');
    await ev(`(() => { document.querySelector('#ctimp [data-ctimp="close"]').click(); return 1; })()`);
    check(await ev(`!document.querySelector('#ctimp')`), '#1437: closed with the x');
    // a failure: also a message that stays
    await ev(`(() => { ctImpRun(${BK}, new File(['no vcard here'], 'x.vcf')); return 1; })()`);
    check(await ready(`/Import failed/.test(document.querySelector('#ctimp')?.textContent || '')`, 20), '#1437: a failure shows a message that stays');
  }, false);

  console.log(`p2410_f_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
