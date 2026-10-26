// 2.154.0 UI tests, part A (#1111 #1356): documents -- the stack hint, the split preview (page previews, cuts, summary),
// "Split" with its undo, the link with an existing task from the document sheet and "Document: <title>" in the task. Own
// container (start.sh), Firefox. Invented names only; the stack PDF (QR codes drawn with segno + Pillow) is made in the
// test container. freelancer-matrix: files
// - a person without organisation: a stack of four pages with two archive number codes -> the sheet says "Stack - split?",
//   the preview shows four pages with previews, "Makes 2 documents"; a cut set by tap -> 3, removed again -> 2; Split ->
//   the stack leaves the list, two documents come; the toast's undo brings the stack back
// - "Link with a task…" opens the task picker, a pick shows "Task: <title>" in the sheet; the task's detail shows
//   "Document: <name>"
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2154_a_ui', check, shots: 'P2154A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2154A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const STACK = `
import base64, io, json, sys, segno
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=44)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    lines = spec.split('\\n')
    if lines[0].startswith('qr:'):
        b = io.BytesIO()
        segno.make(lines.pop(0)[3:], micro=False).save(b, kind='png', scale=8, border=4)
        im.paste(Image.open(b).convert('L'), (1200, 100))
    for i, ln in enumerate(lines):
        d.text((150, 400 + i * 90), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
`;
const stackPdf = pages => Buffer.from(execFileSync('docker', ['exec', CT, 'python', '-c', STACK, JSON.stringify(pages)]).toString().trim(), 'base64');
const up = async (ck, name, data) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([data], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
};
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const SID = await up(CF, 'stapel.pdf', stackPdf(['qr:ASN00201\nRechnung Eins\nBeispiel Strom GmbH', 'Seite zwei der Rechnung\nSumme 12,00 EUR',
    'qr:ASN00202\nVertrag Zwei\nBeispiel Versicherung AG', 'Anlage zum Vertrag\nSeite vier']));
  let d; for (let i = 0; i < 240 && !['done', 'failed'].includes((d = await call(CF, 'GET', `/api/docs/${SID}`)).state); i++) await sleep(500);
  check(d.split?.stack === true, 'the stack is marked ' + JSON.stringify(d.split));
  const ONE = await up(CF, 'brief.pdf', stackPdf(['Ein Brief\nBeispiel Verein e.V.']));
  for (let i = 0; i < 240 && !['done', 'failed'].includes((await call(CF, 'GET', `/api/docs/${ONE}`)).state); i++) await sleep(500);
  const st = await call(CF, 'GET', '/api/state');
  const INB = (st.lists || []).find(l => l.is_inbox)?.id;
  const TID = (await call(CF, 'POST', '/api/tasks', {title: 'Vereinsbeitrag zahlen', list_id: INB})).id;
  check(TID > 0, 'a task to link with');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const ids = `fetch('/api/docs?ws=private&limit=200&facets=0', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.docs.map(x => x.id))`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + `#docs/${SID}`);
    check(await ready(ev, `!!document.querySelector('.dc-md .dsp-hint [data-dsp="open"]')`, 80), 'the sheet: "Stack - split?" with "Split stack…"');
    await shot('p2154-a-hint.png');
    await ev(`(() => { document.querySelector('.dc-md .dsp-hint [data-dsp="open"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.dsp-md .dsp-pg').length === 4`, 60), 'the preview shows four pages');
    check(await ready(ev, `document.querySelectorAll('.dsp-md .dsp-th img').length === 4`, 80), 'the previews of the pages loaded');
    check(await ev(`/Makes 2 documents/.test(document.querySelector('.dsp-md .dsp-sum').textContent)`), 'summary: 2 documents ' + await ev(`document.querySelector('.dsp-md .dsp-sum').textContent`));
    check(await ev(`document.querySelector('.dsp-md [data-dspc="2"]').getAttribute('aria-pressed') === 'true' && document.querySelector('.dsp-md [data-dspc="1"]').getAttribute('aria-pressed') === 'false'`), 'the cut sits before page 3 (the second code)');
    await shot('p2154-a-preview.png');
    await ev(`(() => { document.querySelector('.dsp-md [data-dspc="3"]').click(); return 1; })()`);
    check(await ready(ev, `/Makes 3 documents/.test(document.querySelector('.dsp-md .dsp-sum').textContent)`, 20), 'a cut by tap: 3 documents');
    await ev(`(() => { document.querySelector('.dsp-md [data-dspc="3"]').click(); return 1; })()`);
    check(await ready(ev, `/Makes 2 documents/.test(document.querySelector('.dsp-md .dsp-sum').textContent)`, 20), 'the cut removed: 2 documents');
    await ev(`(() => { document.querySelector('.dsp-md [data-m="split"]').click(); return 1; })()`);
    check(await ready(ev, `${ids}.then(a => !a.includes(${SID}) && a.length === 3)`, 80), 'split: the stack left the list, two documents came');
    check(await ev(`!document.querySelector('.dsp-md') && !document.querySelector('.dc-md')`), 'the dialogs closed');
    check(await ready(ev, `/split into 2 documents/.test(document.querySelector('#toast')?.textContent || '')`, 20), 'the toast names it ' + await ev(`document.querySelector('#toast')?.textContent || ''`));
    await undoToast(ev, /split into 2 documents/);  // 2.312.0 A (#3283)
    check(await ready(ev, `${ids}.then(a => a.includes(${SID}) && a.length === 2)`, 80), 'undo: the stack is back, the parts went');
    // link the letter with the task
    await nav(B + `#docs/${ONE}`);
    check(await ready(ev, `!!document.querySelector('.dc-md [data-dsp="link"]')`, 80), 'the sheet offers "Link with a task…"');
    await ev(`(() => { document.querySelector('.dc-md [data-dsp="link"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dsp-pick [data-pick="${TID}"]')`, 40), 'the task picker lists the task');
    await shot('p2154-a-pick.png');
    await ev(`(() => { document.querySelector('.dsp-pick [data-pick="${TID}"]').click(); return 1; })()`);
    check(await ready(ev, `/Vereinsbeitrag zahlen/.test(document.querySelector('.dc-md .dsp-task')?.textContent || '')`, 40), 'the sheet: "Task: <title>"');
    await shot('p2154-a-linked.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    await nav(B + `#t/${TID}`);
    check(await ready(ev, `/Document: brief\\.pdf/.test(document.querySelector('#detail .dlklnk')?.textContent || '')`, 80), 'the task: "Document: brief.pdf" ' + await ev(`document.querySelector('#detail .dlklnk')?.textContent || '-'`));
    await shot('p2154-a-task.png');
  }, false);

  console.log(`p2154_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
