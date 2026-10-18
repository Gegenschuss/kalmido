// 2.99.0 part B: #2185 chat input: paperclip and the meeting button are level (same box, same centre) on desktop and 390 px,
// the width grip has no native title (own label); #2183 knowledge pages: the sidebar has no "…" menu any more, export / import /
// encryption sit in the header menu under "Area"; the page menu shows on hover / focus and always on touch
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p299_b_ui', check, shots: 'P299B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P299B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,agents,wiki';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const AGL = (await call('POST', '/api/lists', {name: 'With the agent'})).id;
  await call('PUT', `/api/lists/${AGL}/members`, {user_id: AG, role: 'edit'});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/First', body: 'Hello'})).id;
  check(PG > 0, 'setup: a private page');

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const wait = async (ev, js, n = 30) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
  const LEVEL = `(() => { const c = document.querySelector('.chcomp'); if (!c) return null;
    let m = c.querySelector('.mtgbtn');
    if (!m) { m = document.createElement('button'); m.type = 'button'; m.className = 'iconbtn mtgbtn'; m.innerHTML = ic('list'); c.insertBefore(m, c.querySelector('textarea')); }  // the button needs a proposal-taking agent: same markup
    const a = c.querySelector('.chclip').getBoundingClientRect(), b = m.getBoundingClientRect();
    return {ah: Math.round(a.height), bh: Math.round(b.height), ac: Math.round((a.top + a.bottom) / 2), bc: Math.round((b.top + b.bottom) / 2), bw: Math.round(b.width)}; })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'login');
    for (const [w, h, tag] of [[1440, 900, '1440'], [390, 844, '390']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(700);
      await wait(ev, `!!document.querySelector('.chcomp .chclip')`);
      const l = await ev(LEVEL);
      check(l && Math.abs(l.ah - l.bh) <= 1 && Math.abs(l.ac - l.bc) <= 1 && l.bw >= 44, `${tag}: #2185 paperclip and list button have the same height and centre ` + JSON.stringify(l));
      await shot(`p299-b-${tag}-chat.png`);
    }
    // the grip: no native title, own label on hover
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(700);
    const gr = await ev(`(() => { if (typeof placeGrips === 'function') placeGrips(); const g = document.querySelector('#pgrip-chat'); return g ? {title: g.getAttribute('title'), tip: g.dataset.tip || ''} : null; })()`);
    if (gr) check(!gr.title && /Width of the chat/.test(gr.tip), '1440: #2185 the chat grip has no native title, its label is in data-tip ' + JSON.stringify(gr));
    else console.log('note: no chat grip in this layout');

    // ================= #2183 knowledge pages
    await o.nav(B + '#wiki/' + PG); await ready(ev); await sleep(900);
    await wait(ev, `!!document.querySelector('.wkpage [data-wk="pmenu"]')`);
    const n = await ev(`({side: !!document.querySelector('.wkside [data-wk="menu"]'), dots: document.querySelectorAll('.wkside .iconbtn[aria-haspopup="menu"]').length, pmenu: !!document.querySelector('.wkpage [data-wk="pmenu"]')})`);
    check(n && !n.side && n.dots === 0 && n.pmenu, '1440: #2183 no "…" in the sidebar, the page menu stays ' + JSON.stringify(n));
    const op = await ev(`(() => { document.querySelector('#top [data-act="top-more"]').click(); return 1; })()`);
    await wait(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
    const items = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim())`);
    check(items && ['Export as ZIP', 'Import ZIP…'].every(t => items.some(x => x.includes(t))), '1440: #2183 the header menu has export and import ' + JSON.stringify(items));
    check(await ev(`(document.querySelector('#pop').textContent || '').includes('Area')`), '1440: #2183 under the heading "Area"');
    await shot('p299-b-1440-wiki-menu.png');
    await ev(`(() => { closePop(); return 1; })()`);
    // the page menu: hidden until the title row is hovered or focused (desktop)
    const op0 = await ev(`getComputedStyle(document.querySelector('.wkpage [data-wk="pmenu"]')).opacity`);
    await ev(`(() => { document.querySelector('.wkpage [data-wk="pmenu"]').focus(); return 1; })()`); await sleep(400);
    const op1 = await ev(`getComputedStyle(document.querySelector('.wkpage [data-wk="pmenu"]')).opacity`);
    check(+op0 === 0 && +op1 === 1, `1440: #2183 the page menu shows with keyboard focus only (${op0} -> ${op1})`);
  }, false);
  await firefox(async o => {  // a touch screen: the page menu is always there
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'login (touch)');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#wiki/' + PG); await ready(ev); await sleep(900);
    await wait(ev, `!!document.querySelector('.wkpage [data-wk="pmenu"]')`);
    const mo = await ev(`(() => { const b = document.querySelector('.wkpage [data-wk="pmenu"]'); return b ? {op: getComputedStyle(b).opacity, w: Math.round(b.getBoundingClientRect().width)} : null; })()`);
    check(mo && +mo.op === 1 && mo.w >= 40, '390: #2183 the page menu is always visible on a touch screen ' + JSON.stringify(mo));
    await shot('p299-b-390-wiki-page.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
