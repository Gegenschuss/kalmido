// p2680_c_pointer_ui -- what tests/ff.js's touch switch gives Firefox, and what the machine's own Firefox reports
// kalmido-suite: nodata
// 2.680.0 C (#5138 #5139 #5140 #5141 #5142 #5143 #5144): six UI suites were red in the CI of 2.668 (and on the Mac's VM). ff.js
// starts Firefox without a pointer setting when a suite passes no `touch`, so Firefox takes the machine's own: headless, without
// an input device (GitHub runner, the Mac's VM), that is hover: none / pointer: none, and since #5082 / #5085 the app's finger
// switches (isTouch(), isTouchUi(), CSS (hover:none)) turn on - no draggable rows, wiki pages read-first, no autofocus. Those
// suites now pass touch: false. No server, only about:blank:
// - touch: false matches (hover: hover) and (pointer: fine) - the mouse the six suites ask for
// - touch: true matches (pointer: coarse) and (hover: none)
// - the machine's own values (touch undefined) stand on the summary line, so a CI log shows what the runner reports
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2680_c_pointer_ui', check, lazy: true, allWs: true});
const MQ = `(() => { const m = q => matchMedia(q).matches; return {hover: m('(hover: hover)'), nohover: m('(hover: none)'), fine: m('(pointer: fine)'),
  coarse: m('(pointer: coarse)'), none: m('(pointer: none)'), anyHover: m('(any-hover: hover)'), touchEvents: 'ontouchstart' in window}; })()`;
const seen = {};
const probe = touch => firefox(async ({ev}) => { seen[String(touch)] = await ev(MQ); }, touch);

(async () => {
  for (const t of [undefined, false, true]) await probe(t);
  const m = seen.false || {};
  check(m.hover === true && m.nohover === false, `touch false: (hover: hover), not (hover: none) ${JSON.stringify(m)}`);
  check(m.fine === true && m.coarse === false && m.none === false, `touch false: (pointer: fine) ${JSON.stringify(m)}`);
  const t = seen.true || {};
  check(t.coarse === true && t.nohover === true && t.hover === false, `touch true: a finger (pointer: coarse, hover: none) ${JSON.stringify(t)}`);
  // on the summary line: run_all.sh keeps only FAIL and summary lines
  console.log(`p2680_c_pointer_ui: ${ok} ok, ${F.length} failed (this machine's Firefox without pointer prefs: ${JSON.stringify(seen.undefined)})`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
