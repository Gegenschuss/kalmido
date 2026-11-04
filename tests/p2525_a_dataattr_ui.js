// kalmido-suite: fresh
// 2.525.0 (#4281) UI test: one data attribute, two meanings - the document-level click listeners act on their own elements only.
// Own container (start.sh), jsdom, every module loaded (boot: ld_all). freelancer-matrix: n/a (client listeners, no route)
// - data-rx: the reaction picker's key (agents.js) and the retention box's kind (orgexport.js) send nothing to /api/docs/;
//   a receipt's own "Discard" still reaches rx_post with its document id
// - data-cc: a choice card's pick (choicecard.js) leaves the credit card sheet's state alone (CC.pick no NaN), a button of the
//   credit card sheet outside the office view is not taken as a choice card's answer (no preventDefault)
// - data-cb: the X of the address books dialog (contacts.js) does not open the cash book's "Close day"; the cash book's own
//   button still does
// - the lint tools/check_dataattr.py is green on the tree and finds a new double meaning
const path = require('path');
const fs = require('fs');
const os = require('os');
const {execFileSync, spawnSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const ROOT = path.join(__dirname, '..');

// ---- the lint (no server needed)
const lint = spawnSync('python3', [path.join(ROOT, 'tools', 'check_dataattr.py'), '-v'], {encoding: 'utf8'});
check(lint.status === 0, 'check_dataattr.py is green on the tree: ' + (lint.stdout || '').slice(-400));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'p2525a-'));
fs.mkdirSync(path.join(tmp, 'tools')); fs.mkdirSync(path.join(tmp, 'static', 'js'), {recursive: true});
fs.copyFileSync(path.join(ROOT, 'tools', 'check_dataattr.py'), path.join(tmp, 'tools', 'check_dataattr.py'));
fs.writeFileSync(path.join(tmp, 'static', 'js', 'a.js'), "document.addEventListener('click', e => {\n  const b = e.target.closest('[data-zz]'); if (!b) return;\n  go(b.dataset.zz);\n});\n");
fs.writeFileSync(path.join(tmp, 'static', 'js', 'b.js'), "const h = k => `<button data-zz=\"${k}\">x</button>`;\n");
let r = spawnSync('python3', [path.join(tmp, 'tools', 'check_dataattr.py')], {encoding: 'utf8'});
check(r.status === 1 && /a\.js:1: data-zz is emitted by b\.js/.test(r.stdout), 'the lint finds a listener whose attribute another file emits: ' + r.stdout);
fs.writeFileSync(path.join(tmp, 'static', 'js', 'a.js'), "// one-meaning guard: data-zz\ndocument.addEventListener('click', e => {\n  const b = e.target.closest('[data-zz]'); if (!b) return;\n});\n");
r = spawnSync('python3', [path.join(tmp, 'tools', 'check_dataattr.py')], {encoding: 'utf8'});
check(r.status === 1 && /add it to KNOWN/.test(r.stdout), 'an attribute missing in KNOWN is a finding even with the marker');
fs.rmSync(tmp, {recursive: true, force: true});

execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => (await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined})).json().catch(() => ({}));
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,office,clients,docs,files,contacts'});

  const w = await boot({user: 'alice'}), d = w.document;
  check(typeof w.rx_post === 'function' && typeof w.cbCloseModal === 'function' && typeof w.ccAnswer === 'function', 'setup: receipts, cash book and choice cards are loaded');
  const seen = [];
  const f0 = w.fetch; w.fetch = (u, o) => { seen.push(`${(o && o.method) || 'GET'} ${String(u)}`); return f0(u, o); };
  const rx = []; w.rx_post = async (id, b) => { rx.push([id, b && b.do]); return {}; };
  let closes = 0; w.cbCloseModal = async () => { closes++; };
  const click = el => { const ev = new w.MouseEvent('click', {bubbles: true, cancelable: true}); el.dispatchEvent(ev); return ev; };
  const put = html => { const x = d.createElement('div'); x.innerHTML = html; d.body.appendChild(x); return x; };

  // data-rx
  let x = put('<div class="rxpick"><div class="rxgrid"><button data-rx="thumbsup">t</button></div></div>');
  click(x.querySelector('button'));
  x.remove();
  x = put('<div class="rxbox" data-rx="retention"><h5>Retention export</h5><p class="muted">text</p></div>');
  click(x.querySelector('p'));
  x.remove();
  // the listeners call rx_post / fetch / cbCloseModal synchronously within the click (before their first await)
  check(!seen.some(s => /\/api\/docs\//.test(s)) && !rx.length, '#4281: a reaction key and the retention box send nothing to /api/docs/ ' + JSON.stringify([seen, rx]));
  x = put('<div class="rc-sug"><button type="button" class="btn sm" data-rx="dismiss:5">Discard</button></div>');
  click(x.querySelector('button'));
  x.remove();
  check(await require('./boot').until(() => rx.length === 1 && rx[0][0] === 5 && rx[0][1] === 'dismiss', {timeout: 5000, step: 50}), "a receipt's own Discard still reaches rx_post " + JSON.stringify(rx));

  // data-cc
  x = put('<div class="cccard"><div class="cchw"><button type="button" class="cchb" data-cc="pick" data-cid="987654" data-ch="a">A</button></div></div>');
  click(x.querySelector('button'));
  x.remove();
  check(w.eval('CC.pick') === null, "#4281: a choice card's pick leaves the credit card sheet's pick alone " + w.eval('String(CC.pick)'));
  x = put('<div class="elsewhere"><button type="button" data-cc="tocard">Back</button></div>');
  const ev = click(x.querySelector('button'));
  x.remove();
  check(!ev.defaultPrevented, '#4281: a data-cc button outside the office view is neither a choice card answer nor the sheet\'s');

  // data-cb
  w.eval("CB.bid = 1");
  const md = w.modal('<div class="lhdr"><h3>Address books</h3><button class="iconbtn" data-cb="close" aria-label="Close">x</button></div><div id="cb-body"></div>');
  click(md.querySelector('[data-cb="close"]'));
  check(closes === 0, '#4281: the address books X does not open the cash book\'s Close day');
  x = put('<div class="ofcbar"><button class="btn" data-cb="close">Close day</button></div>');
  click(x.querySelector('button'));
  x.remove();
  check(closes === 1, "the cash book's own Close day button still opens it");
  w.fetch = f0;
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
