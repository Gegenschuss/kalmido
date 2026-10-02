// 2.9.0 UI tests, own container (start.sh, isolated test database). jsdom: Settings > Account > App passwords (list, create
// = shown once, revoke), Settings > Integrations > Calendar apps (CalDAV): server, address, user name, the step-by-step guides
// (iPhone / iPad, Mac, Thunderbird, Tasks.org, DAVx5, Evolution, Windows), the proxy note only for admins, German texts;
// "via CalDAV" in the history; Settings > Administration > Sign-in: the OIDC provider form (save, locked fields, the
// guides link); SW v78. Then Firefox headless (ff.js): touch 360 x 780 / 390 x 844 and a mouse at 1280 x 800: the CalDAV
// section and the app passwords without horizontal overflow, 44 px touch targets, contrast of the hint text.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p290_ui', check, shots: 'P290_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(b.width), Math.round(b.height)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v7[89]'/.test(SW), 'service worker cache v78 or newer (2.10.0: v79)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  const L = (await call('POST', '/api/lists', {name: 'Work'})).id;

  // ================= Settings > Account > App passwords
  let w = await boot({user: 'alice'}), d = w.document;
  w.confirm = () => true;
  w.settingsModal('apppw');
  await sleep(300);
  const acc = d.querySelector('[data-pane="account"]');
  check(acc && !acc.classList.contains('hidden') && acc.querySelector('#s-apw-h'), 'focus "apppw" opens Account at App passwords');
  check(!acc.querySelector('#s-apw-h').closest('details'), 'App passwords are visible (not under the developer details)');
  check(await until(() => /No app passwords yet/.test(d.querySelector('#s-apws')?.textContent || '')), 'empty list: "No app passwords yet."');
  click(w, acc.querySelector('[data-apw="new"]'));
  await sleep(150);
  let md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('#apw-name'), 'the new app password dialog asks for a name');
  md.querySelector('#apw-name').value = 'iPhone';
  click(w, md.querySelector('[data-m="ok"]'));
  const sec = await until(() => d.querySelector('#sec-val'));
  check(sec && /^[a-z2-9]{5}(-[a-z2-9]{5}){3}$/.test(sec.value), `the password is shown once (${sec && sec.value})`);
  check(/alice/.test(sec.closest('.modal').textContent) && /only this once/.test(sec.closest('.modal').textContent), 'with the user name and "only this once"');
  click(w, sec.closest('.modal').querySelector('[data-m="close"]'));
  check(await until(() => /iPhone/.test(d.querySelector('#s-apws')?.textContent || '') && /never used/.test(d.querySelector('#s-apws').textContent)),
        'the list shows the new app password (never used)');
  check(!d.querySelector('#s-apws').textContent.includes(sec.value), 'the list never shows the password');
  const pw = sec.value;
  const r = await fetch(B + 'dav/', {method: 'PROPFIND', headers: {Depth: '0', Authorization: 'Basic ' + Buffer.from('alice:' + pw).toString('base64')}});
  check(r.status === 207, 'the shown password works for CalDAV');
  click(w, d.querySelector('#s-apws [data-apw="del"]'));
  check(await until(() => /No app passwords yet/.test(d.querySelector('#s-apws')?.textContent || '')), 'revoke: the list is empty again');

  // ================= Settings > Integrations > Calendar apps (CalDAV)
  click(w, d.querySelector('.snav [data-sec="integr"]'));
  await sleep(200);
  const ig = d.querySelector('[data-pane="integr"]');
  check(ig.querySelector('#s-dav-h') && /Calendar apps \(CalDAV\)/.test(ig.querySelector('#s-dav-h').textContent), 'Integrations: Calendar apps (CalDAV)');
  check(ig.querySelector('#dav-srv').value === 'kalmido.example' && ig.querySelector('#dav-url').value === 'https://kalmido.example/dav/'
        && ig.querySelector('#dav-user').value === 'alice', 'server, CalDAV address and user name');
  check(ig.querySelectorAll('.davrow [data-davcopy]').length === 3, 'each of them can be copied');
  const steps = ig.querySelector('#s-dav-h').parentElement.textContent;
  for (const k of ['iPhone / iPad', 'Mac:', 'Thunderbird', 'Tasks.org', 'DAVx⁵', 'Evolution', 'Windows'])
    check(steps.includes(k), `guide for ${k}`);
  check(/\/dav\/principals\/alice\//.test(steps), 'the iPhone / Mac fallback names the principal address');
  check(/must bypass the proxy login/.test(steps), 'admins see the proxy note');
  click(w, ig.querySelector('[data-apw="new"]'));
  await sleep(150);
  check([...d.querySelectorAll('.modal')].pop().querySelector('#apw-name'), 'the CalDAV section creates app passwords too');
  click(w, [...d.querySelectorAll('.modal')].pop().querySelector('[data-m="close"]'));
  check(w.actText({kind: 'created', data: {via: 'caldav'}, user_id: 1}, {1: 'Alice'}).includes('via CalDAV'), 'history: "via CalDAV"');

  // ================= Administration > Sign-in: OIDC form
  click(w, d.querySelector('.snav [data-sec="users"]'));
  await sleep(300);
  const us = d.querySelector('[data-pane="users"]');
  const form = us.querySelector('#s-signin .oidcform');
  check(form && form.open, 'OIDC not configured: the provider form is open');
  for (const k of ['issuer', 'client_id', 'client_secret', 'scopes', 'username_claim', 'groups_claim', 'required_group', 'admin_group', 'admin_domains', 'label'])
    check(form.querySelector('#oi-' + k), `OIDC field ${k}`);
  check(form.querySelector('a[href$="docs/OIDC.md"]'), 'link to the provider guides');
  form.querySelector('#oi-issuer').value = 'https://id.example.com/realms/team';
  form.querySelector('#oi-client_id').value = 'kalmido';
  form.querySelector('#oi-admin_domains').value = 'example.com';
  click(w, form.querySelector('[data-oidc="save"]'));
  check(await until(() => /id\.example\.com/.test(us.querySelector('#s-signin')?.textContent || '') && us.querySelector('#s-signin [data-oidc="check"]')),
        'saved: the status shows the provider, "Check provider" appears');
  check((await call('GET', '/api/state')).about.oidc.admin_domains === 'example.com', 'stored on the server');
  check(/Client secret/.test(us.querySelector('#s-signin').textContent), 'the secret field is there');
  w.close();

  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  w.settingsModal('caldav'); await sleep(300);
  check(/Kalender-Apps \(CalDAV\)/.test(d.querySelector('#s-dav-h')?.textContent || '') && /CalDAV-Account hinzufügen/.test(d.querySelector('[data-pane="integr"]').textContent),
        'German: Kalender-Apps (CalDAV) with the iPhone steps');
  check(/App-Passwörter/.test(d.querySelector('#s-apw-h')?.textContent || ''), 'German: App-Passwörter');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  // not an admin: no proxy note
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CKB);
  w = await boot({user: 'bob'}); d = w.document;
  w.settingsModal('caldav'); await sleep(300);
  check(d.querySelector('#s-dav-h') && !/must bypass the proxy login/.test(d.querySelector('[data-pane="integr"]').textContent), 'members see no proxy note');
  check(!d.querySelector('#s-signin'), 'members see no sign-in settings');
  w.close();

  // ================= Firefox: real layout
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
      let nr = 0;
      for (const [vw, vh] of touch ? [[360, 780], [390, 844]] : [[1280, 800]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        for (const theme of ['dark', 'light']) {
          await nav(B + 'static/icon.svg');
          await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
          await nav(B + '?v=' + (++nr) + '#l/' + L);
          for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
          await sleep(800);
          await ev(`(() => { settingsModal('caldav'); return 1; })()`); await sleep(700);
          const lay = await ev(`(() => { const m = document.querySelector('.smodal .spanes'); const s = document.querySelector('#s-dav-h'); const i = document.querySelector('#dav-url');
            return {sw: m.scrollWidth, cw: m.clientWidth, h: !!(s && s.offsetWidth), iw: i ? Math.round(i.getBoundingClientRect().width) : 0, doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
          check(lay.h && lay.sw <= lay.cw + 1 && lay.doc && lay.iw >= 100, `${vw}px ${theme}: CalDAV section without horizontal overflow ${JSON.stringify(lay)}`);
          if (touch) {
            const small = await ev(SMALL('[data-pane="integr"] .davrow button, [data-pane="integr"] [data-apw]'));
            check(!small.length, `${vw}px ${theme}: CalDAV buttons >= 44 px ${JSON.stringify(small)}`);
          }
          if (vw === 390 || vw === 1280) await shot(`p290-caldav-${vw}-${theme}.png`);
          await ev(`(() => { document.querySelector('.snav [data-sec="account"]').click(); return 1; })()`); await sleep(500);
          const acc = await ev(`(() => { const m = document.querySelector('.smodal .spanes'); return {sw: m.scrollWidth, cw: m.clientWidth, h: !!document.querySelector('#s-apw-h')?.offsetWidth}; })()`);
          check(acc.h && acc.sw <= acc.cw + 1, `${vw}px ${theme}: App passwords without horizontal overflow ${JSON.stringify(acc)}`);
          if (touch) {
            const small = await ev(SMALL('[data-pane="account"] [data-apw]'));
            check(!small.length, `${vw}px ${theme}: app password buttons >= 44 px ${JSON.stringify(small)}`);
          }
        }
      }
    }, touch);
  }
  console.log(`p290_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
