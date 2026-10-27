// 2.376 A UI tests (#3292, #3293, #3294), own container (start.sh), jsdom, a person without an organisation, invented texts only:
// kalmido-suite:
// - #3292 "Found in the text": each hit shows its snippet below the name (.wksnip), the query words <b>, the text escaped;
//   the browser's own cut (wks_snip, for texts it has already: a space with the lock, offline) gives the same as the server;
//   a hit without a text (a locked page) shows the name only, without an error
// - #3293 a step in the panel (another folder, the top again) or a hit opened ends the search: the field empty, the folder's
//   list shows; Back finds the folder without the hits
// - #3294 a ```seiten block (```pages): the space's pages as a nested list sorted by path (numbers in order), links
//   #wiki/<id> named by the last part, ohne / ab / tiefe (exclude / from / depth), empty = a grey hint, names escaped
// - Firefox (the real layout): the snippet below the name in at most two lines, inside the screen; the block as an indented list;
//   the index or a page that arrives while the search field has the focus is drawn at once
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return c; };
const firefox = require('./ff')({tag: 'p2376_a_wiki_snippet_ui', check, shots: 'P2321A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2321A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const type = (w, d, v) => { const q = d.querySelector('#wk-q'); q.value = v; q.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const FILL = Array.from({length: 40}, (_, i) => 'wort' + String(i).padStart(3, '0')).join(' ');
  const BODY = `# Kopf\n\n${FILL} Der **Kühlschrank** hat 3 < 5 & mehr an der [[Plan/Straße|Straße]]. ${FILL}`;
  const id = {};
  for (const [k, p, b] of [['note', 'Haushalt/Notiz', BODY], ['alpha', 'Projekte/Alpha', 'A'], ['gamma', 'Projekte/Beta/Gamma', 'G'], ['i10', 'Projekte/Item 10', 'x'],
    ['i2', 'Projekte/Item 2', 'x'], ['odd', 'Projekte/Odd <b>name', 'x'], ['lib', 'Library/Buch', 'x'], ['repo', 'Repositories/Code', 'x'], ['cfg', 'CONFIG', 'x'],
    ['start', 'Start', 'Intro\n\n```seiten\nohne: Library, repositories, Config\n```\n\nEnde']]) {
    id[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  }
  check(Object.values(id).every(Boolean), 'setup: the pages');

  // ================= #3292 the snippet under the name
  const w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  await until(() => d.querySelector('#wk-q') && rowOf(d, 'Projekte'));
  type(w, d, 'kuhlschrank');
  const sn = await until(() => d.querySelector('#wks .wksnip'));
  check(sn && [...sn.querySelectorAll('b')].map(b => b.textContent).join('|') === 'Kühlschrank', 'the hit has its snippet, the word bold ' + (sn?.innerHTML || '').slice(0, 300));
  check(sn && sn.textContent.startsWith('…') && sn.textContent.endsWith('…') && sn.textContent.includes('3 < 5 & mehr') && !sn.querySelector(':not(b)'), 'plain text, escaped, "…" where cut ' + (sn?.textContent || ''));
  check(sn && sn.closest('.wkitem')?.querySelector('span')?.textContent === 'Haushalt/Notiz', 'the snippet sits below the name');
  const srv = await call('GET', '/api/wiki/search?q=kuhlschrank'), sp = (srv.pages || []).find(p => p.id === id.note);
  const loc = JSON.parse(w.eval(`JSON.stringify(wks_snip(${JSON.stringify(BODY)}, 'kuhlschrank'))`));
  check(sp && loc && loc.snippet === sp.snippet && JSON.stringify(loc.marks) === JSON.stringify(sp.marks), 'the browser cuts like the server ' + JSON.stringify([loc, sp && {snippet: sp.snippet, marks: sp.marks}]).slice(0, 500));
  const l2 = JSON.parse(w.eval(`JSON.stringify(wks_snip('Ein ab und abseits davon, STRASSE: die Straße', 'ab strasse'))`));
  check(l2 && JSON.stringify(l2.marks.map(([a, b]) => Array.from(l2.snippet).slice(a, b).join(''))) === '["ab","STRASSE","Straße"]', 'short words whole only, ß = ss, capitals ' + JSON.stringify(l2));
  const lh = w.eval(`wk_hitHtml({id: 9, path: 'Locked', space: 'private', body: '', _wke: 'locked'}, 0) + wk_hitHtml({id: 8, path: 'X', space: 'private'}, 0)`);
  check(!lh.includes('wksnip') && lh.includes('Locked'), 'a hit without a text: the name only, no error');
  const lb = w.eval(`wk_hitHtml({id: 7, path: 'Open', space: 'private', body: 'Hier liegt der Kühlschrank <img src=x onerror=alert(1)> neu'}, 0)`);
  check(lb.includes('<b>Kühlschrank</b>') && !lb.includes('<img'), 'a text the browser has (a space with the lock): its own snippet, tags left out');

  // ================= #3293 the panel and a hit end the search
  check(await until(() => d.querySelector('#view #wk-res .wkitem')), 'setup: the hits replace the folder');
  rowOf(d, 'Projekte').querySelector('.sbbtn').click();
  check(await until(() => w.eval('WK.q') === '' && d.querySelector('#wk-q')?.value === '' && !d.querySelector('#wks') && d.querySelector('#view .wkfolder h2')?.textContent === 'Projekte'),
    'a folder in the panel: the search ends, the folder shows ' + d.querySelector('#view .wkfolder h2')?.textContent);
  check(d.querySelector(`#view .wkdlist a[href="#wiki/${id.alpha}"]`), 'the folder list has its pages');
  type(w, d, 'Alpha');
  await until(() => d.querySelector('#view #wk-res.wkdlist a[href^="#wiki/"]'));
  rowOf(d, 'Projekte').querySelector('.sbbtn').click();  // the same place again: drawn at once
  check(await until(() => w.eval('WK.q') === '' && d.querySelector('#view .wkfolder h2')?.textContent === 'Projekte' && !d.querySelector('#view #wk-res.wkdlist, #wks')), 'the same folder clicked again: the search ends too');
  w.location.hash = '#wiki'; await sleep(300);
  type(w, d, 'kuhlschrank');
  const a = await until(() => d.querySelector(`#wks a[href="#wiki/${id.note}"]`));
  a?.click(); if (a) w.location.hash = a.getAttribute('href');  // jsdom does not follow a link
  check(await until(() => w.eval('WK.q') === '' && d.querySelector('#view .wkpage') && w.eval('WK.pg && WK.pg.id') === id.note), 'a hit opened: the page shows, the search ended');
  w.history.back();
  check(await until(() => w.location.hash === '#wiki' && d.querySelector('#view .wkfolder') && !d.querySelector('#wks') && d.querySelector('#wk-q')?.value === ''), 'Back: the folder, without the hits ' + w.location.hash);

  // ================= #3294 the ```seiten block
  w.location.hash = '#wiki/' + id.start;
  const toc = await until(() => d.querySelector('#view .wkpage .wktoc ul'));
  const top = toc ? [...toc.children].map(li => li.firstElementChild?.textContent) : [];
  check(JSON.stringify(top) === JSON.stringify(['Haushalt', 'Projekte', 'Start']), 'top level sorted, ohne leaves out Library, Repositories, CONFIG (case ignored) ' + JSON.stringify(top));
  const pj = toc && [...toc.children].find(li => li.firstElementChild?.textContent === 'Projekte');
  const kids = pj ? [...pj.querySelector(':scope > ul').children].map(li => li.firstElementChild?.textContent) : [];
  check(JSON.stringify(kids) === JSON.stringify(['Alpha', 'Beta', 'Item 2', 'Item 10', 'Odd <b>name']), 'one level in per folder, sorted by path, numbers in order, names escaped ' + JSON.stringify(kids));
  check(pj && pj.firstElementChild.tagName === 'SPAN' && !d.querySelector('#view .wktoc li b'), 'a folder without a page of its own: a plain name');
  const ga = pj?.querySelector(':scope > ul > li > ul a');
  check(ga && ga.textContent === 'Gamma' && ga.getAttribute('href') === '#wiki/' + id.gamma, 'a link #wiki/<id> named by the last part, nested below Beta');
  check(!!d.querySelector(`#view .wktoc a[href="#wiki/${id.start}"]`) && !d.querySelector(`#view .wktoc a[href="#wiki/${id.lib}"]`), 'the page itself listed, excluded ones not');
  const r1 = w.eval(`(() => { const x = document.createElement('div'); x.innerHTML = wk_tocHtml('private', 'ab: Projekte/\\ntiefe: 1'); return [...x.querySelectorAll('li')].map(l => l.firstElementChild.textContent).join('|'); })()`);
  check(r1 === 'Alpha|Item 2|Item 10|Odd <b>name', 'ab: only that folder, relative; tiefe: 1 = its own level only ' + r1);
  const r2 = w.eval(`(() => { const x = document.createElement('div'); x.innerHTML = wk_render({space: 'private', body: '\`\`\`pages\\nfrom: Projekte\\ndepth: 2\\nexclude: item, odd\\n\`\`\`'}); return [...x.querySelectorAll('.wktoc li')].map(l => l.firstElementChild.textContent).join('|'); })()`);
  check(r2 === 'Alpha|Beta|Gamma', 'English pages / from / depth / exclude (relative to from) ' + r2);
  const r3 = w.eval(`wk_tocHtml('private', 'ab: Nirgendwo/')`);
  check(r3.includes('class="muted wktoc"') && r3.includes('No pages to list here.'), 'nothing to list: a grey hint ' + r3);

  // ================= Firefox: the real layout
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#wiki');
    await ready(ev, `!!document.querySelector('#wk-q') && typeof wks_html === 'function'`, 80);  // wkhist.js comes on demand; typed before the index is here: drawn when it comes (wk_redraw)
    await ev(`(() => { const q = document.querySelector('#wk-q'); q.focus(); q.value = 'kuhlschrank'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    if (!check(await ready(ev, `!!document.querySelector('#wks .wksnip b')`, 60), 'Firefox: the hit shows its snippet')) console.log(await ev(`document.querySelector('#view')?.textContent.slice(0, 400)`));
    const g = await ev(`(() => { const s = document.querySelector('#wks .wksnip'), n = s.closest('.wkitem').querySelector('span'), a = s.getBoundingClientRect(), b = n.getBoundingClientRect(), lh = parseFloat(getComputedStyle(s).lineHeight);
      return JSON.stringify({below: a.top >= b.bottom - 1, lines: Math.round(a.height / lh), inside: a.right <= document.documentElement.clientWidth, small: parseFloat(getComputedStyle(s).fontSize) < parseFloat(getComputedStyle(n).fontSize)}); })()`);
    const gj = JSON.parse(g || '{}');
    check(gj.below && gj.lines >= 1 && gj.lines <= 2 && gj.inside && gj.small, 'Firefox: the snippet below the name, smaller, at most two lines, inside the screen ' + g);
    await shot('p2321-a-snippet.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    const g2 = await ev(`(() => { const s = document.querySelector('#wks .wksnip'); if (!s) return 'none'; const a = s.getBoundingClientRect(), lh = parseFloat(getComputedStyle(s).lineHeight); return JSON.stringify({lines: Math.round(a.height / lh), inside: a.right <= document.documentElement.clientWidth}); })()`);
    check(g2 !== 'none' && JSON.parse(g2).lines <= 2 && JSON.parse(g2).inside, 'Firefox phone: still two lines at most, inside the screen ' + g2);
    await shot('p2321-a-snippet-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { const q = document.querySelector('#wk-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);  // the hits would stand in for the page; the page drawn although the field keeps the focus (wk_redraw)
    await nav(B + '#wiki/' + id.start);
    if (!check(await ready(ev, `!!document.querySelector('.wkpage .wktoc ul ul a')`, 60), 'Firefox: the block draws its nested list')) console.log(await ev(`location.hash + ' ' + (document.querySelector('#view')?.innerHTML || '').slice(0, 1500)`));
    const ind = await ev(`(() => { const a = document.querySelector('.wkpage .wktoc > ul > li > :first-child'), b = document.querySelector('.wkpage .wktoc ul ul a'); return b.getBoundingClientRect().left > a.getBoundingClientRect().left + 8; })()`);
    check(ind, 'Firefox: one level in = indented');
    await shot('p2321-a-toc.png');
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
