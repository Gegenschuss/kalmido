// 2.501.0 A UI test (#4198): what left the start loads when it is needed. Own container (start.sh), jsdom, invented data only, a person
// kalmido-suite: fresh
// without an organisation (the same client code for everyone; server routes unchanged).
// - a cold start runs none of family.js, ablage.js, ablinks.js, wikie2e.js; the row helpers, the switches and the stand-ins are there
// - the file store's view and its panel load the module; the module Family's view, its palette actions and a child's tour too
// - wikie2e.js runs before wiki.js; when it cannot load wiki.js does not run (no plain writes without the lock)
// - the news text of a released key needs no module
// - a key only the server's code names is not in the core; tr() shows it in English, loads the part "py" and then translates; the
//   language switch brings that part along; an unknown key stays as it is, with no raw part after "|"
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.ok ? r.json() : {status: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 50});
const ran = (w, f) => !!w.document.querySelector(`script[data-ld="${f}"]`);
const fn = (w, n) => w.eval(`typeof ${n}`) === 'function';

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call(CK, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'files,family,wiki,events'});

  // ---- a cold start
  let w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}});
  const mods = w.eval('LD_MODS');
  check(mods.wiki[0] === 'wikie2e' && mods.ablage.includes('ablinks') && mods.family[0] === 'family', 'the modules name the files');
  const tags = w.eval(`[...document.querySelectorAll('script[src]')].map(s => s.getAttribute('src'))`);
  check(!tags.some(s => /\/(family|ablage|ablinks|wikie2e)\.js/.test(s)), 'a cold start runs none of the four files');
  check(!fn(w, 'wkeOn') && !fn(w, 'ab_panelHtml') && !fn(w, 'famData'), 'their functions are not there yet');
  check(w.eval(`famOn() === true && ab_on() === true && isOcc({fam: {kind: 'birthday'}}) === true && daysTo(today()) === 0 && typeof daysWord(1) === 'string'`), 'the switches and helpers of the start are there');
  check(w.eval(`occWhat({fam: {kind: 'birthday', year: 2000}, due: '2030-05-01'}) !== ''`), 'the row text of a birthday without the module');
  check(/stay|bleib/i.test(w.eval(`fs_keptText([{reason: 'x'}])`)), 'the hint of a trashed folder without the module');
  check(w.eval(`ab_linkBtn('att', 1, null, 'x')`).includes('data-ablink="att:1:"'), 'the file row button without the module');

  // ---- the news text
  const news = w.eval(`newsText({kind: 'wiki_e2e_key', data: {name: 'Acme'}, actor_id: S.me.id}, () => S.me)`);
  check(/Acme/.test(news) && !fn(w, 'wkeOn'), 'the news text of a released key needs no module: ' + news);

  // ---- the file store: view and panel
  check(w.eval(`sbb_panelHtml('ablage')`) !== undefined, 'the panel draws before the module is there');
  w.eval(`go('ablage')`);
  await until(() => w.document.querySelector('#view .abview'));
  check(w.document.querySelector('#view .abview') && fn(w, 'ab_panelHtml') && ran(w, 'ablinks'), 'the view of the file store loads the module with its links');
  check(typeof w.eval(`sbb_panelHtml('ablage')`) === 'string' && w.eval(`SBB_LAST.ablage !== undefined`), 'the panel draws from the module now');
  check(w.eval(`AB_ACT.ext_view`) === 'opened it through the link', 'ablinks.js added its history words');

  // ---- the module Family
  w.eval(`go('family')`);
  await until(() => fn(w, 'famData') && w.document.querySelector('#view .famview, #view .fc-meals, #view [data-act^="fam-"]'));
  check(w.document.querySelector('#view [data-act^="fam-"]'), 'the Family view loads its module');
  check(w.eval(`famBar({family: 'shopping', id: 1})`).includes('shop-start'), 'the real bar replaced the stand-in');
  w.close();

  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}});
  w.eval(`dlModal()`);
  await until(() => w.document.querySelector('.famdlg'));
  check(w.document.querySelector('.famdlg'), 'a palette action loads the module and opens its dialog');
  w.close();

  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}});
  w.eval(`S.me.kid = 1; tourStart()`);
  await until(() => w.eval('TOUR.on') === true);
  check(fn(w, 'kd_tourSteps') && w.eval('TOUR.steps.length') > 0, "a child's tour loads the module first");
  w.close();

  // ---- the lock comes before the knowledge pages
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}});
  w.eval(`window.__ld0 = ld_script; window.__ldfail = true; ld_script = f => window.__ldfail && f === 'wikie2e' ? Promise.reject(new Error('no lock')) : window.__ld0(f); 0`);
  const failed = await w.eval(`loadModule('wiki').then(() => 'loaded', () => 'failed')`);
  check(failed === 'failed' && !fn(w, 'wk_spaces') && !fn(w, 'wkeOn'), 'without the lock the knowledge pages do not run: ' + failed);
  w.eval(`window.__ldfail = false; 0`);
  const again = await w.eval(`window.__order = []; const o = ld_script; ld_script = f => { window.__order.push(f); return o(f); }; loadModule('wiki').then(() => 'loaded', e => String(e))`);
  check(again === 'loaded' && fn(w, 'wkeOn') && fn(w, 'wk_spaces'), 'a second try loads both: ' + again);
  check(w.eval('window.__order[0]') === 'wikie2e', 'the lock runs first ' + w.eval('window.__order.join()'));
  w.close();

  // ---- the part of the server's keys
  const html = await (await fetch(B, {headers: {Cookie: CK}})).text();
  const V = (html.match(/name="kalmido-i18n" content="([0-9a-f]{12})"/) || [])[1] || '';
  const de = await (await fetch(B + `static/i18n/de.mod-py.json?v=${V}`)).json();
  const fr = await (await fetch(B + `static/i18n/fr.mod-py.json?v=${V}`)).json();
  const core = await (await fetch(B + `static/i18n/de.core.json?v=${V}`)).json();
  const [k, v] = Object.entries(de).find(([x, y]) => typeof y === 'string' && y !== x && x.length > 14 && !/[{<|]/.test(x) && fr[x] && fr[x] !== y) || [];
  check(k && !(k in core) && core._mods.includes('py'), 'a key only the server names is outside the core: ' + k);
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}});
  check(w.eval(`I18N.dict[${JSON.stringify(k)}]`) === undefined || w.eval(`I18N.parts.has('py')`), 'the start does not need the part');
  check([k, v].includes(w.eval(`tr(${JSON.stringify(k)})`)), 'a miss shows the English text or the translation');
  await until(() => w.eval(`!!I18N.parts?.has('py')`));
  check(w.eval(`tr(${JSON.stringify(k)})`) === v, 'tr(variable) translates a server key after the part came: ' + v);
  check(w.eval(`tr('Unknown text 4198|context')`) === 'Unknown text 4198', 'an unknown key shows without its context mark');
  check(w.eval(`I18N_MODS.has('py')`), 'the part follows a language switch');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
