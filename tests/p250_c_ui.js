// 2.50.0 UI tests of part C (#329 customer view of public links, #1200 approval links; own container, start.sh). jsdom:
// - Share dialog > Public link: "What does the customer see?" with the switches (new link: sections + due dates on), the
//   list's fields and "only tasks with tag"; saving sends them, the server keeps them
// - the list's acceptance block appears once the link exists: "Request acceptance" creates a link to copy
// - a sent quotation: "Approval by the customer" -> "Create approval link" shows the link; draft quotations have no block
// Firefox (real layout, skipped without firefox): 390 px touch - the customer page and the approval page stay inside the screen,
// the decision buttons are big enough to tap
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p250_c_ui', check: (c, w) => check(c, w), shots: 'P250C_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P250C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'office', 'clients'])].join(',')});
  const L = (await call('POST', '/api/lists', {name: 'Customer project'})).id;
  const FLD = (await call('POST', `/api/lists/${L}/fields`, {name: 'Budget', type: 'number'})).id;
  await call('POST', '/api/tasks', {list_id: L, title: 'Rough cut', ltags: ['client']});
  await call('POST', '/api/tasks', {list_id: L, title: 'Approval of the rough cut', ms: 1});

  // ================= Share dialog > Public link > what the customer sees
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`shareModal(${L})`);
  let md = await until(() => d.querySelector('.modal.shmodal #cv-sec') && d.querySelector('.modal.shmodal'));
  check(md && md.querySelector('#cv-sec .cvh')?.textContent === 'What does the customer see?', 'the section "What does the customer see?"');
  const box = id => md.querySelector(`[data-cv="${id}"]`);
  check(box('sections')?.checked && box('due')?.checked && !box('progress')?.checked && !box('assignees')?.checked && !box('files')?.checked && !box('brand')?.checked,
    'a new link: sections + due dates on, the rest off (as before)');
  check(md.querySelector(`[data-cvf="${FLD}"]`) && !md.querySelector(`[data-cvf="${FLD}"]`).checked, 'the list field is offered, off');
  check(md.querySelector('#cv-tag') && [...md.querySelector('#cv-tag').options].some(o => o.textContent === 'Only with tag client'), 'only tasks with tag ...');
  box('progress').checked = true; md.querySelector(`[data-cvf="${FLD}"]`).checked = true;
  click(w, md.querySelector('[data-lp="save"]'));
  const k = await until(async () => { const j = await call('GET', `/api/lists/${L}/public-link`); return j.link && j.link; });
  check(k && k.show.progress === true && k.show.fields.length === 1 && k.show.fields[0] === FLD && k.show.sections === true, 'saved with the link: ' + JSON.stringify(k && k.show));
  // the acceptance block (the link exists now)
  const lb = await until(() => d.querySelector('.modal.shmodal #sg-lbox [data-sg="new"]'));
  check(lb && d.querySelector('#sg-what') && [...d.querySelector('#sg-what').options].some(o => /Milestone: Approval of the rough cut/.test(o.textContent)), 'acceptance: the milestone can be chosen');
  check(/qualified signature/.test(d.querySelector('#sg-lbox')?.textContent || ''), 'the note on the simple electronic signature');
  click(w, lb);
  const u = await until(() => d.querySelector('#sg-lbox [data-sgurl]'));
  check(u && /\/s\/q\/[A-Za-z0-9_-]{40,}$/.test(u.value), 'Request acceptance: the link to copy ' + (u && u.value));
  const PUB = k ? k.url.slice(k.url.indexOf('/s/') + 1) : '';
  const ACC = u ? u.value.slice(u.value.indexOf('/s/q/') + 1) : '';
  w.close();

  // ================= a quotation: draft without, sent with the approval block
  await call('PUT', '/api/office/settings', {company: {name: 'Example Studio', lines: ['Example Studio']}, lang: 'en', currency: 'EUR'});
  const SV = (await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', daily_rate: 900, hourly_rate: null, raw_fee: 0, producing: 0, intext: 'intern', unit: 'day', tax: 'standard'})).id;
  const DOC = (await call('POST', '/api/office/docs', {project_title: 'Image film', recipient: {name: 'Example Client', lines: ['Example Client']}})).id;
  await call('PUT', `/api/office/docs/${DOC}/items`, {items: [{service_id: SV, qty: 2}]});
  w = await boot({user: 'alice', hash: `office/offers/${DOC}`}); d = w.document;
  await until(() => d.querySelector('#view .ofdeditor'));
  check(d.querySelector('#view .ofdeditor') && !d.querySelector('#sg-box'), 'a draft quotation has no approval block');
  w.close();
  await call('POST', `/api/office/docs/${DOC}/status`, {status: 'sent'});
  w = await boot({user: 'alice', hash: `office/offers/${DOC}`}); d = w.document;
  const nb = await until(() => d.querySelector('#sg-box [data-sg="new"]'));
  check(nb && /Approval by the customer/.test(d.querySelector('.sgsec')?.textContent || ''), 'a sent quotation: "Approval by the customer"');
  click(w, nb);
  const qu = await until(() => d.querySelector('#sg-box [data-sgurl]'));
  check(qu && /\/s\/q\//.test(qu.value) && /Waiting for the customer/.test(d.querySelector('#sg-box').textContent), 'Create approval link: link + state');
  const OFF = qu ? qu.value.slice(qu.value.indexOf('/s/q/') + 1) : '';
  check(d.querySelector('#sg-box') && !d.querySelector('#sg-box').closest('fieldset[disabled]'), 'the block is outside the locked editor');
  w.close();

  // ================= Firefox: the customer's pages on the phone
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const OVER = `(() => { const vw = document.documentElement.clientWidth, bad = [...document.querySelectorAll('main *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).map(e => e.tagName + '.' + e.className).slice(0, 5); return {sw: document.scrollingElement.scrollWidth, vw, bad}; })()`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const [p, name, sel] of [[PUB, 'list', '.prog'], [OFF, 'offer', 'table.sig'], [ACC, 'acceptance', '.sigf']]) {
      if (!p) { check(false, 'no address for ' + name); continue; }
      await nav(B + p);
      for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(300);
      const o = await ev(OVER);
      check(o.sw <= o.vw + 1 && !o.bad.length, `390 px: the ${name} page stays inside the screen ` + JSON.stringify(o));
      if (name !== 'list') {
        const b = await ev(`(() => { const r = document.querySelector('.sigf button[value="accept"]').getBoundingClientRect(); return {h: r.height, w: r.width}; })()`);
        check(b.h >= 44, `390 px: the ${name} button is big enough to tap ` + JSON.stringify(b));
      }
      await shot(`p250c-${name}-390.png`);
    }
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
