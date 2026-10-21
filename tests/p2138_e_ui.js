// 2.138.0 UI tests, part E (office), own container (start.sh). Invented data only.
// (taken over from the 2.112.0 A, C and D suites, only the cases of #2234 #2235 #2237 #2241)
// jsdom:
// - #2237: the services have "Renumber" (admin): one click numbers the shown order 1..n, one undo step; the dialog
//   "Edit service" shows the currency beside the daily / hourly rate field (same row, no hint line below)
// - #2241: undoing an import lists the archived entries with name and where they are used, each with "Restore"; an
//   import undone before shows "Archive leftover entries" once
// - #2235: the bar shows the next step: draft -> Finalise (no "Create invoice" in front), finalised -> Mark as sent,
//   sent -> Accepted / Declined, accepted -> Create invoice; before the acceptance "Create invoice" is in "…" and asks
//   once (cancel = no invoice, yes = the invoice dialog); the PDF button reads "Preview"
// Firefox (desktop, mouse):
// - #2234: a dialog gets a grip at the bottom right; dragging it makes the dialog bigger; closing + opening keeps the size
//   (per kind); double click on the grip = default size again; a narrow window has no grip
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2138_e_ui', check, shots: 'P2138E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2138E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const svc = async () => (await call('GET', '/api/office/services?archived=1')).items || [];
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const item = (title, qty, rate, unit = 'day') => ({kind: 'service', title, qty, unit, rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});
const docStatus = async id => (await call('GET', `/api/office/docs/${id}`)).status;
const invCount = async () => ((await call('GET', '/api/office/docs?kind=invoice')).docs || []).length;
const menuInv = d => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Create invoice/.test(b.textContent));
// 2.138.0 (#2235): "Create invoice" opens the dialog full / progress / final (2.120.0 A, #2087); "full" is preselected
const absOk = async (w, d) => { const b = await until(() => d.querySelector('.modal input[name="abs-type"]') && d.querySelector('.modal .foot [data-m="ok"]'), 40); click(w, b); return !!b; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  await call('POST', '/api/office/services', {name_de: 'Kamera', category: 'Video', sort: 30, daily_rate: 700});
  await call('POST', '/api/office/services', {name_de: 'Schnitt', category: 'Video', sort: 70, hourly_rate: 90, unit: 'hour'});
  let w, d;

  // ================= #2237: "Renumber" + the currency beside the rate
  w = await boot({hash: 'office/services'}); d = w.document;
  const rb = await until(() => d.querySelector('.office .ofcbar [data-imr="renumber"]'), 60);
  check(!!rb && /Renumber/.test(rb.textContent), '#2237: the services have "Renumber"');
  rb?.click();
  check(await until(async () => (await svc()).map(x => x.sort).join() === '1,2', 40), '#2237: one click numbers the order 1..n');
  check(await until(() => w.eval(`HIST.undo.length && /renumbered/.test(HIST.undo[HIST.undo.length - 1].label)`), 20), '#2237: one undo step');
  await w.eval(`HIST.undo[HIST.undo.length - 1].undo()`);
  check(await until(async () => (await svc()).map(x => x.sort).join() === '30,70', 40), '#2237: undo brings the old order values back');
  await until(() => d.querySelector('.office [data-ofc="open"][data-kind="services"]') && !w.eval('typeof OFCP === "object" && OFCP.stale'), 40);
  // 2.138.0: a tap while the office view reloads after a save is replayed later (#2327, CSS.escape, not in jsdom): wait for it
  d.querySelector('.office [data-ofc="open"][data-kind="services"]').click();
  const rate = await until(() => d.querySelector('.modal #of-daily_rate'), 30);
  const row = rate?.closest('.row'), cur = row?.querySelector('.imrcur');
  check(!!cur && cur.previousElementSibling === rate && /EUR/.test(cur.textContent) && !row.querySelector('.ofchint'), '#2237: the currency stands beside the daily rate field');
  check(d.querySelector('.modal #of-hourly_rate')?.nextElementSibling?.classList.contains('imrcur'), '#2237: and beside the hourly rate');
  w.close();

  // ================= #2241: undo lists the archived entries, restore
  const imp = await call('POST', '/api/office/legacy/import', {services: [{name_de: 'Neu A', daily_rate: 100, action: 'new'}, {name_de: 'Neu B', action: 'new'}]});
  check(imp.http === 201, '#2241: an import ' + imp.http);
  const NA = (await svc()).find(x => x.name_de === 'Neu A').id;
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Imagefilm Probe'});
  await call('PUT', `/api/office/docs/${doc.id}/items`, {items: [{kind: 'service', service_id: NA, qty: 1}]});
  w = await boot({hash: 'office/import'}); d = w.document;
  const undo = await until(() => d.querySelector(`.oim .oimrun [data-oim="undo"][data-id="${imp.run_id}"]:not([data-kind])`), 60);
  undo?.click();
  (await until(() => d.querySelector('.modal [data-cd="yes"]'), 30))?.click();
  const box = await until(() => d.querySelector('.oim .imrarc'), 40);
  check(!!box && /Neu A/.test(box.textContent) && /Imagefilm Probe/.test(box.textContent) && !/Neu B/.test(box.textContent), '#2241: the archived entry with name and its document: ' + (box?.textContent || '').slice(0, 200));
  check(((await svc()).find(x => x.id === NA) || {}).archived === 1, '#2241: archived on the server');
  box?.querySelector('[data-imr="restore"]')?.click();
  check(await until(async () => ((await svc()).find(x => x.id === NA) || {}).archived === 0, 40), '#2241: "Restore" makes it active again');
  check(await until(() => /Restored/.test(d.querySelector('.oim .imrarc')?.textContent || ''), 30), '#2241: the entry shows as restored');

  // ================= #2241: "Archive leftover entries" for a run undone before
  // 2.144.6 B (#2400 F4): an entry restored by hand is no leftover; a run undone before 2.112 (no restore note) is
  // simulated by taking the note out of the run's detail
  w.eval(`OIM.arcd = null; oimLoad()`);
  await sleep(1200);
  check(!d.querySelector(`.oim [data-imr="tidy"][data-id="${imp.run_id}"]`), '#2400 F4: no "Archive leftover entries" for an entry restored by hand');
  execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, "UPDATE office_import_runs SET detail=(detail::jsonb - 'restored')::text WHERE id=?", JSON.stringify([imp.run_id])]);
  w.eval(`OIM.arcd = null; oimLoad()`);
  const tidy = await until(() => d.querySelector(`.oim [data-imr="tidy"][data-id="${imp.run_id}"]`), 40);
  check(!!tidy && /Archive leftover entries/.test(tidy.textContent) && /\(1\)/.test(tidy.textContent), '#2241: the undone run offers "Archive leftover entries" (1)');
  tidy?.click();
  (await until(() => d.querySelector('.modal [data-cd="yes"]'), 30))?.click();
  check(await until(async () => ((await svc()).find(x => x.id === NA) || {}).archived === 1, 40), '#2241: the leftover is archived');
  check(await until(() => !d.querySelector('.oim [data-imr="tidy"]'), 40), '#2241: the button goes once nothing is left');
  w.close();


  // ================= #2235: draft -> Finalise in front, invoice in "…" with one question; "Preview"
  const doc2 = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', items: [item('Concept', 1, 800)]});
  check(doc2.http === 201, 'a quotation ' + doc2.http);
  w = await boot({user: 'alice', hash: `office/offers/${doc2.id}`}); d = w.document;
  await until(() => d.querySelector('.ofdhead [data-ofd="more"]'), 60);
  check(d.querySelector('.ofdhead [data-ofd="finalize"]') && !d.querySelector('.ofdhead [data-ofd="to-invoice"]'), '#2235 draft: Finalise in front, no "Create invoice"');
  check(/^Preview$/.test(d.querySelector('.ofdhead .ofdpdf .ofdpdft')?.textContent || ''), '#2235: the PDF button reads "Preview" ' + d.querySelector('.ofdhead .ofdpdf')?.textContent);
  const n0 = await invCount();
  let asked = 0;
  w.confirm = () => { asked++; return false; };
  click(w, d.querySelector('.ofdhead [data-ofd="more"]'));
  await until(() => menuInv(d));
  click(w, menuInv(d));
  await until(() => asked);
  await sleep(500);
  check(asked === 1 && await invCount() === n0 && w.eval('OFD.doc.kind') === 'offer', '#2235: cancelled question = no invoice ' + asked);
  w.confirm = () => { asked++; return true; };
  click(w, d.querySelector('.ofdhead [data-ofd="more"]'));
  await until(() => menuInv(d));
  click(w, menuInv(d));
  check(await absOk(w, d), '#2235: yes = the invoice dialog (full / progress / final)');
  await until(() => w.eval('OFD.doc && OFD.doc.kind') === 'invoice');
  check(asked === 2 && w.eval('OFD.doc.kind') === 'invoice' && await invCount() === n0 + 1, '#2235: yes = the invoice draft from the draft quotation');
  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // finalised -> Mark as sent -> Accepted / Declined -> Create invoice (no question)
  const fin = await call('POST', `/api/office/docs/${doc2.id}/finalize`, {});
  check(fin.http === 200, 'finalise the quotation ' + fin.http + ' ' + (fin.error || ''));
  w = await boot({user: 'alice', hash: `office/offers/${doc2.id}`}); d = w.document;
  await until(() => d.querySelector('.ofdhead [data-ofd="kva-st"]'));
  const nb = () => [...d.querySelectorAll('.ofdhead .ofdnext')].map(b => b.dataset.st || b.dataset.ofd).join();
  check(nb() === 'sent' && !d.querySelector('.ofdhead [data-ofd="finalize"]'), '#2235 finalised: "Mark as sent" in front ' + nb());
  click(w, d.querySelector('.ofdhead [data-st="sent"]'));
  await until(() => nb() === 'accepted,declined');
  check(nb() === 'accepted,declined' && (await docStatus(doc2.id)) === 'sent', '#2235 sent: Accepted / Declined in front ' + nb());
  check(d.querySelector('.ofdhead [data-st="declined"]')?.getAttribute('aria-label') === 'Declined', '#2235: the icon button keeps its name for screen readers');
  click(w, d.querySelector('.ofdhead [data-st="accepted"]'));
  await until(() => nb() === 'to-invoice');
  check(nb() === 'to-invoice' && (await docStatus(doc2.id)) === 'accepted', '#2235 accepted: "Create invoice" in front ' + nb());
  click(w, d.querySelector('.ofdhead [data-ofd="more"]'));
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  check(!menuInv(d), '#2235 accepted: no second "Create invoice" in "…"');
  w.eval('document.body.click()');
  const n1 = await invCount(); asked = 0;
  click(w, d.querySelector('.ofdhead [data-ofd="to-invoice"]'));
  check(await absOk(w, d), '#2235 accepted: the invoice dialog');
  await until(() => w.eval('OFD.doc && OFD.doc.kind') === 'invoice');
  check(asked === 0 && await invCount() === n1 + 1, '#2235 accepted: the invoice without a question ' + asked);
  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= #2234: resizable dialogs (Firefox, desktop)
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(() => 1)`);
    await nav(B + '#inbox');
    await ready(ev, `typeof modal === 'function' && !!document.getElementById('app')`, 80);
    const open = `(() => { const m = modal('<h3>Probe</h3><p>text</p><div class="foot"><button class="btn">Close</button></div>'); m.classList.add('p2138probe'); return 1; })()`;
    const size = `(() => { const r = document.querySelector('.p2138probe .card').getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })()`;
    const drag = (dx, dy) => `(() => { const g = document.querySelector('.p2138probe .dlggrip'); const r = g.getBoundingClientRect(); const x = r.left + 4, y = r.top + 4;
      const o = (t, X, Y) => new PointerEvent(t, {bubbles: true, cancelable: true, clientX: X, clientY: Y, pointerId: 7, button: 0, pointerType: 'mouse'});
      g.dispatchEvent(o('pointerdown', x, y)); document.dispatchEvent(o('pointermove', x + ${dx}, y + ${dy})); document.dispatchEvent(o('pointerup', x + ${dx}, y + ${dy})); return 1; })()`;
    await ev(open);
    await ready(ev, `!!document.querySelector('.p2138probe .dlggrip')`);
    check(await ev(`!!document.querySelector('.p2138probe .dlggrip') && getComputedStyle(document.querySelector('.p2138probe .dlggrip')).display !== 'none' && !!document.querySelector('.p2138probe .dlggrip').getAttribute('aria-label')`), '#2234: the dialog has a grip with a label');
    const s0 = await ev(size);
    await ev(drag(100, 80));
    const s1 = await ev(size);
    check(s1[0] > s0[0] && s1[1] > s0[1], '#2234: dragging the grip makes the dialog bigger ' + s0 + ' -> ' + s1);
    await shot('p2138-e-resized.png');
    await ev(`(() => { document.querySelectorAll('.p2138probe').forEach(m => m.remove()); return 1; })()`);
    await ev(open); await ready(ev, `!!document.querySelector('.p2138probe .dlggrip')`);
    const s2 = await ev(size);
    check(s2[0] === s1[0] && s2[1] === s1[1], '#2234: the size is kept for the next time ' + s2);
    await ev(`(() => { document.querySelector('.p2138probe .dlggrip').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`);
    const s3 = await ev(size);
    check(s3[0] === s0[0] && s3[1] === s0[1], '#2234: double click = default size ' + s3);
    await ev(`(() => { document.querySelectorAll('.p2138probe').forEach(m => m.remove()); return 1; })()`);
    await ev(open); await ready(ev, `!!document.querySelector('.p2138probe .dlggrip')`);
    const s4 = await ev(size);
    check(s4[0] === s0[0] && s4[1] === s0[1], '#2234: the saved size is forgotten after the reset ' + s4);
    await ev(`(() => { document.querySelectorAll('.p2138probe').forEach(m => m.remove()); return 1; })()`);
    // a narrow window: no grip
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 420, height: 800}});
    await sleep(300);
    await ev(open); await sleep(300);
    check(await ev(`!document.querySelector('.p2138probe .dlggrip') || getComputedStyle(document.querySelector('.p2138probe .dlggrip')).display === 'none'`), '#2234: a narrow window has no grip');
  }, false);


  console.log(`p2138_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
