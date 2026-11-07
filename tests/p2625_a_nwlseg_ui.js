// 2.625.0 A test (#4486): a newsletter segment is chosen with condition rows (what / is | is not / value). Own container
// kalmido-suite: fresh
// (start.sh with the fake newsletter services inside it), jsdom + API, invented names, addresses @example.com.
// freelancer-matrix: newsletter (frida has no organisation: the newsletter of her own space)
// - server: an old segment (tags / companies / books) is stored, answered and counted exactly as before (no new keys); the
//   exclusions not_tags / not_companies / not_books take contacts out; a book of another space is refused there too
// - the sheet: an old segment opens as one "is" row per kind with its values and saves the same rule; a new segment with
//   "Group is VIP" + "Group is not Press" saves {tags: [VIP], not_tags: [Press]} and counts the same contacts as the server rule
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore',
  env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8086 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='}});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { /* no body */ } return {...(j || {}), http: r.status}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
for (const f of ['nl.json', 'nl.log']) { try { fs.unlinkSync(path.join(DATA, f)); } catch { /* none */ } }
fs.copyFileSync(path.join(__dirname, 'fake_newsletter.py'), path.join(DATA, 'fake_newsletter.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_newsletter.py']);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['contacts']}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FK = await login('frida');
  const st = await call('GET', '/api/state', null, FK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private', features: [...new Set([...(st.settings?.features || '').split(','), 'contacts'])].filter(Boolean).join(',')}, FK);
  check(!((await call('GET', '/api/state', null, FK)).me.workspaces || []).length, 'frida has no organisation');
  const bk = await call('POST', '/api/books', {name: 'Customers'}, FK);
  const other = await call('POST', '/api/books', {name: 'Alice book'}, CK);
  const mk = async (fn, groups, org) => (await call('POST', '/api/contacts', {book_id: bk.id, fn, groups, org, emails: [{value: fn.split(' ')[0].toLowerCase() + '@example.com'}]}, FK)).id;
  await mk('Anna Alpha', ['VIP'], 'Firm One');
  await mk('Ben Beta', ['VIP', 'Press'], '');
  await mk('Cleo Gamma', ['Press'], 'Firm Two');
  await mk('Dora Delta', [], 'Firm One');
  const cn = await call('PUT', '/api/newsletter', {ws: 'private', kind: 'listmonk', url: 'http://127.0.0.1:8086', user: 'lmuser', token: 'lm-secret-token-1234'}, FK);
  check(cn.http === 200, `frida connects her own newsletter service (${cn.http})`);

  // ---- server: the old format stays, the exclusions count
  const seg = async (name, rule) => { const r = await call('POST', '/api/newsletter/segments', {ws: 'private', name, rule, create_list: true}, FK); return {r, s: (r.segments || []).find(x => x.id === r.segment_id)}; };
  const old = await seg('Old VIP', {tags: ['VIP'], companies: [], books: [bk.id]});
  check(old.r.http < 300 && JSON.stringify(old.s?.rule) === JSON.stringify({tags: ['VIP'], companies: [], books: [bk.id]}), `an old segment keeps its rule as it was ${JSON.stringify(old.s?.rule)}`);
  check(old.s?.counts?.match === 2, `old segment: Anna and Ben (${old.s?.counts?.match})`);
  const ex = await seg('VIP no press', {tags: ['VIP'], companies: [], books: [], not_tags: ['press']});
  check(ex.r.http < 300 && JSON.stringify(ex.s?.rule?.not_tags) === '["press"]', `the exclusion is stored ${JSON.stringify(ex.s?.rule)}`);
  check(ex.s?.counts?.match === 1, `VIP but not Press: only Anna (${ex.s?.counts?.match})`);
  const exc = await seg('Not Firm One', {tags: [], companies: [], books: [], not_companies: ['firm one']});
  check(exc.s?.counts?.match === 2, `not at Firm One: Ben and Cleo, a contact without a company stays (${exc.s?.counts?.match})`);
  const exb = await seg('Not Customers', {tags: [], companies: [], books: [], not_books: [bk.id]});
  check(exb.s?.counts?.match === 0, `not in the only book: nobody (${exb.s?.counts?.match})`);
  check((await seg('Foreign', {tags: [], companies: [], books: [], not_books: [other.id]})).r.http === 400, 'an excluded book of another space is refused');
  check((await seg('Bad', {tags: [], not_tags: 'VIP'})).r.http === 400, 'an exclusion that is no list is refused');
  check(!('not_tags' in (old.s?.rule || {})) && !('not_books' in (exc.s?.rule || {})), 'empty exclusions are not stored');

  // ---- the sheet
  const w = await boot({user: 'frida', hash: 'contacts'}), d = w.document;
  await until(() => w.eval('S.booted && typeof loadModule === "function"'), 60);
  await w.eval(`loadModule('contacts').then(() => { nwl_open(); return 1; })`);
  const body = () => d.querySelector('.modal.nwl-md .nwl-body');
  await until(() => body()?.querySelector(`[data-nwl="seg-edit"][data-sid="${old.s?.id}"]`));
  check(/Without groups: press/.test(body()?.textContent || ''), 'the list of segments names the exclusion');
  // an old segment opens as rows
  click(w, body().querySelector(`[data-nwl="seg-edit"][data-sid="${old.s.id}"]`));
  const sm = await until(() => d.querySelector('.nwl-smd .nwl-conds .fcond') && d.querySelector('.nwl-smd'));
  const rows = () => [...sm.querySelectorAll('.nwl-conds .fcond')];
  check(sm && !sm.querySelector('.nwl-chips'), 'the sheet has condition rows, no buttons per group');
  check(rows().length === 2 && rows()[0].querySelector('.fc-f').value === 'tags' && rows()[0].querySelector('.fc-op').value === 'is' && /VIP/.test(rows()[0].querySelector('.fc-v').textContent),
    'old segment: the row "Group is VIP"');
  check(rows()[1].querySelector('.fc-f').value === 'books' && /Customers/.test(rows()[1].querySelector('.fc-v').textContent), '… and the row "Address book is Customers"');
  check([...rows()[0].querySelectorAll('.fc-op option')].map(o => o.textContent.trim()).join('|') === 'is|is not', 'the comparisons: is / is not');
  check([...rows()[0].querySelectorAll('.fc-f option')].map(o => o.value).join(',') === 'tags,companies,books', 'what: group, company, address book');
  await until(() => sm.querySelector('#ns-list option[value="__new"]'));
  click(w, sm.querySelector('[data-ns="save"]'));
  await until(() => !d.querySelector('.nwl-smd'));
  const s1 = (await call('GET', '/api/newsletter?ws=private', null, FK)).segments.find(x => x.id === old.s.id);
  check(JSON.stringify(s1?.rule) === JSON.stringify(old.s.rule) && s1?.counts?.match === 2, `saved unchanged: the same rule, the same contacts ${JSON.stringify(s1?.rule)}`);

  // a new segment from rows: Group is VIP, Group is not Press
  click(w, await until(() => body()?.querySelector('[data-nwl="seg-new"]')));
  const nm = await until(() => d.querySelector('.nwl-smd'));
  check(nm && !nm.querySelector('.fcond'), 'a new segment starts without a row');
  nm.querySelector('#ns-name').value = 'VIP rows';
  const pick = async (i, label) => {
    click(w, rows2()[i].querySelector('.fc-v'));
    const p = await until(() => d.querySelector('#pop:not(.hidden) [role="menuitemcheckbox"]') && d.querySelector('#pop'));
    click(w, p && [...p.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === label));
    w.eval('closePop()');
  };
  const rows2 = () => [...nm.querySelectorAll('.nwl-conds .fcond')];
  click(w, nm.querySelector('[data-ns="cond-add"]'));
  check(rows2().length === 1 && rows2()[0].querySelector('.fc-f').value === 'tags', '"+ Condition" adds a row');
  await pick(0, 'VIP');
  check(/VIP/.test(rows2()[0].querySelector('.fc-v').textContent), 'the value menu picks VIP');
  click(w, nm.querySelector('[data-ns="cond-add"]'));
  change(w, rows2()[1].querySelector('.fc-f'), 'tags');
  change(w, rows2()[1].querySelector('.fc-op'), 'isnot');
  await pick(1, 'Press');
  await until(() => nm.querySelector('#ns-list option[value="__new"]'));
  click(w, nm.querySelector('[data-ns="save"]'));
  await until(() => !d.querySelector('.nwl-smd'));
  const s2 = (await call('GET', '/api/newsletter?ws=private', null, FK)).segments.find(x => x.name === 'VIP rows');
  check(JSON.stringify(s2?.rule) === JSON.stringify({tags: ['VIP'], companies: [], books: [], not_tags: ['Press']}), `the rows are saved as the rule ${JSON.stringify(s2?.rule)}`);
  check(s2?.counts?.match === 1, `… and hit the same contact as the server rule: Anna (${s2?.counts?.match})`);

  // reopening shows the exclusion row; removing it saves the old format again
  click(w, await until(() => body()?.querySelector(`[data-nwl="seg-edit"][data-sid="${s2?.id}"]`)));
  const em = await until(() => d.querySelector('.nwl-smd .nwl-conds .fcond') && d.querySelector('.nwl-smd'));
  const r3 = () => [...em.querySelectorAll('.nwl-conds .fcond')];
  check(r3().length === 2 && r3()[1].querySelector('.fc-op').value === 'isnot' && /Press/.test(r3()[1].querySelector('.fc-v').textContent), 'reopened: the row "Group is not Press"');
  click(w, r3()[1].querySelector('.fc-x'));
  await until(() => em.querySelector('#ns-list option'));
  click(w, em.querySelector('[data-ns="save"]'));
  await until(() => !d.querySelector('.nwl-smd'));
  const s3 = (await call('GET', '/api/newsletter?ws=private', null, FK)).segments.find(x => x.id === s2?.id);
  check(JSON.stringify(s3?.rule) === JSON.stringify({tags: ['VIP'], companies: [], books: []}) && s3?.counts?.match === 2, `without the row: the old format, Anna and Ben ${JSON.stringify(s3?.rule)}`);
  w.close();

  console.log(`p2625_a_nwlseg_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
