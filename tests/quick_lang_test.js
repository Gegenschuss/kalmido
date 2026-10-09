// 2.12.0: quick add (parseQuick in static/app.js) understands dates, times and repeats in all six app languages. English and
// German words always work; French, Spanish, Italian and Dutch while the app runs in that language. Priority, tags and the
// list stay symbols (!!! / #tag / ~list). Runs the real app in jsdom on the browser demo (tools/build_demo.py, no container).
// The expected dates are computed with the app's own date helpers, so the test passes on any day.
// usage: node quick_lang_test.js
const {JSDOM, VirtualConsole} = require('jsdom');
const http = require('http'), fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
const ROOT = path.join(__dirname, '..'), OUT = path.join(__dirname, '.demo-quick');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ok = 0; const fails = [];
const check = (c, what) => { if (c) ok++; else { fails.push(what); console.log('FAIL:', what); } };

execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tools', 'build_demo.py'), OUT], {encoding: 'utf-8'});
const srv = http.createServer((req, res) => {
  const p = path.join(OUT, decodeURIComponent(req.url.split('?')[0]).replace(/^\/demo\//, '/').replace(/\/$/, '/index.html'));
  if (!p.startsWith(OUT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {'Content-Type': p.endsWith('.js') ? 'text/javascript' : p.endsWith('.css') ? 'text/css' : 'text/html'}); fs.createReadStream(p).pipe(res);
});

// [input, title, due expression (app helpers) or null, time or null, repeat or null, priority or undefined, tags or undefined]
const D = n => `addDays(today(), ${n})`, NW = (wd, next) => `nextWeekday(${wd}${next ? ', true' : ''})`;
const SLASH = `(() => { const t = pd(today()); let d = new Date(t.getFullYear(), 9, 3); if (ds(d) < today()) d.setFullYear(t.getFullYear() + 1); return ds(d); })()`;
const CASES = {
  fr: [
    ['Dentiste demain 15h !!! #privé', 'Dentiste', D(1), '15:00', null, 5, ['privé']],
    ["Courses aujourd'hui", 'Courses', D(0)],
    ['Réunion après-demain à 9h30', 'Réunion', D(2), '09:30'],
    ['Rapport vendredi', 'Rapport', NW(5)],
    ['Appel lundi prochain', 'Appel', NW(1, true)],
    ['Facture dans 3 jours', 'Facture', D(3)],
    ['Bilan dans une semaine', 'Bilan', D(7)],
    ['Projet la semaine prochaine', 'Projet', NW(1)],
    ['Vacances 3/10', 'Vacances', SLASH],
    ['Vacances 3.10.', 'Vacances', SLASH],
    ['Sport tous les jours', 'Sport', D(0), null, 'FREQ=DAILY'],
    ['Équipe chaque lundi', 'Équipe', 'nextOrToday(1)', null, 'FREQ=WEEKLY;BYDAY=MO'],
    ['Ménage toutes les 2 semaines', 'Ménage', D(0), null, 'FREQ=WEEKLY;INTERVAL=2'],
    ['Loyer chaque mois', 'Loyer', D(0), null, 'FREQ=MONTHLY'],
    ['Dentist tomorrow 3pm !high', 'Dentist', D(1), '15:00', null, 5],
  ],
  es: [
    ['Dentista mañana a las 15 !!! #privado', 'Dentista', D(1), '15:00', null, 5, ['privado']],
    ['Compra hoy', 'Compra', D(0)],
    ['Reunión pasado mañana a las 9:30', 'Reunión', D(2), '09:30'],
    ['Informe viernes', 'Informe', NW(5)],
    ['Informe el sábado', 'Informe', NW(6)],
    ['Llamada el próximo lunes', 'Llamada', NW(1, true)],
    ['Llamar lunes que viene', 'Llamar', NW(1, true)],
    ['Factura en 3 días', 'Factura', D(3)],
    ['Proyecto la próxima semana', 'Proyecto', NW(1)],
    ['Vacaciones 3/10', 'Vacaciones', SLASH],
    ['Deporte todos los días', 'Deporte', D(0), null, 'FREQ=DAILY'],
    ['Equipo cada lunes', 'Equipo', 'nextOrToday(1)', null, 'FREQ=WEEKLY;BYDAY=MO'],
    ['Limpieza cada 2 semanas', 'Limpieza', D(0), null, 'FREQ=WEEKLY;INTERVAL=2'],
    ['Alquiler cada mes !', 'Alquiler', D(0), null, 'FREQ=MONTHLY', 1],
  ],
  it: [
    ['Dentista domani alle 15 !!! #privato', 'Dentista', D(1), '15:00', null, 5, ['privato']],
    ['Spesa oggi', 'Spesa', D(0)],
    ['Riunione dopodomani alle 9:30', 'Riunione', D(2), '09:30'],
    ['Rapporto venerdì', 'Rapporto', NW(5)],
    ['Rapporto venerdi', 'Rapporto', NW(5)],
    ['Chiamata lunedì prossimo', 'Chiamata', NW(1, true)],
    ['Chiamata prossimo lunedì', 'Chiamata', NW(1, true)],
    ['Fattura tra 3 giorni', 'Fattura', D(3)],
    ['Fattura fra una settimana', 'Fattura', D(7)],
    ['Progetto la settimana prossima', 'Progetto', NW(1)],
    ['Vacanze 3/10', 'Vacanze', SLASH],
    ['Sport ogni giorno', 'Sport', D(0), null, 'FREQ=DAILY'],
    ['Team ogni lunedì', 'Team', 'nextOrToday(1)', null, 'FREQ=WEEKLY;BYDAY=MO'],
    ['Pulizie ogni 2 settimane', 'Pulizie', D(0), null, 'FREQ=WEEKLY;INTERVAL=2'],
  ],
  nl: [
    ['Tandarts morgen 15 uur !!! #privé', 'Tandarts', D(1), '15:00', null, 5, ['privé']],
    ['Boodschappen vandaag', 'Boodschappen', D(0)],
    ['Overleg overmorgen om 9:30', 'Overleg', D(2), '09:30'],
    ['Rapport vrijdag', 'Rapport', NW(5)],
    ['Bellen volgende maandag', 'Bellen', NW(1, true)],
    ['Factuur over 3 dagen', 'Factuur', D(3)],
    ['Factuur over een week', 'Factuur', D(7)],
    ['Project volgende week', 'Project', NW(1)],
    ['Vakantie 3/10', 'Vakantie', SLASH],
    ['Sporten elke dag', 'Sporten', D(0), null, 'FREQ=DAILY'],
    ['Team elke maandag', 'Team', 'nextOrToday(1)', null, 'FREQ=WEEKLY;BYDAY=MO'],
    ['Schoonmaken elke 2 weken', 'Schoonmaken', D(0), null, 'FREQ=WEEKLY;INTERVAL=2'],
    ['Huur maandelijks', 'Huur', D(0), null, 'FREQ=MONTHLY'],
  ],
  en: [
    ['Dentist tomorrow 3pm !high #private', 'Dentist', D(1), '15:00', null, 5, ['private']],
    ['Trip 3/10', 'Trip', SLASH],
    ['Call Domingo', 'Call Domingo', null],  // another language's weekday is text in English
    ['Read pages 3/13 of the book', 'Read pages 3/13 of the book', null],  // no 13th month
    ['Report next friday at 9:30', 'Report', NW(5, true), '09:30'],
  ],
  de: [
    ['Zahnarzt morgen 15 Uhr !hoch #privat', 'Zahnarzt', D(1), '15:00', null, 5, ['privat']],
    ['Urlaub 3/10', 'Urlaub', SLASH],
    ['Urlaub am 3.10.', 'Urlaub', SLASH],
    ['Sport jeden montag', 'Sport', 'nextOrToday(1)', null, 'FREQ=WEEKLY;BYDAY=MO'],
    ['Anruf vandaag', 'Anruf vandaag', null],  // Dutch words only in Dutch
  ],
};

(async () => {
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const store = {}, errs = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(`http://127.0.0.1:${srv.address().port}/demo/`, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
        key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      Object.defineProperty(w.navigator, 'languages', {configurable: true, value: ['en-GB']});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
    }});
  await sleep(2500);
  const w = dom.window;
  check(w.eval('S.tasks.size') > 0, 'app booted');
  for (const [lang, cases] of Object.entries(CASES)) {
    check(await w.eval(`i18nLoad('${lang}')`), `${lang}: language loaded`);
    let n = 0;
    for (const [inp, title, due, time = null, rep = null, prio, tags] of cases) {
      const r = JSON.parse(w.eval(`JSON.stringify(parseQuick(${JSON.stringify(inp)}, new Set()))`));
      const want = due ? w.eval(due) : undefined;
      const good = r.title === title && r.due === want && (r.due_time ?? null) === time && (r.repeat ?? null) === rep
        && (prio === undefined || r.priority === prio) && (!tags || JSON.stringify(r.tags) === JSON.stringify(tags));
      check(good, `${lang}: ${JSON.stringify(inp)} -> ${JSON.stringify({title: r.title, due: r.due, time: r.due_time, repeat: r.repeat, prio: r.priority, tags: r.tags})}, want ${JSON.stringify({title, due: want, time, rep, prio, tags})}`);
      n += good;
    }
    console.log(`${lang}: ${n}/${cases.length} quick add cases`);
  }
  // the quick add hints of fr / es / it / nl use their own words, no English keywords
  for (const lang of ['fr', 'es', 'it', 'nl']) {
    await w.eval(`i18nLoad('${lang}')`);
    const hint = w.eval(`tr('tomorrow 3pm · !high · #tag · ~list · every monday') + ' ' + tr("Type the way you think: “Dentist tomorrow 3pm !high #private ~list”")`);
    check(!/tomorrow|3pm|!high|every monday/.test(hint), `${lang}: hints without English keywords: ${hint}`);
    // and every word in the hint examples is understood
    const ex = w.eval(`tr('tomorrow 3pm · !high · #tag · ~list · every monday')`).split(' · ');
    const r1 = JSON.parse(w.eval(`JSON.stringify(parseQuick('X ' + ${JSON.stringify(ex[0])}, new Set()))`));
    const r2 = JSON.parse(w.eval(`JSON.stringify(parseQuick('X ' + ${JSON.stringify(ex[4])}, new Set()))`));
    check(r1.title === 'X' && r1.due && r1.due_time === '15:00' && r2.title === 'X' && r2.repeat === 'FREQ=WEEKLY;BYDAY=MO', `${lang}: the hint examples parse (${ex[0]} / ${ex[4]})`);
  }
  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close(); srv.close();
  fs.rmSync(OUT, {recursive: true, force: true});
  console.log(`quick_lang: ${ok} ok, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
