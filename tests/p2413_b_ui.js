// kalmido-suite: fresh
// 2.413.0 B (#3496) UI test, own container (start.sh), invented data only. Firefox (real layout): every list row (task row, file
// row, contact row, settings row, menu row, search hit) is as tall as the task row, at 1270 px and at 390 px (a phone: 44 px);
// the search fields of the files, contacts and knowledge pages are one build (.ctsearch, icon left) with the field height
// --fld-h; the knowledge page's main button is a full-height "btn pri" (no .sm). Screenshots with P2413B_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2413_b_ui', check, shots: 'P2413B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CK = await login('alice');
  const call = (method, url, body) => fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined});
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,files,docs,contacts,wiki', workspace: 'private'});

  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector(${JSON.stringify(sel)})`).catch(() => false)); i++) await sleep(300); await sleep(300); };
  // one probe block with one row of each kind, built with the app's own classes (the CSS is the app's)
  const PROBE = `(async () => {
    for (const f of ['settings', 'docs', 'contacts', 'wiki']) { if (!document.querySelector('link[href*="css/' + f + '.css"]')) { const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/css/' + f + '.css'; document.head.appendChild(l); await new Promise(r => { l.onload = l.onerror = r; }); } }
    document.getElementById('p2413') && document.getElementById('p2413').remove();
    const d = document.createElement('div'); d.id = 'p2413'; d.style.cssText = 'position:fixed;left:0;top:0;width:20rem;z-index:99999;background:var(--bg)';
    d.innerHTML = '<div class="trow"><span class="ttl">Task</span></div><a class="frow" href="#"><span class="ft"><b>File</b></span></a><button class="ctrow" type="button"><span class="ctn"><b>Contact</b></span></button><div class="navrow"><span>Setting</span></div><div class="menu-list"><button type="button">Menu</button></div><div class="ssres"><button type="button">Hit</button></div>';
    document.body.appendChild(d);
    const h = s => Math.round(d.querySelector(s).getBoundingClientRect().height * 10) / 10;
    return {trow: h('.trow'), frow: h('.frow'), ctrow: h('.ctrow'), navrow: h('.navrow'), menu: h('.menu-list button'), ssres: h('.ssres button')};
  })()`;
  const FIELD = `(() => { const out = {}; for (const [k, s] of [['dc', '#dc-q'], ['ct', '#ct-q'], ['wk', '#wk-q']]) { const i = document.querySelector(s); const b = i && i.closest('.ctsearch'); out[k] = b ? {h: Math.round(b.getBoundingClientRect().height * 10) / 10, icon: !!b.querySelector('svg'), fld: Math.round(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fld-h')) * parseFloat(getComputedStyle(document.documentElement).fontSize) * 10) / 10} : null; } return out; })()`;
  const same = o => { const v = Object.values(o); return v.every(x => Math.abs(x - v[0]) < .6); };

  for (const [W, touch] of [[1270, false], [390, true]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, `${W}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 900}});
      await nav(B + '#today'); await ready(ev, '#top h1');
      const p = await ev(PROBE);
      check(same(p), `${W}: task, file, contact, settings, menu and search-hit rows are equally tall ` + JSON.stringify(p));
      check(p.trow >= (touch ? 43.5 : 39.5), `${W}: the row height is the task row's (${p.trow})`);
      await ev(`document.getElementById('p2413').remove()`);
      // search fields: one build, the field height
      const fs = {};
      for (const [hash, key, sel] of [['docs', 'dc', '#dc-q'], ['contacts', 'ct', '#ct-q'], ['wiki', 'wk', '#wk-q']]) {
        await nav(B + '#' + hash); await ready(ev, sel);
        fs[key] = (await ev(FIELD))[key];
        // 2.413.0 (#3496, einreihen): on touch the input itself is 44 px (p2210_ui), its 1 px frame makes the field 2 px taller
        // 2.540.0 (#4472): the search of the documents stands in a toolbar: it has the toolbar's height (40 px, 44 on touch), not the field's
        const want = key === 'dc' ? [(touch ? 44 : 40) - .6, (touch ? 44 : 40) + .6] : [fs[key] && fs[key].fld - .6, fs[key] && fs[key].fld + (touch ? 2.6 : .6)];
        check(fs[key] && fs[key].icon && fs[key].h > want[0] && fs[key].h < want[1], `${W}: ${hash}: search field is .ctsearch with an icon and the field height ` + JSON.stringify(fs[key]));
        if (W === 1270) await shot(`p2413b-${hash}.png`);
      }
      // the knowledge page's main button
      await nav(B + '#wiki'); await ready(ev, '[data-wk="new"]');
      const nb = await ev(`(() => { const b = document.querySelector('#view [data-wk="new"]'); return b ? {sm: b.classList.contains('sm'), pri: b.classList.contains('pri')} : null; })()`);
      check(nb && nb.pri && !nb.sm, `${W}: wiki "New page" is btn pri, not sm ` + JSON.stringify(nb));
    }, touch);
  }
  console.log(`p2413_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
