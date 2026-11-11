// 2.955.0 (#5239) UI test, own container (start.sh): the Dada quote of the day (static/js/quotes_dada.js, jsdom).
// kalmido-suite: fresh
// - the data: the accepted list without no. 17, 28 and 53; every quote has its author; every quote that is no sound poem has
//   the German and the English text (its original or a translation), a sound poem has no translation; Vaché and Pansaers
//   without a work title; the pick is fixed per day and walks through the whole list before one repeats
// - Today (home): below the greeting "Good …, Alice" the original in italics, below it the English translation and "— Author";
//   the module loads on demand (lazy start: first a placeholder, then the line); drawing the page again twice keeps the
//   same line and draws it at once (no placeholder, no jump)
// - the sign-in page shows the same line, alone (no "nice to have you here" greeting any more)
// - German interface: a French original shows the German translation, a German one only the author; Spanish: English
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {boot, sleep, B, login, idle, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');

// ================= the data, without a page (the file is a classic script: run it in an own context)
const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'quotes_dada.js'), 'utf8');
const ctx = {}; vm.createContext(ctx); vm.runInContext(SRC + '\n;this.QD_LIST = QD_LIST; this.qd_pick = qd_pick; this.qd_tr = qd_tr;', ctx);
const Q = ctx.QD_LIST, nos = Q.map(q => q[0]);
check(Q.length === 78 && !nos.includes(17) && !nos.includes(28) && !nos.includes(53), 'the accepted list: 78 quotes, no. 17, 28 and 53 are out ' + Q.length);
check(new Set(nos).size === Q.length, 'no quote twice');
check(Q.every(q => q[5] && /\S \S/.test(q[5])), 'every quote has its author (first and last name)');
const bad = Q.filter(q => !q[7] && !((q[1] === 'de' || q[3]) && (q[1] === 'en' || q[4])));
check(!bad.length, 'every quote that is no sound poem reads in German and English ' + bad.map(q => q[0]));
check(Q.filter(q => q[7]).map(q => q[0]).join() === '15,16,21,22,23' && Q.filter(q => q[7]).every(q => !q[3] && !q[4]), 'the sound poems 15, 16, 21-23 have no translation');
check(Q.filter(q => /Vaché|Pansaers/.test(q[5])).every(q => !q[6]) && Q.filter(q => !/Vaché|Pansaers/.test(q[5])).every(q => q[6]), 'Vaché and Pansaers without a work title, every other quote with one');
check(Q.find(q => q[0] === 39)?.[2] === 'Les jours de pluie ressemblent aux vacances.' && Q.find(q => q[0] === 18)?.[2] === 'Blau ist die Farbe deines gelben Haares. / Rot ist das Girren deines grünen Vogels.',
  'the wording as in the original');
const day = n => new Date(2026, 10, 11 + n, 12);
check(ctx.qd_pick(day(0)) === ctx.qd_pick(new Date(2026, 10, 11, 0, 5)) && ctx.qd_pick(day(0)) === ctx.qd_pick(new Date(2026, 10, 11, 23, 55)), 'one quote for the whole day');
check(new Set(Array.from({length: Q.length}, (_, i) => ctx.qd_pick(day(i))[0])).size === Q.length, 'every quote comes once before one repeats');
check(ctx.qd_pick(day(0)) !== ctx.qd_pick(day(1)), 'the next day another quote');
const fr = Q.find(q => q[0] === 39), de = Q.find(q => q[0] === 1), en = Q.find(q => q[0] === 74), snd = Q.find(q => q[0] === 23);
check(ctx.qd_tr(fr, 'de') === 'Regentage sehen aus wie Ferien.' && ctx.qd_tr(fr, 'en') === 'Rainy days look like holidays.' && ctx.qd_tr(fr, 'es') === 'Rainy days look like holidays.' && ctx.qd_tr(fr, 'fr') === '',
  'a French original: German for German, English for English / Spanish, nothing for French');
check(ctx.qd_tr(de, 'de') === '' && /^What we call Dada/.test(ctx.qd_tr(de, 'en')) && ctx.qd_tr(en, 'en') === '' && ctx.qd_tr(en, 'it') === '' && /Sonne/.test(ctx.qd_tr(en, 'de')),
  'German original + German interface: only the author; an English original reads untranslated in every interface but German');
check(['de', 'en', 'fr'].every(l => ctx.qd_tr(snd, l) === ''), 'a sound poem is never translated');

execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const line = d => { const f = d.querySelector('figure.qd'); return f && {n: Number(f.dataset.qdn), o: f.querySelector('.qdo')?.textContent || '', t: f.querySelector('.qdt')?.textContent.trim() || '',
  a: f.querySelector('.qda')?.textContent || '', tip: f.querySelector('.qda')?.getAttribute('title') || '', cls: f.className, lang: f.querySelector('.qdo')?.getAttribute('lang') || '',
  italic: f.querySelector('.qdo')?.tagName === 'BLOCKQUOTE'}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});

  // ================= Today, English, the module loads on demand
  let w = await boot({user: 'alice', hash: 'home', lazy: true}), d = w.document;
  await idle(w);
  await until(() => d.querySelector('.dash figure.qd.dashq'));
  let L = line(d);
  const want = w.eval('qd_pick()');
  check(L && L.n === want[0] && L.o === want[2] && L.lang === want[1], 'Today: the quote of the day in its original ' + JSON.stringify(L));
  check(L && Q.some(q => q[0] === L.n && q[2] === L.o), 'Today: a quote of the list');
  check(L && L.a === '— ' + want[5] && L.tip === want[6], 'Today: "— Author", the work as the tooltip ' + (L && L.a));
  check(L && L.t === ctx.qd_tr(want, 'en'), 'Today: the English translation (none for an English original or a sound poem) ' + (L && L.t));
  const head = d.querySelector('.dash .dashhead h2'), fig = d.querySelector('.dash figure.qd');
  check(head && /Alice/.test(head.textContent) && head.closest('.dashhead').nextElementSibling === fig, 'Today: the greeting with the name stays, the quote right below it');
  check(!d.querySelector('.dash .qdslot'), 'Today: no placeholder left');
  // drawing again: the same line at once
  for (let i = 0; i < 2; i++) {
    w.eval('render()');
    const now = line(d);
    check(now && now.n === L.n && !d.querySelector('.qdslot'), `Today: drawn again (${i + 1}): the same line at once, no placeholder`);
  }
  // the next day (another date): another quote of the list, the French one in English
  const f39 = w.eval(`(() => { const D = new Date(2026, 10, 11); for (let i = 0; i < 400; i++) { const x = new Date(D.getTime() + i * 864e5); if (qd_pick(x)[0] === 39) return x.getTime(); } return 0; })()`);
  const n39 = w.eval(`qd_node('dashq', new Date(${f39}))`);
  check(n39.querySelector('.qdo').textContent === 'Les jours de pluie ressemblent aux vacances.' && n39.querySelector('.qdt')?.textContent.trim() === 'Rainy days look like holidays.' && n39.querySelector('.qda').textContent === '— Francis Picabia',
    'English interface, a French original: the English translation and the author');

  // ================= the sign-in page: the same line, alone, centred above the form
  w.eval(`authScreen({auth: 'login'})`);
  await until(() => d.querySelector('.authscreen figure.qd.lgq'));
  const sc = d.querySelector('.authscreen');
  const LS = sc && (() => { const f = sc.querySelector('figure.qd'); return {n: Number(f.dataset.qdn), o: f.querySelector('.qdo').textContent, a: f.querySelector('.qda').textContent, before: !!(f.compareDocumentPosition(sc.querySelector('#auth-form')) & 4)}; })();
  check(LS && LS.n === L.n && LS.o === L.o && LS.a === L.a, 'sign-in page: the same quote as on Today ' + JSON.stringify(LS));
  check(LS && LS.before, 'sign-in page: the quote stands above the form');
  check(sc && !/nice to have you here|Welcome back/.test(sc.textContent) && !sc.querySelector('.lghello'), 'sign-in page: no "nice to have you here" / "Welcome back" any more');
  w.close();

  // ================= German interface
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await idle(w);
  await until(() => d.querySelector('.dash figure.qd.dashq'));
  L = line(d);
  check(L && L.t === ctx.qd_tr(want, 'de'), 'German: the German translation (only the author for a German original) ' + JSON.stringify(L));
  const g39 = w.eval(`qd_node('', new Date(${f39}))`);
  check(g39.querySelector('.qdt')?.textContent.trim() === 'Regentage sehen aus wie Ferien.', 'German, a French original: the German translation');
  const gde = w.eval(`(() => { const D = new Date(2026, 10, 11); for (let i = 0; i < 400; i++) { const x = new Date(D.getTime() + i * 864e5); if (qd_pick(x)[0] === 1) return qd_node('', x); } return null; })()`);
  check(gde && !gde.querySelector('.qdt') && gde.querySelector('.qda').textContent === '— Hugo Ball', 'German, a German original: only "— Hugo Ball"');
  w.close();

  console.log(`p2955_a_quotes: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
