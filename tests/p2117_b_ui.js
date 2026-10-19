// 2.117.0 UI tests, part B (#2283 samples of the document templates, #2285 PDF files of a framework contract), own container
// (start.sh, mode workspaces), Firefox (desktop + phone width). Invented companies, people and figures only.
// - #2283: "Use sample" lists ten samples (legal ones marked); the new template dialog has "Start from a sample"; taking
//   over the cover letter makes an own template
// - #2285: the contracts list shows the paper clip; the contract's dialog lists its PDF (open = the PDF viewer, remove with
//   undo through the toast); a new contract keeps a chosen PDF until it is saved; on a phone the row stays inside the
//   screen with big targets; a member sees the files without the buttons to change them
// - a person without organisation: the same in the personal office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2117_b_ui', check, shots: 'P2117B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2117B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const PDF = '%PDF-1.4\\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\\ntrailer<</Root 1 0 R>>\\n%%EOF\\n';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com'});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'en', company_fields: {name: 'Beispiel Studio GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const ct = await call(CA, 'POST', '/api/office/contracts', {name: 'Rahmenvertrag Eins'});
  check(ct.http < 300, 'a framework contract ' + ct.http);
  const ctf = await call(CF, 'POST', '/api/office/contracts', {name: 'Rahmenvertrag privat'});
  check(ctf.http < 300, 'a framework contract of the freelancer ' + ctf.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = (m, u) => `fetch('${u}', {method: '${m}', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  // an upload from the page (a file chooser cannot be driven): the same request the dialog's button sends
  const upload = (cid, name) => `(() => { const fd = new FormData(); fd.append('file', new File(['${PDF}'], '${name}', {type: 'application/pdf'})); return fetch('/api/office/contracts/${cid}/files', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}, body: fd}).then(r => r.status); })()`;
  const noSide = `(() => { const m = document.querySelector('.modal'); const W = document.documentElement.clientWidth; return [...m.querySelectorAll('.dma-row *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const openContract = async (ev, nav, cid) => {
    await nav(B + '#office/contracts');
    await ready(ev, `!!document.querySelector('[data-ofc="open"][data-kind="contracts"][data-id="${cid}"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ofc="open"][data-kind="contracts"][data-id="${cid}"]').click(); return 1; })()`);
    return ready(ev, `!!document.querySelector('.modal #dma-box') && !/Loading/.test(document.querySelector('.modal #dma-box').textContent)`);
  };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= #2283 samples
    await nav(B + '#office/gendocs');
    check(await ready(ev, `!!document.querySelector('[data-dt="view"][data-v="templates"]')`, 80), '#2283: the documents tab');
    await ev(`(() => { document.querySelector('[data-dt="view"][data-v="templates"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-dt="tnew"]')`), '#2283: the templates view');
    await ev(`(() => { document.querySelector('[data-dt="tnew"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-m="starters"]')`), '#2283: the new template dialog offers "Start from a sample"');
    await ev(`(() => { document.querySelector('.modal [data-m="starters"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal .dtp-starters li').length === 10 && !document.querySelector('#dt-tbody')`), '#2283: ten samples instead of the empty dialog');
    check(await ev(`(() => { const li = [...document.querySelectorAll('.modal .dtp-starters li')]; const t = k => li.find(x => x.querySelector('[data-k="' + k + '"]'))?.textContent || ''; return /Legal text/.test(t('dunning')) && /Legal text/.test(t('authority')) && !/Legal text/.test(t('letter')); })()`),
      '#2283: legal samples are marked');
    await shot('p2117-b-samples.png');
    await ev(`(() => { document.querySelector('.modal [data-m="take"][data-k="letter"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && [...document.querySelectorAll('.dtp-list .ofcrow')].some(x => /Cover letter/.test(x.textContent))`), '#2283: the cover letter is an own template');
    // ================= #2285 the contract's PDF files
    check(await ev(upload(ct.id, 'Vertrag unterschrieben.pdf')) === 201, '#2285: upload');
    await nav(B + '#office/contracts');
    check(await ready(ev, `!!document.querySelector('[data-ofc="open"][data-id="${ct.id}"] .dma-clip')`, 80), '#2285: the paper clip in the list');
    check(await openContract(ev, nav, ct.id), '#2285: the dialog with its PDF row');
    check(await ev(`document.querySelectorAll('.modal .dma-f').length === 1 && /Vertrag unterschrieben\\.pdf/.test(document.querySelector('.modal .dma-f').textContent) && !!document.querySelector('.modal [data-dma="up"]') && !!document.querySelector('.modal [data-dma="replace"]')`),
      '#2285: the file with open / replace / remove and the upload button');
    await shot('p2117-b-contract.png');
    await ev(`(() => { document.querySelector('.modal [data-dma="view"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lightbox.pview')`), '#2285: open shows the PDF viewer');
    await ev(`(() => { document.querySelector('.lightbox.pview [data-pv="x"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.lightbox.pview')`);
    await ev(`(() => { document.querySelector('.modal [data-dma="rm"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal .dma-f') && !!document.querySelector('.modal .dma-none')`), '#2285: removed');
    check(await ready(ev, `!!document.querySelector('#toast button')`), '#2285: the toast offers undo');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal .dma-f').length === 1`), '#2285: undo brings the file back');
    // phone width: big targets, nothing sticks out
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#2285: on a phone the PDF row stays inside the screen');
    check(await ev(`[...document.querySelectorAll('.modal .dma-acts .iconbtn, .modal .dma-up')].every(b => b.getBoundingClientRect().height >= 40)`), '#2285: big targets on a phone');
    await ev(`(() => { document.querySelector('.modal #dma-box').scrollIntoView({block: 'center'}); return 1; })()`);
    await shot('p2117-b-contract-phone.png');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal')`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // a new contract: the chosen PDF goes up when it is saved
    await nav(B + '#office/contracts');
    await ready(ev, `!!document.querySelector('[data-ofc="new"][data-kind="contracts"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ofc="new"][data-kind="contracts"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #dma-box [data-dma="up"]')`), '#2285: a new contract offers the upload');
    await ev(`(() => { DMA.pending.push(new File(['${PDF}'], 'Nachtrag.pdf', {type: 'application/pdf'})); document.querySelector('.modal #dma-box').innerHTML = dmaListHtml([], null); document.querySelector('.modal #of-name').value = 'Rahmenvertrag Zwei'; return 1; })()`);
    check(await ev(`/is attached when you save/.test(document.querySelector('.modal #dma-box').textContent)`), '#2285: the chosen file waits for the save');
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    const two = async () => (await ev(api('GET', '/api/office/contracts'))).items?.find(x => x.name === 'Rahmenvertrag Zwei');
    let c2 = null; for (let i = 0; i < 40 && !(c2 && c2.files === 1); i++) { c2 = await two(); await sleep(250); }
    check(c2 && c2.files === 1, '#2285: saved with its PDF ' + JSON.stringify(c2));
    // ================= member: reads, no buttons
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    check(await openContract(ev, nav, ct.id), '#2285: a member opens the contract');
    check(await ev(`document.querySelectorAll('.modal .dma-f').length === 1 && !document.querySelector('.modal [data-dma="up"]') && !document.querySelector('.modal [data-dma="rm"]') && !document.querySelector('.modal [data-dma="replace"]')`),
      '#2285: a member sees the file, no upload / remove / replace');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    // ================= a person without organisation (personal office)
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    check(await ev(upload(ctf.id, 'privat.pdf')) === 201, 'freelancer: upload');
    check(await openContract(ev, nav, ctf.id), 'freelancer: the contract dialog');
    check(await ev(`document.querySelectorAll('.modal .dma-f').length === 1 && !!document.querySelector('.modal [data-dma="rm"]')`), 'freelancer: the file with its buttons (own admin)');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    const st = await ev(api('GET', '/api/office/doc-templates/starters'));
    check(st.starters?.length === 10, 'freelancer: the samples');
  }, false);

  console.log(`p2117_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
