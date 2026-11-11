// 2.910.0 UI test (#5442 dialogs alike, #5444 list errors in plain words, #5445 quick add shows each part once; built before in
// 2.788 / 2.820 / 2.893, never live): own container (start.sh), jsdom + Firefox (1440 px and phone 390 px). Invented data only.
// kalmido-suite: fresh
// freelancer-matrix: n/a (no new route; alice and bruno have no organisation, every check runs without one)
// P2910A_NOSTART=1 = the container runs.
// - #5442: dialogs that save by themselves close with "Done" (also as a sub-dialog: no "Back"), pure choices with "Close",
//   forms with "Cancel" + the main button on the right, Cancel right next to it; the date picker sits on the shared key stack:
//   Escape closes only the picker, the dialog stays, the focus goes back to its field button; the Share dialog of a project is
//   built from the shared frame (cross, parts, "… settings…" | "Done") and keeps its height while it loads (Firefox; the folder's
//   dialog follows in #5587); a member
//   who cannot manage opens Share with agents around (regression: the template asked a helper defined only after it)
// - 2.913.0 (#5587): the folder's Share dialog on the same frame: opened from the folder settings it says "Done" (was "Back"),
//   its people show up (no Loading left), the folder's role question = "Only new projects" left, Cancel + "Set everywhere"
//   right; the task choice of the multi-selection (dgPick) closes with "Close" and lists the tasks; Firefox: the folder's
//   Share dialog keeps its height while it loads like the project's
// - #5445: "Logo approve tomorrow !high #client" in the docked composer shows the day once (its chip, no second parser chip),
//   the priority once, the tag as its chip; the syntax help leaves once something is recognised and comes back for an empty
//   field; the small x after the date chip = "don't recognise"; the phone sheet shows the title in front of its chips
// - #5444 (bruno: no organisation, German): ticking off a task the server refuses (500 "Testfehler") says "Erledigt konnte
//   nicht gespeichert werden (Testfehler)" and the circle is empty again; a refused reorder says the task is back in its place;
//   offline the comments, the dependencies and the status history say the one sentence
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2910_a_ui', check, shots: 'P2910A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2910A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const callAs = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
let CK;
const call = (method, url, body) => callAs(CK, method, url, body);
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  const CA = CK;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const WORK = (await call('POST', '/api/lists', {name: 'Workshop', kind: 'project', folder: 'Studio'})).id;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('POST', '/api/users', {username: 'bruno', display_name: 'Bruno', password: 'password123', email: 'bruno@example.com', orgs: []});
  const CB = await login('bruno');
  await callAs(CB, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
  check(!((await callAs(CB, 'GET', '/api/state')).me?.workspaces || []).length, 'bruno: no organisation (freelancer)');
  const CBo = await login('bob');
  await callAs(CBo, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const UBo = (await callAs(CBo, 'GET', '/api/state')).me;
  await call('PUT', `/api/lists/${WORK}/members`, {user_id: UBo.id, role: 'edit'});
  await call('POST', '/api/tasks', {title: 'Sand the boards', list_id: WORK});
  const TID = (await call('POST', '/api/tasks', {title: 'Paint the hull', list_id: WORK})).id;
  check(WORK && TID && UBo?.id, 'set-up: a project in a folder, two tasks, bob as a member');

  let w = await boot({user: 'alice', hash: 'l/' + WORK}), d = w.document;
  await until(() => d.querySelector('#view .trow'));
  // ================= #5442 (jsdom): the words and the order of the dialog buttons
  const foot = m => [...(m?.querySelectorAll('.foot .btn') || [])].map(b => txt(b));
  const open = async (js, sel) => { w.eval(js); return until(() => d.querySelector(sel)?.closest('.modal')); };
  const shut = () => d.querySelectorAll('.modal').forEach(m => m.remove());
  let md = await open(`shareModal(${WORK})`, '.modal.shmodal [data-m="list-edit"]');
  check(md && md.querySelector('.lhdr [data-m="close"]') && JSON.stringify(foot(md)) === JSON.stringify(['Project settings…', 'Done']), '#5442: project Share: cross in the head, "Project settings…" | "Done" ' + JSON.stringify(foot(md)));
  // from there into the project settings and back: both say "Done" (no "Back" any more)
  md.querySelector('[data-m="list-edit"]').click();
  let le = await until(() => [...d.querySelectorAll('.modal')].find(m => m.querySelector('[data-m="share-open"]') && m.style.display !== 'none'));
  check(le && txt(le.querySelector('.foot .btn.pri')) === 'Done' && !/Back/.test(txt(le.querySelector('.foot'))), '#5442: project settings as a sub-dialog close with "Done" ' + txt(le?.querySelector('.foot')));
  le?.querySelector('[data-m="share-open"]').click();
  md = await until(() => [...d.querySelectorAll('.modal.shmodal')].find(m => m.style.display !== 'none'));
  check(md && txt(md.querySelector('.foot .btn.pri')) === 'Done', '#5442: ... and the Share dialog again "Done"');
  shut();
  md = await open(`folderShareModal('Studio')`, '.modal.fshmodal [data-m="fsh-props"]');
  check(md && md.querySelector('.lhdr [data-m="close"]') && JSON.stringify(foot(md)) === JSON.stringify(['Folder settings…', 'Done']), '#5442: folder Share: cross in the head, "Folder settings…" | "Done" ' + JSON.stringify(foot(md)));
  check(md && md.querySelector('#fsh-sec-own.shsec > summary h4#fsh-own-h') && md.querySelector('#fp-sec-ntf.shsec'), '#5442: folder Share: the shared folded parts keep their ids');
  md.querySelector('[data-m="fsh-props"]').click();
  le = await until(() => [...d.querySelectorAll('.modal.fsmodal')].find(m => m.style.display !== 'none'));
  check(le && txt(le.querySelector('.foot .btn.pri')) === 'Done', '#5442: folder settings as a sub-dialog close with "Done" ' + txt(le?.querySelector('.foot')));
  shut();
  // 2.913.0 (#5587): the folder settings on their own -> "Share…": the folder's Share dialog as a sub-dialog says "Done" too
  // (was "Back"), with its people shown
  le = await open(`folderPropsModal('Studio')`, '.modal.fsmodal [data-m="people"]');
  le?.querySelector('.foot [data-m="people"]').click();
  md = await until(() => [...d.querySelectorAll('.modal.fshmodal')].find(m => m.style.display !== 'none' && m.querySelector('#fsh-members .fshowner')));
  check(md && txt(md.querySelector('.foot .btn.pri')) === 'Done' && !/Back/.test(txt(md.querySelector('.foot'))), '#5587: folder Share as a sub-dialog closes with "Done" ' + txt(md?.querySelector('.foot')));
  check(md && /Alice/.test(txt(md.querySelector('#fsh-members'))) && !md.querySelector('#fsh-members .eload') && md.querySelector('#fsh-members.shppl'), '#5587: folder Share shows its people (the owner), no Loading left ' + txt(md?.querySelector('#fsh-members')).slice(0, 80));
  check(md && md.querySelector('select[data-fprole], #fsh-members') && md.querySelector('#fsh-sec-own > summary .shsecst#fsh-st-own'), '#5587: folder Share: the shared folded part (state in the folded line)');
  md?.querySelector('.foot .btn.pri').click();
  check(await until(() => [...d.querySelectorAll('.modal.fsmodal')].find(m => m.style.display !== 'none')), '#5587: "Done" leads back to the folder settings');
  shut();
  // 2.913.0 (#5587): the task choice of the multi-selection: the tasks are there, it closes with "Close"
  md = await open(`dgPick({title: 'Pick a task', filter: () => true, near: S.tasks.get(${TID}), pick: () => {}})`, '.modal.dgpick');
  check(await until(() => /Sand the boards/.test(txt(md?.querySelector('#dg-list')))) && JSON.stringify(foot(md)) === JSON.stringify(['Close']), '#5587: the multi-selection task choice lists the tasks and closes with "Close" ' + JSON.stringify(foot(md)));
  md?.querySelector('.foot [data-m="close"]').click();
  check(await until(() => !d.querySelector('.modal.dgpick:not(.an-out)')), '#5587: "Close" closes the choice');
  shut();
  // a form: Cancel + Save, Save at the right edge, Cancel right next to it
  md = await open(`statusModal(${WORK})`, '.modal.stmodal');
  check(JSON.stringify(foot(md)) === JSON.stringify(['Cancel', 'Save']), '#5442: status dialog = Cancel | Save (was Close | Update status) ' + JSON.stringify(foot(md)));
  shut();
  // a pure choice: Close (nothing to cancel)
  md = await open(`depPicker(${TID}, 'by')`, '.modal.dpmodal');
  check(JSON.stringify(foot(md)) === JSON.stringify(['Close']), '#5442: "Blocked by…" choice = Close ' + JSON.stringify(foot(md)));
  shut();
  // the date picker in a dialog: Escape closes only it, the dialog stays, the focus is back on the field's button
  md = await open(`modal('<h3>Pick</h3>' + dateIn('p2910-d', '', {label: 'Day'}) + '<div class="foot"><button class="btn" data-m="close">Cancel</button></div>')`, '[data-dpfor="p2910-d"]');
  const fb = md.querySelector('[data-dpfor="p2910-d"]');
  fb.focus(); fb.click();
  const dp = await until(() => d.querySelector('#dpop'));
  check(dp && w.eval(`KBR.st.some(s => s.el === document.querySelector('#dpop') && s.scope === 'popover')`), '#5442: the date picker is on the shared key stack');
  const inDp = await until(() => d.activeElement?.closest?.('#dpop') && d.activeElement);
  inDp?.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  check(await until(() => !d.querySelector('#dpop:not(.an-out)')) && md.isConnected && md.style.display !== 'none', '#5442: Escape closes only the date picker, the dialog stays');
  check(d.activeElement === fb, '#5442: the focus is back on the date field\'s button ' + (d.activeElement?.outerHTML || '').slice(0, 80));
  check(!w.eval(`KBR.st.some(s => s.el && s.el.id === 'dpop' && s.el.isConnected && !s.el.classList.contains('an-out'))`), '#5442: the picker is off the stack');
  // a second Escape closes the dialog (the next one on the stack)
  fb.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  check(await until(() => !md.isConnected || md.classList.contains('an-out')), '#5442: the next Escape closes the dialog');
  shut();
  w.close();

  // ================= #5442 regression: a member who cannot manage opens Share while agents exist
  w = await boot({user: 'bob', hash: 'l/' + WORK}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const shErr = w.eval(`(() => { S.agents = [{id: 990001, name: 'Helper', agent: true}]; try { shareModal(${WORK}); return ''; } catch (e) { return String(e); } })()`);
  check(!shErr && w.eval(`!canManage(listById(${WORK}))`), '#5442: Share opens for a member who cannot manage, agents around ' + shErr);
  check(await until(() => d.querySelector('.modal.shmodal .foot .btn.pri')), '#5442: ... the dialog is there with its "Done"');
  w.close();

  // ================= #5445 the docked composer (jsdom, desktop)
  const LW = (await callAs(CA, 'POST', '/api/lists', {name: 'Website'})).id;
  w = await boot({user: 'alice', hash: 'l/' + LW}); d = w.document;
  check(await until(() => d.querySelector('.qadd.dock #qinput')), '#5445: the docked composer is there');
  const typeQ = (sel, v) => w.eval(`(() => { const i = document.querySelector(${JSON.stringify(sel)}); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
  const hintShown = sel => w.eval(`(() => { const h = document.querySelector(${JSON.stringify(sel)}); return !!h && !h.hidden && !h.querySelector('.qhcs')?.hidden; })()`);
  check(hintShown('.qadd.dock .qhint'), '#5445: the syntax help shows for an empty field');
  await typeQ('#qinput', 'Logo approve tomorrow !high #client');
  const tom = w.eval(`dayLabel(addDays(today(), 1))`);
  const chips = () => w.eval(`(() => { const q = [...document.querySelectorAll('#qdchips .qdc, #qchips .qchip:not(.qdx)')].filter(e => !e.classList.contains('off')).map(e => e.textContent.trim()); return JSON.stringify(q); })()`);
  check(await until(() => JSON.parse(chips()).some(x => x === tom)), '#5445: the date chip says ' + tom + ' ' + chips());
  let c = JSON.parse(chips());
  check(c.filter(x => x.toLowerCase().includes(tom.toLowerCase())).length === 1, '#5445: the day shows exactly once ' + JSON.stringify(c));
  check(c.filter(x => /high/i.test(x)).length === 1, '#5445: the priority shows exactly once ' + JSON.stringify(c));
  check(c.includes('#client'), '#5445: the tag shows as its chip ' + JSON.stringify(c));
  check(!d.querySelector('#qchips .qchip[data-qtype="date"]:not(.off), #qchips .qchip[data-qtype="prio"]:not(.off)'), '#5445: no second parser chip for date / priority');
  check(!hintShown('.qadd.dock .qhint'), '#5445: the syntax help is gone once something is recognised');
  // the small x keeps "don't recognise"
  check(!!d.querySelector('#qdchips .qdx[data-qtype="date"]'), '#5445: the date chip read from the text has its small x');
  w.eval(`document.querySelector('#qdchips .qdx[data-qtype="date"]').click()`);
  check(await until(() => d.querySelector('#qchips .qchip.off[data-qtype="date"]')), '#5445: the x = the word comes back crossed out (recognise again)');
  check(!JSON.parse(chips()).includes(tom), '#5445: the date chip no longer takes the word ' + chips());
  w.eval(`document.querySelector('#qchips .qchip.off[data-qtype="date"]').click()`);
  check(await until(() => JSON.parse(chips()).filter(x => x.includes(tom)).length === 1), '#5445: recognised again: once ' + chips());
  await typeQ('#qinput', '');
  check(await until(() => hintShown('.qadd.dock .qhint')), '#5445: the help comes back for an empty field');
  w.close();
  // the phone sheet
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + LW}); d = w.document;
  await until(() => d.querySelector('#view'));
  w.eval(`openQuickSheet()`);
  check(await until(() => d.querySelector('.qadd.sheet #qsheet')), '#5445: phone: the sheet opens');
  check(hintShown('.qadd.sheet .qhint'), '#5445: phone: the help for an empty field');
  await typeQ('#qsheet', 'Logo approve tomorrow !high #client');
  check(await until(() => (d.querySelector('.qadd.sheet .chips .qttl')?.textContent || '') === 'Logo approve'), '#5445: phone: the title stays in sight in front of the chips: ' + d.querySelector('.qadd.sheet .chips')?.textContent);
  const sc = [...d.querySelectorAll('.qadd.sheet .chips .qchip:not(.off)')].map(e => e.textContent.trim());
  check(sc.filter(x => /tomorrow/i.test(x)).length === 1, '#5445: phone: the day once ' + JSON.stringify(sc));
  check(!hintShown('.qadd.sheet .qhint'), '#5445: phone: the help is gone once something is recognised');
  w.close();

  // ================= #5444 a refused completion / reorder (jsdom, bruno: German, no organisation)
  const LB = (await callAs(CB, 'POST', '/api/lists', {name: 'Garten'})).id;
  const TB = (await callAs(CB, 'POST', '/api/tasks', {title: 'Rasen mähen', list_id: LB})).id;
  const TB2 = (await callAs(CB, 'POST', '/api/tasks', {title: 'Hecke schneiden', list_id: LB})).id;
  w = await boot({user: 'bruno', hash: 'l/' + LB}); d = w.document;
  const of = w.fetch;
  w.__fail = null;
  w.fetch = async (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(); if (m !== 'GET' && w.__fail && w.__fail.test(String(u))) return new Response(JSON.stringify({error: 'Testfehler'}), {status: 500, headers: {'Content-Type': 'application/json'}}); return of(u, o); };
  check(await until(() => d.querySelector(`#view .trow[data-id="${TB}"] .chk`)), '#5444: the task row');
  w.__fail = /\/complete$/;
  w.eval(`document.querySelector('#view .trow[data-id="${TB}"] .chk').click()`);
  const toastT = () => (d.querySelector('#toast')?.textContent || '').trim();
  check(await until(() => /Erledigt konnte nicht gespeichert werden/.test(toastT())), '#5444: the message says what was not saved: ' + toastT());
  check(/Testfehler/.test(toastT()) && toastT().indexOf('Erledigt') < toastT().indexOf('Testfehler'), '#5444: the server text only as an addition after it: ' + toastT());
  check(await until(() => { const k = d.querySelector(`#view .trow[data-id="${TB}"] .chk`); return k && !k.classList.contains('on') && !k.querySelector('svg') && k.getAttribute('aria-checked') !== 'true'; }), '#5444: the circle is empty again');
  check(((await callAs(CB, 'GET', '/api/state')).tasks || []).find(x => x.id === TB)?.status === 0, '#5444: the task is still open on the server');
  // a refused reorder: its own message
  w.__fail = /\/api\/tasks\/reorder$/;
  await w.eval(`api('POST', '/api/tasks/reorder', {items: [{id: ${TB2}, sort: -5}]}).catch(() => 0)`);
  check(await until(() => /Verschieben nicht gespeichert, die Aufgabe steht wieder an ihrem Platz/.test(toastT())), '#5444: a refused reorder says the task is back: ' + toastT());
  w.__fail = null;
  // offline: the one sentence
  const off = w.eval(`(() => { const t = taskById(${TB}); S.dp = {id: t.id, err: 'offline'}; const deps = depsHtml(t); S.tl = {id: t.id, err: 'offline'}; return JSON.stringify([deps, timelineItems(), histItems(), errText(new Offline())]); })()`);
  const offs = JSON.parse(off).map(h => h.replace(/<[^>]+>/g, '').trim());
  check(offs.every(x => x.endsWith('Nur online verfügbar.')), '#5444: offline one sentence everywhere ' + JSON.stringify(offs));
  check(w.eval(`errText({message: 'Testfehler'}, tr('The comments could not be loaded'))`) === 'Die Kommentare konnten nicht geladen werden (Testfehler)', '#5444: errText: the sentence, the server text in brackets');
  w.close();

  w.close();

  // ================= #5442 (Firefox): the Share dialog keeps its height while it loads
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    // #5442: the Share dialog keeps its height while it loads (people, agents, the public link): sampled every frame
    for (const [wd, ht, tag] of [[1440, 900, 'computer'], [390, 844, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      await nav(B + `#l/${WORK}`);
      await wait(`!!document.querySelector('#view .trow')`, 80);
      for (const [fn, sel] of [[`shareModal(${WORK})`, '.modal.shmodal:not(.fshmodal)'], [`folderShareModal('Studio')`, '.modal.fshmodal']]) {  // 2.913.0 (#5587): + the folder's Share dialog on the frame
        const hs = await ev(`new Promise(res => { const hs = []; ${fn}; const t0 = performance.now();
          const tick = () => { const c = document.querySelector('${sel} .card'); if (c) hs.push(Math.round(c.getBoundingClientRect().height)); if (performance.now() - t0 < 2500) requestAnimationFrame(tick); else res(hs); }; requestAnimationFrame(tick); })`);
        const loaded = await ev(`!document.querySelector('${sel} .eload') || 'still'`);
        const first = hs.find(h => h > 0) || 0, last = hs[hs.length - 1] || 0, steps = hs.filter((h, i) => i && h - hs[i - 1] > 4).length;
        check(hs.length > 5 && first > 100 && Math.abs(last - first) <= 6 && steps === 0, `Firefox ${tag}: ${fn}: the dialog does not grow while it loads ` + JSON.stringify({first, last, steps, loaded, n: hs.length}));
        await shot(`p2910-share-${tag}-${fn.startsWith('folder') ? 'folder' : 'project'}.png`);
        await ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
      }
    }
  });

  console.log(`p2910_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
