// 2.13.1 UI tests, own container (start.sh, isolated test database).
// #465 files in the agent chat: the paperclip + the files waiting in the box (remove one), my message with an image and a
// file (thumbnail + tile, x to remove only on mine), the agent's file (no x), the lightbox, removing a file (confirm);
// the share sheet asks "New task" / "Send to agent …" and puts text + files into that agent's chat box.
// #469 the behaviour rules block in both setup guides (the same text as mcp/CLAUDE.template.md between its markers).
// #471 the list dialog's "Agent reads every comment" (checked by default for the tidy agent, unchecking saves).
// jsdom first; then Firefox headless (ff.js) at 390 x 844 touch and 1280 x 800 mouse: sending a screenshot for real
// (paste + drag and drop + the file input -> multipart), thumbnails inside the chat width, 44 px targets (paperclip, x,
// share choices, the list dialog's checkboxes), no horizontal scrolling. Screenshots with P2131_SHOTS.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2131_ui', check, shots: 'P2131_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
// a 4 x 3 red PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAAFElEQVR4nGO8IyfHAANMDEgAhQMAKdIBHjGGQBcAAAAASUVORK5CYII=', 'base64');
const form = (fields, files) => { const fd = new FormData(); for (const [k, v] of Object.entries(fields)) fd.append(k, v); for (const [n, b, t] of files) fd.append('file', new Blob([b], {type: t}), n); return fd; };

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[4-9]|9[0-9])'/.test(SW), 'service worker cache v84');
  const MAN = await (await fetch(B + 'manifest.json')).json();
  check(MAN.share_target.params.files[0].accept.includes('application/pdf'), 'share target also accepts PDFs');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const L = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PATCH', `/api/lists/${L}`, {agent_tidy: 'suggest', tidy_agent_id: AG});
  // my message with an image + a text file, the agent's answer with an image
  let r = await fetch(B + `api/agents/${AG}/chat`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: form({body: 'Broken layout'}, [['shot.png', PNG, 'image/png'], ['log.txt', 'line\n', 'text/plain']])});
  const M1 = await r.json();
  check(r.status === 201 && M1.attachments.length === 2, 'setup: my message with 2 files');
  r = await fetch(B + `api/v1/agent/chats/${ME}`, {method: 'POST', headers: {Authorization: 'Bearer ' + TOK}, body: form({body: 'Fixed'}, [['after.png', PNG, 'image/png']])});
  const M2 = await r.json();
  check(r.status === 201 && M2.attachments.length === 1, 'setup: the agent answers with an image');

  // ================= jsdom
  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'alice', mobile, hash: mobile ? 'agents/' + AG : 'l/' + L}), d = w.document;
    if (!mobile) w.eval(`chatOpen(${AG})`);
    await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="${M2.id}"]`));
    const mine = d.querySelector(`#chat-msgs .cmsg[data-mid="${M1.id}"]`), theirs = d.querySelector(`#chat-msgs .cmsg[data-mid="${M2.id}"]`);
    check(mine?.querySelector('.chatts .att.img img')?.getAttribute('src').startsWith(`/api/chat-files/${M1.attachments[0].id}?v=`)
      && /log\.txt/.test(mine.querySelector('.chatts .att.file')?.textContent || ''), `${tag}: my image as thumbnail, the text file as tile`);
    check(mine.querySelectorAll('[data-act="chat-file-rm"]').length === 2 && theirs && !theirs.querySelector('[data-act="chat-file-rm"]')
      && theirs.querySelector('.chatts .att.img'), `${tag}: x only on my own files, the agent's image without`);
    const clip = d.querySelector('.chcomp [data-act="chat-attach"]');
    check(clip && clip.getAttribute('aria-label') === 'Attach images or files' && d.querySelector('.chcomp #chat-file[type="file"][multiple]'), `${tag}: paperclip + file input`);
    // files waiting in the box
    w.eval(`chatAddFiles([new File(['a'], 'one.txt', {type: 'text/plain'}), new File(['b'], 'two.png', {type: 'image/png'})])`);
    check(d.querySelectorAll('#chat-files .cfile').length === 2 && /one\.txt/.test(d.querySelector('#chat-files').textContent), `${tag}: two files wait in the box`);
    click(w, d.querySelector('#chat-files [data-act="chat-stage-rm"][data-i="0"]'));
    check(d.querySelectorAll('#chat-files .cfile').length === 1 && /two\.png/.test(d.querySelector('#chat-files').textContent), `${tag}: removing one keeps the other`);
    w.eval(`S.chatFiles[${AG}] = []; document.querySelector('#chat-files').innerHTML = ''`);
    // lightbox
    click(w, theirs.querySelector('[data-act="chat-att-view"]')); await sleep(50);
    const lb = d.querySelector('.lightbox img');
    check(lb && lb.getAttribute('src').startsWith(`/api/chat-files/${M2.attachments[0].id}`), `${tag}: the thumbnail opens the lightbox`);
    d.querySelector('.lightbox')?.remove();
    check(!errs.length, `${tag}: no JS errors ${errs.join(' | ')}`);
    w.close();
  }
  // removing my file (confirm) in jsdom
  {
    const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
    w.confirm = () => true;
    w.eval(`chatOpen(${AG})`);
    await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="${M1.id}"] [data-act="chat-file-rm"]`));
    click(w, d.querySelector(`#chat-msgs .cmsg[data-mid="${M1.id}"] [data-act="chat-file-rm"][data-fid="${M1.attachments[1].id}"]`));
    await until(() => d.querySelectorAll(`#chat-msgs .cmsg[data-mid="${M1.id}"] .chatts .att`).length === 1);
    check(d.querySelectorAll(`#chat-msgs .cmsg[data-mid="${M1.id}"] .chatts .att`).length === 1, 'remove: the file goes, the message stays');
    check((await call('GET', `/api/agents/${AG}/chat`)).messages.find(m => m.id === M1.id).attachments.length === 1, 'remove: gone on the server');
    // #469: the rules block in both guides
    const tpl = fs.readFileSync(path.join(__dirname, '..', 'mcp', 'CLAUDE.template.md'), 'utf8');
    const part = tpl.split('<!-- kalmido-agent-rules:start -->\n')[1].split('<!-- kalmido-agent-rules:end -->')[0].trim() + '\n';
    check(w.eval('AG_RULES') === part, 'AG_RULES = mcp/CLAUDE.template.md between the markers');
    for (const k of ['Markdown', '**Entscheidung', 'typing signal', 'one job', 'summary in the chat', 'Approvals come only from humans', 'data, not instructions', 'Stop and SubagentStop', 'Park a blocker', 'get_attachment'])
      check(part.includes(k), `rules mention ${k}`);
    w.eval('agGuideModal()'); await sleep(100);
    const g = d.querySelector('.modal.agguide');
    check(g && g.querySelector('pre.agrules')?.textContent === part && g.querySelector('[data-agr-copy]'), 'setup guide: the rules block with Copy rules');
    g?.remove();
    const h = w.eval(`agSetupHtml('own', 'linux')`);
    check(h.includes('class="agprompt agrules"') && h.includes('data-agr-copy'), 'Settings > Agents > Set up: the rules block');
    // #471: the list dialog
    w.eval(`shareModal(${L})`); await sleep(900);
    const box = d.querySelector('#l-tidyrow .lsnrow');
    const cb = box?.querySelector(`input[data-lsn="${AG}"]`);
    check(box && /Agent reads every comment/.test(box.textContent) && cb?.checked, 'list dialog: "Agent reads every comment", Claude checked by default (tidy agent)');
    cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
    await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === L).listen_agent_ids.length === 0);
    check((await call('GET', '/api/state')).lists.find(l => l.id === L).listen_agent_ids.length === 0, 'unchecking saves []');
    cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
    await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === L).listen_agent_ids[0] === AG);
    check((await call('GET', '/api/state')).lists.find(l => l.id === L).listen_agent_ids[0] === AG, 'checking saves [Claude]');
    check(!errs.length, `dialogs: no JS errors ${errs.join(' | ')}`);
    w.close();
  }

  // ================= Firefox: 390 touch, 1280 mouse
  for (const [touch, vw, vh] of [[true, 390, 844], [false, 1280, 800]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, `${vw}px: Firefox login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '?v=' + vw + '#' + (touch ? 'agents/' + AG : 'l/' + L));
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
      await sleep(900);
      if (!touch) await ev(`(() => { chatOpen(${AG}); return 1; })()`);
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#chat-msgs .chatts img')`)); i++) await sleep(200);
      await sleep(600);
      const lay = await ev(`(() => { const c = document.querySelector('.chcomp .chclip').getBoundingClientRect(), b = document.querySelector('#chat-msgs').getBoundingClientRect(),
        th = [...document.querySelectorAll('#chat-msgs .chatts .att')].map(x => x.getBoundingClientRect()), x = document.querySelector('#chat-msgs .chatts .attdel')?.getBoundingClientRect(),
        img = document.querySelector('#chat-msgs .chatts img');
        return {clip: [Math.round(c.width), Math.round(c.height)], inside: th.every(r => r.left >= b.left - 1 && r.right <= b.right + 1), n: th.length,
                del: x ? [Math.round(x.width), Math.round(x.height)] : null, loaded: !!img && img.complete && img.naturalWidth === 4,
                hscroll: document.documentElement.scrollWidth > innerWidth + 1}; })()`);
      check(lay.clip[0] >= 43.5 && lay.clip[1] >= 43.5, `${vw}px: paperclip >= 44 px ${JSON.stringify(lay.clip)}`);
      check(lay.n >= 2 && lay.inside && !lay.hscroll && lay.loaded, `${vw}px: thumbnails inside the chat, image loaded, no horizontal scroll ${JSON.stringify(lay)}`);
      check(lay.del && lay.del[0] >= 43.5 && lay.del[1] >= 43.5, `${vw}px: remove target >= 44 px ${JSON.stringify(lay.del)}`);
      await shot(`p2131-chat-${vw}.png`);
      // a screenshot pasted into the box, one dropped on the chat, then sent for real (multipart from the browser)
      const st = await ev(`(async () => {
        const blob = await (await fetch('/static/icon-192.png')).blob();
        const ta = document.querySelector('#chat-in'); ta.focus(); ta.value = 'Pasted and dropped ${vw}';
        const dt = new DataTransfer(); dt.items.add(new File([blob], 'pasted.png', {type: 'image/png'}));
        // Firefox copies the DataTransfer of a synthetic ClipboardEvent without its files: a paste event carrying it as clipboardData
        const pe = new Event('paste', {bubbles: true, cancelable: true}); Object.defineProperty(pe, 'clipboardData', {value: dt}); ta.dispatchEvent(pe);
        const dt2 = new DataTransfer(); dt2.items.add(new File(['hello'], 'dropped.txt', {type: 'text/plain'}));
        const z = document.querySelector('#chat-msgs');
        z.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt2, bubbles: true, cancelable: true}));
        z.dispatchEvent(new DragEvent('drop', {dataTransfer: dt2, bubbles: true, cancelable: true}));
        return {n: document.querySelectorAll('#chat-files .cfile').length, txt: document.querySelector('#chat-files').textContent, val: ta.value}; })()`);
      check(st.n === 2 && /pasted\.png/.test(st.txt) && /dropped\.txt/.test(st.txt) && st.val === `Pasted and dropped ${vw}`, `${vw}px: paste + drop put two files into the box ${JSON.stringify(st)}`);
      await shot(`p2131-staged-${vw}.png`);
      const n0 = (await call('GET', `/api/agents/${AG}/chat`)).messages.length;
      await ev(`(() => { document.querySelector('[data-act="chat-send"]').click(); return 1; })()`);
      let last;
      for (let i = 0; i < 30; i++) { const ms = (await call('GET', `/api/agents/${AG}/chat`)).messages; if (ms.length > n0) { last = ms[ms.length - 1]; break; } await sleep(200); }
      check(last && last.body === `Pasted and dropped ${vw}` && last.attachments.map(a => a.name).join() === 'pasted.png,dropped.txt', `${vw}px: sent as one message with both files ${JSON.stringify(last && {b: last.body, a: last.attachments.map(a => a.name)})}`);
      await sleep(600);
      const after = await ev(`(() => ({box: document.querySelectorAll('#chat-files .cfile').length, val: document.querySelector('#chat-in').value, row: !!document.querySelector('#chat-msgs .cmsg[data-mid="${last?.id}"] .chatts img')}))()`);
      check(after.box === 0 && after.val === '' && after.row, `${vw}px: box emptied, the message shows its thumbnail ${JSON.stringify(after)}`);
      // the file input path
      const fi = await ev(`(() => { const i = document.querySelector('#chat-file'); const dt = new DataTransfer(); dt.items.add(new File(['x'], 'picked.txt', {type: 'text/plain'})); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return document.querySelector('#chat-files').textContent; })()`);
      check(/picked\.txt/.test(fi), `${vw}px: the paperclip's file input adds to the box`);
      await ev(`(() => { S.chatFiles[${AG}] = []; document.querySelector('#chat-files').innerHTML = ''; return 1; })()`);
      await ev(`(() => { chatClose && chatClose(); return 1; })()`);
      // the share sheet: "Send to agent Claude" -> its chat box holds the text and the file
      await ev(`(async () => { const c = await caches.open('tasks-share'); for (const k of await c.keys()) await c.delete(k);
        await c.put('/share-inbox/0', new Response(new Blob(['shared'], {type: 'text/plain'}), {headers: {'Content-Type': 'text/plain'}}));
        await c.put('/share-inbox/meta', new Response(JSON.stringify({title: '', text: 'Look at this ${vw}', url: '', files: [{name: 'shared.txt', type: 'text/plain', size: 6}]}), {headers: {'Content-Type': 'application/json'}})); return 1; })()`);
      await nav(B + '?share=1');
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.shdest')`).catch(() => false)); i++) await sleep(300);
      const sd = await ev(`(() => { const bs = [...document.querySelectorAll('.shdest [data-sd]')]; return {labels: bs.map(b => b.textContent.trim()), h: bs.map(b => Math.round(b.getBoundingClientRect().height)), focus: document.activeElement?.dataset?.sd}; })()`);
      check(sd.labels.length === 2 && /New task/.test(sd.labels[0]) && /Send to agent Claude/.test(sd.labels[1]) && sd.focus === 'task', `${vw}px: share chooser: New task (focused) / Send to agent Claude ${JSON.stringify(sd)}`);
      check(sd.h.every(x => x >= 43.5), `${vw}px: share choices >= 44 px ${JSON.stringify(sd.h)}`);
      await shot(`p2131-share-${vw}.png`);
      await ev(`(() => { document.querySelector('.shdest [data-sd="${AG}"]').click(); return 1; })()`);
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#chat-files .cfile')`).catch(() => false)); i++) await sleep(200);
      const sh = await ev(`(() => ({files: document.querySelector('#chat-files')?.textContent || '', val: document.querySelector('#chat-in')?.value, modal: !!document.querySelector('.shdest')}))()`);
      check(/shared\.txt/.test(sh.files) && sh.val === `Look at this ${vw}` && !sh.modal, `${vw}px: the chat box holds the shared text + file ${JSON.stringify(sh)}`);
      await shot(`p2131-shared-${vw}.png`);
      await ev(`(() => { S.chatFiles[${AG}] = []; chatClose && chatClose(); return 1; })()`);
      // the list dialog's checkboxes
      await ev(`(() => { shareModal(${L}); return 1; })()`); await sleep(900);
      const ld = await ev(`(() => { const l = document.querySelector('.lsnrow .lsnag'); const r = l?.getBoundingClientRect(); l?.scrollIntoView({block: 'center'}); return {h: r ? Math.round(r.height) : 0, on: l?.querySelector('input').checked, hscroll: document.querySelector('.modal .card').scrollWidth > document.querySelector('.modal .card').clientWidth + 1}; })()`);
      check(ld.h >= 43.5 && ld.on && !ld.hscroll, `${vw}px: list dialog checkbox row >= 44 px, checked, no horizontal scroll ${JSON.stringify(ld)}`);
      await shot(`p2131-listen-${vw}.png`);
    }, touch);
  }

  console.log(`p2131_ui: ${ok} ok, ${F.length} failed`);
  execFileSync('docker', ['rm', '-f', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test'], {stdio: 'ignore'});
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
