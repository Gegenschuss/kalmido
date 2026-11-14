#!/usr/bin/env node
// kalmido-suite: fresh
// 2.1156.0 part B (#4550): inviting a person without an account by a link / QR code (cinvite.js), own container (start.sh, no
// SMTP: the new account is active at once). jsdom, invented names only, every person without an organisation:
// - frida: "Find people" shows "Invite by link"; the dialog makes a link: the QR code and the link are VISIBLE, the open link
//   is listed with its note; "Take back" removes it (one undo step brings it back)
// - a second browser without a session opens the link: the page names frida, the form (name, address, password) creates the
//   account; the new account then sees frida under Connections in its own "Find people"
// - 2.1156.0 (#4550, Fable F1): without e-mail the form asks for no address (name + password); the username comes from the name
// - dora (signed in) opens a link: the app starts and asks "Connect with Frida?"; yes connects
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const wait = fn => until(fn, {timeout: 15000, step: 150});

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, CK);
  for (const [u, n] of [['frida', 'Frida'], ['dora', 'Dora']]) {
    check((await call('POST', '/api/users', {username: u, display_name: n, password: 'password123', email: `${u}@example.com`, orgs: []}, CK)).id, `setup: ${u}`);
    await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, await login(u));
  }
  const sw = await call('PATCH', '/api/admin/settings', {cinv_signup: true, password: 'password123'}, CK);
  check(sw.cinv_signup === true, 'an admin switches invitation links on');
  const CKF = await login('frida');

  // ================= frida: Find people > Invite by link
  let w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  w.eval('dsc_open()');
  const md = await wait(() => d.querySelector('.dscmodal [data-dsc="invite"]') && d.querySelector('.dscmodal'));
  check(md && /Invite by link/.test(md.querySelector('[data-dsc="invite"]')?.textContent || ''), 'Find people: the button "Invite by link"');
  md.querySelector('[data-dsc="invite"]').click();
  const cm = await wait(() => d.querySelector('.cnvmodal'));
  check(cm && cm.querySelector('#cnv-note') && !cm.querySelector('.qrbox'), 'the dialog: a note field, no link before one is made');
  cm.querySelector('#cnv-note').value = 'Nina';
  cm.querySelector('[data-cnv-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const img = await wait(() => cm.querySelector('.qrbox img'));
  check(img && /^data:image\/svg\+xml/.test(img.getAttribute('src') || '') && !img.closest('[hidden]'), 'the QR code is shown');
  const link = cm.querySelector('#cnv-link')?.value || '';
  check(/#cinv\/[A-Za-z0-9_-]{40,}$/.test(link), `the link is shown (${link.slice(0, 40)})`);
  check(cm.querySelector('[data-cnv="copy"]') && /runs out/.test(cm.querySelector('.cnv-row')?.textContent || '') && /Nina/.test(cm.querySelector('.cnv-row .n')?.textContent || ''),
    'Copy; the open link is listed with its note and when it runs out');
  // take back + undo (a second link, so the first stays for the visitor)
  cm.querySelector('#cnv-note').value = 'Tom';
  cm.querySelector('[data-cnv-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await wait(() => cm.querySelectorAll('.cnv-row').length === 2);
  const tomRow = [...cm.querySelectorAll('.cnv-row')].find(r => /Tom/.test(r.textContent));
  tomRow.querySelector('[data-cnv="withdraw"]').click();
  await wait(() => cm.querySelectorAll('.cnv-row').length === 1);
  check(cm.querySelectorAll('.cnv-row').length === 1 && (await call('GET', '/api/disc/invites', null, CKF)).items.length === 1, 'Take back: the link is gone');
  await w.eval(`histStep('undo')`);
  await wait(() => cm.querySelectorAll('.cnv-row').length === 2);
  check((await call('GET', '/api/disc/invites', null, CKF)).items.length === 2, 'undo brings it back');
  w.close();

  // ================= a visitor without a session opens the link
  const tok = link.split('#cinv/')[1];
  w = await boot({user: null, hash: 'cinv/' + tok}); d = w.document;
  const card = await wait(() => d.querySelector('.authscreen #cnv-form') && d.querySelector('.authscreen'));
  check(card && /Frida invites you/.test(card.querySelector('h2')?.textContent || ''), 'the page names who invites');
  check(!/#cinv/.test(w.location.href), 'the token left the address bar');
  // 2.1156.0 (#4550, Fable F1): no address field without e-mail
  check(!card.querySelector('#cnv-mail') && card.querySelector('#cnv-pw') && card.querySelector('#cnv-pw2'), 'no e-mail: name + password, no address field');
  card.querySelector('#cnv-name').value = 'Nina Example';
  card.querySelector('#cnv-pw').value = 'password123';
  card.querySelector('#cnv-pw2').value = 'password123';
  card.querySelector('#cnv-form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const done = await wait(() => /You are connected with Frida/.test(d.querySelector('.authscreen [role="status"]')?.textContent || '') && d.querySelector('.authscreen'));
  check(done && /username for signing in: nina\.example/.test(done.textContent), 'registered: connected, the username is shown');
  check(done && done.querySelector('[data-cnv="go"]'), '... with "Continue"');
  w.close();

  // ================= nina signs in: frida stands under Connections
  w = await boot({user: 'nina.example', hash: 'today'}); d = w.document;
  w.eval('dsc_open()');
  const m2 = await wait(() => d.querySelector('.dscmodal #dsc-con-h') && d.querySelector('.dscmodal'));
  check(m2 && /Frida/.test(m2.querySelector('[aria-labelledby="dsc-con-h"]')?.textContent || ''), 'nina: Frida under Connections');
  w.close();
  const news = (await call('GET', '/api/news', null, CKF)).items || [];
  const it = news.find(x => x.kind === 'connok');
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  check(it && /accepted your invitation/.test(w.eval(`newsText(${JSON.stringify(it)}, {${it.actor_id}: 'Nina Example'})`)), 'frida\'s News: "… accepted your invitation …"');
  w.close();

  // ================= dora, signed in, opens a link: "Connect with Frida?"
  const j2 = await call('POST', '/api/disc/invites', {}, CKF);
  const tok2 = j2.link.split('#cinv/')[1];
  w = await boot({user: 'dora', hash: 'cinv/' + tok2}); d = w.document;
  const CKD = w.__cookie;
  const connected = async () => ((await call('GET', '/api/disc', null, CKD)).connections || []).some(c => c.person.name === 'Frida');
  await wait(async () => await connected());
  check(await connected(), 'dora: the confirmation (yes) connects her with Frida');
  check(!d.querySelector('.authscreen'), 'signed in: no registration page');
  w.close();

  console.log(`p21156_b_cinvite_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
