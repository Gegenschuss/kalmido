// kalmido-suite: fresh
// 2.417.0 B (#3497): three heading levels. Page heads of every area = #top h1 (desktop and 390 px), group labels in plain
// text (no uppercase), dialog sub-heads = .modal h4. The CSS is checked on probe elements in the real layout (Firefox).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2417_b_ui', check, shots: 'P2417B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const PROBE = `(() => {
    const px = e => parseFloat(getComputedStyle(e).fontSize);
    const host = document.createElement('div'); host.id = 'p2417probe';
    host.innerHTML = '<div class="dashhead"><h2>a</h2></div><div class="kidtop"><h2>a</h2></div><div class="shophead"><h2>a</h2></div>'
      + '<div class="office"><div class="ofchead"><h2>a</h2></div></div><div class="clients"><div class="clhead"><h2>a</h2></div></div><div class="calbar"><h2>a</h2></div>'
      + '<div class="menu-list"><div class="mgh">Sell</div><div class="hhead">Head</div></div>'
      + '<div class="modal"><h4>m</h4></div><div class="tcxdlg"><h4>t</h4></div><div class="bwcset"><h4>b</h4></div><div class="envbox"><h4>e</h4></div><div class="wkedlg"><h4>w</h4></div><div class="apb-dlg"><h4>c</h4></div><div class="shvsec"><h4>s</h4></div>'
      + '<div class="dcard"><h3>d</h3></div><div class="bgsec"><h3>d</h3></div><div class="stcard"><h4>d</h4></div>';
    document.body.appendChild(host);
    const q = s => host.querySelector(s);
    const top = px(document.querySelector('#top h1'));
    const out = {top, heads: ['.dashhead h2', '.kidtop h2', '.shophead h2', '.ofchead h2', '.clhead h2', '.calbar h2'].map(s => px(q(s))),
      mgh: getComputedStyle(q('.mgh')).textTransform, hhead: getComputedStyle(q('.hhead')).textTransform,
      modal: px(q('.modal h4')), dlg: ['.tcxdlg h4', '.bwcset h4', '.envbox h4', '.wkedlg h4', '.apb-dlg h4', '.shvsec h4'].map(s => px(q(s))),
      sec: ['.dcard h3', '.bgsec h3', '.stcard h4'].map(s => [px(q(s)), getComputedStyle(q(s)).fontWeight])};
    host.remove(); return out;
  })()`;
  const ready = async ev => { for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(500); };
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = String(w);
      await o.nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await o.nav(B); await ready(ev);
      const p = await ev(PROBE);
      check(p && p.heads.every(x => x === p.top), `${tag}: page heads = #top h1 ${JSON.stringify(p)}`);
      check(p && p.top === (w < 768 ? 19 : 24), `${tag}: #top h1 size ${p && p.top}`);
      check(p && p.mgh === 'none' && p.hhead === 'none', `${tag}: menu group labels without uppercase`);
      check(p && p.dlg.every(x => x === p.modal), `${tag}: dialog sub-heads = .modal h4 ${JSON.stringify(p)}`);
      check(p && p.sec.every(([s, wt]) => s === 14 && Number(wt) >= 600), `${tag}: section heads 14px / 600 ${JSON.stringify(p && p.sec)}`);
      await shot(`p2417b-${w}.png`);
    }, w < 768);
  }
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
