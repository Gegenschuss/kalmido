// 2.547.0 UI test, part C (#4500): the team chat morphs its live updates instead of rebuilding the message list.
// kalmido-suite: fresh
// Own container (start.sh), jsdom, invented data only. A reaction, an own message and a live update (another person writes
// while I edit) in a room and in a thread keep the nodes of the unchanged messages (the avatar of bob's message, its bubble)
// as the same DOM objects (before, tcPatch / tth_patch rebuilt the box: avatars loaded again, the list flashed); the box keeps
// its scroll and the composer its draft. freelancer-matrix: team -- frida has no organisation: her own private channel.
// P2547C_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2547C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    return {...(await r.json().catch(() => ({}))), status: r.status};
  }
};
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  const st0 = await call(CA, 'GET', '/api/state'), feats = new Set(((st0.settings || {}).features || '').split(',').filter(Boolean)); feats.add('collab');
  const FEAT = [...feats].join(',');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call(CA, 'POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const RID = (await call(CA, 'POST', '/api/team/channels', {name: 'Project', org_id: ORG, open: false, members: [BOB]})).id;
  check(RID > 0, 'a channel of alice and bob');
  const B1 = (await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Hello from Bob'})).id;
  const A1 = (await call(CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Hi Bob'})).id;
  await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Monday works', thread_of: B1});
  check(B1 && A1, 'messages through the API');

  // ================= alice, desktop: the room, then the thread of bob's message
  {
    const w = await boot({user: 'alice', hash: 'team/' + RID}), d = w.document;
    const sel = `#tc-msgs .cmsg[data-mid="t:${B1}"]`;
    const av = await until(() => d.querySelector(`${sel} .tcwho .avatar`));
    const msg = d.querySelector(sel), bub = d.querySelector(`${sel} .cbub`), mine = d.querySelector(`#tc-msgs .cmsg[data-mid="t:${A1}"]`);
    check(av && msg && bub && mine, 'room: bob\'s message with his avatar, my message');
    const box = d.querySelector('#tc-msgs');
    const same = what => { check(d.querySelector(`${sel} .tcwho .avatar`) === av && d.querySelector(sel) === msg && d.querySelector(`${sel} .cbub`) === bub
      && d.querySelector(`#tc-msgs .cmsg[data-mid="t:${A1}"]`) === mine && av.isConnected, `#4500 ${what}: the unchanged messages keep their nodes (avatar, bubble)`);
      check(d.querySelector('#tc-msgs') === box, `#4500 ${what}: the same box`); };
    // a draft in the composer
    const ta = d.querySelector('#tc-in'); ta.value = 'half a thought'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    // a reaction to bob's message: only its reaction row changes
    const chip = d.querySelector(`${sel} .rx[data-act="tc-react"][data-mid="${B1}"]`);
    check(!!chip, 'room: a reaction chip on bob\'s message');
    const e = chip?.dataset.e;
    click(w, chip);
    await until(() => d.querySelector(`${sel} .rx.on[data-e="${e}"]`));
    check(!!d.querySelector(`${sel} .rx.on[data-e="${e}"]`), 'room: the reaction is shown');
    same('reaction');
    check(d.querySelector('#tc-in') === ta && ta.value === 'half a thought', '#4500 reaction: the draft stays');
    // bob writes while alice edits her message (the live update goes through tcPatch then)
    w.eval(`S.tc.edit = ${A1}; S.tc.editTh = false; tcPatch();`);
    const ed = await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${A1}"] .tc-edit`));
    check(!!ed, 'room: my message in edit mode');
    ed.value = 'Hi Bob, edited'; ed.focus();
    const B2 = (await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Are you there?'})).id;
    await w.eval('teamChanged()');
    await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${B2}"]`));
    check(!!d.querySelector(`#tc-msgs .cmsg[data-mid="t:${B2}"]`), 'room: bob\'s new message arrives live');
    check(d.querySelector(`${sel} .tcwho .avatar`) === av && d.querySelector(`${sel} .cbub`) === bub, '#4500 live update: bob\'s first message keeps its nodes');
    check(d.querySelector(`#tc-msgs .cmsg[data-mid="t:${A1}"] .tc-edit`) === ed && ed.value === 'Hi Bob, edited' && d.activeElement === ed, '#4500 live update: the edit box keeps its text and the focus');
    click(w, d.querySelector('[data-act="tc-edit-cancel"]'));
    await until(() => !d.querySelector('#tc-msgs .tc-edit'));
    // an own message: the others stay
    ta.value = 'Sent from the test'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    click(w, d.querySelector('[data-act="tc-send"]'));
    await until(() => [...d.querySelectorAll('#tc-msgs .cmsg[data-mid]')].some(x => /Sent from the test/.test(x.textContent)) && !d.querySelector('#tc-msgs .csdpend'));
    check([...d.querySelectorAll('#tc-msgs .cmsg[data-mid]')].some(x => /Sent from the test/.test(x.textContent)), 'room: my new message is shown');
    check(d.querySelector(`${sel} .tcwho .avatar`) === av && d.querySelector(`${sel} .cbub`) === bub, '#4500 send: bob\'s message keeps its nodes');

    // the thread of bob's message
    w.eval(`tth_open(${RID}, ${B1})`);
    const tsel = `#tth-msgs .cmsg[data-mid="t:${B1}"]`;
    const tav = await until(() => d.querySelector(`${tsel} .tcwho .avatar`));
    const tbub = d.querySelector(`${tsel} .cbub`), tans = await until(() => [...d.querySelectorAll('#tth-msgs .cmsg[data-mid]')].find(x => /Monday works/.test(x.textContent)));
    check(tav && tbub && tans, 'thread: bob\'s first message with his avatar, his answer');
    const tsame = what => check(d.querySelector(`${tsel} .tcwho .avatar`) === tav && d.querySelector(`${tsel} .cbub`) === tbub && tans.isConnected
      && [...d.querySelectorAll('#tth-msgs .cmsg[data-mid]')].includes(tans), `#4500 thread ${what}: the unchanged messages keep their nodes`);
    // a reaction to the answer (tcReact -> tcPatch -> tth_patch)
    const amid = +tans.dataset.mid.split(':')[1];
    const tchip = tans.querySelector(`.rx[data-act="tc-react"][data-mid="${amid}"]`);
    check(!!tchip, 'thread: a reaction chip on bob\'s answer');
    const te = tchip?.dataset.e;
    click(w, tchip);
    await until(() => tans.querySelector(`.rx.on[data-e="${te}"]`));
    check(!!tans.querySelector(`.rx.on[data-e="${te}"]`), 'thread: the reaction is shown on the same answer node');
    tsame('reaction');
    // an own answer in the thread
    const tta = d.querySelector('#tth-in'); tta.value = 'See you then';
    click(w, d.querySelector('[data-act="tth-send"]'));
    await until(() => [...d.querySelectorAll('#tth-msgs .cmsg[data-mid]')].some(x => /See you then/.test(x.textContent)) && !d.querySelector('#tth-msgs .csdpend'));
    check([...d.querySelectorAll('#tth-msgs .cmsg[data-mid]')].some(x => /See you then/.test(x.textContent)), 'thread: my answer is shown');
    tsame('send');
    check(!errs.length, `alice: no JS errors ${errs.join(' | ')}`);
    await sleep(300); w.close();
  }

  // ================= frida (no organisation): her own private channel, an own message keeps the earlier ones
  {
    errs.length = 0;
    await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
    const CF = await login('frida');
    await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
    check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
    const FR = (await call(CF, 'POST', '/api/team/channels', {name: 'Notes to self'})).id;
    check(FR > 0, 'frida: her own private channel');
    const M1 = (await call(CF, 'POST', `/api/team/rooms/${FR}/messages`, {body: 'First idea'})).id;
    const w = await boot({user: 'frida', hash: 'team/' + FR}), d = w.document;
    const fsel = `#tc-msgs .cmsg[data-mid="t:${M1}"]`;
    const fb = await until(() => d.querySelector(`${fsel} .cbub`)), fm = d.querySelector(fsel);
    check(!!fb, 'frida: her first message');
    const ta = d.querySelector('#tc-in'); ta.value = 'Second idea';
    click(w, d.querySelector('[data-act="tc-send"]'));
    await until(() => [...d.querySelectorAll('#tc-msgs .cmsg[data-mid]')].some(x => /Second idea/.test(x.textContent)) && !d.querySelector('#tc-msgs .csdpend'));
    check([...d.querySelectorAll('#tc-msgs .cmsg[data-mid]')].some(x => /Second idea/.test(x.textContent)), 'frida: her second message is shown');
    check(d.querySelector(fsel) === fm && d.querySelector(`${fsel} .cbub`) === fb, '#4500 frida: the first message keeps its nodes');
    check(!errs.length, `frida: no JS errors ${errs.join(' | ')}`);
    await sleep(300); w.close();
  }

  console.log(`p2547_c_tcmorph_ui: ${ok} ok, ${F.length} failed`);
  execFileSync('docker', ['rm', '-f', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test'], {stdio: 'ignore'});
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
