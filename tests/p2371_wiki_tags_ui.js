// 2.371 UI tests (#3150), own container (start.sh), jsdom, a person without an organisation, invented texts only:
// kalmido-suite:
// - #tags in a page's text are links to the tag's list (#wiki/t/<tag>), not inside code or a link, #123 stays a task; the
//   frontmatter's tags are links too
// - the panel has the group "Tags" below the folders (most used first); a tag opens its pages as rows; #wiki/t/ = all tags
// - the ```abfrage block (```query): a list of links, a table with the columns asked for, the open checkboxes; empty = a grey
//   hint, lines not understood are named; fresh after a change (S.v); names escaped
// - the browser's own run (a space with the lock, offline: wkt_tags / wkq_run) gives the same as the server
// - Firefox (the real layout): the tags in the text and the group in the panel, the block's table inside the screen
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return c; };
const firefox = require('./ff')({tag: 'p2371_wiki_tags_ui', check, shots: 'P2371_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2371_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const canon = v => JSON.stringify(v, (k, x) => x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => a < b ? -1 : 1)) : x);  // the server sorts the keys
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const T = {
    plan: ['Kunden/Nord', 'Plan für #Projekt und #kunde/Nord, Aufgabe #123, `#imcode`, [Link](https://example.com/#frag).\n\n- [ ] Angebot <b>schreiben</b>\n- [x] Erledigt\n\n```\n- [ ] im Code #imblock\n```'],
    sued: ['Kunden/Süd', '---\ntags: [projekt, intern]\nstatus: offen\n---\nText ohne Tag.'],
    west: ['Kunden/West', '---\ntag: projekt\nstatus: zu\n---\n- [ ] Rückruf'],
    odd: ['Kunden/Odd <i>name', '#projekt'],
    none: ['Notizen', 'Kein Tag.'],
    tpl: ['Templates/Vorlage', '#projekt'],
    q: ['Übersicht', 'Oben #übersicht\n\n```abfrage\ntag: projekt\nsortiere: name\n```\n\n```abfrage\ntag: projekt\nals: tabelle\nspalten: status\nfoo bar\n```\n\n```query\nshow: tasks\nfolder: Kunden\n```\n\n```abfrage\ntag: nirgends\n```'],
  };
  const id = {};
  for (const [k, [p, b]] of Object.entries(T)) id[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  check(Object.values(id).every(Boolean), 'setup: the pages');

  // ================= the tags in the text
  const w = await boot({user: 'alice', hash: 'wiki/' + id.plan}), d = w.document;
  const md = await until(() => d.querySelector('#view .wkpage #wk-md a.wktag') && d.querySelector('#view .wkpage #wk-md'));
  const links = md ? [...md.querySelectorAll('a.wktag')].map(a => a.textContent + '>' + a.getAttribute('href')) : [];
  check(JSON.stringify(links) === JSON.stringify(['#Projekt>#wiki/t/Projekt', '#kunde/Nord>#wiki/t/kunde%2FNord']), 'the #tags of the text are links to their list, not in code or a link target ' + JSON.stringify(links));
  check(md && !md.querySelector('code a.wktag, pre a.wktag') && md.textContent.includes('#123') && !md.querySelector('a.wktag[href*="123"]'), '#123 stays a task reference, code stays code');
  w.location.hash = '#wiki/' + id.sued;
  const at = await until(() => d.querySelector('#view .wkpage .wkattrs a.wktag'));
  check(at && [...d.querySelectorAll('#view .wkattrs a.wktag')].map(a => a.textContent).join(' ') === '#projekt #intern', 'the frontmatter tags are links too');

  // ================= the panel and a tag's list
  const grp = await until(() => rowOf(d, 'Tags'));
  check(grp, 'the panel has the group "Tags"');
  grp?.querySelector('.sbbtar')?.click();
  const tr1 = await until(() => rowOf(d, '#Projekt'));
  const order = [...d.querySelectorAll('#side .sbbt .sbbtn .n')].map(n => n.textContent).filter(t => t.startsWith('#'));
  check(tr1 && order[0] === '#Projekt' && order.includes('#intern') && !order.includes('#imcode') && !order.includes('#imblock'), 'most used first, no tag from code ' + JSON.stringify(order));
  tr1?.querySelector('.sbbtn')?.click();
  const rows = await until(() => { const r = [...d.querySelectorAll('#view .wktagview .wkdlist .wkitem span')].map(s => s.textContent); return r.length ? r : null; });
  check(w.location.hash === '#wiki/t/Projekt' && JSON.stringify(rows) === JSON.stringify(['Kunden/Nord', 'Kunden/Odd <i>name', 'Kunden/Süd', 'Kunden/West']),
    'a tag opens its pages (no template, names escaped) ' + w.location.hash + ' ' + JSON.stringify(rows));
  check(d.querySelector('#view .wktagview h2')?.textContent.trim() === '#Projekt', 'the list is headed by the tag');
  w.location.hash = '#wiki/t/fehlt';
  check(await until(() => d.querySelector('#view .wktagview .empty')), 'an unknown tag: "No page has this tag."');

  // ================= the ```abfrage block
  w.location.hash = '#wiki/' + id.q;
  const qs = await until(() => { const x = d.querySelectorAll('#view .wkpage .wkq'); return x.length === 4 && !d.querySelector('#view .wkpage p.wkq') ? [...x] : null; }, 60);
  check(qs, 'four blocks drawn ' + (d.querySelector('#view .wkpage')?.innerHTML || '').slice(0, 600));
  if (qs) {
    const l1 = [...qs[0].querySelectorAll('.wkqlist a')].map(a => a.textContent);
    check(JSON.stringify(l1) === JSON.stringify(['Nord', 'Odd <i>name', 'Süd', 'West']) && !qs[0].querySelector('.wkqlist i'), 'a list of links named by the page, escaped ' + JSON.stringify(l1));
    check(qs[0].querySelector('.wkqlist a')?.getAttribute('href') === '#wiki/' + id.plan && qs[0].querySelector('.wkqlist small')?.textContent === 'Kunden', 'links to the page, its folder beside it');
    const th = [...qs[1].querySelectorAll('thead th')].map(x => x.textContent), td = [...qs[1].querySelectorAll('tbody tr')].map(r => [...r.children].map(c => c.textContent).join('='));
    check(JSON.stringify(th) === JSON.stringify(['Page', 'status']) && td.includes('Süd=offen') && td.includes('West=zu') && td.includes('Nord='), 'a table with the columns asked for ' + JSON.stringify([th, td]));
    check(qs[1].querySelector('.wkqerr')?.textContent.includes('foo bar'), 'a line not understood is named');
    const tk = [...qs[2].querySelectorAll('.wkqtasks li')].map(li => li.querySelector('span').textContent + '@' + li.querySelector('a').textContent);
    check(JSON.stringify(tk) === JSON.stringify(['Angebot <b>schreiben</b>@Nord', 'Rückruf@West']) && qs[2].querySelector('input[type=checkbox][disabled]'), 'the open checkboxes with their page, escaped ' + JSON.stringify(tk));
    check(qs[3].querySelector('p.muted')?.textContent === 'No page matches this query.', 'nothing matches: a grey hint');
    check(!d.querySelector('#view .wkpage pre code')?.textContent.includes('tag: projekt'), 'the block is not shown as code');
  }
  // fresh after a change
  const nid = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Kunden/Neu', body: '#projekt neu'})).id;
  w.eval('S.v = (S.v || 0) + 1; viewSafeRender()');  // what a change pushed by the server does
  check(await until(() => [...d.querySelectorAll('#view .wkpage .wkq')][0]?.textContent.includes('Neu'), 60), 'a new page with the tag: the block shows it after the change');

  // ================= the browser's own run = the server's
  const full = [];
  for (const k of [...Object.keys(id), 'neu']) { const p = await call('GET', '/api/wiki/pages/' + (k === 'neu' ? nid : id[k])); full.push({id: p.id, path: p.path, attrs: p.attrs, body: p.body, updated_at: p.updated_at, created_at: p.created_at}); }
  full.sort((a, b) => a.path.toLowerCase() < b.path.toLowerCase() ? -1 : 1);  // as the index (and the server) go: by name, the first spelling wins
  const srvT = (await call('GET', '/api/wiki/tags?space=private')).tags;
  const locT = JSON.parse(w.eval(`(() => { const n = new Map(), s = new Map(); for (const p of ${JSON.stringify(full)}) if (!/^templates\\//i.test(p.path)) for (const [k, t] of wkt_tags(p.body)) { n.set(k, (n.get(k) || 0) + 1); if (!s.has(k)) s.set(k, t); } return JSON.stringify([...n.keys()].sort((a, b) => n.get(b) - n.get(a) || (a < b ? -1 : a > b ? 1 : 0)).map(k => ({tag: s.get(k), n: n.get(k)}))); })()`));
  check(canon(locT) === canon(srvT), 'the tags: the browser finds what the server finds ' + JSON.stringify([locT, srvT]).slice(0, 500));
  for (const q of ['tag: projekt', 'tag: projekt, intern', 'ordner: Kunden\nsortiere: status absteigend', 'eigenschaft: status = offen', 'property: status\nals: tabelle\nspalten: status', 'show: tasks\nfolder: kunden', 'tag: projekt\ngrenze: 2\nsort: name desc', 'foo\nzeige: alles']) {
    const s = await call('GET', '/api/wiki/query?page=' + id.q + '&q=' + encodeURIComponent(q)); delete s.http;
    const l = JSON.parse(w.eval(`JSON.stringify(wkq_run(wkq_parse(${JSON.stringify(q)}), ${JSON.stringify(full)}, ${id.q}))`));
    check(canon(l) === canon(s), 'the query run in the browser = the server: ' + JSON.stringify(q) + ' ' + JSON.stringify([l, s]).slice(0, 600));
  }

  // ================= Firefox: the real layout
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#wiki/' + id.q);
    if (!check(await ready(ev, `document.querySelectorAll('.wkpage .wkq').length === 4 && !!document.querySelector('.wkpage .wkqt')`, 80), 'Firefox: the blocks draw')) console.log(await ev(`(document.querySelector('#view')?.innerHTML || '').slice(0, 1500)`));
    const g = await ev(`(() => { const t = document.querySelector('.wkpage .wkqt'), r = t.getBoundingClientRect(), a = document.querySelector('.wkpage a.wktag'); return JSON.stringify({inside: r.right <= document.documentElement.clientWidth + 1, rows: t.querySelectorAll('tbody tr').length, tag: !!a && getComputedStyle(a).whiteSpace === 'nowrap'}); })()`);
    const gj = JSON.parse(g || '{}');
    check(gj.inside && gj.rows >= 4 && gj.tag, 'Firefox: the table inside the screen, the tag on one line ' + g);
    await shot('p2371-wiki-query.png');
    await nav(B + '#wiki/t/Projekt');
    check(await ready(ev, `!!document.querySelector('.wktagview .wkdlist .wkitem') && [...document.querySelectorAll('#side .sbbtn .n')].some(n => n.textContent === 'Tags')`, 60), 'Firefox: a tag\'s pages and the group in the panel');
    await shot('p2371-wiki-tag.png');
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
