// 2.69.0 UI tests of part A (#1846; own container, start.sh). jsdom:
// - documents settings: the two ways (address / export ZIP) with the hint how to make the export
// - an export ZIP (built here with Python's zipfile, invented contents) uploaded in parts with progress, then the same
//   preview with the mapping and the exact size, the import, the result line "Last import from a ZIP"
// - phone width: the ZIP way is there and usable
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore',
  env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8= -e KALMIDO_PAPERLESS_ZIP_CHUNK_KB=64'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

// an export of document_exporter: manifest.json + two PDFs (with random bytes after them: the ZIP spans several 64 KB parts)
const ZIP = path.join(DATA, 'p269a-export.zip');
execFileSync('python3', ['-c', `
import io, json, random, sys, zipfile
rnd = random.Random(1846)
def pdf(t):
    s = f"BT /F1 12 Tf 40 700 Td ({t}) Tj ET".encode()
    o = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
         b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
         b"<< /Length %d >>\\nstream\\n" % len(s) + s + b"\\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\\n", []
    for i, x in enumerate(o, 1):
        offs.append(len(out)); out += b"%d 0 obj\\n" % i + x + b"\\nendobj\\n"
    x = len(out)
    out += b"xref\\n0 6\\n0000000000 65535 f \\n" + b"".join(b"%010d 00000 n \\n" % f for f in offs)
    out += b"trailer\\n<< /Size 6 /Root 1 0 R >>\\nstartxref\\n%d\\n%%%%EOF\\n" % x
    return out + b"%" + bytes(rnd.getrandbits(8) for _ in range(90000))
d = lambda pk, title, fn, tags: {"model": "documents.document", "pk": pk, "fields": {"title": title, "content": title + " text", "created": "2025-04-01",
     "correspondent": None, "document_type": None, "tags": tags, "archive_serial_number": None, "original_filename": fn, "mime_type": "application/pdf"},
     "__exported_file_name__": fn}
man = [{"model": "documents.tag", "pk": 1, "fields": {"name": "Keep", "match": "", "matching_algorithm": 0, "is_insensitive": True}},
       {"model": "documents.tag", "pk": 2, "fields": {"name": "Drop", "match": "", "matching_algorithm": 0, "is_insensitive": True}},
       d(1, "Zip letter one", "0001.pdf", [1]), d(2, "Zip letter two", "0002.pdf", [2])]
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("export/manifest.json", json.dumps(man))
    z.writestr("export/0001.pdf", pdf("Zip letter one"))
    z.writestr("export/0002.pdf", pdf("Zip letter two"))
`, ZIP]);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});

  // ================= the two ways (2.87.9 #1936: in Settings > Integrations)
  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  w.eval(`settingsModal('paperless')`);
  const slot = () => d.querySelector('.smodal .pl-slot');
  await until(() => slot()?.querySelector('[data-pl="zip-pick"]'));
  const tx = slot()?.textContent || '';
  check(/Connect by address/.test(tx) && /From a Paperless-ngx export \(ZIP\)/.test(tx) && /document_exporter/.test(tx), 'settings: both ways, with how to make the export');
  check(slot()?.querySelector('#pl-url') && slot()?.querySelector('#plh-file[accept*="zip"]'), 'settings: the address form and the ZIP file picker');

  // ================= upload in parts -> the preview -> the import
  w.__zip = new w.File([fs.readFileSync(ZIP)], 'export-2026.zip', {type: 'application/zip'});
  w.eval('plh_upload(window.__zip)');
  const prog = await until(() => /Uploading|Checking the export/.test(slot()?.textContent || '') || d.querySelector('.pl-pmd'), 40);
  check(prog, 'the upload shows its progress');
  const pm = await until(() => d.querySelector('.pl-pmd [data-plp="start"]') && d.querySelector('.pl-pmd'), 100);
  check(pm && /2 documents in Paperless-ngx/.test(pm.textContent), 'after the upload: the same preview, counting the documents');
  check(pm && /Needs .* of storage/.test(pm.textContent), 'the preview names the size');
  const rows = [...(pm?.querySelectorAll('.pl-map') || [])];
  check(rows.length === 2, 'one row per tag');
  const drop = rows.find(li => /Drop/.test(li.textContent));
  if (drop) { const s = drop.querySelector('select'); s.value = 'skip'; s.dispatchEvent(new w.Event('change', {bubbles: true})); }
  pm?.querySelector('[data-plp="start"]').click();
  // 2.87.9 (#1940): the import first names its target
  await until(() => d.querySelector('.itc-dlg [data-cd="yes"]'));
  d.querySelector('.itc-dlg [data-cd="yes"]')?.click();
  await until(() => /Last import from a ZIP: 2 new/.test(slot()?.textContent || ''), 150);
  check(/Last import from a ZIP: 2 new/.test(slot()?.textContent || ''), 'the result line ' + (slot()?.textContent || '').slice(0, 300));
  const docs = (await call('GET', '/api/docs?ws=private')).docs || [];
  check(docs.length === 2 && docs.some(x => x.name === 'Zip letter one.pdf'), 'two documents came in ' + JSON.stringify(docs.map(x => x.name)));
  const two = docs.find(x => x.name === 'Zip letter two.pdf');
  check(two && !(two.tags || []).length, 'the left out tag did not come');
  check(slot()?.querySelector('[data-pl="zip-pick"]'), 'after the run: another ZIP can be chosen');
  w.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), f = m.document;
  m.eval(`settingsModal('paperless')`);  // 2.87.9 (#1936): Settings > Integrations
  check(await until(() => f.querySelector('.smodal .pl-slot [data-pl="zip-pick"]')), 'phone: the ZIP way is there');
  m.close();

  console.log(`p269_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
