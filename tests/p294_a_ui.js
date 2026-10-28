// 2.94.0 UI tests, part A (#1930: leads before the sales pipeline), own container (start.sh, mode workspaces), Firefox
// (desktop + phone width). Invented companies, people and figures only.
// - the pipeline has five columns, "Leads" first: the cards sorted by follow-up day, a day that has come in the accent
//   colour, next step and source on the card; no sum in the column; the toolbar counts the leads to follow up
// - "New lead": the dialog shows the lead's fields (company, e-mail, source, next step, follow-up) instead of client /
//   probability / expected date; saved as a lead with 10 %
// - "Convert into a client": the card moves to "Inquiry" with a new client; the undo brings the lead back and removes the
//   client; a lead with the e-mail of an existing client offers that client
// - the CSV import preview (duplicates marked) and the take over (one undo step)
// - phone: the switcher reaches the leads, nothing sticks out, large tap targets
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p294_a_ui', check, shots: 'P294A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P294A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => TC.day(n);

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
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Beispiel Werbung KG', email: 'werbung@example.com', org_id: org.id});
  const l1 = await call(CA, 'POST', '/api/office/deals', {title: 'Musterbau GmbH', stage: 'lead', contact: 'Frau Beispiel', company: 'Musterbau GmbH',
    email: 'lead1@example.com', source: 'website', next_step: 'Call back on Monday', follow_up: day(-1)});
  const l2 = await call(CA, 'POST', '/api/office/deals', {title: 'Later lead', stage: 'lead', follow_up: day(10)});
  const l3 = await call(CA, 'POST', '/api/office/deals', {title: 'Werbung lead', stage: 'lead', email: 'werbung@example.com'});
  await call(CA, 'POST', '/api/office/deals', {title: 'Imagefilm', client_id: cl.id, value: 10000});
  check(l1.http === 201 && l2.http === 201 && l3.http === 201, 'three leads ' + l1.http + l2.http + l3.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg') && !e.closest('.sr')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const deals = `fetch('/api/office/deals', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const leadCards = `[...document.querySelectorAll('[data-pipcol="lead"] .ppcard')]`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/pipeline');
    check(await ready(ev, `document.querySelectorAll('.pipcols .pipcol').length === 5`, 80), '#1930: the pipeline with five columns');
    check(await ev(`document.querySelector('.pipcols .pipcol').dataset.pipcol === 'lead' && ${leadCards}.length === 3`), '#1930: "Leads" first, with the three leads');
    check(await ev(`/Musterbau/.test(${leadCards}[0].textContent) && /Later lead/.test(${leadCards}[1].textContent)`), '#1930: sorted by follow-up day (none last)');
    check(await ev(`(() => { const c = ${leadCards}[0]; return c.classList.contains('lead-due') && /Call back on Monday/.test(c.textContent) && /Website/.test(c.textContent) && !!c.querySelector('.lead-fu.due'); })()`),
      '#1930: the due lead marked, with next step and source');
    const fuc = `[${leadCards}[0].querySelector('.lead-fu.due'), ${leadCards}[1].querySelector('.lead-fu')].map(e => e && getComputedStyle(e).color)`;
    check(await ev(`(() => { const [a, b] = ${fuc}; return !!a && !!b && a !== b; })()`),
      '#1930: a follow-up day that has come stands out (accent colour) ' + await ev(`JSON.stringify(${fuc})`));
    check(await ev(`!${leadCards}[1].classList.contains('lead-due')`), '#1930: a later follow-up is not marked');
    check(await ev(`!document.querySelector('[data-pipcol="lead"] header .rksum') && /1 to follow up/.test(document.querySelector('.lead-cnt')?.textContent || '')`), '#1930: no sum in the leads column, the toolbar counts');
    check(await ev(`/10,000\\.00/.test(document.querySelector('.pptiles').textContent)`), '#1930: the open sum without the leads');
    check(await ev(`[...document.querySelectorAll('.ppcard.lead-card')].every(c => c.getAttribute('draggable') !== 'true')`), '#1930: lead cards are not dragged (converted with the button)');
    await shot('p294-a-leads.png');

    // new lead
    await ev(`(() => { document.querySelector('[data-pp="new"]').click(); const st = document.querySelector('.modal #pp-stage'); st.value = 'lead'; st.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);  // 2.224.0 B (#2816): the one "New inquiry" button, the stage chosen in the dialog
    check(await ready(ev, `!!document.querySelector('.modal #lead-company')`), '#1930: the lead dialog');
    check(await ev(`(() => { const m = document.querySelector('.modal'); return !m.querySelector('.leadf').hidden && m.querySelector('.ppnolead #pp-prob').closest('.ppnolead').hidden && m.querySelector('#pp-stage').value === 'lead' ; })()`),
      '#1930: the lead fields instead of probability / date');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#pp-title').value = 'Neue Agentur'; m.querySelector('#pp-contact').value = 'Herr Neu';
      m.querySelector('#lead-company').value = 'Neue Agentur GmbH'; m.querySelector('#lead-email').value = 'neu@example.com'; m.querySelector('#lead-source').value = 'referral';
      m.querySelector('#lead-next').value = 'Send the showreel'; m.querySelector('#lead-fu').value = '${day(2)}'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && ${leadCards}.some(c => /Neue Agentur/.test(c.textContent))`), '#1930: the new lead in its column');
    check(await ev(`${deals}.then(j => j.items.some(x => x.title === 'Neue Agentur' && x.stage === 'lead' && x.probability === 10 && x.source === 'referral' && x.next_step === 'Send the showreel' && x.follow_up === '${day(2)}' && x.email === 'neu@example.com'))`),
      '#1930: saved as a lead with its fields');

    // convert + undo
    await ev(`(() => { ${leadCards}.find(c => /Neue Agentur/.test(c.textContent)).click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-m="convert"]') && !document.querySelector('.modal [data-m="offer"]')`), '#1930: the lead offers "Convert into a client", no quotation');
    await ev(`(() => { document.querySelector('.modal [data-m="convert"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && [...document.querySelectorAll('[data-pipcol="inquiry"] .ppcard')].some(c => /Neue Agentur/.test(c.textContent) && /Neue Agentur GmbH/.test(c.textContent))`, 60),
      '#1930: converted: in "Inquiry" with the new client');
    check(await ev(`${deals}.then(j => j.items.some(x => x.title === 'Neue Agentur' && x.stage === 'inquiry' && x.client_name === 'Neue Agentur GmbH'))`), '#1930: saved as an inquiry with a client');
    check(await ready(ev, `/Converted into a client/.test(document.querySelector('#toast')?.textContent || '')`), '#1930: the toast with undo');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await ready(ev, `${deals}.then(j => j.items.some(x => x.title === 'Neue Agentur' && x.stage === 'lead' && !x.client_id))`, 60), '#1930: undo: a lead again');
    check(await ev(`fetch('/api/clients', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => !(j.clients || []).some(c => c.name === 'Neue Agentur GmbH'))`), '#1930: undo: the new client is gone');
    // an existing client with the same e-mail is offered
    await ready(ev, `${leadCards}.some(c => /Werbung lead/.test(c.textContent))`);
    await ev(`(() => { ${leadCards}.find(c => /Werbung lead/.test(c.textContent)).click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal [data-m="convert"]')`);
    await ev(`(() => { document.querySelector('.modal [data-m="convert"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-lm="${cl.id}"]') && !!document.querySelector('.modal [data-lm="new"]')`), '#1930: the existing client with the same e-mail is offered');
    await ev(`(() => { document.querySelector('.modal [data-lm="${cl.id}"]').click(); return 1; })()`);
    check(await ready(ev, `${deals}.then(j => j.items.some(x => x.title === 'Werbung lead' && x.stage === 'inquiry' && x.client_id === ${cl.id}))`, 60), '#1930: converted with the existing client');
    check(await ready(ev, `!document.querySelector('.modal')`), '#1930: the dialogs are closed');

    // CSV import (the preview of a file read like the picker's)
    const csv = 'Name;Firma;E-Mail;Wiedervorlage\\nAnna Beispiel;Beispiel Studio;anna@example.com;20.11.2026\\nDoppelt;;lead1@example.com;\\n';
    await ev(`(() => { const t = '${csv}'; api('POST', '/api/office/leads/import', {text: t}).then(p => leadImpModal(t, p)); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .lead-pv') && document.querySelectorAll('.modal .lead-pv li').length === 2 && document.querySelectorAll('.modal .lead-pv li.lead-dup').length === 1`),
      '#1930: the import preview with the duplicate marked');
    await shot('p294-a-import.png');
    await ev(`(() => { document.querySelector('.modal [data-li="go"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`, 40), '2.356.0 B (#2934): the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && ${leadCards}.some(c => /Beispiel Studio/.test(c.textContent))`, 60), '#1930: the imported lead in the column');
    check(await ready(ev, `/1 lead imported/.test(document.querySelector('#toast')?.textContent || '')`), '#1930: the import toast with undo');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await ready(ev, `${deals}.then(j => !j.items.some(x => x.title === 'Beispiel Studio'))`, 60), '#1930: undo of the import');

    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    await ev(`(() => { document.querySelector('[data-pp="stage"][data-v="lead"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.pipcol')].filter(c => getComputedStyle(c).display !== 'none').map(c => c.dataset.pipcol).join() === 'lead'`), '#1930: phone: the switcher shows the leads alone');
    check(await ev(noSide), '#1930: phone: nothing sticks out to the side');
    check(await ev(`[...document.querySelectorAll('.pipcol.on .ppcard')].every(x => x.getBoundingClientRect().height >= 43) && [...document.querySelectorAll('.ofcbar [data-pp="new"]')].every(b => b.getBoundingClientRect().height >= 43)`), '#1930: phone: large tap targets');
    await shot('p294-a-leads-phone.png');
  }, false);
  console.log(`p294_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
