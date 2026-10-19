// 2.122.4 C UI tests (own container, Firefox 390 touch): phone sizes, measured on real CSS with small injected markup.
// #2326 office settings select is 44 px (iOS ignores min-height: the rule sets height; Firefox with a coarse pointer takes the same path),
// #2348 the contact import notice lies below dialogs, #2217 video review targets >= 44 px (marker, time button via ::before hit
// area probed with elementFromPoint, version select), #2223 bookmark detail: description / note full width, tag target 44 px.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21224_c_ui', check, shots: 'P21224C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21224C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  await firefox(async o => {
    const {cmd, ev, ctx} = o, tag = '390';
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#bookmarks');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#view')`).catch(() => false)); i++) await sleep(300);
    await sleep(500);
    await ev(`Promise.all(['office', 'contacts', 'videorev', 'bookmarks'].map(f => loadCss(f))).then(() => 1)`);
    const g = await ev(`(() => {
      const add = h => { const d = document.createElement('div'); d.innerHTML = h; if (d.firstElementChild.classList.contains('modal')) { document.body.appendChild(d.firstElementChild); return document.body.lastElementChild; } d.style.cssText = 'position:fixed;top:0;left:0;width:100%;z-index:9000;background:#fff'; document.body.appendChild(d); return d; };
      const out = {};
      const a = add('<div class="ofcset"><div class="row"><label for="t1">x</label><select id="t1"><option>a</option></select></div></div>');
      out.sel = a.querySelector('select').getBoundingClientRect().height; a.remove();
      const b = add('<div class="ctimp" id="t2">n</div>'); const m3 = add('<div class="modal" id="t3"><div class="card"></div></div>');
      out.zi = [+getComputedStyle(b.querySelector('.ctimp')).zIndex, +getComputedStyle(m3).zIndex]; b.remove(); m3.remove();
      const c = add('<div class="vdrtl" style="margin:3rem 1rem"><button class="vdrmk" style="left:50%"></button></div><div class="vdrch" style="margin:1rem"><button class="vdrtc">0:12</button></div><div class="vdrvsel"><select><option>V1</option></select></div>');
      const probe = (el, dx, dy) => { el.scrollIntoView({block: 'center'}); const r = el.getBoundingClientRect(); const hit = document.elementFromPoint(r.left + r.width / 2 + dx, r.top + r.height / 2 + dy); if (hit !== el) (out.dbg = out.dbg || []).push((hit ? hit.tagName + '.' + hit.className : 'null') + ' @' + Math.round(r.top) + ',' + Math.round(r.left)); return hit === el; };
      const mk = c.querySelector('.vdrmk'), tc = c.querySelector('.vdrtc');
      out.mk = [probe(mk, 0, 0), probe(mk, 0, 20), probe(mk, 0, -20), probe(mk, 20, 0), probe(mk, -20, 0)];
      const th = tc.getBoundingClientRect().height; out.tc = [th, probe(tc, 0, th / 2 + 3), probe(tc, 0, -th / 2 - 3)];
      out.vs = c.querySelector('select').getBoundingClientRect().height; c.remove();
      const d = add('<div class="bmdlg"><div class="card" style="box-sizing:border-box;width:100%;padding:1.25rem"><div class="row"><label for="t4">Description</label><textarea id="t4" rows="2"></textarea></div><div class="bmtags"><button class="bmtag">tag</button></div></div></div>');
      out.ta = [d.querySelector('textarea').getBoundingClientRect().width, d.querySelector('.card').getBoundingClientRect().width];
      const tg = d.querySelector('.bmtag'), tr = tg.getBoundingClientRect();
      out.tag = [tr.height, probe(tg, 0, tr.height / 2 + 3), probe(tg, 0, -tr.height / 2 - 3)];
      return out; })()`);
    check(g.sel >= 43.5, `${tag}: #2326 office select is 44 px ` + JSON.stringify(g.sel));
    check(g.zi[0] < g.zi[1], `${tag}: #2348 import notice below the dialog ` + JSON.stringify(g.zi));
    check(g.mk.every(Boolean), `${tag}: #2217 timeline marker has a 44 px target ` + JSON.stringify(g.mk) + JSON.stringify(g.dbg));
    check(g.tc[0] < 40 && g.tc[1] && g.tc[2], `${tag}: #2217 time button target grows without growing the look ` + JSON.stringify(g.tc));
    check(g.vs >= 43.5, `${tag}: #2217 version select 44 px ` + JSON.stringify(g.vs));
    check(g.ta[0] >= g.ta[1] - 60, `${tag}: #2223 description uses the full width ` + JSON.stringify(g.ta));
    check(g.tag[1] && g.tag[2], `${tag}: #2223 tag target reaches 44 px ` + JSON.stringify(g.tag) + JSON.stringify(g.dbg));
  }, true);
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
