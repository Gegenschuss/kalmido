// 2.1165.0 part A UI test (#6114, #6115): uploading into the file store / the documents, and the trash of the file store
// kalmido-suite: fresh
// Own container (start.sh; P21165A_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom for the flows, Firefox for the delete in
// the file view (its way back is a real history step) and the drop frame. Invented names and files only.
// freelancer-matrix: frida has no organisation (her private space); rita reads / edits a folder of alice's
// #6114 - an upload with a good file, two empty ones (.mp4 / .wav, the open point of the walk-through) and one above the limit:
//         the good one goes up, ONE message "1 file uploaded · 3 not uploaded" with Undo, no "Uploading … files" toast besides
//         it, a list names the three and why (empty / larger than); the empty ones never reach the server; Undo takes the file
//         back; the form asks for the progress bar at any size (upWanted). Files dragged over the list: the frame says
//         "Drop here - lands in “<folder>”" - over a folder row its name. Documents: a .docx and an empty PDF stay out (the
//         button's kinds, the drop too) with the list, 52 files go in portions (all 52 added, none cut at 50).
// #6115 - the trash: a row opens its details read only ("In the trash", Restore, Preview; no new version, no Share); the
//         preview reads the content (content?trash=1, 404 without it and for others); a deleted file opened by its address
//         shows the same; Restore brings it back; the file store opens the workspace again after the trash was left (abSpace
//         never 'trash'); "Empty trash" only for whom something in it may be deleted (rita: no); the note in plain words.
//         Firefox: Delete in the file view goes back to the list WITH the message "… moved to the trash · Undo", still there
//         after 1,5 s; Undo brings the file back.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21165_a_files_ui', check, shots: 'P21165A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21165A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const upload = async (ck, name, data, form) => {
  const fd = new FormData(); fd.append('file', new Blob([data]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return ((await r.json()).items || [])[0]?.id;
};
const raw = async (ck, url) => (await fetch(B + url.replace(/^\//, ''), {headers: {'X-Requested-With': 'kalmido', Cookie: ck}})).status;
const FEATS = 'files,docs';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
// a drag of files from the computer onto el (jsdom has no DataTransfer: the event carries a plain stand-in)
const dragFiles = (w, el, type = 'dragover', files = []) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'dataTransfer', {value: {types: ['Files'], files, dropEffect: 'none', getData: () => ''}}); el.dispatchEvent(e); return e; };
// every text the toast showed (the check "no second message" needs the ones that were replaced)
const watchToasts = w => w.eval(`(() => { window.__toasts = []; const t = document.querySelector('#toast'); new MutationObserver(() => { if (!t.classList.contains('hidden')) window.__toasts.push(t.textContent); }).observe(t, {childList: true, subtree: true, characterData: true, attributes: true}); return 1; })()`);
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings?.features || '').split(','), ...FEATS.split(',')])].filter(Boolean).join(',');
  const ID = {};
  for (const name of ['frida', 'rita']) {
    const u = await call(CA, 'POST', '/api/users', {username: name, display_name: name[0].toUpperCase() + name.slice(1), password: 'password123', email: `${name}@example.com`, orgs: []});
    check(u.http < 300, `setup: ${name} ${u.http}`); ID[name] = u.id;
  }
  const FK = await login('frida'), RK = await login('rita');
  for (const ck of [CA, FK, RK]) await call(ck, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats, workspace: 'private'});
  check(((await call(FK, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const items = async (ck, q) => (await call(ck, 'GET', '/api/files?' + q)).items || [];
  let w, d;

  // ================= #6114 the upload: checked before sending, ONE message, the list of what stayed out
  const BOX = (await call(FK, 'POST', '/api/files/folders', {name: 'Drehorte', space: 'private'})).id;
  check(BOX, 'setup: frida\'s folder Drehorte');
  w = await boot({user: 'frida', hash: 'ablage', ls: {'tasks.abSpace': '"private"'}}); d = w.document;
  check(await until(() => d.querySelector(`#view .abrow[data-abid="${BOX}"]`)), 'frida: her private space shows the folder');
  check(w.eval(`(() => { const fd = new FormData(); fd.append('file', new File(['x'], 'x.txt')); const a = upWanted(fd); fd.upBar = true; return !a && upWanted(fd); })()`), 'a tiny form gets the progress bar when it asks for it (upBar)');
  watchToasts(w);
  w.eval('S.maxFileMb = 1');  // the limit of this check (the server's own stays)
  await w.eval(`ab_upload([new File(['Hallo Welt'], 'motiv.txt', {type: 'text/plain'}), new File([], 'leer.mp4', {type: 'video/mp4'}), new File([], 'leer.wav', {type: 'audio/wav'}),
    new File([new Uint8Array(1200 * 1024)], 'gross.bin')], null)`);
  const out = d.querySelector('#upbars .upout');
  check(out && /3 files were not uploaded/.test(txt(out)), 'the list says 3 files stayed out: ' + txt(out));
  check(out && /leer\.mp4 The file is empty/.test(txt(out)) && /leer\.wav The file is empty/.test(txt(out)), 'the empty .mp4 / .wav are named with "The file is empty"');
  check(out && /gross\.bin Larger than 1 MB/.test(txt(out)), 'the big one is named with "Larger than 1 MB"');
  check(await until(() => /1 file uploaded · 3 not uploaded/.test(txt(d.querySelector('#toast')))), 'ONE message at the end: ' + txt(d.querySelector('#toast')));
  check(/Undo/.test(d.querySelector('#toast button')?.textContent || ''), 'the message offers Undo');
  check(!w.__toasts.some(t => /Uploading \d+ file/.test(t)), 'no "Uploading … files" toast besides the bar: ' + JSON.stringify(w.__toasts));
  check(await until(() => [...d.querySelectorAll('#view .abrow .abname')].some(n => n.textContent === 'motiv.txt')), 'the good file is in the list');
  const names = (await items(FK, 'space=private')).map(x => x.name);
  check(names.includes('motiv.txt') && !names.some(n => /^leer\./.test(n) || n === 'gross.bin'), 'the server got the good file only: ' + names.join());
  const MOT = (await items(FK, 'space=private')).find(x => x.name === 'motiv.txt')?.id;
  d.querySelector('#toast button').click();
  check(await until(async () => (await items(FK, 'space=trash')).some(x => x.id === MOT)), 'Undo takes the upload back (the file in the trash)');
  check(await until(() => ![...d.querySelectorAll('#view .abrow .abname')].some(n => n.textContent === 'motiv.txt')), 'its row leaves the list');
  d.querySelector('#upbars .upout .upoutx').click();
  check(!d.querySelector('#upbars .upout'), 'the list closes with its x');
  // the drop frame says where the files land
  const view = d.querySelector('#view .abview');
  const e1 = dragFiles(w, d.querySelector('#view .abview .abmain'));
  check(e1.defaultPrevented && view.classList.contains('abdrop') && view.dataset.abdroptxt === 'Drop here - lands in “Private”', 'over the list: the frame "Drop here - lands in “Private”" ' + view.dataset.abdroptxt);
  dragFiles(w, d.querySelector(`#view .abrow[data-abid="${BOX}"] [data-abdrop]`));
  check(view.dataset.abdroptxt === 'Drop here - lands in “Drehorte”', 'over a folder row: its name ' + view.dataset.abdroptxt);
  const cssOk = w.eval(`[...document.styleSheets].some(s => { try { return [...s.cssRules].some(r => /abdroptxt/.test(r.selectorText || '')); } catch { return false; } })`);
  check(cssOk, 'the frame\'s text is drawn by the stylesheet (::after of data-abdroptxt)');
  w.close();

  // ================= #6114 the documents: the same check (the button's kinds, a drop too), portions instead of cutting at 50
  w = await boot({user: 'frida', hash: 'docs'}); d = w.document;
  check(await until(() => d.querySelector('.dc-bar #dc-file'), 80), 'frida: the documents are drawn');
  check(d.querySelector('#dc-file').getAttribute('accept') === w.eval('DC_ACCEPT'), 'the button offers the kinds of DC_ACCEPT');
  watchToasts(w);
  await w.eval(`dc_upload([new File(['Angebot Drehtag'], 'angebot.txt', {type: 'text/plain'}), new File(['PK'], 'vertrag.docx', {type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}), new File([], 'leer.pdf', {type: 'application/pdf'})])`);
  const dout = d.querySelector('#upbars .upout');
  check(dout && /vertrag\.docx This kind of file cannot be added here/.test(txt(dout)) && /leer\.pdf The file is empty/.test(txt(dout)), 'documents: the .docx and the empty PDF are named and why: ' + txt(dout));
  check(await until(() => /1 document added · 2 not uploaded/.test(txt(d.querySelector('#toast')))), 'documents: ONE message with the count: ' + txt(d.querySelector('#toast')));
  check(!w.__toasts.some(t => /Uploading/.test(t)), 'documents: no second message');
  // a drop takes the same kinds as the button
  dragFiles(w, d.querySelector('.dc-view'), 'drop', [new w.File(['PK'], 'liste.xlsx', {type: 'application/vnd.ms-excel'})]);
  check(await until(() => /liste\.xlsx This kind of file cannot be added here/.test(txt(d.querySelector('#upbars .upout')))), 'a drop: the same kinds as the button (the .xlsx stays out, named)');
  const many = await w.eval(`dc_upload(Array.from({length: 52}, (_, i) => new File(['Beleg Nummer ' + i], 'beleg-' + i + '.txt', {type: 'text/plain'})))`);
  check(Array.isArray(many) && many.length === 52, '52 documents at once: all 52 added (portions of 50, nothing cut) ' + (many && many.length));
  w.close();

  // ================= #6115 the trash of the file store
  const BRIEF = await upload(FK, 'brief.txt', 'Lieber Max, bis morgen am Set.');
  const BILD = await upload(FK, 'standbild.png', PNG);
  check(BRIEF && BILD, 'setup: a text and a picture');
  for (const id of [BRIEF, BILD]) await call(FK, 'DELETE', `/api/files/nodes/${id}`);
  check((await items(FK, 'space=trash')).filter(x => [BRIEF, BILD].includes(x.id)).length === 2, 'setup: both in the trash');
  check(await raw(FK, `/api/files/nodes/${BRIEF}/content`) === 404, 'server: a file in the trash stays 404 without trash=1');
  check(await raw(FK, `/api/files/nodes/${BRIEF}/content?trash=1`) === 200, 'server: trash=1 reads it for its owner');
  check(await raw(RK, `/api/files/nodes/${BRIEF}/content?trash=1`) === 404, 'server: trash=1 gives nothing to another person');
  // (2) by its address: "In the trash" + Restore, no new version, no Share
  w = await boot({user: 'frida', hash: 'ablage/' + BRIEF, ls: {'tasks.abSpace': '"private"'}}); d = w.document;
  let dlg = await until(() => d.querySelector('.abtrdlg'));
  check(dlg && /In the trash/.test(txt(dlg.querySelector('.abtrashed'))) && dlg.querySelector('.abtrashed [data-abd="restore"]'), 'its address: "In the trash" with Restore on top ' + txt(dlg));
  check(dlg && !dlg.querySelector('[data-abd="ver"], [data-abd="share"], [data-abd="open"]') && !/Upload a new version|Share…/.test(txt(dlg)), 'no Upload a new version / Share / Open of a living file');
  dlg.querySelector('[data-abd="see"]').click();
  check(await until(() => /Lieber Max, bis morgen am Set\./.test(txt(d.querySelector('.tview')))), 'Preview shows the text (read only) ' + txt(d.querySelector('.tview')).slice(0, 80));
  d.querySelector('.tview')?.remove();
  dlg.querySelector('[data-abd="restore"]').click();
  check(await until(async () => !(await items(FK, 'space=trash')).some(x => x.id === BRIEF)), 'Restore brings it back');
  check(await until(() => !d.querySelector('.abtrdlg')), 'the dialog closes');
  w.close();
  // (3) (4) (5) the trash itself
  w = await boot({user: 'frida', hash: 'ablage', ls: {'tasks.abSpace': '"private"'}}); d = w.document;
  check(await until(() => d.querySelector(`#view .abrow[data-abid="${BOX}"]`)), 'frida: the private space');
  w.eval(`(() => { ab_pick('trash'); AB.key = ''; ab_load(); return 1; })()`);  // what the space button / the panel's Trash do
  check(await until(() => d.querySelector(`#view .abrow[data-abid="${BILD}"] [data-ab="tropen"]`)), 'the trash: its row can be opened');
  check(w.localStorage.getItem('tasks.abSpace') === '"private"', 'the trash is not remembered (abSpace stays private) ' + w.localStorage.getItem('tasks.abSpace'));
  check(d.querySelector('#view [data-ab="trash-empty"]'), 'frida (owner): "Empty trash"');
  const note = txt(d.querySelector('#view .abtrashdays'));
  check(/^Deleted items stay here (for \d+ days?, then they are gone for good|until you delete them permanently)\.$/.test(note), 'the note in plain words: ' + note);
  d.querySelector(`#view .abrow[data-abid="${BILD}"] [data-ab="tropen"]`).click();
  dlg = await until(() => d.querySelector('.abtrdlg'));
  check(dlg && /standbild\.png/.test(txt(dlg)) && /In the trash/.test(txt(dlg)), 'a tap on the row: its details ' + txt(dlg));
  const img = dlg?.querySelector('.abtrimg img');
  check(img && /\/content\?trash=1$/.test(img.getAttribute('src')), 'the picture right there (content?trash=1)');
  check(dlg && !dlg.querySelector('[data-abd="ver"], [data-abd="share"]'), 'read only: no new version, no Share');
  dlg.querySelector('[data-m="close"]').click();
  w.location.hash = '#docs';
  check(await until(() => w.eval('S.route.mod') !== 'ablage'), 'another area');
  w.location.hash = '#ablage';
  check(await until(() => w.eval('S.route.mod') === 'ablage' && w.eval('ab_curSpace()') === 'private' && d.querySelector(`#view .abrow[data-abid="${BOX}"]`)), '"Files" again: the workspace, not the trash ' + w.eval('ab_curSpace()'));
  w.close();
  // rita: edits a folder of alice's, puts its file into the trash - she may restore it, not delete it for good
  const SH = (await call(CA, 'POST', '/api/files/folders', {name: 'Gemeinsam', space: 'private'})).id;
  const SF = await upload(CA, 'drehplan.txt', 'Drehplan', {parent_id: String(SH)});
  check((await call(CA, 'POST', `/api/files/nodes/${SH}/shares`, {user_id: ID.rita, role: 'edit'})).http < 300, 'setup: Gemeinsam shared with rita to edit');
  check((await call(RK, 'DELETE', `/api/files/nodes/${SF}`)).http < 300, 'setup: rita puts drehplan.txt into the trash');
  w = await boot({user: 'rita', hash: 'ablage', ls: {'tasks.abSpace': '"trash"'}}); d = w.document;
  check(await until(() => w.eval('ab_curSpace()') === 'private'), 'an old abSpace "trash" opens the workspace');
  w.eval(`(() => { ab_pick('trash'); AB.key = ''; ab_load(); return 1; })()`);
  check(await until(() => d.querySelector(`#view .abrow[data-abid="${SF}"]`)), 'rita: her trash shows drehplan.txt');
  check(d.querySelector(`#view .abrow[data-abid="${SF}"] [data-ab="restore"]`) && !d.querySelector('#view [data-ab="trash-empty"]'), 'rita: Restore, but no "Empty trash" (nothing she may delete for good)');
  w.close();
  // review (job/4506): content?trash=1 reads only for who may restore it (as the details): a share that stays on a file alice
  // deleted reads nothing of it; rita's own deleted file she reads
  const SF2 = await upload(CA, 'gage.txt', 'Gage nur fuer alice', {parent_id: String(SH)});
  check((await call(CA, 'DELETE', `/api/files/nodes/${SF2}`)).http < 300, 'setup: alice puts gage.txt into the trash');
  check(await raw(RK, `/api/files/nodes/${SF2}/content?trash=1`) === 404, 'server: rita (edit share) reads nothing of a file alice deleted');
  check(await raw(RK, `/api/files/nodes/${SF2}/content?trash=1&v=1`) === 404, 'server: nor an old version of it');
  check(await raw(RK, `/api/files/nodes/${SF}/content?trash=1`) === 200, 'server: rita reads the file she put into the trash');

  // ================= Firefox: Delete in the file view keeps its message with Undo; the drop frame as a picture
  const DEL = await upload(FK, 'notiz-set.txt', 'Notiz vom Set');
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.abSpace', '"private"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await o.nav(B + '#ablage');
    check(await wait(`!!document.querySelector('#view .abrow[data-abid="${DEL}"] [data-ab="open"]')`), 'ff: the list shows notiz-set.txt');
    // the drop frame (a real DataTransfer with a file)
    await ev(`(() => { const dt = new DataTransfer(); dt.items.add(new File(['x'], 'neu.txt', {type: 'text/plain'})); document.querySelector('#view .abview .abmain').dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: dt})); return 1; })()`);
    check(await wait(`getComputedStyle(document.querySelector('#view .abview.abdrop'), '::after').content.includes('Drop here - lands in')`), 'ff: the frame shows "Drop here - lands in …"');
    await shot('p21165a-drop-frame.png');
    await ev(`(() => { document.querySelectorAll('.abdrop').forEach(x => x.classList.remove('abdrop')); return 1; })()`);
    // the file view: Delete
    await ev(`(() => { document.querySelector('#view .abrow[data-abid="${DEL}"] [data-ab="open"]').click(); return 1; })()`);
    check(await wait(`location.hash === '#ablage/${DEL}' && !!document.querySelector('.dv-view [data-dc="del"]')`), 'ff: the file view with Delete');
    await ev(`(() => { document.querySelector('.dv-view [data-dc="del"]').click(); return 1; })()`);
    check(await wait(`location.hash !== '#ablage/${DEL}' && !document.querySelector('.dv-view') && /notiz-set\\.txt” moved to the trash/.test(document.querySelector('#toast:not(.hidden)')?.textContent || '')`), 'ff: back at the list with "… moved to the trash"');
    await sleep(1500);  // the walk-through's probe: still there after 1,5 s (the message's own time is 6 s)
    check(await ev(`/moved to the trash/.test(document.querySelector('#toast:not(.hidden)')?.textContent || '') && /Undo/.test(document.querySelector('#toast:not(.hidden) button')?.textContent || '')`), 'ff: after 1,5 s the message with Undo is still there');
    await shot('p21165a-view-delete-toast.png');
    await ev(`(() => { document.querySelector('#toast button').click(); return 1; })()`);
    check(await until(async () => !(await items(FK, 'space=trash')).some(x => x.id === DEL)), 'ff: Undo brings the file back');
  });

  console.log(`p21165_a_files_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: exception', e); process.exit(1); });
