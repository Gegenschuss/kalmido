// 2.540.0 UI tests of part A (#4575 #4588): the overview of the spaces under "All workspaces" for the file store and
// kalmido-suite: fresh
// the views of Reading (as Knowledge does it). Own container (start.sh), jsdom, invented data only. freelancer-matrix: files, reading
// - #4575 the file store under "All": the top shows one row per space (Private, the organisation, Shared with me, the trash),
//   not silently the space remembered in abSpace; a tap opens it (#ablage/s/<space>), the path leads back to the overview,
//   abSpace is not written under "All"; with the panel folded (tablet width) the overview is in the view; one workspace
//   shown above = as before (no overview, its files)
// - #4588 Read later, Bookmarks, Feeds and Home & life under "All": the overview instead of the picker of #2677; a tap
//   opens the space (#<view>/s/<space>) with only its entries, the path back; one workspace shown = as before
// - a person without an organisation: one space, no overview anywhere
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const upload = async (ck, name, space) => {
  const fd = new FormData(); fd.append('file', new Blob(['text of ' + name]), name); fd.append('space', space);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};
const FEAT = 'cal,comments,collab,files,reading,feeds,travel';
const rows = d => [...d.querySelectorAll('#view .spov [data-spov]')].map(a => a.dataset.spov);
const ablageNames = d => [...d.querySelectorAll('#view .abrow .abname')].map(x => x.textContent).join('|');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  let CA = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal']}, CA);
  CA = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CA);
  const ORG = (await call('GET', '/api/state', null, CA)).me.workspaces[0].id, SP = 'org:' + ORG;
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CA);
  check(fu.status < 300, 'a person without an organisation ' + fu.status);
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CF);
  check(((await call('GET', '/api/state', null, CF)).me.workspaces || []).length === 0, 'P4: frida is in no organisation');
  await upload(CA, 'mine.txt', 'private'); await upload(CA, 'team.txt', SP); await upload(CF, 'frida.txt', 'private');
  check((await call('POST', '/api/reading', {url: 'https://example.com/mine', title: 'My long read', space: 'private'}, CA)).status < 300, 'a private read-later entry');
  check((await call('POST', '/api/reading', {url: 'https://example.com/team', title: 'Team article', space: SP}, CA)).status < 300, 'a read-later entry of the organisation');
  check((await call('POST', '/api/reading', {url: 'https://example.com/frida', title: 'Frida reads', space: 'private'}, CF)).status < 300, 'frida: a read-later entry');

  // ================= #4575 the file store under "All workspaces"
  let w = await boot({user: 'alice', hash: 'ablage', ls: {'tasks.abSpace': JSON.stringify(SP)}}), d = w.document;
  check(w.eval('wsCur()') === 'all' && w.eval('ab_all()'), '#4575: alice shows "All workspaces" with two spaces of her own');
  // 2.769.0 (#5352): a computer with the panel shows "Recently edited" in the view, not a second list of the spaces (the
  // panel lists them); a space opens from the panel / its address, the path leads back to the overview
  const ovr = () => !!d.querySelector('#view .zleov') && !rows(d).length;
  check(await until(ovr), '#4575 / #5352: the overview: "Recently edited", no second list of the spaces ' + rows(d).join('|'));
  check(JSON.stringify(w.eval(`ab_spaces()`)) === JSON.stringify(['private', SP, 'shared', 'trash']), '#4575: Private, the organisation, Shared with me, the trash (the panel)');
  check(!d.querySelector('#view .abrow') && !d.querySelector('#view .abcrumbs'), '#4575: not silently the remembered space (abSpace = the organisation; 2.769.0 #5352: its file may be listed under "Recently edited")');
  check(!d.querySelector('#side [data-absp][aria-current], #side .on[data-absp]'), '#4575: the panel marks no space on the overview');
  w.location.hash = 'ablage/s/' + SP;
  check(await until(() => w.location.hash === '#ablage/s/' + SP && /team\.txt/.test(ablageNames(d))), '#4575: the organisation opens, the address carries it ' + w.location.hash + ' ' + ablageNames(d));
  check(!/mine\.txt/.test(ablageNames(d)), '#4575: only the files of that space');
  check(d.querySelector('#view .abcrumbs [data-spovup]') && /Alpha/.test(d.querySelector('#view .abcrumbs').textContent), '#4575: the path "All workspaces / Alpha" above it');
  check(w.eval(`LS.get('abSpace', '')`) === SP && w.eval('AB.space') === SP, '#4575: under "All" abSpace is not written (still the old value)');
  d.querySelector('#view .abcrumbs [data-spovup]').click();
  check(await until(() => w.location.hash === '#ablage' && ovr()), '#4575: the path leads back to the overview ' + w.location.hash);
  w.location.hash = 'ablage/s/private';
  check(await until(() => w.location.hash === '#ablage/s/private' && /mine\.txt/.test(ablageNames(d)) && !/team\.txt/.test(ablageNames(d))), '#4575: Private opens with its files ' + ablageNames(d));
  w.history.back();
  check(await until(ovr), '#4575: the browser\'s Back returns to the overview');
  w.close();
  // an old address straight in
  w = await boot({user: 'alice', hash: 'ablage/s/' + SP}); d = w.document;
  check(await until(() => /team\.txt/.test(ablageNames(d))) && !rows(d).length, '#4575: #ablage/s/<organisation> opens the organisation directly');
  w.close();

  // the panel folded (a tablet width without the panel): the overview still shows in the view
  w = await boot({user: 'alice', hash: 'ablage', ls: {'tasks.sideFold': 'true'}}); d = w.document;
  check(await until(() => rows(d).length === 4) && w.eval('sbb_on()'), '#4575: panel folded: the spaces in the view (2.769.0, #5352: as chips above "Recently edited") ' + rows(d).join('|'));
  check(!d.querySelector('#view .abspaces'), '#4575: no bar of spaces next to it');
  w.close();
  // the phone: the overview too, no bar of spaces on top of it
  w = await boot({user: 'alice', hash: 'ablage', mobile: true}); d = w.document;
  check(await until(() => rows(d).length === 4) && !d.querySelector('#view .abspaces'), '#4575: the phone: the overview as the list');
  w.close();

  // one workspace shown above: as before
  await call('PATCH', '/api/settings', {workspace: 'private'}, CA);
  w = await boot({user: 'alice', hash: 'ablage'}); d = w.document;
  check(await until(() => /mine\.txt/.test(ablageNames(d))) && !rows(d).length && !d.querySelector('#view [data-spovup]'), '#4575: Private shown: its files, no overview, no path back ' + ablageNames(d));
  w.close();
  await call('PATCH', '/api/settings', {workspace: SP}, CA);
  w = await boot({user: 'alice', hash: 'ablage'}); d = w.document;
  check(await until(() => /team\.txt/.test(ablageNames(d))) && !rows(d).length, '#4575: the organisation shown: its files, no overview ' + ablageNames(d));
  w.close();

  // ================= #4588 Reading under "All workspaces"
  await call('PATCH', '/api/settings', {workspace: 'all'}, CA);
  w = await boot({user: 'alice', hash: 'reading'}); d = w.document;
  check(await until(() => rows(d).length === 2), '#4588: Read later: the overview of the spaces ' + rows(d).join('|'));
  check(JSON.stringify(rows(d)) === JSON.stringify(['private', SP]), '#4588: Private and the organisation ' + rows(d).join('|'));
  check(!d.querySelector('#view select') && !d.querySelector('#rl-url') && !d.querySelector('.rlrow'), '#4588: no picker (#2677 replaced), no mixed list');
  d.querySelector(`#view .spov [data-spov="${SP}"]`).click();
  check(await until(() => w.location.hash === '#reading/s/' + SP && /Team article/.test(d.querySelector('.rlview')?.textContent || '')), '#4588: a tap opens the organisation\'s list ' + w.location.hash);
  check(!/My long read/.test(d.querySelector('.rlview').textContent) && d.querySelector('#rl-url'), '#4588: only its entries, the link field there');
  check(d.querySelector('.rlview .spovc [data-spovup]') && /Alpha/.test(d.querySelector('.rlview .spovc').textContent), '#4588: the path back "All workspaces / Alpha"');
  d.querySelector('.rlview [data-spovup]').click();
  check(await until(() => w.location.hash === '#reading' && rows(d).length === 2), '#4588: back to the overview');
  d.querySelector('#view .spov [data-spov="private"]').click();
  check(await until(() => /My long read/.test(d.querySelector('.rlview')?.textContent || '') && !/Team article/.test(d.querySelector('.rlview').textContent)), '#4588: Private: only its entries');
  w.close();
  for (const [h, sel] of [['bookmarks', '#bm-url'], ['feeds', '.rsshead'], ['life', '.dash.life']]) {
    w = await boot({user: 'alice', hash: h}); d = w.document;
    check(await until(() => rows(d).length === 2) && !d.querySelector('#view select[aria-label="Workspace"]'), `#4588: #${h}: the overview, no picker ` + rows(d).join('|'));
    d.querySelector('#view .spov [data-spov="private"]').click();
    check(await until(() => w.location.hash === `#${h}/s/private` && d.querySelector('#view ' + sel) && !rows(d).length), `#4588: #${h}: a tap opens Private ` + w.location.hash);
    check(await until(() => d.querySelector('#view .spovc [data-spovup]') && !d.querySelector('#view .lempty')), `#4588: #${h}: the path back (also once loaded)`);
    w.close();
  }
  // one workspace shown above: as before
  await call('PATCH', '/api/settings', {workspace: SP}, CA);
  w = await boot({user: 'alice', hash: 'reading'}); d = w.document;
  check(await until(() => /Team article/.test(d.querySelector('.rlview')?.textContent || '')) && !rows(d).length && !d.querySelector('#view [data-spovup]'), '#4588: the organisation shown: its list as before, no overview');
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all'}, CA);

  // ================= a person without an organisation: one space, no overview
  w = await boot({user: 'frida', hash: 'ablage'}); d = w.document;
  check(await until(() => /frida\.txt/.test(ablageNames(d))) && !rows(d).length && !d.querySelector('#view [data-spovup]'), 'P4: the file store: her files, no overview ' + ablageNames(d));
  w.close();
  w = await boot({user: 'frida', hash: 'reading'}); d = w.document;
  check(await until(() => /Frida reads/.test(d.querySelector('.rlview')?.textContent || '')) && !rows(d).length && d.querySelector('#rl-url'), 'P4: Read later as before, no overview');
  w.close();
  w = await boot({user: 'frida', hash: 'life'}); d = w.document;
  check(await until(() => d.querySelector('#view .dash.life')) && !rows(d).length, 'P4: Home & life without an overview');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
