// 2.575.0 D UI tests "the menu of the area icons" (#4051, own container, start.sh, jsdom, invented names only):
// kalmido-suite: fresh
// - a right click (computer) on an area's icon of the bar opens its menu: Move up / down, Hide from the bar (not Projects),
//   Customise menu … (only areas with an editor), Set as start area, and only for an organisation's admin, apart at the end,
//   Switch off in this organisation
// - Move up stores the person's order (setting nav_menus "rail") and the phone's drawer row (390 px) shows the same order;
//   dragging an icon on the computer moves it too
// - Hide from the bar = Settings > Appearance > Sidebar (setting "sidebar"), a message with Undo and the hint where it comes back
// - Set as start area: start_page "a:<area>", the app opened without a page lands there; a wrong area is refused (400)
// - Switch off in this organisation: orgs.areas_off (the admin); a member has no such entry and the server refuses it
// - 390 px: a long press on an icon of the drawer's row opens the same menu; the click ending the press opens nothing
// freelancer-matrix: settings -- frida has no organisation (her own admin): the menu without point 5, everything else works
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2575D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { let x = null; try { x = await fn(); } catch { /* not there yet */ } if (x) return x; await sleep(150); } try { return await fn(); } catch { return null; } };
const FEAT = 'cal,comments,collab,office,clients,docs,wiki';
const state = async ck => (await call('GET', '/api/state', null, ck)).settings || {};
const rail = d => [...d.querySelectorAll('#srail .srb[data-sbb]')].map(b => b.dataset.sbb);
const acts = d => [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.dataset.act || '');
const right = (w, b) => b?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}));
const pick = async (w, act) => { const b = await until(() => w.document.querySelector(`#pop [role="menuitem"][data-act="${act}"]`)); b?.click(); return !!b; };
const closeMenu = w => { try { w.eval('closePop()'); } catch { /* none open */ } };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CA);
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'}, CA);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com'}, CA);
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck);
  const me = (await call('GET', '/api/state', null, CA)).me;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me.id}, CA);
  check(!!org.id, 'setup: an organisation');
  await call('PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'}, CA);
  for (const ck of [CA, CB]) await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}, ck);
  check(!((await call('GET', '/api/state', null, CF)).me.workspaces || []).length, 'setup: frida has no organisation');

  // ================= the computer: alice (the organisation's admin)
  {
    const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
    const ids0 = await until(() => { const x = rail(d); return x.includes('cal') && x.includes('wiki') && x; });
    check(!!ids0, 'the bar shows Calendar and Knowledge ' + JSON.stringify(ids0));
    check(ids0 && ids0.every(id => d.querySelector(`#srail .srb[data-sbb="${id}"]`).getAttribute('draggable') === 'true'), 'the computer\'s icons can be dragged');
    // Projects: no "Hide" (it always stays), but moving and the start
    right(w, d.querySelector('#srail .srb[data-sbb="tasks"]'));
    let A = await until(() => acts(d).length && acts(d));
    check(A && A.includes('sbb-up') && A.includes('sbb-down') && A.includes('sbb-start') && !A.includes('sbb-hide'), 'Projects: up, down, start area, no hide ' + JSON.stringify(A));
    check(A && !A.includes('sbb-orgoff'), 'Projects cannot be switched off in the organisation');
    closeMenu(w);
    // Calendar: the full menu of an area without an editor; the admin also sees "Switch off" only where the organisation has that switch
    right(w, d.querySelector('#srail .srb[data-sbb="cal"]'));
    A = await until(() => acts(d).length && acts(d));
    check(A && A.includes('sbb-hide') && !A.includes('sbb-custom'), 'Calendar: hide, no "Customise menu" (no editor) ' + JSON.stringify(A));
    closeMenu(w);
    right(w, d.querySelector('#srail .srb[data-sbb="wiki"]'));
    A = await until(() => acts(d).length && acts(d));
    check(A && A[A.length - 1] === 'sbb-orgoff', 'the admin: "Switch off in this organisation" is the last entry ' + JSON.stringify(A));
    const sep = d.querySelector('#pop [data-act="sbb-orgoff"]')?.previousElementSibling;
    check(sep?.tagName === 'HR' && d.querySelector('#pop [data-act="sbb-orgoff"]').classList.contains('danger'), 'the switch sits apart (a line before it), marked as dangerous');
    closeMenu(w);

    // 1. Move up: the order is stored once for the person
    const ci = ids0.indexOf('cal'), above = ids0[ci - 1];
    right(w, d.querySelector('#srail .srb[data-sbb="cal"]'));
    check(await pick(w, 'sbb-up'), 'Move up is there');
    const ids1 = await until(() => { const x = rail(d); return x.indexOf('cal') === ci - 1 && x; });
    check(ids1 && ids1[ci] === above, 'Move up: Calendar is above ' + above + ' ' + JSON.stringify(ids1));
    const rail1 = await until(async () => { const m = JSON.parse((await state(CA)).nav_menus || '{}'); return m.rail?.order?.indexOf('cal') === ci - 1 && m.rail.order; });
    check(!!rail1, 'the order is stored in nav_menus "rail" ' + JSON.stringify(rail1));
    // the first icon has no "Move up", the last no "Move down"
    right(w, d.querySelector('#srail .srb[data-sbb]'));
    A = await until(() => acts(d).length && acts(d));
    check(A && !A.includes('sbb-up') && A.includes('sbb-down'), 'the first icon: no "Move up" ' + JSON.stringify(A));
    closeMenu(w);

    // dragging on the computer: Notes dropped on the lower half of the first icon lands right after it
    {
      const first = rail(d)[0], src = d.querySelector('#srail .srb[data-sbb="notes"]'), dst = d.querySelector(`#srail .srb[data-sbb="${first}"]`);
      const dt = {effectAllowed: '', dropEffect: '', setData() {}, getData: () => ''};
      const fire = (el, type, y) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = dt; e.clientY = y; el.dispatchEvent(e); };
      fire(src, 'dragstart', 0); fire(dst, 'dragover', 1); fire(dst, 'drop', 1); fire(src, 'dragend', 0);
      const ids2 = await until(() => { const x = rail(d); return x[1] === 'notes' && x; });
      check(!!ids2, 'dragging Notes onto the first icon puts it second ' + JSON.stringify(rail(d)));
      check(await until(async () => JSON.parse((await state(CA)).nav_menus || '{}').rail?.order?.[1] === 'notes'), 'the dragged order is stored');
    }

    // 2. Hide from the bar: the message names where it comes back; Undo brings it back
    right(w, d.querySelector('#srail .srb[data-sbb="cal"]'));
    check(await pick(w, 'sbb-hide'), 'Hide from the bar is there');
    check(await until(() => !d.querySelector('#srail .srb[data-sbb="cal"]')), 'Hide: Calendar left the bar');
    const msg = await until(() => !d.querySelector('#toast').classList.contains('hidden') && /hidden from the bar/.test(d.querySelector('#toast').textContent) && d.querySelector('#toast').textContent);
    check(/hidden from the bar/.test(msg || '') && /Settings > Appearance > Sidebar/.test(msg || ''), 'the message says where it comes back: ' + msg);
    check(await until(async () => (JSON.parse((await state(CA)).sidebar || '{}').hidden || []).includes('e:cal')), 'the same setting as Settings > Appearance > Sidebar (sidebar e:cal)');
    d.querySelector('#toast button')?.click();
    check(await until(() => !!d.querySelector('#srail .srb[data-sbb="cal"]')), 'Undo: Calendar is back in the bar');
    check(await until(async () => !(JSON.parse((await state(CA)).sidebar || '{}').hidden || []).includes('e:cal')), 'Undo: stored back');

    // 3. Customise menu …: the area's editor (office has one)
    right(w, d.querySelector('#srail .srb[data-sbb="office"]'));
    check(await pick(w, 'sbb-custom'), 'Customise menu … for the office');
    check(await until(() => w.eval('NAV.edit') === 'office' && /^#office/.test(w.location.hash)), 'Customise opens the office with its menu editor ' + w.location.hash);
    w.eval('nav_edit("office", false)');

    // 5. Switch off in this organisation (the admin)
    right(w, d.querySelector('#srail .srb[data-sbb="wiki"]'));
    check(await pick(w, 'sbb-orgoff'), 'the admin switches Knowledge off in the organisation');
    check(await until(async () => ((await call('GET', '/api/orgs', null, CA)).orgs || []).find(o => o.id === org.id)?.areas_off?.includes('wiki')), 'stored in orgs.areas_off');
    check(await until(() => !d.querySelector('#srail .srb[data-sbb="wiki"]')), 'Knowledge left the bar in the organisation');
    d.querySelector('#toast button')?.click();
    check(await until(async () => !((await call('GET', '/api/orgs', null, CA)).orgs || []).find(o => o.id === org.id)?.areas_off?.includes('wiki')), 'Undo switches it on again');
    w.close();
  }

  // ================= a member: no point 5, and the server refuses it
  {
    const w = await boot({user: 'bob', hash: 'today'}), d = w.document;
    const b = await until(() => d.querySelector('#srail .srb[data-sbb="wiki"]'));
    right(w, b);
    const A = await until(() => acts(d).length && acts(d));
    check(A && A.includes('sbb-start') && !A.includes('sbb-orgoff'), 'the member: no "Switch off in this organisation" ' + JSON.stringify(A));
    closeMenu(w);
    const x = await call('PATCH', `/api/orgs/${org.id}`, {areas_off: ['wiki']}, CB);
    check(x.status >= 400 && x.status < 500, 'the server refuses the member\'s switch ' + x.status);
    // the person's order is the same on every device: the drawer's row on a phone of 390 px
    w.close();
  }

  // ================= 4. Set as start area (frida, no organisation) + the phone (390 px)
  {
    const w = await boot({user: 'frida', hash: 'today', startPage: null}), d = w.document;
    const b = await until(() => d.querySelector('#srail .srb[data-sbb="notes"]'));
    right(w, b);
    const A = await until(() => acts(d).length && acts(d));
    check(A && A.includes('sbb-up') && A.includes('sbb-hide') && A.includes('sbb-start') && !A.includes('sbb-orgoff'), 'frida (no organisation): the menu without point 5 ' + JSON.stringify(A));
    check(await pick(w, 'sbb-start'), 'Set as start area');
    check(await until(async () => (await state(CF)).start_page === 'a:notes'), 'start_page is a:notes');
    right(w, await until(() => d.querySelector('#srail .srb[data-sbb="notes"]')));  // drawn again after the change
    const st = await until(() => d.querySelector('#pop [data-act="sbb-start"]'));
    check(st?.disabled && st.classList.contains('on'), 'the start area shows ticked in its menu');
    closeMenu(w);
    w.close();
    const bad = await call('PATCH', '/api/settings', {start_page: 'a:nope'}, CF);
    check(bad.status === 400, 'an unknown start area is refused ' + bad.status);
    const w2 = await boot({user: 'frida', startPage: null, ls: {'tasks.lastKey': null}});
    check(await until(() => /^#notes/.test(w2.location.hash)), 'the app opened without a page lands on the start area ' + w2.location.hash);
    w2.close();
  }
  {
    // alice's order on a phone of 390 px: the drawer row has the same order; a long press opens the same menu
    const w = await boot({user: 'alice', hash: 'today', mobile: true}), d = w.document;
    await until(() => w.eval('S.booted'));
    w.eval('sideDrawerOpen(); renderSide()');
    const row = await until(() => { const x = [...d.querySelectorAll('#side .sbmr .srb[data-sbb]')].map(b => b.dataset.sbb); return x.length > 3 && x; });
    const ord = JSON.parse((await state(CA)).nav_menus || '{}').rail?.order || [];
    const want = ord.filter(id => row.includes(id));
    check(row && row.join('|') === want.join('|'), '390 px: the drawer row follows the stored order ' + JSON.stringify({row, want}));
    const b = d.querySelector('#side .sbmr .srb[data-sbb="wiki"]');  // an area the organisation can switch off
    const pe = (type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'pointerType', {value: 'touch'}); Object.defineProperty(e, 'clientX', {value: 20}); Object.defineProperty(e, 'clientY', {value: 20}); return e; };
    b.dispatchEvent(pe('pointerdown'));
    const A = await until(() => acts(d).length && acts(d));
    check(A && A.includes('sbb-hide') && A.includes('sbb-start') && A.includes('sbb-orgoff'), '390 px: a long press opens the icon\'s menu ' + JSON.stringify(A));
    b.dispatchEvent(pe('pointerup'));
    const h0 = w.location.hash;
    b.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, detail: 1}));
    await sleep(300);
    check(w.location.hash === h0 && !!d.querySelector('#pop [data-act="sbb-start"]'), '390 px: the click ending the press opens nothing');
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
