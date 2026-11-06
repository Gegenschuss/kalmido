// kalmido-suite: fresh
// 2.580.0 C (#4401) UI: a clear stack is split without a person; a part's sheet says "Split automatically from a stack" with
// "Undo"; the undo brings the stack back ("Stack - split?") and the parts go, the toast's undo splits it again. Own container
// (start.sh), Firefox. Invented names only; the stack PDF (QR codes drawn with segno + Pillow) is made in the test container.
// freelancer-matrix: files (a person without organisation)
// Red without the fix: the stack stays "Stack - split?", no part, no hint.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2580_c_autosplit_ui', check, shots: 'P2580C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2580C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const docIds = async () => ((await call(CF, 'GET', '/api/docs?ws=private&limit=200&facets=0')).docs || []).map(x => x.id);
  const SID = await up(CF, 'stapel.pdf', stackPdf(['qr:ASN00201\nRechnung Eins\nBeispiel Strom GmbH', 'Seite zwei der Rechnung\nSumme 12,00 EUR',
    'qr:ASN00202\nVertrag Zwei\nBeispiel Versicherung AG']));
  let P = [];
  for (let i = 0; i < 360; i++) { P = await docIds(); if (!P.includes(SID) && P.length === 2) break; await sleep(500); }
  check(!P.includes(SID) && P.length === 2, 'the clear stack was split without a click ' + JSON.stringify(P));
  const part = Math.min(...P);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const ids = `fetch('/api/docs?ws=private&limit=200&facets=0', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.docs.map(x => x.id))`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + `#docs/${part}`);
    check(await ready(ev, `/Split automatically from a stack/.test(document.querySelector('.dc-md .dsp-auto')?.textContent || '')`, 80),
      'the part\'s sheet: "Split automatically from a stack" ' + await ev(`document.querySelector('.dc-md')?.textContent?.slice(0, 200) || '-'`));
    check(await ev(`!!document.querySelector('.dc-md .dsp-auto [data-dsp="unsplit"]')`), 'with "Undo"');
    await shot('p2580-c-auto-hint.png');
    await ev(`(() => { document.querySelector('.dc-md .dsp-auto [data-dsp="unsplit"]').click(); return 1; })()`);
    check(await ready(ev, `${ids}.then(a => a.includes(${SID}) && a.length === 1)`, 80), 'undo: the stack is back, the parts went');
    check(await ready(ev, `/Stack restored: stapel\\.pdf/.test(document.querySelector('#toast')?.textContent || '')`, 20), 'the toast names the stack ' + await ev(`document.querySelector('#toast')?.textContent || ''`));
    check(await ev(`!document.querySelector('.dc-md')`), 'the part\'s sheet closed');
    await undoToast(ev, /Stack restored/);
    check(await ready(ev, `${ids}.then(a => !a.includes(${SID}) && a.length === 2)`, 80), 'the toast\'s undo splits it again');

    // review 2.580 C (7a): the undo went through but reading the stack's cuts fails -- the sheet closes anyway, the list is fresh
    const before = await ev(ids);
    const S2 = await up(CF, 's2.pdf', stackPdf(['qr:ASN00203\nBrief Drei\nBeispiel Verein e.V.', 'qr:ASN00204\nBrief Vier\nBeispiel Bank AG']));
    check(await ready(ev, `${ids}.then(a => !a.includes(${S2}) && a.length === 4)`, 360), 'a second clear stack split without a click');
    const P2 = (await ev(ids)).filter(x => !before.includes(x)).sort((x, y) => x - y);
    await nav(B + `#docs/${Math.max(...P2)}`);
    check(await ready(ev, `!!document.querySelector('.dc-md .dsp-auto [data-dsp="unsplit"]')`, 80), 'the second stack\'s part: "Undo"');
    await ev(`(() => { const f0 = window.fetch; window.fetch = (u, o) => /\\/split$/.test(String(u)) && !(o && o.method && o.method !== 'GET') ? Promise.resolve(new Response('{"error":"down"}', {status: 500, headers: {'Content-Type': 'application/json'}})) : f0(u, o); return 1; })()`);
    await ev(`(() => { document.querySelector('.dc-md .dsp-auto [data-dsp="unsplit"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.dc-md')`, 40), 'reading the cuts failed: the part\'s sheet closed all the same');
    check(await ready(ev, `${ids}.then(a => a.includes(${S2}) && ${JSON.stringify(P2)}.every(x => !a.includes(x)))`, 40), 'the undo went through');
    check(await ready(ev, `!!DC.docs && DC.docs.some(x => x.id === ${S2}) && !DC.docs.some(x => x.id === ${Math.max(...P2)})`, 40), 'the list was loaded again (the stack, not the part) ' + await ev(`JSON.stringify((DC.docs || []).map(x => x.id))`));
  }, false);

  console.log(`p2580_c_autosplit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
