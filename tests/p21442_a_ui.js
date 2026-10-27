// 2.144.2 UI test, part A (small interface fixes), own container (start.sh). jsdom:
// - #2447/#2448: the channel dialog (Settings > Notifications > Channels) labels the type "Channel type" (not the office "Service") and
//   its event rows use the 44 px row class like "Active"
// - #2435: a click on the label "Send read receipts" switches the box and saves
// - #2352/#2375: the touch rules for the receipt sheet, cash book, "Bill on" pick and the workweek buttons are in the CSS (44 px)
// - #2369: the setup dialog's preset match is guarded against the empty preset
// P21442A_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21442A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const rd = f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');
const FEAT = 'cal,comments,collab,events,files,time';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  const w = await boot({user: 'alice'}), d = w.document;
  w.__dialogs = 'manual';
  w.eval(`settingsModal('notify')`);
  await until(() => d.querySelector('#s-chn [data-chn="new"]'), 60);
  // #2435: the label is part of the checkbox's label; a click on its text toggles and saves
  const cb = d.querySelector('#s-trd');
  check(cb && cb.checked && cb.closest('label'), '#2435: the box sits inside its label');
  if (cb) { click(w, cb.closest('label')); }
  check(await until(async () => (await call('GET', '/api/state')).settings?.chat_read_receipts === '0'), '#2435: a click on the label saves');
  // #2447 / #2448
  click(w, d.querySelector('#s-chn [data-chn="new"]'));
  await until(() => d.querySelector('#chn-kind'));
  const lab = d.querySelector('label[for="chn-kind"]');
  check(lab && lab.textContent.trim() === 'Channel type', '#2448: own label "Channel type": ' + (lab && lab.textContent));
  const rows = [...d.querySelectorAll('[data-chnev]')].map(x => x.closest('label'));
  check(rows.length >= 3 && rows.every(l => l.classList.contains('chkl')), '#2447: event rows use .chkl (44 px on touch)');
  check(/\.chkl\{min-height:2\.75rem/.test(rd('static/app.css')), '#2447: .chkl has 2.75rem on touch');
  // #2352 / #2375: CSS rules
  const docs = rd('static/css/docs.css'), off = rd('static/css/office.css'), app = rd('static/app.css');
  check(/pointer:coarse[^]*\.rc-acts \.btn[^}]*min-height: 2\.75rem/.test(docs) && /\.rc-money input[^}]*min-height: 2\.75rem/.test(docs), '#2352: receipt sheet buttons and amount / VAT fields 44 px on touch');
  check(/pointer:coarse\) \{\s*\.cb-bar select,#cb-vat,#bkb-doc\{height:2\.75rem/.test(off), '#2352: cash book selects and the "Bill on" pick 44 px on touch');
  check(/\.wtdays button\{min-width:2\.75rem;min-height:2\.75rem\}/.test(app) && /\.chkl\.wtfocus\{[^}]*overflow-wrap:anywhere/.test(app), '#2375: workweek buttons 44 px, focus label wraps');
  check(!!d.querySelector('#chn-kind') && rd('static/js/settings.js').includes('chkl wtfocus'), '#2375: the focus-sessions label has the wrapping class');
  // #2369
  check(/const matches = k => !!SETUP_PRESETS\[k\] && /.test(rd('static/js/account.js')), '#2369: the empty preset matches nothing');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
