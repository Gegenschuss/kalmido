// kalmido-suite: fresh
// 2.353.0 B UI tests (#2786 #2777 #2773), jsdom, own container (start.sh). freelancer-matrix: Oberflaeche (frida has no organisation)
// - #2786: the agent status menu starts with "Agents and jobs", then a divider, then the agents; chats and jobs stay below
// - #2777: with a panel header (sidebar B / the phone's drawer) the project group's own label is visually hidden: "Projects" shows once
// - #2773: Settings > Integrations has "Scans from your computer" (download, inboxes), the document settings only point there
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2353B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DESK = {'(hover:hover) and (pointer:fine)': true};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  const st = await call('GET', '/api/state', null, CF);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...new Set([...(st.settings?.features || '').split(','), 'agents', 'files', 'docs'])].filter(Boolean).join(',')}, CF);
  check(((await call('GET', '/api/state', null, CF)).me.workspaces || []).length === 0, 'frida has no organisation');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'agents,files,docs,comments'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Office Helper'});
  check(ag.http < 300, 'setup: an agent');
  await call('POST', '/api/lists', {name: 'Office'}, CF);

  // ---- #2786 the agent status menu
  for (const user of ['alice', 'frida']) {
    const w = await boot({user, media: DESK}), d = w.document;
    await until(() => w.eval('S.booted && (S.agents || []).length >= 1'));
    w.eval('window.__m = null; menu = (a, items) => { window.__m = items; };');
    w.eval(`agentChipMenu(document.body)`);
    const items = await until(() => w.eval('window.__m'));
    const lab = x => x === '-' ? '-' : x.label || (x.row ? '[row]' : '?');
    const L = (items || []).map(lab);
    check(L[0] === 'Agents and jobs' && L[1] === '-', `${user}: "Agents and jobs" on top, then a divider ` + JSON.stringify(L));
    check(!L.some((x, i) => x === '-' && L[i + 1] === '-') && L[L.length - 1] !== '-', `${user}: no doubled or trailing divider ` + JSON.stringify(L));
    const iAg = L.findIndex(x => /Office Helper/.test(x) && !/^Chat with/.test(x)), iChat = L.findIndex(x => /^Chat with Office Helper/.test(x));
    check(iAg > 1 && iChat > iAg && L.indexOf('Choose the agents shown…') > iChat, `${user}: then the agents; chats and the rest stay below ` + JSON.stringify(L));
    w.close();
  }

  // ---- #2777 one "Projects" heading
  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'frida', mobile, ...(mobile ? {} : {media: DESK})}), d = w.document;
    await until(() => w.eval('S.booted'));
    if (mobile) { w.eval(`document.querySelector('#top .menu')?.click()`); }
    await until(() => d.querySelector('#side .sg-lists'));
    const panel = w.eval('sbb_on() || sbm_on()');
    const shown = [...d.querySelectorAll('#side .sg-lists .sgt > span')].filter(x => !x.classList.contains('sr') && !x.classList.contains('c') && /Projects/.test(x.textContent));
    const hid = [...d.querySelectorAll('#side .sg-lists .sgt > span.sr')].filter(x => /Projects/.test(x.textContent));
    check(panel ? shown.length === 0 && hid.length === 1 && /Projects/.test(d.querySelector('#side .sbbpt')?.textContent || '') : shown.length === 1,
      `${tag}: Projects once on screen (panel header ${panel}, group label shown ${shown.length}, hidden for readers ${hid.length})`);
    check(!!d.querySelector('#side .sg-lists [data-act="list-new"]') && !!d.querySelector('#side .sg-lists [data-act="side-group"]'), `${tag}: the group keeps its fold button and "New project"`);
    w.close();
  }

  // ---- #2773 Scans from your computer in Settings > Integrations
  {
    const w = await boot({user: 'frida', media: DESK}), d = w.document;
    await until(() => w.eval('S.booted && typeof dsc_integrDraw === "function"'), 60);
    w.eval(`settingsModal('integr')`);
    const card = await until(() => d.querySelector('.icard[data-jump="#s-scan-h"]'));
    check(!!card, 'Integrations: a card "Scans from your computer" (one click from the list of cards)');
    check(await until(() => d.querySelector('#s-scan .dsc-way')), 'Integrations: the section is drawn (folder watcher)');
    const txt = () => d.querySelector('#s-scan')?.textContent || '';
    check(/Folder watcher/.test(txt()) && ((d.querySelector('#s-scan .dsc-dl')?.children.length || 0) >= 1 || /Not available on this server/.test(txt())), 'Integrations: the download (or the honest hint) is there');
    check(!!d.querySelector('#s-scan-h') && !d.querySelector('#s-scan [data-dcs]'), 'Integrations: heading, no mail buttons of the documents');
    check(!!d.querySelector('.aczlink [data-m="go-access"]'), 'Integrations: a link to API tokens and webhooks (Access)');
    // the document settings: a pointer, no second copy
    w.eval(`document.querySelectorAll('.modal').forEach(m => modalClose(m))`);
    w.eval('dc_settings()');
    await until(() => d.querySelector('.dc-smd .dsc-way'));
    check(!d.querySelector('.dc-smd .dsc-dl') && !d.querySelector('.dc-smd .dsc-new') && !!d.querySelector('.dc-smd [data-dsc="tointegr"]'), 'document settings: only the pointer to Integrations');
    click(w, d.querySelector('.dc-smd [data-dsc="tointegr"]'));
    check(await until(() => !d.querySelector('.dc-smd') && d.querySelector('#s-scan .dsc-way')), 'the pointer opens Integrations at the section (one click)');
    w.close();
  }

  console.log(`p2353_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
