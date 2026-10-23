// 2.187.0 part A UI test (#2476), own container (start.sh), Firefox (desktop + phone width): the page "Rights" of the office's
// settings and the office menu that follows the rights. Invented names only. P2187AUI_NOSTART=1 = the server already runs.
// - the office's settings carry the person's rights (org admin: manager "admin"; a member without a group: legacy)
// - the org admin opens Settings > Rights: People (the admin fixed, a member with the group picker), Groups (templates to
//   copy, own groups), Log; copies the template "Staff", changes a level (saved at once), gives a member "Staff" by the picker
// - the member with "Staff" sees no Bank / Figures in the office menu (also before the office is loaded: LS ofmLv), a direct
//   link to the bank shows the hint, Settings shows "My rights" (read only)
// - a member without a group keeps exactly the menu of before; a group without the special "release" has no "Finalise"
// - phone width: one column, nothing sticks out to the side
// - freelancer-matrix: office -- a person without an organisation opens the page without an error (own admin, own office)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2187_a_rights_ui', check, shots: 'P2187A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2187AUI_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {http: r.status, ...j}; };
const FEAT = 'cal,comments,collab,office,clients,docs,contacts,time,travel';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  const mk = async (u, orgs) => {
    const r = await call(CA, 'POST', '/api/users', {orgs, username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`});
    check(r.http < 300, 'user ' + u + ' ' + r.http);
    const ck = await login(u);
    await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, ...(orgs.length ? {workspace: 'org:' + ORG} : {})});
    return {id: r.id, ck};
  };
  const bob = await mk('bob', [{id: ORG, role: 'member'}]), carl = await mk('carl', [{id: ORG, role: 'member'}]);
  const frida = await mk('frida', []);  // freelancer-matrix: office (no organisation: the own personal office)

  // ---- the rights in the office's settings
  const sa = await call(CA, 'GET', '/api/office/settings');
  check(sa.rights?.manager === 'admin' && sa.rights.legacy === false && sa.rights.levels?.bank === 'manage', 'org admin: rights.manager admin, every area manage ' + JSON.stringify(sa.rights || {}).slice(0, 160));
  const sb = await call(bob.ck, 'GET', '/api/office/settings');
  check(sb.rights?.legacy === true && sb.rights.manager === '' && sb.rights.levels?.offers === 'edit' && sb.rights.levels?.bank === 'none', 'member without a group: legacy, the levels of before ' + JSON.stringify(sb.rights || {}).slice(0, 160));
  check(Array.isArray(sb.rights?.adm) && sb.rights.adm.includes('bank') && !sb.rights.adm.includes('offers'), 'the areas that were the admins\' ("adm")');
  const sf = await call(frida.ck, 'GET', '/api/office/settings');
  check(sf.http === 200 && sf.rights?.manager === 'admin', 'freelancer: the own admin of the personal office ' + sf.http + ' ' + JSON.stringify(sf.rights || {}).slice(0, 120));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const signOut = ev => ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status, () => 0)`);
  const fresh = async (ev, nav, u) => { await nav(B + 'static/icon.svg'); await signOut(ev); await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`); await signIn(ev, u); };
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.orr *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const items = `(typeof ofm_items === 'function' ? ofm_items().map(i => i.key).join(',') : '')`;
  const txt = `(document.querySelector('#view')?.textContent || '').replace(/\\s+/g, ' ')`;
  const rights = async () => call(CA, 'GET', '/api/office/rights');

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the menu of a member without a group: exactly as before (no admin points)
    await fresh(ev, nav, 'bob');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!(typeof OFC !== 'undefined' && OFC.info)`, 80), 'bob: the office loads');
    const before = await ev(items);
    check(before.includes('offers') && !before.includes('bank') && !before.includes('kpi') && !before.includes('travel'), 'bob without a group: the menu of before ' + before);

    // ---- the org admin: Settings > Rights
    await fresh(ev, nav, 'alice');
    await nav(B + '#office/rights');
    check(await ready(ev, `!!document.querySelector('.orr .orrsub')`, 80), 'alice: the page Rights with its sections ' + await ev(txt).catch(e => String(e)).then(t => String(t).slice(0, 200)));
    check(await ev(`!!document.querySelector('.ofrseg [data-go="office/rights"][aria-selected="true"]') && !!document.querySelector('.ofrseg [data-go="office/settings"]')`), 'the tab Rights next to General | Templates');
    check(await ev(`/Org admins always see everything/.test(document.querySelector('.orr-hint').textContent)`), 'the hint on top');
    check(await ev(`(() => { const ps = [...document.querySelectorAll('.orr-p')]; const a = ps.find(p => /Alice/.test(p.textContent)), b = ps.find(p => /Bob/.test(p.textContent));
      return !!a && !!a.querySelector('.orr-fixed') && !a.querySelector('.orr-pick') && !!b && !!b.querySelector('.orr-pick') && /Previous access/.test(b.textContent); })()`), 'People: the admin fixed, Bob with the picker (Previous access)');
    // Groups: copy the template "Staff"
    await ev(`(() => { document.querySelector('.orr [data-orr="sub"][data-k="groups"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.orr [data-orr="copy"][data-ref="tpl:staff"]')`), 'Groups: the templates with "Copy"');
    check(await ev(`!document.querySelector('.orr [data-orr="copy"][data-ref="tpl:legacy"]')`), '"Previous access" is no template to copy');
    await ev(`(() => { document.querySelector('.orr [data-orr="copy"][data-ref="tpl:staff"]').click(); return 1; })()`);
    let gid = 0;
    for (let i = 0; i < 40 && !gid; i++) { gid = ((await rights()).groups || [])[0]?.id || 0; if (!gid) await sleep(200); }
    check(gid > 0, 'the copy is an own group');
    check(await ready(ev, `!!document.querySelector('.orr details[data-orr-open="g:${gid}"][open] select[data-area="equipment"]')`), 'the new group is open with its levels');
    check(await ev(`(() => { const s = document.querySelector('.orr details[data-orr-open="g:${gid}"] select[data-area="bank"]'); return !!s && ![...s.options].some(o => o.value === 'own'); })()`), '"Own entries only" only where the area has it (not Bank)');
    check(await ev(`!!document.querySelector('.orr details[data-orr-open="g:${gid}"] select[data-area="receipts"] option[value="own"]')`), '"Own entries only" for receipts');
    // a level changes -> saved at once
    await ev(`(() => { const s = document.querySelector('.orr details[data-orr-open="g:${gid}"] select[data-area="equipment"]'); s.value = 'edit'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    let lv = '';
    for (let i = 0; i < 40 && lv !== 'edit'; i++) { lv = ((await rights()).groups || []).find(g => g.id === gid)?.levels?.equipment; if (lv !== 'edit') await sleep(200); }
    check(lv === 'edit', 'autosave: equipment edit ' + lv);
    check(await ready(ev, `!!document.querySelector('.orr details[data-orr-open="g:${gid}"][open]')`), 'the group stays open after the save');
    await shot('p2187-a-groups.png');
    // People: Bob gets "Staff" by the picker
    await ev(`(() => { document.querySelector('.orr [data-orr="sub"][data-k="people"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.orr input[data-orr="pg"][data-pid="${bob.id}"][value="tpl:staff"]')`);
    await ev(`(() => { const d = document.querySelector('.orr input[data-orr="pg"][data-pid="${bob.id}"]').closest('details'); d.open = true; const x = d.querySelector('input[value="tpl:staff"]'); x.checked = true; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    let bg = [];
    for (let i = 0; i < 40 && bg.join() !== 'tpl:staff'; i++) { bg = ((await rights()).people || []).find(p => p.id === bob.id)?.groups || []; if (bg.join() !== 'tpl:staff') await sleep(200); }
    check(bg.join() === 'tpl:staff', 'Bob in "Staff" (Previous access unticked) ' + bg.join());
    check(await ready(ev, `/Staff/.test(document.querySelector('.orr input[data-pid="${bob.id}"]')?.closest('.orr-p')?.querySelector('summary')?.textContent || '')`), 'the picker shows the new group');
    await shot('p2187-a-people.png');
    check((await call(CA, 'PUT', `/api/office/rights/people/${carl.id}`, {groups: [`g:${gid}`]})).http === 200, 'Carl in the own group (API)');
    // Log
    await ev(`(() => { document.querySelector('.orr [data-orr="sub"][data-k="log"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.orr-log > li').length >= 3`, 60), 'Log: the changes ' + await ev(`document.querySelectorAll('.orr-log > li').length`));
    check(await ev(`/changed the groups of Bob/.test(document.querySelector('.orr-log').textContent) && /created the group/.test(document.querySelector('.orr-log').textContent)`), 'Log: in words (who, whom)');
    await ev(`(() => { const d = [...document.querySelectorAll('.orr-le')].find(x => /changed the group /.test(x.textContent)); if (d) d.open = true; return 1; })()`);
    check(await ev(`[...document.querySelectorAll('.orr-le[open] .orr-ld li')].some(l => /Equipment: .*→ Edit/.test(l.textContent))`), 'Log: before -> after of the level');
    await shot('p2187-a-log.png');

    // ---- Bob with "Staff": no Bank / Figures in the menu
    await fresh(ev, nav, 'bob');
    await nav(B + '#office/offers');
    await ready(ev, `!!(typeof OFC !== 'undefined' && OFC.info && OFC.info.rights)`, 80);
    const st = await ev(items);
    check(!st.includes('bank') && !st.includes('kpi') && !st.includes('offers') && st.includes('travel') && st.includes('settings'), 'Bob (Staff): no Bank / Figures / quotations, own travel expenses, Settings ' + st);
    check(await ev(`!!(JSON.parse(localStorage.getItem('tasks.ofmLv') || localStorage.getItem('ofmLv') || '{}') && Object.values(JSON.parse(localStorage.getItem('tasks.ofmLv') || localStorage.getItem('ofmLv') || '{}'))[0]?.bank === 'none')`), 'the levels kept for the menu before the office is loaded');
    await nav(B + '#office/bank');
    check(await ready(ev, `/Your office rights do not include this area/.test(${txt})`, 60), 'a direct link to the bank: the hint');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('.orr') && /My rights/.test(${txt}) && !document.querySelector('.orr select:not([disabled])')`, 60), 'Settings: "My rights", read only');
    check(await ev(`/Own entries only/.test(${txt}) && /No access/.test(${txt})`), 'My rights: the levels in words');
    check(await ev(`!document.querySelector('.ofrseg [data-go="office/settings"]')`), 'no tab General without the settings');

    // ---- Carl (own group, quotations "edit" without the special "release"): a draft opens, no "Finalise"
    check((await call(CA, 'PATCH', `/api/office/rights/groups/${gid}`, {levels: {offers: 'edit'}})).http === 200, 'the own group edits quotations');
    const Q = await call(CA, 'POST', '/api/office/docs', {kind: 'offer', project_title: 'Example shoot'});
    await fresh(ev, nav, 'carl');
    await nav(B + '#office/offers/' + Q.id);
    check(await ready(ev, `!!document.querySelector('.ofdhead')`, 80), 'Carl: the draft opens ' + await ev(txt).catch(e => String(e)).then(t => String(t).slice(0, 160)));
    check(await ev(`!document.querySelector('[data-ofd="finalize"]')`), 'Carl without "release": no "Finalise"');

    // ---- phone width: alice's groups
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await fresh(ev, nav, 'alice');
    await ev(`(() => { localStorage.setItem('tasks.orrSub', '"groups"'); localStorage.setItem('orrSub', '"groups"'); return 1; })()`);
    await nav(B + '#office/rights');
    await ready(ev, `!!document.querySelector('.orr .orr-gl')`, 80);
    await ev(`(() => { if (typeof LS !== 'undefined') LS.set('orrSub', 'groups'); if (typeof ofcDraw === 'function') ofcDraw(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.orr details[data-orr-open="g:${gid}"]')`, 40);
    await ev(`(() => { const d = document.querySelector('.orr details[data-orr-open="g:${gid}"]'); if (d) d.open = true; return 1; })()`);
    await sleep(300);
    check(await ev(`(() => { const ss = [...document.querySelectorAll('.orr details[open] .orr-mg')]; return ss.length > 1 && ss.every(s => Math.abs(s.getBoundingClientRect().left - ss[0].getBoundingClientRect().left) < 2); })()`), 'phone: the areas in one column');
    check(await ev(noSide), 'phone: nothing sticks out to the side');
    await shot('p2187-a-phone.png');

    // ---- freelancer-matrix: office -- a person without an organisation
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await fresh(ev, nav, 'frida');
    await nav(B + '#office/rights');
    check(await ready(ev, `!!document.querySelector('.orr .orrsub')`, 80), 'freelancer: the page Rights opens ' + await ev(txt).catch(e => String(e)).then(t => String(t).slice(0, 200)));
    check(await ev(`/your own admin/.test(document.querySelector('.orr-hint').textContent) && !!document.querySelector('.orr-p .orr-fixed')`), 'freelancer: "your own admin", the person fixed');
  }, false);

  console.log(`p2187_a_rights_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
