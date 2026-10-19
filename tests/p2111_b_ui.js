// 2.111.0 UI tests, part B (#2056 invitations by e-mail + the subscription link of an event calendar), own container
// (start.sh, an SMTP sink), Firefox (desktop + phone width). Invented names, addresses @example.com only.
// - the event editor: no invitation switch while only people of the server are invited; an external address brings
//   "Send the invitation by e-mail", ticked; removing it hides the switch again; saving mails the address an .ics;
//   opening the event again shows the switch ticked (an invitation went); unticked, a new time mails nobody
// - the calendar's menu has "Subscription link…": create shows the link, Copy, New link (the old one stops), Turn off;
//   on a phone the dialog stays inside the screen
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2111_b_ui', check, shots: 'P2111B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P2111B_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '')
    + ' -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test'}});
  fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
}
const mails = to => { try { return fs.readFileSync(path.join(DATA, 'mail', 'out.jsonl'), 'utf8').split('\n').filter(Boolean).map(JSON.parse).filter(m => JSON.stringify(m.to).includes(to)); } catch { return []; } };
const waitMail = async (to, n) => { for (let i = 0; i < 50; i++) { if (mails(to).length >= n) break; await sleep(200); } return mails(to); };

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Beispiel', password: 'password123'})});
  check(r.ok, 'setup');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const call = (ev, method, url, body) => ev(`fetch('${url}', {method: '${method}', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}${body ? `, body: JSON.stringify(${JSON.stringify(body)})` : ''}}).then(r => r.text()).then(t => { try { return JSON.parse(t); } catch { return null; } })`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel} *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await call(ev, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
    await call(ev, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,events,contacts'});
    execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, "UPDATE users SET email='alice@example.com' WHERE username='alice'"]);
    const cal = await call(ev, 'POST', '/api/evcals', {name: 'Alice Termine'});
    await nav(B + '#cal');
    check(await ready(ev, `!!document.querySelector('#view .calbar [data-act="ev-cals"]')`, 80), 'the calendar view');

    // ---- the editor's switch
    await ev(`(() => { evEditor({start: '2030-03-04T10:00', end: '2030-03-04T11:00', cal_id: ${cal.id}}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evmodal #ev-attin')`), 'the event editor');
    await sleep(500);
    check(await ev(`!document.querySelector('.evmodal #ev-invrow') || document.querySelector('.evmodal #ev-invrow').hidden`), 'no invitation switch without external attendees');
    const addAtt = v => ev(`(() => { const m = document.querySelector('.evmodal'); const i = m.querySelector('#ev-attin'); i.value = '${v}'; m.querySelector('[data-evm="attadd"]').click(); return 1; })()`);
    await addAtt('gast@example.com');
    check(await ready(ev, `(() => { const r = document.querySelector('.evmodal #ev-invrow'); return r && !r.hidden && document.querySelector('#ev-inv')?.checked === true; })()`),
      'an external address brings "Send the invitation by e-mail", ticked');
    check(/Send the invitation by e-mail/.test(await ev(`document.querySelector('#ev-invrow').textContent`)), 'the switch is labelled');
    check(await ev(`document.querySelector('#ev-invrow .swc').getBoundingClientRect().height >= 20`), 'the switch is a large target');
    await shot('p2111-b-editor.png');
    await ev(`(() => { document.querySelector('.evmodal [data-evatrm="0"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#ev-invrow').hidden === true`), 'removing the address hides the switch');
    await addAtt('gast@example.com');
    await ready(ev, `document.querySelector('#ev-inv')?.checked === true`);
    await ev(`(() => { const m = document.querySelector('.evmodal'); m.querySelector('#ev-title').value = 'Abstimmung Entwurf'; m.querySelector('[data-evm="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.evmodal')`), 'saved');
    let m = await waitMail('gast@example.com', 1);
    check(m.length === 1 && /METHOD:REQUEST/.test(Buffer.from((m[0].raw.match(/filename="invite\.ics"[\s\S]*?\r?\n\r?\n([A-Za-z0-9+/=\r\n]+)/) || [])[1] || '', 'base64').toString()),
      `saving mails the invitation with the .ics (${m.length})`);
    const evs = await call(ev, 'GET', '/api/events?from=2030-03-04&to=2030-03-04');
    const e1 = (evs.items || []).find(x => x.title === 'Abstimmung Entwurf');
    check(!!e1, 'the event exists');
    if (e1) {
      const full = await call(ev, 'GET', `/api/events/${e1.eid}`);
      await ev(`(() => { evEditor({ev: ${JSON.stringify(full)}}); return 1; })()`);
      check(await ready(ev, `document.querySelector('#ev-inv')?.checked === true`), 'opened again: the switch is ticked (an invitation went)');
      await ev(`(() => { const c = document.querySelector('#ev-inv'); c.click(); return 1; })()`);
      check(await ev(`document.querySelector('#ev-inv').checked === false`), 'unticked');
      await ev(`(() => { const m = document.querySelector('.evmodal'); const t = m.querySelector('#ev-loc'); t.value = 'Raum 2'; m.querySelector('[data-evm="save"]').click(); return 1; })()`);
      check(await ready(ev, `!document.querySelector('.evmodal')`), 'saved without the tick');
      await sleep(1500);
      check(mails('gast@example.com').length === 1, 'unticked: a new place mails nobody');
    }

    // ---- the subscription link from the calendar's menu
    await ev(`(() => { document.querySelector('[data-act="ev-cals"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evcmodal [data-evcmenu="${cal.id}"]')`), 'the Calendars dialog lists the calendar');
    await ev(`(() => { document.querySelector('.evcmodal [data-evcmenu="${cal.id}"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('[role="menuitem"]')].some(b => /Subscription link/.test(b.textContent))`), 'the menu offers "Subscription link…"');
    await ev(`(() => { [...document.querySelectorAll('[role="menuitem"]')].find(b => /Subscription link/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evfmodal [data-evf="create"]')`), 'the dialog offers "Create subscription link"');
    check(/Anyone who has the link/.test(await ev(`document.querySelector('.evfmodal').textContent`)), 'the dialog says who sees the events');
    await ev(`(() => { document.querySelector('.evfmodal [data-evf="create"]').click(); return 1; })()`);
    check(await ready(ev, `/\\/ical\\/ev\\/\\d+\\.[A-Za-z0-9_-]+\\.ics$/.test(document.querySelector('#evf-url')?.value || '')`), 'create shows the link');
    const u1 = await ev(`document.querySelector('#evf-url').value`);
    await ev(`(() => { document.querySelector('.evfmodal [data-evf="copy"]').click(); return 1; })()`);
    check(await ready(ev, `/Link copied|Copy the selected link/.test(document.querySelector('#toast')?.textContent || '')`), 'Copy answers with a short note');
    await shot('p2111-b-feed.png');
    const p1 = new URL(u1).pathname;
    check((await fetch(B + p1.slice(1))).status === 200, 'the link works without login');
    await ev(`(() => { document.querySelector('.evfmodal [data-evf="rotate"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-cd="yes"]')`, 20), 'New link asks first');
    await ev(`(() => { document.querySelector('[data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `(document.querySelector('#evf-url')?.value || '') !== ${JSON.stringify(u1)} && !!document.querySelector('#evf-url')`), 'New link replaces it');
    check((await fetch(B + p1.slice(1))).status === 404, 'the old link stops');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.evfmodal')), 'on a phone the dialog stays inside the screen');
    await shot('p2111-b-feed-phone.png');
  }, false);

  console.log(`p2111_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
