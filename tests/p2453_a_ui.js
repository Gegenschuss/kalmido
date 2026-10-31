#!/usr/bin/env node
// kalmido-suite: fresh
// 2.453.0 UI test (#3840), own container (start.sh), Firefox on a touch screen at 360 px, real layout:
// - the message is as wide as its content: "Gespeichert" with Undo and Close stays on one line, no word split
// - a long message with Undo stays inside the screen, its buttons whole, a word is not split while it fits a line
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2453_a', check, shots: 'P2453A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/admin/setup', {method: 'POST', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', modules: []})});
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done'})});

  await firefox(async ({cmd, ev, ctx, nav, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 780}});
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B);
    await until(`!!document.querySelector('#toast') && typeof toast === 'function' && !!document.querySelector('#view').children.length`);
    // the box of the text and how many lines it fills; a word split shows as a text box as wide as a line but with a second line
    const show = msg => ev(`(() => { toast(${JSON.stringify(msg)}, () => {}, 60000);
      const el = document.querySelector('#toast'), sp = el.querySelector('span'), b = el.getBoundingClientRect(), r = document.createRange();
      r.selectNodeContents(sp);
      const tops = new Set([...r.getClientRects()].map(x => Math.round(x.top)));
      return {left: b.left, right: b.right, w: b.width, lines: tops.size, shown: Math.round(sp.getBoundingClientRect().height / (parseFloat(getComputedStyle(sp).lineHeight) || 1)),
        btn: [...el.querySelectorAll('button')].every(x => { const q = x.getBoundingClientRect(); return q.width > 0 && q.left >= b.left && q.right <= b.right + 1; })}; })()`);
    const a = await show('Gespeichert');
    check(a.lines === 1, '#3840: "Gespeichert" with Undo and Close on one line: ' + JSON.stringify(a));
    check(a.w > 180, '#3840: the message is wider than half of the screen when its content needs it: ' + a.w);
    check(a.left >= 0 && a.right <= 360, '#3840: short message inside the screen: ' + JSON.stringify(a));
    check(a.btn, '#3840: short message: buttons whole');
    const b = await show('Die Aufgabe wurde in die Liste Rechnungsversand verschoben und bleibt dort, bis jemand sie abhakt');
    check(b.left >= 0 && b.right <= 360, '#3840: long message inside the screen: ' + JSON.stringify(b));
    check(b.btn, '#3840: long message: buttons whole');
    check(b.shown <= 2, '#3840: long message shows at most two lines: ' + b.shown);  // the range also counts the lines the clamp hides
  }, true);

  console.log(`p2453_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
