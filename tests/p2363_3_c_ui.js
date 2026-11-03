// 2.363.3 UI tests, part C (#3134 uploads), own container (start.sh), Firefox:
// - a form with files from 1 MB goes through the bar of upbar.js: progress with Cancel; the file arrives as before; a small file
//   shows nothing; after the body is out Cancel is gone (the server stores the file then)
// - Cancel ends the request on the wire, leaves no half file behind and no half task (filesToTasks), is not "offline"
// - all file dialogs use the server's limit: a smaller limit refuses what 50 MB took, a larger one takes what 50 MB refused
// - a truncated multipart body (what a Cancel sends) leaves no attachment on the server
const fs = require('fs'), net = require('net'), path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2363_3_c_ui', check, shots: 'P2363_3C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23633C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

// a body cut off in the middle of its file, then the connection ends
const cutUpload = (ck, tid) => new Promise(res => {
  const u = new URL(B), bd = '----cut', head = `--${bd}\r\nContent-Disposition: form-data; name="file"; filename="half.bin"\r\nContent-Type: application/octet-stream\r\n\r\n`;
  const s = net.connect(+u.port || 80, u.hostname, () => {
    s.write(`POST /api/tasks/${tid}/attachments HTTP/1.1\r\nHost: ${u.host}\r\nCookie: ${ck}\r\nX-Requested-With: kalmido\r\nContent-Type: multipart/form-data; boundary=${bd}\r\nContent-Length: 2000000\r\n\r\n${head}`);
    s.write(Buffer.alloc(500000, 7), () => { s.destroy(); res(); });
  });
  s.on('error', res);
});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const L = await call(CA, 'POST', '/api/lists', {name: 'Uploads'});
  const T = await call(CA, 'POST', '/api/tasks', {list_id: L.id, title: 'With files'});
  check(T.id > 0, 'the task ' + T.http);
  const atts = async () => (await call(CA, 'GET', `/api/tasks/${T.id}`)).attachments || [];

  // the server side of Cancel, independent of a browser
  await cutUpload(CA, T.id);
  await sleep(500);
  check((await atts()).length === 0, 'a body cut off leaves no attachment');
  check((await call(CA, 'GET', '/api/state')).http === 200, 'the server answers after a cut off body');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(150); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    await nav(B + `#list/${L.id}`);
    check(await ready(ev, `!!S.me && !!document.querySelector('#view') && typeof uploadFiles === 'function' && !!taskById(${T.id})`), 'the app is up');
    await ev(`(() => { window.mkf = (mb, name) => new File([new Uint8Array(Math.round(mb * 1024 * 1024))], name || 'clip.bin'); window.Real = XMLHttpRequest; return 1; })()`);

    // a real upload: goes by XHR, arrives whole (the test container's limit is 1 MB)
    await ev(`(() => { window.sends = 0; const o = XMLHttpRequest.prototype.send; XMLHttpRequest.prototype.send = function (b) { window.sends++; return o.call(this, b); }; return 1; })()`);
    const up1 = await ev(`uploadFiles(${T.id}, [mkf(1, 'whole.bin')]).then(x => String(x) + ' | ' + (document.querySelector('#toast')?.textContent || ''))`);
    check(/^true/.test(up1), 'a real upload of 1 MB ends fine: ' + up1);
    check(await ev(`window.sends`) === 1, 'it went through the helper');
    let a = await atts();
    check(a.length === 1 && a[0].size === 1024 * 1024, 'the file arrived whole: ' + JSON.stringify(a.map(x => x.size)));
    check(await ready(ev, `!document.querySelector('.upbar')`), 'the bar is gone after the end');
    // a small file stays a plain fetch
    await ev(`uploadFiles(${T.id}, [mkf(.1, 'small.bin')])`);
    check(await ev(`window.sends`) === 1, 'a small file does not use the helper');
    check((await atts()).length === 2, 'the small file arrived');

    // a controlled request: progress, the bar, Cancel
    await ev(`(() => { S.maxFileMb = 50;
      window.XMLHttpRequest = class { constructor() { window.fx = this; this.upload = {}; this.aborted = false; }
        open() {} setRequestHeader() {} send() { window.fxSent = true; }
        abort() { this.aborted = true; this.onabort(); } getResponseHeader() { return null; } };
      window.res = null; uploadFiles(${T.id}, [mkf(2, 'stopped.bin')]).then(x => { window.res = String(x); });
      return 1; })()`);
    check(await ready(ev, `!!window.fxSent && !!document.querySelector('.upbar')`), 'a bar shows while the upload runs');
    await ev(`window.fx.upload.onprogress({lengthComputable: true, loaded: 40, total: 100})`);
    check(await ev(`document.querySelector('.upbar .upp').textContent`) === '40 %', 'the bar says 40 %');
    check(await ev(`document.querySelector('.uptrack').getAttribute('aria-valuenow')`) === '40', 'the progress is readable for a screen reader');
    check(/stopped\.bin/.test(await ev(`document.querySelector('.upbar .upn').textContent`)), 'the bar names the file');
    check(await ready(ev, `(() => { const t = document.querySelector('.uptrack').getBoundingClientRect().width, w = document.querySelector('.uptrack>i').getBoundingClientRect().width; return t > 0 && Math.abs(w / t - .4) < .02; })()`), 'the track is drawn 40 % full');
    await shot('upbar.png');
    const box = await ev(`(() => { const r = document.querySelector('.upbar').getBoundingClientRect(), b = document.querySelector('.upbar button').getBoundingClientRect(); return [r.left, r.right, b.height]; })()`);
    check(box[0] >= 0 && box[1] <= 390, 'the bar fits the phone: ' + box);
    await ev(`document.querySelector('.upbar button').click()`);
    check(await ready(ev, `window.res !== null`), 'Cancel ends the upload');
    check(await ev(`window.fx.aborted`), 'Cancel aborts the request');
    check(await ev(`window.res`) === 'undefined', 'a cancelled upload does not count as offline (the next flush would send it again): ' + await ev(`window.res`));
    check(await ev(`!document.querySelector('.upbar') && OUT.online`), 'the bar is gone, the app stays online');
    check(/Upload cancelled/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'a toast says so');

    // the body is out: no Cancel any more, the answer ends it
    await ev(`(() => { S.maxFileMb = 50; window.fxSent = false; window.res = null; uploadFiles(${T.id}, [mkf(2, 'later.bin')]).then(x => { window.res = String(x); }); return 1; })()`);
    check(await ready(ev, `!!window.fxSent && !!document.querySelector('.upbar')`), 'the bar again');
    await ev(`window.fx.upload.onload()`);
    check(await ev(`!document.querySelector('.upbar button')`), 'no Cancel once the body is out');
    check(await ev(`document.querySelector('.uptrack').getAttribute('aria-valuenow')`) === '100', 'the bar is full');
    await ev(`(() => { const x = window.fx; x.status = 500; x.responseText = JSON.stringify({error: 'stored badly'}); x.responseURL = location.origin + '/api/tasks/${T.id}/attachments'; x.getResponseHeader = k => k.toLowerCase() === 'content-type' ? 'application/json' : null; x.onload(); return 1; })()`);
    check(await ready(ev, `window.res !== null`), 'the answer ends it');
    check(/stored badly/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'an error of the server shows as with fetch');

    // a list drop: Cancel takes the new task with it
    const before = await ev(`S.tasks.size`);
    // #3506: a load of the state (the poll, after a change) puts the server's limit of 1 MB back: S.maxFileMb in the same step as the
    // upload, and one load on purpose here (the CI's "no bar": upLimit had refused the 2 MB, a toast instead of an upload)
    await ev(`load().then(() => 1)`);
    await ev(`(() => { S.maxFileMb = 50; window.fxSent = false; window.res = null; filesToTasks(listById(${L.id}), [mkf(2, 'drop.bin')]).then(() => { window.res = 'end'; }); return 1; })()`);
    check(await ready(ev, `!!window.fxSent && !!document.querySelector('.upbar')`), 'the list drop shows the bar: ' + await ev(`document.querySelector('#toast')?.textContent || ''`));
    await ev(`document.querySelector('.upbar button').click()`);
    check(await ready(ev, `window.res === 'end'`), 'the list drop ends');
    check(await ev(`S.tasks.size`) === before, 'no task without its file stays behind');
    await ev(`(() => { window.XMLHttpRequest = window.Real; return 1; })()`);

    // the server's limit in the dialogs
    const lim = async (mb, code) => ev(`(async () => { S.maxFileMb = ${mb}; ${code} })()`);
    check(await lim(1, `return upLimit([mkf(2, 'big.bin')], true)`) === 'big.bin is larger than 1 MB', 'a limit of 1 MB refuses 2 MB');
    check(await lim(60, `return upLimit([mkf(55, 'big.bin')], true)`) === '', 'a limit of 60 MB takes 55 MB');
    check(/larger than 4 MB/.test(await lim(1, `return upLimit([mkf(.9), mkf(.9), mkf(.9), mkf(.9), mkf(.9)])`)), 'the total of one request is checked');
    check(await lim(1, `return upLimit([mkf(.9), mkf(.9), mkf(.9), mkf(.9), mkf(.9)], true)`) === '', 'one request per file: only the size per file counts');
    await lim(1, `S.cfiles[${T.id}] = [mkf(2, 'comment.bin')]; S.sel = ${T.id}; document.body.insertAdjacentHTML('beforeend', '<textarea id="c-input"></textarea>'); await sendComment(); document.querySelector('#c-input').remove(); S.sel = null; delete S.cfiles[${T.id}]; return 1`);
    check(/comment\.bin is larger than 1 MB/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'comments use the limit');
    await lim(1, `await povUpload(listById(${L.id}), [mkf(2, 'proj.bin')]); return 1`);
    check(/proj\.bin is larger than 1 MB/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'project files use the limit');
    await lim(1, `await filesToTasks(listById(${L.id}), [mkf(2, 'list.bin')]); return 1`);
    check(/list\.bin is larger than 1 MB/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'the list drop uses the limit');
    check(await ev(`S.tasks.size`) === before, 'the refused drop created nothing');
    await lim(1, `await e2eUpload(${T.id}, [mkf(2, 'enc.bin')]); return 1`);
    check(/enc\.bin is larger than 1 MB/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), 'encrypted attachments use the limit');
  });

  // no dialog keeps a fixed limit (the dialogs of lazy modules, which this suite does not open)
  const js = path.join(__dirname, '..', 'static', 'js');
  for (const f of ['chat', 'collab', 'projects', 'sidebar', 'e2e', 'liste2efile', 'agentchat', 'meetprop', 'fslock', 'attachments']) {
    const s = fs.readFileSync(path.join(js, f + '.js'), 'utf8');
    check(!/\b50 \* 1024 \* 1024|larger than 50 MB/.test(s), f + '.js has no fixed 50 MB');
    if (f !== 'attachments') check(/upLimit\(/.test(s), f + '.js uses the server limit');
  }
  console.log(`p2363_3_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
