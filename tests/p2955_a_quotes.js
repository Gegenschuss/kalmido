// 2.955.0 (#5239) UI test, own container (start.sh): the Dada quote of the day (static/js/quotes_dada.js, jsdom).
// kalmido-suite: fresh
// - the data: the accepted list without no. 17, 28 and 53; every quote has its author; every quote that is no sound poem has
//   the German and the English text (its original or a translation), a sound poem has no translation; Vaché and Pansaers
//   without a work title; the pick is fixed per day and walks through the whole list before one repeats
// - Today (home): below the greeting "Good …, Alice" the quote ONCE in italics, in the interface language, and "— Author";
//   2.1017.0 (#5784): replaces the original + translation below it (#5239); no quote ends on a comma, semicolon or colon;
//   the module loads on demand (lazy start: first a placeholder, then the line); drawing the page again twice keeps the
//   same line and draws it at once (no placeholder, no jump)
// - the sign-in page shows the same line, alone (no "nice to have you here" greeting any more)
// - German interface: a French original shows only the German text, a German one its original; French: the French original,
//   else English; a sound poem always its original
// - 2.1030.0 (#5785): Spanish, Italian, Dutch and French have their own text for every quote that is no sound poem (French:
//   for the German and English originals), each in its own file loaded on demand (quotes_dada_<code>.js); the same verse
//   breaks as the original, none ends on a comma, semicolon or colon; without that file the line falls back to English;
//   a Spanish interface shows the Spanish text on Today and on the sign-in page and loads only the Spanish file
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
const ctx = {}; vm.createContext(ctx); vm.runInContext(SRC + '\n;this.QD_LIST = QD_LIST; this.qd_pick = qd_pick; this.qd_text = qd_text;', ctx);
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
const T = (q, l) => ctx.qd_text(q, l).join('|');
// 2.1017.0 (#5784): one text in the interface language (was: the original and the translation below it)
check(T(fr, 'de') === 'Regentage sehen aus wie Ferien.|de' && T(fr, 'en') === 'Rainy days look like holidays.|en' && T(fr, 'es') === 'Rainy days look like holidays.|en'
  && T(fr, 'fr') === 'Les jours de pluie ressemblent aux vacances.|fr', 'a French original: German for German, English for English / Spanish, the original for French');
check(T(de, 'de') === 'Was wir Dada nennen, ist ein Narrenspiel aus dem Nichts|de' && /^What we call Dada.*\|en$/.test(T(de, 'en')) && /^What we call Dada.*\|en$/.test(T(de, 'fr'))
  && /^What we call Dada.*\|en$/.test(T(de, 'nl')) && T(en, 'it') === en[2] + '|en' && T(en, 'fr') === en[2] + '|en' && /Sonne.*\|de$/.test(T(en, 'de')),
  'a German original: itself for German, English for French / Dutch; an English original in English everywhere but German');
check(['de', 'en', 'fr', 'es'].every(l => T(snd, l) === snd[2] + '|' + snd[1]), 'a sound poem is never translated');
check(Q.every(q => [q[2], q[3], q[4]].every(x => !/[,;:]\s*$/.test(x))), 'no quote ends on a comma, semicolon or colon (no. 30, 32, 60) '
  + Q.filter(q => [q[2], q[3], q[4]].some(x => /[,;:]\s*$/.test(x))).map(q => q[0]));

// 2.1030.0 (#5785): the own texts of es / it / nl / fr (their files run after quotes_dada.js, as LD_NEED loads them)
const TL = ['es', 'it', 'nl', 'fr'], ctx2 = {}; vm.createContext(ctx2);
vm.runInContext(SRC + TL.map(l => '\n' + fs.readFileSync(path.join(__dirname, '..', 'static', 'js', `quotes_dada_${l}.js`), 'utf8').replace("'use strict';", '')).join('')
  + '\n;this.QD_TR = QD_TR; this.qd_text = qd_text;', ctx2);
const brk = x => x.split(' / ').length;
for (const l of TL) {
  const own = Q.filter(q => !q[7] && q[1] !== l), tx = ctx2.QD_TR[l] || {};
  const miss = own.filter(q => { const [t, tl] = ctx2.qd_text(q, l); return tl !== l || !t || t === q[4] || t === q[2]; }).map(q => q[0]);
  check(!miss.length && Object.keys(tx).length === own.length, `${l}: every quote that is no sound poem has its own text (${own.length}) ` + miss);
  check(own.every(q => !tx[q[0]] || brk(tx[q[0]]) === brk(q[2])), `${l}: the same verse breaks as the original ` + own.filter(q => tx[q[0]] && brk(tx[q[0]]) !== brk(q[2])).map(q => q[0]));
  check(Object.values(tx).every(x => !/[,;:]\s*$/.test(x)), `${l}: no text ends on a comma, semicolon or colon`);
  check(Q.filter(q => q[7] || q[1] === l).every(q => ctx2.qd_text(q, l).join('|') === q[2] + '|' + q[1]), `${l}: a sound poem and an original in ${l} show the original`);
}
check(ctx2.qd_text(fr, 'fr')[0] === fr[2] && ctx2.qd_text(de, 'fr')[1] === 'fr' && ctx2.qd_text(en, 'fr')[1] === 'fr' && ctx2.qd_text(fr, 'en')[0] === fr[4]
  && ctx2.qd_text(fr, 'de')[0] === fr[3], 'French: the French original itself, a German / English original in French; English and German stay as they were');
check(ctx2.qd_text(de, 'es')[0] === 'Lo que llamamos Dada es un juego de locos surgido de la nada' && /Dada/.test(ctx2.QD_TR.it[1]) && /Dada/.test(ctx2.QD_TR.nl[1]), 'the names and "Dada" stay');

execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const line = d => { const f = d.querySelector('figure.qd'); return f && {n: Number(f.dataset.qdn), o: f.querySelector('.qdo')?.textContent || '', cap: f.querySelector('figcaption')?.textContent || '',
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
  const wt = ctx.qd_text(want, 'en');
  check(L && L.n === want[0] && L.o === wt[0] && L.lang === wt[1], 'Today: the quote of the day once, in English (or its English original / sound poem) ' + JSON.stringify(L));
  check(L && Q.some(q => q[0] === L.n && (q[2] === L.o || q[4] === L.o)), 'Today: a quote of the list');
  check(L && L.a === '— ' + want[5] && L.tip === want[6], 'Today: "— Author", the work as the tooltip ' + (L && L.a));
  check(L && L.cap === L.a && !d.querySelector('.qdt'), 'Today: below the quote only the author, no second text ' + (L && L.cap));
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
  check(n39.querySelector('.qdo').textContent === 'Rainy days look like holidays.' && n39.querySelector('.qdo').lang === 'en' && n39.querySelector('figcaption').textContent === '— Francis Picabia',
    'English interface, a French original: only the English text and the author');

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
  check(L && L.o === ctx.qd_text(want, 'de')[0] && L.cap === L.a, 'German: the German text once, below it only the author ' + JSON.stringify(L));
  const g39 = w.eval(`qd_node('', new Date(${f39}))`);
  check(g39.querySelector('.qdo').textContent === 'Regentage sehen aus wie Ferien.' && g39.querySelector('.qdo').lang === 'de' && !g39.textContent.includes('vacances'),
    'German, a French original: only the German text, not the French one');
  const gde = w.eval(`(() => { const D = new Date(2026, 10, 11); for (let i = 0; i < 400; i++) { const x = new Date(D.getTime() + i * 864e5); if (qd_pick(x)[0] === 1) return qd_node('', x); } return null; })()`);
  check(gde && gde.querySelector('.qdo').textContent === 'Was wir Dada nennen, ist ein Narrenspiel aus dem Nichts' && gde.querySelector('figcaption').textContent === '— Hugo Ball',
    'German, a German original: the original and "— Hugo Ball"');
  w.close();

  // ================= 2.1030.0 (#5785): Spanish interface, the Spanish file loads on demand beside the quotes
  await call('PATCH', '/api/settings', {lang: 'es'});
  w = await boot({user: 'alice', hash: 'home', lazy: true}); d = w.document;
  await idle(w);
  await until(() => d.querySelector('.dash figure.qd.dashq'));
  L = line(d);
  const wes = ctx2.qd_text(want, 'es');
  check(L && L.o === wes[0] && L.lang === wes[1] && L.cap === L.a, 'Spanish: the Spanish text once (or the original of a sound poem), below it only the author ' + JSON.stringify(L));
  const s39 = w.eval(`qd_node('', new Date(${f39}))`);
  check(s39.querySelector('.qdo').textContent === 'Los días de lluvia se parecen a las vacaciones.' && s39.querySelector('.qdo').lang === 'es', 'Spanish, a French original: the Spanish text');
  const ran = w.eval('[...LD_RAN]').filter(x => /^quotes/.test(x));
  check(ran.includes('quotes_dada_es') && !ran.some(x => /quotes_dada_(it|nl|fr)$/.test(x)), 'Spanish: only the Spanish file is loaded ' + ran);
  w.eval('render()');
  check(line(d)?.o === L.o && !d.querySelector('.qdslot'), 'Spanish: drawn again, the same line at once');
  w.eval(`authScreen({auth: 'login'})`);
  await until(() => d.querySelector('.authscreen figure.qd.lgq'));
  check(d.querySelector('.authscreen figure.qd .qdo')?.textContent === wes[0], 'Spanish: the sign-in page shows the same Spanish line');
  w.close();

  console.log(`p2955_a_quotes: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
