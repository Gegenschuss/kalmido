// kalmido-suite: fresh
// 2.892.0 (#4873, includes #4806) UI: "Optimise PDF" in the document view. Own container (start.sh), Firefox (1440 px, a
// mouse). Invented names only; the scan (Pillow pictures as a PDF without a text layer) is drawn in the test container.
// freelancer-matrix: files (a person without organisation)
// - a scanned PDF: "Actions" offers "Optimise PDF…"; the dialog measures the pages first and lists the blank page that goes
//   ("Pages that go: Page 2"), the level Automatic is chosen and "Remove blank pages" is on
// - "Optimise": the dialog shows the sizes before / after ("… → …") and that it is a new version; the view's "Actions" now
//   offer "Download searchable PDF" and "Download original" (#4806); the tab History lists two versions (v2 current, v1)
// - Greyscale switches "Remove blank pages" off (it is on only in Automatic)
// - the original comes back: "Restore" on v1 in the tab History makes it the newest version again (v3 = the original's bytes)
// The buttons are pressed with the mouse (ff.js realClick): what a person sees is what is pressed.
// P2892CU_SHOTS=1: pictures of the dialog.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const firefox = require('./ff')({tag: 'p2892_c_pdfopt_ui', check, shots: 'P2892CU_SHOTS'});
const {realClick} = require('./ff');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2892CU_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const SCAN = `
import base64, io, json, sys
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=56)
W, H = 2480, 3508
grain = Image.effect_noise((W, H), 6).point(lambda x: 236 + (x - 128) // 12)
pages = []
for text in json.loads(sys.argv[1]):
    im = Image.merge('RGB', [grain] * 3)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(text.split('|') if text else []):
        d.text((260, 400 + i * 110), ln, fill=(20, 20, 20), font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=300, save_all=True, append_images=pages[1:], quality=85)
print(base64.b64encode(o.getvalue()).decode())
`;
const scanPdf = pages => Buffer.from(execFileSync('docker', ['exec', CT, 'python', '-c', SCAN, JSON.stringify(pages)], {maxBuffer: 1 << 28}).toString().trim(), 'base64');
const up = async (ck, name, data) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([data], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).ids?.[0];
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,docs,files,office'});
  const DID = await up(CF, 'mietvertrag-scan.pdf', scanPdf(['Mietvertrag Wohnung 17|Beispiel Hausverwaltung|Miete 800 EUR', '']));
  let d = {};
  for (let i = 0; i < 600 && !(d.state === 'done' || d.state === 'failed'); i++) { d = await call(CF, 'GET', `/api/docs/${DID}`); if (d.state !== 'done') await sleep(500); }
  check(d.state === 'done' && d.method === 'ocr' && d.pdfopt?.can, 'the scan recognised by text recognition ' + JSON.stringify([d.state, d.method, d.pdfopt]));

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    const press = async (sel, what) => { const c = await realClick({cmd, ev, ctx}, sel); check(c.ok, `${what}: pressed with the mouse (${c.on})`); return c.ok; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + `#ablage/${DID}`);
    check(await wait(`!!document.querySelector('.dv-view [data-dc="actsmore"]') && DC.doc?.id === ${DID}`), 'the document view with "Actions"');
    await press('.dv-view [data-dc="actsmore"]', 'Actions');
    check(await wait(`!!document.querySelector('.dv-view #dc-amore:not([hidden]) [data-po="open"]')`), 'Actions: "Optimise PDF…" ' + await ev(`document.querySelector('.dv-view #dc-amore')?.textContent?.slice(0, 300) || '-'`));
    check(await ev(`!document.querySelector('.dv-view .po-dlorig')`), 'not optimised yet: no "Download original"');
    await press('.dv-view [data-po="open"]', 'Optimise PDF…');
    check(await wait(`!!document.querySelector('.po-md')`), 'the dialog opens');
    check(await ev(`document.querySelector('.po-md input[name="po-lv"]:checked')?.value === 'auto' && document.querySelector('.po-md [data-po="blank"]').checked`), 'Automatic chosen, "Remove blank pages" on');
    check(await wait(`/Pages that go: Page 2/.test(document.querySelector('.po-md .po-pages')?.textContent || '')`, 600), 'the pages measured: page 2 goes ' + await ev(`document.querySelector('.po-md .po-pages')?.textContent || '-'`));
    check(await ev(`/2 pages/.test(document.querySelector('.po-md .po-pages').textContent)`), 'the number of pages shown');
    await shot('p2892-c-pdfopt-check.png');
    // Greyscale: the switch goes off by itself, the list of pages that go empties; back to Automatic: on again
    await ev(`(() => { const g = document.querySelector('.po-md input[value="gray"]'); g.click(); return 1; })()`);
    check(await wait(`!document.querySelector('.po-md [data-po="blank"]').checked && !/Pages that go/.test(document.querySelector('.po-md .po-pages').textContent)`, 20), 'Greyscale: "Remove blank pages" off, no page goes');
    await ev(`(() => { document.querySelector('.po-md input[value="auto"]').click(); return 1; })()`);
    check(await wait(`document.querySelector('.po-md [data-po="blank"]').checked`, 20), 'Automatic again: the switch on');
    await press('.po-md [data-po="run"]', 'Optimise');
    check(await wait(`/→/.test(document.querySelector('.po-md .po-size')?.textContent || '')`, 1200), 'the sizes before / after ' + await ev(`document.querySelector('.po-md .po-res')?.textContent || '-'`));
    check(await ev(`/new version/.test(document.querySelector('.po-md .po-res').textContent) && /Page 2/.test(document.querySelector('.po-md .po-res').textContent)`), 'a new version, page 2 removed');
    await shot('p2892-c-pdfopt-done.png');
    const j = await call(CF, 'GET', `/api/docs/${DID}/pdfopt`);
    check(j.state === 'done' && j.after < j.before && j.orig === 1, 'the server: done, smaller, the original = version 1 ' + JSON.stringify(j));
    await press('.po-md .foot [data-po="close"]', 'Close');
    check(await wait(`!document.querySelector('.po-md')`), 'the dialog closes');
    // the view read the document again: the downloads of #4806 in "Actions"
    check(await wait(`DC.doc?.pdfopt?.orig === 1`, 80), 'the view knows the original');
    await press('.dv-view [data-dc="actsmore"]', 'Actions again');
    check(await wait(`!!document.querySelector('.dv-view #dc-amore:not([hidden]) .po-dlorig') && !!document.querySelector('.dv-view .po-dlsearch')`), 'Actions: "Download searchable PDF" and "Download original"');
    check(await ev(`/content\\?v=1&dl=1$/.test(document.querySelector('.dv-view .po-dlorig').getAttribute('href'))`), 'the original is version 1');
    const orig = await fetch(B + `api/files/nodes/${DID}/content?v=1&dl=1`, {headers: {Cookie: CF}});
    check(orig.ok && (await orig.arrayBuffer()).byteLength === j.before, 'the original downloads unchanged');
    // the tab History: the new version on top (current), the original below it; "Restore" brings the original back
    await ev(`(typeof dcv_menuClose === 'function' && dcv_menuClose(), 1)`);
    await press('.dv-view [data-dvtab="hist"]', 'tab History');
    check(await wait(`document.querySelectorAll('.dv-view #dv-p-hist .abvrow').length === 2`, 80), 'History: two versions ' + await ev(`document.querySelector('.dv-view #dv-p-hist')?.textContent?.slice(0, 300) || '-'`));
    check(await ev(`(() => { const r = [...document.querySelectorAll('.dv-view #dv-p-hist .abvrow')].map(x => x.textContent); return /v2/.test(r[0]) && /current/.test(r[0]) && /v1/.test(r[1]) && !/current/.test(r[1]); })()`), 'History: v2 (current) above v1');
    check(await ev(`!!document.querySelector('.dv-view #dv-p-hist [data-abv="1"]') && !document.querySelector('.dv-view #dv-p-hist [data-abv="2"]')`), 'History: "Restore" only at the original');
    await shot('p2892-c-pdfopt-history.png');
    await press('.dv-view #dv-p-hist [data-abv="1"]', 'Restore v1');
    let back = {};
    for (let i = 0; i < 80 && back.version !== 3; i++) { back = await call(CF, 'GET', `/api/files/nodes/${DID}`); if (back.version !== 3) await sleep(250); }
    check(back.version === 3, 'the original is the newest version again (v3) ' + back.version);
    const now = await fetch(B + `api/docs/${DID}/file?dl=1`, {headers: {Cookie: CF}});
    check(now.ok && (await now.arrayBuffer()).byteLength === j.before, 'the document is the original again (its bytes)');
    check(await wait(`document.querySelectorAll('.dv-view #dv-p-hist .abvrow').length === 3`, 80), 'History: three versions after the restore');
    // review F7: the optimised version is no longer the current one -> no "original" offered any more
    const after = await call(CF, 'GET', `/api/docs/${DID}/pdfopt`);
    check(after.orig == null, 'after the restore no "Download original" (the original is the current version) ' + JSON.stringify(after.orig));
  }, false);

  console.log(`p2892_c_pdfopt_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
