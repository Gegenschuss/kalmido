// 2.30.0 UI tests (files), own container (start.sh), Firefox (WebDriver BiDi):
// #1035 a click on a Markdown file (task attachment, comment file, agent chat file) opens the text viewer: formatted with the
//      description's renderer (headings, lists, tables, code), switch "Formatted / Source", Copy, Download, Close / Esc;
//      .html / .json / .sh.txt open as source text (highlighted), never rendered. A hostile .md (<script>, <img onerror>,
//      javascript: / data: links, attribute injection, raw <iframe> / <svg onload>) runs nothing and produces no such element;
//      links open in a new tab with rel noopener noreferrer. Dark mode, and full screen on the phone (390, touch) without
//      sideways scrolling of the page.
// #380 a file an agent wrote says "Created by agent" on its tile and in the viewer.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2300_files_ui', check, shots: 'P2300_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const V = B + 'api/v1';

const EVIL = [
  '# Report title',
  '## Findings',
  '- first point with **bold**',
  '- second point',
  '  - nested',
  '1. one',
  '2. two',
  '',
  '| Name | Value | Note |',
  '|:-----|------:|:----:|',
  '| alpha | 1 | ok |',
  '| beta \\| pipe | 22 | `code` |',
  '',
  '> a quoted line',
  '',
  '---',
  '```js',
  'const x = "<b>not bold</b>"; // comment',
  '```',
  '<script>window.__pwn = 1</script>',
  '<img src=x onerror="window.__pwn = 2">',
  '[click me](javascript:window.__pwn=3)',
  '[data](data:text/html,<script>parent.__pwn=4</script>)',
  '![pic](javascript:window.__pwn=5)',
  '<a href="javascript:window.__pwn=6">raw link</a>',
  '[x](https://example.com/"onmouseover="window.__pwn=7)',
  '<iframe src="javascript:parent.__pwn=8"></iframe>',
  '<svg onload="window.__pwn=9"></svg>',
  '<details open ontoggle="window.__pwn=10">x</details>',
  '[good](https://example.com/page?a=1&b=2) and https://example.org/bare.',
].join('\n');
const HTML = '<!doctype html>\n<html><body onload="window.__pwn=11">\n<script>window.__pwn = 12</script>\n<p class="x">Hello</p>\n</body></html>\n';
const SAFE_JS = `(() => {
  const b = document.querySelector('.tview .tvbody'); if (!b) return 'no body';
  const bad = b.querySelectorAll('script,iframe,object,embed,svg,img,details,style,link,meta,form,input:not([type=checkbox])');
  const bad2 = [...bad].filter(e => !(e.tagName.toLowerCase() === 'svg' && e.closest('.mdcopy')));  // the code block's Copy icon
  if (bad2.length) return 'bad elements: ' + bad2.map(e => e.tagName).join(',');
  for (const e of b.querySelectorAll('*')) for (const a of e.attributes) if (/^on/i.test(a.name)) return 'handler ' + a.name;
  for (const a of b.querySelectorAll('a')) { const h = a.getAttribute('href') || ''; if (!/^(https?:|mailto:)/i.test(h)) return 'href ' + h; if (a.target !== '_blank' || !/noopener/.test(a.rel) || !/noreferrer/.test(a.rel)) return 'rel ' + a.rel; }
  return window.__pwn === undefined ? 'ok' : 'pwn ' + window.__pwn;
})()`;

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,agents'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments', 'attachments:read', 'attachments:write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Reviews'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PATCH', `/api/lists/${L}`, {agent_members: true, agent_peers: true});
  const T = (await call('POST', '/api/tasks', {title: 'Security review', list_id: L})).id;
  const put = async (name, content) => { const r = await fetch(`${V}/tasks/${T}/attachments/text`, {method: 'POST', headers: AGH, body: JSON.stringify({name, content})}); return r.json(); };
  const md = await put('review.md', EVIL), html = await put('page.html', HTML), sh = await put('deploy.sh', 'echo "hi"\nrm -rf /tmp/x\n');
  await put('data.json', '{"a": [1, 2, {"b": null}], "s": "<script>"}');
  check(md.name === 'review.md' && html.name === 'page.html' && sh.name === 'deploy.sh.txt', '#380: the agent stored its files ' + [md.name, html.name, sh.name].join(' '));
  // a comment with a Markdown file (person) + an agent chat message with one
  let fd = new FormData(); fd.append('body', 'Notes attached'); fd.append('file', new Blob(['# Comment notes\n\n- a\n- b\n'], {type: 'text/markdown'}), 'notes.md');
  let r = await fetch(B + `api/tasks/${T}/comments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(r.ok, 'comment with notes.md ' + r.status);
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Hello'});
  fd = new FormData(); fd.append('body', 'Here is the report'); fd.append('file', new Blob(['# Chat report\n\n| k | v |\n|---|---|\n| a | 1 |\n'], {type: 'text/markdown'}), 'chat-report.md');
  r = await fetch(V + '/agent/chats/1', {method: 'POST', headers: {Authorization: AGH.Authorization}, body: fd});
  check(r.status === 201, 'agent chat file ' + r.status);

  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#top h1', n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector(${JSON.stringify(sel)})`).catch(() => false)); i++) await sleep(300); await sleep(600); };
  const waitFor = async (ev, expr, n = 30) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
  const openTile = (ev, scope, name) => ev(`(() => { const a = [...document.querySelectorAll(${JSON.stringify(scope + ' a[data-tview]')})].find(x => x.title === ${JSON.stringify(name)}); if (!a) return false; a.click(); return true; })()`);

  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#t/' + T); await ready(ev, '#detail .attsec');
    await waitFor(ev, `!!document.querySelector('#detail .attsec a[data-tview]')`);
    check(await ev(`(() => { const a = [...document.querySelectorAll('#detail .attsec .att.file')].find(x => /review\\.md/.test(x.textContent)); return !!a && /Created by agent/.test(a.textContent); })()`), `${tag}: #380 the tile says "Created by agent"`);
    check(await openTile(ev, '#detail .attsec', 'review.md'), `${tag}: #1035 the .md tile is a viewer link`);
    check(await waitFor(ev, `!!document.querySelector('.tview .tvmd h4')`), `${tag}: #1035 the viewer opens formatted`);
    await sleep(500);
    const fm = await ev(`(() => { const b = document.querySelector('.tview .tvbody'); return {h4: b.querySelector('h4')?.textContent, h5: !!b.querySelector('h5'), ul: b.querySelectorAll('ul li').length, ol: b.querySelectorAll('ol li').length,
      th: [...b.querySelectorAll('table th')].map(x => x.textContent), td: [...b.querySelectorAll('table td')].map(x => x.textContent), right: b.querySelector('table td.ta-r')?.textContent,
      code: b.querySelector('.mdcode code')?.textContent, kw: !!b.querySelector('.mdcode .hl-k'), q: !!b.querySelector('blockquote'), hr: !!b.querySelector('hr'),
      seg: [...document.querySelectorAll('.tview .tvseg button')].map(x => x.textContent), note: document.querySelector('.tview .tvnote')?.textContent || '',
      dl: document.querySelector('.tview a[download]')?.getAttribute('href') || '', copy: !!document.querySelector('.tview [data-tv="copy"]'),
      txt: b.textContent}; })()`);
    check(fm.h4 === 'Report title' && fm.h5 && fm.ul >= 3 && fm.ol === 2, `${tag}: #1035 headings + lists ` + JSON.stringify([fm.h4, fm.h5, fm.ul, fm.ol]));
    check(JSON.stringify(fm.th) === '["Name","Value","Note"]' && fm.td.includes('beta | pipe') && fm.right === '1', `${tag}: #1035 the table (aligned, \\| = a pipe) ` + JSON.stringify([fm.th, fm.td, fm.right]));
    check(fm.code === 'const x = "<b>not bold</b>"; // comment' && fm.kw, `${tag}: #1035 the code block, highlighted, as text`);
    check(fm.q && fm.hr, `${tag}: #1035 quote + rule`);
    check(fm.seg.join('|') === 'Formatted|Source' && fm.copy && /api\/attachments\/\d+\?v=\d+&dl=1/.test(fm.dl), `${tag}: #1035 switch, Copy, Download ` + JSON.stringify([fm.seg, fm.dl]));
    check(/Created by agent Claude/.test(fm.note), `${tag}: #380 the viewer says who wrote it ` + fm.note);
    check(/<script>window.__pwn = 1<\/script>/.test(fm.txt) && /onerror/.test(fm.txt), `${tag}: #1035 raw HTML shows as text`);
    await sleep(800);  // an image error / a load handler would have fired by now
    const safe = await ev(SAFE_JS);
    check(safe === 'ok', `${tag}: #1035 the hostile Markdown runs nothing (${safe})`);
    check(await ev(`(() => { const a = [...document.querySelectorAll('.tview .tvbody a')].find(x => x.textContent === 'good'); return !!a && a.getAttribute('href') === 'https://example.com/page?a=1&b=2'; })()`), `${tag}: #1035 a good link stays`);
    check(await ev(`(() => { const c = getComputedStyle(document.querySelector('.tview .tvbox')); return c.backgroundColor; })()`).then(bg => th === 'dark' ? !/255, 255, 255/.test(bg) : true), `${tag}: the viewer follows the theme`);
    await shot(`p2300-${th}-1440-md-formatted.png`);
    // Source
    await ev(`(() => { document.querySelector('.tview [data-tv="src"]').click(); return 1; })()`); await sleep(300);
    check(await ev(`(() => { const p = document.querySelector('.tview pre.tvsrc'); return !!p && p.textContent.startsWith('# Report title') && p.textContent.includes('<iframe src="javascript:parent.__pwn=8"></iframe>'); })()`), `${tag}: #1035 Source shows the file as it is`);
    check(await ev(SAFE_JS) === 'ok', `${tag}: #1035 ... and runs nothing either`);
    await shot(`p2300-${th}-1440-md-source.png`);
    await ev(`(() => { document.querySelector('.tview [data-tv="fmt"]').click(); return 1; })()`); await sleep(200);
    // Esc closes
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`); await sleep(300);
    check(await ev(`!document.querySelector('.tview')`), `${tag}: #1035 Esc closes the viewer`);
    // HTML -> source, highlighted, never rendered
    check(await openTile(ev, '#detail .attsec', 'page.html'), `${tag}: #1035 the .html tile opens the viewer`);
    check(await waitFor(ev, `!!document.querySelector('.tview pre.tvsrc .hl-t')`), `${tag}: #1035 HTML as highlighted source`);
    check(await ev(`!document.querySelector('.tview .tvseg') && /window.__pwn = 12/.test(document.querySelector('.tview pre.tvsrc').textContent)`), `${tag}: #1035 ... no Formatted switch, the script is text`);
    await sleep(400);
    check(await ev(SAFE_JS) === 'ok', `${tag}: #1035 the HTML runs nothing`);
    await shot(`p2300-${th}-1440-html-source.png`);
    await ev(`(() => { document.querySelector('.tview [data-tv="x"]').click(); return 1; })()`); await sleep(200);
    check(await openTile(ev, '#detail .attsec', 'deploy.sh.txt'), `${tag}: #380 deploy.sh.txt opens as text`);
    check(await waitFor(ev, `/rm -rf/.test(document.querySelector('.tview pre.tvsrc')?.textContent || '')`), `${tag}: ... with its content`);
    await ev(`(() => { document.querySelector('.tview').click(); return 1; })()`); await sleep(200);
    check(await ev(`!document.querySelector('.tview')`), `${tag}: a click beside the box closes it`);
    // a comment's file
    await waitFor(ev, `!!document.querySelector('#detail .catts a[data-tview]')`);
    check(await openTile(ev, '#detail .catts', 'notes.md'), `${tag}: #1035 a comment's .md opens the viewer`);
    check(await waitFor(ev, `document.querySelector('.tview .tvmd h4')?.textContent === 'Comment notes'`), `${tag}: ... formatted`);
    check(await ev(`!document.querySelector('.tview .tvnote')`), `${tag}: a person's file has no agent note`);
    await ev(`(() => { document.querySelector('.tview [data-tv="x"]').click(); return 1; })()`);
    // the agent chat
    await o.nav(B + '#agents/' + AG); await ready(ev, '.chatts');
    check(await openTile(ev, '.chatts', 'chat-report.md'), `${tag}: #1035 a chat file .md opens the viewer`);
    check(await waitFor(ev, `!!document.querySelector('.tview .tvmd table')`), `${tag}: ... with its table`);
    await shot(`p2300-${th}-1440-chat-md.png`);
  });

  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'dark') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#t/' + T); await ready(ev, '#detail .attsec');
    await waitFor(ev, `!!document.querySelector('#detail .attsec a[data-tview]')`);
    check(await openTile(ev, '#detail .attsec', 'review.md'), `${tag}: #1035 the tile opens the viewer on the phone`);
    check(await waitFor(ev, `!!document.querySelector('.tview .tvmd h4')`), `${tag}: ... formatted`);
    await sleep(500);
    const g = await ev(`(() => { const r = document.querySelector('.tview .tvbox').getBoundingClientRect(), t = document.querySelector('.tview .mdtbl'); return {w: r.width, h: r.height, l: r.left, t: r.top, page: document.documentElement.scrollWidth, tbl: t ? t.getBoundingClientRect().right <= 391 : false}; })()`);
    check(g.w >= 389 && g.h >= 800 && g.l <= 1 && g.t <= 1, `${tag}: #1035 full screen ` + JSON.stringify(g));
    check(g.page <= 390 && g.tbl, `${tag}: #1035 nothing scrolls the page sideways ` + JSON.stringify(g));
    check(await ev(SAFE_JS) === 'ok', `${tag}: #1035 runs nothing`);
    check(await ev(`(() => { const b = [...document.querySelectorAll('.tview .tvbar .iconbtn')]; return b.length === 3 && b.every(x => { const r = x.getBoundingClientRect(); return r.width >= 36 && r.right <= 390; }); })()`), `${tag}: #1035 Copy / Download / Close are big enough and visible`);
    await shot('p2300-dark-390-md.png');
    await ev(`(() => { document.querySelector('.tview [data-tv="src"]').click(); return 1; })()`); await sleep(300);
    check(await ev(`!!document.querySelector('.tview pre.tvsrc') && document.documentElement.scrollWidth <= 390`), `${tag}: #1035 Source on the phone`);
    await shot('p2300-dark-390-source.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
