// 2.742.0 UI test, part C (#4862): the tag field of a document (tagsel.js tf_html), jsdom, own container (start.sh),
// kalmido-suite: fresh
// invented names only. P2742C_NOSTART=1 = the container runs.
// - the field: the tags as pills with an x, a text field behind them, no <datalist>; combobox + listbox + aria-activedescendant
// - one letter: its own list with the known tags of the workspace (the start first, then within; the hit in bold), the
//   best one marked; "New: …" as the last row; the arrow keys move the mark, Enter / Tab take it, a comma makes a new tag
// - Backspace in the empty field takes the last pill away; the x takes one away; Esc closes the list, not the view
// - every change saves at once (PATCH, data-dcp=tags) with the view's undo; a reload shows the saved pills
// - names are text: a tag with markup in its name stays text in the pills and in the list
// - one value (single): a second name replaces the first (the mode the sender / type field will use later)
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2742C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const type = (w, el, v) => { el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

function pdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${st.length} >>\nstream\n${st}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
const tagsOf = async id => ((await call('GET', `/api/docs/${id}`)).tags || []).map(t => t.name).sort().join('|');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('letter.pdf', ['Example Insurance Ltd', 'Policy letter', 'Date 01.09.2026']);
  const D2 = await upload('other.pdf', ['Sample Utility Co', 'Meter reading', 'Date 03.10.2026']);
  // the known tags of the workspace come from another document; one with markup in its name
  const XSS = '<img alt=x data-bad=1>';  // no letter s: the first list ("s") must not hold it
  check((await call('PATCH', `/api/docs/${D2}`, {tags: ['Steuer', 'Versicherung', 'Haus', 'Garten', XSS]})).status === 200, 'known tags set on another document');
  await call('PATCH', `/api/docs/${D1}`, {tags: []});

  const w = await boot({user: 'alice', hash: `docs/${D1}`}), d = w.document;
  const fld = () => d.querySelector('.dv-view .tfld[data-tf="dc-tags"]'), inp = () => d.querySelector('.dv-view #dc-tags');
  const lb = () => d.querySelector('body > .tflb'), opts = () => [...(lb()?.querySelectorAll('[role="option"]') || [])];
  const pills = () => [...(fld()?.querySelectorAll('.tfp') || [])].map(p => p.dataset.tfv).join('|');
  check(await until(() => fld() && inp() && w.eval(`DC.set?.tags?.length >= 5`)), 'the view of the document shows the tag field');
  check(inp()?.getAttribute('role') === 'combobox' && inp()?.getAttribute('aria-autocomplete') === 'list' && !inp()?.hasAttribute('list') && !fld()?.querySelector('datalist'), 'the field: a combobox, no datalist');
  check(d.querySelector('.dv-view label[for="dc-tags"]'), 'its label names the text field');

  // ================= one letter: the list
  type(w, inp(), 's');
  check(await until(() => opts().length), 'one letter opens the list');
  const names = () => opts().map(o => o.textContent.trim());
  check(names()[0] === 'Steuer', 'the start first: ' + names().join(', '));
  check(names().indexOf('Versicherung') > 0 && names().indexOf('Haus') > 0 && names().indexOf('Garten') < 0, 'then the ones containing the letter, not the others');
  check(/New: s/.test(names()[names().length - 1]) && opts()[opts().length - 1].classList.contains('tfnew'), '"New: …" as the last row');
  check(opts()[0].querySelector('b')?.textContent === 'S', 'the hit in bold');
  check(lb()?.getAttribute('role') === 'listbox' && inp().getAttribute('aria-expanded') === 'true' && inp().getAttribute('aria-controls') === lb()?.id, 'listbox, aria-expanded, aria-controls');
  check(inp().getAttribute('aria-activedescendant') === opts()[0].id && opts()[0].getAttribute('aria-selected') === 'true', 'the best hit is marked (aria-activedescendant)');
  keyOn(w, inp(), 'ArrowDown');
  const second = names()[1];
  check(inp().getAttribute('aria-activedescendant') === opts()[1].id, 'ArrowDown moves the mark');
  keyOn(w, inp(), 'Enter');
  check(await until(async () => (await tagsOf(D1)) === second), 'Enter takes the marked tag and saves it: ' + second);
  check(pills() === second && inp().value === '' && !lb(), 'a pill, the field empty, the list closed');
  check(d.activeElement === inp(), 'the focus stays in the field');

  // a comma makes a new tag
  type(w, inp(), 'Brandneu,');
  check(await until(async () => (await tagsOf(D1)) === [second, 'Brandneu'].sort().join('|')), 'a comma makes a new tag and saves it');
  check(await until(() => pills().split('|').sort().join('|') === [second, 'Brandneu'].sort().join('|')), 'two pills (in the order the server keeps)');
  // Tab takes the marked one
  type(w, inp(), 'gar');
  check(await until(() => names()[0] === 'Garten'), 'the list for "gar"');
  keyOn(w, inp(), 'Tab');
  check(await until(async () => (await tagsOf(D1)).includes('Garten')), 'Tab takes the marked tag');
  // Enter on "New: …" (arrow up from the first row = the last row)
  type(w, inp(), 'Haus2');
  check(await until(() => opts().length === 1 && /New: Haus2/.test(names()[0])), 'a name nobody has: only "New: …"');
  keyOn(w, inp(), 'Enter');
  check(await until(async () => (await tagsOf(D1)).includes('Haus2')), 'Enter on "New: …" makes the tag');
  check(await until(() => pills().split('|').sort().join('|') === [second, 'Brandneu', 'Garten', 'Haus2'].sort().join('|')), 'four pills: ' + pills());

  // Backspace in the empty field: the last pill goes; undo puts it back
  const last = pills().split('|').pop();
  keyOn(w, inp(), 'Backspace');
  check(await until(async () => !(await tagsOf(D1)).split('|').includes(last)), 'Backspace in the empty field takes the last pill away: ' + last);
  check(await until(() => /Saved/.test(d.querySelector('.dv-view .dv-saved')?.textContent || '')), '"Saved" with undo in the head');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await tagsOf(D1)).split('|').includes(last)), 'undo puts the tag back on the server');
  check(await until(() => pills().split('|').includes(last)), '... and the pill');
  // the x of a pill
  click(w, fld().querySelector('.tfp[data-tfv="Brandneu"] .tfx'));
  check(await until(async () => !(await tagsOf(D1)).includes('Brandneu')), 'the x takes one tag away');
  // Esc closes the list, not the view
  type(w, inp(), 'v');
  check(await until(() => lb()), 'the list open again');
  keyOn(w, inp(), 'Escape');
  check(!lb() && w.location.hash === `#docs/${D1}` && d.querySelector('.dv-view'), 'Esc closes the list, the view stays');
  inp().value = '';
  // names are text
  type(w, inp(), 'img');
  check(await until(() => opts().length), 'the list for the tag with markup');
  check(!lb().querySelector('img, [data-bad]') && names().some(n => n === XSS), 'a name with markup stays text in the list: ' + JSON.stringify([names(), w.eval('TFLD.all.get("dc-tags")'), w.eval('DC.set.tags.map(t => t.name)')]));
  keyOn(w, inp(), 'Enter');
  check(await until(() => fld()?.querySelector(`.tfp[data-tfv="${XSS.replace(/"/g, '\\"')}"]`)), 'taken as a pill');
  check(!fld().querySelector('img, [data-bad]'), '... as text, not markup');
  check(await until(async () => (await tagsOf(D1)).includes(XSS)), '... and saved');
  const saved = await tagsOf(D1);
  w.close();

  // ================= a reload shows the saved pills
  const w2 = await boot({user: 'alice', hash: `docs/${D1}`}), d2 = w2.document;
  const p2 = await until(() => d2.querySelector('.dv-view .tfld[data-tf="dc-tags"] .tfp') && [...d2.querySelectorAll('.dv-view .tfld .tfp')].map(p => p.dataset.tfv).sort().join('|'));
  check(p2 === saved, 'after a reload the pills are the saved tags: ' + p2 + ' / ' + saved);
  // one value: a second name replaces the first (no save path: a free test field)
  w2.eval(`{ const b = document.createElement('div'); b.id = 'tf1test'; b.innerHTML = tf_html({id: 'tf1-in', vals: ['Alpha'], all: ['Beta', 'Gamma'], single: true}); document.body.appendChild(b); }`);
  const i1 = d2.querySelector('#tf1-in');
  type(w2, i1, 'be');
  await until(() => d2.querySelector('body > .tflb [role="option"]'));
  keyOn(w2, i1, 'Enter');
  check([...d2.querySelectorAll('#tf1test .tfp')].map(p => p.dataset.tfv).join('|') === 'Beta' && d2.querySelector('#tf1test .tfval').value === 'Beta', 'one value: the new one replaces the old one');
  w2.close();

  console.log(`p2742_c_tagpills_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
