// 2.113.1 UI tests, part B (#2059): team chat channels, groups and files, own container (start.sh). jsdom:
// the conversation list with the sections Channels / Groups / Lists and direct messages; "+" offers New channel, New group,
// Browse channels; the dialogs create a channel (name, workspace, open, invited people) and a group; a channel's head has
// its settings (members, rename); the paperclip, files waiting in the box (remove one), sending them (multipart) and the
// message's files (thumbnail -> lightbox, file tile); an archived channel shows "archived" + Restore instead of the box.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2113BB_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  const st0 = await call('GET', '/api/state'), feats = new Set(((st0.settings || {}).features || '').split(',').filter(Boolean)); feats.add('collab');
  const FEAT = [...feats].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const ids = {};
  for (const u of ['bob', 'carol']) ids[u] = (await call('POST', '/api/users', {orgs: [ORG], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const L = (await call('POST', '/api/lists', {name: 'Team', org_id: ORG})).id;
  for (const u of [ids.bob, ids.carol]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  const GEN = (await call('POST', '/api/team/channels', {name: 'General', org_id: ORG, open: true, members: [ids.bob]})).id;
  check(GEN > 0, 'a channel to start with');
  // bob sends two files (multipart)
  const fd = new FormData(); fd.append('body', 'Look at these');
  fd.append('file', new Blob([PNG], {type: 'image/png'}), 'shot.png'); fd.append('file', new Blob(['some notes'], {type: 'text/plain'}), 'notes.txt');
  const M1 = await (await fetch(B + `api/team/rooms/${GEN}/messages`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: BCK}, body: fd})).json();
  check((M1.attachments || []).length === 2, 'bob\'s message with two files ' + JSON.stringify(M1).slice(0, 200));
  const GRP = (await call('POST', '/api/team/groups', {members: [ids.bob, ids.carol]})).id;
  await call('POST', `/api/team/rooms/${GRP}/messages`, {body: 'Lunch?'}, BCK);

  // ================= the list, the sections, "+"
  {
    const w = await boot({user: 'alice', hash: 'team'}), d = w.document;
    await until(() => w.eval('S.tc.rooms && S.tc.rooms.length'));
    if (!d.querySelector('.tclist .tcrow')) w.eval('renderView()');  // jsdom: the first list may still say "Loading…"
    await until(() => d.querySelector(`.tclist .tcrow[data-rid="${GEN}"]`));
    const secs = [...d.querySelectorAll('.tclist .tcsec')].map(x => x.textContent);
    check(secs.join('|') === 'Channels|Groups', 'list: the sections (the quiet list channel stays hidden as before) ' + secs.join('|'));
    const gr = d.querySelector(`.tclist .tcrow[data-rid="${GEN}"]`), gg = d.querySelector(`.tclist .tcrow[data-rid="${GRP}"]`);
    check(gr && /General/.test(gr.textContent) && gr.querySelector('.tcico svg'), 'list: the channel row with its symbol');
    check(gg && /Bob, Carol/.test(gg.textContent) && /Lunch\?/.test(gg.textContent), 'list: the group named after its members, its last message ' + (gg?.textContent || '').trim().slice(0, 80));
    click(w, d.querySelector('.tchead [data-act="tc-new"]')); await until(() => d.querySelector('#pop [role="menuitem"]'));
    const items = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
    check(items.includes('New channel') && items.includes('New group') && items.includes('Browse channels'), '"+": New channel, New group, Browse channels ' + items.join('|'));
    w.eval('closePop()');
    // a new channel through the dialog
    w.eval('tcx_chanNew()'); await until(() => d.querySelector('.modal .tcxdlg #tcx-mem input'));
    const md = d.querySelector('.modal .tcxdlg');
    check(md.querySelector('#tcx-open')?.checked && md.querySelector(`#tcx-mem input[value="${ids.bob}"]`), 'dialog: open by default in the organisation, bob to invite');
    md.querySelector('#tcx-name').value = 'Design';
    md.querySelector(`#tcx-mem input[value="${ids.bob}"]`).checked = true;
    md.querySelector('#tcx-open').checked = false;
    md.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
    const des = await until(async () => (await call('GET', '/api/team/channels')).channels.find(c => c.name === 'Design'));
    check(des && des.open === false && des.members === 2, 'dialog: the channel exists, invited only, with bob ' + JSON.stringify(des));
    await until(() => w.location.hash === '#team/' + des?.id);
    check(w.location.hash === '#team/' + des?.id, 'dialog: the new channel opens ' + w.location.hash);
    // a group through the dialog
    w.eval('tcx_groupNew()'); await until(() => d.querySelector('.modal .tcxdlg .tcxpick'));
    const gd = d.querySelector('.modal .tcxdlg');
    for (const u of [ids.bob, ids.carol]) gd.querySelector(`.tcxpick input[value="${u}"]`).checked = true;
    gd.querySelector('#tcx-name').value = 'Planning';
    gd.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
    const g2 = await until(async () => (await call('GET', '/api/team')).rooms.find(x => x.kind === 'group' && x.name === 'Planning'));
    check(g2 && g2.members === 3, 'dialog: the group "Planning" with bob and carol');
    await until(() => w.location.hash === '#team/' + g2?.id); await sleep(300);
    check(w.location.hash === '#team/' + g2?.id, 'dialog: the new group opens');
    check(!errs.length, `list: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }
  // ================= a channel: files, the box, the settings
  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'alice', mobile, hash: 'team/' + GEN}), d = w.document;
    await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${M1.id}"] .chatts`));
    const m = d.querySelector(`#tc-msgs .cmsg[data-mid="t:${M1.id}"]`);
    check(m?.querySelector('.chatts .att.img img')?.getAttribute('src').startsWith(`/api/team/files/${M1.attachments[0].id}?v=`)
      && /notes\.txt/.test(m.querySelector('.chatts .att.file')?.textContent || ''), `${tag}: the image as thumbnail, the text file as tile`);
    click(w, m.querySelector('[data-act="tc-att-view"]')); await sleep(50);
    check(d.querySelector('.lightbox img')?.getAttribute('src').startsWith(`/api/team/files/${M1.attachments[0].id}`), `${tag}: the thumbnail opens the lightbox`);
    d.querySelector('.lightbox')?.remove();
    const clip = d.querySelector('.tccomp [data-act="tc-attach"]');
    check(clip && clip.getAttribute('aria-label') === 'Attach images or files' && d.querySelector('.tccomp #tc-file[type="file"][multiple]'), `${tag}: paperclip + file input`);
    check(d.querySelector('.tcrhead [data-act="tc-set"]'), `${tag}: the channel settings in the head`);
    w.eval(`tcx_addFiles([new File(['a'], 'one.txt', {type: 'text/plain'}), new File(['b'], 'two.txt', {type: 'text/plain'})])`);
    check(d.querySelectorAll('#tc-files .cfile').length === 2, `${tag}: two files wait in the box`);
    click(w, d.querySelector('#tc-files [data-act="tc-file-rm"][data-i="0"]'));
    check(d.querySelectorAll('#tc-files .cfile').length === 1 && /two\.txt/.test(d.querySelector('#tc-files').textContent), `${tag}: removing one keeps the other`);
    if (!mobile) {
      d.querySelector('#tc-in').value = 'Here it is';
      w.eval('tcSend()');
      const sent = await until(async () => (await call('GET', `/api/team/rooms/${GEN}/messages`)).messages.find(x => x.body === 'Here it is'));
      check(sent && (sent.attachments || []).map(a => a.name).join() === 'two.txt', `${tag}: sent with the file ` + JSON.stringify(sent || {}).slice(0, 200));
      await until(() => !d.querySelector('#tc-files .cfile'));
      check(!d.querySelector('#tc-files .cfile'), `${tag}: the box is empty after sending`);
      // the settings
      click(w, d.querySelector('.tcrhead [data-act="tc-set"]'));
      await until(() => d.querySelector('#tcx-set .tcxmem'));
      const st = d.querySelector('#tcx-set');
      check(/Channel settings/.test(st.textContent) && st.querySelectorAll('.tcxmem .tcxrow').length >= 2 && st.querySelector('#tcx-name')?.value === 'General'
        && st.querySelector('[data-xs="archive"]'), `${tag}: settings with name, members, archive`);
      st.querySelector('#tcx-name').value = 'General chat';
      st.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
      const rn = await until(async () => (await call('GET', '/api/team/channels')).channels.find(c => c.id === GEN && c.name === 'General chat'));
      check(!!rn, `${tag}: renamed in the settings`);
      d.querySelector('.modal')?.remove();
    }
    check(!errs.length, `${tag}: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }
  // ================= an archived channel
  {
    const DES = (await call('GET', '/api/team/channels')).channels.find(c => c.name === 'Design').id;
    await call('PATCH', `/api/team/rooms/${DES}`, {archived: true});
    const w = await boot({user: 'alice', hash: 'team/' + DES}), d = w.document;
    await until(() => d.querySelector('.tcarch'));
    check(d.querySelector('.tcarch [data-act="tc-restore"]') && !d.querySelector('#tc-in'), 'archived: notice + Restore, no message box');
    click(w, d.querySelector('.tcarch [data-act="tc-restore"]'));
    const back = await until(async () => (await call('GET', '/api/team/channels')).channels.find(c => c.id === DES && !c.archived));
    check(!!back, 'archived: Restore brings it back');
    await until(() => d.querySelector('#tc-in'));
    check(d.querySelector('#tc-in'), 'archived: the message box is back after restoring');
    check(!errs.length, `archived: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }

  console.log(`p2113b_b_ui: ${ok} ok, ${F.length} failed`);
  execFileSync('docker', ['rm', '-f', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test'], {stdio: 'ignore'});
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
