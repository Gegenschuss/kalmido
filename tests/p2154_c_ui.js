// 2.154.0 C (#2192) UI tests: data protection sheets of a client, own container (start.sh, mode workspaces), Firefox
// (desktop + phone width). Invented companies, people and figures only.
// - the client card has the section "Data protection" with the button "Data protection sheet": the dialog offers the
//   three sheets (the DPA with its hint) and the own templates; creating one from an own template lists it as "Open"
// - the sheet's menu offers the PDF, "Send by e-mail…" and "Upload the signed sheet…"; marking it signed by hand shows
//   the new status; a sheet from the sample opens the document editor (placeholders)
// - the client list's filter "DPA open" / "To check" keeps / hides the client; on a phone nothing sticks out to the side
// - a member sees neither the section nor the filter
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2154_c_ui', check, shots: 'P2154C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2154C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

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
  await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Studio GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Kundenweg 5', zip: '20000', city: 'Hamburg', country: 'DE', email: 'kunde@example.com'});
  const cl2 = await call(CA, 'POST', '/api/clients', {name: 'Kunde Zwei AG'});
  const tpl = await call(CA, 'POST', '/api/office/doc-templates', {kind: 'other', name: 'AVV kurz', lang: 'de', sign: 1, body: '# AVV\n\nZwischen {{client.name}} und {{company.name}}.'});
  check(cl.http < 300 && cl2.http < 300 && tpl.http < 300, 'clients + template ' + [cl.http, cl2.http, tpl.http]);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return 0; e.click(); return 1; })()`;
  const menuHas = re => `[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => ${re}.test(b.textContent))`;
  const menuClick = re => `(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => ${re}.test(x.textContent)); if (!b) return 0; b.click(); return 1; })()`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#view .dsbsec *')].filter(e => e.getClientRects().length && e.getBoundingClientRect().right > W + 1).length === 0; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the section + the dialog
    await nav(B + `#client/${cl.id}`);
    // 2.435.0 (#3600): the block Data protection starts folded (its own title then stays out, the fold title names it): open it
    await ready(ev, `!!document.querySelector('#view [data-mscl="fold"][data-k="privacy"]')`, 80); await ev(click('#view [data-mscl="fold"][data-k="privacy"]'));
    check(await ready(ev, `!!document.querySelector('#view .dsbsec [data-dsb="new"]')`, 80), '#2192: the client card has the section with the button');
    check(await ev(`/Data protection/.test(document.querySelector('#view [data-mscl="fold"][data-k="privacy"]')?.textContent || '') && !document.querySelector('#view .dsbsec li')`), '#2192: no sheet yet');
    await ev(click('#view .dsbsec [data-dsb="new"]'));
    check(await ready(ev, `!!document.querySelector('.modal.dsbdlg #dsb-kind')`, 60), '#2192: the dialog opens');
    check(await ev(`[...document.querySelectorAll('#dsb-kind option')].map(o => o.value).join() === 'dpa,info,consent'`), '#2192: three sheets');
    check(await ev(`/Art\\. 28/.test(document.querySelector('#dsb-hint').textContent)`), '#2192: the DPA hint');
    check(await ev(`[...document.querySelectorAll('#dsb-tpl option')].some(o => o.textContent === 'AVV kurz') && document.querySelector('#dsb-tpl').value === ''`), '#2192: the sample first, own templates offered');
    await shot('dialog');
    await ev(`(() => { const s = document.querySelector('#dsb-tpl'); s.value = '${tpl.id}'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ev(click('.modal.dsbdlg [data-m="save"]'));
    check(await ready(ev, `!document.querySelector('.modal.dsbdlg') && [...document.querySelectorAll('#view .dsbsec li')].some(li => /Data processing agreement/.test(li.textContent) && /Open/.test(li.textContent))`, 80),
      '#2192: the new sheet is listed as open');
    await shot('section');
    // ================= the menu
    await ev(click('#view .dsbsec [data-dsb="menu"]'));
    check(await ready(ev, menuHas('/Send by e-mail/')), '#2192: the menu offers the mail');
    check(await ev(menuHas('/Upload the signed sheet/')) && await ev(menuHas('/Open PDF/')) && await ev(menuHas('/Mark as signed/')), '#2192: upload, PDF, status');
    await ev(menuClick('/Mark as signed/'));
    check(await ready(ev, `[...document.querySelectorAll('#view .dsbsec .dsb-st')].some(s => s.textContent === 'Signed')`, 60), '#2192: marked as signed');
    // ================= the filter of the list
    const flt = v => `(() => { const s = document.querySelector('#mscl-dsb'); if (!s) return 0; s.value = '${v}'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
    const rows = `[...document.querySelectorAll('#view .ctlist .ctrow')].map(b => b.textContent).join('|')`;
    check(await ready(ev, `!!document.querySelector('#mscl-dsb')`), '#2192: the list has the filter');
    await ev(flt('dpa'));
    check(await ready(ev, `!${rows}.includes('Kunde')`), '#2192: "DPA open": the signed DPA does not count, no client');
    const s2 = await call(CA, 'POST', '/api/office/privacy-sheets', {client_id: cl2.id, kind: 'dpa', template_id: tpl.id});
    check(s2.http === 201, '#2192: a second client gets an open DPA ' + s2.http);
    await nav(B + `#client/${cl.id}`);
    await ev(flt('dpa'));
    if (!await ready(ev, `${rows}.includes('Kunde Zwei') && !${rows}.includes('Kunde Eins')`, 60)) {
      check(false, '#2192: "DPA open" keeps the client with an open DPA');
      console.log('DIAG', await ev(rows), await ev(`JSON.stringify({f: DSB.f, no: DSB.no, all: DSB.all})`));
    } else ok++;
    await ev(flt('review'));
    check(await ready(ev, `!${rows}.includes('Kunde')`), '#2192: "To check": none');
    await ev(flt(''));
    check(await ready(ev, `${rows}.includes('Kunde Eins') && ${rows}.includes('Kunde Zwei')`), '#2192: the filter off: all clients');
    // ================= a sheet from the sample opens the editor
    await ev(click('#view .dsbsec [data-dsb="new"]'));
    await ready(ev, `!!document.querySelector('.modal.dsbdlg #dsb-kind')`, 60);
    await ev(`(() => { const s = document.querySelector('#dsb-kind'); s.value = 'consent'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ev(`document.querySelector('#dsb-hint').textContent === ''`), '#2192: no hint for the consent');
    await ev(click('.modal.dsbdlg [data-m="save"]'));
    check(await ready(ev, `/^#office\\/gendocs\\/\\d+/.test(location.hash) && /Mustertext, keine Rechtsberatung/.test(document.querySelector('#dt-body')?.value || '')`, 80),
      '#2192: the sample opens in the document editor');
    // ================= phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + `#client/${cl.id}`);
    check(await ready(ev, `!!document.querySelector('#view .dsbsec li')`, 80) && await ev(noSide), '#2192: phone: the section fits');
    await shot('phone');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + `#client/${cl.id}`);
    await ready(ev, `!!document.querySelector('#view .msclcard')`, 80);
    await sleep(1500);
    check(await ev(`!document.querySelector('#view .dsbsec') && !document.querySelector('#mscl-dsb')`), '#2192: a member: no section, no filter');
  }, false);

  console.log(`p2154_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
