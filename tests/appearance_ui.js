// 1.2 Settings > Appearance (jsdom): theme, density, font size, font, accent color. All per device (localStorage),
// applied instantly without Save, reset to defaults, command palette entries, German labels, bundled fonts,
// WCAG AA contrast of every accent x theme combination (computed from app.css), rem scale integrity.
// Starts its own container (start.sh). Real layout (no horizontal overflow at 125 % on a phone) needs a browser
// and is not part of this suite.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, clientSource} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, k, o = {}, target) => (target || w).dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const DATA = process.argv[2] || path.join(__dirname, '.data');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

// ---- WCAG 2 contrast
const lum = hex => { const h = hex.replace('#', ''); const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => m - n); return (y + 0.05) / (x + 0.05); };

(async () => {
  // ---- static checks on the shipped files
  // the files the container serves (= the image under test)
  const get = async f => (await fetch(B + f)).text();
  const css = await get('static/app.css'), js = await clientSource(), sw = await get('sw.js');
  const vars = sel => { const m = css.match(new RegExp(sel.replace(/[[\]()"=]/g, '\\$&') + '\\{([^}]*)\\}')); const o = {}; if (m) for (const [, k, v] of m[1].matchAll(/--([\w-]+):([^;]+)/g)) o[k] = v.trim(); return o; };
  const root = vars(':root'), light = vars(':root[data-theme="light"]');
  check(light.accent === 'var(--acc-l)' && light['accent-ink'] === 'var(--acc-ink-l)', 'light theme takes the light accent variables');
  const accents = {violet: {d: root['acc-d'], id: root['acc-ink-d'], l: root['acc-l'], il: root['acc-ink-l']}};
  for (const [, k, body] of css.matchAll(/:root\[data-accent="(\w+)"\]\{([^}]*)\}/g)) { const o = {}; for (const [, n, v] of body.matchAll(/--([\w-]+):([^;]+)/g)) o[n] = v.trim(); accents[k] = {d: o['acc-d'], id: o['acc-ink-d'], l: o['acc-l'], il: o['acc-ink-l']}; }
  check(Object.keys(accents).length === 7, 'seven accents in app.css (2.11.0: violet default, raspberry + mint selectable): ' + Object.keys(accents));
  const darkBg = [root.bg, root.bg2, root.bg3], lightBg = [light.bg, light.bg2, light.bg3];
  let worst = 99;
  for (const [k, a] of Object.entries(accents)) {
    for (const bg of darkBg) { const r = ratio(a.d, bg); worst = Math.min(worst, r); check(r >= 4.5, `contrast ${k} dark text on ${bg}: ${r.toFixed(2)}`); }
    for (const bg of lightBg) { const r = ratio(a.l, bg); worst = Math.min(worst, r); check(r >= 4.5, `contrast ${k} light text on ${bg}: ${r.toFixed(2)}`); }
    check(ratio(a.d, a.id) >= 4.5, `contrast ${k} dark ink on accent: ${ratio(a.d, a.id).toFixed(2)}`);
    check(ratio(a.l, a.il) >= 4.5, `contrast ${k} light ink on accent: ${ratio(a.l, a.il).toFixed(2)}`);
    check(ratio(a.d, root.bg) >= 3 && ratio(a.l, light.bg) >= 3, `${k}: focus ring / borders >= 3:1`);
    // the swatches in the settings (LOOK table in app.js) show the same colors
    check(new RegExp(`\\['${k}', N_\\('\\w+'\\), '${a.d}', '${a.l}'\\]`).test(js), `${k}: LOOK table matches app.css`);
  }
  console.log('worst accent text contrast', worst.toFixed(2));
  // 1.1.3: Amber became Orange; it must stay apart from the high-priority red (--p5) in both themes (hue >= 15 degrees)
  const hue = hex => { const [r, g, b] = [0, 2, 4].map(i => parseInt(hex.slice(1 + i, 3 + i), 16) / 255), mx = Math.max(r, g, b), mn = Math.min(r, g, b), dd = mx - mn;
    if (!dd) return 0; const h = mx === r ? ((g - b) / dd) % 6 : mx === g ? (b - r) / dd + 2 : (r - g) / dd + 4; return (h * 60 + 360) % 360; };
  check(accents.orange && !accents.amber, 'orange replaces amber');
  if (accents.orange) {
    check(Math.abs(hue(accents.orange.d) - hue(root.p5)) >= 15, `orange vs priority red (dark): ${hue(accents.orange.d).toFixed(0)} / ${hue(root.p5).toFixed(0)}`);
    check(Math.abs(hue(accents.orange.l) - hue(light.p5)) >= 15, `orange vs priority red (light): ${hue(accents.orange.l).toFixed(0)} / ${hue(light.p5).toFixed(0)}`);
  }
  // rem scale: no fixed px sizes > 2px outside @media conditions (they would not follow the font size)
  const noMedia = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/@media[^{]*\{/g, '').replace('calc(16px * var(--ui))', '');
  const bad = [...noMedia.matchAll(/(?<![\w.#-])(\d*\.?\d+)px/g)].map(m => +m[1]).filter(v => v > 2 && v < 9999);
  check(bad.length === 0, 'app.css: only rem sizes (px > 2 left: ' + bad.slice(0, 5) + ')');
  check(/html\{[^}]*font-size:calc\(16px \* var\(--ui\)\)/.test(css) && /:root\[data-fsize="xl"\]\{--ui:1\.25\}/.test(css) && /:root\[data-fsize="s"\]\{--ui:\.9\}/.test(css), 'root font size = 16px x --ui, sizes 90 / 112 / 125 %');
  check(/@media print\{:root\[data-fsize\]\{--ui:1\}\}/.test(css), 'print: always 100 %');
  check(/:root\[data-font="atkinson"\]\{--sans:"Atkinson Hyperlegible"/.test(css) && /:root\[data-font="system"\]\{--sans:system-ui/.test(css), 'font variables');
  check(/--mono:"Geist Mono"/.test(css) && !/data-font[^{]*\{[^}]*--mono/.test(css), 'mono details always Geist Mono');
  check(/AtkinsonHyperlegible-Regular\.woff2/.test(sw) && /AtkinsonHyperlegible-Bold\.woff2/.test(sw), 'service worker precaches Atkinson regular + bold');
  for (const f of ['Regular', 'Bold', 'Italic', 'BoldItalic']) {
    const r = await fetch(B + `static/fonts/AtkinsonHyperlegible-${f}.woff2`);
    const b = Buffer.from(await r.arrayBuffer());
    check(r.ok && b.slice(0, 4).toString() === 'wOF2' && b.length < 40000, `font ${f} served (woff2, ${b.length} bytes)`);
  }
  check((await fetch(B + 'static/fonts/OFL-AtkinsonHyperlegible.txt')).ok, 'Atkinson license shipped');

  // ---- UI
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  let w = await boot({user: 'alice'}), d = w.document;
  const de = d.documentElement.dataset;
  check(de.fsize === 'm' && de.font === 'geist' && de.accent === 'violet' && de.theme === 'auto' && de.density === 'compact', 'defaults: normal size, Geist, violet (2.11.0), automatic, compact');
  check(w.eval('uiZ()') === 1 && w.eval('weekH()') === 44, 'default scale 1 (week grid 44 px per hour)');
  const before = (await (await w.fetch('/api/state')).json()).settings;
  w.eval(`settingsModal('look')`); await sleep(300);
  let md = d.querySelector('.modal.smodal');
  const secs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(secs.indexOf('look') === secs.indexOf('general') + 1, 'Appearance tab right after General: ' + secs);
  check(md.querySelector('.snav .on')?.dataset.sec === 'look' && !md.querySelector('[data-pane="look"]').classList.contains('hidden'), 'settingsModal("look") opens the tab');
  check(/Appearance/.test(md.querySelector('.snav [data-sec="look"]').textContent), 'tab label Appearance');
  check(!md.querySelector('[data-pane="general"] #s-theme') && !md.querySelector('[data-pane="general"] #s-density'), 'theme + density moved out of General');
  const pane = () => md.querySelector('[data-pane="look"]');
  check(['#s-theme', '#s-density', '#s-fsize', '#s-font', '#s-accent'].every(s => pane().querySelector(s)), 'pane: theme, density, font size, font, accent');
  check(pane().querySelector('.devtag'), 'pane tagged "This device"');
  check(pane().querySelector('#s-fsize').type === 'range' && pane().querySelector('#s-fsize').min === '75' && pane().querySelector('#s-fsize').max === '150' && pane().querySelector('#s-fsize').step === '5' && pane().querySelectorAll('#s-font button').length === 3 && pane().querySelectorAll('#s-accent button').length === 7, 'font size: a slider 75-150 % in 5 % steps (2.13.0 #429, 2.13.2 #478: from 75); fonts 3, accents 7');
  const pv = pane().querySelector('.lookpv');
  check(pv && pv.hasAttribute('inert') && pv.querySelector('.trow .chk') && pv.querySelector('.trow .meta .dt') && pv.querySelector('.btn.pri') && pv.querySelector('.lpv-link'), 'live preview: sample rows, date, button, link (inert)');
  check(pane().querySelector('#s-fsize').value === '100' && /100 %/.test(pane().querySelector('#s-fsv').textContent) && pane().querySelector('[data-look="accent"][data-v="violet"]').getAttribute('aria-pressed') === 'true', 'current values marked (class + aria-pressed)');
  const pick = async (k, v) => { click(w, pane().querySelector(`[data-look="${k}"][data-v="${v}"]`)); await sleep(40); };
  // font size
  const slide = async v => { const sl = pane().querySelector('#s-fsize'); sl.value = String(v); sl.dispatchEvent(new w.Event('input', {bubbles: true})); sl.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(40); };
  for (const [v, k] of [[75, 'custom'], [150, 'custom'], [90, 's'], [112, 'l'], [125, 'xl']]) {
    await slide(v);
    check(de.fsize === k && w.__store['tasks.fsize'] === JSON.stringify(v) && Math.abs(w.eval('uiZ()') - v / 100) < 1e-9 && (k !== 'custom' || d.documentElement.style.getPropertyValue('--ui') === String(v / 100)), `font size ${v} %: applied + stored`);
    check(pane().querySelector('#s-fsv').textContent === v + ' %' && d.documentElement.classList.contains('ui-small') === v < 100, `font size ${v} %: shown`);
  }
  check(w.eval('weekH()') === 55 && w.eval('tlDW()') === 45, 'JS-drawn sizes scale (week grid 55 px/h, timeline 45 px/day at 125 %)');
  check(!md.classList.contains('dirty'), 'no Save needed (dialog not dirty)');
  key(w, '-', {ctrlKey: true}, d.body); check(w.__store['tasks.fsize'] === '120', 'Ctrl + -: 5 % smaller'); key(w, '0', {ctrlKey: true}, d.body); check(!('tasks.fsize' in w.__store) && de.fsize === 'm', 'Ctrl + 0: back to 100 %'); await slide(125);
  // font
  for (const v of ['atkinson', 'system']) { await pick('font', v); check(de.font === v && w.__store['tasks.font'] === JSON.stringify(v), `font ${v}: applied + stored`); }
  // accent
  for (const v of ['sky', 'raspberry', 'rose', 'orange', 'lime']) { await pick('accent', v); check(de.accent === v && w.__store['tasks.accent'] === JSON.stringify(v), `accent ${v}: applied + stored`); }
  // theme + density (moved here)
  await pick('theme', 'light'); check(de.theme === 'light' && w.__store['tasks.theme'] === '"light"', 'theme light: applied + stored');
  check(d.querySelector('meta[name="theme-color"]').content === '#f8f8f9', 'theme-color meta follows');
  await pick('density', 'comfortable'); check(de.density === 'comfortable' && w.__store['tasks.density'] === '"comfortable"', 'density comfortable: applied + stored');
  const after = (await (await w.fetch('/api/state')).json()).settings;
  check(JSON.stringify(before) === JSON.stringify(after), 'nothing stored on the server');
  // logout keeps the device preferences
  w.eval('clearLocal()');
  check(['theme', 'density', 'fsize', 'font', 'accent'].every(k => ('tasks.' + k) in w.__store), 'logout / user switch keeps the appearance');
  const store = {...w.__store};
  w.close();
  // same device again: everything back; another device: defaults
  w = await boot({user: 'alice', ls: store}); d = w.document;
  let x = d.documentElement.dataset;
  check(x.fsize === 'xl' && x.font === 'system' && x.accent === 'lime' && x.theme === 'light' && x.density === 'comfortable', 'same device: restored on the next start');
  w.close();
  w = await boot({user: 'alice'}); d = w.document; x = d.documentElement.dataset;
  check(x.fsize === 'm' && x.font === 'geist' && x.accent === 'violet', 'other device: defaults (per device)');
  w.close();
  // garbage in localStorage -> defaults
  w = await boot({user: 'alice', ls: {'tasks.fsize': '"huge"', 'tasks.font': '"comic"', 'tasks.accent': '"<x>"', 'tasks.theme': '"light"'}}); d = w.document; x = d.documentElement.dataset;
  check(x.fsize === 'm' && x.font === 'geist' && x.accent === 'violet', 'unknown stored values fall back to the defaults');
  // reset to defaults
  w.eval(`settingsModal('look')`); await sleep(300);
  md = d.querySelector('.modal.smodal');
  await pick('accent', 'violet'); { const sl = pane().querySelector('#s-fsize'); sl.value = '110'; sl.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(40); }
  click(w, pane().querySelector('[data-m="look-reset"]')); await sleep(80);
  x = d.documentElement.dataset;
  check(x.fsize === 'm' && x.font === 'geist' && x.accent === 'violet' && x.theme === 'auto' && x.density === 'compact', 'reset: defaults applied');
  check(!['theme', 'density', 'fsize', 'font', 'accent'].some(k => ('tasks.' + k) in w.__store), 'reset: stored values removed');
  check(/reset/i.test(d.querySelector('#toast')?.textContent || ''), 'reset: toast');
  check(pane().querySelector('[data-look="accent"][data-v="violet"]').classList.contains('on'), 'reset: pane redrawn');
  md.remove();

  // ---- command palette
  const pal = async (q) => {
    key(w, 'k', {ctrlKey: true}); await sleep(80);
    const i = d.querySelector('.palette .pqin'); i.value = q; i.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(40);
    return d.querySelector('.palette .pitem.on');
  };
  const run = async (q, id) => { const it = await pal(q); const on = it?.dataset?.id || it?.id || ''; key(w, 'Enter', {}, d.querySelector('.palette .pqin')); await sleep(120); return on; };
  key(w, 'k', {ctrlKey: true}); await sleep(80);
  check(!/Accent color|Font size/.test(d.querySelector('.palette .plist').textContent), 'palette: appearance items only when searching');
  key(w, 'Escape', {}, d.querySelector('.palette .pqin')); await sleep(40);
  await run('accent violet'); check(d.documentElement.dataset.accent === 'violet' && w.__store['tasks.accent'] === '"violet"', 'palette: "accent violet"');
  await run('font size larger'); check(w.eval('fsPct()') === 105, 'palette: font size larger (100 -> 105 %)');
  await run('font size larger'); check(w.eval('fsPct()') === 110, 'palette: font size larger again (110 %)');
  w.eval(`LS.set('fsize', 150); applyLook()`); await pal('font size larger'); check(![...d.querySelectorAll('.palette .pitem:not(.pdo)')].some(x => /larger/.test(x.textContent)), 'palette: no "larger" at the largest size (2.16.0: only "Ask … / Create as task: …" with the typed text)');
  key(w, 'Escape', {}, d.querySelector('.palette .pqin')); await sleep(40);
  await run('font size smaller'); check(w.eval('fsPct()') === 145, 'palette: font size smaller (5 %)');
  await run('font atkinson'); check(d.documentElement.dataset.font === 'atkinson', 'palette: font Atkinson');
  await run('color scheme dark'); check(d.documentElement.dataset.theme === 'dark', 'palette: color scheme dark');
  const accItem = (await pal('accent sky'));
  check(accItem && accItem.querySelector('.psw')?.getAttribute('style')?.includes('#38bdf8'), 'palette: accent items show the swatch');
  key(w, 'Escape', {}, d.querySelector('.palette .pqin')); await sleep(40);
  await run('reset appearance'); check(d.documentElement.dataset.accent === 'violet' && d.documentElement.dataset.fsize === 'm' && d.documentElement.dataset.font === 'geist', 'palette: reset appearance');
  await run('settings appearance'); check(d.querySelector('.smodal .snav .on')?.dataset.sec === 'look', 'palette: Settings: Appearance');
  d.querySelector('.smodal')?.remove();
  w.close();

  // ---- phone + German
  await (await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: await require('./boot').login('alice')}, body: JSON.stringify({lang: 'de'})})).text();
  w = await boot({user: 'alice', ls: {'tasks.accent': '"amber"'}}); d = w.document;
  check(d.documentElement.dataset.accent === 'orange' && w.__store['tasks.accent'] === '"orange"', 'stored "amber" (1.1.2) is migrated to "orange"');
  w.close();
  w = await boot({user: 'alice', mobile: true, ls: {'tasks.fsize': '"xl"'}}); d = w.document;
  check(d.documentElement.dataset.fsize === 'xl' && d.documentElement.dataset.density === 'comfortable', 'phone: 125 % + comfortable');
  w.eval(`settingsModal('look')`); await sleep(300);
  md = d.querySelector('.modal.smodal');
  const t = md.querySelector('[data-pane="look"]').textContent;
  check(/Darstellung/.test(md.querySelector('.snav [data-sec="look"]').textContent) && /Schriftgröße/.test(t) && /Akzentfarbe/.test(t) && /Zurücksetzen \(100 %\)/.test(t) && /Auf Standard zurücksetzen/.test(t), 'German labels');
  md.remove();
  key(w, 'k', {ctrlKey: true}); await sleep(80);
  const i = d.querySelector('.palette .pqin'); i.value = 'akzent'; i.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(40);
  check(/Akzentfarbe: Violett/.test(d.querySelector('.palette .plist').textContent), 'German palette entries');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
