// 2.769.0 A (#5339, #5350) UI test (Firefox, touch), fresh DB:
// kalmido-suite: fresh
// #5339 the path line above an open workspace in "All": "All workspaces /" sits on the same top / height / baseline gap as
//       the other path links (it was an inline anchor: other height) - at 320, 460 and 1280 px
// #5350 a tap on the toast's Close never reaches the row below: (a) the toast's timer runs out while the finger is down,
//       (b) the tap lands on the toast's old place right after it went away
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2769_a_pfad_toast_ui', check, shots: 'P2769A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done', whatsnew_on: '0'})});

  await firefox(async ({cmd, ev, nav, ctx, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    check(await until(`typeof toast === 'function' && typeof spo_upHtml === 'function' && !!document.querySelector('#view')`), 'the app is up');

    // ---- #5339: the path line, measured next to a button link
    for (const w of [320, 460, 1280]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 844}});
      const m = await ev(`(() => { document.getElementById('p2769-pl')?.remove();
        const n = document.createElement('div'); n.id = 'p2769-pl'; n.style.cssText = 'position:fixed;top:60px;left:0;right:0;z-index:5';
        n.innerHTML = '<nav class="abcrumbs">' + spo_upHtml('ablage') + '<button type="button" class="linkbtn" data-ab="space">Private</button><span class="abcsep">/</span><span class="abccur">Docs</span></nav>';
        document.body.appendChild(n);
        const a = n.querySelector('[data-spovup]'), b = n.querySelector('button.linkbtn:not([data-spovup])'), ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        const sep = n.querySelector('.abcsep').getBoundingClientRect();
        return {tag: a.tagName, ta: Math.round(ra.top * 10) / 10, tb: Math.round(rb.top * 10) / 10, ha: Math.round(ra.height * 10) / 10, hb: Math.round(rb.height * 10) / 10,
          gap1: Math.round((sep.left - ra.right) * 10) / 10, gap2: Math.round((rb.left - n.querySelectorAll('.abcsep')[0].getBoundingClientRect().right) * 10) / 10}; })()`);
      check(m.tag === 'BUTTON' && m.ta === m.tb && m.ha === m.hb && m.gap1 === m.gap2, `#5339 at ${w}px: the same top / height / gap ${JSON.stringify(m)}`);
    }
    await ev(`document.getElementById('p2769-pl')?.remove()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});

    // ---- #5350: a row of its own under the toast, counting clicks
    const SETUP = `(() => { document.getElementById('p2769-row')?.remove(); window.__row = 0;
      toast('Task done', () => {}, 700);
      const t = document.querySelector('#toast'), r = t.getBoundingClientRect(), x = document.createElement('button');
      x.id = 'p2769-row'; x.style.cssText = 'position:fixed;z-index:1;left:0;right:0;top:' + (r.top - 80) + 'px;height:' + (r.height + 160) + 'px';  // wide: the toast's entry animation may still move it
      x.onclick = () => { window.__row++; }; document.body.appendChild(x);
      const q = t.querySelector('button.tx').getBoundingClientRect(); return {x: Math.round(q.left + q.width / 2), y: Math.round(q.top + q.height / 2)}; })()`;
    const tap = async (p, hold) => {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
    };
    // (a) the finger stays down longer than the toast's time (700 ms)
    let p = await ev(SETUP);
    await until(`!!document.querySelector('#toast:not(.hidden)') && document.querySelector('#toast').getAnimations().length === 0`);
    p = await ev(`(() => { const q = document.querySelector('#toast button.tx').getBoundingClientRect(); return {x: Math.round(q.left + q.width / 2), y: Math.round(q.top + q.height / 2)}; })()`);
    await tap(p, 1200);
    check(await until(`document.querySelector('#toast').classList.contains('hidden')`), '#5350 (a): the tap closed the toast');
    await new Promise(r => setTimeout(r, 400));
    check(await ev(`window.__row`) === 0, '#5350 (a): the row below got no click (' + await ev(`window.__row`) + ')');
    // (b) the toast is gone, the tap lands on its old place right after (guard window widened: the browser needs time)
    await ev(`(() => { TOAST_GUARD_MS = 8000; })()`);
    await ev(SETUP);
    await until(`!!document.querySelector('#toast:not(.hidden)')`);
    p = await ev(`(() => { const q = document.querySelector('#toast button.tx').getBoundingClientRect(); return {x: Math.round(q.left + q.width / 2), y: Math.round(q.top + q.height / 2)}; })()`);
    await ev(`document.querySelector('#toast button.tx').click()`);
    await tap(p, 50);
    await new Promise(r => setTimeout(r, 300));
    check(await ev(`window.__row`) === 0, '#5350 (b): a tap on the old place right after the hide reached no row (' + await ev(`window.__row`) + ')');
    // after the guard window a tap on the row works again
    await ev(`(() => { TOAST_GUARD_MS = 0; })()`);
    await tap(p, 50);
    check(await until(`window.__row === 1`), '#5350: later the row takes its click again');
  }, true);

  console.log(`p2769_a_pfad_toast_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2769_a_pfad_toast_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
