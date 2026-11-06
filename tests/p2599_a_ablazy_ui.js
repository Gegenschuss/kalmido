// 2.599.0 A UI test (#4907): a module file that breaks while it runs. Own container (start.sh), jsdom, invented data only, a
// kalmido-suite: fresh
// person without an organisation (the same client code for everyone; no server route changed).
// - ablage.js cannot run (here: a global AB declared before it, the same SyntaxError a cut or wrong answer gives): the module
//   ablage fails, ablinks.js does not run after it on the missing AB_ACT, so xl_stdHtml is not locked "before initialization";
//   a second try does not run the broken file again, the toast offers a reload
// - the file in flight is inserted once even when two chains ask for it
// - normal: Settings > Data draws the sharing defaults once the module ablage is there (settings.js xl_stdLater)
// - 2.599.0 (#4506): debounce(fn, ms) of core.js runs once after the calls stop (the latest arguments), flush() runs a waiting
//   call at once and only once, cancel() drops it; the "All saved" tick (savedChip) goes away through it
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.ok ? r.json() : {status: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 50});
// typeof of a name in the TDZ throws: 'locked' tells the bug of #4907 apart from 'undefined' (never declared) and 'function'
const kind = (w, n) => w.eval(`(() => { try { return typeof ${n}; } catch (e) { return 'locked: ' + e.message; } })()`);

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'files,wiki,events'});

  // ---- ablage.js breaks while it runs
  let w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"en"'}});
  check(kind(w, 'xl_stdHtml') === 'undefined' && kind(w, 'AB_ACT') === 'undefined', 'a cold start has none of the module ablage');
  const sc = w.document.createElement('script'); sc.textContent = 'let AB = 1;'; w.document.head.appendChild(sc);  // ablage.js declares const AB
  const res = await w.eval(`loadModule('ablage').then(() => 'loaded', e => 'failed: ' + e.message)`);
  check(/^failed: ablage\.js failed while it ran/.test(res), 'the broken file fails the module: ' + res);
  check(w.eval(`LD_BAD.has('ablage') && !LD_RAN.has('ablage') && !LD_RAN.has('ablinks')`), 'it is kept as broken, not as run');
  check(!w.document.querySelector('script[data-ld="ablinks"]'), 'ablinks.js did not run after it');
  check(kind(w, 'xl_stdHtml') === 'undefined', 'xl_stdHtml is not locked before initialization: ' + kind(w, 'xl_stdHtml'));
  const tst = await until(() => { const t = w.document.querySelector('#toast'); return t && !t.classList.contains('hidden') && /Could not be loaded/.test(t.textContent) && t.textContent; });
  check(/Reload/.test(tst || ''), 'the toast offers a reload: ' + tst);
  const n0 = w.document.querySelectorAll('script[src*="/ablage.js"]').length;
  const again = await w.eval(`loadModule('ablage').then(() => 'loaded', e => 'failed: ' + e.message)`);
  check(/^failed/.test(again) && w.document.querySelectorAll('script[src*="/ablage.js"]').length === n0, 'a second try does not run the broken file again: ' + again);
  // the settings: no "before initialization" any more (the stand-in reports the failed load)
  await w.eval(`Promise.resolve(settingsModal('general')).then(() => 1, () => 1)`);
  check(kind(w, 'xl_stdHtml') === 'undefined', 'opening the settings locks nothing: ' + kind(w, 'xl_stdHtml'));
  check(!require('./boot').errs.some(m => /before initialization|AB_ACT/.test(m)), 'no script error of ablinks.js: ' + require('./boot').errs.filter(m => /AB_ACT|initialization/.test(m)).join(' | '));
  w.close();

  // ---- one file in flight is inserted once
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"en"'}});
  const once = await w.eval(`(() => { const a = ld_script('stats'), b = ld_script('stats'); return Promise.all([a, b]).then(() => (a === b) + ':' + document.querySelectorAll('script[data-ld="stats"]').length); })()`);
  check(once === 'true:1', 'two chains get the same load of a file: ' + once);
  w.close();

  // ---- normal: the sharing defaults come with the module
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"en"'}});
  w.eval(`settingsModal('data')`);
  const box = await until(() => w.document.querySelector('.smodal #s-xlstd-sec #s-xlstd'));
  check(box && w.document.querySelector('#s-xlstd-h') && kind(w, 'xl_stdHtml') === 'function', 'Settings > Data draws the sharing defaults after the module');
  check(await until(() => w.document.querySelector('#s-xlstd-exp')), 'and loads their values');
  w.close();

  // ---- 2.599.0 (#4506): debounce
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"en"'}});
  w.eval(`window.__dc = []; window.__db = debounce(function (v) { __dc.push(v + ':' + (this && this.k)); return 'r' + v; }, 40); 0`);
  w.eval(`__db.call({k: 'a'}, 1); __db.call({k: 'b'}, 2); 0`);
  check(w.eval(`__dc.length === 0 && __db.pending()`), 'nothing runs while the calls go on');
  await until(() => w.eval(`__dc.length`) > 0);
  check(w.eval(`__dc.join()`) === '2:b' && !w.eval(`__db.pending()`), 'one run after the calls stopped, with the latest arguments and this: ' + w.eval(`__dc.join()`));
  const fl = w.eval(`(() => { __db.call({k: 'c'}, 3); const r = __db.flush(), r2 = __db.flush(); return [r, r2 === undefined, __dc.join(), __db.pending()].join('|'); })()`);
  check(fl === 'r3|true|2:b,3:c|false', 'flush runs the waiting call at once and only once: ' + fl);
  w.eval(`__db.call({k: 'd'}, 4); __db.cancel(); __db.call({k: 'e'}, 5); 0`);
  await until(() => w.eval(`__dc.length`) > 2);
  check(w.eval(`__dc.join()`) === '2:b,3:c,5:e', 'cancel drops the waiting call: ' + w.eval(`__dc.join()`));
  check(w.eval(`__db.flush()`) === undefined && w.eval(`__dc.length`) === 3, 'flush with nothing waiting does nothing');
  w.eval(`savedChip(); 0`);
  check(w.document.querySelector('#savedok.on'), 'savedChip shows its tick');
  check(await until(() => !w.document.querySelector('#savedok.on')), 'and the tick goes away through debounce');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
