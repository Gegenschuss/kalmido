// 2.43.0 UI tests, part C (#1452 widgets changed right in the view, #1346 the project page as a pin board, #1504 the agents
// card), own container (start.sh). jsdom:
// - the project page: every block has a "…" menu; width a third and height tall from it are stored (opts lw / lh) and
//   shown (classes lw2 / lh3); "Make this the standard for everyone" shows for the owner only while the own arrangement
//   differs and promotes it; an edit member sees only "Reset to the standard"
// - "+ Block" > Notepad: a notepad opens for writing, leaving the field saves it; a colour from the "…" menu for everyone
// - the start page: the agents card lists both running jobs of an agent; the review is on the builder
// Firefox: 1440 mouse: the grip resizes a block and it snaps to the columns of six; 390 touch: one column, the "…" menu is a
// full touch target, no grip. Screenshots into $P2430C_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2430_c_ui', check, shots: 'P2430C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team,review';
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const item = (d, t) => items(d).find(x => (x.querySelector('.ml')?.firstChild?.textContent || x.textContent).trim() === t || x.getAttribute('title') === t);

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PATCH', `/api/lists/${P}/overview`, {description: '## Goal\nA new site.'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});  // the admin sees the jobs of agents it shares a list with
  for (const t of ['Build the sitemap', 'Check the links']) await call('POST', '/api/v1/agent/jobs', {title: t}, null, AGH);
  const lay = async (ck = CK) => call('GET', `/api/lists/${P}/layout`, null, ck);
  const pov = {'tasks.pov': JSON.stringify([P])};

  // ================= #1452 the "…" menu at a block
  let w = await boot({user: 'alice', hash: 'l/' + P, ls: pov}), d = w.document;
  await until(() => d.querySelector('#view .pov .lysix .povs'));
  check(d.querySelectorAll('#view .lysix[data-ly="project"] > .lyb [data-act="wg-more"]').length >= 3, '#1452: every block has a "…" menu');
  check(!d.querySelector('.wgstd'), '#1452: no standard bar while nothing differs');
  click(w, d.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]'));
  await until(() => item(d, '⅓'));
  check(item(d, '⅓') && item(d, '½') && item(d, '⅔') && item(d, 'Full') && item(d, 'Compact') && item(d, 'Tall') && item(d, 'Hide') && item(d, 'Arrange blocks…'), '#1452: width, height, hide, arrange in the menu ' + items(d).map(x => x.textContent.trim()).join('|'));
  click(w, item(d, '⅓'));
  let y = await until(async () => { const x = await lay(); return JSON.parse(x.mine || '{}').opts?.desc?.lw === 2 ? x : null; });
  check(y && JSON.parse(y.mine).half?.includes('desc'), '#1452: a third is stored (lw 2) and half for older versions ' + y?.mine);
  await until(() => d.querySelector('.lyb[data-lyk="desc"].lw2'));
  check(d.querySelector('.lyb[data-lyk="desc"].lw2'), '#1452: ... and shown');
  click(w, d.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]')); await until(() => item(d, 'Tall'));
  click(w, item(d, 'Tall'));
  await until(() => d.querySelector('.lyb[data-lyk="desc"].lh3'));
  check(d.querySelector('.lyb[data-lyk="desc"].lh3'), '#1452: height tall');
  check(w.eval(`HIST.undo.length`) >= 2, '#1452: each change is an undo step');
  // the standard bar: the owner may promote
  await until(() => d.querySelector('.wgstd [data-act="wg-promote"]'));
  check(d.querySelector('.wgstd [data-act="wg-promote"]') && d.querySelector('.wgstd [data-act="wg-reset"]'), '#1452: the owner sees "Make this the standard" + "Reset" once it differs');
  click(w, d.querySelector('.wgstd [data-act="wg-promote"]'));
  y = await until(async () => { const x = await lay(); return x.std && !x.mine ? x : null; });
  check(y && JSON.parse(y.std).opts?.desc?.lh === 3, '#1452: promoted: the standard has it, the own arrangement is gone ' + JSON.stringify(y));
  await until(() => !d.querySelector('.wgstd'));
  check(!d.querySelector('.wgstd'), '#1452: the bar goes once it is the standard');

  // ================= #1346 notepad + colour
  click(w, d.querySelector('[data-act="ly-add"][data-lyv="project"]'));
  await until(() => item(d, 'Notepad'));
  check(item(d, 'Notepad'), '#1346: "+ Block" offers a notepad');
  click(w, item(d, 'Notepad'));
  const ta = await until(() => d.querySelector('#view textarea.wgpadin'));
  check(ta, '#1346: the new notepad opens for writing');
  if (ta) {
    ta.value = '- call **the printer**'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    ta.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); ta.blur();
    y = await until(async () => { const x = await lay(); return (x.pads || []).some(p => p.body === '- call **the printer**') ? x : null; });
    check(y, '#1346: leaving the field saves the notepad');
    await until(() => d.querySelector('#view .wgpadmd b'));
    check(d.querySelector('#view .wgpadmd b')?.textContent === 'the printer', '#1346: shown as Markdown');
  }
  const np = (await lay()).pads?.[0];
  click(w, d.querySelector(`.lyb[data-lyk="np${np?.id}"] [data-act="wg-more"]`));
  await until(() => item(d, 'Blue'));
  check(item(d, 'Blue') && item(d, 'Rename…') && item(d, 'Delete notepad'), '#1346: colours, rename, delete in its menu');
  click(w, item(d, 'Blue'));
  y = await until(async () => { const x = await lay(); return x.style?.['np' + np?.id] === 'blue' ? x : null; });
  check(y, '#1346: the colour is stored for everyone');
  await until(() => d.querySelector(`.lyb[data-lyk="np${np?.id}"].lyc-blue`));
  check(d.querySelector(`.lyb[data-lyk="np${np?.id}"].lyc-blue`), '#1346: ... and tints the block');
  w.close();

  // bob (edit member): own change -> only "Reset to the standard"
  w = await boot({user: 'bob', hash: 'l/' + P, ls: pov}); d = w.document;
  await until(() => d.querySelector('#view .pov .lysix .povs'));
  check(d.querySelector(`.lyb[data-lyk="np${np?.id}"].lyc-blue`), '#1346: bob sees the notepad in its colour');
  click(w, d.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]')); await until(() => item(d, 'Full'));
  click(w, item(d, 'Full'));
  await until(() => d.querySelector('.wgstd'));
  check(d.querySelector('.wgstd [data-act="wg-reset"]') && !d.querySelector('.wgstd [data-act="wg-promote"]'), '#1452: an edit member: reset, no "standard for everyone"');
  click(w, d.querySelector('.wgstd [data-act="wg-reset"]'));
  y = await until(async () => { const x = await lay(BCK); return x.mine === '' ? x : null; }, 40);
  check(y, '#1452: reset = back to the standard');
  w.close();

  // ================= #1504 the agents card, the review on the builder
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelectorAll('.dc-agents .djob').length >= 2);
  const jobs = [...d.querySelectorAll('.dc-agents .djob')].map(x => x.querySelector('.dwt').textContent.trim());  // 2.45.0 (#1504): + "since HH:MM" after the title
  check(jobs.length === 2 && jobs.includes('Build the sitemap') && jobs.includes('Check the links'), '#1504: the agents card lists both running jobs ' + JSON.stringify(jobs));
  // 2.45.0 (#1504): the narrow cards sit in the right column (.hpcol) of the start page
  check(d.querySelector('.dgrid.lysix[data-ly="home"] > .hpcol > .lyb.lw2 [data-act="wg-more"]'), '#1452: start page cards are a third wide with their menu');
  w.close();
  w = await boot({user: 'alice', hash: 'review'}); d = w.document;
  await until(() => d.querySelector('.lysix[data-ly="review"] .lyb'));
  check(d.querySelector('.lysix[data-ly="review"] .lyb[data-lyk="done"] [data-act="wg-more"]'), '#1452: the review is on the builder');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.pov', '[${P}]'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#view .pov .lysix .povs', n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const g = await ev(`(() => { const g = document.querySelector('.pov .lysix'); return getComputedStyle(g).gridTemplateColumns.split(' ').length; })()`);
    check(g === 6, `${tag}: columns of six (${g})`);
    // drag the grip of "Members"/"Key links" (a half block) to two thirds
    const res = await ev(`(async () => {
      const el = document.querySelector('.lyb[data-lyk="links"]'), gp = el.querySelector('.lygrip'), g = el.parentElement, r = el.getBoundingClientRect(), col = g.clientWidth / 6;
      const pe = (t, x, y) => gp.dispatchEvent(new PointerEvent(t, {bubbles: true, pointerType: 'mouse', button: 0, clientX: x, clientY: y}));
      pe('pointerdown', r.right - 4, r.bottom - 4);
      document.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerType: 'mouse', clientX: r.left + col * 3.8, clientY: r.bottom - 4}));
      const live = el.classList.contains('lw4');
      document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerType: 'mouse', clientX: r.left + col * 3.8, clientY: r.bottom - 4}));
      await new Promise(f => setTimeout(f, 1200));
      const n = document.querySelector('.lyb[data-lyk="links"]');
      return {live, cls: n?.className, w: Math.round(n.getBoundingClientRect().width / col * 10) / 10};
    })()`);
    check(res.live && /\blw4\b/.test(res.cls) && res.w > 3.5 && res.w < 4.3, `${tag}: #1452 the grip snaps to two thirds ${JSON.stringify(res)}`);
    // the header moves a block: "Milestones" dropped before "Description" (a line shows where)
    const mv = await ev(`(async () => {
      const h = document.querySelector('.lyb[data-lyk="ms"] .povh h3'), hr = h.getBoundingClientRect(), t = document.querySelector('.lyb[data-lyk="desc"]').getBoundingClientRect();
      const pe = (el, ty, x, y) => el.dispatchEvent(new PointerEvent(ty, {bubbles: true, pointerType: 'mouse', button: 0, clientX: x, clientY: y}));
      pe(h, 'pointerdown', hr.left + 5, hr.top + 5);
      pe(document, 'pointermove', hr.left + 30, hr.top + 30);
      pe(document, 'pointermove', t.left + 10, t.top + 40);
      const line = !!document.querySelector('.wgline:not([hidden])');
      pe(document, 'pointerup', t.left + 10, t.top + 40);
      await new Promise(f => setTimeout(f, 1200));
      return {line, order: [...document.querySelectorAll('.pov .lysix > .lyb')].map(b => b.dataset.lyk).slice(0, 3)};
    })()`);
    check(mv.line && mv.order.indexOf('ms') < mv.order.indexOf('desc'), `${tag}: #1452 the header moves a block, a line shows where ${JSON.stringify(mv)}`);
    await shot('p2430c-1440-project.png');
    await ev(`(() => { document.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]').click(); return 1; })()`); await sleep(500);
    await shot('p2430c-1440-menu.png');
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); document.querySelector('#pop')?.classList.add('hidden'); return 1; })()`);
    for (const h of ['home', 'today', 'review']) { await o.nav(B + '#' + h); await sleep(2500); await shot(`p2430c-1440-${h}.png`); }
  }, false);
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const m = await ev(`(() => { const bs = [...document.querySelectorAll('.pov .lysix > .lyb')]; return {lefts: [...new Set(bs.map(b => Math.round(b.getBoundingClientRect().left)))].length,
      grip: !!document.querySelector('.lygrip'), tgt: [...document.querySelectorAll('.lymore')].filter(b => b.offsetWidth).map(b => Math.round(b.getBoundingClientRect().height)), sw: document.documentElement.scrollWidth}; })()`);
    check(m.lefts === 1 && !m.grip && m.tgt.length && m.tgt.every(h => h >= 43.5) && m.sw <= 390, `${tag}: #1452 one column, no grip, the menu a full touch target ${JSON.stringify(m)}`);
    await shot('p2430c-390-project.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
