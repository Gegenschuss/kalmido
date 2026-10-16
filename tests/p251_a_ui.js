// 2.51.0 UI tests, part A (agents in the office #1348 / #1350), own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, people and figures only.
// - the agent's dialog shows "May draft office documents" (off), the admin switches it on (saved at once)
// - the office settings have the privacy switch "Agents may read office data" with the hint about the AI model (saved)
// - a quotation draft of the agent: "Drafted by the agent ...", the marked positions (accent line + text: price changed / free /
//   discount 10 %), "Confirm" takes the mark away (saved)
// - the chat card of the draft: link buttons "Open in the office" (an app target) and "PDF preview"; only app targets
// - the invoice list shows "Suggested payments"; "Book" records the payment
// - the access log filters "Agents"; on a phone nothing sticks out to the side and the buttons are large enough
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p251_a_ui', check, shots: 'P251A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P251_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const agent = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1/office' + url, {method, headers: {...H, Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const today = new Date().toISOString().slice(0, 10);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'GET', '/api/office/settings');
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE',
    vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const s1 = await call(CA, 'POST', '/api/office/services', {name_de: 'Kamera', name_en: 'Camera', daily_rate: 800});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Musterfirma GmbH', address: 'Weg 2\n10115 Berlin'});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call(CA, 'POST', '/api/my/agents', {username: 'officebot', display_name: 'Office Bot', scopes: ['read', 'office'], org_id: org.id});
  check(ag.http === 201, 'an agent ' + ag.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg') && !e.closest('.sr')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#home');
    await ready(ev, `!!document.querySelector('.dash')`, 80);
    // ================= the agent's switch in its dialog
    await ev(`(() => { api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; agModal(j.agents.find(x => x.id === ${ag.id}), () => {}); }); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .oa_sw #oa-sw')`, 60), '#1348: the agent dialog has the office switch');
    check(await ev(`!document.querySelector('#oa-sw').checked && !document.querySelector('#oa-sw').disabled && /May draft office documents/.test(document.querySelector('.oa_sw').textContent)`),
      '#1348: off by default, the admin may switch it');
    await ev(`(() => { document.querySelector('#oa-sw').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/agents/${ag.id}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.office_drafts === true)`, 40), '#1348: switched on at once');
    check(await ev(`/Agents may read office data/.test(document.querySelector('.oa_sw').textContent)`), '#1348: the dialog points to the privacy switch while it is off');
    await shot('p251-a-agent-switch.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // ================= the privacy switch in the office settings
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-agents-read')`, 80), '#1348: the privacy switch in the office settings');
    check(await ev(`!document.querySelector('#os-agents-read').checked && /AI model/.test(document.querySelector('#os-agents-read').closest('form').textContent)`), '#1348: off, with the hint about the AI model');
    await ev(`(() => { document.querySelector('#os-agents-read').checked = true; document.querySelector('#ofc-set').requestSubmit(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/settings', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.settings.agents_read === 1)`, 40), '#1348: the privacy switch is saved');
    // ================= the agent's draft
    const q = await agent(ag.token, 'POST', '/offers', {client_id: cl.id, title: 'Imagefilm 2027', notify: true, items: [{service_id: s1.id, qty: 2}, {service_id: s1.id, qty: 1, price: 900},
      {text: 'Fahrtkosten', qty: 1, unit: 'flat', price: 120}, {service_id: s1.id, qty: 1, discount: 10}]});
    check(q.http === 201, 'the agent drafts a quotation ' + q.http);
    const qid = q.doc.id;
    await nav(B + `#office/offers/${qid}`);
    check(await ready(ev, `document.querySelectorAll('.ofdit.oa_flag').length === 3`, 80), '#1348: three marked positions ' + await ev(`document.querySelectorAll('.ofdit.oa_flag').length`));
    check(await ev(`(() => { const t = [...document.querySelectorAll('.oa_flagt')].map(x => x.textContent.trim()); return t.join('|'); })()`) === 'price changed|free|discount 10 %', '#1348: the marks say what is marked');
    check(await ev(`/Drafted by the agent Office Bot/.test(document.querySelector('.oa_by')?.textContent || '')`), '#1348: "Drafted by the agent" above the document');
    check(await ev(`getComputedStyle(document.querySelector('.ofdit.oa_flag')).boxShadow.includes('inset')`), '#1348: the accent line on a marked position');
    await shot('p251-a-draft.png');
    await ev(`(() => { document.querySelector('[data-oa="confirm"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/docs/${qid}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items.filter(i => i.agent_flag).length === 2)`, 40), '#1348: Confirm takes the mark away (saved)');
    check(await ready(ev, `document.querySelectorAll('.ofdit.oa_flag').length === 2`, 40), '#1348: ... and the editor shows it');
    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(500);
    check(await ev(noSide), '#1348: on a phone nothing of the draft sticks out to the side');
    check(await ev(`[...document.querySelectorAll('.oa_flags .btn')].every(b => b.getBoundingClientRect().height >= 34)`), '#1348: the Confirm buttons are large enough');
    await shot('p251-a-draft-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= the chat card
    await nav(B + '#home');
    await ready(ev, `!!document.querySelector('.dash')`, 80);
    await ev(`(() => { chatOpen(${ag.id}, {float: false}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.oa_links a[href="#office/offers/${qid}"]')`, 80), '#1348: the chat card has "Open in the office" ' + await ev(`document.querySelector('#achat')?.textContent.slice(0, 300)`));
    check(await ev(`!!document.querySelector('.oa_links a[href="/api/office/docs/${qid}/pdf?inline=1"][target="_blank"]')`), '#1348: ... and the PDF preview (new tab)');
    check(await ev(`oa_linkBtns([{id: 'a', label: 'x', href: 'javascript:alert(1)'}, {id: 'b', label: 'y', href: 'https://example.com'}]).includes('<a') === false`), '#1348: only app targets become links');
    await ev(`(() => { document.querySelector('.oa_links a[href="#office/offers/${qid}"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/offers/${qid}'`, 40), '#1348: the button opens the draft');
    // ================= #1350 suggested payments
    await call(CA, 'POST', `/api/office/docs/${qid}/status`, {status: 'sent'});
    await call(CA, 'POST', `/api/office/docs/${qid}/status`, {status: 'accepted'});
    const inv = await agent(ag.token, 'POST', `/offers/${qid}/invoice`, {});
    check(inv.http === 201, '#1350: the agent drafts the invoice ' + inv.http);
    await call(CA, 'PATCH', `/api/office/docs/${inv.doc.id}`, {recipient: {name: 'Musterfirma GmbH', lines: ['Weg 2', '10115 Berlin']}, service_from: today, service_to: today});
    const fin = await call(CA, 'POST', `/api/office/docs/${inv.doc.id}/finalize`);
    check(fin.http === 200, 'the invoice is finalised ' + fin.http);
    const pp = await agent(ag.token, 'POST', '/payment-suggestions', {invoice_id: inv.doc.id, amount: '200.00', date: today, reference: 'Musterfirma Abschlag', confidence: 'high'});
    check(pp.http === 201, '#1350: a payment suggestion ' + pp.http);
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('.ofdkinds [data-kind="invoice"]')`, 80);
    await ev(`(() => { document.querySelector('.ofdkinds [data-kind="invoice"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.oa_pp li').length === 1 && /Musterfirma Abschlag/.test(document.querySelector('.oa_pp').textContent)`, 80), '#1350: "Suggested payments" above the invoices');
    await shot('p251-a-payments.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), '#1350: on a phone nothing sticks out');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('[data-oa="pp-ok"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/docs/${inv.doc.id}/payments', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.payments.length === 1)`, 40), '#1350: Book records the payment');
    check(await ready(ev, `!document.querySelector('.oa_pp')`, 40), '#1350: the box goes when nothing is open');
    // ================= the access log
    await nav(B + '#office/settings');
    await ready(ev, `!!document.querySelector('[data-ofc="log"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ofc="log"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.oa_logf [data-ofc="log-ag"]')`, 40), '#1348: the access log has the filter "Agents"');
    await ev(`(() => { document.querySelector('[data-ofc="log-ag"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.ofdlog li').length > 0 && [...document.querySelectorAll('.ofdlog li')].every(li => /Office Bot/.test(li.textContent))`, 40), '#1348: ... it shows the agent\'s accesses only');
  }, false);

  console.log(`p251_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
