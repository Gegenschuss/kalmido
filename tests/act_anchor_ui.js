// 2.551.0 (#4599), jsdom, invented data only: the data-act test anchor helpers of tests/boot.js (actName, untilAct) and tests/ff.js (act)
// - the anchor name follows the i18n key: lower case, runs of non-letters/digits -> one '-', none at the ends
// - untilAct waits for the element to appear (a real state, no fixed time) and gives null for a missing anchor
// kalmido-suite: fresh
const {boot, B, actName, untilAct} = require('./boot');
const ffAct = require('./ff').act;
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  for (const [k, want] of [['Add to favourites', 'add-to-favourites'], ['  Delete…  ', 'delete'], ['New task (T)', 'new-task-t'], ['Ärger & Öl', 'ärger-öl'], ['a--b', 'a-b'], ['x1', 'x1']])
    check(actName(k) === want, `actName(${JSON.stringify(k)}) = ${actName(k)}`);
  check(actName(actName('Add to favourites')) === 'add-to-favourites', 'a ready-made name stays as it is');

  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const w = await boot({user: 'alice'}), d = w.document;
  check(await untilAct(w, 'No such anchor here', 300) === null, 'untilAct gives null for a missing anchor');
  setTimeout(() => { const b = d.createElement('button'); b.dataset.act = 'add-to-favourites'; b.textContent = 'Anything'; d.body.append(b); }, 150);
  const el = await untilAct(w, 'Add to favourites');
  check(el && el.textContent === 'Anything', 'untilAct waits for the anchor and finds it by the i18n key, whatever its text');

  // ff.js act(): the Firefox helper clicks via the page's evaluate; here a fake evaluate on the jsdom page
  let clicked = 0; el.addEventListener('click', () => clicked++);
  const ev = async expr => w.eval(expr);
  check(await ffAct(ev, 'Add to favourites', {n: 2}) === true && clicked === 1, 'ff act() finds and clicks the anchor');
  check(await ffAct(ev, 'Missing one', {n: 1}) === false, 'ff act() reports false when the anchor is missing');
  w.close();
  console.log(`act_anchor_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
