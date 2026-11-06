// kalmido-suite:
// 2.580.0 A (#4815) UI test, own container (start.sh), Firefox with real layout. Invented data only.
// Pages with their own widths now stand on one of the four widths (--w-lesen 46rem / --w-form 40rem / --w-seite 96rem / --w-voll),
// in the middle. Measured in the content area (#view without padding and scroll bar):
// - 1920 px: Documents (tiles) are wider than 68.75rem = --w-seite wide, more than 5 tile columns, head and first tile on one edge
// - the calendar agenda has its own class .agendav (not the agents page's .agview) and stands at --w-seite
// - the overview of tables (.shvwrap.shvov) = --w-seite, in the middle; at 3840 px limited
// - Completed (.hview) = --w-seite; the news page (.nwview) = --w-lesen; the team chat channel list is limited to --w-seite
// - 1440 x 900 and 390 px: the pages fill the content area, no sideways overflow
// freelancer-matrix: Breiten (alice has no organisation; the widths do not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2580_a_breite_ui', check, shots: 'P2580A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
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
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['office', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,docs,sheets,collab'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');
  await upload('insurance.pdf', ['Versicherung Beispiel AG', 'Police Haftpflicht']);
  await upload('power.pdf', ['Stadtwerke Musterstadt', 'Abschlag Strom']);
  await call('POST', '/api/sheets', {title: 'Shot list', space: 'private'});
  await call('POST', '/api/events', {title: 'Standup', start: '2026-11-10T09:00', end: '2026-11-10T09:15'});
  const t = await call('POST', '/api/tasks', {title: 'Write the brief', due: '2026-11-10'});
  await call('PATCH', `/api/tasks/${t.id}`, {status: 'done'});

  await firefox(async ({cmd, ev, ctx, nav, shot, until: wait}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    // box of the content area and of one element (px); rem = root font size
    const MEASURE = sel => `(() => { const v = document.querySelector('#view'), e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
      const cs = getComputedStyle(v), vr = v.getBoundingClientRect(), l = vr.left + parseFloat(cs.paddingLeft), r = vr.left + v.clientWidth - parseFloat(cs.paddingRight), b = e.getBoundingClientRect();
      return {l: b.left - l, r: r - b.right, w: b.width, area: r - l, rem: parseFloat(getComputedStyle(document.documentElement).fontSize), over: v.scrollWidth - v.clientWidth}; })()`;
    // [name, hash, selector, kind: seite (limit 96rem) | lesen (46rem)]
    const PAGES = [
      ['documents', '#docs', '#view .dc-wrap', 'seite'],
      ['tables', '#sheets', '#view .shvwrap.shvov', 'seite'],
      ['completed', '#done', '#view .hview', 'seite'],
      ['news', '#news', '#view .nwview', 'lesen'],
    ];
    for (const [vw, vh] of [[390, 844], [1440, 900], [1920, 1080], [3840, 1600]]) {
      await cmdViewport(cmd, ctx, vw, vh);
      for (const [name, hash, sel, kind] of PAGES) {
        await nav(B + '?w=' + vw + hash);
        const m = await wait(`!!S.booted && !!document.querySelector(${JSON.stringify(sel)}) && (${MEASURE(sel)})`);
        if (!m) { check(false, `${vw}px ${name}: ${sel} shows`); continue; }
        const lim = Math.min(m.area, (kind === 'seite' ? 96 : 46) * m.rem);
        check(Math.abs(m.w - lim) <= 2, `${vw}px ${name}: width ${kind} = ${Math.round(lim)} px ` + JSON.stringify(m));
        check(Math.abs(m.l - m.r) <= 2, `${vw}px ${name}: in the middle ` + JSON.stringify(m));
        check(m.over <= 1, `${vw}px ${name}: no sideways overflow ` + JSON.stringify(m));
        if (vw === 3840 && kind === 'seite') check(m.area - m.w > 2, `${vw}px ${name}: limited (narrower than the content area) ` + JSON.stringify(m));
        if (name === 'documents' && vw >= 1440) {
          const g = await wait(`(() => { const v = document.querySelector('#view .dc-view'), bar = document.querySelector('#view .dc-bar'), c = document.querySelector('#view .dc-grid .dc-card'), gr = document.querySelector('#view .dc-grid');
            if (!v || !bar || !c || !gr) return null; const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
            return {viewW: v.getBoundingClientRect().width, rem, cols: getComputedStyle(gr).gridTemplateColumns.split(' ').length, barL: bar.getBoundingClientRect().left, cardL: c.getBoundingClientRect().left}; })()`);
          if (!g) check(false, `${vw}px documents: tiles show`);
          else {
            if (vw >= 1920) check(g.viewW > 68.75 * g.rem + 2 && g.cols > 5, `${vw}px documents: wider than 68.75rem, more than 5 tile columns ` + JSON.stringify(g));
            check(Math.abs(g.barL - g.cardL) <= 2, `${vw}px documents: head and first tile on one edge ` + JSON.stringify(g));
          }
        }
        if (vw >= 1920) for (const theme of ['light', 'dark']) {
          await ev(`(() => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))); })()`);
          await shot(`p2580a-${name}-${vw}-${theme}.png`);
        }
      }
      // the calendar agenda: own class, no borrowed .agview, at --w-seite
      await nav(B + '?w=' + vw + '#cal');
      await wait(`!!S.booted && !!document.querySelector('#view .calbar')`);
      await ev(`(() => { S.calMode = 'agenda'; S.calSel = '2026-11-10'; renderView(); return 1; })()`);
      const ag = await wait(`(${MEASURE('#view .agenda')})`);
      if (!ag) check(false, `${vw}px agenda shows`);
      else {
        check(await ev(`!!document.querySelector('#view .agenda.agendav') && !document.querySelector('#view .agenda.agview')`), `${vw}px agenda: its own class .agendav, not .agview`);
        check(Math.abs(ag.w - Math.min(ag.area, 96 * ag.rem)) <= 2 && Math.abs(ag.l - ag.r) <= 2, `${vw}px agenda: --w-seite in the middle ` + JSON.stringify(ag));
      }
      // the team chat's channel list on its own page (a phone shows it without a room)
      if (vw === 390) {
        await nav(B + '?w=' + vw + '#team');
        const tv = await wait(`(${MEASURE('#view .tcview')})`);
        if (tv) check(tv.w <= 96 * tv.rem + 1 && tv.over <= 1, `${vw}px team chat: the channel list fits ` + JSON.stringify(tv));
      }
    }
  }, false);
  console.log(`p2580_a_breite_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
async function cmdViewport(cmd, ctx, width, height) { await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}}); }
