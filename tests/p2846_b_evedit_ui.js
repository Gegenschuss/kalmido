// 2.846.0 UI test, part B (#5465): the event editor is calm and loses nothing silently, jsdom, invented names only:
// kalmido-suite: fresh
// - a new event: title in focus, the people field says "Only you so far" as its placeholder (no loose line above), no
//   availability bar while nobody else is invited; Esc without typing closes at once
// - typed something: Esc, the X, Cancel and a click next to the dialog each ask "Discard changes?"; "Keep editing" keeps the
//   text, "Discard" closes without an event
// - an existing event with a guest outside Kalmido opens and closes again without a question (nothing changed)
// - the all-day switch keeps the own reminders: 30 min chosen, all day on and off -> 30 min again; an all-day choice comes
//   back the same way; saved as chosen
// - "More options" is a fold with an arrow and says what is inside; the time zone is searched by city ("Tokyo" -> Asia/Tokyo,
//   shown "Tokyo (Asia)"), something unknown keeps the zone; saved with the zone
// - the end of a repeat is named "Repeat ends", not "Ends" like the end of the event
// - a guest outside Kalmido on a server without mail: the hint in everyday words (no "server", no "set up")
// - an existing event opened with a mouse: the title has the focus with the caret at the end
// freelancer-matrix: events (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const typeIn = (w, el, v) => { el.focus?.(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const esc = (w, el) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const D1 = dstr(new Date(Date.now() + 86400000));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const G = await call('POST', '/api/events', {title: 'Supplier visit', cal_id: W.id, start: `${D1}T11:00`, end: `${D1}T12:00`, reminders: [15],
    attendees: [{email: 'guest@example.net', name: 'Gerda Gast', partstat: 'needs-action'}]});
  check(W.id && G.id, 'a calendar and an event with a guest on the server');
  const inv = await call('GET', '/api/evinvite');

  const w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  await until(() => d.querySelector('#view [data-act="ev-new"]') && w.eval(`typeof evEditor === 'function'`));
  const editor = () => d.querySelector('.modal.evmodal');
  const ask = () => d.querySelector('.modal.cdlg');
  const openNew = async () => {
    click(w, d.querySelector('#view [data-act="ev-new"]'));
    return until(() => editor()?.querySelector('#ev-rems .evchip') && editor());
  };
  const events = async () => (await call('GET', `/api/events?from=${dstr(new Date(Date.now() - 40 * 86400000))}&to=${dstr(new Date(Date.now() + 40 * 86400000))}`)).items || [];

  // ---- a new event: what it shows
  let md = await openNew();
  check(/New event/.test(md.querySelector('h3').textContent), 'the editor: "New event"');
  check(await until(() => d.activeElement === md.querySelector('#ev-title')), 'a new event starts in its title');
  const ai = md.querySelector('#ev-attin');
  check(/Only you so far/.test(ai.placeholder) && md.querySelector('#ev-atts').hidden && !/Only you\b(?! so far)/.test(md.querySelector('.evatts').textContent),
    'people: "Only you so far" is the placeholder of the field, no loose line above it: ' + ai.placeholder);
  await until(() => w.eval(`typeof efb_draw === 'function'`));  // calabs.js is in: a bar would stand now
  check(!md.querySelector('#ev-fb'), 'a new event without guests: no availability bar');
  const rep = md.querySelector('#ev-repend');
  check(rep.getAttribute('aria-label') === 'Repeat ends' && [...md.querySelectorAll('.evdt .rlab')].map(x => x.textContent).join() === 'Starts,Ends',
    'the end of a repeat is "Repeat ends", the end of the event "Ends"');
  const more = md.querySelector('details.evmore'), sum = more.querySelector('summary');
  check(!more.open && sum.querySelector('.fcar') && /More options/.test(sum.textContent) && /Time zone, status, link/.test(sum.textContent),
    '"More options" is a closed fold with an arrow and says what is inside: ' + sum.textContent);
  check(!md.querySelector('select#ev-tz') && md.querySelector('#ev-tzq')?.value && !/[_/]/.test(md.querySelector('#ev-tzq').value),
    'the time zone is a search field with the city name: ' + md.querySelector('#ev-tzq')?.value);
  // Esc without typing: closes at once
  esc(w, md.querySelector('#ev-title'));
  check(await until(() => !editor()) && !ask(), 'nothing typed: Esc closes without a question');

  // ---- typed: every way out asks first
  md = await openNew();
  typeIn(w, md.querySelector('#ev-title'), 'Dentist appointment');
  esc(w, md.querySelector('#ev-title'));
  const asked = await until(() => ask() && /Discard changes\?/.test(ask().textContent));
  check(asked, 'typed + Esc: "Discard changes?"');
  const clear = () => d.querySelectorAll('.modal').forEach(m => m.remove());  // without the question (old code): on with a clean page
  if (asked) {
  click(w, ask().querySelector('[data-cd="no"]'));
  check(await until(() => !ask()) && editor() && editor().querySelector('#ev-title').value === 'Dentist appointment', '"Keep editing": the editor stays with the text');
  for (const [how, go] of [['the X', () => click(w, editor().querySelector('.lhdr [data-evm="close"]'))],
    ['Cancel', () => click(w, editor().querySelector('.foot [data-evm="close"]'))],
    ['a click next to it', () => editor().dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}))]]) {
    go();
    check(await until(() => ask()), `typed + ${how}: asks first`);
    click(w, ask().querySelector('[data-cd="no"]'));
    check(await until(() => !ask()) && editor()?.querySelector('#ev-title').value === 'Dentist appointment', `${how}, "Keep editing": the text stays`);
  }
  click(w, editor().querySelector('.lhdr [data-evm="close"]'));
  await until(() => ask());
  click(w, ask().querySelector('[data-cd="yes"]'));
  check(await until(() => !editor()), '"Discard": the editor closes');
  } else clear();
  check(!(await events()).some(x => x.title === 'Dentist appointment'), 'discarded: no event made');
  // a person added (no field typed) counts too
  md = await openNew();
  typeIn(w, md.querySelector('#ev-attin'), 'someone@example.org'); click(w, md.querySelector('[data-evm="attadd"]'));
  check(await until(() => md.querySelectorAll('#ev-atts .evatp').length === 1 && !md.querySelector('#ev-atts').hidden && /Name or e-mail/.test(md.querySelector('#ev-attin').placeholder)),
    'a guest added: the chip shows, the placeholder is the plain one again');
  if (inv.mail_ok === false) {
    const h = await until(() => md.querySelector('#ev-invno'));
    check(h && /Guests outside Kalmido do not get an invitation by e-mail/.test(h.textContent) && !/server|set up/i.test(h.textContent),
      'no mail on this server: the hint in everyday words: ' + (h?.textContent || ''));
  } else console.log('note: mail is on in this container, the hint without mail is not shown');
  esc(w, md.querySelector('#ev-attin'));
  check(await until(() => ask()), 'a guest added + Esc: asks first');
  if (ask()) click(w, ask().querySelector('[data-cd="yes"]')); else clear();
  await until(() => !editor());

  // ---- an existing event, nothing changed: closes without a question (its invitation row is drawn again after the server answers)
  const full = await call('GET', `/api/events/${G.id}`);
  w.eval(`evEditor({ev: ${JSON.stringify(full)}})`);
  md = await until(() => editor()?.querySelector('#ev-invrow:not([hidden])') && editor());
  check(md && /Edit event/.test(md.querySelector('h3').textContent) && md.querySelector('#ev-title').value === 'Supplier visit' && /Gerda Gast/.test(md.querySelector('#ev-atts').textContent),
    'the existing event opens with its title and its guest');
  check(await until(() => d.activeElement === md.querySelector('#ev-title')) && md.querySelector('#ev-title').selectionStart === 'Supplier visit'.length,
    'an existing event with a mouse: the title in focus, the caret at the end');
  await until(() => w.eval(`document.querySelector('.evmodal')._evi?.info !== null`));
  click(w, md.querySelector('.foot [data-evm="close"]'));
  check(await until(() => !editor()) && !ask(), 'nothing changed: Cancel closes without a question');

  // ---- all day keeps the own reminders
  md = await openNew();
  typeIn(w, md.querySelector('#ev-title'), 'Workshop');
  const rem = m => md.querySelector(`[data-evrem="${m}"]`);
  const onRems = () => [...md.querySelectorAll('#ev-rems .evchip.on')].map(b => b.dataset.evrem).join();
  click(w, rem('15')); click(w, rem('30'));
  check(onRems() === '30', 'own reminder: 30 min (15 off)');
  const ad = md.querySelector('#ev-allday');
  ad.checked = true; change(w, ad);
  check(rem('-540') && onRems() === '-540', 'all day: the all-day reminders: ' + onRems());
  click(w, rem('-540')); click(w, rem('900'));
  check(onRems() === '900', 'all day: own choice "1 day before at 9:00"');
  ad.checked = false; change(w, ad);
  check(onRems() === '30', 'all day off again: the own 30 min are back: ' + onRems());
  ad.checked = true; change(w, ad);
  check(onRems() === '900', 'all day on again: the own all-day choice is back: ' + onRems());
  ad.checked = false; change(w, ad);

  // ---- the time zone by city
  md.querySelector('details.evmore').open = true;
  const tzq = md.querySelector('#ev-tzq') || d.createElement('input');
  tzq.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  check(await until(() => md.querySelectorAll('#ev-tzl option').length > 50) && [...md.querySelectorAll('#ev-tzl option')].some(o => o.value === 'Tokyo (Asia)'),
    'the search offers cities: "Tokyo (Asia)"');
  change(w, tzq, 'Tokyo');
  check(md.querySelector('#ev-tz').value === 'Asia/Tokyo' && tzq.value === 'Tokyo (Asia)', 'typed "Tokyo": the zone Asia/Tokyo, shown "Tokyo (Asia)"');
  change(w, tzq, 'Nowhere City');
  check(md.querySelector('#ev-tz').value === 'Asia/Tokyo' && tzq.value === 'Tokyo (Asia)', 'something unknown: the zone stays');
  click(w, md.querySelector('[data-evm="save"]'));
  const ws = await until(async () => (await events()).find(x => x.title === 'Workshop'));
  const wf = ws && await call('GET', `/api/events/${ws.eid}`);
  check(wf && !wf.all_day && (wf.reminders || []).join() === '30' && wf.tz === 'Asia/Tokyo', 'saved: timed, the own 30 min, Asia/Tokyo ' + JSON.stringify(wf && {r: wf.reminders, tz: wf.tz, ad: wf.all_day}));
  check(!ask(), 'saving asks nothing');

  w.close();
  console.log(`p2846_b_evedit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
