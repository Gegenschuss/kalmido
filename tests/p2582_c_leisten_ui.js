// 2.582.0 C UI tests (#4830 every grip up to the neighbours' minimum, #4827 backups under Server > Backup)
// kalmido-suite:
// own container (start.sh), jsdom + Firefox. Invented data only. P2582C_NOSTART=1 = the container runs.
// - #4830: the task panel has no fixed 48 rem limit any more: its grip goes as far as the list keeps LIST_MIN_PX; a stored
//   width above 48 rem stays; a double click = the standard width (at most 48 rem as before). Documents: the properties beside
//   the preview keep the preview only a small rest (12 rem), no longer 20 rem.
// - #4827: Backups, Off-site backup and Check storage stand under Settings > Server > Backup (no longer Organisation > Data),
//   for a server admin with and without an organisation; an organisation admin without server rights sees none of it; the old
//   jump 'odata' and the settings search lead a server admin there.
// freelancer-matrix: settings (sam is a server admin without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2582_c_leisten_ui', check, shots: 'P2582C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2582C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});
const secOn = md => md.querySelector('.snav .on')?.dataset.sec;
const subs = (md, sec) => [...md.querySelectorAll(`[data-pane="${sec}"] [data-admsub]`)].map(b => b.dataset.admsub).join();

function pdf(lines) {  // a one-page PDF, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c), st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [4 0 R] /Count 1 >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>', `<< /Length ${st.length} >>\nstream\n${st}\nendstream`];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments', 'docs']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'olga', display_name: 'Olga', password: 'password123', email: 'olga@example.com', orgs: [{id: ORG, role: 'admin'}]});
  await call('POST', '/api/users', {username: 'sam', display_name: 'Sam', password: 'password123', email: 'sam@example.com', is_admin: true});  // no organisation
  for (const u of ['alice', 'olga', 'sam']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, await login(u));
  const sam = (await call('GET', '/api/state', null, await login('sam'))).me;
  check(sam && sam.is_admin, 'sam: a server admin (created without an organisation)');
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Wide panel'})).id;

  // ================= #4830 jsdom: the numbers of the task panel
  let w = await boot({user: 'alice', hash: 'l/' + L, setup: x => width(x, 2560), ls: {'tasks.pw.det': '60'}}), d = w.document;
  check(w.eval(`panelRem('det')`) === 60, '#4830: a stored task panel width above the former 48 rem stays ' + w.eval(`panelRem('det')`));
  w.eval(`openDetail(${T})`);
  await until(() => d.querySelector('#app').classList.contains('detail-open'));
  w.eval(`localStorage.removeItem('tasks.pw.det'); fitLayout()`);
  const mx = w.eval(`panelMax('det')`);
  check(mx > 48 && mx <= (2560 - 420) / 16 + 0.01, '#4830: at 2560 px the grip of the task panel reaches past 48 rem, the list keeps 420 px ' + mx);
  w.eval(`panelSet('det', 999)`);
  const st = +w.__store['tasks.pw.det'];
  check(st > 48 && Math.abs(st - Math.round(mx * 4) / 4) < 0.01, '#4830: dragged to the end = stored up to the room, not 48 rem ' + st + ' / ' + mx);
  check(parseFloat(d.documentElement.style.getPropertyValue('--detW')) > 48, '#4830: the width in use above 48 rem ' + d.documentElement.style.getPropertyValue('--detW'));
  check(w.eval(`pw_std('det')`) <= 48, '#4830: the growing default stays at most 48 rem ' + w.eval(`pw_std('det')`));
  w.eval(`panelSet('det', null)`);
  check(!w.__store['tasks.pw.det'], '#4830: the standard width again (double click / Enter), nothing stored');
  const L1 = w.eval(`JSON.stringify(lay2209({W: 1440, bar: 0, barRail: 0, side: 240, det: 1280, detMin: 320, chat: 0, chatMin: 320, fold: false}))`), l1 = JSON.parse(L1);
  check(!l1.rail && l1.det >= 320 && 1440 - 240 - l1.det >= 319.5, '#4830: lay2209 with a stored 80 rem panel in 1440 px: the panel shrinks, the list keeps its room ' + L1);
  w.close();

  // ================= #4830 jsdom: the properties grip of the documents
  w = await boot({user: 'alice', hash: 'docs', media: {'(min-width:64rem)': true}}); d = w.document;
  check(await until(() => w.eval(`typeof dcr_gripMax === 'function'`)), 'documents: the module loaded');
  const gm = w.eval(`(() => { const wrap = document.createElement('div'), main = document.createElement('div'); wrap.className = 'dc-wrap'; main.className = 'dc-main'; wrap.appendChild(main); document.body.appendChild(wrap);
    Object.defineProperty(main, 'clientWidth', {value: 1200}); Object.defineProperty(wrap, 'clientWidth', {value: 2400}); const r = dcr_gripMax(DCR_GRIPS.props, 'props', wrap); wrap.remove(); return r; })()`);
  check(gm === 1200 - 13 * 16, '#4830: the properties may take all of the part but the preview rest (12 rem + the gap), not 20 rem: ' + gm);
  check(w.eval(`DCR_GRIPS.pane.keep === 18 && DCR_GRIPS.list.keep === 30`), '#4830: the other two grips keep the neighbours\' minimums (list 18 rem, pane 30 rem)');
  w.close();

  // ================= #4827 jsdom: Server > Backup
  // the server admin with an organisation
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('backup')`);
  let md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && subs(md, 'users') === 'signin,server,log,backup', '#4827: settingsModal(backup) opens Server, the sub-tabs ' + secOn(md) + ' ' + subs(md, 'users'));
  check(md.querySelector('#adms-backup')?.textContent.trim() === 'Backup', '#4827: the sub-tab is called "Backup"');
  let bp = md.querySelector('#admp-backup');
  check(bp && !bp.hidden && bp.querySelector('#s-bk-h') && bp.querySelector('#s-sto-h'), '#4827: Backup shows the backups and Check storage');
  check(await until(() => bp.querySelector('#s-bk #bk-on') && bp.querySelector('#s-bko-h')), '#4827: the backups and the off-site backup are drawn there');
  const od = md.querySelector('#admp-odata');
  check(od && !od.querySelector('#s-bk-h, #s-bk, #s-bko, #s-sto-h') && od.querySelector('#s-orgenc') && od.querySelector('#s-wsdata'), '#4827: Organisation > Data keeps only the organisation\'s data');
  check(md.querySelectorAll('#s-bk-h').length === 1, '#4827: the backups once in the dialog');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('odata')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && !md.querySelector('#admp-backup').hidden, '#4827: the old jump odata (a backup error\'s News item) opens Server > Backup for a server admin ' + secOn(md));
  // the settings search finds it at the new place
  const sq = md.querySelector('#s-search'); sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = 'Off-site backup'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
  const hit = await until(() => [...md.querySelectorAll('#s-sres [data-hit]')].find(b => /Off-site backup/.test(b.textContent)));
  check(hit && /Server/.test(hit.textContent), '#4827: the search names Server for the off-site backup ' + hit?.textContent);
  click(w, hit);
  check(await until(() => secOn(md) === 'users' && !md.querySelector('#admp-backup').hidden), '#4827: the hit opens Server > Backup');
  w.close();

  // the server admin without an organisation (self-hosting alone)
  w = await boot({user: 'sam'}); d = w.document;
  w.eval(`settingsModal('backup')`);
  md = await until(() => d.querySelector('.smodal'));
  bp = md.querySelector('#admp-backup');
  check(secOn(md) === 'users' && bp && !bp.hidden, '#4827: without an organisation: Server > Backup opens ' + secOn(md));
  check(await until(() => bp.querySelector('#s-bk #bk-on') && bp.querySelector('#s-sto-h')), '#4827: without an organisation: the backups are drawn');
  w.close();

  // the organisation's admin without server rights
  w = await boot({user: 'olga'}); d = w.document;
  w.eval(`settingsModal('backup')`);
  md = await until(() => d.querySelector('.smodal'));
  check(!md.querySelector('.snav [data-sec="users"]') && !md.querySelector('#admp-backup, #s-bk, #s-bk-h, #s-bko, #s-sto-h'), '#4827: an organisation admin sees no Server and no backups');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('odata')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'org' && md.querySelector('#admp-odata') && !md.querySelector('#admp-odata').hidden, '#4827: for an organisation admin odata stays Organisation > Data ' + secOn(md));
  w.close();

  // ================= Firefox: the real layout
  const fd = new FormData();
  fd.append('files', new Blob([pdf(['Versicherung Beispiel AG', 'Brief'])], {type: 'application/pdf'}), 'one.pdf');
  fd.append('ws', 'private');
  const DOC = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${DOC}`)).state), 150);
  await call('POST', `/api/docs/${DOC}/review`, {done: true});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { const x = await ev(js).catch(() => false); if (x) return x; await sleep(250); } return false; };
    const R = sel => `(() => { const e = document.querySelector('${sel}'); if (!e) return null; const r = e.getBoundingClientRect(); return {l: Math.round(r.left), r: Math.round(r.right), w: Math.round(r.width)}; })()`;
    // the task panel at 2560 px: End on its grip = as wide as the list allows
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2560, height: 1200}});
    await nav(B + '#l/' + L);
    check(await wait(`!!S.booted && !!document.querySelector('#view .trow')`), 'Firefox: the project shows');
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    check(await wait(`(() => { placeGrips(); const g = document.querySelector('#pgrip-det'); return !!g && !g.hidden; })()`), 'Firefox: the grip of the task panel');
    await ev(`(() => { const g = document.querySelector('#pgrip-det'); g.focus(); g.dispatchEvent(new KeyboardEvent('keydown', {key: 'End', bubbles: true, cancelable: true})); return 1; })()`);
    const wide = await wait(`(() => { const d = ${R('#detail')}, m = ${R('#main')}; return d && m && d.w > 48 * 16 + 4 ? {d, m, over: document.documentElement.scrollWidth - innerWidth} : null; })()`);
    check(wide && wide.d.w > 48 * 16 + 4 && wide.m.w >= 418 && wide.over <= 0, 'Firefox 2560: the task panel wider than 48 rem, the list keeps 420 px, no sideways scroll ' + JSON.stringify(wide));
    await shot('p2582c-task-wide.png');
    await ev(`(() => { document.querySelector('#pgrip-det').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`);
    const back = await wait(`(() => { const d = ${R('#detail')}; return d && d.w <= 48 * 16 + 2 && !localStorage.getItem('tasks.pw.det') ? d : null; })()`);
    check(back, 'Firefox 2560: double click = the standard width again (at most 48 rem) ' + JSON.stringify(await ev(R('#detail'))));
    // the documents' reading view at 2900 px: the properties grip up to the preview's small rest
    await ev(`(() => { localStorage.setItem('tasks.dc.read', 'true'); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2900, height: 1400}});
    await nav(B + 'static/icon.svg');  // a new page load (from #l/… only the hash would change)
    await nav(B + '#docs/' + DOC);
    check(await wait(`document.querySelectorAll('.dc-card').length === 1 && document.querySelector('.dc-pane .dc-body')?.dataset.id === '${DOC}'`, 80), 'Firefox 2900: the document opens in the pane ' + JSON.stringify(await ev(`({h: location.hash, cards: document.querySelectorAll('.dc-card').length, wrap: document.querySelector('.dc-wrap')?.className, pane: document.querySelector('.dc-pane .dc-body')?.dataset.id, read: localStorage.getItem('tasks.dc.read')})`).catch(() => null)));
    check(await wait(`(() => { const p = document.querySelector('.dc-wrap.dc-read .dc-main.dc-rd > .dc-props'), t = document.querySelector('.dc-main.dc-rd > .dc-top'); return p && t && p.getBoundingClientRect().left >= t.getBoundingClientRect().right - 2; })()`, 80), 'Firefox 2900: the properties beside the preview ' + JSON.stringify(await ev(`({wrap: document.querySelector('.dc-wrap')?.className, main: document.querySelector('.dc-pane .dc-main')?.className, top: ${R('.dc-pane .dc-top')}, props: ${R('.dc-pane .dc-props')}, pane: ${R('.dc-pane')}})`).catch(() => null)));
    await ev(`(() => { dcr_gripSet('props', 99999, true); return 1; })()`);
    const pr = await wait(`(() => { const t = ${R('.dc-main.dc-rd > .dc-top')}, p = ${R('.dc-main.dc-rd > .dc-props')}, m = ${R('.dc-pane .dc-main')}; return t && p && m && p.w > 400 ? {t, p, m} : null; })()`);
    check(pr && pr.t.w >= 12 * 16 - 2 && pr.t.w <= 14 * 16 && pr.p.w >= pr.m.w - 14 * 16, 'Firefox 2900: the properties dragged to the end, the preview keeps about 12 rem (no longer 20) ' + JSON.stringify(pr));
    check(pr && pr.p.r <= pr.m.r + 2 && pr.t.l >= pr.m.l - 2, 'Firefox 2900: nothing runs out of the part ' + JSON.stringify(pr));
    await shot('p2582c-docs-props.png');
  }, false);

  console.log(`p2582_c_leisten_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
