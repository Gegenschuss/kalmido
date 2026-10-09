// 2.34.0 UI tests (agent D), own container (start.sh, KALMIDO_NOTIF_TEMPLATE=read). jsdom:
// #368 / #260 "New project from briefing": the file picker takes PDFs; a PDF's text lands in the briefing field (server reads
//      it, POST /api/pdf-text), a scanned PDF shows the hint instead
// #1089 the template card "Custom selection" has its own key (German "Eigene", the date range stays "Zeitraum"); a member
//      sees who limited the notifications also in the list settings
// #1090 the permission badge carries a short label (data-short) for narrow phones, the full text stays
// Firefox 390 x 844 touch (German, like the iPhone): the usage ring's box is >= 44 px, the badge shows the short label and
//      fits; the chat's search field hides the tab bar while it has the focus (#1091); a swipe beside a short message's
//      bubble starts a reply (#1091); screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const fs = require('fs');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2340_d_ui', check, shots: 'P2340D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_NOTIF_TEMPLATE: 'read'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';
const I18N = path.join(__dirname, '..', 'static', 'i18n');

function makePdf(pages) {  // a minimal PDF ('' = a page without a text layer, like a scan)
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${3 + 2 * i} 0 R`).join(' ')}] /Count ${pages.length} >>`];
  const font = 3 + 2 * pages.length;
  pages.forEach((t, i) => {
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${font} 0 R >> >> /Contents ${4 + 2 * i} 0 R >>`);
    const st = t ? `BT /F1 12 Tf 72 720 Td (${t}) Tj ET` : '0 0 1 rg 10 10 100 100 re f';
    objs.push(`<< /Length ${st.length} >>\nstream\n${st}\nendstream`);
  });
  objs.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return Buffer.from(out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`, 'latin1');
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();

  // ================= #1089 the template card's own key; the member's hint in the list settings
  const de = fs.readFileSync(path.join(I18N, 'de.json'), 'utf8');
  check(/^ {2}"Custom selection": "Eigene",?$/m.test(de) && /^ {2}"Custom": "Zeitraum",?$/m.test(de), '#1089: German "Eigene" for the card, "Zeitraum" stays for the date range');
  check(['es', 'fr', 'it', 'nl'].every(lg => /^ {2}"Custom selection": "[^"]+",?$/m.test(fs.readFileSync(path.join(I18N, lg + '.json'), 'utf8'))), '#1089: all languages have the key');
  const tpl = await call('PUT', `/api/lists/${L}/notify-template`, {tpl: 'read'});
  check(tpl.status === 200, '#1089: setup: the owner limits the members to Read only ' + tpl.status);
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(w.eval(`tr(NTF_TPLS[3][1])`) === 'Custom selection' && w.eval(`NTF_TPLS[3][0]`) === 'custom', '#1089: the fourth card is "Custom selection"');
  w.eval(`listModal(${L})`); await sleep(400);
  check(d.querySelector('.lmodal') && !d.querySelector('.lmodal .ntfhint'), '#1089: the owner sees no member hint in the list settings');
  d.querySelectorAll('.modal, .mwrap').forEach(m => m.remove());

  // ================= #1090 the badge's short label (jsdom: the markup)
  const b1 = w.eval(`chatModeHtml({permission_mode: '', may_set_mode: true, host: {host_permission_mode: 'auto'}})`);
  check(/data-short="Auto"/.test(b1) && /<span class="pmlong">Host default \(Auto\)<\/span>/.test(b1) && /aria-label="Permissions: Host default \(Auto\)"/.test(b1),
    '#1090: host default (Auto): short "Auto", the full text inside and in the label ' + b1);
  const b2 = w.eval(`chatModeHtml({permission_mode: 'ask', may_set_mode: true, host: {permission_mode: 'auto'}})`);
  check(/data-short="Auto"/.test(b2) && /Ask first · runs: Auto/.test(b2), '#1090: wish and real mode differ: short = what it runs with ' + b2);
  const b3 = w.eval(`chatModeHtml({permission_mode: '', may_set_mode: true, host: {}})`);
  check(/data-short="Default"/.test(b3), '#1090: nothing known: short "Default" ' + b3);

  // ================= #368 / #260 the briefing field takes a PDF
  w.eval(`S.proposers = [{id: ${AG}, name: 'Claude'}]`);
  w.eval(`propRequest('project')`); await sleep(200);
  const inp = d.querySelector('#pp-file');
  check(inp && /\.pdf/.test(inp.getAttribute('accept')) && /application\/pdf/.test(inp.getAttribute('accept')) && /\.pdf/.test(inp.closest('label').textContent),
    '#368: the picker takes PDFs ' + inp?.getAttribute('accept'));
  const pick = async (name, buf, type) => {
    const f = new w.File([buf], name, {type});
    Object.defineProperty(inp, 'files', {configurable: true, value: [f]});
    inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  };
  await pick('brief.pdf', makePdf(['Kickoff for the new shop', 'Launch in March']), 'application/pdf');
  await until(() => d.querySelector('#pp-text')?.value);
  const txt = d.querySelector('#pp-text')?.value || '';
  check(/Kickoff for the new shop/.test(txt) && /Launch in March/.test(txt) && d.querySelector('#pp-fname').textContent === 'brief.pdf' && d.querySelector('#pp-err').hidden,
    '#368: the PDF text lands in the briefing field ' + JSON.stringify(txt.slice(0, 80)));
  d.querySelector('#pp-text').value = '';
  await pick('scan.pdf', makePdf(['', '']), 'application/pdf');
  await until(() => !d.querySelector('#pp-err').hidden);
  check(!d.querySelector('#pp-err').hidden && /OCR/.test(d.querySelector('#pp-err').textContent) && !d.querySelector('#pp-text').value, '#368: a scan: the hint, the field stays empty ' + d.querySelector('#pp-err').textContent);
  await pick('photo.jpg', Buffer.from('xx'), 'image/jpeg');
  check(/Only text files \(\.txt, \.md\) or PDF/.test(d.querySelector('#pp-err').textContent), '#368: other files are refused ' + d.querySelector('#pp-err').textContent);
  w.close();

  // ================= the member: the hint in the list settings (#1089)
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(400);
  const h = d.querySelector('.lmodal .ntfhint');
  check(h && /Alice has limited the notifications for this list: Read only/.test(h.textContent), '#1089: the member sees who limited it in the list settings ' + (h?.textContent || ''));
  w.close();

  // ================= Firefox 390 touch, German
  await call('PATCH', '/api/settings', {lang: 'de'});
  const wk = Math.floor(Date.now() / 1000) + 3 * 86400, fh = Math.floor(Date.now() / 1000) + 3600;
  await v1('PUT', '/agent/quota', {rate_limits: {five_hour: {used_percentage: 23.5, resets_at: fh}, seven_day: {used_percentage: 41, resets_at: wk}}});
  await v1('PUT', '/agent/status', {status: 'idle', model: 'Opus 5.5', host_permission_mode: 'auto'});
  await v1('POST', `/agent/chats/${ME.id}`, {body: 'Moin, wie kann ich helfen? Ich lese gern das Briefing.'});
  const short = await v1('POST', `/agent/chats/${ME.id}`, {body: 'Ok'});
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1200);
    // #1090: the ring's box, the badge
    const g = await ev(`(() => { const r = document.querySelector('.chnm .chring'), m = document.querySelector('.chnm .chmode'), hd = document.querySelector('.chath'), sv = r?.querySelector('svg'); if (!r || !m) return {r: !!r, m: !!m};
      const a = r.getBoundingClientRect(), s = sv.getBoundingClientRect(), mb = m.getBoundingClientRect(), bf = getComputedStyle(m, '::before').content;
      return {w: a.width, h: a.height, sv: s.width, lineH: document.querySelector('.chnm').getBoundingClientRect().height, long: getComputedStyle(m.querySelector('.pmlong')).display,
        before: bf, fits: m.scrollWidth <= m.clientWidth + 1, mw: mb.width, mright: mb.right, hdr: hd.scrollWidth <= hd.clientWidth + 1, page: document.documentElement.scrollWidth <= 390,
        label: m.getAttribute('aria-label')}; })()`);
    check(g && g.w >= 44 && g.h >= 44 && g.sv <= 20, `${tag}: #1090 the ring's tap box >= 44 px, the ring itself stays small ` + JSON.stringify(g));
    check(g && g.long === 'none' && /Auto/.test(g.before || '') && g.fits && g.mright <= 390 && g.page, `${tag}: #1090 the badge shows "Auto" and fits ` + JSON.stringify(g));
    check(g && /Rechte: Standard des Hosts \(Auto\)/.test(g.label || ''), `${tag}: #1090 the full text stays in the label ` + JSON.stringify(g?.label));
    await shot('p2340d-390-chathead.png');
    // #1091: the search field hides the tab bar while it has the focus
    const t0 = await ev(`getComputedStyle(document.querySelector('#tabs')).display`);
    await ev(`(() => { document.querySelector('[data-act="ms-toggle"]').click(); return 1; })()`); await sleep(500);
    const t1 = await ev(`({f: document.activeElement?.id, cls: document.body.classList.contains('ms-typing'), tabs: getComputedStyle(document.querySelector('#tabs')).display})`);
    check(t0 !== 'none' && t1.f === 'ms-q' && t1.cls && t1.tabs === 'none', `${tag}: #1091 the search field has the focus, the tab bar steps aside ` + JSON.stringify({t0, t1}));
    await shot('p2340d-390-search.png');
    await ev(`(() => { document.querySelector('[data-act="ms-close"]').click(); document.activeElement?.blur?.(); return 1; })()`); await sleep(500);
    const t2 = await ev(`({cls: document.body.classList.contains('ms-typing'), tabs: getComputedStyle(document.querySelector('#tabs')).display})`);
    check(!t2.cls && t2.tabs !== 'none', `${tag}: #1091 search closed: the tab bar is back ` + JSON.stringify(t2));
    // #1091: a swipe beside the short message's bubble starts a reply
    const sw = await ev(`(async () => {
      const m = document.querySelector('#chat-msgs .cmsg[data-mid="a:${short.id}"]'), box = document.querySelector('#chat-msgs'); if (!m) return {m: false};
      m.scrollIntoView({block: 'center'}); await new Promise(r => setTimeout(r, 200));
      const r = m.getBoundingClientRect(), y = r.top + r.height / 2, x0 = Math.max(r.right + 40, 200);
      const hit = document.elementFromPoint(x0, y);
      const T = (x) => new Touch({identifier: 7, target: hit, clientX: x, clientY: y});
      const fire = (type, x) => { const t = T(x); hit.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
      fire('touchstart', x0);
      for (let i = 1; i <= 8; i++) { fire('touchmove', x0 + i * 12); await new Promise(r => setTimeout(r, 16)); }
      fire('touchend', x0 + 96);
      await new Promise(r => setTimeout(r, 400));
      const bar = document.querySelector('.rbar:not(.hidden)');
      return {m: true, beside: !m.contains(hit), x0, right: r.right, bar: bar ? bar.textContent.trim() : ''}; })()`);
    check(sw && sw.m && sw.beside && /Ok/.test(sw.bar), `${tag}: #1091 a swipe beside the bubble answers that message ` + JSON.stringify(sw));
  }, true);
  await call('PATCH', '/api/settings', {lang: 'en'});
  console.log(`p2340_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
