// 2.371.3 (#3333, #3152): knowledge pages (Firefox, real keys), computer 1280x800 (alice, admin of the organisation Alpha) and
// tablet 820x1180 (frida, a person WITHOUT an organisation: freelancer-matrix: wiki):
// - #3333: "/" -> "Task (#)" puts "#" and lists the tasks the person sees; typing a title word filters the loaded tasks, a word
//   only in a comment comes from the server's search (GET /api/search); Enter puts "#id " (saved page read back over the API)
// - #3152: PUT /api/wiki/style: a fixed choice only (400 for anything else), the private space's person sets it (frida), in an
//   organisation only its admins (bob, a member: 403); the index answers style + may_style; the page carries the class of
//   the space's style, "Reading style…" in the page's "…" overrides it for the person (account setting look.wkSt), light
//   and dark keep the theme's colours
// Invented texts only. Screenshots: P23713_SHOTS.
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23713_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2371_3_wiki_ui', check, shots: 'P23713_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const K = {Enter: '', Escape: ''};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const bu = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [org.id]});
  const CF = await login('frida'), CB = await login('bob');
  for (const ck of [CF, CB]) await call(ck, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && bu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation, bob is in Alpha');

  // ---- #3152 over the API
  const OS = `org:${org.id}`;
  for (const bad of ['fancy', '<style>', 'clear', 5, null]) {
    const r = await call(CF, 'PUT', '/api/wiki/style', {space: 'private', style: bad});
    check(r.http === 400, `#3152: style ${JSON.stringify(bad)} is refused (${r.http})`);
  }
  let r = await call(CF, 'PUT', '/api/wiki/style', {space: 'private', style: 'book'});
  check(r.http === 200 && r.style === 'book' && r.space === 'private', `#3152: frida (no organisation) sets her private space's style ${JSON.stringify(r)}`);
  let ix = await call(CF, 'GET', '/api/wiki?space=private');
  check(ix.style === 'book' && ix.may_style === true, `#3152: frida's index: style book, may_style ${JSON.stringify([ix.style, ix.may_style])}`);
  r = await call(CB, 'PUT', '/api/wiki/style', {space: OS, style: 'compact'});
  check(r.http === 403, `#3152: bob (a member) may not set the organisation's style (${r.http})`);
  r = await call(CB, 'PUT', '/api/wiki/style', {space: 'private', style: 'notepad'});
  check(r.http === 200, `#3152: bob sets his own private space (${r.http})`);
  r = await call(CF, 'PUT', '/api/wiki/style', {space: OS, style: 'compact'});
  check(r.http === 404, `#3152: frida cannot reach Alpha's space (${r.http})`);
  r = await call(CA, 'PUT', '/api/wiki/style', {space: OS, style: 'notepad'});
  check(r.http === 200 && r.style === 'notepad', `#3152: alice (admin) sets Alpha's style (${r.http})`);
  ix = await call(CB, 'GET', `/api/wiki?space=${OS}`);
  check(ix.style === 'notepad' && ix.may_style === false, `#3152: bob's index of Alpha: notepad, may_style false ${JSON.stringify([ix.style, ix.may_style])}`);
  check((await call(CA, 'GET', '/api/wiki?space=private')).style === '', '#3152: alice\'s private space stays Clear (the styles are per space)');
  await call(CB, 'PATCH', '/api/settings', {look: JSON.stringify({wkSt: 'body{display:none}', theme: 'dark'})});
  let lk0 = (await call(CB, 'GET', '/api/state')).settings?.look || '';
  check(!/wkSt/.test(lk0) && /"theme":"dark"/.test(lk0), `#3152: the own style keeps only a known value (${lk0})`);
  await call(CB, 'PATCH', '/api/settings', {look: JSON.stringify({wkSt: 'book'})});
  lk0 = (await call(CB, 'GET', '/api/state')).settings?.look || '';
  check(/"wkSt":"book"/.test(lk0), `#3152: a known own style is kept (${lk0})`);

  // ---- tasks for #3333 (their own, in the inbox) and the pages
  const runs = [];
  for (const [who, ck, sp] of [['alice', CA, OS], ['frida', CF, 'private']]) {
    const t1 = (await call(ck, 'POST', '/api/tasks', {title: `Call the printer ${who}`})).id;
    const t2 = (await call(ck, 'POST', '/api/tasks', {title: `Order paper ${who}`})).id;
    await call(ck, 'POST', `/api/tasks/${t2}/comments`, {body: 'ask about zebrafinch stock'});
    const id = (await call(ck, 'POST', '/api/wiki/pages', {space: sp, path: 'Notes', body: 'Start'})).id;
    check(t1 && t2 && id, `setup: ${who}'s tasks and page`);
    runs.push({who, ck, sp, id, t1, t2});
  }

  for (const [[vw, vh], run] of [[[1280, 800], runs[0]], [[820, 1180], runs[1]]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const tag = `${vw} ${run.who}`;
    const until = async (expr, n = 40) => { for (let i = 0; i < n; i++) { const x = await ev(expr).catch(() => null); if (x) return x; await sleep(250); } return ev(expr).catch(() => null); };
    const saved = async want => { let b = ''; for (let i = 0; i < 60 && b !== want; i++) { await sleep(250); b = (await call(run.ck, 'GET', `/api/wiki/pages/${run.id}`)).body; } return b; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const type = s => act([{type: 'key', id: 'k', actions: [...s].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const press = key => act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: K[key] || key}, {type: 'keyUp', value: K[key] || key}]}]);
    const acList = `(() => { const a = document.querySelector('#wk-ac'); return a && !a.classList.contains('hidden') && a.querySelector('button') ? [...a.querySelectorAll('button')].map(b => b.textContent.trim()) : null; })()`;
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${run.who}', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${tag}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + `#wiki/${run.id}`);
    // #3152: the space's style on the page (alice: Alpha = notepad, frida: private = book)
    const want = run.who === 'alice' ? 'notepad' : 'book';
    check(await until(`!!document.querySelector('article.wkpage.wkst-${want} #wk-md')`), `${tag}: the page shows the space's style ${want}`);
    const look = await ev(`(() => { const m = getComputedStyle(document.querySelector('#wk-md')); return {ff: m.fontFamily, bg: m.backgroundImage, lh: m.lineHeight}; })()`);
    check(want === 'book' ? /Georgia|serif/i.test(look.ff) : /gradient/.test(look.bg), `${tag}: the style is visible ${JSON.stringify(look)}`);
    // light and dark: the paper / the text follow the theme's variables
    const col = async th => { await ev(`(() => { document.documentElement.dataset.theme = '${th}'; return 1; })()`); await sleep(100); return ev(`(() => { const m = getComputedStyle(document.querySelector('#wk-md')); return {c: m.color, bg: m.backgroundImage}; })()`); };
    const li = await col('light'), dk = await col('dark');
    check(li.c !== dk.c, `${tag}: light and dark give different text colours ${JSON.stringify([li.c, dk.c])}`);
    if (want === 'notepad') check(li.bg !== dk.bg, `${tag}: the notepad's paper follows light / dark`);
    if (vw > 1000) await shot(`p2371_3_${vw}_${want}.png`);
    // the own choice in the page's "…" -> "Reading style…" -> "Compact"
    await ev(`(() => { document.querySelector('[data-wk="pmenu"]').click(); return 1; })()`);
    await until(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
    const sub = await ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /Reading style/.test(x.textContent)); if (!b) return null; b.click(); return 1; })()`);
    check(sub, `${tag}: the page's "…" has "Reading style…"`);
    const items = await until(`(() => { const t = [...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()); return t.some(x => /^Compact/.test(x)) ? t : null; })()`);
    check(items && items.some(x => /^Like the space \((Book|Notepad)\)$/.test(x)) && items.filter(x => x === 'Compact').length === 2, `${tag}: the choices: mine and the space's (both may set it) ${JSON.stringify(items)}`);
    const heads = await ev(`[...document.querySelectorAll('#pop .mgh')].map(x => x.textContent.trim())`);
    check(heads.includes('For me') && heads.includes('Default of the space'), `${tag}: "For me" and (admin / own space) "Default of the space" ${JSON.stringify(heads)}`);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => x.textContent.trim() === 'Compact').click(); return 1; })()`);
    check(await until(`!!document.querySelector('article.wkpage.wkst-compact') && !document.querySelector('article.wkpage.wkst-${want}')`), `${tag}: the own choice Compact replaces the space's style`);
    let lk = '';
    for (let i = 0; i < 40 && !/"wkSt":"compact"/.test(lk); i++) { await sleep(250); lk = (await call(run.ck, 'GET', '/api/state')).settings?.look || ''; }
    check(/"wkSt":"compact"/.test(lk), `${tag}: the choice is kept with the account (${lk})`);
    await ev(`(() => { LS.del('wkSt'); renderView(); return 1; })()`);
    check(await until(`!!document.querySelector('article.wkpage.wkst-${want}')`), `${tag}: without an own choice the space's style is back`);

    // #3333 in the plain text field (the account setting look.wkEd = text)
    await ev(`(() => { LS.set('wkEd', 'text'); renderView(); return 1; })()`);
    await until(`!!document.querySelector('[data-wk="mode"][data-m="edit"]')`);
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    await until(`!!document.querySelector('#wk-body')`);
    await ev(`(() => { const t = document.querySelector('#wk-body'); t.focus(); t.setSelectionRange(t.value.length, t.value.length); return 1; })()`);
    await press('Enter'); await type('/task');
    const m1 = await until(acList);
    check(m1 && m1[0] === 'Task (#)', `${tag}: "/task" offers "Task (#)" ${JSON.stringify(m1)}`);
    await press('Enter');
    const m2 = await until(acList);
    check(await ev(`document.querySelector('#wk-body').value`) === 'Start\n#' && m2 && m2.some(x => x === `#${run.t1} Call the printer ${run.who}`), `${tag}: Enter puts "#" and lists the own tasks ${JSON.stringify(m2)}`);
    await type('printer');
    const m3 = await until(`(() => { const l = ${acList}; return l && l.length === 1 ? l : null; })()`);
    check(m3 && m3[0] === `#${run.t1} Call the printer ${run.who}`, `${tag}: a title word filters the loaded tasks ${JSON.stringify(m3)}`);
    if (vw > 1000) await shot(`p2371_3_${vw}_task.png`);
    await press('Enter');
    check(await saved(`Start\n#${run.t1} `) === `Start\n#${run.t1} `, `${tag}: Enter puts "#${run.t1} " (saved)`);
    // a word only in a comment: the server's full-text search finds the task
    await press('Enter'); await type('/task'); await until(acList); await press('Enter');
    await type('zebrafinch');
    const m4 = await until(`(() => { const l = ${acList}; return l && l.some(x => x.startsWith('#${run.t2} ')) ? l : null; })()`);
    check(m4 && m4[0] === `#${run.t2} Order paper ${run.who}`, `${tag}: a word of a comment finds the task over the server's search ${JSON.stringify(m4)}`);
    await press('Enter');
    const w2 = `Start\n#${run.t1} \n#${run.t2} `;
    check(await saved(w2) === w2, `${tag}: the second pick saved (${JSON.stringify(await saved(w2))})`);
    // a "#" typed by hand opens no task search (a tag stays a tag)
    await type('#abc');
    check(!(await ev(acList)), `${tag}: "#abc" typed by hand opens no list`);
    await ev(`(() => { LS.del('wkEd'); return 1; })()`);
  });
  console.log(`p2371_3_wiki_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
