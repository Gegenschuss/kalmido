// kalmido-suite:
// 2.519.0 UI test (#4467: the document pane on a computer stays below the page head; its title and the close button stay
// visible and clickable also after the list was scrolled), own container (start.sh), Firefox (1280 and 1024 px, light and
// dark). Invented data only. P2519A_NOSTART=1 = the container runs.
// P4: a person without an organisation (private documents) gets the same pane (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2519_a_docpane_sticky_ui', check, shots: 'P2519A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2519A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

const SCROLL = to => `(() => { const wrap = document.querySelector('.dc-wrap'); let sc = wrap; while (sc && !(sc.scrollHeight > sc.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement; sc = sc || document.querySelector('#view'); sc.scrollTop = ${to}; return Math.round(sc.scrollTop); })()`;

(async () => {
  await sleep(600);
  // alice: a person without an organisation, her private documents
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const fd = new FormData();
  for (let i = 1; i <= 24; i++) fd.append('files', new Blob([textPdf([`Beispiel Absender ${i}`, 'Rechnung', `Datum ${String(i).padStart(2, '0')}.10.2026`])], {type: 'application/pdf'}), `letter-${i}.pdf`);
  fd.append('ws', 'private');
  const ids = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids || [];
  check(ids.length === 24, '24 documents uploaded');
  check(await until(async () => { for (const id of ids) if (!['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state)) return false; return true; }, 300), '... all read');

  // bob: only three documents, the list is shorter than the pane (the case of the UI check: scrolled, the pane went under the head)
  const CKa = CK;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'});
  CK = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const fb = new FormData();
  for (let i = 1; i <= 3; i++) fb.append('files', new Blob([textPdf([`Kurz Absender ${i}`, 'Brief'])], {type: 'application/pdf'}), `short-${i}.pdf`);
  fb.append('ws', 'private');
  const bids = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fb})).json()).ids || [];
  check(bids.length === 3, 'bob: 3 documents uploaded');
  check(await until(async () => { for (const id of bids) if (!['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state)) return false; return true; }, 300), '... all read');
  CK = CKa;

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    // the scroll box of the list, the head above the page, the pane's title and close button, what lies on top of them
    const MEASURE = `(() => {
      const wrap = document.querySelector('.dc-wrap'); let sc = wrap; while (sc && !(sc.scrollHeight > sc.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
      const p = document.querySelector('.dc-pane'), h = document.querySelector('.dc-pane #dc-h'), x = document.querySelector('.dc-pane .dc-x');
      if (!p || !h || !x) return null;
      const hits = el => { const r = el.getBoundingClientRect(), t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!t && (t === el || el.contains(t)); };
      const heads = [...document.querySelectorAll('#kbar, #top')].filter(e => e.offsetParent || getComputedStyle(e).position === 'fixed').map(e => Math.round(e.getBoundingClientRect().bottom));
      const r = p.getBoundingClientRect();
      const top = t => { const e = document.elementFromPoint(t.left + t.width / 2, t.top + t.height / 2); return e ? e.tagName + (e.id ? '#' + e.id : '') : '-'; };
      return {sc: sc ? (sc.id || sc.className) : 'page', main: document.querySelector('#main').scrollTop, app: document.querySelector('#app').scrollTop, doc: document.scrollingElement.scrollTop, onX: top(x.getBoundingClientRect()), st: sc ? Math.round(sc.scrollTop) : 0, pt: Math.round(r.top), pb: Math.round(r.bottom), vh: innerHeight, head: Math.max(0, ...heads),
        ht: Math.round(h.getBoundingClientRect().top), xt: Math.round(x.getBoundingClientRect().top), hOk: hits(h), xOk: hits(x)};
    })()`;
    for (const [width, theme, height] of [[1280, 'light', 700], [1280, 'dark', 900], [1024, 'light', 800], [1280, 'light', 1000]]) {
      const at = `${width}x${height} ${theme}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
      await nav(B + '#docs');
      await ev(`(document.documentElement.dataset.theme = '${theme}', 1)`);
      check(await wait(`document.querySelectorAll('.dc-card').length >= 12`), `${at}: the cards`);
      // unscrolled: open one, title and X are free
      await ev(`(document.querySelector('.dc-view .dc-card [data-dco]').click(), 1)`);
      check(await wait(`!!document.querySelector('.dc-pane #dc-h')`), `${at}: the pane opens`);
      await sleep(300);  // the pane's slide-in is over (animation, not a state to wait on)
      let m = await ev(MEASURE);
      check(m && m.hOk && m.xOk && m.pt >= m.head, `${at}, list not scrolled: title and close button are free ` + JSON.stringify(m));
      await ev(`(document.querySelector('.dc-pane .dc-x').click(), 1)`);
      check(await wait(`!document.querySelector('.dc-pane')`), `${at}: the pane closes`);
      // scroll the list by 150 px, open a card that is in view
      check(await ev(`(() => { const wrap = document.querySelector('.dc-wrap'); let sc = wrap; while (sc && !(sc.scrollHeight > sc.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement; (sc || document.scrollingElement).scrollTop = 150; return (sc || document.scrollingElement).scrollTop >= 140; })()`), `${at}: the list scrolls by 150 px`);
      await ev(`(() => { const c = [...document.querySelectorAll('.dc-view .dc-card [data-dco]')].find(b => { const r = b.getBoundingClientRect(); return r.top > 150 && r.bottom < innerHeight - 20; }); c.click(); return 1; })()`);
      check(await wait(`!!document.querySelector('.dc-pane #dc-h')`), `${at}, scrolled: the pane opens`);
      await sleep(300);
      m = await ev(MEASURE);
      check(m && m.hOk && m.xOk && m.pt >= m.head && m.pb <= m.vh, `${at}, list scrolled: title and close button stay visible below the head ` + JSON.stringify(m));
      await shot(`p2519-docpane-scrolled-${width}x${height}-${theme}.png`);
      console.log('measure', at, JSON.stringify(m), JSON.stringify(await ev(`(() => { const v = document.querySelector('#view'); return {vt: Math.round(v.getBoundingClientRect().top), vsh: v.scrollHeight, vch: v.clientHeight}; })()`)));
      // the close button works by a real click on its spot
      if (m && m.xOk) {
        await ev(`(() => { const x = document.querySelector('.dc-pane .dc-x'), r = x.getBoundingClientRect(); document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); return 1; })()`);
        check(await wait(`!document.querySelector('.dc-pane')`), `${at}, scrolled: the close button on its spot closes the pane`);
      }
      // the list scrolled to its very end with the pane open
      await ev(`(document.querySelector('.dc-view .dc-card [data-dco]').click(), 1)`);
      check(await wait(`!!document.querySelector('.dc-pane #dc-h')`), `${at}: the pane opens again`);
      await ev(SCROLL(1e6)); await sleep(300);
      m = await ev(MEASURE);
      check(m && m.hOk && m.xOk && m.pt >= m.head && m.pb <= m.vh, `${at}, list at its end: title and close button visible ` + JSON.stringify(m));
    }
    // bob, a short list: open, scroll as far as it goes, the pane stays below the head (before 2.519.0 it went under it)
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'bob', password: 'password123'})}).then(r => r.status)`);
    for (const [width, height] of [[1280, 800], [1024, 700]]) {
      const at = `bob ${width}x${height}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
      await nav(B + '#docs');
      check(await wait(`document.querySelectorAll('.dc-card').length === 3`), `${at}: three cards`);
      await ev(`(document.querySelector('.dc-view .dc-card [data-dco]').click(), 1)`);
      check(await wait(`!!document.querySelector('.dc-pane #dc-h')`), `${at}: the pane opens`);
      await sleep(300);
      await ev(SCROLL(150)); await sleep(200);
      let m = await ev(MEASURE);
      check(m && m.hOk && m.xOk && m.pt >= m.head && m.pb <= m.vh, `${at}, scrolled 150 px: title and close button visible ` + JSON.stringify(m));
      await ev(SCROLL(1e6)); await sleep(200);
      m = await ev(MEASURE);
      check(m && m.hOk && m.xOk && m.pt >= m.head && m.pb <= m.vh, `${at}, scrolled to the end: title and close button visible ` + JSON.stringify(m));
      console.log('measure', at, JSON.stringify(m));
      await shot(`p2519-docpane-short-${width}.png`);
    }
  }, false);

  console.log(`p2519_a_docpane_sticky_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
