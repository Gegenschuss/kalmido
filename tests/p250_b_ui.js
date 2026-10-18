// 2.50.0 UI tests, part B (office: sales pipeline #1196, business figures #1197), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented companies, people and figures only.
// - #1196: the admin has the tab "Pipeline": the sums on top (open, weighted, the months with the next one marked), four
//   columns with the deals; a new inquiry through the dialog lands in "Inquiry"; dragging a card into another column changes
//   its stage (saved); a declined quotation shows on the card; on a phone one stage at a time with the switcher, nothing
//   sticks out to the side, large tap targets
// - #1197: the tab "Figures": tiles (revenue, open / overdue invoices, pipeline, cash flow), twelve months, the client with
//   budget and margin; a tap on "Open invoices" opens the invoice list; on a phone nothing sticks out
// - a member sees neither tab
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p250_b_ui', check, shots: 'P250B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const today = TC.today();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', budget_h: 20});
  const d1 = await call(CA, 'POST', '/api/office/deals', {title: 'Imagefilm', client_id: cl.id, value: 10000});
  const d2 = await call(CA, 'POST', '/api/office/deals', {title: 'Werbespot', contact: 'Frau Beispiel', value: 4000, stage: 'offer'});
  check(d1.http === 201 && d2.http === 201, 'two deals ' + d1.http + d2.http);
  const qo = await call(CA, 'POST', `/api/office/deals/${d2.id}/offer`);
  for (const st of ['sent', 'declined']) await call(CA, 'POST', `/api/office/docs/${qo.doc_id}/status`, {status: st});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg') && !e.closest('.sr')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const deals = `fetch('/api/office/deals', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= #1196
    await nav(B + '#office/pipeline');
    check(await ready(ev, `document.querySelectorAll('.pipcols .pipcol').length === 4`, 80), '#1196: the pipeline with four columns');
    check(await ev(`!!document.querySelector('.ofmenu [data-go="office/pipeline"]') && !!document.querySelector('.ofmenu [data-go="office/kpi"]')`), '#1196 #1197: both tabs for the admin');  // 2.87.9 (#1917): the office menu
    check(await ev(`/14,000\\.00/.test(document.querySelector('.pptiles').textContent) && /4,000\\.00/.test(document.querySelector('.pptiles').textContent)`),
      '#1196: open sum and weighted sum on top ' + await ev(`document.querySelector('.pptiles')?.textContent`));
    check(await ev(`document.querySelectorAll('.ppfcl li').length === 6 && document.querySelectorAll('.ppfcl li.next').length === 1`), '#1196: the months ahead with the next one marked');
    check(await ev(`document.querySelectorAll('[data-pipcol="inquiry"] .ppcard').length === 1 && document.querySelectorAll('[data-pipcol="offer"] .ppcard').length === 1`), '#1196: the cards in their columns');
    check(await ev(`document.querySelector('[data-pipcol="offer"] .ppcard').classList.contains('warn') && /declined/.test(document.querySelector('[data-pipcol="offer"] .ppcard').textContent)`), '#1196: a declined quotation shows on the card');
    // new inquiry through the dialog
    await ev(`(() => { document.querySelector('[data-pp="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #pp-title')`), '#1196: the deal dialog');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#pp-title').value = 'Messefilm'; m.querySelector('#pp-value').value = '2500'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && [...document.querySelectorAll('[data-pipcol="inquiry"] .ppcard')].some(c => /Messefilm/.test(c.textContent))`), '#1196: the new inquiry is in its column');
    check(await ev(`${deals}.then(j => j.items.some(x => x.title === 'Messefilm' && x.stage === 'inquiry' && x.probability === 20))`), '#1196: saved as an inquiry with 20 %');
    // 2.50.1: open + save keeps a value >= 1,000 (the field shows "2,500.00"; ofcNum read it as 2.5)
    check(await ev(`ofcNum(fmtNum(2500, 2)) === 2500 && ofcNum('2,500.00') === 2500 && ofcNum('1.5') === 1.5`), '2.50.1: ofcNum reads the thousands separator');
    await ev(`(() => { [...document.querySelectorAll('.ppcard')].find(x => /Messefilm/.test(x.textContent)).click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('.modal #pp-value')?.value === '2,500'`), '2.50.1: the dialog shows the value with its separator');
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && ${deals}.then(j => j.items.some(x => x.title === 'Messefilm' && +x.value === 2500))`), '2.50.1: open + save keeps 2,500');
    // drag a card into "Order"
    await ev(`(() => { const c = [...document.querySelectorAll('.ppcard')].find(x => /Imagefilm/.test(x.textContent)), col = document.querySelector('[data-pipcol="won"]'); const dt = new DataTransfer();
      c.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: dt})); col.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: dt})); col.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt})); return 1; })()`);
    check(await ready(ev, `${deals}.then(j => j.items.some(x => x.title === 'Imagefilm' && x.stage === 'won' && x.probability === 100))`), '#1196: dragging into "Order" saves the stage');
    check(await ready(ev, `[...document.querySelectorAll('[data-pipcol="won"] .ppcard')].some(c => /Imagefilm/.test(c.textContent))`), '#1196: the card moved');
    // the won deal offers "Create project"
    await ev(`(() => { [...document.querySelectorAll('.ppcard')].find(x => /Imagefilm/.test(x.textContent)).click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-m="project"]') && !!document.querySelector('.modal [data-m="offer"]')`), '#1196: the won deal offers a quotation and a project');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await shot('p250-b-pipeline.png');
    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(`getComputedStyle(document.querySelector('.ppseg')).display !== 'none' && [...document.querySelectorAll('.pipcol')].filter(c => getComputedStyle(c).display !== 'none').length === 1`), '#1196: on a phone one stage with the switcher');
    await ev(`(() => { document.querySelector('[data-pp="stage"][data-v="won"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.pipcol')].find(c => getComputedStyle(c).display !== 'none')?.dataset.pipcol === 'won'`), '#1196: the switcher shows another stage');
    check(await ev(noSide), '#1196: on a phone nothing sticks out to the side');
    check(await ev(`[...document.querySelectorAll('.pipcol.on .ppcard')].every(x => x.getBoundingClientRect().height >= 43)`), '#1196: large tap targets');
    await shot('p250-b-pipeline-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= #1197
    await nav(B + '#office/kpi');
    check(await ready(ev, `document.querySelectorAll('.kptiles .kptile').length === 6`, 80), '#1197: the figures with six tiles');
    check(await ev(`document.querySelectorAll('.kpbars .kpm').length === 12 && document.querySelectorAll('.kpbars .kpm.cur').length === 1 && document.querySelectorAll('table.sr tbody tr').length === 12`), '#1197: twelve months, this one marked, a table for screen readers');
    check(await ev(`/Kunde Eins GmbH/.test(document.querySelector('.kpcl')?.textContent || '') && /of 20/.test(document.querySelector('.kpcl').textContent)`), '#1197: the client with hours against the budget');
    check(await ev(`/2,500\\.00/.test([...document.querySelectorAll('.kptile')].find(t => /Pipeline/.test(t.textContent))?.textContent || '')`), '#1197: the weighted pipeline (the won deal not in it)');
    await shot('p250-b-kpi.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#1197: on a phone nothing sticks out to the side');
    await shot('p250-b-kpi-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('[data-kp="go"][data-go="open"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/offers' && document.querySelector('.ofdkinds [aria-selected="true"]')?.dataset.kind === 'invoice'`, 60), '#1197: a tap on open invoices opens the invoice list');
    // the start page block "Figures" (admins of the office)
    await nav(B + '#home');
    check(await ready(ev, `!!document.querySelector('.dc-kpi a[href="#office/kpi"]')`, 60), '#1197: the start page shows the block "Figures" for the admin');
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#home');
    await ready(ev, `!!document.querySelector('.dash')`, 60); await sleep(1500);
    check(await ev(`!document.querySelector('.dc-kpi')`), '#1197: no block "Figures" for a member');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('.ofmenu [data-go="office/offers"]') && !!OFC.info`, 80), 'the office (member)');  // 2.87.9 (#1917): the office menu (the role known)
    check(await ev(`!document.querySelector('.ofmenu [data-go="office/pipeline"]') && !document.querySelector('.ofmenu [data-go="office/kpi"]')`), '#1196 #1197: a member sees neither tab');
  }, false);

  console.log(`p250_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
