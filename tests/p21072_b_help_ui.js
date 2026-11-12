// 2.1072.0 UI test, part B (#5820): the help in the app (static/js/helpview.js, loaded on demand), German interface.
// kalmido-suite: fresh
// jsdom, fresh container. Invented names only. alice uses Kalmido in German:
//  - the command search: "Hilfe" lists "Hilfe" and the help's topics; "Scan" finds "Scan-Eingang einrichten"; Enter opens it
//  - the topic shows its steps in German, visible: the heading, four numbered steps with the screen's labels (Einstellungen,
//    Integrationen, Dokumente: Eingänge, Scan-Eingang anlegen), "Was dann passiert"; the address is #help/<key>
//  - "Alle Hilfethemen" leads to the list (the five areas in the sidebar's words), a topic opens, the browser's Back returns to
//    the list; the help's own search ("Kontoauszug") finds "Eine Zahlung erfassen"
//  - the same text the page shows comes over the API for agents (read_help translated) and over GET /api/help/section
//  - the ways in: Settings > Help ("Hilfe: So geht's"), "So geht's" in an empty project (-> the area Aufgaben first), "Hilfe zu
//    diesem Bereich" in the header's "…" of a project; an unknown topic says so
// The waits are on states (elements, texts, the hash), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const USCAN = 'files#how-to-set-up-a-scan-inbox';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
  const L = await call(CA, 'POST', '/api/lists', {name: 'Leeres Projekt'});
  check(L.id, `an empty project (${L.http})`);

  const w = await boot({user: 'alice', hash: 'today'}); const d = w.document;
  const pal = async q => {
    w.eval('openPalette()');
    const inp = await until(() => d.querySelector('.palette .pqin'));
    inp.value = q; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
    return inp;
  };
  const items = () => [...d.querySelectorAll('.palette .pitem')].map(x => (x.querySelector('.plt') || x).textContent.trim());

  // ---- the command search: "Hilfe", then "Scan"
  await pal('Hilfe');
  check(await until(() => items().includes('Hilfe') && items().includes('Scan-Eingang einrichten')), `"Hilfe": the view and the topics (${items().slice(0, 8)})`);
  w.eval('closePalette(true)');
  const inp = await pal('Scan');
  check(await until(() => items().includes('Scan-Eingang einrichten')), `"Scan" finds "Scan-Eingang einrichten" (${items().slice(0, 6)})`);
  const it = [...d.querySelectorAll('.palette .pitem')].find(x => /Scan-Eingang einrichten/.test(x.textContent));
  check(it && /Hilfe · Dateien/.test(it.textContent), `the entry says where it belongs: ${it?.textContent}`);
  it.click();
  const h2 = () => d.querySelector('#view .hvsec h2')?.textContent;
  check(await until(() => h2() === 'Scan-Eingang einrichten'), `the topic opens in German (${h2()})`);
  check(decodeURIComponent(w.location.hash) === '#help/' + USCAN && !d.querySelector('.palette'), `its address, the search closed (${w.location.hash})`);
  const steps = [...d.querySelectorAll('#view .hvtext ol li')].map(x => x.textContent);
  const body = d.querySelector('#view .hvtext')?.textContent || '';
  check(steps.length === 4 && /Einstellungen/.test(steps[0]) && /Integrationen/.test(steps[0]) && /Dokumente: Eingänge/.test(steps[0]) && /Scan-Eingang anlegen/.test(steps[2]),
    `four steps with the screen's German labels: ${JSON.stringify(steps).slice(0, 400)}`);
  check([...d.querySelectorAll('#view .hvtext ol li b, #view .hvtext ol li strong')].some(x => x.textContent === 'Ordner-Wächter'), 'the labels stand out (bold)');
  check(/Was dann passiert/.test(body) && !/<!--|\*\*/.test(body), 'what happens then; no Markdown marks or comments visible');
  check(d.querySelector('#top h1')?.textContent.includes('Hilfe'), `the header says Hilfe (${d.querySelector('#top h1')?.textContent})`);
  check(d.querySelector('#view .hvsec')?.getAttribute('data-show') === 'files.scan-inbox', 'the topic carries its named place');

  // ---- the same text over the API (agents) and the session route
  const sec = await call(CA, 'GET', '/api/help/section?key=' + encodeURIComponent(USCAN));
  check(sec.http === 200 && sec.title === 'Scan-Eingang einrichten' && /Scan-Eingang anlegen/.test(sec.text), 'GET /api/help/section: the same German topic');
  const tok = (await call(CA, 'POST', '/api/me/tokens', {name: 'help', scopes: ['read']})).token;
  const rd = await (await fetch(B + 'api/v1/help/section?lang=de&key=' + encodeURIComponent(USCAN), {headers: {Authorization: 'Bearer ' + tok}})).json();
  check(rd.translated?.text === sec.text && rd.user === 'files', 'read_help (agents): the same German text as the page');
  const sh = await (await fetch(B + 'api/v1/search?kind=help&q=' + encodeURIComponent('Scan-Eingang einrichten'), {headers: {Authorization: 'Bearer ' + tok}})).json();
  check(sh.data?.[0]?.key === USCAN, `search_help: the same topic first (${sh.data?.slice(0, 2).map(h => h.key)})`);

  // ---- back to the list, a topic, the browser's Back
  d.querySelector('#view [data-hvback]').click();
  const areaNames = () => [...d.querySelectorAll('#view .hvarea h3')].map(x => x.textContent);
  check(await until(() => areaNames().length === 5), `"Alle Hilfethemen": the list (${areaNames()})`);
  check(areaNames().join() === 'Dateien,Agenten,Büro,Aufgaben,Kalender', `the areas in the sidebar's words: ${areaNames()}`);
  const pay = [...d.querySelectorAll('#view .hvtopic')].find(x => x.textContent === 'Eine Zahlung erfassen');
  check(pay, 'the topic "Eine Zahlung erfassen" is listed');
  pay.click();
  check(await until(() => h2() === 'Eine Zahlung erfassen'), 'a topic of the list opens');
  w.history.back();
  check(await until(() => areaNames().length === 5 && !d.querySelector('#view .hvsec')), `the browser's Back returns to the list (${w.location.hash})`);

  // ---- the help's own search
  const q = d.querySelector('#hv-q');
  q.value = 'Kontoauszug'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  const hitTitles = () => [...d.querySelectorAll('#view .hvhits .hvtopic b')].map(x => x.textContent);
  check(await until(() => hitTitles()[0] === 'Eine Zahlung erfassen'), `search "Kontoauszug": "Eine Zahlung erfassen" (${hitTitles()})`);
  check(/Büro|Bank|Kontoauszug/.test(d.querySelector('#view .hvhits small')?.textContent || ''), 'a hit shows a short German text');
  q.value = 'frobnicate'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => /Nichts in der Hilfe gefunden/.test(d.querySelector('#view .hvbody')?.textContent || '')), 'nothing found says so');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => areaNames().length === 5), 'an empty search shows the topics again');

  // ---- an unknown topic
  w.location.hash = '#help/' + encodeURIComponent('files#gibt-es-nicht');
  check(await until(() => /Dieses Hilfethema gibt es nicht/.test(d.querySelector('#view .hvbody')?.textContent || '')), 'an unknown topic says so (with the way back)');
  check(d.querySelector('#view [data-hvback]'), 'the way back is there');

  // ---- Settings > Help
  w.eval("settingsModal('help')");
  const sb = await until(() => [...d.querySelectorAll('.modal [data-hlp]')].find(b => /Hilfe: So geht's/.test(b.textContent)));
  check(sb, 'Settings > Help: "Hilfe: So geht\'s"');
  sb.click();
  check(await until(() => !d.querySelector('.modal') && areaNames().length === 5 && w.location.hash === '#help'), 'it closes the settings and opens the help');

  // ---- the empty project: "So geht's" -> the area Aufgaben first
  w.location.hash = '#l/' + L.id;
  const lk = await until(() => d.querySelector('#view .empty [data-hlp]'));
  check(lk && /So geht's/.test(lk.textContent), `the empty project offers "So geht's" (${lk?.textContent})`);
  lk.click();
  check(await until(() => d.querySelector('#view .hvarea.hvcur h3')?.textContent === 'Aufgaben' && areaNames()[0] === 'Aufgaben'), `the area Aufgaben first (${areaNames()})`);
  check(decodeURIComponent(w.location.hash) === '#help/area:tasks', `its address (${w.location.hash})`);

  // ---- the header's "…" of a project: "Hilfe zu diesem Bereich"
  w.location.hash = '#l/' + L.id;
  await until(() => d.querySelector('#view .empty [data-hlp]'));
  d.querySelector('#top [data-act="top-more"]').click();
  const mi = await until(() => [...d.querySelectorAll('#pop:not(.hidden) .menu-list button')].find(b => /Hilfe zu diesem Bereich/.test(b.textContent)));
  check(mi, '"…" lists "Hilfe zu diesem Bereich"');
  mi?.click();
  check(await until(() => areaNames()[0] === 'Aufgaben'), 'it opens the help of the area');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p21072_b_help_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
