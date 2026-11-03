// 2.504.0 (#4084), jsdom, invented data only: the test window of tests/boot.js has CSS.escape and CSS.supports
// - escape follows the CSSOM rules and the app's selectors built with it find their element in jsdom
// - supports leaves the vendored libraries on the path they took without a CSS object
// kalmido-suite: fresh
const {boot, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const w = await boot({user: 'alice'}), d = w.document;
  check(w.eval(`typeof CSS`) === 'object', 'the app sees a CSS object');
  const esc = v => w.eval(`CSS.escape(${JSON.stringify(v)})`);
  for (const [v, want] of [['abc-_9', 'abc-_9'], ['1a', '\\31 a'], ['-1a', '-\\31 a'], ['-', '\\-'], ['--x', '--x'], ['a b', 'a\\ b'], ['a"b', 'a\\"b'], ['a:b.c#d', 'a\\:b\\.c\\#d'],
    ['a\\b', 'a\\\\b'], ['a\nb', 'a\\a b'], ['a\x7fb', 'a\\7f b'], ['a\0b', 'a�b'], ['äß€', 'äß€'], ['', '']]) check(esc(v) === want, `CSS.escape(${JSON.stringify(v)}) = ${JSON.stringify(esc(v))}`);
  check(w.eval(`CSS.escape(12)`) === '\\31 2', 'CSS.escape takes a number as text');

  // the way the app uses it: inside an attribute selector and after a #
  const el = d.createElement('i'); d.body.append(el);
  for (const v of ['private', 'org:1', 'a b', 'a"b', 'x.y', 'ä']) {
    el.dataset.cssProbe = v;
    check(d.querySelector(`[data-css-probe="${esc(v)}"]`) === el, `attribute selector finds ${v}`);
  }
  el.id = 'os-name:1';
  check(d.querySelector('#' + esc(el.id)) === el, 'id selector finds an id with a colon');
  el.remove();

  const sup = (...a) => w.eval(`CSS.supports(${a.map(x => JSON.stringify(x)).join(', ')})`);
  check(sup('backdrop-filter', 'blur(1px)') === false, 'pdf.js: no backdrop filter, as without a CSS object');
  check(sup('color', 'red') === true, 'mermaid: a colour jsdom knows counts');
  check(sup('color', 'not-a-colour') === false, 'mermaid: a text that is no colour does not');
  check(sup('(display: grid)') === false, 'the one-argument form answers false');
  w.close();
  console.log(`p2504_a_css_boot_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
