// 2.607.0 B UI tests (#4867, #4612). Own container (start.sh), jsdom, a person WITHOUT an organisation (as
// kalmido-suite: fresh
// tests/freelancer_fixture.py), invented names only.
// - #4867 the date picker has a text field on top (focused, the value selected; on a phone the grid keeps the focus and the
//   field asks for numbers): parseDMY understands 6.11. / 06.11.2026 / 6.11.26 / 61126 / 06112026 / 2026-11-06 / 11/6/2026
//   (by the date order), today / tomorrow / +3 / -2 (de, en); without a year this year, on a due date the next time;
//   31.02. and outside min / max = nothing. Typing moves the month, Enter takes it, an invalid text turns red and takes nothing
// - #4612 a right click on a contact row opens its menu: the name, "Select", Open; "Select" starts the selection
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2607B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const key = (w, el, k) => { const e = new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}); el.dispatchEvent(e); return e; };
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'a person without an organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'contacts'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');

  // ================= #4867 parseDMY
  let w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  await until(() => w.eval(`typeof parseDMY === 'function' && typeof S !== 'undefined' && !!S.settings`));
  const P = (v, o = {}) => w.eval(`parseDMY(${JSON.stringify(v)}, ${JSON.stringify({ref: '2026-11-06', ...o})})`);
  w.eval(`S.settings.date_order = 'dmy'`);
  const dmy = ['6.11.', '06.11.2026', '6.11.26', '6.11.2026', '61126', '061126', '6112026', '06112026', '2026-11-06', '20261106', '6/11/2026', '6-11-2026', ' 6. 11. 2026 '].map(v => [v, P(v)]);
  check(dmy.every(([, x]) => x === '2026-11-06'), 'day first: every form gives 06.11.2026 ' + JSON.stringify(dmy.filter(([, x]) => x !== '2026-11-06')));
  w.eval(`S.settings.date_order = 'mdy'`);
  const mdy = ['11/6/2026', '11/06/26', '110626', '11062026', '2026-11-06', '6.11.2026'].map(v => [v, P(v)]);
  check(mdy.every(([, x]) => x === '2026-11-06'), 'month first (en-US order): 11/6/2026 and the digits ' + JSON.stringify(mdy.filter(([, x]) => x !== '2026-11-06')));
  w.eval(`S.settings.date_order = ''`);
  check(P('1.3.') === '2026-03-01' && P('1.3.', {future: true}) === '2027-03-01' && P('6.11.', {future: true}) === '2026-11-06' && P('7.11.', {future: true}) === '2026-11-07',
    'without a year: this year; on a due date the next 1.3. (today counts as coming) ' + [P('1.3.'), P('1.3.', {future: true}), P('6.11.', {future: true})]);
  w.eval(`S.settings.date_order = 'dmy'`);
  check(P('611') === '2026-11-06' && P('0611') === '2026-11-06' && P('153') === '2026-03-15' && P('15326') === '2026-03-15', 'digits without dots: 611, 0611, 153 (15.3.), 15326 ' + [P('611'), P('153'), P('15326')]);
  w.eval(`S.settings.date_order = ''`);
  check(['2026-11-06', '2027-03-15', '2026-01-02'].every(v => w.eval(`parseDMY(dpTxt('${v}'))`) === v), 'what the field shows reads back as the same day');
  check(P('29.02.', {future: true}) === '2028-02-29' && P('29.2.2028') === '2028-02-29', '29.02. without a year on a due date: the next leap year ' + P('29.02.', {future: true}));
  const words = {heute: '2026-11-06', today: '2026-11-06', morgen: '2026-11-07', Tomorrow: '2026-11-07', 'übermorgen': '2026-11-08', 'day after tomorrow': '2026-11-08', '+3': '2026-11-09', '-2': '2026-11-04', '+ 10': '2026-11-16'};
  check(Object.entries(words).every(([v, x]) => P(v) === x), 'today / tomorrow / +3 / -2 (de, en) ' + JSON.stringify(Object.keys(words).map(v => [v, P(v)])));
  check(P('31.02.2026') === null && P('32.1.') === null && P('1.13.2026') === null && P('abc') === null && P('6.11.2026x') === null && P('') === '' && P('  ') === '',
    'not a date: null (31.02., month 13, letters); empty: ""');
  check(P('1.12.2026', {max: '2026-11-30'}) === null && P('+30', {max: '2026-11-30'}) === null && P('1.11.2026', {min: '2026-11-02'}) === null && P('5.11.2026', {min: '2026-11-02', max: '2026-11-30'}) === '2026-11-05',
    'min / max hold for typed dates and words too');

  // ================= #4867 the picker of a date field (computer)
  w.eval(`(() => { const x = document.createElement('div'); x.id = 'tst'; x.innerHTML = dateIn('tst-d', '', {label: 'Test'}) + dateIn('tst-m', '', {label: 'Max', max: '2026-12-31'}) + dateIn('tst-due', '', {label: 'Due'}); document.body.appendChild(x); return 1; })()`);
  d.querySelector('[data-dpfor="tst-d"]').click();
  let din = await until(() => d.activeElement?.id === 'dp-din' && d.activeElement);
  check(din && d.querySelector('#dpop .dpk #dp-din') && d.querySelector('#dpop .dpcal .dph') && d.querySelector('#dpop .dpg [tabindex="0"]'), 'the picker opens with the text field above the month, the field has the focus');
  check(din && din.getAttribute('inputmode') === 'text' && din.value === '' && din.placeholder === w.eval(`dpTxt(today())`), 'computer: a text field, empty field = empty, the placeholder shows today as numbers ' + din?.placeholder);
  type(w, din, '15.03.2027');
  check(await until(() => d.querySelector('#dpop .dpy')?.value === '2027' && d.querySelector('#dpop .dpd.sel')?.dataset.d === '2027-03-15') && d.activeElement === din,
    'typing moves the month along (March 2027, the day marked), the focus stays in the field');
  const ar = key(w, din, 'ArrowRight');
  check(!ar.defaultPrevented && d.activeElement === din && d.querySelector('#dpop'), 'an arrow key in the field stays in the field (not the grid)');
  key(w, din, 'Enter');
  check(await until(() => !d.querySelector('#dpop') && d.querySelector('#tst-d').value === '2027-03-15'), 'Enter takes the typed day, the picker closes');
  check(/15/.test(d.querySelector('[data-dpfor="tst-d"]').textContent) && d.activeElement === d.querySelector('[data-dpfor="tst-d"]'), 'the button shows it and has the focus back');
  // the value comes back selected, an invalid text turns red and takes nothing
  d.querySelector('[data-dpfor="tst-d"]').click();
  din = await until(() => d.activeElement?.id === 'dp-din' && d.activeElement);
  const shown = w.eval(`dpTxt('2027-03-15')`);
  check(din && din.value === shown && din.selectionStart === 0 && din.selectionEnd === shown.length && w.eval(`parseDMY(${JSON.stringify(shown)})`) === '2027-03-15',
    'the field holds the current value (selected) in the form it reads back ' + din?.value);
  type(w, din, '31.02.2027');
  check(din.classList.contains('bad') && din.getAttribute('aria-invalid') === 'true', '31.02. turns the field red');
  key(w, din, 'Enter'); await sleep(50);
  check(d.querySelector('#dpop') && d.querySelector('#tst-d').value === '2027-03-15', 'Enter on an invalid text takes nothing, the picker stays');
  type(w, din, '6.11.');
  check(!din.classList.contains('bad'), 'a valid text clears the red');
  key(w, din, 'Enter');
  const exp611 = w.eval(`parseDMY('6.11.')`);
  check(await until(() => !d.querySelector('#dpop') && d.querySelector('#tst-d').value === exp611) && /-11-06$/.test(exp611), '"6.11." + Enter sets the 6 November ' + exp611);
  // max holds for typed dates
  d.querySelector('[data-dpfor="tst-m"]').click();
  din = await until(() => d.activeElement?.id === 'dp-din' && d.activeElement);
  type(w, din, '1.1.2027'); key(w, din, 'Enter'); await sleep(50);
  check(din.classList.contains('bad') && d.querySelector('#dpop') && d.querySelector('#tst-m').value === '', 'a typed day after max: red, nothing taken');
  key(w, din, 'Escape');
  // a due date: a day / month that passed this year means the next year
  d.querySelector('[data-dpfor="tst-due"]').click();
  din = await until(() => d.activeElement?.id === 'dp-din' && d.activeElement);
  const y0 = w.eval(`(() => { const y = addDays(today(), -1); return y.slice(8) + '.' + y.slice(5, 7) + '.'; })()`);
  const expDue = w.eval(`(() => { const y = addDays(today(), -1), Y = +today().slice(0, 4), c = Y + y.slice(4); return c < today() ? (Y + 1) + y.slice(4) : c; })()`);
  type(w, din, y0); key(w, din, 'Enter');
  check(await until(() => d.querySelector('#tst-due').value === expDue), 'a due field: yesterday\'s day / month without a year = next year ' + y0 + ' -> ' + d.querySelector('#tst-due').value);
  w.close();

  // ================= #4867 the phone: the grid keeps the focus (no keyboard on its own), the field asks for numbers
  w = await boot({user: 'frida', hash: 'today', mobile: true}); d = w.document;
  await until(() => w.eval(`typeof dateIn === 'function' && typeof S !== 'undefined' && !!S.settings`));
  w.eval(`(() => { const x = document.createElement('div'); x.innerHTML = dateIn('tst-p', '2026-11-06', {label: 'Test'}); document.body.appendChild(x); return 1; })()`);
  d.querySelector('[data-dpfor="tst-p"]').click();
  const cell = await until(() => d.activeElement?.closest?.('#dpop .dpg') && d.activeElement);
  din = d.querySelector('#dpop #dp-din');
  check(d.querySelector('#dpop.sheet') && cell && din && din.getAttribute('inputmode') === 'numeric' && d.activeElement !== din, 'phone: a sheet, the focus on the grid, the field with the number keyboard');
  w.eval(`S.settings.date_order = 'dmy'`);
  din.focus(); type(w, din, '61126'); key(w, din, 'Enter');
  check(await until(() => !d.querySelector('#dpop') && d.querySelector('#tst-p').value === '2026-11-06'), 'phone: "61126" + Enter -> 06.11.2026');
  w.close();

  // ================= #4612 contacts: a right click on a row opens its menu, "Select" on top
  const BK = (await call(CF, 'POST', '/api/books', {name: 'Mine'})).id;
  const fd = new FormData(); fd.append('file', new Blob(['BEGIN:VCARD\r\nVERSION:3.0\r\nUID:p2607-1\r\nFN:Erika Example\r\nN:Example;Erika;;;\r\nEND:VCARD\r\n', 'BEGIN:VCARD\r\nVERSION:3.0\r\nUID:p2607-2\r\nFN:Max Sample\r\nN:Sample;Max;;;\r\nEND:VCARD\r\n'], {type: 'text/vcard'}), 'x.vcf');
  check((await fetch(B + `api/books/${BK}/import`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd})).status === 200, 'two contacts imported');
  w = await boot({user: 'frida', hash: 'contacts'}); d = w.document;
  await until(() => d.querySelectorAll('#view .ctrow[data-ctopen]').length === 2, 60);
  const row = [...d.querySelectorAll('#view .ctrow[data-ctopen]')].find(x => /Erika/.test(x.textContent));
  const cm = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: 10, clientY: 10}); row.dispatchEvent(cm);
  const its = await until(() => { const x = [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(b => b.textContent); return x.length && x; });
  check(cm.defaultPrevented && its && its[0] === 'Erika Example' && its[1] === 'Select' && its.includes('Open') && its.includes('Delete') && d.querySelector('#pop .mhead[disabled]'),
    '#4612: right click = the name as head, "Select", Open, Delete ' + its);
  [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => x.textContent.trim() === 'Select').click();
  check(await until(() => d.querySelector('#ct-sbar') && w.eval('CT.pick && CT.pick.size === 1')), '#4612: "Select" starts the selection with this row');
  w.close();

  console.log(`p2607_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
