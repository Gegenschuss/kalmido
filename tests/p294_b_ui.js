// 2.94.0 UI tests, part B (#1929 appointment booking by customers), own container (start.sh, an SMTP host so the page can be
// switched on), Firefox (desktop + phone width). Invented names only.
// - the Calendars dialog has "Booking page…"; it opens the settings: the address, title, weekly hours, saving makes the page
//   and shows its link; the switch turns it on; a new appointment type through its dialog shows in the list; Undo of saving
// - the public page /s/b/<address> lists the type, its free times are links with large targets; on a phone nothing sticks out
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p294_b_ui', check, shots: 'P294B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P294B_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '')
    + ' -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test'}});
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Beispiel', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const get = (ev, url) => ev(`fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel} *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await ev(`fetch('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({lang: 'en', tour: 'done', features: 'cal,comments,events,contacts'})}).then(r => r.status)`);
    await nav(B + '#cal');
    check(await ready(ev, `!!document.querySelector('#view .calbar [data-act="ev-cals"]')`, 80), 'the calendar with its Calendars button');
    await ev(`(() => { document.querySelector('[data-act="ev-cals"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.evcmodal [data-evc="booking"]')`), 'the Calendars dialog offers "Booking page…"');
    await ev(`(() => { document.querySelector('[data-evc="booking"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.apb-dlg #apb-slug')`, 60), 'the booking page settings open (lazy module)');
    check(await ev(`!document.querySelector('.apb-dlg .apb-link') && /^[a-z0-9-]{3,40}$/.test(document.querySelector('#apb-slug').value) && document.querySelectorAll('.apb-day').length === 7`),
      'before the first save: a suggested address, seven days, no link yet');
    check(await ev(`document.querySelectorAll('.apb-day:not(.off)').length === 5`), 'Monday to Friday are on by default');
    await ev(`(() => { const m = document.querySelector('.apb-dlg'); m.querySelector('#apb-slug').value = 'alice-beispiel'; m.querySelector('#apb-title').value = 'Termine bei Alice';
      const sat = m.querySelector('[data-apbday="sat"]'); sat.checked = true; sat.dispatchEvent(new Event('change', {bubbles: true}));
      m.querySelector('[data-apb="save"]').click(); return 1; })()`);
    check(await ready(ev, `/\\/s\\/b\\/alice-beispiel$/.test(document.querySelector('.apb-dlg .apb-link code')?.textContent || '')`), 'saving makes the page and shows its link');
    let pg = await get(ev, '/api/appt/page');
    check(pg.page.title === 'Termine bei Alice' && pg.page.hours.sat.length === 1 && pg.page.enabled === false, 'title + Saturday saved, still off ' + JSON.stringify(pg.page));
    await ev(`(() => { document.querySelector('[data-apb="newtype"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.apb-tdlg #apt-name')`), 'the appointment type dialog');
    await ev(`(() => { const m = document.querySelector('.apb-tdlg'); m.querySelector('#apt-name').value = 'Erstgespräch'; m.querySelector('#apt-dur').value = '45'; m.querySelector('#apt-notice').value = '0';
      m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.apb-tdlg') && /Erstgespräch/.test(document.querySelector('.apb-dlg .apb-list')?.textContent || '')`), 'the new type is listed');
    await ev(`(() => { const c = document.querySelector('#apb-on'); c.click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/appt/page', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.page.enabled === true)`), 'the switch turns the page on');
    await shot('p294-b-settings.png');
    // Undo of a change of the page
    await ev(`(() => { const m = document.querySelector('.apb-dlg'); m.querySelector('#apb-title').value = 'Neu'; m.querySelector('[data-apb="save"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/appt/page', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.page.title === 'Neu')`), 'the title changed');
    await ev(`(() => { const b = document.querySelector('#toast button'); if (b) b.click(); return !!b; })()`);
    check(await ready(ev, `fetch('/api/appt/page', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.page.title === 'Termine bei Alice')`), 'Undo brings the old title back');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.apb-dlg .card')), 'on a phone the settings stay inside the screen');
    await shot('p294-b-settings-phone.png');
    // the public page
    pg = await get(ev, '/api/appt/page');
    const types = await get(ev, '/api/appt/types');
    await nav(B + 's/b/alice-beispiel');
    check(await ready(ev, `/Erstgespräch/.test(document.body.textContent) && /Termine bei Alice/.test(document.querySelector('h1')?.textContent || '')`), 'the public page lists the type');
    await nav(B + `s/b/alice-beispiel/${types.types[0].id}`);
    check(await ready(ev, `document.querySelectorAll('.apb-slots a').length > 0`), 'the free times as links');
    check(await ev(`[...document.querySelectorAll('.apb-slots a')].every(a => a.getBoundingClientRect().height >= 40)`), 'large targets for the times');
    check(await ev(noSide('main')), 'the public times stay inside a phone screen');
    await shot('p294-b-public-phone.png');
    await ev(`(() => { document.querySelector('.apb-slots a').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('form.apb-form #apb-name') && !!document.querySelector('.hp input[name="website"]')`), 'the booking form with the hidden honeypot');
    await shot('p294-b-form-phone.png');
  }, false);

  console.log(`p294_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
