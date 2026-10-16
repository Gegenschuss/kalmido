// 2.48.0 part C (#1642): lock a task's note with one's own password, own container (start.sh), Firefox (real WebCrypto):
// - "Lock note" under the description of a task in an own, unshared list; the first time: the warning (lost = lost), then
//   the setup of the passphrase and the recovery code (with Print); the note is locked: the server keeps only ciphertext
// - after a reload the note shows locked ("Unlock to view"); unlocking asks for the passphrase and shows the text
// - a change of the unlocked note is saved encrypted (the plain note on the server stays empty)
// - "Remove lock" makes it a normal note again (the changed text); no "Lock note" in a shared list
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p248_c_lock_ui', check, shots: 'P248C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const SECRET = 'Garden plan: the key is under the blue pot';
const PASS = 'correct horse battery staple';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Private'})).j.id;
  const LS = (await call('POST', '/api/lists', {name: 'Shared'})).j.id;
  await call('PUT', `/api/lists/${LS}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Garden', list_id: L, content: SECRET})).j.id;
  const TS = (await call('POST', '/api/tasks', {title: 'Team', list_id: LS, content: 'shared text'})).j.id;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash);  // a real page load each time
      await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#t/' + TS);
    check(await waitFor(`!!document.querySelector('#d-content')`) && !(await ev(`!!document.querySelector('[data-ln="lock"]')`)), '#1642: no "Lock note" in a shared list');
    await boot('#t/' + T);
    check(await waitFor(`!!document.querySelector('[data-ln="lock"]')`), '#1642: "Lock note" under the description of an own, unshared list');
    await ev(`(document.querySelector('[data-ln="lock"]').click(), 1)`);
    const warn = await waitFor(`document.querySelector('.cdlg #cdlg-b')?.textContent || ''`);
    check(/lost/.test(warn || '') && /not even the operator/.test(warn || ''), '#1642: the first lock warns clearly: lost = lost, not even the operator ' + warn);
    await ev(`(document.querySelector('.cdlg [data-cd="yes"]').click(), 1)`);
    check(await waitFor(`!!document.querySelector('#e2e-p1')`), '#1642: set up the passphrase (no keys yet)');
    await ev(`(() => { const s = (id, v) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }; s('e2e-p1', ${JSON.stringify(PASS)}); s('e2e-p2', ${JSON.stringify(PASS)}); document.querySelector('.e2edlg form').requestSubmit(); return 1; })()`);
    check(await waitFor(`!!document.querySelector('#e2e-code')`, 160), '#1642: the recovery code is shown');
    check(await ev(`!!document.querySelector('.e2edlg [data-m="print"]')`), '#1642: the recovery code can be printed');
    await shot('p248c-lock-code.png');
    await ev(`(() => { const c = document.getElementById('e2e-noted'); c.checked = true; c.dispatchEvent(new Event('change', {bubbles: true})); document.querySelector('.e2edlg [data-m="done"]').click(); return 1; })()`);
    const locked = await waitFor(`(() => { const t = S.tasks.get(${T}); return t && t.note_locked && !t.content && !!document.querySelector('#d-ln') ? 1 : 0; })()`, 80);
    check(locked, '#1642: the note is locked (the task shows the locked note)');
    let s = await call('GET', '/api/state');
    const st = (s.j.tasks || []).find(t => t.id === T);
    const lk = await call('GET', `/api/tasks/${T}/note-lock`);
    check(st && st.content === '' && st.note_locked && lk.status === 200 && lk.j.body?.ct && !JSON.stringify(lk.j).includes('blue pot'),
      '#1642: the server keeps only ciphertext, the plain note is empty');
    check(!(await ev(`JSON.stringify(HIST.undo).includes('blue pot') || JSON.stringify(HIST.redo).includes('blue pot') || (localStorage.getItem('cache') || '').includes('blue pot') || (localStorage.getItem('outbox') || '').includes('blue pot')`)),
      '#1642: no plain copy stays in this tab (undo steps, offline cache, outbox)');
    await shot('p248c-lock-locked.png');
    // a reload: still locked; the passphrase unlocks it (once per session)
    await boot('#t/' + T);
    check(await waitFor(`!!document.querySelector('#d-ln .lnopen')`) && !(await ev(`!!document.querySelector('#d-content')`)), '#1642: after a reload the note is locked ("Unlock to view")');
    await ev(`(document.querySelector('#d-ln .lnopen').click(), 1)`);
    const pw = await waitFor(`!!document.querySelector('#e2e-pw')`);
    if (pw) await ev(`(() => { document.getElementById('e2e-pw').value = ${JSON.stringify(PASS)}; document.querySelector('.e2edlg form').requestSubmit(); return 1; })()`);
    const txt = await waitFor(`document.querySelector('#d-ln-in')?.value || ''`, 160);
    check(pw && txt === SECRET, '#1642: the passphrase unlocks it, the text shows ' + JSON.stringify(txt));
    await shot('p248c-lock-open.png');
    // a change is saved encrypted
    const ct0 = lk.j.body.ct;
    await ev(`(() => { const a = document.getElementById('d-ln-in'); a.value = a.value + ' (moved)'; a.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    let ct1 = null;
    for (let i = 0; i < 30; i++) { await sleep(300); ct1 = (await call('GET', `/api/tasks/${T}/note-lock`)).j.body?.ct; if (ct1 && ct1 !== ct0) break; }
    s = await call('GET', '/api/state');
    check(ct1 && ct1 !== ct0 && (s.j.tasks || []).find(t => t.id === T)?.content === '', '#1642: a change is saved as new ciphertext, the plain note stays empty');
    // "Lock now" hides it again without asking (the keys stay unlocked in this session)
    await ev(`(document.querySelector('#d-ln [data-ln="hide"]').click(), 1)`); await sleep(300);
    check(await ev(`!!document.querySelector('#d-ln .lnopen') && !document.querySelector('#d-ln-in')`), '#1642: "Lock now" hides the text');
    await ev(`(document.querySelector('#d-ln .lnopen').click(), 1)`);
    check(await waitFor(`(document.querySelector('#d-ln-in')?.value || '').includes('(moved)')`) && !(await ev(`!!document.querySelector('#e2e-pw')`)), '#1642: once per session: opening again needs no passphrase');
    // 2.48.0 review (S3): "Lock encryption" / sign out: no decrypted locked note stays in the tab's memory
    await ev(`(e2eLock(), 1)`); await sleep(300);
    check(await ev(`Object.keys(LN.notes).length === 0 && LN.saveT === null && !document.querySelector('#d-ln-in') && !!document.querySelector('#d-ln .lnopen')`),
      '#1642 review: locking the keys empties the decrypted notes and redraws the field');
    // 2.48.0 review (L7): an edit conflict about the note goes with the lock; a waiting batch of the task blocks locking
    check(await ev(`(() => { S.conflicts = [{tid: ${T}, field: 'content', server: 'a', mine: 'b', title: 'x'}, {tid: ${T}, field: 'title', server: 'c', mine: 'd'}]; ln_forget(${T});
      return S.conflicts.length === 1 && !(localStorage.getItem('conflicts') || '').includes('"content"') && ln_outHit({url: '/api/tasks/batch', body: {ids: [${T}]}}, ${T}) && !ln_outHit({url: '/api/tasks/${T}9'}, ${T}); })()`),
      '#1642 review: conflicts about the note go, waiting batches are seen');
    await ev(`(() => { S.conflicts = []; LS.set('conflicts', []); return 1; })()`);
    await ev(`(document.querySelector('#d-ln .lnopen').click(), 1)`);
    if (await waitFor(`!!document.querySelector('#e2e-pw')`)) await ev(`(() => { document.getElementById('e2e-pw').value = ${JSON.stringify(PASS)}; document.querySelector('.e2edlg form').requestSubmit(); return 1; })()`);
    check(await waitFor(`(document.querySelector('#d-ln-in')?.value || '').includes('(moved)')`, 160), '#1642 review: the passphrase opens it again');
    // remove the lock: a normal note again
    await ev(`(document.querySelector('#d-ln [data-ln="remove"]').click(), 1)`);
    await waitFor(`!!document.querySelector('.cdlg [data-cd="yes"]')`);
    await ev(`(document.querySelector('.cdlg [data-cd="yes"]').click(), 1)`);
    const back = await waitFor(`(() => { const t = S.tasks.get(${T}); return t && !t.note_locked && t.content ? t.content : ''; })()`);
    s = await call('GET', '/api/state');
    const st2 = (s.j.tasks || []).find(t => t.id === T);
    check(back === SECRET + ' (moved)' && st2?.content === SECRET + ' (moved)' && !st2.note_locked && await ev(`!!document.querySelector('#d-content') && !document.querySelector('#d-ln')`),
      '#1642: "Remove lock" makes it a normal note again ' + JSON.stringify(back));
  }, false);

  console.log(`p248_c_lock_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
