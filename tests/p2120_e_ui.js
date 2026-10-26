// 2.120.0 UI tests, part E (#2091 own letterhead PDF), own container (start.sh, mode workspaces), Firefox (desktop + phone
// width). Invented companies only; the letterhead PDF is made here.
// - the office settings have the section "Letterhead": empty state, upload (the same request the button sends), the file
//   with its pages, margins of page 1 / following pages and the two switches appear
// - every change is saved at once (no save button of its own) and is one step of the undo history (toast, redo); Enter
//   never submits the settings form
// - the preview opens the PDF viewer; removing has its undo
// - on a phone the section stays inside the screen; a member sees the state without the buttons, the fields locked
// - a person without organisation: the same in the personal office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2120_e_ui', check, shots: 'P2120E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2120E_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

// a one page A4 PDF (no compression) with correct offsets, built in the page
// 2.296.0 (#3177): a Type 3 font (glyphs in the file); a named Helvetica without its program is refused (PDF/A)
const MKPDF = `(() => { const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [4 0 R] /Count 1 >>', '<< /Type /Font /Subtype /Type3 /FontBBox [0 0 600 700] /FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << >> /Encoding << /Type /Encoding /Differences [] >> /FirstChar 32 /LastChar 32 /Widths [600] >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>'];
  const c = 'BT /F1 16 Tf 40 800 Td (UI-LETTERHEAD) Tj ET'; objs.push('<< /Length ' + c.length + ' >>\\nstream\\n' + c + '\\nendstream');
  let out = '%PDF-1.4\\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += (i + 1) + ' 0 obj\\n' + o + '\\nendobj\\n'; });
  const x = out.length; out += 'xref\\n0 ' + (objs.length + 1) + '\\n0000000000 65535 f \\n' + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \\n').join('');
  out += 'trailer\\n<< /Size ' + (objs.length + 1) + ' /Root 1 0 R >>\\nstartxref\\n' + x + '\\n%%EOF\\n'; return out; })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com', orgs: []});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'en', company_fields: {name: 'Beispiel Studio GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const state = `fetch('/api/office/letterhead', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.letterhead)`;
  // an upload from the page (a file chooser cannot be driven): the same function the button's file input calls
  const upload = `(() => { bp_upload(new File([${MKPDF}], 'Briefbogen.pdf', {type: 'application/pdf'})); return 1; })()`;
  const openSettings = async (ev, nav) => {
    await nav(B + '#office/settings');
    return ready(ev, `!!document.querySelector('#ofc-set #bpset') && !/Loading/.test(document.querySelector('#bpset').textContent)`, 80);
  };
  const setVal = (id, v) => `(() => { const e = document.getElementById('${id}'); e.value = '${v}'; e.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const undoToast = `(() => { const b = document.querySelector('#toast:not(.hidden) button:not(.tx)'); if (!b) return 0; b.click(); return 1; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    check(await openSettings(ev, nav), 'the settings show the letterhead section');
    check(await ev(`/No letterhead yet/.test(document.querySelector('#bpset').textContent) && !!document.querySelector('#bpset [data-bp-act="pick"]') && !document.querySelector('#bpset [data-bp="m1"]')`),
      'empty state: upload button, no margins yet');
    check(await ev(`!!document.querySelector('#bpset[data-fg-skip]')`), 'the section is outside the form guard (saved at once)');
    await ev(upload);
    check(await ready(ev, `document.querySelectorAll('#bpset [data-bp]').length === 8`), 'after the upload: eight margin fields');
    check(await ev(`/Briefbogen\\.pdf/.test(document.querySelector('#bpset').textContent) && /one page for all pages/.test(document.querySelector('#bpset').textContent)`),
      'the file name and its pages');
    check(await ev(`document.getElementById('bp-hide-head').checked && document.getElementById('bp-hide-foot').checked`), 'both switches on by default');
    check((await ev(state)).on === true, 'the letterhead is stored');
    await ev(`(() => { document.getElementById('bpset').scrollIntoView({block: 'start'}); return 1; })()`);
    await shot('letterhead-desktop');
    // a margin: saved at once, undo in the toast
    await ev(setVal('bp-m1-left', '30'));
    let st = null; for (let i = 0; i < 40 && !(st && st.m1[3] === 30); i++) { st = await ev(state); await sleep(250); }
    check(st && st.m1[3] === 30, 'margin saved at once ' + JSON.stringify(st && st.m1));
    check(await ready(ev, undoToast, 20), 'the toast offers the undo');
    st = null; for (let i = 0; i < 40 && !(st && st.m1[3] === 25); i++) { st = await ev(state); await sleep(250); }
    check(st && st.m1[3] === 25, 'undo restores the margin');
    await ev(`(() => { histStep('redo'); return 1; })()`);
    st = null; for (let i = 0; i < 40 && !(st && st.m1[3] === 30); i++) { st = await ev(state); await sleep(250); }
    check(st && st.m1[3] === 30, 'redo sets the margin again');
    await ready(ev, `document.getElementById('bp-m1-left')?.value === '30'`);
    await ev(setVal('bp-m1-left', '25'));
    st = null; for (let i = 0; i < 40 && !(st && st.m1[3] === 25); i++) { st = await ev(state); await sleep(250); }
    await ev(setVal('bp-m1-left', '150'));
    check(await ready(ev, `/at least/.test(document.getElementById('bp-err')?.textContent || '')`), 'an impossible margin shows the error at the section');
    check((await ev(state)).m1[3] === 25, 'the impossible margin is not saved');
    await ev(`(() => { document.getElementById('bp-hide-foot').click(); return 1; })()`);
    st = null; for (let i = 0; i < 40 && !(st && st.hide_footer === 0); i++) { st = await ev(state); await sleep(250); }
    check(st && st.hide_footer === 0, 'the footer switch saved at once');
    // Enter in a margin field never submits the settings form
    await ev(`(() => { window.__sub = 0; document.getElementById('ofc-set').addEventListener('submit', () => { window.__sub++; }, {once: true}); const e = document.getElementById('bp-m2-top'); e.focus(); e.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    await sleep(300);
    check(await ev(`window.__sub === 0`), 'Enter in a margin field does not submit the settings form');
    // preview
    await ev(`(() => { document.querySelector('#bpset [data-bp-act="preview"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lightbox.pview')`, 60), 'the preview opens the PDF viewer');
    await ev(`(() => { document.querySelector('.lightbox [data-pv="x"]')?.click(); document.querySelector('.lightbox')?.remove(); return 1; })()`);
    // remove + undo
    await ev(`(() => { document.querySelector('#bpset [data-bp-act="del"]').click(); return 1; })()`);
    check(await ready(ev, `/No letterhead yet/.test(document.querySelector('#bpset').textContent)`), 'removed');
    check(await ready(ev, undoToast, 20), 'the removal can be undone in the toast');
    check(await ready(ev, `document.querySelectorAll('#bpset [data-bp]').length === 8`), 'undo brings the letterhead back');
    check((await ev(state)).on === true, 'the letterhead is on again');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await openSettings(ev, nav);
    await ev(`(() => { document.getElementById('bpset').scrollIntoView(); return 1; })()`);
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#bpset *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`),
      'phone: the section stays inside the screen');
    // 2.298.0 A2 (#3186): the (i) of the letterhead rule (.ib) reaches 44 px through its ::after, like every (i)
    check(await ev(`[...document.querySelectorAll('#bpset button:not(.ib)')].every(b => b.getBoundingClientRect().height >= 28)`), 'phone: big enough buttons');
    await shot('letterhead-phone');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member: reads, no buttons, fields locked
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    check(await openSettings(ev, nav), 'a member sees the section');
    check(await ev(`!document.querySelector('#bpset [data-bp-act="pick"]') && !document.querySelector('#bpset [data-bp-act="del"]') && !!document.querySelector('#bpset [data-bp-act="preview"]')`),
      'a member: preview only, no upload / remove');
    check(await ev(`[...document.querySelectorAll('#bpset [data-bp]')].every(e => e.disabled || e.closest('fieldset:disabled'))`), 'a member: the margins are locked');
    // a person without organisation (personal office)
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    check(await openSettings(ev, nav), 'freelancer: the section in the personal office');
    check(await ev(`!!document.querySelector('#bpset [data-bp-act="pick"]') && /No letterhead yet/.test(document.querySelector('#bpset').textContent)`),
      'freelancer: own empty letterhead with the upload (own admin)');
    await ev(upload);
    check(await ready(ev, `document.querySelectorAll('#bpset [data-bp]').length === 8`), 'freelancer: upload');
  }, false);

  console.log(`p2120_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
