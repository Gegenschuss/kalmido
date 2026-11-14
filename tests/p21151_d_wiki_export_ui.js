// kalmido-suite: fresh
// 2.1151.0 D (#5524) UI test, Firefox, own container (start.sh), invented data only. A knowledge page's "…" offers "Download
// as PDF" and "Download as Word (.docx)"; each starts a download of /api/wiki/pages/<id>/export with the reading style the page
// is shown in, and the file that comes is a PDF / a Word file holding the page's title and text. A read-only member (who has
// no "Rename…") gets the two entries too. The browser's own Word file of a space with the lock (wkdoc.js, loaded on demand)
// holds the page's heading, its bold text and its list. P21151D_SHOTS=dir: pictures.
// freelancer-matrix: n/a - nur Oberfläche (the route's freelancer case is in p21151_d_wiki_export_test.py)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21151_d_wiki_export_ui', check, shots: 'P21151D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21151D_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const MODS = 'wiki,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', password: 'password123'})});
  const CA = (r.headers.get('set-cookie') || '').split(';')[0];
  const call = (method, url, body) => fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}).then(x => x.json());
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: MODS.split(',')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS + ',collab'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'rita', display_name: 'Rita', password: 'password123', email: 'rita@example.com', orgs: [{id: ORG, role: 'readonly'}]});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'org:' + ORG, path: 'Letters/Quote Birchwood', body: 'Dear client,\n\nthe **new plan** follows.\n\n- Survey\n- Report\n'})).id;
  check(PG > 0, 'a page of the organisation ' + PG);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const openMenu = async ev => {
    await ev(`(() => { document.querySelector('#view [data-wk="pmenu"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`, 20);
    return (await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim())`)) || [];
  };
  // a click on a menu entry; the download link it makes is caught (its address), then fetched in the page like the browser would
  const download = async (ev, label) => {
    await ev(`(() => { window.__dl = null; if (!window.__dlHook) { window.__dlHook = 1; const c = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = function () { if (this.hasAttribute('download') && /\\/export\\?/.test(this.href)) { window.__dl = this.href; return; } return c.call(this); }; } return 1; })()`);
    await openMenu(ev);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => x.textContent.trim() === ${JSON.stringify(label)}).click(); return 1; })()`);
    await ready(ev, `!!window.__dl`, 20);
    return ev(`(async () => { const u = window.__dl; if (!u) return {u: null}; const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
      let doc = ''; if (b[0] === 0x50 && b[1] === 0x4b) { const e = wkeUnzip(b).find(x => x.name === 'word/document.xml'); if (e) doc = new TextDecoder().decode(e.method === 8 ? await wkeInflate(e.data()) : e.data()); }
      return {u, status: r.status, type: r.headers.get('content-type'), head: String.fromCharCode(...b.slice(0, 8)), size: b.length, doc}; })()`);
  };

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('wkSt', 'book'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login in the browser');
    await nav(B + `#wiki/${PG}`);
    check(await ready(ev, `!!S.booted && !!document.querySelector('#view [data-wk="pmenu"]') && !!document.querySelector('#view .wkpage')`, 80), 'computer: the page is open');
    const it = await openMenu(ev);
    await shot('p21151d-menu.png');
    check(it.includes('Download as PDF') && it.includes('Download as Word (.docx)') && it.includes('Rename…'), 'the page\'s "…" offers PDF and Word ' + JSON.stringify(it));
    await ev(`(() => { closePop(); return 1; })()`);
    const pdf = await download(ev, 'Download as PDF');
    check(pdf.u && pdf.u.includes(`/api/wiki/pages/${PG}/export?format=pdf`) && pdf.u.includes('style=book'), 'PDF: the download asks for the page in the reading style shown (Book) ' + JSON.stringify(pdf.u));
    check(pdf.status === 200 && /application\/pdf/.test(pdf.type || '') && pdf.head.startsWith('%PDF-') && pdf.size > 2000, 'PDF: the file comes ' + JSON.stringify({...pdf, doc: undefined}));
    const docx = await download(ev, 'Download as Word (.docx)');
    check(docx.status === 200 && /wordprocessingml/.test(docx.type || ''), 'Word: the file comes ' + JSON.stringify({...docx, doc: undefined}));
    check(docx.doc.includes('Quote Birchwood') && docx.doc.includes('new plan') && docx.doc.includes('Survey'), 'Word: document.xml holds the page\'s title and text ' + docx.doc.slice(0, 300));
    // the browser's own Word file (a space with the lock): wkdoc.js on demand, made from the page as the app draws it
    const loc = await ev(`(async () => { await loadModule('wkdoc'); const b = wdxDocx({id: 1, space: 'private', path: 'Sealed/Plan Oak', body: '# Plan Oak\\n\\nWe build **two rooms**.\\n\\n1. Floor\\n2. Roof\\n\\nSee [the site](https://example.com/x)'});
      const u = new Uint8Array(await b.arrayBuffer()), es = wkeUnzip(u), get = n => { const e = es.find(x => x.name === n); return e ? new TextDecoder().decode(e.data()) : ''; };
      return {names: es.map(e => e.name), doc: get('word/document.xml'), rels: get('word/_rels/document.xml.rels'), type: b.type}; })()`);
    check(loc.names.includes('[Content_Types].xml') && loc.names.includes('word/styles.xml') && /wordprocessingml/.test(loc.type), 'browser Word file: the parts of a .docx ' + JSON.stringify(loc.names));
    check(/Heading1/.test(loc.doc) && loc.doc.includes('Plan Oak') && !/w:val="Title"/.test(loc.doc), 'browser Word file: the heading, no second title ' + loc.doc.slice(0, 300));
    check(/<w:b\/>/.test(loc.doc) && loc.doc.includes('two rooms') && loc.doc.includes('Floor') && /<w:numId w:val="2"\/>/.test(loc.doc), 'browser Word file: bold run and the numbered list');
    check(loc.rels.includes('https://example.com/x') && /<w:hyperlink/.test(loc.doc), 'browser Word file: the web link');
    // ---- a read-only member: no "Rename…", the downloads are there
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: ${JSON.stringify(H)}}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'rita', password: 'password123'})}).then(r => r.status)`) === 200, 'rita logs in');
    await ev(`fetch('/api/settings', {method: 'PATCH', headers: ${JSON.stringify(H)}, body: JSON.stringify({lang: 'en', tour: 'done', features: '${MODS},collab'})}).then(r => r.status)`);
    await nav(B + `#wiki/${PG}`);
    check(await ready(ev, `!!S.booted && !!document.querySelector('#view [data-wk="pmenu"]')`, 80), 'read-only: the page shows its "…"');
    const ri = await openMenu(ev);
    await shot('p21151d-readonly-menu.png');
    check(ri.includes('Download as PDF') && ri.includes('Download as Word (.docx)') && !ri.includes('Rename…'), 'read-only: only reading entries, the downloads among them ' + JSON.stringify(ri));
    await ev(`(() => { closePop(); return 1; })()`);
    const rp = await download(ev, 'Download as PDF');
    check(rp.status === 200 && rp.head.startsWith('%PDF-'), 'read-only: the PDF comes ' + JSON.stringify({...rp, doc: undefined}));
  }, true);

  console.log(`p21151_d_wiki_export_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
