// 2.64.1 part D (#1817): the lock per list - dialogs and display, plus #1518. Own container (start.sh), Firefox.
// The data layer (liste2e.js, part C) and the server routes (part A) are stubbed here: the lock state is set on the list in
// the client and le2eInfo / le2eStart / le2eRelease / ... are replaced, so this suite checks only what part D draws:
// - list dialog: section "Encrypted in the browser", the switch, blockers with their way, the notice before switching on
//   (points 1-4, members yes / no, waiting list with names, attachments, limit, recovery code), OK only after "I have read
//   this", progress while switching
// - share dialog: key present / key pending (+ Release) / not set up, safety number, key change warning, rotation pending,
//   no participant role, agents greyed out
// - display: lock in the sidebar and the header, placeholder per task, unlock hint in the detail, the bar (unlock, waiting)
// - greyed out: save as template, playbook, mail address of the list, lock note; News kind e2e_key, entries with enc
// - Settings > Administration > Encryption: the third category; #1518: "You switched encryption on", aria-label
// - every visible button in the new dialogs has a name
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264a_d_ui', check, shots: 'P264AD_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };

// #1518: the German texts (static check of the language file)
const I18N = path.join(__dirname, '..', 'static', 'i18n');
const de = JSON.parse(fs.readFileSync(path.join(I18N, 'de.json'), 'utf8'));
check(de['You switched encryption on'] === 'Du hast die Verschlüsselung eingeschaltet' && de['You switched encryption off'] === 'Du hast die Verschlüsselung ausgeschaltet', '#1518: own German texts "Du hast …"');
// 2.64.2 D (#1817): the key changes now (rotation); the honest text says so while it runs
check(/Der Schlüssel wird gewechselt/.test(de['A member has left this list. The key is being changed; until everything is encrypted again, former members can still decrypt older contents with their old key.'] || ''), '#1817 E8: the honest leave text in German');
for (const f of fs.readdirSync(I18N).filter(x => x.endsWith('.json'))) {
  const j = JSON.parse(fs.readFileSync(path.join(I18N, f), 'utf8'));
  check(j['Encrypted in the browser'] && j['Not available in encrypted lists'] && j['You switched encryption on'], `#1817: the new texts are in ${f}`);
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).j.me?.id || 1;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).j.id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).j.id;
  const L = (await call('POST', '/api/lists', {name: 'Safe'})).j.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: CAROL, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Plan', list_id: L, content: 'text'})).j.id;
  // Settings > Administration > Encryption: the server sends the third category and the note for the plain list
  const sc = (await call('GET', '/api/admin/orgcrypt')).j.scope || {};
  check(Array.isArray(sc.browser) && /lists with a lock/.test(sc.browser.join(' ')) && /except in lists with a lock/.test(sc.plain_note || '') && (sc.plain || []).includes('Tasks'),
    '#1817: the encryption overview gets "Encrypted in the browser (lists with a lock)" ' + JSON.stringify(sc));

  await firefox(async ({cmd, ev: ev0, nav, ctx, shot}) => {
    const UP = `typeof E2E === 'object' && typeof S === 'object' && !!S.booted`;
    // 2.87.0: the slow CI runner sometimes reloads the page between two steps: a ReferenceError (E2E / S not yet defined) waits for the boot and retries
    // 2.88.1: on CI the app can be "up" and the next step still meets no E2E (seen right after the second boot): the 2nd try
    // loads the page again (only used right after a boot, see stub), the error then says what the page looked like
    const DIAG = `[location.href, document.readyState, performance.getEntriesByType('navigation')[0]?.type, Math.round(performance.now()), typeof E2E, typeof S, typeof S === 'object' && S.booted, !!navigator.serviceWorker?.controller, sessionStorage.getItem('kalmido-rl-n'), document.scripts.length].join(' | ')`;
    let lastHash = '';
    const ev = async (expr, reboot) => { for (let i = 0; ; i++) { try { return await ev0(expr); } catch (e) {
      if (!/ReferenceError: \w+ is not defined/.test(e.message)) throw e;
      const d = await ev0(DIAG).catch(x => 'no diag: ' + x.message);
      if (i >= 2) throw new Error(e.message + ' (page: ' + d + ')');
      console.log('p264a_d_ui: ' + e.message + ', try ' + (i + 1) + ' (page: ' + d + ')');
      if (reboot && i === 1) await boot(lastHash);
      for (let k = 0; k < 75 && !(await ev0(UP).catch(() => false)); k++) await sleep(200); } } };
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    // 2.88.1 (CI): the second boot sometimes ends on a page without the app (E2E never defined, also after 45 s of waiting) - the
    // app is up only when its globals are there (S is a const: window.S never exists); otherwise say where the page is and load again
    const boot = async hash => {
      lastHash = hash;
      for (let a = 0; a < 3; a++) {
        await nav(B + 'static/icon.svg'); await nav(B + hash);
        if (await waitFor(UP, 60)) { await sleep(500); return; }
        console.log('p264a_d_ui: no app after loading ' + hash + ' (try ' + (a + 1) + '): ' + await ev0(`[location.href, document.readyState, document.title, document.scripts.length, typeof S, typeof E2E].join(' | ')`).catch(e => e.message));
      }
    };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 800, height: 760}});
    await boot('#l/' + L);
    // every visible button / switch inside el has a name (aria-label, text or title)
    const unnamed = sel => ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].filter(b => b.offsetParent && !(b.getAttribute('aria-label') || b.textContent.trim() || b.title || b.labels?.[0]?.textContent.trim())).map(b => b.outerHTML.slice(0, 120))`);
    // the stubs of the data layer (part C) and of the person's keys (e2e.js): recorded calls in window.__c
    const stub = info => ev(`(() => { window.__c = []; window.__info = ${JSON.stringify(info)};
      E2E.st = {set: true, password: true}; window.e2eLoad = async () => E2E.st; window.e2eEnsure = async () => true;
      window.le2eInfo = async () => JSON.parse(JSON.stringify(window.__info));
      window.le2eStart = async (lid, onP) => { __c.push(['start', lid]); onP({done: 1, total: 4}); await new Promise(r => setTimeout(r, 1500)); onP({done: 4, total: 4}); };
      window.le2eRelease = async (lid, ids) => { __c.push(['release', lid, ids]); };
      window.le2eUnlock = async lid => { __c.push(['unlock', lid]); };
      window.le2eSafety = async uid => '12345 67890 11111 22222 33333 44444 55555 66666';
      window.le2eKeyChanged = uid => uid === ${BOB};
      window.le2eAcceptKey = uid => { __c.push(['accept', uid]); };
      window.le2eReady = () => false;
      window.le2eLocked = t => !!t && t.list_id === ${L};
      return 1; })()`, true);
    const setList = o => ev(`(() => { Object.assign(listById(${L}), ${JSON.stringify(o)}); render(); return 1; })()`);
    const people = [{user_id: ME, name: 'Alice', role: 'owner', kind: 'person', has_keys: true, pub: {kty: 'EC', crv: 'P-256', x: 'a', y: 'b'}, key_gens: [1]},
      {user_id: BOB, name: 'Bob', role: 'edit', kind: 'person', has_keys: true, pub: {kty: 'EC', crv: 'P-256', x: 'c', y: 'd'}, key_gens: []},
      {user_id: CAROL, name: 'Carol', role: 'edit', kind: 'person', has_keys: false, pub: null, key_gens: []}];

    // ---- #1518: the system texts of an encrypted DM and the aria-label of "Attach encrypted"
    const sys = await ev(`(() => { S.tc = S.tc || {}; S.tc.users = S.tc.users || {}; S.tc.users[${BOB}] = 'Bob';
      return [e2eMsgBody({enc: {sys: 'on'}, user_id: S.me.id}), e2eMsgBody({enc: {sys: 'off'}, user_id: S.me.id}), e2eMsgBody({enc: {sys: 'on'}, user_id: ${BOB}})]; })()`);
    check(/You switched encryption on/.test(sys[0]) && /You switched encryption off/.test(sys[1]) && /Bob switched encryption on/.test(sys[2]) && !/You switched encryption on/.test(sys[2]), '#1518: own texts for "you" ' + JSON.stringify(sys));
    check(await ev(`(() => { const st = E2E.st; E2E.st = {set: true}; const h = e2eAttAddHtml({id: 5}); E2E.st = st; const d = document.createElement('div'); d.innerHTML = h; return !!d.querySelector('label[aria-label="Attach encrypted"]') && !!d.querySelector('input[aria-label="Attach encrypted"]'); })()`), '#1518: "Attach encrypted" has an aria-label');
    // ---- Administration overview: three categories
    check(await ev(`(() => { const d = document.createElement('div'); d.innerHTML = pm_cryptScopeHtml(${JSON.stringify(sc)}); return d.querySelectorAll('.pmcs').length === 3 && /lists with a lock/.test(d.querySelector('.pmcs.br')?.textContent || '') && /except in lists with a lock/.test(d.querySelector('.pmcs.off .pmcsn')?.textContent || ''); })()`),
      '#1817: Settings > Administration > Encryption shows the third category and "except in lists with a lock"');

    // ---- list dialog, open list with blockers
    await stub({list_id: L, mode: null, gen: 0, rotate: 0, can_manage: true, keys: [], pending: [], members: people, agents: [],
      blockers: [{code: 'agent', text: 'An agent is in this list.'}, {code: 'public_link', text: 'This list has a public link.'}, {code: 'org_open', text: 'Everyone in the organisation may join.'}, {code: 'participant', text: 'Bob is a participant.'},
        // 2.64.1 review (L4, M2): the server's folder code and the owner's set-up have their way too
        {code: 'folder_participant', text: 'A folder share reaches this list.'}, {code: 'owner_setup', text: 'The owner needs to set up encryption first.'}], left: {}});
    await ev(`(listModal(${L}), 1)`);
    const sec = await waitFor(`(() => { const b = document.querySelector('#l-e2e'); return b && b.querySelector('#l-e2e-sw') ? b.textContent : ''; })()`);
    check(sec && /Remove the agent first/.test(sec) && /Delete the public link first/.test(sec) && /Everyone in the organisation/.test(sec) && /Change the participant role first/.test(sec), '#1817: blockers with a clear text and the way ' + sec);
    check(/Change the participant role of the folder first/.test(sec) && /The owner sets it up in Settings > Account/.test(sec), '2.64.1 review (L4/M2): folder_participant and owner_setup show their way ' + sec);
    check(await ev(`document.querySelector('#l-e2e-sw').disabled && /Encrypted in the browser/.test(document.querySelector('#l-e2e-h').textContent)`), '#1817: section "Encrypted in the browser", switch off while something blocks');
    check(!(await unnamed('#l-e2e button, #l-e2e input')).length, '#1817: the buttons of the lock section have names');
    await ev(`(document.querySelector('.lmodal [data-m="close"]')?.click(), 1)`); await sleep(300);

    // ---- no blockers: the notice, OK only after "I have read this", then the progress
    await ev(`(window.__info.blockers = [], 1)`);
    await ev(`(listModal(${L}), 1)`);
    await waitFor(`!!document.querySelector('#l-e2e-sw') && !document.querySelector('#l-e2e-sw').disabled`);
    await ev(`(() => { const s = document.querySelector('#l-e2e-sw'); s.checked = true; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    const note = await waitFor(`document.querySelector('.cdlg .le2unote') ? document.querySelector('.cdlg #cdlg-b').textContent : ''`);
    check(note && /not even the operator/.test(note) && /manipulated server/.test(note) && /no agents, no tasks by e-mail/.test(note) && /needs encryption set up/.test(note), '#1817: the notice before switching on (points 1-4) ' + (note || '').slice(0, 200));
    check(/Carol: not set up yet/.test(note || '') && /waiting list/.test(note || ''), '#1817 E7: members without encryption go on the waiting list, by name');
    // 2.64.2 D (#1817): attachments are encrypted with the list key now (the E9 hint is gone)
    check(/Attachments and the messages of the list chat are encrypted with it/.test(note || '') && /recovery code is enough/.test(note || '') && /End-to-end in the browser/.test(note || '') && /Limit/.test(note || ''), '#1817 2.64.2 / E5 / E10: attachments, recovery code, the limit');
    check(await ev(`document.querySelectorAll('.cdlg .le2umem li.ok').length === 2 && document.querySelectorAll('.cdlg .le2umem li.no').length === 1`), '#1817: the members with yes / no "Encryption set up"');
    check(await ev(`document.querySelector('.cdlg [data-cd="yes"]').disabled`), '#1817: OK only after "I have read this"');
    check(!(await unnamed('.cdlg button, .cdlg input')).length, '#1817: every button of the notice has a name');
    await sleep(900); await shot('p264a-d-notice.png');  // phones: the dialog slides in first
    await ev(`(() => { const c = document.getElementById('le2u-ack'); c.checked = true; c.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ev(`!document.querySelector('.cdlg [data-cd="yes"]').disabled`), '#1817: "I have read this" enables OK');
    await ev(`(document.querySelector('.cdlg [data-cd="yes"]').click(), 1)`);
    const prog = await waitFor(`document.querySelector('#le2ubar .le2upb') || document.querySelector('#l-e2e .le2upb') ? 1 : 0`);
    check(prog && await ev(`__c.some(c => c[0] === 'start' && c[1] === ${L})`), '#1817: switching on runs le2eStart with a progress bar');
    await sleep(2000);
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);

    // ---- share dialog of a locked list: key state per person
    await stub({list_id: L, mode: 'on', gen: 1, rotate: 1, can_manage: true, keys: [{gen: 1}], members: people, agents: [], blockers: [],
      pending: [{user_id: BOB, name: 'Bob', since: '2026-10-17T01:00:00', has_keys: true}, {user_id: CAROL, name: 'Carol', since: '2026-10-17T01:00:00', has_keys: false}], left: {}});
    await ev(`(window.le2eKeyChanged = () => false, 1)`);
    await setList({e2e: 'on', e2e_gen: 1, e2e_rotate: 1, e2e_pending: 2, e2e_mine: true});
    await ev(`(shareModal(${L}), 1)`);
    const sh = await waitFor(`document.querySelectorAll('.shmodal .le2ust').length >= 3 ? document.querySelector('.shmodal').textContent : ''`);
    check(sh && /Key present/.test(sh) && /Key pending/.test(sh) && /Has not set up encryption yet/.test(sh), '#1817: member states key present / pending / not set up');
    check(await ev(`!!document.querySelector('.shmodal .mrow[data-uid="${BOB}"] [data-le2us="release"]') && !document.querySelector('.shmodal .mrow[data-uid="${CAROL}"] [data-le2us="release"]')`), '#1817: "Release" only for a waiting person with encryption set up');
    check(await ev(`!!document.querySelector('.shmodal .mrow[data-uid="${BOB}"] [data-le2us="safety"]')`), '#1817: a safety number per person');
    // 2.64.2 D (#1817): the hint now says the key is being changed (rotation in 2.64.2)
    check(/former members can still decrypt older contents with their old key/.test(sh || ''), '#1817 E8: the honest hint while a rotation is pending');
    check(await ev(`![...document.querySelectorAll('.shmodal select option')].some(o => o.value === 'participant')`), '#1817 E4: no participant role in a locked list');
    check(await ev(`!document.querySelector('.shmodal #sh-agwrap') || /Not available in encrypted lists/.test(document.querySelector('.shmodal #sh-agwrap').textContent)`), '#1817: agents greyed out with the reason');
    check(!(await unnamed('.shmodal button, .shmodal select')).length, '#1817: every button of the share dialog has a name ' + JSON.stringify(await unnamed('.shmodal button, .shmodal select')));
    await sleep(900); await shot('p264a-d-members.png');
    await ev(`(document.querySelector('.shmodal .mrow[data-uid="${BOB}"] [data-le2us="release"]').click(), 1)`);
    check(await waitFor(`__c.some(c => c[0] === 'release' && c[1] === ${L} && c[2].length === 1 && c[2][0] === ${BOB})`), '#1817: "Release" hands the key to the waiting person (le2eRelease)');
    await ev(`(document.querySelector('.shmodal .mrow[data-uid="${BOB}"] [data-le2us="safety"]')?.click(), 1)`);
    check(await waitFor(`/12345 67890/.test(document.querySelector('.cdlg')?.textContent || '')`), '#1817: the safety number dialog');
    await ev(`(document.querySelector('.cdlg [data-cd="no"]')?.click(), 1)`); await sleep(200);
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
    // a key change: the warning, "Understood"
    await ev(`(window.le2eKeyChanged = uid => uid === ${BOB}, 1)`);
    await setList({e2e: 'on', e2e_gen: 1, e2e_rotate: 1, e2e_pending: 2, e2e_mine: true});  // a load() after the release reset the client state
    await ev(`(shareModal(${L}), 1)`);
    check(await waitFor(`/The key of Bob has changed/.test(document.querySelector('.shmodal .le2uchg')?.textContent || '')`), '#1817 H4: a warning when the key of a person changed');
    check(await ev(`!document.querySelector('.shmodal .mrow[data-uid="${BOB}"] [data-le2us="release"]')`), '#1817 H4: no release to a changed key before it is accepted');
    await ev(`(document.querySelector('.shmodal .le2uchg [data-le2us="accept"]').click(), 1)`);
    check(await waitFor(`__c.some(c => c[0] === 'accept' && c[1] === ${BOB}) && !document.querySelector('.shmodal .le2uchg')`), '#1817 H4: "Understood" accepts the new key');
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);

    // ---- display: marks, placeholder, detail, the bar
    await boot('#l/' + L);
    await stub({list_id: L, mode: 'on', gen: 1, rotate: 0, can_manage: true, keys: [{gen: 1}], members: people, pending: [], agents: [], blockers: [], left: {}});
    await setList({e2e: 'on', e2e_gen: 1, e2e_rotate: 0, e2e_pending: 0, e2e_mine: true});
    check(await waitFor(`!!document.querySelector('#side [data-list="${L}"] .le2um, #side .srow[data-list="${L}"] .le2um')`), '#1817: the lock at the list name in the sidebar');
    check(await ev(`!!document.querySelector('#top h1 .le2um')`), '#1817: the lock in the header of the list');
    check(await waitFor(`/Encrypted – unlock/.test(document.querySelector('#view .trow[data-id="${T}"] .le2uph')?.textContent || '')`), '#1817: a placeholder per task while the list is not unlocked');
    check(/Encrypted list: unlock/.test(await ev(`document.querySelector('#le2ubar')?.textContent || ''`)), '#1817: the bar offers to unlock');
    await ev(`(document.querySelector('#view .trow[data-id="${T}"] .le2uph').click(), 1)`);
    check(await waitFor(`__c.some(c => c[0] === 'unlock' && c[1] === ${L})`), '#1817: a click on the placeholder unlocks (le2eUnlock)');
    // 2.64.1 review (L5): reachable with Tab, Enter unlocks
    const nU = await ev(`__c.filter(c => c[0] === 'unlock').length`);
    check(await ev(`(() => { const p = document.querySelector('#view .trow[data-id="${T}"] .le2uph'); if (!p || p.tabIndex !== 0) return false; p.focus(); p.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return true; })()`)
      && await waitFor(`__c.filter(c => c[0] === 'unlock').length > ${nU}`), '2.64.1 review (L5): the placeholder takes the focus and Enter unlocks');
    await shot('p264a-d-list.png');
    await ev(`(openDetail(${T}), 1)`);
    check(await waitFor(`!!document.querySelector('#detail .le2ud [data-le2u="unlock"]') && !document.querySelector('#detail #d-content') && document.querySelector('#detail .dtitle').hidden`), '#1817: the detail shows the unlock hint instead of title and description');
    await setList({e2e_pending: 2});
    check(/2 people are waiting for the key/.test(await ev(`document.querySelector('#le2ubar')?.textContent || ''`)), '#1817: the bar for the owner: 2 people waiting, Release');
    await setList({e2e_pending: 0, e2e_mine: false});
    check(await waitFor(`/Key pending – Alice has to release it/.test(document.querySelector('#view .trow[data-id="${T}"] .le2uph')?.textContent || '')`), '#1817: a waiting member sees "Key pending – <name> has to release it"');

    // ---- greyed out in a locked list
    await setList({e2e: 'on', e2e_mine: true});
    await ev(`(listModal(${L}), 1)`);
    check(await waitFor(`(() => { const b = document.querySelector('.lmodal [data-m="tpl"]'); return b && b.disabled && /Not available in encrypted lists/.test(b.title); })()`), '#1817: "Save as template" greyed out with the reason');
    check(await waitFor(`/On/.test(document.querySelector('#l-e2e #l-e2e-st')?.textContent || '') && !!document.querySelector('#l-e2e [data-le2ul="stop"]')`), '#1817: the owner sees the way back ("Open the lock…")');
    check(!(await unnamed('#l-e2e button')).length, '#1817: the buttons of the lock section (on) have names');
    await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
    check(await ev(`!ln_listOk(listById(${L}))`), '#1817: no "Lock note" (2.48) in a locked list');
    check(await ev(`(() => { const h = mailHtml({enabled: true, address: 'in@example.com', plain: 'in@example.com', email: '', lists: [{list_id: ${L}, name: 'Safe', address: 'safe@example.com'}]}); return !h.includes('safe@example.com') && /Create tasks by e-mail/.test(h) && /address of this list is off/.test(h); })()`), '#1817: "Create tasks by e-mail" greyed out with the reason');
    check(await ev(`/released the key for/.test(newsText({kind: 'e2e_key', list_id: ${L}, actor_id: ${BOB}, data: {}}, {${BOB}: 'Bob'}))`), '#1817: News "<name> released the key for <list> to you"');
    check(await ev(`(() => { S.nf.users = S.nf.users || {}; const h = newsItemHtml({kind: 'comment', enc: true, task_id: ${T}, task_title: null, list_id: ${L}, excerpt: 'e2e1:x', actor_id: ${BOB}, created_at: new Date().toISOString(), count: 1}, 0); return /Encrypted task/.test(h) && !h.includes('e2e1:'); })()`), '#1817: a News entry of a locked list: no excerpt, the title neutral until decrypted');
    check(await ev(`/Lists with a lock/.test(le2u_helpHtml())`), '#1817: in-app help: a short part "Lists with a lock"');
    // ---- 2.85.0 (#1904): fresh load, keys state not yet fetched -> no "not set up" hint, the switch is free
    await ev(`(() => { document.querySelector('.lmodal [data-m="close"]')?.click(); window.__info = {list_id: ${L}, mode: null, gen: 0, rotate: 0, can_manage: true, keys: [], pending: [], members: [], agents: [], blockers: [], left: {}};
      E2E.st = null; window.e2eLoad = async () => (E2E.st = {set: true, password: true}); return 1; })()`); await sleep(300);
    await ev(`(listModal(${L}), 1)`);
    check(await waitFor(`(() => { const s = document.querySelector('#l-e2e-sw'); return !!s && !s.disabled; })()`), '#1904: the lock switch is free after a fresh load');
    check(await ev(`!/not set up yet/.test(document.querySelector('#l-e2e')?.textContent || '')`), '#1904: no "not set up yet" hint when the passphrase exists');
  }, false);

  console.log(`p264a_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
