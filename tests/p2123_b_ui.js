// 2.123.0 part B (#2104): shares of knowledge pages in the browser -- the page's "…" menu has "Share…" and "Share folder…",
// the dialog (People + Public link) creates a link (the address shows with a copy button), the shared page gets its mark in
// the tree, the public page opens without an account (no app, no script, the text), and the guest finds the page under
// "Shared with me" and reads it in a dialog (desktop and 390 px)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2123_b_ui', check, shots: 'P2123B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2123B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,wiki';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('POST', '/api/users', {username: 'dave', display_name: 'Dave Customer', password: 'password123', email: 'dave@example.com'});
  const DK = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, DK);
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Customer/Guide', body: '# Start\n\nRead **this** first.\n\n- [x] kick-off\n- [ ] sign-off\n\nSee [[Customer/Prices]] and [[Internal]].'})).id;
  const PR = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Customer/Prices', body: 'All prices.'})).id;
  await call('POST', '/api/wiki/pages', {space: 'private', path: 'Internal', body: 'not shared'});
  check(PG > 0 && PR > 0, 'setup: private pages');

  const ffLogin = async ({ev, nav}, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const wait = async (ev, js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
  const menuPick = (ev, text) => ev(`(() => { const x = [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => b.textContent.trim().startsWith(${JSON.stringify(text)})); if (x) x.click(); return !!x; })()`);
  let url = '';
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#wiki/' + PG); await ready(ev); await sleep(900);
    await wait(ev, `!!document.querySelector('.wkpage [data-wk="pmenu"]')`);
    await ev(`(() => { document.querySelector('.wkpage [data-wk="pmenu"]').click(); return 1; })()`);
    await wait(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
    const items = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim())`);
    check(items && items.some(x => x.startsWith('Share…')) && items.some(x => x.startsWith('Share folder…')), '1440: the page menu has Share… and Share folder… ' + JSON.stringify(items));
    check(await menuPick(ev, 'Share…'), '1440: Share… opens');
    check(await wait(ev, `!!document.querySelector('.wshmodal [data-wsh="link"]')`), '1440: the dialog with People and Public link');
    const d = await ev(`(() => { const m = document.querySelector('.wshmodal'); return {h: m.querySelector('h3').textContent, secs: [...m.querySelectorAll('h4')].map(x => x.textContent), person: !!m.querySelector('[data-wsh="person"]')}; })()`);
    check(d && /Customer\/Guide|Guide/.test(d.h) && d.secs.includes('People') && d.secs.includes('Public link') && d.person, '1440: dialog sections ' + JSON.stringify(d));
    await ev(`(() => { document.querySelector('.wshmodal [data-wsh="link"]').click(); return 1; })()`);
    check(await wait(ev, `!!document.querySelector('.wshmodal [data-wsh-url]')`), '1440: the new link shows in the dialog');
    url = await ev(`document.querySelector('.wshmodal [data-wsh-url]').value`);
    check(/\/s\/w\/[A-Za-z0-9_-]{30,}$/.test(url || ''), '1440: the link address ' + url);
    check(await ev(`!!document.querySelector('.wshmodal [data-wsh="copy"]') && !!document.querySelector('.wshmodal [data-wsh="end"]')`), '1440: copy and turn off');
    const ub = await ev(`(HIST.undo[HIST.undo.length - 1] || {}).label || ''`);
    check(/Public link created/.test(ub), '1440: creating the link is one Undo step ' + ub);
    await shot('p2123-b-1440-dialog.png');
    await ev(`(() => { document.querySelector('.wshmodal [data-m="close"]').click(); return 1; })()`);
    check(await wait(ev, `!!document.querySelector('.wktitle .wshmark')`), '1440: the shared page has its mark in the title');
    check(await wait(ev, `!!document.querySelector('.wkside a[href="#wiki/${PG}"] .wshmark') && !document.querySelector('.wkside a[href="#wiki/${PR}"] .wshmark')`), '1440: the mark in the tree, only at the shared page');
    // the folder share with Dave (person)
    await ev(`(() => { document.querySelector('.wkpage [data-wk="pmenu"]').click(); return 1; })()`);
    await wait(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
    await menuPick(ev, 'Share folder…');
    check(await wait(ev, `!!document.querySelector('.wshmodal #wsh-email')`), '1440: the folder dialog');
    await ev(`(() => { const i = document.querySelector('.wshmodal #wsh-email'); i.value = 'dave@example.com'; document.querySelector('.wshmodal [data-wsh="person"]').click(); return 1; })()`);
    check(await wait(ev, `/Dave Customer/.test(document.querySelector('.wshmodal #wsh-ppl')?.textContent || '')`), '1440: Dave is in the folder share');
    await shot('p2123-b-1440-folder.png');
  }, false);
  // the public page without an account
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(url.replace(/^https?:\/\/[^/]+\//, B)); await sleep(800);
    const p = await ev(`({h1: document.querySelector('h1')?.textContent, scripts: document.scripts.length, app: !!document.querySelector('#top, #view'), bold: !!document.querySelector('.wkpub strong'), links: [...document.querySelectorAll('.wkpub a')].map(a => a.textContent), boxes: document.querySelectorAll('.wkpub input[type=checkbox]').length, wide: document.documentElement.scrollWidth <= 390})`);
    check(p && p.h1 === 'Guide' && p.scripts === 0 && !p.app && p.bold && p.boxes === 2 && !p.links.length && p.wide, '390: the public page: text only, no app, no script, no links to unshared pages ' + JSON.stringify(p));
    await shot('p2123-b-390-public.png');
  }, true);
  // the guest: "Shared with me"
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'dave') === 200, 'login dave');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#wiki'); await ready(ev); await sleep(900);
    check(await wait(ev, `!!document.querySelector('.wshside [data-wsh-open="${PG}"]') && !!document.querySelector('.wshside [data-wsh-open="${PR}"]')`), '390: Shared with me lists the folder\'s pages');
    check(await ev(`!/Internal/.test(document.querySelector('.wshside').textContent)`), '390: nothing else of the space');
    await shot('p2123-b-390-shared.png');
    await ev(`(() => { document.querySelector('.wshside [data-wsh-open="${PG}"]').click(); return 1; })()`);
    check(await wait(ev, `!!document.querySelector('.wshread .wshmd strong')`), '390: the page opens read-only');
    const g = await ev(`(() => { const m = document.querySelector('.wshread'); return {links: [...m.querySelectorAll('.wshmd a')].map(a => a.getAttribute('href')), edit: !!m.querySelector('textarea, [data-wk="mode"]')}; })()`);
    check(g && g.links.length === 1 && g.links[0] === '#wsh/' + PR && !g.edit, '390: only the shared page is a link, nothing to edit ' + JSON.stringify(g));
    await shot('p2123-b-390-read.png');
    await ev(`(() => { document.querySelector('.wshread .wshmd a').click(); return 1; })()`);
    check(await wait(ev, `/All prices/.test(document.querySelector('.wshread')?.textContent || '')`), '390: the link opens the other shared page in the dialog');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
